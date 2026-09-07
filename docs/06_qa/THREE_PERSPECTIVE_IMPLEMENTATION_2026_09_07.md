# 三面向清查建議實作交接（2026-09-07）

本文件承接 2026-09-06 三面向唯讀清查報告的建議，記錄本輪已落地的工程、驗收與仍需外部證據的 Gate。完整本機報告位於 `output/qa/three_perspective_audit_20260906/PROJECT_REVIEW.md`；可提交的結論以本文件與 Scoped SSOT 為準。

## 執行邊界

- 本輪未寫入正式資料根目錄、正式 SQLite、模型 production pointer 或券商介面。
- 沒有啟動全市場訓練、重建、promotion、scheduler 或 broker order。
- 所有 ML 新入口維持 `formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`。
- 容量與 parity 工具只在明確提供 candidate 路徑時寫入報告；沒有自動刪除、搬移或覆寫 immutable run。

## 依序完成的工程

### 1. 分析證據、成交與持倉閉環

- `ScoreEffectivenessReadModel` 增加流動性成本、成本後 benchmark excess 與描述性 95% 區間，並保留樣本數、警告與限制；沒有把缺成本的 Paper ledger 合成淨績效。
- `ConservativeFillPolicy` 以 Decimal／整數處理下一交易日開盤成交，揭露漲跌停拒絕、成交量參與率、整張限制、部分成交與未成交原因；推薦組合回放將 requested／filled／unfilled 與 fill status 一起保存。
- `PaperTradeReconciliationService` 增加可選現金守恆檢查；`require_cash_reconciliation` 未通過時維持 append blocked。候選 portfolio ledger migration 仍只作用於隔離副本。
- `PositionHealthStateMachine` 將論點弱化、硬性失效與 time-stop 分開，支援明確 `reduce`／`exit` action；沒有完整官方交易日曆時回報 `time_stop_calendar_incomplete`，不猜曆日、不自動下單。
- 基本面 available date、PIT、企業行動與歷史產業成分沿用既有 fail-closed acceptance／look-ahead contract；本輪沒有用目前快照補造正式歷史資料。

### 2. D 槽容量與 ML 交付

- 新增 `data_module/ml_storage_capacity.py`，用整數 bytes 統一「持久新增、暫存峰值、執行後安全保留」三段預算。Raw PIT exporter、Direct numeric store、Direct/OOC scheduled wrapper 與 OOC trainer 都在啟動及階段／年度 checkpoint 重驗，超額時保存 checkpoint／heartbeat 並安全停止。
- Raw PIT 的 capacity telemetry 不再進 immutable publication identity hash；相同來源重播仍產生相同 publication，預發佈檢查會把 staging bytes 計入持久配額，避免 rename 後留下無 pointer 的 orphan publication。
- `minimal_linear_shadow` 只允許單一 `ridge_logistic` 與一個明確 horizon，且將 complexity policy 寫入 request／summary；`full_shadow` 才保留既有多 horizon／HGB 研究流程。兩者都不授予 production authority。
- `AllocationReleaseAdapter` 綁定 model、preprocessor、calibrator、feature order、missing policy、dataset／source lineage hash；`validate_ml_release_parity.py` 以同一批 frozen rows 比對 OOC 與 release 的逐列輸出，mismatch 即 fail closed。舊 artifact 沒有 release manifest 時仍走相容唯讀路徑。
- 日常 inference 只有在明確存在且通過驗證的 `release_manifest.json` 時才使用 adapter；沒有 attached calibration artifact 時，OOC diagnostic calibration 不會被當成正式校準器。

容量操作建議把日常更新與額外餘裕併入安全保留：

`D free >= 100 GiB safety reserve + 35 GiB persistent + 40 GiB temporary + 10 GiB daily update + 15 GiB margin = 200 GiB`。

目前唯讀檢查以 `safety_reserve=125 GiB`、`persistent=35 GiB`、`temporary=40 GiB` 計算 required free `200 GiB`；D 槽觀察可用約 `330.39 GiB`，因此此次 preflight 通過。執行前仍應重新執行 `run_ml_direct_chain_maintenance.py --preflight-only`，並明確傳入 `--safety-reserve-bytes 134217728000`；容量通過不代表 Formal／promotion 通過。

### 3. UI／UX

- Research context store／strip 將股票、決策日、行情／來源日期、result ID 與 profile 帶入跨頁下鑽，返回時保留來源；不重新計算推薦。
- Research Console 將 Rule-only、ML 未參與、正式輸入缺件與 stale projection 轉成中文可採取行動的摘要，技術 hash／DTO／Formal flags 放在可收合診斷層。
- Recommendation 長任務增加四階段進度、百分比、耗時、最後活動與合作式取消；取消只在 worker 安全收尾後結束，部分結果不會冒充成功。
- Fast Canvas chart 增加 ARIA label、方向鍵／Home／End 與同 payload 產生的「顯示數值」替代；Smart Money 圖形欄提供 `AccessibleTextRole`／`StatusTipRole`，主表與分點表支援鍵盤焦點。
- 首頁既有行動中心保留前三至五個待辦與 blocker 入口；本輪未另造重複 dashboard。

## 驗證

- 完整 pytest：`4003 passed, 2 skipped, 27 warnings in 558.49s`；pytest collection=`4005`，
  inventory filesystem／entry=`679/679`，collection errors=`0`。
- 成交／帳務／退出／推薦組合：`59 passed`。
- ML release／parity／容量：`18 passed, 1 skipped`；minimal profile CLI：`4 passed`。
- PIT exporter／assembler／OOC：`62 passed`。
- UI P2、研究上下文、圖表／Smart Money 與必要更新頁：`115 passed`。
- 相關 orchestration／inference：`20 passed`；全模組 mypy：`536 source files` 無錯。
- `scripts/qa_validate_update_tab.py`：`25 passed, 0 failed, 4 skipped`。
- PIT replay、資料更新與文件檢查另以 `git diff --check`、py_compile 驗證；沒有正式資料寫入。

## 尚未可由程式自行完成的 Gate

目前正式 ML input 仍是 `0/3`：因果非現金 portfolio ledger、正式 Rule Champion history、PIT sector membership 尚未同時具備 owner-controlled custody。OOC calibration 仍標記 `oof_diagnostic_only`，尚未形成 attached production calibration；因此不能建立可用於正式推薦的 release，也不能提高 alpha。

內容定址年度／月份 block 重用與 Direct／OOC／inference 全路徑 façade 需要先變更 manifest／consumer contract 和完整 frozen corpus 驗證。本輪先交付容量 checkpoint、release adapter 與 parity 邊界，保留 immutable 歷史，沒有在未經 owner review 下搬移或刪除資料。最後仍需實機 UI 鍵盤／螢幕閱讀器／150%～200% 縮放驗收，以及 owner 對正式輸入、校準與 retention 的具名 review。
