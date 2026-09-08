from app_module.machine_status_classification import (
    MACHINE_STATUS_HUMAN_REVIEW,
    MACHINE_STATUS_INVALID_EVIDENCE,
    MACHINE_STATUS_SOURCE_MISSING,
    MACHINE_STATUS_WAITING_FOR_TIME,
    MACHINE_STATUS_UNKNOWN,
    classify_machine_status,
)


def test_generic_action_required_is_not_named_human_review() -> None:
    assert classify_machine_status("action_required") == MACHINE_STATUS_UNKNOWN
    assert (
        classify_machine_status("action_required", ("source_missing_screening_matrix",))
        == MACHINE_STATUS_SOURCE_MISSING
    )


def test_machine_classification_keeps_waiting_and_invalid_distinct() -> None:
    assert (
        classify_machine_status("waiting_for_time", ("insufficient_dry_run_days",))
        == MACHINE_STATUS_WAITING_FOR_TIME
    )
    assert (
        classify_machine_status("blocked", ("evidence_hash_mismatch",))
        == MACHINE_STATUS_INVALID_EVIDENCE
    )


def test_explicit_human_review_diagnostic_remains_human() -> None:
    assert (
        classify_machine_status("action_required", ("pending_human_review",))
        == MACHINE_STATUS_HUMAN_REVIEW
    )


def test_source_gap_diagnostic_cannot_be_hidden_by_passed_status() -> None:
    assert (
        classify_machine_status("passed", ("screening_matrix_missing",))
        == MACHINE_STATUS_SOURCE_MISSING
    )
