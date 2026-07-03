# V1.1 至 V2.0 版本路線圖

> **最後更新**：2026-07-02
> **定位**：本文件是 `ROADMAP_6M_ENGINEERING.md` 的版本化交付 companion。6M Roadmap 仍是未來 6 個月工程主線權威；本文件負責把「V1 已完成、main 可運行、資料可信度仍在驗證中」之後的工作拆成可討論、可 commit、可驗收的 V1.1 至 V2.0 節奏。

---

## 1. 當前基準

目前假設：

- V1 已完成，`main` 已通過 release gate 且可順利運行。
- V1 的意義是工程入口、資料契約、操作流程與 QA gate 可用，不代表策略、推薦或警示已具備投資有效性。
- Post-V1 evidence 底座已建立，但正式資料可信度、forward evidence 樣本、live-vs-research gap、Decision Quality 與 production scheduler 都仍在驗證中。
- Evidence dry-run 可以繼續跑，不需要等待 3-5 個交易日才開始 V1.1 規劃與非破壞式實作；但 production write-mode scheduler 仍需明確人工核准。

版本切分原則：

- V1.x：不大改資訊架構，不移除既有主要 Tab；優先把 workflow 串順、把 evidence 看得見、把可信度 gate 補強。
- V2.0：等 V1.x 的真實使用與 evidence 證明使用者每天怎麼決策後，再重整資訊架構與主要工作台。
- 任何策略、回測、推薦、factor、portfolio 或績效改動，都維持 no-look-ahead、Decimal / 整數單位與資料可得日防線。

---

## 2. 版本總覽

| 版本 | 主題 | 核心問題 | 預期結果 |
|---|---|---|---|
| V1.1 | Decision Workflow Integration | 每日決策、推薦、研究回放與 lifecycle 判讀仍需要更清楚的 workflow bridge | 已完成 v1：推薦 Profile 可見、推薦回放語意清楚、Profile replay comparison 可產生人工 lifecycle candidate |
| V1.2 | Research Credibility & Execution Model | 研究回測已有治理，但成交假設、微結構與 attribution 還不夠像真實決策 | 已完成 v1：replay 訓練 / 驗證分離、rolling risk、microstructure preflight、relative attribution |
| V1.3 | Evidence Operations & Manual Lifecycle | Evidence dashboard 已建立，但樣本、覆盤、人工核准流程還未形成日常節奏 | 已完成 v1：weekly evidence operations package、manual approval summary、signal decay candidate 與 action item planning |
| V1.4 | Evidence Review History | weekly review 可產生，但缺少 append-only history 與 UI 查閱入口 | 已完成 v1：weekly review history repository、CLI save/list、Research Lab `Evidence Review -> 覆盤歷史` 唯讀子頁 |
| V2.0 | Unified Decision Workbench | V1.x 驗證後，Daily Decision / Market Watch / Evidence / Portfolio Review 的邊界可以重整 | 形成單一決策工作台，舊 Tab 轉為 drill-down 或專家模式 |

---

## 3. V1.1：Decision Workflow Integration

建議定位：V1.1 不是大改版，而是把已完成的 V1 能力變成每天可順手使用的流程。

狀態：2026-07-02 v1 closeout 已完成。實作範圍聚焦在推薦分析到 Research Lab / lifecycle 的 workflow bridge；Daily Decision Desk 與 Market Watch 的完整資訊架構合併仍留待 V2.0 評估。

核心交付：

1. Daily Decision Desk 保持為每日入口，優先顯示今日 market regime、breadth、sector rotation、watchlist trigger、portfolio alert、risk prompt 與資料品質。
2. Market Watch / Smart Money 不急著合併進 Daily Decision Desk；先做成明確 drill-down：從 Daily Decision 的市場、產業、個股、籌碼警示可以回到對應市場觀察證據。
3. Research Lab / Evidence Review 只讀 evidence dashboard 保留在 Research Lab，但 Daily Decision 可以顯示 evidence summary 入口與「目前樣本仍不足 / pending / missing」狀態。
4. 觀察清單、推薦、研究、持倉警示之間補齊 cross-flow 文案與 navigation affordance，讓下一步動作更清楚。
5. Empty state 要誠實：正式 DB 沒 evidence rows 時，畫面要說明「目前還沒有可覆盤樣本」，而不是看起來像壞掉。

