"""候選股下鑽使用畫面排序，且不依賴掃描榜 membership。"""
import os
import json
import sqlite3
from types import SimpleNamespace
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from ui_qt.views.watchlist_view import WatchlistView
from ui_qt.views.smart_money.smart_money_flow_view import SmartMoneyFlowView
from app_module.watchlist_analysis_service import WatchlistAnalysisService, WatchlistAnalysisDTO


class WatchlistStub:
    def query_stock_names(self, codes):
        return {"2330": "台積電", "1101": "台泥"}

    def get_stocks(self):
        return [
            {"stock_code": "2330", "stock_name": "台積電"},
            {"stock_code": "1101", "stock_name": "台泥"},
        ]


def test_sorted_watchlist_opens_selected_stock_and_empty_selection_does_not_emit():
    app = QApplication.instance() or QApplication([])
    view = WatchlistView(WatchlistStub())
    emitted = []
    view.stockAnalysisRequested.connect(emitted.append)
    view.stocks_model.sort(0, Qt.AscendingOrder)
    view.stocks_table.selectRow(0)
    view.stock_analysis_btn.click()
    assert emitted == ["1101"]
    view.stocks_table.clearSelection()
    view.stock_analysis_btn.click()
    assert emitted == ["1101"]
    view.close()


def test_unranked_stock_loads_detail_through_service(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []

    class FlowStub:
        def load_stock_branch_detail(self, code, period, as_of):
            calls.append((code, period, as_of))

    view = SmartMoneyFlowView(FlowStub())
    view._data_loaded = True
    view._dashboard_as_of_date = date(2026, 9, 4)
    view._apply_scanner_signals([])
    monkeypatch.setattr(view, "_start_request", lambda kind, task, callback: task())
    view.select_stock("2330")
    assert calls[0][0] == "2330"
    assert calls[0][2] == date(2026, 9, 4)
    assert "2330" in view.sub_card_title.text()
    assert "未列入" in view.sub_card_stats.text()
    view.close()


def test_saved_analysis_reads_exact_source_and_rejects_future_without_writing(tmp_path):
    runs = tmp_path / "recommendation" / "runs"
    runs.mkdir(parents=True)
    payload = {"result_id": "saved-1", "result_name": "策略甲", "config": {},
               "run_context": {"as_of_date": "2026-09-04"},
               "recommendations": [{"stock_code": "2330", "stock_name": "台積電",
                                    "recommendation_reasons": "均線向上", "total_score": 75}]}
    artifact = runs / "saved-1.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    database = runs / "recommendation_runs.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE runs (result_id TEXT, data_path TEXT, created_at TEXT)")
        conn.execute("INSERT INTO runs VALUES (?, ?, ?)", ("saved-1", str(artifact), "2026-09-04"))
    before = {p.name: p.read_bytes() for p in runs.iterdir()}
    service = WatchlistAnalysisService(SimpleNamespace(output_root=tmp_path))
    result = service.fetch("2330", "saved-1", date(2026, 9, 6))
    assert result.status == "saved"
    assert result.reasons == "均線向上"
    assert result.analysis_date == "2026-09-04"
    assert service.fetch("2330", "saved-1", date(2026, 9, 3)).status == "unavailable"
    assert service.fetch("1101", "saved-1", date(2026, 9, 6)).status == "not_in_result"
    assert {p.name: p.read_bytes() for p in runs.iterdir()} == before

    app = QApplication.instance() or QApplication([])
    view = WatchlistView(WatchlistStub())
    view.analysis_service = service
    view.stocks_table.selectRow(0)
    for _ in range(100):
        app.processEvents()
        if "均線向上" in view.analysis_text.toPlainText():
            break
        QTest.qWait(10)
    assert "均線向上" in view.analysis_text.toPlainText()
    assert "2026-09-04" in view.analysis_text.toPlainText()
    view.close()


def test_stale_analysis_callback_cannot_replace_current_stock():
    app = QApplication.instance() or QApplication([])
    view = WatchlistView(WatchlistStub())
    view._analysis_request_id = 2
    view.analysis_text.setPlainText("1101")
    view._show_selected_analysis(1, WatchlistAnalysisDTO("2330", "missing"))
    assert view.analysis_text.toPlainText() == "1101"
    view._show_selected_analysis(2, WatchlistAnalysisDTO("1101", "saved", "2026-09-04", "run", "75", "30", "均線向上"))
    assert "均線向上" in view.analysis_text.toPlainText()
    assert "2026-09-04" in view.analysis_text.toPlainText()
    view.close()


def test_saved_list_preview_does_not_modify_candidate_pool(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])

    class UniverseStub:
        def list_watchlists(self):
            return [{"name": "成長觀察", "count": 1, "watchlist_id": "growth"}]

        def load_watchlist(self, identifier):
            assert identifier == "growth"
            return SimpleNamespace(codes=["2330"])

    monkeypatch.setattr("ui_qt.views.watchlist_view.UniverseService", lambda config: UniverseStub())
    view = WatchlistView(WatchlistStub(), config=SimpleNamespace(output_root=tmp_path))
    emitted = []
    view.stockAnalysisRequested.connect(emitted.append)
    view.universe_list.setCurrentRow(0)
    assert view.universe_stock_list.count() == 1
    assert "台積電" in view.universe_stock_list.item(0).text()
    view.universe_stock_list.itemDoubleClicked.emit(view.universe_stock_list.item(0))
    assert emitted == ["2330"]
    assert view.stocks_model.rowCount() == 2
    view.close()


def test_initial_dashboard_completion_retains_requested_unranked_stock(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []
    service = SimpleNamespace(load_stock_branch_detail=lambda code, period, cutoff: calls.append((code, cutoff)))
    view = SmartMoneyFlowView(service)
    monkeypatch.setattr(view, "load_data_if_needed", lambda: None)
    monkeypatch.setattr(view, "_start_request", lambda kind, task, callback: task())
    monkeypatch.setattr(view, "_on_branch_changed", lambda: None)
    monkeypatch.setattr(view.summary_strip, "update_summary", lambda summary: None)
    view.select_stock("2330")
    view._apply_dashboard_snapshot(SimpleNamespace(
        as_of_date=date(2026, 9, 4), top_signals=[], bottom_signals=[],
        summary=None, semantics_by_code={}, tracked_branches=[], quality="observed",
    ))
    assert calls[-1] == ("2330", date(2026, 9, 4))
    assert view.sub_card_title.text() == "2330"
    view.close()
