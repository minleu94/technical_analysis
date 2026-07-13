# Cross-workstream Integration／QA／Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Do not enter the write phase until every upstream handoff gate is satisfied.

**Goal:** 在 A、B、C、D、E1、E2、F 七條工作流都由 Git Coordinator 串行提交到共享 `dev` 後，驗證其 handoff、檔案 ownership、契約與測試，建立一條可重跑的跨工作流驗證鏈，完成全量 QA、中央 SSOT 文件同步與誠實 closeout。

**Architecture:** G 是唯一 cross-workstream composition 與中央文件 owner。G 不建立整合 branch、不 cherry-pick／merge；它先驗證 A～F handoff 對應的 coordinator commits 已存在於同一個 `dev` history，再依 dependency order 重跑契約與 focused tests。之後以 temp SQLite 與 bounded read-only 正式來源驗證 source → rehearsal → PIT dataset → ML shadow → Dashboard。G 不重寫各 domain 實作，domain failure 必須退回原 owner。

**Tech Stack:** Python 3.11、pytest、mypy、SQLite temp／read-only、PySide6 QA、JSON verifier、Markdown SSOT、PowerShell、Git。

## Shared `dev` Execution Protocol（本計畫所有 Task 的最高優先規則）

- 開工前以唯讀 `git rev-parse --abbrev-ref HEAD` 確認結果為 `dev`；不得建立或切換 branch／worktree。
- G worker 禁止執行 `git add`、`git commit`、`git push`、`git pull`、`git stash`、`git rebase`、`git reset`、`git revert`、`git cherry-pick` 或 `git merge`。所有 Git index、commit 與 remote mutation 只由單一 Git Coordinator 串行處理。
- G 只修改本計畫 `Ownership` 明列的 exclusive paths，以及 Task 2 collision log 逐檔核准的最小 composition／adapter paths；不得清理、覆寫或納入其他 agent 的未提交變更。
- 使用獨立 `$env:TEMP\technical_analysis_parallel\G`、`OUTPUT_ROOT`，且每條 pytest command 必須同時指定 slice／upstream 專屬 `--basetemp` 與 `-o "cache_dir=..."`；readiness、fixture、performance、pytest cache 與 QA outputs 不得與其他 workstream 共用。
- Upstream focused tests 可依 dependency order重跑；full pytest、完整 mypy、UI QA、正式資料 smoke 等重型驗證由 Git Coordinator 核發無其他 heavy job 的串行 QA slot。
- 每個原本的 commit slice 改成 implementation／handoff slice。G 在 `$env:TEMP\technical_analysis_parallel_handoffs\G-<slice>.json` 交付 `workstream_id`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、`sha256_by_file`（path → SHA-256 mapping）、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged` 與 `rollback_notes`；handoff 不得提交進 repo。
- Handoff 發出後停止修改該 slice，直到 Git Coordinator 驗證 SHA-256、以精確 path staging 並回覆已提交或退回修正。Coordinator 提交前若 hash 已變，必須拒絕該 handoff。

## 啟動 Gate

G 的「唯讀 readiness audit」可先做；以下七份 handoff 尚未齊全時，不得新增整合程式、修改 shared files 或宣稱 closeout：

每個 workstream 的各 slice 由 Git Coordinator 提交後，Coordinator 必須另產生一份 `<workstream_id>-final-committed.json`，彙總該流所有 coordinator commits、最終 ready file SHA-256 與測試證據。G 只接受這七份 final committed manifests，不把仍為 `ready_for_commit` 的 slice handoff 當成已落地。

| ID | 必須交付 | 必要 public contract |
|---|---|---|
| A | coordinator commit SHAs、Evidence focused tests、report v2 sample | execution facts、lineage、semantic fingerprint |
| B | dataset／model artifact sample、2025 OOS report | feature schema、artifact manifest、model load contract |
| C | latency samples、snapshot fixture | `BrokerFlowDashboardSnapshot` |
| D | UI tests、Dashboard fixture | Dashboard provider protocol／read model |
| E1 | parser fixture、dry-run／working-copy report | `P0SourceCandidateStatus`、normalized observation |
| E2 | PIT coverage／blocker report | availability diagnostics、corporate-action policy |
| F | inference／registry sample、fallback tests | shadow prediction projection、artifact identity |

每份 handoff 必須包含：

```text
workstream_id
shared_branch=dev
slice_id
handoff_status=coordinator_committed
coordinator_commit_shas
owned_files_ready_with_sha256
public_interfaces
focused_test_paths
focused_tests_and_results
boundary_checks_and_results
performance_or_data_coverage_results
known_blockers
external_gates_unchanged
rollback_notes
```

## Ownership

**Create:**

- `tests/test_cross_workstream_system_integration.py`
- `scripts/verify_system_execution_blueprint.py`
- `docs/06_qa/SYSTEM_EXECUTION_BLUEPRINT_CLOSEOUT_2026_07_15.md`

**Modify only after all upstream handoffs are verified and their coordinator commits are already on `dev`:**

- `qa/full_app_healthcheck/test_inventory.py`
- `docs/06_qa/FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md`
- `docs/06_qa/EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/01_architecture/system_architecture.md`
- `docs/01_architecture/target_system_architecture.md`（只有 target boundary 確實改變時）
- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `PROJECT_NAVIGATION.md`

**Must not rewrite:** `ml_module` trainer／split、P0 ingestion、PIT repair、Broker query／semantics、Dashboard widget 或 Evidence orchestrator 的 domain logic。

---

## Task 1：建立 Dependency／Ownership Readiness Gate

**Files:**

- Before all seven are ready: write only `$env:TEMP\technical_analysis_parallel_handoffs\readiness.json` or report in the task response
- After all seven are ready: Create `docs/06_qa/SYSTEM_EXECUTION_BLUEPRINT_CLOSEOUT_2026_07_15.md`
- Read: 七份 upstream handoff、Master Plan、Design Authority

- [ ] **Step 1: 記錄整合基線**

Run:

```powershell
if ((git rev-parse --abbrev-ref HEAD) -ne 'dev') { throw 'shared dev required' }
git status --short
git rev-parse HEAD
git log --oneline --max-count=20
```

Expected: 現有變更都有 owner；不得清除或覆寫非 G 變更。

- [ ] **Step 2: 建立 readiness matrix**

在TEMP readiness report逐流記錄 coordinator commit SHA、ready file SHA-256、focused tests、artifact/schema、known blockers、shared-file collision。缺一個必要欄位，或 `handoff_status != coordinator_committed`，就標 `not_ready`；此時不得建立或修改 repository closeout 文件。

- [ ] **Step 3: 驗證 ownership**

主控將七份 `<workstream_id>-final-committed.json` 放在 `$env:TEMP\technical_analysis_parallel_handoffs`。執行：

```powershell
$handoffRoot = Join-Path $env:TEMP 'technical_analysis_parallel_handoffs'
$requiredIds = @('A', 'B', 'C', 'D', 'E1', 'E2', 'F')
foreach ($id in $requiredIds) {
  $handoffFile = Join-Path $handoffRoot "$id-final-committed.json"
  if (-not (Test-Path -LiteralPath $handoffFile)) { throw "missing final handoff: $id" }
  $handoff = Get-Content -Raw -Encoding UTF8 -LiteralPath $handoffFile | ConvertFrom-Json
  if ($handoff.shared_branch -ne 'dev') { throw "non-dev handoff: $id" }
  if ($handoff.handoff_status -ne 'coordinator_committed') { throw "uncommitted handoff: $id" }
  $history = @(git rev-list HEAD)
  foreach ($sha in @($handoff.coordinator_commit_shas)) {
    if ($history -notcontains $sha) { throw "commit not on dev HEAD history: $sha" }
  }
  foreach ($ready in @($handoff.owned_files_ready_with_sha256)) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $ready.path).Hash.ToLowerInvariant()
    if ($actual -ne $ready.sha256.ToLowerInvariant()) { throw "hash mismatch: $($ready.path)" }
  }
  $commitPaths = @($handoff.coordinator_commit_shas | ForEach-Object {
    git show --pretty=format: --name-only $_
  } | Where-Object { $_ } | Sort-Object -Unique)
  $readyPaths = @($handoff.owned_files_ready_with_sha256.path | Sort-Object -Unique)
  if (Compare-Object $commitPaths $readyPaths) { throw "commit/ownership mismatch: $id" }
}
```

Expected: 每個 commit 都位於目前 `dev` HEAD history，且 commit paths、ready paths、SHA-256 與 Master Plan ownership 完全一致。若出現中央 SSOT 或別流 exclusive path，停止 closeout 並退回 owner／Git Coordinator 修正；G 不做 Git 回退。

- [ ] **Step 4: 全部 ready 後才允許進入 repository matrix write phase**

只有七流都 `coordinator_committed` 且上述驗證通過時，才可進入 Task 3～8，最後把 verified matrix 寫入 `SYSTEM_EXECUTION_BLUEPRINT_CLOSEOUT_2026_07_15.md`；若未齊，保留 TEMP audit／任務回報，不建立 repository 文件或虛假 closeout。

## Task 2：依序驗證已落在 `dev` 的七條工作流

**Files:**

- Read: shared `dev` Git history與七份 coordinator-confirmed handoff
- Test: 每條工作流自己的 focused suite

- [ ] **Step 1: 依固定 dependency order 核對**

核對順序不可任意交換：A → C → E1 → D → B → E2 → F。這是契約驗證順序，不是 Git 整合順序；所有 coordinator commits 在 G 啟動前就必須已存在於同一個 `dev` history。G 不建立 branch、不套用或合併任何 commit。

- [ ] **Step 2: 每條整合後立即驗證**

從本次handoff的`focused_test_paths`執行：

```powershell
$tests = @($handoff.focused_test_paths)
$paths = @($handoff.owned_files_ready_with_sha256.path)
git diff --check -- $paths
& .\.venv\Scripts\python.exe -m pytest @tests -q -o addopts= --basetemp "$env:TEMP\technical_analysis_parallel\G\upstream-$($handoff.workstream_id)" -o "cache_dir=$env:TEMP\technical_analysis_parallel\G\pytest-cache-upstream-$($handoff.workstream_id)"
```

Expected: exit code 0。若 domain test 失敗，標記該 handoff `verification_failed` 並交回原 owner／Git Coordinator；G 不回退 shared `dev`、不偷修 domain logic，也不得繼續宣稱 closeout ready。

- [ ] **Step 3: 建立 interface collision log**

只允許 G 解決 composition／adapter／import 路徑衝突。每個解法必須列 consumer、producer、contract version、exclusive file owner 與 rollback notes；若需修改 domain-owned path，必須退回原 owner，不得自行擴權。

## Task 3：Cross-workstream RED Integration Tests

**Files:**

- Create: `tests/test_cross_workstream_system_integration.py`

- [ ] **Step 1: 建立 deterministic temp SQLite fixture**

Fixture 至少含：PIT-safe 價量／技術資料、受控缺表與 future-date rows、少量 broker rows、月營收 status、法人 0-row status。所有日期與 source versions 必須明確，禁止依賴正式 DB。

- [ ] **Step 2: 寫完整鏈 RED test**

驗證：

```text
governed source opened read-only
→ working-copy Evidence replay
→ PIT-safe historical feature snapshot
→ frozen dataset and shadow model artifact
→ shadow prediction / rule comparison
→ Dashboard read model
```

Assertions 必須同時涵蓋 source bytes不變、working copy可寫、artifact id／hash／parent可串接、formal score與Advice未改、Dashboard不隱藏 missing source。

- [ ] **Step 3: 寫時間邊界 RED tests**

至少包含：

- `training_end <= 2024-12-31`。
- `max(train_label_available_date) <= 2024-12-31`，且train label horizon／purge boundary早於OOS start。
- `max(blend_selection_label_available_date) <= 2024-12-31`；research alpha／threshold不能使用2025才成熟的OOF outcome。
- `2025-01-01..2025-12-31` 只進 locked OOS，不回流 tuning。
- future `available_date` 被排除。
- immature label 被排除。
- 2026 只能成熟 late-2025 label，不能供 feature／tuning。

- [ ] **Step 4: 寫 UI／query boundary tests**

至少包含：

- Broker Top／Bottom limit 已下推 query，不是 UI 事後裁切。
- 月營收、法人、信用、TDCC、broker 都存在 status card。
- `row_count=0` 顯示 `missing/degraded`，不能顯示 clean／ready。
- ML prediction 只顯示 shadow metadata，排序與 Advice payload維持 rule-only。

- [ ] **Step 5: 執行 RED tests，保存真實失敗原因**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cross_workstream_system_integration.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\G\pytest-task-3 -o "cache_dir=$env:TEMP\technical_analysis_parallel\G\pytest-cache-task-3"
```