本次 v1 closeout 已交付：

1. 建立 V1.1 spec / plan，明確界定先做非破壞式 workflow bridge，不直接合併主要 Tab。
2. 新增 `ProfileReplayComparisonService` / DTO，以注入 runner 的 replay 結果比較多個 Profile，輸出 promote / hold / demote_candidate / retire_candidate / insufficient_evidence 候選標籤。
3. 推薦分析 Profile 說明區揭露權重、技術分類、型態預覽與主要篩選條件，讓內建 Profile 差異可被檢查。
4. 推薦頁後續操作明確區分「批次回測今日名單」與「推薦回放重播 Profile / Config」。
5. 升降級仍需保存 Research Run / Evidence 後人工審核；V1.1 不新增自動降級、退休或刪除策略版本。

Daily Decision 與 Market Watch 是否整合：

- V1.1：不做完整合併。保留兩個 Tab，新增跨 Tab 下鑽、摘要、狀態同步與共同語彙。
- 原因：資料可信度仍在驗證中，太早合併會把「資訊架構設計」和「資料有效性驗證」綁在一起，後續很難拆。
- V2.0：若 V1.1 的使用證明 Daily Decision 是自然入口，Market Watch 可以降為 Unified Decision Workbench 內的市場證據 drill-down。

V1.1 驗收 Gate：

- `main` 仍可乾淨啟動，8 個頂層工作區 smoke 不退化。
- UI 不直接重算 scoring、screening、portfolio、broker flow 或 evidence；仍走 service / snapshot。
- Evidence dry-run 繼續背景累積，不因 V1.1 UI 串接而寫 production evidence DB。
- Manual 與 Roadmap 明確揭露：資料可信度仍在驗證，forward evidence 不等於投資有效性。

---

## 4. V1.2：Research Credibility & Execution Model

建議定位：補強「研究結果是否可信」而不是追求更多策略。

狀態：2026-07-02 v1 closeout 已完成。V1.2 先把 replay / Profile 比較結果的可信度揭露補齊，不宣稱推薦或策略具備投資有效性，也不把任何 lifecycle candidate 變成自動操作。

核心交付：

1. Profile / replay 獨立驗證：已完成 `validation_start_date` / `validation_end_date`，驗證期必須晚於訓練期，lifecycle candidate 以 validation metrics 主導。
2. 台股微結構 preflight：已完成可選欄位檢查，涵蓋處置股、分盤、全額交割、漲跌停鎖死、除權息；缺 source 時揭露 `missing_optional_sources`。
3. rolling risk metrics：已完成 Rolling Sharpe / Sortino、VaR / CVaR、drawdown duration、turnover approximation。
4. benchmark / industry / concept relative attribution：已完成 replay 期間相對歸因與 missing source 揭露。
5. 報告輸出深化：Excel 已完成，PDF 仍維持研究輸出 backlog；若要做，先以 evidence / attribution 可追溯為主。

Residual：

- 零股、買賣價差、完整委託簿撮合、Gap 實際成交價格調整尚未完成。
- 正式處置股、分盤、全額交割、漲跌停鎖死與除權息資料源尚未接入 governed source / available_date / quality / missing policy。
- factor attribution 與 forward performance 的保存後讀取、儀表化與報告化仍留待後續。

V1.2 驗收 Gate：

- 已完成項目的成交假設、optional source 與 missing source 會在 metadata / details 中可追溯。
- 不因新增微結構資料而破壞既有回測或推薦核心；V1.2 preflight 只讀已提供 history，不改 PnL、成交價、cash ledger 或 sizing。
- 策略 / 回測修改已附 no-look-ahead 自查與 focused tests；金融 float boundary 掃描維持通過。

