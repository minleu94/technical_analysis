"""UpdateView 的純格式化與顯示文字函式。"""

from typing import Any, Mapping


def _safe_nonnegative_int(value: Any) -> int:
    """把 malformed 計數 fail-closed 成 0，避免狀態頁因顯示而中止。"""

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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
        "degraded": "需注意",
        "partial": "部分完成",
        "passed": "正常",
        "passed_with_warnings": "需注意",
        "waiting_for_external_input": "等待外部輸入",
        "action_required": "需處理",
        "error": "異常",
        "missing": "缺漏",
        "empty": "缺漏",
        "unavailable": "不可用",
        "official_no_data": "官方無資料",
        "no_data": "官方無資料",
        "schema_blocked": "格式不符",
        "schema_mismatch": "格式不符",
        "network_failed": "網路失敗",
        "audit_unavailable": "稽核不可用",
        "blocked_provenance": "來源證據受阻",
        "research_shadow": "研究影子",
        "contract_only": "僅有契約",
        "governance_review": "待治理審核",
        "not_supplied": "未提供",
        "not_observed": "未觀測",
        "lagging": "待更新",
        "stale": "待更新",
        "summary": "待更新",
        "candidate_available": "候選可用",
        "ready_for_merge": "可併入候選",
        "already_merged": "已併入",
        "conflict": "有衝突",
        "merge_blocked": "合併受阻",
        "invalid": "候選無效",
        "unknown": "未知",
        "正常": "正常",
        "待更新": "待更新",
        "未檢查": "未檢查",
    }
    return mapping.get(normalized, raw_status or "未知")


def format_monthly_revenue_candidate_lines(detail: Mapping[str, Any]) -> list[str]:
    """投影月營收數值 snapshot 與 availability mapping 候選的唯讀差異。"""

    lines: list[str] = []
    latest_period = str(detail.get("latest_period") or "").strip()
    snapshot_period = str(detail.get("candidate_latest_period") or "").strip()
    if snapshot_period and (
        latest_period in {"", "未知", "無"} or snapshot_period > latest_period
    ):
        lines.append(f"候選待套用期別：{snapshot_period}")

    mapping_period = str(
        detail.get("availability_candidate_latest_period") or ""
    ).strip()
    mapping_status = str(
        detail.get("availability_candidate_status") or ""
    ).strip()
    if mapping_period and mapping_status:
        status = format_status_token(mapping_status)
        row_count = _safe_nonnegative_int(
            detail.get("availability_candidate_row_count")
        )
        available_date = str(
            detail.get("availability_candidate_latest_available_date") or ""
        ).strip()
        suffix = f"{row_count:,} 筆"
        if available_date:
            suffix += f"；可用日至 {available_date}"
        added = detail.get("availability_candidate_added_count")
        conflicts = detail.get("availability_candidate_conflict_count")
        if added is not None or conflicts is not None:
            suffix += (
                f"；新增 {_safe_nonnegative_int(added):,}"
                f"／衝突 {_safe_nonnegative_int(conflicts):,}"
            )
        lines.append(
            f"公告日 mapping 候選：{mapping_period}（{status}；{suffix}）"
        )
    return lines


def format_freshness_gap(detail: Mapping[str, Any]) -> str:
    """把來源相對 daily reference 的落後日期轉成可讀提示。"""

    freshness_status = str(detail.get("freshness_status") or "").strip().lower()
    if freshness_status not in {"lagging", "stale"}:
        return ""
    reference_date = detail.get("freshness_reference_date") or detail.get("reference_date")
    latest_date = detail.get("latest_date")
    if not reference_date or not latest_date:
        return ""
    return f"新鮮度基準日：{reference_date}（資料最新日：{latest_date}）"


def format_source_detail_summary(source: str, detail: Mapping[str, Any]) -> str:
    latest_date = detail.get("latest_date") or "未知"
    total_records = _safe_nonnegative_int(detail.get("total_records"))
    if source == "monthly_revenue":
        latest_period = detail.get("latest_period") or latest_date
        latest_available_period = detail.get("latest_available_period") or "尚無"
        latest_available_date = detail.get("latest_available_date") or "尚無"
        next_available_date = detail.get("next_available_date")
        pending_period_count = _safe_nonnegative_int(detail.get("pending_period_count"))
        lines = [
            f"最新可用日：{latest_available_date}",
            f"已匯入期別：{latest_period}",
            f"目前可用期別：{latest_available_period}",
        ]
        lines.extend(format_monthly_revenue_candidate_lines(detail))
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
            lines.append(f"CSV 日檔數：{_safe_nonnegative_int(csv_count):,}")
        missing_dates = detail.get("missing_dates") or []
        if missing_dates:
            lines.append("缺漏日期：" + "、".join(str(date) for date in missing_dates[:8]))
    elif source == "broker_branch":
        lines.append(f"實際天數：{_safe_nonnegative_int(detail.get('date_count')):,}")
        lines.append(f"雙榜紀錄：{_safe_nonnegative_int(detail.get('dual_count')):,}")
        lines.append(f"張數榜專屬：{_safe_nonnegative_int(detail.get('e_only_count')):,}")
        lines.append(f"金額榜專屬：{_safe_nonnegative_int(detail.get('b_only_count')):,}")
    elif source in {"technical", "technical_indicators"} and detail.get("file_count") is not None:
        lines.append(f"指標檔數：{_safe_nonnegative_int(detail.get('file_count')):,}")
    read_mode = str(detail.get("read_mode") or "").strip()
    if read_mode:
        lines.append(f"讀取模式：{read_mode}")
    warnings = detail.get("warnings") or detail.get("quality_warnings") or []
    if warnings:
        lines.append("提醒：" + "；".join(str(item) for item in warnings[:3]))
    freshness_gap = format_freshness_gap(detail)
    if freshness_gap:
        lines.append(freshness_gap)
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
