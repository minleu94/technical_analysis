"""UpdateView 一鍵更新流程的非 Qt orchestration。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


Result = dict[str, Any]
ProgressCallback = Callable[[str, int], None]


def _twse_skip_warning_messages(result: Result) -> list[str]:
    skipped_dates = sorted(
        {str(item) for item in result.get("skipped_dates", []) if str(item).strip()}
    )
    if not skipped_dates:
        return []
    return [f"TWSE 上游查無資料，已跳過日期：{', '.join(skipped_dates)}"]


def run_update_all(
    *,
    mode: str,
    start_date: str,
    end_date: str,
    update_service: Any,
    get_overview_status: Callable[[], Any],
    update_tpex_daily_prices: Callable[[str, str], Result],
    run_incremental_technical: Callable[[ProgressCallback | None], Result],
    tpex_warning_messages: Callable[[Result], list[str]],
    progress_callback: ProgressCallback | None = None,
) -> Result:
    """依既有 quick/safe 契約執行更新；不持有 widget 或 worker。"""
    completed: list[Result] = []
    warnings: list[str] = []
    soft_failures: list[Result] = []

    def report(message: str, progress: int) -> None:
        if progress_callback:
            progress_callback(message, progress)

    def run_step(name: str, progress: int, action: Callable[[], Any]) -> Any:
        report(name, progress)
        result = action()
        if isinstance(result, dict) and not result.get("success", True):
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
            lambda: update_service.update_daily(daily_update_start_date, end_date),
        ),
        (
            "TPEX 每日股價更新",
            16,
            lambda: update_tpex_daily_prices(daily_update_start_date, end_date),
        ),
        (
            "同步每日股價至 SQLite",
            18,
            lambda: update_service.sync_source_to_sqlite(
                "daily_price_files", daily_update_start_date, end_date
            ),
        ),
        ("大盤指數更新", 24, lambda: update_service.update_market(start_date, end_date)),
        (
            "同步大盤指數至 SQLite",
            30,
            lambda: update_service.sync_source_to_sqlite("market_index"),
        ),
        ("產業指數更新", 36, lambda: update_service.update_industry(start_date, end_date)),
        (
            "同步產業指數至 SQLite",
            42,
            lambda: update_service.sync_source_to_sqlite("industry_index"),
        ),
        (
            "券商分點更新",
            48,
            lambda: update_service.update_broker_branch(start_date, end_date),
        ),
    ]
    if is_quick_mode:
        steps.append(
            (
                "同步券商分點至 SQLite (直接檔案同步)",
                65,
                lambda: update_service.sync_source_to_sqlite(
                    "broker_branch_files", start_date, end_date
                ),
            )
        )
    else:
        steps.extend(
            [
                ("合併每日資料", 55, lambda: update_service.merge_daily_data(force_all=False)),
                (
                    "同步合併每日資料至 SQLite",
                    62,
                    lambda: update_service.sync_source_to_sqlite("daily_data"),
                ),
                ("合併券商分點", 69, update_service.merge_broker_branch_data),
                (
                    "同步券商分點至 SQLite",
                    76,
                    lambda: update_service.sync_source_to_sqlite("broker_branch"),
                ),
            ]
        )
    steps.extend(
        [
            (
                "檢查並增量計算技術指標",
                88,
                lambda: run_incremental_technical(progress_callback),
            ),
            ("刷新資料狀態", 100, get_overview_status),
        ]
    )

    for name, progress, action in steps:
        result = run_step(name, progress, action)
        if name.startswith("每日股價更新") and isinstance(result, dict):
            warnings.extend(_twse_skip_warning_messages(result))
        if name.startswith("TPEX 每日股價更新") and isinstance(result, dict):
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
        if isinstance(result, dict) and not result.get("success", True):
            return {
                "success": False,
                "message": result.get("message", f"{name} 失敗"),
                "failed_step": name,
                "completed_steps": completed,
                "step_result": result,
            }

    final_message = "快速更新所有數據完成" if is_quick_mode else "安全更新所有數據完成"
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
