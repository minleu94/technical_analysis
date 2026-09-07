"""Immutable DTOs for research-session context."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResearchStockContextDTO:
    """單股研究下鑽所需的唯讀來源脈絡。

    這個 DTO 只攜帶識別與日期，不攜帶行情、DataFrame 或重新計算結果。
    `decision_date` 是原研究決策日，`data_date` 是該次研究實際使用的資料日；
    兩者刻意分開，避免跨頁時把目前行情誤認成歷史研究日期。
    """

    stock_code: str
    stock_name: str = ""
    decision_date: str = ""
    data_date: str = ""
    result_id: str = ""
    profile_id: str = ""
    profile_version: str = ""
    source_id: str = ""
    source_kind: str = ""
    source_label: str = ""
    source_workspace: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "stock_code",
            "stock_name",
            "decision_date",
            "data_date",
            "result_id",
            "profile_id",
            "profile_version",
            "source_id",
            "source_kind",
            "source_label",
            "source_workspace",
        ):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, "" if value is None else str(value).strip())

    @property
    def has_source(self) -> bool:
        """是否有可返回的來源頁面。"""

        return bool(self.source_workspace)


@dataclass(frozen=True)
class ResearchSessionSnapshotDTO:
    """Current lightweight research workflow context.

    This snapshot is intentionally small. It should describe what the user is
    currently researching, not own market data, DataFrames, widget state, or
    computed business results.
    """

    active_symbol: Optional[str] = None
    active_regime: Optional[str] = None
    active_profile: Optional[str] = None
    selected_watchlist_id: Optional[str] = None
    current_recommendation_run_id: Optional[str] = None
    # 單股研究上下文。保留舊欄位以相容既有頁面與測試。
    stock_context: Optional[ResearchStockContextDTO] = None
    active_stock_code: Optional[str] = None
    decision_date: Optional[str] = None
    data_date: Optional[str] = None
    result_id: Optional[str] = None
    profile_id: Optional[str] = None
    profile_version: Optional[str] = None
    source_id: Optional[str] = None
    source_kind: Optional[str] = None
    source_label: Optional[str] = None
    source_workspace: Optional[str] = None
