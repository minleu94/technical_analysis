"""Raw PIT 年度 shards 直接建立 numeric OOC store。

本模組刻意不發布 ``portfolio-ml-training-shards`` JSONL，也不建立跨年度
observation SQLite。每次只開啟一個年度工作資料庫，載入當年 observation 與
下一年度（供最長 60 日標籤）的價格資料，然後直接串流寫出固定 dtype binary
artifacts。年度完成後保存 compact causal feature carry、原子封存並刪除工作庫。
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_EVEN
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Mapping, Sequence, cast
from zoneinfo import ZoneInfo

import numpy as np

from data_module import portfolio_ml_dataset_assembler as legacy
from data_module import portfolio_ml_out_of_core_store as store_module
from ml_module.allocation_training_service import AllocationTrainingSample


DIRECT_SCHEMA_VERSION = "portfolio-ml-direct-numeric.v2"
DIRECT_CHECKPOINT_SCHEMA_VERSION = "portfolio-ml-direct-checkpoint.v2"
_TAIPEI = ZoneInfo("Asia/Taipei")
_DECISION_TIME = time(hour=8, minute=30)
_SHA256_PREFIX = "sha256:"
_REPLAY_SOURCE_SCHEMA_VERSION = "portfolio-ml-replay-source.v1"
_PRICE_OPEN_FEATURE_ID = "daily_prices.開盤價"
_PRICE_CLOSE_FEATURE_ID = "daily_prices.收盤價"
_PRICE_VOLUME_FEATURE_ID = "daily_prices.成交股數"
_RULE_MA20_FEATURE_ID = "technical_indicators.MA20"


@dataclass(frozen=True)
class PortfolioMLDirectNumericRequest:
    raw_manifest_path: Path
    output_root: Path
    training_as_of: str
    benchmark_entity_id: str
    sector_membership_path: Path | None = None
    corporate_action_manifest_path: Path | None = None
    minimum_train_dates: int = 252
    test_date_count: int = 63
    purge_trading_days: int = 60
    embargo_trading_days: int = 5
    batch_size: int = 8_192
    workers: int = 1
    memory_budget_mb: int = 4_096
    temporary_storage_budget_bytes: int | None = None
    resume: bool = True

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
            minimum_train_dates=self.minimum_train_dates,
            test_date_count=self.test_date_count,
            purge_trading_days=self.purge_trading_days,
            embargo_trading_days=self.embargo_trading_days,
            batch_size=self.batch_size,
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


class PortfolioMLDirectNumericStoreBuilder:
    """逐年 bounded workspace、manifest-last 的 direct numeric builder。"""

    def build(
        self,
        request: PortfolioMLDirectNumericRequest,
    ) -> PortfolioMLDirectNumericPublication:
        memory_guard = _MemoryBudgetGuard.create(request.memory_budget_mb)
        raw_path = request.raw_manifest_path.resolve()
        raw_manifest = legacy._read_json(raw_path)
        legacy._validate_raw_dataset_manifest(raw_manifest)
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
        }
        run_id = "direct-ooc-" + _sha256_json(direct_identity)[7:31]
        output_root = request.output_root.resolve()
        runs_root = output_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        run_directory = runs_root / run_id
        run_directory.mkdir(parents=True, exist_ok=True)
        manifest_path = run_directory / "manifest.json"
        latest_path = output_root / "latest_manifest.json"

        discovery = _discover(
            raw_manifest_path=raw_path,
            raw_manifest=raw_manifest,
            cutoff=cutoff,
            benchmark_entity_id=request.benchmark_entity_id,
            minimum_train_dates=request.minimum_train_dates,
            test_date_count=request.test_date_count,
            purge_trading_days=request.purge_trading_days,
            embargo_trading_days=request.embargo_trading_days,
        )
        memory_guard.observe(stage="raw_discovery_complete")
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
        portfolio_replay = legacy._build_cash_only_portfolio_state_replay(
            calendar=discovery.calendar,
            decision_dates=discovery.eligible_dates,
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
            store_module._validate_completed_store(
                manifest=existing_manifest,
                run_directory=run_directory,
                expected_identity=store_identity,
            )
            store_module._write_latest_pointer(
                latest_manifest_path=latest_path,
                run_id=run_id,
                manifest=existing_manifest,
            )
            return _publication(
                run_id=run_id,
                run_directory=run_directory,
                manifest_path=manifest_path,
                latest_path=latest_path,
                manifest=existing_manifest,
            )
        if not request.resume and any(run_directory.iterdir()):
            raise FileExistsError(
                "incomplete direct numeric run exists and resume=false"
            )

        temporary_preflight = _preflight_temporary_budget(
            shards=tuple(discovery.shard_by_year.values()),
            feature_count=len(discovery.feature_ids),
            budget_bytes=request.temporary_storage_budget_bytes,
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
        carry: Any = {
            "stock": {},
            "market": {},
            "industry": {},
        }
        peak_temporary_bytes = int(
            checkpoint.get("peak_temporary_bytes", 0)
        )
        total_corporate_exclusions = 0
        total_teacher_incomplete = 0
        year_manifests: list[dict[str, Any]] = []
        years = tuple(sorted(discovery.shard_by_year))
        for ordinal, year in enumerate(years):
            year_directory = run_directory / f"year={year:04d}"
            existing_year = completed.get(year)
            if (
                existing_year is not None
                and _checkpointed_year_is_valid(
                    year_directory=year_directory,
                    checkpoint_entry=existing_year,
                )
            ):
                year_manifest = _read_json(
                    year_directory / "manifest.json"
                )
                year_manifests.append(year_manifest)
                carry = _read_carry(year_directory / "carry.state.gz")
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
                )
                completed[year] = adopted_entry
                _write_incomplete_checkpoint(
                    checkpoint_path=checkpoint_path,
                    run_id=run_id,
                    raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                    completed=completed,
                    peak_temporary_bytes=peak_temporary_bytes,
                )
                year_manifests.append(year_manifest)
                carry = _read_carry(year_directory / "carry.state.gz")
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
                memory_guard.observe(
                    stage=f"year_{year}_checkpoint_adopted"
                )
                continue
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
                dataset_identity_hash=dataset_identity_hash,
                feature_registry_hash=feature_registry_hash,
                portfolio_replay=portfolio_replay,
                corporate_custody=corporate_custody,
                carry=carry,
                memory_guard=memory_guard,
            )
            peak_temporary_bytes = max(
                peak_temporary_bytes,
                temp_bytes,
            )
            _enforce_temporary_budget(
                observed_bytes=peak_temporary_bytes,
                budget_bytes=request.temporary_storage_budget_bytes,
            )
            year_manifests.append(year_manifest)
            total_corporate_exclusions += int(
                year_manifest[
                    "corporate_action_excluded_label_count"
                ]
            )
            total_teacher_incomplete += int(
                year_manifest["teacher_incomplete_decision_count"]
            )
            completed[year] = _completed_year_entry(
                year=year,
                year_directory=year_directory,
                year_manifest=year_manifest,
            )
            _write_incomplete_checkpoint(
                checkpoint_path=checkpoint_path,
                run_id=run_id,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                completed=completed,
                peak_temporary_bytes=peak_temporary_bytes,
            )
            memory_guard.observe(stage=f"year_{year}_checkpoint_complete")

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
            )
        )
        blockers = {
            "portfolio_ledger_missing_cash_only_fallback_"
            "turnover_and_cooldown_not_learned",
            "official_trade_restriction_timeline_missing_formal_replay_blocked",
            "formal_rule_champion_snapshot_history_missing_formal_replay_blocked",
        }
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
        portfolio_state_policy = portfolio_replay.custody_payload()
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
            # Direct raw-PIT store 尚未接收可逐日驗證的正式交易限制與 Rule
            # Champion snapshot history；兩者皆是 OOS 配置語意的一部分，
            # 不可在 replay 階段以 proxy 或現在值補寫。
            "official_trade_restriction_timeline_present": False,
            "formal_rule_champion_snapshot_history_present": False,
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
                "full_period_observation_sqlite": False,
                "training_jsonl_intermediate": False,
                "annual_work_sqlite": True,
                "annual_atomic_checkpoint": True,
                "compact_feature_carry": True,
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
                    request.temporary_storage_budget_bytes
                ),
                "temporary_storage_preflight": temporary_preflight,
                "temporary_storage_quota_enforced_during_workspace": True,
                "peak_temporary_bytes": peak_temporary_bytes,
            },
            "safety": {
                "pit_contract_revalidated_per_row": True,
                "t_minus_1_contract_revalidated_per_row": True,
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
                "production_alpha_bp": 0,
                "formal_oos_allowed": False,
                "broker_order_allowed": False,
            },
            "store_identity": store_identity,
        }
        manifest["manifest_hash"] = _sha256_json(manifest)
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
        dataset_identity_hash: str,
        feature_registry_hash: str,
        portfolio_replay: Any,
        corporate_custody: Any,
        carry: Any,
        memory_guard: _MemoryBudgetGuard,
    ) -> tuple[dict[str, Any], Any, int]:
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
            )
            memory_guard.observe(stage=f"year_{year}_raw_spool_complete")
            _enforce_workspace_budget(
                roots=(work, staging),
                budget_bytes=request.temporary_storage_budget_bytes,
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
            )
            memory_guard.observe(stage=f"year_{year}_labels_complete")
            _enforce_workspace_budget(
                roots=(work, staging),
                budget_bytes=request.temporary_storage_budget_bytes,
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
            registry = _DirectWriterRegistry(
                staging=staging,
                expected_year=year,
                year_ordinal=year_ordinal,
                feature_ids=discovery.feature_ids,
                feature_scales=discovery.feature_scales,
                horizons=legacy.SUPPORTED_HORIZONS,
                batch_size=request.batch_size,
            )
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
                )
            )
            memory_guard.observe(stage=f"year_{year}_assembly_complete")
            _enforce_workspace_budget(
                roots=(work, staging),
                budget_bytes=request.temporary_storage_budget_bytes,
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
                    "official_trade_restriction_timeline_present": False,
                    "teacher_targets_used": False,
                },
                "direct_source_shards": [
                    {
                        "year": int(item["year"]),
                        "path": str(item["path"]),
                        "compressed_sha256": item["compressed_sha256"],
                        "content_sha256": item["content_sha256"],
                    }
                    for item in shards
                ],
                "carry_entry_count": carry_count,
                "teacher_incomplete_decision_count": teacher_incomplete,
                "corporate_action_excluded_label_count": (
                    corporate_excluded
                ),
                "artifacts": artifacts,
                "complete": True,
            }
            year_manifest["manifest_hash"] = _sha256_json(year_manifest)
            _write_json(staging / "manifest.json", year_manifest)
            memory_guard.observe(stage=f"year_{year}_artifacts_complete")
            connection.close()
            temp_bytes = _directory_size_bytes(work) + _directory_size_bytes(
                staging
            )
            _enforce_temporary_budget(
                observed_bytes=temp_bytes,
                budget_bytes=request.temporary_storage_budget_bytes,
            )
            final_directory = run_directory / f"year={year:04d}"
            os.replace(staging, final_directory)
            _safe_remove_tree(work, run_directory)
            return year_manifest, carry, temp_bytes
        except Exception:
            connection.close()
            if staging.exists():
                _safe_remove_tree(staging, run_directory)
            if work.exists():
                _safe_remove_tree(work, run_directory)
            raise


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
        batch_size: int,
    ) -> None:
        self.expected_year = expected_year
        self.writer = _DirectYearWriter(
            staging=staging,
            year=expected_year,
            year_ordinal=year_ordinal,
            feature_ids=feature_ids,
            feature_scales=feature_scales,
            horizons=horizons,
            batch_size=batch_size,
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
        batch_size: int,
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
        self.row_count = 0
        self.observed_counts = np.zeros(
            len(feature_ids),
            dtype=np.int64,
        )
        self._closed = False

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
                "unknown_no_official_restriction_timeline",
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
        history = self._volume_history.setdefault(symbol, deque(maxlen=20))
        if (
            price_event_at is not None
            and volume_shares is not None
            and (
                not history
                or history[-1][0] != price_event_at
            )
        ):
            history.append((price_event_at, volume_shares))
        median_volume = None
        if len(history) >= 20:
            ordered = sorted(item[1] for item in history)
            median_volume = (
                ordered[9] + ordered[10]
            ) // 2
        open_int = _eligible_current_int(open_value)
        close_int = _eligible_current_int(close_value)
        open_scale = _eligible_current_scale(open_value)
        close_scale = _eligible_current_scale(close_value)
        rule_score_bp = _relative_score_bp(close_value, ma20_value)
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
) -> _Discovery:
    base_definitions = legacy._base_feature_definitions(raw_manifest)
    runtime = dict(base_definitions)
    publication_root = raw_manifest_path.parent.parent.resolve()
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
        shard_path = (
            publication_root / str(shard["path"])
        ).resolve()
        if not shard_path.is_relative_to(publication_root):
            raise ValueError("raw shard path escapes publication root")
        if _file_sha256(shard_path) != str(shard["compressed_sha256"]):
            raise ValueError("raw shard compressed hash mismatch")
        shard_digest = hashlib.sha256()
        row_count = 0
        value_count = 0
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
        if _SHA256_PREFIX + shard_digest.hexdigest() != str(
            shard["content_sha256"]
        ):
            raise ValueError("raw shard content hash mismatch")
        if row_count != int(shard["row_count"]):
            raise ValueError("raw shard row_count mismatch")
        if value_count != int(shard["feature_value_count"]):
            raise ValueError("raw shard feature_value_count mismatch")
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
        for scope in sorted(carry):
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
                            + "\n"
                        ).encode("utf-8")
                    )
                    count += 1
    return count


def _read_carry(path: Path) -> Any:
    result: Any = {"stock": {}, "market": {}, "industry": {}}
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            payload = json.loads(line)
            scope = str(payload.pop("scope"))
            entity = str(payload.pop("entity_key"))
            feature_id = str(payload.pop("feature_id"))
            result.setdefault(scope, {}).setdefault(entity, {})[
                feature_id
            ] = legacy._CurrentValue(**payload)
    return result


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
) -> bool:
    manifest_path = year_directory / "manifest.json"
    carry_path = year_directory / "carry.state.gz"
    if not manifest_path.is_file() or not carry_path.is_file():
        return False
    if not store_module._verify_year_directory(
        year_directory=year_directory,
        expected_manifest_hash=str(checkpoint_entry.get("manifest_hash", "")),
    ):
        return False
    return (
        checkpoint_entry.get("manifest_file_hash")
        == _file_sha256(manifest_path)
        and checkpoint_entry.get("carry_file_hash")
        == _file_sha256(carry_path)
    )


def _completed_year_entry(
    *,
    year: int,
    year_directory: Path,
    year_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "year": year,
        "manifest_hash": year_manifest["manifest_hash"],
        "manifest_file_hash": _file_sha256(
            year_directory / "manifest.json"
        ),
        "carry_file_hash": _file_sha256(
            year_directory / "carry.state.gz"
        ),
    }


def _adopt_finalized_year(
    *,
    year_directory: Path,
    year: int,
    year_ordinal: int,
    discovery: _Discovery,
    dataset_identity_hash: str,
    feature_registry_hash: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """採納已原子 rename、但 checkpoint 尚未落盤的完整年度。

    這是 ``os.replace(staging, final)`` 與 outer checkpoint 寫入之間的
    crash recovery。只有所有 artifact、carry 與本次 dataset identity
    完全相符時才採納；否則 fail closed，絕不覆寫既有 finalized directory。
    """

    manifest_path = year_directory / "manifest.json"
    carry_path = year_directory / "carry.state.gz"
    if not manifest_path.is_file() or not carry_path.is_file():
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
            "path": str(item["path"]),
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
        and manifest.get("direct_source_shards") == expected_shard_custody
    )
    expected_manifest_hash = str(manifest.get("manifest_hash", ""))
    if not identity_matches or not store_module._verify_year_directory(
        year_directory=year_directory,
        expected_manifest_hash=expected_manifest_hash,
    ):
        raise RuntimeError(
            f"uncheckpointed finalized year {year} failed custody validation"
        )
    entry = _completed_year_entry(
        year=year,
        year_directory=year_directory,
        year_manifest=manifest,
    )
    return manifest, entry


def _write_incomplete_checkpoint(
    *,
    checkpoint_path: Path,
    run_id: str,
    raw_manifest_hash: str,
    completed: Mapping[int, Mapping[str, Any]],
    peak_temporary_bytes: int,
) -> None:
    _atomic_write_json(
        checkpoint_path,
        {
            "schema_version": DIRECT_CHECKPOINT_SCHEMA_VERSION,
            "run_id": run_id,
            "raw_manifest_hash": raw_manifest_hash,
            "completed_years": [
                dict(completed[key]) for key in sorted(completed)
            ],
            "peak_temporary_bytes": peak_temporary_bytes,
            "complete": False,
        },
    )


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
    shutil.rmtree(resolved)


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
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
