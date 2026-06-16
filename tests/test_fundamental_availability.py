from datetime import date

from data_module.fundamental_availability import (
    FundamentalAvailabilityInput,
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
