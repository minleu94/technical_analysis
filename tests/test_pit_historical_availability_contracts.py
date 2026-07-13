from datetime import date

import pytest

from data_module import fundamental_availability as availability


def _record(**overrides: object) -> object:
    values: dict[str, object] = {
        "source_id": "mops.statement.publication",
        "source_version": "fixture-v1",
        "source_hash": "a" * 64,
        "symbol": "2330",
        "data_family": "quarterly_statement",
        "period_or_event_date": date(2024, 12, 31),
        "announcement_at": date(2025, 2, 14),
        "first_observed_at": None,
        "available_at": date(2025, 2, 14),
        "revision": 1,
        "parent_revision": None,
        "effective_at": None,
        "quality_tier": "official",
        "match_method": "official_natural_key",
        "content_hash": "b" * 64,
        "warnings": (),
    }
    values.update(overrides)
    record_type = getattr(availability, "AvailabilityEvidenceRecord", None)
    assert record_type is not None, "AvailabilityEvidenceRecord contract is missing"
    return record_type(**values)


def test_backfill_date_is_not_historical_availability() -> None:
    record = _record(
        source_id="manual.retroactive_statement_baseline_mapping",
        announcement_at=None,
        available_at=date(2026, 6, 17),
        quality_tier="retroactive_baseline",
    )

    result = availability.evaluate_historical_feature_eligibility(
        record,
        feature_cutoff=date(2024, 12, 31),
    )

    assert result.eligible is False
    assert "retroactive_backfill_not_historical_availability" in result.reasons


def test_available_before_announcement_is_rejected() -> None:
    with pytest.raises(
        availability.AvailabilityEvidenceValidationError,
        match="available_before_announcement",
    ):
        _record(available_at=date(2025, 2, 13))


def test_revision_is_append_only_and_cannot_overwrite_existing_content() -> None:
    original = _record()
    revision = _record(
        source_version="fixture-v2",
        available_at=date(2025, 2, 20),
        revision=2,
        parent_revision=1,
        content_hash="c" * 64,
    )
    history = availability.append_availability_revision((original,), revision)

    with pytest.raises(
        availability.AvailabilityEvidenceValidationError,
        match="revision_content_overwrite",
    ):
        availability.append_availability_revision(
            history,
            _record(revision=2, parent_revision=1, content_hash="d" * 64),
        )

    assert history == (original, revision)


def test_revision_cannot_be_visible_before_its_parent() -> None:
    original = _record()
    with pytest.raises(
        availability.AvailabilityEvidenceValidationError,
        match="revision_before_parent_available",
    ):
        availability.append_availability_revision(
            (original,),
            _record(
                revision=2,
                parent_revision=1,
                announcement_at=date(2025, 2, 12),
                available_at=date(2025, 2, 13),
            ),
        )


def test_event_date_does_not_make_future_announcement_visible() -> None:
    event = _record(
        data_family="corporate_action",
        period_or_event_date=date(2025, 3, 1),
        announcement_at=date(2025, 3, 10),
        available_at=date(2025, 3, 10),
        effective_at=date(2025, 3, 20),
    )

    assert availability.visible_evidence_as_of((event,), as_of_date=date(2025, 3, 5)) == ()
    assert availability.visible_evidence_as_of((event,), as_of_date=date(2025, 3, 10)) == (event,)


def test_unknown_corporate_action_coverage_blocks_clean_label() -> None:
    coverage = availability.CoverageWindow(
        source_id="corporate_action.ex_dividend_timeline",
        data_family="corporate_action",
        coverage_start=None,
        coverage_end=None,
        quality="unknown",
    )

    result = availability.evaluate_label_window_eligibility(
        label_start=date(2025, 1, 2),
        label_end=date(2025, 1, 31),
        coverage=coverage,
        strict=True,
    )

    assert result.eligible is False
    assert result.quality == "blocked"
    assert "coverage_unknown" in result.reasons


def test_coverage_diagnostics_keep_future_and_revision_counts_typed() -> None:
    official = _record()
    revision = _record(
        source_version="fixture-v2",
        available_at=date(2025, 2, 20),
        revision=2,
        parent_revision=1,
        content_hash="c" * 64,
    )

    diagnostics = availability.summarize_availability_coverage(
        (official, revision),
        feature_cutoff=date(2025, 2, 15),
    )

    assert diagnostics.total == 2
    assert diagnostics.matched_official == 2
    assert diagnostics.revision == 1
    assert diagnostics.future_blocked == 1
    assert diagnostics.eligible == 1
