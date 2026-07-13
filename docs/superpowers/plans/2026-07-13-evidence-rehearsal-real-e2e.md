# Evidence Rehearsal Real E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留既有 replay-summary projection 相容模式，新增真正開啟唯讀 source DB、建立隔離 working copy、執行 historical replay／P0／可選 ML comparison／lineage 的 Evidence Rehearsal E2E 模式。

**Architecture:** 新增 `EvidenceRehearsalSourceReader` 與 `EvidenceRehearsalOrchestrator`；CLI 只負責解析路徑與序列化。`working_copy_e2e` 先以 SQLite backup API複製唯讀source，再只對working copy執行 `HistoricalEvidenceReplayService.run()`；Orchestrator從實際產物建立 `ArtifactIdentity`並呼叫 `EvidenceRehearsalService.run()`。故障注入改變working copy／provider的真實輸入，不再直接append blocker。

**Tech Stack:** Python 3.11、sqlite3 URI `mode=ro`、dataclasses、JSON／Markdown、pytest subprocess、Decimal／integer bp、existing Evidence／P0／ML modules。

## Global Constraints

### Shared `dev` Execution Protocol（本計畫所有 Task 的最高優先規則）

- 開工前以唯讀 `git rev-parse --abbrev-ref HEAD` 確認結果為 `dev`；不得建立或切換 branch／worktree。
- Worker 禁止執行 `git add`、`git commit`、`git push`、`git pull`、`git stash`、`git rebase`、`git reset`、`git revert`、`git cherry-pick` 或 `git merge`。所有 Git index、commit 與 remote mutation 只由單一 Git Coordinator 串行處理。
- 只修改本計畫 `Ownership` 明列的 exclusive paths；看到其他 agent 的未提交變更時保留原狀，不得清理、覆寫或納入自己的交付。
- 每個 workstream 使用獨立 `$env:TEMP\technical_analysis_parallel\A`、`OUTPUT_ROOT`，且每條 pytest command 必須同時指定 slice 專屬 `--basetemp` 與 `-o "cache_dir=..."`；不得共用 temp、cache 或其他可寫輸出目錄。
- Focused tests 可在互斥 owned files 上平行執行；full pytest、完整 mypy、UI QA、正式資料 smoke 等重型驗證由 Git Coordinator 排程，避免資源與輸出互撞。
- 每個原本的 commit slice 改成 implementation／handoff slice。Worker 在 `$env:TEMP\technical_analysis_parallel_handoffs\A-<slice>.json` 交付 `workstream_id`、`slice_id`、`handoff_status=ready_for_commit`、`ready_files`、`sha256_by_file`（path → SHA-256 mapping）、`suggested_commit_message`、`public_interfaces`、`focused_test_paths`、`focused_tests_and_results`、`boundary_checks_and_results`、`performance_or_data_coverage_results`、`blockers`、`external_gates_unchanged` 與 `rollback_notes`；不得把 handoff 檔提交進 repo。
- Handoff 發出後停止修改該 slice，直到 Git Coordinator 驗證 SHA-256、以精確 path staging 並回覆已提交或退回修正。Coordinator 提交前若 hash 已變，必須拒絕該 handoff。

- 不寫 production DB；source DB 必須 `mode=ro` 且 `PRAGMA query_only=ON`。
- `projection_only` 保持既有相容；`working_copy_e2e` 必須建立明確隔離working copy。
- working copy／output不得位於`DATA_ROOT`、正式DB目錄或其resolved descendants；既有target預設拒絕覆寫。
- 不修改正式 Evidence、Recommendation、Advice、scheduler、broker、Portfolio 或 ML lifecycle。
- `scenario.decision_date` 必須與 replay decision day 一致；不一致直接 blocker，不能 coverage=10000。
- 13 個 P0 contract 即使 0 rows 仍必須出現在 report。
- ML 必須經 `MLRehearsalComparisonService.compare()`；不得信任任意 JSON status。
- 所有 artifacts 保留 content hash、parent ids、tier 與 rollback reference。
- 本流不得修改 `ui_qt/`、`app_module/recommendation_service.py` 或中央 SSOT 文件。

---

## Ownership

**Owns:**

