# TASK-LOOP-03 推薦閉環交接

## 2026-09-06 來源 ID 接線補驗

03／07 owner 依整合者明確指派完成最小 follow-up：Recommendation View 在保存成功後記錄 persist 回傳的真實 current_result_id；開始或完成新一輪分析時清除舊 ID；選取股票加入候選時傳遞 source_id。未保存結果保持空值，不使用展示 placeholder 充當來源身份。07 DataFrame 入口保留 source_id／result_id，pandas 缺值不會變成虛構字串 ID。

本次只改 `ui_qt/views/recommendation_view.py`、`ui_qt/views/watchlist_view.py`、`tests/test_task_loop_03_contract.py`、`tests/test_task_loop_07_contract.py` 及 03／07 handoff；base／current SHA=`2bfe86879760966560d36b5e1aecbccd23c4c69b`。只傳 ID，沒有新增金融計算、資料時點改寫、正式來源寫入或 main／08 檔變更。

驗證使用 TASK-07 雙根、PROFILE=test、Qt offscreen。`tests/test_task_loop_03_contract.py tests/test_task_loop_07_contract.py tests/test_recommendation_save_coordinator.py tests/test_recommendation_execution_coordinator.py tests/test_ui_qt_watchlist_candidate_pool_copy_text.py tests/test_ui_qt_update_view_workbench.py` 以既有 interpreter 跑 `-q -o addopts= -p no:cacheprovider`：exit 0、131 passed（來源 focused 50＋強制更新 81），2 個先前已記錄的 RSI dtype FutureWarning。全模組 mypy 532 files、金融／日期 guard、4 個 Python 檔 py_compile、diff check 均 exit 0；強制更新 QA 25 passed／0 failed／4 明示 skips。紀錄在 `output/master_goal/TASK-LOOP-07/identity_focused.log`、`identity_mypy.log`、`identity_update_qa.log`。

給 08-B 的 Manual 6.3／7.1 補句：「先保存推薦，再加入候選，可保留該保存結果的來源 ID；未保存或重新分析後的結果沒有保存身份，候選來源 ID 保持空值。」回復只移除本次 ID 記錄／清除／傳遞及六個新增契約案例的 hunks，保留 03／07 原本變更；無正式資料回復需求，未 stage／commit／push。

2026-09-06。狀態：本卡工程驗收完成；集中文件同步、inventory 登錄與跨卡最終驗收交 08-B。歷史產業成分來源仍為外部條件未滿，相關篩選採保守拒用，不宣稱正式 V4 或投資證據成熟。

## 版本、來源與執行邊界

- 延續前次架構稽核的共同 base SHA：`678db2bb260bb1de5cee4a0864f9f402db3660a7`；交接時 current SHA：`2bfe86879760966560d36b5e1aecbccd23c4c69b`。共享 HEAD 已由其他工作推進，本卡沒有 stage／commit／push。
- 接手時已有 01、04、08-A 未提交差異，以及先前治理文件變更；執行期間 02／05 並行。只修改以下本卡白名單，不還原或提交其他 owner 的差異。
- 測試環境：`DATA_ROOT=output/master_goal/TASK-LOOP-03/data`、`OUTPUT_ROOT=output/master_goal/TASK-LOOP-03/artifacts`、`PROFILE=test`、`QT_QPA_PLATFORM=offscreen`。TWStockConfig 解析到各根的 `_test`；pytest 自備 tmp_path／test_config fixtures。
- 推薦 QA 自行建立 `output/qa/recommendation_tab/task03_*/data/_test` 與 `artifacts/_test`，覆蓋並還原四個環境值。只使用合成行情與隔離 repository，fixture 結束清理自身 config log handler；不讀寫正式雙根。
- 時間線自查：先以 `日期 <= as_of_date`、若有則再以 `available_date <= as_of_date` 篩選，才限制股票池、評分與排名。PE 同時限制資料日與可得日，只採 observed；月營收沿用正式 availability mapping provider。只有公告日、沒有時刻的資料仍受上游 available_date 契約管理，本卡不聲稱盤中可得。
- T+1／費用／撮合不在本卡修改範圍；重播只交 Profile 與 config，不傳今日入選名單。正式來源 acceptance、promotion、ML flags、Portfolio、broker、Scheduler 均未修改。

