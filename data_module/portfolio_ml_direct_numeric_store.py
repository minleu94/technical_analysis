"""Raw PIT 年度 shards 直接建立 numeric OOC store。

本模組刻意不發布 ``portfolio-ml-training-shards`` JSONL，也不建立跨年度
observation SQLite。每次只開啟一個年度工作資料庫，載入當年 observation 與
下一年度（供最長 60 日標籤）的價格資料，然後直接串流寫出固定 dtype binary
artifacts。年度完成後保存 compact causal feature carry、原子封存並刪除工作庫。
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time as time_module
from typing import Any, Callable, Mapping, Sequence, cast
from zoneinfo import ZoneInfo

import numpy as np

from data_module import portfolio_ml_dataset_assembler as legacy
from data_module import portfolio_ml_out_of_core_store as store_module
from data_module.ml_storage_capacity import (
    heavy_chain_capacity_budget,
    MLStorageCapacityBudget,
    StorageCapacityError,
    directory_size_bytes as capacity_directory_size_bytes,
    preflight_capacity,
)
from data_module.ml_pit_shared_block_resolver import resolve_pit_shard_record
from data_module.ml_direct_shared_block_resolver import (
    DIRECT_NUMERIC_ARTIFACT_IDS,
    DIRECT_NUMERIC_ARTIFACT_KEY_VERSION,
    DIRECT_NUMERIC_ARTIFACT_REFERENCE_SCHEMA_VERSION,
    DIRECT_NUMERIC_MATURITY_POLICY_VERSION,
    DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION,
    direct_numeric_year_descriptor_key,
    direct_numeric_artifact_key,
    find_direct_year_descriptor,
    publish_direct_numeric_artifact,
    publish_direct_year_descriptor,
    resolve_direct_year_descriptor,
    resolve_direct_year_artifact_paths,
)
from ml_module.allocation_training_service import AllocationTrainingSample


DIRECT_SCHEMA_VERSION = "portfolio-ml-direct-numeric.v4"
DIRECT_CHECKPOINT_SCHEMA_VERSION = "portfolio-ml-direct-checkpoint.v2"
DIRECT_HEARTBEAT_SCHEMA_VERSION = "portfolio-ml-direct-heartbeat.v1"
DIRECT_DISCOVERY_CACHE_SCHEMA_VERSION = (
    "portfolio-ml-direct-discovery-cache.v1"
)
DIRECT_CARRY_SCHEMA_VERSION = "portfolio-ml-direct-carry.v2"
DIRECT_REPLAY_VOLUME_CARRY_SCOPE = "replay_volume"
DIRECT_REPLAY_VOLUME_POLICY_VERSION = (
    "direct-replay-volume20-cross-year-carry.v1"
)
DIRECT_LABEL_CONTRACT_VERSION = "direct-numeric-label-contract.v1"
_TAIPEI = ZoneInfo("Asia/Taipei")
_DECISION_TIME = time(hour=8, minute=30)
_SHA256_PREFIX = "sha256:"
_REPLAY_SOURCE_SCHEMA_VERSION = "portfolio-ml-replay-source.v1"
_PRICE_OPEN_FEATURE_ID = "daily_prices.開盤價"
_PRICE_CLOSE_FEATURE_ID = "daily_prices.收盤價"
_PRICE_VOLUME_FEATURE_ID = "daily_prices.成交股數"
_RULE_MA20_FEATURE_ID = "technical_indicators.MA20"
_OFFICIAL_TRADE_RESTRICTION_HALT = "trading_halt"
_OFFICIAL_TRADE_RESTRICTION_RESUME = "trading_resume"
_TRADE_RESTRICTION_STATUS_UNKNOWN = (
    "unknown_no_official_restriction_timeline"
)
# Windows Defender/indexers may briefly hold a heartbeat, checkpoint, or
# annual staging directory.  Keep the retry bounded, but long enough to cover
# a normal scan window; custody validation still fails closed after exhaustion.
_ATOMIC_REPLACE_RETRY_COUNT = 120
_ATOMIC_REPLACE_RETRY_DELAY_SECONDS = 0.5
_DISCOVERY_PROGRESS_INTERVAL = 100_000
_DISCOVERY_PROGRESS_CHECK_INTERVAL = 4_096
_DISCOVERY_PROGRESS_MAX_SILENCE_NS = 30 * 1_000_000_000
_VOLUME_WINDOW_SIZE = 20
_CARRY_METADATA_KEY = "__carry_schema_version__"


@dataclass(frozen=True)
class PortfolioMLDirectNumericRequest:
    raw_manifest_path: Path
    output_root: Path
    training_as_of: str
    benchmark_entity_id: str
    sector_membership_path: Path | None = None
    corporate_action_manifest_path: Path | None = None
    formal_portfolio_ledger_path: Path | None = None
    formal_rule_champion_history_path: Path | None = None
    minimum_train_dates: int = 252
    test_date_count: int = 63
    purge_trading_days: int = 60
    embargo_trading_days: int = 5
    batch_size: int = 8_192
    workers: int = 1
    memory_budget_mb: int = 4_096
    temporary_storage_budget_bytes: int | None = None
    resume: bool = True
    # Capacity policy additions are optional so callers using the previous
    # direct request contract continue to work unchanged.
    persistent_storage_budget_bytes: int | None = None
    persistent_new_bytes_budget: int | None = None
    safety_reserve_bytes: int | None = None
    shared_block_store_root: Path | None = None
    shared_numeric_store_root: Path | None = None

    def __post_init__(self) -> None:
        legacy.PortfolioMLDatasetAssemblyRequest(
            dataset_manifest_path=self.raw_manifest_path,
            output_root=self.output_root,
            training_as_of=self.training_as_of,
            benchmark_entity_id=self.benchmark_entity_id,
            sector_membership_path=self.sector_membership_path,
            corporate_action_manifest_path=(
                self.corporate_action_manifest_path
            ),
            formal_portfolio_ledger_path=self.formal_portfolio_ledger_path,
            formal_rule_champion_history_path=(
                self.formal_rule_champion_history_path
            ),
            minimum_train_dates=self.minimum_train_dates,
            test_date_count=self.test_date_count,
            purge_trading_days=self.purge_trading_days,
            embargo_trading_days=self.embargo_trading_days,
            batch_size=self.batch_size,
            shared_block_store_root=self.shared_block_store_root,
        )
        for field_name in ("workers", "memory_budget_mb"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.workers > 32:
            raise ValueError("workers must not exceed 32")
        if self.memory_budget_mb < 256:
            raise ValueError("memory_budget_mb must be at least 256")
        if self.temporary_storage_budget_bytes is not None:
            value = self.temporary_storage_budget_bytes
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "temporary_storage_budget_bytes must be integer or None"
                )
            if value <= 0:
                raise ValueError(
                    "temporary_storage_budget_bytes must be positive"
                )
        aliases = (
            self.persistent_storage_budget_bytes,
            self.persistent_new_bytes_budget,
        )
        if (
            aliases[0] is not None
            and aliases[1] is not None
            and aliases[0] != aliases[1]
        ):
            raise ValueError(
                "persistent_storage_budget_bytes and "
                "persistent_new_bytes_budget must match"
            )
        for field_name, value in zip(
            (
                "persistent_storage_budget_bytes",
                "persistent_new_bytes_budget",
            ),
            aliases,
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer or None")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.safety_reserve_bytes is not None:
            value = self.safety_reserve_bytes
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("safety_reserve_bytes must be integer or None")
            if value <= 0:
                raise ValueError("safety_reserve_bytes must be positive")
        if not isinstance(self.resume, bool):
            raise TypeError("resume must be bool")


@dataclass(frozen=True)
class PortfolioMLDirectNumericPublication:
    run_id: str
    run_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    manifest_file_hash: str
    row_count: int
    feature_count: int
    fold_count: int
    full_market_ready: bool
    readiness_failed_checks: tuple[str, ...]


@dataclass
class _MemoryBudgetGuard:
    budget_bytes: int
    peak_rss_bytes: int = 0

    @classmethod
    def create(cls, memory_budget_mb: int) -> _MemoryBudgetGuard:
        guard = cls(budget_bytes=memory_budget_mb * 1024 * 1024)
        guard.observe(stage="request_start")
        return guard

    def observe(self, *, stage: str) -> int:
        rss_bytes = _current_rss_bytes()
        if rss_bytes is None:
            raise RuntimeError(
                "process RSS cannot be measured; memory budget fails closed"
            )
        self.peak_rss_bytes = max(self.peak_rss_bytes, rss_bytes)
        if rss_bytes > self.budget_bytes:
            raise MemoryError(
                "memory budget exceeded at "
                f"{stage}: {rss_bytes} > {self.budget_bytes}"
            )
        return rss_bytes


@dataclass(frozen=True)
class _Discovery:
    definitions: tuple[Any, ...]
    feature_packs: list[dict[str, Any]]
    feature_ids: tuple[str, ...]
    feature_scales: tuple[int, ...]
    calendar: tuple[str, ...]
    eligible_dates: tuple[str, ...]
    fold_windows: tuple[Any, ...]
    shard_by_year: Mapping[int, Mapping[str, Any]]
    source_content_hash: str


def _official_trade_restriction_status(
    events: Sequence[Any],
    *,
    decision_at: datetime,
    timeline_present: bool,
) -> str:
    """Return an as-of execution status without using future visibility.

    A halt/resume event whose effective time has passed but whose official
    availability is still in the future makes the state unknowable at the
    decision timestamp.  That case is deliberately not treated as tradable.
    """

    if not timeline_present:
        return _TRADE_RESTRICTION_STATUS_UNKNOWN
    visible: list[Any] = []
    for event in events:
        if event.revision_availability_ambiguous:
            if event.effective_at <= decision_at:
                return "unknown_official_restriction_revision"
            continue
        if event.effective_at > decision_at:
            continue
        if event.available_at > decision_at:
            return "unknown_official_restriction_availability"
        visible.append(event)
    if not visible:
        return "officially_tradable"
    latest = max(
        visible,
        key=lambda event: (
            event.effective_at,
            event.available_at,
            event.event_id,
        ),
    )
    if latest.event_type == _OFFICIAL_TRADE_RESTRICTION_HALT:
        return "officially_blocked"
    if latest.event_type == _OFFICIAL_TRADE_RESTRICTION_RESUME:
        return "officially_tradable"
    return "unknown_official_restriction_event"


class PortfolioMLDirectNumericStoreBuilder:
    """逐年 bounded workspace、manifest-last 的 direct numeric builder。"""

    def build(
        self,
        request: PortfolioMLDirectNumericRequest,
    ) -> PortfolioMLDirectNumericPublication:
        # 先解析中央 heavy policy，再建立 run identity；避免 capacity
        # 預設變更後沿用同一個 run id 而靜默混用不同安全邊界。
        capacity_budget = _capacity_budget_for_request(request)
        temporary_budget_bytes = capacity_budget.temporary_peak_bytes_budget
        if temporary_budget_bytes is None:
            raise RuntimeError(
                "resolved Direct capacity budget lacks temporary limit"
            )
        memory_guard = _MemoryBudgetGuard.create(request.memory_budget_mb)
        raw_path = request.raw_manifest_path.resolve()
        raw_manifest = legacy._read_json(raw_path)
        legacy._validate_raw_dataset_manifest(raw_manifest)
        shared_contract = legacy._validate_shared_block_dataset_manifest(
            raw_manifest
        )
        if shared_contract is not None and request.shared_block_store_root is None:
            raise ValueError(
                "shared_block_store_root is required for shared PIT dataset"
            )
        cutoff = legacy._available_datetime(
            request.training_as_of,
            field_name="training_as_of",
        )
        raw_decision = legacy._decision_datetime(
            str(raw_manifest["decision_at"])
        )
        if cutoff > raw_decision:
            raise ValueError(
                "training_as_of cannot exceed raw publication decision_at"
            )
        raw_file_hash = _file_sha256(raw_path)
        sector_file_hash = _optional_file_hash(
            request.sector_membership_path
        )
        corporate_file_hash = _optional_file_hash(
            request.corporate_action_manifest_path
        )
        direct_identity = {
            "schema_version": DIRECT_SCHEMA_VERSION,
            "store_schema_version": store_module.STORE_SCHEMA_VERSION,
            "raw_manifest_hash": raw_manifest["manifest_hash"],
            "raw_manifest_file_hash": raw_file_hash,
            "training_as_of": cutoff.isoformat(),
            "benchmark_entity_id": request.benchmark_entity_id,
            "sector_membership_file_hash": sector_file_hash,
            "corporate_action_manifest_file_hash": corporate_file_hash,
            "minimum_train_dates": request.minimum_train_dates,
            "test_date_count": request.test_date_count,
            "purge_trading_days": request.purge_trading_days,
            "embargo_trading_days": request.embargo_trading_days,
            "capacity_budget": capacity_budget.as_dict(),
            # carry schema/policy 屬於 run identity；舊年度若沒有跨年
            # volume seed，不得用相同 request 靜默重用舊產物。
            "volume_history_carry_schema_version": (
                DIRECT_CARRY_SCHEMA_VERSION
            ),
            "volume_history_carry_policy_version": (
                DIRECT_REPLAY_VOLUME_POLICY_VERSION
            ),
        }
        if shared_contract is not None:
            direct_identity["shared_block_store_mode"] = "content_addressed"
        if request.shared_numeric_store_root is not None:
            direct_identity["shared_numeric_store_mode"] = "content_addressed"
            direct_identity["shared_numeric_artifact_key_version"] = (
                DIRECT_NUMERIC_ARTIFACT_KEY_VERSION
            )
            direct_identity["shared_numeric_reference_schema_version"] = (
                DIRECT_NUMERIC_ARTIFACT_REFERENCE_SCHEMA_VERSION
            )
        if request.formal_portfolio_ledger_path is not None:
            direct_identity["formal_portfolio_ledger_file_hash"] = (
                _file_sha256(request.formal_portfolio_ledger_path.resolve())
            )
            direct_identity["formal_portfolio_ledger_path"] = str(
                request.formal_portfolio_ledger_path.resolve()
            )
        if request.formal_rule_champion_history_path is not None:
            direct_identity["formal_rule_champion_history_file_hash"] = (
                _file_sha256(
                    request.formal_rule_champion_history_path.resolve()
                )
            )
            direct_identity["formal_rule_champion_history_path"] = str(
                request.formal_rule_champion_history_path.resolve()
            )
        run_id = "direct-ooc-" + _sha256_json(direct_identity)[7:31]
        output_root = request.output_root.resolve()
        runs_root = output_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        run_directory = runs_root / run_id
        run_directory.mkdir(parents=True, exist_ok=True)
        manifest_path = run_directory / "manifest.json"
        latest_path = output_root / "latest_manifest.json"
        heartbeat_path = run_directory / "heartbeat.json"
        if not manifest_path.is_file() and not request.resume and any(
            run_directory.iterdir()
        ):
            raise FileExistsError(
                "incomplete direct numeric run exists and resume=false"
            )
        _write_heartbeat(
            path=heartbeat_path,
            run_id=run_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
            status="running",
            stage="run_initialized",
            completed_years=(),
        )

        def report_discovery(stage: str) -> None:
            _write_heartbeat(
                path=heartbeat_path,
                run_id=run_id,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                status="running",
                stage=stage,
                completed_years=(),
            )

        discovery_cache_path = run_directory / "discovery_cache.json"
        discovery = _load_discovery_cache(
            path=discovery_cache_path,
            raw_manifest_path=raw_path,
            raw_manifest=raw_manifest,
            raw_manifest_file_hash=raw_file_hash,
            cutoff=cutoff,
            benchmark_entity_id=request.benchmark_entity_id,
            minimum_train_dates=request.minimum_train_dates,
            test_date_count=request.test_date_count,
            purge_trading_days=request.purge_trading_days,
            embargo_trading_days=request.embargo_trading_days,
            shared_block_store_root=request.shared_block_store_root,
            shared_contract=shared_contract,
        )
        if discovery is None:
            discovery = _discover(
                raw_manifest_path=raw_path,
                raw_manifest=raw_manifest,
                cutoff=cutoff,
                benchmark_entity_id=request.benchmark_entity_id,
                minimum_train_dates=request.minimum_train_dates,
                test_date_count=request.test_date_count,
                purge_trading_days=request.purge_trading_days,
                embargo_trading_days=request.embargo_trading_days,
                shared_block_store_root=request.shared_block_store_root,
                shared_contract=shared_contract,
                progress_callback=report_discovery,
            )
            _write_discovery_cache(
                path=discovery_cache_path,
                raw_manifest=raw_manifest,
                raw_manifest_file_hash=raw_file_hash,
                cutoff=cutoff,
                benchmark_entity_id=request.benchmark_entity_id,
                minimum_train_dates=request.minimum_train_dates,
                test_date_count=request.test_date_count,
                purge_trading_days=request.purge_trading_days,
                embargo_trading_days=request.embargo_trading_days,
                discovery=discovery,
            )
        else:
            report_discovery("discovery_cache_reused")
        memory_guard.observe(stage="raw_discovery_complete")
        _write_heartbeat(
            path=heartbeat_path,
            run_id=run_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
            status="running",
            stage="discovery_complete",
            completed_years=(),
        )
        corporate_custody = legacy._load_corporate_action_custody(
            request.corporate_action_manifest_path,
            training_as_of=cutoff,
        )
        sector_manifest_hash, sector_count = _sector_custody(
            request.sector_membership_path,
            cutoff=cutoff,
        )
        feature_registry_payload = {
            "features": [
                asdict(definition)
                for definition in discovery.definitions
            ],
            "feature_packs": discovery.feature_packs,
        }
        feature_registry_hash = _sha256_json(feature_registry_payload)
        source_manifest_hashes = legacy._source_manifest_hashes(
            definitions=discovery.definitions,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
            sector_manifest_hash=sector_manifest_hash,
            corporate_action_manifest_hash=corporate_custody.manifest_hash,
        )
        portfolio_replay = legacy._build_portfolio_state_replay(
            calendar=discovery.calendar,
            decision_dates=discovery.eligible_dates,
            formal_portfolio_ledger_path=request.formal_portfolio_ledger_path,
        )
        formal_rule_champion_custody = (
            legacy._load_formal_rule_champion_history(
                request.formal_rule_champion_history_path,
                decision_dates=discovery.eligible_dates,
                training_as_of=cutoff.isoformat(),
            )
        )
        dataset_identity_hash = _sha256_json(
            {
                "direct_identity": direct_identity,
                "source_content_hash": discovery.source_content_hash,
                "feature_registry_hash": feature_registry_hash,
                "source_manifest_hashes": source_manifest_hashes,
                "folds": [
                    asdict(window)
                    for window in discovery.fold_windows
                ],
                "corporate_action_custody": (
                    corporate_custody.custody_payload()
                ),
                "portfolio_state_policy": (
                    portfolio_replay.custody_payload()
                ),
                **(
                    {}
                    if formal_rule_champion_custody is None
                    else {
                        "formal_rule_champion_history": (
                            formal_rule_champion_custody.custody_payload()
                        )
                    }
                ),
            }
        )
        store_identity = {
            "schema_version": store_module.STORE_SCHEMA_VERSION,
            "direct_builder_schema_version": DIRECT_SCHEMA_VERSION,
            "direct_identity": direct_identity,
            "dataset_identity_hash": dataset_identity_hash,
            "feature_registry_hash": feature_registry_hash,
            "feature_ids": list(discovery.feature_ids),
            "feature_scales": list(discovery.feature_scales),
            "horizons": list(legacy.SUPPORTED_HORIZONS),
            "folds": [
                asdict(window) for window in discovery.fold_windows
            ],
            "lane": "formal",
        }
        if manifest_path.is_file():
            existing_manifest = _read_json(manifest_path)
            _validate_completed_direct_store(
                manifest=existing_manifest,
                run_directory=run_directory,
                expected_identity=store_identity,
                shared_numeric_store_root=request.shared_numeric_store_root,
            )
            store_module._write_latest_pointer(
                latest_manifest_path=latest_path,
                run_id=run_id,
                manifest=existing_manifest,
            )
            _write_heartbeat(
                path=heartbeat_path,
                run_id=run_id,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                status="complete",
                stage="completed_manifest_reused",
                completed_years=tuple(
                    int(item["year"])
                    for item in existing_manifest.get("years", ())
                    if isinstance(item, Mapping) and "year" in item
                ),
            )
            return _publication(
                run_id=run_id,
                run_directory=run_directory,
                manifest_path=manifest_path,
                latest_path=latest_path,
                manifest=existing_manifest,
            )
        temporary_preflight = _preflight_temporary_budget(
            shards=tuple(discovery.shard_by_year.values()),
            feature_count=len(discovery.feature_ids),
            budget_bytes=temporary_budget_bytes,
        )
        capacity_preflight = preflight_capacity(
            probe_path=output_root,
            budget=capacity_budget,
            stage="direct_before_checkpoint",
            persistent_roots=(run_directory,),
            persistent_new_bytes_estimate=(
                _estimate_persistent_new_bytes(
                    shards=tuple(discovery.shard_by_year.values()),
                    feature_count=len(discovery.feature_ids),
                    horizon_count=len(legacy.SUPPORTED_HORIZONS),
                )
            ),
            temporary_peak_bytes_observed=int(
                temporary_preflight["estimated_peak_bytes"]
            ),
        )
        checkpoint_path = run_directory / "checkpoint.json"
        checkpoint = _load_checkpoint(
            path=checkpoint_path,
            run_id=run_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
        )
        completed = {
            int(item["year"]): dict(item)
            for item in _mapping_sequence(
                checkpoint.get("completed_years", []),
                field_name="completed_years",
            )
        }
        carry: Any = _empty_carry()
        peak_temporary_bytes = int(
            checkpoint.get("peak_temporary_bytes", 0)
        )
        last_capacity_preflight: dict[str, Any] = (
            capacity_preflight.as_dict()
        )

        def capacity_checkpoint(
            stage: str,
            temporary_roots: Sequence[Path] = (),
        ) -> dict[str, Any]:
            """在每個階段與年度 checkpoint 重新量測容量。

            這個 callback 只讀取 output filesystem。若新資料或暫存峰值
            超過政策，``preflight_capacity`` 會拋出例外，年度 builder
            會清掉未封存 workspace，而 outer checkpoint 仍保留可續跑的
            已完成年度。
            """

            nonlocal last_capacity_preflight, peak_temporary_bytes
            result = preflight_capacity(
                probe_path=output_root,
                budget=capacity_budget,
                stage=stage,
                persistent_roots=(run_directory,),
                persistent_new_bytes_estimate=capacity_directory_size_bytes(
                    run_directory
                ),
                temporary_roots=tuple(temporary_roots),
                temporary_peak_bytes_observed=peak_temporary_bytes,
            )
            observed_temporary_bytes = result.temporary_peak_bytes_observed
            if observed_temporary_bytes is None:
                raise StorageCapacityError(
                    "capacity preflight returned an unknown temporary peak",
                    preflight=result.as_dict(),
                )
            peak_temporary_bytes = max(
                peak_temporary_bytes,
                observed_temporary_bytes,
            )
            last_capacity_preflight = result.as_dict()
            return last_capacity_preflight

        total_corporate_exclusions = 0
        total_teacher_incomplete = 0
        total_trade_restriction_unknown = 0
        total_teacher_diagnostics: dict[str, int] = {}
        year_manifests: list[dict[str, Any]] = []
        years = tuple(sorted(discovery.shard_by_year))
        _write_heartbeat(
            path=heartbeat_path,
            run_id=run_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
            status="running",
            stage="checkpoint_loaded",
            completed_years=tuple(sorted(completed)),
        )
        for ordinal, year in enumerate(years):
            try:
                capacity_checkpoint(
                    f"year_{year}_before_checkpoint",
                    (run_directory / f".work-year-{year:04d}",),
                )
            except StorageCapacityError as exc:
                _write_incomplete_checkpoint(
                    checkpoint_path=checkpoint_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    completed=completed,
                    peak_temporary_bytes=peak_temporary_bytes,
                    capacity_preflight=exc.preflight,
                    failure={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                _write_heartbeat(
                    path=heartbeat_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    status="blocked_capacity",
                    stage=f"year_{year}_before_checkpoint_capacity_blocked",
                    completed_years=tuple(sorted(completed)),
                    current_year=year,
                    year_ordinal=ordinal,
                )
                raise
            year_directory = run_directory / f"year={year:04d}"
            existing_year = completed.get(year)
            if (
                existing_year is not None
                and _checkpointed_year_is_valid(
                    year_directory=year_directory,
                    checkpoint_entry=existing_year,
                    shared_numeric_store_root=request.shared_numeric_store_root,
                )
            ):
                year_manifest = _read_json(
                    year_directory / "manifest.json"
                )
                year_manifests.append(year_manifest)
                _accumulate_teacher_diagnostics(
                    total_teacher_diagnostics,
                    year_manifest,
                )
                carry = _read_year_carry(
                    year_directory=year_directory,
                    year_manifest=year_manifest,
                    shared_numeric_store_root=request.shared_numeric_store_root,
                )
                total_corporate_exclusions += int(
                    year_manifest.get(
                        "corporate_action_excluded_label_count", 0
                    )
                )
                total_teacher_incomplete += int(
                    year_manifest.get(
                        "teacher_incomplete_decision_count", 0
                    )
                )
                total_trade_restriction_unknown += int(
                    year_manifest.get(
                        "trade_restriction_unknown_row_count", 0
                    )
                )
                _write_heartbeat(
                    path=heartbeat_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    status="running",
                    stage="year_checkpoint_reused",
                    completed_years=tuple(sorted(completed)),
                    current_year=year,
                    year_ordinal=ordinal,
                )
                continue
            if existing_year is not None:
                raise RuntimeError(
                    f"checkpointed direct year {year} failed custody validation"
                )
            if year_directory.exists():
                year_manifest, adopted_entry = _adopt_finalized_year(
                    year_directory=year_directory,
                    year=year,
                    year_ordinal=ordinal,
                    discovery=discovery,
                    dataset_identity_hash=dataset_identity_hash,
                    feature_registry_hash=feature_registry_hash,
                    shared_numeric_store_root=request.shared_numeric_store_root,
                )
                completed[year] = adopted_entry
                _write_incomplete_checkpoint(
                    checkpoint_path=checkpoint_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    completed=completed,
                    peak_temporary_bytes=peak_temporary_bytes,
                    capacity_preflight=last_capacity_preflight,
                )
                _write_heartbeat(
                    path=heartbeat_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    status="running",
                    stage="year_checkpoint_adopted",
                    completed_years=tuple(sorted(completed)),
                    current_year=year,
                    year_ordinal=ordinal,
                )
                year_manifests.append(year_manifest)
                _accumulate_teacher_diagnostics(
                    total_teacher_diagnostics,
                    year_manifest,
                )
                carry = _read_year_carry(
                    year_directory=year_directory,
                    year_manifest=year_manifest,
                    shared_numeric_store_root=request.shared_numeric_store_root,
                )
                total_corporate_exclusions += int(
                    year_manifest.get(
                        "corporate_action_excluded_label_count", 0
                    )
                )
                total_teacher_incomplete += int(
                    year_manifest.get(
                        "teacher_incomplete_decision_count", 0
                    )
                )
                total_trade_restriction_unknown += int(
                    year_manifest.get(
                        "trade_restriction_unknown_row_count", 0
                    )
                )
                memory_guard.observe(
                    stage=f"year_{year}_checkpoint_adopted"
                )
                continue
            if request.shared_numeric_store_root is not None:
                # Descriptor lookup is deliberately before ``_build_year``.
                # A reusable annual block must not create an assembly SQLite,
                # numeric staging files, or invoke the numeric writer first.
                annual_dates = tuple(
                    value
                    for value in discovery.eligible_dates
                    if date.fromisoformat(value).year == year
                )
                source_shards = [dict(discovery.shard_by_year[year])]
                if year + 1 in discovery.shard_by_year:
                    source_shards.append(
                        dict(discovery.shard_by_year[year + 1])
                    )
                reused = _try_reuse_shared_year(
                    year_directory=year_directory,
                    year=year,
                    year_ordinal=ordinal,
                    annual_dates=annual_dates,
                    source_shards=source_shards,
                    raw_manifest=raw_manifest,
                    source_manifest_hashes=source_manifest_hashes,
                    sector_manifest_hash=sector_manifest_hash,
                    feature_registry_hash=feature_registry_hash,
                    cutoff=cutoff,
                    benchmark_entity_id=request.benchmark_entity_id,
                    corporate_custody=corporate_custody,
                    portfolio_replay=portfolio_replay,
                    carry_input_hash=_carry_identity_hash(carry),
                    dataset_identity_hash=dataset_identity_hash,
                    shared_store_root=request.shared_numeric_store_root,
                )
                if reused is not None:
                    year_manifest, carry, temp_bytes = reused
                    peak_temporary_bytes = max(
                        peak_temporary_bytes,
                        temp_bytes,
                    )
                    try:
                        capacity_checkpoint(
                            f"year_{year}_shared_reuse_checkpoint",
                        )
                    except StorageCapacityError as exc:
                        _write_incomplete_checkpoint(
                            checkpoint_path=checkpoint_path,
                            run_id=run_id,
                            raw_manifest_hash=str(
                                raw_manifest["manifest_hash"]
                            ),
                            completed=completed,
                            peak_temporary_bytes=peak_temporary_bytes,
                            capacity_preflight=exc.preflight,
                            failure={
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            },
                        )
                        _write_heartbeat(
                            path=heartbeat_path,
                            run_id=run_id,
                            raw_manifest_hash=str(
                                raw_manifest["manifest_hash"]
                            ),
                            status="blocked_capacity",
                            stage=(
                                f"year_{year}_shared_reuse_capacity_blocked"
                            ),
                            completed_years=tuple(sorted(completed)),
                            current_year=year,
                            year_ordinal=ordinal,
                        )
                        raise
                    year_manifests.append(year_manifest)
                    _accumulate_teacher_diagnostics(
                        total_teacher_diagnostics,
                        year_manifest,
                    )
                    total_corporate_exclusions += int(
                        year_manifest[
                            "corporate_action_excluded_label_count"
                        ]
                    )
                    total_teacher_incomplete += int(
                        year_manifest[
                            "teacher_incomplete_decision_count"
                        ]
                    )
                    total_trade_restriction_unknown += int(
                        year_manifest[
                            "trade_restriction_unknown_row_count"
                        ]
                    )
                    completed[year] = _completed_year_entry(
                        year=year,
                        year_directory=year_directory,
                        year_manifest=year_manifest,
                        shared_numeric_store_root=(
                            request.shared_numeric_store_root
                        ),
                    )
                    _write_incomplete_checkpoint(
                        checkpoint_path=checkpoint_path,
                        run_id=run_id,
                        raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                        completed=completed,
                        peak_temporary_bytes=peak_temporary_bytes,
                        capacity_preflight=last_capacity_preflight,
                    )
                    _write_heartbeat(
                        path=heartbeat_path,
                        run_id=run_id,
                        raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                        status="running",
                        stage="year_shared_reused_before_build",
                        completed_years=tuple(sorted(completed)),
                        current_year=year,
                        year_ordinal=ordinal,
                    )
                    memory_guard.observe(
                        stage=f"year_{year}_shared_reused_before_build"
                    )
                    continue
            _write_heartbeat(
                path=heartbeat_path,
                run_id=run_id,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                status="running",
                stage="building_year",
                completed_years=tuple(sorted(completed)),
                current_year=year,
                year_ordinal=ordinal,
            )

            def _report_year_stage(stage: str) -> None:
                _write_heartbeat(
                    path=heartbeat_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    status="running",
                    stage=stage,
                    completed_years=tuple(sorted(completed)),
                    current_year=year,
                    year_ordinal=ordinal,
                )

            try:
                year_manifest, carry, temp_bytes = self._build_year(
                    request=request,
                    run_directory=run_directory,
                    raw_manifest_path=raw_path,
                    raw_manifest=raw_manifest,
                    discovery=discovery,
                    year=year,
                    year_ordinal=ordinal,
                    cutoff=cutoff,
                    source_manifest_hashes=source_manifest_hashes,
                    sector_manifest_hash=sector_manifest_hash,
                    dataset_identity_hash=dataset_identity_hash,
                    feature_registry_hash=feature_registry_hash,
                    portfolio_replay=portfolio_replay,
                    corporate_custody=corporate_custody,
                    carry=carry,
                    memory_guard=memory_guard,
                    heartbeat=_report_year_stage,
                    capacity_checkpoint=capacity_checkpoint,
                    capacity_budget=capacity_budget,
                )
            except StorageCapacityError as exc:
                _write_incomplete_checkpoint(
                    checkpoint_path=checkpoint_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    completed=completed,
                    peak_temporary_bytes=peak_temporary_bytes,
                    capacity_preflight=exc.preflight,
                    failure={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                _write_heartbeat(
                    path=heartbeat_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    status="blocked_capacity",
                    stage=f"year_{year}_capacity_blocked",
                    completed_years=tuple(sorted(completed)),
                    current_year=year,
                    year_ordinal=ordinal,
                )
                raise
            peak_temporary_bytes = max(
                peak_temporary_bytes,
                temp_bytes,
            )
            try:
                capacity_checkpoint(
                    f"year_{year}_checkpoint",
                )
            except StorageCapacityError as exc:
                _write_incomplete_checkpoint(
                    checkpoint_path=checkpoint_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    completed=completed,
                    peak_temporary_bytes=peak_temporary_bytes,
                    capacity_preflight=exc.preflight,
                    failure={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                _write_heartbeat(
                    path=heartbeat_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    status="blocked_capacity",
                    stage=f"year_{year}_checkpoint_capacity_blocked",
                    completed_years=tuple(sorted(completed)),
                    current_year=year,
                    year_ordinal=ordinal,
                )
                raise
            year_manifests.append(year_manifest)
            _accumulate_teacher_diagnostics(
                total_teacher_diagnostics,
                year_manifest,
            )
            total_corporate_exclusions += int(
                year_manifest[
                    "corporate_action_excluded_label_count"
                ]
            )
            total_teacher_incomplete += int(
                year_manifest["teacher_incomplete_decision_count"]
            )
            total_trade_restriction_unknown += int(
                year_manifest["trade_restriction_unknown_row_count"]
            )
            completed[year] = _completed_year_entry(
                year=year,
                year_directory=year_directory,
                year_manifest=year_manifest,
                shared_numeric_store_root=request.shared_numeric_store_root,
            )
            _write_incomplete_checkpoint(
                checkpoint_path=checkpoint_path,
                run_id=run_id,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                completed=completed,
                peak_temporary_bytes=peak_temporary_bytes,
                capacity_preflight=last_capacity_preflight,
            )
            _write_heartbeat(
                path=heartbeat_path,
                run_id=run_id,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                status="running",
                stage="year_checkpoint_complete",
                completed_years=tuple(sorted(completed)),
                current_year=year,
                year_ordinal=ordinal,
            )
            memory_guard.observe(stage=f"year_{year}_checkpoint_complete")

        _write_heartbeat(
            path=heartbeat_path,
            run_id=run_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
            status="running",
            stage="building_fold_indexes",
            completed_years=tuple(sorted(completed)),
        )
        capacity_checkpoint("fold_indexes_start")
        shared_year_rows_paths: dict[int, Path] | None = None
        if request.shared_numeric_store_root is not None:
            shared_year_rows_paths = {}
            for year_manifest in year_manifests:
                year_value = int(year_manifest["year"])
                shared_year_rows_paths[year_value] = (
                    resolve_direct_year_artifact_paths(
                        year_manifest,
                        year_directory=(
                            run_directory / f"year={year_value:04d}"
                        ),
                        shared_store_root=request.shared_numeric_store_root,
                    )["rows.sqlite"]
                )
        fold_manifests = (
            store_module.PortfolioMLOutOfCoreStoreBuilder()
            ._build_fold_indexes(
                run_directory=run_directory,
                folds=tuple(
                    asdict(window)
                    for window in discovery.fold_windows
                ),
                year_manifests=year_manifests,
                batch_size=request.batch_size,
                year_rows_paths=shared_year_rows_paths,
            )
        )
        capacity_checkpoint("fold_indexes_complete")
        portfolio_state_policy = portfolio_replay.custody_payload()
        official_trade_restriction_timeline_present = bool(
            corporate_custody.official_trade_restriction_timeline_present
            and total_trade_restriction_unknown == 0
        )
        blockers: set[str] = set()
        if portfolio_replay.cash_only_fallback:
            blockers.add(
                "portfolio_ledger_missing_cash_only_fallback_"
                "turnover_and_cooldown_not_learned"
            )
        if formal_rule_champion_custody is None:
            blockers.add(
                "formal_rule_champion_snapshot_history_missing_formal_replay_blocked"
            )
        if not official_trade_restriction_timeline_present:
            blockers.add(
                "official_trade_restriction_timeline_missing_formal_replay_blocked"
            )
        if sector_count == 0:
            blockers.add(
                "pit_sector_membership_missing_teacher_new_positions_disabled"
            )
        if not corporate_custody.manifest_present:
            blockers.add(
                "corporate_action_adjustment_timeline_not_in_raw_"
                "publication_labels_are_research_shadow"
            )
        if total_teacher_incomplete:
            blockers.add(
                "teacher_search_incomplete_for_one_or_more_decision_dates"
            )
        row_count = sum(
            int(item["row_count"]) for item in year_manifests
        )
        readiness_checks = {
            "all_expected_years_finalized": (
                len(year_manifests) == len(years)
                and {
                    int(item["year"]) for item in year_manifests
                }
                == set(years)
            ),
            "nonempty_numeric_rows": row_count > 0,
            "minimum_four_outer_folds": len(fold_manifests) >= 4,
            "pit_sector_membership_present": sector_count > 0,
            "official_corporate_action_custody_present": (
                corporate_custody.manifest_present
            ),
            "causal_non_cash_portfolio_ledger_present": (
                not bool(portfolio_state_policy["cash_only_fallback"])
            ),
            # Official restriction status is persisted per replay row only
            # after its effective/available ordering has been validated.
            "official_trade_restriction_timeline_present": (
                official_trade_restriction_timeline_present
            ),
            "formal_rule_champion_snapshot_history_present": (
                formal_rule_champion_custody is not None
            ),
            "teacher_search_complete": total_teacher_incomplete == 0,
            "memory_budget_measurable_and_within_limit": (
                memory_guard.peak_rss_bytes <= memory_guard.budget_bytes
            ),
        }
        readiness_failed_checks = sorted(
            check
            for check, passed in readiness_checks.items()
            if not passed
        )
        full_market_ready = not readiness_failed_checks
        direct_store_complete = bool(
            readiness_checks["all_expected_years_finalized"]
            and readiness_checks["nonempty_numeric_rows"]
            and readiness_checks["minimum_four_outer_folds"]
        )
        manifest: dict[str, Any] = {
            "schema_version": store_module.STORE_SCHEMA_VERSION,
            "status": "complete",
            "run_id": run_id,
            "dataset_id": (
                f"{raw_manifest['dataset_id']}-direct-allocation-"
                f"{dataset_identity_hash[7:19]}"
            ),
            "dataset_identity_hash": dataset_identity_hash,
            "dataset_manifest_file_hash": raw_file_hash,
            "source_training_manifest_hash": raw_manifest["manifest_hash"],
            "source_training_manifest_file_hash": raw_file_hash,
            "feature_registry_hash": feature_registry_hash,
            "source_manifest_hashes": [
                list(item) for item in source_manifest_hashes
            ],
            "training_as_of": cutoff.isoformat(),
            "formal_source_only": True,
            "research_shadow_included": False,
            "research_only": False,
            "promotion_eligible": False,
            "feature_packs": discovery.feature_packs,
            "feature_family_coverage": (
                store_module._feature_family_coverage(
                    feature_packs=discovery.feature_packs,
                    feature_ids=discovery.feature_ids,
                    year_manifests=year_manifests,
                )
            ),
            "feature_ids": list(discovery.feature_ids),
            "feature_scales": list(discovery.feature_scales),
            "feature_count": len(discovery.feature_ids),
            "horizons": list(legacy.SUPPORTED_HORIZONS),
            "target_fields": list(store_module.TARGET_FIELDS),
            "label_fields": list(store_module.LABEL_FIELDS),
            "row_count": row_count,
            "years": year_manifests,
            "folds": fold_manifests,
            "fold_count": len(fold_manifests),
            "assembly_blockers": sorted(blockers),
            "teacher_target_diagnostics": dict(
                sorted(total_teacher_diagnostics.items())
            ),
            "corporate_action_custody": (
                corporate_custody.custody_payload()
            ),
            "corporate_action_excluded_label_count": (
                total_corporate_exclusions
            ),
            "execution": {
                "direct_numeric_store": True,
                "direct_store_complete": direct_store_complete,
                "full_market_scale_capable": direct_store_complete,
                "full_market_ready": full_market_ready,
                "readiness_checks": readiness_checks,
                "readiness_failed_checks": readiness_failed_checks,
                "trade_restriction_unknown_row_count": (
                    total_trade_restriction_unknown
                ),
                "full_period_observation_sqlite": False,
                "training_jsonl_intermediate": False,
                "annual_work_sqlite": True,
                "annual_atomic_checkpoint": True,
                "compact_feature_carry": True,
                "replay_volume_cross_year_carry": True,
                "replay_volume_carry_schema_version": (
                    DIRECT_CARRY_SCHEMA_VERSION
                ),
                "replay_volume_carry_policy_version": (
                    DIRECT_REPLAY_VOLUME_POLICY_VERSION
                ),
                "shared_numeric_artifact_key_version": (
                    DIRECT_NUMERIC_ARTIFACT_KEY_VERSION
                    if request.shared_numeric_store_root is not None
                    else None
                ),
                "shared_numeric_reference_schema_version": (
                    DIRECT_NUMERIC_ARTIFACT_REFERENCE_SCHEMA_VERSION
                    if request.shared_numeric_store_root is not None
                    else None
                ),
                "shared_numeric_year_descriptor_schema_version": (
                    DIRECT_NUMERIC_YEAR_DESCRIPTOR_SCHEMA_VERSION
                    if request.shared_numeric_store_root is not None
                    else None
                ),
                "resume_supported": True,
                "sample_python_objects_retained": 0,
                "oof_python_objects_retained": 0,
                "batch_size": request.batch_size,
                "workers": request.workers,
                "memory_budget_mb": request.memory_budget_mb,
                "memory_budget_enforced": True,
                "peak_rss_bytes": memory_guard.peak_rss_bytes,
                "within_memory_budget": (
                    memory_guard.peak_rss_bytes
                    <= memory_guard.budget_bytes
                ),
                "temporary_storage_budget_bytes": (
                    temporary_budget_bytes
                ),
                "persistent_storage_budget_bytes": (
                    capacity_budget.persistent_new_bytes_budget
                ),
                "persistent_new_bytes_budget": (
                    capacity_budget.persistent_new_bytes_budget
                ),
                "safety_reserve_bytes": capacity_budget.safety_reserve_bytes,
                "temporary_storage_preflight": temporary_preflight,
                "temporary_storage_quota_enforced_during_workspace": True,
                "peak_temporary_bytes": peak_temporary_bytes,
                "capacity_budget": capacity_budget.as_dict(),
                "capacity_preflight": last_capacity_preflight,
            },
            "safety": {
                "pit_contract_revalidated_per_row": True,
                "t_minus_1_contract_revalidated_per_row": True,
                "replay_volume_future_seed_rejected": True,
                "replay_volume_duplicate_events_deduplicated": True,
                "replay_volume_zero_is_observed": True,
                "integer_scaled_features": True,
                "integer_bp_targets_and_labels": True,
                "source_shards_hash_verified": True,
                "fold_row_indexes_materialized": True,
                "purge_minimum_trading_days": 60,
                "embargo_minimum_trading_days": 5,
                "corporate_action_affected_horizons_excluded": (
                    corporate_custody.manifest_present
                ),
                "post_event_corporate_action_used_as_feature": False,
                "official_trade_restriction_bound_per_row": (
                    official_trade_restriction_timeline_present
                ),
                "trade_restriction_unknown_row_count": (
                    total_trade_restriction_unknown
                ),
                "production_alpha_bp": 0,
                "formal_oos_allowed": False,
                "broker_order_allowed": False,
            },
            "store_identity": store_identity,
        }
        if formal_rule_champion_custody is not None:
            manifest["formal_rule_champion_history"] = (
                formal_rule_champion_custody.custody_payload()
            )
        if not portfolio_replay.cash_only_fallback:
            manifest["portfolio_state_policy"] = portfolio_state_policy
        manifest["manifest_hash"] = _sha256_json(manifest)
        _write_heartbeat(
            path=heartbeat_path,
            run_id=run_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
            status="running",
            stage="publishing_manifest",
            completed_years=tuple(sorted(completed)),
        )
        _write_json(manifest_path, manifest)
        manifest_file_hash = _file_sha256(manifest_path)
        _atomic_write_json(
            checkpoint_path,
            {
                "schema_version": DIRECT_CHECKPOINT_SCHEMA_VERSION,
                "run_id": run_id,
                "raw_manifest_hash": raw_manifest["manifest_hash"],
                "completed_years": [
                    completed[key] for key in sorted(completed)
                ],
                "peak_temporary_bytes": peak_temporary_bytes,
                "capacity_budget": capacity_budget.as_dict(),
                "capacity_preflight": last_capacity_preflight,
                "complete": True,
                "manifest_hash": manifest["manifest_hash"],
                "manifest_file_hash": manifest_file_hash,
            },
        )
        store_module._write_latest_pointer(
            latest_manifest_path=latest_path,
            run_id=run_id,
            manifest=manifest,
        )
        _write_heartbeat(
            path=heartbeat_path,
            run_id=run_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
            status="complete",
            stage="complete",
            completed_years=tuple(sorted(completed)),
        )
        return _publication(
            run_id=run_id,
            run_directory=run_directory,
            manifest_path=manifest_path,
            latest_path=latest_path,
            manifest=manifest,
        )

    def _build_year(
        self,
        *,
        request: PortfolioMLDirectNumericRequest,
        run_directory: Path,
        raw_manifest_path: Path,
        raw_manifest: Mapping[str, Any],
        discovery: _Discovery,
        year: int,
        year_ordinal: int,
        cutoff: datetime,
        source_manifest_hashes: tuple[tuple[str, str], ...],
        sector_manifest_hash: str,
        dataset_identity_hash: str,
        feature_registry_hash: str,
        portfolio_replay: Any,
        corporate_custody: Any,
        carry: Any,
        memory_guard: _MemoryBudgetGuard,
        heartbeat: Callable[[str], None],
        capacity_checkpoint: Callable[
            [str, Sequence[Path]], dict[str, Any]
        ],
        capacity_budget: MLStorageCapacityBudget,
    ) -> tuple[dict[str, Any], Any, int]:
        temporary_budget_bytes = capacity_budget.temporary_peak_bytes_budget
        if temporary_budget_bytes is None:
            raise RuntimeError(
                "resolved Direct capacity budget lacks temporary limit"
            )
        carry_input_hash = _carry_identity_hash(carry)
        work = run_directory / f".work-year-{year:04d}"
        if work.exists():
            _safe_remove_tree(work, run_directory)
        work.mkdir(parents=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".year-{year:04d}-",
                dir=run_directory,
            )
        )
        connection = sqlite3.connect(work / "assembly.sqlite")
        connection.row_factory = sqlite3.Row
        legacy._initialize_spool(connection)
        try:
            def report_stage(stage: str) -> None:
                # Capacity is checked before publishing the heartbeat so an
                # operator never sees a stage as healthy after its budget was
                # already exceeded.
                capacity_stages = {
                    f"year_{year}_start",
                    f"year_{year}_raw_spool_complete",
                    f"year_{year}_labels_complete",
                    f"year_{year}_assembly_complete",
                    f"year_{year}_artifacts_complete",
                    f"year_{year}_directory_finalized",
                }
                if stage in capacity_stages:
                    capacity_checkpoint(stage, (work, staging))
                heartbeat(stage)

            report_stage(f"year_{year}_start")
            shards = [dict(discovery.shard_by_year[year])]
            if year + 1 in discovery.shard_by_year:
                shards.append(dict(discovery.shard_by_year[year + 1]))
            subset = dict(raw_manifest)
            subset["shards"] = shards
            base_definitions = legacy._base_feature_definitions(raw_manifest)
            spool_definitions = dict(base_definitions)
            for definition in discovery.definitions:
                spool_definitions[definition.feature_id] = definition
            legacy.PortfolioMLDatasetAssembler()._spool_raw_observations(
                connection=connection,
                dataset_manifest_path=raw_manifest_path,
                manifest=subset,
                definitions=spool_definitions,
                source_digest=hashlib.sha256(),
                batch_size=request.batch_size,
                shared_block_store_root=request.shared_block_store_root,
                progress_callback=report_stage,
            )
            report_stage("year_raw_spool_complete")
            memory_guard.observe(stage=f"year_{year}_raw_spool_complete")
            _enforce_workspace_budget(
                roots=(work, staging),
                budget_bytes=temporary_budget_bytes,
                stage=f"year_{year}_raw_spool_complete",
            )
            legacy._spool_sector_memberships(
                connection,
                request.sector_membership_path,
                training_as_of=cutoff,
            )
            calendar, benchmark_returns = legacy._build_label_spool(
                connection=connection,
                benchmark_entity_id=request.benchmark_entity_id,
                cutoff=cutoff,
                horizons=legacy.SUPPORTED_HORIZONS,
                batch_size=request.batch_size,
                corporate_action_effective_dates=(
                    corporate_custody.effective_dates_by_symbol
                ),
                progress_callback=report_stage,
            )
            report_stage("year_labels_complete")
            memory_guard.observe(stage=f"year_{year}_labels_complete")
            _enforce_workspace_budget(
                roots=(work, staging),
                budget_bytes=temporary_budget_bytes,
                stage=f"year_{year}_labels_complete",
            )
            del calendar
            corporate_excluded = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM label_exclusions
                    WHERE reason=?
                      AND decision_date >= ?
                      AND decision_date < ?
                    """,
                    (
                        "corporate_action_effective_within_label_horizon",
                        f"{year:04d}-01-01",
                        f"{year + 1:04d}-01-01",
                    ),
                ).fetchone()[0]
            )
            annual_dates = tuple(
                value
                for value in discovery.eligible_dates
                if date.fromisoformat(value).year == year
            )
            if not annual_dates:
                raise ValueError(f"year {year} has no eligible decision dates")
            if (
                year_ordinal > 0
                and carry.get(_CARRY_METADATA_KEY)
                != DIRECT_CARRY_SCHEMA_VERSION
            ):
                raise ValueError(
                    "direct replay volume carry is missing before noninitial year"
                )
            first_decision_at = datetime.combine(
                date.fromisoformat(annual_dates[0]),
                _DECISION_TIME,
                tzinfo=_TAIPEI,
            )
            registry = _DirectWriterRegistry(
                staging=staging,
                expected_year=year,
                year_ordinal=year_ordinal,
                feature_ids=discovery.feature_ids,
                feature_scales=discovery.feature_scales,
                horizons=legacy.SUPPORTED_HORIZONS,
                trade_restriction_events_by_symbol=(
                    corporate_custody.trade_restriction_events_by_symbol
                ),
                trade_restriction_timeline_present=(
                    corporate_custody.official_trade_restriction_timeline_present
                ),
                batch_size=request.batch_size,
                initial_volume_history=_volume_history_from_carry(carry),
                seed_cutoff=first_decision_at,
            )
            teacher_diagnostics: legacy.TeacherDiagnostics = {}
            teacher_incomplete, sample_count = (
                legacy.PortfolioMLDatasetAssembler()._assemble_samples(
                    connection=connection,
                    definitions=discovery.definitions,
                    source_manifest_hashes=source_manifest_hashes,
                    dataset_identity_hash=dataset_identity_hash,
                    feature_registry_hash=feature_registry_hash,
                    header_common={},
                    writers=cast(Any, registry),
                    cutoff=cutoff,
                    benchmark_entity_id=request.benchmark_entity_id,
                    benchmark_returns=benchmark_returns,
                    eligible_dates=annual_dates,
                    portfolio_state_replay=portfolio_replay,
                    years=(year,),
                    batch_size=request.batch_size,
                    initial_current_feature_cache=carry,
                    teacher_diagnostics=teacher_diagnostics,
                    progress_callback=report_stage,
                )
            )
            report_stage("year_assembly_complete")
            memory_guard.observe(stage=f"year_{year}_assembly_complete")
            _enforce_workspace_budget(
                roots=(work, staging),
                budget_bytes=temporary_budget_bytes,
                stage=f"year_{year}_assembly_complete",
            )
            if sample_count == 0:
                raise ValueError(f"year {year} emitted no mature samples")
            last_decision = annual_dates[-1]
            previous_cutoff = datetime.combine(
                date.fromisoformat(last_decision),
                _DECISION_TIME,
                tzinfo=_TAIPEI,
            )
            next_boundary = datetime.combine(
                date(year + 1, 1, 1),
                time.min,
                tzinfo=_TAIPEI,
            )
            carry_cutoff = min(cutoff, next_boundary)
            if carry_cutoff > previous_cutoff:
                legacy._advance_current_features(
                    connection,
                    previous_cutoff=previous_cutoff.isoformat(),
                    decision_at=carry_cutoff.isoformat(),
                    decision_date=carry_cutoff.date().isoformat(),
                    batch_size=request.batch_size,
                    current_feature_cache=carry,
                    persist_current_history=False,
                )
            writer = registry.writer
            writer.close()
            carry[DIRECT_REPLAY_VOLUME_CARRY_SCOPE] = (
                writer.volume_history_carry()
            )
            carry_path = staging / "carry.state.gz"
            carry_count = _write_carry(carry_path, carry)
            artifacts = store_module._artifact_payloads(
                staging,
                (
                    writer.values_path,
                    writer.masks_path,
                    writer.targets_path,
                    writer.labels_path,
                    writer.label_masks_path,
                    writer.rows_path,
                    writer.replay_source_path,
                    carry_path,
                ),
                workers=request.workers,
            )
            year_manifest: dict[str, Any] = {
                "schema_version": store_module.YEAR_SCHEMA_VERSION,
                "year": year,
                "year_ordinal": year_ordinal,
                "row_count": writer.row_count,
                "feature_count": len(discovery.feature_ids),
                "dataset_identity_hash": dataset_identity_hash,
                "feature_registry_hash": feature_registry_hash,
                "source_manifest_hashes": [
                    list(item) for item in source_manifest_hashes
                ],
                "feature_values_shape": [
                    writer.row_count,
                    len(discovery.feature_ids),
                ],
                "feature_observed_counts": [
                    int(value) for value in writer.observed_counts
                ],
                "target_shape": [
                    writer.row_count,
                    len(store_module.TARGET_FIELDS),
                ],
                "label_shape": [
                    writer.row_count,
                    len(legacy.SUPPORTED_HORIZONS),
                    len(store_module.LABEL_FIELDS),
                ],
                "replay_source": {
                    "schema_version": _REPLAY_SOURCE_SCHEMA_VERSION,
                    "path": writer.replay_source_path.name,
                    "row_count": writer.row_count,
                    "t_minus_one_price_event_and_availability_persisted": True,
                    "pit_sector_id_persisted": True,
                    "median_volume_20d_uses_distinct_causal_price_events": True,
                    "volume_history_carry_schema_version": (
                        DIRECT_CARRY_SCHEMA_VERSION
                    ),
                    "volume_history_carry_policy_version": (
                        DIRECT_REPLAY_VOLUME_POLICY_VERSION
                    ),
                    "volume_history_seed_event_count": (
                        writer.volume_history_seed_event_count
                    ),
                    "volume_history_final_event_count": (
                        writer.volume_history_event_count
                    ),
                    "volume_history_max_event_count_per_symbol": (
                        writer.volume_history_max_event_count_per_symbol
                    ),
                    "volume_history_duplicate_event_count": (
                        writer.volume_history_duplicate_event_count
                    ),
                    "volume_history_future_event_count": (
                        writer.volume_history_future_event_count
                    ),
                    "volume_history_invalid_event_count": (
                        writer.volume_history_invalid_event_count
                    ),
                    "volume_history_invalid_volume_count": (
                        writer.volume_history_invalid_volume_count
                    ),
                    "official_trade_restriction_timeline_present": (
                        corporate_custody.official_trade_restriction_timeline_present
                        and registry.writer.unknown_trade_restriction_count == 0
                    ),
                    "trade_restriction_unknown_row_count": (
                        registry.writer.unknown_trade_restriction_count
                    ),
                    "teacher_targets_used": False,
                },
                "direct_source_shards": [
                    {
                        "year": int(item["year"]),
                        "path": _shard_lineage_path(item),
                        "compressed_sha256": item["compressed_sha256"],
                        "content_sha256": item["content_sha256"],
                    }
                    for item in shards
                ],
                "carry_entry_count": carry_count,
                "carry_schema_version": DIRECT_CARRY_SCHEMA_VERSION,
                "teacher_incomplete_decision_count": teacher_incomplete,
                # 這些是每個決策日的 bounded provenance 計數；只說明
                # teacher 為何形成現有 target，不會把缺件補成可訓練標籤。
                "teacher_target_diagnostics": dict(
                    sorted(teacher_diagnostics.items())
                ),
                "trade_restriction_unknown_row_count": (
                    registry.writer.unknown_trade_restriction_count
                ),
                "corporate_action_excluded_label_count": (
                    corporate_excluded
                ),
                "artifacts": artifacts,
                "complete": True,
            }
            if request.shared_numeric_store_root is not None:
                year_manifest["shared_artifact_publication"] = (
                    _publish_direct_year_artifacts(
                        staging=staging,
                        year_manifest=year_manifest,
                        year=year,
                        year_ordinal=year_ordinal,
                        annual_dates=annual_dates,
                        source_shards=shards,
                        raw_manifest=raw_manifest,
                        source_manifest_hashes=source_manifest_hashes,
                        sector_manifest_hash=sector_manifest_hash,
                        feature_registry_hash=feature_registry_hash,
                        cutoff=cutoff,
                        benchmark_entity_id=request.benchmark_entity_id,
                        corporate_custody=corporate_custody,
                        portfolio_replay=portfolio_replay,
                        carry_input_hash=carry_input_hash,
                        shared_store_root=(
                            request.shared_numeric_store_root
                        ),
                        temporary_budget_bytes=(
                            temporary_budget_bytes
                        ),
                    )
                )
            year_manifest["manifest_hash"] = _sha256_json(year_manifest)
            _write_json(staging / "manifest.json", year_manifest)
            report_stage("year_artifacts_complete")
            memory_guard.observe(stage=f"year_{year}_artifacts_complete")
            connection.close()
            temp_bytes = _directory_size_bytes(work) + _directory_size_bytes(
                staging
            )
            _enforce_temporary_budget(
                observed_bytes=temp_bytes,
                budget_bytes=temporary_budget_bytes,
            )
            final_directory = run_directory / f"year={year:04d}"
            _replace_directory_with_retry(staging, final_directory)
            _safe_remove_tree(work, run_directory)
            report_stage("year_directory_finalized")
            return year_manifest, carry, temp_bytes
        except Exception:
            connection.close()
            if staging.exists():
                _safe_remove_tree(staging, run_directory)
            if work.exists():
                _safe_remove_tree(work, run_directory)
            raise


