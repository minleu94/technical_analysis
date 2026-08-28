from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from scripts.inspect_scheduled_task_registration import (
    EXPECTED_TASKS,
    TASK_WRAPPER_PATHS,
    inspect_scheduled_task_registration,
)


def test_scheduler_registration_probe_is_query_only_and_redacts_raw_output() -> None:
    calls = []
    repo_root = Path(__file__).resolve().parents[1]

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        task_name = command[3]
        wrapper = repo_root / TASK_WRAPPER_PATHS[task_name]
        return SimpleNamespace(
            returncode=0,
            stdout=(
                f"TaskName: \\{task_name}\n"
                f"Task To Run: cmd.exe /c \"{wrapper}\"\n"
                "Run As User: private-user\n"
                "Last Result: 0\n"
            ),
            stderr="",
        )

    report = inspect_scheduled_task_registration(runner=fake_run, repo_root=repo_root)

    assert report["query_only"] is True
    assert report["side_effect_free"] is True
    assert report["all_available"] is True
    assert report["all_wrappers_present"] is True
    assert report["all_actions_observed"] is True
    assert report["all_actions_match"] is True
    assert report["configuration_ready"] is True
    assert report["available_count"] == len(EXPECTED_TASKS)
    assert len(calls) == len(EXPECTED_TASKS)
    assert all(call[0][1:3] == ["/Query", "/TN"] for call in calls)
    assert all("private-user" not in item for item in str(report["tasks"]))
    assert all("output" not in item for item in report["tasks"])


def test_scheduler_registration_probe_counts_missing_tasks() -> None:
    def fake_run(command, **kwargs):
        name = command[3]
        return SimpleNamespace(
            returncode=0 if name == EXPECTED_TASKS[0]["name"] else 1,
            stdout="Last Result: 0\n" if name == EXPECTED_TASKS[0]["name"] else "ERROR: task not found\n",
            stderr="" if name == EXPECTED_TASKS[0]["name"] else "ERROR: task not found\n",
        )

    report = inspect_scheduled_task_registration(runner=fake_run)

    assert report["all_available"] is False
    assert report["available_count"] == 1
    assert report["missing_or_unavailable_count"] == len(EXPECTED_TASKS) - 1
    assert report["tasks"][0]["status"] == "available"
    assert report["tasks"][1]["status"] == "missing_or_unavailable"


def test_scheduler_registration_probe_detects_missing_local_wrappers(tmp_path: Path) -> None:
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="Last Result: 0\n", stderr="")

    report = inspect_scheduled_task_registration(runner=fake_run, repo_root=tmp_path)

    assert report["all_available"] is True
    assert report["all_wrappers_present"] is False
    assert report["wrapper_missing_count"] == len(EXPECTED_TASKS)
    assert report["configuration_ready"] is False
    assert report["tasks"][0]["wrapper_status"] == "missing"


def test_scheduler_registration_probe_detects_task_action_mismatch() -> None:
    def fake_run(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout='Task To Run: cmd.exe /c "C:\\wrong\\wrapper.cmd"\n',
            stderr="",
        )

    report = inspect_scheduled_task_registration(runner=fake_run)

    assert report["all_available"] is True
    assert report["all_wrappers_present"] is True
    assert report["all_actions_observed"] is True
    assert report["action_mismatch_count"] == len(EXPECTED_TASKS)
    assert report["all_actions_match"] is False
    assert report["configuration_ready"] is False


def test_scheduler_registration_probe_requires_observed_task_actions() -> None:
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="Last Result: 0\n", stderr="")

    report = inspect_scheduled_task_registration(runner=fake_run)

    assert report["all_available"] is True
    assert report["action_mismatch_count"] == 0
    assert report["action_unobserved_count"] == len(EXPECTED_TASKS)
    assert report["all_actions_observed"] is False
    assert report["all_actions_match"] is True
    assert report["configuration_ready"] is False


def test_scheduler_registration_help_is_utf8_safe_with_cp1252() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "inspect_scheduled_task_registration.py"
    )
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0
    assert "唯讀檢查" in completed.stdout.decode("utf-8")
