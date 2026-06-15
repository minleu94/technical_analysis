"""每日決策工作台 View."""

from datetime import date, datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QGroupBox,
)

from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskSnapshot,
)
from app_module.decision_desk_service import DecisionDeskSnapshotBuilder


class DecisionDeskView(QWidget):
    """每日決策工作台：只透過 DecisionDeskSnapshotBuilder 取得快照。"""

    def __init__(
        self,
        decision_desk_builder: DecisionDeskSnapshotBuilder | None = None,
        as_of_date: date | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.decision_desk_builder = decision_desk_builder or DecisionDeskSnapshotBuilder()
        self.as_of_date = as_of_date or date.today()
        self._last_snapshot: DecisionDeskSnapshot | None = None

        self._setup_ui()
        self._refresh_snapshot()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        title_layout = QHBoxLayout()
        title = QLabel("每日決策")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        title_layout.addWidget(title)
        title_layout.addStretch()

        self.refresh_btn = QPushButton("更新決策摘要")
        self.refresh_btn.clicked.connect(self.refresh_snapshot)
        title_layout.addWidget(self.refresh_btn)
        layout.addLayout(title_layout)

        self.overall_status_label = QLabel("")
        self.generated_at_label = QLabel("")
        self.overall_warn_label = QTextEdit()
        self.overall_warn_label.setReadOnly(True)
        self.overall_warn_label.setMaximumHeight(90)

        info_group = QGroupBox("總覽")
        info_layout = QVBoxLayout(info_group)
        info_layout.addWidget(self.overall_status_label)
        info_layout.addWidget(self.generated_at_label)
        info_layout.addWidget(self.overall_warn_label)
        layout.addWidget(info_group)

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
        self.risk_prompts_value.setWordWrap(True)

        sections_group = QGroupBox("各模組狀態")
        sections_layout = QVBoxLayout(sections_group)
        sections_layout.addWidget(self._make_section_row("市場情緒", self.market_regime_status, self.market_regime_value))
        sections_layout.addWidget(self._make_section_row("市況廣度", self.market_breadth_status, self.market_breadth_value))
        sections_layout.addWidget(self._make_section_row("產業輪動", self.sector_rotation_status, self.sector_rotation_value))
        sections_layout.addWidget(self._make_section_row("強弱與流動性", self.relative_strength_liquidity_status, self.relative_strength_liquidity_value))
        sections_layout.addWidget(self._make_section_row("Watchlist 提示", self.watchlist_triggers_status, self.watchlist_triggers_value))
        sections_layout.addWidget(self._make_section_row("持倉警示", self.portfolio_alerts_status, self.portfolio_alerts_value))
        sections_layout.addWidget(self._make_section_row("Why Not / 風險提示", self.risk_prompts_status, self.risk_prompts_value))
        layout.addWidget(sections_group)

    def _make_section_row(self, title: str, status_label: QLabel, value_label: QLabel) -> QWidget:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 4, 0, 4)
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)

        row_layout.addWidget(title_label)
        row_layout.addWidget(status_label)
        row_layout.addWidget(value_label)
        return row

    def refresh_snapshot(self):
        self._refresh_snapshot()

    def _refresh_snapshot(self) -> None:
        try:
            snapshot = self.decision_desk_builder.build_snapshot(self.as_of_date)
        except Exception as exc:
            self._display_exception_snapshot(str(exc))
            return

        self._last_snapshot = snapshot
        self._render_snapshot(snapshot)

    def _render_snapshot(self, snapshot: DecisionDeskSnapshot) -> None:
        self.overall_status_label.setText(f"整體品質：{self._quality_label(snapshot.overall_quality)}")
        self.generated_at_label.setText(f"生成時間：{snapshot.generated_at.isoformat()}（決策日 {snapshot.as_of_date.isoformat()}）")

        warning_lines = list(snapshot.warnings)
        self.overall_warn_label.setPlainText("\n".join(warning_lines) if warning_lines else "無警示")

        self.market_regime_status.setText(f"品質：{self._quality_label(snapshot.market_regime.quality)}")
        self.market_regime_value.setText(
            f"市場狀態：{snapshot.market_regime.regime_label or '未定義'}；"
            f"得分：{snapshot.market_regime.regime_score or 0}；"
            f"訊號強度：{snapshot.market_regime.regime_confidence or 0}"
        )

        self.market_breadth_status.setText(f"品質：{self._quality_label(snapshot.market_breadth.quality)}")
        self.market_breadth_value.setText(
            f"多方：{snapshot.market_breadth.advancing or 0}；空方：{snapshot.market_breadth.declining or 0}；"
            f"持平：{snapshot.market_breadth.unchanged or 0}；"
            f"廣度比率BP：{snapshot.market_breadth.breadth_ratio_bp if snapshot.market_breadth.breadth_ratio_bp is not None else 'N/A'}"
        )

        self.sector_rotation_status.setText(f"品質：{self._quality_label(snapshot.sector_rotation.quality)}")
        self.sector_rotation_value.setText(
            f"領先產業：{snapshot.sector_rotation.leading_sector or '未定義'}；"
            f"落後產業：{snapshot.sector_rotation.trailing_sector or '未定義'}；"
            f"輪動強度BP：{snapshot.sector_rotation.rotation_intensity_bp if snapshot.sector_rotation.rotation_intensity_bp is not None else 'N/A'}"
        )

        self.relative_strength_liquidity_status.setText(
            f"品質：{self._quality_label(snapshot.relative_strength_liquidity.quality)}"
        )
        self.relative_strength_liquidity_value.setText(
            f"強勢：{', '.join(snapshot.relative_strength_liquidity.top_strength_codes) if snapshot.relative_strength_liquidity.top_strength_codes else '無'}；"
            f"弱勢：{', '.join(snapshot.relative_strength_liquidity.weak_strength_codes) if snapshot.relative_strength_liquidity.weak_strength_codes else '無'}；"
            f"低流動性：{', '.join(snapshot.relative_strength_liquidity.low_liquidity_codes) if snapshot.relative_strength_liquidity.low_liquidity_codes else '無'}"
        )

        self.watchlist_triggers_status.setText(f"品質：{self._quality_label(snapshot.watchlist_triggers.quality)}")
        self.watchlist_triggers_value.setText(
            f"觸發數：{snapshot.watchlist_triggers.trigger_count or 0}；"
            f"代碼：{', '.join(snapshot.watchlist_triggers.triggered_codes) if snapshot.watchlist_triggers.triggered_codes else '無'}；"
            f"訊號：{snapshot.watchlist_triggers.top_signal or '無'}"
        )

        self.portfolio_alerts_status.setText(f"品質：{self._quality_label(snapshot.portfolio_alerts.quality)}")
        self.portfolio_alerts_value.setText(
            f"警示數：{snapshot.portfolio_alerts.alert_count or 0}；"
            f"持倉代碼：{', '.join(snapshot.portfolio_alerts.alert_codes) if snapshot.portfolio_alerts.alert_codes else '無'}；"
            f"等級：{snapshot.portfolio_alerts.alert_level or '無'}"
        )

        self.risk_prompts_status.setText(f"品質：{self._quality_label(snapshot.risk_prompts.quality)}")
        self.risk_prompts_value.setText(self._format_risk_prompts(snapshot.risk_prompts.prompts))

        for section_text in self._collect_warnings(snapshot):
            if section_text not in warning_lines:
                warning_lines.append(section_text)

        if warning_lines:
            warning_lines = [str(item) for item in warning_lines]
            self.overall_warn_label.setPlainText("\n".join(warning_lines))
        else:
            self.overall_warn_label.setPlainText("無警示")

        if snapshot.overall_quality == DecisionDeskQuality.DEGRADED:
            self.overall_status_label.setStyleSheet("color: #b71c1c;")
        elif snapshot.overall_quality == DecisionDeskQuality.MISSING:
            self.overall_status_label.setStyleSheet("color: #f57f17;")
        else:
            self.overall_status_label.setStyleSheet("")

    @staticmethod
    def _format_risk_prompts(prompts) -> str:
        if not prompts:
            return "無"
        parts = []
        for prompt in prompts[:5]:
            code = f"{prompt.code} " if prompt.code else ""
            parts.append(f"[{prompt.severity}] {code}{prompt.title}：{prompt.action_hint}")
        return "；".join(parts)

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
            return "缺漏 (missing)"
        return "降級 (degraded)"

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
