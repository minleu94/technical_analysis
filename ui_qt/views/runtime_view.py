from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTextEdit, QLabel, QListWidget, QGroupBox, QListWidgetItem, QSizePolicy,
    QScrollArea, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui_qt.widgets.info_button import InfoButton
from ui_qt.widgets.theme_widgets import EmptyStatePanel
from ui_qt.theme import MIDNIGHT_ANALYST
from app_module.dtos.runtime_dtos import (
    RuntimeStateSnapshotDTO,
    RuntimeHealthSnapshotDTO,
    RuntimeEventDTO,
    ScheduledOperationsSnapshotDTO,
    EnvironmentReadinessSnapshotDTO,
)

STATE_LABELS = {
    "IDLE": "閒置",
    "DISPATCHED": "已派發",
    "THINKING": "思考中",
    "VALIDATING": "驗證中",
    "APPROVED": "已核准",
    "ERROR": "錯誤",
    "RECOVERY": "復原中",
    "HALTED": "治理暫停",
}

EVENT_LABELS = {
    "test_start": "測試開始",
    "agent_output_received": "收到 agent 輸出",
    "validation_passed": "驗證通過",
    "validation_rejected": "驗證拒絕",
    "governance_violation": "治理規則違反",
}

ERROR_LABELS = {
    "JSONDecodeError": "JSON 格式錯誤",
    "SchemaViolation": "Schema 違規",
    "GovernanceViolation": "治理規則違反",
}

SEVERITY_LABELS = {
    "INFO": "資訊",
    "WARNING": "警告",
    "CRITICAL": "重大",
}

OPERATION_STATE_LABELS = {
    "operational": "正常",
    "guarded": "安全邊界中",
    "attention": "需要注意",
    "unavailable": "無法判定",
    "observed": "已觀測",
}
MAX_RENDERED_RUNTIME_EVENTS = 500
DEFAULT_HEALTH_SCOPE_NOTE = (
    "治理暫停或拒絕率升高只代表 agent / governance workflow 狀態，"
    "不代表日常營運排程或主 App 一般功能失敗。"
)
EVENT_LOG_READ_STATE_LABELS = {
    "observed": "已讀取",
    "missing": "尚未建立",
    "degraded": "部分無法解析",
    "unavailable": "無法讀取",
}
ENVIRONMENT_STATE_LABELS = {
    "ready": "可用",
    "attention": "需要處理",
    "unavailable": "無法使用",
}
ENVIRONMENT_PATH_STATE_LABELS = {
    "ready": "可用",
    "ready_to_create": "待建立（不由此頁建立）",
    "attention": "需要處理",
    "unavailable": "無法使用",
}


