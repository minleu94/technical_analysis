from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


REQUIRED_CMD_FILES = (
    "run_paper_execution_daily.cmd",
    "run_paper_execution_daily_isolated.cmd",
    "run_paper_execution_daily_isolated.py",
    "run_daily_data_update_quick.cmd",
    "run_daily_data_update_quick.py",
    "run_daily_data_freshness_check.cmd",
    "run_ml_raw_pit_refresh.cmd",
    "run_ml_raw_pit_refresh.py",
    "run_ml_direct_chain_maintenance.cmd",
    "run_ml_direct_chain_maintenance.py",
    "run_recommendation_snapshot.cmd",
    "run_scheduled_recommendation_snapshot.py",
    "run_evidence_pipeline_dry_run.cmd",
    "run_ml_promotion_evidence.cmd",
    "run_ml_allocation_copilot.cmd",
    "run_ml_promotion_authority.cmd",
    "run_decision_evidence_capture.cmd",
    "run_scheduled_decision_evidence_capture.py",
    "run_paper_portfolio_daily.cmd",
    "run_formal_input_producer_daily.cmd",
    "run_formal_input_producer_daily.py",
    "register_formal_input_producer_task.cmd",
    "register_paper_execution_task.cmd",
    "run_evidence_working_copy_smoke.cmd",
    "register_baldr_scheduled_tasks.cmd",
    "unregister_baldr_scheduled_tasks.cmd",
    "query_baldr_scheduled_tasks.cmd",
    "README.md",
)


FORMAL_PAPER_WINDOWS_WRAPPERS = (
    "run_formal_input_producer_daily.cmd",
    "run_formal_rule_source_preopen.cmd",
    "run_formal_pit_sidecar_postcutoff.cmd",
    "run_pit_sector_membership_preopen_capture.cmd",
    "run_paper_execution_daily.cmd",
    "run_paper_execution_daily_isolated.cmd",
    "run_paper_portfolio_daily.cmd",
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


def test_formal_paper_windows_wrappers_use_crlf_line_endings() -> None:
    offenders: list[str] = []
    for name in FORMAL_PAPER_WINDOWS_WRAPPERS:
        data = (SCHEDULED_DIR / name).read_bytes()
        bare_line_endings = data.replace(b"\r\n", b"")
        if not data.endswith(b"\r\n") or b"\n" in bare_line_endings or b"\r" in bare_line_endings:
            offenders.append(name)

    assert offenders == []
