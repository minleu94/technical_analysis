"""
報告匯出資料傳輸對象 (Report Export DTOs)
定義規格化報告匯出所使用的 DTO 與 Payload 契約，確保資料不可變性與防禦性複製。
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import pandas as pd


@dataclass(frozen=True)
class ReportMetadata:
    """報告元數據，保存資料版本、策略版本、市場狀態等可追溯欄位"""
    report_type: str
    generated_at: str = ""
    data_as_of_date: str = ""
    data_version: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    regime: str = ""
    benchmark: str = ""
    execution_assumption: str = ""

    def missing_fields(self) -> List[str]:
        """獲取缺失的必要欄位清單"""
        required = (
            "generated_at",
            "data_as_of_date",
            "data_version",
            "strategy_version",
            "regime",
            "benchmark",
            "execution_assumption",
        )
        return [name for name in required if not getattr(self, name)]


@dataclass
class SingleBacktestExportPayload:
    """單股回測匯出資料載荷"""
    metadata: ReportMetadata
    run_params: Dict[str, Any]
    metrics: Dict[str, Any]
    validation: Dict[str, Any]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame

    def __post_init__(self):
        # 進行防禦性複製以防止外部變更
        self.trades = self.trades.copy()
        self.equity_curve = self.equity_curve.copy()


@dataclass
class BatchBacktestExportPayload:
    """批次回測匯出資料載荷"""
    metadata: ReportMetadata
    leaderboard: pd.DataFrame
    overall_stats: str

    def __post_init__(self):
        self.leaderboard = self.leaderboard.copy()


@dataclass
class RecommendationReplayExportPayload:
    """推薦回放組合回測匯出資料載荷"""
    metadata: ReportMetadata
    run_params: Dict[str, Any]
    summary: Dict[str, Any]
    period_holdings: pd.DataFrame
    stock_contribution: pd.DataFrame
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    diagnostics: List[str] = field(default_factory=list)
    improvement_hints: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.period_holdings = self.period_holdings.copy()
        self.stock_contribution = self.stock_contribution.copy()
        self.trades = self.trades.copy()
        self.equity_curve = self.equity_curve.copy()


@dataclass
class CurrentRecommendationExportPayload:
    """當前推薦結果匯出資料載荷"""
    metadata: ReportMetadata
    run_params: Dict[str, Any]
    recommendations: pd.DataFrame
    regime_snapshot: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        self.recommendations = self.recommendations.copy()
