# Test Inventory / Healthcheck Classification 2026-06-23

> 目的：盤點 `tests/` 底下所有有效 Python 測試檔，分類哪些可以被非破壞式 Full App Healthcheck Runner 呼叫、哪些只能作 service/oracle 證據、哪些必須保留在一般 pytest 或人工檢查流程。

## 2026-08-28 machine refresh

> Latest follow-up after the official calendar bundle capture slice: filesystem／inventory=`654/654`、`3726 tests collected`；前一輪段落中的 `653/653`／`3719`／`3702`／`3691`／`3696` 僅作歷史基準，以下 current count 以本行與後續欄位為準。

本輪 Data Update trust UX、Gate 3 P0 Source Control Center／P0 intake validator／decision append CLI、Gate 4 Portfolio foundation、Dashboard／market／candidate-pool refresh status、OOC RSS monitor lifecycle、MainWindow startup screenshot 時序、Runtime environment readiness、Runtime existing-file write-handle／Registry transaction probe、Runtime 窄版垂直欄／session context strip、Update date-level progress、合作式取消與大型匯出／合併批次進度及安全邊界、增量合併 no-op 明確狀態、Paper future-date look-ahead guard、Decision Desk current-date/query-only guard、Paper／Decision 排程 future-write guard、UpdateView 台灣市場日期／localized unavailable／全域錯誤摘要同步回歸、候選資料源頁內摘要、窄版導覽／卡片／操作鈕重排、Paper fills template/append CLI UTF-8 guard、單檔 CSV 讀取批次取消、Recommendation Pattern Explain evidence、SQLite 欄位別名正規化、Formal stale-clock diagnostic、Pre-V2／Simulation projection consistency、prospective staging diagnostics、P0 owner packet renderer 與 TPEx fallback／日期 fail-closed 回歸補強，以及 P0 fallback rejected／date provenance UI projection regression、scheduled-task registration inspector（含 CP1252 `--help` guard）、technical process-pool／worker recovery acceptance、P0 audit → candidate intake projection、freshness ACL-safe status/log route、machine evidence handoff projection／intake envelope guard、explicit freshness readiness projection、freshness probe ACL fail-soft regression、PowerShell freshness wrapper canonical delegation、Formal candidate inventory、月營收 snapshot 選擇／候選狀態、availability candidate merge 與 broker real HTTP canary 後重新收集：`3683 tests collected`，filesystem／inventory 為
`653/653`，缺漏路徑、過時路徑與 collection errors 均為 `0`。新增納管的測試主要是
P0 source control center／P0 intake validator／decision append CLI、Portfolio Stress Lab、Trade Import contract、Paper Portfolio readiness、Paper Trade Ledger、Paper fills CSV producer、Equal Weight builder、Paper weekly evidence、Stress history、月營收 availability candidate projection 與 UI bridge；這些測試仍維持原分類與執行邊界，
不會因此被 quick healthcheck 直接執行。

本次 technical production canary guard 新增 7 個定向測試，P0 license evidence candidate capture 新增 5 個定向測試，月營收 availability candidate projection 新增 6 個定向測試；`pytest --collect-only` 已更新為 `3719`，尚未重跑耗時的全量回歸。

本次另新增 prospective clock planner 的 8 個定向測試，以及官方日曆 bundle capture／normalizer 的 7 個定向測試；它們只驗證官方日曆 raw response、準備日與既有 clock 不重用，仍維持 governance tooling 分類，不會啟動 Formal 或 scheduler。

> 機器重算（2026-08-28）：新增 P0 fallback rejected／date provenance UI projection regression、scheduled-task registration inspector（含 CP1252 `--help` guard）、technical process-pool／worker recovery acceptance、P0 audit → candidate intake projection、freshness ACL-safe status/log route、machine evidence handoff projection、explicit freshness readiness projection、Evidence Workbench pending-period、formal cutoff 診斷、freshness probe ACL fail-soft regression、PowerShell freshness wrapper canonical delegation、Formal candidate inventory、月營收 snapshot 選擇／候選狀態、availability candidate merge、monthly-revenue availability candidate projection、prospective clock planner、official calendar bundle capture／normalizer 與 broker real HTTP canary 後，實際為 `3726 tests collected`、filesystem／inventory `654/654`；current category `general-unit-keep-in-pytest=143`。以下 current count 欄位已同步，前述段落中的 `3614`／`3612`／`3596`／`637`／`3683`／`3696` 為前序中間讀數，`3603`／`3604`／`3607`／`3608` 為更早的前序中間讀數。

