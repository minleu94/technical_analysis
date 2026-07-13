# P0 Daily Source Candidate Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and the repository data-audit workflow.

**Goal:** 將三大法人、信用交易與TDCC現有fetcher升級為具官方schema fixtures、真實publication／first-observed時間、normalized contract、raw manifest、quarantine、coverage與安全working-copy ingestion的candidate-only pipeline。

**Architecture:** Fetcher只取得raw payload與官方response metadata；source-specific parser轉canonical candidate rows；availability policy只接受官方publication timestamp或實際first-observed timestamp，不猜 `decision_date+1`／`period_end+3`；candidate repository只寫explicit working-copy。Readiness service輸出0-row也可見的P0 candidate status，但不改正式Score或source acceptance。

**Tech Stack:** Python 3.11、requests／existing fetch transport、dataclasses、Decimal／integer units、SHA-256 raw manifests、SQLite working-copy、pytest fixtures、JSON／Markdown diagnostics。

## Shared `dev` Execution Model

- 所有 worker 都在共享 repository 的既有 `dev` branch 工作；開始前必須以唯讀命令確認 `git rev-parse --abbrev-ref HEAD` 回傳 `dev`。若不是 `dev`，停止並通知 Git Coordinator，不得自行修正。
- 不得建立、切換或刪除 branch／worktree；不得執行 `git add`、`git commit`、`git push`、`git stash`、`git pull`、`git rebase`、`git reset`、`git revert`、`git cherry-pick` 或 `git merge`。
- Worker 只可修改本計畫 `Ownership` 中的 exclusive paths。若需要碰其他工作流或中央 SSOT 的 owned file，停止該變更並列入 blockers，不得跨 ownership 代改。
- 本工作流使用獨立暫存：`TEMP=$env:TEMP\technical_analysis_parallel\E1\temp`、`TMP` 同值、`OUTPUT_ROOT=$env:TEMP\technical_analysis_parallel\E1\output`，pytest 一律加 `--basetemp $env:TEMP\technical_analysis_parallel\E1\pytest\<slice>` 與 `-o "cache_dir=$env:TEMP\technical_analysis_parallel\E1\pytest_cache\<slice>"`。SQLite working-copy 必須位於此工作流 output 下，不得共用其他 worker 的 temp、output、DB 或 pytest cache。
- Focused tests 可與其他工作流平行執行；全量 pytest、repo-wide mypy、完整 quant／ML boundary、UI QA、encoding／link audit 與其他重型 QA 只由 Coordinator 排程。Worker 不得自行啟動重型 QA 競爭共享資源。
- 每個原 commit slice 改為 implementation／handoff slice。Worker 完成 focused tests 後，必須交付 canonical fields：`workstream_id`、`slice_id`、`handoff_status: ready_for_commit`、`ready_files`、`sha256_by_file`（path → SHA-256 mapping）、`focused_test_paths`、`focused_tests_and_results`、`performance_or_data_coverage_results`、`suggested_commit_message`、`public_interfaces`、`boundary_checks_and_results`、`external_gates_unchanged: true` 與 `rollback_notes`，並附 blockers 給 Git Coordinator；不得自行 stage 或 commit。
- Handoff 送出後，worker 對該 slice 進入 `handoff_waiting`，在 Coordinator 明確確認前不得再修改該 slice 的 ready files。

## Non-negotiable Data Rules

- 目前 `decision_date+1` 與TDCC `data_date+3` 只是推測，不能保存為verified `available_date`。
- 優先保存官方publication timestamp；官方未提供時保存本次實際 `fetched_at/first_observed_at`，不可回填交易日。
- 同日資料保留timezone-aware timestamp；不能只靠同一日期推定收盤前已可用。
- Fetcher `stock_code/decision_date` 與shadow adapter `symbol/trade_date`必須在normalized contract統一，不能由consumer猜欄位。
- malformed、schema drift、conflict進quarantine；missing不可補0。
- candidate `downstream_eligibility=none`、`production_scheduler_allowed=false`、`human_decision=requires_human_acceptance`。
- dry-run不得建立DB／table／directory／DBManager log；apply只允許explicit isolated working-copy。

