from __future__ import annotations

import json
import subprocess
import sys
from datetime import date

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import build_stored_decision_desk_snapshot
from app_module.evidence_event_dtos import EvidenceEventType
from app_module.evidence_event_repository import EvidenceEventRepository
from data_module.config import TWStockConfig
from tests.test_decision_desk_snapshot_repository import _snapshot


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _capture(config, source: str):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/capture_evidence_events.py",
            "--source",
            source,
            "--decision-date",
            "2026-06-30",
            "--db-path",
            str(config.db_file),
            "--data-root",
            str(config.data_root),
            "--output-root",
            str(config.output_root),
            "--confirm",
            "--json-output",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_importers_read_watchlist_portfolio_and_risk_prompt_from_durable_snapshot(tmp_path):
    config = _config(tmp_path)
    DecisionDeskSnapshotRepository(config).save_snapshot(
        build_stored_decision_desk_snapshot(_snapshot(date(2026, 6, 30)))
    )

    summary = _capture(config, "all")
    event_types = summary["event_type_counts"]

    assert event_types[EvidenceEventType.WATCHLIST_TRIGGER_ADDED.value] == 1
    assert event_types[EvidenceEventType.WATCHLIST_TRIGGER_STRENGTH_DOWN.value] == 1
    assert event_types[EvidenceEventType.PORTFOLIO_ALERT_CONDITION_WARNING.value] == 1
    assert event_types[EvidenceEventType.RISK_PROMPT_LOW_LIQUIDITY.value] == 1
    assert summary["diagnostics_by_code"].get("source_unsupported", 0) == 0
    saved_events = EvidenceEventRepository(config).list_events(decision_date="2026-06-30")
    assert {event.source_snapshot_id for event in saved_events if event.source_type.startswith("daily_decision_desk")}


def test_cli_without_snapshot_reports_diagnostic_and_does_not_forge_event(tmp_path):
    config = _config(tmp_path)

    summary = _capture(config, "watchlist-trigger")

    assert summary["events_seen"] == 0
    assert summary["diagnostics_by_code"]["source_missing_snapshot"] == 1
    assert EvidenceEventRepository(config).list_events(decision_date="2026-06-30") == []
