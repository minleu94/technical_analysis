# 評分系統說明：buy_score 與 sell_score

> **📖 文檔定位**：本文檔是**用戶快速參考指南**，專注於 buy_score 和 sell_score 的使用說明。  
> 如需完整的策略設計規格、驗證方法、風險分析等技術細節，請參考 [策略設計規格書](STRATEGY_DESIGN_SPECIFICATION.md)。

## 概述

`buy_score` 和 `sell_score` 是策略的**閾值參數**，用於判斷何時進場（買入）和出場（賣出）。它們是基於**TotalScore（總分）**的閾值，而 TotalScore 是由多個子分數加權計算得出的。

---

## TotalScore（總分）的計算方式

### 公式

```
TotalScore = W_pattern × PatternScore + W_indicator × IndicatorScore + W_volume × VolumeScore
```

其中：
- **PatternScore（圖形分數）**：0-100 分，基於識別到的技術圖形模式（如頭肩頂、雙底等）
- **IndicatorScore（指標分數）**：0-100 分，基於技術指標的綜合評分
- **VolumeScore（成交量分數）**：0-100 分，基於成交量的變化與異常
- **權重（W_pattern, W_indicator, W_volume）**：各子分數的權重，會根據市場狀態（Regime）自動調整

### 子分數的詳細計算

#### 1. IndicatorScore（技術指標分數）

綜合以下技術指標的評分（如果啟用）：

- **RSI（相對強弱指標）**：判斷超買超賣
- **MACD（移動平均收斂發散）**：判斷趨勢動能
- **KD（隨機指標）**：判斷短期動能
- **ADX（平均趨向指標）**：判斷趨勢強度
- **均線系統（MA）**：判斷價格與均線的關係（如 MA5, MA10, MA20, MA60）
- **布林通道（Bollinger Bands）**：判斷價格波動與通道位置

每個指標都會被標準化為 0-100 分，然後根據配置的權重加權平均。

#### 2. PatternScore（圖形分數）

基於識別到的技術圖形模式，例如：
- 頭肩頂/頭肩底
- 雙頂/雙底
- 三角形整理
- 旗形/楔形
- 等等

每個模式都有對應的分數，最終加權平均得到 PatternScore。

#### 3. VolumeScore（成交量分數）

基於成交量的變化：
- 成交量放大倍數
- 成交量異常檢測
- 量價關係分析

---

## buy_score 與 sell_score 的作用

### buy_score（買入閾值）

**預設值**：60 分

**作用**：
- 當 `TotalScore >= buy_score` 時，觸發**買入信號候選**
- 需要連續 `buy_confirm_days` 天都滿足條件，才會真正產生買入信號
- 例如：`buy_score = 60`，`buy_confirm_days = 2` 表示需要連續 2 天總分都 >= 60 才會買入

**邏輯**：
```python
# 計算連續確認
buy_confirmed = 連續 buy_confirm_days 天都滿足 (TotalScore >= buy_score)

# 進場條件
if 未持倉 and buy_confirmed and 不在 cooldown 期間:
    產生買入信號
```

### sell_score（賣出閾值）

**預設值**：40 分

**作用**：
- 當 `TotalScore <= sell_score` 時，觸發**賣出信號候選**
- 需要連續 `sell_confirm_days` 天都滿足條件，才會真正產生賣出信號
- 例如：`sell_score = 40`，`sell_confirm_days = 2` 表示需要連續 2 天總分都 <= 40 才會賣出

**邏輯**：
```python
# 計算連續確認
sell_confirmed = 連續 sell_confirm_days 天都滿足 (TotalScore <= sell_score)

# 出場條件
if 已持倉 and sell_confirmed and 不在 cooldown 期間:
    產生賣出信號
```

---

## 策略執行流程

以 **Baseline Score Threshold** 策略為例：

1. **數據準備**：載入股票歷史數據
2. **技術指標計算**：計算 RSI、MACD、均線等技術指標
3. **圖形模式識別**：識別技術圖形模式
4. **總分計算**：
   ```
   TotalScore = W_pattern × PatternScore + W_indicator × IndicatorScore + W_volume × VolumeScore
   ```
5. **信號生成**：
   - 檢查 `TotalScore >= buy_score` 是否連續 `buy_confirm_days` 天
   - 檢查 `TotalScore <= sell_score` 是否連續 `sell_confirm_days` 天
   - 考慮 cooldown 期間（交易後 `cooldown_days` 天內禁止反向操作）
6. **執行交易**：根據信號執行買入或賣出

---

## 參數調整建議

### buy_score 調整

- **提高 buy_score（如 70）**：
  - 更嚴格的進場條件
  - 減少假信號，但可能錯過一些機會
  - 適合穩健型策略

- **降低 buy_score（如 50）**：
  - 更寬鬆的進場條件
  - 捕捉更多機會，但可能增加假信號
  - 適合積極型策略

### sell_score 調整

- **提高 sell_score（如 50）**：
  - 更早出場
  - 保護利潤，但可能過早離場
  - 適合短線策略

- **降低 sell_score（如 30）**：
  - 更晚出場
  - 給趨勢更多空間，但可能回吐更多利潤
  - 適合長線策略

### 確認天數調整

- **buy_confirm_days / sell_confirm_days**：
  - 增加確認天數：減少假信號，但可能延遲進出場
  - 減少確認天數：更快反應，但可能增加假信號

---

## 範例

假設某股票在連續 3 天的 TotalScore 分別為：55, 62, 65

**設定**：
- `buy_score = 60`
- `buy_confirm_days = 2`

**分析**：
- 第 1 天：TotalScore = 55 < 60，不滿足條件
- 第 2 天：TotalScore = 62 >= 60，滿足條件（第 1 天）
- 第 3 天：TotalScore = 65 >= 60，滿足條件（第 2 天）

**結果**：第 3 天產生買入信號（因為連續 2 天都 >= 60）

---

## 相關參數

> **注意**：以下預設值適用於 **Baseline Score Threshold** 策略。其他策略（如暴衝策略、穩健策略）有不同的預設值，詳見 [UI 功能文檔](UI_FEATURES_DOCUMENTATION.md)。

- **buy_score**：買入閾值（預設 60）
- **sell_score**：賣出閾值（預設 40）
- **buy_confirm_days**：買入確認天數（預設 2）
- **sell_confirm_days**：賣出確認天數（預設 2）
- **cooldown_days**：交易後冷卻天數（預設 3）

---

## 總結

- **TotalScore** 是綜合技術指標、圖形模式和成交量的加權總分（0-100 分）
- **buy_score** 是買入閾值，當 TotalScore >= buy_score 且連續確認天數滿足時，產生買入信號
- **sell_score** 是賣出閾值，當 TotalScore <= sell_score 且連續確認天數滿足時，產生賣出信號
- 這些參數可以通過**參數最佳化**功能來尋找最適合的數值

---

## 📚 相關文檔

- **[策略設計規格書](STRATEGY_DESIGN_SPECIFICATION.md)**：完整的策略設計規格，包含研究假設、驗證方案、風險分析、優化建議等技術細節
- **[使用者指南](USER_GUIDE.md)**：複雜功能的使用教程，包含參數最佳化、Walk-forward 驗證等
- **[UI 功能文檔](UI_FEATURES_DOCUMENTATION.md)**：所有 Tab 的功能說明和參數文檔

