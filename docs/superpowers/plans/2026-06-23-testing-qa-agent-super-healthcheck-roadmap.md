# Testing QA Agent Super Healthcheck Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「非破壞式超級 UI / release healthcheck 腳本」與「Testing / QA Agent 調度員」整合成一個可詢問、可路由、可執行、可解讀、可交接的 QA 小員工。

**Architecture:** Full App Healthcheck Runner 是執行器，負責跑 quick / full / high-risk-dry-run 測試、橋接既有 pytest、輸出 JSON / Markdown 證據；Testing / QA Agent 是調度與解讀層，負責把使用者的功能問題映射到 feature route、決定模式、讀取結果、判斷 owner 與交接對象。Data Audit Agent 只在資料完整性、SQLite / CSV 一致性、available_date 或 schema 問題被判定需要時條件式介入；Execution Agent 負責修 bug，不負責測試路由決策。

**Tech Stack:** Python 3.12, PySide6, pytest, `qa/full_app_healthcheck/*`, `scripts/run_full_app_healthcheck.py`, Markdown / JSON report, existing `tests/test_ui_qt_*`, `docs/agents/testing_qa_agent.md`, `docs/06_qa/*HEALTHCHECK*`.

---

## 1. 這份文件解決什麼問題

本路線原本分散在多個文件與對話上下文中。已存在的文件如下：

- `docs/superpowers/plans/2026-06-23-non-destructive-release-healthcheck-runner.md`：超級 healthcheck runner 的原始實作計畫。
- `docs/agents/testing_qa_agent.md`：Testing / QA Agent 的角色權威文件。
- `docs/06_qa/FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md`：功能到測試的路由矩陣。
- `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`：`tests/` 全量測試分類與橋接規則。
- `qa/full_app_healthcheck/feature_router.py`：功能查詢與模糊路由。
- `qa/full_app_healthcheck/result_interpreter.py`：healthcheck 結果解讀與 Markdown 輸出。

缺少的是一份「總控 Roadmap」：說清楚最終目標、目前完成度、下一階段如何接續，以及新對話應讀哪些文件。本文件就是這個接力棒。

## 2. 最終產品定義

最終目標不是單一 pytest 檔，也不是只會跑一次的腳本，而是一個 QA Agent 工作流：

1. 使用者問：「幫我驗證某功能」或「這次改動要跑哪些測試」。
2. Testing / QA Agent 查 `feature_router.py` 與 `FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md`。
3. Agent 決定要跑 quick、full、high-risk-dry-run，或只回報 manual gap。
4. Runner 執行非破壞測試與既有 suite bridge。
5. Result interpreter 把 runner output 轉成功能層級結論。
6. Agent 產出繁體中文測試報告：
   - 哪些功能通過。
   - 哪些功能沒跑，原因是 quick 不支援、manual-only、blocked 或 not-yet-automated。
   - 哪些失敗偏向資料問題，需交 Data Audit。
   - 哪些失敗偏向 UI / 程式錯誤，需交 Execution。
   - 哪些問題是架構或產品流程不合理，需交 Tech Lead。
7. 未來 release 前可跑完整巡檢；日常變更可跑 quick 或 feature-scoped 檢查。

## 3. 非目標與安全邊界

- 不在目前階段啟動 D-2 MainWindow 真實 UI 導覽，除非該階段被明確啟動。
- 不執行正式資料更新、migration、backfill apply、資料刪除、清空或強制重建。
- 不把 runner 自動測試通過等同人工 healthcheck `通過`。
- 不讓 Testing / QA Agent 修 code；修 code 是 Execution Agent 工作。
- 不讓 Testing / QA Agent 深挖資料完整性；資料完整性是 Data Audit Agent 工作。
- 不把 manual-only 或 write-risk 測試硬塞進 quick / full bridge。

## 4. 目前完成度

### 4.1 Runner / Super Script 基礎

已完成：

- Manifest / safety gate。
- Reporting JSON / Markdown 基礎輸出。
- Runner core。
- CLI：`scripts/run_full_app_healthcheck.py`。
- Existing test suite bridge。
- Coverage matrix 與 Batch 1-6 closeout baseline。
- Test inventory 分類與 legacy diagnostics relocation。
- Quick mode 可跑 direct bridge 中安全的 UI 測試。

