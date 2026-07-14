"""Read-only core-source adapter for Terra development generations."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType
from typing import Mapping

from data_module.ml_historical_snapshot_provider import (
    HistoricalIndexObservation,
    HistoricalPriceObservation,
    HistoricalTechnicalObservation,
)


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
class CoreSourceSnapshot:
    """Bounded observations and independent fingerprints for the allowed sources."""

    prices: tuple[HistoricalPriceObservation, ...]
    technicals: tuple[HistoricalTechnicalObservation, ...]
    market: tuple[HistoricalIndexObservation, ...]
    industries: tuple[HistoricalIndexObservation, ...]
    source_fingerprints: Mapping[str, str]
    source_tables: tuple[str, ...] = _SOURCE_TABLES
    query_only: bool = True

    def __post_init__(self) -> None:
        if self.source_tables != _SOURCE_TABLES:
            raise ValueError("Terra source whitelist mismatch")
        if not self.query_only:
            raise ValueError("Terra source access must be query-only")
        if set(self.source_fingerprints) != set(_SOURCE_TABLES):
            raise ValueError("each core source requires a fingerprint")
        for value in self.source_fingerprints.values():
            _require_sha256(value)


class CoreSourceAdapter:
    """Loads only the four approved source tables through SQLite read-only access."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        if not self._database_path.is_file():
            raise FileNotFoundError(self._database_path)

    def load(self, start: str, end: str) -> CoreSourceSnapshot:
        start_compact = _compact_date(start)
        end_compact = _compact_date(end)
        if start_compact > end_compact:
            raise ValueError("source date range is invalid")
        before = self._database_path.stat()
        with closing(self._connect()) as connection:
            schemas = self._validate_schema(connection)
            raw_rows = self._load_rows(connection, start_compact, end_compact)
        after = self._database_path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError("formal source database changed during development read")
        fingerprints = MappingProxyType(
            {
                table: _hash_payload(
                    {"table": table, "schema": list(schemas[table]), "rows": raw_rows[table]}
                )
                for table in _SOURCE_TABLES
            }
        )
        return CoreSourceSnapshot(
            prices=tuple(_price(row) for row in raw_rows["daily_prices"]),
            technicals=tuple(_technical(row) for row in raw_rows["technical_indicators"]),
            market=tuple(_market(row) for row in raw_rows["market_indices"]),
            industries=tuple(_industry(row) for row in raw_rows["industry_indices"]),
            source_fingerprints=fingerprints,
        )

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self._database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA query_only").fetchone() != (1,):
            connection.close()
            raise RuntimeError("SQLite query_only could not be enabled")
        return connection

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
        existing = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        schemas: dict[str, tuple[str, ...]] = {}
        for table in _SOURCE_TABLES:
            if table not in existing:
                raise ValueError(f"required core source is missing: {table}")
            columns = tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})"))
            missing = _REQUIRED_COLUMNS[table] - set(columns)
            if missing:
                raise ValueError(f"required columns missing from {table}: {sorted(missing)}")
            schemas[table] = columns
        return schemas

    @staticmethod
    def _load_rows(
        connection: sqlite3.Connection, start: str, end: str
    ) -> dict[str, list[tuple[object, ...]]]:
        return {
            "daily_prices": [
                tuple(row) for row in connection.execute(
                    'SELECT "證券代號", "日期", "成交股數", "成交金額", '
                    'CAST("開盤價" AS TEXT), CAST("最高價" AS TEXT), '
                    'CAST("最低價" AS TEXT), CAST("收盤價" AS TEXT) '
                    'FROM daily_prices WHERE "日期" BETWEEN ? AND ? ORDER BY "證券代號", "日期"',
                    (start, end),
                )
            ],
            "technical_indicators": [
                tuple(row) for row in connection.execute(
                    'SELECT "證券代號", "日期", CAST("RSI" AS TEXT), '
                    'CAST("MACD" AS TEXT), CAST("ADX" AS TEXT) '
                    'FROM technical_indicators WHERE "日期" BETWEEN ? AND ? ORDER BY "證券代號", "日期"',
                    (start, end),
                )
            ],
            "market_indices": [
                tuple(row) for row in connection.execute(
                    'SELECT "日期", CAST(COALESCE("收盤價", "收盤指數") AS TEXT) '
                    'FROM market_indices WHERE "日期" BETWEEN ? AND ? ORDER BY "日期"',
                    (start, end),
                )
            ],
            "industry_indices": [
                tuple(row) for row in connection.execute(
                    'SELECT "指數名稱", "日期", CAST("收盤指數" AS TEXT) '
                    'FROM industry_indices WHERE "日期" BETWEEN ? AND ? ORDER BY "指數名稱", "日期"',
                    (start, end),
                )
            ],
        }


def _price(row: tuple[object, ...]) -> HistoricalPriceObservation:
    return HistoricalPriceObservation(
        symbol=str(row[0]).strip(), trading_date=_iso_date(row[1]), volume=_integer(row[2]),
        turnover_amount_minor=_integer(row[3]), open_price=_decimal(row[4]), high_price=_decimal(row[5]),
        low_price=_decimal(row[6]), close_price=_decimal(row[7]),
    )


def _technical(row: tuple[object, ...]) -> HistoricalTechnicalObservation:
    return HistoricalTechnicalObservation(
        symbol=str(row[0]).strip(), trading_date=_iso_date(row[1]), rsi=_decimal(row[2]),
        macd=_decimal(row[3]), adx=_decimal(row[4]),
    )


def _market(row: tuple[object, ...]) -> HistoricalIndexObservation:
    return HistoricalIndexObservation("market", _iso_date(row[0]), _decimal(row[1]))


def _industry(row: tuple[object, ...]) -> HistoricalIndexObservation:
    return HistoricalIndexObservation(str(row[0]).strip(), _iso_date(row[1]), _decimal(row[2]))


def _compact_date(value: str) -> str:
    digits = value[:10].replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        raise ValueError("date must be ISO YYYY-MM-DD")
    return digits


def _iso_date(value: object) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _decimal(value: object) -> Decimal | None:
    if value is None or str(value).strip() in {"", "--", "-"}:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None


def _integer(value: object) -> int | None:
    decimal_value = _decimal(value)
    if decimal_value is None:
        return None
    try:
        return int(decimal_value)
    except (OverflowError, ValueError):
        return None


def _hash_payload(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("source fingerprint must be sha256")
