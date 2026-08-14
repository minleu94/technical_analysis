"""基本面資料公告日與可得日解析政策。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Iterable

from decision_module.factors.factor_dtos import FactorDiagnostic, FactorQuality

RETROACTIVE_BASELINE_SOURCE = "manual.retroactive_baseline_mapping"
RETROACTIVE_STATEMENT_BASELINE_SOURCE = "manual.retroactive_statement_baseline_mapping"
RETROACTIVE_BASELINE_SOURCES = frozenset(
    {
        RETROACTIVE_BASELINE_SOURCE,
        RETROACTIVE_STATEMENT_BASELINE_SOURCE,
    }
)
RETROACTIVE_BACKFILL_DATE = date(2026, 6, 17)

# `available_date` is not enough to establish that a row was formally usable at
# a historical decision boundary.  Keep first-observed evidence in the
# research/shadow lane and require a separately verifiable official
# announcement record before a mapping can enter the formal lane.
OFFICIAL_ANNOUNCEMENT_EVIDENCE_CLASS = "official_announcement"
FORMAL_AVAILABILITY_CONTRACT_VERSION = "formal-availability.v2"
FIRST_OBSERVED_EVIDENCE_CLASSES = frozenset(
    {
        "first_observed",
        "local_first_seen",
        "observed_only",
    }
)
_SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


class AvailabilityEvidenceValidationError(ValueError):
    """可得性 evidence 違反時間或 revision contract。"""


@dataclass(frozen=True)
class FormalAvailabilityProvenance:
    """正式公告 mapping 所需的可稽核 provenance。

    此 DTO 只描述「可接受為正式公告 mapping」的證據。retroactive
    baseline 與 first-observed evidence 有不同用途，不能用這個 DTO 假裝成
    歷史公告證據。
    """

    evidence_class: str
    source_hash: str
    revision: int
    parent_revision: int | None


def parse_formal_official_provenance(
    *,
    evidence_class: str | None,
    source_hash: str | None,
    revision: str | int | None,
    parent_revision: str | int | None,
) -> tuple[FormalAvailabilityProvenance | None, tuple[str, ...]]:
    """解析並驗證正式公告 mapping 的 evidence／hash／revision contract.

    回傳的錯誤代碼刻意不綁定月營收或財報，讓兩個 availability loader
    都能以各自的 factor diagnostic prefix 呈現同一個 fail-closed 規則。
    """

    issues: list[str] = []
    normalized_class = (evidence_class or "").strip()
    if not normalized_class:
        issues.append("missing_evidence_class")
    elif normalized_class in FIRST_OBSERVED_EVIDENCE_CLASSES:
        issues.append("first_observed_evidence_not_formal")
    elif normalized_class != OFFICIAL_ANNOUNCEMENT_EVIDENCE_CLASS:
        issues.append("invalid_evidence_class")

    normalized_hash = (source_hash or "").strip()
    if not normalized_hash:
        issues.append("missing_source_hash")
    elif _SHA256_PATTERN.fullmatch(normalized_hash) is None:
        issues.append("invalid_source_hash")

    parsed_revision = _parse_provenance_revision(revision)
    if parsed_revision is None:
        issues.append("missing_or_invalid_revision")

    raw_parent = "" if parent_revision is None else str(parent_revision).strip()
    parsed_parent = _parse_provenance_revision(parent_revision) if raw_parent else None
    if raw_parent and parsed_parent is None:
        issues.append("invalid_parent_revision")

    if parsed_revision is not None:
        if parsed_revision == 1 and raw_parent:
            issues.append("initial_revision_has_parent")
        elif parsed_revision > 1:
            if parsed_parent is None:
                issues.append("revision_parent_missing")
            elif parsed_parent != parsed_revision - 1:
                issues.append("revision_parent_must_be_previous")

    if issues:
        return None, tuple(sorted(set(issues)))
    assert parsed_revision is not None
    return (
        FormalAvailabilityProvenance(
            evidence_class=normalized_class,
            source_hash=normalized_hash,
            revision=parsed_revision,
            parent_revision=parsed_parent,
        ),
        (),
    )


def _parse_provenance_revision(value: str | int | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed >= 1 else None


@dataclass(frozen=True)
class AvailabilityEvidenceRecord:
    """跨基本面與 corporate-action 共用的 append-only evidence record。"""

    source_id: str
    source_version: str
    source_hash: str
    symbol: str
    data_family: str
    period_or_event_date: date
    announcement_at: date | None
    first_observed_at: date | None
    available_at: date
    revision: int
    parent_revision: int | None
    effective_at: date | None
    quality_tier: str
    match_method: str
    content_hash: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.available_at < self.period_or_event_date:
            raise AvailabilityEvidenceValidationError("available_before_period_or_event")
        if self.announcement_at is not None and self.available_at < self.announcement_at:
            raise AvailabilityEvidenceValidationError("available_before_announcement")
        if self.revision < 1:
            raise AvailabilityEvidenceValidationError("invalid_revision")
        if self.revision == 1 and self.parent_revision is not None:
            raise AvailabilityEvidenceValidationError("initial_revision_has_parent")
        if self.revision > 1 and self.parent_revision is None:
            raise AvailabilityEvidenceValidationError("revision_parent_missing")

    @property
    def natural_key(self) -> tuple[str, str, str, date]:
        return (
            self.source_id,
            self.symbol,
            self.data_family,
            self.period_or_event_date,
        )


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    quality: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageWindow:
    source_id: str
    data_family: str
    coverage_start: date | None
    coverage_end: date | None
    quality: str


@dataclass(frozen=True)
class AvailabilityCoverageDiagnostics:
    total: int
    matched_official: int
    matched_observed_only: int
    unmatched: int
    duplicate: int
    revision: int
    future_blocked: int
    eligible: int


def evaluate_historical_feature_eligibility(
    record: AvailabilityEvidenceRecord,
    *,
    feature_cutoff: date,
) -> EligibilityResult:
    reasons: list[str] = []
    if (
        record.available_at == RETROACTIVE_BACKFILL_DATE
        and record.period_or_event_date < RETROACTIVE_BACKFILL_DATE
        and (
            record.source_id in RETROACTIVE_BASELINE_SOURCES
            or record.quality_tier == "retroactive_baseline"
        )
    ):
        reasons.append("retroactive_backfill_not_historical_availability")
    if record.available_at > feature_cutoff:
        reasons.append("available_after_feature_cutoff")
    if record.quality_tier in {"unmatched", "unknown"}:
        reasons.append("availability_evidence_unmatched")
    return EligibilityResult(
        eligible=not reasons,
        quality="eligible" if not reasons else "blocked",
        reasons=tuple(reasons),
    )


def append_availability_revision(
    history: tuple[AvailabilityEvidenceRecord, ...],
    candidate: AvailabilityEvidenceRecord,
) -> tuple[AvailabilityEvidenceRecord, ...]:
    same_revision = tuple(
        item
        for item in history
        if item.natural_key == candidate.natural_key and item.revision == candidate.revision
    )
    if same_revision:
        existing = same_revision[0]
        if existing.content_hash != candidate.content_hash:
            raise AvailabilityEvidenceValidationError("revision_content_overwrite")
        return history

    if candidate.revision == 1:
        if any(item.natural_key == candidate.natural_key for item in history):
            raise AvailabilityEvidenceValidationError("duplicate_initial_revision")
        return (*history, candidate)

    parents = tuple(
        item
        for item in history
        if item.natural_key == candidate.natural_key
        and item.revision == candidate.parent_revision
    )
    if not parents:
        raise AvailabilityEvidenceValidationError("revision_parent_not_found")
    if candidate.available_at < parents[0].available_at:
        raise AvailabilityEvidenceValidationError("revision_before_parent_available")
    return (*history, candidate)


def visible_evidence_as_of(
    records: Iterable[AvailabilityEvidenceRecord],
    *,
    as_of_date: date,
) -> tuple[AvailabilityEvidenceRecord, ...]:
    """只以 available_at 判斷可見性；event/effective date 不授予提前可見。"""

    return tuple(record for record in records if record.available_at <= as_of_date)


def evaluate_label_window_eligibility(
    *,
    label_start: date,
    label_end: date,
    coverage: CoverageWindow,
    strict: bool,
) -> EligibilityResult:
    covered = (
        coverage.quality in {"official", "observed"}
        and coverage.coverage_start is not None
        and coverage.coverage_end is not None
        and coverage.coverage_start <= label_start
        and coverage.coverage_end >= label_end
    )
    if covered:
        return EligibilityResult(eligible=True, quality="clean")
    return EligibilityResult(
        eligible=False,
        quality="blocked" if strict else "degraded",
        reasons=("coverage_unknown",),
    )


def summarize_availability_coverage(
    records: Iterable[AvailabilityEvidenceRecord],
    *,
    feature_cutoff: date,
) -> AvailabilityCoverageDiagnostics:
    items = tuple(records)
    identities = [(item.natural_key, item.revision) for item in items]
    return AvailabilityCoverageDiagnostics(
        total=len(items),
        matched_official=sum(item.quality_tier == "official" for item in items),
        matched_observed_only=sum(
            item.quality_tier == "observed_only" for item in items
        ),
        unmatched=sum(item.quality_tier in {"unmatched", "unknown"} for item in items),
        duplicate=len(identities) - len(set(identities)),
        revision=sum(item.revision > 1 for item in items),
        future_blocked=sum(item.available_at > feature_cutoff for item in items),
        eligible=sum(
            evaluate_historical_feature_eligibility(
                item,
                feature_cutoff=feature_cutoff,
            ).eligible
            for item in items
        ),
    )


@dataclass(frozen=True)
class FundamentalAvailabilityInput:
    stock_code: str
    period: str
    as_of_date: date
    announced_date: date | None
    explicit_available_date: date | None
    source: str


@dataclass(frozen=True)
class FundamentalAvailabilityResolution:
    announced_date: date | None
    available_date: date | None
    quality: FactorQuality
    diagnostics: tuple[FactorDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def resolve_fundamental_availability(
    observation: FundamentalAvailabilityInput,
) -> FundamentalAvailabilityResolution:
    factor_name = "fundamental.availability"
    diagnostics: list[FactorDiagnostic] = []

    available_date = observation.explicit_available_date
    if available_date is None:
        return FundamentalAvailabilityResolution(
            announced_date=observation.announced_date,
            available_date=None,
            quality=FactorQuality.MISSING,
            diagnostics=(
                _diagnostic(
                    observation,
                    factor_name,
                    "fundamental_availability.missing_available_date",
                    "fundamental observation has no explicit available_date",
                ),
            ),
        )

    if available_date < observation.as_of_date:
        return FundamentalAvailabilityResolution(
            announced_date=observation.announced_date,
            available_date=None,
            quality=FactorQuality.MISSING,
            diagnostics=(
                _diagnostic(
                    observation,
                    factor_name,
                    "fundamental_availability.available_before_period_end",
                    "available_date is before period end date",
                ),
            ),
        )

    if observation.announced_date is not None and available_date < observation.announced_date:
        return FundamentalAvailabilityResolution(
            announced_date=observation.announced_date,
            available_date=None,
            quality=FactorQuality.MISSING,
            diagnostics=(
                _diagnostic(
                    observation,
                    factor_name,
                    "fundamental_availability.available_before_announcement",
                    "available_date is before announced_date",
                ),
            ),
        )

    if observation.announced_date is None:
        if observation.source in RETROACTIVE_BASELINE_SOURCES:
            return FundamentalAvailabilityResolution(
                announced_date=None,
                available_date=available_date,
                quality=FactorQuality.DEGRADED,
                diagnostics=(),
            )
        diagnostics.append(
            _diagnostic(
                observation,
                factor_name,
                "fundamental_availability.missing_announced_date",
                "announced_date missing; available_date is explicit but quality is degraded",
            )
        )
        quality = FactorQuality.DEGRADED
    else:
        quality = FactorQuality.OBSERVED

    return FundamentalAvailabilityResolution(
        announced_date=observation.announced_date,
        available_date=available_date,
        quality=quality,
        diagnostics=tuple(diagnostics),
    )


def _diagnostic(
    observation: FundamentalAvailabilityInput,
    factor_name: str,
    code: str,
    message: str,
) -> FactorDiagnostic:
    return FactorDiagnostic(
        code=code,
        factor_name=factor_name,
        stock_code=observation.stock_code,
        message=f"{message}; period={observation.period}; source={observation.source}",
    )
