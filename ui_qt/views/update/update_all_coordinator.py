"""UpdateView 一鍵更新流程的非 Qt orchestration。"""

from __future__ import annotations

from collections.abc import Callable
import inspect
from typing import Any


Result = dict[str, Any]
ProgressCallback = Callable[[str, int], None]
CancellationCallback = Callable[[], bool]


def _supports_progress_keyword(method: Any) -> bool:
    """讓新版更新 service 回報即時進度，並相容舊測試替身。"""
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
    """檢查 callable 是否明確接受指定 keyword，保留舊替身相容性。"""
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
    if (
        cancellation_callback is not None
        and _supports_named_keyword(method, "cancel_callback")
    ):
        return method(*args, cancel_callback=cancellation_callback, **kwargs)
    if (
        cancellation_callback is not None
        and _supports_named_keyword(method, "cancellation_callback")
    ):
        return method(*args, cancellation_callback=cancellation_callback, **kwargs)
    return method(*args, **kwargs)


def _operation_result_failed(result: Any) -> bool:
    """判定單一步驟是否明確失敗。"""
    if not isinstance(result, dict):
        return False
    if result.get("success") is False:
        return True
    status = str(result.get("status", "")).strip().lower()
    return status.startswith(("error", "failed", "failure", "exception"))


def _status_payload_failures(result: Any) -> list[tuple[str, dict[str, Any]]]:
    """找出 overview 內的錯誤資料源，不把 nested error 當成成功。"""
    if not isinstance(result, dict):
        return []
    failures: list[tuple[str, dict[str, Any]]] = []
    for key, value in result.items():
        if isinstance(value, dict) and _operation_result_failed(value):
            failures.append((str(key), value))
    return failures


def _market_skip_messages(result: Result) -> list[str]:
    skipped_dates = sorted(
        {
            str(item)
            for item in result.get("no_data_skipped_dates", [])
            if str(item).strip()
        }
    )
    if not skipped_dates:
        return []
    return [f"台股因故（如颱風假）休市或無資料，全市場各項數據均已自動跳過日期：{', '.join(skipped_dates)}"]


def _map_nested_progress(
    callback: ProgressCallback | None,
    start: int,
    end: int,
) -> ProgressCallback | None:
    """把子流程進度映射到外層區間，避免進度條倒退。"""
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


