from __future__ import annotations

import json
from pathlib import Path

import pytest

from development_module.formal_observation_lane import (
    CANDIDATE_SOURCE_IDS,
    FormalObservationLaneDecision,
    RULE_ONLY_SOURCE_IDS,
)
from scripts.bind_formal_observation_lane import append_binding


def _decision(**overrides) -> FormalObservationLaneDecision:
    values = {
        "decision_id": "decision:rule-only:20260728-r1",
        "holdout_id": "formal-rule-only-20260729-r1",
        "decided_at": "2026-07-28T12:40:11+08:00",
        "owner_id": "archi",
        "first_eligible_session": "2026-07-29",
        "allowed_source_ids": RULE_ONLY_SOURCE_IDS,
        "excluded_source_ids": CANDIDATE_SOURCE_IDS,
        "rollback_reference": "append formal-observation-lane-disabled.v1",
    }
    values.update(overrides)
    return FormalObservationLaneDecision(**values)


def _output_root(tmp_path: Path) -> Path:
    root = tmp_path / "technical_analysis_development_output"
    governance = root / "governance"
    governance.mkdir(parents=True)
    decision = {
        "decision": "seen_oos",
        "owner_provided_authorization": "owner record",
        "year_2025_usage": "development_only",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "effective_timestamp_utc": "2026-07-14T05:07:25Z",
        "development_output_root": str(root),
        "new_holdout_start": "2026-07-15",
    }
    (governance / "DevelopmentDataUsageDecision.jsonl").write_text(
        json.dumps(decision) + "\n", encoding="utf-8"
    )
    return root


def test_lane_decision_roundtrip_and_hash() -> None:
    decision = _decision()
    restored = FormalObservationLaneDecision.from_dict(
        {**decision.to_dict(), "content_hash": decision.content_hash}
    )
    assert restored == decision
    assert restored.content_hash.startswith("sha256:")


def test_lane_decision_rejects_candidate_source_in_allowed_set() -> None:
    with pytest.raises(ValueError, match="overlap"):
        _decision(
            allowed_source_ids=tuple(
                sorted((*RULE_ONLY_SOURCE_IDS, "fubon.marketdata"))
            )
        )


def test_lane_decision_rejects_unsafe_flags() -> None:
    with pytest.raises(ValueError, match="safety flags"):
        _decision(formal_evidence_credit_authorized=True)


def test_append_binding_preserves_legacy_record_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    root = _output_root(tmp_path)
    registry = root / "governance" / "HoldoutConsumptionRegistry.jsonl"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "holdout-consumption-registry.v2",
                "record_type": "formal_holdout_binding",
                "development_holdout_start": "2026-07-15",
                "formal_trading_session": "2026-07-21",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    decision = _decision()
    decision_path = root / "governance" / "lane.json"
    decision_path.write_text(
        json.dumps({**decision.to_dict(), "content_hash": decision.content_hash}),
        encoding="utf-8",
    )

    binding = append_binding(
        output_root=root,
        decision_path=decision_path,
        formal_trading_session="2026-07-29",
        bound_at="2026-07-28T12:45:00+08:00",
    )

    assert binding["holdout_id"] == decision.holdout_id
    assert len(registry.read_text(encoding="utf-8").splitlines()) == 2
    with pytest.raises(ValueError, match="holdout_id already exists"):
        append_binding(
            output_root=root,
            decision_path=decision_path,
            formal_trading_session="2026-07-29",
            bound_at="2026-07-28T12:46:00+08:00",
        )
