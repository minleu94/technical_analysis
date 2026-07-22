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

    # Path security check: prevent loading from formal DB directories or invalid system paths
    path_str = str(resolved).replace("\\", "/").lower()
    if "/fa_data/sqlite" in path_str or "/data_root/sqlite" in path_str or "twstock.db" in path_str:
        raise ValueError("approved weekly history projection path 不得位於正式 SQLite 資料庫目錄中")

    if not resolved.exists():
        return None

    payload: dict[str, Any] = json.loads(resolved.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("approved weekly history projection schema 不支援")
    if payload.get("formal_credit_authorized") is not False:
        raise ValueError("approved weekly history projection 不得授權 formal credit")

    records: list[dict[str, str]] = []
    seen_periods: set[tuple[str, str]] = set()

    for item in payload.get("records", []):
        if not isinstance(item, dict):
            raise ValueError("approved weekly history projection record 無效")
        required = ("review_id", "review_hash", "period_start", "period_end", "owner_role", "approved_at")
        if any(not str(item.get(key, "")).strip() for key in required):
            raise ValueError("approved weekly history projection 缺少具名 owner 或 review 證據")
        if item.get("status") != "approved_weekly_review":
            continue

        p_start = str(item["period_start"]).strip()
        p_end = str(item["period_end"]).strip()
        period_key = (p_start, p_end)

        if period_key in seen_periods:
            raise ValueError(f"approved weekly history projection 包含重複的週期: {period_key}")
        seen_periods.add(period_key)

        records.append({key: str(item[key]) for key in (*required, "status")})

    return ApprovedWeeklyHistoryProjection(records=tuple(records), path=resolved)
