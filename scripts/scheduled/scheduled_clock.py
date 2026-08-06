from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


SCHEDULE_TIMEZONE = ZoneInfo("America/Los_Angeles")


def scheduled_now() -> datetime:
    return datetime.now(SCHEDULE_TIMEZONE)


def scheduled_today() -> date:
    return scheduled_now().date()
