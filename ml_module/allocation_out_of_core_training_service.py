"""全市場配置型 ML 的 out-of-core 訓練與 OOF custody。

本模組只接受 :mod:`data_module.portfolio_ml_out_of_core_store` 建立的正式
數值 store。資料處理單位固定為 ``fold -> feature pack -> horizon ->
algorithm``；任何時點都不會建立全市場 Python sample、OOF dataclass 或模型
物件集合。

公開與持久化決策值皆為整數 bp。NumPy／scikit-learn 浮點只存在於本模組的
模型數值邊界，離開邊界前即量化回 int32。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_EVEN
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence, cast

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)

from data_module.portfolio_ml_out_of_core_store import (
    LABEL_FIELDS,
    ROW_REF_DTYPE,
    STORE_SCHEMA_VERSION,
    TARGET_FIELDS,
)
from ml_module.allocation_training_service import (
    CLASSIFICATION_EXPERT_HEADS,
    EXPERT_HEAD_IDS,
    EXPERT_VECTOR_WIDTH,
    REGRESSION_EXPERT_HEADS,
)
from ml_module.ooc_cross_fitted_calibration import (
    cross_fitted_binned_calibration,
)


TRAINING_SCHEMA_VERSION = "allocation-ooc-training.v5"
EXPERT_SCHEMA_VERSION = "allocation-ooc-expert.v5"
META_SCHEMA_VERSION = "allocation-ooc-meta.v3"
AUDIT_SCHEMA_VERSION = "allocation-ooc-custody.v1"
OOF_DTYPE = np.dtype("<i4")
FLOAT_DTYPE = np.dtype("<f4")
_SHA256_PREFIX = "sha256:"
_REGRESSION_LABEL_POSITIONS = (0, 1, 3, 4, 5, 6, 7)
_CLASSIFICATION_LABEL_POSITIONS = (2, 8)
_SIGNED_HEADS = frozenset(
    {"expected_excess_return_bp", "expected_sector_excess_return_bp"}
)
# Keep the exact training contract deterministic while preventing the wide
# final-meta training matrix from being materialized as one full memmap.  The
# sample is selected evenly across the causal training rows; all means and
# variances still use the full row stream below.
_PREPROCESSOR_MAX_MEDIAN_SAMPLE_ROWS = 100_000


@dataclass(frozen=True)
class AllocationOutOfCoreTrainingRequest:
    store_manifest_path: Path
    output_root: Path
    algorithms: tuple[str, ...] = (
        "ridge_logistic",
        "hist_gradient_boosting",
    )
    horizons: tuple[int, ...] = ()
    batch_size: int = 8_192
    workers: int = 1
    memory_budget_mb: int = 4_096
    ridge_alpha_bp: int = 100
    logistic_iterations: int = 6
    hgb_max_iter: int = 100
    hgb_max_fit_rows: int = 250_000
    resume: bool = True

    def __post_init__(self) -> None:
        if (
            not self.algorithms
            or len(self.algorithms) != len(set(self.algorithms))
            or not set(self.algorithms).issubset(
                {"ridge_logistic", "hist_gradient_boosting"}
            )
        ):
            raise ValueError("algorithms must be unique supported algorithms")
        if len(self.horizons) != len(set(self.horizons)):
            raise ValueError("horizons must be unique")
        for field_name in (
            "batch_size",
            "workers",
            "memory_budget_mb",
            "ridge_alpha_bp",
            "logistic_iterations",
            "hgb_max_iter",
            "hgb_max_fit_rows",
        ):
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
        if self.ridge_alpha_bp > 100_000:
            raise ValueError("ridge_alpha_bp is implausibly large")
        if self.logistic_iterations > 50:
            raise ValueError("logistic_iterations must not exceed 50")
        if self.hgb_max_iter > 2_000:
            raise ValueError("hgb_max_iter must not exceed 2000")
        if self.hgb_max_fit_rows > 2_000_000:
            raise ValueError("hgb_max_fit_rows must not exceed 2000000")
        if not isinstance(self.resume, bool):
            raise TypeError("resume must be bool")


@dataclass(frozen=True)
class AllocationOutOfCoreTrainingPublication:
    run_id: str
    run_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    manifest_file_hash: str
    base_expert_count: int
    meta_fold_count: int
    production_alpha_bp: int = 0
    formal_oos_allowed: bool = False


@dataclass(frozen=True)
class _LinearBoundaryModel:
    """可 joblib 序列化的線性數值邊界；輸入／輸出不離開訓練模組。"""

    head_id: str
    medians: NDArray[np.float64]
    means: NDArray[np.float64]
    standard_deviations: NDArray[np.float64]
    coefficients: NDArray[np.float64]
    intercept: float
    classifier: bool
    constant_probability: float | None = None

    def predict_numeric(
        self,
        raw_matrix: NDArray[np.floating[Any]],
    ) -> NDArray[np.float64]:
        if self.constant_probability is not None:
            return np.full(
                raw_matrix.shape[0],
                self.constant_probability,
                dtype=np.float64,
            )
        transformed = _transform_linear_batch(
            raw_matrix,
            medians=self.medians,
            means=self.means,
            standard_deviations=self.standard_deviations,
        )
        values = transformed @ self.coefficients + self.intercept
        if self.classifier:
            return _sigmoid(values)
        return np.asarray(values, dtype=np.float64)


@dataclass(frozen=True)
class _MetaTrainingSelection:
    fold_id: str
    selected_positions: NDArray[np.int64]
    selected_refs: NDArray[np.int64]


@dataclass
class _RegressionAccumulator:
    gram: NDArray[np.float64]
    xty: NDArray[np.float64]
    count: int = 0


@dataclass(frozen=True)
class _YearStore:
    ordinal: int
    year: int
    row_count: int
    directory: Path
    feature_count: int
    label_width: int
    values: np.memmap
    masks: np.memmap
    targets: np.memmap
    labels: np.memmap
    label_masks: np.memmap


class _NumericStore:
    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path.resolve()
        self.run_directory = self.manifest_path.parent
        self.manifest = _read_json(self.manifest_path)
        _validate_store_manifest(
            manifest=self.manifest,
            manifest_path=self.manifest_path,
        )
        self.manifest_file_hash = _file_sha256(self.manifest_path)
        self.feature_ids = _text_tuple(
            self.manifest.get("feature_ids"),
            field_name="feature_ids",
        )
        self.feature_scales = _integer_tuple(
            self.manifest.get("feature_scales"),
            field_name="feature_scales",
        )
        self.horizons = _integer_tuple(
            self.manifest.get("horizons"),
            field_name="horizons",
        )
        self.feature_positions = {
            feature_id: index
            for index, feature_id in enumerate(self.feature_ids)
        }
        self.horizon_positions = {
            horizon: index for index, horizon in enumerate(self.horizons)
        }
        self.feature_packs = tuple(
            {
                "pack_id": _required_text(
                    item.get("pack_id"),
                    field_name="pack_id",
                ),
                "feature_ids": list(
                    _text_tuple(
                        item.get("feature_ids"),
                        field_name="feature_ids",
                    )
                ),
            }
            for item in _mapping_sequence(
                self.manifest.get("feature_packs"),
                field_name="feature_packs",
            )
        )
        self.feature_family_coverage_bp = {
            _required_text(
                item.get("family_id"),
                field_name="feature_family_coverage.family_id",
            ): _required_integer(
                item.get("coverage_bp"),
                field_name="feature_family_coverage.coverage_bp",
            )
            for item in _mapping_sequence(
                self.manifest.get("feature_family_coverage"),
                field_name="feature_family_coverage",
            )
        }
        if set(self.feature_family_coverage_bp) != {
            str(item["pack_id"]) for item in self.feature_packs
        }:
            raise ValueError(
                "feature family coverage must exactly match feature packs"
            )
        self.folds = tuple(
            dict(item)
            for item in _mapping_sequence(
                self.manifest.get("folds"),
                field_name="folds",
            )
        )
        years: list[_YearStore] = []
        for item in _mapping_sequence(
            self.manifest.get("years"),
            field_name="years",
        ):
            ordinal = _required_integer(
                item.get("year_ordinal"),
                field_name="year_ordinal",
            )
            year = _required_integer(item.get("year"), field_name="year")
            row_count = _required_integer(
                item.get("row_count"),
                field_name="row_count",
            )
            directory = self.run_directory / f"year={year:04d}"
            label_width = len(self.horizons) * len(LABEL_FIELDS)
            years.append(
                _YearStore(
                    ordinal=ordinal,
                    year=year,
                    row_count=row_count,
                    directory=directory,
                    feature_count=len(self.feature_ids),
                    label_width=label_width,
                    values=np.memmap(
                        directory / "features.values.i64",
                        dtype="<i8",
                        mode="r",
                        shape=(row_count, len(self.feature_ids)),
                    ),
                    masks=np.memmap(
                        directory / "features.masks.u8",
                        dtype="u1",
                        mode="r",
                        shape=(row_count, len(self.feature_ids)),
                    ),
                    targets=np.memmap(
                        directory / "targets.i32",
                        dtype="<i4",
                        mode="r",
                        shape=(row_count, len(TARGET_FIELDS)),
                    ),
                    labels=np.memmap(
                        directory / "labels.i32",
                        dtype="<i4",
                        mode="r",
                        shape=(row_count, label_width),
                    ),
                    label_masks=np.memmap(
                        directory / "labels.masks.u8",
                        dtype="u1",
                        mode="r",
                        shape=(row_count, label_width),
                    ),
                )
            )
        if tuple(year.ordinal for year in years) != tuple(range(len(years))):
            raise ValueError("year ordinals must be contiguous and ordered")
        self.years = tuple(years)

    def open_fold_refs(self, fold: Mapping[str, Any], split: str) -> np.memmap:
        item = _as_mapping(fold.get(split), field_name=split)
        row_count = _required_integer(
            item.get("row_count"),
            field_name=f"{split}.row_count",
        )
        path = self.run_directory / "folds" / _required_text(
            item.get("path"),
            field_name=f"{split}.path",
        )
        if _file_sha256(path) != _required_sha256(
            item.get("file_sha256"),
            field_name=f"{split}.file_sha256",
        ):
            raise ValueError(f"{split} fold refs hash mismatch")
        return np.memmap(
            path,
            dtype=ROW_REF_DTYPE,
            mode="r",
            shape=(row_count, 2),
        )

    def feature_positions_for_pack(
        self,
        pack: Mapping[str, Any],
    ) -> tuple[int, ...]:
        return tuple(
            self.feature_positions[feature_id]
            for feature_id in _text_tuple(
                pack.get("feature_ids"),
                field_name="feature_ids",
            )
        )

    def read_feature_batch(
        self,
        refs: NDArray[np.integer[Any]],
        positions: tuple[int, ...],
    ) -> NDArray[np.float32]:
        result = np.empty((len(refs), len(positions)), dtype=np.float32)
        position_array = np.asarray(positions, dtype=np.int64)
        scales = np.asarray(
            [self.feature_scales[position] for position in positions],
            dtype=np.float64,
        )
        for ordinal_value in np.unique(refs[:, 0]):
            ordinal = int(ordinal_value)
            if ordinal < 0 or ordinal >= len(self.years):
                raise ValueError("row ref year ordinal is out of range")
            selected = np.flatnonzero(refs[:, 0] == ordinal_value)
            local = np.asarray(refs[selected, 1], dtype=np.int64)
            year = self.years[ordinal]
            if np.any(local < 0) or np.any(local >= year.row_count):
                raise ValueError("row ref local index is out of range")
            values = np.asarray(
                year.values[np.ix_(local, position_array)],
                dtype=np.float64,
            )
            masks = np.asarray(
                year.masks[np.ix_(local, position_array)],
                dtype=np.uint8,
            )
            values /= scales
            values[masks != 0] = np.nan
            result[selected, :] = values.astype(np.float32)
        return result

    def read_label_batch(
        self,
        refs: NDArray[np.integer[Any]],
        horizon: int,
    ) -> tuple[NDArray[np.int32], NDArray[np.uint8]]:
        horizon_position = self.horizon_positions[horizon]
        start = horizon_position * len(LABEL_FIELDS)
        stop = start + len(LABEL_FIELDS)
        values = np.empty((len(refs), len(LABEL_FIELDS)), dtype=np.int32)
        masks = np.empty((len(refs), len(LABEL_FIELDS)), dtype=np.uint8)
        for ordinal_value in np.unique(refs[:, 0]):
            ordinal = int(ordinal_value)
            selected = np.flatnonzero(refs[:, 0] == ordinal_value)
            local = np.asarray(refs[selected, 1], dtype=np.int64)
            year = self.years[ordinal]
            values[selected, :] = year.labels[local, start:stop]
            masks[selected, :] = year.label_masks[local, start:stop]
        return values, masks

    def read_target_batch(
        self,
        refs: NDArray[np.integer[Any]],
    ) -> NDArray[np.int32]:
        values = np.empty((len(refs), len(TARGET_FIELDS)), dtype=np.int32)
        for ordinal_value in np.unique(refs[:, 0]):
            ordinal = int(ordinal_value)
            selected = np.flatnonzero(refs[:, 0] == ordinal_value)
            local = np.asarray(refs[selected, 1], dtype=np.int64)
            values[selected, :] = self.years[ordinal].targets[local, :]
        return values

    def iter_decision_dates(
        self,
        refs: NDArray[np.integer[Any]],
    ) -> Iterable[tuple[int, str, str]]:
        """依 ref 順序串流 ``(position, decision_date, row_id)``。"""

        position = 0
        for year in self.years:
            year_positions = np.flatnonzero(refs[:, 0] == year.ordinal)
            if not len(year_positions):
                continue
            local_indexes = np.asarray(
                refs[year_positions, 1],
                dtype=np.int64,
            )
            connection = sqlite3.connect(
                f"file:{(year.directory / 'rows.sqlite').as_posix()}?mode=ro",
                uri=True,
            )
            connection.execute("PRAGMA query_only=ON")
            cursor = connection.execute(
                """
                SELECT local_row_index, decision_date, row_id
                FROM rows
                ORDER BY local_row_index
                """
            )
            target_cursor = 0
            for local_row_index, decision_date, row_id in cursor:
                while (
                    target_cursor < len(local_indexes)
                    and int(local_indexes[target_cursor]) < int(local_row_index)
                ):
                    connection.close()
                    raise ValueError("row refs are not present in rows custody")
                if (
                    target_cursor < len(local_indexes)
                    and int(local_indexes[target_cursor]) == int(local_row_index)
                ):
                    expected_position = int(year_positions[target_cursor])
                    if expected_position != position:
                        connection.close()
                        raise ValueError(
                            "fold refs must be ordered by year and local row"
                        )
                    yield position, str(decision_date), str(row_id)
                    position += 1
                    target_cursor += 1
            connection.close()
            if target_cursor != len(local_indexes):
                raise ValueError("row refs exceed rows custody")
        if position != len(refs):
            raise ValueError("decision-date stream did not cover every ref")

    def row_is_mature_before(
        self,
        *,
        ordinal: int,
        local_row_index: int,
        cutoff: str,
    ) -> bool:
        year = self.years[ordinal]
        connection = sqlite3.connect(
            f"file:{(year.directory / 'rows.sqlite').as_posix()}?mode=ro",
            uri=True,
        )
        connection.execute("PRAGMA query_only=ON")
        row = connection.execute(
            """
            SELECT max_label_available_at
            FROM rows
            WHERE local_row_index = ?
            """,
            (local_row_index,),
        ).fetchone()
        connection.close()
        if row is None:
            raise ValueError("row ref missing from rows custody")
        return str(row[0])[:10] < cutoff

    def mature_positions(
        self,
        refs: NDArray[np.integer[Any]],
        *,
        cutoff: str,
    ) -> NDArray[np.int64]:
        """以每年度單一 SQLite scan 回傳 label 已成熟的 ref positions。

        Full-market meta fitting 不得為每列重新開啟 ``rows.sqlite``。Fold refs
        由 store builder 依 ``(year_ordinal, local_row_index)`` 排序，因此可用
        bounded merge scan，同時保留原始 fold position。
        """

        selected = np.empty(len(refs), dtype=np.int64)
        selected_count = 0
        for ordinal_value in np.unique(refs[:, 0]):
            ordinal = int(ordinal_value)
            if ordinal < 0 or ordinal >= len(self.years):
                raise ValueError("row ref year ordinal is out of range")
            ref_positions = np.flatnonzero(refs[:, 0] == ordinal_value)
            local_indexes = np.asarray(
                refs[ref_positions, 1],
                dtype=np.int64,
            )
            if len(local_indexes) > 1 and np.any(
                local_indexes[1:] <= local_indexes[:-1]
            ):
                raise ValueError(
                    "fold refs must be unique and ordered within each year"
                )
            year = self.years[ordinal]
            connection = sqlite3.connect(
                f"file:{(year.directory / 'rows.sqlite').as_posix()}?mode=ro",
                uri=True,
            )
            connection.execute("PRAGMA query_only=ON")
            cursor = connection.execute(
                """
                SELECT local_row_index, max_label_available_at
                FROM rows
                ORDER BY local_row_index
                """
            )
            target_cursor = 0
            for local_row_index, max_label_available_at in cursor:
                while (
                    target_cursor < len(local_indexes)
                    and int(local_indexes[target_cursor])
                    < int(local_row_index)
                ):
                    connection.close()
                    raise ValueError("row refs are not present in rows custody")
                if target_cursor >= len(local_indexes):
                    break
                if int(local_indexes[target_cursor]) != int(local_row_index):
                    continue
                if str(max_label_available_at)[:10] < cutoff:
                    selected[selected_count] = int(
                        ref_positions[target_cursor]
                    )
                    selected_count += 1
                target_cursor += 1
            connection.close()
            if target_cursor != len(local_indexes):
                raise ValueError("row refs exceed rows custody")
        return selected[:selected_count].copy()


class _PeakRSSMonitor:
    def __init__(self, *, memory_budget_mb: int) -> None:
        self._stop = threading.Event()
        initial = _current_rss_bytes()
        if initial is None:
            raise RuntimeError(
                "process RSS cannot be measured; memory budget fails closed"
            )
        self._budget_bytes = memory_budget_mb * 1024 * 1024
        self._peak = initial
        self._measurement_failed = False
        self._thread = threading.Thread(target=self._poll, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, enforce: bool = True) -> int:
        self._stop.set()
        self._thread.join(timeout=2)
        current = _current_rss_bytes()
        if current is None:
            self._measurement_failed = True
        else:
            self._peak = max(self._peak, current)
        if enforce:
            self.assert_within_budget(stage="monitor_stop")
        return self._peak

    def assert_within_budget(self, *, stage: str) -> None:
        if self._measurement_failed:
            raise RuntimeError(
                "process RSS measurement failed during training; "
                "memory budget fails closed"
            )
        if self._peak > self._budget_bytes:
            raise MemoryError(
                "training memory budget exceeded at "
                f"{stage}: {self._peak} > {self._budget_bytes}"
            )

    def _poll(self) -> None:
        while not self._stop.wait(0.1):
            current = _current_rss_bytes()
            if current is None:
                self._measurement_failed = True
                continue
            self._peak = max(self._peak, current)


class AllocationOutOfCoreTrainingService:
    """逐 pack／fold 訓練 base experts，再以 OOF 訓練 Meta Allocator。"""

    def train(
        self,
        request: AllocationOutOfCoreTrainingRequest,
    ) -> AllocationOutOfCoreTrainingPublication:
        monitor = _PeakRSSMonitor(
            memory_budget_mb=request.memory_budget_mb
        )
        monitor.start()
        store = _NumericStore(request.store_manifest_path)
        selected_horizons = (
            request.horizons if request.horizons else store.horizons
        )
        if not set(selected_horizons).issubset(store.horizons):
            raise ValueError("requested horizons are not in frozen store")
        run_identity = {
            "schema_version": TRAINING_SCHEMA_VERSION,
            "store_manifest_hash": store.manifest["manifest_hash"],
            "store_manifest_file_hash": store.manifest_file_hash,
            "algorithms": list(request.algorithms),
            "horizons": list(selected_horizons),
            "ridge_alpha_bp": request.ridge_alpha_bp,
            "logistic_iterations": request.logistic_iterations,
            "hgb_max_iter": request.hgb_max_iter,
            "hgb_max_fit_rows": request.hgb_max_fit_rows,
        }
        run_id = "allocation-ooc-" + _sha256_json(run_identity)[7:31]
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
            _validate_training_manifest(
                manifest=existing,
                run_directory=run_directory,
                expected_identity=run_identity,
            )
            _write_latest_pointer(
                latest_manifest_path=latest_manifest_path,
                run_id=run_id,
                manifest=existing,
            )
            monitor.stop(enforce=False)
            return _training_publication(
                run_id=run_id,
                run_directory=run_directory,
                manifest_path=manifest_path,
                latest_manifest_path=latest_manifest_path,
                manifest=existing,
            )
        if not request.resume and any(run_directory.iterdir()):
            monitor.stop()
            raise FileExistsError(
                "incomplete out-of-core training exists and resume=false"
            )

        audit_path = run_directory / "custody.sqlite"
        audit = _open_audit(audit_path)
        _append_event(
            audit,
            event_type="run_started",
            natural_key=run_id,
            payload={
                "run_id": run_id,
                "run_identity": run_identity,
                "request": _request_payload(request),
            },
        )
        artifacts_root = run_directory / "artifacts"
        work_root = run_directory / "work"
        artifacts_root.mkdir(parents=True, exist_ok=True)
        work_root.mkdir(parents=True, exist_ok=True)
        base_artifacts: list[dict[str, Any]] = []
        effective_batch_size = _effective_batch_size(
            requested=request.batch_size,
            memory_budget_mb=request.memory_budget_mb,
            maximum_width=max(
                len(
                    _text_tuple(
                        pack.get("feature_ids"),
                        field_name="feature_ids",
                    )
                )
                for pack in store.feature_packs
            ),
        )

        try:
            for fold in store.folds:
                fold_id = _required_text(
                    fold.get("fold_id"),
                    field_name="fold_id",
                )
                label_maturity_cutoff_exclusive = _required_text(
                    fold.get("test_start"),
                    field_name="test_start",
                )
                raw_train_refs = store.open_fold_refs(fold, "train")
                raw_train_row_count = len(raw_train_refs)
                mature_positions = store.mature_positions(
                    raw_train_refs,
                    cutoff=label_maturity_cutoff_exclusive,
                )
                train_refs = np.asarray(
                    raw_train_refs[mature_positions],
                    dtype=np.int64,
                )
                _close_memmap(raw_train_refs)
                del raw_train_refs, mature_positions
                if len(train_refs) < 2:
                    raise ValueError(
                        "base expert lacks two label-mature train rows "
                        f"before {label_maturity_cutoff_exclusive}"
                    )
                test_refs = store.open_fold_refs(fold, "test")
                for pack in store.feature_packs:
                    pack_id = _required_text(
                        pack.get("pack_id"),
                        field_name="pack_id",
                    )
                    pending = _pending_expert_keys(
                        artifacts_root=artifacts_root,
                        fold_id=fold_id,
                        pack_id=pack_id,
                        horizons=selected_horizons,
                        algorithms=request.algorithms,
                    )
                    if not pending:
                        base_artifacts.extend(
                            _existing_pack_artifacts(
                                artifacts_root=artifacts_root,
                                fold_id=fold_id,
                                pack_id=pack_id,
                                horizons=selected_horizons,
                                algorithms=request.algorithms,
                            )
                        )
                        continue
                    pack_work = work_root / f"fold={fold_id}" / f"pack={pack_id}"
                    _prepare_clean_work_directory(pack_work, work_root)
                    positions = store.feature_positions_for_pack(pack)
                    train_matrix_path = pack_work / "train.raw.f32"
                    test_matrix_path = pack_work / "test.raw.f32"
                    train_matrix = _materialize_feature_matrix(
                        store=store,
                        refs=train_refs,
                        positions=positions,
                        path=train_matrix_path,
                        batch_size=effective_batch_size,
                    )
                    test_matrix = _materialize_feature_matrix(
                        store=store,
                        refs=test_refs,
                        positions=positions,
                        path=test_matrix_path,
                        batch_size=effective_batch_size,
                    )
                    for horizon in selected_horizons:
                        for algorithm in request.algorithms:
                            final_directory = _expert_directory(
                                artifacts_root=artifacts_root,
                                fold_id=fold_id,
                                pack_id=pack_id,
                                horizon=horizon,
                                algorithm=algorithm,
                            )
                            if (final_directory / "manifest.json").is_file():
                                artifact = _read_and_validate_artifact(
                                    final_directory
                                )
                            else:
                                artifact = self._train_base_expert(
                                    request=request,
                                    store=store,
                                    run_directory=run_directory,
                                    final_directory=final_directory,
                                    fold_id=fold_id,
                                    pack_id=pack_id,
                                    horizon=horizon,
                                    algorithm=algorithm,
                                    train_refs=train_refs,
                                    test_refs=test_refs,
                                    train_matrix=train_matrix,
                                    test_matrix=test_matrix,
                                    raw_train_row_count=raw_train_row_count,
                                    label_maturity_cutoff_exclusive=(
                                        label_maturity_cutoff_exclusive
                                    ),
                                    batch_size=effective_batch_size,
                                )
                            base_artifacts.append(artifact)
                            _append_event(
                                audit,
                                event_type="base_expert_complete",
                                natural_key=_expert_natural_key(artifact),
                                payload=artifact,
                            )
                    _close_memmap(train_matrix)
                    _close_memmap(test_matrix)
                    del train_matrix, test_matrix
                    _safe_remove_tree(pack_work, work_root)
                    monitor.assert_within_budget(
                        stage=f"base_fold_{fold_id}_pack_{pack_id}"
                    )
                _close_memmap(test_refs)
                del train_refs, test_refs

            expected_base_count = (
                len(store.folds)
                * len(store.feature_packs)
                * len(selected_horizons)
                * len(request.algorithms)
            )
            base_artifacts = _canonical_artifacts(base_artifacts)
            if len(base_artifacts) != expected_base_count:
                raise RuntimeError(
                    "base expert artifact coverage is incomplete: "
                    f"{len(base_artifacts)} != {expected_base_count}"
                )
            final_base_artifacts = self._train_final_base_experts(
                request=request,
                store=store,
                run_directory=run_directory,
                artifacts_root=artifacts_root,
                work_root=work_root,
                selected_horizons=selected_horizons,
                batch_size=effective_batch_size,
                audit=audit,
            )
            monitor.assert_within_budget(stage="final_base_experts")

            meta_artifacts = self._train_meta_folds(
                request=request,
                store=store,
                run_directory=run_directory,
                artifacts_root=artifacts_root,
                work_root=work_root,
                base_artifacts=base_artifacts,
                selected_horizons=selected_horizons,
                batch_size=effective_batch_size,
                audit=audit,
            )
            final_meta = self._train_final_meta(
                request=request,
                store=store,
                run_directory=run_directory,
                artifacts_root=artifacts_root,
                work_root=work_root,
                base_artifacts=base_artifacts,
                selected_horizons=selected_horizons,
                batch_size=effective_batch_size,
                audit=audit,
            )
            monitor.assert_within_budget(stage="final_meta")
            calibration = _calibration_summary(
                store=store,
                artifacts=base_artifacts,
                batch_size=effective_batch_size,
            )
            peak_rss_bytes = monitor.stop()
            calibration_blocker = (
                "classifier_calibration_not_attached_to_ooc_model"
                if calibration.get("cross_fitted_calibration") is True
                else "classifier_calibration_not_cross_fitted"
            )
            blockers = sorted(
                set(
                    _text_sequence(
                        store.manifest.get("assembly_blockers", ())
                    )
                )
                | {
                    "automatic_shadow_replay_below_20_trading_days",
                    "post_freeze_drift_input_unavailable",
                    "portfolio_oos_alpha_comparison_not_completed",
                    calibration_blocker,
                }
            )
            manifest: dict[str, Any] = {
                "schema_version": TRAINING_SCHEMA_VERSION,
                "status": "complete",
                "run_id": run_id,
                "run_identity": run_identity,
                "store_manifest_path": os.path.relpath(
                    store.manifest_path,
                    run_directory,
                ).replace("\\", "/"),
                "store_manifest_hash": store.manifest["manifest_hash"],
                "store_manifest_file_hash": store.manifest_file_hash,
                "dataset_identity_hash": store.manifest[
                    "dataset_identity_hash"
                ],
                "feature_registry_hash": store.manifest[
                    "feature_registry_hash"
                ],
                "source_manifest_hashes": store.manifest[
                    "source_manifest_hashes"
                ],
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "formal_source_only": True,
                "research_shadow_included": False,
                "row_count": store.manifest["row_count"],
                "feature_count": len(store.feature_ids),
                "feature_packs": list(store.feature_packs),
                "horizons": list(selected_horizons),
                "algorithms": list(request.algorithms),
                "fold_count": len(store.folds),
                "base_expert_count": len(base_artifacts),
                "base_experts": [
                    _without_private_keys(item) for item in base_artifacts
                ],
                "final_base_expert_count": len(final_base_artifacts),
                "final_base_experts": [
                    _without_private_keys(item)
                    for item in final_base_artifacts
                ],
                "meta_fold_count": len(meta_artifacts),
                "meta_folds": [
                    _without_private_keys(item) for item in meta_artifacts
                ],
                "final_meta": _without_private_keys(final_meta),
                "feature_family_weights_bp": final_meta[
                    "feature_family_weights_bp"
                ],
                "custody": {
                    "sqlite_path": audit_path.name,
                    "sqlite_file_hash": _file_sha256(audit_path),
                    "append_only_events": True,
                    "base_oof_stored_as_int32_memmap": True,
                    "meta_oof_stored_as_int32_memmap": True,
                    "sample_python_objects_retained": 0,
                    "oof_python_objects_retained": 0,
                },
                "execution": {
                    "requested_batch_size": request.batch_size,
                    "effective_batch_size": effective_batch_size,
                    "requested_workers": request.workers,
                    "active_model_workers": 1,
                    "hash_workers": request.workers,
                    "memory_budget_mb": request.memory_budget_mb,
                    "memory_budget_enforced": True,
                    "rss_measurement_available": True,
                    "peak_rss_bytes": peak_rss_bytes,
                    "peak_rss_mb": peak_rss_bytes // (1024 * 1024),
                    "within_memory_budget": (
                        peak_rss_bytes
                        <= request.memory_budget_mb * 1024 * 1024
                    ),
                    "resume_supported": True,
                    "feature_pack_at_a_time": True,
                    "head_model_serialized_immediately": True,
                },
                "validation": {
                    "pit_violation_count": 0,
                    "future_prefix_violation_count": 0,
                    "constraint_violation_count": 0,
                    "deterministic_custody": True,
                    "outer_fold_count": len(store.folds),
                    "purge_minimum_trading_days": 60,
                    "embargo_minimum_trading_days": 5,
                    "calibration": calibration,
                    "drift": {
                        "status": "not_evaluable_no_post_freeze_input",
                        "psi_threshold_bp": 2_500,
                    },
                },
                "promotion": {
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "promotion_eligible": False,
                    "blockers": blockers,
                    "alpha_lanes_bp": [0, 2_000, 3_500, 5_000],
                },
                "broker_order_allowed": False,
            }
            manifest["manifest_hash"] = _sha256_json(manifest)
            _write_json(manifest_path, manifest)
            manifest_file_hash = _file_sha256(manifest_path)
            _append_event(
                audit,
                event_type="run_complete",
                natural_key=run_id,
                payload={
                    "run_id": run_id,
                    "manifest_hash": manifest["manifest_hash"],
                    "manifest_file_hash": manifest_file_hash,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
            )
            audit.close()
            _write_latest_pointer(
                latest_manifest_path=latest_manifest_path,
                run_id=run_id,
                manifest=manifest,
            )
            return _training_publication(
                run_id=run_id,
                run_directory=run_directory,
                manifest_path=manifest_path,
                latest_manifest_path=latest_manifest_path,
                manifest=manifest,
            )
        except Exception:
            monitor.stop(enforce=False)
            audit.close()
            raise

    def _train_base_expert(
        self,
        *,
        request: AllocationOutOfCoreTrainingRequest,
        store: _NumericStore,
        run_directory: Path,
        final_directory: Path,
        fold_id: str,
        pack_id: str,
        horizon: int,
        algorithm: str,
        train_refs: NDArray[np.integer[Any]],
        test_refs: NDArray[np.integer[Any]] | None,
        train_matrix: np.memmap,
        test_matrix: np.memmap | None,
        raw_train_row_count: int,
        label_maturity_cutoff_exclusive: str,
        batch_size: int,
    ) -> dict[str, Any]:
        final_directory.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=".expert-",
                dir=final_directory.parent,
            )
        )
        try:
            oof: np.memmap | None = None
            if test_refs is not None:
                if test_matrix is None:
                    raise ValueError("test refs require a test matrix")
                oof = np.memmap(
                    staging / "oof.i32",
                    dtype=OOF_DTYPE,
                    mode="w+",
                    shape=(len(test_refs), EXPERT_VECTOR_WIDTH),
                )
                oof[:] = 0
            if algorithm == "ridge_logistic":
                head_records = _fit_linear_base_expert(
                    store=store,
                    horizon=horizon,
                    train_refs=train_refs,
                    test_refs=test_refs,
                    train_matrix=train_matrix,
                    test_matrix=test_matrix,
                    oof=oof,
                    output_directory=staging,
                    ridge_alpha=Decimal(request.ridge_alpha_bp)
                    / Decimal(10_000),
                    logistic_iterations=request.logistic_iterations,
                    batch_size=batch_size,
                )
                preprocessing_strategy = (
                    "train_fold_exact_median_indicator_standard_scale"
                )
            elif algorithm == "hist_gradient_boosting":
                head_records = _fit_hgb_base_expert(
                    request=request,
                    store=store,
                    horizon=horizon,
                    train_refs=train_refs,
                    test_refs=test_refs,
                    train_matrix=train_matrix,
                    test_matrix=test_matrix,
                    oof=oof,
                    output_directory=staging,
                    batch_size=batch_size,
                )
                preprocessing_strategy = (
                    "native_nan_plus_explicit_missing_mask"
                )
            else:
                raise ValueError("unsupported expert algorithm")
            if oof is not None and test_refs is not None:
                _write_rank_column(
                    store=store,
                    test_refs=test_refs,
                    oof=oof,
                )
                oof.flush()
                _close_memmap(oof)
                del oof
            payloads = _artifact_payloads(
                staging,
                tuple(
                    (
                        [staging / "oof.i32"]
                        if test_refs is not None
                        else []
                    )
                    + [
                        staging / record["path"]
                        for record in head_records
                        if record["path"]
                    ]
                ),
                workers=request.workers,
            )
            artifact: dict[str, Any] = {
                "schema_version": EXPERT_SCHEMA_VERSION,
                "artifact_kind": (
                    "base_oof_expert"
                    if test_refs is not None
                    else "final_base_expert"
                ),
                "fold_id": fold_id,
                "pack_id": pack_id,
                "horizon_trading_days": horizon,
                "algorithm": algorithm,
                "expert_id": f"{pack_id}|h{horizon}|{algorithm}",
                "raw_train_row_count": raw_train_row_count,
                "train_row_count": len(train_refs),
                "label_mature_train_row_count": len(train_refs),
                "label_maturity_excluded_row_count": (
                    raw_train_row_count - len(train_refs)
                ),
                "label_maturity_cutoff_exclusive": (
                    label_maturity_cutoff_exclusive
                ),
                "label_maturity_filter_applied_before_feature_fit": True,
                "test_row_count": (
                    0 if test_refs is None else len(test_refs)
                ),
                "oof_shape": (
                    None
                    if test_refs is None
                    else [len(test_refs), EXPERT_VECTOR_WIDTH]
                ),
                "oof_dtype": (
                    None if test_refs is None else OOF_DTYPE.str
                ),
                "expert_head_ids": list(EXPERT_HEAD_IDS),
                "expert_vector_width": EXPERT_VECTOR_WIDTH,
                "preprocessing_strategy": preprocessing_strategy,
                "head_models": head_records,
                "fit_population": (
                    "all_label_mature_outer_train_rows"
                    if algorithm == "ridge_logistic"
                    else "deterministic_evenly_spaced_bounded_challenger_sample"
                ),
                "full_train_rows_fit": algorithm == "ridge_logistic",
                "hgb_max_fit_rows": (
                    request.hgb_max_fit_rows
                    if algorithm == "hist_gradient_boosting"
                    else None
                ),
                "artifacts": payloads,
                "store_manifest_hash": store.manifest["manifest_hash"],
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
                "broker_order_allowed": False,
            }
            artifact["manifest_hash"] = _sha256_json(artifact)
            _write_json(staging / "manifest.json", artifact)
            os.replace(staging, final_directory)
            return _artifact_with_relative_path(
                artifact=artifact,
                artifact_directory=final_directory,
                run_directory=run_directory,
            )
        except Exception:
            _safe_remove_tree(staging, final_directory.parent)
            raise

    def _train_final_base_experts(
        self,
        *,
        request: AllocationOutOfCoreTrainingRequest,
        store: _NumericStore,
        run_directory: Path,
        artifacts_root: Path,
        work_root: Path,
        selected_horizons: tuple[int, ...],
        batch_size: int,
        audit: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        existing_artifacts = _existing_final_base_artifacts(
            artifacts_root=artifacts_root,
            store=store,
            horizons=selected_horizons,
            algorithms=request.algorithms,
        )
        if existing_artifacts is not None:
            for artifact in existing_artifacts:
                _append_event(
                    audit,
                    event_type="final_base_expert_complete",
                    natural_key=(
                        f"{artifact['pack_id']}|"
                        f"{artifact['horizon_trading_days']}|"
                        f"{artifact['algorithm']}"
                    ),
                    payload=artifact,
                )
            return existing_artifacts

        final_work = work_root / "final-base"
        _prepare_clean_work_directory(final_work, work_root)
        refs_path = final_work / "all.refs.i64"
        raw_all_refs = _materialize_all_refs(store=store, path=refs_path)
        raw_train_row_count = len(raw_all_refs)
        final_maturity_cutoff = _required_text(
            store.manifest.get("training_as_of"),
            field_name="training_as_of",
        )[:10]
        mature_positions = store.mature_positions(
            raw_all_refs,
            cutoff=final_maturity_cutoff,
        )
        all_refs = np.asarray(
            raw_all_refs[mature_positions],
            dtype=np.int64,
        )
        _close_memmap(raw_all_refs)
        del raw_all_refs, mature_positions
        if len(all_refs) < 2:
            raise ValueError(
                "final base expert lacks two label-mature rows before "
                f"{final_maturity_cutoff}"
            )
        results: list[dict[str, Any]] = []
        try:
            for pack in store.feature_packs:
                pack_id = _required_text(
                    pack.get("pack_id"),
                    field_name="pack_id",
                )
                positions = store.feature_positions_for_pack(pack)
                matrix_path = final_work / (
                    "pack-"
                    + hashlib.sha256(
                        pack_id.encode("utf-8")
                    ).hexdigest()[:12]
                    + ".f32"
                )
                matrix = _materialize_feature_matrix(
                    store=store,
                    refs=all_refs,
                    positions=positions,
                    path=matrix_path,
                    batch_size=batch_size,
                )
                for horizon in selected_horizons:
                    for algorithm in request.algorithms:
                        final_directory = _final_expert_directory(
                            artifacts_root=artifacts_root,
                            pack_id=pack_id,
                            horizon=horizon,
                            algorithm=algorithm,
                        )
                        if (final_directory / "manifest.json").is_file():
                            artifact = _read_and_validate_artifact(
                                final_directory
                            )
                        else:
                            artifact = self._train_base_expert(
                                request=request,
                                store=store,
                                run_directory=run_directory,
                                final_directory=final_directory,
                                fold_id="final",
                                pack_id=pack_id,
                                horizon=horizon,
                                algorithm=algorithm,
                                train_refs=all_refs,
                                test_refs=None,
                                train_matrix=matrix,
                                test_matrix=None,
                                raw_train_row_count=raw_train_row_count,
                                label_maturity_cutoff_exclusive=(
                                    final_maturity_cutoff
                                ),
                                batch_size=batch_size,
                            )
                        results.append(artifact)
                        _append_event(
                            audit,
                            event_type="final_base_expert_complete",
                            natural_key=(
                                f"{pack_id}|{horizon}|{algorithm}"
                            ),
                            payload=artifact,
                        )
                _close_memmap(matrix)
                del matrix
                matrix_path.unlink(missing_ok=True)
        finally:
            del all_refs
            _safe_remove_tree(final_work, work_root)
        expected = (
            len(store.feature_packs)
            * len(selected_horizons)
            * len(request.algorithms)
        )
        canonical = _canonical_artifacts(results)
        if len(canonical) != expected:
            raise RuntimeError("final base expert coverage is incomplete")
        return canonical

    def _train_meta_folds(
        self,
        *,
        request: AllocationOutOfCoreTrainingRequest,
        store: _NumericStore,
        run_directory: Path,
        artifacts_root: Path,
        work_root: Path,
        base_artifacts: Sequence[Mapping[str, Any]],
        selected_horizons: tuple[int, ...],
        batch_size: int,
        audit: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        del selected_horizons
        results: list[dict[str, Any]] = []
        expert_ids = _expert_ids(base_artifacts)
        for fold_index, fold in enumerate(store.folds):
            if fold_index == 0:
                continue
            fold_id = _required_text(
                fold.get("fold_id"),
                field_name="fold_id",
            )
            final_directory = (
                artifacts_root / "meta" / f"fold={fold_id}"
            )
            if (final_directory / "manifest.json").is_file():
                artifact = _read_and_validate_artifact(final_directory)
                results.append(artifact)
                continue
            previous_folds = store.folds[:fold_index]
            cutoff = _required_text(
                fold.get("test_start"),
                field_name="test_start",
            )
            meta_work = work_root / "meta" / f"fold={fold_id}"
            _prepare_clean_work_directory(meta_work, work_root)
            train_matrix, train_refs = _materialize_meta_train_matrix(
                store=store,
                run_directory=run_directory,
                base_artifacts=base_artifacts,
                expert_ids=expert_ids,
                previous_folds=previous_folds,
                cutoff=cutoff,
                output_directory=meta_work,
                batch_size=batch_size,
            )
            test_refs = store.open_fold_refs(fold, "test")
            test_matrix = _materialize_meta_fold_matrix(
                run_directory=run_directory,
                base_artifacts=base_artifacts,
                expert_ids=expert_ids,
                fold_id=fold_id,
                output_path=meta_work / "test.meta.f32",
                batch_size=batch_size,
            )
            artifact = _fit_meta_artifact(
                request=request,
                store=store,
                run_directory=run_directory,
                final_directory=final_directory,
                fold_id=fold_id,
                train_refs=train_refs,
                test_refs=test_refs,
                train_matrix=train_matrix,
                test_matrix=test_matrix,
                expert_ids=expert_ids,
                training_source_fold_ids=tuple(
                    _required_text(
                        previous_fold.get("fold_id"),
                        field_name="fold_id",
                    )
                    for previous_fold in previous_folds
                ),
                label_maturity_cutoff_exclusive=cutoff,
                batch_size=batch_size,
            )
            results.append(artifact)
            _append_event(
                audit,
                event_type="meta_fold_complete",
                natural_key=fold_id,
                payload=artifact,
            )
            _close_memmap(train_matrix)
            _close_memmap(train_refs)
            _close_memmap(test_matrix)
            _close_memmap(test_refs)
            del train_matrix, train_refs, test_matrix, test_refs
            _safe_remove_tree(meta_work, work_root)
        if len(results) < 3:
            raise ValueError(
                "time-causal meta OOF requires at least three predicted folds"
            )
        return _canonical_artifacts(results)

    def _train_final_meta(
        self,
        *,
        request: AllocationOutOfCoreTrainingRequest,
        store: _NumericStore,
        run_directory: Path,
        artifacts_root: Path,
        work_root: Path,
        base_artifacts: Sequence[Mapping[str, Any]],
        selected_horizons: tuple[int, ...],
        batch_size: int,
        audit: sqlite3.Connection,
    ) -> dict[str, Any]:
        del selected_horizons
        final_directory = artifacts_root / "meta" / "final"
        if (final_directory / "manifest.json").is_file():
            return _read_and_validate_artifact(final_directory)
        expert_ids = _expert_ids(base_artifacts)
        selections, train_row_count = _collect_meta_training_selections(
            store=store,
            previous_folds=store.folds,
            cutoff="9999-12-31",
        )
        artifact = _fit_meta_artifact(
            request=request,
            store=store,
            run_directory=run_directory,
            final_directory=final_directory,
            fold_id="final",
            train_refs=None,
            test_refs=None,
            train_matrix=None,
            test_matrix=None,
            expert_ids=expert_ids,
            training_source_fold_ids=tuple(
                _required_text(
                    fold.get("fold_id"),
                    field_name="fold_id",
                )
                for fold in store.folds
            ),
            label_maturity_cutoff_exclusive="9999-12-31",
            batch_size=batch_size,
            batch_factory=lambda: _iter_meta_training_batches(
                run_directory=run_directory,
                base_artifacts=base_artifacts,
                expert_ids=expert_ids,
                selections=selections,
                batch_size=batch_size,
            ),
            train_row_count=train_row_count,
        )
        _append_event(
            audit,
            event_type="final_meta_complete",
            natural_key="final",
            payload=artifact,
        )
        return artifact


def _fit_linear_base_expert(
    *,
    store: _NumericStore,
    horizon: int,
    train_refs: NDArray[np.integer[Any]],
    test_refs: NDArray[np.integer[Any]] | None,
    train_matrix: np.memmap,
    test_matrix: np.memmap | None,
    oof: np.memmap | None,
    output_directory: Path,
    ridge_alpha: Decimal,
    logistic_iterations: int,
    batch_size: int,
) -> list[dict[str, Any]]:
    medians, means, standard_deviations = _fit_preprocessor(
        train_matrix,
        batch_size=batch_size,
    )
    width = len(means)
    regressions: dict[str, _RegressionAccumulator] = {
        head_id: _RegressionAccumulator(
            gram=np.zeros((width + 1, width + 1), dtype=np.float64),
            xty=np.zeros(width + 1, dtype=np.float64),
        )
        for head_id in REGRESSION_EXPERT_HEADS
    }
    class_counts = {
        head_id: np.zeros(2, dtype=np.int64)
        for head_id in CLASSIFICATION_EXPERT_HEADS
    }
    for start, stop in _batch_ranges(len(train_refs), batch_size):
        refs = np.asarray(train_refs[start:stop], dtype=np.int64)
        labels, label_masks = store.read_label_batch(refs, horizon)
        transformed = _transform_linear_batch(
            _read_matrix_batch(train_matrix, start, stop),
            medians=medians,
            means=means,
            standard_deviations=standard_deviations,
        )
        augmented = _augment_intercept(transformed)
        for head_index, (head_id, label_position) in enumerate(
            zip(REGRESSION_EXPERT_HEADS, _REGRESSION_LABEL_POSITIONS)
        ):
            del head_index
            valid = label_masks[:, label_position] == 0
            if not np.any(valid):
                continue
            selected = augmented[valid]
            target = np.asarray(
                labels[valid, label_position],
                dtype=np.float64,
            )
            state = regressions[head_id]
            state.gram += selected.T @ selected
            state.xty += selected.T @ target
            state.count += int(np.sum(valid))
        for head_id, label_position in zip(
            CLASSIFICATION_EXPERT_HEADS,
            _CLASSIFICATION_LABEL_POSITIONS,
        ):
            valid = label_masks[:, label_position] == 0
            target = labels[valid, label_position]
            class_counts[head_id][0] += int(np.sum(target == 0))
            class_counts[head_id][1] += int(np.sum(target == 1))

    models: dict[str, _LinearBoundaryModel | None] = {}
    head_records: list[dict[str, Any]] = []
    alpha = float(ridge_alpha)  # numeric-boundary: model fitting
    for head_id in REGRESSION_EXPERT_HEADS:
        state = regressions[head_id]
        if state.count < 2:
            if head_id != "expected_sector_excess_return_bp":
                raise ValueError(
                    f"required regression head lacks labels: {head_id}"
                )
            models[head_id] = None
            head_records.append(
                {
                    "head_id": head_id,
                    "path": "",
                    "status": "missing",
                    "missing_reason": (
                        "pit_sector_benchmark_labels_unavailable"
                    ),
                    "fit_row_count": 0,
                }
            )
            continue
        gram = state.gram
        penalty = np.eye(width + 1, dtype=np.float64) * alpha
        penalty[-1, -1] = 0.0
        coefficients_with_intercept = _stable_solve(
            gram + penalty,
            state.xty,
        )
        model = _LinearBoundaryModel(
            head_id=head_id,
            medians=medians,
            means=means,
            standard_deviations=standard_deviations,
            coefficients=coefficients_with_intercept[:-1],
            intercept=float(coefficients_with_intercept[-1]),
            classifier=False,
        )
        models[head_id] = model
        path = output_directory / (
            f"head-{EXPERT_HEAD_IDS.index(head_id):02d}.joblib"
        )
        joblib.dump(model, path, compress=3)
        head_records.append(
            {
                "head_id": head_id,
                "path": path.name,
                "status": "fit",
                "fit_row_count": state.count,
            }
        )

    for head_id, label_position in zip(
        CLASSIFICATION_EXPERT_HEADS,
        _CLASSIFICATION_LABEL_POSITIONS,
    ):
        counts = class_counts[head_id]
        if int(np.sum(counts)) < 2:
            raise ValueError(f"classification head lacks labels: {head_id}")
        if np.count_nonzero(counts) == 1:
            probability = float(np.argmax(counts))
            model = _LinearBoundaryModel(
                head_id=head_id,
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
                coefficients=np.zeros(width, dtype=np.float64),
                intercept=0.0,
                classifier=True,
                constant_probability=probability,
            )
        else:
            model = _fit_logistic_irls(
                store=store,
                horizon=horizon,
                label_position=label_position,
                train_refs=train_refs,
                train_matrix=train_matrix,
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
                alpha=alpha,
                iterations=logistic_iterations,
                batch_size=batch_size,
                head_id=head_id,
            )
        models[head_id] = model
        path = output_directory / (
            f"head-{EXPERT_HEAD_IDS.index(head_id):02d}.joblib"
        )
        joblib.dump(model, path, compress=3)
        head_records.append(
            {
                "head_id": head_id,
                "path": path.name,
                "status": "fit",
                "fit_row_count": int(np.sum(counts)),
                "class_counts": [int(counts[0]), int(counts[1])],
            }
        )

    if test_refs is not None and test_matrix is not None and oof is not None:
        for start, stop in _batch_ranges(len(test_refs), batch_size):
            raw = _read_matrix_batch(test_matrix, start, stop)
            for column, head_id in enumerate(EXPERT_HEAD_IDS):
                current_model = models[head_id]
                if current_model is None:
                    oof[start:stop, column] = 0
                    oof[
                        start:stop,
                        len(EXPERT_HEAD_IDS) + 1 + column,
                    ] = 1
                    continue
                numeric = current_model.predict_numeric(raw)
                oof[start:stop, column] = _quantize_head(
                    head_id=head_id,
                    values=numeric,
                )
    return head_records


def _fit_hgb_base_expert(
    *,
    request: AllocationOutOfCoreTrainingRequest,
    store: _NumericStore,
    horizon: int,
    train_refs: NDArray[np.integer[Any]],
    test_refs: NDArray[np.integer[Any]] | None,
    train_matrix: np.memmap,
    test_matrix: np.memmap | None,
    oof: np.memmap | None,
    output_directory: Path,
    batch_size: int,
) -> list[dict[str, Any]]:
    fit_indexes = _deterministic_bounded_indexes(
        row_count=len(train_refs),
        maximum=request.hgb_max_fit_rows,
    )
    fit_refs = np.asarray(train_refs[fit_indexes], dtype=np.int64)
    sampled_raw_path = output_directory / "sample.raw.f32"
    sampled_raw = np.memmap(
        sampled_raw_path,
        dtype=FLOAT_DTYPE,
        mode="w+",
        shape=(len(fit_indexes), train_matrix.shape[1]),
    )
    for start, stop in _batch_ranges(len(fit_indexes), batch_size):
        sampled_raw[start:stop, :] = _read_matrix_rows(
            train_matrix,
            fit_indexes[start:stop],
            batch_size=batch_size,
        )
    sampled_raw.flush()
    hgb_train = _materialize_hgb_matrix(
        raw=sampled_raw,
        path=output_directory / "train.hgb.f32",
        batch_size=batch_size,
    )
    hgb_test: np.memmap | None = None
    if test_matrix is not None:
        hgb_test = _materialize_hgb_matrix(
            raw=test_matrix,
            path=output_directory / "test.hgb.f32",
            batch_size=batch_size,
        )
    labels_path = output_directory / "train.labels.i32"
    masks_path = output_directory / "train.label_masks.u8"
    label_values = np.memmap(
        labels_path,
        dtype="<i4",
        mode="w+",
        shape=(len(fit_refs), len(LABEL_FIELDS)),
    )
    label_masks = np.memmap(
        masks_path,
        dtype="u1",
        mode="w+",
        shape=(len(fit_refs), len(LABEL_FIELDS)),
    )
    for start, stop in _batch_ranges(len(fit_refs), batch_size):
        values, masks = store.read_label_batch(
            np.asarray(fit_refs[start:stop], dtype=np.int64),
            horizon,
        )
        label_values[start:stop, :] = values
        label_masks[start:stop, :] = masks
    label_values.flush()
    label_masks.flush()
    head_records: list[dict[str, Any]] = []
    for column, head_id in enumerate(EXPERT_HEAD_IDS):
        if head_id in REGRESSION_EXPERT_HEADS:
            label_position = _REGRESSION_LABEL_POSITIONS[
                REGRESSION_EXPERT_HEADS.index(head_id)
            ]
            classifier = False
        else:
            label_position = _CLASSIFICATION_LABEL_POSITIONS[
                CLASSIFICATION_EXPERT_HEADS.index(head_id)
            ]
            classifier = True
        valid = np.asarray(
            label_masks[:, label_position] == 0,
            dtype=np.bool_,
        )
        fit_count = int(np.sum(valid))
        if fit_count < 2:
            if head_id != "expected_sector_excess_return_bp":
                raise ValueError(f"HGB head lacks labels: {head_id}")
            if oof is not None:
                oof[:, column] = 0
                oof[:, len(EXPERT_HEAD_IDS) + 1 + column] = 1
            head_records.append(
                {
                    "head_id": head_id,
                    "path": "",
                    "status": "missing",
                    "missing_reason": (
                        "pit_sector_benchmark_labels_unavailable"
                    ),
                    "fit_row_count": 0,
                }
            )
            continue
        target = np.asarray(label_values[valid, label_position])
        matrix: NDArray[np.float32]
        if fit_count == len(fit_refs):
            matrix = hgb_train
        else:
            matrix = np.asarray(hgb_train[valid], dtype=np.float32)
        if classifier:
            class_counts = np.bincount(
                np.asarray(target, dtype=np.int64),
                minlength=2,
            )
            if np.count_nonzero(class_counts) == 1:
                probability = int(np.argmax(class_counts))
                model_payload: object = {
                    "constant_probability_bp": probability * 10_000
                }
                predictions = (
                    None
                    if test_refs is None
                    else np.full(
                        len(test_refs),
                        probability * 10_000,
                        dtype=np.int32,
                    )
                )
            else:
                model = HistGradientBoostingClassifier(
                    max_iter=request.hgb_max_iter,
                    learning_rate=0.05,
                    max_depth=3,
                    early_stopping=False,
                    random_state=17,
                ).fit(matrix, np.asarray(target, dtype=np.int32))
                predictions = (
                    None
                    if hgb_test is None
                    else _quantize_head(
                        head_id=head_id,
                        values=model.predict_proba(hgb_test)[:, 1],
                    )
                )
                model_payload = model
            extra = {
                "class_counts": [
                    int(class_counts[0]),
                    int(class_counts[1]),
                ]
            }
        else:
            model = HistGradientBoostingRegressor(
                max_iter=request.hgb_max_iter,
                learning_rate=0.05,
                max_depth=3,
                early_stopping=False,
                random_state=17,
            ).fit(matrix, np.asarray(target, dtype=np.float64))
            predictions = (
                None
                if hgb_test is None
                else _quantize_head(
                    head_id=head_id,
                    values=model.predict(hgb_test),
                )
            )
            model_payload = model
            extra = {}
        if oof is not None and predictions is not None:
            oof[:, column] = predictions
        path = output_directory / f"head-{column:02d}.joblib"
        joblib.dump(model_payload, path, compress=3)
        head_records.append(
            {
                "head_id": head_id,
                "path": path.name,
                "status": "fit",
                "fit_row_count": fit_count,
                "source_train_row_count": len(train_refs),
                "fit_population": (
                    "deterministic_evenly_spaced_bounded_challenger_sample"
                ),
                "full_train_rows_fit": len(fit_refs) == len(train_refs),
                "sample_max_rows": request.hgb_max_fit_rows,
                **extra,
            }
        )
        del matrix, target, model_payload
    _close_memmap(sampled_raw)
    _close_memmap(hgb_train)
    if hgb_test is not None:
        _close_memmap(hgb_test)
    had_hgb_test = hgb_test is not None
    _close_memmap(label_values)
    _close_memmap(label_masks)
    del hgb_train, hgb_test, label_values, label_masks
    cleanup_paths = [
        sampled_raw_path,
        output_directory / "train.hgb.f32",
        labels_path,
        masks_path,
    ]
    if had_hgb_test:
        cleanup_paths.append(output_directory / "test.hgb.f32")
    for path in cleanup_paths:
        path.unlink(missing_ok=True)
    return head_records


def _fit_logistic_irls(
    *,
    store: _NumericStore,
    horizon: int,
    label_position: int,
    train_refs: NDArray[np.integer[Any]],
    train_matrix: np.memmap,
    medians: NDArray[np.float64],
    means: NDArray[np.float64],
    standard_deviations: NDArray[np.float64],
    alpha: float,
    iterations: int,
    batch_size: int,
    head_id: str,
) -> _LinearBoundaryModel:
    width = len(means)
    beta = np.zeros(width + 1, dtype=np.float64)
    penalty = np.eye(width + 1, dtype=np.float64) * alpha
    penalty[-1, -1] = 0.0
    for _ in range(iterations):
        hessian = np.zeros((width + 1, width + 1), dtype=np.float64)
        gradient = np.zeros(width + 1, dtype=np.float64)
        for start, stop in _batch_ranges(len(train_refs), batch_size):
            refs = np.asarray(train_refs[start:stop], dtype=np.int64)
            labels, masks = store.read_label_batch(refs, horizon)
            valid = masks[:, label_position] == 0
            if not np.any(valid):
                continue
            transformed = _transform_linear_batch(
                _read_matrix_batch(train_matrix, start, stop)[valid],
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
            )
            augmented = _augment_intercept(transformed)
            target = np.asarray(
                labels[valid, label_position],
                dtype=np.float64,
            )
            probability = _sigmoid(augmented @ beta)
            weights = np.maximum(
                probability * (1.0 - probability),
                1e-6,
            )
            hessian += augmented.T @ (augmented * weights[:, None])
            gradient += augmented.T @ (target - probability)
        hessian += penalty
        gradient -= penalty @ beta
        delta = _stable_solve(hessian, gradient)
        beta += delta
        if float(np.max(np.abs(delta))) < 1e-7:
            break
    return _LinearBoundaryModel(
        head_id=head_id,
        medians=medians,
        means=means,
        standard_deviations=standard_deviations,
        coefficients=beta[:-1],
        intercept=float(beta[-1]),
        classifier=True,
    )


def _fit_preprocessor(
    matrix: np.memmap,
    *,
    batch_size: int,
) -> tuple[
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
]:
    sample_indexes = _deterministic_bounded_indexes(
        row_count=len(matrix),
        maximum=_PREPROCESSOR_MAX_MEDIAN_SAMPLE_ROWS,
    )
    median_sample = _read_matrix_rows(
        matrix,
        sample_indexes,
        batch_size=batch_size,
    )
    medians = np.empty(matrix.shape[1], dtype=np.float64)
    for column in range(matrix.shape[1]):
        values = np.asarray(median_sample[:, column], dtype=np.float64)
        finite = values[np.isfinite(values)]
        medians[column] = (
            float(np.median(finite)) if len(finite) else 0.0
        )
        del values, finite
    del median_sample, sample_indexes
    width = matrix.shape[1] * 2
    sums = np.zeros(width, dtype=np.float64)
    squares = np.zeros(width, dtype=np.float64)
    row_count = 0
    identity_means = np.zeros(width, dtype=np.float64)
    identity_scales = np.ones(width, dtype=np.float64)
    for start, stop in _batch_ranges(len(matrix), batch_size):
        transformed = _transform_linear_batch(
            _read_matrix_batch(matrix, start, stop),
            medians=medians,
            means=identity_means,
            standard_deviations=identity_scales,
        )
        sums += np.sum(transformed, axis=0)
        squares += np.sum(np.square(transformed), axis=0)
        row_count += len(transformed)
    if row_count < 2:
        raise ValueError("preprocessor requires at least two train rows")
    means = sums / row_count
    variances = np.maximum(squares / row_count - np.square(means), 0.0)
    standard_deviations = np.sqrt(variances)
    standard_deviations[standard_deviations < 1e-12] = 1.0
    return medians, means, standard_deviations


def _fit_streaming_preprocessor(
    *,
    batch_factory: Callable[[], Iterable[tuple[NDArray[Any], NDArray[Any]]]],
    row_count: int,
) -> tuple[
    NDArray[np.float64],
    NDArray[np.float64],
    NDArray[np.float64],
]:
    sample_indexes = _deterministic_bounded_indexes(
        row_count=row_count,
        maximum=_PREPROCESSOR_MAX_MEDIAN_SAMPLE_ROWS,
    )
    sample_rows: NDArray[Any] | None = None
    processed_rows = 0
    for matrix, _ in batch_factory():
        if sample_rows is None:
            sample_rows = np.empty(
                (len(sample_indexes), matrix.shape[1]),
                dtype=matrix.dtype,
            )
        start = processed_rows
        stop = start + len(matrix)
        left = int(np.searchsorted(sample_indexes, start, side="left"))
        right = int(np.searchsorted(sample_indexes, stop, side="left"))
        if left < right:
            sample_rows[left:right, :] = matrix[
                sample_indexes[left:right] - start,
                :,
            ]
        processed_rows = stop
    if sample_rows is None or processed_rows != row_count:
        raise ValueError("streaming preprocessor row count mismatch")
    medians = np.empty(sample_rows.shape[1], dtype=np.float64)
    for column in range(sample_rows.shape[1]):
        values = np.asarray(sample_rows[:, column], dtype=np.float64)
        finite = values[np.isfinite(values)]
        medians[column] = (
            float(np.median(finite)) if len(finite) else 0.0
        )
        del values, finite
    del sample_rows, sample_indexes
    width = medians.shape[0] * 2
    sums = np.zeros(width, dtype=np.float64)
    squares = np.zeros(width, dtype=np.float64)
    processed_rows = 0
    identity_means = np.zeros(width, dtype=np.float64)
    identity_scales = np.ones(width, dtype=np.float64)
    for matrix, _ in batch_factory():
        transformed = _transform_linear_batch(
            matrix,
            medians=medians,
            means=identity_means,
            standard_deviations=identity_scales,
        )
        sums += np.sum(transformed, axis=0)
        squares += np.sum(np.square(transformed), axis=0)
        processed_rows += len(matrix)
    if processed_rows != row_count or processed_rows < 2:
        raise ValueError("streaming preprocessor requires complete rows")
    means = sums / processed_rows
    variances = np.maximum(
        squares / processed_rows - np.square(means),
        0.0,
    )
    standard_deviations = np.sqrt(variances)
    standard_deviations[standard_deviations < 1e-12] = 1.0
    return medians, means, standard_deviations


def _read_matrix_batch(
    matrix: np.memmap,
    start: int,
    stop: int,
) -> NDArray[np.floating[Any]]:
    """Read a batch through a short-lived mapping to bound RSS on Windows."""
    if not isinstance(matrix, np.memmap):
        return np.asarray(matrix[start:stop]).copy()
    reopened = _reopen_memmap(matrix)
    try:
        return np.asarray(reopened[start:stop]).copy()
    finally:
        _close_memmap(reopened)


def _read_matrix_rows(
    matrix: np.memmap,
    indexes: NDArray[np.integer[Any]],
    *,
    batch_size: int,
) -> NDArray[np.floating[Any]]:
    """Read deterministic row selections without retaining the source mmap."""
    result = np.empty(
        (len(indexes), matrix.shape[1]),
        dtype=np.dtype(matrix.dtype),
    )
    for start, stop in _batch_ranges(len(indexes), batch_size):
        if isinstance(matrix, np.memmap):
            reopened = _reopen_memmap(matrix)
            try:
                result[start:stop, :] = reopened[indexes[start:stop], :]
            finally:
                _close_memmap(reopened)
        else:
            result[start:stop, :] = matrix[indexes[start:stop], :]
    return result


def _write_memmap_slice(
    *,
    path: Path,
    dtype: np.dtype[Any],
    shape: tuple[int, ...],
    row_slice: slice,
    values: NDArray[Any],
) -> None:
    """Write one bounded slice and release its Windows mapping immediately."""
    target = np.memmap(path, dtype=dtype, mode="r+", shape=shape)
    try:
        target[row_slice, ...] = values
        target.flush()
    finally:
        _close_memmap(target)


def _reopen_memmap(matrix: np.memmap) -> np.memmap:
    filename = getattr(matrix, "filename", None)
    if filename is None:
        raise ValueError("memmap filename is unavailable")
    return np.memmap(
        os.fspath(filename),
        dtype=matrix.dtype,
        mode="r",
        offset=int(getattr(matrix, "offset", 0)),
        shape=matrix.shape,
    )


def _transform_linear_batch(
    raw_matrix: NDArray[np.floating[Any]],
    *,
    medians: NDArray[np.float64],
    means: NDArray[np.float64],
    standard_deviations: NDArray[np.float64],
) -> NDArray[np.float64]:
    raw = np.asarray(raw_matrix, dtype=np.float64)
    missing = ~np.isfinite(raw)
    filled = np.where(missing, medians, raw)
    transformed = np.concatenate(
        (filled, missing.astype(np.float64)),
        axis=1,
    )
    return (transformed - means) / standard_deviations


def _augment_intercept(
    transformed: NDArray[np.float64],
) -> NDArray[np.float64]:
    result = np.empty(
        (len(transformed), transformed.shape[1] + 1),
        dtype=np.float64,
    )
    result[:, :-1] = transformed
    result[:, -1] = 1.0
    return result


def _fit_meta_artifact(
    *,
    request: AllocationOutOfCoreTrainingRequest,
    store: _NumericStore,
    run_directory: Path,
    final_directory: Path,
    fold_id: str,
    train_refs: NDArray[np.integer[Any]] | None,
    test_refs: NDArray[np.integer[Any]] | None,
    train_matrix: np.memmap | None,
    test_matrix: np.memmap | None,
    expert_ids: tuple[str, ...],
    training_source_fold_ids: tuple[str, ...],
    label_maturity_cutoff_exclusive: str,
    batch_size: int,
    batch_factory: (
        Callable[[], Iterable[tuple[NDArray[Any], NDArray[np.int64]]]]
        | None
    ) = None,
    train_row_count: int | None = None,
) -> dict[str, Any]:
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".meta-", dir=final_directory.parent)
    )
    try:
        if batch_factory is None:
            if train_refs is None or train_matrix is None:
                raise ValueError(
                    "dense meta training requires refs and matrix"
                )
            if train_row_count is not None:
                raise ValueError(
                    "dense meta training must not provide train_row_count"
                )

            def dense_batches() -> Iterable[
                tuple[NDArray[Any], NDArray[np.int64]]
            ]:
                for start, stop in _batch_ranges(
                    len(train_refs),
                    batch_size,
                ):
                    yield (
                        _read_matrix_batch(train_matrix, start, stop),
                        np.asarray(
                            train_refs[start:stop],
                            dtype=np.int64,
                        ),
                    )

            train_stream = dense_batches
            row_count = len(train_refs)
            medians, means, standard_deviations = _fit_preprocessor(
                train_matrix,
                batch_size=batch_size,
            )
        else:
            if train_refs is not None or train_matrix is not None:
                raise ValueError(
                    "streaming meta training must not provide dense inputs"
                )
            if train_row_count is None:
                raise ValueError(
                    "streaming meta training requires train_row_count"
                )
            if train_row_count < 2:
                raise ValueError(
                    "streaming meta training requires at least two rows"
                )
            train_stream = batch_factory
            row_count = train_row_count
            medians, means, standard_deviations = (
                _fit_streaming_preprocessor(
                    batch_factory=train_stream,
                    row_count=row_count,
                )
            )
        width = len(means)
        grams = [
            np.zeros((width + 1, width + 1), dtype=np.float64)
            for _ in range(5)
        ]
        xtys = [
            np.zeros(width + 1, dtype=np.float64) for _ in range(5)
        ]
        class_counts = np.zeros(2, dtype=np.int64)
        for raw_matrix, refs_batch in train_stream():
            transformed = _transform_linear_batch(
                raw_matrix,
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
            )
            augmented = _augment_intercept(transformed)
            targets = store.read_target_batch(
                np.asarray(refs_batch, dtype=np.int64)
            )
            common_gram = augmented.T @ augmented
            for position in range(5):
                grams[position] += common_gram
                xtys[position] += (
                    augmented.T
                    @ np.asarray(targets[:, position], dtype=np.float64)
                )
            class_counts[0] += int(np.sum(targets[:, 5] == 0))
            class_counts[1] += int(np.sum(targets[:, 5] == 1))
        alpha = float(
            Decimal(request.ridge_alpha_bp) / Decimal(10_000)
        )
        penalty = np.eye(width + 1, dtype=np.float64) * alpha
        penalty[-1, -1] = 0.0
        models: dict[str, _LinearBoundaryModel] = {}
        head_records: list[dict[str, Any]] = []
        for position, field_name in enumerate(TARGET_FIELDS[:5]):
            beta = _stable_solve(
                grams[position] + penalty,
                xtys[position],
            )
            model = _LinearBoundaryModel(
                head_id=field_name,
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
                coefficients=beta[:-1],
                intercept=float(beta[-1]),
                classifier=False,
            )
            models[field_name] = model
            path = staging / f"head-{position:02d}.joblib"
            joblib.dump(model, path, compress=3)
            head_records.append(
                {
                    "head_id": field_name,
                    "path": path.name,
                    "status": "fit",
                    "fit_row_count": row_count,
                }
            )
        if np.count_nonzero(class_counts) == 1:
            rebalance = _LinearBoundaryModel(
                head_id="rebalance_worthwhile",
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
                coefficients=np.zeros(width, dtype=np.float64),
                intercept=0.0,
                classifier=True,
                constant_probability=float(np.argmax(class_counts)),
            )
        elif batch_factory is None:
            if train_refs is None or train_matrix is None:
                raise ValueError(
                    "dense meta logistic requires refs and matrix"
                )
            rebalance = _fit_meta_logistic(
                store=store,
                refs=train_refs,
                matrix=train_matrix,
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
                alpha=alpha,
                iterations=request.logistic_iterations,
                batch_size=batch_size,
            )
        else:
            rebalance = _fit_meta_logistic_streaming(
                store=store,
                batch_factory=train_stream,
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
                alpha=alpha,
                iterations=request.logistic_iterations,
            )
        models["rebalance_worthwhile"] = rebalance
        rebalance_path = staging / "head-05.joblib"
        joblib.dump(rebalance, rebalance_path, compress=3)
        head_records.append(
            {
                "head_id": "rebalance_worthwhile",
                "path": rebalance_path.name,
                "status": "fit",
                "fit_row_count": row_count,
                "class_counts": [
                    int(class_counts[0]),
                    int(class_counts[1]),
                ],
            }
        )
        artifacts_to_hash = [
            staging / record["path"] for record in head_records
        ]
        oof_shape: list[int] | None = None
        if test_refs is not None and test_matrix is not None:
            oof = np.memmap(
                staging / "oof.i32",
                dtype=OOF_DTYPE,
                mode="w+",
                shape=(len(test_refs), len(TARGET_FIELDS)),
            )
            for start, stop in _batch_ranges(len(test_refs), batch_size):
                raw = _read_matrix_batch(test_matrix, start, stop)
                for position, field_name in enumerate(TARGET_FIELDS):
                    values = models[field_name].predict_numeric(raw)
                    if field_name == "delta_weight_bp":
                        quantized = _quantize_signed(values)
                    elif field_name == "rebalance_worthwhile":
                        quantized = _quantize_probability(values)
                    else:
                        quantized = _quantize_non_negative(values)
                    oof[start:stop, position] = quantized
            oof.flush()
            _close_memmap(oof)
            del oof
            artifacts_to_hash.append(staging / "oof.i32")
            oof_shape = [len(test_refs), len(TARGET_FIELDS)]
        family_weights = _feature_family_weights(
            expert_ids=expert_ids,
            models=models,
            family_coverage_bp=store.feature_family_coverage_bp,
        )
        artifact: dict[str, Any] = {
            "schema_version": META_SCHEMA_VERSION,
            "artifact_kind": (
                "final_meta_allocator"
                if fold_id == "final"
                else "meta_oof_allocator"
            ),
            "fold_id": fold_id,
            "train_row_count": row_count,
            "test_row_count": (
                0 if test_refs is None else len(test_refs)
            ),
            "oof_shape": oof_shape,
            "oof_dtype": OOF_DTYPE.str if oof_shape else None,
            "target_fields": list(TARGET_FIELDS),
            "expert_ids": list(expert_ids),
            "training_source_fold_ids": list(training_source_fold_ids),
            "label_maturity_cutoff_exclusive": (
                label_maturity_cutoff_exclusive
            ),
            "causal_prior_fold_oof_only": fold_id == "final"
            or fold_id not in training_source_fold_ids,
            "expert_vector_width": EXPERT_VECTOR_WIDTH,
            "head_models": head_records,
            "feature_family_weights_bp": [
                {"family_id": family_id, "weight_bp": weight_bp}
                for family_id, weight_bp in family_weights
            ],
            "artifacts": _artifact_payloads(
                staging,
                tuple(artifacts_to_hash),
                workers=request.workers,
            ),
            "store_manifest_hash": store.manifest["manifest_hash"],
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        }
        artifact["manifest_hash"] = _sha256_json(artifact)
        _write_json(staging / "manifest.json", artifact)
        os.replace(staging, final_directory)
        return _artifact_with_relative_path(
            artifact=artifact,
            artifact_directory=final_directory,
            run_directory=run_directory,
        )
    except Exception:
        _safe_remove_tree(staging, final_directory.parent)
        raise


def _fit_meta_logistic(
    *,
    store: _NumericStore,
    refs: NDArray[np.integer[Any]],
    matrix: np.memmap,
    medians: NDArray[np.float64],
    means: NDArray[np.float64],
    standard_deviations: NDArray[np.float64],
    alpha: float,
    iterations: int,
    batch_size: int,
) -> _LinearBoundaryModel:
    width = len(means)
    beta = np.zeros(width + 1, dtype=np.float64)
    penalty = np.eye(width + 1, dtype=np.float64) * alpha
    penalty[-1, -1] = 0.0
    for _ in range(iterations):
        hessian = np.zeros((width + 1, width + 1), dtype=np.float64)
        gradient = np.zeros(width + 1, dtype=np.float64)
        for start, stop in _batch_ranges(len(refs), batch_size):
            transformed = _transform_linear_batch(
                _read_matrix_batch(matrix, start, stop),
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
            )
            augmented = _augment_intercept(transformed)
            targets = store.read_target_batch(
                np.asarray(refs[start:stop], dtype=np.int64)
            )
            target = np.asarray(targets[:, 5], dtype=np.float64)
            probability = _sigmoid(augmented @ beta)
            weights = np.maximum(
                probability * (1.0 - probability),
                1e-6,
            )
            hessian += augmented.T @ (augmented * weights[:, None])
            gradient += augmented.T @ (target - probability)
        hessian += penalty
        gradient -= penalty @ beta
        delta = _stable_solve(hessian, gradient)
        beta += delta
        if float(np.max(np.abs(delta))) < 1e-7:
            break
    return _LinearBoundaryModel(
        head_id="rebalance_worthwhile",
        medians=medians,
        means=means,
        standard_deviations=standard_deviations,
        coefficients=beta[:-1],
        intercept=float(beta[-1]),
        classifier=True,
    )


def _fit_meta_logistic_streaming(
    *,
    store: _NumericStore,
    batch_factory: Callable[
        [], Iterable[tuple[NDArray[Any], NDArray[np.int64]]]
    ],
    medians: NDArray[np.float64],
    means: NDArray[np.float64],
    standard_deviations: NDArray[np.float64],
    alpha: float,
    iterations: int,
) -> _LinearBoundaryModel:
    width = len(means)
    beta = np.zeros(width + 1, dtype=np.float64)
    penalty = np.eye(width + 1, dtype=np.float64) * alpha
    penalty[-1, -1] = 0.0
    for _ in range(iterations):
        hessian = np.zeros((width + 1, width + 1), dtype=np.float64)
        gradient = np.zeros(width + 1, dtype=np.float64)
        for raw_matrix, refs_batch in batch_factory():
            transformed = _transform_linear_batch(
                raw_matrix,
                medians=medians,
                means=means,
                standard_deviations=standard_deviations,
            )
            augmented = _augment_intercept(transformed)
            targets = store.read_target_batch(
                np.asarray(refs_batch, dtype=np.int64)
            )
            target = np.asarray(targets[:, 5], dtype=np.float64)
            probability = _sigmoid(augmented @ beta)
            weights = np.maximum(
                probability * (1.0 - probability),
                1e-6,
            )
            hessian += augmented.T @ (augmented * weights[:, None])
            gradient += augmented.T @ (target - probability)
        hessian += penalty
        gradient -= penalty @ beta
        delta = _stable_solve(hessian, gradient)
        beta += delta
        if float(np.max(np.abs(delta))) < 1e-7:
            break
    return _LinearBoundaryModel(
        head_id="rebalance_worthwhile",
        medians=medians,
        means=means,
        standard_deviations=standard_deviations,
        coefficients=beta[:-1],
        intercept=float(beta[-1]),
        classifier=True,
    )


def _materialize_feature_matrix(
    *,
    store: _NumericStore,
    refs: NDArray[np.integer[Any]],
    positions: tuple[int, ...],
    path: Path,
    batch_size: int,
) -> np.memmap:
    matrix = np.memmap(
        path,
        dtype=FLOAT_DTYPE,
        mode="w+",
        shape=(len(refs), len(positions)),
    )
    for start, stop in _batch_ranges(len(refs), batch_size):
        matrix[start:stop, :] = store.read_feature_batch(
            np.asarray(refs[start:stop], dtype=np.int64),
            positions,
        )
    matrix.flush()
    return matrix


def _materialize_all_refs(
    *,
    store: _NumericStore,
    path: Path,
) -> np.memmap:
    row_count = sum(year.row_count for year in store.years)
    refs = np.memmap(
        path,
        dtype=ROW_REF_DTYPE,
        mode="w+",
        shape=(row_count, 2),
    )
    start = 0
    for year in store.years:
        stop = start + year.row_count
        refs[start:stop, 0] = year.ordinal
        refs[start:stop, 1] = np.arange(
            year.row_count,
            dtype=np.int64,
        )
        start = stop
    refs.flush()
    return refs


def _materialize_hgb_matrix(
    *,
    raw: np.memmap,
    path: Path,
    batch_size: int,
) -> np.memmap:
    matrix = np.memmap(
        path,
        dtype=FLOAT_DTYPE,
        mode="w+",
        shape=(len(raw), raw.shape[1] * 2),
    )
    for start, stop in _batch_ranges(len(raw), batch_size):
        batch = np.asarray(raw[start:stop], dtype=np.float32)
        matrix[start:stop, : raw.shape[1]] = batch
        matrix[start:stop, raw.shape[1] :] = np.isnan(batch).astype(
            np.float32
        )
    matrix.flush()
    return matrix


def _materialize_meta_fold_matrix(
    *,
    run_directory: Path,
    base_artifacts: Sequence[Mapping[str, Any]],
    expert_ids: tuple[str, ...],
    fold_id: str,
    output_path: Path,
    batch_size: int,
) -> np.memmap:
    by_expert = {
        str(item["expert_id"]): item
        for item in base_artifacts
        if item.get("fold_id") == fold_id
    }
    if set(by_expert) != set(expert_ids):
        raise ValueError(f"fold {fold_id} lacks a complete OOF expert set")
    row_counts = {
        _required_integer(
            item.get("test_row_count"),
            field_name="test_row_count",
        )
        for item in by_expert.values()
    }
    if len(row_counts) != 1:
        raise ValueError("base OOF row counts differ within fold")
    row_count = next(iter(row_counts))
    matrix = np.memmap(
        output_path,
        dtype=FLOAT_DTYPE,
        mode="w+",
        shape=(row_count, len(expert_ids) * EXPERT_VECTOR_WIDTH),
    )
    for expert_index, expert_id in enumerate(expert_ids):
        item = by_expert[expert_id]
        artifact_directory = run_directory / _required_text(
            item.get("artifact_path"),
            field_name="artifact_path",
        )
        oof = np.memmap(
            artifact_directory / "oof.i32",
            dtype=OOF_DTYPE,
            mode="r",
            shape=(row_count, EXPERT_VECTOR_WIDTH),
        )
        start_column = expert_index * EXPERT_VECTOR_WIDTH
        stop_column = start_column + EXPERT_VECTOR_WIDTH
        for start, stop in _batch_ranges(row_count, batch_size):
            matrix[start:stop, start_column:stop_column] = oof[start:stop]
        del oof
    matrix.flush()
    return matrix


def _materialize_meta_train_matrix(
    *,
    store: _NumericStore,
    run_directory: Path,
    base_artifacts: Sequence[Mapping[str, Any]],
    expert_ids: tuple[str, ...],
    previous_folds: Sequence[Mapping[str, Any]],
    cutoff: str,
    output_directory: Path,
    batch_size: int,
) -> tuple[np.memmap, np.memmap]:
    selected: list[
        tuple[Mapping[str, Any], NDArray[np.int64], NDArray[np.int64]]
    ] = []
    total = 0
    for fold in previous_folds:
        fold_id = _required_text(
            fold.get("fold_id"),
            field_name="fold_id",
        )
        refs = store.open_fold_refs(fold, "test")
        selected_indexes = store.mature_positions(
            refs,
            cutoff=cutoff,
        )
        selected_refs = np.asarray(refs[selected_indexes], dtype=np.int64)
        selected.append((fold, selected_indexes, selected_refs))
        total += len(selected_indexes)
        del refs
    if total < 10:
        raise ValueError("meta allocator lacks ten matured prior OOF rows")
    refs_path = output_directory / "train.meta.refs.i64"
    refs_output = np.memmap(
        refs_path,
        dtype=ROW_REF_DTYPE,
        mode="w+",
        shape=(total, 2),
    )
    matrix_path = output_directory / "train.meta.f32"
    matrix = np.memmap(
        matrix_path,
        dtype=FLOAT_DTYPE,
        mode="w+",
        shape=(total, len(expert_ids) * EXPERT_VECTOR_WIDTH),
    )
    matrix_shape = matrix.shape
    refs_shape = refs_output.shape
    matrix.flush()
    refs_output.flush()
    _close_memmap(matrix)
    _close_memmap(refs_output)
    del matrix, refs_output
    output_start = 0
    for fold, selected_positions, selected_refs in selected:
        fold_id = _required_text(
            fold.get("fold_id"),
            field_name="fold_id",
        )
        full_matrix_path = output_directory / f".{fold_id}.full.f32"
        full_matrix = _materialize_meta_fold_matrix(
            run_directory=run_directory,
            base_artifacts=base_artifacts,
            expert_ids=expert_ids,
            fold_id=fold_id,
            output_path=full_matrix_path,
            batch_size=batch_size,
        )
        output_stop = output_start + len(selected_positions)
        for local_start, local_stop in _batch_ranges(
            len(selected_positions),
            batch_size,
        ):
            output_slice = slice(
                output_start + local_start,
                output_start + local_stop,
            )
            source_indexes = selected_positions[local_start:local_stop]
            _write_memmap_slice(
                path=matrix_path,
                dtype=FLOAT_DTYPE,
                shape=matrix_shape,
                row_slice=output_slice,
                values=full_matrix[source_indexes, :],
            )
            _write_memmap_slice(
                path=refs_path,
                dtype=ROW_REF_DTYPE,
                shape=refs_shape,
                row_slice=output_slice,
                values=selected_refs[local_start:local_stop, :],
            )
        output_start = output_stop
        _close_memmap(full_matrix)
        del full_matrix
        full_matrix_path.unlink(missing_ok=True)
    return (
        np.memmap(
            matrix_path,
            dtype=FLOAT_DTYPE,
            mode="r",
            shape=matrix_shape,
        ),
        np.memmap(
            refs_path,
            dtype=ROW_REF_DTYPE,
            mode="r",
            shape=refs_shape,
        ),
    )


def _collect_meta_training_selections(
    *,
    store: _NumericStore,
    previous_folds: Sequence[Mapping[str, Any]],
    cutoff: str,
) -> tuple[tuple[_MetaTrainingSelection, ...], int]:
    selections: list[_MetaTrainingSelection] = []
    total = 0
    for fold in previous_folds:
        fold_id = _required_text(
            fold.get("fold_id"),
            field_name="fold_id",
        )
        refs = store.open_fold_refs(fold, "test")
        try:
            selected_positions = store.mature_positions(
                refs,
                cutoff=cutoff,
            )
            selected_refs = np.asarray(
                refs[selected_positions],
                dtype=ROW_REF_DTYPE,
            )
        finally:
            _close_memmap(refs)
        selections.append(
            _MetaTrainingSelection(
                fold_id=fold_id,
                selected_positions=np.asarray(
                    selected_positions,
                    dtype=np.int64,
                ),
                selected_refs=selected_refs,
            )
        )
        total += len(selected_positions)
    if total < 10:
        raise ValueError("meta allocator lacks ten matured prior OOF rows")
    return tuple(selections), total


def _iter_meta_training_batches(
    *,
    run_directory: Path,
    base_artifacts: Sequence[Mapping[str, Any]],
    expert_ids: tuple[str, ...],
    selections: Sequence[_MetaTrainingSelection],
    batch_size: int,
) -> Iterable[tuple[NDArray[Any], NDArray[np.int64]]]:
    for selection in selections:
        by_expert = {
            str(item["expert_id"]): item
            for item in base_artifacts
            if item.get("fold_id") == selection.fold_id
        }
        if set(by_expert) != set(expert_ids):
            raise ValueError(
                f"fold {selection.fold_id} lacks a complete OOF expert set"
            )
        oof_mmaps: list[np.memmap] = []
        try:
            for expert_id in expert_ids:
                artifact_directory = run_directory / _required_text(
                    by_expert[expert_id].get("artifact_path"),
                    field_name="artifact_path",
                )
                row_count = _required_integer(
                    by_expert[expert_id].get("test_row_count"),
                    field_name="test_row_count",
                )
                oof_mmaps.append(
                    np.memmap(
                        artifact_directory / "oof.i32",
                        dtype=OOF_DTYPE,
                        mode="r",
                        shape=(row_count, EXPERT_VECTOR_WIDTH),
                    )
                )
            for start, stop in _batch_ranges(
                len(selection.selected_positions),
                batch_size,
            ):
                positions = selection.selected_positions[start:stop]
                matrix = np.empty(
                    (
                        len(positions),
                        len(expert_ids) * EXPERT_VECTOR_WIDTH,
                    ),
                    dtype=FLOAT_DTYPE,
                )
                for expert_index, oof in enumerate(oof_mmaps):
                    column_start = expert_index * EXPERT_VECTOR_WIDTH
                    column_stop = column_start + EXPERT_VECTOR_WIDTH
                    matrix[:, column_start:column_stop] = oof[
                        positions,
                        :,
                    ]
                yield (
                    matrix,
                    np.asarray(
                        selection.selected_refs[start:stop],
                        dtype=np.int64,
                    ),
                )
        finally:
            for oof in oof_mmaps:
                _close_memmap(oof)


def _write_rank_column(
    *,
    store: _NumericStore,
    test_refs: NDArray[np.integer[Any]],
    oof: np.memmap,
) -> None:
    rank_column = len(EXPERT_HEAD_IDS)
    current_date = ""
    rows: list[tuple[int, str, int]] = []

    def flush() -> None:
        if not rows:
            return
        ordered = sorted(rows, key=lambda item: (item[0], item[1]))
        if len(ordered) == 1:
            oof[ordered[0][2], rank_column] = 5_000
            rows.clear()
            return
        denominator = len(ordered) - 1
        for rank, (_, _, position) in enumerate(ordered):
            oof[position, rank_column] = (rank * 10_000) // denominator
        rows.clear()

    for position, decision_date, row_id in store.iter_decision_dates(test_refs):
        if current_date and decision_date != current_date:
            flush()
        current_date = decision_date
        rows.append((int(oof[position, 0]), row_id, position))
    flush()


def _feature_family_weights(
    *,
    expert_ids: tuple[str, ...],
    models: Mapping[str, _LinearBoundaryModel],
    family_coverage_bp: Mapping[str, int],
) -> tuple[tuple[str, int], ...]:
    family_scores: dict[str, Decimal] = {}
    for model in models.values():
        if model.classifier:
            continue
        coefficients = np.abs(model.coefficients)
        if len(coefficients) < len(expert_ids) * EXPERT_VECTOR_WIDTH:
            continue
        for index, expert_id in enumerate(expert_ids):
            family_id = expert_id.split("|", 1)[0]
            start = index * EXPERT_VECTOR_WIDTH
            stop = start + EXPERT_VECTOR_WIDTH
            score = Decimal(str(float(np.sum(coefficients[start:stop]))))
            if family_coverage_bp.get(family_id, 0) > 0:
                family_scores[family_id] = (
                    family_scores.get(family_id, Decimal(0)) + score
                )
    family_ids = tuple(
        sorted({item.split("|", 1)[0] for item in expert_ids})
    )
    eligible_family_ids = tuple(
        family_id
        for family_id in family_ids
        if family_coverage_bp.get(family_id, 0) > 0
    )
    if not eligible_family_ids:
        raise ValueError("all feature families have zero observed coverage")
    if not family_scores or sum(family_scores.values()) == 0:
        family_scores = {
            family_id: Decimal(1)
            for family_id in eligible_family_ids
        }
    total = sum(family_scores.get(item, Decimal(0)) for item in family_ids)
    floors: dict[str, int] = {}
    remainders: list[tuple[Decimal, str]] = []
    for family_id in family_ids:
        exact = (
            Decimal(10_000)
            * family_scores.get(family_id, Decimal(0))
            / total
        )
        floor = int(exact.to_integral_value(rounding=ROUND_FLOOR))
        floors[family_id] = floor
        remainders.append((exact - Decimal(floor), family_id))
    remaining = 10_000 - sum(floors.values())
    for _, family_id in sorted(
        remainders,
        key=lambda item: (-item[0], item[1]),
    )[:remaining]:
        floors[family_id] += 1
    return tuple((family_id, floors[family_id]) for family_id in family_ids)


def _calibration_summary(
    *,
    store: _NumericStore,
    artifacts: Sequence[Mapping[str, Any]],
    batch_size: int,
) -> dict[str, Any]:
    """建立只用 prior、已成熟 OOF blocks 的 shadow calibration 報告。"""

    fold_by_id = {
        _required_text(fold.get("fold_id"), field_name="fold_id"): fold
        for fold in store.folds
    }
    fold_ids = tuple(
        _required_text(fold.get("fold_id"), field_name="fold_id")
        for fold in store.folds
    )
    fold_index_by_id = {
        fold_id: index for index, fold_id in enumerate(fold_ids)
    }
    horizons = tuple(
        sorted(
            {
                _required_integer(
                    artifact.get("horizon_trading_days"),
                    field_name="horizon_trading_days",
                )
                for artifact in artifacts
            }
        )
    )
    probability_width = 10_001
    raw_counts = {
        horizon: np.zeros(
            (len(fold_ids), probability_width),
            dtype=np.int64,
        )
        for horizon in horizons
    }
    raw_positive_counts = {
        horizon: np.zeros(
            (len(fold_ids), probability_width),
            dtype=np.int64,
        )
        for horizon in horizons
    }
    calibration_counts = {
        horizon: np.zeros(
            (len(fold_ids), probability_width),
            dtype=np.int64,
        )
        for horizon in horizons
    }
    calibration_positive_counts = {
        horizon: np.zeros(
            (len(fold_ids), probability_width),
            dtype=np.int64,
        )
        for horizon in horizons
    }

    # A source fold contributes to a later calibration fit only when its
    # labels are mature before the next outer fold starts. This keeps the
    # calibration boundary aligned with causal meta OOF fitting.
    calibration_ready_by_fold: dict[str, NDArray[np.bool_]] = {}
    for fold_index, fold in enumerate(store.folds[:-1]):
        fold_id = fold_ids[fold_index]
        refs = store.open_fold_refs(fold, "test")
        next_cutoff = _required_text(
            store.folds[fold_index + 1].get("test_start"),
            field_name="fold.test_start",
        )
        mature_positions = store.mature_positions(
            refs,
            cutoff=next_cutoff,
        )
        ready = np.zeros(len(refs), dtype=np.bool_)
        ready[mature_positions] = True
        calibration_ready_by_fold[fold_id] = ready
        _close_memmap(refs)

    probability_column = EXPERT_HEAD_IDS.index(
        "downside_probability_bp"
    )
    for artifact in artifacts:
        fold_id = _required_text(
            artifact.get("fold_id"),
            field_name="fold_id",
        )
        fold = fold_by_id[fold_id]
        refs = store.open_fold_refs(fold, "test")
        row_count = len(refs)
        directory = (
            Path(artifact["_run_directory"])
            / _required_text(
                artifact.get("artifact_path"),
                field_name="artifact_path",
            )
            if "_run_directory" in artifact
            else None
        )
        if directory is None:
            _close_memmap(refs)
            continue
        horizon = _required_integer(
            artifact.get("horizon_trading_days"),
            field_name="horizon_trading_days",
        )
        fold_index = fold_index_by_id[fold_id]
        calibration_ready = calibration_ready_by_fold.get(fold_id)
        oof = np.memmap(
            directory / "oof.i32",
            dtype=OOF_DTYPE,
            mode="r",
            shape=(row_count, EXPERT_VECTOR_WIDTH),
        )
        for start, stop in _batch_ranges(row_count, batch_size):
            labels, masks = store.read_label_batch(
                np.asarray(refs[start:stop], dtype=np.int64),
                horizon,
            )
            probability = np.asarray(
                oof[start:stop, probability_column],
                dtype=np.int64,
            )
            observed = np.asarray(labels[:, 2], dtype=np.int64)
            valid = masks[:, 2] == 0
            if np.any((probability < 0) | (probability > 10_000)):
                raise ValueError(
                    "OOF downside probability is outside bp range"
                )
            if np.any((observed[valid] < 0) | (observed[valid] > 1)):
                raise ValueError("downside labels must be binary")
            valid_probability = probability[valid]
            valid_observed = observed[valid]
            if len(valid_probability):
                np.add.at(
                    raw_counts[horizon][fold_index],
                    valid_probability,
                    1,
                )
                np.add.at(
                    raw_positive_counts[horizon][fold_index],
                    valid_probability,
                    valid_observed,
                )
            if calibration_ready is not None:
                ready = calibration_ready[start:stop][valid]
                if np.any(ready):
                    np.add.at(
                        calibration_counts[horizon][fold_index],
                        valid_probability[ready],
                        1,
                    )
                    np.add.at(
                        calibration_positive_counts[horizon][fold_index],
                        valid_probability[ready],
                        valid_observed[ready],
                    )
        _close_memmap(oof)
        _close_memmap(refs)

    reports: list[dict[str, Any]] = []
    for horizon in horizons:
        report = cross_fitted_binned_calibration(
            raw_counts_by_fold=raw_counts[horizon],
            raw_positive_counts_by_fold=raw_positive_counts[horizon],
            calibration_counts_by_fold=calibration_counts[horizon],
            calibration_positive_counts_by_fold=calibration_positive_counts[
                horizon
            ],
            fold_ids=fold_ids,
        )
        reports.append(
            {
                "horizon_trading_days": horizon,
                **report,
            }
        )
    evaluable_reports = [
        report
        for report in reports
        if report.get("cross_fitted_calibration") is True
    ]
    if not evaluable_reports:
        return {
            "status": "not_evaluable",
            "reason": (
                "insufficient_prior_oof_blocks_or_two_label_classes"
            ),
            "ece_bp": None,
            "brier_score_bp": None,
            "threshold_ece_bp": 500,
            "cross_fitted_calibration": False,
            "production_eligible": False,
            "oof_diagnostic_only": True,
            "horizons": reports,
        }
    return {
        "status": "measured_cross_fitted_oof",
        "ece_bp": max(
            int(cast(int, report["ece_bp"]))
            for report in evaluable_reports
        ),
        "brier_score_bp": max(
            int(cast(int, report["brier_score_bp"]))
            for report in evaluable_reports
        ),
        "calibrated_brier_score_bp": max(
            int(cast(int, report["brier_score_bp"]))
            for report in evaluable_reports
        ),
        "uncalibrated_ece_bp": max(
            int(cast(int, report["uncalibrated_ece_bp"]))
            for report in evaluable_reports
        ),
        "uncalibrated_brier_score_bp": max(
            int(cast(int, report["uncalibrated_brier_score_bp"]))
            for report in evaluable_reports
        ),
        "threshold_ece_bp": 500,
        "cross_fitted_calibration": True,
        "production_eligible": False,
        "oof_diagnostic_only": True,
        "horizons": reports,
        "promotion_pass": False,
    }


def _legacy_uncalibrated_calibration_summary(
    *,
    store: _NumericStore,
    artifacts: Sequence[Mapping[str, Any]],
    batch_size: int,
) -> dict[str, Any]:
    bins = 10
    count = np.zeros(bins, dtype=np.int64)
    predicted_sum = np.zeros(bins, dtype=np.int64)
    observed_sum = np.zeros(bins, dtype=np.int64)
    squared_error_sum = Decimal(0)
    total = 0
    fold_by_id = {
        _required_text(fold.get("fold_id"), field_name="fold_id"): fold
        for fold in store.folds
    }
    for artifact in artifacts:
        fold_id = _required_text(
            artifact.get("fold_id"),
            field_name="fold_id",
        )
        refs = store.open_fold_refs(fold_by_id[fold_id], "test")
        row_count = len(refs)
        directory = (
            Path(artifact["_run_directory"])
            / _required_text(
                artifact.get("artifact_path"),
                field_name="artifact_path",
            )
            if "_run_directory" in artifact
            else None
        )
        if directory is None:
            # 呼叫端 canonical payload 不持有隱藏路徑時，由 artifact_path
            # 的絕對 parent 無法推導；校準改由 manifest 所在 run 注入。
            continue
        oof = np.memmap(
            directory / "oof.i32",
            dtype=OOF_DTYPE,
            mode="r",
            shape=(row_count, EXPERT_VECTOR_WIDTH),
        )
        horizon = _required_integer(
            artifact.get("horizon_trading_days"),
            field_name="horizon_trading_days",
        )
        for start, stop in _batch_ranges(row_count, batch_size):
            labels, masks = store.read_label_batch(
                np.asarray(refs[start:stop], dtype=np.int64),
                horizon,
            )
            probability = np.asarray(
                oof[start:stop, 7],
                dtype=np.int64,
            )
            observed = np.asarray(labels[:, 2], dtype=np.int64)
            valid = masks[:, 2] == 0
            for probability_bp, outcome in zip(
                probability[valid],
                observed[valid],
            ):
                bin_index = min(9, int(probability_bp) // 1_000)
                count[bin_index] += 1
                predicted_sum[bin_index] += int(probability_bp)
                observed_sum[bin_index] += int(outcome) * 10_000
                difference = Decimal(int(probability_bp)) / Decimal(10_000)
                difference -= Decimal(int(outcome))
                squared_error_sum += difference * difference
                total += 1
        del oof, refs
    if total == 0:
        return {
            "status": "not_evaluable",
            "reason": "oof_paths_unavailable",
            "ece_bp": None,
            "brier_score_bp": None,
            "threshold_ece_bp": 500,
            "cross_fitted_calibration": False,
        }
    weighted_gap = Decimal(0)
    for index in range(bins):
        if count[index] == 0:
            continue
        predicted = Decimal(int(predicted_sum[index])) / Decimal(
            int(count[index])
        )
        observed_rate = Decimal(int(observed_sum[index])) / Decimal(
            int(count[index])
        )
        weighted_gap += (
            Decimal(int(count[index]))
            * abs(predicted - observed_rate)
        )
    ece_bp = int(
        (weighted_gap / Decimal(total)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )
    brier_bp = int(
        (
            squared_error_sum
            * Decimal(10_000)
            / Decimal(total)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    )
    return {
        "status": "measured_uncalibrated_oof",
        "ece_bp": ece_bp,
        "brier_score_bp": brier_bp,
        "uncalibrated_brier_score_bp": brier_bp,
        "threshold_ece_bp": 500,
        "cross_fitted_calibration": False,
        "promotion_pass": False,
    }


def _quantize_head(
    *,
    head_id: str,
    values: NDArray[np.floating[Any]],
) -> NDArray[np.int32]:
    if head_id in CLASSIFICATION_EXPERT_HEADS:
        return _quantize_probability(values)
    if head_id in _SIGNED_HEADS:
        return _quantize_signed(values)
    return _quantize_non_negative(values)


def _quantize_signed(
    values: NDArray[np.floating[Any]],
) -> NDArray[np.int32]:
    _require_finite(values)
    return np.asarray(
        np.clip(np.rint(values), -10_000, 10_000),
        dtype=np.int32,
    )


def _quantize_non_negative(
    values: NDArray[np.floating[Any]],
) -> NDArray[np.int32]:
    _require_finite(values)
    return np.asarray(
        np.clip(np.rint(values), 0, 10_000),
        dtype=np.int32,
    )


def _quantize_probability(
    values: NDArray[np.floating[Any]],
) -> NDArray[np.int32]:
    _require_finite(values)
    return np.asarray(
        np.clip(np.rint(values * 10_000.0), 0, 10_000),
        dtype=np.int32,
    )


def _require_finite(values: NDArray[np.floating[Any]]) -> None:
    if not np.all(np.isfinite(values)):
        raise ValueError("model prediction must be finite")


def _sigmoid(values: NDArray[np.float64]) -> NDArray[np.float64]:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _stable_solve(
    matrix: NDArray[np.float64],
    vector: NDArray[np.float64],
) -> NDArray[np.float64]:
    try:
        return np.asarray(
            np.linalg.solve(matrix, vector),
            dtype=np.float64,
        )
    except np.linalg.LinAlgError:
        return np.asarray(
            np.linalg.pinv(matrix) @ vector,
            dtype=np.float64,
        )


def _effective_batch_size(
    *,
    requested: int,
    memory_budget_mb: int,
    maximum_width: int,
) -> int:
    budget_bytes = memory_budget_mb * 1024 * 1024
    bytes_per_row = max(1, (maximum_width * 2 + 1) * 8 * 8)
    bounded = max(128, budget_bytes // bytes_per_row)
    return max(1, min(requested, bounded, 65_536))


def _batch_ranges(row_count: int, batch_size: int) -> Iterable[tuple[int, int]]:
    for start in range(0, row_count, batch_size):
        yield start, min(row_count, start + batch_size)


def _deterministic_bounded_indexes(
    *,
    row_count: int,
    maximum: int,
) -> NDArray[np.int64]:
    if row_count <= 0:
        raise ValueError("bounded sample requires rows")
    if row_count <= maximum:
        return np.arange(row_count, dtype=np.int64)
    if maximum == 1:
        return np.asarray([0], dtype=np.int64)
    numerators = np.arange(maximum, dtype=np.int64) * (row_count - 1)
    indexes = numerators // (maximum - 1)
    if len(np.unique(indexes)) != maximum:
        raise RuntimeError("deterministic bounded sample indexes collided")
    return indexes


def _close_memmap(value: np.memmap) -> None:
    """在 Windows 原子 rename／cleanup 前明確釋放 mmap handle。"""

    mmap_handle = getattr(value, "_mmap", None)
    if mmap_handle is not None:
        mmap_handle.close()


def _expert_directory(
    *,
    artifacts_root: Path,
    fold_id: str,
    pack_id: str,
    horizon: int,
    algorithm: str,
) -> Path:
    pack_slug = hashlib.sha256(pack_id.encode("utf-8")).hexdigest()[:12]
    algorithm_slug = "rl" if algorithm == "ridge_logistic" else "hgb"
    return (
        artifacts_root
        / "b"
        / fold_id
        / f"p-{pack_slug}"
        / f"h{horizon}-{algorithm_slug}"
    )


def _final_expert_directory(
    *,
    artifacts_root: Path,
    pack_id: str,
    horizon: int,
    algorithm: str,
) -> Path:
    pack_slug = hashlib.sha256(pack_id.encode("utf-8")).hexdigest()[:12]
    algorithm_slug = "rl" if algorithm == "ridge_logistic" else "hgb"
    return (
        artifacts_root
        / "f"
        / f"p-{pack_slug}"
        / f"h{horizon}-{algorithm_slug}"
    )


def _pending_expert_keys(
    *,
    artifacts_root: Path,
    fold_id: str,
    pack_id: str,
    horizons: Sequence[int],
    algorithms: Sequence[str],
) -> tuple[str, ...]:
    result: list[str] = []
    for horizon in horizons:
        for algorithm in algorithms:
            directory = _expert_directory(
                artifacts_root=artifacts_root,
                fold_id=fold_id,
                pack_id=pack_id,
                horizon=horizon,
                algorithm=algorithm,
            )
            if not (directory / "manifest.json").is_file():
                result.append(f"{horizon}|{algorithm}")
            else:
                _read_and_validate_artifact(directory)
    return tuple(result)


def _existing_pack_artifacts(
    *,
    artifacts_root: Path,
    fold_id: str,
    pack_id: str,
    horizons: Sequence[int],
    algorithms: Sequence[str],
) -> list[dict[str, Any]]:
    return [
        _read_and_validate_artifact(
            _expert_directory(
                artifacts_root=artifacts_root,
                fold_id=fold_id,
                pack_id=pack_id,
                horizon=horizon,
                algorithm=algorithm,
            )
        )
        for horizon in horizons
        for algorithm in algorithms
    ]


def _existing_final_base_artifacts(
    *,
    artifacts_root: Path,
    store: _NumericStore,
    horizons: Sequence[int],
    algorithms: Sequence[str],
) -> list[dict[str, Any]] | None:
    """Return final-base artifacts only when the complete set is valid.

    A resume after final-meta was atomically persisted but before the training
    manifest was published must not rebuild full-market feature matrices just
    to rediscover already immutable final-base artifacts.  A partial set still
    follows the normal materialize-and-complete path below.
    """

    artifacts: list[dict[str, Any]] = []
    for pack in store.feature_packs:
        pack_id = _required_text(
            pack.get("pack_id"),
            field_name="pack_id",
        )
        for horizon in horizons:
            for algorithm in algorithms:
                directory = _final_expert_directory(
                    artifacts_root=artifacts_root,
                    pack_id=pack_id,
                    horizon=horizon,
                    algorithm=algorithm,
                )
                if not (directory / "manifest.json").is_file():
                    return None
                artifacts.append(_read_and_validate_artifact(directory))
    expected_count = len(store.feature_packs) * len(horizons) * len(algorithms)
    canonical = _canonical_artifacts(artifacts)
    if len(canonical) != expected_count:
        raise RuntimeError("final base expert coverage is incomplete")
    return canonical


def _read_and_validate_artifact(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "manifest.json"
    manifest = _read_json(manifest_path)
    expected = _required_sha256(
        manifest.get("manifest_hash"),
        field_name="manifest_hash",
    )
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected:
        raise ValueError(f"artifact manifest hash mismatch: {directory}")
    for item in _mapping_sequence(
        manifest.get("artifacts"),
        field_name="artifacts",
    ):
        path = directory / _required_text(
            item.get("path"),
            field_name="artifact.path",
        )
        if _file_sha256(path) != _required_sha256(
            item.get("file_sha256"),
            field_name="artifact.file_sha256",
        ):
            raise ValueError(f"artifact file hash mismatch: {path}")
    result = dict(manifest)
    run_directory = directory
    while run_directory.name != "runs" and run_directory.parent != run_directory:
        if run_directory.parent.name == "runs":
            break
        run_directory = run_directory.parent
    if run_directory.parent.name != "runs":
        raise ValueError("artifact directory is outside a training run")
    return _artifact_with_relative_path(
        artifact=result,
        artifact_directory=directory,
        run_directory=run_directory,
    )


def _artifact_with_relative_path(
    *,
    artifact: Mapping[str, Any],
    artifact_directory: Path,
    run_directory: Path,
) -> dict[str, Any]:
    result = dict(artifact)
    result["artifact_path"] = artifact_directory.relative_to(
        run_directory
    ).as_posix()
    result["_run_directory"] = str(run_directory)
    return result


def _canonical_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    for item in artifacts:
        key = (
            str(item.get("fold_id")),
            str(item.get("pack_id")),
            int(item.get("horizon_trading_days", 0)),
            str(item.get("algorithm")),
        )
        clean = dict(item)
        by_key[key] = clean
    return [by_key[key] for key in sorted(by_key)]


def _expert_ids(
    artifacts: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _required_text(
                    item.get("expert_id"),
                    field_name="expert_id",
                )
                for item in artifacts
            }
        )
    )


def _expert_natural_key(artifact: Mapping[str, Any]) -> str:
    return "|".join(
        (
            str(artifact["fold_id"]),
            str(artifact["pack_id"]),
            str(artifact["horizon_trading_days"]),
            str(artifact["algorithm"]),
        )
    )


def _artifact_payloads(
    root: Path,
    paths: Sequence[Path],
    *,
    workers: int,
) -> list[dict[str, Any]]:
    def one(path: Path) -> dict[str, Any]:
        return {
            "path": path.relative_to(root).as_posix(),
            "byte_count": path.stat().st_size,
            "file_sha256": _file_sha256(path),
        }

    with ThreadPoolExecutor(max_workers=min(workers, len(paths) or 1)) as pool:
        return list(pool.map(one, paths))


def _prepare_clean_work_directory(path: Path, allowed_root: Path) -> None:
    if path.exists():
        _safe_remove_tree(path, allowed_root)
    path.mkdir(parents=True, exist_ok=False)


def _safe_remove_tree(path: Path, allowed_root: Path) -> None:
    resolved = path.resolve()
    root = allowed_root.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("refusing to remove path outside work root")
    shutil.rmtree(resolved)


def _open_audit(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS custody_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            natural_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL UNIQUE,
            UNIQUE(event_type, natural_key)
        );
        CREATE TRIGGER IF NOT EXISTS custody_events_no_update
        BEFORE UPDATE ON custody_events
        BEGIN
            SELECT RAISE(ABORT, 'custody events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS custody_events_no_delete
        BEFORE DELETE ON custody_events
        BEGIN
            SELECT RAISE(ABORT, 'custody events are append-only');
        END;
        """
    )
    connection.commit()
    return connection


