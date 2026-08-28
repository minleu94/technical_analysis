# UI 功能文件（Qt）

> **最後整理**：2026-08-27
> **適用範圍**：`ui_qt/` 目前主要使用者介面。
> **狀態判讀**：目前狀態以 `docs/00_core/PROJECT_SNAPSHOT.md` 為準；未來 6 個月工程方向以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準；本文件只描述 UI 功能與操作入口。
> **完整操作**：安裝、逐步操作、參數、結果判讀與排錯見 [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md)。

---

## 一、UI 定位

Qt UI 不是單純顯示股票名單，而是把「資料更新、候選觀察、策略研究、推薦、持倉檢查、Agent runtime 觀測」串成可回溯的投資決策工作台。

目前入口為：

- `ui_qt/main.py`
- `ui_qt/views/`
- `ui_qt/widgets/`

主要設計原則：

- UI 只負責呈現、輸入、互動與事件轉接。
- 核心計算、資料讀寫與策略邏輯必須在 service / domain 層。
- Recommendation、Backtest、Portfolio 之間的交接必須保留來源 metadata。
- 策略、回測、績效、持倉與金融金額計算不得在 UI 內新增裸 `float` 核心計算。
- 涉及回測或推薦訊號時，必須維持 Look-ahead bias 防線。

---

## 二、頂層 Tab

### 1. 數據更新

主要 view：

- `ui_qt/views/update_view.py`
- `ui_qt/widgets/sqlite_inspector_widget.py`

主要能力：

- 每日股價、大盤、產業、券商分點與技術指標更新；每日股價一鍵更新包含 TWSE + TPEX，TPEX timeout 以 warning 呈現且不阻斷其他資料同步。
- TWSE 每日股價若明確回報失敗，單一來源流程會在 TPEX／SQLite／技術指標之前 fail-closed；只有已驗證的官方無交易日（`no_data_skipped_dates`）才允許後續流程繼續。
- 快速更新（僅 SQLite）與安全更新（CSV + SQLite）分流；兩者預設補齊結束日前最近 10 個工作日，快速更新跳過大型合併，安全更新保留完整 CSV 合併與 SQLite 同步。
- SQLite 狀態檢查、資料表檢視、唯讀 SQL preview，以及具有日期預設（單日今天、區間本月）、完整日期欄寬、穩定排序、重複顯示欄名防護、分頁控制與 stale-result 防護的檢視器分頁。
- 更新狀態卡只在 service 回傳明確的 `ok`／`success`／`current`／`normal` 時顯示綠色「最新」；`error`、`missing`、`empty`、`unavailable` 與部分狀態查詢失敗會顯示異常，不會因描述文字含「最新」而假綠。inline 摘要也會把 `success`／`current`／`normal` 統一顯示為中文「正常」。狀態 payload 缺少資料源時會清除上一輪卡片與 inline 摘要，避免殘留數字或「0 筆」被誤讀；全域檢查也會同步刷新六個核心與三個候選來源頁面的 inline 摘要；個別來源詳情查詢失敗時只標記該來源，不污染其他卡片；全域檢查失敗時九個來源摘要會同步清除舊內容並保留共同錯誤原因。尚未執行檢查的 placeholder 不會被解析成狀態，燈號維持「未檢查」。候選來源仍標示為 research-only，不會因此進入正式評分或交易流程。
- 更新頁所有「今日」日期控件都以台灣市場日期為基準，不受桌面作業系統時區跨日影響；localized `不可用` 會落到異常燈號，避免被誤讀為單純待更新。
- 更新流程的進度由外層 coordinator 統一映射，技術指標子流程固定落在外層區間內；每日資料合併會回報檔案／讀取批次／寫入批次，若沒有新 CSV 會以結構化 no-op 狀態揭露「資料已是最新」，CSV 匯出會回報查詢總筆數與已處理筆數，單一工作生命週期內不會倒退，最終資料狀態檢查完成且通過後才顯示 100%。所有 CSV／SQLite／合併／技術指標／匯出寫入工作具互斥保護，重複啟動會提示等待，唯讀來源詳情仍可並行查詢；合併／匯出取消均保留原子目標檔，不在半個檔案內提交。
- SQLite sync 在寫入前會將日期、股票代號與股票名稱的受治理中英文欄位別名正規化為 canonical 欄位，並統一日期／四碼代號格式；只處理寫入副本，不改 raw CSV，缺必要欄位仍維持 fail-closed。
- 快速／安全一鍵更新先驗證更新前總覽；核心資料源若明確回報 `error`／`failed`／`exception`，會在任何寫入前 fail-closed 並回傳失敗資料源，避免在基線已不可讀時繼續產生部分更新。
- SQLite Inspector 啟動與刷新採明確 `mode=ro`／`PRAGMA query_only=ON`；資料庫不存在、損毀或不可讀時保留頁面並顯示「SQLite 不可用」，不建立空資料庫，也不讓主視窗因 Inspector 初始化失敗而中止。若使用 immutable fallback，頁首會明示快照可能非即時。
- UpdateService 的 overview／detail／technical coverage 狀態查詢共用同一個 query-only adapter；不論資料庫是否已存在，狀態讀取都不建構可寫 `DBManager`、不初始化 schema 或切換 WAL。
- Portfolio 的目前價格／未實現損益投影也共用 query-only adapter；缺少正式 SQLite 時只降級讀取既有 CSV，不會因打開持倉頁而建立空 `twstock.db`。
- Windows 一般 read lock 不可取得時，狀態 payload 會帶 `read_mode=immutable_fallback` 與提醒；UpdateView 以黃色「待更新」及 inline `讀取模式`／`提醒` 揭露可能只到最後已提交內容，不把快照假裝成即時讀取。
- 每日股價分頁的 TPEX 背景補齊會在頁面內顯示 `尚未啟動`／`執行中`／`完成`／`失敗` 與最後更新時間；狀態 JSON 無法建立或讀取時會顯示錯誤並記錄日誌，無法可靠追蹤時不啟動背景程序，避免按鈕已顯示執行中但沒有可查進度的假狀態。日期範圍同步若發生例外也會保留可見日誌。
- UpdateView 內容使用可垂直捲動的工作區；窄版（小於 720px）會將來源導覽移到上方、六張核心狀態卡改為雙欄、候選卡改為單欄、操作按鈕改為直列，避免固定 160px 導覽與六欄卡片把資料更新畫面壓成不可讀細條。
- 券商分點資料更新、合併、長碼解密與品質狀態呈現；SQLite `broker_flows` 唯一鍵包含 `trade_type`，可保存同日買超 / 賣超榜單。
- 「三大法人」、「信用交易」、「集保股權」與「自動排程狀態」為唯讀治理頁；前三者只讀 SQLite 筆數／最新決策日期，`MISSING` 或 0 筆代表未接線或尚未匯入，不能解讀為中性數值，也不提供誤導性的下載控制。