- `scripts/run_evidence_rehearsal.py`
- `app_module/evidence_rehearsal_*`
- `tests/test_evidence_rehearsal_*`
- `docs/07_guides/EVIDENCE_REHEARSAL_RUNBOOK.md`
- 新增 `docs/06_qa/EVIDENCE_REHEARSAL_REAL_E2E_CLOSEOUT_2026_07_13.md`

**Must not modify:** `ui_qt/`、`ml_module/`、`data_module/official_phase3c_fetcher.py`、`app_module/recommendation_service.py`、`docs/00_core/*`。

## Task 1: 建立 Truth Regression Tests

**Files:**
- Create: `tests/test_evidence_rehearsal_real_e2e.py`
- Modify: `tests/test_evidence_rehearsal_cli.py`

**Interfaces:**
- Produces: source DB opened、date coherence、ML boundary、lineage output與 source immutability 的失敗測試。

- [ ] **Step 0: 凍結兩種execution modes**

`projection_only` 必須回報 `source_db.opened=false`、`working_copy.created=false`；`working_copy_e2e` 必須回報source read-only與working-copy write facts。兩者都不得把工程執行誤寫成forward evidence。

- [ ] **Step 1: 寫 scenario／replay date mismatch RED test**

```python
def test_cli_blocks_replay_day_after_scenario_decision_date(tmp_path):
    completed, report = run_cli(
        tmp_path,
        scenario_decision_date="2026-07-12",
        replay_decision_date="2026-07-13",
    )
    assert completed.returncode == 2
    assert "scenario_replay_decision_date_mismatch" in report["blockers"]
    assert report["coverage_metrics"][0]["observed_count"] == 0
```

- [ ] **Step 2: 寫 invalid ML payload RED test**

```python
def test_cli_does_not_trust_supplied_shadow_ready_status(tmp_path):
    _, report = run_cli(
        tmp_path,
        ml_shadow={"status": "shadow_ready", "total_rows": 0, "accepted_rows": 999},
    )
    assert report["ml_shadow"]["status"] in {
        "boundary_inconsistent", "insufficient_sample", "training_context_required"
    }
    assert "ml_shadow:shadow_ready" not in report["blockers"]
```

- [ ] **Step 3: 寫 DB 與 lineage RED test**

```python
def test_real_e2e_opens_source_read_only_and_emits_lineage(tmp_path):
    source = seed_rehearsal_source_db(tmp_path / "source.sqlite3")
    before = source.read_bytes()
    _, report = run_cli(tmp_path, source_db=source)
    assert report["execution"]["source_db_opened"] is True
    assert report["lineage"]["artifact_dag"]
    assert report["lineage"]["artifact_hashes"]
    assert source.read_bytes() == before
```

- [ ] **Step 4: 執行 RED tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_rehearsal_real_e2e.py tests/test_evidence_rehearsal_cli.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\A\pytest-task-1 -o "cache_dir=$env:TEMP\technical_analysis_parallel\A\pytest-cache-task-1"
```

Expected: 新 assertions 失敗，證明目前 CLI 未開 DB、未輸出 lineage、未驗證 ML payload。

- [ ] **Step 5: 準備 tests handoff**

依 Shared `dev` Execution Protocol 產生 `A-task-1.json`，ready files 僅列本 Task 的兩個測試檔並附 SHA-256；`suggested_commit_message` 為 `test(evidence): expose rehearsal e2e truth gaps`。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 2: Read-only Source DB Reader 與隔離 Working Copy

**Files:**
- Create: `app_module/evidence_rehearsal_source_reader.py`
- Test: `tests/test_evidence_rehearsal_source_reader.py`
- Modify: `app_module/historical_evidence_replay.py`
- Modify: `tests/test_historical_evidence_replay.py`

**Interfaces:**
- Produces: `EvidenceRehearsalSourceSnapshot`、`EvidenceRehearsalSourceReader.read(path, decision_date)` 與安全的 SQLite backup working-copy facts。

- [ ] **Step 1: 寫 reader contract test**

```python
def test_reader_reports_schema_and_never_writes_source(tmp_path):
    db = seed_source_db(tmp_path / "source.sqlite3")
    before = db.read_bytes()
    snapshot = EvidenceRehearsalSourceReader().read(db, decision_date="2026-07-09")
    assert snapshot.opened is True
    assert snapshot.schema_fingerprint
    assert snapshot.table_row_counts["daily_prices"] > 0
    assert db.read_bytes() == before
