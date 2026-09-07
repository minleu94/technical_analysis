# TASK-LOOP-07 DESK 交接

日期：2026-09-06。狀態：工程驗收完成；08-B 主畫面組裝與集中文件整合待承接；正式候選池 migration／ledger 切換未授權、未執行。

## 2026-09-06 同程序 QA 清理修正

主控八卡合併驗收在 `test_decision_qa_failure_is_nonzero_and_preserves_environment` 的 QA finally 執行全域 `gc.collect()` 時發生 Windows fatal `0xc0000374`。本卡以同一組八卡、同一 pytest 程序重現，exit=`-1073740940`，紀錄 `output/master_goal/TASK-LOOP-07/cleanup_baseline.log`。這定位到不當的全程序回收觸發點；不宣稱已定位其他測試遺留原生物件的內部損壞根因。

本 QA 不建立 QApplication、Qt widget、worker 或 thread，無權清理其他測試的 Qt 物件。已移除 gc import／collect，改以 ExitStack 管理本 QA 資源：推薦 repository 模組的局部 sqlite3 借用名稱暫時提供 connect 代理，每次仍呼叫原本真實 SQLite connect，立即註冊 close，涵蓋 writer 建構與保存的成功／例外；標準庫 sqlite3.connect 不變，scope 退出還原模組引用。既有 watchlist、snapshot、saved recommendation reader、06 ledger repository 已有明確 closing／finally close。

TWStockConfig 的共用 logger 在本 QA 期間暫卸既有 handlers、停用 propagate；退出時只關閉新 handlers，完整恢復借用的 handlers、level、propagate。借用 handler 不關閉、不接收本 QA 訊息。資源關閉先於環境還原及 TemporaryDirectory 退出；未使用 subprocess、skip、disable-GC 或忽略清理錯誤。

只修改 `scripts/qa_validate_decision_loop.py`、`tests/test_task_loop_07_contract.py` 及本交接；base／current SHA=`2bfe86879760966560d36b5e1aecbccd23c4c69b`，未修改正式 writer、Qt、其他卡或正式資料，未 stage／commit／push。

