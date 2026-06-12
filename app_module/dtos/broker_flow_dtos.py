"""
Broker Flow Data Transfer Objects (DTOs)
定義券商分點原始資料與基礎聚合資料的標準結構
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Any

@dataclass
class BrokerFlowEvent:
    """單筆分點進出紀錄 (原子數據)"""
    date: str
    branch_system_key: str
    branch_display_name: str
    stock_code: str
    stock_name: str
    buy_qty: Optional[int] = None
    sell_qty: Optional[int] = None
    net_qty: Optional[int] = None
    buy_amount_k_twd: Optional[int] = None
    sell_amount_k_twd: Optional[int] = None
    net_amount_k_twd: Optional[int] = None
    lots_available: bool = True
    has_estimated_lots: bool = False
    lots_observed: bool = True
    amount_observed: bool = True
    lots_rank: Optional[int] = None
    amount_rank: Optional[int] = None
    lots_quality: str = "observed"  # 'observed' | 'estimated' | 'unavailable'
    amount_quality: str = "observed"  # 'observed' | 'unavailable'

@dataclass
class StockFlowAggregation:
    """以「股票」為主體的聚合結果 (Overview Mode 使用)"""
    stock_code: str
    stock_name: str
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    total_net_qty: int = 0
    # 參與買超的分點名稱清單
    buying_branches: List[str] = field(default_factory=list)
    # 參與賣超的分點名稱清單
    selling_branches: List[str] = field(default_factory=list)
    # 此股票所有相關的原始事件
    events: List[BrokerFlowEvent] = field(default_factory=list)
    lots_available: bool = True
    has_estimated_lots: bool = False
    observed_event_count: int = 0
    estimated_event_count: int = 0
    unavailable_event_count: int = 0
    usable_event_count: int = 0
    lots_coverage_ratio: Decimal = Decimal("1")

@dataclass
class BranchFlowAggregation:
    """以「分點」為主體的聚合結果 (Branch Tracker Mode 使用)"""
    branch_system_key: str
    branch_display_name: str
    stock_code: str
    stock_name: str
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    total_net_qty: int = 0
    # 該分點操作此股票的歷史事件
    events: List[BrokerFlowEvent] = field(default_factory=list)
    # Sparkline 繪圖資料 (最近 5 筆)
    sparkline_data: List[float] = field(default_factory=list)
    # 趨勢詳細資料 (包含日期與買賣超張數，用於 ToolTip)
    sparkline_details: List[Any] = field(default_factory=list)
    lots_available: bool = True
    has_estimated_lots: bool = False
    observed_event_count: int = 0
    estimated_event_count: int = 0
    unavailable_event_count: int = 0
    usable_event_count: int = 0
    lots_coverage_ratio: Decimal = Decimal("1")
