"""TASK-LOOP-08-A 隔離 Runtime 觀測 QA；只用自建 fixture，不啟動任何 task。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@contextmanager
def isolated_environment(root: Path) -> Iterator[dict[str, str]]:
    values = {
        "DATA_ROOT": str(root / "data"),
        "OUTPUT_ROOT": str(root / "artifacts"),
        "PROFILE": "test",
        "QT_QPA_PLATFORM": "offscreen",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield values
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


def run_checks(root: Path) -> dict[str, object]:
    from PySide6.QtWidgets import QApplication
    from app_module.runtime_services.health_service import RuntimeHealthService
    from app_module.runtime_services.runtime_controller import RuntimeController
    from app_module.runtime_services.snapshot_service import RuntimeSnapshotService
    from ui_qt.bridges.runtime_event_bridge import QtRuntimeBridge
    from ui_qt.views.runtime_view import RuntimeView

    checks: list[str] = []
    source = root / "data" / "runtime"
    events_file = source / "events" / "runtime_events.jsonl"
    events_file.parent.mkdir(parents=True)
    events_file.write_text('{"event_id":"historical"}\n', encoding="utf-8")
    controller = RuntimeController(str(source), scheduled_output_root=root / "artifacts" / "scheduled")
    app = QApplication.instance() or QApplication([])
    bridge = QtRuntimeBridge(controller.event_bus)
    view = RuntimeView()
    bridge.state_updated.connect(view.on_state_updated)
    bridge.event_received.connect(view.on_event_received)
    received = []
    bridge.event_received.connect(received.append)
    try:
        before = _inventory(root)
        controller.poll_updates()
        if received or _inventory(root) != before:
            raise AssertionError("啟動 observer 不得重播舊事件或改寫來源")
        if "未知" not in view.status_label.text():
            raise AssertionError("缺狀態來源不得呈現閒置")
        checks.extend(("restart_tail_attach_read_only", "missing_task_is_unknown"))

        event = {"event_id": "qa-event", "timestamp": "2099-01-01T00:00:00+00:00", "event_type": "validation_rejected", "severity": "CRITICAL"}
        raw = json.dumps(event)
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write(raw)
        before = _inventory(root)
        controller.poll_updates()
        if received or _inventory(root) != before:
            raise AssertionError("半行事件不得發布或由 observer 修復")
        checks.append("partial_line_waits_without_write")
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write("\n" + raw + "\n")
        before = _inventory(root)
        controller.poll_updates()
        if len(received) != 1 or _inventory(root) != before:
            raise AssertionError("完整同 ID 事件須去重且來源不變")
        checks.append("event_identity_deduplicated_read_only")

        health = RuntimeHealthService(
            controller.store, now_provider=lambda: datetime(2026, 9, 6, tzinfo=timezone.utc)
        ).get_health_snapshot()
        if health.future_event_count != 2 or health.observation_scope != "timestamp_future":
            raise AssertionError("未來事件不得作目前治理失敗判定")
        checks.append("future_event_excluded_from_current_health")

        state_path = source / "state" / "current_task.json"
        state_path.parent.mkdir()
        state_path.write_text("[]", encoding="utf-8")
        snapshot = RuntimeSnapshotService(controller.store).get_snapshot()
        if snapshot.task_status != "UNKNOWN" or not snapshot.diagnostics:
            raise AssertionError("非 object task 必須明示未知與診斷")
        checks.append("invalid_task_diagnostic")

        bridge.dispose()
        before = _inventory(root)
        controller.poll_updates()
        if _inventory(root) != before:
            raise AssertionError("解除訂閱後輪詢不得修改來源")
        checks.append("disposed_observer_stays_read_only")
        return {
            "status": "passed", "scope": "TASK-LOOP-08-A", "checks": checks,
            "source_hashes": before, "fixture_only": True, "source_unchanged": True,
            "production_scheduler_allowed": False, "task_execution_allowed": False,
            "upstream_integration": "not_evaluated_by_observer_only_qa",
        }
    finally:
        bridge.dispose()
        view.close()
        app.processEvents()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=PROJECT_ROOT / "output" / "qa" / "runtime_loop" / "report.json")
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="baldr_task_loop_08_") as directory:
            with isolated_environment(Path(directory)) as environment:
                result = run_checks(Path(directory))
                result["isolation"] = {**environment, "config_instantiated": False}
    except Exception as exc:
        result = {"status": "failed", "scope": "TASK-LOOP-08-A", "error": f"{type(exc).__name__}: {exc}"}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