| 最後驗收 | 結果 |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/test_task_loop_07_contract.py -q -o addopts= -p no:cacheprovider` | exit 0，20 passed；包含本 QA 真實七場景成功與故障後資源釋放 |
| 同 interpreter，`tests/test_task_loop_01_contract.py tests/test_task_loop_02_contract.py tests/test_task_loop_03_contract.py tests/test_task_loop_04_contract.py tests/test_task_loop_05_contract.py tests/test_task_loop_06_contract.py tests/test_task_loop_07_contract.py tests/test_task_loop_08_contract.py -q -o addopts= -p no:cacheprovider` | 單一 pytest 程序，exit 0，119 passed、0 skips；2 個既有 RSI dtype FutureWarning |
| `-m py_compile scripts/qa_validate_decision_loop.py tests/test_task_loop_07_contract.py` | exit 0 |

仍使用本卡隔離雙根／PROFILE=test／offscreen；紀錄為 `cleanup_07.log`、`cleanup_all_contracts.log`。新故障案例保留開啟連線後拋錯，驗證原錯誤與非零碼、連線已關、temp 根已移除、既有外部 handler 未被寫入／關閉、logger 與模組引用完整恢復；成功案例直接在測試程序中跑七場景並驗證 temp 根消失。回復只能移除本次 QA 資源 scope、兩個新增案例與本段 hunks，保留 03／07 其他功能；不應重新採用已證實可令八卡程序崩潰的全域 gc 清理。

來源鏈補驗（同日）：03／07 最小 follow-up 已完成 Recommendation persist 真實 result_id → current_result_id → Watchlist source_id。新分析清除舊 ID，未保存結果保持空值；DataFrame 的 pandas 缺值安全回落 result_id 或空值。新增六個跨 UI／App 保存重開與身份生命週期案例。最新 focused＋強制更新共 131 passed（50＋81）、0 skips；mypy 532 files、兩防禦 guard、py_compile、diff check 均 exit 0；更新 QA 25 passed／0 failed／4 明示 skips。完整命令、4 個 Python 改檔與回復說明見 TASK_LOOP_03_HANDOFF 的「來源 ID 接線補驗」；原始紀錄為本卡 `identity_*.log`。本補驗沒有改 main／08 或正式資料。

## 範圍與工作樹

- base SHA／驗收時 current SHA 同為 `2bfe86879760966560d36b5e1aecbccd23c4c69b`；未 stage、commit、push。
- 共用工作樹已有其他卡修改；本卡只改下表白名單，沒有覆寫 01–06／08 的工作。
- 已讀 AGENTS、共用治理、Playbook 共同契約與本卡、02／03 handoff，並消費 06 凍結的 App read-model；先查既有 graphify 圖譜再以實碼確認。
- pytest 雙根：`output/master_goal/TASK-LOOP-07/data`、`output/master_goal/TASK-LOOP-07/artifacts`，PROFILE=test、QT_QPA_PLATFORM=offscreen；TWStockConfig 的 test 解析會追加 `_test`。專用 QA 自建 TemporaryDirectory，明確傳入雙根及 profile=unit，環境值 PROFILE=test；其 config 實際根位於臨時 data／artifacts，報告列出來源 hash。

| 實際改檔 | 內容 |
|---|---|
| `app_module/watchlist_service.py` | App 股票名稱唯讀查詢；可注入 SQLite repository；JSON 舊資料相容、損毀檔只報錯、原子 replace；source_id；revision 衝突傳出 |
| `data_module/watchlist_repository.py`（新增） | schema 1，watchlists payload／revision／source_hash；明確初始化，query-only 讀取，transaction／revision 保存及移除 |
| `data_module/watchlist_migration.py`（新增） | watchlist-copy.v1；只處理 caller 指定 sandbox 內 JSON 副本，內容／身份／hash／冪等比對，不覆寫差異目標 |
| `app_module/watchlist_trigger_service.py` | added_at 截止、未來來源拒絕、Decimal 分數解析、全未知與有效空池區分、前期未知診斷 |
| `app_module/decision_desk_dtos.py` | 可選 RecommendationDeskSummary、DecisionDeskSnapshot.recommendations／source_lineage；既有 schema_version=2 不變，additive fields |
| `app_module/decision_desk_service.py` | TASK-02 Regime DTO 品質／實際日；section 日期防護；已保存推薦只讀 provider；06 ledger read-model adapter；完整來源鏈 |
| `app_module/decision_desk_snapshot_repository.py` | 沿既有 SQLite schema 保存完整 loop payload；generated_at 不參與身份 hash；payload 重載、typed 推薦／來源鏈重載；所有連線明確 close |
| `app_module/workbench_read_only_composer.py` | 保留 snapshot warnings、推薦 context 與來源鏈 |
| `ui_qt/views/watchlist_view.py` | 股票名稱透過 App port，移除 UI DBManager／CSV 讀取；跨頁輸入 source_id 保留 |
| `ui_qt/views/decision_desk_view.py` | request generation／日期隔離過期結果與錯誤；pending 最新刷新；未知風險／觸發數文字；保存推薦來源文字 |
| `scripts/qa_validate_decision_loop.py`（新增） | 七個離線閉環場景、明確非零失敗、雙根／環境還原、temp 資源關閉 |
| `tests/test_task_loop_07_contract.py`（新增） | 13 個契約案例（含參數化）；migration、讀取不寫、日期、future-append、snapshot、stale callback、QA 故障碼 |
| `tests/test_decision_desk_service.py` | DTO additive 欄位預期同步 |
| 本交接檔（新增） | 契約、證據、08-B 接點與精確文件補丁 |

未改 main、factory、Workbench source service、storage DTO、Portfolio、Recommendation 計算、Scoring、撮合、帳務或正式資料。

## 凍結契約與日期語意

1. WatchlistService 預設沿用 JSON；注入 WatchlistRepository 後以候選 SQLite 為該實例 SSOT。migration 不是自動啟動功能，正式 JSON 不會被轉換。JSON 損毀不再自動備份改名／換空池；重開保留資料並回報原錯誤。source_id 是選填，既有記錄為空；不猜造推薦身份。
2. provider 對 `added_at > as_of_date` 的項目排除；這是目前候選池的日期截止，沒有已刪除項目的歷史事件帳，不代表能重建歷史 watchlist membership。Trigger 是日資料研究提示；前期分數未知仍可列為新候選，但帶 `watchlist_trigger_previous_unknown` 並降為 estimated，不宣稱已驗證的即時突破。全數分數未知為 missing／trigger_count=None，有效空候選池 observed／0。
3. Builder 對未來／缺日期 section 清除值並標 missing；較舊實際日期保留並 degraded，禁止冒充當日 observed。Regime 優先消費 detect_regime_dto 的 effective_date、quality、warnings、source metadata，不由 Desk 重算市場。
4. SavedRecommendationDeskProvider 只以 mode=ro／query_only 讀既有 runs metadata 與範圍內 JSON；選取 run_context.as_of_date 不晚於決策日的最近結果，保留 recommendation-context.v1 的 Profile、fingerprint、Why Not 品質資訊。缺舊 context／來源損毀明確缺資料，不自行評分。新增未來結果不改歷史選取；未使用只取最新 N 筆的捷徑。
5. PortfolioLedgerDeskProvider 只呼叫已注入的 PortfolioService.build_ledger_read_model，source_lineage.portfolio_ledger 保留 portfolio_id、namespace、as_of_date、source_ledger_id/hash、event_count、quality、missing_inputs、warnings、candidate_only 及 Decimal 字串投影。它不取未驗證的現價；有持倉缺行情時 blocked，Desk 清除安全等級，沒有替代 06 的帳務或風控。未來事件追加不改既有決策日的 read-model hash。
6. DecisionDeskSnapshotRepository.save_loop_snapshot 沿用 decision_desk_snapshots schema 1，source_version=decision-loop.v1、builder_version=DecisionDeskSnapshotBuilder:loop-v1；完整 snapshot.to_dict 放在 metadata.loop_snapshot，時間戳單獨保存、不參與 hash。load_loop_snapshot_payload 提供完整序列化 round-trip；load_loop_snapshot 在既有 typed section converter 上補回推薦／來源鏈。後者仍沿用 legacy converter 對 action_summary／sector_focus／stock_focus／market_data_visibility 未還原的限制，完整核對應用 payload 方法。
7. 不產生成交、調倉、promotion、ML flag、Formal credit 或 production readiness。自然日期、財報 available_date 與 T+1 成交由 02／03／04 契約承接；Desk 不重新解釋為可成交訊號。

## 驗收證據

全部 pytest 使用 `.\.venv\Scripts\python.exe -m pytest`，加 `-q -o addopts= -p no:cacheprovider`，雙根如上；本卡無 skips。

| 檢查 | 命令／檔案 | 結果 |
|---|---|---|
| 聚焦及既有回歸 | `tests/test_watchlist_trigger_service.py tests/test_ui_qt_watchlist_candidate_pool_copy_text.py tests/test_decision_desk_service.py tests/test_decision_desk_dashboard_service.py tests/test_decision_desk_dto_contract.py tests/test_decision_desk_ui_contract.py tests/test_ui_qt_decision_desk_view.py tests/test_ui_qt_decision_desk_main_integration.py tests/test_task_loop_07_contract.py tests/test_workbench_read_only_composer.py tests/test_decision_desk_snapshot_repository.py` | exit 0，100 passed；包含唯一 Desk 導覽既有契約 |
| 專用 QA | `.\.venv\Scripts\python.exe scripts/qa_validate_decision_loop.py --output-json output/master_goal/TASK-LOOP-07/qa.json` | exit 0，7 scenarios，0 skips；failure 非零及環境還原另有 fault injection |
| 強制更新 UI | `tests/test_ui_qt_update_view_workbench.py` | exit 0，81 passed |
| 強制更新 QA | `.\.venv\Scripts\python.exe scripts/qa_validate_update_tab.py` | exit 0，25 passed／0 failed／4 明示 skips；不宣稱全覆蓋 |
| 全模組型別 | `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | exit 0，532 files |
| 金融／日期防線 | `.\.venv\Scripts\python.exe scripts/check_financial_float_boundaries.py`、同 interpreter 的 `scripts/check_look_ahead_bias.py` | 均 exit 0 |
| 語法／diff | 本卡 13 個 Python 檔 `-m py_compile`；本卡路徑 `git diff --check` | exit 0 |

