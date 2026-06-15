import os
import sys
import types
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel
from app_module.decision_desk_dtos import (
    DecisionDeskQuality,
    DecisionDeskSnapshot,
    MarketBreadthSummary,
    MarketRegimeSummary,
    PortfolioAlertSummary,
    SectorRotationSummary,
    WatchlistTriggerSummary,
)

import ui_qt.main as main_module
from PySide6.QtWidgets import QWidget


class _DummySignal:
    def __init__(self):
        self.calls = []

    def connect(self, slot):
        self.calls.append(slot)


class _DummyView(QWidget):
    def __init__(self, *args, **kwargs):
        parent = kwargs.get("parent")
        super().__init__(parent)
        self.load_data_if_needed_calls = 0

    def load_data_if_needed(self):
        self.load_data_if_needed_calls += 1


class _DummyRecommendationView(_DummyView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sendToBacktestRequested = _DummySignal()


class _RecordedDecisionDeskView(_DummyView):
    def __init__(self, decision_desk_builder, as_of_date=None, parent=None):
        self.decision_desk_builder = decision_desk_builder
        self.as_of_date = as_of_date
        super().__init__(parent=parent)


def _snapshot() -> DecisionDeskSnapshot:
    sample_date = date(2026, 6, 15)
    return DecisionDeskSnapshot(
        as_of_date=sample_date,
        generated_at=None,
        schema_version=1,
        overall_quality=DecisionDeskQuality.MISSING,
        market_regime=MarketRegimeSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("market_regime_missing",)),
        market_breadth=MarketBreadthSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("market_breadth_missing",)),
        sector_rotation=SectorRotationSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("sector_rotation_missing",)),
        watchlist_triggers=WatchlistTriggerSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("watchlist_triggers_missing",), trigger_count=0),
        portfolio_alerts=PortfolioAlertSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("portfolio_alerts_missing",), alert_count=0),
        warnings=(),
    )


class _TrackingDecisionDeskBuilder:
    instances: list["_TrackingDecisionDeskBuilder"] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.provider = kwargs.get("provider")
        _TrackingDecisionDeskBuilder.instances.append(self)

    def build_snapshot(self, as_of_date):
        _snapshot()
        return _snapshot()


class _FailingDecisionDeskBuilder:
    def __init__(self):
        raise RuntimeError("Decision desk service unavailable")


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


class _RuntimeController:
    def __init__(self, _):
        self.event_bus = object()

    def poll_updates(self):
        pass


class _RuntimeBridge:
    def __init__(self, *_args, **_kwargs):
        self.state_updated = _DummySignal()
        self.health_updated = _DummySignal()
        self.event_received = _DummySignal()


class _RuntimeView(QWidget):
    def on_state_updated(self, *args, **kwargs):
        pass

    def on_health_updated(self, *args, **kwargs):
        pass

    def on_event_received(self, *args, **kwargs):
        pass


class _SessionContextStrip(QWidget):
    def __init__(self, *args, **kwargs):
        parent = kwargs.pop("parent", None)
        if parent is None and len(args) >= 2:
            parent = args[1]
        super().__init__(parent)


class _DummyUpdateView(_DummyView):
    pass


def _install_fake_dependencies(monkeypatch, decision_desk_builder_cls):
    fake_tabs = {
        "UpdateView": _DummyUpdateView,
        "MarketRegimeView": _DummyView,
        "StrongStocksView": _DummyView,
        "WeakStocksView": _DummyView,
        "StrongIndustriesView": _DummyView,
        "WeakIndustriesView": _DummyView,
        "RecommendationView": _DummyRecommendationView,
        "BacktestView": _DummyView,
        "WatchlistView": _DummyView,
        "SmartMoneyFlowView": _DummyView,
        "DecisionDeskView": _RecordedDecisionDeskView,
        "SessionContextStrip": _SessionContextStrip,
        "RuntimeController": _RuntimeController,
        "QtRuntimeBridge": _RuntimeBridge,
        "RuntimeView": _RuntimeView,
    }
    for name, value in fake_tabs.items():
        monkeypatch.setattr(main_module, name, value)
    fake_portfolio_module = types.ModuleType("ui_qt.views.portfolio_view")
    fake_portfolio_module.PortfolioView = _DummyView
    monkeypatch.setitem(sys.modules, "ui_qt.views.portfolio_view", fake_portfolio_module)
    monkeypatch.setattr(main_module, "DecisionDeskSnapshotBuilder", decision_desk_builder_cls)


def _build_main_window(*, regime_service=None, portfolio_service=None):
    main_window = main_module.MainWindow.__new__(main_module.MainWindow)
    from PySide6.QtWidgets import QMainWindow

    QMainWindow.__init__(main_window)
    main_window.config = object()
    main_window.screening_service = object()
    main_window.regime_service = regime_service or object()
    main_window.recommendation_service = object()
    main_window.update_service = object()
    main_window.backtest_service = object()
    main_window.broker_flow_service = object()
    main_window.watchlist_service = object()
    main_window.universe_service = object()
    main_window.research_session_store = object()
    main_window.portfolio_service = portfolio_service or object()
    main_window.journal_service = object()
    main_window.broker_flow_service = object()
    return main_window


def _get_tab_names(main_window) -> list[str]:
    return [main_window.tabs.tabText(i) for i in range(main_window.tabs.count())]


def test_main_window_adds_daily_decision_tab(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window._setup_ui()

    assert "每日決策" in _get_tab_names(target_window)
    decision_idx = _get_tab_names(target_window).index("每日決策")
    assert isinstance(target_window.tabs.widget(decision_idx), _RecordedDecisionDeskView)
    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.provider is not None
    assert callable(getattr(builder.provider, "fetch_market_regime", None))


class _FakeRegimeService:
    def __init__(self):
        self.calls: list[str] = []

    def detect_regime(self, date: str = None):
        self.calls.append(date)
        class _Dto:
            pass
        dto = _Dto()
        dto.confidence = 0.77
        dto.details = {"ma20_slope": 1.2}
        dto.regime_name_cn = "趨勢循環"
        dto.regime = "Trend"
        return dto


def test_market_regime_provider_is_injected_and_callable(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    fake_regime_service = _FakeRegimeService()
    target_window = _build_main_window(regime_service=fake_regime_service)
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    provider = _TrackingDecisionDeskBuilder.instances[-1].provider
    summary = provider.fetch_market_regime(date(2026, 6, 15))

    assert fake_regime_service.calls == ["2026-06-15"]
    assert summary.regime_label == "趨勢循環"
    assert summary.regime_confidence == 7700
    assert summary.regime_score == 120


def test_market_breadth_service_is_injected_into_decision_desk_builder(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.kwargs["market_breadth_service"] is not None
    assert callable(getattr(builder.kwargs["market_breadth_service"], "build_snapshot", None))


def test_main_window_degrades_daily_decision_tab_when_builder_fails(monkeypatch):
    app()
    _install_fake_dependencies(monkeypatch, _FailingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window._setup_ui()

    assert "每日決策" in _get_tab_names(target_window)
    decision_idx = _get_tab_names(target_window).index("每日決策")
    widget = target_window.tabs.widget(decision_idx)
    assert isinstance(widget, QLabel)
    assert "初始化失敗" in widget.text()
