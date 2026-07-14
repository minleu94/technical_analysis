# Terra Development Dataset V0 設計規格

## 目的與授權

本規格建立一個獨立的 development-only historical dataset generation，供研究訓練與離線評估使用。專案 owner 已明確選擇 2025 方案 B：2025 永久標示為 `seen_oos`／`development_data`，不再具備 virgin／untouched formal OOS 資格。

授權決策採 append-only 記錄，位於明確的 `DEVELOPMENT_OUTPUT_ROOT`：`C:\Temp\technical_analysis_development_output`。已記錄有效時間、owner 授權、2025 僅限 development、2026-07-15 為新的未消費 holdout 起點，以及不變的安全旗標。

## 不可變安全邊界

- `formal_oos_allowed=false`。
- `production_blend_alpha_bp=0`。
- 正式 Rule-only path 完全不變；不得改動 `ScoringEngine`、Recommendation、Portfolio、Exit 或 scheduler。
- 不讀取、開啟或使用既有 EV3 sealed payload、return、metric、ranking 或 report body。
- 不修改 `locked_oos`、formal verifier 或任何正式資料庫／正式資料。
- generation 的一切輸出僅能寫入呼叫端明確指定、且不在 `DATA_ROOT` 的 `DEVELOPMENT_OUTPUT_ROOT` 或 TEMP。
- 既有 2025 development labels 不可沿用；必須於新的 generation 從受控原始價格資料重建。

## 架構

新增獨立 `development_module/`，不擴充既有 formal／historical ML builder 的行為：

1. `contracts.py` 定義不可變的 generation request、row、diagnostics 與 manifest safety boundary。
2. `source_adapter.py` 以 SQLite 唯讀連線（`mode=ro`、`PRAGMA query_only=ON`）讀取 core source，計算 source fingerprint，且拒絕 non-core table。
3. `universe.py` 實作明示 `conservative_observed_history` policy：僅以 decision time 前可觀測的歷史計數判定，最少 252 個交易日；所有 listing／delisting metadata 缺失或歧義皆保存為 diagnostics，不能用今日 survivor list 補足。
4. `generation.py` 使用 T-1、`available_date <= decision_date` 的 feature，從當次受控價格 snapshot 建立 labels；2025 labels 可列入 development fit，2026 成熟 labels 必須標 `evaluation_only`，不得輸出到 fit rows。
5. `writer.py` 將資料、manifest、diagnostics 與 source fingerprint 寫至 generation-specific output root，使用 canonical JSON 與 SHA-256 content hash；不得建立或寫入 production DB。
6. `scripts/build_terra_development_dataset_v0.py` 是唯一 composition root，要求顯式 output root、輸入資料庫與 generation ID，並執行 output-root／formal-boundary preflight。

## 資料與時間邊界

core sources 僅限：`daily_prices`、`technical_indicators`、`market_indices`、`industry_indices`。fundamental 和 broker 在 V0 明確排除，不補 0、也不讀取其 table。

每個 feature row 的 `feature_as_of_date` 必須早於 `decision_date`，且 `available_date` 不晚於 `decision_date`。label 只由新 generation 所讀的 price snapshot 建立；20 個共同市場交易日的 horizon 完成後才能標 ready。所有累積報酬、relative return 與 adverse excursion 均使用 `Decimal`／整數 bp，避免核心量化邏輯使用裸 `float`。

2025 的 ready labels 屬 `development_fit_eligible`；2026 即使已成熟，也只屬 `evaluation_only`，不可進入 fit rows、split、normalizer、hyperparameter 或 blend 選擇。新的 holdout 開始日從決策 artifact 指定的首個未消費交易時段起，並在 generation preflight 再確認未被 consumption registry 使用。

corporate-action coverage 無法確認時，research mode 可保留 label，但 generation 必須標記 `dataset_status=research_only_degraded`、`formal_oos_allowed=false`、對應 blockers 和逐項 row diagnostics；strict mode 必須排除該 label window。

## 產物與可重建性

每一 generation 都建立不可覆寫的資料夾，並輸出：

- dataset/generation ID 與 created-at；
- core feature／label registry hashes；
- 各 source 的 schema／內容 fingerprint；
- decision、training、evaluation cutoff 與 date range；
- fit/evaluation row counts、missing／exclusion／listing／delisting diagnostics；
- dataset status、corporate coverage、排除的 fundamental／broker；
- canonical deterministic content hash 與 manifest hash；
- `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`formal_rule_only_path_unchanged=true`、`zero_formal_write=true`。

同 generation ID 的重複寫入一律拒絕；資料內容相同但不同 generation ID 仍各自保存 lineage。任何 output root 位於 `DATA_ROOT`、正式 SQLite 位置或 formal registry 時一律 fail closed。

## 測試與驗證

採 RED→GREEN：先測 output-root 拒絕、core-source allowlist、T-1／available-date、252 日 conservative universe、2025 fit／2026 evaluation-only、corporate degraded、deterministic content hash、append-only 及 zero-formal-write。

完成後執行 targeted pytest、targeted mypy、變更 Python 的 `py_compile`、quant guard／look-ahead boundary 檢查，並以 bounded、唯讀真實資料來源進行一次 smoke。Smoke 所有輸出僅寫 `DEVELOPMENT_OUTPUT_ROOT`／TEMP，並驗證正式 DB 檔案 hash 與 mtime 未變。

## 非目標

V0 不訓練模型、不選模型、不產生 recommendation、不做 promotion、不修改 UI、不修改 scheduler、也不把 2026 outcome 納入 fit。任何後續 external source、corporate coverage 提升或新的 holdout 都必須建立新的 generation，不可覆寫 V0。
