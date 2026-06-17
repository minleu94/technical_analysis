from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app_module.promotion_service import PromotionService
from app_module.promotion_reconciliation_service import (
    PromotionPreflightError,
    PromotionReconciliationService,
)
from app_module.recommendation_portfolio_promotion_service import (
    RecommendationPortfolioPromotionService,
)
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_repository import ResearchRunRepository
from app_module.research_run_service import ResearchRunService
from app_module.strategy_version_service import StrategyVersionService
from data_module.config import TWStockConfig


def _config(tmp_path):
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")


def _metadata(run_id: str = "registry-run-001", **overrides) -> ResearchRunMetadataDTO:
    values: dict[str, Any] = {
        "run_id": run_id,
        "run_name": "Registry Run",
        "run_type": "single_backtest",
        "strategy_id": "baseline_score",
        "strategy_version": "1.0.0",
        "parameter_contract_version": "v1",
        "normalized_params": {"buy_score": 70, "sell_score": 40},
        "universe": ["2330"],
        "start_date": "2026-01-02",
        "end_date": "2026-01-09",
        "data_fingerprint": "sha256:data",
        "capital_cents": 1_000_000_00,
        "fee_bp_x100": 1425,
        "slippage_bp_x100": 500,
        "execution_price": "next_open",
        "sizing_mode": "fixed_amount",
        "metrics": {
            "total_return": 0.08,
            "sharpe_ratio": 1.2,
            "max_drawdown": 0.03,
            "win_rate": 0.6,
            "total_trades": 24,
        },
        "regime_breakdown": {"trend": {"trades": 24}},
        "benchmark_results": {"taiex": {"excess_return_bp": 300}},
        "data_manifest": {
            "factor_snapshot": {
                "records": [
                    {"factor_name": "technical.total_score", "quality": "observed"},
                    {"factor_name": "broker.net_buy", "quality": "observed"},
                ]
            }
        },
        "payload_hash": f"sha256:{run_id}",
        "created_at": "2026-06-14T12:00:00",
    }
    values.update(overrides)
    return ResearchRunMetadataDTO(**values)


def _equity():
    return pd.DataFrame(
        {"日期": ["2026-01-02", "2026-01-09"], "portfolio_value": [1000, 1080]}
    )


def _trades():
    return pd.DataFrame(
        {"date": ["2026-01-09"], "stock_code": ["2330"], "return_pct": [0.08]}
    )


def _service(tmp_path):
    config = _config(tmp_path)
    research_service = ResearchRunService(config)
    version_service = StrategyVersionService(config)
    reconciliation = PromotionReconciliationService(
        research_repository=research_service.repository,
        strategy_version_service=version_service,
    )
    return research_service, version_service, reconciliation


def test_promote_registry_run_creates_json_and_marks_registry(tmp_path):
    research_service, version_service, reconciliation = _service(tmp_path)
    saved = research_service.save_run(_metadata(), _equity(), _trades())

    version_id = reconciliation.promote_registry_run(saved.run_id, notes="通過 registry gate")

    version = version_service.get_version(version_id)
    assert version is not None
    assert version.source_run_id == saved.run_id
    assert version.strategy_id == "baseline_score"
    assert version.params["buy_score"] == 70
    assert version.backtest_summary["total_return"] == 0.08

    promoted = research_service.repository.get_metadata(saved.run_id)
    assert promoted.promoted_version_id == version_id
    assert promoted.promotion_reconciliation_status == "synced"


@pytest.mark.parametrize(
    "metadata",
    [
        _metadata(parameter_contract_version=""),
        _metadata(metrics={"total_return": -0.01, "total_trades": 24}),
        _metadata(metrics={"total_return": 0.08, "total_trades": 0}),
    ],
)
def test_promote_registry_run_rejects_failed_preflight(tmp_path, metadata):
    research_service, _version_service, reconciliation = _service(tmp_path)
    saved = research_service.save_run(metadata, _equity(), _trades())

    with pytest.raises(PromotionPreflightError):
        reconciliation.promote_registry_run(saved.run_id)