## 回滾清單

### 變更檔案清單

| 路徑 | 類型與摘要 | 回滾方式 | 回滾風險 |
|---|---|---|---|
| `app_module/recommendation_service.py` | 修改；決策日入口、唯讀行情與 PE、可得資料切片、空集合、未知分數與歷史分類防線、執行指紋 | 只反向套用本卡 diff | 回退後歷史窗口與未知因子舊風險恢復 |
| `decision_module/scoring_engine.py` | 修改；已啟用的 RSI／MACD／KD／ADX／MA／Bollinger 缺值不使用中性預設 | 只反向套用本卡 diff | 回退後缺因子可能被中性分數掩蓋 |
| `app_module/dtos/__init__.py` | 修改；相容 run_context 與精確價格還原 | 先回退依賴，再回退本卡 DTO 差異 | 後續使用者可能已依賴新欄位；不可整檔還原 |
| `ui_qt/views/recommendation_view.py` | 修改；執行前凍結 Profile 身份、保存 run_context、重播設定 deepcopy | 與 DTO 接線共同回退 | 不改其他頁面或保存協調器 |
| `scripts/qa_validate_recommendation_tab.py` | 修改；自備雙根與離線 fixture、真實 scoring／repository QA、skip 非零 | 只反向套用本卡 diff | 回退後 QA 再依賴環境資料 |
| `tests/test_task_loop_03_contract.py` | 新增；24 個參數展開後的行為契約 | 確認依賴後移除本卡新檔並由 owner 同步 inventory | 不刪除其他測試 |
| `docs/06_qa/TASK_LOOP_03_HANDOFF.md` | 新增；本交接與集中補丁 | 保留證據，回退時註記已回退 | 無正式資料影響 |

### 回滾步驟（依序執行）

1. 先看最新 git status／diff，識別本卡與其他 owner 之後的變更。
2. 只反向套用以上功能差異；共享 DTO 先協調下游依賴，不執行整檔 checkout。新檔移除前確認 inventory 與 runner 引用；本卡未實際執行刪除。
3. 跑下列 focused、UI 與共同 Gate，確認回復結果；輸出 artifact 依 Git 排除規則保留於 ignored output，不提交原始 QA。

### 替代回滾方案

無法乾淨反向套用時，逐段恢復舊入口與 DTO 預設，不處理其他卡的未提交變更；先保留 diff 供 owner 核對。無 DB migration 或原始資料回復作業。

## 凍結的相容契約

