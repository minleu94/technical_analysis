"""Append-only SQLite repository for research paper-portfolio snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class PaperPortfolioPositionSnapshot:
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
            if isinstance(value, bool) or not isinstance(value, Decimal) or value < Decimal("0"):
                raise ValueError(f"{field_name} must be a non-negative Decimal")
        if isinstance(self.weight_bp, bool) or not isinstance(self.weight_bp, int) or not 0 <= self.weight_bp <= 10000:
            raise ValueError("weight_bp must be an integer within 0..10000")


@dataclass(frozen=True)
class PaperPortfolioSnapshot:
    snapshot_id: str
    portfolio_id: str
    decision_date: str
    source_result_id: str
    cash: Decimal
    total_value: Decimal
    positions: tuple[PaperPortfolioPositionSnapshot, ...]

    def __post_init__(self) -> None:
        if not self.snapshot_id or not self.portfolio_id or not self.decision_date:
            raise ValueError("snapshot_id, portfolio_id and decision_date are required")
        for field_name in ("cash", "total_value"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, Decimal) or value < Decimal("0"):
                raise ValueError(f"{field_name} must be a non-negative Decimal")


class PaperPortfolioSnapshotRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def append(self, snapshot: PaperPortfolioSnapshot) -> None:
        try:
            with sqlite3.connect(self._path) as conn:
                conn.execute(
                    "INSERT INTO paper_portfolio_snapshots VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        snapshot.snapshot_id,
                        snapshot.portfolio_id,
                        snapshot.decision_date,
                        snapshot.source_result_id,
                        str(snapshot.cash),
                        str(snapshot.total_value),
                    ),
                )
                conn.executemany(
                    "INSERT INTO paper_portfolio_positions VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        (
                            snapshot.snapshot_id,
                            item.stock_code,
                            item.quantity,
                            str(item.mark_price),
                            str(item.market_value),
                            item.weight_bp,
                        )
                        for item in snapshot.positions
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"snapshot already exists: {snapshot.snapshot_id}") from exc

    def get(self, snapshot_id: str) -> PaperPortfolioSnapshot | None:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM paper_portfolio_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
            if row is None:
                return None
            return self._hydrate(conn, row)

    def list_for_portfolio(self, portfolio_id: str) -> tuple[PaperPortfolioSnapshot, ...]:
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM paper_portfolio_snapshots WHERE portfolio_id = ? ORDER BY decision_date, snapshot_id",
                (portfolio_id,),
            ).fetchall()
            return tuple(self._hydrate(conn, row) for row in rows)

    def _hydrate(self, conn: sqlite3.Connection, row: sqlite3.Row) -> PaperPortfolioSnapshot:
        position_rows = conn.execute(
            "SELECT * FROM paper_portfolio_positions WHERE snapshot_id = ? ORDER BY stock_code",
            (row["snapshot_id"],),
        ).fetchall()
        positions = tuple(
            PaperPortfolioPositionSnapshot(
                stock_code=str(item["stock_code"]),
                quantity=int(item["quantity"]),
                mark_price=Decimal(str(item["mark_price"])),
                market_value=Decimal(str(item["market_value"])),
                weight_bp=int(item["weight_bp"]),
            )
            for item in position_rows
        )
        return PaperPortfolioSnapshot(
            snapshot_id=str(row["snapshot_id"]),
            portfolio_id=str(row["portfolio_id"]),
            decision_date=str(row["decision_date"]),
            source_result_id=str(row["source_result_id"]),
            cash=Decimal(str(row["cash"])),
            total_value=Decimal(str(row["total_value"])),
            positions=positions,
        )

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_portfolio_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    decision_date TEXT NOT NULL,
                    source_result_id TEXT NOT NULL,
                    cash TEXT NOT NULL,
                    total_value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_portfolio_positions (
                    snapshot_id TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    mark_price TEXT NOT NULL,
                    market_value TEXT NOT NULL,
                    weight_bp INTEGER NOT NULL,
                    PRIMARY KEY (snapshot_id, stock_code),
                    FOREIGN KEY (snapshot_id) REFERENCES paper_portfolio_snapshots(snapshot_id)
                );
                """
            )
