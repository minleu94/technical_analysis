"""受控建立 Paper Portfolio 的 frozen-constituent Equal Weight benchmark。

這個 service 將 benchmark 建置的讀取／驗證／append 邊界放在應用層，讓
CLI 與 Qt 走同一套契約。預覽永遠 query-only；只有明確 ``confirm=True``
才會建立新的 append-only ledger，且既有 output 絕不覆寫。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable, Mapping, Sequence

from app_module.paper_equal_weight_benchmark_ledger import (
    EqualWeightBenchmarkEntry,
    EqualWeightBenchmarkLedger,
    EqualWeightBenchmarkService,
)
from app_module.paper_portfolio_daily_runner import PaperPriceObservation
from app_module.paper_portfolio_time import paper_portfolio_today
from app_module.sqlite_read_only import ReadOnlySQLiteManager


PAPER_EQUAL_WEIGHT_BENCHMARK_BUILD_SCHEMA_VERSION = "paper-equal-weight-benchmark-build.v1"
DEFAULT_PORTFOLIO_ID = "paper-main"
DEFAULT_BENCHMARK_ID = "paper-main-equal"
TodayProvider = Callable[[], date]


@dataclass(frozen=True)
class PaperEqualWeightBenchmarkPreview:
    """不可變的 benchmark 建置預覽；不持有任何 writer connection。"""

    baseline_path: Path
    state_db_path: Path
    market_db_path: Path
    output_ledger_path: Path
    portfolio_id: str
    benchmark_id: str
    entries: tuple[EqualWeightBenchmarkEntry, ...]

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("benchmark preview requires at least one entry")
        if not self.portfolio_id.strip() or not self.benchmark_id.strip():
            raise ValueError("portfolio_id and benchmark_id are required")
        if self.entries[0].benchmark_id != self.benchmark_id:
            raise ValueError("preview benchmark_id does not match entries")

    @property
    def constituent_count(self) -> int:
        return len(self.entries[0].constituents)

    @property
    def constituents(self) -> tuple[str, ...]:
        return self.entries[0].constituents

    @property
    def observation_count(self) -> int:
        return len(self.entries)

    @property
    def first_date(self) -> str:
        return self.entries[0].decision_date

    @property
    def latest_date(self) -> str:
        return self.entries[-1].decision_date

    @property
    def initial_value(self) -> Decimal:
        return self.entries[0].total_value

    @property
    def latest_value(self) -> Decimal:
        return self.entries[-1].total_value

    def to_dict(self, *, status: str = "preview", write_performed: bool = False) -> dict[str, Any]:
        if status not in {"preview", "built"}:
            raise ValueError(f"unsupported benchmark build status: {status}")
        return {
            "schema_version": PAPER_EQUAL_WEIGHT_BENCHMARK_BUILD_SCHEMA_VERSION,
            "status": status,
            "baseline_path": str(self.baseline_path),
            "state_db": str(self.state_db_path),
            "market_db": str(self.market_db_path),
            "output_ledger": str(self.output_ledger_path),
            "portfolio_id": self.portfolio_id,
            "benchmark_id": self.benchmark_id,
            "constituent_count": self.constituent_count,
            "constituents": list(self.constituents),
            "observation_count": self.observation_count,
            "first_date": self.first_date,
            "latest_date": self.latest_date,
            "initial_value": str(self.initial_value),
            "latest_value": str(self.latest_value),
            "research_only": True,
            "writes_market_db": False,
            "broker_order_allowed": False,
            "auto_rebalance_allowed": False,
            "write_performed": write_performed,
        }


class PaperEqualWeightBenchmarkBuilder:
    """建立並在確認後保存 Equal Weight benchmark。"""

    def __init__(
        self,
        *,
        portfolio_id: str = DEFAULT_PORTFOLIO_ID,
        benchmark_id: str = DEFAULT_BENCHMARK_ID,
        today_provider: TodayProvider = paper_portfolio_today,
    ) -> None:
        self.portfolio_id = str(portfolio_id)
        self.benchmark_id = str(benchmark_id)
        self._today_provider = today_provider

    def preview(
        self,
        *,
        baseline_path: str | Path,
        state_db_path: str | Path,
        market_db_path: str | Path,
        output_ledger_path: str | Path,
    ) -> PaperEqualWeightBenchmarkPreview:
        baseline = _resolve_path(baseline_path)
        state_db = _resolve_path(state_db_path)
        market_db = _resolve_path(market_db_path)
        output = _resolve_path(output_ledger_path)
        if output in {baseline, state_db, market_db}:
            raise ValueError("benchmark output must be different from every input path")
        entries = self.build_entries(
            baseline_path=baseline,
            state_db_path=state_db,
            market_db_path=market_db,
        )
        return PaperEqualWeightBenchmarkPreview(
            baseline_path=baseline,
            state_db_path=state_db,
            market_db_path=market_db,
            output_ledger_path=output,
            portfolio_id=self.portfolio_id,
            benchmark_id=self.benchmark_id,
            entries=entries,
        )

    def commit(
        self,
        preview: PaperEqualWeightBenchmarkPreview,
        *,
        confirm: bool = False,
    ) -> Path:
        """重新驗證預覽輸入後建立新的 ledger；不接受隱含寫入。"""
        if not confirm:
            raise ValueError("paper benchmark build requires explicit confirm=True")
        if preview.portfolio_id != self.portfolio_id or preview.benchmark_id != self.benchmark_id:
            raise ValueError("benchmark preview belongs to a different builder identity")
        output = preview.output_ledger_path
        if output.exists():
            raise ValueError(f"output ledger already exists: {output}")

        current = self.preview(
            baseline_path=preview.baseline_path,
            state_db_path=preview.state_db_path,
            market_db_path=preview.market_db_path,
            output_ledger_path=output,
        )
        if current.entries != preview.entries:
            raise ValueError("benchmark inputs changed after preview")
        self.write_new_ledger(output, current.entries)
        return output

    def build_entries(
        self,
        *,
        baseline_path: str | Path,
        state_db_path: str | Path,
        market_db_path: str | Path,
    ) -> tuple[EqualWeightBenchmarkEntry, ...]:
        baseline_date, capital, prices = _baseline_inputs(_read_object(_resolve_path(baseline_path)))
        snapshot_dates = self._snapshot_dates(
            _resolve_path(state_db_path),
        )
        if snapshot_dates[0] != baseline_date:
            raise ValueError(
                "paper snapshot and benchmark baseline require aligned first date: "
                f"{snapshot_dates[0]} != {baseline_date}"
            )
        service = EqualWeightBenchmarkService()
        entries: list[EqualWeightBenchmarkEntry] = [
            service.create_baseline(
                benchmark_id=self.benchmark_id,
                decision_date=baseline_date,
                capital=capital,
                prices=prices,
            )
        ]
        for decision_date in snapshot_dates[1:]:
            observations = self._latest_price_observations(
                _resolve_path(market_db_path),
                symbols=tuple(prices),
                decision_date=decision_date,
            )
            entries.append(
                service.mark(
                    prior=entries[-1],
                    decision_date=decision_date,
                    prices=observations,
                )
            )
        return tuple(entries)

    @staticmethod
    def write_new_ledger(
        path: str | Path,
        entries: tuple[EqualWeightBenchmarkEntry, ...],
    ) -> None:
        output = _resolve_path(path)
        if output.exists():
            raise ValueError(f"output ledger already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{output.stem}.",
            suffix=".tmp.sqlite",
            dir=str(output.parent),
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            ledger = EqualWeightBenchmarkLedger(temporary)
            for entry in entries:
                ledger.append(entry)
            # 目標檔案必須是新檔；Windows rename 在競態時會拒絕覆寫。
            os.rename(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _snapshot_dates(self, state_db: Path) -> tuple[str, ...]:
        if not state_db.is_file():
            raise FileNotFoundError(state_db)
        manager = ReadOnlySQLiteManager(state_db)
        with manager.connect() as conn:
            if not _table_exists(conn, "paper_portfolio_snapshots"):
                raise ValueError("paper snapshot DB is missing paper_portfolio_snapshots")
            rows = conn.execute(
                """
                SELECT decision_date
                FROM paper_portfolio_snapshots
                WHERE portfolio_id = ?
                ORDER BY decision_date, snapshot_id
                """,
                (self.portfolio_id,),
            ).fetchall()
        dates = tuple(_iso_date(row["decision_date"], "snapshot decision_date") for row in rows)
        if len(dates) < 2:
            raise ValueError("paper snapshots require at least two observations")
        if len(set(dates)) != len(dates):
            raise ValueError("paper snapshots require one observation per decision date")
        today = self._today_provider()
        future_dates = sorted({item for item in dates if date.fromisoformat(item) > today})
        if future_dates:
            raise ValueError(
                "paper snapshots contain future-dated observations: "
                + ", ".join(future_dates)
                + f" (today={today.isoformat()})"
            )
        return dates

    def _latest_price_observations(
        self,
        market_db: Path,
        *,
        symbols: Sequence[str],
        decision_date: str,
    ) -> tuple[PaperPriceObservation, ...]:
        if not market_db.is_file():
            raise FileNotFoundError(market_db)
        manager = ReadOnlySQLiteManager(market_db)
        selected: dict[str, tuple[str, Decimal]] = {}
        with manager.connect() as conn:
            if not _table_exists(conn, "daily_prices"):
                raise ValueError("market DB is missing daily_prices")
            columns = {
                str(row[1])
                for row in conn.execute('PRAGMA table_info("daily_prices")').fetchall()
            }
            required = {"證券代號", "日期", "收盤價"}
            if not required.issubset(columns):
                missing = ",".join(sorted(required - columns))
                raise ValueError(f"market DB daily_prices schema mismatch: {missing}")
            for symbol in sorted(set(symbols)):
                rows = conn.execute(
                    """
                    SELECT 日期 AS price_date, 收盤價 AS close
                    FROM daily_prices
                    WHERE 證券代號 = ? AND 收盤價 IS NOT NULL
                    """,
                    (symbol,),
                ).fetchall()
                for row in rows:
                    try:
                        price_date = _iso_date(row["price_date"], "market price date")
                        close = _positive_decimal(row["close"], f"market close {symbol}")
                    except ValueError:
                        continue
                    if price_date >= decision_date:
                        continue
                    prior = selected.get(symbol)
                    if prior is None or price_date > prior[0]:
                        selected[symbol] = (price_date, close)
        missing_symbols = sorted(set(symbols) - set(selected))
        if missing_symbols:
            raise ValueError(
                "missing causal T-1 benchmark prices: " + ",".join(missing_symbols)
            )
        return tuple(
            PaperPriceObservation(symbol, selected[symbol][0], selected[symbol][0], selected[symbol][1])
            for symbol in sorted(set(symbols))
        )


def _resolve_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _read_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("baseline JSON must contain an object")
    return payload


def _iso_date(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be Decimal text") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return parsed


def _positive_decimal(value: object, field_name: str) -> Decimal:
    parsed = _decimal(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _baseline_inputs(payload: Mapping[str, Any]) -> tuple[str, Decimal, dict[str, Decimal]]:
    if payload.get("research_only") is not True:
        raise ValueError("baseline must remain research_only")
    for key in ("writes_positions_db", "broker_order_allowed", "auto_rebalance_allowed"):
        if payload.get(key) is not False:
            raise ValueError(f"baseline safety boundary violated: {key}")
    decision_date = _iso_date(payload.get("decision_date"), "baseline decision_date")
    residual_cash = _decimal(payload.get("residual_cash"), "baseline residual_cash")
    raw_allocations = payload.get("allocations")
    if not isinstance(raw_allocations, list) or not raw_allocations:
        raise ValueError("baseline allocations are required")

    prices: dict[str, Decimal] = {}
    invested_amount = Decimal("0")
    for index, raw in enumerate(raw_allocations, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"allocation {index} must be an object")
        stock_code = str(raw.get("stock_code") or "").strip()
        if not stock_code:
            raise ValueError(f"allocation {index} stock_code is required")
        shares = _integer(raw.get("executable_shares"), f"allocation {index} executable_shares")
        if shares == 0:
            continue
        if stock_code in prices:
            raise ValueError(f"duplicate benchmark constituent: {stock_code}")
        price = _positive_decimal(raw.get("reference_price"), f"allocation {index} reference_price")
        amount = _decimal(
            raw.get("executable_amount", price * shares),
            f"allocation {index} executable_amount",
        )
        if amount <= 0:
            raise ValueError(f"allocation {index} executable_amount must be positive")
        prices[stock_code] = price
        invested_amount += amount

    if not prices:
        raise ValueError("baseline has no executable benchmark constituents")
    capital = (residual_cash + invested_amount).quantize(Decimal("0.01"))
    if capital <= 0:
        raise ValueError("benchmark capital must be positive")
    return decision_date, capital, prices


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


__all__ = [
    "DEFAULT_BENCHMARK_ID",
    "DEFAULT_PORTFOLIO_ID",
    "PAPER_EQUAL_WEIGHT_BENCHMARK_BUILD_SCHEMA_VERSION",
    "PaperEqualWeightBenchmarkBuilder",
    "PaperEqualWeightBenchmarkPreview",
]
