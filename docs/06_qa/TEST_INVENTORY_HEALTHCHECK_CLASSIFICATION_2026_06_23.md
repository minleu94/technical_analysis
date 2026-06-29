# Test Inventory / Healthcheck Classification 2026-06-23

> 目的：盤點 `tests/` 底下所有有效 Python 測試檔，分類哪些可以被非破壞式 Full App Healthcheck Runner 呼叫、哪些只能作 service/oracle 證據、哪些必須保留在一般 pytest 或人工檢查流程。

## 結論

目前有效測試區 Python 檔共 208 個，不含 `__pycache__` 與 `.pytest_cache`。分類結果如下：

| 分類 | 數量 | Runner 使用方式 |
|---|---:|---|
| `healthcheck-runner-owned` | 28 | Runner 自身單元測試，不由 runner 呼叫。 |
| `ui-healthcheck-direct-bridge` | 11 | 可直接登錄到 `test_suite_bridge.py`，並可由 runner 依 `--tab` 分頁篩選。 |
| `ui-healthcheck-candidate-bridge` | 10 | 可逐步評估納入 full mode 或特定 flow diagnostics。 |
| `service-oracle-data-market` | 37 | 可作資料 / 市場狀態 oracle，不直接當 UI flow step。 |
| `service-oracle-research-backtest` | 31 | 可作 Research Lab / backtest / strategy oracle，需注意金融數值與 look-ahead 邊界。 |
| `service-oracle-recommendation` | 9 | 可作推薦分析與 profile lifecycle oracle。 |
| `service-oracle-portfolio-decision-runtime` | 17 | 可作持倉、每日決策、Runtime、Smart Money oracle。 |
| `governance-doc-tooling` | 6 | 可作 release gate 的輔助治理檢查，不屬 UI healthcheck 主流程。 |
| `write-risk-dry-run-required` | 28 | 不可由非破壞 runner 直接呼叫，除非測試明確 dry-run / tmp path / mock。 |
| `slow-e2e-or-environment` | 1 | 不放 quick mode，可考慮 full/nightly。 |
| `manual-only` | 16 | 不自動執行，只保留 coverage matrix 或人工操作參考。 |
| `legacy-or-low-priority` | 9 | 不被預設 pytest 收集或僅為 package marker / 舊診斷腳本，不納入第一版 runner。 |
| `general-unit-keep-in-pytest` | 5 | 一般單元測試 / fixture / smoke helper，保留一般 pytest。 |

## 使用狀態稽核

本節於 2026-06-23 重新以 `pytest --collect-only -q -o addopts=` 與 runner bridge registry 交叉檢查。

| 狀態 | 數量 | 判讀 |
|---|---:|---|
| 預設 pytest gate 會收集 | 177 files / 1051 tests | 仍屬現行自動化測試；沒有逐名出現在文件中也不代表 unused。 |
| 目前已由 healthcheck runner bridge 呼叫 | 11 files | direct bridge UI 測試；另有 `scripts/qa_validate_update_tab.py` 作為 QA script bridge，不屬 `tests/` 208 files。 |
| pytest support file | 1 | `tests/conftest.py` 不產生測項，但仍被 pytest fixture 系統使用。 |
| manual legacy 已隔離 | 16 | `tests/manual/` 底下歷史探索腳本，已在 legacy/manual 區，不進預設 pytest。 |
| manual script 已隔離 | 5 | `tests/scripts/` 底下真實來源 / 外部站台 / 人工整合檢查，不進預設 pytest，也不可進 runner quick/full。 |
| package marker，不視為測試 | 2 | `__init__.py` 空檔，不需由 runner 或 pytest 執行。 |
| legacy diagnostics relocated | 7 | 已移入 `tests/manual/legacy_diagnostics/`；不被 pytest 收集，且含固定真實路徑、外部 API、舊 import 或一次性診斷語意。 |

### legacy relocation candidates

這 7 個檔案不被 `pytest.ini` 收集，也不應被 healthcheck runner 呼叫。已移到 `tests/manual/legacy_diagnostics/`，並保留簡短原因：

