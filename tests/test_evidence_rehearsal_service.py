from __future__ import annotations

from dataclasses import replace

import pytest

from app_module.artifact_lineage_verifier import ArtifactIdentity
from app_module.evidence_rehearsal_dtos import (
    CoverageMetric,
    EvidenceRehearsalScenario,
    RehearsalArtifact,
)
from app_module.evidence_rehearsal_service import EvidenceRehearsalService


DECISION_DATE = "2026-07-12"


def _scenario() -> EvidenceRehearsalScenario:
    return EvidenceRehearsalScenario(
        scenario_id="cross-domain-fixture",
        decision_date=DECISION_DATE,
        source_db_path="C:/fixtures/evidence.sqlite",
        working_copy_db_path="C:/work/rehearsal.sqlite",
        tier="engineering_fixture",
    )


def _artifact(
    artifact_id: str,
    artifact_type: str,
    *,
    parents: tuple[str, ...] = (),
) -> ArtifactIdentity:
    return ArtifactIdentity(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        run_id="engineering-cross-domain-fixture",
        decision_date=DECISION_DATE,
        as_of_date="2026-07-11",
        available_date=DECISION_DATE,
        source_id="fixture.governed",
        source_version="v1",
        data_quality="observed",
        missing_state="complete",
        strategy_version="rule-v1",
        policy_version="policy-v1",
        model_version="shadow-v1",
        parent_artifact_ids=parents,
        evidence_tier="engineering_fixture",
        current_status="current_engineering",
        content_hash="a" * 64,
        rollback_reference="commit:fixture",
    )


def _complete_outputs() -> dict[str, tuple[ArtifactIdentity, ...]]:
    chain = (
        ("source", _artifact("data", "daily_governed_data")),
        ("market", _artifact("market", "market_context", parents=("data",))),
        ("replay", _artifact("recommendation", "recommendation", parents=("market",))),
        ("advice", _artifact("advice", "bounded_advice", parents=("recommendation",))),
        ("paper", _artifact("paper", "paper_portfolio", parents=("advice",))),
        ("health", _artifact("health", "position_health", parents=("paper",))),
        ("evidence", _artifact("evidence", "evidence_event", parents=("health",))),
        ("outcome", _artifact("outcome", "forward_outcome", parents=("evidence",))),
        ("weekly", _artifact("weekly", "weekly_review", parents=("outcome",))),
        ("signal", _artifact("signal", "signal_effectiveness", parents=("weekly",))),
        ("ml", _artifact("ml", "ml_shadow_prediction", parents=("signal",))),
    )
    return {adapter_name: (artifact,) for adapter_name, artifact in chain}


def test_orchestrates_complete_cross_domain_chain_as_read_only_ordered_report() -> None:
    result = EvidenceRehearsalService().run(_scenario(), _complete_outputs())

    assert result.status == "complete"
    assert result.ordered_artifact_ids == (
        "data", "market", "recommendation", "advice", "paper", "health", "evidence", "outcome", "weekly", "signal", "ml",
    )
    assert result.blockers == ()
    assert result.diagnostics == ()
    assert result.artifact_dag["ml"] == ("signal",)
    assert result.artifact_count == 11
    assert result.formal_product_closeout is False
    assert result.production_actions_allowed is False


def test_repeat_same_scenario_produces_identical_hashes_ids_and_counts() -> None:
    service = EvidenceRehearsalService()
    first = service.run(_scenario(), _complete_outputs())
    second = service.run(_scenario(), _complete_outputs())

    assert first == second
    assert first.ordered_artifact_ids == second.ordered_artifact_ids
    assert first.artifact_hashes == second.artifact_hashes
    assert first.artifact_count == second.artifact_count == 11


def test_build_preserves_the_public_rehearsal_report_contract() -> None:
    result = EvidenceRehearsalService().build(
        _scenario(),
        artifacts=(
            RehearsalArtifact(
                artifact_id="replay",
                decision_date=DECISION_DATE,
                available_date=DECISION_DATE,
                tier="historical_replay_candidate",
            ),
        ),
        coverage=(
            CoverageMetric(
                source_id="historical_replay",
                total_count=1,
                observed_count=1,
                degraded_count=0,
                missing_count=0,
                future_blocked_count=0,
                immature_label_count=0,
                coverage_bp=10000,
            ),
        ),
    )

    assert result.scenario == _scenario()
    assert result.artifacts[0].artifact_id == "replay"
    assert result.coverage_metrics[0].source_id == "historical_replay"


