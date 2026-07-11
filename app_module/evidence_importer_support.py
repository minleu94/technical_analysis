from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.evidence_event_dtos import EvidenceDataQuality


def normalize_quality(value: Any) -> EvidenceDataQuality:
    raw = value.value if hasattr(value, "value") else value
    if raw == EvidenceDataQuality.OBSERVED.value:
        return EvidenceDataQuality.OBSERVED
    if raw == EvidenceDataQuality.ESTIMATED.value:
        return EvidenceDataQuality.ESTIMATED
    if raw == EvidenceDataQuality.DEGRADED.value:
        return EvidenceDataQuality.DEGRADED
    if raw == EvidenceDataQuality.MISSING.value:
        return EvidenceDataQuality.MISSING
    if raw == DecisionDeskQuality.OBSERVED.value:
        return EvidenceDataQuality.OBSERVED
    if raw == DecisionDeskQuality.ESTIMATED.value:
        return EvidenceDataQuality.ESTIMATED
    if raw == DecisionDeskQuality.DEGRADED.value:
        return EvidenceDataQuality.DEGRADED
    return EvidenceDataQuality.MISSING


def date_text(value: Any, fallback: str | None = None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return fallback or date.today().isoformat()
    text = str(value).strip()
    if not text:
        return fallback or date.today().isoformat()
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return text[:10]


def string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        if ";" in value:
            return tuple(item.strip() for item in value.split(";") if item.strip())
        return (value.strip(),) if value.strip() else ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def score_bp(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        score = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return int((score * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
