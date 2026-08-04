"""Foreground-only bounded batch runner for MOPS numeric PIT candidate acquisition."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.config import TWStockConfig
from data_module.mops_numeric_pit_aggregator import (
    build_mops_numeric_pit_aggregate,
    validate_single_candidate_bundle,
)
from development_module.output_guard import validate_development_output_root
from scripts.build_mops_numeric_pit_candidate import build_candidate


_SHA256_RE = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
_STOCK_RE = re.compile(r"\d{4,6}\Z")


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
    """Execute a bounded foreground acquisition batch.

    Resume is deliberately hash-addressed: an existing identity is skipped only
    when the manifest supplies its expected candidate SHA-256.  Conflicting or
    unverifiable identities are reported before any network fetch, and revision
    creation remains an explicit separate workflow.
    """
    if max_items <= 0:
        raise ValueError("max_items must be a positive integer")
    if rate_limit_seconds < 0:
        raise ValueError("rate_limit_seconds cannot be negative")
    if minimum_coverage_bp != 8000:
        raise ValueError("minimum_coverage_bp is a fixed policy threshold of 8000 bp")

    config = TWStockConfig()
    safe_root = validate_development_output_root(
        output_root,
        data_root=Path(config.data_root),
        formal_db=Path(config.db_file),
    )
    items_to_process = batch_manifest[:max_items]

    existing_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    if safe_root.exists():
        for candidate_json in safe_root.glob("*/numeric-pit-candidate.json"):
            candidate_dir = candidate_json.parent
            _assert_candidate_dir_contained(candidate_dir, safe_root)
            try:
                validation_result = validate_single_candidate_bundle(candidate_dir)
            except Exception as exc:
                raise ValueError(
                    f"existing candidate scan failed closed at {candidate_dir}: {exc}"
                ) from exc
            identity = (validation_result.stock_code, validation_result.period)
            if identity in existing_by_identity:
                raise ValueError(f"existing candidate identity is duplicated: {identity}")
            existing_by_identity[identity] = {
                "directory": candidate_dir,
                "candidate_sha256": f"sha256:{validation_result.candidate_sha256}",
                "manifest_sha256": f"sha256:{validation_result.manifest_sha256}",
            }

    attempted = 0
    succeeded = 0
    failed = 0
    skipped_identical = 0
    failure_diagnostics: list[dict[str, Any]] = []
    acquired_dirs = [item["directory"] for item in existing_by_identity.values()]
    fetch_count = 0

    for index, raw_item in enumerate(items_to_process):
        attempted += 1
        try:
            stock_code, market, roc_year, season, period = _validate_manifest_item(raw_item)
        except (TypeError, ValueError) as exc:
            failed += 1
            failure_diagnostics.append({"item_index": index, "error": str(exc)})
            continue
        identity = (stock_code, period)

        if dry_run:
            print(
                f"[DRY-RUN] Item {attempted}/{len(items_to_process)}: "
                f"stock={stock_code}, market={market}, period={period}"
            )
            succeeded += 1
            continue

        existing = existing_by_identity.get(identity)
        if existing is not None:
            expected_hash = _normalize_sha256(raw_item.get("candidate_sha256"))
            if expected_hash is None:
                failed += 1
                failure_diagnostics.append({
                    "stock_code": stock_code,
                    "period": period,
                    "error": "resume_requires_expected_candidate_sha256",
                })
            elif expected_hash == existing["candidate_sha256"]:
                skipped_identical += 1
            else:
                failed += 1
                failure_diagnostics.append({
                    "stock_code": stock_code,
                    "period": period,
                    "error": "conflicting_candidate_identity_requires_manual_revision",
                    "existing_candidate_sha256": existing["candidate_sha256"],
                    "expected_candidate_sha256": expected_hash,
                })
            continue

        if fetch_count > 0 and rate_limit_seconds > 0:
            time.sleep(rate_limit_seconds)
        fetch_count += 1
        run_id = (
            f"dev-mops-batch-{stock_code}-{roc_year}q{season}-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{index}"
        )
        try:
            build_result = build_candidate(
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
            candidate_dir = Path(build_result["output_directory"])
            _assert_candidate_dir_contained(candidate_dir, safe_root)
            validation = validate_single_candidate_bundle(candidate_dir)
            expected_hash = _normalize_sha256(raw_item.get("candidate_sha256"))
            actual_hash = f"sha256:{validation.candidate_sha256}"
            if expected_hash is not None and expected_hash != actual_hash:
                _remove_new_candidate_dir(candidate_dir, safe_root)
                raise ValueError("new candidate SHA-256 does not match manifest expectation")
            if identity in existing_by_identity:
                _remove_new_candidate_dir(candidate_dir, safe_root)
                raise ValueError("candidate identity appeared during acquisition")
            existing_by_identity[identity] = {
                "directory": candidate_dir,
                "candidate_sha256": actual_hash,
                "manifest_sha256": f"sha256:{validation.manifest_sha256}",
            }
            acquired_dirs.append(candidate_dir)
            succeeded += 1
        except Exception as exc:
            failed += 1
            failure_diagnostics.append({
                "stock_code": stock_code,
                "period": period,
                "error": str(exc),
            })

    coverage_summary: dict[str, Any] = {}
    if acquired_dirs and not dry_run and failed == 0:
        try:
            agg_run_id = f"dev-mops-batch-aggregate-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
            aggregate = build_mops_numeric_pit_aggregate(
                candidate_dirs=acquired_dirs,
                output_root=safe_root,
                run_id=agg_run_id,
                minimum_coverage_bp=minimum_coverage_bp,
            )
            coverage_summary = {
                key: aggregate[key]
                for key in (
                    "candidate_count",
                    "unique_identity_count",
                    "matching_decision_row_count",
                    "pit_eligible_row_count",
                    "canonical_denominator",
                    "cumulative_coverage_bp",
                    "coverage_gap_bp",
                )
            }
        except Exception as exc:
            failed += 1
            coverage_summary = {"aggregate_error": str(exc)}
            failure_diagnostics.append({"stage": "aggregate", "error": str(exc)})

    batch_result: dict[str, Any] = {
        "schema_version": "mops-batch-acquisition-result.v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "max_items_requested": max_items,
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "skipped_identical": skipped_identical,
        "revision_candidates": 0,
        "coverage_summary": coverage_summary,
        "failure_diagnostics": failure_diagnostics,
        "status": "failed" if failed else "completed",
    }
    return batch_result


def _validate_manifest_item(item: Mapping[str, Any]) -> tuple[str, str, int, int, str]:
    if not isinstance(item, Mapping):
        raise ValueError("batch manifest item must be an object")
    stock_code = str(item.get("stock_code") or "").strip()
    market = str(item.get("market") or "").strip()
    if _STOCK_RE.fullmatch(stock_code) is None:
        raise ValueError("stock_code must be a 4-to-6 digit security identifier")
    if market not in {"sii", "otc", "rotc", "pub"}:
        raise ValueError("market must be one of sii, otc, rotc, pub")
    try:
        roc_year = int(item.get("roc_year", 0))
        season = int(item.get("season", item.get("quarter", 0)))
    except (TypeError, ValueError) as exc:
        raise ValueError("roc_year and season must be integers") from exc
    if roc_year <= 0 or season not in {1, 2, 3, 4}:
        raise ValueError("roc_year must be positive and season must be 1 through 4")
    return stock_code, market, roc_year, season, f"{roc_year + 1911}-Q{season}"


def _normalize_sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    if _SHA256_RE.fullmatch(candidate) is None:
        return None
    return candidate if candidate.startswith("sha256:") else f"sha256:{candidate}"


def _assert_candidate_dir_contained(candidate_dir: Path, safe_root: Path) -> Path:
    resolved = candidate_dir.expanduser().resolve()
    root = safe_root.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("candidate output directory must remain inside development output root") from exc
    if not resolved.is_dir():
        raise ValueError(f"candidate output directory does not exist: {resolved}")
    return resolved


def _remove_new_candidate_dir(candidate_dir: Path, safe_root: Path) -> None:
    resolved = _assert_candidate_dir_contained(candidate_dir, safe_root)
    shutil.rmtree(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-manifest", type=Path, required=True)
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
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
