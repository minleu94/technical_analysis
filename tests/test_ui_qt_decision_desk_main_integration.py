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
    RelativeStrengthLiquiditySummary,
    DecisionDeskRiskPromptSummary,
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
    instances: list["_RecordedDecisionDeskView"] = []

    def __init__(self, decision_desk_builder, as_of_date=None, navigate_to_smart_money_callback=None, parent=None):
        self.decision_desk_builder = decision_desk_builder
        self.as_of_date = as_of_date
        self.navigate_to_smart_money_callback = navigate_to_smart_money_callback
        super().__init__(parent=parent)
        _RecordedDecisionDeskView.instances.append(self)


class _RecordedWorkbenchView(_DummyView):
    def __init__(self, source_service=None, auto_refresh=True, parent=None, **kwargs):
        self.source_service = source_service
        self.auto_refresh = auto_refresh
        self.kwargs = kwargs
        super().__init__(parent=parent)


class _RecordedSmartMoneyFlowView(_DummyView):
    def __init__(self, *args, **kwargs):
        self.smart_money_semantic_service = kwargs.get("smart_money_semantic_service")
        super().__init__(*args, **kwargs)


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
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("relative_strength_liquidity_missing",)),
        watchlist_triggers=WatchlistTriggerSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("watchlist_triggers_missing",), trigger_count=0),
        portfolio_alerts=PortfolioAlertSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("portfolio_alerts_missing",), alert_count=0),
        risk_prompts=DecisionDeskRiskPromptSummary(as_of_date=sample_date, quality=DecisionDeskQuality.MISSING, warnings=("risk_prompts_missing",)),
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


class _TrackingWorkbenchSourceService:
    instances: list["_TrackingWorkbenchSourceService"] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        _TrackingWorkbenchSourceService.instances.append(self)

    def inspect(self, **kwargs):
        self.inspect_kwargs = kwargs
        return None


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
        "SmartMoneyFlowView": _RecordedSmartMoneyFlowView,
        "DecisionDeskView": _RecordedDecisionDeskView,
        "UnifiedDecisionWorkbenchView": _RecordedWorkbenchView,
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
    monkeypatch.setattr(main_module, "WorkbenchSourceService", _TrackingWorkbenchSourceService)


def _build_main_window(*, regime_service=None, portfolio_service=None, config=None):
    main_window = main_module.MainWindow.__new__(main_module.MainWindow)
    from PySide6.QtWidgets import QMainWindow

    QMainWindow.__init__(main_window)
    main_window.config = config or object()
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


def _get_nav_labels(main_window) -> list[str]:
    return [
        main_window.left_navigation.label_for_key(key)
        for key in main_window.left_navigation.item_keys()
    ]


def test_main_window_owns_one_decision_desk_as_market_overview_index_zero(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _RecordedDecisionDeskView.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window._setup_ui()

    assert "每日決策" not in _get_nav_labels(target_window)
    assert isinstance(target_window.decision_desk_view, _RecordedDecisionDeskView)
    assert (
        target_window.decision_desk_view.navigate_to_smart_money_callback
        == target_window.show_smart_money_flow_for_stock
    )
    assert len(_RecordedDecisionDeskView.instances) == 1
    assert target_window.market_tabs.tabText(0) == "市場總覽"
    assert target_window.market_tabs.widget(0) is target_window.decision_desk_view
    assert "decision_source_widget" not in target_window.workbench_view.kwargs
    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.provider is not None
    assert callable(getattr(builder.provider, "fetch_market_regime", None))


def test_market_exploration_lazy_loading_uses_widget_identity_after_overview_insert(
    monkeypatch,
):
    app()
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)
    target_window = _build_main_window(
        config=types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    )
    target_window._setup_ui()

    expected_tabs = (
        "市場總覽",
        "大盤指數",
        "強勢個股",
        "弱勢個股",
        "強勢產業",
        "弱勢產業",
        "主力流向",
    )
    assert tuple(
        target_window.market_tabs.tabText(index)
        for index in range(target_window.market_tabs.count())
    ) == expected_tabs

    for label in expected_tabs:
        index = expected_tabs.index(label)
        target_window._on_market_tab_changed(index)

    for label in ("強勢個股", "弱勢個股", "強勢產業", "弱勢產業", "主力流向"):
        widget = target_window.market_tabs.widget(expected_tabs.index(label))
        assert widget.load_data_if_needed_calls == 1


def test_main_window_adds_unified_decision_workbench_tab(monkeypatch, tmp_path):
    app()
    _TrackingWorkbenchSourceService.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)
    output_root = tmp_path / "output"
    replay_summary_path = (
        output_root
        / "evidence_pipeline"
        / "historical_replay_reference_fix_20260706"
        / "historical_replay_2026-01-06_2026-07-06_reference_fix.json"
    )
    replay_summary_path.parent.mkdir(parents=True)
    replay_summary_path.write_text("{}", encoding="utf-8")

    target_window = _build_main_window(config=types.SimpleNamespace(output_root=output_root))
    target_window._setup_ui()

    assert _get_nav_labels(target_window) == [
        "決策工作台",
        "市場探索",
        "推薦分析",
        "策略回測",
        "觀察清單",
        "持倉管理",
        "數據更新",
        "Runtime",
    ]
    assert target_window.left_navigation.current_key() == "workbench"
    workbench_tab = target_window.workspace_widgets["workbench"]
    assert isinstance(workbench_tab, _RecordedWorkbenchView)
    assert _TrackingWorkbenchSourceService.instances
    assert workbench_tab.source_service is _TrackingWorkbenchSourceService.instances[-1]
    assert workbench_tab.auto_refresh is True
    assert workbench_tab.kwargs["replay_summary_json"] == replay_summary_path
    assert callable(workbench_tab.kwargs["navigate_to_daily_decision_callback"])
    assert callable(workbench_tab.kwargs["navigate_to_market_explore_callback"])
    assert callable(workbench_tab.kwargs["navigate_to_evidence_review_callback"])
    assert callable(workbench_tab.kwargs["navigate_to_portfolio_callback"])

    workbench_tab.kwargs["navigate_to_daily_decision_callback"]()
    assert target_window.left_navigation.current_key() == "market_explore"
    assert target_window.market_tabs.currentIndex() == 0

    target_window.market_tabs.setCurrentIndex(3)
    workbench_tab.kwargs["navigate_to_market_explore_callback"]()
    assert target_window.left_navigation.current_key() == "market_explore"
    assert target_window.market_tabs.currentIndex() == 0

    workbench_tab.kwargs["navigate_to_evidence_review_callback"]()
    assert target_window.left_navigation.current_key() == "backtest"

    workbench_tab.kwargs["navigate_to_portfolio_callback"]()
    assert target_window.left_navigation.current_key() == "portfolio"


