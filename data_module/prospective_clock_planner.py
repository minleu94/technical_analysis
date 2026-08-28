"""Read-only planner for the next prospective formal simulation clock.

The planner consumes an explicit, already-captured TWSE/TPEX calendar bundle.  It
never downloads a calendar, chooses a same-day override, writes a formal clock,
or discovers and mutates controlled input paths.  Its result is a proposal only;
``publish_prospective_formal_clock.py`` remains the create-only publisher after
the owner has reviewed the concrete identity and source evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from data_module.prospective_formal_clock import canonical_json, payload_hash


PROSPECTIVE_CLOCK_PLANNING_SCHEMA_VERSION = (
    "prospective-formal-clock-planning.v1"
)
OFFICIAL_CALENDAR_BUNDLE_SCHEMA_VERSION = "official-trading-calendar-bundle.v1"
TAIPEI_TIMEZONE = ZoneInfo("Asia/Taipei")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLOCK_DATE_RE = re.compile(r"^clock:prospective:(?P<date>\d{8})(?::|$)")


class ProspectiveClockPlanningError(ValueError):
    """Calendar or planning input violates the fail-closed contract."""


@dataclass(frozen=True)
class _CalendarDay:
    """已驗證的一日雙市場官方日曆證據。"""

    trading_day: date
    twse: Mapping[str, object]
    tpex: Mapping[str, object]

    @property
    def is_common_trading_day(self) -> bool:
        return bool(self.twse["is_trading_day"]) and bool(
            self.tpex["is_trading_day"]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.trading_day.isoformat(),
            "twse": dict(self.twse),
            "tpex": dict(self.tpex),
        }


def plan_next_prospective_clock(
    *,
    now: datetime,
    owner_decision_timestamp: datetime,
    calendar_evidence: Mapping[str, object],
    minimum_preparation_days: int = 1,
    lookahead_days: int = 31,
    existing_clock_ids: Sequence[str] = (),
    clock_id_prefix: str = "clock:prospective:",
) -> dict[str, object]:
    """選出下一個可供 owner 審閱的共同交易日 proposal。

    ``minimum_preparation_days`` 以台北「日曆日」距離表示：值為 1 代表
    activation 必須嚴格晚於目前台北日期，且目前日期保留為 preparation
    window 的第一天。這與既有 prospective restart 的 8/27 → 8/28
    preparation-day 定義一致。
    """

    now_aware = _require_aware(now, "now")
    owner_aware = _require_aware(
        owner_decision_timestamp,
        "owner_decision_timestamp",
    )
    if owner_aware > now_aware:
        raise ProspectiveClockPlanningError(
            "owner_decision_timestamp cannot be in the future"
        )
    if (
        isinstance(minimum_preparation_days, bool)
        or not isinstance(minimum_preparation_days, int)
        or minimum_preparation_days < 1
    ):
        raise ProspectiveClockPlanningError(
            "minimum_preparation_days must be a positive integer"
        )
    if (
        isinstance(lookahead_days, bool)
        or not isinstance(lookahead_days, int)
        or lookahead_days < 1
    ):
        raise ProspectiveClockPlanningError(
            "lookahead_days must be a positive integer"
        )
    if not isinstance(clock_id_prefix, str) or not clock_id_prefix.strip():
        raise ProspectiveClockPlanningError("clock_id_prefix must be non-empty text")
    prefix = clock_id_prefix.strip()
    if not prefix.endswith(":"):
        prefix += ":"

    calendar_days = _parse_calendar_bundle(calendar_evidence)
    now_taipei = now_aware.astimezone(TAIPEI_TIMEZONE)
    owner_taipei = owner_aware.astimezone(TAIPEI_TIMEZONE)
    today = now_taipei.date()
    earliest = today + timedelta(days=minimum_preparation_days)
    latest = today + timedelta(days=lookahead_days)
    existing_dates = _existing_clock_dates(existing_clock_ids)

    candidates = [
        item
        for item in calendar_days
        if earliest <= item.trading_day <= latest
        and item.trading_day > owner_taipei.date()
        and item.is_common_trading_day
        and item.trading_day not in existing_dates
    ]
    candidates.sort(key=lambda item: item.trading_day)

    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_CLOCK_PLANNING_SCHEMA_VERSION,
        "status": "blocked",
        "generated_at": now_aware.isoformat(),
        "now_taipei": now_taipei.isoformat(),
        "owner_decision_timestamp": owner_aware.isoformat(),
        "decision_timezone": "Asia/Taipei",
        "minimum_preparation_days": minimum_preparation_days,
        "lookahead_days": lookahead_days,
        "earliest_activation_date": earliest.isoformat(),
        "latest_activation_date": latest.isoformat(),
        "calendar_bundle_hash": payload_hash(calendar_evidence),
        "calendar_day_count": len(calendar_days),
        "existing_clock_ids": [str(item) for item in existing_clock_ids],
        "safety": {
            "read_only": True,
            "formal_clock_created": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "historical_backfill_claimed": False,
            "same_day_preopen_override_selected": False,
            "secret_values_emitted": False,
        },
    }

    if not candidates:
        body["blockers"] = [
            "no_unconsumed_common_trading_day_in_future_calendar_window"
        ]
        body["next_action"] = (
            "provide a fresh official TWSE/TPEX calendar bundle or extend the "
            "lookahead window; do not reuse an elapsed clock"
        )
        return _with_plan_hash(body)

    selected = candidates[0]
    activation = selected.trading_day
    clock_id = f"{prefix}{activation:%Y%m%d}:planned-v1"
    preparation_start = today
    preparation_end = activation - timedelta(days=1)
    body.update(
        {
            "status": "candidate_ready",
            "clock_id": clock_id,
            "activation_trading_day": activation.isoformat(),
            "preparation_window": {
                "start": preparation_start.isoformat(),
                "end": preparation_end.isoformat(),
                "calendar_days": (preparation_end - preparation_start).days + 1,
            },
            "selected_calendar_evidence": selected.to_dict(),
            "candidate_count": len(candidates),
            "blockers": [],
            "next_action": (
                "owner review the selected date and hashes, then use the "
                "create-only clock publisher; this proposal is not a formal input"
            ),
        }
    )
    return _with_plan_hash(body)


def _with_plan_hash(body: Mapping[str, object]) -> dict[str, object]:
    result = dict(body)
    result["plan_hash"] = payload_hash(result)
    return result


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ProspectiveClockPlanningError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveClockPlanningError(f"{field_name} must include timezone")
    return value


def _parse_calendar_bundle(value: Mapping[str, object]) -> tuple[_CalendarDay, ...]:
    if not isinstance(value, Mapping):
        raise ProspectiveClockPlanningError("calendar evidence must be an object")
    if value.get("schema_version") != OFFICIAL_CALENDAR_BUNDLE_SCHEMA_VERSION:
        raise ProspectiveClockPlanningError(
            "calendar evidence schema_version must be "
            f"{OFFICIAL_CALENDAR_BUNDLE_SCHEMA_VERSION}"
        )
    raw_days = value.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise ProspectiveClockPlanningError(
            "calendar evidence days must be a non-empty array"
        )

    parsed: list[_CalendarDay] = []
    seen: set[date] = set()
    for index, raw_day in enumerate(raw_days):
        if not isinstance(raw_day, Mapping):
            raise ProspectiveClockPlanningError(
                f"calendar evidence day {index} must be an object"
            )
        trading_day = _parse_date(raw_day.get("date"), f"days[{index}].date")
        if trading_day in seen:
            raise ProspectiveClockPlanningError(
                f"calendar evidence contains duplicate date {trading_day.isoformat()}"
            )
        seen.add(trading_day)
        twse = _parse_market(raw_day, "twse", index)
        tpex = _parse_market(raw_day, "tpex", index)
        parsed.append(_CalendarDay(trading_day, twse, tpex))
    return tuple(sorted(parsed, key=lambda item: item.trading_day))


def _parse_market(
    row: Mapping[str, object],
    market: str,
    index: int,
) -> dict[str, object]:
    raw = row.get(market)
    if not isinstance(raw, Mapping):
        raise ProspectiveClockPlanningError(
            f"days[{index}].{market} must be an object"
        )
    flag = raw.get("is_trading_day")
    if not isinstance(flag, bool):
        raise ProspectiveClockPlanningError(
            f"days[{index}].{market}.is_trading_day must be boolean"
        )
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ProspectiveClockPlanningError(
            f"days[{index}].{market}.source must be non-empty text"
        )
    source_hash = raw.get("source_hash")
    if not isinstance(source_hash, str) or _SHA256_RE.fullmatch(source_hash) is None:
        raise ProspectiveClockPlanningError(
            f"days[{index}].{market}.source_hash must be sha256: plus 64 lowercase hex"
        )
    return {
        "is_trading_day": flag,
        "source": source.strip(),
        "source_hash": source_hash,
    }


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveClockPlanningError(f"{field_name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ProspectiveClockPlanningError(
            f"{field_name} must be YYYY-MM-DD"
        ) from error
    if parsed.isoformat() != value:
        raise ProspectiveClockPlanningError(f"{field_name} must be YYYY-MM-DD")
    return parsed


def _existing_clock_dates(values: Sequence[str]) -> set[date]:
    dates: set[date] = set()
    for value in values:
        if not isinstance(value, str):
            raise ProspectiveClockPlanningError("existing_clock_ids must contain text")
        match = _CLOCK_DATE_RE.match(value.strip())
        if match is None:
            continue
        try:
            dates.add(datetime.strptime(match.group("date"), "%Y%m%d").date())
        except ValueError as error:
            raise ProspectiveClockPlanningError(
                f"existing clock id contains invalid date: {value}"
            ) from error
    return dates
