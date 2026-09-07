# 觀察清單分析與 ML 可見性驗收

## 範圍與回滾清單

| 檔案 | 變更 | 回滾方式與風險 |
|---|---|---|
| app_module/watchlist_analysis_service.py | 唯讀保存推薦 → 個股摘要 DTO | 移除本輪新增檔前先撤回 UI import；不涉及資料遷移 |
| ui_qt/views/watchlist_view.py | 清單股票預覽、非同步推薦摘要、個股下鑽 | 只撤回本輪 hunk；保留八卡既有變更 |
| ui_qt/views/smart_money/smart_money_flow_view.py | 任意個股分點查詢、初次非同步載入後恢復定位 | 只撤回本輪 requested stock 與 fallback hunk |
| ui_qt/main.py | 觀察清單訊號接入既有主力流向導覽 | 只撤回 stockAnalysisRequested 接線 |
| tests/test_watchlist_stock_analysis_navigation.py | 排序、來源日期、唯讀、非同步、清單預覽與首次載入測試 | 僅本輪新增檔，先確認未被其他工作接續 |
| APPLICATION_MANUAL／PROJECT_SNAPSHOT | 實際操作與 dated ML 查核 | 逐段撤回本輪新增說明，不整檔還原 |

未執行 rollback、stage、commit、正式資料寫入、訓練或 promotion。原有工作樹變更保留。

## 需求與證據

- 清單不再只顯示名稱：選清單立即顯示個股代號／名稱，經 UniverseService 與 WatchlistService 讀取；測試確認不改候選池。
- 個股分析串聯：單擊候選股或預覽股，背景讀取已保存推薦分數、理由、日期與來源；來源 ID 存在則精確查詢，無 ID 僅讀最近保存結果，不宣稱全市場分析。日期缺失／未來、未入選、缺件均揭露。
- 雙擊／按鈕／選單接至既有主力流向；任意未入榜股票仍經 App service 查分點，初次 dashboard 回傳後保留所選股票。沒有資料不補造分數。
- 排序使用目前模型列；快速切股、刷新與關閉均透過 request ID 拒絕舊摘要回呼。
- ML 架構已查原始碼：ml_module 訓練、App 推論轉 bp 提案、Portfolio allocation promotion 檢查；UI Research Console 只讀 sanitized projection。
- 實際 process 的 Console projection 日期 2026-07-14；服務 inspect 回報 degraded／projection_stale。7/14 是來源日期，不是假定最新訓練日期。
- 2026-09-07 UTC 重新執行 inspect_ml_formal_input_readiness，training-as-of=2026-09-07T00:00:00+08:00；ready=0/3、waiting_for_formal_inputs。三項 prospective manifest 未發布，alpha=0、formal_oos=false、broker=false。報告 output/watchlist_analysis/ml_readiness_current.json；只寫本地 QA 產物。

## 驗證

使用 .\.venv\Scripts\python.exe；UI pytest 設定 QT_QPA_PLATFORM=offscreen，DATA_ROOT／OUTPUT_ROOT 指向 output/watchlist_analysis 隔離根，PROFILE=test。

- pytest：test_watchlist_stock_analysis_navigation、test_ui_qt_smart_money_flow_view、test_ui_qt_decision_desk_main_integration、test_ui_qt_watchlist_candidate_pool_copy_text、test_ui_qt_update_view_workbench，106 passed；使用 -q -o addopts= -p no:cacheprovider。
- qa_validate_update_tab.py：25 passed、0 failed、4 明列下載／合併 skip。
- 全指定模組 mypy：533 files success；既有兩則 untyped-body notes。
- check_financial_float_boundaries.py、check_look_ahead_bias.py、改動 Python py_compile 通過。
- 套用 apply_app_theme 的 Watchlist 隔離 fixture 截圖已人工檢視：output/watchlist_analysis/watchlist_preview.png，繁體中文及清單／摘要區可讀。不是正式資料或整個 MainWindow 人工驗收。

ML 尚未被本輪啟用；需先補具備合法時間與來源的正式三項 input，並經既有訓練、評估、promotion 流程。Console 過期投影需受控重新產出，不能改時間戳假裝更新。