---

## 5. V1.3：Evidence Operations & Manual Lifecycle

狀態：2026-07-03 v1 closeout 已完成。V1.3 把 evidence 從「看得到」推到「每週可彙總、可建立人工 action item、可形成 manual approval package」；production scheduler 仍未啟用。

核心交付：

1. Evidence Review UI manual smoke closeout，確認 Forward Evidence、Live vs Research Gap、Signal Decay、Decision Quality 在有樣本與無樣本時都可判讀。
2. Multi-day dry-run record 轉成固定節奏：每天看 05:30 read-only 摘要，每週整理 pending / missing / blocking gaps。
3. Manual Approval Workflow：任何 production scheduler、lifecycle action、demote / retire、strategy promotion 都要有人工核准紀錄。
4. Signal Decay 與 Decision Quality 的 action item 開始回流到 Research Lab / Strategy Lifecycle，但不自動改策略版本。
5. 建立「決策覆盤週報」最小格式：本週觸發事件、完成 outcome、missing source、最大 gap、下週 action。

本次 v1 closeout 已交付：

1. 新增 `EvidenceOperationsService` / DTO，彙總 scheduler readiness、Decision Quality、Signal Decay 與 action item。
2. 新增 `scripts/build_evidence_operations_weekly_review.py`，可輸出 JSON / Markdown weekly review。
3. Action item planning 預設 dry-run；`--confirm-action-items` 才 append-only 寫入 explicit DB。
4. Signal Decay demote / retire candidate 只列為人工審核清單，`apply_action=false`。
5. 樣本不足時 status 為 `coverage_only`，只輸出覆蓋率與資料品質缺口。

V1.3 驗收 Gate：

- Production scheduler 仍預設未啟用，除非通過 explicit approval。
- Evidence 樣本不足時只能輸出覆蓋率與品質缺口，不能包裝成策略結論。
- Decision Quality 是流程 evidence，不是績效或責備分數。
- Action item planning 不得跳過人工 review，也不得套用 lifecycle action。

---

## 6. V1.4：Evidence Review History

狀態：2026-07-03 v1 closeout 已完成。V1.4 把 V1.3 每週覆盤包從「一次性輸出」推進到「可封存、可回看、可由 UI 檢查的覆盤歷史」，讓後續數週 evidence operations 可以比較週期、status、blocking gaps 與 manual lifecycle candidate 數量，而不需要重新解讀散落的 CLI output。

本次 v1 closeout 已交付：

1. 新增 `EvidenceOperationsHistoryRepository` / DTO，將 weekly review payload 以穩定 hash append-only 保存到 `evidence_operations_weekly_reviews`。
2. `scripts/build_evidence_operations_weekly_review.py` 新增 `--save-history` 與 `--list-history`；保存 history 必須指定 explicit `--db-path`，疑似正式 DB 仍需額外 `--allow-production-like-db`。
3. 新增 `EvidenceOperationsHistoryDashboardService`、Qt table model 與 Research Lab `Evidence Review -> 覆盤歷史` 唯讀子頁。
4. history row 明確保存 `production_scheduler_allowed=false`，不建立 scheduler、不寫 action item、不改 Strategy Lifecycle state、不改 portfolio。

V1.4 驗收 Gate：

- History 保存採 append-only / idempotent hash，重複保存同一份 weekly review 不新增重複列。
- UI 只能讀 dashboard service，不直接讀寫 SQLite repository、不啟用 scheduler、不自動 lifecycle action。
- History 只代表人工覆盤封存，不代表 alpha、策略、推薦或警示有效。

---

## 7. V2.0：Unified Decision Workbench

建議定位：V2.0 是資訊架構重整，不是單純增加功能。

V2.0 應該長這樣：

