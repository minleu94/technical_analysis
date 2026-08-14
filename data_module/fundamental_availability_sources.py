"""受治理的月營收 ``available_date`` 來源契約。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from data_module.fundamental_availability import (
    FIRST_OBSERVED_EVIDENCE_CLASSES,
    FORMAL_AVAILABILITY_CONTRACT_VERSION,
    RETROACTIVE_BASELINE_SOURCE,
    FundamentalAvailabilityInput,
    FormalAvailabilityProvenance,
    parse_formal_official_provenance,
    resolve_fundamental_availability,
)
from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality


AvailabilityKey = tuple[str, str]
_BASE_MONTHLY_REVENUE_AVAILABILITY_COLUMNS = (
    "stock_code",
    "period",
    "as_of_date",
    "announced_date",
    "available_date",
    "source",
    "source_version",
)
MONTHLY_REVENUE_FORMAL_PROVENANCE_COLUMNS = (
    "availability_contract_version",
    "evidence_class",
    "source_hash",
    "revision",
    "parent_revision",
)
MONTHLY_REVENUE_AVAILABILITY_COLUMNS = (
    *_BASE_MONTHLY_REVENUE_AVAILABILITY_COLUMNS,
    *MONTHLY_REVENUE_FORMAL_PROVENANCE_COLUMNS,
)

MONTHLY_REVENUE_FORMAL_AVAILABILITY_SOURCES = frozenset(
    {
        "manual.twse_monthly_revenue_announcement_log",
        "twse.monthly_revenue_announcement",
        "tpex.monthly_revenue_announcement",
        "mops.monthly_revenue_announcement",
        "tej.monthly_revenue_announcement_pit",
    }
)
MONTHLY_REVENUE_BASELINE_AVAILABILITY_SOURCES = frozenset(
    {RETROACTIVE_BASELINE_SOURCE}
)
MONTHLY_REVENUE_ALLOWED_AVAILABILITY_SOURCES = frozenset(
    {
        *MONTHLY_REVENUE_FORMAL_AVAILABILITY_SOURCES,
        *MONTHLY_REVENUE_BASELINE_AVAILABILITY_SOURCES,
    }
)

# Only the already-materialized 2026-06 official mappings may cross the legacy
# compatibility bridge.  New ingestion must use ``formal-availability.v2``.
# Keep this as exact source/version pairs: a prefix would accidentally admit a
# future source snapshot without the required evidence fields.
_LEGACY_OFFICIAL_SOURCE_VERSIONS = frozenset(
    {
        (
            "twse.monthly_revenue_announcement",
            "twse-openapi-t187ap05-l-2026-07-14",
        ),
        (
            "tpex.monthly_revenue_announcement",
            "tpex-openapi-mopsfin-t187ap05-o-2026-07-14",
        ),
    }
)
_FIRST_OBSERVED_SOURCE = "manual.available_date_mapping"


@dataclass(frozen=True)
class FundamentalAvailabilityOverride:
    stock_code: str
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
class FundamentalAvailabilityOverrideLoadResult:
    overrides: dict[AvailabilityKey, FundamentalAvailabilityOverride]
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", dict(self.overrides))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def load_monthly_revenue_availability_overrides(
    rows: list[Mapping[str, str]],
) -> FundamentalAvailabilityOverrideLoadResult:
    """讀取 mapping，且在 loader 層就阻擋 first-seen 繞過 backfill gate。"""

    overrides: dict[AvailabilityKey, FundamentalAvailabilityOverride] = {}
    formal_candidates: dict[AvailabilityKey, list[FundamentalAvailabilityOverride]] = {}
    diagnostics: list[FactorDiagnostic] = []

    for row in rows:
        stock_code = row.get("stock_code", "").strip()
        period = row.get("period", "").strip()
        source = row.get("source", "").strip()
        source_version = row.get("source_version", "").strip()
        factor_name = "fundamental.availability"

        if source == "financial_data.monthly_revenue_csv":
            diagnostics.append(
                FactorDiagnostic(
                    code="fundamental_availability.raw_csv_not_available_source",
                    factor_name=factor_name,
                    stock_code=stock_code,
                    message=(
                        "raw monthly revenue CSV date is not an announcement or "
                        f"available_date source; period={period}"
                    ),
                )
            )
            continue

        provenance, provenance_mode, provenance_diagnostics = _resolve_provenance(
            row,
            source=source,
            source_version=source_version,
            stock_code=stock_code,
            period=period,
        )
        diagnostics.extend(provenance_diagnostics)
        if provenance_mode is None:
            continue

        try:
            as_of_date = _parse_required_date(row.get("as_of_date", ""))
        except ValueError:
            diagnostics.append(_invalid_date_diagnostic(stock_code, period, "as_of_date"))
            continue

        try:
            announced_date = _parse_optional_date(row.get("announced_date", ""))
            available_date = _parse_optional_date(row.get("available_date", ""))
        except ValueError as exc:
            diagnostics.append(_invalid_date_diagnostic(stock_code, period, str(exc)))
            continue

        if provenance_mode != "retroactive_baseline" and announced_date is None:
            diagnostics.append(
                _provenance_diagnostic(
                    "official_announcement_missing",
                    stock_code,
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

        if provenance_mode == "retroactive_baseline":
            evidence_class = "retroactive_baseline"
            source_hash = ""
            revision = 0
            parent_revision = None
        elif provenance_mode == "legacy_official_compatibility":
            evidence_class = "legacy_official_compatibility"
            source_hash = ""
            revision = 1
            parent_revision = None
        else:
            assert provenance is not None
            evidence_class = provenance.evidence_class
            source_hash = provenance.source_hash
            revision = provenance.revision
            parent_revision = provenance.parent_revision

        override = FundamentalAvailabilityOverride(
            stock_code=stock_code,
            period=period,
            as_of_date=as_of_date,
            announced_date=resolution.announced_date,
            available_date=resolution.available_date,
            quality=resolution.quality,
            source=source,
            source_version=source_version,
            evidence_class=evidence_class,
            source_hash=source_hash,
            revision=revision,
            parent_revision=parent_revision,
            provenance_mode=provenance_mode,
        )
        key = (stock_code, period)
        if provenance_mode == "retroactive_baseline":
            overrides[key] = override
        else:
            formal_candidates.setdefault(key, []).append(override)

    for key, candidates in formal_candidates.items():
        latest, chain_diagnostics = _select_latest_formal_revision(candidates)
        diagnostics.extend(
            _provenance_diagnostic(code, key[0], key[1], message)
            for code, message in chain_diagnostics
        )
        if latest is not None:
            overrides[key] = latest

    return FundamentalAvailabilityOverrideLoadResult(
        overrides=overrides,
        diagnostics=tuple(diagnostics),
    )


def load_monthly_revenue_availability_overrides_csv(
    path: Path,
) -> FundamentalAvailabilityOverrideLoadResult:
    path = Path(path)
    if not path.exists():
        return FundamentalAvailabilityOverrideLoadResult(
            overrides={},
            diagnostics=(
                FactorDiagnostic(
                    code="fundamental_availability.mapping_file_missing",
                    factor_name="fundamental.availability",
                    stock_code="",
                    message=f"monthly revenue availability mapping file missing; path={path}",
                ),
            ),
        )

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        missing_columns = [
            column for column in _BASE_MONTHLY_REVENUE_AVAILABILITY_COLUMNS if column not in fieldnames
        ]
        if missing_columns:
            return FundamentalAvailabilityOverrideLoadResult(
                overrides={},
                diagnostics=(
                    FactorDiagnostic(
                        code="fundamental_availability.mapping_missing_columns",
                        factor_name="fundamental.availability",
                        stock_code="",
                        message=(
                            "monthly revenue availability mapping missing required columns; "
                            f"path={path}; missing={','.join(missing_columns)}"
                        ),
                    ),
                ),
            )

        return load_monthly_revenue_availability_overrides(list(reader))


def _resolve_provenance(
    row: Mapping[str, str],
    *,
    source: str,
    source_version: str,
    stock_code: str,
    period: str,
) -> tuple[
    FormalAvailabilityProvenance | None,
    str | None,
    tuple[FactorDiagnostic, ...],
]:
    evidence_class = (row.get("evidence_class") or "").strip()
    contract_version = (row.get("availability_contract_version") or "").strip()

    if (
        source == _FIRST_OBSERVED_SOURCE
        or evidence_class in FIRST_OBSERVED_EVIDENCE_CLASSES
        or _looks_like_first_observed_value(source)
        or _looks_like_first_observed_value(source_version)
    ):
        return None, None, (
            _provenance_diagnostic(
                "first_observed_evidence_not_formal",
                stock_code,
                period,
                "local first-seen / first-observed evidence is shadow-only and cannot "
                "be accepted as a formal PIT availability mapping",
            ),
        )

    if source in MONTHLY_REVENUE_BASELINE_AVAILABILITY_SOURCES:
        return None, "retroactive_baseline", ()

    if source not in MONTHLY_REVENUE_FORMAL_AVAILABILITY_SOURCES:
        return None, None, (
            _provenance_diagnostic(
                "unsupported_available_date_source",
                stock_code,
                period,
                f"monthly revenue availability source is not formally governed; source={source}",
            ),
        )

    provenance_values_present = any(
        (row.get(column) or "").strip()
        for column in MONTHLY_REVENUE_FORMAL_PROVENANCE_COLUMNS
    )
    if not provenance_values_present:
        if _is_legacy_official_mapping(source, source_version):
            return None, "legacy_official_compatibility", ()
        return None, None, (
            _provenance_diagnostic(
                "formal_provenance_missing",
                stock_code,
                period,
                "new official mapping must declare formal-availability.v2 provenance; "
                "only the bounded TWSE/TPEx legacy compatibility mappings are allowed without it",
            ),
        )

    if contract_version != FORMAL_AVAILABILITY_CONTRACT_VERSION:
        return None, None, (
            _provenance_diagnostic(
                "unsupported_provenance_contract_version",
                stock_code,
                period,
                f"expected={FORMAL_AVAILABILITY_CONTRACT_VERSION}; actual={contract_version or 'missing'}",
            ),
        )
    if not source_version:
        return None, None, (
            _provenance_diagnostic(
                "formal_source_version_missing",
                stock_code,
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
                period,
                "official mapping provenance failed validation; "
                f"issue={issue}",
            )
            for issue in issues
        )
    assert provenance is not None
    return provenance, "formal_v2", ()


def _select_latest_formal_revision(
    candidates: list[FundamentalAvailabilityOverride],
) -> tuple[
    FundamentalAvailabilityOverride | None,
    tuple[tuple[str, str], ...],
]:
    by_revision: dict[int, FundamentalAvailabilityOverride] = {}
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


def _is_legacy_official_mapping(source: str, source_version: str) -> bool:
    return (source, source_version) in _LEGACY_OFFICIAL_SOURCE_VERSIONS


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


def _invalid_date_diagnostic(stock_code: str, period: str, field_name: str) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=f"fundamental_availability.invalid_{field_name}",
        factor_name="fundamental.availability",
        stock_code=stock_code,
        message=f"availability mapping has invalid date field; period={period}; field={field_name}",
    )


def _provenance_diagnostic(
    code: str,
    stock_code: str,
    period: str,
    message: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=f"fundamental_availability.{code}",
        factor_name="fundamental.availability",
        stock_code=stock_code,
        message=f"{message}; period={period}",
    )
