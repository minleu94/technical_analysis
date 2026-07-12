from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from app_module.workbench_dtos import (
    WorkbenchActionItem,
    WorkbenchChecklistItem,
    WorkbenchEvidenceFeedItem,
    WorkbenchEvidenceSummary,
    WorkbenchOperatingLoopStep,
    WorkbenchReviewItem,
    WorkbenchStatusItem,
)
from app_module.advice_dtos import PortfolioAdviceDTO, RecommendationAdviceDTO


ColumnSpec = tuple[tuple[str, str], ...]


class _WorkbenchTableModel(QAbstractTableModel):
    COLUMNS: ColumnSpec = ()

    def __init__(self, rows: Sequence[Any] = (), parent=None) -> None:
        super().__init__(parent)
        self._rows = tuple(rows)

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        field_name = self.COLUMNS[index.column()][0]
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            return _display_value(getattr(row, field_name, None))
        status = _row_status(row)
        tone = _status_tone(status)
        if role == Qt.ForegroundRole and field_name in {"status", "severity"}:
            return QBrush(QColor(tone["fg"]))
        if role == Qt.BackgroundRole and _is_attention_status(status):
            return QBrush(QColor(tone["bg"]))
        if role == Qt.FontRole and field_name in {"status", "severity", "title", "label"}:
            font = QFont()
            font.setBold(True)
            return font
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.COLUMNS):
            return self.COLUMNS[section][1]
        return section + 1

    def column_index(self, field_name: str) -> int:
        for index, (column_field, _) in enumerate(self.COLUMNS):
            if column_field == field_name:
                return index
        raise KeyError(field_name)

    def raw_value(self, row: int, field_name: str):
        return getattr(self._rows[row], field_name)

    def row_at(self, row: int):
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None


class WorkbenchStatusStripTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "項目"),
        ("value", "值"),
        ("status", "狀態"),
        ("summary", "摘要"),
    )

    def __init__(self, rows: Sequence[WorkbenchStatusItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchReviewQueueTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("severity", "嚴重度"),
        ("title", "標題"),
        ("source", "來源"),
        ("code", "代碼"),
        ("summary", "摘要"),
        ("drilldown_target", "下鑽"),
    )

    def __init__(self, rows: Sequence[WorkbenchReviewItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchEvidenceFeedTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "證據來源"),
        ("status", "狀態"),
        ("summary", "摘要"),
    )

    def __init__(self, rows: Sequence[WorkbenchEvidenceFeedItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchActionItemTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("queue_group", "佇列"),
        ("severity", "嚴重度"),
        ("source_label", "來源"),
        ("title", "待處理事項"),
        ("summary", "摘要"),
    )

    def __init__(self, rows: Sequence[WorkbenchActionItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchOperatingLoopTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "步驟"),
        ("cadence", "節奏"),
        ("status", "狀態"),
        ("summary", "摘要"),
        ("source_trace", "Source trace"),
        ("linked_item_ids", "連結項目"),
        ("drilldown_target", "下鑽"),
        ("guidance", "人工提示"),
        ("write_intent", "寫入意圖"),
    )

    def __init__(self, rows: Sequence[WorkbenchOperatingLoopStep] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchEvidenceTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "證據"),
        ("status", "狀態"),
        ("summary", "摘要"),
    )

    def __init__(self, rows: Sequence[WorkbenchEvidenceSummary] = (), parent=None) -> None:
        super().__init__(rows, parent)


class WorkbenchChecklistTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("label", "檢查項目"),
        ("status", "狀態"),
        ("summary", "摘要"),
    )

    def __init__(self, rows: Sequence[WorkbenchChecklistItem] = (), parent=None) -> None:
        super().__init__(rows, parent)


class AdviceRecommendationTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("stock_code", "標的"),
        ("advice_action", "Action"),
        ("why_not_reasons", "理由"),
        ("data_quality", "資料品質"),
        ("execution_feasibility", "可成交性"),
    )

    def __init__(self, rows: Sequence[RecommendationAdviceDTO] = (), parent=None) -> None:
        super().__init__(rows, parent)


