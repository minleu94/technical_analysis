# PIT Historical Data Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and the repository data-audit workflow.

**Goal:** 為月營收、季度財報與corporate-action／restriction建立可稽核的歷史announcement／available／revision timeline與ML label-window eligibility artifact，修正「所有歷史row在2026-06-17才可得」造成的PIT缺口，但絕不猜日期或直接改正式DB。

**Architecture:** Source adapters收集官方或可分級的availability evidence；builders建立append-only canonical mappings與coverage diagnostics；eligibility projector將mapping投影成下一版dataset可消費的feature／label gates。無可信證據的rows保持unmatched／blocked；production apply與source acceptance另需人工核准。

**Tech Stack:** Python 3.11、SQLite read-only、dataclasses、Decimal／integer units、canonical JSON／CSV staging、SHA-256 manifests、pytest、mypy、official-source evidence reports。

## Shared `dev` Execution Model

- 所有 worker 都在共享 repository 的既有 `dev` branch 工作；開始前必須以唯讀命令確認 `git rev-parse --abbrev-ref HEAD` 回傳 `dev`。若不是 `dev`，停止並通知 Git Coordinator，不得自行修正。
- 不得建立、切換或刪除 branch／worktree；不得執行 `git add`、`git commit`、`git push`、`git stash`、`git pull`、`git rebase`、`git reset`、`git revert`、`git cherry-pick` 或 `git merge`。
- Worker 只可修改本計畫 `Ownership` 中的 exclusive paths。若需要碰其他工作流或中央 SSOT 的 owned file，停止該變更並列入 blockers，不得跨 ownership 代改。
- 本工作流使用獨立暫存：`TEMP=$env:TEMP\technical_analysis_parallel\E2\temp`、`TMP` 同值、`OUTPUT_ROOT=$env:TEMP\technical_analysis_parallel\E2\output`，pytest 一律加 `--basetemp $env:TEMP\technical_analysis_parallel\E2\pytest\<slice>` 與 `-o "cache_dir=$env:TEMP\technical_analysis_parallel\E2\pytest_cache\<slice>"`。Staging mapping／coverage output 必須位於此 output 下，不得共用其他 worker 的 temp、output、DB 或 pytest cache。
- Focused tests 可與其他工作流平行執行；全量 pytest、repo-wide mypy、完整 quant／ML boundary、UI QA、encoding／link audit 與其他重型 QA 只由 Coordinator 排程。Worker 不得自行啟動重型 QA 競爭共享資源。
- 每個原 commit slice 改為 implementation／handoff slice。Worker 完成 focused tests 後，必須交付 canonical fields：`workstream_id`、`slice_id`、`handoff_status: ready_for_commit`、`ready_files`、`sha256_by_file`（path → SHA-256 mapping）、`focused_test_paths`、`focused_tests_and_results`、`performance_or_data_coverage_results`、`suggested_commit_message`、`public_interfaces`、`boundary_checks_and_results`、`external_gates_unchanged: true` 與 `rollback_notes`，並附 blockers 給 Git Coordinator；不得自行 stage 或 commit。
- Handoff 送出後，worker 對該 slice 進入 `handoff_waiting`，在 Coordinator 明確確認前不得再修改該 slice 的 ready files。

## Non-negotiable PIT Rules

- `2026-06-17` backfill date不是2014～2025歷史公告日。
- period end、raw CSV filename/date、filesystem mtime、FinMind `create_time`都不能自動提升為官方announcement date。
- 每筆mapping需區分 period／event date、announcement/publication、first-observed、available、revision/effective date與source version。
- revision append-only；後來版本不能覆寫當時可見的早期版本。
- 無可信歷史公告證據的row保持unmatched／blocked；retroactive baseline只能標degraded research mapping。
- Corporate-action coverage不足時，label-window eligibility fail closed或degraded，不得標clean。
- 本工作流不修改B已凍結的core dataset；只輸出future dataset generation可用artifact。
- E2 進入寫入／實作前，Git Coordinator 必須已把 B 的 fundamentals exclusion contract slice提交並push至共享`dev`。尚未落地時只可做唯讀source盤點與準備，不得修改repository files。
- source acceptance、formal Score與production apply皆保持人工Gate。

## Ownership

**Modify:**

- `data_module/fundamental_availability.py`
- `data_module/fundamental_availability_sources.py`
- `data_module/fundamental_statement_availability_sources.py`
- `data_module/monthly_revenue_availability_history.py`
- `data_module/monthly_revenue_availability_builder.py`
- `data_module/corporate_action_policy.py`
- `data_module/p0_pit_fundamental_announcement_adapters.py`
- `data_module/p0_corporate_restriction_shadow_adapters.py`
- matching existing tests