Expected: 尚未完成的 composition／adapter assertion 失敗；不得為了變綠降低安全條件。

## Task 4：補最小 Integration Adapters

**Files:**

- Modify: only composition roots／protocol adapters identified in Task 2
- Test: `tests/test_cross_workstream_system_integration.py`

- [ ] **Step 1: 接 Evidence 與 ML artifact provider**

A 只能消費已投影 DTO／artifact；不得讓 `app_module` 或 `runtime` 直接 import `ml_module`。由 `scripts/` composition root 或 existing application port 注入 provider。

- [ ] **Step 2: 接 Dashboard providers**

G把E1 candidate status與E2 eligibility透過adapter投影成D的optional visibility provider，並保留candidate/degraded標記；C snapshot留在既有Smart Money drill-down，不接成D的完成依賴。Qt不直接查SQLite、不重新聚合domain data。

- [ ] **Step 3: 接 F shadow metadata**

正式 Recommendation score／ranking／Advice不變；任何 schema/hash/load failure一律 rule-only fallback，並留下 typed diagnostic。

- [ ] **Step 4: 跑 integration test 至 GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cross_workstream_system_integration.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\G\pytest-task-4 -o "cache_dir=$env:TEMP\technical_analysis_parallel\G\pytest-cache-task-4"
git diff --check -- tests/test_cross_workstream_system_integration.py
```

- [ ] **Step 5: 準備 integration handoff**

依 Shared `dev` Execution Protocol 產生 `G-task-4.json`，逐檔列出 integration test 與 Task 2 collision log 已核准的最小 composition／adapter paths，全部附 SHA-256；`suggested_commit_message` 為 `test(integration): cover evidence ml and dashboard flow`。不得列入任何 domain-owned 實作。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 5：建立只讀 Acceptance Verifier

**Files:**

- Create: `scripts/verify_system_execution_blueprint.py`
- Test: `tests/test_verify_system_execution_blueprint.py`

- [ ] **Step 1: 寫 malformed／missing artifact RED tests**

Verifier必須拒絕：缺hash、date boundary矛盾、train或blend-selection label在2025才可得、prediction非shadow、`production_blend_alpha_bp != 0`、formal score changed、broker latency samples不足、external gate被標complete。

- [ ] **Step 2: 實作 pure verifier**

Inputs 為 A～F JSON artifacts；output 是單一 canonical JSON，至少含：

```text
evidence_execution
ml_split_and_pit
dataset_model_prediction_identity
dashboard_visibility
broker_latency
formal_boundaries
external_pending
overall_engineering_status
```

它不得訓練模型、開啟可寫正式 DB、更新 registry 或改 gate。

- [ ] **Step 3: 跑 focused tests與 fixture smoke**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_verify_system_execution_blueprint.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\G\pytest-task-5 -o "cache_dir=$env:TEMP\technical_analysis_parallel\G\pytest-cache-task-5"
.\.venv\Scripts\python.exe scripts\verify_system_execution_blueprint.py --input-root tests\fixtures\system_execution_blueprint --output $env:TEMP\technical_analysis_parallel\G\system-blueprint-closeout.json
```

