"""將舊 JSONL 交易紀錄轉成隔離帳本副本的受控工具。

這個檔案只讀取來源，並且只允許寫入呼叫者明確提供的 candidate SQLite。
沒有正式資料根目錄、正式 ledger 或 apply/delete/clear 的隱含路徑。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any

from data_module.portfolio_ledger_repository import (
    LEDGER_NAMESPACES,
    PortfolioLedgerEvent,
    PortfolioLedgerRepository,
)


@dataclass(frozen=True)
class PortfolioLedgerMigrationReport:
    source_path: str
    candidate_db_path: str
    source_hash: str | None
    status: str
    source_row_count: int
    valid_row_count: int
    migrated_event_count: int
    duplicate_event_count: int
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    candidate_only: bool = True
    write_performed: bool = False
    formal_apply_allowed: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"ready", "completed", "blocked", "rejected", "already_present"}:
            raise ValueError(f"unsupported migration status: {self.status}")
        for name in (
            "source_row_count",
            "valid_row_count",
            "migrated_event_count",
            "duplicate_event_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.candidate_only is not True or self.formal_apply_allowed is not False:
            raise ValueError("migration is candidate-only")
        if self.write_performed and self.status not in {"completed", "already_present"}:
            raise ValueError("write_performed requires completed status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "portfolio-ledger-migration.v1",
            "source_path": self.source_path,
            "candidate_db_path": self.candidate_db_path,
            "source_hash": self.source_hash,
            "status": self.status,
            "source_row_count": self.source_row_count,
            "valid_row_count": self.valid_row_count,
            "migrated_event_count": self.migrated_event_count,
            "duplicate_event_count": self.duplicate_event_count,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "candidate_only": self.candidate_only,
            "write_performed": self.write_performed,
            "formal_apply_allowed": self.formal_apply_allowed,
        }


class PortfolioLedgerMigration:
    """Read-only JSONL parser plus explicit candidate-copy writer."""

    def __init__(
        self,
        source_path: str | Path,
        candidate_db_path: str | Path,
        *,
        source_namespace: str = "manual",
        portfolio_id: str = "default",
    ) -> None:
        self.source_path = Path(source_path).expanduser().resolve()
        self.candidate_db_path = Path(candidate_db_path).expanduser().resolve()
        if source_namespace not in LEDGER_NAMESPACES:
            raise ValueError(f"unsupported source namespace: {source_namespace}")
        if source_namespace == "backtest":
            raise ValueError("backtest results cannot be migrated as portfolio fills")
        if not portfolio_id.strip():
            raise ValueError("portfolio_id is required")
        if self.source_path == self.candidate_db_path:
            raise ValueError("source JSONL and candidate database must be different paths")
        self.source_namespace = source_namespace
        self.portfolio_id = portfolio_id

    def preview(self) -> PortfolioLedgerMigrationReport:
        source_hash, rows, parse_blockers, diagnostics = self._read_source()
        events: list[PortfolioLedgerEvent] = []
        blockers = list(parse_blockers)
        warnings: list[str] = []
        seen: set[str] = set()
        for line_number, row in rows:
            try:
                event = self._to_event(row, line_number)
            except (TypeError, ValueError, InvalidOperation) as exc:
                blockers.append("legacy_trade_invalid")
                diagnostics.append(f"legacy_trade_invalid:{line_number}:{type(exc).__name__}:{exc}")
                continue
            if event.event_id in seen:
                blockers.append("legacy_trade_duplicate_event_id")
                diagnostics.append(f"legacy_trade_duplicate_event_id:{line_number}:{event.event_id}")
                continue
            seen.add(event.event_id)
            events.append(event)
        if self.source_namespace in {"paper", "backtest"}:
            warnings.append(f"source_namespace_requires_external_acceptance:{self.source_namespace}")
        status = "blocked" if blockers else "ready"
        return PortfolioLedgerMigrationReport(
            source_path=str(self.source_path),
            candidate_db_path=str(self.candidate_db_path),
            source_hash=source_hash,
            status=status,
            source_row_count=len(rows) + (1 if "legacy_trade_source_missing" in blockers else 0),
            valid_row_count=len(events),
            migrated_event_count=0,
            duplicate_event_count=0,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )

    def migrate_copy(self) -> PortfolioLedgerMigrationReport:
        source_hash, rows, parse_blockers, diagnostics = self._read_source()
        events: list[PortfolioLedgerEvent] = []
        blockers = list(parse_blockers)
        warnings: list[str] = []
        seen: set[str] = set()
        for line_number, row in rows:
            try:
                event = self._to_event(row, line_number)
            except (TypeError, ValueError, InvalidOperation) as exc:
                blockers.append("legacy_trade_invalid")
                diagnostics.append(f"legacy_trade_invalid:{line_number}:{type(exc).__name__}:{exc}")
                continue
            if event.event_id in seen:
                blockers.append("legacy_trade_duplicate_event_id")
                diagnostics.append(f"legacy_trade_duplicate_event_id:{line_number}:{event.event_id}")
                continue
            seen.add(event.event_id)
            events.append(event)
        if blockers:
            return PortfolioLedgerMigrationReport(
                source_path=str(self.source_path),
                candidate_db_path=str(self.candidate_db_path),
                source_hash=source_hash,
                status="blocked",
                source_row_count=len(rows),
                valid_row_count=len(events),
                migrated_event_count=0,
                duplicate_event_count=0,
                blockers=tuple(dict.fromkeys(blockers)),
                warnings=tuple(dict.fromkeys(warnings)),
                diagnostics=tuple(dict.fromkeys(diagnostics)),
            )

        repository = PortfolioLedgerRepository(self.candidate_db_path)
        existing_ids = {item.event_id for item in repository.list_events()}
        pending = [item for item in events if item.event_id not in existing_ids]
        duplicate_count = len(events) - len(pending)
        if pending:
            repository.append_many(pending)
        status = "completed" if pending else "already_present"
        if self.source_namespace in {"paper", "backtest"}:
            warnings.append(f"source_namespace_requires_external_acceptance:{self.source_namespace}")
        return PortfolioLedgerMigrationReport(
            source_path=str(self.source_path),
            candidate_db_path=str(self.candidate_db_path),
            source_hash=source_hash,
            status=status,
            source_row_count=len(rows),
            valid_row_count=len(events),
            migrated_event_count=len(pending),
            duplicate_event_count=duplicate_count,
            blockers=(),
            warnings=tuple(dict.fromkeys(warnings)),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            write_performed=True,
        )

    def _read_source(
        self,
    ) -> tuple[str | None, list[tuple[int, dict[str, Any]]], list[str], list[str]]:
        if not self.source_path.is_file():
            return None, [], ["legacy_trade_source_missing"], []
        try:
            raw = self.source_path.read_bytes()
        except OSError as exc:
            return None, [], ["legacy_trade_source_unavailable"], [
                f"legacy_trade_source_error:{type(exc).__name__}"
            ]
        source_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        rows: list[tuple[int, dict[str, Any]]] = []
        blockers: list[str] = []
        diagnostics: list[str] = []
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line, parse_float=Decimal, parse_int=int)
            except (UnicodeError, json.JSONDecodeError) as exc:
                blockers.append("legacy_trade_source_invalid_json")
                diagnostics.append(f"legacy_trade_source_invalid_json:{line_number}:{type(exc).__name__}")
                continue
            if not isinstance(value, dict):
                blockers.append("legacy_trade_row_not_object")
                diagnostics.append(f"legacy_trade_row_not_object:{line_number}")
                continue
            rows.append((line_number, value))
        return source_hash, rows, blockers, diagnostics

    def _to_event(self, row: dict[str, Any], line_number: int) -> PortfolioLedgerEvent:
        del line_number  # kept in the caller's diagnostic context
        event_type = str(row.get("event_type", "trade"))
        if event_type == "compensation":
            return PortfolioLedgerEvent(
                event_id=str(row.get("event_id", row.get("trade_id", ""))),
                portfolio_id=str(row.get("portfolio_id", self.portfolio_id)),
                source_namespace=self.source_namespace,
                occurred_at=str(row.get("occurred_at", row.get("trade_date", ""))),
                stock_code=str(row.get("stock_code", "")),
                stock_name=str(row.get("stock_name", "")),
                source_id=str(row.get("source_id", "")),
                source_snapshot_hash=str(row.get("source_snapshot_hash", "")),
                thesis_id=str(row.get("thesis_id", "")),
                event_type="compensation",
                reverses_event_id=str(row.get("reverses_event_id", "")),
                reason=str(row.get("reason", "legacy compensation")),
                metadata={"legacy_record": row},
                created_at=str(row.get("created_at", "")),
            )
        return PortfolioLedgerEvent(
            event_id=str(row.get("event_id", row.get("trade_id", ""))),
            portfolio_id=str(row.get("portfolio_id", self.portfolio_id)),
            source_namespace=self.source_namespace,
            occurred_at=str(row.get("occurred_at", row.get("trade_date", ""))),
            stock_code=str(row.get("stock_code", "")),
            stock_name=str(row.get("stock_name", "")),
            side=str(row.get("side", "")).lower(),
            quantity=_whole_number(row.get("quantity", 0), "quantity"),
            price=_money_value(row.get("price", "0"), "price", positive=True),
            fees=_money_value(row.get("fees", "0"), "fees"),
            taxes=_money_value(row.get("taxes", "0"), "taxes"),
            currency=str(row.get("currency", "TWD")),
            source_id=str(row.get("source_id", "")),
            source_snapshot_hash=str(row.get("source_snapshot_hash", "")),
            thesis_id=str(row.get("thesis_id", "")),
            metadata={
                "legacy_record": row,
                "legacy_source_hash": self._record_hash(row),
            },
            created_at=str(row.get("created_at", "")),
        )

    @staticmethod
    def _record_hash(row: dict[str, Any]) -> str:
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decimal_value(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field_name} must not be a binary float")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be Decimal-like") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _whole_number(value: object, field_name: str) -> int:
    number = _decimal_value(value, field_name)
    if number != number.to_integral_value() or number <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return int(number)


def _money_value(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    number = _decimal_value(value, field_name)
    if number != number.quantize(Decimal("0.01")):
        raise ValueError(f"{field_name} must be expressed in cents")
    if positive and number <= 0:
        raise ValueError(f"{field_name} must be positive")
    if not positive and number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number.quantize(Decimal("0.01"))


__all__ = ["PortfolioLedgerMigration", "PortfolioLedgerMigrationReport"]
