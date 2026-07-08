from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from app_module.scheduled_evidence_status_service import (
    ScheduledEvidenceStatus,
    ScheduledEvidenceStatusService,
)
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.workers.task_worker import TaskWorker


class ScheduledEvidenceStatusView(QWidget):
    def __init__(
        self,
        status_service: ScheduledEvidenceStatusService,
        *,
        auto_refresh: bool = True,
        async_refresh: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.status_service = status_service
        self.async_refresh = async_refresh
        self._worker: TaskWorker | None = None
        self._setup_ui()
        if auto_refresh:
            self.refresh_status()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel("每日排程證據狀態")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        root.addWidget(title)

        self.boundary_label = QLabel(
            "此頁只讀取 Windows Task Scheduler 產出的 latest_status.json 與 dry-run report；"
            "不重跑 pipeline、不寫 evidence DB、不計入正式 multi-day record。"
        )
        self.boundary_label.setWordWrap(True)
        self.boundary_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.warning}; background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: 6px; padding: 7px;"
        )
        root.addWidget(self.boundary_label)

        cards = QGridLayout()
        self.freshness_label = self._make_card("Data freshness", "尚未載入")
        self.recommendation_label = self._make_card("Recommendation snapshot", "尚未載入")
        self.evidence_label = self._make_card("Evidence dry-run", "尚未載入")
        self.safety_label = self._make_card("安全邊界", "尚未載入")
        self.report_label = self._make_card("Report", "尚未載入")
        cards.addWidget(self.freshness_label, 0, 0)
        cards.addWidget(self.recommendation_label, 0, 1)
        cards.addWidget(self.evidence_label, 1, 0)
        cards.addWidget(self.safety_label, 1, 1)
        cards.addWidget(self.report_label, 2, 0, 1, 2)
        root.addLayout(cards)

        self.refresh_button = QPushButton("重新整理排程狀態")
        self.refresh_button.setProperty("variant", "primary")
        self.refresh_button.clicked.connect(self.refresh_status)
        root.addWidget(self.refresh_button, alignment=Qt.AlignLeft)

        self.detail_panel = QTextEdit()
        self.detail_panel.setReadOnly(True)
        self.detail_panel.setFont(QFont("Consolas", 9))
        root.addWidget(self.detail_panel, stretch=1)

    def refresh_status(self) -> None:
        self.refresh_button.setEnabled(False)
        if self.async_refresh:
            worker = TaskWorker(self.status_service.load_latest)
            self._worker = worker
            worker.finished.connect(self._on_status_loaded)
            worker.error.connect(self._on_status_error)
            worker.finished.connect(lambda _result: self._release_worker())
            worker.error.connect(lambda _message: self._release_worker())
            worker.start()
            return
        try:
            self._on_status_loaded(self.status_service.load_latest())
        except Exception as exc:  # noqa: BLE001
            self._on_status_error(str(exc))

    def _on_status_loaded(self, status: ScheduledEvidenceStatus) -> None:
        self.refresh_button.setEnabled(True)
        latest_date = status.latest_data_date or "未知"
        decision_date = status.decision_date or "未知"
        self.freshness_label.setText(f"Data freshness\n{status.freshness_status} / 最新資料 {latest_date}")
        self.evidence_label.setText(
            f"Evidence dry-run\n{status.evidence_status} / 決策日 {decision_date}"
        )
        recommendation_id = status.recommendation_result_id or "未知"
        recommendation_count = (
            str(status.recommendations_count) if status.recommendations_count is not None else "未知"
        )
        self.recommendation_label.setText(
            "Recommendation snapshot\n"
            f"{status.recommendation_status} / {status.recommendation_source} / "
            f"{recommendation_id} / {recommendation_count} 筆"
        )
        self.safety_label.setText(
            "安全邊界\n"
            f"confirm={_bool_text(status.confirm)} / "
            f"writes_evidence_db={_bool_text(status.writes_evidence_db)} / "
            f"auto_trading={_bool_text(status.auto_trading)}"
        )
        self.report_label.setText(
            "Report\n"
            + (str(status.report_path) if status.report_path is not None else "未提供 report path")
        )
        self.detail_panel.setPlainText(_format_details(status))

    def _on_status_error(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.freshness_label.setText("Data freshness\n載入失敗")
        self.recommendation_label.setText("Recommendation snapshot\n載入失敗")
        self.evidence_label.setText("Evidence dry-run\n載入失敗")
        self.safety_label.setText("安全邊界\n無法判斷")
        self.report_label.setText("Report\n無法判斷")
        self.detail_panel.setPlainText(f"排程狀態載入失敗：{message.splitlines()[0]}")

    def _release_worker(self) -> None:
        self.refresh_button.setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _make_card(self, title: str, value: str) -> QLabel:
        card = QLabel(f"{title}\n{value}")
        card.setAlignment(Qt.AlignCenter)
        card.setWordWrap(True)
        card.setMinimumHeight(68)
        card.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_primary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: 6px; padding: 6px;"
        )
        return card


