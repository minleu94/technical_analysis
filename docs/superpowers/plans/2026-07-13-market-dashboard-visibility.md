# Market Exploration Integrated Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and the repository UI verification gates.

**Goal:** 將既有 `DecisionDeskView` 提升為「市場探索」第一個整合總覽，讓月營收與三大法人／信用／TDCC資料狀態可見，保留現有六個頁面作 drill-down，並消除 Workbench 的重複 Decision Desk instance。

**Architecture:** 不建立第三套Dashboard。`MarketDataVisibilityService`以read-only SQLite建立PIT-safe研究摘要與source status；`DecisionDeskSnapshot`攜帶optional visibility section；同一個 `DecisionDeskView` 放入 Market Exploration index 0。Workbench只導航到該唯一instance。Visibility不參與action summary、stock focus、Score或Advice。

**Tech Stack:** Python 3.11、SQLite URI `mode=ro`、dataclasses、Decimal／integer bp、PySide6 existing design system／TaskWorker、pytest-qt、mypy。

## Target Information Architecture

```text
市場探索
├── 市場總覽（既有 DecisionDeskView；唯一 instance）
├── 大盤指數
├── 強勢個股
├── 弱勢個股
├── 強勢產業
├── 弱勢產業
└── 主力流向
```

Workbench「決策來源」改為說明＋「開啟市場總覽」導航，不再嵌入第二個 `DecisionDeskView`。

## Ownership

**Create:**

- `app_module/market_data_visibility_dtos.py`
- `app_module/market_data_visibility_service.py`
- `tests/test_market_data_visibility_service.py`
- `docs/06_qa/MARKET_EXPLORATION_INTEGRATED_DASHBOARD_2026_07_15.md`

**Modify:**

- `app_module/decision_desk_dtos.py`
- `app_module/decision_desk_service.py`
- `app_module/decision_desk_composition.py`
- `ui_qt/views/decision_desk_view.py`
- `ui_qt/views/workbench_view.py`
- `ui_qt/main.py`
- `tests/test_decision_desk_dto_contract.py`
- `tests/test_decision_desk_service.py`
- `tests/test_ui_qt_decision_desk_view.py`
- `tests/test_ui_qt_decision_desk_main_integration.py`
- `tests/test_ui_qt_workbench_view.py`
- `docs/07_guides/APPLICATION_MANUAL.md`

**Must not modify:**

- `app_module/broker_flow_service.py`
- `app_module/smart_money_semantic_service.py`
- `app_module/dtos/smart_money_semantic_dtos.py`
- `ui_qt/views/smart_money/**`
- C新增的broker repository／query／DTO
- E1 parser／candidate ingestion files
- central Snapshot／Roadmap／Architecture files（G owns）

---

## Task 1：凍結資料可見性／PIT Contracts

**Files:**

- Create: `app_module/market_data_visibility_dtos.py`
- Create: `tests/test_market_data_visibility_service.py`

- [ ] **Step 1: 寫月營收PIT RED tests**

Assertions：只允許`available_date <= as_of_date`；同stock／period取當時最新合法revision；latest period、上月、去年同期都必須在as-of時可得；無comparable row不可補0；2025 as-of不得讀到`available_date=2026-06-17`的backfill rows。

- [ ] **Step 2: 寫法人0-row／future-row RED tests**

0 rows回傳`MISSING`＋「尚未匯入（0 筆）」；不得顯示外資／投信／自營商淨額皆0。`decision_date > as_of_date`或`available_date > as_of_date`的rows被排除。

- [ ] **Step 3: 定義DTO**

至少包含：

- `SourceVisibilityStatus`：source id、display name、quality、row/stock count、latest observation／available date、PIT status、eligibility、warnings。
- `MonthlyRevenueBreadthSummary`：latest period、coverage、MoM／YoY comparable與positive counts／ratios bp、quality、warnings。
- `InstitutionalFlowMarketSummary`：latest date、stock count、foreign／trust／dealer net shares、quality、warnings。
- `MarketDataVisibilitySummary`：as-of、兩個摘要、all source statuses、overall quality、warnings。

