from __future__ import annotations

from types import SimpleNamespace

from scripts.inspect_scheduled_task_registration import (
    EXPECTED_TASKS,
    inspect_scheduled_task_registration,
)


def test_scheduler_registration_probe_is_query_only_and_redacts_raw_output() -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "TaskName: \\baldr-data-update-quick-daily\n"
                "Run As User: private-user\n"
                "Last Result: 0\n"
            ),
            stderr="",
        )

    report = inspect_scheduled_task_registration(runner=fake_run)

    assert report["query_only"] is True
    assert report["side_effect_free"] is True
    assert report["all_available"] is True
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

