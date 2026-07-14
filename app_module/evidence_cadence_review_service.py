"""Read-only cadence projections for the EV1 shadow evidence ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from app_module.external_evidence_contracts import EvidenceOutcomeRevision, ExternalEvidenceDecisionSnapshot


@dataclass(frozen=True)
class EvidenceCadenceReviewPackage:
    cadence: str
    status: str
    primary_matured_count: int
    primary_effectiveness_denominator: int
    blockers: tuple[str, ...]


class EvidenceCadenceReviewService:
    """Projects operational readiness only; it never declares an External Gate met."""

    def build_daily(
        self,
        *,
        expected_operation_days: Sequence[str],
        snapshots: Sequence[ExternalEvidenceDecisionSnapshot],
        missing_reasons: Mapping[str, str],
    ) -> EvidenceCadenceReviewPackage:
        snapshot_days = {datetime.fromisoformat(item.decision_timestamp).date().isoformat() for item in snapshots}
        blockers: list[str] = []
        for operation_day in expected_operation_days:
            if operation_day not in snapshot_days and not str(missing_reasons.get(operation_day, "")).strip():
                blockers.append(f"missing_decision_or_reason:{operation_day}")
        return EvidenceCadenceReviewPackage(
            cadence="daily",
            status="indeterminate" if blockers else "manual_review_required",
            primary_matured_count=0,
            primary_effectiveness_denominator=0,
            blockers=tuple(blockers),
        )

    def build_monthly(
        self,
        *,
        snapshots: Sequence[ExternalEvidenceDecisionSnapshot],
        outcome_revisions: Sequence[EvidenceOutcomeRevision],
    ) -> EvidenceCadenceReviewPackage:
        registered_snapshots = {
            item.snapshot_id: item for item in snapshots if item.capture_kind == "manual_observed"
        }
        revisions_by_snapshot: dict[str, list[EvidenceOutcomeRevision]] = {
            snapshot_id: [] for snapshot_id in registered_snapshots
        }
        for revision in outcome_revisions:
            if revision.snapshot_id in revisions_by_snapshot and revision.window_trading_days == 20:
                revisions_by_snapshot[revision.snapshot_id].append(revision)

        current_revisions: list[EvidenceOutcomeRevision] = []
        for revisions in revisions_by_snapshot.values():
            parent_ids = {item.parent_revision_id for item in revisions if item.parent_revision_id is not None}
            leaves = [item for item in revisions if item.revision_id not in parent_ids]
            if len(leaves) == 1:
                current_revisions.append(leaves[0])
        primary_verified = tuple(item for item in current_revisions if item.status == "verified")
        primary_pending = any(item.status == "pending_maturity" for item in current_revisions)
        blockers = ("primary_horizon_pending",) if primary_pending else ()
        return EvidenceCadenceReviewPackage(
            cadence="monthly",
            status="manual_review_required",
            primary_matured_count=len(primary_verified),
            primary_effectiveness_denominator=len(primary_verified),
            blockers=blockers,
        )

    def build_weekly(self, *, period_end_dates: Sequence[str]) -> EvidenceCadenceReviewPackage:
        """Require natural, named periods and never fill missing weeks synthetically."""
        unique_periods = tuple(dict.fromkeys(str(item) for item in period_end_dates))
        blockers = () if len(unique_periods) >= 3 else ("three_real_weekly_periods_required",)
        return EvidenceCadenceReviewPackage(
            cadence="weekly",
            status="manual_review_required" if not blockers else "indeterminate",
            primary_matured_count=0,
            primary_effectiveness_denominator=0,
            blockers=blockers,
        )
