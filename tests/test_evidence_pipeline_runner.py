from __future__ import annotations

from pathlib import Path

import pytest

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_pipeline_runner import (
    EvidencePipelineRunner,
    _advisory_count,
    _split_warning_and_advisory_counts,
    write_pipeline_report,
)
from app_module.evidence_pipeline_runner_dtos import (
    EvidencePipelineRunRequest,
    EvidencePipelineRunSummary,
    EvidencePipelineStepSummary,
    STEP_READY_WITH_ADVISORIES,
)
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig
from tests.test_evidence_pipeline_smoke import _seed_market_db


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "data" / "sqlite" / "twstock.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_recommendation(
    config: TWStockConfig,
    *,
    result_id: str = "runner-rec",
    score_percentile_bp: int | None = 9300,
    threshold_mode: str = "fixed",
) -> str:
    result = RecommendationResultDTO(
        result_id=result_id,
        result_name="Runner fixture",
        config={"profile_id": "balanced", "profile_version": "1.0"},
        recommendations=[
            RecommendationDTO(
                stock_code="2330",
                stock_name="TSMC",
                close_price=100.0,
                price_change=1.0,
                total_score=88.0,
                indicator_score=30.0,
                pattern_score=28.0,
                volume_score=30.0,
                recommendation_reasons="rank_top",
                industry="半導體",
                regime_match=True,
                score_percentile_bp=score_percentile_bp,
                threshold_mode=threshold_mode,
            )
        ],
        regime="Trend",
        created_at="2026-07-01T09:00:00",
    )
    return RecommendationRepository(config).save_result(result)


def test_runner_defaults_to_dry_run_and_does_not_write_events_or_outcomes(tmp_path: Path) -> None:
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

    repository = EvidenceEventRepository(config)
    assert summary.dry_run is True
    assert summary.confirm is False
    assert summary.events_seen >= 1
    assert summary.events_inserted == 0
    assert summary.outcomes_created == 0
    assert repository.list_events() == []
    assert repository.list_outcomes() == []
    assert [step.step_name for step in summary.steps] == [
        "source_coverage_check",
        "capture_decision_desk_snapshot",
        "capture_evidence_events",
        "calculate_forward_outcomes",
        "summarize_forward_performance",
        "write_diagnostics_report",
    ]


def test_runner_summary_and_report_include_warning_breakdown(tmp_path: Path) -> None:
    config = _config(tmp_path)
    result_id = _seed_recommendation(
        config,
        result_id="runner-warning-rec",
        score_percentile_bp=None,
        threshold_mode="cross_sectional",
    )
    report_path = tmp_path / "evidence_report.md"

    summary = EvidencePipelineRunner(config).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("recommendation",),
            result_id=result_id,
            skip_snapshot=True,
            skip_outcomes=True,
            skip_summary=True,
            report_output=str(report_path),
        )
    )

    assert summary.to_dict().get("warning_counts", {}).get("score_percentile_missing") == 1
    report = report_path.read_text(encoding="utf-8")
    assert "## Warning Breakdown" in report
    assert "- score_percentile_missing: 1" in report


def test_pipeline_report_separates_warning_occurrences_from_unique_warning_tokens(tmp_path: Path) -> None:
    report_path = tmp_path / "warning_summary.md"
    summary = EvidencePipelineRunSummary(
        run_id="warning-summary",
        decision_date="2026-07-01",
        start_date=None,
        end_date=None,
        dry_run=True,
        confirm=False,
        db_path=None,
        started_at="2026-07-01T05:15:00",
        finished_at="2026-07-01T05:15:01",
        overall_status="degraded",
        scheduler_readiness_before="ready_for_design",
        scheduler_readiness_after="ready_for_manual_confirm",
        source_coverage={},
        steps=(EvidencePipelineStepSummary(step_name="capture_evidence_events", status="degraded", dry_run=True),),
        warnings_count=12,
        warning_counts={"risk_prompt_source_quality:portfolio_alerts:estimated": 10, "score_percentile_missing": 2},
        advisories_count=3,
        advisory_counts={"portfolio_alerts_chip_estimated:2330": 1, "portfolio_alerts_chip_estimated:2382": 1},
        quality_coverage_rows=(
            {
                "symbol": "2330",
                "observed_event_count": 92,
                "estimated_event_count": 132,
                "unavailable_event_count": 0,
            },
        ),
    )

    write_pipeline_report(summary, report_path)

    payload = summary.to_dict()
    report = report_path.read_text(encoding="utf-8")
    assert payload["warning_unique_count"] == 2
    assert payload["warning_top_counts"][0] == {
        "warning": "risk_prompt_source_quality:portfolio_alerts:estimated",
        "count": 10,
    }
    assert "## Warning Summary" in report
    assert "- warning_occurrence_count: 12" in report
    assert "- unique_warning_token_count: 2" in report
    assert "- risk_prompt_source_quality:portfolio_alerts:estimated: 10" in report
    assert "## Advisories" in report
    assert "- advisory_occurrence_count: 3" in report
    assert "- portfolio_alerts_chip_estimated:2330: 1" in report
    assert "## Source Quality Coverage" in report
    assert "- 2330: observed=92, estimated=132, unavailable=0" in report


