from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable


CAPABILITY_READY = "ready"
CAPABILITY_PARTIAL = "partial"
CAPABILITY_PLANNED = "planned"
CAPABILITY_DEFERRED = "deferred"


@dataclass(frozen=True)
class DataSourceField:
    field_name: str
    description: str
    required: bool = True
    available_date_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "description": self.description,
            "required": self.required,
            "available_date_required": self.available_date_required,
        }


@dataclass(frozen=True)
class DataSourceCapability:
    source_id: str
    source_name: str
    source_type: str
    status: str
    coverage_scope: str
    available_date_policy: str
    latency_policy: str
    quality_policy: str
    missing_policy: str
    license_note: str
    rate_limit_note: str
    backfill_policy: str
    fields: tuple[DataSourceField, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "status": self.status,
            "coverage_scope": self.coverage_scope,
            "available_date_policy": self.available_date_policy,
            "latency_policy": self.latency_policy,
            "quality_policy": self.quality_policy,
            "missing_policy": self.missing_policy,
            "license_note": self.license_note,
            "rate_limit_note": self.rate_limit_note,
            "backfill_policy": self.backfill_policy,
            "fields": [field.to_dict() for field in self.fields],
            "warnings": list(self.warnings),
        }


class DataSourceCapabilityRegistry:
    def __init__(self, capabilities: Iterable[DataSourceCapability]) -> None:
        self._capabilities = {item.source_id: item for item in capabilities}

    def get(self, source_id: str) -> DataSourceCapability | None:
        return self._capabilities.get(source_id)

    def require(self, source_id: str) -> DataSourceCapability:
        capability = self.get(source_id)
        if capability is None:
            raise KeyError(source_id)
        return capability

    def list(self) -> tuple[DataSourceCapability, ...]:
        return tuple(self._capabilities[key] for key in sorted(self._capabilities))

    def list_by_status(self, status: str) -> tuple[DataSourceCapability, ...]:
        return tuple(item for item in self.list() if item.status == status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "production_data_writes": False,
            "sources": [item.to_dict() for item in self.list()],
        }


@dataclass(frozen=True)
class DataSourceCapabilityInspection:
    registry: DataSourceCapabilityRegistry

    def to_dict(self) -> dict[str, Any]:
        payload = self.registry.to_dict()
        counts = Counter(item.status for item in self.registry.list())
        payload["status_counts"] = dict(sorted(counts.items()))
        payload["readiness_boundary"] = (
            "read-only capability inspection; no production DB write, source ingestion, "
            "scheduler enablement, or trading conclusion"
        )
        return payload

    def to_markdown(self) -> str:
        payload = self.to_dict()
        rows = [
            "| source_id | status | type | missing_policy |",
            "|---|---|---|---|",
        ]
        for item in payload["sources"]:
            rows.append(
                f"| `{item['source_id']}` | {item['status']} | {item['source_type']} | {item['missing_policy']} |"
            )
        return "\n".join(
            [
                "# Data Source Capability Registry",
                "",
                f"- schema_version: {payload['schema_version']}",
                f"- production_data_writes: {str(payload['production_data_writes']).lower()}",
                f"- status_counts: {payload['status_counts']}",
                "",
                *rows,
                "",
                "## Boundary",
                "",
                payload["readiness_boundary"],
            ]
        )


