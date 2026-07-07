# Workbench Left Navigation IA Design

## Purpose

重排主 UI 的資訊架構，讓 app 打開後第一眼回答「今天我該看什麼」。新首頁採用中密度 `決策工作台`，以「今日待判讀」作為主心臟；需要深挖時再進入市場、決策來源、Evidence 或持倉細節。

這是資訊架構與呈現層設計，不改資料來源、不改 scoring、不改 portfolio 計算、不啟用 scheduler、不產生買賣建議。

## Current Problem

目前主 UI 同時有：

- `市場觀察`
- `決策工作台`
- `每日決策`
- `策略回測 > 證據覆盤`
- `持倉管理`

這些頁面各自有價值，但有三個頁面正在競爭「每日第一入口」：

1. `決策工作台`：應該回答今天要看什麼。
2. `每日決策`：已經能解釋市場 / watchlist / portfolio / risk prompt，但和 Workbench 平行時會搶首頁定位。
3. `市場觀察`：有完整市場探索能力，但不適合作為每日 first-look。

結果是資訊量很強，但第一眼負擔太高。使用者需要的是漂亮、安靜、可掃描的第一層，再按需深挖。

## Chosen Direction

使用者已確認：

- Workbench first screen 採 `中密度工作台`。
- 中間主區採 `今日待判讀清單`。
- 視覺方向採 `指揮中心式`。
- 主 tab 改為左側導覽。
- 子 tab 保留在各工作區上方。
- `每日決策` 不再作為頂層 tab，改為 Workbench 內的 `決策來源` detail。
- `市場觀察` 保留頂層，但重新定位並改名為 `市場探索`。
- 初始主導覽順序採：
  1. `決策工作台`
  2. `市場探索`
  3. `推薦分析`
  4. `策略回測`
  5. `觀察清單`
  6. `持倉管理`
  7. `數據更新`
  8. `Runtime`

## Visual Hierarchy

第一屏分三層。

### 1. Top Status Strip

只顯示 4 個摘要，不放長表格：

- 今日狀態：例如 `需人工判讀 4`
- 資料品質：例如 `Observed` / `Degraded` / `Missing`
- 持倉風險：例如 `2 alerts`
- Evidence gate：例如 `weekly 0/3 · multi-day 1/3`

目的：使用者 3 秒內知道今天是否需要處理、是否資料可信、是否有持倉風險、official gate 是否仍 blocked。

### 2. Main Queue: 今日待判讀

主內容區是一個排序佇列，把 Market / Portfolio / Evidence / Replay / Gate 事項混在同一個人工處理清單。

每列至少包含：

- severity：High / Medium / Low
- title：一句話說明要看什麼
- source label：Market / Portfolio / Evidence / Replay / Gate
- degraded reason 或 blocker reason
- drill-down target
- `write_intent=false`

排序原則：

1. High severity official blocker / safety blocker。
2. 需要人工判讀的持倉與市場風險。
3. Evidence / data quality degraded source。
4. replay / simulated-only 提醒。

Empty state 必須設計成正向但不誤導：

- 當 queue 為空時，中間主區顯示「今日所有風險已確認，市場無重大異常」或同等語氣。
- Empty state 必須保留 read-only / non-advice 邊界，不得暗示可以交易或 gate 已完成。
- Empty state 可提供下一步入口，例如 `前往市場探索`、`查看 Evidence gate`、`檢查持倉追蹤`。
- Empty state 不得自動觸發 refresh、pipeline、replay、scheduler 或 DB write。

Queue drill-down 回饋採 non-persistent first slice：

- 點擊 queue row 進入 drill-down 後，第一版可在本次 UI session 將該列標示為「已查看」或降低視覺權重。
- 此狀態只存在 UI memory，不寫 DB、不改 DTO、不套用 lifecycle。
- 若後續需要跨 session 記憶，再另案設計 manual review / action item persistence gate。

### 3. Drill-down + Compressed Snapshots

右側是深挖入口，不是第二個資訊牆：

- `決策來源`：Daily Decision detail。
- `市場探索`：產業、強弱勢、主力流向。
- `Evidence`：gate、source gaps、QA。
- `持倉追蹤`：thesis、alerts、lifecycle follow-up。

下方只保留 3 個壓縮摘要：

- Market snapshot：大盤 / 強勢產業 / 主力流向。
- Portfolio snapshot：alerts / thesis review / action。
- Evidence snapshot：simulated / official / scheduler。

完整表格、長 warnings、source trace、歷史 rows 都放到 deep-dive，不出現在第一眼。

