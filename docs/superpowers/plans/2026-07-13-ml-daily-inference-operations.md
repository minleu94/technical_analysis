# ML Daily Inference／Registry／Drift／Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and the ML shadow boundary checks.

**Goal:** 載入B已凍結的shadow model artifact，使用同一feature registry／builder執行每日inference，append-only保存量化prediction，監控drift／calibration與lifecycle，任何錯誤都停止ML overlay並維持正式rule-only。

**Architecture:** `ml_module`負責artifact驗證、feature parity、inference、registry與monitoring；`scripts/`是唯一可同時import `ml_module`與中立application projection DTO的composition root。`app_module`／`runtime`不得import `ml_module`。本流不直接接Recommendation；G日後只注入已投影的shadow metadata，正式Score／ranking維持不變。

**Tech Stack:** Python 3.11、joblib／scikit-learn shadow boundary、SHA-256 manifests、SQLite explicit shadow DB、integer bp persistence、dataclasses、pytest、mypy、JSON operations report。

## Shared `dev` Execution Model

- 所有 worker 都在共享 repository 的既有 `dev` branch 工作；開始前必須以唯讀命令確認 `git rev-parse --abbrev-ref HEAD` 回傳 `dev`。若不是 `dev`，停止並通知 Git Coordinator，不得自行修正。
- 不得建立、切換或刪除 branch／worktree；不得執行 `git add`、`git commit`、`git push`、`git stash`、`git pull`、`git rebase`、`git reset`、`git revert`、`git cherry-pick` 或 `git merge`。
- Worker 只可修改本計畫 `Ownership` 中的 exclusive paths。若需要碰其他工作流或中央 SSOT 的 owned file，停止該變更並列入 blockers，不得跨 ownership 代改。
- 本工作流使用獨立暫存：`TEMP=$env:TEMP\technical_analysis_parallel\F\temp`、`TMP` 同值、`OUTPUT_ROOT=$env:TEMP\technical_analysis_parallel\F\output`，pytest 一律加 `--basetemp $env:TEMP\technical_analysis_parallel\F\pytest\<slice>` 與 `-o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\<slice>"`。Shadow model root／registry DB 必須位於此 output 下，不得共用其他 worker 的 temp、output、DB 或 pytest cache。
- Focused tests 可與其他工作流平行執行；全量 pytest、repo-wide mypy、完整 quant／ML boundary、UI QA、encoding／link audit 與其他重型 QA 只由 Coordinator 排程。Worker 不得自行啟動重型 QA 競爭共享資源。
- 每個原 commit slice 改為 implementation／handoff slice。Worker 完成 focused tests 後，必須交付 canonical fields：`workstream_id`、`slice_id`、`handoff_status: ready_for_commit`、`ready_files`、`sha256_by_file`（path → SHA-256 mapping）、`focused_test_paths`、`focused_tests_and_results`、`performance_or_data_coverage_results`、`suggested_commit_message`、`public_interfaces`、`boundary_checks_and_results`、`external_gates_unchanged: true` 與 `rollback_notes`，並附 blockers 給 Git Coordinator；不得自行 stage 或 commit。
- Handoff 送出後，worker 對該 slice 進入 `handoff_waiting`，在 Coordinator 明確確認前不得再修改該 slice 的 ready files。

## Start Dependencies

F0～F3可先用fixtures開始；F4真實feature parity與F5 smoke必須等B commit以下contracts：

- feature registry hash與canonical order／dtype／unit。
- dataset manifest v2。
- model artifact manifest／hash／family／library versions。
- shared historical feature builder load contract。
- `HistoricalMLShadowRunReport`。

如果B尚未交付，不得自行建立第二套feature transformation。

## Hard Boundaries

- Inference path永遠不能呼叫trainer `.fit()`、自動retrain或hyperparameter search。
- `app_module`／`runtime`不得import `ml_module`；現有`MLShadowBoundaryGuard`必須持續通過。
- Persisted return／rank／probability使用integer bp；float只存在`ml_module` model boundary。
- Registry要求explicit shadow DB／output root並拒絕正式DB、DATA_ROOT及resolved descendants。
- Major drift只停用shadow model／建立review event，不自動promotion或retrain。
- Recommendation、ScoringEngine、Advice、Portfolio與production scheduler不在F ownership。
- `formal_rule_unchanged=true`、`production_action_allowed=false`是每次result必要欄位。

