from typing import Any, Dict, List, Optional

import pandas as pd

from decision_module.industry_mapper import IndustryMapper
from decision_module.reason_engine import ReasonEngine
from decision_module.strategy_configurator import StrategyConfigurator


class RecommendationDataFrameProvider:
    """Use the existing recommendation scoring flow against an in-memory history slice."""

    def __init__(self, industry_mapper: Optional[IndustryMapper] = None):
        self.strategy_configurator = StrategyConfigurator()
        self.reason_engine = ReasonEngine()
        self.industry_mapper = industry_mapper

    def __call__(self, as_of_data: pd.DataFrame, config: Dict[str, Any], top_n: int) -> List[Dict[str, Any]]:
        data = self._normalize_columns(as_of_data)
        if data.empty:
            return []

        stock_col = "證券代號"
        recommendations = []
        for stock_code in data[stock_col].dropna().astype(str).unique():
            stock_df = data[data[stock_col].astype(str) == stock_code].copy()
            stock_df = stock_df.sort_values("日期").reset_index(drop=True)
            if len(stock_df) < 20:
                continue

            try:
                result_df = self.strategy_configurator.generate_recommendations(stock_df, config)
                if result_df.empty:
                    continue

                latest_row = result_df.iloc[-1].copy()
                close_col = self._first_existing_column(latest_row.index, ["收盤價", "Close", "close"])
                prev_price = pd.to_numeric(stock_df.iloc[-2].get(close_col, 0), errors="coerce") if close_col else 0
                curr_price = pd.to_numeric(latest_row.get(close_col, 0), errors="coerce") if close_col else 0
                price_change = ((curr_price - prev_price) / prev_price * 100) if prev_price and not pd.isna(prev_price) else 0
                latest_row["漲幅%"] = 0 if pd.isna(price_change) else price_change

                reasons = self.reason_engine.generate_reasons(latest_row, config)
                final_score = latest_row.get(
                    "FinalScore",
                    latest_row.get("TotalScore", latest_row.get("綜合評分", 0)),
                )
                recommendations.append(
                    {
                        "stock_code": stock_code,
                        "stock_name": str(latest_row.get("證券名稱", stock_df.iloc[-1].get("證券名稱", stock_code))),
                        "total_score": float(final_score or 0),
                        "factor_scores": {
                            "technical": float(latest_row.get("IndicatorScore", 0) or 0),
                            "pattern": float(latest_row.get("PatternScore", 0) or 0),
                            "volume": float(latest_row.get("VolumeScore", 0) or 0),
                            "broker_flow": float(latest_row.get("BrokerFlowScore", 0) or 0),
                            "revenue": float(latest_row.get("RevenueScore", 0) or 0),
                        },
                        "selection_reason": self.reason_engine.format_reason_text(reasons, max_reasons=3),
                    }
                )
            except Exception:
                continue

        recommendations.sort(key=lambda item: item["total_score"], reverse=True)
        return recommendations[:top_n]

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy()
        if "日期" not in data.columns:
            raise ValueError("history 必須包含 日期 欄位")
        data["日期"] = pd.to_datetime(data["日期"], errors="coerce")
        data = data[data["日期"].notna()]

        if "證券代號" not in data.columns and "股票代號" in data.columns:
            data["證券代號"] = data["股票代號"]
        if "證券代號" not in data.columns:
            raise ValueError("history 必須包含 證券代號 或 股票代號 欄位")
        data["證券代號"] = data["證券代號"].astype(str)

        if "證券名稱" not in data.columns:
            data["證券名稱"] = data["股票名稱"] if "股票名稱" in data.columns else data["證券代號"]
        return data

    def _first_existing_column(self, columns, candidates: List[str]) -> Optional[str]:
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return None
