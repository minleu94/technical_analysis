# TASK-LOOP-06 PORT Handoff

日期：2026-09-06
狀態：candidate-only implementation complete；未進行 stage、commit、push 或正式資料切換。

驗收修正：2026-09-06 已補上 SQLite connection cleanup。先前使用
`with sqlite3.Connection` 只完成 transaction commit/rollback，不會自動 close
handle；現在 repository 的所有讀寫與 schema 檢查統一經過 `_connection_scope()`，
在成功、例外與 read-only 路徑都明確 close。新增 Windows candidate directory
cleanup contract，確認 repository 與 read-only repository 都可在物件釋放後被
`shutil.rmtree` 清理。

## 交付範圍

本卡在既有 JSONL 相容路徑之外建立隔離的精確事件帳本。資料層新增
`data_module/portfolio_ledger_repository.py` 與
`data_module/portfolio_ledger_migration.py`：事件以整數分、整數股數、Decimal
邊界與 source namespace 保存，SQLite writer 只有 append，撤銷只新增
compensation event。migration 只接受 caller 明確提供的 candidate SQLite，讀取
JSONL 時保留來源雜湊與原始 record；重跑會回報 already_present，不會改寫來源。
backtest namespace 會被拒絕轉成 portfolio fills，paper namespace 仍保留外部
source acceptance warning。

`portfolio_module/core.py` 新增精確 `LedgerPosition`、`LedgerProjection`、
`rebuild_ledger_projection()` 與已提交價格的未實現損益計算。它會檢查 namespace
與 portfolio scope、重複事件、補償目標、超賣、費稅、負現金（可選
`reject_negative_cash=True`），並以排序後事件重播得到可重建持倉、現金與已實現損益。

`PortfolioService` 只有在 caller 注入 `PortfolioLedgerRepository` 時才開啟精確
帳本；既有 UI／JSONL API 的相容行為沒有被暗中切換。新增的
`record_precise_trade()`、`rebuild_from_ledger()`、`compensate_ledger_event()` 與
`build_ledger_read_model()` 都透過 app DTO 交換資料。既有
`TradeDTO`／`PositionDTO` 不變，另增精確 Ledger DTO。

## 07 消費契約（凍結）

資料層 `PortfolioLedgerReadModel` 與 app 層
`PortfolioLedgerReadModelDTO` 的共同欄位為：

- `portfolio_id`、`source_namespace`、`as_of_date`
- `quality`：`complete`、`degraded`、`blocked`
- `source_ledger_id`、`source_ledger_hash`（`sha256:<hex>`）
- `event_count`、`missing_inputs`、`warnings`、`candidate_only=True`
- app DTO 另帶 `positions`、`cash`、`realized_pnl`；position 內含整數股數、Decimal 金額字串化 DTO、source lineage 與 trade IDs。

入口是：

`PortfolioService.build_ledger_read_model(portfolio_id, source_namespace, as_of_date, market_prices, source_ledger_id, initial_cash, reject_negative_cash)`。

事件只取 `occurred_at <= as_of_date`。有持倉而沒有已提交 `market_prices` 時為
`blocked` 並列出 `market_prices`；缺 `source_id` 或 thesis 時保留持倉並為
`degraded` 加 warning；沒有事件時為 `blocked` 並列出 `ledger_events`。07 的
fixture 應使用暫存根目錄、`PortfolioLedgerRepository.create_synthetic_fixture()`、
`PortfolioLedgerEvent(source_namespace="synthetic", quantity=int,
price/fees/taxes=Decimal)` 與 `append_many()`；不得指向正式 JSONL、Paper ledger
或預設資料根目錄。

## 驗收證據

以下命令均以 exit code 0 完成：

```text
.\.venv\Scripts\python.exe -m pytest tests/test_portfolio_mvp.py tests/test_portfolio_numeric_governance.py tests/test_portfolio_jsonl_store_serialization.py tests/test_portfolio_delete.py tests/test_paper_trade_ledger.py tests/test_paper_trade_import_service.py tests/test_paper_trade_reconciliation.py tests/test_position_health_service.py tests/test_position_health_state_machine.py tests/test_task_loop_06_contract.py -q -o addopts=
```

結果：50 passed。新增契約覆蓋費稅／現金／部分賣出、重複事件、超賣、負現金、補償重播、namespace 隔離、read-only 不建 schema、Windows connection cleanup、日期／quality／hash、缺 thesis/source 的 degraded、JSONL→candidate SQLite 冪等，以及缺來源 blocked。

```text
.\.venv\Scripts\python.exe scripts\qa_validate_portfolio_tab.py
```

結果：service/domain、隔離精確 ledger、compensation、migration、缺 fills blocked 與 PortfolioView smoke 全部 PASSED。測試資料均在 TemporaryDirectory。

共同 gate：

- `mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`：Success，532 files。
- `scripts/check_financial_float_boundaries.py`：exit 0。
- `scripts/check_look_ahead_bias.py`：exit 0。
- `tests/test_ui_qt_update_view_workbench.py`：81 passed。
- `scripts/qa_validate_update_tab.py`：25 passed、0 failed、4 skipped（既有外部下載／合併 skip）。
- `scripts/run_full_app_healthcheck.py --mode quick`：Healthcheck passed。
- 變更檔 source compile 檢查使用不寫入 pycache 的 compile gate；標準 `py_compile` 受到共享 `__pycache__` 權限阻擋，並非語法錯誤。

TASK-LOOP-07 依賴驗收（只讀執行，未修改 07 檔案）：

- `tests/test_task_loop_07_contract.py`：13 passed。
- `scripts/qa_validate_decision_loop.py`：status passed，七個 fixture-only checks 全部通過，`production_migration_allowed=false`。

## 外部缺件與後續 gate

目前沒有真實 broker／paper producer fills，故本卡沒有建立任何正式成交、沒有
把回測結果轉成 fills，也沒有執行正式 migration、delete、clear、broker order 或
source acceptance。要啟動正式來源，必須另取得具名來源、source ID、提交價格、
thesis、費稅與時間邊界，先通過 PaperTrade reconciliation，再由獨立核准 gate
決定正式 writer；本 handoff 不授權該切換。

## 回復方式

本卡新增檔案可直接移除；既有檔案以本卡變更前保存的 patch 反向套用，先用
`git apply --reverse --check <saved-patch>` 驗證。不得使用整棵 checkout、reset、
clean 或刪除正式資料的方式回復。回復後重跑本卡 pytest、portfolio QA 與
financial/look-ahead gate。