def test_runner_returns_ready_with_advisories_without_missing_or_blocking_data(tmp_path: Path) -> None:
    runner = EvidencePipelineRunner(_config(tmp_path))

    status = runner._overall_status(
        [
            EvidencePipelineStepSummary(
                step_name="capture_decision_desk_snapshot",
                status=STEP_READY_WITH_ADVISORIES,
                dry_run=True,
                advisories_count=1,
                advisory_counts={"portfolio_alerts_chip_estimated:2330": 1},
            )
        ],
        [],
    )

    assert status == STEP_READY_WITH_ADVISORIES


def test_warning_split_normalizes_stored_estimated_advisory_but_preserves_missing_as_warning() -> None:
    warnings, advisories = _split_warning_and_advisory_counts(
        (
            "portfolio_alerts:portfolio_alerts_chip_estimated:2330",
            "risk_prompts:risk_prompt_source_quality:portfolio_alerts:missing",
        )
    )

    assert advisories == {"portfolio_alerts_chip_estimated:2330": 1}
    assert warnings == {"risk_prompts:risk_prompt_source_quality:portfolio_alerts:missing": 1}


def test_advisory_count_uses_deduplicated_advisory_counts() -> None:
    assert _advisory_count({"portfolio_alerts_chip_estimated:2330": 1, "portfolio_alerts_chip_estimated:2382": 1}) == 2


def test_runner_dry_run_without_db_path_uses_scratch_db_not_default_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = EvidencePipelineRunner(config)

    summary = runner.run(EvidencePipelineRunRequest(decision_date="2026-07-01", sources=("recommendation",)))

    assert summary.dry_run is True
    assert runner.db_path == config.output_root / "evidence_pipeline" / "dry_run_scratch" / "evidence_pipeline_dry_run.db"
    assert runner.db_path != config.db_file


def test_runner_confirm_requires_explicit_db_path(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with pytest.raises(ValueError, match="explicit --db-path"):
        EvidencePipelineRunner(config).run(
            EvidencePipelineRunRequest(decision_date="2026-07-01", confirm=True, dry_run=False)
        )


def test_runner_confirm_writes_events_and_outcomes_to_explicit_working_db(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)

    summary = EvidencePipelineRunner(config, db_path=config.db_file).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("recommendation",),
            result_id=result_id,
            windows=(5,),
            min_sample_size=1,
            confirm=True,
            dry_run=False,
            db_path=str(config.db_file),
        )
    )

    repository = EvidenceEventRepository(config)
    assert summary.dry_run is False
    assert summary.events_inserted == 1
    assert summary.outcomes_created == 1
    assert len(repository.list_events()) == 1
    assert len(repository.list_outcomes(window_days=5)) == 1
    assert summary.scheduler_readiness_after == "ready_for_manual_confirm"


def test_runner_repeated_confirm_is_idempotent_for_events(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)
    runner = EvidencePipelineRunner(config, db_path=config.db_file)
    request = EvidencePipelineRunRequest(
        decision_date="2026-07-01",
        sources=("recommendation",),
        result_id=result_id,
        windows=(5,),
        min_sample_size=1,
        confirm=True,
        dry_run=False,
        db_path=str(config.db_file),
    )

    first = runner.run(request)
    second = runner.run(request)

    assert first.events_inserted == 1
    assert second.events_inserted == 0
    assert second.events_skipped_duplicate == 1
    assert len(EvidenceEventRepository(config).list_events()) == 1


