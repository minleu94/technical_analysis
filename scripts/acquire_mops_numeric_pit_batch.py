"""Foreground-only bounded batch runner for MOPS numeric PIT candidate acquisition."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import sys
import time
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.config import TWStockConfig
from development_module.output_guard import validate_development_output_root
from scripts.build_mops_numeric_pit_candidate import build_candidate
from data_module.mops_numeric_pit_aggregator import validate_single_candidate_bundle, build_mops_numeric_pit_aggregate


def execute_mops_batch(
    batch_manifest: list[dict[str, Any]],
    *,
    output_root: Path,
    canonical_manifest: Path,
    canonical_dataset: Path,
    max_items: int,
    rate_limit_seconds: float = 2.0,
    timeout_seconds: int = 30,
    dry_run: bool = False,
    minimum_coverage_bp: int = 8000,
) -> dict[str, Any]:
    """Execute a foreground-only bounded acquisition batch for MOPS numeric PIT candidates.

    Fail-closed & Safety rules:
    1. Mandatory max_items restriction.
    2. Atomic staging and validation per candidate.
    3. Idempotent skip for identical (stock_code, period, candidate_sha256).
    4. Conflict diagnostic for changed content on same identity.
    5. Output strictly to development/TEMP root.
    6. No background processes or schedulers.
    """
    if max_items <= 0:
        raise ValueError("max_items must be a positive integer")
    if rate_limit_seconds < 0:
        raise ValueError("rate_limit_seconds cannot be negative")

    config = TWStockConfig()
    safe_root = validate_development_output_root(
        output_root,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )

    items_to_process = batch_manifest[:max_items]

    # Scan existing candidate directories in safe_root to support resume & conflict detection
    existing_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if safe_root.exists():
        for candidate_json in safe_root.glob("*/numeric-pit-candidate.json"):
            cdir = candidate_json.parent
            try:
                vres = validate_single_candidate_bundle(cdir)
                identity = (vres.stock_code, vres.period)
                existing_by_identity.setdefault(identity, []).append({
                    "directory": cdir,
                    "candidate_sha256": vres.candidate_sha256,
                    "manifest_sha256": vres.manifest_sha256,
                })
            except Exception:
                continue

    attempted = 0
    succeeded = 0
    failed = 0
    skipped_identical = 0
    revision_candidates = 0
    failure_diagnostics: list[dict[str, Any]] = []

    acquired_dirs: list[Path] = []
    # Collect all existing valid candidate directories
    for cand_list in existing_by_identity.values():
        for item in cand_list:
            acquired_dirs.append(item["directory"])

    for index, item in enumerate(items_to_process):
        stock_code = str(item.get("stock_code") or "").strip()
        market = str(item.get("market") or "").strip()
        roc_year = int(item.get("roc_year", 0))
        season = int(item.get("season", item.get("quarter", 0)))
        period = f"{roc_year + 1911}-Q{season}"
        identity = (stock_code, period)

        attempted += 1

        if dry_run:
            print(f"[DRY-RUN] Item {attempted}/{len(items_to_process)}: stock={stock_code}, market={market}, period={period}")
            succeeded += 1
            continue

        if index > 0 and rate_limit_seconds > 0:
            time.sleep(rate_limit_seconds)

        run_id = f"dev-mops-batch-{stock_code}-{roc_year}q{season}-{int(datetime.now(timezone.utc).timestamp())}"

        try:
            res = build_candidate(
                stock_code=stock_code,
                roc_year=roc_year,
                season=season,
                market=market,
                output_root=safe_root,
                run_id=run_id,
                canonical_manifest=canonical_manifest,
                canonical_dataset=canonical_dataset,
                timeout_seconds=timeout_seconds,
            )
            cand_dir = Path(res["output_directory"])
            vres = validate_single_candidate_bundle(cand_dir)

            # Check against existing candidates with same identity
            existing = existing_by_identity.get(identity, [])
            identical_match = any(e["candidate_sha256"] == vres.candidate_sha256 for e in existing)
            conflict_match = any(e["candidate_sha256"] != vres.candidate_sha256 for e in existing)

            if identical_match:
                skipped_identical += 1
            elif conflict_match:
                revision_candidates += 1
                succeeded += 1
                acquired_dirs.append(cand_dir)
            else:
                succeeded += 1
                acquired_dirs.append(cand_dir)

        except Exception as exc:
            failed += 1
            failure_diagnostics.append({
                "stock_code": stock_code,
                "period": period,
                "error": str(exc),
            })

    # Compute updated aggregate coverage across acquired candidate directories
    coverage_summary: dict[str, Any] = {}
    if acquired_dirs and not dry_run:
        try:
            agg_run_id = f"dev-mops-batch-aggregate-{int(datetime.now(timezone.utc).timestamp())}"
            agg_payload = build_mops_numeric_pit_aggregate(
                candidate_dirs=acquired_dirs,
                output_root=safe_root,
                run_id=agg_run_id,
                minimum_coverage_bp=minimum_coverage_bp,
            )
            coverage_summary = {
                "candidate_count": agg_payload["candidate_count"],
                "unique_identity_count": agg_payload["unique_identity_count"],
                "matching_decision_row_count": agg_payload["matching_decision_row_count"],
                "pit_eligible_row_count": agg_payload["pit_eligible_row_count"],
                "canonical_denominator": agg_payload["canonical_denominator"],
                "cumulative_coverage_bp": agg_payload["cumulative_coverage_bp"],
                "coverage_gap_bp": agg_payload["coverage_gap_bp"],
            }
        except Exception as exc:
            coverage_summary = {"aggregate_error": str(exc)}

    return {
        "schema_version": "mops-batch-acquisition-result.v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "max_items_requested": max_items,
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "skipped_identical": skipped_identical,
        "revision_candidates": revision_candidates,
        "coverage_summary": coverage_summary,
        "failure_diagnostics": failure_diagnostics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", type=Path, required=True, help="Path to JSON file containing array of {stock_code, market, roc_year, season/quarter}")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--canonical-manifest", type=Path, required=True)
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--max-items", type=int, required=True)
    parser.add_argument("--rate-limit-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    batch_manifest = json.loads(args.batch_manifest.read_text(encoding="utf-8"))
    if not isinstance(batch_manifest, list):
        raise ValueError("batch_manifest JSON must be a list of item dictionaries")

    result = execute_mops_batch(
        batch_manifest=batch_manifest,
        output_root=args.output_root,
        canonical_manifest=args.canonical_manifest,
        canonical_dataset=args.canonical_dataset,
        max_items=args.max_items,
        rate_limit_seconds=args.rate_limit_seconds,
        timeout_seconds=args.timeout_seconds,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
