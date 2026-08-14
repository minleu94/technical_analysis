from datetime import date

from data_module.fundamental_availability import (
    FundamentalAvailabilityInput,
    parse_formal_official_provenance,
    resolve_fundamental_availability,
)
from decision_module.factors.factor_dtos import FactorQuality


def test_resolve_availability_accepts_explicit_available_date_with_announcement():
    result = resolve_fundamental_availability(
        FundamentalAvailabilityInput(
            stock_code="2330",
            period="2026-05",
            as_of_date=date(2026, 5, 31),
            announced_date=date(2026, 6, 10),
            explicit_available_date=date(2026, 6, 11),
            source="twse.monthly_revenue",
        )
    )

    assert result.available_date == date(2026, 6, 11)
    assert result.announced_date == date(2026, 6, 10)
    assert result.quality == FactorQuality.OBSERVED
    assert result.diagnostics == ()


def test_resolve_availability_degrades_when_announcement_date_is_missing():
    result = resolve_fundamental_availability(
        FundamentalAvailabilityInput(
            stock_code="2330",
            period="2026-05",
            as_of_date=date(2026, 5, 31),
            announced_date=None,
            explicit_available_date=date(2026, 6, 11),
            source="manual.available_date_mapping",
        )
    )

    assert result.available_date == date(2026, 6, 11)
    assert result.announced_date is None
    assert result.quality == FactorQuality.DEGRADED
    assert result.diagnostics[0].code == "fundamental_availability.missing_announced_date"


def test_resolve_availability_reports_missing_available_date():
    result = resolve_fundamental_availability(
        FundamentalAvailabilityInput(
            stock_code="2330",
            period="2026-05",
            as_of_date=date(2026, 5, 31),
            announced_date=date(2026, 6, 10),
            explicit_available_date=None,
            source="financial_data.monthly_revenue_csv",
        )
    )

    assert result.available_date is None
    assert result.quality == FactorQuality.MISSING
    assert result.diagnostics[0].code == "fundamental_availability.missing_available_date"


def test_resolve_availability_rejects_available_date_before_announcement():
    result = resolve_fundamental_availability(
        FundamentalAvailabilityInput(
            stock_code="2330",
            period="2026-05",
            as_of_date=date(2026, 5, 31),
            announced_date=date(2026, 6, 10),
            explicit_available_date=date(2026, 6, 9),
            source="bad.mapping",
        )
    )

    assert result.available_date is None
    assert result.quality == FactorQuality.MISSING
    assert result.diagnostics[0].code == "fundamental_availability.available_before_announcement"


def test_resolve_availability_rejects_available_date_before_period_end():
    result = resolve_fundamental_availability(
        FundamentalAvailabilityInput(
            stock_code="2330",
            period="2026-05",
            as_of_date=date(2026, 5, 31),
            announced_date=None,
            explicit_available_date=date(2026, 5, 30),
            source="bad.mapping",
        )
    )

    assert result.available_date is None
    assert result.quality == FactorQuality.MISSING
    assert result.diagnostics[0].code == "fundamental_availability.available_before_period_end"


def test_formal_provenance_requires_official_evidence_hash_and_initial_lineage():
    provenance, issues = parse_formal_official_provenance(
        evidence_class="official_announcement",
        source_hash="sha256:" + "a" * 64,
        revision="1",
        parent_revision="",
    )

    assert issues == ()
    assert provenance is not None
    assert provenance.revision == 1
    assert provenance.parent_revision is None


def test_formal_provenance_rejects_first_observed_evidence():
    provenance, issues = parse_formal_official_provenance(
        evidence_class="first_observed",
        source_hash="sha256:" + "a" * 64,
        revision="1",
        parent_revision="",
    )

    assert provenance is None
    assert issues == ("first_observed_evidence_not_formal",)
