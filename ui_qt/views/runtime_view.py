from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTextEdit, QLabel, QListWidget, QGroupBox, QListWidgetItem
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui_qt.widgets.info_button import InfoButton
from app_module.dtos.runtime_dtos import RuntimeStateSnapshotDTO, RuntimeHealthSnapshotDTO, RuntimeEventDTO

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


class RuntimeView(QWidget):
    """
    Pure Render UI component for the Runtime Observatory.
    This view strictly depends ONLY on DTOs and has zero business logic or direct file IO.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # 標題列（標題 + InfoButton）
        title_layout = QHBoxLayout()
        title = QLabel("運行監控站 (Runtime Observatory)")
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
            "Runtime Observatory 不監控資料更新背景任務；資料更新、回測與推薦長任務仍由各自頁面顯示狀態。"
        )
        self.scope_label.setWordWrap(True)
        main_layout.addWidget(self.scope_label)

        splitter = QSplitter(Qt.Horizontal)

        # ---------------------------------------------------------
        # Left Panel: FSM State & Context Overview
        # ---------------------------------------------------------
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        self.state_group = QGroupBox("任務狀態機")
        state_layout = QVBoxLayout(self.state_group)
        self.objective_label = QLabel("目前治理目標：尚未指派治理任務")
        self.status_label = QLabel("任務流程狀態：閒置")

        # Apply CSS for clear visual boundaries
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        state_layout.addWidget(self.objective_label)
        state_layout.addWidget(self.status_label)

        self.context_group = QGroupBox("Runtime Context 環境")
        ctx_layout = QVBoxLayout(self.context_group)
        self.context_text = QTextEdit()
        self.context_text.setReadOnly(True)
        ctx_layout.addWidget(self.context_text)

        left_layout.addWidget(self.state_group)
        left_layout.addWidget(self.context_group)

        # ---------------------------------------------------------
        # Right Panel: Governance Observability & Event Stream
        # ---------------------------------------------------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.health_group = QGroupBox("治理健康狀態")
        health_layout = QVBoxLayout(self.health_group)
        self.health_state_label = QLabel("整體治理狀態：未知")
        self.rejection_rate_label = QLabel("驗證拒絕率：0.0%（穩定）｜連續失敗次數：0")
        self.last_violation_label = QLabel("最近重大違規：無")
        self.last_violation_label.setStyleSheet("color: red; font-weight: bold;")
        self.health_scope_note_label = QLabel(
            "治理暫停或拒絕率升高只代表 agent / governance workflow 狀態，不代表主 App 一般功能失敗。"
        )
        self.health_scope_note_label.setWordWrap(True)

        health_layout.addWidget(self.health_state_label)
        health_layout.addWidget(self.rejection_rate_label)
        health_layout.addWidget(self.last_violation_label)
        health_layout.addWidget(self.health_scope_note_label)

        self.events_group = QGroupBox("事件流")
        events_layout = QVBoxLayout(self.events_group)
        self.event_list = QListWidget()
        events_layout.addWidget(self.event_list)

        right_layout.addWidget(self.health_group)
        right_layout.addWidget(self.events_group)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)

        # 40% / 60% split ratio
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        main_layout.addWidget(splitter)

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
        state_value = dto.current_state.value
        state_label = STATE_LABELS.get(state_value, state_value)
        high_risk = (
            state_value in {"ERROR", "HALTED"}
            or dto.rejection_rate >= 0.5
            or dto.consecutive_failures >= 3
        )
        state_color = "red" if high_risk else "green"
        self.health_state_label.setText(f"整體治理狀態：<font color='{state_color}'>{state_label}</font>")
        self.health_state_label.setStyleSheet("font-weight: bold;" if high_risk else "")

        rate_pct = dto.rejection_rate * 100
        trend_arrow = "↑" if dto.rejection_rate_trend == "UP" else ("↓" if dto.rejection_rate_trend == "DOWN" else "→")
        self.rejection_rate_label.setText(
            f"驗證拒絕率：{rate_pct:.1f}%（{trend_arrow}）｜連續失敗次數：{dto.consecutive_failures}"
        )

        if dto.last_critical_violation:
            msg = self._localize_message(dto.last_critical_violation.human_readable_message)
            self.last_violation_label.setText(f"最近重大違規：{msg}")
        else:
            self.last_violation_label.setText("最近重大違規：無")

    def on_event_received(self, dto: RuntimeEventDTO) -> None:
        """Pure rendering slot for appending event logs"""
        time_str = dto.timestamp.strftime("%H:%M:%S")
        severity_label = SEVERITY_LABELS.get(dto.severity.value, dto.severity.value)
        event_label = EVENT_LABELS.get(dto.event_type, dto.event_type)
        message = self._localize_message(dto.human_readable_message)
        item_text = f"[{time_str}] {severity_label}｜{dto.actor}｜{event_label}：{message}"

        item = QListWidgetItem(item_text)
        item.setToolTip(
            f"raw event_type: {dto.event_type}\n"
            f"payload: {dto.payload_preview}\n"
            f"message: {dto.human_readable_message}"
        )
        self.event_list.addItem(item)
        self.event_list.scrollToBottom()

    def _localize_message(self, message: str) -> str:
        localized = str(message or "")
        for raw, label in ERROR_LABELS.items():
            localized = localized.replace(raw, label)
        return localized
