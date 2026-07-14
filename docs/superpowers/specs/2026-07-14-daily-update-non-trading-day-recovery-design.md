# 每日資料更新：無資料日恢復設計

## 目標

避免上游 TWSE 對非交易日或尚無資料日期回覆「查無資料」時，中斷每日快速更新、TPEX 補齊、SQLite 同步與技術指標增量更新；同時讓 UI 與 Windows 排程明確揭露真正失敗與資料不完整狀態。

## 問題與根因

`UpdateService.update_daily()` 會將工作日中缺少 TWSE raw CSV 的日期交給批次下載器。下載器把上游「沒有符合條件的資料」視為失敗。只要範圍內有一日失敗，快速更新協調器便停止，未執行 TPEX、SQLite、合併資料及技術指標步驟。因此即使其他日期已可下載，UI 的 SQLite-first 狀態仍停留在舊日期。

## 設計

### 1. 下載結果契約

批次每日下載應區分三種結果：

- `updated`：TWSE raw CSV 已成功寫入。
- `skipped_no_data`：TWSE 明確回覆查無資料；此日期不視為下載錯誤。
- `failed`：網路、解析、格式或其他未預期錯誤。

`skipped_no_data` 要保留日期與原因，供上層 status 與 UI 顯示；它不會使整體 `success` 變成 `false`。

### 2. 快速更新流程

`UpdateService.update_daily()` 解析批次輸出時，將無資料日放入 `skipped_dates`，只有 `failed_dates` 會使 TWSE 步驟失敗。如此一來，無資料日後仍可繼續執行 TPEX 更新、SQLite 同步、每日整合與技術指標計算。

TPEX 若真正缺檔或更新失敗，仍保留既有 `passed_with_warnings`／`failed` 的安全語意；不得把未完整資料宣告為完整。

### 3. 可見診斷

排程 `latest_status.json` 必須保存 TWSE `skipped_dates`，並以可讀訊息標示「上游查無資料，已跳過」。UI 快速更新的完成訊息沿用相同結果，讓使用者能辨識：

- 已完整更新；
- 有無資料日被安全跳過，但後續同步已完成；
- 有真正失敗，資料可能未完整。

### 4. Freshness 判讀

資料新鮮度檢查需將「近期交易日缺漏」呈現為 warning 或 degraded，而不是僅以曆日差距小於七天判定 passed。無資料日不會被誤報為缺漏；實際可交易日原始資料或 SQLite 落後則必須可見。

## 測試

新增回歸測試覆蓋：

1. 解析器遇到上游查無資料時，回傳 `skipped_dates` 且不標記失敗。
2. 快速更新遇到無資料日時，繼續執行後續資料來源與同步步驟。
3. 真正下載錯誤仍會阻斷流程並維持失敗狀態。
4. freshness 對近期交易日缺漏不再靜默通過。

測試不得呼叫真實資料來源或修改正式 `DATA_ROOT`。

## 文件

更新每日資料更新指南與完整操作手冊，說明無資料日、`passed_with_warnings`／`failed` 的結果判讀及排錯入口。

## 非目標

- 不修改歷史正式資料檔。
- 不執行回補或重建正式資料。
- 不變更投資策略、推薦、下單或 evidence write-mode 邊界。
