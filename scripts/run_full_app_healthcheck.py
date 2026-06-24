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
from qa.full_app_healthcheck.manifest import HealthcheckMode
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


def run_existing_suites_for_mode(context, step):
    from qa.full_app_healthcheck.test_suite_bridge import suites_for_mode

    mode = context["mode"]
    outputs = []
    for suite in suites_for_mode(mode):
        completed = subprocess.run(
            suite.command,
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
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
    return {"suites": outputs}


def build_action_registry():
    from qa.full_app_healthcheck.actions import (
        assert_widget_visible,
        assert_tab_exists,
        assert_text_contains,
        assert_viewport_declared,
    )
    return {
        "run_existing_suites_for_mode": run_existing_suites_for_mode,
        "assert_widget_visible": assert_widget_visible,
        "assert_tab_exists": assert_tab_exists,
        "assert_text_contains": assert_text_contains,
        "assert_viewport_declared": assert_viewport_declared,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="非破壞式 Full App Healthcheck Runner")
    parser.add_argument("--mode", choices=[mode.value for mode in HealthcheckMode], default="quick")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "output" / "qa" / "full_app_healthcheck"))
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--viewport", default="1366x768")
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
    args = parse_args(argv)
    mode = HealthcheckMode(args.mode)
    manifest = build_default_manifest()
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
        context={"viewport": args.viewport, "mode": mode},
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
