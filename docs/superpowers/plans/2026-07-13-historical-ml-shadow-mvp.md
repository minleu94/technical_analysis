# Historical ML Shadow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development` to implement this plan task-by-task.

**Goal:** 以 2024 年（含）以前的 PIT-safe 價量、技術、市場與產業資料建立可重現 dataset、trading-calendar purged walk-forward、linear／HGB shadow challengers，最後對 2025 執行一次 locked OOS。

**Architecture:** `data_module` 提供唯讀、批次歷史 snapshot；`ml_module` 擁有 feature／label registries、dataset freeze、split、training、calibration與evaluation。第一版只做 `core_long_history`；broker 是獨立 short-history add-on；fundamental只建立 eligibility gate。所有產物是 shadow research artifact，正式 Score／Recommendation／Advice完全不變。

**Tech Stack:** Python 3.11、SQLite URI `mode=ro`、dataclasses、Decimal／integer bp persistence、NumPy／pandas／scikit-learn只在 `ml_module` analytics boundary、pytest、mypy、JSON manifests。

## Frozen Boundaries

- 決策日 `T` 的 feature cutoff固定為前一交易日 `T-1`；不得使用 `T` 日收盤後才知道的值。
- Label可使用未來outcome，但只有horizon成熟且`label.available_date <= training_as_of`才能fit／evaluate。2025 locked OOS的final fit將`training_as_of`固定為`2024-12-31`，因此late-2024但2025才成熟的label不得進final fit。
- 2015～2024 採 expanding purged walk-forward；2025 是 locked OOS，不得 random split／shuffle。
- 看過 2025 結果後不得回頭改 feature、universe、label、threshold或hyperparameter；任何新設計必須建立新 research generation，且2025不再被稱為 untouched OOS。
- 2026只可讓late-2025 labels成熟以完成2025 OOS evaluation；這些outcome不得進final fit、2025 feature、model selection或tuning。
- Universe由每個 decision date當時存在且有足夠歷史的symbol建立，禁止以今日存活清單回填。
- Core model只用 price／technical／market／industry。Fundamental在E2修復前完全排除；broker缺值不得補0。
- ML output固定 `shadow_only=true`、`production_action_allowed=false`；不修改 ScoringEngine、rule weights、排序、Advice、Portfolio、scheduler或交易。
- `ml_module`內模型矩陣可用float；跨出analytics boundary前須量化為integer bp或中立DTO。

## Ownership

**Modify:**

- `ml_module/dataset_manifest.py`
- `ml_module/purged_walk_forward.py`
- `ml_module/boosted_challengers.py`（僅必要相容擴充）

**Create:**

- `data_module/ml_historical_snapshot_provider.py`
- `ml_module/historical_contracts.py`
- `ml_module/feature_registry.py`
- `ml_module/label_registry.py`
- `ml_module/historical_feature_builder.py`
- `ml_module/historical_label_builder.py`
- `ml_module/historical_dataset_builder.py`
- `ml_module/linear_challengers.py`
- `ml_module/historical_training_service.py`
- `ml_module/historical_evaluation.py`
- `ml_module/broker_addon_dataset.py`
- `ml_module/model_artifact_manifest.py`
- `ml_module/historical_run_report.py`
- `scripts/build_ml_historical_dataset.py`
- `scripts/train_ml_shadow_challengers.py`
- `scripts/evaluate_ml_2025_oos.py`
- matching `tests/test_ml_*.py`
- `docs/07_guides/HISTORICAL_ML_SHADOW_RUNBOOK.md`
- `docs/06_qa/HISTORICAL_ML_SHADOW_MVP_CLOSEOUT_2026_07_15.md`

**Must not modify:**

- `ml_module/model_prediction_registries.py`（F owns）
- `data_module/monthly_revenue_*`、fundamental availability／corporate-action repair（E2 owns）
- `decision_module/scoring_engine.py`
- `app_module/recommendation_service.py`
- `runtime/**`
- central Snapshot／Roadmap／Architecture／Manual files

