"""四條 ML 配置研究 lane 與 append-only 自動證據收集器。

本模組刻意維持下列邊界：

* 市場 SQLite 僅以 ``mode=ro`` 與 ``PRAGMA query_only=ON`` 讀取。
* 每日 Rule baseline 只來自決策日前最後一筆完整 Paper ledger。
* 0/2000/3500/5000 bp lane 皆是 research-only；不具券商送單或正式
  Promotion 權限。
* observation / outcome 使用獨立 SQLite sidecar 的 INSERT-only 紀錄；
  同 custody 重跑冪等，custody 改變時新增 revision，不覆寫歷史。
* 缺少 20 個真實可交易日或任何必要證據時，狀態必為
  ``insufficient_evidence``，不以 0 代替未知值。

sklearn 等模型內部浮點邊界不在本模組內；所有持久化金融數值均使用
整數 bp／股數或 Decimal 字串。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence, cast

from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig
from app_module.paper_portfolio_snapshot_repository import (
    PaperPortfolioPositionSnapshot,
    PaperPortfolioSnapshot,
)
from app_module.portfolio_allocation_dtos import (
    TOTAL_WEIGHT_BP,
    AllocationWeightContract,
    CausalPortfolioState,
    MLAllocationProposal,
    MLAllocationSignalRow,
    PortfolioAllocationContextRow,
    PortfolioAllocationRequestV2,
)
from app_module.portfolio_allocation_service import PortfolioAllocationService
from financial_module.portfolio_turnover import canonical_turnover_bp
from ml_module.allocation_contracts import PortfolioMLDatasetRow
from ml_module.allocation_promotion_reference import (
    OUTCOME_CONTRACT_HASH,
    OUTCOME_CONTRACT_VERSION,
    PROMOTION_HORIZONS,
    build_promotion_observation,
    evaluate_matured_promotion_reference,
)


SHADOW_ALPHA_LANES_BP = (0, 2000, 3500, 5000)
OBSERVATION_SCHEMA_VERSION = "ml-allocation-shadow-observation-v2"
OUTCOME_SCHEMA_VERSION = "ml-allocation-shadow-outcome-v3"
EVIDENCE_SCHEMA_VERSION = "ml-allocation-shadow-evidence-v3"
ADVICE_SCHEMA_VERSION = "allocation-shadow-advice-v1"
_CASH = "CASH"
_BUY_COST_BP = 25
_SELL_COST_BP = 55
_TAIPEI_EOD_SUFFIX = "T23:59:59+08:00"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_deadline(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("natural forward deadline must contain a timezone")
    return value.astimezone(timezone.utc)


def _normalize_availability_cutoff(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("availability cutoff must contain a timezone")
    return value.astimezone(timezone.utc)


def _available_by(
    value: str,
    *,
    cutoff: datetime | None,
) -> bool:
    if cutoff is None:
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("market row available_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("market row available_at must contain a timezone")
    return parsed.astimezone(timezone.utc) <= cutoff


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    if (
        not text.startswith("sha256:")
        or len(text) != 71
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 hash")
    return text


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, Any], value)


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be an array")
    return cast(Sequence[object], value)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def deterministic_blend_weights(
    *,
    rule_weights: AllocationWeightContract,
    ml_weights: AllocationWeightContract,
    alpha_bp: int,
) -> AllocationWeightContract:
    """以整數商與 largest remainder 產生可重播的研究混合權重。"""

    if isinstance(alpha_bp, bool) or alpha_bp not in SHADOW_ALPHA_LANES_BP:
        raise ValueError("alpha_bp must be one of 0, 2000, 3500, 5000")
    keys = [
        *sorted(
            set(rule_weights.symbol_weights_bp)
            | set(ml_weights.symbol_weights_bp)
        ),
        _CASH,
    ]
    floors: dict[str, int] = {}
    remainders: dict[str, int] = {}
    for key in keys:
        rule_bp = (
            rule_weights.cash_weight_bp
            if key == _CASH
            else rule_weights.weight_for(key)
        )
        ml_bp = (
            ml_weights.cash_weight_bp
            if key == _CASH
            else ml_weights.weight_for(key)
        )
        numerator = (
            (TOTAL_WEIGHT_BP - alpha_bp) * rule_bp
            + alpha_bp * ml_bp
        )
        floors[key], remainders[key] = divmod(numerator, TOTAL_WEIGHT_BP)
    remainder_count = TOTAL_WEIGHT_BP - sum(floors.values())
    for key in sorted(keys, key=lambda item: (-remainders[item], item))[
        :remainder_count
    ]:
        floors[key] += 1
    return AllocationWeightContract(
        symbol_weights_bp={
            key: floors[key]
            for key in keys
            if key != _CASH and floors[key] > 0
        },
        cash_weight_bp=floors[_CASH],
    )


def exact_weights_from_snapshot(
    snapshot: PaperPortfolioSnapshot,
) -> AllocationWeightContract:
    """由 Decimal market value 重算 10,000 bp，避免使用已截斷的欄位。"""

    if snapshot.total_value <= Decimal("0"):
        raise ValueError("paper ledger total_value must be positive")
    position_total = sum(
        (position.market_value for position in snapshot.positions),
        Decimal("0"),
    )
    if position_total + snapshot.cash != snapshot.total_value:
        raise ValueError("paper ledger cash and positions do not equal total_value")
    amounts: dict[str, Decimal] = {
        position.stock_code: position.market_value
        for position in snapshot.positions
        if position.quantity > 0 and position.market_value > Decimal("0")
    }
    amounts[_CASH] = snapshot.cash
    floors: dict[str, int] = {}
    remainders: dict[str, Decimal] = {}
    for key, amount in amounts.items():
        exact = amount * Decimal(TOTAL_WEIGHT_BP) / snapshot.total_value
        floor = int(exact.to_integral_value(rounding=ROUND_DOWN))
        floors[key] = floor
        remainders[key] = exact - Decimal(floor)
    missing_bp = TOTAL_WEIGHT_BP - sum(floors.values())
    for key in sorted(amounts, key=lambda item: (-remainders[item], item))[
        :missing_bp
    ]:
        floors[key] += 1
    return AllocationWeightContract(
        symbol_weights_bp={
            key: floors[key]
            for key in sorted(floors)
            if key != _CASH and floors[key] > 0
        },
        cash_weight_bp=floors.get(_CASH, 0),
    )


def _position_quantities(
    snapshot: PaperPortfolioSnapshot,
) -> dict[str, int]:
    return {
        position.stock_code: position.quantity
        for position in snapshot.positions
        if position.quantity > 0
    }


@dataclass(frozen=True)
class PaperLedgerContext:
    snapshot: PaperPortfolioSnapshot
    current_weights: AllocationWeightContract
    weekly_turnover_used_bp: int
    cooldown_days: Mapping[str, int | None]
    ledger_hash: str


def load_t_minus_one_paper_ledger(
    *,
    state_db_path: Path,
    portfolio_id: str,
    decision_date: date,
) -> PaperLedgerContext:
    """讀取嚴格早於決策日的 Paper ledger；缺檔或不完整即 fail closed。"""

    if not state_db_path.is_file():
        raise FileNotFoundError(f"paper ledger not found: {state_db_path}")
    snapshots = _read_paper_snapshots_read_only(
        state_db_path=state_db_path,
        portfolio_id=portfolio_id,
    )
    eligible = tuple(
        snapshot
        for snapshot in snapshots
        if date.fromisoformat(snapshot.decision_date) < decision_date
    )
    if not eligible:
        raise ValueError("no strictly prior paper ledger snapshot")
    snapshot = eligible[-1]
    current_weights = exact_weights_from_snapshot(snapshot)

    # 只有在可觀察到的歷史 quantity 未變時才把 weekly turnover 記為 0。
    # 有變化而缺交易明細時維持未知並 fail closed，絕不由權重漂移猜交易量。
    window_start = decision_date.toordinal() - 7
    weekly = tuple(
        item
        for item in eligible
        if date.fromisoformat(item.decision_date).toordinal() >= window_start
    )
    quantity_states = tuple(_position_quantities(item) for item in weekly)
    if len(quantity_states) >= 2 and len(set(map(_canonical_json, quantity_states))) > 1:
        raise ValueError("paper ledger weekly turnover is not derivable from snapshots")
    weekly_turnover_used_bp = 0

    current_quantities = _position_quantities(snapshot)
    cooldown_days: dict[str, int | None] = {}
    for symbol in sorted(current_quantities):
        prior_states = [
            _position_quantities(item).get(symbol, 0)
            for item in eligible[-6:]
        ]
        cooldown_days[symbol] = (
            5
            if len(prior_states) >= 6
            and len(set(prior_states)) == 1
            else None
        )

    ledger_payload = {
        "portfolio_id": portfolio_id,
        "snapshot_id": snapshot.snapshot_id,
        "decision_date": snapshot.decision_date,
        "source_result_id": snapshot.source_result_id,
        "cash": str(snapshot.cash),
        "total_value": str(snapshot.total_value),
        "positions": [
            {
                "stock_code": item.stock_code,
                "quantity": item.quantity,
                "mark_price": str(item.mark_price),
                "market_value": str(item.market_value),
            }
            for item in snapshot.positions
        ],
        "exact_weights": current_weights.to_dict(),
        "weekly_turnover_used_bp": weekly_turnover_used_bp,
        "cooldown_days": cooldown_days,
    }
    return PaperLedgerContext(
        snapshot=snapshot,
        current_weights=current_weights,
        weekly_turnover_used_bp=weekly_turnover_used_bp,
        cooldown_days=cooldown_days,
        ledger_hash=_payload_hash(ledger_payload),
    )


def _read_paper_snapshots_read_only(
    *,
    state_db_path: Path,
    portfolio_id: str,
) -> tuple[PaperPortfolioSnapshot, ...]:
    uri = state_db_path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA query_only").fetchone() != (1,):
            raise RuntimeError("paper ledger query_only could not be enabled")
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT snapshot_id, portfolio_id, decision_date, source_result_id,
                   cash, total_value
            FROM paper_portfolio_snapshots
            WHERE portfolio_id = ?
            ORDER BY decision_date, snapshot_id
            """,
            (portfolio_id,),
        ).fetchall()
        result: list[PaperPortfolioSnapshot] = []
        for row in rows:
            positions = connection.execute(
                """
                SELECT stock_code, quantity, mark_price, market_value, weight_bp
                FROM paper_portfolio_positions
                WHERE snapshot_id = ?
                ORDER BY stock_code
                """,
                (row["snapshot_id"],),
            ).fetchall()
            result.append(
                PaperPortfolioSnapshot(
                    snapshot_id=str(row["snapshot_id"]),
                    portfolio_id=str(row["portfolio_id"]),
                    decision_date=str(row["decision_date"]),
                    source_result_id=str(row["source_result_id"]),
                    cash=Decimal(str(row["cash"])),
                    total_value=Decimal(str(row["total_value"])),
                    positions=tuple(
                        PaperPortfolioPositionSnapshot(
                            stock_code=str(item["stock_code"]),
                            quantity=int(item["quantity"]),
                            mark_price=Decimal(str(item["mark_price"])),
                            market_value=Decimal(str(item["market_value"])),
                            weight_bp=int(item["weight_bp"]),
                        )
                        for item in positions
                    ),
                )
            )
    return tuple(result)


@dataclass(frozen=True)
class MarketContext:
    stock_code: str
    close_price: Decimal | None
    median_volume_20d_shares: int | None
    price_date: str | None
    stock_name: str
    missing_reasons: tuple[str, ...]


@dataclass(frozen=True)
class MarketOutcomeRow:
    """一筆 content-addressed outcome 市場列。"""

    observed_date: date
    open_price: Decimal | None
    close_price: Decimal | None
    available_at: str
    revision_id: str
    source_row_hash: str
    source_payload: Mapping[str, object]


@dataclass(frozen=True)
class OfficialMarketEvent:
    symbol: str
    effective_date: date
    event_type: str
    formal_label_ledger_allowed: bool
    formal_trading_restriction_allowed: bool
    revision_availability_ambiguous: bool
    revision_id: str
    source_record_hash: str
    event_hash: str


