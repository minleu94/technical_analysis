"""UpdateView 單一資料源更新 request。"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable


ProgressCallback = Callable[[str, int], None]
CancellationCallback = Callable[[], bool]


def _supports_progress_keyword(method: Any) -> bool:
    """保留舊 service double 相容性，同時讓新 service 接收即時進度。"""
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == "progress_callback"
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _supports_named_keyword(method: Any, name: str) -> bool:
    """檢查 callable 是否接受指定 callback keyword。"""
    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.name == name
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _invoke_with_optional_progress(
    method: Any,
    *args: Any,
    progress_callback: ProgressCallback | None,
    cancellation_callback: CancellationCallback | None = None,
    **kwargs: Any,
) -> Any:
    call_kwargs = dict(kwargs)
    if progress_callback is not None and _supports_progress_keyword(method):
        call_kwargs["progress_callback"] = progress_callback
    if cancellation_callback is not None:
        if _supports_named_keyword(method, "cancel_callback"):
            call_kwargs["cancel_callback"] = cancellation_callback
        elif _supports_named_keyword(method, "cancellation_callback"):
            call_kwargs["cancellation_callback"] = cancellation_callback
    return method(*args, **call_kwargs)


def _invoke_with_optional_cancellation(
    method: Any,
    *args: Any,
    cancellation_callback: CancellationCallback | None,
    **kwargs: Any,
) -> Any:
    """只對新版 service 傳遞合作式取消 callback。"""
    if cancellation_callback is not None:
        if _supports_named_keyword(method, "cancel_callback"):
            return method(*args, cancel_callback=cancellation_callback, **kwargs)
        if _supports_named_keyword(method, "cancellation_callback"):
            return method(*args, cancellation_callback=cancellation_callback, **kwargs)
    return method(*args, **kwargs)


def _map_nested_progress(
    callback: ProgressCallback | None,
    start: int,
    end: int,
) -> ProgressCallback | None:
    """把來源子流程進度映射到 UpdateView 的外層區間。"""
    if callback is None:
        return None

    def report(message: str, percentage: int) -> None:
        try:
            inner = max(0, min(100, int(percentage)))
        except (TypeError, ValueError):
            inner = 0
        mapped = start + round((end - start) * inner / 100)
        callback(message, mapped)

    return report


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
        cancellation_callback: CancellationCallback | None = None,
    ) -> dict[str, Any]:
        if cancellation_callback is not None and cancellation_callback():
            return {
                "success": False,
                "cancelled": True,
                "message": "已取消：每日資料更新尚未開始",
                "updated_dates": [],
                "failed_dates": [],
            }
        if self.update_type == "daily":
            return self._execute_daily(
                update_service,
                update_tpex_daily_prices=update_tpex_daily_prices,
                tpex_warning_messages=tpex_warning_messages,
                progress_callback=progress_callback,
                cancellation_callback=cancellation_callback,
            )
        if self.update_type == "market":
            return _invoke_with_optional_cancellation(
                update_service.update_market,
                self.start_date,
                self.end_date,
                cancellation_callback=cancellation_callback,
            )
        if self.update_type == "industry":
            return _invoke_with_optional_cancellation(
                update_service.update_industry,
                self.start_date,
                self.end_date,
                cancellation_callback=cancellation_callback,
            )
        if self.update_type == "broker_branch":
            return _invoke_with_optional_progress(
                update_service.update_broker_branch,
                start_date=self.start_date,
                end_date=self.end_date,
                progress_callback=progress_callback,
                cancellation_callback=cancellation_callback,
            )
        raise ValueError(f"未知的更新類型：{self.update_type}")

    def _execute_daily(
        self,
        update_service: Any,
        *,
        update_tpex_daily_prices: Callable[[str, str], dict[str, Any]],
        tpex_warning_messages: Callable[[dict[str, Any]], list[str]],
        progress_callback: ProgressCallback | None,
        cancellation_callback: CancellationCallback | None,
    ) -> dict[str, Any]:
        def cancelled(message: str) -> dict[str, Any]:
            if progress_callback:
                progress_callback(message, 100)
            return {
                "success": False,
                "cancelled": True,
                "message": message,
                "updated_dates": [],
                "failed_dates": [],
            }

        if progress_callback:
            progress_callback("更新 TWSE 每日股價", 15)
        if cancellation_callback is not None and cancellation_callback():
            return cancelled("已取消：TWSE 每日股價更新")
        twse_progress = _map_nested_progress(progress_callback, 15, 30)
        result = _invoke_with_optional_progress(
            update_service.update_daily,
            self.start_date,
            self.end_date,
            progress_callback=twse_progress,
            cancellation_callback=cancellation_callback,
        )
        if isinstance(result, dict) and result.get("cancelled"):
            return result
        if not result.get("success", False):
            # TWSE 若已明確失敗，不能拿既有日檔繼續做 TPEX／SQLite／指標寫入。
            # 只有成功但帶有 no_data_skipped_dates 的官方無交易日才允許繼續。
            warnings = list(result.get("warnings", []))
            failed_dates = [
                str(item)
                for item in result.get("failed_dates", [])
                if str(item).strip()
            ]
            if failed_dates:
                warnings.append(f"TWSE 每日股價缺少日期：{', '.join(sorted(set(failed_dates)))}")
            result["warnings"] = list(dict.fromkeys(warnings))
            if progress_callback:
                progress_callback("TWSE 每日股價更新失敗，已停止後續寫入", 30)
            return result
        if progress_callback:
            progress_callback("更新 TPEX 每日收盤行情", 30)
        if cancellation_callback is not None and cancellation_callback():
            return cancelled("已取消：TPEX 每日股價更新")
        tpex_progress = _map_nested_progress(progress_callback, 30, 50)
        tpex_result = _invoke_with_optional_progress(
            update_tpex_daily_prices,
            self.start_date,
            self.end_date,
            progress_callback=tpex_progress,
            cancellation_callback=cancellation_callback,
        )
        if isinstance(tpex_result, dict) and tpex_result.get("cancelled"):
            return tpex_result
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
        if cancellation_callback is not None and cancellation_callback():
            return cancelled("已取消：每日股價 SQLite 同步")
        sqlite_result = _invoke_with_optional_cancellation(
            update_service.sync_source_to_sqlite,
            "daily_price_files",
            self.start_date,
            self.end_date,
            cancellation_callback=cancellation_callback,
        )
        # 保留結構化同步結果，讓 UI 不必只從自然語言 message 猜測
        # SQLite 是否真的完成，以及實際寫入了多少筆。
        if isinstance(sqlite_result, dict):
            sqlite_sync = dict(sqlite_result)
            sqlite_sync.setdefault("source", "daily_price_files")
            sqlite_sync.setdefault("table", "daily_prices")
        else:
            sqlite_sync = {
                "success": bool(sqlite_result),
                "source": "daily_price_files",
                "table": "daily_prices",
                "synced_records": 0,
                "message": str(sqlite_result),
            }
        result["sqlite_sync"] = sqlite_sync
        if isinstance(sqlite_result, dict) and sqlite_result.get("cancelled"):
            return sqlite_result
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
        if cancellation_callback is not None and cancellation_callback():
            return cancelled("已取消：技術指標計算")

        def report_indicator_progress(message: str, percentage: int) -> None:
            """把技術計算的局部進度壓在單一來源流程的 85–99%。"""
            if progress_callback is None:
                return
            try:
                inner = max(0, min(100, int(percentage)))
            except (TypeError, ValueError):
                inner = 0
            progress_callback(message, 85 + round(inner * 0.14))

        indicator_result = _invoke_with_optional_progress(
            update_service.calculate_technical_indicators,
            target_stock=None,
            force_all=False,
            start_date=None,
            progress_callback=report_indicator_progress,
            cancellation_callback=cancellation_callback,
        )
        if isinstance(indicator_result, dict) and indicator_result.get("cancelled"):
            return indicator_result
        if not indicator_result.get("success", False):
            result["success"] = False
            warnings.append(
                f"技術指標計算失敗: {indicator_result.get('message', 'unknown error')}"
            )
        if warnings:
            result["warnings"] = list(dict.fromkeys(warnings))
        if progress_callback and result.get("success", False):
            progress_callback("每日資料更新完成", 100)
        return result