---

## Task 1：凍結 Feature／Label／Universe Contracts

**Files:**

- Create: `ml_module/historical_contracts.py`
- Create: `ml_module/feature_registry.py`
- Create: `ml_module/label_registry.py`
- Test: `tests/test_ml_historical_contracts.py`
- Test: `tests/test_ml_feature_label_registries.py`

- [ ] **Step 1: 寫 decision timing RED tests**

測試 `decision_date=T` 時，任何 `feature_as_of_date >= T` 都被拒絕；same-day close即使 `available_date=T` 也不可進本模型。

- [ ] **Step 2: 寫 registry hash／immutability RED tests**

Feature與label canonical order、unit、dtype、missing policy、availability policy任一變動都要改 registry hash；相同內容的hash需 deterministic。

- [ ] **Step 3: 定義核心契約**

至少包含：`HistoricalUniversePolicy`、`HistoricalFeatureSpec`、`HistoricalLabelSpec`、`HistoricalFeatureRow`、`HistoricalLabelRow`、`HistoricalDatasetRow`。Persisted financial quantities使用integer bp／amount units；missing與observed zero分開表達。

- [ ] **Step 4: 執行 GREEN tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_historical_contracts.py tests/test_ml_feature_label_registries.py -q -o addopts=
```

- [ ] **Step 5: Commit**

```powershell
git add ml_module/historical_contracts.py ml_module/feature_registry.py ml_module/label_registry.py tests/test_ml_historical_contracts.py tests/test_ml_feature_label_registries.py
git commit -m "test(ml): freeze historical feature and label contracts"
```

## Task 2：建立唯讀 Historical Snapshot Provider

**Files:**

- Create: `data_module/ml_historical_snapshot_provider.py`
- Test: `tests/test_ml_historical_snapshot_provider.py`

- [ ] **Step 1: 寫 source immutability／schema RED tests**

Assertions：SQLite URI含 `mode=ro`、連線設 `query_only=ON`、run前後source bytes／mtime不變、缺必要欄位fail closed、provider constructor不建立DB／table／log。

- [ ] **Step 2: 寫 causal batch query RED tests**

一次查日期範圍與symbol集合，不逐股N+1；`decision_date=T`只回傳截至前一交易日資料。中文格式日期或整數日期不得被誤判為epoch。

- [ ] **Step 3: 實作批次 snapshots**

提供 daily price、technical、market index、industry index與可選 broker family；metadata含 source path alias、schema fingerprint、table coverage、row counts、source stat fingerprint。不要對大型正式DB每次做全檔hash。

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_historical_snapshot_provider.py -q -o addopts=
.\.venv\Scripts\python.exe -m py_compile data_module\ml_historical_snapshot_provider.py
git diff --check
git add data_module/ml_historical_snapshot_provider.py tests/test_ml_historical_snapshot_provider.py
git commit -m "feat(ml): add read-only historical snapshot provider"
```

## Task 3：Core Causal Feature Builder

**Files:**

- Create: `ml_module/historical_feature_builder.py`
- Test: `tests/test_ml_historical_feature_builder.py`

- [ ] **Step 1: 寫 prefix-invariance RED tests**

在資料尾端增加未來rows後，既有日期feature bytes與hash必須完全不變。測試同日資料、missing values、短history與delisted symbols。

- [ ] **Step 2: 實作第一版 feature families**

使用當下可得history計算：stock return 1／5／20／60日bp、trailing volatility、high-low range、close-to-MA 5／20／60 bp、RSI／ADX／MACD normalized、volume ratio 5／20、成交額／流動性、market return 5／20／60、stock-minus-market、industry-relative return、missingness indicators。

- [ ] **Step 3: 明確缺值語意**

