from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd

from app_module.recommendation_portfolio_dtos import RecommendationSnapshotDTO
from app_module.recommendation_portfolio_dates import parse_stock_dates


RecommendationProvider = Callable[[pd.DataFrame, Dict[str, Any], int], List[Dict[str, Any]]]


class RecommendationReplayService:
    def __init__(self, provider: RecommendationProvider):
        self.provider = provider

    def run_snapshot(
        self,
        as_of_date: str,
        profile_id: str,
        config: Dict[str, Any],
        history: pd.DataFrame,
        universe: Optional[Iterable[str]],
        top_n: int,
    ) -> RecommendationSnapshotDTO:
        if "日期" not in history.columns:
            raise ValueError("history 必須包含 日期 欄位")

        as_of_ts = pd.to_datetime(as_of_date)
        data = history.copy()
        data["日期"] = parse_stock_dates(data["日期"])
        data = data[data["日期"].notna()]
        data = data[data["日期"] <= as_of_ts]

        diagnostics = []
        if universe is not None:
            universe_set = {str(code) for code in universe}
            stock_col = "證券代號" if "證券代號" in data.columns else "股票代號"
            if stock_col in data.columns:
                data = data[data[stock_col].astype(str).isin(universe_set)]
            else:
                diagnostics.append("missing_stock_code_column")

        recommendations = self.provider(data, config, top_n)[:top_n]

        return RecommendationSnapshotDTO(
            as_of_date=as_of_ts.strftime("%Y-%m-%d"),
            profile_id=profile_id,
            strategy_config=config,
            regime=str(config.get("regime") or ""),
            recommendations=recommendations,
            diagnostics=diagnostics,
        )
