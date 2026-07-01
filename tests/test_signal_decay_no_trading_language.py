from __future__ import annotations

from pathlib import Path


FILES = (
    Path("app_module/signal_decay_dtos.py"),
    Path("app_module/signal_decay_repository.py"),
    Path("app_module/signal_decay_service.py"),
    Path("scripts/capture_signal_decay.py"),
    Path("scripts/inspect_signal_decay.py"),
)


def test_signal_decay_files_do_not_use_forbidden_language_or_boundaries() -> None:
    forbidden_terms = [
        "b" + "uy",
        "s" + "ell",
        "target " + "price",
        "fair " + "price",
        "high " + "confidence",
    ]
    forbidden_boundaries = [
        "ui_qt",
        "ScoringEngine",
        "portfolio_module",
        "record_trade(",
        "delete_trade(",
        "clear_all_data(",
    ]

    for path in FILES:
        text = path.read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            assert term not in text, f"{path} contains forbidden wording: {term}"
        for boundary in forbidden_boundaries:
            assert boundary.lower() not in text, f"{path} imports or calls forbidden boundary: {boundary}"

