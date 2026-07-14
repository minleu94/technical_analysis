"""Causal matured-label construction for historical ML shadow datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Literal, Mapping

from data_module.ml_historical_snapshot_provider import (
    HistoricalIndexObservation,
    HistoricalPriceObservation,
)
from ml_module.historical_contracts import HistoricalFeatureRow, HistoricalLabelRow
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY, LabelRegistry


CorporateActionQuality = Literal["clean", "degraded", "blocked"]


@dataclass(frozen=True)
class CorporateActionLabelEligibility:
    """Stable B-side input boundary for an E2 corporate-action eligibility result."""

    label_start_date: str
    label_end_date: str
    eligible: bool
    quality: CorporateActionQuality
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        start = date.fromisoformat(self.label_start_date[:10])
        end = date.fromisoformat(self.label_end_date[:10])
        if end <= start:
            raise ValueError("corporate-action label window end must follow start")
        if self.eligible and self.quality != "clean":
            raise ValueError("eligible corporate-action labels must be clean")
        if not self.eligible and self.quality == "clean":
            raise ValueError("ineligible corporate-action labels cannot be clean")


@dataclass(frozen=True)
class HistoricalLabelBuildResult:
    labels: tuple[HistoricalLabelRow, ...]
    accepted_diagnostics: dict[str, int]
    excluded_diagnostics: dict[str, int]
    corporate_action_coverage: str
    formal_oos_allowed: bool
    blockers: tuple[str, ...]
    shadow_only: bool = True
    production_action_allowed: bool = False


@dataclass(frozen=True)
class _Candidate:
    symbol: str
    decision_date: str
    horizon_end_date: str
    relative_return_bp: int
    maximum_adverse_excursion_bp: int
    downside_flag: int
    quality: Literal["clean", "degraded"]


class HistoricalLabelBuilder:
    """Builds 20-trading-day labels without calendar-day or future-as-of peeking."""

    def __init__(
        self,
        *,
        label_registry: LabelRegistry = CORE_LONG_HISTORY_LABEL_REGISTRY,
        downside_threshold_bp: int | None = None,
    ) -> None:
        self.label_registry = label_registry
        threshold = (
            label_registry.downside_threshold_bp
            if downside_threshold_bp is None
            else downside_threshold_bp
        )
        if threshold != label_registry.downside_threshold_bp:
            raise ValueError("downside threshold must match the frozen label registry")
        self.downside_threshold_bp = threshold
        horizons = {spec.horizon_trading_days for spec in label_registry.specs}
        if horizons != {20}:
            raise ValueError("historical label builder requires a single 20-day horizon")

    def build(
        self,
        *,
        feature_rows: tuple[HistoricalFeatureRow, ...],
        prices: tuple[HistoricalPriceObservation, ...],
        market: tuple[HistoricalIndexObservation, ...],
        label_as_of: str,
        corporate_action_by_row: Mapping[
            tuple[str, str], CorporateActionLabelEligibility
        ],
        mode: Literal["strict", "research"],
    ) -> HistoricalLabelBuildResult:
        if mode not in {"strict", "research"}:
            raise ValueError("mode must be strict or research")
        as_of = date.fromisoformat(label_as_of[:10]).isoformat()
        market_by_date = {
            row.trading_date: row.close_value
            for row in market
            if row.index_name == "market" and row.trading_date <= as_of
        }
        price_by_symbol: dict[str, dict[str, Decimal | None]] = {}
        for row in prices:
            if row.trading_date <= as_of:
                price_by_symbol.setdefault(row.symbol, {})[row.trading_date] = row.close_price
        diagnostics: dict[str, int] = {}
        blockers: set[str] = set()
        candidates: list[_Candidate] = []
        for feature in sorted(feature_rows, key=lambda row: (row.decision_date, row.symbol)):
            calendar = sorted(
                trading_date
                for trading_date, close in market_by_date.items()
                if trading_date >= feature.feature_as_of_date and close is not None
            )
            if not calendar or calendar[0] != feature.feature_as_of_date:
                _increment(diagnostics, "market_cutoff_missing")
                continue
            if len(calendar) <= 20:
                _increment(diagnostics, "immature_label_window")
                continue
            window_dates = calendar[:21]
            eligibility = corporate_action_by_row.get(
                (feature.symbol, feature.decision_date)
            )
            if eligibility is not None and (
                eligibility.label_start_date != feature.feature_as_of_date
                or eligibility.label_end_date != window_dates[-1]
            ):
                _increment(diagnostics, "corporate_action_gate_window_mismatch")
                continue
            if (eligibility is None or not eligibility.eligible) and mode == "strict":
                _increment(diagnostics, "corporate_action_coverage_blocked")
                continue
            quality: Literal["clean", "degraded"] = (
                "clean" if eligibility is not None and eligibility.eligible else "degraded"
            )
            if quality == "degraded":
                blockers.update(
                    eligibility.reasons
                    if eligibility is not None and eligibility.reasons
                    else ("corporate_action_coverage_missing",)
                )
            symbol_prices = price_by_symbol.get(feature.symbol, {})
            stock_window = [symbol_prices.get(trading_date) for trading_date in window_dates]
            market_window = [market_by_date[trading_date] for trading_date in window_dates]
            if any(value is None for value in stock_window):
                _increment(diagnostics, "price_gap_in_label_window")
                continue
            if any(value is None for value in market_window):
                _increment(diagnostics, "market_gap_in_label_window")
                continue
            stock_values = [value for value in stock_window if value is not None]
            market_values = [value for value in market_window if value is not None]
            if stock_values[0] == 0 or market_values[0] == 0:
                _increment(diagnostics, "zero_start_value")
                continue
            stock_return = _return_bp(stock_values[0], stock_values[-1])
            market_return = _return_bp(market_values[0], market_values[-1])
            relative_return = stock_return - market_return
            path_returns = tuple(_return_bp(stock_values[0], value) for value in stock_values[1:])
            candidates.append(
                _Candidate(
                    symbol=feature.symbol,
                    decision_date=feature.decision_date,
                    horizon_end_date=window_dates[-1],
                    relative_return_bp=relative_return,
                    maximum_adverse_excursion_bp=min(0, *path_returns),
                    downside_flag=int(relative_return <= self.downside_threshold_bp),
                    quality=quality,
                )
            )
        labels = self._materialize(candidates)
        degraded = any(candidate.quality == "degraded" for candidate in candidates)
        coverage = (
            "research_only_degraded"
            if degraded
            else "clean_official_or_observed"
            if candidates
            else "no_accepted_label_windows"
        )
        return HistoricalLabelBuildResult(
            labels=labels,
            accepted_diagnostics={"accepted_label_windows": len(candidates)} if candidates else {},
            excluded_diagnostics=diagnostics,
            corporate_action_coverage=coverage,
            formal_oos_allowed=bool(candidates) and not degraded,
            blockers=tuple(sorted(blockers)),
        )

    def _materialize(self, candidates: list[_Candidate]) -> tuple[HistoricalLabelRow, ...]:
        top_symbols: set[tuple[str, str]] = set()
        by_decision: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            by_decision.setdefault(candidate.decision_date, []).append(candidate)
        for decision_date, group in by_decision.items():
            ranked = sorted(group, key=lambda item: (-item.relative_return_bp, item.symbol))
            top_count = max(1, (len(ranked) + 4) // 5)
            top_symbols.update((decision_date, item.symbol) for item in ranked[:top_count])
        result: list[HistoricalLabelRow] = []
        for candidate in sorted(candidates, key=lambda item: (item.decision_date, item.symbol)):
            values = {
                "relative_return_20d_bp": candidate.relative_return_bp,
                "maximum_adverse_excursion_20d_bp": candidate.maximum_adverse_excursion_bp,
                "downside_20d_flag": candidate.downside_flag,
                "cross_sectional_top_quintile_20d_flag": int(
                    (candidate.decision_date, candidate.symbol) in top_symbols
                ),
            }
            for spec in self.label_registry.specs:
                result.append(
                    HistoricalLabelRow(
                        symbol=candidate.symbol,
                        decision_date=candidate.decision_date,
                        label_id=spec.label_id,
                        value=values[spec.label_id],
                        horizon_end_date=candidate.horizon_end_date,
                        available_date=candidate.horizon_end_date,
                        maturity_status="ready",
                        quality=candidate.quality,
                    )
                )
        return tuple(result)


def _return_bp(start: Decimal, end: Decimal) -> int:
    return int(((end / start - 1) * Decimal(10_000)).quantize(
        Decimal(1), rounding=ROUND_HALF_EVEN
    ))


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1
