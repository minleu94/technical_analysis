from __future__ import annotations

from dataclasses import dataclass

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES, FeatureRoute
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_inventory import get_candidate_bridge_files, is_allowed_in_bridge


@dataclass(frozen=True)
class CandidateBridgeDecision:
    path: str
    feature_id: str | None
    decision: str
    allowed_modes: tuple[HealthcheckMode, ...]
    runner_action: str
    likely_owner: str
    prerequisites: tuple[str, ...]
    safety_notes: tuple[str, ...]


@dataclass(frozen=True)
class CandidateBridgePolicyReport:
    items: tuple[CandidateBridgeDecision, ...]
    summary: str


def evaluate_candidate_bridge_policy() -> CandidateBridgePolicyReport:
    decisions = tuple(
        _decision_for_candidate(path)
        for path in sorted(get_candidate_bridge_files())
    )
    reviewable = sum(1 for item in decisions if item.decision == "eligible-full-mode-review")
    unmapped = sum(1 for item in decisions if item.decision == "needs-feature-route")
    return CandidateBridgePolicyReport(
        items=decisions,
        summary=(
            f"{len(decisions)} candidate tests reviewed: "
            f"{reviewable} eligible for full-mode review, {unmapped} need feature route mapping."
        ),
    )


def render_candidate_bridge_policy_markdown(report: CandidateBridgePolicyReport) -> str:
    lines = [
        "## Candidate Bridge Promote Policy",
        "",
        "Do not edit `qa/full_app_healthcheck/test_suite_bridge.py` automatically.",
        f"{len(report.items)} candidate tests are classified for review.",
        "",
        f"Summary: {report.summary}",
        "",
        "| Candidate Test | Decision | Feature | Modes | Owner | Runner Action |",
        "|---|---|---|---|---|---|",
    ]
    for item in report.items:
        modes = ", ".join(mode.value for mode in item.allowed_modes) or "none"
        feature_id = item.feature_id or "unmapped"
        lines.append(
            f"| `{item.path}` | `{item.decision}` | `{feature_id}` | `{modes}` | "
            f"`{item.likely_owner}` | `{item.runner_action}` |"
        )

    lines.append("")
    lines.append("### Prerequisites")
    for item in report.items:
        lines.append(f"#### `{item.path}`")
        for prerequisite in item.prerequisites:
            lines.append(f"- [ ] {prerequisite}")
        for note in item.safety_notes:
            lines.append(f"- Note: {note}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _decision_for_candidate(path: str) -> CandidateBridgeDecision:
    route = _route_for_candidate(path)
    if route is None:
        return CandidateBridgeDecision(
            path=path,
            feature_id=None,
            decision="needs-feature-route",
            allowed_modes=(),
            runner_action="do-not-bridge-yet",
            likely_owner="tech_lead",
            prerequisites=(
                "Map this candidate test to a FEATURE_ROUTES entry before promotion.",
                "Decide whether the test is a UI flow step, service oracle, or manual gap.",
            ),
            safety_notes=("Candidate remains outside quick/full bridge until route mapping exists.",),
        )

    allowed_modes = _candidate_allowed_modes(route)
    safety_notes = [route.safety_notes]
    if not route.quick_supported:
        safety_notes.append("Quick Mode is not supported for this feature; full-mode review only.")
    if is_allowed_in_bridge(path):
        safety_notes.append("Already direct-bridge allowed; no candidate promotion needed.")

    return CandidateBridgeDecision(
        path=path,
        feature_id=route.feature_id,
        decision="eligible-full-mode-review",
        allowed_modes=allowed_modes,
        runner_action="do-not-bridge-yet",
        likely_owner="testing_qa",
        prerequisites=(
            "Collect non-destructive evidence before changing bridge classification.",
            "Confirm the test does not invoke MainWindow, data writes, migration, backfill, or external high-risk flows.",
            "Record covered healthcheck IDs or flow IDs before adding a suite entry.",
        ),
        safety_notes=tuple(safety_notes),
    )


def _route_for_candidate(path: str) -> FeatureRoute | None:
    for route in FEATURE_ROUTES.values():
        if path in route.candidate_test_paths:
            return route
    return None


def _candidate_allowed_modes(route: FeatureRoute) -> tuple[HealthcheckMode, ...]:
    if route.full_supported:
        return (HealthcheckMode.FULL,)
    if route.quick_supported:
        return (HealthcheckMode.QUICK,)
    return ()
