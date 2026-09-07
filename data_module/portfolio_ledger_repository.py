"""隔離式、不可變持倉事件帳本。

這個 repository 是 TASK-LOOP-06 的資料層邊界。它只負責以 SQLite 保存
精確事件，不依賴 app_module、UI 或 broker。正式 JSONL／Paper ledger 的切換
由另外的核准 gate 決定；本模組本身沒有 delete、update 或清帳 API。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator, Mapping, Sequence


PORTFOLIO_LEDGER_SCHEMA_VERSION = "portfolio-ledger.v1"
LEDGER_EVENT_TYPES = frozenset({"trade", "compensation"})
LEDGER_NAMESPACES = frozenset({"manual", "paper", "backtest", "synthetic"})
MONEY_QUANTUM = Decimal("0.01")


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field_name} must be Decimal or a decimal string")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be a finite Decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _money(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    result = _decimal(value, field_name)
    if result != result.quantize(MONEY_QUANTUM):
        raise ValueError(f"{field_name} must be expressed in cents")
    if positive and result <= 0:
        raise ValueError(f"{field_name} must be positive")
    if not positive and result < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return result.quantize(MONEY_QUANTUM)


def _iso_date(value: str, field_name: str) -> str:
    text = str(value).strip()
    try:
        date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc
    return text


def _json_safe(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class PortfolioLedgerEvent:
    """一筆不可變交易或補償事件。

    金額在 Python 邊界使用 Decimal，SQLite 只保存整數分；股數是整數。
    ``compensation`` 不攜帶新的成交數值，只引用要抵銷的原事件。
    """

    event_id: str
    portfolio_id: str
    source_namespace: str
    occurred_at: str
    stock_code: str = ""
    stock_name: str = ""
    side: str | None = None
    quantity: int = 0
    price: Decimal = Decimal("0.00")
    fees: Decimal = Decimal("0.00")
    taxes: Decimal = Decimal("0.00")
    currency: str = "TWD"
    source_id: str = ""
    source_snapshot_hash: str = ""
    thesis_id: str = ""
    event_type: str = "trade"
    reverses_event_id: str | None = None
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    schema_version: str = PORTFOLIO_LEDGER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not str(self.event_id).strip():
            raise ValueError("event_id is required")
        if not str(self.portfolio_id).strip():
            raise ValueError("portfolio_id is required")
        if self.source_namespace not in LEDGER_NAMESPACES:
            raise ValueError(f"unsupported source namespace: {self.source_namespace}")
        if self.event_type not in LEDGER_EVENT_TYPES:
            raise ValueError(f"unsupported event type: {self.event_type}")
        _iso_date(self.occurred_at, "occurred_at")
        if not str(self.currency).strip():
            raise ValueError("currency is required")
        if self.event_type == "trade":
            if not str(self.stock_code).strip():
                raise ValueError("stock_code is required for trade")
            if self.side not in {"buy", "sell"}:
                raise ValueError("trade side must be buy or sell")
            if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
                raise ValueError("trade quantity must be an integer")
            if self.quantity <= 0:
                raise ValueError("trade quantity must be positive")
            _money(self.price, "price", positive=True)
            _money(self.fees, "fees")
            _money(self.taxes, "taxes")
            if self.reverses_event_id:
                raise ValueError("trade cannot reverse another event")
        else:
            if not str(self.reverses_event_id or "").strip():
                raise ValueError("compensation must reference an event")
            if self.side is not None or self.quantity != 0:
                raise ValueError("compensation cannot carry trade quantity")
            if _money(self.price, "price") != Decimal("0.00"):
                raise ValueError("compensation cannot carry price")
            if _money(self.fees, "fees") != Decimal("0.00"):
                raise ValueError("compensation cannot carry fees")
            if _money(self.taxes, "taxes") != Decimal("0.00"):
                raise ValueError("compensation cannot carry taxes")
            if not str(self.reason).strip():
                raise ValueError("compensation reason is required")

    @property
    def price_cents(self) -> int:
        return int(_money(self.price, "price") * 100)

    @property
    def fees_cents(self) -> int:
        return int(_money(self.fees, "fees") * 100)

    @property
    def taxes_cents(self) -> int:
        return int(_money(self.taxes, "taxes") * 100)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "portfolio_id": self.portfolio_id,
            "source_namespace": self.source_namespace,
            "occurred_at": self.occurred_at,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "side": self.side,
            "quantity": self.quantity,
            "price": str(_money(self.price, "price")),
            "fees": str(_money(self.fees, "fees")),
            "taxes": str(_money(self.taxes, "taxes")),
            "price_cents": self.price_cents,
            "fees_cents": self.fees_cents,
            "taxes_cents": self.taxes_cents,
            "currency": self.currency,
            "source_id": self.source_id,
            "source_snapshot_hash": self.source_snapshot_hash,
            "thesis_id": self.thesis_id,
            "event_type": self.event_type,
            "reverses_event_id": self.reverses_event_id,
            "reason": self.reason,
            "metadata": _json_safe(dict(self.metadata)),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class PortfolioLedgerReadModel:
    """跨頁可消費的帳本 read-model metadata。

    這個介面刻意只承諾來源與品質資訊；持倉數值由 domain replay 產生，
    因此 UI 不需要讀 SQLite，也不會把缺資料渲染成零。
    """

    portfolio_id: str
    source_namespace: str
    as_of_date: str
    quality: str
    source_ledger_id: str
    source_ledger_hash: str
    event_count: int
    missing_inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    candidate_only: bool = True

    def __post_init__(self) -> None:
        _iso_date(self.as_of_date, "as_of_date")
        if self.quality not in {"complete", "degraded", "blocked"}:
            raise ValueError("quality must be complete, degraded or blocked")
        if self.event_count < 0:
            raise ValueError("event_count must be non-negative")
        if self.candidate_only is not True:
            raise ValueError("portfolio read-model is candidate-only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "source_namespace": self.source_namespace,
            "as_of_date": self.as_of_date,
            "quality": self.quality,
            "source_ledger_id": self.source_ledger_id,
            "source_ledger_hash": self.source_ledger_hash,
            "event_count": self.event_count,
            "missing_inputs": list(self.missing_inputs),
            "warnings": list(self.warnings),
            "candidate_only": self.candidate_only,
        }


class PortfolioLedgerRepository:
    """單一 writer 的隔離 SQLite event store。

    ``initialize=False`` 可用於唯讀檢查；它不建立目錄、檔案或 schema。
    ``read_only=True`` 會以 SQLite URI 的 mode=ro 開啟，任何 DDL/DML 都會失敗。
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        initialize: bool = True,
        read_only: bool = False,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.read_only = read_only
        if read_only or not initialize:
            if not self.db_path.is_file():
                raise FileNotFoundError(self.db_path)
            if read_only:
                self._assert_schema_exists()
        else:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._ensure_schema()

    @classmethod
    def open_read_only(cls, db_path: str | Path) -> "PortfolioLedgerRepository":
        return cls(db_path, initialize=False, read_only=True)

    @classmethod
    def create_synthetic_fixture(
        cls,
        db_path: str | Path,
        *,
        events: Iterable[PortfolioLedgerEvent] = (),
    ) -> "PortfolioLedgerRepository":
        """建立只供測試／QA 使用的 candidate fixture。"""

        repository = cls(db_path)
        fixture_events = tuple(events)
        if fixture_events:
            repository.append_many(fixture_events)
        return repository

    def append(self, event: PortfolioLedgerEvent) -> None:
        self.append_many((event,))

    def append_many(self, events: Iterable[PortfolioLedgerEvent]) -> None:
        if self.read_only:
            raise PermissionError("portfolio ledger is read-only")
        entries = tuple(events)
        if not entries:
            raise ValueError("at least one ledger event is required")
        seen: set[str] = set()
        for event in entries:
            if event.event_id in seen:
                raise ValueError(f"duplicate event_id in batch: {event.event_id}")
            seen.add(event.event_id)
        with self._connection_scope() as connection:
            existing = {
                str(row[0])
                for row in connection.execute(
                    "SELECT event_id FROM portfolio_ledger_events WHERE event_id IN ({})".format(
                        ",".join("?" for _ in entries)
                    ),
                    tuple(item.event_id for item in entries),
                ).fetchall()
            }
            if existing:
                raise ValueError(f"ledger event already exists: {sorted(existing)[0]}")
            known_ids = {
                str(row[0])
                for row in connection.execute(
                    "SELECT event_id FROM portfolio_ledger_events"
                ).fetchall()
            }
            known_ids.update(seen)
            compensation_targets_in_batch: set[str] = set()
            for event in entries:
                if event.event_type == "compensation":
                    if event.reverses_event_id in compensation_targets_in_batch:
                        raise ValueError(
                            f"batch has duplicate compensation target: {event.reverses_event_id}"
                        )
                    compensation_targets_in_batch.add(str(event.reverses_event_id))
                    if event.reverses_event_id not in known_ids:
                        raise ValueError(
                            f"compensation target is missing: {event.reverses_event_id}"
                        )
                    if event.reverses_event_id in seen:
                        target = next(
                            item for item in entries if item.event_id == event.reverses_event_id
                        )
                        if target.event_type == "compensation":
                            raise ValueError("compensation cannot target compensation")
                        if (
                            target.portfolio_id != event.portfolio_id
                            or target.source_namespace != event.source_namespace
                        ):
                            raise ValueError("compensation target scope does not match")
                    else:
                        target_row = connection.execute(
                            "SELECT portfolio_id, source_namespace, event_type "
                            "FROM portfolio_ledger_events WHERE event_id = ?",
                            (event.reverses_event_id,),
                        ).fetchone()
                        if target_row is None or str(target_row["event_type"]) != "trade":
                            raise ValueError("compensation target must be a trade")
                        if (
                            str(target_row["portfolio_id"]) != event.portfolio_id
                            or str(target_row["source_namespace"]) != event.source_namespace
                        ):
                            raise ValueError("compensation target scope does not match")
                    duplicate = connection.execute(
                        "SELECT 1 FROM portfolio_ledger_events "
                        "WHERE event_type = 'compensation' AND reverses_event_id = ?",
                        (event.reverses_event_id,),
                    ).fetchone()
                    if duplicate is not None:
                        raise ValueError(
                            f"event already has a compensation: {event.reverses_event_id}"
                        )
            connection.executemany(
                """
                INSERT INTO portfolio_ledger_events (
                    schema_version, event_id, portfolio_id, source_namespace,
                    event_type, occurred_at, stock_code, stock_name, side,
                    quantity, price_cents, fees_cents, taxes_cents, currency,
                    source_id, source_snapshot_hash, thesis_id, reverses_event_id,
                    reason, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(self._event_row(item) for item in entries),
            )

    def append_compensation(
        self,
        reverses_event_id: str,
        *,
        event_id: str,
        occurred_at: str,
        reason: str,
        source_id: str = "",
    ) -> PortfolioLedgerEvent:
        target = self.get(reverses_event_id)
        if target is None:
            raise ValueError(f"ledger event not found: {reverses_event_id}")
        event = PortfolioLedgerEvent(
            event_id=event_id,
            portfolio_id=target.portfolio_id,
            source_namespace=target.source_namespace,
            occurred_at=occurred_at,
            stock_code=target.stock_code,
            stock_name=target.stock_name,
            currency=target.currency,
            source_id=source_id,
            source_snapshot_hash=target.source_snapshot_hash,
            thesis_id=target.thesis_id,
            event_type="compensation",
            reverses_event_id=reverses_event_id,
            reason=reason,
        )
        self.append(event)
        return event

    def get(self, event_id: str) -> PortfolioLedgerEvent | None:
        with self._connection_scope() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_ledger_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return None if row is None else _row_to_event(row)

    def list_events(
        self,
        *,
        portfolio_id: str | None = None,
        source_namespace: str | None = None,
        as_of_date: str | None = None,
    ) -> tuple[PortfolioLedgerEvent, ...]:
        clauses: list[str] = []
        params: list[object] = []
        if portfolio_id is not None:
            clauses.append("portfolio_id = ?")
            params.append(portfolio_id)
        if source_namespace is not None:
            if source_namespace not in LEDGER_NAMESPACES:
                raise ValueError(f"unsupported source namespace: {source_namespace}")
            clauses.append("source_namespace = ?")
            params.append(source_namespace)
        if as_of_date is not None:
            _iso_date(as_of_date, "as_of_date")
            clauses.append("substr(occurred_at, 1, 10) <= ?")
            params.append(as_of_date[:10])
        query = "SELECT * FROM portfolio_ledger_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY occurred_at, created_at, event_id"
        with self._connection_scope() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return tuple(_row_to_event(row) for row in rows)

    def source_hash(
        self,
        *,
        portfolio_id: str | None = None,
        source_namespace: str | None = None,
        as_of_date: str | None = None,
    ) -> str:
        payload = [
            event.to_dict()
            for event in self.list_events(
                portfolio_id=portfolio_id,
                source_namespace=source_namespace,
                as_of_date=as_of_date,
            )
        ]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def read_model(
        self,
        *,
        portfolio_id: str,
        source_namespace: str,
        as_of_date: str,
        source_ledger_id: str | None = None,
        missing_inputs: Sequence[str] = (),
        warnings: Sequence[str] = (),
    ) -> PortfolioLedgerReadModel:
        events = self.list_events(
            portfolio_id=portfolio_id,
            source_namespace=source_namespace,
            as_of_date=as_of_date,
        )
        missing = list(dict.fromkeys(str(item) for item in missing_inputs))
        warning_list = list(dict.fromkeys(str(item) for item in warnings))
        if not events:
            missing.append("ledger_events")
        quality = "blocked" if missing else ("degraded" if warning_list else "complete")
        return PortfolioLedgerReadModel(
            portfolio_id=portfolio_id,
            source_namespace=source_namespace,
            as_of_date=as_of_date,
            quality=quality,
            source_ledger_id=source_ledger_id or str(self.db_path),
            source_ledger_hash=self.source_hash(
                portfolio_id=portfolio_id,
                source_namespace=source_namespace,
                as_of_date=as_of_date,
            ),
            event_count=len(events),
            missing_inputs=tuple(missing),
            warnings=tuple(warning_list),
        )

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            uri = f"file:{self.db_path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        else:
            connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection_scope(self) -> Iterator[sqlite3.Connection]:
        """管理 transaction 與 close；SQLite context manager 本身不會 close。"""

        connection = self._connect()
        try:
            yield connection
            if not self.read_only:
                connection.commit()
        except BaseException:
            if not self.read_only:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connection_scope() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolio_ledger_events (
                    schema_version TEXT NOT NULL,
                    event_id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    source_namespace TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    side TEXT,
                    quantity INTEGER NOT NULL,
                    price_cents INTEGER NOT NULL,
                    fees_cents INTEGER NOT NULL,
                    taxes_cents INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_snapshot_hash TEXT NOT NULL,
                    thesis_id TEXT NOT NULL,
                    reverses_event_id TEXT,
                    reason TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_portfolio_ledger_scope
                    ON portfolio_ledger_events (portfolio_id, source_namespace, occurred_at, event_id);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_ledger_compensation_target
                    ON portfolio_ledger_events (reverses_event_id)
                    WHERE event_type = 'compensation';
                """
            )

    def _assert_schema_exists(self) -> None:
        with self._connection_scope() as connection:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'portfolio_ledger_events'"
            ).fetchone()
        if row is None:
            raise ValueError("portfolio ledger schema is missing")

    @staticmethod
    def _event_row(event: PortfolioLedgerEvent) -> tuple[object, ...]:
        created_at = event.created_at or datetime.now().isoformat(timespec="seconds")
        metadata = json.dumps(
            _json_safe(dict(event.metadata)), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return (
            event.schema_version,
            event.event_id,
            event.portfolio_id,
            event.source_namespace,
            event.event_type,
            event.occurred_at,
            event.stock_code,
            event.stock_name,
            event.side,
            event.quantity,
            event.price_cents,
            event.fees_cents,
            event.taxes_cents,
            event.currency,
            event.source_id,
            event.source_snapshot_hash,
            event.thesis_id,
            event.reverses_event_id,
            event.reason,
            metadata,
            created_at,
        )


def _row_to_event(row: sqlite3.Row) -> PortfolioLedgerEvent:
    metadata = json.loads(str(row["metadata_json"]))
    if not isinstance(metadata, dict):
        raise ValueError("portfolio ledger metadata must be an object")
    return PortfolioLedgerEvent(
        event_id=str(row["event_id"]),
        portfolio_id=str(row["portfolio_id"]),
        source_namespace=str(row["source_namespace"]),
        event_type=str(row["event_type"]),
        occurred_at=str(row["occurred_at"]),
        stock_code=str(row["stock_code"]),
        stock_name=str(row["stock_name"]),
        side=None if row["side"] is None else str(row["side"]),
        quantity=int(row["quantity"]),
        price=Decimal(int(row["price_cents"])) / Decimal("100"),
        fees=Decimal(int(row["fees_cents"])) / Decimal("100"),
        taxes=Decimal(int(row["taxes_cents"])) / Decimal("100"),
        currency=str(row["currency"]),
        source_id=str(row["source_id"]),
        source_snapshot_hash=str(row["source_snapshot_hash"]),
        thesis_id=str(row["thesis_id"]),
        reverses_event_id=(None if row["reverses_event_id"] is None else str(row["reverses_event_id"])),
        reason=str(row["reason"]),
        metadata=metadata,
        created_at=str(row["created_at"]),
        schema_version=str(row["schema_version"]),
    )


__all__ = [
    "LEDGER_EVENT_TYPES",
    "LEDGER_NAMESPACES",
    "MONEY_QUANTUM",
    "PORTFOLIO_LEDGER_SCHEMA_VERSION",
    "PortfolioLedgerEvent",
    "PortfolioLedgerReadModel",
    "PortfolioLedgerRepository",
]
