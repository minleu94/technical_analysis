"""v3 feature contract 的有界 h5 線性 shadow release producer。

這個模組把 post-freeze v3 input 與既有唯讀 Direct numeric store 接起來。
它不載入任何 v2 model artifact；歷史 fit 只讀 parent store 的 feature values、
mask 與 h5 labels，market change 以唯讀 official TAIEX close 逐交易日用
``Decimal`` 推導，然後由 ``AllocationReleaseAdapter`` 載入實際發布 bytes。

模型訓練的 NumPy／scikit-learn 浮點只存在明確的 model-boundary；跨邊界的
feature／label／calibration 數值仍是整數 scale 或整數 bp。這是一條
``v3_h5_linear_shadow`` 單 horizon／單 ridge-logistic 的研究路徑，所有
formal、alpha 與 broker 權限固定關閉。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
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
import threading
from typing import Any, Iterable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

import joblib
import numpy as np
from numpy.typing import NDArray
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app_module.allocation_release_adapter import load_allocation_release
from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.ml_storage_capacity import (
    BYTES_PER_GIB,
    CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES,
    MLStorageCapacityBudget,
    StorageCapacityError,
    acquire_heavy_chain_reservation,
    directory_size_bytes,
    heavy_chain_lock_path,
    preflight_capacity,
    release_heavy_chain_reservation,
)
from ml_module.allocation_out_of_core_training_service import (
    _NumericStore,
    _current_rss_bytes,
)
from ml_module.allocation_release_contract import (
    AllocationReleaseManifest,
    CalibrationBinding,
    IntegerProbabilityCalibrator,
    MissingPolicyBinding,
    PreprocessorBinding,
    bytes_hash,
    canonical_json,
    feature_order_hash,
    payload_hash,
)
from ml_module.allocation_rank_contract import DEFAULT_RANK_CONTRACT
from ml_module.allocation_family_weight_contract import (
    FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
    FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL,
)
from ml_module.allocation_training_service import (
    CLASSIFICATION_EXPERT_HEADS,
    EXPERT_HEAD_IDS,
    REGRESSION_EXPERT_HEADS,
)
from ml_module.allocation_out_of_core_training_service import TARGET_FIELDS
from ml_module.ooc_cross_fitted_calibration import _fit_isotonic_mapping_bp
from scripts.build_ml_allocation_post_freeze_feature_repair import (
    load_repaired_input,
)


V3_RELEASE_SCHEMA_VERSION = "allocation-v3-linear-shadow-release.v1"
V3_TRAINING_SCHEMA_VERSION = "allocation-v3-linear-shadow-training.v1"
V3_PROFILE = "v3_h5_linear_shadow"
HORIZON = 5
# Base heads are trained on an earlier bounded fold; Meta receives no model
# fitting because the frozen Direct targets are constant (see target_summary).
# The separated fold scopes make the calibration evidence independent from the
# base fit and avoid silently treating in-sample predictions as OOF.
FIT_FOLD_ID = "fold-001"
META_FIT_FOLD_ID = "fold-002"
CALIBRATION_FOLD_IDS = ("fold-003", "fold-004")
MAX_FIT_SAMPLE_ROWS = 100_000
DEFAULT_BATCH_SIZE = 8_192
PERSISTENT_BUDGET_BYTES = BYTES_PER_GIB
TEMPORARY_BUDGET_BYTES = BYTES_PER_GIB
TEMPORARY_ESTIMATE_BYTES = 256 * 1024 * 1024
SAFETY_RESERVE_BYTES = CANONICAL_HEAVY_CHAIN_SAFETY_RESERVE_BYTES
# SQLite 的 canonical market_indices 沒有事件時間欄位；正式 assembler
# 將官方收盤觀測定義在台北 14:30。這個 policy 明確把可得時間綁在
# 觀測日的收盤時刻，不能用同日 08:30 的收盤值回填盤前特徵。
MARKET_EVENT_TIME = time(14, 30)
MARKET_TIMEZONE = "Asia/Taipei"
_TAIPEI_TZ = ZoneInfo(MARKET_TIMEZONE)
MARKET_PROJECTION_POLICY = (
    "official-consecutive-close-before-decision.v2"
)
_DQ_FAMILY = "data_quality"
_EXCLUDED_FEATURES = frozenset(
    {
        "technical_indicators.涨跌",
        "technical_indicators.漲跌(+/-)",
    }
)
_DERIVED_MARKET_FEATURES = frozenset(
    {
        "market_indices.漲跌百分比",
        "market_indices.漲跌點數",
    }
)
_DQ_METRICS = (
    "coverage_bp",
    "max_available_lag_days",
    "missing_count",
    "quality_blocked_count",
    "stale_count",
)
_LABEL_FIELD_NAMES = (
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
_REGRESSION_LABEL_POSITIONS = {
    "expected_excess_return_bp": 0,
    "expected_sector_excess_return_bp": 1,
    "predicted_mae_bp": 3,
    "predicted_mfe_bp": 4,
    "predicted_realized_volatility_bp": 5,
    "predicted_max_drawdown_bp": 6,
    "predicted_tail_loss_bp": 7,
}
_CLASSIFICATION_LABEL_POSITIONS = {
    "downside_probability_bp": 2,
    "fill_feasibility_probability_bp": 8,
}
_META_FIELDS = (
    "target_weight_bp",
    "delta_weight_bp",
    "risk_contribution_bp",
    "risky_budget_bp",
    "cash_bp",
)


@dataclass(frozen=True)
class V3LinearReleaseRequest:
    """建立 v3 release 的所有輸入與有界資源政策。"""

    v3_input_path: Path
    parent_store_manifest_path: Path
    market_database_path: Path
    output_root: Path
    fit_sample_rows: int = MAX_FIT_SAMPLE_ROWS
    batch_size: int = DEFAULT_BATCH_SIZE
    acquire_heavy_lock: bool = False
    heavy_lock_path: Path | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "v3_input_path",
            "parent_store_manifest_path",
            "market_database_path",
            "output_root",
        ):
            if not isinstance(getattr(self, field_name), Path):
                raise TypeError(f"{field_name} must be a Path")
        if (
            isinstance(self.fit_sample_rows, bool)
            or not isinstance(self.fit_sample_rows, int)
            or self.fit_sample_rows < 2
            or self.fit_sample_rows > MAX_FIT_SAMPLE_ROWS
        ):
            raise ValueError("fit_sample_rows must be within 2..100000")
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or self.batch_size <= 0
            or self.batch_size > 65_536
        ):
            raise ValueError("batch_size must be within 1..65536")
        if not isinstance(self.acquire_heavy_lock, bool):
            raise TypeError("acquire_heavy_lock must be bool")
        if self.heavy_lock_path is not None and not isinstance(
            self.heavy_lock_path, Path
        ):
            raise TypeError("heavy_lock_path must be a Path or None")


@dataclass(frozen=True)
class _MarketCloseObservation:
    """SQLite official TAIEX close with an explicit event/availability time."""

    event_date: str
    event_at: str
    available_at: str
    close: Decimal


@dataclass(frozen=True)
class _MarketCloseSeries:
    """Bounded, read-only market history used by the v3 projection.

    ``market_indices`` is a daily official observation table rather than a
    PIT event table.  Its established source contract places the close at
    14:30 Asia/Taipei.  A weekday absent from this TAIEX series is unknown;
    it is never guessed to be a holiday or replaced by an arbitrary older
    row.  Weekends are the only dates that may be skipped without a source
    observation.
    """

    observations: tuple[_MarketCloseObservation, ...]
    source_path: str
    _eligibility_times: tuple[datetime, ...] = field(init=False, repr=False)
    _calendar: OfficialTradingCalendar = field(init=False, repr=False)
    _calendar_cache: dict[str, bool | None] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        parsed_times = tuple(
            max(
                _parse_aware_datetime(item.event_at, field_name="market event_at"),
                _parse_aware_datetime(
                    item.available_at, field_name="market available_at"
                ),
            )
            for item in self.observations
        )
        if tuple(item.event_date for item in self.observations) != tuple(
            sorted(item.event_date for item in self.observations)
        ):
            raise ValueError("market close observations must be date ordered")
        if any(
            parsed_times[index] > parsed_times[index + 1]
            for index in range(len(parsed_times) - 1)
        ):
            raise ValueError("market close availability must be ordered")
        object.__setattr__(self, "_eligibility_times", parsed_times)
        object.__setattr__(
            self,
            "_calendar",
            OfficialTradingCalendar(db_path=self.source_path),
        )
        object.__setattr__(self, "_calendar_cache", {})

    @property
    def dates(self) -> frozenset[str]:
        return frozenset(item.event_date for item in self.observations)

    def __len__(self) -> int:
        return len(self.observations)

    @property
    def first_date(self) -> str | None:
        return self.observations[0].event_date if self.observations else None

    @property
    def last_date(self) -> str | None:
        return self.observations[-1].event_date if self.observations else None

    def _eligible(self, decision_at: str) -> tuple[_MarketCloseObservation, ...]:
        cutoff = _parse_aware_datetime(decision_at, field_name="decision_at")
        end = bisect_right(self._eligibility_times, cutoff)
        return self.observations[:end]

    def _calendar_status(self, value: date) -> bool | None:
        key = value.isoformat()
        if key not in self._calendar_cache:
            status, _reason = self._calendar.is_official_trading_day(
                value,
                allow_online_probe=False,
            )
            self._calendar_cache[key] = status
        return self._calendar_cache[key]

    def _pair_is_valid(
        self,
        current: _MarketCloseObservation,
        previous: _MarketCloseObservation,
        decision_at: str,
    ) -> bool:
        cutoff = _parse_aware_datetime(decision_at, field_name="decision_at")
        try:
            current_date = date.fromisoformat(current.event_date)
            decision_date = cutoff.astimezone(_TAIPEI_TZ).date()
        except ValueError as exc:
            raise ValueError("market event dates must be canonical") from exc
        return _official_dates_are_consecutive(
            previous.event_date,
            current.event_date,
            observed_dates=self.dates,
            calendar_status=self._calendar_status,
        ) and _official_sessions_before_decision_are_known(
            current_date,
            decision_date,
            observed_dates=self.dates,
            calendar_status=self._calendar_status,
        )

    def pair_for_decision(
        self,
        decision_at: str,
    ) -> tuple[_MarketCloseObservation, _MarketCloseObservation] | None:
        """Return ``(current, previous)`` only for a proven prior pair."""

        eligible = self._eligible(decision_at)
        if len(eligible) < 2:
            return None
        current, previous = eligible[-1], eligible[-2]
        if not self._pair_is_valid(current, previous, decision_at):
            return None
        return current, previous

    def pair_reason(self, decision_at: str) -> str | None:
        """Explain why a decision timestamp has no usable close pair."""

        eligible = self._eligible(decision_at)
        if len(eligible) < 2:
            cutoff = _parse_aware_datetime(decision_at, field_name="decision_at")
            if any(
                item.event_date == cutoff.date().isoformat()
                and _parse_aware_datetime(
                    item.available_at, field_name="market available_at"
                )
                > cutoff
                for item in self.observations
            ):
                return "same_day_close_unavailable_before_decision"
            return "insufficient_pre_decision_close_observations"
        current, previous = eligible[-1], eligible[-2]
        if not _official_dates_are_consecutive(
            previous.event_date,
            current.event_date,
            observed_dates=self.dates,
            calendar_status=self._calendar_status,
        ):
            return "official_trading_day_continuity_unproven"
        cutoff = _parse_aware_datetime(decision_at, field_name="decision_at")
        if not _official_sessions_before_decision_are_known(
            date.fromisoformat(current.event_date),
            cutoff.astimezone(_TAIPEI_TZ).date(),
            observed_dates=self.dates,
            calendar_status=self._calendar_status,
        ):
            return "official_trading_day_gap_before_decision"
        return None


@dataclass
class _V3CapacityMonitor:
    """執行中重查 filesystem/RSS，將 estimate 與 observed 分開保存。"""

    output_root: Path
    source_probe: Path
    temporary_root: Path
    baseline_output_bytes: int
    budget: MLStorageCapacityBudget
    memory_budget_bytes: int = 4_096 * 1024 * 1024

    def __post_init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.peak_rss_bytes = 0
        self.peak_temporary_bytes = 0
        self._stopped = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        initial = _current_rss_bytes()
        if initial is None:
            raise RuntimeError("v3 RSS measurement unavailable; capacity fails closed")
        self.peak_rss_bytes = initial

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._poll_rss,
            name="allocation-v3-rss-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self.checkpoint("monitor_stop")

    def _poll_rss(self) -> None:
        while not self._stop.wait(0.1):
            current = _current_rss_bytes()
            if current is None:
                continue
            self.peak_rss_bytes = max(self.peak_rss_bytes, current)
            if self.peak_rss_bytes > self.memory_budget_bytes:
                self._stop.set()
                return

    def checkpoint(self, stage: str) -> dict[str, Any]:
        current = _current_rss_bytes()
        if current is None:
            raise RuntimeError(
                "v3 RSS measurement failed during execution; capacity fails closed"
            )
        self.peak_rss_bytes = max(self.peak_rss_bytes, current)
        if self.peak_rss_bytes > self.memory_budget_bytes:
            raise MemoryError(
                f"v3 memory budget exceeded at {stage}: "
                f"{self.peak_rss_bytes} > {self.memory_budget_bytes}"
            )
        temporary_bytes = directory_size_bytes(self.temporary_root)
        self.peak_temporary_bytes = max(self.peak_temporary_bytes, temporary_bytes)
        output_bytes = directory_size_bytes(self.output_root)
        persistent_new = max(0, output_bytes - self.baseline_output_bytes)
        capacity = preflight_capacity(
            probe_path=_nearest_existing(self.output_root),
            budget=self.budget,
            stage=f"v3_linear_execution_{stage}",
            persistent_roots=(self.output_root,) if self.output_root.exists() else (),
            persistent_new_bytes_estimate=persistent_new,
            temporary_roots=(self.temporary_root,),
            temporary_peak_bytes_observed=temporary_bytes,
        ).as_dict()
        source_capacity = preflight_capacity(
            probe_path=_nearest_existing(self.source_probe),
            budget=self.budget,
            stage=f"v3_linear_source_execution_{stage}",
            persistent_roots=(),
            persistent_new_bytes_estimate=0,
            temporary_roots=(),
            temporary_peak_bytes_observed=0,
        ).as_dict()
        record = {
            "stage": stage,
            "persistent_output_bytes": output_bytes,
            "persistent_new_bytes_observed": persistent_new,
            "temporary_bytes_observed": temporary_bytes,
            "peak_temporary_bytes_observed": self.peak_temporary_bytes,
            "rss_bytes_observed": current,
            "peak_rss_bytes_observed": self.peak_rss_bytes,
            "memory_budget_bytes": self.memory_budget_bytes,
            "memory_enforcement": "sampling_and_stage_checkpoints",
            "within_memory_budget": self.peak_rss_bytes <= self.memory_budget_bytes,
            "temporary_measurement_scope": "producer_owned_temp_root_only",
            "capacity": capacity,
            "source_capacity": source_capacity,
        }
        self.records.append(record)
        return record


def preflight_v3_linear_release(
    request: V3LinearReleaseRequest,
) -> dict[str, Any]:
    """只讀確認 v3 input、h5 labels、market source 與容量政策。"""

    input_path = request.v3_input_path.resolve()
    parent_path = request.parent_store_manifest_path.resolve()
    market_path = request.market_database_path.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if not parent_path.is_file():
        raise FileNotFoundError(parent_path)
    if not market_path.is_file():
        raise FileNotFoundError(market_path)
    payload, rows = _load_v3_input(input_path)
    store = _NumericStore(parent_path)
    if HORIZON not in store.horizons:
        raise ValueError("parent store does not contain h5 labels")
    _validate_v3_rows(rows, payload)
    lock_path = _resolve_shared_lock_path(parent_path, request.heavy_lock_path)
    market = _load_market_close_pairs(market_path)
    fit_refs = _fold_refs(store, FIT_FOLD_ID, "train")
    fit_projection_refs, fit_projection_scope = _select_projection_refs(
        store, fit_refs
    )
    fit_sample_refs = _sample_refs(fit_projection_refs, request.fit_sample_rows)
    meta_refs = _fold_refs(store, META_FIT_FOLD_ID, "test")
    meta_projection_refs, meta_projection_scope = _select_projection_refs(
        store, meta_refs
    )
    meta_sample_refs = _sample_refs(meta_projection_refs, request.fit_sample_rows)
    calibration_refs_with_scope = tuple(
        _select_projection_refs(store, _fold_refs(store, fold_id, "test"))
        for fold_id in CALIBRATION_FOLD_IDS
    )
    calibration_refs = tuple(item[0] for item in calibration_refs_with_scope)
    calibration_projection_scope = {
        fold_id: item[1]
        for fold_id, item in zip(CALIBRATION_FOLD_IDS, calibration_refs_with_scope)
    }
    fit_label_stats = _label_stats(store, fit_sample_refs, HORIZON)
    meta_label_stats = _label_stats(store, meta_sample_refs, HORIZON)
    fit_target_stats = _target_stats(store, fit_sample_refs)
    meta_target_stats = _target_stats(store, meta_sample_refs)
    calibration_label_stats = {
        fold_id: _label_stats(store, refs, HORIZON)
        for fold_id, refs in zip(CALIBRATION_FOLD_IDS, calibration_refs)
    }
    fit_metadata = _ref_metadata(store, fit_sample_refs)
    meta_metadata = _ref_metadata(store, meta_sample_refs)
    calibration_metadata = {
        fold_id: _ref_metadata(store, refs)
        for fold_id, refs in zip(CALIBRATION_FOLD_IDS, calibration_refs)
    }
    _validate_calibration_separation(
        fit_metadata=fit_metadata,
        calibration_metadata=calibration_metadata,
    )
    calibration_label_maturity = {
        fold_id: _validate_horizon_label_maturity(
            store,
            refs,
            calibration_metadata[fold_id][0],
        )
        for fold_id, refs in zip(CALIBRATION_FOLD_IDS, calibration_refs)
    }
    decision_at_sets = {
        "fit": fit_metadata[0],
        "meta": meta_metadata[0],
        **{
            fold_id: calibration_metadata[fold_id][0]
            for fold_id, refs in zip(CALIBRATION_FOLD_IDS, calibration_refs)
        },
    }
    market_coverage = {
        name: _market_coverage(decision_ats, market)
        for name, decision_ats in decision_at_sets.items()
    }
    _close_memmap(fit_refs)
    _close_memmap(fit_projection_refs)
    _close_memmap(fit_sample_refs)
    _close_memmap(meta_refs)
    _close_memmap(meta_projection_refs)
    _close_memmap(meta_sample_refs)
    for refs in calibration_refs:
        _close_memmap(refs)

    output_root = request.output_root.resolve()
    output_probe = _nearest_existing(output_root)
    source_probe = _nearest_existing(parent_path)
    budget = MLStorageCapacityBudget(
        persistent_new_bytes_budget=PERSISTENT_BUDGET_BYTES,
        temporary_peak_bytes_budget=TEMPORARY_BUDGET_BYTES,
        safety_reserve_bytes=SAFETY_RESERVE_BYTES,
    )
    output_capacity = preflight_capacity(
        probe_path=output_probe,
        budget=budget,
        stage="v3_linear_output_preflight",
        persistent_roots=(output_root,) if output_root.exists() else (),
        persistent_new_bytes_estimate=64 * 1024 * 1024,
        temporary_peak_bytes_observed=TEMPORARY_ESTIMATE_BYTES,
    )
    source_capacity = preflight_capacity(
        probe_path=source_probe,
        budget=budget,
        stage="v3_linear_source_preflight",
        persistent_roots=(),
        persistent_new_bytes_estimate=0,
        temporary_peak_bytes_observed=0,
    )
    return {
        "schema_version": V3_RELEASE_SCHEMA_VERSION,
        "status": "preflight_passed",
        "v3_input": {
            "path": str(input_path),
            "compressed_file_hash": _file_hash(input_path),
            "row_count": len(rows),
            "feature_count": len(rows[0].features),
            "contract_hash": payload["feature_contract_hash"],
            "dataset_identity_hash": rows[0].dataset_identity_hash,
            "decision_at": rows[0].decision_at,
            "excluded_feature_ids": sorted(_EXCLUDED_FEATURES),
            "derived_market_feature_ids": sorted(_DERIVED_MARKET_FEATURES),
        },
        "parent_store": {
            "path": str(parent_path),
            "manifest_file_hash": store.manifest_file_hash,
            "manifest_hash": store.manifest["manifest_hash"],
            "dataset_identity_hash": store.manifest["dataset_identity_hash"],
            "row_count": store.manifest["row_count"],
            "feature_count": store.manifest["feature_count"],
            "horizons": list(store.horizons),
            "fit_fold_id": FIT_FOLD_ID,
            "meta_fold_id": META_FIT_FOLD_ID,
            "calibration_fold_ids": list(CALIBRATION_FOLD_IDS),
            "fold_005_or_later_read": False,
            "fold_006_or_later_read": False,
        },
        "market_source": {
            "path": str(market_path),
            "file_hash": _file_hash(market_path),
            "tai_ex_close_count": len(market),
            "first_date": market.first_date,
            "last_date": market.last_date,
            "first_event_at": (
                None if not market.observations else market.observations[0].event_at
            ),
            "last_event_at": (
                None if not market.observations else market.observations[-1].event_at
            ),
            "event_time_policy": "Asia/Taipei 14:30:00",
            "availability_policy": "event_at",
            "projection_policy": MARKET_PROJECTION_POLICY,
            "weekday_gap_policy": "unknown_weekday_fails_closed",
        },
        "label_scope": {
            "horizon": HORIZON,
            "fit_sample": fit_label_stats,
            "meta_scope": meta_label_stats,
            "calibration": calibration_label_stats,
            "calibration_maturity": calibration_label_maturity,
        },
        "calibration_separation": {
            "base_fit_row_ids_hash": payload_hash(list(fit_metadata[2])),
            "calibration_row_ids_hash_by_fold": {
                fold_id: payload_hash(list(calibration_metadata[fold_id][2]))
                for fold_id in CALIBRATION_FOLD_IDS
            },
            "row_identity_overlap": False,
            "decision_at_order_verified": True,
        },
        "target_scope": {
            "fit_sample": fit_target_stats,
            "meta_sample": meta_target_stats,
            "training_skipped_when_constant": True,
        },
        "parent_dq_projection": {
            "fit": fit_projection_scope,
            "meta": meta_projection_scope,
            "calibration": calibration_projection_scope,
        },
        "market_date_coverage": market_coverage,
        "capacity": {
            "persistent_budget_bytes": PERSISTENT_BUDGET_BYTES,
            "temporary_budget_bytes": TEMPORARY_BUDGET_BYTES,
            "temporary_peak_estimate_bytes": TEMPORARY_ESTIMATE_BYTES,
            "memory_budget_mb": 4_096,
            "safety_reserve_bytes": SAFETY_RESERVE_BYTES,
            "output": output_capacity.as_dict(),
            "source": source_capacity.as_dict(),
            "shared_heavy_lock_path": str(lock_path.resolve()),
            "temporary_measurement": "preflight_estimate_only",
        },
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "broker_order_allowed": False,
    }


def _build_v3_linear_release_unlocked(
    request: V3LinearReleaseRequest,
) -> dict[str, Any]:
    """建立並 readback 一個新的 v3 h5 線性 shadow release。"""

    preflight = preflight_v3_linear_release(request)
    input_path = request.v3_input_path.resolve()
    parent_path = request.parent_store_manifest_path.resolve()
    market_path = request.market_database_path.resolve()
    payload, rows = _load_v3_input(input_path)
    store = _NumericStore(parent_path)
    market = _load_market_close_pairs(market_path)
    contract_hash = str(payload["feature_contract_hash"])
    feature_order, packs = _v3_feature_layout(rows)
    readback_mode = _readback_inference_mode(rows)
    # consumer/preprocessor 的 canonical order 是 family pack 串接後、各
    # pack 內 feature id 排序；來源 row 的全域 feature id 排序會把 pack
    # 邊界打散，不能拿來驗證 release layout。
    expected_feature_order = tuple(
        feature_id for _pack_id, feature_ids in packs for feature_id in feature_ids
    )
    if feature_order != expected_feature_order:
        raise ValueError("v3 feature order does not match frozen pack layout")
    source_hashes = tuple(sorted(rows[0].source_manifest_hashes))
    input_hash = _file_hash(input_path)
    fit_refs = _fold_refs(store, FIT_FOLD_ID, "train")
    fit_projection_refs, fit_projection_scope = _select_projection_refs(
        store, fit_refs
    )
    fit_sample_refs = _sample_refs(fit_projection_refs, request.fit_sample_rows)
    fit_decision_ats, fit_symbols, fit_row_ids = _ref_metadata(
        store, fit_sample_refs
    )
    meta_refs = _fold_refs(store, META_FIT_FOLD_ID, "test")
    meta_projection_refs, meta_projection_scope = _select_projection_refs(
        store, meta_refs
    )
    meta_sample_refs = _sample_refs(meta_projection_refs, request.fit_sample_rows)
    meta_decision_ats, meta_symbols, meta_row_ids = _ref_metadata(
        store, meta_sample_refs
    )
    calibration_ref_sets_with_scope = {
        fold_id: _select_projection_refs(
            store, _fold_refs(store, fold_id, "test")
        )
        for fold_id in CALIBRATION_FOLD_IDS
    }
    calibration_ref_sets = {
        fold_id: item[0]
        for fold_id, item in calibration_ref_sets_with_scope.items()
    }
    calibration_projection_scope = {
        fold_id: item[1]
        for fold_id, item in calibration_ref_sets_with_scope.items()
    }
    calibration_metadata = {
        fold_id: _ref_metadata(store, refs)
        for fold_id, refs in calibration_ref_sets.items()
    }
    calibration_label_maturity = {
        fold_id: _validate_horizon_label_maturity(
            store,
            refs,
            calibration_metadata[fold_id][0],
        )
        for fold_id, refs in calibration_ref_sets.items()
    }
    baseline_output_bytes = (
        directory_size_bytes(request.output_root.resolve())
        if request.output_root.exists()
        else 0
    )
    temporary_root = Path(
        tempfile.mkdtemp(prefix="technical_analysis_v3_linear_")
    )
    try:
        capacity_monitor = _V3CapacityMonitor(
            output_root=request.output_root.resolve(),
            source_probe=parent_path,
            temporary_root=temporary_root,
            baseline_output_bytes=baseline_output_bytes,
            budget=MLStorageCapacityBudget(
                persistent_new_bytes_budget=PERSISTENT_BUDGET_BYTES,
                temporary_peak_bytes_budget=TEMPORARY_BUDGET_BYTES,
                safety_reserve_bytes=SAFETY_RESERVE_BYTES,
            ),
        )
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    try:
        capacity_monitor.start()
        capacity_monitor.checkpoint("inputs_loaded")
        fit_matrix = _project_matrix(
            store,
            fit_sample_refs,
            fit_decision_ats,
            feature_order,
            market,
            batch_size=request.batch_size,
        )
        capacity_monitor.checkpoint("fit_projection")
        fit_labels, fit_label_masks = store.read_label_batch(
            np.asarray(fit_sample_refs, dtype=np.int64),
            HORIZON,
        )
        calibration_matrices = {
            fold_id: _project_matrix(
                store,
                refs,
                calibration_metadata[fold_id][0],
                feature_order,
                market,
                batch_size=request.batch_size,
            )
            for fold_id, refs in calibration_ref_sets.items()
        }
        capacity_monitor.checkpoint("calibration_projection")
        models = _fit_base_models(
            fit_matrix,
            fit_labels,
            fit_label_masks,
            packs=packs,
            feature_order=feature_order,
            fit_row_ids=fit_row_ids,
        )
        capacity_monitor.checkpoint("base_fit")
        calibration_mapping, calibration_evidence = _fit_calibrator(
            models=models,
            calibration_matrices=calibration_matrices,
            calibration_ref_sets=calibration_ref_sets,
            store=store,
            calibration_metadata=calibration_metadata,
            fit_metadata=(fit_decision_ats, fit_symbols, fit_row_ids),
            packs=packs,
            feature_order=feature_order,
        )
        capacity_monitor.checkpoint("calibration_fit")
        # The Direct parent records constant allocation targets.  Do not fit a
        # constant Meta estimator and then present it as an identified
        # allocator.  A neutral, explicitly marked adapter Meta keeps the
        # existing inference schema loadable while all research signal remains
        # in the base expert heads and their calibrated downside readout.
        meta_targets = store.read_target_batch(
            np.asarray(meta_sample_refs, dtype=np.int64)
        )
        meta_models, target_summary = _build_neutral_meta_models(
            targets=meta_targets,
            meta_row_ids=meta_row_ids,
        )
        capacity_monitor.checkpoint("meta_validation")
        training_identity = {
            "schema_version": V3_TRAINING_SCHEMA_VERSION,
            "profile": V3_PROFILE,
            "horizon": HORIZON,
            "algorithm": "ridge_logistic",
            "v3_input_hash": input_hash,
            "v3_contract_hash": contract_hash,
            "parent_store_manifest_hash": store.manifest["manifest_hash"],
            "parent_store_manifest_file_hash": store.manifest_file_hash,
            "market_database_file_hash": _file_hash(market_path),
            "fit_fold_id": FIT_FOLD_ID,
            "meta_fold_id": META_FIT_FOLD_ID,
            "fit_source_row_count": len(fit_refs),
            "fit_projection_row_count": fit_projection_scope["eligible_rows"],
            "fit_sample_row_count": len(fit_sample_refs),
            "meta_source_row_count": len(meta_refs),
            "meta_projection_row_count": meta_projection_scope["eligible_rows"],
            "meta_sample_row_count": len(meta_sample_refs),
            "parent_dq_projection": {
                "fit": fit_projection_scope,
                "meta": meta_projection_scope,
                "calibration": calibration_projection_scope,
            },
            "calibration_fold_ids": list(CALIBRATION_FOLD_IDS),
            "calibration_row_count": sum(
                len(refs) for refs in calibration_ref_sets.values()
            ),
            "feature_order": list(feature_order),
            "feature_packs": [[pack_id, list(ids)] for pack_id, ids in packs],
            "rank_contract": DEFAULT_RANK_CONTRACT,
            "meta_probability_input": "calibrated",
            "market_projection_policy": MARKET_PROJECTION_POLICY,
            "market_event_time_policy": "Asia/Taipei 14:30:00",
            "readback_inference_mode": readback_mode,
            # 此欄位描述 immutable training manifest 寫入前的 readback
            # 計畫；真正是否成功必須由 build result 與獨立 audit 證明，
            # 避免 readback 失敗時把預定 mode 誤當成成功。
            "inference_readback_status": "planned_before_publish",
            "calibration_label_maturity": calibration_label_maturity,
            "fold_scope": {
                fold_id: _fold_scope(store, fold_id)
                for fold_id in (
                    FIT_FOLD_ID,
                    META_FIT_FOLD_ID,
                    *CALIBRATION_FOLD_IDS,
                )
            },
        }
        training_hash = payload_hash(training_identity)
        target_summary = {
            **target_summary,
            "training_manifest_hash": training_hash,
            "all_meta_targets_constant": bool(
                target_summary["all_meta_targets_constant"]
            ),
        }
        artifact_payload = _artifact_payload(
            models=models,
            meta_models=meta_models,
            packs=packs,
            feature_order=feature_order,
            dataset_id="all_field_enriched-v3-market-repair",
            dataset_identity_hash=rows[0].dataset_identity_hash,
            dataset_manifest_file_hash=input_hash,
            feature_registry_hash=contract_hash,
            source_manifest_hashes=source_hashes,
            training_as_of=_training_as_of(store),
            fit_row_ids=fit_row_ids,
            training_profile=V3_PROFILE,
            target_summary=target_summary,
        )
        artifact_bytes = _joblib_bytes(artifact_payload)
        artifact_hash = bytes_hash(artifact_bytes)
        calibrator = IntegerProbabilityCalibrator.create(
            calibration_id=str(calibration_evidence["calibration_id"]),
            model_id="baldr-ml-allocation-v3-h5-linear-shadow",
            feature_order_hash=feature_order_hash(feature_order),
            mapping_bp=calibration_mapping,
            fit_fold_ids=CALIBRATION_FOLD_IDS,
        )
        calibrator_bytes = (
            (canonical_json(calibrator.to_dict()) + "\n").encode("utf-8")
        )
        preprocessor_binding, preprocessor_bytes = _preprocessor_binding(
            model_id="baldr-ml-allocation-v3-h5-linear-shadow",
            order_hash=feature_order_hash(feature_order),
            training_hash=training_hash,
        )
        calibration_binding = CalibrationBinding(
            calibration_id=calibrator.calibration_id,
            model_id=calibrator.model_id,
            method=calibrator.method,
            application="external_integer_bp",
            feature_order_hash=calibrator.feature_order_hash,
            artifact_file="calibrator.json",
            artifact_hash=bytes_hash(calibrator_bytes),
            fit_fold_ids=calibrator.fit_fold_ids,
        )
        missing_policy = MissingPolicyBinding.create(
            policy_id="v3-explicit-mask-neutral-fallback-v1"
        )
        release_identity_seed = {
            "training_hash": training_hash,
            "artifact_hash": artifact_hash,
            "calibrator_hash": calibration_binding.artifact_hash,
            "feature_contract_hash": contract_hash,
            "input_hash": input_hash,
        }
        release_id = "v3-linear-h5-" + payload_hash(release_identity_seed)[7:23]
        release = AllocationReleaseManifest.create(
            release_id=release_id,
            model_id=calibrator.model_id,
            dataset_id="all_field_enriched-v3-market-repair",
            training_manifest_hash=training_hash,
            artifact_file="model.joblib",
            artifact_hash=artifact_hash,
            dataset_identity_hash=rows[0].dataset_identity_hash,
            feature_registry_hash=contract_hash,
            source_manifest_hashes=source_hashes,
            feature_order=feature_order,
            preprocessor=preprocessor_binding,
            calibration=calibration_binding,
            missing_policy=missing_policy,
        )
        training_payload = {
            **training_identity,
            "manifest_hash": training_hash,
            "artifact_hash": artifact_hash,
            "calibrator": calibration_evidence,
            "calibrator_contract_hash": calibrator.contract_hash,
            "target_summary": target_summary,
            "inference_readback": {
                "mode": readback_mode,
                "decision_at": rows[0].decision_at,
                "status": "planned_before_publish",
            },
            "source_manifest_hashes": [list(item) for item in source_hashes],
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
            "capacity_execution": {
                "measurement": "observed_during_execution",
                "stages": capacity_monitor.records,
                "temporary_root": str(temporary_root),
                "temporary_measurement_scope": "producer_owned_temp_root_only",
                "memory_enforcement": "sampling_and_stage_checkpoints",
            },
        }
        release_root = _release_run_root(request.output_root, release.release_id)
        capacity_monitor.checkpoint("publish_preflight")
        publish_result = _publish_release(
            release_root=release_root,
            output_root=request.output_root.resolve(),
            release=release,
            artifact_bytes=artifact_bytes,
            preprocessor_bytes=preprocessor_bytes,
            calibrator_bytes=calibrator_bytes,
            training_bytes=(canonical_json(training_payload) + "\n").encode("utf-8"),
            baseline_bytes=baseline_output_bytes,
        )
        capacity_monitor.checkpoint("publish")
        loaded = load_allocation_release(release_root)
        consumed = _infer_release_readback(
            loaded=loaded,
            rows=rows,
            policy_id=missing_policy.policy_id,
            policy_hash=missing_policy.policy_hash,
        )
        capacity_monitor.checkpoint("readback")
        audit = consumed.audit_payload()
        capacity_monitor.stop()
        execution_capacity = {
            "measurement": "observed_during_execution",
            "stages": list(capacity_monitor.records),
            "peak_rss_bytes_observed": capacity_monitor.peak_rss_bytes,
            "peak_temporary_bytes_observed": capacity_monitor.peak_temporary_bytes,
            "memory_budget_bytes": capacity_monitor.memory_budget_bytes,
            "within_memory_budget": (
                capacity_monitor.peak_rss_bytes
                <= capacity_monitor.memory_budget_bytes
            ),
            "memory_enforcement": "sampling_and_stage_checkpoints",
            "temporary_measurement_scope": "producer_owned_temp_root_only",
            "temporary_root_cleaned_after_readback": True,
        }
        return {
            "status": "v3_linear_shadow_release_published",
            "release_id": release.release_id,
            "release_root": str(release_root),
            "release_manifest": str(release_root / "release_manifest.json"),
            "release_identity_hash": release.release_identity_hash,
            "model_artifact_hash": artifact_hash,
            "calibrator_id": calibrator.calibration_id,
            "calibrator_contract_hash": calibrator.contract_hash,
            "fit_fold_id": FIT_FOLD_ID,
            "calibration_fit_fold_ids": list(CALIBRATION_FOLD_IDS),
            "parent_dq_projection": {
                "fit": fit_projection_scope,
                "meta": meta_projection_scope,
                "calibration": calibration_projection_scope,
            },
            "fit_sample_row_count": len(fit_sample_refs),
            "meta_sample_row_count": len(meta_sample_refs),
            "calibration_row_count": sum(
                len(refs) for refs in calibration_ref_sets.values()
            ),
            "inference_row_count": len(rows),
            "inference_readback_mode": readback_mode,
            "inference_readback_status": "verified_after_publish",
            "inference_readback_audit_hash": payload_hash(audit),
            "inference_audit_hash": payload_hash(audit),
            "meta_targets_constant": target_summary["all_meta_targets_constant"],
            "meta_training_skipped": target_summary["training_skipped"],
            "target_summary_status": target_summary["status"],
            "publish": publish_result,
            "capacity_execution": execution_capacity,
            "preflight": preflight,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
        }
    finally:
        _close_memmap(fit_refs)
        _close_memmap(fit_projection_refs)
        _close_memmap(fit_sample_refs)
        for refs in calibration_ref_sets.values():
            _close_memmap(refs)
        _close_memmap(meta_refs)
        _close_memmap(meta_projection_refs)
        _close_memmap(meta_sample_refs)
        try:
            capacity_monitor.stop()
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)


def build_v3_linear_release(
    request: V3LinearReleaseRequest,
) -> dict[str, Any]:
    """在需要時持有全鏈 reservation，再建立單一 immutable release。"""

    if not request.acquire_heavy_lock:
        return _build_v3_linear_release_unlocked(request)
    lock_path = _resolve_shared_lock_path(
        request.parent_store_manifest_path.resolve(),
        request.heavy_lock_path,
    )
    reservation = acquire_heavy_chain_reservation(lock_path)
    if reservation is None:
        raise StorageCapacityError(
            "shared heavy chain lock is already held",
            preflight={"stage": "v3_linear_release_lock", "path": str(lock_path)},
        )
    try:
        # Recheck source/output capacity while the shared lock is held.  The
        # producer itself remains the only writer under the repository output
        # root; the Direct parent and market database are opened read-only.
        preflight_v3_linear_release(request)
        return _build_v3_linear_release_unlocked(request)
    finally:
        release_heavy_chain_reservation(reservation)


def _load_v3_input(
    path: Path,
) -> tuple[dict[str, Any], tuple[Any, ...]]:
    try:
        payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid v3 input") from exc
    if not isinstance(payload, dict):
        raise TypeError("v3 input payload must be an object")
    expected = payload.get("feature_contract_hash")
    if not isinstance(expected, str):
        raise ValueError("v3 input feature contract hash is missing")
    rows = load_repaired_input(path, expected_contract_hash=expected)
    return payload, rows


def _validate_v3_rows(rows: Sequence[Any], payload: Mapping[str, Any]) -> None:
    if not rows:
        raise ValueError("v3 input rows must not be empty")
    expected_hash = payload.get("feature_contract_hash")
    expected_features = {
        feature.feature_id: feature.family_id for feature in rows[0].features
    }
    expected_ids = set(expected_features)
    if len(expected_ids) != 60:
        raise ValueError("v3 input must contain exactly 60 features")
    if _EXCLUDED_FEATURES & expected_ids:
        raise ValueError("v3 input still contains excluded classification fields")
    if not _DERIVED_MARKET_FEATURES.issubset(expected_ids):
        raise ValueError("v3 input is missing derived market changes")
    if not isinstance(expected_hash, str) or rows[0].feature_registry_hash != expected_hash:
        raise ValueError("v3 input contract identity mismatch")
    expected_dataset_identity = rows[0].dataset_identity_hash
    expected_sources = rows[0].source_manifest_hashes
    expected_decision_at = rows[0].decision_at
    seen_row_ids: set[str] = set()
    seen_symbols: set[str] = set()
    for row in rows:
        if row.feature_registry_hash != expected_hash:
            raise ValueError("v3 rows do not share one feature contract")
        if row.dataset_identity_hash != expected_dataset_identity:
            raise ValueError("v3 rows do not share one dataset identity")
        if row.source_manifest_hashes != expected_sources:
            raise ValueError("v3 rows do not share one source lineage")
        if row.decision_at != expected_decision_at:
            raise ValueError("v3 rows do not share one decision timestamp")
        if row.targets is not None:
            raise ValueError("v3 inference input must not contain targets")
        row_features = {
            feature.feature_id: feature.family_id for feature in row.features
        }
        if row_features != expected_features:
            raise ValueError("v3 rows do not share the complete feature layout")
        if row.row_id in seen_row_ids or row.symbol in seen_symbols:
            raise ValueError("v3 rows contain duplicate row identity")
        seen_row_ids.add(row.row_id)
        seen_symbols.add(row.symbol)


def _readback_inference_mode(rows: Sequence[Any]) -> str:
    """決定 readback 使用正式 daily 或明確標記的研究入口。"""

    if not rows:
        raise ValueError("readback rows are empty")
    decision_at = _parse_aware_datetime(
        rows[0].decision_at,
        field_name="readback decision_at",
    ).astimezone(_TAIPEI_TZ)
    if decision_at.timetz().replace(tzinfo=None) == time(8, 30):
        return "daily_08_30"
    if all(
        str(row.row_id).startswith("row:post-freeze-shadow:")
        for row in rows
    ):
        return "post_freeze_research_shadow"
    raise ValueError(
        "non-08:30 readback requires post-freeze-shadow row identity"
    )


def _infer_release_readback(
    *,
    loaded: Any,
    rows: Sequence[Any],
    policy_id: str,
    policy_hash: str,
) -> Any:
    """在不放寬正式 consumer 時鐘下執行 release readback。"""

    mode = _readback_inference_mode(rows)
    arguments = {
        "rows": rows,
        "universe_id": "v3-post-freeze-11",
        "policy_id": policy_id,
        "policy_hash": policy_hash,
    }
    if mode == "daily_08_30":
        return loaded.infer(**arguments)
    return loaded.infer_research_shadow(**arguments)


def _v3_feature_layout(
    rows: Sequence[Any],
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    family_ids: dict[str, set[str]] = {}
    for feature in rows[0].features:
        family_ids.setdefault(feature.family_id, set()).add(feature.feature_id)
    packs = tuple(
        (family_id, tuple(sorted(ids)))
        for family_id, ids in sorted(family_ids.items())
    )
    if tuple(pack_id for pack_id, _ in packs) != (
        "data_quality",
        "market_sector_cross_section",
        "price_liquidity_technical",
    ):
        raise ValueError("v3 feature families do not match frozen three-pack layout")
    order = tuple(feature_id for _, ids in packs for feature_id in ids)
    if len(order) != 60 or len(set(order)) != 60:
        raise ValueError("v3 feature order is incomplete")
    return order, packs


def _parse_aware_datetime(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed


def _canonical_market_date(value: object) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"market date is invalid: {value!r}") from exc
    if parsed.isoformat() != text[:10]:
        raise ValueError(f"market date is not canonical: {value!r}")
    return parsed.isoformat()


def _official_dates_are_consecutive(
    previous_date: str,
    current_date: str,
    *,
    observed_dates: frozenset[str],
    calendar_status: Any | None = None,
) -> bool:
    """驗證兩筆觀測間每個官方交易日都有 source evidence。"""

    try:
        previous = date.fromisoformat(previous_date)
        current = date.fromisoformat(current_date)
    except ValueError as exc:
        raise ValueError("market event dates must be canonical") from exc
    if previous >= current:
        return False
    cursor = previous + timedelta(days=1)
    while cursor < current:
        status = (
            calendar_status(cursor)
            if calendar_status is not None
            else (False if cursor.weekday() >= 5 else True)
        )
        if status is None:
            return False
        if status is True and cursor.isoformat() not in observed_dates:
            return False
        cursor += timedelta(days=1)
    return True


def _official_sessions_before_decision_are_known(
    current_date: date,
    decision_date: date,
    *,
    observed_dates: frozenset[str],
    calendar_status: Any,
) -> bool:
    """拒絕最新 close 與決策日間遺失的官方 session。"""

    cursor = current_date + timedelta(days=1)
    while cursor < decision_date:
        status = calendar_status(cursor)
        if status is None:
            return False
        if status is True and cursor.isoformat() not in observed_dates:
            return False
        cursor += timedelta(days=1)
    return True


def _load_market_close_pairs(path: Path) -> _MarketCloseSeries:
    """讀取唯讀 SQLite，並以決策 timestamp 選取可得的 close pair。

    SQLite schema 沒有 ``event_at``／``available_at`` 欄位；既有正式
    assembler 的 source contract 將每日收盤固定在台北 14:30。這個推導
    只把該時間視為可得上界，並不把資料庫的日期欄誤當成全天可得。
    """

    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            """
            SELECT 日期, COALESCE(收盤指數, 收盤價)
            FROM market_indices
            WHERE 指數名稱 = ?
              AND COALESCE(收盤指數, 收盤價) IS NOT NULL
            ORDER BY 日期 ASC
            """,
            ("TAIEX",),
        ).fetchall()
    finally:
        connection.close()
    observations: list[_MarketCloseObservation] = []
    seen_dates: set[str] = set()
    for raw_date, raw_close in rows:
        if raw_date is None or raw_close is None:
            continue
        event_date = _canonical_market_date(raw_date)
        if event_date in seen_dates:
            raise ValueError("duplicate TAIEX close observation: " + event_date)
        try:
            close = Decimal(str(raw_close))
        except Exception as exc:  # noqa: BLE001 - source value is untrusted
            raise ValueError("TAIEX close is not Decimal-compatible") from exc
        if not close.is_finite() or close <= 0:
            raise ValueError("TAIEX close must be finite and positive")
        timestamp = f"{event_date}T{MARKET_EVENT_TIME.isoformat()}+08:00"
        observations.append(
            _MarketCloseObservation(
                event_date=event_date,
                event_at=timestamp,
                available_at=timestamp,
                close=close,
            )
        )
        seen_dates.add(event_date)
    observations.sort(key=lambda item: item.event_date)
    return _MarketCloseSeries(
        observations=tuple(observations),
        source_path=str(path.resolve()),
    )


def _fold_refs(
    store: _NumericStore,
    fold_id: str,
    split: str,
) -> np.memmap:
    for fold in store.folds:
        if fold.get("fold_id") == fold_id:
            return store.open_fold_refs(fold, split)
    raise ValueError(f"fold is unavailable: {fold_id}")


def _fold_scope(store: _NumericStore, fold_id: str) -> dict[str, Any]:
    for fold in store.folds:
        if fold.get("fold_id") != fold_id:
            continue
        return {
            "fold_id": fold_id,
            "manifest_hash": fold.get("manifest_hash"),
            "train_end_date": fold.get("train_end_date"),
            "test_start": fold.get("test_start"),
            "test_end": fold.get("test_end"),
            "purge_trading_days": fold.get("purge_trading_days"),
            "embargo_trading_days": fold.get("embargo_trading_days"),
            "train_row_count": fold.get("train", {}).get("row_count"),
            "test_row_count": fold.get("test", {}).get("row_count"),
        }
    raise ValueError(f"fold is unavailable: {fold_id}")


def _sample_refs(refs: np.ndarray | np.memmap, maximum: int) -> np.ndarray:
    if len(refs) <= maximum:
        return np.asarray(refs, dtype=np.int64).copy()
    indexes = np.linspace(
        0,
        len(refs) - 1,
        num=maximum,
        dtype=np.int64,
    )
    return np.asarray(refs[indexes], dtype=np.int64)


def _select_projection_refs(
    store: _NumericStore,
    refs: np.ndarray | np.memmap,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[np.ndarray, dict[str, Any]]:
    """只選取 parent DQ 狀態可逐列證明的 projection refs。

    Direct numeric store 只保存 family aggregate 的 stale／quality-blocked
    計數，不能把非零 aggregate 還原成每個 feature 的狀態。這條 bounded
    路徑因此明確排除非零或未知狀態列，並把排除分母寫入 training evidence；
    不把它們誤標成 observed，也不把原狀態清成零。
    """

    ref_array = np.asarray(refs, dtype=np.int64)
    if ref_array.ndim != 2 or ref_array.shape[1] != 2:
        raise ValueError("projection refs must have shape (n, 2)")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        raise TypeError("projection batch_size must be integer")
    if batch_size <= 0:
        raise ValueError("projection batch_size must be positive")
    families = (
        "market_sector_cross_section",
        "price_liquidity_technical",
    )
    feature_ids = tuple(
        feature_id
        for family_id in families
        for feature_id in (
            f"data_quality.{family_id}.quality_blocked_count",
            f"data_quality.{family_id}.stale_count",
        )
    )
    try:
        positions = tuple(store.feature_positions[item] for item in feature_ids)
    except KeyError as exc:
        raise ValueError("parent store is missing projection DQ fields") from exc
    keep = np.ones(len(ref_array), dtype=bool)
    family_reports: dict[str, dict[str, int]] = {}
    for family_index, family_id in enumerate(families):
        family_reports[family_id] = {
            "total_rows": len(ref_array),
            "eligible_rows": 0,
            "excluded_rows": 0,
            "excluded_unknown_status_rows": 0,
            "excluded_quality_blocked_rows": 0,
            "excluded_stale_rows": 0,
        }
        blocked_position = family_index * 2
        stale_position = blocked_position + 1
        family_keep = np.ones(len(ref_array), dtype=bool)
        family_unknown = np.zeros(len(ref_array), dtype=bool)
        family_blocked = np.zeros(len(ref_array), dtype=bool)
        family_stale = np.zeros(len(ref_array), dtype=bool)
        for start in range(0, len(ref_array), batch_size):
            stop = min(len(ref_array), start + batch_size)
            chunk = store.read_feature_batch(
                ref_array[start:stop],
                (positions[blocked_position], positions[stale_position]),
            )
            blocked = chunk[:, 0]
            stale = chunk[:, 1]
            invalid_blocked = (
                ~np.isfinite(blocked)
                | (blocked < 0)
                | (blocked != np.floor(blocked))
            )
            invalid_stale = (
                ~np.isfinite(stale)
                | (stale < 0)
                | (stale != np.floor(stale))
            )
            unknown = invalid_blocked | invalid_stale
            blocked_rows = ~invalid_blocked & (blocked > 0)
            stale_rows = ~invalid_stale & (stale > 0)
            family_unknown[start:stop] = unknown
            family_blocked[start:stop] = blocked_rows
            family_stale[start:stop] = stale_rows
            family_keep[start:stop] = ~(unknown | blocked_rows | stale_rows)
        family_reports[family_id]["eligible_rows"] = int(family_keep.sum())
        family_reports[family_id]["excluded_rows"] = int((~family_keep).sum())
        family_reports[family_id]["excluded_unknown_status_rows"] = int(
            family_unknown.sum()
        )
        family_reports[family_id]["excluded_quality_blocked_rows"] = int(
            family_blocked.sum()
        )
        family_reports[family_id]["excluded_stale_rows"] = int(
            family_stale.sum()
        )
        keep &= family_keep
    selected = ref_array[keep].copy()
    if not len(selected):
        raise ValueError("parent DQ projection leaves no eligible rows")
    return selected, {
        "policy": "exclude_parent_dq_nonzero_or_unknown_status",
        "total_rows": len(ref_array),
        "eligible_rows": len(selected),
        "excluded_rows": int((~keep).sum()),
        "family": family_reports,
    }


def _ref_metadata(
    store: _NumericStore,
    refs: np.ndarray | np.memmap,
) -> tuple[list[str], list[str], list[str]]:
    """以 rows.sqlite 的完整 decision_at 建立 bounded ref metadata。"""

    ref_array = np.asarray(refs, dtype=np.int64)
    metadata: list[tuple[str, str, str] | None] = [None] * len(ref_array)
    for year in store.years:
        positions = np.flatnonzero(ref_array[:, 0] == year.ordinal)
        if not len(positions):
            continue
        local_to_position = {
            int(ref_array[position, 1]): int(position) for position in positions
        }
        connection = sqlite3.connect(
            f"file:{(year.directory / 'rows.sqlite').as_posix()}?mode=ro",
            uri=True,
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            local_indexes = tuple(local_to_position)
            for start in range(0, len(local_indexes), 500):
                batch = local_indexes[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                cursor = connection.execute(
                    "SELECT local_row_index, decision_at, row_id FROM rows "
                    f"WHERE local_row_index IN ({placeholders}) "
                    "ORDER BY local_row_index",
                    batch,
                )
                for local_row_index, decision_at, row_id in cursor:
                    position = local_to_position.pop(int(local_row_index), None)
                    if position is None:
                        raise ValueError("rows.sqlite returned an unexpected ref")
                    decision_text = str(decision_at)
                    _parse_aware_datetime(
                        decision_text,
                        field_name="rows.decision_at",
                    )
                    row_text = str(row_id)
                    metadata[position] = (
                        decision_text,
                        row_text.rsplit(":", 1)[-1],
                        row_text,
                    )
        finally:
            connection.close()
        if local_to_position:
            raise ValueError("row refs are not present in rows custody")
    if any(item is None for item in metadata):
        raise ValueError("row metadata length mismatch")
    complete = [item for item in metadata if item is not None]
    return (
        [item[0] for item in complete],
        [item[1] for item in complete],
        [item[2] for item in complete],
    )


def _ref_decision_ats(
    store: _NumericStore,
    refs: np.ndarray | np.memmap,
) -> list[str]:
    return _ref_metadata(store, refs)[0]


def _ref_dates(store: _NumericStore, refs: np.ndarray | np.memmap) -> list[str]:
    return [
        _parse_aware_datetime(value, field_name="decision_at").date().isoformat()
        for value in _ref_decision_ats(store, refs)
    ]


def _validate_horizon_label_maturity(
    store: _NumericStore,
    refs: np.ndarray | np.memmap,
    decision_ats: Sequence[str],
) -> dict[str, Any]:
    """確認 frozen h5 label 的最大可得時間晚於每列決策時間。"""

    ref_array = np.asarray(refs, dtype=np.int64)
    if len(ref_array) != len(decision_ats):
        raise ValueError("label maturity metadata length mismatch")
    decision_times = [
        _parse_aware_datetime(value, field_name="decision_at")
        for value in decision_ats
    ]
    checked = 0
    min_available: datetime | None = None
    max_available: datetime | None = None
    for year in store.years:
        positions = np.flatnonzero(ref_array[:, 0] == year.ordinal)
        if not len(positions):
            continue
        local_to_position = {
            int(ref_array[position, 1]): int(position) for position in positions
        }
        connection = sqlite3.connect(
            f"file:{(year.directory / 'rows.sqlite').as_posix()}?mode=ro",
            uri=True,
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            local_indexes = tuple(local_to_position)
            for start in range(0, len(local_indexes), 500):
                batch = local_indexes[start : start + 500]
                placeholders = ",".join("?" for _ in batch)
                cursor = connection.execute(
                    "SELECT local_row_index, max_label_available_at FROM rows "
                    f"WHERE local_row_index IN ({placeholders})",
                    batch,
                )
                for local_row_index, max_label_available_at in cursor:
                    position = local_to_position.pop(int(local_row_index), None)
                    if position is None:
                        raise ValueError("rows.sqlite returned an unexpected label ref")
                    available = _parse_aware_datetime(
                        str(max_label_available_at),
                        field_name="max_label_available_at",
                    )
                    if available <= decision_times[position]:
                        raise ValueError(
                            "h5 label is available at or before decision_at: "
                            + str(local_row_index)
                        )
                    checked += 1
                    min_available = (
                        available
                        if min_available is None
                        else min(min_available, available)
                    )
                    max_available = (
                        available
                        if max_available is None
                        else max(max_available, available)
                    )
        finally:
            connection.close()
        if local_to_position:
            raise ValueError("label refs are not present in rows custody")
    if checked != len(ref_array):
        raise ValueError("h5 label maturity stream did not cover every ref")
    return {
        "row_count": checked,
        "all_available_after_decision": True,
        "min_label_available_at": (
            None if min_available is None else min_available.isoformat()
        ),
        "max_label_available_at": (
            None if max_available is None else max_available.isoformat()
        ),
    }


def _project_matrix(
    store: _NumericStore,
    refs: np.ndarray | np.memmap,
    decision_ats: Sequence[str],
    feature_order: Sequence[str],
    market: _MarketCloseSeries,
    *,
    batch_size: int,
) -> NDArray[np.float32]:
    if len(refs) != len(decision_ats):
        raise ValueError("project refs and decision timestamps length mismatch")
    positions = tuple(store.feature_positions[feature_id] for feature_id in feature_order)
    result = np.empty((len(refs), len(feature_order)), dtype=np.float32)
    local_positions = {feature_id: index for index, feature_id in enumerate(feature_order)}
    family_positions: dict[str, list[int]] = {}
    for index, feature_id in enumerate(feature_order):
        family = _feature_family(store, feature_id)
        family_positions.setdefault(family, []).append(index)
    dq_positions = {
        feature_id: local_positions[feature_id]
        for feature_id in feature_order
        if feature_id.startswith("data_quality.")
    }
    market_base_positions = family_positions["market_sector_cross_section"]
    price_base_positions = family_positions["price_liquidity_technical"]
    market_base_positions = [
        index
        for index in market_base_positions
        if feature_order[index] not in _DERIVED_MARKET_FEATURES
    ]
    for start in range(0, len(refs), batch_size):
        stop = min(len(refs), start + batch_size)
        chunk_refs = np.asarray(refs[start:stop], dtype=np.int64)
        chunk = store.read_feature_batch(chunk_refs, positions)
        for feature_id in _DERIVED_MARKET_FEATURES:
            index = local_positions[feature_id]
            for offset, decision_at in enumerate(decision_ats[start:stop]):
                pair = market.pair_for_decision(decision_at)
                if pair is None:
                    chunk[offset, index] = np.nan
                    continue
                current, previous = pair
                current_decimal = current.close
                previous_decimal = previous.close
                if feature_id.endswith("漲跌點數"):
                    value = current_decimal - previous_decimal
                else:
                    value = (
                        (current_decimal - previous_decimal)
                        / previous_decimal
                        * Decimal("100")
                    )
                quantized = value.quantize(
                    Decimal("0.0001"),
                    rounding=ROUND_HALF_EVEN,
                )
                chunk[offset, index] = float(quantized)  # numeric-boundary: model fitting
        _recompute_dq_values(
            chunk=chunk,
            feature_order=feature_order,
            dq_positions=dq_positions,
            market_base_positions=market_base_positions,
            price_base_positions=price_base_positions,
            parent_dq_positions={
                feature_id: local_positions[feature_id]
                for feature_id in feature_order
                if feature_id.startswith("data_quality.")
            },
        )
        result[start:stop] = chunk
    return result


def _recompute_dq_values(
    *,
    chunk: NDArray[np.float32],
    feature_order: Sequence[str],
    dq_positions: Mapping[str, int],
    market_base_positions: Sequence[int],
    price_base_positions: Sequence[int],
    parent_dq_positions: Mapping[str, int],
) -> None:
    # parent DQ 的 stale／quality_blocked 分類沒有在數值 store 另存 revision；
    # 呼叫端已先排除非零／未知列。這裡仍保留原 aggregate，避免把不可證明
    # 的狀態誤寫成零；若有繞過選擇器的列則直接 fail closed。
    for family_id, positions in (
        ("market_sector_cross_section", market_base_positions),
        ("price_liquidity_technical", price_base_positions),
    ):
        observed = np.sum(np.isfinite(chunk[:, positions]), axis=1)
        total = len(positions)
        old_prefix = f"data_quality.{family_id}."
        old_blocked = chunk[:, parent_dq_positions[old_prefix + "quality_blocked_count"]]
        old_stale = chunk[:, parent_dq_positions[old_prefix + "stale_count"]]
        for name, values in (
            ("quality_blocked_count", old_blocked),
            ("stale_count", old_stale),
        ):
            if np.any(
                ~np.isfinite(values)
                | (values < 0)
                | (values != np.floor(values))
            ):
                raise ValueError(
                    "v3 DQ projection encountered unknown parent " + name
                )
        if np.any(old_blocked != 0) or np.any(old_stale != 0):
            raise ValueError(
                "v3 DQ projection received an excluded parent DQ row"
            )
        metric_values = {
            "coverage_bp": (observed * 10_000 // total).astype(np.float32),
            "missing_count": (total - observed).astype(np.float32),
            "quality_blocked_count": old_blocked.astype(np.float32),
            "stale_count": old_stale.astype(np.float32),
        }
        old_lag = chunk[:, parent_dq_positions[old_prefix + "max_available_lag_days"]]
        metric_values["max_available_lag_days"] = np.nan_to_num(
            old_lag,
            nan=0.0,
        ).astype(np.float32)
        for metric, values in metric_values.items():
            chunk[:, dq_positions[old_prefix + metric]] = values


def _feature_family(store: _NumericStore, feature_id: str) -> str:
    for pack in store.feature_packs:
        if feature_id in pack["feature_ids"]:
            return str(pack["pack_id"])
    raise ValueError(f"feature family is unavailable: {feature_id}")


def _fit_base_models(
    matrix: NDArray[np.float32],
    labels: NDArray[np.int32],
    label_masks: NDArray[np.uint8],
    *,
    packs: Sequence[tuple[str, tuple[str, ...]]],
    feature_order: Sequence[str],
    fit_row_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    positions = {feature_id: index for index, feature_id in enumerate(feature_order)}
    for pack_id, feature_ids in packs:
        pack_matrix = matrix[:, [positions[item] for item in feature_ids]]
        pack_models: dict[str, Any] = {}
        missing: dict[str, str] = {}
        head_fit_rows: dict[str, list[str]] = {}
        for head_id in REGRESSION_EXPERT_HEADS:
            label_position = _REGRESSION_LABEL_POSITIONS[head_id]
            valid = label_masks[:, label_position] == 0
            if not np.any(valid):
                if head_id != "expected_sector_excess_return_bp":
                    raise ValueError(f"v3 required label is missing: {head_id}")
                pack_models[head_id] = None
                missing[head_id] = "pit_sector_benchmark_labels_unavailable"
                head_fit_rows[head_id] = []
                continue
            regression_model = _linear_regression_model(
                pack_matrix[valid],
                labels[valid, label_position],
            )
            pack_models[head_id] = regression_model
            head_fit_rows[head_id] = [
                fit_row_ids[index] for index in np.flatnonzero(valid)
            ]
        for head_id in CLASSIFICATION_EXPERT_HEADS:
            label_position = _CLASSIFICATION_LABEL_POSITIONS[head_id]
            valid = label_masks[:, label_position] == 0
            if int(np.sum(valid)) < 2:
                raise ValueError(f"v3 required classification label is missing: {head_id}")
            target = np.asarray(labels[valid, label_position], dtype=np.int32)
            if len(np.unique(target)) == 1:
                classifier_model: Any = _ConstantProbabilityModel(int(target[0]))
            else:
                classifier_model = _linear_classification_model(
                    pack_matrix[valid], target
                )
            pack_models[head_id] = classifier_model
            head_fit_rows[head_id] = [
                fit_row_ids[index] for index in np.flatnonzero(valid)
            ]
        result[pack_id] = {
            "models": pack_models,
            "fit_row_ids": head_fit_rows,
            "missing": missing,
            "feature_ids": feature_ids,
        }
    return result


def _linear_regression_model(
    matrix: NDArray[np.float32],
    target: NDArray[np.int32],
) -> Pipeline:
    model = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=100.0)),
        ]
    )
    model.fit(matrix, np.asarray(target, dtype=np.float64))
    return model


def _linear_classification_model(
    matrix: NDArray[np.float32],
    target: NDArray[np.int32],
) -> Pipeline:
    model = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=100, random_state=17)),
        ]
    )
    model.fit(matrix, target)
    return model


class _ConstantProbabilityModel:
    """可序列化且明確標記 classifier 的單一 class fallback。"""

    classifier = True

    def __init__(self, probability_class: int) -> None:
        if probability_class not in {0, 1}:
            raise ValueError("probability class must be 0 or 1")
        self.probability_class = probability_class

    def predict_proba(self, matrix: NDArray[Any]) -> NDArray[np.float64]:
        count = len(matrix)
        result = np.zeros((count, 2), dtype=np.float64)
        result[:, self.probability_class] = 1.0
        return result


def _quantize_probability(values: NDArray[Any]) -> np.ndarray:
    result = np.empty(len(values), dtype=np.int64)
    for index, value in enumerate(values):
        bounded = max(Decimal("0"), min(Decimal("1"), Decimal(str(float(value)))))
        result[index] = int(
            (bounded * Decimal("10000")).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_EVEN,
            )
        )
    return result


def _fit_calibrator(
    *,
    models: Mapping[str, Mapping[str, Any]],
    calibration_matrices: Mapping[str, NDArray[np.float32]],
    calibration_ref_sets: Mapping[str, np.ndarray | np.memmap],
    store: "_CalibrationLabelReader",
    calibration_metadata: Mapping[str, tuple[list[str], list[str], list[str]]],
    fit_metadata: tuple[list[str], list[str], list[str]],
    packs: Sequence[tuple[str, tuple[str, ...]]],
    feature_order: Sequence[str],
) -> tuple[tuple[int, ...], dict[str, Any]]:
    _validate_calibration_separation(
        fit_metadata=fit_metadata,
        calibration_metadata=calibration_metadata,
    )
    counts = np.zeros(10_001, dtype=np.int64)
    positive = np.zeros(10_001, dtype=np.int64)
    per_fold_counts: dict[str, int] = {}
    for fold_id in CALIBRATION_FOLD_IDS:
        refs = calibration_ref_sets[fold_id]
        labels, masks = store.read_label_batch(np.asarray(refs, dtype=np.int64), HORIZON)
        valid = (masks[:, 2] == 0) & ((labels[:, 2] == 0) | (labels[:, 2] == 1))
        fold_observation_count = 0
        for pack_id, feature_ids in packs:
            matrix = calibration_matrices[fold_id][:, [feature_order.index(item) for item in feature_ids]]
            model = models[pack_id]["models"]["downside_probability_bp"]
            raw = _predict_probability(model, matrix)
            raw_bp = _quantize_probability(raw)
            selected = raw_bp[valid]
            observed = labels[valid, 2].astype(np.int64)
            if len(selected):
                np.add.at(counts, selected, 1)
                np.add.at(positive, selected, observed)
                fold_observation_count += len(selected)
        per_fold_counts[fold_id] = fold_observation_count
    if int(np.sum(counts)) == 0 or int(np.sum(positive)) == 0 or int(np.sum(counts - positive)) == 0:
        raise ValueError("v3 calibrator requires both downside label classes")
    mapping = _fit_isotonic_mapping_bp(counts, positive)
    evidence_seed = {
        "schema_version": "allocation-v3-linear-calibration-evidence.v1",
        "source": f"new_v3_base_models_on_{FIT_FOLD_ID}_train",
        "fit_fold_ids": list(CALIBRATION_FOLD_IDS),
        "fit_observation_count_by_fold": per_fold_counts,
        "fit_row_count_by_fold": {
            fold_id: int(len(calibration_ref_sets[fold_id]))
            for fold_id in CALIBRATION_FOLD_IDS
        },
        "positive_row_count": int(np.sum(positive)),
        "negative_row_count": int(np.sum(counts - positive)),
        "shared_mapping_across_feature_packs": True,
        "feature_pack_ids": [pack_id for pack_id, _ in packs],
        "horizon": HORIZON,
        "feature_order_hash": feature_order_hash(feature_order),
        "rank_contract": DEFAULT_RANK_CONTRACT,
    }
    evidence = {
        **evidence_seed,
        "calibration_id": "v3-isotonic-" + payload_hash(evidence_seed)[7:23],
        "mapping_hash": payload_hash([int(item) for item in mapping]),
        "diagnostic_only": False,
        "oof_diagnostic_only": False,
        "target_fold_self_excluded": True,
        "base_fit_fold_id": FIT_FOLD_ID,
        "meta_training_labels_not_used": True,
        "base_fit_row_ids_hash": payload_hash(list(fit_metadata[2])),
        "calibration_row_ids_hash_by_fold": {
            fold_id: payload_hash(list(calibration_metadata[fold_id][2]))
            for fold_id in CALIBRATION_FOLD_IDS
        },
        "fit_decision_at_range": _decision_at_range(fit_metadata[0]),
        "calibration_decision_at_range_by_fold": {
            fold_id: _decision_at_range(calibration_metadata[fold_id][0])
            for fold_id in CALIBRATION_FOLD_IDS
        },
    }
    return tuple(int(item) for item in mapping), evidence


def _decision_at_range(values: Sequence[str]) -> dict[str, str | None]:
    if not values:
        return {"min": None, "max": None}
    parsed = sorted(
        _parse_aware_datetime(value, field_name="decision_at") for value in values
    )
    return {"min": parsed[0].isoformat(), "max": parsed[-1].isoformat()}


def _validate_calibration_separation(
    *,
    fit_metadata: tuple[list[str], list[str], list[str]],
    calibration_metadata: Mapping[str, tuple[list[str], list[str], list[str]]],
) -> None:
    """以實際 row identity 與 timestamp 驗證 base/calibration 分離。"""

    fit_decision_ats, _fit_symbols, fit_row_ids = fit_metadata
    if len(fit_decision_ats) != len(fit_row_ids) or not fit_row_ids:
        raise ValueError("calibration base fit metadata is incomplete")
    fit_ids = set(fit_row_ids)
    fit_times = sorted(
        _parse_aware_datetime(value, field_name="fit decision_at")
        for value in fit_decision_ats
    )
    previous_fold_max: datetime | None = None
    calibration_ids: set[str] = set()
    for fold_id in CALIBRATION_FOLD_IDS:
        metadata = calibration_metadata.get(fold_id)
        if metadata is None:
            raise ValueError("calibration metadata is missing: " + fold_id)
        decision_ats, _symbols, row_ids = metadata
        if len(decision_ats) != len(row_ids) or not row_ids:
            raise ValueError("calibration metadata is incomplete: " + fold_id)
        overlap = fit_ids.intersection(row_ids)
        if overlap:
            raise ValueError(
                "calibration rows overlap base fit rows: " + fold_id
            )
        cross_fold_overlap = calibration_ids.intersection(row_ids)
        if cross_fold_overlap:
            raise ValueError(
                "calibration folds share row identities: " + fold_id
            )
        calibration_ids.update(row_ids)
        fold_times = sorted(
            _parse_aware_datetime(value, field_name=f"{fold_id} decision_at")
            for value in decision_ats
        )
        if fold_times[0] <= fit_times[-1]:
            raise ValueError(
                "calibration decision_at is not after base fit scope: " + fold_id
            )
        if previous_fold_max is not None and fold_times[0] <= previous_fold_max:
            raise ValueError(
                "calibration folds are not strictly time ordered: " + fold_id
            )
        previous_fold_max = fold_times[-1]


class _CalibrationLabelReader(Protocol):
    """Calibration only requires the immutable store label read contract."""

    def read_label_batch(
        self,
        refs: NDArray[np.integer[Any]],
        horizon: int,
    ) -> tuple[NDArray[np.int32], NDArray[np.uint8]]: ...


def _predict_probability(model: Any, matrix: NDArray[np.float32]) -> NDArray[np.float64]:
    values = np.asarray(model.predict_proba(matrix)[:, 1], dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise ValueError("v3 probability prediction is invalid")
    return values


def _build_neutral_meta_models(
    *,
    targets: NDArray[np.int32],
    meta_row_ids: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """建立 adapter 所需的 neutral Meta，拒絕把常數 target 當成學習成果。"""

    if targets.ndim != 2 or targets.shape[1] != len(TARGET_FIELDS):
        raise ValueError("v3 Meta targets do not match the frozen target schema")
    if len(targets) == 0 or len(meta_row_ids) != len(targets):
        raise ValueError("v3 Meta target rows are unavailable")
    unique_counts = [
        int(len(np.unique(targets[:, index])))
        for index in range(targets.shape[1])
    ]
    all_constant = all(count == 1 for count in unique_counts)
    if not all_constant:
        raise ValueError(
            "v3 bounded release requires an identified Meta target source; "
            "retrain only after a non-constant Direct target contract exists"
        )
    constants = [int(targets[0, index]) for index in range(targets.shape[1])]
    meta: dict[str, Any] = {
        "numeric": {
            field_name: _ConstantRegressionModel(constants[index])
            for index, field_name in enumerate(_META_FIELDS)
        },
        "rebalance": _ConstantProbabilityModel(constants[5]),
        "fit_row_ids": list(meta_row_ids),
    }
    summary_fields = tuple(TARGET_FIELDS)
    target_summary: dict[str, Any] = {
        "schema_version": "allocation-v3-target-summary.v1",
        "row_count": len(targets),
        "source_row_ids_hash": payload_hash(list(meta_row_ids)),
        "all_meta_targets_constant": True,
        "training_skipped": True,
        "status": "degenerate_constant_targets_adapter_neutral",
        "ranges": {
            field_name: {
                "min": constants[index],
                "max": constants[index],
                "unique_count": unique_counts[index],
            }
            for index, field_name in enumerate(summary_fields)
        },
    }
    return meta, target_summary


class _ConstantRegressionModel:
    """只供 schema-compatible neutral Meta；不代表已識別的配置器。"""

    classifier = False

    def __init__(self, value: int) -> None:
        self.value = int(value)

    def predict(self, matrix: NDArray[Any]) -> NDArray[np.float64]:
        return np.full(len(matrix), self.value, dtype=np.float64)


def _artifact_payload(
    *,
    models: Mapping[str, Mapping[str, Any]],
    meta_models: Mapping[str, Any],
    packs: Sequence[tuple[str, tuple[str, ...]]],
    feature_order: Sequence[str],
    dataset_id: str,
    dataset_identity_hash: str,
    dataset_manifest_file_hash: str,
    feature_registry_hash: str,
    source_manifest_hashes: Sequence[tuple[str, str]],
    training_as_of: str,
    fit_row_ids: Sequence[str],
    training_profile: str,
    target_summary: Mapping[str, Any],
) -> dict[str, Any]:
    expert_keys = [f"{pack_id}|h{HORIZON}|ridge_logistic" for pack_id, _ in packs]
    base_models: dict[str, Any] = {}
    for expert_key, (pack_id, _feature_ids) in zip(expert_keys, packs):
        entry = models[pack_id]
        base_models[expert_key] = {
            "regression_models": {
                head_id: entry["models"][head_id]
                for head_id in REGRESSION_EXPERT_HEADS
            },
            "classification_models": {
                head_id: entry["models"][head_id]
                for head_id in CLASSIFICATION_EXPERT_HEADS
            },
            "preprocessing_strategy": "v3_contract_pipeline",
            "head_fit_row_ids": {
                head_id: list(entry["fit_row_ids"][head_id])
                for head_id in EXPERT_HEAD_IDS
            },
            "head_missing_reasons": dict(entry["missing"]),
            "fit_row_ids": list(fit_row_ids),
        }
    return {
        "artifact_schema_version": "allocation-model-artifact-v3",
        "dataset_id": dataset_id,
        "dataset_identity_hash": dataset_identity_hash,
        "dataset_manifest_file_hash": dataset_manifest_file_hash,
        "feature_registry_hash": feature_registry_hash,
        "source_manifest_hashes": [list(item) for item in source_manifest_hashes],
        "training_as_of": training_as_of,
        "feature_packs": [[pack_id, list(ids)] for pack_id, ids in packs],
        "horizons": [HORIZON],
        "expert_keys": expert_keys,
        "expert_head_ids": list(EXPERT_HEAD_IDS),
        "expert_vector_width": len(EXPERT_HEAD_IDS) * 2 + 1,
        "base_models": base_models,
        "meta_models": {
            "numeric": dict(meta_models["numeric"]),
            "rebalance": meta_models["rebalance"],
            "fit_row_ids": list(meta_models["fit_row_ids"]),
        },
        # The v3 target source is degenerate; coverage uses a separately
        # versioned deterministic equal-family policy, with the remainder
        # assigned to the last canonical pack so the integer sum is exact.
        "feature_family_weights_bp": [
            [
                pack_id,
                (10_000 // len(packs))
                + (1 if index == len(packs) - 1 else 0),
            ]
            for index, (pack_id, _feature_ids) in enumerate(packs)
        ],
        "production_alpha_bp": 0,
        "production_action_allowed": False,
        "formal_oos_allowed": False,
        "broker_order_allowed": False,
        "meta_probability_input": "calibrated",
        "training_profile": training_profile,
        "complexity_policy": {
            "algorithm_count": 1,
            "horizon_count": 1,
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
        },
        "rank_contract": DEFAULT_RANK_CONTRACT,
        "family_weight_policy": FAMILY_WEIGHT_POLICY_DEGENERATE_EQUAL_V1,
        "feature_family_weights_status": (
            FAMILY_WEIGHT_STATUS_DEGENERATE_UNIDENTIFIED_EQUAL
        ),
        "target_summary": dict(target_summary),
    }


def _preprocessor_binding(
    *,
    model_id: str,
    order_hash: str,
    training_hash: str,
) -> tuple[PreprocessorBinding, bytes]:
    preprocessor_id = "v3-preprocessor-" + payload_hash(
        {"model_id": model_id, "order_hash": order_hash, "training_hash": training_hash}
    )[7:23]
    body = {
        "schema_version": "allocation-ml-preprocessor.v1",
        "preprocessor_id": preprocessor_id,
        "strategy": "v3_contract_pipeline",
        "feature_order_hash": order_hash,
        "artifact_file": "preprocessor.json",
        "attached_to_model": True,
    }
    content = (canonical_json(body) + "\n").encode("utf-8")
    return (
        PreprocessorBinding(
            preprocessor_id=preprocessor_id,
            strategy="v3_contract_pipeline",
            feature_order_hash=order_hash,
            artifact_file="preprocessor.json",
            artifact_hash=bytes_hash(content),
        ),
        content,
    )


def _training_as_of(store: _NumericStore) -> str:
    value = store.manifest.get("training_as_of")
    if not isinstance(value, str) or not value:
        raise ValueError("parent training_as_of is missing")
    return value


def _release_run_root(output_root: Path, release_id: str) -> Path:
    return output_root.resolve() / "runs" / release_id


def _publish_release(
    *,
    release_root: Path,
    output_root: Path,
    release: AllocationReleaseManifest,
    artifact_bytes: bytes,
    preprocessor_bytes: bytes,
    calibrator_bytes: bytes,
    training_bytes: bytes,
    baseline_bytes: int,
    failure_inject_stage: str | None = None,
) -> dict[str, Any]:
    """以 staging directory 與 atomic pointer 發布 immutable release。"""

    output_root.mkdir(parents=True, exist_ok=True)
    if release_root.exists():
        existing = release_root / "release_manifest.json"
        if not existing.is_file():
            raise FileExistsError("v3 release run root is incomplete")
        loaded = load_allocation_release(release_root)
        if loaded.manifest.release_identity_hash != release.release_identity_hash:
            raise ValueError("existing v3 release identity differs")
        latest_content = _latest_manifest_content(release_root, release)
        if failure_inject_stage == "pointer":
            raise RuntimeError("injected publish failure before pointer replace")
        pointer_path = output_root / "latest_manifest.json"
        pointer_existing_bytes = (
            pointer_path.stat().st_size if pointer_path.is_file() else 0
        )
        projected = (
            directory_size_bytes(output_root)
            - baseline_bytes
            + max(0, len(latest_content) - pointer_existing_bytes)
        )
        if projected > PERSISTENT_BUDGET_BYTES:
            raise StorageCapacityError(
                "v3 release persistent byte budget exceeded",
                preflight={
                    "stage": "v3_linear_publish",
                    "file": "latest_manifest.json",
                    "baseline_bytes": baseline_bytes,
                    "projected_new_bytes": projected,
                    "budget_bytes": PERSISTENT_BUDGET_BYTES,
                },
            )
        _atomic_replace_bytes(pointer_path, latest_content)
        return {
            "status": "existing_release_reused",
            "bytes": len(latest_content),
            "staged_readback_verified": True,
            "final_readback_verified": True,
            "latest_pointer_atomic": True,
            "latest_pointer_repaired": True,
        }
    release_root.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "model.joblib": artifact_bytes,
        "preprocessor.json": preprocessor_bytes,
        "calibrator.json": calibrator_bytes,
        "training_manifest.json": training_bytes,
        "release_manifest.json": (canonical_json(release.to_dict()) + "\n").encode("utf-8"),
    }
    staging_root = Path(
        tempfile.mkdtemp(prefix=".v3-release-staging-", dir=output_root)
    )
    written = sum(len(content) for content in files.values())

    def projected_new_bytes(extra_bytes: int = 0) -> int:
        staging_bytes = directory_size_bytes(staging_root)
        output_without_staging = directory_size_bytes(output_root) - staging_bytes
        return output_without_staging - baseline_bytes + staging_bytes + extra_bytes

    def enforce_persistent_budget(file_name: str, extra_bytes: int = 0) -> None:
        projected = projected_new_bytes(extra_bytes)
        if projected > PERSISTENT_BUDGET_BYTES:
            raise StorageCapacityError(
                "v3 release persistent byte budget exceeded",
                preflight={
                    "stage": "v3_linear_publish",
                    "file": file_name,
                    "baseline_bytes": baseline_bytes,
                    "projected_new_bytes": projected,
                    "budget_bytes": PERSISTENT_BUDGET_BYTES,
                },
            )

    staging_active = True
    try:
        for name, content in files.items():
            enforce_persistent_budget(name, len(content))
            path = staging_root / name
            with path.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        # Read the exact staged bytes before they become discoverable through
        # the pointer.  A corrupt/incomplete model therefore cannot replace a
        # previously valid latest pointer.
        staged_loaded = load_allocation_release(staging_root)
        if staged_loaded.manifest.release_identity_hash != release.release_identity_hash:
            raise ValueError("staged v3 release identity differs")
        if failure_inject_stage == "before_release_replace":
            raise RuntimeError("injected publish failure before release replace")
        if release_root.exists():
            raise FileExistsError("v3 release run root appeared during publish")
        os.replace(staging_root, release_root)
        staging_active = False
        final_loaded = load_allocation_release(release_root)
        if final_loaded.manifest.release_identity_hash != release.release_identity_hash:
            raise ValueError("published v3 release identity differs")
        latest_content = _latest_manifest_content(release_root, release)
        enforce_persistent_budget("latest_manifest.json", len(latest_content))
        if failure_inject_stage == "pointer":
            raise RuntimeError("injected publish failure before pointer replace")
        _atomic_replace_bytes(output_root / "latest_manifest.json", latest_content)
    except Exception:
        if staging_active:
            shutil.rmtree(staging_root, ignore_errors=True)
        raise
    return {
        "status": "release_written",
        "bytes": written + len(latest_content),
        "staged_readback_verified": True,
        "final_readback_verified": True,
        "latest_pointer_atomic": True,
    }


def _latest_manifest_content(
    release_root: Path,
    release: AllocationReleaseManifest,
) -> bytes:
    return (
        canonical_json(
            {
                "schema_version": V3_RELEASE_SCHEMA_VERSION,
                "release_id": release.release_id,
                "release_manifest": str(release_root / "release_manifest.json"),
                "release_identity_hash": release.release_identity_hash,
                "artifact_hash": release.artifact_hash,
            }
        )
        + "\n"
    ).encode("utf-8")


def _atomic_replace_bytes(path: Path, content: bytes) -> None:
    """同一目錄 temp + replace，失敗時保留原檔案。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(raw_path)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _label_stats(
    store: _NumericStore,
    refs: np.ndarray | np.memmap,
    horizon: int,
) -> dict[str, Any]:
    labels, masks = store.read_label_batch(np.asarray(refs, dtype=np.int64), horizon)
    result: dict[str, Any] = {"row_count": len(refs), "fields": {}}
    for index, field_name in enumerate(_LABEL_FIELD_NAMES):
        valid = masks[:, index] == 0
        field: dict[str, Any] = {"valid_count": int(np.sum(valid)), "missing_count": int(np.sum(~valid))}
        if field_name in {"downside_observed", "fill_feasible_observed"}:
            values = labels[valid, index]
            field["class_counts"] = [
                int(np.sum(values == 0)),
                int(np.sum(values == 1)),
            ]
        elif np.any(valid):
            values = labels[valid, index]
            field["min"] = int(np.min(values))
            field["max"] = int(np.max(values))
        result["fields"][field_name] = field
    return result