def test_preserves_upstream_multi_parent_lineage_when_direct_parent_is_present() -> None:
    outputs = {
        **_complete_outputs(),
        "advice": (
            _artifact(
                "advice",
                "bounded_advice",
                parents=("recommendation", "market"),
            ),
        ),
    }

    result = EvidenceRehearsalService().run(_scenario(), outputs)

    assert result.status == "complete"
    assert result.artifact_dag["advice"] == ("recommendation", "market")


def test_fails_closed_when_adapter_emits_artifact_from_another_domain() -> None:
    outputs = {
        **_complete_outputs(),
        "source": (_artifact("data", "market_context"),),
    }

    result = EvidenceRehearsalService().run(_scenario(), outputs)

    assert result.status == "degraded"
    assert (
        "adapter_artifact_type_mismatch:source:market_context:daily_governed_data"
        in result.blockers
    )
    assert result.artifact_dag == {}
    assert result.artifact_hashes == {}


def test_duplicate_artifact_id_is_not_projected_into_unverified_dag_or_hashes() -> None:
    outputs = {
        **_complete_outputs(),
        "market": (
            replace(_complete_outputs()["market"][0], artifact_id="data"),
        ),
    }

    result = EvidenceRehearsalService().run(_scenario(), outputs)

    assert result.status == "degraded"
    assert "duplicate_artifact_id:data" in result.blockers
    assert result.artifact_dag == {}
    assert result.artifact_hashes == {}


def test_fails_closed_when_parent_is_in_the_wrong_cross_domain_chain_position() -> None:
    outputs = {
        **_complete_outputs(),
        "advice": (
            _artifact("advice", "bounded_advice", parents=("data",)),
        ),
    }

    result = EvidenceRehearsalService().run(_scenario(), outputs)

    assert result.status == "degraded"
    assert "missing_required_cross_domain_parent:advice:recommendation" in result.blockers
    assert result.artifact_dag == {}
    assert result.artifact_hashes == {}


@pytest.mark.parametrize(
    ("name", "outputs", "expected_blocker"),
    (
        (
            "missing-day",
            {**_complete_outputs(), "source": ()},
            "missing_required_adapter_output:source",
        ),
        (
            "source-outage",
            {**_complete_outputs(), "source": (RuntimeError("source outage"),)},
            "adapter_failure:source:source outage",
        ),
        (
            "future-data",
            {
                **_complete_outputs(),
                "source": (replace(_complete_outputs()["source"][0], available_date="2026-07-13"),),
            },
            "future_available_date:data",
        ),
        (
            "future-scenario-day",
            {
                **_complete_outputs(),
                "source": (
                    replace(
                        _complete_outputs()["source"][0],
                        decision_date="2026-07-13",
                        as_of_date="2026-07-13",
                        available_date="2026-07-13",
                    ),
                ),
            },
            "scenario_decision_date_mismatch:data",
        ),
        (
            "cycle",
            {
                **_complete_outputs(),
                "source": (_artifact("data", "daily_governed_data", parents=("ml",)),),
            },
            "lineage_cycle",
        ),
        (
            "missing-parent",
            {
                **_complete_outputs(),
                "paper": (_artifact("paper", "paper_portfolio", parents=("not-produced",)),),
            },
            "missing_parent:paper:not-produced",
        ),
    ),
)
def test_fails_closed_or_degrades_for_unsafe_adapter_outputs(
    name: str,
    outputs: dict[str, tuple[object, ...]],
    expected_blocker: str,
) -> None:
    result = EvidenceRehearsalService().run(_scenario(), outputs)

    assert name
    assert result.status == "degraded"
    assert expected_blocker in result.blockers
    assert result.formal_product_closeout is False
    assert result.production_actions_allowed is False
