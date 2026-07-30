"""全欄位 ML eligibility 契約與 SQLite schema 稽核。

本模組只檢查呼叫端提供的 SQLite connection，不建立 table、不寫資料，
也不會把新欄位自動視為可訓練特徵。未知欄位一律 ``unreviewed``，
由下游以 fail-closed 方式處理。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import sqlite3
from typing import Literal


FeatureEligibilityStatus = Literal[
    "formal_backfill",
    "first_seen_only",
    "research_shadow",
    "availability_only",
    "excluded_identifier",
    "excluded_leakage",
    "blocked_no_provenance",
    "unreviewed",
]

ELIGIBILITY_STATUSES: frozenset[str] = frozenset(
    {
        "formal_backfill",
        "first_seen_only",
        "research_shadow",
        "availability_only",
        "excluded_identifier",
        "excluded_leakage",
        "blocked_no_provenance",
        "unreviewed",
    }
)

ALL_FIELD_SOURCE_TABLES: tuple[str, ...] = (
    "daily_prices",
    "technical_indicators",
    "market_indices",
    "industry_indices",
    "fundamental_monthly_revenues",
    "fundamental_statement_items",
    "fundamental_valuation_metrics",
    "institutional_flows",
    "credit_transactions",
    "tdcc_shareholding",
    "broker_flows",
)


@dataclass(frozen=True)
class TimeFieldPolicy:
    """單一來源 table 的 PIT 時間欄位政策。"""

    event_at: str
    announced_at: str | None
    available_at: str | None
    first_seen_at: str | None
    effective_at: str | None
    revision_id: str | None
    decision_time_policy: str = "08:30 Asia/Taipei; date-only availability is end-of-day"

    def __post_init__(self) -> None:
        if not self.event_at.strip() or not self.decision_time_policy.strip():
            raise ValueError("event_at and decision_time_policy are required")


@dataclass(frozen=True)
class FeatureEligibilityRecord:
    """一個 SQLite ``table.column`` 的完整治理 disposition。"""

    table_name: str
    column_name: str
    family: str
    source_id: str
    sqlite_declared_type: str
    canonical_dtype: str
    unit: str
    scale: int
    time_policy: TimeFieldPolicy
    missing_policy: str
    staleness_days: int
    revision_policy: str
    license_policy: str
    quality_policy: str
    eligibility_status: FeatureEligibilityStatus
    reason_code: str
    rule_version: str
    record_hash: str

    def __post_init__(self) -> None:
        required = (
            self.table_name,
            self.column_name,
            self.family,
            self.source_id,
            self.canonical_dtype,
            self.unit,
            self.missing_policy,
            self.revision_policy,
            self.license_policy,
            self.quality_policy,
            self.reason_code,
            self.rule_version,
            self.record_hash,
        )
        if any(not value.strip() for value in required):
            raise ValueError("feature eligibility text fields must be non-empty")
        if self.eligibility_status not in ELIGIBILITY_STATUSES:
            raise ValueError(f"invalid eligibility status: {self.eligibility_status}")
        if isinstance(self.scale, bool) or not isinstance(self.scale, int) or self.scale <= 0:
            raise ValueError("scale must be a positive integer")
        if (
            isinstance(self.staleness_days, bool)
            or not isinstance(self.staleness_days, int)
            or self.staleness_days < 0
        ):
            raise ValueError("staleness_days must be a non-negative integer")
        if not self.record_hash.startswith("sha256:"):
            raise ValueError("record_hash must be a sha256 identity")

    @property
    def feature_id(self) -> str:
        return f"{self.table_name}.{self.column_name}"

    @property
    def is_numeric_feature(self) -> bool:
        return self.canonical_dtype == "int" and self.eligibility_status in {
            "formal_backfill",
            "first_seen_only",
            "research_shadow",
        }

    @property
    def formal_training_eligible(self) -> bool:
        return self.canonical_dtype == "int" and self.eligibility_status in {
            "formal_backfill",
            "first_seen_only",
        }

    @classmethod
    def create(
        cls,
        *,
        table_name: str,
        column_name: str,
        family: str,
        source_id: str,
        sqlite_declared_type: str,
        canonical_dtype: str,
        unit: str,
        scale: int,
        time_policy: TimeFieldPolicy,
        missing_policy: str,
        staleness_days: int,
        revision_policy: str,
        license_policy: str,
        quality_policy: str,
        eligibility_status: FeatureEligibilityStatus,
        reason_code: str,
        rule_version: str = "all-field-eligibility.v1",
    ) -> "FeatureEligibilityRecord":
        identity_payload = {
            "table_name": table_name,
            "column_name": column_name,
            "family": family,
            "source_id": source_id,
            "sqlite_declared_type": sqlite_declared_type,
            "canonical_dtype": canonical_dtype,
            "unit": unit,
            "scale": scale,
            "time_policy": asdict(time_policy),
            "missing_policy": missing_policy,
            "staleness_days": staleness_days,
            "revision_policy": revision_policy,
            "license_policy": license_policy,
            "quality_policy": quality_policy,
            "eligibility_status": eligibility_status,
            "reason_code": reason_code,
            "rule_version": rule_version,
        }
        digest = hashlib.sha256(
            _canonical_json(identity_payload).encode("utf-8")
        ).hexdigest()
        return cls(
            table_name=table_name,
            column_name=column_name,
            family=family,
            source_id=source_id,
            sqlite_declared_type=sqlite_declared_type,
            canonical_dtype=canonical_dtype,
            unit=unit,
            scale=scale,
            time_policy=time_policy,
            missing_policy=missing_policy,
            staleness_days=staleness_days,
            revision_policy=revision_policy,
            license_policy=license_policy,
            quality_policy=quality_policy,
            eligibility_status=eligibility_status,
            reason_code=reason_code,
            rule_version=rule_version,
            record_hash=f"sha256:{digest}",
        )


@dataclass(frozen=True)
class FeatureEligibilityManifest:
    """SQLite schema 的完整、可重播 eligibility manifest。"""

    records: tuple[FeatureEligibilityRecord, ...]
    inspected_tables: tuple[str, ...]
    missing_tables: tuple[str, ...]
    manifest_hash: str

    def __post_init__(self) -> None:
        identities = tuple(record.feature_id for record in self.records)
        if len(identities) != len(set(identities)):
            raise ValueError("feature eligibility identities must be unique")
        if tuple(sorted(identities)) != identities:
            raise ValueError("feature eligibility records must use canonical ordering")
        if not self.manifest_hash.startswith("sha256:"):
            raise ValueError("manifest_hash must be a sha256 identity")

    @property
    def unreviewed_records(self) -> tuple[FeatureEligibilityRecord, ...]:
        return tuple(
            record for record in self.records if record.eligibility_status == "unreviewed"
        )

    def for_table(self, table_name: str) -> tuple[FeatureEligibilityRecord, ...]:
        return tuple(record for record in self.records if record.table_name == table_name)

    def get(self, table_name: str, column_name: str) -> FeatureEligibilityRecord | None:
        identity = f"{table_name}.{column_name}"
        return next((record for record in self.records if record.feature_id == identity), None)

    @classmethod
    def create(
        cls,
        *,
        records: tuple[FeatureEligibilityRecord, ...],
        inspected_tables: tuple[str, ...],
        missing_tables: tuple[str, ...],
    ) -> "FeatureEligibilityManifest":
        ordered = tuple(sorted(records, key=lambda record: record.feature_id))
        payload = {
            "records": [record.record_hash for record in ordered],
            "inspected_tables": list(sorted(inspected_tables)),
            "missing_tables": list(sorted(missing_tables)),
        }
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return cls(
            records=ordered,
            inspected_tables=tuple(sorted(inspected_tables)),
            missing_tables=tuple(sorted(missing_tables)),
            manifest_hash=f"sha256:{digest}",
        )


@dataclass(frozen=True)
class _TablePolicy:
    family: str
    source_id: str
    default_status: FeatureEligibilityStatus
    event_candidates: tuple[str, ...]
    announced_candidates: tuple[str, ...]
    available_candidates: tuple[str, ...]
    first_seen_candidates: tuple[str, ...]
    effective_candidates: tuple[str, ...]
    revision_candidates: tuple[str, ...]
    identifier_columns: frozenset[str]
    feature_specs: dict[str, tuple[str, int]]
    blocked_columns: frozenset[str]
    staleness_days: int
    license_policy: str
    quality_policy: str


_PRICE_UNITS: dict[str, tuple[str, int]] = {
    "成交股數": ("shares", 1),
    "成交筆數": ("trade_count", 1),
    "成交金額": ("currency_minor", 1),
    "開盤價": ("price_1e4", 10_000),
    "最高價": ("price_1e4", 10_000),
    "最低價": ("price_1e4", 10_000),
    "收盤價": ("price_1e4", 10_000),
    "漲跌價差": ("price_1e4", 10_000),
    "最後揭示買價": ("price_1e4", 10_000),
    "最後揭示買量": ("shares", 1),
    "最後揭示賣價": ("price_1e4", 10_000),
    "最後揭示賣量": ("shares", 1),
    "本益比": ("ratio_1e4", 10_000),
}

_TECHNICAL_UNITS: dict[str, tuple[str, int]] = {
    name: ("indicator_1e4", 10_000)
    for name in (
        "漲跌(+/-)",
        "漲跌價差",
        "最後揭示買價",
        "最後揭示賣價",
        "本益比",
        "SMA30",
        "DEMA30",
        "EMA30",
        "RSI",
        "MACD",
        "MACD_signal",
        "MACD_hist",
        "slowk",
        "slowd",
        "middleband",
        "upperband",
        "lowerband",
        "SAR",
        "TSF",
        "涨跌",
        "MA5",
        "MA10",
        "MA20",
        "MA60",
        "ATR",
        "ADX",
    )
}
_TECHNICAL_UNITS.update(
    {
        "最後揭示買量": ("shares", 1),
        "最後揭示賣量": ("shares", 1),
    }
)

_MARKET_UNITS: dict[str, tuple[str, int]] = {
    "收盤指數": ("index_1e4", 10_000),
    "漲跌點數": ("index_1e4", 10_000),
    "漲跌百分比": ("percent_1e4", 10_000),
    "開盤價": ("index_1e4", 10_000),
    "最高價": ("index_1e4", 10_000),
    "最低價": ("index_1e4", 10_000),
    "收盤價": ("index_1e4", 10_000),
    "成交量": ("shares", 1),
}

_INSTITUTIONAL_UNITS = {
    name: ("shares", 1)
    for name in (
        "foreign_investor_buy",
        "foreign_investor_sell",
        "foreign_investor_net",
        "investment_trust_buy",
        "investment_trust_sell",
        "investment_trust_net",
        "dealer_buy",
        "dealer_sell",
        "dealer_net",
    )
}
_CREDIT_UNITS = {
    name: ("shares", 1)
    for name in (
        "margin_purchase",
        "margin_balance",
        "short_sale",
        "short_balance",
        "financing",
        "securities_lending",
    )
}
_TDCC_UNITS = {
    "large_holder_ratio_bp": ("bp", 1),
    "retail_holder_ratio_bp": ("bp", 1),
    "dispersion_index_bp": ("bp", 1),
}
_BROKER_UNITS = {
    "買進股數": ("shares", 1),
    "賣出股數": ("shares", 1),
    "買賣超股數": ("shares", 1),
    "買進金額千元": ("thousand_currency", 1),
    "賣出金額千元": ("thousand_currency", 1),
    "買賣超金額千元": ("thousand_currency", 1),
    "lots_observed": ("boolean_int", 1),
    "amount_observed": ("boolean_int", 1),
    "lots_rank": ("rank", 1),
    "amount_rank": ("rank", 1),
}

_TABLE_POLICIES: dict[str, _TablePolicy] = {
    "daily_prices": _TablePolicy(
        family="price_liquidity_technical",
        source_id="sqlite.daily_prices",
        default_status="formal_backfill",
        event_candidates=("日期",),
        announced_candidates=(),
        available_candidates=(),
        first_seen_candidates=(),
        effective_candidates=(),
        revision_candidates=(),
        identifier_columns=frozenset({"證券代號", "證券名稱"}),
        feature_specs=_PRICE_UNITS,
        blocked_columns=frozenset(
            {
                "涨跌",
                "漲跌",
                "Date",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "漲跌(+/-)",
                "SMA30",
                "DEMA30",
                "EMA30",
                "RSI",
                "MACD",
                "MACD_signal",
                "MACD_hist",
                "slowk",
                "slowd",
                "middleband",
                "upperband",
                "lowerband",
                "SAR",
                "TSF",
            }
        ),
        staleness_days=7,
        license_policy="source-registry:twse-tpex-required",
        quality_policy="core-source-quality-firewall",
    ),
    "technical_indicators": _TablePolicy(
        family="price_liquidity_technical",
        source_id="sqlite.technical_indicators",
        default_status="formal_backfill",
        event_candidates=("日期",),
        announced_candidates=(),
        available_candidates=(),
        first_seen_candidates=(),
        effective_candidates=(),
        revision_candidates=(),
        identifier_columns=frozenset({"證券代號", "證券名稱"}),
        feature_specs=_TECHNICAL_UNITS,
        blocked_columns=frozenset(
            {
                "成交筆數",
                "成交金額",
                "成交股數",
                "開盤價",
                "最高價",
                "最低價",
                "收盤價",
                "Date",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "漲跌",
            }
        ),
        staleness_days=7,
        license_policy="derived-from-governed-price-source",
        quality_policy="causal-technical-prefix-required",
    ),
    "market_indices": _TablePolicy(
        family="market_sector_cross_section",
        source_id="sqlite.market_indices",
        default_status="formal_backfill",
        event_candidates=("日期",),
        announced_candidates=(),
        available_candidates=(),
        first_seen_candidates=(),
        effective_candidates=(),
        revision_candidates=(),
        identifier_columns=frozenset({"指數名稱"}),
        feature_specs=_MARKET_UNITS,
        blocked_columns=frozenset({"漲跌"}),
        staleness_days=7,
        license_policy="source-registry:twse-required",
        quality_policy="core-source-quality-firewall",
    ),
    "industry_indices": _TablePolicy(
        family="market_sector_cross_section",
        source_id="sqlite.industry_indices",
        default_status="formal_backfill",
        event_candidates=("日期",),
        announced_candidates=(),
        available_candidates=(),
        first_seen_candidates=(),
        effective_candidates=(),
        revision_candidates=(),
        identifier_columns=frozenset({"指數名稱"}),
        feature_specs={
            key: value
            for key, value in _MARKET_UNITS.items()
            if key in {"收盤指數", "漲跌點數", "漲跌百分比"}
        },
        blocked_columns=frozenset({"漲跌"}),
        staleness_days=7,
        license_policy="source-registry:twse-required",
        quality_policy="core-source-quality-firewall",
    ),
    "fundamental_monthly_revenues": _TablePolicy(
        family="fundamental_growth_quality",
        source_id="sqlite.fundamental_monthly_revenues",
        default_status="research_shadow",
        event_candidates=("as_of_date", "period"),
        announced_candidates=("announced_date",),
        available_candidates=("available_at", "available_date"),
        first_seen_candidates=("first_observed_at", "created_at"),
        effective_candidates=(),
        revision_candidates=("revision_id", "source_version"),
        identifier_columns=frozenset({"stock_code", "period"}),
        feature_specs={"revenue": ("currency_1e4", 10_000)},
        blocked_columns=frozenset(),
        staleness_days=62,
        license_policy="row-source-license-acceptance-required",
        quality_policy="announcement-or-first-seen-and-quality-mask",
    ),
    "fundamental_statement_items": _TablePolicy(
        family="fundamental_growth_quality",
        source_id="sqlite.fundamental_statement_items",
        default_status="research_shadow",
        event_candidates=("as_of_date", "period"),
        announced_candidates=("announced_date",),
        available_candidates=("available_at", "available_date"),
        first_seen_candidates=("first_observed_at", "created_at"),
        effective_candidates=(),
        revision_candidates=("revision_id", "source_version"),
        identifier_columns=frozenset(
            {"stock_code", "statement_type", "period", "item_code", "item_name"}
        ),
        feature_specs={"value": ("currency_1e4", 10_000)},
        blocked_columns=frozenset(),
        staleness_days=150,
        license_policy="row-source-license-acceptance-required",
        quality_policy="publication-or-first-seen-and-quality-mask",
    ),
    "fundamental_valuation_metrics": _TablePolicy(
        family="valuation",
        source_id="sqlite.fundamental_valuation_metrics",
        default_status="research_shadow",
        event_candidates=("as_of_date",),
        announced_candidates=("announced_date",),
        available_candidates=("available_at", "available_date"),
        first_seen_candidates=("first_observed_at", "created_at"),
        effective_candidates=(),
        revision_candidates=("revision_id", "source_version"),
        identifier_columns=frozenset({"stock_code", "metric_name", "industry"}),
        feature_specs={
            "value": ("ratio_1e4", 10_000),
            "industry_percentile_bp": ("bp", 1),
        },
        blocked_columns=frozenset(),
        staleness_days=45,
        license_policy="row-source-license-acceptance-required",
        quality_policy="first-seen-and-quality-mask",
    ),
    "institutional_flows": _TablePolicy(
        family="flow_chip",
        source_id="sqlite.institutional_flows",
        default_status="research_shadow",
        event_candidates=("decision_date",),
        announced_candidates=("publication_at",),
        available_candidates=("available_at", "available_date"),
        first_seen_candidates=("first_observed_at", "created_at"),
        effective_candidates=(),
        revision_candidates=("revision_id", "source_version"),
        identifier_columns=frozenset({"stock_code"}),
        feature_specs=_INSTITUTIONAL_UNITS,
        blocked_columns=frozenset(),
        staleness_days=7,
        license_policy="p0-source-license-acceptance-required",
        quality_policy="research-shadow-quality-mask",
    ),
    "credit_transactions": _TablePolicy(
        family="flow_chip",
        source_id="sqlite.credit_transactions",
        default_status="research_shadow",
        event_candidates=("decision_date",),
        announced_candidates=("publication_at",),
        available_candidates=("available_at", "available_date"),
        first_seen_candidates=("first_observed_at", "created_at"),
        effective_candidates=(),
        revision_candidates=("revision_id", "source_version"),
        identifier_columns=frozenset({"stock_code"}),
        feature_specs=_CREDIT_UNITS,
        blocked_columns=frozenset(),
        staleness_days=7,
        license_policy="p0-source-license-acceptance-required",
        quality_policy="research-shadow-quality-mask",
    ),
    "tdcc_shareholding": _TablePolicy(
        family="flow_chip",
        source_id="sqlite.tdcc_shareholding",
        default_status="research_shadow",
        event_candidates=("decision_date",),
        announced_candidates=("publication_at",),
        available_candidates=("available_at", "available_date"),
        first_seen_candidates=("first_observed_at", "created_at"),
        effective_candidates=(),
        revision_candidates=("revision_id", "source_version"),
        identifier_columns=frozenset({"stock_code"}),
        feature_specs=_TDCC_UNITS,
        blocked_columns=frozenset({"shareholding_tiers"}),
        staleness_days=14,
        license_policy="p0-source-license-acceptance-required",
        quality_policy="research-shadow-quality-mask",
    ),
    "broker_flows": _TablePolicy(
        family="flow_chip",
        source_id="sqlite.broker_flows",
        default_status="research_shadow",
        event_candidates=("日期",),
        announced_candidates=(),
        available_candidates=(),
        first_seen_candidates=(),
        effective_candidates=(),
        revision_candidates=(),
        identifier_columns=frozenset(
            {"分點名稱", "證券代號", "證券名稱", "trade_type"}
        ),
        feature_specs=_BROKER_UNITS,
        blocked_columns=frozenset(),
        staleness_days=7,
        license_policy="broker-source-license-acceptance-required",
        quality_policy="ranked-metric-observation-mask-required",
    ),
}

_COMMON_AVAILABILITY_COLUMNS = frozenset(
    {
        "as_of_date",
        "data_as_of_date",
        "event_at",
        "event_date",
        "announced_at",
        "announced_date",
        "publication_at",
        "available_at",
        "available_date",
        "first_observed_at",
        "first_seen_at",
        "created_at",
        "effective_at",
        "effective_date",
        "revision_id",
        "source",
        "source_version",
        "quality",
        "日期",
        "decision_date",
    }
)
_LEAKAGE_TOKENS = (
    "label",
    "target",
    "future",
    "forward",
    "outcome",
    "prediction",
    "predicted",
    "output",
    "horizon_end",
    "next_return",
    "未來",
    "標籤",
    "預測",
)
_COMMON_IDENTIFIER_COLUMNS = frozenset(
    {
        "id",
        "stock_code",
        "symbol",
        "security_code",
        "ticker",
        "證券代號",
        "證券名稱",
        "股票代號",
        "股票名稱",
        "分點名稱",
        "指數名稱",
        "item_code",
        "item_name",
        "metric_name",
    }
)


def build_feature_eligibility_manifest(
    connection: sqlite3.Connection,
    *,
    expected_tables: tuple[str, ...] = ALL_FIELD_SOURCE_TABLES,
    include_all_user_tables: bool = True,
) -> FeatureEligibilityManifest:
    """以唯讀 schema introspection 建立每欄位都有 disposition 的 manifest。"""

    if not expected_tables or len(expected_tables) != len(set(expected_tables)):
        raise ValueError("expected_tables must be non-empty and unique")

    existing = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }
    records: list[FeatureEligibilityRecord] = []
    inspected: list[str] = []
    missing = sorted(set(expected_tables) - existing)
    inspected_targets = (
        sorted(existing)
        if include_all_user_tables
        else sorted(existing.intersection(expected_tables))
    )
    for table_name in inspected_targets:
        inspected.append(table_name)
        columns = tuple(
            (str(row[1]), str(row[2] or ""))
            for row in connection.execute(
                f"PRAGMA table_info({_quote_identifier(table_name)})"
            ).fetchall()
        )
        column_names = {name for name, _ in columns}
        policy = _TABLE_POLICIES.get(table_name) or _generic_table_policy(
            table_name, column_names
        )
        time_policy = _time_policy(policy, column_names)
        records.extend(
            _record_for_column(
                table_name=table_name,
                column_name=column_name,
                declared_type=declared_type,
                policy=policy,
                time_policy=time_policy,
            )
            for column_name, declared_type in columns
        )
    return FeatureEligibilityManifest.create(
        records=tuple(records),
        inspected_tables=tuple(inspected),
        missing_tables=tuple(missing),
    )


def table_family(table_name: str) -> str:
    """回傳受治理來源 table 的 feature pack。"""

    policy = _TABLE_POLICIES.get(table_name)
    if policy is None:
        raise KeyError(table_name)
    return policy.family


def table_time_policy(
    table_name: str, available_columns: frozenset[str] | set[str]
) -> TimeFieldPolicy:
    """依實際 schema 解出 table 的 PIT 時間欄位。"""

    policy = _TABLE_POLICIES.get(table_name)
    if policy is None:
        raise KeyError(table_name)
    return _time_policy(policy, set(available_columns))


def _record_for_column(
    *,
    table_name: str,
    column_name: str,
    declared_type: str,
    policy: _TablePolicy,
    time_policy: TimeFieldPolicy,
) -> FeatureEligibilityRecord:
    lower_name = column_name.casefold()
    if any(token in lower_name for token in _LEAKAGE_TOKENS):
        status: FeatureEligibilityStatus = "excluded_leakage"
        reason = "future_label_or_output_column"
        canonical_dtype, unit, scale = "metadata", "not_applicable", 1
    elif column_name in _COMMON_AVAILABILITY_COLUMNS:
        status = "availability_only"
        reason = "pit_availability_or_lineage_metadata"
        canonical_dtype, unit, scale = "metadata", "not_applicable", 1
    elif column_name in policy.identifier_columns:
        status = "excluded_identifier"
        reason = "entity_or_category_identifier"
        canonical_dtype, unit, scale = "metadata", "not_applicable", 1
    elif (
        column_name.casefold() in _COMMON_IDENTIFIER_COLUMNS
        or column_name.casefold().endswith("_id")
    ):
        status = "excluded_identifier"
        reason = "generic_identifier_fail_closed"
        canonical_dtype, unit, scale = "metadata", "not_applicable", 1
    elif column_name in policy.blocked_columns:
        status = "blocked_no_provenance"
        reason = "duplicate_or_unregistered_transform"
        canonical_dtype, unit, scale = "metadata", "not_applicable", 1
    elif column_name in policy.feature_specs:
        status = policy.default_status
        reason = {
            "formal_backfill": "explicit_causal_feature_rule",
            "first_seen_only": "explicit_first_seen_feature_rule",
            "research_shadow": "explicit_research_shadow_feature_rule",
        }[status]
        canonical_dtype = "int"
        unit, scale = policy.feature_specs[column_name]
    else:
        status = "unreviewed"
        reason = "unknown_column_fail_closed"
        canonical_dtype, unit, scale = "metadata", "not_applicable", 1

    revision_policy = (
        f"append-only; revision key={time_policy.revision_id}"
        if time_policy.revision_id is not None
        else "source snapshot hash; no revision column"
    )
    return FeatureEligibilityRecord.create(
        table_name=table_name,
        column_name=column_name,
        family=policy.family,
        source_id=policy.source_id,
        sqlite_declared_type=declared_type or "UNDECLARED",
        canonical_dtype=canonical_dtype,
        unit=unit,
        scale=scale,
        time_policy=time_policy,
        missing_policy="missing_is_not_zero; preserve explicit mask",
        staleness_days=policy.staleness_days,
        revision_policy=revision_policy,
        license_policy=policy.license_policy,
        quality_policy=policy.quality_policy,
        eligibility_status=status,
        reason_code=reason,
    )


def _time_policy(policy: _TablePolicy, columns: set[str]) -> TimeFieldPolicy:
    event_at = _first_present(policy.event_candidates, columns)
    if event_at is None:
        event_at = policy.event_candidates[0]
    return TimeFieldPolicy(
        event_at=event_at,
        announced_at=_first_present(policy.announced_candidates, columns),
        available_at=_first_present(policy.available_candidates, columns),
        first_seen_at=_first_present(policy.first_seen_candidates, columns),
        effective_at=_first_present(policy.effective_candidates, columns),
        revision_id=_first_present(policy.revision_candidates, columns),
    )


def _generic_table_policy(table_name: str, columns: set[str]) -> _TablePolicy:
    event_candidates = tuple(
        candidate
        for candidate in (
            "decision_date",
            "日期",
            "event_at",
            "event_date",
            "data_as_of_date",
            "as_of_date",
            "created_at",
        )
        if candidate in columns
    ) or ("__unresolved_event_at__",)
    return _TablePolicy(
        family="unassigned",
        source_id=f"sqlite.{table_name}",
        default_status="unreviewed",
        event_candidates=event_candidates,
        announced_candidates=tuple(
            candidate
            for candidate in ("announced_at", "announced_date", "publication_at")
            if candidate in columns
        ),
        available_candidates=tuple(
            candidate
            for candidate in ("available_at", "available_date", "data_as_of_date")
            if candidate in columns
        ),
        first_seen_candidates=tuple(
            candidate
            for candidate in ("first_observed_at", "first_seen_at", "created_at")
            if candidate in columns
        ),
        effective_candidates=tuple(
            candidate
            for candidate in ("effective_at", "effective_date")
            if candidate in columns
        ),
        revision_candidates=tuple(
            candidate
            for candidate in ("revision_id", "source_version", "version")
            if candidate in columns
        ),
        identifier_columns=frozenset(),
        feature_specs={},
        blocked_columns=frozenset(),
        staleness_days=0,
        license_policy="unreviewed-source-license-fail-closed",
        quality_policy="unreviewed-quality-fail-closed",
    )


def _first_present(candidates: tuple[str, ...], columns: set[str]) -> str | None:
    return next((candidate for candidate in candidates if candidate in columns), None)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
