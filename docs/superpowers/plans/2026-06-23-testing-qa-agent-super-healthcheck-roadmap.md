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

- 不在目前階段啟動 D-4 high-risk dry-run dialog 真實 UI 驗證，除非該階段被明確啟動。
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
- [x] C-2：Flow diagnostics renderer，列出入口、步驟、證據、下一步導向、manual gap。
- [x] C-3：Known UX gap mapping，把人工 healthcheck 中的「看不懂、找不到、被遮住、下一步不明」轉成可追蹤項目。

### Track D：近似使用者行為的 UI 驗收

目的：逐步接近使用者真的打開 app 操作的樣子。

- [x] D-1：Offscreen widget-level UI checks，僅測 widget 可見、文案、layout、QTest 安全點擊。
- [x] D-2：MainWindow non-destructive smoke，首次允許受控啟動完整主視窗，但仍禁止資料寫入。
- [x] D-3：Viewport / resize evidence，輸出 1366x768、1440x900、1920x1080 等截圖與 layout bounds。
- [x] D-4：High-risk dry-run dialogs，只測 confirmation dialog、取消流程、mock service 未被呼叫。
- D-5：Visible / interactive mode，日後需要人工旁看時再開，不作第一批必要項。

### Track E：Release Gate 與版本比較

目的：讓未來版本升級真的更有效，而不是每次重測都從零開始。

- [x] E-1：Run history manifest，保存 run_id、commit、mode、viewport、suite results、feature results、manual gaps。
- [x] E-2：Compare two healthcheck runs，輸出新增覆蓋、修復、退步、仍未覆蓋。
- [x] E-3：Quick mode release gate proposal，等 quick 穩定後再決定是否變成正式 gate。
- [x] E-4：Full mode release checklist，release 前人工與機器共同使用。

## 6. 推薦下一個實作批次

Track E 已完成到 E-4。下一個批次尚未定義；必須先由使用者明確確認新的方向、範圍與安全邊界後才可進入。

理由：

- A-3.1 / A-3.2 已讓結果能解讀與輸出 Markdown。
- A-3.3 已建立 known issue matcher，可將錯誤對上已知 manual gap / blocked / likely owner。
- A-3.4 已建立 handoff recommendation contract，可把 `likely_owner`、evidence、recommended_next_steps 統一成可交接格式。
- A-4 已可把功能名稱轉成應跑命令、模式、風險與預期報告，讓 QA Agent 更容易安全執行。
- B-2 已建立 candidate bridge promote policy，避免直接把候選 UI 測試放進 runner。
- B-3 已整理 service oracle metadata，讓 service-oracle 測試可作功能證據，但不直接當 UI flow step。
- B-4 已輸出 coverage burn-down report，讓 `manual-only`、`blocked`、`not-yet-automated` 與 known gaps 不被隱藏。
- C-1 已建立四大 closed-loop flow model，把入口、步驟、證據、下一步導向與 manual gap 變成資料模型。
- C-2 已把 flow model 轉成診斷報告，列出每條閉環的目前覆蓋、缺口、可執行命令建議與交接方向。
- C-3 已把人工 healthcheck 中的「看不懂、找不到、被遮住、下一步不明」轉成可追蹤 UX gap metadata，並讓 C-2 diagnostics 可以引用。
- D-1 已建立 offscreen widget-level UI checks，只描述 widget 可見、文案、layout 與安全 QTest 動作，不啟動完整 MainWindow。
- D-2 已建立 MainWindow non-destructive smoke plan metadata，仍不在 unit tests 或 quick/full runner 中啟動 MainWindow。
- D-3 已建立 Viewport / resize evidence plan metadata，仍不在 unit tests 或 quick/full runner 中啟動 MainWindow、截圖或 resize widget。
- D-4 已建立 High-risk dry-run dialog plan metadata，仍不在 unit tests 或 quick/full runner 中啟動 MainWindow、執行 dialog、或呼叫真實 service。
- E-1 已建立 Run history manifest 記憶體內元資料與 Markdown 渲染器，不寫檔，不影響執行器。
- E-2 已建立 Compare two healthcheck runs 的純記憶體比對器與 Markdown 渲染器，可輸出新舊測試執行差異。
- E-3 已建立 Quick mode release gate proposal metadata，明確標示 proposal-only、不啟用 CI gate、不修改 runner bridge。
- E-4 已建立 Full mode release checklist metadata，明確標示 checklist-only、不啟用 release gate、不修改 runner bridge。
- 下一步尚未定義；應由使用者決定是否進入新的 roadmap batch，或停在目前可回滾的 release healthcheck metadata 邊界。

### Task E-2：Compare Two Healthcheck Runs

**Files:**

- Create: `qa/full_app_healthcheck/run_history_compare.py`
- Test: `tests/test_full_app_healthcheck_run_history_compare.py`
- Modify: `qa/full_app_healthcheck/test_inventory.py`
- Modify: `tests/test_full_app_healthcheck_test_inventory.py`
- Modify: `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`
- Modify: `docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md`

