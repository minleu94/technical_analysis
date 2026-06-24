# Full App Healthcheck 逐列 Coverage Mapping 2026-06-24

> 來源母檔：[`FULL_APP_HEALTHCHECK_2026_06_16.md`](FULL_APP_HEALTHCHECK_2026_06_16.md)。
> 目的：把人工 healthcheck 每一列對照到目前非破壞式 super healthcheck runner、direct bridge、candidate bridge、service oracle evidence 或 manual-only 狀態。

## 判讀規則

本文件是 coverage 對照表，不是 pass / fail 結論，也不是 release gate。

| Coverage 類型 | 意義 |
|---|---|
| `direct-quick` | 已由 quick mode 非破壞 direct bridge 覆蓋。 |
| `direct-full` | 已由 full mode 非破壞 direct bridge 覆蓋；quick mode 不一定執行。 |
| `candidate` | 已有候選 UI 測試或相關 pytest，但尚未納入 runner bridge。 |
| `oracle` | 有 service / domain / data oracle 證據，可輔助判讀，但不是 UI flow step。 |
| `report-only` | 已有 metadata、診斷或 checklist 可出現在 healthcheck 報告，但不執行該流程。 |
| `manual-only` | 仍需人工操作、視覺判讀、真實資料確認或 MainWindow 流程。 |
| `write-risk-manual` | 涉及資料寫入、刪除、migration、backfill 或 high-risk confirm；不得放入非破壞 runner。 |

目前 runner bridge 允許範圍：

- Quick mode：`ui-update-workbench`、`ui-decision-desk`。
- Full mode：Quick mode 兩項，加上 `ui-research-workflow`、`ui-market-regime-view`、`ui-run-registry-compare`、`ui-smart-money-flow`、`qa-update-tab`。

## 摘要

| 區塊 | 行數 | 目前自動化判讀 |
|---|---:|---|
| 數據更新 / UpdateView | 35 | UI contract 與狀態查詢已有 direct bridge；真實下載、合併、強制重建、背景補齊與正式資料驗證仍需 manual / Data Audit。 |
| 市場觀察 | 22 | Regime 與 Smart Money 部分已有 full direct bridge；強弱股 / 產業排行、圖表美觀與效能仍需人工或後續 candidate。 |
| 每日決策 | 9 | quick direct bridge 與 service oracle 已覆蓋 snapshot / dashboard / warning contract；實際資料品質與互動判讀仍需人工。 |
| Research Lab / 回測 | 42 | full direct bridge 覆蓋多數 Research workflow、Registry 比較與推薦回放；匯出、最佳化重任務與部分高風險操作仍不可當 release gate。 |
| 推薦分析 | 20 | 多數已有 candidate / service oracle；部分跨頁送 Research Lab 已由 full direct bridge 覆蓋。 |
| 觀察清單 | 13 | 跨頁 handoff 與部分候選池操作已有 full direct bridge / candidate；清單 CRUD 仍以人工驗證為主。 |
| 持倉管理 | 17 | 目前以 candidate UI tests 與 service oracle 為主；寫入 / 刪除 / 清空資料屬 write-risk manual。 |
| Runtime Observatory | 6 | 已有 candidate UI test，尚未納入 runner bridge；仍需人工判讀狀態語意。 |
| 全域與跨工作區流程 | 7 | MainWindow 啟動與 Tab 順序仍 manual-only；推薦到回測已有 full direct bridge；持倉與主力下鑽仍需 candidate / manual。 |

