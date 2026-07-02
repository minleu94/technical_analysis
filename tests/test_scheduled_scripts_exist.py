from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


REQUIRED_FILES = (
    "run_daily_data_freshness_check.ps1",
    "run_evidence_pipeline_dry_run.ps1",
    "run_evidence_working_copy_smoke.ps1",
    "register_baldr_scheduled_tasks.ps1",
    "unregister_baldr_scheduled_tasks.ps1",
    "README.md",
)


def test_required_scheduled_scripts_exist() -> None:
    missing = [name for name in REQUIRED_FILES if not (SCHEDULED_DIR / name).exists()]

    assert missing == []


def test_register_and_unregister_support_dry_run_modes() -> None:
    register_text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.ps1").read_text(encoding="utf-8")
    unregister_text = (SCHEDULED_DIR / "unregister_baldr_scheduled_tasks.ps1").read_text(encoding="utf-8")

    assert "ValidateSet('DryRun', 'Register')" in register_text
    assert "ValidateSet('DryRun', 'Unregister')" in unregister_text
    assert "baldr-data-freshness-check-daily" in register_text
    assert "baldr-evidence-pipeline-dry-run-daily" in register_text
    assert "baldr-evidence-working-copy-smoke-manual" in register_text
