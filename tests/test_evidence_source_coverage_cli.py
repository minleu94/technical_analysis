from __future__ import annotations

import json
import subprocess
import sys
from datetime import date

from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
from app_module.decision_desk_snapshot_storage_dtos import build_stored_decision_desk_snapshot
from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig
from tests.test_decision_desk_snapshot_repository import _snapshot


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _inspect(config):
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/inspect_evidence_source_coverage.py",
            "--db-path",
            str(config.db_file),
            "--data-root",
            str(config.data_root),
            "--output-root",
            str(config.output_root),
            "--json-output",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_coverage_cli_reports_blocking_gaps_without_snapshot(tmp_path):
    summary = _inspect(_config(tmp_path))

    assert summary["decision_desk_snapshots_count"] == 0
    assert summary["watchlist_trigger_capture_ready"] is False
    assert summary["scheduler_readiness"] == "not_ready"
    assert "decision_desk_snapshot_missing" in summary["blocking_gaps"]


def test_coverage_cli_marks_design_ready_only_when_sources_are_durable(tmp_path):
    config = _config(tmp_path)
    DecisionDeskSnapshotRepository(config).save_snapshot(
        build_stored_decision_desk_snapshot(_snapshot(date(2026, 6, 30)))
    )
    RecommendationRepository(config).save_result(
        RecommendationResultDTO(
            result_id="rec-ready",
            result_name="Ready fixture",
            config={},
            recommendations=[
                RecommendationDTO(
                    stock_code="2330",
                    stock_name="TSMC",
                    close_price=100.0,
                    price_change=1.0,
                    total_score=80.0,
                    indicator_score=30.0,
                    pattern_score=30.0,
                    volume_score=20.0,
                    recommendation_reasons="rank_top",
                    industry="Semi",
                    regime_match=True,
                )
            ],
            why_not_payload_json=[{"stock_code": "1101", "exclusion_reason_codes": ["weak_relative_strength"]}],
            liquidity_gate_payload_json=[{"stock_code": "2201", "exclusion_reason_codes": ["low_liquidity"]}],
        )
    )

    summary = _inspect(config)

    assert summary["recommendation_persisted_available"] is True
    assert summary["recommendation_exclusion_payload_available"] is True
    assert summary["watchlist_trigger_capture_ready"] is True
    assert summary["portfolio_alert_capture_ready"] is True
    assert summary["risk_prompt_capture_ready"] is True
    assert summary["why_not_capture_ready"] is True
    assert summary["liquidity_gate_capture_ready"] is True
    assert summary["scheduler_readiness"] == "ready_for_design"
    assert summary["scheduler_readiness"] != "production_ready"
