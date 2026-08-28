from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Any

from app_module.decision_desk_snapshot_storage_dtos import section_is_ready
from app_module.evidence_pipeline_runner_dtos import (
    READINESS_DRY_RUN_ONLY,
    READINESS_NOT_READY,
    READINESS_READY_FOR_DESIGN,
)
from app_module.paper_portfolio_time import taiwan_market_today
from data_module.config import TWStockConfig
from data_module.data_source_capability_registry import build_default_data_source_capability_registry


@dataclass(frozen=True)
class EvidenceSourceCoverageInspection:
    recommendation_persisted_available: bool
    recommendation_exclusion_payload_available: bool
    recommendation_screening_matrix_available: bool
    decision_desk_snapshots_count: int
    latest_decision_desk_snapshot_date: str | None
    watchlist_trigger_capture_ready: bool
    portfolio_alert_capture_ready: bool
    risk_prompt_capture_ready: bool
    why_not_capture_ready: bool
    liquidity_gate_capture_ready: bool
    screening_matrix_capture_ready: bool
    scheduler_readiness: str
    blocking_gaps: tuple[str, ...]
    warnings: tuple[str, ...]
    source_capability_status: dict[str, str]
    source_capabilities: dict[str, dict[str, Any]]
    future_decision_desk_snapshot_dates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_persisted_available": self.recommendation_persisted_available,
            "recommendation_exclusion_payload_available": self.recommendation_exclusion_payload_available,
            "recommendation_screening_matrix_available": self.recommendation_screening_matrix_available,
            "decision_desk_snapshots_count": self.decision_desk_snapshots_count,
            "latest_decision_desk_snapshot_date": self.latest_decision_desk_snapshot_date,
            "watchlist_trigger_capture_ready": self.watchlist_trigger_capture_ready,
            "portfolio_alert_capture_ready": self.portfolio_alert_capture_ready,
            "risk_prompt_capture_ready": self.risk_prompt_capture_ready,
            "why_not_capture_ready": self.why_not_capture_ready,
            "liquidity_gate_capture_ready": self.liquidity_gate_capture_ready,
            "screening_matrix_capture_ready": self.screening_matrix_capture_ready,
            "scheduler_readiness": self.scheduler_readiness,
            "blocking_gaps": list(self.blocking_gaps),
            "warnings": list(self.warnings),
            "source_capability_status": dict(self.source_capability_status),
            "source_capabilities": {
                source_id: dict(payload) for source_id, payload in self.source_capabilities.items()
            },
            "future_decision_desk_snapshot_dates": list(self.future_decision_desk_snapshot_dates),
        }


class EvidenceSourceCoverageService:
    """Read-only evidence source coverage inspection for V1.5 source gates."""

    def __init__(self, config: TWStockConfig, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)

    def inspect(
        self,
        *,
        decision_date: str | None = None,
        result_id: str | None = None,
    ) -> EvidenceSourceCoverageInspection:
        today = taiwan_market_today()
        cutoff_date, requested_future_date = _bounded_decision_date(decision_date, today)
        recommendation = self._latest_recommendation(result_id)
        snapshots = _list_snapshots_read_only(self.db_path)
        active_snapshots = [item for item in snapshots if item.get("snapshot_status") == "active"]
        future_snapshot_dates = tuple(
            sorted(
                {
                    str(item["decision_date"])
                    for item in active_snapshots
                    if _is_future_date_text(str(item.get("decision_date") or ""), today)
                }
            )
        )
        latest_candidates = [
            item
            for item in active_snapshots
            if str(item.get("decision_date") or "") <= cutoff_date
        ]
        latest_snapshot = latest_candidates[0] if latest_candidates else None

        recommendation_available = recommendation is not None
        why_not_ready = _has_payload(recommendation.get("why_not_payload_json")) if recommendation else False
        liquidity_ready = (
            _has_payload(recommendation.get("liquidity_gate_payload_json")) if recommendation else False
        )
        screening_matrix_ready = (
            _has_payload(recommendation.get("screening_matrix_json")) if recommendation else False
        )
        watchlist_ready = latest_snapshot is not None and section_is_ready(
            latest_snapshot.get("watchlist_trigger_json", {})
        )
        portfolio_ready = latest_snapshot is not None and section_is_ready(
            latest_snapshot.get("portfolio_alert_json", {})
        )
        risk_ready = latest_snapshot is not None and section_is_ready(
            latest_snapshot.get("risk_prompt_json", {})
        )
        blocking_gaps = self._blocking_gaps(
            recommendation_available=recommendation_available,
            latest_snapshot_available=latest_snapshot is not None,
            watchlist_ready=watchlist_ready,
            portfolio_ready=portfolio_ready,
            risk_ready=risk_ready,
            future_snapshot_dates=future_snapshot_dates,
            requested_future_date=requested_future_date,
        )
        warnings = self._warnings(
            why_not_ready=why_not_ready,
            liquidity_ready=liquidity_ready,
            screening_matrix_ready=screening_matrix_ready,
        )
        snapshot_ready = latest_snapshot is not None and watchlist_ready and portfolio_ready and risk_ready
        if not recommendation_available or not snapshot_ready or blocking_gaps:
            readiness = READINESS_NOT_READY
        elif warnings:
            readiness = READINESS_DRY_RUN_ONLY
        else:
            readiness = READINESS_READY_FOR_DESIGN

        source_capabilities = _source_capabilities()
        return EvidenceSourceCoverageInspection(
            recommendation_persisted_available=recommendation_available,
            recommendation_exclusion_payload_available=why_not_ready and liquidity_ready,
            recommendation_screening_matrix_available=screening_matrix_ready,
            decision_desk_snapshots_count=len(snapshots),
            latest_decision_desk_snapshot_date=(
                str(latest_snapshot["decision_date"]) if latest_snapshot is not None else None
            ),
            watchlist_trigger_capture_ready=watchlist_ready,
            portfolio_alert_capture_ready=portfolio_ready,
            risk_prompt_capture_ready=risk_ready,
            why_not_capture_ready=why_not_ready,
            liquidity_gate_capture_ready=liquidity_ready,
            screening_matrix_capture_ready=screening_matrix_ready,
            scheduler_readiness=readiness,
            blocking_gaps=tuple(blocking_gaps),
            warnings=tuple(warnings),
            source_capability_status={
                source_id: str(payload.get("status") or "unknown")
                for source_id, payload in source_capabilities.items()
            },
            source_capabilities=source_capabilities,
            future_decision_desk_snapshot_dates=future_snapshot_dates,
        )

    def _latest_recommendation(self, result_id: str | None) -> dict[str, Any] | None:
        return _latest_recommendation_read_only(self.config, result_id)

    def _blocking_gaps(
        self,
        *,
        recommendation_available: bool,
        latest_snapshot_available: bool,
        watchlist_ready: bool,
        portfolio_ready: bool,
        risk_ready: bool,
        future_snapshot_dates: tuple[str, ...],
        requested_future_date: date | None,
    ) -> list[str]:
        gaps: list[str] = []
        if not recommendation_available:
            gaps.append("recommendation_persisted_missing")
        if not latest_snapshot_available:
            gaps.append("decision_desk_snapshot_missing")
        if latest_snapshot_available and not watchlist_ready:
            gaps.append("watchlist_trigger_snapshot_section_missing")
        if latest_snapshot_available and not portfolio_ready:
            gaps.append("portfolio_alert_snapshot_section_missing")
        if latest_snapshot_available and not risk_ready:
            gaps.append("risk_prompt_snapshot_section_missing")
        if future_snapshot_dates:
            gaps.append("decision_desk_snapshot_future_dated")
        if requested_future_date is not None:
            gaps.append("decision_desk_snapshot_request_future_dated")
        return gaps

    def _warnings(
        self,
        *,
        why_not_ready: bool,
        liquidity_ready: bool,
        screening_matrix_ready: bool,
    ) -> list[str]:
        warnings: list[str] = []
        if not why_not_ready:
            warnings.append("why_not_payload_missing")
        if not liquidity_ready:
            warnings.append("liquidity_gate_payload_missing")
        if not screening_matrix_ready:
            warnings.append("screening_matrix_missing")
        return warnings


