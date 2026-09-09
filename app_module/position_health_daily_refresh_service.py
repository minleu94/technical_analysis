"""從隔離 Paper snapshot 建立每日、唯讀的 position-health baseline。

這個 producer 只更新 derived JSON。它不會把缺少的 thesis、invalidation 或
review 欄位填成推測值，也不會執行 health transition；未知內容維持
``WATCH``／unknown，讓 evidence consumer 可以明確阻擋。Paper SQLite 以同一個
``mode=ro``／``query_only`` transaction 讀取，舊 baseline 只用來保留已輸入的
人工作業欄位，不作為新的市場觀測。跨日期承接還必須有同一 snapshot identity
或 Paper trade ledger 證明期間沒有該代號的買賣事件；無法證明時只保留歷史欄位。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from app_module.position_health_baseline_service import PositionHealthBaselineService
from app_module.paper_position_identity_provider import (
    PaperPositionIdentityProvider,
    PositionIdentitySourceResult,
)
from app_module.sqlite_read_only import ReadOnlySQLiteManager


SCHEMA_VERSION = "position-health-daily-refresh.v1"
_REQUIRED_STATE_COLUMNS = {
    "snapshot_id",
    "portfolio_id",
    "decision_date",
    "source_result_id",
    "cash",
    "total_value",
}
_REQUIRED_POSITION_COLUMNS = {
    "snapshot_id",
    "stock_code",
    "quantity",
    "weight_bp",
}
_REQUIRED_LEDGER_COLUMNS = {
    "schema_version",
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
    "override_reason",
    "source_type",
    "research_only",
    "broker_order_allowed",
    "auto_rebalance_allowed",
}
_HEALTH_FIELDS = ("entry_thesis", "invalidation", "holding_horizon", "review_date")
_HEALTH_STATES = {
    "HEALTHY",
    "WATCH",
    "REDUCE_CANDIDATE",
    "EXIT_CANDIDATE",
    "CLOSED",
}


@dataclass(frozen=True)
class _PaperSnapshot:
    snapshot_id: str
    portfolio_id: str
    decision_date: date
    source_result_id: str
    positions: tuple[dict[str, Any], ...]
    rows_sha256: str
    data_version: int


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_sha256(payload: object) -> str:
    return _sha256_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


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


def _non_negative_int(value: object, field_name: str) -> int:
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
    before = path.read_bytes()
    digest = _sha256_bytes(before)
    payload = json.loads(before.decode("utf-8-sig"))
    after = path.read_bytes()
    if before != after:
        raise ValueError(f"source_changed_during_read:{path}")
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON object required:{path}")
    return dict(payload), digest


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return {str(row[1]) for row in rows}


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item).strip()))


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(_canonical_json(payload), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class PositionHealthDailyRefreshService:
    """Create a fresh Paper-derived health baseline without inventing health."""

    def __init__(
        self,
        *,
        state_db_path: str | Path,
        status_path: str | Path,
        ledger_db_path: str | Path | None = None,
        coverage_status_path: str | Path | None = None,
        portfolio_id: str = "paper-main",
        position_identity_provider: PaperPositionIdentityProvider | None = None,
    ) -> None:
        if not portfolio_id.strip():
            raise ValueError("portfolio_id is required")
        self.state_db_path = Path(state_db_path).expanduser().resolve()
        self.status_path = Path(status_path).expanduser().resolve()
        self.ledger_db_path = (
            Path(ledger_db_path).expanduser().resolve()
            if ledger_db_path is not None
            else self.state_db_path.parent.parent / "paper_trade_ledger.sqlite"
        )
        self.coverage_status_path = (
            Path(coverage_status_path).expanduser().resolve()
            if coverage_status_path is not None
            else self.state_db_path.parent.parent
            / "scheduled"
            / "paper_portfolio_isolated"
            / "latest_status.json"
        )
        self.portfolio_id = portfolio_id
        self.position_identity_provider = position_identity_provider

    def refresh(
        self,
        *,
        as_of_date: date,
        output_dir: str | Path,
        previous_baseline_path: str | Path | None = None,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(as_of_date, date):
            raise ValueError("as_of_date must be a date")
        observed = observed_at or datetime.now(timezone.utc)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at must include timezone")
        observed_utc = observed.astimezone(timezone.utc)
        output = Path(output_dir).expanduser().resolve()
        base_status: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "producer": "app_module.position_health_daily_refresh_service",
            "observed_at": observed_utc.isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "state_db_path": str(self.state_db_path),
            "paper_status_path": str(self.status_path),
            "paper_trade_ledger_path": str(self.ledger_db_path),
            "paper_snapshot_coverage_status_path": str(self.coverage_status_path),
            "portfolio_id": self.portfolio_id,
            "research_only": True,
            "writes_positions_db": False,
            "writes_paper_state": False,
            "auto_action_allowed": False,
            "broker_execution": False,
            "formal_credit": False,
            "read_only_sources": True,
        }
        try:
            self._validate_output_dir(output)
            snapshot = self._read_snapshot(as_of_date)
            status_payload, status_hash = _read_json_with_hash(self.status_path)
            blockers, warnings = self._validate_status(
                status_payload,
                as_of_date=as_of_date,
                snapshot=snapshot,
            )
            if blockers:
                return self._blocked(
                    output=output,
                    base_status=base_status,
                    blockers=blockers,
                    warnings=warnings,
                    snapshot=snapshot,
                )
            (
                previous,
                previous_hash,
                previous_warnings,
                previous_snapshot_id,
                previous_snapshot_date,
            ) = self._read_previous_baseline(
                previous_baseline_path,
                snapshot_date=snapshot.decision_date,
            )
            warnings.extend(previous_warnings)
            identity_source: PositionIdentitySourceResult | None = None
            if self.position_identity_provider is not None:
                identity_source = self.position_identity_provider.resolve(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_date=snapshot.decision_date,
                    observed_at=observed_utc,
                    previous_baseline=previous,
                )
                warnings.extend(identity_source.warnings)
                if identity_source.blockers:
                    return self._blocked(
                        output=output,
                        base_status=base_status,
                        blockers=list(identity_source.blockers),
                        warnings=warnings,
                        snapshot=snapshot,
                    )
            baseline = self._build_baseline(
                snapshot=snapshot,
                previous=previous,
                previous_hash=previous_hash,
                previous_snapshot_id=previous_snapshot_id,
                previous_snapshot_date=previous_snapshot_date,
                status_hash=status_hash,
                as_of_date=as_of_date,
                warnings=warnings,
                identity_source=identity_source,
            )
            return self._persist(
                output=output,
                baseline=baseline,
                snapshot=snapshot,
                observed_at=observed_utc,
                warnings=warnings,
                status_hash=status_hash,
            )
        except (FileNotFoundError, OSError, sqlite3.Error, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return self._blocked(
                output=output,
                base_status=base_status,
                blockers=[f"paper_health_refresh_unavailable:{type(exc).__name__}"],
                warnings=[str(exc)],
                snapshot=None,
            )

    def _validate_output_dir(self, output: Path) -> None:
        if output in {self.state_db_path, self.status_path}:
            raise ValueError("health output overlaps a Paper source file")

    def _read_snapshot(self, as_of_date: date) -> _PaperSnapshot:
        manager = ReadOnlySQLiteManager(self.state_db_path)
        with manager.connect() as connection:
            connection.execute("BEGIN")
            state_columns = _table_columns(connection, "paper_portfolio_snapshots")
            position_columns = _table_columns(connection, "paper_portfolio_positions")
            if not _REQUIRED_STATE_COLUMNS.issubset(state_columns):
                raise ValueError("paper_snapshot_schema_missing")
            if not _REQUIRED_POSITION_COLUMNS.issubset(position_columns):
                raise ValueError("paper_position_schema_missing")
            rows = connection.execute(
                """
                SELECT snapshot_id, portfolio_id, decision_date, source_result_id
                FROM paper_portfolio_snapshots
                WHERE portfolio_id = ?
                ORDER BY decision_date, snapshot_id
                """,
                (self.portfolio_id,),
            ).fetchall()
            eligible = []
            for row in rows:
                row_date = _parse_date(row["decision_date"], "paper snapshot decision_date")
                if row_date <= as_of_date:
                    eligible.append((row, row_date))
            if not eligible:
                raise ValueError("paper_snapshot_as_of_missing")
            row, selected_date = eligible[-1]
            snapshot_id = str(row["snapshot_id"] or "").strip()
            if not snapshot_id:
                raise ValueError("paper_snapshot_id_missing")
            positions_rows = connection.execute(
                """
                SELECT stock_code, quantity, weight_bp
                FROM paper_portfolio_positions
                WHERE snapshot_id = ?
                ORDER BY stock_code
                """,
                (snapshot_id,),
            ).fetchall()
            positions: list[dict[str, Any]] = []
            for item in positions_rows:
                code = str(item["stock_code"] or "").strip()
                if not code:
                    raise ValueError("paper_position_stock_code_missing")
                quantity = _non_negative_int(item["quantity"], "paper position quantity")
                if quantity <= 0:
                    continue
                positions.append(
                    {
                        "stock_code": code,
                        "executable_shares": quantity,
                        "constrained_weight_bp": _non_negative_int(
                            item["weight_bp"], "paper position weight_bp"
                        ),
                    }
                )
            if not positions:
                raise ValueError("paper_snapshot_positions_missing")
            canonical = {
                "snapshot_id": snapshot_id,
                "portfolio_id": str(row["portfolio_id"] or ""),
                "decision_date": selected_date.isoformat(),
                "source_result_id": str(row["source_result_id"] or ""),
                "positions": positions,
            }
            data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
            return _PaperSnapshot(
                snapshot_id=snapshot_id,
                portfolio_id=str(row["portfolio_id"] or ""),
                decision_date=selected_date,
                source_result_id=str(row["source_result_id"] or ""),
                positions=tuple(positions),
                rows_sha256=_canonical_sha256(canonical),
                data_version=data_version,
            )

    def _validate_status(
        self,
        payload: Mapping[str, Any],
        *,
        as_of_date: date,
        snapshot: _PaperSnapshot,
    ) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        # The status hash is provenance stored in the receipt/baseline.  It is
        # not a quality warning; treating every hash as a warning would keep
        # a freshly refreshed health source degraded forever.
        warnings: list[str] = []
        if payload.get("schema_version") != "paper-portfolio-daily-status.v1":
            blockers.append("paper_daily_status_schema_mismatch")
        status = str(payload.get("status") or "unknown")
        if status not in {"passed", "skipped_non_trading_day"}:
            blockers.append(f"paper_daily_status_{status}")
        for field in ("writes_market_db", "auto_rebalance_allowed", "changes_advice", "broker_execution"):
            if payload.get(field) is not False:
                blockers.append(f"paper_daily_status_boundary_violation:{field}")
        try:
            status_date = _parse_date(payload.get("decision_date"), "paper status decision_date")
        except ValueError:
            blockers.append("paper_daily_status_date_invalid")
            return blockers, warnings
        if status_date > as_of_date:
            blockers.append("paper_daily_status_future_dated")
        if status == "passed":
            if str(payload.get("snapshot_id") or "") != snapshot.snapshot_id:
                blockers.append("paper_daily_status_snapshot_mismatch")
            if status_date != snapshot.decision_date:
                blockers.append("paper_daily_status_date_mismatch")
        else:
            warnings.append("paper_daily_status_non_trading_day")
        if status_date < as_of_date:
            warnings.append(f"paper_daily_status_as_of_fallback:{status_date.isoformat()}")
        return blockers, warnings

    def _read_previous_baseline(
        self,
        path: str | Path | None,
        *,
        snapshot_date: date,
    ) -> tuple[
        dict[str, Mapping[str, Any]],
        str | None,
        list[str],
        str | None,
        date | None,
    ]:
        if path is None:
            return {}, None, [], None, None
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            return {}, None, ["previous_health_baseline_missing"], None, None
        try:
            payload, digest = _read_json_with_hash(resolved)
            previous_date = _parse_date(payload.get("decision_date"), "previous health decision_date")
            if previous_date > snapshot_date:
                return {}, digest, ["previous_health_baseline_future_dated"], None, previous_date
            if payload.get("research_only") is not True or payload.get("auto_action_allowed") is not False:
                return {}, digest, ["previous_health_baseline_boundary_invalid"], None, previous_date
            raw_positions = payload.get("positions")
            if not isinstance(raw_positions, list):
                return {}, digest, ["previous_health_baseline_positions_invalid"], None, previous_date
            positions: dict[str, Mapping[str, Any]] = {}
            for item in raw_positions:
                if not isinstance(item, Mapping):
                    continue
                code = str(item.get("stock_code") or "").strip()
                if code and code not in positions:
                    positions[code] = item
            previous_snapshot_id = str(payload.get("source_snapshot_id") or "").strip() or None
            warnings: list[str] = []
            if previous_snapshot_id is None:
                warnings.append("previous_health_baseline_entry_lineage_missing")
            return positions, digest, warnings, previous_snapshot_id, previous_date
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return {}, None, [f"previous_health_baseline_unusable:{type(exc).__name__}"], None, None

    @staticmethod
    def _same_resolved_path(value: object, expected: Path) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        try:
            return Path(value).expanduser().resolve() == expected
        except (OSError, ValueError):
            return False

    def _read_coverage_receipt(
        self,
        *,
        previous_snapshot_id: str,
        previous_snapshot_date: date,
        snapshot: _PaperSnapshot,
    ) -> tuple[dict[str, Any], list[str]]:
        """Verify the controlled preopen receipt that covers this snapshot edge.

        A zero-row ledger query is not evidence of completeness by itself: a
        damaged or partially imported ledger also looks empty.  The isolated
        Paper preopen producer is the custody boundary that reads the ledger,
        applies any prior fills, and appends the next snapshot.  Only its
        immutable, path-bound status may authorize the absence check below.
        """

        metadata: dict[str, Any] = {
            "path": str(self.coverage_status_path),
            "status": "unavailable",
            "coverage_start_snapshot_id": previous_snapshot_id,
            "coverage_start_date": previous_snapshot_date.isoformat(),
            "coverage_end_snapshot_id": snapshot.snapshot_id,
            "coverage_end_date": snapshot.decision_date.isoformat(),
        }
        try:
            payload, digest = _read_json_with_hash(self.coverage_status_path)
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            metadata["error_type"] = type(exc).__name__
            return metadata, [f"paper_entry_lineage_coverage_unavailable:{type(exc).__name__}"]

        failures: list[str] = []
        if payload.get("schema_version") != "paper-portfolio-daily-status.v1":
            failures.append("schema_mismatch")
        if payload.get("producer") != "scripts.scheduled.run_paper_portfolio_daily_isolated":
            failures.append("producer_mismatch")
        if payload.get("status") != "passed":
            failures.append("status_not_passed")
        if payload.get("portfolio_id") != self.portfolio_id:
            failures.append("portfolio_mismatch")
        if not self._same_resolved_path(payload.get("state_db"), self.state_db_path):
            failures.append("state_db_path_mismatch")
        if not self._same_resolved_path(payload.get("paper_ledger_db"), self.ledger_db_path):
            failures.append("ledger_path_mismatch")
        if payload.get("snapshot_id") != snapshot.snapshot_id:
            failures.append("snapshot_id_mismatch")
        try:
            receipt_date = _parse_date(payload.get("decision_date"), "Paper coverage decision_date")
            if receipt_date != snapshot.decision_date:
                failures.append("snapshot_date_mismatch")
        except ValueError:
            failures.append("snapshot_date_invalid")
        if payload.get("snapshot_appended") is not True:
            failures.append("snapshot_append_not_verified")
        try:
            transitions = _non_negative_int(
                payload.get("paper_ledger_transitions_applied"),
                "Paper coverage ledger transitions",
            )
        except ValueError:
            failures.append("ledger_transition_count_invalid")
            transitions = None
        for field in ("writes_market_db", "auto_rebalance_allowed", "changes_advice", "broker_execution"):
            if payload.get(field) is not False:
                failures.append(f"boundary_violation:{field}")
        if payload.get("trading_calendar_validated") is not True:
            failures.append("trading_calendar_not_verified")

        after_payload = self.coverage_status_path.read_bytes()
        if digest != _sha256_bytes(after_payload):
            failures.append("coverage_receipt_changed_during_read")
        metadata.update(
            {
                "file_sha256": digest,
                "ledger_transitions_applied": transitions,
                "producer_version": payload.get("producer_version"),
            }
        )
        if failures:
            metadata["error_codes"] = failures
            return metadata, [
                "paper_entry_lineage_coverage_invalid:" + ",".join(failures)
            ]
        metadata["status"] = "ready"
        return metadata, []

    def _read_snapshot_endpoint_provenance(
        self,
        *,
        previous_snapshot_id: str,
        previous_snapshot_date: date,
        snapshot: _PaperSnapshot,
    ) -> tuple[dict[str, Any], list[str]]:
        """Bind both baseline endpoints to the same Paper state DB."""

        metadata: dict[str, Any] = {
            "path": str(self.state_db_path),
            "status": "unavailable",
            "previous_snapshot_id": previous_snapshot_id,
            "previous_snapshot_date": previous_snapshot_date.isoformat(),
            "current_snapshot_id": snapshot.snapshot_id,
            "current_snapshot_date": snapshot.decision_date.isoformat(),
        }
        before = _sha256_bytes(self.state_db_path.read_bytes())
        try:
            manager = ReadOnlySQLiteManager(self.state_db_path)
            with manager.connect() as connection:
                connection.execute("BEGIN")
                state_columns = _table_columns(connection, "paper_portfolio_snapshots")
                position_columns = _table_columns(connection, "paper_portfolio_positions")
                if not _REQUIRED_STATE_COLUMNS.issubset(state_columns):
                    raise ValueError("paper_snapshot_schema_missing")
                if not _REQUIRED_POSITION_COLUMNS.issubset(position_columns):
                    raise ValueError("paper_position_schema_missing")
                rows = connection.execute(
                    """
                    SELECT snapshot_id, portfolio_id, decision_date, source_result_id,
                           cash, total_value
                    FROM paper_portfolio_snapshots
                    WHERE portfolio_id = ? AND snapshot_id IN (?, ?)
                    ORDER BY decision_date, snapshot_id
                    """,
                    (self.portfolio_id, previous_snapshot_id, snapshot.snapshot_id),
                ).fetchall()
                by_id = {str(row["snapshot_id"]): row for row in rows}
                endpoints: dict[str, Any] = {}
                for endpoint_id, endpoint_date in (
                    (previous_snapshot_id, previous_snapshot_date),
                    (snapshot.snapshot_id, snapshot.decision_date),
                ):
                    row = by_id.get(endpoint_id)
                    if row is None:
                        raise ValueError(f"paper_snapshot_endpoint_missing:{endpoint_id}")
                    parsed_date = _parse_date(row["decision_date"], "Paper endpoint decision_date")
                    if parsed_date != endpoint_date:
                        raise ValueError(f"paper_snapshot_endpoint_date_mismatch:{endpoint_id}")
                    positions_rows = connection.execute(
                        """
                        SELECT stock_code, quantity, weight_bp
                        FROM paper_portfolio_positions
                        WHERE snapshot_id = ?
                        ORDER BY stock_code
                        """,
                        (endpoint_id,),
                    ).fetchall()
                    endpoint_positions: list[dict[str, Any]] = []
                    for item in positions_rows:
                        endpoint_positions.append(
                            {
                                "stock_code": str(item["stock_code"] or "").strip(),
                                "quantity": _non_negative_int(
                                    item["quantity"], "Paper endpoint quantity"
                                ),
                                "weight_bp": _non_negative_int(
                                    item["weight_bp"], "Paper endpoint weight_bp"
                                ),
                            }
                        )
                    endpoints[endpoint_id] = {
                        "portfolio_id": str(row["portfolio_id"] or ""),
                        "decision_date": parsed_date.isoformat(),
                        "source_result_id": str(row["source_result_id"] or ""),
                        "cash": str(row["cash"]),
                        "total_value": str(row["total_value"]),
                        "positions": endpoint_positions,
                    }
                data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
            after = _sha256_bytes(self.state_db_path.read_bytes())
            if before != after:
                raise ValueError("paper_snapshot_source_changed_during_read")
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as exc:
            metadata["error_type"] = type(exc).__name__
            return metadata, [f"paper_entry_lineage_snapshot_unavailable:{type(exc).__name__}"]

        metadata.update(
            {
                "status": "ready",
                "file_sha256": before,
                "data_version": data_version,
                "endpoints_sha256": {
                    endpoint_id: _canonical_sha256(endpoint)
                    for endpoint_id, endpoint in endpoints.items()
                },
            }
        )
        return metadata, []

    def _read_entry_ledger_window(
        self,
        *,
        start_date: date,
        end_date: date,
        stock_codes: Sequence[str],
        previous_snapshot_id: str,
        snapshot: _PaperSnapshot,
    ) -> tuple[dict[str, tuple[dict[str, Any], ...]], dict[str, Any], list[str]]:
        """Read the fill ledger needed to prove continuous entry lineage.

        The absence check is allowed only after a controlled preopen receipt
        binds both snapshot endpoints to this state/ledger pair.  A valid
        empty result then means no Paper event for the focused codes was
        observed in the covered interval.  Any missing or malformed custody
        keeps continuity unproven; it never grants inheritance by default.
        """

        metadata: dict[str, Any] = {
            "path": str(self.ledger_db_path),
            "read_mode": "sqlite_uri_mode_ro_and_query_only",
            "window_start_exclusive": start_date.isoformat(),
            "window_end_inclusive": end_date.isoformat(),
            "focused_stock_codes": sorted({str(code).strip() for code in stock_codes if str(code).strip()}),
            "coverage_status_path": str(self.coverage_status_path),
        }
        if start_date >= end_date:
            metadata["status"] = "not_needed"
            return {}, metadata, []
        if not previous_snapshot_id.strip():
            metadata["status"] = "unavailable"
            return {}, metadata, ["paper_entry_lineage_previous_snapshot_id_missing"]
        focused_codes = tuple(sorted({str(code).strip() for code in stock_codes if str(code).strip()}))
        if not focused_codes:
            metadata["status"] = "unavailable"
            return {}, metadata, ["paper_entry_lineage_focused_codes_missing"]
        coverage, coverage_warnings = self._read_coverage_receipt(
            previous_snapshot_id=previous_snapshot_id,
            previous_snapshot_date=start_date,
            snapshot=snapshot,
        )
        metadata["coverage_receipt"] = coverage
        if coverage.get("status") != "ready":
            return {}, metadata, coverage_warnings or ["paper_entry_lineage_coverage_unavailable"]
        endpoint, endpoint_warnings = self._read_snapshot_endpoint_provenance(
            previous_snapshot_id=previous_snapshot_id,
            previous_snapshot_date=start_date,
            snapshot=snapshot,
        )
        metadata["snapshot_provenance"] = endpoint
        if endpoint.get("status") != "ready":
            return {}, metadata, endpoint_warnings or ["paper_entry_lineage_snapshot_unavailable"]
        if not self.ledger_db_path.is_file():
            metadata["status"] = "unavailable"
            return {}, metadata, ["paper_entry_lineage_source_missing"]

        try:
            before = _sha256_bytes(self.ledger_db_path.read_bytes())
            manager = ReadOnlySQLiteManager(self.ledger_db_path)
            with manager.connect() as connection:
                connection.execute("BEGIN")
                columns = _table_columns(connection, "paper_trade_ledger")
                if not _REQUIRED_LEDGER_COLUMNS.issubset(columns):
                    raise ValueError("paper_entry_lineage_schema_missing")
                placeholders = ",".join("?" for _ in focused_codes)
                rows = connection.execute(
                    f"""
                    SELECT schema_version, fill_id, order_id, portfolio_id,
                           event_date, stock_code, side, requested_quantity,
                           filled_quantity, reference_price, fill_price,
                           commission, tax, slippage_cost, turnover_bp,
                           execution_gap_bp, status, source_event_id,
                           override_reason, source_type, research_only,
                           broker_order_allowed, auto_rebalance_allowed
                    FROM paper_trade_ledger
                    WHERE portfolio_id = ?
                      AND event_date > ?
                      AND event_date <= ?
                      AND stock_code IN ({placeholders})
                    ORDER BY event_date, stock_code, fill_id
                    """,
                    (
                        self.portfolio_id,
                        start_date.isoformat(),
                        end_date.isoformat(),
                        *focused_codes,
                    ),
                ).fetchall()
                by_code: dict[str, list[dict[str, Any]]] = {}
                canonical_rows: list[dict[str, Any]] = []
                for row in rows:
                    event_date = _parse_date(row["event_date"], "paper ledger event_date")
                    code = str(row["stock_code"] or "").strip()
                    if not code:
                        raise ValueError("paper_entry_lineage_stock_code_missing")
                    if str(row["side"] or "").strip() not in {"buy", "sell"}:
                        raise ValueError("paper_entry_lineage_side_invalid")
                    if str(row["status"] or "").strip() not in {
                        "filled",
                        "partially_filled",
                        "rejected",
                        "cancelled",
                    }:
                        raise ValueError("paper_entry_lineage_status_invalid")
                    if int(row["research_only"] or 0) != 1:
                        raise ValueError("paper_entry_lineage_research_boundary_invalid")
                    if int(row["broker_order_allowed"] or 0) != 0:
                        raise ValueError("paper_entry_lineage_broker_boundary_invalid")
                    if int(row["auto_rebalance_allowed"] or 0) != 0:
                        raise ValueError("paper_entry_lineage_rebalance_boundary_invalid")
                    canonical_row = {
                        column: row[column]
                        for column in (
                            "schema_version",
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
                            "override_reason",
                            "source_type",
                            "research_only",
                            "broker_order_allowed",
                            "auto_rebalance_allowed",
                        )
                    }
                    canonical_rows.append(canonical_row)
                    by_code.setdefault(code, []).append(
                        {
                            "fill_id": str(row["fill_id"]),
                            "event_date": event_date.isoformat(),
                            "side": str(row["side"]),
                            "status": str(row["status"]),
                            "filled_quantity": _non_negative_int(
                                row["filled_quantity"], "paper ledger filled_quantity"
                            ),
                        }
                    )
                data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
            after = _sha256_bytes(self.ledger_db_path.read_bytes())
            if before != after:
                raise ValueError("paper_entry_lineage_source_changed_during_read")
            metadata.update(
                {
                    "status": "ready",
                    "file_sha256": before,
                    "data_version": data_version,
                    "event_count": sum(len(items) for items in by_code.values()),
                    "rows_sha256": _canonical_sha256(canonical_rows),
                    "row_count": len(canonical_rows),
                }
            )
            return {code: tuple(items) for code, items in by_code.items()}, metadata, []
        except (FileNotFoundError, OSError, sqlite3.Error, ValueError) as exc:
            metadata.update(
                {
                    "status": "unavailable",
                    "error_type": type(exc).__name__,
                }
            )
            return {}, metadata, [f"paper_entry_lineage_source_unavailable:{type(exc).__name__}"]

    def _build_baseline(
        self,
        *,
        snapshot: _PaperSnapshot,
        previous: Mapping[str, Mapping[str, Any]],
        previous_hash: str | None,
        previous_snapshot_id: str | None,
        previous_snapshot_date: date | None,
        status_hash: str,
        as_of_date: date,
        warnings: list[str],
        identity_source: PositionIdentitySourceResult | None = None,
    ) -> dict[str, Any]:
        baseline = PositionHealthBaselineService().build_from_paper_snapshot(
            decision_date=snapshot.decision_date.isoformat(),
            source_result_id=snapshot.source_result_id or snapshot.snapshot_id,
            allocations=snapshot.positions,
            source_path=self.state_db_path,
        )
        identity_by_code = (
            {}
            if identity_source is None
            else {
                str(code): dict(identity)
                for code, identity in identity_source.identities.items()
            }
        )
        continuity_verified = previous_snapshot_id == snapshot.snapshot_id
        ledger_events: dict[str, tuple[dict[str, Any], ...]] = {}
        ledger_metadata: dict[str, Any] = {"status": "not_needed"}
        lineage_warnings: list[str] = []
        if previous and not continuity_verified:
            if previous_snapshot_id is None:
                lineage_warnings.append("paper_entry_lineage_previous_snapshot_id_missing")
            elif previous_snapshot_date is None:
                lineage_warnings.append("paper_entry_lineage_previous_snapshot_date_missing")
            else:
                ledger_events, ledger_metadata, lineage_warnings = self._read_entry_ledger_window(
                    start_date=previous_snapshot_date,
                    end_date=snapshot.decision_date,
                    stock_codes=tuple(
                        str(item.get("stock_code") or "").strip()
                        for item in baseline["positions"]
                        if isinstance(item, dict)
                    ),
                    previous_snapshot_id=previous_snapshot_id,
                    snapshot=snapshot,
                )
        continuity_codes: set[str] = set()
        if ledger_metadata.get("status") == "ready" and previous_snapshot_date is not None:
            for current in baseline["positions"]:
                if not isinstance(current, dict):
                    continue
                code = str(current.get("stock_code") or "").strip()
                prior = previous.get(code)
                if prior is None or ledger_events.get(code):
                    continue
                try:
                    prior_shares = _non_negative_int(
                        prior.get("paper_shares"), "previous paper shares"
                    )
                    current_shares = _non_negative_int(
                        current.get("paper_shares"), "current paper shares"
                    )
                except ValueError:
                    continue
                if prior_shares == current_shares and current_shares > 0:
                    continuity_codes.add(code)
        positions: list[dict[str, Any]] = []
        historical_prior_codes: list[str] = []
        closed_prior_codes: list[str] = []
        for item in baseline["positions"]:
            if not isinstance(item, dict):
                continue
            code = str(item.get("stock_code") or "").strip()
            prior_record = previous.get(code)
            is_continuous = continuity_verified or code in continuity_codes
            prior = prior_record if is_continuous else None
            item = dict(item)
            prior_reasons = _string_list(
                None if prior_record is None else prior_record.get("reasons")
            )
            if prior_record is not None:
                # Preserve prior human input and diagnostic context in the
                # derived history even when the current projection cannot
                # safely inherit it.
                item["historical_prior_state"] = str(
                    prior_record.get("state") or "unknown"
                )
                item["historical_prior_reasons"] = prior_reasons
                item["historical_prior_source_snapshot_id"] = previous_snapshot_id
                item["historical_prior_health_fields"] = {
                    field: prior_record.get(field) for field in _HEALTH_FIELDS
                }
            if prior is not None:
                prior_name = str(prior.get("stock_name") or "").strip()
                if prior_name:
                    item["stock_name"] = prior_name
                for field in _HEALTH_FIELDS:
                    if field in prior and not _is_missing(prior.get(field)):
                        item[field] = prior[field]
                prior_state = str(prior.get("state") or "").strip().upper()
                if prior_state in _HEALTH_STATES and prior_state not in {"HEALTHY", "CLOSED"}:
                    item["state"] = prior_state
                if prior_state == "CLOSED":
                    closed_prior_codes.append(code)
                    historical_prior_codes.append(code)
                    item["state_projection_blocked"] = "closed_state_with_active_quantity"
                    item["entry_lineage_status"] = "closed_prior_not_projected"
                    # A live quantity cannot be labelled CLOSED merely because
                    # the prior baseline used that state.  Do not copy its
                    # thesis into the active projection either.
                    for field in _HEALTH_FIELDS:
                        item[field] = None
                    prior = None
            elif prior_record is not None:
                historical_prior_codes.append(code)
            required = [field for field in _HEALTH_FIELDS if _is_missing(item.get(field))]
            reasons = [f"missing_{field}" for field in required]
            reasons.append("health_transition_not_evaluated")
            if prior is not None and prior_reasons:
                # A carried state must retain the prior trigger context; the
                # daily producer may append diagnostics but must not erase an
                # earlier EXIT/WATCH reason when rebuilding the list.
                reasons = list(dict.fromkeys(prior_reasons + reasons))
            item["required_human_fields"] = required
            item["reasons"] = reasons
            item["source_trace"] = [
                f"paper_snapshot:{snapshot.snapshot_id}",
                f"paper_health_refresh:{as_of_date.isoformat()}",
            ]
            identity = identity_by_code.get(code)
            if identity is not None:
                item["position_id"] = identity.get("position_id")
                item["entry_lineage_id"] = identity.get("entry_lineage_id")
                item["position_identity_source"] = identity
                item["source_trace"].append(
                    f"paper_position_identity:{identity.get('status', 'verified')}"
                )
            elif identity_source is not None:
                # Keep an explicit null identity in the baseline so a
                # downstream evaluator cannot accidentally fall back to the
                # stock code as a lineage key.
                item["position_id"] = None
                item["entry_lineage_id"] = None
                item["position_identity_source"] = {
                    "status": "unproven",
                    "stock_code": code,
                }
            item["entry_lineage_status"] = (
                "same_snapshot_verified"
                if continuity_verified and prior is not None
                else "ledger_continuous_no_trade"
                if code in continuity_codes and prior is not None
                else item.get("entry_lineage_status", "unproven")
            )
            if identity is not None:
                item["entry_lineage_status"] = str(
                    identity.get("status") or item["entry_lineage_status"]
                )
            elif identity_source is not None and item.get("entry_lineage_status") not in {
                "closed_prior_not_projected",
            }:
                # Snapshot continuity can justify carrying historical fields,
                # but it cannot turn a stock-code-only row into a stable
                # position identity.  Keep the current lineage explicitly
                # unproven when the identity provider has no evidence.
                item["entry_lineage_status"] = "unproven"
            item["auto_action_allowed"] = False
            positions.append(item)
        verified_statuses = {
            "same_snapshot_verified",
            "ledger_continuous_no_trade",
            "natural_entry_verified",
            "carried_verified",
        }
        unproven_codes = sorted(
            str(item.get("stock_code") or "")
            for item in positions
            if item.get("entry_lineage_status") == "unproven"
        )
        prior_unproven_codes = sorted(
            str(item.get("stock_code") or "")
            for item in positions
            if str(item.get("stock_code") or "") in previous
            and item.get("entry_lineage_status") not in verified_statuses
        )
        lineage_warning: list[str] = []
        if previous and not continuity_verified and prior_unproven_codes:
            lineage_warning.append("paper_position_entry_lineage_not_verified")
        if closed_prior_codes:
            lineage_warning.append("paper_position_prior_closed_not_projected")
        lineage_warning.extend(lineage_warnings)
        baseline.update(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "fresh",
                "as_of_date": as_of_date.isoformat(),
                "source_path": str(self.state_db_path),
                "source_type": "paper_snapshot_read_only",
                "source_snapshot_id": snapshot.snapshot_id,
                "source_snapshot_date": snapshot.decision_date.isoformat(),
                "source_snapshot_rows_sha256": snapshot.rows_sha256,
                "source_data_version": snapshot.data_version,
                "paper_status_path": str(self.status_path),
                "paper_status_sha256": status_hash,
                "previous_health_baseline_sha256": previous_hash,
                "previous_source_snapshot_id": previous_snapshot_id,
                "previous_source_snapshot_date": (
                    None if previous_snapshot_date is None else previous_snapshot_date.isoformat()
                ),
                "entry_lineage_policy": (
                    "preserve_human_fields_only_when_same_snapshot_or_verified_ledger_continuity"
                ),
                "entry_lineage_verified": bool(continuity_verified or continuity_codes),
                "entry_lineage_verified_codes": sorted(continuity_codes),
                "entry_lineage_unproven_codes": unproven_codes,
                "entry_lineage_historical_prior_codes": sorted(historical_prior_codes),
                "entry_lineage_closed_prior_codes": sorted(closed_prior_codes),
                "entry_lineage_source": ledger_metadata,
                "position_identity_source": (
                    None
                    if identity_source is None
                    else dict(identity_source.provenance)
                ),
                "position_identity_verified_codes": (
                    []
                    if identity_source is None
                    else sorted(identity_by_code)
                ),
                "source_read_mode": "sqlite_uri_mode_ro_and_query_only",
                "research_only": True,
                "writes_positions_db": False,
                "auto_action_allowed": False,
                "broker_execution": False,
                "formal_credit": False,
                "positions": positions,
                "warnings": list(
                    dict.fromkeys(
                        [
                            str(item) for item in baseline.get("warnings", [])
                        ]
                        + list(warnings)
                        + lineage_warning
                        + ["position_health_daily_refresh_does_not_evaluate_transition"]
                    )
                ),
                "diagnostics": [
                    *list(baseline.get("diagnostics", [])),
                    "paper_snapshot_rows_read_in_one_transaction",
                    "health_transition_requires_human_thesis_and_current_condition_source",
                ],
            }
        )
        return baseline

    def _persist(
        self,
        *,
        output: Path,
        baseline: dict[str, Any],
        snapshot: _PaperSnapshot,
        observed_at: datetime,
        warnings: list[str],
        status_hash: str,
    ) -> dict[str, Any]:
        output.mkdir(parents=True, exist_ok=True)
        encoded = _canonical_json(baseline).encode("utf-8")
        dated = output / f"baseline_{snapshot.decision_date.strftime('%Y%m%d')}.json"
        result_status = "passed"
        if dated.exists():
            if dated.read_bytes() == encoded:
                result_status = "reused"
            else:
                suffix = hashlib.sha256(encoded).hexdigest()[:16]
                dated = output / f"baseline_{snapshot.decision_date.strftime('%Y%m%d')}_{suffix}.json"
                if dated.exists() and dated.read_bytes() != encoded:
                    raise ValueError("health baseline immutable filename collision")
        if not dated.exists():
            dated.write_bytes(encoded)
        latest = output / "latest.json"
        _atomic_write_json(latest, baseline)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "producer": "app_module.position_health_daily_refresh_service",
            "status": result_status,
            "observed_at": observed_at.isoformat(),
            "as_of_date": baseline["as_of_date"],
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_date": snapshot.decision_date.isoformat(),
            "snapshot_rows_sha256": snapshot.rows_sha256,
            "paper_status_sha256": status_hash,
            "baseline_path": str(dated),
            "latest_path": str(latest),
            "baseline_sha256": _sha256_bytes(encoded),
            "warnings": list(dict.fromkeys(warnings)),
            "blockers": [],
            "research_only": True,
            "writes_positions_db": False,
            "writes_paper_state": False,
            "auto_action_allowed": False,
            "broker_execution": False,
            "formal_credit": False,
        }
        _atomic_write_json(output / "latest_status.json", receipt)
        return receipt

    def _blocked(
        self,
        *,
        output: Path,
        base_status: Mapping[str, Any],
        blockers: list[str],
        warnings: list[str],
        snapshot: _PaperSnapshot | None,
    ) -> dict[str, Any]:
        receipt = dict(base_status)
        receipt.update(
            {
                "status": "blocked",
                "blockers": list(dict.fromkeys(blockers)),
                "warnings": list(dict.fromkeys(warnings)),
                "snapshot_id": None if snapshot is None else snapshot.snapshot_id,
                "snapshot_date": None if snapshot is None else snapshot.decision_date.isoformat(),
                "baseline_path": None,
                "latest_path": str(output / "latest.json"),
            }
        )
        try:
            self._validate_output_dir(output)
            _atomic_write_json(output / "latest_status.json", receipt)
        except (OSError, ValueError):
            # The source failure is still returned to the scheduled caller;
            # never turn an unsafe output path into a write elsewhere.
            pass
        return receipt
