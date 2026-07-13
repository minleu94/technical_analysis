import pytest

from ml_module.purged_walk_forward import MLTimeWindowRow, PurgedWalkForwardSplitter


def _rows() -> tuple[MLTimeWindowRow, ...]:
    dates = [f"2026-01-{day:02d}" for day in range(1, 13)]
    return tuple(
        MLTimeWindowRow(
            row_id=f"r{index}",
            decision_date=day,
            label_end_date=f"2026-01-{min(index + 3, 12):02d}",
        )
        for index, day in enumerate(dates, start=1)
    )


def test_splitter_builds_expanding_purged_folds() -> None:
    folds = PurgedWalkForwardSplitter(
        minimum_train_dates=4,
        test_date_count=2,
        purge_trading_days=1,
        embargo_trading_days=1,
    ).split(_rows())

    assert len(folds) >= 2
    first = folds[0]
    assert first.test_start == "2026-01-05"
    assert first.test_end == "2026-01-06"
    assert all(row.decision_date < first.test_start for row in first.train_rows)
    assert all(row.label_end_date < first.test_start for row in first.train_rows)
    assert {row.row_id for row in first.train_rows}.isdisjoint(
        row.row_id for row in first.test_rows
    )


def test_embargo_separates_test_blocks() -> None:
    folds = PurgedWalkForwardSplitter(
        minimum_train_dates=4,
        test_date_count=2,
        purge_trading_days=0,
        embargo_trading_days=1,
    ).split(_rows())

    assert folds[1].test_start == "2026-01-08"


def test_split_is_prefix_invariant() -> None:
    splitter = PurgedWalkForwardSplitter(
        minimum_train_dates=4,
        test_date_count=2,
        purge_trading_days=1,
        embargo_trading_days=1,
    )
    short = splitter.split(_rows()[:9])
    long = splitter.split(_rows())

    assert short[0] == long[0]


def test_invalid_split_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="minimum_train_dates"):
        PurgedWalkForwardSplitter(
            minimum_train_dates=0,
            test_date_count=2,
            purge_trading_days=1,
            embargo_trading_days=1,
        )


def test_purge_counts_trading_dates_across_a_weekend() -> None:
    rows = (
        MLTimeWindowRow("thu", "2024-05-30", "2024-05-30"),
        MLTimeWindowRow("fri", "2024-05-31", "2024-05-31"),
        MLTimeWindowRow("mon", "2024-06-03", "2024-06-03"),
        MLTimeWindowRow("tue", "2024-06-04", "2024-06-04"),
    )
    fold = PurgedWalkForwardSplitter(
        minimum_train_dates=2,
        test_date_count=1,
        purge_trading_days=1,
        embargo_trading_days=0,
    ).split(rows)[0]

    assert fold.test_start == "2024-06-03"
    assert tuple(row.row_id for row in fold.train_rows) == ("thu",)


def test_legacy_calendar_day_parameters_fail_with_migration_message() -> None:
    with pytest.raises(TypeError, match="purge_trading_days"):
        PurgedWalkForwardSplitter(
            minimum_train_dates=2,
            test_date_count=1,
            purge_days=1,
            embargo_days=0,
        )


def test_appending_future_rows_preserves_all_completed_prefix_folds() -> None:
    splitter = PurgedWalkForwardSplitter(
        minimum_train_dates=4,
        test_date_count=2,
        purge_trading_days=1,
        embargo_trading_days=1,
    )
    prefix = splitter.split(_rows()[:10])
    extended = splitter.split(_rows())

    assert extended[: len(prefix)] == prefix
