"""Read-only preflight for the Terra formal-evidence clock.

This command deliberately cannot bind a holdout, create an observed snapshot,
or write an evidence ledger.  It turns the explicit governance checks into one
auditable report so an operator does not mistake a development artifact for a
formal-clock credit.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot
from development_module.governance import load_development_data_usage_decision


def _read_registry(path: Path, holdout_start: str) -> tuple[str, str | None]:
    """Return only the registry state; never infer a holdout binding."""
    if not path.exists():
        return "missing", "consumption_registry_missing"
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unreadable", "consumption_registry_unreadable"
    if any(not isinstance(record, dict) for record in records):
        return "invalid", "consumption_registry_invalid"
    if any(record.get("trading_session", record.get("holdout_start")) == holdout_start for record in records):
        return "consumed", "holdout_already_consumed"
    return "present_unconsumed", None


def _inspect_snapshot(path: Path | None) -> tuple[str, str | None]:
    if path is None:
        return "missing", "manual_observed_snapshot_missing"
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unreadable", "manual_observed_snapshot_unreadable"
    if not isinstance(payload, dict) or payload.get("capture_kind") != "manual_observed":
        return "invalid", "capture_kind_must_be_manual_observed"
    payload.pop("snapshot_id", None)
    try:
        ExternalEvidenceDecisionSnapshot.create(**payload)
    except (TypeError, ValueError):
        return "invalid", "manual_observed_snapshot_contract_invalid"
    return "structurally_valid", None


def inspect_readiness(output_root: Path, snapshot_json: Path | None = None) -> dict[str, object]:
    """Produce a fail-closed report for an operator-provided artifact only."""
    root = output_root.expanduser().resolve()
    decision_path = root / "governance" / "DevelopmentDataUsageDecision.jsonl"
    report: dict[str, object] = {
        "schema_version": "formal-clock-readiness.v1",
        "output_root": str(root),
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "rule_only_formal_path": True,
        "owner_decision": "missing",
        "consumption_registry": "not_checked",
        "snapshot": "not_checked",
        "can_capture_shadow_snapshot": False,
        "formal_readiness": False,
        "blockers": [],
    }
    blockers: list[str] = []
    try:
        decision = load_development_data_usage_decision(decision_path, output_root=root)
    except (OSError, ValueError):
        blockers.append("owner_decision_missing_or_invalid")
        report["snapshot"] = _inspect_snapshot(snapshot_json)[0]
    else:
        report["owner_decision"] = "valid"
        report["holdout_start"] = decision.new_holdout_start
        report["owner_decision_sha256"] = decision.decision_record_sha256
        registry_state, registry_blocker = _read_registry(
            root / "governance" / "HoldoutConsumptionRegistry.jsonl", decision.new_holdout_start
        )
        report["consumption_registry"] = registry_state
        if registry_blocker:
            blockers.append(registry_blocker)
        snapshot_state, snapshot_blocker = _inspect_snapshot(snapshot_json)
        report["snapshot"] = snapshot_state
        if snapshot_blocker:
            blockers.append(snapshot_blocker)
        report["can_capture_shadow_snapshot"] = (
            registry_state == "present_unconsumed" and snapshot_state == "structurally_valid"
        )
    blockers.append("holdout_binding_requires_owner_authority")
    blockers.append("source_acceptance_owner_review_required")
    report["blockers"] = blockers
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only formal clock readiness inspection")
    parser.add_argument("--development-output-root", required=True)
    parser.add_argument("--snapshot-json", help="existing decision-time manual_observed artifact; never inferred")
    args = parser.parse_args(argv)
    report = inspect_readiness(Path(args.development_output_root), Path(args.snapshot_json) if args.snapshot_json else None)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