## 數據更新 / UpdateView

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| U-001 | 全部資料 / 檢查數據狀態 | 通過 | `direct-quick` + `oracle` | `qa-update-tab` 覆蓋 `U-001`；`tests/test_update_service_status.py` 提供 read-only service evidence。 | 保留 direct bridge。 |
| U-002 | 快速更新（僅 SQLite） | 已修正待驗證 | `oracle` + `write-risk-manual` | UpdateView tests 覆蓋 safe-update contract；真實資料更新仍會寫 SQLite / CSV source。 | 不進 runner；人工或 Data Audit 驗證實際資料。 |
| U-003 | 安全更新（完整 CSV + SQLite） | 已修正待驗證 | `oracle` + `write-risk-manual` | service tests 可驗證流程契約；完整更新涉及正式資料寫入。 | 維持人工高風險驗證。 |
| U-004 | 清除日誌 | 通過 | `direct-quick` | `tests/test_ui_qt_update_view_workbench.py` 覆蓋 UpdateView UI contract；近期 UI commit 需重看按鈕位置。 | 可補更精確 offscreen assertion。 |
| U-005 | 每日股價日期範圍設定 | 通過 | `direct-quick` | `test_source_date_controls_use_clear_calendar_buttons`、date picker tests。 | 保留 direct bridge。 |
| U-006 | 每日股價檢查此資料源狀態 | 需確認 | `direct-quick` + `oracle` | `qa-update-tab` 覆蓋 `U-006`；UpdateView test 覆蓋 detail status summary。 | 人工確認文字是否足夠可讀。 |
| U-007 | 每日股價手動下載此資料源 | 需確認 | `oracle` + `write-risk-manual` | `test_manual_daily_update_also_fetches_tpex_daily_price` 驗證契約；真實下載需外部來源與寫入。 | 不進 runner；Data Audit 驗證正式資料日期。 |
| U-008 | 合併每日股價 | 已修正待驗證 | `oracle` + `write-risk-manual` | `test_merge_daily_data_includes_tpex_daily_price_dir`、sync tests。 | 只做 dry-run / tmp path 測試；正式合併人工確認。 |
| U-009 | 匯出 CSV 備案 | 通過 | `manual-only` | 目前不在 runner bridge；可能屬 report/export candidate。 | 需要 tmp output dry-run 才能自動化。 |
| U-010 | 強制重新合併所有每日股價 | 需確認 | `write-risk-manual` + `report-only` | D-4 high-risk dialog plan 只描述取消路徑，不執行。 | 只能人工測取消流程；不得自動 confirm。 |
| U-011 | 大盤指數日期範圍設定 | 通過 | `direct-quick` | UpdateView source date controls 覆蓋共用日期控制。 | 保留 direct bridge。 |
| U-012 | 大盤指數檢查狀態 | 通過 | `oracle` | `check_source_detail` service contract 可覆蓋狀態查詢。 | 若需 UI 精準列入，可補 covered ID。 |
| U-013 | 大盤指數手動下載 | 通過 | `write-risk-manual` | 需要真實來源 / 寫入；不適合非破壞 runner。 | 保留人工。 |
| U-014 | 大盤指數匯出 CSV | 通過 | `manual-only` | 未納入 bridge。 | 若要自動化，需 tmp output export test。 |
| U-015 | 產業指數日期範圍設定 | 通過 | `direct-quick` | UpdateView source date controls 覆蓋共用日期控制。 | 保留 direct bridge。 |
| U-016 | 產業指數檢查狀態 | 通過 | `oracle` | Update service status oracle。 | 可補直接 mapping。 |
| U-017 | 產業指數手動下載 | 通過 | `write-risk-manual` | 真實來源 / 寫入。 | 保留人工。 |
| U-018 | 產業指數匯出 CSV | 通過 | `manual-only` | 未納入 bridge。 | 需 tmp output export test。 |
| U-019 | 券商分點日期範圍設定 | 通過 | `direct-quick` | UpdateView source date controls 覆蓋共用日期控制。 | 保留 direct bridge。 |
| U-020 | 券商分點檢查狀態 | 需確認 | `direct-full` + `oracle` | `qa-update-tab` 覆蓋 `U-020`；service oracle read-only 載入 registry。 | 人工確認狀態摘要可讀。 |
| U-021 | 券商分點手動下載 | 通過 | `oracle` + `write-risk-manual` | `tests/test_broker_branch_decode.py` 覆蓋 MoneyDJ HTTP fast path、non-trading skip；真實下載仍寫 daily CSV。 | 不進 runner；必要時用 tmp data root live sample。 |
| U-022 | 合併券商分點 | 已修正待驗證 | `oracle` + `write-risk-manual` | broker flow SQLite / unit tests 覆蓋 schema 與 merge contract。 | 正式合併人工 / Data Audit。 |
| U-023 | 計算技術指標 | 已修正待驗證 | `oracle` + `write-risk-manual` | `test_smart_incremental_technical_calculation_*` 與 indicator merge tests。 | 不在 runner 實作正式計算。 |
| U-024 | SQLite 資料檢視 | 通過 | `direct-quick` + `oracle` | `test_sqlite_inspector_*` 覆蓋分頁、排序、日期、stale result、duplicate columns。 | 近期 UI compact pagination 已有回歸風險，需保持 direct bridge。 |
| U-025 | 月營收 MOPS snapshot | 已修正待驗證 | `oracle` + `write-risk-manual` | fundamental CLI / service tests 可作 evidence；正式 apply 寫 DB。 | 只做 dry-run 自動化；正式寫入人工確認。 |
| U-026 | SQLite 基本面資料表檢視 | 已修正待驗證 | `direct-quick` + `oracle` | SQLite Inspector tests 覆蓋 table / filter contract；fundamental tests 作資料 evidence。 | 人工確認下拉表名與欄位語意。 |
| U-027 | 基本面 factor diagnostics CLI | 需確認 | `oracle` | fundamental source / factor tests 可驗證唯讀 diagnostics。 | 可納入 command advisor，不進 UI bridge。 |
| U-028 | 背景補齊 TPEX + 技術指標 | 已修正待驗證 | `oracle` + `write-risk-manual` | `test_background_tpex_refresh_does_not_force_technical_all` 與 service tests。 | 不自動啟動背景補齊；人工讀狀態。 |
| U-029 | 檢查背景任務狀態 | 已修正待驗證 | `direct-quick` + `oracle` | UpdateView tests 覆蓋背景狀態按鈕 / status file contract。 | 人工確認訊息框與 console 可讀。 |
| U-I-20260617-001 | TPEX / SQLite 歷史缺口 | 已修正待驗證 | `oracle` + `manual-only` | TPEX sync / daily_prices tests。 | Data Audit 查正式 DB。 |
| U-I-20260617-002 | 每日股價手動下載跑 TPEX | 已修正待驗證 | `oracle` | manual daily update TPEX contract test。 | 人工或 tmp source live smoke。 |
| U-I-20260617-003 | 快速 / 安全更新差異 | 已修正待驗證 | `direct-quick` + `oracle` | UpdateView labels / safe update sequence tests。 | 人工確認文案理解。 |
| U-I-20260617-004 | 背景補齊順序 | 已修正待驗證 | `oracle` | background refresh / technical skip tests。 | 不自動執行背景任務。 |
| U-I-20260617-005 | TPEX SQLite sync 欄位 | 已修正待驗證 | `oracle` | daily price sync canonicalization tests。 | Data Audit spot check。 |
| U-I-20260618-001 | Git / QA 母檔接續 | 已記錄 | `report-only` | 本 mapping 與 closeout 文件。 | 維護文件接手入口。 |

