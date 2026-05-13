# AI Context Pack (系統分析與治理規範)

> **目的**：提供給外部 AI 助手（如 ChatGPT、Codex、Antigravity）一個高密度、結構化的專案上下文包。幫助 AI 快速理解專案架構、邊界、工作流與多 Agent 協作規則，避免產生幻覺 (hallucination) 或執行破壞性的重構。

---

## 1. Project Snapshot (專案快照)

* **Project Purpose (專案目標)**：這不是一個簡單的每日報明牌工具，而是一個「可驗證、可回溯、可演化」的投資決策系統。核心精神在於：「看懂市場 -> 嘗試策略 -> 驗證策略 -> 管理持倉」。
* **Current Phase (目前階段)**：Phase 3.3b（研究閉環已完成）與 AI Runtime MVP 已完成。即將邁入 Phase 4（持倉與日誌管理）。
* **Core Architecture (核心架構)**：三層式解耦架構。
  1. `ui_qt/`（純粹的觀察者 Observatory / 渲染層）
  2. `app_module/`（應用服務層與協調器 Orchestrator）
  3. Domain 模組（`backtest_module/`、`analysis_module/`、`runtime/`）
* **Major Modules (主要模組)**：資料收集器、市場觀察儀、推薦引擎、策略回測實驗室、籌碼分析終端 (Smart Money Terminal MVP)、Runtime 子系統。
* **UI Structure (UI 結構)**：基於 PySide6 (Qt) 建構。擁有固定的頂層 Tab（Update、Market Watch、Recommendation、Backtest）。大量使用 `pandas_table_model` 呈現高密度數據網格。
* **Current Priorities (目前優先事項)**：
  1. 找出 UX 與理解上的斷點（強化 Why/WhyNot 解釋）。
  2. 補齊日常流程與關鍵指標的文件（維持一致性）。
  3. 回測對標呈現方式定稿（Walk-forward / 過擬合風險提示）。
* **Technical Stack (技術棧)**：Python 3, PySide6 (Qt), Pandas, SQLite, Parquet, Selenium（用於券商分點爬蟲）。
* **Known Pain Points (已知痛點)**：
  1. 券商分點資料爬蟲容易因特殊股票代碼（如 ETF）解析失敗。
  2. UI 與 Service 狀態的同步一致性挑戰。
  3. 參數的單位一致性與可比較性（已在 Phase 2.5 透過 ATR-based 與 z-score 獲得大幅改善）。

---

## 2. Agent Inventory (Agent 盤點)

專案使用特定的 AI 角色（定義於 `docs/agents/` 與 Cursor Skills 中）。

### Tech Lead Agent (`tech_lead.md`)
* **Purpose (目的)**：負責技術決策、架構方向與風險評估。
* **Responsibilities (職責)**：評估設計提案，確保符合 Roadmap。
* **Strong At (擅長)**：風險雷達 (Risk Radar)、架構審查。
* **Weak At (弱項)**：實作細節與寫 code。
* **Typical Tasks (典型任務)**：評估是否該實作某功能並定義 MVP 範圍。
* **Allowed Areas (允許範圍)**：讀取所有文檔、審查 DTO 契約。
* **Forbidden Areas (禁止範圍)**：撰寫或重構實際程式碼。

### Data Audit Agent (`data_audit_agent.md`)
* **Purpose (目的)**：資料完整性與品質驗證。
* **Responsibilities (職責)**：稽核資料集一致性、跨資料源比對。
* **Strong At (擅長)**：找出缺失欄位、型別錯誤、異常值。
* **Weak At (弱項)**：功能開發。
* **Typical Tasks (典型任務)**：比對 FinMind 與 TWSE 資料、稽核券商分點資料。
* **Allowed Areas (允許範圍)**：讀取原始資料檔、撰寫驗證腳本。
* **Forbidden Areas (禁止範圍)**：破壞性的資料修改。

