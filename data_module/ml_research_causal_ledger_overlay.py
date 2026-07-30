"""Research-only T-1 recursive Rule/Risk Budget/Inverse-Vol ledger overlay。

輸入必須是已隔離的 research-shadow training union。第一遍只讀 causal features
並逐 decision date 遞推 baseline portfolio；future teacher targets 不得回灌狀態。
第二遍把已落帳的 T-1 state、rule_portfolio_health features 與相對該狀態的 delta
labels 寫回新 publication。Formal consumer 永遠拒絕此資料集。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from ml_module.allocation_contracts import (
    AllocationWeightContract,
    CausalPortfolioState,
)
from scripts.train_ml_allocation_copilot import _parse_sample


PUBLICATION_SCHEMA_VERSION = "portfolio-ml-training-shards.v2"
RECORD_SCHEMA_VERSION = "allocation-training-jsonl-v2"
LEDGER_SCHEMA_VERSION = "research-causal-baseline-ledger.v1"
OVERLAY_SCHEMA_VERSION = "research-causal-ledger-overlay.v1"
_SHA256_PREFIX = "sha256:"
_RULE_SOURCE_ID = "derived:research_causal_rule_risk_inverse_vol_ledger"
_RULE_FEATURE_IDS = (
    "rule_portfolio_health.cash_bp",
    "rule_portfolio_health.current_symbol_weight_bp",
    "rule_portfolio_health.invested_bp",
    "rule_portfolio_health.position_count",
    "rule_portfolio_health.state_complete_flag",
    "rule_portfolio_health.weekly_turnover_used_bp",
)


@dataclass(frozen=True)
class ResearchCausalLedgerOverlayRequest:
    research_union_manifest_path: Path
    output_root: Path
    risky_budget_bp: int = 8_000
    max_positions: int = 8
    max_single_position_bp: int = 1_500
    minimum_cash_bp: int = 2_000
    weekly_turnover_cap_bp: int = 2_000
    rebalance_band_bp: int = 300
    minimum_trade_bp: int = 200
    cooldown_trading_days: int = 5
    buy_cost_bp: int = 25
    sell_cost_bp: int = 55
    grid_bp: int = 100
    compression_level: int = 6

    def __post_init__(self) -> None:
        for field_name in (
            "risky_budget_bp",
            "max_positions",
            "max_single_position_bp",
            "minimum_cash_bp",
            "weekly_turnover_cap_bp",
            "rebalance_band_bp",
            "minimum_trade_bp",
            "cooldown_trading_days",
            "buy_cost_bp",
            "sell_cost_bp",
            "grid_bp",
            "compression_level",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value < 0:
                raise ValueError(f"{field_name} must be nonnegative")
        if self.max_positions < 1 or self.max_positions > 8:
            raise ValueError("max_positions must be within 1..8")
        if self.max_single_position_bp > 1_500:
            raise ValueError("max_single_position_bp must not exceed 1500")
        if self.minimum_cash_bp < 2_000:
            raise ValueError("minimum_cash_bp must be at least 2000")
        if self.risky_budget_bp > 10_000 - self.minimum_cash_bp:
            raise ValueError("risky budget violates minimum cash")
        if self.weekly_turnover_cap_bp > 2_000:
            raise ValueError("weekly turnover cap must not exceed 2000")
        if self.grid_bp != 100:
            raise ValueError("research baseline grid must equal 100 bp")
        if not 0 <= self.compression_level <= 9:
            raise ValueError("compression_level must be within 0..9")


@dataclass(frozen=True)
class ResearchCausalLedgerOverlayPublication:
    publication_id: str
    publication_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    dataset_identity_hash: str
    ledger_manifest_hash: str
    sample_count: int
    non_cash_state_day_count: int
    add_transition_count: int
    reduce_transition_count: int


@dataclass
class _LedgerRuntime:
    state: CausalPortfolioState | None
    week_key: tuple[int, int] | None
    price_history: dict[str, list[tuple[str, int, int]]]
    last_trade_index: dict[str, int]
    chain_hash: str
    decision_index: int = 0


class ResearchCausalLedgerOverlayBuilder:
    """建立不污染 Formal 的 deterministic recursive research ledger。"""

    def build(
        self,
        request: ResearchCausalLedgerOverlayRequest,
    ) -> ResearchCausalLedgerOverlayPublication:
        source_path = request.research_union_manifest_path.resolve()
        source = _read_json(source_path)
        _validate_source_manifest(source)
        source_file_hash = _file_sha256(source_path)
        policy = _policy_payload(request)
        policy_hash = _sha256_json(policy)
        identity = {
            "schema_version": OVERLAY_SCHEMA_VERSION,
            "source_manifest_hash": source["manifest_hash"],
            "source_manifest_file_hash": source_file_hash,
            "policy_hash": policy_hash,
        }
        output_root = request.output_root.resolve()
        runs_root = output_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=".research-ledger-", dir=output_root)
        )
        ledger_path = staging / "causal_ledger.sqlite"
        try:
            ledger_summary = _simulate_ledger(
                source_manifest_path=source_path,
                source_manifest=source,
                ledger_path=ledger_path,
                request=request,
                policy_hash=policy_hash,
            )
            ledger_manifest_hash = _sha256_json(
                {
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "source_manifest_hash": source["manifest_hash"],
                    "policy": policy,
                    **ledger_summary,
                }
            )
            feature_registry = _overlay_feature_registry(
                source,
                ledger_manifest_hash=ledger_manifest_hash,
            )
            feature_registry_hash = _sha256_json(feature_registry)
            source_manifest_hashes = _overlay_source_hashes(
                source,
                ledger_manifest_hash=ledger_manifest_hash,
            )
            dataset_identity_hash = _sha256_json(
                {
                    **identity,
                    "ledger_manifest_hash": ledger_manifest_hash,
                    "feature_registry_hash": feature_registry_hash,
                    "source_manifest_hashes": source_manifest_hashes,
                    "research_only": True,
                }
            )
            writers = _WriterRegistry(
                staging=staging,
                compression_level=request.compression_level,
            )
            writers.configure(
                {
                    "record_type": "header",
                    "schema_version": RECORD_SCHEMA_VERSION,
                    "direct_training_input": True,
                    "dataset_id": (
                        "research_shadow_causal_allocation_ledger"
                    ),
                    "dataset_identity_hash": dataset_identity_hash,
                    "training_as_of": source["training_as_of"],
                    "horizons": source["horizons"],
                    "feature_packs": source["feature_packs"],
                    "folds": source["folds"],
                    "assembly_blockers": sorted(
                        {
                            *(
                                str(value)
                                for value in source.get(
                                    "assembly_blockers", []
                                )
                                if str(value)
                                != (
                                    "portfolio_ledger_missing_cash_only_"
                                    "fallback_turnover_and_cooldown_not_"
                                    "learned"
                                )
                            ),
                            "research_causal_ledger_not_formal_source",
                        }
                    ),
                    "feature_registry_hash": feature_registry_hash,
                    "source_manifest_hashes": [
                        list(item) for item in source_manifest_hashes
                    ],
                    "portfolio_state_policy": {
                        "schema_version": LEDGER_SCHEMA_VERSION,
                        "ledger_manifest_hash": ledger_manifest_hash,
                        "policy": policy,
                        "reads_same_day_advice": False,
                        "oracle_teacher_state_allowed": False,
                        "teacher_targets_replayed_into_state": False,
                        "cash_only_fallback": False,
                    },
                    "label_policy": source.get("label_policy", {}),
                }
            )
            try:
                sample_count = _rewrite_samples(
                    source_manifest_path=source_path,
                    source_manifest=source,
                    ledger_path=ledger_path,
                    writers=writers,
                    dataset_identity_hash=dataset_identity_hash,
                    feature_registry_hash=feature_registry_hash,
                    source_manifest_hashes=source_manifest_hashes,
                    ledger_manifest_hash=ledger_manifest_hash,
                    policy=policy,
                )
            finally:
                writers.close_all()
            shards = writers.manifest_payloads(staging=staging)
            if sample_count != int(source["sample_count"]):
                raise ValueError("causal ledger overlay sample coverage mismatch")
            publication_identity = {
                **identity,
                "dataset_identity_hash": dataset_identity_hash,
                "ledger_manifest_hash": ledger_manifest_hash,
                "shards": [
                    {
                        "year": item["year"],
                        "content_sha256": item["content_sha256"],
                    }
                    for item in shards
                ],
            }
            publication_id = (
                "research-ledger-"
                + _sha256_json(publication_identity)[7:31]
            )
            final_directory = runs_root / publication_id
            manifest: dict[str, Any] = {
                "schema_version": PUBLICATION_SCHEMA_VERSION,
                "publication_id": publication_id,
                "stage": "research_causal_recursive_ledger_overlay",
                "direct_training_input": True,
                "target_cli": "scripts/train_ml_research_shadow_challenger.py",
                "target_schema_version": RECORD_SCHEMA_VERSION,
                "dataset_id": "research_shadow_causal_allocation_ledger",
                "dataset_identity_hash": dataset_identity_hash,
                "feature_registry_hash": feature_registry_hash,
                "source_identity": identity,
                "source_manifest_hashes": [
                    list(item) for item in source_manifest_hashes
                ],
                "training_as_of": source["training_as_of"],
                "horizons": source["horizons"],
                "feature_packs": source["feature_packs"],
                "feature_pack_dispositions": source.get(
                    "feature_pack_dispositions", []
                ),
                "feature_registry": feature_registry,
                "feature_count": source["feature_count"],
                "folds": source["folds"],
                "fold_count": source["fold_count"],
                "sample_count": sample_count,
                "scope": source.get("scope"),
                "causal_ledger": {
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "sqlite_path": ledger_path.name,
                    "sqlite_file_hash": _file_sha256(ledger_path),
                    "manifest_hash": ledger_manifest_hash,
                    "policy": policy,
                    **ledger_summary,
                    "algorithm": (
                        "rule_momentum_filter_then_inverse_realized_"
                        "volatility_risk_budget"
                    ),
                    "inputs": (
                        "T_minus_1_price_features_and_prior_ledger_state"
                    ),
                    "future_teacher_target_used_for_state": False,
                    "same_day_advice_used_for_state": False,
                    "append_only": True,
                },
                "assembly_blockers": sorted(
                    {
                        *(
                            str(value)
                            for value in source.get(
                                "assembly_blockers", []
                            )
                            if str(value)
                            != (
                                "portfolio_ledger_missing_cash_only_"
                                "fallback_turnover_and_cooldown_not_"
                                "learned"
                            )
                        ),
                        "research_causal_ledger_not_formal_source",
                        "research_shadow_dataset_permanently_ineligible_for_promotion",
                        "thesis_health_exit_history_unavailable",
                    }
                ),
                "research_only": True,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "production_action_allowed": False,
                "promotion_eligible": False,
                "broker_order_allowed": False,
                "formal_consumer_compatible": False,
                "safety": {
                    "T_minus_1_recursive_portfolio_state": True,
                    "future_teacher_targets_feed_next_state": False,
                    "same_day_advice_read_allowed": False,
                    "integer_bp_state_and_costs": True,
                    "weekly_turnover_cap_enforced": True,
                    "cooldown_enforced": True,
                    "deterministic_transition_chain": True,
                    "formal_dataset": False,
                    "formal_orchestrator_load_allowed": False,
                    "promotion_consumer_load_allowed": False,
                    "production_alpha_bp": 0,
                },
                "execution": {
                    "two_pass_streaming": True,
                    "one_decision_date_group_in_memory": True,
                    "append_only_sqlite_ledger": True,
                    "training_jsonl_rewritten": True,
                    "parquet_dependency_added": False,
                },
                "shards": shards,
            }
            manifest["manifest_hash"] = _sha256_json(manifest)
            _write_json(staging / "manifest.json", manifest)
            if final_directory.exists():
                existing = _read_json(final_directory / "manifest.json")
                if existing.get("manifest_hash") != manifest["manifest_hash"]:
                    raise FileExistsError(
                        "research ledger publication id collision"
                    )
                _safe_remove_tree(staging, output_root)
            else:
                os.replace(staging, final_directory)
            latest_path = output_root / "latest_manifest.json"
            _atomic_write_json(
                latest_path,
                {
                    "schema_version": "research-causal-ledger-latest.v1",
                    "publication_id": publication_id,
                    "manifest_path": (
                        f"runs/{publication_id}/manifest.json"
                    ),
                    "manifest_hash": manifest["manifest_hash"],
                    "research_only": True,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                },
            )
            return ResearchCausalLedgerOverlayPublication(
                publication_id=publication_id,
                publication_directory=final_directory,
                manifest_path=final_directory / "manifest.json",
                latest_manifest_path=latest_path,
                manifest_hash=str(manifest["manifest_hash"]),
                dataset_identity_hash=dataset_identity_hash,
                ledger_manifest_hash=ledger_manifest_hash,
                sample_count=sample_count,
                non_cash_state_day_count=int(
                    ledger_summary["non_cash_state_day_count"]
                ),
                add_transition_count=int(
                    ledger_summary["add_transition_count"]
                ),
                reduce_transition_count=int(
                    ledger_summary["reduce_transition_count"]
                ),
            )
        except Exception:
            if staging.exists():
                _safe_remove_tree(staging, output_root)
            raise


def _simulate_ledger(
    *,
    source_manifest_path: Path,
    source_manifest: Mapping[str, Any],
    ledger_path: Path,
    request: ResearchCausalLedgerOverlayRequest,
    policy_hash: str,
) -> dict[str, Any]:
    connection = sqlite3.connect(ledger_path)
    try:
        return _simulate_ledger_open_connection(
            connection=connection,
            source_manifest_path=source_manifest_path,
            source_manifest=source_manifest,
            request=request,
            policy_hash=policy_hash,
        )
    finally:
        connection.close()


def _simulate_ledger_open_connection(
    *,
    connection: sqlite3.Connection,
    source_manifest_path: Path,
    source_manifest: Mapping[str, Any],
    request: ResearchCausalLedgerOverlayRequest,
    policy_hash: str,
) -> dict[str, Any]:
    connection.executescript(
        """
        CREATE TABLE transitions (
            decision_date TEXT PRIMARY KEY,
            input_state_json TEXT NOT NULL,
            desired_weights_json TEXT NOT NULL,
            output_state_json TEXT NOT NULL,
            feature_input_hash TEXT NOT NULL,
            buy_turnover_bp INTEGER NOT NULL,
            sell_turnover_bp INTEGER NOT NULL,
            canonical_turnover_bp INTEGER NOT NULL,
            estimated_cost_bp INTEGER NOT NULL,
            add_count INTEGER NOT NULL,
            reduce_count INTEGER NOT NULL,
            transition_hash TEXT NOT NULL UNIQUE,
            chain_hash TEXT NOT NULL UNIQUE
        );
        CREATE TRIGGER transitions_no_update
        BEFORE UPDATE ON transitions
        BEGIN
            SELECT RAISE(ABORT, 'append-only ledger');
        END;
        CREATE TRIGGER transitions_no_delete
        BEFORE DELETE ON transitions
        BEGIN
            SELECT RAISE(ABORT, 'append-only ledger');
        END;
        """
    )
    runtime = _LedgerRuntime(
        state=None,
        week_key=None,
        price_history={},
        last_trade_index={},
        chain_hash=_sha256_json(
            {
                "genesis": True,
                "source_manifest_hash": source_manifest["manifest_hash"],
                "policy_hash": policy_hash,
            }
        ),
    )
    counts = {
        "decision_day_count": 0,
        "non_cash_state_day_count": 0,
        "add_transition_count": 0,
        "reduce_transition_count": 0,
        "hold_transition_count": 0,
        "total_turnover_bp": 0,
        "total_estimated_cost_bp": 0,
    }
    for decision_date, samples in _iter_decision_groups(
        source_manifest_path,
        source_manifest,
    ):
        first_state = samples[0]["row"]["portfolio_state"]
        if runtime.state is None:
            runtime.state = _state_from_payload(first_state)
        iso = date.fromisoformat(decision_date).isocalendar()
        week_key = (iso.year, iso.week)
        if runtime.week_key is not None and week_key != runtime.week_key:
            runtime.state = CausalPortfolioState.create(
                as_of_date=runtime.state.as_of_date,
                weights=runtime.state.weights,
                weekly_turnover_used_bp=0,
            )
        runtime.week_key = week_key
        input_state = runtime.state
        assert input_state is not None
        if input_state.weights.invested_bp > 0:
            counts["non_cash_state_day_count"] += 1
        signals, feature_input_hash = _causal_signals(
            samples=samples,
            runtime=runtime,
        )
        desired = _desired_weights(
            signals=signals,
            request=request,
        )
        (
            executed,
            buy_turnover,
            sell_turnover,
            canonical_turnover,
            estimated_cost,
            add_count,
            reduce_count,
        ) = _execute_rebalance(
            current=input_state.weights,
            desired=desired,
            weekly_turnover_used_bp=(
                input_state.weekly_turnover_used_bp
            ),
            runtime=runtime,
            request=request,
        )
        next_state = CausalPortfolioState.create(
            as_of_date=decision_date,
            weights=executed,
            weekly_turnover_used_bp=(
                input_state.weekly_turnover_used_bp
                + canonical_turnover
            ),
        )
        transition_payload = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "decision_date": decision_date,
            "input_state_hash": input_state.state_hash,
            "feature_input_hash": feature_input_hash,
            "desired_weights": _weight_payload(desired),
            "output_state_hash": next_state.state_hash,
            "buy_turnover_bp": buy_turnover,
            "sell_turnover_bp": sell_turnover,
            "canonical_turnover_bp": canonical_turnover,
            "estimated_cost_bp": estimated_cost,
            "add_count": add_count,
            "reduce_count": reduce_count,
            "future_teacher_target_used": False,
            "same_day_advice_used": False,
        }
        transition_hash = _sha256_json(transition_payload)
        runtime.chain_hash = _sha256_json(
            {
                "previous_chain_hash": runtime.chain_hash,
                "transition_hash": transition_hash,
            }
        )
        connection.execute(
            """
            INSERT INTO transitions(
                decision_date, input_state_json, desired_weights_json,
                output_state_json, feature_input_hash, buy_turnover_bp,
                sell_turnover_bp, canonical_turnover_bp, estimated_cost_bp,
                add_count, reduce_count, transition_hash, chain_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_date,
                _canonical_json(_state_payload(input_state)),
                _canonical_json(_weight_payload(desired)),
                _canonical_json(_state_payload(next_state)),
                feature_input_hash,
                buy_turnover,
                sell_turnover,
                canonical_turnover,
                estimated_cost,
                add_count,
                reduce_count,
                transition_hash,
                runtime.chain_hash,
            ),
        )
        connection.commit()
        runtime.state = next_state
        runtime.decision_index += 1
        counts["decision_day_count"] += 1
        counts["add_transition_count"] += add_count
        counts["reduce_transition_count"] += reduce_count
        counts["hold_transition_count"] += int(
            add_count == 0 and reduce_count == 0
        )
        counts["total_turnover_bp"] += canonical_turnover
        counts["total_estimated_cost_bp"] += estimated_cost
    return {
        **counts,
        "transition_chain_hash": runtime.chain_hash,
        "policy_hash": policy_hash,
        "deterministic_replay": True,
        "state_unit": "integer_bp",
        "cost_unit": "integer_bp",
    }


