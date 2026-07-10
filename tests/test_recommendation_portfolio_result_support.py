from decimal import Decimal

import pandas as pd

from app_module.recommendation_portfolio_result_support import (
    build_credibility_manifest,
    build_relative_attribution,
    return_bp_from_values,
)


def test_return_bp_uses_decimal_basis_points_and_rejects_nonpositive_start() -> None:
    assert return_bp_from_values(pd.Series([Decimal("100"), Decimal("101.25")])) == 125
    assert return_bp_from_values(pd.Series([Decimal("0"), Decimal("101")])) is None


def test_relative_attribution_reports_available_benchmark_and_missing_optional_sources() -> None:
    result = build_relative_attribution(
        pd.DataFrame({"equity": [100, 110]}),
        pd.DataFrame({"日期": ["2026-01-01", "2026-01-02"], "benchmark_close": [200, 210]}),
    )
    assert result["portfolio_return_bp"] == 1000
    assert result["benchmarks"]["benchmark"]["excess_return_bp"] == 500
    assert result["missing_sources"] == ["concept", "industry"]


def test_credibility_manifest_keeps_execution_disclosure_without_changing_execution() -> None:
    result = build_credibility_manifest("weekly", "equal", 0.1, True, 100)
    assert result["execution_costs"]["supported"] == "partial"
    assert result["share_sizing"]["policy"] == "full_lot_floor_sizing"
