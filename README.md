# baldr

baldr 是一套台股研究與投資決策工作台。它把資料更新、市場探索、推薦分析、策略回測、觀察清單、持倉追蹤與證據覆盤整合成可追溯的研究流程，協助你用一致的資料與規則完成判讀。

目前 `main` 提供可穩定使用的**唯讀研究版**：可以進行資料更新、研究、回測、人工覆盤與證據檢視；不會自動下單、修改策略生命週期或啟用 production evidence scheduler。

目前開發狀態是 `V3.3 Engineering Complete / V4 Evidence Accumulation`，整體 readiness
仍為 `action_required`，不是正式 V4.0 Production。七個 lane 的完成／缺口與推進順序見
[2026-08-29 程式現況重估](docs/06_qa/PROGRAM_STATUS_REBASELINE_2026_08_29.md)。

> baldr 不提供獲利保證，也不把回測或歷史重播視為實盤績效。所有推薦、風險提示與研究結果都必須連同資料品質、可得日、交易成本、成交限制與樣本量一併判讀。

## 這套工具能做什麼

- 更新並檢查台股市場資料與本機 SQLite 狀態。
- 從市場廣度、強弱、產業、相對強度、流動性與籌碼資訊探索市場。
- 以 Recommendation Profile 產生候選清單，查看 Why、Why Not 與資料限制。
- 以單股、批次、固定組合或推薦組合執行研究型回測與 walk-forward 比較。
- 追蹤觀察清單與持倉的價格、條件、風險提示、來源與生命週期審核資訊。
- 在「決策工作台」集中查看每日待判讀項目、Evidence、人工待處理事項與操作節奏。
- 以 V3.0 evidence tooling 檢查訊號、警示、排除條件與分數區間的歷史 forward outcome；結果會保留樣本不足與資料品質揭露。

## 開始前準備

### 1. 安裝環境

請先安裝 Python，然後在專案根目錄執行：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 設定資料位置

baldr 預設使用的資料根目錄由 `data_module/config.py` 的 `TWStockConfig` 管理，通常為：

```text
D:/Min/Python/Project/FA_Data
```

若你的資料放在其他位置，請在啟動前設定環境變數：

```powershell
$env:DATA_ROOT = "D:\your\baldr-data"
$env:OUTPUT_ROOT = "D:\your\baldr-data\output"
```

資料目錄包含 SQLite、CSV、輸出報告與執行紀錄。請先確認該位置具有可用磁碟空間，並避免與其他程式同時大量寫入同一份資料庫。

### 3. 啟動應用程式

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

首次使用時，先進入「數據更新」確認資料來源、日期與診斷訊息，再開始研究流程。

## 建議的日常使用流程

1. 在「數據更新」更新資料並確認沒有 blocking diagnostics。
2. 到「決策工作台」閱讀今日待判讀、資料品質、Evidence 與人工待處理項目。
3. 在「市場探索」了解大盤、產業、相對強弱、流動性與籌碼背景。
4. 在「推薦分析」建立或選擇 Profile，閱讀候選的 Why、Why Not、流動性與資料限制。
5. 需要驗證假設時，前往「策略回測」或 Research Lab 使用固定規則、成本假設與 out-of-sample 設定進行比較。
6. 將你要持續追蹤的標的放入「觀察清單」；已有持倉則在「持倉管理」檢查條件、風險提示與來源追溯。
7. 定期回到「Evidence」與覆盤畫面，比對 forward outcome、資料缺口與人工決策紀錄；不要以單次結果調整策略或判定有效性。

## 工作區導覽

| 工作區 | 適合何時使用 |
|---|---|
| 決策工作台 | 每日開場：集中查看待判讀事項、Evidence、持倉追蹤與操作節奏。 |
| 市場探索 | 先理解市場與產業背景，再進一步研究個股。 |
| 推薦分析 | 建立候選清單並檢視 Why、Why Not、風險與資料品質。 |
| 策略回測 | 驗證規則與假設；結果屬研究證據，不是交易指令。 |
| 觀察清單 | 管理需要持續觀察的標的與觸發條件。 |
| 持倉管理 | 追蹤已記錄持倉、風險提示、來源與生命週期審核資訊。 |
| 數據更新 | 更新市場資料、檢查資料新鮮度與處理診斷。 |
| Runtime | 檢視系統的唯讀治理與執行狀態。 |

## 如何解讀結果

- `OBSERVED` 代表資料可直接觀測；`DEGRADED`、`MISSING` 或 warning 代表資料有限制，不能當作完整結論。
- 樣本不足、未成熟的 forward outcome、缺少產業 benchmark 或舊 payload 缺口，會在 evidence 結果中明確揭露；它們不是通過 gate 的訊號。
- 推薦分數與回測指標只能用於研究比較。請一併考量資料可得日、滑價、交易成本、流動性、處置／交易限制與 out-of-sample 證據。
- V3.0 的 score effectiveness、threshold robustness 與 component ablation 工具是唯讀診斷；不會自動調整分數、門檻、組合、生命週期或下單行為。

## 安全與版本邊界

- Production evidence scheduler 目前維持關閉。
- 不提供自動下單、券商串接、AI 自動升降級策略或自動修改投資組合。
- V3.3 工程底座已完成並可供研究使用；P0 接受、Evidence formal credit、Paper 真實 fills／成本、Formal inputs 與 production canary 仍未 closeout，因此不代表投資有效性或 V4.0 成熟度。
- 請先備份你的資料根目錄，再進行任何明確會寫入資料庫的更新或維護操作。

## 需要更完整的操作說明？

- [完整應用手冊](docs/07_guides/APPLICATION_MANUAL.md)：每個工作區的入口、步驟、參數、結果判讀、安全限制與排錯。
- [目前狀態](docs/00_core/PROJECT_SNAPSHOT.md)：現有能力與已知限制。
- [完整程式盤點](docs/06_qa/PROGRAM_STATUS_REBASELINE_2026_08_29.md)：七個 readiness lane、真正缺口與下一步。
- [ML 儲存清理紀錄](docs/06_qa/ML_RELEASE_V4_STORAGE_RETENTION_CLEANUP_2026_08_29.md)：2026-08-29 retention 行為、保留鏈與不可逆邊界。
- [V2.1–V4.0 版本路線](docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md)：長期成熟度與 gate 說明。
- [疑難排解與資料治理](docs/07_guides/APPLICATION_MANUAL.md)：資料位置、診斷訊息與安全限制。

## 開發與協作

一般使用者不需要閱讀內部工程文件。若你要參與開發，請使用 `dev` 分支，並先閱讀 [AGENTS.md](AGENTS.md)、[AGENT_CONTEXT.md](AGENT_CONTEXT.md) 與 [專案導航](PROJECT_NAVIGATION.md)。

`main` 是可安裝、可啟動、可研究的穩定入口；`dev` 是日常開發主線。
