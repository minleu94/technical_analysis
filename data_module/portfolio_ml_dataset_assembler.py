"""將 raw PIT observations 組裝成可直接訓練的配置型 ML 年度 shards。

來源必須是 :mod:`data_module.ml_pit_year_shard_exporter` 發佈的正式
``core_long_history`` 或 ``all_field_enriched`` dataset manifest。本模組：

* 逐行驗證 gzip JSONL 與 manifest/hash，不把完整歷史載入記憶體。
* 以暫存 SQLite 做 append-only spool 與逐決策日 as-of join。
* 決策時間固定為台北 08:30；價格與技術特徵嚴格只允許 T-1。
* 標籤可讀未來價格，但只有在 ``available_at <= training_as_of`` 時輸出。
* 產業歸屬 sidecar 必須是 accepted、具來源／授權與 canonical manifest；
  當期 ``companies.csv`` 快照不得冒充歷史 PIT mapping。
* 沒有可證明的歷史產業歸屬時，teacher 對該股票 fail closed，不新增持倉。
* Portfolio state 預設為每日 T-1 cash-only causal baseline，不讀 Advice。

金融計算使用 ``Decimal`` 或整數 bp。暫存 SQLite 與輸出都不含裸 float。
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Sequence
import uuid
from zoneinfo import ZoneInfo

from ml_module.allocation_contracts import (
    AllocationTargets,
    AllocationWeightContract,
    CausalPortfolioState,
    FeatureQuality,
    PITFeatureValue,
    PortfolioMLDatasetRow,
)
from ml_module.allocation_teacher import (
    CausalAllocationTeacher,
    CausalTeacherRequest,
    TeacherCandidateOutcome,
)
from ml_module.allocation_training_service import (
    AllocationHorizonLabel,
    AllocationTrainingSample,
)


TRAINING_JSONL_SCHEMA_VERSION = "allocation-training-jsonl-v2"
PUBLICATION_SCHEMA_VERSION = "portfolio-ml-training-shards.v2"
SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION = (
    "pit-sector-membership-sidecar-v1"
)
SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION = (
    "pit-sector-membership-manifest-v1"
)
SUPPORTED_HORIZONS = (5, 10, 20, 60)
_TAIPEI = ZoneInfo("Asia/Taipei")
_DECISION_TIME = time(8, 30)
_MARKET_CLOSE_TIME = time(14, 30)
_FORMAL_DATASETS = frozenset({"core_long_history", "all_field_enriched"})
_STOCK_TABLES = frozenset(
    {
        "daily_prices",
        "technical_indicators",
        "fundamental_monthly_revenues",
        "fundamental_statement_items",
        "fundamental_valuation_metrics",
        "institutional_flows",
        "credit_transactions",
        "tdcc_shareholding",
        "broker_flows",
    }
)
_PRICE_TECHNICAL_TABLES = frozenset(
    {"daily_prices", "technical_indicators"}
)
_LONG_FORMAT_TABLES = frozenset(
    {"fundamental_statement_items", "fundamental_valuation_metrics"}
)
_BUY_COST_BP = 25
_SELL_COST_BP = 55
_ZERO_SHA256 = "sha256:" + ("0" * 64)
_PORTFOLIO_STATE_REPLAY_SCHEMA_VERSION = "causal-portfolio-state-replay-v1"
_CORPORATE_ACTION_CUSTODY_SCHEMA_VERSION = (
    "portfolio-ml-corporate-action-custody.v1"
)
_OFFICIAL_MARKET_EVENT_PUBLICATION_SCHEMA_VERSION = (
    "official-market-event-publication.v1"
)
_OFFICIAL_MARKET_EVENT_SCHEMA_VERSION = "official-market-event.v1"
_CORPORATE_ACTION_LABEL_EVENT_TYPES = frozenset(
    {
        "ex_right_dividend_result",
        "capital_reduction_resume_result",
    }
)
_CORPORATE_ACTION_EXCLUSION_REASON = (
    "corporate_action_effective_within_label_horizon"
)


@dataclass(frozen=True)
class PortfolioMLDatasetAssemblyRequest:
    """Raw publication 到 frozen training shards 的顯式組裝政策。"""

    dataset_manifest_path: Path
    output_root: Path
    training_as_of: str
    benchmark_entity_id: str
    sector_membership_path: Path | None = None
    corporate_action_manifest_path: Path | None = None
    years: tuple[int, ...] = ()
    minimum_train_dates: int = 252
    test_date_count: int = 63
    purge_trading_days: int = 60
    embargo_trading_days: int = 5
    batch_size: int = 2_048
    compression_level: int = 6

    def __post_init__(self) -> None:
        _available_datetime(
            self.training_as_of, field_name="training_as_of"
        )
        if not self.benchmark_entity_id.strip():
            raise ValueError("benchmark_entity_id is required")
        normalized_years = _normalized_years(self.years)
        object.__setattr__(self, "years", normalized_years)
        for field_name in (
            "minimum_train_dates",
            "test_date_count",
            "purge_trading_days",
            "embargo_trading_days",
            "batch_size",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.purge_trading_days < 60:
            raise ValueError("purge_trading_days must be at least 60")
        if self.embargo_trading_days < 5:
            raise ValueError("embargo_trading_days must be at least 5")
        if self.batch_size > 100_000:
            raise ValueError("batch_size must not exceed 100000")
        if (
            isinstance(self.compression_level, bool)
            or not isinstance(self.compression_level, int)
        ):
            raise TypeError("compression_level must be integer")
        if not 0 <= self.compression_level <= 9:
            raise ValueError("compression_level must be within 0..9")


@dataclass(frozen=True)
class PortfolioMLDatasetPublication:
    publication_id: str
    publication_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    dataset_manifest_file_hash: str
    shard_paths: tuple[Path, ...]
    sample_count: int
    fold_count: int
    direct_training_input: bool = True


@dataclass(frozen=True)
class _FeatureDefinition:
    feature_id: str
    base_feature_id: str
    table_name: str
    family_id: str
    source_id: str
    scale: int
    stale_after_days: int
    record_hash: str
    scope: str
    dimension_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FoldWindow:
    fold_id: str
    train_end_date: str
    test_start: str
    test_end: str
    purge_trading_days: int
    embargo_trading_days: int


@dataclass(frozen=True)
class _Label:
    horizon: int
    horizon_end_date: str
    available_at: str
    excess_return_bp: int
    sector_excess_return_bp: int | None
    sector_excess_observed: bool
    sector_excess_missing_reason: str | None
    downside_observed: bool
    mae_loss_bp: int
    mfe_gain_bp: int
    realized_volatility_bp: int
    max_drawdown_bp: int
    tail_loss_bp: int
    fill_feasible_observed: bool
    source_hash: str


@dataclass(frozen=True)
class _CurrentValue:
    value_int: int | None
    scale: int
    event_at: str
    available_at: str
    revision_id: str
    quality: str
    source_value_hash: str
    stale_after_days: int
    formal_training_eligible: bool
    missing_mask: bool
    quality_blocked_mask: bool


_CurrentFeatureCache = dict[
    str,
    dict[str, dict[str, _CurrentValue]],
]


@dataclass(frozen=True)
class _PortfolioStateReplayEntry:
    decision_date: str
    transition_hash: str
    state: CausalPortfolioState


@dataclass(frozen=True)
class _PortfolioStateReplay:
    entries: tuple[_PortfolioStateReplayEntry, ...]
    ledger_manifest_hash: str
    policy_hash: str
    transition_chain_hash: str
    cash_only_fallback: bool
    decision_dates: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        decision_dates = tuple(
            entry.decision_date for entry in self.entries
        )
        if decision_dates != tuple(sorted(set(decision_dates))):
            raise ValueError(
                "portfolio state replay decision dates must be unique and sorted"
            )
        object.__setattr__(self, "decision_dates", decision_dates)

    def state_for(self, decision_date: str) -> CausalPortfolioState:
        index = bisect_left(self.decision_dates, decision_date)
        if (
            index < len(self.decision_dates)
            and self.decision_dates[index] == decision_date
        ):
            return self.entries[index].state
        raise KeyError(f"portfolio state replay misses decision date: {decision_date}")

    def custody_payload(self) -> dict[str, Any]:
        return {
            "schema_version": _PORTFOLIO_STATE_REPLAY_SCHEMA_VERSION,
            "mode": (
                "per_decision_t_minus_1_cash_only_fallback"
                if self.cash_only_fallback
                else "per_decision_t_minus_1_ledger"
            ),
            "ledger_present": not self.cash_only_fallback,
            "ledger_manifest_hash": self.ledger_manifest_hash,
            "policy_hash": self.policy_hash,
            "transition_chain_hash": self.transition_chain_hash,
            "transition_count": len(self.entries),
            "cash_only_fallback": self.cash_only_fallback,
            "teacher_targets_replayed_into_state": False,
            "turnover_observed": not self.cash_only_fallback,
            "cooldown_observed": not self.cash_only_fallback,
            "turnover_learning_claim_allowed": not self.cash_only_fallback,
            "cooldown_learning_claim_allowed": not self.cash_only_fallback,
        }


@dataclass(frozen=True)
class _CorporateActionCustody:
    manifest_present: bool
    manifest_hash: str
    manifest_file_hash: str
    canonical_events_hash: str
    canonical_event_count: int
    label_ledger_event_count: int
    eligible_label_ledger_event_count: int
    eligible_effective_date_count: int
    effective_dates_by_symbol: Mapping[str, tuple[str, ...]]
    min_effective_date: str | None = None
    max_effective_date: str | None = None

    def custody_payload(self) -> dict[str, Any]:
        return {
            "schema_version": _CORPORATE_ACTION_CUSTODY_SCHEMA_VERSION,
            "manifest_present": self.manifest_present,
            "manifest_hash": self.manifest_hash,
            "manifest_file_hash": self.manifest_file_hash,
            "canonical_events_hash": self.canonical_events_hash,
            "canonical_event_count": self.canonical_event_count,
            "label_ledger_event_count": self.label_ledger_event_count,
            "eligible_label_ledger_event_count": (
                self.eligible_label_ledger_event_count
            ),
            "eligible_effective_date_count": (
                self.eligible_effective_date_count
            ),
            "covered_symbol_count": len(self.effective_dates_by_symbol),
            "min_effective_date": self.min_effective_date,
            "max_effective_date": self.max_effective_date,
            "allowed_use": "supervised_label_exclusion_and_ledger_only",
            "decision_feature_allowed": False,
            "post_event_values_used_as_features": False,
        }


class PortfolioMLDatasetAssembler:
    """以 bounded-memory pipeline 發佈年度 training JSONL shards。"""

    def build(
        self, request: PortfolioMLDatasetAssemblyRequest
    ) -> PortfolioMLDatasetPublication:
        manifest_path = request.dataset_manifest_path.resolve()
        raw_manifest = _read_json(manifest_path)
        _validate_raw_dataset_manifest(raw_manifest)
        dataset_id = str(raw_manifest["dataset_id"])
        if dataset_id not in _FORMAL_DATASETS:
            raise ValueError("research-shadow raw dataset cannot become training input")
        cutoff = _available_datetime(
            request.training_as_of, field_name="training_as_of"
        )
        raw_decision = _decision_datetime(str(raw_manifest["decision_at"]))
        if cutoff > raw_decision:
            raise ValueError(
                "training_as_of cannot exceed the raw publication decision_at"
            )
        corporate_action_custody = _load_corporate_action_custody(
            request.corporate_action_manifest_path,
            training_as_of=cutoff,
        )
        corporate_action_policy = (
            corporate_action_custody.custody_payload()
        )

        output_root = request.output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        runs_root = output_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=".portfolio-ml-", dir=output_root)
        )
        spool_directory = Path(
            tempfile.mkdtemp(prefix="baldr-portfolio-ml-spool-")
        )
        connection: sqlite3.Connection | None = None
        writers = _TrainingShardWriterRegistry(
            staging=staging,
            compression_level=request.compression_level,
        )
        try:
            connection = sqlite3.connect(spool_directory / "assembly.sqlite")
            connection.row_factory = sqlite3.Row
            _initialize_spool(connection)
            base_definitions = _base_feature_definitions(raw_manifest)
            runtime_definitions = dict(base_definitions)
            source_digest = hashlib.sha256()
            raw_row_count, raw_value_count = self._spool_raw_observations(
                connection=connection,
                dataset_manifest_path=manifest_path,
                manifest=raw_manifest,
                definitions=runtime_definitions,
                source_digest=source_digest,
                batch_size=request.batch_size,
            )
            _finalize_long_format_definitions(
                runtime_definitions=runtime_definitions,
                base_definitions=base_definitions,
            )
            sector_manifest_hash, sector_count = _spool_sector_memberships(
                connection,
                request.sector_membership_path,
                training_as_of=cutoff,
            )
            feature_definitions = tuple(
                sorted(
                    runtime_definitions.values(),
                    key=lambda row: row.feature_id,
                )
            )
            if not feature_definitions:
                raise ValueError("raw dataset contains no registered numeric features")
            feature_packs = _feature_pack_payloads(feature_definitions)
            feature_registry_payload = {
                "features": [
                    asdict(definition) for definition in feature_definitions
                ],
                "feature_packs": feature_packs,
            }
            feature_registry_hash = _sha256_json(
                feature_registry_payload
            )
            source_manifest_hashes = _source_manifest_hashes(
                definitions=feature_definitions,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                sector_manifest_hash=sector_manifest_hash,
                corporate_action_manifest_hash=(
                    corporate_action_custody.manifest_hash
                ),
            )
            calendar, benchmark_returns = _build_label_spool(
                connection=connection,
                benchmark_entity_id=request.benchmark_entity_id,
                cutoff=cutoff,
                horizons=SUPPORTED_HORIZONS,
                batch_size=request.batch_size,
                corporate_action_effective_dates=(
                    corporate_action_custody.effective_dates_by_symbol
                ),
            )
            corporate_action_excluded_label_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM label_exclusions "
                    "WHERE reason=?",
                    (_CORPORATE_ACTION_EXCLUSION_REASON,),
                ).fetchone()[0]
            )
            calendar_positions = {
                day: index for index, day in enumerate(calendar)
            }
            eligible_dates = tuple(
                day
                for day in _eligible_decision_dates(
                    connection,
                    years=request.years,
                )
                if calendar_positions.get(day, 0) > 0
            )
            fold_windows = _build_fold_windows(
                eligible_dates,
                minimum_train_dates=request.minimum_train_dates,
                test_date_count=request.test_date_count,
                purge_trading_days=request.purge_trading_days,
                embargo_trading_days=request.embargo_trading_days,
            )
            if len(fold_windows) < 4:
                raise ValueError(
                    "dataset must produce at least four expanding outer folds; "
                    f"eligible_decision_dates={len(eligible_dates)}; "
                    f"fold_count={len(fold_windows)}; "
                    f"minimum_train_dates={request.minimum_train_dates}; "
                    f"test_date_count={request.test_date_count}; "
                    f"purge_trading_days={request.purge_trading_days}; "
                    f"embargo_trading_days={request.embargo_trading_days}"
                )

            assembly_blockers: set[str] = set()
            portfolio_state_replay = _build_cash_only_portfolio_state_replay(
                calendar=calendar,
                decision_dates=eligible_dates,
            )
            portfolio_state_policy = portfolio_state_replay.custody_payload()
            assembly_blockers.add(
                "portfolio_ledger_missing_cash_only_fallback_"
                "turnover_and_cooldown_not_learned"
            )
            if sector_count == 0:
                assembly_blockers.add(
                    "pit_sector_membership_missing_teacher_new_positions_disabled"
                )
            industry_price_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM prices WHERE scope='industry'"
                ).fetchone()[0]
            )
            if industry_price_count == 0:
                assembly_blockers.add(
                    "pit_sector_benchmark_unavailable_sector_excess_masked"
                )
            if not corporate_action_custody.manifest_present:
                assembly_blockers.add(
                    "corporate_action_adjustment_timeline_not_in_raw_"
                    "publication_labels_are_research_shadow"
                )
            dataset_identity_hash = _sha256_json(
                {
                    "schema_version": TRAINING_JSONL_SCHEMA_VERSION,
                    "raw_dataset_manifest_hash": raw_manifest["manifest_hash"],
                    "raw_content_digest": (
                        f"sha256:{source_digest.hexdigest()}"
                    ),
                    "training_as_of": cutoff.isoformat(),
                    "benchmark_entity_id": request.benchmark_entity_id,
                    "sector_manifest_hash": sector_manifest_hash,
                    "feature_registry_hash": feature_registry_hash,
                    "source_manifest_hashes": source_manifest_hashes,
                    "horizons": list(SUPPORTED_HORIZONS),
                    "fold_windows": [asdict(window) for window in fold_windows],
                    "portfolio_state_replay_custody": portfolio_state_policy,
                    "corporate_action_custody": corporate_action_policy,
                    "corporate_action_excluded_label_count": (
                        corporate_action_excluded_label_count
                    ),
                    "teacher_policy": "100bp_constrained_grid",
                    "formal_consumer_marker_policy": "explicit_fail_closed_v1",
                }
            )
            header_common: dict[str, Any] = {
                "record_type": "header",
                "schema_version": TRAINING_JSONL_SCHEMA_VERSION,
                "direct_training_input": True,
                "research_only": False,
                "formal_consumer_compatible": True,
                "promotion_eligible": False,
                "research_shadow_included": False,
                "formal_source_only": True,
                "dataset_id": (
                    f"{dataset_id}-portfolio-allocation-"
                    f"{dataset_identity_hash[7:19]}"
                ),
                "dataset_identity_hash": dataset_identity_hash,
                "training_as_of": cutoff.isoformat(),
                "horizons": list(SUPPORTED_HORIZONS),
                "feature_packs": feature_packs,
                "folds": [asdict(window) for window in fold_windows],
                "assembly_blockers": sorted(assembly_blockers),
                "feature_registry_hash": feature_registry_hash,
                "source_manifest_hashes": [
                    list(item) for item in source_manifest_hashes
                ],
                "portfolio_state_policy": {
                    **portfolio_state_policy,
                    "reads_same_day_advice": False,
                    "oracle_teacher_state_allowed": False,
                },
                "corporate_action_custody": corporate_action_policy,
                "label_policy": {
                    "entry": "decision_day_open_next_tradable_time",
                    "exit": "exact_market_session_horizon_close",
                    "transaction_cost_bp": _BUY_COST_BP + _SELL_COST_BP,
                    "numeric_heads": [
                        "benchmark_excess_return_bp",
                        "sector_excess_return_bp_optional",
                        "mae_bp",
                        "mfe_bp",
                        "realized_volatility_bp",
                        "max_drawdown_bp",
                        "tail_loss_bp",
                    ],
                    "classification_heads": [
                        "downside_observed",
                        "fill_feasible_observed",
                    ],
                    "sector_excess_without_pit_benchmark": (
                        "explicit_missing_mask"
                    ),
                    "fill_feasibility_without_tick_or_limit_state": (
                        "single_price_session_fail_closed"
                    ),
                    "future_values_are_supervised_labels_only": True,
                    "maturity_cutoff_required": True,
                    "teacher_targets_feed_next_state": False,
                    "corporate_action_affected_horizon": (
                        "explicit_missing_then_incomplete_sample_excluded"
                    ),
                    "corporate_action_exclusion_reason": (
                        _CORPORATE_ACTION_EXCLUSION_REASON
                    ),
                    "corporate_action_excluded_label_count": (
                        corporate_action_excluded_label_count
                    ),
                    "post_event_corporate_action_used_as_feature": False,
                },
            }
            teacher_incomplete_count, sample_count = self._assemble_samples(
                connection=connection,
                definitions=feature_definitions,
                source_manifest_hashes=source_manifest_hashes,
                dataset_identity_hash=dataset_identity_hash,
                feature_registry_hash=feature_registry_hash,
                header_common=header_common,
                writers=writers,
                cutoff=cutoff,
                benchmark_entity_id=request.benchmark_entity_id,
                benchmark_returns=benchmark_returns,
                eligible_dates=eligible_dates,
                portfolio_state_replay=portfolio_state_replay,
                years=request.years,
                batch_size=request.batch_size,
            )
            if sample_count == 0:
                raise ValueError("no mature PortfolioMLDatasetRow samples were emitted")
            if teacher_incomplete_count:
                assembly_blockers.add(
                    "teacher_search_incomplete_for_one_or_more_decision_dates"
                )
            writers.close_all()
            shard_payloads = writers.manifest_payloads(staging=staging)
            publication_identity = {
                "dataset_identity_hash": dataset_identity_hash,
                "training_as_of": cutoff.isoformat(),
                "shards": [
                    {
                        "year": payload["year"],
                        "content_sha256": payload["content_sha256"],
                    }
                    for payload in shard_payloads
                ],
            }
            publication_id = (
                "portfolio-ml-"
                + _sha256_json(publication_identity)[7:31]
            )
            publication_manifest: dict[str, Any] = {
                "schema_version": PUBLICATION_SCHEMA_VERSION,
                "publication_id": publication_id,
                "stage": "portfolio_ml_dataset_row_assembly",
                "direct_training_input": True,
                "target_cli": "scripts/train_ml_allocation_copilot.py",
                "target_schema_version": TRAINING_JSONL_SCHEMA_VERSION,
                "dataset_id": header_common["dataset_id"],
                "dataset_identity_hash": dataset_identity_hash,
                "feature_registry_hash": feature_registry_hash,
                "source_manifest_hashes": [
                    list(item) for item in source_manifest_hashes
                ],
                "training_as_of": cutoff.isoformat(),
                "benchmark_entity_id": request.benchmark_entity_id,
                "raw_dataset_manifest": {
                    "path": manifest_path.name,
                    "manifest_hash": raw_manifest["manifest_hash"],
                    "dataset_id": dataset_id,
                    "raw_row_count": raw_row_count,
                    "raw_value_count": raw_value_count,
                    "streaming_jsonl": True,
                },
                "feature_packs": header_common["feature_packs"],
                "feature_registry": feature_registry_payload,
                "feature_count": sum(
                    len(pack["feature_ids"])
                    for pack in header_common["feature_packs"]
                ),
                "horizons": list(SUPPORTED_HORIZONS),
                "folds": [asdict(window) for window in fold_windows],
                "fold_count": len(fold_windows),
                "sample_count": sample_count,
                "teacher_incomplete_decision_count": teacher_incomplete_count,
                "sector_membership_count": sector_count,
                "sector_benchmark_price_count": industry_price_count,
                "sector_manifest_hash": sector_manifest_hash,
                "corporate_action_custody": corporate_action_policy,
                "corporate_action_excluded_label_count": (
                    corporate_action_excluded_label_count
                ),
                "corporate_action_exclusion_reason": (
                    _CORPORATE_ACTION_EXCLUSION_REASON
                ),
                "portfolio_state_policy": portfolio_state_policy,
                "assembly_blockers": sorted(assembly_blockers),
                "formal_oos_allowed": False,
                "research_only": False,
                "formal_consumer_compatible": True,
                "promotion_eligible": False,
                "research_shadow_included": False,
                "formal_source_only": True,
                "production_alpha_bp": 0,
                "production_action_allowed": False,
                "safety": {
                    "available_at_lte_decision_at": True,
                    "price_and_technical_t_minus_1": True,
                    "future_labels_only": True,
                    "label_maturity_lte_training_as_of": True,
                    "corporate_action_affected_horizons_excluded": (
                        corporate_action_custody.manifest_present
                    ),
                    "post_event_corporate_action_used_as_feature": False,
                    "corporate_action_manifest_hash_bound_in_identity": True,
                    "same_day_advice_read": False,
                    "oracle_portfolio_state": False,
                    "cash_only_portfolio_state_fallback_declared": True,
                    "turnover_learning_claim_allowed": False,
                    "cooldown_learning_claim_allowed": False,
                    "sector_membership_accepted_only": True,
                    "sector_membership_canonical_manifest_verified": True,
                    "current_company_snapshot_backfill_allowed": False,
                    "missing_values_zero_filled": False,
                    "sqlite_source_write": False,
                    "atomic_manifest_last_publish": True,
                },
                "execution": {
                    "raw_streaming_gzip_jsonl": True,
                    "bounded_python_state": True,
                    "temporary_sqlite_spool": True,
                    "batch_size": request.batch_size,
                    "parquet_dependency_added": False,
                },
                "shards": shard_payloads,
            }
            publication_manifest["manifest_hash"] = _sha256_json(
                publication_manifest
            )
            _write_json(staging / "manifest.json", publication_manifest)
            dataset_manifest_file_hash = _file_sha256(
                staging / "manifest.json"
            )

            publication_directory = runs_root / publication_id
            if publication_directory.exists():
                existing = _read_json(publication_directory / "manifest.json")
                if (
                    existing.get("manifest_hash")
                    != publication_manifest["manifest_hash"]
                ):
                    raise RuntimeError(
                        "publication identity collision with different manifest"
                    )
                _safe_remove_tree(staging, output_root)
            else:
                os.replace(staging, publication_directory)
            latest_manifest_path = output_root / "latest_manifest.json"
            _atomic_write_json(
                latest_manifest_path,
                {
                    "schema_version": "portfolio-ml-training-pointer.v1",
                    "publication_id": publication_id,
                    "manifest_path": f"runs/{publication_id}/manifest.json",
                    "manifest_hash": publication_manifest["manifest_hash"],
                },
            )
            shard_paths = tuple(
                publication_directory / str(payload["path"])
                for payload in shard_payloads
            )
            return PortfolioMLDatasetPublication(
                publication_id=publication_id,
                publication_directory=publication_directory,
                manifest_path=publication_directory / "manifest.json",
                latest_manifest_path=latest_manifest_path,
                manifest_hash=str(publication_manifest["manifest_hash"]),
                dataset_manifest_file_hash=dataset_manifest_file_hash,
                shard_paths=shard_paths,
                sample_count=sample_count,
                fold_count=len(fold_windows),
            )
        except Exception:
            writers.close_all()
            if staging.exists():
                _safe_remove_tree(staging, output_root)
            raise
        finally:
            if connection is not None:
                connection.close()
            if spool_directory.exists():
                shutil.rmtree(spool_directory)

    def _spool_raw_observations(
        self,
        *,
        connection: sqlite3.Connection,
        dataset_manifest_path: Path,
        manifest: Mapping[str, Any],
        definitions: dict[str, _FeatureDefinition],
        source_digest: Any,
        batch_size: int,
    ) -> tuple[int, int]:
        publication_root = dataset_manifest_path.parent.parent.resolve()
        dataset_id = str(manifest["dataset_id"])
        raw_row_count = 0
        raw_value_count = 0
        observation_batch: list[tuple[object, ...]] = []
        price_batch: list[tuple[object, ...]] = []
        for shard in _mapping_sequence(
            manifest.get("shards"), field_name="shards"
        ):
            shard_path = (publication_root / str(shard["path"])).resolve()
            if not shard_path.is_relative_to(publication_root):
                raise ValueError("raw shard path escapes publication root")
            if _file_sha256(shard_path) != str(shard["compressed_sha256"]):
                raise ValueError(f"raw shard compressed hash mismatch: {shard_path}")
            content_digest = hashlib.sha256()
            shard_row_count = 0
            shard_value_count = 0
            with gzip.open(shard_path, "rb") as stream:
                for line_number, raw_line in enumerate(stream, start=1):
                    if not raw_line.strip():
                        continue
                    content_digest.update(raw_line)
                    source_digest.update(raw_line)
                    try:
                        payload = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise ValueError(
                            f"invalid raw JSONL at {shard_path}:{line_number}"
                        ) from exc
                    row = _as_mapping(payload, field_name="raw observation")
                    if row.get("schema_version") != "ml-pit-observation.v1":
                        raise ValueError("unsupported raw observation schema")
                    if row.get("dataset_id") != dataset_id:
                        raise ValueError("raw observation dataset_id mismatch")
                    if row.get("pit_status") != "eligible_as_of_decision":
                        raise ValueError("raw observation is not PIT eligible")
                    expected_row_hash = str(row.get("source_row_hash", ""))
                    hash_payload = dict(row)
                    hash_payload.pop("source_row_hash", None)
                    if expected_row_hash != _sha256_json(hash_payload):
                        raise ValueError("raw source_row_hash mismatch")
                    available_at = _available_datetime(
                        str(row["available_at"]), field_name="available_at"
                    ).isoformat()
                    event_at = _available_datetime(
                        str(row["event_at"]), field_name="event_at"
                    ).isoformat()
                    table_name = str(row["source_table"])
                    row_source_id = str(row["source_id"])
                    row_family_id = str(row["family"])
                    entity_id = str(row["entity_id"])
                    scope, entity_key = _scope_and_entity(
                        table_name=table_name,
                        entity_id=entity_id,
                    )
                    value_mappings = _mapping_sequence(
                        row.get("values"), field_name="values"
                    )
                    seen_ids: set[str] = set()
                    price_values: dict[str, tuple[int | None, int]] = {}
                    for value in value_mappings:
                        base_feature_id = str(value["feature_id"])
                        if base_feature_id in seen_ids:
                            raise ValueError(
                                "raw observation contains duplicate feature_id"
                            )
                        seen_ids.add(base_feature_id)
                        runtime_definition = _runtime_definition(
                            base_feature_id=base_feature_id,
                            table_name=table_name,
                            entity_id=entity_id,
                            definitions=definitions,
                        )
                        runtime_feature_id = runtime_definition.feature_id
                        if runtime_definition.source_id != row_source_id:
                            raise ValueError(
                                "blocker:manifest_observation_source_id_mismatch:"
                                f"{base_feature_id}:manifest="
                                f"{runtime_definition.source_id}:observation="
                                f"{row_source_id}"
                            )
                        if runtime_definition.family_id != row_family_id:
                            raise ValueError(
                                "blocker:manifest_observation_family_mismatch:"
                                f"{base_feature_id}"
                            )
                        value_int = value.get("value_int")
                        if value_int is not None and (
                            isinstance(value_int, bool)
                            or not isinstance(value_int, int)
                        ):
                            raise TypeError("raw value_int must be integer or null")
                        scale = value.get("scale")
                        if (
                            isinstance(scale, bool)
                            or not isinstance(scale, int)
                            or scale <= 0
                        ):
                            raise TypeError("raw scale must be positive integer")
                        if scale != runtime_definition.scale:
                            raise ValueError(
                                "blocker:manifest_observation_scale_mismatch:"
                                f"{base_feature_id}"
                            )
                        source_value_hash = str(value["source_value_hash"])
                        _require_sha256(
                            source_value_hash, field_name="source_value_hash"
                        )
                        formal_training_eligible = _required_json_bool(
                            value.get("formal_training_eligible"),
                            field_name=(
                                f"{base_feature_id}.formal_training_eligible"
                            ),
                        )
                        missing_mask = _required_json_bool(
                            value.get("missing_mask"),
                            field_name=f"{base_feature_id}.missing_mask",
                        )
                        quality_blocked_mask = _required_json_bool(
                            value.get("quality_blocked_mask"),
                            field_name=f"{base_feature_id}.quality_blocked_mask",
                        )
                        _required_json_bool(
                            value.get("staleness_mask"),
                            field_name=f"{base_feature_id}.staleness_mask",
                        )
                        revision_id = (
                            str(row["revision_id"])
                            if row.get("revision_id") is not None
                            else expected_row_hash
                        )
                        observation_batch.append(
                            (
                                scope,
                                entity_key,
                                runtime_feature_id,
                                table_name,
                                row_source_id,
                                row_family_id,
                                event_at,
                                available_at,
                                revision_id,
                                str(row["quality"]),
                                expected_row_hash,
                                source_value_hash,
                                value_int,
                                scale,
                                int(value["stale_after_days"]),
                                int(formal_training_eligible),
                                int(missing_mask),
                                int(quality_blocked_mask),
                            )
                        )
                        raw_value_count += 1
                        price_values[base_feature_id] = (value_int, scale)
                    price_record = _price_record(
                        table_name=table_name,
                        entity_key=entity_key,
                        event_at=event_at,
                        available_at=available_at,
                        source_row_hash=expected_row_hash,
                        values=price_values,
                    )
                    if price_record is not None:
                        price_batch.append(price_record)
                    raw_row_count += 1
                    shard_row_count += 1
                    shard_value_count += len(value_mappings)
                    if len(observation_batch) >= batch_size:
                        _insert_observations(connection, observation_batch)
                        observation_batch.clear()
                    if len(price_batch) >= batch_size:
                        _insert_prices(connection, price_batch)
                        price_batch.clear()
            if (
                f"sha256:{content_digest.hexdigest()}"
                != str(shard["content_sha256"])
            ):
                raise ValueError(f"raw shard content hash mismatch: {shard_path}")
            if shard_row_count != int(shard["row_count"]):
                raise ValueError(f"raw shard row_count mismatch: {shard_path}")
            if shard_value_count != int(shard["feature_value_count"]):
                raise ValueError(
                    f"raw shard feature_value_count mismatch: {shard_path}"
                )
        if observation_batch:
            _insert_observations(connection, observation_batch)
        if price_batch:
            _insert_prices(connection, price_batch)
        connection.commit()
        return raw_row_count, raw_value_count

    def _assemble_samples(
        self,
        *,
        connection: sqlite3.Connection,
        definitions: tuple[_FeatureDefinition, ...],
        source_manifest_hashes: tuple[tuple[str, str], ...],
        dataset_identity_hash: str,
        feature_registry_hash: str,
        header_common: Mapping[str, Any],
        writers: "_TrainingShardWriterRegistry",
        cutoff: datetime,
        benchmark_entity_id: str,
        benchmark_returns: Mapping[tuple[str, int], tuple[int, str, str]],
        eligible_dates: tuple[str, ...],
        portfolio_state_replay: _PortfolioStateReplay,
        years: tuple[int, ...],
        batch_size: int,
        initial_current_feature_cache: _CurrentFeatureCache | None = None,
    ) -> tuple[int, int]:
        del benchmark_returns  # 已於 label spool 使用，保留參數作稽核邊界。
        by_scope = {
            scope: tuple(
                definition
                for definition in definitions
                if definition.scope == scope
            )
            for scope in ("stock", "market", "industry")
        }
        feature_by_id = {
            definition.feature_id: definition for definition in definitions
        }
        previous_cutoff = "0001-01-01T00:00:00+08:00"
        current_feature_cache: _CurrentFeatureCache = (
            initial_current_feature_cache
            if initial_current_feature_cache is not None
            else {
                "stock": {},
                "market": {},
                "industry": {},
            }
        )
        teacher = CausalAllocationTeacher()
        sample_count = 0
        teacher_incomplete_count = 0
        requested_years = frozenset(years)
        for decision_date in eligible_dates:
            decision_year = date.fromisoformat(decision_date).year
            if requested_years and decision_year not in requested_years:
                continue
            decision_at = datetime.combine(
                date.fromisoformat(decision_date),
                _DECISION_TIME,
                tzinfo=_TAIPEI,
            )
            if decision_at > cutoff:
                continue
            _advance_current_features(
                connection,
                previous_cutoff=previous_cutoff,
                decision_at=decision_at.isoformat(),
                decision_date=decision_date,
                batch_size=batch_size,
                current_feature_cache=current_feature_cache,
                persist_current_history=False,
            )
            previous_cutoff = decision_at.isoformat()
            labels_by_symbol = _labels_for_decision(connection, decision_date)
            if not labels_by_symbol:
                continue
            sectors = _sectors_for_decision(
                connection,
                decision_date=decision_date,
                decision_at=decision_at.isoformat(),
            )
            candidate_rows = _teacher_candidates(
                labels_by_symbol=labels_by_symbol,
                sectors=sectors,
            )
            state = portfolio_state_replay.state_for(decision_date)
            teacher_result = teacher.build_targets(
                CausalTeacherRequest(
                    decision_date=decision_date,
                    training_as_of=cutoff.isoformat(),
                    portfolio_state=state,
                    candidates=candidate_rows,
                )
            )
            if not teacher_result.formal_label_eligible:
                teacher_incomplete_count += 1
            market_current = current_feature_cache["market"].get(
                benchmark_entity_id,
                {},
            )
            for symbol in sorted(labels_by_symbol):
                sector_id = sectors.get(symbol)
                industry_current: dict[str, _CurrentValue] = {}
                if sector_id is not None:
                    industry_current = current_feature_cache["industry"].get(
                        sector_id,
                        {},
                    )
                stock_current = current_feature_cache["stock"].get(
                    symbol,
                    {},
                )
                features, missing_families = _build_feature_snapshot(
                    decision_at=decision_at,
                    definitions=definitions,
                    feature_by_id=feature_by_id,
                    by_scope=by_scope,
                    stock_current=stock_current,
                    market_current=market_current,
                    industry_current=industry_current,
                )
                sample = AllocationTrainingSample(
                    row=PortfolioMLDatasetRow(
                        row_id=f"row:{decision_date}:{symbol}",
                        decision_at=decision_at.isoformat(),
                        symbol=symbol,
                        features=features,
                        missing_family_ids=missing_families,
                        portfolio_state=state,
                        dataset_identity_hash=dataset_identity_hash,
                        feature_registry_hash=feature_registry_hash,
                        source_manifest_hashes=source_manifest_hashes,
                        targets=teacher_result.targets,
                    ),
                    horizon_labels=tuple(
                        AllocationHorizonLabel(
                            horizon_trading_days=label.horizon,
                            horizon_end_date=label.horizon_end_date,
                            available_at=label.available_at,
                            benchmark_excess_return_bp=label.excess_return_bp,
                            sector_excess_return_bp=(
                                label.sector_excess_return_bp
                            ),
                            sector_excess_observed=(
                                label.sector_excess_observed
                            ),
                            sector_excess_missing_reason=(
                                label.sector_excess_missing_reason
                            ),
                            downside_observed=label.downside_observed,
                            mae_bp=label.mae_loss_bp,
                            mfe_bp=label.mfe_gain_bp,
                            realized_volatility_bp=(
                                label.realized_volatility_bp
                            ),
                            max_drawdown_bp=label.max_drawdown_bp,
                            tail_loss_bp=label.tail_loss_bp,
                            fill_feasible_observed=(
                                label.fill_feasible_observed
                            ),
                        )
                        for label in labels_by_symbol[symbol]
                    ),
                )
                writer = writers.get(
                    year=decision_year,
                    header={
                        **header_common,
                        "year": decision_year,
                    },
                )
                write_with_context = getattr(
                    writer,
                    "write_sample_with_context",
                    None,
                )
                if callable(write_with_context):
                    write_with_context(
                        sample,
                        sector_id=sector_id,
                        stock_current=stock_current,
                    )
                else:
                    writer.write_sample(sample)
                sample_count += 1
        return teacher_incomplete_count, sample_count


def _initialize_spool(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=FILE")
    connection.executescript(
        """
        CREATE TABLE observations (
            sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            feature_id TEXT NOT NULL,
            source_table TEXT NOT NULL,
            event_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            quality TEXT NOT NULL,
            source_row_hash TEXT NOT NULL,
            source_value_hash TEXT NOT NULL,
            value_int INTEGER,
            scale INTEGER NOT NULL,
            stale_after_days INTEGER NOT NULL,
            formal_training_eligible INTEGER NOT NULL,
            missing_mask INTEGER NOT NULL,
            quality_blocked_mask INTEGER NOT NULL
        );
        CREATE INDEX idx_observations_available
            ON observations(available_at, event_at, revision_id, source_row_hash);
        CREATE TABLE current_features (
            scope TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            feature_id TEXT NOT NULL,
            event_period TEXT NOT NULL,
            value_int INTEGER,
            scale INTEGER NOT NULL,
            event_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            quality TEXT NOT NULL,
            source_value_hash TEXT NOT NULL,
            stale_after_days INTEGER NOT NULL,
            formal_training_eligible INTEGER NOT NULL,
            missing_mask INTEGER NOT NULL,
            quality_blocked_mask INTEGER NOT NULL,
            PRIMARY KEY(scope, entity_key, feature_id, event_period)
        ) WITHOUT ROWID;
        CREATE INDEX idx_current_features_lookup
            ON current_features(
                scope, entity_key, feature_id, event_period,
                available_at, revision_id
            );
        CREATE TABLE prices (
            scope TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            event_date TEXT NOT NULL,
            available_at TEXT NOT NULL,
            open_int INTEGER,
            open_scale INTEGER,
            high_int INTEGER,
            high_scale INTEGER,
            low_int INTEGER,
            low_scale INTEGER,
            close_int INTEGER,
            close_scale INTEGER,
            source_row_hash TEXT NOT NULL,
            PRIMARY KEY(scope, entity_key, event_date)
        ) WITHOUT ROWID;
        CREATE INDEX idx_prices_scope_entity_date
            ON prices(scope, entity_key, event_date);
        CREATE TABLE labels (
            symbol TEXT NOT NULL,
            decision_date TEXT NOT NULL,
            horizon INTEGER NOT NULL,
            horizon_end_date TEXT NOT NULL,
            available_at TEXT NOT NULL,
            excess_return_bp INTEGER NOT NULL,
            sector_excess_return_bp INTEGER,
            sector_excess_observed INTEGER NOT NULL,
            sector_excess_missing_reason TEXT,
            downside_observed INTEGER NOT NULL,
            mae_loss_bp INTEGER NOT NULL,
            mfe_gain_bp INTEGER NOT NULL,
            realized_volatility_bp INTEGER NOT NULL,
            max_drawdown_bp INTEGER NOT NULL,
            tail_loss_bp INTEGER NOT NULL,
            fill_feasible_observed INTEGER NOT NULL,
            source_hash TEXT NOT NULL,
            PRIMARY KEY(symbol, decision_date, horizon)
        ) WITHOUT ROWID;
        CREATE INDEX idx_labels_decision
            ON labels(decision_date, symbol, horizon);
        CREATE TABLE label_exclusions (
            symbol TEXT NOT NULL,
            decision_date TEXT NOT NULL,
            horizon INTEGER NOT NULL,
            horizon_end_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            event_effective_date TEXT NOT NULL,
            PRIMARY KEY(symbol, decision_date, horizon, reason)
        ) WITHOUT ROWID;
        CREATE INDEX idx_label_exclusions_decision
            ON label_exclusions(decision_date, symbol, horizon);
        CREATE TABLE sector_memberships (
            symbol TEXT NOT NULL,
            sector_id TEXT NOT NULL,
            available_at TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            effective_to TEXT,
            status TEXT NOT NULL CHECK(status = 'accepted'),
            source_id TEXT NOT NULL,
            license_id TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            PRIMARY KEY(symbol, available_at, effective_from, sector_id)
        ) WITHOUT ROWID;
        """
    )


def _base_feature_definitions(
    manifest: Mapping[str, Any],
) -> dict[str, _FeatureDefinition]:
    result: dict[str, _FeatureDefinition] = {}
    for payload in _mapping_sequence(
        manifest.get("features"), field_name="features"
    ):
        base_feature_id = str(payload["feature_id"])
        table_name = str(payload["table_name"])
        definition = _definition_from_manifest(
            payload=payload,
            feature_id=base_feature_id,
            base_feature_id=base_feature_id,
        )
        result[definition.feature_id] = definition
    return result


def _definition_from_manifest(
    *,
    payload: Mapping[str, Any],
    feature_id: str,
    base_feature_id: str,
) -> _FeatureDefinition:
    table_name = str(payload["table_name"])
    return _FeatureDefinition(
        feature_id=feature_id,
        base_feature_id=base_feature_id,
        table_name=table_name,
        family_id=str(payload["family"]),
        source_id=str(payload["source_id"]),
        scale=int(payload["scale"]),
        stale_after_days=int(payload["staleness_days"]),
        record_hash=str(payload["record_hash"]),
        scope=_scope_for_table(table_name),
        dimension_values=(),
    )


def _runtime_definition(
    *,
    base_feature_id: str,
    table_name: str,
    entity_id: str,
    definitions: dict[str, _FeatureDefinition],
) -> _FeatureDefinition:
    existing = definitions.get(base_feature_id)
    if table_name not in _LONG_FORMAT_TABLES:
        if existing is None:
            raise ValueError(f"raw feature is absent from manifest: {base_feature_id}")
        return existing
    dimension = _long_format_dimension(table_name, entity_id)
    runtime_feature_id = (
        f"{base_feature_id}::"
        f"{_sha256_json({'dimension': dimension})[7:23]}"
    )
    runtime = definitions.get(runtime_feature_id)
    if runtime is not None:
        return runtime
    if existing is None:
        raise ValueError(f"raw feature is absent from manifest: {base_feature_id}")
    runtime = _FeatureDefinition(
        feature_id=runtime_feature_id,
        base_feature_id=base_feature_id,
        table_name=existing.table_name,
        family_id=existing.family_id,
        source_id=existing.source_id,
        scale=existing.scale,
        stale_after_days=existing.stale_after_days,
        record_hash=_sha256_json(
            {
                "base_record_hash": existing.record_hash,
                "dimension": dimension,
            }
        ),
        scope=existing.scope,
        dimension_values=dimension,
    )
    definitions[runtime_feature_id] = runtime
    return runtime


def _finalize_long_format_definitions(
    *,
    runtime_definitions: dict[str, _FeatureDefinition],
    base_definitions: Mapping[str, _FeatureDefinition],
) -> None:
    expanded_bases = {
        definition.base_feature_id
        for feature_id, definition in runtime_definitions.items()
        if feature_id != definition.base_feature_id
    }
    for base_feature_id, definition in base_definitions.items():
        if (
            definition.table_name in _LONG_FORMAT_TABLES
            and base_feature_id in expanded_bases
        ):
            runtime_definitions.pop(base_feature_id, None)


def _scope_for_table(table_name: str) -> str:
    if table_name in _STOCK_TABLES:
        return "stock"
    if table_name == "market_indices":
        return "market"
    if table_name == "industry_indices":
        return "industry"
    raise ValueError(f"unsupported raw source table: {table_name}")


def _scope_and_entity(*, table_name: str, entity_id: str) -> tuple[str, str]:
    scope = _scope_for_table(table_name)
    if scope == "stock":
        symbol = entity_id.split("|", 1)[0].strip()
        if not symbol:
            raise ValueError("stock observation requires symbol identity")
        return scope, symbol
    if not entity_id.strip():
        raise ValueError("global observation requires entity identity")
    return scope, entity_id


def _long_format_dimension(table_name: str, entity_id: str) -> tuple[str, ...]:
    parts = tuple(entity_id.split("|"))
    dimension: tuple[str, ...]
    if table_name == "fundamental_statement_items":
        if len(parts) < 4:
            raise ValueError("statement item identity is incomplete")
        dimension = (parts[1], parts[3])
    elif table_name == "fundamental_valuation_metrics":
        if len(parts) < 2:
            raise ValueError("valuation metric identity is incomplete")
        dimension = (parts[1],)
    else:
        raise ValueError("table is not long-format")
    return dimension


def _price_record(
    *,
    table_name: str,
    entity_key: str,
    event_at: str,
    available_at: str,
    source_row_hash: str,
    values: Mapping[str, tuple[int | None, int]],
) -> tuple[object, ...] | None:
    open_keys: tuple[str, ...]
    high_keys: tuple[str, ...]
    low_keys: tuple[str, ...]
    close_keys: tuple[str, ...]
    if table_name == "daily_prices":
        scope = "stock"
        open_keys = ("daily_prices.開盤價",)
        high_keys = ("daily_prices.最高價",)
        low_keys = ("daily_prices.最低價",)
        close_keys = ("daily_prices.收盤價",)
    elif table_name == "market_indices":
        scope = "market"
        open_keys = ("market_indices.開盤價",)
        high_keys = ("market_indices.最高價",)
        low_keys = ("market_indices.最低價",)
        close_keys = (
            "market_indices.收盤指數",
            "market_indices.收盤價",
        )
    else:
        return None
    open_value = _first_price(values, open_keys)
    close_value = _first_price(values, close_keys)
    if open_value is None and close_value is None:
        return None
    high_value = _first_price(values, high_keys)
    low_value = _first_price(values, low_keys)
    return (
        scope,
        entity_key,
        event_at[:10],
        available_at,
        *(open_value or (None, None)),
        *(high_value or (None, None)),
        *(low_value or (None, None)),
        *(close_value or (None, None)),
        source_row_hash,
    )


def _first_price(
    values: Mapping[str, tuple[int | None, int]],
    keys: Sequence[str],
) -> tuple[int | None, int] | None:
    for key in keys:
        value = values.get(key)
        if value is not None:
            return value
    return None


def _insert_observations(
    connection: sqlite3.Connection,
    rows: Sequence[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT INTO observations(
            scope, entity_key, feature_id, source_table,
            event_at, available_at, revision_id, quality, source_row_hash,
            source_value_hash, value_int, scale, stale_after_days,
            formal_training_eligible, missing_mask, quality_blocked_mask
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (*row[:4], *row[6:])
            for row in rows
        ),
    )


def _insert_prices(
    connection: sqlite3.Connection,
    rows: Sequence[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO prices(
            scope, entity_key, event_date, available_at,
            open_int, open_scale, high_int, high_scale,
            low_int, low_scale, close_int, close_scale, source_row_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _spool_sector_memberships(
    connection: sqlite3.Connection,
    path: Path | None,
    *,
    training_as_of: datetime | None = None,
) -> tuple[str, int]:
    if path is None:
        return "sha256:" + ("0" * 64), 0
    resolved = path.resolve()
    payloads, canonical_manifest_hash = (
        _load_sector_membership_sidecar(resolved)
    )
    rows: list[
        tuple[
            str,
            str,
            str,
            str,
            str | None,
            str,
            str,
            str,
            str,
        ]
    ] = []
    natural_keys: set[tuple[str, str, str, str]] = set()
    for payload in payloads:
        required_fields = {
            "symbol",
            "sector_id",
            "available_at",
            "effective_from",
            "status",
            "source_id",
            "license_id",
            "source_hash",
        }
        allowed_fields = required_fields | {"effective_to"}
        missing_fields = sorted(required_fields - set(payload))
        unknown_fields = sorted(set(payload) - allowed_fields)
        if missing_fields or unknown_fields:
            raise ValueError(
                "sector membership row fields invalid: "
                f"missing={','.join(missing_fields)}; "
                f"unknown={','.join(unknown_fields)}"
            )
        status = _required_text(
            payload.get("status"), field_name="status"
        )
        if status != "accepted":
            raise ValueError(
                "blocker:sector_membership_status_not_accepted"
            )
        source_id = _required_text(
            payload.get("source_id"), field_name="source_id"
        )
        if _is_current_company_snapshot_source(source_id):
            raise ValueError(
                "blocker:current_companies_snapshot_not_historical_pit"
            )
        license_id = _required_text(
            payload.get("license_id"), field_name="license_id"
        )
        symbol = _required_text(payload.get("symbol"), field_name="symbol")
        sector_id = _required_text(
            payload.get("sector_id"), field_name="sector_id"
        )
        available_datetime = _available_datetime(
            _required_text(
                payload.get("available_at"), field_name="available_at"
            ),
            field_name="available_at",
        )
        if (
            training_as_of is not None
            and available_datetime > training_as_of
        ):
            raise ValueError(
                "blocker:sector_membership_available_after_training_as_of"
            )
        available_at = available_datetime.isoformat()
        effective_from_date = _parse_date(
            _required_text(
                payload.get("effective_from"), field_name="effective_from"
            ),
            field_name="effective_from",
        )
        effective_from = effective_from_date.isoformat()
        effective_to_raw = payload.get("effective_to")
        effective_to_date = (
            None if effective_to_raw in (None, "") else _parse_date(
                str(effective_to_raw), field_name="effective_to"
            )
        )
        if (
            effective_to_date is not None
            and effective_to_date < effective_from_date
        ):
            raise ValueError(
                "sector membership effective_to precedes effective_from"
            )
        effective_to = (
            None
            if effective_to_date is None
            else effective_to_date.isoformat()
        )
        source_hash = _required_text(
            payload.get("source_hash"), field_name="source_hash"
        )
        _require_sha256(source_hash, field_name="source_hash")
        natural_key = (
            symbol,
            available_at,
            effective_from,
            sector_id,
        )
        if natural_key in natural_keys:
            raise ValueError(
                "sector membership natural keys must be unique"
            )
        natural_keys.add(natural_key)
        rows.append(
            (
                symbol,
                sector_id,
                available_at,
                effective_from,
                effective_to,
                status,
                source_id,
                license_id,
                source_hash,
            )
        )
    connection.executemany(
        """
        INSERT INTO sector_memberships(
            symbol, sector_id, available_at, effective_from,
            effective_to, status, source_id, license_id, source_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()
    return canonical_manifest_hash, len(rows)


def _load_sector_membership_sidecar(
    path: Path,
) -> tuple[tuple[Mapping[str, Any], ...], str]:
    """載入並驗證具 canonical manifest 的產業歸屬 sidecar。"""

    if path.suffix.lower() == ".json":
        envelope = _as_mapping(
            json.loads(path.read_text(encoding="utf-8")),
            field_name="sector membership sidecar",
        )
    else:
        opener = gzip.open if path.suffix.lower() == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as stream:
            records = tuple(
                _as_mapping(
                    json.loads(line),
                    field_name="sector membership sidecar record",
                )
                for line in stream
                if line.strip()
            )
        if not records:
            raise ValueError("sector membership sidecar is empty")
        header = records[0]
        if header.get("record_type") != "manifest":
            raise ValueError(
                "sector membership JSONL must start with manifest"
            )
        if set(header) != {
            "record_type",
            "schema_version",
            "manifest",
        }:
            raise ValueError(
                "sector membership JSONL manifest fields are invalid"
            )
        jsonl_rows: list[Mapping[str, Any]] = []
        for record in records[1:]:
            if record.get("record_type") != "membership":
                raise ValueError(
                    "sector membership JSONL contains unknown record type"
                )
            if set(record) != {"record_type", "row"}:
                raise ValueError(
                    "sector membership JSONL row fields are invalid"
                )
            jsonl_rows.append(
                _as_mapping(
                    record.get("row"),
                    field_name="sector membership row",
                )
            )
        envelope = {
            "schema_version": header.get("schema_version"),
            "manifest": header.get("manifest"),
            "rows": jsonl_rows,
        }
    if set(envelope) != {"schema_version", "manifest", "rows"}:
        raise ValueError(
            "sector membership sidecar fields must be "
            "schema_version, manifest, rows"
        )
    schema_version = _required_text(
        envelope.get("schema_version"),
        field_name="sector membership schema_version",
    )
    if schema_version != SECTOR_MEMBERSHIP_SIDECAR_SCHEMA_VERSION:
        raise ValueError(
            "unsupported sector membership sidecar schema"
        )
    payload_rows = _mapping_sequence(
        envelope.get("rows"), field_name="sector membership rows"
    )
    manifest = dict(
        _as_mapping(
            envelope.get("manifest"),
            field_name="sector membership manifest",
        )
    )
    canonical_hash = _required_text(
        manifest.pop("canonical_hash", None),
        field_name="sector membership manifest canonical_hash",
    )
    _require_sha256(
        canonical_hash,
        field_name="sector membership manifest canonical_hash",
    )
    manifest_schema = _required_text(
        manifest.get("schema_version"),
        field_name="sector membership manifest schema_version",
    )
    if manifest_schema != SECTOR_MEMBERSHIP_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            "unsupported sector membership manifest schema"
        )
    row_count = manifest.get("row_count")
    if (
        isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or row_count < 0
    ):
        raise TypeError(
            "sector membership manifest row_count must be non-negative integer"
        )
    if row_count != len(payload_rows):
        raise ValueError(
            "sector membership manifest row_count mismatch"
        )
    rows_hash = _required_text(
        manifest.get("rows_hash"),
        field_name="sector membership manifest rows_hash",
    )
    _require_sha256(
        rows_hash,
        field_name="sector membership manifest rows_hash",
    )
    if rows_hash != _sha256_json(
        [dict(row) for row in payload_rows]
    ):
        raise ValueError("sector membership manifest rows hash mismatch")
    expected_canonical_hash = _sha256_json(
        {
            "sidecar_schema_version": schema_version,
            "manifest": manifest,
        }
    )
    if canonical_hash != expected_canonical_hash:
        raise ValueError(
            "sector membership manifest canonical hash mismatch"
        )
    return payload_rows, canonical_hash


