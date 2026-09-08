"""固定 outer-fold 的 base expert／Rule／Equal Weight 研究比較。

本模組只讀取 immutable allocation OOC parent 的 base ``oof.i32``、Direct
store 的 ``replay_source.sqlite`` 與已成熟 h5 labels。它不讀 teacher targets，
不重訓 Meta，也不把今日 sector membership 回填到歷史。交易、成交限制與
成本直接重用正式 OOS replay 的整數 bp／Decimal 邏輯；若 Direct source 沒有
PIT sector id，仍會保存各 lane 的 requested 與 blocked/unfilled 證據，並把
該比較標示為 research-only。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN, ROUND_DOWN
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

import numpy as np

from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    MLStorageCapacityBudget,
    StorageCapacityError,
    acquire_heavy_chain_reservation,
    directory_size_bytes,
    heavy_chain_lock_path,
    preflight_capacity,
    release_heavy_chain_reservation,
    resolve_heavy_chain_lock_path,
)
from data_module.portfolio_ml_out_of_core_store import (
    LABEL_FIELDS,
    STORE_SCHEMA_VERSION,
)
from ml_module import allocation_oos_portfolio_replay as replay
from ml_module import allocation_oos_replay_input_builder as replay_input_builder
from ml_module import allocation_replay_causal_volume_sidecar as causal_volume_sidecar
from ml_module.allocation_replay_causal_volume_sidecar import (
    CAUSAL_VOLUME_SIDECAR_POLICY_VERSION,
    CausalVolumeTarget,
    reconstruct_causal_volume20,
)
from ml_module.allocation_oos_replay_input_builder import (
    _ALLOWED_TRADABLE,
    _Bar,
    _Candidate,
    INITIAL_CAPITAL,
    _LaneState,
    _capped_weights,
    _cost,
    _eligible_for_new_position,
    _execute_day,
    _money_minor,
    _parse_datetime,
    _scaled_price,
    _turnover_bp,
    _weights_from_holdings,
)
from ml_module.allocation_out_of_core_training_service import (
    EXPERT_SCHEMA_VERSION,
    EXPERT_VECTOR_WIDTH,
    OOF_DTYPE,
    _NumericStore,
    _read_and_validate_artifact,
)
from ml_module.allocation_training_service import EXPERT_HEAD_IDS


# v7 keeps v6 immutable and adds a read-only cross-year causal volume sidecar.
# v1-v6 outputs are historical experiments and are never rewritten by this
# producer.
COMPARISON_SCHEMA_VERSION = "allocation-base-expert-oos-comparison.v7"
LIQUIDITY_POOL_POLICY_VERSION = "t-minus-one-dollar-volume-top8.v1"
LOT_EXECUTION_POLICY_VERSION = "complete-lot-turnover-cash-participation.v1"
METHOD_FREEZE_VERSION = "base-expert-comparison-method.v7"
_SHA256_PREFIX = "sha256:"
_CASH = "CASH"
_FOLD_ID = "fold-004"
_HORIZON = 5
_ALGORITHM = "ridge_logistic"
_MAX_BUDGET_BYTES = 256 * 1024 * 1024
_ESTIMATED_PERSISTENT_BYTES = 32 * 1024 * 1024
_ESTIMATED_TEMPORARY_BYTES = 32 * 1024 * 1024
_SOURCE_BATCH_SIZE = 500
_MAX_SIGNAL_SYMBOLS = 8
_FUTURE_CONFIRMATORY_FOLD_IDS = ("fold-005",)
_BASE_HEAD = "expected_excess_return_bp"
_BASE_HEAD_POSITION = EXPERT_HEAD_IDS.index(_BASE_HEAD)
_LABEL_RETURN_POSITION = LABEL_FIELDS.index("benchmark_excess_return_bp")


@dataclass(frozen=True)
class AllocationBaseExpertComparisonRequest:
    """一次固定 fold 的 immutable historical research comparison。"""

    parent_training_manifest_path: Path
    output_root: Path
    fold_id: str = _FOLD_ID
    horizon: int = _HORIZON
    algorithms: tuple[str, ...] = (_ALGORITHM,)
    pack_ids: tuple[str, ...] = ()
    batch_size: int = 8_192
    memory_budget_mb: int = 4_096
    persistent_new_bytes_budget: int = _MAX_BUDGET_BYTES
    temporary_peak_bytes_budget: int = _MAX_BUDGET_BYTES
    safety_reserve_bytes: int = 200 * BYTES_PER_GIB
    heavy_lock_path: Path | None = None
    acquire_heavy_lock: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.parent_training_manifest_path, Path):
            raise TypeError("parent_training_manifest_path must be a Path")
        if not isinstance(self.output_root, Path):
            raise TypeError("output_root must be a Path")
        if not isinstance(self.fold_id, str) or not self.fold_id.strip():
            raise ValueError("fold_id is required")
        if self.fold_id != _FOLD_ID:
            raise ValueError("bounded comparison currently requires fold-004")
        if self.horizon != _HORIZON:
            raise ValueError("bounded comparison currently requires h5")
        if self.algorithms != (_ALGORITHM,):
            raise ValueError(
                "bounded comparison requires ridge_logistic only; "
                "the linear OOF scope is explicit"
            )
        if len(set(self.pack_ids)) != len(self.pack_ids):
            raise ValueError("pack_ids must be unique")
        for field_name in (
            "horizon",
            "batch_size",
            "memory_budget_mb",
            "persistent_new_bytes_budget",
            "temporary_peak_bytes_budget",
            "safety_reserve_bytes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.batch_size > 65_536:
            raise ValueError("batch_size must not exceed 65536")
        if self.memory_budget_mb > 4_096:
            raise ValueError("memory budget must not exceed 4096 MB")
        if self.persistent_new_bytes_budget > _MAX_BUDGET_BYTES:
            raise ValueError("persistent comparison budget exceeds 256 MiB")
        if self.temporary_peak_bytes_budget > _MAX_BUDGET_BYTES:
            raise ValueError("temporary comparison budget exceeds 256 MiB")
        if not isinstance(self.acquire_heavy_lock, bool):
            raise TypeError("acquire_heavy_lock must be bool")
        if self.heavy_lock_path is not None and not isinstance(
            self.heavy_lock_path,
            Path,
        ):
            raise TypeError("heavy_lock_path must be a Path or None")


@dataclass(frozen=True)
class AllocationBaseExpertComparisonPublication:
    """比較 artifact 的可審核路徑與 immutable hash。"""

    comparison_path: Path
    comparison_hash: str
    latest_pointer_path: Path
    run_id: str
    output_size_bytes: int
    capacity_preflight: Mapping[str, Any]
    idempotent: bool = False


@dataclass(frozen=True)
class _SelectedRow:
    position: int
    year_ordinal: int
    local_row_index: int
    row_id: str
    candidate: _Candidate
    label_observed: bool
    label_return_bp: int | None
    # Direct writer 的 stored median 只作 parity／缺件證據；研究 sidecar
    # 另外保存跨年 causal window 的重建值，不能混入 parent bytes。
    stored_median_volume_20d_shares: int | None = None
    causal_volume20_median_volume_20d_shares: int | None = None
    causal_volume20_evidence: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class _LaneDefinition:
    lane_id: str
    lane_kind: str
    selection_policy: str
    scenario: str
    pack_id: str | None = None
    algorithm: str | None = None


@dataclass
class _LaneAccumulator:
    definition: _LaneDefinition
    state: _LaneState
    gross_returns_bp: list[int]
    net_returns_bp: list[int]
    net_equities_minor: list[int]
    gross_equities_minor: list[int]
    daily: list[dict[str, Any]]
    turnover_total_bp: int = 0
    transaction_cost_minor: int = 0
    requested_order_count: int = 0
    executed_trade_count: int = 0
    executed_buy_count: int = 0
    executed_sell_count: int = 0
    unfilled_order_count: int = 0
    blocked_order_count: int = 0
    requested_weight_bp: int = 0
    filled_weight_bp: int = 0
    unfilled_weight_bp: int = 0
    label_observed_weight_bp: int = 0
    label_missing_weight_bp: int = 0
    label_weighted_return_sum_bp: Decimal = Decimal(0)
    label_weighted_return_count: int = 0
    cumulative_cost_minor: int = 0
    previous_net_close_minor: int | None = None
    previous_gross_close_minor: int | None = None


def build_allocation_base_expert_comparison(
    request: AllocationBaseExpertComparisonRequest,
) -> AllocationBaseExpertComparisonPublication:
    """執行一次有界比較；所有來源開啟為唯讀，輸出 write-once。"""

    parent_path = request.parent_training_manifest_path.resolve()
    if not parent_path.is_file():
        raise FileNotFoundError(parent_path)
    output_root = request.output_root.resolve()
    parent = _read_json_mapping(parent_path)
    parent_hash = _verify_logical_hash(parent, "manifest_hash")
    store_path = _resolve_store_path(parent_path, parent)
    store_manifest = _read_json_mapping(store_path)
    store_hash = _verify_logical_hash(store_manifest, "manifest_hash")
    if store_manifest.get("schema_version") != STORE_SCHEMA_VERSION:
        raise ValueError("comparison requires portfolio-ml-ooc-store.v3")
    if parent.get("store_manifest_hash") != store_hash:
        raise ValueError("parent/store manifest hash mismatch")
    if parent.get("store_manifest_file_hash") != _file_sha256(store_path):
        raise ValueError("parent/store manifest file hash mismatch")
    _reject_source_output_overlap(parent_path, store_path, output_root)
    resolved_pack_ids = _resolved_pack_ids(request, store_manifest)

    capacity = _capacity_preflight(
        request,
        source_path=store_path,
        output_root=output_root,
        stage="base_expert_comparison_preflight",
    )
    run_id = _comparison_run_id(
        request,
        parent_hash=parent_hash,
        store_hash=store_hash,
        pack_ids=resolved_pack_ids,
        method_freeze_hash=_method_freeze_evidence(
            request=request,
            pack_ids=resolved_pack_ids,
            parent_hash=parent_hash,
            store_hash=store_hash,
        )["method_freeze_hash"],
    )
    comparison_path = output_root / "runs" / run_id / "comparison.json"
    latest_pointer_path = output_root / "latest_comparison.json"
    existing = _load_existing_comparison(
        comparison_path,
        latest_pointer_path,
        parent_hash=parent_hash,
        store_hash=store_hash,
        request=request,
    )
    if existing is not None:
        return AllocationBaseExpertComparisonPublication(
            comparison_path=comparison_path,
            comparison_hash=_required_sha256(
                existing.get("comparison_hash"),
                "comparison_hash",
            ),
            latest_pointer_path=latest_pointer_path,
            run_id=run_id,
            output_size_bytes=directory_size_bytes(output_root),
            capacity_preflight=capacity,
            idempotent=True,
        )

    reservation = None
    if request.acquire_heavy_lock:
        lock_path = resolve_heavy_chain_lock_path(
            parent_path,
            explicit_path=request.heavy_lock_path,
        )
        if lock_path is None:
            lock_path = _default_lock_path(parent_path)
        reservation = acquire_heavy_chain_reservation(lock_path)
        if reservation is None:
            raise StorageCapacityError(
                "comparison heavy-chain reservation unavailable",
                preflight={
                    "stage": "base_expert_comparison_lock",
                    "lock_path": str(lock_path.resolve()),
                    "blockers": ["heavy_chain_reservation_unavailable"],
                },
            )
        try:
            capacity = _capacity_preflight(
                request,
                source_path=store_path,
                output_root=output_root,
                stage="base_expert_comparison_locked_recheck",
            )
            payload = _build_comparison_payload(
                request=request,
                parent=parent,
                parent_path=parent_path,
                parent_hash=parent_hash,
                store_path=store_path,
                store_manifest=store_manifest,
                store_hash=store_hash,
                run_id=run_id,
                capacity=capacity,
            )
            return _publish_comparison(
                payload,
                comparison_path=comparison_path,
                latest_pointer_path=latest_pointer_path,
                output_root=output_root,
                capacity=capacity,
                request=request,
            )
        finally:
            release_heavy_chain_reservation(reservation)

    payload = _build_comparison_payload(
        request=request,
        parent=parent,
        parent_path=parent_path,
        parent_hash=parent_hash,
        store_path=store_path,
        store_manifest=store_manifest,
        store_hash=store_hash,
        run_id=run_id,
        capacity=capacity,
    )
    return _publish_comparison(
        payload,
        comparison_path=comparison_path,
        latest_pointer_path=latest_pointer_path,
        output_root=output_root,
        capacity=capacity,
        request=request,
    )


def preflight_allocation_base_expert_comparison(
    request: AllocationBaseExpertComparisonRequest,
) -> dict[str, Any]:
    """只做來源、selection 與雙 filesystem 容量查核，不取得 lock。"""

    parent_path = request.parent_training_manifest_path.resolve()
    parent = _read_json_mapping(parent_path)
    parent_hash = _verify_logical_hash(parent, "manifest_hash")
    store_path = _resolve_store_path(parent_path, parent)
    store_manifest = _read_json_mapping(store_path)
    store_hash = _verify_logical_hash(store_manifest, "manifest_hash")
    if parent.get("store_manifest_hash") != store_hash:
        raise ValueError("parent/store manifest hash mismatch")
    output_root = request.output_root.resolve()
    _reject_source_output_overlap(parent_path, store_path, output_root)
    capacity = _capacity_preflight(
        request,
        source_path=store_path,
        output_root=output_root,
        stage="base_expert_comparison_preflight",
    )
    selected = _selection_preflight(
        request,
        parent=parent,
        store_manifest=store_manifest,
        parent_path=parent_path,
        store_path=store_path,
    )
    method_freeze = _method_freeze_evidence(
        request=request,
        pack_ids=tuple(selected["pack_ids"]),
        parent_hash=parent_hash,
        store_hash=store_hash,
    )
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": "preflight_passed",
        "parent_training_manifest": str(parent_path),
        "parent_training_manifest_hash": parent_hash,
        "store_manifest": str(store_path),
        "store_manifest_hash": store_hash,
        "fold_id": request.fold_id,
        "horizon": request.horizon,
        "algorithms": list(request.algorithms),
        "pack_ids": list(selected["pack_ids"]),
        "method_freeze": method_freeze,
        "future_confirmatory_scopes": _future_confirmatory_scopes(),
        "selected_oof_row_count": selected["selected_oof_row_count"],
        "selected_oof_artifact_count": selected[
            "selected_oof_artifact_count"
        ],
        "capacity_preflight": capacity,
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }


def _build_comparison_payload(
    *,
    request: AllocationBaseExpertComparisonRequest,
    parent: Mapping[str, Any],
    parent_path: Path,
    parent_hash: str,
    store_path: Path,
    store_manifest: Mapping[str, Any],
    store_hash: str,
    run_id: str,
    capacity: Mapping[str, Any],
) -> dict[str, Any]:
    store = _NumericStore(store_path)
    selection = _select_oof_artifacts(
        request,
        parent=parent,
        parent_path=parent_path,
        store=store,
    )
    fold = _find_fold(store.folds, request.fold_id)
    refs_map = store.open_fold_refs(fold, "test")
    refs = np.asarray(refs_map, dtype=np.int64)
    del refs_map
    if len(refs) != selection["selected_oof_row_count"]:
        raise ValueError("selected OOF row count does not match fold refs")
    _require_replay_source_sidecars(store, refs)
    try:
        rows_by_position = _load_selected_rows(
            store=store,
            refs=refs,
            fold_id=request.fold_id,
        )
        labels, label_masks = store.read_label_batch(refs, request.horizon)
        bars = _load_bars(
            store=store,
            selected=rows_by_position,
        )
        score_vectors = _load_oof_scores(selection["artifacts"])
        payload = _run_lanes(
            request=request,
            rows=rows_by_position,
            labels=np.asarray(labels, dtype=np.int32),
            label_masks=np.asarray(label_masks, dtype=np.uint8),
            bars=bars,
            score_vectors=score_vectors,
            store_manifest=store_manifest,
            parent=parent,
            parent_path=parent_path,
            parent_hash=parent_hash,
            store_hash=store_hash,
            store_manifest_file_hash=_file_sha256(store_path),
            run_id=run_id,
            selection=selection,
            capacity=capacity,
        )
    finally:
        del refs
    return payload


def _run_lanes(
    *,
    request: AllocationBaseExpertComparisonRequest,
    rows: Sequence[_SelectedRow],
    labels: np.ndarray,
    label_masks: np.ndarray,
    bars: Mapping[date, Mapping[str, _Bar]],
    score_vectors: Mapping[str, np.ndarray],
    store_manifest: Mapping[str, Any],
    parent: Mapping[str, Any],
    parent_path: Path,
    parent_hash: str,
    store_hash: str,
    store_manifest_file_hash: str,
    run_id: str,
    selection: Mapping[str, Any],
    capacity: Mapping[str, Any],
) -> dict[str, Any]:
    rows_by_date: dict[date, list[_SelectedRow]] = {}
    for item in rows:
        rows_by_date.setdefault(item.candidate.decision_date, []).append(item)
    decision_dates = tuple(sorted(rows_by_date))
    pack_ids = tuple(str(item) for item in selection["pack_ids"])
    lane_templates = tuple(
        _LaneDefinition(
            lane_id=f"base_{pack_id}_ridge_logistic",
            lane_kind="base_expert_challenger",
            selection_policy="positive_expected_excess_return_bp_top8_capped",
            scenario="template",
            pack_id=pack_id,
            algorithm=_ALGORITHM,
        )
        for pack_id in pack_ids
    ) + (
        _LaneDefinition(
            lane_id="base_mean_ridge_logistic",
            lane_kind="base_expert_challenger_aggregate",
            selection_policy="integer_half_even_mean_positive_score_top8_capped",
            scenario="template",
            algorithm=_ALGORITHM,
        ),
        _LaneDefinition(
            lane_id="causal_rule_research",
            lane_kind="causal_research_rule",
            selection_policy="persisted_t_minus_one_rule_score_top8_capped",
            scenario="template",
        ),
        _LaneDefinition(
            lane_id="equal_weight_t_minus_one_liquidity_pool",
            lane_kind="equal_weight_baseline",
            selection_policy="t_minus_one_liquidity_pool_top8_equal_weight_not_full_universe",
            scenario="template",
        ),
    )
    scenarios = ("strict_sector", "research_no_sector_cap")
    lane_definitions = tuple(
        _LaneDefinition(
            lane_id=f"{scenario}__{template.lane_id}",
            lane_kind=template.lane_kind,
            selection_policy=template.selection_policy,
            scenario=scenario,
            pack_id=template.pack_id,
            algorithm=template.algorithm,
        )
        for scenario in scenarios
        for template in lane_templates
    )
    accumulators = {
        definition.lane_id: _LaneAccumulator(
            definition=definition,
            state=_LaneState(),
            gross_returns_bp=[],
            net_returns_bp=[],
            net_equities_minor=[],
            gross_equities_minor=[],
            daily=[],
        )
        for definition in lane_definitions
    }
    all_basic_candidates = 0
    all_strict_candidates = 0
    all_liquidity_pool_eligible = 0
    all_liquidity_pool_selected = 0
    source_values_hasher = hashlib.sha256()
    for item in rows:
        candidate = item.candidate
        source_values_hasher.update(
            _canonical_json(
                {
                    "position": item.position,
                    "year_ordinal": item.year_ordinal,
                    "local_row_index": item.local_row_index,
                    "row_id": item.row_id,
                    "decision_at": candidate.decision_at.isoformat(),
                    "symbol": candidate.symbol,
                    "source_values_hash": candidate.source_values_hash,
                    "t_minus_one_close_price": (
                        None
                        if candidate.t_minus_one_close_price is None
                        else str(candidate.t_minus_one_close_price)
                    ),
                    "t_minus_one_close_available_at": (
                        None
                        if candidate.t_minus_one_close_available_at is None
                        else candidate.t_minus_one_close_available_at.isoformat()
                    ),
                    "t_minus_one_close_source_values_hash": (
                        candidate.t_minus_one_close_source_values_hash
                    ),
                    "stored_median_volume_20d_shares": (
                        item.stored_median_volume_20d_shares
                    ),
                    "causal_volume20_median_volume_20d_shares": (
                        item.causal_volume20_median_volume_20d_shares
                    ),
                }
            ).encode("utf-8")
        )
        all_strict_candidates += int(_eligible_for_new_position(candidate))
        all_basic_candidates += int(_basic_signal_candidate(candidate))
    universe_scope_hash = _SHA256_PREFIX + source_values_hasher.hexdigest()
    pool_scope_hasher = hashlib.sha256()
    daily_records: list[dict[str, Any]] = []
    for session_index, decision_day in enumerate(decision_dates):
        day_rows = tuple(
            sorted(rows_by_date[decision_day], key=lambda item: item.candidate.symbol)
        )
        pool_rows, pool_record = _select_liquidity_pool(day_rows)
        all_liquidity_pool_eligible += _required_int(
            pool_record.get("eligible_count"),
            "liquidity_pool.eligible_count",
        )
        all_liquidity_pool_selected += len(pool_rows)
        pool_scope_hasher.update(
            _canonical_json(
                {
                    "decision_date": decision_day.isoformat(),
                    "selected": pool_record["selected"],
                }
            ).encode("utf-8")
        )
        selected = pool_rows
        candidates = tuple(item.candidate for item in selected)
        day_labels = {
            item.position: (
                None
                if label_masks[item.position, _LABEL_RETURN_POSITION] != 0
                else int(labels[item.position, _LABEL_RETURN_POSITION])
            )
            for item in selected
        }
        day_record: dict[str, Any] = {
            "decision_date": decision_day.isoformat(),
            "candidate_count": len(day_rows),
            "liquidity_pool_candidate_count": len(candidates),
            "strict_eligible_count": sum(
                _eligible_for_new_position(item.candidate) for item in day_rows
            ),
            "basic_signal_candidate_count": sum(
                _basic_signal_candidate(item.candidate) for item in day_rows
            ),
            "liquidity_pool": pool_record,
            "h5_label_observed_count": sum(
                day_labels[item.position] is not None for item in selected
            ),
            "h5_label_missing_count": sum(
                day_labels[item.position] is None for item in selected
            ),
            "lanes": {},
        }
        day_bars = bars.get(decision_day, {})
        for lane_id, accumulator in accumulators.items():
            no_sector_cap = (
                accumulator.definition.scenario == "research_no_sector_cap"
            )
            eligibility_fn = (
                _research_no_sector_eligibility
                if no_sector_cap
                else _eligible_for_new_position
            )
            requested = _requested_weights(
                definition=accumulator.definition,
                candidates=candidates,
                selected=selected,
                score_vectors=score_vectors,
            )
            execution_requested = requested
            lot_execution: Mapping[str, Any] | None = None
            if no_sector_cap:
                execution_requested, lot_execution = _research_lot_aware_requested(
                    state=accumulator.state,
                    decision_day=decision_day,
                    requested=requested,
                    bars=day_bars,
                    # signals 使用共用的八檔 pool；lot/capacity 仍可讀取
                    # 當日全 custody rows，才能對 pool 外既有持倉套用賣出
                    # participation cap，而不把持倉靜默當成無上限退出。
                    candidates=tuple(item.candidate for item in day_rows),
                )
            metrics, transition = _execute_day(
                state=accumulator.state,
                decision_day=decision_day,
                session_index=session_index,
                candidates=candidates,
                bars=day_bars,
                requested=execution_requested,
                eligibility_fn=eligibility_fn,
                enforce_sector_cap=not no_sector_cap,
            )
            calculation = _required_mapping(
                transition.get("calculation"),
                "transition.calculation",
            )
            closing_minor = _required_int(
                calculation.get("closing_value_minor"),
                "closing_value_minor",
            )
            transaction_cost_minor = _required_int(
                calculation.get("transaction_cost_minor"),
                "transaction_cost_minor",
            )
            previous_net_close = (
                accumulator.previous_net_close_minor
                if accumulator.previous_net_close_minor is not None
                else _money_minor(INITIAL_CAPITAL)
            )
            previous_gross_close = (
                accumulator.previous_gross_close_minor
                if accumulator.previous_gross_close_minor is not None
                else _money_minor(INITIAL_CAPITAL)
            )
            accumulator.cumulative_cost_minor += transaction_cost_minor
            gross_close_minor = (
                closing_minor + accumulator.cumulative_cost_minor
            )
            net_return_bp = _close_to_close_return_bp(
                previous_close_minor=previous_net_close,
                closing_minor=closing_minor,
            )
            gross_return_bp = _close_to_close_return_bp(
                previous_close_minor=previous_gross_close,
                closing_minor=gross_close_minor,
            )
            lane_daily = _lane_daily_metrics(
                requested=requested,
                execution_requested=execution_requested,
                metrics=metrics,
                transition=transition,
                candidates=candidates,
                selected=selected,
                day_labels=day_labels,
                gross_return_bp=gross_return_bp,
                net_return_bp=net_return_bp,
                helper_after_cost_return_bp=_required_int(
                    metrics.get("after_cost_return_bp"),
                    "after_cost_return_bp",
                ),
                eligibility_fn=eligibility_fn,
                net_closing_equity_minor=closing_minor,
                gross_closing_equity_cost_addback_estimate_minor=(
                    gross_close_minor
                ),
                investment_pool_symbols=tuple(
                    item.candidate.symbol for item in selected
                ),
                lot_execution=lot_execution,
            )
            accumulator.previous_net_close_minor = closing_minor
            accumulator.previous_gross_close_minor = gross_close_minor
            accumulator.daily.append(lane_daily)
            accumulator.gross_returns_bp.append(gross_return_bp)
            accumulator.net_returns_bp.append(net_return_bp)
            accumulator.net_equities_minor.append(closing_minor)
            accumulator.gross_equities_minor.append(gross_close_minor)
            _accumulate_lane(accumulator, lane_daily)
            day_record["lanes"][lane_id] = lane_daily
        daily_records.append(day_record)

    label_observed_count = int(
        np.sum(label_masks[:, _LABEL_RETURN_POSITION] == 0)
    )
    sidecar_evidence = _causal_volume_sidecar_evidence(rows)
    pool_nonempty_day_count = sum(
        int(item["liquidity_pool"]["selected_count"]) > 0
        for item in daily_records
    )
    pool_empty_day_count = len(daily_records) - pool_nonempty_day_count
    formal_rule_history_available = not any(
        "formal_rule_champion_snapshot_history_missing_formal_replay_blocked"
        in str(item)
        for item in store_manifest.get("assembly_blockers", [])
    )
    investment_pool_scope_hash = _SHA256_PREFIX + pool_scope_hasher.hexdigest()
    source_quality = _source_quality(rows)
    source_quality["liquidity_pool_missing_t_minus_one_close_count"] = sum(
        item.candidate.t_minus_one_close_price is None for item in rows
    )
    source_quality["stored_median_volume_20d_missing_count"] = sum(
        item.stored_median_volume_20d_shares is None for item in rows
    )
    source_quality["causal_volume20_sidecar_missing_count"] = int(
        sidecar_evidence["derived_missing_row_count"]
    )
    source_quality["causal_volume20_sidecar_recovered_count"] = int(
        sidecar_evidence["cross_year_recovered_row_count"]
    )
    if source_quality["liquidity_pool_missing_t_minus_one_close_count"]:
        source_quality.setdefault("blockers", []).append(
            "t_minus_one_close_missing_for_some_rows"
        )
    source_blockers = list(source_quality["blockers"])
    if not formal_rule_history_available:
        source_blockers.append(
            "formal_rule_champion_snapshot_history_missing_formal_replay_blocked"
        )
    source_blockers = sorted(set(source_blockers))
    lane_summaries = [
        _lane_summary(
            accumulator,
            decision_dates=decision_dates,
            candidate_count=len(rows),
            strict_eligible_count=all_strict_candidates,
            label_observed_count=label_observed_count,
            universe_scope_hash=universe_scope_hash,
            investment_pool_scope_hash=investment_pool_scope_hash,
        )
        for accumulator in accumulators.values()
    ]
    body: dict[str, Any] = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": "complete_research",
        "run_id": run_id,
        "parent_training_manifest_path": str(parent_path),
        "parent_training_manifest_hash": parent_hash,
        "parent_store_manifest_hash": store_hash,
        "parent_store_manifest_file_hash": store_manifest_file_hash,
        "dataset_identity_hash": store_manifest.get("dataset_identity_hash"),
        "store_schema_version": store_manifest.get("schema_version"),
        "fold_id": request.fold_id,
        "horizon": request.horizon,
        "algorithms": list(request.algorithms),
        "pack_ids": list(pack_ids),
        "selected_oof_row_count": int(selection["selected_oof_row_count"]),
        "selected_oof_artifact_count": int(selection["selected_oof_artifact_count"]),
        "selected_oof_artifacts": list(selection["artifact_evidence"]),
        "base_head_used": _BASE_HEAD,
        "base_head_position": _BASE_HEAD_POSITION,
        "meta_targets_read": False,
        "teacher_targets_read": False,
        "final_base_experts_used": False,
        "final_meta_used": False,
        "selection_lineage": {
            "parent_manifest_hash": parent_hash,
            "parent_store_manifest_hash": store_hash,
            "fold_id": request.fold_id,
            "horizon": request.horizon,
            "algorithms": list(request.algorithms),
            "pack_ids": list(pack_ids),
            "source_values_hash_binding": universe_scope_hash,
            "investment_pool_scope_hash": investment_pool_scope_hash,
            "liquidity_pool_policy_version": LIQUIDITY_POOL_POLICY_VERSION,
            "lot_execution_policy_version": LOT_EXECUTION_POLICY_VERSION,
            "causal_volume_sidecar_policy_version": (
                CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
            ),
        },
        "universe": {
            "decision_date_start": decision_dates[0].isoformat()
            if decision_dates
            else None,
            "decision_date_end": decision_dates[-1].isoformat()
            if decision_dates
            else None,
            "decision_date_count": len(decision_dates),
            "selected_row_count": len(rows),
            "strict_eligible_row_count": all_strict_candidates,
            "basic_signal_candidate_row_count": all_basic_candidates,
            "liquidity_pool_eligible_row_count": all_liquidity_pool_eligible,
            "liquidity_pool_selected_row_count": all_liquidity_pool_selected,
            "liquidity_pool_size": _MAX_SIGNAL_SYMBOLS,
            "liquidity_pool_policy_version": LIQUIDITY_POOL_POLICY_VERSION,
            "liquidity_pool_nonempty_decision_date_count": (
                pool_nonempty_day_count
            ),
            "liquidity_pool_empty_decision_date_count": pool_empty_day_count,
            "scope_hash": universe_scope_hash,
            "investment_pool_scope_hash": investment_pool_scope_hash,
            "all_lanes_same_scope": True,
            "all_lanes_same_investment_pool": True,
        },
        "causal_volume_sidecar": dict(sidecar_evidence),
        "source_quality": {
            **source_quality,
            "formal_rule_champion_history_available": formal_rule_history_available,
            "causal_rule_source": "replay_source.rule_score_bp",
            "causal_rule_is_formal_champion": False,
            "blockers": source_blockers,
        },
        "execution_contract": {
            "policy": dict(replay._REPLAY_POLICY),
            "transaction_costs_included": True,
            "price_basis": "replay_source.open_close_integer_components",
            "eligibility": "replay_input_builder._eligible_for_new_position",
            "next_tradable_execution": True,
            "strict_sector_scenario": (
                "requires_persisted_pit_sector_id_and_sector_cap"
            ),
            "research_no_sector_cap_scenario": (
                "removes_only_sector_gate/cap_when_pit_sector_id_missing; "
                "does_not create sector ids and is not promotable"
            ),
            "research_weekly_turnover_step": (
                "research_no_sector_cap first derives complete-lot target "
                "differences from the full signal target, then allocates lots "
                "globally within remaining weekly turnover, cash, "
                "participation, position, and symbol limits; the same policy "
                "is used by every research lane"
            ),
            "liquidity_pool": {
                "policy_version": LIQUIDITY_POOL_POLICY_VERSION,
                "selection": (
                    "per decision date select up to eight eligible symbols by "
                    "descending T-1 median_volume_20d_shares multiplied by "
                    "the T-1 close available before decision_at; ties use "
                    "symbol then custody position"
                ),
                "same_pool_for_all_lanes": True,
                "metric_units": "shares_times_TWD_per_share_equals_TWD",
                "rule_or_ml_values_used": False,
                "volume_source": (
                    "research_sidecar_reconstructed_from_immutable_"
                    "replay_source_cross_year_distinct_price_events"
                ),
            },
            "complete_lot_execution": {
                "policy_version": LOT_EXECUTION_POLICY_VERSION,
                "lot_size_shares": replay._REPLAY_POLICY["lot_size_shares"],
                "sub_lot_policy": "retain_cash_and_record_reason",
                "outcome_tuning": False,
            },
            "return_basis": (
                "net_total_return_and_mdd_use_integer_minor_close_equity; "
                "gross_is_same_realized_holdings_with_cumulative_cost_addback "
                "estimate, not an independent no_cost_portfolio; helper "
                "open_to_close is execution_helper_after_cost_return_bp diagnostic"
            ),
            "decision_timezone": "Asia/Taipei",
            "decision_time_local": "08:30:00",
            "all_values_integer_bp_or_decimal_money": True,
            "causal_volume_sidecar_policy_version": (
                CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
            ),
        },
        "performance_capital": {
            "initial_capital": str(INITIAL_CAPITAL),
            "initial_capital_minor": _money_minor(INITIAL_CAPITAL),
            "currency": "TWD",
            "minor_unit": "TWD_cent",
        },
        "lanes": lane_summaries,
        "daily": daily_records,
        "maturity": {
            "classification": "historical_frozen_oos_research",
            "h5_label_field": "benchmark_excess_return_bp",
            "h5_label_observed_row_count": label_observed_count,
            "h5_label_missing_row_count": len(rows) - label_observed_count,
            "forward_effectiveness": "not_evaluated",
            "formal_promotion": "blocked",
        },
        "method_freeze": _method_freeze_evidence(
            request=request,
            pack_ids=pack_ids,
            parent_hash=parent_hash,
            store_hash=store_hash,
        ),
        "future_confirmatory_scopes": _future_confirmatory_scopes(),
        "capacity_preflight": dict(capacity),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "research_only": True,
        "source_readonly": True,
    }
    body["comparison_hash"] = _payload_hash(body)
    return body


def _selection_preflight(
    request: AllocationBaseExpertComparisonRequest,
    *,
    parent: Mapping[str, Any],
    store_manifest: Mapping[str, Any],
    parent_path: Path,
    store_path: Path,
) -> dict[str, Any]:
    store = _NumericStore(store_path)
    fold = _find_fold(store.folds, request.fold_id)
    refs = store.open_fold_refs(fold, "test")
    row_count = len(refs)
    _require_replay_source_sidecars(store, np.asarray(refs, dtype=np.int64))
    del refs
    selected = _select_oof_artifacts(
        request,
        parent=parent,
        parent_path=parent_path,
        store=store,
    )
    return {
        "pack_ids": selected["pack_ids"],
        "selected_oof_row_count": row_count,
        "selected_oof_artifact_count": len(selected["artifacts"]),
    }


def _select_oof_artifacts(
    request: AllocationBaseExpertComparisonRequest,
    *,
    parent: Mapping[str, Any],
    parent_path: Path,
    store: _NumericStore,
) -> dict[str, Any]:
    available_packs = tuple(
        _required_text(item.get("pack_id"), "feature_pack.pack_id")
        for item in store.feature_packs
    )
    pack_ids = _resolved_pack_ids(request, {"feature_packs": list(store.feature_packs)})
    if set(pack_ids) != set(available_packs):
        raise ValueError(
            "comparison requires the complete selected feature-pack scope; "
            f"expected {available_packs}, got {pack_ids}"
        )
    selected: list[dict[str, Any]] = []
    summaries = parent.get("base_experts")
    if not isinstance(summaries, list):
        raise ValueError("parent base_experts is missing")
    for pack_id in pack_ids:
        matches = [
            item
            for item in summaries
            if isinstance(item, dict)
            and item.get("fold_id") == request.fold_id
            and item.get("pack_id") == pack_id
            and item.get("horizon_trading_days") == request.horizon
            and item.get("algorithm") == _ALGORITHM
        ]
        if len(matches) != 1:
            raise ValueError(
                "base OOF coverage is incomplete for "
                f"{request.fold_id}/{pack_id}/h{request.horizon}/{_ALGORITHM}"
            )
        summary = matches[0]
        artifact_directory = parent_path.parent / _required_text(
            summary.get("artifact_path"),
            "base_expert.artifact_path",
        )
        artifact = _read_and_validate_artifact(artifact_directory)
        if artifact.get("schema_version") != EXPERT_SCHEMA_VERSION:
            raise ValueError("base expert artifact schema mismatch")
        if artifact.get("expert_head_ids") != list(EXPERT_HEAD_IDS):
            raise ValueError(f"base expert head contract mismatch: {pack_id}")
        if artifact.get("store_manifest_hash") != store.manifest["manifest_hash"]:
            raise ValueError(f"base expert store lineage mismatch: {pack_id}")
        test_row_count = artifact.get("test_row_count")
        if isinstance(test_row_count, bool) or not isinstance(test_row_count, int):
            raise TypeError(f"base expert test row count must be integer: {pack_id}")
        if test_row_count != summary.get("test_row_count"):
            raise ValueError(f"base expert OOF row count mismatch: {pack_id}")
        if test_row_count <= 0:
            raise ValueError(f"base expert OOF is empty: {pack_id}")
        oof_path = artifact_directory / "oof.i32"
        if not oof_path.is_file():
            raise ValueError(f"base expert OOF file missing: {pack_id}")
        oof_entry = next(
            (
                item
                for item in artifact.get("artifacts", [])
                if isinstance(item, dict) and item.get("path") == "oof.i32"
            ),
            None,
        )
        if not isinstance(oof_entry, dict):
            raise ValueError(f"base expert OOF custody missing: {pack_id}")
        if _file_sha256(oof_path) != oof_entry.get("file_sha256"):
            raise ValueError(f"base expert OOF hash mismatch: {pack_id}")
        expected_bytes = test_row_count * EXPERT_VECTOR_WIDTH * 4
        if oof_path.stat().st_size != expected_bytes:
            raise ValueError(f"base expert OOF byte count mismatch: {pack_id}")
        selected.append(
            {
                "pack_id": pack_id,
                "algorithm": _ALGORITHM,
                "artifact_path": str(artifact_directory),
                "artifact_manifest_hash": artifact["manifest_hash"],
                "artifact_manifest_file_hash": _file_sha256(
                    artifact_directory / "manifest.json"
                ),
                "oof_path": str(oof_path),
                "oof_file_hash": oof_entry["file_sha256"],
                "oof_row_count": test_row_count,
            }
        )
    return {
        "pack_ids": pack_ids,
        "artifacts": selected,
        "selected_oof_row_count": selected[0]["oof_row_count"],
        "selected_oof_artifact_count": len(selected),
        "artifact_evidence": [
            {
                key: item[key]
                for key in (
                    "pack_id",
                    "algorithm",
                    "artifact_manifest_hash",
                    "artifact_manifest_file_hash",
                    "oof_file_hash",
                    "oof_row_count",
                )
            }
            for item in selected
        ],
    }


def _resolved_pack_ids(
    request: AllocationBaseExpertComparisonRequest,
    store_manifest: Mapping[str, Any],
) -> tuple[str, ...]:
    """依 immutable store 的宣告順序解析完整 pack scope。"""

    raw_packs = store_manifest.get("feature_packs")
    if not isinstance(raw_packs, list) or not raw_packs:
        raise ValueError("store feature_packs are missing")
    available = tuple(
        _required_text(
            item.get("pack_id") if isinstance(item, dict) else None,
            "feature_pack.pack_id",
        )
        for item in raw_packs
    )
    if len(set(available)) != len(available):
        raise ValueError("store feature pack ids are duplicated")
    requested = tuple(request.pack_ids)
    if requested and set(requested) != set(available):
        raise ValueError(
            "comparison requires the complete selected feature-pack scope; "
            f"expected {available}, got {requested}"
        )
    return available


def _require_replay_source_sidecars(
    store: _NumericStore,
    refs: np.ndarray,
) -> None:
    """在 preflight 階段確認選定 fold 的 source sidecar 完整存在。"""

    if refs.ndim != 2 or refs.shape[1] != 2:
        raise ValueError("fold refs must have [year_ordinal, local_row_index]")
    ordinals = sorted({int(value) for value in refs[:, 0].tolist()})
    for ordinal in ordinals:
        if ordinal < 0 or ordinal >= len(store.years):
            raise ValueError(f"fold ref year ordinal is out of range: {ordinal}")
        year = store.years[ordinal]
        source_path = year.directory / "replay_source.sqlite"
        if not source_path.is_file():
            raise ValueError(
                "replay_source.sqlite missing for selected year "
                f"{year.year}; build a Direct replay source before comparison"
            )


def _load_oof_scores(
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, np.ndarray]:
    scores: dict[str, np.ndarray] = {}
    for item in artifacts:
        pack_id = _required_text(item.get("pack_id"), "artifact.pack_id")
        path = Path(_required_text(item.get("oof_path"), "artifact.oof_path"))
        row_count = _required_int(item.get("oof_row_count"), "artifact.oof_row_count")
        mmap = np.memmap(
            path,
            dtype=OOF_DTYPE,
            mode="r",
            shape=(row_count, EXPERT_VECTOR_WIDTH),
        )
        scores[pack_id] = np.asarray(mmap[:, _BASE_HEAD_POSITION], dtype=np.int64)
        del mmap
    return scores


def _load_selected_rows(
    *,
    store: _NumericStore,
    refs: np.ndarray,
    fold_id: str,
) -> tuple[_SelectedRow, ...]:
    custody: dict[int, tuple[str, str]] = {}
    for position, decision_date, row_id in store.iter_decision_dates(refs):
        custody[int(position)] = (str(decision_date), str(row_id))
    if len(custody) != len(refs):
        raise ValueError("rows custody did not cover selected fold refs")
    result: list[_SelectedRow] = []
    for ordinal_value in np.unique(refs[:, 0]):
        ordinal = int(ordinal_value)
        indexes = np.flatnonzero(refs[:, 0] == ordinal_value)
        locals_ = np.asarray(refs[indexes, 1], dtype=np.int64)
        year = store.years[ordinal]
        connection = _readonly_sqlite(year.directory / "replay_source.sqlite")
        try:
            source_rows = _fetch_source_by_local_indexes(connection, locals_)
        finally:
            connection.close()
        for position in indexes.tolist():
            local = int(refs[position, 1])
            source = source_rows.get(local)
            if source is None:
                raise ValueError(
                    f"replay source missing selected ref {ordinal}:{local}"
                )
            decision_date_text, row_id = custody[position]
            candidate = _candidate_from_source(
                source,
                fold_id=fold_id,
                custody_decision_date=decision_date_text,
                custody_row_id=row_id,
            )
            result.append(
                _SelectedRow(
                    position=int(position),
                    year_ordinal=ordinal,
                    local_row_index=local,
                    row_id=row_id,
                    candidate=candidate,
                    label_observed=False,
                    label_return_bp=None,
                    stored_median_volume_20d_shares=(
                        candidate.median_volume_20d_shares
                    ),
                )
            )
    result.sort(key=lambda item: item.position)
    with_close = _attach_t_minus_one_close_evidence(store, tuple(result))
    return _attach_causal_volume_sidecar(store, with_close)


def _attach_causal_volume_sidecar(
    store: _NumericStore,
    rows: Sequence[_SelectedRow],
) -> tuple[_SelectedRow, ...]:
    """以 immutable source 跨年重建 volume window，供研究 pool 使用。"""

    if not rows:
        return tuple()
    targets = tuple(
        CausalVolumeTarget(
            year_ordinal=item.year_ordinal,
            local_row_index=item.local_row_index,
            symbol=item.candidate.symbol,
            decision_at=item.candidate.decision_at,
            stored_median_volume_20d_shares=(
                item.stored_median_volume_20d_shares
            ),
        )
        for item in rows
    )
    max_year = max(item.candidate.decision_date.year for item in rows)
    source_paths = tuple(
        (
            int(year.ordinal),
            year.directory / "replay_source.sqlite",
        )
        for year in store.years
        if year.year <= max_year
    )
    sidecar = reconstruct_causal_volume20(
        source_paths=source_paths,
        targets=targets,
        require_same_year_parity=True,
    )
    attached: list[_SelectedRow] = []
    for item in rows:
        value = sidecar.values[(item.year_ordinal, item.local_row_index)]
        candidate = item.candidate
        derived = value.derived_median_volume_20d_shares
        if derived is not None:
            # 後續 pool／participation 計算讀這個 research-only corrected
            # value；stored median 仍留在 row evidence 供 parity 查核。
            candidate = replace(
                candidate,
                median_volume_20d_shares=derived,
            )
        attached.append(
            replace(
                item,
                candidate=candidate,
                causal_volume20_median_volume_20d_shares=derived,
                causal_volume20_evidence=sidecar.evidence,
            )
        )
    return tuple(attached)


def _attach_t_minus_one_close_evidence(
    store: _NumericStore,
    rows: Sequence[_SelectedRow],
) -> tuple[_SelectedRow, ...]:
    """為 pool 排序附加決策日前最後可得 close；只讀 sidecar。"""

    if not rows:
        return tuple()
    symbols = tuple(sorted({item.candidate.symbol for item in rows}))
    max_decision_date = max(
        item.candidate.decision_date for item in rows
    )
    prior_by_symbol: dict[str, list[tuple[date, datetime, Decimal, str]]] = {}
    for year in store.years:
        if year.year > max_decision_date.year:
            continue
        connection = _readonly_sqlite(year.directory / "replay_source.sqlite")
        try:
            for start in range(0, len(symbols), _SOURCE_BATCH_SIZE):
                batch = symbols[start : start + _SOURCE_BATCH_SIZE]
                placeholders = ",".join("?" for _ in batch)
                cursor = connection.execute(
                    f"""
                    SELECT symbol, decision_date, price_event_at,
                           price_available_at, close_int, close_scale,
                           source_values_hash
                    FROM replay_source
                    WHERE symbol IN ({placeholders})
                      AND decision_date < ?
                      AND close_int IS NOT NULL
                      AND close_scale IS NOT NULL
                    """,
                    (*batch, max_decision_date.isoformat()),
                )
                for row in cursor:
                    (
                        symbol,
                        decision_date_text,
                        price_event_at,
                        price_available_at,
                        close_int,
                        close_scale,
                        source_values_hash,
                    ) = row
                    if not isinstance(symbol, str):
                        continue
                    try:
                        close_date = date.fromisoformat(str(decision_date_text))
                    except ValueError:
                        continue
                    close_price = _scaled_price(close_int, close_scale)
                    available_at = _optional_datetime(price_available_at)
                    if available_at is None:
                        available_at = _optional_datetime(price_event_at)
                    source_hash = _optional_text(source_values_hash)
                    if (
                        close_price is None
                        or available_at is None
                        or source_hash is None
                    ):
                        continue
                    prior_by_symbol.setdefault(symbol, []).append(
                        (close_date, available_at, close_price, source_hash)
                    )
        finally:
            connection.close()

    attached: list[_SelectedRow] = []
    for item in rows:
        candidate = item.candidate
        possibilities = [
            value
            for value in prior_by_symbol.get(candidate.symbol, [])
            if value[0] < candidate.decision_date
            and value[1] < candidate.decision_at
        ]
        prior = max(possibilities, default=None, key=lambda value: (value[0], value[1]))
        if prior is None:
            attached.append(item)
            continue
        _, available_at, close_price, source_hash = prior
        attached.append(
            replace(
                item,
                candidate=replace(
                    candidate,
                    t_minus_one_close_price=close_price,
                    t_minus_one_close_available_at=available_at,
                    t_minus_one_close_source_values_hash=source_hash,
                ),
            )
        )
    return tuple(attached)


def _load_bars(
    *,
    store: _NumericStore,
    selected: Sequence[_SelectedRow],
) -> dict[date, dict[str, _Bar]]:
    if not selected:
        return {}
    start = min(item.candidate.decision_date for item in selected)
    end = max(item.candidate.decision_date for item in selected)
    bars: dict[date, dict[str, _Bar]] = {}
    for year in store.years:
        if year.year < start.year or year.year > end.year:
            continue
        connection = _readonly_sqlite(year.directory / "replay_source.sqlite")
        try:
            cursor = connection.execute(
                """
                SELECT local_row_index, decision_at, decision_date, symbol,
                       price_available_at, open_int, open_scale, close_int,
                       close_scale, volume_shares, source_values_hash
                FROM replay_source
                WHERE decision_date >= ? AND decision_date <= ?
                ORDER BY decision_date, symbol, local_row_index
                """,
                (start.isoformat(), end.isoformat()),
            )
            for row in cursor:
                (
                    _local_row_index,
                    decision_at,
                    decision_date_text,
                    symbol,
                    price_available_at,
                    open_int,
                    open_scale,
                    close_int,
                    close_scale,
                    volume_shares,
                    source_values_hash,
                ) = row
                event_date = date.fromisoformat(str(decision_date_text))
                open_price = _scaled_price(open_int, open_scale)
                close_price = _scaled_price(close_int, close_scale)
                if (
                    open_price is None
                    or close_price is None
                    or not isinstance(symbol, str)
                    or not isinstance(source_values_hash, str)
                ):
                    continue
                available_at = _optional_datetime(price_available_at)
                if available_at is None:
                    available_at = _parse_datetime(str(decision_at))
                bars.setdefault(event_date, {})[str(symbol)] = _Bar(
                    symbol=str(symbol),
                    event_date=event_date,
                    available_at=available_at,
                    open_price=open_price,
                    close_price=close_price,
                    open_int=_required_int(open_int, "open_int"),
                    open_scale=_required_int(open_scale, "open_scale"),
                    close_int=_required_int(close_int, "close_int"),
                    close_scale=_required_int(close_scale, "close_scale"),
                    volume_shares=max(0, _required_int(volume_shares, "volume_shares")),
                    source_values_hash=str(source_values_hash),
                )
        finally:
            connection.close()
    return bars


def _requested_weights(
    *,
    definition: _LaneDefinition,
    candidates: Sequence[_Candidate],
    selected: Sequence[_SelectedRow],
    score_vectors: Mapping[str, np.ndarray],
) -> dict[str, int]:
    if definition.lane_kind == "causal_research_rule":
        scored = [
            (item, int(item.rule_score_bp or 0))
            for item in candidates
            if _basic_signal_candidate(item)
            and item.rule_score_bp is not None
            and item.rule_score_bp > 0
        ]
        ranked = sorted(
            scored,
            key=lambda item: (-item[1], item[0].symbol),
        )[:_MAX_SIGNAL_SYMBOLS]
        return _capped_weights(
            [
                (item.symbol, score, item.sector_id)
                for item, score in ranked
            ]
        )
    if definition.lane_kind == "equal_weight_baseline":
        eligible = [item for item in candidates if _basic_signal_candidate(item)]
        equal_ranked = sorted(
            eligible,
            key=lambda item: item.symbol,
        )[:_MAX_SIGNAL_SYMBOLS]
        # Strict sector/PIT eligibility remains enforced by _execute_day.  A
        # candidate with no sector therefore creates a visible unfilled order,
        # rather than an invented sector fallback.
        return _capped_weights(
            [(item.symbol, 1, item.sector_id) for item in equal_ranked]
        )
    if definition.pack_id is not None:
        vector = score_vectors[definition.pack_id]
        values = [
            (item.candidate, int(vector[item.position]))
            for item in selected
        ]
    else:
        values = []
        for item in selected:
            total = sum(
                int(score_vectors[pack_id][item.position])
                for pack_id in score_vectors
            )
            mean = (
                Decimal(total) / Decimal(len(score_vectors))
            ).to_integral_value(rounding=ROUND_HALF_EVEN)
            values.append((item.candidate, int(mean)))
    scored_eligible = [
        (candidate, score)
        for candidate, score in values
        if _basic_signal_candidate(candidate) and score > 0
    ]
    score_ranked = sorted(
        scored_eligible,
        key=lambda item: (-item[1], item[0].symbol),
    )[:_MAX_SIGNAL_SYMBOLS]
    return _capped_weights(
        [
            (candidate.symbol, score, candidate.sector_id)
            for candidate, score in score_ranked
        ]
    )


def _select_liquidity_pool(
    rows: Sequence[_SelectedRow],
) -> tuple[tuple[_SelectedRow, ...], dict[str, Any]]:
    """以 T-1 dollar volume 建立所有 lane 共用的前八檔研究池。"""

    evidence: list[dict[str, Any]] = []
    eligible: list[tuple[_SelectedRow, Decimal]] = []
    for item in rows:
        candidate = item.candidate
        reasons = _liquidity_pool_exclusion_reasons(candidate)
        metric = _liquidity_notional(candidate)
        if not reasons and metric is not None:
            eligible.append((item, metric))
        evidence.append(
            {
                "symbol": candidate.symbol,
                "position": item.position,
                "row_id": item.row_id,
                "eligible": not reasons and metric is not None,
                "selected": False,
                "selection_rank": None,
                "median_volume_20d_shares": candidate.median_volume_20d_shares,
                "stored_median_volume_20d_shares": (
                    item.stored_median_volume_20d_shares
                ),
                "causal_volume20_sidecar_median_volume_20d_shares": (
                    item.causal_volume20_median_volume_20d_shares
                ),
                "volume_source": (
                    "causal_volume20_cross_year_sidecar"
                    if item.causal_volume20_median_volume_20d_shares is not None
                    else "stored_direct_replay_source"
                ),
                "t_minus_one_close": (
                    None
                    if candidate.t_minus_one_close_price is None
                    else str(candidate.t_minus_one_close_price)
                ),
                "t_minus_one_close_available_at": (
                    None
                    if candidate.t_minus_one_close_available_at is None
                    else candidate.t_minus_one_close_available_at.isoformat()
                ),
                "liquidity_notional_twd": (
                    None if metric is None else str(metric)
                ),
                "metric_units": (
                    "median_volume_20d_shares_times_t_minus_one_close_twd_per_share"
                ),
                "exclusion_reasons": sorted(set(reasons)),
            }
        )
    ranked = sorted(
        eligible,
        key=lambda item: (-item[1], item[0].candidate.symbol, item[0].position),
    )
    selected = tuple(item for item, _ in ranked[:_MAX_SIGNAL_SYMBOLS])
    selected_positions = {item.position for item in selected}
    rank_by_position = {
        item.position: rank
        for rank, item in enumerate(selected, start=1)
    }
    for entry in evidence:
        position = int(entry["position"])
        if position in selected_positions:
            entry["selected"] = True
            entry["selection_rank"] = rank_by_position[position]
        elif entry["eligible"]:
            entry["exclusion_reasons"] = ["liquidity_pool_size_limit"]
    evidence_by_position = {
        int(entry["position"]): entry for entry in evidence
    }
    return selected, {
        "policy_version": LIQUIDITY_POOL_POLICY_VERSION,
        "requested_size": _MAX_SIGNAL_SYMBOLS,
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "metric_units": "shares_times_TWD_per_share_equals_TWD",
        "selection_rule": (
            "descending T-1 median volume times T-1 close; symbol then "
            "custody position deterministic tie break"
        ),
        "same_pool_for_all_lanes": True,
        "selected": [
            evidence_by_position[item.position] for item in selected
        ],
        "excluded": [item for item in evidence if not item["selected"]],
    }


def _liquidity_pool_exclusion_reasons(candidate: _Candidate) -> list[str]:
    """回傳可供審計的 pool 排除原因，不讀 signal 或 label。"""

    reasons: list[str] = []
    if candidate.price_event_at is None:
        reasons.append("price_event_missing")
    elif candidate.price_event_at >= candidate.decision_at:
        reasons.append("price_event_not_available_before_decision")
    if (
        candidate.median_volume_20d_shares is None
        or candidate.median_volume_20d_shares <= 0
    ):
        reasons.append("median_volume_20d_missing_or_nonpositive")
    if candidate.t_minus_one_close_price is None:
        reasons.append("t_minus_one_close_missing_or_unavailable")
    elif candidate.t_minus_one_close_price <= 0:
        reasons.append("t_minus_one_close_nonpositive")
    if candidate.trade_restriction_status not in _ALLOWED_TRADABLE:
        reasons.append(
            "trade_restriction_not_tradable:" + candidate.trade_restriction_status
        )
    return reasons


def _liquidity_notional(candidate: _Candidate) -> Decimal | None:
    if (
        candidate.median_volume_20d_shares is None
        or candidate.median_volume_20d_shares <= 0
        or candidate.t_minus_one_close_price is None
        or candidate.t_minus_one_close_price <= 0
    ):
        return None
    return (
        Decimal(candidate.median_volume_20d_shares)
        * candidate.t_minus_one_close_price
    )


def _research_turnover_capped_requested(
    *,
    state: _LaneState,
    decision_day: date,
    requested: Mapping[str, int],
    bars: Mapping[str, _Bar],
) -> dict[str, int]:
    """研究情境按剩餘週轉額逐步靠近 signal target。"""

    symbols = sorted(set(state.shares) | (set(requested) - {_CASH}))
    open_prices: dict[str, Decimal] = {}
    open_value = state.cash
    for symbol in symbols:
        shares = state.shares.get(symbol, 0)
        if shares > 0 and symbol not in bars:
            raise ValueError(f"held_symbol_bar_missing:{symbol}")
        bar = bars.get(symbol)
        if bar is None:
            continue
        open_prices[symbol] = bar.open_price
        open_value += Decimal(shares) * bar.open_price
    if open_value <= 0:
        raise ValueError("replay_lane_open_value_not_positive")
    current = _weights_from_holdings(
        state,
        prices=open_prices,
        total=open_value,
    )
    target = {
        symbol: int(value)
        for symbol, value in requested.items()
        if symbol != _CASH
    }
    theoretical = _turnover_bp(current, target)
    week = decision_day.isocalendar()
    week_key = (week.year, week.week)
    remaining = max(
        0,
        replay._REPLAY_POLICY["maximum_weekly_turnover_bp"]
        - state.weekly_turnover.get(week_key, 0),
    )
    if theoretical <= remaining:
        return target
    if remaining <= 0 or theoretical <= 0:
        return {
            symbol: int(current.get(symbol, 0))
            for symbol in sorted(set(current) - {_CASH})
        }
    stepped: dict[str, int] = {}
    for symbol in sorted((set(current) | set(target)) - {_CASH}):
        current_value = int(current.get(symbol, 0))
        desired_value = int(target.get(symbol, 0))
        delta = desired_value - current_value
        movement = abs(delta) * remaining // theoretical
        stepped[symbol] = (
            current_value + movement
            if delta > 0
            else current_value - movement
            if delta < 0
            else current_value
        )
    if _turnover_bp(current, stepped) > remaining:
        raise ValueError("research turnover step exceeds remaining weekly budget")
    return stepped


def _research_lot_aware_requested(
    *,
    state: _LaneState,
    decision_day: date,
    requested: Mapping[str, int],
    bars: Mapping[str, _Bar],
    candidates: Sequence[_Candidate],
) -> tuple[dict[str, int], dict[str, Any]]:
    """把研究 target 轉成受週轉、現金、參與率約束的完整 lot target。"""

    # 先依完整 signal target 決定每檔應有的 lot 數，再以全組合的
    # remaining turnover/cash/participation 逐 lot 選擇；不能先把週額度
    # 平均切給每檔，否則每檔可能都低於一張而錯過可執行的整體建倉。
    symbols = sorted(set(state.shares) | (set(requested) - {_CASH}))
    open_prices: dict[str, Decimal] = {}
    open_value = state.cash
    for symbol in symbols:
        shares = state.shares.get(symbol, 0)
        if shares > 0 and symbol not in bars:
            raise ValueError(f"held_symbol_bar_missing:{symbol}")
        bar = bars.get(symbol)
        if bar is None:
            continue
        open_prices[symbol] = bar.open_price
        open_value += Decimal(shares) * bar.open_price
    if open_value <= 0:
        raise ValueError("replay_lane_open_value_not_positive")
    current_weights = _weights_from_holdings(
        state,
        prices=open_prices,
        total=open_value,
    )
    week = decision_day.isocalendar()
    week_key = (week.year, week.week)
    remaining = max(
        0,
        replay._REPLAY_POLICY["maximum_weekly_turnover_bp"]
        - state.weekly_turnover.get(week_key, 0),
    )
    lot = replay._REPLAY_POLICY["lot_size_shares"]
    max_risky = 10_000 - replay._REPLAY_POLICY["minimum_cash_bp"]
    candidate_by_symbol = {item.symbol: item for item in candidates}
    desired_shares: dict[str, int] = {}
    symbol_evidence: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        current_shares = int(state.shares.get(symbol, 0))
        target_weight = int(requested.get(symbol, 0))
        bar = bars.get(symbol)
        candidate = candidate_by_symbol.get(symbol)
        reasons: list[str] = []
        raw_shares: int | None = None
        target_lot_shares = 0
        volume_cap_shares: int | None = None
        if candidate is not None:
            if candidate.median_volume_20d_shares is None:
                volume_cap_shares = None
            else:
                volume_cap_shares = (
                    int(candidate.median_volume_20d_shares)
                    * replay._REPLAY_POLICY[
                        "maximum_t_minus_1_median_volume_participation_bp"
                    ]
                    // 10_000
                )
                volume_cap_shares = volume_cap_shares // lot * lot
        if target_weight <= 0:
            base_target_lot_shares = 0
        elif bar is None:
            base_target_lot_shares = current_shares
            reasons.append("execution_bar_missing_retain_current_state")
        else:
            raw_shares = int(
                (
                    open_value
                    * Decimal(target_weight)
                    / Decimal(10_000)
                    / bar.open_price
                ).to_integral_value(rounding=ROUND_DOWN)
            )
            target_lot_shares = raw_shares // lot * lot
            if raw_shares < lot and current_shares == 0:
                reasons.append("target_below_one_lot_retain_cash")
            max_symbol_shares = int(
                (
                    open_value
                    * Decimal(replay._REPLAY_POLICY["maximum_symbol_weight_bp"])
                    / Decimal(10_000)
                    / bar.open_price
                ).to_integral_value(rounding=ROUND_DOWN)
            ) // lot * lot
            if target_lot_shares > max_symbol_shares:
                target_lot_shares = max_symbol_shares
                reasons.append("maximum_symbol_weight_trimmed_lots")
            base_target_lot_shares = target_lot_shares
        if bar is None and target_weight > 0:
            target_lot_shares = current_shares
        elif target_weight <= 0:
            if current_shares <= 0:
                target_lot_shares = 0
            elif volume_cap_shares is None:
                target_lot_shares = current_shares
                reasons.append("sell_participation_cap_missing_retain_state")
            elif volume_cap_shares < lot:
                target_lot_shares = current_shares
                reasons.append(
                    "sell_participation_cap_below_one_lot_retain_state"
                )
            else:
                target_lot_shares = max(
                    0,
                    current_shares
                    - min(current_shares, volume_cap_shares),
                )
                reasons.append("target_difference_requires_full_lot_sell")
        elif bar is not None:
            base_target_lot_shares = max(0, base_target_lot_shares)
            if base_target_lot_shares > current_shares:
                if volume_cap_shares is None:
                    target_lot_shares = current_shares
                    reasons.append("buy_participation_cap_missing_retain_cash")
                elif volume_cap_shares < lot:
                    target_lot_shares = current_shares
                    if current_shares == 0:
                        reasons.append(
                            "participation_cap_below_one_lot_retain_cash"
                        )
                else:
                    target_lot_shares = min(
                        base_target_lot_shares,
                        current_shares + volume_cap_shares,
                    )
                    if target_lot_shares < base_target_lot_shares:
                        reasons.append("participation_cap_trimmed_buy_lots")
            elif base_target_lot_shares < current_shares:
                if volume_cap_shares is None:
                    target_lot_shares = current_shares
                    reasons.append("sell_participation_cap_missing_retain_state")
                elif volume_cap_shares < lot:
                    target_lot_shares = current_shares
                    reasons.append(
                        "sell_participation_cap_below_one_lot_retain_state"
                    )
                else:
                    target_lot_shares = max(
                        base_target_lot_shares,
                        current_shares - volume_cap_shares,
                    )
                    if target_lot_shares > base_target_lot_shares:
                        reasons.append("participation_cap_trimmed_sell_lots")
            else:
                target_lot_shares = current_shares
        if target_lot_shares < 0:
            target_lot_shares = 0
        desired_shares[symbol] = max(0, target_lot_shares)
        symbol_evidence[symbol] = {
            "symbol": symbol,
            "current_shares": current_shares,
            "requested_weight_bp": int(requested.get(symbol, 0)),
            "requested_target_weight_bp": target_weight,
            "raw_target_shares": raw_shares,
            "lot_aligned_target_shares": desired_shares[symbol],
            "volume_cap_shares": volume_cap_shares,
            "lot_size_shares": lot,
            "open_price": None if bar is None else str(bar.open_price),
            "notional_per_lot": (
                None if bar is None else str(Decimal(lot) * bar.open_price)
            ),
            "reasons": reasons,
        }

    plan = {
        symbol: int(shares)
        for symbol, shares in state.shares.items()
        if int(shares) > 0
    }
    planned_cash = state.cash
    reserve = (
        open_value
        * Decimal(replay._REPLAY_POLICY["minimum_cash_bp"])
        / Decimal(10_000)
    )

    # 先賣出完整 lot 釋放現金，再依每一步重新計算的 target 缺口逐 lot
    # 買入；同值時以剩餘 lot 缺口與 symbol 作 deterministic tie-break。
    for symbol in sorted(symbols):
        current_shares = int(state.shares.get(symbol, 0))
        target_shares = desired_shares.get(symbol, 0)
        while int(plan.get(symbol, 0)) - lot >= target_shares:
            tentative = dict(plan)
            tentative[symbol] = int(tentative.get(symbol, 0)) - lot
            tentative_weights = _lot_plan_weights(
                tentative,
                current_shares=state.shares,
                current_weights=current_weights,
                bars=bars,
                open_value=open_value,
            )
            if sum(
                value for key, value in tentative_weights.items() if key != _CASH
            ) > max_risky:
                symbol_evidence[symbol]["reasons"].append(
                    "minimum_cash_or_risky_budget"
                )
                break
            if _turnover_bp(current_weights, tentative_weights) > remaining:
                symbol_evidence[symbol]["reasons"].append(
                    "remaining_weekly_turnover_exhausted"
                )
                break
            plan = tentative
            notional = Decimal(lot) * open_prices[symbol]
            planned_cash += notional - _cost(
                notional,
                replay._REPLAY_POLICY["sell_cost_bp"],
            )

    allocation_steps: list[dict[str, Any]] = []
    blocked_buy_symbols: set[str] = set()
    while True:
        buyable = [
            symbol
            for symbol in symbols
            if symbol not in blocked_buy_symbols
            and desired_shares.get(symbol, 0) > int(plan.get(symbol, 0))
            and bars.get(symbol) is not None
        ]
        if not buyable:
            break
        current_plan_weights = _lot_plan_weights(
            plan,
            current_shares=state.shares,
            current_weights=current_weights,
            bars=bars,
            open_value=open_value,
        )
        gap_by_symbol = {
            symbol: max(
                0,
                int(requested.get(symbol, 0))
                - int(current_plan_weights.get(symbol, 0)),
            )
            for symbol in buyable
        }
        if all(gap == 0 for gap in gap_by_symbol.values()):
            break
        symbol = min(
            buyable,
            key=lambda item: (
                -gap_by_symbol[item],
                -(
                    desired_shares[item]
                    - int(plan.get(item, 0))
                ),
                item,
            ),
        )
        bar = bars[symbol]
        before_gap = gap_by_symbol[symbol]
        tentative = dict(plan)
        tentative[symbol] = int(tentative.get(symbol, 0)) + lot
        tentative_weights = _lot_plan_weights(
            tentative,
            current_shares=state.shares,
            current_weights=current_weights,
            bars=bars,
            open_value=open_value,
        )
        positive = [
            value
            for key, value in tentative_weights.items()
            if key != _CASH and value > 0
        ]
        rejection: str | None = None
        if len(positive) > replay._REPLAY_POLICY["maximum_positions"]:
            rejection = "maximum_positions_reached"
        elif any(
            value > replay._REPLAY_POLICY["maximum_symbol_weight_bp"]
            for value in positive
        ):
            rejection = "maximum_symbol_weight_reached"
        elif sum(positive) > max_risky:
            rejection = "minimum_cash_or_risky_budget"
        elif _turnover_bp(current_weights, tentative_weights) > remaining:
            rejection = "remaining_weekly_turnover_exhausted"
        else:
            notional = Decimal(lot) * bar.open_price
            buy_cost = _cost(
                notional,
                replay._REPLAY_POLICY["buy_cost_bp"],
            )
            if planned_cash - notional - buy_cost < reserve:
                rejection = "minimum_cash_or_buy_cost_unaffordable"
        if rejection is not None:
            symbol_evidence[symbol]["reasons"].append(rejection)
            blocked_buy_symbols.add(symbol)
            continue
        plan = tentative
        planned_cash -= notional + buy_cost
        allocation_steps.append(
            {
                "step": len(allocation_steps) + 1,
                "symbol": symbol,
                "requested_target_weight_bp": int(requested.get(symbol, 0)),
                "before_execution_weight_bp": int(
                    current_plan_weights.get(symbol, 0)
                ),
                "before_weight_gap_bp": before_gap,
                "remaining_lot_gap": int(
                    desired_shares[symbol] - int(plan.get(symbol, 0))
                )
                // lot,
                "remaining_share_gap": int(
                    desired_shares[symbol] - int(plan.get(symbol, 0))
                ),
                "selection_basis": (
                    "maximum_remaining_target_weight_gap_then_remaining_lots_then_symbol"
                ),
            }
        )

    execution_weights = _lot_plan_weights(
        plan,
        current_shares=state.shares,
        current_weights=current_weights,
        bars=bars,
        open_value=open_value,
    )
    for symbol in symbols:
        evidence = symbol_evidence[symbol]
        evidence["execution_shares"] = int(plan.get(symbol, 0))
        evidence["execution_weight_bp"] = int(execution_weights.get(symbol, 0))
        evidence["turnover_execution_target_weight_bp"] = int(
            execution_weights.get(symbol, 0)
        )
        evidence["complete_lots"] = int(plan.get(symbol, 0)) // lot
        if (
            evidence["raw_target_shares"] is not None
            and int(plan.get(symbol, 0))
            < int(evidence["lot_aligned_target_shares"])
            and "remaining_weekly_turnover_exhausted"
            not in evidence["reasons"]
        ):
            evidence["reasons"].append("execution_constraints_trimmed_lots")
        evidence["reasons"] = sorted(set(evidence["reasons"]))
    return execution_weights, {
        "policy_version": LOT_EXECUTION_POLICY_VERSION,
        "lot_size_shares": lot,
        "remaining_weekly_turnover_bp": remaining,
        "requested_target_weights": _weight_rows(requested),
        "execution_weights": _weight_rows(execution_weights),
        "allocation_steps": allocation_steps,
        "symbols": [symbol_evidence[symbol] for symbol in symbols],
        "all_execution_shares_lot_aligned": all(
            int(plan.get(symbol, 0)) % lot == 0 for symbol in symbols
        ),
        "outcome_tuning": False,
    }


def _lot_plan_weights(
    plan: Mapping[str, int],
    *,
    current_shares: Mapping[str, int],
    current_weights: Mapping[str, int],
    bars: Mapping[str, _Bar],
    open_value: Decimal,
) -> dict[str, int]:
    """把 lot plan 轉成能讓 replay 反解回同一 lot 數的整數權重。"""

    weights: dict[str, int] = {}
    for symbol, shares_value in sorted(plan.items()):
        shares = int(shares_value)
        if shares <= 0:
            continue
        bar = bars.get(symbol)
        if bar is None:
            raise ValueError(f"held_symbol_bar_missing:{symbol}")
        weight = int(
            (
                Decimal(shares)
                * bar.open_price
                * Decimal(10_000)
                / open_value
            ).to_integral_value(rounding=ROUND_CEILING)
        )
        weights[symbol] = max(1, weight)
    weights[_CASH] = 10_000 - sum(weights.values())
    if weights[_CASH] < 0:
        raise ValueError("lot plan exceeds total equity")
    return weights


def _lane_daily_metrics(
    *,
    requested: Mapping[str, int],
    metrics: Mapping[str, Any],
    transition: Mapping[str, Any],
    candidates: Sequence[_Candidate],
    selected: Sequence[_SelectedRow],
    day_labels: Mapping[int, int | None],
    execution_requested: Mapping[str, int],
    gross_return_bp: int,
    net_return_bp: int,
    helper_after_cost_return_bp: int,
    eligibility_fn: Any,
    net_closing_equity_minor: int,
    gross_closing_equity_cost_addback_estimate_minor: int,
    investment_pool_symbols: Sequence[str] = (),
    lot_execution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    calculation = _required_mapping(transition.get("calculation"), "calculation")
    before = _weights_from_rows(calculation.get("before_weights"))
    after = _weights_from_rows(calculation.get("after_trade_weights"))
    symbols = set(before) | set(after) | set(requested)
    requested_target = {symbol: int(requested.get(symbol, 0)) for symbol in symbols}
    requested_orders = [
        symbol
        for symbol in symbols
        if symbol != _CASH
        and requested_target[symbol] != int(before.get(symbol, 0))
    ]
    unfilled_orders = [
        symbol
        for symbol in requested_orders
        if requested_target[symbol] != int(after.get(symbol, 0))
    ]
    candidate_by_symbol = {item.symbol: item for item in candidates}
    blocked_orders = [
        symbol
        for symbol in requested_orders
        if symbol != _CASH
        and (
            requested_target[symbol] > int(before.get(symbol, 0))
            and (
            candidate_by_symbol.get(symbol) is None
            or not eligibility_fn(candidate_by_symbol[symbol])
            )
        )
    ]
    holdings = _required_sequence(calculation.get("holdings"), "calculation.holdings")
    buy_count = sum(
        _required_int(_required_mapping(item, "holding").get("post_trade_shares"), "post_trade_shares")
        > _required_int(_required_mapping(item, "holding").get("opening_shares"), "opening_shares")
        for item in holdings
    )
    sell_count = sum(
        _required_int(_required_mapping(item, "holding").get("post_trade_shares"), "post_trade_shares")
        < _required_int(_required_mapping(item, "holding").get("opening_shares"), "opening_shares")
        for item in holdings
    )
    observed_weight = 0
    missing_weight = 0
    label_numerator = Decimal(0)
    label_count = 0
    for selected_row in selected:
        weight = int(after.get(selected_row.candidate.symbol, 0))
        if weight <= 0:
            continue
        label = day_labels.get(selected_row.position)
        if label is None:
            missing_weight += weight
            continue
        observed_weight += weight
        label_numerator += Decimal(weight) * Decimal(label) / Decimal(10_000)
        label_count += 1
    return {
        "gross_return_bp": int(gross_return_bp),
        "net_return_bp": int(net_return_bp),
        "net_closing_equity_minor": _required_int(
            net_closing_equity_minor,
            "net_closing_equity_minor",
        ),
        "gross_closing_equity_cost_addback_estimate_minor": _required_int(
            gross_closing_equity_cost_addback_estimate_minor,
            "gross_closing_equity_cost_addback_estimate_minor",
        ),
        "execution_helper_after_cost_return_bp": int(
            helper_after_cost_return_bp
        ),
        "turnover_bp": _required_int(metrics.get("turnover_bp"), "turnover_bp"),
        "transaction_cost_minor": _required_int(
            calculation.get("transaction_cost_minor"),
            "transaction_cost_minor",
        ),
        "requested_order_count": len(requested_orders),
        "executed_trade_count": buy_count + sell_count,
        "executed_buy_count": buy_count,
        "executed_sell_count": sell_count,
        "unfilled_order_count": len(unfilled_orders),
        "blocked_order_count": len(blocked_orders),
        "requested_weight_bp": sum(
            value for key, value in requested_target.items() if key != _CASH
        ),
        "filled_weight_bp": sum(
            value for key, value in after.items() if key != _CASH
        ),
        "unfilled_weight_bp": sum(
            max(0, requested_target.get(key, 0) - int(after.get(key, 0)))
            for key in requested_target
            if key != _CASH
        ),
        "h5_label_observed_weight_bp": observed_weight,
        "h5_label_missing_weight_bp": missing_weight,
        "h5_label_weighted_excess_return_bp": _decimal_to_int(
            label_numerator
        )
        if label_count
        else None,
        "h5_label_observed_position_count": label_count,
        "requested_weights": _weight_rows(requested_target),
        "execution_requested_weights": _weight_rows(execution_requested),
        "research_turnover_step_applied": (
            dict(requested) != dict(execution_requested)
        ),
        "investment_pool_symbols": list(investment_pool_symbols),
        "complete_lot_execution": (
            None if lot_execution is None else dict(lot_execution)
        ),
        "before_trade_weights": _weight_rows(before),
        "after_trade_weights": _weight_rows(after),
        "diagnostic_signal_top_symbols_without_sector_gate": _signal_top_symbols(
            candidates,
            selected,
            requested,
        ),
        "core_coverage_bp": _required_int(
            metrics.get("core_coverage_bp"), "core_coverage_bp"
        ),
        "enriched_coverage_bp": _required_int(
            metrics.get("enriched_coverage_bp"), "enriched_coverage_bp"
        ),
        "feasible_fill_coverage_bp": _required_int(
            metrics.get("feasible_fill_coverage_bp"),
            "feasible_fill_coverage_bp",
        ),
        "constraint_violation_count": _required_int(
            metrics.get("constraint_violation_count"),
            "constraint_violation_count",
        ),
        "post_close_state_hash": transition.get("post_close_state_hash"),
    }


def _accumulate_lane(accumulator: _LaneAccumulator, daily: Mapping[str, Any]) -> None:
    accumulator.turnover_total_bp += _required_int(daily.get("turnover_bp"), "turnover_bp")
    accumulator.transaction_cost_minor += _required_int(
        daily.get("transaction_cost_minor"), "transaction_cost_minor"
    )
    accumulator.requested_order_count += _required_int(
        daily.get("requested_order_count"), "requested_order_count"
    )
    accumulator.executed_trade_count += _required_int(
        daily.get("executed_trade_count"), "executed_trade_count"
    )
    accumulator.executed_buy_count += _required_int(
        daily.get("executed_buy_count"), "executed_buy_count"
    )
    accumulator.executed_sell_count += _required_int(
        daily.get("executed_sell_count"), "executed_sell_count"
    )
    accumulator.unfilled_order_count += _required_int(
        daily.get("unfilled_order_count"), "unfilled_order_count"
    )
    accumulator.blocked_order_count += _required_int(
        daily.get("blocked_order_count"), "blocked_order_count"
    )
    accumulator.requested_weight_bp += _required_int(
        daily.get("requested_weight_bp"), "requested_weight_bp"
    )
    accumulator.filled_weight_bp += _required_int(
        daily.get("filled_weight_bp"), "filled_weight_bp"
    )
    accumulator.unfilled_weight_bp += _required_int(
        daily.get("unfilled_weight_bp"), "unfilled_weight_bp"
    )
    accumulator.label_observed_weight_bp += _required_int(
        daily.get("h5_label_observed_weight_bp"), "h5_label_observed_weight_bp"
    )
    accumulator.label_missing_weight_bp += _required_int(
        daily.get("h5_label_missing_weight_bp"), "h5_label_missing_weight_bp"
    )
    label = daily.get("h5_label_weighted_excess_return_bp")
    if label is not None:
        accumulator.label_weighted_return_sum_bp += Decimal(int(label))
        accumulator.label_weighted_return_count += 1


def _lane_summary(
    accumulator: _LaneAccumulator,
    *,
    decision_dates: Sequence[date],
    candidate_count: int,
    strict_eligible_count: int,
    label_observed_count: int,
    universe_scope_hash: str,
    investment_pool_scope_hash: str | None = None,
) -> dict[str, Any]:
    initial_equity_minor = _money_minor(INITIAL_CAPITAL)
    gross_total = _equity_total_return_bp(
        accumulator.gross_equities_minor,
        initial_equity_minor,
    )
    net_total = _equity_total_return_bp(
        accumulator.net_equities_minor,
        initial_equity_minor,
    )
    gross_mdd = _maximum_drawdown_from_equities(
        accumulator.gross_equities_minor,
        initial_equity_minor,
    )
    net_mdd = _maximum_drawdown_from_equities(
        accumulator.net_equities_minor,
        initial_equity_minor,
    )
    weekly: dict[tuple[int, int], int] = {}
    for decision_day, daily in zip(decision_dates, accumulator.daily):
        iso = decision_day.isocalendar()
        key = (iso.year, iso.week)
        weekly[key] = weekly.get(key, 0) + _required_int(
            daily.get("turnover_bp"), "turnover_bp"
        )
    max_weekly_turnover = max(weekly.values(), default=0)
    label_average = None
    if accumulator.label_weighted_return_count:
        label_average = _decimal_to_int(
            accumulator.label_weighted_return_sum_bp
            / Decimal(accumulator.label_weighted_return_count)
        )
    if accumulator.executed_trade_count > 0:
        status = "executed_with_replay_constraints"
        status_reason: str | None = None
    elif accumulator.definition.scenario == "strict_sector" and accumulator.blocked_order_count > 0:
        status = "blocked_missing_pit_sector_id"
        status_reason = "strict_sector_eligibility_blocked_missing_or_invalid_pit_sector"
    elif accumulator.blocked_order_count > 0:
        status = "blocked_by_replay_eligibility_constraints"
        status_reason = "research_signal_failed_price_volume_or_tradable_gate"
    elif accumulator.requested_order_count > 0 and accumulator.unfilled_order_count > 0:
        status = "no_fills_after_replay_constraints"
        status_reason = "lot_volume_cash_turnover_or_cooldown_constraint"
    else:
        status = "no_orders_requested"
        status_reason = "selection_policy_produced_no_positive_basic_signal"
    return {
        "lane_id": accumulator.definition.lane_id,
        "lane_kind": accumulator.definition.lane_kind,
        "scenario": accumulator.definition.scenario,
        "selection_policy": accumulator.definition.selection_policy,
        "pack_id": accumulator.definition.pack_id,
        "algorithm": accumulator.definition.algorithm,
        "execution_status": status,
        "execution_status_reason": status_reason,
        "performance_semantics": (
            "net total return and MDD are computed directly from integer minor "
            "unit closing equity; gross is the same realized holdings with "
            "cumulative transaction-cost addback estimate, not an independent "
            "no-cost portfolio; execution helper open-close is diagnostic"
        ),
        "candidate_row_count": candidate_count,
        "strict_eligible_row_count": strict_eligible_count,
        "decision_date_count": len(decision_dates),
        "daily_sample_count": len(accumulator.net_equities_minor),
        "label_observed_row_count": label_observed_count,
        "label_maturity_status": (
            "h5_observed_for_selected_direct_rows"
            if label_observed_count == candidate_count
            else "h5_partially_observed_for_direct_rows"
        ),
        "requested_order_count": accumulator.requested_order_count,
        "executed_trade_count": accumulator.executed_trade_count,
        "executed_buy_count": accumulator.executed_buy_count,
        "executed_sell_count": accumulator.executed_sell_count,
        "unfilled_order_count": accumulator.unfilled_order_count,
        "blocked_order_count": accumulator.blocked_order_count,
        "requested_weight_bp_sum": accumulator.requested_weight_bp,
        "filled_weight_bp_sum": accumulator.filled_weight_bp,
        "unfilled_weight_bp_sum": accumulator.unfilled_weight_bp,
        "turnover_total_bp": accumulator.turnover_total_bp,
        "maximum_weekly_turnover_bp": max_weekly_turnover,
        "transaction_cost_minor_total": accumulator.transaction_cost_minor,
        "final_net_closing_equity_minor": (
            accumulator.net_equities_minor[-1]
            if accumulator.net_equities_minor
            else initial_equity_minor
        ),
        "final_gross_closing_equity_cost_addback_estimate_minor": (
            accumulator.gross_equities_minor[-1]
            if accumulator.gross_equities_minor
            else initial_equity_minor
        ),
        "gross_total_return_bp": gross_total,
        "net_total_return_bp": net_total,
        "gross_max_drawdown_bp": gross_mdd,
        "net_max_drawdown_bp": net_mdd,
        "gross_net_cost_drag_bp": gross_total - net_total,
        "h5_label_weighted_excess_return_average_bp": label_average,
        "h5_label_observed_weight_bp_sum": accumulator.label_observed_weight_bp,
        "h5_label_missing_weight_bp_sum": accumulator.label_missing_weight_bp,
        "universe_scope_hash": universe_scope_hash,
        "investment_pool_scope_hash": (
            universe_scope_hash
            if investment_pool_scope_hash is None
            else investment_pool_scope_hash
        ),
        "formal_comparison": False,
        "production_alpha_bp": 0,
    }


def _source_quality(rows: Sequence[_SelectedRow]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in rows:
        candidate = item.candidate
        stored_median = item.stored_median_volume_20d_shares
        for field_name, missing in (
            ("sector_id", candidate.sector_id is None),
            ("price_event_at", candidate.price_event_at is None),
            (
                "median_volume_20d_shares",
                stored_median is None,
            ),
            ("rule_score_bp", candidate.rule_score_bp is None),
        ):
            if missing:
                counts[field_name] = counts.get(field_name, 0) + 1
    blockers: list[str] = []
    if counts.get("sector_id", 0):
        blockers.append("pit_sector_membership_missing_strict_execution_blocked")
    if counts.get("rule_score_bp", 0):
        blockers.append("causal_rule_score_missing_for_some_rows")
    if counts.get("price_event_at", 0):
        blockers.append("price_event_at_missing_for_some_rows")
    return {
        "selected_row_count": len(rows),
        "missing_field_counts": counts,
        "blockers": sorted(set(blockers)),
    }


def _causal_volume_sidecar_evidence(
    rows: Sequence[_SelectedRow],
) -> dict[str, Any]:
    """讀取 rows 上附加的 immutable sidecar aggregate；不自行推算數值。"""

    for item in rows:
        evidence = item.causal_volume20_evidence
        if evidence is not None:
            return dict(evidence)
    return {
        "policy_version": CAUSAL_VOLUME_SIDECAR_POLICY_VERSION,
        "status": "not_attached",
        "selected_row_count": len(rows),
        "derived_observed_row_count": 0,
        "derived_missing_row_count": len(rows),
        "stored_median_observed_row_count": 0,
        "same_year_parity_checked_row_count": 0,
        "same_year_parity_match_row_count": 0,
        "same_year_parity_mismatch_row_count": 0,
        "cross_year_recovered_row_count": 0,
        "source_scope_hash": None,
        "read_only": True,
    }


def _basic_signal_candidate(candidate: _Candidate) -> bool:
    return bool(
        candidate.price_event_at is not None
        and candidate.price_event_at < candidate.decision_at
        and candidate.median_volume_20d_shares
        and candidate.median_volume_20d_shares > 0
        and candidate.trade_restriction_status in _ALLOWED_TRADABLE
    )


def _research_no_sector_eligibility(candidate: _Candidate) -> bool:
    """研究情境只移除 PIT sector gate，保留其餘可得性限制。"""

    return _basic_signal_candidate(candidate)


def _signal_top_symbols(
    candidates: Sequence[_Candidate],
    selected: Sequence[_SelectedRow],
    requested: Mapping[str, int],
) -> list[str]:
    # 這個欄位只記錄「若忽略缺失 sector 的診斷排序」，不參與 requested
    # weights 或報酬，避免把不可成交的 counterfactual 冒充 portfolio baseline。
    requested_symbols = {
        key for key, value in requested.items() if key != _CASH and value > 0
    }
    if requested_symbols:
        return sorted(requested_symbols)[:_MAX_SIGNAL_SYMBOLS]
    return [
        item.symbol
        for item in sorted(
            (
                candidate
                for candidate in candidates
                if _basic_signal_candidate(candidate)
                and (
                    candidate.rule_score_bp is not None
                    and candidate.rule_score_bp > 0
                )
            ),
            key=lambda item: (-int(item.rule_score_bp or 0), item.symbol),
        )[:_MAX_SIGNAL_SYMBOLS]
    ]


def _close_to_close_return_bp(
    *,
    previous_close_minor: int,
    closing_minor: int,
) -> int:
    """以連續 close equity 計算報酬，保留隔夜 open gap。"""

    if previous_close_minor <= 0 or closing_minor < 0:
        raise ValueError("close-to-close equity must be positive")
    value = (
        Decimal(closing_minor) / Decimal(previous_close_minor)
        - Decimal(1)
    ) * Decimal(10_000)
    return _decimal_to_int(value)


def _equity_total_return_bp(
    equities_minor: Sequence[int],
    initial_equity_minor: int,
) -> int:
    """以首筆資金與最後收盤 equity 直接計算總報酬。"""

    if initial_equity_minor <= 0:
        raise ValueError("initial equity must be positive")
    for equity in equities_minor:
        if isinstance(equity, bool) or not isinstance(equity, int):
            raise TypeError("closing equity must be integer minor units")
        if equity < 0:
            raise ValueError("closing equity must not be negative")
    if not equities_minor:
        return 0
    value = (
        Decimal(equities_minor[-1]) / Decimal(initial_equity_minor)
        - Decimal(1)
    ) * Decimal(10_000)
    return _decimal_to_int(value)


def _maximum_drawdown_from_equities(
    equities_minor: Sequence[int],
    initial_equity_minor: int,
) -> int:
    """由連續整數收盤 equity 計算最大回撤，避免每日 bp 四捨五入累積誤差。"""

    if initial_equity_minor <= 0:
        raise ValueError("initial equity must be positive")
    peak = initial_equity_minor
    maximum = Decimal(0)
    for equity in equities_minor:
        if isinstance(equity, bool) or not isinstance(equity, int):
            raise TypeError("closing equity must be integer minor units")
        if equity < 0:
            raise ValueError("closing equity must not be negative")
        peak = max(peak, equity)
        if peak <= 0:
            continue
        drawdown = (
            Decimal(peak - equity) / Decimal(peak) * Decimal(10_000)
        )
        maximum = max(maximum, drawdown)
    return _decimal_to_int(maximum)


def _candidate_from_source(
    source: Mapping[str, Any],
    *,
    fold_id: str,
    custody_decision_date: str,
    custody_row_id: str,
) -> _Candidate:
    decision_at = _parse_datetime(
        _required_text(source.get("decision_at"), "source.decision_at")
    )
    decision_date = date.fromisoformat(
        _required_text(source.get("decision_date"), "source.decision_date")
    )
    if decision_date.isoformat() != custody_decision_date:
        raise ValueError("replay source/rows decision-date mismatch")
    symbol = _required_text(source.get("symbol"), "source.symbol")
    if not custody_row_id.endswith(f":{symbol}"):
        raise ValueError("replay source/rows symbol mismatch")
    return _Candidate(
        fold_id=fold_id,
        decision_date=decision_date,
        decision_at=decision_at,
        symbol=symbol,
        sector_id=_optional_text(source.get("sector_id")),
        price_event_at=_optional_datetime(source.get("price_event_at")),
        price_available_at=_optional_datetime(source.get("price_available_at")),
        median_volume_20d_shares=_optional_int(
            source.get("median_volume_20d_shares")
        ),
        rule_score_bp=_optional_int(source.get("rule_score_bp")),
        trade_restriction_status=_required_text(
            source.get("trade_restriction_status"),
            "source.trade_restriction_status",
        ),
        source_values_hash=_required_text(
            source.get("source_values_hash"),
            "source.source_values_hash",
        ),
        ml_target_weight_bp=None,
    )


def _fetch_source_by_local_indexes(
    connection: sqlite3.Connection,
    indexes: np.ndarray,
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    local_values = [int(value) for value in indexes.tolist()]
    for start in range(0, len(local_values), _SOURCE_BATCH_SIZE):
        batch = local_values[start : start + _SOURCE_BATCH_SIZE]
        placeholders = ",".join("?" for _ in batch)
        cursor = connection.execute(
            f"""
            SELECT local_row_index, decision_at, decision_date, symbol,
                   sector_id, price_event_at, price_available_at, open_int,
                   open_scale, close_int, close_scale, volume_shares,
                   median_volume_20d_shares, rule_score_bp,
                   trade_restriction_status, source_values_hash
            FROM replay_source
            WHERE local_row_index IN ({placeholders})
            """,
            batch,
        )
        columns = (
            "local_row_index",
            "decision_at",
            "decision_date",
            "symbol",
            "sector_id",
            "price_event_at",
            "price_available_at",
            "open_int",
            "open_scale",
            "close_int",
            "close_scale",
            "volume_shares",
            "median_volume_20d_shares",
            "rule_score_bp",
            "trade_restriction_status",
            "source_values_hash",
        )
        for row in cursor:
            payload = dict(zip(columns, row))
            result[_required_int(payload.pop("local_row_index"), "local_row_index")] = payload
    if len(result) != len(local_values):
        raise ValueError("replay source local index coverage is incomplete")
    return result


def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _find_fold(
    folds: Sequence[Mapping[str, Any]],
    fold_id: str,
) -> Mapping[str, Any]:
    matches = [item for item in folds if item.get("fold_id") == fold_id]
    if len(matches) != 1:
        raise ValueError(f"fold custody missing or duplicated: {fold_id}")
    return matches[0]


def _resolve_store_path(parent_path: Path, parent: Mapping[str, Any]) -> Path:
    value = _required_text(parent.get("store_manifest_path"), "store_manifest_path")
    path = Path(value)
    return (path if path.is_absolute() else parent_path.parent / path).resolve()


def _reject_source_output_overlap(
    parent_path: Path,
    store_path: Path,
    output_root: Path,
) -> None:
    for source in (parent_path.resolve(), store_path.resolve()):
        if output_root == source or output_root.is_relative_to(source.parent):
            raise ValueError("comparison output must not overlap immutable source")


def _capacity_preflight(
    request: AllocationBaseExpertComparisonRequest,
    *,
    source_path: Path,
    output_root: Path,
    stage: str,
) -> dict[str, Any]:
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=request.persistent_new_bytes_budget,
        temporary_peak_bytes_budget=request.temporary_peak_bytes_budget,
        safety_reserve_bytes=request.safety_reserve_bytes,
    )
    output = preflight_capacity(
        probe_path=output_root,
        budget=budget,
        stage=stage + "_output",
        persistent_roots=(output_root,),
        persistent_new_bytes_estimate=_ESTIMATED_PERSISTENT_BYTES,
        temporary_roots=(output_root,),
        temporary_peak_bytes_observed=_ESTIMATED_TEMPORARY_BYTES,
    )
    source = preflight_capacity(
        probe_path=source_path,
        budget=budget,
        stage=stage + "_source",
        persistent_roots=(),
        persistent_new_bytes_estimate=0,
        temporary_roots=(),
        temporary_peak_bytes_observed=0,
    )
    return {
        "output": output.as_dict(),
        "source": source.as_dict(),
        "persistent_estimate_bytes": _ESTIMATED_PERSISTENT_BYTES,
        "temporary_estimate_bytes": _ESTIMATED_TEMPORARY_BYTES,
        "budgets": budget.as_dict(),
    }


def _default_lock_path(parent_path: Path) -> Path:
    # runs/<id>/manifest.json -> release_v4/.ml_heavy_chain.lock
    release_root = parent_path.parent.parent.parent
    return heavy_chain_lock_path(release_root)


def _comparison_run_id(
    request: AllocationBaseExpertComparisonRequest,
    *,
    parent_hash: str,
    store_hash: str,
    pack_ids: Sequence[str],
    method_freeze_hash: str,
) -> str:
    return "base-compare-" + hashlib.sha256(
        _canonical_json(
            {
                "schema_version": COMPARISON_SCHEMA_VERSION,
                "parent_hash": parent_hash,
                "store_hash": store_hash,
                "fold_id": request.fold_id,
                "horizon": request.horizon,
                "algorithms": list(request.algorithms),
                "pack_ids": list(pack_ids),
                "cost_policy": replay._REPLAY_POLICY,
                "method_freeze_hash": method_freeze_hash,
            }
        ).encode("utf-8")
    ).hexdigest()[:24]


def _future_confirmatory_scopes() -> list[dict[str, Any]]:
    """登記未檢視的後續 fold；此函式不開啟任何 fold source 或 label。"""

    scopes: list[dict[str, Any]] = []
    for fold_id in _FUTURE_CONFIRMATORY_FOLD_IDS:
        # fold-005 的 request identity 與本次 fold-004 request 分離；這裡只
        # 登記規格，不解析任何未來 fold 的 source、price、label 或結果。
        request_body = {
            "request_role": "future_confirmatory_registration",
            "fold_id": fold_id,
            "horizon": _HORIZON,
            "algorithms": [_ALGORITHM],
            "pack_ids": "parent_declared_complete",
            "liquidity_pool_policy_version": LIQUIDITY_POOL_POLICY_VERSION,
            "lot_execution_policy_version": LOT_EXECUTION_POLICY_VERSION,
            "causal_volume_sidecar_policy_version": (
                CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
            ),
            "method_freeze_version": METHOD_FREEZE_VERSION,
            "status": "registered_not_read",
        }
        request_hash = _SHA256_PREFIX + hashlib.sha256(
            _canonical_json(request_body).encode("utf-8")
        ).hexdigest()
        scopes.append(
            {
                "fold_id": fold_id,
                "classification": "confirmatory_oos_pre_registered",
                "status": "registered_not_read",
                "request_hash": request_hash,
                "price_data_read": False,
                "label_data_read": False,
                "result_data_read": False,
                "requires_frozen_method_hash": True,
            }
        )
    return scopes


def _method_freeze_evidence(
    *,
    request: AllocationBaseExpertComparisonRequest,
    pack_ids: Sequence[str],
    parent_hash: str,
    store_hash: str,
) -> dict[str, Any]:
    """固定 request、實作檔與政策的 hash，供後續 confirmatory fold 鎖定。"""

    future_scopes = _future_confirmatory_scopes()
    future_request_hashes = [
        str(item["request_hash"]) for item in future_scopes
    ]
    request_body = {
        "request_role": "exploratory_oos_comparison",
        "fold_id": request.fold_id,
        "horizon": request.horizon,
        "algorithms": list(request.algorithms),
        "pack_ids": list(pack_ids),
        "batch_size": request.batch_size,
        "memory_budget_mb": request.memory_budget_mb,
        "persistent_new_bytes_budget": request.persistent_new_bytes_budget,
        "temporary_peak_bytes_budget": request.temporary_peak_bytes_budget,
        "safety_reserve_bytes": request.safety_reserve_bytes,
        "acquire_heavy_lock": request.acquire_heavy_lock,
        "parent_training_manifest_hash": parent_hash,
        "parent_store_manifest_hash": store_hash,
    }
    policy_body = {
        "comparison_method_version": METHOD_FREEZE_VERSION,
        "liquidity_pool_policy_version": LIQUIDITY_POOL_POLICY_VERSION,
        "lot_execution_policy_version": LOT_EXECUTION_POLICY_VERSION,
        "causal_volume_sidecar_policy_version": (
            CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
        ),
        "replay_policy": replay._REPLAY_POLICY,
        "maximum_signal_symbols": _MAX_SIGNAL_SYMBOLS,
        "lane_selection_policies": {
            "base": "positive_expected_excess_return_bp_top8_capped",
            "base_mean": "integer_half_even_mean_positive_score_top8_capped",
            "rule": "persisted_t_minus_one_rule_score_top8_capped",
            "equal_weight": "t_minus_one_liquidity_pool_equal_weight",
        },
        "future_confirmatory_fold_ids": list(_FUTURE_CONFIRMATORY_FOLD_IDS),
        "future_confirmatory_request_hashes": future_request_hashes,
        "outcome_tuning": False,
    }
    request_hash = _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(request_body).encode("utf-8")
    ).hexdigest()
    policy_hash = _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(policy_body).encode("utf-8")
    ).hexdigest()
    code_file_hashes = {
        "comparison_file_hash": _file_sha256(Path(__file__).resolve()),
        "replay_input_builder_file_hash": _file_sha256(
            Path(str(replay_input_builder.__file__)).resolve()
        ),
        "replay_policy_owner_file_hash": _file_sha256(
            Path(str(replay.__file__)).resolve()
        ),
        "causal_volume_sidecar_file_hash": _file_sha256(
            Path(str(causal_volume_sidecar.__file__)).resolve()
        ),
    }
    parent_input_hashes = {
        "parent_training_manifest_hash": parent_hash,
        "parent_store_manifest_hash": store_hash,
    }
    method_freeze_hash = _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(
            {
                "method_freeze_version": METHOD_FREEZE_VERSION,
                "request_hash": request_hash,
                "policy_hash": policy_hash,
                "code_file_hashes": code_file_hashes,
                "parent_input_hashes": parent_input_hashes,
                "future_confirmatory_request_hashes": future_request_hashes,
            }
        ).encode("utf-8")
    ).hexdigest()
    return {
        "method_freeze_version": METHOD_FREEZE_VERSION,
        "request_hash": request_hash,
        "policy_hash": policy_hash,
        "code_file_hashes": code_file_hashes,
        # 保留單一 comparison hash 欄位供舊 consumer 讀取；完整凍結依賴
        # 上述三個 owner file hash，不可只檢查本檔。
        "code_file_hash": code_file_hashes["comparison_file_hash"],
        "parent_input_hashes": parent_input_hashes,
        "future_confirmatory_request_hashes": future_request_hashes,
        "method_freeze_hash": method_freeze_hash,
        "review_status": "frozen_exploratory_pending_confirmatory_review",
        "outcome_tuning": False,
        "outcome_tuning_evidence": (
            "boolean_request_flag_is_not_evidence; fold-004 remains exploratory"
        ),
    }


def _publish_comparison(
    payload: Mapping[str, Any],
    *,
    comparison_path: Path,
    latest_pointer_path: Path,
    output_root: Path,
    capacity: Mapping[str, Any],
    request: AllocationBaseExpertComparisonRequest,
) -> AllocationBaseExpertComparisonPublication:
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    comparison_hash = _required_sha256(body.get("comparison_hash"), "comparison_hash")
    if comparison_path.exists():
        existing = _read_json_mapping(comparison_path)
        if existing != body:
            raise ValueError("immutable comparison run id collision")
        idempotent = True
    else:
        _write_json_exclusive(comparison_path, body)
        idempotent = False
    pointer_body = {
        "schema_version": "allocation-base-expert-oos-comparison-pointer.v1",
        "status": body.get("status"),
        "comparison_path": str(comparison_path.resolve()),
        "comparison_hash": comparison_hash,
        "run_id": body.get("run_id"),
        "parent_training_manifest_hash": body.get(
            "parent_training_manifest_hash"
        ),
        "store_manifest_hash": body.get("parent_store_manifest_hash"),
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
    }
    pointer_body["pointer_hash"] = _payload_hash(pointer_body)
    if latest_pointer_path.exists():
        existing_pointer = _read_json_mapping(latest_pointer_path)
        if existing_pointer != pointer_body:
            raise ValueError("immutable latest comparison pointer collision")
    else:
        _write_json_exclusive(latest_pointer_path, pointer_body)
    output_size = directory_size_bytes(output_root)
    if output_size > request.persistent_new_bytes_budget:
        raise StorageCapacityError(
            "comparison output exceeds persistent budget",
            preflight={
                "stage": "base_expert_comparison_post_publish",
                "output_size_bytes": output_size,
                "persistent_new_bytes_budget": request.persistent_new_bytes_budget,
                "capacity_preflight": dict(capacity),
            },
        )
    return AllocationBaseExpertComparisonPublication(
        comparison_path=comparison_path,
        comparison_hash=comparison_hash,
        latest_pointer_path=latest_pointer_path,
        run_id=_required_text(body.get("run_id"), "run_id"),
        output_size_bytes=output_size,
        capacity_preflight=capacity,
        idempotent=idempotent,
    )


def _load_existing_comparison(
    comparison_path: Path,
    latest_pointer_path: Path,
    *,
    parent_hash: str,
    store_hash: str,
    request: AllocationBaseExpertComparisonRequest,
) -> Mapping[str, Any] | None:
    if not comparison_path.exists():
        if latest_pointer_path.exists():
            raise ValueError("latest comparison pointer exists without run")
        return None
    existing = _read_json_mapping(comparison_path)
    if existing.get("parent_training_manifest_hash") != parent_hash:
        raise ValueError("existing comparison parent lineage mismatch")
    if existing.get("parent_store_manifest_hash") != store_hash:
        raise ValueError("existing comparison store lineage mismatch")
    if existing.get("fold_id") != request.fold_id or existing.get("horizon") != request.horizon:
        raise ValueError("existing comparison selection mismatch")
    expected_hash = _verify_logical_hash(existing, "comparison_hash")
    if expected_hash != existing.get("comparison_hash"):
        raise ValueError("existing comparison hash mismatch")
    return existing


def _decimal_to_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


def _weight_rows(value: object) -> list[dict[str, int | str]]:
    if isinstance(value, Mapping):
        mapping = {
            _required_text(key, "weight key"): _required_int(
                item,
                "weight value",
            )
            for key, item in value.items()
        }
    else:
        mapping = _weights_from_rows(value)
    return [
        {"key": key, "weight_bp": int(mapping[key])}
        for key in sorted(mapping)
        if int(mapping[key]) > 0
    ]


def _weights_from_rows(value: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in _required_sequence(value, "weights"):
        mapping = _required_mapping(item, "weight")
        key = _required_text(mapping.get("key"), "weight.key")
        weight = _required_int(mapping.get("weight_bp"), "weight.weight_bp")
        result[key] = weight
    if _CASH not in result:
        result[_CASH] = 10_000 - sum(
            value for key, value in result.items() if key != _CASH
        )
    return result


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _readonly_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(_readonly_text(path))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


def _verify_logical_hash(payload: Mapping[str, Any], field_name: str) -> str:
    expected = _required_sha256(payload.get(field_name), field_name)
    body = dict(payload)
    body.pop(field_name, None)
    if _payload_hash(body) != expected:
        raise ValueError(f"{field_name} logical hash mismatch")
    return expected


def _payload_hash(payload: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _required_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be object")
    return value


def _required_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be list")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be non-empty string")
    return value


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be integer")
    return value


def _required_sha256(value: object, label: str) -> str:
    text = _required_text(value, label)
    if not text.startswith(_SHA256_PREFIX) or len(text) != 71:
        raise ValueError(f"{label} must be sha256")
    return text


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _required_int(value, "optional integer")


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return _required_text(value, "optional text")


def _optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    return _parse_datetime(_required_text(value, "optional datetime"))


__all__ = [
    "AllocationBaseExpertComparisonRequest",
    "AllocationBaseExpertComparisonPublication",
    "COMPARISON_SCHEMA_VERSION",
    "LIQUIDITY_POOL_POLICY_VERSION",
    "LOT_EXECUTION_POLICY_VERSION",
    "METHOD_FREEZE_VERSION",
    "build_allocation_base_expert_comparison",
    "preflight_allocation_base_expert_comparison",
]
