from datetime import date

from data_module.fundamental_availability import FORMAL_AVAILABILITY_CONTRACT_VERSION
from data_module.fundamental_availability_sources import (
    MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
    load_monthly_revenue_availability_overrides,
    load_monthly_revenue_availability_overrides_csv,
)
from decision_module.factors.factor_dtos import FactorQuality


_HASH = "a" * 64


def _formal_row(**overrides: str) -> dict[str, str]:
    row = {
        "stock_code": "2330",
        "period": "2026-05",
        "as_of_date": "2026-05-31",
        "announced_date": "2026-06-10",
        "available_date": "2026-06-11",
        "source": "manual.twse_monthly_revenue_announcement_log",
        "source_version": "announcement-log-2026-06-16",
        "availability_contract_version": FORMAL_AVAILABILITY_CONTRACT_VERSION,
        "evidence_class": "official_announcement",
        "source_hash": f"sha256:{_HASH}",
        "revision": "1",
        "parent_revision": "",
    }
    row.update(overrides)
    return row


def test_load_monthly_revenue_availability_overrides_preserves_formal_announcement_contract():
    result = load_monthly_revenue_availability_overrides([_formal_row()])

    override = result.overrides[("2330", "2026-05")]

    assert override.stock_code == "2330"
    assert override.period == "2026-05"
    assert override.as_of_date == date(2026, 5, 31)
    assert override.announced_date == date(2026, 6, 10)
    assert override.available_date == date(2026, 6, 11)
    assert override.quality == FactorQuality.OBSERVED
    assert override.source == "manual.twse_monthly_revenue_announcement_log"
    assert override.source_version == "announcement-log-2026-06-16"
    assert override.evidence_class == "official_announcement"
    assert override.source_hash == f"sha256:{_HASH}"
    assert override.revision == 1
    assert override.provenance_mode == "formal_v2"
    assert result.diagnostics == ()


def test_load_monthly_revenue_availability_overrides_rejects_local_first_seen_evidence():
    result = load_monthly_revenue_availability_overrides(
        [
            _formal_row(
                announced_date="",
                source="manual.available_date_mapping",
                source_version="mops-first-seen-observation-2026-06-16",
                evidence_class="first_observed",
            )
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == (
        "fundamental_availability.first_observed_evidence_not_formal"
    )


def test_load_monthly_revenue_availability_overrides_allows_retroactive_baseline_without_announcement():
    result = load_monthly_revenue_availability_overrides(
        [
            {
                "stock_code": "2330",
                "period": "2024-04",
                "as_of_date": "2024-04-30",
                "announced_date": "",
                "available_date": "2026-06-17",
                "source": "manual.retroactive_baseline_mapping",
                "source_version": "mops-retroactive-baseline-2026-06-17",
            }
        ]
    )

    override = result.overrides[("2330", "2024-04")]

    assert override.announced_date is None
    assert override.available_date == date(2026, 6, 17)
    assert override.quality == FactorQuality.DEGRADED
    assert override.provenance_mode == "retroactive_baseline"
    assert result.diagnostics == ()


def test_load_monthly_revenue_availability_overrides_rejects_missing_available_date():
    result = load_monthly_revenue_availability_overrides([_formal_row(available_date="")])

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.missing_available_date"


def test_load_monthly_revenue_availability_overrides_rejects_raw_csv_date_as_source():
    result = load_monthly_revenue_availability_overrides(
        [
            {
                "stock_code": "2330",
                "period": "2026-05",
                "as_of_date": "2026-05-31",
                "announced_date": "",
                "available_date": "2026-06-10",
                "source": "financial_data.monthly_revenue_csv",
                "source_version": "financial-data-csv-preflight-v1",
            }
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.raw_csv_not_available_source"


def test_load_monthly_revenue_availability_overrides_csv_reads_governed_file(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    row = _formal_row()
    mapping_file.write_text(
        ",".join(MONTHLY_REVENUE_AVAILABILITY_COLUMNS)
        + "\n"
        + ",".join(row[column] for column in MONTHLY_REVENUE_AVAILABILITY_COLUMNS)
        + "\n",
        encoding="utf-8-sig",
    )

    result = load_monthly_revenue_availability_overrides_csv(mapping_file)

    override = result.overrides[("2330", "2026-05")]
    assert override.announced_date == date(2026, 6, 10)
    assert override.available_date == date(2026, 6, 11)
    assert override.quality == FactorQuality.OBSERVED
    assert result.diagnostics == ()


def test_load_monthly_revenue_availability_overrides_accepts_only_bounded_legacy_official_mapping():
    result = load_monthly_revenue_availability_overrides(
        [
            {
                "stock_code": "2330",
                "period": "2026-06",
                "as_of_date": "2026-06-30",
                "announced_date": "2026-07-14",
                "available_date": "2026-07-15",
                "source": "twse.monthly_revenue_announcement",
                "source_version": "twse-openapi-t187ap05-l-2026-07-14",
            }
        ]
    )

    override = result.overrides[("2330", "2026-06")]
    assert override.provenance_mode == "legacy_official_compatibility"
    assert result.diagnostics == ()


def test_load_monthly_revenue_availability_overrides_rejects_unversioned_new_official_mapping():
    result = load_monthly_revenue_availability_overrides(
        [
            _formal_row(
                source="twse.monthly_revenue_announcement",
                source_version="twse-openapi-t187ap05-l-2026-07-15",
                availability_contract_version="",
                evidence_class="",
                source_hash="",
                revision="",
            )
        ]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.formal_provenance_missing"


def test_load_monthly_revenue_availability_overrides_requires_contiguous_revision_lineage():
    result = load_monthly_revenue_availability_overrides(
        [_formal_row(revision="2", parent_revision="1")]
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == (
        "fundamental_availability.formal_revision_chain_incomplete"
    )


def test_load_monthly_revenue_availability_overrides_csv_reports_missing_file(tmp_path):
    result = load_monthly_revenue_availability_overrides_csv(
        tmp_path / "missing_monthly_revenue_availability.csv"
    )

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.mapping_file_missing"


def test_load_monthly_revenue_availability_overrides_csv_reports_missing_columns(tmp_path):
    mapping_file = tmp_path / "monthly_revenue_availability.csv"
    mapping_file.write_text("stock_code,period\n2330,2026-05\n", encoding="utf-8")

    result = load_monthly_revenue_availability_overrides_csv(mapping_file)

    assert result.overrides == {}
    assert result.diagnostics[0].code == "fundamental_availability.mapping_missing_columns"
