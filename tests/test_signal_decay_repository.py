from __future__ import annotations

from pathlib import Path

from app_module.signal_decay_dtos import SignalDecayObservation
from app_module.signal_decay_repository import SignalDecayRepository
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "signal_decay.db"
    config.use_sqlite = True
    return config


def _observation(**overrides) -> SignalDecayObservation:
    base = {
        "decay_id": "decay-1",
        "decay_hash": "sha256:decay-1",
        "observation_date": "2026-07-09",
        "signal_scope_type": "event_type",
        "signal_scope_id": "recommendation_included",
        "strategy_version_id": "",
        "profile_id": "",
        "event_type": "recommendation_included",
        "event_family": "recommendation",
        "factor_name": "",
        "window_short": 30,
        "window_long": 120,
        "sample_size_short": 30,
        "sample_size_long": 120,
        "forward_excess_short_bp": -350,
        "forward_excess_long_bp": 200,
        "win_rate_short_bp": 3000,
        "win_rate_long_bp": 5500,
        "mae_short_bp": -800,
        "mae_long_bp": -300,
        "live_gap_short_bp": -500,
        "live_gap_long_bp": -100,
        "decay_score_bp": 6500,
        "decay_status": "decaying",
        "suggested_lifecycle_action": "demote_candidate",
        "confidence": "medium",
        "evidence_event_count": 120,
        "gap_observation_count": 20,
        "quality": "degraded",
        "warnings_json": ["missing_industry"],
        "diagnostics_json": [{"code": "short_window_weaker"}],
        "metadata_json": {"source": "unit-test"},
    }
    base.update(overrides)
    return SignalDecayObservation(**base)


def test_repository_idempotent_save_and_list(tmp_path: Path) -> None:
    repo = SignalDecayRepository(_config(tmp_path))

    saved = repo.save_observation(_observation())
    duplicate = repo.save_observation(_observation(decay_id="decay-other"))

    assert duplicate.decay_id == saved.decay_id
    rows = repo.list_observations(signal_scope_type="event_type")
    assert [row.decay_id for row in rows] == ["decay-1"]
    assert rows[0].warnings_json == ["missing_industry"]


def test_repository_summarizes_status_and_suggestions(tmp_path: Path) -> None:
    repo = SignalDecayRepository(_config(tmp_path))
    repo.save_observation(_observation())
    repo.save_observation(
        _observation(
            decay_id="decay-2",
            decay_hash="sha256:decay-2",
            signal_scope_id="watchlist_trigger_added",
            event_type="watchlist_trigger_added",
            decay_status="stable",
            suggested_lifecycle_action="hold",
            confidence="high",
            quality="observed",
            warnings_json=[],
        )
    )

    summary = repo.summarize_decay(observation_date="2026-07-09")

    assert summary.observations_count == 2
    assert summary.status_counts["decaying"] == 1
    assert summary.status_counts["stable"] == 1
    assert summary.suggestion_counts["demote_candidate"] == 1
    assert summary.confidence_counts["high"] == 1

