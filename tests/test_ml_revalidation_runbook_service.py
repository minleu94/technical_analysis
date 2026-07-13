from app_module.ml_revalidation_runbook_service import MLRevalidationRunbookService


def test_runbook_contains_complete_revalidation_sequence() -> None:
    runbook = MLRevalidationRunbookService().build(
        run_id="ml-revalidation-2026q3",
        trigger="new_matured_evidence",
        dataset_id="gate7-next",
        current_model_id="m1",
        training_as_of="2026-09-30",
        owner="ml-reviewer",
    )

    assert [step.step_id for step in runbook.steps] == [
        "freeze_dataset",
        "validate_available_dates",
        "purged_walk_forward",
        "train_challengers",
        "calibrate_oof",
        "write_shadow_predictions",
        "measure_drift",
        "compare_champion",
        "build_review_package",
        "check_shadow_boundary",
    ]
    assert runbook.auto_retrain_allowed is False
    assert runbook.auto_promotion_allowed is False
    assert runbook.production_scheduler_allowed is False


def test_runbook_converts_to_open_ml_revalidation_gate() -> None:
    runbook = MLRevalidationRunbookService().build(
        run_id="r1",
        trigger="major_drift",
        dataset_id="d2",
        current_model_id="m1",
        training_as_of="2026-09-30",
        owner="ml-reviewer",
    )

    gate = runbook.to_gate_item(revision=1, earliest_validation_date="2026-10-01")
    assert gate.category == "ml_revalidation"
    assert gate.status == "open"
    assert gate.progress_bp == 0
    assert "do not auto-promote challenger" in gate.prohibited_actions


def test_unknown_revalidation_trigger_is_rejected() -> None:
    try:
        MLRevalidationRunbookService().build(
            run_id="r",
            trigger="because",
            dataset_id="d",
            current_model_id="m",
            training_as_of="2026-09-30",
            owner="owner",
        )
    except ValueError as exc:
        assert "trigger" in str(exc)
    else:
        raise AssertionError("unknown trigger should fail")
