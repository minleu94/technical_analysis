from pathlib import Path
import threading

import pytest

from ml_module.model_lifecycle_registry import (
    ModelLifecycleEvent,
    ModelLifecycleRegistry,
    initialize_model_lifecycle_registry,
)


def _event(event_id: str, event_type: str) -> ModelLifecycleEvent:
    return ModelLifecycleEvent(
        event_id=event_id,
        model_id="model-1",
        event_type=event_type,
        created_at="2026-07-13T12:00:00+00:00",
        reason="fixture contract",
    )


def _pair() -> tuple[ModelLifecycleEvent, ModelLifecycleEvent]:
    return (
        _event("review-1", "review_required"),
        _event("disable-1", "disabled"),
    )


def test_constructor_and_read_do_not_create_registry(tmp_path: Path) -> None:
    db_path = tmp_path / "shadow" / "lifecycle.sqlite"
    registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")

    assert not db_path.exists()
    with pytest.raises(FileNotFoundError):
        registry.list_events("model-1")
    assert not db_path.exists()


def test_lifecycle_is_append_only_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_model_lifecycle_registry(db_path, data_root=tmp_path / "formal-data")
    registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")
    activated = _event("event-1", "activated_for_shadow")

    assert registry.append(activated) == "inserted"
    assert registry.append(activated) == "idempotent"
    with pytest.raises(ValueError, match="conflict"):
        registry.append(ModelLifecycleEvent(**{**activated.__dict__, "reason": "different"}))
    assert registry.current_status("model-1") == "activated_for_shadow"


def test_invalid_transition_preserves_previous_state(tmp_path: Path) -> None:
    db_path = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_model_lifecycle_registry(db_path, data_root=tmp_path / "formal-data")
    registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")

    with pytest.raises(ValueError, match="transition"):
        registry.append(_event("event-2", "superseded"))
    assert registry.list_events("model-1") == ()

    registry.append(_event("event-1", "activated_for_shadow"))
    registry.append(_event("event-3", "disabled"))
    assert registry.current_status("model-1") == "disabled"
    assert tuple(event.event_type for event in registry.list_events("model-1")) == (
        "activated_for_shadow",
        "disabled",
    )


