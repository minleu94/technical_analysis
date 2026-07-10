from datetime import datetime
from pathlib import Path

from data_module.market_date_utils import (
    convert_date_format,
    convert_to_datetime,
    convert_roc_date,
    daily_price_file,
    date_range_days,
    normalize_market_date_range,
    recent_date_range,
    year_to_date_start,
)
def test_date_utilities():
    assert convert_date_format("113/03/29") == "20240329"
    assert convert_date_format("2024-03-29", True) == "113/03/29"
    assert convert_to_datetime("20240329").strftime("%Y-%m-%d") == "2024-03-29"
    assert convert_roc_date("111/01/04") == "2022/01/04"


def test_date_range_helpers_normalize_swap_clamp_and_build_paths() -> None:
    now = datetime(2026, 1, 15)

    assert normalize_market_date_range("2026-01-20", "2026-01-10", now=now) == ("2026-01-10", "2026-01-15")
    assert recent_date_range(30, now=now) == ("2025-12-16", "2026-01-15")
    assert year_to_date_start(now=now) == "2026-01-01"
    assert [item.strftime("%Y-%m-%d") for item in date_range_days("2026-01-02", "2026-01-04")] == ["2026-01-02", "2026-01-03", "2026-01-04"]
    assert daily_price_file(Path("daily"), "2026-01-04") == Path("daily/20260104.csv")
