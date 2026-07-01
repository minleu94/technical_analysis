from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig
from tests.test_evidence_pipeline_smoke import _seed_market_db


def _config(tmp_path: Path, *, db_name: str = "source.db") -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / db_name
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_recommendation(config: TWStockConfig) -> str:
    result = RecommendationResultDTO(
        result_id="working-copy-rec",
        result_name="Working copy smoke fixture",
        config={"profile_id": "balanced", "profile_version": "1.0"},
        recommendations=[
            RecommendationDTO(
                stock_code="2330",
                stock_name="TSMC",
                close_price=100.0,
                price_change=1.0,
                total_score=88.0,
                indicator_score=30.0,
                pattern_score=28.0,
                volume_score=30.0,
                recommendation_reasons="rank_top",
                industry="半導體",
                regime_match=True,
                score_percentile_bp=9300,
            )
        ],
        regime="Trend",
        created_at="2026-07-01T09:00:00",
    )
    return RecommendationRepository(config).save_result(result)


def _event_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evidence_events'").fetchone()
        if row is None:
            return 0
        return int(conn.execute("SELECT COUNT(*) FROM evidence_events").fetchone()[0])


def _outcome_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evidence_outcomes'").fetchone()
        if row is None:
            return 0
        return int(conn.execute("SELECT COUNT(*) FROM evidence_outcomes").fetchone()[0])


def _run_smoke(config: TWStockConfig, working_copy: Path, report_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/smoke_evidence_pipeline_working_copy.py",
            "--source-db-path",
            str(config.db_file),
            "--working-copy-db-path",
            str(working_copy),
            "--decision-date",
            "2026-07-01",
            "--sources",
            "recommendation",
            "--windows",
            "5",
            "--repeat",
            "2",
            "--report-output",
            str(report_path),
            "--json-output",
            "--data-root",
            str(config.data_root),
            "--output-root",
            str(config.output_root),
            *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_working_copy_smoke_writes_only_working_copy_and_repeat_is_idempotent(tmp_path: Path) -> None:
    source_config = _config(tmp_path)
    _seed_market_db(source_config)
    _seed_recommendation(source_config)
    working_copy = tmp_path / "working-copy.db"
    report_path = tmp_path / "smoke-report.md"

    completed = _run_smoke(source_config, working_copy, report_path)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["source_db_path"] == str(source_config.db_file)
    assert payload["working_copy_db_path"] == str(working_copy)
    assert payload["repeat_count"] == 2
    assert payload["event_count_before"] == 0
    assert payload["event_count_after_run_1"] == 1
    assert payload["event_count_after_run_2"] == 1
    assert payload["outcome_count_after_run_1"] == 1
    assert payload["outcome_count_after_run_2"] == 1
    assert payload["duplicate_events_detected"] is False
    assert payload["idempotency_check"]["passed"] is True
    assert _event_count(source_config.db_file) == 0
    assert _event_count(working_copy) == 1
    assert _outcome_count(working_copy) == 1
    assert report_path.exists()


def test_working_copy_smoke_missing_durable_source_becomes_blocking_gap(tmp_path: Path) -> None:
    source_config = _config(tmp_path)
    _seed_market_db(source_config)
    working_copy = tmp_path / "working-copy.db"
    report_path = tmp_path / "smoke-report.md"

    completed = _run_smoke(
        source_config,
        working_copy,
        report_path,
        "--sources",
        "watchlist-trigger",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["readiness_after_smoke"] in {"not_ready", "dry_run_only", "ready_for_design"}
    assert "watchlist_trigger_not_ready" in payload["blocking_gaps"]
    assert payload["event_count_after_run_2"] == 0


def test_working_copy_smoke_rejects_same_source_and_working_copy_path(tmp_path: Path) -> None:
    source_config = _config(tmp_path)
    _seed_market_db(source_config)

    completed = _run_smoke(source_config, source_config.db_file, tmp_path / "smoke-report.md")

    assert completed.returncode != 0
    assert "working-copy DB must differ from source DB" in completed.stderr


def test_working_copy_smoke_script_has_no_forbidden_imports_or_language() -> None:
    text = Path("scripts/smoke_evidence_pipeline_working_copy.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "ui_qt" not in text
    assert "ScoringEngine" not in text
    assert "portfolio_module" not in text
    for forbidden in ("buy", "sell", "target price", "fair price", "high confidence"):
        assert forbidden not in lowered
