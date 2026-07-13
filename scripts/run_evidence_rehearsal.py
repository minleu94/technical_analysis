"""Run a controlled, dry/read-only evidence rehearsal and emit handoff reports."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.artifact_lineage_verifier import ArtifactIdentity  # noqa: E402
from app_module.evidence_rehearsal_adapters import HistoricalReplayRehearsalAdapter  # noqa: E402
from app_module.evidence_rehearsal_dtos import EvidenceRehearsalScenario  # noqa: E402
from app_module.evidence_rehearsal_service import EvidenceRehearsalService  # noqa: E402
from data_module.config import TWStockConfig  # noqa: E402


_FAILURE_BLOCKERS = {
    "missing_day": "missing_required_adapter_output:source",
    "source_outage": "adapter_failure:source:source_outage",
    "future_available_date": "future_available_date:source-data",
    "schema_missing": "missing_field:source-data:source_version",
    "immature_label": "immature_label:ml-shadow",
}
_PRODUCTION_MARKERS = frozenset({"prod", "production"})
_ADAPTER_CHAIN = (
    ("source", "source-data", "daily_governed_data", ()),
    ("market", "market-context", "market_context", ("source-data",)),
    ("replay", "replay-recommendation", "recommendation", ("market-context",)),
    ("advice", "rehearsal-advice-projection", "bounded_advice", ("replay-recommendation",)),
    ("paper", "paper-projection", "paper_portfolio", ("rehearsal-advice-projection",)),
    ("health", "health-projection", "position_health", ("paper-projection",)),
    ("evidence", "evidence-projection", "evidence_event", ("health-projection",)),
    ("outcome", "outcome-projection", "forward_outcome", ("evidence-projection",)),
    ("weekly", "weekly-projection", "weekly_review", ("outcome-projection",)),
    ("signal", "signal-projection", "signal_effectiveness", ("weekly-projection",)),
    ("ml", "ml-shadow", "ml_shadow_prediction", ("signal-projection",)),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a controlled evidence rehearsal in permanent dry/read-only mode."
    )
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--working-copy-db", type=Path, required=True)
    parser.add_argument("--replay-summary", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
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
    for label, path in (
        ("source DB", source_db),
        ("working-copy DB", working_copy_db),
        ("output root", output_root),
    ):
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


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _adapter_outputs(scenario: EvidenceRehearsalScenario) -> dict[str, tuple[ArtifactIdentity | BaseException, ...]]:
    outputs: dict[str, tuple[ArtifactIdentity | BaseException, ...]] = {}
    for adapter_name, artifact_id, artifact_type, parents in _ADAPTER_CHAIN:
        outputs[adapter_name] = (
            ArtifactIdentity(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                run_id=f"rehearsal:{scenario.scenario_id}",
                decision_date=scenario.decision_date,
                as_of_date=scenario.decision_date,
                available_date=scenario.decision_date,
                source_id="engineering.rehearsal",
                source_version="v1",
                data_quality="observed",
                missing_state="complete",
                strategy_version="rehearsal-rule-v1",
                policy_version="rehearsal-policy-v1",
                model_version="shadow-v1",
                parent_artifact_ids=parents,
                evidence_tier=scenario.tier,
                current_status="rehearsal_only",
                content_hash=_stable_hash(f"{scenario.scenario_id}:{artifact_id}"),
                rollback_reference="rehearsal:dry-read-only",
            ),
        )
    return outputs


def _inject_failure(
    outputs: dict[str, tuple[ArtifactIdentity | BaseException, ...]],
    name: str | None,
    decision_date: str,
) -> tuple[dict[str, tuple[ArtifactIdentity | BaseException, ...]], str | None]:
    if name is None:
        return outputs, None
    if name == "missing_day":
        outputs["source"] = ()
    elif name == "source_outage":
        outputs["source"] = (RuntimeError("source_outage"),)
    elif name == "future_available_date":
        source = outputs["source"][0]
        if isinstance(source, ArtifactIdentity):
            future_date = (date.fromisoformat(decision_date) + timedelta(days=1)).isoformat()
            outputs["source"] = (replace(source, available_date=future_date),)
    elif name == "schema_missing":
        source = outputs["source"][0]
        if isinstance(source, ArtifactIdentity):
            outputs["source"] = (replace(source, source_version=""),)
    elif name == "immature_label":
        return outputs, _FAILURE_BLOCKERS[name]
    return outputs, None


def _service_payload(report: Any) -> dict[str, object]:
    return {
        "status": report.status,
        "ordered_artifact_ids": list(report.ordered_artifact_ids),
        "blockers": list(report.blockers),
        "diagnostics": list(report.diagnostics),
        "artifact_dag": {key: list(value) for key, value in report.artifact_dag.items()},
        "artifact_hashes": dict(report.artifact_hashes),
        "artifact_count": report.artifact_count,
        "formal_product_closeout": report.formal_product_closeout,
        "production_actions_allowed": report.production_actions_allowed,
    }


def _build_report(
    scenario: EvidenceRehearsalScenario,
    replay_summary: Mapping[str, object],
    injection_name: str | None,
) -> tuple[dict[str, object], dict[str, object]]:
    replay_artifacts = HistoricalReplayRehearsalAdapter().project(
        replay_summary,
        decision_date=scenario.decision_date,
        rollback_reference="rehearsal:dry-read-only",
    )
    outputs, additional_blocker = _inject_failure(
        _adapter_outputs(scenario), injection_name, scenario.decision_date
    )
    service_report = EvidenceRehearsalService().run(scenario, outputs)
    blockers = list(service_report.blockers)
    if additional_blocker is not None:
        blockers.append(additional_blocker)
    blockers = list(dict.fromkeys(blockers))
    status = "degraded" if blockers else service_report.status
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
        "mode": "dry_read_only",
        "source_db_opened": False,
        "working_copy_created": False,
        "db_write_performed": False,
        "scheduler_invoked": False,
        "broker_invoked": False,
        "advice_invoked": False,
        "promotion_invoked": False,
    }
    report = {
        "contract_version": 1,
        "status": status,
        "scenario": scenario.to_dict(),
        "execution": execution,
        "injection": injection,
        "blockers": blockers,
        "service": _service_payload(service_report),
        "historical_replay_artifacts": [artifact.to_dict() for artifact in replay_artifacts],
    }
    handoff = {
        "contract_version": 1,
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
        "- The source DB was not opened and the working-copy DB was not created.\n"
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
        report, handoff = _build_report(
            scenario,
            _read_json_mapping(args.replay_summary, "replay summary"),
            args.inject_failure,
        )
        _write_package(args.output_root, report, handoff)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps({"status": report["status"], "output_root": str(args.output_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
