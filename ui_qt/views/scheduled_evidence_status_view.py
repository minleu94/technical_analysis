from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from app_module.scheduled_evidence_status_service import (
    ScheduledEvidenceStatus,
    ScheduledEvidenceStatusService,
)
from app_module.machine_status_classification import (
    MACHINE_STATUS_STALE,
    MACHINE_STATUS_UNKNOWN,
)
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.views.update.update_formatters import (
    format_machine_status_classification,
    format_status_token,
)
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
        self._last_good_status: ScheduledEvidenceStatus | None = None
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
        self.refresh_button.setAccessibleName("重新整理排程證據狀態")
        self.refresh_button.setAccessibleDescription(
            "重新讀取既有排程輸出；失敗時保留最後可信資料並標示 stale。"
        )
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
        # Only a service read with ``current`` metadata is a last-known-good
        # payload.  The compatibility branch below accepts old injected DTOs
        # for tests/legacy callers, but an initial service read with partial
        # source gaps must remain unknown and must not become stale custody.
        if not status.is_stale and (
            status.load_state == "current"
            or (
                status.load_state == MACHINE_STATUS_UNKNOWN
                and status.load_checked_at is None
                and status.machine_status_classification != MACHINE_STATUS_UNKNOWN
            )
        ):
            self._last_good_status = status
        self.refresh_button.setEnabled(True)
        latest_date = status.latest_data_date or "未知"
        decision_date = status.decision_date or "未知"
        freshness_class = dict(status.machine_status_classifications).get("data_freshness", "unknown")
        recommendation_class = dict(status.machine_status_classifications).get(
            "recommendation_snapshot", "unknown"
        )
        evidence_class = dict(status.machine_status_classifications).get("evidence_pipeline", "unknown")
        load_label = _load_state_label(status)
        stale_suffix = (
            "\n資料狀態：stale（沿用最後可信內容）"
            if status.is_stale or status.load_state == MACHINE_STATUS_STALE
            else ""
        )
        self.boundary_label.setText(
            "此頁只讀取 Windows Task Scheduler 產出的 latest_status.json 與 dry-run report；"
            "不重跑 pipeline、不寫 evidence DB、不計入正式 multi-day record。\n"
            f"讀取狀態：{load_label}；"
            f"最後可信載入：{status.last_good_loaded_at or '未知'}。"
        )
        self.freshness_label.setText(
            "Data freshness\n"
            f"{status.freshness_status} / 最新資料 {latest_date}\n"
            f"分類：{format_machine_status_classification(freshness_class)}{stale_suffix}"
        )
        self.evidence_label.setText(
            "Evidence dry-run\n"
            f"{status.evidence_status} / 決策日 {decision_date}\n"
            f"分類：{format_machine_status_classification(evidence_class)}{stale_suffix}"
        )
        recommendation_id = status.recommendation_result_id or "未知"
        recommendation_count = (
            str(status.recommendations_count) if status.recommendations_count is not None else "未知"
        )
        self.recommendation_label.setText(
            "Recommendation snapshot\n"
            f"{status.recommendation_status} / {status.recommendation_source} / "
            f"{recommendation_id} / {recommendation_count} 筆\n"
            f"分類：{format_machine_status_classification(recommendation_class)}{stale_suffix}"
        )
        self.safety_label.setText(
            "安全邊界\n"
            f"confirm={_bool_text(status.confirm)} / "
            f"recommendation_result_write={_bool_text(status.writes_recommendation_result)} / "
            f"writes_evidence_db={_bool_text(status.writes_evidence_db)} / "
            f"auto_trading={_bool_text(status.auto_trading)} / load={load_label}{stale_suffix}"
        )
        self.report_label.setText(
            "Report\n"
            + (str(status.report_path) if status.report_path is not None else "未提供 report path")
            + stale_suffix
        )
        self.detail_panel.setPlainText(_format_details(status))

    def _on_status_error(self, message: str) -> None:
        error_line = _error_line(message)
        if self._last_good_status is not None:
            stale_status = replace(
                self._last_good_status,
                load_state=MACHINE_STATUS_STALE,
                is_stale=True,
                load_checked_at=_now_text(),
                diagnostics=tuple(
                    dict.fromkeys(
                        (
                            *self._last_good_status.diagnostics,
                            f"status_loader_error:{error_line}",
                            "last_known_good_preserved",
                        )
                    )
                ),
            )
            self._on_status_loaded(stale_status)
            self.detail_panel.append(f"\n本次重新整理失敗，已保留 last-known-good：{error_line}")
            self.refresh_button.setFocus(Qt.OtherFocusReason)
            return

        self.refresh_button.setEnabled(True)
        unknown_label = format_machine_status_classification(MACHINE_STATUS_UNKNOWN)
        self.boundary_label.setText(
            "此頁狀態未知：尚無可信排程 payload。請聚焦 Retry；不補值、不寫 evidence DB。"
        )
        self.freshness_label.setText(f"Data freshness\n分類：{unknown_label}")
        self.recommendation_label.setText(f"Recommendation snapshot\n分類：{unknown_label}")
        self.evidence_label.setText(f"Evidence dry-run\n分類：{unknown_label}")
        self.safety_label.setText("安全邊界\n狀態未知；不能推定可寫入或可交易")
        self.report_label.setText("Report\n狀態未知；尚無可信 report")
        self.detail_panel.setPlainText(
            f"排程狀態載入失敗；狀態未知：{error_line}\n"
            "請聚焦 Retry；尚無 last-known-good 可保留。"
        )
        self.refresh_button.setFocus(Qt.OtherFocusReason)

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
        f"- machine load state: {_load_state_label(status)}",
        f"- last good loaded at: {status.last_good_loaded_at or '未知'}",
        (
            "- machine classifications: "
            + "; ".join(
                f"{name}={format_machine_status_classification(classification)}"
                for name, classification in status.machine_status_classifications
            )
        ),
        f"- data freshness: {status.freshness_status} / 最新資料 {status.latest_data_date or '未知'}",
        (
            "- recommendation snapshot: "
            f"{status.recommendation_status} / {status.recommendation_source} / "
            f"{recommendation_id} / {recommendation_count} 筆"
        ),
        f"- recommendation note: {recommendation_note}",
        f"- evidence dry-run: {status.evidence_status} / 決策日 {status.decision_date or '未知'}",
        f"- blocking gaps: {_join(status.pipeline_blocking_gaps)}",
        f"- evidence/trading boundary: {'ok' if boundary_ok else 'needs review'}",
        (
            "- recommendation result write: "
            f"{_bool_text(status.writes_recommendation_result)} / research-only output"
        ),
        f"- production evidence/trading write risk: {_bool_text(status.has_production_write_risk)}",
        "",
        "人工判讀範圍（僅限明確 human_review）",
        f"- scheduled recommendation days: {status.recommendation_snapshot_observed_days}",
        f"- manual recommendation days: {status.manual_recommendation_observed_days}",
        f"- scheduler_readiness_after: {status.scheduler_readiness_after or '未知'}",
        f"- source warnings: {_join(status.source_coverage_warnings)}",
        f"- pipeline warnings: {_pipeline_warning_summary(status)}",
        f"- pipeline advisories: {_pipeline_advisory_summary(status)}",
        f"- top pipeline warnings: {_join_warning_top_counts(status.pipeline_warning_top_counts)}",
        f"- top pipeline advisories: {_join_warning_top_counts(status.pipeline_advisory_top_counts)}",
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
        f"- production evidence/trading write risk: {_bool_text(status.has_production_write_risk)}",
        "",
        "執行狀態",
        f"- data freshness: {status.freshness_status}",
        f"- recommendation snapshot: {status.recommendation_status}",
        f"- evidence dry-run: {status.evidence_status}",
        f"- pipeline_overall_status: {status.pipeline_overall_status or '未知'}",
        f"- evidence_checked_at: {status.evidence_checked_at or '未知'}",
        f"- freshness warnings: {_join(status.freshness_warnings)}",
        f"- pipeline warnings: {_pipeline_warning_summary(status)}",
        f"- pipeline advisories: {_pipeline_advisory_summary(status)}",
        f"- pipeline_warning_top_counts: {_join_warning_top_counts(status.pipeline_warning_top_counts)}",
        f"- pipeline_advisory_top_counts: {_join_warning_top_counts(status.pipeline_advisory_top_counts)}",
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


