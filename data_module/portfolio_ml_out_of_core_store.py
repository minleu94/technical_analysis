"""將正式 Portfolio ML JSONL publication 轉為可續跑的數值型 out-of-core store。

這條路徑不取代既有小型／bounded trainer；它專門處理全市場資料：

* 每次只解析一列 ``AllocationTrainingSample``，不保留 Python sample 集合。
* 特徵、missing mask、targets 與 labels 依年度寫入固定 dtype memmap。
* row identity 與 availability custody 寫入年度唯讀 SQLite。
* outer-fold train/test membership 寫成 ``(year_ordinal, local_row_index)``
  的 int64 binary index；不展開成 Python row-id tuple。
* 年度目錄與最終 manifest 都採 manifest-last／atomic replace，可安全續跑。

公開與持久化欄位維持整數 bp／整數 scaled value；浮點只允許在後續模型
數值邊界內產生。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np

from scripts.train_ml_allocation_copilot import _parse_sample


STORE_SCHEMA_VERSION = "portfolio-ml-ooc-store.v3"
YEAR_SCHEMA_VERSION = "portfolio-ml-ooc-year.v3"
CHECKPOINT_SCHEMA_VERSION = "portfolio-ml-ooc-checkpoint.v1"
FOLD_INDEX_SCHEMA_VERSION = "portfolio-ml-ooc-fold-index.v1"
SOURCE_SCHEMA_VERSION = "portfolio-ml-training-shards.v2"
SOURCE_RECORD_SCHEMA_VERSION = "allocation-training-jsonl-v2"

VALUE_DTYPE = np.dtype("<i8")
MASK_DTYPE = np.dtype("u1")
TARGET_DTYPE = np.dtype("<i4")
LABEL_DTYPE = np.dtype("<i4")
ROW_REF_DTYPE = np.dtype("<i8")

TARGET_FIELDS = (
    "target_weight_bp",
    "delta_weight_bp",
    "risk_contribution_bp",
    "risky_budget_bp",
    "cash_bp",
    "rebalance_worthwhile",
)
LABEL_FIELDS = (
    "benchmark_excess_return_bp",
    "sector_excess_return_bp",
    "downside_observed",
    "mae_bp",
    "mfe_bp",
    "realized_volatility_bp",
    "max_drawdown_bp",
    "tail_loss_bp",
    "fill_feasible_observed",
)
_SHA256_PREFIX = "sha256:"


@dataclass(frozen=True)
class PortfolioMLOutOfCoreStoreRequest:
    training_manifest_path: Path
    output_root: Path
    batch_size: int = 8_192
    workers: int = 1
    memory_budget_mb: int = 4_096
    resume: bool = True
    lane: Literal["formal", "research_shadow"] = "formal"

    def __post_init__(self) -> None:
        for field_name in ("batch_size", "workers", "memory_budget_mb"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.batch_size > 65_536:
            raise ValueError("batch_size must not exceed 65536")
        if self.workers > 32:
            raise ValueError("workers must not exceed 32")
        if self.memory_budget_mb < 256:
            raise ValueError("memory_budget_mb must be at least 256")
        if not isinstance(self.resume, bool):
            raise TypeError("resume must be bool")
        if self.lane not in {"formal", "research_shadow"}:
            raise ValueError("lane must be formal or research_shadow")


@dataclass(frozen=True)
class PortfolioMLOutOfCoreStorePublication:
    run_id: str
    run_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    manifest_file_hash: str
    row_count: int
    feature_count: int
    fold_count: int


@dataclass(frozen=True)
class _SourceShard:
    ordinal: int
    year: int
    path: Path
    relative_path: str
    sample_count: int
    compressed_sha256: str
    content_sha256: str


class PortfolioMLOutOfCoreStoreBuilder:
    """Streaming、resume-safe 的正式數值 store builder。"""

    def build(
        self,
        request: PortfolioMLOutOfCoreStoreRequest,
    ) -> PortfolioMLOutOfCoreStorePublication:
        source_manifest_path = request.training_manifest_path.resolve()
        source_manifest = _read_json(source_manifest_path)
        _validate_source_manifest(
            source_manifest,
            lane=request.lane,
        )
        source_manifest_file_hash = _file_sha256(source_manifest_path)
        feature_packs = _feature_packs(source_manifest)
        feature_ids = tuple(
            feature_id
            for pack in feature_packs
            for feature_id in pack["feature_ids"]
        )
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("source feature ids must be globally unique")
        feature_scales = _feature_scales(
            source_manifest,
            feature_ids=feature_ids,
        )
        horizons = _integer_tuple(
            source_manifest.get("horizons"),
            field_name="horizons",
        )
        folds = _folds(source_manifest)
        source_shards = _source_shards(
            source_manifest_path=source_manifest_path,
            manifest=source_manifest,
        )
        store_identity = {
            "schema_version": STORE_SCHEMA_VERSION,
            "source_manifest_hash": source_manifest["manifest_hash"],
            "source_manifest_file_hash": source_manifest_file_hash,
            "dataset_identity_hash": source_manifest[
                "dataset_identity_hash"
            ],
            "feature_registry_hash": source_manifest[
                "feature_registry_hash"
            ],
            "feature_ids": list(feature_ids),
            "feature_scales": list(feature_scales),
            "horizons": list(horizons),
            "folds": folds,
            "lane": request.lane,
        }
        run_id = "ooc-" + _sha256_json(store_identity)[7:31]
        output_root = request.output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        runs_root = output_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        run_directory = runs_root / run_id
        run_directory.mkdir(parents=True, exist_ok=True)
        manifest_path = run_directory / "manifest.json"
        latest_manifest_path = output_root / "latest_manifest.json"

        if manifest_path.is_file():
            existing = _read_json(manifest_path)
            _validate_completed_store(
                manifest=existing,
                run_directory=run_directory,
                expected_identity=store_identity,
            )
            _write_latest_pointer(
                latest_manifest_path=latest_manifest_path,
                run_id=run_id,
                manifest=existing,
            )
            return _publication_from_manifest(
                run_id=run_id,
                run_directory=run_directory,
                manifest_path=manifest_path,
                latest_manifest_path=latest_manifest_path,
                manifest=existing,
            )
        if not request.resume and any(run_directory.iterdir()):
            raise FileExistsError(
                "incomplete out-of-core run exists and resume=false"
            )

        checkpoint_path = run_directory / "checkpoint.json"
        checkpoint = _load_checkpoint(
            checkpoint_path=checkpoint_path,
            run_id=run_id,
            source_manifest_hash=str(source_manifest["manifest_hash"]),
        )
        completed_years = {
            int(item["year"]): item
            for item in _mapping_sequence(
                checkpoint.get("completed_years", ()),
                field_name="completed_years",
            )
        }
        year_manifests: list[dict[str, Any]] = []
        for source_shard in source_shards:
            year_directory = (
                run_directory / f"year={source_shard.year:04d}"
            )
            existing_year = completed_years.get(source_shard.year)
            if (
                existing_year is not None
                and _verify_year_directory(
                    year_directory=year_directory,
                    expected_manifest_hash=str(
                        existing_year["manifest_hash"]
                    ),
                )
            ):
                year_manifests.append(
                    _read_json(year_directory / "manifest.json")
                )
                continue
            if year_directory.exists():
                raise RuntimeError(
                    "uncheckpointed finalized year directory exists: "
                    f"{year_directory}"
                )
            year_manifest = self._build_year(
                request=request,
                run_directory=run_directory,
                source_manifest=source_manifest,
                source_manifest_file_hash=source_manifest_file_hash,
                source_shard=source_shard,
                feature_ids=feature_ids,
                feature_scales=feature_scales,
                horizons=horizons,
            )
            year_manifests.append(year_manifest)
            completed_years[source_shard.year] = {
                "year": source_shard.year,
                "manifest_hash": year_manifest["manifest_hash"],
                "manifest_file_hash": _file_sha256(
                    year_directory / "manifest.json"
                ),
            }
            _atomic_write_json(
                checkpoint_path,
                {
                    "schema_version": CHECKPOINT_SCHEMA_VERSION,
                    "run_id": run_id,
                    "source_manifest_hash": source_manifest[
                        "manifest_hash"
                    ],
                    "completed_years": [
                        completed_years[year]
                        for year in sorted(completed_years)
                    ],
                    "complete": False,
                },
            )

        year_manifests = sorted(
            year_manifests,
            key=lambda item: int(item["year"]),
        )
        fold_manifests = self._build_fold_indexes(
            run_directory=run_directory,
            folds=folds,
            year_manifests=year_manifests,
            batch_size=request.batch_size,
        )
        manifest: dict[str, Any] = {
            "schema_version": STORE_SCHEMA_VERSION,
            "status": "complete",
            "run_id": run_id,
            "dataset_id": source_manifest["dataset_id"],
            "dataset_identity_hash": source_manifest[
                "dataset_identity_hash"
            ],
            "dataset_manifest_file_hash": source_manifest_file_hash,
            "source_training_manifest_hash": source_manifest[
                "manifest_hash"
            ],
            "source_training_manifest_file_hash": (
                source_manifest_file_hash
            ),
            "feature_registry_hash": source_manifest[
                "feature_registry_hash"
            ],
            "source_manifest_hashes": source_manifest[
                "source_manifest_hashes"
            ],
            "training_as_of": source_manifest["training_as_of"],
            "formal_source_only": request.lane == "formal",
            "research_shadow_included": (
                request.lane == "research_shadow"
            ),
            "research_only": request.lane == "research_shadow",
            "promotion_eligible": False,
            "feature_packs": feature_packs,
            "feature_family_coverage": _feature_family_coverage(
                feature_packs=feature_packs,
                feature_ids=feature_ids,
                year_manifests=year_manifests,
            ),
            "feature_ids": list(feature_ids),
            "feature_scales": list(feature_scales),
            "feature_count": len(feature_ids),
            "horizons": list(horizons),
            "target_fields": list(TARGET_FIELDS),
            "label_fields": list(LABEL_FIELDS),
            "row_count": sum(
                int(item["row_count"]) for item in year_manifests
            ),
            "years": year_manifests,
            "folds": fold_manifests,
            "fold_count": len(fold_manifests),
            "assembly_blockers": source_manifest.get(
                "assembly_blockers",
                [],
            ),
            # 轉存 teacher provenance，讓下游 OOC fit 能在任何模型 artifact
            # 建立前執行 eligibility gate；不把成熟後 label 變化當成輸入
            # 完整性的替代證據。
            "teacher_target_diagnostics": source_manifest.get(
                "teacher_target_diagnostics",
                {},
            ),
            # 只有具備三來源 readback、逐決策日覆蓋及 hash binding 的
            # provenance 才能讓下游 teacher gate 通過；缺值必須保留為
            # None，不能由 counters 推導出正式輸入完整性。
            "teacher_input_provenance": source_manifest.get(
                "teacher_input_provenance",
            ),
            "execution": {
                "streaming_jsonl": True,
                "annual_memmap": True,
                "sample_python_objects_retained": 0,
                "oof_python_objects_retained": 0,
                "batch_size": request.batch_size,
                "workers": request.workers,
                "memory_budget_mb": request.memory_budget_mb,
                "resume_supported": True,
                "checkpoint_file": checkpoint_path.name,
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
                "production_alpha_bp": 0,
                "formal_oos_allowed": False,
                "broker_order_allowed": False,
            },
            "store_identity": store_identity,
        }
        source_policy = source_manifest.get("portfolio_state_policy")
        if (
            isinstance(source_policy, Mapping)
            and source_policy.get("cash_only_fallback") is False
        ):
            manifest["portfolio_state_policy"] = dict(source_policy)
        formal_rule_history = source_manifest.get(
            "formal_rule_champion_history"
        )
        if isinstance(formal_rule_history, Mapping):
            manifest["formal_rule_champion_history"] = dict(
                formal_rule_history
            )
        manifest["manifest_hash"] = _sha256_json(manifest)
        _write_json(manifest_path, manifest)
        manifest_file_hash = _file_sha256(manifest_path)
        _atomic_write_json(
            checkpoint_path,
            {
                "schema_version": CHECKPOINT_SCHEMA_VERSION,
                "run_id": run_id,
                "source_manifest_hash": source_manifest[
                    "manifest_hash"
                ],
                "completed_years": [
                    completed_years[year]
                    for year in sorted(completed_years)
                ],
                "complete": True,
                "manifest_hash": manifest["manifest_hash"],
                "manifest_file_hash": manifest_file_hash,
            },
        )
        _write_latest_pointer(
            latest_manifest_path=latest_manifest_path,
            run_id=run_id,
            manifest=manifest,
        )
        return _publication_from_manifest(
            run_id=run_id,
            run_directory=run_directory,
            manifest_path=manifest_path,
            latest_manifest_path=latest_manifest_path,
            manifest=manifest,
        )

    def _build_year(
        self,
        *,
        request: PortfolioMLOutOfCoreStoreRequest,
        run_directory: Path,
        source_manifest: Mapping[str, Any],
        source_manifest_file_hash: str,
        source_shard: _SourceShard,
        feature_ids: tuple[str, ...],
        feature_scales: tuple[int, ...],
        horizons: tuple[int, ...],
    ) -> dict[str, Any]:
        final_directory = (
            run_directory / f"year={source_shard.year:04d}"
        )
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".year-{source_shard.year:04d}-",
                dir=run_directory,
            )
        )
        values_path = staging / "features.values.i64"
        masks_path = staging / "features.masks.u8"
        targets_path = staging / "targets.i32"
        labels_path = staging / "labels.i32"
        label_masks_path = staging / "labels.masks.u8"
        rows_path = staging / "rows.sqlite"
        row_count = source_shard.sample_count
        feature_count = len(feature_ids)
        label_width = len(horizons) * len(LABEL_FIELDS)
        values = np.memmap(
            values_path,
            dtype=VALUE_DTYPE,
            mode="w+",
            shape=(row_count, feature_count),
        )
        masks = np.memmap(
            masks_path,
            dtype=MASK_DTYPE,
            mode="w+",
            shape=(row_count, feature_count),
        )
        targets = np.memmap(
            targets_path,
            dtype=TARGET_DTYPE,
            mode="w+",
            shape=(row_count, len(TARGET_FIELDS)),
        )
        labels = np.memmap(
            labels_path,
            dtype=LABEL_DTYPE,
            mode="w+",
            shape=(row_count, label_width),
        )
        label_masks = np.memmap(
            label_masks_path,
            dtype=MASK_DTYPE,
            mode="w+",
            shape=(row_count, label_width),
        )
        values[:] = 0
        masks[:] = 1
        targets[:] = 0
        labels[:] = 0
        label_masks[:] = 1
        connection = sqlite3.connect(rows_path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(
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
        feature_position = {
            feature_id: index
            for index, feature_id in enumerate(feature_ids)
        }
        observed_counts = np.zeros(feature_count, dtype=np.int64)
        horizon_position = {
            horizon: index for index, horizon in enumerate(horizons)
        }
        row_batch: list[tuple[object, ...]] = []
        content_digest = hashlib.sha256()
        emitted = 0
        header: Mapping[str, Any] | None = None
        try:
            if _file_sha256(source_shard.path) != (
                source_shard.compressed_sha256
            ):
                raise ValueError(
                    f"source shard compressed hash mismatch: "
                    f"{source_shard.path}"
                )
            with gzip.open(source_shard.path, "rb") as stream:
                for line_number, raw_line in enumerate(stream, start=1):
                    if not raw_line.strip():
                        continue
                    content_digest.update(raw_line)
                    try:
                        decoded = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise ValueError(
                            "invalid source training JSONL at "
                            f"{source_shard.path}:{line_number}"
                        ) from exc
                    record = _as_mapping(
                        decoded,
                        field_name="training record",
                    )
                    record_type = record.get("record_type")
                    if record_type == "header":
                        if header is not None or emitted:
                            raise ValueError(
                                "source header must be the first record"
                            )
                        header = record
                        _validate_source_header(
                            header=header,
                            source_manifest=source_manifest,
                            year=source_shard.year,
                        )
                        continue
                    if record_type != "sample" or header is None:
                        raise ValueError(
                            "source record must be header then samples"
                        )
                    sample_payload = _as_mapping(
                        record.get("sample"),
                        field_name="sample",
                    )
                    sample = _parse_sample(sample_payload)
                    if emitted >= row_count:
                        raise ValueError(
                            "source shard exceeds declared sample_count"
                        )
                    row = sample.row
                    if (
                        row.dataset_identity_hash
                        != source_manifest["dataset_identity_hash"]
                    ):
                        raise ValueError(
                            "sample dataset identity hash mismatch"
                        )
                    if (
                        row.feature_registry_hash
                        != source_manifest["feature_registry_hash"]
                    ):
                        raise ValueError(
                            "sample feature registry hash mismatch"
                        )
                    if row.decision_at[:4] != f"{source_shard.year:04d}":
                        raise ValueError(
                            "sample decision year mismatches source shard"
                        )
                    features_by_id = {
                        feature.feature_id: feature
                        for feature in row.features
                    }
                    if set(features_by_id) != set(feature_ids):
                        raise ValueError(
                            "sample feature set mismatches explicit registry"
                        )
                    for feature_id, position in feature_position.items():
                        feature = features_by_id[feature_id]
                        if feature.scale != feature_scales[position]:
                            raise ValueError(
                                f"feature scale drift: {feature_id}"
                            )
                        if feature.observed:
                            assert feature.value_int is not None
                            _require_int_range(
                                feature.value_int,
                                dtype=VALUE_DTYPE,
                                field_name=feature_id,
                            )
                            values[emitted, position] = feature.value_int
                            masks[emitted, position] = 0
                            observed_counts[position] += 1
                    row_targets = sample.row.targets
                    if row_targets is None:
                        raise ValueError(
                            "formal training sample requires targets"
                        )
                    symbol = row.symbol
                    target_weight = dict(
                        row_targets.target_weights.positions_bp
                    ).get(symbol, 0)
                    delta_weight = dict(
                        row_targets.delta_weights_bp
                    ).get(symbol, 0)
                    risk_contribution = dict(
                        row_targets.risk_contributions_bp
                    ).get(symbol, 0)
                    target_values = (
                        target_weight,
                        delta_weight,
                        risk_contribution,
                        row_targets.risky_budget_bp,
                        row_targets.cash_bp,
                        int(row_targets.rebalance_worthwhile),
                    )
                    for target_value in target_values:
                        _require_int_range(
                            target_value,
                            dtype=TARGET_DTYPE,
                            field_name="target",
                        )
                    targets[emitted, :] = target_values
                    labels_by_horizon = {
                        label.horizon_trading_days: label
                        for label in sample.horizon_labels
                    }
                    if set(labels_by_horizon) != set(horizons):
                        raise ValueError(
                            "sample horizon labels mismatch store horizons"
                        )
                    max_label_available_at = ""
                    max_horizon_end_date = ""
                    for horizon, horizon_index in horizon_position.items():
                        label = labels_by_horizon[horizon]
                        max_label_available_at = max(
                            max_label_available_at,
                            label.available_at,
                        )
                        max_horizon_end_date = max(
                            max_horizon_end_date,
                            label.horizon_end_date,
                        )
                        sector_value = (
                            0
                            if label.sector_excess_return_bp is None
                            else label.sector_excess_return_bp
                        )
                        label_values = (
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
                        start = horizon_index * len(LABEL_FIELDS)
                        for offset, label_value in enumerate(
                            label_values
                        ):
                            _require_int_range(
                                label_value,
                                dtype=LABEL_DTYPE,
                                field_name=(
                                    f"h{horizon}.{LABEL_FIELDS[offset]}"
                                ),
                            )
                            labels[emitted, start + offset] = label_value
                            label_masks[emitted, start + offset] = 0
                        if label.sector_excess_return_bp is None:
                            label_masks[emitted, start + 1] = 1
                    sample_hash = _sha256_json(sample_payload)
                    row_batch.append(
                        (
                            emitted,
                            row.row_id,
                            row.decision_at,
                            row.decision_at[:10],
                            row.symbol,
                            row.portfolio_state.state_hash,
                            row_targets.available_at,
                            max_label_available_at,
                            max_horizon_end_date,
                            sample_hash,
                        )
                    )
                    emitted += 1
                    if len(row_batch) >= request.batch_size:
                        _insert_row_batch(connection, row_batch)
                        row_batch.clear()
            if row_batch:
                _insert_row_batch(connection, row_batch)
            if emitted != row_count:
                raise ValueError(
                    "source shard sample_count mismatch: "
                    f"declared={row_count}; actual={emitted}"
                )
            if (
                _SHA256_PREFIX + content_digest.hexdigest()
                != source_shard.content_sha256
            ):
                raise ValueError(
                    f"source shard content hash mismatch: "
                    f"{source_shard.path}"
                )
            connection.commit()
            values.flush()
            masks.flush()
            targets.flush()
            labels.flush()
            label_masks.flush()
        except Exception:
            connection.close()
            del values, masks, targets, labels, label_masks
            _safe_remove_tree(staging, run_directory)
            raise
        connection.close()
        del values, masks, targets, labels, label_masks
        artifacts = _artifact_payloads(
            staging,
            (
                values_path,
                masks_path,
                targets_path,
                labels_path,
                label_masks_path,
                rows_path,
            ),
            workers=request.workers,
        )
        year_manifest: dict[str, Any] = {
            "schema_version": YEAR_SCHEMA_VERSION,
            "year": source_shard.year,
            "year_ordinal": source_shard.ordinal,
            "row_count": row_count,
            "feature_count": feature_count,
            "feature_values_shape": [row_count, feature_count],
            "feature_observed_counts": [
                int(value) for value in observed_counts
            ],
            "target_shape": [row_count, len(TARGET_FIELDS)],
            "label_shape": [row_count, len(horizons), len(LABEL_FIELDS)],
            "source_shard": {
                "path": source_shard.relative_path,
                "compressed_sha256": source_shard.compressed_sha256,
                "content_sha256": source_shard.content_sha256,
                "sample_count": source_shard.sample_count,
            },
            "source_training_manifest_file_hash": (
                source_manifest_file_hash
            ),
            "artifacts": artifacts,
            "complete": True,
        }
        year_manifest["manifest_hash"] = _sha256_json(year_manifest)
        _write_json(staging / "manifest.json", year_manifest)
        os.replace(staging, final_directory)
        return year_manifest

    def _build_fold_indexes(
        self,
        *,
        run_directory: Path,
        folds: tuple[dict[str, Any], ...],
        year_manifests: Sequence[Mapping[str, Any]],
        batch_size: int,
        year_rows_paths: Mapping[int, Path] | None = None,
    ) -> list[dict[str, Any]]:
        folds_directory = run_directory / "folds"
        folds_directory.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train_path = folds_directory / f"{fold_id}.train.refs.i64"
            test_path = folds_directory / f"{fold_id}.test.refs.i64"
            fold_manifest_path = (
                folds_directory / f"{fold_id}.manifest.json"
            )
            if fold_manifest_path.is_file():
                existing = _read_json(fold_manifest_path)
                if _verify_fold_manifest(
                    existing,
                    folds_directory=folds_directory,
                ):
                    results.append(existing)
                    continue
                raise ValueError(
                    f"existing fold index failed custody: {fold_id}"
                )
            train_partial = train_path.with_suffix(
                train_path.suffix + ".partial"
            )
            test_partial = test_path.with_suffix(
                test_path.suffix + ".partial"
            )
            train_count = 0
            test_count = 0
            train_digest = hashlib.sha256()
            test_digest = hashlib.sha256()
            with (
                train_partial.open("wb", buffering=1024 * 1024) as train_stream,
                test_partial.open("wb", buffering=1024 * 1024) as test_stream,
            ):
                for year_manifest in year_manifests:
                    year = int(year_manifest["year"])
                    ordinal = int(year_manifest["year_ordinal"])
                    rows_path = (
                        year_rows_paths[year]
                        if year_rows_paths is not None and year in year_rows_paths
                        else (
                            run_directory
                            / f"year={year:04d}"
                            / "rows.sqlite"
                        )
                    )
                    connection = sqlite3.connect(
                        f"file:{rows_path.as_posix()}?mode=ro",
                        uri=True,
                    )
                    connection.execute("PRAGMA query_only=ON")
                    cursor = connection.execute(
                        """
                        SELECT local_row_index, decision_date
                        FROM rows
                        ORDER BY local_row_index
                        """
                    )
                    while True:
                        rows = cursor.fetchmany(batch_size)
                        if not rows:
                            break
                        for local_row_index, decision_date_value in rows:
                            decision_date = str(decision_date_value)
                            encoded = struct.pack(
                                "<qq",
                                ordinal,
                                int(local_row_index),
                            )
                            if decision_date <= str(
                                fold["train_end_date"]
                            ):
                                train_stream.write(encoded)
                                train_digest.update(encoded)
                                train_count += 1
                            elif (
                                str(fold["test_start"])
                                <= decision_date
                                <= str(fold["test_end"])
                            ):
                                test_stream.write(encoded)
                                test_digest.update(encoded)
                                test_count += 1
                    connection.close()
                train_stream.flush()
                os.fsync(train_stream.fileno())
                test_stream.flush()
                os.fsync(test_stream.fileno())
            if train_count == 0 or test_count == 0:
                train_partial.unlink(missing_ok=True)
                test_partial.unlink(missing_ok=True)
                raise ValueError(
                    f"fold requires non-empty train and test refs: {fold_id}"
                )
            os.replace(train_partial, train_path)
            os.replace(test_partial, test_path)
            fold_manifest: dict[str, Any] = {
                "schema_version": FOLD_INDEX_SCHEMA_VERSION,
                **fold,
                "train": {
                    "path": train_path.name,
                    "row_count": train_count,
                    "shape": [train_count, 2],
                    "dtype": ROW_REF_DTYPE.str,
                    "content_sha256": (
                        _SHA256_PREFIX + train_digest.hexdigest()
                    ),
                    "file_sha256": _file_sha256(train_path),
                },
                "test": {
                    "path": test_path.name,
                    "row_count": test_count,
                    "shape": [test_count, 2],
                    "dtype": ROW_REF_DTYPE.str,
                    "content_sha256": (
                        _SHA256_PREFIX + test_digest.hexdigest()
                    ),
                    "file_sha256": _file_sha256(test_path),
                },
            }
            fold_manifest["manifest_hash"] = _sha256_json(
                fold_manifest
            )
            _write_json(fold_manifest_path, fold_manifest)
            results.append(fold_manifest)
        return results


def _insert_row_batch(
    connection: sqlite3.Connection,
    rows: Sequence[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT INTO rows(
            local_row_index, row_id, decision_at, decision_date, symbol,
            portfolio_state_hash, target_available_at,
            max_label_available_at, max_horizon_end_date, sample_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _feature_family_coverage(
    *,
    feature_packs: Sequence[Mapping[str, Any]],
    feature_ids: tuple[str, ...],
    year_manifests: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    positions = {
        feature_id: index for index, feature_id in enumerate(feature_ids)
    }
    observed_by_position = [0 for _ in feature_ids]
    total_rows = 0
    for year_manifest in year_manifests:
        row_count = _required_integer(
            year_manifest.get("row_count"),
            field_name="year.row_count",
        )
        counts = _integer_tuple(
            year_manifest.get("feature_observed_counts"),
            field_name="year.feature_observed_counts",
        )
        if len(counts) != len(feature_ids):
            raise ValueError("year feature observed counts width mismatch")
        total_rows += row_count
        for position, count in enumerate(counts):
            if count < 0 or count > row_count:
                raise ValueError("year feature observed count out of range")
            observed_by_position[position] += count
    result: list[dict[str, Any]] = []
    for pack in feature_packs:
        family_id = _required_text(
            pack.get("pack_id"),
            field_name="pack_id",
        )
        pack_features = _text_tuple(
            pack.get("feature_ids"),
            field_name="feature_ids",
        )
        observed_count = sum(
            observed_by_position[positions[feature_id]]
            for feature_id in pack_features
        )
        possible_count = total_rows * len(pack_features)
        coverage_bp = (
            0
            if possible_count == 0
            else (observed_count * 10_000) // possible_count
        )
        result.append(
            {
                "family_id": family_id,
                "feature_count": len(pack_features),
                "observed_count": observed_count,
                "possible_count": possible_count,
                "coverage_bp": coverage_bp,
            }
        )
    return result


def _feature_packs(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    seen_pack_ids: set[str] = set()
    for payload in _mapping_sequence(
        manifest.get("feature_packs"),
        field_name="feature_packs",
    ):
        pack_id = _required_text(
            payload.get("pack_id"),
            field_name="pack_id",
        )
        if pack_id in seen_pack_ids:
            raise ValueError("feature pack ids must be unique")
        seen_pack_ids.add(pack_id)
        feature_ids = _text_tuple(
            payload.get("feature_ids"),
            field_name=f"{pack_id}.feature_ids",
        )
        if "*" in feature_ids:
            raise ValueError("wildcard feature packs are forbidden")
        result.append(
            {
                "pack_id": pack_id,
                "feature_ids": list(feature_ids),
            }
        )
    if not result:
        raise ValueError("feature_packs are required")
    return tuple(result)


def _feature_scales(
    manifest: Mapping[str, Any],
    *,
    feature_ids: tuple[str, ...],
) -> tuple[int, ...]:
    registry = _as_mapping(
        manifest.get("feature_registry"),
        field_name="feature_registry",
    )
    definitions = {
        _required_text(item.get("feature_id"), field_name="feature_id"): item
        for item in _mapping_sequence(
            registry.get("features"),
            field_name="feature_registry.features",
        )
    }
    unknown_registered = set(definitions) - set(feature_ids)
    if unknown_registered:
        raise ValueError(
            "feature registry contains fields outside explicit feature packs"
        )
    result: list[int] = []
    for feature_id in feature_ids:
        definition = definitions.get(feature_id)
        if definition is None:
            if not _is_assembler_data_quality_feature(feature_id):
                raise ValueError(
                    "feature lacks registry provenance or an explicit "
                    f"assembler-derived contract: {feature_id}"
                )
            result.append(1)
            continue
        scale = definition.get("scale")
        if isinstance(scale, bool) or not isinstance(scale, int) or scale <= 0:
            raise TypeError(f"{feature_id}.scale must be positive integer")
        result.append(scale)
    return tuple(result)


def _is_assembler_data_quality_feature(feature_id: str) -> bool:
    """只接受 assembler 公開契約內、scale=1 的確定性品質欄位。"""

    if not feature_id.startswith("data_quality."):
        return False
    return feature_id.rsplit(".", 1)[-1] in {
        "coverage_bp",
        "max_available_lag_days",
        "missing_count",
        "quality_blocked_count",
        "stale_count",
    }


def _folds(
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    previous_test_end = ""
    for payload in _mapping_sequence(
        manifest.get("folds"),
        field_name="folds",
    ):
        fold_id = _required_text(
            payload.get("fold_id"),
            field_name="fold_id",
        )
        train_end_date = _required_text(
            payload.get("train_end_date"),
            field_name="train_end_date",
        )
        test_start = _required_text(
            payload.get("test_start"),
            field_name="test_start",
        )
        test_end = _required_text(
            payload.get("test_end"),
            field_name="test_end",
        )
        purge_trading_days = _required_integer(
            payload.get("purge_trading_days"),
            field_name="purge_trading_days",
        )
        embargo_trading_days = _required_integer(
            payload.get("embargo_trading_days"),
            field_name="embargo_trading_days",
        )
        fold = {
            "fold_id": fold_id,
            "train_end_date": train_end_date,
            "test_start": test_start,
            "test_end": test_end,
            "purge_trading_days": purge_trading_days,
            "embargo_trading_days": embargo_trading_days,
        }
        if purge_trading_days < 60:
            raise ValueError("out-of-core folds require purge >= 60")
        if embargo_trading_days < 5:
            raise ValueError("out-of-core folds require embargo >= 5")
        if not (train_end_date < test_start <= test_end):
            raise ValueError("fold date ordering is invalid")
        if previous_test_end and test_start <= previous_test_end:
            raise ValueError("fold test windows must be strictly ordered")
        previous_test_end = test_end
        result.append(fold)
    if len(result) < 4:
        raise ValueError("out-of-core store requires at least four folds")
    return tuple(result)


def _source_shards(
    *,
    source_manifest_path: Path,
    manifest: Mapping[str, Any],
) -> tuple[_SourceShard, ...]:
    root = source_manifest_path.parent.resolve()
    result: list[_SourceShard] = []
    seen_years: set[int] = set()
    for ordinal, item in enumerate(
        sorted(
            _mapping_sequence(
                manifest.get("shards"),
                field_name="shards",
            ),
            key=lambda value: (
                _required_integer(
                    value.get("year"),
                    field_name="year",
                ),
                str(value.get("path", "")),
            ),
        )
    ):
        year = _required_integer(item.get("year"), field_name="year")
        if year in seen_years:
            raise ValueError(
                "out-of-core store requires one source shard per year"
            )
        seen_years.add(year)
        relative_path = _required_text(
            item.get("path"),
            field_name="shard.path",
        )
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("source shard path escapes publication root")
        result.append(
            _SourceShard(
                ordinal=ordinal,
                year=year,
                path=path,
                relative_path=relative_path,
                sample_count=_required_integer(
                    item.get("sample_count"),
                    field_name="sample_count",
                ),
                compressed_sha256=_required_sha256(
                    item.get("compressed_sha256"),
                    field_name="compressed_sha256",
                ),
                content_sha256=_required_sha256(
                    item.get("content_sha256"),
                    field_name="content_sha256",
                ),
            )
        )
    if not result:
        raise ValueError("source shards are required")
    return tuple(result)


def _validate_source_manifest(
    manifest: Mapping[str, Any],
    *,
    lane: Literal["formal", "research_shadow"],
) -> None:
    if manifest.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError(
            f"source schema_version must equal {SOURCE_SCHEMA_VERSION}"
        )
    if manifest.get("direct_training_input") is not True:
        raise ValueError("source manifest must authorize direct training input")
    if manifest.get("formal_oos_allowed") is not False:
        raise ValueError("source manifest formal_oos_allowed must remain false")
    if lane == "formal":
        if manifest.get("research_only") is not False:
            raise ValueError(
                "formal out-of-core lane requires explicit research_only=false"
            )
        if manifest.get("formal_consumer_compatible") is not True:
            raise ValueError(
                "formal out-of-core lane requires "
                "formal_consumer_compatible=true"
            )
        if manifest.get("research_shadow_included") is not False:
            raise ValueError(
                "formal out-of-core lane requires "
                "research_shadow_included=false"
            )
        if manifest.get("formal_source_only") is not True:
            raise ValueError(
                "formal out-of-core lane requires formal_source_only=true"
            )
        if manifest.get("promotion_eligible") is not False:
            raise ValueError(
                "formal source promotion_eligible must remain false"
            )
    else:
        if manifest.get("research_only") is not True:
            raise ValueError(
                "research-shadow lane requires research_only=true"
            )
        if manifest.get("promotion_eligible") is not False:
            raise ValueError(
                "research-shadow lane requires promotion_eligible=false"
            )
        if manifest.get("formal_consumer_compatible") is not False:
            raise ValueError(
                "research-shadow lane must reject formal consumers"
            )
    expected_hash = _required_sha256(
        manifest.get("manifest_hash"),
        field_name="manifest_hash",
    )
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_hash:
        raise ValueError("source manifest logical hash mismatch")
    for field_name in (
        "dataset_id",
        "dataset_identity_hash",
        "feature_registry_hash",
        "training_as_of",
    ):
        _required_text(manifest.get(field_name), field_name=field_name)
    _required_sha256(
        manifest.get("dataset_identity_hash"),
        field_name="dataset_identity_hash",
    )
    _required_sha256(
        manifest.get("feature_registry_hash"),
        field_name="feature_registry_hash",
    )


def _validate_source_header(
    *,
    header: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    year: int,
) -> None:
    if header.get("record_type") != "header":
        raise ValueError("invalid source header record_type")
    if header.get("schema_version") != SOURCE_RECORD_SCHEMA_VERSION:
        raise ValueError("invalid source header schema_version")
    if header.get("direct_training_input") is not True:
        raise ValueError("source header direct_training_input must be true")
    expected_pairs = (
        ("dataset_id", "dataset_id"),
        ("dataset_identity_hash", "dataset_identity_hash"),
        ("feature_registry_hash", "feature_registry_hash"),
        ("training_as_of", "training_as_of"),
        ("horizons", "horizons"),
        ("feature_packs", "feature_packs"),
        ("folds", "folds"),
        ("source_manifest_hashes", "source_manifest_hashes"),
    )
    for header_field, manifest_field in expected_pairs:
        if _canonical_json(header.get(header_field)) != _canonical_json(
            source_manifest.get(manifest_field)
        ):
            raise ValueError(
                f"source header {header_field} mismatches manifest"
            )
    if header.get("year") != year:
        raise ValueError("source header year mismatches shard")


def _validate_completed_store(
    *,
    manifest: Mapping[str, Any],
    run_directory: Path,
    expected_identity: Mapping[str, Any],
) -> None:
    if manifest.get("schema_version") != STORE_SCHEMA_VERSION:
        raise ValueError("existing store schema mismatch")
    if manifest.get("status") != "complete":
        raise ValueError("existing store is not complete")
    if _canonical_json(manifest.get("store_identity")) != _canonical_json(
        expected_identity
    ):
        raise ValueError("existing store identity mismatch")
    expected_hash = _required_sha256(
        manifest.get("manifest_hash"),
        field_name="manifest_hash",
    )
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_hash:
        raise ValueError("existing store manifest hash mismatch")
    for year_manifest in _mapping_sequence(
        manifest.get("years"),
        field_name="years",
    ):
        year_directory = (
            run_directory / f"year={int(year_manifest['year']):04d}"
        )
        if not _verify_year_directory(
            year_directory=year_directory,
            expected_manifest_hash=str(year_manifest["manifest_hash"]),
        ):
            raise ValueError("existing store year custody mismatch")
    for fold_manifest in _mapping_sequence(
        manifest.get("folds"),
        field_name="folds",
    ):
        if not _verify_fold_manifest(
            fold_manifest,
            folds_directory=run_directory / "folds",
        ):
            raise ValueError("existing store fold custody mismatch")


def _verify_year_directory(
    *,
    year_directory: Path,
    expected_manifest_hash: str,
) -> bool:
    manifest_path = year_directory / "manifest.json"
    if not manifest_path.is_file():
        return False
    manifest = _read_json(manifest_path)
    if manifest.get("manifest_hash") != expected_manifest_hash:
        return False
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_manifest_hash:
        return False
    for artifact in _mapping_sequence(
        manifest.get("artifacts"),
        field_name="artifacts",
    ):
        path = year_directory / str(artifact["path"])
        if not path.is_file() or _file_sha256(path) != artifact["file_sha256"]:
            return False
    return True


def _verify_fold_manifest(
    manifest: Mapping[str, Any],
    *,
    folds_directory: Path,
) -> bool:
    expected_hash = manifest.get("manifest_hash")
    if not isinstance(expected_hash, str):
        return False
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_hash:
        return False
    for split in ("train", "test"):
        item = _as_mapping(manifest.get(split), field_name=split)
        path = folds_directory / str(item["path"])
        if not path.is_file() or _file_sha256(path) != item["file_sha256"]:
            return False
    return True


def _artifact_payloads(
    root: Path,
    paths: Sequence[Path],
    *,
    workers: int = 1,
) -> list[dict[str, Any]]:
    def one(path: Path) -> dict[str, Any]:
        return {
            "path": path.relative_to(root).as_posix(),
            "byte_count": path.stat().st_size,
            "file_sha256": _file_sha256(path),
        }

    with ThreadPoolExecutor(max_workers=min(workers, len(paths) or 1)) as pool:
        return list(pool.map(one, paths))


def _load_checkpoint(
    *,
    checkpoint_path: Path,
    run_id: str,
    source_manifest_hash: str,
) -> dict[str, Any]:
    if not checkpoint_path.is_file():
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "run_id": run_id,
            "source_manifest_hash": source_manifest_hash,
            "completed_years": [],
            "complete": False,
        }
    payload = _read_json(checkpoint_path)
    if (
        payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
        or payload.get("run_id") != run_id
        or payload.get("source_manifest_hash") != source_manifest_hash
    ):
        raise ValueError("checkpoint identity mismatch")
    return payload


def _write_latest_pointer(
    *,
    latest_manifest_path: Path,
    run_id: str,
    manifest: Mapping[str, Any],
) -> None:
    _atomic_write_json(
        latest_manifest_path,
        {
            "schema_version": "portfolio-ml-ooc-pointer.v1",
            "run_id": run_id,
            "manifest_path": f"runs/{run_id}/manifest.json",
            "manifest_hash": manifest["manifest_hash"],
        },
    )


def _publication_from_manifest(
    *,
    run_id: str,
    run_directory: Path,
    manifest_path: Path,
    latest_manifest_path: Path,
    manifest: Mapping[str, Any],
) -> PortfolioMLOutOfCoreStorePublication:
    return PortfolioMLOutOfCoreStorePublication(
        run_id=run_id,
        run_directory=run_directory,
        manifest_path=manifest_path,
        latest_manifest_path=latest_manifest_path,
        manifest_hash=str(manifest["manifest_hash"]),
        manifest_file_hash=_file_sha256(manifest_path),
        row_count=int(manifest["row_count"]),
        feature_count=int(manifest["feature_count"]),
        fold_count=int(manifest["fold_count"]),
    )


def _require_int_range(
    value: object,
    *,
    dtype: np.dtype[Any],
    field_name: str,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    limits = np.iinfo(dtype)
    if not int(limits.min) <= value <= int(limits.max):
        raise OverflowError(f"{field_name} exceeds {dtype.str}")


def _required_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    return value


def _integer_tuple(value: object, *, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(
        _required_integer(item, field_name=field_name)
        for item in value
    )


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value


def _required_sha256(value: object, *, field_name: str) -> str:
    text = _required_text(value, field_name=field_name)
    if (
        len(text) != 71
        or not text.startswith(_SHA256_PREFIX)
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise ValueError(f"{field_name} must be canonical sha256")
    return text


def _text_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a sequence")
    result = tuple(
        _required_text(item, field_name=field_name) for item in value
    )
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _mapping_sequence(
    value: object,
    *,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(
        _as_mapping(item, field_name=field_name) for item in value
    )


def _as_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


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
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise TypeError(f"JSON object required: {path}")
    return decoded


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{os.getpid()}.staged")
    _write_json(staged, payload)
    os.replace(staged, path)


def _safe_remove_tree(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if (
        resolved.parent != root
        or not resolved.name.startswith(".year-")
    ):
        raise ValueError(f"refusing unsafe staging cleanup: {resolved}")
    shutil.rmtree(resolved)