def _causal_signals(
    *,
    samples: Sequence[Mapping[str, Any]],
    runtime: _LedgerRuntime,
) -> tuple[list[tuple[str, int, int]], str]:
    signals: list[tuple[str, int, int]] = []
    inputs: list[dict[str, Any]] = []
    for sample in samples:
        row = _mapping(sample.get("row"), "sample.row")
        symbol = str(row["symbol"])
        features = _mapping_sequence(
            row.get("features"),
            "row.features",
        )
        close = _close_feature(features)
        if close is None:
            continue
        event_date, value_int, scale, content_hash = close
        history = runtime.price_history.setdefault(symbol, [])
        if not history or history[-1][0] != event_date:
            history.append((event_date, value_int, scale))
            if len(history) > 61:
                del history[:-61]
        returns = _return_series_bp(history[-21:])
        momentum_bp = (
            0
            if len(history) < 2
            else _scaled_return_bp(history[max(0, len(history) - 21)], history[-1])
        )
        volatility_bp = (
            1_000
            if not returns
            else max(_integer_median(tuple(abs(value) for value in returns)), 1)
        )
        eligible = len(history) < 5 or momentum_bp > 0
        if eligible:
            signals.append((symbol, momentum_bp, volatility_bp))
        inputs.append(
            {
                "symbol": symbol,
                "event_date": event_date,
                "close_value_int": value_int,
                "close_scale": scale,
                "close_content_hash": content_hash,
                "momentum_bp": momentum_bp,
                "volatility_bp": volatility_bp,
                "eligible": eligible,
            }
        )
    signals.sort(key=lambda item: (-item[1], item[2], item[0]))
    return signals, _sha256_json(inputs)


