from __future__ import annotations

import hashlib

import pytest

from ml_module.historical_run_report import HistoricalMLShadowRunReport


def _sha(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _report(**overrides: object) -> HistoricalMLShadowRunReport:
    values: dict[str, object] = {
        "run_id": "historical-shadow-contract-fixture",
        "dataset_id": "core-2015-2024-v1",
        "model_id": "core-linear-2024-v1",
        "training_end_date": "2024-12-31",
        "oos_start_date": "2025-01-02",
        "oos_end_date": "2025-12-31",
        "accepted_rows": 1000,
        "excluded_rows": 25,
        "fold_ids": ("fold-001", "fold-002"),
        "metrics_bp": {"mae_bp": 125, "precision_at_k_bp": 6000},
        "artifact_hashes": {
            "dataset": _sha("dataset"),
            "model": _sha("model"),
            "evaluation": _sha("evaluation"),
        },
        "blockers": ("corporate_action_coverage_research_only",),
        "evidence_tier": "historical_locked_oos",
        "result_status": "continue_shadow",
    }
    values.update(overrides)
    return HistoricalMLShadowRunReport.create(**values)  # type: ignore[arg-type]


def test_run_report_is_deterministic_hashed_shadow_only_contract() -> None:
    first = _report()
    second = _report(
        metrics_bp={"precision_at_k_bp": 6000, "mae_bp": 125},
        artifact_hashes={
            "evaluation": _sha("evaluation"),
            "model": _sha("model"),
            "dataset": _sha("dataset"),
        },
    )

    assert first == second
    assert first.report_hash.startswith("sha256:")
    assert first.shadow_only is True
    assert first.production_eligible is False
    assert first.production_action_allowed is False


def test_run_report_round_trip_rejects_tampering_and_unsafe_flags() -> None:
    report = _report()
    assert HistoricalMLShadowRunReport.from_dict(report.to_dict()) == report

    tampered = report.to_dict()
    tampered["accepted_rows"] = 1001
    with pytest.raises(ValueError, match="report hash mismatch"):
        HistoricalMLShadowRunReport.from_dict(tampered)

    unsafe = report.to_dict()
    unsafe["production_action_allowed"] = True
    with pytest.raises(ValueError, match="shadow flags"):
        HistoricalMLShadowRunReport.from_dict(unsafe)


def test_run_report_rejects_float_metrics_and_invalid_artifact_hash() -> None:
    with pytest.raises(TypeError, match="metrics_bp"):
        _report(metrics_bp={"mae_bp": 12.5})
    with pytest.raises(ValueError, match="artifact_hashes"):
        _report(artifact_hashes={"model": "sha256:short"})


def test_run_report_nested_mappings_are_immutable() -> None:
    report = _report()

    with pytest.raises(TypeError):
        report.metrics_bp["mae_bp"] = 1  # type: ignore[index]


def test_run_report_rejects_incoherent_dates_or_duplicate_fold_ids() -> None:
    with pytest.raises(ValueError, match="date range"):
        _report(oos_start_date="2024-12-30")
    with pytest.raises(ValueError, match="fold_ids"):
        _report(fold_ids=("fold-001", "fold-001"))
