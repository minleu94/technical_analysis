from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qa.full_app_healthcheck.default_manifest import build_default_manifest
from qa.full_app_healthcheck.manifest import (
    HealthcheckManifest,
    HealthcheckMode,
    HealthcheckStep,
    RiskLevel,
)
from qa.full_app_healthcheck.report_sections import (
    ALLOWED_REPORT_SECTION_IDS,
    build_report_sections,
    build_run_history_comparison_report_section,
)
from qa.full_app_healthcheck.runner import HealthcheckRunner
from qa.full_app_healthcheck.run_history_manifest import (
    FeatureRunRecord,
    RunHistoryManifest,
    SuiteRunRecord,
)


def configure_utf8_stdio(*, stdout=None, stderr=None) -> None:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    for stream in (stdout, stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


TAB_CHOICES = (
    "update",
    "market",
    "decision",
    "research",
    "recommendation",
    "watchlist",
    "portfolio",
    "runtime",
    "cross-flow",
)


def run_existing_suites_for_mode(context, step):
    from qa.full_app_healthcheck.test_suite_bridge import suites_for_mode_and_tabs

    mode = context["mode"]
    tabs = tuple(context.get("tabs") or ())
    outputs = []
    for suite in suites_for_mode_and_tabs(mode, tabs):
        completed = subprocess.run(
            suite.command,
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="backslashreplace",
            timeout=900,
            check=False,
        )
        outputs.append({
            "id": suite.id,
            "title": suite.title,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
        })
        if completed.returncode != 0:
            raise AssertionError(f"既有測試失敗：{suite.id}")
    return {"tabs": tabs, "suites": outputs}


def build_action_registry():
    from qa.full_app_healthcheck.actions import (
        assert_widget_visible,
        assert_tab_exists,
        assert_text_contains,
        assert_viewport_declared,
        collect_mainwindow_smoke_evidence,
        run_mainwindow_ui_smoke,
    )
    return {
        "run_existing_suites_for_mode": run_existing_suites_for_mode,
        "assert_widget_visible": assert_widget_visible,
        "assert_tab_exists": assert_tab_exists,
        "assert_text_contains": assert_text_contains,
        "assert_viewport_declared": assert_viewport_declared,
        "collect_mainwindow_smoke_evidence": collect_mainwindow_smoke_evidence,
        "run_mainwindow_ui_smoke": run_mainwindow_ui_smoke,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="非破壞式 Full App Healthcheck Runner")
    parser.add_argument("--mode", choices=[mode.value for mode in HealthcheckMode], default="quick")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "output" / "qa" / "full_app_healthcheck"))
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--viewport", default="1366x768")
    parser.add_argument(
        "--tab",
        dest="tabs",
        action="append",
        choices=TAB_CHOICES,
        default=[],
        help="Only run suites mapped to the selected UI tab/workspace. Can be provided multiple times.",
    )
    parser.add_argument(
        "--ui-smoke",
        action="store_true",
        help="Opt in to launching the real PySide6 MainWindow for UI smoke evidence.",
    )
    parser.add_argument(
        "--ui-smoke-switch-tabs",
        action="store_true",
        help="When --ui-smoke is enabled, switch through all top-level MainWindow tabs.",
    )
    parser.add_argument(
        "--ui-smoke-screenshot",
        action="store_true",
        help="When --ui-smoke is enabled, capture startup and resize screenshots.",
    )
    parser.add_argument(
        "--ui-smoke-resize",
        action="append",
        default=[],
        help="When --ui-smoke is enabled, resize MainWindow to WIDTHxHEIGHT. Can be repeated.",
    )
    parser.add_argument(
        "--ui-smoke-dialog-cancel",
        action="store_true",
        help="When --ui-smoke is enabled, run cancel-only high-risk dialog probes.",
    )
    parser.add_argument(
        "--report-section",
        dest="report_sections",
        action="append",
        choices=sorted(ALLOWED_REPORT_SECTION_IDS),
        default=[],
        help="Append an opt-in, report-only QA metadata section to REPORT.md and result.json.",
    )
    parser.add_argument("--compare-baseline-manifest", default=None)
    parser.add_argument("--compare-candidate-manifest", default=None)
    return parser.parse_args(argv)


