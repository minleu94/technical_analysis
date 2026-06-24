from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CoverageStatus(str, Enum):
    AUTOMATED = "automated"
    EXISTING_TEST_BRIDGED = "existing-test-bridged"
    MANUAL_ONLY = "manual-only"
    BLOCKED = "blocked"
    NOT_YET_AUTOMATED = "not-yet-automated"
    RETIRED = "retired"


class ManualHealthcheckStatus(str, Enum):
    PASSED = "通過"
    FIXED_PENDING_VERIFICATION = "已修正待驗證"
    NEEDS_CONFIRMATION = "需確認"
    LATER_DESIGN = "後續設計"
    NOT_FIXED = "未修正"
    INVESTIGATED_NOT_PARALLELIZED = "已排查，未平行化"
    UNKNOWN = "unknown"


GAP_STATUSES = {
    CoverageStatus.MANUAL_ONLY,
    CoverageStatus.BLOCKED,
    CoverageStatus.NOT_YET_AUTOMATED,
}


@dataclass(frozen=True)
class HealthcheckCoverageItem:
    healthcheck_id: str
    title: str
    status: CoverageStatus
    manual_status: ManualHealthcheckStatus = ManualHealthcheckStatus.UNKNOWN
    evidence: str = ""
    owner: str = ""
    notes: str = ""
    source_batch: str = ""
    blocked_reason: str = ""


def detect_coverage_gaps(
    items: tuple[HealthcheckCoverageItem, ...],
) -> tuple[HealthcheckCoverageItem, ...]:
    return tuple(item for item in items if item.status in GAP_STATUSES)