### Data Cleanup Agent (`data_cleanup_agent.md`)
* **Purpose (目的)**：清理專案技術債。
* **Responsibilities (職責)**：掃描死碼 (Dead code)、精簡依賴項。
* **Strong At (擅長)**：辨識未使用的 imports、重複邏輯。
* **Weak At (弱項)**：架構決策。
* **Typical Tasks (典型任務)**：提出 `requirements.txt` 精簡計畫。
* **Allowed Areas (允許範圍)**：掃描整個 codebase。
* **Forbidden Areas (禁止範圍)**：未經人類核准的直接刪除行為。

### Execution Agent (`execution_agent.md`)
* **Purpose (目的)**：嚴格的任務實作。
* **Responsibilities (職責)**：依照指令精準實作，不添加未要求的重構或功能。
* **Strong At (擅長)**：精準修復 Bug、提供可回滾 (rollback) 的 diff 清單。
* **Weak At (弱項)**：模糊的架構規劃。
* **Typical Tasks (典型任務)**：實作 DTO 欄位擴充、修復 UI Bug。
* **Allowed Areas (允許範圍)**：指定的模組與檔案。
* **Forbidden Areas (禁止範圍)**：未經授權的大範圍重構。

### Documentation Agent (`documentation_agent.md`)
* **Purpose (目的)**：確保文檔與 codebase 狀態同步。
* **Responsibilities (職責)**：掃描 PR/diff 並更新索引、快照 (Snapshot) 與開發路線圖。
* **Strong At (擅長)**：維持 Single Source of Truth (SSOT)。
* **Allowed Areas (允許範圍)**：`docs/` 資料夾。
* **Forbidden Areas (禁止範圍)**：修改業務邏輯。

---

## 3. Workflow Map (工作流地圖)

### A. 日常人類研究工作流 (Daily Human Research Workflow)
* **Purpose (目的)**：日常選股與投資研究。
* **Path (路徑)**：更新數據 (Update Data) ➔ 市場觀察看 Regime (Market Watch) ➔ 推薦分析選 Profile (Recommendation) ➔ 加入候選池 (Watchlist) ➔ 策略回測驗證 (Backtest) ➔ 升級保存策略 (Promote)。
* **Dependent Agents (依賴 Agent)**：Execution Agent（用於擴展 UI 或除錯）。
* **Typical Use Case (典型情境)**：每日盤後產生推薦清單並驗證策略勝率。

### B. 多 Agent 協作工作流 (Multi-Agent Development Workflow)
* **Purpose (目的)**：協調平行開發的 AI Agent，減少邊界模糊。
* **Path (路徑)**：`main` (穩定版) ➔ `ag/*` (UI、快速迭代) / `codex/*` (架構治理、基礎設施) ➔ `integration/*` (整合分支) ➔ `main`。
* **Branch Ownership Semantics (分支擁有權語意)**：嚴格劃分以下所有權以減少重疊：
  - `codex/*`：專注於架構安全 (architecture-safe) 與資料傳輸 (DTO-safe) 的底層實作。
  - `ag/*`：專注於高頻迭代、視覺化與純前端實作。
  - `integration/*`：**暫時性收斂分支 (Temporary convergence branch)**，絕非永久擁有權分支。僅用於多 Agent 協作驗證，待人類審查後再合併至 `main`。
  - `research/*` / `experiment/*`：探索性研究與技術驗證，不直接合併生產代碼。
* **Overlap Workflows (重疊風險)**：兩邊 Agent 可能同時更新核心索引（如 `DOCUMENTATION_INDEX.md`）。
* **Conflict Resolution (衝突解決)**：絕對不要直接覆寫對方的實作。必須提出 Compatibility adapter 或合作合併索引檔。

### C. 券商分點資料工作流 (Broker Branch Data Workflow) - ⚠️ Risky
* **Purpose (目的)**：透過 Selenium 爬取每日對手券商籌碼。
* **Path (路徑)**：下載 CSV ➔ 標準化 Registry ➔ 合併資料 ➔ 透過 DTO 提供給 UI。
* **Risky Workflow (風險)**：高度脆弱。容易因為外部網站 HTML 結構改變或編碼問題 (Mojibake) 崩潰，需要 Execution Agent 隨時準備修復。

