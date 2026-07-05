# V1.6 Cross-sectional Factor Pipeline & Sector Rotation v2 Design

> 日期：2026-07-05  
> 範圍：Daily factor snapshot pipeline、Sector Rotation v2 / concept basket governance、factor rank / quantile 保存、factor attribution summary  
> 狀態：實作中；承接 V1.5 data credibility governance，不改 `ScoringEngine`

## 目標

V1.6 的目標是把每日橫斷面市場、產業、題材、流動性、籌碼與基本面 diagnostics 轉成可追溯、可降級、可重跑檢查的 factor snapshot。這一版只建立研究治理層與唯讀 / 受控寫入入口，不把 factor rank 當成推薦結果，不改核心評分，不啟用 production scheduler，也不宣稱任何 factor 具投資有效性。

V1.6 完成後，系統應能回答四個問題：

1. 指定決策日有哪些 factor records 被接受、neutralized、skipped，原因是什麼。
2. 每檔股票在同一橫斷面 universe 內的 factor rank / quantile 是多少，使用哪些資料品質與可得日政策。
3. 產業輪動 v2 如何同時保存官方產業與 concept basket metadata，且保留 basket 成分版本與 available_date。
4. Research / evidence 後續要做 attribution 時，能以 CLI summary 檢查 factor coverage、quality、rank bucket 與 sector / concept 分布。

## Scope In

- 新增 V1.6 factor snapshot DTO，描述 daily snapshot、factor rows、rank / quantile、sector / concept metadata 與 diagnostics。
- 新增 append-only / idempotent SQLite repository 與 migration helper，用於保存 `cross_sectional_factor_snapshots` 與 `cross_sectional_factor_rows`。
- 新增 cross-sectional pipeline service，從既有 `FactorRecord`、sector rotation summary 與 concept basket definition 組合 snapshot。
- 新增 concept basket governance v1：只接受內建或明確傳入的 basket definition，保存 `basket_id`、`basket_version`、`members`、`available_date` 與 missing policy，不抓外部資料。
- 新增 factor attribution summary service / CLI，唯讀彙總 snapshot coverage、quality、rank bucket、sector / concept 分布與 diagnostics。
- 新增 tests、py_compile、quant guard 與文件同步。

## Scope Out

- 不改 `decision_module/scoring_engine.py`。
- 不把 factor rank / quantile 當作推薦、買賣或策略升降級依據。
- 不導入三大法人、信用交易、TDCC 或正式外部 ingestion。
- 不建立 production scheduler，也不讓既有 evidence scheduler 自動寫入 V1.6 snapshot。
- 不重建或破壞正式 `DATA_ROOT` 原始資料。
- 不調整回測 PnL、cash ledger、成交價、sizing 或 portfolio 狀態。

## 架構

### Factor Snapshot DTO

新增 `app_module/cross_sectional_factor_dtos.py`。核心 DTO：

- `ConceptBasketDefinition`
- `CrossSectionalFactorRow`
- `CrossSectionalFactorDiagnostic`
- `CrossSectionalFactorSnapshot`
- `FactorAttributionSummary`

`CrossSectionalFactorRow` 以整數欄位保存 `score_bp`、`rank`、`quantile_bp`、`universe_size`。排序採同 factor、同 decision date 的 score desc、stock code asc 穩定排序；同分同 rank，quantile 使用整數基點，避免金融核心裸 `float`。

### SQLite Repository

新增 `data_module/cross_sectional_factor_migration.py` 與 `app_module/cross_sectional_factor_repository.py`。Schema：

- `cross_sectional_factor_snapshots`
  - `snapshot_id` primary key
  - `snapshot_hash` unique
  - `decision_date`
  - `factor_set_version`
  - `universe_id`
  - `source_version`
  - `row_count`
  - `diagnostics_json`
  - `metadata_json`
