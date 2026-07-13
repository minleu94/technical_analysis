"""PIT-safe, risk-only credit-transaction shadow adapter."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_contract_registry import build_p0_source_contract_registry


REQUIRED_FIELDS = (
    "symbol",
    "trade_date",
    "available_date",
    "source_version",
    "margin_purchase",
    "margin_balance",
    "short_sale",
    "short_balance",
)
NON_NEGATIVE_FIELDS = (
    "margin_purchase",
    "margin_balance",
    "short_sale",
    "short_balance",
)


class CreditTransactionShadowAdapter:
    def adapt(
        self, *, row: Mapping[str, Any], decision_date: str
    ) -> P0ShadowObservation:
        contract = build_p0_source_contract_registry().require("credit_transactions")
        blocking = [f"missing_{field}" for field in REQUIRED_FIELDS if row.get(field) is None]
        available_date = _text(row.get("available_date"))
        if available_date and _parse(available_date) > _parse(decision_date):
            blocking.append("future_available_date")
        for field in NON_NEGATIVE_FIELDS:
            value = row.get(field)
            if isinstance(value, int) and value < 0:
                blocking.append(f"negative_{field}")
        blocking = sorted(set(blocking))
        return P0ShadowObservation(
            source_id=contract.source_id,
            symbol=_text(row.get("symbol")) or "",
            decision_date=decision_date,
            available_date=available_date,
            source_version=_text(row.get("source_version")) or "",
            status="blocked" if blocking else "shadow_ready",
            diagnostics=tuple((*blocking, "risk_only_not_directional_signal")),
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