缺值不可補成observed 0；imputation參數只能在training fold fit，不能用全資料統計。

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_historical_feature_builder.py -q -o addopts=
git add ml_module/historical_feature_builder.py tests/test_ml_historical_feature_builder.py
git commit -m "feat(ml): build causal long-history feature snapshots"
```

## Task 4：Matured Labels 與 Corporate-action Gate

**Files:**

- Create: `ml_module/historical_label_builder.py`
- Test: `tests/test_ml_historical_label_builder.py`

- [ ] **Step 1: 寫 trading-horizon RED tests**

Primary label為20交易日stock-minus-benchmark return bp；window從feature cutoff close開始，stock與benchmark使用相同交易日期。不得以calendar timedelta找horizon。

- [ ] **Step 2: 寫 maturity／quality RED tests**

Label `available_date`等於horizon完成日；未成熟label不進fit/evaluation。Corporate-action coverage未知時：strict mode排除；rehearsal mode保留degraded與blocker，但不得標clean OOS。

- [ ] **Step 3: 實作 label families**

至少輸出20日relative return、maximum adverse excursion bp、downside flag、cross-sectional top-quintile flag。Downside threshold為顯式config／CLI參數並寫入label registry hash。

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_historical_label_builder.py -q -o addopts=
git add ml_module/historical_label_builder.py tests/test_ml_historical_label_builder.py
git commit -m "feat(ml): add matured labels and corporate-action gate"
```

## Task 5：Dataset Builder 與 Manifest v2

**Files:**

- Modify: `ml_module/dataset_manifest.py`
- Create: `ml_module/historical_dataset_builder.py`
- Create: `scripts/build_ml_historical_dataset.py`
- Test: `tests/test_ml_historical_dataset_builder.py`
- Test: `tests/test_ml_dataset_manifest_v2.py`

- [ ] **Step 1: 寫 deterministic dataset RED tests**

相同source／registry／range／universe必須產生相同dataset hash；相同dataset id不同content必須拒絕；row order不得影響canonical hash。

- [ ] **Step 2: 擴充 manifest**

包含 schema version、feature／label registry hash、universe policy、decision timing、split policy、source fingerprints、accepted/excluded diagnostics、corporate-action coverage、broker/fundamental eligibility與content hash。

- [ ] **Step 3: 實作 CLI安全模式**

正式source只讀；dataset只寫 explicit `--output-root`。若output位於`DATA_ROOT`、正式DB目錄或既有dataset id內容衝突則fail。Raw dataset／model artifacts不commit。

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_historical_dataset_builder.py tests/test_ml_dataset_manifest_v2.py -q -o addopts=
git add ml_module/dataset_manifest.py ml_module/historical_dataset_builder.py scripts/build_ml_historical_dataset.py tests/test_ml_historical_dataset_builder.py tests/test_ml_dataset_manifest_v2.py
git commit -m "feat(ml): freeze reproducible historical datasets"
```

## Task 6：統一 Trading-calendar Purged Walk-forward

**Files:**

- Modify: `ml_module/purged_walk_forward.py`
- Modify: `tests/test_ml_purged_walk_forward.py`

- [ ] **Step 1: 寫現況語意不一致 RED tests**

目前purge使用calendar timedelta、embargo使用unique-date index；建立跨週末／假日case，證明兩者都必須以同一trading-date index計數。

- [ ] **Step 2: 寫 no-leak invariants**

每fold必須滿足train label end早於test start；未來rows加入後既有fold不變；random shuffle無法啟用；fold ids與date windows deterministic。

- [ ] **Step 3: 修正 splitter並提供相容遷移**

保留既有public API可行部分；如需新參數，使用明確 `purge_trading_days`／`embargo_trading_days`並讓舊ambiguity fail with migration message。

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_purged_walk_forward.py -q -o addopts=
git add ml_module/purged_walk_forward.py tests/test_ml_purged_walk_forward.py
git commit -m "fix(ml): enforce trading-calendar purged walk-forward"
```