def _load_corporate_action_custody(
    manifest_path: Path | None,
    *,
    training_as_of: datetime,
) -> _CorporateActionCustody:
    if manifest_path is None:
        return _CorporateActionCustody(
            manifest_present=False,
            manifest_hash=_ZERO_SHA256,
            manifest_file_hash=_ZERO_SHA256,
            canonical_events_hash=_ZERO_SHA256,
            canonical_event_count=0,
            label_ledger_event_count=0,
            eligible_label_ledger_event_count=0,
            eligible_effective_date_count=0,
            effective_dates_by_symbol={},
        )
    resolved_manifest = manifest_path.resolve()
    manifest = _read_json(resolved_manifest)
    if (
        manifest.get("schema_version")
        != _OFFICIAL_MARKET_EVENT_PUBLICATION_SCHEMA_VERSION
    ):
        raise ValueError(
            "unsupported official corporate action publication schema"
        )
    if manifest.get("status") != "formal_source_publication":
        raise ValueError(
            "corporate action manifest is not a formal source publication"
        )
    expected_manifest_hash = _required_text(
        manifest.get("manifest_hash"),
        field_name="corporate action manifest_hash",
    )
    _require_sha256(
        expected_manifest_hash,
        field_name="corporate action manifest_hash",
    )
    logical_manifest = dict(manifest)
    logical_manifest.pop("manifest_hash", None)
    if _sha256_json(logical_manifest) != expected_manifest_hash:
        raise ValueError("corporate action logical manifest hash mismatch")
    manifest_file_hash = _file_sha256(resolved_manifest)
    safety = _as_mapping(
        manifest.get("safety"),
        field_name="corporate action safety",
    )
    required_true_safety = (
        "formal_source_publication",
        "append_only_canonical_events",
        "available_at_effective_at_separated",
        "unlinked_revision_fails_closed",
        "result_tables_label_ledger_only",
        "atomic_latest_manifest_publish",
    )
    for field_name in required_true_safety:
        if not _required_json_bool(
            safety.get(field_name),
            field_name=f"corporate action safety.{field_name}",
        ):
            raise ValueError(
                f"corporate action safety.{field_name} must be true"
            )
    if _required_json_bool(
        safety.get("result_tables_decision_feature_allowed"),
        field_name=(
            "corporate action safety."
            "result_tables_decision_feature_allowed"
        ),
    ):
        raise ValueError(
            "corporate action result tables cannot be decision features"
        )
    canonical = _as_mapping(
        manifest.get("canonical_events"),
        field_name="corporate action canonical_events",
    )
    if canonical.get("schema_version") != _OFFICIAL_MARKET_EVENT_SCHEMA_VERSION:
        raise ValueError("unsupported corporate action event schema")
    relative_path = _required_text(
        canonical.get("path"),
        field_name="corporate action canonical events path",
    )
    publication_root = resolved_manifest.parent.resolve()
    events_path = (publication_root / relative_path).resolve()
    if not events_path.is_relative_to(publication_root):
        raise ValueError("corporate action event path escapes publication")
    expected_events_hash = _required_text(
        canonical.get("file_hash"),
        field_name="corporate action canonical events file_hash",
    )
    _require_sha256(
        expected_events_hash,
        field_name="corporate action canonical events file_hash",
    )
    if _file_sha256(events_path) != expected_events_hash:
        raise ValueError("corporate action canonical events hash mismatch")
    expected_count = canonical.get("event_count")
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count < 0
    ):
        raise TypeError(
            "corporate action canonical event_count must be "
            "non-negative integer"
        )

    revision_keys: set[tuple[str, str]] = set()
    revision_chains: dict[
        str,
        list[
            tuple[
                datetime,
                datetime | None,
                int,
                str,
                str | None,
                bool,
            ]
        ],
    ] = {}
    label_ledger_count = 0
    eligible_label_ledger_count = 0
    eligible_effective_dates: dict[str, set[str]] = {}
    eligible_dates: list[str] = []
    observed_count = 0
    with events_path.open("rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                event = _as_mapping(
                    json.loads(line),
                    field_name=(
                        f"corporate action event line {line_number}"
                    ),
                )
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "corporate action canonical JSONL is invalid at "
                    f"line {line_number}"
                ) from exc
            observed_count += 1
            if event.get("schema_version") != _OFFICIAL_MARKET_EVENT_SCHEMA_VERSION:
                raise ValueError("unsupported corporate action event row schema")
            natural_key = _required_text(
                event.get("natural_key"),
                field_name="corporate action natural_key",
            )
            event_id = _required_text(
                event.get("event_id"),
                field_name="corporate action event_id",
            )
            _require_sha256(event_id, field_name="corporate action event_id")
            expected_event_id = (
                "sha256:"
                + hashlib.sha256(natural_key.encode("utf-8")).hexdigest()
            )
            if event_id != expected_event_id:
                raise ValueError("corporate action event_id mismatch")
            for hash_field in (
                "raw_response_sha256",
                "event_chain_id",
                "source_record_hash",
                "revision_id",
            ):
                hash_value = _required_text(
                    event.get(hash_field),
                    field_name=f"corporate action {hash_field}",
                )
                _require_sha256(
                    hash_value,
                    field_name=f"corporate action {hash_field}",
                )
            revision_id = _required_text(
                event.get("revision_id"),
                field_name="corporate action revision_id",
            )
            revision_key = (natural_key, revision_id)
            if revision_key in revision_keys:
                raise ValueError(
                    "corporate action revisions must be unique"
                )
            revision_keys.add(revision_key)
            predecessor = event.get("predecessor_event_id")
            if predecessor is not None:
                _require_sha256(
                    _required_text(
                        predecessor,
                        field_name=(
                            "corporate action predecessor_event_id"
                        ),
                    ),
                    field_name="corporate action predecessor_event_id",
                )
            source_record = dict(
                _as_mapping(
                    event.get("source_record"),
                    field_name="corporate action source_record",
                )
            )
            if _sha256_json(source_record) != event.get(
                "source_record_hash"
            ):
                raise ValueError(
                    "corporate action source_record_hash mismatch"
                )
            if event.get("revision_id") != event.get("source_record_hash"):
                raise ValueError(
                    "corporate action unlinked revision is not fail closed"
                )
            if _required_json_bool(
                event.get("formal_decision_feature_allowed"),
                field_name=(
                    "corporate action formal_decision_feature_allowed"
                ),
            ):
                raise ValueError(
                    "post-event corporate action cannot be a feature"
                )
            result_only = _required_json_bool(
                event.get("result_only"),
                field_name="corporate action result_only",
            )
            formal_label_allowed = _required_json_bool(
                event.get("formal_label_ledger_allowed"),
                field_name=(
                    "corporate action formal_label_ledger_allowed"
                ),
            )
            formal_restriction_allowed = _required_json_bool(
                event.get("formal_trading_restriction_allowed"),
                field_name=(
                    "corporate action formal_trading_restriction_allowed"
                ),
            )
            effective = _available_datetime(
                _required_text(
                    event.get("effective_at"),
                    field_name="corporate action effective_at",
                ),
                field_name="corporate action effective_at",
            )
            event_at = _available_datetime(
                _required_text(
                    event.get("event_at"),
                    field_name="corporate action event_at",
                ),
                field_name="corporate action event_at",
            )
            available = _available_datetime(
                _required_text(
                    event.get("available_at"),
                    field_name="corporate action available_at",
                ),
                field_name="corporate action available_at",
            )
            if event_at != effective or available < effective:
                raise ValueError(
                    "corporate action availability/effective ordering invalid"
                )
            announced_raw = event.get("announced_at")
            announced = (
                None
                if announced_raw is None
                else _available_datetime(
                    _required_text(
                        announced_raw,
                        field_name="corporate action announced_at",
                    ),
                    field_name="corporate action announced_at",
                )
            )
            if announced is not None and available < announced:
                raise ValueError(
                    "corporate action available_at precedes announced_at"
                )
            ordinal_raw = event.get("source_row_ordinal")
            source_row_ordinal = (
                2_147_483_647
                if ordinal_raw is None
                else _required_positive_int(
                    ordinal_raw,
                    field_name="corporate action source_row_ordinal",
                )
            )
            supersedes_raw = event.get("supersedes_revision_id")
            supersedes_revision_id = (
                None
                if supersedes_raw is None
                else _required_text(
                    supersedes_raw,
                    field_name=(
                        "corporate action supersedes_revision_id"
                    ),
                )
            )
            if supersedes_revision_id is not None:
                _require_sha256(
                    supersedes_revision_id,
                    field_name=(
                        "corporate action supersedes_revision_id"
                    ),
                )
            ambiguity = _required_json_bool(
                event.get("revision_availability_ambiguous"),
                field_name=(
                    "corporate action "
                    "revision_availability_ambiguous"
                ),
            )
            revision_chains.setdefault(natural_key, []).append(
                (
                    available,
                    announced,
                    source_row_ordinal,
                    revision_id,
                    supersedes_revision_id,
                    ambiguity,
                )
            )
            if not result_only:
                if formal_label_allowed or not formal_restriction_allowed:
                    raise ValueError(
                        "trading restriction event usage flags invalid"
                    )
                continue
            if not formal_label_allowed or formal_restriction_allowed:
                raise ValueError(
                    "result-only corporate action usage flags invalid"
                )
            event_type = _required_text(
                event.get("event_type"),
                field_name="corporate action event_type",
            )
            if event_type not in _CORPORATE_ACTION_LABEL_EVENT_TYPES:
                raise ValueError(
                    "unsupported result-only corporate action event_type"
                )
            if event.get("effective_precision") != "date":
                raise ValueError(
                    "result-only corporate action must use date precision"
                )
            label_ledger_count += 1
            if available > training_as_of:
                continue
            eligible_label_ledger_count += 1
            symbol = _required_text(
                event.get("symbol"),
                field_name="corporate action symbol",
            )
            effective_date = effective.date().isoformat()
            eligible_effective_dates.setdefault(symbol, set()).add(
                effective_date
            )
            eligible_dates.append(effective_date)
    if observed_count != expected_count:
        raise ValueError("corporate action canonical event_count mismatch")
    _validate_corporate_action_revision_chains(revision_chains)
    normalized_dates = {
        symbol: tuple(sorted(dates))
        for symbol, dates in sorted(eligible_effective_dates.items())
    }
    return _CorporateActionCustody(
        manifest_present=True,
        manifest_hash=expected_manifest_hash,
        manifest_file_hash=manifest_file_hash,
        canonical_events_hash=expected_events_hash,
        canonical_event_count=observed_count,
        label_ledger_event_count=label_ledger_count,
        eligible_label_ledger_event_count=eligible_label_ledger_count,
        eligible_effective_date_count=sum(
            len(dates) for dates in normalized_dates.values()
        ),
        effective_dates_by_symbol=normalized_dates,
        min_effective_date=min(eligible_dates) if eligible_dates else None,
        max_effective_date=max(eligible_dates) if eligible_dates else None,
    )


