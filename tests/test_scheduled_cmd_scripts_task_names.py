from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


TASK_NAMES = (
    "baldr-data-freshness-check-daily",
    "baldr-evidence-pipeline-dry-run-daily",
    "baldr-evidence-working-copy-smoke-manual",
)


def test_register_cmd_contains_task_names_and_times() -> None:
    text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")

    for task_name in TASK_NAMES:
        assert task_name in text
    assert "05:00" in text
    assert "05:15" in text
    assert "schtasks.exe /Create" in text
    assert "run_daily_data_freshness_check.cmd" in text
    assert "run_evidence_pipeline_dry_run.cmd" in text


def test_query_and_unregister_cmd_include_all_task_names() -> None:
    query_text = (SCHEDULED_DIR / "query_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")
    unregister_text = (SCHEDULED_DIR / "unregister_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")

    for task_name in TASK_NAMES:
        assert task_name in query_text
        assert task_name in unregister_text
