"""唯讀重建 Paper Portfolio 週報的 evidence adapter。

這個 adapter 將已存在的 snapshot、Equal Weight benchmark 與 Paper Trade
Ledger 讀成 ``PaperPortfolioWeeklyReportService`` 所需的純資料物件。它不
建立 SQLite schema、不補值，也不把手動交易或 broker 成交轉成 paper
execution evidence。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from app_module.paper_equal_weight_benchmark_ledger import EqualWeightBenchmarkEntry
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
)
from app_module.paper_portfolio_time import paper_portfolio_today
from app_module.paper_portfolio_weekly_report import (
    PaperPortfolioWeeklyReport,
    PaperPortfolioWeeklyReportService,
    PaperTradeCostRecord,
)
from app_module.paper_trade_ledger import (
    PAPER_TRADE_LEDGER_SCHEMA_VERSION,
    PaperTradeFill,
)
from app_module.sqlite_read_only import ReadOnlySQLiteManager


PAPER_WEEKLY_EVIDENCE_SCHEMA_VERSION = "paper-portfolio-weekly-evidence.v1"
DEFAULT_PORTFOLIO_ID = "paper-main"
DEFAULT_BENCHMARK_ID = "paper-main-equal"
DEFAULT_BENCHMARK_LEDGER_FILENAME = "paper_equal_weight_benchmark.sqlite"
DEFAULT_COST_LEDGER_FILENAME = "paper_trade_ledger.sqlite"


@dataclass(frozen=True)
class PaperPortfolioWeeklyEvidenceDTO:
    """Paper weekly report 與其輸入完整性的唯讀 read model。"""

    generated_at: str
    status: str
    period_start: str | None
    period_end: str | None
    expected_trading_days: int
    portfolio_id: str
    benchmark_id: str
    state_db_path: str
    benchmark_db_path: str | None
    cost_ledger_db_path: str | None
    snapshot_count: int = 0
    benchmark_observation_count: int = 0
    cost_record_count: int = 0
    report: PaperPortfolioWeeklyReport | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    research_only: bool = True
    investment_effectiveness_claim: bool = False
    read_only: bool = True
    writes_allowed: bool = False
    broker_execution: bool = False
    auto_rebalance_allowed: bool = False

    def __post_init__(self) -> None:
        if self.status not in {
            "ready",
            "partial",
            "degraded",
            "not_configured",
            "not_computable",
        }:
            raise ValueError(f"unsupported weekly evidence status: {self.status}")
        if isinstance(self.expected_trading_days, bool) or self.expected_trading_days <= 0:
            raise ValueError("expected_trading_days must be positive")
        for field_name in (
            "snapshot_count",
            "benchmark_observation_count",
            "cost_record_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if (
            self.research_only is not True
            or self.investment_effectiveness_claim is not False
            or self.read_only is not True
            or self.writes_allowed is not False
            or self.broker_execution is not False
            or self.auto_rebalance_allowed is not False
        ):
            raise ValueError("weekly evidence safety boundary must remain fail-closed")

    @property
    def weekly_report_status(self) -> str:
        if self.report is None:
            return "not_computable"
        return "partial" if self.report.warnings or self.warnings else "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAPER_WEEKLY_EVIDENCE_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "status": self.status,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "expected_trading_days": self.expected_trading_days,
            "portfolio_id": self.portfolio_id,
            "benchmark_id": self.benchmark_id,
            "state_db_path": self.state_db_path,
            "benchmark_db_path": self.benchmark_db_path,
            "cost_ledger_db_path": self.cost_ledger_db_path,
            "snapshot_count": self.snapshot_count,
            "benchmark_observation_count": self.benchmark_observation_count,
            "cost_record_count": self.cost_record_count,
            "weekly_report_status": self.weekly_report_status,
            "report": _report_to_dict(self.report),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "research_only": self.research_only,
            "investment_effectiveness_claim": self.investment_effectiveness_claim,
            "read_only": self.read_only,
            "writes_allowed": self.writes_allowed,
            "broker_execution": self.broker_execution,
            "auto_rebalance_allowed": self.auto_rebalance_allowed,
        }


class PaperPortfolioWeeklyEvidenceService:
    """從既有 paper ledgers query-only 建立週報 evidence。"""

    def __init__(
        self,
        *,
        output_root: str | Path,
        state_db_path: str | Path | None = None,
        benchmark_db_path: str | Path | None = None,
        cost_ledger_db_path: str | Path | None = None,
        portfolio_id: str = DEFAULT_PORTFOLIO_ID,
        benchmark_id: str = DEFAULT_BENCHMARK_ID,
    ) -> None:
        self.output_root = Path(output_root)
        self.state_db_path = (
            Path(state_db_path)
            if state_db_path is not None
            else self.output_root / "paper_portfolio" / "paper_portfolio.sqlite"
        )
        configured_benchmark = benchmark_db_path
        if configured_benchmark is None:
            configured_benchmark = os.environ.get("PAPER_EQUAL_WEIGHT_BENCHMARK_PATH")
        self.benchmark_db_path = (
            Path(configured_benchmark)
            if configured_benchmark
            else self.output_root / "paper_portfolio" / DEFAULT_BENCHMARK_LEDGER_FILENAME
        )
        configured_cost_ledger = cost_ledger_db_path
        if configured_cost_ledger is None:
            configured_cost_ledger = os.environ.get("PAPER_TRADE_LEDGER_PATH")
        self.cost_ledger_db_path = (
            Path(configured_cost_ledger)
            if configured_cost_ledger is not None
            else self.output_root / "paper_portfolio" / DEFAULT_COST_LEDGER_FILENAME
        )
        self.portfolio_id = portfolio_id
        self.benchmark_id = benchmark_id
        self._report_service = PaperPortfolioWeeklyReportService()

    def build(
        self,
        *,
        period_start: str,
        period_end: str,
        expected_trading_days: int,
    ) -> PaperPortfolioWeeklyEvidenceDTO:
        start = _require_date(period_start, "period_start")
        end = _require_date(period_end, "period_end")
        if start > end:
            raise ValueError("period_start must not be after period_end")
        if isinstance(expected_trading_days, bool) or not isinstance(expected_trading_days, int):
            raise ValueError("expected_trading_days must be a positive integer")
        if expected_trading_days <= 0:
            raise ValueError("expected_trading_days must be a positive integer")

        start_text = start.isoformat()
        end_text = end.isoformat()
        blockers: list[str] = []
        warnings: list[str] = []
        diagnostics: list[str] = []
        today = paper_portfolio_today()
        if end > today:
            blockers.append("paper_weekly_report_future_period")
            diagnostics.append(
                f"paper_weekly_report_future_period:{end_text}:today={today.isoformat()}"
            )

        snapshots = self._read_snapshots(
            start_text,
            end_text,
            blockers=blockers,
            diagnostics=diagnostics,
        )
        benchmarks = self._read_benchmarks(
            start_text,
            end_text,
            blockers=blockers,
            diagnostics=diagnostics,
        )
        costs = self._read_costs(
            start_text,
            end_text,
            blockers=blockers,
            warnings=warnings,
            diagnostics=diagnostics,
        )

        if snapshots and snapshots[0].decision_date != start_text:
            blockers.append("paper_weekly_report_period_start_snapshot_missing")
        if snapshots and snapshots[-1].decision_date != end_text:
            blockers.append("paper_weekly_report_period_end_snapshot_missing")
        if benchmarks and benchmarks[0].decision_date != start_text:
            blockers.append("paper_weekly_report_period_start_benchmark_missing")
        if benchmarks and benchmarks[-1].decision_date != end_text:
            blockers.append("paper_weekly_report_period_end_benchmark_missing")
        if len(snapshots) < 2:
            blockers.append("paper_weekly_report_requires_two_snapshots")
        if len(benchmarks) < 2:
            blockers.append("paper_weekly_report_requires_two_benchmarks")
        if snapshots and any(item.total_value <= 0 for item in snapshots[:1]):
            blockers.append("paper_weekly_report_invalid_start_value")

        unique_blockers = tuple(sorted(set(blockers)))
        unique_warnings = tuple(sorted(set(warnings)))
        unique_diagnostics = tuple(dict.fromkeys(diagnostics))
        report: PaperPortfolioWeeklyReport | None = None
        if not unique_blockers:
            try:
                report = self._report_service.build(
                    portfolio_snapshots=snapshots,
                    benchmark_entries=benchmarks,
                    trade_costs=costs,
                    expected_trading_days=expected_trading_days,
                )
            except (TypeError, ValueError, ArithmeticError) as exc:
                blockers.append("paper_weekly_report_build_failed")
                diagnostics.append(f"paper_weekly_report_build_error:{type(exc).__name__}")
                unique_blockers = tuple(sorted(set(blockers)))
                unique_diagnostics = tuple(dict.fromkeys(diagnostics))
        if report is not None:
            unique_warnings = tuple(sorted(set((*unique_warnings, *report.warnings))))

        status = _status_for(
            snapshots=snapshots,
            benchmarks=benchmarks,
            blockers=unique_blockers,
            warnings=unique_warnings,
            report=report,
        )
        return PaperPortfolioWeeklyEvidenceDTO(
            generated_at=_utc_now_text(),
            status=status,
            period_start=start_text,
            period_end=end_text,
            expected_trading_days=expected_trading_days,
            portfolio_id=self.portfolio_id,
            benchmark_id=self.benchmark_id,
            state_db_path=str(self.state_db_path),
            benchmark_db_path=(str(self.benchmark_db_path) if self.benchmark_db_path else None),
            cost_ledger_db_path=(
                str(self.cost_ledger_db_path) if self.cost_ledger_db_path else None
            ),
            snapshot_count=len(snapshots),
            benchmark_observation_count=len(benchmarks),
            cost_record_count=len(costs),
            report=report,
            blockers=unique_blockers,
            warnings=unique_warnings,
            diagnostics=unique_diagnostics,
        )

    def build_latest(self, *, expected_trading_days: int = 5) -> PaperPortfolioWeeklyEvidenceDTO:
        """以最近 ``expected_trading_days`` 筆 snapshot 的邊界建立週報。

        UI 使用這個 helper 時仍會把實際 period 映射回 DTO；若 snapshot
        不足，會選取現有首尾日期並由 report 的 observed/expected 差異標示
        incomplete week，而不是假裝有完整交易週。
        """

        if isinstance(expected_trading_days, bool) or not isinstance(expected_trading_days, int):
            raise ValueError("expected_trading_days must be a positive integer")
        if expected_trading_days <= 0:
            raise ValueError("expected_trading_days must be a positive integer")
        dates, blockers, diagnostics = self._list_snapshot_dates()
        if not dates:
            return self._empty_result(
                status="not_configured" if not self.state_db_path.is_file() else "not_computable",
                expected_trading_days=expected_trading_days,
                blockers=tuple(blockers or ["paper_weekly_report_snapshot_dates_missing"]),
                diagnostics=tuple(diagnostics),
            )
        selected = dates[-expected_trading_days:]
        result = self.build(
            period_start=selected[0],
            period_end=selected[-1],
            expected_trading_days=expected_trading_days,
        )
        if blockers or diagnostics:
            return _with_extra_messages(result, blockers=blockers, diagnostics=diagnostics)
        return result

    def _list_snapshot_dates(self) -> tuple[list[str], list[str], list[str]]:
        blockers: list[str] = []
        diagnostics: list[str] = []
        if not self.state_db_path.is_file():
            blockers.append("paper_snapshot_db_missing")
            return [], blockers, diagnostics
        manager = ReadOnlySQLiteManager(self.state_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_portfolio_snapshots"):
                    blockers.append("paper_snapshot_table_missing")
                    return [], blockers, diagnostics
                rows = conn.execute(
                    """
                    SELECT decision_date
                    FROM paper_portfolio_snapshots
                    WHERE portfolio_id = ?
                    ORDER BY decision_date, snapshot_id
                    """,
                    (self.portfolio_id,),
                ).fetchall()
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            blockers.append("paper_snapshot_db_unavailable")
            diagnostics.append(f"paper_snapshot_db_error:{type(exc).__name__}")
            return [], blockers, diagnostics
        dates: list[str] = []
        for row in rows:
            try:
                dates.append(_require_date(row["decision_date"], "decision_date").isoformat())
            except (TypeError, ValueError) as exc:
                blockers.append("paper_snapshot_invalid_date")
                diagnostics.append(f"paper_snapshot_date_invalid:{type(exc).__name__}")
        today = paper_portfolio_today()
        future_dates = sorted({item for item in dates if date.fromisoformat(item) > today})
        if future_dates:
            blockers.append("paper_snapshot_future_dated")
            diagnostics.extend(
                f"paper_snapshot_future_date:{item}:today={today.isoformat()}"
                for item in future_dates
            )
        return sorted(set(dates)), blockers, diagnostics

    def _read_snapshots(
        self,
        period_start: str,
        period_end: str,
        *,
        blockers: list[str],
        diagnostics: list[str],
    ) -> tuple[PaperPortfolioSnapshot, ...]:
        if not self.state_db_path.is_file():
            blockers.append("paper_snapshot_db_missing")
            return ()
        manager = ReadOnlySQLiteManager(self.state_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_portfolio_snapshots"):
                    blockers.append("paper_snapshot_table_missing")
                    return ()
                if not _table_exists(conn, "paper_portfolio_positions"):
                    blockers.append("paper_snapshot_positions_table_missing")
                    return ()
                rows = conn.execute(
                    """
                    SELECT snapshot_id, portfolio_id, decision_date, source_result_id, cash, total_value
                    FROM paper_portfolio_snapshots
                    WHERE portfolio_id = ? AND decision_date >= ? AND decision_date <= ?
                    ORDER BY decision_date, snapshot_id
                    """,
                    (self.portfolio_id, period_start, period_end),
                ).fetchall()
                snapshots: list[PaperPortfolioSnapshot] = []
                for row in rows:
                    try:
                        snapshot_id = _required_text(row["snapshot_id"], "snapshot_id")
                        decision_date = _require_date(row["decision_date"], "decision_date").isoformat()
                        position_rows = conn.execute(
                            """
                            SELECT stock_code, quantity, mark_price, market_value, weight_bp
                            FROM paper_portfolio_positions
                            WHERE snapshot_id = ?
                            ORDER BY stock_code
                            """,
                            (snapshot_id,),
                        ).fetchall()
                        positions = tuple(
                            PaperPortfolioPositionSnapshot(
                                stock_code=_required_text(item["stock_code"], "stock_code"),
                                quantity=_non_negative_int(item["quantity"], "quantity"),
                                mark_price=_decimal(item["mark_price"], "mark_price"),
                                market_value=_decimal(item["market_value"], "market_value"),
                                weight_bp=_bounded_int(item["weight_bp"], "weight_bp", 10000),
                            )
                            for item in position_rows
                        )
                        snapshots.append(
                            PaperPortfolioSnapshot(
                                snapshot_id=snapshot_id,
                                portfolio_id=_required_text(row["portfolio_id"], "portfolio_id"),
                                decision_date=decision_date,
                                source_result_id=str(row["source_result_id"] or ""),
                                cash=_decimal(row["cash"], "cash"),
                                total_value=_decimal(row["total_value"], "total_value"),
                                positions=positions,
                            )
                        )
                    except (TypeError, ValueError, ArithmeticError) as exc:
                        blockers.append("paper_snapshot_invalid_row")
                        diagnostics.append(
                            f"paper_snapshot_row_invalid:{row['snapshot_id']}:{type(exc).__name__}"
                        )
                dates = [item.decision_date for item in snapshots]
                if len(dates) != len(set(dates)):
                    blockers.append("paper_weekly_report_duplicate_snapshot_date")
                return tuple(snapshots)
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            blockers.append("paper_snapshot_db_unavailable")
            diagnostics.append(f"paper_snapshot_db_error:{type(exc).__name__}")
            return ()

    def _read_benchmarks(
        self,
        period_start: str,
        period_end: str,
        *,
        blockers: list[str],
        diagnostics: list[str],
    ) -> tuple[EqualWeightBenchmarkEntry, ...]:
        if not self.benchmark_db_path.is_file():
            blockers.append("equal_weight_benchmark_db_missing")
            return ()
        manager = ReadOnlySQLiteManager(self.benchmark_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_equal_weight_benchmark"):
                    blockers.append("equal_weight_benchmark_table_missing")
                    return ()
                rows = conn.execute(
                    """
                    SELECT benchmark_id, decision_date, constituents_json, units_json, total_value
                    FROM paper_equal_weight_benchmark
                    WHERE benchmark_id = ? AND decision_date >= ? AND decision_date <= ?
                    ORDER BY decision_date
                    """,
                    (self.benchmark_id, period_start, period_end),
                ).fetchall()
                entries: list[EqualWeightBenchmarkEntry] = []
                for row in rows:
                    try:
                        constituents_raw = json.loads(str(row["constituents_json"]))
                        units_raw = json.loads(str(row["units_json"]))
                        if not isinstance(constituents_raw, list) or not constituents_raw:
                            raise ValueError("constituents_json must be a non-empty list")
                        if not isinstance(units_raw, list) or not units_raw:
                            raise ValueError("units_json must be a non-empty list")
                        units: list[tuple[str, Decimal]] = []
                        for item in units_raw:
                            if not isinstance(item, list) or len(item) != 2:
                                raise ValueError("units_json item must be [stock_code, units]")
                            units.append(
                                (
                                    _required_text(item[0], "unit stock_code"),
                                    _positive_decimal(item[1], "units"),
                                )
                            )
                        entries.append(
                            EqualWeightBenchmarkEntry(
                                benchmark_id=_required_text(row["benchmark_id"], "benchmark_id"),
                                decision_date=_require_date(row["decision_date"], "decision_date").isoformat(),
                                constituents=tuple(
                                    _required_text(item, "constituent")
                                    for item in constituents_raw
                                ),
                                units=tuple(units),
                                total_value=_decimal(row["total_value"], "total_value"),
                            )
                        )
                    except (TypeError, ValueError, ArithmeticError, json.JSONDecodeError) as exc:
                        blockers.append("equal_weight_benchmark_invalid_row")
                        diagnostics.append(
                            f"equal_weight_benchmark_row_invalid:{row['decision_date']}:{type(exc).__name__}"
                        )
                dates = [item.decision_date for item in entries]
                if len(dates) != len(set(dates)):
                    blockers.append("paper_weekly_report_duplicate_benchmark_date")
                return tuple(entries)
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            blockers.append("equal_weight_benchmark_db_unavailable")
            diagnostics.append(f"equal_weight_benchmark_db_error:{type(exc).__name__}")
            return ()

    def _read_costs(
        self,
        period_start: str,
        period_end: str,
        *,
        blockers: list[str],
        warnings: list[str],
        diagnostics: list[str],
    ) -> tuple[PaperTradeCostRecord, ...]:
        if self.cost_ledger_db_path is None:
            blockers.append("paper_trade_ledger_path_not_configured")
            return ()
        if not self.cost_ledger_db_path.is_file():
            blockers.append("paper_trade_ledger_db_missing")
            return ()
        manager = ReadOnlySQLiteManager(self.cost_ledger_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_trade_ledger"):
                    blockers.append("paper_trade_ledger_schema_mismatch")
                    diagnostics.append("paper_trade_ledger_table_missing")
                    return ()
                columns = {
                    str(row[1])
                    for row in conn.execute('PRAGMA table_info("paper_trade_ledger")').fetchall()
                }
                required_columns = {
                    "schema_version",
                    "fill_id",
                    "order_id",
                    "portfolio_id",
                    "event_date",
                    "stock_code",
                    "side",
                    "requested_quantity",
                    "filled_quantity",
                    "reference_price",
                    "fill_price",
                    "commission",
                    "tax",
                    "slippage_cost",
                    "turnover_bp",
                    "execution_gap_bp",
                    "status",
                    "source_event_id",
                    "override_reason",
                    "source_type",
                    "research_only",
                    "broker_order_allowed",
                    "auto_rebalance_allowed",
                }
                missing_columns = sorted(required_columns - columns)
                if missing_columns:
                    blockers.append("paper_trade_ledger_schema_mismatch")
                    diagnostics.append(
                        "paper_trade_ledger_missing_columns:" + ",".join(missing_columns)
                    )
                    return ()
                rows = conn.execute(
                    """
                    SELECT * FROM paper_trade_ledger
                    WHERE portfolio_id = ?
                    ORDER BY event_date, fill_id
                    """,
                    (self.portfolio_id,),
                ).fetchall()
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            blockers.append("paper_trade_ledger_db_unavailable")
            diagnostics.append(f"paper_trade_ledger_db_error:{type(exc).__name__}")
            return ()

        if not rows:
            blockers.append("paper_trade_ledger_empty")
            return ()

        costs: list[PaperTradeCostRecord] = []
        period_rows = 0
        for row in rows:
            try:
                fill = _fill_from_row(row)
                event_date = _require_date(fill.event_date, "event_date").isoformat()
                if str(row["schema_version"]) != PAPER_TRADE_LEDGER_SCHEMA_VERSION:
                    raise ValueError("schema_version_mismatch")
                if not fill.source_type.startswith("paper_"):
                    raise ValueError("source_type_not_paper")
            except (TypeError, ValueError, ArithmeticError) as exc:
                blockers.append("paper_trade_ledger_invalid_row")
                diagnostics.append(
                    f"paper_trade_ledger_row_invalid:{row['fill_id']}:{type(exc).__name__}:{exc}"
                )
                continue
            if not period_start <= event_date <= period_end:
                continue
            period_rows += 1
            if fill.turnover_bp is None:
                blockers.append("paper_weekly_report_cost_turnover_missing")
                diagnostics.append(f"paper_trade_ledger_turnover_missing:{fill.fill_id}")
                continue
            if fill.filled_quantity > 0 and fill.execution_gap_bp is None:
                blockers.append("paper_weekly_report_execution_gap_missing")
                diagnostics.append(f"paper_trade_ledger_execution_gap_missing:{fill.fill_id}")
                continue
            costs.append(
                PaperTradeCostRecord(
                    decision_date=event_date,
                    total_cost=fill.total_cost,
                    turnover_bp=fill.turnover_bp,
                )
            )
        if period_rows == 0:
            warnings.append("paper_trade_ledger_no_records_in_period")
        return tuple(costs)

    def _empty_result(
        self,
        *,
        status: str,
        expected_trading_days: int,
        blockers: tuple[str, ...],
        diagnostics: tuple[str, ...],
    ) -> PaperPortfolioWeeklyEvidenceDTO:
        return PaperPortfolioWeeklyEvidenceDTO(
            generated_at=_utc_now_text(),
            status=status,
            period_start=None,
            period_end=None,
            expected_trading_days=expected_trading_days,
            portfolio_id=self.portfolio_id,
            benchmark_id=self.benchmark_id,
            state_db_path=str(self.state_db_path),
            benchmark_db_path=(str(self.benchmark_db_path) if self.benchmark_db_path else None),
            cost_ledger_db_path=(
                str(self.cost_ledger_db_path) if self.cost_ledger_db_path else None
            ),
            blockers=tuple(sorted(set(blockers))),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )


def _fill_from_row(row: sqlite3.Row) -> PaperTradeFill:
    return PaperTradeFill(
        fill_id=_required_text(row["fill_id"], "fill_id"),
        order_id=_required_text(row["order_id"], "order_id"),
        portfolio_id=_required_text(row["portfolio_id"], "portfolio_id"),
        event_date=_require_date(row["event_date"], "event_date").isoformat(),
        stock_code=_required_text(row["stock_code"], "stock_code"),
        side=_required_text(row["side"], "side"),
        requested_quantity=_non_negative_int(row["requested_quantity"], "requested_quantity"),
        filled_quantity=_non_negative_int(row["filled_quantity"], "filled_quantity"),
        reference_price=_positive_decimal(row["reference_price"], "reference_price"),
        fill_price=(
            None
            if row["fill_price"] is None
            else _positive_decimal(row["fill_price"], "fill_price")
        ),
        commission=_decimal(row["commission"], "commission"),
        tax=_decimal(row["tax"], "tax"),
        slippage_cost=_decimal(row["slippage_cost"], "slippage_cost"),
        turnover_bp=(
            None if row["turnover_bp"] is None else _non_negative_int(row["turnover_bp"], "turnover_bp")
        ),
        execution_gap_bp=(
            None if row["execution_gap_bp"] is None else _integer(row["execution_gap_bp"], "execution_gap_bp")
        ),
        status=_required_text(row["status"], "status"),
        source_event_id=_required_text(row["source_event_id"], "source_event_id"),
        override_reason=(
            None if row["override_reason"] is None else str(row["override_reason"])
        ),
        source_type=_required_text(row["source_type"], "source_type"),
        research_only=_sqlite_safety_flag(row["research_only"], "research_only"),
        broker_order_allowed=_sqlite_safety_flag(
            row["broker_order_allowed"], "broker_order_allowed"
        ),
        auto_rebalance_allowed=_sqlite_safety_flag(
            row["auto_rebalance_allowed"], "auto_rebalance_allowed"
        ),
    )


def _status_for(
    *,
    snapshots: tuple[PaperPortfolioSnapshot, ...],
    benchmarks: tuple[EqualWeightBenchmarkEntry, ...],
    blockers: tuple[str, ...],
    warnings: tuple[str, ...],
    report: PaperPortfolioWeeklyReport | None,
) -> str:
    configuration_tokens = (
        "db_missing",
        "path_not_configured",
        "table_missing",
    )
    if any(any(token in item for token in configuration_tokens) for item in blockers):
        return "not_configured"
    if not snapshots or not benchmarks:
        if any(
            token in item
            for item in blockers
            for token in ("missing", "not_configured", "schema_mismatch", "unavailable")
        ):
            return "not_configured"
        return "not_computable"
    if blockers:
        return "degraded"
    if report is None:
        return "not_computable"
    if warnings:
        return "partial"
    return "ready"


def _with_extra_messages(
    result: PaperPortfolioWeeklyEvidenceDTO,
    *,
    blockers: list[str],
    diagnostics: list[str],
) -> PaperPortfolioWeeklyEvidenceDTO:
    all_blockers = tuple(sorted(set((*result.blockers, *blockers))))
    all_diagnostics = tuple(dict.fromkeys((*result.diagnostics, *diagnostics)))
    return PaperPortfolioWeeklyEvidenceDTO(
        generated_at=result.generated_at,
        status="degraded" if all_blockers else result.status,
        period_start=result.period_start,
        period_end=result.period_end,
        expected_trading_days=result.expected_trading_days,
        portfolio_id=result.portfolio_id,
        benchmark_id=result.benchmark_id,
        state_db_path=result.state_db_path,
        benchmark_db_path=result.benchmark_db_path,
        cost_ledger_db_path=result.cost_ledger_db_path,
        snapshot_count=result.snapshot_count,
        benchmark_observation_count=result.benchmark_observation_count,
        cost_record_count=result.cost_record_count,
        report=result.report,
        blockers=all_blockers,
        warnings=result.warnings,
        diagnostics=all_diagnostics,
    )


def _report_to_dict(report: PaperPortfolioWeeklyReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "period_start": report.period_start,
        "period_end": report.period_end,
        "observed_trading_days": report.observed_trading_days,
        "gross_return_bp": report.gross_return_bp,
        "net_return_bp": report.net_return_bp,
        "benchmark_return_bp": report.benchmark_return_bp,
        "net_excess_return_bp": report.net_excess_return_bp,
        "total_cost": str(report.total_cost),
        "turnover_bp": report.turnover_bp,
        "data_quality": report.data_quality,
        "warnings": list(report.warnings),
        "research_only": report.research_only,
        "investment_effectiveness_claim": report.investment_effectiveness_claim,
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _require_date(value: object, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must not be bool")
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return parsed


def _positive_decimal(value: object, field_name: str) -> Decimal:
    parsed = _decimal(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be a non-negative integer")
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return parsed


def _bounded_int(value: object, field_name: str, maximum: int) -> int:
    parsed = _non_negative_int(value, field_name)
    if parsed > maximum:
        raise ValueError(f"{field_name} must be within 0..{maximum}")
    return parsed


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"{field_name} must be an integer")


def _sqlite_safety_flag(value: object, field_name: str) -> bool:
    if isinstance(value, bool) or value not in (0, 1):
        raise ValueError(f"{field_name} must be canonical SQLite boolean 0 or 1")
    return value == 1


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "DEFAULT_BENCHMARK_ID",
    "DEFAULT_BENCHMARK_LEDGER_FILENAME",
    "DEFAULT_COST_LEDGER_FILENAME",
    "DEFAULT_PORTFOLIO_ID",
    "PAPER_WEEKLY_EVIDENCE_SCHEMA_VERSION",
    "PaperPortfolioWeeklyEvidenceDTO",
    "PaperPortfolioWeeklyEvidenceService",
]
