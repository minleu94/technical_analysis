from __future__ import annotations

import json
from pathlib import Path

from app_module.research_console_source_service import ResearchConsoleSourceService


P0_SOURCE_IDS = {
    "corporate_action.ex_dividend_timeline",
    "corporate_action.reduction_split_par_value",
    "microstructure.suspended_halt_resume",
    "microstructure.disposition_stock",
    "microstructure.periodic_call_auction",
    "microstructure.full_delivery",
    "microstructure.limit_lock",
    "institutional_flows",
    "credit_transactions",
    "tdcc_shareholding",
    "twse.monthly_revenue_announcement",
    "tpex.monthly_revenue_announcement",
    "pit.quarterly_financials",
}


def _projection() -> dict[str, object]:
    return {
        "identity": {
            "dataset_id": "terra-development-v0:g-1",
            "generation_id": "g-1",
            "research_run_id": "sha256:run-1",
        },
        "status": {
            "scope": "historical_research_seen_development_data",
            "formal_oos": False,
            "alpha_bp": 0,
            "apply_flags": {
                "apply_promotion": False,
                "apply_retrain": False,
                "apply_scheduler": False,
                "apply_trading": False,
            },
            "promotion_eligible": False,
        },
        "frozen_metrics": {
            "sample_count": 48,
            "coverage_bp": 10000,
            "rule": {"status": "research_baseline", "sample_count": 48},
            "ml": {"status": "development_challenger", "sample_count": 48},
            "downside": {"status": "observed"},
        },
        "blockers": ["research_only_degraded"],
        "lineage": {
            "dataset_id": "terra-development-v0:g-1",
            "generation_id": "g-1",
            "dataset_manifest_hash": "sha256:manifest",
            "dataset_content_hash": "sha256:content",
            "feature_registry_hash": "sha256:features",
            "label_registry_hash": "sha256:labels",
            "rule_configuration_hash": "sha256:rule",
            "input_fit_row_count": 48,
            "input_evaluation_row_count": 0,
            "feature_names": ["rsi_normalized_bp", "adx_normalized_bp"],
            "max_label_available_date": "2025-02-18",
        },
    }


def test_missing_projection_is_fail_closed_without_zero_filling() -> None:
    console = ResearchConsoleSourceService().inspect()

    assert console.overall_status == "missing"
    assert console.boundary.formal_oos_allowed is False
    assert console.boundary.production_blend_alpha_bp == 0
    assert console.boundary.formal_rule_unchanged is True
    assert console.boundary.promotion_allowed is False
    assert console.boundary.retrain_allowed is False
    assert console.boundary.scheduler_allowed is False
    assert console.boundary.trading_allowed is False
    assert {row.gate_id for row in console.gates} == {"EV1", "EV2", "EV3", "EV4", "EV5"}
    assert all(row.status == "missing" for row in console.gates)
    p0_rows = tuple(row for row in console.sources if row.lane == "p0")
    broker_rows = tuple(row for row in console.sources if row.lane == "broker")
    assert {row.source_id for row in p0_rows} == P0_SOURCE_IDS
    assert len(broker_rows) == 1
    assert all(row.status == "missing" and row.observed_rows is None for row in console.sources)
    assert all(row.row_count is None for row in console.pipeline)


def test_projection_provider_is_copied_without_recomputing_domain_metrics() -> None:
    payload = _projection()
    console = ResearchConsoleSourceService(projection_provider=lambda: payload).inspect()

    assert console.overall_status == "degraded"
    assert [row.component_id for row in console.pipeline] == ["dataset", "rule", "ml", "e2e"]
    assert console.pipeline[0].identity == "terra-development-v0:g-1"
    assert console.pipeline[0].row_count == 48
    assert console.pipeline[0].feature_count == 2
    assert console.pipeline[1].status == "research_baseline"
    assert console.pipeline[2].status == "development_challenger"
    assert console.pipeline[3].blockers == ("research_only_degraded",)
    assert console.frozen_metrics == payload["frozen_metrics"]
    assert console.frozen_metrics is not payload["frozen_metrics"]
    assert {item.artifact_id for item in console.artifacts} >= {
        "sha256:manifest",
        "sha256:content",
        "sha256:features",
        "sha256:labels",
    }


