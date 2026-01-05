# Phase 3.3b 研究設計規格：策略與回測強化

## 目標

完成真正的閉環：**推薦 → 回測 → 最佳化 → Promote 成策略版本 → 回到推薦**

讓回測成果可以「升級」為可用策略版本，並提供視覺驗證機制，為 Phase 4 持倉管理做準備。

---

## 1. 研究假設

### 假設 1：回測結果可升級為策略版本（Promote 機制）

**假設**：經過驗證的回測結果（包含參數、績效指標、適用 Regime）可以「升級」為正式的 `strategy_version`，並掛載到 Profile，讓推薦系統能夠使用這個經過實證的策略版本。

**驗證條件**：
- 回測結果必須通過 Walk-Forward 驗證（一致性 >= 60%，退化程度 < 40%）
- 回測結果必須優於 Baseline（Buy & Hold 或隨機策略）
- 回測結果必須有完整的參數記錄與績效摘要

### 假設 2：視覺驗證能提升策略合理性判斷（K 線標記）

**假設**：在 K 線圖上標記買賣點與理由，能夠幫助使用者快速驗證策略行為是否符合預期，識別異常信號（如買在高點、賣在低點），提升策略設計的合理性判斷。

**驗證條件**：
- 使用者能夠從 K 線圖上直觀看到策略的進出場時點
- 使用者能夠從標記中看到買賣理由（reason_tags）
- 視覺驗證能夠發現策略邏輯問題（如信號延遲、假突破）

### 假設 3：回測穩健性驗證能降低過擬合風險

**假設**：透過 Walk-Forward（含暖機期）、Baseline 對比、過擬合風險提示，能夠有效識別過擬合策略，確保策略在未來市場環境中仍能保持穩定表現。

**驗證條件**：
- Walk-Forward 測試期表現與訓練期表現差異 < 40%
- 策略表現優於 Buy & Hold 或隨機策略（統計顯著性 p < 0.05）
- 過擬合風險指標（如參數敏感性、退化程度）在可接受範圍內

---

## 2. 功能定義

### 2.1 Promote 機制（回測成果 → 可用策略版本）

#### 功能描述
讓回測結果可以「升級」為正式的 `strategy_version`，包含：
- 策略參數（從回測結果提取）
- 適用 Regime（從回測期間的 Regime 分布推斷）
- 回測摘要（績效指標、風險指標）
- 可掛載到 Profile（或變成新 Profile）

#### 資料結構
```python
@dataclass
class PromotedStrategyVersion:
    """升級後的策略版本"""
    strategy_id: str  # 原始策略 ID（如 "baseline_score_threshold"）
    strategy_version: str  # 新版本號（如 "1.1.0"，從回測結果生成）
    source_run_id: str  # 來源回測 run_id
    promoted_at: str  # 升級時間
    # 策略參數（從回測結果提取）
    params: Dict[str, Any]  # buy_score, sell_score, confirm_days 等
    config: Dict[str, Any]  # 完整策略配置（technical, patterns, signals）
    # 回測摘要
    backtest_summary: Dict[str, Any]  # total_return, sharpe_ratio, max_drawdown 等
    # 適用 Regime（從回測期間推斷）
    regime: List[str]  # ['Trend', 'Reversion', 'Breakout']
    # Profile 關聯
    profile_id: Optional[str]  # 掛載到哪個 Profile（可選）
    profile_version: Optional[str]  # Profile 版本（可選）
    # 驗證狀態
    validation_status: str  # 'pending', 'validated', 'rejected'
    validation_metrics: Dict[str, Any]  # Walk-Forward 結果、Baseline 對比結果
```

#### 升級條件（Promote Criteria）
1. **Walk-Forward 驗證通過**：
   - 一致性（Consistency）>= 60%
   - 平均退化程度（Average Degradation）< 40%
2. **Baseline 對比優於基準**：
   - 總報酬率 > Buy & Hold 總報酬率
   - Sharpe Ratio > Buy & Hold Sharpe Ratio（或 > 0.5）
3. **風險指標可接受**：
   - 最大回撤 < 30%（可調整）
   - 勝率 > 50%（可調整）

