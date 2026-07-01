from __future__ import annotations

import json
import sqlite3
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
    config.db_file = tmp_path / "data" / "sqlite" / "twstock.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_market_db(config: TWStockConfig, *, days: int = 8, with_benchmark: bool = True) -> None:
    with sqlite3.connect(config.db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                收盤價 REAL,
                PRIMARY KEY (證券代號, 日期)
            );
            CREATE TABLE IF NOT EXISTS market_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                PRIMARY KEY (指數名稱, 日期)
            );
            CREATE TABLE IF NOT EXISTS industry_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                PRIMARY KEY (指數名稱, 日期)
            );
            """
        )
        for offset in range(days):
            day = f"202607{offset + 1:02d}"
            conn.execute("INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?)", (day, "2330", 100 + offset))
            if with_benchmark:
                conn.execute("INSERT OR REPLACE INTO market_indices VALUES (?, ?, ?)", (day, "TAIEX", 10000 + offset))
            conn.execute("INSERT OR REPLACE INTO industry_indices VALUES (?, ?, ?)", (day, "半導體", 1000 + offset))


def _seed_recommendation(config: TWStockConfig, result_id: str = "rec-smoke-001") -> str:
    result = RecommendationResultDTO(
        result_id=result_id,
        result_name="Evidence Pipeline Smoke Fixture",
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
        created_at="2026-07-01T09:00:00",
    )
    RecommendationRepository(config).save_result(result)
    return result.result_id


def _run_smoke(config: TWStockConfig, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "smoke_evidence_pipeline.py"),
            "--db-path",
            str(config.db_file),
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


def test_evidence_pipeline_smoke_dry_run_does_not_write_events_or_outcomes(tmp_path):
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)

    result = _run_smoke(
        config,
        "--recommendation-result-id",
        result_id,
        "--decision-date",
        "2026-07-01",
        "--windows",
        "5",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["events_seen"] == 1
    assert payload["events_inserted"] == 0
    assert payload["outcomes_created"] == 0
    assert EvidenceEventRepository(config).list_events() == []


def test_evidence_pipeline_smoke_confirm_writes_event_and_ready_outcome(tmp_path):
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)

    result = _run_smoke(
        config,
        "--recommendation-result-id",
        result_id,
        "--decision-date",
        "2026-07-01",
        "--windows",
        "5",
        "--confirm",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is False
    assert payload["events_inserted"] == 1
    assert payload["outcomes_created"] == 1
    assert payload["outcome_status_counts"] == {"ready": 1}
    assert payload["sample_events"][0]["event_type"] == "recommendation_included"
    assert payload["sample_outcomes"][0]["return_basis"] == "close_to_close_event_date"


def test_evidence_pipeline_smoke_confirm_is_idempotent_for_duplicate_event(tmp_path):
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)
    args = (
        "--recommendation-result-id",
        result_id,
        "--decision-date",
        "2026-07-01",
        "--windows",
        "5",
        "--confirm",
    )

    first = _run_smoke(config, *args)
    second = _run_smoke(config, *args)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    payload = json.loads(second.stdout)
    assert payload["events_inserted"] == 0
    assert payload["events_skipped_duplicate"] == 1
    assert len(EvidenceEventRepository(config).list_events()) == 1


def test_evidence_pipeline_smoke_marks_future_data_insufficient_as_pending(tmp_path):
    config = _config(tmp_path)
    _seed_market_db(config, days=3)
    result_id = _seed_recommendation(config)

    result = _run_smoke(
        config,
        "--recommendation-result-id",
        result_id,
        "--decision-date",
        "2026-07-01",
        "--windows",
        "5",
        "--confirm",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcomes_pending"] == 1
    assert payload["outcome_status_counts"] == {"insufficient_future_data": 1}


def test_evidence_pipeline_smoke_missing_benchmark_does_not_stop_outcome(tmp_path):
    config = _config(tmp_path)
    _seed_market_db(config, with_benchmark=False)
    result_id = _seed_recommendation(config)

    result = _run_smoke(
        config,
        "--recommendation-result-id",
        result_id,
        "--decision-date",
        "2026-07-01",
        "--windows",
        "5",
        "--confirm",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcomes_created"] == 1
    assert payload["missing_benchmark"] == 1
    assert payload["outcome_status_counts"] == {"ready": 1}


def test_evidence_pipeline_smoke_summary_has_no_trading_language_and_no_ui_import():
    script_text = (ROOT / "scripts" / "smoke_evidence_pipeline.py").read_text(encoding="utf-8")

    assert "ui_qt" not in script_text
    lowered = script_text.lower()
    assert "target price" not in lowered
    assert "fair price" not in lowered
    assert "high confidence" not in lowered

