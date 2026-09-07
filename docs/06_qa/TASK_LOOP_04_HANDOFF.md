# TASK-LOOP-04 EXEC 交接

## 執行前回滾清單

| 檔案 | 類型 | 預期變更 | 回滾方式 | 風險 |
|---|---|---|---|---|
| app_module/recommendation_portfolio_backtest_service.py、recommendation_portfolio_dtos.py | 修改 | 版本化下一開盤撮合與精確帳務 | 核對目前 diff 後反向套用本卡 hunk | 新旧成交結果不同，必須連同契約版本回復 |
| backtest_module/broker_simulator.py、app_module/backtest_service.py | 修改 | 單股撮合與執行版本揭露 | 反向套用本卡 hunk | 尾端持倉與成本語義隨版本回復 |
| ui_qt/views/backtest_view.py | 修改 | 歷史資料經 app service 載入與新契約 | 反向套用本卡 hunk | 需與 service 介面同時回復 |
| scripts/qa_validate_phase3_3b.py、本卡既有測試 | 修改 | 隔離 QA 與 legacy 測試明確化 | 反向套用本卡 hunk | 無正式資料風險 |
| tests/test_task_loop_04_contract.py、本交接檔 | 新增 | 關鍵行為與交接證據 | 核對無其他 agent 接續修改後，移除此卡新增檔 | 刪除測試會降低契約保護 |

回滾步驟：先保存 `git diff -- <本卡實際改檔>` 為本卡 patch，確認沒有混入其他 owner 的變更；用 `git apply --reverse --check <patch>` 驗證，再 `git apply --reverse <patch>`。若檔案已由他人接續修改，逐 hunk 人工回復。不得使用整檔 checkout、clean 或資料重建。回復後執行本卡 focused pytest。未提交的兩個既存刪檔與 Playbook 保留。

## 時間線自查

- T 日收盤後 provider 僅取得日期不晚於 T 的市場切片；訊號設定／股票池凍結。
- 委託於 T 收盤建立，成交只能在後續具有有效開盤且可交易的 session；缺價、零量或停牌延後，不回退收盤成交。
- 開盤成交後才在當日收盤估值；停損停利採收盤確認，下一可交易開盤退出，同日 OHLC 不用來回填成交。
- 末端沒有後續 session 的委託記為未成交，已有部位保留未實現損益，不合成期末清倉。
- 核心現金、股數、成本、報酬與退出使用 Decimal／整數，DTO 浮點僅在輸出邊界。

## 工程交接結果

狀態：本卡獨立工程驗收完成；跨卡 Registry 元資料與共用 Manual 套用由 TASK-05／08-B 接續。base/current HEAD 均為 `678db2bb260bb1de5cee4a0864f9f402db3660a7`，未 stage、commit 或 push 本卡變更。入口既存的兩個刪檔與 Playbook 及其他卡 dirty changes 均保留。

實際修改：`app_module/backtest_service.py`、`app_module/batch_backtest_service.py`、`app_module/recommendation_replay_service.py`、`app_module/recommendation_portfolio_backtest_service.py`、`app_module/recommendation_portfolio_dtos.py`、`backtest_module/broker_simulator.py`、`backtest_module/performance_metrics.py`、`ui_qt/views/backtest_view.py`、`ui_qt/views/backtest/execution_coordinator.py`、`scripts/qa_validate_phase3_3b.py`、`tests/test_backtest_timeline_contract.py`、`tests/test_recommendation_portfolio_backtest.py`。新增 `tests/test_task_loop_04_contract.py` 與本檔。未修改 TASK-05 owner 的 `test_ui_qt_research_run_save.py`，只執行該測試。