文件同步重點：

- 更新流程改動需同步 `docs/03_data/` 相關指南。
- SQLite / CSV 雙軌行為改動需同步 `docs/01_architecture/system_architecture.md` 與 `docs/03_data/SQLITE_STORAGE_GUIDE.md`。

### 2. 市場探索

主要 views：

- `ui_qt/views/decision_desk_view.py`（「市場總覽」唯一 Decision Desk instance）
- `ui_qt/views/market_regime_view.py`
- `ui_qt/views/strong_stocks_view.py`
- `ui_qt/views/weak_stocks_view.py`
- `ui_qt/views/strong_industries_view.py`
- `ui_qt/views/weak_industries_view.py`
- `ui_qt/views/smart_money/smart_money_flow_view.py`

子 Tab：

- 市場總覽
- 大盤指數
- 強勢個股
- 弱勢個股
- 強勢產業
- 弱勢產業
- 主力流向

主要能力：

- 市場總覽以 answer-first dashboard 顯示結論、焦點與來源可見性；Workbench「決策來源」只導向此唯一實例，不建立第二份 widget。
- 月營收、三大法人、信用交易、TDCC 與券商分點卡片保留 status、row count、available date、coverage 與 warning。`row_count=0`／MISSING／DEGRADED 表示缺漏，不是中性分數或業務數值為零，且不參與 action、focus、Score 或品質聚合。
- 「資料更新 > 全部資料」的月營收狀態卡分開顯示已匯入期別與依該期全部資料 `available_date` 判定的目前完整 PIT 可用期別；只要同一期仍有公司尚未生效，該期就會顯示在待生效數與完整可用起始日中，不會誤標成更新失敗。
- 市場 regime 判斷。
- 強弱勢股票與產業篩選。
- 強弱勢探索表格會在載入中、成功（筆數／掃描範圍）、空結果與失敗時顯示可見狀態；刷新失敗會清空過期模型，不把上一輪排名留在畫面上冒充目前資料。
- Smart Money Terminal：個股資金流向、分點進出追蹤、張數 / 金額品質標示。
- 券商 week／month／股票明細採背景查詢並具 stale-result guard；loading 與單一來源錯誤不凍結主 UI，錯誤以 fail-soft warning 呈現。
- 可把觀察標的送入候選池 / Watchlist。
- 候選池在載入中、成功、空清單與失敗時都顯示可見狀態；空清單／失敗使用真正的空模型，不插入 `-` 佔位列，避免把狀態提示誤讀為候選標的。

