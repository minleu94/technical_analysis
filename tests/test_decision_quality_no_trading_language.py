from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_FILES = [
    ROOT / "app_module" / "decision_quality_dtos.py",
    ROOT / "app_module" / "decision_quality_repository.py",
    ROOT / "app_module" / "decision_quality_service.py",
    ROOT / "scripts" / "inspect_decision_quality.py",
    ROOT / "scripts" / "capture_decision_quality_review.py",
]


def test_decision_quality_files_do_not_contain_trading_advice_language() -> None:
    forbidden = [
        "b" + "uy",
        "s" + "ell",
        "target " + "price",
        "fair " + "price",
        "high " + "confidence",
    ]
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in SCAN_FILES if path.exists())

    for phrase in forbidden:
        assert phrase not in text


def test_decision_quality_files_do_not_import_forbidden_layers() -> None:
    forbidden = [
        "ui_qt",
        "ScoringEngine",
        "record_" + "trade(",
        "delete_" + "trade(",
        "clear_" + "all_data(",
        "record_" + "decision(",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in SCAN_FILES if path.exists())

    for phrase in forbidden:
        assert phrase not in text