def _pipeline_warning_summary(status: ScheduledEvidenceStatus) -> str:
    warnings_count = status.pipeline_warnings_count
    unique_count = status.pipeline_warning_unique_count
    if warnings_count is None and unique_count is None:
        return "無"
    warnings_text = str(warnings_count) if warnings_count is not None else "未知"
    unique_text = str(unique_count) if unique_count is not None else "未知"
    return f"{warnings_text} warning occurrences / {unique_text} warning types"


def _pipeline_advisory_summary(status: ScheduledEvidenceStatus) -> str:
    advisories_count = status.pipeline_advisories_count
    unique_count = status.pipeline_advisory_unique_count
    if advisories_count is None and unique_count is None:
        return "無"
    advisories_text = str(advisories_count) if advisories_count is not None else "未知"
    unique_text = str(unique_count) if unique_count is not None else "未知"
    return f"{advisories_text} advisory occurrences / {unique_text} advisory types"


def _join_warning_top_counts(values: tuple[tuple[str, int], ...]) -> str:
    return ", ".join(f"{warning}={count}" for warning, count in values) if values else "無"


def _join(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "無"


def _bool_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "true" if value else "false"


def _load_state_label(status: ScheduledEvidenceStatus) -> str:
    if status.is_stale or status.load_state == MACHINE_STATUS_STALE:
        return format_status_token("stale") + "（保留最後可信資料）"
    if status.load_state == MACHINE_STATUS_UNKNOWN:
        if status.load_checked_at is None and status.machine_status_classification != MACHINE_STATUS_UNKNOWN:
            return format_status_token("current") + "（注入 DTO，未提供 loader metadata）"
        return format_status_token("unknown")
    return format_status_token(status.load_state or "unknown")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_line(message: str) -> str:
    for line in str(message or "").splitlines():
        if line.strip():
            return line.strip()
    return "未提供錯誤訊息"
