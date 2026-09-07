# TASK-LOOP-05 REGISTRY 交接

## 執行前回滾清單

本卡只修改 Playbook TASK-05 白名單中的 ResearchRun service/repository/DTO/comparison、Evidence service/repository/forward service、Research metadata helper/compare widget、指定測試；新增專用 QA、contract test 與本交接。先執行隔離基線；正式資料、04 撮合、promotion、lifecycle、scheduler 與 shared SSOT 不修改。

回滾先保存本卡 scoped diff，核對沒有其他 owner 的 hunk，再以 reverse-check 與逐 hunk 反向套用；不得整檔 checkout、clean 或刪除資料。新檔確認沒有他人接續內容才移除。schema migration 必須只增加相容欄位，不降版、不重寫歷史 payload。回滾後跑本卡 focused suite。

## 執行前時間線／證據自查

- 消費 TASK-04 frozen results 的 execution_contract，不依目前 UI 設定重建，不重算歷史研究。
- 查詢與比較只讀已保存資料；恢復由明確 save owner 操作，不在建構子、list 或 load 暗中執行。
- Forward outcome 是事後 close-to-close 診斷，不能替代 next-session-open 執行損益。
- replay／forward／paper／live 為來源宣告，人工 review 提案保留 run、推薦 snapshot、event 與 outcome lineage；不增加 Formal credit 或策略權限。

## 結果

本卡 05-A 保存／版本與 05-B Evidence 接點的獨立工程驗收完成。真實時間、Paper producer fills 與正式 acceptance 是外部 Gate，沒有以 fixture 補足，也未增加 Formal credit。TASK-06 handoff 尚未出現，因此 06 真實 producer → 本卡 lineage 的整合仍需後續 owner 接續。

base HEAD 為 `678db2bb260bb1de5cee4a0864f9f402db3660a7`；交接 HEAD 為 `2bfe86879760966560d36b5e1aecbccd23c4c69b`（root 在本卡執行期間整合其它卡提交）。本子 Agent 沒有 stage／commit／push。使用者與其他 owner dirty changes 保留。

實際修改 9 個產品檔：`app_module/research_run_service.py`、`app_module/research_run_repository.py`、`app_module/research_run_dtos.py`、`app_module/research_run_comparison_service.py`、`app_module/evidence_event_service.py`、`app_module/evidence_event_repository.py`、`app_module/forward_performance_service.py`、`ui_qt/views/backtest/research_run_metadata.py`、`ui_qt/views/research_lab/run_registry_compare_widget.py`。修改 3 個指定測試：`tests/test_research_run_service.py`、`tests/test_research_run_repository.py`、`tests/test_ui_qt_run_registry_compare.py`。新增 `tests/test_task_loop_05_contract.py`、`scripts/qa_validate_research_registry_loop.py` 與本交接。

root 另外擁有兩個相容 fixture 補丁：`tests/test_inspect_research_registry_transaction.py`、`tests/test_qa_research_registry_production_canary.py` 改成顯式 `.ensure_schema()`；本卡只驗證，沒有修改這兩檔。未改 TASK-04 撮合／結果 producer、data config、Evidence DTO、lifecycle、promotion 或 scheduler 實作。

## 保存與版本契約