def _close_feature(
    features: Sequence[Mapping[str, Any]],
) -> tuple[str, int, int, str] | None:
    candidates: list[Mapping[str, Any]] = []
    for feature in features:
        if feature.get("observed") is not True:
            continue
        feature_id = str(feature.get("feature_id", ""))
        normalized = feature_id.lower()
        if (
            "收盤" in feature_id
            or "æ”¶ç›¤" in feature_id
            or normalized.endswith(".close")
            or "close_price" in normalized
        ):
            candidates.append(feature)
    if not candidates:
        return None
    selected = sorted(
        candidates,
        key=lambda item: str(item.get("feature_id", "")),
    )[0]
    value = selected.get("value_int")
    scale = selected.get("scale")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or isinstance(scale, bool)
        or not isinstance(scale, int)
        or scale <= 0
    ):
        return None
    return (
        str(selected["event_at"])[:10],
        value,
        scale,
        str(selected["content_hash"]),
    )


def _return_series_bp(
    history: Sequence[tuple[str, int, int]],
) -> tuple[int, ...]:
    return tuple(
        _scaled_return_bp(history[index - 1], history[index])
        for index in range(1, len(history))
    )


def _scaled_return_bp(
    first: tuple[str, int, int],
    last: tuple[str, int, int],
) -> int:
    first_value = Decimal(first[1]) / Decimal(first[2])
    last_value = Decimal(last[1]) / Decimal(last[2])
    if first_value <= 0:
        return 0
    return int(
        (
            (last_value / first_value - Decimal(1))
            * Decimal(10_000)
        ).to_integral_value(rounding=ROUND_HALF_EVEN)
    )


