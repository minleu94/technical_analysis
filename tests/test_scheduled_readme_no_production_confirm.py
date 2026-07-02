from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


def _scheduled_texts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in SCHEDULED_DIR.glob("*")
        if path.suffix.lower() in {".ps1", ".cmd", ".md"}
    }


def test_scheduled_scripts_do_not_create_production_confirm_schedule() -> None:
    for name, text in _scheduled_texts().items():
        lowered = text.lower()
        assert "--confirm" not in lowered or name in {
            "run_evidence_working_copy_smoke.ps1",
            "run_evidence_working_copy_smoke.cmd",
        }
        assert "--allow-production-db-confirm" not in lowered
    readme = (SCHEDULED_DIR / "README.md").read_text(encoding="utf-8").lower()
    assert "do not create a production evidence confirm schedule" in readme


def test_daily_tasks_are_read_only_or_dry_run() -> None:
    register_text = (SCHEDULED_DIR / "register_baldr_scheduled_tasks.cmd").read_text(encoding="utf-8")
    dry_run_text = (SCHEDULED_DIR / "run_evidence_pipeline_dry_run.cmd").read_text(encoding="utf-8")
    freshness_probe_text = (SCHEDULED_DIR / "data_freshness_probe.py").read_text(encoding="utf-8")

    assert "run_daily_data_freshness_check.cmd" in register_text
    assert "run_evidence_pipeline_dry_run.cmd" in register_text
    assert "--dry-run" in dry_run_text
    assert "--confirm" not in dry_run_text.lower()
    assert "mode=ro" in freshness_probe_text
    assert "update_daily" not in freshness_probe_text
    assert "sync_source_to_sqlite" not in freshness_probe_text
