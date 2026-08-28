from ui_qt.views.update.update_formatters import (
    format_freshness_gap,
    format_manual_update_summary,
    format_p0_license_capture_status,
    format_scheduler_operations_detail,
    format_source_detail_summary,
    format_status_token,
    get_update_type_name,
    tpex_warning_messages,
)


def test_format_manual_update_summary_keeps_attempt_state_separate_from_scheduler() -> None:
    summary = format_manual_update_summary(
        "安全更新",
        "failed",
        "大盤指數更新失敗",
        start_date="2026-08-27",
        end_date="2026-08-28",
        failed_step="大盤指數更新",
        warnings=["保留已完成的每日股價同步"],
    )

    assert "本次手動更新：失敗（failed）" in summary
    assert "操作：安全更新" in summary
    assert "資料區間：2026-08-27 ~ 2026-08-28" in summary
    assert "失敗步驟：大盤指數更新" in summary
    assert "排程時間軸仍只讀取明確 status artifact" in summary


def test_format_manual_update_summary_clamps_progress_and_counts() -> None:
    summary = format_manual_update_summary(
        "每日股票數據",
        "running",
        progress=125,
        updated_count="2",
        failed_count="-1",
    )

    assert "本次手動更新：執行中（running）" in summary
    assert "目前進度：100%" in summary
    assert "成功日期：2 個" in summary
    assert "失敗日期：0 個" in summary


def test_format_p0_license_capture_status_keeps_machine_token_and_explains_partial() -> None:
    assert (
        format_p0_license_capture_status("capture_partial")
        == "部分取得，仍需複核（capture_partial）"
    )
    assert (
        format_p0_license_capture_status("capture_http_error")
        == "HTTP 失敗（capture_http_error）"
    )
    assert format_p0_license_capture_status("custom") == "custom"


def test_format_status_token_preserves_known_unknown_and_missing_values() -> None:
    assert format_status_token("OK") == "正常"
    assert format_status_token("current") == "正常"
    assert format_status_token("success") == "正常"
    assert format_status_token("completed") == "正常"
    assert format_status_token("normal") == "正常"
    assert format_status_token("warning") == "需注意"
    assert format_status_token(None) == "未知"
    assert format_status_token("custom") == "custom"
    assert format_status_token("degraded") == "需注意"
    assert format_status_token("partial") == "部分完成"
    assert format_status_token("waiting_for_external_input") == "等待外部輸入"
    assert format_status_token("action_required") == "需處理"
    assert format_status_token("not_computable") == "尚不可計算"
    assert format_status_token("pending_human_review") == "待人工覆核"
    assert format_status_token("blocked") == "已阻擋"
    assert format_status_token("running") == "執行中"
    assert format_status_token("skipped_non_trading_day") == "休市略過"
    assert format_status_token("date_mismatch") == "日期不符"
    assert format_status_token("transport_error") == "傳輸失敗"
    assert format_status_token("registry_error") == "登錄檔異常"
    assert format_status_token("blocked_insufficient_storage") == "磁碟空間不足"
    assert format_status_token("production_canary_storage_preflight_blocked") == "正式 canary 磁碟空間不足"
    assert (
        format_status_token("not_computable_cost_ledger_missing")
        == "尚不可計算（成本帳缺漏）"
    )
    assert format_status_token("official_no_data") == "官方無資料"


def test_format_freshness_gap_explains_lagging_reference_and_latest_date() -> None:
    assert format_freshness_gap(
        {
            "freshness_status": "lagging",
            "freshness_reference_date": "2026-08-28",
            "latest_date": "2026-08-27",
        }
    ) == "新鮮度基準日：2026-08-28（資料最新日：2026-08-27）"
    assert format_freshness_gap(
        {
            "freshness_status": "current",
            "freshness_reference_date": "2026-08-28",
            "latest_date": "2026-08-28",
        }
    ) == ""


def test_format_source_detail_summary_keeps_daily_display_text() -> None:
    detail = {
        "latest_date": "2026-07-10",
        "total_records": 123456,
        "status": "warning",
        "csv_file_count": 2890,
        "missing_dates": ["2026-07-08", "2026-07-09"],
        "warnings": ["資料延遲", "來源待確認"],
    }

    assert format_source_detail_summary("daily", detail) == "\n".join(
        [
            "最新日期：2026-07-10",
            "SQLite 筆數：123,456",
            "狀態：需注意",
            "CSV 日檔數：2,890",
            "缺漏日期：2026-07-08、2026-07-09",
            "提醒：資料延遲；來源待確認",
        ]
    )


def test_format_scheduler_operations_detail_explains_state_and_keeps_tokens() -> None:
    summary = format_scheduler_operations_detail(
        {
            "operation_count": 2,
            "scheduled_root": "C:/output/scheduled",
            "read_only": True,
            "operations": [
                {
                    "label": "Raw PIT",
                    "job_id": "ml_raw_pit_refresh",
                    "state": "operational",
                    "raw_status": "completed",
                    "updated_at": "2026-08-28T06:50:37+00:00",
                },
                {
                    "label": "ML Shadow",
                    "job_id": "ml_allocation_copilot",
                    "state": "guarded",
                    "raw_status": "skipped_non_trading_day",
                    "diagnostic": "non_trading_day_noop",
                },
            ],
        }
    )

    assert "Raw PIT：正常（state=operational；raw=completed）" in summary
    assert "ML Shadow：受控（state=guarded；raw=skipped_non_trading_day）" in summary
    assert "診斷=non_trading_day_noop" in summary
    assert "operation_count=2" in summary
    assert "邊界：唯讀" in summary


