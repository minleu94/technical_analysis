"""TPEx S46 disposal CSV parser with the official T-date / T+1 availability rule."""
from __future__ import annotations

import csv
from datetime import date, timedelta
from io import StringIO
from typing import Iterable


REQUIRED_FIELDS = ("公告日期", "股票代號", "處置起日", "處置迄日", "處置原因", "處置內容")


def parse_s46_disposal_csv(*, payload: bytes) -> tuple[dict[str, str], ...]:
    """Return normalized S46 rows and derive availability from the official footer's T date."""
    lines = payload.decode("utf-8-sig").splitlines()
    footer = {key.strip(): value.strip() for line in lines if ":" in line for key, value in [line.split(":", 1)]}
    raw_date = footer.get("資料日期")
    if raw_date is None or len(raw_date) != 8 or not raw_date.isdigit():
        raise ValueError("S46 CSV production date footer missing")
    production_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:]))
    content_lines = [line for line in lines if line and not line.startswith("資料日期:") and not line.startswith("資料產製時間:") and not line.startswith("資料筆數:")]
    rows = list(csv.DictReader(StringIO("\n".join(content_lines))))
    if not rows or not set(REQUIRED_FIELDS).issubset(rows[0]):
        raise ValueError("S46 CSV required fields missing")
    available_date = (production_date + timedelta(days=1)).isoformat()
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not set(REQUIRED_FIELDS).issubset(row) or not str(row["股票代號"] or "").strip():
            raise ValueError("S46 CSV malformed record")
        normalized.append({
            "symbol": str(row["股票代號"]).strip(),
            "announcement_date": str(row["公告日期"]).strip(),
            "effective_from": str(row["處置起日"]).strip(),
            "effective_to": str(row["處置迄日"]).strip(),
            "reason": str(row["處置原因"]).strip(),
            "content": str(row["處置內容"]).strip(),
            "production_date": production_date.isoformat(),
            "available_date": available_date,
        })
    return tuple(normalized)
