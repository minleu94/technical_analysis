"""唯讀彙總 Paper Portfolio、Equal Weight 與週報輸入狀態。

Paper Portfolio 的 runner 與 ledger 是 append-only writer；主 UI／Inspector
不能為了顯示狀態而建構 writer repository，或因缺檔初始化空 schema。這個
service 只讀既有 status JSON／SQLite，將「已累積的 paper snapshot」與「仍
缺少的 benchmark／成本後比較輸入」拆開呈現，並固定保留 research-only 邊界。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from app_module.paper_trade_ledger import (
    PAPER_TRADE_LEDGER_SCHEMA_VERSION,
    PaperTradeFill,
)
from app_module.paper_portfolio_time import paper_portfolio_today
from app_module.sqlite_read_only import ReadOnlySQLiteManager


PAPER_PORTFOLIO_READINESS_SCHEMA_VERSION = "paper-portfolio-readiness.v1"
PAPER_DAILY_STATUS_SCHEMA_VERSION = "paper-portfolio-daily-status.v1"
DEFAULT_PORTFOLIO_ID = "paper-main"
DEFAULT_BENCHMARK_ID = "paper-main-equal"
DEFAULT_BENCHMARK_LEDGER_FILENAME = "paper_equal_weight_benchmark.sqlite"
DEFAULT_COST_LEDGER_FILENAME = "paper_trade_ledger.sqlite"


@dataclass(frozen=True)
class PaperPositionReadModel:
    """最新 paper snapshot 的單一持倉唯讀列。"""

    stock_code: str
    quantity: int
    mark_price: Decimal
    market_value: Decimal
    weight_bp: int

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code is required")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity < 0:
            raise ValueError("quantity must be a non-negative integer")
        for field_name in ("mark_price", "market_value"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"{field_name} must be a finite non-negative Decimal")
        if isinstance(self.weight_bp, bool) or not isinstance(self.weight_bp, int) or not 0 <= self.weight_bp <= 10_000:
            raise ValueError("weight_bp must be an integer within 0..10000")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "quantity": self.quantity,
            "mark_price": str(self.mark_price),
            "market_value": str(self.market_value),
            "weight_bp": self.weight_bp,
        }


@dataclass(frozen=True)
class PaperPortfolioReadinessDTO:
    """Paper Portfolio UI／CLI 的唯讀 readiness read model。"""

    generated_at: str
    status: str
    latest_status: str
    status_path: str
    state_db_path: str
    benchmark_db_path: str | None
    baseline_path: str
    snapshot_count: int
    first_snapshot_date: str | None
    latest_snapshot_date: str | None
    latest_snapshot_id: str | None
    latest_total_value: Decimal | None
    latest_cash: Decimal | None
    latest_position_count: int
    latest_positions: tuple[PaperPositionReadModel, ...] = ()
    cost_ledger_db_path: str | None = None
    cost_ledger_status: str = "not_configured"
    cost_record_count: int = 0
    cost_ledger_first_date: str | None = None
    cost_ledger_latest_date: str | None = None
    cost_total_cost: Decimal | None = None
    filled_event_count: int = 0
    partial_fill_event_count: int = 0
    rejected_event_count: int = 0
    override_event_count: int = 0
    missing_execution_gap_count: int = 0
    missing_turnover_count: int = 0
    benchmark_id: str = DEFAULT_BENCHMARK_ID
    benchmark_observation_count: int = 0
    benchmark_first_date: str | None = None
    benchmark_latest_date: str | None = None
    weekly_report_status: str = "not_computable"
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
        if self.status not in {"ready", "partial", "degraded", "not_configured"}:
            raise ValueError(f"unsupported paper readiness status: {self.status}")
        if self.cost_ledger_status not in {"ready", "partial", "invalid", "missing", "not_configured"}:
            raise ValueError(f"unsupported cost ledger status: {self.cost_ledger_status}")
        if self.latest_status == "":
            raise ValueError("latest_status must not be empty")
        for field_name in (
            "snapshot_count",
            "latest_position_count",
            "benchmark_observation_count",
            "cost_record_count",
            "filled_event_count",
            "partial_fill_event_count",
            "rejected_event_count",
            "override_event_count",
            "missing_execution_gap_count",
            "missing_turnover_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in ("latest_total_value", "latest_cash", "cost_total_cost"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a finite non-negative Decimal or None")
        # Safety flags are contract constants, not caller-provided permissions.
        if (
            self.research_only is not True
            or self.investment_effectiveness_claim is not False
            or self.read_only is not True
            or self.writes_allowed is not False
            or self.broker_execution is not False
            or self.auto_rebalance_allowed is not False
        ):
            raise ValueError("paper readiness safety boundary must remain fail-closed")

    @property
    def benchmark_ready(self) -> bool:
        return self.benchmark_observation_count >= 2 and not any(
            item.startswith("equal_weight_") for item in self.blockers
        )

    @property
    def cost_ledger_ready(self) -> bool:
        return self.cost_ledger_status == "ready" and self.cost_record_count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAPER_PORTFOLIO_READINESS_SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "status": self.status,
            "latest_status": self.latest_status,
            "status_path": self.status_path,
            "state_db_path": self.state_db_path,
            "benchmark_db_path": self.benchmark_db_path,
            "baseline_path": self.baseline_path,
            "snapshot_count": self.snapshot_count,
            "first_snapshot_date": self.first_snapshot_date,
            "latest_snapshot_date": self.latest_snapshot_date,
            "latest_snapshot_id": self.latest_snapshot_id,
            "latest_total_value": _decimal_text(self.latest_total_value),
            "latest_cash": _decimal_text(self.latest_cash),
            "latest_position_count": self.latest_position_count,
            "latest_positions": [item.to_dict() for item in self.latest_positions],
            "cost_ledger_db_path": self.cost_ledger_db_path,
            "cost_ledger_status": self.cost_ledger_status,
            "cost_record_count": self.cost_record_count,
            "cost_ledger_first_date": self.cost_ledger_first_date,
            "cost_ledger_latest_date": self.cost_ledger_latest_date,
            "cost_total_cost": _decimal_text(self.cost_total_cost),
            "filled_event_count": self.filled_event_count,
            "partial_fill_event_count": self.partial_fill_event_count,
            "rejected_event_count": self.rejected_event_count,
            "override_event_count": self.override_event_count,
            "missing_execution_gap_count": self.missing_execution_gap_count,
            "missing_turnover_count": self.missing_turnover_count,
            "benchmark_id": self.benchmark_id,
            "benchmark_observation_count": self.benchmark_observation_count,
            "benchmark_first_date": self.benchmark_first_date,
            "benchmark_latest_date": self.benchmark_latest_date,
            "weekly_report_status": self.weekly_report_status,
            "benchmark_ready": self.benchmark_ready,
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


class PaperPortfolioReadinessService:
    """只讀檢查既有 paper snapshot 與 benchmark ledger，不建立資料。"""

    def __init__(
        self,
        *,
        output_root: str | Path,
        status_path: str | Path | None = None,
        state_db_path: str | Path | None = None,
        baseline_path: str | Path | None = None,
        benchmark_db_path: str | Path | None = None,
        cost_ledger_db_path: str | Path | None = None,
        portfolio_id: str = DEFAULT_PORTFOLIO_ID,
        benchmark_id: str = DEFAULT_BENCHMARK_ID,
    ) -> None:
        self.output_root = Path(output_root)
        self.status_path = (
            Path(status_path)
            if status_path is not None
            else self.output_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
        )
        self.state_db_path = (
            Path(state_db_path)
            if state_db_path is not None
            else self.output_root / "paper_portfolio" / "paper_portfolio.sqlite"
        )
        self.baseline_path = (
            Path(baseline_path)
            if baseline_path is not None
            else self.output_root / "paper_portfolio" / "baseline_20260712.json"
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
            if configured_cost_ledger
            else self.output_root / "paper_portfolio" / DEFAULT_COST_LEDGER_FILENAME
        )
        self.portfolio_id = portfolio_id
        self.benchmark_id = benchmark_id

    def inspect(self) -> PaperPortfolioReadinessDTO:
        blockers: list[str] = []
        warnings: list[str] = []
        diagnostics: list[str] = []

        status_payload, latest_status = self._read_status(blockers, warnings, diagnostics)
        snapshots, latest_positions = self._read_snapshots(blockers, diagnostics)
        today = paper_portfolio_today()
        future_snapshot_dates = sorted(
            {
                str(snapshot["decision_date"])
                for snapshot in snapshots
                if _is_future_date(snapshot.get("decision_date"), today)
            }
        )
        if future_snapshot_dates:
            blockers.append("paper_snapshot_future_dated")
            diagnostics.extend(
                f"paper_snapshot_future_date:{item}:today={today.isoformat()}"
                for item in future_snapshot_dates
            )
        if status_payload is not None and _is_future_date(status_payload.get("decision_date"), today):
            blockers.append("paper_daily_status_future_dated")
            diagnostics.append(
                "paper_daily_status_future_date:"
                f"{status_payload.get('decision_date')}:today={today.isoformat()}"
            )
        benchmark = self._read_benchmark(blockers, diagnostics)
        cost_ledger = self._read_cost_ledger(blockers, warnings, diagnostics)

        snapshot_count = len(snapshots)
        first_snapshot_date = snapshots[0]["decision_date"] if snapshots else None
        # Keep every raw row in ``snapshot_count`` for auditability, but never
        # project a future-dated row as the current paper portfolio.  A clock
        # or scheduler mistake must not turn a future mark into today's NAV or
        # positions.  The raw row remains visible through the blocker and
        # diagnostic above, and is intentionally not deleted or rewritten.
        current_snapshots = [
            snapshot
            for snapshot in snapshots
            if not _is_future_date(snapshot.get("decision_date"), today)
        ]
        latest_snapshot = current_snapshots[-1] if current_snapshots else None
        if snapshots and latest_snapshot is None:
            latest_positions = []
            diagnostics.append("paper_snapshot_current_projection_unavailable_all_rows_future")
        elif (
            snapshots
            and latest_snapshot is not None
            and latest_snapshot["snapshot_id"] != snapshots[-1]["snapshot_id"]
        ):
            latest_positions = self._read_snapshot_positions(
                latest_snapshot["snapshot_id"],
                blockers,
                diagnostics,
            )
            diagnostics.append(
                "paper_snapshot_future_rows_excluded_from_current_projection:"
                f"{len(snapshots) - len(current_snapshots)}"
            )
        latest_snapshot_date = latest_snapshot["decision_date"] if latest_snapshot else None
        latest_snapshot_id = latest_snapshot["snapshot_id"] if latest_snapshot else None
        latest_total_value = latest_snapshot["total_value"] if latest_snapshot else None
        latest_cash = latest_snapshot["cash"] if latest_snapshot else None

        self._reconcile_status(
            status_payload,
            latest_snapshot=latest_snapshot,
            blockers=blockers,
            diagnostics=diagnostics,
        )

        if snapshot_count < 1:
            blockers.append("paper_snapshot_history_missing")
        if snapshot_count < 2:
            blockers.append("paper_weekly_report_requires_two_snapshots")
        if benchmark["count"] < 2:
            blockers.append("paper_weekly_report_benchmark_observations_missing")
        boundary_mismatch = snapshot_count >= 2 and benchmark["count"] >= 2 and (
            first_snapshot_date != benchmark["first_date"]
            or latest_snapshot_date != benchmark["latest_date"]
        )
        if boundary_mismatch:
            # The weekly report service rejects non-aligned periods. Surface the
            # same boundary contract here so readiness cannot overstate a
            # computable report merely because both ledgers have two rows.
            blockers.append("paper_weekly_report_boundary_mismatch")
        future_dated = any(
            item in blockers
            for item in ("paper_snapshot_future_dated", "paper_daily_status_future_dated")
        )
        if future_dated:
            weekly_report_status = "not_computable_future_dated"
        elif snapshot_count >= 2 and benchmark["count"] >= 2:
            if boundary_mismatch:
                weekly_report_status = "not_computable_boundary_mismatch"
            elif cost_ledger["status"] == "ready" and cost_ledger["count"] > 0:
                weekly_report_status = "ready"
            elif cost_ledger["status"] == "invalid":
                weekly_report_status = "not_computable_cost_ledger_invalid"
            elif cost_ledger["status"] == "partial":
                weekly_report_status = "not_computable_cost_ledger_incomplete"
            else:
                weekly_report_status = "not_computable_cost_ledger_missing"
        else:
            weekly_report_status = "not_computable"

        unique_blockers = tuple(sorted(set(blockers)))
        unique_warnings = tuple(sorted(set(warnings)))
        unique_diagnostics = tuple(dict.fromkeys(diagnostics))
        status = _overall_status(
            status_payload=status_payload,
            snapshots=snapshots,
            blockers=unique_blockers,
            warnings=unique_warnings,
        )
        return PaperPortfolioReadinessDTO(
            generated_at=_utc_now_text(),
            status=status,
            latest_status=latest_status,
            status_path=str(self.status_path),
            state_db_path=str(self.state_db_path),
            benchmark_db_path=(str(self.benchmark_db_path) if self.benchmark_db_path else None),
            baseline_path=str(self.baseline_path),
            snapshot_count=snapshot_count,
            first_snapshot_date=first_snapshot_date,
            latest_snapshot_date=latest_snapshot_date,
            latest_snapshot_id=latest_snapshot_id,
            latest_total_value=latest_total_value,
            latest_cash=latest_cash,
            latest_position_count=len(latest_positions),
            latest_positions=tuple(latest_positions),
            cost_ledger_db_path=str(self.cost_ledger_db_path),
            cost_ledger_status=cost_ledger["status"],
            cost_record_count=cost_ledger["count"],
            cost_ledger_first_date=cost_ledger["first_date"],
            cost_ledger_latest_date=cost_ledger["latest_date"],
            cost_total_cost=cost_ledger["total_cost"],
            filled_event_count=cost_ledger["filled_count"],
            partial_fill_event_count=cost_ledger["partial_count"],
            rejected_event_count=cost_ledger["rejected_count"],
            override_event_count=cost_ledger["override_count"],
            missing_execution_gap_count=cost_ledger["missing_execution_gap_count"],
            missing_turnover_count=cost_ledger["missing_turnover_count"],
            benchmark_id=self.benchmark_id,
            benchmark_observation_count=benchmark["count"],
            benchmark_first_date=benchmark["first_date"],
            benchmark_latest_date=benchmark["latest_date"],
            weekly_report_status=weekly_report_status,
            blockers=unique_blockers,
            warnings=unique_warnings,
            diagnostics=unique_diagnostics,
        )

    def _read_status(
        self,
        blockers: list[str],
        warnings: list[str],
        diagnostics: list[str],
    ) -> tuple[dict[str, Any] | None, str]:
        if not self.status_path.is_file():
            blockers.append("paper_daily_status_missing")
            return None, "not_configured"
        try:
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            blockers.append("paper_daily_status_invalid")
            diagnostics.append(f"paper_daily_status_read_error:{type(exc).__name__}")
            return None, "invalid"
        if not isinstance(payload, Mapping):
            blockers.append("paper_daily_status_invalid")
            diagnostics.append("paper_daily_status_payload_not_object")
            return None, "invalid"
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != PAPER_DAILY_STATUS_SCHEMA_VERSION:
            blockers.append("paper_daily_status_schema_mismatch")
        status = str(payload.get("status", "unknown"))
        if status not in {"passed", "skipped_non_trading_day"}:
            blockers.append(f"paper_daily_status_{status}")
        for key in ("writes_market_db", "auto_rebalance_allowed", "changes_advice", "broker_execution"):
            if payload.get(key) is not False:
                blockers.append(f"paper_daily_status_boundary_violation:{key}")
        if status == "passed":
            diagnostics.extend(str(item) for item in payload.get("diagnostics", ()) if str(item))
        return dict(payload), status

    def _read_snapshots(
        self,
        blockers: list[str],
        diagnostics: list[str],
    ) -> tuple[list[dict[str, Any]], list[PaperPositionReadModel]]:
        if not self.state_db_path.is_file():
            blockers.append("paper_snapshot_db_missing")
            return [], []
        manager = ReadOnlySQLiteManager(self.state_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_portfolio_snapshots"):
                    blockers.append("paper_snapshot_table_missing")
                    return [], []
                if not _table_exists(conn, "paper_portfolio_positions"):
                    blockers.append("paper_snapshot_positions_table_missing")
                    return [], []
                rows = conn.execute(
                    """
                    SELECT snapshot_id, portfolio_id, decision_date, cash, total_value
                    FROM paper_portfolio_snapshots
                    WHERE portfolio_id = ?
                    ORDER BY decision_date, snapshot_id
                    """,
                    (self.portfolio_id,),
                ).fetchall()
                snapshots: list[dict[str, Any]] = []
                latest_positions: list[PaperPositionReadModel] = []
                for row in rows:
                    try:
                        snapshot = {
                            "snapshot_id": str(row["snapshot_id"]),
                            "portfolio_id": str(row["portfolio_id"]),
                            "decision_date": str(row["decision_date"]),
                            "cash": _decimal(row["cash"], "cash"),
                            "total_value": _decimal(row["total_value"], "total_value"),
                        }
                    except (TypeError, ValueError) as exc:
                        blockers.append("paper_snapshot_invalid_numeric")
                        diagnostics.append(f"paper_snapshot_row_invalid:{type(exc).__name__}")
                        continue
                    snapshots.append(snapshot)
                if snapshots:
                    latest_id = snapshots[-1]["snapshot_id"]
                    position_rows = conn.execute(
                        """
                        SELECT stock_code, quantity, mark_price, market_value, weight_bp
                        FROM paper_portfolio_positions
                        WHERE snapshot_id = ?
                        ORDER BY stock_code
                        """,
                        (latest_id,),
                    ).fetchall()
                    for row in position_rows:
                        try:
                            latest_positions.append(
                                PaperPositionReadModel(
                                    stock_code=str(row["stock_code"]),
                                    quantity=_non_negative_int(row["quantity"], "quantity"),
                                    mark_price=_decimal(row["mark_price"], "mark_price"),
                                    market_value=_decimal(row["market_value"], "market_value"),
                                    weight_bp=_non_negative_int(row["weight_bp"], "weight_bp"),
                                )
                            )
                        except (TypeError, ValueError) as exc:
                            blockers.append("paper_snapshot_position_invalid")
                            diagnostics.append(f"paper_snapshot_position_invalid:{type(exc).__name__}")
                return snapshots, latest_positions
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            blockers.append("paper_snapshot_db_unavailable")
            diagnostics.append(f"paper_snapshot_db_error:{type(exc).__name__}")
            return [], []

    def _read_snapshot_positions(
        self,
        snapshot_id: str,
        blockers: list[str],
        diagnostics: list[str],
    ) -> list[PaperPositionReadModel]:
        """Read positions for the latest non-future snapshot only.

        This helper is deliberately query-only and is used only when the raw
        newest row is future-dated.  It keeps the UI useful for the last safe
        snapshot without allowing the future row to become current evidence.
        """

        manager = ReadOnlySQLiteManager(self.state_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_portfolio_positions"):
                    blockers.append("paper_snapshot_positions_table_missing")
                    return []
                rows = conn.execute(
                    """
                    SELECT stock_code, quantity, mark_price, market_value, weight_bp
                    FROM paper_portfolio_positions
                    WHERE snapshot_id = ?
                    ORDER BY stock_code
                    """,
                    (snapshot_id,),
                ).fetchall()
                positions: list[PaperPositionReadModel] = []
                for row in rows:
                    try:
                        positions.append(
                            PaperPositionReadModel(
                                stock_code=str(row["stock_code"]),
                                quantity=_non_negative_int(row["quantity"], "quantity"),
                                mark_price=_decimal(row["mark_price"], "mark_price"),
                                market_value=_decimal(row["market_value"], "market_value"),
                                weight_bp=_non_negative_int(row["weight_bp"], "weight_bp"),
                            )
                        )
                    except (TypeError, ValueError) as exc:
                        blockers.append("paper_snapshot_position_invalid")
                        diagnostics.append(f"paper_snapshot_position_invalid:{type(exc).__name__}")
                return positions
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            blockers.append("paper_snapshot_db_unavailable")
            diagnostics.append(f"paper_snapshot_db_error:{type(exc).__name__}")
            return []

    def _read_benchmark(self, blockers: list[str], diagnostics: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {"count": 0, "first_date": None, "latest_date": None}
        if not self.benchmark_db_path.is_file():
            blockers.append("equal_weight_benchmark_db_missing")
            return result
        manager = ReadOnlySQLiteManager(self.benchmark_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_equal_weight_benchmark"):
                    blockers.append("equal_weight_benchmark_table_missing")
                    return result
                rows = conn.execute(
                    """
                    SELECT decision_date
                    FROM paper_equal_weight_benchmark
                    WHERE benchmark_id = ?
                    ORDER BY decision_date
                    """,
                    (self.benchmark_id,),
                ).fetchall()
                dates = [str(row["decision_date"]) for row in rows if str(row["decision_date"])]
                result["count"] = len(dates)
                result["first_date"] = dates[0] if dates else None
                result["latest_date"] = dates[-1] if dates else None
                return result
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            blockers.append("equal_weight_benchmark_db_unavailable")
            diagnostics.append(f"equal_weight_benchmark_db_error:{type(exc).__name__}")
            return result

    def _read_cost_ledger(
        self,
        blockers: list[str],
        warnings: list[str],
        diagnostics: list[str],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "missing",
            "count": 0,
            "first_date": None,
            "latest_date": None,
            "total_cost": None,
            "filled_count": 0,
            "partial_count": 0,
            "rejected_count": 0,
            "override_count": 0,
            "missing_execution_gap_count": 0,
            "missing_turnover_count": 0,
        }
        if not self.cost_ledger_db_path.is_file():
            warnings.append("paper_trade_cost_ledger_not_configured")
            diagnostics.append(f"paper_trade_ledger_path_missing:{self.cost_ledger_db_path}")
            return result

        manager = ReadOnlySQLiteManager(self.cost_ledger_db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "paper_trade_ledger"):
                    blockers.append("paper_trade_ledger_schema_mismatch")
                    diagnostics.append("paper_trade_ledger_table_missing")
                    result["status"] = "invalid"
                    return result
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
                    result["status"] = "invalid"
                    return result
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
            result["status"] = "invalid"
            return result

        result["count"] = len(rows)
        if not rows:
            warnings.append("paper_trade_ledger_empty")
            result["status"] = "partial"
            return result

        valid: list[PaperTradeFill] = []
        invalid_count = 0
        for row in rows:
            status = str(row["status"] or "")
            if status == "filled":
                result["filled_count"] += 1
            elif status == "partially_filled":
                result["partial_count"] += 1
            elif status in {"rejected", "cancelled"}:
                result["rejected_count"] += 1
            if row["override_reason"] is not None and str(row["override_reason"]).strip():
                result["override_count"] += 1
            try:
                raw_filled_quantity = int(row["filled_quantity"] or 0)
            except (TypeError, ValueError):
                raw_filled_quantity = 0
            if row["execution_gap_bp"] is None and raw_filled_quantity > 0:
                result["missing_execution_gap_count"] += 1
            if row["turnover_bp"] is None:
                result["missing_turnover_count"] += 1
            try:
                research_only = _sqlite_safety_flag(row["research_only"], "research_only")
                broker_order_allowed = _sqlite_safety_flag(
                    row["broker_order_allowed"], "broker_order_allowed"
                )
                auto_rebalance_allowed = _sqlite_safety_flag(
                    row["auto_rebalance_allowed"], "auto_rebalance_allowed"
                )
                fill = PaperTradeFill(
                    fill_id=str(row["fill_id"]),
                    order_id=str(row["order_id"]),
                    portfolio_id=str(row["portfolio_id"]),
                    event_date=str(row["event_date"]),
                    stock_code=str(row["stock_code"]),
                    side=str(row["side"]),
                    requested_quantity=int(row["requested_quantity"]),
                    filled_quantity=int(row["filled_quantity"]),
                    reference_price=Decimal(str(row["reference_price"])),
                    fill_price=(
                        None
                        if row["fill_price"] is None
                        else Decimal(str(row["fill_price"]))
                    ),
                    commission=Decimal(str(row["commission"])),
                    tax=Decimal(str(row["tax"])),
                    slippage_cost=Decimal(str(row["slippage_cost"])),
                    turnover_bp=(
                        None if row["turnover_bp"] is None else int(row["turnover_bp"])
                    ),
                    execution_gap_bp=(
                        None
                        if row["execution_gap_bp"] is None
                        else int(row["execution_gap_bp"])
                    ),
                    status=status,
                    source_event_id=str(row["source_event_id"]),
                    override_reason=(
                        None
                        if row["override_reason"] is None
                        else str(row["override_reason"])
                    ),
                    source_type=str(row["source_type"]),
                    research_only=research_only,
                    broker_order_allowed=broker_order_allowed,
                    auto_rebalance_allowed=auto_rebalance_allowed,
                )
                if str(row["schema_version"]) != PAPER_TRADE_LEDGER_SCHEMA_VERSION:
                    raise ValueError("schema_version_mismatch")
                valid.append(fill)
            except (TypeError, ValueError, ArithmeticError) as exc:
                invalid_count += 1
                diagnostics.append(
                    f"paper_trade_ledger_row_invalid:{row['fill_id']}:{type(exc).__name__}"
                )

        if valid:
            dates = sorted(item.event_date for item in valid)
            result["first_date"] = dates[0]
            result["latest_date"] = dates[-1]
            result["total_cost"] = sum(
                (item.total_cost for item in valid), Decimal("0")
            ).quantize(Decimal("0.01"))
        if invalid_count:
            blockers.append("paper_trade_ledger_invalid_row")
            result["status"] = "invalid"
        elif result["missing_turnover_count"] or result["missing_execution_gap_count"]:
            warnings.append("paper_trade_ledger_fields_incomplete")
            result["status"] = "partial"
        else:
            result["status"] = "ready"
        return result

    def _reconcile_status(
        self,
        status_payload: dict[str, Any] | None,
        *,
        latest_snapshot: dict[str, Any] | None,
        blockers: list[str],
        diagnostics: list[str],
    ) -> None:
        if status_payload is None or latest_snapshot is None:
            return
        expected_state = str(self.state_db_path.resolve())
        reported_state = str(status_payload.get("state_db", ""))
        if reported_state and str(Path(reported_state).resolve()) != expected_state:
            blockers.append("paper_daily_status_state_db_path_mismatch")
            diagnostics.append("paper_daily_status_state_db_path_not_opened")
        for payload_key, snapshot_key, blocker in (
            ("snapshot_id", "snapshot_id", "paper_daily_status_snapshot_mismatch"),
            ("decision_date", "decision_date", "paper_daily_status_date_mismatch"),
        ):
            reported_text = str(status_payload.get(payload_key, ""))
            if reported_text and reported_text != str(latest_snapshot[snapshot_key]):
                blockers.append(blocker)
        for payload_key, snapshot_key, blocker in (
            ("cash", "cash", "paper_daily_status_cash_mismatch"),
            ("total_value", "total_value", "paper_daily_status_total_value_mismatch"),
        ):
            reported_value = status_payload.get(payload_key)
            if reported_value is None:
                continue
            try:
                if _decimal(reported_value, payload_key) != latest_snapshot[snapshot_key]:
                    blockers.append(blocker)
            except (TypeError, ValueError):
                blockers.append(f"paper_daily_status_invalid:{payload_key}")


def _overall_status(
    *,
    status_payload: dict[str, Any] | None,
    snapshots: list[dict[str, Any]],
    blockers: tuple[str, ...],
    warnings: tuple[str, ...],
) -> str:
    hard_failure_tokens = (
        "invalid",
        "unavailable",
        "mismatch",
        "boundary_violation",
        "schema_mismatch",
        "future",
    )
    if status_payload is None and not snapshots:
        if any(any(token in item for token in hard_failure_tokens) for item in blockers):
            return "degraded"
        return "not_configured"
    if any(any(token in item for token in hard_failure_tokens) for item in blockers):
        return "degraded"
    if blockers or warnings:
        return "partial"
    return "ready"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must not be bool")
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
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


def _sqlite_safety_flag(value: object, field_name: str) -> bool:
    if isinstance(value, bool) or value not in (0, 1):
        raise ValueError(f"{field_name} must be canonical SQLite boolean 0 or 1")
    return value == 1


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_future_date(value: object, today: date) -> bool:
    """只把合法 ISO 日期與台灣 today 比較；壞日期交由既有 validator 處理。"""

    try:
        parsed = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return parsed > today
