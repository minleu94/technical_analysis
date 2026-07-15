"""Corporate-action／restriction append-only availability timeline。"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping
from uuid import uuid4


@dataclass(frozen=True)
class CorporateEventRecord:
    source_event_id: str
    source_id: str
    source_version: str
    source_hash: str
    content_hash: str
    symbol: str
    event_type: str
    event_date: date
    announcement_at: date | None
    first_observed_at: date | None
    available_at: date
    effective_from: date
    effective_to: date | None
    quality_tier: str
    revision: int
    parent_revision: int | None

    def __post_init__(self) -> None:
        if self.announcement_at is not None and self.available_at < self.announcement_at:
            raise ValueError("available_before_announcement")
        if self.revision < 1:
            raise ValueError("invalid_revision")
        if self.revision > 1 and self.parent_revision is None:
            raise ValueError("revision_parent_missing")


@dataclass(frozen=True)
class CorporateSourceCoverageDiagnostics:
    source_id: str
    coverage_start: date | None
    coverage_end: date | None
    quality: str
    total: int
    matched_official: int
    matched_observed_only: int
    unmatched: int
    future_blocked: int
    revision: int
    eligible: int

    @property
    def coverage_unknown(self) -> bool:
        return (
            self.quality not in {"official", "observed"}
            or self.coverage_start is None
            or self.coverage_end is None
        )


@dataclass(frozen=True)
class CorporateActionAvailabilityHistoryResult:
    records: tuple[CorporateEventRecord, ...]
    coverage_by_source: dict[str, CorporateSourceCoverageDiagnostics]
    unmatched_reasons: tuple[tuple[str, str], ...]
    source_manifest: tuple[tuple[str, str, str], ...]

    def visible_as_of(self, as_of_date: date) -> tuple[CorporateEventRecord, ...]:
        return tuple(record for record in self.records if record.available_at <= as_of_date)


def build_corporate_action_availability_history(
    *,
    evidence_rows: Iterable[Mapping[str, object]],
    coverage_rows: Iterable[Mapping[str, object]],
    as_of_date: date,
) -> CorporateActionAvailabilityHistoryResult:
    history: list[CorporateEventRecord] = []
    unmatched: list[tuple[str, str]] = []
    unmatched_by_source: dict[str, int] = {}
    manifest: set[tuple[str, str, str]] = set()

    for row in evidence_rows:
        event_id = str(row.get("source_event_id") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        announcement_text = str(row.get("announcement_date") or "").strip()
        observed_text = str(row.get("first_observed_date") or "").strip()
        available_text = str(row.get("available_date") or "").strip()
        effective_text = str(row.get("effective_date") or row.get("effective_from") or "").strip()
        tier = str(row.get("quality_tier") or "").strip()
        if not event_id or not (announcement_text or observed_text) or not available_text:
            unmatched.append((event_id, "missing_publication_or_first_observed"))
            unmatched_by_source[source_id] = unmatched_by_source.get(source_id, 0) + 1
            continue
        if not effective_text:
            unmatched.append((event_id, "missing_effective_date"))
            unmatched_by_source[source_id] = unmatched_by_source.get(source_id, 0) + 1
            continue
        if tier == "official" and not announcement_text:
            unmatched.append((event_id, "missing_official_announcement"))
            unmatched_by_source[source_id] = unmatched_by_source.get(source_id, 0) + 1
            continue
        try:
            record = CorporateEventRecord(
                source_event_id=event_id,
                source_id=source_id,
                source_version=str(row.get("source_version") or "").strip(),
                source_hash=str(row.get("source_hash") or "").strip(),
                content_hash=str(row.get("content_hash") or "").strip(),
                symbol=str(row.get("symbol") or "").strip(),
                event_type=str(row.get("event_type") or "").strip(),
                event_date=date.fromisoformat(str(row.get("event_date") or "")),
                announcement_at=_optional_date(announcement_text),
                first_observed_at=_optional_date(observed_text),
                available_at=date.fromisoformat(available_text),
                effective_from=date.fromisoformat(effective_text),
                effective_to=_optional_date(str(row.get("effective_to") or "").strip()),
                quality_tier=tier,
                revision=int(str(row.get("revision") or "1")),
                parent_revision=(
                    int(str(row["parent_revision"]))
                    if str(row.get("parent_revision") or "").strip()
                    else None
                ),
            )
        except ValueError as exc:
            unmatched.append((event_id, str(exc)))
            unmatched_by_source[source_id] = unmatched_by_source.get(source_id, 0) + 1
            continue
        try:
            _append_event_revision(history, record)
        except ValueError as exc:
            unmatched.append((event_id, str(exc)))
            unmatched_by_source[source_id] = unmatched_by_source.get(source_id, 0) + 1
            continue
        manifest.add((record.source_id, record.source_version, record.source_hash))

    coverage_inputs = {
        str(row.get("source_id") or "").strip(): row for row in coverage_rows
    }
    all_sources = set(coverage_inputs) | {record.source_id for record in history}
    coverage_by_source: dict[str, CorporateSourceCoverageDiagnostics] = {}
    for source_id in sorted(all_sources):
        source_records = tuple(record for record in history if record.source_id == source_id)
        coverage_row = coverage_inputs.get(source_id, {})
        source_unmatched = unmatched_by_source.get(source_id, 0)
        coverage_by_source[source_id] = CorporateSourceCoverageDiagnostics(
            source_id=source_id,
            coverage_start=_optional_date(str(coverage_row.get("coverage_start") or "")),
            coverage_end=_optional_date(str(coverage_row.get("coverage_end") or "")),
            quality=str(coverage_row.get("quality") or "unknown"),
            total=len(source_records) + source_unmatched,
            matched_official=sum(record.quality_tier == "official" for record in source_records),
            matched_observed_only=sum(
                record.quality_tier == "observed_only" for record in source_records
            ),
            unmatched=source_unmatched,
            future_blocked=sum(record.available_at > as_of_date for record in source_records),
            revision=sum(record.revision > 1 for record in source_records),
            eligible=sum(record.available_at <= as_of_date for record in source_records),
        )

    records = tuple(
        sorted(history, key=lambda item: (item.symbol, item.event_date, item.available_at))
    )
    return CorporateActionAvailabilityHistoryResult(
        records=records,
        coverage_by_source=coverage_by_source,
        unmatched_reasons=tuple(sorted(unmatched)),
        source_manifest=tuple(sorted(manifest)),
    )


def write_corporate_action_availability_history(
    result: CorporateActionAvailabilityHistoryResult,
    *,
    output_root: Path,
    forbidden_roots: Iterable[Path] = (),
) -> dict[str, Path]:
    root = Path(output_root).resolve()
    resolved_forbidden = tuple(Path(path).resolve() for path in forbidden_roots)
    if any(root == forbidden or root.is_relative_to(forbidden) for forbidden in resolved_forbidden):
        raise ValueError("corporate_action_output_forbidden_root")
    root.mkdir(parents=True, exist_ok=True)
    timeline = root / "corporate_action_availability_timeline.csv"
    coverage = root / "corporate_action_availability_coverage.json"
    manifest = root / "corporate_action_availability_manifest.json"
    existing = tuple(path for path in (timeline, coverage, manifest) if path.exists())
    if existing:
        names = ",".join(path.name for path in existing)
        raise FileExistsError(f"corporate_action_output_exists:{names}")
    staging = root / f".corporate-action-{uuid4().hex}"
    staging.mkdir()
    staged_timeline = staging / timeline.name
    staged_coverage = staging / coverage.name
    staged_manifest = staging / manifest.name
    fieldnames = tuple(CorporateEventRecord.__dataclass_fields__)
    try:
        with staged_timeline.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for record in result.records:
                writer.writerow({key: _serialize(getattr(record, key)) for key in fieldnames})
        staged_coverage.write_text(
            json.dumps(
                {
                    source_id: _coverage_payload(item)
                    for source_id, item in sorted(result.coverage_by_source.items())
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        staged_manifest.write_text(
            json.dumps(
                {
                    "schema_version": "corporate-action-availability.v1",
                    "sources": [list(item) for item in result.source_manifest],
                    "unmatched": [list(item) for item in result.unmatched_reasons],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        for staged, target in (
            (staged_timeline, timeline),
            (staged_coverage, coverage),
            (staged_manifest, manifest),
        ):
            staged.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"timeline": timeline, "coverage": coverage, "manifest": manifest}


def _append_event_revision(
    history: list[CorporateEventRecord], candidate: CorporateEventRecord
) -> None:
    same = [
        item
        for item in history
        if item.source_id == candidate.source_id
        and item.source_event_id == candidate.source_event_id
        and item.revision == candidate.revision
    ]
    if same:
        if same[0].content_hash != candidate.content_hash:
            raise ValueError("revision_content_overwrite")
        return
    if candidate.revision > 1:
        parents = [
            item
            for item in history
            if item.source_id == candidate.source_id
            and item.source_event_id == candidate.source_event_id
            and item.revision == candidate.parent_revision
        ]
        if not parents:
            raise ValueError("revision_parent_not_found")
        if candidate.available_at < parents[0].available_at:
            raise ValueError("revision_before_parent_available")
    history.append(candidate)


def _coverage_payload(item: CorporateSourceCoverageDiagnostics) -> dict[str, object]:
    payload = asdict(item)
    payload["coverage_start"] = _serialize(item.coverage_start)
    payload["coverage_end"] = _serialize(item.coverage_end)
    payload["coverage_unknown"] = item.coverage_unknown
    return payload


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _serialize(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""
    return value
