"""官方交易日曆判定介面。

嚴禁單純以「週一至週五」當作台股交易日。
本模組提供優先採信官方證據（DB 歷史市場指數紀錄與 TWSE/TPEx 官方回應）的判定機制。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import sqlite3
from typing import Optional, Tuple

from data_module.config import TWStockConfig
from data_module.official_phase3c_fetcher import safe_request

logger = logging.getLogger(__name__)


class OfficialTradingCalendar:
    """台股官方交易日判定器。"""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        if db_path is None:
            config = TWStockConfig()
            self.db_path = Path(config.db_file)
        else:
            self.db_path = Path(db_path)

    def is_official_trading_day(
        self, target_date: date, allow_online_probe: bool = True
    ) -> Tuple[Optional[bool], str]:
        """判定指定日期是否為台股官方交易日。

        Returns:
            (is_trading_day, reason_code)
            - (True, "twstock_db_market_indices_evidence")
            - (True, "twse_online_probe_evidence")
            - (False, "twse_official_closed_or_holiday")
            - (None, "lacks_official_evidence")
        """
        date_yyyymmdd = target_date.strftime("%Y%m%d")

        # 僅採 market_indices 的交易日紀錄作為本地證據。daily_prices 曾經
        # 出現過非交易日原始檔，不能單獨用來證明交易日。
        if self.db_path.exists():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    columns = {
                        str(row[1])
                        for row in cursor.execute("PRAGMA table_info(market_indices)")
                    }
                    date_column = next(
                        (
                            column
                            for column in ("日期", "trade_date", "date")
                            if column in columns
                        ),
                        None,
                    )
                    if date_column is not None:
                        count = cursor.execute(
                            f'SELECT COUNT(*) FROM market_indices WHERE "{date_column}" = ?',
                            (date_yyyymmdd,),
                        ).fetchone()[0]
                        if count > 0:
                            return True, "twstock_db_market_indices_evidence"
            except Exception as exc:
                logger.warning(f"讀取 DB 交易日證據失敗 ({target_date}): {exc}")

        # 若不在本地 DB 中且不允許連線 probe，直接回報 lacks_official_evidence
        if not allow_online_probe:
            return None, "lacks_official_evidence"

        # 2. 進行連線 probe 驗證
        twse_url = "https://www.twse.com.tw/fund/T86"
        params = {"response": "json", "date": date_yyyymmdd, "selectType": "ALL"}
        try:
            resp = safe_request(twse_url, params=params, timeout_seconds=8, max_attempts=1)
            payload = resp.json()
            stat = str(payload.get("stat", "")).strip()

            if stat == "OK":
                return True, "twse_online_probe_evidence"
            if "沒有符合條件的資料" in stat or "No Data" in stat:
                return False, "twse_official_closed_or_holiday"
        except Exception as exc:
            logger.warning(f"線上 Probe 交易日失敗 ({target_date}): {exc}")

        return None, "lacks_official_evidence"

    def get_trading_days_in_range(
        self, start_date: date, end_date: date, allow_online_probe: bool = True
    ) -> list[dict[str, object]]:
        """掃描日期區間並傳回各日之官方交易日判定。

        Returns:
            [
                {
                    "date": date_obj,
                    "date_str": "YYYY-MM-DD",
                    "is_trading_day": True | False | None,
                    "reason_code": str
                }, ...
            ]
        """
        results = []
        current = start_date
        while current <= end_date:
            is_td, reason = self.is_official_trading_day(
                current, allow_online_probe=allow_online_probe
            )
            results.append({
                "date": current,
                "date_str": current.isoformat(),
                "is_trading_day": is_td,
                "reason_code": reason,
            })
            current += timedelta(days=1)
        return results
