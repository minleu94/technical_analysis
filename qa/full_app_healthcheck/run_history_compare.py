from __future__ import annotations

from dataclasses import dataclass

from qa.full_app_healthcheck.run_history_manifest import (
    ALLOWED_STATUSES,
    FeatureRunRecord,
    RunHistoryManifest,
    SuiteRunRecord,
)


FAILING_STATUSES = frozenset({"failed", "blocked", "manual-gap"})


@dataclass(frozen=True)
class FeatureStatusChange:
    feature_id: str
    baseline_status: str
    candidate_status: str
    baseline_route_mode: str
    candidate_route_mode: str
    summary: str

    def __post_init__(self) -> None:
        if not self.feature_id:
            raise ValueError("feature_id is required.")
        if self.baseline_status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid baseline_status '{self.baseline_status}'.")
        if self.candidate_status not in ALLOWED_STATUSES:
            raise ValueError(f"Invalid candidate_status '{self.candidate_status}'.")
        if not self.baseline_route_mode:
            raise ValueError("baseline_route_mode is required.")
        if not self.candidate_route_mode:
            raise ValueError("candidate_route_mode is required.")
        if not self.summary:
            raise ValueError("summary is required.")


@dataclass(frozen=True)
class RunHistoryComparison:
    baseline_run_id: str
    candidate_run_id: str
    added_suite_ids: tuple[str, ...]
    removed_suite_ids: tuple[str, ...]
    fixed_suite_ids: tuple[str, ...]
    regressed_suite_ids: tuple[str, ...]
    unchanged_failing_suite_ids: tuple[str, ...]
    new_manual_gaps: tuple[str, ...]
    resolved_manual_gaps: tuple[str, ...]
    feature_status_changes: tuple[FeatureStatusChange, ...]

    def __post_init__(self) -> None:
        if not self.baseline_run_id:
            raise ValueError("baseline_run_id is required.")
        if not self.candidate_run_id:
            raise ValueError("candidate_run_id is required.")
        for change in self.feature_status_changes:
            if not isinstance(change, FeatureStatusChange):
                raise TypeError("feature_status_changes must contain FeatureStatusChange instances.")


def compare_run_history_manifests(
    baseline: RunHistoryManifest,
    candidate: RunHistoryManifest,
) -> RunHistoryComparison:
    if not isinstance(baseline, RunHistoryManifest):
        raise TypeError("baseline must be a RunHistoryManifest.")
    if not isinstance(candidate, RunHistoryManifest):
        raise TypeError("candidate must be a RunHistoryManifest.")

    baseline_suites = _suite_by_id(baseline.suite_results)
    candidate_suites = _suite_by_id(candidate.suite_results)
    shared_suite_ids = sorted(set(baseline_suites) & set(candidate_suites))

    fixed_suite_ids = []
    regressed_suite_ids = []
    unchanged_failing_suite_ids = []

    for suite_id in shared_suite_ids:
        baseline_status = baseline_suites[suite_id].status
        candidate_status = candidate_suites[suite_id].status
        if baseline_status != "passed" and candidate_status == "passed":
            fixed_suite_ids.append(suite_id)
        elif baseline_status == "passed" and candidate_status in FAILING_STATUSES:
            regressed_suite_ids.append(suite_id)
        elif baseline_status in FAILING_STATUSES and candidate_status == baseline_status:
            unchanged_failing_suite_ids.append(suite_id)

    feature_status_changes = _feature_status_changes(baseline.feature_results, candidate.feature_results)

    return RunHistoryComparison(
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        added_suite_ids=tuple(sorted(set(candidate_suites) - set(baseline_suites))),
        removed_suite_ids=tuple(sorted(set(baseline_suites) - set(candidate_suites))),
        fixed_suite_ids=tuple(fixed_suite_ids),
        regressed_suite_ids=tuple(regressed_suite_ids),
        unchanged_failing_suite_ids=tuple(unchanged_failing_suite_ids),
        new_manual_gaps=tuple(sorted(set(candidate.manual_gaps) - set(baseline.manual_gaps))),
        resolved_manual_gaps=tuple(sorted(set(baseline.manual_gaps) - set(candidate.manual_gaps))),
        feature_status_changes=feature_status_changes,
    )


def render_run_history_comparison_markdown(comparison: RunHistoryComparison) -> str:
    lines = [
        "# Run History Comparison",
        "",
        f"- **Baseline Run**: `{comparison.baseline_run_id}`",
        f"- **Candidate Run**: `{comparison.candidate_run_id}`",
        "",
        "## Suite Delta",
        "",
        f"- Added suites: {_format_inline_list(comparison.added_suite_ids)}",
        f"- Removed suites: {_format_inline_list(comparison.removed_suite_ids)}",
        f"- Fixed suites: {_format_inline_list(comparison.fixed_suite_ids)}",
        f"- Regressed suites: {_format_inline_list(comparison.regressed_suite_ids)}",
        f"- Unchanged failing suites: {_format_inline_list(comparison.unchanged_failing_suite_ids)}",
        "",
        "## Manual Gap Delta",
        "",
        f"- New manual gaps: {_format_plain_list(comparison.new_manual_gaps)}",
        f"- Resolved manual gaps: {_format_plain_list(comparison.resolved_manual_gaps)}",
        "",
        "## Feature Status Changes",
        "",
    ]

    if comparison.feature_status_changes:
        lines.extend(
            [
                "| Feature ID | Baseline | Candidate | Route Mode | Summary |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for change in comparison.feature_status_changes:
            route_mode = (
                change.candidate_route_mode
                if change.baseline_route_mode == change.candidate_route_mode
                else f"{change.baseline_route_mode} -> {change.candidate_route_mode}"
            )
            lines.append(
                f"| `{change.feature_id}` | `{change.baseline_status}` | `{change.candidate_status}` | "
                f"`{route_mode}` | {change.summary} |"
            )
    else:
        lines.append("- (None)")

    return "\n".join(lines)


def _suite_by_id(suite_results: tuple[SuiteRunRecord, ...]) -> dict[str, SuiteRunRecord]:
    return {suite.suite_id: suite for suite in suite_results}


def _feature_by_id(feature_results: tuple[FeatureRunRecord, ...]) -> dict[str, FeatureRunRecord]:
    return {feature.feature_id: feature for feature in feature_results}


def _feature_status_changes(
    baseline_features: tuple[FeatureRunRecord, ...],
    candidate_features: tuple[FeatureRunRecord, ...],
) -> tuple[FeatureStatusChange, ...]:
    baseline_by_id = _feature_by_id(baseline_features)
    candidate_by_id = _feature_by_id(candidate_features)
    changes = []

    for feature_id in sorted(set(baseline_by_id) & set(candidate_by_id)):
        baseline = baseline_by_id[feature_id]
        candidate = candidate_by_id[feature_id]
        if baseline.status == candidate.status and baseline.route_mode == candidate.route_mode:
            continue
        changes.append(
            FeatureStatusChange(
                feature_id=feature_id,
                baseline_status=baseline.status,
                candidate_status=candidate.status,
                baseline_route_mode=baseline.route_mode,
                candidate_route_mode=candidate.route_mode,
                summary=f"{feature_id} changed from {baseline.status} to {candidate.status}.",
            )
        )

    return tuple(changes)


def _format_inline_list(items: tuple[str, ...]) -> str:
    if not items:
        return "(none)"
    return ", ".join(f"`{item}`" for item in items)


def _format_plain_list(items: tuple[str, ...]) -> str:
    if not items:
        return "(none)"
    return "; ".join(items)
