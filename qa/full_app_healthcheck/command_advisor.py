from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES, FeatureRoute, query_feature
from qa.full_app_healthcheck.manifest import HealthcheckMode, RiskLevel
from qa.full_app_healthcheck.test_suite_bridge import ExistingSuite, PYTHON, build_existing_suite_registry


@dataclass(frozen=True)
class RecommendedQACommand:
    label: str
    argv: tuple[str, ...]
    mode: HealthcheckMode
    risk: RiskLevel
    expected_evidence: str
    non_destructive: bool = True


@dataclass(frozen=True)
class FeatureCommandAdvice:
    feature_id: str
    display_name: str
    recommended_mode: HealthcheckMode
    risk_level: RiskLevel
    commands: tuple[RecommendedQACommand, ...]
    expected_report: str
    warnings: tuple[str, ...]
    known_gaps: tuple[str, ...]
    candidate_test_paths: tuple[str, ...]
    service_oracle_test_paths: tuple[str, ...]
    safety_notes: str


def advise_feature_commands(
    feature_keyword: str,
    preferred_mode: HealthcheckMode | str | None = None,
) -> FeatureCommandAdvice:
    route = query_feature(feature_keyword)
    if route is None:
        known = ", ".join(sorted(FEATURE_ROUTES))
        raise ValueError(f"Unknown healthcheck feature: {feature_keyword!r}. Known features: {known}")

    requested_mode = _normalize_mode(preferred_mode)
    mode, warnings = _choose_mode(route, requested_mode)
    suites = _mode_compatible_feature_suites(route, mode)

    commands = [
        RecommendedQACommand(
            label=f"Run {suite.id}",
            argv=suite.command,
            mode=mode,
            risk=RiskLevel.UI_ONLY,
            expected_evidence=f"Pytest or QA script exits 0 for suite `{suite.id}`.",
            non_destructive=suite.non_destructive,
        )
        for suite in suites
    ]
    commands.append(
        RecommendedQACommand(
            label=f"Run {mode.value} healthcheck runner",
            argv=(
                PYTHON,
                "scripts\\run_full_app_healthcheck.py",
                "--mode",
                mode.value,
                "--output-dir",
                "output\\qa\\full_app_healthcheck_tmp",
                "--fail-fast",
            ),
            mode=mode,
            risk=RiskLevel.UI_ONLY,
            expected_evidence="Runner exits 0 and writes REPORT.md plus result.json.",
        )
    )

    if not suites:
        warnings = (
            *warnings,
            "No direct bridge suite is currently registered for this feature and mode.",
        )

    return FeatureCommandAdvice(
        feature_id=route.feature_id,
        display_name=route.display_name,
        recommended_mode=mode,
        risk_level=RiskLevel.UI_ONLY,
        commands=tuple(commands),
        expected_report=(
            "Expected Report: command stdout should show pass/fail evidence; runner output should include "
            "`output/qa/full_app_healthcheck_tmp/REPORT.md` and `result.json` for result interpretation."
        ),
        warnings=warnings,
        known_gaps=route.known_gaps,
        candidate_test_paths=route.candidate_test_paths,
        service_oracle_test_paths=route.service_oracle_test_paths,
        safety_notes=route.safety_notes,
    )


def render_feature_command_advice_markdown(advice: FeatureCommandAdvice) -> str:
    lines = [
        "## Feature QA Command Advice",
        "",
        f"- Feature: `{advice.feature_id}` - {advice.display_name}",
        f"- Recommended Mode: `{advice.recommended_mode.value}`",
        f"- Risk: `{advice.risk_level.value}`",
        f"- Safety Notes: {advice.safety_notes}",
        "",
        "### Commands",
        "",
    ]

    for command in advice.commands:
        lines.append(f"#### {command.label}")
        lines.append(f"- Mode: `{command.mode.value}`")
        lines.append(f"- Risk: `{command.risk.value}`")
        lines.append(f"- Expected Evidence: {command.expected_evidence}")
        lines.append("```powershell")
        lines.append(_format_command(command.argv))
        lines.append("```")
        lines.append("")

    lines.append("### Expected Report")
    lines.append(advice.expected_report)
    lines.append("")

    if advice.warnings:
        lines.append("### Warnings")
        for warning in advice.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    if advice.known_gaps:
        lines.append("### Known Gaps")
        for gap in advice.known_gaps:
            lines.append(f"- {gap}")
        lines.append("")

    if advice.candidate_test_paths:
        lines.append("### Candidate Tests")
        for path in advice.candidate_test_paths:
            lines.append(f"- `{path}`")
        lines.append("")

    if advice.service_oracle_test_paths:
        lines.append("### Service Oracle Tests")
        for path in advice.service_oracle_test_paths:
            lines.append(f"- `{path}`")
        lines.append("")

    return "\n".join(lines).rstrip()


def _normalize_mode(mode: HealthcheckMode | str | None) -> HealthcheckMode | None:
    if mode is None:
        return None
    if isinstance(mode, HealthcheckMode):
        return mode
    return HealthcheckMode(mode)


def _choose_mode(
    route: FeatureRoute,
    preferred_mode: HealthcheckMode | None,
) -> tuple[HealthcheckMode, tuple[str, ...]]:
    warnings: list[str] = []

    if preferred_mode == HealthcheckMode.HIGH_RISK_DRY_RUN:
        warnings.append("High-risk dry-run is outside A-4 and is not recommended by this advisor.")
        preferred_mode = None

    if preferred_mode == HealthcheckMode.QUICK and not route.quick_supported:
        warnings.append("Quick Mode is not supported for this feature; recommend Full Mode instead.")

    if preferred_mode == HealthcheckMode.FULL and not route.full_supported:
        warnings.append("Full Mode is not supported for this feature; recommend Quick Mode instead.")

    if preferred_mode == HealthcheckMode.QUICK and route.quick_supported:
        return HealthcheckMode.QUICK, tuple(warnings)
    if preferred_mode == HealthcheckMode.FULL and route.full_supported:
        return HealthcheckMode.FULL, tuple(warnings)
    if route.quick_supported:
        return HealthcheckMode.QUICK, tuple(warnings)
    return HealthcheckMode.FULL, tuple(warnings)


def _mode_compatible_feature_suites(
    route: FeatureRoute,
    mode: HealthcheckMode,
) -> tuple[ExistingSuite, ...]:
    suite_by_id = {suite.id: suite for suite in build_existing_suite_registry()}
    suites: list[ExistingSuite] = []
    for suite_id in route.direct_bridge_suite_ids:
        suite = suite_by_id.get(suite_id)
        if suite is not None and mode in suite.modes and suite.non_destructive:
            suites.append(suite)
    return tuple(suites)


def _format_command(argv: Sequence[str]) -> str:
    return " ".join(_quote_arg(arg) for arg in argv)


def _quote_arg(arg: str) -> str:
    if any(char.isspace() for char in arg):
        return f'"{arg}"'
    return arg
