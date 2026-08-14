from __future__ import annotations

from data_module.fundamental_availability import FORMAL_AVAILABILITY_CONTRACT_VERSION
from data_module.fundamental_statement_availability_entrypoint import (
    STATEMENT_ALLOWED_AVAILABILITY_SOURCES,
    validate_statement_availability_file,
)


_HASH = "a" * 64
_FORMAL_HEADER = (
    "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,"
    "source_version,availability_contract_version,evidence_class,source_hash,revision,"
    "parent_revision\n"
)


def _formal_csv_row(
    *,
    stock_code: str = "2330",
    statement_type: str = "income_statement",
    period: str = "2024-Q1",
    as_of_date: str = "2024-03-31",
    announced_date: str = "2024-05-10",
    available_date: str = "2024-05-11",
    source: str = "manual.statement_available_date_mapping",
    source_version: str = "statement-availability-2026-06-17",
    evidence_class: str = "official_announcement",
    source_hash: str = f"sha256:{_HASH}",
    revision: str = "1",
    parent_revision: str = "",
) -> str:
    return ",".join(
        (
            stock_code,
            statement_type,
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


def test_validate_statement_availability_file_accepts_governed_source(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(_FORMAL_HEADER + _formal_csv_row(), encoding="utf-8-sig")

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()


def test_validate_statement_availability_file_rejects_local_first_seen_evidence(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        _FORMAL_HEADER
        + _formal_csv_row(
            source_version="statement-first-seen-observation-2026-06-17",
            evidence_class="local_first_seen",
        ),
        encoding="utf-8-sig",
    )

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == (
        "fundamental_statement_availability.first_observed_evidence_not_formal"
    )


def test_validate_statement_availability_file_accepts_retroactive_baseline(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2026-06-17,"
        "manual.retroactive_statement_baseline_mapping,statement-retroactive-baseline-2026-06-17\n",
        encoding="utf-8-sig",
    )

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()


def test_validate_statement_availability_file_rejects_raw_csv_source(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        "stock_code,statement_type,period,as_of_date,announced_date,available_date,source,source_version\n"
        "2330,income_statement,2024-Q1,2024-03-31,,2024-05-11,"
        "financial_data.income_statement_csv,raw-v1\n",
        encoding="utf-8-sig",
    )

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == (
        "fundamental_statement_availability.raw_csv_not_available_source"
    )


def test_validate_statement_availability_file_reports_missing_file(tmp_path):
    result = validate_statement_availability_file(
        tmp_path / "missing_fundamental_statement_availability.csv"
    )

    assert result.valid is False
    assert result.accepted_count == 0
    assert result.diagnostics[0].code == "fundamental_statement_availability.mapping_file_missing"


def test_allowed_sources_include_statement_retroactive_baseline():
    assert (
        "manual.retroactive_statement_baseline_mapping"
        in STATEMENT_ALLOWED_AVAILABILITY_SOURCES
    )


def test_allowed_sources_include_official_mops_ezsearch_publication():
    assert "mops.ezsearch.statement_publication" in STATEMENT_ALLOWED_AVAILABILITY_SOURCES


def test_validate_statement_availability_file_accepts_late_official_mops_publication(
    tmp_path,
):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    mapping_file.write_text(
        _FORMAL_HEADER
        + _formal_csv_row(
            stock_code="7835",
            period="2025-Q4",
            as_of_date="2025-12-31",
            announced_date="2026-07-27",
            available_date="2026-07-28",
            source="mops.ezsearch.statement_publication",
            source_version="mops-ezsearch-statement-publication.v1",
        ),
        encoding="utf-8-sig",
    )

    result = validate_statement_availability_file(mapping_file)

    assert result.valid is True
    assert result.accepted_count == 1
    assert result.diagnostics == ()