#### 升級流程
1. 使用者選擇回測結果（從 BacktestRunRepository）
2. 系統檢查升級條件（Walk-Forward、Baseline 對比）
3. 如果通過，生成新的 `strategy_version`
4. 可選擇掛載到現有 Profile 或創建新 Profile
5. 保存到 PresetService 或新的 StrategyVersionService

### 2.2 視覺驗證（K 線標記買賣點 v1）

#### 功能描述
在 K 線圖上標記買賣點，顯示買賣理由，作為策略合理性的視覺輔助（非交易建議）。

#### 視覺元素
- **買點標記**：綠色向上箭頭（^），標記在買入日期
- **賣點標記**：紅色向下箭頭（v），標記在賣出日期
- **理由標籤**：hover tooltip 顯示 reason_tags（如 "RSI超賣, 均線支撐"）
- **價格標記**：顯示買入/賣出價格

#### 技術實現
- 使用現有的 `EquityCurveWidget` 作為基礎（已有買賣點標記功能）
- 擴展為 K 線圖（Candlestick Chart）顯示
- 整合 `DailySignalFrame` 的 `reason_tags` 欄位

#### 顯示內容
- **K 線圖**：開高低收價格（Candlestick）
- **買賣點標記**：在對應日期標記
- **理由標籤**：hover 顯示（reason_tags）
- **技術指標疊加**（可選）：MA、RSI、MACD 等

### 2.3 回測穩健性驗證

#### 2.3.1 Walk-Forward（含暖機期）

##### 暖機期定義
- **目的**：確保技術指標計算有足夠歷史數據
- **長度**：建議 20-60 個交易日（約 1-3 個月）
- **處理方式**：訓練期從「開始日期 + 暖機期」開始計算

##### Walk-Forward 參數
- **訓練期長度**：6 個月（可調整）
- **測試期長度**：3 個月（可調整）
- **步進長度**：3 個月（建議與測試期相同）
- **暖機期長度**：20 個交易日（可調整）

##### 驗證指標
- **一致性（Consistency）**：測試期 Sharpe > 0 的比例
- **平均退化程度**：`(test_sharpe - train_sharpe) / |train_sharpe|`
- **穩定性評級**：根據退化程度分級（優秀/良好/可接受/需改進）

#### 2.3.2 Baseline 對比

##### 基準策略定義
1. **Buy & Hold（買入持有）**
   - 策略：期初買入，期末賣出
   - 用途：評估策略是否優於被動持有

2. **Random Entry（隨機進場）**
   - 策略：隨機選擇買入與賣出時點，保持相同交易頻率
   - 用途：評估信號是否有預測能力（vs 隨機）

3. **Simple Moving Average Crossover（簡單均線交叉）**
   - 策略：MA5 上穿 MA20 買入，下穿賣出
   - 用途：評估是否優於簡單技術指標

##### 對比指標
- **絕對績效**：總報酬率、年化報酬率、Sharpe Ratio、最大回撤
- **相對績效**：相對於 Buy & Hold 的超額報酬率
- **統計顯著性**：使用 t-test 檢驗超額報酬是否顯著（p < 0.05）

#### 2.3.3 過擬合風險提示

##### 風險指標
1. **參數敏感性**：參數小幅變動時，績效變化 < 10%
2. **退化程度**：測試期相對於訓練期的退化 < 30%
3. **交易次數**：過少（< 10 次）或過多（> 100 次）可能表示過擬合
4. **勝率異常**：勝率過高（> 80%）可能表示過擬合

##### 風險提示等級
- **低風險**：所有指標在可接受範圍內
- **中風險**：1-2 個指標超出範圍
- **高風險**：3 個以上指標超出範圍，建議重新設計策略

---

## 3. 最小可行驗證順序（MVP）

### 階段 1：視覺驗證 v1（優先級：最高）

**目標**：讓使用者能夠直觀看到策略的買賣點，驗證策略行為是否符合預期。

**實作內容**：
1. 擴展現有的 `EquityCurveWidget` 為 K 線圖顯示
2. 整合 `DailySignalFrame` 的買賣信號與理由標籤
3. 在 K 線圖上標記買賣點（綠色向上箭頭、紅色向下箭頭）
4. Hover tooltip 顯示理由標籤