def build_effective_manifest(args: argparse.Namespace) -> HealthcheckManifest:
    manifest = build_default_manifest()
    if not args.ui_smoke:
        return manifest
    return HealthcheckManifest(
        id=manifest.id,
        title=manifest.title,
        modes=manifest.modes,
        steps=manifest.steps + (
            HealthcheckStep(
                id="MAINWINDOW-UI-SMOKE",
                title="Opt-in MainWindow UI smoke: launch, switch tabs, screenshots, resize, cancel dialogs",
                mode=HealthcheckMode.FULL,
                workspace="MainWindow",
                action="run_mainwindow_ui_smoke",
                risk=RiskLevel.UI_ONLY,
                expected="Launch the real MainWindow only when explicitly requested and collect UI evidence without writes.",
            ),
        ),
    )


def build_cli_report_sections(args: argparse.Namespace):
    sections = list(build_report_sections(args.report_sections))
    baseline_path = args.compare_baseline_manifest
    candidate_path = args.compare_candidate_manifest
    if bool(baseline_path) != bool(candidate_path):
        raise ValueError(
            "--compare-baseline-manifest and --compare-candidate-manifest must be provided together."
        )
    if baseline_path and candidate_path:
        sections.append(
            build_run_history_comparison_report_section(
                _load_run_history_manifest(Path(baseline_path)),
                _load_run_history_manifest(Path(candidate_path)),
            )
        )
    return tuple(sections)


def _load_run_history_manifest(path: Path) -> RunHistoryManifest:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return RunHistoryManifest(
        run_id=payload["run_id"],
        commit=payload["commit"],
        mode=payload["mode"],
        viewport=payload.get("viewport"),
        suite_results=tuple(
            SuiteRunRecord(
                suite_id=item["suite_id"],
                status=item["status"],
                command=item["command"],
                duration_seconds=item.get("duration_seconds"),
                evidence_path=item.get("evidence_path"),
            )
            for item in payload.get("suite_results", ())
        ),
        feature_results=tuple(
            FeatureRunRecord(
                feature_id=item["feature_id"],
                status=item["status"],
                route_mode=item["route_mode"],
                evidence_summary=item["evidence_summary"],
            )
            for item in payload.get("feature_results", ())
        ),
        manual_gaps=tuple(payload.get("manual_gaps", ())),
        generated_at=payload["generated_at"],
    )


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    args = parse_args(argv)
    mode = HealthcheckMode(args.mode)
    manifest = build_effective_manifest(args)
    report_sections = build_cli_report_sections(args)

    # We will build the coverage baseline here in Batch C and pass it to runner
    coverage_items = None
    try:
        from qa.full_app_healthcheck.batch_closeout_baseline import build_batch_closeout_baseline
        coverage_items = build_batch_closeout_baseline()
    except ImportError:
        pass

    runner = HealthcheckRunner(
        manifest=manifest,
        actions=build_action_registry(),
        context={
            "viewport": args.viewport,
            "mode": mode,
            "tabs": tuple(args.tabs),
            "mainwindow_smoke_output_dir": Path(args.output_dir) / "mainwindow_ui_smoke",
            "ui_smoke_switch_tabs": bool(args.ui_smoke_switch_tabs),
            "ui_smoke_screenshot": bool(args.ui_smoke_screenshot),
            "ui_smoke_resize": tuple(args.ui_smoke_resize),
            "ui_smoke_dialog_cancel": bool(args.ui_smoke_dialog_cancel),
        },
        output_dir=Path(args.output_dir),
        fail_fast=args.fail_fast,
        coverage_items=coverage_items,
        report_sections=report_sections,
    )
    result = runner.run(mode)
    print(f"Healthcheck {result.status}: {result.run_id}")
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