class AdviceCandidateTableModel(AdviceRecommendationTableModel):
    """Professional research candidates only; never used for formal Advice rows."""


class AdvicePortfolioTableModel(_WorkbenchTableModel):
    COLUMNS = (
        ("stock_code", "標的"),
        ("advice_action", "Action"),
        ("target_weight_bp", "Target (bp)"),
        ("current_weight_bp", "Current (bp)"),
        ("weight_gap_bp", "Gap (bp)"),
        ("data_quality", "資料品質"),
        ("execution_feasibility", "可成交性"),
    )

    def __init__(self, rows: Sequence[PortfolioAdviceDTO] = (), parent=None) -> None:
        super().__init__(rows, parent)


def _display_value(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, tuple):
        return "；".join(_display_token(str(item)) for item in value) or "無"
    if isinstance(value, list):
        return "；".join(_display_token(str(item)) for item in value) or "無"
    if value is None:
        return ""
    return _display_token(str(value))


def display_workbench_value(value: str) -> str:
    return _display_token(value)


def _display_token(value: str) -> str:
    text = value.strip()
    if not text:
        return ""

    token_map = {
        "Daily Decision snapshot": "每日決策快照",
        "Data quality": "資料品質",
        "Evidence gate": "證據門檻",
        "Production Scheduler": "正式排程器",
        "Watchlist trigger review": "觀察清單觸發覆盤",
        "Portfolio alert review": "持倉警示覆盤",
        "Historical replay simulated evidence": "歷史 replay 模擬證據",
        "Weekly evidence operations history": "每週 evidence operations 歷史",
        "Multi-day dry-run": "多日 dry-run",
        "Source gaps 收斂狀態": "來源缺口收斂狀態",
        "Read-only Agent report sample": "唯讀 Agent 報告樣本",
        "Decision snapshot freshness": "決策快照新鮮度",
        "Evidence gate status": "證據門檻狀態",
        "Manual review note": "人工覆盤註記",
        "Scheduler write-mode": "排程器寫入模式",
        "Weekly review history": "每週覆盤歷史",
        "Scheduler gate": "排程 Gate",
        "daily": "每日",
        "weekly_until_3": "每週直到 3 筆",
        "daily_until_3": "每日直到 3 筆",
        "after_manual_review": "人工覆盤後",
        "phase_gate": "Phase gate",
        "read_only_sources": "唯讀來源",
        "read_only_sources_plus_historical_replay": "唯讀來源 + 歷史 replay summary",
        "missing": "缺漏",
        "warning": "警告",
        "info": "資訊",
        "observed": "已觀測",
        "ready": "已就緒",
        "degraded": "降級",
        "blocked": "封鎖",
        "done": "完成",
        "off": "關閉",
        "action_required": "需要處理",
        "waiting_for_time": "等待真實時間累積",
        "manual_required": "需要人工覆盤",
        "pre_v2_readiness": "Pre-V2 準備度",
        "watchlist_trigger": "觀察清單觸發",
        "portfolio_alert": "持倉警示",
        "risk_prompt": "風險提示",
        "portfolio_review": "持倉覆盤",
        "daily_review": "每日判讀",
        "evidence_gate": "證據門檻",
        "replay_diagnostics": "Replay 診斷",
        "manual_review": "人工覆盤",
        "evidence_mode": "證據模式",
        "daily_decision": "每日決策",
        "evidence_review": "證據覆盤",
        "daily_decision_snapshot": "Daily Decision snapshot",
        "evidence_review_readiness": "Evidence Review readiness",
        "portfolio_alerts": "Portfolio alerts",
        "replay_summary_diagnostics": "Replay summary diagnostics",
        "DecisionDeskSnapshot": "DecisionDeskSnapshot",
        "DecisionDeskSnapshot.portfolio_alerts": "DecisionDeskSnapshot.portfolio_alerts",
        "PreV2ReadinessReport": "PreV2ReadinessReport",
        "HistoricalReplaySummary": "HistoricalReplaySummary",
        "portfolio_alert_requires_manual_review": "portfolio_alert_requires_manual_review",
        "watchlist_trigger_requires_manual_review": "watchlist_trigger_requires_manual_review",
        "replay_summary_not_supplied": "未提供 replay summary",
        "decision_desk_snapshot_missing": "缺 Daily Decision snapshot",
        "why_not_payload_missing": "缺 Why Not payload",
        "liquidity_gate_payload_missing": "缺 liquidity gate payload",
        "screening_matrix_missing": "缺 screening matrix",
        "strategy_lifecycle_evidence_table_missing": "缺 strategy lifecycle evidence table",
        "insufficient_weekly_history_records": "每週歷史筆數不足",
        "insufficient_dry_run_days": "多日 dry-run 天數不足",
        "simulated_scheduler": "模擬 scheduler（simulated_scheduler）",
        "not_production_readiness": "非 production readiness 證據",
        "missing_industry_benchmark": "缺產業基準",
        "pending_insufficient_future_data": "等待未來資料不足",
    }
    if text in token_map:
        return token_map[text]

    if text.startswith("source_gap_coverage:"):
        payload = text.split(":", 1)[1]
        source, _, ratio = payload.partition("=")
        return f"來源缺口覆蓋：{_display_token(source)} {ratio}"
    if text.startswith("source_gap:"):
        return f"來源缺口：{_display_token(text.split(':', 1)[1])}"
    if text.startswith("payload_gap:"):
        return f"payload 缺口：{_display_token(text.split(':', 1)[1])}"
    if text.startswith("outcome_maturity:"):
        values = _key_values(text.split(":", 1)[1])
        return (
            f"結果成熟度：已成熟 {_fmt_int(values.get('ready'))}；"
            f"等待未來資料 {_fmt_int(values.get('pending_future_data'))}"
        )
    if text.startswith("benchmark_coverage:"):
        return _coverage_text("市場基準覆蓋", text)
    if text.startswith("industry_benchmark_coverage:"):
        return _coverage_text("產業基準覆蓋", text)
    if text.startswith("missing_benchmark:"):
        return f"缺市場基準：{_fmt_int(text.split(':', 1)[1])}"
    if text.startswith("missing_industry_benchmark:"):
        return f"缺產業基準：{_fmt_int(text.split(':', 1)[1])}"
    if text.startswith("pending_future_data:"):
        return f"等待未來資料限制：{_fmt_int(text.split(':', 1)[1])}"
    if text.startswith("phase0_gate_not_satisfied:"):
        return "Phase 0 限制：weekly history 與 multi-day dry-run 必須靠真實時間累積"
    if text.startswith("replay_direction_assessment:"):
        return "方向判讀：市場基準已可用，但產業基準、來源缺口或未成熟 outcome 仍阻擋 production readiness"

    return text


