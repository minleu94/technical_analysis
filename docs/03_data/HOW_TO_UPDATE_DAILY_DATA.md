# 每日資料更新操作指南

> 日常使用優先從 PySide6 UI 的「數據更新」工作區執行。
> 完整 UI 說明見 [APPLICATION_MANUAL.md](../07_guides/APPLICATION_MANUAL.md)。

## 1. 啟動

```powershell
.\.venv\Scripts\python.exe ui_qt\main.py
```

## 2. 日常首選：快速更新

1. 開啟「數據更新」。
2. 點擊「檢查數據狀態」。
3. 點擊「快速更新（僅 SQLite）」。
4. 等待底部日誌顯示完成。
5. 再次檢查狀態，確認每日股價與技術指標日期。

快速更新會下載近期缺失資料並直接同步 SQLite，略過大型歷史 CSV 重寫。

## 3. 完整備份：安全更新

使用「安全更新（完整 CSV + SQLite）」時，系統會保留完整 CSV 整合與 SQLite 同步流程。適合：

- 定期備份
- 資料修復後
- 需要人工檢查完整 CSV
- 確認雙軌資料一致性

## 4. 手動更新單一來源

### 每日股價

1. 選擇「每日股價」。
2. 設定結束日期與最近範圍。
3. 點擊「手動下載此資料源」。
4. 點擊「合併每日股價」。
5. 到「技術指標」執行增量更新。

### 大盤與產業

設定日期範圍後下載，並確認資料已同步至 `market_indices` 或 `industry_indices`。

### 券商分點

1. 設定日期範圍。
2. 手動下載。
3. 點擊「合併券商分點」。
4. 確認 `broker_flows` 日期與筆數。

目前 registry 已擴充至 37 個追蹤分點；資料品質使用 observed、estimated、unavailable 三態。

### 技術指標

- 增量更新：日常使用。
- 強制全量更新：只在算法變更或資料修復時使用。
- 可輸入單一股票代號限制處理範圍。

## 5. SQLite Inspector

使用「SQLite 資料檢視」可唯讀查看：

- 資料預覽
- Schema
- 股票、分點與日期篩選
- 受控筆數上限

不要把 Inspector 當成資料修改工具。

## 6. 匯出 CSV

個別資料頁的「匯出 CSV 備案」可輸出最近範圍或全部歷史，使用 UTF-8 with BOM。

## 7. 命令列替代方式

### 批量更新

```powershell
.\.venv\Scripts\python.exe scripts\batch_update_daily_data.py --start-date 2026-06-01
```

指定結束日期：

```powershell
.\.venv\Scripts\python.exe scripts\batch_update_daily_data.py --start-date 2026-06-01 --end-date 2026-06-12
```

### 單日更新

```powershell
.\.venv\Scripts\python.exe scripts\update_daily_stock_data.py --date 2026-06-12 --merge
```

### 合併既有每日檔

```powershell
.\.venv\Scripts\python.exe scripts\merge_daily_data.py
```

## 8. 注意事項

1. 日期使用 `YYYY-MM-DD`。
2. 週末與休市日沒有交易資料。
3. 手動下載不等於分析資料已可用；仍需合併與計算技術指標。
4. 不要把強制重建當成日常更新。
5. 不得刪除正式 raw 原始資料。

## 9. 排錯

### API 或網路錯誤

檢查網路、交易日與底部日誌，等待後重試缺失日期。

### 更新完成但 UI 日期未變

1. 重新檢查數據狀態。
2. 確認資料已合併至 SQLite。
3. 確認技術指標已計算。
4. 使用 SQLite Inspector 查看對應資料表。

### 詳細故障排除

見 [TROUBLESHOOTING_DAILY_UPDATE.md](TROUBLESHOOTING_DAILY_UPDATE.md) 與 [DATA_FETCHING_LOGIC.md](DATA_FETCHING_LOGIC.md)。