本輪另以 `scripts/run_full_app_healthcheck.py --mode full --ui-smoke --ui-smoke-switch-tabs --ui-smoke-screenshot --ui-smoke-resize 1366x768 --ui-smoke-resize 390x844 --ui-smoke-dialog-cancel --output-dir output/qa/full_app_healthcheck_20260827_update_responsive_final --fail-fast` 完成真實 MainWindow smoke（最新 run `20260827_104105`）：8 個 workspace 均可切換、cancel-only probe 未觸發 destructive action；目前環境的 weekly projection 在 startup 畫面揭露 `3/3`；`1366x768` 與 `390x844` 實際均符合 requested viewport（`matched`），窄版 Runtime 改為垂直治理欄並提供垂直捲動，UpdateView 導覽／卡片／操作鈕也改為可讀重排。UI smoke 子程序會在報告目錄下使用隔離 `_isolated_app/data`／`_isolated_app/output`，不依賴正式資料根目錄的寫入權限，也不寫正式資料；其中 UpdateView focused regression 為 `59 passed / 1 warning`。

Current filesystem Python files: `654`

最新機器重算（2026-08-28）以 `pytest --collect-only -q -o addopts=` 實際收集 `3726 tests collected`；下方歷史段落中的 `3719`／`3702`／`3684`／`3683`／`3691`／`3696` 為前一輪中間讀數。

- 預設 pytest 可收集測試檔：`615`
- pytest support 檔：`1`
- 預設不收集檔：`30`
- `pytest --collect-only -q -o addopts=`：`3726 tests collected`

2026-08-28 本次改動前最近一次全量 pytest 已以 `-o addopts=` 完成：`3683 passed, 1 skipped, 26 warnings`（`540.83s`；已納入 availability merge、broker real HTTP canary、scheduler `--help` guard、availability builder snapshot 選擇與月營收候選狀態回歸）。本次月營收 availability candidate projection 改動只完成 focused regression，尚未重跑耗時的全量 pytest。
下方較早的 `3613 passed`／`3607 passed`／`3606 passed`／`3603 passed`／`3592 passed` 是前一輪中間基準，
不取代本次完整回歸結果。

| 分類 | 數量 |
|---|---:|
| `general-unit-keep-in-pytest` | 143 |
| `governance-doc-tooling` | 109 |
| `healthcheck-runner-owned` | 29 |
| `legacy-or-low-priority` | 10 |
| `manual-only` | 14 |
| `service-oracle-data-market` | 92 |
| `service-oracle-portfolio-decision-runtime` | 103 |
| `service-oracle-recommendation` | 18 |
| `service-oracle-research-backtest` | 56 |
| `slow-e2e-or-environment` | 3 |
| `ui-healthcheck-candidate-bridge` | 22 |
| `ui-healthcheck-direct-bridge` | 12 |
| `write-risk-dry-run-required` | 43 |

最近一次完整 pytest 已以 `-o addopts=` 完成：`3668 passed, 1 skipped, 26 warnings`（`542.69s`；本次執行未指定 JUnit 輸出）。本輪修正 OOC RSS monitor 的 preflight thread lifecycle、UpdateView 合作式取消、SQLite 結果可見性與匯出／合併原子安全邊界，並加入 P0 intake validator／decision append CLI、P0 audit → candidate intake projection、freshness ACL-safe status/log route、machine evidence handoff projection／intake envelope guard、explicit freshness readiness projection、owner packet route evidence、Evidence Workbench pending-period 顯示、formal cutoff 時區診斷、freshness probe ACL fail-soft、PowerShell freshness wrapper canonical delegation、匯出／合併批次進度、增量合併 no-op 狀態、Runtime staging Registry transaction／rollback probe、Runtime existing-file write-handle probe、Paper future-date look-ahead guard、Paper／Decision 排程 future-write guard、Decision Desk current-date/query-only guard、UpdateView 台灣市場日期／localized unavailable／全域錯誤摘要同步、候選資料源頁內摘要、窄版導覽／卡片／操作鈕重排、Paper fills template/append CLI UTF-8 guard、單檔 CSV 讀取批次取消與 reader cleanup、Recommendation Pattern Explain evidence、SQLite 欄位別名正規化、Formal stale-clock diagnostic、Pre-V2／Simulation projection consistency、P0 owner packet renderer、P0 audit CLI CP1252 console guard、TPEx institutional／credit fallback 與日期 fail-closed guard、P0 fallback rejected／date provenance UI projection、technical process-pool／worker recovery acceptance、scheduler registration inspector、Formal candidate inventory 與 inventory 登錄後，全量執行未再重現先前約 89% 的 Windows access violation；warnings 主要是 joblib 核心數偵測 fallback、研究回測同日成交假設與 pytest cache 權限提示。仍保留 focused／full run 證據，後續若再出現 native fault 需以 WER／dump 交叉定位。
- scheduler `--help` CP1252 guard targeted regression：`3 passed / 1 warning`；其後已納入上述最新全量回歸。
第一次 full run 暴露的新測試檔未登錄 inventory；補登錄與數量同步後重跑全量已通過，inventory audit 維持 `0` machine-checkable blockers。本輪環境／Runtime／Update／healthcheck
集中 regression（涵蓋 Update worker／coordinator／service／SQLite／UI／formatter、匯出／合併原子邊界與 healthcheck）既有基準為 `177 passed`；本輪受影響的 Update／UI／coordinator targeted suite 為 `151 passed / 1 warning`，UpdateView focused UI regression 為 `59 passed / 1 warning`，大型合併讀取批次取消與 Update service suite 為 `58 passed / 1 warning`，Pre-V2／Workbench projection consistency 為 `38 passed / 1 warning`、Simulation projection consistency 為 `5 passed / 1 warning`，
Update Tab QA 為 `23 passed / 0 failed / 4 skipped`。

