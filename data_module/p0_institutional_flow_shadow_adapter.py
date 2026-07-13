"""PIT-safe institutional-flow shadow adapter."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_contract_registry import build_p0_source_contract_registry


ACTORS = ("foreign", "trust", "dealer")
REQUIRED_FIELDS = (
    "symbol",
    "trade_date",
    "available_date",
    "source_version",
    *(f"{actor}_{side}" for actor in ACTORS for side in ("buy", "sell", "net")),
)


class InstitutionalFlowShadowAdapter:
    def adapt(
        self, *, row: Mapping[str, Any], decision_date: str
    ) -> P0ShadowObservation:
        contract = build_p0_source_contract_registry().require("institutional_flows")
        diagnostics = [
            f"missing_{field}" for field in REQUIRED_FIELDS if row.get(field) is None
        ]
        available_date = _text(row.get("available_date"))
        if available_date and _parse(available_date) > _parse(decision_date):
            diagnostics.append("future_available_date")
        for actor in ACTORS:
            buy = row.get(f"{actor}_buy")
            sell = row.get(f"{actor}_sell")
            net = row.get(f"{actor}_net")
            if (
                isinstance(buy, int)
                and isinstance(sell, int)
                and isinstance(net, int)
                and buy - sell != net
            ):
                diagnostics.append(f"{actor}_net_mismatch")
        blocking = tuple(sorted(set(diagnostics)))
        disclosures = (*blocking, "single_day_flow_is_not_a_trading_signal")
        return P0ShadowObservation(
            source_id=contract.source_id,
            symbol=_text(row.get("symbol")) or "",
            decision_date=decision_date,
            available_date=available_date,
            source_version=_text(row.get("source_version")) or "",
            status="blocked" if blocking else "shadow_ready",
            diagnostics=disclosures,
            raw_payload=dict(row),
            effective_from=_text(row.get("trade_date")),
            effective_to=_text(row.get("trade_date")),
        )


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
