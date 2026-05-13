"""
Flow Signal Data Transfer Objects (DTOs)
定義由決策模組 (Decision Module) 產出的 Smart Money Flow 訊號結構
"""

from dataclasses import dataclass, field
from typing import List
from app_module.dtos.broker_flow_dtos import StockFlowAggregation

@dataclass
class FlowSignalDTO:
    """Smart Money Flow 訊號 (可供後續推薦/回測/UI使用)"""
    stock_code: str
    stock_name: str
    
    # 來自底層的聚合數據
    aggregation: StockFlowAggregation
    
    # --- 決策訊號屬性 ---
    
    # 主力分數 (0~100)
    smart_money_score: float = 0.0
    
    # 訊號信心度 (0.0~1.0)
    confidence: float = 0.0
    
    # 視覺化標籤 (例如：["連續吸籌", "主力一致買超"])
    signal_tags: List[str] = field(default_factory=list)
    
    # 可解釋性原因 (給 ReasonEngine 或 UI 顯示的具體文本)
    # 例如：["凱基台北與另外3家分點連續3日買超", "淨買超量超過過去平均兩倍"]
    explainable_reasons: List[str] = field(default_factory=list)

    # 籌碼集中度 (0.0~1.0, 1.0表示極度集中在少數分點)
    branch_concentration: float = 0.0
    
    # --- Terminal Scanner 視覺化屬性 ---
    
    # 趨勢線資料 (例如過去 5 天的淨買賣超序列，用於繪製 Inline Sparkline)
    sparkline_data: List[float] = field(default_factory=list)
    
    # 視覺強度等級 (-3 到 3)。大於 0 為淡綠，小於 0 為淡紅。數字越大顏色越深。用於 Row Intensity。
    intensity_level: int = 0

@dataclass
class SmartMoneySummaryDTO:
    """市場主力流向快速摘要 (供 Summary Strip 使用)"""
    market_regime: str = "Unknown"
    bullish_stock_count: int = 0
    bearish_stock_count: int = 0
    strong_industries: List[str] = field(default_factory=list)
    weak_industries: List[str] = field(default_factory=list)
    abnormal_signal_count: int = 0
    # 用於衡量整體市場熱度 (0~100)
    market_heat_score: float = 0.0
