"""Broker Flow dashboard 專用的 SQLite 唯讀範圍查詢 repository。"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app_module.broker_flow_dashboard_dtos import (
    BrokerFlowDashboardQuery,
    BrokerFlowLotQuantity,
)
from decision_module.flow_contracts import BrokerFlowEvent


_REQUIRED_COLUMNS = {
    "日期",
    "分點名稱",
    "證券代號",
    "證券名稱",
    "買進股數",
    "賣出股數",
    "買賣超股數",
    "買進金額千元",
    "賣出金額千元",
    "買賣超金額千元",
    "lots_observed",
    "amount_observed",
    "lots_rank",
    "amount_rank",
}


@dataclass(frozen=True)
class BrokerFlowReadSnapshot:
    selected_trading_dates: tuple[date, ...]
    events: tuple[BrokerFlowEvent, ...]
    tracked_branches: tuple[tuple[str, str], ...]
    quality: str
    warnings: tuple[str, ...]
    source_fingerprint: str
    query_count: int
    materialized_row_count: int


class BrokerFlowSQLiteReadRepository:
    """只允許對既有 SQLite 檔執行 query-specific read。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def load_dashboard_source(
        self, query: BrokerFlowDashboardQuery
    ) -> BrokerFlowReadSnapshot:
        return self._load_source(query)

    def load_stock_source(
        self, stock_code: str, query: BrokerFlowDashboardQuery
    ) -> BrokerFlowReadSnapshot:
        return self._load_source(query, stock_code=str(stock_code))

    def load_branch_source(
        self,
        branch_system_key: str,
        query: BrokerFlowDashboardQuery,
        *,
        limit: int,
    ) -> BrokerFlowReadSnapshot:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        return self._load_source(
            query,
            branch_system_key=str(branch_system_key),
            row_limit=limit,
        )

    def _load_source(
        self,
        query: BrokerFlowDashboardQuery,
        *,
        stock_code: str | None = None,
        branch_system_key: str | None = None,
        row_limit: int | None = None,
    ) -> BrokerFlowReadSnapshot:
        if not self.db_path.is_file():
            return self._missing("broker_flow_sqlite_missing", query_count=0)

        try:
            with closing(self._connect()) as connection:
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(broker_flows)")
                }
                if not columns:
                    return self._missing("broker_flows_table_missing", query_count=1)
                missing_columns = sorted(_REQUIRED_COLUMNS - columns)
                if missing_columns:
                    return self._missing(
                        "broker_flows_columns_missing:" + ",".join(missing_columns),
                        query_count=1,
                    )

                selected_dates = self._load_recent_dates(connection, query)
                if not selected_dates:
                    return BrokerFlowReadSnapshot(
                        selected_trading_dates=(),
                        events=(),
                        tracked_branches=(),
                        quality="missing",
                        warnings=("broker_flow_dates_missing_for_as_of",),
                        source_fingerprint=self._source_fingerprint(columns),
                        query_count=2,
                        materialized_row_count=0,
                    )
                rows = self._load_aggregated_rows(
                    connection,
                    selected_dates,
                    stock_code=stock_code,
                    branch_system_key=branch_system_key,
                    row_limit=row_limit,
                )
        except sqlite3.Error as exc:
            return self._missing(
                f"broker_flow_sqlite_read_failed:{type(exc).__name__}",
                query_count=0,
            )

        events: list[BrokerFlowEvent] = []
        warnings: list[str] = []
        for row in rows:
            event, row_warnings = self._row_to_event(row)
            events.append(event)
            warnings.extend(row_warnings)
        unique_warnings = tuple(dict.fromkeys(warnings))
        branches = tuple(
            sorted(
                {
                    (event.branch_system_key, event.branch_display_name)
                    for event in events
                }
            )
        )
        return BrokerFlowReadSnapshot(
            selected_trading_dates=selected_dates,
            events=tuple(events),
            tracked_branches=branches,
            quality="degraded" if unique_warnings else "observed",
            warnings=unique_warnings,
            source_fingerprint=self._source_fingerprint(columns),
            query_count=2,
            materialized_row_count=len(events),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{self.db_path.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        connection.execute("PRAGMA query_only=ON")
        connection.row_factory = sqlite3.Row
        return connection

    def _load_recent_dates(
        self,
        connection: sqlite3.Connection,
        query: BrokerFlowDashboardQuery,
    ) -> tuple[date, ...]:
        rows = connection.execute(
            """
            SELECT DISTINCT 日期 AS date_key
            FROM broker_flows
            WHERE 日期 <= ?
            ORDER BY date_key DESC
            LIMIT ?
            """,
            (
                query.requested_as_of_date.strftime("%Y%m%d"),
                query.period_trading_days,
            ),
        ).fetchall()
        return tuple(
            sorted(datetime.strptime(str(row[0]), "%Y%m%d").date() for row in rows)
        )

    def _load_aggregated_rows(
        self,
        connection: sqlite3.Connection,
        selected_dates: tuple[date, ...],
        *,
        stock_code: str | None,
        branch_system_key: str | None,
        row_limit: int | None,
    ) -> list[sqlite3.Row]:
        date_keys = tuple(item.strftime("%Y%m%d") for item in selected_dates)
        predicates = [
            "日期 IN ("
            + ",".join("?" for _ in date_keys)
            + ")"
        ]
        parameters: list[object] = list(date_keys)
        if stock_code is not None:
            predicates.append("證券代號 = ?")
            parameters.append(stock_code)
        if branch_system_key is not None:
            predicates.append("分點名稱 = ?")
            parameters.append(branch_system_key)

        sql = f"""
            SELECT
                日期 AS date_key,
                分點名稱,
                證券代號,
                MAX(證券名稱) AS 證券名稱,
                SUM(買進股數) AS 買進股數,
                SUM(賣出股數) AS 賣出股數,
                SUM(買賣超股數) AS 買賣超股數,
                SUM(買進金額千元) AS 買進金額千元,
                SUM(賣出金額千元) AS 賣出金額千元,
                SUM(買賣超金額千元) AS 買賣超金額千元,
                MIN(COALESCE(lots_observed, 0)) AS lots_observed,
                MIN(COALESCE(amount_observed, 0)) AS amount_observed,
                MIN(lots_rank) AS lots_rank,
                MIN(amount_rank) AS amount_rank
            FROM broker_flows
            WHERE {' AND '.join(predicates)}
            GROUP BY date_key, 分點名稱, 證券代號
            ORDER BY date_key DESC, ABS(SUM(買賣超股數)) DESC, 證券代號
        """
        if row_limit is not None:
            sql += " LIMIT ?"
            parameters.append(row_limit)
        return connection.execute(sql, tuple(parameters)).fetchall()

    def _row_to_event(
        self, row: sqlite3.Row
    ) -> tuple[BrokerFlowEvent, tuple[str, ...]]:
        buy = BrokerFlowLotQuantity.from_sqlite_shares(row["買進股數"])
        sell = BrokerFlowLotQuantity.from_sqlite_shares(row["賣出股數"])
        net = BrokerFlowLotQuantity.from_sqlite_shares(row["買賣超股數"])
        warnings = tuple(
            dict.fromkeys((*buy.warnings, *sell.warnings, *net.warnings))
        )
        lots_observed = bool(row["lots_observed"])
        if not lots_observed:
            lots_quality = "unavailable"
            buy_qty = sell_qty = net_qty = None
        elif warnings:
            lots_quality = "degraded"
            buy_qty, sell_qty, net_qty = buy.lots, sell.lots, net.lots
        else:
            lots_quality = "observed"
            buy_qty, sell_qty, net_qty = buy.lots, sell.lots, net.lots

        date_value = datetime.strptime(str(row["date_key"]), "%Y%m%d").date()
        branch = str(row["分點名稱"] or "").strip()
        event = BrokerFlowEvent(
            date=date_value.isoformat(),
            branch_system_key=branch,
            branch_display_name=branch,
            stock_code=str(row["證券代號"] or "").strip(),
            stock_name=str(row["證券名稱"] or "").strip(),
            buy_qty=buy_qty,
            sell_qty=sell_qty,
            net_qty=net_qty,
            buy_amount_k_twd=self._optional_int(row["買進金額千元"]),
            sell_amount_k_twd=self._optional_int(row["賣出金額千元"]),
            net_amount_k_twd=self._optional_int(row["買賣超金額千元"]),
            lots_available=lots_quality in {"observed", "degraded"},
            has_estimated_lots=False,
            lots_observed=lots_observed,
            amount_observed=bool(row["amount_observed"]),
            lots_rank=self._optional_int(row["lots_rank"]),
            amount_rank=self._optional_int(row["amount_rank"]),
            lots_quality=lots_quality,
            amount_quality="observed" if bool(row["amount_observed"]) else "unavailable",
        )
        return event, warnings

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, str, bytes, bytearray)):
            return int(value)
        raise ValueError(f"unsupported SQLite integer value: {type(value).__name__}")

    def _source_fingerprint(self, columns: set[str]) -> str:
        stat = self.db_path.stat()
        payload = f"{stat.st_size}:{stat.st_mtime_ns}:{','.join(sorted(columns))}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _missing(self, warning: str, *, query_count: int) -> BrokerFlowReadSnapshot:
        return BrokerFlowReadSnapshot(
            selected_trading_dates=(),
            events=(),
            tracked_branches=(),
            quality="missing",
            warnings=(warning,),
            source_fingerprint="",
            query_count=query_count,
            materialized_row_count=0,
        )


__all__ = ["BrokerFlowReadSnapshot", "BrokerFlowSQLiteReadRepository"]
