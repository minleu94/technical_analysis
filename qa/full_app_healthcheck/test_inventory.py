from __future__ import annotations

from pathlib import Path

# Test Inventory Registry mapping all currently tracked test-area Python files to their classifications.
# This registry serves as a guardrail to ensure that only allowed tests are bridged.

TEST_INVENTORY: dict[str, str] = {
    # healthcheck-runner-owned
    "tests/test_full_app_healthcheck_batch_closeout_baseline.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_coverage_matrix.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_manifest.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_reporting.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_runner.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_test_suite_bridge.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_test_inventory.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_actions.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_candidate_bridge_policy.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_command_advisor.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_feature_router.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_handoff_contract.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_known_issue_matcher.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_result_interpreter.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_service_oracle_metadata.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_coverage_burndown.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_flow_model.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_flow_diagnostics.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_ux_gap_mapping.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_offscreen_widget_checks.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_mainwindow_smoke_plan.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_viewport_resize_evidence_plan.py": "healthcheck-runner-owned",
    "tests/test_full_app_healthcheck_high_risk_dry_run_dialog_plan.py": "healthcheck-runner-owned",

    # ui-healthcheck-direct-bridge
    "tests/test_ui_qt_decision_desk_view.py": "ui-healthcheck-direct-bridge",
    "tests/test_ui_qt_market_regime_view.py": "ui-healthcheck-direct-bridge",
    "tests/test_ui_qt_research_workflow.py": "ui-healthcheck-direct-bridge",
    "tests/test_ui_qt_run_registry_compare.py": "ui-healthcheck-direct-bridge",
    "tests/test_ui_qt_smart_money_flow_view.py": "ui-healthcheck-direct-bridge",
    "tests/test_ui_qt_update_view_workbench.py": "ui-healthcheck-direct-bridge",

    # ui-healthcheck-candidate-bridge
    "tests/test_ui_qt_chart_payloads.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_chart_widget_factory.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_decision_desk_main_integration.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_portfolio_condition_monitor.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_portfolio_view.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_recommendation_next_steps_copy.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_recommendation_portfolio_results.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_recommendation_profiles.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_report_export.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_research_lab_mode_driven_ui.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_research_lab_workbench_copy.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_research_run_save.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_runtime_view.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_theme.py": "ui-healthcheck-candidate-bridge",
    "tests/test_ui_qt_watchlist_candidate_pool_copy.py": "ui-healthcheck-candidate-bridge",

    # service-oracle-data-market
    "tests/test_abnormal_fundamental_flags.py": "service-oracle-data-market",
    "tests/test_broker_branch_decode.py": "service-oracle-data-market",
    "tests/test_broker_flow_units.py": "service-oracle-data-market",
    "tests/test_company_registry.py": "service-oracle-data-market",
    "tests/test_data_module.py": "service-oracle-data-market",
    "tests/test_db_manager_logging.py": "service-oracle-data-market",
    "tests/test_analysis/test_technical_analysis.py": "service-oracle-data-market",
    "tests/test_finmind_monthly_revenue_create_time.py": "service-oracle-data-market",
    "tests/test_fundamental_availability.py": "service-oracle-data-market",
    "tests/test_fundamental_availability_entrypoint.py": "service-oracle-data-market",
    "tests/test_fundamental_availability_sources.py": "service-oracle-data-market",
    "tests/test_fundamental_data.py": "service-oracle-data-market",
    "tests/test_fundamental_diagnostics_service.py": "service-oracle-data-market",
    "tests/test_fundamental_factor_adapters.py": "service-oracle-data-market",
    "tests/test_fundamental_factor_service.py": "service-oracle-data-market",
    "tests/test_fundamental_schema.py": "service-oracle-data-market",
    "tests/test_fundamental_sqlite_provider.py": "service-oracle-data-market",
    "tests/test_fundamental_statement_availability_entrypoint.py": "service-oracle-data-market",
    "tests/test_fundamental_statement_availability_sources.py": "service-oracle-data-market",
    "tests/test_fundamental_statement_data.py": "service-oracle-data-market",
    "tests/test_market_breadth_service.py": "service-oracle-data-market",
    "tests/test_monthly_revenue_availability_builder.py": "service-oracle-data-market",
    "tests/test_monthly_revenue_availability_history.py": "service-oracle-data-market",
    "tests/test_relative_strength_liquidity_service.py": "service-oracle-data-market",
    "tests/test_revenue_factor_pack.py": "service-oracle-data-market",
    "tests/test_sector_rotation_service.py": "service-oracle-data-market",
    "tests/test_sqlite_inspector_service.py": "service-oracle-data-market",
    "tests/test_sqlite_storage_compatibility.py": "service-oracle-data-market",
    "tests/test_statement_factor_pack.py": "service-oracle-data-market",
    "tests/test_tpex_background_refresh_script.py": "service-oracle-data-market",
    "tests/test_tpex_daily_price_history_plan.py": "service-oracle-data-market",
    "tests/test_tpex_daily_price_history_plan_cli.py": "service-oracle-data-market",
    "tests/test_update_service_status.py": "service-oracle-data-market",
    "tests/test_valuation_data.py": "service-oracle-data-market",
    "tests/test_valuation_factor_adapters.py": "service-oracle-data-market",
    "tests/test_valuation_policy.py": "service-oracle-data-market",
    "tests/test_valuation_source_policy.py": "service-oracle-data-market",

    # service-oracle-research-backtest
    "tests/test_backtest/test_overfitting_risk.py": "service-oracle-research-backtest",
    "tests/test_backtest/test_parallel_safety.py": "service-oracle-research-backtest",
    "tests/test_backtest_diagnostics_and_date_adjustment.py": "service-oracle-research-backtest",
    "tests/test_backtest_factor_metadata.py": "service-oracle-research-backtest",
    "tests/test_backtest_timeline_contract.py": "service-oracle-research-backtest",
    "tests/test_batch_backtest_research_run_save.py": "service-oracle-research-backtest",
    "tests/test_factor_adapters.py": "service-oracle-research-backtest",
    "tests/test_factor_contract.py": "service-oracle-research-backtest",
    "tests/test_factor_gate.py": "service-oracle-research-backtest",
    "tests/test_factor_registry.py": "service-oracle-research-backtest",
    "tests/test_factor_service_research_run.py": "service-oracle-research-backtest",
    "tests/test_pattern_analysis/test_flag_pattern_robustness.py": "service-oracle-research-backtest",
    "tests/test_optimizer_service.py": "service-oracle-research-backtest",
    "tests/test_promotion_reconciliation.py": "service-oracle-research-backtest",
    "tests/test_recommendation_portfolio_backtest.py": "service-oracle-research-backtest",
    "tests/test_recommendation_portfolio_optimizer.py": "service-oracle-research-backtest",
    "tests/test_report_export_dtos.py": "service-oracle-research-backtest",
    "tests/test_report_export_service.py": "service-oracle-research-backtest",
    "tests/test_research_lab_mode_taxonomy.py": "service-oracle-research-backtest",
    "tests/test_research_result_presentation.py": "service-oracle-research-backtest",
    "tests/test_research_run_comparison_service.py": "service-oracle-research-backtest",
    "tests/test_research_run_legacy_adapter.py": "service-oracle-research-backtest",
    "tests/test_research_run_repository.py": "service-oracle-research-backtest",
    "tests/test_research_run_service.py": "service-oracle-research-backtest",
    "tests/test_score_threshold_policy.py": "service-oracle-research-backtest",
    "tests/test_strategy_lifecycle_repository.py": "service-oracle-research-backtest",
    "tests/test_strategy_lifecycle_service.py": "service-oracle-research-backtest",
    "tests/test_strategy_params_persistence_roundtrip.py": "service-oracle-research-backtest",
    "tests/test_strategy_threshold_modes.py": "service-oracle-research-backtest",
    "tests/test_walkforward_service.py": "service-oracle-research-backtest",
    "tests/test_weight_contract.py": "service-oracle-research-backtest",

    # service-oracle-recommendation
    "tests/test_recommendation_dto_roundtrip.py": "service-oracle-recommendation",
    "tests/test_recommendation_percentile_ranker.py": "service-oracle-recommendation",
    "tests/test_recommendation_portfolio_hints.py": "service-oracle-recommendation",
    "tests/test_recommendation_portfolio_numeric_governance.py": "service-oracle-recommendation",
    "tests/test_recommendation_portfolio_promotion_service.py": "service-oracle-recommendation",
    "tests/test_recommendation_portfolio_run_repository.py": "service-oracle-recommendation",
    "tests/test_recommendation_portfolio_view_charts.py": "service-oracle-recommendation",
    "tests/test_recommendation_profile_service.py": "service-oracle-recommendation",
    "tests/test_recommendation_ranking_service.py": "service-oracle-recommendation",

    # service-oracle-portfolio-decision-runtime
    "tests/test_decision_desk_dashboard_service.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_decision_desk_risk_prompt_service.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_decision_desk_service.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_decision_desk_ui_contract.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_alert_service.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_chip_monitor.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_condition_monitor.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_deepening.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_delete.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_feedback_service.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_jsonl_store_serialization.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_mvp.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_numeric_governance.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_review_service.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_portfolio_source_adapter.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_smart_money_semantic_service.py": "service-oracle-portfolio-decision-runtime",
    "tests/test_watchlist_trigger_service.py": "service-oracle-portfolio-decision-runtime",

    # governance-doc-tooling
    "tests/test_audit_document_encoding.py": "governance-doc-tooling",
    "tests/test_financial_float_boundary_checker.py": "governance-doc-tooling",
    "tests/test_financial_units.py": "governance-doc-tooling",
    "tests/test_governance_tools.py": "governance-doc-tooling",
    "tests/test_mcp_context_server.py": "governance-doc-tooling",
    "tests/test_performance_numeric_governance.py": "governance-doc-tooling",

    # write-risk-dry-run-required
    "tests/scripts/test_all_branches_one_day.py": "write-risk-dry-run-required",
    "tests/scripts/test_broker_branch_10days.py": "write-risk-dry-run-required",
    "tests/scripts/test_broker_branch_single.py": "write-risk-dry-run-required",
    "tests/scripts/test_moneydj_requests.py": "write-risk-dry-run-required",
    "tests/scripts/test_moneydj_requests_tables.py": "write-risk-dry-run-required",
    "tests/test_company_registry_cli.py": "write-risk-dry-run-required",
    "tests/test_finmind_monthly_revenue_create_time_cli.py": "write-risk-dry-run-required",
    "tests/test_fundamental_migration.py": "write-risk-dry-run-required",
    "tests/test_fundamental_migration_cli.py": "write-risk-dry-run-required",
    "tests/test_fundamental_statement_backfill.py": "write-risk-dry-run-required",
    "tests/test_fundamental_statement_backfill_cli.py": "write-risk-dry-run-required",
    "tests/test_inspect_fundamental_factors_cli.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_availability_builder_cli.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_availability_cli.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_availability_history_cli.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_backfill.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_backfill_cli.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_retroactive_baseline_cli.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_snapshot_harvester.py": "write-risk-dry-run-required",
    "tests/test_monthly_revenue_snapshot_harvester_cli.py": "write-risk-dry-run-required",
    "tests/test_statement_availability_cli.py": "write-risk-dry-run-required",
    "tests/test_statement_retroactive_baseline_cli.py": "write-risk-dry-run-required",
    "tests/test_tpex_daily_price_backfill.py": "write-risk-dry-run-required",
    "tests/test_tpex_daily_price_backfill_cli.py": "write-risk-dry-run-required",
    "tests/test_tpex_daily_price_source.py": "write-risk-dry-run-required",
    "tests/test_valuation_metrics_backfill.py": "write-risk-dry-run-required",
    "tests/test_valuation_metrics_backfill_cli.py": "write-risk-dry-run-required",
    "tests/test_valuation_source_policy_cli.py": "write-risk-dry-run-required",

    # slow-e2e-or-environment
    "tests/e2e/test_data_path_isolation.py": "slow-e2e-or-environment",

    # manual-only
    "tests/manual/legacy_advanced_patterns_check.py": "manual-only",
    "tests/manual/legacy_api_endpoints_check.py": "manual-only",
    "tests/manual/legacy_backtest_recommendation_check.py": "manual-only",
    "tests/manual/legacy_daily_data_check.py": "manual-only",
    "tests/manual/legacy_data_loading_check.py": "manual-only",
    "tests/manual/legacy_extended_patterns_check.py": "manual-only",
    "tests/manual/legacy_math_analyzer_check.py": "manual-only",
    "tests/manual/legacy_ml_analyzer_check.py": "manual-only",
    "tests/manual/legacy_optimized_patterns_check.py": "manual-only",
    "tests/manual/legacy_pattern_analyzer_check.py": "manual-only",
    "tests/manual/legacy_pattern_parameter_tuning_check.py": "manual-only",
    "tests/manual/legacy_recommendation_report_check.py": "manual-only",
    "tests/manual/legacy_signal_combiner_check.py": "manual-only",
    "tests/manual/legacy_technical_analyzer_check.py": "manual-only",
    "tests/manual/legacy_twse_api_check.py": "manual-only",
    "tests/manual/legacy_utils_check.py": "manual-only",

    # legacy-or-low-priority (moved candidates mapped to new locations)
    "tests/manual/legacy_diagnostics/run_market_index_test.py": "legacy-or-low-priority",
    "tests/manual/legacy_diagnostics/run_technical_calc_test.py": "legacy-or-low-priority",
    "tests/manual/legacy_diagnostics/run_tests.py": "legacy-or-low-priority",
    "tests/manual/legacy_diagnostics/check_columns.py": "legacy-or-low-priority",
    "tests/manual/legacy_diagnostics/check_processed_file.py": "legacy-or-low-priority",
    "tests/manual/legacy_diagnostics/check_saved_file.py": "legacy-or-low-priority",
    "tests/manual/legacy_diagnostics/check_signals_file.py": "legacy-or-low-priority",
    "tests/test_ml_analysis/__init__.py": "legacy-or-low-priority",
    "tests/test_pattern_analysis/__init__.py": "legacy-or-low-priority",

    # general-unit-keep-in-pytest
    "tests/conftest.py": "general-unit-keep-in-pytest",
    "tests/test_core/test_config.py": "general-unit-keep-in-pytest",
    "tests/test_core/test_data_loader.py": "general-unit-keep-in-pytest",
    "tests/test_indicator_parameter_registry.py": "general-unit-keep-in-pytest",
    "tests/test_m2_a_integration.py": "general-unit-keep-in-pytest",
}


