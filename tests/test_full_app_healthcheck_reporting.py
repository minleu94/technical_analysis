import json
from pathlib import Path

from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.report_sections import ReportSection
from qa.full_app_healthcheck.reporting import HealthcheckResult, StepResult, write_reports


def test_write_reports_outputs_markdown_and_json(tmp_path):
    result = HealthcheckResult(
        run_id="run-001",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(
            StepResult(
                id="LOOP-1",
                title="資料與市場狀態閉環",
                status="passed",
                evidence={"message": "ok"},
            ),
            StepResult(
                id="LOOP-2",
                title="研究驗證閉環",
                status="failed",
                evidence={"error": "button missing"},
            ),
        ),
    )

    files = write_reports(result, tmp_path)

    assert files.markdown.exists()
    assert files.json.exists()
    markdown = files.markdown.read_text(encoding="utf-8")
    assert "# Full App Healthcheck Report" in markdown
    assert "資料與市場狀態閉環" in markdown
    assert "研究驗證閉環" in markdown
    payload = json.loads(files.json.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-001"
    assert payload["status"] == "failed"


def test_write_reports_omits_optional_sections_by_default(tmp_path):
    result = HealthcheckResult(
        run_id="run-no-sections",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(),
    )

    files = write_reports(result, tmp_path)

    markdown = files.markdown.read_text(encoding="utf-8")
    payload = json.loads(files.json.read_text(encoding="utf-8"))
    assert "Optional QA Report Sections" not in markdown
    assert "report_sections" not in payload


def test_write_reports_includes_optional_report_sections(tmp_path):
    result = HealthcheckResult(
        run_id="run-with-sections",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(),
    )
    section = ReportSection(
        section_id="quick-gate-proposal",
        title="Quick Gate Proposal",
        markdown="## Quick Gate Proposal\n\n- report-only",
        payload={"report_only": True, "gate_status": "proposal-only"},
    )

    files = write_reports(result, tmp_path, report_sections=(section,))

    markdown = files.markdown.read_text(encoding="utf-8")
    payload = json.loads(files.json.read_text(encoding="utf-8"))
    assert "Optional QA Report Sections" in markdown
    assert "quick-gate-proposal" in markdown
    assert payload["report_sections"][0]["section_id"] == "quick-gate-proposal"
    assert payload["report_sections"][0]["payload"]["report_only"] is True
