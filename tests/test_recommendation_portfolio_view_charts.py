import pandas as pd

from ui_qt.views.backtest_view import (
    build_recommendation_portfolio_drawdown,
    build_recommendation_portfolio_equity_series,
)


def test_build_recommendation_portfolio_equity_series_for_chart():
    equity_curve = pd.DataFrame(
        [
            {"date": "2026-01-02", "equity": 1000000.0},
            {"date": "2026-01-03", "equity": 1050000.0},
            {"date": "2026-01-06", "equity": 990000.0},
        ]
    )

    equity_series = build_recommendation_portfolio_equity_series(equity_curve)
    drawdown_series, max_dd_info = build_recommendation_portfolio_drawdown(equity_series)

    assert list(equity_series.index.strftime("%Y-%m-%d")) == [
        "2026-01-02",
        "2026-01-03",
        "2026-01-06",
    ]
    assert list(equity_series) == [1000000.0, 1050000.0, 990000.0]
    assert round(float(drawdown_series.iloc[-1]), 6) == round((990000.0 - 1050000.0) / 1050000.0, 6)
    assert max_dd_info["max_drawdown_date"].strftime("%Y-%m-%d") == "2026-01-06"
