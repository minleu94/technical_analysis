"""市場資料可見性的唯讀 DTO 契約。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "display_name": self.display_name,
            "as_of_date": self.as_of_date,
            "latest_observation_date": self.latest_observation_date,
            "available_date": self.available_date,
            "row_count": self.row_count,
            "stock_count": self.stock_count,
            "quality": self.quality,
            "pit_status": self.pit_status,
            "eligibility": self.eligibility,
            "warnings": list(self.warnings),
        }


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "latest_period": self.latest_period,
            "stock_count": self.stock_count,
            "mom_comparable_count": self.mom_comparable_count,
            "mom_positive_count": self.mom_positive_count,
            "mom_positive_ratio_bp": self.mom_positive_ratio_bp,
            "yoy_comparable_count": self.yoy_comparable_count,
            "yoy_positive_count": self.yoy_positive_count,
            "yoy_positive_ratio_bp": self.yoy_positive_ratio_bp,
            "quality": self.quality,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class InstitutionalFlowMarketSummary:
    latest_date: str | None
    stock_count: int
    foreign_net_shares: int | None
    investment_trust_net_shares: int | None
    dealer_net_shares: int | None
    quality: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "latest_date": self.latest_date,
            "stock_count": self.stock_count,
            "foreign_net_shares": self.foreign_net_shares,
            "investment_trust_net_shares": self.investment_trust_net_shares,
            "dealer_net_shares": self.dealer_net_shares,
            "quality": self.quality,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class MarketDataVisibilitySummary:
    as_of_date: str
    monthly_revenue: MonthlyRevenueBreadthSummary
    institutional_flow: InstitutionalFlowMarketSummary
    source_statuses: tuple[SourceVisibilityStatus, ...]
    overall_quality: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date,
            "monthly_revenue": self.monthly_revenue.to_dict(),
            "institutional_flow": self.institutional_flow.to_dict(),
            "source_statuses": [status.to_dict() for status in self.source_statuses],
            "overall_quality": self.overall_quality,
            "warnings": list(self.warnings),
        }
