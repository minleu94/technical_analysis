"""以嚴格 T-1 行情更新 append-only Paper Portfolio 每日 preopen 估值。

本工具只寫 ``OUTPUT_ROOT/paper_portfolio`` 的研究帳本與排程狀態；正式行情
SQLite 固定以 ``mode=ro`` / ``query_only`` 開啟。snapshot 代表台北 08:30
preopen 的 T-1 mark-to-market 狀態；T+1 session-open Paper transition 由
獨立 producer／ledger 提供。下一個 preopen 會以 `--ledger-db` 唯讀投影已 append
的 research-only transition，再建立新的 snapshot。它不產生調倉、不改 Advice，也
不具任何券商執行能力。
"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.paper_portfolio_daily_runner import (  # noqa: E402
    PaperPortfolioDailyRunner,
    PaperPriceObservation,
)
from app_module.paper_portfolio_snapshot_repository import (  # noqa: E402
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
    PaperPortfolioSnapshotRepository,
)
from app_module.paper_trade_ledger import PaperTradeFill  # noqa: E402
from data_module.config import TWStockConfig  # noqa: E402
from data_module.official_trading_calendar import (  # noqa: E402
    OfficialTradingCalendar,
)
from runtime.console_encoding import configure_utf8_console  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")
PORTFOLIO_ID = "paper-main"
SCHEMA_VERSION = "paper-portfolio-daily-status.v1"
SNAPSHOT_SEMANTICS = "preopen_t_minus_one_mark_to_market"
EXECUTION_TRANSITION_CONTRACT = "t_plus_one_next_official_session_open"
PAPER_EXECUTION_SOURCE_TYPES = frozenset(
    {
        "paper_daily_execution_delayed_eod_replay_v1",
        "paper_daily_execution_v1",
    }
)


def _next_decision_at(
    value: str | None,
    *,
    now: datetime | None = None,
) -> datetime:
    if value is not None:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("--decision-at must include timezone")
        local = parsed.astimezone(TAIPEI)
        if local.timetz().replace(tzinfo=None) != time(8, 30):
            raise ValueError("--decision-at must be Asia/Taipei 08:30")
        return local
    current_raw = now or datetime.now(TAIPEI)
    if current_raw.tzinfo is None or current_raw.utcoffset() is None:
        raise ValueError("now must include timezone")
    current = current_raw.astimezone(TAIPEI)
    candidate = datetime.combine(current.date(), time(8, 30), tzinfo=TAIPEI)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def _latest_reached_decision_at(
    value: str | None,
    *,
    now: datetime | None = None,
) -> datetime:
    """Resolve the latest Taipei 08:30 cutoff that has already occurred.

    Scheduled tasks run before the Taiwan market cutoff on this host.  Using
    the next unreached cutoff would create a future-dated paper snapshot, so
    the writer defaults to the latest reached cutoff instead.  Explicit
    ``--decision-at`` values are preserved and validated by :func:`run`.
    """

    if value is not None:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("--decision-at must include timezone")
        local = parsed.astimezone(TAIPEI)
        if local.timetz().replace(tzinfo=None) != time(8, 30):
            raise ValueError("--decision-at must be Asia/Taipei 08:30")
        return local
    current_raw = now or datetime.now(TAIPEI)
    if current_raw.tzinfo is None or current_raw.utcoffset() is None:
        raise ValueError("now must include timezone")
    current = current_raw.astimezone(TAIPEI)
    candidate = datetime.combine(current.date(), time(8, 30), tzinfo=TAIPEI)
    if candidate > current:
        candidate -= timedelta(days=1)
    return candidate


def _load_mapping(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("paper baseline must be a JSON object")
    return payload


def _baseline_snapshot(payload: Mapping[str, Any]) -> PaperPortfolioSnapshot:
    decision_date = str(payload["decision_date"])
    cash = Decimal(str(payload["residual_cash"]))
    raw_allocations = payload.get("allocations")
    if not isinstance(raw_allocations, list) or not raw_allocations:
        raise ValueError("paper baseline allocations are required")
    raw_positions: list[tuple[str, int, Decimal, Decimal]] = []
    for raw in raw_allocations:
        if not isinstance(raw, Mapping):
            raise ValueError("paper baseline allocation must be an object")
        raw_positions.append(
            (
                str(raw["stock_code"]),
                _non_negative_int(raw["executable_shares"], "executable_shares"),
                Decimal(str(raw["reference_price"])),
                Decimal(str(raw["executable_amount"])),
            )
        )
    total = cash + sum((row[3] for row in raw_positions), Decimal("0"))
    if total <= Decimal("0"):
        raise ValueError("paper baseline total value must be positive")
    positions = tuple(
        PaperPortfolioPositionSnapshot(
            stock_code=symbol,
            quantity=quantity,
            mark_price=price,
            market_value=amount,
            weight_bp=int(
                (amount * Decimal(10_000) / total).to_integral_value(
                    rounding=ROUND_DOWN
                )
            ),
        )
        for symbol, quantity, price, amount in raw_positions
    )
    return PaperPortfolioSnapshot(
        snapshot_id=f"{PORTFOLIO_ID}-{decision_date.replace('-', '')}-baseline",
        portfolio_id=PORTFOLIO_ID,
        decision_date=decision_date,
        source_result_id=str(payload["source_result_id"]),
        cash=cash,
        total_value=total,
        positions=positions,
    )


def _latest_prices(
    database: Path,
    *,
    symbols: Sequence[str],
    decision_date: str,
) -> tuple[PaperPriceObservation, ...]:
    if not database.is_file():
        raise FileNotFoundError(database)
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    observations: list[PaperPriceObservation] = []
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        for symbol in sorted(set(symbols)):
            row = connection.execute(
                """SELECT 日期, 收盤價
                   FROM daily_prices
                   WHERE 證券代號 = ?
                     AND 日期 < ?
                     AND 收盤價 IS NOT NULL
                   ORDER BY 日期 DESC
                   LIMIT 1""",
                (symbol, decision_date.replace("-", "")),
            ).fetchone()
            if row is None:
                raise ValueError(f"missing T-1 price for {symbol}")
            price_date = _iso_date_text(str(row[0]))
            observations.append(
                PaperPriceObservation(
                    stock_code=symbol,
                    price_date=price_date,
                    available_date=price_date,
                    close=Decimal(str(row[1])),
                )
            )
    return tuple(observations)


def _project_paper_ledger_transitions(
    prior: PaperPortfolioSnapshot,
    *,
    ledger_db: Path | None,
    before_date: str,
) -> tuple[PaperPortfolioSnapshot, tuple[str, ...]]:
    """把已驗證的 EOD Paper transition 投影到下一個 preopen 起始狀態。

    EOD writer 不回寫當日 preopen snapshot。下一個自然日建立 snapshot 時，
    才以唯讀 ledger 讀取 ``prior.decision_date <= event_date < before_date``
    的成交，重算現金與股數；ledger 內容／hash 若在讀取期間變動則 fail closed。
    """

    if ledger_db is None:
        return prior, ()
    resolved = ledger_db.expanduser().resolve()
    if not resolved.exists():
        return prior, ()
    if not resolved.is_file():
        raise ValueError("paper ledger transition path is not a file")
    before_hash = _sha256_file(resolved)
    uri = f"file:{resolved.as_posix()}?mode=ro"
    required = {
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
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            columns = {
                str(row[1])
                for row in connection.execute('PRAGMA table_info("paper_trade_ledger")')
            }
            if not required.issubset(columns):
                raise ValueError("paper trade ledger schema is incomplete")
            rows = connection.execute(
                "SELECT * FROM paper_trade_ledger "
                "WHERE portfolio_id = ? AND event_date >= ? AND event_date < ? "
                "ORDER BY event_date, fill_id",
                (prior.portfolio_id, prior.decision_date, before_date),
            ).fetchall()
            fills = tuple(_paper_fill_from_row(row) for row in rows)
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        raise ValueError(
            f"paper ledger transition read failed:{type(error).__name__}:{error}"
        ) from error
    after_hash = _sha256_file(resolved)
    if before_hash != after_hash:
        raise ValueError("paper ledger changed during read")
    if not fills:
        return prior, ()

    cash = prior.cash.quantize(Decimal("0.01"))
    quantities = {item.stock_code: item.quantity for item in prior.positions}
    marks = {item.stock_code: item.mark_price for item in prior.positions}
    diagnostics: list[str] = []
    for fill in fills:
        if fill.source_type not in PAPER_EXECUTION_SOURCE_TYPES:
            raise ValueError(
                f"paper ledger transition source is unsupported:{fill.source_type}"
            )
        if fill.portfolio_id != prior.portfolio_id:
            raise ValueError("paper ledger transition portfolio is invalid")
        if fill.filled_quantity == 0:
            diagnostics.append(f"paper_ledger_transition_applied:{fill.fill_id}:zero_fill")
            continue
        current = quantities.get(fill.stock_code, 0)
        # fill_price 已含 tick slippage；gross 已反映該價格，現金只再結算
        # commission + tax。total_cost 仍保留 slippage 歸因，不能重扣。
        settlement_cost = fill.cash_settlement_cost
        if fill.side == "buy":
            quantities[fill.stock_code] = current + fill.filled_quantity
            cash = (cash - fill.gross_amount - settlement_cost).quantize(Decimal("0.01"))
        elif fill.side == "sell":
            if fill.filled_quantity > current:
                raise ValueError(f"paper ledger sell exceeds holding:{fill.fill_id}")
            quantities[fill.stock_code] = current - fill.filled_quantity
            cash = (cash + fill.gross_amount - settlement_cost).quantize(Decimal("0.01"))
        else:  # pragma: no cover - PaperTradeFill validates this
            raise ValueError(f"paper ledger side is invalid:{fill.fill_id}")
        if cash < Decimal("0"):
            raise ValueError("paper ledger transition cash is negative")
        if fill.fill_price is not None:
            marks[fill.stock_code] = fill.fill_price
        diagnostics.append(f"paper_ledger_transition_applied:{fill.fill_id}")

    positions = tuple(
        PaperPortfolioPositionSnapshot(
            stock_code=symbol,
            quantity=quantity,
            mark_price=marks[symbol],
            market_value=(marks[symbol] * quantity).quantize(Decimal("0.01")),
            weight_bp=0,
        )
        for symbol, quantity in sorted(quantities.items())
        if quantity > 0
    )
    total = (cash + sum((item.market_value for item in positions), Decimal("0"))).quantize(
        Decimal("0.01")
    )
    if total <= Decimal("0"):
        raise ValueError("paper ledger transition total value is invalid")
    projected = PaperPortfolioSnapshot(
        snapshot_id=prior.snapshot_id,
        portfolio_id=prior.portfolio_id,
        decision_date=prior.decision_date,
        source_result_id=prior.source_result_id,
        cash=cash,
        total_value=total,
        positions=positions,
    )
    return projected, tuple(diagnostics)


def _paper_fill_from_row(row: sqlite3.Row) -> PaperTradeFill:
    return PaperTradeFill(
        fill_id=str(row["fill_id"]),
        order_id=str(row["order_id"]),
        portfolio_id=str(row["portfolio_id"]),
        event_date=str(row["event_date"]),
        stock_code=str(row["stock_code"]),
        side=str(row["side"]),
        requested_quantity=int(row["requested_quantity"]),
        filled_quantity=int(row["filled_quantity"]),
        reference_price=Decimal(str(row["reference_price"])),
        fill_price=(None if row["fill_price"] is None else Decimal(str(row["fill_price"]))),
        commission=Decimal(str(row["commission"])),
        tax=Decimal(str(row["tax"])),
        slippage_cost=Decimal(str(row["slippage_cost"])),
        turnover_bp=(None if row["turnover_bp"] is None else int(row["turnover_bp"])),
        execution_gap_bp=(
            None if row["execution_gap_bp"] is None else int(row["execution_gap_bp"])
        ),
        status=str(row["status"]),
        source_event_id=str(row["source_event_id"]),
        override_reason=(None if row["override_reason"] is None else str(row["override_reason"])),
        source_type=str(row["source_type"]),
        research_only=bool(row["research_only"]),
        broker_order_allowed=bool(row["broker_order_allowed"]),
        auto_rebalance_allowed=bool(row["auto_rebalance_allowed"]),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    *,
    baseline_path: Path,
    state_db: Path,
    market_db: Path,
    output_root: Path,
    decision_at: datetime,
    calendar: OfficialTradingCalendar | None = None,
    now: datetime | None = None,
    ledger_db: Path | None = None,
) -> dict[str, Any]:
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("decision_at must include timezone")
    decision_at = decision_at.astimezone(TAIPEI)
    if decision_at.timetz().replace(tzinfo=None) != time(8, 30):
        raise ValueError("decision_at must be Asia/Taipei 08:30")

    checked_raw = now or datetime.now(TAIPEI)
    if checked_raw.tzinfo is None or checked_raw.utcoffset() is None:
        raise ValueError("now must include timezone")
    checked_at = checked_raw.astimezone(TAIPEI)

    status_path = (
        output_root
        / "scheduled"
        / "paper_portfolio_daily"
        / "latest_status.json"
    )
    if decision_at > checked_at:
        future_status: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": "skipped_future_decision",
            "decision_at": decision_at.isoformat(timespec="seconds"),
            "decision_date": decision_at.date().isoformat(),
            "checked_at": checked_at.isoformat(timespec="seconds"),
            "snapshot_semantics": SNAPSHOT_SEMANTICS,
            "execution_transition_contract": EXECUTION_TRANSITION_CONTRACT,
            "trading_calendar_validated": False,
            "trading_calendar_is_open": None,
            "trading_calendar_reason": "decision_at_not_reached",
            "snapshot_appended": False,
            "skipped_duplicate": False,
            "diagnostics": [
                "future_decision_at:"
                f"{decision_at.isoformat(timespec='seconds')}:"
                f"checked_at={checked_at.isoformat(timespec='seconds')}"
            ],
            "state_db": str(state_db.resolve()),
            "market_db_mode": "not_opened",
            "writes_market_db": False,
            "auto_rebalance_allowed": False,
            "changes_advice": False,
            "broker_execution": False,
        }
        _atomic_write_json(status_path, future_status)
        return future_status

    calendar_service = calendar or OfficialTradingCalendar(db_path=market_db)
    try:
        is_trading_day, calendar_reason = (
            calendar_service.is_official_trading_day(decision_at.date())
        )
    except Exception as exc:  # noqa: BLE001 - 排程必須持久化未知日曆狀態
        is_trading_day = None
        calendar_reason = f"calendar_exception:{type(exc).__name__}"
    if is_trading_day is not True:
        calendar_status: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": (
                "skipped_non_trading_day"
                if is_trading_day is False
                else "degraded_calendar_unknown"
            ),
            "decision_at": decision_at.isoformat(timespec="seconds"),
            "decision_date": decision_at.date().isoformat(),
            "snapshot_semantics": SNAPSHOT_SEMANTICS,
            "execution_transition_contract": EXECUTION_TRANSITION_CONTRACT,
            "trading_calendar_validated": is_trading_day is False,
            "trading_calendar_is_open": is_trading_day,
            "trading_calendar_reason": calendar_reason,
            "snapshot_appended": False,
            "skipped_duplicate": False,
            "diagnostics": [
                (
                    f"official_market_closed:{calendar_reason}"
                    if is_trading_day is False
                    else f"trading_calendar_unknown:{calendar_reason}"
                )
            ],
            "state_db": str(state_db.resolve()),
            "market_db_mode": "not_opened",
            "writes_market_db": False,
            "auto_rebalance_allowed": False,
            "changes_advice": False,
            "broker_execution": False,
        }
        _atomic_write_json(status_path, calendar_status)
        return calendar_status

    repository = PaperPortfolioSnapshotRepository(state_db)
    baseline = _baseline_snapshot(_load_mapping(baseline_path))
    if repository.get(baseline.snapshot_id) is None:
        repository.append(baseline)

    existing = repository.list_for_portfolio(PORTFOLIO_ID)
    if not existing:
        raise RuntimeError("paper portfolio baseline was not initialized")
    prior = existing[-1]
    decision_date = decision_at.date().isoformat()
    snapshot_id = f"{PORTFOLIO_ID}-{decision_date.replace('-', '')}"
    duplicate = repository.get(snapshot_id)
    diagnostics: tuple[str, ...]
    ledger_diagnostics: tuple[str, ...] = ()
    if duplicate is not None:
        result_snapshot = duplicate
        diagnostics = ("snapshot_already_exists",)
        appended = False
    else:
        if prior.decision_date >= decision_date:
            raise ValueError("decision date must be after the latest paper snapshot")
        prior, ledger_diagnostics = _project_paper_ledger_transitions(
            prior,
            ledger_db=ledger_db,
            before_date=decision_date,
        )
        observations = _latest_prices(
            market_db,
            symbols=tuple(row.stock_code for row in prior.positions),
            decision_date=decision_date,
        )
        result = PaperPortfolioDailyRunner().run(
            prior=prior,
            decision_date=decision_date,
            prices=observations,
        )
        result_snapshot = result.snapshot
        repository.append(result_snapshot)
        diagnostics = ledger_diagnostics + result.diagnostics
        appended = True

    status: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "decision_at": decision_at.isoformat(timespec="seconds"),
        "decision_date": decision_date,
        "snapshot_semantics": SNAPSHOT_SEMANTICS,
        "execution_transition_contract": EXECUTION_TRANSITION_CONTRACT,
        "trading_calendar_validated": True,
        "trading_calendar_is_open": True,
        "trading_calendar_reason": calendar_reason,
        "portfolio_id": result_snapshot.portfolio_id,
        "snapshot_id": result_snapshot.snapshot_id,
        "source_result_id": result_snapshot.source_result_id,
        "position_count": len(result_snapshot.positions),
        "cash": str(result_snapshot.cash),
        "total_value": str(result_snapshot.total_value),
        "snapshot_appended": appended,
        "skipped_duplicate": not appended,
        "diagnostics": list(diagnostics),
        "paper_ledger_db": (
            None if ledger_db is None else str(ledger_db.expanduser().resolve())
        ),
        "paper_ledger_transitions_applied": sum(
            item.startswith("paper_ledger_transition_applied:") for item in diagnostics
        ),
        "state_db": str(state_db.resolve()),
        "market_db_mode": "ro/query_only",
        "writes_market_db": False,
        "auto_rebalance_allowed": False,
        "changes_advice": False,
        "broker_execution": False,
    }
    _atomic_write_json(
        status_path,
        status,
    )
    return status


def _iso_date_text(value: str) -> str:
    normalized = value.strip()
    if len(normalized) == 8 and normalized.isdigit():
        return f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    return datetime.fromisoformat(normalized[:10]).date().isoformat()


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    # argparse renders the Chinese module docstring for ``--help`` before any
    # work starts; configure the Windows console first so cp1252 hosts do not
    # fail before the paper runner can report its guarded status.
    configure_utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--state-db", type=Path)
    parser.add_argument("--market-db", type=Path)
    parser.add_argument(
        "--ledger-db",
        type=Path,
        help="已 append-only Paper fill ledger；只讀投影至下一個 preopen snapshot",
    )
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--decision-at")
    args = parser.parse_args(argv)

    config = TWStockConfig(
        output_root=args.output_root
        or Path(os.environ.get("OUTPUT_ROOT", "D:/Min/Python/Project/FA_Data/output"))
    )
    output_root = config.output_root
    baseline = args.baseline or output_root / "paper_portfolio" / "baseline_20260712.json"
    state_db = args.state_db or output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    market_db = args.market_db or config.db_file
    ledger_db = args.ledger_db or (
        Path(os.environ["PAPER_EXECUTION_LEDGER_DB"])
        if os.environ.get("PAPER_EXECUTION_LEDGER_DB")
        else output_root / "paper_portfolio" / "paper_trade_ledger.sqlite"
    )
    try:
        payload = run(
            baseline_path=baseline,
            state_db=state_db,
            market_db=market_db,
            output_root=output_root,
            decision_at=_latest_reached_decision_at(args.decision_at),
            ledger_db=ledger_db,
        )
    except Exception as exc:
        failed = {
            "schema_version": SCHEMA_VERSION,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "writes_market_db": False,
            "auto_rebalance_allowed": False,
            "changes_advice": False,
            "broker_execution": False,
        }
        _atomic_write_json(
            output_root
            / "scheduled"
            / "paper_portfolio_daily"
            / "latest_status.json",
            failed,
        )
        print(json.dumps(failed, ensure_ascii=False, sort_keys=True, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if payload["status"] in {"passed", "skipped_non_trading_day"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
