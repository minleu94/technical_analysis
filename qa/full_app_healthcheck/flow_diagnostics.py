from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.command_advisor import advise_feature_commands
from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES, FeatureRoute
from qa.full_app_healthcheck.flow_model import HealthcheckFlow, get_all_flows
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_inventory import get_category


@dataclass(frozen=True)
class FlowDiagnostic:
    flow_id: str
    display_name: str
    entrypoint: str
    ordered_feature_ids: tuple[str, ...]
    coverage_status: str
    evidence_sources: tuple[str, ...]
    manual_gaps: tuple[str, ...]
    recommended_commands: tuple[str, ...]
    likely_owner: str
    next_steps: tuple[str, ...]

    @property
    def handoff_owner(self) -> str:
        return self.likely_owner


FlowDiagnosticDetail = FlowDiagnostic


@dataclass(frozen=True)
class FlowDiagnosticsReport:
    diagnostics: tuple[FlowDiagnostic, ...]
    summary: str

    @property
    def items(self) -> tuple[FlowDiagnostic, ...]:
        return self.diagnostics


def generate_flow_diagnostics() -> FlowDiagnosticsReport:
    diagnostics = tuple(_diagnostic_for_flow(flow) for flow in get_all_flows())
    status_counts = {
        status: sum(1 for item in diagnostics if item.coverage_status == status)
        for status in (
            "quick_ui_covered",
            "full_or_manual_required",
            "partially_covered",
            "gapped",
        )
    }
    summary = (
        f"Analyzed {len(diagnostics)} closed-loop flows: "
        f"{status_counts['quick_ui_covered']} quick UI covered, "
        f"{status_counts['full_or_manual_required']} full/manual required, "
        f"{status_counts['partially_covered']} partially covered, "
        f"{status_counts['gapped']} gapped."
    )
    return FlowDiagnosticsReport(diagnostics=diagnostics, summary=summary)


def render_flow_diagnostics_markdown(report: FlowDiagnosticsReport) -> str:
    lines = [
        "## Closed-loop Flow Diagnostics Report",
        "",
        "> [!NOTE]",
        "> 本報告將四大閉環流程轉成非破壞式 QA 診斷：service oracle 只作 evidence，不作 UI flow step。",
        "",
        f"Summary: {report.summary}",
        "",
    ]

    for item in report.diagnostics:
        lines.extend(
            [
                f"### `{item.flow_id}` - {item.display_name}",
                f"- **Entrypoint**: {item.entrypoint}",
                f"- **Coverage Status**: `{item.coverage_status}`",
                f"- **Ordered Feature IDs**: {', '.join(f'`{feature_id}`' for feature_id in item.ordered_feature_ids)}",
                f"- **Handoff Owner**: `{item.likely_owner}`",
                "",
                "#### Next Steps",
            ]
        )
        for next_step in item.next_steps:
            lines.append(f"- {next_step}")
        lines.append("")

        lines.append("#### Evidence Sources")
        for source in item.evidence_sources:
            lines.append(f"- {_format_evidence_source(source)}")
        lines.append("")

        lines.append("#### Manual Gaps")
        if item.manual_gaps:
            for gap in item.manual_gaps:
                lines.append(f"- [ ] {gap}")
        else:
            lines.append("- (None)")
        lines.append("")

        lines.append("#### Recommended Commands")
        if item.recommended_commands:
            lines.append("```powershell")
            for command in item.recommended_commands:
                lines.append(command)
            lines.append("```")
        else:
            lines.append("- (None)")
        lines.append("")

    return "\n".join(lines).rstrip()


def _diagnostic_for_flow(flow: HealthcheckFlow) -> FlowDiagnostic:
    routes = tuple(FEATURE_ROUTES[feature_id] for feature_id in flow.ordered_feature_ids)
    evidence_sources = _dedupe(flow.evidence_sources)
    manual_gaps = _dedupe(flow.manual_gaps)
    next_steps = tuple(step.expected_next_step for step in flow.steps)
    coverage_status = _coverage_status(flow, routes)
    likely_owner = _likely_owner(routes, manual_gaps)

    return FlowDiagnostic(
        flow_id=flow.flow_id,
        display_name=flow.display_name,
        entrypoint=flow.entrypoint,
        ordered_feature_ids=flow.ordered_feature_ids,
        coverage_status=coverage_status,
        evidence_sources=evidence_sources,
        manual_gaps=manual_gaps,
        recommended_commands=_recommended_commands(flow, routes, coverage_status),
        likely_owner=likely_owner,
        next_steps=next_steps,
    )


def _coverage_status(flow: HealthcheckFlow, routes: Sequence[FeatureRoute]) -> str:
    route_declared_sources = set(
        source
        for route in routes
        for source in (
            route.direct_bridge_suite_ids
            + route.candidate_test_paths
            + route.service_oracle_test_paths
        )
    )
    has_unrouted_candidate_gap = any(
        _source_category(source) == "ui-healthcheck-candidate-bridge"
        and source not in route_declared_sources
        for source in flow.evidence_sources
    )
    all_have_direct_bridge = all(route.direct_bridge_suite_ids for route in routes)
    all_quick_supported = all(route.quick_supported for route in routes)
    any_full_supported = any(route.full_supported for route in routes)

    if has_unrouted_candidate_gap:
        return "partially_covered"
    if all_have_direct_bridge and all_quick_supported:
        return "quick_ui_covered"
    if any_full_supported:
        return "full_or_manual_required"
    return "gapped"


def _recommended_commands(
    flow: HealthcheckFlow,
    routes: Sequence[FeatureRoute],
    coverage_status: str,
) -> tuple[str, ...]:
    commands: list[str] = []
    preferred_mode = (
        HealthcheckMode.QUICK
        if coverage_status == "quick_ui_covered"
        else HealthcheckMode.FULL
    )

    for feature_id in _dedupe(route.feature_id for route in routes):
        advice = advise_feature_commands(feature_id, preferred_mode=preferred_mode)
        for command in advice.commands:
            commands.append(_format_command(command.argv))

    for source in flow.evidence_sources:
        category = _source_category(source)
        if category == "ui-healthcheck-candidate-bridge":
            commands.append(f".\\.venv\\Scripts\\python.exe -m pytest {source} -q -o addopts=")
        elif category and category.startswith("service-oracle-"):
            commands.append(f".\\.venv\\Scripts\\python.exe -m pytest {source} -q -o addopts=")
        elif source.startswith("scripts/"):
            commands.append(f".\\.venv\\Scripts\\python.exe {source}")

    return _dedupe(commands)


def _likely_owner(routes: Sequence[FeatureRoute], manual_gaps: Sequence[str]) -> str:
    if any(route.data_audit_policy == "conditional" for route in routes):
        if any(
            token in " ".join(manual_gaps).lower()
            for token in ("sqlite", "csv", "tpex", "twse", "freshness", "broker")
        ):
            return "data_audit"
    if manual_gaps:
        return "testing_qa"
    return "execution"


def _format_evidence_source(source: str) -> str:
    category = _source_category(source)
    if category and category.startswith("service-oracle-"):
        return f"`{source}` evidence-only (`{category}`)"
    if category == "ui-healthcheck-candidate-bridge":
        return f"`{source}` candidate UI evidence (`{category}`)"
    return f"`{source}`"


def _source_category(source: str) -> str | None:
    if source.startswith("tests/"):
        return get_category(source)
    return None


def _format_command(argv: Sequence[str]) -> str:
    return " ".join(_quote_arg(arg) for arg in argv)


def _quote_arg(arg: str) -> str:
    if any(char.isspace() for char in arg):
        return f'"{arg}"'
    return arg


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)
