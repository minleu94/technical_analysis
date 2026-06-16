from datetime import date
from decimal import Decimal

from app_module.fundamental_diagnostics_service import FundamentalDiagnosticsService


def test_fundamental_diagnostics_service_serializes_diagnostics_for_research_metadata():
    service = FundamentalDiagnosticsService()

    result = service.build_metadata(
        stock_code="2330",
        as_of_date=date(2026, 6, 15),
        revenue_yoy=Decimal("0.25"),
        operating_profit_yoy=Decimal("-0.10"),
        one_off_gain_ratio=None,
        quality_warnings=(),
        source_version="fundamental-diagnostics-v1",
    )

    assert result["schema_version"] == 1
    assert result["stock_code"] == "2330"
    assert result["diagnostics"][0]["code"] == "abnormal_fundamental.revenue_profit_divergence"
