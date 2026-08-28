from __future__ import annotations

from pathlib import Path

from app_module.evidence_operations_history_dashboard_dtos import EvidenceOperationsHistoryDashboardRequest
from app_module.evidence_operations_history_dashboard_service import (
    EvidenceOperationsHistoryDashboardService,
    create_evidence_operations_history_dashboard_service,
)
from app_module.evidence_operations_history_repository import EvidenceOperationsHistoryRepository
from app_module.evidence_operations_service import EvidenceOperationsService
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "evidence-ops-history-dashboard.db"
    config.use_sqlite = True
    return config


def _readiness(*args, **kwargs) -> dict[str, object]:
    return {
        "readiness": "ready_for_manual_confirm",
        "blocking_gaps": ["manual_smoke_missing"],
        "warnings": ["sample_pending"],
        "required_manual_checks": ["manual evidence review"],
        "production_scheduler_allowed": False,
        "latest_smoke_status": "pending",
        "working_copy_confirm_passed": False,
    }


def test_history_dashboard_loads_saved_reviews_without_enabling_scheduler(tmp_path: Path) -> None:
    config = _config(tmp_path)
    weekly = EvidenceOperationsService(config, readiness_evaluator=_readiness).build_weekly_review(
        start_date="2026-07-06",
        end_date="2026-07-12",
    )
    EvidenceOperationsHistoryRepository(config).save_weekly_review(weekly, generated_by="test")

    result = EvidenceOperationsHistoryDashboardService(EvidenceOperationsHistoryRepository(config)).load_dashboard(
        EvidenceOperationsHistoryDashboardRequest(start_date="2026-07-01", end_date="2026-07-31")
    )

    assert result.cards.reviews_count == 1
    assert result.cards.production_scheduler_allowed_count == 0
    assert result.rows[0].period_end == "2026-07-12"
    assert result.rows[0].production_scheduler_allowed is False
    assert "不會啟用 production scheduler" in " ".join(result.limitations)


def test_history_dashboard_empty_state_is_explicit(tmp_path: Path) -> None:
    config = _config(tmp_path)

    result = EvidenceOperationsHistoryDashboardService(EvidenceOperationsHistoryRepository(config)).load_dashboard(
        EvidenceOperationsHistoryDashboardRequest()
    )

    assert result.rows == ()
    assert "尚無 weekly review history" in result.empty_state_message


def test_history_dashboard_factory_is_query_only_when_db_is_missing(tmp_path: Path) -> None:
    config = _config(tmp_path)
    missing_db = tmp_path / "missing" / "evidence-ops-history.db"
    config.db_file = missing_db

    service = create_evidence_operations_history_dashboard_service(config)
    result = service.load_dashboard(EvidenceOperationsHistoryDashboardRequest())

    assert result.rows == ()
    assert "目前只讀資料源不可用" in result.empty_state_message
    assert "evidence_operations_history_db_missing" in result.empty_state_message
    assert not missing_db.exists()
    assert not missing_db.parent.exists()