## Navigation Design

### Main Navigation

主工作區改為左側導覽，取代目前上方主 `QTabWidget`。

左側導覽目的：

- 把全 app 工作區切換從內容上方移走。
- 讓 Workbench 第一屏不被一排主 tab 壓縮。
- 讓使用者快速理解工作區層級：日常判讀、探索、研究、持倉、維護。

左側導覽可顯示少量 badge：

- `決策工作台`：今日待判讀數。
- `持倉管理`：持倉 alerts 數。
- `市場探索`：可選，顯示焦點數或不顯示。

Badge 只能是摘要，不可觸發計算或資料刷新。

Collapsible left nav 屬 future slice：

- 第一版先做固定寬度左側導覽，確保資訊架構與測試穩定。
- 後續可新增收合模式，只顯示 icon / 短碼 / badge，供小螢幕筆電保留橫向空間。
- 收合狀態只能改呈現，不得改變 workspace routing、資料載入或 refresh 行為。

### Sub-tabs

各工作區內的子 tab 保留在上方。

Workbench 子 tab 建議：

1. `總覽`
2. `決策來源`
3. `Evidence`
4. `持倉追蹤`
5. `操作節奏`

`決策來源` 承接目前 `每日決策` 內容或 detail entry。第一版可先以 existing `DecisionDeskView` 嵌入 / 延遲建構 / drill-down 形式呈現，不重寫其 domain service。

`市場探索` 內部仍保留目前子 tab：

- 大盤指數
- 強勢個股
- 弱勢個股
- 強勢產業
- 弱勢產業
- 主力流向

## Scope

### In Scope

- 主 UI 導覽資訊架構重排。
- 主 tab 從上方改為左側導覽。
- `決策工作台` 成為第一個 / 預設主工作區。
- `市場觀察` 顯示名稱改為 `市場探索`。
- `每日決策` 從頂層 tab 降級為 Workbench 的 `決策來源`。
- Workbench 第一屏調整為 A 指揮中心式 layout。
- 保留 existing drill-down 行為：Workbench 可以導向 Market / Evidence / Portfolio detail。
- 更新 Manual、Snapshot、UI design system 與測試。

### Out of Scope

- 不改 scoring / recommendation / backtest / portfolio 核心計算。
- 不改 evidence DB schema。
- 不啟用 scheduler。
- 不新增 action item repository。
- 不把 replay / simulated-ready 標為 official-ready。
- 不重做所有頁面的細節視覺 polish。
- 不移除 Market / Evidence / Portfolio 的既有深挖能力。

## Implementation Boundary

目前 `ui_qt/main.py` 已有未提交修改；實作前必須先讀取並保護該變更，不得覆寫使用者或其他 agent 的修改。

使用者另有每日 schedule 與 report 產物調整；本次 UI IA 實作不得改動 scheduled wrappers、scheduled output schema、morning report、Pre-V2 readiness 或 simulated phase progress 的資料契約。Workbench 只能透過既有 `WorkbenchSourceService` / DTO 讀取這些資料，不能直接解析或假設 report 欄位固定。

實作應偏向新增小型容器 / helper，而不是在 `main.py` 內繼續堆大量 layout logic。

建議元件：

- `ui_qt/widgets/left_navigation.py`
  - 顯示主工作區按鈕、active state、badge。
  - 不讀 domain service。
  - 只發出 selected workspace signal。
- `ui_qt/widgets/main_workspace_shell.py` 或等價 helper
  - 左側導覽 + 右側 content stack。
  - 讓 main window 可以把既有 views 放入 stack。
- `UnifiedDecisionWorkbenchView`
  - 第一版可調整 layout，但仍只吃 `WorkbenchDashboardDTO` / `WorkbenchSourceService`。
  - 不直接讀 SQLite、不讀 replay DB。

若風險過高，第一個 implementation slice 可以先只做主導覽 shell 與 tab order，不重排 Workbench 內部內容；第二個 slice 再做 Workbench 指揮中心 layout。

## Data Flow

導覽層只管理 view 切換：

```text
MainWindow
  -> LeftNavigation selected workspace
  -> QStackedWidget shows existing view
  -> Existing view keeps current services / DTOs
```

Workbench 仍維持：

```text
WorkbenchSourceService
  -> WorkbenchDashboardDTO
  -> UnifiedDecisionWorkbenchView
```

Daily Decision detail 仍維持：

```text
DecisionDeskSnapshotBuilder / existing providers
  -> DecisionDeskView
  -> embedded or navigated as Workbench 決策來源
```

