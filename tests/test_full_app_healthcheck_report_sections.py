import inspect
import sys

import pytest

from qa.full_app_healthcheck.report_sections import (
    ALLOWED_REPORT_SECTION_IDS,
    ReportSection,
    build_run_history_comparison_report_section,
    build_report_sections,
    render_report_sections_markdown,
)
from qa.full_app_healthcheck.run_history_manifest import (
    FeatureRunRecord,
    SuiteRunRecord,
    build_run_history_manifest,
)


def test_build_report_sections_is_opt_in_and_ordered():
    assert build_report_sections(()) == ()

    sections = build_report_sections(("flow-diagnostics", "quick-gate-proposal"))

    assert tuple(section.section_id for section in sections) == (
        "flow-diagnostics",
        "quick-gate-proposal",
    )
    assert all(section.payload["report_only"] is True for section in sections)


def test_report_sections_include_expected_metadata_content():
    sections = build_report_sections(("coverage-burndown", "full-release-checklist"))
    markdown = render_report_sections_markdown(sections)

    assert "Coverage Burn-down" in markdown
    assert "Full Mode Release Checklist" in markdown
    assert "report-only" in markdown
    assert "Activates Release Gate" in markdown


def test_build_run_history_comparison_report_section_is_explicit_and_report_only():
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

    section = build_run_history_comparison_report_section(baseline, candidate)

    assert section.section_id == "run-history-comparison"
    assert section.payload["report_only"] is True
    assert section.payload["baseline_run_id"] == "baseline"
    assert section.payload["candidate_run_id"] == "candidate"
    assert section.payload["fixed_suite_count"] == 1
    assert "Run History Comparison" in section.markdown
    assert "`suite_fixed`" in section.markdown


def test_build_report_sections_rejects_unknown_section_id():
    with pytest.raises(ValueError, match="Unknown report section"):
        build_report_sections(("unknown-section",))


def test_report_section_rejects_incomplete_values():
    with pytest.raises(ValueError, match="section_id"):
        ReportSection(section_id="", title="Title", markdown="## Title", payload={"report_only": True})

    with pytest.raises(ValueError, match="report_only"):
        ReportSection(section_id="x", title="Title", markdown="## Title", payload={})


def test_allowed_report_section_ids_are_stable():
    assert ALLOWED_REPORT_SECTION_IDS == frozenset(
        {
            "coverage-burndown",
            "flow-diagnostics",
            "quick-gate-proposal",
            "full-release-checklist",
        }
    )


def test_report_sections_have_no_execution_or_write_side_effects():
    import qa.full_app_healthcheck.report_sections as module

    module_source = inspect.getsource(module)

    assert "Path(" not in module_source
    assert "write_text" not in module_source
    assert "write_bytes" not in module_source
    assert "open(" not in module_source
    assert ".write(" not in module_source
    assert "subprocess" not in module_source
    assert "test_suite_bridge" not in module_source
    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "MainWindow" not in module_source
    assert "PySide6.QtWidgets" not in sys.modules