文件同步重點：

- 籌碼、分點、資料品質語意改動需同步 `docs/04_broker_branch/`。
- Regime 或 scoring 輸出語意改動需同步 `docs/02_features/SCORE_EXPLANATION.md`。

### 2.5 決策工作台

主要 view / model：

- `ui_qt/views/workbench_view.py`
- `ui_qt/models/workbench_table_models.py`

主要能力：

- Phase 2 Unified Decision Workbench MVP shell，頂層分頁名稱為「決策工作台」。
- 總覽第一屏新增「今日行動中心」：只用既有 `WorkbenchDashboardDTO` 的資料狀態、review items、Advice DTO 與 Action Items，整理資料／市場／Advice／持倉四張行動卡與一個下一步按鈕。按鈕僅呼叫既有數據更新、Daily Decision、推薦分析或持倉管理導覽 callback；不讀 DB、不更新資料、不執行 Policy、不寫入持倉或交易。
- 主 shell 使用 `ui_qt/widgets/adaptive_workspace_stack.py`，只讓當前可見工作區貢獻尺寸提示，避免隱藏工作區的圖表／設定面板鎖死視窗最小尺寸；主視窗在窄桌面寬度會暫時收合左側導覽，但不改變 workspace、資料載入或 service 行為。
- Runtime 窄版（小於 720px）會把治理左右面板改為上下排列，並以內嵌垂直捲動保留完整診斷內容；Session context status strip 會依可用寬度截斷文字。主視窗明確窄版下限為 320px，避免 Runtime 的長路徑提示把視窗鎖在桌面尺寸。
- Runtime 窄版（小於 720px）會把治理左右面板改為上下排列，並以內嵌垂直捲動保留完整診斷內容；Session context status strip 會依可用寬度截斷文字。主視窗明確窄版下限為 320px，避免 Runtime 的長路徑提示把視窗鎖在桌面尺寸。
- 第一版已從中文 read-only shell 推進到 background evidence feed / read-only Action Items 人工佇列體驗，並完成 Phase 2 read-only Operating Loop closeout：呈現 status strip、今日待判讀、背景證據流、依 severity / queue group / source 排序的只讀 Action Items、操作節奏、Evidence mode / data quality、Daily Checklist、warnings / degraded source。
- 只透過 `WorkbenchSourceService` 取得 `WorkbenchDashboardDTO`，或直接呈現呼叫端提供的 DTO；UI 不直接讀 SQLite、不讀 replay DB、不寫 DB、不啟用 scheduler。
- Workbench 的 current Decision Desk／Pre-V2／Evidence projection 以台灣市場今日為日期上限；正式來源若含 future snapshot，畫面保留 raw future date 的 warning／source gap，但不把它當成 current evidence 或完成 gate。
- 背景證據流只彙整既有 DTO / service payload：Daily Decision snapshot、Evidence Review readiness、Portfolio alerts 與可選 replay summary diagnostics；不在 UI 端重算任何 source gap、portfolio、scoring、backtest 或 lifecycle。
- 只讀 Action Items 只列人工待處理事項；每列必須帶 `severity`、`queue_group`、`source_label`、`source_trace`、`degraded_reason`、`sort_rank` 與 `drilldown_target`，且 `write_intent=false`。Qt model 只顯示 DTO payload，drill-down target 必須對齊舊頁導向（Daily Decision、Evidence Review、Portfolio），Workbench 不建立 action item repository、不 append DB、不自動標記完成。
- Read-only Operating Loop 只從 `WorkbenchDashboardDTO.operating_loop_steps` 顯示 daily first-look、manual queue、weekly review history、multi-day dry-run、manual review note 與 scheduler gate；每列必須帶 `source_trace`、`linked_item_ids`、`drilldown_target`、`guidance` 與 `write_intent=false`。Qt model 不標記完成、不寫 DB、不補 Phase 0 時間 gate。
- 若週期紀錄位於隔離 working-copy DB，Workbench 只會讀取 owner 明確提供的 `approved-weekly-history-projection.v1` 路徑，絕不掃描暫存目錄或合併 DB；projection 固定 `formal_credit_authorized=false`，僅顯示已具名核准的 weekly Gate 計數，不構成 formal clock credit、scheduler、交易或任何下游資格。
- Evidence Feed、Action Items 與 Operating Loop 空狀態必須說明「目前沒有 DTO rows」不等於 gate passed 或 actionable 建議；degraded 狀態只提醒人工覆盤資料不完整，不補值、不觸發 replay / scheduler / lifecycle。
- Advice 區以 `WAITING_FOR_ADVICE_DTO`、`NO_ELIGIBLE_ADVICE`、`ADVICE_DTO_ERROR` 分別呈現尚未載入、已載入但無合格建議、與 DTO 損毀／安全拒絕；來源降級但仍有有效 recommendation 時仍渲染表格與 warning，不得誤標為 DTO error。
- Optional Historical Replay JSON summary 只作 simulated evidence input；若 DTO 帶 replay summary，data quality 區塊必須揭露 `simulated_scheduler`、source gap、payload gap、outcome maturity、benchmark coverage、missing industry benchmark 與 pending future-data。
- Workbench `Evidence` 子頁已由 placeholder 替換為唯讀 `ResearchConsoleView`：三區依序顯示固定 fail-closed Safety Boundary、Development Dataset V0 / Rule baseline / ML challenger / E2E frozen projection，以及 EV1–EV5、P0-13、獨立 Broker lane、P0 Data Source Control Center 與 Artifact Inspector。Control Center 固定保留 13 個 P0 source，顯示 contract、machine/audit、人工 decision、blockers 與 downstream eligibility；沒有 audit artifact 時明示 `contract_only`／`Not supplied`，不把缺資料誤顯示為 ready。資料只來自 `ResearchConsoleSourceService` 的 injected mapping 或顯式 sanitized JSON path；缺 artifact / 欄位顯示 Missing / Unknown，不補零、不讀 DB、不重算 domain logic。
- Research Console 不提供 Apply、Promote、Retrain、Blend、Accept Source 或 Trade；development / candidate / provisional / degraded / fixture / replay 以文字狀態與顏色共同區分，不能解讀為 formal OOS、forward evidence、source accepted 或 production ready。