class RuntimeView(QWidget):
    """
    Pure Render UI component for the Runtime Observatory.
    This view strictly depends ONLY on DTOs and has zero business logic or direct file IO.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # Runtime is also reachable from a narrow desktop viewport. Several
        # diagnostic labels/lists contain long paths and naturally report a
        # large horizontal size hint; if that hint is allowed to bubble up,
        # QMainWindow can refuse a 390 px resize before the navigation has a
        # chance to collapse. Keep the page horizontally yieldable and let
        # wrapped labels / list scrollbars handle the content at the actual
        # viewport width.
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.content_scroll = QScrollArea(self)
        self.content_scroll.setObjectName("runtimeContentScroll")
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        content_widget = QWidget()
        content_widget.setObjectName("runtimeContentWidget")
        content_widget.setMinimumWidth(0)
        content_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.content_widget = content_widget
        outer_layout.addWidget(self.content_scroll)
        self.content_scroll.setWidget(content_widget)

        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(10, 8, 10, 10)
        main_layout.setSpacing(6)

        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("Owner 營運與治理監控")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("runtime_observatory", self)
        title_layout.addWidget(info_btn)
        main_layout.addLayout(title_layout)

        self.scope_label = QLabel(
            "上方營運排程只讀取 OUTPUT_ROOT/scheduled 的已保存狀態；它不代表 Windows Task Scheduler 正在執行或已註冊。"
        )
        self.scope_label.setWordWrap(True)
        self.scope_label.setMaximumHeight(44)
        self.scope_label.setMinimumWidth(0)
        self.scope_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.scope_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 6px 8px;"
        )
        main_layout.addWidget(self.scope_label)

        self.environment_group = QGroupBox("正式路徑環境（唯讀診斷）")
        self.environment_group.setMinimumWidth(0)
        self.environment_group.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        environment_layout = QVBoxLayout(self.environment_group)
        self.environment_summary_label = QLabel("路徑能力：尚未讀取")
        self.environment_summary_label.setMinimumWidth(0)
        self.environment_summary_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        self.environment_summary_label.setStyleSheet("font-weight: bold;")
        self.environment_detail_label = QLabel(
            "只檢查既有路徑與 os.access hint；不建立目錄、不建立 probe 檔、不初始化 SQLite。"
        )
        self.environment_detail_label.setWordWrap(True)
        self.environment_detail_label.setMinimumWidth(0)
        self.environment_detail_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        self.environment_list = QListWidget()
        self.environment_list.setMinimumWidth(0)
        self.environment_list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.environment_list.setMaximumHeight(116)
        environment_layout.addWidget(self.environment_summary_label)
        environment_layout.addWidget(self.environment_detail_label)
        environment_layout.addWidget(self.environment_list)
        main_layout.addWidget(self.environment_group)

        self.operations_group = QGroupBox("營運排程（OUTPUT_ROOT／唯讀）")
        self.operations_group.setMinimumWidth(0)
        self.operations_group.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        operations_layout = QVBoxLayout(self.operations_group)
        self.operations_summary_label = QLabel("日常營運：尚未讀取已保存排程狀態")
        self.operations_summary_label.setMinimumWidth(0)
        self.operations_summary_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        self.operations_summary_label.setStyleSheet("font-weight: bold;")
        self.operations_detail_label = QLabel(
            "核心資料更新、推薦與 Paper Portfolio 與治理 Runtime 分開判讀；ML blocked / rule-only 可能是預期安全邊界。"
        )
        self.operations_detail_label.setWordWrap(True)
        self.operations_detail_label.setMinimumWidth(0)
        self.operations_detail_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        self.operations_list = QListWidget()
        self.operations_list.setMinimumWidth(0)
        self.operations_list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.operations_list.setMaximumHeight(142)
        operations_layout.addWidget(self.operations_summary_label)
        operations_layout.addWidget(self.operations_detail_label)
        operations_layout.addWidget(self.operations_list)
        main_layout.addWidget(self.operations_group)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setMinimumWidth(0)
        splitter.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        splitter.setMinimumHeight(360)
        self.main_splitter = splitter

        # ---------------------------------------------------------
        # Left Panel: FSM State & Context Overview
        # ---------------------------------------------------------
        left_panel = QWidget()
        left_panel.setMinimumWidth(0)
        left_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left_layout = QVBoxLayout(left_panel)

        self.state_group = QGroupBox("任務狀態機")
        state_layout = QVBoxLayout(self.state_group)
        self.objective_label = QLabel("目前治理目標：尚未指派治理任務")
        self.status_label = QLabel("任務流程狀態：閒置")
        for label in (self.objective_label, self.status_label):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        # Apply CSS for clear visual boundaries
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        state_layout.addWidget(self.objective_label)
        state_layout.addWidget(self.status_label)

        self.context_group = QGroupBox("Runtime Context 環境")
        ctx_layout = QVBoxLayout(self.context_group)
        self.context_text = QTextEdit()
        self.context_text.setReadOnly(True)
        self.context_text.setMinimumWidth(0)
        self.context_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.context_text.setPlaceholderText("尚無 Runtime context。治理任務啟動後，這裡會顯示目前載入的上下文檔案。")
        ctx_layout.addWidget(self.context_text)

        left_layout.addWidget(self.state_group)
        left_layout.addWidget(self.context_group)

        # ---------------------------------------------------------
        # Right Panel: Governance Observability & Event Stream
        # ---------------------------------------------------------
        right_panel = QWidget()
        right_panel.setMinimumWidth(0)
        right_panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        right_layout = QVBoxLayout(right_panel)

        self.health_group = QGroupBox("治理 Runtime（獨立於日常排程）")
        health_layout = QVBoxLayout(self.health_group)
        self.health_state_label = QLabel("整體治理狀態：未知")
        self.rejection_rate_label = QLabel("驗證拒絕率：0.0%（穩定）｜連續失敗次數：0")
        self.last_violation_label = QLabel("最近重大違規：無")
        for label in (
            self.health_state_label,
            self.rejection_rate_label,
            self.last_violation_label,
        ):
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.last_violation_label.setStyleSheet("color: red; font-weight: bold;")
        self.health_scope_note_label = QLabel(DEFAULT_HEALTH_SCOPE_NOTE)
        self.health_scope_note_label.setWordWrap(True)
        self.health_scope_note_label.setMinimumWidth(0)
        self.health_scope_note_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )

        health_layout.addWidget(self.health_state_label)
        health_layout.addWidget(self.rejection_rate_label)
        health_layout.addWidget(self.last_violation_label)
        health_layout.addWidget(self.health_scope_note_label)

        self.events_group = QGroupBox("本次開啟後的治理事件流")
        events_layout = QVBoxLayout(self.events_group)
        self.event_empty_state = EmptyStatePanel(
            "尚無 Runtime 事件",
            "本次開啟後，治理 workflow 產生的事件會依時間順序顯示在下方；這不是完整歷史稽核查詢。"
        )
        events_layout.addWidget(self.event_empty_state)
        self.event_list = QListWidget()
        self.event_list.setMinimumWidth(0)
        self.event_list.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        events_layout.addWidget(self.event_list)

        right_layout.addWidget(self.health_group)
        right_layout.addWidget(self.events_group)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)

        # 40% / 60% split ratio
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        main_layout.addWidget(splitter, 1)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """窄版把治理雙欄改成單欄，避免文字被切在 viewport 外。"""

        super().resizeEvent(event)
        splitter = getattr(self, "main_splitter", None)
        if splitter is None:
            return

        desired_orientation = Qt.Vertical if self.width() < 720 else Qt.Horizontal
        if splitter.orientation() != desired_orientation:
            splitter.setOrientation(desired_orientation)
            splitter.updateGeometry()

    def on_state_updated(self, dto: RuntimeStateSnapshotDTO) -> None:
        """Pure rendering slot for State Snapshot DTO"""
        objective = dto.task_objective
        if not objective or objective == "No task assigned":
            objective = "尚未指派治理任務"
        status = STATE_LABELS.get(str(dto.task_status), str(dto.task_status))
        self.objective_label.setText(f"目前治理目標：{objective}")
        self.status_label.setText(f"任務流程狀態：{status}")

        ctx_text = "目前上下文檔案：\n" + "\n".join(dto.active_context_files)
        self.context_text.setText(ctx_text)

    def on_health_updated(self, dto: RuntimeHealthSnapshotDTO) -> None:
        """Pure rendering slot for Health Analytics DTO"""
        if dto.observation_scope != "current":
            self._render_noncurrent_governance_health(dto)
            return

        state_value = dto.current_state.value
        state_label = STATE_LABELS.get(state_value, state_value)
        high_risk = (
            state_value in {"ERROR", "HALTED"}
            or dto.rejection_rate >= 0.5
            or dto.consecutive_failures >= 3
            or not dto.is_healthy
        )
        state_color = "red" if high_risk else "green"
        self.health_state_label.setText(f"整體治理狀態：<font color='{state_color}'>{state_label}</font>")
        self.health_state_label.setStyleSheet("font-weight: bold;" if high_risk else "")

        rate_pct = dto.rejection_rate * 100
        trend_arrow = "↑" if dto.rejection_rate_trend == "UP" else ("↓" if dto.rejection_rate_trend == "DOWN" else "→")
        self.rejection_rate_label.setText(
            f"驗證拒絕率：{rate_pct:.1f}%（{trend_arrow}）｜連續失敗次數：{dto.consecutive_failures}"
            + (f"｜未來時間事件：{dto.future_event_count}" if dto.future_event_count else "")
            + self._event_log_read_suffix(dto)
        )
        self.health_scope_note_label.setText(
            DEFAULT_HEALTH_SCOPE_NOTE + self._event_log_read_note(dto)
        )

        if dto.last_critical_violation:
            msg = self._localize_message(dto.last_critical_violation.human_readable_message)
            self.last_violation_label.setText(f"最近重大違規：{msg}")
        else:
            self.last_violation_label.setText("最近重大違規：無")

    def on_scheduled_operations_updated(self, dto: ScheduledOperationsSnapshotDTO) -> None:
        """純渲染已保存的日常營運狀態；不呼叫排程或資料更新。"""
        overall_label = "正常" if dto.overall_state == "operational" else "需要注意"
        self.operations_summary_label.setText(
            f"日常營運：{overall_label}｜核心工作已就緒 {dto.core_ready_count}/{dto.core_job_count}"
        )
        self.operations_list.clear()
        for operation in dto.operations:
            state_label = OPERATION_STATE_LABELS.get(operation.state, operation.state)
            updated_text = (
                operation.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")
                if operation.updated_at is not None
                else "未知"
            )
            item = QListWidgetItem(
                f"{operation.label}｜{state_label}｜{operation.raw_status}｜{updated_text}"
            )
            item.setToolTip(
                "\n".join(
                    (
                        f"job: {operation.job_id}",
                        f"lane: {operation.lane}",
                        f"read_state: {operation.read_state}",
                        f"timestamp_source: {operation.observed_at_source}",
                        f"source: {operation.source_path}",
                        f"diagnostic: {operation.diagnostic or 'none'}",
                    )
                )
            )
            self.operations_list.addItem(item)

    def on_environment_readiness_updated(
        self,
        dto: EnvironmentReadinessSnapshotDTO,
    ) -> None:
        """純渲染正式路徑能力；不在 UI 嘗試建立或修復任何路徑。"""
        state_label = ENVIRONMENT_STATE_LABELS.get(dto.overall_state, dto.overall_state)
        ready_count = sum(item.status in {"ready", "ready_to_create"} for item in dto.paths)
        self.environment_summary_label.setText(
            f"路徑能力：{state_label}｜可用或待建立 {ready_count}/{len(dto.paths)}"
        )
        probe_text = dto.write_probe.replace("_", " / ")
        self.environment_detail_label.setText(
            "只讀取既有路徑與 os.access hint；若已有 logger／Registry 檔案，另嘗試開啟寫入 handle（不寫入內容）；不建立目錄、不建立 probe 檔、不初始化 SQLite。"
            + (f"\nWrite probe：{probe_text}。" if dto.write_probe else "")
            + (f"\n診斷：{'、'.join(dto.diagnostics)}" if dto.diagnostics else "")
        )
        self.environment_list.clear()
        for path_status in dto.paths:
            status_label = ENVIRONMENT_PATH_STATE_LABELS.get(
                path_status.status,
                path_status.status,
            )
            readable = "是" if path_status.readable else "否"
            writable = (
                "未知"
                if path_status.writable is None
                else ("是" if path_status.writable else "否")
            )
            item = QListWidgetItem(
                f"{path_status.label}｜{status_label}｜讀 {readable}｜寫 {writable}"
            )
            item.setToolTip(
                "\n".join(
                    (
                        f"path: {path_status.path}",
                        f"kind: {path_status.kind}",
                        f"exists: {path_status.exists}",
                        f"parent_exists: {path_status.parent_exists}",
                        f"requires_write: {path_status.requires_write}",
                        f"diagnostic: {path_status.diagnostic or 'none'}",
                    )
                )
            )
            self.environment_list.addItem(item)

    def _render_noncurrent_governance_health(
        self,
        dto: RuntimeHealthSnapshotDTO,
    ) -> None:
        if dto.observation_scope == "historical_only":
            state_label = "僅有歷史治理事件"
            detail = "目前未觀測到活躍治理 Runtime；歷史事件不能用來判定今天的營運狀態。"
        elif dto.observation_scope == "timestamp_invalid":
            state_label = "治理事件時間無法解析"
            detail = "治理事件缺少可信時間，不能用來判定目前狀態。"
        elif dto.observation_scope == "timestamp_future":
            state_label = "治理事件時間在未來"
            detail = "治理事件時間超出可接受時鐘誤差，不能用來判定目前狀態。"
        elif dto.observation_scope == "event_log_unreadable":
            state_label = "治理事件檔無法讀取"
            detail = "事件檔無法讀取，不能把它解讀為沒有治理事件或目前健康。"
        elif dto.observation_scope == "event_log_degraded":
            state_label = "治理事件檔部分無法解析"
            detail = "事件檔含無法解析的資料，不能據此宣稱治理 Runtime 健康。"
        else:
            state_label = "尚無治理事件"
            detail = "尚未觀測到治理 Runtime 事件。"
        self.health_state_label.setText(f"整體治理狀態：{state_label}")
        self.health_state_label.setStyleSheet("font-weight: bold;")
        self.rejection_rate_label.setText(
            f"歷史事件：{dto.historical_event_count}｜時間無法解析：{dto.timestamp_invalid_count}"
            f"｜未來時間：{dto.future_event_count}"
            + self._event_log_read_suffix(dto)
        )
        self.health_scope_note_label.setText(detail + self._event_log_read_note(dto))
        if dto.last_critical_violation:
            message = self._localize_message(dto.last_critical_violation.human_readable_message)
            self.last_violation_label.setText(f"最近歷史重大違規：{message}")
        else:
            self.last_violation_label.setText("最近歷史重大違規：無")

    def on_event_received(self, dto: RuntimeEventDTO) -> None:
        """Pure rendering slot for appending event logs"""
        self.event_empty_state.hide()
        time_str = dto.timestamp.strftime("%H:%M:%S") if dto.timestamp is not None else "時間未知"
        severity_label = SEVERITY_LABELS.get(dto.severity.value, dto.severity.value)
        event_label = EVENT_LABELS.get(dto.event_type, dto.event_type)
        message = self._localize_message(dto.human_readable_message)
        item_text = f"[{time_str}] {severity_label}｜{dto.actor}｜{event_label}：{message}"

        item = QListWidgetItem(item_text)
        item.setToolTip(
            f"raw event_type: {dto.event_type}\n"
            f"raw timestamp: {dto.timestamp_raw or 'missing'}\n"
            f"payload: {dto.payload_preview}\n"
            f"message: {dto.human_readable_message}"
        )
        self.event_list.addItem(item)
        while self.event_list.count() > MAX_RENDERED_RUNTIME_EVENTS:
            self.event_list.takeItem(0)
        self.event_list.scrollToBottom()

    def _localize_message(self, message: str) -> str:
        localized = str(message or "")
        for raw, label in ERROR_LABELS.items():
            localized = localized.replace(raw, label)
        return localized

    @staticmethod
    def _event_log_read_suffix(dto: RuntimeHealthSnapshotDTO) -> str:
        if dto.event_log_read_state == "observed":
            return ""
        label = EVENT_LOG_READ_STATE_LABELS.get(
            dto.event_log_read_state,
            dto.event_log_read_state,
        )
        return f"｜事件檔：{label}"

    @staticmethod
    def _event_log_read_note(dto: RuntimeHealthSnapshotDTO) -> str:
        if dto.event_log_read_state == "observed":
            return ""
        detail = f" 事件檔讀取狀態：{dto.event_log_read_state}。"
        if dto.event_log_diagnostic:
            detail += f" 診斷：{dto.event_log_diagnostic}。"
        return detail