## Ownership

**Modify:**

- `data_module/official_phase3c_fetcher.py`
- `scripts/update_phase3c_candidates.py`
- `app_module/source_candidate_readiness.py`
- `tests/test_phase3c_candidate_ingestion.py`
- `tests/test_source_candidate_readiness.py`

**Create:**

- `data_module/p0_source_candidate_contracts.py`
- `data_module/p0_official_source_parsers.py`
- `data_module/p0_candidate_manifest.py`
- `data_module/p0_candidate_repository.py`
- `tests/test_p0_source_candidate_contracts.py`
- `tests/test_p0_official_source_parsers.py`
- `tests/test_p0_candidate_repository.py`
- official parser fixtures under `tests/fixtures/p0_official_sources/`
- `docs/07_guides/P0_DAILY_SOURCE_CANDIDATE_RUNBOOK.md`
- `docs/06_qa/P0_DAILY_SOURCE_CANDIDATE_CLOSEOUT_2026_07_15.md`

**Must not modify:**

- Market Dashboard／Decision Desk／Smart Money UI
- `decision_module/scoring_engine.py`
- Recommendation／Portfolio／runtime scheduler
- monthly revenue／statement availability（E2 owns）
- central Snapshot／Roadmap／Architecture／Manual files

---

## Task 1：凍結 Normalized Observation／Manifest Contract

**Files:**

- Create: `data_module/p0_source_candidate_contracts.py`
- Create: `data_module/p0_candidate_manifest.py`
- Create: `tests/test_p0_source_candidate_contracts.py`

- [ ] **Step 1: 寫欄位不一致RED tests**

Raw fixture使用`stock_code/decision_date`，consumer contract要求`symbol/trade_date`；test必須證明normalized row只有一套canonical names，且所有source-specific aliases在parser邊界結束。

- [ ] **Step 2: 寫availability policy RED tests**

沒有official publication timestamp時，`available_at`不得等於推算的`decision_date+1`／`period_end+3`；必須使用實際first-observed並將quality標degraded／observed-only。

- [ ] **Step 3: 定義normalized contracts**

每筆row至少含 source id/version、symbol、observation/trade date、period、publication_at或null、first_observed_at、available_at、raw payload hash、normalized content hash、quality、eligibility、warnings。數量使用integer shares／lots等明確單位。

- [ ] **Step 4: 定義raw manifest／quarantine record**

