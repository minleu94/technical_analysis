from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from app_module.recommendation_portfolio_result_support import (
    build_credibility_manifest,
    build_factor_manifest,
    build_relative_attribution,
    build_stock_contribution,
    return_bp_from_values,
)
from app_module.recommendation_portfolio_dtos import RecommendationSnapshotDTO


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


def test_stock_contribution_sorts_by_total_pnl_and_reports_return_fields() -> None:
    first = SimpleNamespace(stock_code="2330", stock_name="台積電", return_pct=0.10, pnl=lambda: 100.0)
    second = SimpleNamespace(stock_code="2330", stock_name="台積電", return_pct=-0.05, pnl=lambda: -25.0)
    third = SimpleNamespace(stock_code="2317", stock_name="鴻海", return_pct=0.02, pnl=lambda: 20.0)

    result = build_stock_contribution([first, second, third])

    assert [item.stock_code for item in result] == ["2330", "2317"]
    assert result[0].selected_count == 2
    assert result[0].total_pnl == 75.0
    assert result[0].win_rate == 0.5


def test_factor_manifest_keeps_empty_snapshot_dates_and_empty_sections() -> None:
    snapshot = RecommendationSnapshotDTO("2026-01-02", "p", {}, "normal", [])

    result = build_factor_manifest([snapshot], lambda _: [])

    assert result["factor_snapshot"]["decision_date"] == "2026-01-02"
    assert result["factor_snapshot"]["decision_dates"] == ["2026-01-02"]
    assert result["factor_snapshot"]["records"] == []
    assert result["factor_snapshot"]["diagnostics"] == []
