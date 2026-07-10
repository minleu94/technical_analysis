# V3 後續簡化佇列自動化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 6 個既有 V3.0 milestone cron 改為可在原有夜間時間盒內自動完成多個安全重構切片、測試、commit 與 push 的 V3 後續簡化佇列。

**Architecture:** 以既有 Codex app automation 作為控制平面，不新增 repo runtime service 或資料庫。planner 和 QA 只讀；兩個 sprint 依一份固定優先佇列連續拉取可完成切片，並用每片獨立 commit 讓 QA 與早晨報告有可追溯的驗收單位。

**Tech Stack:** Codex app `automation_update`、PowerShell、Git、pytest、mypy、Python `py_compile`、Markdown。

## Global Constraints

- 保留 6 個 automation id、cron 時間、ACTIVE 狀態、模型、reasoning effort、local 環境及 `dev` 工作區。
- 不建立 worktree；使用者已明確要求直接在 `dev` 執行。
- 不修改 `docs/07_guides/APPLICATION_MANUAL.md`，因其有既存未提交變更。
- 排程不得破壞公開 API、DTO、資料語意與副作用順序，也不得寫 production DB、啟用 production scheduler 或交易。
- 每個重構切片必須先有失敗的保留契約測試，再作最小實作；驗證失敗立即停止寫入。

---

### Task 1: 建立可追溯設計與排程契約

**Files:**
- Create: `docs/superpowers/specs/2026-07-09-v3-refactor-automation-design.md`
- Create: `docs/superpowers/plans/2026-07-09-v3-refactor-automation-plan.md`

**Interfaces:**
- Consumes: 現有 6 個 cron 的 id、時間與 V3.0 closeout prompt。
- Produces: 固定的 10 節點優先佇列、時段責任、安全邊界與讀回成功準則。

- [ ] **Step 1: 建立設計文件**

文件必須列出 10 個目標節點、6 個 cron id、00:00 至 08:00 的時間盒、protected-contract 清單與「不限一晚一個切片」規則。

- [ ] **Step 2: 建立執行計畫**

計畫必須列出本次 cron 更新的 RED/GREEN 驗證、讀回與 Git 文件提交步驟。

- [ ] **Step 3: 檢查文件差異**

Run: `git diff --check -- docs/superpowers/specs/2026-07-09-v3-refactor-automation-design.md docs/superpowers/plans/2026-07-09-v3-refactor-automation-plan.md`

Expected: exit code 0.

### Task 2: 先建立排程新契約的紅燈驗證

**Files:**
- Modify: 6 個 Codex app automation 的外部設定（尚未寫入）

**Interfaces:**
- Consumes: `automation_update(mode="view", id=...)` 與 Task 1 成功準則。
- Produces: 在更新前失敗、更新後成功的設定驗證。

- [ ] **Step 1: 執行 RED 驗證**

對六個 prompt 驗證下列字串都存在：`V3_POST_CLOSEOUT_SIMPLIFICATION_QUEUE`、`多個完整切片`、`每片`、`commit`、`push`、`失敗`、`TWStockConfig`。現況 V3.0 closeout prompt 缺少這些內容，預期 assertion failure。

- [ ] **Step 2: 確認失敗原因**

預期只因新簡化佇列契約尚未更新而失敗；若 automation 無法讀取或 id 不存在，停止並回報 blocker。

### Task 3: 更新 6 個 cron prompt

**Files:**
- Modify external automation: `baldr-milestone-planner-0000`
- Modify external automation: `baldr-milestone-implementation-sprint-0020`
- Modify external automation: `baldr-milestone-qa-checkpoint-0330`
- Modify external automation: `baldr-milestone-morning-finish-planner-0540`
- Modify external automation: `baldr-milestone-finish-sprint-0600`
- Modify external automation: `baldr-milestone-final-closeout-0800`

**Interfaces:**
- Consumes: Task 1 design and Task 2 red state.
- Produces: 六個具不同時段責任、共同 queue / guard / report contract 的 ACTIVE cron。

- [ ] **Step 1: 更新 planner 兩個 prompt**

00:00 planner 只讀取前一輪狀態，於 00:15 前寫出多切片 queue；05:40 planner 只依 QA 結果規劃 06:00 sprint，兩者皆不得改 code。

- [ ] **Step 2: 更新 implementation 與 finish sprint prompt**

兩個 sprint 都可連續完成任意數量的完整切片，直到時間盒結束或出現 blocker；每片依 RED → 最小實作 → focused regression → 必要 UI/mypy gate → `git diff --check` → atomic commit/push 順序執行。

- [ ] **Step 3: 更新 QA 與 closeout prompt**

QA 在 03:30 讀取並驗證已推送 commit，失敗時寫 `BLOCKED` 並禁止 06:00 寫入；08:00 closeout 僅彙整早晨驗收報告，不改 code、commit 或 push。

- [ ] **Step 4: 保留外部設定欄位**

每個 update 以原值保留 cron 時間、ACTIVE、模型、reasoning effort、execution environment、project id 與 cwd；只改名稱及 prompt。

### Task 4: 讀回驗證與範圍檢查

**Files:**
- Inspect external automation: 6 個已更新 cron
- Inspect external automation: `baldr-scheduled-evidence-morning-report`

**Interfaces:**
- Consumes: Task 3 更新後設定。
- Produces: 6 個成功讀回、evidence report 未改、所有 guard 完整的驗證結果。

- [ ] **Step 1: 執行 GREEN 設定驗證**

重跑 Task 2 assertion，預期六個 cron 都通過。

- [ ] **Step 2: 驗證時段與啟用狀態**

讀回每個 cron，確認 rrule、ACTIVE、model、reasoning effort、environment、project target 和 cwd 與更新前相同。

- [ ] **Step 3: 驗證分工與隔離**

確認 planner / QA / closeout 都含「不改 code」；兩個 sprint 都含「多個完整切片」與逐片 commit/push；六個 cron 都將 `graphify-out/memory/**` 視為不可 stage 的已知工具輸出，而其餘未知變更仍 fail-closed；evidence morning report 的設定檔 hash 在前後相同。

### Task 5: 文件驗證與交付

**Files:**
- Modify: Task 1 兩份 Markdown（只在 self-review 修正時）

**Interfaces:**
- Consumes: Task 4 驗證結果。
- Produces: 可提交的規格與計畫文件，以及早晨驗收能依循的 automation 狀態摘要。

- [ ] **Step 1: 計畫 self-review**

確認每個成功準則都有對應 Task，並執行下列 placeholder scan，預期零命中：

```powershell
$patterns = @('TO' + 'DO', 'TB' + 'D', 'implement' + ' later', 'Similar' + ' to Task')
$hits = Select-String -Path docs/superpowers/plans/2026-07-09-v3-refactor-automation-plan.md -Pattern $patterns
if ($hits) { throw $hits }
```

- [ ] **Step 2: Git 驗證**

Run: `git diff --check` and `git status --short`.

Expected: 無 whitespace error；只 stage 本次兩份新增 Markdown，不包含既存 `docs/07_guides/APPLICATION_MANUAL.md` 或 `graphify-out/`。

- [ ] **Step 3: 提交文件**

Run: `git add docs/superpowers/specs/2026-07-09-v3-refactor-automation-design.md docs/superpowers/plans/2026-07-09-v3-refactor-automation-plan.md && git commit -m "docs: schedule v3 simplification automation"`

Expected: 只有本次規格與計畫進入 commit；外部 automation 設定不在 repository stage 範圍。
