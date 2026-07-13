# ML Daily Inference／Registry／Drift／Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and the ML shadow boundary checks.

**Goal:** 載入B已凍結的shadow model artifact，使用同一feature registry／builder執行每日inference，append-only保存量化prediction，監控drift／calibration與lifecycle，任何錯誤都停止ML overlay並維持正式rule-only。

**Architecture:** `ml_module`負責artifact驗證、feature parity、inference、registry與monitoring；`scripts/`是唯一可同時import `ml_module`與中立application projection DTO的composition root。`app_module`／`runtime`不得import `ml_module`。本流不直接接Recommendation；G日後只注入已投影的shadow metadata，正式Score／ranking維持不變。

**Tech Stack:** Python 3.11、joblib／scikit-learn shadow boundary、SHA-256 manifests、SQLite explicit shadow DB、integer bp persistence、dataclasses、pytest、mypy、JSON operations report。

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

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_model_artifact_store.py -q -o addopts=
git add ml_module/model_artifact_store.py tests/test_ml_model_artifact_store.py
git commit -m "feat(ml): add hashed shadow model artifact store"
```

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

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_inference_contracts.py -q -o addopts=
git add ml_module/inference_contracts.py tests/test_ml_inference_contracts.py
git commit -m "feat(ml): define fail-closed inference contract"
```

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

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_model_prediction_registries.py -q -o addopts=
git add ml_module/model_prediction_registries.py tests/test_ml_model_prediction_registries.py
git commit -m "feat(ml): harden append-only prediction registry"
```

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

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_model_lifecycle_registry.py tests/test_ml_calibration_monitor.py tests/test_ml_drift_champion_comparison.py -q -o addopts=
git add ml_module/model_lifecycle_registry.py ml_module/drift_champion_comparison.py ml_module/calibration_monitor.py tests/test_ml_model_lifecycle_registry.py tests/test_ml_calibration_monitor.py tests/test_ml_drift_champion_comparison.py
git commit -m "feat(ml): add drift calibration and lifecycle events"
```

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

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_shadow_inference_service.py -q -o addopts=
git add ml_module/shadow_inference_service.py tests/test_ml_shadow_inference_service.py
git commit -m "feat(ml): enforce train inference feature parity"
```

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

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_shadow_inference_cli.py tests/test_ml_shadow_projection_boundary.py tests/test_ml_shadow_inference_service.py -q -o addopts=
git add app_module/ml_shadow_projection_dtos.py scripts/run_ml_shadow_inference.py scripts/inspect_ml_shadow_operations.py tests/test_ml_shadow_inference_cli.py tests/test_ml_shadow_projection_boundary.py
git commit -m "feat(ml): run daily shadow inference safely"
```

## Task 7：Candidate-only Scheduled Dry-run Wrapper

**Files:**

- Create: `scripts/scheduled/run_ml_shadow_inference_dry_run.py`
- Create: `tests/test_scheduled_ml_shadow_inference_dry_run.py`

- [ ] **Step 1: 寫no-production-scheduler RED tests**

Wrapper固定candidate／dry-run，不能接受`--production`或寫正式scheduler registry；缺explicit output立即fail。Repository runtime config不因本task改變。

- [ ] **Step 2: 實作wrapper**

只組合daily CLI request並輸出handoff artifact；`production_scheduler_allowed=false`。不要建立OS Task Scheduler job或修改runtime scheduler。

- [ ] **Step 3: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scheduled_ml_shadow_inference_dry_run.py -q -o addopts=
git add scripts/scheduled/run_ml_shadow_inference_dry_run.py tests/test_scheduled_ml_shadow_inference_dry_run.py
git commit -m "chore(ml): add candidate inference dry run wrapper"
```

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

- [ ] **Step 4: 完整驗證**

```powershell
$tests = rg --files tests | Where-Object { $_ -match 'test_ml_(model|prediction|inference|drift|calibration|artifact|lifecycle|promotion|shadow)' -or $_ -match 'test_scheduled_ml_shadow' }
.\.venv\Scripts\python.exe -m pytest $tests -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_ml_shadow_boundary.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy ml_module app_module\ml_shadow_projection_dtos.py
git diff --check
git status --short
```

對全部changed Python files執行`py_compile`。

- [ ] **Step 5: Closeout commit**

```powershell
git add docs/07_guides/ML_SHADOW_INFERENCE_OPERATIONS_RUNBOOK.md docs/06_qa/ML_SHADOW_INFERENCE_OPERATIONS_CLOSEOUT_2026_07_15.md
git commit -m "docs(ml): close shadow inference operations"
```

## Completion Gate

- [ ] 同一model/snapshot重跑idempotent；conflict／partial write fail closed。
- [ ] Persisted prediction使用integer bp，registry只存在explicit shadow DB。
- [ ] Schema/hash/model/future feature/drift錯誤都停止overlay且不影響rule path。
- [ ] Research blend只存在shadow metadata；`production_blend_alpha_bp`由contract固定為0且不可由input覆寫。
- [ ] 無`app_module`／`runtime` import `ml_module`；inference不呼叫`.fit()`。
- [ ] Lifecycle append-only、rollback simulation可重跑；scheduler與promotion仍未批准。