## Ownership

**Modify:**

- `ml_module/model_prediction_registries.py`
- `ml_module/drift_champion_comparison.py`
- `ml_module/promotion_review_package.py`（僅append-only review輸出需要時）
- matching existing ML tests

**Create:**

- `ml_module/model_artifact_store.py`
- `ml_module/inference_contracts.py`
- `ml_module/shadow_inference_service.py`
- `ml_module/model_lifecycle_registry.py`
- `ml_module/calibration_monitor.py`
- `app_module/ml_shadow_projection_dtos.py`
- `scripts/run_ml_shadow_inference.py`
- `scripts/inspect_ml_shadow_operations.py`
- `scripts/scheduled/run_ml_shadow_inference_dry_run.py`
- matching `tests/test_ml_*.py`
- `docs/07_guides/ML_SHADOW_INFERENCE_OPERATIONS_RUNBOOK.md`
- `docs/06_qa/ML_SHADOW_INFERENCE_OPERATIONS_CLOSEOUT_2026_07_15.md`

**Must not modify:**

- B trainer／split／feature schema files except consuming public APIs
- `decision_module/scoring_engine.py`
- `app_module/recommendation_service.py`
- `runtime/**`
- production scheduler config
- central Snapshot／Roadmap／Architecture／Manual files

---

## Task 1：Hashed Model Artifact Store

**Files:**

- Create: `ml_module/model_artifact_store.py`
- Create: `tests/test_ml_model_artifact_store.py`

- [ ] **Step 1: 寫path／hash／schema RED tests**

拒絕uncontrolled arbitrary path、DATA_ROOT／production descendant、missing manifest、artifact hash mismatch、feature registry mismatch、wrong model family、`shadow_only=false`或library compatibility failure。

- [ ] **Step 2: 寫atomic write／partial artifact RED tests**

寫入途中失敗時不得留下可load artifact；manifest最後atomic replace。相同model id＋相同content重跑idempotent；相同id不同content拒絕。

- [ ] **Step 3: 實作save/load contract**

Manifest保存model／dataset ids、feature/label registry hashes、artifact hash、library versions、family、training cutoff、shadow flags與created run id。Load先驗manifest與hash，再deserialize。

- [ ] **Step 4: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_model_artifact_store.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f1 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f1"
```

```yaml
handoff:
  workstream_id: F
  slice_id: F1-artifact-store
  ready_files:
    - ml_module/model_artifact_store.py
    - tests/test_ml_model_artifact_store.py
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_ml_model_artifact_store.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact blocker>"
  suggested_commit_message: "feat(ml): add hashed shadow model artifact store"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

## Task 2：Fail-closed Inference Contract

**Files:**

- Create: `ml_module/inference_contracts.py`
- Create: `tests/test_ml_inference_contracts.py`

- [ ] **Step 1: 寫required identity RED tests**

Request缺model id、dataset id、decision date、feature snapshot／registry hash或source versions時拒絕；decision`T` snapshot含`T`日feature時拒絕。Result constructor／serializer收到`production_blend_alpha_bp != 0`時也必須拒絕。

- [ ] **Step 2: 定義request／result**

Result至少含prediction rows、excluded symbols、blockers、drift state、model status、artifact identities、frozen research blend alpha／shadow blend score、`production_blend_alpha_bp=0`、`formal_rule_unchanged=true`、`production_action_allowed=false`。No-model或fail-closed是合法typed result，不是假prediction。

- [ ] **Step 3: 定義prediction identity**

`prediction_id`由model/dataset/decision/symbol/feature snapshot hash決定；persisted values為return/rank/downside probability/uncertainty bp與source/model lineage。

- [ ] **Step 4: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_inference_contracts.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f2 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f2"
```

```yaml
handoff:
  workstream_id: F
  slice_id: F2-inference-contract
  ready_files:
    - ml_module/inference_contracts.py
    - tests/test_ml_inference_contracts.py
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_ml_inference_contracts.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact blocker>"
  suggested_commit_message: "feat(ml): define fail-closed inference contract"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

## Task 3：Prediction Registry v2

**Files:**

- Modify: `ml_module/model_prediction_registries.py`
- Modify: `tests/test_ml_model_prediction_registries.py`

- [ ] **Step 1: 寫explicit path／no-constructor-side-effect RED tests**

