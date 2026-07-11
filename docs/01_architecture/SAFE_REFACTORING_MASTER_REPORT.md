# baldr 安全重構與邏輯簡化總報告

> **建立日期**：2026-07-11
> **適用分支**：`dev`
> **用途**：Planner、Implementation、QA 與人工審查共同讀取的唯一重構執行依據。
> **狀態**：Active engineering companion。
> **Automation program**：`active_program=SAFE_REFACTORING_MASTER_PROGRAM`。
> **不取代**：`PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、`VERSION_ROADMAP_V2_1_TO_V4_0.md`、`system_architecture.md` 或 `APPLICATION_MANUAL.md`。
> **產品交棒**：安全重構完成後的產品方向以 [PRODUCT_ROADMAP_POST_REFACTOR.md](../00_core/PRODUCT_ROADMAP_POST_REFACTOR.md) 為準，理想架構以 [target_system_architecture.md](target_system_architecture.md) 為準。本報告只負責行為不變重構，不承擔 Advice、Portfolio、Exit、Data 或 ML Roadmap。

---

## 1. 執行摘要

baldr 已經具備清楚的產品閉環、治理規則與大量測試，但部分 View、Service 與分析類別累積了過多協調、格式化、I/O、計算與狀態管理責任。安全重構的正確方向不是重寫，而是沿用目前已證明有效的 **Characterization → Pure Support Extraction → Façade 保留 → Focused Regression → Atomic Commit** 模式，逐步把大型節點變成薄協調層。

本計畫採用下列決策：

1. **保留行為，不追求一次到位的新架構**：公開 API、DTO、序列化、排序、warning token、資料 fallback、副作用順序與使用者流程必須相容。
2. **以 Strangler / Branch-by-Abstraction 漸進替換**：先建立測試，再抽無 I/O helper、read model、mapper、presenter 或 adapter；原類別保留 façade。
3. **Planner 不直接依賴固定 Queue**：每輪 Planner 必須讀本報告、最新 Git、前一輪 QA 與既有產物，自行產生一個或多個可在時間盒內完整完成的細項 Plan。
4. **Implementation 只實作指定 Plan**：不得自行擴張範圍；每個切片獨立測試、commit、push。
5. **QA 只驗收前一輪 Implementation 報告與 commit**：不得修改程式；失敗必須產生精確 remediation handoff。
6. **直接在 `dev` 進行**：沿用目前模式；只有乾淨工作區、`origin/dev` 可 fast-forward、完整 Gate 通過時才 atomic commit 並 push。
7. **不影響服務與 App**：不重啟或改 production scheduler、不寫 production evidence DB、不改正式資料、不交易、不套用 lifecycle action。

### 最終目標

重構完成不以「刪了多少行」判定，而以下列結果判定：

- 大型類別只負責協調與 UI wiring，純邏輯可獨立測試。
- Domain 不再直接依賴 Application 或資料庫實作。
- 跨層依賴方向可解釋，循環依賴逐步歸零。
- 同一資料或衍生值不重複計算、不重複正規化。
- 每個切片可獨立回退，不影響目前 App、服務、排程與資料語意。
- 測試、mypy、量化防線、UI Gate 與 Git hygiene 持續通過。

---

## 2. 範圍與非目標

### 2.1 Scope In

- `ui_qt/` 的大型 View、MainWindow wiring、presenter / view-model 邊界。
- `app_module/` 的 orchestration service、read model、DTO 組裝、status / report support。
- `decision_module/` 與 `analysis_module/` 的資料存取邊界、dispatch、純計算 helper 與依賴方向。
- `data_module/` adapter、repository 與 domain contract 的依賴方向。
- `backtest_module/`、`portfolio_module/` 的相容性測試與金融核心邊界。
- import cycle、重複正規化、重複 query、重複組裝與大型函式拆分。
- automation 的 Planner → Implementation → QA 產物鏈與安全狀態機。

### 2.2 Scope Out

- 不新增產品功能、資料源、推薦規則或策略。
- 不改 `ScoringEngine` 分數、threshold、profile weights、portfolio allocation 或 lifecycle policy。
- 不變更 production DB schema、production evidence write-mode scheduler 或 Windows Task Scheduler。
- 不自動交易、不串 broker、不輸出買賣建議。
- 不用重構宣稱策略有效、alpha、V3/V4 投資有效性或 ML readiness。
- 不刪除正式資料、原始 CSV、SQLite 或未經使用證據確認的 legacy API。
- 不以一次性大搬檔、新框架或全域 DI container 重寫現有 App。

---

## 3. 證據基線

### 3.1 靜態結構盤點

2026-07-10 `dev`／`origin/dev` 基線 `b5f779f50ecabcf4fe0803f63eb57461b96d985a`：

| 指標 | 結果 |
|---|---:|
| 核心 Python 檔案 | 330 |
| 核心程式總行數 | 98,745 |
| 函式 / 方法 | 3,383 |
| 類別 | 589 |
| 靜態 import edges | 759 |
| 偵測到的 file/module SCC cycle | 2 |

### 3.2 目前最大節點

| 優先觀察節點 | 行數 | 方法數 / 特徵 | 主要風險 |
|---|---:|---:|---|
| `ui_qt/views/backtest_view.py::BacktestView` | 4,890 | 204 methods | UI wiring、研究執行、registry、export、optimizer 協調混合 |
| `app_module/update_service.py::UpdateService` | 3,581 | 54 methods | status、更新、merge、DB、指標與備份副作用集中 |
| `ui_qt/views/recommendation_view.py::RecommendationView` | 2,706 | 59 methods | form、profile、結果、export 與 presentation 混合 |
| `ui_qt/views/update_view.py::UpdateView` | 2,555 | 68 methods | UI、worker、更新流程與狀態顯示混合 |
| `analysis_module/pattern_analysis/pattern_analyzer.py::PatternAnalyzer` | 2,220 | 21 methods | 多種形態演算法、dispatch、fit 與例外語意集中 |
| `decision_module/stock_screener.py::StockScreener` | 1,683 | 16 methods | SQL / CSV fallback、排序、reason token 與篩選混合 |
| `app_module/broker_branch_update_service.py` | 1,529 | 23 methods | registry、抓取、合併、品質與寫入協調 |
| `app_module/recommendation_portfolio_backtest_service.py` | 1,111 | 40 methods | replay、execution、metrics、credibility 與 factor manifest |
| `data_module/data_loader.py::DataLoader` | 1,012 | 24 methods | 外部抓取、日期、資料型態與 persistence 路徑 |
| `analysis_module/technical_analysis/technical_indicators.py` | 930 | 18 methods | 指標公式、參數 registry、warm-up 與欄位契約 |

### 3.3 最大函式風險

- `BacktestConfigPanel._setup_ui()`：685 行。
- `RecommendationService.run_recommendation()`：590 行。
- `UpdateView._add_source_tab_content()`：501 行。
- `RecommendationView._create_config_panel()`：490 行。
- `UpdateService.calculate_technical_indicators()`：451 行。
- `BrokerSimulator.run()`：441 行。
- `StockScreener.get_strong_stocks()`：408 行。
- `BatchBacktestService.run_batch_backtest()`：375 行。
- `RecommendationPortfolioBacktestService.run_portfolio_backtest()`：355 行。

### 3.4 Graphify 結果

現有 `graphify-out/graph.json` 將下列節點列為 God Nodes：

1. `BacktestView`：216 edges。
2. `ResearchRunMetadataDTO`：77 edges。
3. `UpdateView`：77 edges。
4. `RecommendationView`：69 edges。
5. `PandasTableModel`：63 edges。
6. `UnifiedDecisionWorkbenchView`：56 edges。
7. `UpdateService`：55 edges。
8. `TaskWorker`：50 edges。
9. `DecisionDeskQuality`：49 edges。
10. `RecommendationPortfolioBacktestService`：47 edges。

Graphify 只作探索證據。圖譜含 INFERRED edges，且曾有 shrink-guard / 更新時點限制；任何重構驗收以目前程式碼、測試、Git 與實際呼叫契約為準，不得只憑圖譜移動或刪除程式。

### 3.5 已知依賴問題

1. `app_module.walkforward_service` 直接依賴 `BacktestService`，而 `backtest_service.py` 為型別引用反向引用 `WalkForwardResult`；應先用 `TYPE_CHECKING` / protocol / 中立 DTO 消除 cycle，不改 runtime 行為。
2. `app_module.update_service` 使用 `from app_module import update_data_normalization`，會經 package `__init__` 間接載入 `BacktestService`；應改為明確 module import，但必須先鎖定 import-time side effect。
3. `decision_module.flow_signal_engine` 依賴 `app_module.dtos.*`，違反 Domain 不依賴 Application 的方向；DTO ownership 需設計 migration shim，禁止 automation 直接搬類別。
4. `decision_module` 多處在方法內直接建立或 import `DBManager`；長期應由 Application 注入 read port / provider。
5. `analysis_module.technical_indicators` 反向依賴 `decision_module.indicator_parameter_registry`，同時 Decision 又依賴 Analysis；需以中立參數契約或顯式參數輸入解開雙向依賴。

### 3.6 既有重構成果

Slice 1–16 已證明「小切片 + façade + characterization」模式可行：

- BacktestView research metadata support。
- UpdateService 純 normalization。
- RecommendationView metadata / profile presentation support。
- UpdateView formatter support。
- RecommendationService payload / ranking / negative evidence support。
- StrategyConfigurator row / diagnostic support。
- RecommendationPortfolioBacktest support。
- BacktestService report / factor support。
- DataLoader date / path support。
- DecisionDesk snapshot support。
- DecisionDesk DTO characterization。
- ForwardPerformanceReadModel support。
- Evidence importer support。
- EvidencePipelineRunner summary/status support。
- UpdateService status read-model support。
- StockScreener SQLite reader/query seam。

截至 Slice 16，最新 QA 為 `READY_TO_CONTINUE`，`dev` 與 `origin/dev` 同步。總計已把十個原始目標檔淨減 1,065 行，同時用 support modules 與契約測試增加可維護性；這是本報告建議延續的模式。

---

## 4. 方案比較與採用決策

### 方案 A：漸進式 Strangler + Characterization（採用）

優點：回歸範圍小、可逐片回退、可保留現有服務與 App、符合現有測試與 automation。缺點：短期總 LOC 可能上升，完成時間較長，期間會存在 façade 與 support module 並存。

### 方案 B：按模組一次拆分

優點：檔案快速變小、目錄看起來更整齊。缺點：同時改 import、state、Qt ownership、side effect 與測試，容易產生隱性行為差異；不適合無人夜間 automation。

### 方案 C：建立 VNext 平行重寫並雙跑

優點：可重新設計乾淨介面。缺點：雙系統漂移、測試與資料語意複製、切換成本高，會擴大 Roadmap 與產品範圍；目前不採用。

### 決策

採方案 A。方案 B 只允許在已具備完整 characterization、明確 façade 與人工核准時作單一模組收尾；方案 C 不進近期主線。

---

## 5. 目標依賴方向

```text
ui_qt
  ↓ 只依賴 Application façade / DTO / presenter contract
