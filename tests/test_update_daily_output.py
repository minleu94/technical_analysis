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