@dataclass(frozen=True)
class OfficialMarketEventCustody:
    ready: bool
    blocker: str | None
    pointer_path: str | None
    manifest_hash: str | None
    manifest_file_hash: str | None
    canonical_events_hash: str | None
    source_registry_hash: str | None
    coverage_start_year: int | None
    coverage_end_year: int | None
    events_by_symbol: Mapping[str, tuple[OfficialMarketEvent, ...]]

    def interval_blocker(
        self,
        *,
        symbol: str,
        entry_date: date,
        exit_date: date,
    ) -> str | None:
        if not self.ready:
            return self.blocker or "corporate_action_custody_unavailable"
        if (
            self.coverage_start_year is None
            or self.coverage_end_year is None
            or entry_date.year < self.coverage_start_year
            or exit_date.year > self.coverage_end_year
        ):
            return "corporate_action_year_coverage_missing"
        for event in self.events_by_symbol.get(symbol, ()):
            if not entry_date <= event.effective_date <= exit_date:
                continue
            if event.revision_availability_ambiguous:
                return "corporate_action_revision_availability_ambiguous"
            if (
                event.formal_label_ledger_allowed
                or event.formal_trading_restriction_allowed
            ):
                return f"corporate_action_interval_excluded:{event.event_type}"
        return None


class SQLiteTMinusOneMarketReader:
    """正式市場庫的嚴格唯讀 T-1 reader。"""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def read_contexts(
        self,
        *,
        symbols: Iterable[str],
        strict_t_minus_one: date,
    ) -> dict[str, MarketContext]:
        if not self._database_path.is_file():
            raise FileNotFoundError(
                f"market database not found: {self._database_path}"
            )
        result: dict[str, MarketContext] = {}
        with self._connect() as connection:
            for symbol in sorted(set(symbols)):
                rows = connection.execute(
                    """
                    SELECT "日期", "收盤價", "成交股數", "證券名稱"
                    FROM daily_prices
                    WHERE "證券代號" = ? AND "日期" <= ?
                    ORDER BY "日期" DESC
                    LIMIT 20
                    """,
                    (symbol, strict_t_minus_one.strftime("%Y%m%d")),
                ).fetchall()
                reasons: list[str] = []
                exact = (
                    rows[0]
                    if rows
                    and _sqlite_date(rows[0][0]) == strict_t_minus_one
                    else None
                )
                close_price = (
                    _decimal_or_none(exact[1]) if exact is not None else None
                )
                if close_price is None or close_price <= Decimal("0"):
                    close_price = None
                    reasons.append("strict_t_minus_one_close_missing")
                volumes = [
                    _integer_or_none(row[2])
                    for row in rows
                ]
                valid_volumes = [
                    item
                    for item in volumes
                    if item is not None and item >= 0
                ]
                median_volume = (
                    _integer_median(valid_volumes)
                    if len(valid_volumes) == 20
                    else None
                )
                if median_volume is None:
                    reasons.append("strict_t_minus_one_20d_volume_missing")
                result[symbol] = MarketContext(
                    stock_code=symbol,
                    close_price=close_price,
                    median_volume_20d_shares=median_volume,
                    price_date=(
                        strict_t_minus_one.isoformat()
                        if exact is not None
                        else None
                    ),
                    stock_name=(
                        str(exact[3]).strip()
                        if exact is not None and exact[3] is not None
                        else ""
                    ),
                    missing_reasons=tuple(reasons),
                )
        return result

    def read_close_paths(
        self,
        *,
        symbols: Iterable[str],
        start_date: date,
        cutoff_date: date,
    ) -> dict[str, tuple[tuple[date, Decimal], ...]]:
        result: dict[str, tuple[tuple[date, Decimal], ...]] = {}
        with self._connect() as connection:
            for symbol in sorted(set(symbols)):
                rows = connection.execute(
                    """
                    SELECT "日期", "收盤價"
                    FROM daily_prices
                    WHERE "證券代號" = ?
                      AND "日期" >= ?
                      AND "日期" <= ?
                    ORDER BY "日期"
                    """,
                    (
                        symbol,
                        start_date.strftime("%Y%m%d"),
                        cutoff_date.strftime("%Y%m%d"),
                    ),
                ).fetchall()
                values: list[tuple[date, Decimal]] = []
                for raw_date, raw_close in rows:
                    parsed_date = _sqlite_date(raw_date)
                    close = _decimal_or_none(raw_close)
                    if (
                        parsed_date is not None
                        and close is not None
                        and close > Decimal("0")
                    ):
                        values.append((parsed_date, close))
                result[symbol] = tuple(values)
        return result

    def read_outcome_sessions(
        self,
        *,
        symbol: str,
        start_date: date,
        cutoff_date: date,
        limit: int,
    ) -> tuple[MarketOutcomeRow, ...]:
        """讀取單一股票自己的可交易 session；不做跨股票日期交集。"""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("outcome session limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT "日期", "證券代號", "證券名稱", "開盤價", "收盤價"
                FROM daily_prices
                WHERE "證券代號" = ?
                  AND "日期" >= ?
                  AND "日期" <= ?
                ORDER BY "日期"
                LIMIT ?
                """,
                (
                    symbol,
                    start_date.strftime("%Y%m%d"),
                    cutoff_date.strftime("%Y%m%d"),
                    limit,
                ),
            ).fetchall()
        result: list[MarketOutcomeRow] = []
        for raw_date, raw_symbol, raw_name, raw_open, raw_close in rows:
            observed_date = _sqlite_date(raw_date)
            open_price = _decimal_or_none(raw_open)
            close_price = _decimal_or_none(raw_close)
            if observed_date is None:
                continue
            if open_price is not None and open_price <= Decimal("0"):
                open_price = None
            if close_price is not None and close_price <= Decimal("0"):
                close_price = None
            payload: dict[str, object] = {
                "source_id": "sqlite.daily_prices",
                "table": "daily_prices",
                "event_date": observed_date.isoformat(),
                "symbol": str(raw_symbol).strip(),
                "security_name": (
                    str(raw_name).strip() if raw_name is not None else ""
                ),
                "open": str(open_price) if open_price is not None else None,
                "close": str(close_price) if close_price is not None else None,
                "availability_basis": (
                    "official_market_session_end_of_day_conservative"
                ),
                "available_at": (
                    observed_date.isoformat() + _TAIPEI_EOD_SUFFIX
                ),
            }
            source_row_hash = _payload_hash(payload)
            result.append(
                MarketOutcomeRow(
                    observed_date=observed_date,
                    open_price=open_price,
                    close_price=close_price,
                    available_at=str(payload["available_at"]),
                    revision_id=source_row_hash,
                    source_row_hash=source_row_hash,
                    source_payload=payload,
                )
            )
        return tuple(result)

    def read_taiex_rows(
        self,
        *,
        observed_dates: Iterable[date],
    ) -> Mapping[date, MarketOutcomeRow]:
        """讀取精確日期的 TAIEX open/close；缺列或重複列皆由呼叫端 fail closed。"""

        dates = tuple(sorted(set(observed_dates)))
        if not dates:
            return {}
        placeholders = ",".join("?" for _ in dates)
        parameters = tuple(item.strftime("%Y%m%d") for item in dates)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT "日期", "指數名稱", "開盤價", "收盤價"
                FROM market_indices
                WHERE "日期" IN ({placeholders})
                  AND UPPER(TRIM("指數名稱")) = 'TAIEX'
                ORDER BY "日期", "指數名稱"
                """,
                parameters,
            ).fetchall()
        result: dict[date, MarketOutcomeRow] = {}
        duplicate_dates: set[date] = set()
        for raw_date, raw_name, raw_open, raw_close in rows:
            observed_date = _sqlite_date(raw_date)
            open_price = _decimal_or_none(raw_open)
            close_price = _decimal_or_none(raw_close)
            if observed_date is None:
                continue
            if observed_date in result:
                duplicate_dates.add(observed_date)
                continue
            if open_price is not None and open_price <= Decimal("0"):
                open_price = None
            if close_price is not None and close_price <= Decimal("0"):
                close_price = None
            payload: dict[str, object] = {
                "source_id": "sqlite.market_indices",
                "table": "market_indices",
                "event_date": observed_date.isoformat(),
                "benchmark_id": str(raw_name).strip(),
                "open": str(open_price) if open_price is not None else None,
                "close": str(close_price) if close_price is not None else None,
                "availability_basis": (
                    "official_market_session_end_of_day_conservative"
                ),
                "available_at": (
                    observed_date.isoformat() + _TAIPEI_EOD_SUFFIX
                ),
            }
            source_row_hash = _payload_hash(payload)
            result[observed_date] = MarketOutcomeRow(
                observed_date=observed_date,
                open_price=open_price,
                close_price=close_price,
                available_at=str(payload["available_at"]),
                revision_id=source_row_hash,
                source_row_hash=source_row_hash,
                source_payload=payload,
            )
        for duplicate_date in duplicate_dates:
            result.pop(duplicate_date, None)
        return result

    def _connect(self) -> sqlite3.Connection:
        uri = self._database_path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA query_only").fetchone() != (1,):
            connection.close()
            raise RuntimeError("market database query_only could not be enabled")
        return connection


def _sqlite_date(value: object) -> date | None:
    text = str(value).strip()
    for template in ("%Y%m%d", "%Y-%m-%d"):
        try:
            from datetime import datetime

            return datetime.strptime(text, template).date()
        except ValueError:
            continue
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    return result if result.is_finite() else None


