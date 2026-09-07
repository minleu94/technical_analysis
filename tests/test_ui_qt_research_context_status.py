"""P1 UI 契約：單股研究上下文路由與 Research Console 狀態翻譯。"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolButton

from app_module.dtos import RecommendationDTO
from app_module.research_console_dtos import (
    ResearchConsoleBoundaryDTO,
    ResearchConsoleDTO,
    ResearchPipelineRowDTO,
)
from app_module.research_session import (
    ResearchContextChanged,
    ResearchSessionStore,
    ResearchStockContextDTO,
)
from ui_qt.main import MainWindow
from ui_qt.models.pandas_table_model import PandasTableModel
from ui_qt.views.recommendation_view import RecommendationView
from ui_qt.views.research_console_view import ResearchConsoleView
from ui_qt.views.watchlist_view import WatchlistView
from ui_qt.widgets.session_context_strip import SessionContextStrip


def app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_store_keeps_full_stock_context_and_can_clear() -> None:
    store = ResearchSessionStore()
    context = ResearchStockContextDTO(
        stock_code=" 2330 ",
        stock_name=" 台積電 ",
        decision_date="2026-09-05",
        data_date="2026-09-04",
        result_id="result-1",
        profile_id="momentum",
        profile_version="2.1",
        source_id="provider-1",
        source_kind="recommendation",
        source_label="已保存推薦結果",
        source_workspace="recommendation",
    )

    snapshot = store.set_stock_context(context)

    assert snapshot.stock_context == context
    assert snapshot.active_stock_code == "2330"
    assert snapshot.decision_date == "2026-09-05"
    assert snapshot.data_date == "2026-09-04"
    assert snapshot.result_id == "result-1"
    assert snapshot.profile_id == "momentum"
    assert snapshot.source_id == "provider-1"
    assert store.clear_stock_context().stock_context is None


def test_store_accepts_context_wrapped_event_alias() -> None:
    store = ResearchSessionStore()
    context = ResearchStockContextDTO(stock_code="1101", source_workspace="watchlist")
    snapshot = store.dispatch(ResearchContextChanged(context=context))
    assert snapshot.stock_context == context


def test_context_strip_shows_dates_and_returns_snapshot() -> None:
    app()
    store = ResearchSessionStore()
    strip = SessionContextStrip(store)
    returned = []
    strip.returnToSourceRequested.connect(returned.append)
    store.set_stock_context(
        ResearchStockContextDTO(
            stock_code="2330",
            stock_name="台積電",
            decision_date="2026-09-05",
            data_date="2026-09-04",
            result_id="result-1",
            source_id="provider-1",
            source_label="已保存推薦結果",
            source_workspace="recommendation",
        )
    )
    strip.resize(900, 24)
    strip.show()
    app().processEvents()

    assert "2330 台積電" in strip._full_context_text
    assert "決策日：2026-09-05" in strip._full_context_text
    assert "資料日：2026-09-04" in strip._full_context_text
    assert strip.return_button.isVisible()
    strip.return_button.click()
    assert returned and returned[0].stock_context.result_id == "result-1"
    strip.close()


def _recommendation_view() -> RecommendationView:
    regime_service = SimpleNamespace(
        detect_regime=lambda: SimpleNamespace(
            regime="Trend",
            regime_name_cn="趨勢",
            confidence=0.8,
            details={"source": "fixture", "as_of_date": "2026-09-05"},
        ),
        get_strategy_config=lambda _regime: {},
    )
    view = RecommendationView(MagicMock(), regime_service)
    view.current_config = {"as_of_date": "2026-09-05"}
    view.current_profile = "momentum"
    view.current_result_id = "result-1"
    view.recommendation_service.last_run_context = {
        "as_of_date": "2026-09-05",
        "data_date": "2026-09-04",
        "profile_id": "momentum",
        "profile_version": "2.1",
        "source_id": "provider-1",
    }
    recommendation = RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        close_price=100,
        price_change=1,
        total_score=80,
        indicator_score=80,
        pattern_score=80,
        volume_score=80,
        recommendation_reasons="均線向上",
        industry="半導體",
        regime_match=True,
    )
    view.current_recommendations = [recommendation]
    view.recommendations_model = PandasTableModel(
        pd.DataFrame([recommendation.to_dict()])
    )
    view.results_table.setModel(view.recommendations_model)
    return view


def test_recommendation_drilldown_emits_saved_context_without_recompute() -> None:
    app()
    view = _recommendation_view()
    emitted = []
    view.stockResearchRequested.connect(emitted.append)
    view.results_table.selectRow(0)
    view._open_selected_stock_research()

    assert len(emitted) == 1
    context = emitted[0]
    assert context.stock_code == "2330"
    assert context.decision_date == "2026-09-05"
    assert context.data_date == "2026-09-04"
    assert context.result_id == "result-1"
    assert context.profile_id == "momentum"
    assert context.source_id == "provider-1"
    view.close()


class _WatchlistWithSource:
    def query_stock_names(self, codes):
        return {"2330": "台積電"}

    def get_stocks(self):
        return [
            {
                "stock_code": "2330",
                "stock_name": "台積電",
                "source_id": "result-1",
            }
        ]


def test_watchlist_drilldown_reads_saved_metadata_and_keeps_source_id(tmp_path: Path) -> None:
    runs = tmp_path / "recommendation" / "runs"
    runs.mkdir(parents=True)
    artifact = runs / "result-1.json"
    artifact.write_text(
        json.dumps(
            {
                "result_id": "result-1",
                "result_name": "策略甲",
                "config": {"profile_id": "momentum", "profile_version": "2.1"},
                "run_context": {
                    "as_of_date": "2026-09-05",
                    "data_date": "2026-09-04",
                    "profile_id": "momentum",
                    "profile_version": "2.1",
                    "source_id": "provider-1",
                },
                "recommendations": [],
            }
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(runs / "recommendation_runs.db") as conn:
        conn.execute("CREATE TABLE runs (result_id TEXT, data_path TEXT, created_at TEXT)")
        conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?)",
            ("result-1", str(artifact), "2026-09-05"),
        )

    app()
    view = WatchlistView(
        _WatchlistWithSource(), config=SimpleNamespace(output_root=tmp_path)
    )
    emitted = []
    view.stockResearchRequested.connect(emitted.append)
    view.stocks_table.selectRow(0)
    view._open_stock_analysis()

    assert len(emitted) == 1
    context = emitted[0]
    assert context.stock_code == "2330"
    assert context.result_id == "result-1"
    assert context.source_id == "result-1"
    assert context.decision_date == "2026-09-05"
    assert context.data_date == "2026-09-04"
    assert context.profile_id == "momentum"
    view.close()


def test_main_routes_context_to_store_and_smart_money_without_recompute() -> None:
    window = MainWindow.__new__(MainWindow)
    window.research_session_store = ResearchSessionStore()
    window._select_main_workspace = lambda _workspace: None
    visited = []
    window.show_smart_money_flow_for_stock = visited.append

    window._open_stock_research_context(
        {
            "stock_code": "2330",
            "decision_date": "2026-09-05",
            "data_date": "2026-09-04",
            "result_id": "result-1",
            "source_workspace": "watchlist",
        }
    )

    assert visited == ["2330"]
    assert window.research_session_store.get_snapshot().stock_context.stock_code == "2330"


def test_research_console_defaults_to_chinese_conclusion_and_collapsed_diagnostics() -> None:
    app()
    console = ResearchConsoleDTO(
        overall_status="degraded",
        source_reference="fixture:projection",
        boundary=ResearchConsoleBoundaryDTO(),
        pipeline=(
            ResearchPipelineRowDTO(
                component_id="e2e",
                label="Development E2E Run",
                identity="run-1",
                status="degraded",
                blockers=("projection_stale",),
            ),
        ),
        blockers=("projection_stale",),
    )
    view = ResearchConsoleView(console=console, auto_refresh=False)

    assert "Rule 使用中" in view.conclusion_banner.text()
    assert "ML 未參與" in view.conclusion_banner.text()
    assert "已過期" in view.conclusion_banner.text()
    assert view.diagnostics_panel.isHidden()
    assert isinstance(view.diagnostics_toggle, QToolButton)
    view.diagnostics_toggle.click()
    assert not view.diagnostics_panel.isHidden()
    assert "formal_oos_allowed = False" in view.diagnostics_panel.text()
    view.close()
