"""Explicit manual entrypoint for a TEMP or explicitly named shadow ledger.

It intentionally has no scheduler hook and never reads or writes the formal
market database.  A confirmed invocation can initialise only an isolated
sidecar ledger; it cannot manufacture a decision snapshot or an observed day.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.evidence_outcome_revision_repository import EvidenceOutcomeRevisionRepository
from app_module.external_evidence_contracts import ExternalEvidenceDecisionSnapshot


CONFIRMATION = "append-external-evidence"


def _default_output_root() -> Path:
    return Path(tempfile.gettempdir()) / "external-evidence-shadow"


def _is_allowed_shadow_root(path: Path) -> bool:
    return "shadow" in path.name.lower()


def _is_allowed_db_path(path: Path, output_root: Path) -> bool:
    resolved = path.resolve()
    return resolved.is_relative_to(output_root.resolve()) or resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual shadow-only external evidence capture")
    parser.add_argument("--db", required=True, help="isolated evidence sidecar SQLite path")
    parser.add_argument("--output-root", default=str(_default_output_root()), help="TEMP or explicit shadow output root")
    parser.add_argument("--confirm", default="", help=f"required exact value: {CONFIRMATION}")
    parser.add_argument("--snapshot-json", help="manual_observed decision artifact; optional and never inferred")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    output_root = Path(args.output_root)
    if not _is_allowed_shadow_root(output_root):
        print(json.dumps({"status": "rejected", "reason": "output_root_must_be_temp_or_shadow"}, sort_keys=True))
        return 2
    if not _is_allowed_db_path(db_path, output_root):
        print(json.dumps({"status": "rejected", "reason": "formal_market_db_path_rejected"}, sort_keys=True))
        return 2

    confirmed = args.confirm == CONFIRMATION
    snapshot: ExternalEvidenceDecisionSnapshot | None = None
    if args.snapshot_json:
        try:
            artifact = json.loads(Path(args.snapshot_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "rejected", "reason": "snapshot_artifact_unreadable"}, sort_keys=True))
            return 2
        if artifact.get("capture_kind") != "manual_observed":
            print(json.dumps({"status": "rejected", "reason": "capture_kind_must_be_manual_observed"}, sort_keys=True))
            return 2
        parent_artifact_ids = artifact.get("parent_artifact_ids")
        if not isinstance(parent_artifact_ids, list) or not any(
            isinstance(item, str) and ":sha256:" in item
            for item in parent_artifact_ids
        ):
            print(json.dumps({"status": "rejected", "reason": "manual_observed_decision_output_lineage_missing"}, sort_keys=True))
            return 2
        try:
            snapshot = ExternalEvidenceDecisionSnapshot.create(**artifact)
        except (TypeError, ValueError) as exc:
            print(json.dumps({"status": "rejected", "reason": f"invalid_snapshot:{exc}"}, sort_keys=True))
            return 2
    if confirmed:
        output_root.mkdir(parents=True, exist_ok=True)
        repository = EvidenceOutcomeRevisionRepository(db_path)
        if snapshot is not None:
            repository.append_snapshot(snapshot)
    print(
        json.dumps(
            {
                "status": "manual_shadow_ready",
                "write_performed": confirmed,
                "formal_oos_allowed": False,
                "production_blend_alpha_bp": 0,
                "observed_decisions_created": 1 if confirmed and snapshot is not None else 0,
            },
            sort_keys=True,
        )
    )
    print(f"write_performed={'true' if confirmed else 'false'}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
