from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


REQUIRED_FILES = (
    "run_official_market_event_backfill.py",
    "run_official_market_event_backfill.cmd",
    "run_ml_raw_pit_refresh.cmd",
    "run_ml_raw_pit_refresh.py",
    "run_ml_direct_chain_maintenance.cmd",
    "run_ml_direct_chain_maintenance.py",
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
    register_cmd_text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")
    unregister_text = (SCHEDULED_DIR / "unregister_baldr_scheduled_tasks.ps1").read_text(encoding="utf-8")

    assert "ValidateSet('DryRun', 'Register', 'WeeklyRegister', 'RegisterAll')" in register_text
    assert "ValidateSet('DryRun', 'Unregister')" in unregister_text
    assert "register-all" in register_cmd_text
    assert "Wrapper preflight failed" in register_cmd_text
    assert "baldr-data-freshness-check-daily" in register_text
    assert "baldr-official-market-events-daily" in register_text
    assert "baldr-ml-raw-pit-refresh-daily" in register_text
    assert "baldr-recommendation-snapshot-daily" in register_text
    assert "baldr-evidence-pipeline-dry-run-daily" in register_text
    assert "baldr-ml-promotion-evidence-daily" in register_text
    assert "baldr-ml-promotion-authority-daily" in register_text
    assert "baldr-ml-allocation-copilot-daily" in register_text
    assert "baldr-decision-evidence-capture-daily" in register_text
    assert "baldr-paper-portfolio-daily" in register_text
    assert "baldr-v2-2-weekly-collection" in register_text
    assert "baldr-official-market-events-daily" in unregister_text
    assert "baldr-ml-raw-pit-refresh-daily" in unregister_text
    assert "baldr-ml-promotion-evidence-daily" in unregister_text
    assert "baldr-ml-promotion-authority-daily" in unregister_text
    assert "baldr-evidence-working-copy-smoke-manual" not in register_text
    assert "baldr-evidence-working-copy-smoke-manual" in unregister_text


def test_freshness_powershell_wrapper_delegates_to_canonical_probe() -> None:
    text = (SCHEDULED_DIR / "run_daily_data_freshness_check.ps1").read_text(encoding="utf-8")

    assert "data_freshness_probe.py" in text
    assert "--status-path" in text
    assert "--log-path" in text
    assert "FreshnessProbe = @'" not in text
    assert "status=failed" not in text.lower()