- 推薦回放新預設 `next-session-open.v2`；舊同日收盤必須明選 `legacy-same-day-close.v1`。舊測試明確標示 legacy，而非改寫既存 run。
- 推薦與單股 next_open 均為收盤委託、後續有效開盤成交；零量、停牌、缺開盤不回退 close；末端只估值，不偽造成交。收盤確認停損停利後次開盤出場，跳空使用實際 open。
- 新執行核心使用 Decimal／整數；費稅與滑價只扣一次，股數與現金守恆。單股加碼股數累加、FIFO 部分退出成本配對；推薦 DTO 的 `pnl_cents` 與 summary 的 `ending_equity_cents`／`ending_cash_cents` 保留精確結果。
- `PeriodHoldingDTO` 新欄位均有相容預設：`execution_contract`、`position_status`、`exit_signal_date`、`pnl_cents`。開放部位的 `actual_exit_date` 留空，`actual_exit_price=0`；`pnl_cents` 為含已支出成本的期末估值損益，不代表已實現。
- 同資料／費稅／滑價／session 的 Equal Weight benchmark 消費 frozen recommendations，不重跑選股。單股 Buy & Hold 以相同 BrokerConfig 的 next_open／成本／末端估值建立；不同版本不得直接混排名。
- UI 的研究歷史由 `BacktestService.load_recommendation_portfolio_history()` 提供，SQLite 使用 `mode=ro`／`query_only`，保留開盤與量，不初始化 DBManager／writer。UI 使用所選手續費／滑價、賣出稅 30 bp、整張 1000 股；服務 API 預設整股 1 股，成本未指定仍揭露 `unspecified_cost_assumptions`。
- 推薦 replay 深拷貝設定與結果，optional `available_date` 不晚於決策日才可進 provider；缺失 available_date 的列排除並揭露。保留候選上限、既有 profile 邊界，不接 P0 未接受新來源。
- 單股合作式取消傳至逐 session 撮合；推薦取消保留 partial/cancelled 狀態與未成交原因，不把取消當完整成功。

## 隔離與驗證證據

DATA_ROOT=`C:/Projects/PythonProjects/technical_analysis/output/master_goal/TASK-LOOP-04/data`、OUTPUT_ROOT=`C:/Projects/PythonProjects/technical_analysis/output/master_goal/TASK-LOOP-04/artifacts`、PROFILE=`test`、QT_QPA_PLATFORM=`offscreen`。TWStockConfig 的衍生路徑位於各根 `/_test`；契約測試與新 QA 使用離線 DataFrame fixture，不讀正式資料。唯讀 SQLite fixture 讀取前後 SHA-256 不變的測試已通過。