## Readability Rules

- 第一屏不顯示完整大型表格。
- 第一屏不顯示長 source trace；只顯示 source label 與 blocker summary。
- 第一屏每個區塊要有明確任務：
  - status strip = 總狀態。
  - queue = 今天看什麼。
  - drill-down = 去哪裡深挖。
  - snapshots = 市場 / 持倉 / evidence 壓縮摘要。
- 每個文字容器必須能承受中文長字串，不得重疊或被截到無法判讀。
- 不新增裝飾性漸層、orb、過量陰影或卡片套卡片。
- 維持 Midnight Analyst 深色、安靜、專業工作台風格。

## Testing Requirements

至少需要：

- MainWindow / tab integration 測試更新：
  - `決策工作台` 是第一個主工作區。
  - 左側導覽包含預期工作區名稱與順序。
  - `每日決策` 不再是頂層主工作區。
  - `市場探索` 替代 `市場觀察` 作為頂層名稱。
- Workbench view 測試：
  - `今日待判讀` queue 仍由 DTO / source service 提供。
  - row 保留 severity / source label / drill-down target / `write_intent=false`。
  - empty / degraded state 文案仍保留 read-only / non-advice 邊界。
- UI safety tests：
  - Workbench / navigation 不直接 import scoring、backtest、portfolio core 計算模組。
  - 不新增 DB write path。
- Existing required UI QA:
  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
  .\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
  .\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
  ```

## Documentation Requirements

若實作進行，必須同步：

- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`（若改變 V2.1/V2.2 completion wording）
- `docs/01_architecture/ui_design_system_midnight_analyst.md`
- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- 對應 QA closeout in `docs/06_qa/`

## Open Implementation Risks

- `ui_qt/main.py` 已偏大；直接在其中新增左側導覽可能讓檔案更難維護。
- 主 tab 由 `QTabWidget` 改為左側 navigation + `QStackedWidget` 會影響現有 tab index assumptions，例如 Market Watch lazy load 與 Portfolio auto-refresh。
- Workbench drill-down callbacks 目前用 tab label 選取；降級 `每日決策` 後需要重新定義 callback。
- UI tests 可能依賴舊 tab names / order，需要同步更新。
- 左側導覽在小寬度下需要 fallback；第一版 desktop-only 也必須不破壞 layout。

## Design Decision

採用 left-navigation command-center IA：

- 左側主導覽管理全 app 工作區。
- Workbench 是 default first workspace。
- Daily Decision 變 Workbench `決策來源` detail。
- Market Watch 改名 `市場探索` 並保留深挖能力。
- Workbench 第一屏採指揮中心式：status strip + 今日待判讀 + drill-down + compressed snapshots。

此設計通過使用者視覺 mockup 確認，下一步才進入 implementation plan。

## Implementation Result（2026-07-07）

已落地：

- 主 UI 由上方主 tab 改為左側主導覽。
- 預設主工作區為 `決策工作台`。
- 主工作區順序為 `決策工作台`、`市場探索`、`推薦分析`、`策略回測`、`觀察清單`、`持倉管理`、`數據更新`、`Runtime`。
- `每日決策` 已從頂層主工作區移除，嵌入 `決策工作台 > 決策來源`。
- `市場觀察` 已改名並重新定位為 `市場探索`，原有市場子頁保留。
- Workbench 內部子頁已新增 `總覽`、`決策來源`、`Evidence`、`持倉追蹤`、`操作節奏`。
- `今日待判讀` 佇列為空時顯示空狀態，提示可前往市場探索研究。
- Queue row drill-down 後只在本次 UI session 顯示已查看計數；不寫 DB、不標記完成、不改 lifecycle。
- 本次未修改 scheduled wrappers、scheduled output schema、morning report、Pre-V2 readiness 或 simulated phase progress contract。

仍需等待正式資料 / 未標示完成：

- Phase 0 weekly history `0/3` 仍需真實 weekly review history 累積。
- Multi-day dry-run `1/3` 仍需真實時間下的 scheduled/manual dry-run record 累積。
- Replay summary 可用於揭露 source gap、payload gap、benchmark / industry coverage 與 UI 設計檢查，但不能取代上述 gate。

Future slice：

- 左側導覽可再新增 collapsed icon-only mode；badge 仍需保留在 icon 右上角。
- Workbench 第一屏可再把大型表格壓縮成更高密度摘要卡與 drill-down details，但仍必須維持 read-only DTO 邊界。
