"""Validate a research-only MOPS quarterly artifact without granting source acceptance."""
from __future__ import annotations

import argparse
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.p0_source_contract_registry import map_candidate_source_id, resolve_mops_numeric_pit_source_mapping


REQUIRED_ARTIFACT_FIELDS = {"source_id", "source_version", "captured_at", "rows"}
REQUIRED_ROW_FIELDS = {
    "stock_code", "statement_type", "statement_scope", "period", "period_end",
    "announcement_date", "available_date", "revision", "content_hash",
}
SHA256_REFERENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NUMERIC_LINEAGE_FIELDS = {
    "numeric_statement_source",
    "availability_artifact_sha256",
    "canonical_dataset_lineage",
}
NUMERIC_ROW_FIELDS = {
    "publication_timestamp",
    "numeric_source_row_sha256",
    "availability_event_sha256",
    "statement_items",
}


def _require_sha256_reference(value: object, field: str) -> None:
    if not isinstance(value, str) or not SHA256_REFERENCE_RE.fullmatch(value):
        raise ValueError(f"{field} must be a sha256-addressed immutable artifact")


def _parse_publication_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("publication_timestamp must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("publication_timestamp must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("publication_timestamp must include a timezone")
    return parsed


def _numeric_claimed(payload: Mapping[str, object], rows: list[object]) -> bool:
    coverage = payload.get("pit_coverage_summary")
    return (
        isinstance(coverage, Mapping)
        and coverage.get("numeric_pit_ratios_supplied") is True
    ) or any(isinstance(row, Mapping) and "statement_items" in row for row in rows)


def _validate_numeric_lineage(payload: Mapping[str, object], rows: list[object]) -> None:
    """Require evidence that numeric values came from a separate raw source.

    MOPS EZSearch publication rows establish only availability.  They cannot by
    themselves establish numeric financial ratios, revisions, or coverage.
    """
    lineage = payload.get("lineage")
    if not isinstance(lineage, Mapping) or not NUMERIC_LINEAGE_FIELDS.issubset(lineage):
        raise ValueError("numeric PIT claim missing raw numeric and canonical-dataset lineage")

    numeric_source = lineage["numeric_statement_source"]
    if not isinstance(numeric_source, Mapping):
        raise ValueError("numeric_statement_source must be an object")
    source_id = numeric_source.get("source_id")
    if source_id in {"mops.ezsearch.statement_publication", "mops.statement.publication"}:
        raise ValueError("availability-only MOPS source cannot be the numeric statement source")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("numeric_statement_source.source_id is required")
    if not isinstance(numeric_source.get("source_version"), str) or not numeric_source["source_version"].strip():
        raise ValueError("numeric_statement_source.source_version is required")
    _require_sha256_reference(
        numeric_source.get("artifact_sha256"),
        "numeric_statement_source.artifact_sha256",
    )
    _require_sha256_reference(lineage["availability_artifact_sha256"], "availability_artifact_sha256")

    dataset_lineage = lineage["canonical_dataset_lineage"]
    if not isinstance(dataset_lineage, Mapping):
        raise ValueError("canonical_dataset_lineage must be an object")
    _require_sha256_reference(dataset_lineage.get("manifest_sha256"), "canonical_dataset_lineage.manifest_sha256")
    _require_sha256_reference(dataset_lineage.get("dataset_sha256"), "canonical_dataset_lineage.dataset_sha256")

    for row in rows:
        if not isinstance(row, Mapping) or not NUMERIC_ROW_FIELDS.issubset(row):
            raise ValueError("numeric PIT row missing raw numeric or availability lineage")
        publication_at = _parse_publication_timestamp(row["publication_timestamp"])
        try:
            available_on = date.fromisoformat(str(row["available_date"]))
        except ValueError as exc:
            raise ValueError("numeric PIT available_date must be an ISO date") from exc
        if available_on <= publication_at.date():
            raise ValueError("numeric PIT available_date must be after the publication date")
        _require_sha256_reference(row["numeric_source_row_sha256"], "numeric_source_row_sha256")
        _require_sha256_reference(row["availability_event_sha256"], "availability_event_sha256")
        statement_items = row["statement_items"]
        if not isinstance(statement_items, Mapping) or not statement_items:
            raise ValueError("numeric PIT statement_items must be a non-empty object")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in statement_items.values()):
            raise ValueError("numeric PIT statement_items must use integer minor units or basis points")


def validate_artifact(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or not REQUIRED_ARTIFACT_FIELDS.issubset(payload):
        raise ValueError("mops artifact missing required provenance fields")
    if payload["source_id"] != "mops.statement.publication":
        raise ValueError("unexpected mops source_id")

    rows = payload["rows"]
    if not isinstance(rows, list):
        raise ValueError("mops artifact rows must be a list")

    numeric_src_id = "mops.t163sb06.financial_ratio"
    avail_src_id = "mops.document_listing.statement_publication"
    lineage = payload.get("lineage")
    if isinstance(lineage, Mapping) and isinstance(lineage.get("numeric_statement_source"), Mapping):
        numeric_src_id = str(lineage["numeric_statement_source"].get("source_id") or numeric_src_id)

    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id=str(payload["source_id"]),
        numeric_source_id=numeric_src_id,
        availability_source_id=avail_src_id,
    )
    if mapping.blockers or mapping.governance_source_id != "pit.quarterly_financials":
        raise ValueError(f"mops artifact source_id lacks a governed P0 contract mapping: {mapping.blockers}")

    source_alignment = map_candidate_source_id(str(payload["source_id"]))
    if _numeric_claimed(payload, rows):
        _validate_numeric_lineage(payload, rows)
    artifact_hash = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or not REQUIRED_ROW_FIELDS.issubset(row):
            raise ValueError("mops artifact row missing PIT fields")
        revision = int(str(row["revision"]))
        if revision < 1 or (revision > 1 and not str(row.get("parent_revision") or "").strip()):
            raise ValueError("mops artifact revision chain invalid")
        normalized.append(
            {
                **row,
                "source_id": mapping.governance_source_id,
                "artifact_source_id": mapping.artifact_source_id,
                "numeric_source_id": mapping.numeric_source_id,
                "availability_source_id": mapping.availability_source_id,
                "source_contract_mapping_version": mapping.mapping_version,
                "source_version": payload["source_version"],
                "source_hash": artifact_hash,
                "evidence_tier": "research_candidate",
            }
        )
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
