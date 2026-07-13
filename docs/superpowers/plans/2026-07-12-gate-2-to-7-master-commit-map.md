# Gate 2–7 Engineering Closure Master Commit Map

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以一個可獨立驗證的切片一個 commit，完成 Gate 2–7 工程閉環與人工／時間／ML 控制中心。

**Architecture:** 依資料依賴順序分成 Evidence、P0、Paper、Health、ML、Control Center 六個 plans。每個 plan 只消費前一 plan 的公開 DTO / repository / artifact，不直接讀取 UI state 或越權接 production decision path。

**Tech Stack:** Python 3.11、SQLite、PySide6 read-only view、scikit-learn / 可用 gradient boosting backend、pytest、mypy。

## Global Constraints

- 金融核心計算使用 `Decimal` 或整數 bp；ML float 只存在 `ml_module` adapter 邊界。
- 所有 feature / label / source observation 保存並檢查 `available_date <= decision_date`。
- 不修改正式資料、不啟用 production scheduler、不串 broker、不自動 promotion / lifecycle。
- 每個 task 完成 focused tests、文件同步、`git diff --check` 後獨立 commit。
- 每個 plan 邊界執行完整 pytest、mypy、financial / look-ahead guard。

---

## Commit Sequence

### Plan 0：既有前置變更拆分

- [ ] `docs(v2.2): record Week 1 evidence operation`
- [ ] `docs(v2.3): record official source evidence pass`
- [ ] `feat(v2.4): build saved-recommendation paper baseline`
- [ ] `feat(v2.5): build fail-closed position health baseline`
- [ ] `docs(v3.0): record Week 1 deferred pruning decision`
- [ ] `test(governance): align inventory and scheduler safety checks`

### Plan 1：Evidence / V3 Data Quality

- [ ] `feat(evidence): classify metric applicability by event family`
- [ ] `fix(evidence): resolve causal event-price trading date`
- [ ] `feat(evidence): expose expected outcome maturity dates`
- [ ] `feat(v3): add decision-ready effectiveness metrics`
- [ ] `feat(v3): build structured pruning decision package`

### Plan 2：P0 Source Control

- [ ] `feat(data): add versioned P0 source contract registry`
- [ ] `feat(data): add corporate-action and restriction shadow adapters`
- [ ] `feat(data): add institutional-flow shadow adapters`
- [ ] `feat(data): add credit-transaction shadow adapters`
- [ ] `feat(data): add TDCC distribution shadow adapter`
- [ ] `feat(data): add PIT revenue and financial announcement adapters`
- [ ] `feat(data): add source acceptance verifier`

### Plan 3：Paper Portfolio

- [ ] `feat(paper): add append-only snapshot repository`
- [ ] `feat(paper): add daily mark-to-market runner`
- [ ] `feat(paper): add governed rebalance evaluator`
- [ ] `feat(paper): add equal-weight benchmark ledger`
- [ ] `feat(paper): add weekly cost-adjusted report`

### Plan 4：Position Health / Exit

- [ ] `feat(health): add thesis and invalidation contract`
- [ ] `feat(health): add governed position state machine`
- [ ] `feat(health): add append-only transition repository`
- [ ] `feat(health): add exit effectiveness read model`

### Plan 5：Gate 7 ML Shadow

- [ ] `feat(ml): add frozen dataset manifest and registry`
- [ ] `feat(ml): enforce feature-label available-date boundary`
- [ ] `feat(ml): add purged walk-forward splitter`
- [ ] `feat(ml): add boosted ranking and downside challengers`
- [ ] `feat(ml): add probability calibration`
- [ ] `feat(ml): add model and shadow prediction registries`
- [ ] `feat(ml): add drift and champion comparison`
- [ ] `feat(ml): add rollback and promotion-review package`
- [ ] `test(ml): enforce shadow-only dependency boundary`

### Plan 6：Control Center / Closeout

- [ ] `feat(governance): add human and time gate registry`
- [ ] `feat(governance): add ML revalidation runbook service`
- [ ] `feat(governance): add Gate 2-7 closeout verifier`
- [ ] `feat(workbench): add read-only engineering closure dashboard`
- [ ] `docs(roadmap): close Gate 2-7 engineering program`

## Plan Boundary Verification

在 Plan 1–6 每包結束執行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -o addopts=
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime ml_module
.\.venv\Scripts\python.exe scripts\quant_guard_linter.py
git diff --check
```

Expected：pytest 0 failures、mypy 0 issues、quant guard 0 violations、diff check exit 0。