## 市場觀察

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| M-001 | 大盤指數檢測市場狀態 | 已修正待驗證 | `direct-full` + `oracle` | `ui-market-regime-view` 覆蓋 `M-001`；walk-forward service oracle。 | 保留 full bridge。 |
| M-002 | 技術細節顯示 | 已修正待驗證 | `direct-full` + `oracle` | `ui-market-regime-view` 覆蓋 `M-002` 與 breakout base indicators。 | 補人工看可讀性。 |
| M-003 | 強勢個股本日 / 本周切換 | 通過 | `manual-only` | 尚無 direct bridge 指定覆蓋。 | 可納入 offscreen widget check 後續。 |
| M-004 | 強勢個股載入數據 | 通過 | `manual-only` + `oracle` | Market data service 有資料 evidence，但 UI 載入效能需人工。 | 若要自動化，需 SQLite-first performance smoke。 |
| M-005 | 強勢個股刷新 | 通過 | `manual-only` | 未納入 bridge。 | 候選 offscreen check。 |
| M-006 | 強勢個股加入觀察清單 | 通過 | `manual-only` | 跨頁加入候選池未直接覆蓋此來源。 | 候選 UI flow。 |
| M-007 | 弱勢個股本日 / 本周切換 | 通過 | `manual-only` | 未納入 bridge。 | 候選 offscreen check。 |
| M-008 | 弱勢個股載入數據 | 通過 | `manual-only` + `oracle` | 資料 evidence 可輔助，效能仍人工。 | 後續 performance smoke。 |
| M-009 | 弱勢個股刷新 | 通過 | `manual-only` | 未納入 bridge。 | 候選 offscreen check。 |
| M-010 | 弱勢個股加入觀察清單 | 通過 | `manual-only` | 未納入 bridge。 | 候選 UI flow。 |
| M-011 | 強勢產業本日 / 本周切換 | 通過 | `manual-only` | 未納入 bridge。 | 候選 offscreen check。 |
| M-012 | 強勢產業載入數據 | 通過 | `manual-only` + `oracle` | 資料 evidence 可輔助，效能仍人工。 | 後續 performance smoke。 |
| M-013 | 強勢產業刷新 | 通過 | `manual-only` | 未納入 bridge。 | 候選 offscreen check。 |
| M-014 | 弱勢產業本日 / 本周切換 | 通過 | `manual-only` | 未納入 bridge。 | 候選 offscreen check。 |
| M-015 | 弱勢產業載入數據 | 通過 | `manual-only` + `oracle` | 資料 evidence 可輔助，效能仍人工。 | 後續 performance smoke。 |
| M-016 | 弱勢產業刷新 | 通過 | `manual-only` | 未納入 bridge。 | 候選 offscreen check。 |
| M-017 | 主力流向週期切換 | 已修正待驗證 | `direct-full` + `oracle` | `ui-smart-money-flow` 覆蓋 `M-017`。 | 人工確認 Top / Bottom 50 體感。 |
| M-018 | 主力流向圖表型態切換 | 需確認 | `manual-only` | 圖表可讀性 / 美觀屬 visual QA。 | 需 viewport / screenshot evidence。 |
| M-019 | 主力流向開始掃描 | 需確認 | `direct-full` + `oracle` | `ui-smart-money-flow` 覆蓋 `M-019`；broker flow oracle。 | 真實資料品質仍 Data Audit。 |
| M-020 | 表格排序與懸停提示 | 需確認 | `manual-only` | Tooltip 與排序交互未納入 bridge。 | 候選 offscreen UI test。 |
| M-021 | 主力流向加入觀察清單 | 通過 | `manual-only` | 未直接覆蓋此來源加入。 | 候選跨頁 flow。 |
| M-022 | 分點進出追蹤選擇券商分點 | 需確認 | `direct-full` + `oracle` | `ui-smart-money-flow` 覆蓋 `M-022` 分點 drill-down。 | 人工確認趨勢視覺化。 |

