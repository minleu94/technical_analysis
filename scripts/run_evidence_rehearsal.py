"""Run a controlled projection or working-copy evidence rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.evidence_rehearsal_adapters import HistoricalReplayRehearsalAdapter  # noqa: E402
from app_module.evidence_rehearsal_coverage import (  # noqa: E402
    CoverageObservation,
    EvidenceRehearsalCoverageProjector,
)
from app_module.evidence_rehearsal_dtos import (  # noqa: E402
    CoverageMetric,
    EvidenceRehearsalScenario,
    RehearsalArtifact,
)
from app_module.evidence_rehearsal_service import EvidenceRehearsalService  # noqa: E402
from app_module.evidence_rehearsal_fault_injection import (  # noqa: E402
    EvidenceRehearsalFaultInjector,
)
from app_module.evidence_rehearsal_orchestrator import (  # noqa: E402
    EvidenceRehearsalExecutionReport,
    EvidenceRehearsalExecutionRequest,
    EvidenceRehearsalOrchestrator,
)
from app_module.evidence_rehearsal_ml_provider import (  # noqa: E402
    JsonMLRehearsalEvidenceProvider,
)
from app_module.evidence_rehearsal_source_reader import (  # noqa: E402
    EvidenceRehearsalSourceReader,
    EvidenceRehearsalSourceSnapshot,
)
from app_module.evidence_rehearsal_source_comparison import (  # noqa: E402
    P0SourceShadowComparisonService,
)
from data_module.config import TWStockConfig  # noqa: E402
from data_module.p0_shadow_observation import P0ShadowObservation  # noqa: E402


_FAILURE_BLOCKERS = {
    "missing_day": "missing_required_adapter_output:source",
    "source_outage": "adapter_failure:source:source_outage",
    "future_available_date": "future_available_date:source-data",
    "schema_missing": "missing_field:source-data:source_version",
    "immature_label": "immature_label:ml-shadow",
}
_PRODUCTION_MARKERS = frozenset({"prod", "production"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a controlled projection or working-copy evidence rehearsal."
    )
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--working-copy-db", type=Path, required=True)
    parser.add_argument("--replay-summary", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--execution-mode",
        choices=("projection_only", "working_copy_e2e"),
        default="projection_only",
    )
    parser.add_argument("--overwrite-working-copy", action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--ml-evidence-root", type=Path)
    parser.add_argument(
        "--inject-failure",
        choices=(
            "missing_day",
            "source_outage",
            "future_available_date",
            "schema_missing",
            "immature_label",
        ),
    )
    return parser


def _read_json_mapping(path: Path, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be readable JSON: {path}") from error
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _is_production_like(path: Path) -> bool:
    resolved_path = path.expanduser().resolve()
    normalized = str(resolved_path).replace("\\", "/").lower()
    tokens = {
        token
        for segment in normalized.split("/")
        for token in re.split(r"[_.-]+", segment)
        if token
    }
    if tokens & _PRODUCTION_MARKERS:
        return True
    return _is_at_or_below(resolved_path, _configured_data_root())


def _configured_data_root() -> Path:
    """Resolve TWStockConfig's configured production root without constructing it."""
    data_root_factory = cast(
        Callable[[], Path],
        TWStockConfig.__dataclass_fields__["data_root"].default_factory,
    )
    return Path(data_root_factory()).expanduser().resolve()


def _is_at_or_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_paths(source_db: Path, working_copy_db: Path, output_root: Path) -> None:
    if source_db.expanduser().resolve() == working_copy_db.expanduser().resolve():
        raise ValueError("working-copy DB must differ from source DB")
    for label, path in (("working-copy DB", working_copy_db), ("output root", output_root)):
        if _is_production_like(path):
            raise ValueError(f"{label} must not be production-like")
    if not source_db.is_file():
        raise ValueError(f"source DB not found: {source_db}")