防線：

- 不重算 scoring、recommendation、portfolio、backtest 或 lifecycle。
- 不產生買賣建議、不下單、不套用 lifecycle action。
- Phase 0 weekly history 目前由具名 owner-approved projection 顯示 `3/3 ready`，但 `formal_credit_authorized=false`；multi-day dry-run 亦為 `3/3 ready`。畫面仍需明確揭露這只是 read-only readiness，不構成 Formal evidence credit 或 production scheduler approval；pending sidecar 週期仍須 owner/reviewer 審核，兩者皆不能用 fixture、手動改表或 replay 取代。

### Gate 1 Advice（決策工作台）

決策工作台在 DTO 已提供 Advice 時，會顯示 mode、decision / data-as-of date、action、理由、資料品質、可成交性、source trace，以及 Portfolio 的 target/current/gap。畫面是唯讀：不會建立委託、寫入資料庫、套用 lifecycle 或重算 scoring / portfolio / backtest。

- Guided Mode 只接受 promoted strategy；Professional Mode 的 candidate 僅供研究檢視，不能混作 formal Advice。
- `NO_NEW_POSITION`、`RESEARCH`、`AVOID` 是資料、風險、可成交性或策略狀態不符合時的正常安全輸出，不表示系統故障。
- 平衡限制為最低現金 `2000 bp`、最多 8 檔、單檔上限 `1500 bp`；UI 只呈現 contract 結果。
- Advice 不保證報酬、不是 broker 指令，且不解除 weekly evidence、production scheduler 或其他產品 Gate。

### 3. 策略回測

主要 views：