app_module
  ↓ orchestration、transaction boundary、repository/provider 組裝
decision_module / backtest_module / portfolio_module / runtime contracts
  ↑ 純 domain，不 import ui_qt、app_module 或 DBManager
data_module / external adapters
  ↑ 實作 repository/provider port，可依賴 domain contract
```

### 核心規則

- UI 不直接開 SQLite、不直接建立 DBManager、不直接重算 domain 結果。
- Application 可以組合 Domain 與 Data adapter，但不把 presentation 狀態塞進 Domain。
- Domain 不依賴 Application DTO；共用契約應由 domain 擁有或由獨立、穩定的 contract module 擁有。
- Data adapter 可以實作 Domain port，但 Domain 不直接 import 具體 Data adapter。
- 所有跨層資料都使用具名 DTO / protocol；不得以無結構 dict 擴散。
- 不建立全域 service locator 或隱性 singleton cache。

---

## 6. 不可變契約與安全護欄

### 6.1 Protected Contracts

下列本體不得由夜間 automation 改名、搬檔、改 enum value、改欄位、建構、序列化或預設值：

- `TWStockConfig`
- `StrategySpec`
- `DecisionDeskQuality`
- `ResearchRunMetadataDTO`
- `FactorDiagnostic`
- `EvidenceEventType`
- `RecommendationResultDTO`
- Portfolio / Research Run / Evidence 已保存 JSON key 與 datetime/date 格式

只允許新增相容性測試、adapter 或 deprecation shim。任何確實需要修改契約的工作，必須轉為人工核准的獨立設計，不可由本 automation 自動執行。

### 6.2 行為不變定義

每個切片至少固定：

- 公開 import path、class `__module__`、method signature。
- DTO field、JSON key、key order（若既有測試依賴）、enum value。
- SQL predicate、decision-date cutoff、排序、tie-break、limit、fallback。
- warning / advisory / diagnostic token 與順序。
- dry-run / confirm gate、repository write 次數與副作用順序。
- Qt signal、slot、worker ownership、取消與錯誤顯示。
- 金額、基點、股數與績效的 Decimal / 整數語意。
- Look-ahead：決策日只能使用當時可得資料。

### 6.3 禁止的「假簡化」

- 只把巨型函式搬到另一個巨型檔案。
- 以 `Any`、全域 dict、反射或 service locator 隱藏耦合。
- 用 broad `except Exception` 吃掉既有 failure。
- 為減少 LOC 移除 diagnostics、quality 或 source trace。
- 為了通過測試改 fixture、降低 assertion 或跳過 Gate。
- 把多個不相關切片塞進同一 commit。

---

## 7. 重構波次與優先佇列

### Wave 0：每輪基線與治理

每輪先確認：`dev`、乾淨工作區、`origin/dev`、上一輪報告、Graphify 輔助、focused baseline、protected contracts、資料與量化邊界。Wave 0 不是獨立 commit，而是所有切片的前置 Gate。

### Wave 1：完成現行低風險支援抽取

目前 continuation anchor 是 `PatternAnalyzer` characterization / dispatch / fit support。Planner 必須先檢查 Slice 17 是否已被其他執行完成；若已完成，從下一個未完成且具 characterization 的節點選擇。

允許：prefix-only golden tests、dispatch table、無 I/O fit helper、column resolution。禁止：改 pattern 公式、position、threshold、例外語意或使用未來列。

### Wave 2：UI 薄殼化

優先順序由 Planner 依測試成熟度決定，不按檔案行數硬排：

1. `BacktestView`：抽 coordinator / presenter；保留 QWidget ownership、signal wiring、公開 properties。
2. `RecommendationView`：抽 form schema、result presenter、export adapter；保留 profile 與 table 行為。
3. `UpdateView`：抽 tab builder / worker coordinator / status presenter；不移動更新副作用。
4. `WorkbenchView`：抽 section presenter 與 model mapping；保持 read-only DTO boundary。
5. `MainWindow`：最後才抽 composition factory；先做 startup / navigation / signal characterization。

每片只處理一種責任，禁止同時改視覺、功能與資料流。

### Wave 3：Application orchestration 簡化

- `UpdateService`：status/read model 已抽；後續依 source family 拆 orchestration，但 update/merge/backup/indicator 寫入順序不得改。
- `RecommendationService.run_recommendation()`：把 pipeline stage 變成具名純步驟；輸入輸出必須 snapshot-equivalent。
- `RecommendationPortfolioBacktestService`：分離 execution ledger、metrics、credibility manifest；金融計算保持 Decimal / basis points。
- `BrokerBranchUpdateService`：分離 registry parsing、transport、merge plan、write coordinator；production data path 只允許 dry-run / temp DB 測試。
- `BacktestService` / `BatchBacktestService`：分離 report assembly 與 execution orchestration；不改成交、成本、timeline。

### Wave 4：依賴反轉與 cycle 移除

此波風險高於一般 helper 抽取，每個目標先做 design-only Plan：

1. 消除 `backtest_service` ↔ `walkforward_service` cycle。
2. 消除 `update_service` 經 `app_module.__init__` 的 package initialization cycle。
3. 將 `decision_module.flow_signal_engine` 對 `app_module.dtos` 的依賴改為 domain-owned contract + compatibility re-export。
4. 將 `StockScreener`、`IndustryMapper`、`MarketRegimeDetector` 的具體 DBManager 存取改由 Application provider 注入。
5. 解開 `analysis_module.technical_indicators` 與 `decision_module.indicator_parameter_registry` 的雙向依賴。

任何搬動 DTO ownership 的 Plan 必須先列全 repo import、序列化相容、pickle / persisted JSON 風險與至少一版 deprecation shim；未具備這些內容時只能補 characterization，不得實作搬檔。

### Wave 5：金融與分析核心

最後處理：`TechnicalIndicatorCalculator`、`ScoringEngine`、`MarketRegimeDetector`、`BrokerSimulator`、績效指標與 Portfolio core。

順序固定為：golden corpus → prefix / T-1 test → numeric boundary test → pure kernel extraction → façade → full financial regression。禁止先改公式再補測試。

### Wave 6：清理與移除

只有在完成以下證據後才可刪除 shim / legacy code：

- `rg` 靜態引用為零。
- dynamic import / `getattr` / Qt signal route 已檢查。
- 對應測試與 healthcheck 不再使用。
- 至少一輪 automation + morning closeout 無回歸。
- 人工核准刪除清單與回滾方式。

夜間 automation 預設不得執行 Wave 6 刪除。

---

## 8. 切片選擇評分

Planner 對候選切片使用下列原則，不用「最大檔案優先」：

| 維度 | 加分條件 | 扣分條件 |
|---|---|---|
| Characterization | 已有完整輸入輸出與副作用測試 | 無法建立穩定 oracle |
| Purity | 無 I/O、無 Qt ownership、無金融公式 | DB write、scheduler、Qt lifecycle |
| Coupling reduction | 能移除重複邏輯或反向 import | 只搬檔、不減邊 |
| Rollback | 單一 façade / helper，可一 commit 回退 | 多模組 schema / contract 連動 |
| Timebox | 可在本輪完整 RED/GREEN/QA | 只能留下半成品 |
| User impact | 無外部行為變更 | 改 UI 流程、結果或資料語意 |

選擇門檻：必須同時滿足「有 oracle、可完整驗證、可獨立回退、無 production 寫入」。

---

## 9. 測試與驗收矩陣

### 9.1 每片最小 Gate

1. 新增或確認 characterization RED。
2. 最小 GREEN 實作。
3. Focused pytest。
4. Changed-file `py_compile`。
5. `git diff --check`。
6. Protected-contract diff。
7. `git status --short` 只含本片檔案與 ignored output。

### 9.2 條件式 Gate

- UI：相關 view contract、對應 QA script、必要 MainWindow smoke。
- Update UI：`tests/test_ui_qt_update_view_workbench.py`、`scripts/qa_validate_update_tab.py`、全域 mypy。
- 推薦 / 回測 / Portfolio：financial float checker、Look-ahead checker、timeline / diagnostics tests。
- DB / repository：temp DB、read-only URI、dry-run、idempotency、rollback / failure injection。
- DTO / persisted payload：constructor、field、enum、JSON round-trip、legacy payload compatibility。
- import boundary：fresh interpreter import smoke、cycle scan、mypy。

### 9.3 週期性整體 Gate

至少在每個夜間 closeout 執行：

- 本夜所有切片 focused suite 聯集。
- 全域 mypy：`ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`。
- 適用 UI QA。
- Quant guard。
- Protected-contract diff。
- `git diff --check <night-baseline>..HEAD`。
- `dev == origin/dev`、工作區乾淨。

全量 pytest / Full App Healthcheck 依風險與時間安排；未執行必須在 closeout 說明原因，不能暗示已通過。

---

## 10. Automation 產物鏈

### 10.1 唯一權威與工作目錄

- Master report：`docs/01_architecture/SAFE_REFACTORING_MASTER_REPORT.md`。
- Runtime handoff：`output/automation/version_loop/`，永不 stage。
- Planner / Implementation / QA 都必須讀本報告；不得把 prompt 內的簡短摘要當成完整規格。
- 本報告是 refactor execution companion，不改產品 Roadmap 優先權。

### 10.2 循環

```text
Master Report
    ↓
