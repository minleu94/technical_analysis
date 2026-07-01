from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig


ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_recommendation(config: TWStockConfig) -> str:
    result = RecommendationResultDTO(
        result_id="rec-cli-001",
        result_name="CLI Evidence Test",
        config={"profile_id": "balanced", "profile_version": "1.0"},
        recommendations=[
            RecommendationDTO(
                stock_code="2330",
                stock_name="台積電",
                close_price=100.0,
                price_change=1.0,
                total_score=90.0,
                indicator_score=30.0,
                pattern_score=30.0,
                volume_score=30.0,
                recommendation_reasons="rank_top",
                industry="半導體",
                regime_match=True,
                score_percentile_bp=9500,
            )
        ],
        regime="Trend",
        created_at="2026-07-02T09:00:00",
    )
    RecommendationRepository(config).save_result(result)
    return result.result_id


def _run_capture(config: TWStockConfig, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "capture_evidence_events.py"),
            "--data-root",
            str(config.data_root),
            "--output-root",
            str(config.output_root),
            "--db-path",
            str(config.db_file),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_inspect(config: TWStockConfig, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "inspect_evidence_events.py"),
            "--data-root",
            str(config.data_root),
            "--output-root",
            str(config.output_root),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_capture_evidence_events_cli_defaults_to_dry_run(tmp_path):
    config = _config(tmp_path)
    result_id = _seed_recommendation(config)

    result = _run_capture(config, "--source", "recommendation", "--result-id", result_id)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["events_seen"] == 1
    assert payload["events_inserted"] == 0
    assert EvidenceEventRepository(config).list_events() == []


def test_capture_evidence_events_cli_confirm_writes_and_source_all_skips_unsupported(tmp_path):
    config = _config(tmp_path)
    result_id = _seed_recommendation(config)

    result = _run_capture(
        config,
        "--source",
        "all",
        "--result-id",
        result_id,
        "--confirm",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    assert payload["events_inserted"] == 1
    assert payload["diagnostics_by_code"]["source_unsupported"] >= 1
    assert len(EvidenceEventRepository(config).list_events()) == 1

    inspected = _run_inspect(config, "--event-type", "recommendation_included")
    assert inspected.returncode == 0, inspected.stderr
    inspected_payload = json.loads(inspected.stdout)
    assert inspected_payload["events_count"] == 1