def run_update_all(
    *,
    mode: str,
    start_date: str,
    end_date: str,
    update_service: Any,
    get_overview_status: Callable[[], Any],
    update_tpex_daily_prices: Callable[..., Result],
    run_incremental_technical: Callable[[ProgressCallback | None], Result],
    tpex_warning_messages: Callable[[Result], list[str]],
    progress_callback: ProgressCallback | None = None,
    cancellation_callback: CancellationCallback | None = None,
) -> Result:
    """依既有 quick/safe 契約執行更新；不持有 widget 或 worker。"""
    completed: list[Result] = []
    warnings: list[str] = []
    info_messages: list[str] = []
    soft_failures: list[Result] = []

    def is_cancel_requested() -> bool:
        if cancellation_callback is None:
            return False
        try:
            return bool(cancellation_callback())
        except Exception:
            # 取消狀態讀取失敗時採 fail-closed，避免繼續寫入未知狀態。
            return True

    def cancelled_result(step_name: str, step_result: Any = None) -> Result:
        message = f"已取消：{step_name}；已完成步驟保留，未繼續後續寫入"
        report(message, 0)
        return {
            "success": False,
            "cancelled": True,
            "message": message,
            "failed_step": step_name,
            "completed_steps": completed,
            "step_result": step_result,
        }

    def report(message: str, progress: int) -> None:
        if progress_callback:
            progress_callback(message, progress)

    def run_step(name: str, progress: int, action: Callable[[], Any]) -> Any:
        report(name, progress)
        result = action()
        if _operation_result_failed(result):
            return result
        completed.append({"step": name, "result": result})
        return result

    is_quick_mode = mode == "quick" and bool(
        getattr(update_service.config, "use_sqlite", False)
    )
    daily_update_start_date = start_date
    steps: list[tuple[str, int, Callable[[], Any]]] = [
        ("檢查資料狀態", 0, get_overview_status),
        (
            "每日股價更新",
            12,
            lambda: _invoke_with_optional_cancellation(
                update_service.update_daily,
                daily_update_start_date,
                end_date,
                cancellation_callback=cancellation_callback,
            ),
        ),
        (
            "TPEX 每日股價更新",
            16,
            lambda: _invoke_with_optional_progress(
                update_tpex_daily_prices,
                daily_update_start_date,
                end_date,
                next(
                    (
                        c["result"].get("no_data_skipped_dates")
                        for c in completed
                        if c["step"] == "每日股價更新"
                    ),
                    None,
                ),
                progress_callback=_map_nested_progress(progress_callback, 16, 18),
                cancellation_callback=cancellation_callback,
            ),
        ),
        (
            "同步每日股價至 SQLite",
            18,
            lambda: _invoke_with_optional_cancellation(
                update_service.sync_source_to_sqlite,
                "daily_price_files",
                daily_update_start_date,
                end_date,
                cancellation_callback=cancellation_callback,
            ),
        ),
        (
            "大盤指數更新",
            24,
            lambda: _invoke_with_optional_cancellation(
                update_service.update_market,
                start_date,
                end_date,
                cancellation_callback=cancellation_callback,
            ),
        ),
        (
            "同步大盤指數至 SQLite",
            30,
            lambda: _invoke_with_optional_cancellation(
                update_service.sync_source_to_sqlite,
                "market_index",
                cancellation_callback=cancellation_callback,
            ),
        ),
        (
            "產業指數更新",
            36,
            lambda: _invoke_with_optional_cancellation(
                update_service.update_industry,
                start_date,
                end_date,
                cancellation_callback=cancellation_callback,
            ),
        ),
        (
            "同步產業指數至 SQLite",
            42,
            lambda: _invoke_with_optional_cancellation(
                update_service.sync_source_to_sqlite,
                "industry_index",
                cancellation_callback=cancellation_callback,
            ),
        ),
        (
            "券商分點更新",
            48,
            lambda: _invoke_with_optional_cancellation(
                update_service.update_broker_branch,
                start_date,
                end_date,
                cancellation_callback=cancellation_callback,
            ),
        ),
    ]
    if is_quick_mode:
        steps.append(
            (
                "同步券商分點至 SQLite (直接檔案同步)",
                65,
                lambda: _invoke_with_optional_cancellation(
                    update_service.sync_source_to_sqlite,
                    "broker_branch_files",
                    start_date,
                    end_date,
                    cancellation_callback=cancellation_callback,
                ),
            )
        )
    else:
        steps.extend(
            [
                (
                    "合併每日資料",
                    55,
                    lambda: _invoke_with_optional_progress(
                        update_service.merge_daily_data,
                        force_all=False,
                        progress_callback=_map_nested_progress(progress_callback, 55, 62),
                        cancellation_callback=cancellation_callback,
                    ),
                ),
                (
                    "同步合併每日資料至 SQLite",
                    62,
                    lambda: _invoke_with_optional_cancellation(
                        update_service.sync_source_to_sqlite,
                        "daily_data",
                        cancellation_callback=cancellation_callback,
                    ),
                ),
                (
                    "合併券商分點",
                    69,
                    lambda: _invoke_with_optional_progress(
                        update_service.merge_broker_branch_data,
                        progress_callback=_map_nested_progress(progress_callback, 69, 76),
                        cancellation_callback=cancellation_callback,
                    ),
                ),
                (
                    "同步券商分點至 SQLite",
                    76,
                    lambda: _invoke_with_optional_cancellation(
                        update_service.sync_source_to_sqlite,
                        "broker_branch",
                        cancellation_callback=cancellation_callback,
                    ),
                ),
            ]
        )
    steps.extend(
        [
            (
                "檢查並增量計算技術指標",
                88,
                lambda: _invoke_with_optional_cancellation(
                    run_incremental_technical,
                    _map_nested_progress(progress_callback, 88, 99),
                    cancellation_callback=cancellation_callback,
                ),
            ),
            ("刷新資料狀態", 99, get_overview_status),
        ]
    )

    for name, progress, action in steps:
        if is_cancel_requested():
            return cancelled_result(name)
        result = run_step(name, progress, action)
        if isinstance(result, dict) and result.get("cancelled"):
            return cancelled_result(name, result)
        if name == "檢查資料狀態":
            baseline_failures = _status_payload_failures(result)
            if baseline_failures:
                failed_sources = ", ".join(source for source, _payload in baseline_failures)
                return {
                    "success": False,
                    "message": f"更新前資料狀態發現錯誤，已停止寫入：{failed_sources}",
                    "failed_step": name,
                    "completed_steps": completed,
                    "step_result": result,
                    "status_failures": [
                        {"source": source, "result": payload}
                        for source, payload in baseline_failures
                    ],
                }
        if name == "每日股價更新" and isinstance(result, dict):
            info_messages.extend(_market_skip_messages(result))
            no_data_dates = result.get("no_data_skipped_dates", [])
            if no_data_dates:
                warnings.append(f"TWSE 上游查無資料：{', '.join(str(d) for d in no_data_dates)}")
        if name == "TPEX 每日股價更新" and isinstance(result, dict):
            step_warnings = [f"{name}: {warning}" for warning in tpex_warning_messages(result)]
            if not result.get("success", True) and not step_warnings:
                step_warnings.append(f"{name}: {result.get('message', f'{name} 失敗')}")
            if step_warnings:
                warnings.extend(step_warnings)
                soft_failures.append(
                    {"step": name, "result": result, "warnings": step_warnings}
                )
                if not result.get("success", True):
                    completed.append({"step": name, "result": result, "warning": True})
                elif completed and completed[-1].get("step") == name:
                    completed[-1]["warning"] = True
                continue
        if _operation_result_failed(result):
            return {
                "success": False,
                "message": result.get("message", f"{name} 失敗"),
                "failed_step": name,
                "completed_steps": completed,
                "step_result": result,
            }

    final_status = completed[-1]["result"] if completed and completed[-1]["step"] == "刷新資料狀態" else None
    status_failures = _status_payload_failures(final_status)
    if status_failures:
        failed_sources = ", ".join(source for source, _payload in status_failures)
        return {
            "success": False,
            "message": f"資料狀態檢查發現錯誤：{failed_sources}",
            "failed_step": "刷新資料狀態",
            "completed_steps": completed,
            "step_result": final_status,
            "status_failures": [
                {"source": source, "result": payload}
                for source, payload in status_failures
            ],
        }

    final_message = "快速更新所有數據完成" if is_quick_mode else "安全更新所有數據完成"
    if info_messages:
        final_message += "\n\n備註：\n" + "\n".join(info_messages)

    report(final_message, 100)
    if soft_failures:
        return {
            "success": False,
            "message": f"{final_message}，但 TPEX 每日股價未完整更新",
            "failed_step": soft_failures[0]["step"],
            "completed_steps": completed,
            "warnings": list(dict.fromkeys(warnings)),
            "step_result": soft_failures[0]["result"],
            "soft_failures": soft_failures,
        }
    return {
        "success": True,
        "message": final_message,
        "completed_steps": completed,
        "warnings": list(dict.fromkeys(warnings)),
    }
