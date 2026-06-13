# Strategy & Scoring Governance 設計規格

## 1. 目的

在不破壞既有策略版本與歷史回測重現性的前提下，為回測進出場門檻與每日推薦排名加入分位數治理。

本階段不改變 `TotalScore` 的計算公式，而是治理「如何使用分數做決策」：

- 回測：固定分數門檻或單股歷史分位數門檻。
- 推薦：最新交易日 eligible universe 的橫斷面百分位排名。

## 2. 已核准決策

1. 採雙模式漸進遷移，不直接取代既有固定門檻。
2. 舊策略未提供 `threshold_mode` 時，一律視為 `fixed`。
3. 回測分位數採單股 Expanding 歷史分布。
4. T 日門檻只能使用 T-1 日以前的 `TotalScore`。
5. 回測固定暖機期為 60 個有效分數觀測值。
6. 決策層分位數使用整數基點，不新增裸 `float` 參數。
7. 第一版不支援 rolling window，不自動轉換歷史策略版本。

## 3. Scope

### 3.1 Scope In

- `fixed` / `quantile` 雙模式參數契約。
- 回測 Expanding T-1 分位數門檻。
- 60 個有效觀測值暖機契約。
- Baseline、Momentum Aggressive、Stable Conservative 三個 executor。
- 回測診斷、最佳化參數與 UI 模式切換。
- 推薦 eligible universe 橫斷面百分位排名。
- Preset、StrategyVersion 與研究結果的門檻 metadata 追溯。
- Look-ahead、數值邊界、向後相容與重播測試。

### 3.2 Scope Out

- 不修改 `ScoringEngine` 的 `TotalScore` 公式。
- 不移除 `buy_score` / `sell_score`。
- 不把舊策略自動轉成 quantile。
- 不加入 rolling quantile 或自適應窗口。
- 不把 quantile 設為預設策略模式。
- 不修改或重建正式市場資料與 SQLite schema。

## 4. 參數契約

### 4.1 固定門檻模式

```python
{
    "threshold_mode": "fixed",
    "buy_score": 60,
    "sell_score": 40,
    "buy_confirm_days": 2,
    "sell_confirm_days": 2,
}
```

相容規則：

- 缺少 `threshold_mode` 時等同 `fixed`。
- 固定模式的訊號、診斷與回測結果必須與變更前一致。
- `buy_score` / `sell_score` 仍保留在 Preset、StrategyVersion 與最佳化流程。

### 4.2 分位數門檻模式

```python
{
    "threshold_mode": "quantile",
    "buy_quantile_bp": 8000,
    "sell_quantile_bp": 4000,
    "quantile_warmup_observations": 60,
    "quantile_method": "nearest_rank",
    "buy_confirm_days": 2,
    "sell_confirm_days": 2,
}
```

驗證規則：

- 基點範圍為 `0 <= value <= 10000`。
- `buy_quantile_bp` 必須大於 `sell_quantile_bp`。
- `quantile_warmup_observations` 第一版固定為 60；載入其他值時應拒絕，而非靜默改寫。
- `quantile_method` 第一版固定為 `nearest_rank`，並寫入 metadata 供重播。

UI 可顯示為百分比，但 Service / Domain / Executor 邊界只傳遞整數基點。

## 5. 回測時間序列契約

進入門檻元件前，先把 `TotalScore` 量化為整數 `score_bp`：

```python
score_bp = quantize_score_to_basis_points(total_score)
```

`quantize_score_to_basis_points()` 使用 `Decimal(str(value))` 與明確的 `ROUND_HALF_UP`，把 `0..100` 分數轉成 `0..10000` 整數基點。不得用裸 `float` 乘法完成量化。

對 T 日以前的有效 `score_bp` 排序後，使用整數 nearest-rank：

```python
rank = max(1, (sample_count * quantile_bp + 9999) // 10000)
threshold_score_bp = sorted_history[rank - 1]
```

語義：

- T 日 `TotalScore` 不得參與 T 日門檻計算。
- 暖機以非空的歷史分數觀測值計數。
- 暖機完成前，買進與賣出候選條件都為 `False`。
- 暖機完成後：
  - 買進候選：`score_bp[T] >= buy_threshold_score_bp[T]`
  - 賣出候選：`score_bp[T] <= sell_threshold_score_bp[T]`
- `buy_confirm_days` / `sell_confirm_days` 套用於上述候選條件。
- 尾端新增未來資料不得改變任何既有日期的門檻或訊號。

## 6. 推薦橫斷面契約

推薦與回測使用不同母體，不共用時間序列門檻計算器。

推薦流程：

1. 載入截至最新交易日可取得的資料。
2. 依資料完整性、產業、流動性與使用者硬條件建立 eligible universe。
3. 對每檔 eligible 股票計算最新 `FinalScore`。
4. 所有股票完成評分後，統一計算橫斷面百分位。
5. 依推薦分位門檻與 `top_n` 產出結果。

輸出 metadata 至少包含：

- `score_percentile_bp`
- `eligible_universe_size`
- `eligible_universe_date`
- `ranking_method`
- `threshold_mode`

推薦第一版參數：

