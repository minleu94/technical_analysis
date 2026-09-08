"""以官方日價 overlay 建立隔離的 feature／label 影響證據。

此 consumer 只讀取 SQLite 與已驗證的 candidate overlay，將決策日的
daily-price raw features 與固定 h20 supervised labels 在記憶體中各重算一次。
它保存原始 SQLite 路徑與 overlay 候選的並列結果，不回寫 SQLite、CSV、PIT
或既有 label artifact。overlay 是事後擷取，因此 ``observed_at`` 只代表本次
研究證據觀察時間，不能被解讀成歷史決策時點可得。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from data_module.ml_daily_price_overlay import (
    DailyPriceOverlayError,
    load_daily_price_overlay,
)
from data_module.twse_historical_daily_capture import load_twse_capture


LEGACY_OVERLAY_CONSUMER_SCHEMA_VERSION = (
    "portfolio-ml-daily-price-overlay-impact.v1"
)
OVERLAY_CONSUMER_SCHEMA_VERSION = (
    "portfolio-ml-daily-price-overlay-impact.v2"
)
POST_CAPTURE_RESEARCH_MODE = "post_capture_historical_research.v2"
HORIZON_TRADING_DAYS = 20
BUY_COST_BP = 25
SELL_COST_BP = 55
TRANSACTION_COST_BP = BUY_COST_BP + SELL_COST_BP
_SHA256_PREFIX = "sha256:"
_CHUNK_BYTES = 1 << 20
_LABEL_FIELDS = (
    "benchmark_excess_return_bp",
    "downside_observed",
    "mae_loss_bp",
    "mfe_gain_bp",
    "realized_volatility_bp",
    "max_drawdown_bp",
    "tail_loss_bp",
    "fill_feasible_observed",
)
_FEATURE_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume_shares",
)


class DailyPriceOverlayConsumerError(ValueError):
    """overlay、來源 snapshot 或隔離重算不符合契約。"""


@dataclass(frozen=True)
class DailyPriceOverlayImpactResult:
    """隔離 impact artifact 的摘要。"""

    output_path: Path
    output_hash: str
    row_count: int
    # 舊欄位保留作相容，但現在明確代表事後 raw diagnostic 的差異數，
    # 不是可送進模型的 feature 影響數。
    changed_feature_count: int
    changed_label_count: int
    decision_time_feature_changed_count: int = 0


@dataclass(frozen=True)
class _PricePoint:
    date: str
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume_shares: int


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise DailyPriceOverlayConsumerError(
            f"source file cannot be read: {path}"
        ) from exc
    return _SHA256_PREFIX + digest.hexdigest()


def _required_hash(value: object, *, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if (
        len(text) != 71
        or not text.startswith(_SHA256_PREFIX)
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise DailyPriceOverlayConsumerError(
            f"{field_name} must be a sha256 digest"
        )
    return text


def _normalise_date(value: object, *, field_name: str) -> str:
    text = str(value).strip()
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise DailyPriceOverlayConsumerError(
            f"{field_name} must be YYYY-MM-DD or YYYYMMDD"
        ) from exc


def _decimal(value: object, *, field_name: str, positive: bool = True) -> Decimal:
    if value is None or isinstance(value, bool):
        raise DailyPriceOverlayConsumerError(f"{field_name} is missing")
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise DailyPriceOverlayConsumerError(
            f"{field_name} is not numeric"
        ) from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise DailyPriceOverlayConsumerError(
            f"{field_name} is not a valid positive finite number"
        )
    return parsed


def _integer(value: object, *, field_name: str) -> int:
    parsed = _decimal(value, field_name=field_name, positive=False)
    if parsed != parsed.to_integral_value() or parsed < 0:
        raise DailyPriceOverlayConsumerError(
            f"{field_name} must be a non-negative integer"
        )
    return int(parsed)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _return_bp(start: Decimal, end: Decimal) -> int:
    if start <= 0:
        raise DailyPriceOverlayConsumerError("label entry price must be positive")
    return int(
        (((end / start) - Decimal(1)) * Decimal(10_000)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _validate_price_point(point: _PricePoint, *, field_name: str) -> None:
    if point.low > min(point.open, point.close):
        raise DailyPriceOverlayConsumerError(
            f"{field_name} low is above open/close"
        )
    if point.high < max(point.open, point.close):
        raise DailyPriceOverlayConsumerError(
            f"{field_name} high is below open/close"
        )


def _point_from_mapping(
    row: Mapping[str, object],
    *,
    symbol: str,
    date_value: str,
    field_name: str,
) -> _PricePoint:
    raw_symbol = str(row.get("symbol") or symbol).strip()
    if raw_symbol != symbol:
        raise DailyPriceOverlayConsumerError(
            f"{field_name} symbol mismatch: expected {symbol}, got {raw_symbol}"
        )
    point = _PricePoint(
        date=date_value,
        symbol=symbol,
        open=_decimal(row.get("open"), field_name=f"{field_name}.open"),
        high=_decimal(row.get("high"), field_name=f"{field_name}.high"),
        low=_decimal(row.get("low"), field_name=f"{field_name}.low"),
        close=_decimal(row.get("close"), field_name=f"{field_name}.close"),
        volume_shares=_integer(
            row.get("volume_shares"),
            field_name=f"{field_name}.volume_shares",
        ),
    )
    _validate_price_point(point, field_name=field_name)
    return point


def _point_from_sqlite(row: sqlite3.Row, *, symbol: str) -> _PricePoint:
    date_value = _normalise_date(row["日期"], field_name="sqlite.日期")
    point = _PricePoint(
        date=date_value,
        symbol=str(row["證券代號"]).strip(),
        open=_decimal(row["開盤價"], field_name="sqlite.open"),
        high=_decimal(row["最高價"], field_name="sqlite.high"),
        low=_decimal(row["最低價"], field_name="sqlite.low"),
        close=_decimal(row["收盤價"], field_name="sqlite.close"),
        volume_shares=_integer(
            row["成交股數"], field_name="sqlite.volume_shares"
        ),
    )
    if point.symbol != symbol:
        raise DailyPriceOverlayConsumerError(
            f"SQLite symbol mismatch: expected {symbol}, got {point.symbol}"
        )
    _validate_price_point(point, field_name=f"sqlite.{symbol}.{date_value}")
    return point


def _open_sqlite_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise DailyPriceOverlayConsumerError(
            f"SQLite source is missing or symlinked: {resolved}"
        )
    try:
        connection = sqlite3.connect(
            f"file:{resolved.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error as exc:
        raise DailyPriceOverlayConsumerError(
            f"SQLite source cannot be opened: {resolved}"
        ) from exc


def _stock_point(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    date_value: str,
) -> _PricePoint:
    rows = connection.execute(
        """
        SELECT 日期, 證券代號, 開盤價, 最高價, 最低價, 收盤價, 成交股數
        FROM daily_prices
        WHERE 證券代號=? AND 日期=?
        """,
        (symbol, date_value.replace("-", "")),
    ).fetchall()
    if len(rows) != 1:
        raise DailyPriceOverlayConsumerError(
            f"SQLite must contain exactly one row for {symbol}/{date_value}; "
            f"found {len(rows)}"
        )
    return _point_from_sqlite(rows[0], symbol=symbol)


def _stock_window(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    dates: Sequence[str],
) -> tuple[_PricePoint, ...]:
    if not dates:
        raise DailyPriceOverlayConsumerError("label date window is empty")
    placeholders = ",".join("?" for _ in dates)
    rows = connection.execute(
        """
        SELECT 日期, 證券代號, 開盤價, 最高價, 最低價, 收盤價, 成交股數
        FROM daily_prices
        WHERE 證券代號=? AND 日期 IN ("""
        + placeholders
        + ") ORDER BY 日期",
        (symbol, *(item.replace("-", "") for item in dates)),
    ).fetchall()
    by_date: dict[str, _PricePoint] = {}
    for row in rows:
        point = _point_from_sqlite(row, symbol=symbol)
        if point.date in by_date:
            raise DailyPriceOverlayConsumerError(
                f"SQLite has duplicate stock date: {symbol}/{point.date}"
            )
        by_date[point.date] = point
    missing = [item for item in dates if item not in by_date]
    if missing:
        raise DailyPriceOverlayConsumerError(
            f"SQLite stock window is incomplete for {symbol}: {','.join(missing)}"
        )
    return tuple(by_date[item] for item in dates)


def _previous_close(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    decision_date: str,
) -> Decimal | None:
    rows = connection.execute(
        """
        SELECT 收盤價
        FROM daily_prices
        WHERE 證券代號=? AND 日期 < ?
        ORDER BY 日期 DESC
        LIMIT 1
        """,
        (symbol, decision_date.replace("-", "")),
    ).fetchall()
    if not rows:
        return None
    return _decimal(rows[0]["收盤價"], field_name="sqlite.previous_close")


def _previous_session_features(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    decision_date: str,
) -> tuple[_PricePoint, Decimal]:
    """取得決策日前最近兩個來源交易日，供盤前 feature 使用。

    同日 overlay 是事後擷取，不能參與決策日 08:30 的 model input。這裡
    強制使用 ``日期 < decision_date`` 的兩列，並用較早一列的收盤價計算
    前一收盤變動；來源沒有足夠歷史時直接 fail closed。
    """

    rows = connection.execute(
        """
        SELECT 日期, 證券代號, 開盤價, 最高價, 最低價, 收盤價, 成交股數
        FROM daily_prices
        WHERE 證券代號=? AND 日期 < ?
        ORDER BY 日期 DESC
        LIMIT 2
        """,
        (symbol, decision_date.replace("-", "")),
    ).fetchall()
    if len(rows) != 2:
        raise DailyPriceOverlayConsumerError(
            "decision-time feature source needs two prior sessions for "
            f"{symbol}/{decision_date}; found {len(rows)}"
        )
    latest = _point_from_sqlite(rows[0], symbol=symbol)
    prior = _point_from_sqlite(rows[1], symbol=symbol)
    if latest.date >= decision_date or prior.date >= latest.date:
        raise DailyPriceOverlayConsumerError(
            "decision-time feature source is not strictly before decision date "
            f"for {symbol}/{decision_date}"
        )
    return latest, prior.close


def _market_dates(
    connection: sqlite3.Connection,
    *,
    benchmark_entity: str,
    decision_date: str,
    horizon: int,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT 日期, 開盤價, 收盤價
        FROM market_indices
        WHERE 指數名稱=? AND 日期>=?
        ORDER BY 日期
        """,
        (benchmark_entity, decision_date.replace("-", "")),
    ).fetchall()
    by_date: dict[str, tuple[Decimal, Decimal]] = {}
    for row in rows:
        current = _normalise_date(row["日期"], field_name="market.日期")
        if current in by_date:
            raise DailyPriceOverlayConsumerError(
                f"benchmark has duplicate date: {current}"
            )
        by_date[current] = (
            _decimal(row["開盤價"], field_name="market.open"),
            _decimal(row["收盤價"], field_name="market.close"),
        )
    selected = tuple(sorted(by_date))[:horizon]
    if len(selected) != horizon or not selected or selected[0] != decision_date:
        raise DailyPriceOverlayConsumerError(
            "benchmark does not provide a complete decision-day horizon"
        )
    return selected


