"""每日決策工作台 View."""

from datetime import date, datetime
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
)

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskSnapshot,
)
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder
from ui_qt.theme import MIDNIGHT_ANALYST
from ui_qt.workers.task_worker import TaskWorker
from ui_qt.widgets.theme_widgets import CompactCodeList, MetricCard, SectionPanel, StatusBadge, WarningList


class DecisionDeskView(QWidget):
    """每日決策工作台：只透過 DecisionDeskSnapshotBuilder 取得快照。"""

    def __init__(
        self,
        decision_desk_builder: DecisionDeskSnapshotBuilder | None = None,
        as_of_date: date | None = None,
        auto_refresh: bool = True,
        async_refresh: bool = True,
        navigate_to_smart_money_callback: Callable[[str], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.decision_desk_builder = decision_desk_builder or DecisionDeskSnapshotBuilder()
        self.as_of_date = as_of_date or date.today()
        self.async_refresh = async_refresh
        self.navigate_to_smart_money_callback = navigate_to_smart_money_callback
        self._auto_refresh_pending = auto_refresh
        self._last_snapshot: DecisionDeskSnapshot | None = None
        self._refresh_worker: TaskWorker | None = None

        self._setup_ui()
        self._display_pending_snapshot()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._auto_refresh_pending:
            self._auto_refresh_pending = False
            self.refresh_snapshot()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(0, 0, 0, 0)

        title_layout = QHBoxLayout()
        title = QLabel("每日決策")
        title_font = QFont()
        title_font.setPointSize(17)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()

        self.refresh_btn = QPushButton("更新決策摘要")
        self.refresh_btn.setProperty("variant", "primary")
        self.refresh_btn.clicked.connect(self.refresh_snapshot)
        title_layout.addWidget(self.refresh_btn)
        content_layout.addLayout(title_layout)

        self.overall_status_label = QLabel("")
        self.generated_at_label = QLabel("")
        self.overall_status_label.setWordWrap(True)
        status_font = QFont()
        status_font.setPointSize(13)
        status_font.setBold(True)
        self.overall_status_label.setFont(status_font)
        generated_font = QFont()
        generated_font.setPointSize(10)
        self.generated_at_label.setFont(generated_font)
        self.generated_at_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_muted};")
        self.overall_quality_badge = StatusBadge("", "observed")
        self.warning_list = WarningList()
        self.warning_list.setMaximumHeight(120)
        self.overall_warn_label = self.warning_list
        self.decision_date_card = MetricCard("決策日", self.as_of_date.isoformat())
        self.generated_at_card = MetricCard("生成時間", "N/A")

        info_group = SectionPanel("總覽")
        info_layout = info_group.layout
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.overall_status_label, 1)
        status_layout.addWidget(self.overall_quality_badge, 0)
        info_layout.addLayout(status_layout)
        metric_layout = QHBoxLayout()
        metric_layout.addWidget(self.decision_date_card)
        metric_layout.addWidget(self.generated_at_card)
        info_layout.addLayout(metric_layout)
        info_layout.addWidget(self.generated_at_label)
        info_layout.addWidget(self.warning_list)
        content_layout.addWidget(info_group)

        self.action_headline_label = QLabel("今日主結論：尚未載入")
        self.action_headline_label.setWordWrap(True)
        action_font = QFont()
        action_font.setPointSize(14)
        action_font.setBold(True)
        self.action_headline_label.setFont(action_font)
        self.action_note_label = QLabel("研究模式：以下為市場與籌碼輔助判讀，不是交易建議。")
        self.action_note_label.setWordWrap(True)
        self.action_note_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary};")
        conclusion_group = SectionPanel("今日主結論")
        conclusion_group.layout.addWidget(self.action_headline_label)
        conclusion_group.layout.addWidget(self.action_note_label)
        content_layout.addWidget(conclusion_group)

        self.priority_sector_label = QLabel("優先產業：尚未載入")
        self.risk_sector_label = QLabel("避開產業 / 風險區：尚未載入")
        self.priority_stock_label = QLabel("優先研究股票：尚未載入")
        self.risk_stock_label = QLabel("風險股票：尚未載入")
        self.stock_focus_buttons: list[QPushButton] = []
        focus_group = SectionPanel("市場焦點")
        for label in (
            self.priority_sector_label,
            self.risk_sector_label,
            self.priority_stock_label,
            self.risk_stock_label,
        ):
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 10pt;")
            focus_group.layout.addWidget(label)
        self.stock_focus_button_container = QWidget()
        self.stock_focus_button_layout = QHBoxLayout(self.stock_focus_button_container)
        self.stock_focus_button_layout.setContentsMargins(0, 4, 0, 0)
        self.stock_focus_button_layout.setSpacing(6)
        focus_group.layout.addWidget(self.stock_focus_button_container)
        content_layout.addWidget(focus_group)

        self.market_regime_status = QLabel("")
        self.market_regime_value = QLabel("")
        self.market_breadth_status = QLabel("")
        self.market_breadth_value = QLabel("")
        self.sector_rotation_status = QLabel("")
        self.sector_rotation_value = QLabel("")
        self.relative_strength_liquidity_status = QLabel("")
        self.relative_strength_liquidity_value = QLabel("")
        self.watchlist_triggers_status = QLabel("")
        self.watchlist_triggers_value = QLabel("")
        self.portfolio_alerts_status = QLabel("")
        self.portfolio_alerts_value = QLabel("")
        self.risk_prompts_status = QLabel("")
        self.risk_prompts_value = QLabel("")
        self.relative_strength_codes = CompactCodeList()
        self._section_badges: dict[str, StatusBadge] = {}
        self._status_badges: dict[QLabel, StatusBadge] = {}

        sections_group = SectionPanel("各模組狀態")
        sections_layout = sections_group.layout
        sections_layout.addWidget(self._make_section_row("市場情緒", self.market_regime_status, self.market_regime_value))
        sections_layout.addWidget(self._make_section_row("市況廣度", self.market_breadth_status, self.market_breadth_value))
        sections_layout.addWidget(self._make_section_row("產業輪動", self.sector_rotation_status, self.sector_rotation_value))
        sections_layout.addWidget(self._make_section_row("強弱與流動性", self.relative_strength_liquidity_status, self.relative_strength_liquidity_value))
        sections_layout.addWidget(self.relative_strength_codes)
        sections_layout.addWidget(self._make_section_row("Watchlist 提示", self.watchlist_triggers_status, self.watchlist_triggers_value))
        sections_layout.addWidget(self._make_section_row("持倉警示", self.portfolio_alerts_status, self.portfolio_alerts_value))
        sections_layout.addWidget(self._make_section_row("Why Not / 風險提示", self.risk_prompts_status, self.risk_prompts_value))
        content_layout.addWidget(sections_group)
        content_layout.addStretch()

        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)

    def _make_section_row(self, title: str, status_label: QLabel, value_label: QLabel) -> QWidget:
        row = QWidget()
        row.setObjectName("decisionDeskSectionRow")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(3)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary};")
        quality_badge = StatusBadge("", "observed")
        self._section_badges[title] = quality_badge
        self._status_badges[status_label] = quality_badge
        status_label.setWordWrap(True)
        value_label.setWordWrap(True)
        status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        status_label.setMinimumWidth(0)
        value_label.setMinimumWidth(0)
        status_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 10pt;")
        value_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 10pt; line-height: 130%;")
        status_label.hide()
        row.setStyleSheet(
            f"#decisionDeskSectionRow {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border-bottom: 1px solid {MIDNIGHT_ANALYST.border}; }}"
        )

        header_layout.addWidget(title_label, 1)
        header_layout.addWidget(quality_badge, 0)
        row_layout.addLayout(header_layout)
        row_layout.addWidget(status_label)
        row_layout.addWidget(value_label)
        return row

    def refresh_snapshot(self):
        if self.async_refresh:
            self._start_refresh_worker()
        else:
            self._refresh_snapshot()

    def _display_pending_snapshot(self) -> None:
        self.overall_status_label.setText("每日決策尚未載入")
        self.generated_at_label.setText("生成時間：N/A")
        self.overall_quality_badge.setText("尚未載入")
        self.overall_quality_badge.set_quality("missing")
        self.decision_date_card.value_label.setText(self.as_of_date.isoformat())
        self.generated_at_card.value_label.setText("N/A")
        self.warning_list.set_warnings(())
        self.relative_strength_codes.set_groups(())
        self.action_headline_label.setText("今日主結論：尚未載入")
        self.action_note_label.setText("研究模式：以下為市場與籌碼輔助判讀，不是交易建議。")
        self.priority_sector_label.setText("優先產業：尚未載入")
        self.risk_sector_label.setText("避開產業 / 風險區：尚未載入")
        self.priority_stock_label.setText("優先研究股票：尚未載入")
        self.risk_stock_label.setText("風險股票：尚未載入")
        self._set_stock_focus_buttons(())
        for status_label, badge in self._status_badges.items():
            status_label.setText("尚未載入")
            badge.setText("尚未載入")
            badge.set_quality("missing")
        for value_label in (
            self.market_regime_value,
            self.market_breadth_value,
            self.sector_rotation_value,
            self.relative_strength_liquidity_value,
            self.watchlist_triggers_value,
            self.portfolio_alerts_value,
            self.risk_prompts_value,
        ):
            value_label.setText("待背景載入")
        self.overall_status_label.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            "border-radius: 6px; padding: 8px; font-size: 13pt; font-weight: 700;"
        )

    def _display_loading_snapshot(self) -> None:
        self.overall_status_label.setText("每日決策載入中")
        self.generated_at_label.setText("生成時間：背景載入中")
        self.generated_at_card.value_label.setText("載入中")
        self.refresh_btn.setEnabled(False)

    def _start_refresh_worker(self) -> None:
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            return
        self._display_loading_snapshot()
        worker = TaskWorker(self.decision_desk_builder.build_snapshot, self.as_of_date)
        self._refresh_worker = worker
        worker.finished.connect(self._on_refresh_worker_finished)
        worker.error.connect(self._on_refresh_worker_error)
        worker.cancelled.connect(self._on_refresh_worker_cancelled)
        worker.start()

    def _release_refresh_worker(self) -> None:
        self.refresh_btn.setEnabled(True)
        worker = self._refresh_worker
        self._refresh_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_refresh_worker_finished(self, snapshot: DecisionDeskSnapshot) -> None:
        self._last_snapshot = snapshot
        self._render_snapshot(snapshot)
        self._release_refresh_worker()

    def _on_refresh_worker_error(self, error_message: str) -> None:
        self._display_exception_snapshot(error_message)
        self._release_refresh_worker()

    def _on_refresh_worker_cancelled(self) -> None:
        self._release_refresh_worker()

    def closeEvent(self, event) -> None:
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            self._refresh_worker.cancel(cooperative=True, wait=False)
        super().closeEvent(event)

    def _set_section_quality(self, status_label: QLabel, quality: DecisionDeskQuality) -> None:
        label = self._quality_label(quality)
        status_label.setText(label)
        badge = self._status_badges.get(status_label)
        if badge is not None:
            badge.setText(label)
            badge.set_quality(self._quality_token(quality))

    def _refresh_snapshot(self) -> None:
        try:
            snapshot = self.decision_desk_builder.build_snapshot(self.as_of_date)
        except Exception as exc:
            self._display_exception_snapshot(str(exc))
            return

        self._last_snapshot = snapshot
        self._render_snapshot(snapshot)

    def _render_snapshot(self, snapshot: DecisionDeskSnapshot) -> None:
        self._render_answer_first_dashboard(snapshot)
        self.overall_status_label.setText(f"整體品質：{self._quality_label(snapshot.overall_quality)}")
        self.generated_at_label.setText(f"生成時間：{snapshot.generated_at.isoformat()}（決策日 {snapshot.as_of_date.isoformat()}）")
        self.overall_quality_badge.setText(self._quality_label(snapshot.overall_quality))
        self.overall_quality_badge.set_quality(self._quality_token(snapshot.overall_quality))
        self.decision_date_card.value_label.setText(snapshot.as_of_date.isoformat())
        self.generated_at_card.value_label.setText(snapshot.generated_at.strftime("%H:%M:%S"))

        warning_lines = [self._humanize_warning_token(item) for item in snapshot.warnings]
        self.warning_list.set_warnings(warning_lines)

        self._set_section_quality(self.market_regime_status, snapshot.market_regime.quality)
        self.market_regime_value.setText(
            f"市場狀態：{snapshot.market_regime.regime_label or '未定義'}；"
            f"得分：{snapshot.market_regime.regime_score or 0}；"
            f"訊號強度：{snapshot.market_regime.regime_confidence or 0}"
        )

        self._set_section_quality(self.market_breadth_status, snapshot.market_breadth.quality)
        self.market_breadth_value.setText(
            f"多方：{snapshot.market_breadth.advancing or 0}；空方：{snapshot.market_breadth.declining or 0}；"
            f"持平：{snapshot.market_breadth.unchanged or 0}；"
            f"廣度比率BP：{snapshot.market_breadth.breadth_ratio_bp if snapshot.market_breadth.breadth_ratio_bp is not None else 'N/A'}"
        )

        self._set_section_quality(self.sector_rotation_status, snapshot.sector_rotation.quality)
        self.sector_rotation_value.setText(
            f"領先產業：{snapshot.sector_rotation.leading_sector or '未定義'}；"
            f"落後產業：{snapshot.sector_rotation.trailing_sector or '未定義'}；"
            f"輪動強度BP：{snapshot.sector_rotation.rotation_intensity_bp if snapshot.sector_rotation.rotation_intensity_bp is not None else 'N/A'}"
        )

        self._set_section_quality(
            self.relative_strength_liquidity_status,
            snapshot.relative_strength_liquidity.quality,
        )
        self.relative_strength_liquidity_value.setText("")
        self.relative_strength_liquidity_value.hide()
        self.relative_strength_codes.set_groups(
            [
                ("強勢", snapshot.relative_strength_liquidity.top_strength_codes),
                ("弱勢", snapshot.relative_strength_liquidity.weak_strength_codes),
                ("低流動性", snapshot.relative_strength_liquidity.low_liquidity_codes),
            ]
        )

        self._set_section_quality(self.watchlist_triggers_status, snapshot.watchlist_triggers.quality)
        self.watchlist_triggers_value.setText(
            f"觸發數：{snapshot.watchlist_triggers.trigger_count or 0}；"
            f"代碼：{', '.join(snapshot.watchlist_triggers.triggered_codes) if snapshot.watchlist_triggers.triggered_codes else '無'}；"
            f"訊號：{snapshot.watchlist_triggers.top_signal or '無'}"
        )

        self._set_section_quality(self.portfolio_alerts_status, snapshot.portfolio_alerts.quality)
        portfolio_attribution_text = self._format_portfolio_attributions(getattr(snapshot.portfolio_alerts, "attributions", ()))
        self.portfolio_alerts_value.setText(
            f"警示數：{snapshot.portfolio_alerts.alert_count or 0}；"
            f"持倉代碼：{', '.join(snapshot.portfolio_alerts.alert_codes) if snapshot.portfolio_alerts.alert_codes else '無'}；"
            f"等級：{snapshot.portfolio_alerts.alert_level or '無'}；"
            f"來源歸因：{portfolio_attribution_text}"
        )

        self._set_section_quality(self.risk_prompts_status, snapshot.risk_prompts.quality)
        self.risk_prompts_value.setText(self._format_risk_prompts(snapshot.risk_prompts.prompts))

        for section_text in self._collect_warnings(snapshot):
            humanized = self._humanize_warning_token(section_text)
            if humanized not in warning_lines:
                warning_lines.append(humanized)

        if warning_lines:
            warning_lines = [str(item) for item in warning_lines]
            self.warning_list.set_warnings(warning_lines)
        else:
            self.warning_list.set_warnings(())

        if snapshot.overall_quality == DecisionDeskQuality.DEGRADED:
            self.overall_status_label.setStyleSheet(
                f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.warning}; "
                f"border: 1px solid {MIDNIGHT_ANALYST.warning}; "
                "border-radius: 6px; padding: 8px; font-size: 13pt; font-weight: 700;"
            )
        elif snapshot.overall_quality == DecisionDeskQuality.MISSING:
            self.overall_status_label.setStyleSheet(
                f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.danger}; "
                f"border: 1px solid {MIDNIGHT_ANALYST.danger}; "
                "border-radius: 6px; padding: 8px; font-size: 13pt; font-weight: 700;"
            )
        else:
            self.overall_status_label.setStyleSheet(
                f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.success}; "
                f"border: 1px solid {MIDNIGHT_ANALYST.success}; "
                "border-radius: 6px; padding: 8px; font-size: 13pt; font-weight: 700;"
            )

    def _render_answer_first_dashboard(self, snapshot: DecisionDeskSnapshot) -> None:
        action = getattr(snapshot, "action_summary", None)
        if action is None:
            self.action_headline_label.setText("今日主結論：尚未產生")
            self.action_note_label.setText("研究模式：以下為市場與籌碼輔助判讀，不是交易建議。")
        else:
            self.action_headline_label.setText(action.headline)
            self.action_note_label.setText(action.research_mode_note)

        sector_focus = getattr(snapshot, "sector_focus", None)
        if sector_focus is None:
            self.priority_sector_label.setText("優先產業：尚未產生")
            self.risk_sector_label.setText("避開產業 / 風險區：尚未產生")
        else:
            self.priority_sector_label.setText(
                "優先產業：" + self._format_sector_cards(sector_focus.priority_sectors)
            )
            self.risk_sector_label.setText(
                "避開產業 / 風險區：" + self._format_sector_cards(sector_focus.risk_sectors)
            )

        stock_focus = getattr(snapshot, "stock_focus", None)
        if stock_focus is None:
            self.priority_stock_label.setText("優先研究股票：尚未產生")
            self.risk_stock_label.setText("風險股票：尚未產生")
            self._set_stock_focus_buttons(())
        else:
            self.priority_stock_label.setText(
                "優先研究股票：" + self._format_stock_cards(stock_focus.priority_stocks)
            )
            self.risk_stock_label.setText("風險股票：" + self._format_stock_cards(stock_focus.risk_stocks))
            self._set_stock_focus_buttons(tuple(stock_focus.priority_stocks) + tuple(stock_focus.risk_stocks))

    @staticmethod
    def _format_sector_cards(cards) -> str:
        if not cards:
            return "無"
        return "；".join(f"{card.sector_name}（{card.reason}）" for card in cards[:5])

    @staticmethod
    def _format_stock_cards(cards) -> str:
        if not cards:
            return "無"
        return "；".join(f"{card.stock_code} {card.reason}" for card in cards[:5])

    def _set_stock_focus_buttons(self, cards) -> None:
        while self.stock_focus_button_layout.count():
            item = self.stock_focus_button_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.stock_focus_buttons = []
        for card in cards[:6]:
            button = QPushButton(str(card.stock_code))
            button.setToolTip(f"開啟主力流向：{card.stock_code} {card.reason}")
            button.clicked.connect(lambda checked=False, code=str(card.stock_code): self._navigate_to_smart_money(code))
            self.stock_focus_button_layout.addWidget(button)
            self.stock_focus_buttons.append(button)
        self.stock_focus_button_layout.addStretch()

    def _navigate_to_smart_money(self, stock_code: str) -> None:
        if self.navigate_to_smart_money_callback is not None:
            self.navigate_to_smart_money_callback(str(stock_code))

    @staticmethod
    def _format_risk_prompts(prompts) -> str:
        if not prompts:
            return "無"
        parts = []
        for prompt in prompts[:5]:
            code = f"{prompt.code} " if prompt.code else ""
            parts.append(f"[{prompt.severity}] {code}{prompt.title}：{prompt.action_hint}")
        return "；".join(parts)

    @staticmethod
    def _format_portfolio_attributions(attributions) -> str:
        if not attributions:
            return "無"
        parts = []
        for item in attributions[:3]:
            source = DecisionDeskView._display_source_label(item.source_label)
            condition = DecisionDeskView._display_condition_label(item.condition_status)
            chip = DecisionDeskView._display_chip_label(item.chip_risk_level)
            parts.append(
                f"{item.stock_code} 來源：{source}；條件：{condition}；籌碼：{chip}"
            )
        return "；".join(parts)

    @staticmethod
    def _format_code_list(codes, limit: int = 8) -> str:
        items = [str(code) for code in codes or () if str(code)]
        if not items:
            return "無"
        shown = items[:limit]
        suffix = f"（另 {len(items) - limit} 檔）" if len(items) > limit else ""
        return ", ".join(shown) + suffix

    def _display_exception_snapshot(self, error_message: str):
        now = datetime.now()
        fallback_snapshot = DecisionDeskSnapshot(
            as_of_date=self.as_of_date,
            generated_at=now,
            schema_version=1,
            overall_quality=DecisionDeskQuality.DEGRADED,
            market_regime=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"市場情勢:{error_message}",)),
            market_breadth=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"市場廣度:{error_message}",)),
            sector_rotation=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"產業輪動:{error_message}",)),
            relative_strength_liquidity=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"強弱與流動性:{error_message}",)),
            watchlist_triggers=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"Watchlist:{error_message}",)),
            portfolio_alerts=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"持倉警示:{error_message}",)),
            risk_prompts=_EmptySection(DecisionDeskQuality.DEGRADED, warnings=(f"Why Not / 風險提示:{error_message}",)),
            warnings=(f"snapshot_error:{error_message}",),
        )
        self._render_snapshot(fallback_snapshot)

    @staticmethod
    def _quality_label(quality: DecisionDeskQuality) -> str:
        if quality == DecisionDeskQuality.OBSERVED:
            return "觀察到"
        if quality == DecisionDeskQuality.ESTIMATED:
            return "估算"
        if quality == DecisionDeskQuality.MISSING:
            return "缺漏"
        return "降級"

    @staticmethod
    def _quality_token(quality: DecisionDeskQuality) -> str:
        return quality.value if hasattr(quality, "value") else str(quality).lower()

    @staticmethod
    def _collect_warnings(snapshot: DecisionDeskSnapshot) -> list[str]:
        lines: list[str] = []
        section_statuses = [
            ("市場情勢", snapshot.market_regime.warnings),
            ("市場廣度", snapshot.market_breadth.warnings),
            ("產業輪動", snapshot.sector_rotation.warnings),
            ("強弱與流動性", snapshot.relative_strength_liquidity.warnings),
            ("Watchlist", snapshot.watchlist_triggers.warnings),
            ("持倉警示", snapshot.portfolio_alerts.warnings),
            ("Why Not / 風險提示", snapshot.risk_prompts.warnings),
        ]
        for section_name, section_warnings in section_statuses:
            for warning in section_warnings:
                lines.append(f"{section_name}:{warning}")
        return lines

    @staticmethod
    def _humanize_warning_token(warning: object) -> str:
        token = str(warning)
        if not token:
            return token

        section = ""
        raw_code = token
        english_sections = {
            "market_regime": "市場情勢",
            "market_breadth": "市場廣度",
            "sector_rotation": "產業輪動",
            "relative_strength_liquidity": "強弱與流動性",
            "watchlist_triggers": "Watchlist",
            "portfolio_alerts": "持倉警示",
            "risk_prompts": "Why Not / 風險提示",
        }
        for raw_section, display_section in english_sections.items():
            prefix = f"{raw_section}:"
            if token.startswith(prefix):
                section = display_section
                raw_code = token[len(prefix):]
                break
        known_sections = (
            "市場情勢",
            "市場廣度",
            "產業輪動",
            "強弱與流動性",
            "Watchlist",
            "持倉警示",
            "Why Not / 風險提示",
        )
        if not section:
            for section_name in known_sections:
                prefix = f"{section_name}:"
                if token.startswith(prefix):
                    section = section_name
                    raw_code = token[len(prefix):]
                    break

        def with_section(message: str) -> str:
            if section and not message.startswith(section):
                return f"{section}：{message}"
            return message

        parts = raw_code.split(":")
        code = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        extra = parts[2:] if len(parts) > 2 else []
        source_label = DecisionDeskView._display_source_label(value)

        if code == "relative_strength_liquidity_skipped_symbols" and value:
            return with_section(f"強弱與流動性：因流動性或資料條件不足跳過 {value} 檔股票")
        if code == "relative_strength_liquidity_missing":
            return with_section("強弱與流動性資料缺漏")
        if code == "relative_strength_liquidity_insufficient_history":
            return with_section("強弱與流動性歷史資料不足，無法完成排序")
        if code == "relative_strength_liquidity_missing_required_columns":
            return with_section("強弱與流動性缺少必要欄位")
        if code == "watchlist_trigger_data_insufficient" and value:
            return with_section(f"Watchlist 提示：{value} 資料不足，暫無法判斷觸發狀態")
        if code == "watchlist_stale":
            return with_section("Watchlist 資料可能不是最新狀態")
        if code == "sector_missing":
            return with_section("產業輪動資料缺漏")
        if code == "market_breadth_fetch_error":
            reason = value or "未知原因"
            return with_section(f"市場廣度資料取得失敗：{reason}")
        if code == "risk_prompt_source_quality" and len(parts) >= 3:
            quality = DecisionDeskView._display_quality_value(extra[0])
            return with_section(f"風險提示來源「{source_label}」目前為{quality}資料")
        if code == "watchlist_trigger_risk_alert" and value:
            return with_section(f"Watchlist 觸發風險提示：{value}")
        if code == "portfolio_alert_top_source" and len(parts) >= 3:
            count = extra[0]
            return with_section(f"持倉警示主要來源為「{source_label}」，共 {count} 筆")
        if code == "portfolio_alerts_chip_estimated" and value:
            return with_section(f"{value} 籌碼張數使用估算資料")
        if code == "portfolio_alerts_chip_unavailable_events" and len(parts) >= 3:
            count = extra[0]
            return with_section(f"{value} 有 {count} 筆籌碼事件缺少可用張數")
        if code == "portfolio_alerts_chip_data_missing" and value:
            return with_section(f"{value} 籌碼資料缺漏")
        if code == "portfolio_alerts_chip_summary_invalid" and value:
            return with_section(f"{value} 籌碼摘要無法判讀")
        if code == "portfolio_alerts_no_active_position":
            return with_section("目前沒有可檢查的啟用持倉")
        if code == "portfolio_alerts_condition_monitor_error" and len(parts) >= 3:
            return with_section(f"{value} 持倉條件檢查失敗：{':'.join(extra)}")
        if code == "portfolio_alerts_portfolio_service_error" and value:
            return with_section(f"持倉資料服務發生錯誤：{value}")
        if code.endswith("_missing"):
            name = DecisionDeskView._display_source_label(code[:-8])
            return with_section(f"{name}資料缺漏")
        if code.endswith("_provider_error"):
            name = DecisionDeskView._display_source_label(code[:-15])
            return with_section(f"{name}資料提供者發生錯誤")
        if code.endswith("_as_of_fallback"):
            name = DecisionDeskView._display_source_label(code[:-15])
            return with_section(f"{name}使用備援決策日")

        return token

    @staticmethod
    def _display_source_label(source: object) -> str:
        text = str(source or "")
        labels = {
            "relative_strength_liquidity": "強弱與流動性",
            "relative_strength_liquidity_service": "強弱與流動性",
            "portfolio_alerts": "持倉警示",
            "portfolio_alert": "持倉警示",
            "watchlist_triggers": "觀察清單觸發",
            "watchlist": "觀察清單",
            "market_breadth": "市場廣度",
            "sector_rotation": "產業輪動",
            "market_regime": "市場情勢",
            "risk_prompts": "風險提示",
            "manual": "手動來源",
            "recommendation_result": "推薦結果",
            "fundamental": "基本面診斷",
        }
        if text.startswith("recommendation_result:"):
            return "推薦結果 " + text.split(":", 1)[1]
        return labels.get(text, text)

    @staticmethod
    def _display_quality_value(value: object) -> str:
        text = str(value or "").lower()
        labels = {
            "observed": "觀察到",
            "estimated": "估算",
            "degraded": "降級",
            "missing": "缺漏",
            "unavailable": "不可用",
        }
        return labels.get(text, str(value or "未知"))

    @staticmethod
    def _display_condition_label(value: object) -> str:
        text = str(value or "").lower()
        labels = {
            "valid": "正常",
            "warning": "警示",
            "invalid": "失效",
            "unknown": "未知",
        }
        return labels.get(text, str(value or "未知"))

    @staticmethod
    def _display_chip_label(value: object) -> str:
        text = str(value or "").lower()
        labels = {
            "bullish": "偏多",
            "bearish": "偏空",
            "neutral": "中性",
            "risk": "風險",
            "extreme": "極端風險",
            "unknown": "未知",
        }
        return labels.get(text, str(value or "未知"))


class _EmptySection:
    """Fallback section with minimal required fields for degraded rendering."""

    def __init__(self, quality: DecisionDeskQuality, warnings: tuple[str, ...] = ()):
        self.quality = quality
        self.warnings = warnings
        self.regime_label = None
        self.regime_score = None
        self.regime_confidence = None
        self.breadth_ratio_bp = None
        self.advancing = None
        self.declining = None
        self.unchanged = None
        self.leading_sector = None
        self.trailing_sector = None
        self.rotation_intensity_bp = None
        self.trigger_count = None
        self.triggered_codes: tuple[str, ...] = ()
        self.top_signal = None
        self.top_strength_codes: tuple[str, ...] = ()
        self.weak_strength_codes: tuple[str, ...] = ()
        self.low_liquidity_codes: tuple[str, ...] = ()
        self.alert_count = None
        self.alert_codes: tuple[str, ...] = ()
        self.alert_level = None
        self.prompts: tuple[object, ...] = ()
        self.attributions: tuple[object, ...] = ()