def _integer_median(values: tuple[int, ...]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _desired_weights(
    *,
    signals: Sequence[tuple[str, int, int]],
    request: ResearchCausalLedgerOverlayRequest,
) -> AllocationWeightContract:
    selected = tuple(signals[: request.max_positions])
    if not selected:
        return AllocationWeightContract(positions_bp=(), cash_bp=10_000)
    maximum_invested = min(
        request.risky_budget_bp,
        len(selected) * request.max_single_position_bp,
    )
    inverse_scores = {
        symbol: Decimal(1) / Decimal(max(volatility_bp, 100))
        for symbol, _, volatility_bp in selected
    }
    remaining = maximum_invested
    weights: dict[str, int] = {}
    active = set(inverse_scores)
    while active and remaining >= request.grid_bp:
        total_score = sum(inverse_scores[symbol] for symbol in active)
        proposals: list[tuple[Decimal, str, int]] = []
        allocated = 0
        for symbol in sorted(active):
            exact = (
                Decimal(remaining)
                * inverse_scores[symbol]
                / total_score
            )
            grid_units = int(exact // Decimal(request.grid_bp))
            weight = min(
                grid_units * request.grid_bp,
                request.max_single_position_bp
                - weights.get(symbol, 0),
            )
            proposals.append(
                (
                    exact - Decimal(weight),
                    symbol,
                    weight,
                )
            )
            allocated += weight
        for _, symbol, value in proposals:
            weights[symbol] = weights.get(symbol, 0) + value
        remaining -= allocated
        if remaining < request.grid_bp:
            break
        progressed = False
        for _, symbol, _ in sorted(
            proposals,
            key=lambda item: (-item[0], item[1]),
        ):
            if (
                remaining < request.grid_bp
                or weights[symbol] >= request.max_single_position_bp
            ):
                continue
            weights[symbol] += request.grid_bp
            remaining -= request.grid_bp
            progressed = True
        active = {
            symbol
            for symbol in active
            if weights.get(symbol, 0) < request.max_single_position_bp
        }
        if allocated == 0 and not progressed:
            break
    positions = tuple(
        (symbol, value)
        for symbol, value in sorted(weights.items())
        if value > 0
    )
    invested = sum(value for _, value in positions)
    return AllocationWeightContract(
        positions_bp=positions,
        cash_bp=10_000 - invested,
    )


def _execute_rebalance(
    *,
    current: AllocationWeightContract,
    desired: AllocationWeightContract,
    weekly_turnover_used_bp: int,
    runtime: _LedgerRuntime,
    request: ResearchCausalLedgerOverlayRequest,
) -> tuple[AllocationWeightContract, int, int, int, int, int, int]:
    current_map = dict(current.positions_bp)
    desired_map = dict(desired.positions_bp)
    result = dict(current_map)
    available = max(
        request.weekly_turnover_cap_bp - weekly_turnover_used_bp,
        0,
    )
    changes = [
        (
            symbol,
            desired_map.get(symbol, 0) - current_map.get(symbol, 0),
        )
        for symbol in sorted(set(current_map) | set(desired_map))
    ]
    changes.sort(key=lambda item: (item[1] >= 0, item[0]))
    buy_turnover = 0
    sell_turnover = 0
    add_count = 0
    reduce_count = 0
    for symbol, delta in changes:
        if abs(delta) < request.rebalance_band_bp:
            continue
        magnitude = (
            abs(delta) // request.grid_bp * request.grid_bp
        )
        magnitude = min(magnitude, available)
        magnitude = magnitude // request.grid_bp * request.grid_bp
        if delta > 0:
            if (
                current_map.get(symbol, 0) == 0
                and result.get(symbol, 0) == 0
                and len(
                    tuple(
                        value
                        for value in result.values()
                        if value > 0
                    )
                )
                >= request.max_positions
            ):
                continue
            maximum_invested = 10_000 - request.minimum_cash_bp
            magnitude = min(
                magnitude,
                request.max_single_position_bp
                - result.get(symbol, 0),
                maximum_invested - sum(result.values()),
            )
            magnitude = (
                max(magnitude, 0)
                // request.grid_bp
                * request.grid_bp
            )
            if magnitude < request.minimum_trade_bp:
                continue
            last_trade = runtime.last_trade_index.get(symbol)
            if (
                last_trade is not None
                and runtime.decision_index - last_trade
                < request.cooldown_trading_days
            ):
                continue
            result[symbol] = current_map.get(symbol, 0) + magnitude
            buy_turnover += magnitude
            add_count += 1
        else:
            if magnitude < request.minimum_trade_bp:
                continue
            result[symbol] = max(
                current_map.get(symbol, 0) - magnitude,
                0,
            )
            sell_turnover += magnitude
            reduce_count += 1
        runtime.last_trade_index[symbol] = runtime.decision_index
        available -= magnitude
    result = {
        symbol: value
        for symbol, value in result.items()
        if value > 0
    }
    positions = tuple(sorted(result.items()))
    invested = sum(value for _, value in positions)
    if (
        len(positions) > request.max_positions
        or any(
            value > request.max_single_position_bp
            for _, value in positions
        )
        or invested > 10_000 - request.minimum_cash_bp
    ):
        raise ValueError("causal baseline projection violated hard limits")
    output = AllocationWeightContract(
        positions_bp=positions,
        cash_bp=10_000 - invested,
    )
    canonical_turnover = _canonical_turnover_bp(current, output)
    if (
        weekly_turnover_used_bp + canonical_turnover
        > request.weekly_turnover_cap_bp
    ):
        raise ValueError("causal baseline weekly turnover exceeded")
    estimated_cost = (
        buy_turnover * request.buy_cost_bp
        + sell_turnover * request.sell_cost_bp
        + 9_999
    ) // 10_000
    return (
        output,
        buy_turnover,
        sell_turnover,
        canonical_turnover,
        estimated_cost,
        add_count,
        reduce_count,
    )


def _canonical_turnover_bp(
    current: AllocationWeightContract,
    target: AllocationWeightContract,
) -> int:
    current_map = dict(current.positions_bp)
    target_map = dict(target.positions_bp)
    absolute = sum(
        abs(target_map.get(symbol, 0) - current_map.get(symbol, 0))
        for symbol in set(current_map) | set(target_map)
    ) + abs(target.cash_bp - current.cash_bp)
    return absolute // 2


def _rewrite_samples(
    *,
    source_manifest_path: Path,
    source_manifest: Mapping[str, Any],
    ledger_path: Path,
    writers: "_WriterRegistry",
    dataset_identity_hash: str,
    feature_registry_hash: str,
    source_manifest_hashes: tuple[tuple[str, str], ...],
    ledger_manifest_hash: str,
    policy: Mapping[str, Any],
) -> int:
    connection = sqlite3.connect(
        f"file:{ledger_path.as_posix()}?mode=ro",
        uri=True,
    )
    connection.execute("PRAGMA query_only=ON")
    sample_count = 0
    try:
        for decision_date, samples in _iter_decision_groups(
            source_manifest_path,
            source_manifest,
        ):
            cursor = connection.execute(
                """
                SELECT input_state_json
                FROM transitions
                WHERE decision_date=?
                """,
                (decision_date,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
            if row is None:
                raise ValueError(
                    "ledger transition missing for decision date"
                )
            state_payload = json.loads(str(row[0]))
            for source_sample in samples:
                sample = json.loads(_canonical_json(source_sample))
                row_payload = _mapping(sample.get("row"), "sample.row")
                row_payload["dataset_identity_hash"] = dataset_identity_hash
                row_payload["feature_registry_hash"] = feature_registry_hash
                row_payload["source_manifest_hashes"] = [
                    list(item) for item in source_manifest_hashes
                ]
                row_payload["portfolio_state"] = state_payload
                row_payload["features"] = _rewrite_rule_features(
                    _mapping_sequence(
                        row_payload.get("features"),
                        "row.features",
                    ),
                    symbol=str(row_payload["symbol"]),
                    decision_at=str(row_payload["decision_at"]),
                    state_payload=state_payload,
                    ledger_manifest_hash=ledger_manifest_hash,
                )
                missing = [
                    str(value)
                    for value in row_payload.get(
                        "missing_family_ids", []
                    )
                    if str(value) != "rule_portfolio_health"
                ]
                row_payload["missing_family_ids"] = sorted(set(missing))
                targets = _mapping(
                    row_payload.get("targets"), "row.targets"
                )
                target_positions = {
                    str(symbol): _strict_integer(
                        weight, "target weight"
                    )
                    for symbol, weight in _pair_sequence(
                        _mapping(
                            targets.get("target_weights"),
                            "targets.target_weights",
                        ).get("positions_bp"),
                        "target positions",
                    )
                }
                current_positions = {
                    str(symbol): _strict_integer(
                        weight, "current weight"
                    )
                    for symbol, weight in _pair_sequence(
                        _mapping(
                            state_payload.get("weights"),
                            "state.weights",
                        ).get("positions_bp"),
                        "current positions",
                    )
                }
                deltas = tuple(
                    (
                        symbol,
                        target_positions.get(symbol, 0)
                        - current_positions.get(symbol, 0),
                    )
                    for symbol in sorted(
                        set(target_positions) | set(current_positions)
                    )
                    if target_positions.get(symbol, 0)
                    != current_positions.get(symbol, 0)
                )
                targets["delta_weights_bp"] = [
                    [symbol, value] for symbol, value in deltas
                ]
                targets["rebalance_worthwhile"] = any(
                    abs(value) >= int(policy["minimum_trade_bp"])
                    for _, value in deltas
                )
                _parse_sample(sample)
                year = int(str(row_payload["decision_at"])[:4])
                writers.get(year=year).write_sample(sample)
                sample_count += 1
    finally:
        connection.close()
    return sample_count


def _rewrite_rule_features(
    features: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    decision_at: str,
    state_payload: Mapping[str, Any],
    ledger_manifest_hash: str,
) -> list[dict[str, Any]]:
    state = _state_from_payload(state_payload)
    values = {
        "rule_portfolio_health.cash_bp": state.weights.cash_bp,
        "rule_portfolio_health.current_symbol_weight_bp": dict(
            state.weights.positions_bp
        ).get(symbol, 0),
        "rule_portfolio_health.invested_bp": (
            state.weights.invested_bp
        ),
        "rule_portfolio_health.position_count": len(
            state.weights.positions_bp
        ),
        "rule_portfolio_health.state_complete_flag": 1,
        "rule_portfolio_health.weekly_turnover_used_bp": (
            state.weekly_turnover_used_bp
        ),
    }
    existing = {
        str(feature["feature_id"]): dict(feature)
        for feature in features
    }
    event_at = f"{state.as_of_date}T14:30:00+08:00"
    available_at = min(event_at, decision_at)
    for feature_id in _RULE_FEATURE_IDS:
        value = values[feature_id]
        content_hash = _sha256_json(
            {
                "feature_id": feature_id,
                "symbol": symbol,
                "decision_at": decision_at,
                "state_hash": state.state_hash,
                "ledger_manifest_hash": ledger_manifest_hash,
                "value_int": value,
            }
        )
        existing[feature_id] = {
            "feature_id": feature_id,
            "family_id": "rule_portfolio_health",
            "source_id": _RULE_SOURCE_ID,
            "value_int": value,
            "scale": 1,
            "event_at": event_at,
            "available_at": available_at,
            "revision_id": state.state_hash,
            "quality": "observed",
            "content_hash": content_hash,
            "observed": True,
            "event_time_semantics": "realized_observation",
        }
    return [existing[key] for key in sorted(existing)]


def _overlay_feature_registry(
    source: Mapping[str, Any],
    *,
    ledger_manifest_hash: str,
) -> dict[str, Any]:
    registry = json.loads(
        _canonical_json(
            _mapping(source.get("feature_registry"), "feature_registry")
        )
    )
    features = _mapping_sequence(
        registry.get("features"),
        "feature_registry.features",
    )
    rewritten: list[dict[str, Any]] = []
    for feature in features:
        payload = dict(feature)
        if str(payload.get("feature_id")) in _RULE_FEATURE_IDS:
            payload["source_id"] = _RULE_SOURCE_ID
            payload["source_table"] = "research_causal_ledger"
            payload["aggregation_policy"] = (
                "T_minus_1_recursive_rule_risk_inverse_vol_state"
            )
            payload["record_hash"] = _sha256_json(
                {
                    "feature_id": payload["feature_id"],
                    "ledger_manifest_hash": ledger_manifest_hash,
                }
            )
        rewritten.append(payload)
    registry["features"] = sorted(
        rewritten,
        key=lambda item: str(item["feature_id"]),
    )
    return registry


def _overlay_source_hashes(
    source: Mapping[str, Any],
    *,
    ledger_manifest_hash: str,
) -> tuple[tuple[str, str], ...]:
    rows = {
        str(source_id): str(manifest_hash)
        for source_id, manifest_hash in _pair_sequence(
            source.get("source_manifest_hashes"),
            "source_manifest_hashes",
        )
    }
    rows[_RULE_SOURCE_ID] = ledger_manifest_hash
    return tuple(sorted(rows.items()))


def _iter_decision_groups(
    manifest_path: Path,
    manifest: Mapping[str, Any],
) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    root = manifest_path.parent
    current_date = ""
    group: list[dict[str, Any]] = []
    for shard in sorted(
        _mapping_sequence(manifest.get("shards"), "shards"),
        key=lambda item: (int(item["year"]), str(item["path"])),
    ):
        path = (root / str(shard["path"])).resolve()
        if not path.is_relative_to(root):
            raise ValueError("research shard path escapes publication")
        if _file_sha256(path) != str(shard["compressed_sha256"]):
            raise ValueError("research shard compressed hash mismatch")
        content_digest = hashlib.sha256()
        shard_samples = 0
        with gzip.open(path, "rb") as stream:
            for raw_line in stream:
                if not raw_line.strip():
                    continue
                content_digest.update(raw_line)
                record = json.loads(raw_line.decode("utf-8"))
                if record.get("record_type") == "header":
                    continue
                if record.get("record_type") != "sample":
                    raise ValueError("unsupported research record type")
                sample = _mapping(record.get("sample"), "sample")
                decision_date = str(sample["row"]["decision_at"])[:10]
                if current_date and decision_date != current_date:
                    yield current_date, group
                    group = []
                current_date = decision_date
                group.append(dict(sample))
                shard_samples += 1
        if _SHA256_PREFIX + content_digest.hexdigest() != str(
            shard["content_sha256"]
        ):
            raise ValueError("research shard content hash mismatch")
        if shard_samples != int(shard["sample_count"]):
            raise ValueError("research shard sample count mismatch")
    if group:
        yield current_date, group


class _Writer:
    def __init__(
        self,
        *,
        path: Path,
        year: int,
        header: Mapping[str, Any],
        compression_level: int,
    ) -> None:
        self.path = path
        self.year = year
        self._raw = path.open("wb")
        self._gzip = gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=compression_level,
            fileobj=self._raw,
            mtime=0,
        )
        self._content_digest = hashlib.sha256()
        self.sample_count = 0
        self.min_decision_date: str | None = None
        self.max_decision_date: str | None = None
        self._closed = False
        self._write(header)

    def write_sample(self, sample: Mapping[str, Any]) -> None:
        self._write({"record_type": "sample", "sample": sample})
        decision_date = str(sample["row"]["decision_at"])[:10]
        self.sample_count += 1
        self.min_decision_date = (
            decision_date
            if self.min_decision_date is None
            else min(self.min_decision_date, decision_date)
        )
        self.max_decision_date = (
            decision_date
            if self.max_decision_date is None
            else max(self.max_decision_date, decision_date)
        )

    def _write(self, payload: Mapping[str, Any]) -> None:
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        self._gzip.write(encoded)
        self._content_digest.update(encoded)

    def close(self) -> None:
        if self._closed:
            return
        self._gzip.close()
        self._raw.flush()
        os.fsync(self._raw.fileno())
        self._raw.close()
        self._closed = True

    def manifest_payload(self, root: Path) -> dict[str, Any]:
        self.close()
        return {
            "year": self.year,
            "path": self.path.relative_to(root).as_posix(),
            "format": "gzip_jsonl",
            "schema_version": RECORD_SCHEMA_VERSION,
            "compressed_sha256": _file_sha256(self.path),
            "content_sha256": (
                _SHA256_PREFIX + self._content_digest.hexdigest()
            ),
            "compressed_bytes": self.path.stat().st_size,
            "sample_count": self.sample_count,
            "min_decision_date": self.min_decision_date,
            "max_decision_date": self.max_decision_date,
            "direct_training_input": True,
            "research_only": True,
            "promotion_eligible": False,
        }


class _WriterRegistry:
    def __init__(self, *, staging: Path, compression_level: int) -> None:
        self.staging = staging
        self.compression_level = compression_level
        self.writers: dict[int, _Writer] = {}
        self.common_header: Mapping[str, Any] | None = None

    def configure(self, header: Mapping[str, Any]) -> None:
        self.common_header = header

    def get(self, *, year: int) -> _Writer:
        if self.common_header is None:
            raise RuntimeError("writer header is not configured")
        writer = self.writers.get(year)
        if writer is None:
            writer = _Writer(
                path=self.staging / f"year={year:04d}.jsonl.gz",
                year=year,
                header={**self.common_header, "year": year},
                compression_level=self.compression_level,
            )
            self.writers[year] = writer
        return writer

    def close_all(self) -> None:
        for writer in self.writers.values():
            writer.close()

    def manifest_payloads(self, *, staging: Path) -> list[dict[str, Any]]:
        return [
            writer.manifest_payload(staging)
            for _, writer in sorted(self.writers.items())
        ]


def _policy_payload(
    request: ResearchCausalLedgerOverlayRequest,
) -> dict[str, Any]:
    return {
        "schema_version": "research-causal-baseline-policy.v1",
        "algorithm": (
            "rule_momentum_filter_then_inverse_realized_volatility_"
            "risk_budget"
        ),
        "risky_budget_bp": request.risky_budget_bp,
        "minimum_cash_bp": request.minimum_cash_bp,
        "max_positions": request.max_positions,
        "max_single_position_bp": request.max_single_position_bp,
        "weekly_turnover_cap_bp": request.weekly_turnover_cap_bp,
        "rebalance_band_bp": request.rebalance_band_bp,
        "minimum_trade_bp": request.minimum_trade_bp,
        "cooldown_trading_days": request.cooldown_trading_days,
        "buy_cost_bp": request.buy_cost_bp,
        "sell_cost_bp": request.sell_cost_bp,
        "grid_bp": request.grid_bp,
        "causal_price_history_sessions": 20,
        "future_teacher_target_used_for_state": False,
        "same_day_advice_used_for_state": False,
    }


def _validate_source_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise ValueError("research union schema mismatch")
    if manifest.get("research_only") is not True:
        raise ValueError("causal ledger overlay requires research_only=true")
    if manifest.get("promotion_eligible") is not False:
        raise ValueError("research source must remain promotion-ineligible")
    if manifest.get("formal_consumer_compatible") is not False:
        raise ValueError("research source must reject formal consumers")
    body = dict(manifest)
    expected = str(body.pop("manifest_hash", ""))
    if _sha256_json(body) != expected:
        raise ValueError("research union manifest hash mismatch")


def _state_from_payload(payload: Mapping[str, Any]) -> CausalPortfolioState:
    weights = _mapping(payload.get("weights"), "state.weights")
    return CausalPortfolioState(
        as_of_date=str(payload["as_of_date"]),
        weights=AllocationWeightContract(
            positions_bp=tuple(
                (
                    str(symbol),
                    _strict_integer(weight, "state position weight"),
                )
                for symbol, weight in _pair_sequence(
                    weights.get("positions_bp"),
                    "state.positions_bp",
                )
            ),
            cash_bp=int(weights["cash_bp"]),
        ),
        weekly_turnover_used_bp=int(
            payload["weekly_turnover_used_bp"]
        ),
        state_hash=str(payload["state_hash"]),
    )


def _state_payload(state: CausalPortfolioState) -> dict[str, Any]:
    return {
        "as_of_date": state.as_of_date,
        "weights": _weight_payload(state.weights),
        "weekly_turnover_used_bp": state.weekly_turnover_used_bp,
        "state_hash": state.state_hash,
    }


def _weight_payload(
    weights: AllocationWeightContract,
) -> dict[str, Any]:
    return {
        "positions_bp": [
            [symbol, value]
            for symbol, value in weights.positions_bp
        ],
        "cash_bp": weights.cash_bp,
    }


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be object")
    return value


def _strict_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    return value


def _mapping_sequence(
    value: object,
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be list")
    return tuple(_mapping(item, field_name) for item in value)


def _pair_sequence(
    value: object,
    field_name: str,
) -> tuple[tuple[object, object], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be sequence")
    result: list[tuple[object, object]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise TypeError(f"{field_name} entries must be pairs")
        result.append((item[0], item[1]))
    return tuple(result)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(payload: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON object required")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            payload,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_write_json(path: Path, payload: object) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        _write_json(temporary, payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_remove_tree(path: Path, root: Path) -> None:
    resolved = path.resolve()
    allowed = root.resolve()
    if not resolved.is_relative_to(allowed) or resolved == allowed:
        raise ValueError("refusing to remove outside overlay root")
    shutil.rmtree(resolved)