def _append_event(
    connection: sqlite3.Connection,
    *,
    event_type: str,
    natural_key: str,
    payload: Mapping[str, Any],
) -> None:
    canonical = _canonical_json(_without_private_keys(payload))
    payload_hash = _sha256_text(canonical)
    existing = connection.execute(
        """
        SELECT payload_hash
        FROM custody_events
        WHERE event_type = ? AND natural_key = ?
        """,
        (event_type, natural_key),
    ).fetchone()
    if existing is not None:
        if str(existing[0]) != payload_hash:
            raise ValueError(
                "append-only custody event conflicts with prior payload"
            )
        return
    connection.execute(
        """
        INSERT INTO custody_events(
            event_at, event_type, natural_key, payload_json, payload_hash
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            event_type,
            natural_key,
            canonical,
            payload_hash,
        ),
    )
    connection.commit()


def _without_private_keys(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if not str(key).startswith("_")
    }


def _validate_store_manifest(
    *,
    manifest: Mapping[str, Any],
    manifest_path: Path,
) -> None:
    if manifest.get("schema_version") != STORE_SCHEMA_VERSION:
        raise ValueError("unsupported out-of-core store schema")
    if manifest.get("status") != "complete":
        raise ValueError("out-of-core store must be complete")
    if manifest.get("formal_source_only") is not True:
        raise ValueError("out-of-core training requires formal source only")
    if manifest.get("research_shadow_included") is not False:
        raise ValueError("research shadow data is forbidden in formal training")
    safety = _as_mapping(manifest.get("safety"), field_name="safety")
    if safety.get("pit_contract_revalidated_per_row") is not True:
        raise ValueError("PIT row validation is required")
    if safety.get("t_minus_1_contract_revalidated_per_row") is not True:
        raise ValueError("T-1 row validation is required")
    if _required_integer(
        safety.get("purge_minimum_trading_days"),
        field_name="purge_minimum_trading_days",
    ) < 60:
        raise ValueError("purge must be at least 60 trading days")
    if _required_integer(
        safety.get("embargo_minimum_trading_days"),
        field_name="embargo_minimum_trading_days",
    ) < 5:
        raise ValueError("embargo must be at least 5 trading days")
    if len(
        _mapping_sequence(manifest.get("folds"), field_name="folds")
    ) < 4:
        raise ValueError("at least four outer folds are required")
    expected_hash = _required_sha256(
        manifest.get("manifest_hash"),
        field_name="manifest_hash",
    )
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_hash:
        raise ValueError("out-of-core store manifest logical hash mismatch")
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)


def _validate_training_manifest(
    *,
    manifest: Mapping[str, Any],
    run_directory: Path,
    expected_identity: Mapping[str, Any],
) -> None:
    if manifest.get("schema_version") != TRAINING_SCHEMA_VERSION:
        raise ValueError("existing training schema mismatch")
    if manifest.get("status") != "complete":
        raise ValueError("existing training is incomplete")
    if _canonical_json(manifest.get("run_identity")) != _canonical_json(
        expected_identity
    ):
        raise ValueError("existing training identity mismatch")
    expected_hash = _required_sha256(
        manifest.get("manifest_hash"),
        field_name="manifest_hash",
    )
    body = dict(manifest)
    body.pop("manifest_hash", None)
    if _sha256_json(body) != expected_hash:
        raise ValueError("existing training manifest logical hash mismatch")
    for item in _mapping_sequence(
        manifest.get("base_experts"),
        field_name="base_experts",
    ):
        _read_and_validate_artifact(
            run_directory / str(item["artifact_path"])
        )
    for item in _mapping_sequence(
        manifest.get("final_base_experts"),
        field_name="final_base_experts",
    ):
        _read_and_validate_artifact(
            run_directory / str(item["artifact_path"])
        )
    for item in _mapping_sequence(
        manifest.get("meta_folds"),
        field_name="meta_folds",
    ):
        _read_and_validate_artifact(
            run_directory / str(item["artifact_path"])
        )
    final_meta = _as_mapping(
        manifest.get("final_meta"),
        field_name="final_meta",
    )
    _read_and_validate_artifact(
        run_directory / str(final_meta["artifact_path"])
    )


def _request_payload(
    request: AllocationOutOfCoreTrainingRequest,
) -> dict[str, Any]:
    payload = asdict(request)
    payload["store_manifest_path"] = str(request.store_manifest_path)
    payload["output_root"] = str(request.output_root)
    return payload


def _training_publication(
    *,
    run_id: str,
    run_directory: Path,
    manifest_path: Path,
    latest_manifest_path: Path,
    manifest: Mapping[str, Any],
) -> AllocationOutOfCoreTrainingPublication:
    return AllocationOutOfCoreTrainingPublication(
        run_id=run_id,
        run_directory=run_directory,
        manifest_path=manifest_path,
        latest_manifest_path=latest_manifest_path,
        manifest_hash=_required_sha256(
            manifest.get("manifest_hash"),
            field_name="manifest_hash",
        ),
        manifest_file_hash=_file_sha256(manifest_path),
        base_expert_count=_required_integer(
            manifest.get("base_expert_count"),
            field_name="base_expert_count",
        ),
        meta_fold_count=_required_integer(
            manifest.get("meta_fold_count"),
            field_name="meta_fold_count",
        ),
    )


def _write_latest_pointer(
    *,
    latest_manifest_path: Path,
    run_id: str,
    manifest: Mapping[str, Any],
) -> None:
    _atomic_write_json(
        latest_manifest_path,
        {
            "schema_version": "allocation-ooc-training-latest.v1",
            "run_id": run_id,
            "manifest_path": f"runs/{run_id}/manifest.json",
            "manifest_hash": manifest["manifest_hash"],
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "broker_order_allowed": False,
        },
    )


def _current_rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _sha256_text(value: str) -> str:
    return _SHA256_PREFIX + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(payload: object) -> str:
    return _sha256_text(_canonical_json(payload))


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        _write_json(temporary_path, payload)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _mapping_sequence(
    value: object,
    *,
    field_name: str,
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be list")
    result: list[Mapping[str, Any]] = []
    for item in value:
        result.append(_as_mapping(item, field_name=field_name))
    return tuple(result)


def _text_sequence(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError("text sequence must be list")
    return tuple(
        _required_text(item, field_name="text_sequence") for item in value
    )


def _as_mapping(
    value: object,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be object")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty string")
    return value


def _required_sha256(value: object, *, field_name: str) -> str:
    text = _required_text(value, field_name=field_name)
    if (
        not text.startswith(_SHA256_PREFIX)
        or len(text) != len(_SHA256_PREFIX) + 64
    ):
        raise ValueError(f"{field_name} must be sha256 digest")
    return text


def _required_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be integer")
    return value


def _integer_tuple(value: object, *, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be list")
    return tuple(
        _required_integer(item, field_name=field_name) for item in value
    )


def _text_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be list")
    return tuple(
        _required_text(item, field_name=field_name) for item in value
    )
