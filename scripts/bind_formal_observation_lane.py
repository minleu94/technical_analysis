"""Append one owner-approved forward observation lane binding.

This command writes only the explicit TEMP/development governance registry.  It
does not capture a snapshot, consume a session, grant formal credit, or touch a
market/formal database.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from development_module.formal_observation_lane import (
    FormalObservationLaneDecision,
    load_formal_observation_lane_decision,
)
from development_module.governance import load_development_data_usage_decision


def build_binding(
    *,
    decision: FormalObservationLaneDecision,
    development_holdout_start: str,
    development_decision_sha256: str,
    formal_trading_session: str,
    bound_at: str,
) -> dict[str, Any]:
    session = date.fromisoformat(formal_trading_session)
    bound = datetime.fromisoformat(bound_at.replace("Z", "+00:00"))
    if bound.tzinfo is None:
        raise ValueError("bound_at must include a timezone")
    decided = datetime.fromisoformat(decision.decided_at.replace("Z", "+00:00"))
    if bound < decided:
        raise ValueError("binding cannot precede the owner decision")
    if session.isoformat() != decision.first_eligible_session:
        raise ValueError("formal session must equal the owner-approved first eligible session")
    return {
        "schema_version": "holdout-consumption-registry.v3",
        "record_type": "formal_observation_lane_binding",
        "holdout_id": decision.holdout_id,
        "development_holdout_start": development_holdout_start,
        "formal_trading_session": session.isoformat(),
        "owner_id": decision.owner_id,
        "binding_authorization": decision.decision_id,
        "bound_at": bound.isoformat(),
        "lane_decision_sha256": decision.content_hash,
        "development_decision_sha256": development_decision_sha256,
        "unconsumed_before_binding": True,
        "rule_only_formal_path": True,
        "no_retroactive_credit": True,
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
    }


def append_binding(
    *,
    output_root: Path,
    decision_path: Path,
    formal_trading_session: str,
    bound_at: str,
) -> dict[str, Any]:
    root = _safe_output_root(output_root)
    resolved_decision_path = decision_path.expanduser().resolve()
    governance_root = (root / "governance").resolve()
    if resolved_decision_path.parent != governance_root:
        raise ValueError(
            "formal observation lane decision must be inside output-root governance"
        )
    decision = load_formal_observation_lane_decision(resolved_decision_path)
    development_decision = load_development_data_usage_decision(
        root / "governance" / "DevelopmentDataUsageDecision.jsonl",
        output_root=root,
        require_unconsumed=False,
    )
    registry_path = root / "governance" / "HoldoutConsumptionRegistry.jsonl"
    records = _read_records(registry_path)
    if any(record.get("holdout_id") == decision.holdout_id for record in records):
        raise ValueError("holdout_id already exists in the consumption registry")
    if any(
        record.get("formal_trading_session") == formal_trading_session
        for record in records
    ):
        raise ValueError("formal trading session is already present in the registry")
    binding = build_binding(
        decision=decision,
        development_holdout_start=development_decision.new_holdout_start,
        development_decision_sha256=development_decision.decision_record_sha256,
        formal_trading_session=formal_trading_session,
        bound_at=bound_at,
    )
    with registry_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(binding, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return binding


def _safe_output_root(path: Path) -> Path:
    root = path.expanduser().resolve()
    repo = PROJECT_ROOT.resolve()
    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    if root == repo or root.is_relative_to(repo):
        raise ValueError("development output root cannot be inside the repository")
    if root == data_root or root.is_relative_to(data_root):
        raise ValueError("development output root cannot be inside DATA_ROOT")
    if root.name != "technical_analysis_development_output":
        raise ValueError("unexpected development output root")
    return root


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("consumption registry contains a non-object record")
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind one owner-approved Rule-only formal observation lane"
    )
    parser.add_argument("--development-output-root", required=True, type=Path)
    parser.add_argument("--decision-json", required=True, type=Path)
    parser.add_argument("--formal-trading-session", required=True)
    parser.add_argument("--bound-at", required=True)
    args = parser.parse_args(argv)
    try:
        binding = append_binding(
            output_root=args.development_output_root,
            decision_path=args.decision_json,
            formal_trading_session=args.formal_trading_session,
            bound_at=args.bound_at,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "bound", "binding": binding}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
