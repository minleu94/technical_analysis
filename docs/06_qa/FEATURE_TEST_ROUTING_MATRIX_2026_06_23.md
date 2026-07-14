# Feature-to-Test Routing Matrix (2026-06-23)

> **Scope**: 本文件是 Testing / QA Agent 所使用的功能對應測試路由矩陣（Feature-to-Test Routing Matrix），定義六大高頻 UI 工作區之測試橋接、對照測試路徑與模式支援。
>
> **角色定義與權威來源**：
> - 本文件僅作為測試路由之知識庫與對照矩陣，不包含 Agent 角色與行為定義。
> - 完整與權威的 Agent 角色定位、職責與工作流程，請參見 [testing_qa_agent.md](../agents/testing_qa_agent.md)。

---

## 1. 測試路由基本原則

Testing / QA Agent 接收到功能驗證請求後，將其映射到系統的六大高頻 UI 工作區之一，並根據本矩陣決策測試模式與稽核需求：
- **Quick Mode**：僅包含執行時間短、無龐大外部/資料依賴、安全無副作用的測試。
- **Full Mode**：包含較重型的 UI 聯動、跨頁 workflow、多 Research Run 比較或較複雜的計算。
- **條件式資料稽核**：僅於涉及真實資料演算、回測正確性校驗、或判定 SQLite / CSV 欄位與資料新鮮度時，方條件式觸發 Data Audit Agent 支援；純 UI smoke / contract 測試則不予觸發。

---

## 2. 六大高頻 UI 功能測試路由矩陣

### 2.1 UpdateView / 資料更新頁

* **Direct Bridge 測試** (可立即執行)：
  * `tests/test_ui_qt_update_view_workbench.py` (id: `ui-update-workbench`)
  * `scripts/qa_validate_update_tab.py` (id: `qa-update-tab`)
* **Candidate UI 測試** (待進一步橋接)：
  * 無
* **Service Oracle 測試** (邏輯驗證)：
  * `tests/test_update_service_status.py`
* **Manual-only / 尚未自動化缺口**：
  * 真實向 TWSE/TPEX 抓取資料時的進度條顯示、長任務取消流程、SQLite 資料同步的對話框確認。
* **是否安全可跑 Quick**：
  * **是** (僅限 `ui-update-workbench` 單元測試；QA validation 腳本必須跑 `Full`，因為它會執行較完整的元件載入與模擬)。
* **資料稽核政策 (Data Audit Policy)**：
  * **條件式觸發 (Conditional)**。執行 UI 佈局 smoke 測試時不觸發；僅於需要比對 SQLite db schema 與 daily price CSV 整合狀態時，才需觸發 Data Audit。

---

### 2.2 Daily Decision Desk / 每日決策

* **Direct Bridge 測試** (可立即執行)：
  * `tests/test_ui_qt_decision_desk_view.py` (id: `ui-decision-desk`)
* **Candidate UI 測試** (待進一步橋接)：
  * `tests/test_ui_qt_decision_desk_main_integration.py`
* **Service Oracle 測試** (邏輯驗證)：
  * `tests/test_decision_desk_dashboard_service.py`
  * `tests/test_decision_desk_risk_prompt_service.py`
  * `tests/test_decision_desk_service.py`
  * `tests/test_decision_desk_ui_contract.py`
* **Manual-only / 尚未自動化缺口**：
  * 各種不同降級狀態（如籌碼缺失、指標過期）在 UI 上的視覺警示排版、Why Not 按鈕點擊後彈出說明的文字可讀性。
* **是否安全可跑 Quick**：
  * **是** (使用 `ui-decision-desk` 驗證元件狀態與 DTO binding)。
* **資料稽核政策 (Data Audit Policy)**：
  * **條件式觸發 (Conditional)**。純 UI smoke 測試不觸發；若需要核實 decision desk 警示所關聯 the watchlist risk 或持倉資料的真偽時才觸發。

---

### 2.3 Research Lab / 策略回測

* **Direct Bridge 測試** (可立即執行)：
  * `tests/test_ui_qt_research_workflow.py` (id: `ui-research-workflow`)
  * `tests/test_ui_qt_run_registry_compare.py` (id: `ui-run-registry-compare`)
* **Candidate UI 測試** (待進一步橋接)：
  * `tests/test_ui_qt_research_lab_mode_driven_ui.py`
  * `tests/test_ui_qt_research_lab_workbench_copy_text.py`
  * `tests/test_ui_qt_research_run_save.py`
* **Service Oracle 測試** (邏輯驗證)：
  * `tests/test_research_lab_mode_taxonomy.py`
  * `tests/test_research_result_presentation.py`
  * `tests/test_research_run_repository.py`
  * `tests/test_research_run_service.py`
* **Manual-only / 尚未自動化缺口**：
  * 回測進度條與 cancel 按鈕的執行緒安全退出、自訂策略參數滑桿的 resize 佈局是否會吃掉文字、Equity Curve 圖表的雙擊放大功能。
* **是否安全可跑 Quick**：
  * **否** (回測策略涉及繁重計算、並行運算與大量 SQLite I/O，建議限於 `Full` 模式跑橋接測試)。
