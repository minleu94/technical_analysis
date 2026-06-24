import json
from pathlib import Path

from qa.full_app_healthcheck.manifest import HealthcheckMode
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
