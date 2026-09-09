from __future__ import annotations

from pathlib import Path

import pytest

from ml_module.drift_champion_comparison import MLFeatureDriftResult
from ml_module.model_lifecycle_registry import (
    ModelLifecycleEvent,
    ModelLifecycleRegistry,
    initialize_model_lifecycle_registry,
)
from ml_module.shadow_monitoring_service import ShadowModelMonitoringService


def _registry(tmp_path: Path) -> ModelLifecycleRegistry:
    path = tmp_path / "shadow" / "lifecycle.sqlite"
    initialize_model_lifecycle_registry(path, data_root=tmp_path / "formal-data")
    registry = ModelLifecycleRegistry(path, data_root=tmp_path / "formal-data")
    registry.append(
        ModelLifecycleEvent(
            event_id="activate-model-1",
            model_id="model-1",
            event_type="activated_for_shadow",
            created_at="2026-07-13T10:00:00+00:00",
            reason="controlled fixture",
        )
    )
    return registry


def test_major_drift_appends_review_then_disable_and_stops_overlay(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    service = ShadowModelMonitoringService(registry)
    major = MLFeatureDriftResult("score_bp", 0.30, "major_drift", 100, 100)

    first = service.apply_drift_review(
        model_id="model-1",
        dataset_id="dataset-1",
        evaluated_at="2026-07-13T12:00:00+00:00",
        drift_results=(major,),
    )
    second = service.apply_drift_review(
        model_id="model-1",
        dataset_id="dataset-1",
        evaluated_at="2026-07-13T12:00:00+00:00",
        drift_results=(major,),
    )

    assert first == second
    assert first.status == "major_drift_disabled"
    assert first.overlay_allowed is False
    assert first.retrain_automatically is False
    assert first.auto_promotion_allowed is False
    assert first.formal_rule_unchanged is True
    assert first.production_action_allowed is False
    assert registry.current_status("model-1") == "disabled"
    assert tuple(event.event_type for event in registry.list_events("model-1")) == (
        "activated_for_shadow",
        "review_required",
        "disabled",
    )


def test_stable_drift_keeps_shadow_active_without_lifecycle_write(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    report = ShadowModelMonitoringService(registry).apply_drift_review(
        model_id="model-1",
        dataset_id="dataset-1",
        evaluated_at="2026-07-13T12:00:00+00:00",
        drift_results=(MLFeatureDriftResult("score_bp", 0.01, "stable", 100, 100),),
    )

    assert report.status == "stable"
    assert report.overlay_allowed is True
    assert len(registry.list_events("model-1")) == 1


def test_rollback_simulation_is_append_only_idempotent_and_preserves_rule_path(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    service = ShadowModelMonitoringService(registry)

    first = service.simulate_rollback(
        model_id="model-1",
        dataset_id="dataset-1",
        requested_at="2026-07-13T13:00:00+00:00",
        reason="operator fixture rollback",
    )
    second = service.simulate_rollback(
        model_id="model-1",
        dataset_id="dataset-1",
        requested_at="2026-07-13T13:00:00+00:00",
        reason="operator fixture rollback",
    )

    assert first == second
    assert first.status == "rollback_simulated_disabled"
    assert first.overlay_allowed is False
    assert first.formal_rule_unchanged is True
    assert first.production_action_allowed is False
    assert tuple(event.event_type for event in registry.list_events("model-1")) == (
        "activated_for_shadow",
        "rollback_requested",
        "disabled",
    )


def test_stable_drift_never_reenables_a_disabled_shadow_model(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    service = ShadowModelMonitoringService(registry)
    service.simulate_rollback(
        model_id="model-1",
        dataset_id="dataset-1",
        requested_at="2026-07-13T13:00:00+00:00",
        reason="operator fixture rollback",
    )

    report = service.apply_drift_review(
        model_id="model-1",
        dataset_id="dataset-1",
        evaluated_at="2026-07-14T12:00:00+00:00",
        drift_results=(MLFeatureDriftResult("score_bp", 0.01, "stable", 100, 100),),
    )

    assert report.status == "lifecycle_disabled"
    assert report.overlay_allowed is False
    assert report.formal_rule_unchanged is True


def test_monitoring_rollback_path_is_crash_consistent_and_recoverable(
    tmp_path: Path, monkeypatch
) -> None:
    registry = _registry(tmp_path)
    service = ShadowModelMonitoringService(registry)
    original_insert = registry._insert_event
    calls = 0

    def fail_after_first(conn, event, payload_json) -> None:
        nonlocal calls
        calls += 1
        original_insert(conn, event, payload_json)
        if calls == 1:
            raise RuntimeError("injected rollback evidence crash")

    monkeypatch.setattr(registry, "_insert_event", fail_after_first)
    with pytest.raises(RuntimeError, match="injected rollback evidence crash"):
        service.simulate_rollback(
            model_id="model-1",
            dataset_id="dataset-1",
            requested_at="2026-07-13T13:00:00+00:00",
            reason="operator fixture rollback",
        )
    assert tuple(event.event_type for event in registry.list_events("model-1")) == (
        "activated_for_shadow",
    )

    monkeypatch.setattr(registry, "_insert_event", original_insert)
    report = service.simulate_rollback(
        model_id="model-1",
        dataset_id="dataset-1",
        requested_at="2026-07-13T13:00:00+00:00",
        reason="operator fixture rollback",
    )
    assert report.status == "rollback_simulated_disabled"
    assert tuple(event.event_type for event in registry.list_events("model-1")) == (
        "activated_for_shadow",
        "rollback_requested",
        "disabled",
    )
