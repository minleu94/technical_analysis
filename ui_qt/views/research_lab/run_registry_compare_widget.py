"""Research Run Registry 跨 run 比較子頁。"""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app_module.research_run_comparison_service import (
    ComparabilityStatus,
    ResearchRunComparisonService,
)
from app_module.research_run_dtos import ResearchRunMetadataDTO
from ui_qt.models.pandas_table_model import PandasTableModel


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
        self._request_id = 0
        self._all_runs: list[ResearchRunMetadataDTO] = []
        self._filtered_runs: list[ResearchRunMetadataDTO] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("run type"))
        self.run_type_filter = QComboBox()
        self.run_type_filter.addItems(["全部", "single_backtest", "recommendation_portfolio"])
        self.run_type_filter.currentTextChanged.connect(self.refresh_runs)
        filter_row.addWidget(self.run_type_filter)

        filter_row.addWidget(QLabel("strategy"))
        self.strategy_filter = QLineEdit()
        self.strategy_filter.setPlaceholderText("strategy_id")
        self.strategy_filter.textChanged.connect(self.refresh_runs)
        filter_row.addWidget(self.strategy_filter)

        filter_row.addWidget(QLabel("tag"))
        self.tag_filter = QLineEdit()
        self.tag_filter.setPlaceholderText("tag")
        self.tag_filter.textChanged.connect(self.refresh_runs)
        filter_row.addWidget(self.tag_filter)

        self.refresh_button = QPushButton("重新整理")
        self.refresh_button.clicked.connect(self.refresh_runs)
        filter_row.addWidget(self.refresh_button)
        layout.addLayout(filter_row)

        list_group = QGroupBox("Research Runs")
        list_layout = QVBoxLayout(list_group)
        self.run_list = QListWidget()
        self.run_list.setSelectionMode(QListWidget.ExtendedSelection)
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
        self.comparability_badge.setAlignment(Qt.AlignCenter)
        self.comparability_badge.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.comparability_badge.setStyleSheet("padding: 6px; background: #ECEFF1;")
        layout.addWidget(self.comparability_badge)

        tables_row = QHBoxLayout()
        self.params_diff_table = self._new_table()
        self.metrics_table = self._new_table()
        self.regime_table = self._new_table()
        self.benchmark_table = self._new_table()
        tables_row.addWidget(self._wrap_table("參數差異", self.params_diff_table))
        tables_row.addWidget(self._wrap_table("Metrics", self.metrics_table))
        tables_row.addWidget(self._wrap_table("Regime", self.regime_table))
        tables_row.addWidget(self._wrap_table("Benchmark", self.benchmark_table))
        layout.addLayout(tables_row, stretch=2)

        self.normalized_equity_table = self._new_table()
        layout.addWidget(self._wrap_table("Normalized Equity", self.normalized_equity_table), stretch=2)

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

        run_data = [self.research_run_service.load_run_data(run_id) for run_id in run_ids]
        metadata = [item.metadata for item in run_data]
        comparability = self.comparison_service.evaluate_comparability(metadata)
        self._render_comparability_badge(comparability.status, comparability.reasons)

        self._set_table_model(self.params_diff_table, self._build_params_diff(metadata))
        self._set_table_model(self.metrics_table, self._flatten_run_dicts(metadata, "metrics"))
        self._set_table_model(self.regime_table, self._flatten_run_dicts(metadata, "regime_breakdown"))
        benchmark = self.comparison_service.collect_benchmark_attribution(metadata)
        self._set_table_model(self.benchmark_table, self._flatten_mapping_by_run(benchmark))

        normalized = self.comparison_service.build_normalized_equity(
            {item.metadata.run_id: item.equity for item in run_data}
        )
        self._set_table_model(
            self.normalized_equity_table,
            self._normalized_equity_frame(normalized.normalized),
        )

    def _apply_filters_and_render(self) -> None:
        run_type = self.run_type_filter.currentText()
        strategy = self.strategy_filter.text().strip().lower()
        tag = self.tag_filter.text().strip().lower()

        filtered: list[ResearchRunMetadataDTO] = []
        for run in self._all_runs:
            if run_type != "全部" and run.run_type != run_type:
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
            text = f"{run.run_name} | {run.run_type} | {run.strategy_id} | {run.created_at[:16]}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, run.run_id)
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

    def _render_comparability_badge(
        self, status: ComparabilityStatus, reasons: list[str]
    ) -> None:
        reason_text = "" if not reasons else " | " + ", ".join(reasons)
        self.comparability_badge.setText(f"{status.value}{reason_text}")
        colors = {
            ComparabilityStatus.COMPARABLE: "#DFF3E3",
            ComparabilityStatus.CAUTION: "#FFF4D6",
            ComparabilityStatus.INCOMPATIBLE: "#FDE2E2",
        }
        self.comparability_badge.setStyleSheet(
            f"padding: 6px; background: {colors[status]};"
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
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QTableView.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _wrap_table(self, title: str, table: QTableView) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(table)
        return group

    def _set_table_model(self, table: QTableView, frame: pd.DataFrame) -> None:
        model = PandasTableModel(frame)
        table.setModel(model)
        table.resizeColumnsToContents()
