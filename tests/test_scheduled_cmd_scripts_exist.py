from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


REQUIRED_CMD_FILES = (
    "run_daily_data_freshness_check.cmd",
    "run_evidence_pipeline_dry_run.cmd",
    "run_evidence_working_copy_smoke.cmd",
    "register_baldr_scheduled_tasks.cmd",
    "unregister_baldr_scheduled_tasks.cmd",
    "query_baldr_scheduled_tasks.cmd",
    "README.md",
)


def test_required_scheduled_cmd_scripts_exist() -> None:
    missing = [name for name in REQUIRED_CMD_FILES if not (SCHEDULED_DIR / name).exists()]

    assert missing == []


def test_cmd_wrappers_do_not_use_powershell_policy_bypass() -> None:
    offenders: list[str] = []
    for path in SCHEDULED_DIR.glob("*.cmd"):
        text = path.read_text(encoding="utf-8").lower()
        if "set-executionpolicy" in text or "executionpolicy bypass" in text:
            offenders.append(path.name)

    assert offenders == []