- [x] **Step 0: Confirm authorization**

Do not begin E-2 unless the user explicitly confirms that starting run history comparison planning is allowed.

- [x] **Step 1: Inspect E-1 manifest schema**

Run:

```powershell
Get-Content -Raw -Encoding UTF8 qa\full_app_healthcheck\run_history_manifest.py
Get-Content -Raw -Encoding UTF8 tests\test_full_app_healthcheck_run_history_manifest.py
```

Expected: understand the in-memory manifest schema before comparing two runs. Keep E-2 pure unless a later executor explicitly writes comparison output.

- [x] **Step 2: Write run history comparison tests before implementation**

Create `tests/test_full_app_healthcheck_run_history_compare.py` with cases for:

- Compare result dataclass can report added suite coverage, removed suite coverage, fixed suites, regressed suites, unchanged failing suites, new manual gaps, resolved manual gaps, and feature status changes.
- Comparison is pure in memory and does not write files.
- Inputs are two `RunHistoryManifest` instances.
- Markdown rendering summarizes baseline run, candidate run, fixes, regressions, coverage changes, and manual gap changes.

- [x] **Step 3: Implement `run_history_compare.py`**

Suggested public API:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunHistoryComparison:
    baseline_run_id: str
    candidate_run_id: str
    added_suite_ids: tuple[str, ...]
    removed_suite_ids: tuple[str, ...]
    fixed_suite_ids: tuple[str, ...]
    regressed_suite_ids: tuple[str, ...]
    unchanged_failing_suite_ids: tuple[str, ...]
    new_manual_gaps: tuple[str, ...]
    resolved_manual_gaps: tuple[str, ...]
    feature_status_changes: tuple[FeatureStatusChange, ...]
```

Required helpers:

- `compare_run_history_manifests(baseline: RunHistoryManifest, candidate: RunHistoryManifest) -> RunHistoryComparison`
- `render_run_history_comparison_markdown(comparison: RunHistoryComparison) -> str`

- [x] **Step 4: Keep E-2 pure unless explicitly approved**

Do not write output files, mutate run output directories, start MainWindow, execute dialogs, or add E-2 to quick/full runner bridge automatically.

- [x] **Step 5: Update inventory and docs count**

After adding the new test file, run collect-only and update counts:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
```

Update:

- `qa/full_app_healthcheck/test_inventory.py`
- `tests/test_full_app_healthcheck_test_inventory.py`
- `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`

- [x] **Step 6: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_run_history_compare.py tests/test_full_app_healthcheck_run_history_manifest.py tests/test_full_app_healthcheck_high_risk_dry_run_dialog_plan.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
git diff --check
```

Expected:

- Focused tests pass.
- Collect-only count is updated in inventory docs.
- Quick runner passes.
- `git diff --check` has no whitespace errors.

### Task E-3：Quick Mode Release Gate Proposal

**Files:**

- Create: `qa/full_app_healthcheck/quick_mode_release_gate_proposal.py`
- Test: `tests/test_full_app_healthcheck_quick_mode_release_gate_proposal.py`
- Modify: `qa/full_app_healthcheck/test_inventory.py`
- Modify: `tests/test_full_app_healthcheck_test_inventory.py`
- Modify: `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`
- Modify: `docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md`

- [x] **Step 0: Confirm authorization**

Do not begin E-3 unless the user explicitly confirms that starting quick mode release gate proposal planning is allowed.

- [x] **Step 1: Keep E-3 proposal-only**

E-3 must not activate CI / release gate behavior, mutate runner bridge behavior, write output files, start UI, execute dialogs, call services, or perform data writes.

- [x] **Step 2: Define proposal metadata**

Create a frozen metadata model that records:

- Proposal id and status.
- Candidate mode (`quick`).
- Proposal-only guardrails.
- Required criteria.
- Blocker notes.
- Manual confirmation points.
- Rollback notes.
- Next review step.

- [x] **Step 3: Render Markdown**

Add a Markdown renderer that makes the proposal status, required evidence, manual confirmations, blockers, rollback notes, and next review step readable for a future release review.

- [x] **Step 4: Test defensive boundaries**

Tests must verify proposal-only flags, no gate activation, no bridge mutation, required criteria coverage, readable Markdown, inventory registration, and no write / UI execution side effects.

- [x] **Step 5: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_quick_mode_release_gate_proposal.py tests/test_full_app_healthcheck_run_history_compare.py tests/test_full_app_healthcheck_run_history_manifest.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
git diff --check
```

### Task E-4：Full Mode Release Checklist

**Files:**

- Create: `qa/full_app_healthcheck/full_mode_release_checklist.py`
- Test: `tests/test_full_app_healthcheck_full_mode_release_checklist.py`
- Modify: `qa/full_app_healthcheck/test_inventory.py`
- Modify: `tests/test_full_app_healthcheck_test_inventory.py`
- Modify: `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`
- Modify: `docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md`

- [x] **Step 0: Confirm authorization**

Do not begin E-4 unless the user explicitly confirms that starting full mode release checklist planning is allowed.

