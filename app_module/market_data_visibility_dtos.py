"""市場資料可見性的唯讀 DTO 契約。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceVisibilityStatus:
    source_id: str
    display_name: str
    as_of_date: str
    latest_observation_date: str | None
    available_date: str | None
    row_count: int
    stock_count: int
    quality: str
    pit_status: str
    eligibility: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MonthlyRevenueBreadthSummary:
    latest_period: str | None
    stock_count: int
    mom_comparable_count: int
    mom_positive_count: int
    mom_positive_ratio_bp: int | None
    yoy_comparable_count: int
    yoy_positive_count: int
    yoy_positive_ratio_bp: int | None
    quality: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstitutionalFlowMarketSummary:
    latest_date: str | None
    stock_count: int
    foreign_net_shares: int | None
    investment_trust_net_shares: int | None
    dealer_net_shares: int | None
    quality: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketDataVisibilitySummary:
    as_of_date: str
    monthly_revenue: MonthlyRevenueBreadthSummary
    institutional_flow: InstitutionalFlowMarketSummary
    source_statuses: tuple[SourceVisibilityStatus, ...]
    overall_quality: str
    warnings: tuple[str, ...] = ()
