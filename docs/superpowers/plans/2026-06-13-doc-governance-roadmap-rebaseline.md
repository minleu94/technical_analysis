# Doc Governance Roadmap Rebaseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將專案文件從單一 Roadmap 全域權威改為 Scoped SSOT，並建立 6 個月可執行工程路線。

**Architecture:** `DEVELOPMENT_ROADMAP.md` 改為 Roadmap Hub；未來工程路線移至 `ROADMAP_6M_ENGINEERING.md`；舊完整 Roadmap 歸檔至 `09_archive/`。Snapshot、Index、Coverage Map、Architecture、Agent 指引同步改為分範圍權威。

**Tech Stack:** Markdown 文件、PowerShell / ripgrep 檢查、pytest/mypy 僅在程式碼或 UI 行為變更時需要。

---

### Task 1: Core Roadmap Split

**Files:**
- Move: `docs/00_core/DEVELOPMENT_ROADMAP.md` -> `docs/09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md`
- Create: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Create: `docs/00_core/ROADMAP_6M_ENGINEERING.md`

- [x] **Step 1: Preserve legacy roadmap**

Run: `git mv docs\00_core\DEVELOPMENT_ROADMAP.md docs\09_archive\DEVELOPMENT_ROADMAP_LEGACY_2026_06.md`

Expected: 舊 Roadmap 完整保留在 archive。

- [x] **Step 2: Create Roadmap Hub**

新增 Roadmap Hub，明確列出 Snapshot、6M Roadmap、Architecture、Index、Archive 的權威範圍。

- [x] **Step 3: Create 6M Engineering Roadmap**

新增 6 個月路線，包含 Track A-E、Month 1-6、交付物與驗收標準。

