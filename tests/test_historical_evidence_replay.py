from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3

import pytest

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService
from app_module.forward_performance_service import ForwardPerformanceService
from app_module.historical_evidence_replay import (
    HistoricalEvidenceReplayDay,
    HistoricalEvidenceReplayRequest,
    HistoricalEvidenceReplayReport,
    HistoricalEvidenceReplayService,
)
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig
from tests.test_evidence_pipeline_smoke import _seed_market_db


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "data" / "sqlite" / "twstock.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_result(config: TWStockConfig, *, result_id: str, created_at: str) -> str:
    result = RecommendationResultDTO(
        result_id=result_id,
        result_name=f"Replay fixture {result_id}",
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
        created_at=created_at,
        screening_matrix_json=[
            {"stock_code": "2330", "status": "pass", "quality": "observed", "reason_codes": ["recommendation_selected"]}
        ],
        why_not_payload_json=[],
        liquidity_gate_payload_json=[],
    )
    return RecommendationRepository(config).save_result(result)


def test_replay_rejects_same_source_and_replay_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)

    with pytest.raises(ValueError, match="replay DB must be separate"):
        HistoricalEvidenceReplayService(config).run(
            HistoricalEvidenceReplayRequest(
                start_date="2026-07-01",
                end_date="2026-07-02",
                source_db_path=config.db_file,
                replay_db_path=config.db_file,
            )
        )


def test_replay_uses_only_recommendation_results_available_on_decision_date(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=6)
    _seed_result(config, result_id="past-rec", created_at="2026-07-01T06:00:00")
    _seed_result(config, result_id="future-rec", created_at="2026-07-04T06:00:00")
    replay_db = tmp_path / "replay" / "historical.db"

    report = HistoricalEvidenceReplayService(config).run(
        HistoricalEvidenceReplayRequest(
            start_date="2026-07-01",
            end_date="2026-07-02",
            source_db_path=config.db_file,
            replay_db_path=replay_db,
            sources=("recommendation",),
            windows=(2,),
            confirm=True,
        )
    )

    assert report.replay_mode == "historical_replay"
    assert report.source_label == "simulated_scheduler"
    assert [day.selected_recommendation_result_id for day in report.days] == ["past-rec", "past-rec"]
    events = EvidenceEventRepository(config, db_path=replay_db).list_events()
    assert events
    assert {event.source_id for event in events} == {"past-rec"}
    assert report.days[0].evidence_ids == tuple(event.event_id for event in events if event.decision_date == "2026-07-01")
    assert all(event.metadata["replay_mode"] == "historical_replay" for event in events)
    assert all(event.metadata["source_label"] == "simulated_scheduler" for event in events)


def test_replay_refuses_existing_working_copy_without_overwrite(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=3)
    _seed_result(config, result_id="past-rec", created_at="2026-07-01T06:00:00")
    replay_db = tmp_path / "replay" / "historical.db"
    replay_db.parent.mkdir(parents=True)
    shutil.copy2(config.db_file, replay_db)
    replay_config = TWStockConfig(data_root=config.data_root, output_root=config.output_root)
    replay_config.db_file = replay_db
    other_run_event = EvidenceEventService(EvidenceEventRepository(replay_config, db_path=replay_db)).record_event(
        event_date="2026-07-01",
        decision_date="2026-07-01",
        symbol="2330",
        event_type="recommendation_included",
        event_family="recommendation",
        source_type="recommendation_result",
        source_id="other-rec",
        source_snapshot_id="other-rec",
        data_quality="observed",
        as_of_date="2026-07-01",
        available_date="2026-07-01",
        metadata={"replay_run_id": "hre-other"},
    )

    with pytest.raises(FileExistsError, match="working copy already exists"):
        HistoricalEvidenceReplayService(config).run(
            HistoricalEvidenceReplayRequest(
                start_date="2026-07-01",
                end_date="2026-07-01",
                source_db_path=config.db_file,
                replay_db_path=replay_db,
                sources=("recommendation",),
                windows=(1,),
                confirm=True,
                replay_run_id="hre-current",
            )
        )

    assert other_run_event.event_id


def test_replay_does_not_fabricate_recommendation_when_no_asof_result_exists(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=3)
    _seed_result(config, result_id="future-rec", created_at="2026-07-03T06:00:00")
    replay_db = tmp_path / "replay" / "historical.db"

    report = HistoricalEvidenceReplayService(config).run(
        HistoricalEvidenceReplayRequest(
            start_date="2026-07-01",
            end_date="2026-07-01",
            source_db_path=config.db_file,
            replay_db_path=replay_db,
            sources=("recommendation",),
            windows=(1,),
            confirm=True,
        )
    )

    assert report.days[0].selected_recommendation_result_id is None
    assert "recommendation_asof_result_missing" in report.days[0].diagnostics
    assert EvidenceEventRepository(config, db_path=replay_db).list_events() == []