- `cross_sectional_factor_rows`
  - `row_id` primary key
  - `snapshot_id`
  - `stock_code`
  - `factor_name`
  - `as_of_date`
  - `available_date`
  - `value`
  - `score_bp`
  - `rank`
  - `quantile_bp`
  - `universe_size`
  - `quality`
  - `missing_policy`
  - `sector`
  - `concept_basket`
  - `metadata_json`

Repository 寫入採 snapshot hash idempotency；同 hash 重跑不新增重複 snapshot。正式 production-like DB 不由 CLI 預設寫入，CLI 必須指定 `--db-path` 與 `--confirm` 才保存。

### Pipeline Service

新增 `app_module/cross_sectional_factor_pipeline.py`：

1. 使用既有 `FactorService.build_snapshot()` 先跑 `FactorGate`。
2. 只對 accepted / neutralized rows 產生 rank；skipped 只進 diagnostics。
3. 每個 factor 先固定當日 universe，再計算 rank / quantile。
4. concept basket 僅由明確 definition 指派；若 basket `available_date > decision_date`，對應 metadata 不寫入 row，並產生 diagnostic。
5. sector metadata 可由呼叫者傳入 stock -> sector mapping，或由 sector rotation summary metadata 只做 summary attachment；不在 pipeline 內重新查 DB。

### Sector Rotation v2 / Concept Basket

V1.6 不重寫既有 `SectorRotationService`。v2 在 pipeline metadata 層承接既有 sector ranking，並補 concept basket governance：

- 官方產業：保存 `sector` 與 sector ranking source metadata。
- Concept basket：保存 basket id / version / available_date / members。
- 沒有 governed basket definition 時，concept 欄位為 `None`，並以 summary warnings 揭露 `concept_basket_missing_definition`。

### Attribution Summary

新增 `app_module/cross_sectional_factor_attribution.py` 與 CLI `scripts/inspect_cross_sectional_factor_snapshot.py`：

- `--snapshot-id` 或 `--latest` 讀取 snapshot。
- JSON / Markdown summary。
- 彙總 factor row count、quality counts、rank bucket counts、sector counts、concept basket counts、diagnostics。
- 只讀取 repository，不寫 DB、不讀 UI state。

## Look-ahead 自查

- Factor `available_date > decision_date` 仍交給 `FactorGate` fail-closed / neutralize / skip。
- 橫斷面 rank 只在同一 `decision_date`、同一 factor、當日已固定 universe 內計算，不跨日使用未來分布。
- Concept basket definition 必須有 `available_date <= decision_date` 才能指派；否則只產生 diagnostics。
- Sector rotation metadata 只接受 caller 已提供的 snapshot / mapping，不在 pipeline 內以未來資料回補。
- CLI 預設唯讀，保存 snapshot 必須 explicit confirm 與 explicit DB path。

## 測試策略

- DTO tests：驗證 rank / quantile 欄位、JSON safety、bool metadata fail-closed。
- Repository tests：驗證 schema creation、idempotent save、list / latest / get rows。
- Pipeline tests：驗證 accepted / neutralized / skipped 分流、同分 rank、quantile、concept basket available_date gate、sector metadata。
- CLI / summary tests：驗證 latest summary、Markdown / JSON 輸出與只讀行為。
- 執行 focused pytest、py_compile、`scripts/quant_guard_linter.py`、`git diff --check`。

## 文件更新

完成實作後同步：

- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/01_architecture/system_architecture.md`
- `docs/07_guides/APPLICATION_MANUAL.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/06_qa/V1_6_CROSS_SECTIONAL_FACTOR_PIPELINE_CLOSEOUT_2026_07_05.md`

## 驗收 Gate

- 可建立 daily cross-sectional factor snapshot，且保存 hash idempotent。
- factor rank / quantile 以整數基點保存，且不污染 `ScoringEngine`。
- concept basket assignment 遵守 `available_date <= decision_date`。
- attribution CLI 可唯讀彙總 snapshot coverage / quality / rank / sector / concept。
- focused tests、py_compile、quant guard 與 docs closeout 通過後才完成分段 commit。