PYTEST_SUPPORT_FILES = frozenset(["tests/conftest.py"])

PYTEST_COLLECTED_FILES = frozenset(
    path for path in TEST_INVENTORY
    if path.startswith("tests/")
    and not path.startswith("tests/manual/")
    and not path.startswith("tests/scripts/")
    and Path(path).name.startswith("test_")
    and path.endswith(".py")
)

PYTEST_NOT_COLLECTED_FILES = frozenset(
    path for path in TEST_INVENTORY
    if path not in PYTEST_SUPPORT_FILES and path not in PYTEST_COLLECTED_FILES
)

BRIDGE_REJECTED_CATEGORIES = frozenset([
    "healthcheck-runner-owned",
    "service-oracle-data-market",
    "service-oracle-research-backtest",
    "service-oracle-recommendation",
    "service-oracle-portfolio-decision-runtime",
    "governance-doc-tooling",
    "write-risk-dry-run-required",
    "slow-e2e-or-environment",
    "manual-only",
    "legacy-or-low-priority",
    "general-unit-keep-in-pytest",
])


def get_all_test_files() -> frozenset[str]:
    return frozenset(TEST_INVENTORY.keys())


def get_category(path: str) -> str | None:
    norm_path = path.replace("\\", "/")
    return TEST_INVENTORY.get(norm_path)


