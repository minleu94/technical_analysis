"""Multi-candidate lineage and coverage aggregator for MOPS numeric PIT research candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from data_module.config import TWStockConfig
from data_module.p0_source_contract_registry import resolve_mops_numeric_pit_source_mapping
from development_module.output_guard import validate_development_output_root
from scripts.validate_mops_quarterly_artifact import validate_artifact


DEFAULT_MINIMUM_COVERAGE_BP = 8000


@dataclass(frozen=True)
class CandidateValidationResult:
    candidate_path: Path
    manifest_path: Path
    run_id: str
    stock_code: str
    period: str
    available_date: str
    candidate_sha256: str
    manifest_sha256: str
    canonical_manifest_sha256: str
    canonical_dataset_sha256: str
    matching_decision_rows: int
    pit_eligible_rows: int
    canonical_denominator: int


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _file_sha256_ref(path: Path) -> str:
    return f"sha256:{_file_sha256(path)}"


def validate_single_candidate_bundle(
    candidate_dir: Path,
) -> CandidateValidationResult:
    """Validate a single candidate directory bundle prior to aggregation.

    Fail-closed checks:
    1. Candidate and manifest files exist.
    2. Manifest schema is mops-numeric-pit-run-manifest.v1.
    3. 5 physical files match manifest SHA-256 entries.
    4. Lineage hashes match manifest hashes.
    5. No float values in statement_items.
    6. safe next-day available_date policy.
    7. correction_status == "none", revision == 1, parent_revision is None.
    """
    candidate_dir = candidate_dir.resolve()
    manifest_path = candidate_dir / "run-manifest.json"
    candidate_path = candidate_dir / "numeric-pit-candidate.json"
    num_src_path = candidate_dir / "numeric-source.json"
    avail_src_path = candidate_dir / "availability-source.json"

    if not manifest_path.is_file():
        raise ValueError(f"missing run-manifest.json in candidate directory: {candidate_dir}")
    if not candidate_path.is_file():
        raise ValueError(f"missing numeric-pit-candidate.json in candidate directory: {candidate_dir}")
    if not num_src_path.is_file():
        raise ValueError(f"missing numeric-source.json in candidate directory: {candidate_dir}")
    if not avail_src_path.is_file():
        raise ValueError(f"missing availability-source.json in candidate directory: {candidate_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "mops-numeric-pit-run-manifest.v1":
        raise ValueError(f"invalid manifest schema_version in {manifest_path}")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"manifest missing files dictionary in {manifest_path}")

    req_keys = {"numeric_source", "availability_source", "candidate", "raw_numeric_response", "raw_listing_response"}
    if not req_keys.issubset(files.keys()):
        raise ValueError(f"manifest missing required file entries in {manifest_path}")

    # Physical file hash verification
    for key, rel_name in [
        ("numeric_source", "numeric-source.json"),
        ("availability_source", "availability-source.json"),
        ("candidate", "numeric-pit-candidate.json"),
    ]:
        p = candidate_dir / rel_name
        if _file_sha256_ref(p) != files[key]:
            raise ValueError(f"physical file hash mismatch for {rel_name} in {candidate_dir}")

    raw_dir = candidate_dir / "raw"
    if not raw_dir.is_dir():
        raise ValueError(f"missing raw custody directory in {candidate_dir}")

    raw_files = list(raw_dir.glob("*.html"))
    if len(raw_files) < 2:
        raise ValueError(f"missing raw HTML custody responses in {raw_dir}")

    # Check raw file hashes match manifest entries
    raw_num_match = any(_file_sha256_ref(rf) == files["raw_numeric_response"] for rf in raw_files)
    raw_avail_match = any(_file_sha256_ref(rf) == files["raw_listing_response"] for rf in raw_files)
    if not raw_num_match or not raw_avail_match:
        raise ValueError(f"raw HTML custody hash mismatch in {raw_dir}")

    # Candidate JSON schema & content validation
    cand_payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    normalized_rows = validate_artifact(cand_payload)
    if not normalized_rows:
        raise ValueError(f"candidate artifact has no valid rows: {candidate_path}")

    row = cand_payload["rows"][0]
    stock_code = str(row["stock_code"]).strip()
    period = str(row["period"]).strip()
    pub_ts = str(row["publication_timestamp"])
    available_date = str(row["available_date"])
    correction_status = str(row.get("correction_status", ""))
    revision = row.get("revision")
    parent_revision = row.get("parent_revision")

    if correction_status != "none":
        raise ValueError(f"unknown or unhandled correction_status '{correction_status}' in {candidate_path}")
    if revision != 1 or parent_revision is not None:
        raise ValueError(f"invalid revision chain in {candidate_path}")

    # Publication date vs available_date check
    pub_date = date.fromisoformat(pub_ts[:10])
    avail_d = date.fromisoformat(available_date)
    if avail_d <= pub_date:
        raise ValueError(f"available_date {available_date} must be strictly after publication date {pub_date}")

    # Check statement_items for float prohibition
    items = row.get("statement_items", {})
    if not isinstance(items, dict) or not items:
        raise ValueError(f"missing or empty statement_items in {candidate_path}")
    for k, v in items.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"statement_items field '{k}' must be an integer, got {type(v)}: {candidate_path}")

    # Lineage check
    lineage = cand_payload.get("lineage", {})
    num_src_ref = lineage.get("numeric_statement_source", {}).get("artifact_sha256")
    avail_src_ref = lineage.get("availability_artifact_sha256")
    if num_src_ref != files["numeric_source"] or avail_src_ref != files["availability_source"]:
        raise ValueError(f"candidate lineage hashes do not match run-manifest in {candidate_dir}")

    canon_lineage = lineage.get("canonical_dataset_lineage", {})
    canon_manifest_h = str(canon_lineage.get("manifest_sha256"))
    canon_dataset_h = str(canon_lineage.get("dataset_sha256"))

    cov_summary = cand_payload.get("pit_coverage_summary", {})
    matching_rows = int(cov_summary.get("canonical_matching_decision_row_count", 0))
    eligible_rows = int(cov_summary.get("canonical_pit_eligible_row_count", 0))
    denominator = int(cov_summary.get("canonical_dataset_row_count", 0))

    cand_sha256 = _file_sha256(candidate_path)
    man_sha256 = _file_sha256(manifest_path)
    run_id = str(manifest.get("run_id") or candidate_dir.name)

    return CandidateValidationResult(
        candidate_path=candidate_path,
        manifest_path=manifest_path,
        run_id=run_id,
        stock_code=stock_code,
        period=period,
        available_date=available_date,
        candidate_sha256=cand_sha256,
        manifest_sha256=man_sha256,
        canonical_manifest_sha256=canon_manifest_h,
        canonical_dataset_sha256=canon_dataset_h,
        matching_decision_rows=matching_rows,
        pit_eligible_rows=eligible_rows,
        canonical_denominator=denominator,
    )


def build_mops_numeric_pit_aggregate(
    candidate_dirs: list[Path],
    *,
    output_root: Path,
    run_id: str,
    minimum_coverage_bp: int = DEFAULT_MINIMUM_COVERAGE_BP,
) -> dict[str, Any]:
    """Aggregate multi-candidate MOPS numeric PIT research artifacts deterministically.

    Fail-closed rules:
    - Entire batch fails if any candidate validation fails.
    - Entire batch fails if duplicate (stock_code, period) identities exist across candidates.
    - Entire batch fails if canonical manifest/dataset lineage is mixed.
    """
    if not candidate_dirs:
        raise ValueError("candidate_dirs list cannot be empty")
    if not 0 <= minimum_coverage_bp <= 10000:
        raise ValueError("minimum_coverage_bp must be within 0..10000")

    config = TWStockConfig()
    safe_root = validate_development_output_root(
        output_root,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )

    validated: list[CandidateValidationResult] = []
    seen_identities: set[tuple[str, str]] = set()

    for cdir in candidate_dirs:
        res = validate_single_candidate_bundle(cdir)
        identity = (res.stock_code, res.period)
        if identity in seen_identities:
            raise ValueError(f"duplicate candidate identity {identity} in batch")
        seen_identities.add(identity)
        validated.append(res)

    # Check canonical dataset/manifest identity consistency
    canon_manifests = {v.canonical_manifest_sha256 for v in validated}
    canon_datasets = {v.canonical_dataset_sha256 for v in validated}
    if len(canon_manifests) != 1 or len(canon_datasets) != 1:
        raise ValueError("mixed canonical dataset or manifest lineage across candidates")

    canon_manifest_h = next(iter(canon_manifests))
    canon_dataset_h = next(iter(canon_datasets))

    # Aggregated metrics (sum matching and eligible rows across unique candidates)
    matching_rows = sum(v.matching_decision_rows for v in validated)
    eligible_rows = sum(v.pit_eligible_rows for v in validated)
    denominator = validated[0].canonical_denominator

    if denominator <= 0:
        raise ValueError("canonical dataset denominator must be positive")

    cumulative_coverage_bp = (eligible_rows * 10000) // denominator
    coverage_gap_bp = max(0, minimum_coverage_bp - cumulative_coverage_bp)

    # Source identity mapping contract verification
    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id="mops.statement.publication",
        numeric_source_id="mops.t163sb06.financial_ratio",
        availability_source_id="mops.document_listing.statement_publication",
    )

    diagnostics: list[str] = []
    if cumulative_coverage_bp < minimum_coverage_bp:
        diagnostics.append("coverage_below_minimum")
    diagnostics.append("missing_license_evidence")
    diagnostics.append("requires_human_acceptance")

    aggregate_payload = {
        "schema_version": "mops-numeric-pit-aggregate.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "governance_source_id": mapping.governance_source_id,
        "artifact_source_id": mapping.artifact_source_id,
        "numeric_source_id": mapping.numeric_source_id,
        "availability_source_id": mapping.availability_source_id,
        "source_identity_mapping": mapping.to_dict(),
        "canonical_manifest_sha256": canon_manifest_h,
        "canonical_dataset_sha256": canon_dataset_h,
        "candidate_count": len(validated),
        "unique_identity_count": len(validated),
        "matching_decision_row_count": matching_rows,
        "pit_eligible_row_count": eligible_rows,
        "canonical_denominator": denominator,
        "cumulative_coverage_bp": cumulative_coverage_bp,
        "minimum_coverage_bp": minimum_coverage_bp,
        "coverage_gap_bp": coverage_gap_bp,
        "candidates": [
            {
                "run_id": v.run_id,
                "stock_code": v.stock_code,
                "period": v.period,
                "available_date": v.available_date,
                "candidate_sha256": f"sha256:{v.candidate_sha256}",
                "manifest_sha256": f"sha256:{v.manifest_sha256}",
            }
            for v in validated
        ],
        "rejected_diagnostics": [],
        "source_acceptance_readiness_diagnostics": sorted(set(diagnostics)),
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
        "downstream_eligibility": "none",
    }

    target_dir = (safe_root / run_id).resolve()
    if target_dir.exists():
        raise ValueError(f"output directory {target_dir} already exists")

    target_dir.mkdir(parents=True)
    out_file = target_dir / "mops-numeric-pit-aggregate.json"
    out_file.write_text(json.dumps(aggregate_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return aggregate_payload
