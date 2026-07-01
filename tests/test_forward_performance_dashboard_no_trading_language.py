from __future__ import annotations

from pathlib import Path


DASHBOARD_FILES = (
    Path("app_module/forward_performance_dashboard_dtos.py"),
    Path("app_module/forward_performance_dashboard_service.py"),
    Path("ui_qt/views/forward_performance_view.py"),
    Path("ui_qt/models/forward_performance_table_model.py"),
)

FORBIDDEN_TRADING_PHRASES = (
    "buy",
    "sell",
    "target price",
    "fair price",
    "high confidence",
)

FORBIDDEN_IMPORT_FRAGMENTS = (
    "decision_module.scoring_engine",
    "ScoringEngine",
    "portfolio_module",
    "portfolio_service",
    "record_trade",
    "insert_event",
    "upsert_outcome",
    "EvidenceCaptureService",
)


def _existing_dashboard_texts() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in DASHBOARD_FILES if path.exists()}


def test_dashboard_files_do_not_use_forbidden_trading_language() -> None:
    texts = _existing_dashboard_texts()
    assert texts, "dashboard files should exist"

    for path, text in texts.items():
        lowered = text.lower()
        for phrase in FORBIDDEN_TRADING_PHRASES:
            assert phrase not in lowered, f"{phrase!r} found in {path}"


def test_dashboard_surface_does_not_import_mutation_or_scoring_paths() -> None:
    texts = _existing_dashboard_texts()
    assert texts, "dashboard files should exist"

    for path, text in texts.items():
        for fragment in FORBIDDEN_IMPORT_FRAGMENTS:
            assert fragment not in text, f"{fragment!r} found in {path}"


def test_forward_performance_view_does_not_read_sqlite_directly() -> None:
    path = Path("ui_qt/views/forward_performance_view.py")
    assert path.exists()

    text = path.read_text(encoding="utf-8")

    assert "sqlite3" not in text
    assert "EvidenceEventRepository" not in text
    assert "ForwardPerformanceReadModel" not in text
