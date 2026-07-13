from __future__ import annotations

from copy import deepcopy

from app_module.evidence_rehearsal_adapters import (
    HistoricalReplayRehearsalAdapter,
    canonical_payload_hash,
)


def _replay_summary() -> dict[str, object]:
    return {
        "replay_run_id": "hre-fixture",
        "replay_mode": "historical_replay",
        "source_label": "simulated_scheduler",
        "source_version": "replay-v1",
        "as_of_date": "2026-07-10",
        "available_date": "2026-07-10",
        "data_quality": "observed",
        "days": [
            {
                "decision_date": "2026-07-10",
                "selected_recommendation_result_id": "rec-1",
                "source_ids": ["source-1"],
                "evidence_ids": ["event-1"],
                "diagnostics": ["missing_screening_matrix"],
                "score_effectiveness_rows": [{"bucket": "80-100", "sample_count": 2}],
                "benchmark_diagnostics": ["missing_benchmark", "missing_industry_benchmark"],
            }
        ],
    }


def test_adapter_projects_immutable_replay_payload_with_stable_hash_and_lineage() -> None:
    summary = _replay_summary()
    original = deepcopy(summary)

    artifacts = HistoricalReplayRehearsalAdapter().project(
        summary,
        decision_date="2026-07-10",
        rollback_reference="commit:fixture",
    )

    assert summary == original
    assert len(artifacts) == 1
    payload = artifacts[0].to_dict()
    assert payload["parent_artifact_ids"] == ("source-1", "rec-1", "event-1")
    assert payload["as_of_date"] == "2026-07-10"
    assert payload["available_date"] == "2026-07-10"
    assert payload["source_version"] == "replay-v1"
    assert payload["data_quality"] == "observed"
    assert payload["missing_state"] == "missing"
    assert payload["diagnostics"] == (
        "missing_screening_matrix",
        "missing_benchmark",
        "missing_industry_benchmark",
    )
    assert payload["content_hash"] == canonical_payload_hash(payload["canonical_payload"])
    assert canonical_payload_hash({"b": 1, "a": "台股"}) == canonical_payload_hash({"a": "台股", "b": 1})


def test_adapter_blocks_future_available_payload_and_excludes_it_from_effectiveness_denominator() -> None:
    summary = _replay_summary()
    summary["available_date"] = "2026-07-11"

    artifact = HistoricalReplayRehearsalAdapter().project(
        summary,
        decision_date="2026-07-10",
        rollback_reference="commit:fixture",
    )[0]

    payload = artifact.to_dict()
    assert payload["available_date"] == "2026-07-10"
    assert payload["canonical_payload"]["available_date"] == "2026-07-11"
    assert payload["current_status"] == "future_blocked"
    assert payload["effectiveness_denominator_included"] is False


def test_adapter_preserves_absent_legacy_fields_without_inventing_fallback_values() -> None:
    artifact = HistoricalReplayRehearsalAdapter().project(
        {
            "replay_run_id": "hre-legacy",
            "days": [{"decision_date": "2026-07-10", "diagnostics": ["missing_benchmark"]}],
        },
        decision_date="2026-07-10",
        rollback_reference="commit:fixture",
    )[0]

    payload = artifact.to_dict()
    assert payload["canonical_payload"] == {
        "replay_run_id": "hre-legacy",
        "decision_date": "2026-07-10",
        "diagnostics": ("missing_benchmark",),
        "missing_state": "missing",
    }
    assert "as_of_date" not in payload
    assert "source_version" not in payload
    assert "data_quality" not in payload


def test_adapter_preserves_duplicate_diagnostics_in_original_sequence() -> None:
    summary = _replay_summary()
    summary["days"][0]["diagnostics"] = ["missing_benchmark", "missing_benchmark"]  # type: ignore[index]
    summary["days"][0]["benchmark_diagnostics"] = ["missing_benchmark", "missing_industry_benchmark"]  # type: ignore[index]

    artifact = HistoricalReplayRehearsalAdapter().project(
        summary,
        decision_date="2026-07-10",
        rollback_reference="commit:fixture",
    )[0]

    assert artifact.diagnostics == (
        "missing_benchmark",
        "missing_benchmark",
        "missing_benchmark",
        "missing_industry_benchmark",
    )