Manifest含endpoint id、request parameters、HTTP metadata、fetched_at、payload hash/size、parser version、row counts；quarantine含raw row hash、reason code與source version，不保存秘密token。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p0_source_candidate_contracts.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E1\pytest\e1-1 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E1\pytest_cache\e1-1"
```

```yaml
handoff:
  workstream_id: E1
  slice_id: E1-1-contracts
  ready_files: [data_module/p0_source_candidate_contracts.py, data_module/p0_candidate_manifest.py, tests/test_p0_source_candidate_contracts.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_p0_source_candidate_contracts.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "test(data): freeze P0 source observation contracts"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 2：以Captured Official Fixtures鎖定 Parsers

**Files:**

- Create: `data_module/p0_official_source_parsers.py`
- Create: `tests/test_p0_official_source_parsers.py`
- Create: `tests/fixtures/p0_official_sources/**`
- Modify: `data_module/official_phase3c_fetcher.py`

- [ ] **Step 1: 建立fixture provenance**

針對TWSE／TPEx三大法人、信用與TDCC，保存可合法提交的最小去識別payload fixture及來源URL／capture date／schema version說明；不保存token或大量原始資料。

- [ ] **Step 2: 寫schema drift／malformed RED tests**

欄位改名、空欄、千分位、負號、日期格式、duplicate、部分source outage各有typed diagnostics；不得吞例外或補0。

- [ ] **Step 3: 寫timestamp evidence RED tests**

官方response有publication timestamp時保留；只有HTTP/fetch time時標first-observed；period end與file date不得自動提升成publication。

- [ ] **Step 4: 實作source-specific parsers與fetch envelope**

Fetcher回raw envelope，不自行猜availability。Live network只作manual smoke，不作deterministic test gate；tests只用captured fixtures。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p0_official_source_parsers.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E1\pytest\e1-2 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E1\pytest_cache\e1-2"
```

```yaml
handoff:
  workstream_id: E1
  slice_id: E1-2-official-parsers
  ready_files: [data_module/p0_official_source_parsers.py, data_module/official_phase3c_fetcher.py, tests/test_p0_official_source_parsers.py, tests/fixtures/p0_official_sources]
  sha256_by_file:
    "<path from ready_files; expand fixture directories to individual files>": "<SHA-256; one entry per file>"
  focused_test_paths: [tests/test_p0_official_source_parsers.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "fix(data): preserve verified source publication evidence"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 3：Normalizers、Conservation 與 Quarantine

**Files:**

- Modify: `data_module/p0_official_source_parsers.py`
- Modify: `tests/test_p0_official_source_parsers.py`

- [ ] **Step 1: 寫row conservation RED tests**

每個raw row必須恰好落在accepted、duplicate-idempotent、quarantine或blocked之一；四類總數等於parsed raw count。

- [ ] **Step 2: 寫idempotency／conflict RED tests**

同source/version/natural key相同payload重跑idempotent；相同identity不同content進conflict quarantine，不覆寫先前row。

- [ ] **Step 3: 實作三類source normalizers**

Institutional／credit／TDCC各自轉canonical observation，保留source-specific extras在versioned metadata；不得讓consumer依賴raw Chinese headers。

- [ ] **Step 4: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p0_official_source_parsers.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E1\pytest\e1-3 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E1\pytest_cache\e1-3"
```

```yaml
handoff:
  workstream_id: E1
  slice_id: E1-3-normalizers
  ready_files: [data_module/p0_official_source_parsers.py, tests/test_p0_official_source_parsers.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_p0_official_source_parsers.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "feat(data): normalize institutional credit and TDCC candidates"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 4：Candidate-only Working-copy Repository

**Files:**

- Create: `data_module/p0_candidate_repository.py`
- Create: `tests/test_p0_candidate_repository.py`
- Modify: `scripts/update_phase3c_candidates.py`
- Modify: `tests/test_phase3c_candidate_ingestion.py`

- [ ] **Step 1: 寫production path rejection RED tests**

拒絕`TWStockConfig`正式DB、DATA_ROOT、其descendants、symlink/resolved alias與production-like default。Apply要求`--working-copy-db`＋`--confirm-candidate-write`；沒有兩者即dry-run。

- [ ] **Step 2: 寫dry-run no-side-effect RED tests**

Dry-run前後filesystem tree完全相同；不得初始化會建schema/log的`DBManager`。Output report如未指定路徑只寫stdout。

- [ ] **Step 3: 寫atomic／restart RED tests**

Transaction中斷不留半批；重跑相同batch idempotent；conflicts append quarantine；existing unrelated tables/rows不變。

- [ ] **Step 4: 實作repository與CLI range模式**

支援current與明確date range；先fetch／parse／diagnose，再選擇dry-run或working-copy apply。Manifest、accepted、quarantine與coverage使用同一run id串起。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p0_candidate_repository.py tests/test_phase3c_candidate_ingestion.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E1\pytest\e1-4 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E1\pytest_cache\e1-4"
```

```yaml
handoff:
  workstream_id: E1
  slice_id: E1-4-working-copy
  ready_files: [data_module/p0_candidate_repository.py, scripts/update_phase3c_candidates.py, tests/test_p0_candidate_repository.py, tests/test_phase3c_candidate_ingestion.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_p0_candidate_repository.py, tests/test_phase3c_candidate_ingestion.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "feat(data): add candidate-only working-copy ingestion"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 5：Readiness／Source Status 與 Coverage Artifact

**Files:**

- Modify: `app_module/source_candidate_readiness.py`
- Modify: `tests/test_source_candidate_readiness.py`

- [ ] **Step 1: 寫0-row visibility RED tests**

每個P0 source即使0 rows也輸出 `P0SourceCandidateStatus`，含latest observation／available time、row/symbol counts、schema quality、coverage、eligibility、warnings與human decision。

- [ ] **Step 2: 寫candidate不等於accepted RED tests**

有大量rows也只能顯示candidate engineering status；不得因coverage高自動改`downstream_eligibility`、source acceptance registry或scheduler flag。

- [ ] **Step 3: 實作source status projection**

只讀manifest／candidate repository；不要在application service觸發fetch或寫入。供D/G以adapter消費，但本流不修改UI。

- [ ] **Step 4: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_source_candidate_readiness.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E1\pytest\e1-5 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E1\pytest_cache\e1-5"
```

```yaml
handoff:
  workstream_id: E1
  slice_id: E1-5-readiness
  ready_files: [app_module/source_candidate_readiness.py, tests/test_source_candidate_readiness.py]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_source_candidate_readiness.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker 清單"
  suggested_commit_message: "feat(data): expose P0 candidate source status"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Task 6：Bounded Live Probe、Runbook 與 Closeout

**Files:**

- Create: `docs/07_guides/P0_DAILY_SOURCE_CANDIDATE_RUNBOOK.md`
- Create: `docs/06_qa/P0_DAILY_SOURCE_CANDIDATE_CLOSEOUT_2026_07_15.md`

- [ ] **Step 1: 逐來源執行bounded live dry-run**

只向官方endpoint查最小日期範圍；遵守rate limit，記錄endpoint/schema/fetched time/status。Network failure是source diagnostic，不得改fixture test結果。

- [ ] **Step 2: 執行isolated working-copy smoke**

從temp空DB或明確working copy寫candidate batch；重跑驗idempotency與conflict quarantine。正式DB stat不變。

- [ ] **Step 3: 文件化操作與人工Gate**

Runbook涵蓋current/range dry-run、working-copy apply、outputs、owner、rollback、failure、禁止事項與source acceptance completion rule。

- [ ] **Step 4: Worker focused verification 與 Coordinator heavy-QA request**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p0_source_candidate_contracts.py tests/test_p0_official_source_parsers.py tests/test_p0_candidate_repository.py tests/test_phase3c_candidate_ingestion.py tests/test_source_candidate_readiness.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\E1\pytest\e1-6 -o "cache_dir=$env:TEMP\technical_analysis_parallel\E1\pytest_cache\e1-6"
git diff --check -- docs/07_guides/P0_DAILY_SOURCE_CANDIDATE_RUNBOOK.md docs/06_qa/P0_DAILY_SOURCE_CANDIDATE_CLOSEOUT_2026_07_15.md
git status --short  # shared dev 的 foreign dirty entries 是預期狀態；不得修改
```

對全部changed Python files執行`py_compile`。

Worker 不執行repo-wide或重型QA；`scripts/quant_guard_linter.py`、完整targeted mypy與全量suite列入Git Coordinator heavy-QA queue。

- [ ] **Step 5: Closeout implementation／Git Coordinator handoff**

```yaml
handoff:
  workstream_id: E1
  slice_id: E1-6-closeout-docs
  ready_files: [docs/07_guides/P0_DAILY_SOURCE_CANDIDATE_RUNBOOK.md, docs/06_qa/P0_DAILY_SOURCE_CANDIDATE_CLOSEOUT_2026_07_15.md]
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_p0_source_candidate_contracts.py, tests/test_p0_official_source_parsers.py, tests/test_p0_candidate_repository.py, tests/test_phase3c_candidate_ingestion.py, tests/test_source_candidate_readiness.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "none 或具體 blocker／Coordinator QA pending清單"
  suggested_commit_message: "docs(data): close P0 candidate ingestion engineering"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出後停止修改本 slice ready files，等待 Git Coordinator 確認。

## Completion Gate

- [ ] 每筆candidate具有source/version/raw hash/fetched time與可信availability policy。
- [ ] 未知publication time不再被推算日期冒充；historical rows可合理保持blocked。
- [ ] Dry-run零side effects；apply只寫explicit working-copy並拒絕production paths。
- [ ] duplicate idempotent、conflict／malformed quarantine、row conservation成立。
- [ ] 0-row source status仍可見；source acceptance、formal Score與scheduler狀態完全未提升。