Planner 產生精確 Plan + JSON manifest
    ↓
Implementation 只讀該 Plan，實作、驗證、commit、push、產生 Implementation Report
    ↓
QA 只讀該 Implementation Report、Plan、Git commit，獨立驗收並產生 QA Report
    ↓
下一個 Planner 讀 Master Report + QA Report + 未完成狀態
```

### 10.2.1 每日完整時段

| 循環 | Planner | Implementation | QA / Closeout |
|---|---|---|---|
| A | 00:00 | 00:20 | 02:10 |
| B | 02:30 | 02:45 | 04:20 |
| C | 05:40 | 06:00 | 08:00 |
| D | 08:20 | 08:40 | 09:00 |
| E | 09:20 | 09:40 | 10:00 |
| F | 10:20 | 10:40 | 11:00 |
| G | 11:20 | 11:40 | 12:00 Final QA / Closeout |

08:00、09:00、10:00、11:00 都是中繼 QA，必須把 exact QA artifact 交給下一輪 Planner；只有 12:00 可產生 nightly closeout 與次日 00:00 handoff。四個延長循環不可壓縮或合併角色。

### 10.3 產物命名

每輪使用 `cycle_id=YYYYMMDD-HHMM-<stage>`：

- Planner：`refactor_plan_<cycle_id>.md/.json` 與 `latest_refactor_plan.md/.json`。
- Implementation：`refactor_implementation_<cycle_id>.md/.json` 與 `latest_refactor_implementation.md/.json`。
- QA：`refactor_qa_<cycle_id>.md/.json` 與 `latest_refactor_qa.md/.json`。
- 12:00 closeout：`refactor_nightly_closeout_YYYYMMDD.md/.json`。

latest pointer 必須包含實際 artifact filename、cycle id、status、baseline SHA、result SHA 與 `handoff_to`，避免讀到同名舊報告。

### 10.4 Planner 報告必要欄位

- `master_report_path` 與讀取確認。
- `cycle_id`、baseline SHA、branch、origin SHA、dirty classification。
- 前一 QA / closeout artifact 與 status。
- 問題陳述與 evidence。
- 精確 Scope In / Scope Out。
- 預計修改 / 新增檔案。
- RED oracle、最小 GREEN、focused / conditional gates。
- protected contracts、Look-ahead、float、DB / scheduler / UI boundary。
- commit message、stop conditions、rollback commands。
- `plan_status=READY | NO_SAFE_SLICE | REMEDIATION_ONLY | BLOCKED`。

### 10.5 Implementation 報告必要欄位

- `consumed_plan` 的 exact filename / cycle id / baseline SHA。
- 實際修改檔與 diff summary。
- RED 證據、GREEN 證據、所有命令與 exit status。
- root-cause attempts（如有）。
- commit SHA、push 結果、origin SHA。
- protected / quant / data / production boundary 結果。
- 未完成事項與偏離 Plan 的內容；有偏離即不得宣稱完成。
- `implementation_status=IMPLEMENTED_AND_PUSHED | NO_CHANGE | REMEDIATION_REQUIRED | BLOCKED`。

### 10.6 QA 報告必要欄位

- `consumed_implementation` 與 `consumed_plan`。
- 確認 commit parent 等於 Plan baseline，或清楚解釋合法的串接 commit。
- 驗證 diff scope、公開契約、focused tests、conditional gates、Git hygiene。
- 不得只複述 Implementation 報告；必須重跑最關鍵命令。
- `qa_status=READY_TO_CONTINUE | REMEDIATION_REQUIRED | BLOCKED`。
- remediation 必須列 exact file、root-cause evidence、RED、最小修正與驗證命令。

---

## 11. 狀態機與停止條件

### 11.1 狀態定義

- `READY_TO_CONTINUE`：本輪 commit 已 push，獨立 QA 通過。
- `REMEDIATION_REQUIRED`：可在相同安全邊界內修復的測試、格式、型別或最小契約回歸；下一 Planner 只能先排 remediation。
- `BLOCKED`：未知 dirty、production / protected contract、需要外部權限 / 資料、non-fast-forward、語意無法安全判定或三次根因迴圈仍無法收斂。
- `NO_SAFE_SLICE`：沒有能在時間盒內完成全部 Gate 的切片；這不是失敗，禁止強行開工。

### 11.2 立即停止寫入

- 非 ignored dirty file。
- branch 不是 `dev`。
- `git pull --ff-only origin dev` 失敗。
- Plan artifact 缺失、cycle id 不一致或 baseline SHA 不符。
- 需要改 protected contract、production DB、scheduler、交易或正式資料。
- RED oracle 無法穩定重現。
- 實作超出 Plan scope。
- 測試、mypy、py_compile、UI gate、quant guard 或 diff check 未通過。
- push 不是 fast-forward。

不得使用 `reset --hard`、不得覆寫未知變更、不得以跳過測試繼續下一片。

---

## 12. Git、Commit 與回滾

- 每個切片一個 atomic commit；不混入 output、graphify、cache 或其他工作。
- commit 格式：`automation-dev: refactor <node> <slice>`；remediation：`automation-dev: fix <node> <gate>`。
- 每片完整通過後才 push `origin dev`。
- 本片尚未 push：只回退本片明確檔案，先確認沒有其他變更。
- 已 push：使用新的 `git revert <sha>` commit，不 rewrite `dev` 歷史。
- 外部 automation prompt 回滾：使用更新前 snapshot 逐支恢復，保留 id / schedule / model / status。
- 任何回滾後都要重跑原切片 focused Gate 與 Git hygiene。

---

## 13. 成效量測

### 13.1 每片量測

- 原始 façade 行數變化。
- 抽出模組的單一責任與 public surface。
- import edge / cycle 是否減少。
- characterization tests 數量與覆蓋契約。
- focused test、mypy、UI / quant Gate。
- regression / remediation 次數。

### 13.2 每週量測

- God node degree 趨勢，但 Graphify 只作輔助。
- 超過 300 行函式、1,000 行類別數量趨勢。
- module cycle 數。
- Domain → Application / concrete Data 反向 import 數。
- 重複正規化 / 重複 query / 重複計算移除數。
- automation 成功、remediation、blocked、revert 比例。

### 13.3 成功不是 LOC 最小化

Support module 與 characterization tests 可能讓 repo 淨 LOC 上升。只要 façade 降低認知負荷、依賴方向更清楚、契約更可驗證，便屬有效簡化。

---

## 14. 第一批建議候選

Planner 應依最新 QA 自行判斷，當前建議順序如下：

1. 確認並完成 PatternAnalyzer Slice 17，或驗收已完成的對應 commit。
2. 修復兩個低風險 import cycle：`backtest_service` / `walkforward_service` 型別 cycle、`update_service` package import cycle。
3. TechnicalIndicatorCalculator 只建立 golden / warm-up / prefix characterization，不搬公式。
4. MainWindow / TradingAnalysisApp 只建立 startup / navigation / signal wiring characterization。
5. 回到 BacktestView、RecommendationView、UpdateView，選擇已有 oracle 的單一 coordinator / presenter 切片。
6. Decision ↔ Application / Data 依賴反轉先做 design-only plan，不自動搬 DTO。

不得因本清單存在便跳過 Planner 的現況核對；若 HEAD、QA 或測試已改變，Planner 必須以新證據調整。

---

## 15. Definition of Done

單一切片只有在以下全部成立時才完成：

- Plan、Implementation、QA 三份產物可互相追溯。
- 只有 Plan 指定檔案進入 commit。
- 行為契約與副作用順序有 characterization 證據。
- Focused 與條件式 Gate 通過。
- Protected contracts 無非預期 diff。
- Look-ahead / float / data / scheduler boundary 已判定。
- Commit 已 push，`dev == origin/dev`。
- 工作區除 ignored output / graphify 外乾淨。
- QA 狀態為 `READY_TO_CONTINUE`。

整體重構計畫只有在以下成立時才可宣告 closeout：

- 主要 God nodes 已變成薄 façade / coordinator，或有明確保留理由。
- Domain 的 Application / concrete DB 反向依賴已移除或有治理例外。
- import cycle 為零，或每個例外有文件化原因與測試。
- Full App Healthcheck 與人工 smoke 覆蓋主要工作區。
- 無 production 資料、scheduler、交易、投資語意或使用流程回歸。
- 文件索引與目前架構同步。
- 建立 Product Roadmap / Target Architecture 的交棒連結，並停止以重構切片取代產品 Gate。

---

## 16. Planner / Implementation / QA 最短指令摘要

### Planner

讀本報告 → 讀最新 QA / closeout → 查 Git / Graphify / code / tests → 選可完整驗證的最小切片 → 產生精確 Plan；不改 code。

### Implementation

讀本報告與 exact Plan → 驗證 baseline → RED → 最小 GREEN → 全部 Gate → atomic commit / push → 產生 Implementation report；不得自行擴 scope。

### QA

讀本報告、exact Plan 與 Implementation report → 獨立核對 diff / commit / tests / contracts / Git → 產生 READY、REMEDIATION_REQUIRED 或 BLOCKED；不改 code。

---

## 17. 更新規則

本報告只有在下列情況更新：

- 重構安全邊界、automation 產物契約或 protected contracts 改變。
- 新的結構證據使優先波次或依賴方向需要調整。
- 重大重構波次完成，需要更新 continuation anchor。

單一切片完成不必每次修改本報告；進度由 `output/automation/version_loop/` 與 Git 保存。若本報告與架構權威衝突，以 `system_architecture.md` 為準並停止實作、要求人工判定。

- 2026-07-11：新增 Post-Refactor Product Roadmap 與 Target Architecture 交棒連結；明確 Gate 0 closeout 後停止以重構作為產品主線。