* **資料稽核政策 (Data Audit Policy)**：
  * **條件式觸發 (Conditional)**。純 UI 佈局或回測頁面切換等 UI smoke 測試不需要觸發；僅於需要確認歷史價格完整性、回測邏輯正確性、或判定是否存在 look-ahead bias 時，才需觸發 Data Audit。

---

### 2.4 Market Regime / 市場觀察

* **Direct Bridge 測試** (可立即執行)：
  * `tests/test_ui_qt_market_regime_view.py` (id: `ui-market-regime-view`)
* **Candidate UI 測試** (待進一步橋接)：
  * 無
* **Service Oracle 測試** (邏輯驗證)：
  * `tests/test_walkforward_service.py` (包含 regime label & hysteresis 驗證)
* **Manual-only / 尚未自動化缺口**：
  * 規則匹配度 tooltip 是否與手冊規範的「不是勝率」一致、Regime 分類明細下拉的排版。
* **是否安全可跑 Quick**：
  * **否** (市場狀態判定需要完整的大盤指標與歷史收盤價，計算較繁重，應歸在 `Full` 模式)。
* **資料稽核政策 (Data Audit Policy)**：
  * **條件式觸發 (Conditional)**。UI smoke 測試不觸發；若要核實 Regime 計算數值的真實來源與一致性時才觸發。

---

### 2.5 Smart Money Flow / 主力流向

* **Direct Bridge 測試** (可立即執行)：
  * `tests/test_ui_qt_smart_money_flow_view.py` (id: `ui-smart-money-flow`)
* **Candidate UI 測試** (待進一步橋接)：
  * 無
* **Service Oracle 測試** (邏輯驗證)：
  * `tests/test_smart_money_semantic_service.py`
  * `tests/test_broker_branch_decode.py`
  * `tests/test_broker_flow_units.py`
* **Manual-only / 尚未自動化缺口**：
  * 點擊「下鑽詳細主力流向」與持倉/個股聯動的高亮、多日分點統計排序。
* **是否安全可跑 Quick**：
  * **否** (主力流向需讀取大量券商進出資料，磁碟 I/O 量大，應歸在 `Full` 模式)。
* **資料稽核政策 (Data Audit Policy)**：
  * **條件式觸發 (Conditional)**。主力流向之資料來源為 `broker_flow_dir` 目錄、SQLite `broker_flows` 資料表、以及券商分點基礎資料（非寫死單一 Parquet 解析）。當需要稽核這些分點資料之欄位完整性、主鍵約束以及 ETF 排除代號之 schema 一致性時，才需觸發 Data Audit。

---

### 2.6 Run Registry Compare / 策略比較

* **Direct Bridge 測試** (可立即執行)：
  * `tests/test_ui_qt_run_registry_compare.py` (id: `ui-run-registry-compare`)
* **Candidate UI 測試** (待進一步橋接)：
  * 無
* **Service Oracle 測試** (邏輯驗證)：
  * `tests/test_research_run_comparison_service.py`
* **Manual-only / 尚未自動化缺口**：
  * 橫向跨 run 參數對比、Normalized Equity 曲線 Matplotlib 渲染。
* **是否安全可跑 Quick**：
  * **否** (比較多組 Research Run 需要讀取並載入 SQLite Run metadata 與 Parquet 明細，應限於 `Full` 模式)。
* **資料稽核政策 (Data Audit Policy)**：
  * **從不觸發 (Never)** (純粹比較回測 Registry 數值，無額外外部資料稽核需求)。

---

## 3. 2026-07-13 System Integration 測試路由

| 範圍 | 路由 | 說明 |
|---|---|---|
| `tests/test_cross_workstream_system_integration.py` | slow E2E / environment | 依固定 A→C→E1→D→B→E2→F dependency order 驗證跨流契約；不放 Quick。 |
| `tests/test_verify_system_execution_blueprint.py` | governance / docs / tooling | 純 JSON verifier、malformed input 與 fail-closed contract；可獨立 focused 執行。 |
| `tests/test_full_app_healthcheck_test_inventory.py` | healthcheck-owned contract | 保護 inventory 完整性；新增測試必須先分類，不得以未登錄測試繞過 healthcheck。 |
| Broker latency、P0、PIT、market visibility、corporate action | service oracle / data-market | 需要真實資料判讀時才觸發 Data Audit；正式 DB 一律唯讀並比對 integrity。 |
| `ml/` focused unit tests | general unit / keep in pytest | 僅驗證 shadow contract、split、identity、drift 與 gate；不得宣稱 formal OOS 或 production。 |
| Smart Money async UI | candidate UI bridge | 驗證 loading、stale-result、error recovery 與 UI responsiveness；真實大量 broker I/O 留在 Full。 |

跨流失敗必須回到擁有該 contract 的 workstream 修正。整合 adapter／verifier 不得補缺值、把 `degraded` 改成 ready、放寬 source acceptance／ML promotion Gate，或用 fixture 折抵 forward evidence、real artifact 與人工／時間條件。
