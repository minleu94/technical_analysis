from datetime import datetime
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
