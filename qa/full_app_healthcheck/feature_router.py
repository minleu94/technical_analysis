from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureRoute:
    feature_id: str
    display_name: str
    direct_bridge_suite_ids: tuple[str, ...]
    candidate_test_paths: tuple[str, ...]
    service_oracle_test_paths: tuple[str, ...]
    quick_supported: bool
    full_supported: bool
    data_audit_policy: str  # 'never', 'conditional'
    data_audit_triggers: tuple[str, ...]
    known_gaps: tuple[str, ...]
    safety_notes: str



FEATURE_ROUTES: dict[str, FeatureRoute] = {
    "update_view": FeatureRoute(
        feature_id="update_view",
        display_name="UpdateView / 資料更新頁",
        direct_bridge_suite_ids=("ui-update-workbench", "qa-update-tab"),
        candidate_test_paths=(),
        service_oracle_test_paths=("tests/test_update_service_status.py",),
        quick_supported=True,
        full_supported=True,
        data_audit_policy="conditional",
        data_audit_triggers=("Compare SQLite schema with daily price CSV integration",),
        known_gaps=("TWSE/TPEX real API fetch progress bar indication", "Long task thread-safe cancellation", "Confirm dialog on SQLite daily prices sync"),
        safety_notes="Do not invoke actual backfill/migration write actions in quick mode.",
    ),
    "decision_desk": FeatureRoute(
        feature_id="decision_desk",
        display_name="Daily Decision Desk / 每日決策",
        direct_bridge_suite_ids=("ui-decision-desk",),
        candidate_test_paths=("tests/test_ui_qt_decision_desk_main_integration.py",),
        service_oracle_test_paths=(
            "tests/test_decision_desk_dashboard_service.py",
            "tests/test_decision_desk_risk_prompt_service.py",
            "tests/test_decision_desk_service.py",
            "tests/test_decision_desk_ui_contract.py",
        ),
        quick_supported=True,
        full_supported=True,
        data_audit_policy="conditional",
        data_audit_triggers=("Verify watchlist risk or portfolio alerts source integrity",),
        known_gaps=("Visual layout of warning flags under degraded data status", "Clicking Why Not button popup readability"),
        safety_notes="Safe to run in quick mode; no data write side effects.",
    ),
    "research_lab": FeatureRoute(
        feature_id="research_lab",
        display_name="Research Lab / 策略回測",
        direct_bridge_suite_ids=("ui-research-workflow", "ui-run-registry-compare"),
        candidate_test_paths=(
            "tests/test_ui_qt_research_lab_mode_driven_ui.py",
            "tests/test_ui_qt_research_lab_workbench_copy.py",
            "tests/test_ui_qt_research_run_save.py",
        ),
        service_oracle_test_paths=(
            "tests/test_research_lab_mode_taxonomy.py",
            "tests/test_research_result_presentation.py",
            "tests/test_research_run_repository.py",
            "tests/test_research_run_service.py",
        ),
        quick_supported=False,
        full_supported=True,
        data_audit_policy="conditional",
        data_audit_triggers=("Check historical prices look-ahead bias and registry integrity",),
        known_gaps=("Replay execution progress bar thread exit", "Custom parameter slider UI layout resize check", "Equity curve zoom interaction"),
        safety_notes="Contains heavy calculations; not allowed in quick mode.",
    ),
    "market_regime": FeatureRoute(
        feature_id="market_regime",
        display_name="Market Regime / 市場觀察",
        direct_bridge_suite_ids=("ui-market-regime-view",),
        candidate_test_paths=(),
        service_oracle_test_paths=("tests/test_walkforward_service.py",),
        quick_supported=False,
        full_supported=True,
        data_audit_policy="conditional",
        data_audit_triggers=("Verify market index CSV and moving averages consistency",),
        known_gaps=("Regime rule match tooltip verification", "Regime breakdown dropdown geometry details"),
        safety_notes="Requires large daily indicators calculations; not allowed in quick mode.",
    ),
    "smart_money": FeatureRoute(
        feature_id="smart_money",
        display_name="Smart Money Flow / 主力流向",
        direct_bridge_suite_ids=("ui-smart-money-flow",),
        candidate_test_paths=(),
        service_oracle_test_paths=(
            "tests/test_smart_money_semantic_service.py",
            "tests/test_broker_branch_decode.py",
            "tests/test_broker_flow_units.py",
        ),
        quick_supported=False,
        full_supported=True,
        data_audit_policy="conditional",
        data_audit_triggers=("Verify broker branch registry CSV and broker_flows SQLite integrity",),
        known_gaps=("Drill-down connection to portfolio/stock highlight", "Multi-day broker flow sorting"),
        safety_notes="Involves broker_flow_dir / SQLite broker_flows / broker branch registry which may have large I/O; not allowed in quick mode.",
    ),
    "registry_compare": FeatureRoute(
        feature_id="registry_compare",
        display_name="Run Registry Compare / 策略比較",
        direct_bridge_suite_ids=("ui-run-registry-compare",),
        candidate_test_paths=(),
        service_oracle_test_paths=("tests/test_research_run_comparison_service.py",),
        quick_supported=False,
        full_supported=True,
        data_audit_policy="never",
        data_audit_triggers=(),
        known_gaps=("Cross-run parameters horizontal table alignment", "Normalized equity curve canvas rendering"),
        safety_notes="Requires comparison of multiple research runs; not allowed in quick mode.",
    ),
}


