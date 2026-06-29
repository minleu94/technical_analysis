import json
import subprocess
from dataclasses import asdict

import pytest

from qa.full_app_healthcheck.manifest import HealthcheckManifest, HealthcheckMode, HealthcheckStep, RiskLevel
from qa.full_app_healthcheck.report_sections import ReportSection
from qa.full_app_healthcheck.runner import HealthcheckRunner
from qa.full_app_healthcheck.run_history_manifest import (
    FeatureRunRecord,
    SuiteRunRecord,
    build_run_history_manifest,
)
from scripts.run_full_app_healthcheck import (
    build_cli_report_sections,
    parse_args,
    run_existing_suites_for_mode,
)


def test_runner_dispatches_registered_action(tmp_path):
    calls = []

    def fake_action(context, step):
        calls.append((context["name"], step.id))
        return {"message": "ok"}

    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.QUICK,),
        steps=(
            HealthcheckStep(
                id="S-001",
                title="測試步驟",
                mode=HealthcheckMode.QUICK,
                workspace="測試",
                action="fake_action",
                risk=RiskLevel.UI_ONLY,
            ),
        ),
    )
    runner = HealthcheckRunner(
        manifest=manifest,
        actions={"fake_action": fake_action},
        context={"name": "ctx"},
        output_dir=tmp_path,
    )

    result = runner.run(HealthcheckMode.QUICK)

    assert calls == [("ctx", "S-001")]
    assert result.status == "passed"
    assert result.steps[0].status == "passed"


def test_full_app_healthcheck_cli_parse_mode_and_output():
    args = parse_args(["--mode", "full", "--output-dir", "out", "--fail-fast"])

    assert args.mode == "full"
    assert args.output_dir == "out"
    assert args.fail_fast is True


def test_full_app_healthcheck_cli_parse_repeated_tab_filters():
    args = parse_args(["--mode", "full", "--tab", "update", "--tab", "research"])

    assert args.tabs == ["update", "research"]


def test_run_existing_suites_filters_by_selected_tabs(monkeypatch):
    commands: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    evidence = run_existing_suites_for_mode(
        {"mode": HealthcheckMode.FULL, "tabs": ("research",)},
        None,
    )

    suite_ids = {suite["id"] for suite in evidence["suites"]}
    assert "ui-research-workflow" in suite_ids
    assert "ui-run-registry-compare" in suite_ids
    assert "ui-update-workbench" not in suite_ids
    assert all("test_ui_qt_update_view_workbench.py" not in " ".join(command) for command in commands)


def test_runner_writes_optional_report_sections(tmp_path):
    def fake_action(context, step):
        return {"message": "ok"}

    section = ReportSection(
        section_id="quick-gate-proposal",
        title="Quick Gate Proposal",
        markdown="## Quick Gate Proposal\n\n- report-only",
        payload={"report_only": True, "gate_status": "proposal-only"},
    )
    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.QUICK,),
        steps=(
            HealthcheckStep(
                id="S-001",
                title="測試步驟",
                mode=HealthcheckMode.QUICK,
                workspace="測試",
                action="fake_action",
                risk=RiskLevel.UI_ONLY,
            ),
        ),
    )
    runner = HealthcheckRunner(
        manifest=manifest,
        actions={"fake_action": fake_action},
        context={"name": "ctx"},
        output_dir=tmp_path,
        report_sections=(section,),
    )

    result = runner.run(HealthcheckMode.QUICK)
    payload = json.loads((tmp_path / result.run_id / "result.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / result.run_id / "REPORT.md").read_text(encoding="utf-8")

    assert payload["report_sections"][0]["section_id"] == "quick-gate-proposal"
    assert "Optional QA Report Sections" in markdown


def test_full_app_healthcheck_cli_parse_report_sections():
    args = parse_args(
        [
            "--mode",
            "quick",
            "--report-section",
            "coverage-burndown",
            "--report-section",
            "flow-diagnostics",
        ]
    )

    assert args.report_sections == ["coverage-burndown", "flow-diagnostics"]


def test_full_app_healthcheck_cli_parse_run_history_comparison_manifests():
    args = parse_args(
        [
            "--mode",
            "quick",
            "--compare-baseline-manifest",
            "baseline.json",
            "--compare-candidate-manifest",
            "candidate.json",
        ]
    )

    assert args.compare_baseline_manifest == "baseline.json"
    assert args.compare_candidate_manifest == "candidate.json"


def test_build_cli_report_sections_appends_run_history_comparison(tmp_path):
    baseline = build_run_history_manifest(
        run_id="baseline",
        commit="base",
        mode="quick",
        viewport=None,
        suite_results=(SuiteRunRecord("suite_fixed", "failed", "pytest fixed", 1.0, None),),
        feature_results=(FeatureRunRecord("update_view", "manual-gap", "quick", "baseline gap"),),
        manual_gaps=("old gap",),
        generated_at="2026-06-24T00:00:00Z",
    )
    candidate = build_run_history_manifest(
        run_id="candidate",
        commit="candidate",
        mode="quick",
        viewport=None,
        suite_results=(SuiteRunRecord("suite_fixed", "passed", "pytest fixed", 1.0, None),),
        feature_results=(FeatureRunRecord("update_view", "passed", "quick", "candidate ok"),),
        manual_gaps=(),
        generated_at="2026-06-24T00:05:00Z",
    )
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(asdict(baseline)), encoding="utf-8-sig")
    candidate_path.write_text(json.dumps(asdict(candidate)), encoding="utf-8-sig")

    args = parse_args(
        [
            "--mode",
            "quick",
            "--report-section",
            "quick-gate-proposal",
            "--compare-baseline-manifest",
            str(baseline_path),
            "--compare-candidate-manifest",
            str(candidate_path),
        ]
    )

    sections = build_cli_report_sections(args)

    assert tuple(section.section_id for section in sections) == (
        "quick-gate-proposal",
        "run-history-comparison",
    )
    assert sections[-1].payload["baseline_run_id"] == "baseline"
    assert sections[-1].payload["fixed_suite_count"] == 1
