from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTextEdit, QLabel, QListWidget, QGroupBox
)
from PySide6.QtCore import Qt
from app_module.dtos.runtime_dtos import RuntimeStateSnapshotDTO, RuntimeHealthSnapshotDTO, RuntimeEventDTO

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
        splitter = QSplitter(Qt.Horizontal)
        
        # ---------------------------------------------------------
        # Left Panel: FSM State & Context Overview
        # ---------------------------------------------------------
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        state_group = QGroupBox("FSM State Machine")
        state_layout = QVBoxLayout(state_group)
        self.objective_label = QLabel("Objective: N/A")
        self.status_label = QLabel("Status: IDLE")
        
        # Apply CSS for clear visual boundaries
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        state_layout.addWidget(self.objective_label)
        state_layout.addWidget(self.status_label)
        
        ctx_group = QGroupBox("Runtime Context Environment")
        ctx_layout = QVBoxLayout(ctx_group)
        self.context_text = QTextEdit()
        self.context_text.setReadOnly(True)
        ctx_layout.addWidget(self.context_text)
        
        left_layout.addWidget(state_group)
        left_layout.addWidget(ctx_group)
        
        # ---------------------------------------------------------
        # Right Panel: Governance Observability & Event Stream
        # ---------------------------------------------------------
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        health_group = QGroupBox("Governance Health")
        health_layout = QVBoxLayout(health_group)
        self.health_state_label = QLabel("Overall System State: UNKNOWN")
        self.rejection_rate_label = QLabel("Rejection Rate: 0.0% (STABLE)")
        self.last_violation_label = QLabel("Last Critical Violation: None")
        self.last_violation_label.setStyleSheet("color: red; font-weight: bold;")
        
        health_layout.addWidget(self.health_state_label)
        health_layout.addWidget(self.rejection_rate_label)
        health_layout.addWidget(self.last_violation_label)
        
        events_group = QGroupBox("Append-only Event Stream")
        events_layout = QVBoxLayout(events_group)
        self.event_list = QListWidget()
        events_layout.addWidget(self.event_list)
        
        right_layout.addWidget(health_group)
        right_layout.addWidget(events_group)
        
        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        
        # 40% / 60% split ratio
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        
        main_layout.addWidget(splitter)
        
    def on_state_updated(self, dto: RuntimeStateSnapshotDTO) -> None:
        """Pure rendering slot for State Snapshot DTO"""
        self.objective_label.setText(f"Objective: {dto.task_objective}")
        self.status_label.setText(f"Task Workflow Status: {dto.task_status}")
        
        ctx_text = "Active Files:\n" + "\n".join(dto.active_context_files)
        self.context_text.setText(ctx_text)
        
    def on_health_updated(self, dto: RuntimeHealthSnapshotDTO) -> None:
        """Pure rendering slot for Health Analytics DTO"""
        state_color = "red" if dto.current_state.value in ["ERROR", "HALTED"] else "green"
        self.health_state_label.setText(f"Overall System State: <font color='{state_color}'>{dto.current_state.value}</font>")
        
        rate_pct = dto.rejection_rate * 100
        trend_arrow = "↑" if dto.rejection_rate_trend == "UP" else ("↓" if dto.rejection_rate_trend == "DOWN" else "→")
        self.rejection_rate_label.setText(f"Rejection Rate: {rate_pct:.1f}% ({trend_arrow}) [Consecutive Fails: {dto.consecutive_failures}]")
        
        if dto.last_critical_violation:
            msg = dto.last_critical_violation.human_readable_message
            self.last_violation_label.setText(f"Last Critical Violation: {msg}")
        else:
            self.last_violation_label.setText("Last Critical Violation: None")
            
    def on_event_received(self, dto: RuntimeEventDTO) -> None:
        """Pure rendering slot for appending event logs"""
        time_str = dto.timestamp.strftime("%H:%M:%S")
        item_text = f"[{time_str}] {dto.severity.value} | {dto.actor} | {dto.event_type} - {dto.human_readable_message}"
        
        self.event_list.addItem(item_text)
        self.event_list.scrollToBottom()