- `RecommendationService.run_recommendation` 新增 keyword-only `as_of_date` 與 `universe`；也接受 config 的 `as_of_date`。既有無參數呼叫保持最新資料模式。SQLite 兩種模式都使用 mode=ro／query_only，歷史窗口錨定指定日以前 60 曆日，不因全庫更新日期而移動。CSV 歷史入口讀取可用來源後裁切；來源本身不是新 SSOT。
- 可得日存在時，非法／未到可得日的 row 排除；同股票同交易日採當時已知的最新 available_date 修訂。沒有版本可得日的覆寫歷史不能被此機制逆推出舊值。
- `last_run_context`／`RecommendationResultDTO.run_context` 使用 `schema_version=recommendation-context.v1`：決策日、實際行情日、深複製 strategy_config、Profile id/version、universe_spec、來源介面名稱、行情 fingerprint、基本面輸入 provenance、合併 data_fingerprint、eligible_universe_size 與 warnings。
- `data_fingerprint` 是本次讀到的行情內容加實際使用的基本面列之 SHA-256，不是整個來源檔 hash。PE 保留資料日／可得日／source／source_version／quality；月營收保留 period／available_date／source/version／值。future-only 資料追加不應改變歷史 fingerprint。
- 空股票池、空產業結果、沒有可得行情或全部分數未知皆回空集合；quantile 有非空但不足母體仍沿用既有明確錯誤。fixed 維持預設及原有同分處理順序，quantile 仍 opt-in；母體在 top_n 以前固定。
- 缺／非有限總分留 `total_score_missing_or_nonfinite`，不補零；已啟用技術指標的必要欄缺失／非有限值維持未知，總分傳播 Decimal NaN 後由服務排除。沒有啟用的指標仍保留既有中性預設。
- 每筆 screening／Why Not 附上 as_of_date 與 data_fingerprint；有 missing／degraded row 時 exclusion_quality 降級，不把未知宣稱 observed。
- 歷史產業分類沒有 PIT 權威：指定決策日且要求產業篩選時回空集合，逐股 reason=`industry_membership_pit_unavailable`；歷史推薦省略未驗證產業理由，context warning=`industry_membership_not_point_in_time`。非歷史模式產業 performance 查詢帶實際決策日。
- `RecommendationDTO.close_price` 容許 Decimal／既有 float，from_dict 以 Decimal 還原精確價格；展示不能回流成新的金融運算。RecommendationResultDTO 的 run_context 為新增預設空欄，歷史 JSON 可讀。既有保存協調器透過 config 的保留鍵 `_recommendation_run_context` 傳入，DTO 取出後不污染 strategy config。
- Profile→replay 的設定在 Qt payload 邊界 deepcopy；TASK-04 ReplayService 既有日期／available_date 裁切與 config 凍結經本卡整合測試，沒有改動它。

## 驗證紀錄

所有 pytest 使用 `.\.venv\Scripts\python.exe -m pytest`、`-q -o addopts= -p no:cacheprovider`，預先設定上述雙根；停用 cache 只避免既有 ACL 警告。