- `tests/manual/legacy_diagnostics/run_market_index_test.py` - 依賴 yfinance / FinMind token，屬外部 API 診斷。
- `tests/manual/legacy_diagnostics/run_technical_calc_test.py` - 固定 `D:/Min/Python/Project/FA_Data`，會檢查 / 建立真實資料目錄並可能寫 `tech_test.log`。
- `tests/manual/legacy_diagnostics/run_tests.py` - 舊 unittest runner，引用不存在或過時的 `test_data_module`。
- `tests/manual/legacy_diagnostics/check_columns.py` - 固定讀取 `D:/.../technical_analysis/2330_indicators.csv` 的一次性欄位檢查。
- `tests/manual/legacy_diagnostics/check_processed_file.py` - 固定讀取 `D:/.../technical_analysis/2330_processed.csv` 的一次性欄位檢查。
- `tests/manual/legacy_diagnostics/check_saved_file.py` - 固定讀取 `D:/.../test_data/2330_processed.csv` 的一次性欄位檢查。
- `tests/manual/legacy_diagnostics/check_signals_file.py` - 固定讀取 `D:/.../test_data/2330_signals.csv` 的一次性欄位檢查。

### runner bridge current usage

目前 `qa/full_app_healthcheck/test_suite_bridge.py` 只應橋接下列 direct UI 測試：

- `tests/test_ui_qt_update_view_workbench.py`
- `tests/test_ui_qt_decision_desk_view.py`
- `tests/test_ui_qt_research_workflow.py`
- `tests/test_ui_qt_market_regime_view.py`
- `tests/test_ui_qt_run_registry_compare.py`
- `tests/test_ui_qt_smart_money_flow_view.py`
- `tests/test_ui_qt_recommendation_profiles.py`
- `tests/test_ui_qt_recommendation_next_steps_copy.py`
- `tests/test_ui_qt_watchlist_candidate_pool_copy.py`
- `tests/test_ui_qt_portfolio_view.py`
- `tests/test_ui_qt_runtime_view.py`

其中 quick mode 只能先跑 UpdateView 與 Daily Decision Desk；Research / Market Regime / Registry Compare / Smart Money / Recommendation / Watchlist / Portfolio / Runtime 保留 full mode，並由 `test_inventory.py` 的 direct bridge allowlist 防止其他類別誤入 runner。`scripts/run_full_app_healthcheck.py --mode full --tab <tab>` 可依 `update`、`research`、`recommendation`、`watchlist`、`portfolio`、`runtime` 等 tab 分批驗證，不必每次跑完整 full mode。

## Runner 規則

- `quick` 模式只允許 fast、明確非破壞、與 UI healthcheck 直接相關的測試。
- `full` 模式可加入更多 UI candidate bridge 與 service oracle，但不可直接跑正式資料寫入、回補、migration、harvester、外部站台大量請求。
- `high-risk-dry-run` 只驗證 dialog、cancel、dry-run、mock service 未被呼叫。
- `manual-only` 與 `write-risk-dry-run-required` 預設不得進 `test_suite_bridge.py`。
- `test_suite_bridge.py` 必須保存每個 suite 的 `covered_healthcheck_ids` 與 `covered_flow_ids`，避免重複寫同一行為測試。

## 分類清單

### healthcheck-runner-owned