- [ ] **Step 4: 準備 verifier handoff**

依 Shared `dev` Execution Protocol 產生 `G-task-5.json`，ready files 僅列 verifier 與其 tests 並附 SHA-256；`suggested_commit_message` 為 `chore(qa): add system execution blueprint verifier`。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 6：Bounded Real-data／Performance Smoke

**Files:**

- Create: ignored artifacts under `$env:TEMP`
- Modify: closeout evidence only

- [ ] **Step 1: 記錄環境與 DB stat**

記錄 Python、OS、CPU、source path alias、DB size／mtime；正式絕對路徑與資料內容只留在 G 的 ignored TEMP／OUTPUT_ROOT，不得寫入 repository handoff ready files。

- [ ] **Step 2: 執行 bounded read-only smoke**

只查白名單日期／symbol／row limit。Evidence 的 replay寫到 temp working copy；任何 source bytes／mtime改變都 fail。

- [ ] **Step 3: 執行 Broker latency gate**

至少 1 warm-up + 20 samples；記錄 raw samples、median、p95。驗收：warm p95 < 2 秒，UI在 300 ms內顯示 loading，GUI thread不做 blocking query。

- [ ] **Step 4: 如實處理環境差異**

若未達門檻，closeout標 `performance_gate_failed` 並退回 C；不得刪除 slow samples或改門檻。

