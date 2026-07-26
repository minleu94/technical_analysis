"""Read-only preflight for the Terra formal-evidence clock.

This command deliberately cannot bind a holdout, create an observed snapshot,
or write an evidence ledger.  It turns the explicit governance checks into one
auditable report so an operator does not mistake a development artifact for a
formal-clock credit.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot
from development_module.governance import load_development_data_usage_decision


def _read_registry(
    path: Path, holdout_start: str, decision_sha256: str, decision_effective_at: str
) -> tuple[str, str | None, str | None]:
    """Validate an owner-attested binding without inferring a trading session."""
    if not path.exists():
        return "missing", "consumption_registry_missing", None
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unreadable", "consumption_registry_unreadable", None
    if any(not isinstance(record, dict) for record in records):
        return "invalid", "consumption_registry_invalid", None
    matching = [record for record in records if record.get("development_holdout_start") == holdout_start]
    if not matching:
        return "present_without_binding", "holdout_binding_missing", None
    bindings = [record for record in matching if record.get("record_type") == "formal_holdout_binding"]
    if len(bindings) != 1:
        return "invalid", "holdout_binding_must_be_exactly_one", None
    binding = bindings[0]
    required = ("owner_id", "binding_authorization", "bound_at")
    if binding.get("schema_version") != "holdout-consumption-registry.v2":
        return "invalid", "holdout_binding_schema_invalid", None
    if any(not isinstance(binding.get(field), str) or not binding[field].strip() for field in required):
        return "invalid", "holdout_binding_owner_attestation_missing", None
    try:
        bound_at = datetime.fromisoformat(str(binding["bound_at"]).replace("Z", "+00:00"))
    except ValueError:
        return "invalid", "holdout_binding_timestamp_invalid", None
    if bound_at.tzinfo is None:
        return "invalid", "holdout_binding_timestamp_invalid", None
    if bound_at < datetime.fromisoformat(decision_effective_at.replace("Z", "+00:00")):
        return "invalid", "holdout_binding_precedes_owner_decision", None
    try:
        formal_session = date.fromisoformat(str(binding.get("formal_trading_session", "")))
    except ValueError:
        return "invalid", "formal_trading_session_invalid", None
    if formal_session < bound_at.date():
        return "invalid", "formal_trading_session_precedes_binding", None
    if binding.get("owner_decision_sha256") != decision_sha256:
        return "invalid", "holdout_binding_decision_hash_mismatch", None
    if binding.get("unconsumed_before_binding") is not True:
        return "invalid", "holdout_binding_unconsumed_attestation_missing", None
    if binding.get("formal_oos_allowed") is not False or binding.get("production_blend_alpha_bp") != 0:
        return "invalid", "holdout_binding_safety_flags_invalid", None
    return "owner_attested_binding_valid", None, formal_session.isoformat()


def _inspect_snapshot(path: Path | None) -> tuple[str, str | None, str | None]:
    if path is None:
        return "missing", "manual_observed_snapshot_missing", None
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "unreadable", "manual_observed_snapshot_unreadable", None
    if not isinstance(payload, dict) or payload.get("capture_kind") != "manual_observed":
        return "invalid", "capture_kind_must_be_manual_observed", None
    payload.pop("snapshot_id", None)
    try:
        ExternalEvidenceDecisionSnapshot.create(**payload)
    except (TypeError, ValueError):
        return "invalid", "manual_observed_snapshot_contract_invalid", None
    return "structurally_valid", None, str(payload["decision_timestamp"])[:10]


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
        "shadow_computation_readiness": True,
        "formal_blockers": [],
        "optional_shadow_blockers": [],
        "shadow_diagnostics": [
            "fubon_shadow_lane_optional_does_not_block_rule_only_formal_clock"
        ],
        "blockers": [],
    }
    formal_blockers: list[str] = []
    optional_shadow_blockers: list[str] = []
    shadow_diagnostics: list[str] = [
        "fubon_shadow_lane_optional_does_not_block_rule_only_formal_clock"
    ]

    try:
        decision = load_development_data_usage_decision(
            decision_path, output_root=root, require_unconsumed=False
        )
    except (OSError, ValueError):
        formal_blockers.append("owner_decision_missing_or_invalid")
        report["snapshot"] = _inspect_snapshot(snapshot_json)[0]
    else:
        report["owner_decision"] = "valid"
        report["holdout_start"] = decision.new_holdout_start
        report["owner_decision_sha256"] = decision.decision_record_sha256
        registry_state, registry_blocker, formal_session = _read_registry(
            root / "governance" / "HoldoutConsumptionRegistry.jsonl",
            decision.new_holdout_start,
            decision.decision_record_sha256,
            decision.effective_timestamp_utc,
        )
        report["consumption_registry"] = registry_state
        report["formal_trading_session"] = formal_session
        if registry_blocker:
            formal_blockers.append(registry_blocker)
        snapshot_state, snapshot_blocker, snapshot_date = _inspect_snapshot(snapshot_json)
        report["snapshot"] = snapshot_state
        if snapshot_blocker:
            formal_blockers.append(snapshot_blocker)
        if snapshot_state == "structurally_valid" and formal_session is not None and snapshot_date != formal_session:
            formal_blockers.append("manual_observed_session_mismatch")
        report["can_capture_shadow_snapshot"] = (
            registry_state == "owner_attested_binding_valid" and snapshot_state == "structurally_valid"
            and snapshot_date == formal_session
        )
    if report["consumption_registry"] != "owner_attested_binding_valid":
        formal_blockers.append("holdout_binding_requires_owner_authority")

    # A valid snapshot declares its typed lineage through source_versions.
    # Free-form text is never treated as source usage.
    snapshot_path = snapshot_json
    if snapshot_path is not None and snapshot_path.exists():
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if _snapshot_references_fubon(data):
                formal_blockers.append("fubon_source_not_accepted_for_formal_clock")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass

    report["formal_blockers"] = formal_blockers
    report["optional_shadow_blockers"] = optional_shadow_blockers
    report["shadow_diagnostics"] = shadow_diagnostics
    report["shadow_computation_readiness"] = True
    report["formal_readiness"] = False
    report["blockers"] = formal_blockers
    return report


def _snapshot_references_fubon(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    source_versions = payload.get("source_versions")
    if not isinstance(source_versions, dict):
        return False
    fubon_source_ids = {
        "fubon.marketdata",
        "microstructure.disposition_stock",
        "microstructure.periodic_call_auction",
        "microstructure.suspended_halt_resume",
        "microstructure.limit_lock",
        "corporate_action.ex_dividend_timeline",
        "corporate_action.reduction_split_par_value",
    }
    return any(str(source_id) in fubon_source_ids for source_id in source_versions)


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