- `ui_qt/views/backtest_view.py`
- `ui_qt/views/backtest/config_panel.py`
- `ui_qt/views/backtest/result_panel.py`
- `ui_qt/widgets/fast_chart_widget.py`

主要能力：

- 單股回測、候選池批次回測、推薦組合回放。
- Strategy registry / preset / promotion 整合。
- Walk-forward、baseline comparison、overfitting risk、validation status。
- Fixed / quantile threshold mode UI 控制與無交易診斷。
- 結果保存已接入 Research Run Registry；Research Lab 內新增 Registry 比較子頁，可篩選、分頁、多選 2 至 5 個 run，顯示 comparability、參數差異、normalized equity、metrics、Regime 與保存 benchmark。Registry-based Promote Gate 已接入 service 層，且 Month 6 起需通過 lifecycle gate；策略版本 JSON 與 Registry 回填具補償與 reconciliation 防線。
- 規格化 Excel 報告匯出：單股、批次及組合回放結果的背景原子匯出，缺值自動標記 N/A。
- Fast chart renderer：權益曲線、回撤曲線、報酬分佈、持有天數。
- 策略回測日期欄與 Research Lab 證據覆盤日期篩選採受控日曆 popup；回測日期開啟時定位今天，未設定的 evidence 日期篩選也定位今天，不落到 sentinel 年份。
- Research Lab「證據覆盤 > 排程狀態」會分開顯示 freshness warnings、pipeline warning 與 advisory 的 occurrences / unique types、pipeline overall status、推薦結果 research-only write 與 production evidence / trading write risk；pipeline degraded 時不會只因 exit code 0 顯示為 passed，`ready_with_advisories` 也不會被誤標 degraded。
- Research Lab「覆盤歷史」dashboard 採 query-only history repository；缺少 history DB／table 時顯示明確唯讀診斷與建立指引，不會因打開畫面而初始化空 schema。

回測防線：

- 回測訊號只能使用決策當下可取得的資料。
- `next_open` / `close` 撮合假設必須透過 metadata 或 warning 呈現。
- Quantile 模式的門檻需由策略執行器輸出，不應在 UI 或 service 端用完整期間重算。

文件同步重點：

- 回測邏輯變更需同步 `docs/02_features/BACKTEST_LAB_FEATURES.md`。
- 策略參數與門檻語意變更需同步 `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`。

### 4. 推薦分析

主要 view：

- `ui_qt/views/recommendation_view.py`

主要能力：

- Profile / mode / strategy config 推薦。
- Why / WhyNot / Explain panel。
- Explain 的圖形理由會顯示 rolling detector 已確認的型態名稱、方向與距確認日；若只有方向訊號而沒有型態名稱，會顯示保守的 generic 圖形訊號，不從分數臆測具體型態。
- Regime snapshot 與推薦 metadata 保存。
- 推薦結果保存與 round-trip 載入。
- 一鍵送策略回測。
- 送 Research Lab 批次回測。
- 建立候選池 / Watchlist。
- Fixed / quantile 門檻模式與 eligible universe 橫斷面百分位排名。
- 可選月營收 YoY 最低值與 PE 最高值篩選；啟用時只讀 `available_date <= decision_date` 的 PIT 基本面版本，無法標準化決策日期、缺 PE／去年同期營收或不符門檻者寫入 screening matrix 的 `skipped` 原因，不補零也不讀未來資料。
- 目前推薦 Excel 報告匯出：包含今日配置、Regime 狀態與股票名單的背景原子匯出。

推薦防線：

- Quantile / percentile 推薦必須先固定當日 eligible universe。
- 母體不足時應拒絕降級並顯示可理解錯誤。
- 排序需穩定化，避免相同分數因輸入順序造成結果不可重現。

文件同步重點：

- 推薦分數與百分位語意需同步 `docs/02_features/SCORE_EXPLANATION.md`。
- 推薦策略 contract 需同步 `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`。

### 5. 觀察清單

主要 view：

- `ui_qt/views/watchlist_view.py`

主要能力：

- 候選池 / watchlist 管理。
- 從 Market Watch、Recommendation、Backtest 取得候選標的。
- 支援後續送入 Backtest / Research workflow。

文件同步重點：

- Watchlist 語意若改為正式投組、研究候選池或交易候選池，需同步 Snapshot、User Guide 與 architecture。