### Task 2: Update Core Documentation Authority

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/DOC_COVERAGE_MAP.md`
- Modify: `docs/00_core/DOCUMENTATION_STRUCTURE.md`
- Modify: `docs/00_core/AI_CONTEXT_PACK.md`

- [x] **Step 1: Update Snapshot**

把舊 Roadmap current section 權威改為 scoped authority，並把本週優先事項對齊 Month 1。

- [x] **Step 2: Update Index**

新增 `ROADMAP_6M_ENGINEERING.md` 與 legacy roadmap archive，調整核心入口說明。

- [x] **Step 3: Update Coverage Map**

把「Roadmap 最高權威」改為「依主題判斷 scoped authority」。

- [x] **Step 4: Update Documentation Structure**

將 `00_core/` 的用途改為核心入口與分範圍權威，不再只有單一 roadmap 權威。

- [x] **Step 5: Update AI Context Pack**

同步目前主線、權威文件與 6 個月工程路線。

### Task 3: Update Architecture And Root Navigation

**Files:**
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `PROJECT_NAVIGATION.md`
- Modify: `PROJECT_INVENTORY.md`
- Modify: `README.md`
- Modify: `docs/README.md`

- [x] **Step 1: Update system architecture**

把 Phase 4.1 / 4.2 舊狀態改為目前完成狀態，加入 factor layer 與 scoped docs authority。

- [x] **Step 2: Update navigation and inventory**

修正 Portfolio、Roadmap 與文件入口說明。

- [x] **Step 3: Update README files**

更新目前主線與 docs 入口。

### Task 4: Update Agent Instructions

**Files:**
- Modify: `AGENTS.md`
- Modify: `GEMINI.md`
- Modify: `docs/agents/README.md`
- Modify: `docs/agents/shared_context.md`
- Modify: `docs/agents/skills_registry.md`
- Modify: `docs/agents/tech_lead.md`
- Modify: `docs/agents/documentation_agent.md`
- Modify: `docs/agents/execution_agent.md`
- Modify: `docs/agents/skills/team.md`
- Modify: `docs/agents/antigravity/*.md`

- [x] **Step 1: Update required reading order**

加入 Roadmap Hub 與 6M Engineering Roadmap 的讀取規則。

- [x] **Step 2: Update role boundaries**

把「不可修改 roadmap」改成「不得未授權改變 scoped authority 或 phase/track 定位」。

- [x] **Step 3: Update Documentation Agent workflow**

把舊 Snapshot / Index / Roadmap 一致性改成 Snapshot / Roadmap Hub / 6M Roadmap / Architecture / Index 一致性。

### Task 5: Verification

**Files:**
- All modified Markdown files

- [x] **Step 1: Search for stale authority language**

Run: `rg -n "Living Section|以 .*DEVELOPMENT_ROADMAP\.md.*為準|Roadmap / Snapshot|Snapshot / Index / Roadmap|Roadmap/Snapshot|Portfolio Tab 尚未完成|Phase 5：尚未開始" docs AGENTS.md GEMINI.md README.md PROJECT_NAVIGATION.md PROJECT_INVENTORY.md .agent\rules -g "*.md" -g "!docs/09_archive/**"`

Expected: Active 文件不再把舊 Roadmap current section 當目前狀態依據；Archive、舊 superpowers plans/specs 與 `docs/agents/archive/` 可保留歷史語句。

- [x] **Step 2: Check git status**

Run: `git status --short`

Expected: 只包含本次文件治理相關變更。

- [x] **Step 3: Review links**

Run: `rg -n "DEVELOPMENT_ROADMAP_LEGACY_2026_06|ROADMAP_6M_ENGINEERING|DEVELOPMENT_ROADMAP.md" docs AGENTS.md GEMINI.md README.md PROJECT_NAVIGATION.md PROJECT_INVENTORY.md`

Expected: 新 Roadmap Hub、6M Roadmap 與 legacy archive 均有正確入口。

---

### Task 6: Legacy Roadmap Carryover Closure

**Files:**
- Create: `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`

- [ ] **Step 1: Inventory every unresolved legacy item**

逐項涵蓋舊 Roadmap 未勾選項目與 current section 中明確記錄的後續工作。

- [ ] **Step 2: Give every item one disposition**

每個項目必須標示為「已完成」、「移交至 Month X」、「被新架構取代」或「正式取消」，不得只寫「後續處理」。

- [ ] **Step 3: Add carryover gate**

在 6M Roadmap 中明定 Month 3 開始前，所有 Legacy Carryover 必須完成或有正式決策記錄。

### Task 7: Repair Stale Active Documentation

**Files:**
- Modify: `docs/07_guides/QUICK_START.md`
- Modify: `docs/07_guides/INSTALL_GUIDE.md`
- Modify: `docs/07_guides/QUICK_REFERENCE.md`
- Modify: `docs/03_data/HOW_TO_UPDATE_DAILY_DATA.md`
- Modify: `docs/03_data/DATA_FETCHING_LOGIC.md`
- Modify: `docs/01_architecture/system_flow_end_to_end.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `PROJECT_NAVIGATION.md`
- Modify: `ui_qt/README.md`
- Modify: `app_module/README.md`
- Modify: other active Markdown files still presenting `ui_app/main.py` as the primary entry

- [ ] **Step 1: Replace stale primary UI entry**

Current user instructions must use `.\.venv\Scripts\python.exe ui_qt\main.py` or `python ui_qt/main.py`.

- [ ] **Step 2: Remove obsolete Tkinter troubleshooting**

Replace Tkinter-specific guidance with PySide6 and QtWebEngine troubleshooting.

- [ ] **Step 3: Correct stale phase and service status**

Update completed Phase 3/4 capabilities, current service boundaries, and the remaining Phase 5 backlog.

### Task 8: Complete Application Manual

**Files:**
- Create: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/02_features/USER_GUIDE.md`
- Modify: `docs/07_guides/README.md`
- Modify: `docs/02_features/README.md`

- [ ] **Step 1: Document installation and launch**

Include virtual environment, data root, launch command, first-run checks, and current limitations.

- [ ] **Step 2: Document all seven top-level workspaces**

Cover Update, Market Watch, Recommendation, Research Lab, Watchlist, Portfolio, and Runtime Observatory.

- [ ] **Step 3: Document cross-workspace workflows**

Cover Update to Market Watch, Recommendation to Candidate Pool, Candidate Pool to Research Lab, and Recommendation/Backtest to Portfolio.

- [ ] **Step 4: Document safety and interpretation**

Cover quick vs safe update, SQLite Inspector read-only constraints, observed/estimated/unavailable data quality, fixed/quantile limitations, Promote gates, and destructive operations.

### Task 9: Documentation Coverage Synchronization

**Files:**
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/00_core/DOC_COVERAGE_MAP.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/agents/documentation_agent.md`

- [ ] **Step 1: Register the manual and carryover matrix**

Add both documents to the core index and relevant navigation pages.

- [ ] **Step 2: Make manual coverage a Definition of Done**

Require launch steps, operation steps, parameter meaning, result interpretation, safety notes, and troubleshooting for every user-facing workspace.

- [ ] **Step 3: Record documentation closure**

Update Snapshot and Roadmap Hub to distinguish documentation completion from still-unimplemented product backlog.

### Task 10: Final Verification And Publication

- [ ] **Step 1: Scan active docs for stale entry points and statuses**

Run `rg` across active Markdown while excluding archive and historical Superpowers plans/specs.

- [ ] **Step 2: Validate Markdown links**

Run a repository-local Markdown link checker script or equivalent deterministic path check.

- [ ] **Step 3: Review git diff and exclusions**

Confirm no data, local QA output, caches, or unrelated files are staged.

- [ ] **Step 4: Commit and push**

Commit the completed documentation rebaseline and push `codex/docs-roadmap-rebaseline` to `origin`.

## Self-review

- 規格覆蓋：核心拆分、Legacy 完整移交、過期文件清理、全功能 Manual、權威重定義、架構同步、Agent 同步與驗證皆已列入任務。
- 佔位掃描：本計畫不含 TBD / TODO。
- 類型一致性：本任務為 Markdown 文件治理，不涉及程式型別。
