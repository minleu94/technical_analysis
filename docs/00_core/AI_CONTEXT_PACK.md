# AI Context Pack (系統分析與治理規範)

> **目的**：提供給外部 AI 助手（如 ChatGPT、Codex、Antigravity）一個高密度、結構化的專案上下文包。幫助 AI 快速理解專案架構、邊界、工作流與多 Agent 協作規則，避免產生幻覺 (hallucination) 或執行破壞性的重構。

---

## 1. Project Snapshot (專案快照)

* **Project Purpose (專案目標)**：這不是一個簡單的每日報明牌工具，而是一個「可驗證、可回溯、可演化」的投資決策系統。核心精神在於：「看懂市場 -> 嘗試策略 -> 驗證策略 -> 管理持倉」。
* **Current Phase (目前階段)**：三個產品閉環的基礎與主要深化已完成。Roadmap 已從單一最高權威重構為 Scoped SSOT：Snapshot 管現在、6M Roadmap 管未來工程路線、system architecture 管架構、archive 管歷史。當前主線是 Month 3 Factor Layer v1 與 Research Run factor metadata 追溯。
* **Core Architecture (核心架構)**：分層解耦架構。
  1. `ui_qt/`（PySide6 UI / Observatory / 渲染層）
  2. `app_module/`（應用服務層、DTO、Repository 與 use case orchestrator）
  3. Domain / Engine 模組（`decision_module/`、`backtest_module/`、`portfolio_module/`、`analysis_module/`、`data_module/`、`runtime/`）
* **Major Modules (主要模組)**：資料更新工作台、市場觀察儀、推薦引擎、Research Lab、Research Run Registry、Factor Layer v1、籌碼分析終端、Portfolio 監控、Runtime 子系統。
* **UI Structure (UI 結構)**：基於 PySide6 (Qt) 建構。目前有 7 個頂層 Tab：數據更新、市場觀察（含主力流向子 Tab）、策略回測（Research Lab 多模式實驗室語意）、推薦分析、觀察清單、持倉管理、Runtime Observatory。大量使用 `pandas_table_model` 呈現高密度數據網格。
* **Current Priorities (目前優先事項)**：
  1. Month 3 Factor Layer v1：Factor Contract、Registry、Look-ahead Gate、既有技術 / 量能 / 券商分點 adapters 與 FactorService snapshot/contribution serialization。
  2. Month 3 研究追溯：`ResearchRunService.save_run()` 已可在實際寫入流程保存 `factor_snapshot` / `factor_contributions`；推薦組合回放已先供給 `technical.total_score` 與 `volume.volume_ratio` metadata，後續要擴大到單股回測與更多 Research Lab 路徑。
  3. 已完成 Gate 的回歸維護：Month 1 fixed / quantile OOS 實證、SQLite 穩定分頁、規格化 Excel 報告匯出、Month 2 M2-A / M2-B / M2-C / final registry governance gate。
* **Technical Stack (技術棧)**：Python 3, PySide6 (Qt), Pandas, SQLite, Parquet, Selenium（用於券商分點爬蟲）。
* **Known Pain Points (已知痛點)**：
  1. Quantile 的真實 OOS 實證未優於 fixed，因此仍維持 opt-in，不可宣稱更準。
  2. Factor Layer v1 已建立基礎與 Research Run 實際保存入口，推薦組合回放已有初始 factor feed；更多上游流程仍需持續餵入 factor records，避免部分 run 只有空的追溯欄位。
  3. 營收、基本面、估值與三大法人尚未成為正式資料因子；未來接入必須保存 `available_date`、quality 與 missing policy。
  4. PDF 研究報告輸出仍是後續 backlog；Excel 報告與 SQLite 穩定分頁已完成。

---

## 2. Agent Inventory (Agent 盤點)

專案使用特定的 AI 角色（定義於 repo 根目錄 `AGENTS.md`、`GEMINI.md` 與 `docs/agents/` 中）。Codex 的自動讀取入口是 `AGENTS.md`；Antigravity 的自動讀取入口是 `GEMINI.md`；`docs/agents/*.md` 是唯一角色與規則權威。`docs/agents/skills_registry.md` 僅負責 Codex / Antigravity 共用的角色選擇、流程導引與 shared context 入口，不重新定義 Agent。

