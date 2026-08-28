"""受控建立 Paper Portfolio 的 frozen-constituent Equal Weight benchmark。

預設只讀取 baseline、既有 paper snapshot 與正式行情 SQLite，建立 deterministic
preview；只有傳入 ``--confirm-build-paper-benchmark`` 才會在指定 output path
寫入新的 append-only benchmark ledger。這個入口不改市場 DB、不改 Portfolio
snapshot、不呼叫 broker，也不把手動交易當成 benchmark 成交證據。
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_equal_weight_benchmark_ledger import (  # noqa: E402
    EqualWeightBenchmarkEntry,
    EqualWeightBenchmarkLedger,
    EqualWeightBenchmarkService,
)
from app_module.paper_portfolio_daily_runner import PaperPriceObservation  # noqa: E402
from app_module.paper_portfolio_time import paper_portfolio_today  # noqa: E402
from app_module.sqlite_read_only import ReadOnlySQLiteManager  # noqa: E402


SCHEMA_VERSION = "paper-equal-weight-benchmark-build.v1"
PORTFOLIO_ID = "paper-main"
BENCHMARK_ID = "paper-main-equal"


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
            # A rejected/zero-sized candidate is not part of the frozen benchmark universe.
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


def _snapshot_dates(
    state_db: Path,
    *,
    portfolio_id: str,
) -> tuple[str, ...]:
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
            (portfolio_id,),
        ).fetchall()
    dates = tuple(_iso_date(row["decision_date"], "snapshot decision_date") for row in rows)
    if len(dates) < 2:
        raise ValueError("paper snapshots require at least two observations")
    if len(set(dates)) != len(dates):
        raise ValueError("paper snapshots require one observation per decision date")
    today = paper_portfolio_today()
    future_dates = sorted({item for item in dates if date.fromisoformat(item) > today})
    if future_dates:
        raise ValueError(
            "paper snapshots contain future-dated observations: "
            + ", ".join(future_dates)
            + f" (today={today.isoformat()})"
        )
    return dates


def _latest_price_observations(
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


def _build_entries(
    *,
    baseline_path: Path,
    state_db: Path,
    market_db: Path,
    portfolio_id: str,
    benchmark_id: str,
) -> tuple[EqualWeightBenchmarkEntry, ...]:
    baseline_date, capital, prices = _baseline_inputs(_read_object(baseline_path))
    snapshot_dates = _snapshot_dates(state_db, portfolio_id=portfolio_id)
    if snapshot_dates[0] != baseline_date:
        raise ValueError(
            "paper snapshot and benchmark baseline require aligned first date: "
            f"{snapshot_dates[0]} != {baseline_date}"
        )
    service = EqualWeightBenchmarkService()
    entries: list[EqualWeightBenchmarkEntry] = [
        service.create_baseline(
            benchmark_id=benchmark_id,
            decision_date=baseline_date,
            capital=capital,
            prices=prices,
        )
    ]
    for decision_date in snapshot_dates[1:]:
        observations = _latest_price_observations(
            market_db,
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


def _preview_payload(
    *,
    baseline_path: Path,
    state_db: Path,
    market_db: Path,
    output_ledger: Path,
    entries: tuple[EqualWeightBenchmarkEntry, ...],
    portfolio_id: str,
    benchmark_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "preview",
        "baseline_path": str(baseline_path.resolve()),
        "state_db": str(state_db.resolve()),
        "market_db": str(market_db.resolve()),
        "output_ledger": str(output_ledger.resolve()),
        "portfolio_id": portfolio_id,
        "benchmark_id": benchmark_id,
        "constituent_count": len(entries[0].constituents),
        "constituents": list(entries[0].constituents),
        "observation_count": len(entries),
        "first_date": entries[0].decision_date,
        "latest_date": entries[-1].decision_date,
        "initial_value": str(entries[0].total_value),
        "latest_value": str(entries[-1].total_value),
        "research_only": True,
        "writes_market_db": False,
        "broker_order_allowed": False,
        "auto_rebalance_allowed": False,
        "write_performed": False,
    }


def _write_new_ledger(path: Path, entries: tuple[EqualWeightBenchmarkEntry, ...]) -> None:
    if path.exists():
        raise ValueError(f"output ledger already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.",
        suffix=".tmp.sqlite",
        dir=str(path.parent),
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        ledger = EqualWeightBenchmarkLedger(temporary)
        for entry in entries:
            ledger.append(entry)
        # The target is required to be new; Windows rename therefore fails
        # instead of silently replacing a user-created ledger in a race.
        os.rename(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--state-db", type=Path, required=True)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--output-ledger", type=Path, required=True)
    parser.add_argument("--portfolio-id", default=PORTFOLIO_ID)
    parser.add_argument("--benchmark-id", default=BENCHMARK_ID)
    parser.add_argument("--confirm-build-paper-benchmark", action="store_true")
    args = parser.parse_args(argv)

    try:
        entries = _build_entries(
            baseline_path=args.baseline,
            state_db=args.state_db,
            market_db=args.market_db,
            portfolio_id=str(args.portfolio_id),
            benchmark_id=str(args.benchmark_id),
        )
        payload = _preview_payload(
            baseline_path=args.baseline,
            state_db=args.state_db,
            market_db=args.market_db,
            output_ledger=args.output_ledger,
            entries=entries,
            portfolio_id=str(args.portfolio_id),
            benchmark_id=str(args.benchmark_id),
        )
        if args.confirm_build_paper_benchmark:
            _write_new_ledger(args.output_ledger, entries)
            payload["status"] = "built"
            payload["write_performed"] = True
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "rejected",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "research_only": True,
                    "writes_market_db": False,
                    "broker_order_allowed": False,
                    "auto_rebalance_allowed": False,
                    "write_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


def _configure_utf8_stdio() -> None:
    """讓直接執行腳本的 Windows 主控台也能顯示繁中說明與診斷。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 測試 capture stream 或外部 host 管理的 stream 可能禁止重設；
            # 這不應改變 benchmark readiness 結果。
            continue


if __name__ == "__main__":
    raise SystemExit(main())
