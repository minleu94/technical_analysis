# V2.1–V2.5 Versioned Delivery Master Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 V2.1–V2.5 交付拆成獨立工程 readiness 與正式 closeout commit，讓每版可驗證、可回滾並明確保留人工作業。

**Architecture:** 先建立版本事實帳本，將現有工程能力、正式 Gate 與人工作業分開；之後每個版本以自己的設計、實作、QA 與 closeout 文件交付。V3.0 只讀取前版 evidence，直到具備真實 effectiveness/pruning 決議才可正式 closeout。

**Tech Stack:** Python、PySide6、SQLite working-copy、pytest、mypy、Markdown QA artifacts。

## Global Constraints

- 工程 readiness commit 不等於正式版本 closeout。
- 權重一律整數 bp，金額一律 `Decimal`；不新增裸 `float`。
- 所有決策資料皆需 `available_date <= decision_date`。
- 不串 broker、不自動交易、不自動平倉、不自動 lifecycle action。
- 每版都要有版本說明、rollback SHA、focused tests、mypy、py_compile、financial／look-ahead guard 與 `git diff --check`。
- weekly history、P0 acceptance、paper evidence、position thesis 與 pruning 決議只能以真實人工證據完成。

---

### Task 1: V2.1 正式版本化 closeout

**Files:**
- Create: `docs/06_qa/V2_1_ENGINEERING_READINESS_2026_07_12.md`
- Create: `docs/06_qa/V2_1_FORMAL_CLOSEOUT_2026_07_12.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: 寫版本 closeout 完整性測試清單**

檢查 Advice Policy 的 promoted/locked/disclosure、最大 8 檔、Professional 分區、Workbench 唯讀與 `NO_NEW_POSITION`。

- [ ] **Step 2: 執行版本驗證**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_dtos.py tests/test_advice_policy.py tests/test_advice_composer.py tests/test_workbench_advice_contract.py tests/test_ui_qt_workbench_view.py tests/test_ui_qt_update_view_workbench.py -q -o addopts=`  
Expected: PASS。

- [ ] **Step 3: 寫 V2.1 readiness／formal closeout**

記錄功能、限制、驗證輸出、rollback SHA、人工 UI 文案 smoke 結論；不得宣稱投資有效或 broker execution。

- [ ] **Step 4: Commit**

```powershell
git add docs
git commit -m "docs(v2.1): record formal closeout"
```

### Task 2: V2.2 Engineering Readiness 與真實週期操作包

**Files:**
- Create: `docs/06_qa/V2_2_ENGINEERING_READINESS_2026_07_12.md`
- Create: `docs/07_guides/V2_2_WEEKLY_REVIEW_RUNBOOK.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: 固定三週人工紀錄格式**

每週必填：週期日期、資料 freshness、dry-run 狀態、warnings、reviewed/dismissed/follow-up、owner、working-copy DB path、`--save-history` 結果、下一步。

- [ ] **Step 2: 驗證 working-copy history 操作**

Run: `./.venv/Scripts/python.exe scripts/build_evidence_operations_weekly_review.py --help`  
Expected: 顯示 `--save-history`、`--list-history`、`--action-owner`，且不對 production DB 執行。

- [ ] **Step 3: 建立 readiness commit**

記錄目前 weekly `0/3 waiting_for_time`、multi-day `3/3 ready`、scheduler 未核准；不可建立 formal closeout。

- [ ] **Step 4: Commit**

```powershell
git add docs
git commit -m "docs(v2.2): record engineering readiness"
```

### Task 3: V2.3 P0 Data Credibility 決策包

**Files:**
- Create: `docs/06_qa/V2_3_ENGINEERING_READINESS_2026_07_12.md`
- Create: `docs/06_qa/V2_3_P0_SOURCE_ACCEPTANCE_REGISTER.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: 以 source-by-source 建立決策表**

每列固定：source id、用途、available-date、quality、license、缺失／outage policy、candidate status、人工決議、決議人、日期、downstream eligibility。

- [ ] **Step 2: 驗證 candidate boundary**

Run: `./.venv/Scripts/python.exe scripts/inspect_source_candidate_readiness.py --help`  
Expected: 僅 candidate readiness／diagnostics；不得啟用 ScoringEngine write 或 scheduler。

- [ ] **Step 3: 建立 readiness commit**

所有未決 source 標為 `requires_human_acceptance`；不可把 candidate 寫為 accepted feature。

- [ ] **Step 4: Commit**

```powershell
git add docs
git commit -m "docs(v2.3): record data readiness"
```

### Task 4: V2.4 Portfolio Coach Engineering Gap Plan

**Files:**
- Create: `docs/superpowers/specs/2026-07-12-v2-4-portfolio-coach-design.md`
- Create: `docs/06_qa/V2_4_ENGINEERING_READINESS_2026_07_12.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`

- [ ] **Step 1: 寫 Gap Matrix**

比較現有 `portfolio_construction_service.py` sandbox 與 V2.4 所需 risk budget、Equal Weight、target/current/gap、bands、paper portfolio、execution feasibility。

- [ ] **Step 2: 定義不可自動完成的人工作業**

列出 paper portfolio 週期、成本後比較、risk policy owner 與交易／持倉輸入來源；不把 virtual trace 當 paper evidence。

- [ ] **Step 3: Commit**

```powershell
git add docs
git commit -m "docs(v2.4): define portfolio readiness"
```

### Task 5: V2.5 Position Health Engineering Gap Plan

**Files:**
- Create: `docs/superpowers/specs/2026-07-12-v2-5-position-health-design.md`
- Create: `docs/06_qa/V2_5_ENGINEERING_READINESS_2026_07_12.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`

- [ ] **Step 1: 寫 health contract matrix**

固定 thesis、invalidation、horizon、review date、HEALTHY/WATCH/REDUCE_CANDIDATE/EXIT_CANDIDATE/CLOSED、reason category、override 與 source trace。

- [ ] **Step 2: 比對現有 Portfolio／Lifecycle**

只盤點 `portfolio_review_service.py`、`strategy_lifecycle_service.py` 與現有 journal；禁止自動平倉或自動套用 lifecycle。

- [ ] **Step 3: Commit**

```powershell
git add docs
git commit -m "docs(v2.5): define position health readiness"
```

### Task 6: V3.0 前置 Evidence／Pruning Gate

**Files:**
- Create: `docs/06_qa/V3_0_PRE_CLOSEOUT_EVIDENCE_REGISTER.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`

- [ ] **Step 1: 將既有 V3 engineering candidate 分類**

每項標示為 read-only scaffold、manual validation pending 或 formal evidence；不得使用 `V3.0 complete`。

- [ ] **Step 2: 定義 pruning 決議紀錄格式**

每項 score/component/gate/alert/Profile 要有 sample、regime、quality、decision、fallback、rollback、human owner。

- [ ] **Step 3: Commit**

```powershell
git add docs
git commit -m "docs(v3.0): record pre-closeout evidence"
```

