# Antigravity Rule 10 - Development Execution

## 適用時機

使用者要求實作功能、修 Bug、調整 UI、補測試或修改程式碼時套用。

> [!NOTE]
> **職責分工與角色邊界**：
> - 「補測試檔 / 修改程式碼」屬於 Execution 職責。
> - 若任務是決定應跑哪些測試、解讀 healthcheck / pytest 結果、準備測試證據，應先使用 Testing / QA Agent，而不是 Execution Agent。

## 執行前

1. 讀 `docs/agents/antigravity/execution_agent.md`。
2. 檢查 `git status --short`，辨識既有未提交變更。
3. 確認任務範圍、相關模組與測試入口。
4. 先列出變更檔案清單、預期影響與回滾方式。

## 實作原則

- 優先遵循既有架構、命名、測試與 UI pattern。
- 不主動重構未指定範圍。
- 不修改正式資料根目錄內的原始資料。
- Recommendation Portfolio Backtest 相關工作必須使用既有 replay / date parser / service layer，不可把新 factor 直接硬塞進 UI。
- 日期欄若是台股 `YYYYMMDD` 數字格式，不可裸用 `pd.to_datetime(series)`。

## 驗證

依變更範圍執行最小但足夠的測試。若無法執行測試，必須在回覆中明確說明原因與風險。
