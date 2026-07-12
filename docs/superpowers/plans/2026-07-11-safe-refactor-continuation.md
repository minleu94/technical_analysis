# Safe Refactor Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依安全重構 Master Report 的 gate，消除已確認的 import cycle，逐步薄殼化主要 Qt views，最後才移除有完整證據的 shim／legacy code。

**Architecture:** 每個切片先以 characterization 或 contract test 固定公開行為，再把依賴改為明確 submodule、結構型 protocol、coordinator 或 presenter。QWidget 保留 ownership、signal wiring 與公開 properties；Application 與金融核心分開處理，禁止同片跨層搬移。

**Tech Stack:** Python 3.11、PySide6、pytest、mypy、AST import-contract tests。

## Global Constraints

- 不修改正式資料、SQLite schema、交易語意或 scheduler。
- 金融核心不得新增裸 `float` 計算；涉及訊號與回測時必須執行 look-ahead bias 自查。
- 每片必須可獨立回退，並同步架構與狀態文件。
- shim 與 legacy code 僅能在所有 consumer、序列化與 import 證據完成後移除。

---

### Task 1: UpdateService package import dependency

- [x] 新增 AST RED，禁止從 package attribute 匯入 normalization module。
- [x] 改為明確 submodule dependency。
- [x] 驗證 fresh-interpreter re-export、normalization、py_compile 與 mypy。

### Task 2: Backtest / Walk-forward cycle

- [x] 補 T-1 fold boundary contract。
- [x] 補 degradation 與 summary golden numeric contract。
- [x] 新增 import-cycle RED。
- [x] 以結構型 `WalkForwardResultContract` 移除反向 module dependency。
- [x] 驗證 walk-forward、overfitting、py_compile 與 mypy。

### Task 3: UI thin shells

- [x] BacktestView：移出完整績效摘要（SOP／score diagnostics／baseline／overfitting／詳細統計）、promotion message 與 choice label presenter，保留相容委派。
- [x] BacktestView：以 immutable `BacktestExecutionRequest` 統一單檔 service kwargs 與 persisted `current_run_params`，View 僅保留 widget 讀值、batch 分流與 worker lifecycle。
- [x] BacktestView：以 immutable `OptimizationExecutionRequest` 與 `BatchBacktestExecutionRequest` 移出 grid/batch service kwargs、progress adapter、parallel/research metadata 與 cancellation contract。
- [x] BacktestView：以 immutable `WalkForwardExecutionRequest` 移出 Train-Test/Walk-forward mode、期間與 service result envelope。
- [x] RecommendationView：移出完整 profile advanced summary chain（Decimal 權重／篩選格式、pattern preview）與 regime label presenter，保留相容委派。
- [x] RecommendationView：移出完整 recommendation reason keyword/trace HTML 與 Explain score/ranking/risk HTML presenters，保留相容委派。
- [x] RecommendationView：移出完整 Why Not score/filter/regime gap 與 severity HTML presenter，保留相容委派。
- [x] RecommendationView：以 immutable `RecommendationExecutionRequest` 集中 required selection validation、service kwargs 與 progress contract。
- [x] RecommendationView：以 immutable `RecommendationSaveRequest` 移出 result DTO、Profile/Regime/negative-evidence snapshot 與 watchlist payload 建構。
- [x] UpdateView：移出多 worker lifecycle coordinator與完整 quick/safe update-all orchestration；保留 `_active_workers` / `worker` 契約、步驟順序、TPEX soft failure 與一般步驟 fail-fast payload。
- [x] UpdateView：以 immutable `SourceUpdateRequest` 移出 daily TWSE/TPEX/SQLite/indicator step graph 與 market/industry/broker operation mapping。
- [x] WorkbenchView：移出 review queue、evidence feed、action items、operating loop DTO-to-text/degraded mapping，維持 read-only boundary。
- [x] MainWindow：移出 workspace alias routing 與 immutable workspace registration/navigation plan，保留 Qt ownership 與 signal wiring。
- [x] MainWindow：移出 Smart Money semantic/common-loader Application composition 與 Runtime controller/bridge/view/timer Qt composition。
- [x] 建立 `tests/test_ui_thin_shell_boundaries.py`，禁止五個 UI shell 直接呼叫核心 execution entrypoints並鎖定 delegate 尺寸。
- [x] 執行 UI focused tests、UpdateView QA script、mypy 與 py_compile。

### Task 4: Application orchestration and dependency inversion

- [x] 將 MainWindow 的 Decision Desk service graph 移入 `app_module/decision_desk_composition.py`，以 constructor map 注入依賴並維持 fail-soft optional services。
- [x] 將 Smart Money semantic service 與共用 market-frame loader 組裝併入 Application composition root。
- [x] 依 Task 3 產生的 ports 逐 service 建立 characterization。
- [x] Recommendation save coordinator 提升至 `app_module`，單一 `persist()` 管理必要 result write 與 soft-failure watchlist write。
- [x] RecommendationService market-history stage 改由 injected provider port；default adapter 保留 SQLite-first/CSV fallback 與 normalization。
- [x] Recommendation market-frame 欄位正規化抽成不突變來源的具名純步驟，固定 legacy alias 與 name fallback 契約。
- [x] Recommendation final ranking 抽成 immutable pure plan，固定 fixed／quantile tie-break、percentile bp、universe 與 top_n 契約。
- [x] IndustryMapper／MarketRegimeDetector 新增 frame-provider ports，MainWindow 的 Screening／Regime／Recommendation graph 移至 Application composition root。
- [x] BrokerBranchUpdateService 分離 registry parsing、MoneyDJ request builder、E/B merge plan 與 CSV write coordinator；temp-path contracts 保留 backup/write order。
- [x] UpdateService daily source 的 subprocess output parsing/result aggregation 抽成純步驟；保留缺日、命令與 temp log orchestration。
- [x] 只反轉已被 contract 覆蓋的 concrete dependency。
- [x] 驗證公開 service entrypoints 與 persisted payload identity。
- [x] IndicatorParameterRegistry 改由 analysis domain 擁有，decision 舊路徑以 class-identity re-export 相容。
- [x] Broker/Flow DTO 改由 decision domain 擁有；Application 舊 import path、dataclass payload 與 consumer contracts 保持。

### Task 5: Financial / analytical core and cleanup

- [x] 先建立 Decimal／bp／T-1／look-ahead contract，再移動核心責任。
- [x] 技術指標價格清理完成 golden／numeric／prefix-T-1 RED→GREEN；移除前導缺值 backward-fill look-ahead，抽成純 kernel。
- [x] ScoringEngine 既有 Decimal／bp／prefix oracle 下抽出 10,000 bp 最大餘額 pure kernel，保留 façade。
- [x] MarketRegimeDetector 在 golden／short-history／prefix oracle 下抽出 MA slope 與 Bollinger bandwidth causal kernels。
- [x] BrokerSimulator／performance／Portfolio／RecommendationPortfolio 既有 units、ledger/metrics/result supports 通過 92 項 timeline／Decimal／numeric governance closeout；未重寫已合規公式。
- [x] 完成全 repo static/dynamic/persisted-data audit，產出 `SHIM_LEGACY_REMOVAL_AUDIT_2026-07-12.md`；production imports 已遷移。
- [x] 使用者於 2026-07-12 明確核准 Wave 6 移除；tests 先改為舊檔不存在契約。
- [x] 移除無 consumer 的 shim／legacy code，並同步 inventory、導航、migration history 與架構文件。
- [x] 完整 release healthcheck passed（run `20260712_025311`）；pytest 1676、Update UI 38、Update QA 23/0/4、mypy 364、financial checker 37 均通過。
