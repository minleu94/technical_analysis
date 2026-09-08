"""全欄位、唯讀、PIT-safe 的 SQLite ML snapshot provider。

Provider 以來源資料的聯集輸出 observation，不做 inner join，因此短歷史
flow／broker pack 不會截短長歷史價格資料。所有 SQLite 連線固定使用
``mode=ro`` 與 ``PRAGMA query_only=ON``；缺 table、空 table、缺 availability
或未審欄位只會產生降級診斷，不會建立 schema 或寫入 ``DATA_ROOT``。
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Literal
from zoneinfo import ZoneInfo

from ml_module.feature_eligibility import (
    ALL_FIELD_SOURCE_TABLES,
    FeatureEligibilityManifest,
    FeatureEligibilityRecord,
    FeatureEligibilityStatus,
    build_feature_eligibility_manifest,
    table_family,
)
from data_module.statement_report_basis_contract import (
    resolve_statement_report_basis,
)


TableAvailabilityState = Literal["available", "degraded", "empty", "missing", "blocked"]
FamilyAvailabilityState = Literal["available", "degraded", "empty", "missing", "blocked"]

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


@dataclass(frozen=True)
class PITFeatureValue:
    """可持久化的 int/scale 特徵值與明確 mask。"""

    feature_id: str
    value_int: int | None
    scale: int
    unit: str
    eligibility_status: FeatureEligibilityStatus
    missing_mask: bool
    staleness_mask: bool
    age_days: int
    formal_training_eligible: bool
    source_value_hash: str

    def __post_init__(self) -> None:
        if not self.feature_id.strip() or not self.unit.strip():
            raise ValueError("feature_id and unit are required")
        if isinstance(self.scale, bool) or not isinstance(self.scale, int) or self.scale <= 0:
            raise ValueError("scale must be a positive integer")
        if isinstance(self.value_int, bool) or not isinstance(
            self.value_int, (int, type(None))
        ):
            raise TypeError("PIT feature values must persist as integer units or missing")
        if self.missing_mask != (self.value_int is None):
            raise ValueError("missing_mask must match value_int")
        if (
            isinstance(self.age_days, bool)
            or not isinstance(self.age_days, int)
            or self.age_days < 0
        ):
            raise ValueError("age_days must be a non-negative integer")
        if not self.source_value_hash.startswith("sha256:"):
            raise ValueError("source_value_hash must be a sha256 identity")
        if self.eligibility_status == "research_shadow" and self.formal_training_eligible:
            raise ValueError("research_shadow values cannot be formal-training eligible")


@dataclass(frozen=True)
class PITFeatureObservation:
    """一筆來源 row 的 PIT observation；不同來源不要求同日對齊。"""

    source_table: str
    family: str
    entity_id: str
    event_at: str
    available_at: str
    announced_at: str | None
    first_seen_at: str | None
    revision_id: str | None
    quality: str
    values: tuple[PITFeatureValue, ...]
    source_row_hash: str
    report_basis: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_table,
                self.family,
                self.entity_id,
                self.event_at,
                self.available_at,
                self.quality,
            )
        ):
            raise ValueError("PIT observation text fields must be non-empty")
        if not self.values:
            raise ValueError("PIT observation values are required")
        feature_ids = tuple(value.feature_id for value in self.values)
        if tuple(sorted(feature_ids)) != feature_ids or len(feature_ids) != len(
            set(feature_ids)
        ):
            raise ValueError("PIT observation feature ids must be unique and ordered")
        if not self.source_row_hash.startswith("sha256:"):
            raise ValueError("source_row_hash must be a sha256 identity")
        if self.source_table == "fundamental_statement_items":
            basis = self.report_basis
            if basis is None or not basis.strip():
                raise ValueError("statement report_basis is missing")
            if basis not in _REPORT_BASES:
                raise ValueError("statement report_basis is unsupported")
            object.__setattr__(self, "report_basis", basis)
        elif self.report_basis is not None:
            raise ValueError("report_basis is only valid for statement items")


@dataclass(frozen=True)
class SourceTableAvailability:
    table_name: str
    family: str
    state: TableAvailabilityState
    row_count: int
    feature_value_count: int
    missing_value_count: int
    stale_value_count: int
    blocked_future_rows: int
    blocked_missing_availability_rows: int
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        counts = (
            self.row_count,
            self.feature_value_count,
            self.missing_value_count,
            self.stale_value_count,
            self.blocked_future_rows,
            self.blocked_missing_availability_rows,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValueError("availability counts must be non-negative integers")


@dataclass(frozen=True)
class FeatureFamilyAvailability:
    family: str
    state: FamilyAvailabilityState
    tables: tuple[SourceTableAvailability, ...]
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.family.strip() or not self.tables:
            raise ValueError("family and table availability are required")
        if any(table.family != self.family for table in self.tables):
            raise ValueError("table availability family mismatch")


@dataclass(frozen=True)
class AllFieldPITSnapshot:
    decision_at: str
    history_start_date: str
    core_feature_as_of_date: str | None
    observations: tuple[PITFeatureObservation, ...]
    family_availability: tuple[FeatureFamilyAvailability, ...]
    eligibility_manifest_hash: str
    source_fingerprint: str
    snapshot_hash: str
    query_count: int
    source_tables: tuple[str, ...] = ALL_FIELD_SOURCE_TABLES
    query_only: bool = True
    shadow_only: bool = True
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        decision = datetime.fromisoformat(self.decision_at)
        if decision.tzinfo is None:
            raise ValueError("decision_at must include timezone")
        if date.fromisoformat(self.history_start_date) > decision.date():
            raise ValueError("history_start_date must not exceed decision_at")
        if self.core_feature_as_of_date is not None and (
            date.fromisoformat(self.core_feature_as_of_date) >= decision.date()
        ):
            raise ValueError("core feature as-of must be before decision date")
        if self.source_tables != ALL_FIELD_SOURCE_TABLES:
            raise ValueError("all-field source table contract mismatch")
        if not self.query_only or not self.shadow_only or self.production_action_allowed:
            raise ValueError("all-field snapshot must remain read-only and shadow-only")
        if isinstance(self.query_count, bool) or self.query_count < 0:
            raise ValueError("query_count must be a non-negative integer")
        for identity in (
            self.eligibility_manifest_hash,
            self.source_fingerprint,
            self.snapshot_hash,
        ):
            if not identity.startswith("sha256:"):
                raise ValueError("snapshot identities must use sha256")


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


class MLAllFieldSnapshotProvider:
    """讀取全欄位 PIT snapshot，不接正式決策或任何寫入路徑。"""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)

    def inspect_eligibility(self) -> FeatureEligibilityManifest:
        """唯讀掃描目前 schema；每個已存在欄位必有 disposition。"""

        with closing(self._connect()) as connection:
            return build_feature_eligibility_manifest(connection)

    def load(
        self,
        *,
        decision_at: str,
        history_start_date: str,
        symbols: tuple[str, ...],
        industry_index_names: tuple[str, ...] = (),
    ) -> AllFieldPITSnapshot:
        source_stat_before = self.database_path.stat()
        decision = _decision_datetime(decision_at)
        history_start = _date_value(history_start_date)
        if history_start > decision.date():
            raise ValueError("history_start_date must not exceed decision_at")
        normalized_symbols = _normalized_texts(symbols, field_name="symbols")
        normalized_industries = tuple(
            sorted(
                {
                    str(value).strip()
                    for value in industry_index_names
                    if str(value).strip()
                }
            )
        )

        query_count = 0
        observations: list[PITFeatureObservation] = []
        table_availability: list[SourceTableAvailability] = []
        with closing(self._connect()) as connection:
            data_version_before = _pragma_int(connection, "data_version")
            manifest = build_feature_eligibility_manifest(connection)
            query_count += 1
            for table_name in ALL_FIELD_SOURCE_TABLES:
                if table_name in manifest.missing_tables:
                    table_availability.append(
                        _missing_table_availability(table_name)
                    )
                    continue
                table_records = manifest.for_table(table_name)
                table_result, table_rows = self._load_table(
                    connection,
                    table_name=table_name,
                    records=table_records,
                    decision=decision,
                    history_start=history_start,
                    symbols=normalized_symbols,
                    industry_index_names=normalized_industries,
                )
                query_count += 1
                table_availability.append(table_result)
                observations.extend(table_rows)
            data_version_after = _pragma_int(connection, "data_version")
            if data_version_after != data_version_before:
                raise RuntimeError("SQLite source data_version changed during snapshot load")

        source_stat_after = self.database_path.stat()
        if (
            source_stat_after.st_size,
            source_stat_after.st_mtime_ns,
        ) != (
            source_stat_before.st_size,
            source_stat_before.st_mtime_ns,
        ):
            raise RuntimeError("SQLite source changed during snapshot load")

        ordered_observations = tuple(
            sorted(
                observations,
                key=lambda row: (
                    row.family,
                    row.source_table,
                    row.entity_id,
                    row.event_at,
                    row.source_row_hash,
                ),
            )
        )
        ordered_table_availability = tuple(
            sorted(table_availability, key=lambda row: row.table_name)
        )
        family_availability = _family_availability(ordered_table_availability)
        core_dates = [
            _date_value(row.event_at)
            for row in ordered_observations
            if row.source_table == "daily_prices"
        ]
        core_as_of = max(core_dates).isoformat() if core_dates else None
        source_fingerprint = _source_fingerprint(
            manifest=manifest,
            source_stat=source_stat_before,
        )
        snapshot_payload = {
            "decision_at": decision.isoformat(),
            "history_start_date": history_start.isoformat(),
            "core_feature_as_of_date": core_as_of,
            "observation_hashes": [row.source_row_hash for row in ordered_observations],
            "family_availability": [asdict(row) for row in family_availability],
            "eligibility_manifest_hash": manifest.manifest_hash,
        }
        snapshot_hash = _sha256(_canonical_json(snapshot_payload))
        return AllFieldPITSnapshot(
            decision_at=decision.isoformat(),
            history_start_date=history_start.isoformat(),
            core_feature_as_of_date=core_as_of,
            observations=ordered_observations,
            family_availability=family_availability,
            eligibility_manifest_hash=manifest.manifest_hash,
            source_fingerprint=source_fingerprint,
            snapshot_hash=snapshot_hash,
            query_count=query_count,
        )

    def _load_table(
        self,
        connection: sqlite3.Connection,
        *,
        table_name: str,
        records: tuple[FeatureEligibilityRecord, ...],
        decision: datetime,
        history_start: date,
        symbols: tuple[str, ...],
        industry_index_names: tuple[str, ...],
    ) -> tuple[SourceTableAvailability, tuple[PITFeatureObservation, ...]]:
        family = table_family(table_name)
        runtime = _RUNTIME_POLICIES[table_name]
        identity_columns = (
            *runtime.identity_columns,
            *tuple(
                column
                for column in runtime.optional_identity_columns
                if column in {record.column_name for record in records}
            ),
        )
        columns = {record.column_name for record in records}
        feature_records = tuple(
            sorted(
                (record for record in records if record.is_numeric_feature),
                key=lambda record: record.feature_id,
            )
        )
        unreviewed = tuple(
            record for record in records if record.eligibility_status == "unreviewed"
        )
        if not records:
            return (
                SourceTableAvailability(
                    table_name=table_name,
                    family=family,
                    state="blocked",
                    row_count=0,
                    feature_value_count=0,
                    missing_value_count=0,
                    stale_value_count=0,
                    blocked_future_rows=0,
                    blocked_missing_availability_rows=0,
                    diagnostics=("schema_has_no_columns",),
                ),
                (),
            )
        time_policy = records[0].time_policy
        required_columns = {
            time_policy.event_at,
            *(column for column in identity_columns if column),
        }
        missing_required = tuple(sorted(required_columns - columns))
        if missing_required or not feature_records:
            diagnostic_items = [
                f"missing_required_column:{column}" for column in missing_required
            ]
            if not feature_records:
                diagnostic_items.append("no_numeric_eligible_features")
            diagnostics = tuple(diagnostic_items)
            return (
                SourceTableAvailability(
                    table_name=table_name,
                    family=family,
                    state="blocked",
                    row_count=0,
                    feature_value_count=0,
                    missing_value_count=0,
                    stale_value_count=0,
                    blocked_future_rows=0,
                    blocked_missing_availability_rows=0,
                    diagnostics=diagnostics,
                ),
                (),
            )

        metadata_columns = tuple(
            column
            for column in (
                *identity_columns,
                time_policy.event_at,
                time_policy.announced_at,
                time_policy.available_at,
                time_policy.first_seen_at,
                time_policy.revision_id,
                "quality" if "quality" in columns else None,
                "source" if "source" in columns else None,
                "source_version" if "source_version" in columns else None,
            )
            if column is not None and column in columns
        )
        metadata_columns = tuple(dict.fromkeys(metadata_columns))
        select_parts = [_quote_identifier(column) for column in metadata_columns]
        feature_aliases: dict[str, str] = {}
        for index, record in enumerate(feature_records):
            alias = f"__feature_{index}"
            feature_aliases[record.column_name] = alias
            select_parts.append(
                f"CAST({_quote_identifier(record.column_name)} AS TEXT) "
                f"AS {_quote_identifier(alias)}"
            )
        query = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {_quote_identifier(table_name)}"
        )
        parameters: tuple[str, ...] = ()
        if runtime.stock_column is not None:
            query += (
                f" WHERE {_quote_identifier(runtime.stock_column)} "
                f"IN ({_placeholders(normalized_values=symbols)})"
            )
            parameters = symbols
        elif runtime.industry_column is not None and industry_index_names:
            query += (
                f" WHERE {_quote_identifier(runtime.industry_column)} "
                f"IN ({_placeholders(normalized_values=industry_index_names)})"
            )
            parameters = industry_index_names

        connection.row_factory = sqlite3.Row
        raw_rows = connection.execute(query, parameters).fetchall()
        observations: list[PITFeatureObservation] = []
        blocked_future = 0
        blocked_missing_availability = 0
        for row in raw_rows:
            event_date = _optional_date(row[time_policy.event_at])
            if event_date is None or event_date < history_start:
                continue
            if event_date >= decision.astimezone(_TAIPEI).date():
                blocked_future += 1
                continue
            available, announced, first_seen = _row_availability(
                row,
                event_date=event_date,
                status=feature_records[0].eligibility_status,
                available_column=time_policy.available_at,
                announced_column=time_policy.announced_at,
                first_seen_column=time_policy.first_seen_at,
            )
            if available is None:
                blocked_missing_availability += 1
                continue
            if available > decision:
                blocked_future += 1
                continue

            quality = _row_text(row, "quality") or "not_provided"
            entity_id = "|".join(
                _row_text(row, column) or "<missing>"
                for column in identity_columns
            )
            report_basis: str | None = None
            if table_name == "fundamental_statement_items":
                report_basis = resolve_statement_report_basis(
                    explicit_value=_row_text(row, "report_basis"),
                    explicit_column_present="report_basis" in columns,
                    source=_row_text(row, "source"),
                    source_version=_row_text(row, "source_version"),
                )
            age_days = max(0, (decision.date() - available.astimezone(_TAIPEI).date()).days)
            values = tuple(
                _feature_value(
                    record,
                    raw_value=row[feature_aliases[record.column_name]],
                    age_days=age_days,
                    quality=quality,
                )
                for record in feature_records
            )
            revision_id = (
                _row_text(row, time_policy.revision_id)
                if time_policy.revision_id is not None
                else None
            )
            row_payload = {
                "source_table": table_name,
                "family": family,
                "entity_id": entity_id,
                "report_basis": report_basis,
                "event_at": _event_datetime(event_date).isoformat(),
                "available_at": available.isoformat(),
                "announced_at": announced.isoformat() if announced else None,
                "first_seen_at": first_seen.isoformat() if first_seen else None,
                "revision_id": revision_id,
                "quality": quality,
                "values": [
                    {
                        "feature_id": value.feature_id,
                        "value_int": value.value_int,
                        "scale": value.scale,
                        "missing_mask": value.missing_mask,
                        "staleness_mask": value.staleness_mask,
                        "formal_training_eligible": value.formal_training_eligible,
                        "source_value_hash": value.source_value_hash,
                    }
                    for value in values
                ],
            }
            observations.append(
                PITFeatureObservation(
                    source_table=table_name,
                    family=family,
                    entity_id=entity_id,
                    event_at=_event_datetime(event_date).isoformat(),
                    available_at=available.isoformat(),
                    announced_at=announced.isoformat() if announced else None,
                    first_seen_at=first_seen.isoformat() if first_seen else None,
                    revision_id=revision_id,
                    quality=quality,
                    values=values,
                    source_row_hash=_sha256(_canonical_json(row_payload)),
                    report_basis=report_basis,
                )
            )

        ordered = tuple(
            sorted(
                observations,
                key=lambda item: (
                    item.entity_id,
                    item.event_at,
                    item.source_row_hash,
                ),
            )
        )
        feature_count = sum(len(row.values) for row in ordered)
        missing_count = sum(
            1 for row in ordered for value in row.values if value.missing_mask
        )
        stale_count = sum(
            1 for row in ordered for value in row.values if value.staleness_mask
        )
        degradation_diagnostics = [
            *(f"unreviewed_column:{record.column_name}" for record in unreviewed),
        ]
        table_diagnostics = list(degradation_diagnostics)
        if blocked_future:
            table_diagnostics.append(f"future_availability_blocked:{blocked_future}")
        if blocked_missing_availability:
            diagnostic = (
                f"missing_availability_blocked:{blocked_missing_availability}"
            )
            table_diagnostics.append(diagnostic)
            degradation_diagnostics.append(diagnostic)
        if not ordered:
            state: TableAvailabilityState = (
                "blocked"
                if blocked_future or blocked_missing_availability
                else "empty"
            )
        elif degradation_diagnostics:
            state = "degraded"
        else:
            state = "available"
        return (
            SourceTableAvailability(
                table_name=table_name,
                family=family,
                state=state,
                row_count=len(ordered),
                feature_value_count=feature_count,
                missing_value_count=missing_count,
                stale_value_count=stale_count,
                blocked_future_rows=blocked_future,
                blocked_missing_availability_rows=blocked_missing_availability,
                diagnostics=tuple(table_diagnostics),
            ),
            ordered,
        )

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA query_only").fetchone() != (1,):
                raise RuntimeError("SQLite query_only could not be enabled")
            return connection
        except Exception:
            connection.close()
            raise


def _feature_value(
    record: FeatureEligibilityRecord,
    *,
    raw_value: object,
    age_days: int,
    quality: str,
) -> PITFeatureValue:
    value_int = _scaled_integer(raw_value, scale=record.scale)
    quality_allowed = not any(
        token in quality.casefold() for token in _BAD_QUALITY_TOKENS
    )
    payload = {
        "feature_id": record.feature_id,
        "raw_text": None if raw_value is None else str(raw_value),
        "scale": record.scale,
        "record_hash": record.record_hash,
    }
    return PITFeatureValue(
        feature_id=record.feature_id,
        value_int=value_int,
        scale=record.scale,
        unit=record.unit,
        eligibility_status=record.eligibility_status,
        missing_mask=value_int is None,
        staleness_mask=age_days > record.staleness_days,
        age_days=age_days,
        formal_training_eligible=record.formal_training_eligible and quality_allowed,
        source_value_hash=_sha256(_canonical_json(payload)),
    )


def _row_availability(
    row: sqlite3.Row,
    *,
    event_date: date,
    status: FeatureEligibilityStatus,
    available_column: str | None,
    announced_column: str | None,
    first_seen_column: str | None,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    available = (
        _optional_datetime(row[available_column], date_only_end_of_day=True)
        if available_column is not None
        else None
    )
    announced = (
        _optional_datetime(row[announced_column], date_only_end_of_day=True)
        if announced_column is not None
        else None
    )
    first_seen = (
        _optional_datetime(row[first_seen_column], date_only_end_of_day=True)
        if first_seen_column is not None
        else None
    )
    candidates = [value for value in (available, announced, first_seen) if value is not None]
    if status == "first_seen_only":
        if available is None and first_seen is None:
            return None, announced, first_seen
        return max(candidates), announced, first_seen
    if candidates:
        return max(candidates), announced, first_seen
    return _event_datetime(event_date), announced, first_seen


def _family_availability(
    tables: tuple[SourceTableAvailability, ...],
) -> tuple[FeatureFamilyAvailability, ...]:
    grouped: dict[str, list[SourceTableAvailability]] = {}
    for table in tables:
        grouped.setdefault(table.family, []).append(table)
    results: list[FeatureFamilyAvailability] = []
    for family, family_tables in grouped.items():
        ordered = tuple(sorted(family_tables, key=lambda table: table.table_name))
        states = {table.state for table in ordered}
        if states == {"missing"}:
            state: FamilyAvailabilityState = "missing"
        elif states <= {"empty", "missing"} and "empty" in states:
            state = "empty"
        elif states == {"blocked"}:
            state = "blocked"
        elif states == {"available"}:
            state = "available"
        else:
            state = "degraded"
        diagnostics = tuple(
            f"{table.table_name}:{diagnostic}"
            for table in ordered
            for diagnostic in table.diagnostics
        )
        results.append(
            FeatureFamilyAvailability(
                family=family,
                state=state,
                tables=ordered,
                diagnostics=diagnostics,
            )
        )
    return tuple(sorted(results, key=lambda result: result.family))


def _missing_table_availability(table_name: str) -> SourceTableAvailability:
    return SourceTableAvailability(
        table_name=table_name,
        family=table_family(table_name),
        state="missing",
        row_count=0,
        feature_value_count=0,
        missing_value_count=0,
        stale_value_count=0,
        blocked_future_rows=0,
        blocked_missing_availability_rows=0,
        diagnostics=("optional_source_table_missing",),
    )


def _source_fingerprint(
    *,
    manifest: FeatureEligibilityManifest,
    source_stat: object,
) -> str:
    payload = {
        "eligibility_manifest_hash": manifest.manifest_hash,
        "size": getattr(source_stat, "st_size"),
        "mtime_ns": getattr(source_stat, "st_mtime_ns"),
    }
    return _sha256(_canonical_json(payload))


def _scaled_integer(value: object, *, scale: int) -> int | None:
    """SQLite numeric → Decimal → int 的隔離轉換邊界。"""

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


def _decision_datetime(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("decision_at is required")
    if len(text) == 10:
        return datetime.combine(date.fromisoformat(text), _DECISION_TIME, tzinfo=_TAIPEI)
    parsed = _parse_datetime(text)
    return parsed.astimezone(_TAIPEI)


def _optional_datetime(
    value: object, *, date_only_end_of_day: bool
) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if _looks_like_date_only(text):
        day = _date_value(text)
        clock = _END_OF_DAY if date_only_end_of_day else _MARKET_CLOSE_TIME
        return datetime.combine(day, clock, tzinfo=_TAIPEI)
    try:
        return _parse_datetime(text)
    except ValueError:
        return None


def _parse_datetime(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        # SQLite CURRENT_TIMESTAMP 為 UTC；未知 naive timestamp 採較保守的 UTC。
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_TAIPEI)


def _event_datetime(value: date) -> datetime:
    return datetime.combine(value, _MARKET_CLOSE_TIME, tzinfo=_TAIPEI)


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


def _looks_like_date_only(value: str) -> bool:
    text = value.strip()
    return (len(text) == 8 and text.isdigit()) or (
        len(text) == 10 and text[4] == "-" and text[7] == "-"
    )


def _row_text(row: sqlite3.Row, column_name: str) -> str | None:
    if column_name not in row.keys() or row[column_name] is None:
        return None
    text = str(row[column_name]).strip()
    return text or None


def _normalized_texts(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    result = tuple(
        sorted({str(value).strip() for value in values if str(value).strip()})
    )
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _placeholders(*, normalized_values: tuple[str, ...]) -> str:
    if not normalized_values:
        raise ValueError("SQL placeholder values must not be empty")
    return ",".join("?" for _ in normalized_values)


def _pragma_int(connection: sqlite3.Connection, pragma: str) -> int:
    row = connection.execute(f"PRAGMA {pragma}").fetchone()
    if row is None or isinstance(row[0], bool) or not isinstance(row[0], int):
        raise RuntimeError(f"SQLite PRAGMA {pragma} returned an invalid value")
    return row[0]


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
