from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


TASK_NAMES = (
    "baldr-data-update-quick-daily",
    "baldr-data-freshness-check-daily",
    "baldr-recommendation-snapshot-daily",
    "baldr-evidence-pipeline-dry-run-daily",
    "baldr-evidence-working-copy-smoke-manual",
)

WEEKLY_TASK_NAME = "baldr-v2-2-weekly-collection"


def test_register_cmd_contains_task_names_and_times() -> None:
    text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")

    for task_name in TASK_NAMES:
        assert task_name in text
    assert "04:20" in text
    assert "05:00" in text
    assert "05:10" in text
    assert "05:15" in text
    assert "schtasks.exe /Create" in text
    assert "run_daily_data_update_quick.cmd" in text
    assert "run_daily_data_freshness_check.cmd" in text
    assert "run_recommendation_snapshot.cmd" in text
    assert "run_evidence_pipeline_dry_run.cmd" in text


def test_query_and_unregister_cmd_include_all_task_names() -> None:
    query_text = (SCHEDULED_DIR / "query_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")
    unregister_text = (SCHEDULED_DIR / "unregister_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")

    for task_name in TASK_NAMES:
        assert task_name in query_text
        assert task_name in unregister_text


def test_weekly_register_creates_only_the_sunday_sidecar_collection_task() -> None:
    text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")

    assert "weekly-register" in text
    assert WEEKLY_TASK_NAME in text
    assert "/SC WEEKLY /D SUN /ST 18:00" in text
    assert "run_v2_2_weekly_collection.cmd" in text

    weekly_section = text.split(":weekly_register", maxsplit=1)[1].split(":usage", maxsplit=1)[0]
    for daily_task_name in TASK_NAMES:
        assert daily_task_name not in weekly_section


def test_weekly_task_is_queryable_and_unregistrable_without_daily_task_changes() -> None:
    query_text = (SCHEDULED_DIR / "query_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")
    unregister_text = (SCHEDULED_DIR / "unregister_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")

    assert WEEKLY_TASK_NAME in query_text
    assert WEEKLY_TASK_NAME in unregister_text


def test_register_dryrun_displays_the_weekly_sunday_task_definition() -> None:
    result = subprocess.run(
        [
            "cmd.exe",
            "/d",
            "/c",
            str(SCHEDULED_DIR / "register_baldr_scheduled_tasks.cmd"),
            "dryrun",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert WEEKLY_TASK_NAME in result.stdout
    assert "Schedule: WEEKLY SUN 18:00" in result.stdout
    assert "Dryrun only. No scheduled task was created." in result.stdout


def test_weekly_collection_wrappers_invoke_only_collection_cli_without_history_or_confirm() -> None:
    cmd_text = (SCHEDULED_DIR / "run_v2_2_weekly_collection.cmd").read_text(encoding="utf-8")
    powershell_text = (SCHEDULED_DIR / "run_v2_2_weekly_collection.ps1").read_text(encoding="utf-8")

    assert "powershell.exe" not in cmd_text.lower()
    assert "collect_v2_2_weekly_evidence.py" in cmd_text
    assert "collect_v2_2_weekly_evidence.py" in powershell_text
    for text in (cmd_text, powershell_text):
        assert "--save-history" not in text
        assert "--confirm-action-items" not in text