- [ ] **Step 4: 明確source status coverage**

即使0 rows，`institutional_flows`、`credit_transactions`、`tdcc_shareholding`、`broker_flows`、`fundamental_monthly_revenues`都必須有status，不得從UI消失。

- [ ] **Step 5: RED verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_market_data_visibility_service.py -q -o addopts=
git add app_module/market_data_visibility_dtos.py tests/test_market_data_visibility_service.py
git commit -m "test(market-data): define visibility and PIT contracts"
```

## Task 2：唯讀 Market Data Visibility Service

**Files:**

- Create: `app_module/market_data_visibility_service.py`
- Modify: `tests/test_market_data_visibility_service.py`

- [ ] **Step 1: 寫read-only／fail-closed RED tests**

連線必須URI `mode=ro`＋`PRAGMA query_only=ON`；service不建立table、不backfill、不觸發crawler。缺DB／table／schema／query error回typed missing/degraded snapshot，不讓整體Dashboard崩潰。

- [ ] **Step 2: 實作月營收breadth**

每檔先選as-of可得revision，再以`Decimal`計算MoM／YoY並量化integer bp；現有retroactive/static history標 `historical_pit_unverified`／degraded，不冒充official PIT。

- [ ] **Step 3: 實作法人摘要與source status**

資料存在時按三類法人加總net shares並輸出coverage；沒有資料時保持missing。信用／TDCC可先只有status，不猜值、不補零。

- [ ] **Step 4: 證明資料加入後無需改UI**

在temp DB由0 rows加入合法institutional rows後，同一service contract自動回observed摘要；加入future rows時結果不變。

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_market_data_visibility_service.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile app_module\market_data_visibility_dtos.py app_module\market_data_visibility_service.py
git add app_module/market_data_visibility_service.py tests/test_market_data_visibility_service.py
git commit -m "feat(market-data): add readonly visibility service"
```

## Task 3：接入 DecisionDesk Snapshot，但隔離正式決策

**Files:**

- Modify: `app_module/decision_desk_dtos.py`
- Modify: `app_module/decision_desk_service.py`
- Modify: `app_module/decision_desk_composition.py`
- Modify: `tests/test_decision_desk_dto_contract.py`
- Modify: `tests/test_decision_desk_service.py`

- [ ] **Step 1: 寫snapshot schema RED tests**

`DecisionDeskSnapshot`新增optional `market_data_visibility`並進`to_dict()`；舊schema v1 payload仍可載入；新build預設schema v2。

- [ ] **Step 2: 寫decision isolation RED tests**

同一市場／portfolio inputs下，visibility為observed、missing或service exception時，既有action summary、sector focus、stock focus與正式score payload完全相同。

- [ ] **Step 3: 注入optional service**

Builder透過port呼叫visibility service；failure產生degraded visibility section，不讓其他Decision Desk sections失敗。不要讓Dashboard composer用visibility計算action。

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_decision_desk_dto_contract.py tests/test_decision_desk_service.py tests/test_market_data_visibility_service.py -q -o addopts=
git add app_module/decision_desk_dtos.py app_module/decision_desk_service.py app_module/decision_desk_composition.py tests/test_decision_desk_dto_contract.py tests/test_decision_desk_service.py
git commit -m "feat(decision-desk): attach market data visibility snapshot"
```

## Task 4：重排 Market Exploration 與移除重複Instance

**Files:**

- Modify: `ui_qt/main.py`
- Modify: `ui_qt/views/workbench_view.py`
- Modify: `tests/test_ui_qt_decision_desk_main_integration.py`
- Modify: `tests/test_ui_qt_workbench_view.py`

- [ ] **Step 1: 寫唯一instance RED test**

Main window只建立一個`DecisionDeskView`；它位於Market Exploration index 0、標籤「市場總覽」。Workbench不再建立或持有第二個instance。

- [ ] **Step 2: 寫導航／drill-down RED tests**

Workbench按鈕切到`market_explore`並選市場總覽；既有大盤、強弱股、強弱產業、主力流向皆可開啟；`show_smart_money_flow_for_stock()`仍定位主力流向與stock。

- [ ] **Step 3: 移除hard-coded tab index lazy loading**

以widget identity或registry mapping對應loader；新增index 0後不能錯載其他tab。

- [ ] **Step 4: 實作Workbench導航卡**

以簡短來源說明、最新狀態與「開啟市場總覽」取代嵌入式Decision Desk；保持keyboard操作與可辨識focus。

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_decision_desk_main_integration.py tests/test_ui_qt_workbench_view.py -q -o addopts=
git add ui_qt/main.py ui_qt/views/workbench_view.py tests/test_ui_qt_decision_desk_main_integration.py tests/test_ui_qt_workbench_view.py
git commit -m "refactor(ui): make decision desk the market overview"
```

