"""正式 allocation OOS portfolio replay 的證據聚合器。

本模組不從 teacher target 或 horizon label 推測日報酬，也不把研究 sidecar
當成正式 OOS。完整 replay 必須由正式 training run 內的 hash-bound execution
ledger 提供 Rule 與四條 alpha lane 的實際逐日成本後結果；若 training v5 尚未
產出該 ledger，模組只發布 ``blocked`` 稽核產物，絕不合成可 promotion 的數字。

所有對外金融值使用整數 bp。複利、MDD 與 CVaR 的中間運算使用 ``Decimal``。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
from typing import Any, Iterable, Mapping, Sequence, cast


REPLAY_SCHEMA_VERSION = "allocation-ooc-portfolio-replay.v1"
REPLAY_POINTER_SCHEMA_VERSION = "allocation-ooc-portfolio-replay-pointer.v1"
REPLAY_INPUT_SCHEMA_VERSION = "allocation-ooc-replay-inputs.v1"
REPLAY_ROW_SCHEMA_VERSION = "allocation-ooc-replay-observation.v1"
FORMAL_SEMANTIC_VERIFICATION_SCHEMA_VERSION = (
    "allocation-oos-semantic-verification.v1"
)
FORMAL_SEMANTIC_VERIFIER_ID = "allocation-oos-semantic-verifier-v1"
TRAINING_SCHEMA_VERSION = "allocation-ooc-training.v5"
STORE_SCHEMA_VERSION = "portfolio-ml-ooc-store.v3"
EXPERT_SCHEMA_VERSION = "allocation-ooc-expert.v5"
META_SCHEMA_VERSION = "allocation-ooc-meta.v3"
OOF_BUNDLE_SCHEMA_VERSION = "allocation-promotion-oof-custody.v1"
ALPHA_LANES = (0, 2_000, 3_500, 5_000)
MINIMUM_OUTER_FOLDS = 4
MINIMUM_META_OOF_FOLDS = 4
META_TARGET_FIELDS = (
    "target_weight_bp",
    "delta_weight_bp",
    "risk_contribution_bp",
    "risky_budget_bp",
    "cash_bp",
    "rebalance_worthwhile",
)
_SHA256_PREFIX = "sha256:"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TAIPEI_OFFSET = timedelta(hours=8)
_REPLAY_INPUT_RELATIVE_PATH = (
    Path("artifacts") / "oos_portfolio_replay_inputs" / "manifest.json"
)
_REPLAY_POLICY = {
    "minimum_cash_bp": 2_000,
    "maximum_positions": 8,
    "maximum_symbol_weight_bp": 1_500,
    "maximum_sector_weight_bp": 3_000,
    "maximum_t_minus_1_median_volume_participation_bp": 500,
    "maximum_weekly_turnover_bp": 2_000,
    "rebalance_band_bp": 300,
    "minimum_trade_bp": 200,
    "cooldown_trading_days": 5,
    "lot_size_shares": 1_000,
    "buy_cost_bp": 25,
    "sell_cost_bp": 55,
}
_REQUIRED_EXECUTION_SAFETY = {
    "causal_t_minus_one_portfolio_state": True,
    "actual_next_tradable_execution": True,
    "transaction_costs_included": True,
    "rule_baseline_replayed": True,
    "hard_constraints_replayed": True,
    "advice_feedback_forbidden": True,
    "teacher_future_targets_used_for_execution": False,
    "decision_time_local": "08:30:00",
    "decision_timezone": "Asia/Taipei",
    "execution_return_basis": (
        "next_tradable_execution_to_next_tradable_mark_after_cost"
    ),
}
_EXECUTION_COMPONENT_CONTRACT = {
    "schema_version": "allocation-ooc-replay-calculation-components.v1",
    "daily_return_recomputed_from_minor_units": True,
    "turnover_recomputed_from_integer_weights": True,
    "price_component_set_hash_verified": True,
    "maximum_daily_after_cost_return_bp": 10_000,
    "maximum_daily_turnover_bp": 10_000,
}
# Cash-only training state、歷史 sector membership 或交易限制都會改變模型輸入
# 或風控投影，不能在 OOS replay 階段事後「補成」正式證據。保留空集合可讓
# engineering builder 繼續存在，但 Formal consumer 只接受原始 store 已完整
# 通過 full_market_ready 的資料。
_REPLAY_RECONSTRUCTABLE_READINESS_GAPS: frozenset[str] = frozenset()


class _ReplayBlocked(RuntimeError):
    def __init__(self, blockers: Sequence[str]) -> None:
        normalized = tuple(sorted(set(blockers)))
        if not normalized:
            normalized = ("formal_oos_replay_blocked_without_reason",)
        super().__init__(";".join(normalized))
        self.blockers = normalized


@dataclass(frozen=True)
class AllocationOOSPortfolioReplayRequest:
    """一次獨立 replay 聚合請求。"""

    training_manifest_path: Path
    output_root: Path
    replay_run_id: str
    role: str
    replay_as_of: datetime
    replay_input_manifest_path: Path | None = None

    def __post_init__(self) -> None:
        if self.role not in {"primary", "verification"}:
            raise ValueError("role must be primary or verification")
        if not _SAFE_RUN_ID.fullmatch(self.replay_run_id):
            raise ValueError("replay_run_id contains unsafe path characters")
        if self.replay_as_of.tzinfo is None:
            raise ValueError("replay_as_of must be timezone-aware")


@dataclass(frozen=True)
class AllocationOOSPortfolioReplayResult:
    """發布結果；``blocked`` 不會更新 latest complete pointer。"""

    status: str
    replay_run_id: str
    role: str
    blockers: tuple[str, ...]
    replay_path: Path
    replay_file_hash: str
    replay_result_hash: str | None
    manifest_hash: str
    latest_pointer_path: Path
    latest_pointer_updated: bool
    idempotent: bool


@dataclass(frozen=True)
class _FormalCustody:
    training_path: Path
    training: Mapping[str, object]
    dataset_path: Path
    dataset: Mapping[str, object]
    input_custody: Mapping[str, str]
    outer_fold_ids: tuple[str, ...]
    folds_by_id: Mapping[str, Mapping[str, object]]
    base_oof_by_fold: Mapping[str, tuple[Mapping[str, object], ...]]
    meta_oof_by_fold: Mapping[str, Mapping[str, object]]
    dataset_replay_source_hash: str


@dataclass(frozen=True)
class _DailyRow:
    fold_id: str
    decision_date: date
    rule: Mapping[str, int]
    lanes: Mapping[int, Mapping[str, int]]


@dataclass(frozen=True)
class _CalculationState:
    closing_cash_minor: int
    post_trade_shares: Mapping[str, int]
    closing_value_minor: int


@dataclass(frozen=True)
class _ReplaySourceArtifact:
    year: int
    path: Path
    source_mode: str


def build_allocation_oos_portfolio_replay(
    request: AllocationOOSPortfolioReplayRequest,
) -> AllocationOOSPortfolioReplayResult:
    """建立一次正式 replay；任何 custody 或 PIT 缺口都發布 blocked 產物。"""

    custody: _FormalCustody | None = None
    try:
        custody = _load_formal_custody(request.training_manifest_path)
        replay_input_path = _resolve_replay_input_path(request, custody)
        replay_input = _load_replay_input(
            replay_input_path,
            custody=custody,
        )
        rows = _load_daily_rows(
            replay_input,
            replay_input_path=replay_input_path,
            custody=custody,
            replay_as_of=request.replay_as_of,
        )
        lanes = _aggregate_lanes(rows, custody.outer_fold_ids)
        replay_result_hash = _payload_hash(
            {
                "input_custody": dict(custody.input_custody),
                "lanes": lanes,
            }
        )
        body: dict[str, object] = {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "status": "complete",
            "replay_run_id": request.replay_run_id,
            "replay_role": request.role,
            "replay_as_of": request.replay_as_of.isoformat(
                timespec="seconds"
            ),
            "formal_source_only": True,
            "research_shadow_included": False,
            "research_only": False,
            "input_custody": dict(custody.input_custody),
            "replay_input_manifest_path": str(replay_input_path.resolve()),
            "replay_input_manifest_file_hash": _file_hash(
                replay_input_path
            ),
            "replay_input_manifest_hash": _required_sha256(
                replay_input.get("manifest_hash"),
                "replay_input.manifest_hash",
            ),
            "dataset_replay_source_hash": (
                custody.dataset_replay_source_hash
            ),
            "outer_fold_count": len(custody.outer_fold_ids),
            "daily_observation_count": len(rows),
            "lanes": lanes,
            "replay_result_hash": replay_result_hash,
            # 交易、持倉、成本與報酬已能逐日重算；但目前尚未由獨立
            # verifier 從 production Rule champion、完整六頭 Meta OOF
            # 與官方交易日曆重建每日 requested/projected weights。這份
            # artifact 因此只能作 engineering replay，不能取得 Promotion
            # credit。待 verifier 真正實作後才可把 verified 原子切成 true。
            "formal_semantic_validation": {
                "schema_version": (
                    FORMAL_SEMANTIC_VERIFICATION_SCHEMA_VERSION
                ),
                "verifier_id": FORMAL_SEMANTIC_VERIFIER_ID,
                "verified": False,
                "blockers": [
                    "official_trading_calendar_custody_not_independently_verified",
                    "production_rule_champion_replay_not_independently_rebuilt",
                    "six_head_meta_oof_projection_not_independently_rebuilt",
                    "retro_raw_derivation_not_independently_recomputed_by_promotion_consumer",
                ],
            },
            "promotion_eligible_input": False,
            "broker_order_allowed": False,
        }
        return _publish(
            request,
            payload=_with_logical_hash(body, "manifest_hash"),
            blockers=(),
            replay_result_hash=replay_result_hash,
        )
    except _ReplayBlocked as exc:
        return _publish_blocked(
            request,
            blockers=exc.blockers,
            custody=custody,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return _publish_blocked(
            request,
            blockers=(
                "formal_oos_replay_input_invalid:"
                f"{type(exc).__name__}:{_safe_reason(exc)}",
            ),
            custody=custody,
        )


def _load_formal_custody(training_path: Path) -> _FormalCustody:
    training_path = training_path.resolve()
    _require_file(training_path, "training_manifest_missing")
    training = _read_json_mapping(training_path, "training_manifest")
    if training.get("schema_version") != TRAINING_SCHEMA_VERSION:
        _block("training_manifest_not_formal_ooc_v5")
    if training.get("status") != "complete":
        _block("training_manifest_incomplete")
    _require_formal_lane(training, "training_manifest")
    _verify_logical_hash(
        training,
        "manifest_hash",
        "training_manifest_logical_hash_mismatch",
    )
    training_file_hash = _file_hash(training_path)

    store_text = _required_text(
        training.get("store_manifest_path"),
        "training.store_manifest_path",
    )
    dataset_path = (
        Path(store_text).resolve()
        if Path(store_text).is_absolute()
        else (training_path.parent / store_text).resolve()
    )
    _require_file(dataset_path, "dataset_manifest_missing")
    dataset = _read_json_mapping(dataset_path, "dataset_manifest")
    if dataset.get("schema_version") != STORE_SCHEMA_VERSION:
        _block("dataset_manifest_not_formal_ooc_v3")
    if dataset.get("status") != "complete":
        _block("dataset_manifest_incomplete")
    _require_formal_lane(dataset, "dataset_manifest")
    _verify_logical_hash(
        dataset,
        "manifest_hash",
        "dataset_manifest_logical_hash_mismatch",
    )
    dataset_file_hash = _file_hash(dataset_path)
    if training.get("store_manifest_file_hash") != dataset_file_hash:
        _block("training_dataset_manifest_file_hash_mismatch")
    dataset_identity_hash = _required_sha256(
        dataset.get("dataset_identity_hash"),
        "dataset.dataset_identity_hash",
    )
    if training.get("dataset_identity_hash") != dataset_identity_hash:
        _block("training_dataset_identity_hash_mismatch")

    readiness_value = dataset.get("readiness")
    if readiness_value is None:
        readiness_value = dataset.get("execution")
    readiness = _required_mapping(
        readiness_value,
        "dataset.readiness_or_execution",
    )
    if readiness.get("full_market_ready") is not True:
        failed_checks = {
            _required_text(item, "dataset.readiness_failed_check")
            for item in _required_sequence(
                readiness.get("readiness_failed_checks"),
                "dataset.readiness_failed_checks",
            )
        }
        replay_can_reconstruct = bool(
            readiness.get("direct_numeric_store") is True
            and readiness.get("direct_store_complete") is True
            and failed_checks
            and failed_checks.issubset(
                _REPLAY_RECONSTRUCTABLE_READINESS_GAPS
            )
        )
        if not replay_can_reconstruct:
            _block("formal_ooc_dataset_full_market_not_ready")
    safety = _required_mapping(dataset.get("safety"), "dataset.safety")
    if safety.get("pit_contract_revalidated_per_row") is not True:
        _block("formal_ooc_dataset_pit_not_revalidated")
    if safety.get("t_minus_1_contract_revalidated_per_row") is not True:
        _block("formal_ooc_dataset_t_minus_one_not_revalidated")
    validation = _required_mapping(
        training.get("validation"),
        "training.validation",
    )
    for field_name in (
        "pit_violation_count",
        "future_prefix_violation_count",
        "constraint_violation_count",
    ):
        if _required_nonnegative_int(
            validation.get(field_name),
            f"training.validation.{field_name}",
        ) != 0:
            _block(f"formal_ooc_training_{field_name}_nonzero")
    if validation.get("deterministic_custody") is not True:
        _block("formal_ooc_training_deterministic_custody_missing")

    folds = _mapping_sequence(dataset.get("folds"), "dataset.folds")
    outer_fold_ids = tuple(
        _required_text(item.get("fold_id"), "fold.fold_id")
        for item in folds
    )
    if (
        len(outer_fold_ids) < MINIMUM_OUTER_FOLDS
        or len(outer_fold_ids) != len(set(outer_fold_ids))
    ):
        _block(
            "formal_ooc_outer_folds_incomplete:"
            f"{len(set(outer_fold_ids))}/{MINIMUM_OUTER_FOLDS}"
        )
    if _required_int(training.get("fold_count"), "training.fold_count") != len(
        outer_fold_ids
    ):
        _block("training_dataset_outer_fold_count_mismatch")
    folds_by_id = {
        _required_text(item.get("fold_id"), "fold.fold_id"): item
        for item in folds
    }

    final_meta = _required_mapping(
        training.get("final_meta"),
        "training.final_meta",
    )
    final_directory = _contained_path(
        training_path.parent,
        _required_text(final_meta.get("artifact_path"), "final_meta.path"),
        "final_model_artifact_path_escapes_run",
    )
    final_manifest = _validate_artifact_directory(
        final_directory,
        expected_schema=META_SCHEMA_VERSION,
        blocker_prefix="final_model",
    )
    if final_manifest.get("artifact_kind") != "final_meta_allocator":
        _block("final_model_artifact_kind_mismatch")
    _validate_meta_artifact_contract(
        final_manifest,
        blocker_prefix="final_model",
        require_oof=False,
    )

    base_entries: list[Mapping[str, object]] = []
    observed_base_folds: set[str] = set()
    summaries = _mapping_sequence(
        training.get("base_experts"),
        "training.base_experts",
    )
    if (
        _required_int(
            training.get("base_expert_count"),
            "training.base_expert_count",
        )
        != len(summaries)
        or not summaries
    ):
        _block("formal_ooc_base_expert_coverage_incomplete")
    for index, summary in enumerate(summaries):
        directory = _contained_path(
            training_path.parent,
            _required_text(
                summary.get("artifact_path"),
                f"base[{index}].artifact_path",
            ),
            "base_oof_artifact_path_escapes_run",
        )
        manifest = _validate_artifact_directory(
            directory,
            expected_schema=EXPERT_SCHEMA_VERSION,
            blocker_prefix=f"base_oof:{index}",
        )
        entry = _oof_entry(directory, manifest, "base")
        fold_id = _required_text(entry.get("fold_id"), "base.fold_id")
        observed_base_folds.add(fold_id)
        base_entries.append(entry)
    if observed_base_folds != set(outer_fold_ids):
        _block("formal_ooc_base_oof_fold_coverage_incomplete")

    meta_entries: list[Mapping[str, object]] = []
    for index, summary in enumerate(
        _mapping_sequence(training.get("meta_folds"), "training.meta_folds")
    ):
        directory = _contained_path(
            training_path.parent,
            _required_text(
                summary.get("artifact_path"),
                f"meta[{index}].artifact_path",
            ),
            "meta_oof_artifact_path_escapes_run",
        )
        manifest = _validate_artifact_directory(
            directory,
            expected_schema=META_SCHEMA_VERSION,
            blocker_prefix=f"meta_oof:{index}",
        )
        _validate_meta_artifact_contract(
            manifest,
            blocker_prefix=f"meta_oof:{index}",
            require_oof=True,
        )
        meta_entries.append(_oof_entry(directory, manifest, "meta"))
    meta_by_fold = {
        _required_text(item.get("fold_id"), "meta.fold_id"): item
        for item in meta_entries
    }
    if len(meta_by_fold) != len(meta_entries):
        _block("formal_ooc_meta_oof_fold_duplicate")
    if set(meta_by_fold).difference(outer_fold_ids):
        _block("formal_ooc_meta_oof_fold_unknown")
    if len(meta_by_fold) < MINIMUM_META_OOF_FOLDS:
        _block(
            "formal_ooc_meta_oof_coverage_insufficient:"
            f"{len(meta_by_fold)}/{MINIMUM_META_OOF_FOLDS}"
        )

    dataset_id = _required_text(dataset.get("dataset_id"), "dataset.dataset_id")
    oof_body: dict[str, object] = {
        "schema_version": OOF_BUNDLE_SCHEMA_VERSION,
        "training_manifest_hash": _required_sha256(
            training.get("manifest_hash"),
            "training.manifest_hash",
        ),
        "training_manifest_file_hash": training_file_hash,
        "model_artifact_hash": training_file_hash,
        "dataset_id": dataset_id,
        "dataset_identity_hash": dataset_identity_hash,
        "dataset_manifest_file_hash": dataset_file_hash,
        "outer_fold_ids": list(outer_fold_ids),
        "base_oof_artifacts": sorted(
            base_entries,
            key=lambda item: (
                str(item["fold_id"]),
                str(item.get("expert_id", "")),
            ),
        ),
        "meta_oof_artifacts": sorted(
            meta_entries,
            key=lambda item: str(item["fold_id"]),
        ),
        "formal_source_only": True,
        "research_shadow_included": False,
    }
    oof_source_hash = _payload_hash(oof_body)
    input_custody = {
        "training_manifest_file_hash": training_file_hash,
        "model_artifact_hash": training_file_hash,
        "dataset_identity_hash": dataset_identity_hash,
        "dataset_manifest_file_hash": dataset_file_hash,
        "oof_source_hash": oof_source_hash,
    }
    base_by_fold: dict[str, list[Mapping[str, object]]] = {
        fold_id: [] for fold_id in outer_fold_ids
    }
    for item in base_entries:
        base_by_fold[str(item["fold_id"])].append(item)
    canonical_base_by_fold = {
        fold_id: tuple(
            sorted(
                values,
                key=lambda item: str(item.get("expert_id", "")),
            )
        )
        for fold_id, values in base_by_fold.items()
    }
    return _FormalCustody(
        training_path=training_path,
        training=training,
        dataset_path=dataset_path,
        dataset=dataset,
        input_custody=input_custody,
        outer_fold_ids=outer_fold_ids,
        folds_by_id=folds_by_id,
        base_oof_by_fold=canonical_base_by_fold,
        meta_oof_by_fold=meta_by_fold,
        dataset_replay_source_hash=_dataset_replay_source_hash(
            dataset,
            dataset_path=dataset_path,
        ),
    )


def _dataset_replay_source_hash(
    dataset: Mapping[str, object],
    *,
    dataset_path: Path,
) -> str:
    source_records: list[dict[str, object]] = []
    for year in _mapping_sequence(dataset.get("years"), "dataset.years"):
        year_value = _required_int(year.get("year"), "year.year")
        directory = dataset_path.parent / f"year={year_value}"
        selected: list[dict[str, object]] = []
        artifacts = _mapping_sequence(year.get("artifacts"), "year.artifacts")
        by_name = {
            Path(_required_text(item.get("path"), "artifact.path")).name: item
            for item in artifacts
        }
        for name in (
            "targets.i32",
            "labels.i32",
            "labels.masks.u8",
            "rows.sqlite",
        ):
            item = by_name.get(name)
            if item is None:
                _block(f"formal_ooc_dataset_replay_artifact_missing:{year_value}:{name}")
            assert item is not None
            path = _contained_path(
                directory,
                _required_text(item.get("path"), "artifact.path"),
                "dataset_replay_artifact_path_escapes_year",
            )
            _require_file(
                path,
                f"formal_ooc_dataset_replay_artifact_missing:{year_value}:{name}",
            )
            expected_hash = _required_sha256(
                item.get("file_sha256"),
                "artifact.file_sha256",
            )
            if _file_hash(path) != expected_hash:
                _block(
                    "formal_ooc_dataset_replay_artifact_hash_mismatch:"
                    f"{year_value}:{name}"
                )
            expected_bytes = _required_nonnegative_int(
                item.get("byte_count"),
                "artifact.byte_count",
            )
            if path.stat().st_size != expected_bytes:
                _block(
                    "formal_ooc_dataset_replay_artifact_byte_count_mismatch:"
                    f"{year_value}:{name}"
                )
            selected.append(
                {
                    "path": name,
                    "file_sha256": expected_hash,
                    "byte_count": expected_bytes,
                }
            )
        source_records.append(
            {
                "year": year_value,
                "year_manifest_hash": _required_sha256(
                    year.get("manifest_hash"),
                    "year.manifest_hash",
                ),
                "artifacts": selected,
            }
        )
    if not source_records:
        _block("formal_ooc_dataset_year_label_artifacts_missing")

    fold_records: list[dict[str, object]] = []
    for fold in _mapping_sequence(dataset.get("folds"), "dataset.folds"):
        fold_id = _required_text(fold.get("fold_id"), "fold.fold_id")
        test = _required_mapping(fold.get("test"), "fold.test")
        test_path = _contained_path(
            dataset_path.parent / "folds",
            _required_text(test.get("path"), "fold.test.path"),
            "dataset_fold_test_path_escapes_store",
        )
        _require_file(test_path, f"dataset_fold_test_refs_missing:{fold_id}")
        expected_hash = _required_sha256(
            test.get("file_sha256"),
            "fold.test.file_sha256",
        )
        if _file_hash(test_path) != expected_hash:
            _block(f"dataset_fold_test_refs_hash_mismatch:{fold_id}")
        fold_records.append(
            {
                "fold_id": fold_id,
                "test_ref_file_hash": expected_hash,
                "test_ref_content_hash": _required_sha256(
                    test.get("content_sha256"),
                    "fold.test.content_sha256",
                ),
                "test_ref_row_count": _required_nonnegative_int(
                    test.get("row_count"),
                    "fold.test.row_count",
                ),
            }
        )
    return _payload_hash(
        {
            "dataset_identity_hash": dataset["dataset_identity_hash"],
            "year_label_sources": source_records,
            "fold_test_sources": fold_records,
        }
    )


def _resolve_replay_input_path(
    request: AllocationOOSPortfolioReplayRequest,
    custody: _FormalCustody,
) -> Path:
    if request.replay_input_manifest_path is None:
        candidate = custody.training_path.parent / _REPLAY_INPUT_RELATIVE_PATH
    else:
        candidate = request.replay_input_manifest_path
    resolved = candidate.resolve()
    allowed_root = (
        custody.training_path.parent
        / _REPLAY_INPUT_RELATIVE_PATH.parent
    ).resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError:
        _block("formal_oos_replay_input_path_outside_training_run")
    if not resolved.is_file():
        raise _ReplayBlocked(
            (
                "formal_oos_replay_execution_ledger_missing",
                "formal_oos_replay_realized_daily_returns_missing",
                "formal_oos_replay_rule_baseline_missing",
            )
        )
    return resolved


def _load_replay_input(
    path: Path,
    *,
    custody: _FormalCustody,
) -> Mapping[str, object]:
    payload = _read_json_mapping(path, "replay_input")
    if payload.get("schema_version") != REPLAY_INPUT_SCHEMA_VERSION:
        _block("formal_oos_replay_input_schema_mismatch")
    if payload.get("status") != "complete":
        _block("formal_oos_replay_input_incomplete")
    _require_formal_lane(payload, "replay_input")
    _verify_logical_hash(
        payload,
        "manifest_hash",
        "formal_oos_replay_input_manifest_hash_mismatch",
    )
    declared = _required_mapping(
        payload.get("input_custody"),
        "replay_input.input_custody",
    )
    if dict(declared) != dict(custody.input_custody):
        _block("formal_oos_replay_input_custody_mismatch")
    if (
        payload.get("dataset_replay_source_hash")
        != custody.dataset_replay_source_hash
    ):
        _block("formal_oos_replay_dataset_source_hash_mismatch")
    if tuple(
        _required_text(item, "outer_fold_id")
        for item in _required_sequence(
            payload.get("outer_fold_ids"),
            "replay_input.outer_fold_ids",
        )
    ) != custody.outer_fold_ids:
        _block("formal_oos_replay_outer_fold_order_mismatch")
    if tuple(
        _required_int(item, "alpha_lane")
        for item in _required_sequence(
            payload.get("alpha_lanes_bp"),
            "replay_input.alpha_lanes_bp",
        )
    ) != ALPHA_LANES:
        _block("formal_oos_replay_alpha_lanes_incomplete")
    if dict(
        _required_mapping(payload.get("policy"), "replay_input.policy")
    ) != _REPLAY_POLICY:
        _block("formal_oos_replay_policy_mismatch")
    execution_safety = _required_mapping(
        payload.get("execution_safety"),
        "replay_input.execution_safety",
    )
    if dict(execution_safety) != _REQUIRED_EXECUTION_SAFETY:
        _block("formal_oos_replay_execution_safety_mismatch")
    component_contract = _required_mapping(
        payload.get("execution_component_contract"),
        "replay_input.execution_component_contract",
    )
    if dict(component_contract) != _EXECUTION_COMPONENT_CONTRACT:
        _block("formal_oos_replay_execution_component_contract_mismatch")
    expected_bindings = _expected_fold_bindings(custody)
    bindings = _mapping_sequence(
        payload.get("fold_bindings"),
        "replay_input.fold_bindings",
    )
    if list(bindings) != expected_bindings:
        _block("formal_oos_replay_fold_bindings_mismatch")
    return payload


def _expected_fold_bindings(
    custody: _FormalCustody,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for fold_id in custody.outer_fold_ids:
        fold = custody.folds_by_id[fold_id]
        test = _required_mapping(fold.get("test"), "fold.test")
        meta = custody.meta_oof_by_fold.get(fold_id)
        result.append(
            {
                "fold_id": fold_id,
                "store_test_refs_file_hash": _required_sha256(
                    test.get("file_sha256"),
                    "fold.test.file_sha256",
                ),
                "store_test_refs_content_hash": _required_sha256(
                    test.get("content_sha256"),
                    "fold.test.content_sha256",
                ),
                "store_test_row_count": _required_nonnegative_int(
                    test.get("row_count"),
                    "fold.test.row_count",
                ),
                "base_oof_set_hash": _payload_hash(
                    list(custody.base_oof_by_fold[fold_id])
                ),
                "meta_oof_file_hash": (
                    None
                    if meta is None
                    else _required_sha256(
                        meta.get("oof_file_hash"),
                        "meta.oof_file_hash",
                    )
                ),
                "allocation_source": (
                    "rule_fallback" if meta is None else "meta_oof"
                ),
            }
        )
    return result


def _validate_replay_source_artifacts(
    replay_input: Mapping[str, object],
    *,
    replay_input_path: Path,
    custody: _FormalCustody,
) -> Mapping[int, _ReplaySourceArtifact]:
    raw_artifacts = replay_input.get("replay_source_artifacts")
    if raw_artifacts is None:
        return {}
    result: dict[int, _ReplaySourceArtifact] = {}
    file_hashes: list[str] = []
    expected_years = {
        _required_int(item.get("year"), "dataset.year.year")
        for item in _mapping_sequence(
            custody.dataset.get("years"),
            "dataset.years",
        )
    }
    for index, item in enumerate(
        _mapping_sequence(
            raw_artifacts,
            "replay_input.replay_source_artifacts",
        )
    ):
        if set(item) != {
            "year",
            "path",
            "file_sha256",
            "row_count",
            "source_mode",
            "lineage",
        }:
            _block(
                "formal_oos_replay_source_artifact_fields_mismatch:"
                f"{index}"
            )
        year = _required_int(item.get("year"), "replay_source.year")
        if year in result:
            _block(f"formal_oos_replay_source_artifact_duplicate:{year}")
        source_mode = _required_text(
            item.get("source_mode"),
            "replay_source.source_mode",
        )
        if source_mode not in {
            "embedded_direct_numeric",
            "retro_hash_bound_raw_pit",
        }:
            _block(f"formal_oos_replay_source_mode_invalid:{year}")
        path = Path(
            _required_text(item.get("path"), "replay_source.path")
        ).resolve()
        allowed_root = (
            custody.dataset_path.parent.resolve()
            if source_mode == "embedded_direct_numeric"
            else (replay_input_path.parent / "replay_sources").resolve()
        )
        try:
            path.relative_to(allowed_root)
        except ValueError:
            _block(f"formal_oos_replay_source_path_outside_custody:{year}")
        _require_file(path, f"formal_oos_replay_source_missing:{year}")
        expected_hash = _required_sha256(
            item.get("file_sha256"),
            "replay_source.file_sha256",
        )
        if _file_hash(path) != expected_hash:
            _block(f"formal_oos_replay_source_file_hash_mismatch:{year}")
        _validate_replay_source_lineage(
            _required_mapping(item.get("lineage"), "replay_source.lineage"),
            source_mode=source_mode,
            database_path=path,
            database_file_hash=expected_hash,
            replay_input_path=replay_input_path,
            custody=custody,
            year=year,
        )
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
        )
        try:
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(replay_source)"
                )
            }
            required_columns = {
                "symbol",
                "price_event_at",
                "price_available_at",
                "open_int",
                "open_scale",
                "close_int",
                "close_scale",
                "volume_shares",
                "source_values_hash",
            }
            if not required_columns.issubset(columns):
                _block(
                    f"formal_oos_replay_source_schema_mismatch:{year}"
                )
            observed_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM replay_source"
                ).fetchone()[0]
            )
        finally:
            connection.close()
        if observed_rows != _required_nonnegative_int(
            item.get("row_count"),
            "replay_source.row_count",
        ):
            _block(f"formal_oos_replay_source_row_count_mismatch:{year}")
        result[year] = _ReplaySourceArtifact(
            year=year,
            path=path,
            source_mode=source_mode,
        )
        file_hashes.append(expected_hash)
    if set(result) != expected_years:
        _block("formal_oos_replay_source_year_coverage_mismatch")
    if _payload_hash(file_hashes) != _required_sha256(
        replay_input.get("replay_source_manifest_set_hash"),
        "replay_input.replay_source_manifest_set_hash",
    ):
        _block("formal_oos_replay_source_manifest_set_hash_mismatch")
    return result


def _validate_replay_source_lineage(
    lineage: Mapping[str, object],
    *,
    source_mode: str,
    database_path: Path,
    database_file_hash: str,
    replay_input_path: Path,
    custody: _FormalCustody,
    year: int,
) -> None:
    exact_fields = {
        "schema_version",
        "derivation_manifest_path",
        "derivation_manifest_hash",
        "derivation_manifest_file_hash",
        "database_file_hash",
        "training_manifest_hash",
        "training_manifest_file_hash",
        "store_manifest_hash",
        "store_manifest_file_hash",
        "raw_manifest_hash",
        "raw_manifest_file_hash",
    }
    if set(lineage) != exact_fields:
        _block(f"formal_oos_replay_source_lineage_fields_mismatch:{year}")
    if (
        lineage.get("schema_version")
        != "allocation-replay-source-lineage.v1"
        or lineage.get("database_file_hash") != database_file_hash
        or lineage.get("training_manifest_hash")
        != custody.training.get("manifest_hash")
        or lineage.get("training_manifest_file_hash")
        != _file_hash(custody.training_path)
        or lineage.get("store_manifest_hash")
        != custody.dataset.get("manifest_hash")
        or lineage.get("store_manifest_file_hash")
        != _file_hash(custody.dataset_path)
    ):
        _block(f"formal_oos_replay_source_lineage_custody_mismatch:{year}")
    store_identity = _required_mapping(
        custody.dataset.get("store_identity"),
        "dataset.store_identity",
    )
    direct_identity = _required_mapping(
        store_identity.get("direct_identity"),
        "dataset.store_identity.direct_identity",
    )
    if (
        lineage.get("raw_manifest_hash")
        != direct_identity.get("raw_manifest_hash")
        or lineage.get("raw_manifest_file_hash")
        != direct_identity.get("raw_manifest_file_hash")
    ):
        _block(f"formal_oos_replay_source_raw_identity_mismatch:{year}")
    derivation_path = Path(
        _required_text(
            lineage.get("derivation_manifest_path"),
            "lineage.derivation_manifest_path",
        )
    ).resolve()
    allowed_manifest = (
        custody.dataset_path.resolve()
        if source_mode == "embedded_direct_numeric"
        else (replay_input_path.parent / "replay_sources").resolve()
    )
    if source_mode == "embedded_direct_numeric":
        if derivation_path != allowed_manifest:
            _block(
                f"formal_oos_replay_source_store_manifest_path_mismatch:{year}"
            )
    else:
        try:
            derivation_path.relative_to(allowed_manifest)
        except ValueError:
            _block(
                f"formal_oos_replay_source_retro_manifest_path_escape:{year}"
            )
    _require_file(
        derivation_path,
        f"formal_oos_replay_source_derivation_manifest_missing:{year}",
    )
    if _file_hash(derivation_path) != _required_sha256(
        lineage.get("derivation_manifest_file_hash"),
        "lineage.derivation_manifest_file_hash",
    ):
        _block(
            f"formal_oos_replay_source_derivation_manifest_file_hash_mismatch:{year}"
        )
    derivation = _read_json_mapping(
        derivation_path,
        "replay_source.derivation_manifest",
    )
    _verify_logical_hash(
        derivation,
        "manifest_hash",
        f"formal_oos_replay_source_derivation_manifest_hash_mismatch:{year}",
    )
    if derivation.get("manifest_hash") != lineage.get(
        "derivation_manifest_hash"
    ):
        _block(
            f"formal_oos_replay_source_derivation_manifest_identity_mismatch:{year}"
        )
    if source_mode == "retro_hash_bound_raw_pit":
        if (
            derivation.get("schema_version")
            != "portfolio-ml-replay-source.v1"
            or derivation.get("source_mode")
            != "retro_hash_bound_raw_pit"
            or derivation.get("year") != year
            or derivation.get("database_path") != database_path.name
            or derivation.get("database_file_hash") != database_file_hash
            or derivation.get("training_manifest_hash")
            != lineage.get("training_manifest_hash")
            or derivation.get("training_manifest_file_hash")
            != lineage.get("training_manifest_file_hash")
            or derivation.get("store_manifest_hash")
            != lineage.get("store_manifest_hash")
            or derivation.get("store_manifest_file_hash")
            != lineage.get("store_manifest_file_hash")
            or derivation.get("raw_manifest_hash")
            != lineage.get("raw_manifest_hash")
            or derivation.get("raw_manifest_file_hash")
            != lineage.get("raw_manifest_file_hash")
        ):
            _block(
                f"formal_oos_replay_source_retro_manifest_custody_mismatch:{year}"
            )


def _validate_price_components_against_sources(
    prices: Sequence[Mapping[str, object]],
    *,
    replay_sources: Mapping[int, _ReplaySourceArtifact],
    line_number: int,
) -> None:
    if not replay_sources:
        _block(
            f"formal_oos_replay_price_source_artifacts_missing:{line_number}"
        )
    for item in prices:
        event_date = _parse_date(
            _required_text(item.get("event_date"), "price.event_date"),
            "price.event_date",
        )
        matched = False
        for source_year in (event_date.year, event_date.year + 1):
            source = replay_sources.get(source_year)
            if source is None:
                continue
            connection = sqlite3.connect(
                f"file:{source.path.as_posix()}?mode=ro",
                uri=True,
            )
            try:
                candidates = connection.execute(
                    """
                    SELECT price_available_at
                    FROM replay_source
                    WHERE symbol = ?
                      AND substr(price_event_at, 1, 10) = ?
                      AND open_int = ?
                      AND open_scale = ?
                      AND close_int = ?
                      AND close_scale = ?
                      AND volume_shares = ?
                      AND source_values_hash = ?
                    LIMIT 32
                    """,
                    (
                        item["symbol"],
                        event_date.isoformat(),
                        item["open_int"],
                        item["open_scale"],
                        item["close_int"],
                        item["close_scale"],
                        item["volume_shares"],
                        item["source_values_hash"],
                    ),
                ).fetchall()
            finally:
                connection.close()
            expected_available_at = _parse_datetime(
                _required_text(item.get("available_at"), "price.available_at"),
                "price.available_at",
            )
            if any(
                candidate[0] is not None
                and _parse_datetime(
                    str(candidate[0]),
                    "source.price_available_at",
                )
                == expected_available_at
                for candidate in candidates
            ):
                matched = True
                break
        if not matched:
            _block(
                "formal_oos_replay_price_component_not_in_hash_bound_source:"
                f"{line_number}:{item['symbol']}"
            )


def _load_daily_rows(
    replay_input: Mapping[str, object],
    *,
    replay_input_path: Path,
    custody: _FormalCustody,
    replay_as_of: datetime,
) -> tuple[_DailyRow, ...]:
    rows_item = _required_mapping(replay_input.get("rows"), "replay_input.rows")
    rows_path = _contained_path(
        replay_input_path.parent,
        _required_text(rows_item.get("path"), "rows.path"),
        "formal_oos_replay_rows_path_escapes_input_directory",
    )
    _require_file(rows_path, "formal_oos_replay_rows_missing")
    if _file_hash(rows_path) != _required_sha256(
        rows_item.get("file_sha256"),
        "rows.file_sha256",
    ):
        _block("formal_oos_replay_rows_file_hash_mismatch")
    if rows_path.stat().st_size != _required_nonnegative_int(
        rows_item.get("byte_count"),
        "rows.byte_count",
    ):
        _block("formal_oos_replay_rows_byte_count_mismatch")

    rows: list[_DailyRow] = []
    record_hashes: list[str] = []
    seen_keys: set[tuple[str, date]] = set()
    as_of_utc = replay_as_of.astimezone(timezone.utc)
    rule_policy_hash = _required_sha256(
        replay_input.get("rule_policy_hash"),
        "replay_input.rule_policy_hash",
    )
    cost_policy_hash = _required_sha256(
        replay_input.get("cost_policy_hash"),
        "replay_input.cost_policy_hash",
    )
    ledger_hash = _required_sha256(
        replay_input.get("causal_portfolio_ledger_hash"),
        "replay_input.causal_portfolio_ledger_hash",
    )
    replay_sources = _validate_replay_source_artifacts(
        replay_input,
        replay_input_path=replay_input_path,
        custody=custody,
    )
    calculation_states: dict[tuple[str, str], _CalculationState] = {}
    expected_fold_dates = _expected_fold_decision_dates(custody)
    for line_number, raw_line in enumerate(
        rows_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        value = json.loads(raw_line)
        row = _required_mapping(value, f"rows[{line_number}]")
        if row.get("schema_version") != REPLAY_ROW_SCHEMA_VERSION:
            _block(f"formal_oos_replay_row_schema_mismatch:{line_number}")
        _verify_logical_hash(
            row,
            "record_hash",
            f"formal_oos_replay_row_hash_mismatch:{line_number}",
        )
        record_hashes.append(
            _required_sha256(row.get("record_hash"), "row.record_hash")
        )
        if row.get("rule_policy_hash") != rule_policy_hash:
            _block(f"formal_oos_replay_rule_policy_hash_mismatch:{line_number}")
        if row.get("cost_policy_hash") != cost_policy_hash:
            _block(f"formal_oos_replay_cost_policy_hash_mismatch:{line_number}")
        if row.get("causal_portfolio_ledger_hash") != ledger_hash:
            _block(f"formal_oos_replay_ledger_hash_mismatch:{line_number}")
        fold_id = _required_text(row.get("fold_id"), "row.fold_id")
        if fold_id not in custody.folds_by_id:
            _block(f"formal_oos_replay_unknown_fold:{fold_id}")
        decision_at = _parse_datetime(
            _required_text(row.get("decision_at"), "row.decision_at"),
            "row.decision_at",
        )
        if (
            decision_at.utcoffset() != _TAIPEI_OFFSET
            or decision_at.timetz().replace(tzinfo=None) != time(8, 30)
        ):
            _block(
                f"formal_oos_replay_decision_time_not_taipei_0830:{line_number}"
            )
        decision_date = _parse_date(
            _required_text(row.get("decision_date"), "row.decision_date"),
            "row.decision_date",
        )
        if decision_at.date() != decision_date:
            _block(f"formal_oos_replay_decision_date_mismatch:{line_number}")
        outcome_available_at = _parse_datetime(
            _required_text(
                row.get("outcome_available_at"),
                "row.outcome_available_at",
            ),
            "row.outcome_available_at",
        )
        if outcome_available_at <= decision_at:
            _block(f"formal_oos_replay_outcome_not_forward:{line_number}")
        if outcome_available_at.astimezone(timezone.utc) > as_of_utc:
            _block(f"formal_oos_replay_outcome_not_available:{line_number}")
        fold = custody.folds_by_id[fold_id]
        test_start = fold.get("test_start")
        test_end = fold.get("test_end")
        if test_start is not None and decision_date < _parse_date(
            _required_text(test_start, "fold.test_start"),
            "fold.test_start",
        ):
            _block(f"formal_oos_replay_date_before_fold:{line_number}")
        if test_end is not None and decision_date > _parse_date(
            _required_text(test_end, "fold.test_end"),
            "fold.test_end",
        ):
            _block(f"formal_oos_replay_date_after_fold:{line_number}")
        key = (fold_id, decision_date)
        if key in seen_keys:
            _block(f"formal_oos_replay_duplicate_fold_date:{fold_id}:{decision_date}")
        seen_keys.add(key)

        meta = custody.meta_oof_by_fold.get(fold_id)
        source_hash = row.get("source_meta_oof_file_hash")
        if meta is None:
            if source_hash is not None or row.get("allocation_source") != "rule_fallback":
                _block(f"formal_oos_replay_invalid_rule_fallback:{line_number}")
        else:
            expected_meta_hash = _required_sha256(
                meta.get("oof_file_hash"),
                "meta.oof_file_hash",
            )
            if (
                source_hash != expected_meta_hash
                or row.get("allocation_source") != "meta_oof"
            ):
                _block(f"formal_oos_replay_meta_oof_hash_mismatch:{line_number}")

        rule = _normalize_daily_metrics(
            _required_mapping(row.get("rule"), "row.rule"),
            label="row.rule",
        )
        lanes = _normalize_daily_lanes(row.get("lanes"), label="row.lanes")
        if lanes[0] != rule:
            _block(f"formal_oos_replay_alpha_zero_not_rule:{line_number}")
        _validate_daily_calculation_components(
            row=row,
            rule=rule,
            lanes=lanes,
            line_number=line_number,
            fold_id=fold_id,
            states=calculation_states,
            replay_sources=replay_sources,
        )
        if meta is None and any(lanes[alpha] != rule for alpha in ALPHA_LANES):
            _block(
                f"formal_oos_replay_rule_fallback_lane_diverged:{line_number}"
            )
        rows.append(
            _DailyRow(
                fold_id=fold_id,
                decision_date=decision_date,
                rule=rule,
                lanes=lanes,
            )
        )
    if len(rows) != _required_nonnegative_int(
        rows_item.get("row_count"),
        "rows.row_count",
    ):
        _block("formal_oos_replay_rows_count_mismatch")
    if _payload_hash(record_hashes) != _required_sha256(
        rows_item.get("record_hashes_hash"),
        "rows.record_hashes_hash",
    ):
        _block("formal_oos_replay_record_hashes_hash_mismatch")
    observed_folds = {row.fold_id for row in rows}
    if observed_folds != set(custody.outer_fold_ids):
        _block(
            "formal_oos_replay_daily_fold_coverage_incomplete:"
            f"{len(observed_folds)}/{len(custody.outer_fold_ids)}"
        )
    if seen_keys != expected_fold_dates:
        missing = sorted(expected_fold_dates - seen_keys)
        extra = sorted(seen_keys - expected_fold_dates)
        _block(
            "formal_oos_replay_daily_date_coverage_mismatch:"
            f"missing={len(missing)}:extra={len(extra)}"
        )
    fold_order = {
        fold_id: index for index, fold_id in enumerate(custody.outer_fold_ids)
    }
    return tuple(
        sorted(
            rows,
            key=lambda row: (fold_order[row.fold_id], row.decision_date),
        )
    )


def _expected_fold_decision_dates(
    custody: _FormalCustody,
) -> set[tuple[str, date]]:
    year_rows: dict[int, Path] = {}
    for year_item in _mapping_sequence(
        custody.dataset.get("years"),
        "dataset.years",
    ):
        ordinal = _required_int(
            year_item.get("year_ordinal"),
            "dataset.year.year_ordinal",
        )
        year = _required_int(year_item.get("year"), "dataset.year.year")
        rows_artifact = next(
            (
                item
                for item in _mapping_sequence(
                    year_item.get("artifacts"),
                    "dataset.year.artifacts",
                )
                if Path(
                    _required_text(item.get("path"), "artifact.path")
                ).name
                == "rows.sqlite"
            ),
            None,
        )
        if rows_artifact is None:
            _block(f"formal_oos_replay_rows_artifact_missing:{year}")
        assert rows_artifact is not None
        rows_path = _contained_path(
            custody.dataset_path.parent / f"year={year}",
            _required_text(rows_artifact.get("path"), "rows.path"),
            "formal_oos_replay_rows_artifact_path_escape",
        )
        _require_file(
            rows_path,
            f"formal_oos_replay_rows_artifact_file_missing:{year}",
        )
        if _file_hash(rows_path) != _required_sha256(
            rows_artifact.get("file_sha256"),
            "rows.file_sha256",
        ):
            _block(f"formal_oos_replay_rows_artifact_hash_mismatch:{year}")
        year_rows[ordinal] = rows_path
    expected: set[tuple[str, date]] = set()
    for fold_id in custody.outer_fold_ids:
        fold = custody.folds_by_id[fold_id]
        test = _required_mapping(fold.get("test"), "fold.test")
        refs_path = _contained_path(
            custody.dataset_path.parent / "folds",
            _required_text(test.get("path"), "fold.test.path"),
            "formal_oos_replay_test_refs_path_escape",
        )
        _require_file(
            refs_path,
            f"formal_oos_replay_test_refs_missing:{fold_id}",
        )
        refs_bytes = refs_path.read_bytes()
        expected_ref_count = _required_nonnegative_int(
            test.get("row_count"),
            "fold.test.row_count",
        )
        if (
            len(refs_bytes) != expected_ref_count * 16
            or _file_hash(refs_path)
            != _required_sha256(
                test.get("file_sha256"),
                "fold.test.file_sha256",
            )
        ):
            _block(f"formal_oos_replay_test_refs_invalid:{fold_id}")
        refs_by_ordinal: dict[int, list[int]] = {}
        for ordinal, local_index in struct.iter_unpack("<qq", refs_bytes):
            refs_by_ordinal.setdefault(int(ordinal), []).append(
                int(local_index)
            )
        resolved_count = 0
        for ordinal, local_indexes in refs_by_ordinal.items():
            current_rows_path = year_rows.get(ordinal)
            if current_rows_path is None:
                _block(
                    f"formal_oos_replay_test_ref_year_unknown:{fold_id}:{ordinal}"
                )
            assert current_rows_path is not None
            connection = sqlite3.connect(
                f"file:{current_rows_path.as_posix()}?mode=ro",
                uri=True,
            )
            try:
                for offset in range(0, len(local_indexes), 800):
                    chunk = local_indexes[offset : offset + 800]
                    placeholders = ",".join("?" for _ in chunk)
                    values = connection.execute(
                        "SELECT local_row_index, decision_date FROM rows "
                        f"WHERE local_row_index IN ({placeholders})",
                        chunk,
                    ).fetchall()
                    resolved_count += len(values)
                    expected.update(
                        (
                            fold_id,
                            _parse_date(str(value[1]), "rows.decision_date"),
                        )
                        for value in values
                    )
            finally:
                connection.close()
        if resolved_count != expected_ref_count:
            _block(
                f"formal_oos_replay_test_ref_coverage_incomplete:{fold_id}:"
                f"{resolved_count}/{expected_ref_count}"
            )
    return expected


def _normalize_daily_lanes(
    value: object,
    *,
    label: str,
) -> Mapping[int, Mapping[str, int]]:
    result: dict[int, Mapping[str, int]] = {}
    for index, raw in enumerate(_mapping_sequence(value, label)):
        alpha = _required_int(raw.get("alpha_bp"), f"{label}[{index}].alpha_bp")
        if alpha in result:
            _block(f"formal_oos_replay_duplicate_alpha_lane:{alpha}")
        payload = dict(raw)
        payload.pop("alpha_bp", None)
        result[alpha] = _normalize_daily_metrics(
            payload,
            label=f"{label}[{index}]",
        )
    if tuple(sorted(result)) != ALPHA_LANES:
        _block("formal_oos_replay_alpha_lanes_incomplete")
    return result


def _normalize_daily_metrics(
    value: Mapping[str, object],
    *,
    label: str,
) -> Mapping[str, int]:
    exact_fields = {
        "after_cost_return_bp",
        "turnover_bp",
        "core_coverage_bp",
        "enriched_coverage_bp",
        "feasible_fill_coverage_bp",
        "pit_violation_count",
        "future_prefix_violation_count",
        "constraint_violation_count",
    }
    if set(value) != exact_fields:
        _block(f"formal_oos_replay_daily_metric_fields_mismatch:{label}")
    after_cost = _required_int(
        value.get("after_cost_return_bp"),
        f"{label}.after_cost_return_bp",
    )
    if after_cost <= -10_000:
        _block(f"formal_oos_replay_daily_return_below_minus_10000:{label}")
    if after_cost > _required_int(
        _EXECUTION_COMPONENT_CONTRACT[
            "maximum_daily_after_cost_return_bp"
        ],
        "execution_component_contract.maximum_daily_after_cost_return_bp",
    ):
        _block(f"formal_oos_replay_daily_return_above_bound:{label}")
    turnover = _required_nonnegative_int(
        value.get("turnover_bp"),
        f"{label}.turnover_bp",
    )
    if turnover > _required_int(
        _EXECUTION_COMPONENT_CONTRACT["maximum_daily_turnover_bp"],
        "execution_component_contract.maximum_daily_turnover_bp",
    ):
        _block(f"formal_oos_replay_daily_turnover_above_bound:{label}")
    return {
        "after_cost_return_bp": after_cost,
        "turnover_bp": turnover,
        "core_coverage_bp": _required_bp(
            value.get("core_coverage_bp"),
            f"{label}.core_coverage_bp",
        ),
        "enriched_coverage_bp": _required_bp(
            value.get("enriched_coverage_bp"),
            f"{label}.enriched_coverage_bp",
        ),
        "feasible_fill_coverage_bp": _required_bp(
            value.get("feasible_fill_coverage_bp"),
            f"{label}.feasible_fill_coverage_bp",
        ),
        "pit_violation_count": _required_nonnegative_int(
            value.get("pit_violation_count"),
            f"{label}.pit_violation_count",
        ),
        "future_prefix_violation_count": _required_nonnegative_int(
            value.get("future_prefix_violation_count"),
            f"{label}.future_prefix_violation_count",
        ),
        "constraint_violation_count": _required_nonnegative_int(
            value.get("constraint_violation_count"),
            f"{label}.constraint_violation_count",
        ),
    }


def _validate_daily_calculation_components(
    *,
    row: Mapping[str, object],
    rule: Mapping[str, int],
    lanes: Mapping[int, Mapping[str, int]],
    line_number: int,
    fold_id: str,
    states: dict[tuple[str, str], _CalculationState],
    replay_sources: Mapping[int, _ReplaySourceArtifact],
) -> None:
    verification = _required_mapping(
        row.get("calculation_verification"),
        "row.calculation_verification",
    )
    price_components = _mapping_sequence(
        verification.get("price_components"),
        "row.calculation_verification.price_components",
    )
    canonical_prices: list[dict[str, object]] = []
    seen_symbols: set[str] = set()
    for index, component in enumerate(price_components):
        if set(component) != {
            "symbol",
            "event_date",
            "available_at",
            "open_int",
            "open_scale",
            "close_int",
            "close_scale",
            "volume_shares",
            "source_values_hash",
        }:
            _block(
                "formal_oos_replay_price_component_fields_mismatch:"
                f"{line_number}:{index}"
            )
        symbol = _required_text(
            component.get("symbol"),
            "price_component.symbol",
        )
        if symbol in seen_symbols:
            _block(
                f"formal_oos_replay_price_component_duplicate:{line_number}"
            )
        seen_symbols.add(symbol)
        event_date = _parse_date(
            _required_text(
                component.get("event_date"),
                "price_component.event_date",
            ),
            "price_component.event_date",
        )
        if event_date != _parse_date(
            _required_text(row.get("decision_date"), "row.decision_date"),
            "row.decision_date",
        ):
            _block(
                f"formal_oos_replay_price_component_date_mismatch:{line_number}"
            )
        available_at = _parse_datetime(
            _required_text(
                component.get("available_at"),
                "price_component.available_at",
            ),
            "price_component.available_at",
        )
        decision_at = _parse_datetime(
            _required_text(row.get("decision_at"), "row.decision_at"),
            "row.decision_at",
        )
        if available_at <= decision_at:
            _block(
                f"formal_oos_replay_price_component_not_forward:{line_number}"
            )
        open_int = _required_nonnegative_int(
            component.get("open_int"),
            "price_component.open_int",
        )
        close_int = _required_nonnegative_int(
            component.get("close_int"),
            "price_component.close_int",
        )
        open_scale = _required_int(
            component.get("open_scale"),
            "price_component.open_scale",
        )
        close_scale = _required_int(
            component.get("close_scale"),
            "price_component.close_scale",
        )
        if (
            open_int <= 0
            or close_int <= 0
            or open_scale <= 0
            or close_scale <= 0
        ):
            _block(
                f"formal_oos_replay_price_component_nonpositive:{line_number}"
            )
        canonical_prices.append(
            {
                "symbol": symbol,
                "event_date": event_date.isoformat(),
                "available_at": available_at.isoformat(timespec="seconds"),
                "open_int": open_int,
                "open_scale": open_scale,
                "close_int": close_int,
                "close_scale": close_scale,
                "volume_shares": _required_nonnegative_int(
                    component.get("volume_shares"),
                    "price_component.volume_shares",
                ),
                "source_values_hash": _required_sha256(
                    component.get("source_values_hash"),
                    "price_component.source_values_hash",
                ),
            }
        )
    expected_price_hash = _required_sha256(
        verification.get("price_source_set_hash"),
        "calculation_verification.price_source_set_hash",
    )
    if _payload_hash(canonical_prices) != expected_price_hash:
        _block(
            f"formal_oos_replay_price_component_hash_mismatch:{line_number}"
        )
    if canonical_prices:
        outcome_available_at = _parse_datetime(
            _required_text(
                row.get("outcome_available_at"),
                "row.outcome_available_at",
            ),
            "row.outcome_available_at",
        )
        component_outcome_at = max(
            _parse_datetime(
                _required_text(item["available_at"], "available_at"),
                "available_at",
            )
            for item in canonical_prices
        )
        if outcome_available_at != component_outcome_at:
            _block(
                "formal_oos_replay_outcome_component_availability_mismatch:"
                f"{line_number}"
            )
        _validate_price_components_against_sources(
            canonical_prices,
            replay_sources=replay_sources,
            line_number=line_number,
        )

    rule_components = _required_mapping(
        verification.get("rule"),
        "calculation_verification.rule",
    )
    states[(fold_id, "rule")] = _validate_lane_calculation(
        rule_components,
        metrics=rule,
        label=f"row[{line_number}].rule",
        prices=canonical_prices,
        previous=states.get((fold_id, "rule")),
    )
    lane_components: dict[int, Mapping[str, object]] = {}
    for index, component in enumerate(
        _mapping_sequence(
            verification.get("lanes"),
            "calculation_verification.lanes",
        )
    ):
        alpha = _required_int(
            component.get("alpha_bp"),
            f"calculation_verification.lanes[{index}].alpha_bp",
        )
        if alpha in lane_components:
            _block(
                f"formal_oos_replay_calculation_lane_duplicate:{line_number}"
            )
        payload = dict(component)
        payload.pop("alpha_bp", None)
        lane_components[alpha] = payload
    if tuple(sorted(lane_components)) != ALPHA_LANES:
        _block(
            f"formal_oos_replay_calculation_lanes_incomplete:{line_number}"
        )
    for alpha in ALPHA_LANES:
        key = (fold_id, f"lane:{alpha}")
        states[key] = _validate_lane_calculation(
            lane_components[alpha],
            metrics=lanes[alpha],
            label=f"row[{line_number}].lane[{alpha}]",
            prices=canonical_prices,
            previous=states.get(key),
        )
    if dict(lane_components[0]) != dict(rule_components):
        _block(
            f"formal_oos_replay_calculation_alpha_zero_not_rule:{line_number}"
        )


def _validate_lane_calculation(
    value: Mapping[str, object],
    *,
    metrics: Mapping[str, int],
    label: str,
    prices: Sequence[Mapping[str, object]],
    previous: _CalculationState | None,
) -> _CalculationState:
    if set(value) != {
        "opening_value_minor",
        "closing_value_minor",
        "transaction_cost_minor",
        "opening_cash_minor",
        "closing_cash_minor",
        "holdings",
        "before_weights",
        "after_trade_weights",
    }:
        _block(f"formal_oos_replay_calculation_fields_mismatch:{label}")
    opening = _required_int(
        value.get("opening_value_minor"),
        f"{label}.opening_value_minor",
    )
    closing = _required_nonnegative_int(
        value.get("closing_value_minor"),
        f"{label}.closing_value_minor",
    )
    cost = _required_nonnegative_int(
        value.get("transaction_cost_minor"),
        f"{label}.transaction_cost_minor",
    )
    if opening <= 0 or cost > opening:
        _block(f"formal_oos_replay_calculation_amount_invalid:{label}")
    opening_cash = _required_nonnegative_int(
        value.get("opening_cash_minor"),
        f"{label}.opening_cash_minor",
    )
    closing_cash = _required_nonnegative_int(
        value.get("closing_cash_minor"),
        f"{label}.closing_cash_minor",
    )
    holdings: dict[str, tuple[int, int]] = {}
    for index, item in enumerate(
        _mapping_sequence(value.get("holdings"), f"{label}.holdings")
    ):
        if set(item) != {
            "symbol",
            "opening_shares",
            "post_trade_shares",
        }:
            _block(f"formal_oos_replay_holding_fields_mismatch:{label}")
        symbol = _required_text(
            item.get("symbol"),
            f"{label}.holdings[{index}].symbol",
        )
        if symbol in holdings:
            _block(f"formal_oos_replay_holding_duplicate:{label}")
        holdings[symbol] = (
            _required_nonnegative_int(
                item.get("opening_shares"),
                f"{label}.holdings[{index}].opening_shares",
            ),
            _required_nonnegative_int(
                item.get("post_trade_shares"),
                f"{label}.holdings[{index}].post_trade_shares",
            ),
        )
    opening_shares = {
        symbol: values[0]
        for symbol, values in holdings.items()
        if values[0] > 0
    }
    post_trade_shares = {
        symbol: values[1]
        for symbol, values in holdings.items()
        if values[1] > 0
    }
    if previous is not None and (
        opening_cash != previous.closing_cash_minor
        or opening_shares != dict(previous.post_trade_shares)
        or opening != previous.closing_value_minor
    ):
        _block(f"formal_oos_replay_state_chain_mismatch:{label}")
    prices_by_symbol = {
        str(item["symbol"]): item for item in prices
    }
    required_symbols = set(opening_shares) | set(post_trade_shares)
    if not required_symbols.issubset(prices_by_symbol):
        _block(f"formal_oos_replay_holding_price_missing:{label}")
    current_open_value = Decimal(opening_cash)
    after_trade_open_value = Decimal(closing_cash)
    calculated_close_value = Decimal(closing_cash)
    calculated_cost = Decimal(0)
    expected_closing_cash = Decimal(opening_cash)
    for symbol in sorted(required_symbols):
        item = prices_by_symbol[symbol]
        open_price_minor = (
            Decimal(_required_int(item["open_int"], "open_int"))
            * Decimal(100)
            / Decimal(_required_int(item["open_scale"], "open_scale"))
        )
        close_price_minor = (
            Decimal(_required_int(item["close_int"], "close_int"))
            * Decimal(100)
            / Decimal(_required_int(item["close_scale"], "close_scale"))
        )
        before_shares = opening_shares.get(symbol, 0)
        after_shares = post_trade_shares.get(symbol, 0)
        current_open_value += Decimal(before_shares) * open_price_minor
        after_trade_open_value += Decimal(after_shares) * open_price_minor
        calculated_close_value += Decimal(after_shares) * close_price_minor
        delta = after_shares - before_shares
        if delta > 0:
            notional = Decimal(delta) * open_price_minor
            trade_cost = (
                notional
                * Decimal(
                    _required_int(
                        _REPLAY_POLICY["buy_cost_bp"],
                        "policy.buy_cost_bp",
                    )
                )
                / Decimal(10_000)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            expected_closing_cash -= notional + trade_cost
            calculated_cost += trade_cost
        elif delta < 0:
            notional = Decimal(-delta) * open_price_minor
            trade_cost = (
                notional
                * Decimal(
                    _required_int(
                        _REPLAY_POLICY["sell_cost_bp"],
                        "policy.sell_cost_bp",
                    )
                )
                / Decimal(10_000)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            expected_closing_cash += notional - trade_cost
            calculated_cost += trade_cost
    calculated_current_open = int(
        current_open_value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )
    calculated_after_trade_open = int(
        after_trade_open_value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )
    calculated_close = int(
        calculated_close_value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )
    calculated_cash = int(
        expected_closing_cash.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )
    if previous is None and opening != calculated_current_open:
        _block(f"formal_oos_replay_opening_value_recompute_mismatch:{label}")
    if (
        closing != calculated_close
        or closing_cash != calculated_cash
        or cost != int(calculated_cost)
    ):
        _block(f"formal_oos_replay_closing_value_recompute_mismatch:{label}")
    computed_return = int(
        (
            (
                Decimal(closing) / Decimal(opening)
                - Decimal(1)
            )
            * Decimal(10_000)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    )
    if computed_return != _metric(metrics, "after_cost_return_bp"):
        _block(f"formal_oos_replay_daily_return_recompute_mismatch:{label}")
    before = _calculation_weights(
        value.get("before_weights"),
        label=f"{label}.before_weights",
    )
    after = _calculation_weights(
        value.get("after_trade_weights"),
        label=f"{label}.after_trade_weights",
    )
    recomputed_before = _weights_from_minor_values(
        cash_minor=opening_cash,
        shares=opening_shares,
        prices=prices_by_symbol,
        price_field="open",
        total_minor=calculated_current_open,
    )
    recomputed_after = _weights_from_minor_values(
        cash_minor=closing_cash,
        shares=post_trade_shares,
        prices=prices_by_symbol,
        price_field="open",
        total_minor=calculated_after_trade_open,
    )
    if before != recomputed_before or after != recomputed_after:
        _block(f"formal_oos_replay_weight_recompute_mismatch:{label}")
    computed_turnover = sum(
        abs(before.get(key, 0) - after.get(key, 0))
        for key in set(before) | set(after)
    ) // 2
    if computed_turnover != _metric(metrics, "turnover_bp"):
        _block(f"formal_oos_replay_turnover_recompute_mismatch:{label}")
    return _CalculationState(
        closing_cash_minor=closing_cash,
        post_trade_shares=post_trade_shares,
        closing_value_minor=closing,
    )


def _weights_from_minor_values(
    *,
    cash_minor: int,
    shares: Mapping[str, int],
    prices: Mapping[str, Mapping[str, object]],
    price_field: str,
    total_minor: int,
) -> dict[str, int]:
    if total_minor <= 0:
        _block("formal_oos_replay_weight_total_not_positive")
    result: dict[str, int] = {}
    for symbol, count in sorted(shares.items()):
        item = prices[symbol]
        raw = _required_int(
            item[f"{price_field}_int"],
            f"{price_field}_int",
        )
        scale = _required_int(
            item[f"{price_field}_scale"],
            f"{price_field}_scale",
        )
        exact_minor = Decimal(count) * Decimal(raw) * Decimal(100) / Decimal(
            scale
        )
        result[symbol] = int(
            (
                exact_minor * Decimal(10_000) / Decimal(total_minor)
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
    result["CASH"] = 10_000 - sum(result.values())
    return result


def _calculation_weights(
    value: object,
    *,
    label: str,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, item in enumerate(_mapping_sequence(value, label)):
        if set(item) != {"key", "weight_bp"}:
            _block(f"formal_oos_replay_weight_fields_mismatch:{label}")
        key = _required_text(item.get("key"), f"{label}[{index}].key")
        if key in result:
            _block(f"formal_oos_replay_weight_duplicate:{label}")
        result[key] = _required_bp(
            item.get("weight_bp"),
            f"{label}[{index}].weight_bp",
        )
    if sum(result.values()) != 10_000 or "CASH" not in result:
        _block(f"formal_oos_replay_weight_contract_invalid:{label}")
    return result


def _aggregate_lanes(
    rows: Sequence[_DailyRow],
    outer_fold_ids: Sequence[str],
) -> list[dict[str, object]]:
    lanes: list[dict[str, object]] = []
    rule_returns = [
        _metric(row.rule, "after_cost_return_bp") for row in rows
    ]
    rule_turnover = [
        (row.decision_date, _metric(row.rule, "turnover_bp")) for row in rows
    ]
    rule_mdd = _maximum_drawdown_bp(rule_returns)
    rule_cvar = _cvar_loss_bp(rule_returns)
    rule_weekly_turnover = _maximum_weekly_turnover_bp(rule_turnover)
    for alpha in ALPHA_LANES:
        fold_rows: list[dict[str, object]] = []
        for fold_id in outer_fold_ids:
            selected = [row for row in rows if row.fold_id == fold_id]
            if not selected:
                _block(f"formal_oos_replay_fold_has_no_daily_rows:{fold_id}")
            daily_excess = [
                _metric(row.lanes[alpha], "after_cost_return_bp")
                - _metric(row.rule, "after_cost_return_bp")
                for row in selected
            ]
            fold_rows.append(
                {
                    "fold_id": fold_id,
                    "after_cost_excess_vs_rule_bp": (
                        _relative_compounded_excess_bp(
                            [
                                _metric(
                                    row.lanes[alpha],
                                    "after_cost_return_bp",
                                )
                                for row in selected
                            ],
                            [
                                _metric(
                                    row.rule,
                                    "after_cost_return_bp",
                                )
                                for row in selected
                            ],
                        )
                    ),
                    "daily_after_cost_excess_vs_rule_bp": daily_excess,
                }
            )
        lane_returns = [
            _metric(row.lanes[alpha], "after_cost_return_bp") for row in rows
        ]
        lane_turnover_rows = [
            (row.decision_date, _metric(row.lanes[alpha], "turnover_bp"))
            for row in rows
        ]
        weekly_turnover = _maximum_weekly_turnover_bp(lane_turnover_rows)
        lane: dict[str, object] = {
            "alpha_bp": alpha,
            "folds": fold_rows,
            "winning_fold_count": sum(
                cast(int, fold["after_cost_excess_vs_rule_bp"]) > 0
                for fold in fold_rows
            ),
            "mdd_worsening_vs_rule_bp": (
                _maximum_drawdown_bp(lane_returns) - rule_mdd
            ),
            "cvar_worsening_vs_rule_bp": (
                _cvar_loss_bp(lane_returns) - rule_cvar
            ),
            "weekly_turnover_bp": weekly_turnover,
            "turnover_increment_vs_rule_bp": max(
                0,
                weekly_turnover - rule_weekly_turnover,
            ),
        }
        for field_name in (
            "core_coverage_bp",
            "enriched_coverage_bp",
            "feasible_fill_coverage_bp",
        ):
            lane[field_name] = _conservative_average_bp(
                _metric(row.lanes[alpha], field_name) for row in rows
            )
        for field_name in (
            "pit_violation_count",
            "future_prefix_violation_count",
            "constraint_violation_count",
        ):
            lane[field_name] = sum(
                _metric(row.lanes[alpha], field_name) for row in rows
            )
        lanes.append(lane)
    return lanes


def _relative_compounded_excess_bp(
    lane_returns_bp: Sequence[int],
    rule_returns_bp: Sequence[int],
) -> int:
    lane_wealth = _compound_wealth(lane_returns_bp)
    rule_wealth = _compound_wealth(rule_returns_bp)
    if rule_wealth <= 0:
        _block("formal_oos_replay_rule_wealth_not_positive")
    value = (lane_wealth / rule_wealth - Decimal(1)) * Decimal(10_000)
    return int(value.to_integral_value(rounding=ROUND_HALF_EVEN))


def _compound_wealth(returns_bp: Sequence[int]) -> Decimal:
    wealth = Decimal(1)
    for value in returns_bp:
        if value <= -10_000:
            _block("formal_oos_replay_daily_return_below_minus_10000")
        wealth *= (Decimal(10_000) + Decimal(value)) / Decimal(10_000)
    return wealth


def _maximum_drawdown_bp(returns_bp: Sequence[int]) -> int:
    wealth = Decimal(1)
    peak = Decimal(1)
    maximum = Decimal(0)
    for value in returns_bp:
        wealth *= (Decimal(10_000) + Decimal(value)) / Decimal(10_000)
        peak = max(peak, wealth)
        drawdown = (peak - wealth) / peak * Decimal(10_000)
        maximum = max(maximum, drawdown)
    return int(maximum.to_integral_value(rounding=ROUND_CEILING))


def _cvar_loss_bp(returns_bp: Sequence[int]) -> int:
    if not returns_bp:
        _block("formal_oos_replay_cvar_input_empty")
    tail_count = max(
        1,
        int(
            (
                Decimal(len(returns_bp)) * Decimal(5) / Decimal(100)
            ).to_integral_value(rounding=ROUND_CEILING)
        ),
    )
    tail = sorted(returns_bp)[:tail_count]
    mean = sum(Decimal(value) for value in tail) / Decimal(tail_count)
    loss = max(Decimal(0), -mean)
    return int(loss.to_integral_value(rounding=ROUND_CEILING))


def _maximum_weekly_turnover_bp(
    values: Sequence[tuple[date, int]],
) -> int:
    weekly: dict[tuple[int, int], int] = {}
    for decision_date, turnover in values:
        iso = decision_date.isocalendar()
        key = (iso.year, iso.week)
        weekly[key] = weekly.get(key, 0) + turnover
    return max(weekly.values(), default=0)


def _conservative_average_bp(values: Iterable[int]) -> int:
    materialized = tuple(values)
    if not materialized:
        _block("formal_oos_replay_coverage_input_empty")
    average = sum(Decimal(value) for value in materialized) / Decimal(
        len(materialized)
    )
    return int(average.to_integral_value(rounding=ROUND_FLOOR))


def _publish_blocked(
    request: AllocationOOSPortfolioReplayRequest,
    *,
    blockers: Sequence[str],
    custody: _FormalCustody | None,
) -> AllocationOOSPortfolioReplayResult:
    normalized = tuple(sorted(set(blockers)))
    body: dict[str, object] = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "status": "blocked",
        "replay_run_id": request.replay_run_id,
        "replay_role": request.role,
        "replay_as_of": request.replay_as_of.isoformat(timespec="seconds"),
        "formal_source_only": True,
        "research_shadow_included": False,
        "research_only": False,
        "input_custody": (
            None if custody is None else dict(custody.input_custody)
        ),
        "blockers": list(normalized),
        "blocker_set_hash": _payload_hash(list(normalized)),
        "promotion_eligible_input": False,
        "production_alpha_bp": 0,
        "formal_oos_allowed": False,
        "broker_order_allowed": False,
    }
    return _publish(
        request,
        payload=_with_logical_hash(body, "manifest_hash"),
        blockers=normalized,
        replay_result_hash=None,
    )


def _publish(
    request: AllocationOOSPortfolioReplayRequest,
    *,
    payload: Mapping[str, object],
    blockers: tuple[str, ...],
    replay_result_hash: str | None,
) -> AllocationOOSPortfolioReplayResult:
    role_root = request.output_root.resolve() / request.role
    bucket = "runs" if payload.get("status") == "complete" else "blocked"
    final_directory = role_root / bucket / request.replay_run_id
    replay_path = final_directory / "replay.json"
    idempotent = False
    if replay_path.is_file():
        existing = _read_json_mapping(replay_path, "existing_replay")
        if dict(existing) != dict(payload):
            raise ValueError("immutable replay_run_id collision")
        idempotent = True
    else:
        final_directory.mkdir(parents=True, exist_ok=False)
        _atomic_write_json(replay_path, payload)
    replay_file_hash = _file_hash(replay_path)
    pointer_path = role_root / "latest_replay.json"
    pointer_updated = False
    if payload.get("status") == "complete":
        assert replay_result_hash is not None
        pointer_body: dict[str, object] = {
            "schema_version": REPLAY_POINTER_SCHEMA_VERSION,
            "status": "complete",
            "replay_path": str(replay_path.resolve()),
            "replay_file_hash": replay_file_hash,
            "replay_result_hash": replay_result_hash,
            "replay_run_id": request.replay_run_id,
            "replay_role": request.role,
            "input_custody": payload["input_custody"],
        }
        pointer = _with_logical_hash(pointer_body, "pointer_hash")
        _atomic_write_json(pointer_path, pointer)
        pointer_updated = True
    return AllocationOOSPortfolioReplayResult(
        status=str(payload["status"]),
        replay_run_id=request.replay_run_id,
        role=request.role,
        blockers=blockers,
        replay_path=replay_path.resolve(),
        replay_file_hash=replay_file_hash,
        replay_result_hash=replay_result_hash,
        manifest_hash=_required_sha256(
            payload.get("manifest_hash"),
            "manifest_hash",
        ),
        latest_pointer_path=pointer_path.resolve(),
        latest_pointer_updated=pointer_updated,
        idempotent=idempotent,
    )


def _validate_artifact_directory(
    directory: Path,
    *,
    expected_schema: str,
    blocker_prefix: str,
) -> Mapping[str, object]:
    manifest_path = directory / "manifest.json"
    _require_file(manifest_path, f"{blocker_prefix}_manifest_missing")
    manifest = _read_json_mapping(manifest_path, f"{blocker_prefix}.manifest")
    if manifest.get("schema_version") != expected_schema:
        _block(f"{blocker_prefix}_schema_mismatch")
    _verify_logical_hash(
        manifest,
        "manifest_hash",
        f"{blocker_prefix}_manifest_hash_mismatch",
    )
    artifacts = _mapping_sequence(
        manifest.get("artifacts"),
        f"{blocker_prefix}.artifacts",
    )
    if not artifacts:
        _block(f"{blocker_prefix}_artifact_files_missing")
    for item in artifacts:
        path = _contained_path(
            directory,
            _required_text(item.get("path"), "artifact.path"),
            f"{blocker_prefix}_artifact_path_escapes_directory",
        )
        _require_file(path, f"{blocker_prefix}_artifact_file_missing")
        if _file_hash(path) != _required_sha256(
            item.get("file_sha256"),
            "artifact.file_sha256",
        ):
            _block(f"{blocker_prefix}_artifact_file_hash_mismatch")
        if path.stat().st_size != _required_nonnegative_int(
            item.get("byte_count"),
            "artifact.byte_count",
        ):
            _block(f"{blocker_prefix}_artifact_byte_count_mismatch")
    return manifest


def _validate_meta_artifact_contract(
    manifest: Mapping[str, object],
    *,
    blocker_prefix: str,
    require_oof: bool,
) -> None:
    target_fields = tuple(
        _required_text(item, f"{blocker_prefix}.target_field")
        for item in _required_sequence(
            manifest.get("target_fields"),
            f"{blocker_prefix}.target_fields",
        )
    )
    if target_fields != META_TARGET_FIELDS:
        _block(f"{blocker_prefix}_target_fields_mismatch")
    head_ids = tuple(
        _required_text(
            item.get("head_id"),
            f"{blocker_prefix}.head_model.head_id",
        )
        for item in _mapping_sequence(
            manifest.get("head_models"),
            f"{blocker_prefix}.head_models",
        )
    )
    if head_ids != META_TARGET_FIELDS:
        _block(f"{blocker_prefix}_head_models_mismatch")
    if not require_oof:
        if manifest.get("oof_shape") is not None or (
            manifest.get("oof_dtype") is not None
        ):
            _block(f"{blocker_prefix}_unexpected_oof")
        return
    shape = tuple(
        _required_nonnegative_int(
            item,
            f"{blocker_prefix}.oof_shape",
        )
        for item in _required_sequence(
            manifest.get("oof_shape"),
            f"{blocker_prefix}.oof_shape",
        )
    )
    test_rows = _required_nonnegative_int(
        manifest.get("test_row_count"),
        f"{blocker_prefix}.test_row_count",
    )
    if (
        shape != (test_rows, len(META_TARGET_FIELDS))
        or manifest.get("oof_dtype") != "<i4"
    ):
        _block(f"{blocker_prefix}_oof_shape_or_dtype_mismatch")
    oof = next(
        (
            item
            for item in _mapping_sequence(
                manifest.get("artifacts"),
                f"{blocker_prefix}.artifacts",
            )
            if Path(
                _required_text(item.get("path"), "artifact.path")
            ).name
            == "oof.i32"
        ),
        None,
    )
    if oof is None or _required_nonnegative_int(
        oof.get("byte_count"),
        f"{blocker_prefix}.oof.byte_count",
    ) != test_rows * len(META_TARGET_FIELDS) * 4:
        _block(f"{blocker_prefix}_oof_byte_count_mismatch")


def _oof_entry(
    directory: Path,
    manifest: Mapping[str, object],
    kind: str,
) -> Mapping[str, object]:
    artifacts = _mapping_sequence(manifest.get("artifacts"), "artifacts")
    oof = next(
        (
            item
            for item in artifacts
            if Path(_required_text(item.get("path"), "artifact.path")).name
            == "oof.i32"
        ),
        None,
    )
    if oof is None:
        _block(f"{kind}_oof_file_missing")
    assert oof is not None
    path = _contained_path(
        directory,
        _required_text(oof.get("path"), "oof.path"),
        f"{kind}_oof_path_escapes_directory",
    )
    return {
        "kind": kind,
        "fold_id": _required_text(manifest.get("fold_id"), "fold_id"),
        "expert_id": manifest.get("expert_id"),
        "artifact_manifest_hash": _required_sha256(
            manifest.get("manifest_hash"),
            "artifact_manifest_hash",
        ),
        "artifact_manifest_file_hash": _file_hash(
            directory / "manifest.json"
        ),
        "oof_file_hash": _file_hash(path),
        "oof_byte_count": path.stat().st_size,
        "oof_shape": manifest.get("oof_shape"),
        "oof_dtype": manifest.get("oof_dtype"),
    }


def _with_logical_hash(
    body: Mapping[str, object],
    field_name: str,
) -> dict[str, object]:
    result = dict(body)
    result[field_name] = _payload_hash(result)
    return result


def _verify_logical_hash(
    value: Mapping[str, object],
    field_name: str,
    blocker: str,
) -> None:
    expected = _required_sha256(value.get(field_name), field_name)
    body = dict(value)
    body.pop(field_name, None)
    if _payload_hash(body) != expected:
        _block(blocker)


def _require_formal_lane(
    value: Mapping[str, object],
    label: str,
) -> None:
    if value.get("formal_source_only") is not True:
        _block(f"{label}_formal_source_marker_missing")
    if value.get("research_shadow_included") is not False:
        _block(f"{label}_research_lane_forbidden")
    if value.get("research_only") not in {None, False}:
        _block(f"{label}_research_lane_forbidden")


def _contained_path(root: Path, value: str, blocker: str) -> Path:
    candidate = (
        Path(value).resolve()
        if Path(value).is_absolute()
        else (root / value).resolve()
    )
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        _block(blocker)
    return candidate


def _mapping_sequence(
    value: object,
    label: str,
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _required_mapping(item, f"{label}[{index}]")
        for index, item in enumerate(_required_sequence(value, label))
    )


def _required_sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return cast(Mapping[str, object], value)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be a non-empty string")
    return value


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _required_nonnegative_int(value: object, label: str) -> int:
    result = _required_int(value, label)
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result


def _required_bp(value: object, label: str) -> int:
    result = _required_int(value, label)
    if not 0 <= result <= 10_000:
        raise ValueError(f"{label} must be within 0..10000 bp")
    return result


def _required_sha256(value: object, label: str) -> str:
    text = _required_text(value, label)
    digest = text[7:] if text.startswith(_SHA256_PREFIX) else ""
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError(f"{label} must be a sha256 digest")
    return text


def _metric(value: Mapping[str, int], field_name: str) -> int:
    return value[field_name]


def _parse_date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _parse_datetime(value: str, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO datetime") from exc
    if result.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return result


def _read_json_mapping(path: Path, label: str) -> Mapping[str, object]:
    return _required_mapping(
        json.loads(path.read_text(encoding="utf-8")),
        label,
    )


def _require_file(path: Path, blocker: str) -> None:
    if not path.is_file():
        _block(blocker)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    digest = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
    return f"{_SHA256_PREFIX}{digest}"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"{_SHA256_PREFIX}{digest.hexdigest()}"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        _write_json(temporary, value)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_reason(exc: BaseException) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ")[:240]


def _block(reason: str) -> None:
    raise _ReplayBlocked((reason,))


__all__ = [
    "ALPHA_LANES",
    "AllocationOOSPortfolioReplayRequest",
    "AllocationOOSPortfolioReplayResult",
    "REPLAY_INPUT_SCHEMA_VERSION",
    "REPLAY_POINTER_SCHEMA_VERSION",
    "REPLAY_ROW_SCHEMA_VERSION",
    "REPLAY_SCHEMA_VERSION",
    "build_allocation_oos_portfolio_replay",
]
