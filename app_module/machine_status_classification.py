"""Machine-readable status classifications shared by read-only evidence views.

These classifications describe how an evidence item may be handled by the
application.  They do not grant evidence credit or replace the underlying
source and time checks.
"""

from __future__ import annotations

from collections.abc import Iterable

MACHINE_STATUS_SOURCE_MISSING = "source_missing"
MACHINE_STATUS_WAITING_FOR_TIME = "waiting_for_time"
MACHINE_STATUS_INVALID_EVIDENCE = "invalid_evidence"
MACHINE_STATUS_HUMAN_REVIEW = "human_review"
MACHINE_STATUS_MACHINE_CANDIDATE = "machine_candidate"
MACHINE_STATUS_MACHINE_VERIFIED = "machine_verified"
MACHINE_STATUS_MACHINE_DEGRADED = "machine_degraded"
MACHINE_STATUS_STALE = "stale"
MACHINE_STATUS_UNKNOWN = "unknown"

MACHINE_STATUS_CLASSIFICATIONS = (
    MACHINE_STATUS_SOURCE_MISSING,
    MACHINE_STATUS_WAITING_FOR_TIME,
    MACHINE_STATUS_INVALID_EVIDENCE,
    MACHINE_STATUS_HUMAN_REVIEW,
    MACHINE_STATUS_MACHINE_CANDIDATE,
    MACHINE_STATUS_MACHINE_VERIFIED,
    MACHINE_STATUS_MACHINE_DEGRADED,
    MACHINE_STATUS_STALE,
    MACHINE_STATUS_UNKNOWN,
)

_HUMAN_TOKENS = (
    "human_review",
    "manual_review",
    "pending_human",
    "requires_manual",
    "owner_reviewer",
    "named_owner",
)
_INVALID_TOKENS = (
    "invalid",
    "mismatch",
    "tamper",
    "schema_error",
    "schema_blocked",
    "future_dated",
    "hash_error",
    "hash_mismatch",
    "failed",
    "failure",
    "exception",
)
_SOURCE_MISSING_TOKENS = (
    "source_missing",
    "source_gap",
    "missing",
    "not_found",
    "not_supplied",
    "not_available",
    "unavailable",
    "no_data",
    "coverage_missing",
)
_WAITING_TOKENS = (
    "waiting_for_time",
    "waiting_for_external_input",
    "waiting_for_formal_inputs",
    "pending_future_data",
    "not_yet_available",
    "insufficient",
    "natural_time",
)


def classify_machine_status(
    status: object,
    diagnostics: Iterable[object] = (),
) -> str:
    """Classify a raw status without turning missing evidence into human work.

    ``action_required`` is intentionally not treated as human review by
    itself.  A caller must provide an explicit human-review diagnostic for
    that classification.  This prevents a missing source or a natural-time
    wait from becoming a named-reviewer gate merely because an older producer
    used the generic ``action_required`` token.
    """

    raw = str(status or "").strip().lower()
    reason_text = " ".join(str(item or "").strip().lower() for item in diagnostics if str(item or "").strip())

    if _has_any(raw, _HUMAN_TOKENS) or _has_any(reason_text, _HUMAN_TOKENS):
        return MACHINE_STATUS_HUMAN_REVIEW
    if raw == MACHINE_STATUS_STALE or _has_any(raw, ("stale", "last_known_good")):
        return MACHINE_STATUS_STALE

    # A concrete invalid/waiting/source diagnostic must also override a
    # generic ``passed`` or ``candidate`` producer token.  A producer cannot
    # turn an incomplete or invalid evidence bundle green by self-reporting
    # its overall status.
    if _has_any(raw, _INVALID_TOKENS):
        return MACHINE_STATUS_INVALID_EVIDENCE
    if _has_any(raw, _WAITING_TOKENS):
        return MACHINE_STATUS_WAITING_FOR_TIME
    if _has_any(reason_text, _INVALID_TOKENS):
        return MACHINE_STATUS_INVALID_EVIDENCE
    if _has_any(reason_text, _WAITING_TOKENS):
        return MACHINE_STATUS_WAITING_FOR_TIME
    if _has_any(reason_text, _SOURCE_MISSING_TOKENS):
        return MACHINE_STATUS_SOURCE_MISSING
    if _has_any(raw, ("machine_candidate", "candidate_only", "candidate_evidence")):
        return MACHINE_STATUS_MACHINE_CANDIDATE
    if _has_any(raw, ("machine_verified", "passed", "completed", "success", "current", "ready", "observed", "done")):
        return MACHINE_STATUS_MACHINE_VERIFIED

    if _has_any(raw, _SOURCE_MISSING_TOKENS):
        return MACHINE_STATUS_SOURCE_MISSING
    if raw in {"degraded", "warning", "partial", "attention"}:
        return MACHINE_STATUS_MACHINE_DEGRADED
    if raw == "action_required":
        return MACHINE_STATUS_UNKNOWN
    if not raw or raw in {"unknown", "none", "null"}:
        return MACHINE_STATUS_UNKNOWN
    return MACHINE_STATUS_UNKNOWN


def is_human_review_classification(value: object) -> bool:
    return str(value or "").strip().lower() == MACHINE_STATUS_HUMAN_REVIEW


def _has_any(value: str, tokens: Iterable[str]) -> bool:
    return any(token in value for token in tokens)
