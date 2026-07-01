# Post-V1 Evidence Review Dashboards Read-only UI Pack 設計

## Scope

本設計補上 Research Lab 內的 Evidence Review dashboard pack：

- Decision Quality Review Dashboard。
- Signal Decay Dashboard。
- Live vs Research Gap Dashboard。
- 共用 evidence boundary banner。

Dashboard 只讀取已保存的 evidence / review / observation read service，不建立 scheduler、不寫 evidence、不改 portfolio、不改 strategy lifecycle、不重算 scoring。

## UI Placement

採用最小侵入方案：在 Research Lab / 策略回測結果區新增 `Evidence Review` 分頁，內含四個子頁：

1. Forward Evidence
2. Live vs Research Gap
3. Signal Decay
4. Decision Quality

既有 Forward Performance view 保留，移入 Evidence Review 子頁第一個 tab。

## Read-only Boundary

- UI 只呼叫 dashboard service。
- dashboard service 只呼叫既有 read/list service method。
- UI 不直接讀 SQLite、不 import repository、不 import scoring 或 portfolio mutation flow。
- Dashboard 不呼叫 capture、save、mark reviewed、dismiss、action item 或 lifecycle apply。
- 所有 `demote_candidate` / `retire_candidate` 只呈現為人工覆盤候選。

## Evidence Boundary

畫面必須明確顯示：

- 這是 research evidence，不是買賣建議。
- Close-to-close forward return 不代表可執行實盤績效。
- 樣本不足、benchmark / industry 缺失與 data quality degraded 需要人工判讀。
- Decision Quality Review 是流程覆盤，不是投資能力分數，也不是責備使用者。

## Dashboard Contracts

Decision Quality Dashboard 顯示 process score、open / reviewed / dismissed item、warning counts、review question、reason codes、quality 與 warning breakdown。

Signal Decay Dashboard 顯示 scope、短窗 / 長窗樣本、forward excess、win rate、MAE、live gap、decay score、status、lifecycle candidate、confidence、quality 與 warnings。

Live vs Research Gap Dashboard 顯示 position source trace、portfolio mode、Research Run / strategy version linkage、evidence event / outcome linkage、gap metrics、condition / chip / regime state、attribution categories、match confidence、quality 與 warnings。

## Not Goals

- 不建立正式 scheduler。
- 不做自動 promote / demote / retire。
- 不修改持倉。
- 不宣稱 alpha。
- 不把 dashboard summary 包裝成買賣建議。
- 不把 close-to-close forward return 說成實盤績效。
