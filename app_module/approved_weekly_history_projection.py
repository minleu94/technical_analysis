"""讀取經具名 owner 核准的外部 weekly history 唯讀投影。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "approved-weekly-history-projection.v1"


@dataclass(frozen=True)
class ApprovedWeeklyHistoryProjection:
    records: tuple[dict[str, str], ...]
    path: Path


def load_approved_weekly_history_projection(path: str | Path | None) -> ApprovedWeeklyHistoryProjection | None:
    if path is None or not str(path).strip():
        return None
    resolved = Path(path).expanduser().resolve()
    payload: dict[str, Any] = json.loads(resolved.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("approved weekly history projection schema 不支援")
    if payload.get("formal_credit_authorized") is not False:
        raise ValueError("approved weekly history projection 不得授權 formal credit")
    records: list[dict[str, str]] = []
    for item in payload.get("records", []):
        if not isinstance(item, dict):
            raise ValueError("approved weekly history projection record 無效")
        required = ("review_id", "review_hash", "period_start", "period_end", "owner_role", "approved_at")
        if any(not str(item.get(key, "")).strip() for key in required):
            raise ValueError("approved weekly history projection 缺少具名 owner 或 review 證據")
        if item.get("status") != "approved_weekly_review":
            continue
        records.append({key: str(item[key]) for key in required})
    return ApprovedWeeklyHistoryProjection(records=tuple(records), path=resolved)
