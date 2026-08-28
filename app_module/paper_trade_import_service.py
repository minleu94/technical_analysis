"""受控的 Paper Trade Ledger CSV 匯入服務。

這條路徑與手動 Portfolio 交易匯入刻意分開：CSV 必須提供完整的 paper
execution 欄位（狀態、reference/fill price、Decimal 成本、turnover 與
execution gap），服務不會從手動交易、snapshot 或市場資料猜測缺件。
預覽永遠唯讀；只有呼叫端明確傳入 ``confirm=True`` 才會 append 至 Paper
Trade Ledger，且固定保留 research-only 邊界。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from app_module.paper_trade_ledger import (
    PAPER_TRADE_EVENT_STATUSES,
    PaperTradeFill,
    PaperTradeLedgerRepository,
)


PAPER_TRADE_IMPORT_SCHEMA_VERSION = "paper-trade-import.v1"

_REQUIRED_FIELDS = (
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
)
PAPER_TRADE_IMPORT_FIELDS = _REQUIRED_FIELDS + ("override_reason",)
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "fill_id": ("fill_id", "fillid", "成交編號", "成交序號"),
    "order_id": ("order_id", "orderid", "委託編號", "訂單編號"),
    "portfolio_id": ("portfolio_id", "portfolio", "組合代號", "投資組合"),
    "event_date": ("event_date", "eventdate", "trade_date", "成交日期", "交易日期", "日期"),
    "stock_code": ("stock_code", "stockcode", "symbol", "證券代號", "股票代號", "代號"),
    "side": ("side", "buy_sell", "action", "買賣", "買賣別", "交易別"),
    "requested_quantity": (
        "requested_quantity",
        "requested_qty",
        "委託股數",
        "要求股數",
    ),
    "filled_quantity": ("filled_quantity", "filled_qty", "成交股數", "成交數量"),
    "reference_price": ("reference_price", "ref_price", "參考價", "基準價"),
    "fill_price": ("fill_price", "price", "成交價", "成交單價"),
    "commission": ("commission", "fee", "fees", "手續費", "手續費用"),
    "tax": ("tax", "taxes", "交易稅", "稅金"),
    "slippage_cost": ("slippage_cost", "slippage", "滑價成本"),
    "turnover_bp": ("turnover_bp", "turnover", "換手bp", "換手基點"),
    "execution_gap_bp": (
        "execution_gap_bp",
        "execution_gap",
        "執行落差bp",
        "執行落差基點",
    ),
    "status": ("status", "execution_status", "成交狀態", "狀態"),
    "source_event_id": (
        "source_event_id",
        "source_id",
        "來源事件",
        "來源事件編號",
    ),
    "override_reason": ("override_reason", "override", "覆寫原因", "人工覆寫原因"),
}


@dataclass(frozen=True)
class PaperTradeImportRow:
    """單一 Paper fills CSV 列的驗證結果。"""

    row_number: int
    fill_id: str
    order_id: str
    portfolio_id: str
    event_date: str
    stock_code: str
    side: str
    requested_quantity: int | None
    filled_quantity: int | None
    reference_price: Decimal | None
    fill_price: Decimal | None
    commission: Decimal | None
    tax: Decimal | None
    slippage_cost: Decimal | None
    turnover_bp: int | None
    execution_gap_bp: int | None
    status: str
    source_event_id: str
    override_reason: str | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "portfolio_id": self.portfolio_id,
            "event_date": self.event_date,
            "stock_code": self.stock_code,
            "side": self.side,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "reference_price": _decimal_text(self.reference_price),
            "fill_price": _decimal_text(self.fill_price),
            "commission": _decimal_text(self.commission),
            "tax": _decimal_text(self.tax),
            "slippage_cost": _decimal_text(self.slippage_cost),
            "turnover_bp": self.turnover_bp,
            "execution_gap_bp": self.execution_gap_bp,
            "status": self.status,
            "source_event_id": self.source_event_id,
            "override_reason": self.override_reason,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "valid": self.valid,
        }


@dataclass(frozen=True)
class PaperTradeImportPreview:
    """Paper fills CSV 的不可變預覽結果。"""

    source_path: str
    source_hash: str
    encoding: str
    mapping: Mapping[str, str]
    rows: tuple[PaperTradeImportRow, ...]
    warnings: tuple[str, ...] = ()
    schema_version: str = PAPER_TRADE_IMPORT_SCHEMA_VERSION

    @property
    def valid_rows(self) -> tuple[PaperTradeImportRow, ...]:
        return tuple(row for row in self.rows if row.valid)

    @property
    def invalid_rows(self) -> tuple[PaperTradeImportRow, ...]:
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
            "mapping": dict(self.mapping),
            "row_count": len(self.rows),
            "valid_row_count": len(self.valid_rows),
            "invalid_row_count": len(self.invalid_rows),
            "ready_to_import": self.ready_to_import,
            "warnings": list(self.warnings),
            "rows": [row.to_dict() for row in self.rows],
            "research_only": True,
            "broker_order_allowed": False,
            "auto_rebalance_allowed": False,
        }


class PaperTradeImportService:
    """解析、驗證並在確認後 append Paper Trade Ledger。"""

    def preview_csv(self, source_path: str | Path) -> PaperTradeImportPreview:
        path = Path(source_path).expanduser().resolve()
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        text, encoding = _decode_csv(raw)
        reader = csv.DictReader(text.splitlines())
        headers = tuple(str(item or "").strip() for item in (reader.fieldnames or ()))
        if not headers:
            raise ValueError("paper trade import CSV requires a header row")
        mapping = _infer_mapping(headers)
        rows: list[PaperTradeImportRow] = []
        warnings: list[str] = []
        seen_fill_ids: set[str] = set()
        seen_source_event_ids: set[str] = set()
        if encoding.casefold() == "cp950":
            warnings.append("encoding_cp950_detected")

        for row_number, raw_row in enumerate(reader, start=2):
            values = {
                str(key): str(value or "").strip()
                for key, value in raw_row.items()
                if key is not None
            }
            if not any(values.values()):
                warnings.append(f"empty_row_skipped:{row_number}")
                continue
            row = _parse_row(row_number, values, mapping, source_hash=source_hash)
            errors = list(row.errors)
            extra_values = raw_row.get(None)
            if isinstance(extra_values, list) and any(str(item or "").strip() for item in extra_values):
                errors.append("extra_columns_in_file")
            if row.fill_id and row.fill_id in seen_fill_ids:
                errors.append("fill_id_duplicate_in_file")
            if row.source_event_id and row.source_event_id in seen_source_event_ids:
                errors.append("source_event_id_duplicate_in_file")
            if row.fill_id:
                seen_fill_ids.add(row.fill_id)
            if row.source_event_id:
                seen_source_event_ids.add(row.source_event_id)
            rows.append(replace(row, errors=tuple(dict.fromkeys(errors))))
        if not rows:
            warnings.append("no_paper_trade_rows")
        return PaperTradeImportPreview(
            source_path=str(path),
            source_hash=source_hash,
            encoding=encoding,
            mapping=mapping,
            rows=tuple(rows),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def write_template(output_path: str | Path, *, overwrite: bool = False) -> Path:
        """建立空白 Paper fills CSV 範本，不產生任何成交資料。

        範本只包含受治理的欄位標題；不得預填示例成交，避免使用者把
        示意資料誤當成真實 execution evidence 匯入。預設拒絕覆寫既有檔案。
        """
        path = Path(output_path).expanduser().resolve()
        if path.exists() and not overwrite:
            raise FileExistsError(f"paper trade template already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle, lineterminator="\n").writerow(PAPER_TRADE_IMPORT_FIELDS)
        return path

    def build_fills(self, preview: PaperTradeImportPreview) -> tuple[PaperTradeFill, ...]:
        if not preview.ready_to_import:
            raise ValueError("paper trade import preview is not ready_to_import")
        return tuple(
            _row_to_fill(row, source_hash=preview.source_hash)
            for row in preview.valid_rows
        )

    def commit(
        self,
        preview: PaperTradeImportPreview,
        ledger_db: str | Path,
        *,
        confirm: bool = False,
    ) -> tuple[PaperTradeFill, ...]:
        """確認、hash 重驗證後，以 atomic batch append 至 Paper Ledger。"""
        if not confirm:
            raise ValueError("paper trade import requires explicit confirm=True")
        if not preview.ready_to_import:
            raise ValueError("paper trade import preview contains invalid rows")
        current_hash = hashlib.sha256(Path(preview.source_path).read_bytes()).hexdigest()
        if current_hash != preview.source_hash:
            raise ValueError("paper trade import source changed after preview")
        fills = self.build_fills(preview)
        PaperTradeLedgerRepository(ledger_db).append_many(fills)
        return fills


def _infer_mapping(headers: tuple[str, ...]) -> dict[str, str]:
    normalized_headers = {header.casefold(): header for header in headers}
    mapping: dict[str, str] = {}
    for field_name, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            column = normalized_headers.get(alias.casefold())
            if column is not None:
                mapping[field_name] = column
                break
    missing = [field_name for field_name in _REQUIRED_FIELDS if field_name not in mapping]
    if missing:
        raise ValueError("paper trade import columns missing: " + ", ".join(missing))
    return mapping


def _parse_row(
    row_number: int,
    values: Mapping[str, str],
    mapping: Mapping[str, str],
    *,
    source_hash: str,
) -> PaperTradeImportRow:
    errors: list[str] = []
    fill_id = _required_text(values, mapping["fill_id"], "fill_id", errors)
    order_id = _required_text(values, mapping["order_id"], "order_id", errors)
    portfolio_id = _required_text(values, mapping["portfolio_id"], "portfolio_id", errors)
    event_date = _normalize_date(
        _required_text(values, mapping["event_date"], "event_date", errors)
    )
    if event_date is None:
        errors.append("event_date_invalid")
        event_date = ""
    stock_code = _required_text(values, mapping["stock_code"], "stock_code", errors)
    side = _normalize_side(_required_text(values, mapping["side"], "side", errors))
    if side is None:
        errors.append("side_invalid")
        side = ""
    requested_quantity = _required_int(values, mapping["requested_quantity"], "requested_quantity", errors)
    filled_quantity = _required_int(values, mapping["filled_quantity"], "filled_quantity", errors)
    reference_price = _required_decimal(values, mapping["reference_price"], "reference_price", errors)
    fill_price = _optional_decimal(values, mapping["fill_price"], "fill_price", errors)
    commission = _required_decimal(values, mapping["commission"], "commission", errors)
    tax = _required_decimal(values, mapping["tax"], "tax", errors)
    slippage_cost = _required_decimal(values, mapping["slippage_cost"], "slippage_cost", errors)
    turnover_bp = _required_int(values, mapping["turnover_bp"], "turnover_bp", errors)
    execution_gap_bp = _required_int(
        values,
        mapping["execution_gap_bp"],
        "execution_gap_bp",
        errors,
    )
    status = _normalize_status(_required_text(values, mapping["status"], "status", errors))
    if status is None:
        errors.append("status_invalid")
        status = ""
    source_event_id = _required_text(
        values,
        mapping["source_event_id"],
        "source_event_id",
        errors,
    )
    override_reason = _optional_text(values, mapping.get("override_reason"))
    row = PaperTradeImportRow(
        row_number=row_number,
        fill_id=fill_id,
        order_id=order_id,
        portfolio_id=portfolio_id,
        event_date=event_date,
        stock_code=stock_code,
        side=side,
        requested_quantity=requested_quantity,
        filled_quantity=filled_quantity,
        reference_price=reference_price,
        fill_price=fill_price,
        commission=commission,
        tax=tax,
        slippage_cost=slippage_cost,
        turnover_bp=turnover_bp,
        execution_gap_bp=execution_gap_bp,
        status=status,
        source_event_id=source_event_id,
        override_reason=override_reason,
        errors=tuple(dict.fromkeys(errors)),
    )
    if row.valid:
        try:
            _row_to_fill(row, source_hash=source_hash)
        except (TypeError, ValueError, ArithmeticError) as exc:
            row = replace(row, errors=(f"paper_fill_invalid:{exc}",))
    return row


def _row_to_fill(row: PaperTradeImportRow, *, source_hash: str) -> PaperTradeFill:
    if (
        row.requested_quantity is None
        or row.filled_quantity is None
        or row.reference_price is None
        or row.commission is None
        or row.tax is None
        or row.slippage_cost is None
        or row.turnover_bp is None
        or row.execution_gap_bp is None
    ):
        raise ValueError(f"row {row.row_number} has missing paper fill values")
    return PaperTradeFill(
        fill_id=row.fill_id,
        order_id=row.order_id,
        portfolio_id=row.portfolio_id,
        event_date=row.event_date,
        stock_code=row.stock_code,
        side=row.side,
        requested_quantity=row.requested_quantity,
        filled_quantity=row.filled_quantity,
        reference_price=row.reference_price,
        fill_price=row.fill_price,
        commission=row.commission,
        tax=row.tax,
        slippage_cost=row.slippage_cost,
        turnover_bp=row.turnover_bp,
        execution_gap_bp=row.execution_gap_bp,
        status=row.status,
        source_event_id=f"paper_csv:{source_hash[:16]}:{row.source_event_id}",
        override_reason=row.override_reason,
        source_type="paper_trade_import",
        research_only=True,
        broker_order_allowed=False,
        auto_rebalance_allowed=False,
    )


def _required_text(
    values: Mapping[str, str],
    column: str,
    field_name: str,
    errors: list[str],
) -> str:
    value = str(values.get(column, "") or "").strip()
    if not value:
        errors.append(f"{field_name}_missing")
    return value


def _required_int(
    values: Mapping[str, str],
    column: str,
    field_name: str,
    errors: list[str],
) -> int | None:
    raw = _required_text(values, column, field_name, errors)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        errors.append(f"{field_name}_invalid")
        return None


def _required_decimal(
    values: Mapping[str, str],
    column: str,
    field_name: str,
    errors: list[str],
) -> Decimal | None:
    raw = _required_text(values, column, field_name, errors)
    if not raw:
        return None
    try:
        parsed = Decimal(raw.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        errors.append(f"{field_name}_invalid")
        return None
    if not parsed.is_finite():
        errors.append(f"{field_name}_invalid")
        return None
    return parsed


def _optional_decimal(
    values: Mapping[str, str],
    column: str,
    field_name: str,
    errors: list[str],
) -> Decimal | None:
    raw = str(values.get(column, "") or "").strip()
    if not raw:
        return None
    try:
        parsed = Decimal(raw.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        errors.append(f"{field_name}_invalid")
        return None
    if not parsed.is_finite():
        errors.append(f"{field_name}_invalid")
        return None
    return parsed


def _optional_text(values: Mapping[str, str], column: str | None) -> str | None:
    if column is None:
        return None
    value = str(values.get(column, "") or "").strip()
    return value or None


def _normalize_date(value: str) -> str | None:
    normalized = value.strip().replace("/", "-").replace(".", "-")
    if len(normalized) == 8 and normalized.isdigit():
        normalized = f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"
    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError:
        return None


def _normalize_side(value: str) -> str | None:
    normalized = value.strip().casefold()
    if normalized in {"buy", "b", "買", "買入", "買進"}:
        return "buy"
    if normalized in {"sell", "s", "賣", "賣出"}:
        return "sell"
    return None


def _normalize_status(value: str) -> str | None:
    normalized = value.strip().casefold().replace(" ", "_")
    aliases = {
        "filled": "filled",
        "partially_filled": "partially_filled",
        "partial": "partially_filled",
        "rejected": "rejected",
        "reject": "rejected",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "cancel": "cancelled",
        "成交": "filled",
        "部分成交": "partially_filled",
        "拒絕": "rejected",
        "取消": "cancelled",
    }
    result = aliases.get(normalized)
    if result not in PAPER_TRADE_EVENT_STATUSES:
        return None
    return result


def _decode_csv(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp950"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("paper trade import CSV encoding must be UTF-8 or CP950")


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "PAPER_TRADE_IMPORT_SCHEMA_VERSION",
    "PAPER_TRADE_IMPORT_FIELDS",
    "PaperTradeImportPreview",
    "PaperTradeImportRow",
    "PaperTradeImportService",
]