1. 第一畫面是 Unified Decision Workbench：今日市場狀態、候選變化、持倉警示、研究證據、資料品質與待處理 action item 在同一個工作流內。
2. Daily Decision Desk 與 Market Watch 的完整整合在 V2.0 評估；Market Watch / Smart Money 成為 Workbench 的市場證據 drill-down 或專家模式，不再需要使用者自己決定先看哪個 Tab。
3. Evidence Review、Strategy Lifecycle、Portfolio Review 形成同一個 evidence loop：提示 -> 觀察 -> forward outcome -> gap / decay -> 人工覆盤 -> 研究或策略調整。
4. 介面語彙從「功能分頁」轉為「決策任務」：今日要不要新增候選、哪些持倉要覆盤、哪些策略 evidence 變弱、哪些資料還不能信。
5. V2.0 仍不做自動交易；任何策略生命週期 action 都保留人工核准。

V2.0 啟動條件：

- V1.1 的 daily workflow 被實際使用後，能明確看出 Daily Decision 是自然入口。
- V1.2 至少完成 execution / microstructure 的核心 credibility gate，避免 Workbench 把不可信回測包裝得太漂亮。
- V1.3 已有足夠 evidence operations 節奏，知道哪些 dashboard 真的有用、哪些只是噪音。
- 有 migration / rollback 計畫，保留舊 Tab 或專家模式，不讓資訊架構重整破壞既有研究能力。

---

## 8. 分批 Commit / Push 建議

後續長線任務建議按以下批次推進，均先在 `dev` 或 `codex/*` 分支完成，不直接推 `main`：

1. 文件與版本對齊：版本路線圖、6M Roadmap、Snapshot、Manual boundary。✅ V1.1 closeout 已完成
2. V1.1 spec / plan：推薦 workflow bridge、UI scope、測試清單。✅ 已完成
3. V1.1 implementation batch A：Profile replay comparison service 與 Profile 進階摘要。✅ 已完成
4. V1.1 implementation batch B：推薦回放 workflow 文案、QA、Manual / Snapshot / Roadmap 更新。✅ 已完成
5. V1.2 credibility batch：execution model / microstructure / attribution，各自獨立 gate。✅ 已完成 v1
6. V1.3 operations batch：manual approval、weekly review、action item loop。✅ 已完成 v1
7. V1.4 history batch：weekly review history repository、CLI save/list、Evidence Review history dashboard。✅ 已完成 v1
8. V2.0 design spike：只做資訊架構 prototype / spec，不急著改主 UI。

---

## 9. 目前最合理的下一步

V1.1 至 V1.4 v1 已收尾，下一步不應直接宣稱 Profile 有效，也不應把降級做成自動按鈕。比較穩的順序是：

- V1.3 已把 promote / hold / demote_candidate / retire_candidate 相關 evidence 轉成可審核 weekly package 與 action item planning，而不是自動升降級。
- V1.4 已把 weekly review 封存為可回看的 history；下一步是用 V1.3/V1.4 weekly review 實際跑數週，觀察哪些 dashboard、blocking gaps 與 action item 真的有用。
- V1.2 residual 只在 source / execution model 契約明確時繼續深化，不要用未治理資料補漂亮圖表。
- V2.0 才評估 Unified Decision Workbench 是否要整合 Daily Decision、Market Watch、Evidence Review 與 Portfolio Review。

## 10. 更新記錄

- 2026-07-03：完成 V1.4 Evidence Review History v1，新增 weekly review history repository、CLI save/list 與 Research Lab `Evidence Review -> 覆盤歷史` 唯讀子頁；history 只保存人工覆盤快照，不啟用 production scheduler、不自動 lifecycle action。
- 2026-07-03：完成 V1.3 Evidence Operations & Manual Lifecycle v1，新增 weekly evidence operations package、manual approval summary、signal decay manual lifecycle candidates 與 append-only action item planning；production scheduler 仍未啟用。
