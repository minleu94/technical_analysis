from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from data_module.data_source_capability_registry import build_default_data_source_capability_registry


MICROSTRUCTURE_SOURCE_GROUPS: dict[str, tuple[str, ...]] = {
    "disposition_stock": ("處置股", "disposition_stock", "disposition_flag"),
    "periodic_call_auction": ("分盤交易", "分盤", "periodic_call_auction"),
    "full_delivery": ("全額交割", "full_delivery", "full_delivery_flag"),
    "limit_lock": ("漲跌停鎖死", "漲停鎖死", "跌停鎖死", "limit_lock", "limit_up_down_flag"),
    "ex_dividend_timeline": ("除權息", "除權息日", "ex_dividend", "ex_rights", "adjustment_event"),
}

MICROSTRUCTURE_SOURCE_CAPABILITY_IDS: dict[str, str] = {
    "disposition_stock": "microstructure.disposition_stock",
    "periodic_call_auction": "microstructure.periodic_call_auction",
    "full_delivery": "microstructure.full_delivery",
    "limit_lock": "microstructure.limit_lock",
    "ex_dividend_timeline": "corporate_action.ex_dividend_timeline",
}


@dataclass(frozen=True)
class MicrostructureSourcePreflight:
    source_columns: dict[str, list[str]]
    missing_sources: tuple[str, ...]
    governed_sources: dict[str, dict[str, Any]]
    source_capability_status: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_columns": self.source_columns,
            "missing_sources": list(self.missing_sources),
            "governed_sources": self.governed_sources,
            "source_capability_status": self.source_capability_status,
        }


def build_microstructure_source_preflight(columns: Iterable[str]) -> MicrostructureSourcePreflight:
    column_set = set(columns)
    registry = build_default_data_source_capability_registry()
    source_columns = {
        risk_type: [column for column in candidates if column in column_set]
        for risk_type, candidates in MICROSTRUCTURE_SOURCE_GROUPS.items()
    }
    missing_sources = tuple(sorted(risk_type for risk_type, matched in source_columns.items() if not matched))
    governed_sources: dict[str, dict[str, Any]] = {}
    source_capability_status: dict[str, str] = {}

    for risk_type, candidates in MICROSTRUCTURE_SOURCE_GROUPS.items():
        source_id = MICROSTRUCTURE_SOURCE_CAPABILITY_IDS[risk_type]
        capability = registry.require(source_id)
        source_capability_status[risk_type] = capability.status
        governed_sources[risk_type] = {
            "source_id": capability.source_id,
            "status": capability.status,
            "source_type": capability.source_type,
            "candidate_columns": list(candidates),
            "observed_columns": source_columns[risk_type],
            "available_date_policy": capability.available_date_policy,
            "missing_policy": capability.missing_policy,
            "quality_policy": capability.quality_policy,
            "warnings": list(capability.warnings),
        }

    return MicrostructureSourcePreflight(
        source_columns=source_columns,
        missing_sources=missing_sources,
        governed_sources=governed_sources,
        source_capability_status=source_capability_status,
    )