def _integer_or_none(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    if not result.is_finite() or result != result.to_integral_value():
        return None
    return int(result)


def _discover_official_market_event_pointer(
    *,
    artifact_root: Path,
    market_database_path: Path,
) -> Path | None:
    candidates: list[Path] = []
    for base in (
        artifact_root.resolve(),
        market_database_path.resolve().parent,
    ):
        for ancestor in (base, *base.parents):
            candidates.extend(
                (
                    ancestor / "official_market_events" / "latest_manifest.json",
                    ancestor
                    / "output"
                    / "release_v4"
                    / "official_market_events"
                    / "latest_manifest.json",
                )
            )
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def _load_official_market_event_custody(
    pointer_path: Path | None,
) -> OfficialMarketEventCustody:
    if pointer_path is None or not pointer_path.is_file():
        return OfficialMarketEventCustody(
            ready=False,
            blocker="corporate_action_manifest_missing",
            pointer_path=(
                str(pointer_path.resolve()) if pointer_path is not None else None
            ),
            manifest_hash=None,
            manifest_file_hash=None,
            canonical_events_hash=None,
            source_registry_hash=None,
            coverage_start_year=None,
            coverage_end_year=None,
            events_by_symbol={},
        )
    try:
        return _validated_official_market_event_custody(pointer_path.resolve())
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return OfficialMarketEventCustody(
            ready=False,
            blocker=(
                "corporate_action_custody_invalid:"
                f"{type(exc).__name__}:{str(exc)}"
            ),
            pointer_path=str(pointer_path.resolve()),
            manifest_hash=None,
            manifest_file_hash=None,
            canonical_events_hash=None,
            source_registry_hash=None,
            coverage_start_year=None,
            coverage_end_year=None,
            events_by_symbol={},
        )


def _validated_official_market_event_custody(
    pointer_path: Path,
) -> OfficialMarketEventCustody:
    pointer = _require_mapping(
        json.loads(pointer_path.read_text(encoding="utf-8")),
        "official market event pointer",
    )
    if pointer.get("schema_version") != "official-market-event-latest.v1":
        raise ValueError("official event pointer schema mismatch")
    manifest_hash = _require_sha256(
        pointer.get("manifest_hash"),
        "official event pointer.manifest_hash",
    )
    manifest_file_hash = _require_sha256(
        pointer.get("manifest_file_hash"),
        "official event pointer.manifest_file_hash",
    )
    canonical_events_hash = _require_sha256(
        pointer.get("canonical_events_hash"),
        "official event pointer.canonical_events_hash",
    )
    manifest_relative = Path(
        _require_text(
            pointer.get("manifest_path"),
            "official event pointer.manifest_path",
        )
    )
    manifest_path = (pointer_path.parent / manifest_relative).resolve()
    try:
        manifest_path.relative_to(pointer_path.parent.resolve())
    except ValueError as exc:
        raise ValueError("official event manifest path escapes publication") from exc
    if _file_hash(manifest_path) != manifest_file_hash:
        raise ValueError("official event manifest file hash mismatch")
    manifest = _require_mapping(
        json.loads(manifest_path.read_text(encoding="utf-8")),
        "official market event manifest",
    )
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_hash", None)
    if _payload_hash(manifest_body) != manifest_hash:
        raise ValueError("official event manifest canonical hash mismatch")
    if manifest.get("manifest_hash") != manifest_hash:
        raise ValueError("official event manifest logical hash mismatch")
    if (
        manifest.get("schema_version")
        != "official-market-event-publication.v1"
        or manifest.get("status") != "formal_source_publication"
    ):
        raise ValueError("official event publication is not formal")
    safety = _require_mapping(manifest.get("safety"), "official event safety")
    for field_name in (
        "active_sqlite_written",
        "all_official_revision_vintages_preserved",
        "append_only_canonical_events",
        "available_at_effective_at_separated",
        "formal_source_publication",
        "result_tables_label_ledger_only",
        "unlinked_revision_fails_closed",
    ):
        value = _require_bool(safety.get(field_name), f"safety.{field_name}")
        expected = field_name != "active_sqlite_written"
        if value is not expected:
            raise ValueError(f"official event safety invariant failed: {field_name}")

    source_registry = _require_mapping(
        manifest.get("source_registry"),
        "official event source_registry",
    )
    source_registry_hash = _payload_hash(source_registry)
    sources = tuple(
        _require_mapping(item, "official event source")
        for item in _require_sequence(
            source_registry.get("sources"),
            "official event source_registry.sources",
        )
    )
    if not sources:
        raise ValueError("official event source registry is empty")
    source_ids: set[str] = set()
    allowed_uses: set[str] = set()
    for source in sources:
        source_id = _require_text(source.get("source_id"), "source_id")
        if source_id in source_ids:
            raise ValueError(f"duplicate official event source: {source_id}")
        source_ids.add(source_id)
        _require_text(source.get("license_url"), f"{source_id}.license_url")
        allowed_uses.update(
            _require_text(item, f"{source_id}.allowed_use")
            for item in _require_sequence(
                source.get("allowed_uses"),
                f"{source_id}.allowed_uses",
            )
        )
    if not {
        "formal_label",
        "formal_trading_restriction_timeline",
    }.issubset(allowed_uses):
        raise ValueError("official event formal use coverage is incomplete")

    coverage_rows = tuple(
        _require_mapping(item, "official event coverage")
        for item in _require_sequence(
            manifest.get("coverage"),
            "official event coverage",
        )
    )
    coverage_by_source: dict[str, tuple[int, int]] = {}
    for item in coverage_rows:
        source_id = _require_text(item.get("source_id"), "coverage.source_id")
        if source_id in coverage_by_source:
            raise ValueError(f"duplicate official event coverage: {source_id}")
        if not _require_bool(
            item.get("complete_year_coverage"),
            f"{source_id}.complete_year_coverage",
        ):
            raise ValueError(f"official event year coverage is incomplete: {source_id}")
        start_year = _require_int(
            item.get("requested_start_year"),
            f"{source_id}.requested_start_year",
        )
        end_year = _require_int(
            item.get("requested_end_year"),
            f"{source_id}.requested_end_year",
        )
        if start_year > end_year:
            raise ValueError("official event year coverage is invalid")
        coverage_by_source[source_id] = (start_year, end_year)
    if set(coverage_by_source) != source_ids:
        raise ValueError("official event source/coverage sets mismatch")
    coverage_start_year = max(item[0] for item in coverage_by_source.values())
    coverage_end_year = min(item[1] for item in coverage_by_source.values())
    if coverage_start_year > coverage_end_year:
        raise ValueError("official event sources have no common year coverage")

    canonical = _require_mapping(
        manifest.get("canonical_events"),
        "official event canonical_events",
    )
    if canonical.get("schema_version") != "official-market-event.v1":
        raise ValueError("official event canonical schema mismatch")
    if canonical.get("file_hash") != canonical_events_hash:
        raise ValueError("official event canonical hash pointer mismatch")
    canonical_relative = Path(
        _require_text(canonical.get("path"), "canonical_events.path")
    )
    canonical_path = (manifest_path.parent / canonical_relative).resolve()
    try:
        canonical_path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise ValueError("official event canonical path escapes publication") from exc
    if _file_hash(canonical_path) != canonical_events_hash:
        raise ValueError("official event canonical file hash mismatch")

    events_by_symbol: dict[str, list[OfficialMarketEvent]] = {}
    event_count = 0
    with canonical_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            raw_event = _require_mapping(
                json.loads(line),
                f"official event line {line_number}",
            )
            if raw_event.get("schema_version") != "official-market-event.v1":
                raise ValueError("official event row schema mismatch")
            source_id = _require_text(raw_event.get("source_id"), "event.source_id")
            if source_id not in source_ids:
                raise ValueError("official event row references unknown source")
            source_record = _require_mapping(
                raw_event.get("source_record"),
                "event.source_record",
            )
            source_record_hash = _require_sha256(
                raw_event.get("source_record_hash"),
                "event.source_record_hash",
            )
            if _payload_hash(source_record) != source_record_hash:
                raise ValueError("official event source record hash mismatch")
            revision_id = _require_sha256(
                raw_event.get("revision_id"),
                "event.revision_id",
            )
            if revision_id != source_record_hash:
                raise ValueError("official event revision/source row hash mismatch")
            _require_text(raw_event.get("available_at"), "event.available_at")
            effective_at = _require_text(
                raw_event.get("effective_at"),
                "event.effective_at",
            )
            try:
                effective_date = datetime.fromisoformat(effective_at).date()
            except ValueError as exc:
                raise ValueError("official event effective_at is invalid") from exc
            event = OfficialMarketEvent(
                symbol=_require_text(raw_event.get("symbol"), "event.symbol"),
                effective_date=effective_date,
                event_type=_require_text(
                    raw_event.get("event_type"),
                    "event.event_type",
                ),
                formal_label_ledger_allowed=_require_bool(
                    raw_event.get("formal_label_ledger_allowed"),
                    "event.formal_label_ledger_allowed",
                ),
                formal_trading_restriction_allowed=_require_bool(
                    raw_event.get("formal_trading_restriction_allowed"),
                    "event.formal_trading_restriction_allowed",
                ),
                revision_availability_ambiguous=_require_bool(
                    raw_event.get("revision_availability_ambiguous"),
                    "event.revision_availability_ambiguous",
                ),
                revision_id=revision_id,
                source_record_hash=source_record_hash,
                event_hash=_payload_hash(raw_event),
            )
            events_by_symbol.setdefault(event.symbol, []).append(event)
            event_count += 1
    if event_count != _require_int(canonical.get("event_count"), "event_count"):
        raise ValueError("official event canonical row count mismatch")
    normalized_events = {
        symbol: tuple(
            sorted(
                events,
                key=lambda item: (
                    item.effective_date,
                    item.event_type,
                    item.revision_id,
                ),
            )
        )
        for symbol, events in events_by_symbol.items()
    }
    return OfficialMarketEventCustody(
        ready=True,
        blocker=None,
        pointer_path=str(pointer_path),
        manifest_hash=manifest_hash,
        manifest_file_hash=manifest_file_hash,
        canonical_events_hash=canonical_events_hash,
        source_registry_hash=source_registry_hash,
        coverage_start_year=coverage_start_year,
        coverage_end_year=coverage_end_year,
        events_by_symbol=normalized_events,
    )


def _integer_median(values: Sequence[int]) -> int:
    if not values:
        raise ValueError("median requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def load_allocation_proposal(
    *,
    proposal_path: Path,
    expected_proposal_hash: str,
    expected_replay_hash: str,
) -> MLAllocationProposal:
    """載入 inference proposal 並驗證內容 hash／replay custody。"""

    payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    outer = _require_mapping(payload, "proposal output")
    if outer.get("status") != "inference_completed":
        raise ValueError("proposal output status must be inference_completed")
    if outer.get("proposal_hash") != expected_proposal_hash:
        raise ValueError("proposal hash custody mismatch")
    if outer.get("replay_hash") != expected_replay_hash:
        raise ValueError("proposal replay hash custody mismatch")
    raw = _require_mapping(outer.get("proposal"), "proposal")
    if _payload_hash(raw) != expected_proposal_hash:
        raise ValueError("proposal payload hash mismatch")

    requested = _require_mapping(raw.get("requested_weights"), "requested_weights")
    symbols = _require_mapping(
        requested.get("symbol_weights_bp"),
        "requested_weights.symbol_weights_bp",
    )
    requested_weights = AllocationWeightContract(
        symbol_weights_bp={
            _require_text(symbol, "stock_code"): _require_int(
                weight,
                f"requested_weight[{symbol}]",
            )
            for symbol, weight in symbols.items()
        },
        cash_weight_bp=_require_int(
            requested.get("cash_weight_bp"),
            "requested_weights.cash_weight_bp",
        ),
    )
    signals = tuple(
        _signal_from_payload(
            _require_mapping(item, "proposal.signals[]")
        )
        for item in _require_sequence(raw.get("signals"), "proposal.signals")
    )
    family_weights = _require_mapping(
        raw.get("feature_family_weights_bp"),
        "feature_family_weights_bp",
    )
    proposal = MLAllocationProposal(
        decision_date=_require_text(raw.get("decision_date"), "decision_date"),
        model_id=_require_text(raw.get("model_id"), "model_id"),
        dataset_id=_require_text(raw.get("dataset_id"), "dataset_id"),
        universe_id=_require_text(raw.get("universe_id"), "universe_id"),
        policy_id=_require_text(raw.get("policy_id"), "policy_id"),
        requested_weights=requested_weights,
        model_hash=_require_text(raw.get("model_hash"), "model_hash"),
        dataset_identity_hash=_require_text(
            raw.get("dataset_identity_hash"),
            "dataset_identity_hash",
        ),
        dataset_manifest_file_hash=_require_text(
            raw.get("dataset_manifest_file_hash"),
            "dataset_manifest_file_hash",
        ),
        universe_hash=_require_text(raw.get("universe_hash"), "universe_hash"),
        policy_hash=_require_text(raw.get("policy_hash"), "policy_hash"),
        coverage_bp=_require_int(raw.get("coverage_bp"), "coverage_bp"),
        feature_family_weights_bp={
            _require_text(key, "feature_family_id"): _require_int(
                value,
                f"feature_family_weights_bp[{key}]",
            )
            for key, value in family_weights.items()
        },
        estimated_turnover_bp=_require_int(
            raw.get("estimated_turnover_bp"),
            "estimated_turnover_bp",
        ),
        estimated_transaction_cost=Decimal(
            _require_text(
                raw.get("estimated_transaction_cost"),
                "estimated_transaction_cost",
            )
        ),
        fallback_reason=(
            _require_text(raw.get("fallback_reason"), "fallback_reason")
            if raw.get("fallback_reason") is not None
            else None
        ),
        signals=signals,
        missing_family_ids=tuple(
            _require_text(item, "missing_family_id")
            for item in _require_sequence(
                raw.get("missing_family_ids"),
                "missing_family_ids",
            )
        ),
        reasons=tuple(
            _require_text(item, "reason")
            for item in _require_sequence(raw.get("reasons"), "reasons")
        ),
        formal_oos_allowed=_require_bool(
            raw.get("formal_oos_allowed"),
            "formal_oos_allowed",
        ),
        production_action_allowed=_require_bool(
            raw.get("production_action_allowed"),
            "production_action_allowed",
        ),
        production_blend_alpha_bp=_require_int(
            raw.get("production_blend_alpha_bp"),
            "production_blend_alpha_bp",
        ),
        broker_order_allowed=_require_bool(
            raw.get("broker_order_allowed"),
            "broker_order_allowed",
        ),
    )
    if _payload_hash(proposal.to_dict()) != expected_proposal_hash:
        raise ValueError("proposal DTO canonical replay mismatch")
    return proposal


def _signal_from_payload(raw: Mapping[str, Any]) -> MLAllocationSignalRow:
    optional_sector = raw.get("expected_sector_excess_return_bp")
    return MLAllocationSignalRow(
        stock_code=_require_text(raw.get("stock_code"), "signal.stock_code"),
        expected_excess_return_bp=_require_int(
            raw.get("expected_excess_return_bp"),
            "signal.expected_excess_return_bp",
        ),
        downside_probability_bp=_require_int(
            raw.get("downside_probability_bp"),
            "signal.downside_probability_bp",
        ),
        predicted_mae_bp=_require_int(
            raw.get("predicted_mae_bp"),
            "signal.predicted_mae_bp",
        ),
        rank_bp=_require_int(raw.get("rank_bp"), "signal.rank_bp"),
        confidence_bp=_require_int(
            raw.get("confidence_bp"),
            "signal.confidence_bp",
        ),
        coverage_bp=_require_int(
            raw.get("coverage_bp"),
            "signal.coverage_bp",
        ),
        feature_manifest_hash=_require_text(
            raw.get("feature_manifest_hash"),
            "signal.feature_manifest_hash",
        ),
        expected_sector_excess_return_bp=(
            _require_int(
                optional_sector,
                "signal.expected_sector_excess_return_bp",
            )
            if optional_sector is not None
            else None
        ),
        predicted_mfe_bp=_require_int(
            raw.get("predicted_mfe_bp"),
            "signal.predicted_mfe_bp",
        ),
        predicted_realized_volatility_bp=_require_int(
            raw.get("predicted_realized_volatility_bp"),
            "signal.predicted_realized_volatility_bp",
        ),
        predicted_max_drawdown_bp=_require_int(
            raw.get("predicted_max_drawdown_bp"),
            "signal.predicted_max_drawdown_bp",
        ),
        predicted_tail_loss_bp=_require_int(
            raw.get("predicted_tail_loss_bp"),
            "signal.predicted_tail_loss_bp",
        ),
        fill_feasibility_probability_bp=_require_int(
            raw.get("fill_feasibility_probability_bp"),
            "signal.fill_feasibility_probability_bp",
        ),
        missing_head_ids=tuple(
            _require_text(item, "signal.missing_head_id")
            for item in _require_sequence(
                raw.get("missing_head_ids"),
                "signal.missing_head_ids",
            )
        ),
        missing_family_ids=tuple(
            _require_text(item, "signal.missing_family_id")
            for item in _require_sequence(
                raw.get("missing_family_ids"),
                "signal.missing_family_ids",
            )
        ),
        reasons=tuple(
            _require_text(item, "signal.reason")
            for item in _require_sequence(
                raw.get("reasons"),
                "signal.reasons",
            )
        ),
    )


class ShadowEvidenceRepository:
    """INSERT-only sidecar；records 以內容 hash 為主鍵。"""

    def __init__(
        self,
        database_path: Path,
        *,
        ensure_schema: bool = True,
    ) -> None:
        self.path = database_path
        if ensure_schema:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    def append_observation(
        self,
        *,
        decision_date: str,
        custody_hash: str,
        payload: Mapping[str, object],
        natural_forward_deadline_at: datetime | None = None,
    ) -> tuple[dict[str, object], bool]:
        deadline = _normalize_deadline(natural_forward_deadline_at)
        if deadline is not None and _utc_now() > deadline:
            raise TimeoutError(
                "natural forward observation append deadline has passed"
            )
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            if deadline is not None:
                # Hold the write lock while checking the deadline and inserting
                # the row.  A post-insert check below causes the context manager
                # to rollback if the real emission crosses the cutoff.
                connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT payload_json
                FROM shadow_observations
                WHERE decision_date = ? AND custody_hash = ?
                """,
                (decision_date, custody_hash),
            ).fetchone()
            if existing is not None:
                return cast(
                    dict[str, object],
                    json.loads(str(existing["payload_json"])),
                ), True
            row = connection.execute(
                """
                SELECT revision, record_hash
                FROM shadow_observations
                WHERE decision_date = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (decision_date,),
            ).fetchone()
            revision = 1 if row is None else int(row["revision"]) + 1
            previous_hash = None if row is None else str(row["record_hash"])
            body = {
                **dict(payload),
                "schema_version": OBSERVATION_SCHEMA_VERSION,
                "decision_date": decision_date,
                "custody_hash": custody_hash,
                "revision": revision,
                "previous_revision_hash": previous_hash,
            }
            record = {
                **body,
                "record_hash": _payload_hash(body),
            }
            if deadline is not None and _utc_now() > deadline:
                raise TimeoutError(
                    "natural forward observation append deadline has passed"
                )
            try:
                connection.execute(
                    """
                    INSERT INTO shadow_observations
                    (record_hash, decision_date, custody_hash, revision, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record["record_hash"],
                        decision_date,
                        custody_hash,
                        revision,
                        _canonical_json(record),
                    ),
                )
                if deadline is not None and _utc_now() > deadline:
                    raise TimeoutError(
                        "natural forward observation emission crossed deadline"
                    )
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    """
                    SELECT payload_json
                    FROM shadow_observations
                    WHERE decision_date = ? AND custody_hash = ?
                    """,
                    (decision_date, custody_hash),
                ).fetchone()
                if existing is None:
                    raise
                return cast(
                    dict[str, object],
                    json.loads(str(existing["payload_json"])),
                ), True
            return record, False

    def append_outcome(
        self,
        *,
        observation_hash: str,
        custody_hash: str,
        payload: Mapping[str, object],
    ) -> tuple[dict[str, object], bool]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            existing = connection.execute(
                """
                SELECT payload_json
                FROM shadow_outcomes
                WHERE observation_hash = ? AND custody_hash = ?
                """,
                (observation_hash, custody_hash),
            ).fetchone()
            if existing is not None:
                return cast(
                    dict[str, object],
                    json.loads(str(existing["payload_json"])),
                ), True
            row = connection.execute(
                """
                SELECT revision, record_hash
                FROM shadow_outcomes
                WHERE observation_hash = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (observation_hash,),
            ).fetchone()
            revision = 1 if row is None else int(row["revision"]) + 1
            previous_hash = None if row is None else str(row["record_hash"])
            body = {
                **dict(payload),
                "schema_version": OUTCOME_SCHEMA_VERSION,
                "observation_hash": observation_hash,
                "custody_hash": custody_hash,
                "revision": revision,
                "previous_revision_hash": previous_hash,
            }
            record = {**body, "record_hash": _payload_hash(body)}
            connection.execute(
                """
                INSERT INTO shadow_outcomes
                (record_hash, observation_hash, custody_hash, revision, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record["record_hash"],
                    observation_hash,
                    custody_hash,
                    revision,
                    _canonical_json(record),
                ),
            )
            return record, False

    def observations(self) -> tuple[dict[str, object], ...]:
        return self._records("shadow_observations")

    def outcomes(self) -> tuple[dict[str, object], ...]:
        return self._records("shadow_outcomes")

    def latest_observations(
        self,
    ) -> tuple[dict[str, object], ...]:
        """每個 decision date 只取最高 revision，不刪除舊紀錄。"""

        latest: dict[str, dict[str, object]] = {}
        for record in self.observations():
            decision_date = _require_text(
                record.get("decision_date"),
                "observation.decision_date",
            )
            revision = _require_int(
                record.get("revision"),
                "observation.revision",
            )
            existing = latest.get(decision_date)
            if (
                existing is None
                or revision
                > _require_int(
                    existing.get("revision"),
                    "observation.revision",
                )
            ):
                latest[decision_date] = record
        return tuple(latest[key] for key in sorted(latest))

    def latest_outcomes(
        self,
        *,
        observation_hashes: Iterable[str],
    ) -> tuple[dict[str, object], ...]:
        """只取指定 observation 的最高 outcome revision。"""

        allowed = frozenset(observation_hashes)
        latest: dict[str, dict[str, object]] = {}
        for record in self.outcomes():
            observation_hash = _require_text(
                record.get("observation_hash"),
                "outcome.observation_hash",
            )
            if observation_hash not in allowed:
                continue
            revision = _require_int(
                record.get("revision"),
                "outcome.revision",
            )
            existing = latest.get(observation_hash)
            if (
                existing is None
                or revision
                > _require_int(
                    existing.get("revision"),
                    "outcome.revision",
                )
            ):
                latest[observation_hash] = record
        return tuple(latest[key] for key in sorted(latest))

    def _records(self, table_name: str) -> tuple[dict[str, object], ...]:
        if table_name not in {"shadow_observations", "shadow_outcomes"}:
            raise ValueError("unsupported sidecar table")
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {table_name} ORDER BY rowid"  # noqa: S608
            ).fetchall()
        return tuple(
            cast(dict[str, object], json.loads(str(row[0])))
            for row in rows
        )

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS shadow_observations (
                    record_hash TEXT PRIMARY KEY,
                    decision_date TEXT NOT NULL,
                    custody_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (decision_date, custody_hash),
                    UNIQUE (decision_date, revision)
                );
                CREATE TABLE IF NOT EXISTS shadow_outcomes (
                    record_hash TEXT PRIMARY KEY,
                    observation_hash TEXT NOT NULL,
                    custody_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (observation_hash, custody_hash),
                    UNIQUE (observation_hash, revision)
                );
                """
            )


