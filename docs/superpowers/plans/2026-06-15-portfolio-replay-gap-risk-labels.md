# Portfolio Replay Gap Risk Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在推薦組合回放結果中加入可追溯的 Gap 風險標記，讓同日收盤成交假設之外的隔日開盤跳空風險可被讀取與保存。

**Architecture:** 不改變成交價、PnL、cash ledger 或 sizing；只在 result `details["gap_risk"]` 中揭露 entry close 到下一個可用 open 的 gap。若歷史資料沒有「開盤價」欄位或沒有下一筆交易日，保守輸出空紀錄並在 `portfolio_credibility.gap_risk` 中標示 partial policy。

**Tech Stack:** Python、pytest、Decimal financial units、RecommendationPortfolioBacktestService、Markdown docs。

---

## Files

- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 新增 `_build_gap_risk_manifest()`，以 holding entry date 後的下一筆同股資料「開盤價」計算 gap。
  - 在 no-holdings 與 normal result path 都輸出 `details["gap_risk"]`。
  - 在 `portfolio_credibility` 新增 `gap_risk` 區塊。
- Modify: `tests/test_recommendation_portfolio_backtest.py`
  - 新增 failing test，驗證 next-open gap 風險標記。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - 更新 Month 3 Portfolio Replay 狀態，標示 Gap risk labels 已可追溯。
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - 更新 Month 3 狀態、交付物與待辦，將 Gap 風險從完全缺口改為 partial label。
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - 補充 `gap_risk` 的判讀方式與限制。

---

### Task 1: RED - Gap risk manifest records next-open gap

- [x] **Step 1: Add failing test**

新增 `test_portfolio_backtest_records_next_open_gap_risk_labels()`，建立含「開盤價」的歷史資料，驗證 `details["gap_risk"]` 會輸出 next-open gap record。

- [x] **Step 2: Verify RED**

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_next_open_gap_risk_labels -q -o addopts=
```

Result: FAIL with `KeyError: 'gap_risk'`。

---

### Task 2: GREEN - Build gap risk labels without changing replay math

- [x] **Step 1: Add `gap_risk` details in both return paths**

No-holdings 與 normal result path 都會建立 `gap_risk` manifest 並放進 `details`。

- [x] **Step 2: Add helper methods**

新增 `_build_gap_risk_manifest()`、`_quantize_ratio()`、`_gap_direction()` 與 `_gap_severity()`；所有金融比例計算使用 Decimal，float 只出現在 DTO/details 邊界。

- [x] **Step 3: Add credibility block**

`portfolio_credibility["gap_risk"]` 標示 `supported = "partial"` 與 `next_open_gap_labels_when_open_price_available` policy。

- [x] **Step 4: Verify GREEN**

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_records_next_open_gap_risk_labels tests\test_recommendation_portfolio_backtest.py::test_portfolio_backtest_result_includes_credibility_manifest -q -o addopts=
```

Result: PASS。

---

### Task 3: Documentation sync

- [x] **Step 1: Update Snapshot**

`PROJECT_SNAPSHOT.md` 已說明 recommendation portfolio replay 在 next-open data 可用時輸出 `gap_risk` labels。

- [x] **Step 2: Update 6M Roadmap**

`ROADMAP_6M_ENGINEERING.md` 已將 Gap 從 missing model 調整為 partial risk label，並保留 odd-lot、spread、full matching 與 Gap 實際成交模型為後續工作。

- [x] **Step 3: Update Manual**

`APPLICATION_MANUAL.md` 已補充 `gap_risk.records`、`gap_pct`、`gap_direction`、`severity`，並說明 replay PnL 仍採同日收盤成交假設。

---

### Task 4: Final verification and commit

- [x] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
```

- [x] **Step 2: Run py_compile**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py
```

- [x] **Step 3: Run financial numeric boundary check**

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

- [x] **Step 4: Inspect git diff and stage only planned files**

```powershell
git status --short
git diff -- app_module\recommendation_portfolio_backtest_service.py tests\test_recommendation_portfolio_backtest.py docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\07_guides\APPLICATION_MANUAL.md docs\superpowers\plans\2026-06-15-portfolio-replay-gap-risk-labels.md
```

Expected: only planned files changed.

---

## Rollback Checklist

| File | Change type | Rollback method | Risk |
|---|---|---|---|
| `app_module/recommendation_portfolio_backtest_service.py` | Modify | `git checkout HEAD -- app_module/recommendation_portfolio_backtest_service.py` | Medium; removes gap labels only |
| `tests/test_recommendation_portfolio_backtest.py` | Modify | `git checkout HEAD -- tests/test_recommendation_portfolio_backtest.py` | Low |
| `docs/00_core/PROJECT_SNAPSHOT.md` | Modify | `git checkout HEAD -- docs/00_core/PROJECT_SNAPSHOT.md` | Low |
| `docs/00_core/ROADMAP_6M_ENGINEERING.md` | Modify | `git checkout HEAD -- docs/00_core/ROADMAP_6M_ENGINEERING.md` | Low |
| `docs/07_guides/APPLICATION_MANUAL.md` | Modify | `git checkout HEAD -- docs/07_guides/APPLICATION_MANUAL.md` | Low |
| `docs/superpowers/plans/2026-06-15-portfolio-replay-gap-risk-labels.md` | Create | `Remove-Item docs\superpowers\plans\2026-06-15-portfolio-replay-gap-risk-labels.md` | Low |

## Self-Review

- Spec coverage: Adds Gap risk labels without changing replay execution math or claiming full matching.
- Placeholder scan: No TBD / TODO / implement later placeholders.
- Type consistency: `gap_risk` is a details manifest; `portfolio_credibility.gap_risk` describes policy.
