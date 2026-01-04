# Phase 2 架構設計文檔

## 核心設計原則

### 1. 策略可插拔規格

策略 = 一份可序列化的設定（schema） + 一個可被回測/推薦共用的執行器（executor）

#### StrategySpec（純資料，可存成 JSON/YAML）
```python
@dataclass
class StrategySpec:
    """策略規格（純資料）"""
    strategy_id: str  # 固定 ID，例如 "breakout_momentum_v1"
    strategy_version: str  # 例如 "1.0.0"
    data_version: Optional[str]  # 對應技術指標版本/資料修復版本
    name: str  # 顯示名稱
    description: str  # 策略說明
    regime: List[str]  # 適用 Regime: ['Trend', 'Reversion', 'Breakout']
    risk_level: str  # 'low', 'medium', 'high'
    target_type: str  # 'stock', 'industry', 'both'
    default_params: Dict[str, Any]  # 預設參數
    config: Dict[str, Any]  # 完整策略配置（technical, patterns, signals, filters）
```

#### StrategyExecutor（執行器）
```python
class StrategyExecutor(Protocol):
    """策略執行器介面"""
    
    def generate_signals(
        self, 
        df: pd.DataFrame, 
        spec: StrategySpec
    ) -> pd.DataFrame:
        """
        生成每日信號
        
        Returns:
            DailySignalFrame: index=date，欄位含 signal, score breakdown, reason tags
        """
        ...
```

#### StrategyMeta（元數據）
```python
@dataclass
class StrategyMeta:
    """策略元數據"""
    strategy_id: str
    strategy_version: str
    name: str
    description: str
    regime: List[str]
    risk_level: str
    target_type: str
    default_params: Dict[str, Any]
    risk_description: str  # 風險敘述
    created_at: datetime
    updated_at: datetime
```

### 2. DailySignalFrame（統一輸出格式）

**核心概念**：推薦和回測共用同一條 signal pipeline

```python
DailySignalFrame:
    index: date (pd.DatetimeIndex)
    columns:
        - signal: int  # 1 (買入), 0 (持有), -1 (賣出)
        - score: float  # 總分 (0-100)
        - indicator_score: float
        - pattern_score: float
        - volume_score: float
        - reason_tags: List[str]  # ["breakout_20d_high", "volume_surge", "ma_alignment"]
        - regime_match: bool
        - ... (其他技術指標欄位)
```

**使用方式**：
- **推薦**：只取最後一天（或最後一週）的那行
- **回測**：吃整段 DailySignalFrame

### 3. BacktestService MVP

**最小可用回測**：單策略、單標的、固定規則的交易引擎

#### 核心功能
- **進出場**：signal（1 / 0 / -1）→ 下單（可設隔日開盤/收盤）
- **成本**：手續費、滑價（先常數）
- **風控**：停損/停利/時間停損（先 1~2 種）
- **指標**：CAGR、Sharpe、Max Drawdown、Win rate、Expectancy、Trade count

#### BacktestReportDTO 擴展
```python
@dataclass
class BacktestReportDTO:
    # 基本指標
    total_return: float
    annual_return: float  # CAGR
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    expectancy: float  # 期望值
    
    # 詳細信息
    details: Dict[str, Any]
    equity_curve: pd.DataFrame  # 權益曲線（date, equity）
    trade_list: List[Dict]  # 交易列表（進出場日期、價格、報酬、理由 tags）
    reason_tag_stats: Dict[str, Dict]  # 理由標籤統計
```

### 4. ReasonEngine 升級

**目標**：把理由變成可回測的理由標籤

#### Reason Tags 格式
```python
reason_tags = [
    "breakout_20d_high",      # 突破20日新高
    "volume_surge",          # 成交量暴增
    "ma_alignment",          # 均線多頭排列
    "industry_strength",     # 產業強勢
    "rsi_oversold",          # RSI超賣
    "macd_golden_cross",     # MACD金叉
    ...
]
```

#### 回測後分析
- 「有 volume_surge 的交易勝率是不是更高？」
- 「在 Breakout regime 裡，哪些理由組合最有效？」

### 5. Strategy 版本化

**每個策略都帶**：
- `strategy_id`（固定）
- `strategy_version`（例如 1.0.0）
- `data_version`（可選，對應技術指標版本/資料修復版本）

**回測報告裡一定要寫死**，不然半年後會追不回「當時為什麼賺/賠」。