```

- [ ] **Step 2: 實作 frozen DTO 與 query-only reader**

`EvidenceRehearsalSourceSnapshot` 至少含 source path alias、decision date、opened/access mode、schema fingerprint、白名單table counts、P0 observations與diagnostics。Schema fingerprint使用sorted table/column canonical JSON的SHA-256；P0 rows必須通過既有shadow adapters或明確標示missing。不得在source連線執行DDL/DML。

- [ ] **Step 3: 加入 missing table／schema diagnostics tests**

要求缺表輸出 `schema_missing:<table>`，SQLite error輸出 typed exception；不得偷偷建立 table。

- [ ] **Step 4: 建立SQLite backup working copy**

Source連線維持`mode=ro`＋`query_only=ON`，以SQLite backup API寫入安全target。既有target預設fail；只有`--overwrite-working-copy`且safe-path guard通過才可覆寫。Replay service只能寫working copy，source bytes／mtime保持不變。

- [ ] **Step 5: 寫semantic determinism tests**

相同source、scenario與全新working copy產生相同semantic fingerprint；runtime timestamps可不同，因此不要求整份JSON byte-identical。Report分開記錄source write、working-copy write與production write facts。

- [ ] **Step 6: 跑 focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_rehearsal_source_reader.py tests/test_historical_evidence_replay.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\A\pytest-task-2 -o "cache_dir=$env:TEMP\technical_analysis_parallel\A\pytest-cache-task-2"
.\.venv\Scripts\python.exe -m py_compile app_module/evidence_rehearsal_source_reader.py
```

- [ ] **Step 7: 準備 implementation handoff**

依 Shared `dev` Execution Protocol 產生 `A-task-2.json`，只列本 Task 的 reader、replay 與測試檔並附 SHA-256；`suggested_commit_message` 為 `feat(evidence): run replay on isolated sqlite copy`。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 3: 真實 Orchestrator 與 Lineage Bridge

**Files:**
- Create: `app_module/evidence_rehearsal_orchestrator.py`
- Create: `app_module/evidence_rehearsal_lineage_adapter.py`
- Modify: `app_module/evidence_rehearsal_service.py`
- Test: `tests/test_evidence_rehearsal_orchestrator.py`

**Interfaces:**
- Consumes: scenario、source snapshot、actual replay outputs、實際paper／health artifacts與optional `MLRehearsalEvidenceProvider`。
- Produces: `EvidenceRehearsalExecutionReport`。

- [ ] **Step 1: 寫actual／missing chain RED tests**

```python
def test_orchestrator_runs_required_adapters_and_lineage(complete_inputs):
    report = EvidenceRehearsalOrchestrator().run(complete_inputs)
    assert report.source_db_opened is True
    assert report.lineage_status == "complete"
    assert tuple(report.artifact_dag) == (
        "data", "market", "recommendation", "advice", "paper", "health",
        "evidence", "outcome", "weekly", "signal", "ml",
    )
    assert report.formal_product_closeout is False
    assert report.production_actions_allowed is False
```

另寫缺Advice／paper／health／weekly／ML的fixture，assert report誠實為`degraded/pending`且列出missing blockers；工程DoD不要求正式資料run一定產生complete DAG。

- [ ] **Step 2: 定義execution input／report與optional ML provider**

Request需含execution mode、scenario、source／working-copy paths、date range、overwrite flag與artifact inputs。ML provider以Protocol回傳manifest、boundary result、prediction rows與diagnostics；未提供時report必須寫`not_invoked_missing_input`，不能冒充已完成comparison。Report至少含source／working-copy write facts、service call facts、adapter statuses、DAG/hashes、coverage、P0/ML status、semantic fingerprint、blockers與formal flags。

- [ ] **Step 3: 實作 lineage bridge**

`RehearsalArtifactIdentityAdapter.project()` 必須把 canonical `RehearsalArtifact` 轉成 `ArtifactIdentity`；content hash、decision date與 parent ids 原樣保存，不重新計算 domain結果。

