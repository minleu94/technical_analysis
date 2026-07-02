from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_DIR = ROOT / "scripts" / "scheduled"


FORBIDDEN_PHRASES = (
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


def test_scheduled_scripts_do_not_use_trading_language() -> None:
    offenders: list[tuple[str, str]] = []
    for path in SCHEDULED_DIR.glob("*"):
        if path.suffix.lower() not in {".ps1", ".md"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase.lower() in text:
                offenders.append((path.name, phrase))

    assert offenders == []
