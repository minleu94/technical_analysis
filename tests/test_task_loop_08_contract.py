"""TASK-LOOP-08 的唯讀觀測、訂閱生命週期與跨閉環整合契約。"""

import json
import threading
from datetime import datetime, timezone

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Slot
from PySide6.QtWidgets import QApplication

from app_module.dtos.runtime_dtos import GovernanceSeverity, RuntimeEventDTO
from app_module.runtime_services.event_bus import EventBus
from app_module.runtime_services.runtime_controller import RuntimeController
from app_module.runtime_services.snapshot_service import RuntimeSnapshotService
from runtime.store.local_file_store import LocalFileStore
from ui_qt.bridges.runtime_event_bridge import QtRuntimeBridge
from ui_qt.views.runtime_view import RuntimeView


def test_mainwindow_composition_injects_saved_recommendation_without_writer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app_module.decision_desk_service import SavedRecommendationDeskProvider
    import ui_qt.main as main_module

    settings = SimpleNamespace(output_root=tmp_path)
    builder = SimpleNamespace()
    composition = SimpleNamespace(builder=builder, market_frame_loader=object())
    monkeypatch.setattr(main_module, "build_decision_desk_composition", lambda **kwargs: composition)
    window = SimpleNamespace(config=settings, regime_service=None, portfolio_service=None, watchlist_service=None)
    result = main_module.MainWindow._create_decision_desk_builder(window)
    assert result is builder
    assert isinstance(result.recommendation_provider, SavedRecommendationDeskProvider)
    assert not (tmp_path / "recommendation").exists()
    assert not hasattr(result, "portfolio_ledger_provider")


def test_saved_recommendation_loop_survives_workbench_source_reload(tmp_path):
    from dataclasses import replace
    from datetime import date
    from hashlib import sha256
    from app_module.dtos import RecommendationResultDTO
    from app_module.recommendation_repository import RecommendationRepository
    from app_module.decision_desk_service import DecisionDeskSnapshotBuilder, SavedRecommendationDeskProvider
    from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
    from app_module.workbench_source_service import WorkbenchSourceService
    from data_module.config import TWStockConfig

    settings = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "artifacts")
    recommendations = RecommendationRepository(settings)
    recommendations.save_result(RecommendationResultDTO("frozen-id", "fixture", {}, [],
        run_context={"schema_version": "recommendation-context.v1", "as_of_date": "2026-05-20",
                     "profile_id": "fixture-profile", "data_fingerprint": "sha256:known"}), "fixture")
    builder = DecisionDeskSnapshotBuilder(recommendation_provider=SavedRecommendationDeskProvider(settings))
    snapshot = builder.build_snapshot(date(2026, 5, 20))
    snapshot = replace(snapshot, source_lineage={**snapshot.source_lineage,
        "portfolio_ledger": {"source_ledger_hash": "sha256:fixture", "candidate_only": True, "quality": "blocked"}})
    repository = DecisionDeskSnapshotRepository(settings)
    repository.save_loop_snapshot(snapshot)
    before = sha256(settings.db_file.read_bytes()).hexdigest()
    loaded, diagnostics = WorkbenchSourceService(settings)._load_decision_snapshot("2026-05-20")
    assert diagnostics == []
    assert loaded.recommendations == snapshot.recommendations
    assert loaded.source_lineage == snapshot.source_lineage
    assert loaded.recommendations.result_id == "frozen-id"
    assert loaded.recommendations.context["data_fingerprint"] == "sha256:known"
    assert sha256(settings.db_file.read_bytes()).hexdigest() == before