## 每日決策

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| D-001 | 分頁初始化 | 通過 | `direct-quick` + `oracle` | `ui-decision-desk` 與 decision desk service tests。 | 保留 quick bridge。 |
| D-002 | 更新決策摘要 | 通過 | `direct-quick` + `oracle` | snapshot / dashboard service tests。 | 保留 quick bridge。 |
| D-003 | as_of_date / quality / warnings | 已修正待驗證 | `direct-quick` + `oracle` | decision desk view / service serialization tests。 | 人工確認 warning 中文可讀。 |
| D-004 | Market Regime 摘要 | 需確認 | `direct-quick` + `direct-full` + `oracle` | decision desk + market regime bridge。 | Data date 與真實品質仍人工。 |
| D-005 | Market Breadth | 需確認 | `oracle` + `direct-quick` | decision desk service tests 覆蓋 section 降級與呈現。 | 人工看實際資料內容。 |
| D-006 | Sector Rotation | 需確認 | `oracle` + `direct-quick` | decision desk service tests。 | 人工看產業名稱與排序語意。 |
| D-007 | Relative Strength / Liquidity | 需確認 | `oracle` + `direct-quick` | decision desk service tests。 | 人工看低流動性 / 歷史不足提示。 |
| D-008 | Watchlist Trigger | 需確認 | `oracle` + `direct-quick` | watchlist trigger service tests + decision desk rendering。 | 人工確認候選池真實狀態。 |
| D-009 | Portfolio Alert / Why Not | 需確認 | `oracle` + `direct-quick` + `candidate` | decision risk prompt / portfolio alert attribution tests。 | Portfolio 真實狀態仍人工。 |

