# V2.0 Unified Decision Workbench Phase 1 設計

## 目標

V2.0 Phase 1 建立 Unified Decision Workbench 的唯讀設計原型，先驗證資訊架構與每日使用動線，再決定是否進入 Phase 2 MVP。

第一屏採用「今日任務中控台」：先回答今天需要人工判讀什麼，再提供 Evidence、Market、Portfolio 與 Daily Checklist 的 drill-down。這一版不改正式 production UI，不啟用 scheduler，不新增交易能力，也不宣稱任何策略或推薦具備投資有效性。

## Read-only Prototype Boundary

### Scope In

- Unified Decision Workbench 第一屏資訊架構。
- 「今日任務中控台」作為 V2.0 第一屏。
- Evidence mode 作為 drill-down，承接現有 Evidence Review、Forward Evidence、Live vs Research Gap、Signal Decay、Decision Quality 與覆盤歷史。
- Daily Checklist 作為每日流程檢查區，承接 freshness check、evidence dry-run、manual review note 與 scheduler-off 狀態揭露。
- Historical Replay `_reference_fix` JSON summary 可作 Phase 1 的 evidence quality input，用來呈現 source gap、payload gap、event family、outcome maturity、benchmark availability 與 industry gap。
- Prototype 可使用 mock data、read-only adapter 或既有 DTO snapshot，不寫正式 DB。
- 設計文件需可直接轉成 Phase 1 read-only prototype implementation plan。

### Scope Out

- 不改 production 主 UI 的既有 8 個工作區。
- 不啟用 production scheduler。
- 不寫正式 evidence DB。
- 不新增交易、下單、持倉自動調整或 lifecycle action。
- 不改 `ScoringEngine`、推薦分數、回測績效、Portfolio PnL 或策略權重。
- 不接新外部資料源 ingestion。
- 不用 prototype 結果宣稱投資有效性。

## 第一屏資訊階層

第一屏分成四層：

1. **狀態列**
   - 交易日 / 最新資料日期。
   - Daily Decision data quality。
   - Evidence gate 狀態，例如 `waiting_for_time`、weekly history `0/3`、multi-day dry-run `1/3`。
   - Production scheduler 狀態，固定揭露 write-mode off。

2. **今日待判讀**
   - 候選股 review item。
   - Why Not / liquidity warning。
   - Portfolio alert / thesis invalidation review。
   - Evidence sample insufficiency。
   - Manual note / action item。

3. **Evidence 與風險側欄**
   - Forward Evidence 摘要。
   - Live vs Research Gap 摘要。
   - Signal Decay candidate 摘要，固定 `apply_action=false`。
   - Decision Quality process review 摘要。
   - Read-only Agent summary，必須保留 limitations 與 source trace。

4. **底部 contextual drill-down**
   - Market Context：market breadth、sector rotation、smart money quality。
   - Portfolio / Watchlist：watchlist trigger、portfolio alert、journal link gap。
   - Daily Checklist：freshness check、evidence dry-run、manual review note。

## 使用者工作流

每日進入 Workbench 時，使用者先看狀態列確認資料與 scheduler 邊界，再處理「今日待判讀」清單。

建議工作流：

1. 檢查資料品質與 scheduler-off boundary。
2. 讀取今日待判讀清單。
3. 點入候選股 review，看 Why / Why Not / Risk / Evidence / Data quality。
4. 點入 Portfolio alert，確認警示來源與 thesis 是否需要人工覆盤。
5. 點入 Evidence mode，查看 forward sample、live gap、decay 與 decision quality。
6. 回到 Daily Checklist，完成 manual review note。

此流程不產生買賣建議，不修改持倉，不自動套用 lifecycle action。

## 架構設計

Phase 1 prototype 應位於 read-only presentation boundary。若需要程式原型，建議新增獨立的 prototype service / DTO，而不是改既有 production view。

建議元件：

- `WorkbenchDashboardDTO`
  - `status_strip`
  - `review_items`
  - `evidence_summary`
  - `market_context`
  - `portfolio_watchlist_summary`
  - `daily_checklist`
  - `access_boundary`

- `WorkbenchReadOnlyComposer`
  - 只組合既有 service / DTO / read model。
  - 不重新計算 scoring、screening、portfolio、broker flow、PnL 或 strategy lifecycle。
  - 缺資料時輸出 `MISSING` / `DEGRADED` 與 diagnostics。