- `tests/test_full_app_healthcheck_batch_closeout_baseline.py`
- `tests/test_full_app_healthcheck_coverage_matrix.py`
- `tests/test_full_app_healthcheck_manifest.py`
- `tests/test_full_app_healthcheck_reporting.py`
- `tests/test_full_app_healthcheck_runner.py`
- `tests/test_full_app_healthcheck_test_suite_bridge.py`
- `tests/test_full_app_healthcheck_test_inventory.py`
- `tests/test_full_app_healthcheck_actions.py`
- `tests/test_full_app_healthcheck_candidate_bridge_policy.py`
- `tests/test_full_app_healthcheck_command_advisor.py`
- `tests/test_full_app_healthcheck_feature_router.py`
- `tests/test_full_app_healthcheck_handoff_contract.py`
- `tests/test_full_app_healthcheck_known_issue_matcher.py`
- `tests/test_full_app_healthcheck_result_interpreter.py`
- `tests/test_full_app_healthcheck_service_oracle_metadata.py`
- `tests/test_full_app_healthcheck_coverage_burndown.py`
- `tests/test_full_app_healthcheck_flow_model.py`
- `tests/test_full_app_healthcheck_flow_diagnostics.py`
- `tests/test_full_app_healthcheck_ux_gap_mapping.py`
- `tests/test_full_app_healthcheck_offscreen_widget_checks.py`
- `tests/test_full_app_healthcheck_mainwindow_smoke_plan.py`
- `tests/test_full_app_healthcheck_viewport_resize_evidence_plan.py`
- `tests/test_full_app_healthcheck_high_risk_dry_run_dialog_plan.py`
- `tests/test_full_app_healthcheck_run_history_manifest.py`
- `tests/test_full_app_healthcheck_run_history_compare.py`
- `tests/test_full_app_healthcheck_quick_mode_release_gate_proposal.py`
- `tests/test_full_app_healthcheck_full_mode_release_checklist.py`
- `tests/test_full_app_healthcheck_report_sections.py`


### ui-healthcheck-direct-bridge

- `tests/test_ui_qt_decision_desk_view.py`
- `tests/test_ui_qt_market_regime_view.py`
- `tests/test_ui_qt_portfolio_view.py`
- `tests/test_ui_qt_recommendation_next_steps_copy.py`
- `tests/test_ui_qt_recommendation_profiles.py`
- `tests/test_ui_qt_research_workflow.py`
- `tests/test_ui_qt_run_registry_compare.py`
- `tests/test_ui_qt_runtime_view.py`
- `tests/test_ui_qt_smart_money_flow_view.py`
- `tests/test_ui_qt_update_view_workbench.py`
- `tests/test_ui_qt_watchlist_candidate_pool_copy.py`

### ui-healthcheck-candidate-bridge

- `tests/test_ui_qt_chart_payloads.py`
- `tests/test_ui_qt_chart_widget_factory.py`
- `tests/test_ui_qt_decision_desk_main_integration.py`
- `tests/test_ui_qt_portfolio_condition_monitor.py`
- `tests/test_ui_qt_recommendation_portfolio_results.py`
- `tests/test_ui_qt_report_export.py`
- `tests/test_ui_qt_research_lab_mode_driven_ui.py`
- `tests/test_ui_qt_research_lab_workbench_copy.py`
- `tests/test_ui_qt_research_run_save.py`
- `tests/test_ui_qt_theme.py`

### service-oracle-data-market

- `tests/test_abnormal_fundamental_flags.py`
- `tests/test_broker_branch_decode.py`
- `tests/test_broker_flow_units.py`
- `tests/test_company_registry.py`
- `tests/test_data_module.py`
- `tests/test_db_manager_logging.py`
- `tests/test_analysis/test_technical_analysis.py`
- `tests/test_finmind_monthly_revenue_create_time.py`
- `tests/test_fundamental_availability.py`
- `tests/test_fundamental_availability_entrypoint.py`
- `tests/test_fundamental_availability_sources.py`
- `tests/test_fundamental_data.py`
- `tests/test_fundamental_diagnostics_service.py`
- `tests/test_fundamental_factor_adapters.py`
- `tests/test_fundamental_factor_service.py`
- `tests/test_fundamental_schema.py`
- `tests/test_fundamental_sqlite_provider.py`
- `tests/test_fundamental_statement_availability_entrypoint.py`
- `tests/test_fundamental_statement_availability_sources.py`
- `tests/test_fundamental_statement_data.py`
- `tests/test_market_breadth_service.py`
- `tests/test_monthly_revenue_availability_builder.py`
- `tests/test_monthly_revenue_availability_history.py`
- `tests/test_relative_strength_liquidity_service.py`
- `tests/test_revenue_factor_pack.py`
- `tests/test_sector_rotation_service.py`
- `tests/test_sqlite_inspector_service.py`
- `tests/test_sqlite_storage_compatibility.py`
- `tests/test_statement_factor_pack.py`
- `tests/test_tpex_background_refresh_script.py`
- `tests/test_tpex_daily_price_history_plan.py`
- `tests/test_tpex_daily_price_history_plan_cli.py`
- `tests/test_update_service_status.py`
- `tests/test_valuation_data.py`
- `tests/test_valuation_factor_adapters.py`
- `tests/test_valuation_policy.py`
- `tests/test_valuation_source_policy.py`