### 6. 統一資料契約（Data Contract）

**最小資料契約**：
- OHLCV（開高低收量）
- 必備 indicators（MA20, MA60, RSI, MACD, ATR, ADX）
- industry_id（產業代號）

**缺欄位就直接 fail fast**（不要默默用 NaN 繼續）。

## Phase 2 預設策略庫（4 種）

### 1. Breakout Momentum（暴衝型）
- **策略 ID**: `breakout_momentum_v1`
- **適用 Regime**: Breakout, Trend
- **特點**: 20/60 日新高 + 量能放大 + 波動擴張（ATR/BB Width）
- **風險等級**: High

### 2. Trend Following（順勢型）
- **策略 ID**: `trend_following_v1`
- **適用 Regime**: Trend
- **特點**: 均線多頭排列 + ADX 過門檻 + 回踩不破（pullback entry）
- **風險等級**: Medium

### 3. Mean Reversion（均值回歸/穩健型）
- **策略 ID**: `mean_reversion_v1`
- **適用 Regime**: Reversion
- **特點**: RSI/KD 超賣 + 乖離過大 + 均線支撐（偏短線）
- **風險等級**: Low-Medium

### 4. Industry Rotation（產業輪動型）
- **策略 ID**: `industry_rotation_v1`
- **適用 Regime**: Trend, Breakout
- **特點**: 先挑強勢產業 → 再挑產業內相對強勢個股
- **風險等級**: Medium

## 交付目標

### Qt UI 單一策略回測頁

**功能**：
- 選股票代號
- 日期區間
- 策略（下拉選單，從策略庫選擇）
- 資金
- 成本（手續費、滑價）
- 停損停利

**跑完回傳 BacktestReportDTO**

**報告包含**：
1. 績效摘要表（CAGR/Sharpe/MDD/Win rate/Trade count/Expectancy）
2. 權益曲線（matplotlib 存圖再顯示）
3. 交易列表（進出場日期、價格、報酬、理由 tags）
4. 理由標籤統計（哪些理由組合最有效）

## 實作優先順序

### Step 1: 策略可插拔規格 ✅ **進行中**
- [x] 定義 StrategySpec、StrategyExecutor、StrategyMeta (`app_module/strategy_spec.py`)
- [x] 實現 DailySignalFrame 格式 (`app_module/daily_signal.py`)
- [x] 實現理由標籤系統 (`app_module/reason_tags.py`)
- [ ] 升級 ReasonEngine 整合理由標籤生成

### Step 2: BacktestService MVP ✅ **已完成**
- [x] 實現單策略、單標的回測引擎 (`app_module/backtest_service.py`)
- [x] 實現進出場邏輯（signal → 下單）(`backtest_module/broker_simulator.py`)
- [x] 實現成本計算（手續費、滑價）(`backtest_module/broker_simulator.py`)
- [x] 實現風控（停損/停利）(`backtest_module/broker_simulator.py`)
- [x] 實現績效指標計算（CAGR、Sharpe、MDD、Win rate、Expectancy）(`backtest_module/performance_metrics.py`)
- [x] 擴展 BacktestReportDTO（添加 expectancy 欄位）

**核心檔案**：
- `app_module/backtest_service.py`: Service 協調器，整合數據載入、信號生成、撮合、績效計算
- `backtest_module/broker_simulator.py`: 撮合模擬器，實現固定撮合規則（下一根K開盤成交、全倉/空倉、成本計算）
- `backtest_module/performance_metrics.py`: 績效指標計算，生成權益曲線和交易明細

### Step 3: 4 種預設策略 ✅
- [ ] Breakout Momentum
- [ ] Trend Following
- [ ] Mean Reversion
- [ ] Industry Rotation

### Step 4: Qt UI 回測頁 ✅
- [ ] 回測配置界面
- [ ] 回測結果顯示（表格 + 權益曲線）
- [ ] 交易列表顯示
- [ ] 理由標籤統計顯示

### Step 5: 資料契約 ✅
- [ ] 定義最小資料契約
- [ ] 實現資料驗證（fail fast）

## 架構優勢

1. **策略可插拔**：新增策略只需新增 spec + executor，不影響 UI、回測、推薦
2. **推薦與回測共用**：避免兩套邏輯，結果一致
3. **理由可回測**：讓系統真正「會隨交易理解成長」
4. **版本化**：追蹤策略演進，可重現歷史結果
5. **資料契約**：確保資料完整性，fail fast