def _turnover_bp(
    current: AllocationWeightContract,
    target: AllocationWeightContract,
) -> int:
    symbols = sorted(
        set(current.symbol_weights_bp) | set(target.symbol_weights_bp)
    )
    return canonical_turnover_bp(
        current_position_weights_bp=tuple(
            current.weight_for(symbol) for symbol in symbols
        ),
        current_cash_bp=current.cash_weight_bp,
        target_position_weights_bp=tuple(
            target.weight_for(symbol) for symbol in symbols
        ),
        target_cash_bp=target.cash_weight_bp,
    )


def _advice_payload(
    *,
    alpha_bp: int,
    result: Mapping[str, object],
    research_only: bool,
) -> dict[str, object]:
    rows = _require_sequence(result.get("rows"), "allocation result rows")
    advice_rows = []
    for item in rows:
        row = _require_mapping(item, "allocation result row")
        current_weight = row.get("current_weight_bp")
        target_weight = row.get("target_weight_bp")
        executable_weight = row.get("executable_weight_bp")
        diagnostics = list(
            _require_sequence(
                row.get("diagnostics"),
                "allocation diagnostics",
            )
        )
        why: list[object] = [*diagnostics]
        why_not: list[object] = ["broker_execution_not_authorized"]
        if current_weight is None:
            why.append("current_weight_unknown")
            why_not.append("gap_and_execution_fail_closed")
        elif executable_weight is None:
            why.append("execution_weight_unavailable")
            why_not.append("portfolio_state_or_execution_inputs_incomplete")
        elif executable_weight != current_weight:
            why.append("executable_weight_change_generated")
        elif target_weight == current_weight:
            why.append("final_target_equals_current_weight")
            why_not.append("no_executable_weight_change_required")
        elif (
            isinstance(target_weight, int)
            and isinstance(current_weight, int)
            and target_weight < current_weight
        ):
            why.append("target_reduction_proposed")
            why_not.append(
                "executable_weight_held_by_rebalance_or_cooldown_controls"
            )
        else:
            why.append("target_addition_proposed")
            why_not.append(
                "executable_weight_held_by_health_liquidity_or_rebalance_controls"
            )
        advice_rows.append(
            {
                "stock_code": row.get("stock_code"),
                "target_weight_bp": target_weight,
                "current_weight_bp": current_weight,
                "gap_weight_bp": row.get("gap_weight_bp"),
                "executable_weight_bp": executable_weight,
                "why": list(dict.fromkeys(why)),
                "why_not": list(dict.fromkeys(why_not)),
            }
        )
    reasons = list(
        _require_sequence(result.get("reasons"), "allocation result reasons")
    )
    return {
        "schema_version": ADVICE_SCHEMA_VERSION,
        "research_only": research_only,
        "selected_alpha_bp": alpha_bp,
        "action": result.get("advice_action"),
        "why": reasons,
        "why_not": [
            reason
            for reason in reasons
            if "missing" in str(reason)
            or "blocked" in str(reason)
            or "incomplete" in str(reason)
            or "rule_only" in str(reason)
        ],
        "risk_prompt": (
            "sector／thesis／health 未有正式 PIT 證據時一律 WATCH、不得新增；"
            "本建議不具券商送單權限。"
        ),
        "rows": advice_rows,
        "broker_order_allowed": False,
        "apply_rebalance": False,
    }


