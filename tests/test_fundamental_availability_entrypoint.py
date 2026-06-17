from data_module.fundamental_availability_entrypoint import (
    MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES,
    validate_monthly_revenue_availability_file,
)


def test_validate_monthly_revenue_availability_file_accepts_governed_source(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "manual.twse_monthly_revenue_announcement_log,announcement-log-2026-06-16\n",
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()
    assert result.source_versions == ("announcement-log-2026-06-16",)


def test_validate_monthly_revenue_availability_file_rejects_ungoverned_source(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-05,2026-05-31,2026-06-10,2026-06-11,"
        "financial_data.monthly_revenue_csv,raw-v1\n",
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == "fundamental_availability.raw_csv_not_available_source"


def test_validate_monthly_revenue_availability_file_reports_missing_file(tmp_path):
    result = validate_monthly_revenue_availability_file(
        tmp_path / "monthly_revenue_availability.csv"
    )

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == "fundamental_availability.mapping_file_missing"


def test_validate_monthly_revenue_availability_file_rejects_unreasonably_late_available_date(
    tmp_path,
):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2024-04,2024-04-30,2026-06-17,2026-06-18,"
        "mops.monthly_revenue_announcement,mops-t05st10-ifrs-2026-06-17\n",
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == (
        "fundamental_availability.available_date_unreasonably_late"
    )


def test_validate_monthly_revenue_availability_file_accepts_retroactive_baseline_source(
    tmp_path,
):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2024-04,2024-04-30,,2026-06-17,"
        "manual.retroactive_baseline_mapping,mops-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()
    assert result.source_versions == ("mops-retroactive-baseline-2026-06-17",)


def test_allowed_sources_do_not_include_raw_csv_source():
    assert "financial_data.monthly_revenue_csv" not in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES


def test_allowed_sources_include_authorized_pit_source():
    assert (
        "tej.monthly_revenue_announcement_pit"
        in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
    )


def test_allowed_sources_include_retroactive_baseline_source():
    assert "manual.retroactive_baseline_mapping" in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