def is_allowed_in_bridge(path: str) -> bool:
    category = get_category(path)
    return category == "ui-healthcheck-direct-bridge"


def get_direct_bridge_files() -> frozenset[str]:
    return frozenset(path for path, cat in TEST_INVENTORY.items() if cat == "ui-healthcheck-direct-bridge")


def get_candidate_bridge_files() -> frozenset[str]:
    return frozenset(path for path, cat in TEST_INVENTORY.items() if cat == "ui-healthcheck-candidate-bridge")


def get_bridge_rejected_files() -> frozenset[str]:
    return frozenset(path for path, cat in TEST_INVENTORY.items() if cat in BRIDGE_REJECTED_CATEGORIES)


def is_collected_by_default_pytest(path: str) -> bool:
    return path in PYTEST_COLLECTED_FILES


def get_pytest_collection_status(path: str) -> str:
    if path not in TEST_INVENTORY:
        return "unknown"
    if path in PYTEST_COLLECTED_FILES:
        return "collected"
    if path in PYTEST_SUPPORT_FILES:
        return "support"
    return "not-collected"


def get_files_by_category(category: str) -> frozenset[str]:
    return frozenset(path for path, cat in TEST_INVENTORY.items() if cat == category)


def get_reject_reason(path: str) -> str | None:
    category = get_category(path)
    if category is None:
        return f"未登錄或未分類的測試檔案：{path}"

    if category == "ui-healthcheck-direct-bridge":
        return None

    reasons = {
        "healthcheck-runner-owned": "健康檢查框架自身的單元測試，不可由 runner 調用自身以防無窮迴圈。",
        "ui-healthcheck-candidate-bridge": "屬於候選橋接測試，第一版尚未完成安全防護，目前不允許橋接。",
        "service-oracle-data-market": "屬於數據與市場 Oracle，不應直接作為 UI Flow 步驟執行。",
        "service-oracle-research-backtest": "屬於研究與回測 Oracle，不屬 UI 導覽步驟。",
        "service-oracle-recommendation": "屬於推薦系統 Oracle，不屬 UI 導覽步驟。",
        "service-oracle-portfolio-decision-runtime": "屬於持倉、每日決策與 Runtime Oracle，不屬 UI 導覽步驟。",
        "governance-doc-tooling": "屬於輔助治理工具，非 UI 驗證主流程。",
        "write-risk-dry-run-required": "此測試包含資料寫入風險，預設禁止由非破壞式 runner 執行。",
        "slow-e2e-or-environment": "屬於慢速 E2E 或特定環境測試，禁止於 quick/full bridge 執行。",
        "manual-only": "屬於歷史探索或人工驗證腳本，禁止由自動化 runner 執行。",
        "legacy-or-low-priority": "屬於遺留或低優先級診斷腳本，禁止執行。",
        "general-unit-keep-in-pytest": "屬於通用單元測試，應保留在一般 pytest 流程中獨立執行。",
    }

    return reasons.get(category, f"此分類 ({category}) 禁止執行於 runner bridge。")
