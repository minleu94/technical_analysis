from __future__ import annotations

from app_module.live_research_gap_dtos import LiveResearchGapObservation
from app_module.live_research_gap_repository import LiveResearchGapRepository
from data_module.config import TWStockConfig


def _config(tmp_path):
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "gap.db"
    config.use_sqlite = True
    return config


def _observation(**overrides) -> LiveResearchGapObservation:
    base = {
        "gap_id": "gap-1",
        "gap_hash": "sha256:gap-1",
        "observation_date": "2026-07-08",
        "position_id": "default:2330",
        "symbol": "2330",
        "portfolio_mode": "simulated",
        "source_type": "research_run",
        "source_id": "run-001",
        "research_run_id": "run-001",
        "strategy_version_id": "strategy-v1",
        "recommendation_result_id": "",
        "evidence_event_id": "evt-001",
        "evidence_outcome_id": "out-001",
        "entry_date": "2026-07-01",
        "entry_price": "100.00",
        "current_price_date": "2026-07-08",
        "current_price": "103.00",
        "holding_days": 5,
        "portfolio_return_bp": 300,
        "research_expected_return_bp": 500,
        "forward_evidence_return_bp": 400,
        "benchmark_excess_bp": 100,
        "industry_excess_bp": 50,
        "gap_vs_research_bp": -200,
        "gap_vs_forward_evidence_bp": -100,
        "gap_vs_benchmark_bp": 200,
        "condition_status": "valid",
        "chip_risk_level": "neutral",
        "regime_at_entry": "bull",
        "regime_current": "bull",
        "data_quality": "observed",
        "warnings_json": [],
        "attribution_json": [{"category": "signal_gap", "confidence": "low"}],
        "metadata_json": {"match_confidence": "high"},
    }
    base.update(overrides)
    return LiveResearchGapObservation(**base)


def test_repository_idempotent_save_and_list(tmp_path):
    repo = LiveResearchGapRepository(_config(tmp_path))
    saved = repo.save_observation(_observation())
    duplicate = repo.save_observation(_observation(gap_id="gap-other"))

    assert duplicate.gap_id == saved.gap_id
    rows = repo.list_observations(symbol="2330")
    assert [row.gap_id for row in rows] == ["gap-1"]
    assert rows[0].attribution_json[0]["category"] == "signal_gap"


def test_repository_summary_groups_by_source_type(tmp_path):
    repo = LiveResearchGapRepository(_config(tmp_path))
    repo.save_observation(_observation(gap_hash="sha256:a", gap_id="gap-a", source_type="research_run"))
    repo.save_observation(
        _observation(
            gap_hash="sha256:b",
            gap_id="gap-b",
            source_type="manual",
            data_quality="degraded",
            warnings_json=["source_trace_missing"],
            portfolio_return_bp=-100,
            gap_vs_research_bp=None,
            gap_vs_forward_evidence_bp=None,
            gap_vs_benchmark_bp=None,
        )
    )

    summary = repo.summarize_live_research_gaps(group_by="source_type", min_sample_size=1)

    by_key = {item.group_key: item for item in summary}
    assert by_key["research_run"].sample_size == 1
    assert by_key["research_run"].mean_gap_vs_forward_evidence_bp == -100
    assert by_key["manual"].summary_status == "DEGRADED"
