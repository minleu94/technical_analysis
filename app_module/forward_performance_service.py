from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from uuid import uuid4

from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEvent,
    EvidenceEventType,
    EvidenceOutcome,
    EvidenceOutcomeStatus,
)
from app_module.evidence_event_repository import EvidenceEventRepository


@dataclass(frozen=True)
class ForwardOutcomeSummary:
    events_scanned: int = 0
    events_ready: int = 0
    outcomes_created: int = 0
    outcomes_updated: int = 0
    pending_insufficient_future_data: int = 0
    missing_event_price: int = 0
    missing_outcome_price: int = 0
    missing_benchmark: int = 0
    missing_industry_benchmark: int = 0
    warnings_count: int = 0
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ForwardPerformanceService:
    """Calculate close-to-close forward research outcomes for evidence events."""

    def __init__(
        self,
        config: Any,
        repository: EvidenceEventRepository | None = None,
    ) -> None:
        self.config = config
        self.repository = repository or EvidenceEventRepository(config)
        self.db_path = Path(config.db_file)

    def calculate(
        self,
        *,
        windows: Iterable[int] = (5, 10, 20, 60),
        dry_run: bool = True,
        decision_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        event_type: EvidenceEventType | str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> ForwardOutcomeSummary:
        events = self.repository.list_events(
            symbol=symbol,
            event_type=event_type,
            decision_date=decision_date,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        counters = {
            "events_scanned": len(events),
            "events_ready": 0,
            "outcomes_created": 0,
            "outcomes_updated": 0,
            "pending_insufficient_future_data": 0,
            "missing_event_price": 0,
            "missing_outcome_price": 0,
            "missing_benchmark": 0,
            "missing_industry_benchmark": 0,
            "warnings_count": 0,
        }

        for event in events:
            if not event.symbol or event.symbol.upper() == "MARKET":
                continue
            counters["events_ready"] += 1
            for window in tuple(int(item) for item in windows):
                existing = self.repository.get_outcome(event.event_id, window)
                outcome = self._build_outcome(event, window)
                counters["warnings_count"] += len(outcome.warnings)
                if outcome.outcome_status == EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA:
                    counters["pending_insufficient_future_data"] += 1
                if outcome.outcome_status == EvidenceOutcomeStatus.MISSING_PRICE:
                    counters["missing_event_price"] += 1
                if "missing_outcome_price" in outcome.warnings:
                    counters["missing_outcome_price"] += 1
                if "missing_benchmark" in outcome.warnings:
                    counters["missing_benchmark"] += 1
                if "missing_industry_benchmark" in outcome.warnings:
                    counters["missing_industry_benchmark"] += 1
                if existing is None:
                    counters["outcomes_created"] += 1
                else:
                    counters["outcomes_updated"] += 1
                if not dry_run:
                    self.repository.upsert_outcome(outcome)

        return ForwardOutcomeSummary(dry_run=dry_run, **counters)

    def _build_outcome(self, event: EvidenceEvent, window_days: int) -> EvidenceOutcome:
        warnings: list[str] = []
        event_price = self._find_event_price(str(event.symbol), event.event_date)
        if event_price is None:
            return EvidenceOutcome(
                outcome_id=f"out_{uuid4().hex}",
                event_id=event.event_id,
                window_days=window_days,
                outcome_status=EvidenceOutcomeStatus.MISSING_PRICE,
                data_quality=EvidenceDataQuality.MISSING,
                warnings=("missing_event_price",),
                metadata={"return_basis": "close_to_close_event_date"},
            )

        event_price_date, event_close = event_price
        outcome_price = self._find_outcome_price(str(event.symbol), event_price_date, window_days)
        if outcome_price is None:
            return EvidenceOutcome(
                outcome_id=f"out_{uuid4().hex}",
                event_id=event.event_id,
                window_days=window_days,
                event_price_date=event_price_date,
                event_close=str(event_close),
                outcome_status=EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA,
                data_quality=EvidenceDataQuality.MISSING,
                warnings=("insufficient_future_data",),
                metadata={"return_basis": "close_to_close_event_date"},
            )

        outcome_price_date, outcome_close = outcome_price
        forward_return_bp = self._return_bp(outcome_close, event_close)
        benchmark_return_bp = self._index_return_bp(
            "market_indices",
            event.benchmark_id,
            event_price_date,
            outcome_price_date,
        )
        if benchmark_return_bp is None:
            warnings.append("missing_benchmark")
        benchmark_excess_bp = (
            None if benchmark_return_bp is None else forward_return_bp - benchmark_return_bp
        )

        industry_name = event.industry_benchmark_id or event.sector
        industry_return_bp = self._index_return_bp(
            "industry_indices",
            industry_name,
            event_price_date,
            outcome_price_date,
        )
        if industry_return_bp is None:
            warnings.append("missing_industry_benchmark")
        industry_excess_bp = None if industry_return_bp is None else forward_return_bp - industry_return_bp

        quality = EvidenceDataQuality.OBSERVED if not warnings else EvidenceDataQuality.DEGRADED
        return EvidenceOutcome(
            outcome_id=f"out_{uuid4().hex}",
            event_id=event.event_id,
            window_days=window_days,
            event_price_date=event_price_date,
            event_close=str(event_close),
            outcome_price_date=outcome_price_date,
            outcome_close=str(outcome_close),
            forward_return_bp=forward_return_bp,
            benchmark_return_bp=benchmark_return_bp,
            benchmark_excess_bp=benchmark_excess_bp,
            industry_return_bp=industry_return_bp,
            industry_excess_bp=industry_excess_bp,
            outcome_status=EvidenceOutcomeStatus.READY,
            data_quality=quality,
            warnings=tuple(warnings),
            data_as_of_date=outcome_price_date,
            metadata={"return_basis": "close_to_close_event_date"},
        )

    def _find_event_price(self, symbol: str, event_date: str) -> tuple[str, Decimal] | None:
        target = self._date_key(event_date)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT 日期, 收盤價
                FROM daily_prices
                WHERE 證券代號 = ?
                  AND REPLACE(REPLACE(日期, '-', ''), '/', '') >= ?
                  AND 收盤價 IS NOT NULL
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') ASC
                LIMIT 1
                """,
                (symbol, target),
            ).fetchone()
        if row is None:
            return None
        close_value = self._to_decimal(row[1])
        if close_value is None:
            return None
        return (self._date_iso(row[0]), close_value)

    def _find_outcome_price(
        self,
        symbol: str,
        event_price_date: str,
        window_days: int,
    ) -> tuple[str, Decimal] | None:
        target = self._date_key(event_price_date)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT 日期, 收盤價
                FROM daily_prices
                WHERE 證券代號 = ?
                  AND REPLACE(REPLACE(日期, '-', ''), '/', '') > ?
                  AND 收盤價 IS NOT NULL
                ORDER BY REPLACE(REPLACE(日期, '-', ''), '/', '') ASC
                LIMIT ?
                """,
                (symbol, target, int(window_days)),
            ).fetchall()
        if len(rows) < window_days:
            return None
        row = rows[window_days - 1]
        close_value = self._to_decimal(row[1])
        if close_value is None:
            return None
        return (self._date_iso(row[0]), close_value)

    def _index_return_bp(
        self,
        table_name: str,
        index_name: str | None,
        event_price_date: str,
        outcome_price_date: str,
    ) -> int | None:
        if not index_name:
            return None
        column = "收盤指數"
        with sqlite3.connect(self.db_path) as conn:
            start = conn.execute(
                f"""
                SELECT {column}
                FROM {table_name}
                WHERE 指數名稱 = ?
                  AND REPLACE(REPLACE(日期, '-', ''), '/', '') = ?
                """,
                (index_name, self._date_key(event_price_date)),
            ).fetchone()
            end = conn.execute(
                f"""
                SELECT {column}
                FROM {table_name}
                WHERE 指數名稱 = ?
                  AND REPLACE(REPLACE(日期, '-', ''), '/', '') = ?
                """,
                (index_name, self._date_key(outcome_price_date)),
            ).fetchone()
        if start is None or end is None:
            return None
        start_value = self._to_decimal(start[0])
        end_value = self._to_decimal(end[0])
        if start_value is None or end_value is None or start_value <= 0:
            return None
        return self._return_bp(end_value, start_value)

    @staticmethod
    def _return_bp(current: Decimal, base: Decimal) -> int:
        value = ((current - base) / base) * Decimal("10000")
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _date_key(value: Any) -> str:
        return str(value).strip().replace("-", "").replace("/", "")

    @classmethod
    def _date_iso(cls, value: Any) -> str:
        key = cls._date_key(value)
        if len(key) == 8 and key.isdigit():
            return f"{key[:4]}-{key[4:6]}-{key[6:]}"
        return str(value)
