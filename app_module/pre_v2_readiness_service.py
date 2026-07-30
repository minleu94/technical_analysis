from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import re
import sqlite3
from typing import Any

from app_module.agent_evidence_access_service import (
    AgentEvidenceAccessService,
    build_ai_report_template,
)
from app_module.decision_desk_snapshot_storage_dtos import section_is_ready
from app_module.approved_weekly_history_projection import load_approved_weekly_history_projection


STATUS_READY = "ready"
STATUS_ACTION_REQUIRED = "action_required"
STATUS_WAITING_FOR_TIME = "waiting_for_time"

DEFAULT_MIN_WEEKLY_HISTORY_RECORDS = 3
DEFAULT_MIN_DRY_RUN_DAYS = 3


@dataclass(frozen=True)
class PreV2ReadinessItem:
    item_id: str
    label: str
    status: str
    required_count: int | None = None
    observed_count: int | None = None
    blocking_reasons: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "status": self.status,
            "required_count": self.required_count,
            "observed_count": self.observed_count,
            "blocking_reasons": list(self.blocking_reasons),
            "next_actions": list(self.next_actions),
            "evidence": dict(self.evidence),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class PreV2ReadinessReport:
    generated_at: str
    overall_status: str
    production_scheduler_allowed: bool
    items: tuple[PreV2ReadinessItem, ...]
    limitations: tuple[str, ...]
    rule_operational_scheduler_allowed: bool = True
    required_human_action: bool = False
    automatic_revalidation_enabled: bool = True
    blocking_scope: str = "formal_evidence_credit_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "overall_status": self.overall_status,
            "production_scheduler_allowed": self.production_scheduler_allowed,
            "rule_operational_scheduler_allowed": self.rule_operational_scheduler_allowed,
            "required_human_action": self.required_human_action,
            "automatic_revalidation_enabled": self.automatic_revalidation_enabled,
            "blocking_scope": self.blocking_scope,
            "items": [item.to_dict() for item in self.items],
            "limitations": list(self.limitations),
        }


class PreV2ReadinessService:
    """Read-only readiness inspector for non-scheduler V2.0 prerequisites."""

    def __init__(
        self,
        config: Any,
        *,
        evidence_db_path: str | Path | None = None,
        research_db_path: str | Path | None = None,
        approved_weekly_history_projection_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.evidence_db_path = Path(evidence_db_path) if evidence_db_path is not None else Path(config.db_file)
        self.research_db_path = (
            Path(research_db_path) if research_db_path is not None else Path(config.research_run_db_file)
        )
        self.approved_weekly_history_projection_path = approved_weekly_history_projection_path

    def inspect(
        self,
        *,
        decision_date: str | None = None,
        multi_day_record_path: str | Path | None = None,
        min_weekly_records: int = DEFAULT_MIN_WEEKLY_HISTORY_RECORDS,
        min_dry_run_days: int = DEFAULT_MIN_DRY_RUN_DAYS,
        agent_report_limit: int = 5,
    ) -> PreV2ReadinessReport:
        items = (
            self._weekly_history_item(min_weekly_records),
            self._multi_day_dry_run_item(multi_day_record_path, min_dry_run_days),
            self._source_gap_item(decision_date),
            self._read_only_agent_report_item(agent_report_limit),
        )
        return PreV2ReadinessReport(
            generated_at=_utc_now_text(),
            overall_status=_overall_status(items),
            production_scheduler_allowed=False,
            items=items,
            limitations=(
                "此報告只讀取現有 evidence / 文件 / report，不會建立 schema 或寫入 DB。",
                "waiting_for_time 只限制 formal evidence credit；排程會自動累積與重驗，不需要人工批准。",
                "Rule / Advice / Paper operational scheduler 可持續運作；本報告不授予 ML 非零 alpha 或投資有效性聲明。",
            ),
        )

    def build_agent_report_sample(self, *, limit: int = 5) -> dict[str, Any]:
        service = AgentEvidenceAccessService(
            self.config,
            evidence_db_path=self.evidence_db_path,
            research_db_path=self.research_db_path,
        )
        evidence = service.query_evidence_events(limit=limit, include_outcomes=True)
        research_runs = service.query_research_runs(limit=limit)
        portfolio_review = service.query_portfolio_review_evidence(limit=limit)
        template = build_ai_report_template()
        evidence_rows = _evidence_rows_from_agent_payloads(evidence, research_runs, portfolio_review)
        warnings = _collect_agent_payload_warnings(evidence, research_runs, portfolio_review)
        return {
            "question": "V2.0 前 read-only Agent report sample 能否引用現有 evidence？",
            "filters": {
                "limit": int(limit),
                "evidence_db_path": str(self.evidence_db_path),
                "research_db_path": str(self.research_db_path),
            },
            "evidence_rows": evidence_rows,
            "quality": {
                "evidence_row_count": len(evidence_rows),
                "template_required_sections": list(template["required_sections"]),
                "template_sections_present": True,
            },
            "warnings": warnings,
            "source_trace": {
                "service": "AgentEvidenceAccessService",
                "mode": "read_only",
                "evidence_diagnostics": list(evidence.get("diagnostics", ())),
                "research_run_diagnostics": list(research_runs.get("diagnostics", ())),
                "portfolio_review_diagnostics": list(portfolio_review.get("diagnostics", ())),
            },
            "limitations": list(template["limitations"]),
            "follow_up_questions": [
                "哪些 evidence rows 值得進入 Unified Decision Workbench 第一屏？",
                "哪些 warning 應留在 drill-down，而不是放到主畫面？",
            ],
        }

    def _weekly_history_item(self, min_weekly_records: int) -> PreV2ReadinessItem:
        periods: dict[tuple[str, str], str] = {}
        diagnostics: list[str] = []
        evidence: dict[str, Any] = {
            "count_policy": "distinct_periods_from_automatic_collection_or_legacy_review",
            "automatic_revalidation": True,
            "human_approval_required": False,
        }
        try:
            projection = load_approved_weekly_history_projection(self.approved_weekly_history_projection_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            projection = None
            diagnostics.append(f"approved_weekly_history_projection_unavailable:{exc}")
        if projection is not None:
            evidence["approved_projection_path"] = str(projection.path)
            for item in projection.records:
                key = (str(item["period_start"]), str(item["period_end"]))
                periods[key] = "legacy_approved_projection"

        try:
            with _connect_read_only(self.evidence_db_path) as conn:
                if _table_exists(conn, "evidence_operations_weekly_reviews"):
                    rows = conn.execute(
                        """
                        SELECT period_start, period_end
                        FROM evidence_operations_weekly_reviews
                        """
                    ).fetchall()
                    for row in rows:
                        periods[(str(row["period_start"]), str(row["period_end"]))] = (
                            "legacy_review_history"
                        )
        except FileNotFoundError as exc:
            diagnostics.append(f"legacy_evidence_db_missing_non_blocking:{exc}")
        except sqlite3.Error as exc:
            diagnostics.append(f"legacy_weekly_history_unavailable_non_blocking:{exc}")

        sidecar_path = (
            Path(self.config.output_root)
            / "scheduled"
            / "v2_2_weekly_collection"
            / "evidence_scheduler.db"
        )
        evidence["automatic_collection_sidecar_path"] = str(sidecar_path)
        try:
            with _connect_read_only(sidecar_path) as conn:
                if _table_exists(conn, "evidence_weekly_collections"):
                    rows = conn.execute(
                        """
                        SELECT period_start, period_end
                        FROM evidence_weekly_collections
                        WHERE status = 'observed_automatic'
                          AND error_type = ''
                          AND source_hash LIKE 'sha256:%'
                        """
                    ).fetchall()
                    for row in rows:
                        periods[(str(row["period_start"]), str(row["period_end"]))] = (
                            "automatic_weekly_collection"
                        )
        except FileNotFoundError:
            diagnostics.append("automatic_weekly_collection_not_yet_observed")
        except sqlite3.Error as exc:
            diagnostics.append(f"automatic_weekly_collection_unavailable:{exc}")

        count = len(periods)
        latest_period_end = max((period_end for _, period_end in periods), default=None)
        evidence["latest_period_end"] = latest_period_end
        evidence["observed_periods"] = [
            {
                "period_start": period_start,
                "period_end": period_end,
                "evidence_source": periods[(period_start, period_end)],
            }
            for period_start, period_end in sorted(periods)
        ]
        if count < min_weekly_records:
            return PreV2ReadinessItem(
                item_id="weekly_history",
                label="多週 weekly evidence operations history",
                status=STATUS_WAITING_FOR_TIME,
                required_count=int(min_weekly_records),
                observed_count=count,
                blocking_reasons=("insufficient_weekly_history_records",),
                next_actions=("排程將自動每週累積並重驗；不需要人工簽核。",),
                evidence=evidence,
                diagnostics=tuple(diagnostics),
            )
        return PreV2ReadinessItem(
            item_id="weekly_history",
            label="多週 weekly evidence operations history",
            status=STATUS_READY,
            required_count=int(min_weekly_records),
            observed_count=count,
            evidence=evidence,
            diagnostics=tuple(diagnostics),
        )

    def _multi_day_dry_run_item(
        self,
        multi_day_record_path: str | Path | None,
        min_dry_run_days: int,
    ) -> PreV2ReadinessItem:
        path = Path(multi_day_record_path) if multi_day_record_path is not None else _default_multi_day_record_path()
        diagnostics: list[str] = []
        rows: list[dict[str, str]] = []
        if not path.exists():
            diagnostics.append(f"multi_day_record_missing:{path}")
        else:
            rows = _parse_multi_day_record(path)

        if diagnostics:
            return PreV2ReadinessItem(
                item_id="multi_day_dry_run",
                label="Multi-day dry-run record",
                status=STATUS_ACTION_REQUIRED,
                required_count=int(min_dry_run_days),
                observed_count=0,
                blocking_reasons=("multi_day_record_missing",),
                next_actions=("建立或指定 multi-day dry-run record markdown。",),
                diagnostics=tuple(diagnostics),
            )
        if len(rows) < min_dry_run_days:
            return PreV2ReadinessItem(
                item_id="multi_day_dry_run",
                label="Multi-day dry-run record",
                status=STATUS_WAITING_FOR_TIME,
                required_count=int(min_dry_run_days),
                observed_count=len(rows),
                blocking_reasons=("insufficient_dry_run_days",),
                next_actions=("繼續填寫 3-5 個交易日 dry-run / smoke / dashboard review 紀錄。",),
                evidence={"dates": [row["Date"] for row in rows]},
            )
        return PreV2ReadinessItem(
            item_id="multi_day_dry_run",
            label="Multi-day dry-run record",
            status=STATUS_READY,
            required_count=int(min_dry_run_days),
            observed_count=len(rows),
            evidence={"dates": [row["Date"] for row in rows]},
        )

    def _source_gap_item(self, decision_date: str | None) -> PreV2ReadinessItem:
        payload = _inspect_source_gaps_read_only(
            self.config,
            evidence_db_path=self.evidence_db_path,
            decision_date=decision_date,
        )
        blocking_gaps = tuple(payload["blocking_gaps"])
        warnings = tuple(payload["warnings"])
        if blocking_gaps or warnings:
            return PreV2ReadinessItem(
                item_id="source_gaps",
                label="Source gaps 收斂狀態",
                status=STATUS_ACTION_REQUIRED,
                blocking_reasons=(*blocking_gaps, *warnings),
                next_actions=("補 persisted recommendation payload、DDD snapshot section 或真實 watchlist / portfolio workflow 樣本。",),
                evidence=payload,
            )
        return PreV2ReadinessItem(
            item_id="source_gaps",
            label="Source gaps 收斂狀態",
            status=STATUS_READY,
            evidence=payload,
        )

    def _read_only_agent_report_item(self, limit: int) -> PreV2ReadinessItem:
        sample = self.build_agent_report_sample(limit=limit)
        row_count = int(sample["quality"]["evidence_row_count"])
        diagnostics = (
            *sample["source_trace"]["evidence_diagnostics"],
            *sample["source_trace"]["research_run_diagnostics"],
            *sample["source_trace"]["portfolio_review_diagnostics"],
        )
        if row_count <= 0:
            return PreV2ReadinessItem(
                item_id="read_only_agent_report_sample",
                label="Read-only Agent report sample",
                status=STATUS_ACTION_REQUIRED,
                observed_count=0,
                blocking_reasons=("no_evidence_rows_available_for_agent_report_sample",),
                next_actions=("先用 working-copy DB 累積 evidence rows，再產生 read-only Agent report sample。",),
                evidence=sample,
                diagnostics=tuple(str(item) for item in diagnostics),
            )
        return PreV2ReadinessItem(
            item_id="read_only_agent_report_sample",
            label="Read-only Agent report sample",
            status=STATUS_READY,
            observed_count=row_count,
            evidence=sample,
            diagnostics=tuple(str(item) for item in diagnostics),
        )


def render_pre_v2_readiness_markdown(report: PreV2ReadinessReport) -> str:
    lines = [
        "# Pre-V2 Readiness Report",
        "",
        f"- generated_at: `{report.generated_at}`",
        f"- overall_status: `{report.overall_status}`",
        f"- production_scheduler_allowed: `{str(report.production_scheduler_allowed).lower()}`",
        f"- rule_operational_scheduler_allowed: `{str(report.rule_operational_scheduler_allowed).lower()}`",
        f"- required_human_action: `{str(report.required_human_action).lower()}`",
        f"- blocking_scope: `{report.blocking_scope}`",
        "",
        "| Item | Status | Observed | Required | Blocking reasons |",
        "|---|---|---:|---:|---|",
    ]
    for item in report.items:
        observed = "" if item.observed_count is None else str(item.observed_count)
        required = "" if item.required_count is None else str(item.required_count)
        blocking = "; ".join(item.blocking_reasons)
        lines.append(f"| {item.label} | `{item.status}` | {observed} | {required} | {blocking} |")
    lines.extend(
        [
            "",
            "## V2.0 Boundary",
            "",
            "- ready 只代表可進入 V2.0 design discussion。",
            "- waiting_for_time 由排程自動累積與重驗，不需要人工批准。",
            "- legacy production_scheduler_allowed 只代表 formal evidence credit；Rule operational scheduler 由獨立 V4 自動 gate 控制。",
        ]
    )
    return "\n".join(lines)


def _overall_status(items: tuple[PreV2ReadinessItem, ...]) -> str:
    statuses = {item.status for item in items}
    if STATUS_ACTION_REQUIRED in statuses:
        return STATUS_ACTION_REQUIRED
    if STATUS_WAITING_FOR_TIME in statuses:
        return STATUS_WAITING_FOR_TIME
    return STATUS_READY


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


def _default_multi_day_record_path() -> Path:
    return Path("docs") / "06_qa" / "POST_V1_EVIDENCE_PIPELINE_MULTI_DAY_DRY_RUN_RECORD.md"


def _parse_multi_day_record(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = _markdown_cells(line)
        if not cells:
            continue
        if cells[0] == "Date":
            headers = cells
            continue
        if cells[0].startswith("---") or cells[0] == "YYYY-MM-DD":
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue
        if headers and len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _markdown_cells(line: str) -> list[str]:
    text = line.strip()
    if not text.startswith("|") or not text.endswith("|"):
        return []
    return [cell.strip() for cell in text.strip("|").split("|")]


def _inspect_source_gaps_read_only(
    config: Any,
    *,
    evidence_db_path: Path,
    decision_date: str | None,
) -> dict[str, Any]:
    recommendation = _latest_recommendation_payload(config)
    latest_snapshot = _latest_decision_desk_snapshot(evidence_db_path, decision_date)
    recommendation_available = recommendation is not None
    why_not_ready = _has_payload((recommendation or {}).get("why_not_payload_json"))
    liquidity_ready = _has_payload((recommendation or {}).get("liquidity_gate_payload_json"))
    screening_matrix_ready = _has_payload((recommendation or {}).get("screening_matrix_json"))
    snapshot_available = latest_snapshot is not None
    watchlist_ready = bool(latest_snapshot and section_is_ready(latest_snapshot["watchlist_trigger_json"]))
    portfolio_ready = bool(latest_snapshot and section_is_ready(latest_snapshot["portfolio_alert_json"]))
    risk_ready = bool(latest_snapshot and section_is_ready(latest_snapshot["risk_prompt_json"]))

    blocking_gaps: list[str] = []
    if not recommendation_available:
        blocking_gaps.append("recommendation_persisted_missing")
    if not snapshot_available:
        blocking_gaps.append("decision_desk_snapshot_missing")
    if snapshot_available and not watchlist_ready:
        blocking_gaps.append("watchlist_trigger_snapshot_section_missing")
    if snapshot_available and not portfolio_ready:
        blocking_gaps.append("portfolio_alert_snapshot_section_missing")
    if snapshot_available and not risk_ready:
        blocking_gaps.append("risk_prompt_snapshot_section_missing")

    warnings: list[str] = []
    if not why_not_ready:
        warnings.append("why_not_payload_missing")
    if not liquidity_ready:
        warnings.append("liquidity_gate_payload_missing")
    if not screening_matrix_ready:
        warnings.append("screening_matrix_missing")

    scheduled_closeout = _scheduled_dry_run_source_gap_closeout(
        config,
        decision_date=decision_date,
        durable_snapshot_available=snapshot_available,
        durable_snapshot_date=latest_snapshot["decision_date"] if latest_snapshot else None,
    )
    if (blocking_gaps or warnings) and scheduled_closeout is not None:
        return scheduled_closeout

    return {
        "source_gap_basis": "durable_db_inspection",
        "corrected_historical_observation_allowed": False,
        "recommendation_persisted_available": recommendation_available,
        "recommendation_exclusion_payload_available": why_not_ready and liquidity_ready,
        "recommendation_screening_matrix_available": screening_matrix_ready,
        "decision_desk_snapshot_available": snapshot_available,
        "latest_decision_desk_snapshot_date": latest_snapshot["decision_date"] if latest_snapshot else None,
        "watchlist_trigger_capture_ready": watchlist_ready,
        "portfolio_alert_capture_ready": portfolio_ready,
        "risk_prompt_capture_ready": risk_ready,
        "why_not_capture_ready": why_not_ready,
        "liquidity_gate_capture_ready": liquidity_ready,
        "screening_matrix_capture_ready": screening_matrix_ready,
        "blocking_gaps": blocking_gaps,
        "warnings": warnings,
    }


def _scheduled_dry_run_source_gap_closeout(
    config: Any,
    *,
    decision_date: str | None,
    durable_snapshot_available: bool,
    durable_snapshot_date: str | None,
) -> dict[str, Any] | None:
    status_path = Path(config.output_root) / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
    try:
        loaded = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None

    scheduled_decision_date = str(loaded.get("decision_date") or "")
    if decision_date and scheduled_decision_date != decision_date:
        return None
    if loaded.get("status") != "passed":
        return None
    if loaded.get("dry_run") is not True:
        return None
    if loaded.get("writes_evidence_db") is not False:
        return None
    if loaded.get("exit_code") not in (0, None):
        return None

    source_blocking = _string_list(loaded.get("source_coverage_blocking_gaps"))
    pipeline_blocking = _string_list(loaded.get("pipeline_blocking_gaps"))
    source_warnings = _string_list(loaded.get("source_coverage_warnings"))
    if source_blocking or pipeline_blocking or source_warnings:
        return None
    if str(loaded.get("scheduler_readiness_after") or "") != "ready_for_manual_confirm":
        return None

    return {
        "source_gap_basis": "scheduled_dry_run_latest_status",
        "corrected_historical_observation_allowed": True,
        "scheduled_dry_run_status_path": str(status_path),
        "scheduled_dry_run_decision_date": scheduled_decision_date or None,
        "scheduled_dry_run_checked_at": loaded.get("checked_at"),
        "scheduled_dry_run_report_path": loaded.get("report_path"),
        "scheduled_dry_run_source_coverage_basis": loaded.get("source_coverage_basis"),
        "scheduler_readiness_after": loaded.get("scheduler_readiness_after"),
        "writes_evidence_db": loaded.get("writes_evidence_db"),
        "dry_run": loaded.get("dry_run"),
        "durable_decision_desk_snapshot_available": durable_snapshot_available,
        "durable_decision_desk_snapshot_date": durable_snapshot_date,
        "recommendation_persisted_available": True,
        "recommendation_exclusion_payload_available": bool(
            loaded.get("recommendation_exclusion_payload_available")
            or (loaded.get("why_not_capture_ready") and loaded.get("liquidity_gate_capture_ready"))
        ),
        "recommendation_screening_matrix_available": bool(
            loaded.get("recommendation_screening_matrix_available") or loaded.get("screening_matrix_capture_ready")
        ),
        "decision_desk_snapshot_available": durable_snapshot_available,
        "latest_decision_desk_snapshot_date": durable_snapshot_date,
        "watchlist_trigger_capture_ready": True,
        "portfolio_alert_capture_ready": True,
        "risk_prompt_capture_ready": True,
        "why_not_capture_ready": bool(loaded.get("why_not_capture_ready")),
        "liquidity_gate_capture_ready": bool(loaded.get("liquidity_gate_capture_ready")),
        "screening_matrix_capture_ready": bool(loaded.get("screening_matrix_capture_ready")),
        "pipeline_warnings_count": loaded.get("pipeline_warnings_count"),
        "pipeline_diagnostic_codes": _string_list(loaded.get("pipeline_diagnostic_codes")),
        "blocking_gaps": [],
        "warnings": [],
        "limitations": [
            "此項只接受 scheduled dry-run latest_status 作為 closeout 觀察證據，不代表正式 evidence DB 已有 durable snapshot。",
            "此項不寫 DB、不啟用 scheduler、不代表 production scheduler approval。",
        ],
    }


def _latest_recommendation_payload(config: Any) -> dict[str, Any] | None:
    runs_dir = Path(config.output_root) / "recommendation" / "runs"
    db_path = runs_dir / "recommendation_runs.db"
    try:
        with _connect_read_only(db_path) as conn:
            if not _table_exists(conn, "runs"):
                return None
            row = conn.execute(
                """
                SELECT result_id, data_path, created_at
                FROM runs
                ORDER BY created_at DESC, result_id ASC
                LIMIT 1
                """
            ).fetchone()
    except (FileNotFoundError, sqlite3.Error):
        return None
    if row is None:
        return None
    data_path = Path(str(row["data_path"]))
    if not data_path.is_absolute():
        data_path = runs_dir / data_path
    if not data_path.exists():
        return None
    try:
        loaded = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _latest_decision_desk_snapshot(
    evidence_db_path: Path,
    decision_date: str | None,
) -> dict[str, Any] | None:
    try:
        with _connect_read_only(evidence_db_path) as conn:
            if not _table_exists(conn, "decision_desk_snapshots"):
                return None
            if decision_date:
                row = conn.execute(
                    """
                    SELECT *
                    FROM decision_desk_snapshots
                    WHERE decision_date <= ? AND snapshot_status = 'active'
                    ORDER BY decision_date DESC, created_at DESC
                    LIMIT 1
                    """,
                    (decision_date,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT *
                    FROM decision_desk_snapshots
                    WHERE snapshot_status = 'active'
                    ORDER BY decision_date DESC, created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
    except (FileNotFoundError, sqlite3.Error):
        return None
    if row is None:
        return None
    payload = dict(row)
    for column in ("watchlist_trigger_json", "portfolio_alert_json", "risk_prompt_json"):
        payload[column] = json.loads(str(payload[column] or "{}"))
    return payload


def _has_payload(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return bool(value)
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _evidence_rows_from_agent_payloads(
    evidence: dict[str, Any],
    research_runs: dict[str, Any],
    portfolio_review: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in evidence.get("events", ()):
        rows.append(
            {
                "row_type": "evidence_event",
                "row_id": event.get("event_id"),
                "quality": event.get("data_quality"),
                "source_trace": event.get("source_trace"),
            }
        )
    for run in research_runs.get("runs", ()):
        rows.append(
            {
                "row_type": "research_run",
                "row_id": run.get("run_id"),
                "quality": "metadata",
                "source_trace": run.get("source_trace"),
            }
        )
    for gap in portfolio_review.get("live_research_gap_observations", ()):
        rows.append(
            {
                "row_type": "live_research_gap",
                "row_id": gap.get("gap_id"),
                "quality": gap.get("data_quality"),
                "source_trace": gap.get("source_trace"),
            }
        )
    for lifecycle in portfolio_review.get("strategy_lifecycle_evidence", ()):
        rows.append(
            {
                "row_type": "strategy_lifecycle_evidence",
                "row_id": lifecycle.get("evidence_id"),
                "quality": lifecycle.get("status"),
                "source_trace": lifecycle.get("source_trace"),
            }
        )
    return rows


def _collect_agent_payload_warnings(
    evidence: dict[str, Any],
    research_runs: dict[str, Any],
    portfolio_review: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    for payload in (evidence, research_runs, portfolio_review):
        warnings.extend(str(item) for item in payload.get("diagnostics", ()))
    return warnings


def _utc_now_text() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
