from __future__ import annotations

from pathlib import Path

from app_module.evidence_operations_history_repository import EvidenceOperationsHistoryRepository
from app_module.evidence_operations_service import EvidenceOperationsService
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence-ops-history.db"
    config.use_sqlite = True
    return config


def _readiness(*args, **kwargs) -> dict[str, object]:
    return {
        "readiness": "ready_for_manual_confirm",
        "blocking_gaps": [],
        "warnings": [],
        "required_manual_checks": ["manual evidence review"],
        "production_scheduler_allowed": False,
        "latest_smoke_status": "passed",
        "working_copy_confirm_passed": True,
    }


def test_history_repository_saves_weekly_review_snapshot_idempotently(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = EvidenceOperationsService(config, readiness_evaluator=_readiness)
    report = service.build_weekly_review(start_date="2026-07-06", end_date="2026-07-12")
    repo = EvidenceOperationsHistoryRepository(config)

    first = repo.save_weekly_review(report, generated_by="codex")
    second = repo.save_weekly_review(report, generated_by="codex")

    assert first.review_hash == second.review_hash
    assert first.review_id == second.review_id
    assert first.production_scheduler_allowed is False
    assert first.payload_json["status"] == "coverage_only"
    assert first.generated_by == "codex"
    rows = repo.list_weekly_reviews()
    assert [row.review_id for row in rows] == [first.review_id]


def test_history_repository_lists_latest_period_first(tmp_path: Path) -> None:
    config = _config(tmp_path)
    service = EvidenceOperationsService(config, readiness_evaluator=_readiness)
    repo = EvidenceOperationsHistoryRepository(config)

    older = service.build_weekly_review(start_date="2026-06-29", end_date="2026-07-05")
    newer = service.build_weekly_review(start_date="2026-07-06", end_date="2026-07-12")
    repo.save_weekly_review(older, generated_by="codex")
    repo.save_weekly_review(newer, generated_by="codex")

    rows = repo.list_weekly_reviews(limit=10)

    assert [row.period_end for row in rows] == ["2026-07-12", "2026-07-05"]