### service-oracle-research-backtest

- `tests/test_backtest/test_overfitting_risk.py`
- `tests/test_backtest/test_parallel_safety.py`
- `tests/test_backtest_diagnostics_and_date_adjustment.py`
- `tests/test_backtest_factor_metadata.py`
- `tests/test_backtest_timeline_contract.py`
- `tests/test_batch_backtest_research_run_save.py`
- `tests/test_factor_adapters.py`
- `tests/test_factor_contract.py`
- `tests/test_factor_gate.py`
- `tests/test_factor_registry.py`
- `tests/test_factor_service_research_run.py`
- `tests/test_pattern_analysis/test_flag_pattern_robustness.py`
- `tests/test_optimizer_service.py`
- `tests/test_promotion_reconciliation.py`
- `tests/test_recommendation_portfolio_backtest.py`
- `tests/test_recommendation_portfolio_optimizer.py`
- `tests/test_report_export_dtos.py`
- `tests/test_report_export_service.py`
- `tests/test_research_lab_mode_taxonomy.py`
- `tests/test_research_result_presentation.py`
- `tests/test_research_run_comparison_service.py`
- `tests/test_research_run_legacy_adapter.py`
- `tests/test_research_run_repository.py`
- `tests/test_research_run_service.py`
- `tests/test_score_threshold_policy.py`
- `tests/test_strategy_lifecycle_repository.py`
- `tests/test_strategy_lifecycle_service.py`
- `tests/test_strategy_params_persistence_roundtrip.py`
- `tests/test_strategy_threshold_modes.py`
- `tests/test_walkforward_service.py`
- `tests/test_weight_contract.py`

### service-oracle-recommendation

- `tests/test_recommendation_dto_roundtrip.py`
- `tests/test_recommendation_percentile_ranker.py`
- `tests/test_recommendation_portfolio_hints.py`
- `tests/test_recommendation_portfolio_numeric_governance.py`
- `tests/test_recommendation_portfolio_promotion_service.py`
- `tests/test_recommendation_portfolio_run_repository.py`
- `tests/test_recommendation_portfolio_view_charts.py`
- `tests/test_recommendation_profile_service.py`
- `tests/test_recommendation_ranking_service.py`

### service-oracle-portfolio-decision-runtime

- `tests/test_decision_desk_dashboard_service.py`
- `tests/test_decision_desk_risk_prompt_service.py`
- `tests/test_decision_desk_service.py`
- `tests/test_decision_desk_ui_contract.py`
- `tests/test_portfolio_alert_service.py`
- `tests/test_portfolio_chip_monitor.py`
- `tests/test_portfolio_condition_monitor.py`
- `tests/test_portfolio_deepening.py`
- `tests/test_portfolio_delete.py`
- `tests/test_portfolio_feedback_service.py`
- `tests/test_portfolio_jsonl_store_serialization.py`
- `tests/test_portfolio_mvp.py`
- `tests/test_portfolio_numeric_governance.py`
- `tests/test_portfolio_review_service.py`
- `tests/test_portfolio_source_adapter.py`
- `tests/test_smart_money_semantic_service.py`
- `tests/test_watchlist_trigger_service.py`

### governance-doc-tooling

- `tests/test_audit_document_encoding.py`
- `tests/test_financial_float_boundary_checker.py`
- `tests/test_financial_units.py`
- `tests/test_governance_tools.py`
- `tests/test_mcp_context_server.py`
- `tests/test_performance_numeric_governance.py`

### write-risk-dry-run-required