- ResearchRunService／Repository 建構子不建 schema、不 reconcile。`list_runs()` 只顯示 committed＋valid rows；load 驗證 state、雙 Parquet hash 與 execution version。SQLite query 使用 `mode=ro`／`query_only`，連線明確關閉。空 DB 查詢回傳空結果，不建立 DB。
- 寫入 owner 的 `save_run()` 顯式準備 schema；相同版本 schema 不重寫 updated_at，未知新版 schema 拒絕降版。schema 仍為 2，沒有歷史 DB migration 或歷史 payload 重写。
- 初始 row 以單次 INSERT 原子寫成 staging／pending，避免曾短暫呈現 committed。重啟後由 owner 顯式 `reconcile_incomplete_saves()`：staging→failed；files_ready 雙檔 hash 一致才完成，損毀／缺檔→failed。查詢永遠不代替 owner 修復。
- 同 run_id 的重試核對宣告 hash、既存檔案完整性、immutable metadata 與實際 equity／trades；相同宣告 hash 不能掩蓋變更。保存先複製輸入；已存在 staging run_id 拒絕另一個保存 owner 接手寫入。正式部署仍應維持單一 save／reconcile owner，沒有新增跨程序排程或鎖服務。
- `execution_price` 與 `data_manifest.execution_contract` 保存 `next-session-open.v2`／`legacy-same-day-close.v1`；DTO `execution_contract` property 對歷史無版本 next_open／close 回報 `unversioned`，不推測、不原地升級。未知版本或互相矛盾宣告拒絕保存／載入。
- UI metadata 使用 frozen details／summary 的版本與 status；推薦 v2 保留實際 portfolio_credibility 為 `data_manifest.execution_assumptions`，保存費率、稅、lot 與 terminal policy。0.10 停損 ratio 保存為 1000 bp，費率 14.25 bp 保存為 1425 bp_x100。沒有用目前控件覆蓋 frozen 結果。
- 跨版本或 cancelled／partial 結果為 Incompatible，UI 清除前次績效與標準化權益後停止混排；損毀載入失敗呈現原因，不 repair 或重跑。交易成本／稅／lot 假設不同延續 Caution 分級。兩個同假設 unversioned 舊結果仍可按既有規則展示，不能宣稱符合 v2。

## Evidence 與人工覆盤接點

- `record_event(..., evidence_tier=...)` 可明確宣告 replay／forward／paper／live，metadata 使用 `evidence-lineage.v1` namespace；沒有宣告的歷史事件維持 unclassified。tier 是來源宣告，沒有被當成已驗證的真實時間或正式信用。
- `EvidenceEventRepository.list_events_for_run(run_id)` 是獨立查詢介面，既有 list_events 子類別簽章保持相容。Evidence 建構／查詢不遷移 schema；insert/upsert 才顯式初始化。
- `ForwardPerformanceService` outcome 保存 event hash／run／source／recommendation snapshot lineage，沿用原事件 declared tier；replay 的事後報酬仍是 replay。每次 calculate 更新暫存市場切片，dry_run 不寫資料。close_to_close_event_date 明列 `is_execution_pnl=False`，不替代 v2 實際撮合 PnL。
- `EvidenceEventService.build_review_proposal(run_id, reviewer, review_notes, next_research_question)` 先唯讀載入完整研究，再連結推薦 snapshot、event 與各 window outcome，回傳 `EvidenceReviewProposalDTO`。缺件包含未具名／缺審閱內容、推薦 snapshot lineage、未成熟 outcome、unclassified tier、real_time_producer_acceptance_required 與 formal_evidence_acceptance_not_evaluated。
- proposal_only=True、formal_credit_granted=False、promotion_allowed=False 固定由 service 產生；這是 app service 的人工覆盤接點，不新增 UI 核准按鈕，也不寫 lifecycle 決議、正式 credit 或策略版本。具名 reviewer 字串不是獨立身分驗證，Formal acceptance 仍須既有 owner Gate。

## 隔離與驗證

DATA_ROOT=`C:/Projects/PythonProjects/technical_analysis/output/master_goal/TASK-LOOP-05/data`；OUTPUT_ROOT=`C:/Projects/PythonProjects/technical_analysis/output/master_goal/TASK-LOOP-05/artifacts`；PROFILE=`test`；QT_QPA_PLATFORM=`offscreen`。pytest 用 tmp_path 雙根，QA 嚴格拒絕非 TASK-05 的 env roots；TWStockConfig 使用 `/_test` 衍生路徑。QA 每輪建立且保留獨立 fixture 以供覆盤，不遞迴刪除仍可能持有 logger 的目錄，不使用正式資料。

| 驗證 | 最終結果／exit code |
|---|---|
| Playbook 9 個指定測試檔＋7 個影響測試檔 | 102 passed／0 |
| 新 contract test | 18 個行為案例包含於上列；六 failure points、損毀恢復、readonly、same-hash payload 衝突、future append、版本、cost ratio、tier/review |
| tests/test_ui_qt_update_view_workbench.py | 81 passed／0 |
| scripts/qa_validate_research_registry_loop.py | 9 passed、0 failed／0 |
| scripts/qa_validate_update_tab.py | 25 passed、0 failed、4 skipped／0；下載等 skip 不當成 passed |
| mypy 全 8 個 module 目錄 | 528 source files、0 error／0；兩個既有 annotation-unchecked notes |
| check_financial_float_boundaries、check_look_ahead_bias | 各 exit 0；不取代行為測試 |
| py_compile 本卡 14 個 Python 檔、scoped git diff --check | exit 0 |