**驗證標準**：
- ✅ 使用者能夠從 K 線圖看到策略的進出場時點
- ✅ 使用者能夠看到買賣理由（reason_tags）
- ✅ 視覺驗證能夠發現策略邏輯問題（如買在高點、賣在低點）

**預估工時**：3-5 天

**風險等級**：低（已有 EquityCurveWidget 基礎，只需擴展為 K 線圖）

### 階段 2：Baseline 對比（優先級：高）

**目標**：提供基準比較，評估策略是否優於被動持有或隨機策略。

**實作內容**：
1. 實作 Buy & Hold 基準策略
2. 實作 Random Entry 基準策略（可選）
3. 在回測報告中顯示 Baseline 對比結果
4. 計算統計顯著性（t-test）

**驗證標準**：
- ✅ 回測報告包含 Baseline 對比結果
- ✅ 顯示相對績效（超額報酬率）
- ✅ 顯示統計顯著性（p-value）

**預估工時**：2-3 天

**風險等級**：低（邏輯簡單，只需計算基準策略績效）

### 階段 3：Walk-Forward 暖機期（優先級：高）

**目標**：確保技術指標計算有足夠歷史數據，提升 Walk-Forward 驗證的可靠性。

**實作內容**：
1. 在 `WalkForwardService` 中加入暖機期參數
2. 訓練期從「開始日期 + 暖機期」開始計算
3. 在 Walk-Forward 報告中顯示暖機期資訊

**驗證標準**：
- ✅ Walk-Forward 驗證包含暖機期處理
- ✅ 訓練期從暖機期後開始計算
- ✅ 報告中顯示暖機期長度

**預估工時**：1-2 天

**風險等級**：低（只需修改日期計算邏輯）

### 階段 4：過擬合風險提示（優先級：中）

**目標**：識別過擬合風險，提示使用者策略可能不穩定。

**實作內容**：
1. 計算過擬合風險指標（參數敏感性、退化程度、交易次數、勝率）
2. 在回測報告中顯示風險提示等級
3. 提供風險說明與建議

**驗證標準**：
- ✅ 回測報告包含過擬合風險提示
- ✅ 風險提示等級明確（低/中/高）
- ✅ 提供風險說明與建議

**預估工時**：2-3 天

**風險等級**：中（需要定義風險指標的閾值，可能需要調整）

### 階段 5：Promote 機制 v1（優先級：中）

**目標**：讓回測結果可以升級為策略版本，並掛載到 Profile。

**實作內容**：
1. 建立 `PromotedStrategyVersion` 資料結構
2. 實作升級條件檢查（Walk-Forward、Baseline 對比）
3. 實作升級流程（從回測結果生成 strategy_version）
4. 實作 Profile 掛載功能（可選）

**驗證標準**：
- ✅ 回測結果可以升級為 strategy_version
- ✅ 升級條件檢查正確（Walk-Forward、Baseline 對比）
- ✅ 升級後的策略版本可以在推薦中使用

**預估工時**：5-7 天

**風險等級**：高（涉及版本管理、Profile 整合，可能複雜）

---

## 4. 高風險設計點與簡化建議

### 4.1 Promote 機制（高風險）

#### 風險點
1. **版本管理複雜**：需要管理 strategy_version 的版本號、依賴關係、回滾機制
2. **Profile 整合複雜**：需要處理 Profile 與 strategy_version 的關聯、版本衝突
3. **升級條件判斷**：需要定義明確的升級條件，避免過度寬鬆或嚴格

#### 簡化建議
1. **階段 1：簡化版本管理**
   - 不使用複雜的版本號系統（如語義化版本）
   - 使用簡單的版本號（如 "1.0", "1.1", "2.0"）
   - 不實作版本回滾機制（先做單向升級）

2. **階段 2：簡化 Profile 整合**
   - 不強制掛載到 Profile（可選功能）
   - 升級後的策略版本可以獨立使用
   - 後續再實作 Profile 整合

