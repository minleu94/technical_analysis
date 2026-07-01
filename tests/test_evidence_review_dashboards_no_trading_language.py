from __future__ import annotations

from pathlib import Path


NEW_DASHBOARD_FILES = [
    Path("app_module/decision_quality_dashboard_dtos.py"),
    Path("app_module/decision_quality_dashboard_service.py"),
    Path("app_module/signal_decay_dashboard_dtos.py"),
    Path("app_module/signal_decay_dashboard_service.py"),
    Path("app_module/live_research_gap_dashboard_dtos.py"),
    Path("app_module/live_research_gap_dashboard_service.py"),
    Path("ui_qt/views/evidence_review_view.py"),
    Path("ui_qt/views/decision_quality_view.py"),
    Path("ui_qt/views/signal_decay_view.py"),
    Path("ui_qt/views/live_research_gap_view.py"),
    Path("ui_qt/models/decision_quality_table_model.py"),
    Path("ui_qt/models/signal_decay_table_model.py"),
    Path("ui_qt/models/live_research_gap_table_model.py"),
    Path("ui_qt/widgets/evidence_boundary_banner.py"),
]

FORBIDDEN_LANGUAGE = (
    "buy",
    "sell",
    "target price",
    "fair price",
    "high confidence",
)

FORBIDDEN_UI_IMPORTS = (
    "sqlite3",
    "DecisionQualityRepository",
    "SignalDecayRepository",
    "LiveResearchGapRepository",
    "EvidenceEventRepository",
    "ScoringEngine",
    "record_trade",
    "delete_trade",
    "apply_lifecycle",
    "TaskScheduler",
    "cron",
)


def test_evidence_review_dashboard_files_exist() -> None:
    missing = [str(path) for path in NEW_DASHBOARD_FILES if not path.exists()]
    assert missing == []


def test_evidence_review_dashboards_do_not_use_forbidden_trading_language() -> None:
    for path in NEW_DASHBOARD_FILES:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_LANGUAGE:
            assert phrase not in text, f"{path} contains forbidden phrase: {phrase}"


def test_evidence_review_ui_does_not_read_db_or_import_mutation_modules() -> None:
    ui_paths = [path for path in NEW_DASHBOARD_FILES if str(path).startswith("ui_qt")]
    for path in ui_paths:
        text = path.read_text(encoding="utf-8")
        for phrase in FORBIDDEN_UI_IMPORTS:
            assert phrase not in text, f"{path} contains forbidden UI boundary phrase: {phrase}"


def test_dashboard_services_do_not_call_write_methods() -> None:
    service_paths = [path for path in NEW_DASHBOARD_FILES if str(path).startswith("app_module")]
    forbidden_calls = (
        ".save_",
        ".mark_item_reviewed",
        ".mark_item_dismissed",
        ".create_action_item",
        ".save_gap_observation",
        ".save_decay_observation",
    )
    for path in service_paths:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden_calls:
            assert phrase not in text, f"{path} contains forbidden write call: {phrase}"
