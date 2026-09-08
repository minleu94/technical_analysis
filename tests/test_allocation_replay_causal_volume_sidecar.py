from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from ml_module.allocation_replay_causal_volume_sidecar import (
    CAUSAL_VOLUME_SIDECAR_POLICY_VERSION,
    CausalVolumeTarget,
    reconstruct_causal_volume20,
)


def _create_source(path: Path, rows: list[tuple[Any, ...]]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE replay_source (
                local_row_index INTEGER PRIMARY KEY,
                decision_at TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                price_event_at TEXT,
                price_available_at TEXT,
                volume_shares INTEGER,
                median_volume_20d_shares INTEGER,
                source_values_hash TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO replay_source(
                local_row_index, decision_at, decision_date, symbol,
                price_event_at, price_available_at, volume_shares,
                median_volume_20d_shares, source_values_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def test_sidecar_carries_volume_window_across_year_and_checks_same_year_parity(
    tmp_path: Path,
) -> None:
    first_year = tmp_path / "year0.sqlite"
    second_year = tmp_path / "year1.sqlite"
    first_rows: list[tuple[Any, ...]] = []
    for index in range(19):
        decision_at = datetime(
            2015,
            12,
            1,
            8,
            30,
            tzinfo=timezone.utc,
        ) + timedelta(days=index)
        event_at = decision_at - timedelta(hours=1)
        first_rows.append(
            (
                index,
                decision_at.isoformat(),
                decision_at.date().isoformat(),
                "AAA",
                event_at.isoformat(),
                event_at.isoformat(),
                100,
                100,
                f"source-{index}",
            )
        )
    second_rows: list[tuple[Any, ...]] = []
    first_target_at = datetime(2016, 1, 4, 8, 30, tzinfo=timezone.utc)
    first_event_at = first_target_at - timedelta(hours=1)
    second_rows.append(
        (
            0,
            first_target_at.isoformat(),
            first_target_at.date().isoformat(),
            "AAA",
            first_event_at.isoformat(),
            first_event_at.isoformat(),
            100,
            None,
            "source-19",
        )
    )
    second_target_at = first_target_at + timedelta(days=1)
    second_event_at = second_target_at - timedelta(hours=1)
    second_rows.append(
        (
            1,
            second_target_at.isoformat(),
            second_target_at.date().isoformat(),
            "AAA",
            second_event_at.isoformat(),
            second_event_at.isoformat(),
            100,
            100,
            "source-20",
        )
    )
    _create_source(first_year, first_rows)
    _create_source(second_year, second_rows)

    result = reconstruct_causal_volume20(
        source_paths=((0, first_year), (1, second_year)),
        targets=(
            CausalVolumeTarget(
                year_ordinal=1,
                local_row_index=0,
                symbol="AAA",
                decision_at=first_target_at,
                stored_median_volume_20d_shares=None,
            ),
            CausalVolumeTarget(
                year_ordinal=1,
                local_row_index=1,
                symbol="AAA",
                decision_at=second_target_at,
                stored_median_volume_20d_shares=100,
            ),
        ),
    )

    first = result.values[(1, 0)]
    second = result.values[(1, 1)]
    assert result.evidence["policy_version"] == (
        CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
    )
    assert result.evidence["cross_year_recovered_row_count"] == 1
    assert result.evidence["same_year_parity_checked_row_count"] == 1
    assert result.evidence["same_year_parity_match_row_count"] == 1
    assert first.derived_median_volume_20d_shares == 100
    assert first.recovered_from_missing_stored_median is True
    assert second.same_year_stored_median_matches is True


def test_sidecar_fails_closed_on_stored_median_parity_mismatch(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    rows: list[tuple[Any, ...]] = []
    for index in range(20):
        decision_at = datetime(
            2026,
            1,
            1,
            8,
            30,
            tzinfo=timezone.utc,
        ) + timedelta(days=index)
        event_at = decision_at - timedelta(hours=1)
        rows.append(
            (
                index,
                decision_at.isoformat(),
                decision_at.date().isoformat(),
                "AAA",
                event_at.isoformat(),
                event_at.isoformat(),
                100,
                101 if index == 19 else 100,
                f"source-{index}",
            )
        )
    _create_source(source, rows)

    with pytest.raises(ValueError, match="parity mismatch"):
        reconstruct_causal_volume20(
            source_paths=((0, source),),
            targets=(
                CausalVolumeTarget(
                    year_ordinal=0,
                    local_row_index=19,
                    symbol="AAA",
                    decision_at=datetime(
                        2026,
                        1,
                        20,
                        8,
                        30,
                        tzinfo=timezone.utc,
                    ),
                    stored_median_volume_20d_shares=101,
                ),
            ),
        )


def test_sidecar_computes_selected_row_after_duplicate_event_without_reappend(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    rows: list[tuple[Any, ...]] = []
    for index in range(20):
        decision_at = datetime(
            2026,
            2,
            1,
            8,
            30,
            tzinfo=timezone.utc,
        ) + timedelta(days=index)
        event_at = decision_at - timedelta(hours=1)
        rows.append(
            (
                index,
                decision_at.isoformat(),
                decision_at.date().isoformat(),
                "AAA",
                event_at.isoformat(),
                event_at.isoformat(),
                100,
                100,
                f"source-{index}",
            )
        )
    duplicate_at = datetime(2026, 2, 21, 8, 30, tzinfo=timezone.utc)
    duplicate_event = (
        datetime(2026, 2, 20, 8, 30, tzinfo=timezone.utc)
        - timedelta(hours=1)
    )
    rows.append(
        (
            20,
            duplicate_at.isoformat(),
            duplicate_at.date().isoformat(),
            "AAA",
            duplicate_event.isoformat(),
            duplicate_event.isoformat(),
            999,
            None,
            "source-duplicate",
        )
    )
    _create_source(source, rows)

    result = reconstruct_causal_volume20(
        source_paths=((0, source),),
        targets=(
            CausalVolumeTarget(
                year_ordinal=0,
                local_row_index=20,
                symbol="AAA",
                decision_at=duplicate_at,
                stored_median_volume_20d_shares=None,
            ),
        ),
    )

    value = result.values[(0, 20)]
    assert value.derived_median_volume_20d_shares == 100
    assert value.observation_count == 20


def test_sidecar_accepts_zero_volume_as_observed_event(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    rows: list[tuple[Any, ...]] = []
    for index in range(20):
        decision_at = datetime(
            2026,
            3,
            1,
            8,
            30,
            tzinfo=timezone.utc,
        ) + timedelta(days=index)
        event_at = decision_at - timedelta(hours=1)
        rows.append(
            (
                index,
                decision_at.isoformat(),
                decision_at.date().isoformat(),
                "AAA",
                event_at.isoformat(),
                None,
                0,
                0,
                f"source-{index}",
            )
        )
    _create_source(source, rows)

    result = reconstruct_causal_volume20(
        source_paths=((0, source),),
        targets=(
            CausalVolumeTarget(
                year_ordinal=0,
                local_row_index=19,
                symbol="AAA",
                decision_at=datetime(
                    2026,
                    3,
                    20,
                    8,
                    30,
                    tzinfo=timezone.utc,
                ),
                stored_median_volume_20d_shares=0,
            ),
        ),
    )

    value = result.values[(0, 19)]
    assert value.derived_median_volume_20d_shares == 0
    assert value.same_year_stored_median_matches is True
    assert result.evidence["derived_observed_row_count"] == 1


def test_sidecar_rejects_target_identity_mismatch_before_value_use(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    decision_at = datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc)
    event_at = decision_at - timedelta(hours=1)
    _create_source(
        source,
        [
            (
                7,
                decision_at.isoformat(),
                decision_at.date().isoformat(),
                "AAA",
                event_at.isoformat(),
                event_at.isoformat(),
                100,
                None,
                "source-7",
            )
        ],
    )

    with pytest.raises(ValueError, match="target identity mismatch"):
        reconstruct_causal_volume20(
            source_paths=((0, source),),
            targets=(
                CausalVolumeTarget(
                    year_ordinal=0,
                    local_row_index=7,
                    symbol="AAA",
                    decision_at=decision_at + timedelta(minutes=1),
                    stored_median_volume_20d_shares=None,
                ),
            ),
        )