class MLAllocationShadowCollector:
    """每日記錄四條 lane、成熟舊 observation 並輸出 hash-bound evidence。"""

    def __init__(
        self,
        *,
        market_database_path: Path,
        paper_state_db_path: Path | None,
        sidecar_database_path: Path,
        artifact_root: Path,
        portfolio_id: str = "paper-main",
        policy: PaperPortfolioPolicyConfig | None = None,
        promotion_reference_path: Path | None = None,
        promotion_reference_file_hash: str | None = None,
        official_market_event_pointer_path: Path | None = None,
        ensure_sidecar_schema: bool = True,
    ) -> None:
        if (promotion_reference_path is None) != (
            promotion_reference_file_hash is None
        ):
            raise ValueError(
                "promotion reference path and file hash must be configured together"
            )
        self._market = SQLiteTMinusOneMarketReader(market_database_path)
        self._paper_state_db_path = paper_state_db_path
        self._repository = ShadowEvidenceRepository(
            sidecar_database_path,
            ensure_schema=ensure_sidecar_schema,
        )
        self._artifact_root = artifact_root
        self._portfolio_id = portfolio_id
        self._policy = policy or PaperPortfolioPolicyConfig()
        self._projector = PortfolioAllocationService(self._policy)
        self._promotion_reference_path = (
            promotion_reference_path.resolve()
            if promotion_reference_path is not None
            else None
        )
        self._promotion_reference_file_hash = (
            _require_text(
                promotion_reference_file_hash,
                "promotion_reference_file_hash",
            )
            if promotion_reference_file_hash is not None
            else None
        )
        self._official_market_event_pointer_path = (
            official_market_event_pointer_path.resolve()
            if official_market_event_pointer_path is not None
            else _discover_official_market_event_pointer(
                artifact_root=artifact_root,
                market_database_path=market_database_path,
            )
        )

    @classmethod
    def for_maturity_refresh(
        cls,
        *,
        market_database_path: Path,
        sidecar_database_path: Path,
        artifact_root: Path,
        official_market_event_pointer_path: Path | None = None,
    ) -> "MLAllocationShadowCollector":
        """建立只做既有 outcome 成熟評估的 collector。

        成熟回填不需要 Paper ledger，也不得藉此建立新的 observation。
        將 ``paper_state_db_path`` 固定為 ``None`` 讓這個邊界由型別與
        ``record_and_mature`` 的明確檢查共同守住。
        """

        return cls(
            market_database_path=market_database_path,
            paper_state_db_path=None,
            sidecar_database_path=sidecar_database_path,
            artifact_root=artifact_root,
            official_market_event_pointer_path=(
                official_market_event_pointer_path
            ),
            ensure_sidecar_schema=False,
        )

    def record_and_mature(
        self,
        *,
        decision_date: date,
        strict_t_minus_one: date,
        proposal_path: Path,
        proposal_hash: str,
        proposal_file_hash: str,
        replay_hash: str,
        orchestration_run_hash: str,
        rule_policy_hash: str,
        release_training_manifest_file_hash: str,
        raw_publication_manifest_hash: str,
        inference_universe_hash: str,
        model_artifact_path: Path | None = None,
        post_freeze_rows: Sequence[PortfolioMLDatasetRow] = (),
        post_freeze_input_hash: str | None = None,
        natural_forward_deadline_at: datetime | None = None,
        available_at_cutoff: datetime | None = None,
    ) -> dict[str, object]:
        natural_forward_deadline = _normalize_deadline(
            natural_forward_deadline_at
        )
        if strict_t_minus_one >= decision_date:
            raise ValueError("market context must be strictly before decision_date")
        if _file_hash(proposal_path) != proposal_file_hash:
            raise ValueError("proposal file hash mismatch")
        proposal = load_allocation_proposal(
            proposal_path=proposal_path,
            expected_proposal_hash=proposal_hash,
            expected_replay_hash=replay_hash,
        )
        if date.fromisoformat(proposal.decision_date) != decision_date:
            raise ValueError("proposal decision_date mismatch")
        reference_observation: dict[str, object] | None = None
        if self._promotion_reference_path is not None:
            if model_artifact_path is None or post_freeze_input_hash is None:
                raise ValueError(
                    "promotion reference requires model artifact and post-freeze input"
                )
            assert self._promotion_reference_file_hash is not None
            reference_observation = build_promotion_observation(
                reference_path=self._promotion_reference_path,
                expected_reference_file_hash=(
                    self._promotion_reference_file_hash
                ),
                model_artifact_path=model_artifact_path,
                rows=post_freeze_rows,
                calibrated_probability_by_symbol_bp={
                    signal.stock_code: signal.downside_probability_bp
                    for signal in proposal.signals
                },
                inference_input_hash=post_freeze_input_hash,
                proposal_hash=proposal_hash,
                promotion_policy_hash=proposal.policy_hash,
            )
        elif model_artifact_path is not None or post_freeze_rows or (
            post_freeze_input_hash is not None
        ):
            raise ValueError(
                "post-freeze promotion inputs require a frozen reference"
            )
        paper_state_db_path = self._paper_state_db_path
        if paper_state_db_path is None:
            raise RuntimeError(
                "paper state db is required for observation recording"
            )
        ledger = load_t_minus_one_paper_ledger(
            state_db_path=paper_state_db_path,
            portfolio_id=self._portfolio_id,
            decision_date=decision_date,
        )
        symbols = tuple(
            sorted(
                set(ledger.current_weights.symbol_weights_bp)
                | {signal.stock_code for signal in proposal.signals}
                | set(proposal.requested_weights.symbol_weights_bp)
            )
        )
        market_contexts = self._market.read_contexts(
            symbols=symbols,
            strict_t_minus_one=strict_t_minus_one,
        )
        positions = {
            item.stock_code: item for item in ledger.snapshot.positions
        }
        contexts = tuple(
            PortfolioAllocationContextRow(
                stock_code=symbol,
                current_weight_bp=ledger.current_weights.weight_for(symbol),
                stock_name=market_contexts[symbol].stock_name,
                sector_id=None,
                # 缺 thesis/health 時依規格 fail closed 為 WATCH。
                health_state="WATCH",
                hard_risk_reasons=(),
                reference_price=market_contexts[symbol].close_price,
                current_shares=(
                    positions[symbol].quantity
                    if symbol in positions
                    else 0
                ),
                median_volume_20d_shares=(
                    market_contexts[symbol].median_volume_20d_shares
                ),
                market_data_as_of_date=market_contexts[symbol].price_date,
                trading_days_since_last_trade=ledger.cooldown_days.get(symbol),
            )
            for symbol in symbols
        )
        causal_state = CausalPortfolioState.create(
            as_of_date=ledger.snapshot.decision_date,
            current_weights=ledger.current_weights,
        )
        lanes: list[dict[str, object]] = []
        for alpha_bp in SHADOW_ALPHA_LANES_BP:
            preblend = deterministic_blend_weights(
                rule_weights=ledger.current_weights,
                ml_weights=proposal.requested_weights,
                alpha_bp=alpha_bp,
            )
            # 研究 lane 先完成 deterministic blend，再以 alpha=0 送入同一套
            # V4 projector；避免繞過正式 PromotionAuthorization 邊界。
            projected = self._projector.project(
                PortfolioAllocationRequestV2(
                    decision_date=decision_date.isoformat(),
                    capital_amount=ledger.snapshot.total_value,
                    rule_requested_weights=preblend,
                    ml_proposal=proposal,
                    alpha_bp=0,
                    contexts=contexts,
                    current_cash_bp=ledger.current_weights.cash_weight_bp,
                    weekly_turnover_used_bp=ledger.weekly_turnover_used_bp,
                    rule_policy_hash=rule_policy_hash,
                    causal_portfolio_state=causal_state,
                )
            )
            result = projected.to_dict()
            executable = projected.executable_weights
            constraints = tuple(
                sorted(
                    {
                        reason
                        for row in projected.rows
                        for reason in row.diagnostics
                        if (
                            "constraint" in reason
                            or "health" in reason
                            or "sector" in reason
                            or "liquidity" in reason
                            or "cash" in reason
                            or "cooldown" in reason
                            or "missing" in reason
                        )
                    }
                )
            )
            lane = {
                "alpha_bp": alpha_bp,
                "research_only": True,
                "preblend_weights": preblend.to_dict(),
                "preblend_hash": _payload_hash(preblend.to_dict()),
                "projector_input_alpha_bp": 0,
                "target_weights": projected.target_weights.to_dict(),
                "executable_weights": (
                    executable.to_dict() if executable is not None else None
                ),
                "estimated_cost": str(projected.total_estimated_cost),
                "turnover_bp": (
                    _turnover_bp(ledger.current_weights, executable)
                    if executable is not None
                    else None
                ),
                "constraint_reasons": list(constraints),
                "constraint_violation_count": sum(
                    1
                    for reason in projected.reasons
                    if reason.startswith("hard_constraint_")
                ),
                "allocation_result": result,
            }
            lane["advice"] = _advice_payload(
                alpha_bp=alpha_bp,
                result=result,
                research_only=True,
            )
            lane["lane_hash"] = _payload_hash(lane)
            lanes.append(lane)

        custody_payload = {
            "decision_at": f"{decision_date.isoformat()}T08:30:00+08:00",
            "strict_t_minus_one": strict_t_minus_one.isoformat(),
            "orchestration_run_hash": orchestration_run_hash,
            "proposal_hash": proposal_hash,
            "proposal_file_hash": proposal_file_hash,
            "replay_hash": replay_hash,
            "model_hash": proposal.model_hash,
            "dataset_identity_hash": proposal.dataset_identity_hash,
            "dataset_manifest_file_hash": proposal.dataset_manifest_file_hash,
            "policy_hash": proposal.policy_hash,
            "rule_policy_hash": rule_policy_hash,
            "universe_hash": proposal.universe_hash,
            "inference_universe_hash": inference_universe_hash,
            "release_training_manifest_file_hash": (
                release_training_manifest_file_hash
            ),
            "raw_publication_manifest_hash": raw_publication_manifest_hash,
            "paper_ledger_hash": ledger.ledger_hash,
            "causal_portfolio_state_hash": causal_state.state_hash,
            "lane_hashes": [lane["lane_hash"] for lane in lanes],
            "promotion_reference_hash": (
                reference_observation["reference_hash"]
                if reference_observation is not None
                else None
            ),
            "promotion_reference_file_hash": (
                reference_observation["reference_file_hash"]
                if reference_observation is not None
                else None
            ),
            "promotion_reference_observation_hash": (
                reference_observation["observation_hash"]
                if reference_observation is not None
                else None
            ),
            "promotion_current_distribution_hash": (
                reference_observation["current_distribution_hash"]
                if reference_observation is not None
                else None
            ),
        }
        emitted_at: datetime | None = None
        if natural_forward_deadline is not None:
            emitted_at = _utc_now()
            if emitted_at > natural_forward_deadline:
                raise TimeoutError(
                    "natural forward observation append deadline has passed"
                )
        custody_hash = _payload_hash(custody_payload)
        observation_payload: dict[str, object] = {
            "decision_at": f"{decision_date.isoformat()}T08:30:00+08:00",
            "strict_t_minus_one": strict_t_minus_one.isoformat(),
            "research_only": True,
            # 現行 Shadow lane 以 T-1 paper ledger 的 current weights 作
            # alpha=0 基準，且 sector/thesis/health 缺正式歷史 custody；它可
            # 用於日常工程觀察，但不是 production Rule Champion 的同樣本
            # replay，因此不得累積 20-day Promotion credit。
            "promotion_day_credit_allowed": False,
            "promotion_day_credit_blockers": [
                "formal_rule_champion_weight_snapshot_missing",
                "formal_sector_thesis_health_context_missing",
            ],
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
            "writes_source_database": False,
            "paper_ledger": {
                "portfolio_id": self._portfolio_id,
                "snapshot_id": ledger.snapshot.snapshot_id,
                "as_of_date": ledger.snapshot.decision_date,
                "ledger_hash": ledger.ledger_hash,
                "total_value": str(ledger.snapshot.total_value),
                "current_weights": ledger.current_weights.to_dict(),
                "weekly_turnover_used_bp": ledger.weekly_turnover_used_bp,
                "cooldown_days": dict(ledger.cooldown_days),
                "complete": True,
            },
            "market_context": {
                "source_database_mode": "ro",
                "query_only": True,
                "sector_status": "unknown_fail_closed",
                "thesis_status": "unknown_fail_closed",
                "health_status": "WATCH_fail_closed",
                "symbols": {
                    symbol: {
                        "price_date": market_contexts[symbol].price_date,
                        "close_price": (
                            str(market_contexts[symbol].close_price)
                            if market_contexts[symbol].close_price is not None
                            else None
                        ),
                        "median_volume_20d_shares": (
                            market_contexts[
                                symbol
                            ].median_volume_20d_shares
                        ),
                        "missing_reasons": list(
                            market_contexts[symbol].missing_reasons
                        ),
                    }
                    for symbol in symbols
                },
            },
            "proposal": {
                "path": str(proposal_path.resolve()),
                "hash": proposal_hash,
                "file_hash": proposal_file_hash,
                "replay_hash": replay_hash,
                "coverage_bp": proposal.coverage_bp,
                "signals": [
                    signal.to_dict() for signal in proposal.signals
                ],
            },
            "promotion_reference_observation": reference_observation,
            "custody": custody_payload,
            "lanes": lanes,
            "four_lane_weight_conservation": all(
                sum(
                    cast(
                        Mapping[str, int],
                        cast(
                            Mapping[str, object],
                            lane["preblend_weights"],
                        )["symbol_weights_bp"],
                    ).values()
                )
                + cast(
                    int,
                    cast(
                        Mapping[str, object],
                        lane["preblend_weights"],
                    )["cash_weight_bp"],
                )
                == TOTAL_WEIGHT_BP
                for lane in lanes
            ),
            "future_prefix_violation_count": 0,
            "pit_violation_count": 0,
            "constraint_violation_count": sum(
                cast(int, lane["constraint_violation_count"])
                for lane in lanes
            ),
        }
        if emitted_at is not None:
            observation_payload["emitted_at"] = emitted_at.isoformat(
                timespec="microseconds"
            )
        record, idempotent = self._repository.append_observation(
            decision_date=decision_date.isoformat(),
            custody_hash=custody_hash,
            payload=observation_payload,
            natural_forward_deadline_at=natural_forward_deadline,
        )
        observation_path = self._write_immutable_record(
            record,
            prefix="observation",
        )
        maturity_availability_cutoff = _normalize_availability_cutoff(
            available_at_cutoff
        )
        if maturity_availability_cutoff is None:
            maturity_availability_cutoff = _utc_now()
        if natural_forward_deadline is not None:
            # A forward observation has a hard emission deadline.  Keep the
            # post-append outcome scan out of that critical path; the common
            # orchestration status exit performs the same maturity refresh
            # with the real completion clock after the observation is safely
            # emitted.
            evidence = self._write_evidence(
                self._aggregate_evidence(cutoff_date=strict_t_minus_one)
            )
            maturity_deferred_for_forward_deadline = True
        else:
            evidence = self.mature_and_summarize(
                cutoff_date=strict_t_minus_one,
                available_at_cutoff=maturity_availability_cutoff,
            )
            maturity_deferred_for_forward_deadline = False
        recorded_lanes = _require_sequence(record["lanes"], "record.lanes")
        rule_lane = _require_mapping(recorded_lanes[0], "record.lanes[0]")
        rule_advice = _require_mapping(
            rule_lane.get("advice"),
            "record.lanes[0].advice",
        )
        production_advice = {
            **rule_advice,
            "research_only": False,
            "source_lane_alpha_bp": 0,
            "selected_alpha_bp": 0,
            "formal_oos_allowed": False,
            "broker_order_allowed": False,
            "apply_rebalance": False,
            "selection_reason": "machine_promotion_evidence_insufficient_rule_only",
        }
        production_advice_body = dict(
            cast(Mapping[str, object], production_advice)
        )
        production_advice_payload = {
            **production_advice_body,
            "advice_hash": _payload_hash(production_advice_body),
        }
        production_advice_path = (
            self._artifact_root
            / "production_advice"
            / f"{decision_date.isoformat()}_alpha_0.json"
        )
        _write_json(production_advice_path, production_advice_payload)
        return {
            "status": "shadow_observation_recorded",
            "observation_recorded": True,
            "shadow_day_credit_allowed": False,
            "observation_idempotent": idempotent,
            "observation_revision": record["revision"],
            "observation_hash": record["record_hash"],
            "observation_path": str(observation_path.resolve()),
            "observation_emitted_at": record.get("emitted_at"),
            "natural_forward_deadline_at": (
                natural_forward_deadline.isoformat(timespec="microseconds")
                if natural_forward_deadline is not None
                else None
            ),
            "maturity_available_at_cutoff": evidence.get(
                "available_at_cutoff"
            ),
            "maturity_deferred_for_forward_deadline": (
                maturity_deferred_for_forward_deadline
            ),
            "sidecar_database_path": str(self._repository.path.resolve()),
            "lane_count": len(lanes),
            "lane_alphas_bp": list(SHADOW_ALPHA_LANES_BP),
            "evidence_status": evidence["status"],
            "evidence_hash": evidence["evidence_hash"],
            "evidence_path": evidence["evidence_path"],
            "matured_observation_count": evidence[
                "matured_observation_count"
            ],
            "promotion_reference_observation_hash": (
                reference_observation["observation_hash"]
                if reference_observation is not None
                else None
            ),
            "promotion_current_distribution_hash": (
                reference_observation["current_distribution_hash"]
                if reference_observation is not None
                else None
            ),
            "promotion_reference_metrics_hash": evidence.get(
                "promotion_reference_metrics_hash"
            ),
            "promotion_reference_metrics_path": evidence.get(
                "promotion_reference_metrics_path"
            ),
            "promotion_reference_metrics_file_hash": evidence.get(
                "promotion_reference_metrics_file_hash"
            ),
            "latest_reference_metrics_pointer_path": evidence.get(
                "latest_reference_metrics_pointer_path"
            ),
            "compatible_promotion_evidence_path": evidence.get(
                "compatible_promotion_evidence_path"
            ),
            "production_advice_path": str(
                production_advice_path.resolve()
            ),
            "production_advice_hash": production_advice_payload[
                "advice_hash"
            ],
            "selected_alpha_bp": 0,
            "formal_oos_allowed": False,
            "production_action_allowed": False,
            "broker_order_allowed": False,
            "writes_source_database": False,
        }

    def mature_and_summarize(
        self,
        *,
        cutoff_date: date,
        available_at_cutoff: datetime | None = None,
    ) -> dict[str, object]:
        normalized_availability_cutoff = _normalize_availability_cutoff(
            available_at_cutoff
        )
        outcome_record_count_before = len(self._repository.outcomes())
        corporate_action_custody = _load_official_market_event_custody(
            self._official_market_event_pointer_path
        )
        for observation in self._repository.latest_observations():
            observation_hash = _require_text(
                observation.get("record_hash"),
                "observation.record_hash",
            )
            outcome = self._mature_one(
                observation=observation,
                cutoff_date=cutoff_date,
                corporate_action_custody=corporate_action_custody,
                available_at_cutoff=normalized_availability_cutoff,
            )
            if outcome is None:
                continue
            outcome_custody = _payload_hash(
                {
                    "observation_hash": observation_hash,
                    "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
                    "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
                    "outcome_source_custody_hash": outcome[
                        "outcome_source_custody_hash"
                    ],
                }
            )
            record, _idempotent = self._repository.append_outcome(
                observation_hash=observation_hash,
                custody_hash=outcome_custody,
                payload=outcome,
            )
            self._write_immutable_record(record, prefix="outcome")
        summary = self._aggregate_evidence(cutoff_date=cutoff_date)
        evidence = self._write_evidence(summary)
        outcome_record_count_after = len(self._repository.outcomes())
        return {
            **evidence,
            "outcome_record_count_before": outcome_record_count_before,
            "outcome_record_count_after": outcome_record_count_after,
            "outcome_records_appended": (
                outcome_record_count_after - outcome_record_count_before
            ),
            "available_at_cutoff": (
                normalized_availability_cutoff.isoformat()
                if normalized_availability_cutoff is not None
                else None
            ),
        }

    def _mature_one(
        self,
        *,
        observation: Mapping[str, object],
        cutoff_date: date,
        corporate_action_custody: OfficialMarketEventCustody,
        available_at_cutoff: datetime | None = None,
    ) -> dict[str, object] | None:
        decision_date = date.fromisoformat(
            _require_text(
                observation.get("decision_date"),
                "observation.decision_date",
            )
        )
        proposal = _require_mapping(
            observation.get("proposal"),
            "observation.proposal",
        )
        signals = tuple(
            _require_mapping(item, "observation.signal")
            for item in _require_sequence(
                proposal.get("signals"),
                "observation.proposal.signals",
            )
        )
        if cutoff_date < decision_date:
            return None
        symbols = tuple(
            sorted(
                {
            _require_text(signal.get("stock_code"), "signal.stock_code")
            for signal in signals
                }
            )
        )
        blockers: list[str] = []
        downside_outcomes: list[dict[str, object]] = []
        source_rows_used: list[str] = []
        latest_used_date: date | None = None
        if not symbols:
            blockers.append("promotion_signal_universe_empty")
        if not corporate_action_custody.ready:
            blockers.append(
                corporate_action_custody.blocker
                or "corporate_action_custody_unavailable"
            )
        else:
            assert corporate_action_custody.manifest_hash is not None
            assert corporate_action_custody.canonical_events_hash is not None
            for symbol in symbols:
                sessions = self._market.read_outcome_sessions(
                    symbol=symbol,
                    start_date=decision_date,
                    cutoff_date=cutoff_date,
                    limit=max(PROMOTION_HORIZONS),
                )
                sessions = tuple(
                    row
                    for row in sessions
                    if _available_by(
                        row.available_at,
                        cutoff=available_at_cutoff,
                    )
                )
                if not sessions:
                    blockers.append(f"{symbol}:stock_session_calendar_missing")
                    continue
                required_benchmark_dates = {
                    sessions[0].observed_date,
                    *(
                        sessions[horizon - 1].observed_date
                        for horizon in PROMOTION_HORIZONS
                        if len(sessions) >= horizon
                    ),
                }
                benchmark_rows = self._market.read_taiex_rows(
                    observed_dates=required_benchmark_dates
                )
                benchmark_rows = {
                    observed_date: row
                    for observed_date, row in benchmark_rows.items()
                    if _available_by(
                        row.available_at,
                        cutoff=available_at_cutoff,
                    )
                }
                for horizon in PROMOTION_HORIZONS:
                    if len(sessions) < horizon:
                        blockers.append(
                            f"{symbol}:h{horizon}:"
                            f"symbol_sessions_insufficient:{len(sessions)}/{horizon}"
                        )
                        continue
                    entry = sessions[0]
                    exit_row = sessions[horizon - 1]
                    if entry.open_price is None:
                        blockers.append(f"{symbol}:h{horizon}:stock_open_missing")
                        continue
                    if exit_row.close_price is None:
                        blockers.append(f"{symbol}:h{horizon}:stock_close_missing")
                        continue
                    benchmark_entry = benchmark_rows.get(entry.observed_date)
                    benchmark_exit = benchmark_rows.get(exit_row.observed_date)
                    if (
                        benchmark_entry is None
                        or benchmark_entry.open_price is None
                    ):
                        blockers.append(
                            f"{symbol}:h{horizon}:benchmark_open_missing"
                        )
                        continue
                    if (
                        benchmark_exit is None
                        or benchmark_exit.close_price is None
                    ):
                        blockers.append(
                            f"{symbol}:h{horizon}:benchmark_close_missing"
                        )
                        continue
                    interval_blocker = (
                        corporate_action_custody.interval_blocker(
                            symbol=symbol,
                            entry_date=entry.observed_date,
                            exit_date=exit_row.observed_date,
                        )
                    )
                    if interval_blocker is not None:
                        blockers.append(
                            f"{symbol}:h{horizon}:{interval_blocker}"
                        )
                        continue
                    calendar = tuple(
                        item.observed_date.isoformat()
                        for item in sessions[:horizon]
                    )
                    calendar_hash = _payload_hash(
                        {
                            "calendar_type": "per_symbol_market_sessions",
                            "symbol": symbol,
                            "decision_date": decision_date.isoformat(),
                            "horizon_trading_sessions": horizon,
                            "dates": list(calendar),
                        }
                    )
                    stock_source_rows_hash = _payload_hash(
                        {
                            "source_id": "sqlite.daily_prices",
                            "entry_source_row_hash": entry.source_row_hash,
                            "exit_source_row_hash": exit_row.source_row_hash,
                        }
                    )
                    benchmark_source_rows_hash = _payload_hash(
                        {
                            "source_id": "sqlite.market_indices",
                            "benchmark_id": "TAIEX",
                            "entry_source_row_hash": (
                                benchmark_entry.source_row_hash
                            ),
                            "exit_source_row_hash": (
                                benchmark_exit.source_row_hash
                            ),
                        }
                    )
                    stock_return_bp = _return_bp(
                        entry=entry.open_price,
                        exit_value=exit_row.close_price,
                    )
                    benchmark_return_bp = _return_bp(
                        entry=benchmark_entry.open_price,
                        exit_value=benchmark_exit.close_price,
                    )
                    benchmark_excess_return_bp = (
                        stock_return_bp
                        - benchmark_return_bp
                        - _BUY_COST_BP
                        - _SELL_COST_BP
                    )
                    actual_downside = int(benchmark_excess_return_bp < 0)
                    available_at = max(
                        entry.available_at,
                        exit_row.available_at,
                        benchmark_entry.available_at,
                        benchmark_exit.available_at,
                    )
                    revision_id = _payload_hash(
                        {
                            "stock_entry_revision_id": entry.revision_id,
                            "stock_exit_revision_id": exit_row.revision_id,
                            "benchmark_entry_revision_id": (
                                benchmark_entry.revision_id
                            ),
                            "benchmark_exit_revision_id": (
                                benchmark_exit.revision_id
                            ),
                            "corporate_action_manifest_hash": (
                                corporate_action_custody.manifest_hash
                            ),
                            "corporate_action_canonical_events_hash": (
                                corporate_action_custody.canonical_events_hash
                            ),
                        }
                    )
                    outcome_body: dict[str, object] = {
                        "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
                        "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
                        "decision_date": decision_date.isoformat(),
                        "symbol": symbol,
                        "horizon_trading_sessions": horizon,
                        "entry_date": entry.observed_date.isoformat(),
                        "horizon_end_date": exit_row.observed_date.isoformat(),
                        "stock_open_to_close_return_bp": stock_return_bp,
                        "taiex_open_to_close_return_bp": benchmark_return_bp,
                        "buy_cost_bp": _BUY_COST_BP,
                        "sell_cost_bp": _SELL_COST_BP,
                        "benchmark_excess_return_bp": (
                            benchmark_excess_return_bp
                        ),
                        "actual_downside": actual_downside,
                        "stock_source_rows_hash": stock_source_rows_hash,
                        "benchmark_source_rows_hash": (
                            benchmark_source_rows_hash
                        ),
                        "available_at": available_at,
                        "revision_id": revision_id,
                        "calendar_hash": calendar_hash,
                        "corporate_action_manifest_hash": (
                            corporate_action_custody.manifest_hash
                        ),
                        "corporate_action_canonical_events_hash": (
                            corporate_action_custody.canonical_events_hash
                        ),
                        "source_custody": {
                            "stock_rows": [
                                dict(entry.source_payload),
                                dict(exit_row.source_payload),
                            ],
                            "benchmark_rows": [
                                dict(benchmark_entry.source_payload),
                                dict(benchmark_exit.source_payload),
                            ],
                            "symbol_session_calendar": list(calendar),
                            "availability_basis": (
                                "official_market_session_end_of_day_conservative"
                            ),
                            "revision_basis": (
                                "content_addressed_source_row_snapshot"
                            ),
                            "benchmark_id": "TAIEX",
                            "label_formula": (
                                "stock_return_bp-taiex_return_bp-25-55"
                            ),
                        },
                    }
                    outcome = {
                        **outcome_body,
                        "outcome_hash": _payload_hash(outcome_body),
                    }
                    downside_outcomes.append(outcome)
                    source_rows_used.extend(
                        (
                            entry.source_row_hash,
                            exit_row.source_row_hash,
                            benchmark_entry.source_row_hash,
                            benchmark_exit.source_row_hash,
                        )
                    )
                    if (
                        latest_used_date is None
                        or exit_row.observed_date > latest_used_date
                    ):
                        latest_used_date = exit_row.observed_date
        outcome_keys = {
            (
                _require_text(item.get("symbol"), "outcome.symbol"),
                _require_int(
                    item.get("horizon_trading_sessions"),
                    "outcome.horizon_trading_sessions",
                ),
            )
            for item in downside_outcomes
        }
        completed_horizons = tuple(
            horizon
            for horizon in PROMOTION_HORIZONS
            if symbols
            and all((symbol, horizon) in outcome_keys for symbol in symbols)
        )
        if completed_horizons == PROMOTION_HORIZONS:
            status = "matured_all_horizons"
        elif downside_outcomes:
            status = "partial_horizon_maturity"
        else:
            status = "blocked"
        source_custody_body: dict[str, object] = {
            "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
            "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
            "corporate_action_manifest_hash": (
                corporate_action_custody.manifest_hash
            ),
            "corporate_action_manifest_file_hash": (
                corporate_action_custody.manifest_file_hash
            ),
            "corporate_action_canonical_events_hash": (
                corporate_action_custody.canonical_events_hash
            ),
            "corporate_action_source_registry_hash": (
                corporate_action_custody.source_registry_hash
            ),
            "completed_horizons_trading_sessions": list(completed_horizons),
            "downside_outcome_hashes": [
                item["outcome_hash"]
                for item in sorted(
                    downside_outcomes,
                    key=lambda value: (
                        str(value["symbol"]),
                        _require_int(
                            value["horizon_trading_sessions"],
                            "horizon_trading_sessions",
                        ),
                    ),
                )
            ],
            "source_row_hashes": sorted(set(source_rows_used)),
            "blockers": sorted(set(blockers)),
        }
        outcome_source_custody_hash = _payload_hash(source_custody_body)
        return {
            "status": status,
            "decision_date": decision_date.isoformat(),
            "completed_horizons_trading_sessions": list(completed_horizons),
            "latest_used_date": (
                latest_used_date.isoformat()
                if latest_used_date is not None
                else None
            ),
            "trading_day_count": max(completed_horizons, default=0),
            "price_path_hash": _payload_hash(
                {
                    "source_row_hashes": sorted(set(source_rows_used)),
                    "downside_outcome_hashes": source_custody_body[
                        "downside_outcome_hashes"
                    ],
                }
            ),
            "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
            "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
            "outcome_source_custody": source_custody_body,
            "outcome_source_custody_hash": outcome_source_custody_hash,
            "lane_metrics": {},
            "calibration": {
                "status": "not_evaluated",
                "reason": (
                    "per_horizon_calibration_is_evaluated_by_frozen_reference"
                ),
            },
            "downside_outcomes": sorted(
                downside_outcomes,
                key=lambda item: (
                    str(item["symbol"]),
                    _require_int(
                        item["horizon_trading_sessions"],
                        "horizon_trading_sessions",
                    ),
                ),
            ),
            "feasible_fill_coverage_bp": None,
            "blockers": sorted(set(blockers)),
            "future_prefix_violation_count": observation.get(
                "future_prefix_violation_count"
            ),
            "pit_violation_count": observation.get("pit_violation_count"),
            "constraint_violation_count": observation.get(
                "constraint_violation_count"
            ),
        }

    def _aggregate_evidence(
        self,
        *,
        cutoff_date: date,
    ) -> dict[str, object]:
        all_observations = self._repository.observations()
        observations = self._repository.latest_observations()
        creditable_observations = tuple(
            item
            for item in observations
            if item.get("promotion_day_credit_allowed") is True
        )
        observation_hashes = tuple(
            _require_text(item.get("record_hash"), "observation.record_hash")
            for item in observations
        )
        all_outcomes = self._repository.outcomes()
        outcomes = self._repository.latest_outcomes(
            observation_hashes=observation_hashes
        )
        creditable_observation_hashes = {
            _require_text(
                item.get("record_hash"),
                "creditable_observation.record_hash",
            )
            for item in creditable_observations
        }
        creditable_outcomes = tuple(
            outcome
            for outcome in outcomes
            if _require_text(
                outcome.get("observation_hash"),
                "outcome.observation_hash",
            )
            in creditable_observation_hashes
        )
        matured_outcomes = tuple(
            outcome
            for outcome in creditable_outcomes
            if outcome.get("status") == "matured_all_horizons"
            and tuple(
                _require_int(item, "completed_horizon")
                for item in _require_sequence(
                    outcome.get("completed_horizons_trading_sessions"),
                    "completed_horizons_trading_sessions",
                )
            )
            == PROMOTION_HORIZONS
        )
        matured_count = len(matured_outcomes)
        blockers: list[str] = []
        for outcome in outcomes:
            blockers.extend(
                _require_text(item, "outcome.blocker")
                for item in _require_sequence(
                    outcome.get("blockers", ()),
                    "outcome.blockers",
                )
            )
        if matured_count < 4:
            blockers.append("valid_oos_folds_insufficient")
        if len(creditable_observations) != len(observations):
            blockers.append(
                "shadow_rule_baseline_or_context_not_formal_no_promotion_credit"
            )
        reference_metrics: Mapping[str, object] | None = None
        reference_metrics_path: str | None = None
        reference_metrics_file_hash: str | None = None
        reference_metrics_pointer_path: str | None = None
        if (
            self._promotion_reference_path is not None
            and self._promotion_reference_file_hash is not None
        ):
            reference_observations = tuple(
                _require_mapping(
                    item.get("promotion_reference_observation"),
                    "observation.promotion_reference_observation",
                )
                for item in creditable_observations
                if item.get("promotion_reference_observation") is not None
            )
            downside_outcomes = tuple(
                _require_mapping(item, "outcome.downside_outcome")
                for outcome in creditable_outcomes
                for item in _require_sequence(
                    outcome.get("downside_outcomes", ()),
                    "outcome.downside_outcomes",
                )
            )
            reference_metrics = evaluate_matured_promotion_reference(
                reference_path=self._promotion_reference_path,
                expected_reference_file_hash=(
                    self._promotion_reference_file_hash
                ),
                observations=reference_observations,
                downside_outcomes=downside_outcomes,
            )
            metrics_publication = self._write_reference_metrics(
                reference_metrics
            )
            reference_metrics_path = str(
                metrics_publication["reference_metrics_path"]
            )
            reference_metrics_file_hash = str(
                metrics_publication["reference_metrics_file_hash"]
            )
            reference_metrics_pointer_path = str(
                metrics_publication["latest_reference_metrics_pointer_path"]
            )
            blockers.extend(
                _require_text(item, "promotion_reference.blocker")
                for item in _require_sequence(
                    reference_metrics.get("blockers"),
                    "promotion_reference.blockers",
                )
            )
        else:
            if matured_count < 20:
                blockers.append(
                    f"matured_shadow_days_insufficient:{matured_count}/20"
                )
            blockers.extend(
                [
                    "uncalibrated_probability_baseline_missing",
                    "frozen_feature_psi_reference_missing",
                ]
            )
        coverage_values = [
            _require_int(
                _require_mapping(item.get("proposal"), "proposal").get(
                    "coverage_bp"
                ),
                "coverage_bp",
            )
            for item in creditable_observations
        ]
        average_coverage = (
            sum(coverage_values) // len(coverage_values)
            if coverage_values
            else None
        )
        feasible_fill_values = tuple(
            value
            for outcome in matured_outcomes
            for value in (outcome.get("feasible_fill_coverage_bp"),)
            if isinstance(value, int) and not isinstance(value, bool)
        )
        formal_metrics: dict[str, object] = {
            "valid_oos_fold_count": None,
            "winning_oos_fold_count": None,
            "shadow_observation_days": matured_count,
            "block_bootstrap_excess_return_lower_95_bp": None,
            "calibration_ece_bp": (
                reference_metrics.get("calibration_ece_bp")
                if reference_metrics is not None
                else None
            ),
            "calibrated_brier_bp": (
                reference_metrics.get("calibrated_brier_bp")
                if reference_metrics is not None
                else None
            ),
            "uncalibrated_brier_bp": (
                reference_metrics.get("uncalibrated_brier_bp")
                if reference_metrics is not None
                else None
            ),
            "feature_psi_bp": (
                reference_metrics.get("feature_psi_bp")
                if reference_metrics is not None
                else None
            ),
            "family_psi_bp": (
                reference_metrics.get("family_psi_bp")
                if reference_metrics is not None
                else None
            ),
            "psi_bp": (
                reference_metrics.get("psi_bp")
                if reference_metrics is not None
                else None
            ),
            "core_coverage_bp": average_coverage,
            "enriched_cohort_coverage_bp": average_coverage,
            "feasible_fill_coverage_bp": (
                sum(feasible_fill_values) // len(feasible_fill_values)
                if feasible_fill_values
                else None
            ),
            "future_prefix_violation_count": sum(
                _require_int(
                    item.get("future_prefix_violation_count"),
                    "future_prefix_violation_count",
                )
                for item in creditable_observations
            ),
            "pit_violation_count": sum(
                _require_int(
                    item.get("pit_violation_count"),
                    "pit_violation_count",
                )
                for item in creditable_observations
            ),
            "constraint_violation_count": sum(
                _require_int(
                    item.get("constraint_violation_count"),
                    "constraint_violation_count",
                )
                for item in creditable_observations
            ),
        }
        return {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "status": "insufficient_evidence",
            "as_of_date": cutoff_date.isoformat(),
            "research_only": True,
            "formal_consumer_compatible": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
            "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
            "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
            "observation_count": len(observations),
            "promotion_credit_observation_count": len(
                creditable_observations
            ),
            "observation_revision_record_count": len(all_observations),
            "matured_observation_count": matured_count,
            "partial_outcome_count": sum(
                1
                for outcome in outcomes
                if outcome.get("status") == "partial_horizon_maturity"
            ),
            "blocked_outcome_count": sum(
                1
                for outcome in outcomes
                if outcome.get("status") == "blocked"
            ),
            "outcome_revision_record_count": len(all_outcomes),
            "observation_hashes": [
                item["record_hash"] for item in observations
            ],
            "outcome_hashes": [item["record_hash"] for item in outcomes],
            "formal_metrics": formal_metrics,
            "blockers": list(dict.fromkeys(blockers)),
            "compatible_promotion_evidence_path": None,
            "promotion_reference_status": (
                reference_metrics["promotion_reference_status"]
                if reference_metrics is not None
                else {
                    "uncalibrated_probability_baseline": "missing",
                    "frozen_feature_distribution": "missing",
                    "automatic_nonzero_alpha_possible_after_all_gates": False,
                    "reason": "promotion_reference_not_configured",
                }
            ),
            "promotion_reference_metrics_status": (
                reference_metrics.get("status")
                if reference_metrics is not None
                else "not_configured"
            ),
            "promotion_reference_metrics_hash": (
                reference_metrics.get("metrics_hash")
                if reference_metrics is not None
                else None
            ),
            "promotion_reference_metrics_path": reference_metrics_path,
            "promotion_reference_metrics_file_hash": (
                reference_metrics_file_hash
            ),
            "latest_reference_metrics_pointer_path": (
                reference_metrics_pointer_path
            ),
        }

    def _write_reference_metrics(
        self,
        metrics: Mapping[str, object],
    ) -> dict[str, object]:
        metrics_hash = _require_sha256(
            metrics.get("metrics_hash"),
            "promotion reference metrics_hash",
        )
        body = dict(metrics)
        body.pop("metrics_hash", None)
        if _payload_hash(body) != metrics_hash:
            raise ValueError("promotion reference metrics canonical hash mismatch")
        immutable_path = (
            self._artifact_root
            / "reference_metrics"
            / f"{metrics_hash[7:]}.json"
        )
        canonical_metrics = dict(metrics)
        if immutable_path.exists():
            existing = _require_mapping(
                json.loads(immutable_path.read_text(encoding="utf-8")),
                "immutable promotion reference metrics",
            )
            if existing != canonical_metrics:
                raise ValueError(
                    "immutable promotion reference metrics hash collision"
                )
        else:
            _write_json(immutable_path, canonical_metrics)
        metrics_file_hash = _file_hash(immutable_path)
        pointer_path = self._artifact_root / "latest_reference_metrics.json"
        pointer_payload: dict[str, object] = {
            "schema_version": "ml-allocation-reference-metrics-pointer-v1",
            "reference_metrics_hash": metrics_hash,
            "reference_metrics_file_hash": metrics_file_hash,
            "reference_metrics_path": str(immutable_path.resolve()),
            "outcome_contract_version": OUTCOME_CONTRACT_VERSION,
            "outcome_contract_hash": OUTCOME_CONTRACT_HASH,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "broker_order_allowed": False,
        }
        _write_json(pointer_path, pointer_payload)
        return {
            **pointer_payload,
            "latest_reference_metrics_pointer_path": str(
                pointer_path.resolve()
            ),
        }

    def _write_evidence(
        self,
        summary: Mapping[str, object],
    ) -> dict[str, object]:
        body = dict(summary)
        evidence_hash = _payload_hash(body)
        payload = {**body, "evidence_hash": evidence_hash}
        immutable_path = (
            self._artifact_root
            / "evidence"
            / f"{evidence_hash[7:]}.json"
        )
        if immutable_path.exists():
            existing = json.loads(immutable_path.read_text(encoding="utf-8"))
            if existing != payload:
                raise ValueError("immutable evidence hash collision")
        else:
            _write_json(immutable_path, payload)
        _write_json(
            self._artifact_root / "latest_evidence.json",
            payload,
        )
        return {
            **payload,
            "evidence_path": str(immutable_path.resolve()),
        }

    def _write_immutable_record(
        self,
        record: Mapping[str, object],
        *,
        prefix: str,
    ) -> Path:
        record_hash = _require_text(record.get("record_hash"), "record_hash")
        path = (
            self._artifact_root
            / f"{prefix}s"
            / f"{record_hash[7:]}.json"
        )
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != record:
                raise ValueError("immutable record hash collision")
        else:
            _write_json(path, record)
        return path


