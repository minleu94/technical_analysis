"""Governed quarterly-statement ``available_date`` source contract."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping

from data_module.fundamental_availability import (
    FIRST_OBSERVED_EVIDENCE_CLASSES,
    FORMAL_AVAILABILITY_CONTRACT_VERSION,
    FundamentalAvailabilityInput,
    FormalAvailabilityProvenance,
    RETROACTIVE_STATEMENT_BASELINE_SOURCE,
    parse_formal_official_provenance,
    resolve_fundamental_availability,
)
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


StatementAvailabilityKey = tuple[str, str, str]
_BASE_STATEMENT_AVAILABILITY_COLUMNS = (
    "stock_code",
    "statement_type",
    "period",
    "as_of_date",
    "announced_date",
    "available_date",
    "source",
    "source_version",
)
STATEMENT_FORMAL_PROVENANCE_COLUMNS = (
    "availability_contract_version",
    "evidence_class",
    "source_hash",
    "revision",
    "parent_revision",
)
STATEMENT_AVAILABILITY_COLUMNS = (
    *_BASE_STATEMENT_AVAILABILITY_COLUMNS,
    *STATEMENT_FORMAL_PROVENANCE_COLUMNS,
)
STATEMENT_FORMAL_AVAILABILITY_SOURCES = frozenset(
    {
        "manual.statement_available_date_mapping",
        "tej.statement_announcement_pit",
        "mops.ezsearch.statement_publication",
    }
)
STATEMENT_BASELINE_AVAILABILITY_SOURCES = frozenset(
    {RETROACTIVE_STATEMENT_BASELINE_SOURCE}
)
STATEMENT_ALLOWED_AVAILABILITY_SOURCES = frozenset(
    {
        *STATEMENT_FORMAL_AVAILABILITY_SOURCES,
        *STATEMENT_BASELINE_AVAILABILITY_SOURCES,
    }
)
RAW_STATEMENT_SOURCES = frozenset(
    {
        "financial_data.income_statement_csv",
        "financial_data.balance_sheet_csv",
        "financial_data.cash_flows_statement_csv",
    }
)


@dataclass(frozen=True)
class StatementAvailabilityOverride:
    stock_code: str
    statement_type: str
    period: str
    as_of_date: date
    announced_date: date | None
    available_date: date
    quality: FactorQuality
    source: str
    source_version: str
    evidence_class: str = ""
    source_hash: str = ""
    revision: int = 0
    parent_revision: int | None = None
    provenance_mode: str = ""


@dataclass(frozen=True)
class StatementAvailabilityOverrideLoadResult:
    overrides: dict[StatementAvailabilityKey, StatementAvailabilityOverride]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", dict(self.overrides))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def load_statement_availability_overrides(
    rows: list[Mapping[str, str]],
) -> StatementAvailabilityOverrideLoadResult:
    """Load a mapping while keeping first-seen evidence out of the formal lane."""

    overrides: dict[StatementAvailabilityKey, StatementAvailabilityOverride] = {}
    formal_candidates: dict[
        StatementAvailabilityKey,
        list[StatementAvailabilityOverride],
    ] = {}
    diagnostics: list[FactorDiagnostic] = []

    for row in rows:
        stock_code = row.get("stock_code", "").strip()
        statement_type = row.get("statement_type", "").strip()
        period = row.get("period", "").strip()
        source = row.get("source", "").strip()
        source_version = row.get("source_version", "").strip()

        if source in RAW_STATEMENT_SOURCES:
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_statement_availability.raw_csv_not_available_source",
                    factor_name="fundamental.statement_availability",
                    stock_code=stock_code,
                    message=(
                        "raw statement CSV date is not an announcement or "
                        "available_date source; "
                        f"statement_type={statement_type}; period={period}"
                    ),
                )
            )
            continue

        provenance, provenance_mode, provenance_diagnostics = _resolve_provenance(
            row,
            source=source,
            source_version=source_version,
            stock_code=stock_code,
            statement_type=statement_type,
            period=period,
        )
        diagnostics.extend(provenance_diagnostics)
        if provenance_mode is None:
            continue

        try:
            as_of_date = _parse_required_date(row.get("as_of_date", ""))
        except ValueError:
            diagnostics.append(
                _invalid_date_diagnostic(stock_code, statement_type, period, "as_of_date")
            )
            continue

        try:
            announced_date = _parse_optional_date(row.get("announced_date", ""))
            available_date = _parse_optional_date(row.get("available_date", ""))
        except ValueError as exc:
            diagnostics.append(
                _invalid_date_diagnostic(stock_code, statement_type, period, str(exc))
            )
            continue

        if provenance_mode != "retroactive_baseline" and announced_date is None:
            diagnostics.append(
                _provenance_diagnostic(
                    "official_announcement_missing",
                    stock_code,
                    statement_type,
                    period,
                    "formal availability mapping requires an explicit official announcement date",
                )
            )
            continue

        resolution = resolve_fundamental_availability(
            FundamentalAvailabilityInput(
                stock_code=stock_code,
                period=period,
                as_of_date=as_of_date,
                announced_date=announced_date,
                explicit_available_date=available_date,
                source=source,
            )
        )
        diagnostics.extend(resolution.diagnostics)
        if resolution.available_date is None:
            continue

        override = StatementAvailabilityOverride(
            stock_code=stock_code,
            statement_type=statement_type,
            period=period,
            as_of_date=as_of_date,
            announced_date=resolution.announced_date,
            available_date=resolution.available_date,
            quality=resolution.quality,
            source=source,
            source_version=source_version,
            evidence_class=(
                "retroactive_baseline" if provenance is None else provenance.evidence_class
            ),
            source_hash="" if provenance is None else provenance.source_hash,
            revision=0 if provenance is None else provenance.revision,
            parent_revision=None if provenance is None else provenance.parent_revision,
            provenance_mode=provenance_mode,
        )
        key = (stock_code, statement_type, period)
        if provenance_mode == "retroactive_baseline":
            overrides[key] = override
        else:
            formal_candidates.setdefault(key, []).append(override)

    for key, candidates in formal_candidates.items():
        latest, chain_diagnostics = _select_latest_formal_revision(candidates)
        diagnostics.extend(
            _provenance_diagnostic(code, key[0], key[1], key[2], message)
            for code, message in chain_diagnostics
        )
        if latest is not None:
            overrides[key] = latest

    return StatementAvailabilityOverrideLoadResult(
        overrides=overrides,
        diagnostics=tuple(diagnostics),
    )


def load_statement_availability_overrides_csv(
    path: Path,
) -> StatementAvailabilityOverrideLoadResult:
    return load_statement_availability_overrides_csv_files((Path(path),))


def load_statement_availability_overrides_csv_files(
    paths: Iterable[Path | str],
) -> StatementAvailabilityOverrideLoadResult:
    """Load multiple candidate mappings as one governed revision set.

    Identical rows repeated across overlapping query windows are ignored. Rows
    with the same natural key but different provenance remain visible to the
    formal revision-chain validator, which will fail closed instead of
    guessing which candidate should win.
    """

    rows: list[Mapping[str, str]] = []
    diagnostics: list[FactorDiagnostic] = []
    seen_rows: set[tuple[tuple[str, str], ...]] = set()
    normalized_paths = tuple(Path(path) for path in paths)
    if not normalized_paths:
        return StatementAvailabilityOverrideLoadResult(
            overrides={},
            diagnostics=(
                FactorDiagnostic(
                    code="fundamental_statement_availability.mapping_file_missing",
                    factor_name="fundamental.statement_availability",
                    stock_code="",
                    message="statement availability mapping file list is empty",
                ),
            ),
        )

    for path in normalized_paths:
        file_rows, file_diagnostics = _read_statement_availability_csv(path)
        diagnostics.extend(file_diagnostics)
        for row in file_rows:
            normalized_row = {
                str(key): str(value or "")
                for key, value in row.items()
            }
            fingerprint = tuple(sorted(normalized_row.items()))
            if fingerprint in seen_rows:
                continue
            seen_rows.add(fingerprint)
            rows.append(normalized_row)

    loaded = load_statement_availability_overrides(rows)
    diagnostics.extend(loaded.diagnostics)
    return StatementAvailabilityOverrideLoadResult(
        overrides=loaded.overrides,
        diagnostics=tuple(diagnostics),
    )


def _read_statement_availability_csv(
    path: Path,
) -> tuple[list[Mapping[str, str]], tuple[FactorDiagnostic, ...]]:
    path = Path(path)
    if not path.exists():
        return [], (
            FactorDiagnostic(
                code="fundamental_statement_availability.mapping_file_missing",
                factor_name="fundamental.statement_availability",
                stock_code="",
                message=f"statement availability mapping file missing; path={path}",
            ),
        )

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        missing_columns = [
            column for column in _BASE_STATEMENT_AVAILABILITY_COLUMNS if column not in fieldnames
        ]
        if missing_columns:
            return [], (
                FactorDiagnostic(
                    code="fundamental_statement_availability.mapping_missing_columns",
                    factor_name="fundamental.statement_availability",
                    stock_code="",
                    message=(
                        "statement availability mapping missing required columns; "
                        f"path={path}; missing={','.join(missing_columns)}"
                    ),
                ),
            )
        return [dict(row) for row in reader], ()


def _resolve_provenance(
    row: Mapping[str, str],
    *,
    source: str,
    source_version: str,
    stock_code: str,
    statement_type: str,
    period: str,
) -> tuple[
    FormalAvailabilityProvenance | None,
    str | None,
    tuple[FactorDiagnostic, ...],
]:
    evidence_class = (row.get("evidence_class") or "").strip()
    contract_version = (row.get("availability_contract_version") or "").strip()

    if (
        evidence_class in FIRST_OBSERVED_EVIDENCE_CLASSES
        or _looks_like_first_observed_value(source)
        or _looks_like_first_observed_value(source_version)
    ):
        return None, None, (
            _provenance_diagnostic(
                "first_observed_evidence_not_formal",
                stock_code,
                statement_type,
                period,
                "local first-seen / first-observed evidence is shadow-only and cannot "
                "be accepted as a formal PIT availability mapping",
            ),
        )

    if source in STATEMENT_BASELINE_AVAILABILITY_SOURCES:
        return None, "retroactive_baseline", ()

    if source not in STATEMENT_FORMAL_AVAILABILITY_SOURCES:
        return None, None, (
            _provenance_diagnostic(
                "unsupported_available_date_source",
                stock_code,
                statement_type,
                period,
                f"statement availability source is not formally governed; source={source}",
            ),
        )

    provenance_values_present = any(
        (row.get(column) or "").strip() for column in STATEMENT_FORMAL_PROVENANCE_COLUMNS
    )
    if not provenance_values_present:
        return None, None, (
            _provenance_diagnostic(
                "formal_provenance_missing",
                stock_code,
                statement_type,
                period,
                "official mapping must declare formal-availability.v2 provenance",
            ),
        )

    if contract_version != FORMAL_AVAILABILITY_CONTRACT_VERSION:
        return None, None, (
            _provenance_diagnostic(
                "unsupported_provenance_contract_version",
                stock_code,
                statement_type,
                period,
                f"expected={FORMAL_AVAILABILITY_CONTRACT_VERSION}; "
                f"actual={contract_version or 'missing'}",
            ),
        )
    if not source_version:
        return None, None, (
            _provenance_diagnostic(
                "formal_source_version_missing",
                stock_code,
                statement_type,
                period,
                "official mapping requires a non-empty source_version",
            ),
        )

    provenance, issues = parse_formal_official_provenance(
        evidence_class=evidence_class,
        source_hash=row.get("source_hash"),
        revision=row.get("revision"),
        parent_revision=row.get("parent_revision"),
    )
    if issues:
        return None, None, tuple(
            _provenance_diagnostic(
                f"formal_{issue}",
                stock_code,
                statement_type,
                period,
                f"official mapping provenance failed validation; issue={issue}",
            )
            for issue in issues
        )
    assert provenance is not None
    return provenance, "formal_v2", ()


def _select_latest_formal_revision(
    candidates: list[StatementAvailabilityOverride],
) -> tuple[
    StatementAvailabilityOverride | None,
    tuple[tuple[str, str], ...],
]:
    by_revision: dict[int, StatementAvailabilityOverride] = {}
    issues: list[tuple[str, str]] = []
    for candidate in candidates:
        existing = by_revision.get(candidate.revision)
        if existing is not None:
            issues.append(
                (
                    "formal_duplicate_revision",
                    f"revision={candidate.revision} occurs more than once for the same natural key",
                )
            )
            continue
        by_revision[candidate.revision] = candidate

    if issues:
        return None, tuple(issues)

    revisions = sorted(by_revision)
    if revisions != list(range(1, len(revisions) + 1)):
        return None, (
            (
                "formal_revision_chain_incomplete",
                f"revisions must be contiguous from 1; found={revisions}",
            ),
        )
    for revision in revisions:
        candidate = by_revision[revision]
        if revision == 1 and candidate.parent_revision is not None:
            return None, (
                (
                    "formal_initial_revision_has_parent",
                    "revision=1 must not declare parent_revision",
                ),
            )
        if revision > 1 and candidate.parent_revision != revision - 1:
            return None, (
                (
                    "formal_revision_parent_missing",
                    f"revision={revision} must reference parent_revision={revision - 1}",
                ),
            )
    return by_revision[revisions[-1]], ()


def _looks_like_first_observed_value(value: str) -> bool:
    normalized = value.casefold()
    return any(
        token in normalized
        for token in (
            "first-seen",
            "first_seen",
            "first-observed",
            "first_observed",
            "observation",
        )
    )


def _parse_required_date(value: str) -> date:
    parsed = _parse_optional_date(value)
    if parsed is None:
        raise ValueError("required date is missing")
    return parsed


def _parse_optional_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("invalid_date") from exc


def _invalid_date_diagnostic(
    stock_code: str,
    statement_type: str,
    period: str,
    field_name: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=f"fundamental_statement_availability.invalid_{field_name}",
        factor_name="fundamental.statement_availability",
        stock_code=stock_code,
        message=(
            "statement availability mapping has invalid date field; "
            f"statement_type={statement_type}; period={period}; field={field_name}"
        ),
    )


def _provenance_diagnostic(
    code: str,
    stock_code: str,
    statement_type: str,
    period: str,
    message: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=f"fundamental_statement_availability.{code}",
        factor_name="fundamental.statement_availability",
        stock_code=stock_code,
        message=f"{message}; statement_type={statement_type}; period={period}",
    )