@dataclass(frozen=True)
class _VolumeHistoryCarryValue:
    """跨年度 replay volume carry 的單一 bounded event。"""

    price_event_at: str
    volume_shares: int


class _DirectWriterRegistry:
    def __init__(
        self,
        *,
        staging: Path,
        expected_year: int,
        year_ordinal: int,
        feature_ids: tuple[str, ...],
        feature_scales: tuple[int, ...],
        horizons: tuple[int, ...],
        trade_restriction_events_by_symbol: Mapping[
            str, Sequence[Any]
        ],
        trade_restriction_timeline_present: bool,
        batch_size: int,
        initial_volume_history: Mapping[
            str, Sequence[tuple[str, int]]
        ] | None = None,
        seed_cutoff: datetime | None = None,
    ) -> None:
        self.expected_year = expected_year
        self.writer = _DirectYearWriter(
            staging=staging,
            year=expected_year,
            year_ordinal=year_ordinal,
            feature_ids=feature_ids,
            feature_scales=feature_scales,
            horizons=horizons,
            trade_restriction_events_by_symbol=(
                trade_restriction_events_by_symbol
            ),
            trade_restriction_timeline_present=(
                trade_restriction_timeline_present
            ),
            batch_size=batch_size,
            initial_volume_history=initial_volume_history,
            seed_cutoff=seed_cutoff,
        )

    def get(self, *, year: int, header: Mapping[str, Any]) -> Any:
        del header
        if year != self.expected_year:
            raise ValueError("direct writer received a cross-year sample")
        return self.writer


