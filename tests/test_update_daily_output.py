import json

from app_module.update_daily_output import parse_daily_update_output


def test_parse_daily_update_output_golden_success_skip_and_failure() -> None:
    output = "\n".join(
        [
            "2026-07-08 更新成功：100 筆記錄",
            "2026-07-09 已存在，跳過",
            "2026-07-10 更新失敗：無法獲取數據",
            "[UPDATE_SUMMARY] SUCCESS: 2 days, FAILED: 1 days",
        ]
    )

    result = parse_daily_update_output(output, ["2026-07-08", "2026-07-09", "2026-07-10"])

    assert result == {
        "success": False,
        "message": "更新完成：成功 2 天（其中 1 天已存在並跳過），失敗 1 天",
        "updated_dates": ["2026-07-08", "2026-07-09"],
        "failed_dates": ["2026-07-10"],
        "skipped_dates": ["2026-07-09"],
        "no_data_skipped_dates": [],
        "source_diagnostics": [],
        "diagnostic_codes": [],
    }


def test_parse_daily_update_output_fails_closed_for_empty_output() -> None:
    result = parse_daily_update_output("", ["2026-07-10"])

    assert result["success"] is False
    assert result["failed_dates"] == ["2026-07-10"]
    assert result["diagnostic_codes"] == ["batch_output_missing"]


def test_parse_daily_update_output_treats_explicit_no_data_as_safe_skip() -> None:
    result = parse_daily_update_output(
        "\n".join(
            [
                "SKIPPED_NO_DATA 2026-07-10 上游查無資料",
                "[UPDATE_SUMMARY] SUCCESS: 1 days, SKIPPED_NO_DATA: 1 days, FAILED: 0 days",
            ]
        ),
        ["2026-07-10", "2026-07-13"],
    )

    assert result["success"] is True
    assert result["skipped_dates"] == ["2026-07-10"]
    assert result["no_data_skipped_dates"] == ["2026-07-10"]
    assert result["failed_dates"] == []
    assert "上游查無資料，已跳過 1 天" in result["message"]


def test_parse_daily_update_output_keeps_existing_file_skip_separate_from_no_data() -> None:
    result = parse_daily_update_output(
        "2026-07-10 已存在，跳過\n"
        "SKIPPED_NO_DATA 2026-07-13 上游查無資料\n"
        "[UPDATE_SUMMARY] SUCCESS: 1 days, SKIPPED_NO_DATA: 1 days, FAILED: 0 days",
        ["2026-07-10", "2026-07-13"],
    )

    assert result["skipped_dates"] == ["2026-07-10", "2026-07-13"]
    assert result["no_data_skipped_dates"] == ["2026-07-13"]


def test_parse_daily_update_output_preserves_structured_non_trading_day_diagnostics() -> None:
    diagnostic = {
        "date": "2026-07-10",
        "outcome": "no_data",
        "reason_code": "twse_official_no_data",
        "request_attempts": [
            {"request_type": "ALL", "http_status": 307, "api_status": None},
            {
                "request_type": "ALLBUT0999",
                "http_status": 200,
                "api_status": "很抱歉，沒有符合條件的資料!",
            },
        ],
    }
    result = parse_daily_update_output(
        "\n".join(
            [
                f"UPDATE_DIAGNOSTIC {json.dumps(diagnostic, ensure_ascii=False)}",
                "SKIPPED_NO_DATA 2026-07-10 上游查無資料",
                "[UPDATE_SUMMARY] SUCCESS: 0 days, SKIPPED_NO_DATA: 1 days, FAILED: 0 days",
            ]
        ),
        ["2026-07-10"],
    )

    assert result["success"] is True
    assert result["source_diagnostics"] == [diagnostic]


def test_parse_daily_update_output_infers_real_failed_date_without_placeholder() -> None:
    result = parse_daily_update_output(
        "[UPDATE_SUMMARY] SUCCESS: 0 days, SKIPPED_NO_DATA: 0 days, FAILED: 1 days",
        ["2026-07-10"],
    )

    assert result["success"] is False
    assert result["failed_dates"] == ["2026-07-10"]
    assert "failed_date_unresolved" not in result["diagnostic_codes"]
