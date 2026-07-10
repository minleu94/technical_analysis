from datetime import datetime, timedelta
from pathlib import Path
import re

def convert_date_format(value: str, to_api: bool = False) -> str | None:
    try:
        if re.match(r"^\d{8}$", value): return f"{int(value[:4])-1911:03d}/{value[4:6]}/{value[6:]}" if to_api else value
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            date = datetime.strptime(value, "%Y-%m-%d"); return f"{date.year-1911:03d}/{date.month:02d}/{date.day:02d}" if to_api else date.strftime("%Y%m%d")
        match = re.match(r"^(\d{3})/(\d{2})/(\d{2})$", value)
        if match: return value if to_api else f"{int(match.group(1))+1911}{match.group(2)}{match.group(3)}"
    except ValueError: pass
    return None

def convert_to_datetime(value: str) -> datetime | None:
    normalized = convert_date_format(value)
    try: return datetime.strptime(normalized, "%Y%m%d") if normalized else None
    except ValueError: return None

def convert_roc_date(value: str) -> str:
    parts = value.split("/")
    try: return f"{int(parts[0])+1911}/{parts[1]}/{parts[2]}" if len(parts) == 3 else value
    except (ValueError, TypeError): return value


def daily_price_file(directory: Path, value: str) -> Path:
    normalized = convert_date_format(value)
    if normalized is None:
        raise ValueError(f"無效的日期格式: {value}")
    return directory / f"{normalized}.csv"


def default_market_start_date(*, now: datetime | None = None) -> str:
    current = now or datetime.today()
    return (current - timedelta(days=30)).strftime("%Y-%m-%d")


def normalize_market_date_range(
    start_date: str | None,
    end_date: str | None,
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    current = now or datetime.now()
    today = current.strftime("%Y-%m-%d")
    resolved_end = end_date or today
    resolved_start = start_date or default_market_start_date(now=current)
    start = datetime.strptime(resolved_start, "%Y-%m-%d")
    end = datetime.strptime(resolved_end, "%Y-%m-%d")
    if start > end:
        resolved_start, resolved_end = resolved_end, resolved_start
    if resolved_end > today:
        resolved_end = today
    if resolved_start > today:
        resolved_start = today
    return resolved_start, resolved_end


def recent_date_range(days: int, *, now: datetime | None = None) -> tuple[str, str]:
    current = now or datetime.today()
    return (
        (current - timedelta(days=days)).strftime("%Y-%m-%d"),
        current.strftime("%Y-%m-%d"),
    )


def year_to_date_start(*, now: datetime | None = None) -> str:
    current = now or datetime.today()
    return current.replace(month=1, day=1).strftime("%Y-%m-%d")


def date_range_days(start_date: str, end_date: str) -> list[datetime]:
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if start > end:
        start, end = end, start
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
