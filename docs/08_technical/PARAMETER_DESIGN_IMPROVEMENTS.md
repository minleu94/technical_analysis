# 參數設計改進計劃

## 📋 問題概述

當前系統存在參數「單位不一致」與「可比較性」問題，這會導致：
1. 同一個參數在不同股票/不同波動下意義不同
2. Grid Search 容易過擬合（overfit）
3. 策略組合/權重無法有效運作

## 🎯 改進原則

所有參數要能被解釋、可被縮放（scale）、可跨股票比較、可做 walk-forward。

---

## 優先級 1：強勢/弱勢分數公式改進 ⚠️ 立即修改

### 當前問題
- 量變% 分佈極端（容易爆到幾百%甚至上千%），會把漲幅吃掉
- 漲幅%與量變%直接相加，單位不一致，排序會很不穩定

### 解決方案 A：標準化加權（推薦）

```python
# 標準化報酬
ret_z = zscore(當日/當週報酬)  # 或用 robust zscore：median/MAD

# 標準化量能（使用 log 壓縮）
vol_z = zscore(log(volume / vol_ma))

# 加權分數
score = 0.6*ret_z + 0.4*vol_z
```

### 解決方案 B：量變%壓縮（快速實現）

```python
# 壓縮量變
vol_factor = log1p(volume_ratio)  # 或 tanh(volume_ratio-1)

# 加權分數
score = 0.6*ret_pct + 0.4*vol_factor
```

### 新增參數
- `volume_lookback`：量能均線用幾天（預設 20）
- `min_price`：過濾低價股（預設 5 元）
- `min_liquidity`：最小成交金額門檻

---

## 優先級 2：圖形模式參數 ATR-based ⚠️ 立即修改

### 當前問題
- `window`、`threshold`、`prominence`、`height_ratio` 都跟波動度/股價尺度強耦合
- 同樣 `threshold=0.05`，對低波動大盤股跟高波動小型股不是同一件事

### 解決方案：以 ATR 為單位

```python
# 改用 ATR 標準化
threshold_atr = threshold_price_move / ATR  # 或用 ATR%
prominence_atr = prominence / ATR

# 參數簡化為三層
1. 資料視窗：window（10~30、20~40）
2. 形狀約束：用 ATR 表示（例如 W 底的兩低點容忍度）
3. 確認條件：突破頸線、放量確認
```

### 新增參數
- `breakout_confirm`：`close > neckline` 且 `volume_ratio > x`
- `retest_confirm`（可選）：突破後回測不破再進

---

## 優先級 3：Scoring Contract 統一 ⚠️ 立即修改

### 當前問題
- 每個子分數尺度不一致（0~100、-1~1、百分比混用）
- Regime Match Factor 倍率太大會失控

### 解決方案：固定 Scoring Contract

```python
# 每個子分數輸出：0~100
indicator_score: 0~100
pattern_score: 0~100
volume_score: 0~100

# 總分計算
total = w1*indicator + w2*pattern + w3*volume

# Regime 只做權重切換，不再乘倍率
Trend: w_indicator=0.6, w_pattern=0.2, w_volume=0.2
Reversion: w_indicator=0.5, w_pattern=0.3, w_volume=0.2
Breakout: w_indicator=0.4, w_pattern=0.4, w_volume=0.2

# 如果真的要 factor，限制在很小範圍
match_factor ∈ [0.9, 1.1]
```

---

## 優先級 4：回測參數改進

### Execution Price 明確定義
- `execution_price`: `close` / `next_open`（避免偷看）
- 預設：`next_open`（更真實）

### 停損停利 ATR 倍數模式
- 保留：`stop_loss_pct` / `take_profit_pct`
- 新增：`stop_loss_atr_mult` / `take_profit_atr_mult`（建議預設）

### 手續費/滑價敏感度分析
- `fee_bps`、`slippage_bps` 都能「0 / 真實」切換

---

## 優先級 5：策略參數改進

### buy_score/sell_score 改為分位數
```python
# 當前：固定分數
buy_score = 70

# 建議：分位數（更穩定）
buy_quantile = 0.8  # 前 20% 才買
sell_quantile = 0.4
```

### 新增參數
- `max_positions`：最多同時持有幾檔
- `position_sizing`：等權、分數加權、波動調整
- `allow_pyramid`：是否允許加碼（預設 False）
- `allow_reentry`：是否允許重新進場
- `reentry_cooldown_days`：重新進場冷卻期

