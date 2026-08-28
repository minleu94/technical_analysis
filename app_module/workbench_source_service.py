from __future__ import annotations

from datetime import date
from pathlib import Path
import json
import os
import sqlite3
from typing import Any

from app_module.decision_desk_dtos import DecisionDeskSnapshot
from app_module.decision_desk_snapshot_storage_dtos import StoredDecisionDeskSnapshot
from app_module.pre_v2_readiness_service import (
    DEFAULT_MIN_DRY_RUN_DAYS,
    DEFAULT_MIN_WEEKLY_HISTORY_RECORDS,
    PreV2ReadinessService,
)
from app_module.workbench_dtos import WorkbenchDashboardDTO
from app_module.workbench_read_only_composer import WorkbenchReadOnlyComposer
from app_module.workbench_replay_summary import load_historical_replay_summary
from app_module.scheduled_evidence_status_service import ScheduledEvidenceStatusService
from app_module.paper_portfolio_time import taiwan_market_today


class WorkbenchSourceService:
    """Read-only source adapter for the V2.0 Workbench prototype."""

    def __init__(
        self,
        config: Any,
        *,
        evidence_db_path: str | Path | None = None,
        research_db_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.evidence_db_path = Path(evidence_db_path) if evidence_db_path is not None else Path(config.db_file)
        self.research_db_path = (
            Path(research_db_path) if research_db_path is not None else Path(config.research_run_db_file)
        )
        self.readiness_service = PreV2ReadinessService(
            config,
            evidence_db_path=self.evidence_db_path,
            research_db_path=self.research_db_path,
            approved_weekly_history_projection_path=os.environ.get("WEEKLY_EVIDENCE_HISTORY_PROJECTION_PATH"),
        )
        self.composer = WorkbenchReadOnlyComposer()
        self.scheduled_status_service = ScheduledEvidenceStatusService(config)

    def inspect(
        self,
        *,
        decision_date: str | None = None,
        multi_day_record_path: str | Path | None = None,
        min_weekly_records: int = DEFAULT_MIN_WEEKLY_HISTORY_RECORDS,
        min_dry_run_days: int = DEFAULT_MIN_DRY_RUN_DAYS,
        agent_report_limit: int = 5,
        replay_summary_json: str | Path | None = None,
    ) -> WorkbenchDashboardDTO:
        decision_snapshot, source_diagnostics = self._load_decision_snapshot(decision_date)
        readiness_report = self.readiness_service.inspect(
            decision_date=decision_date,
            multi_day_record_path=multi_day_record_path,
            min_weekly_records=min_weekly_records,
            min_dry_run_days=min_dry_run_days,
            agent_report_limit=agent_report_limit,
        )
        agent_report_sample = self.readiness_service.build_agent_report_sample(limit=agent_report_limit)
        historical_replay_summary = (
            load_historical_replay_summary(replay_summary_json) if replay_summary_json is not None else None
        )
        scheduled_status = self.scheduled_status_service.load_latest()
        source_mode = "read_only_sources_plus_historical_replay" if historical_replay_summary else "read_only_sources"
        return self.composer.compose(
            decision_snapshot=decision_snapshot,
            readiness_report=readiness_report,
            agent_report_sample=agent_report_sample,
            scheduled_status=scheduled_status,
            historical_replay_summary=historical_replay_summary,
            source_mode=source_mode,
            source_diagnostics=tuple(source_diagnostics),
        )

    def _load_decision_snapshot(self, decision_date: str | None) -> tuple[DecisionDeskSnapshot | None, list[str]]:
        diagnostics: list[str] = []
        today = taiwan_market_today()
        cutoff_date, requested_future_date = _bounded_decision_date(decision_date, today)
        try:
            with _connect_read_only(self.evidence_db_path) as conn:
                if not _table_exists(conn, "decision_desk_snapshots"):
                    diagnostics.append("decision_desk_snapshots_table_missing")
                    return None, diagnostics
                future_rows = conn.execute(
                    """
                    SELECT DISTINCT decision_date
                    FROM decision_desk_snapshots
                    WHERE snapshot_status = 'active' AND decision_date > ?
                    ORDER BY decision_date ASC
                    """,
                    (today.isoformat(),),
                ).fetchall()
                future_dates = tuple(str(item["decision_date"]) for item in future_rows)
                if requested_future_date is not None:
                    diagnostics.append(
                        "decision_desk_snapshot_request_future_date:"
                        f"{requested_future_date.isoformat()}:today={today.isoformat()}"
                    )
                diagnostics.extend(
                    "decision_desk_snapshot_future_date:"
                    f"{item}:today={today.isoformat()}"
                    for item in future_dates
                )
                row = conn.execute(
                    """
                    SELECT *
                    FROM decision_desk_snapshots
                    WHERE decision_date <= ? AND snapshot_status = 'active'
                    ORDER BY decision_date DESC, created_at DESC
                    LIMIT 1
                    """,
                    (cutoff_date,),
                ).fetchone()
        except FileNotFoundError as exc:
            diagnostics.append(f"decision_desk_snapshot_db_missing:{exc}")
            return None, diagnostics
        except sqlite3.Error as exc:
            diagnostics.append(f"decision_desk_snapshot_unavailable:{exc}")
            return None, diagnostics

        if row is None:
            diagnostics.append("decision_desk_snapshot_missing")
            return None, diagnostics
        try:
            return _row_to_stored_snapshot(dict(row)).to_decision_desk_snapshot(), diagnostics
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            diagnostics.append(f"decision_desk_snapshot_degraded:{exc}")
            return None, diagnostics


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


def _row_to_stored_snapshot(row: dict[str, Any]) -> StoredDecisionDeskSnapshot:
    return StoredDecisionDeskSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        snapshot_hash=str(row["snapshot_hash"]),
        decision_date=str(row["decision_date"]),
        as_of_date=str(row["as_of_date"]),
        source_version=str(row["source_version"]),
        builder_version=str(row["builder_version"]),
        data_quality=str(row["data_quality"]),
        warnings_json=_json_value(row["warnings_json"], []),
        market_regime_json=_json_value(row["market_regime_json"], {}),
        market_breadth_json=_json_value(row["market_breadth_json"], {}),
        sector_rotation_json=_json_value(row["sector_rotation_json"], {}),
        relative_strength_liquidity_json=_json_value(row["relative_strength_liquidity_json"], {}),
        watchlist_trigger_json=_json_value(row["watchlist_trigger_json"], {}),
        portfolio_alert_json=_json_value(row["portfolio_alert_json"], {}),
        risk_prompt_json=_json_value(row["risk_prompt_json"], {}),
        fundamental_diagnostics_json=_json_value(row["fundamental_diagnostics_json"], {}),
        metadata_json=_json_value(row["metadata_json"], {}),
        snapshot_status=str(row["snapshot_status"]),
        created_at=str(row["created_at"]),
    )


def _json_value(raw: Any, fallback: Any) -> Any:
    if raw is None:
        return fallback
    return json.loads(str(raw))


def _bounded_decision_date(
    decision_date: str | None,
    today: date,
) -> tuple[str, date | None]:
    """把 Workbench 的 current 查詢上限限制在台灣市場今天。"""

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
