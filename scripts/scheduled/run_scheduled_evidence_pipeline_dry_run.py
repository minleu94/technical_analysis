from __future__ import annotations

import argparse
from datetime import datetime
import json
from json import JSONDecodeError
import subprocess
import sys
from typing import Any
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.scheduled.scheduled_clock import scheduled_now
from app_module.position_health_daily_refresh_service import PositionHealthDailyRefreshService
from app_module.forward_position_thesis_candidate_producer import (
    bind_available_candidates,
)
from app_module.paper_position_identity_provider import PaperPositionIdentityProvider
from app_module.position_health_market_source_producer import (
    PositionHealthMarketSourceProducer,
)
from app_module.position_health_transition_evaluator import evaluate_baseline_file
from app_module.exit_effectiveness_read_model import (
    DEFAULT_EXIT_HORIZON_TRADING_DAYS,
)


EXIT_EFFECTIVENESS_TIMEOUT_SECONDS = 120


def _read_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return "unreadable"
    return str(payload.get("status", "unknown"))


def _extract_json_object(text: str) -> dict[str, Any] | None:
    end = text.rfind("}")
    if end < 0:
        return None
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload = json.loads(text[start : end + 1])
        except JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _pipeline_status_fields(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {"pipeline_summary_available": False}
    source_coverage = summary.get("source_coverage")
    if not isinstance(source_coverage, dict):
        source_coverage = {}
    warning_counts = _warning_counts(summary.get("warning_counts"))
    advisory_counts = _warning_counts(summary.get("advisory_counts"))
    natural_maturity_warning_counts = {
        token: count
        for token, count in warning_counts.items()
        if token == "insufficient_future_data"
    }
    actionable_warning_counts = {
        token: count
        for token, count in warning_counts.items()
        if token not in natural_maturity_warning_counts
    }
    return {
        "pipeline_summary_available": True,
        "pipeline_overall_status": str(summary.get("overall_status") or "unknown"),
        "pipeline_warnings_count": int(summary.get("warnings_count") or 0),
        "pipeline_warning_counts": warning_counts,
        "pipeline_warning_unique_count": _warning_unique_count(summary, warning_counts),
        "pipeline_warning_top_counts": _top_warning_counts(warning_counts),
        "pipeline_natural_maturity_warning_count": sum(natural_maturity_warning_counts.values()),
        "pipeline_natural_maturity_warning_counts": natural_maturity_warning_counts,
        "pipeline_actionable_warning_count": sum(actionable_warning_counts.values()),
        "pipeline_actionable_warning_counts": actionable_warning_counts,
        "pipeline_dry_run": bool(summary.get("dry_run")),
        "pipeline_confirm": bool(summary.get("confirm")),
        "pipeline_advisories_count": int(summary.get("advisories_count") or 0),
        "pipeline_advisory_counts": advisory_counts,
        "pipeline_advisory_unique_count": _advisory_unique_count(summary, advisory_counts),
        "pipeline_advisory_top_counts": _top_advisory_counts(advisory_counts),
        "pipeline_errors_count": int(summary.get("errors_count") or 0),
        "pipeline_blocking_gaps": list(summary.get("blocking_gaps") or []),
        "pipeline_diagnostic_codes": list(summary.get("diagnostic_codes") or []),
        "scheduler_readiness_before": summary.get("scheduler_readiness_before"),
        "scheduler_readiness_after": summary.get("scheduler_readiness_after"),
        "source_coverage_warnings": list(source_coverage.get("warnings") or []),
        "source_coverage_blocking_gaps": list(source_coverage.get("blocking_gaps") or []),
        "source_coverage_basis": source_coverage.get("source_coverage_basis"),
        "recommendation_screening_matrix_available": bool(
            source_coverage.get("recommendation_screening_matrix_available")
        ),
        "recommendation_exclusion_payload_available": bool(
            source_coverage.get("recommendation_exclusion_payload_available")
        ),
        "why_not_capture_ready": bool(source_coverage.get("why_not_capture_ready")),
        "liquidity_gate_capture_ready": bool(source_coverage.get("liquidity_gate_capture_ready")),
        "screening_matrix_capture_ready": bool(source_coverage.get("screening_matrix_capture_ready")),
    }


def _warning_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, raw_count in value.items():
        token = str(key).strip()
        if not token:
            continue
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[token] = count
    return dict(sorted(counts.items()))


def _warning_unique_count(summary: dict[str, Any], warning_counts: dict[str, int]) -> int:
    parsed = _optional_int(summary.get("warning_unique_count"))
    if parsed is None:
        return len(warning_counts)
    return parsed if parsed >= 0 else len(warning_counts)


def _top_warning_counts(warning_counts: dict[str, int], *, limit: int = 10) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = [
        {"warning": token, "count": count}
        for token, count in warning_counts.items()
        if token and count > 0
    ]
    return sorted(rows, key=lambda item: (-int(item["count"]), str(item["warning"])))[:limit]


def _advisory_unique_count(summary: dict[str, Any], advisory_counts: dict[str, int]) -> int:
    parsed = _optional_int(summary.get("advisory_unique_count"))
    if parsed is None:
        return len(advisory_counts)
    return parsed if parsed >= 0 else len(advisory_counts)


def _top_advisory_counts(advisory_counts: dict[str, int], *, limit: int = 10) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = [
        {"advisory": token, "count": count}
        for token, count in advisory_counts.items()
        if token and count > 0
    ]
    return sorted(rows, key=lambda item: (-int(item["count"]), str(item["advisory"])))[:limit]


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _process_output_text(value: Any) -> str:
    """Normalize subprocess output for bounded logging and JSON parsing."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _exit_effectiveness_blocked_receipt(
    *,
    command: list[str],
    output_path: Path,
    log_path: Path,
    reason: str,
    return_code: int | None,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "blocked": True,
        "blockers": [reason],
        "research_only": True,
        "formal_credit": False,
        "auto_exit_allowed": False,
        "broker_order_allowed": False,
        "historical_backfill": False,
        "artifact_path": str(output_path),
        "log_path": str(log_path),
        "command": command,
        "child_return_code": return_code,
        "timeout_seconds": EXIT_EFFECTIVENESS_TIMEOUT_SECONDS,
    }


def _run_exit_effectiveness_child(
    *,
    transition_db: Path,
    paper_ledger_db: Path,
    market_db: Path,
    calendar_cache: Path,
    temporary_closure_cache: Path | None,
    output_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    """Run the research-only exit producer with a bounded subprocess.

    The public child CLI intentionally has no historical as-of argument.  It
    derives its date from its own real UTC clock, so this caller never grants
    a prior date credit or falls back to a stale artifact after a failure.
    """

    command = [
        sys.executable,
        "scripts/run_exit_effectiveness_daily.py",
        "--transition-db",
        str(transition_db),
        "--paper-ledger-db",
        str(paper_ledger_db),
        "--market-db",
        str(market_db),
        "--calendar-cache",
        str(calendar_cache),
        "--output",
        str(output_path),
        "--horizon-trading-days",
        str(DEFAULT_EXIT_HORIZON_TRADING_DAYS),
    ]
    if temporary_closure_cache is not None:
        command.extend(("--temporary-closure-cache", str(temporary_closure_cache)))

    completed_stdout = ""
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
            timeout=EXIT_EFFECTIVENESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        completed_stdout = _process_output_text(getattr(exc, "stdout", None))
        log_path.write_text(completed_stdout, encoding="utf-8")
        return _exit_effectiveness_blocked_receipt(
            command=command,
            output_path=output_path,
            log_path=log_path,
            reason="exit_effectiveness_child_timeout",
            return_code=None,
        )
    except OSError as exc:
        completed_stdout = _process_output_text(getattr(exc, "stdout", None))
        log_path.write_text(completed_stdout, encoding="utf-8")
        return _exit_effectiveness_blocked_receipt(
            command=command,
            output_path=output_path,
            log_path=log_path,
            reason=f"exit_effectiveness_child_oserror:{type(exc).__name__}",
            return_code=None,
        )

    completed_stdout = _process_output_text(getattr(completed, "stdout", None))
    log_path.write_text(completed_stdout, encoding="utf-8")
    receipt = _extract_json_object(completed_stdout)
    if receipt is None:
        return _exit_effectiveness_blocked_receipt(
            command=command,
            output_path=output_path,
            log_path=log_path,
            reason="exit_effectiveness_child_json_missing",
            return_code=int(completed.returncode),
        )

    child_status = str(receipt.get("status") or "unknown").strip().lower()
    blockers_value = receipt.get("blockers")
    blockers = (
        [str(item) for item in blockers_value if str(item).strip()]
        if isinstance(blockers_value, list)
        else []
    )
    child_return_code = int(completed.returncode)
    blocked = child_return_code != 0 or child_status not in {"passed", "degraded"}
    if child_return_code != 0 and not blockers:
        blockers.append(f"exit_effectiveness_child_returncode:{child_return_code}")
    if child_status not in {"passed", "degraded"} and not blockers:
        blockers.append(f"exit_effectiveness_child_status:{child_status}")
    return {
        "status": "blocked" if blocked else child_status,
        "blocked": blocked,
        "blockers": blockers,
        "research_only": bool(receipt.get("research_only", True)),
        "historical_backfill": bool(receipt.get("historical_backfill", False)),
        "artifact_path": str(output_path),
        "log_path": str(log_path),
        "command": command,
        "child_return_code": child_return_code,
        "timeout_seconds": EXIT_EFFECTIVENESS_TIMEOUT_SECONDS,
        "receipt": receipt,
    }


def _scheduled_status(
    *,
    return_code: int,
    freshness_status: str,
    pipeline_summary: dict[str, Any] | None,
) -> str:
    if return_code != 0 or freshness_status == "failed":
        return "failed"
    if not pipeline_summary:
        return "degraded"

    pipeline_status = str(pipeline_summary.get("overall_status") or "unknown")
    errors_count = int(pipeline_summary.get("errors_count") or 0)
    warnings_count = int(pipeline_summary.get("warnings_count") or 0)
    blocking_gaps = list(pipeline_summary.get("blocking_gaps") or [])
    if pipeline_status == "failed" or errors_count > 0:
        return "failed"
    if freshness_status == "passed" and pipeline_status == "ready_with_advisories" and not blocking_gaps:
        return "ready_with_advisories"
    if (
        freshness_status != "passed"
        or pipeline_status != "ready"
        or warnings_count > 0
        or blocking_gaps
    ):
        return "degraded"
    return "passed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scheduled evidence pipeline dry-run wrapper.")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--sources", default="all")
    parser.add_argument(
        "--paper-evidence-operation-root",
        help="isolated repository output root containing Paper snapshot state",
    )
    parser.add_argument(
        "--paper-evidence-ledger-db",
        help="Paper trade ledger SQLite used to prove cross-date position continuity",
    )
    parser.add_argument(
        "--paper-evidence-health-status-path",
        help="Paper preopen status receipt used by the daily health refresh",
    )
    parser.add_argument(
        "--paper-evidence-health-baseline",
        help="position-health baseline JSON consumed read-only by evidence",
    )
    parser.add_argument("--paper-evidence-status-path")
    parser.add_argument(
        "--refresh-paper-health",
        action="store_true",
        help="refresh the derived Paper position-health baseline before evidence capture",
    )
    parser.add_argument(
        "--evaluate-position-health-transition",
        action="store_true",
        help="evaluate the refreshed health baseline into isolated proposal-only output",
    )
    parser.add_argument(
        "--paper-health-thesis-registry",
        help="derived append-only human thesis registry JSON",
    )
    parser.add_argument(
        "--paper-health-forward-binding",
        help=(
            "optional verified forward candidate-to-Paper-entry binding JSON; "
            "consumed as lineage provenance only"
        ),
    )
    parser.add_argument(
        "--bind-forward-thesis",
        action="store_true",
        help="automatically bind current-baseline candidate packets to verified Paper entries",
    )
    parser.add_argument(
        "--forward-candidate-root",
        help="repository-isolated forward candidate root used by the daily binder",
    )
    parser.add_argument(
        "--forward-paper-candidate-root",
        help="repository-isolated Paper candidate root scanned by the daily binder",
    )
    parser.add_argument(
        "--paper-health-condition-source",
        help="hash-bound PIT condition source JSON",
    )
    parser.add_argument(
        "--paper-health-metrics-source",
        help="hash-bound Decimal metric source JSON",
    )
    parser.add_argument(
        "--paper-health-policy-source",
        help=(
            "verified Formal machine Rule source status JSON; carries the "
            "frozen policy identity without creating a position thesis"
        ),
    )
    parser.add_argument(
        "--produce-position-health-sources",
        action="store_true",
        help=(
            "read the verified daily market source and create isolated PIT "
            "condition/Decimal metric artifacts before transition evaluation"
        ),
    )
    parser.add_argument(
        "--paper-health-source-output",
        help="isolated output directory for generated condition/metric artifacts",
    )
    parser.add_argument(
        "--paper-health-quick-status-path",
        help="data-update quick status JSON used by the generated sources",
    )
    parser.add_argument(
        "--paper-health-freshness-status-path",
        help="data-freshness status JSON used by the generated sources",
    )
    parser.add_argument(
        "--paper-health-calendar-cache",
        help="verified offline official calendar cache directory",
    )
    parser.add_argument(
        "--paper-health-temporary-closure-cache",
        help="verified official temporary-closure cache directory",
    )
    parser.add_argument(
        "--paper-health-calendar-db",
        help="optional read-only market DB fallback path",
    )
    parser.add_argument(
        "--paper-health-calendar-start-date",
        help="optional YYYY-MM-DD calendar range start",
    )
    parser.add_argument(
        "--run-exit-effectiveness",
        action="store_true",
        help=(
            "run the bounded research-only exit effectiveness child after the "
            "position-health transition proposal"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Required marker for scheduled dry-run mode.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dry_run:
        raise SystemExit("scheduled evidence wrapper requires --dry-run")
    output_root = Path(args.output_root)
    run_root = output_root / "scheduled" / "evidence_pipeline_dry_run"
    report_root = run_root / "reports"
    run_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)

    run_now = scheduled_now()
    decision_date = run_now.date().isoformat()
    today_key = decision_date.replace("-", "")
    status_path = run_root / "latest_status.json"
    log_path = run_root / f"{today_key}_evidence_pipeline_dry_run.log"
    report_path = report_root / f"{today_key}_evidence_pipeline_dry_run.md"
    freshness_status_path = output_root / "scheduled" / "data_freshness" / "latest_status.json"
    paper_operation_root = Path(
        args.paper_evidence_operation_root
        or (REPO_ROOT / "output" / "paper_execution_eod_replay")
    )
    paper_health_baseline = Path(
        args.paper_evidence_health_baseline
        or (
            output_root / "position_health" / "latest.json"
            if args.refresh_paper_health
            else output_root / "position_health" / "baseline_20260712.json"
        )
    )
    paper_status_path = (
        Path(args.paper_evidence_status_path)
        if args.paper_evidence_status_path
        else paper_operation_root / "scheduled" / "paper_portfolio_daily" / "latest_status.json"
    )
    paper_ledger_path = Path(
        args.paper_evidence_ledger_db
        or paper_operation_root / "paper_trade_ledger.sqlite"
    )
    paper_health_status_path = Path(
        args.paper_evidence_health_status_path
        or paper_operation_root
        / "scheduled"
        / "paper_portfolio_isolated"
        / "latest_status.json"
    )
    forward_candidate_root = Path(
        args.forward_candidate_root
        or REPO_ROOT / "output" / "forward_position_thesis"
    )
    forward_paper_candidate_root = Path(
        args.forward_paper_candidate_root
        or paper_operation_root / "candidates"
    )
    effective_forward_binding_path: str | Path | None = (
        args.paper_health_forward_binding
        if args.paper_health_forward_binding
        else (
            forward_candidate_root / "bindings"
            if args.bind_forward_thesis
            else None
        )
    )

    paper_health_refresh: dict[str, Any] | None = None
    if args.refresh_paper_health:
        health_output_dir = paper_health_baseline.parent
        previous_baseline = paper_health_baseline if paper_health_baseline.is_file() else health_output_dir / "latest.json"
        try:
            paper_health_refresh = PositionHealthDailyRefreshService(
                state_db_path=paper_operation_root / "paper_portfolio" / "paper_portfolio.sqlite",
                status_path=paper_health_status_path,
                ledger_db_path=paper_ledger_path,
                coverage_status_path=paper_health_status_path,
                position_identity_provider=PaperPositionIdentityProvider(
                    state_db_path=paper_operation_root / "paper_portfolio" / "paper_portfolio.sqlite",
                    ledger_db_path=paper_ledger_path,
                    coverage_status_path=paper_health_status_path,
                ),
            ).refresh(
                as_of_date=run_now.date(),
                output_dir=health_output_dir,
                previous_baseline_path=previous_baseline,
                observed_at=run_now,
            )
        except Exception as exc:  # noqa: BLE001
            paper_health_refresh = {
                "status": "blocked",
                "blockers": [f"paper_health_refresh_unhandled:{type(exc).__name__}"],
                "warnings": [str(exc)],
                "latest_path": str(health_output_dir / "latest.json"),
            }
        if paper_health_refresh.get("status") not in {"passed", "reused"}:
            # Do not let a stale prior baseline look current after a failed
            # refresh.  The missing path makes the downstream source return
            # explicit unknown/MISSING and keeps readiness fail-closed.
            paper_health_baseline = run_root / f".paper_health_unavailable_{today_key}.json"
        else:
            latest_path = paper_health_refresh.get("latest_path")
            if isinstance(latest_path, str) and latest_path.strip():
                paper_health_baseline = Path(latest_path)

    forward_binding: dict[str, Any] | None = None
    if args.bind_forward_thesis:
        if paper_health_refresh is None or paper_health_refresh.get("status") not in {
            "passed",
            "reused",
        }:
            forward_binding = {
                "status": "blocked",
                "candidate_root": str(forward_candidate_root),
                "paper_candidate_root": str(forward_paper_candidate_root),
                "candidate_count": 0,
                "bound_count": 0,
                "awaiting_count": 0,
                "blocked_count": 1,
                "results": [],
                "warnings": [],
                "blockers": ["forward_daily_binding_health_baseline_unavailable"],
            }
        else:
            forward_binding = bind_available_candidates(
                candidate_root=forward_candidate_root,
                baseline_path=paper_health_baseline,
                paper_candidate_root=forward_paper_candidate_root,
            )

    paper_health_source: dict[str, Any] | None = None
    generated_condition_source: str | None = None
    generated_metrics_source: str | None = None
    if args.produce_position_health_sources:
        source_output = Path(
            args.paper_health_source_output
            or output_root / "position_health_sources"
        )
        quick_status_path = Path(
            args.paper_health_quick_status_path
            or output_root / "scheduled" / "data_update_quick" / "latest_status.json"
        )
        source_freshness_path = Path(
            args.paper_health_freshness_status_path
            or output_root / "scheduled" / "data_freshness" / "latest_status.json"
        )
        try:
            paper_health_source = PositionHealthMarketSourceProducer(
                market_db_path=args.db_path,
                quick_status_path=quick_status_path,
                freshness_status_path=source_freshness_path,
            ).produce(
                baseline_path=paper_health_baseline,
                output_dir=source_output,
                decision_date=decision_date,
            )
            generated_condition_source = str(
                paper_health_source.get("condition_source_path") or ""
            ) or None
            generated_metrics_source = str(
                paper_health_source.get("metrics_source_path") or ""
            ) or None
        except Exception as exc:  # noqa: BLE001
            paper_health_source = {
                "status": "blocked",
                "blockers": [
                    f"position_health_market_source_unhandled:{type(exc).__name__}:{exc}"
                ],
                "warnings": [],
                "output_dir": str(source_output),
                "quick_status_path": str(quick_status_path),
                "freshness_status_path": str(source_freshness_path),
            }
            # Do not let a stale source path from a prior day be consumed when
            # the current source read failed.  The transition provider will
            # report explicit missing/unknown inputs instead.
            generated_condition_source = str(
                run_root / f".position_health_condition_unavailable_{today_key}.json"
            )
            generated_metrics_source = str(
                run_root / f".position_health_metrics_unavailable_{today_key}.json"
            )

    condition_source_for_evaluation = (
        args.paper_health_condition_source or generated_condition_source
    )
    metrics_source_for_evaluation = (
        args.paper_health_metrics_source or generated_metrics_source
    )

    # A natural source capture owns the effective health decision clock.  The
    # source provider records its real read completion; using it here keeps
    # the evaluator from consuming a market artifact as though it existed at
    # the wrapper's earlier startup timestamp.  A blocked/fake source falls
    # back to the wrapper clock so the failure remains explicit in the
    # evaluator result.
    position_health_observed_at: datetime | str = run_now
    if paper_health_source is not None and paper_health_source.get("status") != "blocked":
        captured_at = paper_health_source.get("market_capture_completed_at")
        if isinstance(captured_at, str) and captured_at.strip():
            position_health_observed_at = captured_at

    position_health_transition: dict[str, Any] | None = None
    position_health_transition_output: Path | None = None
    if args.evaluate_position_health_transition:
        position_health_transition_output = output_root / "position_health_transition"
        try:
            position_health_transition = evaluate_baseline_file(
                baseline_path=paper_health_baseline,
                output_dir=position_health_transition_output,
                observed_at=position_health_observed_at,
                decision_date=decision_date,
                transition_repository_path=(
                    position_health_transition_output
                    / "position_health_transitions.sqlite"
                ),
                thesis_registry_path=args.paper_health_thesis_registry,
                forward_binding_path=effective_forward_binding_path,
                condition_source_path=condition_source_for_evaluation,
                metrics_source_path=metrics_source_for_evaluation,
                policy_source_path=args.paper_health_policy_source,
                calendar_cache_path=(
                    args.paper_health_calendar_cache
                    or paper_operation_root / "calendar_cache"
                ),
                temporary_closure_path=args.paper_health_temporary_closure_cache,
                calendar_db_path=args.paper_health_calendar_db,
                calendar_start_date=args.paper_health_calendar_start_date,
            )
        except Exception as exc:  # noqa: BLE001
            position_health_transition = {
                "status": "blocked",
                "blockers": [
                    f"position_health_transition_unhandled:{type(exc).__name__}"
                ],
                "warnings": [str(exc)],
            }

    exit_effectiveness: dict[str, Any] | None = None
    exit_effectiveness_output: Path | None = None
    exit_effectiveness_log: Path | None = None
    if args.run_exit_effectiveness:
        effective_transition_output = (
            position_health_transition_output
            or output_root / "position_health_transition"
        )
        exit_effectiveness_output = (
            output_root / "exit_effectiveness" / f"{today_key}.json"
        )
        exit_effectiveness_log = run_root / f"{today_key}_exit_effectiveness.log"
        exit_calendar_cache = Path(
            args.paper_health_calendar_cache
            or paper_operation_root / "calendar_cache"
        )
        exit_temporary_closure_cache = (
            Path(args.paper_health_temporary_closure_cache)
            if args.paper_health_temporary_closure_cache
            else None
        )
        exit_effectiveness = _run_exit_effectiveness_child(
            transition_db=(
                effective_transition_output / "position_health_transitions.sqlite"
            ),
            paper_ledger_db=paper_ledger_path,
            market_db=Path(args.db_path),
            calendar_cache=exit_calendar_cache,
            temporary_closure_cache=exit_temporary_closure_cache,
            output_path=exit_effectiveness_output,
            log_path=exit_effectiveness_log,
        )

    command = [
        sys.executable,
        "scripts/run_evidence_pipeline.py",
        "--decision-date",
        decision_date,
        "--dry-run",
        "--db-path",
        args.db_path,
        "--data-root",
        args.data_root,
        "--output-root",
        args.output_root,
        "--sources",
        args.sources,
        "--report-output",
        str(report_path),
        "--json-output",
        "--paper-evidence-operation-root",
        str(paper_operation_root),
        "--paper-evidence-health-baseline",
        str(paper_health_baseline),
        "--paper-evidence-status-path",
        str(paper_status_path),
    ]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    pipeline_summary = _extract_json_object(completed.stdout)

    freshness_status = _read_status(freshness_status_path)
    paper_health_refresh_blocked = bool(
        paper_health_refresh is not None
        and paper_health_refresh.get("status") not in {"passed", "reused"}
    )
    paper_health_source_blocked = bool(
        paper_health_source is not None
        and paper_health_source.get("status") == "blocked"
    )
    forward_binding_blocked = bool(
        forward_binding is not None and forward_binding.get("status") == "blocked"
    )
    # A blocked pre-child health refresh is a wrapper failure even when the
    # child happens to return zero.  Keep the child's code separately for
    # diagnosis, but propagate a non-zero scheduler result so a stale
    # baseline cannot look like a successful morning run.
    wrapper_exit_code = completed.returncode
    if paper_health_refresh_blocked and wrapper_exit_code == 0:
        wrapper_exit_code = 2
    if paper_health_source_blocked and wrapper_exit_code == 0:
        wrapper_exit_code = 2
    if forward_binding_blocked and wrapper_exit_code == 0:
        wrapper_exit_code = 2
    position_health_transition_blocked = bool(
        position_health_transition is not None
        and position_health_transition.get("status") == "blocked"
    )
    if position_health_transition_blocked and wrapper_exit_code == 0:
        wrapper_exit_code = 2
    exit_effectiveness_blocked = bool(
        exit_effectiveness is not None
        and exit_effectiveness.get("blocked") is True
    )
    if exit_effectiveness_blocked and wrapper_exit_code == 0:
        wrapper_exit_code = 2
    status = _scheduled_status(
        return_code=wrapper_exit_code,
        freshness_status=freshness_status,
        pipeline_summary=pipeline_summary,
    )
    if (
        position_health_transition is not None
        and position_health_transition.get("status") == "degraded"
        and status in {"passed", "ready_with_advisories"}
    ):
        status = "degraded"
    if (
        exit_effectiveness is not None
        and exit_effectiveness.get("status") == "degraded"
        and status in {"passed", "ready_with_advisories"}
    ):
        status = "degraded"

    pipeline_fields = _pipeline_status_fields(pipeline_summary)
    pipeline_actionable_warning_count = int(pipeline_fields.get("pipeline_actionable_warning_count") or 0)
    pipeline_natural_maturity_warning_count = int(
        pipeline_fields.get("pipeline_natural_maturity_warning_count") or 0
    )
    pipeline_errors_count = int(pipeline_fields.get("pipeline_errors_count") or 0)
    pipeline_blocking_gaps = list(pipeline_fields.get("pipeline_blocking_gaps") or [])
    manual_action_required = bool(
        wrapper_exit_code != 0
        or freshness_status != "passed"
        or pipeline_summary is None
        or pipeline_errors_count > 0
        or pipeline_blocking_gaps
        or pipeline_actionable_warning_count > 0
        or paper_health_refresh_blocked
        or paper_health_source_blocked
        or forward_binding_blocked
        or (
            position_health_transition is not None
            and position_health_transition.get("status") in {"degraded", "blocked"}
        )
        or exit_effectiveness_blocked
    )
    payload = {
        "task": "baldr-evidence-pipeline-dry-run-daily",
        "status": status,
        "dry_run": True,
        "confirm": False,
        "writes_evidence_db": False,
        "production_scheduler_allowed": False,
        "decision_date": decision_date,
        "db_path": args.db_path,
        "freshness_status": freshness_status,
        "freshness_status_path": str(freshness_status_path),
        "report_path": str(report_path),
        "log_path": str(log_path),
        "exit_code": wrapper_exit_code,
        "checked_at": run_now.isoformat(timespec="seconds"),
        "manual_action_required": manual_action_required,
        "natural_maturity_only": bool(
            pipeline_natural_maturity_warning_count > 0 and not manual_action_required
        ),
        "paper_health_refresh_status": (
            "not_requested"
            if paper_health_refresh is None
            else paper_health_refresh.get("status", "unknown")
        ),
        "paper_health_refresh_receipt": paper_health_refresh,
        "paper_evidence_health_baseline": str(paper_health_baseline),
        "paper_evidence_health_status_path": str(paper_health_status_path),
        "paper_evidence_ledger_db": str(paper_ledger_path),
        "paper_health_refresh_blocked": paper_health_refresh_blocked,
        "paper_health_source_status": (
            "not_requested"
            if paper_health_source is None
            else paper_health_source.get("status", "unknown")
        ),
        "paper_health_source_receipt": paper_health_source,
        "paper_health_condition_source": condition_source_for_evaluation,
        "paper_health_metrics_source": metrics_source_for_evaluation,
        "paper_health_policy_source": args.paper_health_policy_source,
        "paper_health_forward_binding": (
            None
            if effective_forward_binding_path is None
            else str(effective_forward_binding_path)
        ),
        "forward_position_thesis_binding_root": (
            None
            if effective_forward_binding_path is None
            else str(effective_forward_binding_path)
        ),
        "forward_position_thesis_binding": forward_binding,
        "forward_position_thesis_binding_blocked": forward_binding_blocked,
        "paper_health_source_blocked": paper_health_source_blocked,
        "paper_health_transition_observed_at": (
            position_health_observed_at.isoformat()
            if isinstance(position_health_observed_at, datetime)
            else position_health_observed_at
        ),
        "pipeline_exit_code": completed.returncode,
        "position_health_transition_status": (
            "not_requested"
            if position_health_transition is None
            else position_health_transition.get("status", "unknown")
        ),
        "position_health_transition_output": (
            None
            if position_health_transition_output is None
            else str(position_health_transition_output)
        ),
        "position_health_transition_evaluation": position_health_transition,
        "exit_effectiveness_status": (
            "not_requested"
            if exit_effectiveness is None
            else exit_effectiveness.get("status", "unknown")
        ),
        "exit_effectiveness_blocked": exit_effectiveness_blocked,
        "exit_effectiveness_output": (
            None
            if exit_effectiveness_output is None
            else str(exit_effectiveness_output)
        ),
        "exit_effectiveness_log": (
            None
            if exit_effectiveness_log is None
            else str(exit_effectiveness_log)
        ),
        "exit_effectiveness_receipt": exit_effectiveness,
    }
    payload.update(pipeline_fields)
    status_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    stdout_text = json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2)
    status_path.write_text(status_text + "\n", encoding="utf-8")
    print(stdout_text)
    return wrapper_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