def test_explicit_projection_path_is_read_only(tmp_path: Path) -> None:
    projection_path = tmp_path / "ResearchConsoleProjection.json"
    projection_path.write_text(json.dumps(_projection()), encoding="utf-8")
    before = (projection_path.stat().st_size, projection_path.stat().st_mtime_ns, projection_path.read_bytes())

    console = ResearchConsoleSourceService(projection_path=projection_path).inspect()

    after = (projection_path.stat().st_size, projection_path.stat().st_mtime_ns, projection_path.read_bytes())
    assert console.source_reference == str(projection_path.resolve())
    assert before == after


def test_invalid_or_unsafe_projection_fails_closed() -> None:
    unsafe = _projection()
    unsafe["status"] = {
        "formal_oos": True,
        "alpha_bp": 100,
        "apply_flags": {"apply_trading": True},
    }

    console = ResearchConsoleSourceService(projection_provider=lambda: unsafe).inspect()

    assert console.overall_status == "degraded"
    assert "projection_boundary_violation" in console.blockers
    assert console.boundary.formal_oos_allowed is False
    assert console.boundary.production_blend_alpha_bp == 0


def test_missing_apply_flags_fail_closed() -> None:
    for flags in ({}, {"apply_promotion": False}):
        unsafe = _projection()
        unsafe["status"]["apply_flags"] = flags  # type: ignore[index]

        console = ResearchConsoleSourceService(projection_provider=lambda: unsafe).inspect()

        assert console.overall_status == "degraded"
        assert "projection_boundary_violation" in console.blockers


def test_provider_failure_returns_degraded_console_instead_of_escaping() -> None:
    def failed_provider() -> dict[str, object]:
        raise RuntimeError("provider unavailable")

    console = ResearchConsoleSourceService(projection_provider=failed_provider).inspect()

    assert console.overall_status == "degraded"
    assert console.blockers == ("projection_read_failed",)


def test_governance_provider_failure_returns_degraded_console() -> None:
    def failed_governance() -> dict[str, object]:
        raise RuntimeError("governance unavailable")

    console = ResearchConsoleSourceService(
        projection_provider=_projection,
        governance_provider=failed_governance,
    ).inspect()

    assert console.overall_status == "degraded"
    assert console.blockers == ("projection_schema_invalid",)


def test_injected_governance_projection_copies_ev_p0_broker_and_artifact_status() -> None:
    governance = {
        "gates": [
            {
                "gate_id": "EV2",
                "status": "provisional",
                "detail": "Human source decision pending",
                "artifact_citation": "ev2:review-package",
            }
        ],
        "sources": [
            {
                "source_id": "institutional_flows",
                "lane": "p0",
                "status": "candidate",
                "allowed_use": "Development Only",
                "observed_rows": 12,
                "revision": "candidate-r1",
            },
            {
                "source_id": "broker_dataset",
                "lane": "broker",
                "status": "degraded",
                "allowed_use": "Research Only",
                "degraded_reason": "license_pending",
            },
        ],
        "artifacts": [
            {
                "artifact_type": "source_review",
                "artifact_id": "ev2:review-package",
                "status": "provisional",
                "citation": "sanitized-governance-projection",
            }
        ],
    }

    console = ResearchConsoleSourceService(
        projection_provider=_projection,
        governance_provider=lambda: governance,
    ).inspect()

    ev2 = next(row for row in console.gates if row.gate_id == "EV2")
    institutional = next(row for row in console.sources if row.source_id == "institutional_flows")
    broker = next(row for row in console.sources if row.lane == "broker")
    assert ev2.status == "provisional"
    assert institutional.status == "candidate" and institutional.observed_rows == 12
    assert broker.status == "degraded" and broker.degraded_reason == "license_pending"
    assert len(tuple(row for row in console.sources if row.lane == "p0")) == 13
    assert any(row.artifact_id == "ev2:review-package" for row in console.artifacts)