def _validate_corporate_action_revision_chains(
    chains: Mapping[
        str,
        Sequence[
            tuple[
                datetime,
                datetime | None,
                int,
                str,
                str | None,
                bool,
            ]
        ],
    ],
) -> None:
    minimum_announced = datetime.min.replace(tzinfo=_TAIPEI)
    for natural_key, revisions in chains.items():
        availability_counts: dict[datetime, int] = {}
        for revision in revisions:
            availability_counts[revision[0]] = (
                availability_counts.get(revision[0], 0) + 1
            )
        ordered = sorted(
            revisions,
            key=lambda revision: (
                revision[0],
                revision[1] or minimum_announced,
                revision[2],
                revision[3],
            ),
        )
        previous_revision_id: str | None = None
        for revision in ordered:
            if revision[4] != previous_revision_id:
                raise ValueError(
                    "corporate action revision chain is unlinked: "
                    f"{natural_key}"
                )
            expected_ambiguity = availability_counts[revision[0]] > 1
            if revision[5] != expected_ambiguity:
                raise ValueError(
                    "corporate action revision ambiguity diagnostic "
                    f"mismatch: {natural_key}"
                )
            previous_revision_id = revision[3]


def _is_current_company_snapshot_source(source_id: str) -> bool:
    """阻擋已知只有當期狀態、沒有歷史 availability 的公司快照。"""

    normalized = source_id.strip().casefold().replace("\\", "/")
    hyphenated = normalized.replace("_", "-")
    return (
        "companies.csv" in normalized
        or "current-companies" in hyphenated
        or "current-company-registry" in hyphenated
        or "company-registry-current" in hyphenated
        or "company-registry-snapshot" in hyphenated
        or (
            ("company" in hyphenated or "companies" in hyphenated)
            and any(
                marker in hyphenated
                for marker in ("current", "latest", "snapshot")
            )
            and "historical" not in hyphenated
        )
    )