def _row_status(row: object) -> str:
    return str(getattr(row, "status", getattr(row, "severity", "")) or "")


def _is_attention_status(status: str) -> bool:
    return status in {
        "critical",
        "warning",
        "degraded",
        "missing",
        "blocked",
        "action_required",
        "waiting_for_time",
        "manual_required",
    }


def _status_tone(status: str) -> dict[str, str]:
    token = str(status)
    if token in {"critical", "blocked", "missing"}:
        return {"fg": "#ef4444", "bg": "#2a1114"}
    if token in {"warning", "degraded", "action_required", "manual_required", "waiting_for_time"}:
        return {"fg": "#f59e0b", "bg": "#221a10"}
    if token in {"observed", "ready", "done", "passed"}:
        return {"fg": "#22c55e", "bg": "#0d2116"}
    if token in {"manual_observed", "info"}:
        return {"fg": "#38bdf8", "bg": "#0b1c27"}
    return {"fg": "#94a3b8", "bg": "#111827"}


def _coverage_text(label: str, text: str) -> str:
    values = _key_values(text.split(":", 1)[1])
    return (
        f"{label}：{_fmt_int(values.get('covered'))}/{_fmt_int(values.get('total'))}，"
        f"缺 {_fmt_int(values.get('missing'))}"
    )


def _key_values(payload: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in payload.split(","):
        key, separator, value = part.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _fmt_int(value: str | None) -> str:
    try:
        return f"{int(value or 0):,}"
    except ValueError:
        return str(value or 0)
