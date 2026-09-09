"""以唯讀串流方式產出全欄位 ML 的年度 PIT 數值 shards。

此模組刻意不使用 pandas／Parquet，也不把來源 SQLite 全表載入記憶體。
來源連線固定為 ``mode=ro`` 與 ``PRAGMA query_only=ON``；資料列以
``fetchmany`` 分批讀取，再寫成 deterministic gzip JSONL。

年度分割以 ``available_at`` 的台北年度為準，而不是報表期末或事件年度。
因此晚到的公告／修訂只會落在真正可取得的年度。正式資料集只接受
``formal_backfill`` 與 ``first_seen_only``；``research_shadow`` 使用獨立
shard，不會混入正式訓練。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence
import uuid
from zoneinfo import ZoneInfo

from data_module.ml_storage_capacity import (
    heavy_chain_capacity_budget,
    MLStorageCapacityBudget,
    directory_size_bytes,
    preflight_capacity,
)
from data_module.ml_daily_price_source_quality import (
    DailyPriceSourceQualityError,
    assert_daily_price_source_quality,
    write_quarantine_report,
)
from data_module.ml_price_availability_contract import (
    PRICE_AVAILABILITY_CONTRACT_VERSION,
    build_price_unavailable_research_contract,
)
from data_module.statement_report_basis_contract import (
    resolve_statement_report_basis,
)
from ml_module.feature_eligibility import (
    ALL_FIELD_SOURCE_TABLES,
    FeatureEligibilityManifest,
    FeatureEligibilityRecord,
    FeatureEligibilityStatus,
    build_feature_eligibility_manifest,
    table_family,
)


DatasetId = Literal[
    "core_long_history",
    "all_field_enriched",
    "research_shadow_all_fields",
]

_DATASET_IDS: tuple[DatasetId, ...] = (
    "core_long_history",
    "all_field_enriched",
    "research_shadow_all_fields",
)
_CORE_TABLES = frozenset(
    {
        "daily_prices",
        "technical_indicators",
        "market_indices",
        "industry_indices",
    }
)
_FORMAL_STATUSES = frozenset({"formal_backfill", "first_seen_only"})
_SHADOW_STATUSES = frozenset({"research_shadow"})
_TAIPEI = ZoneInfo("Asia/Taipei")
_DECISION_TIME = time(hour=8, minute=30)
_MARKET_CLOSE_TIME = time(hour=14, minute=30)
_END_OF_DAY = time(hour=23, minute=59, second=59, microsecond=999_999)
_BAD_QUALITY_TOKENS = frozenset(
    {
        "blocked",
        "degraded",
        "invalid",
        "missing",
        "quarantined",
        "rejected",
        "unavailable",
    }
)
_REPORT_BASES = frozenset({"consolidated", "individual"})


def _source_quality_is_price_unavailable_only(
    report: Mapping[str, Any],
) -> bool:
    """Allow raw research rows with unavailable prices through the shard stage.

    The source guard remains fail-closed for CSV mismatches, route conflicts,
    and scale discontinuities.  This narrow exception is safe only when the
    guard's complete candidate count is the same as its explicit
    ``price_unavailable`` contract count; a truncated sample can never widen
    that exception.
    """

    try:
        candidate_count = int(report.get("candidate_count", -1))
        unavailable_count = int(
            report.get("research_price_unavailable_count", -1)
        )
        invalid_count = int(report.get("research_price_invalid_count", -1))
    except (TypeError, ValueError):
        return False
    if (
        candidate_count <= 0
        or candidate_count != unavailable_count
        or invalid_count != 0
    ):
        return False
    classifications = report.get("classification_counts")
    if not isinstance(classifications, Mapping):
        return False
    return set(str(key) for key in classifications) <= {
        "sqlite_row_invalid_requires_quarantine"
    }


@dataclass(frozen=True)
class PITYearShardBuildRequest:
    """年度 shard 建置輸入；``symbols=None`` 明確代表全 universe。"""

    database_path: Path
    output_root: Path
    decision_at: str
    history_start_date: str = "2014-01-01"
    symbols: tuple[str, ...] | None = None
    years: tuple[int, ...] = ()
    industry_index_names: tuple[str, ...] = ()
    batch_size: int = 2_048
    compression_level: int = 6
    # Capacity policy additions are optional to preserve the previous
    # positional/API contract.  Both persistent names are accepted as
    # compatibility aliases; the canonical value is the ``persistent_new``
    # budget used by the shared capacity contract.
    temporary_storage_budget_bytes: int | None = None
    persistent_storage_budget_bytes: int | None = None
    persistent_new_bytes_budget: int | None = None
    safety_reserve_bytes: int | None = None
    # Optional source guard.  Production callers may supply the canonical
    # daily CSV root; omitted keeps legacy fixture/API behaviour unchanged.
    daily_price_source_dir: Path | None = None
    # Production callers with both exchanges must pass both roots explicitly;
    # routing is performed per symbol and never by directory order alone.
    daily_price_source_dirs: tuple[Path, ...] | None = None
    source_quality_report_path: Path | None = None
    # 來源 receipt 的實際可得時間；不提供時不得以 mtime 或當前時間代替。
    source_quality_known_at: str | None = None
    # 全歷史 source guard 只保留有限 evidence sample；candidate_count 與
    # classification/date counts 仍計算全量候選。
    source_quality_candidate_sample_limit: int = 64

    def __post_init__(self) -> None:
        if not str(self.decision_at).strip():
            raise ValueError("decision_at is required")
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int):
            raise TypeError("batch_size must be an integer")
        if self.batch_size < 1 or self.batch_size > 100_000:
            raise ValueError("batch_size must be between 1 and 100000")
        if isinstance(self.compression_level, bool) or not isinstance(
            self.compression_level, int
        ):
            raise TypeError("compression_level must be an integer")
        if self.compression_level < 0 or self.compression_level > 9:
            raise ValueError("compression_level must be between 0 and 9")
        if isinstance(self.source_quality_candidate_sample_limit, bool) or not isinstance(
            self.source_quality_candidate_sample_limit, int
        ):
            raise TypeError("source_quality_candidate_sample_limit must be an integer")
        if self.source_quality_candidate_sample_limit < 0:
            raise ValueError("source_quality_candidate_sample_limit must be non-negative")
        if self.symbols is not None:
            normalized = _normalized_texts(self.symbols)
            if not normalized:
                raise ValueError("symbols must be non-empty or None for all universe")
            object.__setattr__(self, "symbols", normalized)
        normalized_years = _normalized_years(self.years)
        object.__setattr__(self, "years", normalized_years)
        object.__setattr__(
            self,
            "industry_index_names",
            _normalized_texts(self.industry_index_names),
        )
        if self.daily_price_source_dirs is not None:
            normalized_source_dirs = tuple(
                Path(value) for value in self.daily_price_source_dirs
            )
            if not normalized_source_dirs:
                raise ValueError(
                    "daily_price_source_dirs must be non-empty when supplied"
                )
            object.__setattr__(
                self,
                "daily_price_source_dirs",
                normalized_source_dirs,
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
        for field_name, value in (
            ("temporary_storage_budget_bytes", self.temporary_storage_budget_bytes),
            ("persistent_storage_budget_bytes", self.persistent_storage_budget_bytes),
            ("persistent_new_bytes_budget", self.persistent_new_bytes_budget),
            ("safety_reserve_bytes", self.safety_reserve_bytes),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be integer or None")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True)
class PITYearShardPublication:
    """已原子 publish 的 shard publication 指標。"""

    publication_id: str
    publication_directory: Path
    manifest_path: Path
    latest_manifest_path: Path
    manifest_hash: str
    dataset_manifest_paths: Mapping[str, Path]
    shard_count: int
    row_count: int
    # 執行期間最後一次容量 checkpoint；這些 telemetry 不進 publication
    # manifest 的 logical hash，只供 orchestration 的 bounded QA 使用。
    capacity_preflight: Mapping[str, Any] = field(default_factory=dict)
    temporary_peak_bytes_observed: int | None = None
    capacity_checkpoint_count: int = 0
    capacity_last_stage: str = ""

    def __post_init__(self) -> None:
        if not self.publication_id.strip():
            raise ValueError("publication_id is required")
        if not self.manifest_hash.startswith("sha256:"):
            raise ValueError("manifest_hash must use sha256")
        for count in (self.shard_count, self.row_count):
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("publication counts must be non-negative integers")
        if self.temporary_peak_bytes_observed is not None and (
            isinstance(self.temporary_peak_bytes_observed, bool)
            or not isinstance(self.temporary_peak_bytes_observed, int)
            or self.temporary_peak_bytes_observed < 0
        ):
            raise ValueError(
                "temporary_peak_bytes_observed must be non-negative integer or None"
            )
        if (
            isinstance(self.capacity_checkpoint_count, bool)
            or not isinstance(self.capacity_checkpoint_count, int)
            or self.capacity_checkpoint_count < 0
        ):
            raise ValueError("capacity_checkpoint_count must be non-negative integer")
        if not isinstance(self.capacity_last_stage, str):
            raise TypeError("capacity_last_stage must be a string")


def _capacity_budget_for_request(
    request: PITYearShardBuildRequest,
) -> MLStorageCapacityBudget:
    persistent_budget = request.persistent_storage_budget_bytes
    if persistent_budget is None:
        persistent_budget = request.persistent_new_bytes_budget
    return heavy_chain_capacity_budget(
        persistent_new_bytes_budget=persistent_budget,
        temporary_peak_bytes_budget=request.temporary_storage_budget_bytes,
        safety_reserve_bytes=request.safety_reserve_bytes,
    )


@dataclass(frozen=True)
class _RuntimeTablePolicy:
    identity_columns: tuple[str, ...]
    stock_column: str | None
    industry_column: str | None = None
    optional_identity_columns: tuple[str, ...] = ()


_RUNTIME_POLICIES: dict[str, _RuntimeTablePolicy] = {
    "daily_prices": _RuntimeTablePolicy(("證券代號",), "證券代號"),
    "technical_indicators": _RuntimeTablePolicy(("證券代號",), "證券代號"),
    "market_indices": _RuntimeTablePolicy(("指數名稱",), None),
    "industry_indices": _RuntimeTablePolicy(("指數名稱",), None, "指數名稱"),
    "fundamental_monthly_revenues": _RuntimeTablePolicy(
        ("stock_code", "period"), "stock_code"
    ),
    "fundamental_statement_items": _RuntimeTablePolicy(
        ("stock_code", "statement_type", "period", "item_code"),
        "stock_code",
        optional_identity_columns=("report_basis",),
    ),
    "fundamental_valuation_metrics": _RuntimeTablePolicy(
        ("stock_code", "metric_name"), "stock_code"
    ),
    "institutional_flows": _RuntimeTablePolicy(("stock_code",), "stock_code"),
    "credit_transactions": _RuntimeTablePolicy(("stock_code",), "stock_code"),
    "tdcc_shareholding": _RuntimeTablePolicy(("stock_code",), "stock_code"),
    "broker_flows": _RuntimeTablePolicy(
        ("證券代號", "分點名稱", "trade_type"), "證券代號"
    ),
}

if frozenset(_RUNTIME_POLICIES) != frozenset(ALL_FIELD_SOURCE_TABLES):
    raise RuntimeError("PIT shard runtime policy does not cover all source tables")

# 兩張行情表的 SQLite PRIMARY KEY 都是 (證券代號, 日期)。在這兩欄
# 之後再把 OHLC 與全部 feature 加入 ORDER BY，不會增加 deterministic
# tie-break 能力，反而會讓五百萬列資料建立數 GB 的 temp B-tree。
_PRIMARY_KEY_STREAM_TABLES = frozenset(
    {"daily_prices", "technical_indicators"}
)


@dataclass(frozen=True)
class _DerivedFeatureValue:
    value_decimal: Decimal | None
    derivation_hash: str
    blocker: str | None
    input_columns: tuple[str, ...]
    period: int = 14


class _CausalWilder14State:
    """單一股票的 Wilder ATR/ADX(14) 因果 prefix state。"""

    _PERIOD = 14

    def __init__(self) -> None:
        self._last_event_date: date | None = None
        self._previous_high: Decimal | None = None
        self._previous_low: Decimal | None = None
        self._previous_close: Decimal | None = None
        self._seed_count = 0
        self._tr_sum = Decimal(0)
        self._plus_dm_sum = Decimal(0)
        self._minus_dm_sum = Decimal(0)
        self._smoothed_tr: Decimal | None = None
        self._smoothed_plus_dm: Decimal | None = None
        self._smoothed_minus_dm: Decimal | None = None
        self._dx_seed_count = 0
        self._dx_sum = Decimal(0)
        self._adx: Decimal | None = None
        self._state_hash = "sha256:" + ("0" * 64)

    def update(
        self,
        *,
        event_date: date,
        high: object,
        low: object,
        close: object,
        input_columns: tuple[str, ...],
    ) -> tuple[_DerivedFeatureValue, _DerivedFeatureValue]:
        high_decimal = _optional_decimal(high)
        low_decimal = _optional_decimal(low)
        close_decimal = _optional_decimal(close)
        if (
            high_decimal is None
            or low_decimal is None
            or close_decimal is None
            or high_decimal < low_decimal
        ):
            blocker = "missing_or_invalid_prefix_ohlc"
            derivation_hash = _sha256_json(
                {
                    "previous_state_hash": self._state_hash,
                    "event_date": event_date.isoformat(),
                    "high": None if high is None else str(high),
                    "low": None if low is None else str(low),
                    "close": None if close is None else str(close),
                    "blocker": blocker,
                }
            )
            self._reset_after_gap(
                event_date=event_date, state_hash=derivation_hash
            )
            return self._missing_pair(
                blocker=blocker,
                derivation_hash=derivation_hash,
                input_columns=input_columns,
            )
        if self._last_event_date is not None and event_date <= self._last_event_date:
            blocker = "duplicate_or_non_monotonic_prefix_date"
            derivation_hash = _sha256_json(
                {
                    "previous_state_hash": self._state_hash,
                    "event_date": event_date.isoformat(),
                    "blocker": blocker,
                }
            )
            return self._missing_pair(
                blocker=blocker,
                derivation_hash=derivation_hash,
                input_columns=input_columns,
            )

        previous_state_hash = self._state_hash
        true_range = high_decimal - low_decimal
        plus_dm = Decimal(0)
        minus_dm = Decimal(0)
        if (
            self._previous_high is not None
            and self._previous_low is not None
            and self._previous_close is not None
        ):
            true_range = max(
                true_range,
                abs(high_decimal - self._previous_close),
                abs(low_decimal - self._previous_close),
            )
            upward_move = high_decimal - self._previous_high
            downward_move = self._previous_low - low_decimal
            if upward_move > downward_move and upward_move > 0:
                plus_dm = upward_move
            if downward_move > upward_move and downward_move > 0:
                minus_dm = downward_move

        if self._smoothed_tr is None:
            self._seed_count += 1
            self._tr_sum += true_range
            self._plus_dm_sum += plus_dm
            self._minus_dm_sum += minus_dm
            if self._seed_count == self._PERIOD:
                self._smoothed_tr = self._tr_sum
                self._smoothed_plus_dm = self._plus_dm_sum
                self._smoothed_minus_dm = self._minus_dm_sum
        else:
            period = Decimal(self._PERIOD)
            self._smoothed_tr = (
                self._smoothed_tr
                - (self._smoothed_tr / period)
                + true_range
            )
            if self._smoothed_plus_dm is None or self._smoothed_minus_dm is None:
                raise RuntimeError("incomplete Wilder directional state")
            self._smoothed_plus_dm = (
                self._smoothed_plus_dm
                - (self._smoothed_plus_dm / period)
                + plus_dm
            )
            self._smoothed_minus_dm = (
                self._smoothed_minus_dm
                - (self._smoothed_minus_dm / period)
                + minus_dm
            )

        atr: Decimal | None = None
        if self._smoothed_tr is not None:
            atr = self._smoothed_tr / Decimal(self._PERIOD)
            dx = self._directional_index()
            if self._adx is None:
                self._dx_seed_count += 1
                self._dx_sum += dx
                if self._dx_seed_count == self._PERIOD:
                    self._adx = self._dx_sum / Decimal(self._PERIOD)
            else:
                self._adx = (
                    (self._adx * Decimal(self._PERIOD - 1)) + dx
                ) / Decimal(self._PERIOD)

        self._last_event_date = event_date
        self._previous_high = high_decimal
        self._previous_low = low_decimal
        self._previous_close = close_decimal
        self._state_hash = _sha256_json(
            {
                "previous_state_hash": previous_state_hash,
                "event_date": event_date.isoformat(),
                "high": _decimal_text(high_decimal),
                "low": _decimal_text(low_decimal),
                "close": _decimal_text(close_decimal),
                "period": self._PERIOD,
                "method": "wilder_prefix",
            }
        )
        atr_blocker = None if atr is not None else "atr_prefix_warmup_lt_14"
        adx_blocker = (
            None if self._adx is not None else "adx_prefix_warmup_lt_27"
        )
        return (
            _DerivedFeatureValue(
                value_decimal=atr,
                derivation_hash=self._state_hash,
                blocker=atr_blocker,
                input_columns=input_columns,
            ),
            _DerivedFeatureValue(
                value_decimal=self._adx,
                derivation_hash=self._state_hash,
                blocker=adx_blocker,
                input_columns=input_columns,
            ),
        )

    def _directional_index(self) -> Decimal:
        if (
            self._smoothed_tr is None
            or self._smoothed_plus_dm is None
            or self._smoothed_minus_dm is None
        ):
            raise RuntimeError("Wilder state is not ready")
        if self._smoothed_tr == 0:
            return Decimal(0)
        hundred = Decimal(100)
        plus_di = hundred * self._smoothed_plus_dm / self._smoothed_tr
        minus_di = hundred * self._smoothed_minus_dm / self._smoothed_tr
        denominator = plus_di + minus_di
        if denominator == 0:
            return Decimal(0)
        return hundred * abs(plus_di - minus_di) / denominator

    def _reset_after_gap(self, *, event_date: date, state_hash: str) -> None:
        self._last_event_date = event_date
        self._previous_high = None
        self._previous_low = None
        self._previous_close = None
        self._seed_count = 0
        self._tr_sum = Decimal(0)
        self._plus_dm_sum = Decimal(0)
        self._minus_dm_sum = Decimal(0)
        self._smoothed_tr = None
        self._smoothed_plus_dm = None
        self._smoothed_minus_dm = None
        self._dx_seed_count = 0
        self._dx_sum = Decimal(0)
        self._adx = None
        self._state_hash = state_hash

    @staticmethod
    def _missing_pair(
        *,
        blocker: str,
        derivation_hash: str,
        input_columns: tuple[str, ...],
    ) -> tuple[_DerivedFeatureValue, _DerivedFeatureValue]:
        missing = _DerivedFeatureValue(
            value_decimal=None,
            derivation_hash=derivation_hash,
            blocker=blocker,
            input_columns=input_columns,
        )
        return missing, missing


class PITYearShardExporter:
    """串流讀取 SQLite 並以 manifest-last 方式原子 publish shards。"""

    def build(self, request: PITYearShardBuildRequest) -> PITYearShardPublication:
        database_path = request.database_path.resolve()
        if not database_path.is_file():
            raise FileNotFoundError(database_path)
        output_root = request.output_root.resolve()
        capacity_budget = _capacity_budget_for_request(request)
        # The first check must happen before mkdir/tempfile so a low-capacity
        # invocation is read-only and fail-closed at the process boundary.
        initial_capacity = preflight_capacity(
            probe_path=output_root,
            budget=capacity_budget,
            stage="raw_before_output",
        )
        decision = _decision_datetime(request.decision_at)
        history_start = _date_value(request.history_start_date)
        if history_start > decision.date():
            raise ValueError("history_start_date must not exceed decision_at")
        if request.years and max(request.years) > decision.year:
            raise ValueError("requested shard year must not exceed decision year")

        source_quality_summary: dict[str, Any] | None = None

        source_dirs: tuple[Path, ...] = tuple(
            path
            for path in (
                (() if request.daily_price_source_dir is None else (request.daily_price_source_dir,))
                + (
                    ()
                    if request.daily_price_source_dirs is None
                    else request.daily_price_source_dirs
                )
            )
        )
        if source_dirs:
            source_roots = (database_path.parent, *source_dirs)
            try:
                source_quality = assert_daily_price_source_quality(
                    sqlite_path=database_path,
                    canonical_daily_price_dirs=source_dirs,
                    start_date=history_start.isoformat(),
                    end_date=decision.date().isoformat(),
                    quality_mode="ingest_guard",
                    quality_known_at=request.source_quality_known_at,
                    candidate_sample_limit=request.source_quality_candidate_sample_limit,
                )
            except DailyPriceSourceQualityError as exc:
                if _source_quality_is_price_unavailable_only(exc.report):
                    # Keep the raw row and its missing mask in the shard.  The
                    # feature/label consumers must exclude its affected
                    # windows; this exception never permits a CSV mismatch or
                    # scale anomaly to reach publication.
                    source_quality_summary = {
                        "schema_version": str(exc.report.get("schema_version", "")),
                        "status": str(exc.report.get("status", "")),
                        "research_only": True,
                        "formal_training_allowed": False,
                        "price_availability_contract": (
                            PRICE_AVAILABILITY_CONTRACT_VERSION
                        ),
                        "candidate_count": int(exc.report["candidate_count"]),
                        "research_price_unavailable_count": int(
                            exc.report["research_price_unavailable_count"]
                        ),
                        "candidate_digest": str(
                            exc.report.get("candidate_digest", "")
                        ),
                        "report_hash": str(exc.report.get("report_hash", "")),
                    }
                    if request.source_quality_report_path is not None:
                        write_quarantine_report(
                            request.source_quality_report_path,
                            exc.report,
                            source_roots=source_roots,
                        )
                else:
                    if request.source_quality_report_path is not None:
                        write_quarantine_report(
                            request.source_quality_report_path,
                            exc.report,
                            source_roots=source_roots,
                        )
                    raise
            else:
                source_quality_summary = {
                    "schema_version": str(source_quality.get("schema_version", "")),
                    "status": str(source_quality.get("status", "")),
                    "research_only": False,
                    "formal_training_allowed": bool(
                        source_quality.get("formal_training_allowed", False)
                    ),
                    "price_availability_contract": (
                        PRICE_AVAILABILITY_CONTRACT_VERSION
                    ),
                    "candidate_count": int(source_quality.get("candidate_count", 0)),
                    "research_price_unavailable_count": int(
                        source_quality.get("research_price_unavailable_count", 0)
                    ),
                    "candidate_digest": str(
                        source_quality.get("candidate_digest", "")
                    ),
                    "report_hash": str(source_quality.get("report_hash", "")),
                }
            if request.source_quality_report_path is not None and source_quality_summary is not None and not source_quality_summary["research_only"]:
                write_quarantine_report(
                    request.source_quality_report_path,
                    source_quality,
                    source_roots=source_roots,
                )

        output_root.mkdir(parents=True, exist_ok=True)
        runs_root = output_root / "runs"
        persistent_baseline_bytes = directory_size_bytes(runs_root)
        runs_root.mkdir(parents=True, exist_ok=True)

        source_stat_before = database_path.stat()
        staging: Path | None = None
        peak_temporary_bytes = 0
        last_capacity_preflight = initial_capacity.as_dict()
        capacity_checkpoint_count = 0
        capacity_last_stage = "raw_before_output"

        def capacity_checkpoint(
            stage: str,
            *,
            additional_persistent_bytes: int = 0,
        ) -> None:
            """Recheck persistent delta and staging bytes without writing data."""

            nonlocal capacity_checkpoint_count, capacity_last_stage
            nonlocal last_capacity_preflight, peak_temporary_bytes
            temporary_roots = () if staging is None else (staging,)
            persistent_now = directory_size_bytes(runs_root)
            persistent_new = max(
                0,
                persistent_now - persistent_baseline_bytes,
            ) + additional_persistent_bytes
            result = preflight_capacity(
                probe_path=output_root,
                budget=capacity_budget,
                stage=stage,
                persistent_roots=(runs_root,),
                persistent_new_bytes_estimate=persistent_new,
                temporary_roots=temporary_roots,
                temporary_peak_bytes_observed=peak_temporary_bytes,
            )
            observed_temporary_bytes = result.temporary_peak_bytes_observed
            if observed_temporary_bytes is not None:
                # 容量預算可允許 unknown；已觀測值存在時才更新峰值。
                peak_temporary_bytes = max(
                    peak_temporary_bytes,
                    observed_temporary_bytes,
                )
            last_capacity_preflight = result.as_dict()
            capacity_checkpoint_count += 1
            capacity_last_stage = stage

        staging = Path(
            tempfile.mkdtemp(prefix=".pit-shards-", dir=str(output_root))
        ).resolve()
        writers = _ShardWriterRegistry(
            staging=staging,
            compression_level=request.compression_level,
        )
        if request.years:
            for dataset_id in _DATASET_IDS:
                for year in request.years:
                    writers.get(dataset_id, year)

        connection: sqlite3.Connection | None = None
        transaction_started = False
        try:
            capacity_checkpoint("raw_staging_created")
            connection = _connect_read_only(database_path)
            connection.row_factory = sqlite3.Row
            data_version_before = _pragma_int(connection, "data_version")
            connection.execute("BEGIN")
            transaction_started = True
            eligibility = build_feature_eligibility_manifest(connection)
            dataset_records = _dataset_records(eligibility)
            table_results: list[dict[str, Any]] = []
            query_count = 0
            for table_name in ALL_FIELD_SOURCE_TABLES:
                capacity_checkpoint(f"raw_table_{table_name}_start")
                if table_name in eligibility.missing_tables:
                    table_results.append(
                        {
                            "table_name": table_name,
                            "family": table_family(table_name),
                            "state": "missing",
                            "source_row_count": 0,
                            "emitted_row_count": 0,
                            "blocked_future_row_count": 0,
                            "blocked_missing_availability_row_count": 0,
                            "filtered_year_row_count": 0,
                            "diagnostics": ["optional_source_table_missing"],
                        }
                    )
                    capacity_checkpoint(f"raw_table_{table_name}_complete")
                    continue
                table_result = self._stream_table(
                    connection=connection,
                    table_name=table_name,
                    manifest=eligibility,
                    dataset_records=dataset_records,
                    writers=writers,
                    decision=decision,
                    history_start=history_start,
                    symbols=request.symbols,
                    years=request.years,
                    industry_index_names=request.industry_index_names,
                    batch_size=request.batch_size,
                    capacity_checkpoint=capacity_checkpoint,
                )
                table_results.append(table_result)
                query_count += 1
                capacity_checkpoint(f"raw_table_{table_name}_complete")
            data_version_after = _pragma_int(connection, "data_version")
            if data_version_after != data_version_before:
                raise RuntimeError(
                    "SQLite source data_version changed during shard export"
                )
            connection.execute("ROLLBACK")
            transaction_started = False
            connection.close()
            connection = None
            writers.close_all()

            source_stat_after = database_path.stat()
            if (
                source_stat_before.st_size,
                source_stat_before.st_mtime_ns,
            ) != (
                source_stat_after.st_size,
                source_stat_after.st_mtime_ns,
            ):
                raise RuntimeError("SQLite source changed during shard export")

            eligibility_path = staging / "feature_eligibility_manifest.json"
            eligibility_payload = _eligibility_payload(eligibility)
            _write_json(eligibility_path, eligibility_payload)
            eligibility_file_hash = _file_sha256(eligibility_path)
            source_fingerprint = _sha256_json(
                {
                    "eligibility_manifest_hash": eligibility.manifest_hash,
                    "database_size": source_stat_before.st_size,
                    "database_mtime_ns": source_stat_before.st_mtime_ns,
                }
            )
            dataset_manifests = self._write_dataset_manifests(
                staging=staging,
                writers=writers,
                records=dataset_records,
                decision=decision,
                history_start=history_start,
                requested_years=request.years,
                eligibility_manifest_hash=eligibility.manifest_hash,
                source_fingerprint=source_fingerprint,
                source_quality_summary=source_quality_summary,
                capacity_checkpoint=capacity_checkpoint,
            )
            content_identity = {
                "decision_at": decision.isoformat(),
                "history_start_date": history_start.isoformat(),
                "eligibility_manifest_hash": eligibility.manifest_hash,
                "source_fingerprint": source_fingerprint,
                "dataset_manifest_hashes": {
                    dataset_id: manifest["manifest_hash"]
                    for dataset_id, manifest in sorted(dataset_manifests.items())
                },
            }
            publication_id = (
                "pit-" + _sha256_hex(_canonical_json(content_identity))[:24]
            )
            source_unreviewed = tuple(
                record.feature_id
                for record in eligibility.unreviewed_records
                if record.table_name in ALL_FIELD_SOURCE_TABLES
            )
            publication_manifest: dict[str, Any] = {
                "schema_version": "ml-pit-year-shards.v1",
                "stage": "raw_pit_observations",
                "publication_id": publication_id,
                "decision_at": decision.isoformat(),
                "history_start_date": history_start.isoformat(),
                "partition_basis": "available_at_taipei_year",
                "format": "gzip_jsonl",
                "numeric_contract": "value_int_plus_positive_scale",
                "source": {
                    "database_fingerprint": source_fingerprint,
                    "database_size": source_stat_before.st_size,
                    "eligibility_manifest_hash": eligibility.manifest_hash,
                    "eligibility_file": "feature_eligibility_manifest.json",
                    "eligibility_file_sha256": eligibility_file_hash,
                },
                "scope": {
                    "all_universe": request.symbols is None,
                    "symbols": (
                        None if request.symbols is None else list(request.symbols)
                    ),
                    "symbols_hash": _sha256_json(
                        {
                            "all_universe": request.symbols is None,
                            "symbols": (
                                []
                                if request.symbols is None
                                else list(request.symbols)
                            ),
                        }
                    ),
                    "requested_years": list(request.years),
                    "industry_index_names": list(request.industry_index_names),
                },
                "pit": {
                    "strict_availability_required": True,
                    "future_rows_allowed": False,
                    "first_seen_fallback_may_backdate": False,
                    "date_only_availability_policy": "end_of_day",
                    "price_event_availability_policy": "event_date_14:30_Asia/Taipei",
                    "unknown_columns_fail_closed": True,
                    "source_unreviewed_count": len(source_unreviewed),
                    "source_unreviewed_feature_ids": list(source_unreviewed),
                    "staleness_mask_basis": "publication_decision_at",
                    "training_row_staleness_must_be_recomputed": True,
                },
                "datasets": {
                    dataset_id: {
                        "manifest_path": f"{dataset_id}/manifest.json",
                        "manifest_hash": manifest["manifest_hash"],
                        "included_statuses": manifest["included_statuses"],
                        "feature_count": manifest["feature_count"],
                        "shard_count": manifest["shard_count"],
                        "row_count": manifest["row_count"],
                    }
                    for dataset_id, manifest in sorted(dataset_manifests.items())
                },
                "table_results": sorted(
                    table_results, key=lambda item: str(item["table_name"])
                ),
                "execution": {
                    "sqlite_mode": "ro",
                    "query_only": True,
                    "streaming_fetchmany": True,
                    "batch_size": request.batch_size,
                    "query_count": query_count,
                    "parquet_dependency_added": False,
                    "production_action_allowed": False,
                    "capacity_budget": capacity_budget.as_dict(),
                    # Runtime free/used bytes and the last checkpoint stage
                    # are deliberately kept out of the immutable publication
                    # manifest; replaying the same source must retain the
                    # same manifest hash even when filesystem telemetry has
                    # changed.  The budget and enforcement contract are
                    # deterministic and therefore safe to retain here.
                    "capacity_policy_schema": "ml-storage-capacity.v1",
                    "capacity_quota_enforced_during_stages": True,
                },
                "training_adapter": {
                    "direct_training_input": False,
                    "target_cli": "scripts/train_ml_allocation_copilot.py",
                    "target_schema_version": "allocation-training-input-v1",
                    "required_horizons": [5, 10, 20, 60],
                    "next_stage": "portfolio_ml_dataset_row_assembly",
                    "assembly_blockers": [
                        "as_of_join_raw_observations_into_symbol_decision_rows",
                        "attach_t_minus_1_causal_portfolio_state",
                        "build_matured_allocation_targets_and_horizon_labels",
                        "build_four_or_more_purged_walk_forward_folds",
                        "recompute_staleness_against_each_training_decision_at",
                    ],
                    "must_emit": [
                        "PortfolioMLDatasetRow",
                        "AllocationTargets",
                        "AllocationHorizonLabel",
                        "feature_packs",
                        "folds",
                    ],
                },
            }
            if source_quality_summary is not None:
                publication_manifest["source_quality"] = source_quality_summary
            publication_manifest["manifest_hash"] = _sha256_json(
                publication_manifest
            )
            _write_json(staging / "manifest.json", publication_manifest)
            capacity_checkpoint("raw_manifest_written")

            publication_directory = runs_root / publication_id
            if publication_directory.exists():
                existing_manifest_path = publication_directory / "manifest.json"
                existing = _read_json(existing_manifest_path)
                if existing.get("manifest_hash") != publication_manifest["manifest_hash"]:
                    raise RuntimeError(
                        "publication identity collision with different manifest"
                    )
                # The publication already exists, so this replay has no new
                # persistent bytes.  Check the remaining staging peak before
                # removing it; a post-remove check would only add another
                # failure point without protecting the atomic publication.
                capacity_checkpoint("raw_publication_existing_ready")
                _safe_remove_staging(staging, output_root)
            else:
                # Validate the projected persistent delta while the staging
                # tree is still present.  If this check fails, the existing
                # exception path removes only staging and leaves no orphan
                # publication behind.
                capacity_checkpoint(
                    "raw_publication_ready",
                    additional_persistent_bytes=directory_size_bytes(staging),
                )
                os.replace(staging, publication_directory)
                staging = None

            latest_manifest_path = output_root / "latest_manifest.json"
            pointer = {
                "schema_version": "ml-pit-year-shards-pointer.v1",
                "publication_id": publication_id,
                "manifest_path": f"runs/{publication_id}/manifest.json",
                "manifest_hash": publication_manifest["manifest_hash"],
            }
            _atomic_write_json(latest_manifest_path, pointer)
            dataset_manifest_paths: dict[str, Path] = {
                dataset_id: publication_directory / dataset_id / "manifest.json"
                for dataset_id in _DATASET_IDS
            }
            return PITYearShardPublication(
                publication_id=publication_id,
                publication_directory=publication_directory,
                manifest_path=publication_directory / "manifest.json",
                latest_manifest_path=latest_manifest_path,
                manifest_hash=str(publication_manifest["manifest_hash"]),
                dataset_manifest_paths=dataset_manifest_paths,
                shard_count=sum(
                    int(manifest["shard_count"])
                    for manifest in dataset_manifests.values()
                ),
                row_count=sum(
                    int(manifest["row_count"])
                    for manifest in dataset_manifests.values()
                ),
                capacity_preflight=dict(last_capacity_preflight),
                temporary_peak_bytes_observed=peak_temporary_bytes,
                capacity_checkpoint_count=capacity_checkpoint_count,
                capacity_last_stage=capacity_last_stage,
            )
        except Exception:
            writers.close_all()
            if connection is not None:
                if transaction_started:
                    try:
                        connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                connection.close()
            if staging is not None and staging.exists():
                _safe_remove_staging(staging, output_root)
            raise

    def _stream_table(
        self,
        *,
        connection: sqlite3.Connection,
        table_name: str,
        manifest: FeatureEligibilityManifest,
        dataset_records: Mapping[DatasetId, tuple[FeatureEligibilityRecord, ...]],
        writers: "_ShardWriterRegistry",
        decision: datetime,
        history_start: date,
        symbols: tuple[str, ...] | None,
        years: tuple[int, ...],
        industry_index_names: tuple[str, ...],
        batch_size: int,
        capacity_checkpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        table_manifest_records = manifest.for_table(table_name)
        column_names = {record.column_name for record in table_manifest_records}
        runtime = _RUNTIME_POLICIES[table_name]
        identity_columns = (
            *runtime.identity_columns,
            *tuple(
                column
                for column in runtime.optional_identity_columns
                if column in column_names
            ),
        )
        if not table_manifest_records:
            return _blocked_table_result(
                table_name, "schema_has_no_columns"
            )
        time_policy = table_manifest_records[0].time_policy
        missing_required = sorted(
            {
                time_policy.event_at,
                *identity_columns,
            }
            - column_names
        )
        per_dataset = {
            dataset_id: tuple(
                record
                for record in records
                if record.table_name == table_name
                and not (
                    table_name == "technical_indicators"
                    and record.feature_id
                    in {
                        "technical_indicators.ATR",
                        "technical_indicators.ADX",
                    }
                )
            )
            for dataset_id, records in dataset_records.items()
        }
        derived_atr_adx_records = {
            dataset_id: tuple(
                record
                for record in records
                if table_name == "daily_prices"
                and record.feature_id
                in {
                    "technical_indicators.ATR",
                    "technical_indicators.ADX",
                }
            )
            for dataset_id, records in dataset_records.items()
        }
        selected_records = tuple(
            sorted(
                {
                    record.feature_id: record
                    for records in per_dataset.values()
                    for record in records
                }.values(),
                key=lambda record: record.feature_id,
            )
        )
        if missing_required:
            return _blocked_table_result(
                table_name,
                *(f"missing_required_column:{column}" for column in missing_required),
            )
        if not selected_records:
            return _blocked_table_result(
                table_name, "no_explicit_numeric_eligible_features"
            )

        select_parts: list[str] = []
        for index, column_name in enumerate(identity_columns):
            select_parts.append(
                f"{_quote_identifier(column_name)} AS "
                f"{_quote_identifier(f'__identity_{index}')}"
            )
        select_parts.append(
            f"{_quote_identifier(time_policy.event_at)} AS "
            f"{_quote_identifier('__event_at')}"
        )
        metadata_columns: dict[str, str | None] = {
            "announced_at": time_policy.announced_at,
            "available_at": time_policy.available_at,
            "first_seen_at": time_policy.first_seen_at,
            "effective_at": time_policy.effective_at,
            "revision_id": time_policy.revision_id,
            "quality": "quality" if "quality" in column_names else None,
            "source": "source" if "source" in column_names else None,
            "source_version": "source_version" if "source_version" in column_names else None,
        }
        for alias, metadata_column_name in metadata_columns.items():
            if (
                metadata_column_name is not None
                and metadata_column_name in column_names
            ):
                select_parts.append(
                    f"{_quote_identifier(metadata_column_name)} AS "
                    f"{_quote_identifier(f'__{alias}')}"
                )
        atr_adx_input_groups = _atr_adx_input_column_groups(
            table_name=table_name,
            column_names=column_names,
        )
        for group_index, group in enumerate(atr_adx_input_groups):
            for field_name, column_name in zip(("high", "low", "close"), group):
                select_parts.append(
                    f"CAST({_quote_identifier(column_name)} AS TEXT) AS "
                    f"{_quote_identifier(f'__derive_{group_index}_{field_name}')}"
                )
        feature_aliases: dict[str, str] = {}
        for index, record in enumerate(selected_records):
            alias = f"__feature_{index}"
            feature_aliases[record.feature_id] = alias
            select_parts.append(
                f"CAST({_quote_identifier(record.column_name)} AS TEXT) AS "
                f"{_quote_identifier(alias)}"
            )
        raw_price_aliases = {
            record.column_name: feature_aliases[record.feature_id]
            for record in selected_records
            if table_name == "daily_prices"
            and record.column_name
            in {"證券名稱", "開盤價", "最高價", "最低價", "收盤價", "成交股數"}
        }

        predicates: list[str] = []
        parameters: list[object] = []
        if runtime.stock_column is not None and symbols is not None:
            predicates.append(
                f"{_quote_identifier(runtime.stock_column)} IN "
                f"({_placeholders(len(symbols))})"
            )
            parameters.extend(symbols)
        if runtime.industry_column is not None and industry_index_names:
            predicates.append(
                f"{_quote_identifier(runtime.industry_column)} IN "
                f"({_placeholders(len(industry_index_names))})"
            )
            parameters.extend(industry_index_names)
        if years and table_name != "daily_prices":
            year_columns = tuple(
                dict.fromkeys(
                    column
                    for column in (
                        time_policy.event_at,
                        time_policy.available_at,
                        time_policy.announced_at,
                        time_policy.first_seen_at,
                    )
                    if column is not None and column in column_names
                )
            )
            year_predicates: list[str] = []
            for column in year_columns:
                year_predicates.append(
                    f"{_sql_year_expression(column)} IN "
                    f"({_placeholders(len(years))})"
                )
                parameters.extend(years)
            if year_predicates:
                predicates.append("(" + " OR ".join(year_predicates) + ")")

        # 先依 entity 再依 event time 排序，既能維持每檔 ATR/ADX 的因果
        # prefix，也能利用正式表常見的 (symbol, date) / (index, date)
        # 主鍵索引。若把日期放第一個，五百萬列行情會被迫做全表 temp
        # sort；後續欄位只作同一 identity/event/revision 重複列的
        # deterministic tie-break。
        if table_name in _PRIMARY_KEY_STREAM_TABLES:
            # PRIMARY KEY 已保證 entity/event 唯一且順序穩定；保持索引串流，
            # 避免為不可能出現的同鍵 row 做全表右側排序。
            order_columns = [
                *runtime.identity_columns,
                *(
                    column
                    for column in identity_columns
                    if column not in runtime.identity_columns
                ),
                time_policy.event_at,
            ]
        else:
            order_columns = [
                *identity_columns,
                time_policy.event_at,
                *(
                    (time_policy.revision_id,)
                    if time_policy.revision_id is not None
                    else ()
                ),
                *(
                    column
                    for group in atr_adx_input_groups
                    for column in group
                ),
                *(record.column_name for record in selected_records),
            ]
        query = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {_quote_identifier(table_name)}"
        )
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY " + ", ".join(
            _quote_identifier(column) for column in dict.fromkeys(order_columns)
        )

        source_row_count = 0
        emitted_row_count = 0
        blocked_future_rows = 0
        blocked_missing_availability_rows = 0
        filtered_year_rows = 0
        filtered_history_rows = 0
        invalid_event_rows = 0
        derived_atr_count = 0
        derived_adx_count = 0
        blocked_atr_adx_count = 0
        price_unavailable_row_count = 0
        price_unavailable_contract_samples: list[dict[str, Any]] = []
        technical_states: dict[str, _CausalWilder14State] = {}
        cursor = connection.execute(query, tuple(parameters))
        batch_number = 0
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            batch_number += 1
            for row in batch:
                source_row_count += 1
                event_date = _optional_date(row["__event_at"])
                if event_date is None:
                    invalid_event_rows += 1
                    continue
                if event_date < history_start:
                    filtered_history_rows += 1
                    continue
                event_at = datetime.combine(
                    event_date, _MARKET_CLOSE_TIME, tzinfo=_TAIPEI
                )
                if event_at >= decision:
                    blocked_future_rows += 1
                    continue
                announced_at = _row_optional_datetime(row, "__announced_at")
                explicit_available_at = _row_optional_datetime(
                    row, "__available_at"
                )
                first_seen_at = _row_optional_datetime(row, "__first_seen_at")
                effective_at = _row_optional_datetime(row, "__effective_at")
                revision_id = _row_optional_text(row, "__revision_id")
                quality = _row_optional_text(row, "__quality") or "not_provided"
                source = _row_optional_text(row, "__source")
                source_version = _row_optional_text(row, "__source_version")
                entity_id = "|".join(
                    _required_identity(row[f"__identity_{index}"])
                    for index in range(len(identity_columns))
                )
                price_unavailable_contract: dict[str, Any] | None = None
                if table_name == "daily_prices" and {
                    "開盤價",
                    "最高價",
                    "最低價",
                    "收盤價",
                }.issubset(raw_price_aliases):
                    raw_price_row = {
                        "symbol": entity_id,
                        "name": (
                            row[raw_price_aliases["證券名稱"]]
                            if "證券名稱" in raw_price_aliases
                            else None
                        ),
                        "open": row[raw_price_aliases["開盤價"]],
                        "high": row[raw_price_aliases["最高價"]],
                        "low": row[raw_price_aliases["最低價"]],
                        "close": row[raw_price_aliases["收盤價"]],
                        "volume": (
                            row[raw_price_aliases["成交股數"]]
                            if "成交股數" in raw_price_aliases
                            else None
                        ),
                    }
                    try:
                        price_unavailable_contract = (
                            build_price_unavailable_research_contract(
                                symbol=entity_id,
                                date_iso=event_date.isoformat(),
                                raw_row=raw_price_row,
                            )
                        )
                    except ValueError as contract_error:
                        if str(contract_error) != "raw_row has no unavailable price field":
                            raise
                    if price_unavailable_contract is not None:
                        price_unavailable_row_count += 1
                        if len(price_unavailable_contract_samples) < 64:
                            price_unavailable_contract_samples.append(
                                price_unavailable_contract
                            )
                report_basis: str | None = None
                if table_name == "fundamental_statement_items":
                    report_basis = resolve_statement_report_basis(
                        explicit_value=(
                            row[
                                f"__identity_{identity_columns.index('report_basis')}"
                            ]
                            if "report_basis" in identity_columns
                            else None
                        ),
                        explicit_column_present="report_basis" in column_names,
                        source=source,
                        source_version=source_version,
                    )
                derived_values: dict[str, _DerivedFeatureValue] = {}
                if table_name == "daily_prices":
                    selected_input = _select_technical_input(
                        row=row,
                        input_groups=atr_adx_input_groups,
                    )
                    if selected_input is not None:
                        input_columns, high, low, close = selected_input
                        state = technical_states.setdefault(
                            entity_id, _CausalWilder14State()
                        )
                        atr_value, adx_value = state.update(
                            event_date=event_date,
                            high=high,
                            low=low,
                            close=close,
                            input_columns=input_columns,
                        )
                    else:
                        missing_hash = _sha256_json(
                            {
                                "event_date": event_date.isoformat(),
                                "entity_id": entity_id,
                                "blocker": "missing_ohlc_derivation_columns",
                            }
                        )
                        state = technical_states.setdefault(
                            entity_id, _CausalWilder14State()
                        )
                        state._reset_after_gap(
                            event_date=event_date,
                            state_hash=missing_hash,
                        )
                        atr_value, adx_value = _CausalWilder14State._missing_pair(
                            blocker="missing_ohlc_derivation_columns",
                            derivation_hash=missing_hash,
                            input_columns=(),
                        )
                    derived_values["technical_indicators.ATR"] = atr_value
                    derived_values["technical_indicators.ADX"] = adx_value
                    derived_atr_count += int(atr_value.value_decimal is not None)
                    derived_adx_count += int(adx_value.value_decimal is not None)
                    blocked_atr_adx_count += int(
                        atr_value.value_decimal is None
                        or adx_value.value_decimal is None
                    )

                emitted_this_source_row = False
                future_this_source_row = False
                missing_this_source_row = False
                year_filtered_this_source_row = False
                for dataset_id in _DATASET_IDS:
                    records = per_dataset[dataset_id]
                    if not records:
                        continue
                    grouped: dict[datetime, list[FeatureEligibilityRecord]] = {}
                    for record in records:
                        available_at = _availability_for_status(
                            status=record.eligibility_status,
                            event_at=event_at,
                            available_at=explicit_available_at,
                            announced_at=announced_at,
                            first_seen_at=first_seen_at,
                        )
                        if available_at is None:
                            missing_this_source_row = True
                            continue
                        if available_at > decision:
                            future_this_source_row = True
                            continue
                        if years and available_at.year not in years:
                            year_filtered_this_source_row = True
                            continue
                        grouped.setdefault(available_at, []).append(record)

                    for available_at, group_records in sorted(grouped.items()):
                        values = tuple(
                            _feature_value_payload(
                                record,
                                raw_value=row[feature_aliases[record.feature_id]],
                                decision=decision,
                                available_at=available_at,
                                quality=quality,
                                derived_value=derived_values.get(
                                    record.feature_id
                                ),
                            )
                            for record in sorted(
                                group_records, key=lambda item: item.feature_id
                            )
                        )
                        row_payload: dict[str, Any] = {
                            "schema_version": "ml-pit-observation.v1",
                            "dataset_id": dataset_id,
                            "source_table": table_name,
                            "source_id": group_records[0].source_id,
                            "family": group_records[0].family,
                            "entity_id": entity_id,
                            **(
                                {"report_basis": report_basis}
                                if report_basis is not None
                                else {}
                            ),
                            "event_at": event_at.isoformat(),
                            "available_at": available_at.isoformat(),
                            "announced_at": (
                                None
                                if announced_at is None
                                else announced_at.isoformat()
                            ),
                            "first_seen_at": (
                                None
                                if first_seen_at is None
                                else first_seen_at.isoformat()
                            ),
                            "effective_at": (
                                None
                                if effective_at is None
                                else effective_at.isoformat()
                            ),
                            "revision_id": revision_id,
                            "quality": quality,
                            "source": source,
                            "pit_status": "eligible_as_of_decision",
                            "values": list(values),
                        }
                        if price_unavailable_contract is not None:
                            row_payload["price_availability_contract"] = (
                                price_unavailable_contract
                            )
                        row_payload["source_row_hash"] = _sha256_json(row_payload)
                        writers.get(dataset_id, available_at.year).write(row_payload)
                        emitted_row_count += 1
                        emitted_this_source_row = True

                for dataset_id in (
                    "core_long_history",
                    "all_field_enriched",
                ):
                    records = derived_atr_adx_records[dataset_id]
                    if not records:
                        continue
                    derived_available_at = event_at
                    if years and derived_available_at.year not in years:
                        year_filtered_this_source_row = True
                        continue
                    values = tuple(
                        _feature_value_payload(
                            record,
                            raw_value=None,
                            decision=decision,
                            available_at=derived_available_at,
                            quality=quality,
                            derived_value=derived_values.get(record.feature_id),
                        )
                        for record in sorted(
                            records, key=lambda item: item.feature_id
                        )
                    )
                    derived_payload: dict[str, Any] = {
                        "schema_version": "ml-pit-observation.v1",
                        "dataset_id": dataset_id,
                        "source_table": "daily_prices",
                        "source_id": "derived:daily_prices.ohlc",
                        "family": "price_liquidity_technical",
                        "entity_id": entity_id,
                        "event_at": event_at.isoformat(),
                        "available_at": derived_available_at.isoformat(),
                        "announced_at": None,
                        "first_seen_at": None,
                        "effective_at": None,
                        "revision_id": None,
                        "quality": quality,
                        "source": source,
                        "pit_status": "eligible_as_of_decision",
                        "values": list(values),
                    }
                    if price_unavailable_contract is not None:
                        derived_payload["price_availability_contract"] = (
                            price_unavailable_contract
                        )
                    derived_payload["source_row_hash"] = _sha256_json(
                        derived_payload
                    )
                    writers.get(
                        dataset_id, derived_available_at.year
                    ).write(derived_payload)
                    emitted_row_count += 1
                    emitted_this_source_row = True

                if not emitted_this_source_row:
                    if future_this_source_row:
                        blocked_future_rows += 1
                    if missing_this_source_row:
                        blocked_missing_availability_rows += 1
                    if year_filtered_this_source_row:
                        filtered_year_rows += 1
            # A bounded cadence avoids scanning the staging tree on every row
            # while still stopping a long table before its next table boundary.
            if (
                capacity_checkpoint is not None
                and batch_number % 128 == 0
            ):
                capacity_checkpoint(
                    f"raw_table_{table_name}_batch_{batch_number}"
                )
        cursor.close()

        unreviewed = tuple(
            record.feature_id
            for record in table_manifest_records
            if record.eligibility_status == "unreviewed"
        )
        diagnostics = [
            *(f"unreviewed_fail_closed:{feature_id}" for feature_id in unreviewed),
        ]
        if invalid_event_rows:
            diagnostics.append(f"invalid_event_rows:{invalid_event_rows}")
        if table_name == "daily_prices":
            diagnostics.extend(
                (
                    "atr_adx_derivation:causal_wilder_14_prefix",
                    "atr_adx_availability:event_close_for_next_decision",
                    f"atr_derived_rows:{derived_atr_count}",
                    f"adx_derived_rows:{derived_adx_count}",
                    f"atr_adx_blocked_rows:{blocked_atr_adx_count}",
                    "atr_adx_input_column_groups:"
                    + ";".join(
                        ",".join(group)
                        for group in atr_adx_input_groups
                    )
                    if atr_adx_input_groups
                    else "atr_adx_input_column_groups:<missing>",
                )
            )
        if table_name == "technical_indicators":
            diagnostics.append(
                "raw_atr_adx_ignored:derived_from_daily_prices_prefix"
            )
        table_state = "available" if emitted_row_count else "empty"
        if unreviewed or invalid_event_rows or blocked_missing_availability_rows:
            table_state = "degraded" if emitted_row_count else "blocked"
        return {
            "table_name": table_name,
            "family": table_family(table_name),
            "state": table_state,
            "source_row_count": source_row_count,
            "emitted_row_count": emitted_row_count,
            "blocked_future_row_count": blocked_future_rows,
            "blocked_missing_availability_row_count": (
                blocked_missing_availability_rows
            ),
            "filtered_year_row_count": filtered_year_rows,
            "filtered_history_row_count": filtered_history_rows,
            "invalid_event_row_count": invalid_event_rows,
            "price_unavailable_row_count": price_unavailable_row_count,
            "price_unavailable_contract_schema": (
                PRICE_AVAILABILITY_CONTRACT_VERSION
                if price_unavailable_row_count
                else None
            ),
            "price_unavailable_contract_samples": (
                price_unavailable_contract_samples
            ),
            "diagnostics": diagnostics,
        }

    def _write_dataset_manifests(
        self,
        *,
        staging: Path,
        writers: "_ShardWriterRegistry",
        records: Mapping[DatasetId, tuple[FeatureEligibilityRecord, ...]],
        decision: datetime,
        history_start: date,
        requested_years: tuple[int, ...],
        eligibility_manifest_hash: str,
        source_fingerprint: str,
        source_quality_summary: Mapping[str, Any] | None = None,
        capacity_checkpoint: Callable[[str], None] | None = None,
    ) -> dict[DatasetId, dict[str, Any]]:
        result: dict[DatasetId, dict[str, Any]] = {}
        for dataset_id in _DATASET_IDS:
            dataset_records = records[dataset_id]
            for writer in writers.for_dataset(dataset_id):
                if capacity_checkpoint is not None:
                    capacity_checkpoint(
                        f"raw_dataset_{dataset_id}_year_{writer.year}"
                    )
            shard_payloads = [
                writer.manifest_payload(staging=staging)
                for writer in writers.for_dataset(dataset_id)
            ]
            features = [_feature_manifest_payload(record) for record in dataset_records]
            included_statuses = tuple(
                sorted({record.eligibility_status for record in dataset_records})
            )
            manifest: dict[str, Any] = {
                "schema_version": "ml-pit-year-shard-dataset.v1",
                "stage": "raw_pit_observations",
                "dataset_id": dataset_id,
                "decision_at": decision.isoformat(),
                "history_start_date": history_start.isoformat(),
                "partition_basis": "available_at_taipei_year",
                "format": "gzip_jsonl",
                "eligibility_manifest_hash": eligibility_manifest_hash,
                "source_fingerprint": source_fingerprint,
                "included_statuses": list(included_statuses),
                "requested_years": list(requested_years),
                "feature_count": len(features),
                "features": features,
                "shard_count": len(shard_payloads),
                "row_count": sum(int(shard["row_count"]) for shard in shard_payloads),
                "feature_value_count": sum(
                    int(shard["feature_value_count"]) for shard in shard_payloads
                ),
                "missing_value_count": sum(
                    int(shard["missing_value_count"]) for shard in shard_payloads
                ),
                "stale_value_count": sum(
                    int(shard["stale_value_count"]) for shard in shard_payloads
                ),
                "shards": shard_payloads,
                "safety": {
                    "formal_dataset": dataset_id != "research_shadow_all_fields",
                    "research_shadow_isolated": True,
                    "unreviewed_included": False,
                    "excluded_leakage_included": False,
                    "raw_float_persistence_allowed": False,
                    "staleness_mask_basis": "publication_decision_at",
                },
                "training_adapter": {
                    "direct_training_input": False,
                    "target_schema_version": "allocation-training-input-v1",
                    "feature_pack_adapter": [
                        {
                            "pack_id": family,
                            "feature_ids": [
                                feature["feature_id"]
                                for feature in features
                                if feature["family"] == family
                            ],
                        }
                        for family in sorted(
                            {str(feature["family"]) for feature in features}
                        )
                    ],
                    "next_stage": "portfolio_ml_dataset_row_assembly",
                    "assembly_blockers": [
                        "daily_as_of_join_not_yet_materialized",
                        "causal_portfolio_state_not_in_raw_observation",
                        "teacher_targets_and_horizon_labels_not_in_raw_observation",
                        "purged_walk_forward_folds_not_in_raw_observation",
                        "per_decision_staleness_not_yet_materialized",
                    ],
                },
            }
            if source_quality_summary is not None:
                manifest["source_quality"] = dict(source_quality_summary)
            manifest["manifest_hash"] = _sha256_json(manifest)
            dataset_directory = staging / dataset_id
            dataset_directory.mkdir(parents=True, exist_ok=True)
            _write_json(dataset_directory / "manifest.json", manifest)
            result[dataset_id] = manifest
        return result


class _ShardWriter:
    def __init__(
        self,
        *,
        path: Path,
        dataset_id: DatasetId,
        year: int,
        compression_level: int,
    ) -> None:
        self.path = path
        self.dataset_id = dataset_id
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
        self.row_count = 0
        self.feature_value_count = 0
        self.missing_value_count = 0
        self.stale_value_count = 0
        self.quality_blocked_value_count = 0
        self.source_tables: set[str] = set()
        self.min_event_at: str | None = None
        self.max_event_at: str | None = None
        self.min_available_at: str | None = None
        self.max_available_at: str | None = None

    def write(self, payload: Mapping[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("cannot write a closed shard")
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        self._gzip.write(encoded)
        self._content_digest.update(encoded)
        self.row_count += 1
        values = payload.get("values")
        if not isinstance(values, list):
            raise TypeError("shard payload values must be a list")
        self.feature_value_count += len(values)
        self.missing_value_count += sum(
            1 for value in values if bool(value["missing_mask"])
        )
        self.stale_value_count += sum(
            1 for value in values if bool(value["staleness_mask"])
        )
        self.quality_blocked_value_count += sum(
            1 for value in values if bool(value["quality_blocked_mask"])
        )
        self.source_tables.add(str(payload["source_table"]))
        self.min_event_at, self.max_event_at = _updated_bounds(
            self.min_event_at, self.max_event_at, str(payload["event_at"])
        )
        self.min_available_at, self.max_available_at = _updated_bounds(
            self.min_available_at,
            self.max_available_at,
            str(payload["available_at"]),
        )

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
            "compressed_sha256": _file_sha256(self.path),
            "content_sha256": f"sha256:{self._content_digest.hexdigest()}",
            "compressed_bytes": self.path.stat().st_size,
            "row_count": self.row_count,
            "feature_value_count": self.feature_value_count,
            "missing_value_count": self.missing_value_count,
            "stale_value_count": self.stale_value_count,
            "quality_blocked_value_count": self.quality_blocked_value_count,
            "source_tables": sorted(self.source_tables),
            "min_event_at": self.min_event_at,
            "max_event_at": self.max_event_at,
            "min_available_at": self.min_available_at,
            "max_available_at": self.max_available_at,
        }


class _ShardWriterRegistry:
    def __init__(self, *, staging: Path, compression_level: int) -> None:
        self._staging = staging
        self._compression_level = compression_level
        self._writers: dict[tuple[DatasetId, int], _ShardWriter] = {}

    def get(self, dataset_id: DatasetId, year: int) -> _ShardWriter:
        key = (dataset_id, year)
        writer = self._writers.get(key)
        if writer is None:
            writer = _ShardWriter(
                path=(
                    self._staging
                    / dataset_id
                    / f"year={year:04d}.jsonl.gz"
                ),
                dataset_id=dataset_id,
                year=year,
                compression_level=self._compression_level,
            )
            self._writers[key] = writer
        return writer

    def for_dataset(self, dataset_id: DatasetId) -> tuple[_ShardWriter, ...]:
        return tuple(
            writer
            for (candidate_dataset_id, _), writer in sorted(
                self._writers.items(), key=lambda item: item[0]
            )
            if candidate_dataset_id == dataset_id
        )

    def close_all(self) -> None:
        for writer in self._writers.values():
            writer.close()


def _dataset_records(
    manifest: FeatureEligibilityManifest,
) -> dict[DatasetId, tuple[FeatureEligibilityRecord, ...]]:
    records = tuple(
        record
        for record in manifest.records
        if record.is_numeric_feature
    )
    return {
        "core_long_history": tuple(
            record
            for record in records
            if record.table_name in _CORE_TABLES
            and record.eligibility_status == "formal_backfill"
        ),
        "all_field_enriched": tuple(
            record
            for record in records
            if record.eligibility_status in _FORMAL_STATUSES
        ),
        "research_shadow_all_fields": tuple(
            record
            for record in records
            if record.eligibility_status in _SHADOW_STATUSES
        ),
    }


def _feature_value_payload(
    record: FeatureEligibilityRecord,
    *,
    raw_value: object,
    decision: datetime,
    available_at: datetime,
    quality: str,
    derived_value: _DerivedFeatureValue | None,
) -> dict[str, Any]:
    value_int = (
        _scaled_decimal_integer(
            derived_value.value_decimal, scale=record.scale
        )
        if derived_value is not None
        else _scaled_integer(raw_value, scale=record.scale)
    )
    age_days = max(0, (decision.date() - available_at.date()).days)
    quality_blocked = any(
        token in quality.casefold() for token in _BAD_QUALITY_TOKENS
    )
    hash_payload: dict[str, Any] = {
        "feature_id": record.feature_id,
        "scale": record.scale,
        "record_hash": record.record_hash,
    }
    if derived_value is None:
        hash_payload["raw_text"] = None if raw_value is None else str(raw_value)
    else:
        hash_payload.update(
            {
                "derived_value_int": value_int,
                "derivation_hash": derived_value.derivation_hash,
                "derivation_blocker": derived_value.blocker,
            }
        )
    source_value_hash = _sha256_json(hash_payload)
    payload: dict[str, Any] = {
        "feature_id": record.feature_id,
        "value_int": value_int,
        "scale": record.scale,
        "unit": record.unit,
        "eligibility_status": record.eligibility_status,
        "missing_mask": value_int is None,
        "staleness_mask": age_days > record.staleness_days,
        "stale_after_days": record.staleness_days,
        "age_days_at_publication": age_days,
        "quality_blocked_mask": quality_blocked,
        "formal_training_eligible": (
            record.formal_training_eligible
            and not quality_blocked
            and value_int is not None
        ),
        "source_value_hash": source_value_hash,
    }
    if derived_value is not None:
        payload["derivation"] = {
            "method": "causal_wilder_prefix",
            "period": derived_value.period,
            "input_columns": list(derived_value.input_columns),
            "causal_prefix_only": True,
            "usable_from": available_at.isoformat(),
            "blocker": derived_value.blocker,
            "derivation_hash": derived_value.derivation_hash,
            "raw_feature_value_ignored": True,
        }
    return payload


def _availability_for_status(
    *,
    status: FeatureEligibilityStatus,
    event_at: datetime,
    available_at: datetime | None,
    announced_at: datetime | None,
    first_seen_at: datetime | None,
) -> datetime | None:
    candidates = tuple(
        value
        for value in (available_at, announced_at, first_seen_at)
        if value is not None
    )
    if status == "first_seen_only":
        if available_at is None and first_seen_at is None:
            return None
        return max(candidates)
    return max(candidates) if candidates else event_at


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA query_only").fetchone() != (1,):
            raise RuntimeError("SQLite query_only could not be enabled")
        return connection
    except Exception:
        connection.close()
        raise


def _eligibility_payload(manifest: FeatureEligibilityManifest) -> dict[str, Any]:
    return {
        "schema_version": "ml-feature-eligibility-matrix.v1",
        "manifest_hash": manifest.manifest_hash,
        "inspected_tables": list(manifest.inspected_tables),
        "missing_tables": list(manifest.missing_tables),
        "unknown_columns_fail_closed": True,
        "records": [asdict(record) for record in manifest.records],
    }


def _feature_manifest_payload(
    record: FeatureEligibilityRecord,
) -> dict[str, Any]:
    is_causal_atr_adx = record.feature_id in {
        "technical_indicators.ATR",
        "technical_indicators.ADX",
    }
    payload: dict[str, Any] = {
        "feature_id": record.feature_id,
        "table_name": record.table_name,
        "column_name": record.column_name,
        "family": record.family,
        "source_id": (
            "derived:daily_prices.ohlc"
            if is_causal_atr_adx
            else record.source_id
        ),
        "unit": record.unit,
        "scale": record.scale,
        "eligibility_status": record.eligibility_status,
        "staleness_days": record.staleness_days,
        "record_hash": record.record_hash,
    }
    if is_causal_atr_adx:
        payload["derivation_policy"] = {
            "method": "causal_wilder_prefix",
            "period": 14,
            "source": "daily_prices.same_symbol_ordered_ohlc",
            "availability": "event_close_for_next_decision",
            "raw_null_or_existing_value_used": False,
            "warmup_fail_closed": True,
        }
    return payload


def _blocked_table_result(
    table_name: str, *diagnostics: str
) -> dict[str, Any]:
    return {
        "table_name": table_name,
        "family": table_family(table_name),
        "state": "blocked",
        "source_row_count": 0,
        "emitted_row_count": 0,
        "blocked_future_row_count": 0,
        "blocked_missing_availability_row_count": 0,
        "filtered_year_row_count": 0,
        "filtered_history_row_count": 0,
        "invalid_event_row_count": 0,
        "diagnostics": list(diagnostics),
    }


def _decision_datetime(value: str) -> datetime:
    text = str(value).strip()
    if len(text) == 10:
        return datetime.combine(
            date.fromisoformat(text), _DECISION_TIME, tzinfo=_TAIPEI
        )
    parsed = _parse_datetime(text)
    return parsed.astimezone(_TAIPEI)


def _optional_date(value: object) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return _date_value(str(value))
    except ValueError:
        return None


def _date_value(value: str) -> date:
    text = str(value).strip()
    if len(text) >= 8 and text[:8].isdigit():
        compact = text[:8]
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    return date.fromisoformat(text[:10])


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_TAIPEI)


def _optional_datetime(value: object) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if (len(text) == 8 and text.isdigit()) or (
        len(text) == 10 and text[4] == "-" and text[7] == "-"
    ):
        return datetime.combine(_date_value(text), _END_OF_DAY, tzinfo=_TAIPEI)
    try:
        return _parse_datetime(text)
    except ValueError:
        return None


def _row_optional_datetime(
    row: sqlite3.Row, alias: str
) -> datetime | None:
    return (
        _optional_datetime(row[alias])
        if alias in row.keys()
        else None
    )


def _row_optional_text(row: sqlite3.Row, alias: str) -> str | None:
    if alias not in row.keys() or row[alias] is None:
        return None
    text = str(row[alias]).strip()
    return text or None


def _required_identity(value: object) -> str:
    if value is None or not str(value).strip():
        return "<missing>"
    return str(value).strip()


def _scaled_integer(value: object, *, scale: int) -> int | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text.casefold() in {"", "-", "--", "nan", "none", "null"}:
        return None
    try:
        decimal_value = Decimal(text)
        if not decimal_value.is_finite():
            return None
        return int(
            (decimal_value * Decimal(scale)).to_integral_value(
                rounding=ROUND_HALF_EVEN
            )
        )
    except (InvalidOperation, ValueError):
        return None


def _scaled_decimal_integer(
    value: Decimal | None, *, scale: int
) -> int | None:
    if value is None or not value.is_finite():
        return None
    return int(
        (value * Decimal(scale)).to_integral_value(rounding=ROUND_HALF_EVEN)
    )


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text.casefold() in {"", "-", "--", "nan", "none", "null"}:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _atr_adx_input_column_groups(
    *, table_name: str, column_names: set[str]
) -> tuple[tuple[str, str, str], ...]:
    if table_name != "daily_prices":
        return ()
    candidates = (
        ("最高價", "最低價", "收盤價"),
        ("High", "Low", "Close"),
    )
    return tuple(
        candidate for candidate in candidates if set(candidate) <= column_names
    )


def _select_technical_input(
    *,
    row: sqlite3.Row,
    input_groups: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[str, str, str], object, object, object] | None:
    fallback: tuple[
        tuple[str, str, str], object, object, object
    ] | None = None
    for group_index, columns in enumerate(input_groups):
        values = (
            row[f"__derive_{group_index}_high"],
            row[f"__derive_{group_index}_low"],
            row[f"__derive_{group_index}_close"],
        )
        candidate = (columns, values[0], values[1], values[2])
        if fallback is None:
            fallback = candidate
        parsed = tuple(_optional_decimal(value) for value in values)
        if all(value is not None for value in parsed):
            return candidate
    return fallback


def _normalized_texts(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted({str(value).strip() for value in values if str(value).strip()})
    )


def _normalized_years(values: Sequence[int]) -> tuple[int, ...]:
    normalized: set[int] = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("years must contain integers")
        if value < 1900 or value > 9999:
            raise ValueError("years must be between 1900 and 9999")
        normalized.add(value)
    return tuple(sorted(normalized))


def _sql_year_expression(column: str) -> str:
    quoted = _quote_identifier(column)
    return (
        "CAST(SUBSTR(REPLACE(REPLACE(CAST("
        f"{quoted} AS TEXT), '-', ''), '/', ''), 1, 4) AS INTEGER)"
    )


def _placeholders(count: int) -> str:
    if isinstance(count, bool) or count < 1:
        raise ValueError("placeholder count must be positive")
    return ",".join("?" for _ in range(count))


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _pragma_int(connection: sqlite3.Connection, pragma: str) -> int:
    row = connection.execute(f"PRAGMA {pragma}").fetchone()
    if row is None or isinstance(row[0], bool) or not isinstance(row[0], int):
        raise RuntimeError(f"SQLite PRAGMA {pragma} returned invalid value")
    return row[0]


def _updated_bounds(
    minimum: str | None, maximum: str | None, value: str
) -> tuple[str, str]:
    return (
        value if minimum is None or value < minimum else minimum,
        value if maximum is None or value > maximum else maximum,
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_json(payload: object) -> str:
    return f"sha256:{_sha256_hex(_canonical_json(payload))}"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    with path.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_json(temporary, payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


def _safe_remove_staging(path: Path, output_root: Path) -> None:
    resolved = path.resolve()
    root = output_root.resolve()
    if resolved.parent != root or not resolved.name.startswith(".pit-shards-"):
        raise RuntimeError(f"refusing to remove unexpected staging path: {resolved}")
    shutil.rmtree(resolved)
