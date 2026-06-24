from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class HandoffRecommendation:
    target_owner: str
    target_label: str
    title: str
    severity: str
    summary: str
    evidence: tuple[str, ...]
    recommended_next_steps: tuple[str, ...]
    source_feature_ids: tuple[str, ...]
    source_failure_ids: tuple[str, ...]


OWNER_LABELS = {
    "data_audit": "Data Audit Agent",
    "execution": "Execution Agent",
    "tech_lead": "Tech Lead",
    "testing_qa": "Testing / QA Agent",
    "manual": "Manual QA",
}

OWNER_TITLES = {
    "data_audit": "Data and schema audit handoff",
    "execution": "UI or execution repair handoff",
    "tech_lead": "Architecture or policy decision handoff",
    "testing_qa": "Runner and QA routing handoff",
    "manual": "Manual verification handoff",
}

OWNER_ORDER = ("data_audit", "execution", "tech_lead", "testing_qa", "manual")
ACTIONABLE_STATUSES = frozenset({"failed", "needs_data_audit", "partial"})


def build_handoff_recommendations(interpretation: Any) -> tuple[HandoffRecommendation, ...]:
    buckets: dict[str, dict[str, list[str]]] = {}

    for feature in interpretation.feature_results.values():
        if not _feature_requires_handoff(feature, interpretation.mode):
            continue

        owner = feature.likely_owner or "testing_qa"
        bucket = _bucket_for(buckets, owner)
        _append_unique(bucket["feature_ids"], feature.feature_id)
        for suite_id in feature.failed_suite_ids:
            _append_unique(bucket["failure_ids"], suite_id)
        _append_unique(bucket["evidence"], _feature_evidence(feature))
        _append_unique(bucket["steps"], feature.recommended_next_steps)

    if "data_audit" in buckets:
        for recommendation in interpretation.data_audit_recommendations:
            _append_unique(buckets["data_audit"]["steps"], recommendation)

    for failure in interpretation.runner_failures:
        bucket = _bucket_for(buckets, "testing_qa")
        failure_id = str(failure.get("id") or "unknown-runner-failure")
        _append_unique(bucket["failure_ids"], failure_id)
        _append_unique(bucket["evidence"], _runner_failure_evidence(failure))
        _append_unique(
            bucket["steps"],
            "Check test_suite_bridge.py, feature_router.py, and TEST_INVENTORY classifications before rerunning.",
        )

    return tuple(
        _recommendation_for(owner, buckets[owner])
        for owner in sorted(buckets, key=_owner_sort_key)
    )


def render_handoff_markdown(recommendations: Sequence[HandoffRecommendation]) -> str:
    if not recommendations:
        return "No handoff recommendations."

    lines: list[str] = []
    for recommendation in recommendations:
        lines.append(f"## {recommendation.target_label}")
        lines.append(f"- Likely Owner: `{recommendation.target_owner}`")
        lines.append(f"- Severity: `{recommendation.severity}`")
        if recommendation.source_feature_ids:
            lines.append(f"- Source Features: `{', '.join(recommendation.source_feature_ids)}`")
        if recommendation.source_failure_ids:
            lines.append(f"- Source Failures: `{', '.join(recommendation.source_failure_ids)}`")
        lines.append("")
        lines.append(f"### {recommendation.title}")
        lines.append(recommendation.summary)
        lines.append("")
        lines.append("### Evidence")
        for item in recommendation.evidence:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("### Recommended Next Steps")
        for item in recommendation.recommended_next_steps:
            lines.append(f"- [ ] {item}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _feature_requires_handoff(feature: Any, mode: Any) -> bool:
    if feature.status in ACTIONABLE_STATUSES:
        return True
    if feature.status != "not_run":
        return False

    mode_value = str(getattr(mode, "value", mode)).lower()
    evidence = str(feature.evidence_summary).lower()
    next_steps = str(feature.recommended_next_steps).lower()
    quick_unsupported = (
        mode_value == "quick"
        and not feature.failed_suite_ids
        and (
            "unsupported in quick mode" in evidence
            or "not support quick" in evidence
            or "no action required" in next_steps
            or "full mode" in next_steps
        )
    )
    return not quick_unsupported


def _bucket_for(buckets: dict[str, dict[str, list[str]]], owner: str) -> dict[str, list[str]]:
    if owner not in buckets:
        buckets[owner] = {
            "feature_ids": [],
            "failure_ids": [],
            "evidence": [],
            "steps": [],
        }
    return buckets[owner]


def _append_unique(items: list[str], value: str) -> None:
    value = value.strip()
    if value and value not in items:
        items.append(value)


def _feature_evidence(feature: Any) -> str:
    parts = [
        f"{feature.display_name} [{feature.status}]: {feature.evidence_summary}",
    ]
    if feature.matched_suite_ids:
        parts.append(f"Matched suites: {', '.join(feature.matched_suite_ids)}.")
    if feature.failed_suite_ids:
        parts.append(f"Failed suites: {', '.join(feature.failed_suite_ids)}.")
    if feature.known_gaps:
        parts.append(f"Known gaps: {', '.join(feature.known_gaps)}.")
    return " ".join(parts)


def _runner_failure_evidence(failure: dict[str, Any]) -> str:
    failure_id = str(failure.get("id") or "unknown-runner-failure")
    error = str(failure.get("error") or "No error message")
    suite = failure.get("suite") if isinstance(failure.get("suite"), dict) else {}
    returncode = suite.get("returncode") if suite else None
    if returncode is None:
        return f"Runner failure `{failure_id}`: {error}."
    return f"Runner failure `{failure_id}`: {error}. Return code: `{returncode}`."


def _recommendation_for(owner: str, bucket: dict[str, list[str]]) -> HandoffRecommendation:
    evidence = tuple(bucket["evidence"])
    steps = tuple(bucket["steps"])
    status_text = "actionable issue" if len(evidence) == 1 else "actionable issues"
    severity = "warning" if owner == "data_audit" and bucket["failure_ids"] else "error"
    if owner == "testing_qa" and not bucket["feature_ids"]:
        severity = "error"

    return HandoffRecommendation(
        target_owner=owner,
        target_label=OWNER_LABELS.get(owner, owner),
        title=OWNER_TITLES.get(owner, "Healthcheck handoff"),
        severity=severity,
        summary=f"{len(evidence)} {status_text} require follow-up before treating the healthcheck as closed.",
        evidence=evidence,
        recommended_next_steps=steps,
        source_feature_ids=tuple(bucket["feature_ids"]),
        source_failure_ids=tuple(bucket["failure_ids"]),
    )


def _owner_sort_key(owner: str) -> tuple[int, str]:
    try:
        return (OWNER_ORDER.index(owner), owner)
    except ValueError:
        return (len(OWNER_ORDER), owner)