原始紀錄在 `output/master_goal/TASK-LOOP-07/`：focused.log、mypy.log、qa.json、qa.log、update_pytest.log、update_qa.log；原始輸出不提交。

最後專用 QA 的 JSON 副本 SHA-256=`4cf2bc868244471bbeae5a5e94090cd5baa0a1f4389dc4a9615d6674f7a4ebf8`；已知推薦 JSON=`b20cb2cd88c7126769adee0becb71711aa0e2b714bebe36dfa91981b539a6cbf`。決策日 2026-05-20、市場 fallback 2026-05-19、未來推薦／ledger 為 2026-06-01；所有被讀的來源 hash 前後相同。SQLite 含建立時間，跨次 hash 可能不同；驗證的是同一次 observer 前後不變，不把 fixture hash 當正式來源接受證據。

QA 曾發現 SQLite context manager 不自動 close 的 Windows temp 清理問題。本卡修正 snapshot repository；06 owner 已修正 ledger repository並交叉驗證。後續同程序驗收進一步移除全域 gc，資源清理已改為上方「同程序 QA 清理修正」所述的確定性 scope。

## 08-B 接線與待辦

- ui_qt/main.py 的既有 `_create_decision_desk_builder`，組裝後注入 `SavedRecommendationDeskProvider(self.config)` 到 `builder.recommendation_provider`，保持現有唯一 widget。07 不擅改 main／factory。
- 只在明確注入候選 ledger 的 PortfolioService 存在時，注入 PortfolioLedgerDeskProvider；不得為補齊 UI 初始化正式 ledger writer、套 migration 或用今天價格補歷史行情。
- 新完整快照需呼叫 save_loop_snapshot／load_loop_snapshot_payload；舊 Workbench source service 仍直接呼叫 StoredDecisionDeskSnapshot.to_decision_desk_snapshot，會遺失新增來源欄位。07 未越界修改該唯讀檔；若 08-B 要正式使用完整保存來源，先按共享 owner 規則安排該接點的範圍，再以本卡 payload 契約驗證。
- Recommendation View「加入候選」來源 ID 缺口已由同日 03／07 follow-up 修正，真實 persist 回傳 ID 可保存到候選池；未保存或新一輪分析保持空值。此項已完成，不再是 08-B 待接點。
- QA inventory 由 08-B 登錄 `tests/test_task_loop_07_contract.py`；本卡未改 inventory。
- 以上是中央接線與正式 acceptance 的未完成條件；本卡隔離工程驗收不等於已整合或可正式 migration。