---

## 4. Architecture Governance (架構治理)

### Layer Boundaries (分層邊界與禁止依賴)
* **UI Layer (`ui_qt/`)**：絕對不可 import `repository/db` 或內部 Domain 邏輯檔案。必須只透過 `app_module` 的 DTOs 溝通。
* **App Layer (`app_module/`)**：絕對不可 import `PySide6` 或任何 Qt 專屬套件。不可包含 HTML/CSS 等 UI 格式化字串。
* **Domain/Runtime Layer (`runtime/`)**：絕對不可 import `app_module` 或 `ui_qt`。必須保持純 Python 實作。

### Shared Contract Safety (DTO 規則)
* **Rules (規則)**：禁止靜默重新命名共用 DTO、禁止隨意改變 event payload schema 或服務簽名 (signatures)。
* **Extension Strategy (擴展策略)**：優先使用增量開發 (Additive changes)。若需棄用，請標示 `@deprecated` 而非直接刪除。

### AI Runtime & Event Rules (執行階段與事件規則)
* **EventBus**：純 Python `Callable` 列表，完全不依賴 Qt。
* **Bridging**：透過 `QtRuntimeBridge` 將 EventBus 的事件解耦並翻譯為 UI 需要的 `pyqtSignal`。
* **Runtime Rules**：嚴格的狀態機生命週期 (`IDLE` ➔ `DISPATCHED` ➔ `THINKING` ➔ `VALIDATING` ➔ `APPROVED`/`ERROR`/`HALTED`)。
* **Decision Module Rules**：UI 必須是純粹的觀察者 (Observatory)，將決策邏輯推遲到 Domain 層。

---

## 5. Documentation Index (重要文檔索引)

### Canonical Docs (權威文檔 - Source-of-Truth Level: HIGH)
* **`docs/00_core/DEVELOPMENT_ROADMAP.md`**：專案開發階段的絕對 SSOT。請特別注意「Living Section」段落以獲取當前最新狀態。
* **`docs/00_core/PROJECT_SNAPSHOT.md`**：開場 30 秒必讀的快照文件。內容必須與 Roadmap 的 Living Section 同步。
* **`docs/01_architecture/multi_agent_workflow.md`**：規範 AI Agent 應如何分支與合併的協議。
* **`docs/01_architecture/runtime_observatory_rules.md`**：嚴格的相依性與 DTO 架構治理規則。

### Important Technical Docs (重要技術文檔)
* **`docs/00_core/DOCUMENTATION_INDEX.md`**：查找所有功能說明文件的主索引。
* **`docs/agents/shared_context.md`**：所有 AI 運作不可違背的前提（如強制使用繁體中文）。

### Outdated / Deprecated Docs (過時與冗餘文檔)
* 舊版 `ui_app/README.md` (Tkinter) 相較於新的 `ui_qt` 堆疊已屬舊版遺產。
* Roadmap 中歷史 Phase 的 Exit criteria 屬於歷史紀錄；理解當前狀態請只看「Living Section」。
* （已清理：重複的 `docs/architecture/` 與空的 `docs/governance/` 資料夾已被移除，統一收斂至 `01_architecture/`）。

---

## 6. AI Task Routing Recommendation (AI 任務路由建議)

請根據任務性質，交由最適合的 AI 執行：

### Codex
* **Best For (適合)**：`architecture planning`（架構規劃）、`governance validation`（治理驗證）、`architecture-sensitive implementation`（架構敏感實作）、`migration-safe implementation`（安全轉移實作）、`domain-layer foundation work`（領域層基礎建設）。
* **Focus (重點)**：保持 DTO 安全、維護重放/可審計性 (replay/auditability foundation)、進行受控的領域層與架構安全 MVP 開發。
* **Branch Prefix**：`codex/*`

