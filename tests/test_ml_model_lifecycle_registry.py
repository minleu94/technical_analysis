from pathlib import Path

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
