"""Raw PIT → checkpointed legacy assembly → annual out-of-core store。

既有 assembler 的金融/PIT 邏輯保持單一權威；本模組只把最昂貴的 raw
observation ingest 改成年度 transaction checkpoint，並把 spool 固定放在使用者
指定的 output root。中斷後不必重新解壓、驗證及索引已完成年度。

最後仍發布既有 ``portfolio-ml-training-shards.v2`` custody，再轉成
``portfolio-ml-ooc-store.v2``。目前版本仍保留全期間 SQLite spool 與完整 JSONL
中介，因此明確標示為 transitional adapter；在逐年 direct numeric adapter 完成前，
不得宣稱 full-market-ready。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Mapping

from data_module import portfolio_ml_dataset_assembler as legacy
from data_module.ml_research_shadow_union import (
    ResearchShadowUnionBuilder,
    ResearchShadowUnionRequest,
)
from data_module.portfolio_ml_out_of_core_store import (
    PortfolioMLOutOfCoreStoreBuilder,
    PortfolioMLOutOfCoreStorePublication,
    PortfolioMLOutOfCoreStoreRequest,
)


PIPELINE_SCHEMA_VERSION = "portfolio-ml-raw-to-ooc-pipeline.v2"
CHECKPOINT_SCHEMA_VERSION = "portfolio-ml-raw-spool-checkpoint.v1"
_SHA256_PREFIX = "sha256:"


@dataclass(frozen=True)
class PortfolioMLRawToOOCRequest:
    raw_manifest_path: Path
    output_root: Path
    training_as_of: str
    benchmark_entity_id: str
    sector_membership_path: Path | None = None
    corporate_action_manifest_path: Path | None = None
    formal_portfolio_ledger_path: Path | None = None
    formal_rule_champion_history_path: Path | None = None
    research_shadow_manifest_path: Path | None = None
    research_symbols: tuple[str, ...] | None = None
    years: tuple[int, ...] = ()
    minimum_train_dates: int = 252
    test_date_count: int = 63
    purge_trading_days: int = 60
    embargo_trading_days: int = 5
    batch_size: int = 8_192
    compression_level: int = 6
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
            formal_portfolio_ledger_path=self.formal_portfolio_ledger_path,
            formal_rule_champion_history_path=(
                self.formal_rule_champion_history_path
            ),
            years=self.years,
            minimum_train_dates=self.minimum_train_dates,
            test_date_count=self.test_date_count,
            purge_trading_days=self.purge_trading_days,
            embargo_trading_days=self.embargo_trading_days,
            batch_size=self.batch_size,
            compression_level=self.compression_level,
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
            if (
                isinstance(self.temporary_storage_budget_bytes, bool)
                or not isinstance(self.temporary_storage_budget_bytes, int)
            ):
                raise TypeError(
                    "temporary_storage_budget_bytes must be integer or None"
                )
            if self.temporary_storage_budget_bytes <= 0:
                raise ValueError(
                    "temporary_storage_budget_bytes must be positive"
                )
        if not isinstance(self.resume, bool):
            raise TypeError("resume must be bool")
        if self.research_symbols is not None:
            normalized_symbols = tuple(
                sorted(
                    {
                        symbol.strip()
                        for symbol in self.research_symbols
                        if symbol.strip()
                    }
                )
            )
            if not normalized_symbols:
                raise ValueError("research_symbols must be non-empty or None")
            object.__setattr__(
                self,
                "research_symbols",
                normalized_symbols,
            )


@dataclass(frozen=True)
class PortfolioMLRawToOOCPublication:
    pipeline_id: str
    run_directory: Path
    manifest_path: Path
    training_manifest_path: Path
    store_publication: PortfolioMLOutOfCoreStorePublication
    completed_raw_shard_count: int
    research_union_manifest_path: Path | None = None
    research_store_publication: (
        PortfolioMLOutOfCoreStorePublication | None
    ) = None


class PortfolioMLRawToOOCBuilder:
    """以年度 transaction checkpoint 驅動既有 assembler 與數值 store。"""

    def build(
        self,
        request: PortfolioMLRawToOOCRequest,
    ) -> PortfolioMLRawToOOCPublication:
        raw_manifest_path = request.raw_manifest_path.resolve()
        raw_manifest = legacy._read_json(raw_manifest_path)
        legacy._validate_raw_dataset_manifest(raw_manifest)
        raw_manifest_file_hash = _file_sha256(raw_manifest_path)
        identity = {
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "raw_manifest_hash": raw_manifest["manifest_hash"],
            "raw_manifest_file_hash": raw_manifest_file_hash,
            "training_as_of": request.training_as_of,
            "benchmark_entity_id": request.benchmark_entity_id,
            "sector_membership_file_hash": (
                None
                if request.sector_membership_path is None
                else _file_sha256(request.sector_membership_path.resolve())
            ),
            "corporate_action_manifest_file_hash": (
                None
                if request.corporate_action_manifest_path is None
                else _file_sha256(
                    request.corporate_action_manifest_path.resolve()
                )
            ),
            "years": list(request.years),
            "minimum_train_dates": request.minimum_train_dates,
            "test_date_count": request.test_date_count,
            "purge_trading_days": request.purge_trading_days,
            "embargo_trading_days": request.embargo_trading_days,
            "temporary_storage_budget_bytes": (
                request.temporary_storage_budget_bytes
            ),
        }
        if request.formal_portfolio_ledger_path is not None:
            identity["formal_portfolio_ledger_file_hash"] = _file_sha256(
                request.formal_portfolio_ledger_path.resolve()
            )
        if request.formal_rule_champion_history_path is not None:
            identity["formal_rule_champion_history_file_hash"] = _file_sha256(
                request.formal_rule_champion_history_path.resolve()
            )
        if request.research_shadow_manifest_path is not None:
            identity["research_shadow_manifest_hash"] = _read_json(
                request.research_shadow_manifest_path.resolve()
            )["manifest_hash"]
            identity["research_symbols"] = (
                None
                if request.research_symbols is None
                else list(request.research_symbols)
            )
        pipeline_id = "raw-ooc-" + _sha256_json(identity)[7:31]
        output_root = request.output_root.resolve()
        runs_root = output_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        run_directory = runs_root / pipeline_id
        run_directory.mkdir(parents=True, exist_ok=True)
        manifest_path = run_directory / "manifest.json"
        latest_path = output_root / "latest_manifest.json"
        if manifest_path.is_file():
            existing_manifest = _read_json(manifest_path)
            _validate_pipeline_manifest(
                manifest=existing_manifest,
                expected_identity=identity,
            )
            store_manifest_path = (
                run_directory
                / str(existing_manifest["store_manifest_path"])
            ).resolve()
            store_manifest = _read_json(store_manifest_path)
            store_publication = _store_publication(
                store_manifest_path=store_manifest_path,
                manifest=store_manifest,
            )
            research_union_path_value = existing_manifest.get(
                "research_union_manifest_path"
            )
            research_store_path_value = existing_manifest.get(
                "research_store_manifest_path"
            )
            existing_research_store_publication = None
            if isinstance(research_store_path_value, str):
                research_store_manifest_path = (
                    run_directory / research_store_path_value
                ).resolve()
                existing_research_store_publication = _store_publication(
                    store_manifest_path=research_store_manifest_path,
                    manifest=_read_json(research_store_manifest_path),
                )
            _write_latest(
                path=latest_path,
                pipeline_id=pipeline_id,
                manifest=existing_manifest,
            )
            return PortfolioMLRawToOOCPublication(
                pipeline_id=pipeline_id,
                run_directory=run_directory,
                manifest_path=manifest_path,
                training_manifest_path=(
                    run_directory
                    / str(existing_manifest["training_manifest_path"])
                ).resolve(),
                store_publication=store_publication,
                completed_raw_shard_count=int(
                    existing_manifest["completed_raw_shard_count"]
                ),
                research_union_manifest_path=(
                    None
                    if not isinstance(research_union_path_value, str)
                    else (
                        run_directory / research_union_path_value
                    ).resolve()
                ),
                research_store_publication=(
                    existing_research_store_publication
                ),
            )
        if not request.resume and any(run_directory.iterdir()):
            raise FileExistsError(
                "incomplete raw-to-ooc pipeline exists and resume=false"
            )

        spool_directory = run_directory / "spool"
        spool_directory.mkdir(parents=True, exist_ok=True)
        spool_path = spool_directory / "assembly.sqlite"
        checkpoint_path = run_directory / "checkpoint.json"
        checkpoint = _load_checkpoint(
            path=checkpoint_path,
            pipeline_id=pipeline_id,
            raw_manifest_hash=str(raw_manifest["manifest_hash"]),
        )
        _validate_temporary_storage_preflight(
            raw_manifest=raw_manifest,
            budget_bytes=request.temporary_storage_budget_bytes,
        )
        connection = sqlite3.connect(spool_path)
        connection.row_factory = sqlite3.Row
        legacy._initialize_spool(connection)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        completed = {
            (int(item["year"]), str(item["path"])): dict(item)
            for item in _mapping_sequence(
                checkpoint.get("completed_raw_shards", []),
                field_name="completed_raw_shards",
            )
        }
        base_definitions = legacy._base_feature_definitions(raw_manifest)
        runtime_definitions = _restore_definitions(
            checkpoint=checkpoint,
            fallback=base_definitions,
        )
        raw_row_count = sum(
            int(item["row_count"]) for item in completed.values()
        )
        raw_value_count = sum(
            int(item["feature_value_count"]) for item in completed.values()
        )
        peak_temporary_bytes = max(
            int(checkpoint.get("peak_temporary_bytes", 0)),
            _directory_size_bytes(run_directory),
        )
        try:
            shards = sorted(
                legacy._mapping_sequence(
                    raw_manifest.get("shards"),
                    field_name="shards",
                ),
                key=lambda item: (int(item["year"]), str(item["path"])),
            )
            for shard in shards:
                key = (int(shard["year"]), str(shard["path"]))
                if key in completed:
                    continue
                subset_manifest = dict(raw_manifest)
                subset_manifest["shards"] = [dict(shard)]
                shard_digest = hashlib.sha256()
                connection.execute("BEGIN IMMEDIATE")
                try:
                    rows, values = (
                        legacy.PortfolioMLDatasetAssembler()
                        ._spool_raw_observations(
                            connection=connection,
                            dataset_manifest_path=raw_manifest_path,
                            manifest=subset_manifest,
                            definitions=runtime_definitions,
                            source_digest=shard_digest,
                            batch_size=request.batch_size,
                        )
                    )
                    peak_temporary_bytes = max(
                        peak_temporary_bytes,
                        _directory_size_bytes(run_directory),
                    )
                    _enforce_temporary_storage_budget(
                        observed_bytes=peak_temporary_bytes,
                        budget_bytes=(
                            request.temporary_storage_budget_bytes
                        ),
                    )
                except Exception:
                    connection.rollback()
                    raise
                connection.commit()
                raw_row_count += rows
                raw_value_count += values
                completed[key] = {
                    "year": key[0],
                    "path": key[1],
                    "content_sha256": shard["content_sha256"],
                    "compressed_sha256": shard["compressed_sha256"],
                    "row_count": rows,
                    "feature_value_count": values,
                }
                _atomic_write_json(
                    checkpoint_path,
                    {
                        "schema_version": CHECKPOINT_SCHEMA_VERSION,
                        "pipeline_id": pipeline_id,
                        "raw_manifest_hash": raw_manifest["manifest_hash"],
                        "completed_raw_shards": [
                            completed[item] for item in sorted(completed)
                        ],
                        "runtime_definitions": [
                            asdict(runtime_definitions[feature_id])
                            for feature_id in sorted(runtime_definitions)
                        ],
                        "raw_ingest_complete": False,
                        "peak_temporary_bytes": peak_temporary_bytes,
                        "training_manifest_path": checkpoint.get(
                            "training_manifest_path"
                        ),
                        "store_manifest_path": checkpoint.get(
                            "store_manifest_path"
                        ),
                    },
                )
            if len(completed) != len(shards):
                raise RuntimeError("raw shard checkpoint coverage is incomplete")
            legacy._finalize_long_format_definitions(
                runtime_definitions=runtime_definitions,
                base_definitions=base_definitions,
            )
            checkpoint = {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "pipeline_id": pipeline_id,
                "raw_manifest_hash": raw_manifest["manifest_hash"],
                "completed_raw_shards": [
                    completed[item] for item in sorted(completed)
                ],
                "runtime_definitions": [
                    asdict(runtime_definitions[feature_id])
                    for feature_id in sorted(runtime_definitions)
                ],
                "raw_ingest_complete": True,
                "peak_temporary_bytes": peak_temporary_bytes,
                "training_manifest_path": checkpoint.get(
                    "training_manifest_path"
                ),
                "store_manifest_path": checkpoint.get(
                    "store_manifest_path"
                ),
            }
            _atomic_write_json(checkpoint_path, checkpoint)
            training_manifest_path = self._publish_training(
                request=request,
                run_directory=run_directory,
                raw_manifest_path=raw_manifest_path,
                raw_manifest=raw_manifest,
                connection=connection,
                runtime_definitions=runtime_definitions,
                completed=completed,
                raw_row_count=raw_row_count,
                raw_value_count=raw_value_count,
            )
            peak_temporary_bytes = max(
                peak_temporary_bytes,
                _directory_size_bytes(run_directory),
            )
            _enforce_temporary_storage_budget(
                observed_bytes=peak_temporary_bytes,
                budget_bytes=request.temporary_storage_budget_bytes,
            )
        finally:
            connection.close()

        checkpoint["training_manifest_path"] = os.path.relpath(
            training_manifest_path,
            run_directory,
        ).replace("\\", "/")
        _atomic_write_json(checkpoint_path, checkpoint)
        store_output = run_directory / "store"
        store_publication = PortfolioMLOutOfCoreStoreBuilder().build(
            PortfolioMLOutOfCoreStoreRequest(
                training_manifest_path=training_manifest_path,
                output_root=store_output,
                batch_size=request.batch_size,
                workers=request.workers,
                memory_budget_mb=request.memory_budget_mb,
                resume=request.resume,
            )
        )
        checkpoint["store_manifest_path"] = os.path.relpath(
            store_publication.manifest_path,
            run_directory,
        ).replace("\\", "/")
        _atomic_write_json(checkpoint_path, checkpoint)
        research_union_manifest_path: Path | None = None
        research_store_publication: (
            PortfolioMLOutOfCoreStorePublication | None
        ) = None
        if request.research_shadow_manifest_path is not None:
            research_union = ResearchShadowUnionBuilder().build(
                ResearchShadowUnionRequest(
                    formal_raw_manifest_path=raw_manifest_path,
                    shadow_raw_manifest_path=(
                        request.research_shadow_manifest_path.resolve()
                    ),
                    base_training_manifest_path=training_manifest_path,
                    output_root=run_directory / "research_union",
                    symbols=request.research_symbols,
                    years=request.years,
                    batch_size=request.batch_size,
                    compression_level=request.compression_level,
                )
            )
            research_union_manifest_path = research_union.manifest_path
            research_store_publication = (
                PortfolioMLOutOfCoreStoreBuilder().build(
                    PortfolioMLOutOfCoreStoreRequest(
                        training_manifest_path=(
                            research_union.manifest_path
                        ),
                        output_root=run_directory / "research_store",
                        batch_size=request.batch_size,
                        workers=request.workers,
                        memory_budget_mb=request.memory_budget_mb,
                        resume=request.resume,
                        lane="research_shadow",
                    )
                )
            )
        pipeline_manifest: dict[str, Any] = {
            "schema_version": PIPELINE_SCHEMA_VERSION,
            "status": "complete",
            "pipeline_id": pipeline_id,
            "pipeline_identity": identity,
            "raw_manifest_hash": raw_manifest["manifest_hash"],
            "raw_manifest_file_hash": raw_manifest_file_hash,
            "completed_raw_shard_count": len(completed),
            "raw_row_count": raw_row_count,
            "raw_feature_value_count": raw_value_count,
            "training_manifest_path": checkpoint["training_manifest_path"],
            "training_manifest_file_hash": _file_sha256(
                training_manifest_path
            ),
            "store_manifest_path": checkpoint["store_manifest_path"],
            "store_manifest_hash": store_publication.manifest_hash,
            "store_manifest_file_hash": (
                store_publication.manifest_file_hash
            ),
            "research_union_manifest_path": (
                None
                if research_union_manifest_path is None
                else os.path.relpath(
                    research_union_manifest_path,
                    run_directory,
                ).replace("\\", "/")
            ),
            "research_union_manifest_file_hash": (
                None
                if research_union_manifest_path is None
                else _file_sha256(research_union_manifest_path)
            ),
            "research_store_manifest_path": (
                None
                if research_store_publication is None
                else os.path.relpath(
                    research_store_publication.manifest_path,
                    run_directory,
                ).replace("\\", "/")
            ),
            "research_store_manifest_hash": (
                None
                if research_store_publication is None
                else research_store_publication.manifest_hash
            ),
            "research_lane": {
                "enabled": research_store_publication is not None,
                "research_only": (
                    research_store_publication is not None
                ),
                "formal_consumer_compatible": False,
                "promotion_eligible": False,
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "core_history_preserved_with_missing_masks": True,
            },
            "execution": {
                "raw_year_transaction_checkpoint": True,
                "persistent_spool_path": "spool/assembly.sqlite",
                "direct_numeric_store": False,
                "full_market_ready": False,
                "transitional_legacy_jsonl_adapter": True,
                "resume_supported": True,
                "raw_shard_reingest_on_resume": False,
                "training_publication_manifest_last": True,
                "store_manifest_last": True,
                "batch_size": request.batch_size,
                "workers": request.workers,
                "memory_budget_mb": request.memory_budget_mb,
                "temporary_storage_budget_bytes": (
                    request.temporary_storage_budget_bytes
                ),
                "peak_temporary_bytes": peak_temporary_bytes,
            },
            "safety": {
                "formal_source_only": True,
                "pit_contract_revalidated": True,
                "t_minus_1_contract_revalidated": True,
                "production_alpha_bp": 0,
                "formal_oos_allowed": False,
            },
            "blockers": [
                "direct_annual_numeric_adapter_not_implemented",
                "full_period_sqlite_spool_and_jsonl_intermediate_present",
            ],
        }
        pipeline_manifest["manifest_hash"] = _sha256_json(
            pipeline_manifest
        )
        _write_json(manifest_path, pipeline_manifest)
        _write_latest(
            path=latest_path,
            pipeline_id=pipeline_id,
            manifest=pipeline_manifest,
        )
        return PortfolioMLRawToOOCPublication(
            pipeline_id=pipeline_id,
            run_directory=run_directory,
            manifest_path=manifest_path,
            training_manifest_path=training_manifest_path,
            store_publication=store_publication,
            completed_raw_shard_count=len(completed),
            research_union_manifest_path=research_union_manifest_path,
            research_store_publication=research_store_publication,
        )

    def _publish_training(
        self,
        *,
        request: PortfolioMLRawToOOCRequest,
        run_directory: Path,
        raw_manifest_path: Path,
        raw_manifest: Mapping[str, Any],
        connection: sqlite3.Connection,
        runtime_definitions: Mapping[str, Any],
        completed: Mapping[tuple[int, str], Mapping[str, Any]],
        raw_row_count: int,
        raw_value_count: int,
    ) -> Path:
        training_root = run_directory / "training"
        existing_pointer = training_root / "latest_manifest.json"
        if existing_pointer.is_file():
            pointer = _read_json(existing_pointer)
            path = training_root / str(pointer["manifest_path"])
            existing_training_manifest = _read_json(path)
            if (
                existing_training_manifest.get("schema_version")
                != legacy.PUBLICATION_SCHEMA_VERSION
            ):
                raise ValueError("existing training publication schema mismatch")
            return path
        cutoff = legacy._available_datetime(
            request.training_as_of,
            field_name="training_as_of",
        )
        corporate_action_custody = (
            legacy._load_corporate_action_custody(
                request.corporate_action_manifest_path,
                training_as_of=cutoff,
            )
        )
        corporate_action_policy = (
            corporate_action_custody.custody_payload()
        )
        training_root.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=".training-", dir=training_root)
        )
        writers = legacy._TrainingShardWriterRegistry(
            staging=staging,
            compression_level=request.compression_level,
        )
        try:
            connection.execute("DELETE FROM labels")
            connection.execute("DELETE FROM current_features")
            connection.execute("DELETE FROM sector_memberships")
            connection.commit()
            sector_manifest_hash, sector_count = (
                legacy._spool_sector_memberships(
                    connection,
                    request.sector_membership_path,
                    training_as_of=cutoff,
                )
            )
            feature_definitions = tuple(
                sorted(
                    runtime_definitions.values(),
                    key=lambda row: row.feature_id,
                )
            )
            feature_packs = legacy._feature_pack_payloads(
                feature_definitions
            )
            feature_registry_payload = {
                "features": [
                    asdict(definition)
                    for definition in feature_definitions
                ],
                "feature_packs": feature_packs,
            }
            feature_registry_hash = legacy._sha256_json(
                feature_registry_payload
            )
            source_manifest_hashes = legacy._source_manifest_hashes(
                definitions=feature_definitions,
                raw_manifest_hash=str(raw_manifest["manifest_hash"]),
                sector_manifest_hash=sector_manifest_hash,
                corporate_action_manifest_hash=(
                    corporate_action_custody.manifest_hash
                ),
            )
            calendar, benchmark_returns = legacy._build_label_spool(
                connection=connection,
                benchmark_entity_id=request.benchmark_entity_id,
                cutoff=cutoff,
                horizons=legacy.SUPPORTED_HORIZONS,
                batch_size=request.batch_size,
                corporate_action_effective_dates=(
                    corporate_action_custody.effective_dates_by_symbol
                ),
            )
            corporate_action_excluded_label_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM label_exclusions WHERE reason=?",
                    (
                        "corporate_action_effective_within_label_horizon",
                    ),
                ).fetchone()[0]
            )
            calendar_positions = {
                day: index for index, day in enumerate(calendar)
            }
            eligible_dates = tuple(
                day
                for day in legacy._eligible_decision_dates(
                    connection,
                    years=request.years,
                )
                if calendar_positions.get(day, 0) > 0
            )
            fold_windows = legacy._build_fold_windows(
                eligible_dates,
                minimum_train_dates=request.minimum_train_dates,
                test_date_count=request.test_date_count,
                purge_trading_days=request.purge_trading_days,
                embargo_trading_days=request.embargo_trading_days,
            )
            if len(fold_windows) < 4:
                raise ValueError(
                    "raw-to-ooc pipeline requires at least four folds"
                )
            formal_rule_champion_custody = (
                legacy._load_formal_rule_champion_history(
                    request.formal_rule_champion_history_path,
                    decision_dates=eligible_dates,
                    training_as_of=cutoff.isoformat(),
                )
            )
            replay = legacy._build_portfolio_state_replay(
                calendar=calendar,
                decision_dates=eligible_dates,
                formal_portfolio_ledger_path=(
                    request.formal_portfolio_ledger_path
                ),
            )
            portfolio_state_policy = replay.custody_payload()
            assembly_blockers: set[str] = set()
            if replay.cash_only_fallback:
                assembly_blockers.add(
                    "portfolio_ledger_missing_cash_only_fallback_"
                    "turnover_and_cooldown_not_learned"
                )
            if formal_rule_champion_custody is None:
                assembly_blockers.add(
                    "formal_rule_champion_snapshot_history_missing_formal_replay_blocked"
                )
            if not corporate_action_custody.manifest_present:
                assembly_blockers.add(
                    "corporate_action_adjustment_timeline_not_in_raw_"
                    "publication_labels_are_research_shadow"
                )
            if sector_count == 0:
                assembly_blockers.add(
                    "pit_sector_membership_missing_teacher_new_"
                    "positions_disabled"
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
            raw_content_custody_hash = _sha256_json(
                {
                    "raw_manifest_hash": raw_manifest["manifest_hash"],
                    "shards": [
                        {
                            "year": item["year"],
                            "path": item["path"],
                            "content_sha256": item["content_sha256"],
                        }
                        for _, item in sorted(completed.items())
                    ],
                }
            )
            dataset_identity_hash = legacy._sha256_json(
                {
                    "schema_version": legacy.TRAINING_JSONL_SCHEMA_VERSION,
                    "raw_dataset_manifest_hash": raw_manifest[
                        "manifest_hash"
                    ],
                    "raw_content_digest": raw_content_custody_hash,
                    "training_as_of": cutoff.isoformat(),
                    "benchmark_entity_id": request.benchmark_entity_id,
                    "sector_manifest_hash": sector_manifest_hash,
                    "feature_registry_hash": feature_registry_hash,
                    "source_manifest_hashes": source_manifest_hashes,
                    "horizons": list(legacy.SUPPORTED_HORIZONS),
                    "fold_windows": [
                        asdict(window) for window in fold_windows
                    ],
                    "portfolio_state_replay_custody": (
                        portfolio_state_policy
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
                    "corporate_action_custody": (
                        corporate_action_policy
                    ),
                    "corporate_action_excluded_label_count": (
                        corporate_action_excluded_label_count
                    ),
                    "teacher_policy": "100bp_constrained_grid",
                    "raw_ingest_checkpoint_schema": (
                        CHECKPOINT_SCHEMA_VERSION
                    ),
                    "formal_consumer_marker_policy": (
                        "explicit_fail_closed_v1"
                    ),
                }
            )
            header_common = _header_common(
                raw_manifest=raw_manifest,
                cutoff_iso=cutoff.isoformat(),
                benchmark_entity_id=request.benchmark_entity_id,
                sector_manifest_hash=sector_manifest_hash,
                feature_packs=feature_packs,
                fold_windows=fold_windows,
                assembly_blockers=assembly_blockers,
                feature_registry_hash=feature_registry_hash,
                source_manifest_hashes=source_manifest_hashes,
                portfolio_state_policy=portfolio_state_policy,
                corporate_action_policy=corporate_action_policy,
                corporate_action_excluded_label_count=(
                    corporate_action_excluded_label_count
                ),
                dataset_identity_hash=dataset_identity_hash,
            )
            if formal_rule_champion_custody is not None:
                header_common["formal_rule_champion_history"] = (
                    formal_rule_champion_custody.custody_payload()
                )
            teacher_incomplete_count, sample_count = (
                legacy.PortfolioMLDatasetAssembler()._assemble_samples(
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
                    portfolio_state_replay=replay,
                    years=request.years,
                    batch_size=request.batch_size,
                )
            )
            if sample_count == 0:
                raise ValueError("no mature allocation samples were emitted")
            if teacher_incomplete_count:
                assembly_blockers.add(
                    "teacher_search_incomplete_for_one_or_more_decision_dates"
                )
            writers.close_all()
            shard_payloads = writers.manifest_payloads(staging=staging)
            publication_id = (
                "portfolio-ml-"
                + legacy._sha256_json(
                    {
                        "dataset_identity_hash": dataset_identity_hash,
                        "training_as_of": cutoff.isoformat(),
                        "shards": [
                            {
                                "year": payload["year"],
                                "content_sha256": payload[
                                    "content_sha256"
                                ],
                            }
                            for payload in shard_payloads
                        ],
                    }
                )[7:31]
            )
            training_manifest: dict[str, Any] = {
                "schema_version": legacy.PUBLICATION_SCHEMA_VERSION,
                "publication_id": publication_id,
                "stage": "portfolio_ml_dataset_row_assembly",
                "direct_training_input": True,
                "target_cli": "scripts/train_ml_allocation_out_of_core.py",
                "target_schema_version": (
                    legacy.TRAINING_JSONL_SCHEMA_VERSION
                ),
                "dataset_id": header_common["dataset_id"],
                "dataset_identity_hash": dataset_identity_hash,
                "feature_registry_hash": feature_registry_hash,
                "source_manifest_hashes": [
                    list(item) for item in source_manifest_hashes
                ],
                "training_as_of": cutoff.isoformat(),
                "benchmark_entity_id": request.benchmark_entity_id,
                "raw_dataset_manifest": {
                    "path": str(raw_manifest_path),
                    "manifest_hash": raw_manifest["manifest_hash"],
                    "raw_row_count": raw_row_count,
                    "raw_value_count": raw_value_count,
                    "streaming_jsonl": True,
                    "annual_transaction_checkpoint": True,
                },
                "feature_packs": header_common["feature_packs"],
                "feature_registry": feature_registry_payload,
                "feature_count": sum(
                    len(pack["feature_ids"])
                    for pack in header_common["feature_packs"]
                ),
                "horizons": list(legacy.SUPPORTED_HORIZONS),
                "folds": [asdict(window) for window in fold_windows],
                "fold_count": len(fold_windows),
                "sample_count": sample_count,
                "teacher_incomplete_decision_count": (
                    teacher_incomplete_count
                ),
                "sector_membership_count": sector_count,
                "sector_benchmark_price_count": industry_price_count,
                "sector_manifest_hash": sector_manifest_hash,
                "corporate_action_custody": corporate_action_policy,
                "corporate_action_excluded_label_count": (
                    corporate_action_excluded_label_count
                ),
                "corporate_action_exclusion_reason": (
                    "corporate_action_effective_within_label_horizon"
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
                    "persistent_sqlite_spool": True,
                    "annual_raw_transaction_checkpoint": True,
                    "batch_size": request.batch_size,
                    "parquet_dependency_added": False,
                },
                "shards": shard_payloads,
            }
            if formal_rule_champion_custody is not None:
                training_manifest["formal_rule_champion_history"] = (
                    formal_rule_champion_custody.custody_payload()
                )
            training_manifest["manifest_hash"] = legacy._sha256_json(
                training_manifest
            )
            legacy._write_json(
                staging / "manifest.json",
                training_manifest,
            )
            final_directory = training_root / "runs" / publication_id
            final_directory.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final_directory)
            _atomic_write_json(
                existing_pointer,
                {
                    "schema_version": "portfolio-ml-training-pointer.v1",
                    "publication_id": publication_id,
                    "manifest_path": (
                        f"runs/{publication_id}/manifest.json"
                    ),
                    "manifest_hash": training_manifest["manifest_hash"],
                },
            )
            return final_directory / "manifest.json"
        except Exception:
            writers.close_all()
            if staging.exists():
                _safe_remove_tree(staging, training_root)
            raise


def _header_common(
    *,
    raw_manifest: Mapping[str, Any],
    cutoff_iso: str,
    benchmark_entity_id: str,
    sector_manifest_hash: str,
    feature_packs: list[dict[str, object]],
    fold_windows: tuple[Any, ...],
    assembly_blockers: set[str],
    feature_registry_hash: str,
    source_manifest_hashes: tuple[tuple[str, str], ...],
    portfolio_state_policy: Mapping[str, Any],
    corporate_action_policy: Mapping[str, Any],
    corporate_action_excluded_label_count: int,
    dataset_identity_hash: str,
) -> dict[str, Any]:
    return {
        "record_type": "header",
        "schema_version": legacy.TRAINING_JSONL_SCHEMA_VERSION,
        "direct_training_input": True,
        "dataset_id": (
            f"{raw_manifest['dataset_id']}-portfolio-allocation-"
            f"{dataset_identity_hash[7:19]}"
        ),
        "dataset_identity_hash": dataset_identity_hash,
        "training_as_of": cutoff_iso,
        "horizons": list(legacy.SUPPORTED_HORIZONS),
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
        "corporate_action_custody": dict(corporate_action_policy),
        "label_policy": {
            "entry": "decision_day_open_next_tradable_time",
            "exit": "exact_market_session_horizon_close",
            "transaction_cost_bp": 80,
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
                "corporate_action_effective_within_label_horizon"
            ),
            "corporate_action_excluded_label_count": (
                corporate_action_excluded_label_count
            ),
            "post_event_corporate_action_used_as_feature": False,
            "benchmark_entity_id": benchmark_entity_id,
            "sector_manifest_hash": sector_manifest_hash,
        },
    }


def _restore_definitions(
    *,
    checkpoint: Mapping[str, Any],
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    payloads = checkpoint.get("runtime_definitions")
    if not isinstance(payloads, list) or not payloads:
        return dict(fallback)
    return {
        str(payload["feature_id"]): legacy._FeatureDefinition(**payload)
        for payload in payloads
        if isinstance(payload, dict)
    }


def _load_checkpoint(
    *,
    path: Path,
    pipeline_id: str,
    raw_manifest_hash: str,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "pipeline_id": pipeline_id,
            "raw_manifest_hash": raw_manifest_hash,
            "completed_raw_shards": [],
            "raw_ingest_complete": False,
        }
    payload = _read_json(path)
    if (
        payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or payload.get("pipeline_id") != pipeline_id
        or payload.get("raw_manifest_hash") != raw_manifest_hash
    ):
        raise ValueError("raw spool checkpoint identity mismatch")
    return payload


def _store_publication(
    *,
    store_manifest_path: Path,
    manifest: Mapping[str, Any],
) -> PortfolioMLOutOfCoreStorePublication:
    run_directory = store_manifest_path.parent
    output_root = run_directory.parent.parent
    return PortfolioMLOutOfCoreStorePublication(
        run_id=str(manifest["run_id"]),
        run_directory=run_directory,
        manifest_path=store_manifest_path,
        latest_manifest_path=output_root / "latest_manifest.json",
        manifest_hash=str(manifest["manifest_hash"]),
        manifest_file_hash=_file_sha256(store_manifest_path),
        row_count=int(manifest["row_count"]),
        feature_count=int(manifest["feature_count"]),
        fold_count=int(manifest["fold_count"]),
    )


def _validate_pipeline_manifest(
    *,
    manifest: Mapping[str, Any],
    expected_identity: Mapping[str, Any],
) -> None:
    if manifest.get("schema_version") != PIPELINE_SCHEMA_VERSION:
        raise ValueError("pipeline schema mismatch")
    if manifest.get("status") != "complete":
        raise ValueError("pipeline is not complete")
    if _canonical_json(manifest.get("pipeline_identity")) != _canonical_json(
        expected_identity
    ):
        raise ValueError("pipeline identity mismatch")
    expected = str(manifest.get("manifest_hash", ""))
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected:
        raise ValueError("pipeline manifest logical hash mismatch")


def _write_latest(
    *,
    path: Path,
    pipeline_id: str,
    manifest: Mapping[str, Any],
) -> None:
    _atomic_write_json(
        path,
        {
            "schema_version": "portfolio-ml-raw-to-ooc-latest.v1",
            "pipeline_id": pipeline_id,
            "manifest_path": f"runs/{pipeline_id}/manifest.json",
            "manifest_hash": manifest["manifest_hash"],
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
        },
    )


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


def _safe_remove_tree(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("refusing to remove path outside pipeline root")
    shutil.rmtree(resolved)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _validate_temporary_storage_preflight(
    *,
    raw_manifest: Mapping[str, Any],
    budget_bytes: int | None,
) -> None:
    """以輸入壓縮檔大小作絕對下界，低於下界即在寫入前 fail closed。"""

    if budget_bytes is None:
        return
    compressed_lower_bound = sum(
        int(item.get("compressed_bytes", 0))
        for item in _mapping_sequence(
            raw_manifest.get("shards"),
            field_name="shards",
        )
    )
    if compressed_lower_bound > budget_bytes:
        raise ValueError(
            "temporary storage budget is below the compressed raw input "
            f"lower bound: {budget_bytes} < {compressed_lower_bound}"
        )


def _enforce_temporary_storage_budget(
    *,
    observed_bytes: int,
    budget_bytes: int | None,
) -> None:
    if budget_bytes is not None and observed_bytes > budget_bytes:
        raise RuntimeError(
            "temporary storage budget exceeded: "
            f"{observed_bytes} > {budget_bytes}"
        )


def _directory_size_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return total
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


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


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
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
