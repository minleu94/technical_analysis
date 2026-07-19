"""TPEx S46 disposal CSV parser with the official T-date / T+1 availability rule."""
from __future__ import annotations

import csv
from datetime import date, timedelta
from io import StringIO
from typing import Iterable


REQUIRED_FIELDS = ("公布日期", "證券代號", "處置開始日期", "處置結束日期", "處置原因(英文說明)", "處置內容(英文說明)")


def parse_s46_disposal_csv(*, payload: bytes, production_date: date) -> tuple[dict[str, str], ...]:
    """Return normalized S46 rows; caller must obtain production date from official file footer."""
    rows = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))
    if not rows or not set(REQUIRED_FIELDS).issubset(rows[0]):
        raise ValueError("S46 CSV required fields missing")
    available_date = (production_date + timedelta(days=1)).isoformat()
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not set(REQUIRED_FIELDS).issubset(row) or not str(row["證券代號"] or "").strip():
            raise ValueError("S46 CSV malformed record")
        normalized.append({
            "symbol": str(row["證券代號"]).strip(),
            "announcement_date": str(row["公布日期"]).strip(),
            "effective_from": str(row["處置開始日期"]).strip(),
            "effective_to": str(row["處置結束日期"]).strip(),
            "reason": str(row["處置原因(英文說明)"]).strip(),
            "content": str(row["處置內容(英文說明)"]).strip(),
            "production_date": production_date.isoformat(),
            "available_date": available_date,
        })
    return tuple(normalized)