本節由 `scripts/audit_test_inventory.py` 的 deterministic audit 契約維護；`2026-08-14`
以下段落保留作歷史基準。

## 2026-08-14 machine refresh

本輪新增 Direct/OOC formal-input watcher、scheduled raw PIT refresh、既有 owner
custody 判別、lineage-lock custody、legacy continuation gate normalization、Phase 3C 現行官方 schema、UI crash diagnostics、logging fail-soft、release operational-root 與 Windows persisted user environment 回歸測試後重新收集：`3162 tests collected`，filesystem／inventory 為
`595/595`，collection errors 與
machine-checkable blockers 均為 `0`；前一行
`3120` 為 watcher regression 補入前的中間基準，
`3119` 與 `3114` 保留作前序歷史基準。

Current filesystem Python files: `595`

- 預設 pytest 可收集測試檔：`559`
- pytest support 檔：`1`
- 預設不收集檔：`30`
- `pytest --collect-only -q -o addopts=`：`3186 tests collected`

| 分類 | 數量 |
|---|---:|
| `general-unit-keep-in-pytest` | 135 |
| `governance-doc-tooling` | 69 |
| `healthcheck-runner-owned` | 29 |
| `legacy-or-low-priority` | 10 |
| `manual-only` | 14 |
| `service-oracle-data-market` | 88 |
| `service-oracle-portfolio-decision-runtime` | 100 |
| `service-oracle-recommendation` | 18 |
| `service-oracle-research-backtest` | 56 |
| `slow-e2e-or-environment` | 3 |
| `ui-healthcheck-candidate-bridge` | 20 |
| `ui-healthcheck-direct-bridge` | 11 |
| `write-risk-dry-run-required` | 42 |

本節由 `scripts/audit_test_inventory.py` 的 deterministic audit 契約維護；CLI 同時檢查 filesystem／inventory 缺漏、過時路徑、上述數量漂移、AST parse errors、精確重複測試函式與 `pytest --collect-only` 結果。下方清單保留 2026-06-23 初始盤點歷史，不再作 current count SSOT。

本輪完整 pytest 已以 `-o addopts=` 完成：`3185 passed, 1 skipped, 24 warnings`；
Direct/OOC／scheduled focused suite 為 `71 passed`，目前 collection 與 inventory 均無錯誤。
Warnings 為既有 recommendation portfolio
backtest 的研究假設提示，沒有 test failure 或 stderr error；相關 wrapper／maintainer
`py_compile` 與 mypy 均通過。

2026-07-30 起人工決策清單已清空；來源授權或 PIT 證據不可證時由自動規則 fail closed 至 `research_shadow`，缺 provenance 時自動標記 `blocked_no_provenance`，不再等待人工簽核，也不把未證實資料升為 Formal。

## 2026-06-23 初始結論

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
- `tests/test_ui_qt_recommendation_next_steps_copy_text.py`
- `tests/test_ui_qt_watchlist_candidate_pool_copy_text.py`
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
- `tests/test_ui_qt_recommendation_next_steps_copy_text.py`
- `tests/test_ui_qt_recommendation_profiles.py`
- `tests/test_ui_qt_research_workflow.py`
- `tests/test_ui_qt_run_registry_compare.py`
- `tests/test_ui_qt_runtime_view.py`
- `tests/test_ui_qt_smart_money_flow_view.py`
- `tests/test_ui_qt_update_view_workbench.py`
- `tests/test_ui_qt_watchlist_candidate_pool_copy_text.py`

### ui-healthcheck-candidate-bridge

- `tests/test_ui_qt_chart_payloads.py`
- `tests/test_ui_qt_chart_widget_factory.py`
- `tests/test_ui_qt_decision_desk_main_integration.py`
- `tests/test_ui_qt_portfolio_condition_monitor.py`
- `tests/test_ui_qt_recommendation_portfolio_results.py`
- `tests/test_ui_qt_report_export.py`
- `tests/test_ui_qt_research_lab_mode_driven_ui.py`
- `tests/test_ui_qt_research_lab_workbench_copy_text.py`
- `tests/test_ui_qt_research_run_save.py`
- `tests/test_ui_qt_session_context_strip.py`
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
- `tests/test_portfolio_stress_lab_service.py`
- `tests/test_trade_import_service.py`
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