## Research Lab / 策略回測

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| B-001 | 單股回測模式 | 通過 | `direct-full` | `ui-research-workflow`。 | 保留 full bridge。 |
| B-002 | 批次股票回測模式 | 通過 | `direct-full` | `ui-research-workflow`。 | 保留 full bridge。 |
| B-003 | 固定組合回測模式 | 通過 | `direct-full` + `oracle` | fixed basket metadata tests。 | 完整 portfolio 成交仍非本項。 |
| B-004 | 推薦系統回放模式 | 已修正待驗證 | `direct-full` | `ui-research-workflow` 覆蓋 `B-004`。 | 保留 full bridge。 |
| B-005 | 策略研究模式 | 已修正待驗證 | `direct-full` | `ui-research-workflow` 覆蓋 `B-005`。 | 保留 full bridge。 |
| B-006 | 儲存 Preset | 通過 | `manual-only` + `oracle` | preset / config contract 可輔助。 | 寫入設定需 tmp path test 才能自動化。 |
| B-007 | 載入 Preset | 已修正待驗證 | `direct-full` | Research workflow mode / combobox tests。 | 保留 full bridge。 |
| B-008 | 刪除 Preset | 通過 | `write-risk-manual` | 涉及設定刪除。 | 只可測取消 / tmp path。 |
| B-009 | 單一股票輸入 | 通過 | `direct-full` | Research workflow tests。 | 保留 full bridge。 |
| B-010 | 選股清單輸入 | 通過 | `direct-full` | Watchlist handoff / batch tests。 | 保留 full bridge。 |
| B-011 | 選股清單管理 CRUD | 通過 | `manual-only` + `candidate` | candidate watchlist tests 輔助。 | CRUD 寫入需 tmp path。 |
| B-012 | 初始資金 | 已修正待驗證 | `direct-full` + `oracle` | Research workflow + weight / sizing service tests。 | 保留 full bridge。 |
| B-013 | 手續費 / 滑價 bps | 通過 | `oracle` | backtest metadata / cost tests。 | UI 回歸可補。 |
| B-014 | 成交價假設 | 通過 | `oracle` + `direct-full` | broker simulator / close warning tests。 | 保留 evidence。 |
| B-015 | 停損停利百分比 | 通過 | `oracle` | backtest domain tests。 | UI direct 未逐 ID。 |
| B-016 | ATR 倍數停損停利 | 通過 | `oracle` | backtest domain tests。 | UI direct 未逐 ID。 |
| B-017 | 全倉 sizing | 通過 | `oracle` | weight / portfolio replay tests。 | 保留 oracle。 |
| B-018 | 固定金額 sizing | 通過 | `oracle` | sizing / replay tests。 | 保留 oracle。 |
| B-019 | 風險百分比 sizing | 通過 | `oracle` | sizing / ATR interaction evidence。 | 保留 oracle。 |
| B-020 | 最大持倉數 | 已修正待驗證 | `direct-full` | `test_backtest_view_max_positions_uses_zero_as_unlimited`。 | 保留 full bridge。 |
| B-021 | 權重模式切換 | 通過 | `oracle` + `direct-full` | recommendation weight contract / workflow tests。 | 保留 evidence。 |
| B-022 | 允許加碼 | 通過 | `oracle` | backtest logic tests。 | UI manual spot check。 |
| B-023 | 重新進場 / 冷卻期 | 通過 | `oracle` | backtest logic tests。 | UI manual spot check。 |
| B-024 | 漲跌停限制 | 通過 | `oracle` | backtest execution constraint tests。 | 保留 oracle。 |
| B-025 | 成交量約束 / 最大參與率 | 通過 | `oracle` | portfolio replay credibility tests。 | 保留 oracle。 |
| B-026 | 策略下拉與參數 | 已修正待驗證 | `direct-full` | Research workflow combobox / mode-driven UI tests。 | 保留 full bridge。 |
| B-027 | 參數最佳化 | 需確認 | `direct-full` + `manual-only` | optimization panel / preflight UI tests；真實大型掃描仍 manual。 | 不把 heavy scan 放 runner。 |
| B-028 | 套用選中參數 | 通過 | `direct-full` | optimization fixed values tests。 | 保留 full bridge。 |
| B-029 | Train-Test Split | 已修正待驗證 | `direct-full` + `oracle` | Train-Test summary sample warning tests。 | 保留 full bridge。 |
| B-030 | Walk-forward | 已修正待驗證 | `direct-full` + `oracle` | walk-forward service / summary warning tests。 | 保留 full bridge。 |
| B-031 | 推薦回放 Top N / 候選上限 / 持有天數 | 通過 | `oracle` + `direct-full` | recommendation replay parameter evidence。 | 保留 evidence。 |
| B-032 | 推薦回放頻率 / 資金配置 | 已修正待驗證 | `oracle` + `direct-full` | replay service / UI group tests。 | 保留 evidence。 |
| B-033 | 執行實驗 | 已修正待驗證 | `direct-full` + `manual-only` | UI worker contract tests；真實長任務需人工。 | 不放 heavy execution gate。 |
| B-034 | 取消執行 | 通過 | `direct-full` + `oracle` | optimization worker control / cancellation evidence。 | 保留 full bridge。 |
| B-035 | 保存結果 | 已修正待驗證 | `candidate` + `oracle` | `tests/test_ui_qt_research_run_save.py` 是 candidate；service oracle 覆蓋 stale guard。 | 可評估 promotion。 |
| B-036 | 升級為策略版本 | 已修正待驗證 | `oracle` + `write-risk-manual` | lifecycle / gate service tests；實際策略版本寫入高風險。 | 不自動升級。 |
| B-037 | 匯出 Excel 報告 | 通過 | `candidate` | `tests/test_ui_qt_report_export.py` 是 candidate。 | 可評估 tmp output promotion。 |
| B-038 | 結果圖表 | 已修正待驗證 | `direct-full` | `ui-research-workflow` 覆蓋 `B-038`。 | 視覺 pixel QA 尚未。 |
| B-039 | 歷史與比較 | 已修正待驗證 | `direct-full` | `ui-research-workflow` / `ui-run-registry-compare` 覆蓋。 | 保留 full bridge。 |
| B-040 | 批次結果 | 已修正待驗證 | `direct-full` + `candidate` | Research workflow + report export candidate。 | 匯出仍 candidate。 |
| B-041 | 推薦回放結果 | 已修正待驗證 | `direct-full` | `ui-research-workflow` / `ui-run-registry-compare` 覆蓋。 | 保留 full bridge。 |
| B-042 | Registry 比較 | 已修正待驗證 | `direct-full` + `oracle` | `ui-run-registry-compare` 與 comparison service oracle。 | 保留 full bridge。 |

