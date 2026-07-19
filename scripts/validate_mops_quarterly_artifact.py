"""Validate a captured MOPS quarterly-announcement artifact for PIT staging only."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


REQUIRED_ARTIFACT_FIELDS = {"source_id", "source_version", "captured_at", "rows"}
REQUIRED_ROW_FIELDS = {
    "stock_code", "statement_type", "statement_scope", "period", "period_end",
    "announcement_date", "available_date", "revision", "content_hash",
}


def validate_artifact(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or not REQUIRED_ARTIFACT_FIELDS.issubset(payload):
        raise ValueError("mops artifact missing required provenance fields")
    if payload["source_id"] != "mops.statement.publication":
        raise ValueError("unexpected mops source_id")
    rows = payload["rows"]
    if not isinstance(rows, list):
        raise ValueError("mops artifact rows must be a list")
    artifact_hash = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or not REQUIRED_ROW_FIELDS.issubset(row):
            raise ValueError("mops artifact row missing PIT fields")
        revision = int(str(row["revision"]))
        if revision < 1 or (revision > 1 and not str(row.get("parent_revision") or "").strip()):
            raise ValueError("mops artifact revision chain invalid")
        normalized.append({**row, "source_id": payload["source_id"], "source_version": payload["source_version"], "source_hash": artifact_hash, "evidence_tier": "official"})
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate captured MOPS quarterly announcement/revision artifact.")
    parser.add_argument("--artifact-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = json.loads(args.artifact_json.read_text(encoding="utf-8-sig"))
    normalized = validate_artifact(payload)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