### Tech Lead Agent (`tech_lead.md`)
* **Purpose (目的)**：負責技術決策、架構方向與風險評估。
* **Responsibilities (職責)**：評估設計提案，確保符合 Snapshot、6M Roadmap、Architecture 與專項規格的 scoped authority。
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
* **Responsibilities (職責)**：掃描 PR/diff 並更新 Snapshot、6M Roadmap、Roadmap Hub、Architecture、Index 與專項文檔。
* **Strong At (擅長)**：維持 Scoped SSOT 與文件一致性。
* **Allowed Areas (允許範圍)**：`docs/` 資料夾。
* **Forbidden Areas (禁止範圍)**：修改業務邏輯。

---

## 3. Workflow Map (工作流地圖)

### A. 日常人類研究工作流 (Daily Human Research Workflow)
* **Purpose (目的)**：日常選股與投資研究。
* **Path (路徑)**：數據更新工作台執行快速更新或安全更新 (Update Workbench) ➔ 市場觀察看 Regime / Smart Money (Market Watch) ➔ 推薦分析選 Profile 並查看 Why / Why Not (Recommendation) ➔ 加入候選池 (Watchlist) ➔ Research Lab 執行單股 / 批次 / 固定組合 / 推薦回放驗證 ➔ 保存到 Research Run Registry ➔ 符合 Gate 才升級策略版本 (Promote)。
* **Dependent Agents (依賴 Agent)**：Execution Agent（用於擴展 UI 或除錯）。
* **Typical Use Case (典型情境)**：每日盤後產生推薦清單並驗證策略勝率。

### B. 多 Agent 協作工作流 (Simplified Main-Centric Workflow)
* **Purpose (目的)**：降低多分支維護成本，恢復單一工作區的穩定開發體驗。
* **Path (路徑)**：`main` (Primary active branch)。所有 Agent 直接在 `main` 上進行協作與迭代。
* **Agent Roles (角色分工作業)**：
  - **Antigravity (AG)**：做為主要的 IDE/Workspace 環境，負責監控專案狀態與高頻 UI/功能實作。
  - **Codex**：繼續擔任架構審查者 (architecture reviewer)、具備治理意識的實作者 (governance-aware implementer) 與受控重構助手，但其變更應直接收斂回 `main`。
* **Branch Creation Rules (分支建立規範)**：
  - 暫停使用長效型 (long-lived) 的 `codex/*`、`ag/*` 或 `integration/*` 分支作為持續開發分支。
  - **僅在以下情況允許建立暫時性分支**：高風險實驗 (risky experiments)、大型重構 (large refactors)、破壞性遷移 (destructive migrations)。
  - 建立任何分支前必須明確論述：(1) 為何需要隔離 (2) 降低了什麼風險 (3) 預期合併策略 (4) 預期分支生命週期。
* **Conflict Resolution (衝突解決)**：保持頻繁提交與同步。絕對不要直接覆寫對方的實作。

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
* **Factor Layer (`decision_module/factors/` + `app_module/factor_service.py`)**：新資料不得直接硬接 `ScoringEngine`。所有 factor 必須保留 `as_of_date`、`available_date`、quality、missing policy 與 source version，並由 Look-ahead Gate 驗證。

### Shared Contract Safety (DTO 規則)
* **Rules (規則)**：禁止靜默重新命名共用 DTO、禁止隨意改變 event payload schema 或服務簽名 (signatures)。
* **Extension Strategy (擴展策略)**：優先使用增量開發 (Additive changes)。若需棄用，請標示 `@deprecated` 而非直接刪除。

### AI Runtime & Event Rules (執行階段與事件規則)
* **EventBus**：純 Python `Callable` 列表，完全不依賴 Qt。
* **Bridging**：透過 `QtRuntimeBridge` 將 EventBus 的事件解耦並翻譯為 UI 需要的 `pyqtSignal`。
* **Runtime Rules**：嚴格的狀態機生命週期 (`IDLE` ➔ `DISPATCHED` ➔ `THINKING` ➔ `VALIDATING` ➔ `APPROVED`/`ERROR`/`HALTED`)。
* **Decision Module Rules**：UI 必須是純粹的觀察者 (Observatory)，將決策邏輯推遲到 Domain 層。