def test_format_source_detail_summary_handles_missing_broker_fields() -> None:
    assert format_source_detail_summary("broker_branch", {}) == "\n".join(
        [
            "最新日期：未知",
            "SQLite 筆數：0",
            "狀態：未知",
            "實際天數：0",
            "雙榜紀錄：0",
            "張數榜專屬：0",
            "金額榜專屬：0",
        ]
    )


def test_format_source_detail_summary_fail_closes_malformed_counts_and_dates() -> None:
    summary = format_source_detail_summary(
        "broker_branch",
        {
            "latest_date": None,
            "total_records": "not-a-number",
            "date_count": "-5",
            "dual_count": object(),
            "e_only_count": None,
            "b_only_count": "3",
            "status": "ok",
        },
    )

    assert "最新日期：未知" in summary
    assert "SQLite 筆數：0" in summary
    assert "實際天數：0" in summary
    assert "雙榜紀錄：0" in summary
    assert "張數榜專屬：0" in summary
    assert "金額榜專屬：3" in summary


def test_format_source_detail_summary_exposes_monthly_pit_availability() -> None:
    detail = {
        "latest_date": "2026-06-30",
        "latest_period": "2026-06",
        "latest_available_period": "2026-05",
        "latest_available_date": "2026-06-17",
        "next_available_date": "2026-07-15",
        "pending_period_count": 1,
        "total_records": 246331,
        "status": "ok",
    }

    assert format_source_detail_summary("monthly_revenue", detail) == "\n".join(
        [
            "最新可用日：2026-06-17",
            "已匯入期別：2026-06",
            "目前可用期別：2026-05",
            "待生效：1 個期別（2026-07-15 起可用）",
            "SQLite 筆數：246,331",
            "狀態：正常",
        ]
    )


def test_format_source_detail_summary_exposes_newer_monthly_candidate() -> None:
    detail = {
        "latest_period": "2026-06",
        "latest_available_period": "2026-06",
        "latest_available_date": "2026-07-15",
        "candidate_latest_period": "2026-07",
        "total_records": 246331,
        "status": "candidate_available",
    }

    summary = format_source_detail_summary("monthly_revenue", detail)
    assert "候選待套用期別：2026-07" in summary
    assert "狀態：候選可用" in summary


def test_format_source_detail_summary_exposes_same_period_snapshot_fetch_date() -> None:
    summary = format_source_detail_summary(
        "monthly_revenue",
        {
            "latest_period": "2026-07",
            "latest_available_period": "2026-06",
            "candidate_latest_period": "2026-07",
            "candidate_fetch_date": "2026-08-28",
            "total_records": 10,
            "status": "ok",
        },
    )

    assert "候選快照期別：2026-07（抓取日：2026-08-28）" in summary


def test_format_source_detail_summary_exposes_invalid_availability_candidate_diagnostics() -> None:
    summary = format_source_detail_summary(
        "monthly_revenue",
        {
            "latest_period": "2026-06",
            "availability_candidate_file": "C:/candidate.csv",
            "availability_candidate_status": "invalid",
            "availability_candidate_diagnostics": ["缺少 announced_date", "第二筆格式錯誤"],
            "total_records": 10,
            "status": "ok",
        },
    )

    assert "公告日 mapping 候選：未解析（候選無效" in summary
    assert "候選診斷：缺少 announced_date" in summary
    assert "候選診斷：第二筆格式錯誤" in summary


def test_format_source_detail_summary_exposes_availability_candidate_merge_preview() -> None:
    summary = format_source_detail_summary(
        "monthly_revenue",
        {
            "latest_period": "2026-06",
            "latest_available_period": "2026-06",
            "latest_available_date": "2026-07-15",
            "availability_candidate_latest_period": "2026-07",
            "availability_candidate_status": "ready_for_merge",
            "availability_candidate_row_count": 1851,
            "availability_candidate_latest_available_date": "2026-08-18",
            "availability_candidate_added_count": 1851,
            "availability_candidate_conflict_count": 0,
            "total_records": 246331,
            "status": "candidate_available",
        },
    )

    assert "公告日 mapping 候選：2026-07" in summary
    assert "可併入候選" in summary
    assert "1,851 筆" in summary
    assert "新增 1,851／衝突 0" in summary


def test_format_source_detail_summary_discloses_read_mode_fallback() -> None:
    detail = {
        "latest_date": "2026-08-26",
        "total_records": 10,
        "status": "ok",
        "read_mode": "immutable_fallback",
        "warnings": ["可能只反映最後已提交內容"],
    }

    summary = format_source_detail_summary("daily", detail)
    assert "讀取模式：immutable_fallback" in summary
    assert "提醒：可能只反映最後已提交內容" in summary


def test_format_source_detail_summary_explains_lagging_freshness_reference() -> None:
    summary = format_source_detail_summary(
        "technical",
        {
            "latest_date": "2026-08-27",
            "freshness_status": "lagging",
            "freshness_reference_date": "2026-08-28",
            "total_records": 10,
            "status": "lagging",
        },
    )

    assert "狀態：待更新" in summary
    assert "新鮮度基準日：2026-08-28（資料最新日：2026-08-27）" in summary


def test_tpex_warning_messages_deduplicates_and_sorts_failed_dates() -> None:
    assert tpex_warning_messages(
        {"warnings": ["來源延遲", "來源延遲", ""], "failed_dates": ["20260709", "20260708", "20260709"]}
    ) == ["來源延遲", "TPEX 每日股價缺少日期：20260708, 20260709"]


def test_get_update_type_name_preserves_known_and_unknown_values() -> None:
    assert get_update_type_name("daily") == "每日股票數據"
    assert get_update_type_name("broker_branch") == "券商分點資料"
    assert get_update_type_name("custom") == "custom"
