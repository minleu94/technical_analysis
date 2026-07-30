from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


FORBIDDEN_TRADING_LANGUAGE = (
    "buy recommendation",
    "sell recommendation",
    "target price",
    "fair price",
    "high confidence",
    "買進建議",
    "賣出建議",
    "目標價",
    "合理價",
    "高信心",
)


def test_daily_evidence_cmd_wrapper_does_not_confirm() -> None:
    text = (SCHEDULED_DIR / "run_evidence_pipeline_dry_run.cmd").read_text(encoding="utf-8").lower()

    assert "--dry-run" in text
    assert "--confirm" not in text
    assert "--allow-production-db-confirm" not in text


def test_daily_recommendation_snapshot_wrapper_does_not_confirm_or_trade() -> None:
    cmd_text = (SCHEDULED_DIR / "run_recommendation_snapshot.cmd").read_text(encoding="utf-8").lower()
    py_text = (SCHEDULED_DIR / "run_scheduled_recommendation_snapshot.py").read_text(encoding="utf-8").lower()
    text = cmd_text + "\n" + py_text

    assert "recommendation_snapshot" in text
    assert "--confirm" not in text
    assert "--allow-production-db-confirm" not in text
    assert "writes_evidence_db" in text
    assert "auto_trading" in text
    assert "lifecycle_action" in text


def test_daily_data_update_wrapper_does_not_confirm_or_trade() -> None:
    cmd_text = (SCHEDULED_DIR / "run_daily_data_update_quick.cmd").read_text(encoding="utf-8").lower()
    py_text = (SCHEDULED_DIR / "run_daily_data_update_quick.py").read_text(encoding="utf-8").lower()
    text = cmd_text + "\n" + py_text

    assert "data_update_quick" in text
    assert "--confirm" not in text
    assert "--allow-production-db-confirm" not in text
    assert "production evidence" not in text


def test_official_market_event_wrapper_has_no_prompt_or_broker() -> None:
    cmd_text = (
        SCHEDULED_DIR / "run_official_market_event_backfill.cmd"
    ).read_text(encoding="utf-8").lower()
    py_text = (
        SCHEDULED_DIR / "run_official_market_event_backfill.py"
    ).read_text(encoding="utf-8").lower()
    text = cmd_text + "\n" + py_text

    assert "official_market_event_backfill" in text
    assert "--confirm" not in text
    assert "input(" not in text
    assert "broker_execution" in text
    assert "production_action_allowed" in text


def test_ml_allocation_copilot_wrapper_is_fail_closed() -> None:
    text = (
        SCHEDULED_DIR / "run_ml_allocation_copilot.cmd"
    ).read_text(encoding="utf-8").lower()

    assert "run_daily_ml_allocation_orchestration.py" in text
    assert "--confirm" not in text
    assert "--allow-production-db-confirm" not in text
    assert "ml_allocation_promotion_evidence" not in text
    assert "--promotion-evidence" not in text
    assert "--promotion-authorization" not in text


def test_ml_promotion_authority_wrapper_is_independent_and_noninteractive() -> None:
    text = (
        SCHEDULED_DIR / "run_ml_promotion_authority.cmd"
    ).read_text(encoding="utf-8").lower()

    assert "run_ml_promotion_authority.py" in text
    assert "--confirm" not in text
    assert "--allow-production-db-confirm" not in text
    assert "promotion_authorization" not in text


def test_ml_promotion_evidence_wrapper_is_unsigned_and_noninteractive() -> None:
    text = (
        SCHEDULED_DIR / "run_ml_promotion_evidence.cmd"
    ).read_text(encoding="utf-8").lower()

    assert "run_ml_promotion_evidence_pipeline.py" in text
    assert "--confirm" not in text
    assert "--allow-production-db-confirm" not in text
    assert "promotion_authorization" not in text


def test_decision_evidence_wrapper_is_the_dedicated_confirm_boundary() -> None:
    cmd_text = (
        SCHEDULED_DIR / "run_decision_evidence_capture.cmd"
    ).read_text(encoding="utf-8").lower()
    py_text = (
        SCHEDULED_DIR / "run_scheduled_decision_evidence_capture.py"
    ).read_text(encoding="utf-8").lower()

    assert "run_scheduled_decision_evidence_capture.py" in cmd_text
    assert "capture_decision_desk_snapshot.py" in py_text
    assert "capture_evidence_events.py" in py_text
    assert '"--confirm"' in py_text
    assert "changes_portfolio_state" in py_text
    assert "broker_execution" in py_text


def test_readme_limits_confirm_to_the_dedicated_capture_task() -> None:
    text = (SCHEDULED_DIR / "README.md").read_text(encoding="utf-8").lower()

    assert "only the dedicated decision/evidence capture task" in text
    assert "does not write the production evidence db" in text
    assert "does not automate trading" in text


def test_scheduled_cmd_docs_have_no_trading_language() -> None:
    offenders: list[tuple[str, str]] = []
    for path in SCHEDULED_DIR.glob("*"):
        if path.suffix.lower() not in {".cmd", ".md"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_TRADING_LANGUAGE:
            if phrase.lower() in text:
                offenders.append((path.name, phrase))

    assert offenders == []


def test_no_cmd_wrapper_uses_set_execution_policy() -> None:
    offenders: list[str] = []
    for path in SCHEDULED_DIR.glob("*.cmd"):
        if "set-executionpolicy" in path.read_text(encoding="utf-8").lower():
            offenders.append(path.name)

    assert offenders == []