def test_pair_append_rolls_back_mid_write_and_recovers_exact_prefix(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_model_lifecycle_registry(db_path, data_root=tmp_path / "formal-data")
    registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")
    registry.append(_event("event-1", "activated_for_shadow"))
    pair = _pair()

    original_insert = registry._insert_event
    calls = 0

    def fail_after_first(conn, event, payload_json) -> None:
        nonlocal calls
        calls += 1
        original_insert(conn, event, payload_json)
        if calls == 1:
            raise RuntimeError("injected lifecycle pair crash")

    monkeypatch.setattr(registry, "_insert_event", fail_after_first)
    with pytest.raises(RuntimeError, match="injected lifecycle pair crash"):
        registry.append_pair(pair)

    # The first pair row was attempted, but SQLite transaction rollback keeps
    # the registry at the activation prefix.
    assert tuple(event.event_type for event in registry.list_events("model-1")) == (
        "activated_for_shadow",
    )

    monkeypatch.setattr(registry, "_insert_event", original_insert)
    assert registry.append_pair(pair) == "inserted"
    assert tuple(event.event_type for event in registry.list_events("model-1")) == (
        "activated_for_shadow",
        "review_required",
        "disabled",
    )


def test_pair_append_recovers_legacy_prefix_and_replay_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_model_lifecycle_registry(db_path, data_root=tmp_path / "formal-data")
    registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")
    registry.append(_event("event-1", "activated_for_shadow"))
    pair = _pair()

    # A legacy two-step caller may have committed the decision before the
    # disabling evidence.  Recovery is allowed only for this exact prefix.
    assert registry.append(pair[0]) == "inserted"
    assert registry.append_pair(pair) == "recovered"
    assert registry.append_pair(pair) == "idempotent"
    assert len(registry.list_events("model-1")) == 3


def test_pair_append_rejects_contradictory_versions_and_suffix_only_state(tmp_path: Path) -> None:
    db_path = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_model_lifecycle_registry(db_path, data_root=tmp_path / "formal-data")
    registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")
    registry.append(_event("event-1", "activated_for_shadow"))
    pair = _pair()
    assert registry.append_pair(pair) == "inserted"

    changed_first = ModelLifecycleEvent(
        event_id=pair[0].event_id,
        model_id=pair[0].model_id,
        event_type=pair[0].event_type,
        created_at=pair[0].created_at,
        reason="different lifecycle evidence",
    )
    changed_second = ModelLifecycleEvent(
        event_id=pair[1].event_id,
        model_id=pair[1].model_id,
        event_type=pair[1].event_type,
        created_at=pair[1].created_at,
        reason="different lifecycle evidence",
    )
    changed_pair = (changed_first, changed_second)
    with pytest.raises(ValueError, match="conflict"):
        registry.append_pair(changed_pair)
    assert len(registry.list_events("model-1")) == 3

    other_db = tmp_path / "shadow" / "suffix-only.sqlite"
    initialize_model_lifecycle_registry(other_db, data_root=tmp_path / "formal-data")
    suffix_registry = ModelLifecycleRegistry(other_db, data_root=tmp_path / "formal-data")
    suffix_registry.append(_event("event-1", "activated_for_shadow"))
    assert suffix_registry.append(pair[1]) == "inserted"
    with pytest.raises(ValueError, match="non-recoverable suffix"):
        suffix_registry.append_pair(pair)
    assert tuple(event.event_type for event in suffix_registry.list_events("model-1")) == (
        "activated_for_shadow",
        "disabled",
    )


def test_single_writer_uses_same_lock_and_rechecks_state_after_pair_commit(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_model_lifecycle_registry(db_path, data_root=tmp_path / "formal-data")
    pair_registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")
    single_registry = ModelLifecycleRegistry(db_path, data_root=tmp_path / "formal-data")
    pair_registry.append(_event("event-1", "activated_for_shadow"))
    pair = _pair()
    first_written = threading.Event()
    release_pair = threading.Event()
    original_insert = pair_registry._insert_event

    def pause_after_first(conn, event, payload_json) -> None:
        original_insert(conn, event, payload_json)
        if event.event_id == pair[0].event_id:
            first_written.set()
            assert release_pair.wait(timeout=5)

    monkeypatch.setattr(pair_registry, "_insert_event", pause_after_first)
    pair_result: list[str] = []
    pair_error: list[BaseException] = []

    def append_pair_in_thread() -> None:
        try:
            pair_result.append(pair_registry.append_pair(pair))
        except BaseException as error:  # pragma: no cover - assertion below reports it
            pair_error.append(error)

    pair_thread = threading.Thread(target=append_pair_in_thread)
    pair_thread.start()
    assert first_written.wait(timeout=5)

    single_connected = threading.Event()
    single_begin_attempted = threading.Event()
    single_trace: list[str] = []
    original_connect = single_registry._connect_rw

    def connect_and_signal():
        connection = original_connect()
        def trace(statement: str) -> None:
            single_trace.append(statement)
            if statement == "BEGIN IMMEDIATE":
                single_begin_attempted.set()
        connection.set_trace_callback(trace)
        single_connected.set()
        return connection

    monkeypatch.setattr(single_registry, "_connect_rw", connect_and_signal)
    single_error: list[BaseException] = []

    def append_single_in_thread() -> None:
        try:
            single_registry.append(
                ModelLifecycleEvent(
                    event_id="stale-single",
                    model_id="model-1",
                    event_type="superseded",
                    created_at="2026-07-13T12:01:00+00:00",
                    reason="must observe disabled pair state",
                )
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            single_error.append(error)

    single_thread = threading.Thread(target=append_single_in_thread)
    single_thread.start()
    assert single_connected.wait(timeout=5)
    assert single_begin_attempted.wait(timeout=5)
    release_pair.set()
    pair_thread.join(timeout=5)
    single_thread.join(timeout=5)

    assert not pair_thread.is_alive()
    assert not single_thread.is_alive()
    assert pair_error == []
    assert pair_result == ["inserted"]
    assert len(single_error) == 1
    assert isinstance(single_error[0], ValueError)
    assert "invalid lifecycle transition: disabled -> superseded" in str(single_error[0])
    begin_index = single_trace.index("BEGIN IMMEDIATE")
    current_select_index = next(
        index
        for index, statement in enumerate(single_trace)
        if "SELECT event_id, event_type" in statement
    )
    assert begin_index < current_select_index
    assert tuple(event.event_type for event in single_registry.list_events("model-1")) == (
        "activated_for_shadow",
        "review_required",
        "disabled",
    )
