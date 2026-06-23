import os
import sys
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.dtos.runtime_dtos import (
    GovernanceSeverity,
    RuntimeEventDTO,
    RuntimeHealthSnapshotDTO,
    RuntimeState,
    RuntimeStateSnapshotDTO,
)
from ui_qt.views.runtime_view import RuntimeView


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def make_runtime_health_dto(
    state: str = "HALTED",
    rejection_rate: float = 0.8,
    consecutive_failures: int = 4,
) -> RuntimeHealthSnapshotDTO:
    return RuntimeHealthSnapshotDTO(
        is_healthy=False,
        current_state=RuntimeState(state),
        rejection_rate=rejection_rate,
        rejection_rate_trend="UP",
        consecutive_failures=consecutive_failures,
        last_critical_violation=RuntimeEventDTO(
            event_id="evt-1",
            timestamp=datetime(2026, 6, 23, 9, 0, 0),
            actor="runtime",
            event_type="governance_violation",
            severity=GovernanceSeverity.CRITICAL,
            human_readable_message="GovernanceViolation",
            payload_preview={"raw": "value"},
        ),
    )


def make_runtime_event_dto(
    event_type: str = "validation_rejected",
    message: str = "JSONDecodeError",
) -> RuntimeEventDTO:
    return RuntimeEventDTO(
        event_id="evt-2",
        timestamp=datetime(2026, 6, 23, 9, 1, 0),
        actor="agent",
        event_type=event_type,
        severity=GovernanceSeverity.WARNING,
        human_readable_message=message,
        payload_preview={"exception": message},
    )


def test_runtime_view_static_labels_are_chinese_and_scope_is_explicit():
    app()
    view = RuntimeView()

    assert "任務狀態機" in view.state_group.title()
    assert "Runtime Observatory 不監控資料更新背景任務" in view.scope_label.text()
    assert "資料更新、回測與推薦長任務" in view.scope_label.text()


def test_runtime_state_snapshot_renders_chinese_idle_text():
    app()
    view = RuntimeView()
    dto = RuntimeStateSnapshotDTO(
        task_objective="No task assigned",
        task_status="IDLE",
        active_context_files=[],
    )

    view.on_state_updated(dto)

    assert "目前治理目標：尚未指派治理任務" in view.objective_label.text()
    assert "任務流程狀態：閒置" in view.status_label.text()


def test_runtime_health_halted_uses_red_warning_and_chinese_labels():
    app()
    view = RuntimeView()
    dto = make_runtime_health_dto()

    view.on_health_updated(dto)

    assert "治理暫停" in view.health_state_label.text()
    assert "驗證拒絕率：80.0%" in view.rejection_rate_label.text()
    assert "連續失敗次數：4" in view.rejection_rate_label.text()
    assert "治理規則違反" in view.last_violation_label.text()
    assert "不代表主 App 一般功能失敗" in view.health_scope_note_label.text()


def test_runtime_event_stream_shows_chinese_summary_and_raw_tooltip():
    app()
    view = RuntimeView()
    dto = make_runtime_event_dto()

    view.on_event_received(dto)

    item = view.event_list.item(0)
    assert "驗證拒絕" in item.text()
    assert "JSON 格式錯誤" in item.text()
    assert "validation_rejected" in item.toolTip()
