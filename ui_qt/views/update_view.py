"""
數據更新視圖
提供數據更新功能界面
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QProgressBar,
    QTextEdit, QRadioButton, QButtonGroup,
    QDateEdit, QMessageBox, QFormLayout, QSpinBox, QLineEdit,
    QListWidget, QStackedWidget, QFrame, QCalendarWidget, QGridLayout,
    QScrollArea, QSizePolicy, QBoxLayout, QAbstractItemView, QHeaderView,
    QTableWidget, QTableWidgetItem
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont, QColor
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import subprocess
import sys
import inspect

from ui_qt.workers.task_worker import TaskWorker, ProgressTaskWorker
from app_module.update_service import UpdateService
from app_module.paper_portfolio_time import taiwan_market_today
from app_module.p0_source_control_center import (
    P0SourceControlCenterDTO,
    P0SourceControlCenterService,
)
from app_module.update_source_status_projection import compose_source_status_projection
from app_module.update_status_timeline import load_data_update_timeline
from data_module.source_acceptance_decision_registry import parse_source_acceptance_decisions
from data_module.monthly_revenue_snapshot_selection import (
    select_latest_monthly_revenue_snapshot,
)
from ui_qt.widgets.info_button import InfoButton
from ui_qt.widgets.text_sanitizer import strip_leading_symbol_icon
from ui_qt.views.update.update_formatters import (
    format_freshness_gap,
    format_source_detail_summary,
    format_status_token,
    get_update_type_name,
    tpex_warning_messages,
)
from ui_qt.views.update.worker_coordinator import WorkerCoordinator
from ui_qt.views.update.update_all_coordinator import run_update_all
from ui_qt.views.update.source_update_coordinator import SourceUpdateRequest


def _taiwan_market_qdate() -> QDate:
    """將資料更新 UI 的「今日」統一對齊台灣市場日期。"""

    today = taiwan_market_today()
    return QDate(today.year, today.month, today.day)


def _safe_nonnegative_int(value: Any) -> int:
    """把服務層計數安全投影到 UI；malformed 值不可中止整個狀態畫面。"""

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0





class StatusCard(QFrame):
    """自訂美化數據狀態卡片，與 QTextEdit 介面相容 (Sci-Fi 暗色風格)"""
    def __init__(self, title: str, icon_str: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.icon_str = strip_leading_symbol_icon(icon_str).strip()
        self._raw_text = ""

        self.setObjectName("CardFrame")
        # 設置現代暗色玻璃擬態樣式
        self.setStyleSheet("""
            QFrame#CardFrame {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(30, 41, 59, 0.65),
                    stop:1 rgba(15, 23, 42, 0.8)
                );
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
            }
            QFrame#CardFrame:hover {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(51, 65, 85, 0.75),
                    stop:1 rgba(30, 41, 59, 0.85)
                );
                border: 1px solid rgba(255, 255, 255, 0.18);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # 頂部：圖示 + 標題 + 狀態燈
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)

        title_prefix = f"{self.icon_str} " if self.icon_str else ""
        self.title_label = QLabel(f"<span style='font-size:12px; font-weight:bold; color:#cbd5e1;'>{title_prefix}{title}</span>")
        self.indicator_label = QLabel("<span style='font-size:11px; color:#94a3b8;'>未檢查</span>")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.indicator_label)
        layout.addLayout(header_layout)

        # 中間最新日期
        self.date_label = QLabel("<span style='color:#94a3b8;'>最新日期：</span><b style='color:#f8fafc;'>--</b>")
        self.date_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.date_label)

        # 總筆數
        self.records_label = QLabel("<span style='color:#94a3b8;'>總記錄數：</span><b style='color:#f8fafc;'>--</b>")
        self.records_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.records_label)

        # 額外資訊（例如技術指標數量）
        self.extra_label = QLabel("")
        self.extra_label.setStyleSheet("color:#94a3b8; font-size: 11px;")
        self.extra_label.setVisible(False)
        layout.addWidget(self.extra_label)

    def setPlainText(self, text: str):
        """相容 QTextEdit.setPlainText，用於解析並更新卡片 UI"""
        self._raw_text = text

        date_label = "最新日期"
        latest_date = "未知"
        total_records = "--"
        status_str = "unknown"
        extra_info_lines: list[str] = []

        lines = text.split('\n')
        for line in lines:
            if "最新可用日" in line:
                date_label = "最新可用日"
                latest_date = line.split("：")[-1].strip()
            elif "最新日期" in line:
                latest_date = line.split("：")[-1].strip()
            elif "總記錄數" in line:
                total_records = line.split("：")[-1].strip()
            else:
                # 只有真正的「狀態：…」欄位才可改變燈號；placeholder
                # （例如「點擊『檢查數據狀態』…」）不應被誤判成待更新。
                stripped_line = line.strip()
                if stripped_line.startswith("狀態："):
                    status_str = stripped_line.split("：", 1)[1].strip()
                elif stripped_line.startswith("狀態:"):
                    status_str = stripped_line.split(":", 1)[1].strip()
            if (
                "指標檔數" in line
                or "已匯入期別" in line
                or "目前可用期別" in line
                or "待生效" in line
                or "區間" in line
                or "覆蓋率" in line
            ):
                extra_info_lines.append(line.strip())
            elif "讀取模式" in line or "提醒" in line:
                extra_info_lines.append(line.strip())

        self.date_label.setText(f"<span style='color:#94a3b8;'>{date_label}：</span><b style='color:#f8fafc;'>{latest_date}</b>")
        self.records_label.setText(f"<span style='color:#94a3b8;'>總記錄數：</span><b style='color:#f8fafc;'>{total_records}</b>")

        if extra_info_lines:
            extra_info = "<br>".join(extra_info_lines)
            self.extra_label.setText(f"<span style='color:#94a3b8;'>{extra_info}</span>")
            self.extra_label.setVisible(True)
        else:
            self.extra_label.setVisible(False)

        # 燈號只依明確 status token 判定，不再因為描述文字含「最新」就亮綠燈。
        self.indicator_label.setText(self._indicator_markup(status_str, text))

    @staticmethod
    def _indicator_markup(status: str, text: str = "") -> str:
        """把服務狀態轉為可理解且不會假綠的燈號。"""
        raw_status = str(status or "").strip().lower()
        if not raw_status or raw_status in {"unknown", "未知", "未檢查"}:
            label, color = "未檢查", "#94a3b8"
        elif (
            raw_status.startswith(("error", "failed", "failure", "exception"))
            or raw_status.startswith(("missing", "empty", "unavailable", "缺漏", "不可用"))
            or raw_status in {
                "異常",
                "official_no_data",
                "schema_blocked",
                "schema_mismatch",
                "network_failed",
                "audit_unavailable",
                "blocked_provenance",
            }
            or any(marker in text for marker in ("錯誤", "失敗", "異常"))
        ):
            label, color = "異常", "#ef4444"
        elif raw_status in {"ok", "success", "current", "normal", "正常"}:
            if "immutable" in text.lower() or "唯讀快照" in text:
                label, color = "待更新", "#eab308"
            else:
                label, color = "最新", "#22c55e"
        else:
            label, color = "待更新", "#eab308"
        return f"<span style='font-size:11px; color:{color};'>{label}</span>"

    def toPlainText(self) -> str:
        """相容 QTextEdit.toPlainText"""
        return self._raw_text

    def setReadOnly(self, ro: bool):
        """相容 QTextEdit.setReadOnly"""
        pass

    def setMaximumHeight(self, h: int):
        """相容 QTextEdit.setMaximumHeight"""
        pass

    def clear(self):
        """清除卡片"""
        self._raw_text = ""
        self.date_label.setText("最新日期：--")
        self.records_label.setText("總記錄數：--")
        self.extra_label.setVisible(False)
        self.indicator_label.setText("<span style='font-size:11px; color:#94a3b8;'>未檢查</span>")


