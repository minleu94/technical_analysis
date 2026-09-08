"""把官方日價候選接入既有 research feature／label 重播路徑。

``ml_daily_price_overlay_consumer`` 只建立來源影響診斷；本模組則把已驗證
的 official-response-bound overlay 選入既有
``portfolio_ml_dataset_assembler._build_label_spool``，在隔離的記憶體 spool
上重跑原始與 corrected research label。決策日資料只可作事後 supervised
entry，盤前 feature 仍由決策日前兩個來源交易日提供。所有輸入唯讀，結果
明確標成 historical research，不能成為 formal training 或 promotion 證據。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from data_module.ml_daily_price_overlay_consumer import (
    _LABEL_FIELDS,
    _file_sha256,
    _normalise_date,
    _previous_session_features,
    _return_bp,
    _verify_official_overlay,
    load_daily_price_overlay_impact,
)
from data_module.ml_daily_price_overlay import load_daily_price_overlay
from data_module.portfolio_ml_dataset_assembler import (
    _build_label_spool,
    _initialize_spool,
    _insert_prices,
)


RESEARCH_LABEL_REPLAY_SCHEMA_VERSION = (
    "portfolio-ml-daily-price-research-label-replay.v1"
)
RESEARCH_LABEL_REPLAY_MODE = (
    "post_capture_official_overlay_existing_pipeline.v1"
)
HORIZON_TRADING_DAYS = 20
_TAIPEI_OFFSET_HOURS = 8
_SHA256_PREFIX = "sha256:"
_CHUNK_BYTES = 1 << 20


class DailyPriceResearchReplayError(ValueError):
    """研究 overlay 無法通過既有 label pipeline 的契約。"""


@dataclass(frozen=True)
class DailyPriceResearchReplayResult:
    """已持久化的 research label replay 摘要。"""

    output_path: Path
    replay_hash: str
    row_count: int
    reference_rows_matched: int


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


def _required_hash(value: object, *, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if (
        len(text) != 71
        or not text.startswith(_SHA256_PREFIX)
        or any(character not in "0123456789abcdef" for character in text[7:])
    ):
        raise DailyPriceResearchReplayError(
            f"{field_name} must be a sha256 digest"
        )
    return text


def _decimal(value: object, *, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise DailyPriceResearchReplayError(f"{field_name} is missing")
    try:
        parsed = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DailyPriceResearchReplayError(
            f"{field_name} is not numeric"
        ) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise DailyPriceResearchReplayError(
            f"{field_name} must be a positive finite Decimal"
        )
    return parsed


def _scaled(value: object, *, field_name: str) -> tuple[int, int]:
    parsed = _decimal(value, field_name=field_name)
    exponent = parsed.as_tuple().exponent
    decimal_places = max(0, -int(exponent))
    scale = 10**decimal_places
    scaled_value = parsed * Decimal(scale)
    if scaled_value != scaled_value.to_integral_value():
        raise DailyPriceResearchReplayError(
            f"{field_name} cannot be represented as an integer scale"
        )
    return int(scaled_value), scale


def _nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DailyPriceResearchReplayError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _normalise_capture_time(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DailyPriceResearchReplayError(
            "official capture time must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DailyPriceResearchReplayError(
            "official capture time must include timezone"
        )
    return parsed.isoformat()


def _source_row_hash(payload: Mapping[str, object]) -> str:
    return _payload_hash(dict(payload))


def _validate_price_components(
    *,
    open_value: Decimal,
    high_value: Decimal,
    low_value: Decimal,
    close_value: Decimal,
    field_name: str,
) -> None:
    if low_value > min(open_value, close_value):
        raise DailyPriceResearchReplayError(
            f"{field_name}.low is above open/close"
        )
    if high_value < max(open_value, close_value):
        raise DailyPriceResearchReplayError(
            f"{field_name}.high is below open/close"
        )


def _row_to_price_tuple(
    *,
    scope: str,
    entity_key: str,
    event_date: str,
    available_at: str,
    open_value: object,
    high_value: object,
    low_value: object,
    close_value: object,
    source_row_hash: str,
    field_name: str,
) -> tuple[object, ...]:
    open_decimal = _decimal(open_value, field_name=f"{field_name}.open")
    high_decimal = _decimal(high_value, field_name=f"{field_name}.high")
    low_decimal = _decimal(low_value, field_name=f"{field_name}.low")
    close_decimal = _decimal(close_value, field_name=f"{field_name}.close")
    _validate_price_components(
        open_value=open_decimal,
        high_value=high_decimal,
        low_value=low_decimal,
        close_value=close_decimal,
        field_name=field_name,
    )
    open_int, open_scale = _scaled(
        open_decimal,
        field_name=f"{field_name}.open",
    )
    high_int, high_scale = _scaled(
        high_decimal,
        field_name=f"{field_name}.high",
    )
    low_int, low_scale = _scaled(
        low_decimal,
        field_name=f"{field_name}.low",
    )
    close_int, close_scale = _scaled(
        close_decimal,
        field_name=f"{field_name}.close",
    )
    return (
        scope,
        entity_key,
        event_date,
        available_at,
        open_int,
        open_scale,
        high_int,
        high_scale,
        low_int,
        low_scale,
        close_int,
        close_scale,
        source_row_hash,
    )


def _read_market_window(
    connection: sqlite3.Connection,
    *,
    benchmark_entity: str,
    decision_date: str,
    horizon: int,
) -> tuple[tuple[str, dict[str, object]], ...]:
    rows = connection.execute(
        """
        SELECT 日期, 開盤價, 收盤價
        FROM market_indices
        WHERE 指數名稱=? AND 日期>=?
        ORDER BY 日期
        """,
        (benchmark_entity, decision_date.replace("-", "")),
    ).fetchall()
    by_date: dict[str, dict[str, object]] = {}
    for row in rows:
        current_date = _normalise_date(
            row["日期"],
            field_name="market.日期",
        )
        if current_date in by_date:
            raise DailyPriceResearchReplayError(
                f"benchmark has duplicate date: {current_date}"
            )
        # 送入既有 label spool 前先驗證市場價位欄位。
        _decimal(row["開盤價"], field_name="market.open")
        _decimal(row["收盤價"], field_name="market.close")
        by_date[current_date] = {
            "open": row["開盤價"],
            "close": row["收盤價"],
        }
    selected = tuple(sorted(by_date.items()))[: horizon + 1]
    if len(selected) <= horizon or not selected or selected[0][0] != decision_date:
        raise DailyPriceResearchReplayError(
            "benchmark does not provide horizon plus one complete session"
        )
    return selected


def _read_stock_rows(
    connection: sqlite3.Connection,
    *,
    symbols: tuple[str, ...],
    dates: tuple[str, ...],
) -> dict[tuple[str, str], dict[str, object]]:
    symbol_placeholders = ",".join("?" for _ in symbols)
    date_placeholders = ",".join("?" for _ in dates)
    rows = connection.execute(
        """
        SELECT 日期, 證券代號, 開盤價, 最高價, 最低價, 收盤價, 成交股數
        FROM daily_prices
        WHERE 證券代號 IN ("""
        + symbol_placeholders
        + ") AND 日期 IN ("
        + date_placeholders
        + ") ORDER BY 日期, 證券代號",
        (*symbols, *(item.replace("-", "") for item in dates)),
    ).fetchall()
    result: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        date_iso = _normalise_date(row["日期"], field_name="stock.日期")
        symbol = str(row["證券代號"]).strip()
        if symbol not in symbols:
            raise DailyPriceResearchReplayError(
                f"stock row symbol is outside overlay scope: {symbol}"
            )
        key = (symbol, date_iso)
        if key in result:
            raise DailyPriceResearchReplayError(
                f"duplicate stock price row: {symbol}/{date_iso}"
            )
        for field in ("開盤價", "最高價", "最低價", "收盤價"):
            _decimal(row[field], field_name=f"stock.{symbol}.{date_iso}.{field}")
        volume = row["成交股數"]
        if (
            isinstance(volume, bool)
            or not isinstance(volume, int)
            or volume < 0
        ):
            raise DailyPriceResearchReplayError(
                f"stock.{symbol}.{date_iso}.成交股數 must be non-negative integer"
            )
        result[key] = {
            "open": row["開盤價"],
            "high": row["最高價"],
            "low": row["最低價"],
            "close": row["收盤價"],
            "volume_shares": volume,
        }
    expected = {(symbol, current) for symbol in symbols for current in dates}
    missing = sorted(expected - set(result))
    if missing:
        raise DailyPriceResearchReplayError(
            "stock price window is incomplete: "
            + ",".join(f"{symbol}/{current}" for symbol, current in missing[:8])
        )
    return result


def _official_entry_rows(
    overlay_rows: Mapping[str, Mapping[str, Any]],
    *,
    decision_date: str,
    captured_at: str,
    response_sha256: str,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for symbol, raw_row in overlay_rows.items():
        official = raw_row.get("official_row")
        if not isinstance(official, Mapping):
            raise DailyPriceResearchReplayError(
                f"official overlay row missing for {symbol}"
            )
        official_symbol = str(official.get("symbol") or "").strip()
        if official_symbol != symbol:
            raise DailyPriceResearchReplayError(
                f"official overlay symbol mismatch for {symbol}"
            )
        values = {
            "open": official.get("open"),
            "high": official.get("high"),
            "low": official.get("low"),
            "close": official.get("close"),
            "volume_shares": official.get("volume_shares"),
        }
        for field in ("open", "high", "low", "close"):
            _decimal(
                values[field],
                field_name=f"official.{symbol}.{field}",
            )
        volume = values["volume_shares"]
        if (
            isinstance(volume, bool)
            or not isinstance(volume, int)
            or volume < 0
        ):
            raise DailyPriceResearchReplayError(
                f"official.{symbol}.volume_shares must be non-negative integer"
            )
        _validate_price_components(
            open_value=_decimal(values["open"], field_name="official.open"),
            high_value=_decimal(values["high"], field_name="official.high"),
            low_value=_decimal(values["low"], field_name="official.low"),
            close_value=_decimal(values["close"], field_name="official.close"),
            field_name=f"official.{symbol}.{decision_date}",
        )
        result[symbol] = {
            **values,
            "date": decision_date,
            "available_at": captured_at,
            "source_kind": "official_response_bound_overlay",
            "response_sha256": response_sha256,
            "source_row_hash": _source_row_hash(
                {
                    "schema_version": RESEARCH_LABEL_REPLAY_SCHEMA_VERSION,
                    "symbol": symbol,
                    "date": decision_date,
                    "values": values,
                    "available_at": captured_at,
                    "response_sha256": response_sha256,
                }
            ),
        }
    return result


def _scenario_labels(
    *,
    scenario: str,
    symbols: tuple[str, ...],
    decision_date: str,
    market_rows: tuple[tuple[str, dict[str, object]], ...],
    stock_rows: Mapping[tuple[str, str], Mapping[str, object]],
    official_rows: Mapping[str, Mapping[str, object]],
    captured_at: str,
    sqlite_hash: str,
    response_sha256: str,
    benchmark_entity: str,
    horizon: int,
) -> tuple[dict[str, Any], ...]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        _initialize_spool(connection)
        price_rows: list[tuple[object, ...]] = []
        for current_date, market in market_rows:
            market_open = _decimal(
                market["open"],
                field_name=f"market.{current_date}.open",
            )
            market_close = _decimal(
                market["close"],
                field_name=f"market.{current_date}.close",
            )
            market_hash = _source_row_hash(
                {
                    "source": "sqlite.market_indices",
                    "sqlite_file_sha256": sqlite_hash,
                    "entity": benchmark_entity,
                    "date": current_date,
                    "open": str(market["open"]),
                    "close": str(market["close"]),
                }
            )
            price_rows.append(
                _row_to_price_tuple(
                    scope="market",
                    entity_key=benchmark_entity,
                    event_date=current_date,
                    available_at=captured_at,
                    open_value=market["open"],
                    high_value=max(market_open, market_close),
                    low_value=min(market_open, market_close),
                    close_value=market["close"],
                    source_row_hash=market_hash,
                    field_name=f"market.{current_date}",
                )
            )
        for symbol in symbols:
            for current_date, _ in market_rows:
                source = stock_rows[(symbol, current_date)]
                # 兩個情境都必須維持同一個 row contract；明確註記共同
                # Mapping 型別，避免 mypy 將先出現的 SQLite row 收窄成
                # 不可重新綁定的具體型別。
                selected: Mapping[str, object] = source
                source_kind: str = "sqlite_original"
                if scenario == "corrected" and current_date == decision_date:
                    selected = official_rows[symbol]
                    source_kind = "official_response_bound_overlay"
                source_hash = _source_row_hash(
                    {
                        "source": source_kind,
                        "sqlite_file_sha256": sqlite_hash,
                        "response_sha256": (
                            response_sha256
                            if source_kind == "official_response_bound_overlay"
                            else None
                        ),
                        "symbol": symbol,
                        "date": current_date,
                        "open": str(selected["open"]),
                        "high": str(selected["high"]),
                        "low": str(selected["low"]),
                        "close": str(selected["close"]),
                        "volume_shares": _nonnegative_int(
                            selected["volume_shares"],
                            field_name=f"stock.{symbol}.{current_date}.volume_shares",
                        ),
                    }
                )
                price_rows.append(
                    _row_to_price_tuple(
                        scope="stock",
                        entity_key=symbol,
                        event_date=current_date,
                        available_at=captured_at,
                        open_value=selected["open"],
                        high_value=selected["high"],
                        low_value=selected["low"],
                        close_value=selected["close"],
                        source_row_hash=source_hash,
                        field_name=f"stock.{symbol}.{current_date}",
                    )
                )
        _insert_prices(connection, price_rows)
        connection.commit()
        _build_label_spool(
            connection=connection,
            benchmark_entity_id=benchmark_entity,
            cutoff=datetime.fromisoformat(captured_at.replace("Z", "+00:00")),
            horizons=(horizon,),
            batch_size=2_048,
        )
        labels = tuple(
            {
                str(key): row[key]
                for key in row.keys()
            }
            for row in connection.execute(
                """
                SELECT * FROM labels
                WHERE decision_date=? AND horizon=?
                ORDER BY symbol
                """,
                (decision_date, horizon),
            )
        )
    finally:
        connection.close()
    if len(labels) != len(symbols):
        raise DailyPriceResearchReplayError(
            f"{scenario} existing label pipeline emitted {len(labels)} rows; "
            f"expected {len(symbols)}"
        )
    result: list[dict[str, Any]] = []
    for row in labels:
        pipeline_field_map = {
            "benchmark_excess_return_bp": "excess_return_bp",
            "downside_observed": "downside_observed",
            "mae_loss_bp": "mae_loss_bp",
            "mfe_gain_bp": "mfe_gain_bp",
            "realized_volatility_bp": "realized_volatility_bp",
            "max_drawdown_bp": "max_drawdown_bp",
            "tail_loss_bp": "tail_loss_bp",
            "fill_feasible_observed": "fill_feasible_observed",
        }
        if not all(field_name in row for field_name in pipeline_field_map.values()):
            raise DailyPriceResearchReplayError(
                "existing label pipeline row fields are incomplete: "
                + ",".join(sorted(row))
            )
        label = {
            field: int(row[pipeline_field])
            for field, pipeline_field in pipeline_field_map.items()
        }
        result.append(
            {
                "symbol": str(row["symbol"]),
                "decision_date": str(row["decision_date"]),
                "horizon": int(row["horizon"]),
                "horizon_end_date": str(row["horizon_end_date"]),
                "available_at": str(row["available_at"]),
                "label": label,
                "source_hash": str(row["source_hash"]),
                "source_kind": (
                    "official_response_bound_overlay"
                    if scenario == "corrected"
                    else "sqlite_original"
                ),
            }
        )
    return tuple(result)


def _reference_labels(
    path: Path,
    *,
    date_iso: str,
    symbols: tuple[str, ...],
    horizon: int,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    try:
        payload = load_daily_price_overlay_impact(path.resolve())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise DailyPriceResearchReplayError(
            "existing overlay impact reference cannot be loaded"
        ) from exc
    scope = payload.get("scope")
    if not isinstance(scope, Mapping):
        raise DailyPriceResearchReplayError("reference impact scope is invalid")
    if (
        scope.get("date") != date_iso
        or scope.get("horizon") != horizon
        or tuple(scope.get("symbols") or ()) != symbols
    ):
        raise DailyPriceResearchReplayError(
            "reference impact scope does not match research replay"
        )
    raw_impacts = payload.get("impacts")
    if not isinstance(raw_impacts, list) or len(raw_impacts) != len(symbols):
        raise DailyPriceResearchReplayError(
            "reference impact rows are incomplete"
        )
    original: dict[str, dict[str, int]] = {}
    corrected: dict[str, dict[str, int]] = {}
    for raw in raw_impacts:
        if not isinstance(raw, Mapping):
            raise DailyPriceResearchReplayError("reference impact row is invalid")
        symbol = str(raw.get("symbol") or "")
        labels = raw.get("labels")
        if not isinstance(labels, Mapping):
            raise DailyPriceResearchReplayError(
                f"reference labels are missing for {symbol}"
            )
        for target, sink in (("original", original), ("candidate", corrected)):
            label = labels.get(target)
            if not isinstance(label, Mapping):
                raise DailyPriceResearchReplayError(
                    f"reference {target} label is missing for {symbol}"
                )
            sink[symbol] = {
                field: int(label[field])
                for field in _LABEL_FIELDS
            }
    if tuple(sorted(original)) != symbols or tuple(sorted(corrected)) != symbols:
        raise DailyPriceResearchReplayError(
            "reference impact symbol coverage is incomplete"
        )
    return original, corrected


def _write_immutable_json(
    path: Path,
    payload: Mapping[str, object],
    *,
    source_roots: Sequence[Path],
) -> Path:
    output = path.resolve()
    for source_root in source_roots:
        resolved_root = source_root.resolve()
        if output == resolved_root or resolved_root in output.parents:
            raise DailyPriceResearchReplayError(
                "research replay output overlaps read-only source"
            )
    encoded = (_canonical_json(dict(payload)) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != encoded:
            raise FileExistsError(
                f"research replay already exists with different content: {output}"
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


def build_research_label_replay_from_overlay(
    *,
    overlay_path: Path,
    sqlite_path: Path,
    output_path: Path,
    reference_impact_path: Path | None = None,
    benchmark_entity: str = "TAIEX",
    horizon: int = HORIZON_TRADING_DAYS,
) -> DailyPriceResearchReplayResult:
    """以既有 assembler label spool 重播官方 overlay 的研究版 labels。

    這個入口只建立 bounded in-memory price spool，不把 overlay 回寫 SQLite、
    PIT、training shard 或既有 impact。``reference_impact_path`` 若提供，
    會逐 symbol／逐 label head 對照原先獨立 consumer 的 33 筆結果。
    """

    if horizon != HORIZON_TRADING_DAYS:
        raise DailyPriceResearchReplayError(
            "research replay only supports the frozen h20 label contract"
        )
    overlay_resolved = overlay_path.resolve()
    output_resolved = output_path.resolve()
    if output_resolved == overlay_resolved:
        raise DailyPriceResearchReplayError(
            "research replay output overlaps read-only source"
        )
    try:
        overlay = load_daily_price_overlay(overlay_resolved)
    except (OSError, ValueError, TypeError) as exc:
        raise DailyPriceResearchReplayError(
            "research overlay cannot be loaded"
        ) from exc
    scope = overlay.get("scope")
    if not isinstance(scope, Mapping):
        raise DailyPriceResearchReplayError("overlay scope is invalid")
    date_iso = _normalise_date(scope.get("date"), field_name="overlay.scope.date")
    raw_symbols = scope.get("symbols")
    if not isinstance(raw_symbols, list):
        raise DailyPriceResearchReplayError("overlay symbols are invalid")
    symbols = tuple(sorted({str(item).strip() for item in raw_symbols if str(item).strip()}))
    if not symbols:
        raise DailyPriceResearchReplayError("overlay symbols must not be empty")
    binding, overlay_rows, official_payload = _verify_official_overlay(
        overlay_resolved,
        date_iso=date_iso,
        symbols=symbols,
    )
    captured_at = _normalise_capture_time(binding.get("captured_at_utc"))
    captured_datetime = datetime.fromisoformat(
        captured_at.replace("Z", "+00:00")
    )
    decision_cutoff = datetime.fromisoformat(
        f"{date_iso}T08:30:00+08:00"
    )
    if captured_datetime <= decision_cutoff:
        raise DailyPriceResearchReplayError(
            "official overlay capture must be observed after the historical "
            "decision cutoff"
        )
    receipt = official_payload.get("receipt")
    receipt_timing = (
        receipt.get("capture_timing")
        if isinstance(receipt, Mapping)
        else None
    )
    if not isinstance(receipt_timing, Mapping):
        raise DailyPriceResearchReplayError(
            "official receipt capture timing is missing"
        )
    receipt_completed_at = _normalise_capture_time(
        receipt_timing.get("response_completed_at_utc")
    )
    if receipt_completed_at != captured_at:
        raise DailyPriceResearchReplayError(
            "overlay captured_at does not match official receipt completion time"
        )
    response_sha256 = _required_hash(
        binding.get("response_sha256"),
        field_name="official response_sha256",
    )
    sqlite_resolved = sqlite_path.resolve()
    if not sqlite_resolved.is_file() or sqlite_resolved.is_symlink():
        raise DailyPriceResearchReplayError(
            f"SQLite source is missing or symlinked: {sqlite_resolved}"
        )
    if output_resolved == sqlite_resolved:
        raise DailyPriceResearchReplayError(
            "research replay output overlaps read-only source"
        )
    sqlite_hash = _file_sha256(sqlite_resolved)
    connection = sqlite3.connect(
        f"file:{sqlite_resolved.as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        market_rows = _read_market_window(
            connection,
            benchmark_entity=benchmark_entity,
            decision_date=date_iso,
            horizon=horizon,
        )
        dates = tuple(item[0] for item in market_rows)
        stock_rows = _read_stock_rows(
            connection,
            symbols=symbols,
            dates=dates,
        )
        feature_sources: dict[str, dict[str, object]] = {}
        for symbol in symbols:
            previous, previous_close = _previous_session_features(
                connection,
                symbol=symbol,
                decision_date=date_iso,
            )
            feature_sources[symbol] = {
                "selected_source": "sqlite_prior_session",
                "source_date": previous.date,
                "source_symbol": previous.symbol,
                # SQLite 日價列沒有內建發布 timestamp。研究觀察時間與
                # 僅依日期的前一交易日證據分開保存，不能把晚到的 overlay
                # 擷取時間標成盤前可得時間。
                "source_available_at": None,
                "available_before_decision": True,
                "availability_timestamp_proven": False,
                "availability_basis": (
                    "source date strictly precedes decision date; SQLite "
                    "source has no intraday availability timestamp"
                ),
                "observed_at_utc": captured_at,
                "overlay_row_used": False,
                "previous_close": format(previous_close, "f"),
                "selected_values": {
                    "open": format(previous.open, "f"),
                    "high": format(previous.high, "f"),
                    "low": format(previous.low, "f"),
                    "close": format(previous.close, "f"),
                    "volume_shares": previous.volume_shares,
                    "close_to_previous_close_bp": _return_bp(
                        previous_close,
                        previous.close,
                    ),
                },
                "feature_policy": "strict_previous_session_before_decision",
            }
    finally:
        connection.close()
    official_rows = _official_entry_rows(
        overlay_rows,
        decision_date=date_iso,
        captured_at=captured_at,
        response_sha256=response_sha256,
    )
    original_labels = _scenario_labels(
        scenario="original",
        symbols=symbols,
        decision_date=date_iso,
        market_rows=market_rows,
        stock_rows=stock_rows,
        official_rows=official_rows,
        captured_at=captured_at,
        sqlite_hash=sqlite_hash,
        response_sha256=response_sha256,
        benchmark_entity=benchmark_entity,
        horizon=horizon,
    )
    corrected_labels = _scenario_labels(
        scenario="corrected",
        symbols=symbols,
        decision_date=date_iso,
        market_rows=market_rows,
        stock_rows=stock_rows,
        official_rows=official_rows,
        captured_at=captured_at,
        sqlite_hash=sqlite_hash,
        response_sha256=response_sha256,
        benchmark_entity=benchmark_entity,
        horizon=horizon,
    )
    original_by_symbol = {str(row["symbol"]): row for row in original_labels}
    corrected_by_symbol = {str(row["symbol"]): row for row in corrected_labels}
    reference_match_count = 0
    reference_candidate_match_count = 0
    reference_metadata: dict[str, object] | None = None
    if reference_impact_path is not None:
        reference_resolved = reference_impact_path.resolve()
        if output_resolved == reference_resolved:
            raise DailyPriceResearchReplayError(
                "research replay output overlaps read-only source"
            )
        reference_original, reference_corrected = _reference_labels(
            reference_resolved,
            date_iso=date_iso,
            symbols=symbols,
            horizon=horizon,
        )
        for symbol in symbols:
            if original_by_symbol[symbol]["label"] != reference_original[symbol]:
                raise DailyPriceResearchReplayError(
                    f"existing pipeline original label mismatch: {symbol}"
                )
            reference_match_count += 1
            if corrected_by_symbol[symbol]["label"] != reference_corrected[symbol]:
                raise DailyPriceResearchReplayError(
                    f"existing pipeline corrected label mismatch: {symbol}"
                )
            reference_candidate_match_count += 1
        reference_metadata = {
            "path": str(reference_resolved),
            "file_sha256": _file_sha256(reference_resolved),
            "impact_hash": _required_hash(
                load_daily_price_overlay_impact(reference_resolved).get(
                    "impact_hash"
                ),
                field_name="reference impact_hash",
            ),
        }
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        original = original_by_symbol[symbol]
        corrected = corrected_by_symbol[symbol]
        rows.append(
            {
                "symbol": symbol,
                "decision_date": date_iso,
                "decision_at": f"{date_iso}T08:30:00+08:00",
                "feature_source": feature_sources[symbol],
                "labels": {
                    "original": original["label"],
                    "corrected": corrected["label"],
                    "original_source_hash": original["source_hash"],
                    "corrected_source_hash": corrected["source_hash"],
                    "corrected_source_kind": corrected["source_kind"],
                    "horizon_end_date": corrected["horizon_end_date"],
                    "available_at": corrected["available_at"],
                    "changed_fields": [
                        field
                        for field in _LABEL_FIELDS
                        if original["label"][field]
                        != corrected["label"][field]
                    ],
                },
                "source_lineage": {
                    "sqlite_original_row_retained": True,
                    "official_overlay_entry_selected_for_corrected_label": True,
                    "official_overlay_used_for_decision_features": False,
                    "future_rows_used_as_features": False,
                    "future_rows_used_as_supervised_label": True,
                    "historical_decision_time_available": False,
                    "observed_at_utc": captured_at,
                },
            }
        )
    body: dict[str, object] = {
        "schema_version": RESEARCH_LABEL_REPLAY_SCHEMA_VERSION,
        "status": "completed_research_label_replay",
        "research_mode": RESEARCH_LABEL_REPLAY_MODE,
        "read_only": True,
        "formal_training_allowed": False,
        "promotion_eligible": False,
        "historical_decision_time_available": False,
        "retrained": False,
        "selection": {
            "selected_version": "official_response_bound_candidate_overlay",
            "selection_policy": "explicit_corrected_research_label_entry_only.v1",
            "existing_pipeline": (
                "data_module.portfolio_ml_dataset_assembler._build_label_spool"
            ),
            "original_sqlite_retained": True,
            "decision_feature_source": "strict_previous_session_before_decision",
            "same_day_overlay_as_model_feature": False,
        },
        "scope": {
            "date": date_iso,
            "symbols": list(symbols),
            "row_count": len(rows),
            "benchmark_entity": benchmark_entity,
            "horizon": horizon,
        },
        "observed_at_utc": captured_at,
        "sources": {
            "sqlite": {
                "path": str(sqlite_resolved),
                "file_sha256": sqlite_hash,
                "bytes": sqlite_resolved.stat().st_size,
                "read_only": True,
            },
            "overlay": {
                **binding,
                "official_payload_row_count": len(
                    official_payload["comparison"].get("rows", [])
                ),
            },
            "reference_impact": reference_metadata,
        },
        "label_policy": {
            "entry": "decision-day-open",
            "exit": "20th-market-session-close",
            "transaction_cost_bp": 80,
            "numeric_type": "Decimal converted to integer bp",
            "rounding": "ROUND_HALF_EVEN",
            "future_values_are_supervised_labels_only": True,
        },
        "verification": {
            "pipeline_rows_original": len(original_labels),
            "pipeline_rows_corrected": len(corrected_labels),
            "reference_original_rows_matched": reference_match_count,
            "reference_corrected_rows_matched": reference_candidate_match_count,
            "all_requested_symbols_present": len(rows) == len(symbols),
            "source_sqlite_unchanged": True,
            "overlay_copied_to_sqlite": False,
        },
        "rows": rows,
    }
    body["replay_hash"] = _payload_hash(body)
    source_roots: list[Path] = [sqlite_resolved, overlay_resolved]
    if reference_impact_path is not None:
        source_roots.append(reference_impact_path.resolve())
    output = _write_immutable_json(
        output_path,
        body,
        source_roots=source_roots,
    )
    return DailyPriceResearchReplayResult(
        output_path=output,
        replay_hash=str(body["replay_hash"]),
        row_count=len(rows),
        reference_rows_matched=reference_match_count,
    )


__all__ = [
    "DailyPriceResearchReplayError",
    "DailyPriceResearchReplayResult",
    "HORIZON_TRADING_DAYS",
    "RESEARCH_LABEL_REPLAY_MODE",
    "RESEARCH_LABEL_REPLAY_SCHEMA_VERSION",
    "build_research_label_replay_from_overlay",
]
