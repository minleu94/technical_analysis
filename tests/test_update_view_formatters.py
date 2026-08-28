from ui_qt.views.update.update_formatters import (
    format_source_detail_summary,
    format_status_token,
    get_update_type_name,
    tpex_warning_messages,
)


def test_format_status_token_preserves_known_unknown_and_missing_values() -> None:
    assert format_status_token("OK") == "正常"
    assert format_status_token("current") == "正常"
    assert format_status_token("success") == "正常"
    assert format_status_token("normal") == "正常"
    assert format_status_token("warning") == "需注意"
    assert format_status_token(None) == "未知"
    assert format_status_token("custom") == "custom"


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


def test_tpex_warning_messages_deduplicates_and_sorts_failed_dates() -> None:
    assert tpex_warning_messages(
        {"warnings": ["來源延遲", "來源延遲", ""], "failed_dates": ["20260709", "20260708", "20260709"]}
    ) == ["來源延遲", "TPEX 每日股價缺少日期：20260708, 20260709"]


def test_get_update_type_name_preserves_known_and_unknown_values() -> None:
    assert get_update_type_name("daily") == "每日股票數據"
    assert get_update_type_name("broker_branch") == "券商分點資料"
    assert get_update_type_name("custom") == "custom"