## Task 7：Linear／HGB Challengers、OOF Calibration

**Files:**

- Create: `ml_module/linear_challengers.py`
- Modify: `ml_module/boosted_challengers.py`
- Create: `ml_module/historical_training_service.py`
- Create: `ml_module/historical_evaluation.py`
- Test: `tests/test_ml_historical_training_service.py`
- Test: `tests/test_ml_historical_evaluation.py`

- [ ] **Step 1: 寫 fold-only preprocessing／calibration RED tests**

Scaler／imputer只fit train fold；calibration只用OOF predictions；test/OOS資料不得影響參數。

- [ ] **Step 2: 凍結research-only blend policy**

只用同時滿足`oof_decision_date <= 2024-12-31`與`oof_label_available_date <= 2024-12-31`的OOF predictions比較rule champion、ML challenger與候選`research_alpha_bp`；production alpha永遠為0。Research alpha、selection metric、selection label cutoff與threshold寫入model manifest，並在看2025前freeze。

- [ ] **Step 3: 實作 baseline優先比較**

先訓練linear／logistic baseline，再以相同fold、feature schema比較HGB。Existing rule score只作champion comparison，不當作ML feature。

- [ ] **Step 4: 實作 metrics**

至少包含 Precision@K、NDCG、bucket monotonicity、MAE bp、Brier bp、regime／liquidity stability與coverage；persistent report使用integer bp／counts。

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_historical_training_service.py tests/test_ml_historical_evaluation.py -q -o addopts=
git add ml_module/linear_challengers.py ml_module/boosted_challengers.py ml_module/historical_training_service.py ml_module/historical_evaluation.py tests/test_ml_historical_training_service.py tests/test_ml_historical_evaluation.py
git commit -m "feat(ml): train linear and boosted shadow challengers"
```

## Task 8：Freeze Model Artifact 與 2025 Locked OOS

**Files:**

- Create: `ml_module/model_artifact_manifest.py`
- Create: `ml_module/historical_run_report.py`
- Create: `scripts/train_ml_shadow_challengers.py`
- Create: `scripts/evaluate_ml_2025_oos.py`
- Test: `tests/test_ml_model_artifact_manifest.py`
- Test: `tests/test_ml_2025_locked_oos.py`

- [ ] **Step 1: 凍結producer-owned model artifact manifest**

Manifest需定義model/dataset ids、feature/label registry hashes、family、training cutoff、hyperparameters hash、library versions、serialization format、artifact hash與shadow flags。B只定義並產出contract；F的`model_artifact_store.py`負責日常load safety。

- [ ] **Step 2: 寫 freeze-before-OOS RED tests**

沒有dataset hash、feature／label registry hash、frozen hyperparameters、research blend policy與model artifact hash時不得開啟OOS。Final train rows必須assert`max(decision_date) <= 2024-12-31`、`max(label.available_date) <= 2024-12-31`且最後train label horizon早於OOS start；blend policy另必須assert`max(blend_selection_label_available_date) <= 2024-12-31`；`--confirm-locked-oos`為必要顯式旗標。

- [ ] **Step 3: 寫 append-only evaluation RED tests**

同一artifact＋2025 payload重跑idempotent；同evaluation id不同payload拒絕。任何新model／dataset hash建立新generation，report必須標記是否仍具untouched OOS資格。

- [ ] **Step 4: 實作 frozen train與OOS commands**

將`training_as_of`固定為`2024-12-31`，只用同時滿足`decision_date <= training_as_of`與`label.available_date <= training_as_of`的accepted rows重訓一次；只對2025產生prediction/evaluation artifact。2026才成熟的2025 outcomes只用於OOS評估。合法結果包含`reject`、`continue_shadow`、`shadow_candidate`；工程成功不要求模型勝過rule champion。

- [ ] **Step 5: 產生 `HistoricalMLShadowRunReport`**

至少含 run／dataset／model ids、training end、OOS range、accepted/excluded counts、fold ids、metrics bp、artifact hashes、blockers、evidence tier、shadow flags。

- [ ] **Step 6: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_model_artifact_manifest.py tests/test_ml_2025_locked_oos.py -q -o addopts=
git add ml_module/model_artifact_manifest.py ml_module/historical_run_report.py scripts/train_ml_shadow_challengers.py scripts/evaluate_ml_2025_oos.py tests/test_ml_model_artifact_manifest.py tests/test_ml_2025_locked_oos.py
git commit -m "feat(ml): add locked 2025 out-of-sample evaluation"
```

