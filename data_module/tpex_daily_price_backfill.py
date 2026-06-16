"""Controlled TPEX daily price backfill into daily_prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Mapping

from decision_module.factors.factor_dtos import FactorDiagnostic


@dataclass(frozen=True)
class TpexDailyPriceNormalizeResult:
    rows: tuple[dict[str, object], ...]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True)
class TpexDailyPriceBackfillPlan:
    rows: tuple[dict[str, object], ...]
    diagnostics: tuple[FactorDiagnostic, ...]
    existing_count: int
    insert_count: int
    db_file: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "db_file", Path(self.db_file))

    @property
    def ready_for_apply(self) -> bool:
        return self.insert_count > 0 and not self.diagnostics

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# TPEX Daily Price Backfill Plan",
                "",
                f"- ready_for_apply: {str(self.ready_for_apply).lower()}",
                f"- source_row_count: {self.insert_count + self.existing_count + len(self.diagnostics)}",
                f"- insert_count: {self.insert_count}",
                f"- existing_count: {self.existing_count}",
                f"- diagnostics: {len(self.diagnostics)}",
                f"- db_file: {self.db_file}",
            ]
        )


@dataclass(frozen=True)
class TpexDailyPriceBackfillApplyResult:
    applied: bool
    inserted_count: int
    backup_file: Path | None
    plan: TpexDailyPriceBackfillPlan


def normalize_tpex_daily_price_rows(
    source_rows: list[Mapping[str, object]],
    *,
    fallback_date: str,
) -> TpexDailyPriceNormalizeResult:
    rows: list[dict[str, object]] = []
    diagnostics: list[FactorDiagnostic] = []
    for source_row in source_rows:
        stock_code = _first(source_row, "SecuritiesCompanyCode", "Code")
        stock_name = _first(source_row, "CompanyName", "CompanyAbbreviation", "Name")
        raw_date = _first(source_row, "Date") or fallback_date
        close = _decimal_text(_first(source_row, "Close", "ClosePrice"))

        if not re.fullmatch(r"\d{4}", stock_code):
            diagnostics.append(
                FactorDiagnostic(
                    code="tpex_daily_price.invalid_stock_code",
                    factor_name="market_data.tpex_daily_price",
                    stock_code=stock_code,
                    message="TPEX daily price row is missing a four-digit stock code",
                )
            )
            continue
        if close is None or Decimal(close) <= 0:
            diagnostics.append(
                FactorDiagnostic(
                    code="tpex_daily_price.invalid_price",
                    factor_name="market_data.tpex_daily_price",
                    stock_code=stock_code,
                    message="TPEX daily price row has missing or non-positive close price",
                )
            )
            continue

        change_sign, change_value = _split_change(_first(source_row, "Change", "ChangePrice"))
        rows.append(
            {
                "日期": _normalize_date(raw_date),
                "證券代號": stock_code,
                "證券名稱": stock_name,
                "成交股數": _int_value(_first(source_row, "TradingShares", "Volume")),
                "成交筆數": _int_value(_first(source_row, "TransactionNumber", "Trades")),
                "成交金額": _int_value(_first(source_row, "TransactionAmount", "Amount")),
                "開盤價": _decimal_text(_first(source_row, "Open", "OpenPrice")) or close,
                "最高價": _decimal_text(_first(source_row, "High", "HighPrice")) or close,
                "最低價": _decimal_text(_first(source_row, "Low", "LowPrice")) or close,
                "收盤價": close,
                "漲跌": change_sign,
                "漲跌價差": change_value,
                "最後揭示買價": _decimal_text(_first(source_row, "LastBestBidPrice", "BestBidPrice")),
                "最後揭示買量": _int_value(_first(source_row, "LastBestBidVolume", "BestBidVolume")),
                "最後揭示賣價": _decimal_text(_first(source_row, "LastBestAskPrice", "BestAskPrice")),
                "最後揭示賣量": _int_value(_first(source_row, "LastBestAskVolume", "BestAskVolume")),
                "本益比": _decimal_text(_first(source_row, "PERatio", "PE", "P/E")),
            }
        )

    deduped: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        deduped[(str(row["證券代號"]), str(row["日期"]))] = row
    return TpexDailyPriceNormalizeResult(rows=tuple(deduped.values()), diagnostics=tuple(diagnostics))


def build_tpex_daily_price_plan(
    *,
    db_file: Path,
    source_rows: list[Mapping[str, object]],
    fallback_date: str,
) -> TpexDailyPriceBackfillPlan:
    normalized = normalize_tpex_daily_price_rows(source_rows, fallback_date=fallback_date)
    target_date = _normalize_date(fallback_date)
    if normalized.diagnostics:
        return TpexDailyPriceBackfillPlan(
            rows=(),
            diagnostics=normalized.diagnostics,
            existing_count=0,
            insert_count=0,
            db_file=Path(db_file),
        )

    rows_to_insert: list[dict[str, object]] = []
    existing_count = 0
    with sqlite3.connect(db_file) as conn:
        for row in normalized.rows:
            if row["日期"] != target_date:
                continue
            exists = conn.execute(
                'SELECT 1 FROM daily_prices WHERE "證券代號" = ? AND "日期" = ? LIMIT 1',
                (row["證券代號"], row["日期"]),
            ).fetchone()
            if exists:
                existing_count += 1
            else:
                rows_to_insert.append(row)

    return TpexDailyPriceBackfillPlan(
        rows=tuple(rows_to_insert),
        diagnostics=(),
        existing_count=existing_count,
        insert_count=len(rows_to_insert),
        db_file=Path(db_file),
    )


def apply_tpex_daily_price_backfill(
    *,
    db_file: Path,
    backup_dir: Path,
    source_rows: list[Mapping[str, object]],
    fallback_date: str,
) -> TpexDailyPriceBackfillApplyResult:
    db_file = Path(db_file)
    plan = build_tpex_daily_price_plan(
        db_file=db_file,
        source_rows=source_rows,
        fallback_date=fallback_date,
    )
    if not plan.ready_for_apply:
        return TpexDailyPriceBackfillApplyResult(
            applied=False,
            inserted_count=0,
            backup_file=None,
            plan=plan,
        )

    backup_file = _backup_db(db_file, Path(backup_dir))
    try:
        inserted_count = _insert_daily_price_rows(db_file, plan.rows)
    except Exception:
        shutil.copy2(backup_file, db_file)
        raise
    return TpexDailyPriceBackfillApplyResult(
        applied=True,
        inserted_count=inserted_count,
        backup_file=backup_file,
        plan=plan,
    )


def _first(source_row: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = source_row.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _normalize_date(value: str) -> str:
    value = str(value).strip()
    if len(value) == 7 and value.isdigit():
        year = int(value[:3]) + 1911
        return f"{year:04d}{value[3:5]}{value[5:7]}"
    if len(value) == 8 and value.isdigit():
        return value
    return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")


def _decimal_text(value: str) -> str | None:
    value = _clean_number_text(value)
    if value is None:
        return None
    try:
        return str(Decimal(value))
    except InvalidOperation:
        return None


def _int_value(value: str) -> int | None:
    value = _clean_number_text(value)
    if value is None:
        return None
    try:
        return int(Decimal(value))
    except (InvalidOperation, ValueError):
        return None


def _clean_number_text(value: str) -> str | None:
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-", "N/A", "NA", "null", "None"}:
        return None
    return text


def _split_change(value: str) -> tuple[str | None, str | None]:
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-", "N/A", "NA"}:
        return None, None
    sign = ""
    if text[0] in {"+", "-"}:
        sign = text[0]
        text = text[1:]
    return sign or None, _decimal_text(text)


def _backup_db(db_file: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"{db_file.stem}_tpex_daily_price_backfill_{_timestamp()}{db_file.suffix}"
    shutil.copy2(db_file, backup_file)
    return backup_file


def _insert_daily_price_rows(db_file: Path, rows: tuple[dict[str, object], ...]) -> int:
    if not rows:
        return 0
    with sqlite3.connect(db_file) as conn:
        table_columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(daily_prices)").fetchall())
        available_columns = set(table_columns)
        prepared_rows = tuple(_prepare_row_for_table(row, available_columns) for row in rows)
        columns = tuple(column for column in prepared_rows[0].keys() if column in available_columns)
        required_columns = {"證券代號", "日期"}
        if not required_columns.issubset(columns):
            missing = ", ".join(sorted(required_columns.difference(columns)))
            raise ValueError(f"daily_prices table is missing required columns: {missing}")
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        update_columns = tuple(column for column in columns if column not in required_columns)
        conflict_clause = 'ON CONFLICT("證券代號", "日期") DO NOTHING'
        if update_columns:
            update_clause = ", ".join(f'"{column}" = excluded."{column}"' for column in update_columns)
            conflict_clause = f'ON CONFLICT("證券代號", "日期") DO UPDATE SET {update_clause}'
        sql = f"INSERT INTO daily_prices ({quoted_columns}) VALUES ({placeholders}) {conflict_clause}"
        values = [tuple(row.get(column) for column in columns) for row in prepared_rows]
        conn.executemany(sql, values)
        conn.commit()
    return len(rows)


def _prepare_row_for_table(row: dict[str, object], available_columns: set[str]) -> dict[str, object]:
    prepared = dict(row)
    change_sign = prepared.get("漲跌")
    if change_sign is not None:
        if "涨跌" in available_columns:
            prepared["涨跌"] = change_sign
        if "漲跌(+/-)" in available_columns:
            prepared["漲跌(+/-)"] = change_sign
    return prepared


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
