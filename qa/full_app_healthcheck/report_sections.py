from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from qa.full_app_healthcheck.coverage_burndown import (
    generate_coverage_burndown_report,
    render_coverage_burndown_markdown,
)
from qa.full_app_healthcheck.flow_diagnostics import (
    generate_flow_diagnostics,
    render_flow_diagnostics_markdown,
)
from qa.full_app_healthcheck.full_mode_release_checklist import (
    generate_full_mode_release_checklist,
    render_full_mode_release_checklist_markdown,
)
from qa.full_app_healthcheck.quick_mode_release_gate_proposal import (
    generate_quick_mode_release_gate_proposal,
    render_quick_mode_release_gate_proposal_markdown,
)
from qa.full_app_healthcheck.run_history_compare import (
    compare_run_history_manifests,
    render_run_history_comparison_markdown,
)
from qa.full_app_healthcheck.run_history_manifest import RunHistoryManifest


ALLOWED_REPORT_SECTION_IDS = frozenset(
    {
        "coverage-burndown",
        "flow-diagnostics",
        "quick-gate-proposal",
        "full-release-checklist",
    }
)


@dataclass(frozen=True)
class ReportSection:
    section_id: str
    title: str
    markdown: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if not self.section_id:
            raise ValueError("section_id is required.")
        if not self.title:
            raise ValueError("title is required.")
        if not self.markdown:
            raise ValueError("markdown is required.")
        if self.payload.get("report_only") is not True:
            raise ValueError("payload must include report_only=True.")


def build_report_sections(section_ids: Sequence[str]) -> tuple[ReportSection, ...]:
    builders = _section_builders()
    sections: list[ReportSection] = []
    for section_id in section_ids:
        builder = builders.get(section_id)
        if builder is None:
            allowed = ", ".join(sorted(ALLOWED_REPORT_SECTION_IDS))
            raise ValueError(f"Unknown report section '{section_id}'. Allowed: {allowed}")
        sections.append(builder())
    return tuple(sections)


def render_report_sections_markdown(sections: Sequence[ReportSection]) -> str:
    if not sections:
        return ""
    lines = ["## Optional QA Report Sections", ""]
    for section in sections:
        lines.extend(
            [
                f"### `{section.section_id}` - {section.title}",
                "",
                "- Safety: `report-only`",
                "",
                section.markdown,
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def build_run_history_comparison_report_section(
    baseline: RunHistoryManifest,
    candidate: RunHistoryManifest,
) -> ReportSection:
    comparison = compare_run_history_manifests(baseline, candidate)
    return ReportSection(
        section_id="run-history-comparison",
        title="Run History Comparison",
        markdown=render_run_history_comparison_markdown(comparison),
        payload={
            "report_only": True,
            "baseline_run_id": comparison.baseline_run_id,
            "candidate_run_id": comparison.candidate_run_id,
            "added_suite_count": len(comparison.added_suite_ids),
            "removed_suite_count": len(comparison.removed_suite_ids),
            "fixed_suite_count": len(comparison.fixed_suite_ids),
            "regressed_suite_count": len(comparison.regressed_suite_ids),
            "new_manual_gap_count": len(comparison.new_manual_gaps),
            "resolved_manual_gap_count": len(comparison.resolved_manual_gaps),
            "feature_status_change_count": len(comparison.feature_status_changes),
        },
    )


def _section_builders() -> dict[str, Callable[[], ReportSection]]:
    return {
        "coverage-burndown": _coverage_burndown_section,
        "flow-diagnostics": _flow_diagnostics_section,
        "quick-gate-proposal": _quick_gate_proposal_section,
        "full-release-checklist": _full_release_checklist_section,
    }


def _coverage_burndown_section() -> ReportSection:
    report = generate_coverage_burndown_report()
    return ReportSection(
        section_id="coverage-burndown",
        title="Coverage Burn-down",
        markdown=render_coverage_burndown_markdown(report),
        payload={
            "report_only": True,
            "total_features": report.total_features,
            "ui_covered_count": report.ui_covered_count,
            "oracle_only_count": report.oracle_only_count,
            "gap_count": report.gap_count,
        },
    )


def _flow_diagnostics_section() -> ReportSection:
    report = generate_flow_diagnostics()
    return ReportSection(
        section_id="flow-diagnostics",
        title="Closed-loop Flow Diagnostics",
        markdown=render_flow_diagnostics_markdown(report),
        payload={
            "report_only": True,
            "summary": report.summary,
            "flow_count": len(report.diagnostics),
        },
    )


def _quick_gate_proposal_section() -> ReportSection:
    proposal = generate_quick_mode_release_gate_proposal()
    return ReportSection(
        section_id="quick-gate-proposal",
        title="Quick Mode Release Gate Proposal",
        markdown=render_quick_mode_release_gate_proposal_markdown(proposal),
        payload={
            "report_only": True,
            "proposal_id": proposal.proposal_id,
            "gate_status": proposal.gate_status,
            "activates_ci_gate": proposal.activates_ci_gate,
            "mutates_runner_bridge": proposal.mutates_runner_bridge,
        },
    )


def _full_release_checklist_section() -> ReportSection:
    checklist = generate_full_mode_release_checklist()
    return ReportSection(
        section_id="full-release-checklist",
        title="Full Mode Release Checklist",
        markdown=render_full_mode_release_checklist_markdown(checklist),
        payload={
            "report_only": True,
            "checklist_id": checklist.checklist_id,
            "checklist_status": checklist.checklist_status,
            "activates_release_gate": checklist.activates_release_gate,
            "mutates_runner_bridge": checklist.mutates_runner_bridge,
        },
    )
