from typing import Any, Dict, List, Optional
import warnings

import numpy as np
import pandas as pd

from decision_module.industry_mapper import IndustryMapper
from decision_module.reason_engine import ReasonEngine
from decision_module.strategy_configurator import StrategyConfigurator
from app_module.recommendation_portfolio_dates import parse_stock_dates


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
        lookback_days = int(config.get("_portfolio_lookback_days", 80))
        max_stocks = int(config.get("_portfolio_max_stocks", 200))
        latest_date = data["日期"].max()
        if pd.notna(latest_date) and lookback_days > 0:
            data = data[data["日期"] >= latest_date - pd.Timedelta(days=lookback_days)]
        stock_codes = data[stock_col].dropna().astype(str).unique()[:max_stocks]
        recommendations = []
        for stock_code in stock_codes:
            stock_df = data[data[stock_col].astype(str) == stock_code].copy()
            stock_df = stock_df.sort_values("日期").reset_index(drop=True)
            if len(stock_df) < 20:
                continue
            if not self._passes_fast_filters(stock_df, config):
                continue

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", np.exceptions.RankWarning)
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

    def _passes_fast_filters(self, stock_df: pd.DataFrame, config: Dict[str, Any]) -> bool:
        filters = config.get("filters", {})
        if not filters:
            return True

        close_col = self._first_existing_column(stock_df.columns, ["收盤價", "Close", "close"])
        if close_col and len(stock_df) >= 2:
            prev_price = pd.to_numeric(stock_df.iloc[-2].get(close_col, 0), errors="coerce")
            curr_price = pd.to_numeric(stock_df.iloc[-1].get(close_col, 0), errors="coerce")
            price_change = ((curr_price - prev_price) / prev_price * 100) if prev_price and not pd.isna(prev_price) else 0
            price_min = filters.get("price_change_min")
            price_max = filters.get("price_change_max")
            if price_min is not None and price_change < float(price_min):
                return False
            if price_max is not None and price_change > float(price_max):
                return False

        volume_col = self._first_existing_column(stock_df.columns, ["成交股數", "成交量", "Volume", "volume"])
        volume_min = filters.get("volume_ratio_min")
        if volume_col and volume_min is not None and len(stock_df) >= 21:
            latest_volume = pd.to_numeric(stock_df[volume_col].iloc[-1], errors="coerce")
            volume_ma20 = pd.to_numeric(stock_df[volume_col].iloc[-21:-1], errors="coerce").mean()
            volume_change = ((latest_volume / volume_ma20) - 1) * 100 if volume_ma20 and not pd.isna(volume_ma20) else 0
            threshold = self._normalize_volume_threshold(float(volume_min))
            if volume_change < threshold:
                return False

        return True

    def _normalize_volume_threshold(self, volume_ratio_min: float) -> float:
        if -50 <= volume_ratio_min <= 10:
            return (volume_ratio_min - 1) * 100
        return volume_ratio_min

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy()
        if "日期" not in data.columns:
            raise ValueError("history 必須包含 日期 欄位")
        data["日期"] = parse_stock_dates(data["日期"])
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