def test_forward_outcome_respects_data_as_of_date(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=4)
    repository = EvidenceEventRepository(config)
    event = EvidenceEventService(repository).record_event(
        event_date="2026-07-01",
        decision_date="2026-07-01",
        symbol="2330",
        event_type="recommendation_included",
        event_family="recommendation",
        source_type="recommendation_result",
        source_id="rec",
        source_snapshot_id="rec",
        data_quality="observed",
        as_of_date="2026-07-01",
        available_date="2026-07-01",
        metadata={"fixture": True},
    )

    early = ForwardPerformanceService(config, repository).calculate(
        windows=(2,),
        decision_date="2026-07-01",
        data_as_of_date="2026-07-02",
        dry_run=True,
    )
    late = ForwardPerformanceService(config, repository).calculate(
        windows=(2,),
        decision_date="2026-07-01",
        data_as_of_date="2026-07-03",
        dry_run=False,
    )

    assert event.event_id
    assert early.pending_insufficient_future_data == 1
    assert early.outcomes_created == 1
    assert late.outcomes_created == 1
    outcome = repository.get_outcome(event.event_id, 2)
    assert outcome is not None
    assert outcome.outcome_status.value == "ready"
    assert outcome.outcome_price_date == "2026-07-03"
    assert outcome.data_as_of_date == "2026-07-03"


def test_replay_discovers_trading_dates_from_source_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=3)
    with sqlite3.connect(config.db_file) as conn:
        conn.execute("DELETE FROM daily_prices WHERE 日期 = '20260702'")

    dates = HistoricalEvidenceReplayService(config).discover_trading_dates(
        source_db_path=config.db_file,
        start_date="2026-07-01",
        end_date="2026-07-03",
    )

    assert dates == ("2026-07-01", "2026-07-03")


def test_replay_working_copy_uses_sqlite_backup_for_wal_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    source = config.db_file
    replay_db = tmp_path / "replay" / "working.sqlite3"
    before_mtime: int
    with sqlite3.connect(source) as source_connection:
        source_connection.execute("PRAGMA journal_mode=WAL")
        source_connection.execute(
            "CREATE TABLE daily_prices (股票代碼 TEXT, 日期 TEXT, 收盤價 TEXT)"
        )
        source_connection.execute(
            "INSERT INTO daily_prices VALUES ('2330', '20260701', '100')"
        )
        source_connection.commit()
        before_mtime = source.stat().st_mtime_ns

        HistoricalEvidenceReplayService(config)._prepare_replay_db(
            source, replay_db, overwrite=False
        )

        with sqlite3.connect(replay_db) as replay_connection:
            assert replay_connection.execute(
                "SELECT 股票代碼, 日期 FROM daily_prices"
            ).fetchall() == [("2330", "20260701")]
        assert source.stat().st_mtime_ns == before_mtime


def test_replay_report_projects_read_only_rehearsal_artifact() -> None:
    report = HistoricalEvidenceReplayReport(
        replay_run_id="hre-fixture",
        replay_mode="historical_replay",
        source_label="simulated_scheduler",
        start_date="2026-07-01",
        end_date="2026-07-01",
        source_db_path="C:/fixtures/source.sqlite",
        replay_db_path="C:/fixtures/replay.sqlite",
        dry_run=True,
        confirm=False,
        outcome_mode="final",
        limitations=(),
        days=(
            HistoricalEvidenceReplayDay(
                decision_date="2026-07-01",
                selected_recommendation_result_id="rec-1",
                sources=("source-1",),
                events_seen=1,
                events_inserted=0,
                outcomes_created=0,
                outcomes_updated=0,
                outcomes_pending=1,
                blocking_gaps=(),
                diagnostics=("missing_benchmark",),
                evidence_ids=("event-1",),
            ),
        ),
    )

    artifacts = report.to_rehearsal_artifacts(
        decision_date="2026-07-01",
        rollback_reference="commit:fixture",
    )

    assert artifacts[0].parent_artifact_ids == ("source-1", "rec-1", "event-1")
    assert artifacts[0].canonical_payload is not None
    assert "score_effectiveness_rows" not in artifacts[0].canonical_payload


def test_replay_report_projects_multiple_days_by_their_own_decision_dates() -> None:
    report = HistoricalEvidenceReplayReport(
        replay_run_id="hre-fixture",
        replay_mode="historical_replay",
        source_label="simulated_scheduler",
        start_date="2026-07-09",
        end_date="2026-07-10",
        source_db_path="C:/fixtures/source.sqlite",
        replay_db_path="C:/fixtures/replay.sqlite",
        dry_run=True,
        confirm=False,
        outcome_mode="final",
        limitations=(),
        days=tuple(
            HistoricalEvidenceReplayDay(
                decision_date=decision_date,
                selected_recommendation_result_id=None,
                sources=(),
                events_seen=0,
                events_inserted=0,
                outcomes_created=0,
                outcomes_updated=0,
                outcomes_pending=0,
                blocking_gaps=(),
            )
            for decision_date in ("2026-07-09", "2026-07-10")
        ),
    )

    artifacts = report.to_rehearsal_artifacts(
        decision_date="2026-07-10",
        rollback_reference="commit:fixture",
    )

    assert [artifact.decision_date for artifact in artifacts] == ["2026-07-09", "2026-07-10"]
