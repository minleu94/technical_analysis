"""Research Run Registry 跨 run 比較子頁。"""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_module.research_run_comparison_service import (
    ComparabilityStatus,
    ResearchRunComparisonService,
)
from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_service import ResearchRunRepositoryError, ResearchRunServiceError
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.widgets.table_style import apply_financial_table_style


RUN_TYPE_LABELS = {
    "single_backtest": "單股回測",
    "recommendation_portfolio": "推薦回放",
}

COMPARABILITY_LABELS = {
    ComparabilityStatus.COMPARABLE: "可直接比較",
    ComparabilityStatus.CAUTION: "需謹慎比較",
    ComparabilityStatus.INCOMPATIBLE: "不可直接比較",
}

COMPARABILITY_TONES = {
    ComparabilityStatus.COMPARABLE: MIDNIGHT_ANALYST.success,
    ComparabilityStatus.CAUTION: MIDNIGHT_ANALYST.warning,
    ComparabilityStatus.INCOMPATIBLE: MIDNIGHT_ANALYST.danger,
}


class RunRegistryCompareWidget(QWidget):
    """顯示 Research Run Registry 的比較入口。"""

    def __init__(
        self,
        research_run_service: Any,
        *,
        comparison_service: ResearchRunComparisonService | None = None,
        page_size: int = 25,
        parent=None,
    ):
        super().__init__(parent)
        self.research_run_service = research_run_service
        self.comparison_service = comparison_service or ResearchRunComparisonService()
        self.page_size = page_size
        self.current_page = 1
        self._loaded_once = False
        self._request_id = 0
        self._all_runs: list[ResearchRunMetadataDTO] = []
        self._filtered_runs: list[ResearchRunMetadataDTO] = []
        self._run_aliases: dict[str, str] = {}
        self._run_display_names: dict[str, str] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("類型"))
        self.run_type_filter = QComboBox()
        self.run_type_filter.addItem("全部", "")
        self.run_type_filter.addItem(RUN_TYPE_LABELS["single_backtest"], "single_backtest")
        self.run_type_filter.addItem(
            RUN_TYPE_LABELS["recommendation_portfolio"],
            "recommendation_portfolio",
        )
        self.run_type_filter.currentTextChanged.connect(self.refresh_runs)
        filter_row.addWidget(self.run_type_filter)

        filter_row.addWidget(QLabel("策略"))
        self.strategy_filter = QLineEdit()
        self.strategy_filter.setPlaceholderText("strategy_id")
        self.strategy_filter.textChanged.connect(self.refresh_runs)
        filter_row.addWidget(self.strategy_filter)

        filter_row.addWidget(QLabel("標籤"))
        self.tag_filter = QLineEdit()
        self.tag_filter.setPlaceholderText("tag")
        self.tag_filter.textChanged.connect(self.refresh_runs)
        filter_row.addWidget(self.tag_filter)

        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.clicked.connect(self.refresh_runs)
        filter_row.addWidget(self.refresh_button)
        layout.addLayout(filter_row)

        list_group = QGroupBox("Research Runs 清單")
        list_layout = QVBoxLayout(list_group)
        self.run_list = QListWidget()
        self.run_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.run_list.setMinimumHeight(180)
        self.run_list.itemSelectionChanged.connect(self._update_compare_button_state)
        list_layout.addWidget(self.run_list)

        page_row = QHBoxLayout()
        self.prev_page_btn = QPushButton("上一頁")
        self.prev_page_btn.clicked.connect(self.previous_page)
        page_row.addWidget(self.prev_page_btn)
        self.page_label = QLabel("第 0 / 0 頁")
        page_row.addWidget(self.page_label)
        self.next_page_btn = QPushButton("下一頁")
        self.next_page_btn.clicked.connect(self.next_page)
        page_row.addWidget(self.next_page_btn)
        page_row.addStretch()
        self.compare_button = QPushButton("比較選中")
        self.compare_button.clicked.connect(self.compare_selected_runs)
        self.compare_button.setEnabled(False)
        page_row.addWidget(self.compare_button)
        list_layout.addLayout(page_row)
        layout.addWidget(list_group, stretch=1)

        self.comparability_badge = QLabel("尚未比較")
        self.comparability_badge.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.comparability_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.comparability_badge.setWordWrap(True)
        self._style_comparability_badge(MIDNIGHT_ANALYST.text_muted)
        layout.addWidget(self.comparability_badge)
        self.selected_runs_label = QLabel("尚未選取比較 run。")
        self.selected_runs_label.setWordWrap(True)
        self.selected_runs_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.selected_runs_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_1}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 8px 10px;"
        )
        layout.addWidget(self.selected_runs_label)

        self.params_diff_table = self._new_table()
        self.metrics_table = self._new_table()
        self.regime_table = self._new_table()
        self.benchmark_table = self._new_table()
        for table in (
            self.params_diff_table,
            self.metrics_table,
            self.regime_table,
            self.benchmark_table,
        ):
            table.hide()

        summary_grid = QGridLayout()
        summary_grid.setSpacing(10)
        self.params_summary_label = self._new_summary_label("尚未比較。選擇 2 至 5 筆 run 後，這裡會只列出有差異的參數。")
        self.metrics_summary_label = self._new_summary_label("尚未比較。比較後會以 A / B / C 欄位對照主要績效指標。")
        self.metrics_summary_table = self._new_summary_table()
        self.metrics_summary_table.hide()
        self.regime_summary_label = self._new_summary_label("尚未比較。比較後會摘要各 run 的市場 Regime 分布。")
        self.benchmark_summary_label = self._new_summary_label("尚未比較。比較後會摘要 Benchmark / excess return 等基準資訊。")
        summary_grid.addWidget(
            self._wrap_summary("指標", self.metrics_summary_label, self.metrics_summary_table),
            0,
            0,
            1,
            2,
        )
        summary_grid.addWidget(self._wrap_summary("參數差異", self.params_summary_label), 1, 0)
        summary_grid.addWidget(self._wrap_summary("Benchmark 基準", self.benchmark_summary_label), 1, 1)
        summary_grid.addWidget(self._wrap_summary("市場 Regime", self.regime_summary_label), 2, 0, 1, 2)
        summary_grid.setColumnStretch(0, 1)
        summary_grid.setColumnStretch(1, 1)
        layout.addLayout(summary_grid, stretch=2)

        hidden_tables = QWidget()
        hidden_layout = QHBoxLayout(hidden_tables)
        hidden_layout.setContentsMargins(0, 0, 0, 0)
        hidden_layout.setSpacing(0)
        hidden_layout.addWidget(self.params_diff_table)
        hidden_layout.addWidget(self.metrics_table)
        hidden_layout.addWidget(self.regime_table)
        hidden_layout.addWidget(self.benchmark_table)
        hidden_tables.hide()
        layout.addWidget(hidden_tables)

        self.normalized_equity_table = self._new_table()
        normalized_group = QGroupBox("標準化權益")
        normalized_layout = QVBoxLayout(normalized_group)
        self.normalized_equity_empty_label = QLabel(
            "尚未觸發比較。\n"
            "操作方式：在上方清單選 2 至 5 筆 run，按「比較選中」。\n"
            "顯示條件：被比較的 run 都要有 equity curve，且日期要有交集；第一個共同日期會標準化為 10000。"
        )
        self.normalized_equity_empty_label.setWordWrap(True)
        self.normalized_equity_empty_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 10px; line-height: 145%;"
        )
        normalized_layout.addWidget(self.normalized_equity_empty_label)
        normalized_layout.addWidget(self.normalized_equity_table)
        self.normalized_equity_table.hide()
        layout.addWidget(normalized_group, stretch=1)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event is not None:
            super().showEvent(event)
        if self._loaded_once:
            return
        self._loaded_once = True
        self.refresh_runs()

    def refresh_runs(self) -> None:
        request_id = self.begin_run_list_request()
        runs = self.research_run_service.list_runs(include_archived=False)
        self.apply_run_list_response(request_id, runs)

    def begin_run_list_request(self) -> int:
        self._request_id += 1
        return self._request_id

    def apply_run_list_response(
        self, request_id: int, runs: list[ResearchRunMetadataDTO]
    ) -> None:
        if request_id != self._request_id:
            return
        self._all_runs = list(runs)
        self.current_page = 1
        self._apply_filters_and_render()

    def next_page(self) -> None:
        total_pages = self._total_pages()
        if self.current_page < total_pages:
            self.current_page += 1
            self._render_run_list()

    def previous_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self._render_run_list()

    def selected_run_ids(self) -> list[str]:
        return [
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self.run_list.selectedItems()
        ][:5]

    def compare_selected_runs(self) -> None:
        run_ids = self.selected_run_ids()
        if len(run_ids) < 2 or len(run_ids) > 5:
            QMessageBox.warning(self, "提示", "請選擇 2 至 5 個 research run")
            return

        try:
            run_data = [self.research_run_service.load_run_data(run_id) for run_id in run_ids]
        except (ResearchRunServiceError, ResearchRunRepositoryError, OSError, ValueError) as exc:
            self._render_comparability_badge(ComparabilityStatus.INCOMPATIBLE, [str(exc)])
            for table in (self.params_diff_table, self.metrics_table, self.regime_table,
                          self.benchmark_table, self.normalized_equity_table):
                self._set_table_model(table, pd.DataFrame())
            self._render_metrics_summary_table(pd.DataFrame())
            self.params_summary_label.setText("研究載入失敗")
            self.regime_summary_label.setText("比較已阻擋")
            self.benchmark_summary_label.setText("比較已阻擋")
            self.normalized_equity_empty_label.setText(f"研究載入失敗；未進行修復或重算：{exc}")
            self.normalized_equity_table.hide()
            return
        metadata = [item.metadata for item in run_data]
        self._prepare_run_aliases(metadata)
        self.selected_runs_label.setText(self._selected_runs_summary(metadata))
        comparability = self.comparison_service.evaluate_comparability(metadata)
        self._render_comparability_badge(comparability.status, comparability.reasons)

        if comparability.status == ComparabilityStatus.INCOMPATIBLE:
            for table in (self.metrics_table, self.regime_table, self.benchmark_table,
                          self.normalized_equity_table):
                self._set_table_model(table, pd.DataFrame())
            self._render_metrics_summary_table(pd.DataFrame())
            self._set_table_model(self.params_diff_table, self._build_params_diff(metadata))
            self.normalized_equity_empty_label.setText("研究契約不相容或未完整完成，已停止績效混排與權益標準化。")
            self.normalized_equity_table.hide()
            self.regime_summary_label.setText("比較已阻擋")
            self.benchmark_summary_label.setText("比較已阻擋")
            return

        params_diff = self._build_params_diff(metadata)
        metrics = self._flatten_run_dicts(metadata, "metrics")
        regime = self._flatten_run_dicts(metadata, "regime_breakdown")
        benchmark = self.comparison_service.collect_benchmark_attribution(metadata)
        benchmark_frame = self._flatten_mapping_by_run(benchmark)
        self._set_table_model(self.params_diff_table, params_diff)
        self._set_table_model(self.metrics_table, metrics)
        self._set_table_model(self.regime_table, regime)
        self._set_table_model(self.benchmark_table, benchmark_frame)
        self.params_summary_label.setText(self._params_summary_text(params_diff))
        self._render_metrics_summary_table(metrics)
        self.regime_summary_label.setText(self._run_mapping_summary_text(regime, "尚無 Regime 分布資料"))
        self.benchmark_summary_label.setText(
            self._run_mapping_summary_text(benchmark_frame, "尚無 Benchmark 基準資料")
        )

        normalized = self.comparison_service.build_normalized_equity(
            {item.metadata.run_id: item.equity for item in run_data}
        )
        normalized_frame = self._normalized_equity_frame(normalized.normalized)
        if normalized_frame.empty:
            self.normalized_equity_empty_label.setText(
                "無法產生標準化權益。\n"
                "原因：沒有共同日期可標準化比較，或某些 run 缺少 equity curve / portfolio_value。\n"
                "判讀：這不是比較功能失效，而是目前資料條件不足；請改選日期重疊的 run。"
            )
            self.normalized_equity_table.hide()
        else:
            self.normalized_equity_empty_label.setText(
                f"已產生標準化權益。\n"
                f"共同日期：{len(normalized.date_intersection)} 筆；第一個共同日期標準化為 10000。\n"
                "注意：這只讀取已儲存 run 結果，不重新計算績效。"
            )
            self.normalized_equity_table.show()
        self._set_table_model(
            self.normalized_equity_table,
            normalized_frame,
        )

    def _apply_filters_and_render(self) -> None:
        run_type = str(self.run_type_filter.currentData() or "")
        strategy = self.strategy_filter.text().strip().lower()
        tag = self.tag_filter.text().strip().lower()

        filtered: list[ResearchRunMetadataDTO] = []
        for run in self._all_runs:
            if run_type and run.run_type != run_type:
                continue
            if strategy and strategy not in run.strategy_id.lower():
                continue
            if tag and tag not in self._run_tags_text(run):
                continue
            filtered.append(run)

        self._filtered_runs = filtered
        self._render_run_list()

    def _render_run_list(self) -> None:
        self.run_list.clear()
        total_pages = self._total_pages()
        self.current_page = min(max(self.current_page, 1), total_pages)
        start = (self.current_page - 1) * self.page_size
        end = start + self.page_size

        for run in self._filtered_runs[start:end]:
            text = (
                f"{run.run_name}\n"
                f"類型：{self._run_type_label(run.run_type)}　策略：{run.strategy_id}　時間：{run.created_at[:16]}"
            )
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, 46))
            item.setData(Qt.ItemDataRole.UserRole, run.run_id)
            item.setToolTip(
                f"名稱：{run.run_name}\n"
                f"run_id：{run.run_id}\n"
                f"類型：{self._run_type_label(run.run_type)}\n"
                f"策略：{run.strategy_id}\n"
                f"建立時間：{run.created_at[:16]}"
            )
            self.run_list.addItem(item)

        self.page_label.setText(f"第 {self.current_page} / {total_pages} 頁")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < total_pages)
        self._update_compare_button_state()

    def _update_compare_button_state(self) -> None:
        selected_count = len(self.run_list.selectedItems())
        self.compare_button.setEnabled(2 <= selected_count <= 5)

    def _total_pages(self) -> int:
        if not self._filtered_runs:
            return 1
        return (len(self._filtered_runs) + self.page_size - 1) // self.page_size

    def _run_tags_text(self, run: ResearchRunMetadataDTO) -> str:
        tags = run.original_input.get("tags", [])
        if isinstance(tags, list):
            return " ".join(str(tag).lower() for tag in tags)
        return str(tags).lower()

    def _run_type_label(self, run_type: str) -> str:
        return RUN_TYPE_LABELS.get(run_type, run_type)

    def _render_comparability_badge(
        self, status: ComparabilityStatus, reasons: list[str]
    ) -> None:
        reason_text = "" if not reasons else " | 差異原因：" + "、".join(reasons)
        self.comparability_badge.setText(
            f"比較狀態：{COMPARABILITY_LABELS.get(status, status.value)}{reason_text}"
        )
        self._style_comparability_badge(COMPARABILITY_TONES[status])

    def _style_comparability_badge(self, color: str) -> None:
        self.comparability_badge.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_primary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-left: 5px solid {color}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; padding: 9px 12px;"
        )

    def _build_params_diff(self, runs: list[ResearchRunMetadataDTO]) -> pd.DataFrame:
        keys = sorted(
            {
                str(key)
                for run in runs
                for key in run.normalized_params.keys()
            }
        )
        rows = []
        for key in keys:
            row = {"parameter": key}
            values = []
            for run in runs:
                value = run.normalized_params.get(key, "")
                row[run.run_id] = value
                values.append(str(value))
            row["differs"] = len(set(values)) > 1
            rows.append(row)
        return pd.DataFrame(rows)

    def _flatten_run_dicts(
        self, runs: list[ResearchRunMetadataDTO], field_name: str
    ) -> pd.DataFrame:
        mapping = {
            run.run_id: getattr(run, field_name)
            for run in runs
        }
        return self._flatten_mapping_by_run(mapping)

    def _flatten_mapping_by_run(self, mapping: dict[str, dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for run_id, values in mapping.items():
            flattened = self._flatten_dict(values)
            if not flattened:
                rows.append({"run_id": run_id, "key": "", "value": ""})
                continue
            for key, value in flattened.items():
                rows.append({"run_id": run_id, "key": key, "value": value})
        return pd.DataFrame(rows)

    def _flatten_dict(self, value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, item in value.items():
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, dict):
                flattened.update(self._flatten_dict(item, full_key))
            else:
                flattened[full_key] = item
        return flattened

    def _normalized_equity_frame(self, normalized: dict[str, pd.DataFrame]) -> pd.DataFrame:
        rows = []
        for run_id, frame in normalized.items():
            for record in frame.to_dict(orient="records"):
                rows.append({"run_id": run_id, **record})
        return pd.DataFrame(rows)

    def _new_table(self) -> QTableView:
        table = QTableView()
        apply_financial_table_style(table)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QTableView.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _new_summary_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 12px; line-height: 145%;"
        )
        return label

    def _new_summary_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            f"""
            QTableWidget {{
                background: {MIDNIGHT_ANALYST.surface_1};
                alternate-background-color: {MIDNIGHT_ANALYST.surface_2};
                color: {MIDNIGHT_ANALYST.text_primary};
                gridline-color: {MIDNIGHT_ANALYST.border_subtle};
                border: 1px solid {MIDNIGHT_ANALYST.border};
                border-radius: {MIDNIGHT_ANALYST.radius_panel}px;
            }}
            QHeaderView::section {{
                background: {MIDNIGHT_ANALYST.surface_2};
                color: {MIDNIGHT_ANALYST.text_secondary};
                padding: 5px 7px;
                border: 0;
                border-right: 1px solid {MIDNIGHT_ANALYST.border};
                border-bottom: 1px solid {MIDNIGHT_ANALYST.border};
                font-weight: 700;
            }}
            QTableWidget::item {{
                padding: 5px 7px;
            }}
            """
        )
        return table

    def _wrap_summary(self, title: str, label: QLabel, extra_widget: QWidget | None = None) -> QFrame:
        frame = QFrame()
        frame.setObjectName("registryCompareSummaryCard")
        frame.setStyleSheet(
            f"#registryCompareSummaryCard {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 13px; font-weight: 800;"
        )
        layout.addWidget(title_label)
        layout.addWidget(label, 1)
        if extra_widget is not None:
            layout.addWidget(extra_widget, 2)
        return frame

    def _wrap_table(self, title: str, table: QTableView) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(table)
        return group

    def _set_table_model(self, table: QTableView, frame: pd.DataFrame) -> None:
        model = PandasTableModel(frame)
        table.setModel(model)
        table.resizeColumnsToContents()

    def _params_summary_text(self, frame: pd.DataFrame) -> str:
        if frame.empty:
            return "沒有參數可比較。"
        diff_frame = frame[frame["differs"] == True] if "differs" in frame.columns else frame
        if diff_frame.empty:
            return "參數一致：目前選取的 run 沒有觀測到參數差異。"
        lines: list[str] = []
        run_columns = [col for col in diff_frame.columns if col not in {"parameter", "differs"}]
        for _, row in diff_frame.head(8).iterrows():
            values = " / ".join(
                f"{self._alias_for_run(str(run_id))}={self._format_summary_value(row[run_id])}"
                for run_id in run_columns
            )
            lines.append(f"• {self._label_for_key(str(row['parameter']))}：{values}")
        remaining = len(diff_frame) - len(lines)
        if remaining > 0:
            lines.append(f"• 另有 {remaining} 個差異參數，完整內容保留於資料 model。")
        return "\n".join(lines)

    def _run_mapping_summary_text(self, frame: pd.DataFrame, empty_text: str) -> str:
        if frame.empty:
            return empty_text
        lines: list[str] = []
        for run_id, run_frame in frame.groupby("run_id", sort=False):
            pairs: list[str] = []
            for _, row in run_frame.head(5).iterrows():
                key = str(row.get("key", "")).strip()
                value = self._format_summary_value(row.get("value", ""))
                if not key and not value:
                    continue
                pairs.append(f"{self._label_for_key(key)}={value}" if key else value)
            summary = "；".join(pairs) if pairs else "沒有可顯示欄位"
            extra = max(len(run_frame) - 5, 0)
            suffix = f"；另 {extra} 項" if extra else ""
            lines.append(f"• {self._alias_for_run(str(run_id))}：{summary}{suffix}")
        return "\n".join(lines)

    def _render_metrics_summary_table(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            self.metrics_summary_table.hide()
            self.metrics_summary_label.show()
            self.metrics_summary_label.setText("尚無指標資料。")
            return

        pivot: dict[str, dict[str, str]] = {}
        aliases: list[str] = []
        for run_id, run_frame in frame.groupby("run_id", sort=False):
            alias = self._alias_for_run(str(run_id))
            aliases.append(alias)
            for _, row in run_frame.iterrows():
                key = str(row.get("key", "")).strip()
                if not key:
                    continue
                label = self._label_for_key(key)
                pivot.setdefault(label, {})[alias] = self._format_summary_value(row.get("value", ""))

        if not pivot:
            self.metrics_summary_table.hide()
            self.metrics_summary_label.show()
            self.metrics_summary_label.setText("尚無可顯示的指標欄位。")
            return

        row_labels = list(pivot.keys())[:8]
        self.metrics_summary_table.setColumnCount(len(aliases) + 1)
        self.metrics_summary_table.setRowCount(len(row_labels))
        self.metrics_summary_table.setHorizontalHeaderLabels(["指標", *aliases])
        for row_index, label in enumerate(row_labels):
            label_item = QTableWidgetItem(label)
            label_item.setToolTip(label)
            self.metrics_summary_table.setItem(row_index, 0, label_item)
            for column_index, alias in enumerate(aliases, start=1):
                value = pivot[label].get(alias, "空白")
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.metrics_summary_table.setItem(row_index, column_index, item)

        self.metrics_summary_table.resizeColumnsToContents()
        header = self.metrics_summary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column_index in range(1, self.metrics_summary_table.columnCount()):
            header.setSectionResizeMode(column_index, QHeaderView.Stretch)
        self.metrics_summary_table.setMinimumHeight(min(260, 42 + len(row_labels) * 31))
        self.metrics_summary_label.setText("主要指標對照：")
        self.metrics_summary_label.show()
        self.metrics_summary_table.show()

    def _short_run_id(self, run_id: str) -> str:
        if len(run_id) <= 18:
            return run_id
        return f"{run_id[:12]}…{run_id[-4:]}"

    def _prepare_run_aliases(self, runs: list[ResearchRunMetadataDTO]) -> None:
        labels = ["A", "B", "C", "D", "E"]
        self._run_aliases = {
            run.run_id: labels[index] for index, run in enumerate(runs[: len(labels)])
        }
        self._run_display_names = {
            run.run_id: f"{run.run_name}｜{self._run_type_label(run.run_type)}｜{run.strategy_id}"
            for run in runs
        }

    def _alias_for_run(self, run_id: str) -> str:
        return self._run_aliases.get(run_id, self._short_run_id(run_id))

    def _selected_runs_summary(self, runs: list[ResearchRunMetadataDTO]) -> str:
        if not runs:
            return "尚未選取比較 run。"
        lines = ["比較代號："]
        for run in runs:
            alias = self._alias_for_run(run.run_id)
            lines.append(
                f"{alias}：{run.run_name}｜{self._run_type_label(run.run_type)}｜{run.strategy_id}｜{run.created_at[:16]}"
            )
        return "\n".join(lines)

    def _label_for_key(self, key: str) -> str:
        labels = {
            "allocation_method": "配置方式",
            "annual_return": "年化報酬",
            "avg_holding_days": "平均持有天數",
            "buy_confirm_days": "買進確認天數",
            "buy_quantile_bp": "買進百分位門檻",
            "buy_score": "買進分數",
            "capital_used": "已用資金",
            "cooldown_days": "冷卻天數",
            "credibility_status": "可信度狀態",
            "credibility_warning_count": "可信度警告數",
            "end_date": "結束日期",
            "ending_cash": "期末現金",
            "expectancy": "期望值",
            "holding_days": "持有天數",
            "initial_capital": "初始資金",
            "max_drawdown": "最大回撤",
            "profit_factor": "獲利因子",
            "sharpe_ratio": "Sharpe 比率",
            "taiex.excess_return_bp": "相對大盤超額報酬 bp",
            "total_return": "總報酬",
            "total_trades": "交易次數",
            "trend.trades": "趨勢交易數",
            "win_rate": "勝率",
        }
        return labels.get(key, key.replace("_", " "))

    def _format_summary_value(self, value: Any) -> str:
        if value is None:
            return "空白"
        text = str(value).strip()
        if not text:
            return "空白"
        try:
            number = float(text)
        except ValueError:
            number = None
        if number is not None:
            return f"{number:.4f}".rstrip("0").rstrip(".")
        if text == "equal_weight":
            return "等權重"
        if text == "limited":
            return "樣本有限"
        if len(text) > 32:
            return f"{text[:18]}…{text[-8:]}"
        return text
