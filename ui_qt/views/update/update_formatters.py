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
        "network_error": "網路失敗",
        "transport_error": "傳輸失敗",
        "date_mismatch": "日期不符",
        "registry_error": "登錄檔異常",
        "audit_unavailable": "稽核不可用",
        "blocked_provenance": "來源證據受阻",
        "blocked_insufficient_storage": "磁碟空間不足",
        "direct_chain_storage_preflight_blocked": "磁碟空間不足",
        "production_canary_storage_preflight_blocked": "正式 canary 磁碟空間不足",
        "research_shadow": "研究影子",
        "contract_only": "僅有契約",
        "candidate_only": "僅限候選",
        "candidate_evidence_only": "僅限候選證據",
        "governance_review": "待治理審核",
        "not_supplied": "未提供",
        "not_observed": "未觀測",
        "not_available": "尚未觀測",
        "lagging": "待更新",
        "stale": "待更新",
        "summary": "已讀取摘要",
        "candidate_available": "候選可用",
        "ready": "已讀取",
        "ready_for_merge": "可併入候選",
        "already_merged": "已併入",
        "not_computable": "尚不可計算",
        "not_computable_cost_ledger_missing": "尚不可計算（成本帳缺漏）",
        "waiting_for_formal_inputs": "等待 Formal 輸入",
        "waiting_for_time": "等待真實時間",
        "pending_human_review": "待人工覆核",
        "manual_review_required": "待人工覆核",
        "blocked": "已阻擋",
        "merge_blocked": "合併受阻",
        "running": "執行中",
        "in_progress": "進行中",
        "preview": "預覽",
        "staging": "候選暫存",
        "not_configured": "尚未設定",
        "not_found": "找不到",
        "research_only": "僅限研究",
        "research_only_degraded": "研究受限",
        "no_data_skipped_dates": "官方無資料",
        "operational": "正常",
        "guarded": "受控",
        "attention": "需處理",
        "conflict": "有衝突",
        "invalid": "候選無效",
        "unknown": "未知",
        "正常": "正常",
        "待更新": "待更新",
        "未檢查": "未檢查",
    }
    return mapping.get(normalized, raw_status or "未知")


def format_p0_license_capture_status(status: Any) -> str:
    """Render a P0 license-capture token without hiding its machine value."""

    raw_status = str(status or "not_supplied").strip()
    normalized = raw_status.lower()
    labels = {
        "captured_candidate": "已取得候選指紋",
        "capture_partial": "部分取得，仍需複核",
        "preview_not_captured": "預覽未擷取",
        "capture_transport_error": "傳輸失敗",
        "capture_http_error": "HTTP 失敗",
        "capture_incomplete": "擷取未完成",
        "not_supplied": "未提供",
    }
    label = labels.get(normalized)
    if label is None:
        return raw_status or "未知"
    return f"{label}（{raw_status}）"


def format_manual_update_summary(
    operation: Any,
    status: Any,
    message: Any = "",
    *,
    start_date: Any = None,
    end_date: Any = None,
    updated_count: Any = None,
    failed_count: Any = None,
    failed_step: Any = None,
    warnings: Any = (),
    progress: Any = None,
) -> str:
    """Render the current UI update attempt without conflating it with scheduler state.

    Manual source updates and scheduled ``latest_status.json`` artifacts have
    different provenance.  Keeping this summary local to the current action
    prevents a failed/ cancelled manual run from leaving the previous
    successful scheduler timeline as the only visible explanation.
    """

    raw_status = str(status or "unknown").strip().lower() or "unknown"
    status_labels = {
        "success": "完成",
        "passed": "完成",
        "completed": "完成",
        "failed": "失敗",
        "failure": "失敗",
        "error": "錯誤",
        "running": "執行中",
        "in_progress": "執行中",
        "cancelled": "已取消",
    }
    status_label = status_labels.get(raw_status, format_status_token(raw_status))
    operation_text = str(operation or "資料更新").strip() or "資料更新"
    lines = [f"本次手動更新：{status_label}（{raw_status}）", f"操作：{operation_text}"]

    start_text = str(start_date or "").strip()
    end_text = str(end_date or "").strip()
    if start_text or end_text:
        lines.append(f"資料區間：{start_text or '未提供'} ~ {end_text or '未提供'}")

    try:
        progress_value = int(progress) if progress is not None else None
    except (TypeError, ValueError):
        progress_value = None
    if progress_value is not None:
        lines.append(f"目前進度：{max(0, min(100, progress_value))}%")

    message_text = str(message or "").strip()
    if message_text:
        lines.append(f"訊息：{message_text}")

    if updated_count is not None:
        lines.append(f"成功日期：{_safe_nonnegative_int(updated_count):,} 個")
    if failed_count is not None:
        lines.append(f"失敗日期：{_safe_nonnegative_int(failed_count):,} 個")
    failed_step_text = str(failed_step or "").strip()
    if failed_step_text:
        lines.append(f"失敗步驟：{failed_step_text}")

    if isinstance(warnings, (list, tuple, set)):
        warning_items = warnings
    elif warnings in (None, ""):
        warning_items = ()
    else:
        warning_items = (warnings,)
    warning_values = [
        str(item).strip() for item in warning_items if str(item).strip()
    ]
    if warning_values:
        lines.append("提醒：" + "；".join(warning_values[:3]))

    lines.append("排程時間軸仍只讀取明確 status artifact；兩者不互相回填。")
    return "\n".join(lines)


