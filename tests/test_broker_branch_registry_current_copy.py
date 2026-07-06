from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_update_view_does_not_hardcode_old_broker_branch_count() -> None:
    text = (ROOT / "ui_qt" / "views" / "update_view.py").read_text(encoding="utf-8")

    assert "40 家追蹤分點" not in text
    assert "目前啟用的追蹤分點" in text


def test_powershell_scheduled_task_wrappers_include_quick_data_update() -> None:
    scheduled_dir = ROOT / "scripts" / "scheduled"
    register_text = (scheduled_dir / "register_baldr_scheduled_tasks.ps1").read_text(encoding="utf-8")
    unregister_text = (scheduled_dir / "unregister_baldr_scheduled_tasks.ps1").read_text(encoding="utf-8")

    assert "baldr-data-update-quick-daily" in register_text
    assert "run_daily_data_update_quick.cmd" in register_text
    assert "baldr-data-update-quick-daily" in unregister_text