def _target_stats(
    store: _NumericStore,
    refs: np.ndarray | np.memmap,
) -> dict[str, Any]:
    """以 bounded refs 報告 Meta target 範圍，不把常數誤報為模型訊號。"""

    targets = store.read_target_batch(np.asarray(refs, dtype=np.int64))
    if targets.ndim != 2 or targets.shape[1] != len(TARGET_FIELDS):
        raise ValueError("target columns do not match the frozen target schema")
    return {
        "row_count": len(refs),
        "fields": {
            field_name: {
                "min": int(np.min(targets[:, index])),
                "max": int(np.max(targets[:, index])),
                "unique_count": int(len(np.unique(targets[:, index]))),
                "constant": bool(
                    np.min(targets[:, index]) == np.max(targets[:, index])
                ),
            }
            for index, field_name in enumerate(TARGET_FIELDS)
        },
    }


def _market_coverage(
    decision_ats: Sequence[str],
    market: _MarketCloseSeries,
) -> dict[str, Any]:
    unique_ats = sorted(set(decision_ats))
    unique_dates = sorted(
        {
            _parse_aware_datetime(value, field_name="decision_at")
            .date()
            .isoformat()
            for value in unique_ats
        }
    )
    reasons: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    available_count = 0
    for decision_at in unique_ats:
        pair = market.pair_for_decision(decision_at)
        if pair is None:
            reason = market.pair_reason(decision_at) or "pair_unavailable"
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        available_count += 1
        if len(examples) < 5:
            current, previous = pair
            examples.append(
                {
                    "decision_at": decision_at,
                    "current_event_date": current.event_date,
                    "current_event_at": current.event_at,
                    "current_available_at": current.available_at,
                    "previous_event_date": previous.event_date,
                    "previous_event_at": previous.event_at,
                    "previous_available_at": previous.available_at,
                }
            )
    return {
        "row_count": len(decision_ats),
        "unique_date_count": len(unique_dates),
        "unique_decision_at_count": len(unique_ats),
        "pair_available_date_count": available_count,
        "missing_pair_date_count": len(unique_ats) - available_count,
        "pair_available_decision_at_count": available_count,
        "missing_pair_decision_at_count": len(unique_ats) - available_count,
        "same_day_close_excluded_decision_at_count": reasons.get(
            "same_day_close_unavailable_before_decision", 0
        ),
        "official_continuity_unproven_decision_at_count": reasons.get(
            "official_trading_day_continuity_unproven", 0
        ),
        "unavailable_reason_counts": reasons,
        "pair_examples": examples,
        "first_date": unique_dates[0] if unique_dates else None,
        "last_date": unique_dates[-1] if unique_dates else None,
        "first_decision_at": unique_ats[0] if unique_ats else None,
        "last_decision_at": unique_ats[-1] if unique_ats else None,
    }