def _market_window(
    connection: sqlite3.Connection,
    *,
    benchmark_entity: str,
    dates: Sequence[str],
) -> tuple[tuple[Decimal, Decimal], ...]:
    placeholders = ",".join("?" for _ in dates)
    rows = connection.execute(
        """
        SELECT 日期, 開盤價, 收盤價
        FROM market_indices
        WHERE 指數名稱=? AND 日期 IN ("""
        + placeholders
        + ") ORDER BY 日期",
        (benchmark_entity, *(item.replace("-", "") for item in dates)),
    ).fetchall()
    by_date: dict[str, tuple[Decimal, Decimal]] = {}
    for row in rows:
        current = _normalise_date(row["日期"], field_name="market.日期")
        by_date[current] = (
            _decimal(row["開盤價"], field_name="market.open"),
            _decimal(row["收盤價"], field_name="market.close"),
        )
    if tuple(sorted(by_date)) != tuple(dates):
        raise DailyPriceOverlayConsumerError("benchmark window identity mismatch")
    return tuple(by_date[item] for item in dates)


def _mae_loss_bp(entry: Decimal, path: Sequence[_PricePoint]) -> int:
    lows = [point.low for point in path if point.low > 0]
    if not lows:
        return 10_000
    minimum_return = _return_bp(entry, min(lows))
    return max(0, -minimum_return)