沒有explicit shadow DB path時constructor fail；拒絕production DB／DATA_ROOT descendants。Read-only inspect path不得自動create DB/table；schema init只能在explicit `initialize_shadow_registry()`發生。

- [ ] **Step 2: 寫integer persistence RED tests**

SQLite schema使用INTEGER儲存return/rank/probability/uncertainty bp；v1 reader仍可讀legacy REAL並明確量化／標legacy，不讓new writes回到REAL。

- [ ] **Step 3: 寫append-only／conflict RED tests**

相同prediction id＋payload重跑idempotent；不同payload記conflict並拒絕overwrite；batch transaction中斷不留半批。

- [ ] **Step 4: 實作migration-safe v2**

不要就地破壞production／v1 registry；在explicit shadow DB建立versioned table或migration。每筆保留model/dataset/snapshot/source hashes與created event。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_model_prediction_registries.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f3 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f3"
```

```yaml
handoff:
  workstream_id: F
  slice_id: F3-prediction-registry-v2
  ready_files:
    - ml_module/model_prediction_registries.py
    - tests/test_ml_model_prediction_registries.py
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_ml_model_prediction_registries.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact blocker>"
  suggested_commit_message: "feat(ml): harden append-only prediction registry"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

## Task 4：Lifecycle、Drift 與 Calibration

**Files:**

- Create: `ml_module/model_lifecycle_registry.py`
- Modify: `ml_module/drift_champion_comparison.py`
- Create: `ml_module/calibration_monitor.py`
- Create: `tests/test_ml_model_lifecycle_registry.py`
- Create: `tests/test_ml_calibration_monitor.py`
- Modify: matching drift tests

- [ ] **Step 1: 寫append-only lifecycle RED tests**

Events固定為 `activated_for_shadow`、`disabled`、`rollback_requested`、`superseded`與review events；不得有可靜默覆寫的active pointer。Invalid transition被拒絕並保留前狀態。

- [ ] **Step 2: 寫major drift RED test**

Major drift產生disabled／review-required event且不輸出overlay；正式rule path依舊可運作。不得觸發fit、promotion或scheduler mutation。

- [ ] **Step 3: 寫matured-only calibration RED test**

只有label available且matured的prediction/outcome pair進calibration；future／immature outcomes不改metrics。Persisted metrics使用bp／counts。

- [ ] **Step 4: 實作monitoring reports**

Drift／calibration report含model/dataset ids、window、coverage、threshold version、status、blockers與recommended human action；不自動採取正式行為。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_model_lifecycle_registry.py tests/test_ml_calibration_monitor.py tests/test_ml_drift_champion_comparison.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f4 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f4"
```

```yaml
handoff:
  workstream_id: F
  slice_id: F4-lifecycle-drift-calibration
  ready_files:
    - ml_module/model_lifecycle_registry.py
    - ml_module/drift_champion_comparison.py
    - ml_module/calibration_monitor.py
    - tests/test_ml_model_lifecycle_registry.py
    - tests/test_ml_calibration_monitor.py
    - tests/test_ml_drift_champion_comparison.py
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_ml_model_lifecycle_registry.py, tests/test_ml_calibration_monitor.py, tests/test_ml_drift_champion_comparison.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact blocker>"
  suggested_commit_message: "feat(ml): add drift calibration and lifecycle events"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

若既有drift test檔名不同，使用`rg --files tests | rg 'drift.*champion|champion.*drift'`取得真實路徑後替換命令；不得創造重複test file只為符合名稱。

## Task 5：Train／Inference Feature Parity

**Files:**

- Create: `ml_module/shadow_inference_service.py`
- Create: `tests/test_ml_shadow_inference_service.py`
- Consume: B feature registry／builder／artifact contracts

- [ ] **Step 1: 確認B dependency commit**

記錄B head SHA、feature registry hash與model manifest sample。若缺少，停止本task但可完成Tasks 1～4；不得自行發明schema。

- [ ] **Step 2: 寫parity RED tests**

Feature order、dtype、unit、registry hash、cutoff或source version任一不符都不預測；future feature fail closed；same B builder在train fixture與inference fixture產生相同snapshot hash。

- [ ] **Step 3: 實作inference service**

直接重用B feature builder／registry；不複製pandas transformations。Service只呼叫model predict／predict_proba，source code或spy test證明沒有`.fit()`。

- [ ] **Step 4: Quantize output**