class UpdateView(QWidget):
    """數據更新視圖"""

    def __init__(
        self,
        update_service: UpdateService,
        parent=None,
        *,
        p0_source_audit_path: str | Path | None = None,
        p0_license_evidence_path: str | Path | None = None,
        p0_source_decision_path: str | Path | None = None,
        data_update_status_path: str | Path | None = None,
        data_update_history_path: str | Path | None = None,
        data_freshness_status_path: str | Path | None = None,
        tpex_status_path: str | Path | None = None,
    ):
        """初始化數據更新視圖

        Args:
            update_service: 數據更新服務實例
            parent: 父窗口
        """
        super().__init__(parent)
        self.update_service = update_service
        self.p0_source_audit_path = (
            Path(p0_source_audit_path).expanduser().resolve()
            if p0_source_audit_path is not None
            else None
        )
        self.p0_license_evidence_path = (
            Path(p0_license_evidence_path).expanduser().resolve()
            if p0_license_evidence_path is not None
            else None
        )
        self.p0_source_decision_path = (
            Path(p0_source_decision_path).expanduser().resolve()
            if p0_source_decision_path is not None
            else None
        )
        output_root = getattr(self.update_service.config, "output_root", None)
        meta_data_dir = getattr(
            self.update_service.config,
            "meta_data_dir",
            Path(getattr(self.update_service.config, "data_root", ".")) / "meta_data",
        )

        def _status_path(value: str | Path | None, fallback: Path | None) -> Path | None:
            if value is not None:
                return Path(value).expanduser().resolve()
            return fallback.expanduser().resolve() if fallback is not None else None

        output_root_path = Path(output_root) if output_root is not None else None
        self.data_update_status_path = _status_path(
            data_update_status_path,
            output_root_path / "scheduled" / "data_update_quick" / "latest_status.json"
            if output_root_path is not None
            else None,
        )
        self.data_update_history_path = _status_path(
            data_update_history_path,
            output_root_path / "scheduled" / "data_update_quick" / "history.jsonl"
            if output_root_path is not None
            else None,
        )
        self.data_freshness_status_path = _status_path(
            data_freshness_status_path,
            output_root_path / "scheduled" / "data_freshness" / "latest_status.json"
            if output_root_path is not None
            else None,
        )
        self.tpex_status_path = _status_path(
            tpex_status_path,
            Path(meta_data_dir) / "tpex_full_refresh_status.json",
        )
        self._p0_control_center_service = P0SourceControlCenterService()
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._responsive_narrow: bool | None = None
        self._loaded_detail_sources: set[str] = set()

        # Worker
        self.worker: Optional[TaskWorker] = None
        self._worker_coordinator = WorkerCoordinator[TaskWorker]()
        self._active_workers = self._worker_coordinator.active_workers
        self._last_progress = 0
        self.tpex_refresh_state_file = Path(meta_data_dir) / "tpex_full_refresh_status.json"
        self._tpex_background_process: Optional[subprocess.Popen] = None

        self._setup_ui()

    def _start_worker(self, worker: TaskWorker, *, operation_kind: str = "read") -> TaskWorker:
        """保留背景 worker 生命週期，並阻擋寫入型工作彼此重疊。"""
        self.worker = self._worker_coordinator.start(
            worker,
            kind=operation_kind,
            exclusive=operation_kind == "write",
        )
        if operation_kind == "write":
            self._set_cancel_control_visible(True)
        # 先註冊清理 callback，再由呼叫端接上完成處理，讓完成回呼開始
        # 下一個唯讀狀態檢查時，前一個寫入 worker 已從互斥集合釋放。
        worker.finished.connect(
            lambda _payload, current_worker=worker: self._release_worker(current_worker)
        )
        worker.error.connect(
            lambda _message, current_worker=worker: self._release_worker(current_worker)
        )
        if hasattr(worker, "cancelled"):
            worker.cancelled.connect(lambda current_worker=worker: self._release_worker(current_worker))
            worker.cancelled.connect(lambda current_worker=worker: self._on_worker_cancelled(current_worker))
        return worker

    def _release_worker(self, worker: TaskWorker):
        self.worker = self._worker_coordinator.release(worker)
        if not self._worker_coordinator.has_active("write"):
            self._set_cancel_control_visible(False)

    def _set_cancel_control_visible(self, visible: bool) -> None:
        """控制目前寫入型 worker 的合作式取消按鈕。"""
        button = getattr(self, "cancel_update_btn", None)
        if button is None:
            return
        button.setVisible(visible)
        button.setEnabled(visible)
        if visible:
            button.setText("取消目前工作")

    def _request_current_worker_cancel(self) -> None:
        """送出非阻塞取消請求，等待服務在安全邊界收尾。"""
        workers = list(self._worker_coordinator.active_workers_for("write"))
        requested = 0
        for worker in workers:
            cancel = getattr(worker, "cancel", None)
            if not callable(cancel):
                continue
            try:
                cancel(cooperative=True, wait=False)
                requested += 1
            except Exception as exc:
                self._log(f"取消背景工作請求失敗：{exc}")

        button = getattr(self, "cancel_update_btn", None)
        if button is not None:
            button.setEnabled(False)
        message = (
            "已送出合作式取消，等待目前日期／檔案操作安全收尾…"
            if requested
            else "目前背景工作沒有可用的合作式取消介面，仍會等待其安全完成。"
        )
        if hasattr(self, "progress_label"):
            self.progress_label.setVisible(True)
            self.progress_label.setText(message)
        if hasattr(self, "log_text"):
            self._log(message)

    def _restore_write_controls_after_cancel(self) -> None:
        """取消後恢復可操作按鈕，避免 UI 永久停在「處理中」。"""
        defaults = {
            "quick_update_all_btn": "快速更新 (跳過大型合併)",
            "safe_update_all_btn": "安全更新 (完整 CSV + SQLite)",
            "daily_update_btn": "手動下載此資料源",
            "market_update_btn": "手動下載此資料源",
            "industry_update_btn": "手動下載此資料源",
            "broker_branch_update_btn": "手動下載此資料源",
            "merge_btn": "合併每日股價",
            "force_merge_btn": "強制重新合併所有每日股價",
            "merge_broker_branch_btn": "合併券商分點",
            "calculate_tech_btn": "計算技術指標",
            "monthly_revenue_dry_run_btn": "先檢查，不寫入",
            "monthly_revenue_apply_btn": "確認後寫入月營收",
        }
        for attr, label in defaults.items():
            button = getattr(self, attr, None)
            if button is None:
                continue
            button.setEnabled(True)
            button.setText(label)

    def _on_worker_cancelled(self, worker: TaskWorker) -> None:
        """顯示合作式取消已收尾，並清理共用進度狀態。"""
        self._release_worker(worker)
        self._invalidate_detail_cache()
        self._restore_write_controls_after_cancel()
        sync_label = getattr(self, "sqlite_sync_status_label", None)
        if sync_label is not None and "執行中" in sync_label.text():
            self._set_sqlite_sync_status(
                {
                    "cancelled": True,
                    "source": "目前工作",
                    "message": "尚未完成 SQLite 同步",
                }
            )
        if hasattr(self, "progress_bar"):
            self.progress_bar.setVisible(False)
        if hasattr(self, "progress_label"):
            self.progress_label.setVisible(False)
        if hasattr(self, "log_text"):
            self._log("背景工作已取消；已完成的檔案／資料庫寫入保留，請重新檢查資料狀態。")

    def _attach_worker_cleanup(self, worker: TaskWorker):
        """向後相容的清理掛接；_start_worker 已先註冊同等保護。"""
        worker.finished.connect(lambda _payload, current_worker=worker: self._release_worker(current_worker))
        worker.error.connect(lambda _message, current_worker=worker: self._release_worker(current_worker))

    def _has_active_write_worker(self) -> bool:
        return self._worker_coordinator.has_active("write")

    def _reject_busy_write(self, operation_name: str) -> bool:
        """拒絕重疊寫入／匯出工作；唯讀狀態查詢仍可並行。"""
        if not self._has_active_write_worker() and not self.has_running_background_process():
            return False
        message = f"已有背景工作進行中，無法同時執行「{operation_name}」。請等待目前工作完成。"
        if hasattr(self, "log_text"):
            self._log(message)
        if hasattr(self, "parent"):
            QMessageBox.information(self, "背景工作進行中", message)
        return True

    def _reset_progress(self) -> None:
        self._last_progress = 0

    def _set_progress(self, message: str, percentage: int) -> int:
        """更新共用進度列，保證單一工作生命週期內不倒退。"""
        try:
            requested = max(0, min(100, int(percentage)))
        except (TypeError, ValueError):
            requested = self._last_progress
        displayed = max(self._last_progress, requested)
        self._last_progress = displayed
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_label.setText(message)
        self.progress_bar.setValue(displayed)
        return displayed

    @staticmethod
    def _safe_sync_record_count(value: Any) -> int:
        """把同步筆數正規化為非負整數，避免 UI 因 malformed payload 中止。"""
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _set_sqlite_sync_status(
        self,
        sync_result: Any,
        *,
        context: str = "",
    ) -> str:
        """在進度列下方投影最後一次 SQLite 同步結果。"""
        label = getattr(self, "sqlite_sync_status_label", None)
        payload = sync_result if isinstance(sync_result, dict) else {}
        source = str(payload.get("source") or context or "資料來源").strip()
        table = str(payload.get("table") or "").strip()
        records = self._safe_sync_record_count(payload.get("synced_records"))
        message = str(payload.get("message") or "").strip()
        if payload.get("cancelled"):
            state = "已取消"
            color = "#92400e"
            border = "#fbbf24"
        elif payload.get("status") in {"running", "in_progress"}:
            state = "執行中"
            color = "#1d4ed8"
            border = "#93c5fd"
        elif payload.get("success") is True:
            state = "完成"
            color = "#166534"
            border = "#86efac"
        elif payload:
            state = "失敗"
            color = "#b91c1c"
            border = "#fca5a5"
        else:
            state = "尚未執行"
            color = "#475569"
            border = "#cbd5e1"

        details = [f"SQLite 同步：{state}"]
        if source and state != "尚未執行":
            details.append(f"來源 {source}")
        if table:
            details.append(f"table {table}")
        if state == "完成":
            details.append(f"{records:,} 筆")
        if message:
            details.append(message)
        display = "｜".join(details)
        if label is not None:
            label.setText(display)
            label.setStyleSheet(
                "QLabel {"
                " background-color: #f8fafc;"
                f" color: {color};"
                f" border: 1px solid {border};"
                " border-radius: 6px;"
                " padding: 6px 10px;"
                " font-size: 11px;"
                "}"
            )
        return display

    def _collect_sqlite_sync_results(self, result: Any) -> list[dict[str, Any]]:
        """從一鍵更新結果收集所有 SQLite 同步步驟，包含失敗步驟。"""
        if not isinstance(result, dict):
            return []
        candidates: list[dict[str, Any]] = []
        for item in result.get("completed_steps") or []:
            if not isinstance(item, dict) or "同步" not in str(item.get("step", "")):
                continue
            payload = item.get("result")
            if isinstance(payload, dict):
                candidates.append(payload)
        failed_step = str(result.get("failed_step") or "")
        failed_payload = result.get("step_result")
        if "同步" in failed_step and isinstance(failed_payload, dict):
            candidates.append(failed_payload)
        return candidates

    def _set_sqlite_sync_status_from_update_all(self, result: Any) -> str:
        """顯示一鍵更新的 SQLite 同步彙總，避免只看到下載完成。"""
        payloads = self._collect_sqlite_sync_results(result)
        if not payloads:
            return self._set_sqlite_sync_status(None)
        failed = sum(1 for payload in payloads if payload.get("success") is False)
        records = sum(
            self._safe_sync_record_count(payload.get("synced_records"))
            for payload in payloads
        )
        state = "失敗" if failed else "完成"
        summary = {
            "success": failed == 0,
            "source": f"{len(payloads)} 個同步步驟",
            "table": "",
            "synced_records": records,
            "message": f"{state} {len(payloads) - failed}/{len(payloads)} 個步驟"
            f"，共 {records:,} 筆" if failed == 0 else
            f"{state} {failed}/{len(payloads)} 個步驟，共 {records:,} 筆",
        }
        return self._set_sqlite_sync_status(summary)

    def _invalidate_detail_cache(self) -> None:
        """寫入型工作完成後，強制下一次進入來源頁重新查詢。"""
        self._loaded_detail_sources.clear()

    def has_running_background_process(self) -> bool:
        """TPEX 獨立程序未結束時，主視窗不得假裝可安全關閉。"""
        process = self._tpex_background_process
        return process is not None and process.poll() is None

    def request_cooperative_shutdown(self) -> bool:
        """送出取消但不強制終止；回傳是否已能安全釋放本 view。"""
        for worker in list(self._active_workers):
            if worker.isRunning() and hasattr(worker, "cancel"):
                worker.cancel(cooperative=True, wait=False)
        return not any(
            worker.isRunning() for worker in self._active_workers
        ) and not self.has_running_background_process()

    def _setup_ui(self):
        """設置 UI"""
        # 最外層主布局。Update 內容遠超過窄視窗高度，使用唯讀 scroll
        # shell 保留完整來源頁與日誌，而不把主視窗鎖在所有子元件的尺寸提示。
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.content_scroll = QScrollArea(self)
        self.content_scroll.setObjectName("updateContentScroll")
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        content_widget = QWidget()
        content_widget.setObjectName("updateContentWidget")
        content_widget.setMinimumWidth(0)
        content_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.content_widget = content_widget
        outer_layout.addWidget(self.content_scroll)
        self.content_scroll.setWidget(content_widget)

        main_layout = QVBoxLayout(content_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # 1. 隱藏的 Radio Buttons（保留底層代碼的屬性相容性，使之不受改動影響）
        self.hidden_widget = QWidget()
        hidden_layout = QVBoxLayout(self.hidden_widget)
        self.update_type_group = QButtonGroup(self)
        self.daily_radio = QRadioButton("每日股票數據")
        self.market_radio = QRadioButton("大盤指數數據")
        self.industry_radio = QRadioButton("產業指數數據")
        self.broker_branch_radio = QRadioButton("券商分點資料")
        self.update_type_group.addButton(self.daily_radio, 0)
        self.update_type_group.addButton(self.market_radio, 1)
        self.update_type_group.addButton(self.industry_radio, 2)
        self.update_type_group.addButton(self.broker_branch_radio, 3)
        self.daily_radio.setChecked(True)
        hidden_layout.addWidget(self.daily_radio)
        hidden_layout.addWidget(self.market_radio)
        hidden_layout.addWidget(self.industry_radio)
        hidden_layout.addWidget(self.broker_branch_radio)
        self.hidden_widget.setVisible(False)
        main_layout.addWidget(self.hidden_widget)

        # 2. 隱藏的全域日期變數（使底層一鍵更新/單項更新抓取 UI 輸入的邏輯直接生效）
        self.end_date = QDateEdit()
        self.end_date.setDate(_taiwan_market_qdate())
        self._configure_date_edit(self.end_date)
        self.lookback_days = QSpinBox()
        self.lookback_days.setRange(1, 365)
        self.lookback_days.setValue(10)

        # 3. 左右分欄的導覽區域
        workbench_layout = QHBoxLayout()
        workbench_layout.setSpacing(15)
        self.workbench_layout = workbench_layout

        # 左側導覽列
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(160)
        self.nav_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.nav_list.setStyleSheet("""
            QListWidget {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                background-color: rgba(15, 23, 42, 0.5);
                padding: 5px;
            }
            QListWidget::item {
                height: 38px;
                border-radius: 6px;
                padding-left: 10px;
                margin-bottom: 2px;
                color: #cbd5e1;
            }
            QListWidget::item:hover {
                background-color: rgba(51, 65, 85, 0.5);
                color: #ffffff;
            }
            QListWidget::item:selected {
                background-color: #3b82f6;
                color: white;
                font-weight: bold;
            }
        """)

        self._nav_items = [
            ("all", "全部資料"),
            ("daily", "每日股價"),
            ("market", "大盤指數"),
            ("industry", "產業指數"),
            ("broker_branch", "券商分點"),
            ("technical", "技術指標"),
            ("monthly_revenue", "月營收"),
            ("institutional_flow", "三大法人"),
            ("credit_transaction", "信用交易"),
            ("tdcc_shareholding", "集保股權"),
            ("scheduler_status", "排程狀態"),
            ("db_inspector", "SQLite 資料檢視"),
        ]
        for _, label in self._nav_items:
            self.nav_list.addItem(label)

        # 右側堆疊視窗
        self.content_stack = QStackedWidget()
        self.content_stack.setMinimumWidth(0)
        self.content_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        # 建立看板（全部資料）頁面
        all_page = QWidget()
        all_page.setMinimumWidth(0)
        all_page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.all_page = all_page
        all_layout = QVBoxLayout(all_page)
        all_layout.setSpacing(15)
        all_layout.setContentsMargins(0, 0, 0, 0)

        # 頂部標題列
        title_layout = QHBoxLayout()
        title = QLabel("數據更新看板")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #f8fafc;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        info_btn = InfoButton("update", self)
        title_layout.addWidget(info_btn)
        all_layout.addLayout(title_layout)

        # 看板說明
        desc_label = QLabel("此處提供整個系統的資料狀態概覽。您可以點選下方一鍵安全更新來同步最新資料，或點選左側進行個別資料維護。")
        desc_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        desc_label.setWordWrap(True)
        desc_label.setMinimumWidth(0)
        desc_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        all_layout.addWidget(desc_label)

        # 數據狀態卡片網格（精美 StatusCard 呈現，取代原先 status_group 內多個 TextEdit）
        # 我們將它們宣告為 class member，使底層 _on_status_checked 能直接使用
        self.daily_status_text = StatusCard("每日股票數據", "", self)
        self.market_status_text = StatusCard("大盤指數數據", "", self)
        self.industry_status_text = StatusCard("產業指數數據", "", self)
        self.broker_branch_status_text = StatusCard("券商分點數據", "", self)
        self.technical_status_text = StatusCard("技術指標數據", "", self)
        self.monthly_revenue_status_text = StatusCard("月營收資料", "", self)

        # 卡片佈局
        cards_layout = QGridLayout()
        cards_layout.setSpacing(10)
        self._cards_layout = cards_layout
        self._status_cards = [
            self.daily_status_text,
            self.market_status_text,
            self.industry_status_text,
            self.broker_branch_status_text,
            self.technical_status_text,
            self.monthly_revenue_status_text,
        ]
        for card in self._status_cards:
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._reflow_grid(cards_layout, self._status_cards, columns=6)
        all_layout.addLayout(cards_layout)

        # 更新流程時間軸：只投影明確指定的 latest_status artifact，避免卡片
        # 有數字、卻看不出那是何時完成或是否仍是舊結果。
        timeline_group = QGroupBox("資料更新時間軸（唯讀）")
        timeline_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                color: #94a3b8;
            }
        """)
        timeline_layout = QVBoxLayout(timeline_group)
        timeline_layout.setSpacing(8)
        timeline_layout.setContentsMargins(12, 12, 12, 12)
        self.data_update_timeline_summary_label = QLabel(
            "尚未檢查資料更新時間軸；不會沿用上一輪結果。"
        )
        self.data_update_timeline_summary_label.setWordWrap(True)
        self.data_update_timeline_summary_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        self.data_update_timeline_summary_label.setStyleSheet(
            "color: #cbd5e1; font-size: 11px;"
        )
        timeline_layout.addWidget(self.data_update_timeline_summary_label)
        self.data_update_timeline_table = QTableWidget(0, 3)
        self.data_update_timeline_table.setHorizontalHeaderLabels(("步驟", "結果", "訊息"))
        self.data_update_timeline_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.data_update_timeline_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.data_update_timeline_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.data_update_timeline_table.setAlternatingRowColors(True)
        self.data_update_timeline_table.verticalHeader().setVisible(False)
        self.data_update_timeline_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.data_update_timeline_table.horizontalHeader().setStretchLastSection(True)
        self.data_update_timeline_table.setMinimumHeight(72)
        self.data_update_timeline_table.setToolTip(
            "只顯示明確指定的更新 status artifact；缺失、失敗或過期不會被舊資料掩蓋。"
        )
        timeline_layout.addWidget(self.data_update_timeline_table)
        history_label = QLabel("最近執行歷史（append-only／唯讀）")
        history_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        timeline_layout.addWidget(history_label)
        self.data_update_timeline_history_table = QTableWidget(0, 4)
        self.data_update_timeline_history_table.setHorizontalHeaderLabels(
            ("時間", "結果", "Run", "資料區間")
        )
        self.data_update_timeline_history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.data_update_timeline_history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.data_update_timeline_history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.data_update_timeline_history_table.setAlternatingRowColors(True)
        self.data_update_timeline_history_table.verticalHeader().setVisible(False)
        self.data_update_timeline_history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.data_update_timeline_history_table.horizontalHeader().setStretchLastSection(True)
        self.data_update_timeline_history_table.setMaximumHeight(180)
        self.data_update_timeline_history_table.setToolTip(
            "只讀取明確指定的 data-update-status-history.v1 JSONL；不會改寫或回填歷史。"
        )
        timeline_layout.addWidget(self.data_update_timeline_history_table)
        all_layout.addWidget(timeline_group)

        # 候選與決策資料域群組
        candidate_group = QGroupBox("候選與決策資料域（治理檢視 / 尚未啟用）")
        candidate_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                color: #94a3b8;
            }
        """)
        candidate_layout = QGridLayout(candidate_group)
        candidate_layout.setSpacing(10)
        candidate_layout.setContentsMargins(12, 12, 12, 12)
        self._candidate_layout = candidate_layout

        self.institutional_status_text = StatusCard("三大法人數據", "", self)
        self.credit_status_text = StatusCard("信用交易數據", "", self)
        self.tdcc_status_text = StatusCard("集保股權數據", "", self)

        self._candidate_cards = [
            self.institutional_status_text,
            self.credit_status_text,
            self.tdcc_status_text,
        ]
        for card in self._candidate_cards:
            card.setMinimumWidth(0)
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._reflow_grid(candidate_layout, self._candidate_cards, columns=3)
        all_layout.addWidget(candidate_group)

        # P0 官方來源證據面板：與核心 SQLite/CSV 狀態同頁呈現，但明確保留
        # candidate／shadow 邊界，避免使用者誤以為「抓得到」就等於已核准。
        p0_group = QGroupBox("P0 官方來源證據（候選／唯讀，不參與評分）")
        p0_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                color: #94a3b8;
            }
        """)
        p0_layout = QVBoxLayout(p0_group)
        p0_layout.setSpacing(8)
        p0_layout.setContentsMargins(12, 12, 12, 12)
        self.p0_source_control_summary_label = QLabel(
            "尚未檢查 P0 證據；此區只讀取明確指定的稽核 artifact。"
        )
        self.p0_source_control_summary_label.setWordWrap(True)
        self.p0_source_control_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.p0_source_control_summary_label.setStyleSheet(
            "color: #cbd5e1; font-size: 11px;"
        )
        p0_layout.addWidget(self.p0_source_control_summary_label)

        self.p0_source_control_table = QTableWidget(0, 8)
        self.p0_source_control_table.setHorizontalHeaderLabels(
            (
                "來源",
                "治理／Machine",
                "實際路徑",
                "Fallback",
                "PIT／公告",
                "Coverage／Rows",
                "License",
                "Owner／下游",
            )
        )
        self.p0_source_control_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.p0_source_control_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.p0_source_control_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.p0_source_control_table.setAlternatingRowColors(True)
        self.p0_source_control_table.verticalHeader().setVisible(False)
        self.p0_source_control_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.p0_source_control_table.horizontalHeader().setStretchLastSection(True)
        self.p0_source_control_table.setMinimumHeight(180)
        self.p0_source_control_table.setToolTip(
            "P0 row 只代表候選觀測與治理缺口；downstream eligibility 永遠為 none。"
        )
        p0_layout.addWidget(self.p0_source_control_table)
        all_layout.addWidget(p0_group)

        # 一鍵更新與輔助按鈕
        actions_layout = QHBoxLayout()
        self._actions_layout = actions_layout

        self.quick_update_all_btn = QPushButton("快速更新 (跳過大型合併)")
        self.quick_update_all_btn.setMinimumHeight(45)
        self.quick_update_all_btn.setProperty("variant", "primary")
        self.quick_update_all_btn.setToolTip(
            "【快速更新 (跳過大型合併)】\n"
            "速度優先。TWSE 每日股價、TPEX 每日股價與券商分點都更新結束日前最近 10 個工作日。\n"
            "TPEX 使用官方歷史查詢 endpoint，會先跳過本機已有 CSV，只補缺少日期。\n"
            "資料會直接增量同步 SQLite，但跳過 stock_data_whole 與分點 merged.csv 的大型合併重寫。"
        )
        self.quick_update_all_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8b5cf6, stop:1 #6d28d9);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #a78bfa, stop:1 #7c3aed);
            }
            QPushButton:pressed {
                background: #5b21b6;
            }
            QPushButton:disabled {
                background-color: #cbd5e1;
                color: #94a3b8;
            }
        """)
        self.quick_update_all_btn.clicked.connect(self._execute_quick_update_all)

        self.safe_update_all_btn = QPushButton("安全更新 (完整 CSV + SQLite)")
        self.safe_update_all_btn.setMinimumHeight(45)
        self.safe_update_all_btn.setProperty("variant", "primary")
        self.safe_update_all_btn.setToolTip(
            "【安全更新 (完整 CSV + SQLite)】\n"
            "備份完整性優先。TWSE 每日股價與 TPEX 每日股價會依上方日期範圍檢查並補齊缺少 CSV。\n"
            "券商分點會依上方日期範圍更新目前啟用的追蹤分點。\n"
            "完成下載後會重建每日股價大表與分點 merged.csv，再同步寫入 SQLite。\n"
            "此流程耗時較長，但能保證 CSV 歷史資料庫的完整備份。"
        )
        self.safe_update_all_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #60a5fa, stop:1 #3b82f6);
            }
            QPushButton:pressed {
                background: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #cbd5e1;
                color: #94a3b8;
            }
        """)
        self.safe_update_all_btn.clicked.connect(self._execute_safe_update_all)

        self.check_status_btn = QPushButton("檢查數據狀態")
        self.check_status_btn.setMinimumHeight(45)
        self.check_status_btn.setProperty("variant", "ghost")
        self.check_status_btn.setToolTip(
            "【檢查數據狀態】\n"
            "查詢並重新偵測 SQLite 資料庫與本地 Raw 原始檔案的最新交易日與總記錄數，\n"
            "並更新上方 6 張狀態卡片的狀態文字（最新 / 待更新 / 異常 / 未檢查）。\n"
            "檢查結果會同步呈現在頂部卡片與下方日誌主控台中。"
        )
        self.check_status_btn.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background-color: #e2e8f0;
            }
            QPushButton:pressed {
                background-color: #cbd5e1;
            }
            QPushButton:disabled {
                background-color: #f8fafc;
                color: #cbd5e1;
            }
        """)
        self.check_status_btn.clicked.connect(self._check_data_status)

        self._action_buttons = [
            self.quick_update_all_btn,
            self.safe_update_all_btn,
            self.check_status_btn,
        ]
        for button in self._action_buttons:
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        actions_layout.addWidget(self.quick_update_all_btn, stretch=2)
        actions_layout.addWidget(self.safe_update_all_btn, stretch=2)
        actions_layout.addWidget(self.check_status_btn, stretch=1)
        all_layout.addLayout(actions_layout)
        all_layout.addStretch()

        self.content_stack.addWidget(all_page)

        # 建立其他分頁
        for key, label in self._nav_items[1:]:
            if key == "db_inspector":
                config = getattr(self.update_service, "config", None)
                if config is None or not getattr(config, "use_sqlite", False):
                    page = QWidget()
                    page.setMinimumWidth(0)
                    page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                    page_layout = QVBoxLayout(page)
                    page_layout.addWidget(QLabel("SQLite 未啟用或測試環境中無可用 Config"))
                    self.content_stack.addWidget(page)
                    continue

                from app_module.sqlite_inspector_service import SqliteInspectorService
                from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
                try:
                    # Inspector 本身採唯讀連線；資料庫不存在或不可用時仍保留
                    # 頁面，讓使用者看到 unavailable，而不是讓 MainWindow 啟動失敗。
                    service = SqliteInspectorService(config)
                    page = SqliteInspectorWidget(service, self)
                except Exception as exc:
                    page = QWidget()
                    page.setMinimumWidth(0)
                    page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                    page_layout = QVBoxLayout(page)
                    page_layout.addWidget(QLabel(f"SQLite 檢視不可用：{exc}"))
                self.content_stack.addWidget(page)
                continue

            page = QWidget()
            page.setMinimumWidth(0)
            page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(15)

            # 分頁標題
            sub_title_layout = QHBoxLayout()
            sub_title = QLabel(label)
            sub_title_font = QFont()
            sub_title_font.setPointSize(13)
            sub_title_font.setBold(True)
            sub_title.setFont(sub_title_font)
            sub_title.setStyleSheet("color: #1e293b;")
            sub_title_layout.addWidget(sub_title)
            sub_title_layout.addStretch()
            page_layout.addLayout(sub_title_layout)

            self._add_source_tab_content(page_layout, key)
            self.content_stack.addWidget(page)

        self.nav_list.currentRowChanged.connect(self._on_nav_changed)

        workbench_layout.addWidget(self.nav_list)
        workbench_layout.addWidget(self.content_stack, stretch=1)
        main_layout.addLayout(workbench_layout, stretch=1)

        # 4. 底部全域共享的進度條與日誌 console
        # 進度文字與進度條
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #475569; font-size: 12px;")
        self.progress_label.setVisible(False)
        main_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                text-align: center;
                background-color: #f1f5f9;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #3b82f6;
                border-radius: 5px;
            }
        """)
        main_layout.addWidget(self.progress_bar)

        self.cancel_update_btn = QPushButton("取消目前工作", self)
        self.cancel_update_btn.setObjectName("cancel_update_btn")
        self.cancel_update_btn.setVisible(False)
        self.cancel_update_btn.setEnabled(False)
        self.cancel_update_btn.setToolTip(
            "送出合作式取消。系統會在目前 API 請求、日期或檔案寫入安全收尾後停止，"
            "不會強制終止正在使用 SQLite／檔案資源的執行緒。"
        )
        self.cancel_update_btn.setStyleSheet("""
            QPushButton {
                background-color: #fff7ed;
                color: #9a3412;
                border: 1px solid #fdba74;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ffedd5;
            }
            QPushButton:disabled {
                background-color: #f8fafc;
                color: #94a3b8;
                border-color: #cbd5e1;
            }
        """)
        self.cancel_update_btn.clicked.connect(self._request_current_worker_cancel)
        main_layout.addWidget(self.cancel_update_btn)

        self.sqlite_sync_status_label = QLabel("SQLite 同步：尚未執行", self)
        self.sqlite_sync_status_label.setWordWrap(True)
        self.sqlite_sync_status_label.setStyleSheet(
            "QLabel {"
            " background-color: #f8fafc;"
            " color: #475569;"
            " border: 1px solid #cbd5e1;"
            " border-radius: 6px;"
            " padding: 6px 10px;"
            " font-size: 11px;"
            "}"
        )
        main_layout.addWidget(self.sqlite_sync_status_label)

        # 日誌 Console
        log_group = QGroupBox("日誌主控台")
        log_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 8px;
                font-weight: bold;
                color: #475569;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(10, 2, 10, 6)
        log_layout.setSpacing(4)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #0f172a;
                color: #cbd5e1;
                font-family: 'Consolas', 'Fira Code', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #1e293b;
                border-radius: 6px;
            }
        """)
        log_layout.addWidget(self.log_text)

        # 日誌輔助工具列放在底部，避免標題下方出現整條空白列
        log_toolbar = QHBoxLayout()
        log_toolbar.setContentsMargins(0, 0, 0, 0)
        log_toolbar.setSpacing(0)
        log_toolbar.addStretch()
        clear_log_btn = QPushButton("清除日誌")
        clear_log_btn.setFixedHeight(16)
        clear_log_btn.setStyleSheet("""
            QPushButton {
                min-height: 0px;
                padding: 0px 4px;
                background-color: transparent;
                color: #64748b;
                border: none;
                font-size: 10px;
            }
            QPushButton:hover {
                color: #ef4444;
            }
        """)
        clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        log_toolbar.addWidget(clear_log_btn)
        log_layout.addLayout(log_toolbar)

        log_group.setMaximumHeight(118)  # 緊湊主控台高度，保留更多空間給上方表格
        main_layout.addWidget(log_group)

        # 初始化各資料區塊的顯示 (卡片)
        self.daily_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.market_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.industry_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.broker_branch_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.technical_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.monthly_revenue_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.institutional_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.credit_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")
        self.tdcc_status_text.setPlainText("點擊「檢查數據狀態」以查看數據狀態")

        self.nav_list.setCurrentRow(0)

    @staticmethod
    def _reflow_grid(
        layout: QGridLayout,
        widgets: list[QWidget],
        *,
        columns: int,
    ) -> None:
        """以固定欄數重排狀態卡，避免窄版六欄被壓成不可讀細條。"""

        while layout.count():
            layout.takeAt(0)
        for column in range(8):
            layout.setColumnStretch(column, 0)
        for column in range(columns):
            layout.setColumnStretch(column, 1)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, index // columns, index % columns)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """窄版將 Update 導覽、卡片與操作按鈕改為可讀的單欄／雙欄。"""

        super().resizeEvent(event)
        if not hasattr(self, "workbench_layout"):
            return

        narrow = self.width() < 720
        if self._responsive_narrow == narrow:
            return
        self._responsive_narrow = narrow

        if narrow:
            self.workbench_layout.setDirection(QBoxLayout.TopToBottom)
            self.nav_list.setMinimumWidth(0)
            self.nav_list.setMaximumWidth(16777215)
            self.nav_list.setMaximumHeight(190)
            self.nav_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.content_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self._reflow_grid(self._cards_layout, self._status_cards, columns=2)
            self._reflow_grid(self._candidate_layout, self._candidate_cards, columns=1)
            self._actions_layout.setDirection(QBoxLayout.TopToBottom)
        else:
            self.workbench_layout.setDirection(QBoxLayout.LeftToRight)
            self.nav_list.setFixedWidth(160)
            self.nav_list.setMaximumHeight(16777215)
            self.nav_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            self.content_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
            self._reflow_grid(self._cards_layout, self._status_cards, columns=6)
            self._reflow_grid(self._candidate_layout, self._candidate_cards, columns=3)
            self._actions_layout.setDirection(QBoxLayout.LeftToRight)

    @staticmethod
    def _add_source_detail_status(layout: QVBoxLayout, key: str, parent: QWidget) -> None:
        """在來源分頁放置可見的唯讀狀態摘要。"""
        detail_status = QLabel("尚未檢查此資料源狀態", parent)
        detail_status.setWordWrap(True)
        detail_status.setStyleSheet("""
            QLabel {
                background-color: #f8fafc;
                color: #334155;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 12px;
                line-height: 1.4;
            }
        """)
        setattr(parent, f"{key}_detail_status_label", detail_status)
        layout.addWidget(detail_status)

    def _set_tpex_background_status_label(
        self,
        status: str,
        *,
        message: str = "",
        updated_at: str = "",
        level: str = "info",
    ) -> None:
        """更新 TPEX 背景任務的可見狀態，避免只寫日誌而讓頁面看起來沒有反應。"""
        label = getattr(self, "tpex_background_status_label", None)
        if label is None:
            return

        status_text = {
            "running": "執行中",
            "done": "完成",
            "failed": "失敗",
            "unknown": "未知",
            "not_started": "尚未啟動",
        }.get(status, status or "未知")
        detail = f"｜最後更新：{updated_at}" if updated_at else ""
        if message:
            detail = f"{detail}｜{message}"
        label.setText(f"TPEX 背景任務：{status_text}{detail}")

        color = {
            "info": "#334155",
            "success": "#166534",
            "warning": "#92400e",
            "error": "#b91c1c",
        }.get(level, "#334155")
        border = {
            "info": "#cbd5e1",
            "success": "#86efac",
            "warning": "#fbbf24",
            "error": "#fca5a5",
        }.get(level, "#cbd5e1")
        label.setStyleSheet(
            "QLabel {"
            " background-color: #f8fafc;"
            f" color: {color};"
            f" border: 1px solid {border};"
            " border-radius: 6px;"
            " padding: 8px 10px;"
            " font-size: 12px;"
            "}"
        )

    def _add_source_tab_content(self, layout: QVBoxLayout, key: str):
        """為個別資料源維護分頁建立專屬操作與手動配置界面"""
        if key in {"institutional_flow", "credit_transaction", "tdcc_shareholding", "scheduler_status"}:
            info_group = QGroupBox("資料域狀態與治理說明")
            info_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            info_layout = QVBoxLayout(info_group)
            info_layout.setSpacing(10)

            status_desc = {
                "institutional_flow": "『三大法人』屬 Phase 3C 候選研究資料 (Candidate Data)。\n"
                                      "安全邊界說明：目前獨立於正式資料庫外，嚴禁直接參與 ScoringEngine、Recommendation、Advice、Portfolio 或任何交易邏輯。\n"
                                      "若要對 2024-07-22 至今日開展可續跑 Candidate DB 回補，請使用下方 CLI 命令。",
                "credit_transaction": "『信用交易 (融資融券)』屬 Phase 3C 候選研究資料 (Candidate Data)。\n"
                                      "安全邊界說明：獨立於正式資料庫外，嚴禁將融資券餘額假裝為 0 股或填入正式資料庫。\n"
                                      "若要開展兩年歷史可續跑 Candidate DB 回補，請使用下方 CLI 命令。",
                "tdcc_shareholding": "『集保股權』目前僅 OpenAPI `id=1-5` 提供最新單週公開資料，不支援歷史多日期輪詢回補 (BLOCKED_NO_HISTORICAL_ENDPOINT)。\n"
                                    "可用下方受控命令把官方最新週 snapshot 寫入隔離 Candidate DB；資料日採官方 payload，不會冒充成執行日。",
                "scheduler_status": "目前自動更新排程（Scheduler）處於 `Simulated/Waiting for time` 階段，且生產環境排程權限 `production_scheduler_allowed` 固定為 false。\n"
                                    "此頁面提供唯讀日誌與排程狀態檢視，嚴禁在此處手動觸發排程寫入。"
            }

            text_label = QLabel(status_desc.get(key, ""))
            text_label.setWordWrap(True)
            text_label.setStyleSheet("color: #475569; font-size: 12px; line-height: 140%;")
            info_layout.addWidget(text_label)

            if key in {"institutional_flow", "credit_transaction", "tdcc_shareholding"}:
                cli_box = QTextEdit()
                cli_box.setReadOnly(True)
                cli_box.setMaximumHeight(80)
                if key == "tdcc_shareholding":
                    cmd_str = (
                        "$env:PHASE3C_CANDIDATE_DB_PATH = 'D:/Min/Python/Project/FA_Data_candidate/phase3c_candidate.db'\n"
                        "$endDate = (Get-Date).ToString('yyyy-MM-dd')\n"
                        "python scripts/update_phase3c_candidates.py `\n"
                        "  --date $endDate --sources tdcc --include-latest-tdcc `\n"
                        "  --db-path $env:PHASE3C_CANDIDATE_DB_PATH `\n"
                        "  --confirm apply-phase3c-candidate-ingestion"
                    )
                else:
                    cmd_str = (
                        "$env:PHASE3C_CANDIDATE_DB_PATH = 'D:/Min/Python/Project/FA_Data_candidate/phase3c_candidate.db'\n"
                        "$startDate = (Get-Date).AddYears(-2).ToString('yyyy-MM-dd')\n"
                        "$endDate = (Get-Date).ToString('yyyy-MM-dd')\n"
                        "python scripts/update_phase3c_candidates.py `\n"
                        "  --start-date $startDate --end-date $endDate `\n"
                        "  --sources institutional,credit `\n"
                        "  --db-path $env:PHASE3C_CANDIDATE_DB_PATH `\n"
                        "  --confirm apply-phase3c-candidate-ingestion"
                    )
                cli_box.setPlainText(cmd_str)
                cli_box.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-family: monospace; font-size: 11px;")
                info_layout.addWidget(QLabel("可複製的安全受控 CLI 回補命令 (寫入隔離 Candidate DB)："))
                info_layout.addWidget(cli_box)

            if key == "scheduler_status":
                log_box = QTextEdit()
                log_box.setReadOnly(True)
                log_box.setPlaceholderText("背景排程尚未啟動，目前無執行日誌。")
                log_box.setStyleSheet("background-color: #0f172a; color: #cbd5e1; font-family: monospace; font-size: 11px;")
                status_path = Path(self.update_service.config.output_root) / "scheduled" / "data_freshness" / "latest_status.json"
                if status_path.exists():
                    try:
                        import json
                        status_data = json.loads(status_path.read_text(encoding="utf-8"))
                        log_box.setPlainText(json.dumps(status_data, ensure_ascii=False, indent=2))
                    except Exception as e:
                        log_box.setPlainText(f"加載排程狀態失敗: {e}")
                info_layout.addWidget(QLabel("Scheduler 狀態 (latest_status.json)："))
                info_layout.addWidget(log_box)

            layout.addWidget(info_group)

            op_group = QGroupBox("數據操作")
            op_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            button_layout = QHBoxLayout(op_group)
            check_btn = QPushButton("檢查此資料源狀態")
            check_btn.setMinimumHeight(35)
            check_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f8fafc;
                    color: #475569;
                    border: 1px solid #cbd5e1;
                    border-radius: 6px;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #f1f5f9;
                }
            """)
            check_btn.clicked.connect(lambda _checked=False, source=key: self._check_source_detail(source, force=True))
            button_layout.addWidget(check_btn)
            button_layout.addStretch()
            layout.addWidget(op_group)

            # 候選資料源也要有自己的唯讀狀態摘要；只更新頂部卡片會讓
            # 使用者進入分頁後無法判斷「檢查此資料源狀態」是否真的完成。
            if key in {"institutional_flow", "credit_transaction", "tdcc_shareholding"}:
                self._add_source_detail_status(layout, key, self)

            layout.addStretch()
            return
        descriptions = {
            "daily": "檢查與維護每日股價原始資料（TWSE + TPEX）與 SQLite 對應數據。此處支援增量合併與 Danger Zone 強制重新合併。",
            "market": "檢查與更新加權指數大盤數據。此處會將大盤資料同步儲存至資料庫的 market_indices 表。",
            "industry": "檢查與更新產業指數數據，可將各產業分類的歷史指數同步至 industry_indices 表。",
            "broker_branch": "維護 MoneyDJ 目前啟用的追蹤分點之買賣超資料，並可執行券商分點合併至 SQLite broker_flows 表。",
            "technical": "增量或全量重新計算個股的技術指標（KD, MACD, RSI 等），並高速批量儲存至資料庫中。",
            "monthly_revenue": "使用 MOPS 月營收快照檔搭配正式可得日對照檔，先檢查筆數與診斷結果，再受控寫入正式月營收資料表。",
        }

        desc_label = QLabel(descriptions.get(key, "檢查此資料來源的更新狀態。"))
        desc_label.setStyleSheet("color: #64748b; font-size: 12px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        if key == "monthly_revenue":
            config_group = QGroupBox("MOPS 月營收回填設定")
            config_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            form_layout = QFormLayout(config_group)
            form_layout.setSpacing(8)

            self.monthly_revenue_snapshot_input = QLineEdit()
            self.monthly_revenue_snapshot_input.setObjectName("monthly_revenue_snapshot_input")
            self.monthly_revenue_snapshot_input.setText(str(self._default_monthly_revenue_snapshot_path()))
            self.monthly_revenue_snapshot_input.setToolTip(
                "MOPS 月營收快照檔。系統會從這個檔案讀取各公司每月營收金額；先檢查與正式寫入都使用同一份檔案。"
            )

            self.monthly_revenue_availability_input = QLineEdit()
            self.monthly_revenue_availability_input.setObjectName("monthly_revenue_availability_input")
            self.monthly_revenue_availability_input.setText(str(self._default_monthly_revenue_availability_path()))
            self.monthly_revenue_availability_input.setToolTip(
                "正式可得日對照檔。此檔決定每筆月營收從哪一天起可被因子層讀取，用來避免偷看未來資料。"
            )

            self.monthly_revenue_source_version_input = QLineEdit()
            self.monthly_revenue_source_version_input.setObjectName("monthly_revenue_source_version_input")

            # 動態解析預設版本名稱
            snapshot_path = self._default_monthly_revenue_snapshot_path()
            default_version = "mops-static-snapshot-monthly-revenue-2026-06-16"
            if snapshot_path and snapshot_path.is_file():
                import re
                match = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", snapshot_path.name)
                if match:
                    default_version = f"mops-static-snapshot-monthly-revenue-{match.group(1)}"

            self.monthly_revenue_source_version_input.setText(default_version)
            self.monthly_revenue_source_version_input.setToolTip(
                "本次寫入版本名稱。用來區分不同批次的月營收資料，未來重跑或比對時可以追溯來源。"
            )

            def on_snapshot_changed(text: str):
                import re
                from pathlib import Path
                path = Path(text.strip())
                match = re.search(r"_(\d{4}-\d{2}-\d{2})\.csv$", path.name)
                if match:
                    self.monthly_revenue_source_version_input.setText(
                        f"mops-static-snapshot-monthly-revenue-{match.group(1)}"
                    )
            self.monthly_revenue_snapshot_input.textChanged.connect(on_snapshot_changed)

            form_layout.addRow("MOPS 月營收快照檔：", self.monthly_revenue_snapshot_input)
            form_layout.addRow("正式可得日對照檔：", self.monthly_revenue_availability_input)
            form_layout.addRow("本次寫入版本名稱：", self.monthly_revenue_source_version_input)
            layout.addWidget(config_group)

            op_group = QGroupBox("月營收資料操作")
            op_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            button_layout = QHBoxLayout(op_group)
            button_layout.setSpacing(10)

            self.monthly_revenue_dry_run_btn = QPushButton("先檢查，不寫入")
            self.monthly_revenue_dry_run_btn.setObjectName("monthly_revenue_dry_run_btn")
            self.monthly_revenue_dry_run_btn.setMinimumHeight(35)
            self.monthly_revenue_dry_run_btn.setToolTip("只檢查可回填筆數與診斷結果，不寫入正式資料庫。")
            self.monthly_revenue_dry_run_btn.clicked.connect(
                lambda _checked=False: self._execute_monthly_revenue_backfill(apply=False)
            )
            button_layout.addWidget(self.monthly_revenue_dry_run_btn)

            self.monthly_revenue_apply_btn = QPushButton("確認後寫入月營收")
            self.monthly_revenue_apply_btn.setObjectName("monthly_revenue_apply_btn")
            self.monthly_revenue_apply_btn.setMinimumHeight(35)
            self.monthly_revenue_apply_btn.setToolTip("跳出確認視窗後，使用正式可得日對照檔把 MOPS 月營收寫入正式月營收資料表。")
            self.monthly_revenue_apply_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
            self.monthly_revenue_apply_btn.clicked.connect(
                lambda _checked=False: self._execute_monthly_revenue_backfill(apply=True)
            )
            button_layout.addWidget(self.monthly_revenue_apply_btn)
            button_layout.addStretch()
            layout.addWidget(op_group)
            self._add_source_detail_status(layout, key, self)
            layout.addStretch()
            return

        # 針對需要日期設定的分頁（daily, market, industry, broker_branch）
        if key in {"daily", "market", "industry", "broker_branch"}:
            date_group = QGroupBox("手動下載日期範圍")
            date_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            date_layout = QFormLayout(date_group)
            date_layout.setSpacing(8)

            end_date_edit = QDateEdit()
            end_date_edit.setDate(_taiwan_market_qdate())
            self._configure_date_edit(end_date_edit)
            end_date_edit.setToolTip(
                "【結束日期】\n"
                "設定下載或更新資料的截止日期。\n"
                "當您在任何一個分頁修改此日期，其他分頁的結束日期將同步聯動更新。"
            )
            today_btn = QPushButton("今日")
            today_btn.setMaximumWidth(52)
            today_btn.setToolTip("將結束日期設定為今天。")
            today_btn.clicked.connect(lambda _checked=False, k=key: self._set_shared_end_date_today(k))

            lookback_spin = QSpinBox()
            lookback_spin.setRange(1, 365)
            lookback_spin.setValue(10)
            lookback_spin.setSuffix(" 天")
            lookback_spin.setToolTip(
                "【最近範圍】\n"
                "設定從「結束日期」往前推算的查找天數。\n"
                "例如設定 10 天，代表下載或檢查結束日期前 10 天內的所有交易日資料。"
            )

            end_date_row = QHBoxLayout()
            end_date_row.addWidget(end_date_edit)
            end_date_row.addWidget(self._create_calendar_button(end_date_edit))
            end_date_row.addWidget(today_btn)
            end_date_row.addStretch()
            date_layout.addRow("結束日期:", end_date_row)
            date_layout.addRow("最近範圍:", lookback_spin)
            layout.addWidget(date_group)

            setattr(self, f"{key}_end_date", end_date_edit)
            setattr(self, f"{key}_lookback", lookback_spin)

            end_date_edit.dateChanged.connect(lambda _d, k=key: self._sync_dates(k))
            lookback_spin.valueChanged.connect(lambda _v, k=key: self._sync_dates(k))

            if key == "daily":
                self.end_date = end_date_edit
                self.lookback_days = lookback_spin

        # 針對技術指標計算分頁
        if key == "technical":
            tech_group = QGroupBox("技術指標計算配置")
            tech_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #e2e8f0;
                    border-radius: 6px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: #475569;
                    font-weight: bold;
                }
            """)
            tech_layout = QVBoxLayout(tech_group)
            tech_layout.setSpacing(8)

            mode_layout = QHBoxLayout()
            mode_layout.addWidget(QLabel("計算模式:"))

            self.tech_incremental_radio = QRadioButton("增量更新（只計算新數據）")
            self.tech_incremental_radio.setChecked(True)
            self.tech_incremental_radio.setToolTip(
                "【增量更新模式】\n"
                "僅針對資料庫中最新交易日或尚未計算過指標的新股價數據進行計算。\n"
                "計算速度極快，是日常更新的首選模式。"
            )
            mode_layout.addWidget(self.tech_incremental_radio)

            self.tech_force_all_radio = QRadioButton("強制全量更新（重新計算所有數據）")
            self.tech_force_all_radio.setToolTip(
                "【強制全量更新模式】\n"
                "忽略已計算好的歷史指標，重新對資料庫內的所有股票歷史數據計算技術指標。\n"
                "運算時間較長，通常僅在修改了技術指標算法邏輯時使用。"
            )
            mode_layout.addWidget(self.tech_force_all_radio)
            mode_layout.addStretch()
            tech_layout.addLayout(mode_layout)

            stock_form = QFormLayout()
            self.tech_stock_input = QLineEdit()
            self.tech_stock_input.setPlaceholderText("留空則處理所有股票，例如：2330")
            self.tech_stock_input.setToolTip(
                "【股票代號（選填）】\n"
                "如果只想重算特定一檔股票的技術指標，請在此輸入股票代號（如 2330）。\n"
                "若保持留空，則會對資料庫中所有的股票進行計算。"
            )
            stock_form.addRow("股票代號（可選）:", self.tech_stock_input)
            tech_layout.addLayout(stock_form)

            layout.addWidget(tech_group)

        # 操作按鈕面板
        op_group = QGroupBox("數據操作")
        op_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
                color: #475569;
                font-weight: bold;
            }
        """)
        button_layout = QHBoxLayout(op_group)
        button_layout.setSpacing(10)

        check_btn = QPushButton("檢查此資料源狀態")
        check_btn.setMinimumHeight(35)
        check_btn.setToolTip(
            "【檢查此資料源狀態】\n"
            "單獨檢查此項資料來源在本地原始檔案目錄以及 SQLite 資料庫中的最新狀態（最新日期、總記錄數），\n"
            "並更新頂部的對應數據卡片與下方日誌主控台。"
        )
        check_btn.setStyleSheet("""
            QPushButton {
                background-color: #f8fafc;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
            }
        """)
        check_btn.clicked.connect(lambda _checked=False, source=key: self._check_source_detail(source, force=True))
        button_layout.addWidget(check_btn)

        if key in {"daily", "market", "industry", "broker_branch"}:
            update_btn = QPushButton("手動下載此資料源")
            setattr(self, f"{key}_update_btn", update_btn)
            update_btn.setMinimumHeight(35)
            update_btn.setToolTip(
                f"【手動下載此資料源】\n"
                f"依據上方設定的日期範圍，手動向 API/網頁端發出下載請求，將原始 CSV 檔案下載至本地 raw/ 目錄。\n"
                f"每日股價手動下載會跑 TWSE 日期範圍，TPEX 則改為區間流程嘗試抓取每個交易日；若 API 只回傳最近交易日，會自動以回應日覆蓋對應檔案。\n"
                f"提交後會自動同步 daily_price / daily_price_tpex 到 SQLite，並進行增量技術指標計算。"
            )
            update_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3b82f6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #2563eb;
                }
            """)
            update_btn.clicked.connect(lambda _checked=False, k=key: self._dispatch_update(k))
            button_layout.addWidget(update_btn)
            if key == "daily":
                self.tpex_background_btn = QPushButton("背景補齊 TPEX + 技術指標")
                self.tpex_background_btn.setMinimumHeight(35)
                self.tpex_background_btn.setToolTip(
                    "【背景補齊 TPEX + 技術指標】\n"
                    "將以背景方式執行 TPEX 區間抓取（含 fallback / 重複日短路）、同步日價到 SQLite，並立即進行技術指標增量更新。\n"
                    "任務會寫入背景狀態檔，可用「檢查背景任務狀態」隨時查看最新進度。"
                )
                self.tpex_background_btn.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f59e0b, stop:1 #d97706);
                        color: white;
                        border: none;
                        border-radius: 6px;
                        font-weight: bold;
                        padding: 6px 12px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fbbf24, stop:1 #f59e0b);
                    }
                """)
                self.tpex_background_btn.clicked.connect(self._execute_background_tpex_refresh)
                button_layout.addWidget(self.tpex_background_btn)

                self.tpex_background_status_btn = QPushButton("檢查背景任務狀態")
                self.tpex_background_status_btn.setMinimumHeight(35)
                self.tpex_background_status_btn.setToolTip(
                    "【檢查背景任務狀態】\n"
                    "讀取背景任務的 JSON 狀態檔，確認目前是 running / done / failed，以及 TPEX、SQLite、技術指標三個步驟結果。"
                )
                self.tpex_background_status_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #f8fafc;
                        color: #334155;
                        border: 1px solid #cbd5e1;
                        border-radius: 6px;
                        font-weight: bold;
                        padding: 6px 12px;
                    }
                    QPushButton:hover {
                        background-color: #e2e8f0;
                    }
                """)
                self.tpex_background_status_btn.clicked.connect(self._show_tpex_background_status)
                button_layout.addWidget(self.tpex_background_status_btn)

        if key == "daily":
            self.merge_btn = QPushButton("合併每日股價")
            self.merge_btn.setMinimumHeight(35)
            self.merge_btn.setToolTip(
                "【合併每日股價】\n"
                "將本地 daily_price/ 與 daily_price_tpex/ 目錄下下載好的單日股價 CSV 檔案，\n"
                "增量同步寫入至 SQLite 資料庫的 daily_prices 表中，\n"
                "以便大盤檢測、策略推薦與回測引擎能夠讀取到最新數據。"
            )
            self.merge_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
            self.merge_btn.clicked.connect(self._execute_merge)
            button_layout.addWidget(self.merge_btn)
        elif key == "broker_branch":
            self.merge_broker_branch_btn = QPushButton("合併券商分點")
            self.merge_broker_branch_btn.setMinimumHeight(35)
            self.merge_broker_branch_btn.setToolTip(
                "【合併券商分點】\n"
                "將本地 broker_flow/ 內目前啟用的追蹤分點買賣超 CSV 數據進行增量合併，\n"
                "並同步寫入至 SQLite 資料庫的 broker_flows 表中，供主力流向分析使用。"
            )
            self.merge_broker_branch_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10b981;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
            self.merge_broker_branch_btn.clicked.connect(self._execute_merge_broker_branch)
            button_layout.addWidget(self.merge_broker_branch_btn)
        elif key == "technical":
            self.calculate_tech_btn = QPushButton("計算技術指標")
            self.calculate_tech_btn.setMinimumHeight(35)
            self.calculate_tech_btn.setToolTip(
                "【計算技術指標】\n"
                "依據上方的指標配置，計算個股的 KD, MACD, RSI, ADX 與均線等技術指標，\n"
                "並將計算結果高速儲存至 SQLite 資料庫中。推薦與回測引擎非常依賴此指標，\n"
                "因此手動合併完股價後，務必要點擊此處計算技術指標，系統功能才能正常運作。"
            )
            self.calculate_tech_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10b981, stop:1 #059669);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #34d399, stop:1 #10b981);
                }
            """)
            self.calculate_tech_btn.clicked.connect(self._execute_calculate_technical_indicators)
            button_layout.addWidget(self.calculate_tech_btn)

        export_btn = QPushButton("匯出 CSV 備案")
        export_btn.setMinimumHeight(35)
        export_btn.setToolTip(
            "【匯出 CSV 備案】\n"
            "將 SQLite 資料庫中此資料來源所屬的資料表，匯出為 Excel 可直接開啟的\n"
            "UTF-8 with BOM 編碼的 CSV 檔案。您可以選擇匯出「最近範圍」或「全部歷史」。\n"
            "這屬於離線備份與人工調研的輔助備案功能，日常更新不需要使用。"
        )
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #475569;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #f1f5f9;
                border-color: #94a3b8;
            }
        """)
        export_btn.clicked.connect(lambda _checked=False, source=key: self._execute_export_csv(source))
        button_layout.addWidget(export_btn)
        button_layout.addStretch()
        layout.addWidget(op_group)

        if key == "daily":
            self.tpex_background_status_label = QLabel(
                "TPEX 背景任務：尚未啟動｜尚未產生狀態檔",
                self,
            )
            self.tpex_background_status_label.setWordWrap(True)
            self._set_tpex_background_status_label("not_started", level="warning")
            layout.addWidget(self.tpex_background_status_label)

        if key in {"daily", "market", "industry", "broker_branch", "technical", "monthly_revenue"}:
            self._add_source_detail_status(layout, key, self)

        if key == "daily":
            danger_group = QGroupBox("高風險操作區 (Danger Zone)")
            danger_group.setStyleSheet("""
                QGroupBox {
                    border: 1px solid #ef4444;
                    border-radius: 8px;
                    margin-top: 15px;
                    padding-top: 10px;
                    font-weight: bold;
                    color: #ef4444;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 3px 0 3px;
                }
            """)
            danger_layout = QVBoxLayout(danger_group)
            danger_layout.setSpacing(6)

            danger_desc = QLabel("注意：強制重新合併將完全忽略現有合併結果，並重新讀取 daily_price/ 底下的所有 CSV 檔案寫入資料庫。\n此操作耗時較長，通常僅在資料庫損毀或修復資料時使用。")
            danger_desc.setStyleSheet("color: #64748b; font-size: 11px;")
            danger_desc.setWordWrap(True)

            self.force_merge_btn = QPushButton("強制重新合併所有每日股價")
            self.force_merge_btn.setMinimumHeight(35)
            self.force_merge_btn.setToolTip(
                "【強制重新合併所有每日股價】\n"
                "高風險操作！忽略資料庫中已有的合併狀態，全量掃描並重新將\n"
                "raw/daily_price/ 底下的所有歷史股價 CSV 檔案重新寫入資料庫的 daily_prices 表。\n"
                "可能需要非常長的時間，通常僅在資料庫損毀或需要完全修復重整數據時使用。"
            )
            self.force_merge_btn.setStyleSheet("""
                QPushButton {
                    background-color: #ef4444;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px 12px;
                }
                QPushButton:hover {
                    background-color: #dc2626;
                }
                QPushButton:pressed {
                    background-color: #991b1b;
                }
            """)
            self.force_merge_btn.clicked.connect(self._execute_force_merge)

            danger_layout.addWidget(danger_desc)
            danger_layout.addWidget(self.force_merge_btn)
            layout.addWidget(danger_group)

        layout.addStretch()

    def _default_monthly_revenue_snapshot_path(self) -> Path:
        config = getattr(self.update_service, "config", None)
        if config is None:
            return Path("")
        snapshot_dir = getattr(config, "output_root", Path("")) / "monthly_revenue_mops_snapshots"
        selected = select_latest_monthly_revenue_snapshot(snapshot_dir)
        if selected is None:
            return snapshot_dir
        return selected

    def _default_monthly_revenue_availability_path(self) -> Path:
        config = getattr(self.update_service, "config", None)
        if config is None:
            return Path("")
        return getattr(config, "monthly_revenue_availability_file", Path(""))

    def _set_monthly_revenue_buttons_enabled(self, enabled: bool):
        for attr in ("monthly_revenue_dry_run_btn", "monthly_revenue_apply_btn"):
            button = getattr(self, attr, None)
            if button:
                button.setEnabled(enabled)

    def _execute_monthly_revenue_backfill(self, apply: bool = False):
        """Run MOPS monthly revenue dry-run or controlled SQLite apply."""
        if self._reject_busy_write("月營收處理"):
            return
        if apply:
            reply = QMessageBox.question(
                self,
                "確認寫入月營收",
                "確定要正式寫入 fundamental_monthly_revenues 嗎？\n\n"
                "系統會先建立 SQLite 備份，再用 MOPS snapshot 與正式 availability mapping 回填月營收。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        snapshot_text = self.monthly_revenue_snapshot_input.text().strip()
        availability_text = self.monthly_revenue_availability_input.text().strip()
        source_version = self.monthly_revenue_source_version_input.text().strip()

        self._set_monthly_revenue_buttons_enabled(False)
        self._reset_progress()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在處理 MOPS 月營收...")
        self.log_text.clear()
        mode_text = "正式寫入" if apply else "dry-run"
        self._log(f"開始 MOPS 月營收 {mode_text}")
        self._log(f"MOPS snapshot: {snapshot_text}")
        self._log(f"Availability mapping: {availability_text}")

        def task():
            kwargs = {
                "snapshot_file": Path(snapshot_text) if snapshot_text else None,
                "availability_file": Path(availability_text) if availability_text else None,
                "source_version": source_version or None,
            }
            if apply:
                return self.update_service.apply_mops_monthly_revenue_backfill(**kwargs)
            return self.update_service.dry_run_mops_monthly_revenue_backfill(**kwargs)

        worker = self._start_worker(TaskWorker(task), operation_kind="write")
        worker.finished.connect(lambda result, apply_mode=apply: self._on_monthly_revenue_finished(result, apply_mode))
        worker.error.connect(self._on_monthly_revenue_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_monthly_revenue_finished(self, result: Dict[str, Any], apply: bool):
        self._invalidate_detail_cache()
        self._set_monthly_revenue_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        message = result.get("message", "月營收處理完成")
        self._log(message)
        self._log(f"raw rows: {result.get('raw_row_count', 0):,}")
        self._log(f"normalized records: {result.get('normalized_record_count', result.get('inserted_count', 0)):,}")
        self._log(f"diagnostics: {result.get('diagnostic_count', 0):,}")
        backup_file = result.get("backup_file")
        if backup_file:
            self._log(f"SQLite backup: {backup_file}")

        if result.get("success", False):
            QMessageBox.information(self, "月營收處理完成", message)
            if apply:
                self._check_source_detail("monthly_revenue", force=True)
        else:
            QMessageBox.warning(self, "月營收處理失敗", message)

    def _on_monthly_revenue_error(self, error_msg: str):
        self._invalidate_detail_cache()
        self._set_monthly_revenue_buttons_enabled(True)
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        self._log(f"錯誤：{error_msg}")
        QMessageBox.critical(self, "月營收處理失敗", error_msg)

    def _configure_date_edit(self, date_edit: QDateEdit):
        date_edit.setCalendarPopup(False)
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setMinimumWidth(132)
        date_edit.setMaximumWidth(150)
        date_edit.setStyleSheet("""
            QDateEdit {
                padding-right: 7px;
            }
        """)

    def _create_calendar_button(self, date_edit: QDateEdit) -> QPushButton:
        button = QPushButton("日曆")
        button.setMaximumWidth(52)
        button.setToolTip("開啟日曆選擇日期")
        button.setStyleSheet("""
            QPushButton {
                background-color: #f8fafc;
                color: #334155;
                border: 1px solid #94a3b8;
                border-radius: 5px;
                padding: 3px 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #e0f2fe;
                border-color: #0284c7;
            }
            QPushButton:pressed {
                background-color: #bae6fd;
            }
        """)
        button.clicked.connect(lambda _checked=False, edit=date_edit, anchor=button: self._show_calendar_popup(edit, anchor))
        return button

    def _show_calendar_popup(self, date_edit: QDateEdit, anchor: QPushButton):
        popup = QFrame(None, Qt.Popup)
        popup.setFrameShape(QFrame.StyledPanel)
        popup_layout = QVBoxLayout(popup)
        popup_layout.setContentsMargins(4, 4, 4, 4)
        calendar = QCalendarWidget(popup)
        selected_date = date_edit.date()
        calendar.setGridVisible(True)
        calendar.setMinimumSize(340, 280)
        calendar.setCurrentPage(selected_date.year(), selected_date.month())
        calendar.setSelectedDate(selected_date)
        calendar.setStyleSheet("""
            QCalendarWidget QToolButton {
                min-width: 44px;
                min-height: 24px;
                padding: 2px 6px;
            }
            QCalendarWidget QAbstractItemView {
                font-size: 12px;
                min-width: 300px;
                min-height: 210px;
                selection-background-color: #2563eb;
                selection-color: white;
            }
        """)
        calendar.clicked.connect(lambda selected, edit=date_edit, frame=popup: self._apply_calendar_date(edit, selected, frame))
        popup_layout.addWidget(calendar)
        popup.move(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        self._calendar_popup = popup
        popup.show()

    def _apply_calendar_date(self, date_edit: QDateEdit, selected_date: QDate, popup: QFrame):
        date_edit.setDate(selected_date)
        popup.close()

    def _set_shared_end_date_today(self, source_name: str):
        end_date_widget = getattr(self, f"{source_name}_end_date", None)
        if end_date_widget:
            end_date_widget.setDate(_taiwan_market_qdate())
            self._sync_dates(source_name)

    def _sync_dates(self, source_name: str):
        """同步不同分頁的日期範圍元件"""
        try:
            end_date_widget = getattr(self, f"{source_name}_end_date", None)
            lookback_widget = getattr(self, f"{source_name}_lookback", None)

            if not end_date_widget or not lookback_widget:
                return

            target_date = end_date_widget.date()
            target_days = lookback_widget.value()

            # 同步全域變數 (供底層業務代碼使用)
            self.end_date.setDate(target_date)
            self.lookback_days.setValue(target_days)

            # 同步其他分頁的元件
            for name in ["daily", "market", "industry", "broker_branch"]:
                if name == source_name:
                    continue

                other_date = getattr(self, f"{name}_end_date", None)
                other_days = getattr(self, f"{name}_lookback", None)

                if other_date:
                    other_date.blockSignals(True)
                    other_date.setDate(target_date)
                    other_date.blockSignals(False)

                if other_days:
                    other_days.blockSignals(True)
                    other_days.setValue(target_days)
                    other_days.blockSignals(False)
        except Exception as exc:
            self._log(f"日期範圍同步失敗（{source_name}）：{exc}")

    def _dispatch_update(self, key: str):
        """代理各分頁的開始下載更新，並設定對應的 Radio 按鈕與日期"""
        radio_map = {
            "daily": self.daily_radio,
            "market": self.market_radio,
            "industry": self.industry_radio,
            "broker_branch": self.broker_branch_radio
        }
        radio_btn = radio_map.get(key)
        if radio_btn:
            radio_btn.setChecked(True)

        end_date_widget = getattr(self, f"{key}_end_date", None)
        lookback_widget = getattr(self, f"{key}_lookback", None)
        if end_date_widget and lookback_widget:
            self.end_date.setDate(end_date_widget.date())
            self.lookback_days.setValue(lookback_widget.value())

        self._execute_update()

    def _on_nav_changed(self, row: int):
        """切換工作台頁面並同步單項更新類型"""
        if row < 0:
            return
        self.content_stack.setCurrentIndex(row)
        key = self._nav_items[row][0]

        if key == "daily":
            self.daily_radio.setChecked(True)
        elif key == "market":
            self.market_radio.setChecked(True)
        elif key == "industry":
            self.industry_radio.setChecked(True)
        elif key == "broker_branch":
            self.broker_branch_radio.setChecked(True)
        elif key in {"institutional_flow", "credit_transaction", "tdcc_shareholding", "scheduler_status"}:
            pass
        elif key == "db_inspector":
            inspector_widget = self.content_stack.widget(row)
            if hasattr(inspector_widget, "refresh_tables"):
                inspector_widget.refresh_tables()
            return

        if key != "all" and key not in self._loaded_detail_sources:
            self._check_source_detail(key)

    def _check_data_status(self):
        """檢查數據狀態"""
        try:
            self.check_status_btn.setEnabled(False)
            self.check_status_btn.setText("檢查中...")

            # 在背景執行
            def check_task():
                return self._get_overview_status()

            worker = self._start_worker(TaskWorker(check_task))
            worker.finished.connect(self._on_status_checked)
            worker.error.connect(self._on_status_error)
            self._attach_worker_cleanup(worker)
            worker.start()

        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"檢查數據狀態失敗：\n{str(e)}")
            self.check_status_btn.setEnabled(True)
            self.check_status_btn.setText("檢查數據狀態")

    def _get_overview_status(self) -> Dict[str, Any]:
        """取得全部資料頁使用的輕量狀態"""
        if hasattr(self.update_service, "check_data_overview"):
            res = self.update_service.check_data_overview()
        else:
            res = self.update_service.check_data_status()

        # 呼叫 Service 層以維護架構邊界，不直連 SQLite
        if hasattr(self.update_service, "check_decision_data_status"):
            decision_status = self.update_service.check_decision_data_status()
            res.update(decision_status)
        else:
            # 測試或 Mock Service 時的向下相容預設值
            if 'institutional_flow' not in res:
                res['institutional_flow'] = {'total_records': 0, 'latest_date': '無', 'status': 'MISSING'}
            if 'credit_transaction' not in res:
                res['credit_transaction'] = {'total_records': 0, 'latest_date': '無', 'status': 'MISSING'}
            if 'tdcc_shareholding' not in res:
                res['tdcc_shareholding'] = {'total_records': 0, 'latest_date': '無', 'status': 'MISSING'}
        res["data_update_timeline"] = self._get_data_update_timeline()
        p0_center, p0_error, p0_reference = self._load_p0_source_control_center()
        return compose_source_status_projection(
            res,
            p0_control_center=p0_center,
            p0_load_error=p0_error,
            p0_reference=p0_reference,
        )

    def _get_data_update_timeline(self) -> Dict[str, Any]:
        """只讀取明確設定的更新狀態 artifact；讀取失敗時回傳可見的 fail-closed 結果。"""
        try:
            return load_data_update_timeline(
                update_status_path=self.data_update_status_path,
                freshness_status_path=self.data_freshness_status_path,
                tpex_status_path=self.tpex_status_path,
                history_path=self.data_update_history_path,
            )
        except Exception as exc:
            # 狀態面板不能因 artifact 異常而讓整個資料頁消失，也不能退回
            # 上一次成功摘要；保留明確診斷供 UI／log 排錯。
            return {
                "schema_version": "data-update-timeline.v1",
                "status": "invalid",
                "source": "scheduled_data_update",
                "last_success_at": None,
                "last_attempt_at": None,
                "age_seconds": None,
                "steps": [],
                "step_count": 0,
                "failed_step_count": 0,
                "history": {
                    "status": "invalid",
                    "configured": self.data_update_history_path is not None,
                    "available": False,
                    "records": [],
                    "record_count": 0,
                    "diagnostics": ["history:not_loaded"],
                },
                "diagnostics": [f"timeline_loader_error:{type(exc).__name__}:{exc}"],
                "boundary": {
                    "read_only": True,
                    "writes_allowed": False,
                    "network_allowed": False,
                    "explicit_paths_only": True,
                },
            }

    @staticmethod
    def _format_timeline_age(value: Any) -> str:
        try:
            seconds = max(0, int(value))
        except (TypeError, ValueError):
            return "未知"
        days, remainder = divmod(seconds, 24 * 60 * 60)
        hours, remainder = divmod(remainder, 60 * 60)
        minutes, _ = divmod(remainder, 60)
        if days:
            return f"{days} 天 {hours} 小時"
        if hours:
            return f"{hours} 小時 {minutes} 分"
        return f"{minutes} 分鐘"

    @staticmethod
    def _timeline_status_text(value: Any) -> str:
        return {
            "current": "最新",
            "partial": "部分可用",
            "degraded": "freshness 異常",
            "stale": "已過期",
            "running": "執行中",
            "failed": "失敗",
            "missing": "缺漏",
            "empty": "尚未建立",
            "invalid": "格式異常",
            "not_configured": "未設定",
            "passed": "完成",
            "success": "完成",
            "succeeded": "完成",
            "done": "完成",
            "ok": "完成",
            "completed": "完成",
            "failure": "失敗",
            "error": "錯誤",
            "blocked": "阻擋",
            "unknown": "未知",
        }.get(str(value or "").strip().lower(), str(value or "未知"))

    @staticmethod
    def _timeline_status_color(value: Any) -> str:
        return {
            "current": "#86efac",
            "partial": "#fbbf24",
            "degraded": "#fbbf24",
            "stale": "#fbbf24",
            "running": "#38bdf8",
            "in_progress": "#38bdf8",
            "started": "#38bdf8",
            "failed": "#fca5a5",
            "failure": "#fca5a5",
            "error": "#fca5a5",
            "blocked": "#fca5a5",
            "missing": "#fca5a5",
            "invalid": "#fca5a5",
            "not_configured": "#94a3b8",
            "unknown": "#94a3b8",
            "passed": "#86efac",
            "success": "#86efac",
            "succeeded": "#86efac",
            "done": "#86efac",
            "ok": "#86efac",
            "completed": "#86efac",
        }.get(str(value or "").strip().lower(), "#cbd5e1")

    def _render_data_update_timeline(self, payload: Any) -> None:
        """把更新時間軸及步驟結果投影到看板，並清除本輪沒有的舊列。"""
        label = getattr(self, "data_update_timeline_summary_label", None)
        table = getattr(self, "data_update_timeline_table", None)
        if label is None or table is None:
            return
        value = payload if isinstance(payload, dict) else {}
        status = str(value.get("status") or "not_configured")
        status_text = self._timeline_status_text(status)
        lines = [f"狀態：{status_text}（{status}）"]
        last_success = str(value.get("last_success_at") or "").strip()
        last_attempt = str(value.get("last_attempt_at") or "").strip()
        if last_success:
            lines.append(f"最後成功完成：{last_success}")
        elif last_attempt:
            lines.append(f"最後嘗試：{last_attempt}（本輪未取得成功完成證據）")
        else:
            lines.append("最後成功完成：未提供")
        age = value.get("age_seconds")
        if isinstance(age, int):
            lines.append(f"距今：{self._format_timeline_age(age)}")
        target_date = str(value.get("target_date") or "").strip()
        if target_date:
            lines.append(f"目標資料日：{target_date}")
        run_id = str(value.get("run_id") or "").strip()
        if run_id:
            lines.append(f"Run：{run_id}")
        freshness = value.get("artifacts", {}).get("freshness") if isinstance(value.get("artifacts"), dict) else None
        if isinstance(freshness, dict):
            freshness_status = str(freshness.get("status") or "").strip()
            if freshness_status:
                freshness_age = freshness.get("age_seconds")
                freshness_suffix = (
                    f"（距今 {self._format_timeline_age(freshness_age)}）"
                    if isinstance(freshness_age, int)
                    else ""
                )
                lines.append(f"Freshness 檢查：{freshness_status}{freshness_suffix}")
        tpex = value.get("artifacts", {}).get("tpex") if isinstance(value.get("artifacts"), dict) else None
        if isinstance(tpex, dict) and tpex.get("available"):
            tpex_status = str(tpex.get("status") or "unknown")
            tpex_at = str(tpex.get("completed_at") or "").strip()
            tpex_suffix = f"（{tpex_at}）" if tpex_at else ""
            lines.append(f"TPEX 背景：{tpex_status}{tpex_suffix}")
        history = value.get("history")
        if isinstance(history, dict):
            history_status = str(history.get("status") or "unknown").strip()
            history_count = history.get("record_count")
            if history_status == "current" and isinstance(history_count, int):
                lines.append(f"執行歷史：{history_count} 筆 append-only")
            elif history_status == "missing":
                lines.append("執行歷史：缺漏（新版 runner 尚未產生；不回填舊 latest）")
            elif history_status == "empty":
                lines.append("執行歷史：尚未建立（等待下一次真實排程）")
            elif history_status == "invalid":
                lines.append("執行歷史：格式異常（請修復 JSONL）")
            elif history.get("configured"):
                lines.append(f"執行歷史：{self._timeline_status_text(history_status)}")
        diagnostics = [str(item) for item in value.get("diagnostics", []) if str(item).strip()]
        if diagnostics:
            lines.append("診斷：" + "；".join(diagnostics[:3]))
        lines.append("邊界：唯讀、明確路徑、不啟動網路或寫入")
        label.setText("\n".join(lines))
        label.setStyleSheet(
            f"color: {self._timeline_status_color(status)}; font-size: 11px;"
        )

        table.setRowCount(0)
        steps = value.get("steps") if isinstance(value.get("steps"), list) else []
        for raw_step in steps:
            if not isinstance(raw_step, dict):
                continue
            row_index = table.rowCount()
            table.insertRow(row_index)
            raw_status = str(raw_step.get("status") or "unknown").strip().lower()
            cells = (
                str(raw_step.get("name") or "未命名步驟"),
                raw_status,
                str(raw_step.get("message") or ""),
            )
            for column_index, cell in enumerate(cells):
                item = QTableWidgetItem(cell)
                if column_index == 1:
                    item.setToolTip(
                        f"{self._timeline_status_text(raw_status)}（{raw_status}）"
                    )
                    item.setForeground(QColor(self._timeline_status_color(raw_status)))
                else:
                    item.setToolTip(cell)
                table.setItem(row_index, column_index, item)

        history_table = getattr(self, "data_update_timeline_history_table", None)
        if history_table is None:
            return
        history_table.setRowCount(0)
        history = value.get("history") if isinstance(value.get("history"), dict) else {}
        records = history.get("records") if isinstance(history.get("records"), list) else []
        for raw_record in reversed(records[-32:]):
            if not isinstance(raw_record, dict):
                continue
            row_index = history_table.rowCount()
            history_table.insertRow(row_index)
            completed_at = str(
                raw_record.get("completed_at")
                or raw_record.get("started_at")
                or raw_record.get("captured_at")
                or "未知"
            )
            start_date = str(raw_record.get("start_date") or "")
            end_date = str(raw_record.get("end_date") or "")
            period = f"{start_date} ~ {end_date}" if start_date or end_date else "未提供"
            raw_status = str(raw_record.get("status") or "unknown").strip().lower()
            cells = (
                completed_at,
                raw_status,
                str(raw_record.get("run_id") or "未知"),
                period,
            )
            for column_index, cell in enumerate(cells):
                item = QTableWidgetItem(cell)
                if column_index == 1:
                    item.setToolTip(
                        f"{self._timeline_status_text(raw_status)}（{raw_status}）"
                    )
                    item.setForeground(QColor(self._timeline_status_color(raw_status)))
                else:
                    item.setToolTip(cell)
                history_table.setItem(row_index, column_index, item)

    def _load_p0_source_control_center(
        self,
    ) -> tuple[P0SourceControlCenterDTO | None, str | None, str]:
        """只讀取明確指定的 P0 artifact；任何錯誤均回傳 fail-closed 投影。"""
        audit = None
        license_evidence = None
        decisions = ()
        references: list[str] = []
        try:
            if self.p0_source_audit_path is not None:
                references.append(str(self.p0_source_audit_path))
                if not self.p0_source_audit_path.is_file():
                    raise FileNotFoundError(
                        f"P0 稽核 artifact 不存在：{self.p0_source_audit_path}"
                    )
                parsed_audit = json.loads(self.p0_source_audit_path.read_text(encoding="utf-8"))
                if not isinstance(parsed_audit, dict):
                    raise TypeError("P0 稽核 artifact 根節點必須是 object")
                audit = parsed_audit
            if self.p0_license_evidence_path is not None:
                references.append(str(self.p0_license_evidence_path))
                if not self.p0_license_evidence_path.is_file():
                    raise FileNotFoundError(
                        f"P0 license 候選證據 artifact 不存在：{self.p0_license_evidence_path}"
                    )
                parsed_license = json.loads(
                    self.p0_license_evidence_path.read_text(encoding="utf-8")
                )
                if not isinstance(parsed_license, dict):
                    raise TypeError("P0 license 候選證據 artifact 根節點必須是 object")
                license_evidence = parsed_license
            if self.p0_source_decision_path is not None:
                references.append(str(self.p0_source_decision_path))
                if not self.p0_source_decision_path.is_file():
                    raise FileNotFoundError(
                        f"P0 owner decision artifact 不存在：{self.p0_source_decision_path}"
                    )
                parsed_decisions = json.loads(
                    self.p0_source_decision_path.read_text(encoding="utf-8")
                )
                decisions = parse_source_acceptance_decisions(parsed_decisions)
            center = self._p0_control_center_service.build(
                candidate_audit=audit,
                license_evidence=license_evidence,
                decisions=decisions,
            )
            reference = ", ".join(references) if references else "未設定（contract-only default）"
            return center, None, reference
        except Exception as exc:
            # 仍保留 13 項 contract rows，讓 UI 明確顯示「artifact 讀取失敗」；
            # 不能在讀取失敗時退回成看似正常的 research shadow。
            try:
                center = self._p0_control_center_service.build()
            except Exception:
                center = None
            reference = ", ".join(references) if references else "未設定"
            return center, f"{type(exc).__name__}: {exc}", reference

    @staticmethod
    def _p0_status_color(status: str) -> str:
        return {
            "research_shadow": "#a78bfa",
            "contract_only": "#a78bfa",
            "governance_review": "#f59e0b",
            "blocked_provenance": "#ef4444",
            "audit_unavailable": "#ef4444",
            "not_available": "#94a3b8",
        }.get(str(status or "").strip().lower(), "#94a3b8")

    @staticmethod
    def _p0_percent_text(value: Any) -> str:
        try:
            basis_points = int(value)
        except (TypeError, ValueError):
            return "未提供"
        if basis_points < 0 or basis_points > 10_000:
            return "未提供"
        return f"{basis_points // 100}.{basis_points % 100:02d}%"

    @staticmethod
    def _p0_count_text(value: Any) -> str:
        try:
            return f"{max(0, int(value or 0)):,}"
        except (TypeError, ValueError):
            return "--"

    @classmethod
    def _format_p0_source_row(cls, row: Dict[str, Any]) -> tuple[str, ...]:
        source_id = str(row.get("source_id") or "未知來源")
        label = str(row.get("label") or source_id)
        governance = str(row.get("governance_status") or "unknown")
        machine = str(row.get("machine_status") or "not_observed")
        route_id = str(row.get("acquisition_route_id") or "未觀測")
        route_ids = row.get("acquisition_route_ids") or []
        route_ids_text = ", ".join(str(item) for item in route_ids if str(item).strip())
        if route_ids_text and route_ids_text != route_id:
            route_display = f"{route_id}\n可用路徑：{route_ids_text}"
        else:
            route_display = route_id
        fallback_used = row.get("fallback_used")
        fallback_attempted = row.get("fallback_attempted")
        fallback_route = str(
            row.get("fallback_acquisition_route_id")
            or row.get("fallback_endpoint_id")
            or ""
        ).strip()
        fallback_outcome = str(
            row.get("fallback_probe_outcome")
            or row.get("fallback_official_status")
            or row.get("fallback_error_type")
            or ""
        ).strip()
        fallback_reason = str(row.get("fallback_reason") or "").strip()
        if fallback_used is True:
            fallback_from = str(row.get("fallback_from_route_id") or "來源未提供")
            fallback_display = f"是（{fallback_from}）"
            if fallback_route:
                fallback_display += f"\n採用路徑：{fallback_route}"
            if fallback_reason:
                fallback_display += f"\n{fallback_reason}"
        elif fallback_attempted is True:
            fallback_display = "否（已嘗試但未採用）"
            if fallback_outcome:
                fallback_display += f"\n結果：{fallback_outcome}"
            if fallback_route:
                fallback_display += f"\n替代路徑：{fallback_route}"
            requested_date = str(row.get("fallback_requested_date") or "").strip()
            observation_dates = row.get("fallback_observation_dates") or []
            observation_text = ", ".join(
                str(item) for item in observation_dates if str(item).strip()
            )
            if requested_date:
                fallback_display += f"\n要求日：{requested_date}"
            if observation_text:
                fallback_display += f"\n觀測日：{observation_text}"
            # 舊版正規化器會把 ``fallback_from:*`` 當作路徑 lineage 的
            # 合成說明；fallback 未採用時不能把它誤顯示成失敗原因。
            if fallback_reason and not fallback_reason.startswith("fallback_from:"):
                fallback_display += f"\n{fallback_reason}"
        elif fallback_used is False:
            fallback_display = "否"
        else:
            fallback_display = "未提供"
        pit_status = str(row.get("pit_status") or "未提供")
        availability = str(row.get("availability") or row.get("audit_status") or "未提供")
        pit_display = f"{pit_status}\n可得性：{availability}"
        timestamp_kind = str(row.get("timestamp_kind") or "")
        probe_outcome = str(row.get("probe_outcome") or "")
        if timestamp_kind:
            pit_display += f"\nclass：{timestamp_kind}"
        if probe_outcome:
            pit_display += f"\nprobe：{probe_outcome}"
        coverage = cls._p0_percent_text(row.get("coverage_bp"))
        observed = cls._p0_count_text(row.get("observed_rows"))
        accepted = cls._p0_count_text(row.get("accepted_rows"))
        blocked = cls._p0_count_text(row.get("blocked_rows"))
        coverage_display = f"{coverage}\naccepted {accepted} / observed {observed}\nblocked {blocked}"
        license_display = str(row.get("license_status") or "未提供")
        license_urls = row.get("license_evidence_urls") or []
        if license_urls:
            license_display += f"\n證據 URL：{len(license_urls)}"
        capture_status = str(row.get("license_evidence_capture_status") or "not_supplied")
        if capture_status != "not_supplied":
            license_display += f"\n候選證據：{capture_status}"
        capture_hashes = row.get("license_evidence_content_sha256") or []
        if capture_hashes:
            license_display += f"\n內容 hash：{len(capture_hashes)}"
        keyword_groups = row.get("license_evidence_keyword_groups") or []
        if keyword_groups:
            license_display += f"\n限制提示：{len(keyword_groups)} 組"
        decision = str(row.get("decision_status") or "not_supplied")
        eligibility = str(row.get("downstream_eligibility") or "none")
        owner_display = f"{decision}\n下游：{eligibility}"
        return (
            f"{label}\n{source_id}",
            f"{governance}\n{machine}",
            route_display,
            fallback_display,
            pit_display,
            coverage_display,
            license_display,
            owner_display,
        )

    def _render_p0_source_control_status(self, payload: Any) -> None:
        """將 P0 projection 投影到可讀表格；不以顏色取代狀態文字。"""
        table = getattr(self, "p0_source_control_table", None)
        label = getattr(self, "p0_source_control_summary_label", None)
        if table is None or label is None:
            return
        value = payload if isinstance(payload, dict) else {}
        status = str(value.get("status") or "not_available")
        source_count = self._p0_count_text(value.get("source_count"))
        summary = value.get("summary") if isinstance(value.get("summary"), dict) else {}
        governance_counts = summary.get("governance_status_counts") or {}
        machine_counts = summary.get("machine_status_counts") or {}
        decision_counts = summary.get("decision_status_counts") or {}
        governance_text = ", ".join(
            f"{key} {self._p0_count_text(item)}"
            for key, item in governance_counts.items()
        ) or "未提供"
        machine_text = ", ".join(
            f"{key} {self._p0_count_text(item)}"
            for key, item in machine_counts.items()
        ) or "未提供"
        decision_text = ", ".join(
            f"{key} {self._p0_count_text(item)}"
            for key, item in decision_counts.items()
        ) or "未提供"
        license_capture_counts = summary.get("license_evidence_capture_status_counts") or {}
        lines = [
            f"P0 狀態：{status}｜來源：{source_count}｜治理：{governance_text}",
            f"Machine：{machine_text}｜Owner 決議：{decision_text}",
            "唯讀邊界：writes=false、formal_oos=false、scheduler=false、"
            "auto_accept=false、downstream_eligibility=none",
        ]
        if license_capture_counts and set(license_capture_counts) != {"not_supplied"}:
            license_capture_text = ", ".join(
                f"{key} {self._p0_count_text(item)}"
                for key, item in license_capture_counts.items()
            )
            lines.append(f"License 候選證據：{license_capture_text}")
        observed_rows = summary.get("observed_rows")
        accepted_rows = summary.get("accepted_rows")
        blocked_rows = summary.get("blocked_rows")
        if observed_rows is not None or accepted_rows is not None or blocked_rows is not None:
            lines.append(
                "Rows：observed {0} / accepted {1} / blocked {2}".format(
                    self._p0_count_text(observed_rows),
                    self._p0_count_text(accepted_rows),
                    self._p0_count_text(blocked_rows),
                )
            )
        fallback_attempted_count = summary.get("fallback_attempted_count")
        fallback_used_count = summary.get("fallback_used_count")
        fallback_rejected_count = summary.get("fallback_rejected_count")
        if any(
            value is not None
            for value in (
                fallback_attempted_count,
                fallback_used_count,
                fallback_rejected_count,
            )
        ):
            lines.append(
                "Fallback：已嘗試 {0}／已採用 {1}／未採用 {2}".format(
                    self._p0_count_text(fallback_attempted_count),
                    self._p0_count_text(fallback_used_count),
                    self._p0_count_text(fallback_rejected_count),
                )
            )
        reference = str(value.get("reference") or "").strip()
        if reference:
            lines.append(f"Artifact：{reference}")
        load_error = str(value.get("load_error") or "").strip()
        if load_error:
            lines.append(f"讀取問題：{load_error}")
        label.setText("\n".join(lines))
        label.setStyleSheet(
            f"color: {self._p0_status_color(status)}; font-size: 11px;"
        )

        rows = value.get("rows") if isinstance(value.get("rows"), list) else []
        table.setRowCount(0)
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                continue
            row_index = table.rowCount()
            table.insertRow(row_index)
            display_values = self._format_p0_source_row(raw_row)
            for column_index, display_value in enumerate(display_values):
                item = QTableWidgetItem(display_value)
                item.setToolTip(display_value)
                if column_index == 1:
                    item.setForeground(QColor(self._p0_status_color(raw_row.get("governance_status", ""))))
                table.setItem(row_index, column_index, item)
            blockers = raw_row.get("blockers") or []
            owner_actions = raw_row.get("owner_actions") or []
            license_urls = raw_row.get("license_evidence_urls") or []
            extra = [str(item) for item in (*blockers, *owner_actions) if str(item).strip()]
            extra.extend(
                f"license_evidence_url={item}"
                for item in license_urls
                if str(item).strip()
            )
            fallback_diagnostics = []
            if raw_row.get("fallback_attempted") is True:
                fallback_diagnostics.append(
                    "fallback_attempted=true"
                )
            for key in (
                "fallback_probe_outcome",
                "fallback_official_status",
                "fallback_endpoint_id",
                "fallback_acquisition_route_id",
                "fallback_http_status",
                "fallback_requested_date",
                "fallback_error_type",
                "fallback_error",
                "fallback_payload_sha256",
                "fallback_payload_size_bytes",
                "primary_official_status",
            ):
                raw_value = raw_row.get(key)
                if raw_value not in (None, "", []):
                    fallback_diagnostics.append(f"{key}={raw_value}")
            for key in ("fallback_observation_dates", "fallback_quarantine_reasons"):
                values = raw_row.get(key) or []
                if values:
                    fallback_diagnostics.append(
                        f"{key}={';'.join(str(item) for item in values)}"
                    )
            extra.extend(fallback_diagnostics)
            if extra:
                for column_index in range(table.columnCount()):
                    item = table.item(row_index, column_index)
                    if item is not None:
                        item.setToolTip(f"{item.toolTip()}\n缺口／下一步：{'；'.join(extra)}")

    def _get_source_detail(self, source: str) -> Dict[str, Any]:
        """取得單一資料來源詳細狀態並包成 UI 可套用的狀態 dict"""
        source_map = {
            "daily": "daily_data",
            "market": "market_index",
            "industry": "industry_index",
            "broker_branch": "broker_branch",
            "technical": "technical_indicators",
            "monthly_revenue": "monthly_revenue",
            "institutional_flow": "institutional_flow",
            "credit_transaction": "credit_transaction",
            "tdcc_shareholding": "tdcc_shareholding",
            "scheduler_status": "scheduler_status",
        }
        status_key = source_map.get(source, source)
        if hasattr(self.update_service, "check_source_detail"):
            return {status_key: self.update_service.check_source_detail(source)}
        return {status_key: self.update_service.check_data_status().get(status_key, {})}

    def _check_source_detail(self, source: str, force: bool = False):
        """背景載入單一資料來源的詳細狀態"""
        if not force and source in self._loaded_detail_sources:
            return

        def check_task():
            return {"source": source, "status": self._get_source_detail(source)}

        worker = self._start_worker(TaskWorker(check_task))
        worker.finished.connect(self._on_source_detail_checked)
        worker.error.connect(
            lambda error_msg, current_source=source: self._on_source_detail_error(
                current_source, error_msg
            )
        )
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_source_detail_checked(self, payload: Dict[str, Any]):
        """單一資料來源詳細狀態載入完成"""
        source = payload.get("source")
        status = payload.get("status", {})
        if source:
            self._loaded_detail_sources.add(source)
        source_key = {
            "daily": "daily_data",
            "market": "market_index",
            "industry": "industry_index",
            "broker_branch": "broker_branch",
            "technical": "technical_indicators",
            "monthly_revenue": "monthly_revenue",
            "institutional_flow": "institutional_flow",
            "credit_transaction": "credit_transaction",
            "tdcc_shareholding": "tdcc_shareholding",
        }.get(str(source or ""))
        if source_key:
            detail = status.get(source_key)
            if isinstance(detail, dict):
                self._set_status_card(source_key, detail)
        self._render_source_detail_status(str(source or ""), status)

    def _on_source_detail_error(self, source: str, error_msg: str) -> None:
        """只呈現單一來源詳情錯誤，避免污染全域狀態卡。"""
        self._loaded_detail_sources.discard(source)
        source_key = {
            "daily": "daily_data",
            "market": "market_index",
            "industry": "industry_index",
            "broker_branch": "broker_branch",
            "technical": "technical_indicators",
            "monthly_revenue": "monthly_revenue",
            "institutional_flow": "institutional_flow",
            "credit_transaction": "credit_transaction",
            "tdcc_shareholding": "tdcc_shareholding",
        }.get(source)
        detail = {
            "latest_date": None,
            "total_records": 0,
            "status": f"error: {error_msg}",
            "warnings": [f"error: {error_msg}"],
        }
        if source_key:
            self._set_status_card(source_key, detail)
            self._render_source_detail_status(source, {source_key: detail})
        source_label = {
            "daily": "每日股價",
            "market": "大盤指數",
            "industry": "產業指數",
            "broker_branch": "券商分點",
            "technical": "技術指標",
            "monthly_revenue": "月營收",
            "institutional_flow": "三大法人",
            "credit_transaction": "信用交易",
            "tdcc_shareholding": "集保股權",
            "scheduler_status": "排程狀態",
        }.get(source, source or "資料來源")
        self._log(f"{source_label}狀態檢查失敗：{error_msg}")
        QMessageBox.warning(
            self,
            "資料來源檢查失敗",
            f"{source_label}狀態檢查失敗：\n{error_msg}",
        )

    def _format_status_token(self, status: Any) -> str:
        return format_status_token(status)

    def _format_source_detail_summary(self, source: str, detail: Dict[str, Any]) -> str:
        return format_source_detail_summary(source, detail)

    def _render_source_detail_status(self, source: str, status: Dict[str, Any]) -> None:
        source_to_key = {
            "daily": "daily_data",
            "market": "market_index",
            "industry": "industry_index",
            "broker_branch": "broker_branch",
            "technical": "technical_indicators",
            "monthly_revenue": "monthly_revenue",
            "institutional_flow": "institutional_flow",
            "credit_transaction": "credit_transaction",
            "tdcc_shareholding": "tdcc_shareholding",
        }
        key = source_to_key.get(source)
        label = getattr(self, f"{source}_detail_status_label", None)
        if not key or label is None:
            return
        detail = status.get(key)
        if not isinstance(detail, dict):
            label.setText("尚未檢查此資料源狀態")
            return
        label.setText(self._format_source_detail_summary(source, detail))

    @staticmethod
    def _format_candidate_status_card(value: Dict[str, Any]) -> str:
        record_count = _safe_nonnegative_int(value.get("total_records"))
        earliest = value.get("earliest_date") or "無"
        latest = value.get("latest_date") or "無"
        coverage = value.get("coverage_pct") or "0.0%"
        status = format_status_token(value.get("status") or "MISSING")
        disclaimer = value.get("disclaimer") or "候選研究資料，不參與評分"
        if record_count > 0:
            return (
                f"最新日期：{latest}\n"
                f"總記錄數：{record_count:,}\n"
                f"狀態：{status}\n"
                f"區間：{earliest} ~ {latest}\n"
                f"覆蓋率：{coverage}\n"
                f"[{disclaimer}]"
            )
        return (
            f"最新日期：{latest}\n"
            f"總記錄數：{record_count:,}\n"
            f"狀態：{status} / 尚未匯入\n"
            f"[{disclaimer}]"
        )

    @staticmethod
    def _format_status_card_text(key: str, value: Dict[str, Any]) -> str:
        latest_date = value.get("latest_date") or "未知"
        try:
            total_records = max(0, int(value.get("total_records") or 0))
        except (TypeError, ValueError):
            total_records = 0
        status = value.get("status", "unknown")
        if key in {"institutional_flow", "credit_transaction", "tdcc_shareholding"}:
            return UpdateView._format_candidate_status_card(value)
        if key == "monthly_revenue":
            latest_period = value.get("latest_period") or latest_date
            latest_available_period = value.get("latest_available_period") or "尚無"
            latest_available_date = value.get("latest_available_date") or "尚無"
            next_available_date = value.get("next_available_date")
            try:
                pending_period_count = max(0, int(value.get("pending_period_count") or 0))
            except (TypeError, ValueError):
                pending_period_count = 0
            lines = [
                f"最新可用日：{latest_available_date}",
                f"已匯入期別：{latest_period}",
                f"目前可用期別：{latest_available_period}",
            ]
            if pending_period_count and next_available_date:
                lines.append(
                    f"待生效：{pending_period_count} 個期別（{next_available_date} 起可用）"
                )
            lines.extend([
                f"總記錄數：{total_records:,}",
                f"狀態：{format_status_token(status)}",
            ])
            UpdateView._append_status_diagnostics(lines, value)
            freshness_gap = format_freshness_gap(value)
            if freshness_gap:
                lines.append(freshness_gap)
            return "\n".join(lines)
        if key == "broker_branch":
            lines = [
                f"最新日期：{latest_date}\n"
                f"實際天數：{_safe_nonnegative_int(value.get('date_count')):,} 天\n"
                f"雙榜紀錄 (E&B)：{_safe_nonnegative_int(value.get('dual_count')):,}\n"
                f"張數榜專屬 (E-only)：{_safe_nonnegative_int(value.get('e_only_count')):,}\n"
                f"金額榜專屬 (B-only)：{_safe_nonnegative_int(value.get('b_only_count')):,}\n"
                f"總記錄數：{total_records:,}\n"
                f"狀態：{format_status_token(status)}"
            ]
            UpdateView._append_status_diagnostics(lines, value)
            freshness_gap = format_freshness_gap(value)
            if freshness_gap:
                lines.append(freshness_gap)
            return "\n".join(lines)
        lines = [
            f"最新日期：{latest_date}",
            f"總記錄數：{total_records:,}",
            f"狀態：{format_status_token(status)}",
        ]
        if key == "technical_indicators" and value.get("file_count") is not None:
            lines.append(f"指標檔數：{_safe_nonnegative_int(value.get('file_count')):,}")
        UpdateView._append_status_diagnostics(lines, value)
        freshness_gap = format_freshness_gap(value)
        if freshness_gap:
            lines.append(freshness_gap)
        return "\n".join(lines)

    @staticmethod
    def _append_status_diagnostics(lines: list[str], value: Dict[str, Any]) -> None:
        read_mode = str(value.get("read_mode") or "").strip()
        if read_mode:
            lines.append(f"讀取模式：{read_mode}")
        warnings = value.get("warnings") or value.get("quality_warnings") or []
        for warning in list(warnings)[:2]:
            if str(warning).strip():
                lines.append(f"提醒：{warning}")

    def _set_status_card(self, key: str, value: Dict[str, Any]) -> None:
        card_map = {
            "daily_data": "daily_status_text",
            "market_index": "market_status_text",
            "industry_index": "industry_status_text",
            "broker_branch": "broker_branch_status_text",
            "technical_indicators": "technical_status_text",
            "monthly_revenue": "monthly_revenue_status_text",
            "institutional_flow": "institutional_status_text",
            "credit_transaction": "credit_status_text",
            "tdcc_shareholding": "tdcc_status_text",
        }
        card = getattr(self, card_map.get(key, ""), None)
        if card is not None:
            card.setPlainText(self._format_status_card_text(key, value))

    def _on_status_checked(self, status: Dict[str, Any]):
        """數據狀態檢查完成"""
        self.check_status_btn.setEnabled(True)
        self.check_status_btn.setText("檢查數據狀態")

        card_map = {
            "daily_data": "daily_status_text",
            "market_index": "market_status_text",
            "industry_index": "industry_status_text",
            "broker_branch": "broker_branch_status_text",
            "technical_indicators": "technical_status_text",
            "monthly_revenue": "monthly_revenue_status_text",
            "institutional_flow": "institutional_status_text",
            "credit_transaction": "credit_status_text",
            "tdcc_shareholding": "tdcc_status_text",
        }
        for key, attr in card_map.items():
            value = status.get(key)
            if isinstance(value, dict):
                self._set_status_card(key, value)
            else:
                # 部分 payload 不得沿用上一輪數字，否則會把舊資料誤當成目前狀態。
                card = getattr(self, attr, None)
                if card is not None:
                    card.setPlainText("尚未檢查")
        # 全域檢查也要刷新核心資料源頁面的 inline 摘要，避免卡片已是
        # 新值、頁面內仍殘留上一輪數字的 split-brain 顯示。
        for source in (
            "daily",
            "market",
            "industry",
            "broker_branch",
            "technical",
            "monthly_revenue",
            "institutional_flow",
            "credit_transaction",
            "tdcc_shareholding",
        ):
            self._render_source_detail_status(source, status)
        self._render_data_update_timeline(status.get("data_update_timeline"))
        self._render_p0_source_control_status(status.get("p0_source_control"))
        self._log(f"數據狀態檢查完成")

    def _on_status_error(self, error_msg: str):
        """數據狀態檢查出錯"""
        self.check_status_btn.setEnabled(True)
        self.check_status_btn.setText("檢查數據狀態")
        for attr in (
            "daily_status_text",
            "market_status_text",
            "industry_status_text",
            "broker_branch_status_text",
            "technical_status_text",
            "monthly_revenue_status_text",
            "institutional_status_text",
            "credit_status_text",
            "tdcc_status_text",
        ):
            card = getattr(self, attr, None)
            if card is not None:
                card.setPlainText(f"狀態：error: {error_msg}")
        error_detail = {
            "latest_date": None,
            "total_records": 0,
            "status": f"error: {error_msg}",
            # 讓各來源頁除了顯示異常外，也保留同一個可操作的失敗原因；
            # 否則全域卡片有訊息、頁面內摘要卻只剩空值，仍不足以排錯。
            "warnings": [error_msg],
        }
        source_to_key = {
            "daily": "daily_data",
            "market": "market_index",
            "industry": "industry_index",
            "broker_branch": "broker_branch",
            "technical": "technical_indicators",
            "monthly_revenue": "monthly_revenue",
            "institutional_flow": "institutional_flow",
            "credit_transaction": "credit_transaction",
            "tdcc_shareholding": "tdcc_shareholding",
        }
        for source, source_key in source_to_key.items():
            # 全域檢查失敗時，所有來源頁都必須同步清掉上一輪摘要；
            # 否則卡片顯示 error、頁面內文卻仍顯示舊的成功數字。
            self._render_source_detail_status(
                source,
                {source_key: dict(error_detail)},
            )
        self._render_p0_source_control_status(
            {
                "status": "audit_unavailable",
                "source_count": 0,
                "rows": [],
                "load_error": error_msg,
                "reference": "本輪狀態檢查失敗",
            }
        )
        self._render_data_update_timeline(
            {
                "status": "invalid",
                "last_success_at": None,
                "last_attempt_at": None,
                "steps": [],
                "diagnostics": [f"status_check_error:{error_msg}"],
            }
        )
        QMessageBox.critical(self, "錯誤", f"檢查數據狀態失敗：\n{error_msg}")
        self._log(f"錯誤：{error_msg}")

    def _get_selected_date_range(self) -> tuple[str, str]:
        """取得目前 UI 選定的查找日期範圍"""
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        lookback_days = self.lookback_days.value()
        return self._get_recent_business_day_range(end_date, lookback_days)

    @staticmethod
    def _get_recent_business_day_range(end_date: str, business_days: int) -> tuple[str, str]:
        """以週一至週五計算最近 N 個工作日，結束日仍保留使用者選定日期。"""
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        remaining_days = max(1, int(business_days))
        cursor = end_date_obj
        start_date_obj = end_date_obj
        while remaining_days > 0:
            if cursor.weekday() < 5:
                start_date_obj = cursor
                remaining_days -= 1
            cursor = cursor - timedelta(days=1)
        return start_date_obj.strftime("%Y-%m-%d"), end_date

    def _get_tpex_reference_date(self, end_date: str) -> str:
        """將結束日調整為最近交易日（至少避開週末）。"""
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        for _ in range(7):
            if end_dt.weekday() < 5:
                break
            end_dt = end_dt - timedelta(days=1)
        return end_dt.strftime("%Y-%m-%d")

    def _update_tpex_daily_prices(
        self,
        start_date: str,
        end_date: str,
        twse_no_data_dates: Optional[list[str]] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """更新 TPEX 日價；舊 service 測試替身可退回單日 API。"""
        update_range = getattr(self.update_service, "update_tpex_daily_price_range", None)
        if update_range is not None:
            kwargs = {
                "delay_seconds": 1.0,
                "sync_to_sqlite": False,
                "force_refresh": False,
                "break_on_repeated_source_date": False,
                "twse_no_data_dates": twse_no_data_dates,
            }
            if progress_callback is not None:
                try:
                    parameters = inspect.signature(update_range).parameters.values()
                except (TypeError, ValueError):
                    parameters = ()
                if any(
                    parameter.name == "progress_callback"
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                ):
                    kwargs["progress_callback"] = progress_callback
            if cancel_callback is not None:
                try:
                    parameters = inspect.signature(update_range).parameters.values()
                except (TypeError, ValueError):
                    parameters = ()
                if any(
                    parameter.name in {"cancel_callback", "cancellation_callback"}
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                ):
                    kwargs["cancel_callback"] = cancel_callback
            return update_range(start_date, end_date, **kwargs)
        return self.update_service.update_tpex_daily_price(end_date)

    def _write_tpex_background_status(self, payload: Dict[str, Any]) -> bool:
        """寫入背景任務狀態 JSON，供狀態按鈕即時讀取。"""
        try:
            self.tpex_refresh_state_file.parent.mkdir(parents=True, exist_ok=True)
            payload.update({"updated_at": datetime.now().isoformat(timespec="seconds")})
            self.tpex_refresh_state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            status = str(payload.get("status", "unknown"))
            level = "success" if status == "done" else "error" if status == "failed" else "info"
            self._set_tpex_background_status_label(
                status,
                message=str(payload.get("message", "") or ""),
                updated_at=str(payload.get("updated_at", "") or ""),
                level=level,
            )
            return True
        except Exception as exc:
            error_msg = f"狀態檔寫入失敗：{exc}"
            self._set_tpex_background_status_label("failed", message=error_msg, level="error")
            self._log(f"TPEX 背景任務 {error_msg}；未能可靠保存進度。")
            return False

    def _execute_background_tpex_refresh(self):
        """以獨立進程背景執行 TPEX + TWSE + 技術指標完整流程。"""
        if self._reject_busy_write("TPEX 背景補齊"):
            return
        if self._tpex_background_process is not None and self._tpex_background_process.poll() is None:
            QMessageBox.information(
                self,
                "背景任務進行中",
                "TPEX 背景任務尚未結束，請先完成後再啟動下一次。",
            )
            return

        start_date, end_date = self._get_selected_date_range()
        script_path = self.update_service.scripts_dir / "run_tpex_full_refresh_and_technical.py"
        if not script_path.exists():
            QMessageBox.critical(self, "背景任務啟動失敗", f"找不到背景腳本：{script_path}")
            return

        self.tpex_background_btn.setEnabled(False)
        self.tpex_background_btn.setText("背景補齊中...")

        initial_status = {
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "tpex_full_refresh_and_technical",
            "start_date": start_date,
            "end_date": end_date,
            "steps": {},
        }
        if not self._write_tpex_background_status(initial_status):
            self.tpex_background_btn.setEnabled(True)
            self.tpex_background_btn.setText("背景補齊 TPEX + 技術指標")
            QMessageBox.critical(
                self,
                "背景任務啟動失敗",
                "無法建立 TPEX 背景任務狀態檔，為避免任務進度無法追蹤，本次未啟動背景程序。",
            )
            return

        env = os.environ.copy()
        env["DATA_ROOT"] = str(self.update_service.config.data_root)
        env["OUTPUT_ROOT"] = str(self.update_service.config.output_root)
        env["PROFILE"] = str(self.update_service.config.profile)

        cmd = [
            sys.executable,
            str(script_path),
            "--start-date",
            start_date,
            "--end-date",
            end_date,
            "--state-file",
            str(self.tpex_refresh_state_file),
            "--delay-seconds",
            "1.0",
            "--sync-sqlite",
        ]
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            self._log("開始啟動 TPEX 背景補齊流程（含 SQLite 同步與技術指標增量檢查）")
            self._tpex_background_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
            self._log(
                f"TPEX 背景任務已啟動，PID={self._tpex_background_process.pid}，可點『檢查背景任務狀態』查看進度。"
            )
        except Exception as exc:
            self.tpex_background_btn.setEnabled(True)
            self.tpex_background_btn.setText("背景補齊 TPEX + 技術指標")
            error_msg = f"背景任務啟動失敗：{exc}"
            self._write_tpex_background_status({"status": "failed", "message": error_msg})
            QMessageBox.critical(self, "背景任務啟動失敗", error_msg)

    def _show_tpex_background_status(self):
        """讀取並顯示背景任務 JSON 狀態。"""
        if not self.tpex_refresh_state_file.exists():
            self._set_tpex_background_status_label("not_started", level="warning")
            QMessageBox.information(self, "背景任務狀態", "目前尚未啟動 TPEX 背景補齊任務。")
            return

        try:
            raw = json.loads(self.tpex_refresh_state_file.read_text(encoding="utf-8"))
            lines = [
                f"狀態：{raw.get('status', 'unknown')}",
                f"啟動時間：{raw.get('started_at', '-')}",
                f"最後更新：{raw.get('updated_at', '-')}",
                f"區間：{raw.get('start_date', '-') or '-'} 至 {raw.get('end_date', '-') or '-'}",
                f"模式：{raw.get('mode', '-')}",
            ]

            steps = raw.get("steps", {}) or {}
            twse = steps.get("twse_daily", {})
            tpex = steps.get("tpex_daily", {})
            sqlite = steps.get("sqlite", {})
            tech = steps.get("technical", {})

            def _fmt_step(name: str, payload: Dict[str, Any]) -> str:
                return (
                    f"{name}: {payload.get('status', '-')}, "
                    f"rows={payload.get('rows', '-')}, message={payload.get('message', '-') or '-'}"
                )

            lines.append("---")
            lines.append(_fmt_step("TWSE 每日", twse))
            lines.append(_fmt_step("TPEX 每日", tpex))
            lines.append(_fmt_step("SQLite", sqlite))
            lines.append(_fmt_step("技術指標", tech))

            if raw.get("status") == "failed":
                lines.append(f"錯誤訊息：{raw.get('message', '-')}")

            status = str(raw.get("status", "unknown"))
            level = "success" if status == "done" else "error" if status == "failed" else "warning" if status == "unknown" else "info"
            self._set_tpex_background_status_label(
                status,
                message=str(raw.get("message", "") or ""),
                updated_at=str(raw.get("updated_at", "") or ""),
                level=level,
            )
            # 背景任務狀態與總覽時間軸共用同一組明確 artifact；查詢後立即
            # 重畫，避免使用者看到 TPEX 已完成、總覽卻仍停在舊摘要。
            self._render_data_update_timeline(self._get_data_update_timeline())

            self._log("\n".join(lines))
            QMessageBox.information(self, "背景任務狀態", "\n".join(lines))

            if raw.get("status") in {"done", "failed"}:
                self._invalidate_detail_cache()
                self.tpex_background_btn.setEnabled(True)
                self.tpex_background_btn.setText("背景補齊 TPEX + 技術指標")
        except Exception as exc:
            self._set_tpex_background_status_label(
                "failed",
                message=f"讀取狀態失敗：{exc}",
                level="error",
            )
            self._log(f"TPEX 背景任務狀態讀取失敗：{exc}")
            QMessageBox.critical(self, "背景任務狀態", f"讀取狀態失敗：{exc}")
    def _run_update_all(
        self,
        mode="quick",
        progress_callback=None,
        cancellation_callback=None,
    ) -> Dict[str, Any]:
        start_date, end_date = self._get_selected_date_range()
        return self._run_update_all_request(
            mode, start_date, end_date, progress_callback, cancellation_callback
        )

    def _run_update_all_request(
        self,
        mode: str,
        start_date: str,
        end_date: str,
        progress_callback=None,
        cancellation_callback=None,
    ) -> Dict[str, Any]:
        return run_update_all(
            **{
                "mode": mode,
                "start_date": start_date,
                "end_date": end_date,
                "update_service": self.update_service,
                "get_overview_status": self._get_overview_status,
                "update_tpex_daily_prices": self._update_tpex_daily_prices,
                "run_incremental_technical": self._run_incremental_technical_if_needed,
                "tpex_warning_messages": self._tpex_warning_messages,
                "progress_callback": progress_callback,
                "cancellation_callback": cancellation_callback,
            }
        )

    def _run_incremental_technical_if_needed(
        self,
        progress_callback=None,
        cancellation_callback=None,
    ) -> Dict[str, Any]:
        """Skip technical indicator calculation when the overview already shows it is current."""
        if cancellation_callback is not None and cancellation_callback():
            return {
                "success": False,
                "cancelled": True,
                "message": "已取消：技術指標計算尚未開始",
            }
        status = self._get_overview_status()
        daily_latest = self._parse_status_date(status.get("daily_data", {}).get("latest_date"))
        technical_latest = self._parse_status_date(status.get("technical_indicators", {}).get("latest_date"))
        coverage_check = getattr(self.update_service, "check_technical_indicator_latest_coverage", None)
        coverage = coverage_check() if callable(coverage_check) else None

        if isinstance(coverage, dict) and coverage.get("success") and not coverage.get("is_current", True):
            message = (
                "技術指標最新日覆蓋不足，執行增量計算："
                f"{coverage.get('covered_stock_count', 0)}/{coverage.get('eligible_stock_count', 0)}"
            )
            if progress_callback:
                progress_callback(message, 88)
            self._log(message)
        elif daily_latest is not None and technical_latest is not None and technical_latest >= daily_latest:
            message = (
                f"技術指標已是最新（{technical_latest.strftime('%Y-%m-%d')}），"
                "跳過增量計算"
            )
            if progress_callback:
                progress_callback(message, 88)
            self._log(message)
            return {
                "success": True,
                "message": message,
                "skipped": True,
                "skip_reason": "technical_indicators_current",
                "daily_latest": daily_latest.strftime("%Y-%m-%d"),
                "technical_latest": technical_latest.strftime("%Y-%m-%d"),
                "total_stocks": 0,
                "success_count": 0,
                "fail_count": 0,
                "updated_stocks": [],
                "failed_stocks": [],
            }

        indicator_kwargs: dict[str, Any] = {
            "target_stock": None,
            "force_all": False,
            "start_date": None,
            "progress_callback": progress_callback,
            "incremental_lookback_days": 120,
        }
        if cancellation_callback is not None:
            try:
                parameters = inspect.signature(
                    self.update_service.calculate_technical_indicators
                ).parameters.values()
            except (TypeError, ValueError):
                parameters = ()
            if any(
                parameter.name in {"cancel_callback", "cancellation_callback"}
                or parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            ):
                indicator_kwargs["cancel_callback"] = cancellation_callback
        return self.update_service.calculate_technical_indicators(**indicator_kwargs)

    @staticmethod
    def _parse_status_date(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        value_str = str(value).strip()
        if not value_str or value_str.lower() in {"nan", "nat", "none"}:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(value_str[:10] if fmt == "%Y-%m-%d" else value_str[:8], fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _tpex_warning_messages(result: Dict[str, Any]) -> list[str]:
        return tpex_warning_messages(result)

    def _run_safe_update_all(
        self,
        progress_callback=None,
        cancellation_callback=None,
    ) -> Dict[str, Any]:
        """執行保守的一鍵安全更新流程，供 UI worker 與測試共用，保持向後相容"""
        use_sqlite = getattr(self.update_service.config, "use_sqlite", False)
        mode = "quick" if use_sqlite else "safe"
        return self._run_update_all(
            mode=mode,
            progress_callback=progress_callback,
            cancellation_callback=cancellation_callback,
        )

    def _execute_quick_update_all(self):
        """以背景工作執行快速更新所有數據"""
        self._execute_update_all(mode="quick")

    def _execute_safe_update_all(self):
        """以背景工作執行安全更新所有數據"""
        self._execute_update_all(mode="safe")

    def _execute_update_all(self, mode="quick"):
        """以背景工作執行更新所有數據"""
        if self._reject_busy_write("全部資料更新"):
            return
        self._current_update_mode = mode

        self.quick_update_all_btn.setEnabled(False)
        self.safe_update_all_btn.setEnabled(False)

        mode_name = "快速更新" if mode == "quick" else "安全更新"
        btn_text = "快速更新中..." if mode == "quick" else "安全更新中..."

        if mode == "quick":
            self.quick_update_all_btn.setText(btn_text)
        else:
            self.safe_update_all_btn.setText(btn_text)

        self._reset_progress()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"準備{mode_name}所有數據...")
        self.log_text.clear()
        self._log(f"開始{mode_name}所有數據")

        worker = self._start_worker(
            ProgressTaskWorker(self._run_update_all, mode=mode),
            operation_kind="write",
        )
        worker.progress.connect(self._on_update_all_progress)
        worker.finished.connect(self._on_update_all_finished)
        worker.error.connect(self._on_update_all_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_update_all_progress(self, message: str, progress: int):
        """更新更新流程進度"""
        mode_name = "快速更新" if getattr(self, "_current_update_mode", "quick") == "quick" else "安全更新"
        displayed = self._set_progress(message, progress)
        if "SQLite" in message:
            self._set_sqlite_sync_status(
                {"status": "running", "source": message, "message": "正在同步"}
            )
        self._log(f"[{mode_name} {displayed}%] {message}")

    def _on_update_all_finished(self, result: Dict[str, Any]):
        """更新流程完成"""
        self._invalidate_detail_cache()
        sqlite_summary = self._set_sqlite_sync_status_from_update_all(result)
        self.quick_update_all_btn.setEnabled(True)
        self.safe_update_all_btn.setEnabled(True)
        self.quick_update_all_btn.setText("快速更新 (跳過大型合併)")
        self.safe_update_all_btn.setText("安全更新 (完整 CSV + SQLite)")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        mode_name = "快速更新" if getattr(self, "_current_update_mode", "quick") == "quick" else "安全更新"

        if result.get("success", False):
            message = result.get("message", f"{mode_name}完成")
            warnings = result.get("warnings") or []
            if warnings:
                warning_text = "\n".join(str(warning) for warning in warnings)
                self._log(f"{message}；警告：{warning_text}")
                QMessageBox.warning(
                    self,
                    f"{mode_name}完成但有警告",
                    f"{message}\n\n{sqlite_summary}\n\n警告：\n{warning_text}",
                )
            else:
                self._log(message)
                QMessageBox.information(
                    self,
                    f"{mode_name}完成",
                    f"{message}\n\n{sqlite_summary}",
                )
            self._check_data_status()
            return

        failed_step = result.get("failed_step", "未知步驟")
        message = result.get("message", f"{mode_name}失敗")
        warnings = result.get("warnings") or []
        display_message = message
        if warnings:
            display_message = f"{message}\n\n警告：\n" + "\n".join(str(warning) for warning in warnings)
        display_message = f"{display_message}\n\n{sqlite_summary}"
        self._log(f"{mode_name}失敗：{failed_step} - {message}")
        QMessageBox.warning(self, f"{mode_name}未完成", f"{failed_step} 失敗：\n{display_message}")

    def _on_update_all_error(self, error_msg: str):
        """更新流程出錯"""
        self._invalidate_detail_cache()
        self.quick_update_all_btn.setEnabled(True)
        self.safe_update_all_btn.setEnabled(True)
        self.quick_update_all_btn.setText("快速更新 (跳過大型合併)")
        self.safe_update_all_btn.setText("安全更新 (完整 CSV + SQLite)")
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        mode_name = "快速更新" if getattr(self, "_current_update_mode", "quick") == "quick" else "安全更新"
        self._log(f"{mode_name}錯誤：{error_msg}")

        error_display = error_msg
        if len(error_display) > 500:
            error_display = error_display[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整訊息）"
        QMessageBox.critical(self, f"{mode_name}失敗", error_display)

    def _execute_update(self):
        """執行數據更新"""
        if self._reject_busy_write("單一資料來源更新"):
            return
        # 獲取更新類型
        update_type = None
        if self.daily_radio.isChecked():
            update_type = 'daily'
        elif self.market_radio.isChecked():
            update_type = 'market'
        elif self.industry_radio.isChecked():
            update_type = 'industry'
        elif self.broker_branch_radio.isChecked():
            update_type = 'broker_branch'

        self._active_update_type = update_type

        # 獲取查找範圍
        end_date = self.end_date.date().toString("yyyy-MM-dd")
        lookback_days = self.lookback_days.value()

        # 計算開始日期（從結束日期往前推）
        from datetime import datetime, timedelta
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        start_date_obj = end_date_obj - timedelta(days=lookback_days)
        start_date = start_date_obj.strftime("%Y-%m-%d")

        # 禁用按鈕
        current_update_btn = getattr(self, f"{update_type}_update_btn", None)
        if current_update_btn:
            current_update_btn.setEnabled(False)
            current_update_btn.setText("更新中...")

        # 顯示進度條
        self._reset_progress()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"正在更新{self._get_update_type_name(update_type)}...")

        # 清空日誌
        self.log_text.clear()
        self._log(f"開始更新 {self._get_update_type_name(update_type)}")
        self._log(f"查找範圍：{start_date} 至 {end_date}（最近 {lookback_days} 天）")
        self._log(f"說明：系統會在該範圍內查找缺失的日期並下載，合併時會合併所有數據")

        # 創建 Worker 任務
        def update_task(progress_callback=None, cancel_callback=None):
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行更新任務: update_type={update_type}")
                request = SourceUpdateRequest(str(update_type), start_date, end_date)
                result = request.execute(
                    self.update_service,
                    update_tpex_daily_prices=self._update_tpex_daily_prices,
                    tpex_warning_messages=self._tpex_warning_messages,
                    progress_callback=progress_callback,
                    cancellation_callback=cancel_callback,
                )
                logger.info(f"[UpdateView] 更新任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"更新任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                # ✅ 不要 raise，讓 Worker 的異常處理機制處理
                raise

        worker = self._start_worker(
            ProgressTaskWorker(update_task),
            operation_kind="write",
        )
        worker.progress.connect(self._on_update_progress)
        worker.finished.connect(self._on_update_finished)
        worker.error.connect(self._on_update_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_update_progress(self, message: str, percentage: int):
        """更新進度回調"""
        displayed = self._set_progress(message, percentage)
        if "SQLite" in message:
            self._set_sqlite_sync_status(
                {"status": "running", "source": message, "message": "正在同步"}
            )
        # 只在有實際進度變更時才記錄，避免日誌過多
        if displayed % 10 == 0 or displayed == 100:
            self._log(f"[進度 {displayed}%] {message}")

    def _on_update_finished(self, result: Dict[str, Any]):
        """更新完成"""
        self._invalidate_detail_cache()
        sqlite_summary = self._set_sqlite_sync_status(result.get("sqlite_sync"))
        # 恢復按鈕
        active_type = getattr(self, "_active_update_type", "daily")
        current_update_btn = getattr(self, f"{active_type}_update_btn", None)
        if current_update_btn:
            current_update_btn.setEnabled(True)
            current_update_btn.setText("手動下載此資料源")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # 顯示結果
        if result.get('success', False):
            message = result.get('message', '更新完成')
            updated_dates = result.get('updated_dates', [])
            failed_dates = result.get('failed_dates', [])
            warnings = result.get('warnings', [])

            self._log(f"更新完成：{message}")
            if updated_dates:
                self._log(f"成功更新日期：{len(updated_dates)} 個")
            if failed_dates:
                self._log(f"失敗日期：{len(failed_dates)} 個")
            for warning in warnings:
                self._log(f"警告：{warning}")

            display_message = message
            if warnings:
                display_message = f"{message}\n\n警告：\n" + "\n".join(warnings)
            display_message = f"{display_message}\n\n{sqlite_summary}"

            QMessageBox.information(self, "更新完成", display_message)

            # 自動刷新數據狀態
            self._check_data_status()
        else:
            message = result.get('message', '更新失敗')
            warnings = result.get('warnings', [])
            if warnings:
                message = f"{message}\n\n警告：\n" + "\n".join(str(warning) for warning in warnings)
            message = f"{message}\n\n{sqlite_summary}"
            self._log(f"更新失敗：{message}")
            QMessageBox.warning(self, "更新未完整", message)

    def _on_update_error(self, error_msg: str):
        """更新出錯"""
        self._invalidate_detail_cache()
        # 恢復按鈕
        active_type = getattr(self, "_active_update_type", "daily")
        current_update_btn = getattr(self, f"{active_type}_update_btn", None)
        if current_update_btn:
            current_update_btn.setEnabled(True)
            current_update_btn.setText("手動下載此資料源")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")
        QMessageBox.critical(self, "更新失敗", f"數據更新失敗：\n{error_msg}")

    def _get_update_type_name(self, update_type: str) -> str:
        """獲取更新類型名稱"""
        return get_update_type_name(update_type)

    def _execute_merge(self):
        """執行數據合併（增量合併）"""
        if self._reject_busy_write("合併每日資料"):
            return
        # 確認對話框
        reply = QMessageBox.question(
            self,
            "確認合併",
            "確定要合併每日股票數據嗎？\n這將把 daily_price/ 目錄中的新 CSV 文件合併到 stock_data_whole.csv\n（只合併新數據，不會重新合併已有數據）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        self._do_merge(force_all=False)

    def _execute_force_merge(self):
        """執行強制重新合併所有數據"""
        if self._reject_busy_write("強制合併每日資料"):
            return
        data_root = getattr(getattr(self, "config", None), "data_root", None) or "{DATA_ROOT}"
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle("確認強制合併")
        msg_box.setText("強制重新合併所有每日股價會重建 SQLite 匯入與索引。")
        msg_box.setInformativeText(
            "此操作會重新讀取 CSV 並重建每日股價相關 SQLite 資料，可能需要較長時間。"
            f"\n\n強制合併是針對 SQLite 資料庫重新進行 CSV 匯入與索引建立，"
            f"不應亦不會修改或刪除 {data_root} 底下的 raw CSV 原始檔案，以保障資料安全性。"
            "\n\n建議在執行前確認近期備份狀態；若只是測試取消流程，請按「取消」。"
        )
        cancel_button = msg_box.addButton("取消", QMessageBox.RejectRole)
        confirm_button = msg_box.addButton("確認強制合併", QMessageBox.DestructiveRole)
        msg_box.setDefaultButton(cancel_button)
        msg_box.exec()
        if msg_box.clickedButton() is not confirm_button:
            return

        self._do_merge(force_all=True)

    def _do_merge(self, force_all: bool = False):
        """執行合併操作（內部方法）"""
        if self._reject_busy_write("強制合併每日資料" if force_all else "合併每日資料"):
            return
        # 禁用按鈕
        if force_all:
            self.force_merge_btn.setEnabled(False)
            self.force_merge_btn.setText("強制合併中...")
        else:
            self.merge_btn.setEnabled(False)
            self.merge_btn.setText("合併中...")

        # 顯示進度條
        self._reset_progress()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        if force_all:
            self.progress_label.setText("正在強制重新合併所有每日股票數據...")
        else:
            self.progress_label.setText("正在合併每日股票數據...")

        # 清空日誌
        self.log_text.clear()
        if force_all:
            self._log("開始強制重新合併所有每日股票數據")
        else:
            self._log("開始合併每日股票數據（增量模式）")

        # 創建 Worker 任務
        def merge_task(progress_callback=None, cancel_callback=None):
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行合併任務: force_all={force_all}")
                kwargs: dict[str, Any] = {"force_all": force_all}
                if cancel_callback is not None:
                    try:
                        parameters = inspect.signature(self.update_service.merge_daily_data).parameters.values()
                    except (TypeError, ValueError):
                        parameters = ()
                    if any(
                        parameter.name in {"cancel_callback", "cancellation_callback"}
                        or parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters
                    ):
                        kwargs["cancel_callback"] = cancel_callback
                if progress_callback is not None:
                    try:
                        parameters = inspect.signature(self.update_service.merge_daily_data).parameters.values()
                    except (TypeError, ValueError):
                        parameters = ()
                    if any(
                        parameter.name == "progress_callback"
                        or parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters
                    ):
                        kwargs["progress_callback"] = progress_callback
                result = self.update_service.merge_daily_data(**kwargs)
                logger.info(f"[UpdateView] 合併任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"合併任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                # ✅ 不要 raise，讓 Worker 的異常處理機制處理
                raise

        worker = self._start_worker(ProgressTaskWorker(merge_task), operation_kind="write")
        if hasattr(worker, "progress"):
            worker.progress.connect(self._on_merge_progress)
        worker.finished.connect(self._on_merge_finished)
        worker.error.connect(self._on_merge_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_merge_progress(self, message: str, progress: int):
        """每日資料合併進度更新。"""

        displayed = self._set_progress(message, progress)
        self._log(f"[每日合併 {displayed}%] {message}")

    def _on_merge_finished(self, result: Dict[str, Any]):
        """合併完成"""
        self._invalidate_detail_cache()
        # 恢復按鈕
        self.merge_btn.setEnabled(True)
        self.merge_btn.setText("合併每日數據")
        self.force_merge_btn.setEnabled(True)
        self.force_merge_btn.setText("強制重新合併")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # 顯示結果
        if result.get('success', False):
            message = result.get('message', '合併完成')
            total_records = result.get('total_records', 0)
            merged_files = result.get('merged_files', 0)
            no_op = bool(result.get("no_op"))

            self._log(f"{'無需合併' if no_op else '合併完成'}：{message}")
            if no_op:
                self._log("本次沒有新資料，未建立新的整合檔備份。")
            if total_records > 0:
                self._log(f"總記錄數：{total_records:,}")
            if merged_files > 0:
                self._log(f"合併文件數：{merged_files}")

            QMessageBox.information(
                self,
                "資料已是最新" if no_op else "合併完成",
                (
                    f"{message}\n總記錄數：{total_records:,}\n"
                    "本次沒有新資料，未建立新的整合檔備份。"
                    if no_op
                    else f"{message}\n總記錄數：{total_records:,}"
                ),
            )

            # 自動刷新數據狀態
            self._check_data_status()
        else:
            message = result.get('message', '合併失敗')
            self._log(f"合併失敗：{message}")
            QMessageBox.warning(self, "合併失敗", message)

    def _on_merge_error(self, error_msg: str):
        """合併出錯"""
        self._invalidate_detail_cache()
        import logging
        logger = logging.getLogger(__name__)

        # ✅ 記錄錯誤
        logger.error(f"[UpdateView] 合併數據時發生錯誤: {error_msg}")

        # 恢復按鈕
        self.merge_btn.setEnabled(True)
        self.merge_btn.setText("合併每日數據")
        self.force_merge_btn.setEnabled(True)
        self.force_merge_btn.setText("強制重新合併")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")

        # ✅ 顯示更友好的錯誤訊息
        error_display = error_msg
        if len(error_msg) > 500:
            error_display = error_msg[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整信息）"

        QMessageBox.critical(
            self,
            "合併失敗",
            f"數據合併失敗：\n\n{error_display}\n\n請查看日誌獲取詳細信息。"
        )

    def _execute_merge_broker_branch(self):
        """執行券商分點資料合併"""
        if self._reject_busy_write("合併券商分點資料"):
            return
        # 確認對話框
        reply = QMessageBox.question(
            self,
            "確認合併",
            "確定要合併券商分點資料嗎？\n這將把各分點的 daily/ 目錄中的新 CSV 文件合併到 meta/merged.csv\n（只合併新數據，不會重新合併已有數據）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # 禁用按鈕
        self.merge_broker_branch_btn.setEnabled(False)
        self.merge_broker_branch_btn.setText("合併中...")

        # 顯示進度條
        self._reset_progress()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("正在合併券商分點資料...")

        # 清空日誌
        self.log_text.clear()
        self._log("開始合併券商分點資料（增量模式）")

        # 創建 Worker 任務
        def merge_task(progress_callback=None, cancel_callback=None):
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行券商分點資料合併任務")
                kwargs: dict[str, Any] = {}
                if cancel_callback is not None:
                    try:
                        parameters = inspect.signature(self.update_service.merge_broker_branch_data).parameters.values()
                    except (TypeError, ValueError):
                        parameters = ()
                    if any(
                        parameter.name in {"cancel_callback", "cancellation_callback"}
                        or parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters
                    ):
                        kwargs["cancel_callback"] = cancel_callback
                if progress_callback is not None:
                    try:
                        parameters = inspect.signature(self.update_service.merge_broker_branch_data).parameters.values()
                    except (TypeError, ValueError):
                        parameters = ()
                    if any(
                        parameter.name == "progress_callback"
                        or parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters
                    ):
                        kwargs["progress_callback"] = progress_callback
                result = self.update_service.merge_broker_branch_data(**kwargs)
                logger.info(f"[UpdateView] 券商分點資料合併任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"券商分點資料合併任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                raise

        worker = self._start_worker(ProgressTaskWorker(merge_task), operation_kind="write")
        if hasattr(worker, "progress"):
            worker.progress.connect(self._on_merge_broker_branch_progress)
        worker.finished.connect(self._on_merge_broker_branch_finished)
        worker.error.connect(self._on_merge_broker_branch_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_merge_broker_branch_progress(self, message: str, progress: int):
        """券商分點合併進度更新。"""

        displayed = self._set_progress(message, progress)
        self._log(f"[券商分點合併 {displayed}%] {message}")

    def _on_merge_broker_branch_finished(self, result: Dict[str, Any]):
        """券商分點資料合併完成"""
        self._invalidate_detail_cache()
        # 恢復按鈕
        self.merge_broker_branch_btn.setEnabled(True)
        self.merge_broker_branch_btn.setText("合併券商分點資料")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

            # 顯示結果
        if result.get('success', False):
            message = result.get('message', '合併完成')
            merged_branches = result.get('merged_branches', [])
            new_records = result.get('new_records', 0)
            total_records = result.get('total_records', 0)
            date_range = result.get('date_range', {})

            self._log(f"合併完成：{message}")
            if merged_branches:
                self._log(f"成功合併的分點：{len(merged_branches)} 個")
            if new_records > 0:
                self._log(f"新增記錄數：{new_records:,}")
            if total_records > 0:
                self._log(f"總記錄數：{total_records:,}")

            # 構建詳細訊息
            detail_message = f"{message}\n\n成功合併分點：{len(merged_branches)} 個\n新增記錄：{new_records:,}\n總記錄：{total_records:,}"
            if date_range.get('start_date') and date_range.get('end_date'):
                detail_message += f"\n\n日期範圍：{date_range['start_date']} 至 {date_range['end_date']}"
                detail_message += f"\n最新日期：{date_range['end_date']}"

            QMessageBox.information(
                self,
                "券商分點資料合併完成",
                detail_message
            )

            # 自動刷新數據狀態
            self._check_data_status()
        else:
            message = result.get('message', '合併失敗')
            self._log(f"合併失敗：{message}")
            QMessageBox.warning(self, "合併失敗", message)

    def _on_merge_broker_branch_error(self, error_msg: str):
        """券商分點資料合併出錯"""
        self._invalidate_detail_cache()
        # 恢復按鈕
        self.merge_broker_branch_btn.setEnabled(True)
        self.merge_broker_branch_btn.setText("合併券商分點資料")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")

        # 顯示友好的錯誤訊息
        error_display = error_msg
        if len(error_msg) > 500:
            error_display = error_msg[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整信息）"

        QMessageBox.critical(
            self,
            "合併失敗",
            f"券商分點資料合併失敗：\n\n{error_display}\n\n請查看日誌獲取詳細信息。"
        )

    def _log(self, message: str):
        """添加日誌"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def _execute_calculate_technical_indicators(self):
        """執行技術指標計算"""
        if self._reject_busy_write("技術指標計算"):
            return
        # 獲取計算模式
        force_all = self.tech_force_all_radio.isChecked()

        # 獲取股票代號（如果指定）
        target_stock = self.tech_stock_input.text().strip()
        if not target_stock:
            target_stock = None

        # 確認對話框
        if force_all:
            reply = QMessageBox.question(
                self,
                "確認計算",
                "確定要強制全量更新技術指標嗎？\n\n"
                "這將重新計算所有股票的技術指標，可能需要較長時間。\n\n"
                "建議：只有在需要完全重建指標時才使用此功能。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
        else:
            reply = QMessageBox.question(
                self,
                "確認計算",
                f"確定要計算技術指標嗎？\n\n"
                f"模式：增量更新（只計算新數據）\n"
                f"{'股票：' + target_stock if target_stock else '股票：全部'}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

        if reply != QMessageBox.Yes:
            return

        # 禁用按鈕
        self.calculate_tech_btn.setEnabled(False)
        self.calculate_tech_btn.setText("計算中...")

        # 顯示進度條
        self._reset_progress()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText("準備開始計算技術指標...")

        # 清空日誌
        self.log_text.clear()
        mode_text = "強制全量更新" if force_all else "增量更新"
        stock_text = f"股票：{target_stock}" if target_stock else "股票：全部"
        self._log(f"開始計算技術指標（{mode_text}，{stock_text}）")

        # 創建 Worker 任務（使用 ProgressTaskWorker 支持進度回調）
        def calculate_task(progress_callback=None, cancel_callback=None):
            """技術指標計算任務（支持進度回調）"""
            import logging
            logger = logging.getLogger(__name__)
            try:
                logger.info(f"[UpdateView] 開始執行技術指標計算任務: target_stock={target_stock}, force_all={force_all}")
                indicator_kwargs: dict[str, Any] = {
                    "target_stock": target_stock,
                    "force_all": force_all,
                    "start_date": None,
                    "progress_callback": progress_callback,
                }
                if cancel_callback is not None:
                    try:
                        parameters = inspect.signature(
                            self.update_service.calculate_technical_indicators
                        ).parameters.values()
                    except (TypeError, ValueError):
                        parameters = ()
                    if any(
                        parameter.name in {"cancel_callback", "cancellation_callback"}
                        or parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters
                    ):
                        indicator_kwargs["cancel_callback"] = cancel_callback
                result = self.update_service.calculate_technical_indicators(
                    **indicator_kwargs
                )
                logger.info(f"[UpdateView] 技術指標計算任務完成: success={result.get('success', False)}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"技術指標計算任務執行時發生異常: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"[UpdateView] {error_msg}")
                raise

        worker = self._start_worker(
            ProgressTaskWorker(calculate_task),
            operation_kind="write",
        )
        worker.progress.connect(self._on_tech_progress)
        worker.finished.connect(self._on_tech_calculate_finished)
        worker.error.connect(self._on_tech_calculate_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_tech_progress(self, message: str, progress: int):
        """技術指標計算進度更新"""
        displayed = self._set_progress(message, progress)
        self._log(f"[進度 {displayed}%] {message}")

    def _on_tech_calculate_finished(self, result: Dict[str, Any]):
        """技術指標計算完成"""
        self._invalidate_detail_cache()
        # 恢復按鈕
        self.calculate_tech_btn.setEnabled(True)
        self.calculate_tech_btn.setText("計算技術指標")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # 顯示結果
        if result.get('success', False):
            message = result.get('message', '計算完成')
            total_stocks = result.get('total_stocks', 0)
            success_count = result.get('success_count', 0)
            fail_count = result.get('fail_count', 0)
            insufficient_count = result.get('insufficient_data_count', 0)
            updated_stocks = result.get('updated_stocks', [])
            failed_stocks = result.get('failed_stocks', [])

            self._log(f"計算完成：{message}")
            if updated_stocks:
                self._log(f"成功更新的股票：{len(updated_stocks)} 檔")
                if len(updated_stocks) <= 10:
                    self._log(f"股票列表：{', '.join(updated_stocks)}")
            if failed_stocks:
                self._log(f"失敗的股票：{len(failed_stocks)} 檔")
                if len(failed_stocks) <= 10:
                    self._log(f"股票列表：{', '.join(failed_stocks)}")

            # 顯示詳細結果對話框
            detail_message = (
                f"技術指標計算完成\n\n"
                f"總處理股票數：{total_stocks}\n"
                f"成功處理數：{success_count}\n"
                f"失敗數：{fail_count}\n"
                f"數據不足股票數：{insufficient_count}\n"
                f"處理數據日期範圍：{result.get('start_date', '未知')} 至 {result.get('end_date', '未知')}"
            )

            QMessageBox.information(self, "計算完成", detail_message)
        else:
            message = result.get('message', '計算失敗')
            self._log(f"計算失敗：{message}")
            QMessageBox.warning(self, "計算失敗", message)

    def _on_tech_calculate_error(self, error_msg: str):
        """技術指標計算出錯"""
        self._invalidate_detail_cache()
        # 恢復按鈕
        self.calculate_tech_btn.setEnabled(True)
        self.calculate_tech_btn.setText("計算技術指標")

        # 隱藏進度條
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)

        # 顯示錯誤
        self._log(f"錯誤：{error_msg}")

        # 顯示友好的錯誤訊息
        error_display = error_msg
        if len(error_msg) > 500:
            error_display = error_msg[:500] + "\n\n（錯誤訊息過長，已截斷，請查看日誌獲取完整信息）"

        QMessageBox.critical(
            self,
            "計算失敗",
            f"技術指標計算失敗：\n\n{error_display}\n\n請查看日誌獲取詳細信息。"
        )

    def _execute_export_csv(self, source: str):
        """執行 CSV 匯出邏輯（支援範圍選擇與非同步處理）"""
        if self._reject_busy_write("CSV 匯出"):
            return
        table_mapping = {
            "daily": "daily_prices",
            "market": "market_indices",
            "industry": "industry_indices",
            "broker_branch": "broker_flows",
            "technical": "technical_indicators",
        }

        table_name = table_mapping.get(source)
        if not table_name:
            QMessageBox.warning(self, "警告", f"未知的匯出來源：{source}")
            return

        # 1. 取得 UI 設定日期範圍並彈出選擇對話框
        start_date, end_date = self._get_selected_date_range()

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("匯出 CSV 範圍選擇")
        msg_box.setText("請選擇要匯出的資料日期範圍：")
        msg_box.setInformativeText(
            f"目前的 UI 設定範圍：{start_date} 至 {end_date}\n\n"
            f"點選「最近範圍」將只匯出此區間資料。\n"
            f"點選「全部歷史」將匯出該資料表內的所有歷史資料。"
        )

        btn_range = msg_box.addButton("最近範圍", QMessageBox.ButtonRole.YesRole)
        btn_all = msg_box.addButton("全部歷史", QMessageBox.ButtonRole.NoRole)
        btn_cancel = msg_box.addButton("取消", QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()

        if msg_box.clickedButton() == btn_cancel:
            return
        elif msg_box.clickedButton() == btn_range:
            s_date, e_date = start_date, end_date
        else:
            s_date, e_date = None, None

        # 2. 選擇檔案儲存路徑
        import os
        from pathlib import Path

        export_date = datetime.now().strftime("%Y%m%d")
        default_filename = f"{table_name}_export_{export_date}.csv"

        # 預設儲存於 config 的 data_root 或是 專案根目錄/exports
        default_dir = getattr(self.update_service.config, "data_root", Path.cwd())
        default_path = Path(default_dir) / default_filename

        from PySide6.QtWidgets import QFileDialog
        file_path_str, _ = QFileDialog.getSaveFileName(
            self,
            "選擇儲存的 CSV 檔案",
            str(default_path),
            "CSV 檔案 (*.csv)"
        )

        if not file_path_str:
            return

        target_path = Path(file_path_str)

        # 3. 啟動背景 Worker 執行匯出
        self._reset_progress()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label.setVisible(True)
        self.progress_label.setText(f"正在匯出 {table_name} 資料至 CSV...")
        self._log(f"開始匯出 {table_name} 資料至 {target_path}")

        def export_task(progress_callback=None, cancel_callback=None):
            kwargs: dict[str, Any] = {
                "table_name": table_name,
                "target_path": target_path,
                "start_date": s_date,
                "end_date": e_date,
            }
            if cancel_callback is not None:
                try:
                    parameters = inspect.signature(self.update_service.export_table_to_csv).parameters.values()
                except (TypeError, ValueError):
                    parameters = ()
                if any(
                    parameter.name in {"cancel_callback", "cancellation_callback"}
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                ):
                    kwargs["cancel_callback"] = cancel_callback
            if progress_callback is not None:
                try:
                    parameters = inspect.signature(self.update_service.export_table_to_csv).parameters.values()
                except (TypeError, ValueError):
                    parameters = ()
                if any(
                    parameter.name == "progress_callback"
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                ):
                    kwargs["progress_callback"] = progress_callback
            return self.update_service.export_table_to_csv(**kwargs)

        worker = self._start_worker(ProgressTaskWorker(export_task), operation_kind="write")
        if hasattr(worker, "progress"):
            worker.progress.connect(self._on_export_progress)

        def on_export_finished(result: Dict[str, Any]):
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)
            if result.get("success", False):
                msg = result.get("message", "匯出成功")
                self._log(f"匯出成功：{msg}")
                QMessageBox.information(self, "匯出完成", msg)
            else:
                msg = result.get("message", "匯出失敗")
                self._log(f"匯出失敗：{msg}")
                QMessageBox.warning(self, "匯出失敗", msg)

        def on_export_error(error_msg: str):
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)
            self._log(f"匯出出錯：{error_msg}")
            QMessageBox.critical(self, "匯出失敗", f"匯出過程發生錯誤：\n{error_msg}")

        worker.finished.connect(on_export_finished)
        worker.error.connect(on_export_error)
        self._attach_worker_cleanup(worker)
        worker.start()

    def _on_export_progress(self, message: str, progress: int):
        """CSV 匯出進度更新。"""

        displayed = self._set_progress(message, progress)
        self._log(f"[CSV 匯出 {displayed}%] {message}")

    def closeEvent(self, event):
        """關閉事件"""
        if not self.request_cooperative_shutdown():
            self._log("已送出合作式取消；背景工作結束後才可關閉資料更新頁。")
            event.ignore()
            return
        event.accept()