- [x] **Step 1: Write failing tests first**

Create `tests/test_full_app_healthcheck_full_mode_release_checklist.py` before implementation. The first run must fail because `qa.full_app_healthcheck.full_mode_release_checklist` does not exist yet.

- [x] **Step 2: Keep E-4 checklist-only**

E-4 must not activate release gate behavior, mutate runner bridge behavior, write output files, start UI, execute dialogs, call services, or perform data writes.

- [x] **Step 3: Define checklist metadata**

Create a frozen metadata model that records:

- Checklist id and status.
- Candidate mode (`full`).
- Checklist-only guardrails.
- Full mode checklist items.
- Machine evidence requirements.
- Manual-only gaps.
- Handoff targets.
- Next review step.

- [x] **Step 4: Render Markdown**

Add a Markdown renderer that makes checklist items, required evidence, manual-only gaps, machine evidence requirements, handoff targets, and next review step readable for a future release review.

- [x] **Step 5: Test defensive boundaries**

Tests must verify checklist-only flags, no release gate activation, no bridge mutation, checklist item coverage, readable Markdown, inventory registration, and no write / UI execution side effects.

- [x] **Step 6: Verify**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_full_mode_release_checklist.py tests/test_full_app_healthcheck_quick_mode_release_gate_proposal.py tests/test_full_app_healthcheck_run_history_compare.py tests/test_full_app_healthcheck_run_history_manifest.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
git diff --check
```

## 7. 新對話接手 Prompt

複製以下 prompt 到新 Codex 或 Gemini 對話：

```markdown
你要接手 technical_analysis 專案的 Testing / QA Agent + Full App Healthcheck Runner 路線。目前 Track A-E 已完成到 E-4 Full mode release checklist。下一個批次尚未定義；若使用者尚未明確指定新方向，請只做檢查與回報，不要開始新實作。

工作目標：
延續 `docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md`，先檢查目前 A-3.1 / A-3.2 / A-3.3 / A-3.4 / A-4 / B-2 / B-3 / B-4 / C-1 / C-2 / C-3 / D-1 / D-2 / D-3 / D-4 / E-1 / E-2 / E-3 / E-4 是否已完成並驗證。若使用者明確授權新的 batch，才依新範圍行動；此階段不要把 quick/full mode 升級成正式 gate、不要寫 output 檔、不要啟動 MainWindow、不要執行 dialog、不要呼叫 service、不要資料寫入、migration、backfill apply 或 high-risk dry-run 實作。

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
2. 檢查 `qa/full_app_healthcheck/run_history_manifest.py`、`qa/full_app_healthcheck/run_history_compare.py`、`qa/full_app_healthcheck/quick_mode_release_gate_proposal.py`、`qa/full_app_healthcheck/full_mode_release_checklist.py`、`tests/test_full_app_healthcheck_run_history_manifest.py`、`tests/test_full_app_healthcheck_run_history_compare.py`、`tests/test_full_app_healthcheck_quick_mode_release_gate_proposal.py`、`tests/test_full_app_healthcheck_full_mode_release_checklist.py`、`qa/full_app_healthcheck/high_risk_dry_run_dialog_plan.py`、`qa/full_app_healthcheck/feature_router.py` 與對應測試檔。
3. 跑：
   `.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_offscreen_widget_checks.py tests/test_full_app_healthcheck_ux_gap_mapping.py tests/test_full_app_healthcheck_flow_diagnostics.py tests/test_full_app_healthcheck_flow_model.py tests/test_full_app_healthcheck_coverage_burndown.py tests/test_full_app_healthcheck_service_oracle_metadata.py tests/test_full_app_healthcheck_candidate_bridge_policy.py tests/test_full_app_healthcheck_command_advisor.py tests/test_full_app_healthcheck_handoff_contract.py tests/test_full_app_healthcheck_known_issue_matcher.py tests/test_full_app_healthcheck_result_interpreter.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=`
4. 跑：
   `.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast`
5. 若都通過，回報 Track A-E 已完成到 E-4，並等待使用者指定下一個 batch；沒有新授權就停止。
6. 若使用者指定新 batch，先更新或建立對應 roadmap，再用 TDD 做最小安全批次。
7. 新增測試後同步 `test_inventory.py`、`tests/test_full_app_healthcheck_test_inventory.py`、`docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md` 的測試數量。
8. 完成後只回報檢查與修正結果；不要把任何新 metadata 自動接入 quick/full runner bridge 或 CI gate。

驗收命令：
`.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_full_mode_release_checklist.py tests/test_full_app_healthcheck_quick_mode_release_gate_proposal.py tests/test_full_app_healthcheck_run_history_compare.py tests/test_full_app_healthcheck_run_history_manifest.py tests/test_full_app_healthcheck_high_risk_dry_run_dialog_plan.py tests/test_full_app_healthcheck_flow_diagnostics.py tests/test_full_app_healthcheck_feature_router.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=`
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
- [ ] 若要進入新 batch，必須先由使用者明確確認。