### Antigravity (AG)
* **Best For (適合)**：`rapid implementation`（快速實作）、`UI-heavy work`（重度 UI 開發）、`iteration-heavy features`（高頻迭代功能）、`visualization`（資料視覺化）、`workflow polishing`（工作流拋光）、`integration-heavy tasks`（重度整合任務）。
* **Focus (重點)**：專注於快速迭代、渲染層 (PyQt6) 效能最佳化、精準的 Bug 修復與前端服務整合。
* **Branch Prefix**：`ag/*`

### Integration Workflow (多 Agent 整合)
* **Best For (適合)**：跨領域功能的共用測試與驗證（例如包含架構與 UI 的 MVP 實作）。
* **Focus (重點)**：作為 `codex` 與 `ag` 產出的**暫時性收斂分支**，不可被單一 Agent 永久擁有。
* **Branch Prefix**：`integration/*`

### ChatGPT / Gemini (Conversational/Exploratory)
* **Best For (適合)**：`exploratory research`（探索性研究）、分析複雜的 Pandas 資料邏輯、視覺化繪圖腳本、腦力激盪風險參數。
* **Branch Prefix**：`research/*`, `experiment/*`

### Human Only (僅限人類)
* **Best For (適合)**：PR 合併至 `main` 的最終決策、架構所有權的定奪、實際交易與資金分配決策。
* **Restriction (限制)**：AI Agent 絕對禁止在未經 Human architecture owner 許可下，直接 merge 代碼至 `main`。

---

## 7. Current Active Roadmap (目前活躍開發路線)

* **Active Phase (目前階段)**：Phase 3.3b（研究閉環）已完成。
* **In Progress (進行中)**：
  * Smart Money Terminal（籌碼終端視覺化與高密度渲染）。
  * AI Runtime Subsystem 的 UI 深度整合。
* **Planned (計畫中)**：Phase 4（持倉與日誌管理 Portfolio & Journal）。Phase 5（效能擴展與報告輸出）。
* **Frozen (已凍結/穩定)**：Phase 1 (市場觀察), Phase 2 (策略資料庫), Phase 2.5 (參數標準化)。
* **Deprecated (已棄用)**：不具備 DTO 抽象層的 Monolithic UI 元件。
* **Experimental (實驗中)**：`codex/review-ai-platform-architecture` (平台治理架構審查)。

---

## 8. Risk Report (風險雷達與報告)

* **AI Coordination Risk (AI 協作風險)**：`codex` 與 `ag` 兩個 Agent 容易在修改共同索引（如 `DOCUMENTATION_INDEX.md`）時發生 Merge Conflict。必須嚴格遵循不覆寫對方實作的衝突解決規範。
* **Branch Ambiguity Risk (分支邊界模糊風險)**：如果任務同時包含「架構變更」與「大量 UI 更新」，可能導致分支命名與擁有權混淆（例如 phase4-trade-led-mvp）。解決方案 (Handoff Workflow)：將基礎 DTO 與核心邏輯拆分至 `codex/*` 確保架構與遷移安全；UI 綁定與迭代交由 `ag/*` 處理。對於大型功能，應設立 `integration/<feature-name>` 分支作為雙方的暫時性共用驗證目標，避免單一 Agent 分支承載過多混合邏輯。
* **Governance Risk (架構治理風險)**：隱性耦合 (Hidden coupling)。例如偷偷在共用 DTO 內增加非標準欄位，或是繞過 `EventBus` 直接在 UI 呼叫底層 API。
* **Unclear Ownership (邊界模糊風險)**：將過多資料處理邏輯放在 `ui_qt` 裡面，而非在 Domain 處理完畢後透過 DTO 傳遞。UI 必須純粹是個 Observatory。
* **Workflow Confusion (工作流混亂)**：目前存在多個 `qa_validate_*.py` 腳本，AI 在開發後可能會忘記執行對應模組的 QA 腳本導致 Regression。
* **Doc Inconsistency (文檔不一致風險)**：Agent 在修改程式碼後，常常忘記呼叫 Documentation Agent 同步更新 `PROJECT_SNAPSHOT.md` 與 `DEVELOPMENT_ROADMAP.md` 的 Living Section。
