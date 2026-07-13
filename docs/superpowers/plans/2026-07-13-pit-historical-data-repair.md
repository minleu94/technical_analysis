# PIT Historical Data Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`, `superpowers:test-driven-development`, and the repository data-audit workflow.

**Goal:** 為月營收、季度財報與corporate-action／restriction建立可稽核的歷史announcement／available／revision timeline與ML label-window eligibility artifact，修正「所有歷史row在2026-06-17才可得」造成的PIT缺口，但絕不猜日期或直接改正式DB。

**Architecture:** Source adapters收集官方或可分級的availability evidence；builders建立append-only canonical mappings與coverage diagnostics；eligibility projector將mapping投影成下一版dataset可消費的feature／label gates。無可信證據的rows保持unmatched／blocked；production apply與source acceptance另需人工核准。

**Tech Stack:** Python 3.11、SQLite read-only、dataclasses、Decimal／integer units、canonical JSON／CSV staging、SHA-256 manifests、pytest、mypy、official-source evidence reports。

## Non-negotiable PIT Rules

- `2026-06-17` backfill date不是2014～2025歷史公告日。
- period end、raw CSV filename/date、filesystem mtime、FinMind `create_time`都不能自動提升為官方announcement date。
- 每筆mapping需區分 period／event date、announcement/publication、first-observed、available、revision/effective date與source version。
- revision append-only；後來版本不能覆寫當時可見的早期版本。
- 無可信歷史公告證據的row保持unmatched／blocked；retroactive baseline只能標degraded research mapping。
- Corporate-action coverage不足時，label-window eligibility fail closed或degraded，不得標clean。
- 本工作流不修改B已凍結的core dataset；只輸出future dataset generation可用artifact。
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

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_pit_historical_availability_contracts.py -q -o addopts=
git add data_module/fundamental_availability.py tests/test_pit_historical_availability_contracts.py
git commit -m "test(data): freeze PIT announcement and revision contracts"
```

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

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_monthly_revenue_availability_history.py tests/test_monthly_revenue_availability_builder.py tests/test_fundamental_availability_sources.py tests/test_p0_pit_fundamental_announcement_adapters.py -q -o addopts=
git add data_module/monthly_revenue_availability_history.py `
  data_module/monthly_revenue_availability_builder.py `
  data_module/fundamental_availability_sources.py `
  data_module/p0_pit_fundamental_announcement_adapters.py `
  tests/test_monthly_revenue_availability_history.py `
  tests/test_monthly_revenue_availability_builder.py `
  tests/test_fundamental_availability_sources.py `
  tests/test_p0_pit_fundamental_announcement_adapters.py
git diff --cached --name-only
git commit -m "feat(data): build governed monthly revenue history"
```

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

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_quarterly_statement_availability_history.py tests/test_fundamental_statement_availability_sources.py -q -o addopts=
git add data_module/quarterly_statement_availability_history.py data_module/fundamental_statement_availability_sources.py scripts/build_quarterly_statement_availability_history.py tests/test_quarterly_statement_availability_history.py tests/test_fundamental_statement_availability_sources.py
git commit -m "feat(data): add quarterly statement availability history"
```

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

- [ ] **Step 4: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_corporate_action_availability_history.py tests/test_corporate_action_policy.py tests/test_p0_corporate_restriction_shadow_adapters.py -q -o addopts=
git add data_module/corporate_action_availability_history.py data_module/corporate_action_policy.py data_module/p0_corporate_restriction_shadow_adapters.py scripts/build_corporate_action_availability_history.py tests/test_corporate_action_availability_history.py tests/test_corporate_action_policy.py tests/test_p0_corporate_restriction_shadow_adapters.py
git commit -m "feat(data): add corporate-action and restriction timelines"
```

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

- [ ] **Step 5: Verify／Commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_p0_ml_eligibility_projection.py -q -o addopts=
git add data_module/p0_ml_eligibility_projection.py scripts/project_p0_ml_eligibility.py tests/test_p0_ml_eligibility_projection.py
git commit -m "feat(data): project PIT-safe ML eligibility"
```

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

- [ ] **Step 4: 完整驗證**

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
.\.venv\Scripts\python.exe -m pytest $tests -q -o addopts=
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
.\.venv\Scripts\python.exe -m mypy data_module
git diff --check
git status --short
```

對全部changed Python files執行`py_compile`。

- [ ] **Step 5: Closeout commit**

```powershell
git add docs/07_guides/PIT_HISTORICAL_DATA_REPAIR_RUNBOOK.md docs/06_qa/PIT_HISTORICAL_DATA_REPAIR_CLOSEOUT_2026_07_15.md
git commit -m "docs(data): publish PIT repair coverage evidence"
```

## Completion Gate

- [ ] 月營收／財報／corporate action mapping皆具source/version/hash與time semantics。
- [ ] unmatched、future、duplicate、revision與coverage unknown都有typed diagnostics。
- [ ] 無證據日期沒有被猜值；正式DB與raw source未寫入。
- [ ] `p0-ml-eligibility.v1`可供下一版dataset使用，但B frozen dataset完全未改。
- [ ] Closeout如實區分engineering tooling、actual coverage、source acceptance與production apply；後三者可保持pending／limited。
