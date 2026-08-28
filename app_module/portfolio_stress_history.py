"""Portfolio Stress Lab 的 append-only 研究歷史保存與唯讀讀取面。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from app_module.sqlite_read_only import ReadOnlySQLiteManager
from app_module.portfolio_stress_lab_service import STRESS_LAB_SCHEMA_VERSION


STRESS_HISTORY_SCHEMA_VERSION = "portfolio-stress-history.v1"
DEFAULT_STRESS_HISTORY_FILENAME = "stress_history.sqlite"


@dataclass(frozen=True)
class PortfolioStressHistoryRecord:
    """單次 Stress Lab 結果的不可變、研究用途歷史快照。"""

    record_id: str
    scenario_id: str
    scenario_label: str
    run_at: str
    as_of_date: str | None
    status: str
    priced_position_count: int
    total_position_count: int
    base_market_value: Decimal | None
    stressed_market_value: Decimal | None
    value_delta: Decimal | None
    payload_json: str
    payload_hash: str
    research_only: bool = True
    investment_effectiveness_claim: bool = False
    schema_version: str = STRESS_HISTORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != STRESS_HISTORY_SCHEMA_VERSION:
            raise ValueError("unsupported stress history schema")
        for field_name in ("record_id", "scenario_id", "scenario_label", "run_at", "payload_json", "payload_hash"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if self.status not in {"ready", "partial", "not_computable"}:
            raise ValueError(f"unsupported stress result status: {self.status}")
        for field_name in ("priced_position_count", "total_position_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.priced_position_count > self.total_position_count:
            raise ValueError("priced_position_count cannot exceed total_position_count")
        for field_name in ("base_market_value", "stressed_market_value"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a finite non-negative Decimal or None")
        if self.value_delta is not None and (
            isinstance(self.value_delta, bool)
            or not isinstance(self.value_delta, Decimal)
            or not self.value_delta.is_finite()
        ):
            raise ValueError("value_delta must be a finite Decimal or None")
        if self.research_only is not True or self.investment_effectiveness_claim is not False:
            raise ValueError("stress history safety boundary must remain research-only")
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must be valid JSON") from exc
        if not isinstance(parsed, Mapping):
            raise ValueError("payload_json must contain an object")
        actual_hash = _payload_hash(parsed)
        if actual_hash != self.payload_hash:
            raise ValueError("payload_hash does not match payload_json")

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        run_at: str | None = None,
        record_id: str | None = None,
    ) -> "PortfolioStressHistoryRecord":
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != STRESS_LAB_SCHEMA_VERSION:
            raise ValueError("input must be a portfolio-stress-lab.v1 result")
        scenario = payload.get("scenario")
        if not isinstance(scenario, Mapping):
            raise ValueError("stress result scenario must be an object")
        scenario_id = _required_text(scenario.get("scenario_id"), "scenario_id")
        scenario_label = _required_text(scenario.get("label"), "scenario.label")
        status = _required_text(payload.get("status"), "status")
        priced_count = _non_negative_int(payload.get("priced_position_count"), "priced_position_count")
        total_count = _non_negative_int(payload.get("total_position_count"), "total_position_count")
        base_value = _optional_decimal(payload.get("base_market_value"), "base_market_value")
        stressed_value = _optional_decimal(payload.get("stressed_market_value"), "stressed_market_value")
        delta = _optional_signed_decimal(payload.get("value_delta"), "value_delta")
        if payload.get("research_only") is not True:
            raise ValueError("stress result must remain research_only")
        if payload.get("investment_effectiveness_claim") is not False:
            raise ValueError("stress result cannot claim investment effectiveness")
        canonical_payload = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        stable_record_id = record_id or f"stress:{payload_hash}"
        return cls(
            record_id=stable_record_id,
            scenario_id=scenario_id,
            scenario_label=scenario_label,
            run_at=run_at or _utc_now_text(),
            as_of_date=(None if payload.get("as_of_date") is None else str(payload.get("as_of_date"))),
            status=status,
            priced_position_count=priced_count,
            total_position_count=total_count,
            base_market_value=base_value,
            stressed_market_value=stressed_value,
            value_delta=delta,
            payload_json=canonical_payload,
            payload_hash=payload_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "scenario_id": self.scenario_id,
            "scenario_label": self.scenario_label,
            "run_at": self.run_at,
            "as_of_date": self.as_of_date,
            "status": self.status,
            "priced_position_count": self.priced_position_count,
            "total_position_count": self.total_position_count,
            "base_market_value": _decimal_text(self.base_market_value),
            "stressed_market_value": _decimal_text(self.stressed_market_value),
            "value_delta": _decimal_text(self.value_delta),
            "payload_hash": self.payload_hash,
            "research_only": self.research_only,
            "investment_effectiveness_claim": self.investment_effectiveness_claim,
        }


class PortfolioStressHistoryRepository:
    """明確確認後才使用的 append-only Stress history writer。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolio_stress_history (
                    schema_version TEXT NOT NULL,
                    record_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL,
                    scenario_label TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    as_of_date TEXT,
                    status TEXT NOT NULL,
                    priced_position_count INTEGER NOT NULL,
                    total_position_count INTEGER NOT NULL,
                    base_market_value TEXT,
                    stressed_market_value TEXT,
                    value_delta TEXT,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL UNIQUE,
                    research_only INTEGER NOT NULL,
                    investment_effectiveness_claim INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_portfolio_stress_history_run_at
                    ON portfolio_stress_history (run_at, record_id);
                """
            )

    def append(self, record: PortfolioStressHistoryRecord) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO portfolio_stress_history (
                        schema_version, record_id, scenario_id, scenario_label, run_at,
                        as_of_date, status, priced_position_count, total_position_count,
                        base_market_value, stressed_market_value, value_delta,
                        payload_json, payload_hash, research_only,
                        investment_effectiveness_claim
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.schema_version,
                        record.record_id,
                        record.scenario_id,
                        record.scenario_label,
                        record.run_at,
                        record.as_of_date,
                        record.status,
                        record.priced_position_count,
                        record.total_position_count,
                        _decimal_text(record.base_market_value),
                        _decimal_text(record.stressed_market_value),
                        _decimal_text(record.value_delta),
                        record.payload_json,
                        record.payload_hash,
                        int(record.research_only),
                        int(record.investment_effectiveness_claim),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("stress history record already exists") from exc


@dataclass(frozen=True)
class PortfolioStressHistoryReadDTO:
    """Stress history 的 query-only read model。"""

    status: str
    db_path: str
    records: tuple[PortfolioStressHistoryRecord, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    research_only: bool = True
    investment_effectiveness_claim: bool = False
    read_only: bool = True
    writes_allowed: bool = False

    def __post_init__(self) -> None:
        if self.status not in {"ready", "partial", "degraded", "not_configured"}:
            raise ValueError(f"unsupported stress history status: {self.status}")
        if (
            self.research_only is not True
            or self.investment_effectiveness_claim is not False
            or self.read_only is not True
            or self.writes_allowed is not False
        ):
            raise ValueError("stress history read boundary must remain fail-closed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STRESS_HISTORY_SCHEMA_VERSION,
            "status": self.status,
            "db_path": self.db_path,
            "record_count": len(self.records),
            "records": [item.to_dict() for item in self.records],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "research_only": self.research_only,
            "investment_effectiveness_claim": self.investment_effectiveness_claim,
            "read_only": self.read_only,
            "writes_allowed": self.writes_allowed,
        }


class PortfolioStressHistoryReadService:
    """只讀既有 Stress history，不會因檢查而建立資料庫。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def inspect(self, *, limit: int = 50) -> PortfolioStressHistoryReadDTO:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if not self.db_path.is_file():
            return PortfolioStressHistoryReadDTO(
                status="not_configured",
                db_path=str(self.db_path),
                warnings=("stress_history_not_configured",),
                diagnostics=(f"stress_history_path_missing:{self.db_path}",),
            )
        blockers: list[str] = []
        warnings: list[str] = []
        diagnostics: list[str] = []
        manager = ReadOnlySQLiteManager(self.db_path)
        try:
            with manager.connect() as conn:
                if not _table_exists(conn, "portfolio_stress_history"):
                    return PortfolioStressHistoryReadDTO(
                        status="degraded",
                        db_path=str(self.db_path),
                        blockers=("stress_history_table_missing",),
                    )
                rows = conn.execute(
                    """
                    SELECT schema_version, record_id, scenario_id, scenario_label, run_at,
                           as_of_date, status, priced_position_count, total_position_count,
                           base_market_value, stressed_market_value, value_delta,
                           payload_json, payload_hash, research_only,
                           investment_effectiveness_claim
                    FROM portfolio_stress_history
                    ORDER BY run_at DESC, record_id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except (FileNotFoundError, sqlite3.Error, OSError) as exc:
            return PortfolioStressHistoryReadDTO(
                status="degraded",
                db_path=str(self.db_path),
                blockers=("stress_history_db_unavailable",),
                diagnostics=(f"stress_history_db_error:{type(exc).__name__}",),
            )

        records: list[PortfolioStressHistoryRecord] = []
        for row in rows:
            try:
                record = PortfolioStressHistoryRecord(
                    schema_version=str(row["schema_version"]),
                    record_id=str(row["record_id"]),
                    scenario_id=str(row["scenario_id"]),
                    scenario_label=str(row["scenario_label"]),
                    run_at=str(row["run_at"]),
                    as_of_date=(None if row["as_of_date"] is None else str(row["as_of_date"])),
                    status=str(row["status"]),
                    priced_position_count=int(row["priced_position_count"]),
                    total_position_count=int(row["total_position_count"]),
                    base_market_value=_optional_decimal(row["base_market_value"], "base_market_value"),
                    stressed_market_value=_optional_decimal(row["stressed_market_value"], "stressed_market_value"),
                    value_delta=_optional_signed_decimal(row["value_delta"], "value_delta"),
                    payload_json=str(row["payload_json"]),
                    payload_hash=str(row["payload_hash"]),
                    research_only=_sqlite_bool(row["research_only"], "research_only"),
                    investment_effectiveness_claim=_sqlite_bool(
                        row["investment_effectiveness_claim"],
                        "investment_effectiveness_claim",
                    ),
                )
                records.append(record)
            except (KeyError, TypeError, ValueError, ArithmeticError, json.JSONDecodeError) as exc:
                blockers.append("stress_history_invalid_row")
                diagnostics.append(
                    f"stress_history_row_invalid:{row['record_id'] if 'record_id' in row.keys() else '<unknown>'}:"
                    f"{type(exc).__name__}"
                )
        if not rows:
            warnings.append("stress_history_empty")
        status = "degraded" if blockers else ("partial" if warnings else "ready")
        return PortfolioStressHistoryReadDTO(
            status=status,
            db_path=str(self.db_path),
            records=tuple(records),
            blockers=tuple(sorted(set(blockers))),
            warnings=tuple(sorted(set(warnings))),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
        )


def _payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _required_text(value: object, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    parsed = str(value).strip()
    if not parsed:
        raise ValueError(f"{field_name} is required")
    return parsed


def _non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be a non-negative integer")
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return parsed


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must not be bool")
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return parsed


def _optional_signed_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must not be bool")
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _sqlite_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool) or value not in (0, 1):
        raise ValueError(f"{field_name} must be canonical SQLite boolean 0 or 1")
    return value == 1


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "DEFAULT_STRESS_HISTORY_FILENAME",
    "PortfolioStressHistoryReadDTO",
    "PortfolioStressHistoryReadService",
    "PortfolioStressHistoryRecord",
    "PortfolioStressHistoryRepository",
    "STRESS_HISTORY_SCHEMA_VERSION",
]
