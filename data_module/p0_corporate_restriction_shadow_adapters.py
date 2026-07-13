"""Corporate-action and trading-restriction shadow-only adapters."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_contract_registry import build_p0_source_contract_registry


CORPORATE_SOURCES = frozenset(
    {
        "corporate_action.ex_dividend_timeline",
        "corporate_action.reduction_split_par_value",
    }
)
RESTRICTION_SOURCES = frozenset(
    {
        "microstructure.suspended_halt_resume",
        "microstructure.disposition_stock",
        "microstructure.periodic_call_auction",
        "microstructure.full_delivery",
        "microstructure.limit_lock",
    }
)


class CorporateActionShadowAdapter:
    def adapt(
        self, *, source_id: str, row: Mapping[str, Any], decision_date: str
    ) -> P0ShadowObservation:
        _require_family(source_id, CORPORATE_SOURCES)
        effective_from = _text(row.get("event_date"))
        required = ("symbol", "event_type", "event_date", "available_date", "source_version")
        return _adapt(source_id, row, decision_date, required, effective_from, None)


class TradingRestrictionShadowAdapter:
    def adapt(
        self, *, source_id: str, row: Mapping[str, Any], decision_date: str
    ) -> P0ShadowObservation:
        _require_family(source_id, RESTRICTION_SOURCES)
        effective_from = _text(row.get("effective_from") or row.get("effective_date"))
        effective_to = _text(row.get("effective_to"))
        required = ("symbol", "available_date", "source_version")
        observation = _adapt(
            source_id, row, decision_date, required, effective_from, effective_to
        )
        diagnostics = list(observation.diagnostics)
        if effective_from is None:
            diagnostics.append("missing_effective_from")
        return _replace_status(observation, diagnostics)


def _adapt(
    source_id: str,
    row: Mapping[str, Any],
    decision_date: str,
    required_fields: tuple[str, ...],
    effective_from: str | None,
    effective_to: str | None,
) -> P0ShadowObservation:
    contract = build_p0_source_contract_registry().require(source_id)
    diagnostics = [f"missing_{name}" for name in required_fields if not _text(row.get(name))]
    available_date = _text(row.get("available_date"))
    if available_date and _parse_date(available_date) > _parse_date(decision_date):
        diagnostics.append("future_available_date")
    return P0ShadowObservation(
        source_id=contract.source_id,
        symbol=_text(row.get("symbol")) or "",
        decision_date=decision_date,
        available_date=available_date,
        source_version=_text(row.get("source_version")) or "",
        status="blocked" if diagnostics else "shadow_ready",
        diagnostics=tuple(sorted(set(diagnostics))),
        raw_payload=dict(row),
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _replace_status(
    observation: P0ShadowObservation, diagnostics: list[str]
) -> P0ShadowObservation:
    return P0ShadowObservation(
        source_id=observation.source_id,
        symbol=observation.symbol,
        decision_date=observation.decision_date,
        available_date=observation.available_date,
        source_version=observation.source_version,
        status="blocked" if diagnostics else "shadow_ready",
        diagnostics=tuple(sorted(set(diagnostics))),
        raw_payload=observation.raw_payload,
        effective_from=observation.effective_from,
        effective_to=observation.effective_to,
    )


def _require_family(source_id: str, allowed: frozenset[str]) -> None:
    if source_id not in allowed:
        raise ValueError(f"source is outside adapter family: {source_id}")


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid ISO date: {value}") from exc
