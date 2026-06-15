# Month 3 Closure Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this closure task step-by-step. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 關閉 6M Roadmap Month 3 v1，確認 Factor Layer 與 Portfolio Replay 可信度已達本月接受標準，並把未實作的更細成交模型明確移到 Month 4+ / backlog，不讓文件留下互相矛盾的「仍需補齊」語氣。

**Architecture:** 不修改策略、回測、推薦或成交計算；只做 closure audit、文件同步與 regression verification。Month 3 v1 的範圍是 factor records 保存覆蓋、Research Run factor snapshot/contribution、portfolio replay credibility manifest、未成交原因、cash ledger、execution costs、lot sizing、weight exposure 與 gap risk labels。零股、買賣價差、order book/full matching 與 Gap 實際成交模型保留為後續深化，不阻塞 Month 3 v1。

**Tech Stack:** Markdown docs、pytest、py_compile、financial float boundary checker。

---

## Files

- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - 將 Month 3 Factor Layer 與 Portfolio Replay 由「待補」改為 v1 complete。
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
  - 更新 Roadmap Hub 短版 Next，將 Month 3 從 P1 active 調整為 completed / closed。
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
  - 更新 Month 3 狀態、交付物與立即待辦，避免 stale backlog 阻塞 Month 4。
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - 修正固定組合與推薦回放說明，標示 Month 3 v1 已提供的可信度揭露與仍屬未來深化的模型。
- Modify: `docs/00_core/AI_CONTEXT_PACK.md`
  - 更新外部 AI 高密度上下文，避免仍把 Month 3 描述為進行中。
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
  - 更新文件索引的目前開發狀態。
- Add: `docs/superpowers/plans/2026-06-15-month3-closure-audit.md`
  - 保留本步驟計畫與驗證紀錄。

---

### Task 1: Audit Month 3 evidence

- [x] **Step 1: Inspect roadmap and code/test evidence**

Reviewed roadmap references for Month 3, Factor Layer, Research Lab paths, Portfolio Replay, `portfolio_credibility`, `weight_exposure` and `gap_risk`.

- [x] **Step 2: Define completion boundary**

Month 3 v1 is complete when Factor Layer metadata persists across current Research Lab save paths and Portfolio Replay exposes credibility limitations. Full broker-style execution simulation remains future work.

---

### Task 2: Documentation closure

- [x] **Step 1: Update Project Snapshot**

Mark Month 3 v1 complete and move remaining execution-model depth to backlog / Month 4+.

- [x] **Step 2: Update Roadmap Hub**

Move short Next from active Month 3 implementation to Month 4 Daily Decision Desk.

- [x] **Step 3: Update 6M Engineering Roadmap**

Mark Month 3 status as closed v1 and adjust immediate todo list accordingly.

- [x] **Step 4: Update Application Manual**

Clarify fixed basket per-stock Registry save and recommendation replay credibility disclosures after Month 3 v1.

- [x] **Step 5: Update AI context and documentation index**

`AI_CONTEXT_PACK.md` and `DOCUMENTATION_INDEX.md` now describe Month 3 v1 as closed and Month 4 as the active next track.

---

### Task 3: Verification

- [x] **Step 1: Run Factor Layer regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_factor_service_research_run.py tests\test_research_run_service.py tests\test_backtest_factor_metadata.py tests\test_batch_backtest_research_run_save.py tests\test_ui_qt_research_run_save.py -q -o addopts=
```

- [x] **Step 2: Run Portfolio Replay regression**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_recommendation_portfolio_backtest.py tests\test_recommendation_portfolio_numeric_governance.py -q -o addopts=
```

- [x] **Step 3: Run syntax and numeric governance checks**

```powershell
.\.venv\Scripts\python.exe -m py_compile app_module\research_run_service.py app_module\batch_backtest_service.py app_module\backtest_service.py app_module\recommendation_portfolio_backtest_service.py
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

- [x] **Step 4: Inspect final diff**

```powershell
git status --short
git diff -- docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\DEVELOPMENT_ROADMAP.md docs\00_core\ROADMAP_6M_ENGINEERING.md docs\00_core\AI_CONTEXT_PACK.md docs\00_core\DOCUMENTATION_INDEX.md docs\07_guides\APPLICATION_MANUAL.md docs\superpowers\plans\2026-06-15-month3-closure-audit.md
```

Expected: only planned docs and closure plan changed.

---

## Rollback Checklist

| File | Change type | Rollback method | Risk |
|---|---|---|---|
| `docs/00_core/PROJECT_SNAPSHOT.md` | Modify | `git checkout HEAD -- docs/00_core/PROJECT_SNAPSHOT.md` | Low |
| `docs/00_core/DEVELOPMENT_ROADMAP.md` | Modify | `git checkout HEAD -- docs/00_core/DEVELOPMENT_ROADMAP.md` | Low |
| `docs/00_core/ROADMAP_6M_ENGINEERING.md` | Modify | `git checkout HEAD -- docs/00_core/ROADMAP_6M_ENGINEERING.md` | Low |
| `docs/07_guides/APPLICATION_MANUAL.md` | Modify | `git checkout HEAD -- docs/07_guides/APPLICATION_MANUAL.md` | Low |
| `docs/superpowers/plans/2026-06-15-month3-closure-audit.md` | Create | `Remove-Item docs\superpowers\plans\2026-06-15-month3-closure-audit.md` | Low |

## Self-Review

- Spec coverage: Closes Month 3 v1 without claiming unimplemented execution models.
- Look-ahead check: No calculation logic changed.
- Numeric governance: No new financial computation introduced.
