from data_module.fundamental_availability import FORMAL_AVAILABILITY_CONTRACT_VERSION
from data_module.fundamental_availability_entrypoint import (
    MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES,
    validate_monthly_revenue_availability_file,
)


_HASH = "a" * 64
_FORMAL_HEADER = (
    "stock_code,period,as_of_date,announced_date,available_date,source,source_version,"
    "availability_contract_version,evidence_class,source_hash,revision,parent_revision\n"
)


def _formal_csv_row(
    *,
    stock_code: str = "2330",
    period: str = "2026-05",
    as_of_date: str = "2026-05-31",
    announced_date: str = "2026-06-10",
    available_date: str = "2026-06-11",
    source: str = "manual.twse_monthly_revenue_announcement_log",
    source_version: str = "announcement-log-2026-06-16",
    evidence_class: str = "official_announcement",
    source_hash: str = f"sha256:{_HASH}",
    revision: str = "1",
    parent_revision: str = "",
) -> str:
    return ",".join(
        (
            stock_code,
            period,
            as_of_date,
            announced_date,
            available_date,
            source,
            source_version,
            FORMAL_AVAILABILITY_CONTRACT_VERSION,
            evidence_class,
            source_hash,
            revision,
            parent_revision,
        )
    ) + "\n"


def test_validate_monthly_revenue_availability_file_accepts_governed_source(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(_FORMAL_HEADER + _formal_csv_row(), encoding="utf-8-sig")

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()
    assert result.source_versions == ("announcement-log-2026-06-16",)


def test_validate_monthly_revenue_availability_file_rejects_local_first_seen_source(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        _FORMAL_HEADER
        + _formal_csv_row(
            source="manual.available_date_mapping",
            source_version="mops-first-seen-observation-2026-06-16",
            evidence_class="local_first_seen",
        ),
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == (
        "fundamental_availability.first_observed_evidence_not_formal"
    )


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
        _FORMAL_HEADER
        + _formal_csv_row(
            period="2024-04",
            as_of_date="2024-04-30",
            announced_date="2026-06-17",
            available_date="2026-06-18",
            source="mops.monthly_revenue_announcement",
            source_version="mops-t05st10-ifrs-2026-06-17",
        ),
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


def test_validate_monthly_revenue_availability_file_keeps_bounded_legacy_official_mapping(
    tmp_path,
):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text(
        "stock_code,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,2026-06,2026-06-30,2026-07-14,2026-07-15,"
        "twse.monthly_revenue_announcement,twse-openapi-t187ap05-l-2026-07-14\n",
        encoding="utf-8-sig",
    )

    result = validate_monthly_revenue_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()


def test_allowed_sources_do_not_include_raw_or_first_seen_source():
    assert "financial_data.monthly_revenue_csv" not in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
    assert "manual.available_date_mapping" not in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES


def test_allowed_sources_include_authorized_pit_source():
    assert (
        "tej.monthly_revenue_announcement_pit"
        in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
    )


def test_allowed_sources_include_retroactive_baseline_source():
    assert "manual.retroactive_baseline_mapping" in MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES
