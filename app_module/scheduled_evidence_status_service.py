from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScheduledEvidenceStatus:
    freshness_status: str = "missing"
    recommendation_status: str = "missing"
    evidence_status: str = "missing"
    latest_data_date: str | None = None
    decision_date: str | None = None
    recommendation_checked_at: str | None = None
    recommendation_result_id: str | None = None
    recommendations_count: int | None = None
    screening_matrix_rows: int | None = None
    why_not_payload_rows: int | None = None
    liquidity_gate_payload_rows: int | None = None
    writes_recommendation_result: bool | None = None
    auto_trading: bool | None = None
    lifecycle_action: bool | None = None
    recommendation_snapshot_observed_days: int = 0
    evidence_dry_run_observed_days: int = 0
    scheduled_joint_observed_days: int = 0
    scheduled_joint_observed_dates: tuple[str, ...] = ()
    checked_at: str | None = None
    evidence_checked_at: str | None = None
    dry_run: bool | None = None
    confirm: bool | None = None
    writes_evidence_db: bool | None = None
    exit_code: int | None = None
    scheduler_readiness_after: str | None = None
    freshness_warnings: tuple[str, ...] = ()
    freshness_errors: tuple[str, ...] = ()
    source_coverage_warnings: tuple[str, ...] = ()
    pipeline_diagnostic_codes: tuple[str, ...] = ()
    pipeline_blocking_gaps: tuple[str, ...] = ()
    report_path: Path | None = None
    log_path: Path | None = None
    report_exists: bool = False
    report_preview: str = ""
    diagnostics: tuple[str, ...] = ()

    @property
    def has_production_write_risk(self) -> bool:
        return bool(self.confirm) or bool(self.writes_evidence_db) or bool(self.auto_trading) or bool(self.lifecycle_action)


class ScheduledEvidenceStatusService:
    """Read-only loader for Windows scheduled evidence output files."""

    def __init__(self, config: Any) -> None:
        self.output_root = Path(config.output_root)

    def load_latest(self) -> ScheduledEvidenceStatus:
        diagnostics: list[str] = []
        freshness_path = self.output_root / "scheduled" / "data_freshness" / "latest_status.json"
        recommendation_path = self.output_root / "scheduled" / "recommendation_snapshot" / "latest_status.json"
        evidence_path = self.output_root / "scheduled" / "evidence_pipeline_dry_run" / "latest_status.json"
        freshness = _read_json(freshness_path, diagnostics)
        recommendation = _read_json(recommendation_path, diagnostics)
        evidence = _read_json(evidence_path, diagnostics)

        report_path = _optional_path(evidence.get("report_path"))
        log_path = _optional_path(evidence.get("log_path"))
        report_preview = ""
        report_exists = bool(report_path and report_path.exists())
        if report_path is not None and report_exists:
            report_preview = _read_report_preview(report_path, diagnostics)
        elif report_path is not None:
            diagnostics.append(f"report_missing:{report_path}")

        checks_raw = freshness.get("checks")
        checks: dict[str, Any] = checks_raw if isinstance(checks_raw, dict) else {}
        latest_data_date = (
            checks.get("daily_prices_latest_date")
            or checks.get("daily_price_latest_date_key")
            or checks.get("technical_indicators_latest_date")
        )
        recommendation_dates = _scheduled_recommendation_dates(self.output_root)
        evidence_dates = _scheduled_evidence_report_dates(self.output_root)
        for raw_date in (recommendation.get("decision_date"), evidence.get("decision_date")):
            date_key = _date_key(raw_date)
            if date_key and raw_date == recommendation.get("decision_date"):
                recommendation_dates.add(date_key)
            if date_key and raw_date == evidence.get("decision_date"):
                evidence_dates.add(date_key)
        joint_dates = tuple(sorted(recommendation_dates & evidence_dates))

        return ScheduledEvidenceStatus(
            freshness_status=str(freshness.get("status") or "missing"),
            recommendation_status=str(recommendation.get("status") or "missing"),
            evidence_status=str(evidence.get("status") or "missing"),
            latest_data_date=str(latest_data_date) if latest_data_date else None,
            decision_date=_str_or_none(evidence.get("decision_date")),
            recommendation_checked_at=_str_or_none(recommendation.get("checked_at")),
            recommendation_result_id=_str_or_none(recommendation.get("result_id")),
            recommendations_count=_int_or_none(recommendation.get("recommendations_count")),
            screening_matrix_rows=_int_or_none(recommendation.get("screening_matrix_rows")),
            why_not_payload_rows=_int_or_none(recommendation.get("why_not_payload_rows")),
            liquidity_gate_payload_rows=_int_or_none(recommendation.get("liquidity_gate_payload_rows")),
            writes_recommendation_result=_bool_or_none(recommendation.get("writes_recommendation_result")),
            auto_trading=_bool_or_none(recommendation.get("auto_trading")),
            lifecycle_action=_bool_or_none(recommendation.get("lifecycle_action")),
            recommendation_snapshot_observed_days=len(recommendation_dates),
            evidence_dry_run_observed_days=len(evidence_dates),
            scheduled_joint_observed_days=len(joint_dates),
            scheduled_joint_observed_dates=joint_dates,
            checked_at=_str_or_none(freshness.get("checked_at")),
            evidence_checked_at=_str_or_none(evidence.get("checked_at")),
            dry_run=_bool_or_none(evidence.get("dry_run")),
            confirm=_merged_bool(evidence.get("confirm"), recommendation.get("confirm")),
            writes_evidence_db=_merged_bool(evidence.get("writes_evidence_db"), recommendation.get("writes_evidence_db")),
            exit_code=_int_or_none(evidence.get("exit_code")),
            scheduler_readiness_after=_str_or_none(evidence.get("scheduler_readiness_after")),
            freshness_warnings=_tuple_of_str(freshness.get("warnings")),
            freshness_errors=_tuple_of_str(freshness.get("errors")),
            source_coverage_warnings=_tuple_of_str(evidence.get("source_coverage_warnings")),
            pipeline_diagnostic_codes=_tuple_of_str(evidence.get("pipeline_diagnostic_codes")),
            pipeline_blocking_gaps=_tuple_of_str(evidence.get("pipeline_blocking_gaps")),
            report_path=report_path,
            log_path=log_path,
            report_exists=report_exists,
            report_preview=report_preview,
            diagnostics=tuple(diagnostics),
        )


def _read_json(path: Path, diagnostics: list[str]) -> dict[str, Any]:
    if not path.exists():
        diagnostics.append(f"status_missing:{path}")
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        diagnostics.append(f"status_unreadable:{path}:{exc}")
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _read_report_preview(path: Path, diagnostics: list[str], *, max_lines: int = 120) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        diagnostics.append(f"report_unreadable:{path}:{exc}")
        return ""
    return "\n".join(lines[:max_lines])


def _optional_path(value: Any) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    return Path(str(value))


def _scheduled_recommendation_dates(output_root: Path) -> set[str]:
    runs_dir = output_root / "recommendation" / "runs"
    dates: set[str] = set()
    if not runs_dir.exists():
        return dates
    for path in runs_dir.glob("scheduled_rec_*.json"):
        parts = path.stem.split("_")
        if len(parts) >= 3 and len(parts[2]) == 8 and parts[2].isdigit():
            dates.add(parts[2])
    return dates


def _scheduled_evidence_report_dates(output_root: Path) -> set[str]:
    report_dir = output_root / "scheduled" / "evidence_pipeline_dry_run" / "reports"
    dates: set[str] = set()
    if not report_dir.exists():
        return dates
    for path in report_dir.glob("*_evidence_pipeline_dry_run.md"):
        prefix = path.name.split("_", 1)[0]
        if len(prefix) == 8 and prefix.isdigit():
            dates.add(prefix)
    return dates


def _date_key(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = text.replace("-", "")
    if len(compact) == 8 and compact.isdigit():
        return compact
    return None


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value),)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        return None
    return bool(value)


def _merged_bool(*values: Any) -> bool | None:
    parsed = [_bool_or_none(value) for value in values if value is not None]
    if not parsed:
        return None
    return any(parsed)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