## 推薦分析

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| R-001 | 新手 / 進階模式切換 | 通過 | `candidate` | recommendation UI candidate tests。 | 評估 candidate promotion。 |
| R-002 | Regime 顯示 / 自動偵測 | 已修正待驗證 | `candidate` + `oracle` | recommendation profile / regime tests + market regime oracle。 | 人工確認目前資料。 |
| R-003 | 一鍵套用建議 Profile | 已修正待驗證 | `candidate` | profile combo candidate tests。 | 評估 candidate promotion。 |
| R-004 | 選擇策略風格 | 已修正待驗證 | `candidate` | `tests/test_ui_qt_recommendation_profiles.py`。 | 評估 promotion。 |
| R-005 | 策略傾向偏好設定 | 已修正待驗證 | `candidate` + `oracle` | recommendation service / profile tests。 | 需確定偏好語意。 |
| R-006 | 技術指標勾選 / 參數 | 通過 | `oracle` | recommendation service fail-closed tests。 | UI direct 未納入。 |
| R-007 | 圖形模式勾選 / 參數 | 通過 | `oracle` | pattern / no-look-ahead tests。 | UI direct 未納入。 |
| R-008 | 最小漲幅 | 通過 | `oracle` | recommendation service tests。 | 保留 oracle。 |
| R-009 | 最小成交量比率 | 已修正待驗證 | `oracle` | recommendation service tests。 | 人工確認 UI 單位。 |
| R-010 | 產業篩選 | 通過 | `oracle` | service / data tests。 | UI direct 未納入。 |
| R-011 | 固定門檻 | 已修正待驗證 | `candidate` + `oracle` | threshold mode combobox tests。 | 評估 promotion。 |
| R-012 | 百分位排名 | 已修正待驗證 | `candidate` + `oracle` | percentile ranker / threshold mode tests。 | 保留 look-ahead guard。 |
| R-013 | 執行推薦分析 | 通過 | `oracle` + `manual-only` | service tests；真實背景執行需人工。 | 不放 full runner heavy task。 |
| R-014 | 推薦理由詳情 | 已修正待驗證 | `candidate` + `oracle` | reason / next steps copy tests。 | 人工看文案可讀性。 |
| R-015 | 保存結果 | 已修正待驗證 | `oracle` + `write-risk-manual` | service snapshot tests；實際保存寫入。 | 僅 tmp path 可自動化。 |
| R-016 | 加入候選池 | 已修正待驗證 | `candidate` | recommendation next steps / watchlist candidate tests。 | 評估 promotion。 |
| R-017 | 送 Research Lab 批次回測 | 已修正待驗證 | `direct-full` | `ui-research-workflow` 覆蓋 `X-004` 相關 handoff。 | 保留 full bridge。 |
| R-018 | 送 Research Lab 推薦回放 | 通過 | `direct-full` | Research workflow replay handoff tests。 | 保留 full bridge。 |
| R-019 | 匯出 Excel | 通過 | `candidate` | `tests/test_ui_qt_report_export.py`。 | 可評估 tmp output promotion。 |
| R-020 | 右鍵記錄到持倉 / 加入候選池 | 已修正待驗證 | `candidate` + `write-risk-manual` | recommendation portfolio result tests；持倉寫入高風險。 | 記錄持倉仍人工 / tmp path。 |

