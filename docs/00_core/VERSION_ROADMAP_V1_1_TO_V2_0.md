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
| V1.1 | Decision Workflow Integration | 每日決策與市場觀察已可用，但使用流程還像多個分散工具 | Daily Decision Desk 成為起點，Market Watch / Smart Money 成為可下鑽的證據面板 |
| V1.2 | Research Credibility & Execution Model | 研究回測已有治理，但成交假設、微結構與 attribution 還不夠像真實決策 | 回測 / replay / forward evidence 更能解釋「為什麼可相信或不可相信」 |
| V1.3 | Evidence Operations & Manual Lifecycle | Evidence dashboard 已建立，但樣本、覆盤、人工核准流程還未形成日常節奏 | 形成每週覆盤、manual approval、signal decay 與 action item 的操作閉環 |
| V2.0 | Unified Decision Workbench | V1.x 驗證後，Daily Decision / Market Watch / Evidence / Portfolio Review 的邊界可以重整 | 形成單一決策工作台，舊 Tab 轉為 drill-down 或專家模式 |

---

## 3. V1.1：Decision Workflow Integration

建議定位：V1.1 不是大改版，而是把已完成的 V1 能力變成每天可順手使用的流程。

核心交付：

1. Daily Decision Desk 保持為每日入口，優先顯示今日 market regime、breadth、sector rotation、watchlist trigger、portfolio alert、risk prompt 與資料品質。
2. Market Watch / Smart Money 不急著合併進 Daily Decision Desk；先做成明確 drill-down：從 Daily Decision 的市場、產業、個股、籌碼警示可以回到對應市場觀察證據。
3. Research Lab / Evidence Review 只讀 evidence dashboard 保留在 Research Lab，但 Daily Decision 可以顯示 evidence summary 入口與「目前樣本仍不足 / pending / missing」狀態。
4. 觀察清單、推薦、研究、持倉警示之間補齊 cross-flow 文案與 navigation affordance，讓下一步動作更清楚。
5. Empty state 要誠實：正式 DB 沒 evidence rows 時，畫面要說明「目前還沒有可覆盤樣本」，而不是看起來像壞掉。

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

核心交付：

1. Portfolio replay execution model 深化：零股、買賣價差、完整撮合、跳空成交限制、成交率與未成交原因。
2. 台股微結構 preflight：處置股、分盤、全額交割、跳空鎖死、除權息 / 還原價時間軸。
3. rolling risk metrics：Rolling Sharpe / Sortino、VaR / CVaR、drawdown duration、turnover。
4. benchmark / industry / concept relative attribution：讓 forward evidence 不只看絕對報酬，也能看大盤、產業與題材背景。
5. 報告輸出深化：Excel 已完成，PDF 仍維持研究輸出 backlog；若要做，先以 evidence / attribution 可追溯為主。

V1.2 驗收 Gate：

- 所有成交假設在 UI、報告與 metadata 中可追溯。
- 不因新增微結構資料而破壞既有回測或推薦核心。
- 策略 / 回測修改必須附 no-look-ahead 自查與測試。

---

## 5. V1.3：Evidence Operations & Manual Lifecycle

建議定位：把 evidence 從「看得到」推到「每週真的用來修正決策流程」。

核心交付：

1. Evidence Review UI manual smoke closeout，確認 Forward Evidence、Live vs Research Gap、Signal Decay、Decision Quality 在有樣本與無樣本時都可判讀。
2. Multi-day dry-run record 轉成固定節奏：每天看 05:30 read-only 摘要，每週整理 pending / missing / blocking gaps。
3. Manual Approval Workflow：任何 production scheduler、lifecycle action、demote / retire、strategy promotion 都要有人工核准紀錄。
4. Signal Decay 與 Decision Quality 的 action item 開始回流到 Research Lab / Strategy Lifecycle，但不自動改策略版本。
5. 建立「決策覆盤週報」最小格式：本週觸發事件、完成 outcome、missing source、最大 gap、下週 action。

V1.3 驗收 Gate：

- Production scheduler 仍預設未啟用，除非通過 explicit approval。
- Evidence 樣本不足時只能輸出覆蓋率與品質缺口，不能包裝成策略結論。
- Decision Quality 是流程 evidence，不是績效或責備分數。

---

## 6. V2.0：Unified Decision Workbench

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

## 7. 分批 Commit / Push 建議

後續長線任務建議按以下批次推進，均先在 `dev` 或 `codex/*` 分支完成，不直接推 `main`：

1. 文件與版本對齊：版本路線圖、6M Roadmap、Snapshot、Manual boundary。
2. V1.1 spec / plan：Daily Decision 與 Market Watch cross-flow 設計、UI scope、測試清單。
3. V1.1 implementation batch A：navigation / drill-down / empty state / evidence summary。
4. V1.1 implementation batch B：workflow QA、Manual 更新、Full App smoke。
5. V1.2 credibility batch：execution model / microstructure / attribution，各自獨立 gate。
6. V1.3 operations batch：manual approval、weekly review、action item loop。
7. V2.0 design spike：只做資訊架構 prototype / spec，不急著改主 UI。

---

## 8. 目前最合理的下一步

下一步應先做 V1.1 spec / plan，而不是直接合併 Tab：

- 先盤點 Daily Decision Desk 目前有哪些 section 可以安全下鑽到 Market Watch / Smart Money / Research Lab / Portfolio。
- 再定義每個下鑽只讀什麼 service snapshot，不讓 UI 偷算 domain logic。
- 接著做一小批 UI 串接與 empty state，讓你現在就能每天用，同時讓 dry-run 繼續累積。
- 等你實際用幾天後，再決定 V2.0 的 Unified Decision Workbench 要收斂哪些 Tab。

這樣的節奏可行，因為它把「你現在想繼續推進」和「資料可信度還在驗證」拆開：V1.1 可以改善操作流程；資料有效性則由 evidence dry-run、forward outcome 與 manual review 繼續回答。