## 集中文件精確補丁（交 08-B）

`docs/07_guides/APPLICATION_MANUAL.md` 7.1「候選池操作」末新增：

> 候選池的股票名稱查詢統一透過應用服務。加入時若提供來源 ID，重開及隔離 SQLite 副本會保留該 ID；重複股票不新增。舊 JSON 損毀時會顯示錯誤並保留原檔，請先檢查副本，不再自動清空。SQLite 遷移工具只用於指定 sandbox 的副本驗證，不會於 UI 啟動時自動轉換正式候選池。

> 先保存推薦，再加入候選，可保留該保存結果的來源 ID；未保存或重新分析後的結果沒有保存身份，候選來源 ID 保持空值。

同文件第 8 節「每日決策」結果判讀末新增：

> 市場與其他區塊顯示實際資料日期；較舊資料會標示降級，未來或缺日期資料保持未知。候選池有效空集合與來源缺失分開呈現；前期分數不足的新候選附有估計提示，並非即時突破證明。刷新期間改變決策日，舊請求結果與錯誤不會蓋掉新日期。已注入的保存推薦顯示來源 ID、決策日與品質；候選 ledger 缺行情時不顯示安全等級。這些內容為唯讀研究輸入，不會產生成交或調倉。

`docs/01_architecture/system_architecture.md` 的 Decision Desk／Watchlist 段落新增：

> TASK-07 建立可注入的 watchlist SQLite 副本 repository，預設正式 JSON 相容路徑保持不變。UI 無資料庫或 CSV 股票名稱查詢；App provider 以只讀方式聚合已保存推薦及候選 ledger read-model，DecisionDeskSnapshot additive recommendations／source_lineage 保存日期、品質與來源 hash。完整 loop snapshot 沿既有 SQLite schema 的 metadata 保存；原始 typed storage converter 與 Workbench source 的接線限制須保留在整合驗收中。

`docs/01_architecture/target_system_architecture.md` Current→Target 缺口新增：

> 候選池 SQLite 與 ledger adapter 已在合成雙根中驗收；正式 migration、歷史候選池 membership 重建、已存快照的完整 typed hydration 與正式來源切換仍需獨立範圍／Gate。不得把候選工程完成推進成來源 accepted 或 production readiness。

Snapshot／Roadmap Hub／6M／Index 的 TASK-07 摘要可記「隔離工程驗收完成：100 focused、7 QA；08-B 組裝／集中文件待整合」，不得改 V4 Formal／production 狀態。

## 回復計畫

| 範圍 | 風險與回復 |
|---|---|
| 本卡程式／測試 | 以本表逐檔 diff hunk 移除新增 adapter、DTO 欄位及行為修改；保留其他卡及使用者修改，不整樹 checkout |
| 新 SQLite／migration | 只移除本卡自建 sandbox 副本前先核對絕對路徑位於 TASK-LOOP-07；正式 JSON 無改動，無正式資料回復需求 |
| 新 QA／交接 | 移除本卡新增檔須由人工確認；保留需要稽核的報告，output 不納 Git |
| 共用中央文件 | 由 08-B owner 回復其套用的本卡段落；07 未直接寫入 |

回復後重跑本卡 focused、專用 QA 與 UI 強制 gate。不得使用 git reset --hard、全目錄清理、正式 DB 重建或跨根遞迴移除。