3. **階段 3：明確升級條件**
   - 使用固定的升級條件（Walk-Forward 一致性 >= 60%，退化程度 < 40%）
   - 不實作動態調整升級條件（先做固定規則）

#### Fallback 方案
如果 Promote 機制複雜度過高，可以：
- 先實作「保存為 Preset」功能（使用現有的 PresetService）
- 後續再升級為完整的 Promote 機制

### 4.2 K 線圖標記（中風險）

#### 風險點
1. **圖表庫選擇**：需要選擇合適的圖表庫（matplotlib、PyQtGraph、mplfinance）
2. **性能問題**：大量 K 線數據可能導致渲染緩慢
3. **互動體驗**：hover tooltip、縮放、平移等功能需要實作

#### 簡化建議
1. **階段 1：使用現有基礎**
   - 基於現有的 `EquityCurveWidget`（使用 matplotlib）
   - 使用 `mplfinance` 繪製 K 線圖（簡單易用）
   - 不實作複雜的互動功能（先做基本標記）

2. **階段 2：性能優化**
   - 限制顯示的 K 線數量（如最近 200 根）
   - 使用數據抽樣（如每 5 根顯示 1 根）
   - 後續再優化性能

#### Fallback 方案
如果 K 線圖標記技術難度大，可以：
- 先提供文字列表形式的買賣點說明
- 後續再升級為視覺標記

### 4.3 Walk-Forward 暖機期（低風險）

#### 風險點
1. **暖機期長度定義**：不同策略可能需要不同的暖機期長度
2. **數據可用性**：暖機期可能導致可用數據減少

#### 簡化建議
1. **固定暖機期長度**：使用固定的暖機期長度（20 個交易日）
2. **可調整參數**：後續再實作可調整的暖機期長度

### 4.4 過擬合風險提示（中風險）

#### 風險點
1. **風險指標定義**：需要定義明確的風險指標閾值
2. **風險提示準確性**：風險提示可能過於保守或過於寬鬆

#### 簡化建議
1. **固定風險指標閾值**：使用固定的風險指標閾值（如參數敏感性 < 10%，退化程度 < 30%）
2. **保守提示**：先做保守的風險提示（寧可多提示，不要漏掉）
3. **後續調整**：根據實際使用情況調整風險指標閾值

---

## 5. 優先級判斷

### 必須先做（Phase 3.3b 核心）

1. **視覺驗證 v1**（優先級：最高）
   - 理由：是策略合理性的基礎驗證，使用者需要直觀看到策略行為
   - 依賴：無（可獨立實作）
   - 風險：低

2. **Baseline 對比**（優先級：高）
   - 理由：是評估策略有效性的基礎，必須優於基準才能考慮 Promote
   - 依賴：無（可獨立實作）
   - 風險：低

3. **Walk-Forward 暖機期**（優先級：高）
   - 理由：提升 Walk-Forward 驗證的可靠性，是 Promote 機制的基礎
   - 依賴：現有的 WalkForwardService
   - 風險：低

### 可以延後（Phase 3.3b 增強）

4. **過擬合風險提示**（優先級：中）
   - 理由：是策略穩健性的重要指標，但不是 Promote 機制的必要條件
   - 依賴：Walk-Forward 結果、Baseline 對比結果
   - 風險：中

5. **Promote 機制 v1**（優先級：中）
   - 理由：是 Phase 3.3b 的核心目標，但可以分階段實作
   - 依賴：Walk-Forward 驗證、Baseline 對比、過擬合風險提示（可選）
   - 風險：高

### 建議實作順序

**第一階段（1-2 週）**：
1. 視覺驗證 v1（K 線標記買賣點）
2. Baseline 對比
3. Walk-Forward 暖機期

**第二階段（1-2 週）**：
4. 過擬合風險提示
5. Promote 機制 v1（簡化版：保存為 Preset）

**第三階段（可選，後續優化）**：
6. Promote 機制完整版（版本管理、Profile 整合）

---

## 6. 驗收標準（Exit Criteria）

### Phase 3.3b 最小驗收標準

1. **視覺驗證**：
   - ✅ 使用者能夠從 K 線圖看到策略的進出場時點
   - ✅ 使用者能夠看到買賣理由（reason_tags）