def format_monthly_revenue_candidate_lines(detail: Mapping[str, Any]) -> list[str]:
    """投影月營收數值 snapshot 與 availability mapping 候選的唯讀差異。"""

    lines: list[str] = []
    latest_period = str(detail.get("latest_period") or "").strip()
    snapshot_period = str(detail.get("candidate_latest_period") or "").strip()
    if snapshot_period:
        is_newer = latest_period in {"", "未知", "無"} or snapshot_period > latest_period
        label = "候選待套用期別" if is_newer else "候選快照期別"
        fetch_date = str(detail.get("candidate_fetch_date") or "").strip()
        suffix = f"（抓取日：{fetch_date}）" if fetch_date else ""
        lines.append(f"{label}：{snapshot_period}{suffix}")
    snapshot_status = str(detail.get("candidate_snapshot_status") or "").strip()
    snapshot_diagnostic = str(detail.get("candidate_snapshot_diagnostic") or "").strip()
    if snapshot_status in {"missing", "invalid", "error"}:
        lines.append(f"數值 snapshot 候選：{format_status_token(snapshot_status)}")
        if snapshot_diagnostic:
            lines.append(f"候選診斷：{snapshot_diagnostic}")

    mapping_period = str(
        detail.get("availability_candidate_latest_period") or ""
    ).strip()
    mapping_status = str(
        detail.get("availability_candidate_status") or ""
    ).strip()
    mapping_file = str(detail.get("availability_candidate_file") or "").strip()
    if mapping_period or mapping_status or mapping_file:
        status = format_status_token(mapping_status or "unknown")
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
            f"公告日 mapping 候選：{mapping_period or '未解析'}（{status}；{suffix}）"
        )
        diagnostics = detail.get("availability_candidate_diagnostics") or []
        for diagnostic in list(diagnostics)[:2]:
            if str(diagnostic).strip():
                lines.append(f"候選診斷：{diagnostic}")
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
    elif source == "scheduler_status":
        scheduler_state = str(
            detail.get("scheduler_state") or detail.get("status") or "unknown"
        ).strip()
        operation_count = _safe_nonnegative_int(
            detail.get("operation_count", detail.get("total_records"))
        )
        core_ready = _safe_nonnegative_int(detail.get("core_ready_count"))
        core_jobs = _safe_nonnegative_int(detail.get("core_job_count"))
        lines = [
            f"排程狀態：{format_status_token(scheduler_state)}（{scheduler_state}）",
            f"核心工作就緒：{core_ready:,}/{core_jobs:,}",
            f"已觀測工作：{operation_count:,}",
            f"正常：{_safe_nonnegative_int(detail.get('operational_count')):,}"
            f"／受控：{_safe_nonnegative_int(detail.get('guarded_count')):,}"
            f"／需處理：{_safe_nonnegative_int(detail.get('attention_count')):,}"
            f"／不可用：{_safe_nonnegative_int(detail.get('unavailable_count')):,}",
            f"狀態：{format_status_token(detail.get('status'))}",
        ]
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
    elif source == "scheduler_status":
        scheduled_root = str(detail.get("scheduled_root") or "").strip()
        if scheduled_root:
            lines.append(f"狀態根目錄：{scheduled_root}")
        if detail.get("read_only") is True:
            lines.append("邊界：唯讀，不註冊或修改 Windows Task Scheduler")
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
