"""PIT monthly-revenue and quarterly-financial announcement adapters."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_contract_registry import build_p0_source_contract_registry


REVENUE_SOURCES = frozenset(
    {"twse.monthly_revenue_announcement", "tpex.monthly_revenue_announcement"}
)


class PITRevenueAnnouncementAdapter:
    def adapt(
        self, *, source_id: str, row: Mapping[str, Any], decision_date: str
    ) -> P0ShadowObservation:
        if source_id not in REVENUE_SOURCES:
            raise ValueError(f"source is outside revenue adapter family: {source_id}")
        required = (
            "symbol",
            "period",
            "announcement_date",
            "available_date",
            "source_version",
            "revenue_cents",
        )
        blocking = _base_diagnostics(row, decision_date, required)
        revenue = row.get("revenue_cents")
        if revenue is not None and (not isinstance(revenue, int) or isinstance(revenue, bool)):
            blocking.append("invalid_revenue_cents")
        return _observation(source_id, row, decision_date, blocking, _text(row.get("period")))


class PITFinancialAnnouncementAdapter:
    def adapt(
        self, *, row: Mapping[str, Any], decision_date: str
    ) -> P0ShadowObservation:
        source_id = "pit.quarterly_financials"
        required = (
            "symbol",
            "period_end",
            "announcement_date",
            "available_date",
            "source_version",
            "statement_items",
        )
        blocking = _base_diagnostics(row, decision_date, required)
        revision = row.get("revision_number", 0)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            blocking.append("invalid_revision_number")
        if row.get("statement_items") is not None and not isinstance(row["statement_items"], Mapping):
            blocking.append("invalid_statement_items")
        return _observation(
            source_id, row, decision_date, blocking, _text(row.get("period_end"))
        )


def _base_diagnostics(
    row: Mapping[str, Any], decision_date: str, required: tuple[str, ...]
) -> list[str]:
    blocking = [f"missing_{field}" for field in required if row.get(field) is None]
    available = _text(row.get("available_date"))
    announcement = _text(row.get("announcement_date"))
    if available and _parse(available) > _parse(decision_date):
        blocking.append("future_available_date")
    if available and announcement and _parse(available) < _parse(announcement):
        blocking.append("available_before_announcement")
    return blocking


def _observation(
    source_id: str,
    row: Mapping[str, Any],
    decision_date: str,
    blocking: list[str],
    period: str | None,
) -> P0ShadowObservation:
    contract = build_p0_source_contract_registry().require(source_id)
    unique = tuple(sorted(set(blocking)))
    return P0ShadowObservation(
        source_id=contract.source_id,
        symbol=_text(row.get("symbol")) or "",
        decision_date=decision_date,
        available_date=_text(row.get("available_date")),
        source_version=_text(row.get("source_version")) or "",
        status="blocked" if unique else "shadow_ready",
        diagnostics=(*unique, "period_is_not_available_date"),
        raw_payload=dict(row),
        effective_from=period,
        effective_to=period,
    )


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