最新驗收基準：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
```

預期：`Healthcheck passed`。

### 4.2 Testing / QA Agent 文件與入口

已完成：

- `docs/agents/testing_qa_agent.md` 成為 Testing / QA Agent 權威文件。
- `docs/agents/README.md`、`docs/agents/skills_registry.md`、`docs/agents/skills/team.md`、`AGENTS.md`、`GEMINI.md`、`.agent/rules/10_development_execution.md` 已納入 Testing / QA Agent 分流。
- `docs/06_qa/` 只保留測試矩陣、分類、healthcheck 證據，不保存 Agent 角色定義。

### 4.3 Feature Router / 測試路由

已完成：

- `qa/full_app_healthcheck/feature_router.py` 支援精確 / 模糊 feature query。
- 六大高頻 UI 工作區已建立 feature route：
  - UpdateView。
  - Daily Decision Desk。
  - Research Lab。
  - Market Regime。
  - Smart Money Flow。
  - Run Registry Compare。
- route 內含 direct bridge suites、service oracle、manual gaps、quick support、data audit policy。

### 4.4 Result Interpreter / 結果解讀

已完成：

- `interpret_healthcheck_result(result)`：把 runner step / suite output 轉成功能層級判讀。
- `interpret_healthcheck_json(path)`：讀取 `result.json` 後解讀。
- `render_interpretation_markdown(interpretation)`：產出繁體中文 Markdown 報告。
- 錯誤 owner 初判：
  - data / SQLite / schema / available_date 類錯誤：`data_audit`。
  - widget / tab / layout / visible / assertion 類錯誤：`execution`。
  - quick mode full-only 未跑：`testing_qa`，不視為錯誤。
  - 未註冊 suite：runner / routing failure，整體為 failed。

最新驗收基準：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_result_interpreter.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=
```

預期：`22 passed`。

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
```

目前：`966 tests collected`（A-3.3 / A-3.4 / A-4 / B-2 後）。

## 5. 下一階段路線總覽

### Track A：QA Agent 解讀能力

目的：讓 Agent 不只會說 pass / fail，而是能做測試助理該做的判讀。

- A-3.1：Healthcheck result interpretation API。已完成。
- A-3.2：Interpretation Markdown renderer。已完成。
- A-3.3：Known issue matcher。已完成。
- A-3.4：Handoff recommendation contract，將 `likely_owner`、evidence、recommended_next_steps 統一成可貼給 Data Audit / Execution / Tech Lead 的格式。已完成。
- A-4：Feature-scoped QA command advisor，輸入功能名後輸出應跑命令、模式、風險與預期報告。已完成。

### Track B：Runner 覆蓋率與既有測試橋接

目的：避免重複寫測試，把現有零碎測試變成 runner 可調度資源。

- B-1：Direct bridge 穩定化。已完成。
- B-2：Candidate bridge promote policy，逐一把 `ui-healthcheck-candidate-bridge` 升級為 full mode 或保留 manual gap。已完成。
- B-3：Service oracle metadata，讓 service-oracle 測試可作功能證據，但不直接當 UI flow step。已完成。
- B-4：Coverage burn-down report，讓 manual-only、blocked、not-yet-automated 不被隱藏。已完成。

### Track C：流程閉環診斷

目的：回答「流程是否合理」，而不是只回答「測試有沒有 crash」。

- C-1：四大閉環 flow model。已完成。
  - 資料與市場狀態閉環。

  - 研究驗證閉環。
  - 持倉檢查閉環。
  - 每日決策閉環。
- C-2：Flow diagnostics renderer，列出入口、步驟、證據、下一步導向、manual gap。
- C-3：Known UX gap mapping，把人工 healthcheck 中的「看不懂、找不到、被遮住、下一步不明」轉成可追蹤項目。

### Track D：近似使用者行為的 UI 驗收

目的：逐步接近使用者真的打開 app 操作的樣子。

- D-1：Offscreen widget-level UI checks，僅測 widget 可見、文案、layout、QTest 安全點擊。
- D-2：MainWindow non-destructive smoke，首次允許受控啟動完整主視窗，但仍禁止資料寫入。
- D-3：Viewport / resize evidence，輸出 1366x768、1440x900、1920x1080 等截圖與 layout bounds。
- D-4：High-risk dry-run dialogs，只測 confirmation dialog、取消流程、mock service 未被呼叫。
- D-5：Visible / interactive mode，日後需要人工旁看時再開，不作第一批必要項。

### Track E：Release Gate 與版本比較

目的：讓未來版本升級真的更有效，而不是每次重測都從零開始。

- E-1：Run history manifest，保存 run_id、commit、mode、viewport、suite results、feature results、manual gaps。
- E-2：Compare two healthcheck runs，輸出新增覆蓋、修復、退步、仍未覆蓋。
- E-3：Quick mode release gate proposal，等 quick 穩定後再決定是否變成正式 gate。
- E-4：Full mode release checklist，release 前人工與機器共同使用。

## 6. 推薦下一個實作批次

下一個批次建議做 C-2 flow diagnostics renderer，不要直接進 D-2。

理由：

- A-3.1 / A-3.2 已讓結果能解讀與輸出 Markdown。
- A-3.3 已建立 known issue matcher，可將錯誤對上已知 manual gap / blocked / likely owner。
- A-3.4 已建立 handoff recommendation contract，可把 `likely_owner`、evidence、recommended_next_steps 統一成可交接格式。
- A-4 已可把功能名稱轉成應跑命令、模式、風險與預期報告，讓 QA Agent 更容易安全執行。
- B-2 已建立 candidate bridge promote policy，避免直接把候選 UI 測試放進 runner。
- B-3 已整理 service oracle metadata，讓 service-oracle 測試可作功能證據，但不直接當 UI flow step。
- B-4 已輸出 coverage burn-down report，讓 `manual-only`、`blocked`、`not-yet-automated` 與 known gaps 不被隱藏。
- C-1 已建立四大 closed-loop flow model，把入口、步驟、證據、下一步導向與 manual gap 變成資料模型。
- 下一步 C-2 應把 flow model 轉成診斷報告，列出每條閉環的目前覆蓋、缺口、可執行命令建議與交接方向。
- D-2 會啟動 MainWindow，風險與 token 成本較高，應等 C-1 / C-2 flow diagnostics 更完整再進。

### Task C-2：Flow Diagnostics Renderer

**Files:**

- Create: `qa/full_app_healthcheck/flow_diagnostics.py`
- Test: `tests/test_full_app_healthcheck_flow_diagnostics.py`
- Modify: `qa/full_app_healthcheck/test_inventory.py`
- Modify: `tests/test_full_app_healthcheck_test_inventory.py`
- Modify: `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`
- Modify: `docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md`

- [ ] **Step 1: Inspect existing flow model and QA advisors**

Run:

```powershell
Get-Content -Raw -Encoding UTF8 qa\full_app_healthcheck\flow_model.py
Get-Content -Raw -Encoding UTF8 qa\full_app_healthcheck\feature_router.py
Get-Content -Raw -Encoding UTF8 qa\full_app_healthcheck\coverage_burndown.py
Get-Content -Raw -Encoding UTF8 qa\full_app_healthcheck\command_advisor.py
Get-Content -Raw -Encoding UTF8 qa\full_app_healthcheck\handoff_contract.py
```

Expected: understand how flows map to feature routes, evidence, command recommendations, and handoff fields.

- [ ] **Step 2: Write diagnostics tests before implementation**

Create `tests/test_full_app_healthcheck_flow_diagnostics.py` with cases for:

- Diagnostics are generated for all four C-1 flows.
- Each diagnostic includes flow id, entrypoint, ordered feature ids, evidence sources, manual gaps, command recommendation, and likely handoff owner.
- Quick-ineligible features are reported as `full_or_manual_required`, not as failed.
- Service oracle evidence remains evidence-only and is never rendered as an executable UI step.
- Markdown output names manual gaps, recommended command scope, and next-step handoff destinations.

- [ ] **Step 3: Implement `flow_diagnostics.py`**

Suggested public API:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowDiagnostic:
    flow_id: str
    display_name: str
    entrypoint: str
    ordered_feature_ids: tuple[str, ...]
    coverage_status: str
    evidence_sources: tuple[str, ...]
    manual_gaps: tuple[str, ...]
    recommended_commands: tuple[str, ...]
    likely_owner: str
    next_steps: tuple[str, ...]


@dataclass(frozen=True)
class FlowDiagnosticsReport:
    diagnostics: tuple[FlowDiagnostic, ...]
    summary: str
```