def test_main_window_composes_controlled_rehearsal_dashboard_from_explicit_read_only_report(
    monkeypatch, tmp_path
):
    app()
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)
    report_path = tmp_path / "rehearsal-report.json"
    report_path.write_text(
        """{
  "scenario": {"scenario_id": "controlled", "decision_date": "2026-07-13", "source_db_path": "C:/fixture/source.db", "working_copy_db_path": "C:/fixture/copy.db", "tier": "engineering_fixture", "production_actions_allowed": false},
  "coverage_metrics": [],
  "artifacts": [],
  "p0_source_shadow": {"items": [{"source_id": "institutional_flows", "blockers": ["source_not_ingested"]}]},
  "ml_shadow": {"status": "insufficient_sample"}
}""",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVIDENCE_REHEARSAL_REPORT", str(report_path))

    target_window = _build_main_window()
    target_window._setup_ui()

    rehearsal_dashboard = target_window.workbench_view.kwargs[
        "evidence_rehearsal_dashboard"
    ]
    assert rehearsal_dashboard.status == "blocked"
    assert "source_not_ingested" in rehearsal_dashboard.blockers
    assert "ml_shadow:insufficient_sample" in rehearsal_dashboard.blockers
    assert rehearsal_dashboard.write_intent is False


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


def test_sector_rotation_service_is_injected_into_decision_desk_builder(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.kwargs["sector_rotation_service"] is not None
    assert callable(getattr(builder.kwargs["sector_rotation_service"], "build_snapshot", None))


def test_main_window_degrades_workbench_decision_source_when_builder_fails(monkeypatch):
    app()
    _install_fake_dependencies(monkeypatch, _FailingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window._setup_ui()

    assert "每日決策" not in _get_nav_labels(target_window)
    widget = target_window.decision_desk_view
    assert isinstance(widget, QLabel)
    assert "初始化失敗" in widget.text()


def test_watchlist_trigger_service_is_injected_into_decision_desk_builder(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.kwargs["watchlist_trigger_service"] is not None
    assert callable(getattr(builder.kwargs["watchlist_trigger_service"], "build_snapshot", None))


class _FakePortfolioChipService:
    instances = []

    def __init__(self, config, broker_flow_service=None):
        self.config = config
        self.broker_flow_service = broker_flow_service
        _FakePortfolioChipService.instances.append(self)

    def get_stock_chip_summary(self, stock_code: str, period_days: int = 5):
        return {"risk_level": "neutral", "lots_available": True}


def test_portfolio_alert_service_receives_portfolio_chip_provider(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _FakePortfolioChipService.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)
    monkeypatch.setattr(main_module, "PortfolioChipService", _FakePortfolioChipService)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    assert _FakePortfolioChipService.instances
    portfolio_alert_service = _TrackingDecisionDeskBuilder.instances[-1].kwargs["portfolio_alert_service"]
    assert portfolio_alert_service is not None
    assert portfolio_alert_service.chip_summary_provider is _FakePortfolioChipService.instances[-1]


def test_relative_strength_liquidity_service_is_injected_into_decision_desk_builder(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert _TrackingDecisionDeskBuilder.instances
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.kwargs["relative_strength_liquidity_service"] is not None
    assert callable(getattr(builder.kwargs["relative_strength_liquidity_service"], "build_snapshot", None))


def test_smart_money_semantic_service_is_shared_by_market_and_decision_tabs(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    assert target_window.smart_money_flow.smart_money_semantic_service is not None
    builder = _TrackingDecisionDeskBuilder.instances[-1]
    assert builder.kwargs["smart_money_service"] is target_window.smart_money_flow.smart_money_semantic_service


def test_main_window_shares_one_market_frame_loader_across_decision_providers(monkeypatch):
    app()
    _TrackingDecisionDeskBuilder.instances = []
    _install_fake_dependencies(monkeypatch, _TrackingDecisionDeskBuilder)

    target_window = _build_main_window()
    target_window.config = types.SimpleNamespace(db_file="C:/tmp/not-used.db")
    target_window._setup_ui()

    builder = _TrackingDecisionDeskBuilder.instances[-1]
    loader = builder.kwargs["market_frame_loader"]
    assert loader is not None
    assert builder.kwargs["market_breadth_service"].provider.market_frame_loader is loader
    assert (
        builder.kwargs["relative_strength_liquidity_service"].provider.market_frame_loader
        is loader
    )
    assert builder.kwargs["smart_money_service"].price_provider.market_frame_loader is loader
