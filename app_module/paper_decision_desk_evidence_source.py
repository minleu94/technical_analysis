"""唯讀 Paper Portfolio -> Decision Desk 證據來源。

05:15 evidence dry-run 需要的是決策當下已存在的 Paper 狀態與 position
health 證據。既有 ``PortfolioService`` 是手動 JSONL 來源，不能在排程證據
流程中把它誤當成 Paper ledger。這個 adapter 只讀明確指定的隔離 Paper
snapshot SQLite 與 health baseline JSON，並把檔案／資料列 provenance 交給
Decision Desk 與 evidence importer。

缺少或無法驗證的來源一律回傳 ``unknown``／``MISSING``。已讀到但品質降級
的資料保留其 attribution 與 warning，讓 evidence 可以看見真實事件，同時
不會把 scheduler readiness 升級成 ready。此模組沒有 writer、schema 初始化、
網路請求或自動動作。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    PortfolioAlertAttribution,
    PortfolioAlertSummary,
)
from app_module.sqlite_read_only import ReadOnlySQLiteManager


PaperEvidenceStatus = Literal["ready", "degraded", "unknown"]

_ALLOWED_HEALTH_STATES = {
    "HEALTHY",
    "WATCH",
    "REDUCE_CANDIDATE",
    "EXIT_CANDIDATE",
    "CLOSED",
}
_REQUIRED_STATE_COLUMNS = {
    "snapshot_id",
    "portfolio_id",
    "decision_date",
    "cash",
    "total_value",
}
_REQUIRED_POSITION_COLUMNS = {
    "snapshot_id",
    "stock_code",
    "quantity",
    "mark_price",
    "market_value",
    "weight_bp",
}


@dataclass(frozen=True)
class PaperDecisionDeskEvidence:
    """Paper-derived alert section and its verified source metadata."""

    status: PaperEvidenceStatus
    portfolio_alerts: PortfolioAlertSummary
    metadata: dict[str, Any]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _PaperSnapshot:
    snapshot_id: str
    portfolio_id: str
    decision_date: date
    cash: Decimal
    total_value: Decimal
    positions: tuple[dict[str, Any], ...]
    rows_sha256: str
    data_version: int


def _dedupe(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values if str(item).strip()))


def _sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _canonical_sha256(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(raw)


def _parse_date(value: object, field_name: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO date")
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return parsed


def _parse_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite Decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite Decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be a finite non-negative Decimal")
    return parsed


def _parse_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be a non-negative integer")
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return parsed


def _read_json_with_hash(path: Path) -> tuple[dict[str, Any], str]:
    """Read one JSON file and reject a replacement during the read."""

    before = path.read_bytes()
    digest_before = _sha256_bytes(before)
    payload = json.loads(before.decode("utf-8-sig"))
    after = path.read_bytes()
    if after != before:
        raise ValueError(f"source_changed_during_read:{path}")
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON object required:{path}")
    return dict(payload), digest_before


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return {str(row[1]) for row in rows}


class PaperDecisionDeskEvidenceSource:
    """Read an as-of Paper snapshot and health baseline without any writes."""

    def __init__(
        self,
        *,
        state_db_path: str | Path,
        health_baseline_path: str | Path,
        status_path: str | Path | None = None,
        portfolio_id: str = "paper-main",
        max_health_age_days: int = 31,
    ) -> None:
        if not portfolio_id.strip():
            raise ValueError("portfolio_id is required")
        if isinstance(max_health_age_days, bool) or max_health_age_days <= 0:
            raise ValueError("max_health_age_days must be positive")
        self.state_db_path = Path(state_db_path).expanduser().resolve()
        self.health_baseline_path = Path(health_baseline_path).expanduser().resolve()
        self.status_path = (
            Path(status_path).expanduser().resolve()
            if status_path is not None
            else self.state_db_path.parent.parent
            / "scheduled"
            / "paper_portfolio_daily"
            / "latest_status.json"
        )
        self.portfolio_id = portfolio_id
        self.max_health_age_days = max_health_age_days

    def build(self, as_of_date: date) -> PaperDecisionDeskEvidence:
        if not isinstance(as_of_date, date):
            raise ValueError("as_of_date must be a date")

        blockers: list[str] = []
        warnings: list[str] = []
        metadata: dict[str, Any] = {
            "source_type": "paper_portfolio_snapshot_and_position_health",
            "as_of_date_requested": as_of_date.isoformat(),
            "state_db_path": str(self.state_db_path),
            "health_baseline_path": str(self.health_baseline_path),
            "status_path": str(self.status_path),
            "portfolio_id": self.portfolio_id,
            "read_only": True,
            "writes_allowed": False,
            "research_only": True,
            "formal_credit": False,
            "broker_order_allowed": False,
            "as_of_policy": "latest_paper_snapshot_on_or_before_requested_date",
        }

        status_payload, status_hash = self._read_status(blockers, warnings)
        if status_hash is not None:
            metadata["paper_status_sha256"] = status_hash
        snapshot: _PaperSnapshot | None = None
        try:
            snapshot, future_count = self._read_snapshot(as_of_date)
            if future_count:
                warnings.append(f"paper_snapshot_future_rows_excluded:{future_count}")
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as exc:
            blockers.append(f"paper_snapshot_unavailable:{type(exc).__name__}")

        if snapshot is None:
            blockers.append("paper_snapshot_as_of_missing")

        if status_payload is not None:
            self._validate_status(
                status_payload,
                as_of_date=as_of_date,
                snapshot=snapshot,
                blockers=blockers,
                warnings=warnings,
            )

        health_payload: dict[str, Any] | None = None
        health_hash: str | None = None
        try:
            health_payload, health_hash = _read_json_with_hash(self.health_baseline_path)
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            blockers.append(f"paper_health_baseline_unavailable:{type(exc).__name__}")

        if health_hash is not None:
            metadata["paper_health_baseline_sha256"] = health_hash

        if snapshot is None or health_payload is None:
            return self._unknown_result(
                as_of_date=as_of_date,
                metadata=metadata,
                blockers=blockers,
                warnings=warnings,
            )

        health_date: date | None = None
        try:
            health_date = _parse_date(health_payload.get("decision_date"), "health decision_date")
        except ValueError as exc:
            blockers.append(f"paper_health_baseline_invalid:{exc}")
        if health_date is None:
            return self._unknown_result(
                as_of_date=as_of_date,
                metadata=metadata,
                blockers=blockers,
                warnings=warnings,
            )
        metadata["paper_health_baseline_date"] = health_date.isoformat()
        if health_date > as_of_date:
            blockers.append("paper_health_baseline_future_dated")
        if health_date > snapshot.decision_date:
            blockers.append("paper_health_baseline_after_paper_snapshot")
        age_days = (as_of_date - health_date).days
        metadata["paper_health_age_days"] = age_days
        if age_days > self.max_health_age_days:
            warnings.append(
                f"paper_health_baseline_stale:{health_date.isoformat()}:{self.max_health_age_days}d"
            )

        if health_payload.get("research_only") is not True:
            blockers.append("paper_health_boundary_research_only_violation")
        if health_payload.get("auto_action_allowed") is not False:
            blockers.append("paper_health_boundary_auto_action_violation")
        if health_payload.get("writes_positions_db") is not False:
            blockers.append("paper_health_boundary_write_violation")

        # A health document from after the Paper snapshot would be a
        # look-ahead source for this decision.  Keep it unknown even if its
        # rows happen to contain matching symbols.
        if any(
            item in blockers
            for item in (
                "paper_health_baseline_future_dated",
                "paper_health_baseline_after_paper_snapshot",
                "paper_health_boundary_research_only_violation",
                "paper_health_boundary_auto_action_violation",
                "paper_health_boundary_write_violation",
            )
        ):
            return self._unknown_result(
                as_of_date=as_of_date,
                metadata=metadata,
                blockers=blockers,
                warnings=warnings,
            )

        raw_positions = health_payload.get("positions")
        if not isinstance(raw_positions, list):
            blockers.append("paper_health_positions_missing")
            raw_positions = []
        health_by_code: dict[str, Mapping[str, Any]] = {}
        for item in raw_positions:
            if not isinstance(item, Mapping):
                blockers.append("paper_health_position_invalid")
                continue
            code = str(item.get("stock_code") or "").strip()
            if not code:
                blockers.append("paper_health_position_code_missing")
                continue
            if code in health_by_code:
                blockers.append(f"paper_health_position_duplicate:{code}")
                continue
            health_by_code[code] = item

        known_attributions: list[PortfolioAlertAttribution] = []
        missing_codes: list[str] = []
        unknown_codes: list[str] = []
        for position in snapshot.positions:
            code = str(position["stock_code"])
            health = health_by_code.get(code)
            if health is None:
                missing_codes.append(code)
                continue
            state = str(health.get("state") or "").strip().upper()
            if state not in _ALLOWED_HEALTH_STATES:
                unknown_codes.append(code)
                continue
            required_fields = tuple(
                str(item).strip()
                for item in (health.get("required_human_fields") or [])
                if str(item).strip()
            )
            reasons = tuple(
                str(item).strip()
                for item in (health.get("reasons") or [])
                if str(item).strip()
            )
            if state == "HEALTHY" and required_fields:
                unknown_codes.append(code)
                blockers.append(f"paper_health_state_contract_violation:{code}")
                continue
            if state == "HEALTHY":
                continue
            severity, condition_status = self._health_alert_level(state)
            reason_list = list(reasons)
            if not reason_list:
                reason_list.append(f"health_state:{state.lower()}")
            if required_fields:
                reason_list.append(
                    "missing_human_fields:" + ",".join(required_fields)
                )
            flags = ["paper_health_state"]
            if required_fields:
                flags.append("required_human_fields_missing")
            source_trace = tuple(
                str(item).strip()
                for item in (health.get("source_trace") or [])
                if str(item).strip()
            )
            if source_trace:
                flags.append("health_source_trace_present")
            known_attributions.append(
                PortfolioAlertAttribution(
                    stock_code=code,
                    source_label="paper_position_health",
                    condition_status=condition_status,
                    chip_risk_level="unavailable",
                    severity=severity,
                    reasons=_dedupe(reason_list),
                    data_quality_flags=_dedupe(flags),
                )
            )

        if missing_codes:
            blockers.append(
                "paper_health_position_coverage_missing:" + ",".join(sorted(missing_codes))
            )
        if unknown_codes:
            blockers.append(
                "paper_health_position_state_unknown:" + ",".join(sorted(unknown_codes))
            )

        baseline_warnings = health_payload.get("warnings")
        if isinstance(baseline_warnings, list):
            warnings.extend(str(item) for item in baseline_warnings if str(item).strip())
        elif baseline_warnings is not None:
            blockers.append("paper_health_warnings_invalid")

        metadata.update(
            {
                "paper_snapshot_id": snapshot.snapshot_id,
                "paper_snapshot_date": snapshot.decision_date.isoformat(),
                "paper_snapshot_rows_sha256": snapshot.rows_sha256,
                "paper_snapshot_data_version": snapshot.data_version,
                "paper_position_count": len(snapshot.positions),
                "paper_health_known_position_count": len(known_attributions),
                "paper_health_missing_position_codes": sorted(missing_codes),
                "paper_health_unknown_position_codes": sorted(unknown_codes),
            }
        )
        if snapshot.decision_date < as_of_date:
            warnings.append(f"paper_snapshot_as_of_fallback:{snapshot.decision_date.isoformat()}")

        unique_blockers = _dedupe(blockers)
        unique_warnings = _dedupe(warnings)
        if not known_attributions and (missing_codes or unknown_codes or unique_blockers):
            return self._unknown_result(
                as_of_date=as_of_date,
                metadata=metadata,
                blockers=unique_blockers,
                warnings=unique_warnings,
            )

        quality = (
            DecisionDeskQuality.DEGRADED
            if unique_blockers or unique_warnings
            else DecisionDeskQuality.OBSERVED
        )
        alert_codes = tuple(
            item.stock_code
            for item in sorted(known_attributions, key=lambda item: (-item.severity, item.stock_code))
        )
        summary = PortfolioAlertSummary(
            as_of_date=snapshot.decision_date,
            quality=quality,
            warnings=unique_warnings,
            alert_count=len(known_attributions),
            alert_codes=alert_codes,
            alert_level=self._alert_level(known_attributions),
            attributions=tuple(
                sorted(known_attributions, key=lambda item: (-item.severity, item.stock_code))
            ),
        )
        status: PaperEvidenceStatus = "degraded" if quality != DecisionDeskQuality.OBSERVED else "ready"
        if unique_blockers:
            status = "degraded"
        metadata.update(
            {
                "source_status": status,
                "blockers": list(unique_blockers),
                "warnings": list(unique_warnings),
                "paper_evidence_as_of_date": snapshot.decision_date.isoformat(),
            }
        )
        return PaperDecisionDeskEvidence(
            status=status,
            portfolio_alerts=summary,
            metadata=metadata,
            blockers=unique_blockers,
            warnings=unique_warnings,
        )

    def _read_status(
        self,
        blockers: list[str],
        warnings: list[str],
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not self.status_path.is_file():
            warnings.append("paper_daily_status_missing")
            return None, None
        try:
            payload, digest = _read_json_with_hash(self.status_path)
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            blockers.append(f"paper_daily_status_unavailable:{type(exc).__name__}")
            return None, None
        return payload, digest

    def _validate_status(
        self,
        payload: Mapping[str, Any],
        *,
        as_of_date: date,
        snapshot: _PaperSnapshot | None,
        blockers: list[str],
        warnings: list[str],
    ) -> None:
        if payload.get("schema_version") != "paper-portfolio-daily-status.v1":
            blockers.append("paper_daily_status_schema_mismatch")
        status = str(payload.get("status") or "unknown")
        if status not in {"passed", "skipped_non_trading_day"}:
            blockers.append(f"paper_daily_status_{status}")
        if payload.get("writes_market_db") is not False:
            blockers.append("paper_daily_status_boundary_violation:writes_market_db")
        if payload.get("auto_rebalance_allowed") is not False:
            blockers.append("paper_daily_status_boundary_violation:auto_rebalance_allowed")
        if payload.get("broker_execution") is not False:
            blockers.append("paper_daily_status_boundary_violation:broker_execution")
        raw_date = payload.get("decision_date")
        try:
            status_date = _parse_date(raw_date, "paper status decision_date")
        except ValueError:
            blockers.append("paper_daily_status_date_invalid")
            return
        if status_date > as_of_date:
            blockers.append("paper_daily_status_future_dated")
        if snapshot is not None and status == "passed":
            if str(payload.get("snapshot_id") or "") != snapshot.snapshot_id:
                blockers.append("paper_daily_status_snapshot_mismatch")
            if str(payload.get("decision_date") or "") != snapshot.decision_date.isoformat():
                blockers.append("paper_daily_status_date_mismatch")
            reported_db = str(payload.get("state_db") or "").strip()
            if reported_db and Path(reported_db).expanduser().resolve() != self.state_db_path:
                blockers.append("paper_daily_status_state_db_path_mismatch")
        if status_date < as_of_date:
            warnings.append(f"paper_daily_status_as_of_fallback:{status_date.isoformat()}")

    def _read_snapshot(self, as_of_date: date) -> tuple[_PaperSnapshot | None, int]:
        manager = ReadOnlySQLiteManager(self.state_db_path)
        with manager.connect() as connection:
            connection.execute("BEGIN")
            snapshot_columns = _table_columns(connection, "paper_portfolio_snapshots")
            position_columns = _table_columns(connection, "paper_portfolio_positions")
            if not _REQUIRED_STATE_COLUMNS.issubset(snapshot_columns):
                raise ValueError("paper_snapshot_schema_missing")
            if not _REQUIRED_POSITION_COLUMNS.issubset(position_columns):
                raise ValueError("paper_position_schema_missing")
            rows = connection.execute(
                """
                SELECT snapshot_id, portfolio_id, decision_date, cash, total_value
                FROM paper_portfolio_snapshots
                WHERE portfolio_id = ?
                ORDER BY decision_date, snapshot_id
                """,
                (self.portfolio_id,),
            ).fetchall()
            eligible: list[sqlite3.Row] = []
            future_count = 0
            for row in rows:
                row_date = _parse_date(row["decision_date"], "paper snapshot decision_date")
                if row_date > as_of_date:
                    future_count += 1
                else:
                    eligible.append(row)
            if not eligible:
                return None, future_count
            row = eligible[-1]
            snapshot_id = str(row["snapshot_id"] or "").strip()
            if not snapshot_id:
                raise ValueError("paper snapshot_id missing")
            selected_date = _parse_date(row["decision_date"], "paper snapshot decision_date")
            positions_rows = connection.execute(
                """
                SELECT stock_code, quantity, mark_price, market_value, weight_bp
                FROM paper_portfolio_positions
                WHERE snapshot_id = ?
                ORDER BY stock_code
                """,
                (snapshot_id,),
            ).fetchall()
            positions: list[dict[str, Any]] = []
            for position in positions_rows:
                code = str(position["stock_code"] or "").strip()
                if not code:
                    raise ValueError("paper position stock_code missing")
                positions.append(
                    {
                        "stock_code": code,
                        "quantity": _parse_non_negative_int(position["quantity"], "paper position quantity"),
                        "mark_price": str(_parse_decimal(position["mark_price"], "paper position mark_price")),
                        "market_value": str(_parse_decimal(position["market_value"], "paper position market_value")),
                        "weight_bp": _parse_non_negative_int(position["weight_bp"], "paper position weight_bp"),
                    }
                )
            if not positions:
                raise ValueError("paper snapshot positions missing")
            canonical = {
                "snapshot": {
                    "snapshot_id": snapshot_id,
                    "portfolio_id": str(row["portfolio_id"]),
                    "decision_date": selected_date.isoformat(),
                    "cash": str(_parse_decimal(row["cash"], "paper snapshot cash")),
                    "total_value": str(_parse_decimal(row["total_value"], "paper snapshot total_value")),
                },
                "positions": positions,
            }
            data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
            return (
                _PaperSnapshot(
                    snapshot_id=snapshot_id,
                    portfolio_id=str(row["portfolio_id"]),
                    decision_date=selected_date,
                    cash=_parse_decimal(row["cash"], "paper snapshot cash"),
                    total_value=_parse_decimal(row["total_value"], "paper snapshot total_value"),
                    positions=tuple(positions),
                    rows_sha256=_canonical_sha256(canonical),
                    data_version=data_version,
                ),
                future_count,
            )

    def _unknown_result(
        self,
        *,
        as_of_date: date,
        metadata: dict[str, Any],
        blockers: list[str] | tuple[str, ...],
        warnings: list[str] | tuple[str, ...],
    ) -> PaperDecisionDeskEvidence:
        unique_blockers = _dedupe(tuple(str(item) for item in blockers))
        unique_warnings = _dedupe(tuple(str(item) for item in warnings))
        summary = PortfolioAlertSummary(
            as_of_date=None,
            quality=DecisionDeskQuality.MISSING,
            warnings=unique_warnings + unique_blockers,
            alert_count=None,
            alert_codes=(),
            alert_level=None,
            attributions=(),
        )
        metadata = dict(metadata)
        metadata.update(
            {
                "source_status": "unknown",
                "blockers": list(unique_blockers),
                "warnings": list(unique_warnings),
                "paper_evidence_as_of_date": as_of_date.isoformat(),
            }
        )
        return PaperDecisionDeskEvidence(
            status="unknown",
            portfolio_alerts=summary,
            metadata=metadata,
            blockers=unique_blockers,
            warnings=unique_warnings,
        )

    @staticmethod
    def _health_alert_level(state: str) -> tuple[int, str]:
        if state == "EXIT_CANDIDATE" or state == "CLOSED":
            return 100, "invalid"
        if state == "REDUCE_CANDIDATE":
            return 80, "warning"
        return 70, "warning"

    @staticmethod
    def _alert_level(attributions: list[PortfolioAlertAttribution]) -> str | None:
        if not attributions:
            return "low"
        highest = max(item.severity for item in attributions)
        if highest >= 100:
            return "high"
        if highest >= 70:
            return "medium"
        return "low"
