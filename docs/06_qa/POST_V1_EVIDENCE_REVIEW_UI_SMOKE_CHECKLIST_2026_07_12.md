# Post-V1 Evidence Review UI Smoke Checklist（2026-07-12）

## Scope

本 checklist 用於人工驗證 Research Lab `Evidence Review` read-only UI pack。它是手動 UI smoke closeout，不會寫入 evidence DB，不會建立 scheduler，不會改 portfolio，不會自動套用任何 lifecycle action。

覆蓋範圍：

- 「前瞻證據」（Forward Evidence）tab。
- 「研究落差」（Live vs Research Gap）tab。
- 「訊號衰退」（Signal Decay）tab。
- 「決策品質」（Decision Quality）tab。
- Evidence boundary banner。
- Empty / degraded / insufficient sample states。
- No trading-language check。
- Read-only guarantee。

## Evidence Boundary Check

人工 smoke 時必須確認 UI 明確顯示或等價揭露：

```text
這是 research evidence，不是買賣建議。
Close-to-close forward return 不代表可執行實盤績效。
demote_candidate / retire_candidate 需要人工審核。
Decision Quality 是流程覆盤，不是責備使用者。
```

## Global Read-only Check

每次 smoke 都要確認：

- UI 沒有 capture / confirm / save / apply / lifecycle action button。
- UI 沒有 production scheduler、Windows Task Scheduler、cron 或 background job 入口。
- UI 沒有自動修改 portfolio position。
- UI 沒有自動修改 Strategy Lifecycle state。
- UI 沒有把 dashboard summary 包裝成買賣建議。
- UI 沒有把 close-to-close forward return 說成實盤績效。

## Manual Smoke Steps

每個 dashboard 都要檢查：

1. Tab 可開啟。
2. Filters 可操作，日期欄位可用日曆選擇器選取。
3. Summary cards 顯示。
4. Table 顯示。
5. Detail panel 顯示。
6. Empty state 清楚。
7. Degraded state 清楚。
8. Warning / quality 可見。
9. 無買賣建議語言。
10. 無自動 action button。
11. 不寫 DB。

## Dashboard-Specific Checklist

### Forward Evidence

- 可查看事件總數 / 已完成結果 / 等待中結果 / 缺失結果。
- 可查看 benchmark / industry 缺口。
- 可查看 quality / warnings。
- 樣本不足時不使用正向暗示語氣。
- Detail panel 清楚標示 return basis 與限制。

### Live vs Research Gap

- 可查看 source trace、source id、strategy version。
- 可查看 evidence event / outcome linkage 狀態。
- 可查看 portfolio mode、match confidence、attribution categories。
- 缺 source trace 或缺 evidence link 時顯示 degraded / missing，不補成中性。
- 清楚標示 research / simulated gap 不是完整實帳歸因。

### Signal Decay

- 可查看 scope type / scope id。
- 可查看 short / long sample size。
- 可查看 decay status、lifecycle candidate、confidence。
- `demote_candidate` / `retire_candidate` 僅顯示為人工覆盤候選。
- 樣本不足或缺 benchmark / live gap 時清楚顯示限制。

### Decision Quality

- 可查看 process score 與 review item status。
- 可查看 reason codes、review question、related gap / decay id。
- 清楚標示流程覆盤不是投資能力分數。
- 文案不責備使用者。
- 不提供自動 dismiss / mark reviewed / action item button。

## Manual Result Table

| Area | Step | Expected | Actual | Pass / Fail | Notes | Screenshot path optional |
|---|---|---|---|---|---|---|
| Evidence Review | Boundary banner | 顯示 research evidence / 非買賣建議 / close-to-close 限制 |  |  |  |  |
| 前瞻證據 | Tab 可開啟 | 子頁可開啟且無錯誤 |  |  |  |  |
| 前瞻證據 | Filters 可操作 | 日期日曆、event、source、symbol、group 等 controls 可操作 |  |  |  |  |
| 前瞻證據 | Summary cards | 事件總數 / 已完成 / 等待中 / 缺失等 cards 顯示 |  |  |  |  |
| 前瞻證據 | Table / detail | table 與 detail panel 顯示，空狀態清楚 |  |  |  |  |
| 研究落差 | Tab 可開啟 | 子頁可開啟且無錯誤 |  |  |  |  |
| 研究落差 | Source linkage | source trace / evidence link / match confidence 可見 |  |  |  |  |
| 研究落差 | Degraded state | 缺 source trace / evidence 時清楚標示 |  |  |  |  |
| 訊號衰退 | Tab 可開啟 | 子頁可開啟且無錯誤 |  |  |  |  |
| 訊號衰退 | Lifecycle candidate | candidate 只顯示為人工覆盤候選 |  |  |  |  |
| 訊號衰退 | Insufficient state | 樣本不足限制清楚 |  |  |  |  |
| 決策品質 | Tab 可開啟 | 子頁可開啟且無錯誤 |  |  |  |  |
| 決策品質 | Review item | reason codes / review question / status 可見 |  |  |  |  |
| 決策品質 | Non-blaming wording | 不責備使用者，不包裝成交易建議 |  |  |  |  |
| Global | Read-only | 無寫入 DB / action / scheduler 入口 |  |  |  |  |

## Closeout Rule

此 checklist 全部通過後，只代表 Evidence Review UI 可進入人工使用與多日 dry-run review；不代表 production scheduler 已啟用，不代表 alpha 成立，也不代表任何策略或事件類型有效。