## Task 7：QA Inventory 與 Scoped SSOT 同步

**Files:**

- Modify: `qa/full_app_healthcheck/test_inventory.py`
- Modify: `docs/06_qa/FEATURE_TEST_ROUTING_MATRIX_2026_06_23.md`
- Modify: 上述中央文件 ownership 清單

- [ ] **Step 1: Documentation Coverage Pass**

先列每項使用者可見／架構／資料／ML／操作變更所影響的 authority文件；再進行 Patch Pass。不得只更新 closeout。

- [ ] **Step 2: 更新 QA routing**

加入新 tests、owner、feature route與 failure semantics；確認 inventory 匯入不執行模型訓練或正式資料寫入。

- [ ] **Step 3: 同步中央文件**

每份文件分開陳述：

```text
engineering_integration
historical_ml_shadow
dashboard_visibility
forward_evidence
source_acceptance
production_automation
```

舊兩日計畫 checkbox 只能在有 command、artifact、Git Coordinator commit evidence、completion rule時勾選。`engineering_complete` 不得推導出 forward／license／promotion complete。

- [ ] **Step 4: 更新 Application Manual**

涵蓋 Dashboard入口、資料狀態判讀、refresh／loading／error、ML shadow意義、Evidence兩種模式、安全限制與排錯。