def test_workbench_rejects_future_recommendation_inside_saved_loop(tmp_path):
    from datetime import date
    import sqlite3
    from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
    from app_module.decision_desk_snapshot_repository import DecisionDeskSnapshotRepository
    from app_module.workbench_source_service import WorkbenchSourceService
    from data_module.config import TWStockConfig

    settings = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "artifacts")
    saved = DecisionDeskSnapshotRepository(settings).save_loop_snapshot(
        DecisionDeskSnapshotBuilder().build_snapshot(date(2026, 5, 20)))
    altered = saved.metadata_json
    altered["loop_snapshot"]["recommendations"] = {"as_of_date": "2026-05-21", "quality": "observed"}
    with sqlite3.connect(settings.db_file) as conn:
        conn.execute("UPDATE decision_desk_snapshots SET metadata_json = ?", (json.dumps(altered),))
    loaded, diagnostics = WorkbenchSourceService(settings)._load_decision_snapshot("2026-05-20")
    assert loaded is None
    assert any("decision_desk_snapshot_degraded" in item for item in diagnostics)


def _event(event_id="e-1"):
    return RuntimeEventDTO(
        event_id=event_id,
        timestamp=datetime(2026, 9, 6, tzinfo=timezone.utc),
        actor="fixture",
        event_type="validation_passed",
        severity=GovernanceSeverity.INFO,
        human_readable_message="隔離測試事件",
    )


