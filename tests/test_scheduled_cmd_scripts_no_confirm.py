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


def test_readme_explicitly_blocks_production_confirm() -> None:
    text = (SCHEDULED_DIR / "README.md").read_text(encoding="utf-8").lower()

    assert "do not create a production evidence confirm schedule" in text
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
