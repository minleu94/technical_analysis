"""Read-only SQLite provider for causal historical ML feature snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable
from contextlib import closing


_SOURCE_TABLES = (
    "daily_prices",
    "technical_indicators",
    "market_indices",
    "industry_indices",
)
_REQUIRED_COLUMNS = {
    "daily_prices": frozenset(
        {"日期", "證券代號", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"}
    ),
    "technical_indicators": frozenset({"日期", "證券代號", "RSI", "MACD", "ADX"}),
    "market_indices": frozenset({"日期", "收盤指數", "收盤價"}),
    "industry_indices": frozenset({"日期", "指數名稱", "收盤指數"}),
}


@dataclass(frozen=True)
class HistoricalPriceObservation:
    symbol: str
    trading_date: str
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    close_price: Decimal | None
    volume: int | None
    turnover_amount_minor: int | None


@dataclass(frozen=True)
class HistoricalTechnicalObservation:
    symbol: str
    trading_date: str
    rsi: Decimal | None
    macd: Decimal | None
    adx: Decimal | None


@dataclass(frozen=True)
class HistoricalIndexObservation:
    index_name: str
    trading_date: str
    close_value: Decimal | None


@dataclass(frozen=True)
class HistoricalRawSnapshot:
    decision_date: str
    feature_as_of_date: str
    prices: tuple[HistoricalPriceObservation, ...]
    technicals: tuple[HistoricalTechnicalObservation, ...]
    market: tuple[HistoricalIndexObservation, ...]
    industries: tuple[HistoricalIndexObservation, ...]
    source_fingerprint: str
    query_count: int
    source_tables: tuple[str, ...] = _SOURCE_TABLES
    query_only: bool = True
    shadow_only: bool = True
    production_action_allowed: bool = False

    def __post_init__(self) -> None:
        if date.fromisoformat(self.feature_as_of_date) >= date.fromisoformat(self.decision_date):
            raise ValueError("feature_as_of_date must be before decision_date")
        if self.source_tables != _SOURCE_TABLES:
            raise ValueError("historical ML snapshot source whitelist mismatch")
        if not self.query_only or not self.shadow_only or self.production_action_allowed:
            raise ValueError("historical ML snapshot must remain read-only and shadow-only")


class MLHistoricalSnapshotProvider:
    """Loads bounded price/technical/market/industry history without write access."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)

    def load(
        self,
        *,
        decision_date: str,
        history_start_date: str,
        symbols: tuple[str, ...],
        industry_index_names: tuple[str, ...] = (),
    ) -> HistoricalRawSnapshot:
        source_stat_before = self.database_path.stat()
        decision = _compact_date(decision_date)
        history_start = _compact_date(history_start_date)
        normalized_symbols = _normalized_texts(symbols, field_name="symbols")
        normalized_industries = tuple(sorted({str(value).strip() for value in industry_index_names if str(value).strip()}))
        query_count = 0
        with closing(self._connect()) as connection:
            schema = self._validate_schema(connection)
            symbol_clause = _placeholders(normalized_symbols)
            cutoff_row = connection.execute(
                f'SELECT MAX("日期") FROM daily_prices '
                f'WHERE "日期" < ? AND "證券代號" IN ({symbol_clause})',
                (decision, *normalized_symbols),
            ).fetchone()
            query_count += 1
            if cutoff_row is None or cutoff_row[0] is None:
                raise ValueError("no previous trading day is available for the requested symbols")
            cutoff = str(cutoff_row[0])

            prices = tuple(
                HistoricalPriceObservation(
                    symbol=str(row[0]).strip(), trading_date=_iso_date(row[1]),
                    volume=_integer(row[2]), turnover_amount_minor=_integer(row[3]),
                    open_price=_decimal(row[4]), high_price=_decimal(row[5]),
                    low_price=_decimal(row[6]), close_price=_decimal(row[7]),
                )
                for row in connection.execute(
                    f'SELECT "證券代號", "日期", "成交股數", "成交金額", '
                    f'CAST("開盤價" AS TEXT), CAST("最高價" AS TEXT), '
                    f'CAST("最低價" AS TEXT), CAST("收盤價" AS TEXT) '
                    f'FROM daily_prices WHERE "日期" BETWEEN ? AND ? '
                    f'AND "證券代號" IN ({symbol_clause}) ORDER BY "證券代號", "日期"',
                    (history_start, cutoff, *normalized_symbols),
                )
            )
            query_count += 1
            technicals = tuple(
                HistoricalTechnicalObservation(
                    symbol=str(row[0]).strip(), trading_date=_iso_date(row[1]),
                    rsi=_decimal(row[2]), macd=_decimal(row[3]), adx=_decimal(row[4]),
                )
                for row in connection.execute(
                    f'SELECT "證券代號", "日期", CAST("RSI" AS TEXT), '
                    f'CAST("MACD" AS TEXT), CAST("ADX" AS TEXT) '
                    f'FROM technical_indicators WHERE "日期" BETWEEN ? AND ? '
                    f'AND "證券代號" IN ({symbol_clause}) ORDER BY "證券代號", "日期"',
                    (history_start, cutoff, *normalized_symbols),
                )
            )
            query_count += 1
            market = tuple(
                HistoricalIndexObservation(
                    index_name="market", trading_date=_iso_date(row[0]), close_value=_decimal(row[1])
                )
                for row in connection.execute(
                    'SELECT "日期", CAST(COALESCE("收盤價", "收盤指數") AS TEXT) '
                    'FROM market_indices WHERE "日期" BETWEEN ? AND ? ORDER BY "日期"',
                    (history_start, cutoff),
                )
            )
            query_count += 1
            industries: tuple[HistoricalIndexObservation, ...] = ()
            if normalized_industries:
                industry_clause = _placeholders(normalized_industries)
                industries = tuple(
                    HistoricalIndexObservation(
                        index_name=str(row[0]), trading_date=_iso_date(row[1]), close_value=_decimal(row[2])
                    )
                    for row in connection.execute(
                        f'SELECT "指數名稱", "日期", CAST("收盤指數" AS TEXT) '
                        f'FROM industry_indices WHERE "日期" BETWEEN ? AND ? '
                        f'AND "指數名稱" IN ({industry_clause}) ORDER BY "指數名稱", "日期"',
                        (history_start, cutoff, *normalized_industries),
                    )
                )
            else:
                # Keep a stable batch-query audit count without broad-reading all industries.
                connection.execute('SELECT 1 FROM industry_indices WHERE 0').fetchall()
            query_count += 1

        source_stat_after = self.database_path.stat()
        if (
            source_stat_after.st_size,
            source_stat_after.st_mtime_ns,
        ) != (
            source_stat_before.st_size,
            source_stat_before.st_mtime_ns,
        ):
            raise RuntimeError("historical SQLite source changed during snapshot load")
        return HistoricalRawSnapshot(
            decision_date=_iso_date(decision), feature_as_of_date=_iso_date(cutoff),
            prices=prices, technicals=technicals, market=market, industries=industries,
            source_fingerprint=self._fingerprint(schema, source_stat_before), query_count=query_count,
        )

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        enabled = connection.execute("PRAGMA query_only").fetchone()
        if enabled != (1,):
            connection.close()
            raise RuntimeError("SQLite query_only could not be enabled")
        return connection

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
        schema: dict[str, tuple[str, ...]] = {}
        existing = {str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        for table in _SOURCE_TABLES:
            if table not in existing:
                raise ValueError(f"required table is missing: {table}")
            columns = tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})"))
            missing = _REQUIRED_COLUMNS[table] - set(columns)
            if missing:
                raise ValueError(f"required columns are missing from {table}: {sorted(missing)}")
            schema[table] = columns
        return schema

    def _fingerprint(
        self, schema: dict[str, tuple[str, ...]], stat: object
    ) -> str:
        payload = {
            "path": str(self.database_path), "size": getattr(stat, "st_size"),
            "mtime_ns": getattr(stat, "st_mtime_ns"), "schema": schema,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return f"sha256:{digest}"


def _normalized_texts(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    result = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    return result


def _placeholders(values: tuple[str, ...]) -> str:
    return ",".join("?" for _ in values)


def _compact_date(value: str) -> str:
    return date.fromisoformat(value[:10]).strftime("%Y%m%d")


def _iso_date(value: object) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:])).isoformat()
    return date.fromisoformat(text[:10]).isoformat()


def _decimal(value: object) -> Decimal | None:
    if value is None or str(value).strip() in {"", "--", "-"}:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None


def _integer(value: object) -> int | None:
    if value is None or str(value).strip() in {"", "--", "-"}:
        return None
    try:
        return int(Decimal(str(value).replace(",", "").strip()))
    except (InvalidOperation, ValueError):
        return None
