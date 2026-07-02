from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


def _scheduled_texts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in SCHEDULED_DIR.glob("*")
        if path.suffix.lower() in {".ps1", ".md"}
    }


def test_scheduled_scripts_do_not_create_production_confirm_schedule() -> None:
    for name, text in _scheduled_texts().items():
        lowered = text.lower()
        assert "--confirm" not in lowered or name == "run_evidence_working_copy_smoke.ps1"
        assert "--allow-production-db-confirm" not in lowered
        assert "production confirm" not in lowered


def test_daily_tasks_are_read_only_or_dry_run() -> None:
    register_text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.ps1").read_text(encoding="utf-8")
    dry_run_text = (SCHEDULED_DIR / "run_evidence_pipeline_dry_run.ps1").read_text(encoding="utf-8")
    freshness_text = (SCHEDULED_DIR / "run_daily_data_freshness_check.ps1").read_text(encoding="utf-8")

    assert "run_daily_data_freshness_check.ps1" in register_text
    assert "run_evidence_pipeline_dry_run.ps1" in register_text
    assert "--dry-run" in dry_run_text
    assert "--confirm" not in dry_run_text.lower()
    assert "mode=ro" in freshness_text
    assert "update_daily" not in freshness_text
    assert "sync_source_to_sqlite" not in freshness_text