### Research Run / Factor Traceability Rules (研究保存與因子追溯規則)
* **Research Run Registry**：新「保存結果」入口以 `ResearchRunService.save_run()` 為唯一寫入 owner；metadata 寫入 SQLite，equity curve 與 trades 寫入 Parquet，並以 staging / files_ready / committed 狀態與 hash 驗證防止半成品被當成成功結果。
* **Factor Metadata**：`data_manifest.factor_snapshot` 保存當時可見的 factor 狀態，`data_manifest.factor_contributions` 保存由 snapshot 產生的 contribution summary。Cross-run Comparison 只能讀已保存 metadata，不得比較時重新抓取當前資料。
* **No Performance Claim**：Factor Layer v1 只建立可追溯與資料治理能力，不代表績效改善；任何「更準」宣稱都必須另走 OOS 實證。

---

## 5. Documentation Index (重要文檔索引)

### Canonical Docs (權威文檔 - Scoped Source-of-Truth)
* **`docs/00_core/PROJECT_SNAPSHOT.md`**：開場 30 秒必讀的目前狀態、本週優先事項與高風險區。
* **`docs/00_core/ROADMAP_6M_ENGINEERING.md`**：未來 6 個月可執行工程路線。
* **`docs/00_core/DEVELOPMENT_ROADMAP.md`**：Roadmap Hub，指向 Snapshot、6M Roadmap、Architecture 與 archive。
* **`docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`**：舊 Roadmap 未完成事項的唯一移交與驗收矩陣。
* **`docs/01_architecture/system_architecture.md`**：目前架構、模組邊界與資料流權威。
* **`docs/07_guides/APPLICATION_MANUAL.md`**：目前 7 個工作區與跨工作區流程的完整操作權威。
* **`docs/01_architecture/multi_agent_workflow.md`**：規範 AI Agent 應如何分支與合併的協議。
* **`docs/01_architecture/runtime_observatory_rules.md`**：嚴格的相依性與 DTO 架構治理規則。

### Important Technical Docs (重要技術文檔)
* **`docs/00_core/DOCUMENTATION_INDEX.md`**：查找所有功能說明文件的主索引。
* **`AGENTS.md`**：Codex 自動讀取的 repo 根目錄指令入口，指向 `docs/agents/` 的完整 Agent 架構。
* **`docs/agents/shared_context.md`**：所有 AI 運作不可違背的前提（如強制使用繁體中文）。

### Outdated / Deprecated Docs (過時與冗餘文檔)
* 舊版 `ui_app/README.md` (Tkinter) 相較於新的 `ui_qt` 堆疊已屬舊版遺產。
* 舊 Roadmap 中歷史 Phase 的 Exit criteria 屬於歷史紀錄；理解當前狀態請看 `PROJECT_SNAPSHOT.md`，理解未來方向請看 `ROADMAP_6M_ENGINEERING.md`。
* （已清理：重複的 `docs/architecture/` 與空的 `docs/governance/` 資料夾已被移除，統一收斂至 `01_architecture/`）。
* `docs/agents/archive/CURSOR_SKILLS_DEFINITIONS.md` 是舊 Cursor Skills 歷史定義，僅保留作為遷移參考；Codex / Antigravity 日常協作請使用 `docs/agents/skills_registry.md` 與 `docs/agents/*.md`。
* `docs/09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md` 是舊完整 Roadmap，只作追溯，不作目前狀態或未來工程路線依據。

---

## 6. AI Task Routing Recommendation (AI 任務路由建議)

請根據任務性質，交由最適合的 AI 執行：

### Codex
* **Best For (適合)**：`architecture planning`（架構規劃）、`governance validation`（治理驗證）、`architecture-sensitive implementation`（架構敏感實作）、`migration-safe implementation`（安全轉移實作）、`domain-layer foundation work`（領域層基礎建設）。
* **Focus (重點)**：保持 DTO 安全、維護重放/可審計性 (replay/auditability foundation)、進行受控的領域層與架構安全 MVP 開發。
* **Branch Prefix**：預設直接在 `main` 開發。若需隔離（如破壞性重構）才建立 `codex/*` 暫時分支。

### Antigravity (AG)
* **Best For (適合)**：`rapid implementation`（快速實作）、`UI-heavy work`（重度 UI 開發）、`iteration-heavy features`（高頻迭代功能）、`visualization`（資料視覺化）、`workflow polishing`（工作流拋光）、`integration-heavy tasks`（重度整合任務）。
* **Focus (重點)**：作為主要的工作區與 IDE 環境。專注於快速迭代、渲染層 (PySide6) 效能最佳化、精準的 Bug 修復與前端服務整合。
* **Branch Prefix**：預設直接在 `main` 開發。若需隔離才建立 `ag/*` 暫時分支。