def _mfe_gain_bp(entry: Decimal, path: Sequence[_PricePoint]) -> int:
    highs = [point.high for point in path if point.high > 0]
    if not highs:
        return 0
    return min(10_000, max(0, _return_bp(entry, max(highs))))


def _close_returns_bp(path: Sequence[_PricePoint]) -> tuple[int, ...]:
    return tuple(
        _return_bp(previous.close, current.close)
        for previous, current in zip(path, path[1:])
    )


def _realized_volatility_bp(path: Sequence[_PricePoint]) -> int:
    returns = _close_returns_bp(path)
    if len(returns) < 2:
        return 0
    count = Decimal(len(returns))
    mean = sum((Decimal(value) for value in returns), Decimal(0)) / count
    variance = (
        sum(
            ((Decimal(value) - mean) ** 2 for value in returns),
            Decimal(0),
        )
        / count
    )
    return min(
        10_000,
        max(0, int(variance.sqrt().quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))),
    )


def _max_drawdown_bp(path: Sequence[_PricePoint]) -> int:
    closes = [point.close for point in path if point.close > 0]
    if not closes:
        return 10_000
    peak = closes[0]
    worst = 0
    for current in closes:
        peak = max(peak, current)
        if peak <= 0:
            continue
        drawdown = int(
            (((peak - current) / peak) * Decimal(10_000)).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_EVEN,
            )
        )
        worst = max(worst, drawdown)
    return min(10_000, worst)


def _tail_loss_bp(path: Sequence[_PricePoint]) -> int:
    returns = tuple(sorted(_close_returns_bp(path)))
    if not returns:
        return 10_000
    tail_count = max(1, (len(returns) + 4) // 5)
    tail_mean = sum(
        (Decimal(value) for value in returns[:tail_count]),
        Decimal(0),
    ) / Decimal(tail_count)
    return min(
        10_000,
        max(0, int((-tail_mean).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))),
    )


def _fill_feasible(point: _PricePoint) -> bool:
    return point.high > point.low and point.low <= point.open <= point.high


