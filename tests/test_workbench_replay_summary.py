import json
from pathlib import Path

import pytest

from app_module.workbench_replay_summary import load_historical_replay_summary


def test_load_historical_replay_summary_marks_simulated_and_degraded(tmp_path: Path) -> None:
    path = tmp_path / "replay.json"
    path.write_text(
        json.dumps(
            {
                "replay_mode": "historical_replay",
                "source_label": "simulated_scheduler",
                "start_date": "2026-01-06",
                "end_date": "2026-07-06",
                "totals": {
                    "days": 118,
                    "events_seen": 118056,
                    "outcomes_created": 472224,
                },
                "final_outcome_summary": {
                    "pending_insufficient_future_data": 91488,
                    "missing_benchmark": 0,
                    "missing_industry_benchmark": 378491,
                },
            }
        ),
        encoding="utf-8",
    )

    summary = load_historical_replay_summary(path)

    assert summary["replay_mode"] == "historical_replay"
    assert summary["source_label"] == "simulated_scheduler"
    assert summary["does_not_satisfy_phase0_gate"] is True
    assert summary["production_scheduler_allowed"] is False
    assert "missing_industry_benchmark" in summary["warnings"]
    assert "simulated_scheduler" in summary["warnings"]
    assert "not_production_readiness" in summary["warnings"]


def test_load_historical_replay_summary_builds_quality_disclosures(tmp_path: Path) -> None:
    path = tmp_path / "replay.json"
    path.write_text(
        json.dumps(
            {
                "replay_mode": "historical_replay",
                "source_label": "simulated_scheduler",
                "totals": {
                    "days": 118,
                    "events_seen": 118056,
                    "outcomes_created": 472224,
                },
                "final_outcome_summary": {
                    "ready": 380736,
                    "pending_insufficient_future_data": 91488,
                    "missing_benchmark": 0,
                    "missing_industry_benchmark": 378491,
                },
                "days": [
                    {
                        "date": "2026-01-06",
                        "diagnostics": ["source_missing_screening_matrix"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = load_historical_replay_summary(path)
    disclosures = summary["quality_disclosures"]

    assert "simulated_scheduler" in disclosures
    assert "source_gap:source_missing_screening_matrix" in disclosures
    assert "source_gap_coverage:source_missing_screening_matrix=1/1" in disclosures
    assert "payload_gap:missing_industry_benchmark" in disclosures
    assert "outcome_maturity:ready=380736,pending_future_data=91488" in disclosures
    assert "benchmark_coverage:covered=380736,total=380736,missing=0" in disclosures
    assert "industry_benchmark_coverage:covered=2245,total=380736,missing=378491" in disclosures
    assert "missing_industry_benchmark:378491" in disclosures
    assert "pending_future_data:91488" in disclosures
    assert (
        "replay_direction_assessment:market_benchmark_ready_but_industry_and_source_gaps_block_production_readiness"
        in disclosures
    )
    assert "phase0_gate_not_satisfied:weekly_history_and_multi_day_dry_run_require_real_time_accumulation" in disclosures


def test_load_historical_replay_summary_rejects_replay_db_path(tmp_path: Path) -> None:
    path = tmp_path / "replay.db"
    path.write_bytes(b"not-json")

    with pytest.raises(ValueError, match="JSON summary"):
        load_historical_replay_summary(path)
