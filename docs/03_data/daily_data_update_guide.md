# 每日股票數據更新指南

## 📖 快速導航

- **快速開始** → 查看 [HOW_TO_UPDATE_DAILY_DATA.md](HOW_TO_UPDATE_DAILY_DATA.md) ⭐ 快速指南
- **批量更新（推薦）** → 查看 [批量更新](#批量更新推薦) 章節
- **單日更新** → 查看 [單日更新](#單日更新) 章節
- **合併數據** → 查看 [合併數據](#合併數據) 章節
- **遇到問題** → 查看 [問題排查](#問題排查) 章節

## 概述

本文檔說明如何使用主模組更新每日股票數據。系統已實現完整的數據更新功能，包括批量更新、單日更新和數據合併。

## 批量更新（推薦 ⭐⭐⭐）

### 使用方式

```bash
# 更新從指定日期之後到今天的所有交易日
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 更新指定日期範圍
python scripts/batch_update_daily_data.py --start-date 2025-08-28 --end-date 2025-09-05

# 自訂延遲時間（更安全，避免 API 限制）
python scripts/batch_update_daily_data.py --start-date 2025-08-28 --delay-min 4 --delay-max 4
```

### 特點

- ✅ **使用主模組**（`data_module/data_loader.py`）
- ✅ 自動更新多個交易日（排除週末）
- ✅ 已包含 delay time（預設 4 秒，可調整）
- ✅ 自動跳過已存在的文件
- ✅ 顯示詳細進度和結果摘要
- ✅ 使用 Session 和 cookie 處理（避免 307 錯誤）
- ✅ 使用成功驗證的邏輯（MI_INDEX API, type=ALL）

### 輸出範例

```
準備更新從 2025-08-28 之後到 今天 的股票數據
共 73 個交易日需要更新
延遲時間: 4 秒/次（固定）
============================================================

[1/73] 正在更新 2025-08-29 的數據...
  ✓ 2025-08-29 更新成功：1059 筆記錄
  等待 4.0 秒後繼續...

[2/73] 正在更新 2025-09-01 的數據...
  ✓ 2025-09-01 更新成功：1059 筆記錄
  等待 4.0 秒後繼續...

...

============================================================
批量更新完成！
成功: 73 天
失敗: 0 天
============================================================
注意：數據已更新到 daily_price 目錄，尚未合併到 meta_data
請檢查數據無誤後，再執行合併：python scripts/merge_daily_data.py
```

## 單日更新

### 使用方式

```bash
# 更新單日數據（只更新 daily_price）
python scripts/update_daily_stock_data.py --date 2025-08-29

# 更新並自動合併到 meta_data
python scripts/update_daily_stock_data.py --date 2025-08-29 --merge
```

### 特點

- ✅ 使用主模組方法
- ✅ 已包含 delay time（1.5-2.5 秒）
- ✅ 可選擇是否自動合併
- ✅ 統一的日誌記錄

## 合併數據

### 使用方式

```bash
# 合併所有新的 daily_price 文件到 meta_data
python scripts/merge_daily_data.py
```

### 特點

- ✅ 自動檢測新的 daily_price 文件
- ✅ 增量合併（只處理新文件）
- ✅ 真正有資料要提交時自動創建備份，且同一資料來源只保留最新 5 個日期版本；增量 no-op 不建立新備份
- ✅ 顯示合併結果統計

## 完整更新流程

### UI 安全更新（推薦）

日常維護建議優先使用 Qt UI 的「數據更新」Tab →「安全更新所有數據」。此流程預設補結束日前最近 10 個工作日，會保留既有 CSV 輸出，同時在成功步驟後補做 SQLite 同步：

1. 更新 `daily_price/YYYYMMDD.csv` 後，同步到 `daily_prices`。
2. 更新 `market_index.csv` / `industry_index.csv` 後，同步到 `market_indices` / `industry_indices`。
3. 合併 `stock_data_whole.csv` 後，再以合併結果同步 `daily_prices`。
4. 合併券商分點 `merged.csv` 後，同步到 `broker_flows`。
5. 技術指標計算完成後，同步到 `technical_indicators`。

同步方向固定為 CSV → SQLite，不會用 SQLite 反向覆蓋 CSV。若其中任一同步步驟失敗，安全更新會停止並顯示失敗步驟，避免 UI 狀態與資料庫內容繼續分岔。

快速／安全一鍵更新會先執行一次更新前資料狀態檢查；若總覽 payload 內任一核心資料源明確回報 `error`／`failed`／`exception`，流程會在任何下載、合併或 SQLite 寫入前停止，並列出失敗資料源。`lagging`、`empty`、`unavailable` 等可診斷狀態不會被誤當成寫入錯誤，但完成後仍會由最後狀態檢查判定是否成功。

UI 更新工作具單一寫入互斥：快速／安全更新、個別來源下載、CSV／SQLite 合併、技術指標計算與匯出不能重疊啟動；重複按鈕會提示目前已有背景工作，需等待完成後再重試。唯讀的來源詳情與資料狀態檢查可並行執行。進度條會把技術指標等子流程映射到外層區間並維持單調遞增；每日資料合併會顯示檔案／讀取批次／寫入批次進度，若增量掃描判定沒有新 CSV，會回傳結構化 `no_op=true` 並在 UI 顯示「資料已是最新」，不把 no-op 誤報成一般重新合併，也不會先建立整合檔備份；只有確認有新資料、即將原子提交時才建立備份；CSV 匯出會先取得查詢筆數並顯示已處理筆數，只有最後狀態刷新成功才會顯示 100%。
寫入型工作進行時，進度列下方的「取消目前工作」會送出非阻塞合作式取消。TWSE batch 會先排空目前 API 輸出，TPEX／券商分點／技術指標在日期、檔案或 SQLite 安全邊界停止；每日整合檔會在檔案讀取批次與輸出批次之間檢查取消，SQLite CSV 匯出會在資料批次之間檢查取消；已完成的寫入保留，不會強制終止 QThread。完成訊息與進度列會顯示 SQLite 同步的來源、table、筆數及失敗／取消原因，取消後應重新執行狀態檢查。

狀態卡的綠色「最新」只代表明確的 `ok`／`success`／`current`／`normal` token；`error`／`missing`／`empty`／`unavailable` 或整體檢查失敗會顯示異常，部分 payload 缺少資料源時不會沿用上一輪卡片數字。尚未執行檢查時的提示文字不會被誤當成狀態，燈號維持灰色「未檢查」而不是黃色「待更新」。localized `不可用` 也會視為異常，不會因中文 token 未命中而落到待更新。

每日股價、大盤、產業、券商分點、技術指標、月營收，以及三個候選資料源（法人／信用／集保）分頁均有唯讀 inline 狀態摘要；全域檢查會同步更新這九份摘要，個別來源失敗時只標記該來源，全域檢查失敗時則清除九份舊摘要並保留共同錯誤原因。月營收摘要另外揭露已匯入期別、目前完整 PIT 可用期別與待生效起始日。候選資料源仍是 research-only，不會因此進入正式評分或交易流程。更新頁日期控件的「今日」以台灣市場日期為準，避免作業系統時區跨日造成查詢窗口偏移。

UpdateService overview／detail 在 SQLite 缺失時會先停在 `unavailable`，存在時也只用共用 `mode=ro`／`PRAGMA query_only=ON` adapter，不會呼叫會初始化 schema 的可寫 DB manager；因此狀態檢查本身不改變資料根目錄，也不與寫入連線爭用 schema／WAL。若 Windows 外部鎖定使一般 read lock 不可用，adapter 會明確標記 `read_mode=immutable_fallback` 與提醒；這只代表最後已提交的唯讀快照，應停止其他寫入後再重查。

## TWSE 無資料日與排錯

每日股價更新會先嘗試 TWSE `MI_INDEX` 的 `ALL` 與 `ALLBUT0999` 類型。當沒有任何成功資料、至少一個查詢型別回覆已驗證的官方狀態文案「很抱歉，沒有符合條件的資料！」，且其他嘗試也只可能是同一官方文案或已確認的 HTTP 307 fallback 差異時，該日期才會列入 `no_data_skipped_dates`（同時保留在 `skipped_dates`），並以「官方無交易資料日」顯示；這不是下載失敗，後續 TPEX、SQLite 同步與技術指標仍會繼續執行。若 TWSE 回傳任何 `failed_dates`、transport／解析例外或其他 `success=false`，單一每日流程會立即停止，不呼叫 TPEX、SQLite 同步或技術指標，避免拿既有舊檔繼續產生部分寫入。

除上述 HTTP 307 fallback 外，HTTP 錯誤、逾時、連線例外、JSON／表格解析失敗，或「查詢日期大於今日」與包含「查無資料」但非官方完整文案的回覆，仍會列入 `failed_dates`，並中止後續同步，避免 UI 將不完整資料誤認為已更新。每個查詢型別的 HTTP／API／transport 診斷會保留在批次結果中。排程請查看 `OUTPUT_ROOT/scheduled/data_update_quick/latest_status.json`：`passed_with_warnings` 代表有安全跳過日或 TPEX 警告；`failed` 則應同時查看當日 `*_data_update_quick.log` 與 `errors` 欄位。

備份檔集中存放在 `meta_data/backup/`。為降低硬碟負擔，系統會在新備份成功後清理同一來源的舊備份：同一天只保留最新一份，且最多保留最新 5 個日期版本；清理範圍僅限備份目錄內「完全符合來源前綴 + 日期戳」的檔案，不會刪除正式資料，也不會讓一般 `twstock_*.db` 清掉 `twstock_fundamental_schema_*.db` 這類不同用途的標籤備份。備份來源與既有大檔清理候選見 [BACKUP_RETENTION_AUDIT_2026_07_06.md](BACKUP_RETENTION_AUDIT_2026_07_06.md)。

### CSV 欄位契約與週末交易日證據

同步 `daily_price/YYYYMMDD.csv` 前，檔案必須至少包含 `證券代號` 與 `收盤價`；像單一市場序列、指數或其他非個股格式的 CSV 會被警告並跳過，不會寫入 `daily_prices`。週末日期也不採「一律跳過」：只有 TWSE `MI_INDEX` 對該日回傳官方交易資料時才會同步；若官方查詢沒有資料、逾時或解析失敗，則 fail-closed 不寫入，並保留原始 CSV 供人工稽核。這避免把補班、特殊開市或錯置檔案用星期規則誤判。

寫入 SQLite 前，UpdateService 會把宣告過的欄位別名正規化為 canonical schema：日期接受 `日期`／`date`／`Date`／`trade_date`／`decision_date`，股票代號接受 `證券代號`／`股票代號`／`stock_code`／`stock_id`／`code`／`ticker`，股票名稱接受 `證券名稱`／`股票名稱`／`stock_name`／`name`。日期與股票代號也會統一格式；正規化只作用於寫入用副本，不會原地改寫 raw CSV 或呼叫端 DataFrame。缺少日期（且檔名無法補日期）或缺少 `證券代號`／`收盤價` 時仍會跳過並保留診斷。

若既有 SQLite 已出現空股票代號、已驗證非交易日資料或沒有 `指數名稱` 的大盤列，請使用 `scripts/repair_market_data_integrity.py` 先 dry-run；正式套用需要 `--apply --confirm apply-market-data-integrity-repair`，會先建立一份 SQLite snapshot，絕不修改 raw CSV。操作與回復步驟見 [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md#46-市場資料完整性修復受控-cli)。

### 標準流程（推薦）

```bash
# 步驟 1：批量更新每日數據（只更新 daily_price）
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 步驟 2：檢查更新結果（可選）
# 檢查文件是否正確生成

# 步驟 3：合併到 meta_data
python scripts/merge_daily_data.py
```

### 一鍵更新（自動合併）

```bash
# 單日更新並自動合併
python scripts/update_daily_stock_data.py --date 2025-08-29 --merge
```

## 文件命名格式

- **正確格式**：`YYYYMMDD.csv`（如 `20250829.csv`）
- **存儲位置**：`D:/Min/Python/Project/FA_Data/daily_price/`
- **主模組會自動轉換**：`2025-08-29` → `20250829.csv`

## 問題排查

### 問題 1：HTTP 307 錯誤

**解決方案**：
- 主模組已包含 Session 和 cookie 處理
- 如果仍然失敗，使用增強版：`python update_daily_enhanced.py --date 2025-08-29`

### 問題 2：API 返回錯誤狀態

**解決方案**：
- 檢查日期是否為交易日（週末和假日會失敗）
- 檢查日期格式是否正確（必須為 `YYYY-MM-DD`）

### 問題 3：文件命名錯誤

**解決方案**：
- 主模組已自動處理日期格式轉換
- 確認使用主模組方法（`scripts/batch_update_daily_data.py` 或 `scripts/update_daily_stock_data.py`）

### 問題 4：虛擬環境問題

**解決方案**：
- 直接使用系統 Python：`python scripts/batch_update_daily_data.py --start-date 2025-08-28`
- 不需要激活虛擬環境

## 相關文檔

- **[HOW_TO_UPDATE_DAILY_DATA.md](HOW_TO_UPDATE_DAILY_DATA.md)** - 完整更新指南
- **[DATA_FETCHING_LOGIC.md](DATA_FETCHING_LOGIC.md)** - 數據獲取邏輯詳細說明
- **[../07_guides/scripts_readme.md](../07_guides/scripts_readme.md)** - 腳本使用說明
- **[../01_architecture/data_collection_architecture.md](../01_architecture/data_collection_architecture.md)** - 數據收集架構說明

## 技術細節

### API 資訊

- **端點**：`https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX`
- **參數**：`date` (YYYYMMDD), `type=ALL`, `response=json`
- **數據位置**：`data['tables'][8]`（第9個表格）

### 延遲時間

- **批量更新**：預設 4 秒（可調整）
- **單日更新**：1.5-2.5 秒（隨機）
- **目的**：避免 API 請求過快被限制

### 數據處理

- 只保留 4 位數股票代號
- 自動處理數值欄位（移除逗號、處理 '--'）
- 從 HTML 標籤中提取漲跌符號
- 使用 `utf-8-sig` 編碼（支援 Excel 打開）

## 券商分點更新注意事項

- 新版日檔必須同時包含 `*_lots` 與 `*_amount_k_twd` 六個欄位。
- 僅有舊 `buy_qty/sell_qty/net_qty` 的檔案是 `c=B` 仟元資料，更新流程會視為待補抓。
- MoneyDJ E/B 各自是買超 50 筆與賣超 50 筆的獨立榜單；合併時採 union，不得把另一榜未出現解讀為 0。
- B-only 且有當日有效收盤價時，Smart Money 與 Portfolio Chip Monitor 可用 `Decimal + ROUND_HALF_UP` 折算估計張數，並降低信心度及顯示估算標記。
- 無有效收盤價時保持不可用，不猜測固定股價；單筆不可用事件只排除自身，不會污染同股票的其他可用事件。
- 完整重建衍生資料可執行 `merge_broker_branch_data(force_all=True)` 後同步 `broker_branch`；此流程不修改 `daily/*.csv` 原始檔。