def _label_payload(
    *,
    path: Sequence[_PricePoint],
    benchmark: Sequence[tuple[Decimal, Decimal]],
    benchmark_dates: Sequence[str],
    benchmark_entity: str,
    source_kind: str,
) -> dict[str, Any]:
    if len(path) != len(benchmark) or len(path) != len(benchmark_dates):
        raise DailyPriceOverlayConsumerError(
            "label stock and benchmark evidence lengths must match"
        )
    entry = path[0].open
    stock_return = _return_bp(entry, path[-1].close)
    benchmark_return = _return_bp(benchmark[0][0], benchmark[-1][1])
    excess = stock_return - benchmark_return - TRANSACTION_COST_BP
    return {
        "benchmark_excess_return_bp": excess,
        "downside_observed": int(excess < 0),
        "mae_loss_bp": _mae_loss_bp(entry, path),
        "mfe_gain_bp": _mfe_gain_bp(entry, path),
        "realized_volatility_bp": _realized_volatility_bp(path),
        "max_drawdown_bp": _max_drawdown_bp(path),
        "tail_loss_bp": _tail_loss_bp(path),
        "fill_feasible_observed": int(_fill_feasible(path[0])),
        "horizon_end_date": path[-1].date,
        "return_evidence": {
            "stock_entry_date": path[0].date,
            "stock_entry_open": _decimal_text(path[0].open),
            "stock_exit_date": path[-1].date,
            "stock_exit_close": _decimal_text(path[-1].close),
            "stock_return_bp": stock_return,
            "benchmark_entity": benchmark_entity,
            "benchmark_entry_date": benchmark_dates[0],
            "benchmark_entry_open": _decimal_text(benchmark[0][0]),
            "benchmark_exit_date": benchmark_dates[-1],
            "benchmark_exit_close": _decimal_text(benchmark[-1][1]),
            "benchmark_return_bp": benchmark_return,
            "transaction_cost_bp": TRANSACTION_COST_BP,
            "buy_cost_bp": BUY_COST_BP,
            "sell_cost_bp": SELL_COST_BP,
            "excess_formula": (
                "stock_return_bp - benchmark_return_bp - "
                "transaction_cost_bp"
            ),
            "source_kind": source_kind,
            "decimal_rounding": "ROUND_HALF_EVEN to integer bp",
        },
    }


def _feature_payload(
    *,
    original: _PricePoint,
    candidate: _PricePoint,
    previous_close: Decimal | None,
) -> tuple[dict[str, Any], int]:
    values: dict[str, tuple[str | int, str | int]] = {
        "daily_prices.open": (
            _decimal_text(original.open),
            _decimal_text(candidate.open),
        ),
        "daily_prices.high": (
            _decimal_text(original.high),
            _decimal_text(candidate.high),
        ),
        "daily_prices.low": (
            _decimal_text(original.low),
            _decimal_text(candidate.low),
        ),
        "daily_prices.close": (
            _decimal_text(original.close),
            _decimal_text(candidate.close),
        ),
        "daily_prices.volume_shares": (
            original.volume_shares,
            candidate.volume_shares,
        ),
    }
    if previous_close is not None:
        values["daily_prices.close_to_previous_close_bp"] = (
            _return_bp(previous_close, original.close),
            _return_bp(previous_close, candidate.close),
        )
    result: dict[str, Any] = {}
    changed = 0
    for feature_id, (before, after) in sorted(values.items()):
        is_changed = before != after
        changed += int(is_changed)
        result[feature_id] = {
            "original": before,
            "candidate": after,
            "changed": is_changed,
            "recomputed": True,
            "feature_role": "post_close_raw_price_diagnostic_only",
            "used_for_model_features": False,
        }
    return result, changed


def _decision_time_feature_payload(
    *,
    previous_session: _PricePoint,
    previous_close: Decimal,
    decision_date: str,
    source_available_at: datetime | str | None = None,
) -> dict[str, Any]:
    """建立嚴格盤前可得的 feature 值，不接受決策日或之後資料。"""

    if previous_session.date >= decision_date:
        raise DailyPriceOverlayConsumerError(
            "same-day or future price cannot be used as decision-time features: "
            f"{previous_session.symbol}/{previous_session.date} >= {decision_date}"
        )
    if source_available_at is not None:
        try:
            raw_available_at = (
                source_available_at
                if isinstance(source_available_at, datetime)
                else datetime.fromisoformat(
                    str(source_available_at).replace("Z", "+00:00")
                )
            )
        except (TypeError, ValueError) as exc:
            raise DailyPriceOverlayConsumerError(
                "decision-time feature availability must be aware ISO datetime"
            ) from exc
        decision_cutoff = datetime.fromisoformat(
            f"{decision_date}T08:30:00+08:00"
        )
        if raw_available_at.tzinfo is None or raw_available_at > decision_cutoff:
            raise DailyPriceOverlayConsumerError(
                "late price source cannot be used as decision-time features: "
                f"{raw_available_at.isoformat()} > {decision_cutoff.isoformat()}"
            )
    values: dict[str, str | int] = {
        "daily_prices.open": _decimal_text(previous_session.open),
        "daily_prices.high": _decimal_text(previous_session.high),
        "daily_prices.low": _decimal_text(previous_session.low),
        "daily_prices.close": _decimal_text(previous_session.close),
        "daily_prices.volume_shares": previous_session.volume_shares,
        "daily_prices.close_to_previous_close_bp": _return_bp(
            previous_close,
            previous_session.close,
        ),
    }
    result: dict[str, Any] = {}
    for feature_id, value in sorted(values.items()):
        result[feature_id] = {
            "value": value,
            "original": value,
            "candidate": value,
            "changed": False,
            "recomputed": True,
            "feature_role": "decision_time_model_input",
            "used_for_model_features": True,
            "source_date": previous_session.date,
            "source_symbol": previous_session.symbol,
            "available_before_decision": True,
            "availability_basis": (
                "source date is strictly before decision date; daily source has "
                "no intraday availability timestamp"
            ),
            "intraday_available_at": None,
        }
    return result