- [ ] **Step 4: Orchestrator 必須呼叫 real services**

依序呼叫source probe、working-copy backup、`HistoricalEvidenceReplayService.run(confirm=True)`、historical adapter、coverage projector、P0 comparison、optional `MLRehearsalComparisonService.compare()`、lineage bridge、`EvidenceRehearsalService.run()`。禁止呼叫 `EvidenceRehearsalService.build()` 作為E2E終點，也禁止用fixture補齊不存在的stage。

- [ ] **Step 5: 跑 orchestrator／lineage／ML tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_rehearsal_orchestrator.py tests/test_evidence_rehearsal_service.py tests/test_evidence_rehearsal_ml_comparison.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\A\pytest-task-3 -o "cache_dir=$env:TEMP\technical_analysis_parallel\A\pytest-cache-task-3"
```

- [ ] **Step 6: 準備 implementation handoff**

依 Shared `dev` Execution Protocol 產生 `A-task-3.json`，只列本 Task 的 orchestrator、lineage bridge、service 與測試檔並附 SHA-256；`suggested_commit_message` 為 `feat(evidence): orchestrate real rehearsal lineage`。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 4: Real Failure Injection Ports

**Files:**
- Create: `app_module/evidence_rehearsal_fault_injection.py`
- Test: `tests/test_evidence_rehearsal_fault_injection.py`
- Modify: `app_module/evidence_rehearsal_orchestrator.py`

**Interfaces:**
- Produces: `EvidenceRehearsalFaultInjector.wrap(inputs, failure)`；failure choices 保持五種既有 CLI choice。

- [ ] **Step 1: 寫五種 detector-path tests**

```python
@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("missing_day", "missing_trading_day:"),
        ("source_outage", "adapter_failure:source:"),
        ("future_available_date", "future_feature:"),
        ("schema_missing", "schema_missing:"),
        ("immature_label", "label_not_mature"),
    ],
)
def test_faults_are_detected_by_real_boundaries(complete_inputs, failure, expected):
    injected = EvidenceRehearsalFaultInjector().inject(complete_inputs, failure)
    report = EvidenceRehearsalOrchestrator().run(injected)
    assert any(expected in item for item in report.blockers)
```

- [ ] **Step 2: 實作 immutable input transforms／failing wrappers**

`missing_day` 從working copy移除指定日價量後由trading-date/replay gate偵測；`schema_missing`在working copy改名必要table後由reader/replay偵測；`source_outage`讓source gateway拋typed open failure；`future_available_date`修改raw replay／P0 observation；`immature_label`透過ML provider fixture送入未成熟label。每次輸出target、mutation、detector與observed blockers；不得直接修改report.blockers。

- [ ] **Step 3: 確認每種 failure repeat=2 deterministic**

比較完整 report canonical JSON hash，不只 blocker字串。

- [ ] **Step 4: 準備 implementation handoff**

依 Shared `dev` Execution Protocol 產生 `A-task-4.json`，只列本 Task 的 fault injection、orchestrator 與測試檔並附 SHA-256；`suggested_commit_message` 為 `test(evidence): inject failures through real rehearsal boundaries`。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 5: CLI v2 接入 Orchestrator

**Files:**
- Modify: `scripts/run_evidence_rehearsal.py`
- Modify: `tests/test_evidence_rehearsal_cli.py`
- Modify: `tests/test_evidence_rehearsal_real_e2e.py`

- [ ] **Step 1: CLI加入明確execution mode**

保留既有arguments與預設`projection_only`相容行為；新增：

```text
--execution-mode projection_only|working_copy_e2e
--source-db
--working-copy-db
--start-date
--end-date
--ml-evidence-root
--overwrite-working-copy
```

`working_copy_e2e`輸出contract v2，包含source／working-copy facts、schema fingerprint、service call facts、lineage DAG/hashes、computed ML status與actual fault diagnostics。

- [ ] **Step 2: 拒絕不一致 date／unsafe paths**

所有invalid input return code固定2；stderr與JSON blocker可判讀。Unsafe path時source bytes不變且working copy不建立；合法E2E時source不變、working copy明確created/written。

- [ ] **Step 3: 跑 CLI subprocess tests與兩次 smoke**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_rehearsal_cli.py tests/test_evidence_rehearsal_real_e2e.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\A\pytest-task-5 -o "cache_dir=$env:TEMP\technical_analysis_parallel\A\pytest-cache-task-5"
```

