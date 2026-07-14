"""TWSE T86 20-day retroactive candidate recovery pilot (never formal ingestion)."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from data_module.twse_t86_candidate_normalizer import NORMALIZER_VERSION, normalize_t86_payload
from data_module.twse_t86_candidate_source import RawFetchEnvelope, fetch_t86_envelope, persist_raw_envelope
from development_module.output_guard import validate_development_output_root


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)


def resolve_completed_dates(db_path: Path, *, cutoff_date: str, count: int = 20) -> list[str]:
    with _read_only_connection(db_path) as connection:
        rows = connection.execute('SELECT DISTINCT 日期 FROM daily_prices').fetchall()
    cutoff = date.fromisoformat(cutoff_date)
    parsed = []
    for row in rows:
        text = str(row[0]).strip()
        try:
            parsed_date = datetime.strptime(text, "%Y%m%d").date() if len(text) == 8 and text.isdigit() else date.fromisoformat(text)
        except ValueError:
            continue
        if parsed_date <= cutoff:
            parsed.append(parsed_date)
    dates = [value.isoformat() for value in sorted(set(parsed))[-count:]]
    if len(dates) != count:
        raise ValueError(f"expected {count} completed trading dates, found {len(dates)}")
    return dates


def _universe(db_path: Path, observation_date: str) -> set[str]:
    with _read_only_connection(db_path) as connection:
        rows = connection.execute(
            'SELECT DISTINCT 證券代號 FROM daily_prices WHERE 日期 IN (?, ?)',
            (observation_date, observation_date.replace("-", "")),
        ).fetchall()
    return {str(row[0]).strip() for row in rows if str(row[0]).strip().isdigit() and len(str(row[0]).strip()) == 4}


def _write_new_json(path: Path, value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded)


def run_pilot(
    *,
    db_path: Path,
    development_output_root: Path,
    cutoff_date: str,
    generation_id: str,
    fetcher: Callable[[date], RawFetchEnvelope] = fetch_t86_envelope,
    supersedes_generation_id: str | None = None,
) -> dict[str, object]:
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise ValueError("db_path must be an existing read-only source DB")
    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    output_root = validate_development_output_root(
        development_output_root,
        data_root=data_root,
        formal_db=db_path,
    )
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError("development output root must be new or empty")
    resolved_generation_id = generation_id.strip()
    if not resolved_generation_id:
        raise ValueError("generation_id must not be empty")
    resolved_supersedes_generation_id: str | None = None
    if supersedes_generation_id is not None:
        resolved_supersedes_generation_id = supersedes_generation_id.strip()
        if not resolved_supersedes_generation_id:
            raise ValueError("supersedes_generation_id must not be empty")
    if resolved_supersedes_generation_id == resolved_generation_id:
        raise ValueError("a generation cannot supersede itself")
    output_root.mkdir(parents=True, exist_ok=True)

    resolved_dates = resolve_completed_dates(db_path, cutoff_date=cutoff_date)
    coverage: list[dict[str, object]] = []
    failed_dates: list[dict[str, str]] = []
    raw_hashes: dict[str, str] = {}
    schema_by_date: dict[str, str] = {}
    prior_schema: str | None = None
    schema_diffs: list[dict[str, str]] = []
    rate_limit_observations: list[dict[str, object]] = []
    successful_date_count = 0
    for date_text in resolved_dates:
        try:
            envelope = fetcher(date.fromisoformat(date_text))
            persist_raw_envelope(envelope, output_root=output_root)
            raw_hashes[date_text] = envelope.payload_sha256
            rate_limit_observations.append({
                "date": date_text, "attempts": [asdict(attempt) for attempt in envelope.attempts],
            })
            universe = _universe(db_path, date_text)
            result = normalize_t86_payload(
                envelope.payload, observation_date=date_text, retrieved_at=envelope.retrieved_at,
                allowed_symbols=universe,
            )
            schema_by_date[date_text] = result.schema_sha256
            if prior_schema is not None and prior_schema != result.schema_sha256:
                schema_diffs.append({"date": date_text, "previous_schema_sha256": prior_schema, "schema_sha256": result.schema_sha256})
            prior_schema = result.schema_sha256
            if "schema_drift" in result.warnings:
                error = "schema_drift:payload schema does not match the supported T86 contract"
                failed_dates.append({"date": date_text, "error": error})
                coverage.append({
                    "date": date_text,
                    "status": "failed",
                    "error": error,
                    "raw_rows": result.raw_row_count,
                    "accepted": result.accepted_count,
                    "quarantined": result.quarantined_count,
                    "warnings": list(result.warnings),
                })
                continue
            symbols = set(result.symbols)
            observed_symbols = set(result.observed_symbols)
            normalized_rows = []
            for row in result.rows:
                normalized_rows.append({
                    "observation_date": row.observation_date, "symbol": row.symbol, "name": row.name,
                    "quantities": dict(row.quantities), "raw_row_sha256": row.raw_row_sha256,
                    "raw_payload_sha256": envelope.payload_sha256,
                    "first_observed_at": row.first_observed_at.isoformat(), "available_at": None,
                })
            _write_new_json(output_root / "normalized" / f"{date_text}.json", normalized_rows)
            coverage.append({
                "date": date_text, "status": "success", "raw_rows": result.raw_row_count,
                "accepted": result.accepted_count, "quarantined": result.quarantined_count,
                "explicitly_ignored": result.ignored_count, "duplicates": result.duplicate_count,
                "conflicts": result.conflict_count, "securities": len(symbols),
                "missing_symbols": sorted(universe - symbols), "extra_symbols": sorted(observed_symbols - universe),
                "warnings": list(result.warnings),
            })
            successful_date_count += 1
        except Exception as exc:
            failed_dates.append({"date": date_text, "error": f"{type(exc).__name__}:{exc}"})
            coverage.append({"date": date_text, "status": "failed", "error": f"{type(exc).__name__}:{exc}"})

    manifest: dict[str, object] = {
        "manifest_version": "twse-t86-candidate-pilot.v2", "source_key": "twse:T86",
        "generation_id": resolved_generation_id,
        "normalizer_version": NORMALIZER_VERSION,
        "supersedes_generation_id": resolved_supersedes_generation_id,
        "source_status": "deferred", "candidate_development_only": True,
        "source_accepted": False, "formal_validation_allowed": False,
        "formal_oos_allowed": False, "production_blend_alpha_bp": 0,
        "license_terms_status": "unknown", "resolved_dates": resolved_dates,
        "requested_dates": len(resolved_dates), "received_dates": len(raw_hashes),
        "successful_dates": successful_date_count, "failed_dates": failed_dates,
        "success_ratio": f"{successful_date_count}/{len(resolved_dates)}",
        "raw_hashes": raw_hashes, "schema_by_date": schema_by_date,
        "schema_diffs": schema_diffs, "revision_diffs": [],
        "rate_limit_observations": rate_limit_observations, "coverage": coverage,
    }
    dossier = {
        "source_key": "twse:T86", "decision_status": "deferred",
        "generation_id": resolved_generation_id,
        "normalizer_version": NORMALIZER_VERSION,
        "supersedes_generation_id": resolved_supersedes_generation_id,
        "reason": "retroactive_baseline_candidate_research_only",
        "source_accepted": False, "formal_validation_allowed": False,
        "license_terms_status": "unknown", "manifest": "manifest.json",
    }
    _write_new_json(output_root / "manifest.json", manifest)
    _write_new_json(output_root / "coverage_matrix.json", coverage)
    _write_new_json(output_root / "source_dossier.json", dossier)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover a deferred TWSE T86 20-day candidate pilot")
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--development-output-root", type=Path, required=True)
    parser.add_argument("--generation-id", required=True)
    parser.add_argument("--supersedes-generation-id")
    parser.add_argument("--cutoff-date", required=True, help="已完成交易日上限 YYYY-MM-DD")
    args = parser.parse_args()
    manifest = run_pilot(
        db_path=args.db_path,
        development_output_root=args.development_output_root,
        cutoff_date=args.cutoff_date,
        generation_id=args.generation_id,
        supersedes_generation_id=args.supersedes_generation_id,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if not manifest["failed_dates"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
