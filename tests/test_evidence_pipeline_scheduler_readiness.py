from __future__ import annotations

from pathlib import Path

from app_module.evidence_pipeline_runner import EvidencePipelineRunner
from app_module.evidence_pipeline_runner_dtos import (
    EvidencePipelineRunRequest,
    scheduler_readiness_after_run,
)
from tests.test_evidence_pipeline_runner import _config, _seed_recommendation
from tests.test_evidence_pipeline_smoke import _seed_market_db


def test_readiness_enum_never_reports_production_ready() -> None:
    for before in ("not_ready", "dry_run_only", "ready_for_design", "ready_for_manual_confirm"):
        assert scheduler_readiness_after_run(before, dry_run=True, blocking_gaps=(), errors_count=0) != "production_ready"
        assert scheduler_readiness_after_run(before, dry_run=False, blocking_gaps=(), errors_count=0) != "production_ready"


def test_dry_run_success_can_advance_to_manual_confirm_design_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)

    summary = EvidencePipelineRunner(config).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("recommendation",),
            result_id=result_id,
            windows=(5,),
            min_sample_size=1,
        )
    )

    assert summary.scheduler_readiness_before in {"not_ready", "dry_run_only", "ready_for_design"}
    assert summary.scheduler_readiness_after == "ready_for_manual_confirm"
    assert "production_ready" not in summary.to_dict().values()


def test_blocking_gaps_keep_readiness_below_manual_confirm(tmp_path: Path) -> None:
    config = _config(tmp_path)

    summary = EvidencePipelineRunner(config).run(
        EvidencePipelineRunRequest(decision_date="2026-07-01", sources=("watchlist-trigger",), windows=(5,))
    )

    assert summary.blocking_gaps
    assert summary.scheduler_readiness_after in {"not_ready", "dry_run_only", "ready_for_design"}
