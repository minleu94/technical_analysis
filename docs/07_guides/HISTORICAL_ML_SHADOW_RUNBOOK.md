# Historical ML Shadow Runbook

## 定位與安全邊界

此流程只建立 research-only 傳統 ML challenger，不改 Score、Recommendation、Advice、Portfolio 或 production scheduler。正式 SQLite 必須使用 `mode=ro` 與 `PRAGMA query_only=ON`；dataset、model、preflight report 只能寫入呼叫者明確指定、且不位於 `DATA_ROOT` 的 ignored output root。

Core family 只接受 price、technical、market、industry。Fundamental 在正式 PIT audit 顯示 eligible=0 時維持排除；broker 維持獨立 add-on，不補 0。所有持久化數值使用整數 bp/count；`float` 只存在 sklearn 模型邊界。

## 訓練與選模

1. Feature T 使用前一交易日資料；label 從 feature cutoff close 起算 20 個共同市場交易日。
2. `decision_date`、`label.available_date` 都必須小於等於 `training_as_of`；本版 frozen cutoff 固定為 `2024-12-31`。
3. Split 使用 expanding trading-calendar purged walk-forward，不允許 shuffle/K-fold。Train label end 必須早於 test start。
4. Linear 與 HGB 使用相同 fold/schema；imputer/scaler 只 fit train fold。全缺欄位必須保留 frozen feature shape。
5. Downside calibration 只使用至少兩個 OOF blocks。Research blend 只使用 `label.available_date <= 2024-12-31` 的 OOF rows，候選 alpha 固定為 0/2500/5000/7500/10000 bp。
6. `production_alpha_bp` 永遠是 0。Research alpha 不會寫回 production path，也不代表 promotion。

## Corporate-action gate

- `strict`：coverage unknown 時排除 label window；不得建立 clean/formal OOS dataset。
- `research`：可保留 degraded labels，但 manifest 必須是 `research_only_degraded`、`formal_oos_allowed=false`，並保存 blocker。
- E2 coverage 改善後仍需建立新 dataset/model generation，不可覆寫既有 manifest 或 artifact。

## Terra Development Dataset V0（2025 seen OOS）

2025 已由 owner 決議永久標為 `seen_oos`／`development_data`；不得再稱為 virgin／untouched formal OOS。`formal_oos_allowed=false`、`production_blend_alpha_bp=0`，正式 Rule-only path 不變。Terra V0 是獨立的 development-only generation：只讀 SQLite 的 `daily_prices`、`technical_indicators`、`market_indices`、`industry_indices`；fundamental 與 broker 一律排除。

操作前先確認 `DEVELOPMENT_OUTPUT_ROOT` 位於 `DATA_ROOT` 之外，且 generation ID 尚未使用。下列範例只產生最多五個 decision dates 的 bounded smoke；所有 artifact 只會寫到指定 output root：

```powershell
.\.venv\Scripts\python.exe scripts\build_terra_development_dataset_v0.py `
  --database D:\Min\Python\Project\FA_Data\sqlite\twstock.db `
  --development-output-root C:\Temp\technical_analysis_development_output `
  --generation-id terra-v0-smoke-20260713 `
  --decision-date-start 2025-01-02 `
  --decision-date-end 2026-01-31 `
  --training-as-of 2025-12-31 `
  --evaluation-as-of 2026-12-31 `
  --max-decision-dates 5
```

Feature 一律採 T-1，且 `available_date <= decision_date`。Universe 名稱固定為 `conservative_observed_history`：每一 decision date 至少須有 252 個先前可觀測交易日；來源不提供正式 listing／delisting metadata 時，manifest 必須揭露對應缺口，不能以今日存續股票清單補齊。

labels 必須從本次 generation 讀取的受控原始價格資料重建。2025 ready labels 僅可進 `fit_rows`；2026 即使成熟也只能寫入 `evaluation_rows`，不得進 fit、normalizer、hyperparameter 或 blend 選擇。V0 不讀 corporate-action coverage source，因此 research labels 固定是 `dataset_status=research_only_degraded`，manifest 必須保留 `corporate_action_coverage_missing` blocker。每個 generation 保存 dataset/generation ID、registry hashes、四個 source fingerprints、cutoff、date range、row counts、missing／exclusion diagnostics、canonical content hash 與 zero-formal-write flags；已存在的 generation ID 一律拒絕覆寫。

## 2025 Locked OOS 指令已停用

owner 已選擇 2025 方案 B，因此不得執行 `evaluate_ml_2025_oos.py`、不得提供任何 `--oos-payload`，也不得要求或嘗試取得 `formal_oos_allowed=true`。既有 locked verifier 保留為歷史程式邊界，Terra V0 不呼叫、不修改也不解封它。

2025 的唯一允許用途是 Terra development generation；新 temporal holdout 由 `DevelopmentDataUsageDecision.jsonl` 的 `new_holdout_start` 管理。任何日期範圍觸及該 holdout 起點，或其 consumption registry 已標記 consumed 時，Terra CLI 必須在讀取 core source 前停止。工程成功不等於 formal OOS、model promotion 或投資有效。

## 名詞區分

- Historical research rehearsal：可含 degraded coverage，不是 clean OOS。
- Locked historical OOS：freeze/preflight 全綠後才可一次性讀取。
- Daily shadow inference：由 F workstream 負責，仍無 production action。
- Forward evidence：真實時間後續累積，不可由歷史 OOS 取代。
- Promotion：必須另經人工 review；本流程不自動套用。
