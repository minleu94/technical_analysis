"""
回測視圖常數與純計算輔助函數
"""

import pandas as pd

RESEARCH_LAB_MODES = [
    {
        "id": "single_stock",
        "label": "單股回測",
        "description": "測一檔股票套用指定策略後的交易表現。",
        "primary_input": "股票代號",
    },
    {
        "id": "batch_stock",
        "label": "批次股票回測",
        "description": "一次測一批候選股票，找出策略在不同標的上的表現差異。",
        "primary_input": "候選池 / 選股清單",
    },
    {
        "id": "fixed_basket",
        "label": "固定組合回測",
        "description": "測固定一籃股票在指定期間內的組合表現。",
        "primary_input": "固定股票清單",
    },
    {
        "id": "recommendation_replay",
        "label": "推薦系統回放",
        "description": "把推薦結果送進 Research Lab，檢查推薦邏輯在歷史資料中的表現。",
        "primary_input": "推薦結果",
    },
    {
        "id": "strategy_research",
        "label": "策略研究",
        "description": "比較策略模板、參數版本與優化結果，作為升級策略版本的依據。",
        "primary_input": "策略模板 / 參數",
    },
]


def build_recommendation_portfolio_equity_series(equity_curve: pd.DataFrame) -> pd.Series:
    """Convert recommendation portfolio equity rows into chart-ready series."""
    if equity_curve is None or equity_curve.empty or "date" not in equity_curve.columns or "equity" not in equity_curve.columns:
        return pd.Series(dtype=float)

    series = pd.Series(
        pd.to_numeric(equity_curve["equity"], errors="coerce").values,
        index=pd.to_datetime(equity_curve["date"], errors="coerce"),
        dtype=float,
    )
    series = series[series.index.notna()].dropna()
    return series.sort_index()


def build_recommendation_portfolio_drawdown(equity_series: pd.Series) -> tuple[pd.Series, dict]:
    """Build drawdown series and max-drawdown marker metadata."""
    if equity_series is None or equity_series.empty:
        return pd.Series(dtype=float), {}

    cummax = equity_series.cummax()
    drawdown_series = (equity_series - cummax) / cummax
    max_dd_date = drawdown_series.idxmin()
    peak_date = equity_series.loc[:max_dd_date].idxmax() if max_dd_date is not None else None
    return drawdown_series, {
        "max_drawdown": float(drawdown_series.loc[max_dd_date]) if max_dd_date is not None else 0.0,
        "max_drawdown_date": max_dd_date,
        "peak_date": peak_date,
        "peak_value": float(equity_series.loc[peak_date]) if peak_date is not None else None,
    }
