"""官方交易日曆判定介面。

嚴禁單純以「週一至週五」當作台股交易日。本模組以 TWSE 官方
``holidaySchedule`` 年度休市表為主要證據；只有在年度表成功取得且通過
結構驗證後，才可將「非週末且不在休市表」判為開市。官方表取得失敗時
一律回傳未知，不得以一般工作日推定開市。
"""

from __future__ import annotations

from datetime import date, timedelta
import logging
from pathlib import Path
import re
import sqlite3
from typing import Mapping, Optional, Tuple

from data_module.config import TWStockConfig
from data_module.official_phase3c_fetcher import safe_request

logger = logging.getLogger(__name__)

HOLIDAY_SCHEDULE_URL = (
    "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
)
_OFFICIAL_OPEN_MARKERS = (
    "開始交易",
    "最後交易",
    "恢復交易",
    "照常交易",
)


class OfficialTradingCalendar:
    """台股官方交易日判定器。"""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        if db_path is None:
            config = TWStockConfig()
            self.db_path = Path(config.db_file)
        else:
            self.db_path = Path(db_path)
        self._schedule_cache: dict[int, Mapping[date, bool] | None] = {}

    @staticmethod
    def _parse_roc_date(value: object, *, expected_year: int) -> date:
        digits = re.sub(r"\D", "", str(value))
        if len(digits) != 7:
            raise ValueError("TWSE holidaySchedule Date 必須是 7 碼民國日期")
        roc_year = int(digits[:3])
        result = date(roc_year + 1911, int(digits[3:5]), int(digits[5:7]))
        if result.year != expected_year:
            raise ValueError("TWSE holidaySchedule 回傳非查詢年度日期")
        return result

    @staticmethod
    def _row_is_open(row: Mapping[str, object]) -> bool:
        description = " ".join(
            str(row.get(field, "")) for field in ("Name", "Description")
        )
        return any(marker in description for marker in _OFFICIAL_OPEN_MARKERS)

    def _fetch_official_year_schedule(
        self,
        calendar_year: int,
    ) -> Mapping[date, bool] | None:
        if calendar_year in self._schedule_cache:
            return self._schedule_cache[calendar_year]

        try:
            response = safe_request(
                HOLIDAY_SCHEDULE_URL,
                params={"queryYear": str(calendar_year - 1911)},
                timeout_seconds=8,
                max_attempts=1,
            )
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                raise ValueError("TWSE holidaySchedule 必須回傳非空 array")

            schedule: dict[date, bool] = {}
            valid_rows = 0
            for raw_row in payload:
                if not isinstance(raw_row, dict) or "Date" not in raw_row:
                    raise ValueError("TWSE holidaySchedule row 缺少 Date")
                row_date = self._parse_roc_date(
                    raw_row["Date"],
                    expected_year=calendar_year,
                )
                valid_rows += 1
                # 同日若同時出現休市說明與「恢復／照常交易」說明，以明確
                # 的開市說明優先；週末仍在外層規則固定判為休市。
                schedule[row_date] = (
                    schedule.get(row_date, False)
                    or self._row_is_open(raw_row)
                )
            if valid_rows == 0:
                raise ValueError("TWSE holidaySchedule 無有效日期")
            self._schedule_cache[calendar_year] = schedule
        except Exception as exc:  # noqa: BLE001 - 網路／官方格式皆須 fail closed
            logger.warning(
                "取得 TWSE holidaySchedule 失敗 (%s): %s",
                calendar_year,
                exc,
            )
            self._schedule_cache[calendar_year] = None
        return self._schedule_cache[calendar_year]

    def _has_local_market_index_evidence(self, target_date: date) -> bool:
        """僅供停用線上查詢的歷史回補使用，不推定缺列是休市。"""

        date_yyyymmdd = target_date.strftime("%Y%m%d")
        if not self.db_path.exists():
            return False
        try:
            uri = f"file:{self.db_path.resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                conn.execute("PRAGMA query_only=ON")
                columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(market_indices)")
                }
                date_column = next(
                    (
                        column
                        for column in ("日期", "trade_date", "date")
                        if column in columns
                    ),
                    None,
                )
                if date_column is None:
                    return False
                count = conn.execute(
                    f'SELECT COUNT(*) FROM market_indices WHERE "{date_column}" = ?',
                    (date_yyyymmdd,),
                ).fetchone()[0]
                return bool(count > 0)
        except Exception as exc:  # noqa: BLE001 - 本地證據失效時保持未知
            logger.warning("讀取 DB 交易日證據失敗 (%s): %s", target_date, exc)
            return False

    def is_official_trading_day(
        self, target_date: date, allow_online_probe: bool = True
    ) -> Tuple[Optional[bool], str]:
        """判定指定日期是否為台股官方交易日。

        Returns:
            (is_trading_day, reason_code)
            - (True, "twse_holiday_schedule_open")
            - (True, "twse_holiday_schedule_explicit_open")
            - (True, "twstock_db_market_indices_evidence")
            - (False, "weekend_closed")
            - (False, "twse_holiday_schedule_closed")
            - (None, "twse_holiday_schedule_unavailable")
        """
        if target_date.weekday() >= 5:
            return False, "weekend_closed"

        if not allow_online_probe:
            if self._has_local_market_index_evidence(target_date):
                return True, "twstock_db_market_indices_evidence"
            return None, "lacks_official_evidence"

        schedule = self._fetch_official_year_schedule(target_date.year)
        if schedule is None:
            return None, "twse_holiday_schedule_unavailable"
        if target_date not in schedule:
            return True, "twse_holiday_schedule_open"
        if schedule[target_date]:
            return True, "twse_holiday_schedule_explicit_open"
        return False, "twse_holiday_schedule_closed"

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