def _format_details(status: ScheduledEvidenceStatus) -> str:
    recommendation_id = status.recommendation_result_id or "未知"
    recommendation_count = status.recommendations_count if status.recommendations_count is not None else "未知"
    boundary_ok = not status.has_production_write_risk and status.writes_evidence_db is False
    recommendation_note = _recommendation_note(status)
    lines = [
        "判讀摘要",
        f"- data freshness: {status.freshness_status} / 最新資料 {status.latest_data_date or '未知'}",
        (
            "- recommendation snapshot: "
            f"{status.recommendation_status} / {status.recommendation_source} / "
            f"{recommendation_id} / {recommendation_count} 筆"
        ),
        f"- recommendation note: {recommendation_note}",
        f"- evidence dry-run: {status.evidence_status} / 決策日 {status.decision_date or '未知'}",
        f"- blocking gaps: {_join(status.pipeline_blocking_gaps)}",
        f"- read-only boundary: {'ok' if boundary_ok else 'needs review'}",
        f"- production write risk: {_bool_text(status.has_production_write_risk)}",
        "",
        "人工要看",
        f"- scheduled recommendation days: {status.recommendation_snapshot_observed_days}",
        f"- manual recommendation days: {status.manual_recommendation_observed_days}",
        f"- scheduler_readiness_after: {status.scheduler_readiness_after or '未知'}",
        f"- source warnings: {_join(status.source_coverage_warnings)}",
        f"- diagnostics: {_join(status.diagnostics)}",
        "",
        "關鍵欄位",
        f"- checked_at: freshness={status.checked_at or '未知'} / recommendation={status.recommendation_checked_at or '未知'} / evidence={status.evidence_checked_at or '未知'}",
        f"- screening_matrix_rows: {status.screening_matrix_rows if status.screening_matrix_rows is not None else '未知'}",
        f"- why_not_payload_rows: {status.why_not_payload_rows if status.why_not_payload_rows is not None else '未知'}",
        f"- liquidity_gate_payload_rows: {status.liquidity_gate_payload_rows if status.liquidity_gate_payload_rows is not None else '未知'}",
        f"- manual_result_path: {status.manual_recommendation_result_path or '無'}",
        f"- report_path: {status.report_path or '未提供'}",
        f"- report_exists: {_bool_text(status.report_exists)}",
        "",
        "安全邊界",
        f"- dry_run: {_bool_text(status.dry_run)}",
        f"- confirm: {_bool_text(status.confirm)}",
        f"- writes_recommendation_result: {_bool_text(status.writes_recommendation_result)}",
        f"- writes_evidence_db: {_bool_text(status.writes_evidence_db)}",
        f"- auto_trading: {_bool_text(status.auto_trading)}",
        f"- lifecycle_action: {_bool_text(status.lifecycle_action)}",
        f"- production write risk: {_bool_text(status.has_production_write_risk)}",
        "",
        "執行狀態",
        f"- data freshness: {status.freshness_status}",
        f"- recommendation snapshot: {status.recommendation_status}",
        f"- evidence dry-run: {status.evidence_status}",
        f"- evidence_checked_at: {status.evidence_checked_at or '未知'}",
        f"- warnings: {_join(status.freshness_warnings)}",
        f"- errors: {_join(status.freshness_errors)}",
        f"- exit_code: {status.exit_code if status.exit_code is not None else '未知'}",
        f"- pipeline_diagnostic_codes: {_join(status.pipeline_diagnostic_codes)}",
        f"- log_path: {status.log_path or '未提供'}",
    ]
    if status.report_preview:
        lines.extend(["", "Report preview（trimmed）", _trim_report_preview(status.report_preview)])
    return "\n".join(lines)


def _recommendation_note(status: ScheduledEvidenceStatus) -> str:
    if status.recommendation_status == "manual_observed":
        return "scheduled latest_status missing；manual result observed"
    if status.recommendation_status == "passed":
        return "scheduled latest_status observed"
    if status.recommendation_status == "missing":
        return "recommendation snapshot missing"
    return "review recommendation status"


def _trim_report_preview(preview: str, *, max_lines: int = 24) -> str:
    selected: list[str] = []
    for line in preview.splitlines():
        if line.strip() == "## Source Coverage":
            selected.append("... report preview trimmed before Source Coverage JSON; open report_path for full diagnostics ...")
            break
        selected.append(line)
        if len(selected) >= max_lines:
            selected.append("... report preview trimmed; open report_path for full diagnostics ...")
            break
    return "\n".join(selected)


def _join(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "無"


def _bool_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "true" if value else "false"
