from __future__ import annotations

from datetime import date

from data_module.fundamental_availability import FORMAL_AVAILABILITY_CONTRACT_VERSION
from data_module.fundamental_statement_availability_sources import (
    STATEMENT_AVAILABILITY_COLUMNS,
    load_statement_availability_overrides,
    load_statement_availability_overrides_csv,
    load_statement_availability_overrides_csv_files,
)
from decision_module.factors.factor_dtos import FactorQuality


_HASH = "a" * 64


def _formal_row(**overrides: str) -> dict[str, str]:
    row = {
        "stock_code": "2330",
        "statement_type": "income_statement",
        "period": "2024-Q1",
        "as_of_date": "2024-03-31",
        "announced_date": "2024-05-10",
        "available_date": "2024-05-11",
        "source": "manual.statement_available_date_mapping",
        "source_version": "statement-availability-2026-06-17",
        "availability_contract_version": FORMAL_AVAILABILITY_CONTRACT_VERSION,
        "evidence_class": "official_announcement",
        "source_hash": f"sha256:{_HASH}",
        "revision": "1",
        "parent_revision": "",
    }
    row.update(overrides)
    return row


def test_load_statement_availability_overrides_preserves_formal_announcement_contract():
    result = load_statement_availability_overrides([_formal_row()])

    override = result.overrides[("2330", "income_statement", "2024-Q1")]

    assert override.stock_code == "2330"
    assert override.statement_type == "income_statement"
    assert override.period == "2024-Q1"
    assert override.as_of_date == date(2024, 3, 31)
    assert override.announced_date == date(2024, 5, 10)
    assert override.available_date == date(2024, 5, 11)
    assert override.quality == FactorQuality.OBSERVED
    assert override.evidence_class == "official_announcement"
    assert override.source_hash == f"sha256:{_HASH}"
    assert override.revision == 1
    assert override.provenance_mode == "formal_v2"
    assert result.diagnostics == ()


def test_load_statement_availability_overrides_degrades_retroactive_baseline():
    result = load_statement_availability_overrides(
        [
            {
                "stock_code": "2330",
                "statement_type": "income_statement",
                "period": "2024-Q1",
                "as_of_date": "2024-03-31",
                "announced_date": "",
                "available_date": "2026-06-17",
                "source": "manual.retroactive_statement_baseline_mapping",
                "source_version": "statement-retroactive-baseline-2026-06-17",
            }
        ]
    )

    override = result.overrides[("2330", "income_statement", "2024-Q1")]

    assert override.announced_date is None
    assert override.available_date == date(2026, 6, 17)
    assert override.quality == FactorQuality.DEGRADED
    assert override.provenance_mode == "retroactive_baseline"
    assert result.diagnostics == ()


def test_load_statement_availability_overrides_rejects_local_first_seen_evidence():
    result = load_statement_availability_overrides(
        [
            _formal_row(
                source_version="statement-first-seen-observation-2026-06-17",
                evidence_class="local_first_seen",
            )
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == (
        "fundamental_statement_availability.first_observed_evidence_not_formal"
    )


def test_load_statement_availability_overrides_requires_revision_lineage():
    result = load_statement_availability_overrides(
        [_formal_row(revision="2", parent_revision="1")]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == (
        "fundamental_statement_availability.formal_revision_chain_incomplete"
    )


def test_load_statement_availability_overrides_rejects_raw_statement_source():
    result = load_statement_availability_overrides(
        [
            {
                "stock_code": "2330",
                "statement_type": "income_statement",
                "period": "2024-Q1",
                "as_of_date": "2024-03-31",
                "announced_date": "",
                "available_date": "2024-05-11",
                "source": "financial_data.income_statement_csv",
                "source_version": "raw-v1",
            }
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_statement_availability.raw_csv_not_available_source"


def test_load_statement_availability_overrides_csv_reads_governed_file(tmp_path):
    mapping_file = tmp_path / "fundamental_statement_availability.csv"
    row = _formal_row()
    mapping_file.write_text(
        ",".join(STATEMENT_AVAILABILITY_COLUMNS)
        + "\n"
        + ",".join(row[column] for column in STATEMENT_AVAILABILITY_COLUMNS)
        + "\n",
        encoding="utf-8-sig",
    )

    result = load_statement_availability_overrides_csv(mapping_file)

    assert result.overrides[("2330", "income_statement", "2024-Q1")].available_date == date(
        2024, 5, 11
    )
    assert result.diagnostics == ()


def test_load_statement_availability_overrides_csv_files_merges_and_deduplicates(
    tmp_path,
):
    first_file = tmp_path / "first.csv"
    second_file = tmp_path / "second.csv"
    first = _formal_row()
    second = _formal_row(
        stock_code="2317",
        period="2024-Q2",
        as_of_date="2024-06-30",
        announced_date="2024-08-09",
        available_date="2024-08-10",
        source_hash=f"sha256:{'b' * 64}",
    )

    for path, rows in ((first_file, [first]), (second_file, [second])):
        path.write_text(
            ",".join(STATEMENT_AVAILABILITY_COLUMNS)
            + "\n"
            + "\n".join(
                ",".join(row[column] for column in STATEMENT_AVAILABILITY_COLUMNS)
                for row in rows
            )
            + "\n",
            encoding="utf-8-sig",
        )

    result = load_statement_availability_overrides_csv_files(
        (first_file, second_file, first_file)
    )

    assert set(result.overrides) == {
        ("2330", "income_statement", "2024-Q1"),
        ("2317", "income_statement", "2024-Q2"),
    }
    assert result.diagnostics == ()


def test_load_statement_availability_overrides_csv_reports_missing_file(tmp_path):
    result = load_statement_availability_overrides_csv(
        tmp_path / "missing_fundamental_statement_availability.csv"
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_statement_availability.mapping_file_missing"