- `tests/scripts/test_all_branches_one_day.py`
- `tests/scripts/test_broker_branch_10days.py`
- `tests/scripts/test_broker_branch_single.py`
- `tests/scripts/test_moneydj_requests.py`
- `tests/scripts/test_moneydj_requests_tables.py`
- `tests/test_company_registry_cli.py`
- `tests/test_finmind_monthly_revenue_create_time_cli.py`
- `tests/test_fundamental_migration.py`
- `tests/test_fundamental_migration_cli.py`
- `tests/test_fundamental_statement_backfill.py`
- `tests/test_fundamental_statement_backfill_cli.py`
- `tests/test_inspect_fundamental_factors_cli.py`
- `tests/test_monthly_revenue_availability_builder_cli.py`
- `tests/test_monthly_revenue_availability_cli.py`
- `tests/test_monthly_revenue_availability_history_cli.py`
- `tests/test_monthly_revenue_backfill.py`
- `tests/test_monthly_revenue_backfill_cli.py`
- `tests/test_monthly_revenue_retroactive_baseline_cli.py`
- `tests/test_monthly_revenue_snapshot_harvester.py`
- `tests/test_monthly_revenue_snapshot_harvester_cli.py`
- `tests/test_statement_availability_cli.py`
- `tests/test_statement_retroactive_baseline_cli.py`
- `tests/test_tpex_daily_price_backfill.py`
- `tests/test_tpex_daily_price_backfill_cli.py`
- `tests/test_tpex_daily_price_source.py`
- `tests/test_valuation_metrics_backfill.py`
- `tests/test_valuation_metrics_backfill_cli.py`
- `tests/test_valuation_source_policy_cli.py`

### slow-e2e-or-environment

- `tests/e2e/test_data_path_isolation.py`

### manual-only

- `tests/manual/legacy_advanced_patterns_check.py`
- `tests/manual/legacy_api_endpoints_check.py`
- `tests/manual/legacy_backtest_recommendation_check.py`
- `tests/manual/legacy_daily_data_check.py`
- `tests/manual/legacy_data_loading_check.py`
- `tests/manual/legacy_extended_patterns_check.py`
- `tests/manual/legacy_math_analyzer_check.py`
- `tests/manual/legacy_ml_analyzer_check.py`
- `tests/manual/legacy_optimized_patterns_check.py`
- `tests/manual/legacy_pattern_analyzer_check.py`
- `tests/manual/legacy_pattern_parameter_tuning_check.py`
- `tests/manual/legacy_recommendation_report_check.py`
- `tests/manual/legacy_signal_combiner_check.py`
- `tests/manual/legacy_technical_analyzer_check.py`
- `tests/manual/legacy_twse_api_check.py`
- `tests/manual/legacy_utils_check.py`

### legacy-or-low-priority

- `tests/manual/legacy_diagnostics/run_market_index_test.py`
- `tests/manual/legacy_diagnostics/run_technical_calc_test.py`
- `tests/manual/legacy_diagnostics/run_tests.py`
- `tests/manual/legacy_diagnostics/check_columns.py`
- `tests/manual/legacy_diagnostics/check_processed_file.py`
- `tests/manual/legacy_diagnostics/check_saved_file.py`
- `tests/manual/legacy_diagnostics/check_signals_file.py`
- `tests/test_ml_analysis/__init__.py`
- `tests/test_pattern_analysis/__init__.py`

### general-unit-keep-in-pytest

- `tests/conftest.py`
- `tests/test_core/test_config.py`
- `tests/test_core/test_data_loader.py`
- `tests/test_indicator_parameter_registry.py`
- `tests/test_m2_a_integration.py`

## 對目前 Gemini Batch A-C 的排查結論 (已修復)

- 專屬單元測試可通過，且 `scripts/run_full_app_healthcheck.py --mode quick --fail-fast` 已修正並能執行通過。
- 失敗原因已修復：已將未實作的 active actions 從 manifest 移除，改放至 `coverage_matrix.py` 的 `not-yet-automated` 中，並新增測試防線，確保 manifest 中的 active actions 都已在 action registry 註冊。
- `test_suite_bridge.py` 已使用 `test_inventory.py` 分類清冊進行過濾，僅允許 direct bridge 的測試檔案。
