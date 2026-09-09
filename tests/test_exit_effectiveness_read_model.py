from app_module.exit_effectiveness_read_model import (
    ExitEffectivenessObservation,
    ExitEffectivenessReadModel,
)


def test_read_model_separates_avoided_loss_and_early_exit_regret() -> None:
    report = ExitEffectivenessReadModel().build(
        observations=(
            ExitEffectivenessObservation("e1", "thesis_invalid", "ready", "closed", -200, -800),
            ExitEffectivenessObservation("e2", "thesis_invalid", "ready", "closed", 100, 500),
            ExitEffectivenessObservation("e3", "thesis_invalid", "pending", "proposal", None, None),
        )
    )

    item = report.slices[0]
    assert item.ready_count == 2
    assert item.pending_count == 1
    assert item.avoided_loss_count == 1
    assert item.avoided_loss_average_bp == 800
    assert item.early_exit_regret_count == 1
    assert item.early_exit_regret_average_bp == 500
    assert item.avoided_loss_precision_bp == 5000
    assert report.investment_effectiveness_claim is False


def test_pending_outcomes_are_not_in_metric_denominator() -> None:
    report = ExitEffectivenessReadModel().build(
        observations=(ExitEffectivenessObservation("e1", "risk_watch", "pending", "proposal", None, None),)
    )

    item = report.slices[0]
    assert item.ready_count == 0
    assert item.avoided_loss_precision_bp is None
    assert item.avoided_loss_average_bp is None


def test_proposal_and_closed_rows_with_same_reason_are_not_mixed() -> None:
    report = ExitEffectivenessReadModel().build(
        observations=(
            # ``post_exit_return_bp`` is the legacy counterfactual spelling
            # for a proposal and must never become a realised metric.
            ExitEffectivenessObservation(
                "proposal",
                "same_reason",
                "ready",
                "proposal",
                None,
                -800,
            ),
            ExitEffectivenessObservation(
                "closed",
                "same_reason",
                "ready",
                "closed",
                100,
                500,
            ),
        )
    )

    item = report.slices[0]
    assert item.ready_count == 1
    assert item.avoided_loss_count == 0
    assert item.early_exit_regret_count == 1
    assert item.counterfactual_ready_count == 1
    assert item.counterfactual_avoided_loss_count == 1


def test_ready_outcome_requires_post_exit_return() -> None:
    try:
        ExitEffectivenessObservation("e", "reason", "ready", "closed", 0, None)
    except ValueError as exc:
        assert "post_exit_return_bp" in str(exc)
    else:
        raise AssertionError("ready outcome without post-exit return should fail")


def test_unknown_maturity_status_is_rejected() -> None:
    try:
        ExitEffectivenessObservation("e", "reason", "unknown", "proposal", None, None)
    except ValueError as exc:
        assert "maturity_status" in str(exc)
    else:
        raise AssertionError("unknown maturity should fail")