## 觀察清單

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| W-001 | 候選池刷新 | 通過 | `candidate` | watchlist candidate pool copy tests。 | 評估 promotion。 |
| W-002 | 新增股票 | 已修正待驗證 | `direct-full` | `test_watchlist_view_manual_add_resolves_stock_name_and_rejects_unknown`。 | 保留 full bridge。 |
| W-003 | 移除選中 | 通過 | `candidate` | watchlist candidate tests 可輔助。 | 需 tmp state。 |
| W-004 | 清空候選池 | 通過 | `write-risk-manual` | 有不可逆確認。 | 只測取消 / tmp path。 |
| W-005 | 送 Research Lab 批次回測 | 已修正待驗證 | `direct-full` | `test_watchlist_view_batch_backtest_button_state`。 | 保留 full bridge。 |
| W-006 | 保存為選股清單 | 通過 | `write-risk-manual` | 寫入 universe。 | tmp path 自動化候選。 |
| W-007 | 右鍵移除選取 | 通過 | `candidate` | watchlist candidate tests。 | 需 promotion。 |
| W-008 | 選股清單刷新 | 通過 | `manual-only` | 未納入 bridge。 | 候選 UI test。 |
| W-009 | 載入到候選池 | 通過 | `candidate` | watchlist candidate tests。 | 需 promotion。 |
| W-010 | 新增選股清單 | 通過 | `write-risk-manual` | Universe 寫入。 | tmp path 測試。 |
| W-011 | 編輯選股清單 | 通過 | `write-risk-manual` | Universe 寫入。 | tmp path 測試。 |
| W-012 | 刪除選股清單 | 通過 | `write-risk-manual` | Universe 刪除。 | 只測取消 / tmp path。 |
| W-013 | 跨頁同步 | 通過 | `direct-full` + `candidate` | `ui-research-workflow` watchlist handoff。 | 保留 full bridge。 |