2. **Baseline 對比**：
   - ✅ 回測報告包含 Buy & Hold 對比結果
   - ✅ 顯示相對績效（超額報酬率）

3. **Walk-Forward 暖機期**：
   - ✅ Walk-Forward 驗證包含暖機期處理
   - ✅ 訓練期從暖機期後開始計算

4. **Promote 機制（簡化版）**：
   - ✅ 回測結果可以保存為 Preset（使用現有的 PresetService）
   - ✅ 保存的 Preset 可以在推薦中使用

### Phase 3.3b 完整驗收標準（可選）

5. **過擬合風險提示**：
   - ✅ 回測報告包含過擬合風險提示
   - ✅ 風險提示等級明確（低/中/高）

6. **Promote 機制完整版**：
   - ✅ 回測結果可以升級為 strategy_version
   - ✅ 升級條件檢查正確（Walk-Forward、Baseline 對比）
   - ✅ 升級後的策略版本可以掛載到 Profile

---

## 7. 技術實作建議

### 7.1 K 線圖標記實作

#### 使用 mplfinance
```python
import mplfinance as mpf

# 繪製 K 線圖
mpf.plot(
    df,
    type='candle',
    style='yahoo',
    addplot=addplot_signals,  # 添加買賣點標記
    volume=True,
    title='策略視覺驗證'
)
```

#### 整合現有 EquityCurveWidget
- 擴展現有的 `EquityCurveWidget` 為 `CandlestickWidget`
- 使用 `DailySignalFrame` 的 `signals` 和 `reason_tags` 欄位
- 在 K 線圖上標記買賣點

### 7.2 Baseline 對比實作

#### Buy & Hold 策略
```python
def calculate_buy_hold_return(df, start_date, end_date):
    """計算 Buy & Hold 報酬率"""
    start_price = df.loc[start_date, '收盤價']
    end_price = df.loc[end_date, '收盤價']
    return (end_price - start_price) / start_price
```

#### 統計顯著性檢驗
```python
from scipy import stats

def test_significance(strategy_returns, baseline_returns):
    """檢驗策略報酬是否顯著優於基準"""
    t_stat, p_value = stats.ttest_ind(strategy_returns, baseline_returns)
    return t_stat, p_value
```

### 7.3 Walk-Forward 暖機期實作

#### 修改 WalkForwardService
```python
def walk_forward(
    self,
    ...
    warmup_days: int = 20,  # 暖機期天數
    ...
):
    # 計算實際訓練期（從開始日期 + 暖機期開始）
    actual_train_start = start_dt + timedelta(days=warmup_days)
    ...
```

### 7.4 Promote 機制實作

#### 簡化版：保存為 Preset
```python
def promote_to_preset(
    self,
    run_id: str,
    preset_name: str
) -> str:
    """將回測結果保存為 Preset"""
    run = self.backtest_repository.get_run(run_id)
    
    # 提取策略參數
    params = run.strategy_params
    
    # 保存為 Preset
    preset_id = self.preset_service.save_preset(
        name=preset_name,
        strategy_id=run.strategy_id,
        params=params,
        meta={
            'source_run_id': run_id,
            'backtest_summary': {
                'total_return': run.total_return,
                'sharpe_ratio': run.sharpe_ratio,
                'max_drawdown': run.max_drawdown
            }
        }
    )
    
    return preset_id
```

---

## 8. 文檔維護

### 8.1 版本控制
- **版本號格式**：`v<major>.<minor>.<patch>`
- **重大變更**：修改 Promote 機制邏輯 → 升級 major 版本
- **功能新增**：新增視覺驗證、Baseline 對比 → 升級 minor 版本
- **文檔修正**：修正錯誤、補充說明 → 升級 patch 版本

### 8.2 變更記錄
- **變更日期**：記錄每次變更的日期
- **變更內容**：詳細說明變更的功能、邏輯、理由
- **驗證結果**：變更後的測試結果（功能測試、性能測試）
- **影響評估**：變更對系統的影響（提升/下降/無影響）

---

**文檔版本**：v1.0.0  
**最後更新**：2025-01-01  
**維護者**：量化研究團隊

