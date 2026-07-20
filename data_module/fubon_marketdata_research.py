"""富邦唯讀行情資料的 research-only P0 補強 adapter。

這個模組絕不寫入正式市場資料庫，也不呼叫下單、帳務或部位 API。富邦行情
資料是研究觀測，不是交易所／MOPS 的公告證據；因此所有輸出都保留
``first_observed_only`` 的可得性降級訊號。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any

from data_module.p0_source_candidate_contracts import NormalizedP0Observation


FUBON_SOURCE_VERSION = "fubon-neo-marketdata.v2.2.8"
FUBON_RESEARCH_WARNING = "fubon_marketdata_research_only_not_official_announcement"


@dataclass(frozen=True)
class FubonResearchProjection:
    """Sanitized candidate projection; no credentials or SDK object is retained."""

    observations: tuple[NormalizedP0Observation, ...]
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "fubon-p0-research-projection.v1",
            "source": "fubon.marketdata",
            "source_version": FUBON_SOURCE_VERSION,
            "research_only": True,
            "formal_oos_allowed": False,
            "production_scheduler_allowed": False,
            "production_blend_alpha_bp": 0,
            "observations": [row.to_dict() for row in self.observations],
            "diagnostics": list(self.diagnostics),
        }


def project_ticker(
    payload: Mapping[str, Any],
    *,
    fetched_at: datetime,
    quote_payload: Mapping[str, Any] | None = None,
) -> FubonResearchProjection:
    """Project one documented ``intraday/ticker`` response into P0 candidates.

    The response has no official publication timestamp.  It is therefore suitable
    only for an append-only, decision-time research capture.
    """
    _require_aware(fetched_at)
    symbol = _require_text(payload, "symbol")
    observation_date = _require_date(payload.get("date"), fallback=fetched_at.date().isoformat())
    raw_hash = _payload_hash({"ticker": dict(payload), "quote": dict(quote_payload or {})})
    base_metadata = {
        "exchange": _optional_text(payload.get("exchange")),
        "market": _optional_text(payload.get("market")),
        "capture_kind": "fubon_intraday_ticker",
        "availability_policy": "first_observed_only_not_official_announcement",
    }
    observations: list[NormalizedP0Observation] = []
    diagnostics: list[str] = [FUBON_RESEARCH_WARNING]

    is_disposition = _optional_bool(payload.get("isDisposition"))
    if is_disposition is True:
        observations.append(
            _observation(
                source_id="microstructure.disposition_stock",
                symbol=symbol,
                observation_date=observation_date,
                fetched_at=fetched_at,
                raw_hash=raw_hash,
                quantities={"is_disposition": 1},
                metadata=base_metadata,
            )
        )
    elif is_disposition is None:
        diagnostics.append("fubon_ticker_missing:isDisposition")

    interval = _optional_nonnegative_int(payload.get("matchingInterval"))
    if interval is not None and interval > 0:
        observations.append(
            _observation(
                source_id="microstructure.periodic_call_auction",
                symbol=symbol,
                observation_date=observation_date,
                fetched_at=fetched_at,
                raw_hash=raw_hash,
                quantities={"matching_interval_seconds": interval},
                metadata=base_metadata,
            )
        )
    elif interval is None:
        diagnostics.append("fubon_ticker_missing:matchingInterval")

    security_status = _optional_text(payload.get("securityStatus"))
    if security_status == "SUSPENDED":
        observations.append(
            _observation(
                source_id="microstructure.suspended_halt_resume",
                symbol=symbol,
                observation_date=observation_date,
                fetched_at=fetched_at,
                raw_hash=raw_hash,
                quantities={"is_suspended": 1},
                metadata={**base_metadata, "security_status": security_status},
            )
        )
    elif security_status is None:
        diagnostics.append("fubon_ticker_missing:securityStatus")

    if quote_payload is not None:
        lock = _limit_lock(quote_payload, payload)
        if lock is None:
            diagnostics.append("fubon_quote_insufficient_for_limit_lock")
        else:
            observations.append(
                _observation(
                    source_id="microstructure.limit_lock",
                    symbol=symbol,
                    observation_date=observation_date,
                    fetched_at=fetched_at,
                    raw_hash=raw_hash,
                    quantities=lock,
                    metadata={**base_metadata, "capture_kind": "fubon_ticker_and_quote"},
                )
            )
    else:
        diagnostics.append("fubon_quote_not_captured_limit_lock_unavailable")

    # The documented ticker contract has no full-delivery indicator.
    diagnostics.append("fubon_no_documented_full_delivery_indicator")
    return FubonResearchProjection(tuple(observations), tuple(dict.fromkeys(diagnostics)))


def project_dividends(
    rows: Sequence[Mapping[str, Any]], *, fetched_at: datetime
) -> FubonResearchProjection:
    """Project documented corporate-actions dividends rows as candidate-only events."""
    return _project_corporate_rows(
        rows,
        fetched_at=fetched_at,
        source_id="corporate_action.ex_dividend_timeline",
        event_kind="fubon_corporate_actions_dividends",
        required_event_types=None,
    )


def project_capital_changes(
    rows: Sequence[Mapping[str, Any]], *, fetched_at: datetime
) -> FubonResearchProjection:
    """Project documented capital-reduction/par-value/split rows as candidates."""
    return _project_corporate_rows(
        rows,
        fetched_at=fetched_at,
        source_id="corporate_action.reduction_split_par_value",
        event_kind="fubon_corporate_actions_capital_changes",
        required_event_types={"capital_reduction", "par_value_change", "etf_split_or_merge"},
    )


def _project_corporate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fetched_at: datetime,
    source_id: str,
    event_kind: str,
    required_event_types: set[str] | None,
) -> FubonResearchProjection:
    _require_aware(fetched_at)
    observations: list[NormalizedP0Observation] = []
    diagnostics: list[str] = [FUBON_RESEARCH_WARNING]
    for row in rows:
        try:
            symbol = _require_text(row, "symbol")
            event_date = _require_date(row.get("date") or row.get("effectiveDate"), fallback=None)
            action_type = _optional_text(row.get("actionType"))
            if required_event_types is not None and action_type not in required_event_types:
                diagnostics.append(f"fubon_capital_change_skipped_action_type:{action_type or 'missing'}")
                continue
            raw_hash = _payload_hash(dict(row))
            metadata = {
                "capture_kind": event_kind,
                "exchange": _optional_text(row.get("exchange")),
                "action_type": action_type,
                "event_date": event_date,
                "availability_policy": "first_observed_only_not_official_announcement",
            }
            observations.append(
                _observation(
                    source_id=source_id,
                    symbol=symbol,
                    observation_date=event_date,
                    fetched_at=fetched_at,
                    raw_hash=raw_hash,
                    quantities={},
                    metadata=metadata,
                )
            )
        except (TypeError, ValueError) as exc:
            diagnostics.append(f"fubon_corporate_action_row_rejected:{type(exc).__name__}")
    return FubonResearchProjection(tuple(observations), tuple(dict.fromkeys(diagnostics)))


def _observation(**kwargs: Any) -> NormalizedP0Observation:
    metadata = dict(kwargs.pop("metadata"))
    fetched_at = kwargs.pop("fetched_at")
    raw_payload_sha256 = kwargs.pop("raw_hash")
    return NormalizedP0Observation.build(
        source_version=FUBON_SOURCE_VERSION,
        publication_at=None,
        first_observed_at=fetched_at,
        raw_payload_sha256=raw_payload_sha256,
        warnings=(FUBON_RESEARCH_WARNING,),
        metadata=metadata,
        period="event",
        **kwargs,
    )


def _limit_lock(quote: Mapping[str, Any], ticker: Mapping[str, Any]) -> dict[str, int] | None:
    last_price = _decimal(quote.get("lastPrice") if quote.get("lastPrice") is not None else quote.get("close"))
    limit_up = _decimal(ticker.get("limitUpPrice"))
    limit_down = _decimal(ticker.get("limitDownPrice"))
    if last_price is None or limit_up is None or limit_down is None:
        return None
    return {
        "limit_up_locked": int(last_price == limit_up),
        "limit_down_locked": int(last_price == limit_down),
    }


def _payload_hash(value: Mapping[str, Any]) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return sha256(rendered.encode("utf-8")).hexdigest()


def _require_text(payload: Mapping[str, Any], key: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise ValueError(f"missing {key}")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _require_date(value: Any, *, fallback: str | None) -> str:
    normalized = _optional_text(value) or fallback
    if normalized is None:
        raise ValueError("missing event date")
    try:
        return datetime.fromisoformat(normalized[:10]).date().isoformat()
    except ValueError as exc:
        raise ValueError("invalid event date") from exc


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fetched_at must include timezone")