def _source_capabilities() -> dict[str, dict[str, Any]]:
    registry = build_default_data_source_capability_registry()
    source_ids = (
        "recommendation.persisted_result",
        "recommendation.screening_matrix",
        "recommendation.exclusion.why_not_payload",
        "recommendation.exclusion.liquidity_gate_payload",
        "decision_desk.snapshot.watchlist_trigger",
        "decision_desk.snapshot.portfolio_alert",
        "decision_desk.snapshot.risk_prompt",
    )
    return {source_id: registry.require(source_id).to_dict() for source_id in source_ids}


def _has_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    try:
        return bool(list(value))
    except TypeError:
        return bool(value)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(str(path))
    uri_path = path.resolve().as_posix()
    conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _latest_recommendation_read_only(
    config: TWStockConfig,
    result_id: str | None,
) -> dict[str, Any] | None:
    runs_dir = Path(config.output_root) / "recommendation" / "runs"
    db_path = runs_dir / "recommendation_runs.db"
    try:
        with _connect_read_only(db_path) as conn:
            if not _table_exists(conn, "runs"):
                return None
            if result_id:
                row = conn.execute(
                    "SELECT data_path FROM runs WHERE result_id = ? LIMIT 1",
                    (str(result_id),),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT data_path
                    FROM runs
                    ORDER BY created_at DESC, result_id ASC
                    LIMIT 1
                    """
                ).fetchone()
    except (FileNotFoundError, sqlite3.Error):
        return None
    if row is None:
        return None
    data_path = Path(str(row["data_path"] or ""))
    if not data_path.is_absolute():
        data_path = runs_dir / data_path
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _list_snapshots_read_only(db_path: Path) -> list[dict[str, Any]]:
    try:
        with _connect_read_only(db_path) as conn:
            if not _table_exists(conn, "decision_desk_snapshots"):
                return []
            rows = conn.execute(
                """
                SELECT *
                FROM decision_desk_snapshots
                ORDER BY decision_date DESC, created_at DESC
                """
            ).fetchall()
    except (FileNotFoundError, sqlite3.Error):
        return []
    payloads: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        for column in (
            "watchlist_trigger_json",
            "portfolio_alert_json",
            "risk_prompt_json",
        ):
            payload[column] = _json_object(payload.get(column))
        payloads.append(payload)
    return payloads


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bounded_decision_date(
    decision_date: str | None,
    today: date,
) -> tuple[str, date | None]:
    if not decision_date:
        return today.isoformat(), None
    text = str(decision_date).strip()[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return text, None
    if parsed > today:
        return today.isoformat(), parsed
    return parsed.isoformat(), None


def _is_future_date_text(value: str, today: date) -> bool:
    text = str(value or "").strip()[:10]
    if not text:
        return False
    try:
        return date.fromisoformat(text) > today
    except ValueError:
        return False
