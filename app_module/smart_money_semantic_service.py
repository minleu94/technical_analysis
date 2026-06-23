from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable, Protocol

from app_module.dtos.broker_flow_dtos import BrokerFlowEvent
from app_module.dtos.smart_money_semantic_dtos import (
    SmartMoneyDashboardSummary,
    SmartMoneySemanticSummary,
    SmartMoneyWindowStats,
)


class BrokerFlowEventProvider(Protocol):
    def get_events(self, force_reload: bool = False) -> list[BrokerFlowEvent]: ...


class SmartMoneyPriceProvider(Protocol):
    def load_recent_prices(
        self, stock_code: str, decision_date: date, limit: int
    ) -> list[tuple[date, Decimal]]: ...


class SQLiteSmartMoneyPriceProvider:
    """Read-only recent close-price provider for Smart Money semantic diagnostics."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def load_recent_prices(
        self, stock_code: str, decision_date: date, limit: int
    ) -> list[tuple[date, Decimal]]:
        if limit <= 0 or not self.db_path.exists():
            return []
        target_key = decision_date.strftime("%Y%m%d")
        try:
            db_uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(db_uri, uri=True) as conn:
                conn.execute("PRAGMA query_only=ON")
                rows = conn.execute(
                    """
                    SELECT 日期, 收盤價
                    FROM daily_prices
                    WHERE 證券代號 = ?
                      AND REPLACE(REPLACE(日期, '-', ''), '/', '') <= ?
                      AND 收盤價 IS NOT NULL
                    ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') DESC
                    LIMIT ?
                    """,
                    (str(stock_code), target_key, int(limit)),
                ).fetchall()
        except sqlite3.Error:
            return []

        prices: list[tuple[date, Decimal]] = []
        for raw_date, raw_price in rows:
            try:
                price_date = _parse_event_date(raw_date)
                price = Decimal(str(raw_price).replace(",", ""))
            except (InvalidOperation, ValueError):
                continue
            if price.is_finite() and price > 0:
                prices.append((price_date, price))
        return prices


def _parse_event_date(raw: object) -> date:
    text = str(raw).strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


def _bp(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    value = (Decimal(numerator) * Decimal(10000) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(value)


def _decimal_bp(numerator: Decimal, denominator: Decimal) -> int | None:
    if denominator <= 0:
        return None
    value = (numerator * Decimal(10000) / denominator).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(value)


class SmartMoneySemanticService:
    def __init__(
        self,
        broker_flow_provider: BrokerFlowEventProvider,
        *,
        price_provider: SmartMoneyPriceProvider | None = None,
    ) -> None:
        self.broker_flow_provider = broker_flow_provider
        self.price_provider = price_provider

    def build_stock_semantics(
        self, stock_code: str, decision_date: date
    ) -> SmartMoneySemanticSummary:
        events = self._events_for_stock(stock_code, decision_date)
        stock_name = next((event.stock_name for _, event in events if event.stock_name), stock_code)
        w5 = self._window_stats(events, 5, top_n=3)
        w20 = self._window_stats(events, 20, top_n=5)
        w60 = self._window_stats(events, 60, top_n=5)
        price_position_bp, distance_to_high_bp = self._price_position(stock_code, decision_date)
        primary_state, dominant_side, flags = self._classify(
            w5, w20, w60, price_position_bp, distance_to_high_bp
        )
        warnings = self._quality_warnings(w5, w20, w60)
        quality = "degraded" if warnings else "observed"
        confidence_bp = min(w5.usable_coverage_bp, w20.usable_coverage_bp, w60.usable_coverage_bp)
        status = self._status(primary_state, flags, confidence_bp)
        evidence_lines = self._evidence_lines(
            primary_state, flags, w5, w20, w60, price_position_bp, distance_to_high_bp
        )
        source_quality_counts = {
            "observed": w60.observed_count,
            "estimated": w60.estimated_count,
            "unavailable": w60.unavailable_count,
            "usable": w60.observed_count + w60.estimated_count,
            "total": w60.observed_count + w60.estimated_count + w60.unavailable_count,
        }
        return SmartMoneySemanticSummary(
            stock_code=str(stock_code),
            stock_name=stock_name,
            decision_date=decision_date,
            as_of_date=decision_date,
            net_qty=w5.net_qty,
            dominant_side=dominant_side,
            primary_state=primary_state,
            semantic_flags=tuple(flags),
            confidence_bp=confidence_bp,
            status=status,
            quality=quality,
            warnings=tuple(warnings),
            evidence_lines=tuple(evidence_lines),
            source_quality_counts=source_quality_counts,
            window_5=w5,
            window_20=w20,
            window_60=w60,
            price_position_bp=price_position_bp,
            distance_to_60d_high_bp=distance_to_high_bp,
        )

    def build_dashboard_summary(
        self, decision_date: date, stock_codes: tuple[str, ...] = ()
    ) -> SmartMoneyDashboardSummary:
        codes = stock_codes or tuple(
            sorted(
                {
                    event.stock_code
                    for _, event in self._events_for_stock(None, decision_date)
                    if event.stock_code
                }
            )
        )
        summaries = tuple(self.build_stock_semantics(code, decision_date) for code in codes)
        priority = tuple(
            item
            for item in summaries
            if item.primary_state in {"初轉買", "買超延續"}
        )[:10]
        risk = tuple(
            item
            for item in summaries
            if item.primary_state in {"初轉賣", "賣超延續"}
            or "高檔出貨疑慮" in item.semantic_flags
        )[:10]
        warnings = tuple(warning for item in summaries for warning in item.warnings)
        quality = "degraded" if warnings else "observed"
        return SmartMoneyDashboardSummary(
            decision_date=decision_date,
            as_of_date=decision_date,
            priority_summaries=priority,
            risk_summaries=risk,
            quality=quality,
            warnings=warnings,
        )

    def _events_for_stock(
        self, stock_code: str | None, decision_date: date
    ) -> list[tuple[date, BrokerFlowEvent]]:
        selected: list[tuple[date, BrokerFlowEvent]] = []
        for event in self.broker_flow_provider.get_events(force_reload=False):
            if stock_code is not None and str(event.stock_code) != str(stock_code):
                continue
            try:
                event_date = _parse_event_date(event.date)
            except ValueError:
                continue
            if event_date <= decision_date:
                selected.append((event_date, event))
        selected.sort(key=lambda item: item[0], reverse=True)
        return selected

    def _window_stats(
        self,
        events: list[tuple[date, BrokerFlowEvent]],
        window_days: int,
        *,
        top_n: int,
    ) -> SmartMoneyWindowStats:
        window_events = self._select_recent_event_dates(events, window_days)
        observed_count = 0
        estimated_count = 0
        unavailable_count = 0
        buy_qty = 0
        sell_qty = 0
        branch_positive: defaultdict[str, int] = defaultdict(int)
        branch_negative: defaultdict[str, int] = defaultdict(int)
        daily_net: defaultdict[date, int] = defaultdict(int)

        for event_date, event in window_events:
            net_qty = event.net_qty
            if event.lots_quality == "observed" and net_qty is not None:
                observed_count += 1
            elif event.lots_quality == "estimated" and net_qty is not None:
                estimated_count += 1
            else:
                unavailable_count += 1
                continue

            daily_net[event_date] += net_qty
            if net_qty > 0:
                buy_qty += net_qty
                branch_positive[event.branch_display_name] += net_qty
            elif net_qty < 0:
                sell_qty += abs(net_qty)
                branch_negative[event.branch_display_name] += abs(net_qty)

        net_total = buy_qty - sell_qty
        if net_total > 0:
            direction = "buy"
            concentration_bp, group_concentration_bp = self._concentration_bp(branch_positive, top_n)
        elif net_total < 0:
            direction = "sell"
            concentration_bp, group_concentration_bp = self._concentration_bp(branch_negative, top_n)
        else:
            direction = "neutral"
            concentration_bp = None
            group_concentration_bp = None

        continuous_buy_days, continuous_sell_days = self._continuous_days(daily_net)
        total_count = observed_count + estimated_count + unavailable_count
        coverage_bp = _bp(observed_count + estimated_count, total_count)
        return SmartMoneyWindowStats(
            window_days=window_days,
            net_qty=net_total,
            buy_qty=buy_qty,
            sell_qty=sell_qty,
            direction=direction,
            continuous_buy_days=continuous_buy_days,
            continuous_sell_days=continuous_sell_days,
            top_n=top_n,
            top_concentration_bp=concentration_bp,
            observed_count=observed_count,
            estimated_count=estimated_count,
            unavailable_count=unavailable_count,
            usable_coverage_bp=coverage_bp if coverage_bp is not None else 0,
            top_group_concentration_bp=group_concentration_bp,
        )

    def _select_recent_event_dates(
        self, events: list[tuple[date, BrokerFlowEvent]], window_days: int
    ) -> list[tuple[date, BrokerFlowEvent]]:
        distinct_dates = sorted({event_date for event_date, _ in events}, reverse=True)
        allowed_dates = set(distinct_dates[:window_days])
        return [(event_date, event) for event_date, event in events if event_date in allowed_dates]

    def _concentration_bp(
        self, branch_qty: defaultdict[str, int], top_n: int
    ) -> tuple[int | None, int | None]:
        values = sorted((qty for qty in branch_qty.values() if qty > 0), reverse=True)
        denominator = sum(values)
        if denominator <= 0:
            return None, None
        top_single_bp = _bp(values[0], denominator)
        top_group_bp = _bp(sum(values[:top_n]), denominator)
        return top_single_bp, top_group_bp

    def _continuous_days(self, daily_net: defaultdict[date, int]) -> tuple[int, int]:
        buy_days = 0
        sell_days = 0
        for event_date in sorted(daily_net.keys(), reverse=True):
            net_qty = daily_net[event_date]
            if net_qty > 0 and sell_days == 0:
                buy_days += 1
            elif net_qty < 0 and buy_days == 0:
                sell_days += 1
            else:
                break
        return buy_days, sell_days

    def _price_position(
        self, stock_code: str, decision_date: date
    ) -> tuple[int | None, int | None]:
        if self.price_provider is None:
            return None, None
        rows = self.price_provider.load_recent_prices(stock_code, decision_date, 60)
        normalized_rows: list[tuple[date, Decimal]] = []
        for raw_date, raw_price in rows:
            price_date = raw_date if isinstance(raw_date, date) else _parse_event_date(raw_date)
            if price_date > decision_date:
                continue
            try:
                price = Decimal(str(raw_price))
            except (InvalidOperation, ValueError):
                continue
            if price.is_finite() and price > 0:
                normalized_rows.append((price_date, price))

        if not normalized_rows:
            return None, None

        normalized_rows.sort(key=lambda item: item[0], reverse=True)
        prices = [price for _, price in normalized_rows[:60]]
        current = prices[0]
        high = max(prices)
        low = min(prices)
        position_bp: int | None
        if high == low:
            position_bp = 10000
        else:
            position_bp = _decimal_bp(current - low, high - low)
        distance_bp = _decimal_bp(high - current, high)
        return position_bp, distance_bp

    def _classify(
        self,
        w5: SmartMoneyWindowStats,
        w20: SmartMoneyWindowStats,
        w60: SmartMoneyWindowStats,
        price_position_bp: int | None,
        distance_to_high_bp: int | None,
    ) -> tuple[str, str, list[str]]:
        flags: list[str] = []
        prior_20_net = w20.net_qty - w5.net_qty
        if w5.net_qty > 0 and prior_20_net < 0:
            primary_state = "初轉買"
            dominant_side = "buy"
        elif w5.net_qty > 0:
            primary_state = "買超延續"
            dominant_side = "buy"
        elif w5.net_qty < 0 and prior_20_net > 0:
            primary_state = "初轉賣"
            dominant_side = "sell"
        elif w5.net_qty < 0:
            primary_state = "賣超延續"
            dominant_side = "sell"
        else:
            primary_state = "中性"
            dominant_side = "neutral"

        if self._has_concentration_risk(w5, w20):
            flags.append("分點集中異常")

        if (
            dominant_side == "sell"
            and price_position_bp is not None
            and distance_to_high_bp is not None
            and price_position_bp >= 8000
            and distance_to_high_bp <= 1000
        ):
            flags.append("高檔出貨疑慮")

        return primary_state, dominant_side, flags

    def _has_concentration_risk(
        self, w5: SmartMoneyWindowStats, w20: SmartMoneyWindowStats
    ) -> bool:
        if w5.direction == "neutral" or w5.direction != w20.direction:
            return False
        return any(
            concentration_bp is not None and concentration_bp >= 6000
            for concentration_bp in (w5.top_concentration_bp, w20.top_concentration_bp)
        )

    def _quality_warnings(
        self, *windows: SmartMoneyWindowStats
    ) -> list[str]:
        unavailable = max(window.unavailable_count for window in windows)
        estimated = max(window.estimated_count for window in windows)
        warnings: list[str] = []
        if unavailable > 0:
            warnings.append(
                f"quantity_unavailable_excluded:{unavailable}; concentration denominator excludes unavailable rows"
            )
        if estimated > 0:
            warnings.append(
                f"quantity_estimated_included:{estimated}; confidence reflects estimated quantity rows"
            )
        return warnings

    def _status(self, primary_state: str, flags: Iterable[str], confidence_bp: int) -> str:
        flag_set = set(flags)
        if "高檔出貨疑慮" in flag_set or primary_state in {"初轉賣", "賣超延續"}:
            return "risk"
        if "分點集中異常" in flag_set or confidence_bp < 8000:
            return "watch"
        if primary_state in {"初轉買", "買超延續"}:
            return "priority"
        return "neutral"

    def _evidence_lines(
        self,
        primary_state: str,
        flags: list[str],
        w5: SmartMoneyWindowStats,
        w20: SmartMoneyWindowStats,
        w60: SmartMoneyWindowStats,
        price_position_bp: int | None,
        distance_to_high_bp: int | None,
    ) -> list[str]:
        lines = [
            f"語意狀態：{primary_state}",
            f"5日淨量 {w5.net_qty:+,}；20日淨量 {w20.net_qty:+,}；60日淨量 {w60.net_qty:+,}",
            (
                f"5日 quantity concentration bp="
                f"{w5.top_concentration_bp if w5.top_concentration_bp is not None else 'N/A'}"
            ),
            (
                "資料品質 "
                f"observed={w60.observed_count} estimated={w60.estimated_count} "
                f"unavailable={w60.unavailable_count}"
            ),
        ]
        if price_position_bp is not None and distance_to_high_bp is not None:
            lines.append(
                f"近60日價格位置 {price_position_bp} bp；距高點 {distance_to_high_bp} bp"
            )
        lines.extend(flags)
        return lines