## Task 9：隔離三個 Model Families

**Files:**

- Create: `ml_module/broker_addon_dataset.py`
- Test: `tests/test_ml_broker_addon_dataset.py`

- [ ] **Step 1: Core family gate**

確認core manifest不含fundamental／broker fields。

- [ ] **Step 2: Broker add-on gate**

只使用broker真實起始日後的matched rows，獨立dataset／model ids；早期缺資料不補0。樣本／regime coverage不足輸出 `inconclusive`。

- [ ] **Step 3: Fundamental gate**

只輸出 `ineligible_pending_pit_repair`；不訓練fundamental model，不引用E2尚未accepted mapping。

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_broker_addon_dataset.py -q -o addopts=
git add ml_module/broker_addon_dataset.py tests/test_ml_broker_addon_dataset.py
git commit -m "feat(ml): isolate broker and PIT model families"
```

## Task 10：真實唯讀 Smoke、Runbook 與 Closeout

**Files:**

- Create: `docs/07_guides/HISTORICAL_ML_SHADOW_RUNBOOK.md`
- Create: `docs/06_qa/HISTORICAL_ML_SHADOW_MVP_CLOSEOUT_2026_07_15.md`

- [ ] **Step 1: 先跑 bounded正式資料 build smoke**

使用 `TWStockConfig`定位source，以 `mode=ro`建立 `<=2024` dataset到 explicit ignored `OUTPUT_ROOT/ml_shadow`；記錄rows、coverage、excluded reasons、hash，確認source stat不變。

- [ ] **Step 2: 只在contract與model已freeze後開啟2025 OOS**

保存本次command、frozen hashes、evaluation id與真實結果。不得因結果差重跑調參。

- [ ] **Step 3: 更新runbook／closeout**

明確區分 historical OOS、shadow、forward、promotion；記錄daily inference由F負責、PIT fundamentals由E2負責。

- [ ] **Step 4: 完整驗證**

```powershell
$tests = rg --files tests | Where-Object { $_ -match 'test_ml_(historical|feature|label|dataset|purged|linear|boosted|broker|2025)' }
.\.venv\Scripts\python.exe -m pytest $tests -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_ml_shadow_boundary.py
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy ml_module data_module\ml_historical_snapshot_provider.py
git diff --check
git status --short
```

- [ ] **Step 5: Commit docs**

```powershell
git add docs/07_guides/HISTORICAL_ML_SHADOW_RUNBOOK.md docs/06_qa/HISTORICAL_ML_SHADOW_MVP_CLOSEOUT_2026_07_15.md
git commit -m "docs(ml): close historical shadow MVP engineering"
```

## Completion Gate

- [ ] 真實source DB可唯讀建立`<=2024` frozen dataset，source未改。
- [ ] Purged folds使用一致交易日語意且可重現。
- [ ] 2025 locked OOS具dataset/model/evaluation hashes、coverage、blockers與evidence tier，且`max(train_label_available_date)`與`max(blend_selection_label_available_date)`都`<= 2024-12-31`。
- [ ] Core、broker、fundamental三族完全隔離。
- [ ] Model結果不論好壞都如實保存；沒有為美化OOS回頭調參。
- [ ] 正式Score／Recommendation回歸結果無差異，所有ML output保持shadow-only。
