from typing import Any

import pandas as pd

from app_module.promotion_reconciliation_service import PromotionReconciliationService
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_service import ResearchRunService
from app_module.strategy_lifecycle_repository import (
    LifecycleEvidenceGovernanceService,
    LifecycleEvidenceRepository,
    LifecycleEvidenceStatus,
)
from app_module.strategy_version_service import StrategyVersionService
from data_module.config import TWStockConfig


def _config(tmp_path):
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")


def _metadata(run_id: str = "registry-run-001", **overrides: Any) -> ResearchRunMetadataDTO:
    values: dict[str, Any] = {
        "run_id": run_id,
        "run_name": run_id,
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
            "total_return": "0.08",
            "sharpe_ratio": "1.20",
            "max_drawdown": "0.03",
            "win_rate": "0.60",
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
        "created_at": "2026-06-17T12:00:00",
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


def test_lifecycle_evidence_repository_appends_and_round_trips_decision(tmp_path):
    config = _config(tmp_path)
    research_service = ResearchRunService(config)
    saved = research_service.save_run(_metadata(), _equity(), _trades())
    repository = LifecycleEvidenceRepository(config)

    first = repository.record_decision(
        run=saved,
        version_id="version-001",
        status=LifecycleEvidenceStatus.APPLIED,
        reason="promotion gate accepted",
    )
    second = repository.record_decision(
        run=saved,
        version_id="version-001",
        status=LifecycleEvidenceStatus.SUPERSEDED,
        reason="manual review kept history",
    )

    rows = repository.list_evidence_for_run(saved.run_id)

    assert [row.evidence_id for row in rows] == [first.evidence_id, second.evidence_id]
    assert rows[0].action == "promote"
    assert rows[0].status == LifecycleEvidenceStatus.APPLIED
    assert rows[0].decision_snapshot["run_id"] == saved.run_id
    assert rows[0].decision_snapshot["action"] == "promote"
    assert rows[0].decision_snapshot["gates"][0]["gate_name"] == "total_trades"
    assert rows[0].created_at <= rows[1].created_at


def test_lifecycle_evidence_repository_projects_latest_state_from_history(tmp_path):
    config = _config(tmp_path)
    research_service = ResearchRunService(config)
    saved = research_service.save_run(_metadata(), _equity(), _trades())
    repository = LifecycleEvidenceRepository(config)
    repository.record_decision(
        run=saved,
        version_id="version-001",
        status=LifecycleEvidenceStatus.PROPOSED,
        reason="initial proposal",
    )
    applied = repository.record_decision(
        run=saved,
        version_id="version-001",
        status=LifecycleEvidenceStatus.APPLIED,
        reason="human accepted",
    )

    state = repository.get_current_state(saved.run_id)

    assert state is not None
    assert state.run_id == saved.run_id
    assert state.strategy_id == "baseline_score"
    assert state.version_id == "version-001"
    assert state.action == "promote"
    assert state.status == LifecycleEvidenceStatus.APPLIED
    assert state.latest_evidence_id == applied.evidence_id


def test_promotion_records_lifecycle_evidence_after_registry_sync(tmp_path):
    config = _config(tmp_path)
    research_service = ResearchRunService(config)
    version_service = StrategyVersionService(config)
    evidence_repository = LifecycleEvidenceRepository(config)
    reconciliation = PromotionReconciliationService(
        research_repository=research_service.repository,
        strategy_version_service=version_service,
        lifecycle_evidence_repository=evidence_repository,
    )
    saved = research_service.save_run(_metadata(), _equity(), _trades())

    version_id = reconciliation.promote_registry_run(saved.run_id, notes="registry gate")

    evidence = evidence_repository.list_evidence_for_run(saved.run_id)
    assert len(evidence) == 1
    assert evidence[0].version_id == version_id
    assert evidence[0].status == LifecycleEvidenceStatus.APPLIED
    assert evidence[0].action == "promote"
    assert evidence[0].decision_snapshot["reasons"] == [
        "所有 lifecycle gates 通過，可進入 promote 候選"
    ]


def test_governance_service_records_demote_and_retire_proposals_without_mutating_runs(tmp_path):
    config = _config(tmp_path)
    research_service = ResearchRunService(config)
    evidence_repository = LifecycleEvidenceRepository(config)
    demote = research_service.save_run(
        _metadata(
            "demote-run",
            metrics={
                "total_return": "0.03",
                "sharpe_ratio": "0.70",
                "max_drawdown": "0.42",
                "win_rate": "0.52",
                "total_trades": 30,
            },
        ),
        _equity(),
        _trades(),
    )
    retire = research_service.save_run(
        _metadata(
            "retire-run",
            metrics={
                "total_return": "-0.12",
                "sharpe_ratio": "-0.20",
                "max_drawdown": "0.62",
                "win_rate": "0.35",
                "total_trades": 30,
            },
        ),
        _equity(),
        _trades(),
    )
    governance = LifecycleEvidenceGovernanceService(
        research_repository=research_service.repository,
        evidence_repository=evidence_repository,
    )

    records = governance.record_review_evidence()

    assert [record.run_id for record in records] == ["retire-run", "demote-run"]
    assert [record.action for record in records] == ["retire", "demote"]
    assert all(record.status == LifecycleEvidenceStatus.PROPOSED for record in records)
    assert research_service.repository.get_metadata(demote.run_id).is_archived is False
    assert research_service.repository.get_metadata(retire.run_id).is_archived is False
