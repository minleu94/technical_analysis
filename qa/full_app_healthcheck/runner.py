from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from qa.full_app_healthcheck.manifest import HealthcheckManifest, HealthcheckMode, HealthcheckStep
from qa.full_app_healthcheck.report_sections import ReportSection
from qa.full_app_healthcheck.reporting import HealthcheckResult, StepResult, write_reports
from qa.full_app_healthcheck.safety import validate_non_destructive_manifest

Action = Callable[[dict[str, Any], HealthcheckStep], dict[str, Any]]


class HealthcheckRunner:
    def __init__(
        self,
        *,
        manifest: HealthcheckManifest,
        actions: dict[str, Action],
        context: dict[str, Any],
        output_dir: Path,
        fail_fast: bool = False,
        coverage_items: tuple[Any, ...] | None = None,
        report_sections: tuple[ReportSection, ...] | None = None,
    ) -> None:
        self.manifest = manifest
        self.actions = actions
        self.context = context
        self.output_dir = output_dir
        self.fail_fast = fail_fast
        self.coverage_items = coverage_items
        self.report_sections = report_sections

    def run(self, mode: HealthcheckMode) -> HealthcheckResult:
        validate_non_destructive_manifest(self.manifest)
        step_results: list[StepResult] = []
        for step in self.manifest.steps_for_mode(mode):
            action = self.actions.get(step.action)
            if action is None:
                step_results.append(
                    StepResult(
                        id=step.id,
                        title=step.title,
                        status="failed",
                        evidence={"error": f"找不到 action: {step.action}"},
                    )
                )
                if self.fail_fast:
                    break
                continue
            try:
                evidence = action(self.context, step)
                step_results.append(
                    StepResult(id=step.id, title=step.title, status="passed", evidence=evidence)
                )
            except Exception as exc:  # noqa: BLE001
                step_results.append(
                    StepResult(
                        id=step.id,
                        title=step.title,
                        status="failed",
                        evidence={"error": str(exc), "type": exc.__class__.__name__},
                    )
                )
                if self.fail_fast:
                    break
        status = "passed" if all(result.status == "passed" for result in step_results) else "failed"
        result = HealthcheckResult(
            run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
            mode=mode,
            status=status,
            steps=tuple(step_results),
            tabs=tuple(self.context.get("tabs") or ()),
        )
        write_reports(
            result,
            self.output_dir / result.run_id,
            self.coverage_items,
            self.report_sections,
        )
        return result