### 6. 持倉管理

主要 view：

- `ui_qt/views/portfolio_view.py`

右側子 Tab：

- 交易歷史
- 覆盤日誌
- Paper Portfolio
- 情境壓力
- 策略與價格監控
- 生命週期回顧
- 籌碼監控

主要能力：

- 手動記錄交易並投影目前持倉。
- 「匯入交易 CSV」先做 UTF-8／CP950、欄位、買賣別、數值、日期與重複交易 ID 預覽；只有檔案 hash 未變更且使用者二次確認後，才由 `PortfolioService.record_trades()` 批次驗證並 append，取消或錯誤不寫入。
- 交易歷史提供常駐的「刪除選取交易」操作；只有選取一筆原始交易時才可按，經確認後交由 `PortfolioService.delete_trade` 驗證剩餘交易仍可重算合法持倉。持倉彙總列不會直接刪除整檔歷史。
- 保存 Recommendation / Backtest / Strategy Version 來源 metadata。
- 顯示目前價格、未實現損益、停損 / 停利與條件監控。
- 頂端摘要只顯示有最新價格持倉的「持倉市值（未含現金）」；缺價格會顯示 N/A 與缺漏股票，不把投入金額／已實現損益冒充完整 NAV。
- 情境壓力：由 `PortfolioStressLabService` 對已標記持倉套用固定、可重播的研究情境；缺價只做部分計算，輪動／來源中斷等缺少必要輸入時 fail-closed，不寫資料、不改持倉、不產生交易指令。
- Stress 歷史：按「保存研究快照」並經明確確認後，才由 `PortfolioStressHistoryRepository` 以 hash-idempotent append-only 方式保存目前情境結果；下方歷史表由 `PortfolioStressHistoryReadService` query-only 讀取，缺 DB 不初始化，固定揭露研究用途與 `writes_allowed=false`。
- Paper Portfolio：由 `PaperPortfolioReadinessService` 唯讀讀取 daily status、append-only snapshot 與可選 Equal Weight ledger；畫面顯示 raw 累積筆數與最新可採用 snapshot，遇到 future row 會保留 blocker／diagnostic、降級並排除於 current projection。缺 snapshot、benchmark 或成本帳時明示 `partial`／`degraded`／`not_computable`，不建立 schema、不把 paper 結果冒充正式持倉或投資績效。
- Paper Trade Ledger v1：由獨立 append-only contract 保存研究用 fill event，要求 requested／filled 數量、狀態、Decimal 成本、turnover、execution gap 與來源；Portfolio readiness 會唯讀顯示 ledger 狀態與 full／partial／reject／override 統計，缺欄位不放行 weekly report。
- Paper 成交 CSV：Paper Portfolio 分頁可先預覽完整 execution CSV，要求狀態、reference／fill price、Decimal 成本、turnover、execution gap 與來源事件；只有二次確認且檔案 hash 未變更才由 `PaperTradeImportService` atomic append 至 Paper Trade Ledger，不更新手動 Portfolio、snapshot 或 broker。
- Paper 成交範本：同一分頁可先匯出只含受治理欄位標題的空白 CSV 範本；範本不填入示例成交、拒絕覆寫既有檔案，也不建立 ledger。填入真實 execution 後仍必須回到 Paper 成交 CSV 的預覽／二次確認流程。
- Paper weekly evidence v1：Portfolio 的 Paper 分頁可按「計算最近週報」，以最近 snapshot 邊界唯讀讀取 Paper snapshot、Equal Weight ledger 與成本帳，顯示毛／淨報酬、benchmark、淨超額、成本、換手與觀測日數；未來 period／snapshot、期間邊界、成本欄位或 ledger 缺件時維持 `partial`／`degraded`／`not_computable`，不補值、不寫資料。Equal Weight builder 也會在 preview／apply 前拒絕 future snapshot。
- 顯示策略版本或推薦來源追蹤。
- 生命週期回顧：顯示 thesis 狀態、來源追溯、執行落差、訊號 / 市場 / 資料品質 attribution 與摘要 tokens。
- 籌碼監控：主力淨買賣、集中度、連續流向天數與風險級別。
- 從 Portfolio 下鑽至 Market Watch 的主力流向並定位個股。

持倉防線：

