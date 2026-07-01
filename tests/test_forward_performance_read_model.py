from __future__ import annotations

from pathlib import Path

from app_module.evidence_event_dtos import EvidenceDataQuality, EvidenceEvent, EvidenceOutcome, EvidenceOutcomeStatus
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.forward_performance_read_model import (
    SUMMARY_STATUS_INSUFFICIENT_SAMPLE,
    SUMMARY_STATUS_MISSING_BENCHMARK,
    SUMMARY_STATUS_READY,
    ForwardPerformanceFilter,
    ForwardPerformanceReadModel,
)
from data_module.config import TWStockConfig


def _repo(tmp_path: Path) -> EvidenceEventRepository:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "out")
    config.db_file = tmp_path / "data" / "sqlite" / "twstock.db"
    return EvidenceEventRepository(config)


def _event(
    event_id: str,
    *,
    event_type: str = "recommendation_included",
    regime: str = "Trend",
    sector: str = "半導體",
    profile_id: str = "balanced",
    score_percentile_bp: int | None = 9000,
    data_quality: str = "observed",
) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=event_id,
        event_hash=f"hash-{event_id}",
        event_date="2026-07-01",
        decision_date="2026-07-01",
        symbol="2330",
        event_type=event_type,
        event_family="daily_decision",
        source_type="recommendation",
        source_id=f"source-{event_id}",
        strategy_version_id="v1",
        profile_id=profile_id,
        score_percentile_bp=score_percentile_bp,
        regime=regime,
        sector=sector,
        liquidity_state="normal",
        data_quality=data_quality,
        as_of_date="2026-07-01",
        available_date="2026-07-01",
        source_version="test-fixture",
    )


def _outcome(
    event_id: str,
    *,
    window_days: int = 5,
    forward_return_bp: int | None = 100,
    benchmark_excess_bp: int | None = 50,
    industry_excess_bp: int | None = 25,
    status: str = "ready",
    data_quality: str = "observed",
    warnings: tuple[str, ...] = (),
) -> EvidenceOutcome:
    return EvidenceOutcome(
        outcome_id=f"out-{event_id}-{window_days}",
        event_id=event_id,
        window_days=window_days,
        event_price_date="2026-07-01",
        outcome_price_date="2026-07-08",
        forward_return_bp=forward_return_bp,
        benchmark_excess_bp=benchmark_excess_bp,
        industry_excess_bp=industry_excess_bp,
        max_adverse_excursion_bp=-30 if status == "ready" else None,
        max_favorable_excursion_bp=140 if status == "ready" else None,
        outcome_status=status,
        data_quality=data_quality,
        warnings=warnings,
    )


def test_group_by_event_type_and_ready_metrics(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1"))
    repo.insert_event(_event("evt-2"))
    repo.upsert_outcome(_outcome("evt-1", forward_return_bp=100, benchmark_excess_bp=50, industry_excess_bp=20))
    repo.upsert_outcome(_outcome("evt-2", forward_return_bp=-50, benchmark_excess_bp=-100, industry_excess_bp=10))

    summaries = ForwardPerformanceReadModel(repo).summarize(group_by="event_type")

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.group_key == "recommendation_included"
    assert summary.sample_size == 2
    assert summary.mean_forward_return_bp == 25
    assert summary.median_forward_return_bp == 25
    assert summary.positive_rate_bp == 5000
    assert summary.win_vs_benchmark_rate_bp == 5000
    assert summary.summary_status == SUMMARY_STATUS_READY


def test_group_by_regime_and_score_percentile_bucket(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1", regime="Trend", score_percentile_bp=9500))
    repo.insert_event(_event("evt-2", regime="MeanReversion", score_percentile_bp=3500))
    repo.upsert_outcome(_outcome("evt-1"))
    repo.upsert_outcome(_outcome("evt-2"))

    regimes = ForwardPerformanceReadModel(repo).summarize(group_by="regime")
    buckets = ForwardPerformanceReadModel(repo).summarize(group_by="score_percentile_bucket")

    assert {item.group_key for item in regimes} == {"Trend", "MeanReversion"}
    assert {item.group_key for item in buckets} == {"8001-10000", "2001-4000"}


def test_insufficient_sample_and_pending_not_in_mean(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1"))
    repo.insert_event(_event("evt-2"))
    repo.upsert_outcome(_outcome("evt-1", forward_return_bp=100))
    repo.upsert_outcome(
        _outcome(
            "evt-2",
            forward_return_bp=None,
            benchmark_excess_bp=None,
            industry_excess_bp=None,
            status=EvidenceOutcomeStatus.INSUFFICIENT_FUTURE_DATA,
            data_quality=EvidenceDataQuality.MISSING,
            warnings=("insufficient_future_data",),
        )
    )

    summary = ForwardPerformanceReadModel(repo).summarize(group_by="event_type", min_sample_size=2)[0]

    assert summary.sample_size == 1
    assert summary.pending_count == 1
    assert summary.mean_forward_return_bp == 100
    assert summary.summary_status == SUMMARY_STATUS_INSUFFICIENT_SAMPLE


def test_missing_benchmark_and_industry_are_statused_and_counted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1", data_quality="degraded"))
    repo.insert_event(_event("evt-2", data_quality="degraded"))
    repo.upsert_outcome(
        _outcome(
            "evt-1",
            benchmark_excess_bp=None,
            industry_excess_bp=None,
            data_quality="degraded",
            warnings=("missing_benchmark", "missing_industry_benchmark"),
        )
    )
    repo.upsert_outcome(
        _outcome(
            "evt-2",
            benchmark_excess_bp=None,
            industry_excess_bp=None,
            data_quality="degraded",
            warnings=("missing_benchmark", "missing_industry_benchmark"),
        )
    )

    summary = ForwardPerformanceReadModel(repo).summarize(group_by="event_type")[0]

    assert summary.summary_status == SUMMARY_STATUS_MISSING_BENCHMARK
    assert summary.mean_benchmark_excess_bp is None
    assert summary.warning_counts["missing_benchmark"] == 2
    assert summary.warning_counts["missing_industry_benchmark"] == 2
    assert summary.quality_counts["degraded"] == 4


def test_filter_by_window_and_no_ui_import(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.insert_event(_event("evt-1"))
    repo.upsert_outcome(_outcome("evt-1", window_days=5, forward_return_bp=100))
    repo.upsert_outcome(_outcome("evt-1", window_days=20, forward_return_bp=400))

    summary = ForwardPerformanceReadModel(repo).summarize(
        group_by="event_type",
        filters=ForwardPerformanceFilter(window_days=20),
    )[0]
    script_text = Path("scripts/summarize_forward_performance.py").read_text(encoding="utf-8")

    assert summary.window_days == 20
    assert summary.mean_forward_return_bp == 400
    assert "ui_qt" not in script_text