| 檢查 | 實際命令／範圍 | 結果 |
|---|---|---|
| 接手基線 | ranking_service、ranking_pipeline、scoring_kernels、execution_coordinator、fundamental_filters | exit 0，20 passed |
| 最終 focused＋相關回歸 | `tests/test_recommendation_ranking_service.py tests/test_recommendation_ranking_pipeline.py tests/test_scoring_kernels.py tests/test_recommendation_execution_coordinator.py tests/test_recommendation_fundamental_filters.py tests/test_task_loop_03_contract.py tests/test_recommendation_dto_roundtrip.py tests/test_recommendation_profile_service.py tests/test_recommendation_save_coordinator.py tests/test_recommendation_recomputation.py tests/test_recommendation_exclusion_payload.py tests/test_recommendation_v1_7_negative_evidence.py tests/test_ui_qt_recommendation_profiles.py tests/test_ui_qt_recommendation_metadata.py tests/test_weight_contract.py` | exit 0，80 passed，0 skips；2 個既有 RSI DataFrame 指派 dtype FutureWarning，由 Decimal 極值 fixture 觸發 |
| 推薦 QA | `scripts/qa_validate_recommendation_tab.py` | exit 0，7 passed／0 failed／0 skips；失敗與 skip 非零另有 fault injection 測試 |
| 強制更新頁 | `tests/test_ui_qt_update_view_workbench.py` | exit 0，81 passed |
| 強制更新 QA | `scripts/qa_validate_update_tab.py` | exit 0，25 passed／0 failed／4 明示 skips；不是全覆蓋證明 |
| 全模組型別 | `-m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | 最終 exit 0，528 files；先前並行 02／05 error 已消失 |
| 金融／日期靜態防線 | `scripts/check_financial_float_boundaries.py`、`scripts/check_look_ahead_bias.py` | 各 exit 0；行為 PIT 另以上述測試證實 |
| 語法及 diff | `-m py_compile` 本卡 6 個 Python 檔；`git diff --check` 本卡路徑 | exit 0 |

原始紀錄：`output/master_goal/TASK-LOOP-03/focused.log`、`mypy.log`、`recommendation_qa.log`、`update_pytest.log`、`update_qa.log`；QA 報告 `output/qa/recommendation_tab/VALIDATION_REPORT.md`。

推薦 QA 合成 CSV SHA-256：`307543a9d5b968f003d6dd8aebb0a0f346cda7ba1ac4efafbf75a0781ebf1217`；決策日 `2026-05-25` 的合併輸入 fingerprint：`89cbdc9fb9d27ba869744b734038c061ed136516a0e52cd40f82593a4385f5ea`。repository 保存重載保留 context／Why Not；fixture CSV 前後 hash 相同。這些 hash 不構成正式來源接受或投資效益證據。

## 集中文件精確補丁（交 08-B 套用）

`docs/07_guides/APPLICATION_MANUAL.md` 第 6.3「固定門檻與百分位排名」末尾新增：

> 推薦服務會保留決策日、實際行情日與排名母體；top_n 只限制顯示入選數，不改分位數母體。已啟用指標缺值、基本面缺正式可得證據或總分無效時，結果保留 Why Not 並降低資料品質，不以零分或中性分數代替未知。無符合候選可以是有效空結果。

第 6 節推薦結果保存與送 Research Lab 的操作說明末尾新增：

> 保存推薦時一併保存執行當時的 Profile／設定、決策日、來源內容指紋、母體與負面證據；送「推薦回放」傳送獨立的完整設定快照，後續修改畫面設定不會改動已送出內容。歷史 as_of_date 是應用服務接點，本次沒有新增 UI 日期選擇器。若歷史研究使用產業篩選而缺少當時成分股證據，服務會回報 industry_membership_pit_unavailable；需補齊正式 PIT 分類來源，不能改用今日分類解鎖。

`docs/01_architecture/system_architecture.md` RecommendationProfileService／推薦排名相關段落後新增：

> TASK-LOOP-03 在 RecommendationService 補上決策日先行的行情切片與 query-only SQLite 讀取，產出 recommendation-context.v1；RecommendationResultDTO 相容保存執行設定、行情與實際基本面輸入 fingerprint、母體、Why Not。未知技術因子不再進入中性預設。歷史產業成分 PIT 仍缺可用契約，該篩選明確拒用；市場服務 DTO 與資料接受 Gate 維持各自 owner。

`docs/01_architecture/target_system_architecture.md` 推薦／市場跨域契約的待辦段新增：

> 下一步以具正式可得日及版本的產業成分來源，補齊 recommendation-context.v1 的 PIT universe 接點；source acceptance 與 membership provenance 完成前，不恢復歷史產業篩選。市場 cut-off／regime 的具名輸入版本及 Indicator pipeline 版本須由跨卡接點進一步對齊，不以觀測快照代替正式來源契約。

Snapshot／Roadmap Hub／6M／Index 只登錄「TASK-03 工程驗收完成、待 08-B 整合與產業 PIT 外部條件」，不得改 V4 maturity 或 promotion Gate。

## 交 08-B 的未完成條件

1. 唯一 owner 登錄 `tests/test_task_loop_03_contract.py` 至 QA inventory，套用以上集中補丁並做最終跨卡驗收；本卡未修改 inventory 或集中 SSOT。
2. 歷史產業成分、精確公告時刻、來源 acceptance 完整版本鏈與市場 regime 輸入凍結仍依上游正式證據，不能由本卡 fixture 補造。服務提供可檢查 fingerprint 與明確歷史產業拒用，不宣稱解決缺失的外部證據。
3. 輸入若直接覆寫舊可得日版本，或 indicator 表沒有對應計算版本，單一目前 DB 不能重建原始過去版本；須以保存快照／上游 manifest 鎖定，列入後續來源與研究保存整合。