- 金額、成本、股數、PnL 必須使用 domain/service 層的 Decimal / 整數單位。
- UI 不應自行重算金融核心數值。
- 來源追溯不能被 UI 手動覆蓋成不可追蹤狀態。

目前 Gate 4 尚未收口的部分：Paper Portfolio 的完整 cash-flow ledger、受控 Paper producer 的實際來源資料與人工 review、Equal Weight builder 的明確確認後正式 output review、Stress Lab 的正式 evidence 累積與跨期間 review。現有 UI 已能揭露 Paper snapshot／cost ledger readiness、預覽／匯入 Paper fills、重建最近週報並保存研究用 Stress history，但實際 producer 輸入、成本後證據、壓力結果與 forward outcome 的關聯及 Gate review 仍未完成。

文件同步重點：

- Portfolio 來源模型、條件監控、生命週期回顧或籌碼監控改動需同步 Snapshot、architecture 與 Manual。

### 7. Runtime Observatory

主要 view：

- `ui_qt/views/runtime_view.py`
- `ui_qt/bridges/runtime_event_bridge.py`

主要能力：

- 顯示 AI Runtime Subsystem 狀態。
- 觀測 FSM 狀態、health snapshot 與 event stream。
- 透過 Qt bridge 接收 runtime event bus。

文件同步重點：

- Runtime 狀態、事件或治理規則改動需同步 `docs/01_architecture/runtime_observatory_rules.md`。

---

## 三、跨 Tab 工作流

### 市場觀察到候選池

1. 使用 Market Watch 找出強勢 / 弱勢 / 籌碼異常標的。
2. 加入 Watchlist / Candidate Pool。
3. 候選池可送 Backtest 或作為 Recommendation / Research workflow 的輸入。

### 推薦到回測

1. Recommendation 依 Profile、Regime、strategy config 產生推薦。
2. 使用一鍵送回測或送 Research Lab 批次回測。
3. Backtest 保存 run metadata，必要時 Promote 為策略版本。

### 回測到持倉

1. Backtest run 若符合條件，可建立或輔助建立持倉。
2. Portfolio 保存 `source_type`、`source_id`、strategy / recommendation metadata。
3. 持倉後續用價格、regime、score、籌碼監控做假設檢查。

### 持倉回到研究

1. Portfolio 顯示假設失效、停損 / 停利、籌碼惡化或來源策略資訊。
2. 使用下鑽回 Market Watch / Smart Money 查原因。
3. 回到 Backtest / Recommendation 調整研究假設。

---

## 四、UI Contract

### UI 可做

- 顯示資料、表格、圖表與警示。
- 收集使用者輸入並轉成 service config。
- 轉接跨 Tab 事件。
- 顯示 service/domain 回傳的 metadata、diagnostics 與 validation status。

### UI 不應做

- 不在 UI 內新增策略核心計算。
- 不在 UI 內重算金融金額、PnL、持倉 average cost。
- 不在 UI 內用完整期間資料重算回測門檻或推薦百分位。
- 不直接寫正式資料根目錄，必須透過既有 service / repository。
- Backtest / Research Lab 的新保存入口必須呼叫 `ResearchRunService.save_run()`；UI 只能送出已完成結果 DTO 與執行快照，不可保存 stale pending result。

---

## 五、目前缺口與 6M Roadmap 對齊

近期 UI 相關缺口：

- Phase 5 大表格分頁已完成 (SQLite 檢視器分頁)。
- 規格化 Excel 報告輸出已完成；PDF 仍待完成。
- Research Run Registry 的基礎保存入口、第一版跨 run 比較 UI 與 registry-based Promote service Gate 已完成；後續仍可補更完整的 reconciliation 操作 UI。
- Factor Layer、營收估值、三大法人資料加入後，需要新增可檢查資料品質與 available date 的呈現方式。

對應文件：

- [PROJECT_SNAPSHOT.md](../00_core/PROJECT_SNAPSHOT.md)
- [ROADMAP_6M_ENGINEERING.md](../00_core/ROADMAP_6M_ENGINEERING.md)
- [DEVELOPMENT_ROADMAP.md](../00_core/DEVELOPMENT_ROADMAP.md)
- [system_architecture.md](../01_architecture/system_architecture.md)
- [BACKTEST_LAB_FEATURES.md](BACKTEST_LAB_FEATURES.md)
- [USER_GUIDE.md](USER_GUIDE.md)
- [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md)
