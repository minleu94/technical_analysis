# 評分系統說明：buy_score 與 sell_score

> **📖 文檔定位**：本文檔是**用戶快速參考指南**，專注於 buy_score 和 sell_score 的使用說明。  
> 如需完整的策略設計規格、驗證方法、風險分析等技術細節，請參考 [策略設計規格書](STRATEGY_DESIGN_SPECIFICATION.md)。

## 概述

`buy_score` 和 `sell_score` 是策略的**閾值參數**，用於判斷何時進場（買入）和出場（賣出）。它們是基於**TotalScore（總分）**的閾值，而 TotalScore 是由多個子分數加權計算得出的。

---

## TotalScore（總分）的計算方式

### 公式

```
TotalScore = (
    pattern_bp × PatternScore
  + technical_bp × IndicatorScore
  + volume_bp × VolumeScore
) / 10000
```

其中：
- **PatternScore（圖形分數）**：0-100 分，基於識別到的技術圖形模式（如頭肩頂、雙底等）
- **IndicatorScore（指標分數）**：0-100 分，基於技術指標的綜合評分
- **VolumeScore（成交量分數）**：0-100 分，基於成交量的變化與異常
- **權重（pattern / technical / volume）**：使用非 bool 整數基點，三項必須完整且總和嚴格等於 `10000 bp`
- **數值精度**：核心加權使用 `Decimal`，最後以 `ROUND_HALF_UP` 量化至 `0.01` 分
- **Regime 調整**：使用 Decimal 倍率與最大餘額法重新分配成總和 `10000 bp` 的整數權重

舊版 `0.3 / 0.5 / 0.2` 權重只能經 legacy migration adapter 無損轉換；若乘積不是整數 bp、key 不完整或總和不是 `10000 bp`，系統會拒絕執行，不會自動補差額。

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

## 門檻判定模式 (threshold_mode)

系統支援雙門檻判定模式，以提供向後相容的固定門檻以及適應市場變化的動態歷史分位數門檻：

1. **固定分數門檻 (fixed 模式)**：直接與設定之 `buy_score` (預設 60) 與 `sell_score` (預設 40) 比對。
2. **動態分位數門檻 (quantile 模式)**：採單股 Expanding 歷史分布，透過基點 `buy_quantile_bp` (預設 8000，即 80%) 與 `sell_quantile_bp` (預設 4000，即 40%) 動態判定。

---

## buy_score 與 sell_score (fixed 模式)

### buy_score（買入分數閾值）
- **預設值**：60 分
- **作用**：當 `TotalScore >= buy_score` 時，觸發**買入信號候選**。
- 需要連續 `buy_confirm_days` 天滿足條件才產生信號。

### sell_score（賣出分數閾值）
- **預設值**：40 分
- **作用**：當 `TotalScore <= sell_score` 時，觸發**賣出信號候選**。
- 需要連續 `sell_confirm_days` 天滿足條件才產生信號。

---

## buy_quantile_bp 與 sell_quantile_bp (quantile 模式)

在分位數模式下，門檻並非固定分數，而是隨歷史 Expanding 數據動態變化。為了防範未來函數 (Look-ahead bias)，T 日的門檻只能使用 T-1 日以前的 TotalScore 歷史分布來計算：

### 計算規則
- **暖機期 (Warm-up)**：固定為 60 個交易日。若歷史數據不足 60 個交易日，則不會產生買入與賣出信號。
- **門檻計算公式**：先把 T-1 以前的有效 `score_bp` 排序，再使用整數 nearest-rank：
  - `rank = max(1, (sample_count * quantile_bp + 9999) // 10000)`
  - `threshold_score_bp = sorted_history[rank - 1]`
- **進出場信號判定**：
  - 買入信號候選：`TotalScore_T >= buy_threshold_T` (即大於或等於 T-1 以前歷史分布的 buy_quantile 分位值)。
  - 賣出信號候選：`TotalScore_T <= sell_threshold_T` (即小於或等於 T-1 以前歷史分布的 sell_quantile 分位值)。
- 基點單位：以 `0-10000` 整數基點 (basis points) 進行嚴謹量化，例如 `8000` 基點即代表第 80 百分位。

---

## 推薦橫斷面百分位排名 (Recommendation Quantile Mode)

在「推薦分析」中，若啟用了「百分位排名 (quantile)」模式，則會對當日所有符合基本篩選條件之 Eligible Universe 進行**橫斷面百分位排名**：

- **統計一致性**：採用 Empirical CDF 公式計算百分位，同分時取得相同百分位，且排序不受個股輸入順序影響。
- **合格母體安全閥 (recommendation_min_universe_size)**：
  - 為了保障分位數的統計嚴謹性，當合格母體大小低於最低要求 (預設 20 檔) 時，推薦服務會拋出 `RecommendationUniverseTooSmallError` 且**不進行降級**。
- **百分位篩選門檻 (recommendation_min_percentile_bp)**：
  - 只推薦橫斷面百分位大於或等於最低百分位 (預設 8000，即 80%) 的個股。
- **穩定排序**：符合百分位門檻之個股以 `(total_score desc, stock_code asc)` 雙重排序進行穩定排序，隨後套用 `top_n`。

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

- **threshold_mode**：門檻判定模式 (預設 `fixed`)
- **buy_score**：固定買入分數閾值 (預設 60)
- **sell_score**：固定賣出分數閾值 (預設 40)
- **buy_quantile_bp**：分位數買入基點 (預設 8000，即 80%)
- **sell_quantile_bp**：分位數賣出基點 (預設 4000，即 40%)
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