def query_feature(keyword: str) -> FeatureRoute | None:
    """用功能名稱或關鍵字進行精確或模糊映射，回傳 FeatureRoute 元資料。"""
    keyword_clean = keyword.strip().lower()
    if not keyword_clean:
        return None

    # 1. Exact match on ID or display name
    for fid, route in FEATURE_ROUTES.items():
        if keyword_clean == fid or keyword_clean == route.display_name.lower():
            return route

    # 2. Key mapping
    keyword_map = {
        # UpdateView
        "updateview": "update_view",
        "update_view": "update_view",
        "update": "update_view",
        "更新": "update_view",
        "資料更新": "update_view",
        "更新頁": "update_view",

        # Decision Desk
        "decision_desk": "decision_desk",
        "decision desk": "decision_desk",
        "decision": "decision_desk",
        "desk": "decision_desk",
        "每日決策": "decision_desk",
        "決策": "decision_desk",
        "決策桌": "decision_desk",

        # Research Lab
        "research_lab": "research_lab",
        "research lab": "research_lab",
        "research": "research_lab",
        "lab": "research_lab",
        "回測": "research_lab",
        "最佳化": "research_lab",
        "策略實驗室": "research_lab",

        # Market Regime
        "market_regime": "market_regime",
        "market regime": "market_regime",
        "regime": "market_regime",
        "市場觀察": "market_regime",
        "市場": "market_regime",
        "觀察": "market_regime",
        "大盤": "market_regime",
        "大盤指數": "market_regime",
        "規則匹配度": "market_regime",

        # Smart Money
        "smart_money": "smart_money",
        "smart money": "smart_money",
        "smart": "smart_money",
        "money": "smart_money",
        "主力流向": "smart_money",
        "主力": "smart_money",
        "分點": "smart_money",
        "籌碼": "smart_money",

        # Registry Compare
        "registry_compare": "registry_compare",
        "registry compare": "registry_compare",
        "compare": "registry_compare",
        "比較": "registry_compare",
        "策略比較": "registry_compare",
        "跨回測比較": "registry_compare",
    }

    # Match in mapping
    mapped_id = keyword_map.get(keyword_clean)
    if mapped_id:
        return FEATURE_ROUTES[mapped_id]

    # Partial substring match on ID or display name
    for fid, route in FEATURE_ROUTES.items():
        if keyword_clean in fid or keyword_clean in route.display_name.lower():
            return route

    return None
