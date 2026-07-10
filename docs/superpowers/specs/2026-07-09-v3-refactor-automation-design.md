# V3 後續簡化佇列自動化設計

## 目標

將已完成的 V3.0 Engineering Candidate closeout 排程，改為可在既有夜間時段內連續處理多個「保持行為不變」重構切片的自動化迴圈。每個完成切片都必須驗證、commit 並 push 到 `dev`，讓早晨報告可直接驗收實際完成量。

## 範圍

更新下列 6 個既有 cron 的名稱與 prompt，保留其 id、啟用狀態、模型、reasoning effort、local execution environment、`dev` 工作區與既有執行時間：

1. `baldr-milestone-planner-0000`
2. `baldr-milestone-implementation-sprint-0020`
3. `baldr-milestone-qa-checkpoint-0330`
4. `baldr-milestone-morning-finish-planner-0540`
5. `baldr-milestone-finish-sprint-0600`
6. `baldr-milestone-final-closeout-0800`

獨立的 `baldr-scheduled-evidence-morning-report` 不屬於 V3.0 milestone loop，不修改。

## 有序重構佇列

排程依序從以下節點建立最小、可獨立驗證的重構切片；每個切片是完整的 RED → GREEN → regression → commit → push 週期，而非只做分析或留下半成品。

1. `ui_qt/views/backtest_view.py` (`BacktestView`)
2. `app_module/update_service.py` (`UpdateService`)
3. `ui_qt/views/recommendation_view.py` (`RecommendationView`)
4. `ui_qt/views/update_view.py` (`UpdateView`)
5. `app_module/recommendation_service.py` (`RecommendationService`)
6. `decision_module/strategy_configurator.py` (`StrategyConfigurator`)
7. `app_module/recommendation_portfolio_backtest_service.py` (`RecommendationPortfolioBacktestService`)
8. `app_module/backtest_service.py` (`BacktestService`)
9. `data_module/data_loader.py` (`DataLoader`)
10. `app_module/decision_desk_service.py` (`DecisionDeskSnapshotBuilder`)

若前一個節點剩餘工作無法在一個切片內安全完成，planner 可先拆成更小的相容切片；不得跳過優先序去開新功能。相同夜間可完成幾個切片由實際時間盒、測試與工作區狀態決定，不設「每晚一個」上限。

## 時間與責任分工

| 時段 | Automation | 責任 |
|---|---|---|
| 00:00–00:15 | planner | 讀取上一輪報告、建立排序佇列與精確驗證命令；不改 code。 |
| 00:20–03:15 | implementation | 連續完成可安全完成的切片；每片獨立 commit/push。 |
| 03:30 | QA checkpoint | 驗證已推送切片，失敗則標示 BLOCKED 並禁止後續寫入。 |
| 05:40–05:55 | finish planner | 依 QA 讀回結果只規劃剩餘 P0 切片；不改 code。 |
| 06:00–07:35 | finish sprint | 繼續執行所有在時間內可完整驗證的切片；每片獨立 commit/push。 |
| 08:00 | final closeout | 彙整 commit、測試、佇列進度、未完成與 blocker；不改 code。 |

## 不可違反的契約與安全邊界

- 保留所有公開 API、DTO 欄位／序列化、資料語意與副作用順序。
- `TWStockConfig`、`StrategySpec`、`DecisionDeskQuality`、`ResearchRunMetadataDTO`、`FactorDiagnostic` 是高連通契約；除非只是新增相容性測試，排程不得重命名、刪欄位、改 enum 值或改建構／序列化行為。
- 不得改策略、回測、推薦、資金、倉位、風控、績效的金融語意；禁止新增裸 `float` 計算，且每一個相關切片必須完成 Look-ahead bias 自查。
- 不得寫 production DB、啟用 production scheduler、下單、套用 lifecycle action、刪除正式資料、將 candidate source 接進 `ScoringEngine`、改 recommendation threshold／profile weights／portfolio。
- 僅在 `dev`、乾淨工作區且 `git pull --ff-only origin dev` 成功時才可寫入。遇到未知未提交變更，標記 `DIRTY_WORKTREE_RISK` 並停止寫入。
- `output/automation/**` 與 `graphify-out/memory/**` 是已知工具輸出；可在工作區檢查時忽略，但永遠不得 stage。除此之外的未提交或未追蹤檔案一律視為未知變更。
- 每個切片先驗證 RED（新特徵測試或現有測試能表達保留契約），再作最小實作；focused pytest、`py_compile`、必要 UI gate、必要 mypy、`git diff --check` 皆通過才可 commit/push。
- 任一驗證失敗、測試逾時、merge／push 失敗或工作區不乾淨，立即停止該時段後續寫入，留下可重跑報告；不得用 `reset --hard` 或覆寫他人變更。

## 產出契約

所有 loop 報告寫入既有 ignored 位置 `output/automation/version_loop/`。每一輪需至少包含：

- `active_program=V3_POST_CLOSEOUT_SIMPLIFICATION_QUEUE`
- 已完成切片與各自 commit SHA
- 已執行測試與結果
- queue 的 completed / in-progress / next / blocked 狀態
- 被保護契約的相容性檢查結果
- `PENDING_MANUAL_VALIDATION` 與既有 evidence / scheduler boundary（如仍適用）
- 早晨人工驗收所需的風險與未完成事項

## 成功準則

1. 6 個 cron 讀回後均明確使用 V3 後續簡化佇列，不再以 V3.0 closeout 為 active milestone。
2. implementation 與 finish sprint 都明確允許在時間盒內連續執行多個完整切片，而不是限制一個節點。
3. 每個寫入型 sprint 都強制測試、每片 commit/push、失敗即停止與 protected-contract guard。
4. QA、planner、closeout 不修改 code；QA failure 會阻止 finish sprint 寫入。
5. 既有 cron 時間與啟用狀態不變，evidence morning report 未受影響。
6. Graphify memory 不會阻擋寫入型 sprint，但任何其他未提交變更仍會 fail-closed。
