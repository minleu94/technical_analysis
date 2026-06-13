# Strategy & Scoring Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留既有 fixed 策略結果的前提下，分兩個增量加入回測歷史分位數門檻，以及推薦橫斷面百分位排名。

**Architecture:** `ScoringEngine` 繼續只計算單股分數。增量 A 在 `decision_module` 新增時間序列門檻元件，三個 executor 共用；增量 B 新增橫斷面排名元件，由 `RecommendationService` 在所有 eligible 股票評分完成後統一呼叫。兩者不共用樣本母體，但共用整數分數量化規則。

**Tech Stack:** Python 3、pandas、Decimal、PySide6、pytest、mypy、現有 StrategySpec / DailySignalFrame / RecommendationDTO。

---

## 執行順序

- [ ] 先執行 [增量 A：回測雙模式門檻](2026-06-13-strategy-scoring-governance-a-backtest.md)。
- [ ] 完成增量 A 的 fixed 相容性、Look-ahead、UI QA 與文件 Gate。
- [ ] 再執行 [增量 B：推薦橫斷面排名](2026-06-13-strategy-scoring-governance-b-recommendation.md)。
- [ ] 完成全專案整合驗證與 Walk-forward 比較報告。

## Gate A：允許開始推薦排名

- 三個 executor 缺少 `threshold_mode` 時的 signal frame 與交易結果不變。
- quantile 第 61 個有效觀測才可產生候選條件。
- T 日門檻只使用 T-1 以前資料。
- Preset / StrategyVersion 可保存並重播新參數。
- 回測 UI 可切換 fixed / quantile，最佳化不把字串參數當數值範圍。

## Gate B：Phase 完成

- fixed 推薦排序維持舊行為。
- quantile 推薦先建 eligible universe，再排名，再套百分位門檻與 `top_n`。
- 少於最小母體時回傳明確錯誤，不降級。
- 同分股票取得相同百分位，最終順序以 `stock_code` 穩定化。
- 儲存後載入可保留排名 metadata。
- 相關 pytest、mypy、py_compile、float boundary 與 UI 強制 QA 全數通過。

## 非目標

- 不修改 `TotalScore` / `FinalScore` 公式。
- 不加入 rolling quantile。
- 不自動轉換舊策略版本。
- 不重建正式資料或 SQLite schema。
- quantile 未經 Walk-forward 驗證前不設為預設。

## 提交策略

- 每個子計畫 Task 完成測試後各自提交。
- 增量 A 建議分支：`codex/strategy-scoring-governance-a`。
- 增量 B 建議分支：`codex/strategy-scoring-governance-b`，從通過 Gate A 的提交點建立。
- Stage / commit 前重新閱讀 `docs/agents/git_exclusions.md`，只納入本 Phase 程式、測試與文件。
