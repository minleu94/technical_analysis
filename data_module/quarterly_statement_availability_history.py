"""季度財報 announcement／revision 歷史 mapping。"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from data_module.fundamental_availability import (
    AvailabilityCoverageDiagnostics,
    AvailabilityEvidenceRecord,
    AvailabilityEvidenceValidationError,
    append_availability_revision,
    summarize_availability_coverage,
)

StatementHistoryKey = tuple[str, str, str, str, date]
StatementNaturalKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class QuarterlyStatementAvailabilityHistoryResult:
    records: tuple[AvailabilityEvidenceRecord, ...]
    coverage: AvailabilityCoverageDiagnostics
    unmatched_reasons: dict[StatementNaturalKey, str]
    source_manifest: tuple[tuple[str, str, str], ...]


def build_quarterly_statement_availability_history(
    *,
    statement_keys: set[StatementHistoryKey],
    evidence_rows: Iterable[Mapping[str, object]],
    feature_cutoff: date,
) -> QuarterlyStatementAvailabilityHistoryResult:
    history: tuple[AvailabilityEvidenceRecord, ...] = ()
    matched_keys: set[StatementNaturalKey] = set()
    unmatched_reasons: dict[StatementNaturalKey, str] = {}
    manifest: set[tuple[str, str, str]] = set()
    period_end_by_key = {
        (stock, statement_type, scope, period): period_end
        for stock, statement_type, scope, period, period_end in statement_keys
    }

    for row in evidence_rows:
        key = (
            str(row.get("stock_code") or "").strip(),
            str(row.get("statement_type") or "").strip(),
            str(row.get("statement_scope") or "").strip(),
            str(row.get("period") or "").strip(),
        )
        if key not in period_end_by_key:
            continue
        announcement_text = str(row.get("announcement_date") or "").strip()
        observed_text = str(row.get("first_observed_date") or "").strip()
        available_text = str(row.get("available_date") or "").strip()
        tier = str(row.get("evidence_tier") or "").strip()
        if not (announcement_text or observed_text) or not available_text:
            unmatched_reasons[key] = "missing_publication_or_first_observed"
            continue
        if tier == "official" and not announcement_text:
            unmatched_reasons[key] = "missing_official_publication"
            continue
        if tier == "observed_only" and not observed_text:
            unmatched_reasons[key] = "missing_first_observed"
            continue

        try:
            record = AvailabilityEvidenceRecord(
                source_id=str(row.get("source_id") or "").strip(),
                source_version=str(row.get("source_version") or "").strip(),
                source_hash=str(row.get("source_hash") or "").strip(),
                symbol=key[0],
                data_family=f"quarterly_statement:{key[1]}:{key[2]}",
                period_or_event_date=period_end_by_key[key],
                announcement_at=_optional_date(announcement_text),
                first_observed_at=_optional_date(observed_text),
                available_at=date.fromisoformat(available_text),
                revision=int(str(row.get("revision") or "1")),
                parent_revision=(
                    int(str(row["parent_revision"]))
                    if str(row.get("parent_revision") or "").strip()
                    else None
                ),
                effective_at=None,
                quality_tier=tier,
                match_method=(
                    "official_statement_natural_key"
                    if tier == "official"
                    else "statement_first_observed"
                ),
                content_hash=str(row.get("content_hash") or "").strip(),
            )
            history = append_availability_revision(history, record)
        except (ValueError, AvailabilityEvidenceValidationError) as exc:
            unmatched_reasons[key] = str(exc)
            continue
        matched_keys.add(key)
        manifest.add((record.source_id, record.source_version, record.source_hash))

    for key in period_end_by_key.keys() - matched_keys:
        unmatched_reasons.setdefault(key, "no_matching_statement_evidence")

    records = tuple(
        sorted(
            history,
            key=lambda item: (
                item.symbol,
                item.data_family,
                item.period_or_event_date,
                item.revision,
            ),
        )
    )
    raw_coverage = summarize_availability_coverage(
        records,
        feature_cutoff=feature_cutoff,
    )
    coverage = AvailabilityCoverageDiagnostics(
        total=len(records) + len(unmatched_reasons),
        matched_official=raw_coverage.matched_official,
        matched_observed_only=raw_coverage.matched_observed_only,
        unmatched=len(unmatched_reasons),
        duplicate=raw_coverage.duplicate,
        revision=raw_coverage.revision,
        future_blocked=raw_coverage.future_blocked,
        eligible=raw_coverage.eligible,
    )
    return QuarterlyStatementAvailabilityHistoryResult(
        records=records,
        coverage=coverage,
        unmatched_reasons=unmatched_reasons,
        source_manifest=tuple(sorted(manifest)),
    )


def write_quarterly_statement_availability_history(
    result: QuarterlyStatementAvailabilityHistoryResult,
    *,
    output_root: Path,
) -> dict[str, Path]:
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    mapping_path = root / "quarterly_statement_availability_mapping.csv"
    coverage_path = root / "quarterly_statement_availability_coverage.json"
    manifest_path = root / "quarterly_statement_availability_manifest.json"

    fieldnames = (
        "source_id",
        "source_version",
        "source_hash",
        "symbol",
        "data_family",
        "period_or_event_date",
        "announcement_at",
        "first_observed_at",
        "available_at",
        "revision",
        "parent_revision",
        "effective_at",
        "quality_tier",
        "match_method",
        "content_hash",
    )
    with mapping_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for record in result.records:
            writer.writerow(
                {
                    key: _serialize(getattr(record, key))
                    for key in fieldnames
                }
            )
    coverage_path.write_text(
        json.dumps(asdict(result.coverage), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "quarterly-statement-availability.v1",
                "sources": [
                    {
                        "source_id": source_id,
                        "source_version": source_version,
                        "source_hash": source_hash,
                    }
                    for source_id, source_version, source_hash in result.source_manifest
                ],
                "unmatched": [
                    {"natural_key": list(key), "reason": reason}
                    for key, reason in sorted(result.unmatched_reasons.items())
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "mapping": mapping_path,
        "coverage": coverage_path,
        "manifest": manifest_path,
    }


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _serialize(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""
    return value
