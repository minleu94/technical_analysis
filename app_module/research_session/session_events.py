"""Event contracts for the thin research-session store."""

from dataclasses import dataclass
from typing import Optional, Union

from .session_dtos import ResearchStockContextDTO


@dataclass(frozen=True)
class ActiveSymbolChanged:
    symbol: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class ActiveRegimeChanged:
    regime: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class ActiveProfileChanged:
    profile: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class SelectedWatchlistChanged:
    watchlist_id: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class CurrentRecommendationRunChanged:
    run_id: Optional[str]
    source: str = "unknown"


@dataclass(frozen=True)
class StockResearchContextChanged:
    """切換目前單股研究上下文；只攜帶已保存或已觀測的來源 metadata。"""

    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    decision_date: Optional[str] = None
    data_date: Optional[str] = None
    result_id: Optional[str] = None
    profile_id: Optional[str] = None
    profile_version: Optional[str] = None
    source_id: Optional[str] = None
    source_kind: Optional[str] = None
    source_label: Optional[str] = None
    source_workspace: Optional[str] = None
    source: str = "unknown"
    # 允許 host 直接傳入 immutable DTO；展開欄位仍保留以相容舊呼叫端。
    context: Optional[ResearchStockContextDTO] = None


# 讓呼叫端可用較泛化的名稱，並保持單一事件契約。
ResearchContextChanged = StockResearchContextChanged


ResearchSessionEvent = Union[
    ActiveSymbolChanged,
    ActiveRegimeChanged,
    ActiveProfileChanged,
    SelectedWatchlistChanged,
    CurrentRecommendationRunChanged,
    StockResearchContextChanged,
]
