"""Runtime 事件時間的解析與正規化。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_runtime_event_timestamp(value: Any) -> datetime | None:
    """只接受可解析的來源時間；缺值時由呼叫端明確標示為未知。"""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
