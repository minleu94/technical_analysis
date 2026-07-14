from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from app_module.evidence_rehearsal_dtos import EvidenceRehearsalScenario
from app_module.evidence_rehearsal_orchestrator import (
    EvidenceRehearsalExecutionRequest,
    EvidenceRehearsalMLInputs,
    EvidenceRehearsalOrchestrator,
)
from data_module.config import TWStockConfig
from tests.test_evidence_pipeline_smoke import _seed_market_db


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(
        data_root=tmp_path / "data",
        output_root=tmp_path / "output",
    )
    config.db_file = config.data_root / "sqlite" / "twstock.db"
    config.db_file.parent.mkdir(parents=True, exist_ok=True)
    _seed_market_db(config, days=3)
    return config


def _request(tmp_path: Path) -> EvidenceRehearsalExecutionRequest:
    config = _config(tmp_path)
    working_copy = tmp_path / "working" / "rehearsal.sqlite3"
    return EvidenceRehearsalExecutionRequest(
        scenario=EvidenceRehearsalScenario(
            scenario_id="orchestration-v1",
            decision_date="2026-07-01",
            source_db_path=str(config.db_file),
            working_copy_db_path=str(working_copy),
            tier="engineering_fixture",
        ),
        config=config,
        source_db_path=config.db_file,
        working_copy_db_path=working_copy,
        start_date="2026-07-01",
        end_date="2026-07-01",
    )


def test_orchestrator_calls_real_replay_p0_service_and_lineage(tmp_path: Path) -> None:
    request = _request(tmp_path)
    source_before = request.source_db_path.read_bytes()
    source_mtime_before = request.source_db_path.stat().st_mtime_ns

    report = EvidenceRehearsalOrchestrator().run(request)
    adapter_statuses = dict(report.adapter_statuses)

    assert report.source_db_opened is True
    assert report.source_db_write_performed is False
    assert report.working_copy_created is True
    assert report.working_copy_write_performed is True
    assert report.service_call_facts["historical_replay"] is True
    assert report.service_call_facts["p0_comparison"] is True
    assert report.service_call_facts["evidence_rehearsal_service_run"] is True
    assert report.service_call_facts["lineage_verifier"] is True
    assert report.service_call_facts["ml_comparison"] is False
    assert len(report.p0_source_shadow["items"]) == 13
    assert report.artifact_dag
    assert report.artifact_hashes
    assert adapter_statuses["source"] == "invoked"
    assert adapter_statuses["replay"] == "invoked"
    assert adapter_statuses["advice"] == "not_invoked_missing_input"
    assert any(
        blocker == "missing_required_adapter_output:advice"
        for blocker in report.blockers
    )
    assert report.status == "degraded"
    assert report.formal_product_closeout is False
    assert report.production_actions_allowed is False
    assert request.working_copy_db_path.is_file()
    assert request.source_db_path.read_bytes() == source_before
    assert request.source_db_path.stat().st_mtime_ns == source_mtime_before
    serialized = report.to_dict()
    assert serialized["formal_product_closeout"] is False
    assert serialized["production_actions_allowed"] is False


@dataclass(frozen=True)
class _Manifest:
    dataset_id: str = "dataset-v1"
    created_at: str = "2026-07-01"
    row_count: int = 0
    frozen: bool = True
    shadow_only: bool = True
    production_eligible: bool = False


@dataclass(frozen=True)
class _Boundary:
    accepted_rows: tuple[object, ...] = ()
    rejected_row_ids: tuple[str, ...] = ()
    diagnostics_by_row: tuple[tuple[str, tuple[str, ...]], ...] = ()


class _MLProvider:
    def __init__(self) -> None:
        self.calls = 0

    def load(self) -> EvidenceRehearsalMLInputs:
        self.calls += 1
        return EvidenceRehearsalMLInputs(
            manifest=_Manifest(),
            boundary_report=_Boundary(),
            predictions=(),
        )


def test_optional_ml_provider_is_validated_by_comparison_service(tmp_path: Path) -> None:
    provider = _MLProvider()
    request = _request(tmp_path)
    request = replace(request, ml_provider=provider)

    report = EvidenceRehearsalOrchestrator().run(request)

    assert provider.calls == 1
    assert report.service_call_facts["ml_comparison"] is True
    assert report.ml_shadow is not None
    assert report.ml_shadow.status == "insufficient_sample"
    assert "ml_shadow:insufficient_sample" in report.blockers


def test_orchestration_request_rejects_working_copy_inside_data_root(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    unsafe = request.config.data_root / "working" / "rehearsal.sqlite3"
    scenario = replace(request.scenario, working_copy_db_path=str(unsafe))

    with pytest.raises(ValueError, match="working copy must be outside DATA_ROOT"):
        replace(
            request,
            scenario=scenario,
            working_copy_db_path=unsafe,
        )


def test_orchestration_request_requires_end_date_to_match_decision_date(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    with pytest.raises(ValueError, match="scenario_replay_decision_date_mismatch"):
        replace(request, end_date="2026-07-02")
