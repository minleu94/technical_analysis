import inspect
import sys

import pytest

from qa.full_app_healthcheck.report_sections import (
    ALLOWED_REPORT_SECTION_IDS,
    ReportSection,
    build_report_sections,
    render_report_sections_markdown,
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
