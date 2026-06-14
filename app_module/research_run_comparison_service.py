"""Research Run Registry 跨 run 比較服務。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

import pandas as pd

from app_module.research_run_dtos import ResearchRunMetadataDTO


class ComparabilityStatus(str, Enum):
    """Research run 直接比較的治理狀態。"""

    COMPARABLE = "Comparable"
    CAUTION = "Caution"
    INCOMPATIBLE = "Incompatible"


@dataclass(frozen=True)
class ComparabilityResult:
    status: ComparabilityStatus
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedEquityResult:
    normalized: dict[str, pd.DataFrame]
    date_intersection: list[str]
    excluded_dates: dict[str, list[str]]


class ResearchRunComparisonService:
    """比較已保存 Research Run 的 metadata 與展示用 equity curve。"""

    def evaluate_comparability(
        self, runs: list[ResearchRunMetadataDTO]
    ) -> ComparabilityResult:
        if len(runs) < 2:
            return ComparabilityResult(ComparabilityStatus.COMPARABLE, [])

        baseline = runs[0]
        incompatible_reasons = self._incompatible_reasons(baseline, runs[1:])
        if incompatible_reasons:
            return ComparabilityResult(
                ComparabilityStatus.INCOMPATIBLE,
                incompatible_reasons,
            )

        caution_reasons = self._caution_reasons(baseline, runs[1:])
        if caution_reasons:
            return ComparabilityResult(ComparabilityStatus.CAUTION, caution_reasons)

        return ComparabilityResult(ComparabilityStatus.COMPARABLE, [])

    def build_normalized_equity(
        self, equity_by_run: dict[str, pd.DataFrame]
    ) -> NormalizedEquityResult:
        date_sets: dict[str, set[str]] = {}
        prepared: dict[str, pd.DataFrame] = {}
        for run_id, equity in equity_by_run.items():
            frame = self._prepare_equity_frame(equity)
            prepared[run_id] = frame
            date_sets[run_id] = set(frame["date"].tolist())

        if not date_sets:
            return NormalizedEquityResult({}, [], {})

        common_dates = sorted(set.intersection(*date_sets.values()))
        normalized: dict[str, pd.DataFrame] = {}
        excluded_dates: dict[str, list[str]] = {}
        for run_id, frame in prepared.items():
            excluded_dates[run_id] = sorted(date_sets[run_id] - set(common_dates))
            intersected = frame[frame["date"].isin(common_dates)].copy()
            intersected = intersected.sort_values("date")
            normalized[run_id] = self._normalize_intersected_equity(intersected)

        return NormalizedEquityResult(normalized, common_dates, excluded_dates)

    def collect_benchmark_attribution(
        self, runs: list[ResearchRunMetadataDTO]
    ) -> dict[str, dict[str, Any]]:
        return {run.run_id: dict(run.benchmark_results) for run in runs}

    def _incompatible_reasons(
        self,
        baseline: ResearchRunMetadataDTO,
        runs: list[ResearchRunMetadataDTO],
    ) -> list[str]:
        checks = [
            (
                "data fingerprint differs",
                lambda run: run.data_fingerprint != baseline.data_fingerprint,
            ),
            (
                "execution price differs",
                lambda run: run.execution_price != baseline.execution_price,
            ),
            (
                "sizing mode differs",
                lambda run: run.sizing_mode != baseline.sizing_mode,
            ),
        ]
        return self._ordered_reasons(runs, checks)

    def _caution_reasons(
        self,
        baseline: ResearchRunMetadataDTO,
        runs: list[ResearchRunMetadataDTO],
    ) -> list[str]:
        baseline_universe = sorted(str(item) for item in baseline.universe)
        baseline_cost = (
            baseline.capital_cents,
            baseline.fee_bp_x100,
            baseline.slippage_bp_x100,
            baseline.stop_loss_bp,
            baseline.take_profit_bp,
        )
        checks = [
            (
                "universe differs",
                lambda run: sorted(str(item) for item in run.universe)
                != baseline_universe,
            ),
            (
                "date range differs",
                lambda run: (run.start_date, run.end_date)
                != (baseline.start_date, baseline.end_date),
            ),
            (
                "cost model differs",
                lambda run: (
                    run.capital_cents,
                    run.fee_bp_x100,
                    run.slippage_bp_x100,
                    run.stop_loss_bp,
                    run.take_profit_bp,
                )
                != baseline_cost,
            ),
        ]
        return self._ordered_reasons(runs, checks)

    def _ordered_reasons(
        self,
        runs: list[ResearchRunMetadataDTO],
        checks: list[tuple[str, Any]],
    ) -> list[str]:
        reasons: list[str] = []
        for reason, predicate in checks:
            if any(predicate(run) for run in runs):
                reasons.append(reason)
        return reasons

    def _prepare_equity_frame(self, equity: pd.DataFrame) -> pd.DataFrame:
        date_column = "日期" if "日期" in equity.columns else "date"
        if date_column not in equity.columns:
            raise ValueError("equity curve 必須包含 date 或 日期 欄位")
        if "portfolio_value" not in equity.columns:
            raise ValueError("equity curve 必須包含 portfolio_value 欄位")

        frame = equity[[date_column, "portfolio_value"]].copy()
        frame.columns = ["date", "portfolio_value"]
        frame["date"] = frame["date"].map(str)
        return frame

    def _normalize_intersected_equity(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=["date", "normalized_value"])

        base_value = Decimal(str(frame.iloc[0]["portfolio_value"]))
        if base_value == 0:
            raise ValueError("equity curve 起始值不可為 0")

        records: list[dict[str, Any]] = []
        for row in frame.itertuples(index=False):
            value = Decimal(str(row.portfolio_value))
            normalized = (value / base_value * Decimal("10000")).to_integral_value(
                rounding=ROUND_HALF_UP
            )
            records.append(
                {
                    "date": str(row.date),
                    "normalized_value": int(normalized),
                }
            )
        return pd.DataFrame(records, columns=["date", "normalized_value"])