在離開ML boundary前將return／rank／probability／uncertainty與research-only blend score量化為integer bp並附rounding policy；不把numpy/pandas/model object交給app layer。Research blend只能供shadow comparison，formal ranking不讀取它。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_shadow_inference_service.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f5 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f5"
```

```yaml
handoff:
  workstream_id: F
  slice_id: F5-feature-parity-inference
  ready_files:
    - ml_module/shadow_inference_service.py
    - tests/test_ml_shadow_inference_service.py
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_ml_shadow_inference_service.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact B contract blocker>"
  suggested_commit_message: "feat(ml): enforce train inference feature parity"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

## Task 6：Daily CLI、Projection DTO 與 Failure Recovery

**Files:**

- Create: `app_module/ml_shadow_projection_dtos.py`
- Create: `scripts/run_ml_shadow_inference.py`
- Create: `scripts/inspect_ml_shadow_operations.py`
- Create: `tests/test_ml_shadow_inference_cli.py`
- Create: `tests/test_ml_shadow_projection_boundary.py`

- [ ] **Step 1: 寫dependency-boundary RED test**

`app_module/ml_shadow_projection_dtos.py`只能import標準庫／neutral shared types，不能import `ml_module`。Composition script可同時import兩側並做primitive DTO projection。

- [ ] **Step 2: 寫六種真實failure tests**

Missing artifact、hash mismatch、feature schema mismatch、future feature、major drift、registry conflict與partial-write restart都走真實loader／guard／transaction；不得直接append預設success/blocker。

- [ ] **Step 3: 實作daily CLI**

要求explicit model root、shadow registry、decision date、source DB與output root；source只讀。沒有model輸出`shadow_unavailable`，不產假prediction；失敗不影響正式rule service。

- [ ] **Step 4: 實作inspect CLI**

唯讀列出model lifecycle、last prediction、drift/calibration與blockers；inspect不得建DB或改event。

- [ ] **Step 5: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_shadow_inference_cli.py tests/test_ml_shadow_projection_boundary.py tests/test_ml_shadow_inference_service.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f6 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f6"
```

```yaml
handoff:
  workstream_id: F
  slice_id: F6-daily-cli-projection-recovery
  ready_files:
    - app_module/ml_shadow_projection_dtos.py
    - scripts/run_ml_shadow_inference.py
    - scripts/inspect_ml_shadow_operations.py
    - tests/test_ml_shadow_inference_cli.py
    - tests/test_ml_shadow_projection_boundary.py
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_ml_shadow_inference_cli.py, tests/test_ml_shadow_projection_boundary.py, tests/test_ml_shadow_inference_service.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact blocker>"
  suggested_commit_message: "feat(ml): run daily shadow inference safely"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

## Task 7：Candidate-only Scheduled Dry-run Wrapper

**Files:**

- Create: `scripts/scheduled/run_ml_shadow_inference_dry_run.py`
- Create: `tests/test_scheduled_ml_shadow_inference_dry_run.py`

- [ ] **Step 1: 寫no-production-scheduler RED tests**

Wrapper固定candidate／dry-run，不能接受`--production`或寫正式scheduler registry；缺explicit output立即fail。Repository runtime config不因本task改變。

- [ ] **Step 2: 實作wrapper**

只組合daily CLI request並輸出handoff artifact；`production_scheduler_allowed=false`。不要建立OS Task Scheduler job或修改runtime scheduler。