def _nearest_existing(path: Path) -> Path:
    current = path.resolve()
    while not current.exists():
        if current.parent == current:
            raise FileNotFoundError(path)
        current = current.parent
    return current


def _default_lock_path(parent_path: Path) -> Path:
    run_root = parent_path.parent.resolve()
    return heavy_chain_lock_path(run_root.parent.parent.parent)


def _resolve_shared_lock_path(
    parent_path: Path,
    requested: Path | None,
) -> Path:
    """只接受由 parent 所屬 release_v4 推導出的唯一共用 lock。"""

    expected = _default_lock_path(parent_path.resolve()).resolve()
    actual = (requested or expected).resolve()
    if actual != expected:
        raise ValueError(
            "v3 release must use the parent release_v4 shared heavy-chain lock"
        )
    return actual


def _joblib_bytes(payload: object) -> bytes:
    from io import BytesIO

    output = BytesIO()
    joblib.dump(payload, output, compress=3)
    return output.getvalue()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _close_memmap(value: object) -> None:
    mmap = getattr(value, "_mmap", None)
    if mmap is not None:
        mmap.close()


__all__ = [
    "CALIBRATION_FOLD_IDS",
    "FIT_FOLD_ID",
    "HORIZON",
    "META_FIT_FOLD_ID",
    "MAX_FIT_SAMPLE_ROWS",
    "DEFAULT_BATCH_SIZE",
    "TEMPORARY_ESTIMATE_BYTES",
    "V3LinearReleaseRequest",
    "build_v3_linear_release",
    "preflight_v3_linear_release",
]
