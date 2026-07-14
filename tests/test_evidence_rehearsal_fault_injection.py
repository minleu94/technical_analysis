from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app_module.evidence_rehearsal_fault_injection import (
    EvidenceRehearsalFaultInjector,
)
from app_module.evidence_rehearsal_orchestrator import EvidenceRehearsalOrchestrator
from data_module.p0_shadow_observation import P0ShadowObservation
from tests.test_evidence_rehearsal_orchestrator import _request


def test_source_outage_is_reported_by_real_service_adapter_boundary(
    tmp_path: Path,
) -> None:
    injected = EvidenceRehearsalFaultInjector().inject(
        _request(tmp_path), "source_outage"
    )

    report = EvidenceRehearsalOrchestrator().run(injected)

    assert any(
        blocker.startswith("adapter_failure:source:source_outage")
        for blocker in report.blockers
    )
    assert report.source_db_opened is False
    assert report.working_copy_created is False
    assert report.lineage_status == "incomplete"
    assert report.fault_diagnostics["detector"] == "EvidenceRehearsalService.run"


def test_future_available_date_is_reported_by_p0_comparison(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request = replace(
        request,
        p0_observations=(
            P0ShadowObservation(
                source_id="institutional_flows",
                symbol="2330",
                decision_date=request.scenario.decision_date,
                available_date=request.scenario.decision_date,
                source_version="fixture-v1",
                status="observed",
                diagnostics=(),
                raw_payload={},
            ),
        ),
    )
    injected = EvidenceRehearsalFaultInjector().inject(
        request, "future_available_date"
    )

    report = EvidenceRehearsalOrchestrator().run(injected)

    assert any(
        blocker.endswith(":future_available_date") for blocker in report.blockers
    )
    assert report.fault_diagnostics["mutation"] == "p0_available_date_plus_one_day"
    assert report.fault_diagnostics["detector"] == "P0SourceShadowComparisonService"


def test_independent_faults_are_semantically_deterministic(tmp_path: Path) -> None:
    source_outage_reports = tuple(
        EvidenceRehearsalOrchestrator().run(
            EvidenceRehearsalFaultInjector().inject(
                _request(tmp_path / run_id), "source_outage"
            )
        )
        for run_id in ("source-first", "source-second")
    )
    future_reports = []
    for run_id in ("future-first", "future-second"):
        request = _request(tmp_path / run_id)
        request = replace(
            request,
            p0_observations=(
                P0ShadowObservation(
                    source_id="institutional_flows",
                    symbol="2330",
                    decision_date=request.scenario.decision_date,
                    available_date=request.scenario.decision_date,
                    source_version="fixture-v1",
                    status="observed",
                    diagnostics=(),
                    raw_payload={},
                ),
            ),
        )
        future_reports.append(
            EvidenceRehearsalOrchestrator().run(
                EvidenceRehearsalFaultInjector().inject(
                    request, "future_available_date"
                )
            )
        )

    assert source_outage_reports[0].semantic_fingerprint == source_outage_reports[1].semantic_fingerprint
    assert source_outage_reports[0].blockers == source_outage_reports[1].blockers
    assert future_reports[0].semantic_fingerprint == future_reports[1].semantic_fingerprint
    assert future_reports[0].blockers == future_reports[1].blockers


def test_missing_day_mutates_working_copy_and_replay_detects_gap(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    source_before = request.source_db_path.read_bytes()

    report = EvidenceRehearsalOrchestrator().run(
        EvidenceRehearsalFaultInjector().inject(request, "missing_day")
    )

    assert any(
        blocker.startswith("adapter_failure:replay:missing_trading_day:")
        for blocker in report.blockers
    )
    assert request.working_copy_db_path.is_file()
    assert request.source_db_path.read_bytes() == source_before
    assert report.fault_diagnostics["detector"] == "HistoricalEvidenceReplayService"


def test_schema_missing_mutates_working_copy_and_replay_detects_schema(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    source_before = request.source_db_path.read_bytes()

    report = EvidenceRehearsalOrchestrator().run(
        EvidenceRehearsalFaultInjector().inject(request, "schema_missing")
    )

    assert any(
        blocker.startswith("adapter_failure:replay:schema_missing:daily_prices")
        for blocker in report.blockers
    )
    assert request.working_copy_db_path.is_file()
    assert request.source_db_path.read_bytes() == source_before
    assert report.fault_diagnostics["detector"] == "HistoricalEvidenceReplayService"


def test_immature_label_is_computed_by_validated_ml_boundary(tmp_path: Path) -> None:
    report = EvidenceRehearsalOrchestrator().run(
        EvidenceRehearsalFaultInjector().inject(
            _request(tmp_path), "immature_label"
        )
    )

    assert report.ml_shadow is not None
    assert report.ml_shadow.immature_label_rows == 1
    assert "label_not_mature:ml-shadow" in report.blockers
    assert report.fault_diagnostics["detector"] == "MLRehearsalComparisonService"
