"""Workbench Evidence 子頁的唯讀 Research Console。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_module.research_console_dtos import ResearchConsoleDTO
from app_module.research_console_source_service import ResearchConsoleSourceService
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.widgets.theme_widgets import SectionPanel


_STATUS_COLORS = {
    "observed": "#22c55e",
    "research_baseline": "#38bdf8",
    "development_challenger": "#38bdf8",
    "development_only": "#38bdf8",
    "candidate": "#a78bfa",
    "provisional": "#a78bfa",
    "fixture": "#94a3b8",
    "replay": "#94a3b8",
    "degraded": "#f59e0b",
    "research_only_degraded": "#f59e0b",
    "missing": "#ef4444",
    "unknown": "#ef4444",
}


class ResearchConsoleView(QWidget):
    """只複製 ResearchConsoleDTO；不計算或寫入 domain state。"""

    def __init__(
        self,
        *,
        source_service: ResearchConsoleSourceService | None = None,
        console: ResearchConsoleDTO | None = None,
        auto_refresh: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.source_service = source_service or ResearchConsoleSourceService()
        self._console: ResearchConsoleDTO | None = None
        self._setup_ui()
        if console is not None:
            self.render_console(console)
        elif auto_refresh:
            self.refresh_console()
        else:
            self.render_console(self.source_service.inspect())

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Research Console / Development Evidence")
        title.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 18px; font-weight: 700;"
        )
        subtitle = QLabel(
            "唯讀呈現 sanitized frozen projection；Development／candidate／replay 不等於 formal evidence。"
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.refresh_button = QPushButton("重新載入唯讀 projection")
        self.refresh_button.setProperty("variant", "secondary")
        self.refresh_button.clicked.connect(self.refresh_console)
        layout.addWidget(self.refresh_button)

        boundary_panel = SectionPanel("1. Safety Boundary")
        boundary_grid = QGridLayout()
        boundary_grid.setSpacing(8)
        self.boundary_labels: dict[str, QLabel] = {}
        for index, (key, label) in enumerate(
            (
                ("formal_oos", "Formal OOS"),
                ("alpha", "Production Blend Alpha"),
                ("ml", "Production ML"),
                ("formal_path", "Formal Recommendation / Portfolio"),
                ("actions", "Promotion / Retrain / Scheduler / Trading"),
            )
        ):
            card = QLabel()
            card.setWordWrap(True)
            card.setTextInteractionFlags(Qt.TextSelectableByMouse)
            card.setStyleSheet(
                f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_primary}; "
                f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: 6px; padding: 8px;"
            )
            boundary_grid.addWidget(QLabel(label), index // 2 * 2, index % 2)
            boundary_grid.addWidget(card, index // 2 * 2 + 1, index % 2)
            self.boundary_labels[key] = card
        boundary_panel.layout.addLayout(boundary_grid)
        layout.addWidget(boundary_panel)

        pipeline_panel = SectionPanel("2. Development Pipeline")
        self.pipeline_state_label = QLabel()
        self.pipeline_state_label.setWordWrap(True)
        self.pipeline_state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.pipeline_table = _table(
            ("元件", "Identity", "狀態", "Cutoff / Maturity", "Rows / Eligible / Features", "Artifact / Blockers")
        )
        pipeline_panel.layout.addWidget(self.pipeline_state_label)
        pipeline_panel.layout.addWidget(self.pipeline_table)
        layout.addWidget(pipeline_panel)

        gates_panel = SectionPanel("3. Evidence / Source Gates")
        self.gate_table = _table(("Gate", "狀態", "說明", "Artifact"))
        self.source_table = _table(("來源", "Lane", "狀態", "Allowed use", "Rows", "缺口 / Revision"))
        self.artifact_table = _table(("Artifact", "Identity", "狀態", "Citation"))
        self.broker_lane_label = QLabel("Broker Dataset（獨立 lane）")
        self.broker_lane_label.setStyleSheet("color: #a78bfa; font-weight: 700;")
        gates_panel.layout.addWidget(self.gate_table)
        gates_panel.layout.addWidget(self.broker_lane_label)
        gates_panel.layout.addWidget(self.source_table)
        gates_panel.layout.addWidget(QLabel("Artifact Inspector"))
        gates_panel.layout.addWidget(self.artifact_table)
        layout.addWidget(gates_panel)
        layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

    def refresh_console(self) -> None:
        self.render_console(self.source_service.inspect())

    def render_console(self, console: ResearchConsoleDTO) -> None:
        self._console = console
        boundary = console.boundary
        self.boundary_labels["formal_oos"].setText(
            f"formal_oos_allowed = {boundary.formal_oos_allowed}\nDisabled"
        )
        self.boundary_labels["alpha"].setText(
            f"production_blend_alpha_bp = {boundary.production_blend_alpha_bp}\nDisabled"
        )
        self.boundary_labels["ml"].setText("Production ML: Disabled\nDevelopment Only")
        self.boundary_labels["formal_path"].setText(
            "Formal path: Rule-only\nRecommendation / Portfolio unchanged"
        )
        self.boundary_labels["actions"].setText(
            "Promotion: Disabled｜Retrain: Disabled｜Scheduler: Disabled｜Trading: Disabled"
        )
        self.pipeline_state_label.setText(
            f"狀態：{_display(console.overall_status)}｜來源：{console.source_reference}｜"
            f"Blockers：{_join(console.blockers)}"
        )
        _set_rows(
            self.pipeline_table,
            (
                (
                    row.label,
                    row.identity,
                    row.status,
                    _join_optional(row.cutoff, row.feature_interval, row.label_maturity),
                    _counts(row.row_count, row.eligible_count, row.feature_count),
                    _join_optional(row.artifact_path, row.artifact_hash, _join(row.blockers)),
                )
                for row in console.pipeline
            ),
            status_column=2,
        )
        _set_rows(
            self.gate_table,
            ((row.gate_id, row.status, row.detail, row.artifact_citation or "Not Available") for row in console.gates),
            status_column=1,
        )
        _set_rows(
            self.source_table,
            (
                (
                    row.label,
                    row.lane.upper(),
                    row.status,
                    row.allowed_use,
                    _optional_number(row.observed_rows),
                    _join_optional(row.degraded_reason, row.revision, row.owner),
                )
                for row in console.sources
            ),
            status_column=2,
        )
        _set_rows(
            self.artifact_table,
            ((row.artifact_type, row.artifact_id, row.status, row.citation) for row in console.artifacts),
            status_column=2,
        )

    def visible_text(self) -> str:
        values = [label.text() for label in self.findChildren(QLabel)]
        for table in (self.pipeline_table, self.gate_table, self.source_table, self.artifact_table):
            for row in range(table.rowCount()):
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item is not None:
                        values.append(item.text())
        return "\n".join(values)


def _table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(150)
    return table


def _set_rows(table: QTableWidget, rows, *, status_column: int) -> None:
    materialized = tuple(rows)
    table.setRowCount(len(materialized))
    for row_index, values in enumerate(materialized):
        for column_index, value in enumerate(values):
            item = QTableWidgetItem(_display(value))
            item.setToolTip(item.text())
            if column_index == status_column:
                item.setForeground(QColor(_STATUS_COLORS.get(str(value).lower(), "#94a3b8")))
            table.setItem(row_index, column_index, item)


def _display(value: object) -> str:
    text = str(value) if value not in (None, "") else "Missing / Unknown"
    return text.replace("missing", "Missing").replace("unknown", "Unknown")


def _join(values: tuple[str, ...]) -> str:
    return "；".join(values) if values else "None"


def _join_optional(*values: str | None) -> str:
    present = tuple(value for value in values if value)
    return "｜".join(present) if present else "Missing / Unknown"


def _counts(rows: int | None, eligible: int | None, features: int | None) -> str:
    return (
        f"Rows: {_optional_number(rows)}｜Eligible: {_optional_number(eligible)}｜"
        f"Features: {_optional_number(features)}"
    )


def _optional_number(value: int | None) -> str:
    return f"{value:,}" if value is not None else "Missing / Unknown"