**Create:**

- `data_module/quarterly_statement_availability_history.py`
- `data_module/corporate_action_availability_history.py`
- `data_module/p0_ml_eligibility_projection.py`
- `scripts/build_quarterly_statement_availability_history.py`
- `scripts/build_corporate_action_availability_history.py`
- `scripts/project_p0_ml_eligibility.py`
- `tests/test_quarterly_statement_availability_history.py`
- `tests/test_corporate_action_availability_history.py`
- `tests/test_p0_ml_eligibility_projection.py`
- `docs/07_guides/PIT_HISTORICAL_DATA_REPAIR_RUNBOOK.md`
- `docs/06_qa/PIT_HISTORICAL_DATA_REPAIR_CLOSEOUT_2026_07_15.md`

**Must not modify:**

- B historical feature／dataset／trainer artifacts
- F model／prediction registry
- ScoringEngine／Recommendation／Portfolio／UI／runtime scheduler
- production DB／raw source files
- central Snapshot／Roadmap／Architecture／Manual files

---

## Task 1：凍結 Announcement／Revision／Coverage Contracts

**Files:**

- Modify: `data_module/fundamental_availability.py`
- Create: `tests/test_pit_historical_availability_contracts.py`

- [ ] **Step 1: 寫backfill-date RED test**

2014～2024 row只有`available_date=2026-06-17`時，不得通過historical PIT feature gate；diagnostic須指出`retroactive_backfill_not_historical_availability`。

- [ ] **Step 2: 寫ordering／revision RED tests**

拒絕`available_at < announcement_at`、revision在原版本前可見、相同identity不同content覆寫。合法revision需保留parent/version chain。

- [ ] **Step 3: 定義canonical evidence record**

至少含 source id/version/hash、symbol、data family、period/event date、announcement/publication／first-observed、available、revision/effective、quality tier、match method、warnings。

- [ ] **Step 4: 定義coverage diagnostics**