def _scenario_from_payload(
    payload: Mapping[str, object],
    *,
    source_db: Path,
    working_copy_db: Path,
) -> EvidenceRehearsalScenario:
    scenario_id = payload.get("scenario_id")
    decision_date = payload.get("decision_date")
    tier = payload.get("tier", "engineering_fixture")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ValueError("scenario.scenario_id must be a non-empty string")
    if not isinstance(decision_date, str):
        raise ValueError("scenario.decision_date must be an ISO date")
    if not isinstance(tier, str):
        raise ValueError("scenario.tier must be a supported evidence tier")
    return EvidenceRehearsalScenario(
        scenario_id=scenario_id,
        decision_date=decision_date,
        source_db_path=str(source_db),
        working_copy_db_path=str(working_copy_db),
        tier=tier,  # type: ignore[arg-type]
    )


def _build_report(
    scenario: EvidenceRehearsalScenario,
    replay_summary: Mapping[str, object],
    injection_name: str | None,
    *,
    execution_mode: str = "projection_only",
    source_snapshot: EvidenceRehearsalSourceSnapshot | None = None,
    working_copy_created: bool = False,
    coherence_blocker: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    replay_artifacts = (
        ()
        if coherence_blocker is not None
        else HistoricalReplayRehearsalAdapter().project(
            replay_summary,
            decision_date=scenario.decision_date,
            rollback_reference="rehearsal:projection-only",
        )
    )
    coverage = _coverage_from_replay(replay_artifacts, scenario.decision_date)
    rehearsal_report = EvidenceRehearsalService().build(
        scenario, artifacts=replay_artifacts, coverage=coverage
    )
    p0_shadow = P0SourceShadowComparisonService(
        decision_date=scenario.decision_date,
        shadow_observations=_p0_observations_from_replay(replay_summary),
    ).build_report().to_dict()
    ml_shadow = _ml_shadow_from_replay(replay_summary)
    blockers = list(_rehearsal_blockers(rehearsal_report))
    if coherence_blocker is not None:
        blockers.append(coherence_blocker)
    for item in p0_shadow["items"]:
        if isinstance(item, Mapping):
            source_id = item.get("source_id")
            if isinstance(source_id, str):
                blockers.extend(f"p0_shadow:{source_id}:{blocker}" for blocker in item.get("blockers", ()))
    if ml_shadow["status"] != "shadow_ready":
        blockers.append(f"ml_shadow:{ml_shadow['status']}")
    if injection_name is not None:
        blockers.append(_FAILURE_BLOCKERS[injection_name])
    blockers = list(dict.fromkeys(blockers))
    status = "degraded" if blockers else "rehearsal_only"
    injection = (
        {"name": None, "status": status, "blocker": None}
        if injection_name is None
        else {
            "name": injection_name,
            "status": "degraded",
            "blocker": _FAILURE_BLOCKERS[injection_name],
        }
    )
    execution = {
        "mode": execution_mode,
        "source_db_opened": source_snapshot is not None,
        "source_db_write_performed": False,
        "working_copy_created": working_copy_created,
        "working_copy_write_performed": working_copy_created,
        "production_db_write_performed": False,
        "db_write_performed": False,
        "scheduler_invoked": False,
        "broker_invoked": False,
        "advice_invoked": False,
        "promotion_invoked": False,
    }
    semantic_fingerprint = _semantic_fingerprint(
        scenario=scenario,
        replay_summary=replay_summary,
        source_snapshot=source_snapshot,
        coherence_blocker=coherence_blocker,
    )
    report = {
        "contract_version": 2,
        "status": status,
        "scenario": scenario.to_dict(),
        "execution": execution,
        "source_snapshot": (
            source_snapshot.to_dict()
            if source_snapshot is not None
            else {
                "opened": False,
                "access_mode": "not_opened_projection_only",
                "schema_fingerprint": None,
                "table_row_counts": {},
                "p0_observations": [],
                "diagnostics": [],
            }
        ),
        "semantic_fingerprint": semantic_fingerprint,
        "lineage": {
            "status": "pending_orchestration",
            "artifact_dag": {},
            "artifact_hashes": {},
        },
        "formal_product_closeout": False,
        "production_actions_allowed": False,
        "injection": injection,
        "blockers": blockers,
        "rehearsal_report": rehearsal_report.to_dict(),
        "coverage_metrics": [metric.to_dict() for metric in coverage],
        "p0_source_shadow": p0_shadow,
        "ml_shadow": ml_shadow,
        "historical_replay_artifacts": [artifact.to_dict() for artifact in replay_artifacts],
    }
    handoff = {
        "contract_version": 2,
        "status": "forward_handoff_pending",
        "scenario_id": scenario.scenario_id,
        "decision_date": scenario.decision_date,
        "rehearsal_status": status,
        "blockers": blockers,
        "owner": "human_evidence_operations_owner",
        "completion_rule": "Real-time evidence, required approvals, and explicit manual review are required; this CLI cannot complete or promote them.",
        "required_manual_actions": [
            "Validate real-time source availability and licence terms.",
            "Review data quality, PIT availability, and label maturity.",
            "Approve any scheduler, broker, Advice, or promotion action outside this rehearsal.",
        ],
        "production_actions_allowed": False,
        "prohibited_actions": [
            "production_database_write",
            "scheduler_enablement",
            "broker_invocation",
            "advice_invocation",
            "model_or_strategy_promotion",
        ],
    }
    return report, handoff


def _coverage_from_replay(
    artifacts: tuple[RehearsalArtifact, ...], decision_date: str
) -> tuple[CoverageMetric, ...]:
    if not artifacts:
        return (
            CoverageMetric(
                source_id="historical_replay",
                total_count=1,
                observed_count=0,
                degraded_count=0,
                missing_count=1,
                future_blocked_count=0,
                immature_label_count=0,
                coverage_bp=0,
            ),
        )
    observations = []
    for artifact in artifacts:
        payload = artifact.canonical_payload or {}
        available_date = payload.get("available_date", artifact.available_date)
        observations.append(
            CoverageObservation(
                row_id=artifact.artifact_id,
                source_id="historical_replay",
                source_version=artifact.source_version or "missing",
                decision_date=decision_date,
                available_date=str(available_date) if available_date else None,
                quality="complete" if artifact.current_status == "projected" else "degraded",
                feature_present=artifact.missing_state is None,
                label_maturity_date=(
                    decision_date if artifact.effectiveness_denominator_included else None
                ),
            )
        )
    return EvidenceRehearsalCoverageProjector().project(
        observations, decision_date=decision_date
    )


def _p0_observations_from_replay(
    replay_summary: Mapping[str, object],
) -> tuple[P0ShadowObservation, ...]:
    raw_items = replay_summary.get("p0_shadow_observations", ())
    if not isinstance(raw_items, list):
        return ()
    observations: list[P0ShadowObservation] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        required = ("source_id", "symbol", "decision_date", "source_version", "status")
        if not all(isinstance(item.get(field), str) for field in required):
            continue
        diagnostics = item.get("diagnostics", ())
        observations.append(
            P0ShadowObservation(
                source_id=str(item["source_id"]),
                symbol=str(item["symbol"]),
                decision_date=str(item["decision_date"]),
                available_date=(
                    str(item["available_date"])
                    if item.get("available_date") is not None
                    else None
                ),
                source_version=str(item["source_version"]),
                status=str(item["status"]),
                diagnostics=tuple(str(value) for value in diagnostics) if isinstance(diagnostics, list) else (),
                raw_payload={},
            )
        )
    return tuple(observations)


def _ml_shadow_from_replay(replay_summary: Mapping[str, object]) -> dict[str, object]:
    value = replay_summary.get("ml_shadow")
    if isinstance(value, Mapping):
        return {
            "status": "training_context_required",
            "dataset_id": str(value.get("dataset_id") or "unverified_input"),
            "total_rows": 0,
            "accepted_rows": 0,
            "shadow_only": True,
            "production_action_allowed": False,
            "disclosure": "Supplied ML status is untrusted until manifest and boundary inputs are validated.",
        }
    return {
        "status": "insufficient_sample",
        "dataset_id": "not_provided",
        "total_rows": 0,
        "accepted_rows": 0,
        "shadow_only": True,
        "production_action_allowed": False,
        "disclosure": "No ML shadow projection was supplied by replay input; no model was trained or promoted.",
    }


def _rehearsal_blockers(report: Any) -> tuple[str, ...]:
    blockers: list[str] = []
    for metric in report.coverage_metrics:
        for state, count in (
            ("degraded", metric.degraded_count),
            ("missing", metric.missing_count),
            ("future_blocked", metric.future_blocked_count),
            ("immature_label", metric.immature_label_count),
        ):
            if count:
                blockers.append(f"coverage_{state}:{metric.source_id}={count}")
    for artifact in report.artifacts:
        if artifact.current_status == "future_blocked":
            blockers.append(f"future_available_date:{artifact.artifact_id}")
        blockers.extend(artifact.diagnostics)
    return tuple(sorted(set(blockers)))


def _render_markdown(report: Mapping[str, object], handoff: Mapping[str, object]) -> str:
    blockers = cast(list[str], report["blockers"])
    execution = cast(Mapping[str, object], report["execution"])
    injection = cast(Mapping[str, object], report["injection"])
    blocker_lines = "\n".join(f"- `{item}`" for item in blockers) if blockers else "- None"
    return (
        "# Controlled Evidence Rehearsal Report\n\n"
        "## Status\n\n"
        f"- rehearsal_status: `{report['status']}`\n"
        f"- mode: `{execution['mode']}`\n"
        f"- injection: `{injection['name']}`\n\n"
        "## Safety Boundary\n\n"
        f"- Source DB opened read-only: `{execution['source_db_opened']}`.\n"
        f"- Isolated working copy created: `{execution['working_copy_created']}`.\n"
        "- No production DB write, scheduler, broker, Advice, or promotion action was invoked.\n"
        "- This is engineering/replay rehearsal output, never forward evidence.\n\n"
        "## Blockers\n\n"
        f"{blocker_lines}\n\n"
        "## Forward Handoff\n\n"
        f"- status: `{handoff['status']}`\n"
        f"- owner: `{handoff['owner']}`\n"
        f"- completion_rule: {handoff['completion_rule']}\n"
    )


def _write_package(output_root: Path, report: Mapping[str, object], handoff: Mapping[str, object]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "rehearsal-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_root / "rehearsal-report.md").write_text(
        _render_markdown(report, handoff), encoding="utf-8"
    )
    (output_root / "forward-handoff.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _orchestrated_cli_report(
    execution_report: EvidenceRehearsalExecutionReport,
    scenario: EvidenceRehearsalScenario,
    injection_name: str | None,
) -> tuple[dict[str, object], dict[str, object]]:
    execution_payload = execution_report.to_dict()
    injection = {
        "name": injection_name,
        "status": "degraded" if injection_name is not None else execution_report.status,
        **dict(execution_report.fault_diagnostics),
    }
    report = {
        "contract_version": 2,
        "status": execution_report.status,
        "scenario": scenario.to_dict(),
        "execution": {
            "mode": execution_report.execution_mode,
            "source_db_opened": execution_report.source_db_opened,
            "source_db_write_performed": execution_report.source_db_write_performed,
            "working_copy_created": execution_report.working_copy_created,
            "working_copy_write_performed": execution_report.working_copy_write_performed,
            "production_db_write_performed": False,
            "db_write_performed": False,
            "scheduler_invoked": False,
            "broker_invoked": False,
            "advice_invoked": False,
            "promotion_invoked": False,
            "service_call_facts": dict(execution_report.service_call_facts),
            "adapter_statuses": [list(item) for item in execution_report.adapter_statuses],
        },
        "source_snapshot": dict(execution_report.source_snapshot),
        "semantic_fingerprint": execution_report.semantic_fingerprint,
        "lineage": {
            "status": execution_report.lineage_status,
            "artifact_dag": {
                key: list(value) for key, value in execution_report.artifact_dag.items()
            },
            "artifact_hashes": dict(execution_report.artifact_hashes),
        },
        "formal_product_closeout": False,
        "production_actions_allowed": False,
        "injection": injection,
        "blockers": list(execution_report.blockers),
        "rehearsal_report": execution_payload,
        "coverage_metrics": [
            metric.to_dict() for metric in execution_report.coverage_metrics
        ],
        "p0_source_shadow": dict(execution_report.p0_source_shadow),
        "ml_shadow": execution_payload["ml_shadow"],
        "historical_replay_artifacts": [
            artifact.to_dict()
            for artifact in execution_report.historical_replay_artifacts
        ],
    }
    handoff = {
        "contract_version": 2,
        "status": "forward_handoff_pending",
        "scenario_id": scenario.scenario_id,
        "decision_date": scenario.decision_date,
        "rehearsal_status": execution_report.status,
        "blockers": list(execution_report.blockers),
        "owner": "human_evidence_operations_owner",
        "completion_rule": (
            "Real-time evidence, required approvals, and explicit manual review "
            "are required; this CLI cannot complete or promote them."
        ),
        "required_manual_actions": [
            "Validate real-time source availability and licence terms.",
            "Review data quality, PIT availability, and label maturity.",
            "Approve any scheduler, broker, Advice, or promotion action outside this rehearsal.",
        ],
        "production_actions_allowed": False,
        "prohibited_actions": [
            "production_database_write",
            "scheduler_enablement",
            "broker_invocation",
            "advice_invocation",
            "model_or_strategy_promotion",
        ],
    }
    return report, handoff


def _replay_decision_date(payload: Mapping[str, object]) -> str | None:
    days = payload.get("days")
    if not isinstance(days, list):
        return None
    values = [
        str(item.get("decision_date"))
        for item in days
        if isinstance(item, Mapping) and isinstance(item.get("decision_date"), str)
    ]
    return max(values) if values else None


def _semantic_fingerprint(
    *,
    scenario: EvidenceRehearsalScenario,
    replay_summary: Mapping[str, object],
    source_snapshot: EvidenceRehearsalSourceSnapshot | None,
    coherence_blocker: str | None,
) -> str:
    payload = {
        "scenario_id": scenario.scenario_id,
        "decision_date": scenario.decision_date,
        "replay_run_id": replay_summary.get("replay_run_id"),
        "replay_decision_date": _replay_decision_date(replay_summary),
        "schema_fingerprint": (
            source_snapshot.schema_fingerprint if source_snapshot is not None else None
        ),
        "table_row_counts": (
            dict(source_snapshot.table_row_counts) if source_snapshot is not None else {}
        ),
        "coherence_blocker": coherence_blocker,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_paths(args.source_db, args.working_copy_db, args.output_root)
        scenario = _scenario_from_payload(
            _read_json_mapping(args.scenario, "scenario"),
            source_db=args.source_db,
            working_copy_db=args.working_copy_db,
        )
        replay_summary = _read_json_mapping(args.replay_summary, "replay summary")
        replay_decision_date = _replay_decision_date(replay_summary)
        coherence_blocker = (
            "scenario_replay_decision_date_mismatch"
            if replay_decision_date is not None
            and replay_decision_date != scenario.decision_date
            else None
        )
        if args.inject_failure is not None and args.execution_mode != "working_copy_e2e":
            raise ValueError("failure injection requires working_copy_e2e")
        if args.execution_mode == "working_copy_e2e" and coherence_blocker is None:
            request = EvidenceRehearsalExecutionRequest(
                scenario=scenario,
                config=TWStockConfig(
                    output_root=args.working_copy_db.parent / "runtime-output"
                ),
                source_db_path=args.source_db,
                working_copy_db_path=args.working_copy_db,
                start_date=args.start_date or scenario.decision_date,
                end_date=args.end_date or scenario.decision_date,
                overwrite_working_copy=args.overwrite_working_copy,
                p0_observations=_p0_observations_from_replay(replay_summary),
                ml_provider=(
                    JsonMLRehearsalEvidenceProvider(args.ml_evidence_root)
                    if args.ml_evidence_root is not None
                    else None
                ),
            )
            if args.inject_failure is not None:
                request = EvidenceRehearsalFaultInjector().inject(
                    request,
                    args.inject_failure,
                )
            execution_report = EvidenceRehearsalOrchestrator().run(request)
            report, handoff = _orchestrated_cli_report(
                execution_report,
                scenario,
                args.inject_failure,
            )
        else:
            report, handoff = _build_report(
                scenario,
                replay_summary,
                None,
                execution_mode=args.execution_mode,
                coherence_blocker=coherence_blocker,
            )
        _write_package(args.output_root, report, handoff)
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"status": report["status"], "output_root": str(args.output_root)}, ensure_ascii=False))
    return 2 if coherence_blocker is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