### ChatGPT / Gemini (Conversational/Exploratory)
* **Best For (適合)**：`exploratory research`（探索性研究）、分析複雜的 Pandas 資料邏輯、視覺化繪圖腳本、腦力激盪風險參數。
* **Branch Prefix**：僅在實驗需要時建立 `research/*` 或 `experiment/*` 暫時分支。

### Human Only (僅限人類)
* **Best For (適合)**：PR 合併至 `main` 的最終決策、架構所有權的定奪、實際交易與資金分配決策。
* **Restriction (限制)**：AI Agent 絕對禁止在未經 Human architecture owner 許可下，直接 merge 代碼至 `main`。

---

## 7. Current Active Roadmap (目前活躍開發路線)

* **Active Phase (目前階段)**：三個產品閉環已建立，進入 6 個月工程路線執行期。
* **In Progress (進行中)**：
  * Month 3 Factor Layer v1：Factor Contract、Registry、Look-ahead Gate、既有技術 / 量能 / 券商分點 adapters、FactorService snapshot/contribution serialization。
  * Research Run factor metadata 追溯：`ResearchRunService.save_run()` 已接入 `factor_snapshot` / `factor_contributions` 實際保存流程；推薦組合回放已供給初始 factor records，後續擴大到單股回測等路徑。
  * Month 2 Registry governance gate 回歸維護。
* **Planned (計畫中)**：營收與估值資料、三大法人資料、Portfolio post-trade attribution、PDF 研究報告輸出、策略 promote / demote / retire 規則。
* **Frozen (已凍結/穩定)**：Phase 1 (市場觀察), Phase 2 (策略資料庫), Phase 2.5 (參數標準化), Phase 3.3b (研究閉環), Smart Money Terminal MVP, AI Runtime MVP。
* **Deprecated (已棄用)**：不具備 DTO 抽象層的 Monolithic UI 元件。
* **Backlog**：單股回測與更多 Research Lab 路徑的 factor records 自動供給、估值相對分位、法人籌碼交叉驗證、PDF 報告輸出。

---

## 8. Risk Report (風險雷達與報告)

* **Quantile Evidence Result (分位數實證結果)**：10 檔 OOS pilot 的樣本與 Regime coverage Gate 已通過，但 quantile 未優於 fixed，不能宣稱 quantile 更準。
* **Factor Look-ahead Risk (因子未來函數風險)**：營收、財報、法人與估值資料必須保存可得日，決策不得使用當下尚未公告的資料。
* **Financial Core Boundary Risk (金融核心數值邊界風險)**：核心金額、交易成本、PnL、倉位與風控不可新增裸 `float`；analytics / visualization 邊界需清楚標示。
* **AI Coordination Risk (AI 協作風險)**：`codex` 與 `ag` 兩個 Agent 容易在修改共同索引（如 `DOCUMENTATION_INDEX.md`）時發生 Merge Conflict。必須嚴格遵循不覆寫對方實作的衝突解決規範。
* **Branch Management Overhead (分支管理成本風險)**：過多的分支與複雜的 Handoff 工作流會導致開發節奏拖慢與狀態混淆。解決方案：嚴格遵循 Main-Centric 工作流，減少不必要的分支切換。現有 feature 分支在驗證後應盡快合併至 `main`、封存或刪除。
* **Governance Risk (架構治理風險)**：隱性耦合 (Hidden coupling)。例如偷偷在共用 DTO 內增加非標準欄位，或是繞過 `EventBus` 直接在 UI 呼叫底層 API。
* **Unclear Ownership (邊界模糊風險)**：將過多資料處理邏輯放在 `ui_qt` 裡面，而非在 Domain 處理完畢後透過 DTO 傳遞。UI 必須純粹是個 Observatory。
* **Workflow Confusion (工作流混亂)**：目前存在多個 `qa_validate_*.py` 腳本，AI 在開發後可能會忘記執行對應模組的 QA 腳本導致 Regression。
* **Doc Authority Confusion (文檔權威混淆風險)**：Agent 可能把所有狀態重新塞回 Roadmap Hub。正確做法是依主題更新 Snapshot、6M Roadmap、Architecture、Index 或 archive。