使用同一source建立兩個全新temp working copies，確認semantic fingerprint、artifact hashes與blockers一致；不要比較runtime timestamps造成的byte差異。

- [ ] **Step 4: 準備 implementation handoff**

依 Shared `dev` Execution Protocol 產生 `A-task-5.json`，只列本 Task 的 CLI 與測試檔並附 SHA-256；`suggested_commit_message` 為 `fix(evidence): run controlled rehearsal end to end`。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Task 6: Runbook、Truth Closeout 與完整驗證

**Files:**
- Modify: `docs/07_guides/EVIDENCE_REHEARSAL_RUNBOOK.md`
- Create: `docs/06_qa/EVIDENCE_REHEARSAL_REAL_E2E_CLOSEOUT_2026_07_13.md`
- Do not modify: central roadmap/snapshot/index files

- [ ] **Step 1: 更新 runbook 的真實 execution semantics**

明確區分projection-only與working-copy E2E；記錄source DB以`mode=ro`開啟、working-copy何時建立／寫入、五種injection如何改變輸入、report v2欄位、rollback與禁止事項。Working-copy write不等於production write。

- [ ] **Step 2: 建立 closeout evidence**

只允許 `engineering_real_e2e_complete`；逐條列出仍 pending 的 forward、paper、license、source acceptance、scheduler與ML promotion。

- [ ] **Step 3: 執行 focused 與 boundary verification**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evidence_rehearsal_*.py tests/test_historical_evidence_replay.py tests/test_artifact_lineage_verifier.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\A\pytest-acceptance -o "cache_dir=$env:TEMP\technical_analysis_parallel\A\pytest-cache-acceptance"
.\.venv\Scripts\python.exe -m mypy app_module/evidence_rehearsal_dtos.py app_module/evidence_rehearsal_source_reader.py app_module/evidence_rehearsal_lineage_adapter.py app_module/evidence_rehearsal_orchestrator.py app_module/evidence_rehearsal_fault_injection.py scripts/run_evidence_rehearsal.py
.\.venv\Scripts\python.exe scripts/quant_guard_linter.py
.\.venv\Scripts\python.exe scripts/check_ml_shadow_boundary.py
git diff --check -- scripts/run_evidence_rehearsal.py app_module/evidence_rehearsal_dtos.py app_module/evidence_rehearsal_source_reader.py app_module/evidence_rehearsal_lineage_adapter.py app_module/evidence_rehearsal_orchestrator.py app_module/evidence_rehearsal_fault_injection.py docs/07_guides/EVIDENCE_REHEARSAL_RUNBOOK.md docs/06_qa/EVIDENCE_REHEARSAL_REAL_E2E_CLOSEOUT_2026_07_13.md
```

- [ ] **Step 4: 核對 Git 排除**

確認 temp DB、reports、logs、cache與 `output/qa` 未 stage。

- [ ] **Step 5: 準備 docs handoff**

依 Shared `dev` Execution Protocol 產生 `A-task-6.json`，只列 runbook 與 closeout 文件並附 SHA-256；`suggested_commit_message` 為 `docs(evidence): close real rehearsal e2e engineering`。交付後停止修改此 slice，等待 Git Coordinator 確認。

## Completion Gate

- [ ] CLI 確實開啟 source DB且 bytes不變。
- [ ] Scenario／replay date mismatch fail closed。
- [ ] ML status由 real manifest／boundary／prediction計算，不能由任意 JSON繞過。
- [ ] 實際存在的artifact DAG／hash／lineage status出現在report v2；不存在的stage保持missing，report可合法degraded。
- [ ] 五種 failure通過真實 reader／adapter／boundary detector。
- [ ] 13個P0 source缺資料仍可見且 eligibility不提升。
- [ ] E2E建立並寫入隔離working copy，source與production DB保持零寫入。
- [ ] Workbench接線留給 G；本流沒有修改 UI或中央 SSOT。
