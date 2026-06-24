# Full App Healthcheck / Testing QA Agent 收束報告 2026-06-23

> 範圍：本文件總結非破壞式 Testing / QA Agent + Full App Healthcheck Runner 路線在 Track A-E 完成後的狀態。這是一份收束與交接文件，不是新的實作計畫。

## 目前狀態

截至 commit `7a8db37`，`docs/superpowers/plans/2026-06-23-testing-qa-agent-super-healthcheck-roadmap.md` 已完成到 E-4。

目前交付的是一層圍繞既有 Full App Healthcheck Runner 的非破壞式 QA metadata、測試路由、結果解讀與 release review 輔助能力。它沒有把 quick mode 或 full mode 轉成強制 CI / release gate。

## 已完成 Track

| Track | 狀態 | 結果 |
|---|---|---|
| A | 已完成 | 已具備結果解讀、Markdown 渲染、known issue matching、handoff recommendation 與 command advice。 |
| B | 已完成 | 已具備 candidate bridge policy、service oracle metadata 與 coverage burn-down report。 |
| C | 已完成 | 已具備 closed-loop flow model、flow diagnostics 與 known UX gap mapping。 |
| D | 已完成 | 已具備 offscreen widget check metadata、MainWindow smoke plan metadata、viewport resize evidence plan 與 high-risk dry-run dialog plan。 |
| E | 已完成 | 已具備 run history manifest、run comparison、quick mode release gate proposal 與 full mode release checklist。 |

## 現在可以安全使用什麼

- 使用 Testing / QA Agent 文件把功能請求映射到可能的測試命令、安全模式與預期證據。
- 使用 result interpreter / known issue matcher / handoff contract metadata 解釋 healthcheck output，並把失敗導向可能 owner。
- 使用 service oracle metadata 作為功能覆蓋證據，但不要把 service tests 當成 UI flow steps。
- 使用 flow diagnostics、UX gap mapping 與 coverage burn-down metadata 說明哪些功能已覆蓋、僅 oracle-only，或仍是 manual gap。
- 使用 run history manifest 與 comparison helpers，在記憶體中比較歷史 run 與候選 run 的差異。
- 使用 quick gate proposal 與 full release checklist 作為人工 review 與後續 agent 交接輔助。

## 不能誤用或誤判什麼

- Quick mode 不是正式 release gate。
- Full mode 不是正式 release gate。
- E-3 與 E-4 只是 proposal / checklist metadata；它們不啟用 CI、不修改 runner bridge，也不阻擋 release。
- MainWindow smoke、viewport resize 與 high-risk dialog 仍是 plan / metadata；除非後續有明確授權批次，否則不實作受控執行。
- Manual UX gaps、manual-only tests、write-risk tests 與 high-risk dry-run paths 不會因 quick 或 full mode 通過而自動被認證。
- Service oracle tests 是證據，不是 UI flow step。

## 下一階段選項

### 選項 1：維持 Metadata-Only

停在目前穩定邊界。Testing / QA Agent 使用這些模組回答問題、準備證據與交接工作，但不改 runner 行為。

適合優先考量低風險、易回滾、不想引入 release gate noise 的情境。

### 選項 2：加入可選報告區段

把 coverage burn-down、flow diagnostics、run comparison、quick gate proposal 或 full release checklist Markdown 做成 healthcheck output 的 opt-in report sections。

此選項仍必須維持 report-only：不啟用 CI gate、不自動 blocking、不啟動 MainWindow、不執行 dialog、不寫資料。

適合希望把既有 metadata 出現在 QA 報告中的情境。

### 選項 3：設計真正 Release Gate Roadmap

先建立新的 roadmap，再開始實作。該 roadmap 必須定義 gate scope、blocking rules、override policy、failure ownership、allowed modes、manual gaps、rollback behavior、CI / local invocation，以及如何避免 noisy 或誤導性的 release block。

只有在使用者明確要求把 healthcheck output 變成可執行 gate 時，才建議走這條路。

## 建議下一步

不要自動開始新的實作批次。

若要繼續，請先選擇以下之一：

1. 維持 metadata-only，直接作為 QA Agent 的操作知識庫使用。
2. 建立 opt-in report integration 計畫。
3. 另開真正 release gate roadmap。

最安全的下一個工程方向是選項 2，但必須維持 report-only，且需要先核准新的實作計畫。

補充：選項 2 已完成為 opt-in report-only sections，可透過 `--report-section` 將 coverage burn-down、flow diagnostics、quick gate proposal 與 full release checklist 加入 `REPORT.md` / `result.json`。未傳 `--report-section` 時預設 healthcheck output 與 runner bridge 行為不變。Run history comparison 也已支援，但必須明確提供 `--compare-baseline-manifest` 與 `--compare-candidate-manifest` 兩個 manifest JSON 路徑，才會附加 `run-history-comparison` section。

## 驗證快照

本收束報告前，E-4 最新驗證如下：

- Focused healthcheck metadata tests：`43 passed`
- Pytest collection：`1031 tests collected`
- Quick healthcheck runner：`Healthcheck passed`
- `py_compile`：E-4 相關 Python 檔通過
- `git diff --check`：無 whitespace error，只有 CRLF 提醒

## 交接規則

- 每個新批次先執行 `git status --short --branch`。
- 除非任務明確要求更新 QA 報告，否則不要 stage `output/qa/update_tab/` 底下 tracked 易變輸出。
- 除非後續任務明確授權受控 UI 執行，否則不要啟動 MainWindow。
- 不要從本 roadmap 直接執行 migration、backfill apply、真實資料寫入或 high-risk dry-run implementation。
- 若失敗涉及 SQLite / CSV 新鮮度、schema、available date 或資料完整性，交接給 Data Audit Agent。
- 若下一步會改 runner 行為或 release blocking，先建立新的明確計畫，再編輯程式碼。
