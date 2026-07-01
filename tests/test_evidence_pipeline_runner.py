from __future__ import annotations

from pathlib import Path

import pytest

from app_module.dtos import RecommendationDTO, RecommendationResultDTO
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_pipeline_runner import EvidencePipelineRunner
from app_module.evidence_pipeline_runner_dtos import EvidencePipelineRunRequest
from app_module.recommendation_repository import RecommendationRepository
from data_module.config import TWStockConfig
from tests.test_evidence_pipeline_smoke import _seed_market_db


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "data" / "sqlite" / "twstock.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    return config


def _seed_recommendation(config: TWStockConfig, *, result_id: str = "runner-rec") -> str:
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
                score_percentile_bp=9300,
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
        )
    )

    assert summary.events_seen == 0
    assert summary.events_inserted == 0
    assert "source_missing_snapshot" in summary.diagnostic_codes
    assert summary.scheduler_readiness_after in {"not_ready", "dry_run_only", "ready_for_design"}


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