7 個追加的影響檔是 `tests/test_research_run_legacy_adapter.py`、`tests/test_strategy_lifecycle_repository.py`、`tests/test_batch_backtest_research_run_save.py`、`tests/test_forward_performance_dashboard_service.py`、`tests/test_v1_9_agent_evidence_access.py`、`tests/test_inspect_research_registry_transaction.py`、`tests/test_qa_research_registry_production_canary.py`。測試採 `-q -o addopts=`；只出現既有 `.pytest_cache` 權限 warning。Lifecycle/promotion 相容測試全部使用 tmp_path fixture，沒有執行正式 promotion。

初始基線 56 passed／1 failed，原因是舊 config path 測試未考慮 PROFILE=test；該測試明確隔離自己的 PROFILE 後通過。影響回歸曾發現共用 DB 已有 lifecycle schema 而未有 research schema，已在明確 save 入口補上初始化並重驗，不以 query migration 掩蓋。

QA report：`output/master_goal/TASK-LOOP-05/artifacts/_test/qa/research_registry_loop/VALIDATION_REPORT.json`，SHA-256=`3F08035EE15890680A8024F888FFB5CEA12158148E98FD4C70E808DEB613485A`。JSON 另記錄 QA／contract 檔 hash、UTC 時間、本輪 fixture 雙根與逐項結果。contract test SHA-256=`EC0D8AFE55A2DD1279D10E83C999F1AE59092ADE2BF41A5110E608CF2A4DCD3D`。

Update QA 使用 TASK-01 owner 自帶 TemporaryDirectory fixture；本卡 env 不會使它讀正式資料。當輪報告已複製到 `output/master_goal/TASK-LOOP-05/artifacts/_test/qa/update_tab_report.md`，SHA-256=`7D6F02EE57A078B3869CF7D2E13B4509405D7B6659A79A1511A350B6E7C8A63D`。

## TASK-08-B 共用文件精確補丁

1. **APPLICATION_MANUAL.md／9.9 Registry 保存與比較、排錯**：入口保留研究保存／Registry 比較；說明保存結果使用執行時 frozen version/cost/status，v2／legacy／unversioned 不互相升級；cancelled 結果可作審計保存但不可績效混排。損毀、缺檔或未知 version 停止比較，頁面顯示原因且不修復／重算。對未完成保存，由維護 owner 在隔離副本先驗證後顯式 reconciliation；UI refresh 不執行修復。
2. **同節參數與结果判讀**：推薦 v2 fee_bp_x100、slippage_bp_x100、stop/take bp 是保存單位；0.10 ratio=1000 bp。manifest 保留稅／lot／terminal policy；假設不同為 Caution，執行版本不同為 Incompatible。legacy 無版本結果不宣稱具備 v2 時間線精度。
3. **APPLICATION_MANUAL.md／Forward Performance／覆盤**：close-to-close outcome 是事後診斷；原 event tier 不因成熟 outcome 而升級。人工 review 接點目前在 app service，輸入 run_id／具名 reviewer／notes／下一輪研究問題，回傳 lineage 與缺件；沒有新增 UI 核准按鈕或正式寫入權限。來源 tier 宣告與 reviewer 字串不能當作真實時間／身分／Formal acceptance。
4. **system_architecture.md／11 Registry 事務與 evidence flow**：單次 staging INSERT→files_ready→committed；建構／query readonly，schema 初始化與 reconcile 屬明確 writer。加入 execution_contract property、execution_assumptions、EvidenceReviewProposalDTO 邊界；原始研究→event→outcome→人工提案→下一輪研究是跨 epoch 引用，不修改原 run。
5. **PROJECT_SNAPSHOT／Roadmap／Index**：只新增 TASK-05 工程交接與測試入口；V4 Evidence Accumulation、action_required 與 Formal credit 維持不變。TASK-06 自然產生的 fills／outcome lineage、具名覆盤與正式 acceptance 留在外部 Gate。
