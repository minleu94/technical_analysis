"""Broker Flow dashboard 的單次聚合與 batch query application service。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Mapping, Protocol

from app_module.broker_flow_dashboard_dtos import (
    BrokerFlowBranchTrackerSnapshot,
    BrokerFlowDashboardQuery,
    BrokerFlowDashboardSnapshot,
    BrokerFlowStockDetailSnapshot,
)
from app_module.broker_flow_sqlite_read_repository import BrokerFlowReadSnapshot
from app_module.dtos.smart_money_semantic_dtos import SmartMoneySemanticSummary
from decision_module.flow_contracts import (
    BranchFlowAggregation,
    BrokerFlowEvent,
    FlowSignalDTO,
    SmartMoneySummaryDTO,
    StockFlowAggregation,
)
from decision_module.flow_signal_engine import FlowSignalEngine


class BrokerFlowDashboardRepository(Protocol):
    def load_dashboard_source(
        self, query: BrokerFlowDashboardQuery
    ) -> BrokerFlowReadSnapshot: ...

    def load_stock_source(
        self, stock_code: str, query: BrokerFlowDashboardQuery
    ) -> BrokerFlowReadSnapshot: ...

    def load_branch_source(
        self, branch_system_key: str, query: BrokerFlowDashboardQuery, *, limit: int
    ) -> BrokerFlowReadSnapshot: ...


class BrokerFlowBatchSemanticPort(Protocol):
    def build_batch_semantics(
        self,
        stock_codes: tuple[str, ...],
        decision_date: date,
    ) -> Mapping[str, SmartMoneySemanticSummary]: ...


class BrokerFlowDashboardQueryService:
    def __init__(
        self,
        repository: BrokerFlowDashboardRepository,
        *,
        semantic_port: BrokerFlowBatchSemanticPort | None = None,
        signal_engine: FlowSignalEngine | None = None,
    ) -> None:
        self.repository = repository
        self.semantic_port = semantic_port
        self.signal_engine = signal_engine or FlowSignalEngine()
        self._dashboard_cache: dict[tuple[object, ...], BrokerFlowDashboardSnapshot] = {}

    def load_dashboard_snapshot(
        self, query: BrokerFlowDashboardQuery
    ) -> BrokerFlowDashboardSnapshot:
        version_getter = getattr(self.repository, "source_cache_key", None)
        source_version = version_getter() if callable(version_getter) else None
        cache_key = (
            source_version,
            query.requested_as_of_date,
            query.period,
            query.scope,
            query.limit_per_side,
        )
        if source_version is not None and cache_key in self._dashboard_cache:
            return self._dashboard_cache[cache_key]
        source = self.repository.load_dashboard_source(query)
        if not source.events or not source.selected_trading_dates:
            snapshot = BrokerFlowDashboardSnapshot(
                as_of_date=query.requested_as_of_date,
                period=query.period,
                top_signals=(),
                bottom_signals=(),
                summary=SmartMoneySummaryDTO(),
                semantics_by_code={},
                tracked_branches=source.tracked_branches,
                quality=source.quality,
                warnings=source.warnings,
                source_fingerprint=source.source_fingerprint,
                selected_trading_dates=source.selected_trading_dates,
                query_counts={"repository": source.query_count, "semantic_batch": 0},
            )
            self._store_dashboard_cache(cache_key, source_version, snapshot)
            return snapshot

        aggregations = self._aggregate_market(source.events)
        all_signals = self.signal_engine.generate_signals(list(aggregations.values()))
        top_signals, bottom_signals = self._select_signals(all_signals, query)
        selected_codes = tuple(
            dict.fromkeys(
                signal.stock_code for signal in (*top_signals, *bottom_signals)
            )
        )
        actual_as_of = source.selected_trading_dates[-1]
        if self.semantic_port is None or not selected_codes:
            semantics: Mapping[str, SmartMoneySemanticSummary] = {}
            semantic_query_count = 0
        else:
            semantics = self.semantic_port.build_batch_semantics(
                selected_codes,
                actual_as_of,
            )
            semantic_query_count = 1
        semantic_warnings = tuple(
            warning
            for summary in semantics.values()
            for warning in summary.warnings
        )
        warnings = tuple(dict.fromkeys((*source.warnings, *semantic_warnings)))
        quality = "degraded" if warnings else source.quality
        snapshot = BrokerFlowDashboardSnapshot(
            as_of_date=actual_as_of,
            period=query.period,
            top_signals=top_signals,
            bottom_signals=bottom_signals,
            summary=self._build_market_summary(all_signals),
            semantics_by_code=semantics,
            tracked_branches=source.tracked_branches,
            quality=quality,
            warnings=warnings,
            source_fingerprint=source.source_fingerprint,
            selected_trading_dates=source.selected_trading_dates,
            query_counts={
                "repository": source.query_count,
                "semantic_batch": semantic_query_count,
            },
        )
        self._store_dashboard_cache(cache_key, source_version, snapshot)
        return snapshot

    def _store_dashboard_cache(
        self,
        cache_key: tuple[object, ...],
        source_version: object,
        snapshot: BrokerFlowDashboardSnapshot,
    ) -> None:
        if source_version is None:
            return
        self._dashboard_cache[cache_key] = snapshot
        while len(self._dashboard_cache) > 8:
            self._dashboard_cache.pop(next(iter(self._dashboard_cache)))

    def load_stock_branch_detail(
        self, stock_code: str, query: BrokerFlowDashboardQuery
    ) -> BrokerFlowStockDetailSnapshot:
        source = self.repository.load_stock_source(str(stock_code), query)
        rows = self._aggregate_branches(source.events, group_by_branch=True)
        return BrokerFlowStockDetailSnapshot(
            as_of_date=source.selected_trading_dates[-1] if source.selected_trading_dates else query.requested_as_of_date,
            period=query.period,
            stock_code=str(stock_code),
            rows=rows,
            quality=source.quality,
            warnings=source.warnings,
            source_fingerprint=source.source_fingerprint,
            query_count=source.query_count,
        )

    def load_branch_tracker(
        self, branch_system_key: str, query: BrokerFlowDashboardQuery, *, limit: int = 5000
    ) -> BrokerFlowBranchTrackerSnapshot:
        source = self.repository.load_branch_source(str(branch_system_key), query, limit=limit)
        rows = self._aggregate_branches(source.events, group_by_branch=False)
        return BrokerFlowBranchTrackerSnapshot(
            as_of_date=source.selected_trading_dates[-1] if source.selected_trading_dates else query.requested_as_of_date,
            period=query.period,
            branch_system_key=str(branch_system_key),
            rows=rows,
            quality=source.quality,
            warnings=source.warnings,
            source_fingerprint=source.source_fingerprint,
            query_count=source.query_count,
        )

    @staticmethod
    def _aggregate_branches(
        events: tuple[BrokerFlowEvent, ...], *, group_by_branch: bool
    ) -> tuple[BranchFlowAggregation, ...]:
        aggregations: dict[str, BranchFlowAggregation] = {}
        daily_net: dict[str, dict[str, int]] = {}
        for event in events:
            key = event.branch_system_key if group_by_branch else event.stock_code
            aggregation = aggregations.setdefault(
                key,
                BranchFlowAggregation(
                    branch_system_key=event.branch_system_key,
                    branch_display_name=event.branch_display_name,
                    stock_code=event.stock_code,
                    stock_name=event.stock_name,
                ),
            )
            aggregation.events.append(event)
            if event.lots_quality in {"observed", "degraded"}:
                aggregation.observed_event_count += 1
                aggregation.usable_event_count += 1
            elif event.lots_quality == "estimated":
                aggregation.estimated_event_count += 1
                aggregation.usable_event_count += 1
            else:
                aggregation.unavailable_event_count += 1
            if event.buy_qty is not None:
                aggregation.total_buy_qty += event.buy_qty
            if event.sell_qty is not None:
                aggregation.total_sell_qty += event.sell_qty
            if event.net_qty is not None:
                aggregation.total_net_qty += event.net_qty
                daily = daily_net.setdefault(key, {})
                daily[event.date] = daily.get(event.date, 0) + event.net_qty

        for key, aggregation in aggregations.items():
            total = len(aggregation.events)
            aggregation.lots_coverage_ratio = (
                Decimal(aggregation.usable_event_count) / Decimal(total)
                if total else Decimal("1")
            )
            aggregation.lots_available = aggregation.usable_event_count > 0
            aggregation.has_estimated_lots = aggregation.estimated_event_count > 0
            dates = sorted(daily_net.get(key, {}))[-5:]
            aggregation.sparkline_data = [daily_net[key][item] for item in dates]
            aggregation.sparkline_details = [(item, daily_net[key][item]) for item in dates]
        return tuple(sorted(aggregations.values(), key=lambda item: item.total_net_qty, reverse=True))

    @staticmethod
    def _aggregate_market(
        events: tuple[BrokerFlowEvent, ...]
    ) -> dict[str, StockFlowAggregation]:
        aggregations: dict[str, StockFlowAggregation] = {}
        for event in events:
            aggregation = aggregations.setdefault(
                event.stock_code,
                StockFlowAggregation(
                    stock_code=event.stock_code,
                    stock_name=event.stock_name,
                ),
            )
            aggregation.events.append(event)
            if event.lots_quality in {"observed", "degraded"}:
                aggregation.observed_event_count += 1
                aggregation.usable_event_count += 1
            elif event.lots_quality == "estimated":
                aggregation.estimated_event_count += 1
                aggregation.usable_event_count += 1
            else:
                aggregation.unavailable_event_count += 1
            if event.buy_qty is not None:
                aggregation.total_buy_qty += event.buy_qty
            if event.sell_qty is not None:
                aggregation.total_sell_qty += event.sell_qty
            if event.net_qty is not None:
                aggregation.total_net_qty += event.net_qty
                if event.net_qty > 0 and event.branch_display_name not in aggregation.buying_branches:
                    aggregation.buying_branches.append(event.branch_display_name)
                elif event.net_qty < 0 and event.branch_display_name not in aggregation.selling_branches:
                    aggregation.selling_branches.append(event.branch_display_name)

        for aggregation in aggregations.values():
            total = len(aggregation.events)
            aggregation.lots_coverage_ratio = (
                Decimal(aggregation.usable_event_count) / Decimal(total)
                if total
                else Decimal("1")
            )
            aggregation.lots_available = aggregation.usable_event_count > 0
            aggregation.has_estimated_lots = aggregation.estimated_event_count > 0
        return aggregations

    @staticmethod
    def _select_signals(
        signals: list[FlowSignalDTO],
        query: BrokerFlowDashboardQuery,
    ) -> tuple[tuple[FlowSignalDTO, ...], tuple[FlowSignalDTO, ...]]:
        positive = [signal for signal in signals if signal.aggregation.total_net_qty > 0]
        negative = [signal for signal in signals if signal.aggregation.total_net_qty < 0]
        top = sorted(positive, key=lambda item: item.smart_money_score, reverse=True)
        bottom = sorted(negative, key=lambda item: item.aggregation.total_net_qty)
        if query.scope not in {"all"}:
            top = top[: query.limit_per_side]
            bottom = bottom[: query.limit_per_side]
        if query.scope == "top50":
            bottom = []
        elif query.scope == "bottom50":
            top = []
        return tuple(top), tuple(bottom)

    @staticmethod
    def _build_market_summary(signals: list[FlowSignalDTO]) -> SmartMoneySummaryDTO:
        summary = SmartMoneySummaryDTO()
        for signal in signals:
            net_qty = signal.aggregation.total_net_qty
            if net_qty > 0:
                summary.bullish_stock_count += 1
                if signal.smart_money_score >= 80 and net_qty >= 500:
                    summary.abnormal_signal_count += 1
            elif net_qty < 0:
                summary.bearish_stock_count += 1
                if net_qty <= -500:
                    summary.abnormal_signal_count += 1

        total = summary.bullish_stock_count + summary.bearish_stock_count
        if total:
            heat = Decimal(summary.bullish_stock_count) * Decimal(100) / Decimal(total)
            summary.market_heat_score = float(heat)  # numeric-boundary: DTO/UI display
        if summary.market_heat_score > 60:
            summary.market_regime = "Bullish Flow"
        elif summary.market_heat_score < 40:
            summary.market_regime = "Bearish Flow"
        else:
            summary.market_regime = "Neutral"
        return summary


__all__ = [
    "BrokerFlowBatchSemanticPort",
    "BrokerFlowDashboardQueryService",
    "BrokerFlowDashboardRepository",
]