class _DirectYearWriter:
    def __init__(
        self,
        *,
        staging: Path,
        year: int,
        year_ordinal: int,
        feature_ids: tuple[str, ...],
        feature_scales: tuple[int, ...],
        horizons: tuple[int, ...],
        trade_restriction_events_by_symbol: Mapping[
            str, Sequence[Any]
        ],
        trade_restriction_timeline_present: bool,
        batch_size: int,
        initial_volume_history: Mapping[
            str, Sequence[tuple[str, int]]
        ] | None = None,
        seed_cutoff: datetime | None = None,
    ) -> None:
        self.year = year
        self.year_ordinal = year_ordinal
        self.feature_ids = feature_ids
        self.feature_scales = feature_scales
        self.feature_position = {
            feature_id: index
            for index, feature_id in enumerate(feature_ids)
        }
        self.horizons = horizons
        self.trade_restriction_events_by_symbol = (
            trade_restriction_events_by_symbol
        )
        self.trade_restriction_timeline_present = (
            trade_restriction_timeline_present
        )
        self.horizon_position = {
            horizon: index for index, horizon in enumerate(horizons)
        }
        self.batch_size = batch_size
        self.values_path = staging / "features.values.i64"
        self.masks_path = staging / "features.masks.u8"
        self.targets_path = staging / "targets.i32"
        self.labels_path = staging / "labels.i32"
        self.label_masks_path = staging / "labels.masks.u8"
        self.rows_path = staging / "rows.sqlite"
        self.replay_source_path = staging / "replay_source.sqlite"
        self._values = self.values_path.open("wb")
        self._masks = self.masks_path.open("wb")
        self._targets = self.targets_path.open("wb")
        self._labels = self.labels_path.open("wb")
        self._label_masks = self.label_masks_path.open("wb")
        self._rows = sqlite3.connect(self.rows_path)
        self._rows.executescript(
            """
            CREATE TABLE rows (
                local_row_index INTEGER PRIMARY KEY,
                row_id TEXT NOT NULL UNIQUE,
                decision_at TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                portfolio_state_hash TEXT NOT NULL,
                target_available_at TEXT NOT NULL,
                max_label_available_at TEXT NOT NULL,
                max_horizon_end_date TEXT NOT NULL,
                sample_hash TEXT NOT NULL
            );
            CREATE INDEX idx_rows_decision
                ON rows(decision_date, local_row_index);
            """
        )
        self._replay_source = sqlite3.connect(self.replay_source_path)
        self._replay_source.executescript(
            """
            CREATE TABLE replay_source (
                local_row_index INTEGER PRIMARY KEY,
                decision_at TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                sector_id TEXT,
                price_event_at TEXT,
                price_available_at TEXT,
                open_int INTEGER,
                open_scale INTEGER,
                close_int INTEGER,
                close_scale INTEGER,
                volume_shares INTEGER,
                median_volume_20d_shares INTEGER,
                rule_score_bp INTEGER,
                trade_restriction_status TEXT NOT NULL,
                source_values_hash TEXT NOT NULL
            );
            CREATE INDEX idx_replay_source_decision
                ON replay_source(decision_date, local_row_index);
            CREATE INDEX idx_replay_source_price_event
                ON replay_source(price_event_at, symbol);
            """
        )
        self._row_batch: list[tuple[object, ...]] = []
        self._replay_source_batch: list[tuple[object, ...]] = []
        self._volume_history: dict[str, deque[tuple[str, int]]] = {}
        self._volume_event_keys: dict[str, set[str]] = {}
        self._seed_cutoff = seed_cutoff
        self.volume_history_seed_event_count = 0
        self.volume_history_duplicate_event_count = 0
        self.volume_history_future_event_count = 0
        self.volume_history_invalid_event_count = 0
        self.volume_history_invalid_volume_count = 0
        if initial_volume_history:
            self._load_initial_volume_history(initial_volume_history)
        self._decision_at_cache: dict[str, datetime] = {}
        self.row_count = 0
        self.unknown_trade_restriction_count = 0
        self.observed_counts = np.zeros(
            len(feature_ids),
            dtype=np.int64,
        )
        self._closed = False

    def _load_initial_volume_history(
        self,
        initial_volume_history: Mapping[str, Sequence[tuple[str, int]]],
    ) -> None:
        """載入上一年度最多 20 個事件，並拒絕未來 seed。"""

        for raw_symbol, raw_events in initial_volume_history.items():
            symbol = str(raw_symbol)
            if not symbol:
                raise ValueError("volume carry symbol must be non-empty")
            if len(raw_events) > _VOLUME_WINDOW_SIZE:
                raise ValueError("volume carry exceeds bounded 20-event window")
            history: deque[tuple[str, int]] = deque(
                maxlen=_VOLUME_WINDOW_SIZE
            )
            event_keys: set[str] = set()
            for raw_event_at, raw_volume in raw_events:
                event_at = _canonical_volume_event_at(raw_event_at)
                if event_at in event_keys:
                    raise ValueError(
                        "volume carry contains duplicate price event"
                    )
                volume = _require_nonnegative_volume(raw_volume)
                if (
                    self._seed_cutoff is not None
                    and _volume_event_datetime(event_at) >= self._seed_cutoff
                ):
                    raise ValueError(
                        "volume carry contains event at or after year seed cutoff"
                    )
                history.append((event_at, volume))
                event_keys.add(event_at)
            self._volume_history[symbol] = history
            self._volume_event_keys[symbol] = event_keys
            self.volume_history_seed_event_count += len(history)

    def volume_history_carry(
        self,
    ) -> dict[str, dict[str, _VolumeHistoryCarryValue]]:
        """匯出 bounded carry；順序與內容可重現且不含當年未來事件。"""

        return {
            symbol: {
                event_at: _VolumeHistoryCarryValue(
                    price_event_at=event_at,
                    volume_shares=volume,
                )
                for event_at, volume in history
            }
            for symbol, history in sorted(self._volume_history.items())
            if history
        }

    @property
    def volume_history_event_count(self) -> int:
        return sum(len(history) for history in self._volume_history.values())

    @property
    def volume_history_max_event_count_per_symbol(self) -> int:
        """回傳單一 symbol 的最大 bounded window 長度。"""

        return max(
            (len(history) for history in self._volume_history.values()),
            default=0,
        )

    def write_sample(self, sample: AllocationTrainingSample) -> None:
        self.write_sample_with_context(
            sample,
            sector_id=None,
            stock_current={},
        )

    def write_sample_with_context(
        self,
        sample: AllocationTrainingSample,
        *,
        sector_id: str | None,
        stock_current: Mapping[str, Any],
    ) -> None:
        row = sample.row
        if int(row.decision_at[:4]) != self.year:
            raise ValueError("direct writer sample year mismatch")
        features = {
            feature.feature_id: feature for feature in row.features
        }
        if set(features) != set(self.feature_ids):
            raise ValueError("direct sample feature registry mismatch")
        values = np.zeros(len(self.feature_ids), dtype="<i8")
        masks = np.ones(len(self.feature_ids), dtype="u1")
        for feature_id, position in self.feature_position.items():
            feature = features[feature_id]
            if feature.scale != self.feature_scales[position]:
                raise ValueError("direct sample feature scale drift")
            if feature.observed:
                assert feature.value_int is not None
                store_module._require_int_range(
                    feature.value_int,
                    dtype=store_module.VALUE_DTYPE,
                    field_name=feature_id,
                )
                values[position] = feature.value_int
                masks[position] = 0
                self.observed_counts[position] += 1
        targets = row.targets
        if targets is None:
            raise ValueError("direct formal sample requires targets")
        symbol = row.symbol
        target_values = np.asarray(
            (
                dict(targets.target_weights.positions_bp).get(symbol, 0),
                dict(targets.delta_weights_bp).get(symbol, 0),
                dict(targets.risk_contributions_bp).get(symbol, 0),
                targets.risky_budget_bp,
                targets.cash_bp,
                int(targets.rebalance_worthwhile),
            ),
            dtype="<i4",
        )
        labels = np.zeros(
            len(self.horizons) * len(store_module.LABEL_FIELDS),
            dtype="<i4",
        )
        label_masks = np.ones(len(labels), dtype="u1")
        labels_by_horizon = {
            label.horizon_trading_days: label
            for label in sample.horizon_labels
        }
        if set(labels_by_horizon) != set(self.horizons):
            raise ValueError("direct sample horizon labels mismatch")
        max_available_at = ""
        max_horizon_end = ""
        for horizon, horizon_position in self.horizon_position.items():
            label = labels_by_horizon[horizon]
            max_available_at = max(max_available_at, label.available_at)
            max_horizon_end = max(
                max_horizon_end,
                label.horizon_end_date,
            )
            start = horizon_position * len(store_module.LABEL_FIELDS)
            sector_value = (
                0
                if label.sector_excess_return_bp is None
                else label.sector_excess_return_bp
            )
            labels[start : start + len(store_module.LABEL_FIELDS)] = (
                label.benchmark_excess_return_bp,
                sector_value,
                int(label.downside_observed),
                label.mae_bp,
                label.mfe_bp,
                label.realized_volatility_bp,
                label.max_drawdown_bp,
                label.tail_loss_bp,
                int(label.fill_feasible_observed),
            )
            label_masks[
                start : start + len(store_module.LABEL_FIELDS)
            ] = 0
            if label.sector_excess_return_bp is None:
                label_masks[start + 1] = 1
        self._values.write(values.tobytes(order="C"))
        self._masks.write(masks.tobytes(order="C"))
        self._targets.write(target_values.tobytes(order="C"))
        self._labels.write(labels.tobytes(order="C"))
        self._label_masks.write(label_masks.tobytes(order="C"))
        self._row_batch.append(
            (
                self.row_count,
                row.row_id,
                row.decision_at,
                row.decision_at[:10],
                row.symbol,
                row.portfolio_state.state_hash,
                targets.available_at,
                max_available_at,
                max_horizon_end,
                _sha256_json(asdict(sample)),
            )
        )
        replay_values = self._replay_values(
            symbol=symbol,
            decision_at=row.decision_at,
            stock_current=stock_current,
        )
        self._replay_source_batch.append(
            (
                self.row_count,
                row.decision_at,
                row.decision_at[:10],
                symbol,
                sector_id,
                replay_values["price_event_at"],
                replay_values["price_available_at"],
                replay_values["open_int"],
                replay_values["open_scale"],
                replay_values["close_int"],
                replay_values["close_scale"],
                replay_values["volume_shares"],
                replay_values["median_volume_20d_shares"],
                replay_values["rule_score_bp"],
                replay_values["trade_restriction_status"],
                replay_values["source_values_hash"],
            )
        )
        self.row_count += 1
        if len(self._row_batch) >= self.batch_size:
            self._flush_rows()

    def _replay_values(
        self,
        *,
        symbol: str,
        decision_at: str,
        stock_current: Mapping[str, Any],
    ) -> dict[str, object]:
        open_value = stock_current.get(_PRICE_OPEN_FEATURE_ID)
        close_value = stock_current.get(_PRICE_CLOSE_FEATURE_ID)
        volume_value = stock_current.get(_PRICE_VOLUME_FEATURE_ID)
        ma20_value = stock_current.get(_RULE_MA20_FEATURE_ID)
        price_values = tuple(
            value
            for value in (open_value, close_value, volume_value)
            if value is not None
        )
        price_event_at = (
            max(str(value.event_at) for value in price_values)
            if price_values
            else None
        )
        price_available_at = (
            max(str(value.available_at) for value in price_values)
            if price_values
            else None
        )
        volume_shares = _eligible_current_int(volume_value)
        decision_datetime = self._decision_at_cache.get(decision_at)
        if decision_datetime is None:
            decision_datetime = legacy._available_datetime(
                decision_at,
                field_name="direct replay decision_at",
            )
            self._decision_at_cache[decision_at] = decision_datetime
        history = self._volume_history.setdefault(symbol, deque(maxlen=20))
        event_keys = self._volume_event_keys.setdefault(symbol, set())
        if price_event_at is not None and volume_shares is not None:
            if volume_shares < 0:
                self.volume_history_invalid_volume_count += 1
            else:
                try:
                    event_key = _canonical_volume_event_at(price_event_at)
                    event_datetime = _volume_event_datetime(event_key)
                    available_datetime = (
                        _volume_event_datetime(
                            _canonical_volume_event_at(price_available_at)
                        )
                        if price_available_at is not None
                        else event_datetime
                    )
                except ValueError:
                    self.volume_history_invalid_event_count += 1
                else:
                    if (
                        event_datetime >= decision_datetime
                        or available_datetime >= decision_datetime
                    ):
                        self.volume_history_future_event_count += 1
                    elif event_key in event_keys:
                        self.volume_history_duplicate_event_count += 1
                    else:
                        if len(history) >= _VOLUME_WINDOW_SIZE:
                            evicted_event_at, _ = history.popleft()
                            event_keys.discard(evicted_event_at)
                        history.append((event_key, volume_shares))
                        event_keys.add(event_key)
        median_volume = None
        if len(history) >= _VOLUME_WINDOW_SIZE:
            ordered = sorted(item[1] for item in history)
            median_volume = (
                ordered[9] + ordered[10]
            ) // 2
        open_int = _eligible_current_int(open_value)
        close_int = _eligible_current_int(close_value)
        open_scale = _eligible_current_scale(open_value)
        close_scale = _eligible_current_scale(close_value)
        rule_score_bp = _relative_score_bp(close_value, ma20_value)
        trade_restriction_status = _official_trade_restriction_status(
            self.trade_restriction_events_by_symbol.get(symbol, ()),
            decision_at=decision_datetime,
            timeline_present=self.trade_restriction_timeline_present,
        )
        if trade_restriction_status.startswith("unknown_"):
            self.unknown_trade_restriction_count += 1
        hashes = sorted(
            str(value.source_value_hash)
            for value in (
                open_value,
                close_value,
                volume_value,
                ma20_value,
            )
            if value is not None
        )
        return {
            "price_event_at": price_event_at,
            "price_available_at": price_available_at,
            "open_int": open_int,
            "open_scale": open_scale,
            "close_int": close_int,
            "close_scale": close_scale,
            "volume_shares": volume_shares,
            "median_volume_20d_shares": median_volume,
            "rule_score_bp": rule_score_bp,
            "trade_restriction_status": trade_restriction_status,
            "source_values_hash": _sha256_json(hashes),
        }

    def _flush_rows(self) -> None:
        self._rows.executemany(
            """
            INSERT INTO rows(
                local_row_index, row_id, decision_at, decision_date, symbol,
                portfolio_state_hash, target_available_at,
                max_label_available_at, max_horizon_end_date, sample_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._row_batch,
        )
        self._rows.commit()
        self._row_batch.clear()
        self._replay_source.executemany(
            """
            INSERT INTO replay_source(
                local_row_index, decision_at, decision_date, symbol,
                sector_id, price_event_at, price_available_at,
                open_int, open_scale, close_int, close_scale,
                volume_shares, median_volume_20d_shares, rule_score_bp,
                trade_restriction_status, source_values_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._replay_source_batch,
        )
        self._replay_source.commit()
        self._replay_source_batch.clear()

    def close(self) -> None:
        if self._closed:
            return
        if self._row_batch:
            self._flush_rows()
        self._rows.close()
        self._replay_source.close()
        for stream in (
            self._values,
            self._masks,
            self._targets,
            self._labels,
            self._label_masks,
        ):
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
        self._closed = True


def _discovery_cache_identity(
    *,
    raw_manifest: Mapping[str, Any],
    raw_manifest_file_hash: str,
    cutoff: datetime,
    benchmark_entity_id: str,
    minimum_train_dates: int,
    test_date_count: int,
    purge_trading_days: int,
    embargo_trading_days: int,
) -> dict[str, Any]:
    return {
        "raw_manifest_hash": str(raw_manifest["manifest_hash"]),
        "raw_manifest_file_hash": raw_manifest_file_hash,
        "training_as_of": cutoff.isoformat(),
        "benchmark_entity_id": benchmark_entity_id,
        "minimum_train_dates": minimum_train_dates,
        "test_date_count": test_date_count,
        "purge_trading_days": purge_trading_days,
        "embargo_trading_days": embargo_trading_days,
    }


def _write_discovery_cache(
    *,
    path: Path,
    raw_manifest: Mapping[str, Any],
    raw_manifest_file_hash: str,
    cutoff: datetime,
    benchmark_entity_id: str,
    minimum_train_dates: int,
    test_date_count: int,
    purge_trading_days: int,
    embargo_trading_days: int,
    discovery: _Discovery,
) -> None:
    discovery_payload: dict[str, Any] = {
        "definitions": [
            asdict(definition) for definition in discovery.definitions
        ],
        "feature_packs": discovery.feature_packs,
        "feature_ids": list(discovery.feature_ids),
        "feature_scales": list(discovery.feature_scales),
        "calendar": list(discovery.calendar),
        "eligible_dates": list(discovery.eligible_dates),
        "fold_windows": [
            asdict(window) for window in discovery.fold_windows
        ],
        "shard_by_year": {
            str(year): dict(shard)
            for year, shard in discovery.shard_by_year.items()
        },
        "source_content_hash": discovery.source_content_hash,
    }
    payload: dict[str, Any] = {
        "schema_version": DIRECT_DISCOVERY_CACHE_SCHEMA_VERSION,
        "identity": _discovery_cache_identity(
            raw_manifest=raw_manifest,
            raw_manifest_file_hash=raw_manifest_file_hash,
            cutoff=cutoff,
            benchmark_entity_id=benchmark_entity_id,
            minimum_train_dates=minimum_train_dates,
            test_date_count=test_date_count,
            purge_trading_days=purge_trading_days,
            embargo_trading_days=embargo_trading_days,
        ),
        "discovery": discovery_payload,
    }
    payload["cache_hash"] = _sha256_json(payload)
    _atomic_write_json(path, payload)


def _load_discovery_cache(
    *,
    path: Path,
    raw_manifest_path: Path,
    raw_manifest: Mapping[str, Any],
    raw_manifest_file_hash: str,
    cutoff: datetime,
    benchmark_entity_id: str,
    minimum_train_dates: int,
    test_date_count: int,
    purge_trading_days: int,
    embargo_trading_days: int,
    shared_block_store_root: Path | None = None,
    shared_contract: tuple[str, str, str] | None = None,
) -> _Discovery | None:
    if not path.is_file():
        return None
    try:
        payload = _read_json(path)
        if payload.get("schema_version") != (
            DIRECT_DISCOVERY_CACHE_SCHEMA_VERSION
        ):
            return None
        cache_hash = payload.get("cache_hash")
        unsigned_payload = dict(payload)
        unsigned_payload.pop("cache_hash", None)
        if cache_hash != _sha256_json(unsigned_payload):
            return None
        expected_identity = _discovery_cache_identity(
            raw_manifest=raw_manifest,
            raw_manifest_file_hash=raw_manifest_file_hash,
            cutoff=cutoff,
            benchmark_entity_id=benchmark_entity_id,
            minimum_train_dates=minimum_train_dates,
            test_date_count=test_date_count,
            purge_trading_days=purge_trading_days,
            embargo_trading_days=embargo_trading_days,
        )
        if payload.get("identity") != expected_identity:
            return None
        discovery_payload = _mapping(
            payload.get("discovery"),
            field_name="discovery cache discovery",
        )
        _validate_discovery_cache_shards(
            raw_manifest_path=raw_manifest_path,
            raw_manifest=raw_manifest,
            cached_shards=discovery_payload.get("shard_by_year"),
            shared_block_store_root=shared_block_store_root,
            shared_contract=shared_contract,
        )
        definitions = tuple(
            _cached_feature_definition(item)
            for item in _mapping_sequence(
                discovery_payload.get("definitions"),
                field_name="discovery cache definitions",
            )
        )
        feature_packs = [
            dict(item)
            for item in _mapping_sequence(
                discovery_payload.get("feature_packs"),
                field_name="discovery cache feature_packs",
            )
        ]
        feature_ids = tuple(
            str(item)
            for item in _sequence(
                discovery_payload.get("feature_ids"),
                field_name="discovery cache feature_ids",
            )
        )
        feature_scales = tuple(
            int(cast(Any, item))
            for item in _sequence(
                discovery_payload.get("feature_scales"),
                field_name="discovery cache feature_scales",
            )
        )
        if len(feature_ids) != len(feature_scales):
            raise ValueError("discovery cache feature scale length mismatch")
        calendar = tuple(
            str(item)
            for item in _sequence(
                discovery_payload.get("calendar"),
                field_name="discovery cache calendar",
            )
        )
        eligible_dates = tuple(
            str(item)
            for item in _sequence(
                discovery_payload.get("eligible_dates"),
                field_name="discovery cache eligible_dates",
            )
        )
        fold_windows = tuple(
            _cached_fold_window(item)
            for item in _mapping_sequence(
                discovery_payload.get("fold_windows"),
                field_name="discovery cache fold_windows",
            )
        )
        cached_shards = _mapping(
            discovery_payload.get("shard_by_year"),
            field_name="discovery cache shard_by_year",
        )
        shard_by_year = {
            int(year): dict(
                _mapping(item, field_name="discovery cache shard")
            )
            for year, item in cached_shards.items()
        }
        source_content_hash = str(
            discovery_payload["source_content_hash"]
        )
        if not source_content_hash.startswith(_SHA256_PREFIX):
            raise ValueError("discovery cache source hash is invalid")
        if len(fold_windows) < 4:
            raise ValueError("discovery cache requires at least four folds")
        return _Discovery(
            definitions=definitions,
            feature_packs=feature_packs,
            feature_ids=feature_ids,
            feature_scales=feature_scales,
            calendar=calendar,
            eligible_dates=eligible_dates,
            fold_windows=fold_windows,
            shard_by_year=shard_by_year,
            source_content_hash=source_content_hash,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _resolve_direct_shard_path(
    *,
    raw_manifest_path: Path,
    shard: Mapping[str, Any],
    shared_block_store_root: Path | None,
    shared_contract: tuple[str, str, str] | None,
) -> Path:
    """解析 Direct discovery 的 local/shared shard，保持 bytes 不落回 run。"""

    publication_root = raw_manifest_path.parent.parent.resolve()
    if shared_block_store_root is None:
        shard_path = (publication_root / str(shard["path"])).resolve()
        if not shard_path.is_relative_to(publication_root):
            raise ValueError("raw shard path escapes publication root")
        if _file_sha256(shard_path) != str(shard["compressed_sha256"]):
            raise ValueError("raw shard compressed hash mismatch")
        return shard_path
    resolved = resolve_pit_shard_record(
        record=shard,
        publication_root=publication_root,
        shared_store_root=Path(shared_block_store_root).resolve(),
        expected_feature_contract_hash=(
            shared_contract[0] if shared_contract is not None else None
        ),
        expected_maturity_policy=(
            shared_contract[1] if shared_contract is not None else None
        ),
        expected_lane=(
            shared_contract[2] if shared_contract is not None else None
        ),
    )
    return resolved.path


def _shard_lineage_path(shard: Mapping[str, Any]) -> str:
    """回傳 local path 或 shared view 保存的 source_path 作為 custody label。"""

    value = shard.get("path", shard.get("source_path"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("raw shard requires path or source_path lineage")
    return value


def _validate_discovery_cache_shards(
    *,
    raw_manifest_path: Path,
    raw_manifest: Mapping[str, Any],
    cached_shards: object,
    shared_block_store_root: Path | None = None,
    shared_contract: tuple[str, str, str] | None = None,
) -> None:
    cached = _mapping(
        cached_shards,
        field_name="discovery cache shard_by_year",
    )
    publication_root = raw_manifest_path.parent.parent.resolve()
    manifest_shards = legacy._mapping_sequence(
        raw_manifest.get("shards"),
        field_name="shards",
    )
    manifest_years = {int(item["year"]) for item in manifest_shards}
    cached_years = {int(year) for year in cached}
    if cached_years != manifest_years:
        raise ValueError("discovery cache shard years mismatch")
    for shard in manifest_shards:
        shard_path = _resolve_direct_shard_path(
            raw_manifest_path=raw_manifest_path,
            shard=shard,
            shared_block_store_root=shared_block_store_root,
            shared_contract=shared_contract,
        )
        del shard_path


def _cached_feature_definition(
    value: Mapping[str, Any],
) -> Any:
    dimensions = value.get("dimension_values")
    if not isinstance(dimensions, list):
        raise TypeError("discovery cache dimension_values must be a list")
    return legacy._FeatureDefinition(
        feature_id=str(value["feature_id"]),
        base_feature_id=str(value["base_feature_id"]),
        table_name=str(value["table_name"]),
        family_id=str(value["family_id"]),
        source_id=str(value["source_id"]),
        scale=int(value["scale"]),
        stale_after_days=int(value["stale_after_days"]),
        record_hash=str(value["record_hash"]),
        scope=str(value["scope"]),
        dimension_values=tuple(str(item) for item in dimensions),
    )


def _cached_fold_window(value: Mapping[str, Any]) -> Any:
    return legacy._FoldWindow(
        fold_id=str(value["fold_id"]),
        train_end_date=str(value["train_end_date"]),
        test_start=str(value["test_start"]),
        test_end=str(value["test_end"]),
        purge_trading_days=int(value["purge_trading_days"]),
        embargo_trading_days=int(value["embargo_trading_days"]),
    )


def _discover(
    *,
    raw_manifest_path: Path,
    raw_manifest: Mapping[str, Any],
    cutoff: datetime,
    benchmark_entity_id: str,
    minimum_train_dates: int,
    test_date_count: int,
    purge_trading_days: int,
    embargo_trading_days: int,
    shared_block_store_root: Path | None = None,
    shared_contract: tuple[str, str, str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> _Discovery:
    base_definitions = legacy._base_feature_definitions(raw_manifest)
    runtime = dict(base_definitions)
    stock_dates: set[str] = set()
    benchmark_dates: set[str] = set()
    source_digest = hashlib.sha256()
    shard_by_year: dict[int, Mapping[str, Any]] = {}
    for shard in sorted(
        legacy._mapping_sequence(
            raw_manifest.get("shards"),
            field_name="shards",
        ),
        key=lambda item: int(item["year"]),
    ):
        year = int(shard["year"])
        if year in shard_by_year:
            raise ValueError("direct numeric requires one raw shard per year")
        shard_by_year[year] = shard
        shard_path = _resolve_direct_shard_path(
            raw_manifest_path=raw_manifest_path,
            shard=shard,
            shared_block_store_root=shared_block_store_root,
            shared_contract=shared_contract,
        )
        shard_digest = hashlib.sha256()
        row_count = 0
        value_count = 0
        last_reported_rows = 0
        last_reported_at_ns = time_module.monotonic_ns()
        with gzip.open(shard_path, "rb") as stream:
            for raw_line in stream:
                if not raw_line.strip():
                    continue
                source_digest.update(raw_line)
                shard_digest.update(raw_line)
                payload = json.loads(raw_line.decode("utf-8"))
                row = legacy._as_mapping(
                    payload,
                    field_name="raw observation",
                )
                if (
                    row.get("schema_version")
                    != "ml-pit-observation.v1"
                    or row.get("dataset_id")
                    != raw_manifest["dataset_id"]
                    or row.get("pit_status")
                    != "eligible_as_of_decision"
                ):
                    raise ValueError("invalid direct raw observation")
                expected_hash = str(row.get("source_row_hash", ""))
                body = dict(row)
                body.pop("source_row_hash", None)
                if legacy._sha256_json(body) != expected_hash:
                    raise ValueError("raw source_row_hash mismatch")
                table_name = str(row["source_table"])
                entity_id = str(row["entity_id"])
                event_date = str(row["event_at"])[:10]
                if table_name == "daily_prices":
                    stock_dates.add(event_date)
                elif (
                    table_name == "market_indices"
                    and entity_id == benchmark_entity_id
                ):
                    benchmark_dates.add(event_date)
                values = legacy._mapping_sequence(
                    row.get("values"),
                    field_name="values",
                )
                for value in values:
                    legacy._runtime_definition(
                        base_feature_id=str(value["feature_id"]),
                        table_name=table_name,
                        entity_id=entity_id,
                        definitions=runtime,
                    )
                row_count += 1
                value_count += len(values)
                if progress_callback is not None:
                    now_ns = time_module.monotonic_ns()
                    if (
                        row_count - last_reported_rows
                        >= _DISCOVERY_PROGRESS_INTERVAL
                        or (
                            row_count % _DISCOVERY_PROGRESS_CHECK_INTERVAL
                            == 0
                            and now_ns - last_reported_at_ns
                            >= _DISCOVERY_PROGRESS_MAX_SILENCE_NS
                        )
                    ):
                        progress_callback(
                            f"discovery_source_shard_{year}_rows_"
                            f"{row_count}_processed"
                        )
                        last_reported_rows = row_count
                        last_reported_at_ns = now_ns
        if _SHA256_PREFIX + shard_digest.hexdigest() != str(
            shard["content_sha256"]
        ):
            raise ValueError("raw shard content hash mismatch")
        if row_count != int(shard["row_count"]):
            raise ValueError("raw shard row_count mismatch")
        if value_count != int(shard["feature_value_count"]):
            raise ValueError("raw shard feature_value_count mismatch")
        if progress_callback is not None:
            progress_callback(
                f"discovery_source_shard_{year}_complete"
            )
    legacy._finalize_long_format_definitions(
        runtime_definitions=runtime,
        base_definitions=base_definitions,
    )
    definitions = tuple(
        sorted(runtime.values(), key=lambda item: item.feature_id)
    )
    feature_packs = legacy._feature_pack_payloads(definitions)
    feature_ids = tuple(
        feature_id
        for pack in feature_packs
        for feature_id in cast(Sequence[str], pack["feature_ids"])
    )
    scales_by_id = {
        definition.feature_id: definition.scale
        for definition in definitions
    }
    feature_scales = tuple(
        scales_by_id.get(feature_id, 1)
        for feature_id in feature_ids
    )
    calendar = tuple(sorted(benchmark_dates))
    positions = {value: index for index, value in enumerate(calendar)}
    eligible_dates = tuple(
        value
        for value in sorted(stock_dates & benchmark_dates)
        if positions[value] > 0
        and datetime.combine(
            date.fromisoformat(value),
            _DECISION_TIME,
            tzinfo=_TAIPEI,
        )
        <= cutoff
    )
    folds = legacy._build_fold_windows(
        eligible_dates,
        minimum_train_dates=minimum_train_dates,
        test_date_count=test_date_count,
        purge_trading_days=purge_trading_days,
        embargo_trading_days=embargo_trading_days,
    )
    if len(folds) < 4:
        raise ValueError("direct numeric store requires at least four folds")
    return _Discovery(
        definitions=definitions,
        feature_packs=feature_packs,
        feature_ids=feature_ids,
        feature_scales=feature_scales,
        calendar=calendar,
        eligible_dates=eligible_dates,
        fold_windows=folds,
        shard_by_year=shard_by_year,
        source_content_hash=(
            _SHA256_PREFIX + source_digest.hexdigest()
        ),
    )


def _sector_custody(
    path: Path | None,
    *,
    cutoff: datetime,
) -> tuple[str, int]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    legacy._initialize_spool(connection)
    try:
        return legacy._spool_sector_memberships(
            connection,
            path,
            training_as_of=cutoff,
        )
    finally:
        connection.close()


def _write_carry(path: Path, carry: Any) -> int:
    count = 0
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=6,
        fileobj=path.open("wb"),
        mtime=0,
    ) as stream:
        stream.write(
            (
                json.dumps(
                    {
                        "record_type": "carry_header",
                        "schema_version": DIRECT_CARRY_SCHEMA_VERSION,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\r\n"
            ).encode("utf-8")
        )
        for scope in sorted(carry):
            if scope == _CARRY_METADATA_KEY:
                continue
            for entity_key in sorted(carry[scope]):
                for feature_id in sorted(carry[scope][entity_key]):
                    current = carry[scope][entity_key][feature_id]
                    payload = {
                        "scope": scope,
                        "entity_key": entity_key,
                        "feature_id": feature_id,
                        **asdict(current),
                    }
                    stream.write(
                        (
                            json.dumps(
                                payload,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\r\n"
                        ).encode("utf-8")
                    )
                    count += 1
    return count


def _carry_identity_hash(carry: Mapping[str, Any]) -> str:
    """以可序列化的 canonical records 計算 carry-input semantic hash。"""

    entries: list[dict[str, Any]] = []
    for scope in sorted(str(item) for item in carry):
        if scope == _CARRY_METADATA_KEY:
            continue
        scope_values = carry[scope]
        if not isinstance(scope_values, Mapping):
            raise ValueError("direct carry scope must be an object")
        for entity_key in sorted(str(item) for item in scope_values):
            entity_values = scope_values[entity_key]
            if not isinstance(entity_values, Mapping):
                raise ValueError("direct carry entity must be an object")
            for feature_id in sorted(str(item) for item in entity_values):
                current = entity_values[feature_id]
                if isinstance(current, Mapping):
                    current_payload = dict(current)
                else:
                    current_payload = asdict(current)
                entries.append(
                    {
                        "scope": scope,
                        "entity_key": entity_key,
                        "feature_id": feature_id,
                        "value": current_payload,
                    }
                )
    return _sha256_json(
        {
            "schema_version": carry.get(_CARRY_METADATA_KEY),
            "entries": entries,
        }
    )


def _read_carry(path: Path) -> Any:
    result: Any = _empty_carry(carry_schema_version=None)
    header_seen = False
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            payload = json.loads(line)
            if payload.get("record_type") == "carry_header":
                if payload.get("schema_version") != DIRECT_CARRY_SCHEMA_VERSION:
                    raise ValueError("direct carry schema version mismatch")
                if header_seen:
                    raise ValueError("direct carry header is duplicated")
                header_seen = True
                result[_CARRY_METADATA_KEY] = DIRECT_CARRY_SCHEMA_VERSION
                continue
            scope = str(payload.pop("scope"))
            entity = str(payload.pop("entity_key"))
            feature_id = str(payload.pop("feature_id"))
            scope_values = result.setdefault(scope, {}).setdefault(entity, {})
            if feature_id in scope_values:
                raise ValueError("direct carry contains duplicate entry")
            if scope == DIRECT_REPLAY_VOLUME_CARRY_SCOPE:
                if set(payload) != {"price_event_at", "volume_shares"}:
                    raise ValueError(
                        "direct volume carry payload fields are invalid"
                    )
                scope_values[feature_id] = _VolumeHistoryCarryValue(
                    price_event_at=str(payload["price_event_at"]),
                    volume_shares=_require_nonnegative_volume(
                        payload["volume_shares"]
                    ),
                )
            else:
                scope_values[feature_id] = legacy._CurrentValue(**payload)
    return result


def _read_year_carry(
    *,
    year_directory: Path,
    year_manifest: Mapping[str, Any],
    shared_numeric_store_root: Path | None,
) -> Any:
    """從年度 local/shared artifact 讀取 carry，供 resume 與下一年 seed 使用。"""

    artifact_paths = resolve_direct_year_artifact_paths(
        year_manifest,
        year_directory=year_directory,
        shared_store_root=shared_numeric_store_root,
    )
    return _read_carry(artifact_paths["carry.state.gz"])


def _direct_label_contract_hash() -> str:
    return _sha256_json(
        {
            "version": DIRECT_LABEL_CONTRACT_VERSION,
            "horizons": list(legacy.SUPPORTED_HORIZONS),
            "target_fields": list(store_module.TARGET_FIELDS),
            "label_fields": list(store_module.LABEL_FIELDS),
        }
    )


def _accumulate_teacher_diagnostics(
    total: dict[str, int],
    year_manifest: Mapping[str, Any],
) -> None:
    """合併年度 teacher provenance；舊年度缺欄位時保持向下相容。"""

    raw = year_manifest.get("teacher_target_diagnostics")
    if raw is None:
        return
    if not isinstance(raw, Mapping):
        raise ValueError("teacher_target_diagnostics must be an object")
    for raw_key, raw_value in raw.items():
        key = str(raw_key)
        if (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, int)
            or raw_value < 0
        ):
            raise ValueError(
                "teacher_target_diagnostics values must be non-negative integers"
            )
        total[key] = total.get(key, 0) + raw_value


def _direct_year_source_hashes(
    *,
    year_ordinal: int,
    annual_dates: Sequence[str],
    source_shards: Sequence[Mapping[str, Any]],
    source_manifest_hashes: Sequence[tuple[str, str]],
    sector_manifest_hash: str,
    feature_registry_hash: str,
    corporate_custody: Any,
    portfolio_replay: Any,
    carry_input_hash: str,
    cutoff: datetime,
    benchmark_entity_id: str,
) -> tuple[tuple[str, str], ...]:
    """建立年度 key 的局部依賴；不綁 aggregate raw manifest hash。"""

    values: dict[str, str] = {
        "direct:annual-decision-dates": _sha256_json(list(annual_dates)),
        "direct:benchmark-entity": _sha256_json(benchmark_entity_id),
        "direct:carry-input": carry_input_hash,
        "direct:corporate-custody": _sha256_json(
            corporate_custody.custody_payload()
        ),
        "direct:feature-registry": feature_registry_hash,
        "direct:portfolio-replay-policy": _sha256_json(
            portfolio_replay.custody_payload()
        ),
        # 產業 membership 是 teacher／target eligibility 的輸入；必須成為
        # 年度 immutable key 的明確依賴，不能只由 aggregate manifest 間接帶入。
        "direct:sector-membership": sector_manifest_hash,
        "direct:source-contract-ids": _sha256_json(
            sorted(str(source_id) for source_id, _value in source_manifest_hashes)
        ),
        "direct:training-as-of": _sha256_json(cutoff.isoformat()),
        "direct:year-ordinal": _sha256_json(year_ordinal),
    }
    for shard in source_shards:
        shard_year = int(shard["year"])
        for hash_name in ("compressed_sha256", "content_sha256"):
            hash_value = shard.get(hash_name)
            if not isinstance(hash_value, str):
                raise ValueError(
                    f"direct source shard {hash_name} is missing for {shard_year}"
                )
            values[f"pit-shard:{shard_year}:{hash_name}"] = hash_value
    return tuple(sorted(values.items()))


def _direct_source_shard_custody(
    source_shards: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """將年度使用的 PIT shard 正規化成 descriptor 可比較的 custody。"""

    return [
        {
            "year": int(item["year"]),
            "path": _shard_lineage_path(item),
            "compressed_sha256": str(item["compressed_sha256"]),
            "content_sha256": str(item["content_sha256"]),
        }
        for item in source_shards
    ]


def _direct_source_shard_identity(
    source_shards: Sequence[Mapping[str, Any]],
) -> tuple[tuple[int, str, str], ...]:
    """回傳不含 local path 的 shard identity；registry 搬移不應使 key 失效。"""

    custody = _direct_source_shard_custody(source_shards)
    return tuple(
        (
            int(item["year"]),
            str(item["compressed_sha256"]),
            str(item["content_sha256"]),
        )
        for item in custody
    )


def _direct_artifact_encoding(
    *,
    artifact_id: str,
    row_count: int,
    feature_count: int,
) -> str:
    encodings = {
        "features.values.i64": f"numpy:<i8>:shape={row_count}x{feature_count}",
        "features.masks.u8": f"numpy:<u1>:shape={row_count}x{feature_count}",
        "targets.i32": f"numpy:<i4>:shape={row_count}x{len(store_module.TARGET_FIELDS)}",
        "labels.i32": (
            f"numpy:<i4>:shape={row_count}x{len(legacy.SUPPORTED_HORIZONS)}"
            f"x{len(store_module.LABEL_FIELDS)}"
        ),
        "labels.masks.u8": (
            f"numpy:<u1>:shape={row_count}x{len(legacy.SUPPORTED_HORIZONS)}"
            f"x{len(store_module.LABEL_FIELDS)}"
        ),
        "rows.sqlite": "sqlite:direct-rows.v1",
        "replay_source.sqlite": "sqlite:direct-replay-source.v1",
        "carry.state.gz": "gzip:direct-carry.v2",
    }
    try:
        return encodings[artifact_id]
    except KeyError as exc:
        raise ValueError(f"unsupported direct artifact encoding: {artifact_id}") from exc


def _direct_year_key_context(
    *,
    year: int,
    year_ordinal: int,
    annual_dates: Sequence[str],
    source_shards: Sequence[Mapping[str, Any]],
    raw_manifest: Mapping[str, Any],
    source_manifest_hashes: Sequence[tuple[str, str]],
    sector_manifest_hash: str,
    feature_registry_hash: str,
    cutoff: datetime,
    benchmark_entity_id: str,
    corporate_custody: Any,
    portfolio_replay: Any,
    carry_input_hash: str,
) -> tuple[tuple[tuple[str, str], ...], str, str, str]:
    if not annual_dates:
        raise ValueError(f"direct year {year} has no annual decision dates")
    source_hashes = _direct_year_source_hashes(
        year_ordinal=year_ordinal,
        annual_dates=annual_dates,
        source_shards=source_shards,
        source_manifest_hashes=source_manifest_hashes,
        sector_manifest_hash=sector_manifest_hash,
        feature_registry_hash=feature_registry_hash,
        corporate_custody=corporate_custody,
        portfolio_replay=portfolio_replay,
        carry_input_hash=carry_input_hash,
        cutoff=cutoff,
        benchmark_entity_id=benchmark_entity_id,
    )
    source_version = (
        f"dataset={str(raw_manifest.get('dataset_id', 'unknown'))};"
        f"year={year}"
    )
    return (
        source_hashes,
        source_version,
        str(annual_dates[0]),
        str(annual_dates[-1]),
    )


def _publish_direct_year_artifacts(
    *,
    staging: Path,
    year_manifest: dict[str, Any],
    year: int,
    year_ordinal: int,
    annual_dates: Sequence[str],
    source_shards: Sequence[Mapping[str, Any]],
    raw_manifest: Mapping[str, Any],
    source_manifest_hashes: Sequence[tuple[str, str]],
    sector_manifest_hash: str,
    feature_registry_hash: str,
    cutoff: datetime,
    benchmark_entity_id: str,
    corporate_custody: Any,
    portfolio_replay: Any,
    carry_input_hash: str,
    shared_store_root: Path,
    temporary_budget_bytes: int | None,
) -> dict[str, Any]:
    """發布年度 numeric files 並將 run manifest 改成 shared references。"""

    store_root = Path(shared_store_root).resolve()
    run_root = staging.parent.resolve()
    if (
        store_root == run_root
        or store_root in run_root.parents
        or run_root in store_root.parents
    ):
        raise ValueError(
            "shared numeric store must be outside the direct run directory"
        )
    raw_artifacts = year_manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ValueError("direct year artifacts must be a list before publication")
    row_count = int(year_manifest["row_count"])
    feature_count = int(year_manifest["feature_count"])
    (
        year_source_hashes,
        source_version,
        annual_start,
        annual_end,
    ) = _direct_year_key_context(
        year=year,
        year_ordinal=year_ordinal,
        annual_dates=annual_dates,
        source_shards=source_shards,
        raw_manifest=raw_manifest,
        source_manifest_hashes=source_manifest_hashes,
        sector_manifest_hash=sector_manifest_hash,
        feature_registry_hash=feature_registry_hash,
        cutoff=cutoff,
        benchmark_entity_id=benchmark_entity_id,
        corporate_custody=corporate_custody,
        portfolio_replay=portfolio_replay,
        carry_input_hash=carry_input_hash,
    )
    published_entries: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, Mapping):
            raise TypeError("direct year artifact entry must be an object")
        raw_path = raw_artifact.get("path")
        if not isinstance(raw_path, str) or Path(raw_path).parts != (Path(raw_path).name,):
            raise ValueError("direct year artifact path must be a root file name")
        artifact_id = Path(raw_path).name
        if artifact_id not in DIRECT_NUMERIC_ARTIFACT_IDS:
            raise ValueError(f"unsupported direct year artifact: {artifact_id}")
        if artifact_id in seen:
            raise ValueError(f"duplicate direct year artifact: {artifact_id}")
        seen.add(artifact_id)
        source_path = staging / artifact_id
        key = direct_numeric_artifact_key(
            artifact_id=artifact_id,
            year=year,
            source_version=source_version,
            source_manifest_hashes=year_source_hashes,
            feature_contract_hash=feature_registry_hash,
            label_contract_hash=_direct_label_contract_hash(),
            maturity_policy=DIRECT_NUMERIC_MATURITY_POLICY_VERSION,
            time_start=annual_start,
            time_end=annual_end,
            encoding=_direct_artifact_encoding(
                artifact_id=artifact_id,
                row_count=row_count,
                feature_count=feature_count,
            ),
        )
        result, entry = publish_direct_numeric_artifact(
            store_root=store_root,
            source_path=source_path,
            key=key,
            temporary_roots=(staging,),
            temporary_budget_bytes=temporary_budget_bytes,
        )
        published_entries.append(entry)
        telemetry.append(
            {
                "artifact_id": artifact_id,
                "status": str(result["status"]),
                "new_bytes_written": int(result["new_bytes_written"]),
                "object_hash": str(result["object_hash"]),
                "key_hash": str(result["key_hash"]),
            }
        )
    if seen != set(DIRECT_NUMERIC_ARTIFACT_IDS):
        raise ValueError(
            "direct year artifact set is incomplete before shared publication"
        )
    year_manifest["artifacts"] = published_entries
    year_manifest["artifact_storage"] = "immutable_shared"
    year_manifest["direct_source_semantic_hashes"] = [
        list(item) for item in year_source_hashes
    ]
    descriptor_payload = {
        "year": int(year_manifest["year"]),
        "year_ordinal": int(year_manifest["year_ordinal"]),
        "row_count": row_count,
        "feature_count": feature_count,
        "feature_values_shape": list(year_manifest["feature_values_shape"]),
        "feature_observed_counts": list(
            year_manifest["feature_observed_counts"]
        ),
        "target_shape": list(year_manifest["target_shape"]),
        "label_shape": list(year_manifest["label_shape"]),
        "feature_registry_hash": feature_registry_hash,
        "source_semantic_hashes": [
            list(item) for item in year_source_hashes
        ],
        "replay_source": dict(year_manifest["replay_source"]),
        "direct_source_shards": _direct_source_shard_custody(
            source_shards
        ),
        "carry_entry_count": int(year_manifest["carry_entry_count"]),
        "carry_schema_version": year_manifest["carry_schema_version"],
        "teacher_target_diagnostics": (
            dict(year_manifest["teacher_target_diagnostics"])
            if isinstance(
                year_manifest.get("teacher_target_diagnostics"),
                Mapping,
            )
            else {}
        ),
        "teacher_incomplete_decision_count": int(
            year_manifest["teacher_incomplete_decision_count"]
        ),
        "trade_restriction_unknown_row_count": int(
            year_manifest["trade_restriction_unknown_row_count"]
        ),
        "corporate_action_excluded_label_count": int(
            year_manifest["corporate_action_excluded_label_count"]
        ),
        "artifacts": published_entries,
    }
    descriptor_key = direct_numeric_year_descriptor_key(
        year=year,
        source_version=source_version,
        source_manifest_hashes=year_source_hashes,
        feature_contract_hash=feature_registry_hash,
        label_contract_hash=_direct_label_contract_hash(),
        maturity_policy=DIRECT_NUMERIC_MATURITY_POLICY_VERSION,
        time_start=annual_start,
        time_end=annual_end,
    )
    descriptor_result, descriptor_entry = publish_direct_year_descriptor(
        store_root=store_root,
        key=descriptor_key,
        payload=descriptor_payload,
    )
    year_manifest["shared_year_descriptor"] = descriptor_entry
    # 這是本次 run 的可稽核 telemetry；key 本身只由 immutable semantic
    # dependencies 決定，不能拿 status 欄位作為重用條件。
    year_manifest["shared_artifact_publication"] = {
        "schema_version": "portfolio-ml-direct-shared-publication.v1",
        "artifact_count": len(telemetry) + 1,
        "new_bytes_written": sum(
            int(item["new_bytes_written"]) for item in telemetry
        ) + int(descriptor_result["new_bytes_written"]),
        "statuses": sorted(
            telemetry
            + [
                {
                    "artifact_id": "year.descriptor.json",
                    "status": str(descriptor_result["status"]),
                    "new_bytes_written": int(
                        descriptor_result["new_bytes_written"]
                    ),
                    "object_hash": str(descriptor_result["object_hash"]),
                    "key_hash": str(descriptor_result["key_hash"]),
                }
            ],
            key=lambda item: str(item["artifact_id"]),
        ),
    }
    resolve_direct_year_artifact_paths(
        year_manifest,
        year_directory=staging,
        shared_store_root=store_root,
    )
    for artifact_id in DIRECT_NUMERIC_ARTIFACT_IDS:
        (staging / artifact_id).unlink(missing_ok=True)
    return dict(year_manifest["shared_artifact_publication"])


def _try_reuse_shared_year(
    *,
    year_directory: Path,
    year: int,
    year_ordinal: int,
    annual_dates: Sequence[str],
    source_shards: Sequence[Mapping[str, Any]],
    raw_manifest: Mapping[str, Any],
    source_manifest_hashes: Sequence[tuple[str, str]],
    sector_manifest_hash: str,
    feature_registry_hash: str,
    cutoff: datetime,
    benchmark_entity_id: str,
    corporate_custody: Any,
    portfolio_replay: Any,
    carry_input_hash: str,
    dataset_identity_hash: str,
    shared_store_root: Path,
) -> tuple[dict[str, Any], Any, int] | None:
    """在建立年度 workspace 前尋找 exact semantic descriptor。"""

    (
        year_source_hashes,
        source_version,
        annual_start,
        annual_end,
    ) = _direct_year_key_context(
        year=year,
        year_ordinal=year_ordinal,
        annual_dates=annual_dates,
        source_shards=source_shards,
        raw_manifest=raw_manifest,
        source_manifest_hashes=source_manifest_hashes,
        sector_manifest_hash=sector_manifest_hash,
        feature_registry_hash=feature_registry_hash,
        cutoff=cutoff,
        benchmark_entity_id=benchmark_entity_id,
        corporate_custody=corporate_custody,
        portfolio_replay=portfolio_replay,
        carry_input_hash=carry_input_hash,
    )
    descriptor_key = direct_numeric_year_descriptor_key(
        year=year,
        source_version=source_version,
        source_manifest_hashes=year_source_hashes,
        feature_contract_hash=feature_registry_hash,
        label_contract_hash=_direct_label_contract_hash(),
        maturity_policy=DIRECT_NUMERIC_MATURITY_POLICY_VERSION,
        time_start=annual_start,
        time_end=annual_end,
    )
    found = find_direct_year_descriptor(
        store_root=Path(shared_store_root).resolve(),
        key=descriptor_key,
    )
    if found is None:
        return None
    descriptor, descriptor_entry = found
    if (
        descriptor.get("year") != year
        or descriptor.get("year_ordinal") != year_ordinal
        or descriptor.get("feature_registry_hash") != feature_registry_hash
        or descriptor.get("source_semantic_hashes")
        != [list(item) for item in year_source_hashes]
        or _direct_source_shard_identity(
            descriptor.get("direct_source_shards", [])
            if isinstance(descriptor.get("direct_source_shards"), list)
            else []
        )
        != _direct_source_shard_identity(source_shards)
    ):
        raise ValueError("direct shared year descriptor semantic metadata mismatch")
    raw_artifacts = descriptor.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ValueError("direct shared year descriptor artifacts are missing")
    artifact_ids: set[str] = set()
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, Mapping):
            raise TypeError("direct shared year descriptor artifact is invalid")
        artifact_id = raw_artifact.get("artifact_id")
        if (
            not isinstance(artifact_id, str)
            or artifact_id not in DIRECT_NUMERIC_ARTIFACT_IDS
            or artifact_id in artifact_ids
        ):
            raise ValueError(
                "direct shared year descriptor artifact set is invalid"
            )
        artifact_ids.add(artifact_id)
    if artifact_ids != set(DIRECT_NUMERIC_ARTIFACT_IDS):
        raise ValueError(
            "direct shared year descriptor artifact set is incomplete"
        )
    row_count = int(descriptor["row_count"])
    feature_count = int(descriptor["feature_count"])
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, Mapping):
            raise TypeError("direct shared year descriptor artifact is invalid")
        artifact_id = raw_artifact.get("artifact_id")
        if not isinstance(artifact_id, str):
            raise ValueError("direct shared year descriptor artifact id is missing")
        expected_key = direct_numeric_artifact_key(
            artifact_id=artifact_id,
            year=year,
            source_version=source_version,
            source_manifest_hashes=year_source_hashes,
            feature_contract_hash=feature_registry_hash,
            label_contract_hash=_direct_label_contract_hash(),
            maturity_policy=DIRECT_NUMERIC_MATURITY_POLICY_VERSION,
            time_start=annual_start,
            time_end=annual_end,
            encoding=_direct_artifact_encoding(
                artifact_id=artifact_id,
                row_count=row_count,
                feature_count=feature_count,
            ),
        )
        reference = raw_artifact.get("block_reference")
        if not isinstance(reference, Mapping) or reference.get("key") != expected_key.payload():
            raise ValueError(
                "direct shared year descriptor artifact semantic key mismatch"
            )
    shared_manifest = {
        "schema_version": store_module.YEAR_SCHEMA_VERSION,
        "year": year,
        "year_ordinal": year_ordinal,
        "row_count": row_count,
        "feature_count": feature_count,
        "dataset_identity_hash": dataset_identity_hash,
        "feature_registry_hash": feature_registry_hash,
        "source_manifest_hashes": [list(item) for item in source_manifest_hashes],
        "direct_source_semantic_hashes": [
            list(item) for item in year_source_hashes
        ],
        "feature_values_shape": list(descriptor["feature_values_shape"]),
        "feature_observed_counts": list(descriptor["feature_observed_counts"]),
        "target_shape": list(descriptor["target_shape"]),
        "label_shape": list(descriptor["label_shape"]),
        "replay_source": dict(descriptor["replay_source"]),
        "direct_source_shards": _direct_source_shard_custody(source_shards),
        "carry_entry_count": int(descriptor["carry_entry_count"]),
        "carry_schema_version": descriptor["carry_schema_version"],
        "teacher_target_diagnostics": (
            dict(descriptor["teacher_target_diagnostics"])
            if isinstance(
                descriptor.get("teacher_target_diagnostics"),
                Mapping,
            )
            else {}
        ),
        "teacher_incomplete_decision_count": int(
            descriptor["teacher_incomplete_decision_count"]
        ),
        "trade_restriction_unknown_row_count": int(
            descriptor["trade_restriction_unknown_row_count"]
        ),
        "corporate_action_excluded_label_count": int(
            descriptor["corporate_action_excluded_label_count"]
        ),
        "artifacts": [dict(item) for item in raw_artifacts],
        "artifact_storage": "immutable_shared",
        "shared_year_descriptor": descriptor_entry,
        "shared_artifact_publication": {
            "schema_version": "portfolio-ml-direct-shared-publication.v1",
            "artifact_count": len(raw_artifacts) + 1,
            "new_bytes_written": 0,
            "reuse_before_build": True,
            "statuses": [
                {
                    "artifact_id": artifact_id,
                    "status": "immutable_block_reused_before_build",
                    "new_bytes_written": 0,
                    "object_hash": str(
                        raw_artifact["file_sha256"]
                    ),
                    "key_hash": str(
                        raw_artifact["block_reference"]["key_hash"]
                    ),
                }
                for artifact_id, raw_artifact in sorted(
                    (
                        (str(item["artifact_id"]), item)
                        for item in raw_artifacts
                    ),
                    key=lambda item: item[0],
                )
            ]
            + [
                {
                    "artifact_id": "year.descriptor.json",
                    "status": "immutable_block_reused_before_build",
                    "new_bytes_written": 0,
                    "object_hash": str(descriptor_entry["file_sha256"]),
                    "key_hash": str(
                        descriptor_entry["block_reference"]["key_hash"]
                    ),
                }
            ],
        },
        "complete": True,
    }
    resolve_direct_year_descriptor(
        descriptor_entry,
        shared_store_root=Path(shared_store_root).resolve(),
    )
    resolve_direct_year_artifact_paths(
        shared_manifest,
        year_directory=year_directory,
        shared_store_root=Path(shared_store_root).resolve(),
    )
    year_directory.mkdir(parents=True, exist_ok=False)
    shared_manifest["manifest_hash"] = _sha256_json(shared_manifest)
    _write_json(year_directory / "manifest.json", shared_manifest)
    carry = _read_year_carry(
        year_directory=year_directory,
        year_manifest=shared_manifest,
        shared_numeric_store_root=Path(shared_store_root).resolve(),
    )
    return shared_manifest, carry, 0


def _empty_carry(*, carry_schema_version: str | None = DIRECT_CARRY_SCHEMA_VERSION) -> dict[str, Any]:
    return {
        "stock": {},
        "market": {},
        "industry": {},
        DIRECT_REPLAY_VOLUME_CARRY_SCOPE: {},
        _CARRY_METADATA_KEY: carry_schema_version,
    }


def _volume_history_from_carry(
    carry: Mapping[str, Any],
) -> dict[str, tuple[tuple[str, int], ...]]:
    raw_scope = carry.get(DIRECT_REPLAY_VOLUME_CARRY_SCOPE, {})
    if not isinstance(raw_scope, Mapping):
        raise ValueError("direct replay volume carry scope must be an object")
    result: dict[str, tuple[tuple[str, int], ...]] = {}
    for raw_symbol, raw_events in raw_scope.items():
        if not isinstance(raw_events, Mapping):
            raise ValueError("direct replay volume carry events must be an object")
        if len(raw_events) > _VOLUME_WINDOW_SIZE:
            raise ValueError("direct volume carry exceeds bounded 20-event window")
        events: list[tuple[str, int]] = []
        for raw_event_at, raw_value in raw_events.items():
            volume: object
            if isinstance(raw_value, _VolumeHistoryCarryValue):
                event_at = raw_value.price_event_at
                volume = raw_value.volume_shares
            elif isinstance(raw_value, Mapping):
                event_at = str(raw_value.get("price_event_at", raw_event_at))
                volume = raw_value.get("volume_shares")
            else:
                raise ValueError("direct replay volume carry event is invalid")
            if event_at != str(raw_event_at):
                raise ValueError("direct replay volume carry event key mismatch")
            canonical_event_at = _canonical_volume_event_at(event_at)
            if canonical_event_at != event_at:
                raise ValueError(
                    "direct replay volume carry event timestamp is not canonical"
                )
            events.append((event_at, _require_nonnegative_volume(volume)))
        result[str(raw_symbol)] = tuple(events)
    return result


def _canonical_volume_event_at(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("volume price_event_at must be a timestamp")
    return legacy._available_datetime(
        value.strip(),
        field_name="direct replay volume price_event_at",
    ).isoformat()


def _volume_event_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("volume price_event_at must be a timestamp")
    return legacy._available_datetime(
        value.strip(),
        field_name="direct replay volume price_event_at",
    )


def _require_nonnegative_volume(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("volume_shares must be a non-negative integer")
    if value < 0:
        raise ValueError("volume_shares must be a non-negative integer")
    return value


def _eligible_current_int(value: object) -> int | None:
    if value is None:
        return None
    if (
        not bool(getattr(value, "formal_training_eligible", False))
        or bool(getattr(value, "missing_mask", True))
        or bool(getattr(value, "quality_blocked_mask", True))
    ):
        return None
    raw = getattr(value, "value_int", None)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError("replay source value_int must be integer or null")
    return raw


def _eligible_current_scale(value: object) -> int | None:
    if _eligible_current_int(value) is None:
        return None
    raw = getattr(value, "scale", None)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise TypeError("replay source scale must be positive integer")
    return raw


def _relative_score_bp(
    numerator_value: object,
    denominator_value: object,
) -> int | None:
    numerator_int = _eligible_current_int(numerator_value)
    denominator_int = _eligible_current_int(denominator_value)
    numerator_scale = _eligible_current_scale(numerator_value)
    denominator_scale = _eligible_current_scale(denominator_value)
    if (
        numerator_int is None
        or denominator_int is None
        or numerator_scale is None
        or denominator_scale is None
        or denominator_int <= 0
    ):
        return None
    numerator = Decimal(numerator_int) / Decimal(numerator_scale)
    denominator = Decimal(denominator_int) / Decimal(denominator_scale)
    return int(
        (
            (numerator / denominator - Decimal(1))
            * Decimal(10_000)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    )


def _load_checkpoint(
    *,
    path: Path,
    run_id: str,
    raw_manifest_hash: str,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema_version": DIRECT_CHECKPOINT_SCHEMA_VERSION,
            "run_id": run_id,
            "raw_manifest_hash": raw_manifest_hash,
            "completed_years": [],
            "peak_temporary_bytes": 0,
            "complete": False,
        }
    payload = _read_json(path)
    if (
        payload.get("schema_version")
        != DIRECT_CHECKPOINT_SCHEMA_VERSION
        or payload.get("run_id") != run_id
        or payload.get("raw_manifest_hash") != raw_manifest_hash
    ):
        raise ValueError("direct checkpoint identity mismatch")
    return payload


def _checkpointed_year_is_valid(
    *,
    year_directory: Path,
    checkpoint_entry: Mapping[str, Any],
    shared_numeric_store_root: Path | None = None,
) -> bool:
    manifest_path = year_directory / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        year_manifest = _read_json(manifest_path)
        if not _validate_direct_year_manifest(
            year_manifest=year_manifest,
            year_directory=year_directory,
            shared_numeric_store_root=shared_numeric_store_root,
        ):
            return False
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    try:
        carry = _read_year_carry(
            year_directory=year_directory,
            year_manifest=year_manifest,
            shared_numeric_store_root=shared_numeric_store_root,
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if carry.get(_CARRY_METADATA_KEY) != DIRECT_CARRY_SCHEMA_VERSION:
        return False
    carry_file_hash = _year_carry_file_hash(
        year_directory=year_directory,
        year_manifest=year_manifest,
    )
    return (
        checkpoint_entry.get("manifest_file_hash")
        == _file_sha256(manifest_path)
        and checkpoint_entry.get("carry_file_hash")
        == carry_file_hash
    )


def _completed_year_entry(
    *,
    year: int,
    year_directory: Path,
    year_manifest: Mapping[str, Any],
    shared_numeric_store_root: Path | None = None,
) -> dict[str, Any]:
    del shared_numeric_store_root
    return {
        "year": year,
        "manifest_hash": year_manifest["manifest_hash"],
        "manifest_file_hash": _file_sha256(
            year_directory / "manifest.json"
        ),
        "carry_file_hash": _year_carry_file_hash(
            year_directory=year_directory,
            year_manifest=year_manifest,
        ),
    }


def _year_carry_file_hash(
    *,
    year_directory: Path,
    year_manifest: Mapping[str, Any],
) -> str:
    raw_artifacts = year_manifest.get("artifacts")
    if isinstance(raw_artifacts, (list, tuple)):
        for raw_artifact in raw_artifacts:
            if not isinstance(raw_artifact, Mapping):
                continue
            artifact_id = raw_artifact.get("artifact_id")
            if artifact_id is None and isinstance(raw_artifact.get("path"), str):
                artifact_id = Path(str(raw_artifact["path"])).name
            if artifact_id == "carry.state.gz":
                file_hash = raw_artifact.get("file_sha256")
                if isinstance(file_hash, str):
                    return file_hash
    carry_path = year_directory / "carry.state.gz"
    if not carry_path.is_file():
        raise FileNotFoundError(carry_path)
    return _file_sha256(carry_path)


def _validate_direct_year_manifest(
    *,
    year_manifest: Mapping[str, Any],
    year_directory: Path,
    shared_numeric_store_root: Path | None,
) -> bool:
    if year_manifest.get("schema_version") != store_module.YEAR_SCHEMA_VERSION:
        return False
    if year_manifest.get("complete") is not True:
        return False
    expected_hash = year_manifest.get("manifest_hash")
    if not isinstance(expected_hash, str):
        return False
    body = dict(year_manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_hash:
        return False
    if year_manifest.get("artifact_storage") == "immutable_shared":
        if shared_numeric_store_root is None:
            return False
        descriptor_entry = year_manifest.get("shared_year_descriptor")
        if not isinstance(descriptor_entry, Mapping):
            return False
        try:
            descriptor = resolve_direct_year_descriptor(
                descriptor_entry,
                shared_store_root=shared_numeric_store_root,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if (
            descriptor.get("year") != year_manifest.get("year")
            or descriptor.get("year_ordinal")
            != year_manifest.get("year_ordinal")
            or descriptor.get("feature_registry_hash")
            != year_manifest.get("feature_registry_hash")
            or descriptor.get("source_semantic_hashes")
            != year_manifest.get("direct_source_semantic_hashes")
        ):
            return False
    resolve_direct_year_artifact_paths(
        year_manifest,
        year_directory=year_directory,
        shared_store_root=shared_numeric_store_root,
    )
    return True


def _validate_completed_direct_store(
    *,
    manifest: Mapping[str, Any],
    run_directory: Path,
    expected_identity: Mapping[str, Any],
    shared_numeric_store_root: Path | None,
) -> None:
    if manifest.get("schema_version") != store_module.STORE_SCHEMA_VERSION:
        raise ValueError("existing direct store schema mismatch")
    if manifest.get("status") != "complete":
        raise ValueError("existing direct store is not complete")
    if _canonical_json(manifest.get("store_identity")) != _canonical_json(
        expected_identity
    ):
        raise ValueError("existing direct store identity mismatch")
    expected_hash = manifest.get("manifest_hash")
    if not isinstance(expected_hash, str):
        raise ValueError("existing direct store manifest hash is missing")
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_hash:
        raise ValueError("existing direct store manifest hash mismatch")
    for year_manifest in legacy._mapping_sequence(
        manifest.get("years"),
        field_name="years",
    ):
        year = int(year_manifest["year"])
        if not _validate_direct_year_manifest(
            year_manifest=year_manifest,
            year_directory=run_directory / f"year={year:04d}",
            shared_numeric_store_root=shared_numeric_store_root,
        ):
            raise ValueError("existing direct year custody mismatch")
    for fold_manifest in legacy._mapping_sequence(
        manifest.get("folds"),
        field_name="folds",
    ):
        if not store_module._verify_fold_manifest(
            fold_manifest,
            folds_directory=run_directory / "folds",
        ):
            raise ValueError("existing direct fold custody mismatch")


def _adopt_finalized_year(
    *,
    year_directory: Path,
    year: int,
    year_ordinal: int,
    discovery: _Discovery,
    dataset_identity_hash: str,
    feature_registry_hash: str,
    shared_numeric_store_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """採納已原子 rename、但 checkpoint 尚未落盤的完整年度。

    這是 ``os.replace(staging, final)`` 與 outer checkpoint 寫入之間的
    crash recovery。只有所有 artifact、carry 與本次 dataset identity
    完全相符時才採納；否則 fail closed，絕不覆寫既有 finalized directory。
    """

    manifest_path = year_directory / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            f"uncheckpointed finalized year {year} is incomplete"
        )
    manifest = _read_json(manifest_path)
    expected_shards = [dict(discovery.shard_by_year[year])]
    if year + 1 in discovery.shard_by_year:
        expected_shards.append(dict(discovery.shard_by_year[year + 1]))
    expected_shard_custody = [
        {
            "year": int(item["year"]),
            "path": _shard_lineage_path(item),
            "compressed_sha256": item["compressed_sha256"],
            "content_sha256": item["content_sha256"],
        }
        for item in expected_shards
    ]
    identity_matches = (
        manifest.get("schema_version") == store_module.YEAR_SCHEMA_VERSION
        and manifest.get("complete") is True
        and manifest.get("year") == year
        and manifest.get("year_ordinal") == year_ordinal
        and manifest.get("feature_count") == len(discovery.feature_ids)
        and manifest.get("dataset_identity_hash") == dataset_identity_hash
        and manifest.get("feature_registry_hash") == feature_registry_hash
        and manifest.get("carry_schema_version")
        == DIRECT_CARRY_SCHEMA_VERSION
        and isinstance(manifest.get("replay_source"), Mapping)
        and manifest["replay_source"].get(
            "volume_history_carry_policy_version"
        )
        == DIRECT_REPLAY_VOLUME_POLICY_VERSION
        and manifest.get("direct_source_shards") == expected_shard_custody
    )
    expected_manifest_hash = str(manifest.get("manifest_hash", ""))
    if (
        not identity_matches
        or not _validate_direct_year_manifest(
            year_manifest=manifest,
            year_directory=year_directory,
            shared_numeric_store_root=shared_numeric_store_root,
        )
        or expected_manifest_hash != manifest.get("manifest_hash")
    ):
        raise RuntimeError(
            f"uncheckpointed finalized year {year} failed custody validation"
        )
    try:
        carry = _read_year_carry(
            year_directory=year_directory,
            year_manifest=manifest,
            shared_numeric_store_root=shared_numeric_store_root,
        )
        if carry.get(_CARRY_METADATA_KEY) != DIRECT_CARRY_SCHEMA_VERSION:
            raise ValueError("direct finalized year carry schema is not current")
        _volume_history_from_carry(carry)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"uncheckpointed finalized year {year} carry failed custody validation"
        ) from exc
    entry = _completed_year_entry(
        year=year,
        year_directory=year_directory,
        year_manifest=manifest,
        shared_numeric_store_root=shared_numeric_store_root,
    )
    return manifest, entry


def _write_incomplete_checkpoint(
    *,
    checkpoint_path: Path,
    run_id: str,
    raw_manifest_hash: str,
    completed: Mapping[int, Mapping[str, Any]],
    peak_temporary_bytes: int,
    capacity_preflight: Mapping[str, Any] | None = None,
    failure: Mapping[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": DIRECT_CHECKPOINT_SCHEMA_VERSION,
        "run_id": run_id,
        "raw_manifest_hash": raw_manifest_hash,
        "completed_years": [
            dict(completed[key]) for key in sorted(completed)
        ],
        "peak_temporary_bytes": peak_temporary_bytes,
        "complete": False,
    }
    if capacity_preflight is not None:
        payload["capacity_preflight"] = dict(capacity_preflight)
    if failure is not None:
        payload["failure"] = dict(failure)
    _atomic_write_json(
        checkpoint_path,
        payload,
    )


def _write_heartbeat(
    *,
    path: Path,
    run_id: str,
    raw_manifest_hash: str,
    status: str,
    stage: str,
    completed_years: Sequence[int],
    current_year: int | None = None,
    year_ordinal: int | None = None,
) -> None:
    """Publish a small, fail-closed progress heartbeat for supervisors.

    The checkpoint remains the completion authority.  This sidecar only makes
    a long-running annual build observable without opening the SQLite work
    file or guessing from process CPU usage.  Consumers must still verify the
    PID and checkpoint/manifest custody before treating a run as complete.
    """

    payload: dict[str, Any] = {
        "schema_version": DIRECT_HEARTBEAT_SCHEMA_VERSION,
        "run_id": run_id,
        "raw_manifest_hash": raw_manifest_hash,
        "pid": os.getpid(),
        "status": status,
        "stage": stage,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_years": sorted(int(year) for year in completed_years),
    }
    if current_year is not None:
        payload["current_year"] = int(current_year)
    if year_ordinal is not None:
        payload["year_ordinal"] = int(year_ordinal)
    _atomic_write_json(path, payload)


def _preflight_temporary_budget(
    *,
    shards: Sequence[Mapping[str, Any]],
    feature_count: int,
    budget_bytes: int | None,
) -> dict[str, Any]:
    ordered = sorted(shards, key=lambda item: int(item["year"]))
    estimates = tuple(
        _temporary_year_estimate(
            current=item,
            following=(
                ordered[index + 1]
                if index + 1 < len(ordered)
                else None
            ),
            feature_count=feature_count,
        )
        for index, item in enumerate(ordered)
    )
    peak = max(
        estimates,
        key=lambda item: int(item["estimated_peak_bytes"]),
    )
    estimated_peak = int(peak["estimated_peak_bytes"])
    payload = {
        "estimation_policy": (
            "annual_two_shard_compressed_plus_conservative_"
            "row_value_sqlite_and_numeric_staging_v1"
        ),
        "estimated_peak_bytes": estimated_peak,
        "peak_year": int(peak["year"]),
        "annual_estimates": list(estimates),
        "budget_bytes": budget_bytes,
        "within_budget": (
            budget_bytes is None or estimated_peak <= budget_bytes
        ),
    }
    if budget_bytes is not None and estimated_peak > budget_bytes:
        raise ValueError(
            "temporary storage budget is below conservative annual "
            f"workspace estimate: {budget_bytes} < {estimated_peak} "
            f"(peak year {peak['year']})"
        )
    return payload


def _capacity_budget_for_request(
    request: PortfolioMLDirectNumericRequest,
) -> MLStorageCapacityBudget:
    persistent_budget = request.persistent_storage_budget_bytes
    if persistent_budget is None:
        persistent_budget = request.persistent_new_bytes_budget
    return heavy_chain_capacity_budget(
        persistent_new_bytes_budget=persistent_budget,
        temporary_peak_bytes_budget=request.temporary_storage_budget_bytes,
        safety_reserve_bytes=request.safety_reserve_bytes,
    )


def _estimate_persistent_new_bytes(
    *,
    shards: Sequence[Mapping[str, Any]],
    feature_count: int,
    horizon_count: int,
) -> int:
    """保守估算一個 direct run 會新增的持久 artifacts 大小。

    估算只使用 raw shard manifest 的整數 row／byte 計數，不讀取或修改
    正式資料。完成後每年會再以實際 run directory 大小重新 preflight。
    """

    if feature_count < 0 or horizon_count < 0:
        raise ValueError("feature_count and horizon_count must be non-negative")
    rows = sum(int(item.get("row_count", 0)) for item in shards)
    compressed = sum(int(item.get("compressed_bytes", 0)) for item in shards)
    # values/masks/targets/labels/row custody 的固定 dtype 空間，再加上
    # SQLite 與 manifest/carry 的寬裕；所有係數刻意取整數保守上估。
    numeric_bytes_per_row = (
        feature_count * (8 + 1)
        + 6 * 4
        + horizon_count * 9 * 4
        + 256
    )
    metadata_margin = max(16 * 1024 * 1024, compressed // 10)
    return rows * numeric_bytes_per_row + metadata_margin


def _temporary_year_estimate(
    *,
    current: Mapping[str, Any],
    following: Mapping[str, Any] | None,
    feature_count: int,
) -> dict[str, int]:
    pair = (current,) if following is None else (current, following)
    compressed_bytes = sum(
        int(item.get("compressed_bytes", 0)) for item in pair
    )
    row_count = sum(int(item.get("row_count", 0)) for item in pair)
    feature_value_count = sum(
        int(item.get("feature_value_count", 0)) for item in pair
    )
    sqlite_estimate = (
        row_count * 384
        + feature_value_count * 224
        + compressed_bytes * 2
    )
    current_rows = int(current.get("row_count", 0))
    numeric_staging_estimate = current_rows * (
        feature_count * 9 + 512
    )
    safety_margin = max(512 * 1024 * 1024, compressed_bytes)
    return {
        "year": int(current["year"]),
        "compressed_pair_bytes": compressed_bytes,
        "row_count_pair": row_count,
        "feature_value_count_pair": feature_value_count,
        "sqlite_estimate_bytes": sqlite_estimate,
        "numeric_staging_estimate_bytes": numeric_staging_estimate,
        "safety_margin_bytes": safety_margin,
        "estimated_peak_bytes": (
            sqlite_estimate
            + numeric_staging_estimate
            + safety_margin
        ),
    }


def _enforce_temporary_budget(
    *,
    observed_bytes: int,
    budget_bytes: int | None,
) -> None:
    if budget_bytes is not None and observed_bytes > budget_bytes:
        raise RuntimeError(
            "temporary storage budget exceeded: "
            f"{observed_bytes} > {budget_bytes}"
        )


def _enforce_workspace_budget(
    *,
    roots: Sequence[Path],
    budget_bytes: int | None,
    stage: str,
) -> int:
    observed_bytes = sum(_directory_size_bytes(root) for root in roots)
    if budget_bytes is not None and observed_bytes > budget_bytes:
        raise RuntimeError(
            "temporary storage budget exceeded during "
            f"{stage}: {observed_bytes} > {budget_bytes}"
        )
    return observed_bytes


def _publication(
    *,
    run_id: str,
    run_directory: Path,
    manifest_path: Path,
    latest_path: Path,
    manifest: Mapping[str, Any],
) -> PortfolioMLDirectNumericPublication:
    return PortfolioMLDirectNumericPublication(
        run_id=run_id,
        run_directory=run_directory,
        manifest_path=manifest_path,
        latest_manifest_path=latest_path,
        manifest_hash=str(manifest["manifest_hash"]),
        manifest_file_hash=_file_sha256(manifest_path),
        row_count=int(manifest["row_count"]),
        feature_count=int(manifest["feature_count"]),
        fold_count=int(manifest["fold_count"]),
        full_market_ready=bool(
            cast(Mapping[str, Any], manifest["execution"])[
                "full_market_ready"
            ]
        ),
        readiness_failed_checks=tuple(
            str(item)
            for item in cast(
                Sequence[object],
                cast(Mapping[str, Any], manifest["execution"])[
                    "readiness_failed_checks"
                ],
            )
        ),
    )


def _optional_file_hash(path: Path | None) -> str | None:
    return None if path is None else _file_sha256(path.resolve())


def _mapping_sequence(
    value: object,
    *,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be list")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{field_name} items must be objects")
        result.append(item)
    return tuple(result)


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be object")
    return value


def _sequence(value: object, *, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be list")
    return tuple(value)


def _directory_size_bytes(root: Path) -> int:
    return sum(
        path.stat().st_size
        for path in root.rglob("*")
        if path.is_file()
    )


def _current_rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        return None


def _safe_remove_tree(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("refusing to remove outside direct run root")
    for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
        try:
            shutil.rmtree(resolved)
            return
        except PermissionError:
            if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                raise
            time_module.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)


def _replace_directory_with_retry(staging: Path, final: Path) -> None:
    """Atomically publish one annual directory across transient Win32 locks."""

    for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
        try:
            os.replace(staging, final)
            return
        except PermissionError:
            if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                raise
            time_module.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)


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
    with path.open("w", encoding="utf-8", newline="\r\n") as stream:
        json.dump(
            payload,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        stream.write("\r\n")
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        _write_json(temporary, payload)
        for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                    raise
                time_module.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        temporary.unlink(missing_ok=True)