def build_default_data_source_capability_registry() -> DataSourceCapabilityRegistry:
    return DataSourceCapabilityRegistry(
        (
            _capability(
                "twse.daily_prices.raw",
                "TWSE daily price raw CSV",
                "price",
                CAPABILITY_READY,
                "上市每日股價 raw 日檔",
                "trade date close data is available after source publication and local update",
                ("date", "trade date"), ("stock_code", "證券代號"), ("close_price", "收盤價"),
            ),
            _capability(
                "tpex.daily_prices.raw",
                "TPEX daily price raw CSV",
                "price",
                CAPABILITY_READY,
                "上櫃每日股價 official daily close quotes",
                "trade date close data is available after source publication and local update",
                ("date", "trade date"), ("stock_code", "證券代號"), ("close_price", "收盤價"),
            ),
            _capability(
                "sqlite.daily_prices",
                "SQLite daily_prices table",
                "price",
                CAPABILITY_READY,
                "本地 SQLite daily_prices 查詢層",
                "inherits source available date from synchronized raw daily files",
                ("date", "日期"), ("stock_code", "證券代號"), ("close_price", "收盤價"),
            ),
            _capability(
                "recommendation.persisted_result",
                "Persisted recommendation result",
                "evidence_source",
                CAPABILITY_READY,
                "RecommendationResultDTO 保存後的推薦 included events",
                "created_at / result save time is the evidence available date",
                ("result_id", "推薦結果 ID"), ("stock_code", "證券代號"),
            ),
            _capability(
                "recommendation.exclusion.why_not_payload",
                "Recommendation why-not exclusion payload",
                "evidence_source",
                CAPABILITY_PARTIAL,
                "已保存 RecommendationResultDTO 內的 optional why-not payload",
                "only available when the recommendation result explicitly persists payload rows",
                ("stock_code", "被排除股票代號"), ("exclusion_reason_codes", "排除原因代碼"),
                warnings=("optional_payload_partial", "historical_results_are_not_backfilled"),
            ),
            _capability(
                "recommendation.exclusion.liquidity_gate_payload",
                "Recommendation liquidity gate exclusion payload",
                "evidence_source",
                CAPABILITY_PARTIAL,
                "已保存 RecommendationResultDTO 內的 optional liquidity payload",
                "only available when the recommendation result explicitly persists liquidity rows",
                ("stock_code", "被排除股票代號"), ("exclusion_reason_codes", "流動性排除原因"),
                warnings=("optional_payload_partial", "historical_results_are_not_backfilled"),
            ),
            _capability(
                "decision_desk.snapshot.watchlist_trigger",
                "Durable Daily Decision Desk watchlist trigger snapshot",
                "evidence_source",
                CAPABILITY_READY,
                "Durable Daily Decision Desk snapshot watchlist section",
                "snapshot decision_date is available after explicit capture",
                ("snapshot_id", "snapshot ID"), ("triggered_codes", "觸發股票代號"),
            ),
            _capability(
                "decision_desk.snapshot.portfolio_alert",
                "Durable Daily Decision Desk portfolio alert snapshot",
                "evidence_source",
                CAPABILITY_READY,
                "Durable Daily Decision Desk snapshot portfolio alert section",
                "snapshot decision_date is available after explicit capture",
                ("snapshot_id", "snapshot ID"), ("attributions", "持倉警示來源歸因"),
            ),
            _capability(
                "decision_desk.snapshot.risk_prompt",
                "Durable Daily Decision Desk risk prompt snapshot",
                "evidence_source",
                CAPABILITY_READY,
                "Durable Daily Decision Desk snapshot risk prompt section",
                "snapshot decision_date is available after explicit capture",
                ("snapshot_id", "snapshot ID"), ("prompts", "風險提示"),
            ),
            _capability(
                "corporate_action.ex_dividend_timeline",
                "Corporate action ex-dividend / ex-right timeline",
                "corporate_action",
                CAPABILITY_PLANNED,
                "除權息 / 還原價時間軸 source candidate",
                "must preserve event announcement date and decision-date availability before use",
                ("event_date", "除權息事件日期"), ("available_date", "決策可得日"),
                missing_policy="fail_closed_for_adjusted_decision_features",
                warnings=("source_not_ingested", "adjusted_price_policy_candidate_only"),
            ),
            _capability(
                "microstructure.disposition_stock",
                "Disposition stock governed source",
                "microstructure",
                CAPABILITY_PLANNED,
                "處置股交易限制 source candidate",
                "must preserve restriction effective dates and decision-date availability",
                ("stock_code", "證券代號"), ("effective_date", "生效日期"), ("available_date", "決策可得日"),
                missing_policy="degrade_preflight_and_warn",
                warnings=("source_not_ingested",),
            ),
            _capability(
                "microstructure.periodic_call_auction",
                "Periodic call auction governed source",
                "microstructure",
                CAPABILITY_PLANNED,
                "分盤交易限制 source candidate",
                "must preserve restriction effective dates and decision-date availability",
                ("stock_code", "證券代號"), ("effective_date", "生效日期"), ("available_date", "決策可得日"),
                missing_policy="degrade_preflight_and_warn",
                warnings=("source_not_ingested",),
            ),
            _capability(
                "microstructure.full_delivery",
                "Full delivery stock governed source",
                "microstructure",
                CAPABILITY_PLANNED,
                "全額交割 source candidate",
                "must preserve restriction effective dates and decision-date availability",
                ("stock_code", "證券代號"), ("effective_date", "生效日期"), ("available_date", "決策可得日"),
                missing_policy="degrade_preflight_and_warn",
                warnings=("source_not_ingested",),
            ),
            _capability(
                "microstructure.limit_lock",
                "Limit up/down lock governed source",
                "microstructure",
                CAPABILITY_PLANNED,
                "漲跌停鎖死 source candidate",
                "must be derived from same-day price / volume evidence available at decision time",
                ("stock_code", "證券代號"), ("trade_date", "交易日期"), ("available_date", "決策可得日"),
                missing_policy="degrade_preflight_and_warn",
                warnings=("source_not_ingested",),
            ),
        )
    )


def inspect_data_source_capabilities() -> DataSourceCapabilityInspection:
    return DataSourceCapabilityInspection(build_default_data_source_capability_registry())


def _capability(
    source_id: str,
    source_name: str,
    source_type: str,
    status: str,
    coverage_scope: str,
    available_date_policy: str,
    *fields: tuple[str, str],
    missing_policy: str = "preserve_missing_and_warn",
    warnings: tuple[str, ...] = (),
) -> DataSourceCapability:
    return DataSourceCapability(
        source_id=source_id,
        source_name=source_name,
        source_type=source_type,
        status=status,
        coverage_scope=coverage_scope,
        available_date_policy=available_date_policy,
        latency_policy="source-specific; inspect source capability before use",
        quality_policy="preserve observed / degraded / missing state; do not impute silently",
        missing_policy=missing_policy,
        license_note="local governed use only; verify source terms before expanding ingestion",
        rate_limit_note="read-only registry entry; no request is executed",
        backfill_policy="candidate or existing local source only; formal backfill requires explicit gate",
        fields=tuple(DataSourceField(field_name=name, description=description) for name, description in fields),
        warnings=tuple(warnings),
    )
