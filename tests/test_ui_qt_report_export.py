import os
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
import pytest
import pandas as pd

from app_module.dtos import ValidationStatus
from app_module.report_export_dtos import ReportMetadata
from app_module.report_export_service import ReportExportService

class SynchronousTaskWorker:
    def __init__(self, task_function, *args, **kwargs):
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs
        
        class DummySignal:
            def __init__(self, name):
                self.name = name
                self.slots = []
            def connect(self, slot):
                self.slots.append(slot)
            def emit(self, *args):
                for slot in self.slots:
                    slot(*args)
        
        self.started = DummySignal("started")
        self.finished = DummySignal("finished")
        self.error = DummySignal("error")
        self.progress = DummySignal("progress")
        self.cancelled = DummySignal("cancelled")

    def start(self):
        print(f"\n[TEST SynchronousTaskWorker] start called with function {self.task_function}")
        try:
            self.started.emit()
            result = self.task_function(*self.args, **self.kwargs)
            print("[TEST SynchronousTaskWorker] finished successfully")
            self.finished.emit(result)
        except Exception as e:
            print(f"[TEST SynchronousTaskWorker] failed with exception: {e}")
            self.error.emit(str(e))
            print("[TEST SynchronousTaskWorker] error signal emitted")

    def isRunning(self):
        return False

    def disconnect(self):
        pass

    def wait(self):
        pass

def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance

class FakeBacktestReport:
    def __init__(self):
        self.total_return = Decimal("0.12")
        self.annualized_return = Decimal("0.08")
        self.annual_return = Decimal("0.08")
        self.expectancy = Decimal("0.02")
        self.max_drawdown = Decimal("-0.05")
        self.total_trades = 15
        self.win_rate = Decimal("0.6")
        self.sharpe_ratio = Decimal("1.5")
        self.sortino_ratio = Decimal("1.8")
        self.validation_status = ValidationStatus.PASS
        self.validation_messages = ["SOP passed"]
        self.baseline_comparison = None
        self.overfitting_risk = None
        self.details = {
            "data_version": "sha256:abc",
            "strategy_version": "baseline_score@1.0",
            "regime": "Trend",
            "benchmark": "TAIEX",
            "execution_price": "next_open",
            "trade_list": pd.DataFrame([{"交易日期": "2026-06-01", "價格": 100}]),
            "equity_curve": pd.DataFrame([{"日期": "2026-06-01", "equity": 100000}]),
        }

class FakeBatchResult:
    def __init__(self):
        self.leaderboard = pd.DataFrame([{"排名": 1, "證券代號": "2330", "總報酬率": 0.25, "狀態": "SUCCESS"}])
        self.overall_stats = "總計測試 1 檔股票，1 檔成功"
        self.details = {
            "data_version": "sha256:abc",
            "strategy_version": "baseline_score@1.0",
            "regime": "Trend",
            "benchmark": "TAIEX",
            "execution_price": "next_open",
        }

class FakeRecommendationPortfolioResult:
    def __init__(self):
        self.summary = {"total_return": 0.15, "max_drawdown": -0.04}
        self.trades = pd.DataFrame([{"交易日期": "2026-06-01"}])
        self.equity_curve = pd.DataFrame([{"日期": "2026-06-01", "equity": 1000000}])
        self.diagnostics = ["Diag 1"]
        self.improvement_hints = ["Hint 1"]
        self.details = {
            "data_version": "sha256:abc",
            "strategy_version": "baseline_score@1.0",
            "regime": "Trend",
            "benchmark": "TAIEX",
            "execution_price": "next_open",
        }
    def period_holdings_dataframe(self):
        return pd.DataFrame([{"日期": "2026-06-01"}])
    def stock_contribution_dataframe(self):
        return pd.DataFrame([{"證券代號": "2330"}])

class FakeRecommendationDTO:
    def __init__(self, code, name, score, reason):
        self.stock_code = code
        self.stock_name = name
        self.score = score
        self.reason = reason
    def to_dict(self):
        return {
            "證券代號": self.stock_code,
            "證券名稱": self.stock_name,
            "評分": self.score,
            "推薦理由": self.reason
        }

@pytest.fixture
def init_app():
    return app()

@pytest.fixture
def backtest_view(init_app):
    from ui_qt.views.backtest_view import BacktestView
    # 建立一個測試用的 BacktestView，不傳入服務，手動 mock 掉需要的屬性
    from unittest.mock import MagicMock
    view = BacktestView(MagicMock(), None, MagicMock(), MagicMock(), None)
    view.report_export_service = ReportExportService()
    return view

@pytest.fixture
def recommendation_view(init_app):
    from ui_qt.views.recommendation_view import RecommendationView
    from unittest.mock import MagicMock
    view = RecommendationView(MagicMock(), MagicMock(), parent=None)
    view.report_export_service = ReportExportService()
    return view

def test_backtest_export_button_enabled_only_with_current_report(backtest_view):
    assert not backtest_view.export_report_btn.isEnabled()
    report = FakeBacktestReport()
    backtest_view._on_backtest_finished(report)
    assert backtest_view.export_report_btn.isEnabled()

def test_batch_export_uses_raw_batch_result_not_formatted_table(backtest_view):
    batch_result = FakeBatchResult()
    backtest_view.current_batch_result = batch_result
    # 提供預設的 current_run_params
    backtest_view.current_run_params = {"strategy_id": "test_strat"}
    payload = backtest_view._build_batch_export_payload()
    assert payload.overall_stats == batch_result.overall_stats
    pd.testing.assert_frame_equal(payload.leaderboard, batch_result.leaderboard)

def test_export_failure_restores_button_and_preserves_existing_file(backtest_view, tmp_path, monkeypatch):
    target = tmp_path / "existing.xlsx"
    target.write_bytes(b"existing")
    
    # Mock MessageBox 以防彈窗阻塞測試
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    
    # 注入我們的 SynchronousTaskWorker
    from ui_qt.workers import task_worker as tw_module
    monkeypatch.setattr(tw_module, "TaskWorker", SynchronousTaskWorker)
    
    # 模擬匯出出錯
    monkeypatch.setattr(
        backtest_view.report_export_service,
        "export_single_backtest",
        lambda target_path, payload: (_ for _ in ()).throw(OSError("locked")),
    )
    
    backtest_view.current_report = FakeBacktestReport()
    backtest_view.current_run_params = {"stock_code": "2330"}
    
    backtest_view._export_single_backtest_to_path(target)
    
    # 按鈕應保持啟用狀態
    assert backtest_view.export_report_btn.isEnabled()
    # 既有檔案不應被修改或刪除
    assert target.read_bytes() == b"existing"

def test_recommendation_export_hidden_without_results(recommendation_view):
    assert not recommendation_view.export_report_btn.isVisible()

def test_recommendation_export_uses_result_snapshot(recommendation_view):
    recs = [FakeRecommendationDTO("2330", "台積電", 90.0, "強勢突破")]
    recommendation_view.current_recommendations = recs
    recommendation_view.current_config = {"strategy_id": "rec_strat", "regime": "Trend"}
    payload = recommendation_view._build_current_recommendation_export_payload()
    assert payload.recommendations.shape[0] == len(recs)
    assert payload.metadata.strategy_id == "rec_strat"