- [ ] **Step 5: 準備 Scoped SSOT handoff**

依 Shared `dev` Execution Protocol 產生 `G-task-7.json`，逐檔列出 Coverage Pass 確認需要更新的 QA inventory、routing 與 Scoped SSOT，全部附 SHA-256；`suggested_commit_message` 為 `docs(system): align execution blueprint truth`。若 Coverage Pass 判定 `target_system_architecture.md` 沒有真實 target 變更，不得列入 ready files。交付前逐檔檢查 diff，排除非本任務文件；交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 8：完整 Verification 與 Closeout

本 Task 只能在 Git Coordinator 確認 A～F 與 G 前置 slices 都已串行提交、沒有 active writer，並核發重型 QA slot 後執行；過程仍不得由 G worker 操作 Git index、commit 或 remote。

- [ ] **Step 1: Focused integration／UI verification**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cross_workstream_system_integration.py tests/test_verify_system_execution_blueprint.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\G\pytest-final-focused -o "cache_dir=$env:TEMP\technical_analysis_parallel\G\pytest-cache-final-focused"
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py tests/test_ui_qt_smart_money_flow_view.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\G\pytest-final-ui -o "cache_dir=$env:TEMP\technical_analysis_parallel\G\pytest-cache-final-ui"
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

- [ ] **Step 2: Full suite 與 static checks**

```powershell
.\.venv\Scripts\python.exe -m pytest -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\G\pytest-full -o "cache_dir=$env:TEMP\technical_analysis_parallel\G\pytest-cache-full"
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime ml_module
.\.venv\Scripts\python.exe scripts\audit_document_encoding.py --root . --fail-on-mojibake
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe scripts\check_ml_shadow_boundary.py
```

Full pytest 要用足夠 timeout並取得本次真實 exit code，不得引用舊 closeout。

- [ ] **Step 3: Gate／blueprint verification**

```powershell
.\.venv\Scripts\python.exe scripts\verify_gate_2_to_7_closeout.py --output $env:TEMP\technical_analysis_parallel\G\system-blueprint-gates.json
.\.venv\Scripts\python.exe scripts\verify_system_execution_blueprint.py --input-root $env:TEMP\technical_analysis_parallel\G\system-blueprint-inputs --output $env:TEMP\technical_analysis_parallel\G\system-blueprint-closeout.json
```

- [ ] **Step 4: Python compile／docs links／Git hygiene**

對所有 changed Python files執行 `py_compile`；以 repository既有 link audit方式驗證 active docs relative links；再執行：

```powershell
git diff --check
git status --short
```

- [ ] **Step 5: 準備 final closeout handoff**

Closeout 必須列每條命令、本次 exit code、artifact path/hash、未完成 external/time gates、rollback notes 與對應 coordinator commit references。確認 DB、raw JSON、logs、cache、`output/**`、`graphify-out/**` 都不在 ready files 後，依 Shared `dev` Execution Protocol 產生 `G-task-8.json`；ready files 僅列 `docs/06_qa/SYSTEM_EXECUTION_BLUEPRINT_CLOSEOUT_2026_07_15.md` 並附 SHA-256，`suggested_commit_message` 為 `docs(qa): close historical engineering integration`。交付後停止修改，等待 Git Coordinator 確認並由 Coordinator 串行提交到 `dev`。

## Completion Gate

- [ ] 七份 handoff 可追溯且 ownership無未解衝突。
- [ ] Fixture E2E與 bounded real-data read-only smoke都有新鮮證據。
- [ ] Evidence、PIT、ML shadow、Dashboard、Broker performance與formal score boundary都由機器驗證，且production blend alpha固定0。
- [ ] Full pytest、mypy、UI QA、encoding、quant／ML guards、Gate verifier全部通過。
- [ ] 中央文件與程式真實狀態一致。
- [ ] forward evidence、source acceptance、production scheduler、ML promotion仍依真實條件保持 pending。
