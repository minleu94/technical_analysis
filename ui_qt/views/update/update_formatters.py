"""UpdateView 的純格式化與顯示文字函式。"""

from typing import Any, Mapping


def format_status_token(status: Any) -> str:
    raw_status = str(status or "").strip()
    normalized = raw_status.lower()
    if normalized.startswith(("error", "failed", "failure", "exception")):
        return "異常"
    mapping = {
        "ok": "正常",
        "success": "正常",
        "current": "正常",
        "normal": "正常",
        "warning": "需注意",
        "error": "異常",
        "missing": "缺漏",
        "empty": "缺漏",
        "unavailable": "不可用",
        "lagging": "待更新",
        "stale": "待更新",
        "summary": "待更新",
        "candidate_available": "候選可用",
        "unknown": "未知",
        "正常": "正常",
        "待更新": "待更新",
        "未檢查": "未檢查",
    }
    return mapping.get(normalized, raw_status or "未知")


def format_source_detail_summary(source: str, detail: Mapping[str, Any]) -> str:
    latest_date = detail.get("latest_date") or "未知"
    total_records = int(detail.get("total_records") or 0)
    if source == "monthly_revenue":
        latest_period = detail.get("latest_period") or latest_date
        latest_available_period = detail.get("latest_available_period") or "尚無"
        latest_available_date = detail.get("latest_available_date") or "尚無"
        next_available_date = detail.get("next_available_date")
        pending_period_count = int(detail.get("pending_period_count") or 0)
        lines = [
            f"最新可用日：{latest_available_date}",
            f"已匯入期別：{latest_period}",
            f"目前可用期別：{latest_available_period}",
        ]
        if pending_period_count and next_available_date:
            lines.append(
                f"待生效：{pending_period_count} 個期別（{next_available_date} 起可用）"
            )
        lines.extend([
            f"SQLite 筆數：{total_records:,}",
            f"狀態：{format_status_token(detail.get('status'))}",
        ])
    else:
        lines = [
            f"最新日期：{latest_date}",
            f"SQLite 筆數：{total_records:,}",
            f"狀態：{format_status_token(detail.get('status'))}",
        ]
    if source == "daily":
        csv_count = detail.get("csv_file_count") or detail.get("file_count")
        if csv_count is not None:
            lines.append(f"CSV 日檔數：{int(csv_count):,}")
        missing_dates = detail.get("missing_dates") or []
        if missing_dates:
            lines.append("缺漏日期：" + "、".join(str(date) for date in missing_dates[:8]))
    elif source == "broker_branch":
        lines.append(f"實際天數：{int(detail.get('date_count') or 0):,}")
        lines.append(f"雙榜紀錄：{int(detail.get('dual_count') or 0):,}")
        lines.append(f"張數榜專屬：{int(detail.get('e_only_count') or 0):,}")
        lines.append(f"金額榜專屬：{int(detail.get('b_only_count') or 0):,}")
    elif source in {"technical", "technical_indicators"} and detail.get("file_count") is not None:
        lines.append(f"指標檔數：{int(detail.get('file_count') or 0):,}")
    read_mode = str(detail.get("read_mode") or "").strip()
    if read_mode:
        lines.append(f"讀取模式：{read_mode}")
    warnings = detail.get("warnings") or detail.get("quality_warnings") or []
    if warnings:
        lines.append("提醒：" + "；".join(str(item) for item in warnings[:3]))
    return "\n".join(lines)


def tpex_warning_messages(result: Mapping[str, Any]) -> list[str]:
    warnings = [str(item) for item in result.get("warnings", []) if str(item).strip()]
    failed_dates = sorted({str(item) for item in result.get("failed_dates", []) if str(item).strip()})
    if failed_dates:
        warnings.append(f"TPEX 每日股價缺少日期：{', '.join(failed_dates)}")
    return list(dict.fromkeys(warnings))


def get_update_type_name(update_type: str) -> str:
    names = {
        "daily": "每日股票數據",
        "market": "大盤指數數據",
        "industry": "產業指數數據",
        "broker_branch": "券商分點資料",
    }
    return names.get(update_type, update_type)
