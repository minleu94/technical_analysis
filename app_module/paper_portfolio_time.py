"""台灣市場資料共用的交易日曆時區邊界。"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


TAIWAN_MARKET_TIMEZONE = ZoneInfo("Asia/Taipei")
# 保留既有名稱，避免已存在的 Paper Portfolio 呼叫端改變行為。
PAPER_PORTFOLIO_TIMEZONE = TAIWAN_MARKET_TIMEZONE


def taiwan_market_today() -> date:
    """回傳台灣市場語境下的今天，避免 UTC／主機日期跨日誤判。"""

    return datetime.now(TAIWAN_MARKET_TIMEZONE).date()


def paper_portfolio_today() -> date:
    """回傳 Paper Portfolio 使用的台灣市場日期。"""

    return taiwan_market_today()


__all__ = [
    "PAPER_PORTFOLIO_TIMEZONE",
    "TAIWAN_MARKET_TIMEZONE",
    "paper_portfolio_today",
    "taiwan_market_today",
]
