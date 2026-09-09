"""唯讀接線：把真實 Paper ledger 狀態交給紙上投資組合政策。

``PaperPortfolioPolicy`` 本身只接受已整理好的 bp 欄位。這個 adapter 負責
在 Formal／Paper consumer 邊界讀取 repository ledger，計算本週已用 turnover、
每檔股票最近一次真實 fill 與交易日 cooldown，並從 caller 提供的同日持倉／
官方 sector mapping 計算 sector exposure。缺少來源或官方交易日資料時回傳
``unknown``／``blocked``，不把缺資料當成 0，也不會建立 SQLite schema 或寫入
任何資料。

預設同日 ledger rows 會被驗證但不納入決策狀態，避免在決策時計入尚未可取得的
同日成交；execution EOD consumer 可明確開啟同日 rows，並以 exact fill identity
排除本次重試已寫入的 immutable rows。只有 ``filled``／``partially_filled`` 且有整數
turnover 的 rows 才會增加週 turnover 或更新 cooldown。所有百分點使用整數 bp，金額與檔案內容不
經過裸 ``float`` 計算。批次 reservation 不會先把預期賣款放回現金；sector
projection 也只是候選排序用的暫時診斷。partial／rejected sell 只有在實際
execution readback 證明結算後，才可由 execution owner 重新核對可用現金與
sector exposure。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Literal

from app_module.paper_portfolio_policy import (
    PaperPortfolioAction,
    PaperPortfolioDecision,
    PaperPortfolioPolicy,
    PaperPortfolioPolicyConfig,
    PaperPortfolioRebalanceInput,
)


AdapterStatus = Literal["ready", "blocked", "unknown"]
_EXECUTED_STATUSES = frozenset({"filled", "partially_filled"})
_NON_EXECUTED_STATUSES = frozenset({"rejected", "cancelled"})
_REQUIRED_COLUMNS = frozenset(
    {
        "fill_id",
        "portfolio_id",
        "event_date",
        "stock_code",
        "requested_quantity",
        "filled_quantity",
        "turnover_bp",
        "status",
    }
)
_TOTAL_WEIGHT_BP = 10_000


def _validate_bp(field_name: str, value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _TOTAL_WEIGHT_BP
    ):
        raise ValueError(f"{field_name} must be an integer bp value between 0 and 10000")


def _row_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("ledger event_date must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("ledger event_date must be an ISO date string") from exc
    if parsed.isoformat() != value:
        raise ValueError("ledger event_date must use YYYY-MM-DD")
    return parsed


def _row_int(field_name: str, value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"ledger {field_name} must be an integer >= {minimum}")
    return value


def _row_text(field_name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"ledger {field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True)
class PaperPortfolioPolicyContext:
    """同一決策日已驗證的持倉、sector 與官方交易日來源。"""

    decision_date: date
    current_cash_bp: int
    current_weights_bp: Mapping[str, int]
    sector_by_symbol: Mapping[str, str]
    official_trading_days: tuple[date, ...]
    ledger_history_start: date
    official_calendar_coverage_start: date
    official_calendar_coverage_end: date
    official_calendar_source_hash: str
    official_calendar_complete: bool
    portfolio_id: str = "paper-main"
    snapshot_id: str = ""
    # Generic callers keep the pre-decision view. Delayed EOD execution
    # enables same-session rows so a second candidate sees prior fills, while
    # exact replay rows are excluded by immutable identity and checked again
    # by the producer's append/readback contract.
    include_decision_date_rows: bool = False
    ignored_fill_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.decision_date, date):
            raise ValueError("decision_date must be a date")
        _validate_bp("current_cash_bp", self.current_cash_bp)
        if not self.portfolio_id.strip():
            raise ValueError("portfolio_id is required")
        if not isinstance(self.ledger_history_start, date):
            raise ValueError("ledger_history_start must be a date")
        if self.ledger_history_start > self.decision_date:
            raise ValueError("ledger_history_start cannot be after decision_date")
        if self.official_calendar_coverage_start > self.ledger_history_start:
            raise ValueError("official calendar coverage starts after ledger history")
        if self.official_calendar_coverage_end < self.decision_date:
            raise ValueError("official calendar coverage ends before decision date")
        if not self.official_calendar_source_hash.startswith("sha256:"):
            raise ValueError("official_calendar_source_hash must be hash-bound")
        if self.official_calendar_complete is not True:
            raise ValueError("official_calendar_complete must be True")
        if not isinstance(self.include_decision_date_rows, bool):
            raise ValueError("include_decision_date_rows must be a boolean")
        if tuple(sorted(set(self.ignored_fill_ids))) != self.ignored_fill_ids:
            raise ValueError("ignored_fill_ids must be sorted and unique")
        for fill_id in self.ignored_fill_ids:
            if not isinstance(fill_id, str) or not fill_id.strip():
                raise ValueError("ignored_fill_ids must contain non-empty text")
        if not self.official_trading_days:
            raise ValueError("official_trading_days is required")
        days = tuple(self.official_trading_days)
        if any(not isinstance(item, date) for item in days):
            raise ValueError("official_trading_days must contain dates")
        if tuple(sorted(set(days))) != days:
            raise ValueError("official_trading_days must be sorted and unique")
        for symbol, weight in self.current_weights_bp.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("current_weights_bp contains an empty symbol")
            _validate_bp(f"current weight {symbol}", weight)
        if sum(self.current_weights_bp.values()) > _TOTAL_WEIGHT_BP:
            raise ValueError("current portfolio weights exceed 10000 bp")
        for symbol, sector in self.sector_by_symbol.items():
            if (
                not isinstance(symbol, str)
                or not symbol.strip()
                or not isinstance(sector, str)
                or not sector.strip()
            ):
                raise ValueError("sector_by_symbol must contain non-empty symbol and sector")


@dataclass(frozen=True)
class PaperPolicyCandidate:
    stock_code: str
    target_weight_bp: int
    current_weight_bp: int | None = None

    def __post_init__(self) -> None:
        if not self.stock_code.strip():
            raise ValueError("stock_code is required")
        _validate_bp("target_weight_bp", self.target_weight_bp)
        if self.current_weight_bp is not None:
            _validate_bp("current_weight_bp", self.current_weight_bp)


@dataclass(frozen=True)
class PaperPortfolioPolicyState:
    """Ledger-derived state used by one decision date."""

    portfolio_id: str
    decision_date: date
    week_start: date
    weekly_turnover_used_bp: int
    last_trade_date_by_symbol: Mapping[str, date]
    trading_days_since_last_trade_by_symbol: Mapping[str, int]
    sector_weights_bp: Mapping[str, int]
    ledger_rows_read: int
    future_rows_excluded: int
    ledger_rows_sha256: str
    ledger_data_version: int
    official_calendar_source_hash: str
    portfolio_weight_sum_bp: int


@dataclass(frozen=True)
class PaperPortfolioPolicyAdapterResult:
    status: AdapterStatus
    decision: PaperPortfolioDecision | None = None
    state: PaperPortfolioPolicyState | None = None
    blockers: tuple[str, ...] = ()
    reservation_weekly_turnover_used_bp: int | None = None
    projected_sector_weight_after_bp: int | None = None


@dataclass(frozen=True)
class PaperPortfolioPolicyBatchResult:
    """一次性評估結果；每筆通過候選都會保留 turnover reservation。"""

    status: AdapterStatus
    results: tuple[PaperPortfolioPolicyAdapterResult, ...] = ()
    state: PaperPortfolioPolicyState | None = None
    blockers: tuple[str, ...] = ()
    cash_reservation_semantics: str = "sell_proceeds_not_released_until_actual_fill"
    sector_reservation_semantics: str = (
        "sell_exposure_not_released_until_actual_fill_readback"
    )


@dataclass(frozen=True)
class _LedgerReadSnapshot:
    rows: tuple[sqlite3.Row, ...]
    rows_sha256: str
    data_version: int


def _canonical_rows_sha256(rows: tuple[sqlite3.Row, ...]) -> str:
    digest = sha256()
    fields = (
        "fill_id",
        "portfolio_id",
        "event_date",
        "stock_code",
        "requested_quantity",
        "filled_quantity",
        "turnover_bp",
        "status",
    )
    for row in rows:
        for field in fields:
            value = row[field]
            encoded = ("" if value is None else str(value)).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return f"sha256:{digest.hexdigest()}"


class PaperPortfolioPolicyAdapter:
    """把真實 ledger 以 read-only 方式接到既有政策 evaluator。"""

    def __init__(
        self,
        ledger_path: str | Path,
        config: PaperPortfolioPolicyConfig | None = None,
    ) -> None:
        self._ledger_path = Path(ledger_path).expanduser().resolve()
        self._config = config or PaperPortfolioPolicyConfig()
        self._policy = PaperPortfolioPolicy(self._config)

    @property
    def ledger_path(self) -> Path:
        return self._ledger_path

    def inspect(self, context: PaperPortfolioPolicyContext) -> PaperPortfolioPolicyAdapterResult:
        """讀取 ledger 並計算週 turnover、cooldown 與 sector exposure。"""

        calendar_blocker = self._calendar_blocker(context)
        if calendar_blocker is not None:
            return self._result("unknown", calendar_blocker)
        missing_sector = self._missing_sector_symbols(context, ())
        if missing_sector:
            return self._result(
                "unknown",
                "sector_mapping_missing:" + ",".join(missing_sector),
            )

        if not self._ledger_path.is_file():
            return self._result("unknown", "ledger_source_missing")
        try:
            snapshot = self._read_rows(context.portfolio_id)
            rows = snapshot.rows
        except (OSError, sqlite3.Error) as exc:
            return self._result("unknown", f"ledger_read_failed:{type(exc).__name__}")
        except ValueError as exc:
            return self._result("blocked", str(exc))
        calendar_days = set(context.official_trading_days)
        week_start = context.decision_date - timedelta(
            days=context.decision_date.weekday()
        )
        last_trade: dict[str, date] = {}
        future_rows = 0
        blockers: list[str] = []
        for row in rows:
            try:
                event_date = _row_date(row["event_date"])
                if event_date > context.decision_date or (
                    event_date == context.decision_date
                    and not context.include_decision_date_rows
                ):
                    future_rows += 1
                    continue
                fill_id = _row_text("fill_id", row["fill_id"])
                symbol = _row_text("stock_code", row["stock_code"])
                status = _row_text("status", row["status"])
                requested = _row_int("requested_quantity", row["requested_quantity"], minimum=1)
                filled = _row_int("filled_quantity", row["filled_quantity"])
                if filled > requested:
                    raise ValueError(f"ledger filled_quantity exceeds requested_quantity:{fill_id}")
                if status not in _EXECUTED_STATUSES | _NON_EXECUTED_STATUSES:
                    raise ValueError(f"ledger unsupported status:{status}")
                if event_date < context.ledger_history_start:
                    raise ValueError(f"ledger row predates declared history:{fill_id}")
                if event_date not in calendar_days:
                    raise ValueError(f"ledger event date missing official calendar:{event_date}")
                turnover = row["turnover_bp"]
                if status in _EXECUTED_STATUSES:
                    if filled <= 0:
                        raise ValueError(f"executed ledger row has no filled quantity:{fill_id}")
                    if isinstance(turnover, bool) or not isinstance(turnover, int):
                        raise ValueError(f"executed ledger row missing integer turnover:{fill_id}")
                    _validate_bp("ledger turnover_bp", turnover)
                elif filled != 0:
                    raise ValueError(f"non-executed ledger row has filled quantity:{fill_id}")
            except (KeyError, TypeError) as exc:
                return self._result("unknown", f"ledger_schema_value_missing:{type(exc).__name__}")
            except ValueError as exc:
                blockers.append(str(exc))
                continue

            if fill_id in context.ignored_fill_ids:
                continue
            if status not in _EXECUTED_STATUSES:
                continue
            previous = last_trade.get(symbol)
            if previous is None or event_date > previous:
                last_trade[symbol] = event_date

        if blockers:
            return self._result("blocked", *tuple(sorted(set(blockers))))

        # Recompute the weekly value from the validated pre-decision rows so
        # the state cannot accidentally include a row outside the ISO week.
        weekly_turnover = self._weekly_turnover(
            rows=rows,
            context=context,
            week_start=week_start,
        )
        cooldowns = {
            symbol: self._cooldown_days(
                last_trade_date=trade_date,
                decision_date=context.decision_date,
                official_days=context.official_trading_days,
            )
            for symbol, trade_date in last_trade.items()
        }
        sector_weights: dict[str, int] = {}
        for symbol, weight in context.current_weights_bp.items():
            sector = context.sector_by_symbol[symbol].strip()
            sector_weights[sector] = sector_weights.get(sector, 0) + weight

        return PaperPortfolioPolicyAdapterResult(
            status="ready",
            state=PaperPortfolioPolicyState(
                portfolio_id=context.portfolio_id,
                decision_date=context.decision_date,
                week_start=week_start,
                weekly_turnover_used_bp=weekly_turnover,
                last_trade_date_by_symbol=dict(last_trade),
                trading_days_since_last_trade_by_symbol=cooldowns,
                sector_weights_bp=sector_weights,
                ledger_rows_read=len(rows),
                future_rows_excluded=future_rows,
                ledger_rows_sha256=snapshot.rows_sha256,
                ledger_data_version=snapshot.data_version,
                official_calendar_source_hash=context.official_calendar_source_hash,
                portfolio_weight_sum_bp=sum(context.current_weights_bp.values()),
            ),
        )

    def evaluate(
        self,
        context: PaperPortfolioPolicyContext,
        candidate: PaperPolicyCandidate,
    ) -> PaperPortfolioPolicyAdapterResult:
        """用 ledger-derived state 評估單一候選；缺來源時不猜測。"""

        batch = self.evaluate_batch(context, (candidate,))
        if not batch.results:
            return PaperPortfolioPolicyAdapterResult(
                status=batch.status,
                state=batch.state,
                blockers=batch.blockers,
            )
        return batch.results[0]

    def evaluate_batch(
        self,
        context: PaperPortfolioPolicyContext,
        candidates: tuple[PaperPolicyCandidate, ...],
    ) -> PaperPortfolioPolicyBatchResult:
        """一次讀取 state，逐筆保留通過候選的 turnover／sector reservation。"""

        state_result = self.inspect(context)
        if state_result.status != "ready" or state_result.state is None:
            return PaperPortfolioPolicyBatchResult(
                status=state_result.status,
                state=state_result.state,
                blockers=state_result.blockers,
            )
        if not candidates:
            return PaperPortfolioPolicyBatchResult(
                status="ready",
                state=state_result.state,
            )

        projected_weights = dict(context.current_weights_bp)
        projected_sector_weights = dict(state_result.state.sector_weights_bp)
        projected_cash_bp = context.current_cash_bp
        reserved_turnover = state_result.state.weekly_turnover_used_bp
        results: list[PaperPortfolioPolicyAdapterResult] = []
        reserved_symbols: set[str] = set()
        for candidate in candidates:
            if candidate.stock_code not in context.sector_by_symbol:
                results.append(
                    self._result("unknown", f"sector_mapping_missing:{candidate.stock_code}")
                )
                continue
            if candidate.stock_code in reserved_symbols:
                results.append(self._result("blocked", "duplicate_candidate_symbol"))
                continue
            current_weight = projected_weights.get(candidate.stock_code, 0)
            if (
                candidate.current_weight_bp is not None
                and candidate.current_weight_bp != current_weight
            ):
                results.append(self._result("blocked", "candidate_current_weight_mismatch"))
                continue
            sector = context.sector_by_symbol[candidate.stock_code].strip()
            # Evaluate this candidate's eventual target independently so a
            # corrective sell can still be proposed when the current exposure
            # is already above cap.  The batch reservation deliberately keeps
            # the current sell exposure until actual fill readback; only a
            # positive buy delta reserves additional sector weight.
            sector_after = (
                projected_sector_weights.get(sector, 0)
                - current_weight
                + candidate.target_weight_bp
            )
            sector_reservation_after = projected_sector_weights.get(sector, 0) + max(
                candidate.target_weight_bp - current_weight,
                0,
            )
            if not 0 <= sector_after <= _TOTAL_WEIGHT_BP:
                results.append(self._result("blocked", "sector_weight_after_out_of_range"))
                continue
            if reserved_turnover > _TOTAL_WEIGHT_BP:
                results.append(self._result("blocked", "weekly_turnover_state_out_of_range"))
                continue
            cooldown = state_result.state.trading_days_since_last_trade_by_symbol.get(
                candidate.stock_code,
                self._config.same_symbol_cooldown_trading_days,
            )
            decision = self._policy.evaluate(
                PaperPortfolioRebalanceInput(
                    stock_code=candidate.stock_code,
                    current_weight_bp=current_weight,
                    target_weight_bp=candidate.target_weight_bp,
                    current_cash_bp=projected_cash_bp,
                    sector_weight_after_bp=sector_after,
                    weekly_turnover_used_bp=reserved_turnover,
                    trading_days_since_last_trade=cooldown,
                )
            )
            if (
                decision.action is PaperPortfolioAction.PAPER_TRADE_CANDIDATE
                and projected_cash_bp - max(decision.weight_gap_bp, 0)
                < self._config.minimum_cash_bp
            ):
                decision = PaperPortfolioDecision(
                    action=PaperPortfolioAction.NO_PAPER_TRADE,
                    weight_gap_bp=decision.weight_gap_bp,
                    estimated_round_trip_cost_bp=decision.estimated_round_trip_cost_bp,
                    reasons=("minimum_cash_reserve_after_batch_reservation",),
                )
            result = PaperPortfolioPolicyAdapterResult(
                status="ready",
                decision=decision,
                state=state_result.state,
                reservation_weekly_turnover_used_bp=reserved_turnover,
                projected_sector_weight_after_bp=sector_reservation_after,
            )
            results.append(result)
            if decision.action is PaperPortfolioAction.PAPER_TRADE_CANDIDATE:
                gap = decision.weight_gap_bp
                reserved_turnover += abs(gap)
                reserved_symbols.add(candidate.stock_code)
                projected_weights[candidate.stock_code] = candidate.target_weight_bp
                projected_sector_weights[sector] = sector_reservation_after
                if gap > 0:
                    # A buy reservation consumes cash. A proposed sell does
                    # not release cash until a later execution readback proves
                    # its filled quantity and settlement.
                    projected_cash_bp -= gap

        status: AdapterStatus = "ready"
        if any(item.status == "blocked" for item in results):
            status = "blocked"
        elif any(item.status == "unknown" for item in results):
            status = "unknown"
        batch_blockers = tuple(
            sorted(
                {
                    blocker
                    for item in results
                    if item.status != "ready"
                    for blocker in item.blockers
                }
            )
        )
        return PaperPortfolioPolicyBatchResult(
            status=status,
            results=tuple(results),
            state=state_result.state,
            blockers=batch_blockers,
        )

    def _read_rows(self, portfolio_id: str) -> _LedgerReadSnapshot:
        uri = self._ledger_path.as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(paper_trade_ledger)")
            }
            if not columns:
                raise ValueError("ledger_table_missing")
            missing = sorted(_REQUIRED_COLUMNS - columns)
            if missing:
                raise ValueError("ledger_columns_missing:" + ",".join(missing))
            rows = tuple(
                connection.execute(
                    "SELECT fill_id, portfolio_id, event_date, stock_code, "
                    "requested_quantity, filled_quantity, turnover_bp, status "
                    "FROM paper_trade_ledger WHERE portfolio_id = ? "
                    "ORDER BY event_date, fill_id",
                    (portfolio_id,),
                ).fetchall()
            )
            return _LedgerReadSnapshot(
                rows=rows,
                rows_sha256=_canonical_rows_sha256(rows),
                data_version=data_version,
            )
        finally:
            connection.rollback()
            connection.close()

    @staticmethod
    def _calendar_blocker(context: PaperPortfolioPolicyContext) -> str | None:
        if context.decision_date not in set(context.official_trading_days):
            return "official_calendar_missing_or_not_trading_day"
        return None

    @staticmethod
    def _missing_sector_symbols(
        context: PaperPortfolioPolicyContext,
        additional_symbols: tuple[str, ...],
    ) -> tuple[str, ...]:
        symbols = set(context.current_weights_bp).union(additional_symbols)
        return tuple(
            sorted(
                symbol
                for symbol in symbols
                if not isinstance(context.sector_by_symbol.get(symbol), str)
                or not context.sector_by_symbol[symbol].strip()
            )
        )

    @staticmethod
    def _weekly_turnover(
        *,
        rows: tuple[sqlite3.Row, ...],
        context: PaperPortfolioPolicyContext,
        week_start: date,
    ) -> int:
        total = 0
        for row in rows:
            event_date = _row_date(row["event_date"])
            if not week_start <= event_date <= context.decision_date:
                continue
            if event_date == context.decision_date and not context.include_decision_date_rows:
                continue
            if str(row["fill_id"]) in context.ignored_fill_ids:
                continue
            if str(row["status"]) not in _EXECUTED_STATUSES:
                continue
            turnover = row["turnover_bp"]
            if isinstance(turnover, bool) or not isinstance(turnover, int):
                raise ValueError("executed ledger row missing integer turnover")
            total += turnover
        return total

    @staticmethod
    def _cooldown_days(
        *,
        last_trade_date: date,
        decision_date: date,
        official_days: tuple[date, ...],
    ) -> int:
        return sum(
            1
            for item in official_days
            if last_trade_date < item < decision_date
        )

    @staticmethod
    def _result(
        status: AdapterStatus,
        *blockers: str,
    ) -> PaperPortfolioPolicyAdapterResult:
        return PaperPortfolioPolicyAdapterResult(
            status=status,
            blockers=tuple(sorted(set(blockers))),
        )


__all__ = [
    "AdapterStatus",
    "PaperPolicyCandidate",
    "PaperPortfolioPolicyAdapter",
    "PaperPortfolioPolicyAdapterResult",
    "PaperPortfolioPolicyBatchResult",
    "PaperPortfolioPolicyContext",
    "PaperPortfolioPolicyState",
]
