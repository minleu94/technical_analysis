from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
from typing import Any, Sequence

from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.report_sections import ReportSection, render_report_sections_markdown


@dataclass(frozen=True)
class StepResult:
    id: str
    title: str
    status: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class HealthcheckResult:
    run_id: str
    mode: HealthcheckMode
    status: str
    steps: tuple[StepResult, ...]
    tabs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportFiles:
    markdown: Path
    json: Path


def write_reports(
    result: HealthcheckResult,
    output_dir: Path,
    coverage_items: Sequence[Any] | None = None,
    report_sections: Sequence[ReportSection] | None = None,
) -> ReportFiles:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "REPORT.md"
    json_path = output_dir / "result.json"

    # Save JSON report
    payload = asdict(result)
    if coverage_items is not None:
        payload["coverage_items"] = [asdict(item) for item in coverage_items]
    if report_sections:
        payload["report_sections"] = [asdict(section) for section in report_sections]

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # Render and save Markdown report
    markdown_path.write_text(
        _render_markdown(result, coverage_items, report_sections),
        encoding="utf-8",
    )
    return ReportFiles(markdown=markdown_path, json=json_path)


def _render_markdown(
    result: HealthcheckResult,
    coverage_items: Sequence[Any] | None = None,
    report_sections: Sequence[ReportSection] | None = None,
) -> str:
    lines = [
        "# Full App Healthcheck Report",
        "",
        f"- Run ID: `{result.run_id}`",
        f"- Mode: `{result.mode.value}`",
        f"- Status: `{result.status}`",
    ]
    if result.tabs:
        lines.append(f"- Tabs: `{', '.join(result.tabs)}`")
    lines.extend(["", "## Steps", ""])
    for step in result.steps:
        lines.append(f"### {step.id} - {step.title}")
        lines.append(f"- Status: `{step.status}`")
        if step.evidence:
            lines.append("- Evidence:")
            for key, value in step.evidence.items():
                lines.append(f"  - `{key}`: {value}")
        lines.append("")

    lines.append("## Coverage Summary")
    lines.append("")
    if coverage_items:
        lines.append(
            "| Healthcheck ID | Title | Automation Status | Manual Status | Source Batch | Evidence | Blocked Reason | Notes |"
        )
        lines.append(
            "|---|---|---|---|---|---|---|---|"
        )
        for item in coverage_items:
            lines.append(
                f"| {item.healthcheck_id} | {item.title} | `{item.status.value}` | `{item.manual_status.value}` | {item.source_batch} | {item.evidence} | {item.blocked_reason} | {item.notes} |"
            )
    else:
        lines.append("尚未產生 coverage matrix。")
    lines.append("")

    if report_sections:
        lines.append(render_report_sections_markdown(report_sections))
        lines.append("")

    return "\n".join(lines)