- [ ] **Step 4: Add Markdown renderer**

Add `render_flow_diagnostics_markdown(report)` that lists:

- flow id and display name
- entrypoint
- ordered feature ids
- evidence sources
- manual / UX gaps
- recommended command scope
- likely owner / handoff destination
- next steps

- [ ] **Step 5: Update inventory and docs count**

After adding the new test file, run collect-only and update counts:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
```

Update:

- `qa/full_app_healthcheck/test_inventory.py`
- `tests/test_full_app_healthcheck_test_inventory.py`
- `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`

- [ ] **Step 6: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_flow_diagnostics.py tests/test_full_app_healthcheck_flow_model.py tests/test_full_app_healthcheck_coverage_burndown.py tests/test_full_app_healthcheck_service_oracle_metadata.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
git diff --check
```

Expected:

- Focused tests pass.
- Collect-only count is updated in inventory docs.
- Quick runner passes.
- `git diff --check` has no whitespace errors.

## 7. 新對話接手 Prompt

複製以下 prompt 到新 Codex 或 Gemini 對話：

```markdown
你要接手 technical_analysis 專案的 Testing / QA Agent + Full App Healthcheck Runner 路線，請先不要進 D-2 / MainWindow。

工作目標：
延續 `docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md`，先檢查目前 A-3.1 / A-3.2 / A-3.3 / A-3.4 / A-4 / B-2 / B-3 / B-4 / C-1 是否已完成並驗證，然後只做下一個安全批次 C-2 flow diagnostics renderer。不要啟動真實 MainWindow，不要跑資料寫入，不要 migration，不要進 high-risk dry-run 實作。

必讀文件：
1. `AGENTS.md`
2. `docs/agents/README.md`
3. `docs/agents/shared_context.md`
4. `docs/agents/git_exclusions.md`
5. `docs/00_core/PROJECT_SNAPSHOT.md`
6. `docs/00_core/DEVELOPMENT_ROADMAP.md`
7. `docs/00_core/ROADMAP_6M_ENGINEERING.md`
8. `docs/agents/skills_registry.md`
9. `docs/agents/testing_qa_agent.md`
10. `docs/06_qa/FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md`
11. `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`
12. `docs/superpowers/plans/2026-06-23-non-destructive-release-healthcheck-runner.md`
13. `docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md`

目前設計原則：
- Full App Healthcheck Runner 是超級測試腳本執行器。
- Testing / QA Agent 是測試調度與結果解讀員。
- 既有 runner plan 沒丟掉；QA Agent 只是決定跑 quick/full/partial/closed-loop，並解讀結果。
- Data Audit Agent 只在資料完整性、SQLite/CSV、available_date、schema 等條件成立時被交接。
- Execution Agent 才修 code；Testing / QA Agent 不修 bug。
- 第一階段保持完全非破壞模式。

請先做：
1. `git status --short`，不要覆寫其他 agent 或使用者未提交變更。
2. 檢查 `qa/full_app_healthcheck/result_interpreter.py`、`qa/full_app_healthcheck/known_issue_matcher.py`、`qa/full_app_healthcheck/handoff_contract.py`、`qa/full_app_healthcheck/command_advisor.py`、`qa/full_app_healthcheck/candidate_bridge_policy.py`、`qa/full_app_healthcheck/service_oracle_metadata.py`、`qa/full_app_healthcheck/coverage_burndown.py`、`qa/full_app_healthcheck/flow_model.py`、`tests/test_full_app_healthcheck_result_interpreter.py`、`tests/test_full_app_healthcheck_known_issue_matcher.py`、`tests/test_full_app_healthcheck_handoff_contract.py`、`tests/test_full_app_healthcheck_command_advisor.py`、`tests/test_full_app_healthcheck_candidate_bridge_policy.py`、`tests/test_full_app_healthcheck_service_oracle_metadata.py`、`tests/test_full_app_healthcheck_coverage_burndown.py`、`tests/test_full_app_healthcheck_flow_model.py`、`qa/full_app_healthcheck/feature_router.py`。
3. 跑：
   `.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_flow_model.py tests/test_full_app_healthcheck_coverage_burndown.py tests/test_full_app_healthcheck_service_oracle_metadata.py tests/test_full_app_healthcheck_candidate_bridge_policy.py tests/test_full_app_healthcheck_command_advisor.py tests/test_full_app_healthcheck_handoff_contract.py tests/test_full_app_healthcheck_known_issue_matcher.py tests/test_full_app_healthcheck_result_interpreter.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=`
4. 跑：
   `.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast`
5. 若都通過，開始 C-2：以 TDD 設計 flow diagnostics renderer，將 C-1 四大 flow 轉成可讀診斷報告，列出 coverage status、manual gaps、evidence、recommended commands 與 handoff owner，不啟動 MainWindow。
6. 新增測試後同步 `test_inventory.py`、`tests/test_full_app_healthcheck_test_inventory.py`、`docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md` 的測試數量。
7. 完成後只回報檢查與修正結果，不要直接進 D-2。

驗收命令：
`.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_flow_diagnostics.py tests/test_full_app_healthcheck_flow_model.py tests/test_full_app_healthcheck_coverage_burndown.py tests/test_full_app_healthcheck_service_oracle_metadata.py tests/test_full_app_healthcheck_candidate_bridge_policy.py tests/test_full_app_healthcheck_command_advisor.py tests/test_full_app_healthcheck_handoff_contract.py tests/test_full_app_healthcheck_known_issue_matcher.py tests/test_full_app_healthcheck_result_interpreter.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=`
`.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=`
`.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast`
`git diff --check`
```

## 8. 完成前自查清單

- [ ] 沒有把 quick mode 未跑的 full-only 功能誤判為失敗。
- [ ] 沒有把 manual gap 誤判為通過。
- [ ] 沒有把 runner 自身測試橋接到 runner 中。
- [ ] 沒有把 write-risk / manual-only 測試放入 quick 或 full bridge。
- [ ] 新增測試檔後，test inventory 與文件測試數同步。
- [ ] quick runner 仍通過。
- [ ] 若要進 D-2，必須先由使用者明確確認。