def test_promote_registry_run_rejects_month6_lifecycle_gate_failures(tmp_path):
    research_service, _version_service, reconciliation = _service(tmp_path)
    saved = research_service.save_run(
        _metadata(
            "too-few-trades",
            metrics={
                "total_return": 0.08,
                "sharpe_ratio": 1.2,
                "max_drawdown": 0.03,
                "win_rate": 0.6,
                "total_trades": 3,
            },
        ),
        _equity(),
        _trades(),
    )

    with pytest.raises(PromotionPreflightError, match="Month 6 lifecycle promote gate"):
        reconciliation.promote_registry_run(saved.run_id)


def test_promote_registry_run_rejects_archived_or_already_promoted(tmp_path):
    research_service, _version_service, reconciliation = _service(tmp_path)
    archived = research_service.save_run(_metadata("archived"), _equity(), _trades())
    research_service.archive_run(archived.run_id)
    promoted = research_service.save_run(_metadata("promoted"), _equity(), _trades())
    research_service.repository.mark_promoted(promoted.run_id, "existing-version")

    with pytest.raises(PromotionPreflightError):
        reconciliation.promote_registry_run(archived.run_id)
    with pytest.raises(PromotionPreflightError):
        reconciliation.promote_registry_run(promoted.run_id)


def test_promote_registry_run_deletes_strategy_json_when_registry_update_fails(tmp_path, monkeypatch):
    research_service, version_service, reconciliation = _service(tmp_path)
    saved = research_service.save_run(_metadata(), _equity(), _trades())

    def fail_mark_promoted(run_id: str, version_id: str):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(research_service.repository, "mark_promoted", fail_mark_promoted)

    with pytest.raises(RuntimeError, match="registry unavailable"):
        reconciliation.promote_registry_run(saved.run_id)

    assert version_service.list_versions() == []
    raw = research_service.repository.get_raw_metadata_row(saved.run_id)
    assert raw["promoted_version_id"] is None


def test_reconciliation_reports_json_registry_mismatches(tmp_path):
    research_service, version_service, reconciliation = _service(tmp_path)
    saved = research_service.save_run(_metadata(), _equity(), _trades())
    version_id = version_service.create_version(
        strategy_id="baseline_score",
        params=saved.normalized_params,
        source_run_id=saved.run_id,
    )
    other = research_service.save_run(
        _metadata("registry-points-to-missing"), _equity(), _trades()
    )
    research_service.repository.mark_promoted(other.run_id, "missing-version")

    issues = reconciliation.scan_reconciliation_issues()

    assert {
        issue.issue_type
        for issue in issues
    } == {"json_missing_registry_backfill", "registry_missing_json"}
    assert any(issue.run_id == saved.run_id and issue.version_id == version_id for issue in issues)
    assert any(issue.run_id == other.run_id and issue.version_id == "missing-version" for issue in issues)


def test_single_backtest_promotion_service_delegates_to_registry_reconciliation(tmp_path):
    config = _config(tmp_path)
    reconciliation = MagicMock()
    reconciliation.promote_registry_run.return_value = "version-from-registry"
    legacy_repository = MagicMock()
    service = PromotionService(
        config=config,
        backtest_repository=legacy_repository,
        backtest_service=MagicMock(),
        strategy_version_service=StrategyVersionService(config),
        preset_service=MagicMock(),
        promotion_reconciliation_service=reconciliation,
    )

    version_id = service.promote_to_strategy_version(
        "registry-run-001",
        profile_id="balanced",
        notes="registry path",
    )

    assert version_id == "version-from-registry"
    reconciliation.promote_registry_run.assert_called_once_with(
        "registry-run-001",
        profile_id="balanced",
        notes="registry path",
    )
    legacy_repository.get_run.assert_not_called()


def test_recommendation_portfolio_promotion_service_delegates_to_registry_reconciliation():
    reconciliation = MagicMock()
    reconciliation.promote_registry_run.return_value = "portfolio-version-from-registry"
    legacy_repository = MagicMock()
    service = RecommendationPortfolioPromotionService(
        run_repository=legacy_repository,
        strategy_version_service=MagicMock(),
        promotion_reconciliation_service=reconciliation,
    )

    version_id = service.promote_to_strategy_version("registry-portfolio-run", notes="registry")

    assert version_id == "portfolio-version-from-registry"
    reconciliation.promote_registry_run.assert_called_once_with(
        "registry-portfolio-run",
        notes="registry",
    )
    legacy_repository.load_run.assert_not_called()
