"""Explicit synthetic teacher provenance for isolated ML training tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


_REQUIRED_TEACHER_BLOCKERS = {
    "formal_rule_champion_snapshot_history_missing_formal_replay_blocked",
    "pit_sector_membership_missing_teacher_new_positions_disabled",
    "portfolio_ledger_missing_cash_only_fallback_turnover_and_cooldown_not_learned",
}


def _payload_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _spread(total: int, count: int, *, minimum_one: bool = False) -> list[int]:
    if count <= 0:
        return []
    if minimum_one and total < count:
        raise AssertionError("synthetic teacher fixture needs one eligible row per date")
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def attach_synthetic_teacher_provenance(
    manifest_path: Path,
    *,
    fixture_root: Path,
) -> str:
    """Make a generated test manifest explicitly eligible without weakening runtime gates."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    diagnostics = dict(manifest["teacher_target_diagnostics"])
    decision_count = int(diagnostics["decision_date_count"])
    input_count = max(int(diagnostics["input_candidate_count"]), decision_count)
    diagnostics.update(
        {
            "input_candidate_count": input_count,
            "eligible_candidate_count": input_count,
            "unknown_sector_candidate_count": 0,
            "teacher_incomplete_decision_count": 0,
            "non_cash_target_decision_count": 0,
            "cash_only_target_decision_count": decision_count,
        }
    )

    start = date(2000, 1, 1)
    decision_dates = [
        (start + timedelta(days=index)).isoformat()
        for index in range(decision_count)
    ]
    decision_cutoffs: dict[str, str] = {
        value: datetime.combine(
            date.fromisoformat(value),
            time(8, 30),
            tzinfo=timezone(timedelta(hours=8)),
        ).isoformat()
        for value in decision_dates
    }
    candidate_counts = _spread(input_count, decision_count, minimum_one=True)
    decision_rows: list[dict[str, Any]] = [
        {
            "decision_date": decision_date,
            "candidate_row_count": candidate_count,
            "eligible_candidate_count": candidate_count,
            "complete_candidate_set": True,
            "target_mode": "cash_only",
        }
        for decision_date, candidate_count in zip(decision_dates, candidate_counts)
    ]

    sources: dict[str, object] = {}
    for index, source_name in enumerate(
        (
            "pit_sector_membership",
            "causal_non_cash_portfolio_ledger",
            "formal_rule_champion_snapshot_history",
        )
    ):
        source_schema_version = f"{source_name}.synthetic-test.v1"
        source_identity = {
            "source_name": source_name,
            "source_schema_version": source_schema_version,
            "dataset_id": f"synthetic-test-fixture-{index}",
            "source_nature": "synthetic_test_fixture",
        }
        source_identity_hash = _payload_hash(source_identity)
        source_manifest = {
            "source_name": source_name,
            "source_schema_version": source_schema_version,
            "source_identity_hash": source_identity_hash,
            "storage_mode": "read_only",
            "decision_dates": decision_dates,
            "decision_cutoffs": decision_cutoffs,
            "row_count": decision_count,
        }
        source_manifest["manifest_hash"] = _payload_hash(source_manifest)
        source_manifest_path = fixture_root / f"{source_name}.manifest.json"
        _write_json(source_manifest_path, source_manifest)

        receipt_rows = [
            {
                **row,
                "available_at": decision_cutoffs[row["decision_date"]].replace(
                    "08:30:00", "08:00:00"
                ),
            }
            for row in decision_rows
        ]
        receipt = {
            "schema_version": "allocation-teacher-input-readback.v1",
            "source_name": source_name,
            "source_schema_version": source_schema_version,
            "source_identity": source_identity,
            "source_identity_hash": source_identity_hash,
            "source_manifest_hash": source_manifest["manifest_hash"],
            "decision_dates": decision_dates,
            "decision_cutoffs": decision_cutoffs,
            "rows": receipt_rows,
            "rows_hash": _payload_hash(receipt_rows),
            "custody": {
                "access_mode": "read_only",
                "query_only": True,
                "write_performed": False,
            },
        }
        receipt["receipt_hash"] = _payload_hash(receipt)
        readback_path = fixture_root / f"{source_name}.readback.json"
        _write_json(readback_path, receipt)
        sources[source_name] = {
            "readback_path": str(readback_path.resolve()),
            "readback_file_sha256": _file_hash(readback_path),
            "readback_verified": True,
            "source_manifest_path": str(source_manifest_path.resolve()),
            "source_manifest_file_sha256": _file_hash(source_manifest_path),
            "source_manifest_hash": source_manifest["manifest_hash"],
            "source_identity_hash": source_identity_hash,
            "source_schema_version": source_schema_version,
            "source_row_count": decision_count,
            "covered_decision_dates": decision_dates,
            "read_only": True,
            "available_before_decision": True,
        }

    manifest["teacher_target_diagnostics"] = diagnostics
    manifest["teacher_input_provenance"] = {
        "schema_version": "allocation-teacher-input-provenance.v1",
        "decision_dates": decision_dates,
        "decision_date_count": decision_count,
        "decision_cutoffs": decision_cutoffs,
        "input_candidate_count": input_count,
        "eligible_candidate_count": input_count,
        "decision_rows": decision_rows,
        "sources": sources,
        "source_nature": "synthetic_test_fixture",
    }
    manifest["assembly_blockers"] = [
        blocker
        for blocker in manifest.get("assembly_blockers", [])
        if blocker not in _REQUIRED_TEACHER_BLOCKERS
    ]
    policy = dict(manifest.get("portfolio_state_policy") or {})
    policy["cash_only_fallback"] = False
    policy["test_fixture_override"] = "explicit_synthetic_teacher_provenance"
    manifest["portfolio_state_policy"] = policy
    manifest.pop("manifest_hash", None)
    manifest["manifest_hash"] = _payload_hash(manifest)
    _write_json(manifest_path, manifest)
    return str(manifest["manifest_hash"])