- Prototype UI / artifact
  - 可先是 standalone HTML mockup、Qt prototype view 或 screenshot-driven design doc。
  - 不掛到正式主 UI navigation，除非進入 Phase 2 MVP。

## 資料流

Workbench 只能讀取下列已存在或可唯讀提供的資料：

- Daily Decision Desk snapshot / section DTO。
- Evidence Review read models。
- Evidence Operations weekly review history。
- Pre-V2 readiness summary。
- Historical Replay `_reference_fix` JSON summary；只能讀 JSON summary，不直接掃 replay DB。
- Portfolio alert summary / attribution。
- Watchlist trigger summary。
- Read-only Agent report sample。

資料流方向：

```text
Existing read-only services / DTOs
        |
        v
WorkbenchReadOnlyComposer
        |
        v
WorkbenchDashboardDTO
        |
        v
Read-only prototype UI / design artifact
```

禁止反向呼叫 UI state、writable repository migration、pipeline confirm、scheduler registration 或 broker / order API。

## 錯誤處理與降級

- 缺 DB / 缺 table：顯示 diagnostics，不建立 schema。
- 缺 Daily Decision snapshot：標示 source missing，不讀 UI state 偽造。
- evidence sample 不足：顯示 insufficient sample，不解讀為策略成功或失敗。
- `waiting_for_time`：明確說明需要真實週期累積，不可用 fixture 或手動改表替代。
- Historical replay input：必須標示 `historical_replay` / `simulated_scheduler`，並清楚揭露它不滿足 Phase 0 weekly / multi-day gate。
- Benchmark reference return：`_reference_fix` replay 中 benchmark return / excess 可呈現為可用，但不得轉成投資有效性結論。
- Industry reference return：大量缺值時顯示 `missing_industry_benchmark` / `DEGRADED`，說明原因是舊 recommendation payload 缺 sector / industry，不填 0。
- 舊 recommendation 缺 screening matrix / payload：只列 warning / diagnostic，不回補、不重算。
- scheduler 狀態：在 Phase 5 approval 前固定顯示 production write-mode off。

## 測試與驗收

Phase 1 設計驗收：

- Spec 明確列出 Scope In / Scope Out 與 scheduler 禁止事項。
- 第一屏資訊階層已通過人工確認。
- Evidence mode 與 Daily Checklist 的角色已明確定義。
- Prototype 不改 production UI。

若進入程式 prototype，最低測試 gate：

- Composer unit tests：缺資料、`waiting_for_time`、scheduler off、quality / warnings。
- UI contract test：prototype UI 不 import scoring、screening、portfolio core、broker / order API。
- `py_compile` 覆蓋新增 Python 檔。
- 若修改 Qt UI，再跑專案 UI gate：
  - `.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=`
  - `.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py`
  - `.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`

## Phase 1 決策

- Prototype 先採 standalone artifact / read-only composer 設計，不掛入正式主 UI navigation。
- Phase 1 可讀取 `_reference_fix` replay summary 輔助設計 Evidence mode，但第一屏仍以「今日決策任務」為產品重心；replay 只提供 simulated evidence maturity 與 gap context。
- Phase 2 MVP 預設評估「漸進改造現有 Daily Decision Desk」優先於新增第 9 個頂層工作區，避免工作區數量繼續膨脹；最終仍需 Phase 0 gate 後再定案。
- Phase 1 不新增 append-only manual note repository；review item 先只在 prototype DTO / mock state 呈現 open / done / blocked。

## Phase 2 候選切分

Phase 2 只能在 Phase 0 evidence gate 滿足後評估。候選切分如下：

1. 建立 `WorkbenchReadOnlyComposer` 與 DTO。
2. 建立 Qt read-only Workbench view。
3. 將 Daily Decision、Evidence Review、Portfolio Review 與 Action Items 以 drill-down 方式整合。
4. 保留舊 Tab 作 expert mode。
5. 依 `DOC_COVERAGE_MAP.md` 同步 Manual、Architecture、Snapshot、Roadmap 與 Index。

Phase 2 仍不包含 production scheduler approval；scheduler 屬 Phase 5 gate。