def _observation_capital(observation: Mapping[str, object]) -> Decimal:
    paper = _require_mapping(
        observation.get("paper_ledger"),
        "paper_ledger",
    )
    capital = Decimal(
        _require_text(
            paper.get("total_value"),
            "paper_ledger.total_value",
        )
    )
    if not capital.is_finite() or capital <= Decimal("0"):
        raise ValueError("paper ledger total_value must be positive")
    return capital


def _return_bp(*, entry: Decimal, exit_value: Decimal) -> int:
    if entry <= Decimal("0") or exit_value <= Decimal("0"):
        raise ValueError("outcome prices must be positive")
    return int(
        (((exit_value / entry) - Decimal("1")) * Decimal(TOTAL_WEIGHT_BP)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def fixed_weight_path_metrics(
    *,
    weights: Mapping[str, object],
    price_paths: Mapping[str, Mapping[date, Decimal]],
    dates: Sequence[date],
    transaction_cost: Decimal,
    capital_amount: Decimal,
) -> dict[str, int]:
    """計算固定權重 20 日 after-cost return、MDD 與 5% CVaR（整數 bp）。"""

    if len(dates) < 2:
        raise ValueError("path metrics require at least two dates")
    if capital_amount <= Decimal("0") or transaction_cost < Decimal("0"):
        raise ValueError("capital and transaction cost are invalid")
    symbols = _require_mapping(
        weights.get("symbol_weights_bp"),
        "weights.symbol_weights_bp",
    )
    cash_bp = _require_int(weights.get("cash_weight_bp"), "cash_weight_bp")
    symbol_weights = {
        _require_text(symbol, "symbol"): _require_int(
            raw_weight,
            f"weight[{symbol}]",
        )
        for symbol, raw_weight in symbols.items()
    }
    if sum(symbol_weights.values()) + cash_bp != TOTAL_WEIGHT_BP:
        raise ValueError("weights must conserve 10000 bp")
    values: list[Decimal] = []
    for observed_date in dates:
        value = Decimal(cash_bp)
        for symbol, weight_bp in symbol_weights.items():
            series = price_paths.get(symbol)
            if series is None:
                raise ValueError(f"price path missing: {symbol}")
            start = series.get(dates[0])
            current = series.get(observed_date)
            if start is None or current is None or start <= Decimal("0"):
                raise ValueError(f"price point missing: {symbol}")
            value += Decimal(weight_bp) * current / start
        values.append(value)
    cost_bp = int(
        (
            transaction_cost
            * Decimal(TOTAL_WEIGHT_BP)
            / capital_amount
        ).to_integral_value(rounding=ROUND_HALF_UP)
    )
    after_cost_end = values[-1] - Decimal(cost_bp)
    after_cost_return_bp = int(
        (after_cost_end - Decimal(TOTAL_WEIGHT_BP)).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    peak = values[0]
    max_drawdown_bp = 0
    daily_returns: list[int] = []
    for index, value in enumerate(values):
        if value > peak:
            peak = value
        drawdown_bp = int(
            (
                (peak - value)
                * Decimal(TOTAL_WEIGHT_BP)
                / peak
            ).to_integral_value(rounding=ROUND_HALF_UP)
        )
        max_drawdown_bp = max(max_drawdown_bp, drawdown_bp)
        if index:
            prior = values[index - 1]
            daily_returns.append(
                int(
                    (
                        (value - prior)
                        * Decimal(TOTAL_WEIGHT_BP)
                        / prior
                    ).to_integral_value(rounding=ROUND_HALF_UP)
                )
            )
    loss_tail_count = max(1, (len(daily_returns) + 19) // 20)
    worst = sorted(daily_returns)[:loss_tail_count]
    cvar_loss_bp = max(0, -(sum(worst) // len(worst)))
    return {
        "after_cost_return_bp": after_cost_return_bp,
        "max_drawdown_bp": max_drawdown_bp,
        "cvar_loss_bp": cvar_loss_bp,
        "transaction_cost_bp": cost_bp,
    }


def calibration_metrics(
    rows: Sequence[tuple[int, int]],
    *,
    bin_count: int = 10,
) -> dict[str, int]:
    """以整數 bp 計算 downside probability 的 ECE 與 Brier。"""

    if not rows:
        raise ValueError("calibration rows are required")
    if isinstance(bin_count, bool) or bin_count <= 0:
        raise ValueError("bin_count must be positive")
    bins: dict[int, list[tuple[int, int]]] = {}
    squared_error_total = 0
    for probability_bp, outcome in rows:
        if (
            isinstance(probability_bp, bool)
            or not 0 <= probability_bp <= TOTAL_WEIGHT_BP
            or outcome not in {0, 1}
        ):
            raise ValueError("invalid calibration row")
        bin_id = min(
            bin_count - 1,
            probability_bp * bin_count // (TOTAL_WEIGHT_BP + 1),
        )
        bins.setdefault(bin_id, []).append((probability_bp, outcome))
        error = probability_bp - outcome * TOTAL_WEIGHT_BP
        squared_error_total += error * error
    ece_numerator = 0
    for values in bins.values():
        probability_sum = sum(item[0] for item in values)
        outcome_sum_bp = sum(item[1] for item in values) * TOTAL_WEIGHT_BP
        ece_numerator += abs(probability_sum - outcome_sum_bp)
    ece_bp = ece_numerator // len(rows)
    brier_bp = (
        squared_error_total // len(rows) // TOTAL_WEIGHT_BP
    )
    return {
        "ece_bp": ece_bp,
        "brier_bp": brier_bp,
        "observation_count": len(rows),
    }


def deterministic_block_bootstrap_lower_95_bp(
    excess_returns_bp: Sequence[int],
    *,
    block_size: int = 5,
) -> int:
    """無亂數、可重播的 circular block-bootstrap 5% 下界。"""

    if len(excess_returns_bp) < 20:
        raise ValueError("bootstrap requires at least 20 observations")
    if isinstance(block_size, bool) or block_size <= 0:
        raise ValueError("block_size must be positive")
    values = tuple(
        _require_int(item, "excess_return_bp")
        for item in excess_returns_bp
    )
    sample_count = 2_000
    seed_material = _canonical_json(
        {
            "values": list(values),
            "block_size": block_size,
            "sample_count": sample_count,
        }
    ).encode("utf-8")
    means: list[int] = []
    for sample_index in range(sample_count):
        sample: list[int] = []
        draw_index = 0
        while len(sample) < len(values):
            digest = hashlib.sha256(
                seed_material
                + sample_index.to_bytes(4, byteorder="big", signed=False)
                + draw_index.to_bytes(4, byteorder="big", signed=False)
            ).digest()
            cursor = int.from_bytes(
                digest[:8],
                byteorder="big",
                signed=False,
            ) % len(values)
            for offset in range(block_size):
                sample.append(values[(cursor + offset) % len(values)])
                if len(sample) == len(values):
                    break
            draw_index += 1
        means.append(sum(sample) // len(sample))
    ordered = sorted(means)
    index = max(0, (sample_count * 5 // 100) - 1)
    return ordered[index]


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "MLAllocationShadowCollector",
    "OBSERVATION_SCHEMA_VERSION",
    "OUTCOME_SCHEMA_VERSION",
    "SHADOW_ALPHA_LANES_BP",
    "ShadowEvidenceRepository",
    "SQLiteTMinusOneMarketReader",
    "calibration_metrics",
    "deterministic_blend_weights",
    "deterministic_block_bootstrap_lower_95_bp",
    "exact_weights_from_snapshot",
    "fixed_weight_path_metrics",
    "load_allocation_proposal",
    "load_t_minus_one_paper_ledger",
]