def _build_label_spool(
    *,
    connection: sqlite3.Connection,
    benchmark_entity_id: str,
    cutoff: datetime,
    horizons: tuple[int, ...],
    batch_size: int,
    corporate_action_effective_dates: (
        Mapping[str, tuple[str, ...]] | None
    ) = None,
) -> tuple[
    tuple[str, ...],
    dict[tuple[str, int], tuple[int, str, str]],
]:
    benchmark_rows = tuple(
        connection.execute(
            """
            SELECT * FROM prices
            WHERE scope='market' AND entity_key=?
              AND available_at <= ?
            ORDER BY event_date
            """,
            (benchmark_entity_id, cutoff.isoformat()),
        )
    )
    benchmark_by_date = {
        str(row["event_date"]): row for row in benchmark_rows
    }
    calendar = tuple(sorted(benchmark_by_date))
    if len(calendar) <= max(horizons):
        raise ValueError("benchmark history is too short for configured horizons")
    benchmark_returns: dict[tuple[str, int], tuple[int, str, str]] = {}
    for index, decision_date in enumerate(calendar):
        entry = benchmark_by_date[decision_date]
        if not _positive_price(entry["open_int"], entry["open_scale"]):
            continue
        for horizon in horizons:
            end_index = index + horizon - 1
            if end_index >= len(calendar):
                continue
            end_date = calendar[end_index]
            exit_row = benchmark_by_date[end_date]
            if not _positive_price(exit_row["close_int"], exit_row["close_scale"]):
                continue
            available = max(
                str(entry["available_at"]), str(exit_row["available_at"])
            )
            if _available_datetime(
                available, field_name="benchmark label available_at"
            ) > cutoff:
                continue
            benchmark_returns[(decision_date, horizon)] = (
                _return_bp(
                    entry_int=int(entry["open_int"]),
                    entry_scale=int(entry["open_scale"]),
                    exit_int=int(exit_row["close_int"]),
                    exit_scale=int(exit_row["close_scale"]),
                ),
                end_date,
                available,
            )
    symbols = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT entity_key FROM prices "
            "WHERE scope='stock' ORDER BY entity_key"
        )
    )
    industry_price_cache: dict[str, dict[str, sqlite3.Row]] = {}
    label_batch: list[tuple[object, ...]] = []
    exclusion_batch: list[tuple[object, ...]] = []
    corporate_dates = corporate_action_effective_dates or {}
    for symbol in symbols:
        stock_rows = tuple(
            connection.execute(
                """
                SELECT * FROM prices
                WHERE scope='stock' AND entity_key=?
                ORDER BY event_date
                """,
                (symbol,),
            )
        )
        stock_by_date = {
            str(row["event_date"]): row for row in stock_rows
        }
        membership_rows = tuple(
            connection.execute(
                """
                SELECT sector_id, available_at, effective_from, effective_to
                FROM sector_memberships
                WHERE symbol=? AND status='accepted'
                ORDER BY available_at, effective_from, sector_id
                """,
                (symbol,),
            )
        )
        for index, decision_date in enumerate(calendar):
            entry = stock_by_date.get(decision_date)
            if entry is None or not _positive_price(
                entry["open_int"], entry["open_scale"]
            ):
                continue
            labels: list[tuple[object, ...]] = []
            for horizon in horizons:
                benchmark = benchmark_returns.get((decision_date, horizon))
                if benchmark is None:
                    continue
                benchmark_return, end_date, benchmark_available = benchmark
                exit_row = stock_by_date.get(end_date)
                if exit_row is None or not _positive_price(
                    exit_row["close_int"], exit_row["close_scale"]
                ):
                    continue
                available_at = max(
                    str(entry["available_at"]),
                    str(exit_row["available_at"]),
                    benchmark_available,
                )
                stock_return = _return_bp(
                    entry_int=int(entry["open_int"]),
                    entry_scale=int(entry["open_scale"]),
                    exit_int=int(exit_row["close_int"]),
                    exit_scale=int(exit_row["close_scale"]),
                )
                excess = (
                    stock_return
                    - benchmark_return
                    - _BUY_COST_BP
                    - _SELL_COST_BP
                )
                sector_id = _pit_sector_id(
                    membership_rows=membership_rows,
                    decision_date=decision_date,
                )
                sector_excess: int | None = None
                sector_observed = False
                sector_missing_reason: str | None
                sector_entry_hash: str | None = None
                sector_exit_hash: str | None = None
                if sector_id is None:
                    sector_missing_reason = (
                        "pit_sector_membership_unavailable_at_decision"
                    )
                else:
                    industry_by_date = industry_price_cache.get(sector_id)
                    if industry_by_date is None:
                        industry_by_date = {
                            str(row["event_date"]): row
                            for row in connection.execute(
                                """
                                SELECT * FROM prices
                                WHERE scope='industry' AND entity_key=?
                                ORDER BY event_date
                                """,
                                (sector_id,),
                            )
                        }
                        industry_price_cache[sector_id] = industry_by_date
                    sector_entry = industry_by_date.get(decision_date)
                    sector_exit = industry_by_date.get(end_date)
                    if (
                        sector_entry is None
                        or sector_exit is None
                        or not _positive_price(
                            sector_entry["open_int"],
                            sector_entry["open_scale"],
                        )
                        or not _positive_price(
                            sector_exit["close_int"],
                            sector_exit["close_scale"],
                        )
                    ):
                        sector_missing_reason = (
                            "pit_sector_benchmark_price_unavailable"
                        )
                    else:
                        sector_return = _return_bp(
                            entry_int=int(sector_entry["open_int"]),
                            entry_scale=int(sector_entry["open_scale"]),
                            exit_int=int(sector_exit["close_int"]),
                            exit_scale=int(sector_exit["close_scale"]),
                        )
                        sector_excess = (
                            stock_return
                            - sector_return
                            - _BUY_COST_BP
                            - _SELL_COST_BP
                        )
                        sector_observed = True
                        sector_missing_reason = None
                        sector_entry_hash = str(
                            sector_entry["source_row_hash"]
                        )
                        sector_exit_hash = str(
                            sector_exit["source_row_hash"]
                        )
                        available_at = max(
                            available_at,
                            str(sector_entry["available_at"]),
                            str(sector_exit["available_at"]),
                        )
                if _available_datetime(
                    available_at, field_name="label available_at"
                ) > cutoff:
                    continue
                corporate_action_date = (
                    _corporate_action_effective_date_in_horizon(
                        effective_dates=corporate_dates.get(symbol, ()),
                        decision_date=decision_date,
                        horizon_end_date=end_date,
                    )
                )
                if corporate_action_date is not None:
                    exclusion_batch.append(
                        (
                            symbol,
                            decision_date,
                            horizon,
                            end_date,
                            _CORPORATE_ACTION_EXCLUSION_REASON,
                            corporate_action_date,
                        )
                    )
                    if len(exclusion_batch) >= batch_size:
                        _insert_label_exclusions(
                            connection,
                            exclusion_batch,
                        )
                        exclusion_batch.clear()
                    continue
                # 這是 supervised outcome path；每個 horizon 必須在此重新
                # 綁定自己的 causal label suffix。不得沿用前一個 benchmark
                # 建表迴圈殘留的 end_index，否則 MAE/MFE/波動會讀到 horizon
                # 以後的結果，形成 label leakage。
                end_index = index + horizon - 1
                if (
                    end_index >= len(calendar)
                    or calendar[end_index] != end_date
                ):
                    raise RuntimeError(
                        "benchmark horizon index is inconsistent with label end date"
                    )
                path_dates = calendar[index : end_index + 1]
                path_rows = [
                    stock_by_date.get(path_date) for path_date in path_dates
                ]
                if any(path_row is None for path_row in path_rows):
                    continue
                concrete_path = [
                    path_row for path_row in path_rows if path_row is not None
                ]
                mae_loss = _mae_loss_bp(entry, concrete_path)
                mfe_gain = _mfe_gain_bp(entry, concrete_path)
                realized_volatility = _realized_volatility_bp(concrete_path)
                max_drawdown = _max_drawdown_bp(concrete_path)
                tail_loss = _tail_loss_bp(concrete_path)
                fill_feasible = _t1_fill_feasible(entry)
                source_hash = _sha256_json(
                    {
                        "symbol": symbol,
                        "decision_date": decision_date,
                        "horizon": horizon,
                        "stock_source_hashes": [
                            str(path_row["source_row_hash"])
                            for path_row in concrete_path
                        ],
                        "benchmark_entry_hash": str(
                            benchmark_by_date[decision_date]["source_row_hash"]
                        ),
                        "benchmark_exit_hash": str(
                            benchmark_by_date[end_date]["source_row_hash"]
                        ),
                        "sector_id": sector_id,
                        "sector_entry_hash": sector_entry_hash,
                        "sector_exit_hash": sector_exit_hash,
                        "sector_excess_missing_reason": (
                            sector_missing_reason
                        ),
                        "mae_loss_bp": mae_loss,
                        "mfe_gain_bp": mfe_gain,
                        "realized_volatility_bp": realized_volatility,
                        "max_drawdown_bp": max_drawdown,
                        "tail_loss_bp": tail_loss,
                        "fill_feasible_observed": fill_feasible,
                        "cost_bp": _BUY_COST_BP + _SELL_COST_BP,
                    }
                )
                labels.append(
                    (
                        symbol,
                        decision_date,
                        horizon,
                        end_date,
                        available_at,
                        excess,
                        sector_excess,
                        int(sector_observed),
                        sector_missing_reason,
                        int(excess < 0),
                        mae_loss,
                        mfe_gain,
                        realized_volatility,
                        max_drawdown,
                        tail_loss,
                        int(fill_feasible),
                        source_hash,
                    )
                )
            label_batch.extend(labels)
            if len(label_batch) >= batch_size:
                _insert_labels(connection, label_batch)
                label_batch.clear()
    if label_batch:
        _insert_labels(connection, label_batch)
    if exclusion_batch:
        _insert_label_exclusions(connection, exclusion_batch)
    connection.commit()
    return calendar, benchmark_returns


