"""Application boundary for fundamental diagnostics metadata."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from decision_module.factors.abnormal_fundamental_flags import (
    build_abnormal_fundamental_diagnostics,
)


class FundamentalDiagnosticsService:
    def build_metadata(
        self,
        *,
        stock_code: str,
        as_of_date: date,
        revenue_yoy: Decimal | None,
        operating_profit_yoy: Decimal | None,
        one_off_gain_ratio: Decimal | None,
        quality_warnings: tuple[str, ...],
        source_version: str,
    ) -> dict[str, Any]:
        diagnostics = build_abnormal_fundamental_diagnostics(
            stock_code=stock_code,
            as_of_date=as_of_date,
            revenue_yoy=revenue_yoy,
            operating_profit_yoy=operating_profit_yoy,
            one_off_gain_ratio=one_off_gain_ratio,
            quality_warnings=quality_warnings,
            source_version=source_version,
        )
        return {
            "schema_version": 1,
            "stock_code": stock_code,
            "as_of_date": as_of_date.isoformat(),
            "source_version": source_version,
            "diagnostics": [item.to_dict() for item in diagnostics],
        }
