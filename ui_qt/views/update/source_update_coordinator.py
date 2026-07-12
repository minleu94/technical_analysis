"""UpdateView 單一資料源更新 request。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class SourceUpdateRequest:
    update_type: str
    start_date: str
    end_date: str

    def execute(
        self,
        update_service: Any,
        *,
        update_tpex_daily_prices: Callable[[str, str], dict[str, Any]],
        tpex_warning_messages: Callable[[dict[str, Any]], list[str]],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        if self.update_type == "daily":
            return self._execute_daily(
                update_service,
                update_tpex_daily_prices=update_tpex_daily_prices,
                tpex_warning_messages=tpex_warning_messages,
                progress_callback=progress_callback,
            )
        if self.update_type == "market":
            return update_service.update_market(self.start_date, self.end_date)
        if self.update_type == "industry":
            return update_service.update_industry(self.start_date, self.end_date)
        if self.update_type == "broker_branch":
            return update_service.update_broker_branch(
                start_date=self.start_date,
                end_date=self.end_date,
                progress_callback=progress_callback,
            )
        raise ValueError(f"未知的更新類型：{self.update_type}")

    def _execute_daily(
        self,
        update_service: Any,
        *,
        update_tpex_daily_prices: Callable[[str, str], dict[str, Any]],
        tpex_warning_messages: Callable[[dict[str, Any]], list[str]],
        progress_callback: ProgressCallback | None,
    ) -> dict[str, Any]:
        if progress_callback:
            progress_callback("更新 TWSE 每日股價", 15)
        result = update_service.update_daily(self.start_date, self.end_date)
        if progress_callback:
            progress_callback("更新 TPEX 每日收盤行情", 30)
        tpex_result = update_tpex_daily_prices(self.start_date, self.end_date)
        warnings = list(result.get("warnings", []))
        tpex_warnings = tpex_warning_messages(tpex_result)
        if tpex_result.get("success", False) and not tpex_warnings:
            result["message"] = (
                f"{result.get('message', '每日股票數據更新完成')}\n"
                f"TPEX 每日股價更新: {tpex_result.get('message', '完成')}"
            )
            result["updated_dates"] = list(result.get("updated_dates", [])) + list(
                tpex_result.get("updated_dates", [])
            )
        else:
            result["success"] = False
            if tpex_warnings:
                warnings.extend(f"TPEX 每日股價更新: {item}" for item in tpex_warnings)
            else:
                warnings.append(
                    f"TPEX 每日股價更新: {tpex_result.get('message', 'unknown error')}"
                )
            result["message"] = (
                f"{result.get('message', '每日股票數據更新完成')}\n"
                f"TPEX 每日股價更新未完整：{tpex_result.get('message', 'unknown error')}"
            )

        if progress_callback:
            progress_callback("同步每日股價到 SQLite", 55)
        sqlite_result = update_service.sync_source_to_sqlite(
            "daily_price_files", self.start_date, self.end_date
        )
        if not sqlite_result.get("success", True):
            result["success"] = False
            warnings.append(
                "同步 daily_price_files 到 SQLite 失敗: "
                f"{sqlite_result.get('message', 'unknown error')}"
            )
        else:
            result["synced_records"] = int(result.get("synced_records", 0)) + int(
                sqlite_result.get("synced_records", 0)
            )

        if progress_callback:
            progress_callback("更新技術指標（增量）", 85)
        indicator_result = update_service.calculate_technical_indicators(
            target_stock=None,
            force_all=False,
            start_date=None,
            progress_callback=progress_callback,
        )
        if not indicator_result.get("success", False):
            result["success"] = False
            warnings.append(
                f"技術指標計算失敗: {indicator_result.get('message', 'unknown error')}"
            )
        if warnings:
            result["warnings"] = list(dict.fromkeys(warnings))
        return result