def test_runner_production_like_db_confirm_requires_extra_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path)
    runner = EvidencePipelineRunner(config, db_path=config.db_file)
    monkeypatch.setattr(runner, "_looks_like_production_db", lambda _path: True)

    with pytest.raises(ValueError, match="allow-production-db-confirm"):
        runner.run(
            EvidencePipelineRunRequest(
                decision_date="2026-07-01",
                sources=("recommendation",),
                confirm=True,
                dry_run=False,
                db_path=str(config.db_file),
            )
        )


def test_runner_outcome_step_can_report_pending_future_data(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config, days=3)
    result_id = _seed_recommendation(config)

    summary = EvidencePipelineRunner(config, db_path=config.db_file).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("recommendation",),
            result_id=result_id,
            windows=(5,),
            confirm=True,
            dry_run=False,
            db_path=str(config.db_file),
        )
    )

    assert summary.outcomes_pending == 1


def test_runner_summary_step_reports_insufficient_sample(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    result_id = _seed_recommendation(config)

    summary = EvidencePipelineRunner(config, db_path=config.db_file).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("recommendation",),
            result_id=result_id,
            windows=(5,),
            window=5,
            min_sample_size=2,
            confirm=True,
            dry_run=False,
            db_path=str(config.db_file),
        )
    )

    assert summary.summary_groups == 1
    assert summary.groups_insufficient_sample == 1


def test_runner_missing_snapshot_reports_diagnostic_without_fabricated_events(tmp_path: Path) -> None:
    config = _config(tmp_path)

    summary = EvidencePipelineRunner(config).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("watchlist-trigger", "portfolio-alert", "risk-prompt"),
            windows=(5,),
            skip_snapshot=True,
        )
    )

    assert summary.events_seen == 0
    assert summary.events_inserted == 0
    assert "source_missing_snapshot" in summary.diagnostic_codes
    assert summary.scheduler_readiness_after in {"not_ready", "dry_run_only", "ready_for_design"}


def test_runner_dry_run_reuses_transient_snapshot_for_decision_desk_capture(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)

    summary = EvidencePipelineRunner(config, db_path=config.db_file).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("watchlist-trigger", "portfolio-alert", "risk-prompt"),
            db_path=str(config.db_file),
            windows=(5,),
        )
    )

    assert summary.dry_run is True
    assert summary.events_inserted == 0
    assert "decision_desk_snapshot_missing" not in summary.source_coverage["blocking_gaps"]
    assert summary.source_coverage["latest_decision_desk_snapshot_date"] == "2026-07-01"
    assert summary.source_coverage["source_coverage_basis"] == "dry_run_transient_decision_desk_snapshot"
    assert "source_missing_snapshot" not in summary.diagnostic_codes
    assert EvidenceEventRepository(config).list_events() == []


def test_runner_default_all_does_not_block_on_optional_exclusion_payloads(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_market_db(config)
    _seed_recommendation(config)

    summary = EvidencePipelineRunner(config, db_path=config.db_file).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("all",),
            db_path=str(config.db_file),
            windows=(5,),
        )
    )

    assert "why_not_payload_missing" in summary.source_coverage["warnings"]
    assert "liquidity_gate_payload_missing" in summary.source_coverage["warnings"]
    assert "source_missing_exclusion_payload" not in summary.diagnostic_codes
    assert "why_not_exclusion_payload_missing" not in summary.blocking_gaps
    assert "liquidity_gate_payload_missing" not in summary.blocking_gaps


def test_runner_explicit_exclusion_sources_still_block_without_payloads(tmp_path: Path) -> None:
    config = _config(tmp_path)
    _seed_recommendation(config)

    summary = EvidencePipelineRunner(config, db_path=config.db_file).run(
        EvidencePipelineRunRequest(
            decision_date="2026-07-01",
            sources=("why-not", "liquidity-gate"),
            db_path=str(config.db_file),
            windows=(5,),
        )
    )

    assert "why_not_exclusion_payload_missing" in summary.blocking_gaps
    assert "liquidity_gate_payload_missing" in summary.blocking_gaps
    assert "source_missing_exclusion_payload" in summary.diagnostic_codes


def test_runner_and_cli_do_not_import_forbidden_boundaries() -> None:
    for path in (
        Path("app_module/evidence_pipeline_runner.py"),
        Path("scripts/run_evidence_pipeline.py"),
    ):
        text = path.read_text(encoding="utf-8")
        assert "ui_qt" not in text
        assert "ScoringEngine" not in text
        assert "portfolio_module" not in text
        assert "portfolio_position" not in text
