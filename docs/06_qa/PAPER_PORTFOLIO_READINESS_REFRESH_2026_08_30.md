# Paper Portfolio Readiness Refresh（2026-08-30）

> 本文件記錄 2026-08-30 對正式 Paper output 的唯讀盤點與一個顯示層修正；不把 snapshot、baseline、回測 trades 或手動 Portfolio 交易反推為 fills。

## 唯讀盤點

執行入口：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_paper_portfolio_readiness.py `
  --output-root D:\Min\Python\Project\FA_Data\output\paper_portfolio `
  --status-path D:\Min\Python\Project\FA_Data\output\scheduled\paper_portfolio_daily\latest_status.json `
  --state-db D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_portfolio.sqlite `
  --baseline D:\Min\Python\Project\FA_Data\output\paper_portfolio\baseline_20260712.json `
  --benchmark-db D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_equal_weight_benchmark.sqlite `
  --cost-ledger-db D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_trade_ledger.sqlite `
  --format json
```

結果：

| 項目 | 觀察 |
|---|---|
| Paper snapshot | `21` 筆，`2026-07-12..2026-08-28`，最新 `paper-main-20260828`、總值 `490950.00`、現金 `341000.00` |
| Equal Weight | `21` 筆，`2026-07-12..2026-08-28`，reader=`ready`；與 snapshot 首尾日期一致 |
| Daily status | `skipped_non_trading_day`，`decision_date=2026-08-30`、`weekend_closed`；沒有新增 snapshot 是預期行為 |
| Readiness | `partial`；`blockers=[]`，唯一警告是 `paper_trade_cost_ledger_not_configured` |
| Paper Trade Ledger | path=`D:\Min\Python\Project\FA_Data\output\paper_portfolio\paper_trade_ledger.sqlite` 不存在；fills=`0`、cost records=`0` |
| Weekly evidence | `2026-08-24..2026-08-28` 有 `5/5` snapshot／benchmark observations，但因 ledger missing 為 `not_computable` |

## 真實原因與可持續推進方式

Paper fills 是 execution event，不是可以從 snapshot 或市場行情唯一推導的數字。當前資料根目錄與 repository 的 bounded 查找沒有找到可證明為 broker／Paper execution producer 的成交檔，因此沒有建立空 ledger，也沒有把 `output\portfolio\trades.jsonl`、backtest／research parquet、virtual execution trace 或 baseline 轉入。

已建立無示例成交的匯入範本（TEMP，非正式資料）：

| Artifact | 結果 |
|---|---|
| `C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\paper_trade_handoff_20260830\paper_trade_fills_template.csv` | 只有治理欄位標題，`row_count=0` |
| SHA-256 | `sha256:0B6284E2869DA7958B4C4C0A28EBD083665F1998726DBCA257FE819068F70D96` |
| 空範本 preview | `rejected`、`no_paper_trade_rows`、`write_performed=false` |

下一個可直接落地的輸入是使用者／外部 paper producer 提供真實成交回報（包含 fill／partial-fill／reject／cancel、reference/fill price、Decimal commission/tax/slippage、turnover bp、execution gap、source event）。接收後固定走：

1. `append_paper_trade_csv.py` preview 與欄位驗證。
2. 顯示 source hash、筆數、成本與 invalid rows。
3. 確認前重算 hash；任何變更整批拒絕。
4. 明確 `--confirm-append-paper-ledger` 後才 append 至 Paper Trade Ledger。
5. 重新跑 readiness 與週報；只有完整成本／換手／execution gap 才能解除 `not_computable`。

## 本輪程式修正

`app_module/paper_portfolio_readiness_service.py` 原本會把合法週末／休市日 status 的 `decision_date=2026-08-30` 與最後交易日 snapshot `2026-08-28` 比較，誤報 `paper_daily_status_date_mismatch`。現在只在真正 `passed` 且有 snapshot 的 daily run 進行 snapshot 欄位 reconciliation；`skipped_non_trading_day` 會保留 state-db path check 並輸出 `paper_daily_status_non_trading_day_no_snapshot_expected` diagnostic。

回歸測試：`tests/test_paper_portfolio_readiness_service.py`，`13 passed`。

## 安全邊界

- 這輪沒有寫入 `D:\Min\Python\Project\FA_Data`，沒有建立 `paper_trade_ledger.sqlite`。
- `research_only=true`、`writes_allowed=false`、`broker_execution=false`、`auto_rebalance_allowed=false` 維持不變。
- 沒有把空範本、snapshot、benchmark 或 preview 當成 fill、成本後績效、Formal evidence 或投資有效性。
