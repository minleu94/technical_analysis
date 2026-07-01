from __future__ import annotations

import sqlite3
from pathlib import Path

from data_module.config import TWStockConfig
from app_module.evidence_event_dtos import (
    EvidenceDataQuality,
    EvidenceEventType,
    EvidenceOutcomeStatus,
)
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.forward_performance_service import ForwardPerformanceService


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_prices(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
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
        for index in range(0, 8):
            day = f"202606{index + 1:02d}"
            conn.execute(
                "INSERT INTO daily_prices VALUES (?, ?, ?)",
                (day, "2330", 100 + index * 2),
            )
            conn.execute(
                "INSERT INTO market_indices VALUES (?, ?, ?)",
                (day, "TAIEX", 10000 + index * 10),
            )
            conn.execute(
                "INSERT INTO industry_indices VALUES (?, ?, ?)",
                (day, "半導體類指數", 500 + index * 5),
            )


def _record_event(config: TWStockConfig, *, benchmark_id: str | None = "TAIEX", industry_id: str | None = "半導體類指數"):
    service = EvidenceEventService(EvidenceEventRepository(config))
    return service.record_event(
        event_date="2026-06-01",
        decision_date="2026-06-01",
        symbol="2330",
        event_type=EvidenceEventType.WATCHLIST_TRIGGER,
        event_family="watchlist",
        source_type="decision_desk",
        source_id="desk-001",
        reason_codes=("rank_top",),
        data_quality=EvidenceDataQuality.OBSERVED,
        warnings=(),
        as_of_date="2026-06-01",
        available_date="2026-06-01",
        source_version="test",
        benchmark_id=benchmark_id,
        industry_benchmark_id=industry_id,
    )


def test_forward_outcome_uses_trading_day_window_not_calendar_days(tmp_path):
    config = _config(tmp_path)
    _seed_prices(config.db_file)
    event = _record_event(config)
    forward = ForwardPerformanceService(config, EvidenceEventRepository(config))

    summary = forward.calculate(windows=(5,), dry_run=False)
    outcome = forward.repository.list_outcomes(event_id=event.event_id)[0]

    assert summary.events_scanned == 1
    assert summary.outcomes_created == 1
    assert outcome.outcome_status == EvidenceOutcomeStatus.READY
    assert outcome.event_price_date == "2026-06-01"
    assert outcome.outcome_price_date == "2026-06-06"
    assert outcome.forward_return_bp == 1000
    assert outcome.return_basis == "close_to_close_event_date"
    assert outcome.window_type == "trading_days"


def test_forward_outcome_marks_insufficient_future_data_without_failing_batch(tmp_path):
    config = _config(tmp_path)
    _seed_prices(config.db_file)
    event = _record_event(config)
    forward = ForwardPerformanceService(config, EvidenceEventRepository(config))

    summary = forward.calculate(windows=(60,), dry_run=False)
    outcome = forward.repository.list_outcomes(event_id=event.event_id)[0]

    assert summary.pending_insufficient_future_data == 1
    assert outcome.outcome_status == EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA
    assert "insufficient_future_data" in outcome.warnings


def test_missing_benchmark_and_industry_create_warnings_not_batch_failure(tmp_path):
    config = _config(tmp_path)
    _seed_prices(config.db_file)
    event = _record_event(config, benchmark_id="MISSING_INDEX", industry_id="MISSING_INDUSTRY")
    forward = ForwardPerformanceService(config, EvidenceEventRepository(config))

    summary = forward.calculate(windows=(5,), dry_run=False)
    outcome = forward.repository.list_outcomes(event_id=event.event_id)[0]

    assert summary.events_ready == 1
    assert summary.missing_benchmark == 1
    assert summary.missing_industry_benchmark == 1
    assert outcome.outcome_status == EvidenceOutcomeStatus.READY
    assert outcome.benchmark_return_bp is None
    assert outcome.industry_return_bp is None
    assert "missing_benchmark" in outcome.warnings
    assert "missing_industry_benchmark" in outcome.warnings


def test_dry_run_does_not_write_outcomes(tmp_path):
    config = _config(tmp_path)
    _seed_prices(config.db_file)
    event = _record_event(config)
    repo = EvidenceEventRepository(config)
    forward = ForwardPerformanceService(config, repo)

    summary = forward.calculate(windows=(5,), dry_run=True)

    assert summary.dry_run is True
    assert summary.outcomes_created == 1
    assert repo.list_outcomes(event_id=event.event_id) == []


def test_calculator_filters_symbol_event_type_and_decision_date(tmp_path):
    config = _config(tmp_path)
    _seed_prices(config.db_file)
    event = _record_event(config)
    forward = ForwardPerformanceService(config, EvidenceEventRepository(config))

    skipped = forward.calculate(windows=(5,), symbol="2317", dry_run=True)
    selected = forward.calculate(
        windows=(5,),
        symbol="2330",
        event_type=EvidenceEventType.WATCHLIST_TRIGGER,
        decision_date="2026-06-01",
        dry_run=True,
    )

    assert skipped.events_scanned == 0
    assert selected.events_scanned == 1
    assert selected.events_ready == 1
    assert event.symbol == "2330"