- [ ] **Step 3: Focused verification／Git Coordinator handoff**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_ml_shadow_inference_dry_run.py -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f7 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f7"
```

```yaml
handoff:
  workstream_id: F
  slice_id: F7-candidate-scheduled-dry-run
  ready_files:
    - scripts/scheduled/run_ml_shadow_inference_dry_run.py
    - tests/test_scheduled_ml_shadow_inference_dry_run.py
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item>"
  focused_test_paths: [tests/test_scheduled_ml_shadow_inference_dry_run.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact blocker>"
  suggested_commit_message: "chore(ml): add candidate inference dry run wrapper"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

## Task 8：真實 Smoke、Rollback Simulation、Runbook／Closeout

**Files:**

- Create: `docs/07_guides/ML_SHADOW_INFERENCE_OPERATIONS_RUNBOOK.md`
- Create: `docs/06_qa/ML_SHADOW_INFERENCE_OPERATIONS_CLOSEOUT_2026_07_15.md`

- [ ] **Step 1: 真實唯讀one-date smoke**

以B frozen model／feature contracts、正式source `mode=ro`與explicit ignored shadow root跑一個decision date；保存model/snapshot/prediction hashes與accepted/excluded counts。正式source stat不變。

- [ ] **Step 2: Idempotency／rollback simulation**

同一request重跑registry row count不增加；建立rollback-requested／disabled event後overlay停止，但history仍可讀；不改正式rule path。

- [ ] **Step 3: 文件化daily／failure／review操作**

列command、input、artifact、owner、failure、rollback、completion rule與prohibited actions；明確說明Recommendation live wiring由G負責，promotion／scheduler仍pending。

- [ ] **Step 4: Worker focused verification／Coordinator heavy-QA queue**

```powershell
$tests = rg --files tests | Where-Object { $_ -match 'test_ml_(model|prediction|inference|drift|calibration|artifact|lifecycle|promotion|shadow)' -or $_ -match 'test_scheduled_ml_shadow' }
.\.venv\Scripts\python.exe -m pytest $tests -q -o addopts= --basetemp $env:TEMP\technical_analysis_parallel\F\pytest\f8 -o "cache_dir=$env:TEMP\technical_analysis_parallel\F\pytest_cache\f8"
git diff --check -- docs/07_guides/ML_SHADOW_INFERENCE_OPERATIONS_RUNBOOK.md docs/06_qa/ML_SHADOW_INFERENCE_OPERATIONS_CLOSEOUT_2026_07_15.md
git status --short  # shared dev 的 foreign dirty entries 是預期狀態；不得修改
```

Worker 對全部 changed Python files 執行 `py_compile`。以下重型 QA 只排入 Coordinator 佇列，不由 worker 執行：完整 ML shadow boundary、quant guard、repo-wide mypy、full test suite、encoding／link audit，以及任何 UI QA。

- [ ] **Step 5: Closeout Git Coordinator handoff**

```yaml
handoff:
  workstream_id: F
  slice_id: F8-smoke-rollback-runbook-closeout
  ready_files:
    - docs/07_guides/ML_SHADOW_INFERENCE_OPERATIONS_RUNBOOK.md
    - docs/06_qa/ML_SHADOW_INFERENCE_OPERATIONS_CLOSEOUT_2026_07_15.md
  sha256_by_file:
    "<path from ready_files>": "<SHA-256; repeat one entry for every ready_files item after smoke evidence>"
  focused_test_paths: [tests/test_ml_model_artifact_store.py, tests/test_ml_inference_contracts.py, tests/test_ml_model_prediction_registries.py, tests/test_ml_model_lifecycle_registry.py, tests/test_ml_calibration_monitor.py, tests/test_ml_drift_champion_comparison.py, tests/test_ml_shadow_inference_service.py, tests/test_ml_shadow_inference_cli.py, tests/test_ml_shadow_projection_boundary.py, tests/test_scheduled_ml_shadow_inference_dry_run.py]
  focused_tests_and_results: "<貼上實際命令/exit/pass摘要>"
  performance_or_data_coverage_results: "<actual result or not_applicable_with_reason>"
  blockers: "<none or exact blocker; include queued Coordinator heavy-QA status>"
  suggested_commit_message: "docs(ml): close shadow inference operations"
  public_interfaces: "<none or exact interfaces introduced/changed>"
  boundary_checks_and_results: "<actual boundary result or not_applicable>"
  external_gates_unchanged: true
  rollback_notes: "<exact revert/disable note; never a branch/commit operation>"
  handoff_status: ready_for_commit
  worker_state: handoff_waiting
```

送出 handoff 後停止修改本 slice 的 ready files，直到 Git Coordinator 明確確認。

## Completion Gate

- [ ] 同一model/snapshot重跑idempotent；conflict／partial write fail closed。
- [ ] Persisted prediction使用integer bp，registry只存在explicit shadow DB。
- [ ] Schema/hash/model/future feature/drift錯誤都停止overlay且不影響rule path。
- [ ] Research blend只存在shadow metadata；`production_blend_alpha_bp`由contract固定為0且不可由input覆寫。
- [ ] 無`app_module`／`runtime` import `ml_module`；inference不呼叫`.fit()`。
- [ ] Lifecycle append-only、rollback simulation可重跑；scheduler與promotion仍未批准。