| 驗證 | 結果／exit code |
|---|---|
| 基線金融／時間線 suite | 42 passed／0 |
| Playbook 8 檔 focused suite，加 `test_backtest_factor_metadata.py`、`test_backtest_diagnostics_and_date_adjustment.py`、`test_batch_backtest_research_run_save.py`、`tests/test_backtest/test_overfitting_risk.py` | 124 passed／0 |
| 新 `tests/test_task_loop_04_contract.py` | 15 passed／0；T+1、gap、停牌、缺 open、精度、future append、取消、DTO、FIFO、readonly loader 與 frozen benchmark |
| `tests/test_ui_qt_update_view_workbench.py` | 81 passed／0 |
| `scripts/qa_validate_phase3_3b.py` | 2/2 offline fixture checks passed／0；預設不執行 promotion，`--legacy-full` 未執行 |
| `scripts/qa_validate_update_tab.py` | 25 passed、0 failed、4 skipped／0；來源下載等 skip 不當成 passed |
| `python -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | 527 source files 無 error／0；2 個既有 annotation-unchecked notes |
| `scripts/check_financial_float_boundaries.py`、`scripts/check_look_ahead_bias.py` | 各 exit 0；靜態掃描不取代行為證據 |
| `python -m py_compile <本卡全部 13 個 Python 改檔>`、scoped `git diff --check` | exit 0 |

本卡 focused pytest 命令採 Playbook 列出的完整八檔，追加上述四檔，參數為 `-q -o addopts=`。warning 共 25：24 個明選 legacy 收盤假設 warning 與 1 個既有 `.pytest_cache` 寫入權限 warning；無 test skip。最新新增 metadata 診斷後另跑 15 個契約測試通過。

QA artifact：`output/master_goal/TASK-LOOP-04/artifacts/_test/qa/phase3_3b_validation/VALIDATION_REPORT.json`，SHA-256=`0A3A26F9B807CB03FB2DFC02C16C3098159241A8E733B15564D72BAB1FA09CE9`。fixture 契約測試檔 SHA-256=`15FF4CF34AE8804D6E02361C49F90092B67BF23E39247E9F3D8F7A83DACFE108`。Update QA 當輪報告 SHA-256=`F0836596161D66CE45A32786F8B02AAC906EA2EFA79C17ABB826E2FC063EA196`，另複製至本卡 artifact root 保存；其正式來源是 TASK-01 自帶 TemporaryDirectory，沒有正式下載。

## TASK-05 接線契約

`BacktestReportDTO.details.execution_contract`、`details.data_manifest.execution_contract` 與推薦 result 的 `summary.execution_contract`／`details.execution_contract` 皆提供 version。TASK-05 應在 `research_run_metadata.py` 保存此值到 `ResearchRunMetadataDTO.execution_price`（或另建明確 version 欄位並納入比較），而不是用目前 UI 控件重建；新舊版本必須 `incompatible`。Batch／Fixed per-stock metadata 已使用 `details.execution_contract`。推薦 `details.benchmark_results` 現保存同版本 Equal Weight；Summary 的 status=`cancelled` 不可冒充完整成功。請為這些 source fields、舊 metadata 缺 version 的相容與比較隔離加入 owner 測試。既有 saved payload 一律不重寫。

## TASK-08-B 共用文件精確補丁

1. **APPLICATION_MANUAL.md／9.10 推薦回放**：將目前以同日收盤作現況的長段落移為「legacy 結果」說明。新增目前預設為 `next-session-open.v2`，T 收盤訊號於下一可交易開盤成交；缺 open／停牌延後；停損停利採收盤確認再下一開盤；持有天數從實際進場日計曆日，到期收盤建立退出訊號。說明 UI 費率、滑價、30 bp 賣出稅、1000 股；服務 API 不指定成本會顯示假設不足。
2. **同節結果判讀／排錯**：`position_status=open`、空 exit date 與 `open_position_count` 代表期末持倉，不能當完成交易；`ending_equity` 包含估值，`realized_pnl`／`unrealized_pnl` 分列。`missing_open_or_suspended`、`end_of_data`、`insufficient_cash_or_known_volume`、cancelled 保留原因。`gap_risk` 改為 signal close→actual execution open；rolling risk／microstructure 仍為診斷。新版本 Equal Weight benchmark 使用同 frozen selections／成本／session。
3. **APPLICATION_MANUAL.md／9 研究回測共用流程、9.9 Registry、12 回測 0 交易**：單股／批次／固定組合 per-stock next_open 不再期末強制清倉；沒有後續有效開盤就無成交。保留 fixed basket 仍是 per-stock 研究、沒有完整共享現金 portfolio engine 的限制。跨版本 comparison 不可排名；舊 run 不重算。不授予 promotion、scheduler、broker 或正式 evidence 權限。
4. **system_architecture.md／11 保存與研究治理**：補上版本化 execution 與 Registry 交接；UI 歷史讀取移至 BacktestService query-only 方法。**target architecture** 僅同步已落地的目前→目標說明，不改產品成熟度。
5. **PROJECT_SNAPSHOT／Roadmap Hub／6M／Index**：新增 TASK-04 工程修補與本交接入口；V4 evidence accumulation、Formal credit、真實 paper fills／source acceptance 均維持既有狀態。

## 限制與後續 Gate

結果仍是離線研究：不存在委託簿、盤中成交序列、停牌正式來源接受或真實 fills 證據。單股開盤漲跌停採只看當時 open／前收的保守拒絕；推薦路徑明列 `price_limit_order_book_not_modeled`。盤中 high/low 不被拿來選擇有利成交先後，退出語義固定為收盤確認。舊 legacy 計算僅保留可回放相容，不宣稱其符合新金融／時間線契約。正式 Registry／資料／Profile／帳本無寫入，跨卡整合與人工／真實時間 Gate 仍另行追蹤。
