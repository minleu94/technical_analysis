"""正式 SQLite 的 PIT 歷史 coverage 唯讀稽核。"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SourceYearCoverage:
    source_id: str
    year: str
    total: int
    matched_official: int
    matched_observed_only: int
    unmatched: int
    future_blocked: int
    revision: int
    eligible: int


@dataclass(frozen=True)
class FamilyCoverage:
    family_id: str
    table_name: str
    count_unit: str
    status: str
    total: int
    matched_official: int
    matched_observed_only: int
    unmatched: int
    future_blocked: int
    revision: int
    eligible: int
    source_year_rows: tuple[SourceYearCoverage, ...]
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PITHistoricalCoverageAuditReport:
    audit_cutoff: str
    database_sha256: str
    families: tuple[FamilyCoverage, ...]
    schema_version: str = "pit-historical-coverage-audit.v1"
    database_open_mode: str = "read_only"
    source_acceptance_changed: bool = False
    production_apply_performed: bool = False

    @property
    def family_by_id(self) -> dict[str, FamilyCoverage]:
        return {family.family_id: family for family in self.families}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "audit_cutoff": self.audit_cutoff,
            "database_sha256": self.database_sha256,
            "database_open_mode": self.database_open_mode,
            "source_acceptance_changed": self.source_acceptance_changed,
            "production_apply_performed": self.production_apply_performed,
            "families": [
                {
                    **asdict(family),
                    "source_year_rows": [asdict(row) for row in family.source_year_rows],
                }
                for family in self.families
            ],
        }


_FAMILY_SPECS = (
    ("monthly_revenue", "fundamental_monthly_revenues", "database_rows"),
    ("quarterly_statement", "fundamental_statement_items", "statement_item_rows"),
    ("corporate_action", "corporate_action_events", "event_rows"),
)


def audit_pit_historical_coverage(
    *,
    db_path: Path,
    audit_cutoff: date,
) -> PITHistoricalCoverageAuditReport:
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"formal database missing: {path}")
    database_hash = _sha256_file(path)
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        families = tuple(
            _audit_family(
                connection,
                family_id=family_id,
                table_name=table_name,
                count_unit=count_unit,
                audit_cutoff=audit_cutoff,
                table_names=table_names,
            )
            for family_id, table_name, count_unit in _FAMILY_SPECS
        )
    return PITHistoricalCoverageAuditReport(
        audit_cutoff=audit_cutoff.isoformat(),
        database_sha256=database_hash,
        families=families,
    )


def _audit_family(
    connection: sqlite3.Connection,
    *,
    family_id: str,
    table_name: str,
    count_unit: str,
    audit_cutoff: date,
    table_names: set[str],
) -> FamilyCoverage:
    if table_name not in table_names:
        return FamilyCoverage(
            family_id=family_id,
            table_name=table_name,
            count_unit=count_unit,
            status="coverage_deferred",
            total=0,
            matched_official=0,
            matched_observed_only=0,
            unmatched=0,
            future_blocked=0,
            revision=0,
            eligible=0,
            source_year_rows=(),
            blockers=("source_table_missing", "coverage_unknown"),
        )

    columns = {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table_name}")')
    }
    source_column = _first(columns, ("source_id", "source"))
    quality_column = _first(columns, ("quality_tier", "quality"))
    available_column = _first(columns, ("available_at", "available_date"))
    year_column = _first(
        columns,
        ("period_or_event_date", "as_of_date", "period_end", "period", "event_date"),
    )
    revision_column = _first(columns, ("revision", "revision_number"))
    required = {
        "source": source_column,
        "quality": quality_column,
        "available": available_column,
        "year": year_column,
    }
    missing = tuple(name for name, column in required.items() if column is None)
    if missing:
        total = int(connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])
        return FamilyCoverage(
            family_id=family_id,
            table_name=table_name,
            count_unit=count_unit,
            status="coverage_unknown",
            total=total,
            matched_official=0,
            matched_observed_only=0,
            unmatched=total,
            future_blocked=0,
            revision=0,
            eligible=0,
            source_year_rows=(),
            blockers=tuple(f"missing_{name}_column" for name in missing),
        )

    selected = [source_column, quality_column, available_column, year_column]
    if revision_column is not None:
        selected.append(revision_column)
    query = "SELECT " + ", ".join(f'"{column}"' for column in selected) + f' FROM "{table_name}"'
    groups: dict[tuple[str, str], list[int]] = {}
    for row in connection.execute(query):
        source_id = str(row[source_column] or "unknown_source")
        year = _year(str(row[year_column] or ""))
        counts = groups.setdefault((source_id, year), [0, 0, 0, 0, 0, 0, 0])
        counts[0] += 1
        quality = str(row[quality_column] or "").strip().lower()
        available = _optional_date(str(row[available_column] or ""))
        future = available is not None and available > audit_cutoff
        if quality == "official" and available is not None:
            counts[1] += 1
        elif quality in {"observed", "observed_only"} and available is not None:
            counts[2] += 1
        else:
            counts[3] += 1
        if future:
            counts[4] += 1
        if revision_column is not None and _revision(row[revision_column]) > 1:
            counts[5] += 1
        if quality in {"official", "observed", "observed_only"} and available is not None and not future:
            counts[6] += 1

    source_rows = tuple(
        SourceYearCoverage(
            source_id=source_id,
            year=year,
            total=counts[0],
            matched_official=counts[1],
            matched_observed_only=counts[2],
            unmatched=counts[3],
            future_blocked=counts[4],
            revision=counts[5],
            eligible=counts[6],
        )
        for (source_id, year), counts in sorted(groups.items())
    )
    return FamilyCoverage(
        family_id=family_id,
        table_name=table_name,
        count_unit=count_unit,
        status="audited",
        total=sum(row.total for row in source_rows),
        matched_official=sum(row.matched_official for row in source_rows),
        matched_observed_only=sum(row.matched_observed_only for row in source_rows),
        unmatched=sum(row.unmatched for row in source_rows),
        future_blocked=sum(row.future_blocked for row in source_rows),
        revision=sum(row.revision for row in source_rows),
        eligible=sum(row.eligible for row in source_rows),
        source_year_rows=source_rows,
        blockers=("revision_column_missing",) if revision_column is None else (),
    )


def _first(columns: set[str], candidates: Iterable[str]) -> str | None:
    return next((candidate for candidate in candidates if candidate in columns), None)


def _year(value: str) -> str:
    return value[:4] if len(value) >= 4 and value[:4].isdigit() else "unknown"


def _optional_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _revision(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
