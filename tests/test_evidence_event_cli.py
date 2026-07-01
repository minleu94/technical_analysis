from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from data_module.config import TWStockConfig
from app_module.evidence_event_dtos import EvidenceDataQuality, EvidenceEventType
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService


ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_db(config: TWStockConfig) -> None:
    with sqlite3.connect(config.db_file) as conn:
        conn.executescript(
            """
            CREATE TABLE daily_prices (
                日期 TEXT,
                證券代號 TEXT,
                收盤價 REAL,
                PRIMARY KEY (證券代號, 日期)
            );
            CREATE TABLE market_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                PRIMARY KEY (指數名稱, 日期)
            );
            CREATE TABLE industry_indices (
                日期 TEXT,
                指數名稱 TEXT,
                收盤指數 REAL,
                PRIMARY KEY (指數名稱, 日期)
            );
            """
        )
        for index in range(0, 7):
            day = f"202606{index + 1:02d}"
            conn.execute("INSERT INTO daily_prices VALUES (?, ?, ?)", (day, "2330", 100 + index))
            conn.execute("INSERT INTO market_indices VALUES (?, ?, ?)", (day, "TAIEX", 10000 + index))

    service = EvidenceEventService(EvidenceEventRepository(config))
    service.record_event(
        event_date="2026-06-01",
        decision_date="2026-06-01",
        symbol="2330",
        event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
        event_family="recommendation",
        source_type="recommendation_result",
        source_id="rec-001",
        reason_codes=("rank_top",),
        data_quality=EvidenceDataQuality.OBSERVED,
        warnings=(),
        as_of_date="2026-06-01",
        available_date="2026-06-01",
        source_version="test",
        benchmark_id="TAIEX",
        industry_benchmark_id="半導體類指數",
    )


def _run_script(script: str, *args: str, data_root: Path, output_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / script),
            "--data-root",
            str(data_root),
            "--output-root",
            str(output_root),
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_inspect_evidence_events_cli_outputs_json_summary(tmp_path):
    config = _config(tmp_path)
    _seed_db(config)

    result = _run_script(
        "inspect_evidence_events.py",
        "--event-type",
        "recommendation_included",
        data_root=config.data_root,
        output_root=config.output_root,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["events_count"] == 1
    assert payload["outcomes_count"] == 0
    assert payload["event_types"] == {"recommendation_included": 1}


def test_calculate_forward_outcomes_cli_dry_run_summary_has_required_fields_and_no_trading_language(tmp_path):
    config = _config(tmp_path)
    _seed_db(config)

    result = _run_script(
        "calculate_forward_outcomes.py",
        "--event-type",
        "recommendation_included",
        "--windows",
        "5",
        "--dry-run",
        data_root=config.data_root,
        output_root=config.output_root,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    required = {
        "events_scanned",
        "events_ready",
        "outcomes_created",
        "outcomes_updated",
        "pending_insufficient_future_data",
        "missing_event_price",
        "missing_outcome_price",
        "missing_benchmark",
        "missing_industry_benchmark",
        "warnings_count",
        "dry_run",
    }
    assert required.issubset(payload)
    assert payload["dry_run"] is True
    forbidden = result.stdout.lower()
    assert "buy" not in forbidden
    assert "sell" not in forbidden
    assert "target price" not in forbidden
    assert "fair price" not in forbidden


def test_calculate_forward_outcomes_cli_writes_when_not_dry_run(tmp_path):
    config = _config(tmp_path)
    _seed_db(config)

    result = _run_script(
        "calculate_forward_outcomes.py",
        "--event-type",
        "recommendation_included",
        "--windows",
        "5",
        data_root=config.data_root,
        output_root=config.output_root,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcomes_created"] == 1
    repo = EvidenceEventRepository(config)
    event = repo.list_events()[0]
    assert len(repo.list_outcomes(event_id=event.event_id)) == 1
