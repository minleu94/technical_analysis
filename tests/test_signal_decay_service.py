from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from app_module.evidence_event_dtos import EvidenceEvent, EvidenceOutcome
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.live_research_gap_dtos import LiveResearchGapObservation
from app_module.live_research_gap_repository import LiveResearchGapRepository
from app_module.signal_decay_service import SignalDecayService
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "signal_decay.db"
    config.use_sqlite = True
    return config


def _event(index: int, *, event_type: str = "recommendation_included") -> EvidenceEvent:
    decision_date = (date(2026, 5, 1) + timedelta(days=index)).isoformat()
    return EvidenceEvent(
        event_id=f"evt-{index:03d}",
        event_hash=f"hash-evt-{index:03d}",
        event_date=decision_date,
        decision_date=decision_date,
        symbol=f"23{index:02d}",
        event_type=event_type,
        event_family="recommendation",
        source_type="recommendation",
        strategy_version_id="strategy-v1",
        profile_id="balanced",
        regime="trend",
        sector="semiconductor",
        liquidity_state="normal",
        data_quality="observed",
        as_of_date="2026-06-01",
        available_date="2026-06-01",
        source_version="test",
    )


def _outcome(event_id: str, *, benchmark_excess_bp: int | None, mae_bp: int) -> EvidenceOutcome:
    return EvidenceOutcome(
        outcome_id=f"out-{event_id}",
        event_id=event_id,
        window_days=20,
        forward_return_bp=benchmark_excess_bp,
        benchmark_excess_bp=benchmark_excess_bp,
        industry_excess_bp=benchmark_excess_bp,
        max_adverse_excursion_bp=mae_bp,
        max_favorable_excursion_bp=300,
        outcome_status="ready",
        data_quality="observed",
    )


def _gap(index: int, *, gap_vs_forward_bp: int | None, gap_vs_benchmark_bp: int | None) -> LiveResearchGapObservation:
    observation_date = (date(2026, 5, 1) + timedelta(days=index)).isoformat()
    return LiveResearchGapObservation(
        gap_id=f"gap-{index:03d}",
        gap_hash=f"sha256:gap-{index:03d}",
        observation_date=observation_date,
        position_id=f"pos-{index:03d}",
        symbol=f"23{index:02d}",
        portfolio_mode="simulated",
        source_type="recommendation",
        source_id="source",
        research_run_id="run-1",
        strategy_version_id="strategy-v1",
        recommendation_result_id="",
        evidence_event_id=f"evt-{index:03d}",
        evidence_outcome_id=f"out-evt-{index:03d}",
        entry_date="2026-06-01",
        entry_price="100",
        current_price_date="2026-06-30",
        current_price="99",
        holding_days=20,
        portfolio_return_bp=-100,
        forward_evidence_return_bp=gap_vs_forward_bp,
        benchmark_excess_bp=gap_vs_benchmark_bp,
        gap_vs_forward_evidence_bp=gap_vs_forward_bp,
        gap_vs_benchmark_bp=gap_vs_benchmark_bp,
        data_quality="observed",
        metadata_json={"event_type": "recommendation_included"},
    )


def _seed_scope(
    config: TWStockConfig,
    *,
    long_count: int,
    short_count: int,
    long_excess_bp: int | None,
    short_excess_bp: int | None,
    long_gap_bp: int | None = None,
    short_gap_bp: int | None = None,
) -> None:
    event_repo = EvidenceEventRepository(config)
    gap_repo = LiveResearchGapRepository(config)
    for index in range(long_count):
        event = _event(index)
        event_repo.insert_event(event)
        value = short_excess_bp if index >= long_count - short_count else long_excess_bp
        event_repo.upsert_outcome(_outcome(event.event_id, benchmark_excess_bp=value, mae_bp=-900 if value and value < 0 else -150))
        gap_value = short_gap_bp if index >= long_count - short_count else long_gap_bp
        if gap_value is not None:
            gap_repo.save_observation(_gap(index, gap_vs_forward_bp=gap_value, gap_vs_benchmark_bp=gap_value))


def test_insufficient_sample_never_suggests_lifecycle_change(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_scope(config, long_count=8, short_count=4, long_excess_bp=200, short_excess_bp=-500)

    observation = SignalDecayService(config).evaluate_signal_scope(
        observation_date="2026-07-09",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        min_sample_size=10,
    )

    assert observation.decay_status == "insufficient_sample"
    assert observation.suggested_lifecycle_action == "none"
    assert observation.confidence == "low"


def test_short_window_worsening_can_mark_decay_candidate(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_scope(
        config,
        long_count=40,
        short_count=12,
        long_excess_bp=300,
        short_excess_bp=-700,
        long_gap_bp=100,
        short_gap_bp=-800,
    )

    observation = SignalDecayService(config).evaluate_signal_scope(
        observation_date="2026-07-09",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        short_window_events=12,
        long_window_events=40,
        min_sample_size=10,
    )

    assert observation.decay_status in {"decaying", "severe_decay"}
    assert observation.suggested_lifecycle_action in {"demote_candidate", "retire_candidate"}
    assert observation.decay_score_bp >= 5000
    assert observation.forward_excess_short_bp < observation.forward_excess_long_bp


def test_missing_benchmark_or_live_gap_lowers_confidence_and_blocks_retire(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_scope(config, long_count=40, short_count=12, long_excess_bp=None, short_excess_bp=None)

    observation = SignalDecayService(config).evaluate_signal_scope(
        observation_date="2026-07-09",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        short_window_events=12,
        long_window_events=40,
        min_sample_size=10,
    )

    codes = {item["code"] for item in observation.diagnostics_json}
    assert observation.confidence == "low"
    assert observation.suggested_lifecycle_action != "retire_candidate"
    assert "missing_benchmark_evidence" in codes
    assert "missing_live_gap_evidence" in codes


def test_stable_scope_suggests_hold(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_scope(
        config,
        long_count=40,
        short_count=12,
        long_excess_bp=250,
        short_excess_bp=260,
        long_gap_bp=50,
        short_gap_bp=60,
    )

    observation = SignalDecayService(config).evaluate_signal_scope(
        observation_date="2026-07-09",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        short_window_events=12,
        long_window_events=40,
        min_sample_size=10,
    )

    assert observation.decay_status == "stable"
    assert observation.suggested_lifecycle_action == "hold"


def test_severe_conditions_can_mark_retire_candidate(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_scope(
        config,
        long_count=40,
        short_count=12,
        long_excess_bp=-100,
        short_excess_bp=-900,
        long_gap_bp=-100,
        short_gap_bp=-800,
    )

    observation = SignalDecayService(config).evaluate_signal_scope(
        observation_date="2026-07-09",
        signal_scope_type="event_type",
        signal_scope_id="recommendation_included",
        short_window_events=12,
        long_window_events=40,
        min_sample_size=10,
    )

    assert observation.decay_status == "severe_decay"
    assert observation.suggested_lifecycle_action == "retire_candidate"