## 持倉管理

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| P-001 | 手動記錄交易 | 需確認 | `candidate` + `write-risk-manual` | `tests/test_ui_qt_portfolio_view.py` 是 candidate；實際交易記錄寫入。 | 不進 runner；tmp path promotion 後再評估。 |
| P-002 | 新增日記 | 通過 | `write-risk-manual` | 寫入 journal。 | 只可 tmp path。 |
| P-003 | 整理刷新 | 通過 | `candidate` | portfolio view candidate tests。 | 評估 promotion。 |
| P-004 | 清空全體數據 | 通過 | `write-risk-manual` | 高風險刪除。 | 只測取消流程。 |
| P-005 | 持倉列表 | 需確認 | `candidate` + `oracle` | portfolio active summary tests。 | 評估 promotion。 |
| P-006 | 為此部位寫日記 | 通過 | `write-risk-manual` | 寫入 journal。 | tmp path。 |
| P-007 | 只查看此股交易歷史 | 通過 | `candidate` | trade history filter tests。 | 評估 promotion。 |
| P-008 | 顯示全部交易歷史 | 未通過 | `candidate` | trade history clear filter test exists。 | 母檔狀態需重驗後更新。 |
| P-009 | 檢視交易明細 | 通過 | `candidate` | portfolio view tests。 | 評估 promotion。 |
| P-010 | 刪除此交易紀錄 | 通過 | `write-risk-manual` | 刪除交易記錄。 | 只測取消 / tmp path。 |
| P-011 | 檢視日誌 | 通過 | `candidate` | portfolio view tests。 | 評估 promotion。 |
| P-012 | 刪除此篇日記筆記 | 通過 | `write-risk-manual` | 刪除 journal。 | 只測取消 / tmp path。 |
| P-013 | 目前價格 / 未實現損益 | 需確認 | `candidate` + `oracle` | portfolio monitoring tests。 | Data freshness 人工確認。 |
| P-014 | 來源追溯 | 需確認 | `candidate` + `oracle` | provenance / lifecycle review tests。 | 保留 candidate。 |
| P-015 | 籌碼風險與分點明細 | 需確認 | `candidate` + `oracle` | portfolio condition / broker flow oracle。 | 真實資料品質人工。 |
| P-016 | 下鑽詳細主力流向 | 需確認 | `direct-full` + `candidate` | `ui-smart-money-flow` + portfolio drill-down candidate。 | 可評估 candidate promotion。 |
| P-017 | 推薦 / 回測記錄到持倉 | 未通過 | `candidate` + `write-risk-manual` | recommendation / research provenance tests；持倉寫入高風險。 | 母檔需重驗 Decimal sanitizer 後更新。 |

## Runtime Observatory

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| RT-001 | 分頁載入 | 通過 | `candidate` | `tests/test_ui_qt_runtime_view.py`。 | 評估 promotion。 |
| RT-002 | Objective | 需確認 | `candidate` | runtime view Chinese labels tests。 | 人工確認語意。 |
| RT-003 | Task Workflow Status | 需確認 | `candidate` | runtime idle / halted rendering tests。 | 人工確認 FSM 說明。 |
| RT-004 | Overall System State / Health | 需確認 | `candidate` | runtime health tests。 | 人工確認治理指標可讀。 |
| RT-005 | Last Critical Violation | 需確認 | `candidate` | runtime event / empty state tests。 | 人工確認事件語意。 |
| RT-006 | Append-only Event Stream | 需確認 | `candidate` | runtime event stream tests。 | 評估 promotion。 |

## 全域與跨工作區流程

| ID | 功能 | 母檔狀態 | Coverage | 目前證據 | 後續動作 |
|---|---|---|---|---|---|
| X-001 | 啟動主程式 | 通過 | `manual-only` + `report-only` | D-2 MainWindow smoke plan 只是 metadata，未執行。 | 需明確授權才可做受控 MainWindow smoke。 |
| X-002 | Tab 順序 | 通過 | `manual-only` | 需完整 MainWindow。 | 可成為 D-2 後續執行項。 |
| X-003 | 市場觀察自動載入 | 需確認 | `manual-only` + `oracle` | 資料與 service evidence 可輔助，實際切頁載入需 MainWindow。 | 後續受控 smoke。 |
| X-004 | 推薦到回測 | 通過 | `direct-full` | `ui-research-workflow` 覆蓋 `X-004`。 | 保留 full bridge。 |
| X-005 | 推薦 / 回測到持倉 | 未通過 | `candidate` + `write-risk-manual` | portfolio / recommendation provenance candidate tests。 | 母檔需重驗後更新。 |
| X-006 | 持倉到主力流向 | 需確認 | `direct-full` + `candidate` | smart money direct bridge + portfolio candidate。 | 可評估 promotion。 |
| X-007 | Session context strip | 通過 | `manual-only` | 需要 MainWindow / viewport 視覺判讀。 | D-3 viewport plan 後續。 |

## 下一步建議

1. 不要把本 mapping 當作 release gate；它只是逐列覆蓋視圖。
2. 優先把 `candidate` 且非 write-risk 的項目分批評估是否能升級到 full direct bridge。
3. `write-risk-manual` 項目只能走 tmp path / mock / explicit dry-run，且不得自動 confirm。
4. 對 `manual-only` 且涉及畫面可讀性的項目，下一步應是受控 D-2 / D-3 設計，而不是直接接入 quick/full runner。
5. `FULL_APP_HEALTHCHECK_2026_06_16.md` 的 pass/fail 狀態仍以人工重驗為準；本文件只描述目前自動化與證據覆蓋程度。
