"""Weekly TDCC distribution shadow adapter with explicit publication date."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_contract_registry import build_p0_source_contract_registry


RATIO_FIELDS = (
    "large_holder_ratio_bp",
    "retail_holder_ratio_bp",
    "other_holder_ratio_bp",
)
REQUIRED_FIELDS = ("symbol", "period_end", "available_date", "source_version", *RATIO_FIELDS)


class TDCCDistributionShadowAdapter:
    def adapt(
        self, *, row: Mapping[str, Any], decision_date: str
    ) -> P0ShadowObservation:
        contract = build_p0_source_contract_registry().require("tdcc_shareholding")
        blocking = [f"missing_{field}" for field in REQUIRED_FIELDS if row.get(field) is None]
        available_date = _text(row.get("available_date"))
        if available_date and _parse(available_date) > _parse(decision_date):
            blocking.append("future_available_date")
        valid_ratios: list[int] = []
        for field in RATIO_FIELDS:
            value = row.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10000:
                blocking.append(f"invalid_{field}")
            else:
                valid_ratios.append(value)
        if len(valid_ratios) == len(RATIO_FIELDS) and sum(valid_ratios) != 10000:
            blocking.append("holder_ratio_total_not_10000bp")
        blocking = sorted(set(blocking))
        return P0ShadowObservation(
            source_id=contract.source_id,
            symbol=_text(row.get("symbol")) or "",
            decision_date=decision_date,
            available_date=available_date,
            source_version=_text(row.get("source_version")) or "",
            status="blocked" if blocking else "shadow_ready",
            diagnostics=tuple((*blocking, "weekly_period_end_is_not_available_date")),
            raw_payload=dict(row),
            effective_from=_text(row.get("period_end")),
            effective_to=_text(row.get("period_end")),
        )


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
