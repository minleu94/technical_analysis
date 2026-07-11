# Afternoon Safe Refactor Cycles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 2026-07-11 14:00–19:00 建立並啟動五輪、每輪最多兩切片的單日安全重構循環。

**Architecture:** 沿用 Codex personal automations 的 `automation.toml` cron 格式，建立 H–L 五輪共 15 個 Planner／Implementation／QA automation。每個角色只透過 ignored `output/automation/version_loop/` 與 Git commit/push 交接；最後 QA 產出 afternoon closeout。H 輪因核准時間晚於 14:00，建立後以最接近的未來分鐘啟動，其餘輪次維持每小時節奏。

**Tech Stack:** Codex personal automations TOML、RFC 5545 recurrence、Git、pytest、mypy、PowerShell。

## Global Constraints

- 僅限 2026-07-11，19:00 後不得再次觸發。
- 每輪最多兩個獨立切片，每片各自 RED／GREEN／Gate／atomic commit／push。
- 禁止 production DB/evidence write、正式資料改寫、scheduler 行為變更、交易與 lifecycle action。
- `output/automation/**` 與 `graphify-out/**` 永不 stage。
- 前輪未完成、pointer mismatch、dirty worktree 或 `dev != origin/dev` 時停止。

---

### Task 1: 同步 Git 前置狀態

**Files:**
- Verify: `docs/agents/git_exclusions.md`
- Push: commits `1856c3e`、`90bf9a2`、`3154310`

- [ ] **Step 1:** 執行 `git status --short`、`git diff --check`、`git log -3 --oneline`，確認只有三個待 push commit 且工作區乾淨。
- [ ] **Step 2:** 執行既有驗證：`pytest tests/test_update_service_status.py tests/test_scheduled_data_update_runner.py -q -o addopts=`、相關 mypy 與 quant guard。
- [ ] **Step 3:** 執行 `git push origin dev`，預期 fast-forward。
- [ ] **Step 4:** 執行 `git rev-list --left-right --count HEAD...origin/dev`，預期 `0 0`。

### Task 2: 建立 H–L 一次性 automation

**Files:**
- Create: `C:/Users/archi/.codex/automations/baldr-afternoon-refactor-{planner|implementation|qa}-{h|i|j|k|l}/automation.toml`
- Create: each automation directory `memory.md`

- [ ] **Step 1:** 以既有 master-report automation prompt 為基線，建立五個 Planner，明定最多兩片、exact files、獨立 commit 與第二片 stop conditions。
- [ ] **Step 2:** 建立五個 Implementation，明定逐片 RED／GREEN／Gate／commit／push，第一片失敗即停止第二片。
- [ ] **Step 3:** 建立五個 QA，明定逐 commit linkage 與 focused-suite union；L QA 另產生 `refactor_afternoon_closeout_20260711.*` 與 `AFTERNOON_README.md`。
- [ ] **Step 4:** recurrence 優先使用 `FREQ=DAILY;COUNT=1;BYHOUR=<H>;BYMINUTE=<M>;BYSECOND=0`；若 runtime 不接受，改為臨時 daily recurrence 並在 closeout 後設 `INACTIVE`。
- [ ] **Step 5:** H Planner 使用建立完成後最近的未來分鐘；H Implementation／QA 依序保留至少 10／35 分鐘交接窗口。

### Task 3: 驗證與啟動

**Files:**
- Inspect: all 15 new `automation.toml`

- [ ] **Step 1:** 解析全部 TOML，確認 id、name、status、model、reasoning、target、cwd 與 prompt 完整。
- [ ] **Step 2:** 確認 15 個 automation 沒有重複 id，且 recurrence 都只允許今天一次。
- [ ] **Step 3:** 核對 Codex app 已載入 automation，下一次執行時間符合 H catch-up 與 I–L 時程。
- [ ] **Step 4:** 檢查 H Planner 是否產生當日 Plan artifact；若未自動觸發，立即執行等價受控 Planner 流程，不能直接跳到 Implementation。

### Task 4: 19:00 closeout 與一次性清理

**Files:**
- Produce ignored: `output/automation/version_loop/refactor_afternoon_closeout_20260711.md/.json`
- Produce ignored: `output/automation/version_loop/AFTERNOON_README.md`
- Modify personal automation status only if `COUNT=1` was not accepted.

- [ ] **Step 1:** L QA 彙整 H–L 的 commits、tests、remediation、NO_SAFE_SLICE 與 rollback points。
- [ ] **Step 2:** 驗證 `dev == origin/dev`、工作區乾淨、quant guard 與本日下午 focused suite union。
- [ ] **Step 3:** 確認 15 個 automation 不會在 2026-07-12 再觸發；必要時全部改為 `INACTIVE`。
- [ ] **Step 4:** 產出繁體中文 closeout，明列實際完成切片數與下一輪建議。
