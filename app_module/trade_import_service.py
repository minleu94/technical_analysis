"""受控的 Broker CSV / Paper Trade 匯入邊界。

預覽階段永遠唯讀；只有呼叫端明確傳入 ``confirm=True``，且檔案 hash
仍與預覽一致、全部列通過驗證時，才會交給 PortfolioService append。
匯入本身不連接券商 API，也不代表實際成交或投資有效性。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app_module.dtos.portfolio_dtos import TradeDTO


TRADE_IMPORT_SCHEMA_VERSION = "trade-import.v1"
_REQUIRED_FIELDS = ("stock_code", "side", "quantity", "price", "trade_date")
_OPTIONAL_FIELDS = ("stock_name", "fees", "taxes", "notes")

_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "stock_code": ("stock_code", "stockcode", "symbol", "證券代號", "股票代號", "代號"),
    "stock_name": ("stock_name", "name", "證券名稱", "股票名稱", "名稱"),
    "side": ("side", "buy_sell", "action", "買賣", "買賣別", "交易別", "交易類別"),
    "quantity": ("quantity", "qty", "shares", "股數", "交易股數", "數量"),
    "price": ("price", "fill_price", "成交價", "成交單價", "單價"),
    "trade_date": ("trade_date", "date", "成交日期", "交易日期", "日期"),
    "fees": ("fees", "commission", "手續費", "手續費用"),
    "taxes": ("taxes", "tax", "交易稅", "稅金"),
    "notes": ("notes", "備註", "交易備註"),
}


@dataclass(frozen=True)
class TradeImportColumnMapping:
    stock_code: str
    side: str
    quantity: str
    price: str
    trade_date: str
    stock_name: str | None = None
    fees: str | None = None
    taxes: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        values = {
            name: value
            for name, value in self.to_dict().items()
            if value is not None
        }
        if any(not str(value).strip() for value in values.values()):
            raise ValueError("trade import column names must be non-empty")
        duplicates = [
            value
            for value in values.values()
            if list(values.values()).count(value) > 1
        ]
        if duplicates:
            raise ValueError(f"trade import columns must be unique: {sorted(set(duplicates))}")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "trade_date": self.trade_date,
            "fees": self.fees,
            "taxes": self.taxes,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class TradeImportRow:
    row_number: int
    trade_id: str
    stock_code: str
    stock_name: str
    side: str
    quantity: Decimal | None
    price: Decimal | None
    trade_date: str
    fees: Decimal
    taxes: Decimal
    notes: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "trade_id": self.trade_id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "side": self.side,
            "quantity": None if self.quantity is None else str(self.quantity),
            "price": None if self.price is None else str(self.price),
            "trade_date": self.trade_date,
            "fees": str(self.fees),
            "taxes": str(self.taxes),
            "notes": self.notes,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "valid": self.valid,
        }


@dataclass(frozen=True)
class TradeImportPreview:
    source_path: str
    source_hash: str
    encoding: str
    mapping: TradeImportColumnMapping
    rows: tuple[TradeImportRow, ...]
    warnings: tuple[str, ...] = ()
    schema_version: str = TRADE_IMPORT_SCHEMA_VERSION

    @property
    def valid_rows(self) -> tuple[TradeImportRow, ...]:
        return tuple(row for row in self.rows if row.valid)

    @property
    def invalid_rows(self) -> tuple[TradeImportRow, ...]:
        return tuple(row for row in self.rows if not row.valid)

    @property
    def ready_to_import(self) -> bool:
        return bool(self.rows) and not self.invalid_rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "source_hash": f"sha256:{self.source_hash}",
            "encoding": self.encoding,
            "mapping": self.mapping.to_dict(),
            "row_count": len(self.rows),
            "valid_row_count": len(self.valid_rows),
            "invalid_row_count": len(self.invalid_rows),
            "ready_to_import": self.ready_to_import,
            "warnings": list(self.warnings),
            "rows": [row.to_dict() for row in self.rows],
        }


class TradeImportService:
    """解析與提交交易 CSV；預覽不建立檔案、不寫 Portfolio。"""

    def preview_csv(
        self,
        source_path: str | Path,
        *,
        mapping: TradeImportColumnMapping | Mapping[str, str | None] | None = None,
        existing_trade_ids: Sequence[str] = (),
    ) -> TradeImportPreview:
        path = Path(source_path).expanduser().resolve()
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        text, encoding = _decode_csv(raw)
        reader = csv.DictReader(text.splitlines())
        headers = tuple(str(item or "").strip() for item in (reader.fieldnames or ()))
        if not headers:
            raise ValueError("trade import CSV requires a header row")
        column_mapping = _coerce_mapping(mapping, headers)
        _validate_headers(column_mapping, headers)
        existing_ids = {str(item) for item in existing_trade_ids}
        rows: list[TradeImportRow] = []
        occurrence_by_fingerprint: dict[str, int] = {}
        file_warnings: list[str] = []
        if encoding.lower() == "cp950":
            file_warnings.append("encoding_cp950_detected")

        for row_number, raw_row in enumerate(reader, start=2):
            row_values = {
                str(key): str(value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            }
            if not any(row_values.values()):
                file_warnings.append(f"empty_row_skipped:{row_number}")
                continue
            parsed = _parse_row(row_number, row_values, column_mapping)
            fingerprint = _row_fingerprint(parsed)
            occurrence = occurrence_by_fingerprint.get(fingerprint, 0) + 1
            occurrence_by_fingerprint[fingerprint] = occurrence
            trade_id = f"import_{source_hash[:16]}_{fingerprint[:12]}_{occurrence:02d}"
            if trade_id in existing_ids:
                parsed = _with_error(parsed, "trade_id_already_exists")
            rows.append(
                TradeImportRow(
                    row_number=parsed.row_number,
                    trade_id=trade_id,
                    stock_code=parsed.stock_code,
                    stock_name=parsed.stock_name,
                    side=parsed.side,
                    quantity=parsed.quantity,
                    price=parsed.price,
                    trade_date=parsed.trade_date,
                    fees=parsed.fees,
                    taxes=parsed.taxes,
                    notes=parsed.notes,
                    errors=parsed.errors,
                    warnings=parsed.warnings,
                )
            )

        if not rows:
            file_warnings.append("no_trade_rows")
        return TradeImportPreview(
            source_path=str(path),
            source_hash=source_hash,
            encoding=encoding,
            mapping=column_mapping,
            rows=tuple(rows),
            warnings=tuple(dict.fromkeys(file_warnings)),
        )

    def build_trade_dtos(
        self,
        preview: TradeImportPreview,
        *,
        portfolio_id: str = "default",
    ) -> tuple[TradeDTO, ...]:
        if not preview.ready_to_import:
            raise ValueError("trade import preview is not ready_to_import")
        source_id = f"sha256:{preview.source_hash}"
        result: list[TradeDTO] = []
        for row in preview.valid_rows:
            if row.quantity is None or row.price is None:
                raise ValueError(f"row {row.row_number} has missing numeric values")
            result.append(
                TradeDTO(
                    trade_id=row.trade_id,
                    portfolio_id=portfolio_id,
                    stock_code=row.stock_code,
                    stock_name=row.stock_name,
                    side=row.side,
                    # TradeDTO is a legacy presentation/storage boundary; all parsing
                    # and validation above remains Decimal based.
                    quantity=float(row.quantity),  # numeric-boundary: dto
                    price=float(row.price),  # numeric-boundary: dto
                    trade_date=row.trade_date,
                    fees=float(row.fees),  # numeric-boundary: dto
                    taxes=float(row.taxes),  # numeric-boundary: dto
                    notes=row.notes,
                    source_type="broker_csv",
                    source_id=source_id,
                    source_snapshot_hash=source_id,
                    source_summary={
                        "import_schema_version": preview.schema_version,
                        "source_path": preview.source_path,
                        "source_hash": source_id,
                        "source_row_number": row.row_number,
                        "encoding": preview.encoding,
                    },
                )
            )
        return tuple(result)

    def commit(
        self,
        preview: TradeImportPreview,
        portfolio_service: Any,
        *,
        confirm: bool = False,
    ) -> tuple[TradeDTO, ...]:
        """在二次確認與 source hash 未變更時提交整批交易。"""
        if not confirm:
            raise ValueError("trade import requires explicit confirm=True")
        if not preview.ready_to_import:
            raise ValueError("trade import preview contains invalid rows")
        current_hash = hashlib.sha256(Path(preview.source_path).read_bytes()).hexdigest()
        if current_hash != preview.source_hash:
            raise ValueError("trade import source changed after preview")
        trades = self.build_trade_dtos(preview)
        if not hasattr(portfolio_service, "record_trades"):
            raise TypeError("portfolio service does not expose atomic record_trades")
        result = portfolio_service.record_trades(trades)
        return tuple(result)


def _coerce_mapping(
    mapping: TradeImportColumnMapping | Mapping[str, str | None] | None,
    headers: tuple[str, ...],
) -> TradeImportColumnMapping:
    if mapping is None:
        inferred: dict[str, str | None] = {}
        normalized_headers = {header.casefold(): header for header in headers}
        for field, aliases in _HEADER_ALIASES.items():
            inferred[field] = next(
                (
                    normalized_headers[alias.casefold()]
                    for alias in aliases
                    if alias.casefold() in normalized_headers
                ),
                None,
            )
        missing = [field for field in _REQUIRED_FIELDS if not inferred.get(field)]
        if missing:
            raise ValueError(f"trade import columns missing: {', '.join(missing)}")
        return TradeImportColumnMapping(
            stock_code=str(inferred["stock_code"]),
            side=str(inferred["side"]),
            quantity=str(inferred["quantity"]),
            price=str(inferred["price"]),
            trade_date=str(inferred["trade_date"]),
            stock_name=inferred["stock_name"],
            fees=inferred["fees"],
            taxes=inferred["taxes"],
            notes=inferred["notes"],
        )
    if isinstance(mapping, TradeImportColumnMapping):
        return mapping
    values = dict(mapping)
    missing = [field for field in _REQUIRED_FIELDS if not values.get(field)]
    if missing:
        raise ValueError(f"trade import mapping missing: {', '.join(missing)}")
    return TradeImportColumnMapping(
        stock_code=str(values["stock_code"]),
        side=str(values["side"]),
        quantity=str(values["quantity"]),
        price=str(values["price"]),
        trade_date=str(values["trade_date"]),
        stock_name=_optional_string(values.get("stock_name")),
        fees=_optional_string(values.get("fees")),
        taxes=_optional_string(values.get("taxes")),
        notes=_optional_string(values.get("notes")),
    )


def _validate_headers(mapping: TradeImportColumnMapping, headers: tuple[str, ...]) -> None:
    header_set = set(headers)
    missing = [
        field
        for field, column in mapping.to_dict().items()
        if column is not None and column not in header_set
    ]
    if missing:
        raise ValueError(f"trade import mapped headers missing: {', '.join(missing)}")


def _parse_row(
    row_number: int,
    values: Mapping[str, str],
    mapping: TradeImportColumnMapping,
) -> TradeImportRow:
    errors: list[str] = []
    warnings: list[str] = []
    code = _value(values, mapping.stock_code)
    if not code:
        errors.append("stock_code_missing")
    name = _value(values, mapping.stock_name) if mapping.stock_name else ""
    if not name:
        name = code
        warnings.append("stock_name_missing_fallback_to_code")
    side = _normalize_side(_value(values, mapping.side))
    if side is None:
        errors.append("side_invalid")
        side = ""
    quantity = _parse_positive_decimal(_value(values, mapping.quantity), "quantity", errors)
    price = _parse_positive_decimal(_value(values, mapping.price), "price", errors)
    trade_date = _normalize_date(_value(values, mapping.trade_date))
    if trade_date is None:
        errors.append("trade_date_invalid")
        trade_date = ""
    fees = _parse_nonnegative_decimal(_value(values, mapping.fees), "fees", errors)
    taxes = _parse_nonnegative_decimal(_value(values, mapping.taxes), "taxes", errors)
    notes = _value(values, mapping.notes)
    return TradeImportRow(
        row_number=row_number,
        trade_id="",
        stock_code=code,
        stock_name=name,
        side=side,
        quantity=quantity,
        price=price,
        trade_date=trade_date,
        fees=fees,
        taxes=taxes,
        notes=notes,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _row_fingerprint(row: TradeImportRow) -> str:
    payload = {
        "stock_code": row.stock_code,
        "stock_name": row.stock_name,
        "side": row.side,
        "quantity": None if row.quantity is None else str(row.quantity),
        "price": None if row.price is None else str(row.price),
        "trade_date": row.trade_date,
        "fees": str(row.fees),
        "taxes": str(row.taxes),
        "notes": row.notes,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _with_error(row: TradeImportRow, error: str) -> TradeImportRow:
    return TradeImportRow(
        row_number=row.row_number,
        trade_id=row.trade_id,
        stock_code=row.stock_code,
        stock_name=row.stock_name,
        side=row.side,
        quantity=row.quantity,
        price=row.price,
        trade_date=row.trade_date,
        fees=row.fees,
        taxes=row.taxes,
        notes=row.notes,
        errors=tuple(dict.fromkeys((*row.errors, error))),
        warnings=row.warnings,
    )


def _decode_csv(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("trade import CSV encoding must be UTF-8 or CP950")


def _value(values: Mapping[str, str], column: str | None) -> str:
    return str(values.get(column or "", "") or "").strip()


def _normalize_side(value: str) -> str | None:
    normalized = value.strip().casefold()
    if normalized in {"buy", "b", "買", "買入", "買進"}:
        return "buy"
    if normalized in {"sell", "s", "賣", "賣出", "賣出"}:
        return "sell"
    return None


def _parse_positive_decimal(value: str, field_name: str, errors: list[str]) -> Decimal | None:
    result = _parse_decimal(value, field_name, errors)
    if result is not None and result <= 0:
        errors.append(f"{field_name}_must_be_positive")
        return None
    return result


def _parse_nonnegative_decimal(value: str, field_name: str, errors: list[str]) -> Decimal:
    if not value:
        return Decimal("0")
    result = _parse_decimal(value, field_name, errors)
    if result is None:
        return Decimal("0")
    if result < 0:
        errors.append(f"{field_name}_must_be_nonnegative")
        return Decimal("0")
    return result


def _parse_decimal(value: str, field_name: str, errors: list[str]) -> Decimal | None:
    if not value:
        errors.append(f"{field_name}_missing")
        return None
    try:
        result = Decimal(value.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        errors.append(f"{field_name}_invalid")
        return None
    if not result.is_finite():
        errors.append(f"{field_name}_invalid")
        return None
    return result


def _normalize_date(value: str) -> str | None:
    normalized = value.strip().replace("/", "-").replace(".", "-")
    if len(normalized) == 8 and normalized.isdigit():
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError:
        return None


def _optional_string(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


__all__ = [
    "TRADE_IMPORT_SCHEMA_VERSION",
    "TradeImportColumnMapping",
    "TradeImportPreview",
    "TradeImportRow",
    "TradeImportService",
]