每source／year／family輸出total、matched official、matched observed-only、unmatched、duplicate、revision、future-blocked與eligible counts。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pit_historical_availability_contracts.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E2\pytest\e2-1 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E2\pytest_cache\e2-1"
```

```yaml
handoff:
  workstream_id: E2
  slice_id: E2-1-contracts
  ready_files: [data_module/fundamental_availability.py, tests/test_pit_historical_availability_contracts.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_pit_historical_availability_contracts.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "test(data): freeze PIT announcement and revision contracts"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 2：月營收 Availability History

**Files:**

- Modify: `data_module/monthly_revenue_availability_history.py`
- Modify: `data_module/monthly_revenue_availability_builder.py`
- Modify: `data_module/fundamental_availability_sources.py`
- Modify: `data_module/p0_pit_fundamental_announcement_adapters.py`
- Modify: existing monthly revenue availability tests

- [ ] **Step 1: 寫source-tier RED tests**

Official MOPS announcement evidence可標official；實際historical first-observed可標observed-only；FinMind create time、retroactive baseline與2026 backfill不可自動標official。

- [ ] **Step 2: 寫as-of／revision RED tests**

同stock／period多次公告或修正時，任一historical as-of只能看到當時已available的版本；future revision不能改既有snapshot hash。

- [ ] **Step 3: 建立governed monthly mapping**

輸出canonical mapping、source manifest與coverage；unmatched rows保留原因，不以法定deadline或固定天數猜公告日。

- [ ] **Step 4: 執行fixture與bounded正式資料dry-run**

正式DB只讀，mapping寫explicit staging root。比較現有244,499 rows的year/source coverage與blanket-date blockers。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_monthly_revenue_availability_history.py tests/test_monthly_revenue_availability_builder.py tests/test_fundamental_availability_sources.py tests/test_p0_pit_fundamental_announcement_adapters.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E2\pytest\e2-2 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E2\pytest_cache\e2-2"
```

```yaml
handoff:
  workstream_id: E2
  slice_id: E2-2-monthly-revenue
  ready_files: [data_module/monthly_revenue_availability_history.py, data_module/monthly_revenue_availability_builder.py, data_module/fundamental_availability_sources.py, data_module/p0_pit_fundamental_announcement_adapters.py, tests/test_monthly_revenue_availability_history.py, tests/test_monthly_revenue_availability_builder.py, tests/test_fundamental_availability_sources.py, tests/test_p0_pit_fundamental_announcement_adapters.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_monthly_revenue_availability_history.py, tests/test_monthly_revenue_availability_builder.py, tests/test_fundamental_availability_sources.py, tests/test_p0_pit_fundamental_announcement_adapters.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "feat(data): build governed monthly revenue history"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 3：季度財報 Announcement／Revision History

**Files:**

- Create: `data_module/quarterly_statement_availability_history.py`
- Modify: `data_module/fundamental_statement_availability_sources.py`
- Create: `scripts/build_quarterly_statement_availability_history.py`
- Create: `tests/test_quarterly_statement_availability_history.py`

- [ ] **Step 1: 寫period-end-not-available RED test**

Quarter end或filing deadline不得直接當announcement/available；只有具provenance的official publication或first-observed evidence可用。

- [ ] **Step 2: 寫statement type／revision matching RED tests**

相同symbol／period可能有個別、合併、修訂版本；natural key與parent revision chain必須明確，不能cross-match。

- [ ] **Step 3: 實作history builder與CLI**

CLI讀source manifests與formal DB read-only，輸出staging mapping、coverage與unmatched samples hash；不修改statement rows。

- [ ] **Step 4: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_quarterly_statement_availability_history.py tests/test_fundamental_statement_availability_sources.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E2\pytest\e2-3 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E2\pytest_cache\e2-3"
```

```yaml
handoff:
  workstream_id: E2
  slice_id: E2-3-statements
  ready_files: [data_module/quarterly_statement_availability_history.py, data_module/fundamental_statement_availability_sources.py, scripts/build_quarterly_statement_availability_history.py, tests/test_quarterly_statement_availability_history.py, tests/test_fundamental_statement_availability_sources.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_quarterly_statement_availability_history.py, tests/test_fundamental_statement_availability_sources.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "feat(data): add quarterly statement availability history"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 4：Corporate-action／Restriction Timeline

**Files:**

- Create: `data_module/corporate_action_availability_history.py`
- Modify: `data_module/corporate_action_policy.py`
- Modify: `data_module/p0_corporate_restriction_shadow_adapters.py`
- Create: `scripts/build_corporate_action_availability_history.py`
- Create: `tests/test_corporate_action_availability_history.py`
- Modify: `tests/test_corporate_action_policy.py`

- [ ] **Step 1: 寫event／announcement／effective distinction RED tests**

除權息、減資、分割、面額變更與交易限制的event date、announcement/available date、record/effective date不可互換；future announcement不影響早期label window。

- [ ] **Step 2: 寫coverage unknown RED tests**

日期window內無event rows不代表沒有event；只有source coverage已證明時才可標clean，否則`coverage_unknown`／degraded或blocked。

- [ ] **Step 3: 實作append-only timeline與policy**

每event保留source/version/hash、announcement、available、effective與revision；restriction解除也作新event，不覆寫歷史。

- [ ] **Step 4: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_corporate_action_availability_history.py tests/test_corporate_action_policy.py tests/test_p0_corporate_restriction_shadow_adapters.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E2\pytest\e2-4 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E2\pytest_cache\e2-4"
```

```yaml
handoff:
  workstream_id: E2
  slice_id: E2-4-corporate-actions
  ready_files: [data_module/corporate_action_availability_history.py, data_module/corporate_action_policy.py, data_module/p0_corporate_restriction_shadow_adapters.py, scripts/build_corporate_action_availability_history.py, tests/test_corporate_action_availability_history.py, tests/test_corporate_action_policy.py, tests/test_p0_corporate_restriction_shadow_adapters.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_corporate_action_availability_history.py, tests/test_corporate_action_policy.py, tests/test_p0_corporate_restriction_shadow_adapters.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "feat(data): add corporate-action and restriction timelines"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 5：P0 ML Eligibility Projection

**Files:**

- Create: `data_module/p0_ml_eligibility_projection.py`
- Create: `scripts/project_p0_ml_eligibility.py`
- Create: `tests/test_p0_ml_eligibility_projection.py`

- [ ] **Step 1: 寫feature availability RED tests**

Fundamental observation只有在mapping quality允許且`available_at <= feature_cutoff`時eligible；blanket backfill／unmatched／future revision一律blocked。

- [ ] **Step 2: 寫label-window corporate action RED tests**

Label horizon涵蓋unknown corporate-action coverage時strict mode blocked；research mode可degraded但必須帶reason，不能進formal OOS claim。

- [ ] **Step 3: 實作 `p0-ml-eligibility.v1` artifact**

Artifact含mapping hashes、policy version、source coverage、eligible／blocked natural keys與reason counts；canonical hash deterministic，不包含machine-specific absolute path。

- [ ] **Step 4: 保持B dataset immutable**

CLI只寫explicit staging/output；不得開啟或覆寫B dataset id。Handoff說明由未來新dataset generation選擇是否消費。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p0_ml_eligibility_projection.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E2\pytest\e2-5 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E2\pytest_cache\e2-5"
```

```yaml
handoff:
  workstream_id: E2
  slice_id: E2-5-ml-eligibility
  ready_files: [data_module/p0_ml_eligibility_projection.py, scripts/project_p0_ml_eligibility.py, tests/test_p0_ml_eligibility_projection.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_p0_ml_eligibility_projection.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "feat(data): project PIT-safe ML eligibility"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 6：Coverage Audit、Runbook 與 Human Acceptance Package

**Files:**

- Create: `docs/07_guides/PIT_HISTORICAL_DATA_REPAIR_RUNBOOK.md`
- Create: `docs/06_qa/PIT_HISTORICAL_DATA_REPAIR_CLOSEOUT_2026_07_15.md`

- [ ] **Step 1: 對正式DB執行read-only coverage audit**

輸出monthly revenue、statements、corporate actions逐year/source的matched official、observed-only、unmatched、future-blocked、revision與eligible統計。Output放explicit ignored path，formal DB stat不變。

- [ ] **Step 2: 產生人工作業決策包**

每source提供 `accepted/limited/rejected/deferred`所需證據、license未知項、coverage門檻與completion rule；本任務不得自行把status填accepted。

- [ ] **Step 3: 文件化apply邊界**

本任務只建立staging mapping與eligibility。任何production backfill／migration需要新任務、備份、dry-run diff、人工核准與rollback；不得隱含執行。

- [ ] **Step 4: Worker focused verification 與 Coordinator heavy-QA request**

```powershell
$tests = @(
  'tests/test_pit_historical_availability_contracts.py',
  'tests/test_monthly_revenue_availability_history.py',
  'tests/test_monthly_revenue_availability_builder.py',
  'tests/test_fundamental_availability_sources.py',
  'tests/test_fundamental_statement_availability_sources.py',
  'tests/test_quarterly_statement_availability_history.py',
  'tests/test_corporate_action_availability_history.py',
  'tests/test_corporate_action_policy.py',
  'tests/test_p0_ml_eligibility_projection.py'
)
.\.venv\Scripts\python.exe -m pytest $tests -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E2\pytest\e2-6 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E2\pytest_cache\e2-6"
git diff --check -- docs/07_guides/PIT_HISTORICAL_DATA_REPAIR_RUNBOOK.md docs/06_qa/PIT_HISTORICAL_DATA_REPAIR_CLOSEOUT_2026_07_15.md
git status --short  # shared dev 的 foreign dirty entries 是預期狀態；不得修改
```

對全部changed Python files執行`py_compile`。

Worker 不執行repo-wide或重型QA；`scripts/quant_guard_linter.py`、完整`mypy data_module`與全量suite列入Git Coordinator heavy-QA queue。

- [ ] **Step 5: Closeout implementation／Git Coordinator handoff**

```yaml
handoff:
  workstream_id: E2
  slice_id: E2-6-closeout-docs
  ready_files: [docs/07_guides/PIT_HISTORICAL_DATA_REPAIR_RUNBOOK.md, docs/06_qa/PIT_HISTORICAL_DATA_REPAIR_CLOSEOUT_2026_07_15.md]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_pit_historical_availability_contracts.py, tests/test_monthly_revenue_availability_history.py, tests/test_monthly_revenue_availability_builder.py, tests/test_fundamental_availability_sources.py, tests/test_fundamental_statement_availability_sources.py, tests/test_quarterly_statement_availability_history.py, tests/test_corporate_action_availability_history.py, tests/test_corporate_action_policy.py, tests/test_p0_ml_eligibility_projection.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker／Coordinator QA pending清單"
  suggested_commit_message: "docs(data): publish PIT repair coverage evidence"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Completion Gate

- [ ] 月營收／財報／corporate action mapping皆具source/version/hash與time semantics。
- [ ] unmatched、future、duplicate、revision與coverage unknown都有typed diagnostics。
- [ ] 無證據日期沒有被猜值；正式DB與raw source未寫入。
- [ ] `p0-ml-eligibility.v1`可供下一版dataset使用，但B frozen dataset完全未改。
- [ ] Closeout如實區分engineering tooling、actual coverage、source acceptance與production apply；後三者可保持pending／limited。