def _insert_labels(
    connection: sqlite3.Connection,
    rows: Sequence[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT INTO labels(
            symbol, decision_date, horizon, horizon_end_date, available_at,
            excess_return_bp, sector_excess_return_bp,
            sector_excess_observed, sector_excess_missing_reason,
            downside_observed, mae_loss_bp, mfe_gain_bp,
            realized_volatility_bp, max_drawdown_bp, tail_loss_bp,
            fill_feasible_observed, source_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _corporate_action_effective_date_in_horizon(
    *,
    effective_dates: tuple[str, ...],
    decision_date: str,
    horizon_end_date: str,
) -> str | None:
    index = bisect_left(effective_dates, decision_date)
    if (
        index < len(effective_dates)
        and effective_dates[index] <= horizon_end_date
    ):
        return effective_dates[index]
    return None


def _insert_label_exclusions(
    connection: sqlite3.Connection,
    rows: Sequence[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT INTO label_exclusions(
            symbol, decision_date, horizon, horizon_end_date,
            reason, event_effective_date
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _eligible_decision_dates(
    connection: sqlite3.Connection,
    *,
    years: tuple[int, ...],
) -> tuple[str, ...]:
    parameters: list[object] = [len(SUPPORTED_HORIZONS)]
    year_predicate = ""
    if years:
        year_predicate = (
            " AND CAST(substr(decision_date, 1, 4) AS INTEGER) IN "
            f"({','.join('?' for _ in years)})"
        )
        parameters.extend(years)
    rows = connection.execute(
        """
        SELECT decision_date
        FROM labels
        GROUP BY decision_date, symbol
        HAVING COUNT(DISTINCT horizon)=?
        """
        + year_predicate
        + " ORDER BY decision_date",
        tuple(parameters),
    )
    return tuple(sorted({str(row[0]) for row in rows}))


def _build_fold_windows(
    decision_dates: tuple[str, ...],
    *,
    minimum_train_dates: int,
    test_date_count: int,
    purge_trading_days: int,
    embargo_trading_days: int,
) -> tuple[_FoldWindow, ...]:
    windows: list[_FoldWindow] = []
    start_index = minimum_train_dates
    while start_index + test_date_count <= len(decision_dates):
        purge_boundary = max(0, start_index - purge_trading_days)
        train_dates = decision_dates[:purge_boundary]
        test_dates = decision_dates[
            start_index : start_index + test_date_count
        ]
        if train_dates and test_dates:
            windows.append(
                _FoldWindow(
                    fold_id=f"fold-{len(windows) + 1:03d}",
                    train_end_date=train_dates[-1],
                    test_start=test_dates[0],
                    test_end=test_dates[-1],
                    purge_trading_days=purge_trading_days,
                    embargo_trading_days=embargo_trading_days,
                )
            )
        start_index += test_date_count + embargo_trading_days
    return tuple(windows)


def _build_cash_only_portfolio_state_replay(
    *,
    calendar: tuple[str, ...],
    decision_dates: tuple[str, ...],
) -> _PortfolioStateReplay:
    """明示重播每個決策日的 T-1 state；沒有 ledger 時維持可稽核 fallback。

    Teacher target 是成熟後才可見的 supervised label，絕不可回灌成下一個
    決策日的 current state。沒有 canonical ledger 時只能延續 cash-only，
    並以 policy／transition chain 明確封存「沒有 turnover/cooldown 觀測」。
    """

    calendar_positions = {
        day: index for index, day in enumerate(calendar)
    }
    policy_payload = {
        "schema_version": _PORTFOLIO_STATE_REPLAY_SCHEMA_VERSION,
        "mode": "per_decision_t_minus_1_cash_only_fallback",
        "ledger_manifest_hash": _ZERO_SHA256,
        "teacher_targets_replayed_into_state": False,
        "weekly_turnover_fallback_bp": 0,
        "turnover_learning_claim_allowed": False,
        "cooldown_learning_claim_allowed": False,
    }
    policy_hash = _sha256_json(policy_payload)
    previous_transition_hash = _ZERO_SHA256
    previous_state_hash = _ZERO_SHA256
    entries: list[_PortfolioStateReplayEntry] = []
    cash_weights = AllocationWeightContract(positions_bp=(), cash_bp=10_000)
    for decision_date in decision_dates:
        calendar_position = calendar_positions.get(decision_date)
        if calendar_position is None or calendar_position == 0:
            raise ValueError(
                "portfolio state replay requires a provable T-1 benchmark session: "
                f"{decision_date}"
            )
        state_date = calendar[calendar_position - 1]
        transition_payload = {
            "schema_version": _PORTFOLIO_STATE_REPLAY_SCHEMA_VERSION,
            "decision_date": decision_date,
            "state_as_of_date": state_date,
            "previous_transition_hash": previous_transition_hash,
            "previous_state_hash": previous_state_hash,
            "ledger_manifest_hash": _ZERO_SHA256,
            "policy_hash": policy_hash,
            "from_weights": {
                "positions_bp": [],
                "cash_bp": 10_000,
            },
            "to_weights": {
                "positions_bp": [],
                "cash_bp": 10_000,
            },
            "weekly_turnover_used_bp": 0,
            "transition_reason": "cash_only_fallback_without_canonical_ledger",
        }
        transition_hash = _sha256_json(transition_payload)
        state = CausalPortfolioState.create(
            as_of_date=state_date,
            weights=cash_weights,
            weekly_turnover_used_bp=0,
        )
        entries.append(
            _PortfolioStateReplayEntry(
                decision_date=decision_date,
                transition_hash=transition_hash,
                state=state,
            )
        )
        previous_transition_hash = transition_hash
        previous_state_hash = state.state_hash
    return _PortfolioStateReplay(
        entries=tuple(entries),
        ledger_manifest_hash=_ZERO_SHA256,
        policy_hash=policy_hash,
        transition_chain_hash=previous_transition_hash,
        cash_only_fallback=True,
    )


def _advance_current_features(
    connection: sqlite3.Connection,
    *,
    previous_cutoff: str,
    decision_at: str,
    decision_date: str,
    batch_size: int,
    current_feature_cache: _CurrentFeatureCache | None = None,
    persist_current_history: bool = True,
) -> None:
    decision = _available_datetime(
        decision_at, field_name="current feature decision_at"
    )
    cursor = connection.execute(
        """
        SELECT * FROM observations
        WHERE available_at > ? AND available_at <= ?
        ORDER BY available_at, event_at, revision_id, source_row_hash, sequence_id
        """,
        (previous_cutoff, decision_at),
    )
    upserts: list[tuple[object, ...]] = []
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            event = _available_datetime(
                str(row["event_at"]),
                field_name="current feature event_at",
            )
            if event > decision:
                # realized observation 不可因偽造 availability 提前進入 current。
                continue
            if (
                str(row["source_table"]) in _PRICE_TECHNICAL_TABLES
                and str(row["event_at"])[:10] >= decision_date
            ):
                # 若來源被 poison 成同日或未來價量，當次決策明確忽略。
                continue
            event_period = event.date().isoformat()
            if persist_current_history:
                upserts.append(
                    (
                        row["scope"],
                        row["entity_key"],
                        row["feature_id"],
                        event_period,
                        row["value_int"],
                        row["scale"],
                        row["event_at"],
                        row["available_at"],
                        row["revision_id"],
                        row["quality"],
                        row["source_value_hash"],
                        row["stale_after_days"],
                        row["formal_training_eligible"],
                        row["missing_mask"],
                        row["quality_blocked_mask"],
                    )
                )
            if current_feature_cache is not None:
                _update_current_feature_cache(
                    current_feature_cache,
                    row=row,
                    event_period=event_period,
                )
        if persist_current_history and len(upserts) >= batch_size:
            _upsert_current(connection, upserts)
            upserts.clear()
    if persist_current_history and upserts:
        _upsert_current(connection, upserts)
    connection.commit()


def _update_current_feature_cache(
    cache: _CurrentFeatureCache,
    *,
    row: sqlite3.Row,
    event_period: str,
) -> None:
    """Mirror ``current_features`` newest-period semantics in bounded memory.

    ``_advance_current_features`` reads observations in the same deterministic
    order used by SQLite.  A later row for the same event period therefore
    replaces the prior revision, while a late revision for an older period must
    not displace a newer period.  Only one value per scope/entity/feature is
    retained, so assembly memory is bounded by the current feature surface
    rather than the full history.
    """

    scope = str(row["scope"])
    entity_key = str(row["entity_key"])
    feature_id = str(row["feature_id"])
    current_by_feature = cache.setdefault(scope, {}).setdefault(
        entity_key,
        {},
    )
    existing = current_by_feature.get(feature_id)
    if existing is not None and event_period < existing.event_at[:10]:
        return
    current_by_feature[feature_id] = _CurrentValue(
        value_int=(
            None if row["value_int"] is None else int(row["value_int"])
        ),
        scale=int(row["scale"]),
        event_at=str(row["event_at"]),
        available_at=str(row["available_at"]),
        revision_id=str(row["revision_id"]),
        quality=str(row["quality"]),
        source_value_hash=str(row["source_value_hash"]),
        stale_after_days=int(row["stale_after_days"]),
        formal_training_eligible=bool(row["formal_training_eligible"]),
        missing_mask=bool(row["missing_mask"]),
        quality_blocked_mask=bool(row["quality_blocked_mask"]),
    )


def _upsert_current(
    connection: sqlite3.Connection,
    rows: Sequence[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT OR REPLACE INTO current_features(
            scope, entity_key, feature_id, event_period, value_int, scale, event_at,
            available_at, revision_id, quality, source_value_hash,
            stale_after_days, formal_training_eligible, missing_mask,
            quality_blocked_mask
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _labels_for_decision(
    connection: sqlite3.Connection,
    decision_date: str,
) -> dict[str, tuple[_Label, ...]]:
    rows = tuple(
        connection.execute(
            """
            SELECT *
            FROM labels
            WHERE decision_date=?
            ORDER BY symbol, horizon
            """,
            (decision_date,),
        )
    )
    result: dict[str, list[_Label]] = {}
    for row in rows:
        result.setdefault(str(row["symbol"]), []).append(
            _Label(
                horizon=int(row["horizon"]),
                horizon_end_date=str(row["horizon_end_date"]),
                available_at=str(row["available_at"]),
                excess_return_bp=int(row["excess_return_bp"]),
                sector_excess_return_bp=(
                    None
                    if row["sector_excess_return_bp"] is None
                    else int(row["sector_excess_return_bp"])
                ),
                sector_excess_observed=bool(
                    row["sector_excess_observed"]
                ),
                sector_excess_missing_reason=(
                    None
                    if row["sector_excess_missing_reason"] is None
                    else str(row["sector_excess_missing_reason"])
                ),
                downside_observed=bool(row["downside_observed"]),
                mae_loss_bp=int(row["mae_loss_bp"]),
                mfe_gain_bp=int(row["mfe_gain_bp"]),
                realized_volatility_bp=int(
                    row["realized_volatility_bp"]
                ),
                max_drawdown_bp=int(row["max_drawdown_bp"]),
                tail_loss_bp=int(row["tail_loss_bp"]),
                fill_feasible_observed=bool(
                    row["fill_feasible_observed"]
                ),
                source_hash=str(row["source_hash"]),
            )
        )
    return {
        symbol: tuple(labels)
        for symbol, labels in result.items()
        if tuple(label.horizon for label in labels) == SUPPORTED_HORIZONS
    }


def _sectors_for_decision(
    connection: sqlite3.Connection,
    *,
    decision_date: str,
    decision_at: str,
) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT symbol, sector_id, available_at, effective_from
        FROM sector_memberships
        WHERE status='accepted'
          AND available_at <= ?
          AND effective_from <= ?
          AND (effective_to IS NULL OR effective_to >= ?)
        ORDER BY symbol, available_at DESC, effective_from DESC, sector_id
        """,
        (decision_at, decision_date, decision_date),
    )
    result: dict[str, str] = {}
    for row in rows:
        symbol = str(row["symbol"])
        result.setdefault(symbol, str(row["sector_id"]))
    return result


def _teacher_candidates(
    *,
    labels_by_symbol: Mapping[str, tuple[_Label, ...]],
    sectors: Mapping[str, str],
) -> tuple[TeacherCandidateOutcome, ...]:
    rows: list[tuple[str, str, _Label]] = []
    for symbol, labels in labels_by_symbol.items():
        label20 = next(label for label in labels if label.horizon == 20)
        sector = sectors.get(symbol, "UNKNOWN")
        rows.append((symbol, sector, label20))
    eligible_by_sector: dict[str, list[tuple[str, str, _Label]]] = {}
    for row in rows:
        if row[1] != "UNKNOWN":
            eligible_by_sector.setdefault(row[1], []).append(row)
    selected: set[str] = set()
    for sector_rows in eligible_by_sector.values():
        for symbol, _, _ in sorted(
            sector_rows,
            key=lambda item: (
                -item[2].excess_return_bp,
                item[2].mae_loss_bp,
                item[2].max_drawdown_bp,
                item[0],
            ),
        )[:2]:
            selected.add(symbol)
    if len(selected) > 24:
        selected = set(
            sorted(
                selected,
                key=lambda symbol: (
                    -next(
                        label.excess_return_bp
                        for label in labels_by_symbol[symbol]
                        if label.horizon == 20
                    ),
                    symbol,
                ),
            )[:24]
        )
    return tuple(
        TeacherCandidateOutcome(
            symbol=symbol,
            sector_id=sector,
            realized_after_cost_excess_20d_bp=label.excess_return_bp,
            cvar_loss_bp=label.tail_loss_bp,
            max_drawdown_bp=label.max_drawdown_bp,
            horizon_end_date=label.horizon_end_date,
            label_available_at=label.available_at,
            label_source_hash=label.source_hash,
            eligible=symbol in selected,
        )
        for symbol, sector, label in sorted(rows, key=lambda item: item[0])
    )


def _current_values(
    connection: sqlite3.Connection,
    *,
    scope: str,
    entity_key: str,
    decision_at: str,
) -> dict[str, _CurrentValue]:
    decision = _available_datetime(
        decision_at, field_name="current value decision_at"
    ).isoformat()
    result: dict[str, _CurrentValue] = {}
    rows = connection.execute(
        """
        SELECT * FROM current_features
        WHERE scope=? AND entity_key=?
          AND event_at <= ?
          AND available_at <= ?
        ORDER BY
            feature_id,
            event_period DESC,
            available_at DESC,
            revision_id DESC,
            source_value_hash DESC
        """,
        (scope, entity_key, decision, decision),
    )
    for row in rows:
        feature_id = str(row["feature_id"])
        if feature_id in result:
            continue
        result[feature_id] = _CurrentValue(
            value_int=(
                None if row["value_int"] is None else int(row["value_int"])
            ),
            scale=int(row["scale"]),
            event_at=str(row["event_at"]),
            available_at=str(row["available_at"]),
            revision_id=str(row["revision_id"]),
            quality=str(row["quality"]),
            source_value_hash=str(row["source_value_hash"]),
            stale_after_days=int(row["stale_after_days"]),
            formal_training_eligible=bool(row["formal_training_eligible"]),
            missing_mask=bool(row["missing_mask"]),
            quality_blocked_mask=bool(row["quality_blocked_mask"]),
        )
    return result


def _build_feature_snapshot(
    *,
    decision_at: datetime,
    definitions: tuple[_FeatureDefinition, ...],
    feature_by_id: Mapping[str, _FeatureDefinition],
    by_scope: Mapping[str, tuple[_FeatureDefinition, ...]],
    stock_current: Mapping[str, _CurrentValue],
    market_current: Mapping[str, _CurrentValue],
    industry_current: Mapping[str, _CurrentValue],
) -> tuple[tuple[PITFeatureValue, ...], tuple[str, ...]]:
    del feature_by_id
    current_by_scope = {
        "stock": stock_current,
        "market": market_current,
        "industry": industry_current,
    }
    features: list[PITFeatureValue] = []
    missing_families: set[str] = set()
    family_stats: dict[str, dict[str, int]] = {}
    for definition in definitions:
        current = current_by_scope[definition.scope].get(definition.feature_id)
        stale = False
        lag_days = 0
        observed = False
        if current is not None:
            available = _available_datetime(
                current.available_at,
                field_name=f"{definition.feature_id}.available_at",
            )
            lag_days = max(0, (decision_at.date() - available.date()).days)
            stale = lag_days > current.stale_after_days
            observed = (
                current.formal_training_eligible
                and not current.missing_mask
                and not current.quality_blocked_mask
                and not stale
                and current.value_int is not None
                and available <= decision_at
            )
        stats = family_stats.setdefault(
            definition.family_id,
            {
                "total": 0,
                "observed": 0,
                "missing": 0,
                "stale": 0,
                "quality_blocked": 0,
                "max_available_lag_days": 0,
            },
        )
        stats["total"] += 1
        stats["observed"] += int(observed)
        stats["missing"] += int(not observed)
        stats["stale"] += int(stale)
        stats["quality_blocked"] += int(
            current is not None and current.quality_blocked_mask
        )
        stats["max_available_lag_days"] = max(
            stats["max_available_lag_days"], lag_days
        )
        if observed and current is not None:
            quality: FeatureQuality = (
                "estimated"
                if "estimated" in current.quality.casefold()
                else "degraded"
                if "degraded" in current.quality.casefold()
                else "observed"
            )
            features.append(
                PITFeatureValue(
                    feature_id=definition.feature_id,
                    family_id=definition.family_id,
                    source_id=definition.source_id,
                    value_int=current.value_int,
                    scale=current.scale,
                    event_at=current.event_at,
                    available_at=current.available_at,
                    revision_id=current.revision_id,
                    quality=quality,
                    content_hash=current.source_value_hash,
                    observed=True,
                )
            )
        else:
            missing_families.add(definition.family_id)
            features.append(
                PITFeatureValue(
                    feature_id=definition.feature_id,
                    family_id=definition.family_id,
                    source_id=definition.source_id,
                    value_int=None,
                    scale=definition.scale,
                    event_at=(
                        decision_at.date() - timedelta(days=1)
                    ).isoformat(),
                    available_at=decision_at.isoformat(),
                    revision_id=(
                        "missing:stale"
                        if stale
                        else "missing:not_observed_as_of_decision"
                    ),
                    quality="missing",
                    content_hash=_sha256_json(
                        {
                            "feature_id": definition.feature_id,
                            "decision_at": decision_at.isoformat(),
                            "reason": "stale" if stale else "not_observed",
                        }
                    ),
                    observed=False,
                )
            )
    for family_id, stats in sorted(family_stats.items()):
        total = stats["total"]
        coverage_bp = (
            0 if total == 0 else stats["observed"] * 10_000 // total
        )
        for metric_name, value_int, scale in (
            ("coverage_bp", coverage_bp, 1),
            ("missing_count", stats["missing"], 1),
            ("stale_count", stats["stale"], 1),
            ("quality_blocked_count", stats["quality_blocked"], 1),
            (
                "max_available_lag_days",
                stats["max_available_lag_days"],
                1,
            ),
        ):
            feature_id = f"data_quality.{family_id}.{metric_name}"
            features.append(
                PITFeatureValue(
                    feature_id=feature_id,
                    family_id="data_quality",
                    source_id="derived:feature_quality",
                    value_int=value_int,
                    scale=scale,
                    event_at=decision_at.isoformat(),
                    available_at=decision_at.isoformat(),
                    revision_id="derived:data-quality-v1",
                    quality="observed",
                    content_hash=_sha256_json(
                        {
                            "feature_id": feature_id,
                            "decision_at": decision_at.isoformat(),
                            "value_int": value_int,
                        }
                    ),
                    observed=True,
                )
            )
    return (
        tuple(sorted(features, key=lambda feature: feature.feature_id)),
        tuple(sorted(missing_families)),
    )


def _feature_pack_payloads(
    definitions: tuple[_FeatureDefinition, ...],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for definition in definitions:
        grouped.setdefault(definition.family_id, []).append(definition.feature_id)
    families = tuple(sorted(grouped))
    data_quality_features = [
        f"data_quality.{family}.{metric}"
        for family in families
        for metric in (
            "coverage_bp",
            "missing_count",
            "stale_count",
            "quality_blocked_count",
            "max_available_lag_days",
        )
    ]
    grouped["data_quality"] = data_quality_features
    return [
        {
            "pack_id": family,
            "feature_ids": sorted(feature_ids),
        }
        for family, feature_ids in sorted(grouped.items())
    ]


def _source_manifest_hashes(
    *,
    definitions: tuple[_FeatureDefinition, ...],
    raw_manifest_hash: str,
    sector_manifest_hash: str,
    corporate_action_manifest_hash: str = _ZERO_SHA256,
) -> tuple[tuple[str, str], ...]:
    source_ids = {
        definition.source_id for definition in definitions
    } | {"derived:feature_quality"}
    if sector_manifest_hash != "sha256:" + ("0" * 64):
        source_ids.add("sidecar:pit_sector_membership")
    manifest_hashes = [
        (
            source_id,
            _sha256_json(
                {
                    "source_id": source_id,
                    "raw_manifest_hash": raw_manifest_hash,
                    "sector_manifest_hash": sector_manifest_hash,
                }
            ),
        )
        for source_id in sorted(source_ids)
    ]
    if corporate_action_manifest_hash != _ZERO_SHA256:
        manifest_hashes.append(
            (
                "sidecar:official_corporate_action_ledger",
                corporate_action_manifest_hash,
            )
        )
    return tuple(sorted(manifest_hashes))


class _TrainingShardWriter:
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._raw = self.path.open("wb")
        self._gzip = gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=compression_level,
            fileobj=self._raw,
            mtime=0,
        )
        self._content_digest = hashlib.sha256()
        self._closed = False
        self.sample_count = 0
        self.min_decision_date: str | None = None
        self.max_decision_date: str | None = None
        self._write_record(header)

    def write_sample(self, sample: AllocationTrainingSample) -> None:
        self._write_record(
            {
                "record_type": "sample",
                "sample": asdict(sample),
            }
        )
        decision_date = sample.row.decision_at[:10]
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

    def _write_record(self, payload: Mapping[str, Any]) -> None:
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

    def manifest_payload(self, *, staging: Path) -> dict[str, Any]:
        self.close()
        return {
            "year": self.year,
            "path": self.path.relative_to(staging).as_posix(),
            "format": "gzip_jsonl",
            "schema_version": TRAINING_JSONL_SCHEMA_VERSION,
            "compressed_sha256": _file_sha256(self.path),
            "content_sha256": f"sha256:{self._content_digest.hexdigest()}",
            "compressed_bytes": self.path.stat().st_size,
            "sample_count": self.sample_count,
            "min_decision_date": self.min_decision_date,
            "max_decision_date": self.max_decision_date,
            "direct_training_input": True,
        }


class _TrainingShardWriterRegistry:
    def __init__(self, *, staging: Path, compression_level: int) -> None:
        self._staging = staging
        self._compression_level = compression_level
        self._writers: dict[int, _TrainingShardWriter] = {}

    def get(
        self, *, year: int, header: Mapping[str, Any]
    ) -> _TrainingShardWriter:
        writer = self._writers.get(year)
        if writer is None:
            writer = _TrainingShardWriter(
                path=self._staging / f"year={year:04d}.jsonl.gz",
                year=year,
                header=header,
                compression_level=self._compression_level,
            )
            self._writers[year] = writer
        return writer

    def close_all(self) -> None:
        for writer in self._writers.values():
            writer.close()

    def manifest_payloads(self, *, staging: Path) -> list[dict[str, Any]]:
        return [
            writer.manifest_payload(staging=staging)
            for _, writer in sorted(self._writers.items())
        ]


def _validate_raw_dataset_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != "ml-pit-year-shard-dataset.v1":
        raise ValueError("unsupported raw dataset manifest schema")
    if manifest.get("stage") != "raw_pit_observations":
        raise ValueError("input manifest is not a raw PIT observation dataset")
    if manifest.get("format") != "gzip_jsonl":
        raise ValueError("raw dataset must use gzip_jsonl")
    expected = str(manifest.get("manifest_hash", ""))
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    if expected != _sha256_json(payload):
        raise ValueError("raw dataset manifest hash mismatch")
    safety = _as_mapping(manifest.get("safety"), field_name="safety")
    if not _required_json_bool(
        safety.get("formal_dataset"), field_name="safety.formal_dataset"
    ):
        raise ValueError("raw dataset is not formal")
    if _required_json_bool(
        safety.get("unreviewed_included"),
        field_name="safety.unreviewed_included",
    ):
        raise ValueError("raw dataset includes unreviewed features")
    if _required_json_bool(
        safety.get("excluded_leakage_included"),
        field_name="safety.excluded_leakage_included",
    ):
        raise ValueError("raw dataset includes leakage features")
    if not _required_json_bool(
        safety.get("research_shadow_isolated"),
        field_name="safety.research_shadow_isolated",
    ):
        raise ValueError("raw dataset does not isolate research shadow")
    if _required_json_bool(
        safety.get("raw_float_persistence_allowed"),
        field_name="safety.raw_float_persistence_allowed",
    ):
        raise ValueError("raw dataset allows float persistence")
    _mapping_sequence(manifest.get("features"), field_name="features")


def _pit_sector_id(
    *,
    membership_rows: Sequence[sqlite3.Row],
    decision_date: str,
) -> str | None:
    decision = _parse_date(decision_date, field_name="decision_date")
    decision_at = datetime.combine(
        decision,
        _DECISION_TIME,
        tzinfo=_TAIPEI,
    )
    eligible: list[tuple[datetime, date, str]] = []
    for row in membership_rows:
        available_at = _available_datetime(
            str(row["available_at"]),
            field_name="sector_membership.available_at",
        )
        effective_from = _parse_date(
            str(row["effective_from"]),
            field_name="sector_membership.effective_from",
        )
        raw_effective_to = row["effective_to"]
        effective_to = (
            None
            if raw_effective_to in (None, "")
            else _parse_date(
                str(raw_effective_to),
                field_name="sector_membership.effective_to",
            )
        )
        if (
            available_at <= decision_at
            and effective_from <= decision
            and (effective_to is None or effective_to >= decision)
        ):
            eligible.append(
                (
                    available_at,
                    effective_from,
                    str(row["sector_id"]),
                )
            )
    if not eligible:
        return None
    return max(eligible, key=lambda item: (item[0], item[1], item[2]))[2]


def _return_bp(
    *,
    entry_int: int,
    entry_scale: int,
    exit_int: int,
    exit_scale: int,
) -> int:
    entry = Decimal(entry_int) / Decimal(entry_scale)
    exit_value = Decimal(exit_int) / Decimal(exit_scale)
    if entry <= 0:
        raise ValueError("entry price must be positive")
    return int(
        (((exit_value / entry) - Decimal(1)) * Decimal(10_000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )


def _mae_loss_bp(
    entry: sqlite3.Row,
    path_rows: Sequence[sqlite3.Row],
) -> int:
    entry_price = Decimal(int(entry["open_int"])) / Decimal(
        int(entry["open_scale"])
    )
    path_values: list[Decimal] = []
    for row in path_rows:
        if _positive_price(row["low_int"], row["low_scale"]):
            path_values.append(
                Decimal(int(row["low_int"])) / Decimal(int(row["low_scale"]))
            )
        elif _positive_price(row["close_int"], row["close_scale"]):
            path_values.append(
                Decimal(int(row["close_int"]))
                / Decimal(int(row["close_scale"]))
            )
    if not path_values:
        return 10_000
    minimum_return_bp = int(
        (((min(path_values) / entry_price) - Decimal(1)) * Decimal(10_000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )
    return max(0, -minimum_return_bp)


def _mfe_gain_bp(
    entry: sqlite3.Row,
    path_rows: Sequence[sqlite3.Row],
) -> int:
    entry_price = Decimal(int(entry["open_int"])) / Decimal(
        int(entry["open_scale"])
    )
    path_values: list[Decimal] = []
    for row in path_rows:
        if _positive_price(row["high_int"], row["high_scale"]):
            path_values.append(
                Decimal(int(row["high_int"]))
                / Decimal(int(row["high_scale"]))
            )
        elif _positive_price(row["close_int"], row["close_scale"]):
            path_values.append(
                Decimal(int(row["close_int"]))
                / Decimal(int(row["close_scale"]))
            )
    if not path_values:
        return 0
    maximum_return_bp = int(
        (
            ((max(path_values) / entry_price) - Decimal(1))
            * Decimal(10_000)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    )
    return min(10_000, max(0, maximum_return_bp))


def _close_returns_bp(path_rows: Sequence[sqlite3.Row]) -> tuple[int, ...]:
    closes = [
        Decimal(int(row["close_int"])) / Decimal(int(row["close_scale"]))
        for row in path_rows
        if _positive_price(row["close_int"], row["close_scale"])
    ]
    returns: list[int] = []
    for previous, current in zip(closes, closes[1:]):
        if previous <= 0:
            continue
        returns.append(
            int(
                (
                    ((current / previous) - Decimal(1))
                    * Decimal(10_000)
                ).quantize(
                    Decimal("1"),
                    rounding=ROUND_HALF_EVEN,
                )
            )
        )
    return tuple(returns)


def _realized_volatility_bp(
    path_rows: Sequence[sqlite3.Row],
) -> int:
    returns = _close_returns_bp(path_rows)
    if len(returns) < 2:
        return 0
    count = Decimal(len(returns))
    mean = sum((Decimal(value) for value in returns), Decimal(0)) / count
    variance = (
        sum(
            (
                (Decimal(value) - mean) * (Decimal(value) - mean)
                for value in returns
            ),
            Decimal(0),
        )
        / count
    )
    volatility = variance.sqrt()
    return min(
        10_000,
        max(
            0,
            int(
                volatility.quantize(
                    Decimal("1"),
                    rounding=ROUND_HALF_EVEN,
                )
            ),
        ),
    )


def _tail_loss_bp(path_rows: Sequence[sqlite3.Row]) -> int:
    returns = tuple(sorted(_close_returns_bp(path_rows)))
    if not returns:
        return 10_000
    tail_count = max(1, (len(returns) + 4) // 5)
    tail_mean = (
        sum(
            (Decimal(value) for value in returns[:tail_count]),
            Decimal(0),
        )
        / Decimal(tail_count)
    )
    loss = int(
        (-tail_mean).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )
    return min(10_000, max(0, loss))


def _t1_fill_feasible(entry: sqlite3.Row) -> bool:
    required = (
        ("open_int", "open_scale"),
        ("high_int", "high_scale"),
        ("low_int", "low_scale"),
        ("close_int", "close_scale"),
    )
    if any(
        not _positive_price(entry[value_field], entry[scale_field])
        for value_field, scale_field in required
    ):
        return False
    open_value = Decimal(int(entry["open_int"])) / Decimal(
        int(entry["open_scale"])
    )
    high_value = Decimal(int(entry["high_int"])) / Decimal(
        int(entry["high_scale"])
    )
    low_value = Decimal(int(entry["low_int"])) / Decimal(
        int(entry["low_scale"])
    )
    # 缺少逐筆成交與官方漲跌停狀態時，單一價位盤 fail closed。
    return high_value > low_value and low_value <= open_value <= high_value


def _max_drawdown_bp(path_rows: Sequence[sqlite3.Row]) -> int:
    closes = [
        Decimal(int(row["close_int"])) / Decimal(int(row["close_scale"]))
        for row in path_rows
        if _positive_price(row["close_int"], row["close_scale"])
    ]
    if not closes:
        return 10_000
    peak = closes[0]
    worst = 0
    for value in closes:
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = int(
            (((peak - value) / peak) * Decimal(10_000)).quantize(
                Decimal("1"), rounding=ROUND_HALF_EVEN
            )
        )
        worst = max(worst, drawdown)
    return min(10_000, worst)


def _positive_price(value: object, scale: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and value > 0
        and not isinstance(scale, bool)
        and isinstance(scale, int)
        and scale > 0
    )


def _normalized_years(values: Iterable[int]) -> tuple[int, ...]:
    result: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("years must contain integers")
        if not 1900 <= value <= 9999:
            raise ValueError("years must be within 1900..9999")
        result.append(value)
    return tuple(sorted(set(result)))


def _mapping_sequence(
    value: Any,
    *,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    return tuple(
        _as_mapping(item, field_name=f"{field_name}[]") for item in value
    )


def _as_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    return value


def _required_json_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a JSON boolean")
    return value


def _required_positive_int(value: object, *, field_name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise TypeError(f"{field_name} must be a positive integer")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _parse_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _available_datetime(value: str, *, field_name: str) -> datetime:
    if len(value) == 10:
        parsed_date = _parse_date(value, field_name=field_name)
        return datetime.combine(
            parsed_date,
            time(23, 59, 59, 999_999),
            tzinfo=_TAIPEI,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone offset")
    return parsed.astimezone(_TAIPEI)


def _decision_datetime(value: str) -> datetime:
    parsed = _available_datetime(value, field_name="decision_at")
    if parsed.timetz().replace(tzinfo=None) != _DECISION_TIME:
        raise ValueError("decision_at must be 08:30 Asia/Taipei")
    return parsed


def _require_sha256(value: str, *, field_name: str) -> None:
    digest = value[7:] if value.startswith("sha256:") else ""
    if (
        len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(payload: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be object: {path}")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        _write_json(temporary, payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_remove_tree(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise RuntimeError("refusing to remove path outside assembly output root")
    shutil.rmtree(resolved)