## Task 5：Dashboard Visibility Cards／Empty States

**Files:**

- Modify: `ui_qt/views/decision_desk_view.py`
- Modify: `tests/test_ui_qt_decision_desk_view.py`

- [ ] **Step 1: 寫rendering RED tests**

Cases：revenue degraded可見、2025 revenue blocked、institutional 0-row missing、future institutional rows excluded、valid rows observed。State必須有文字＋badge，不能只靠色彩或空白。

- [ ] **Step 2: 新增「資料可見性與擴充因子」區段**

月營收卡顯示latest period、coverage、MoM／YoY正成長廣度、quality；法人卡顯示latest date、三類net shares或明確0-row missing；source列顯示observation date、available date、PIT status、eligibility與action hint。

- [ ] **Step 3: 沿用既有design system**

使用 `MIDNIGHT_ANALYST`、`MetricCard`、`SectionPanel`、`StatusBadge`與4／8px spacing；不建立新theme。不使用emoji作結構圖示。

- [ ] **Step 4: Layout／accessibility gates**

1280×720與1440×800不出現水平卷軸；keyboard tab order符合視覺順序；existing TaskWorker async refresh與stale-result guard保留。

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_decision_desk_view.py -q -o addopts=
git add ui_qt/views/decision_desk_view.py tests/test_ui_qt_decision_desk_view.py
git commit -m "feat(ui): expose revenue and institutional status"
```

## Task 6：Manual、UI QA 與 Closeout

**Files:**

- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Create: `docs/06_qa/MARKET_EXPLORATION_INTEGRATED_DASHBOARD_2026_07_15.md`

- [ ] **Step 1: 更新完整Manual**

同步入口、tab順序、操作、refresh／loading、月營收／法人數值判讀、missing/degraded／PIT badge、安全限制與排錯。明確說明source可見不等於source accepted或已進Score。

- [ ] **Step 2: Focused UI verification**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_market_data_visibility_service.py tests/test_decision_desk_dto_contract.py tests/test_decision_desk_service.py tests/test_ui_qt_decision_desk_view.py tests/test_ui_qt_decision_desk_main_integration.py tests/test_ui_qt_workbench_view.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

- [ ] **Step 3: Static／compile／Git verification**

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
git diff --check
git status --short
```

對全部changed Python files執行`py_compile`。

- [ ] **Step 4: Closeout commit**

Closeout記錄actual tests、screens/layout cases、DB read-only證據、仍missing source與formal boundary。

```powershell
git add docs/07_guides/APPLICATION_MANUAL.md docs/06_qa/MARKET_EXPLORATION_INTEGRATED_DASHBOARD_2026_07_15.md
git commit -m "docs(ui): record integrated market dashboard closeout"
```

## Completion Gate

- [ ] Market Exploration第一頁是唯一整合市場總覽；沒有第三套Dashboard或Workbench duplicate。
- [ ] 月營收真實可見並明示PIT／quality；歷史as-of不偷看2026 backfill。
- [ ] 三大法人即使0 rows也明確可見、不顯示假零；新合法資料可自動呈現。
- [ ] 信用／TDCC／broker／revenue等source status不隱形。
- [ ] Visibility不改正式Score、Advice、Recommendation或action summary。
- [ ] production DB零寫入；focused tests、mandatory UI QA、mypy與py_compile通過。