```python
{
    "recommendation_ranking": {
        "threshold_mode": "fixed",
        "recommendation_min_percentile_bp": 8000,
        "recommendation_min_universe_size": 20,
        "recommendation_ranking_method": "nearest_rank",
    }
}
```

- `recommendation_ranking` 缺少或其 `threshold_mode` 缺少時，維持既有 fixed 排序與 `top_n` 行為。
- 只有 `recommendation_ranking.threshold_mode == "quantile"` 時才啟用橫斷面百分位門檻。
- eligible universe 少於 20 檔時必須回傳明確診斷，不得靜默降級成 fixed。
- 同分時依 `FinalScore` 降序、`stock_code` 升序確定排序，確保重播一致。
- 百分位採 empirical CDF：`ceil(count(score <= current_score) * 10000 / universe_size)`；同分股票取得相同百分位基點。
- 百分位以整數名次換算成 `0..10000` 基點，不在決策層保存浮點百分位。

## 7. 架構邊界

### 7.1 ScoringEngine

`decision_module/scoring_engine.py` 只負責單股分數：

- `IndicatorScore`
- `PatternScore`
- `VolumeScore`
- `TotalScore`
- `FinalScore`

它不負責：

- 回測進出場門檻。
- 跨股票橫斷面排名。
- 策略版本相容判斷。

### 7.2 回測門檻元件

建立小型共用元件，集中處理：

- 參數驗證。
- fixed / quantile 分流。
- Expanding T-1 動態門檻。
- 暖機狀態。
- 診斷欄位。

三個 executor 只消費門檻元件輸出的候選條件，不各自重複分位數實作。

### 7.3 RecommendationService

`app_module/recommendation_service.py` 在所有 eligible 股票完成單股評分後，負責橫斷面排名。不得在逐股迴圈內計算最終百分位。

## 8. 交付增量

### 增量 A：回測雙模式門檻

- 共用門檻元件與參數驗證。
- Baseline executor 接入。
- Momentum / Stable executor 接入。
- 回測診斷與最佳化參數接入。
- UI fixed / quantile 模式切換。
- 策略版本 metadata 保存與重播。

### 增量 B：推薦橫斷面排名

- eligible universe 契約。
- 推薦百分位排名與門檻。
- DTO / ResultStore metadata。
- 產業篩選、同分、母體不足與可重現測試。

增量 A 必須先完成並通過 fixed 模式相容測試，才開始增量 B。

## 9. 錯誤處理

- 非法 `threshold_mode`：拒絕執行並指出允許值。
- 基點超界或買入分位不高於賣出分位：拒絕執行。
- quantile 模式缺少必要參數：拒絕執行，不套用隱含預設。
- 暖機不足：回傳可診斷狀態，不視為例外。
- 推薦母體不足：回傳明確診斷，不偷偷改用固定門檻。
- 舊策略缺少新欄位：依相容規則採 fixed。

## 10. 測試與驗收

### 10.1 Look-ahead 防禦

- T 日門檻不包含 T 日分數。
- 修改 T+1 以後資料不改變 T 日門檻與訊號。
- 將未來資料附加到序列尾端，不改變既有日期結果。

### 10.2 暖機與邊界

- 前 60 個有效歷史觀測值不足時無訊號。
- 第 61 個有效觀測值開始可產生動態門檻。
- NaN 不被計入有效暖機觀測值。
- `0`、`10000` 與非法基點有確定行為。
- 全部同分時輸出穩定且可重現，門檻值維持同一個整數 `score_bp`。

### 10.3 向後相容

- 缺少 `threshold_mode` 的策略結果與原版一致。
- fixed 模式三個 executor 的訊號與交易結果不變。
- 舊 Preset / StrategyVersion 可載入與重播。

### 10.4 推薦母體

- 只使用 eligible universe 排名。
- 產業篩選後重新建立母體。
- `top_n` 不參與百分位母體建立。
- 同分排序固定使用 `FinalScore` 降序、`stock_code` 升序。

### 10.5 完成 Gate

- 相關 pytest 全部通過。
- mypy 全專案通過。
- 變更 Python 檔案通過 py_compile。
- `scripts/check_financial_float_boundaries.py` 通過。
- UI 變更依 repository 規範完成強制 QA。
- fixed 與 quantile 的 Walk-forward 比較報告完成。

## 11. 文件同步

規格階段同步：

- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/08_technical/PARAMETER_DESIGN_IMPROVEMENTS.md`
- `docs/05_phases/PHASE2_5_COMPLETION_STATUS.md`

功能完成後同步：

- `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md`
- `docs/02_features/SCORE_EXPLANATION.md`
- `docs/02_features/BACKTEST_LAB_FEATURES.md`
- `docs/02_features/USER_GUIDE.md`
- `PROJECT_NAVIGATION.md`

## 12. 完成定義

本 Phase 完成必須同時滿足：

1. 舊策略與 fixed 模式可重現。
2. quantile 模式通過 Look-ahead 防禦測試。
3. 決策參數採整數基點，未新增裸 `float` 邊界。
4. 回測時間序列與推薦橫斷面語義清楚分離。
5. Preset、StrategyVersion、研究結果與診斷 metadata 可追溯。
6. quantile 尚未經 Walk-forward 證明前，不成為預設模式。
