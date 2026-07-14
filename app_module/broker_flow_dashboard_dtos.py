"""Broker Flow SQLite-first dashboard 的唯讀資料契約。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping

from app_module.dtos.smart_money_semantic_dtos import SmartMoneySemanticSummary
from decision_module.flow_contracts import BranchFlowAggregation, FlowSignalDTO, SmartMoneySummaryDTO


_PERIOD_TRADING_DAYS = {"day": 1, "week": 5, "month": 20}
_SCOPES = {"top_bottom", "top_bottom_50", "top50", "bottom50", "all"}


@dataclass(frozen=True)
class BrokerFlowLotQuantity:
    """把 SQLite 的股數明確轉成既有 BrokerFlowEvent 的整張單位。"""

    lots: int | None
    remainder_shares: int
    quality: str
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_sqlite_shares(cls, shares: int | None) -> "BrokerFlowLotQuantity":
        if shares is None:
            return cls(
                lots=None,
                remainder_shares=0,
                quality="unavailable",
                warnings=("share_quantity_unavailable",),
            )

        sign = -1 if shares < 0 else 1
        lots, remainder = divmod(abs(int(shares)), 1000)
        lots *= sign
        remainder *= sign
        if remainder:
            return cls(
                lots=lots,
                remainder_shares=remainder,
                quality="degraded",
                warnings=(f"non_board_lot_remainder_shares:{remainder}",),
            )
        return cls(lots=lots, remainder_shares=0, quality="observed")


@dataclass(frozen=True)
class BrokerFlowDashboardQuery:
    period: str
    scope: str
    requested_as_of_date: date
    limit_per_side: int = 50

    def __post_init__(self) -> None:
        if self.period not in _PERIOD_TRADING_DAYS:
            raise ValueError(f"unsupported period: {self.period}")
        if self.scope not in _SCOPES:
            raise ValueError(f"unsupported scope: {self.scope}")
        if not isinstance(self.requested_as_of_date, date):
            raise ValueError("requested_as_of_date must be an explicit date")
        if self.limit_per_side < 1:
            raise ValueError("limit_per_side must be at least 1")

    @property
    def period_trading_days(self) -> int:
        return _PERIOD_TRADING_DAYS[self.period]

    def select_trading_dates(self, available_dates: Iterable[date]) -> tuple[date, ...]:
        eligible = sorted(
            {
                item
                for item in available_dates
                if item <= self.requested_as_of_date
            }
        )
        return tuple(eligible[-self.period_trading_days :])


@dataclass(frozen=True)
class BrokerFlowDashboardSnapshot:
    as_of_date: date
    period: str
    top_signals: tuple[FlowSignalDTO, ...]
    bottom_signals: tuple[FlowSignalDTO, ...]
    summary: SmartMoneySummaryDTO
    semantics_by_code: Mapping[str, SmartMoneySemanticSummary]
    tracked_branches: tuple[tuple[str, str], ...]
    quality: str
    warnings: tuple[str, ...] = ()
    source_fingerprint: str = ""
    selected_trading_dates: tuple[date, ...] = ()
    query_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class BrokerFlowStockDetailSnapshot:
    as_of_date: date
    period: str
    stock_code: str
    rows: tuple[BranchFlowAggregation, ...]
    quality: str
    warnings: tuple[str, ...] = ()
    source_fingerprint: str = ""
    query_count: int = 0


@dataclass(frozen=True)
class BrokerFlowBranchTrackerSnapshot:
    as_of_date: date
    period: str
    branch_system_key: str
    rows: tuple[BranchFlowAggregation, ...]
    quality: str
    warnings: tuple[str, ...] = ()
    source_fingerprint: str = ""
    query_count: int = 0


__all__ = [
    "BrokerFlowDashboardQuery",
    "BrokerFlowDashboardSnapshot",
    "BrokerFlowStockDetailSnapshot",
    "BrokerFlowBranchTrackerSnapshot",
    "BrokerFlowLotQuantity",
]