---

## 優先級 6：指標參數改進

### RSI (14)
- ✅ 保留預設值
- 新增：`rsi_entry_mode`: `cross` / `level`
- 新增：`rsi_overbought` / `rsi_oversold`（預設 70/30，策略層控制）

### MACD (12,26,9)
- ✅ 保留預設值
- 改用無量綱版本：`macd_norm = macd / close` 或 `macd / atr`
- 或用訊號：`hist > 0`、`macd 上穿 signal`

### KD (5,3,3)
- ✅ 保留預設值
- 新增：`enable_kd`（允許關掉）
- 建議：KD 只用於 Reversion regime

### ADX (14)
- ✅ 保留預設值
- 新增：`adx_trend_threshold`（常見 20/25）
- 新增：`adx_rising_window`（例如 3~5 天）

### MA windows [5,10,20,60]
- ✅ 保留預設值
- 建議：把 MA 訊號定義成事件/結構
  - `ma_trend_structure`: `MA5>MA20>MA60`
  - `ma_slope_window`: `MA20 近 5 日斜率`
  - `close_above_ma20`：單一條件

### ATR (14)
- ✅ 保留預設值
- 建議：`atr_pct = ATR / close`
- 停損/停利用 `k * atr_pct`

### BBANDS (20,2,2)
- ✅ 保留預設值
- 建議：`bb_position = (close - lower)/(upper-lower)` 0~1

---

## 優先級 7：推薦系統參數改進

### 量能比率定義
- `min_volume_ratio`：明確定義為相對於 `vol_ma(20)`
- 新增：`min_turnover`（成交金額門檻）

### 最小報酬率依 Regime 調整
- Trend/Breakout：`min_return_pct` 可以稍高（過濾盤整）
- Reversion：允許負報酬（撿低估）

---

## 優先級 8：Walk-forward 改進

### 暖機期參數
```python
warmup_bars = max(60, 3*max_indicator_period)
# 至少要 >= MA60 才有完整資訊
```

---

## 📝 實施計劃

### Phase 1：立即修改（本週）✅ 已完成
1. ✅ 強勢/弱勢分數改成標準化或壓縮
2. ✅ Pattern threshold/prominence 改成 ATR-based
3. ✅ Scoring contract 固定

### Phase 2：短期（下週）✅ 已完成
4. ✅ 回測 execution_price 明確定義
5. ✅ 停損停利加入 ATR 倍數模式
6. ✅ 加入 max_positions / position_sizing

### Phase 3：中期（兩週內）
7. ✅ 指標參數改進
8. ✅ buy_score/sell_score 改為分位數
9. ✅ 推薦系統參數改進

### Phase 4：長期（一個月內）
10. ✅ Walk-forward 暖機期
11. ✅ 完整測試與驗證

---

## 🔍 驗證標準

每個改進都需要通過：
1. **單位一致性**：參數在不同股票間可比較
2. **可縮放性**：參數可隨市場環境調整
3. **Walk-forward 穩定**：在不同時期表現穩定
4. **可解釋性**：參數意義清晰

---

---

## Phase 2.5 UI 整合狀態

### ✅ 已完成 UI 整合

所有 Phase 2.5 的參數改進已整合到 UI：

1. **執行價格選擇** ✅
   - 下拉選單：next_open / close
   - 位置：回測配置區塊

2. **停損停利模式切換** ✅
   - 下拉選單：百分比模式 / ATR 倍數模式
   - 自動顯示/隱藏對應輸入框
   - 位置：回測配置區塊

3. **ATR 停損停利輸入框** ✅
   - stop_loss_atr_mult（0-10）
   - take_profit_atr_mult（0-20）
   - 位置：回測配置區塊（ATR 模式時顯示）

4. **部位管理配置** ✅
   - 獨立 GroupBox
   - max_positions（1-50）
   - position_sizing（等權重/分數加權/波動調整）
   - allow_pyramid（複選框）
   - allow_reentry（複選框）
   - reentry_cooldown_days（0-30 天）
   - 位置：回測配置區塊下方

### 使用方式

詳細使用說明請參考：
- [UI 功能文檔](UI_FEATURES_DOCUMENTATION.md) - 回測參數部分
- [使用者指南](USER_GUIDE.md) - Phase 2.5 新參數使用指南

---

**最後更新：Phase 2.5 UI 整合完成後**

