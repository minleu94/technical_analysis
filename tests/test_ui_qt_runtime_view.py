import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.dtos.runtime_dtos import (
    GovernanceSeverity,
    RuntimeEventDTO,
    RuntimeHealthSnapshotDTO,
    RuntimeState,
    RuntimeStateSnapshotDTO,
    ScheduledOperationStatusDTO,
    ScheduledOperationsSnapshotDTO,
)
from ui_qt.views.runtime_view import MAX_RENDERED_RUNTIME_EVENTS, RuntimeView


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
    assert "OUTPUT_ROOT/scheduled" in view.scope_label.text()
    assert "Windows Task Scheduler" in view.scope_label.text()
    assert "營運排程" in view.operations_group.title()
    assert "本次開啟後" in view.events_group.title()


def test_runtime_scope_note_is_compact_and_content_starts_near_top():
    app()
    view = RuntimeView()

    assert view.scope_label.maximumHeight() <= 48
    assert hasattr(view, "main_splitter")
    assert view.main_splitter.minimumHeight() >= 360


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
    assert "不代表日常營運排程或主 App 一般功能失敗" in view.health_scope_note_label.text()


def test_runtime_event_stream_shows_chinese_summary_and_raw_tooltip():
    app()
    view = RuntimeView()
    dto = make_runtime_event_dto()

    view.on_event_received(dto)

    item = view.event_list.item(0)
    assert "驗證拒絕" in item.text()
    assert "JSON 格式錯誤" in item.text()
    assert "validation_rejected" in item.toolTip()


def test_runtime_view_renders_operation_status_without_claiming_scheduler_state():
    app()
    view = RuntimeView()
    dto = ScheduledOperationsSnapshotDTO(
        overall_state="operational",
        core_ready_count=6,
        core_job_count=6,
        operations=(
            ScheduledOperationStatusDTO(
                job_id="data_update_quick",
                label="每日資料更新",
                raw_status="passed",
                state="operational",
                updated_at=datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc),
                lane="core",
                observed_at_source="checked_at",
                source_path="C:/output/scheduled/data_update_quick/latest_status.json",
            ),
            ScheduledOperationStatusDTO(
                job_id="ml_allocation_copilot",
                label="ML Shadow Co-pilot",
                raw_status="passed_rule_only",
                state="guarded",
                updated_at=datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc),
                lane="safety",
                diagnostic="ml_shadow_rule_only",
            ),
        ),
        observed_at=datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc),
    )

    view.on_scheduled_operations_updated(dto)

    assert "核心工作已就緒 6/6" in view.operations_summary_label.text()
    assert "每日資料更新｜正常｜passed" in view.operations_list.item(0).text()
    assert "ML Shadow Co-pilot｜安全邊界中｜passed_rule_only" in view.operations_list.item(1).text()
    assert "timestamp_source: checked_at" in view.operations_list.item(0).toolTip()


def test_runtime_view_does_not_render_historical_governance_event_as_current_halt():
    app()
    view = RuntimeView()
    dto = make_runtime_health_dto()
    dto.observation_scope = "historical_only"
    dto.current_state = RuntimeState.IDLE
    dto.historical_event_count = 1

    view.on_health_updated(dto)

    assert "僅有歷史治理事件" in view.health_state_label.text()
    assert "歷史事件：1" in view.rejection_rate_label.text()
    assert "最近歷史重大違規" in view.last_violation_label.text()


def test_runtime_event_list_keeps_bounded_recent_window():
    app()
    view = RuntimeView()

    for index in range(MAX_RENDERED_RUNTIME_EVENTS + 1):
        view.on_event_received(
            RuntimeEventDTO(
                event_id=str(index),
                timestamp=None,
                actor="runtime",
                event_type="test_start",
                severity=GovernanceSeverity.INFO,
                human_readable_message=str(index),
            )
        )

    assert view.event_list.count() == MAX_RENDERED_RUNTIME_EVENTS
    assert "：1" in view.event_list.item(0).text()


def test_runtime_view_shows_unreadable_event_log_as_not_current_health():
    app()
    view = RuntimeView()
    dto = RuntimeHealthSnapshotDTO(
        is_healthy=False,
        current_state=RuntimeState.IDLE,
        rejection_rate=0,
        rejection_rate_trend="STABLE",
        consecutive_failures=0,
        observation_scope="event_log_unreadable",
        event_log_read_state="unavailable",
        event_log_diagnostic="runtime_event_read_failed:PermissionError",
    )

    view.on_health_updated(dto)

    assert "治理事件檔無法讀取" in view.health_state_label.text()
    assert "事件檔：無法讀取" in view.rejection_rate_label.text()
    assert "PermissionError" in view.health_scope_note_label.text()
