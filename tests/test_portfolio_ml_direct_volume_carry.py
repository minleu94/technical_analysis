from __future__ import annotations

from datetime import datetime
import gzip
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from data_module.portfolio_ml_direct_numeric_store import (
    DIRECT_CARRY_SCHEMA_VERSION,
    DIRECT_REPLAY_VOLUME_CARRY_SCOPE,
    _DirectYearWriter,
    _checkpointed_year_is_valid,
    _empty_carry,
    _read_carry,
    _volume_history_from_carry,
    _write_carry,
)


_TAIPEI = ZoneInfo("Asia/Taipei")
_VOLUME_FEATURE = "daily_prices.成交股數"


def _value(
    *,
    event_at: str,
    volume: int,
    available_at: str | None = None,
) -> Any:
    return SimpleNamespace(
        value_int=volume,
        scale=1,
        event_at=event_at,
        available_at=available_at or event_at,
        formal_training_eligible=True,
        missing_mask=False,
        quality_blocked_mask=False,
        source_value_hash="sha256:" + "a" * 64,
    )


def _writer(
    tmp_path: Path,
    name: str,
    *,
    initial_volume_history: dict[str, tuple[tuple[str, int], ...]] | None = None,
    seed_cutoff: datetime | None = None,
) -> _DirectYearWriter:
    staging = tmp_path / name
    staging.mkdir()
    return _DirectYearWriter(
        staging=staging,
        year=2020,
        year_ordinal=1,
        feature_ids=(_VOLUME_FEATURE,),
        feature_scales=(1,),
        horizons=(5,),
        trade_restriction_events_by_symbol={},
        trade_restriction_timeline_present=False,
        batch_size=128,
        initial_volume_history=initial_volume_history,
        seed_cutoff=seed_cutoff,
    )


def _replay_one(
    writer: _DirectYearWriter,
    *,
    decision_date: str,
    event_date: str,
    volume: int,
    available_at: str | None = None,
) -> dict[str, object]:
    event_at = f"{event_date}T08:30:00+08:00"
    decision_at = f"{decision_date}T08:30:00+08:00"
    return writer._replay_values(
        symbol="AAA",
        decision_at=decision_at,
        stock_current={
            _VOLUME_FEATURE: _value(
                event_at=event_at,
                volume=volume,
                available_at=available_at,
            )
        },
    )


def _seed_nineteen(writer: _DirectYearWriter) -> None:
    for day in range(1, 20):
        _replay_one(
            writer,
            decision_date=f"2019-12-{day + 1:02d}",
            event_date=f"2019-12-{day:02d}",
            volume=day,
        )


def test_december_carry_seeds_january_and_roundtrips_bounded_state(
    tmp_path: Path,
) -> None:
    previous = _writer(tmp_path, "previous")
    try:
        _seed_nineteen(previous)
        carry = _empty_carry()
        carry[DIRECT_REPLAY_VOLUME_CARRY_SCOPE] = (
            previous.volume_history_carry()
        )
        carry_path = tmp_path / "carry.state.gz"
        assert _write_carry(carry_path, carry) == 19
    finally:
        previous.close()

    loaded = _read_carry(carry_path)
    assert loaded["__carry_schema_version__"] == DIRECT_CARRY_SCHEMA_VERSION
    history = _volume_history_from_carry(loaded)
    assert len(history["AAA"]) == 19

    next_year = _writer(
        tmp_path,
        "next",
        initial_volume_history=history,
        seed_cutoff=datetime(2020, 1, 1, tzinfo=_TAIPEI),
    )
    try:
        replay_values = _replay_one(
            next_year,
            decision_date="2020-01-03",
            event_date="2020-01-02",
            volume=20,
        )
        # 1..20 的 lower-pair median 是 floor((10 + 11) / 2) = 10。
        assert replay_values["median_volume_20d_shares"] == 10
        assert next_year.volume_history_seed_event_count == 19
        assert next_year.volume_history_event_count == 20
        assert len(next_year.volume_history_carry()["AAA"]) == 20
    finally:
        next_year.close()


def test_duplicate_event_is_not_reappended_after_year_boundary(
    tmp_path: Path,
) -> None:
    previous = _writer(tmp_path, "previous")
    try:
        _seed_nineteen(previous)
        history = {
            symbol: tuple(
                (event_at, value.volume_shares)
                for event_at, value in events.items()
            )
            for symbol, events in previous.volume_history_carry().items()
        }
    finally:
        previous.close()

    next_year = _writer(
        tmp_path,
        "next",
        initial_volume_history=history,
        seed_cutoff=datetime(2020, 1, 1, tzinfo=_TAIPEI),
    )
    try:
        duplicate = _replay_one(
            next_year,
            decision_date="2020-01-03",
            event_date="2019-12-05",
            volume=6,
        )
        assert duplicate["median_volume_20d_shares"] is None
        assert next_year.volume_history_duplicate_event_count == 1
        new_event = _replay_one(
            next_year,
            decision_date="2020-01-04",
            event_date="2020-01-03",
            volume=20,
        )
        assert new_event["median_volume_20d_shares"] == 10
        assert next_year.volume_history_event_count == 20
    finally:
        next_year.close()


def test_zero_volume_is_observed_and_future_seed_is_rejected(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path, "zero")
    try:
        _seed_nineteen(writer)
        zero = _replay_one(
            writer,
            decision_date="2019-12-21",
            event_date="2019-12-20",
            volume=0,
        )
        assert zero["median_volume_20d_shares"] == 9
        assert writer.volume_history_event_count == 20
    finally:
        writer.close()

    guarded = _writer(tmp_path, "guarded")
    try:
        guarded._seed_cutoff = datetime(2020, 1, 1, tzinfo=_TAIPEI)
        with pytest.raises(ValueError, match="seed cutoff"):
            guarded._load_initial_volume_history(
                {"AAA": (("2020-01-02T08:30:00+08:00", 1),)}
            )
        future = _replay_one(
            guarded,
            decision_date="2020-01-03",
            event_date="2020-01-05",
            volume=1,
        )
        assert future["median_volume_20d_shares"] is None
        assert guarded.volume_history_future_event_count == 1
    finally:
        guarded.close()


def test_old_checkpoint_carry_is_not_reused_after_schema_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    year_directory = tmp_path / "year=2020"
    year_directory.mkdir()
    (year_directory / "manifest.json").write_text("{}", encoding="utf-8")
    old_carry = year_directory / "carry.state.gz"
    with gzip.open(old_carry, "wt", encoding="utf-8") as stream:
        stream.write(
            '{"scope":"stock","entity_key":"AAA",'
            '"feature_id":"legacy","value_int":1,"scale":1,'
            '"event_at":"2019-12-31T08:30:00+08:00",'
            '"available_at":"2019-12-31T08:30:00+08:00",'
            '"formal_training_eligible":true,"missing_mask":false,'
            '"quality_blocked_mask":false,"source_value_hash":"sha256:'
            + "a" * 64
            + '"}\n'
        )
    monkeypatch.setattr(
        "data_module.portfolio_ml_direct_numeric_store.store_module"
        "._verify_year_directory",
        lambda **_: True,
    )

    assert _checkpointed_year_is_valid(
        year_directory=year_directory,
        checkpoint_entry={
            "manifest_hash": "sha256:" + "b" * 64,
            "manifest_file_hash": "sha256:" + "c" * 64,
            "carry_file_hash": "sha256:" + "d" * 64,
        },
    ) is False
