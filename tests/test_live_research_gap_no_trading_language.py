from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "app_module" / "live_research_gap_dtos.py",
    ROOT / "app_module" / "live_research_gap_repository.py",
    ROOT / "app_module" / "live_research_gap_service.py",
    ROOT / "scripts" / "capture_live_research_gap.py",
    ROOT / "scripts" / "inspect_live_research_gap.py",
]


def _combined_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8").lower() for path in FILES if path.exists())


def test_live_research_gap_code_has_no_forbidden_trading_language():
    source = _combined_source()
    forbidden = ["buy / sell", "target price", "fair price", "high confidence"]
    for phrase in forbidden:
        assert phrase not in source


def test_live_research_gap_code_does_not_import_ui_or_scoring_or_mutation_modules():
    source = _combined_source()
    forbidden_imports = [
        "ui_qt",
        "scoringengine",
        "decision_module.scoring",
        "record_trade(",
        "delete_trade(",
        "clear_all_data(",
        "mark_promoted(",
    ]
    for phrase in forbidden_imports:
        assert phrase not in source


def test_live_research_gap_summary_boundary_text_is_research_only():
    source = _combined_source()
    assert "research_gap_observation" in source
    assert "production scheduler" not in source
