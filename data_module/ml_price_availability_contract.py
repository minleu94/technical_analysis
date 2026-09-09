"""Research-only contract for daily rows whose price inputs are unavailable.

This module deliberately does not infer why a price is unavailable.  It keeps
the source row and its date so downstream feature/label builders can exclude
the affected window without filling values or treating surrounding dates as
adjacent observations.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


PRICE_AVAILABILITY_CONTRACT_VERSION = "ml-daily-price-availability.v1"
PRICE_FIELDS: tuple[str, ...] = ("open", "high", "low", "close")
_UNAVAILABLE_MARKERS = frozenset({"", "--", "—", "－", "N/A", "NA", "null", "None"})


def _canonical_date(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be an ISO date string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a canonical YYYY-MM-DD date") from exc
    canonical = parsed.isoformat()
    if value != canonical:
        raise ValueError(f"{field_name} must be a canonical YYYY-MM-DD date")
    return canonical


def _canonical_window(
    values: Sequence[str],
    *,
    field_name: str,
    anchor_date: str,
) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of ISO date strings")
    normalised = sorted(
        {_canonical_date(value, field_name=field_name) for value in values}
    )
    if field_name == "feature_window_dates" and anchor_date not in normalised:
        raise ValueError("feature_window_dates must include anchor_date")
    return normalised


def _field_status(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in _UNAVAILABLE_MARKERS:
            return "missing_marker"
        value = stripped
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "invalid"
    if not numeric.is_finite() or numeric <= 0:
        return "invalid"
    return "available"


def _canonical_available_at(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("available_at must be an ISO-8601 string or None")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("available_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("available_at must include a timezone")
    return parsed.isoformat().replace("+00:00", "Z")


def build_price_unavailable_research_contract(
    *,
    symbol: str,
    date_iso: str,
    raw_row: Mapping[str, Any],
    feature_window_dates: Sequence[str] | None = None,
    label_window_dates: Sequence[str] | None = None,
    source_file: Mapping[str, Any] | None = None,
    available_at: str | None = None,
) -> dict[str, Any]:
    """Build a bounded research disposition for a row with unavailable prices.

    ``raw_row`` is copied verbatim into the result.  The caller must provide
    explicit feature/label dates when it knows the downstream horizon.  The
    default anchor-only window is intentionally marked incomplete so callers
    cannot silently use it as a fully expanded training window.
    """

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol must be a non-empty string")
    anchor_date = _canonical_date(date_iso, field_name="date_iso")
    if not isinstance(raw_row, Mapping):
        raise TypeError("raw_row must be a mapping")

    field_status = {field: _field_status(raw_row.get(field)) for field in PRICE_FIELDS}
    missing_mask = {
        field: status != "available" for field, status in field_status.items()
    }
    if not any(missing_mask.values()):
        raise ValueError("raw_row has no unavailable price field")

    feature_dates = _canonical_window(
        (anchor_date,) if feature_window_dates is None else feature_window_dates,
        field_name="feature_window_dates",
        anchor_date=anchor_date,
    )
    label_dates = _canonical_window(
        () if label_window_dates is None else label_window_dates,
        field_name="label_window_dates",
        anchor_date=anchor_date,
    )
    affected_dates = sorted(set(feature_dates).union(label_dates))
    availability_timestamp = _canonical_available_at(available_at)
    feature_window_complete = feature_window_dates is not None
    label_window_complete = label_window_dates is not None
    source_quality_research_eligible = not any(
        status == "invalid" for status in field_status.values()
    )

    return {
        "schema_version": PRICE_AVAILABILITY_CONTRACT_VERSION,
        "status": "price_unavailable",
        "symbol": symbol,
        "date": anchor_date,
        "raw_row": dict(raw_row),
        "price_fields": list(PRICE_FIELDS),
        "field_status": field_status,
        "missing_mask": missing_mask,
        "volume_shares": raw_row.get("volume", raw_row.get("volume_shares")),
        "availability": {
            "available_at": availability_timestamp,
            "availability_observed": availability_timestamp is not None,
            "cause_inferred": False,
            "historical_backfill": False,
        },
        "affected_window": {
            "feature_window_dates": feature_dates,
            "label_window_dates": label_dates,
            "affected_dates": affected_dates,
            "window_scope": (
                "explicit"
                if feature_window_dates is not None or label_window_dates is not None
                else "anchor_only"
            ),
            "feature_window_complete": feature_window_complete,
            "label_window_complete": label_window_complete,
            "horizon_expansion_required": not (
                feature_window_complete and label_window_complete
            ),
            "adjacency_break_at_anchor": True,
            "surrounding_rows_may_not_be_bridged": True,
        },
        "disposition": {
            "research_only": True,
            "include_price_feature_row": False,
            "include_price_label_row": False,
            "preserve_source_row": True,
            "zero_fill": False,
            "drop_source_row": False,
            "require_official_cause": False,
            "source_quality_research_eligible": source_quality_research_eligible,
            "source_quality_disposition": (
                "price_unavailable_missing_or_marker"
                if source_quality_research_eligible
                else "invalid_price_requires_quarantine"
            ),
        },
        "source_file": None if source_file is None else dict(source_file),
    }


def validate_price_unavailable_research_contract(
    contract: Mapping[str, Any],
) -> tuple[str, str, frozenset[str]]:
    """Validate a serialized contract before a feature/label caller consumes it.

    Rebuilding from the preserved raw row prevents a caller from trusting a
    self-declared missing mask or affected window.  The return value is the
    symbol, anchor date, and the validated dates that must remain blocked.
    """

    if not isinstance(contract, Mapping):
        raise TypeError("price availability contract must be a mapping")
    if contract.get("schema_version") != PRICE_AVAILABILITY_CONTRACT_VERSION:
        raise ValueError("price availability contract schema mismatch")
    if contract.get("status") != "price_unavailable":
        raise ValueError("price availability contract status mismatch")
    symbol = contract.get("symbol")
    date_iso = contract.get("date")
    raw_row = contract.get("raw_row")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("price availability contract symbol is invalid")
    if not isinstance(date_iso, str):
        raise ValueError("price availability contract date is invalid")
    if not isinstance(raw_row, Mapping):
        raise ValueError("price availability contract raw_row is invalid")
    affected_window = contract.get("affected_window")
    if not isinstance(affected_window, Mapping):
        raise ValueError("price availability contract affected_window is invalid")
    feature_dates = affected_window.get("feature_window_dates")
    label_dates = affected_window.get("label_window_dates")
    if not isinstance(feature_dates, list) or not isinstance(label_dates, list):
        raise ValueError("price availability contract windows must be lists")
    feature_window_complete = affected_window.get("feature_window_complete")
    label_window_complete = affected_window.get("label_window_complete")
    if not isinstance(feature_window_complete, bool) or not isinstance(
        label_window_complete, bool
    ):
        raise ValueError("price availability contract window completeness is invalid")
    availability = contract.get("availability")
    if not isinstance(availability, Mapping):
        raise ValueError("price availability contract availability is invalid")
    source_file = contract.get("source_file")
    if source_file is not None and not isinstance(source_file, Mapping):
        raise ValueError("price availability contract source_file is invalid")
    rebuilt = build_price_unavailable_research_contract(
        symbol=symbol,
        date_iso=date_iso,
        raw_row=raw_row,
        feature_window_dates=(
            tuple(feature_dates) if feature_window_complete else None
        ),
        label_window_dates=tuple(label_dates) if label_window_complete else None,
        source_file=source_file,
        available_at=availability.get("available_at"),
    )
    for key in (
        "schema_version",
        "status",
        "symbol",
        "date",
        "raw_row",
        "price_fields",
        "field_status",
        "missing_mask",
        "volume_shares",
        "availability",
        "affected_window",
        "disposition",
        "source_file",
    ):
        if contract.get(key) != rebuilt.get(key):
            raise ValueError(f"price availability contract {key} mismatch")
    affected_dates = affected_window.get("affected_dates")
    if not isinstance(affected_dates, list):
        raise ValueError("price availability contract affected_dates is invalid")
    return symbol, date_iso, frozenset(affected_dates)


__all__ = [
    "PRICE_AVAILABILITY_CONTRACT_VERSION",
    "PRICE_FIELDS",
    "build_price_unavailable_research_contract",
    "validate_price_unavailable_research_contract",
]