def _verify_official_overlay(
    overlay_path: Path,
    *,
    date_iso: str,
    symbols: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    try:
        overlay = load_daily_price_overlay(overlay_path)
    except (DailyPriceOverlayError, OSError, ValueError) as exc:
        raise DailyPriceOverlayConsumerError(
            "overlay cannot be loaded and verified"
        ) from exc
    scope = overlay.get("scope")
    if not isinstance(scope, Mapping):
        raise DailyPriceOverlayConsumerError("overlay scope is invalid")
    if scope.get("date") != date_iso or tuple(scope.get("symbols") or ()) != symbols:
        raise DailyPriceOverlayConsumerError("overlay scope does not match request")
    if overlay.get("source_lineage", {}).get(
        "official_raw_response_receipt_present"
    ) is not True:
        raise DailyPriceOverlayConsumerError(
            "consumer requires an overlay bound to an official response receipt"
        )
    official_capture = overlay.get("official_capture")
    if not isinstance(official_capture, Mapping):
        raise DailyPriceOverlayConsumerError("overlay official capture binding is missing")
    comparison_path = Path(str(official_capture.get("comparison_path") or "")).resolve()
    if comparison_path.name != "comparison.json":
        raise DailyPriceOverlayConsumerError("overlay comparison path is invalid")
    try:
        receipt, comparison = load_twse_capture(comparison_path.parent)
    except (OSError, ValueError, KeyError) as exc:
        raise DailyPriceOverlayConsumerError(
            "overlay official response custody cannot be verified"
        ) from exc
    comparison_hash = _required_hash(
        comparison.get("comparison_hash"), field_name="comparison_hash"
    )
    receipt_hash = _required_hash(
        receipt.get("receipt_hash"), field_name="receipt_hash"
    )
    response_hash = _required_hash(
        comparison.get("capture", {}).get("response_sha256"),
        field_name="response_sha256",
    )
    if (
        official_capture.get("comparison_hash") != comparison_hash
        or official_capture.get("receipt_hash") != receipt_hash
        or official_capture.get("response_sha256") != response_hash
    ):
        raise DailyPriceOverlayConsumerError(
            "overlay official capture hashes do not match readback"
        )
    if comparison.get("date") != date_iso:
        raise DailyPriceOverlayConsumerError("official comparison date mismatch")
    if comparison.get("capture", {}).get("historical_decision_time_available") is not False:
        raise DailyPriceOverlayConsumerError(
            "historical official capture cannot be treated as decision-time data"
        )
    captured_at = official_capture.get("captured_at_utc")
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise DailyPriceOverlayConsumerError("official capture observed_at is missing")
    try:
        parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DailyPriceOverlayConsumerError(
            "official capture observed_at is not an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DailyPriceOverlayConsumerError(
            "official capture observed_at must include timezone"
        )
    rows = overlay.get("rows")
    if not isinstance(rows, list) or len(rows) != len(symbols):
        raise DailyPriceOverlayConsumerError("overlay rows are incomplete")
    by_symbol: dict[str, dict[str, Any]] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise DailyPriceOverlayConsumerError("overlay row is invalid")
        symbol = str(raw_row.get("symbol") or "").strip()
        if symbol in by_symbol or symbol not in symbols:
            raise DailyPriceOverlayConsumerError("overlay row symbol scope is invalid")
        if raw_row.get("date") != date_iso:
            raise DailyPriceOverlayConsumerError("overlay row date mismatch")
        official_row = raw_row.get("official_row")
        candidate_row = raw_row.get("overlay_row")
        if not isinstance(official_row, Mapping) or not isinstance(candidate_row, Mapping):
            raise DailyPriceOverlayConsumerError(
                "official overlay row must retain official and candidate values"
            )
        for field in _FEATURE_FIELDS:
            if Decimal(str(official_row.get(field))) != Decimal(str(candidate_row.get(field))):
                raise DailyPriceOverlayConsumerError(
                    f"official/candidate overlay mismatch for {symbol}.{field}"
                )
        by_symbol[symbol] = dict(raw_row)
    if tuple(sorted(by_symbol)) != symbols:
        raise DailyPriceOverlayConsumerError("overlay has partial symbol coverage")
    binding = {
        "overlay_path": str(overlay_path.resolve()),
        "overlay_file_sha256": _file_sha256(overlay_path.resolve()),
        "overlay_hash": _required_hash(
            overlay.get("overlay_hash"), field_name="overlay_hash"
        ),
        "comparison_path": str(comparison_path),
        "comparison_hash": comparison_hash,
        "receipt_hash": receipt_hash,
        "response_sha256": response_hash,
        "captured_at_utc": captured_at,
        "historical_decision_time_available": False,
        "official_row_count": len(by_symbol),
    }
    return binding, by_symbol, {
        "receipt": receipt,
        "comparison": comparison,
    }


def _baseline_extreme_evidence(
    path: Path | None,
    *,
    date_iso: str,
    symbol: str,
) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DailyPriceOverlayConsumerError(
            "baseline label extreme audit cannot be read"
        ) from exc
    if not isinstance(payload, Mapping):
        raise DailyPriceOverlayConsumerError("baseline label extreme audit is invalid")
    selection = payload.get("selection")
    if not isinstance(selection, Mapping):
        raise DailyPriceOverlayConsumerError("baseline selection is missing")
    replay = selection.get("replay_source")
    rows = selection.get("rows")
    if (
        selection.get("horizon") != HORIZON_TRADING_DAYS
        or selection.get("label_field") != "benchmark_excess_return_bp"
        or not isinstance(replay, Mapping)
        or not isinstance(rows, Mapping)
        or replay.get("decision_date") != date_iso
        or rows.get("decision_date") != date_iso
        or replay.get("symbol") != symbol
        or rows.get("symbol") != symbol
    ):
        raise DailyPriceOverlayConsumerError(
            "baseline label extreme audit scope does not match consumer"
        )
    return {
        "path": str(resolved),
        "file_sha256": _file_sha256(resolved),
        "selection_manifest_hash": _required_hash(
            payload.get("selection", {}).get("manifest_hash"),
            field_name="baseline manifest_hash",
        ),
        "label_value_bp": selection.get("label_value_bp"),
        "symbol": symbol,
        "decision_date": date_iso,
        "horizon": HORIZON_TRADING_DAYS,
    }


def _write_immutable_json(path: Path, body: Mapping[str, Any], *, source_roots: Sequence[Path]) -> Path:
    output = path.resolve()
    for source_root in source_roots:
        resolved_root = source_root.resolve()
        if output == resolved_root or resolved_root in output.parents:
            raise DailyPriceOverlayConsumerError(
                "impact output must be outside read-only source roots"
            )
    encoded = (_canonical_json(dict(body)) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != encoded:
            raise FileExistsError(
                f"impact output already exists with different content: {output}"
            )
        return output
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def build_daily_price_overlay_impact(
    *,
    overlay_path: Path,
    sqlite_path: Path,
    output_path: Path,
    benchmark_entity: str = "TAIEX",
    horizon: int = HORIZON_TRADING_DAYS,
    baseline_extreme_audit_path: Path | None = None,
    research_mode: str = POST_CAPTURE_RESEARCH_MODE,
) -> DailyPriceOverlayImpactResult:
    """以事後 overlay 建立 raw diagnostic 與盤前可得 label 證據。

    overlay 的決策日 OHLC/成交量只放在 ``raw_price_diagnostic``；真正的
    ``decision_time_features`` 僅取決策日前兩個來源交易日。此入口是
    post-capture historical research，不能產生正式訓練或 promotion 證據。
    """

    if horizon != HORIZON_TRADING_DAYS:
        raise DailyPriceOverlayConsumerError(
            "consumer only supports the frozen h20 label contract"
        )
    if research_mode != POST_CAPTURE_RESEARCH_MODE:
        raise DailyPriceOverlayConsumerError(
            "unsupported research mode; post-capture research is the only mode"
        )
    overlay_resolved = overlay_path.resolve()
    overlay_payload = load_daily_price_overlay(overlay_resolved)
    scope = overlay_payload.get("scope")
    if not isinstance(scope, Mapping):
        raise DailyPriceOverlayConsumerError("overlay scope is invalid")
    date_iso = _normalise_date(scope.get("date"), field_name="overlay.scope.date")
    raw_symbols = scope.get("symbols")
    if not isinstance(raw_symbols, list):
        raise DailyPriceOverlayConsumerError("overlay symbols are invalid")
    symbols = tuple(sorted({str(item).strip() for item in raw_symbols if str(item).strip()}))
    if not symbols:
        raise DailyPriceOverlayConsumerError("overlay symbols must not be empty")
    binding, overlay_rows, official_payload = _verify_official_overlay(
        overlay_resolved,
        date_iso=date_iso,
        symbols=symbols,
    )
    sqlite_resolved = sqlite_path.resolve()
    sqlite_hash = _file_sha256(sqlite_resolved)
    baseline_evidence = _baseline_extreme_evidence(
        baseline_extreme_audit_path,
        date_iso=date_iso,
        symbol="3017" if "3017" in symbols else symbols[0],
    )

    connection = _open_sqlite_read_only(sqlite_resolved)
    try:
        dates = _market_dates(
            connection,
            benchmark_entity=benchmark_entity,
            decision_date=date_iso,
            horizon=horizon,
        )
        benchmark = _market_window(
            connection,
            benchmark_entity=benchmark_entity,
            dates=dates,
        )
        impacts: list[dict[str, Any]] = []
        raw_diagnostic_changed_feature_count = 0
        decision_time_feature_changed_count = 0
        changed_label_count = 0
        for symbol in symbols:
            original_window = _stock_window(
                connection,
                symbol=symbol,
                dates=dates,
            )
            original_entry = original_window[0]
            raw_overlay = overlay_rows[symbol]
            candidate_entry = _point_from_mapping(
                raw_overlay["overlay_row"],
                symbol=symbol,
                date_value=date_iso,
                field_name=f"overlay.{symbol}",
            )
            if candidate_entry.date != original_entry.date:
                raise DailyPriceOverlayConsumerError(
                    f"overlay decision date mismatch for {symbol}"
                )
            candidate_window = (candidate_entry, *original_window[1:])
            previous_session, previous_close = _previous_session_features(
                connection,
                symbol=symbol,
                decision_date=date_iso,
            )
            raw_price_diagnostic, feature_changes = _feature_payload(
                original=original_entry,
                candidate=candidate_entry,
                previous_close=previous_close,
            )
            decision_time_features = _decision_time_feature_payload(
                previous_session=previous_session,
                previous_close=previous_close,
                decision_date=date_iso,
            )
            original_label = _label_payload(
                path=original_window,
                benchmark=benchmark,
                benchmark_dates=dates,
                benchmark_entity=benchmark_entity,
                source_kind="sqlite_original",
            )
            if (
                baseline_evidence is not None
                and symbol == baseline_evidence["symbol"]
                and date_iso == baseline_evidence["decision_date"]
                and int(baseline_evidence["label_value_bp"])
                != int(original_label["benchmark_excess_return_bp"])
            ):
                raise DailyPriceOverlayConsumerError(
                    "baseline extreme audit does not match independently "
                    "recomputed original label"
                )
            candidate_label = _label_payload(
                path=candidate_window,
                benchmark=benchmark,
                benchmark_dates=dates,
                benchmark_entity=benchmark_entity,
                source_kind="official_overlay_entry_plus_sqlite_future",
            )
            changed_labels = [
                field
                for field in _LABEL_FIELDS
                if original_label[field] != candidate_label[field]
            ]
            raw_diagnostic_changed_feature_count += feature_changes
            changed_label_count += len(changed_labels)
            impacts.append(
                {
                    "symbol": symbol,
                    "decision_date": date_iso,
                    "decision_at": f"{date_iso}T08:30:00+08:00",
                    "observed_at_utc": binding["captured_at_utc"],
                    "historical_decision_time_available": False,
                    "research_mode": research_mode,
                    "feature_recompute_scope": (
                        "raw_price_diagnostic_only;decision_time_features_use_"
                        "prior_session"
                    ),
                    # v2 的通用 features key 直接指向盤前 model input；
                    # 同日官方值只保留在明確的 raw diagnostic key。
                    "features": decision_time_features,
                    "raw_price_diagnostic": raw_price_diagnostic,
                    "decision_time_features": decision_time_features,
                    "labels": {
                        "horizon": horizon,
                        "original": original_label,
                        "candidate": candidate_label,
                        "changed_fields": changed_labels,
                        "historical_maturity_date": dates[-1],
                        "candidate_observed_at_utc": binding["captured_at_utc"],
                        "formal_training_allowed": False,
                    },
                    "source_lineage": {
                        "sqlite_row_is_original": True,
                        "overlay_row_is_candidate_only": True,
                        "overlay_row_official": raw_overlay.get("official_row"),
                        "raw_overlay_row_used_for_model_features": False,
                        "decision_time_feature_source_date": previous_session.date,
                        "decision_time_feature_source_symbol": previous_session.symbol,
                        "decision_time_feature_available_before_decision": True,
                        "decision_time_feature_availability_basis": (
                            "source date strictly precedes decision date; source "
                            "does not carry intraday availability timestamp"
                        ),
                        "future_price_rows_used_for_supervised_label": True,
                        "future_rows_used_as_features": False,
                    },
                }
            )
    finally:
        connection.close()

    body: dict[str, Any] = {
        "schema_version": OVERLAY_CONSUMER_SCHEMA_VERSION,
        "status": "research_overlay_impact_candidate",
        "read_only": True,
        "labels_mutated": False,
        "retrained": False,
        "formal_training_allowed": False,
        "promotion_eligible": False,
        "research_mode": research_mode,
        "overlay_selection": {
            "selected_version": "official_response_bound_candidate_overlay",
            "selection_policy": "post_capture_official_receipt_bound_research_only.v1",
            "original_sqlite_retained": True,
            "raw_overlay_values_used_for_model_features": False,
        },
        "scope": {
            "date": date_iso,
            "symbols": list(symbols),
            "row_count": len(impacts),
            "benchmark_entity": benchmark_entity,
            "horizon": horizon,
        },
        "observed_at_utc": binding["captured_at_utc"],
        "historical_decision_time_available": False,
        "sources": {
            "sqlite": {
                "path": str(sqlite_resolved),
                "file_sha256": sqlite_hash,
                "bytes": sqlite_resolved.stat().st_size,
                "read_only": True,
            },
            "overlay": binding,
            "official_response": {
                "receipt_hash": binding["receipt_hash"],
                "comparison_hash": binding["comparison_hash"],
                "response_sha256": binding["response_sha256"],
                "captured_at_utc": binding["captured_at_utc"],
                "historical_decision_time_available": False,
            },
            "baseline_extreme_audit": baseline_evidence,
        },
        "label_policy": {
            "entry": "decision-day-open",
            "exit": "20th-market-session-close",
            "transaction_cost_bp": TRANSACTION_COST_BP,
            "rounding": "Decimal ROUND_HALF_EVEN to integer bp",
            "future_values_are_supervised_labels_only": True,
        },
        "feature_policy": {
            "model_input_source": "strict_previous_session_before_decision",
            "raw_price_diagnostic_role": "post_close_only_not_model_input",
            "decision_time_cutoff": "08:30:00+08:00",
            "same_day_close_or_volume_allowed": False,
            "intraday_source_timestamp_required_for_same_day": True,
        },
        "verification": {
            "official_rows_verified": len(official_payload["comparison"].get("rows", [])),
            "overlay_rows_consumed": len(impacts),
            "feature_rows_recomputed": len(impacts),
            # 舊 key 是診斷差異的相容別名，不宣稱 model feature impact。
            "changed_feature_count": raw_diagnostic_changed_feature_count,
            "raw_diagnostic_changed_feature_count": raw_diagnostic_changed_feature_count,
            "decision_time_feature_changed_count": decision_time_feature_changed_count,
            "model_feature_impact_claimed": False,
            "changed_label_count": changed_label_count,
            "all_requested_symbols_present": len(impacts) == len(symbols),
            "source_sqlite_unchanged_by_consumer": True,
        },
        "impacts": impacts,
    }
    body["impact_hash"] = _payload_hash(body)
    output = _write_immutable_json(
        output_path,
        body,
        source_roots=(
            sqlite_resolved,
            overlay_resolved,
            Path(binding["comparison_path"]).resolve(),
            *(
                ()
                if baseline_extreme_audit_path is None
                else (baseline_extreme_audit_path.resolve(),)
            ),
        ),
    )
    return DailyPriceOverlayImpactResult(
        output_path=output,
        output_hash=str(body["impact_hash"]),
        row_count=len(impacts),
        changed_feature_count=raw_diagnostic_changed_feature_count,
        changed_label_count=changed_label_count,
        decision_time_feature_changed_count=decision_time_feature_changed_count,
    )


def load_daily_price_overlay_impact(path: Path) -> dict[str, Any]:
    """讀取 immutable impact artifact 並驗證 identity hash。"""

    resolved = path.resolve()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DailyPriceOverlayConsumerError("impact artifact cannot be read") from exc
    if not isinstance(payload, dict):
        raise DailyPriceOverlayConsumerError("impact artifact must be an object")
    supplied = _required_hash(payload.get("impact_hash"), field_name="impact_hash")
    body = dict(payload)
    body.pop("impact_hash", None)
    if _payload_hash(body) != supplied:
        raise DailyPriceOverlayConsumerError("impact_hash mismatch")
    if payload.get("schema_version") not in {
        LEGACY_OVERLAY_CONSUMER_SCHEMA_VERSION,
        OVERLAY_CONSUMER_SCHEMA_VERSION,
    }:
        raise DailyPriceOverlayConsumerError("unsupported impact schema")
    if payload.get("status") != "research_overlay_impact_candidate":
        raise DailyPriceOverlayConsumerError("impact status is not research candidate")
    if payload.get("labels_mutated") is not False:
        raise DailyPriceOverlayConsumerError("impact cannot claim mutated labels")
    if payload.get("schema_version") == OVERLAY_CONSUMER_SCHEMA_VERSION:
        feature_policy = payload.get("feature_policy")
        if not isinstance(feature_policy, Mapping):
            raise DailyPriceOverlayConsumerError("v2 impact feature policy is missing")
        if feature_policy.get("same_day_close_or_volume_allowed") is not False:
            raise DailyPriceOverlayConsumerError(
                "v2 impact cannot allow same-day close or volume as model input"
            )
        if feature_policy.get("raw_price_diagnostic_role") != (
            "post_close_only_not_model_input"
        ):
            raise DailyPriceOverlayConsumerError(
                "v2 impact raw price diagnostic role is invalid"
            )
        if payload.get("research_mode") != POST_CAPTURE_RESEARCH_MODE:
            raise DailyPriceOverlayConsumerError("v2 impact research mode is invalid")
        impacts = payload.get("impacts")
        if not isinstance(impacts, list):
            raise DailyPriceOverlayConsumerError("v2 impact rows are missing")
        for raw_impact in impacts:
            if not isinstance(raw_impact, Mapping):
                raise DailyPriceOverlayConsumerError("v2 impact row is invalid")
            decision_date = _normalise_date(
                raw_impact.get("decision_date"),
                field_name="impact.decision_date",
            )
            decision_features = raw_impact.get("decision_time_features")
            raw_diagnostic = raw_impact.get("raw_price_diagnostic")
            if not isinstance(decision_features, Mapping) or not isinstance(
                raw_diagnostic, Mapping
            ):
                raise DailyPriceOverlayConsumerError(
                    "v2 impact feature role separation is missing"
                )
            for feature_id, feature in decision_features.items():
                if not isinstance(feature, Mapping):
                    raise DailyPriceOverlayConsumerError(
                        f"v2 decision-time feature is invalid: {feature_id}"
                    )
                source_date = _normalise_date(
                    feature.get("source_date"),
                    field_name=f"impact.decision_time_features.{feature_id}.source_date",
                )
                if (
                    feature.get("feature_role") != "decision_time_model_input"
                    or feature.get("used_for_model_features") is not True
                    or feature.get("available_before_decision") is not True
                    or source_date >= decision_date
                ):
                    raise DailyPriceOverlayConsumerError(
                        "v2 decision-time feature is not proven before decision"
                    )
            for feature_id, feature in raw_diagnostic.items():
                if not isinstance(feature, Mapping) or (
                    feature.get("feature_role")
                    != "post_close_raw_price_diagnostic_only"
                    or feature.get("used_for_model_features") is not False
                ):
                    raise DailyPriceOverlayConsumerError(
                        f"v2 raw diagnostic feature role is invalid: {feature_id}"
                    )
    return payload


__all__ = [
    "BUY_COST_BP",
    "DailyPriceOverlayConsumerError",
    "DailyPriceOverlayImpactResult",
    "HORIZON_TRADING_DAYS",
    "LEGACY_OVERLAY_CONSUMER_SCHEMA_VERSION",
    "OVERLAY_CONSUMER_SCHEMA_VERSION",
    "POST_CAPTURE_RESEARCH_MODE",
    "build_daily_price_overlay_impact",
    "load_daily_price_overlay_impact",
]