@pytest.mark.parametrize("raw", [None, "{", "[]", "{}"])
def test_missing_or_invalid_task_never_becomes_observed_idle(tmp_path, raw):
    store = LocalFileStore(str(tmp_path))
    if raw is not None:
        path = tmp_path / "state" / "current_task.json"
        path.parent.mkdir()
        path.write_text(raw, encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    snapshot = RuntimeSnapshotService(store).get_snapshot()

    assert snapshot.task_status == "UNKNOWN"
    assert snapshot.task_read_state != "observed"
    assert snapshot.diagnostics
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_snapshot_retains_unrecognized_status_and_rejects_invalid_context(tmp_path):
    path = tmp_path / "state"
    path.mkdir()
    (path / "current_task.json").write_text(
        json.dumps({"objective": "隔離任務", "status": "unrecognized"}), encoding="utf-8"
    )
    (path / "runtime_context.json").write_text(
        json.dumps({"active_files": "private.py"}), encoding="utf-8"
    )
    snapshot = RuntimeSnapshotService(LocalFileStore(str(tmp_path))).get_snapshot()
    assert snapshot.task_status == "UNKNOWN"
    assert snapshot.raw_task_status == "unrecognized"
    assert snapshot.active_context_files == []
    assert snapshot.context_read_state == "degraded"


def test_task_read_failure_is_visible_and_does_not_stop_other_observation_planes(tmp_path, monkeypatch):
    controller = RuntimeController(str(tmp_path / "runtime"), scheduled_output_root=tmp_path / "scheduled")

    def cannot_read():
        raise PermissionError("fixture_permission_denied")

    monkeypatch.setattr(controller.store, "read_current_task", cannot_read)
    states = []
    scheduled = []
    controller.event_bus.subscribe_state(states.append)
    controller.event_bus.subscribe_scheduled_operations(scheduled.append)
    controller.poll_updates()
    assert states[0].task_status == "UNKNOWN"
    assert states[0].task_read_state == "unavailable"
    assert "runtime_task_read_failed:PermissionError" in states[0].diagnostics
    assert len(scheduled) == 1
    assert not list(tmp_path.iterdir())


def test_subscriber_can_detach_during_publish_without_skipping_next_observer():
    bus = EventBus()
    received = []

    def first(event):
        received.append(("first", event.event_id))
        unsubscribe()

    unsubscribe = bus.subscribe_events(first)
    bus.subscribe_events(lambda event: received.append(("second", event.event_id)))
    bus.publish_event(_event())
    unsubscribe()
    bus.publish_event(_event("e-2"))
    assert received == [("first", "e-1"), ("second", "e-1"), ("second", "e-2")]


@pytest.mark.parametrize("channel,publisher", [
    ("events", "event"), ("state", "state"), ("health", "health"),
    ("scheduled_operations", "scheduled_operations"),
    ("environment_readiness", "environment_readiness"),
])
def test_each_observation_plane_has_independent_idempotent_unsubscribe(channel, publisher):
    bus = EventBus()
    received = []
    cancel_first = getattr(bus, f"subscribe_{channel}")(received.append)
    cancel_second = getattr(bus, f"subscribe_{channel}")(received.append)
    cancel_first()
    cancel_first()
    marker = object()
    getattr(bus, f"publish_{publisher}")(marker)
    assert received == [marker]
    cancel_second()
    getattr(bus, f"publish_{publisher}")(marker)
    assert received == [marker]


def test_bridge_dispose_unsubscribes_and_worker_event_reaches_qt_thread():
    app = QApplication.instance() or QApplication([])
    bus = EventBus()
    bridge = QtRuntimeBridge(bus)

    class Receiver(QObject):
        def __init__(self):
            super().__init__()
            self.received = []

        @Slot(object)
        def receive(self, event):
            self.received.append((event.event_id, QThread.currentThread()))

    receiver = Receiver()
    bridge.event_received.connect(receiver.receive)
    worker = threading.Thread(target=lambda: bus.publish_event(_event()))
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert not receiver.received
    app.processEvents()
    assert receiver.received == [("e-1", app.thread())]
    bridge.dispose()
    bridge.dispose()
    bus.publish_event(_event("e-2"))
    app.processEvents()
    assert len(receiver.received) == 1


def test_destroyed_bridge_detaches_without_touching_the_event_source():
    app = QApplication.instance() or QApplication([])
    bus = EventBus()
    bridge = QtRuntimeBridge(bus)
    received = []
    bridge.event_received.connect(received.append)
    bridge.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    bus.publish_event(_event())
    assert received == []


def test_unknown_state_ui_keeps_read_diagnostic_visible(tmp_path):
    app = QApplication.instance() or QApplication([])
    view = RuntimeView()
    snapshot = RuntimeSnapshotService(LocalFileStore(str(tmp_path))).get_snapshot()
    view.on_state_updated(snapshot)
    assert "未知" in view.status_label.text()
    assert "閒置" not in view.status_label.text()
    assert "missing_or_unreadable" in view.status_label.toolTip()
    assert "來源未確認" in view.context_text.toPlainText()
    view.close()
    app.processEvents()


def test_controller_deduplicates_identical_ids_but_reports_conflicting_payload(tmp_path):
    controller = RuntimeController(str(tmp_path))
    controller.store.append_event({"event_id": "historical"})
    received = []
    controller.event_bus.subscribe_events(received.append)
    controller.poll_updates()
    event = {"event_id": "e-1", "event_type": "validation_passed"}
    controller.store.append_event(event)
    controller.store.append_event(event)
    controller.store.append_event({**event, "event_type": "validation_rejected"})
    controller.poll_updates()
    assert [e.event_type for e in received] == ["validation_passed", "validation_rejected"]
    assert "runtime_event_id_conflict:e-1" in controller.runtime_event_diagnostics
    before = (tmp_path / "events" / "runtime_events.jsonl").read_bytes()
    restarted = RuntimeController(str(tmp_path))
    restarted.event_bus.subscribe_events(received.append)
    restarted.poll_updates()
    assert len(received) == 2
    assert (tmp_path / "events" / "runtime_events.jsonl").read_bytes() == before


def test_runtime_qa_failure_is_nonzero_and_restores_caller_roots(tmp_path, monkeypatch):
    import os
    import scripts.qa_validate_runtime_loop as runtime_qa

    monkeypatch.setenv("DATA_ROOT", "caller-data-must-not-be-used")
    monkeypatch.setenv("OUTPUT_ROOT", "caller-output-must-not-be-used")

    def fail_fixture_check(root):
        assert os.environ["DATA_ROOT"] == str(root / "data")
        assert os.environ["OUTPUT_ROOT"] == str(root / "artifacts")
        raise OSError("fixture_failure")

    monkeypatch.setattr(runtime_qa, "run_checks", fail_fixture_check)
    report = tmp_path / "failed-report.json"
    assert runtime_qa.main(["--output-json", str(report)]) == 1
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "failed"
    assert os.environ["DATA_ROOT"] == "caller-data-must-not-be-used"
    assert os.environ["OUTPUT_ROOT"] == "caller-output-must-not-be-used"
