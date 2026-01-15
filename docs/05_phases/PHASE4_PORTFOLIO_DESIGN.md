# Phase 4：持倉管理設計規格（Portfolio MVP）

## 概述

Phase 4 建立一個 **Read-only / Decision-support** 的 Position/Portfolio Layer，用於觀察、理解與管理既有策略/股票的部位狀態，**不進行任何自動交易或調倉決策**。

**核心定位**：
- ✅ **觀察與呈現**：顯示當前持倉狀態、來源、條件變化
- ✅ **決策支援**：提供資訊幫助使用者判斷「這筆還對嗎」
- ❌ **不做決策**：不自動下單、不自動調倉、不自動調整權重

---

## 一、Phase 定位

### 此階段屬於

**Read-only / Decision-support**

- 系統只負責**呈現狀態**和**提供資訊**
- 所有決策由使用者做出
- 系統不執行任何自動操作

### 與 Phase 3 的關係

Phase 4 建立在 Phase 3 的研究閉環之上：

```
Phase 3 研究閉環：
推薦 → 回測 → 最佳化 → Promote → 回推薦

Phase 4 持倉管理：
從 Phase 3 的推薦/策略版本 → 記錄進場 → 監控狀態 → 回顧決策
```

**關鍵原則**：
- 每個 Position 必須可追溯回 Phase 3 的產出（Recommendation / Backtest / Strategy version）
- Phase 4 不新增策略或 execution 邏輯
- Phase 4 只做「狀態呈現」和「條件監控」

---

## 二、此階段不做的事（明確排除）

### ❌ 不做自動下單或模擬下單

- 系統不執行任何買賣操作
- 不提供「一鍵下單」功能
- 不模擬交易執行

### ❌ 不做倉位最佳化或風險模型

- 不計算「最佳持倉比例」
- 不提供「風險調整建議」
- 不自動調整部位大小

### ❌ 不根據績效自動調整權重

- 不根據歷史績效自動調整權重
- 不提供「動態再平衡」功能
- 不自動加碼或減碼

### ❌ 不新增策略或 execution 邏輯

- 不新增策略類型
- 不修改 execution 邏輯
- 只使用 Phase 3 已建立的策略和邏輯

---

## 三、核心能力（骨架）

### 1️⃣ Position（單一股票 / 策略）

**資料結構**：

```python
@dataclass
class PositionDTO:
    """持倉資料傳輸對象"""
    # 基本資訊
    position_id: str  # 持倉 ID（唯一標識）
    stock_code: str  # 股票代號
    stock_name: str  # 股票名稱
    
    # 持有狀態
    is_holding: bool  # 當前是否持有（Yes / No）
    entry_date: str  # 進場日期（YYYY-MM-DD）
    holding_days: int  # 已持有天數
    
    # 進場來源（與 Phase 3 關聯）
    entry_source_type: str  # 'recommendation' / 'backtest' / 'strategy_version'
    entry_source_id: str  # 來源 ID（recommendation_result_id / backtest_run_id / strategy_version_id）
    entry_source_name: str  # 來源名稱（用於顯示）
    
    # 進場時的快照（Snapshot）
    entry_snapshot: Dict[str, Any]  # 包含：
        # - recommendation_snapshot: RecommendationResultDTO（如果是從推薦進場）
        # - backtest_snapshot: BacktestRun（如果是從回測進場）
        # - strategy_version_snapshot: StrategyVersion（如果是從策略版本進場）
        # - entry_regime: str  # 進場時的 Regime
        # - entry_total_score: float  # 進場時的 TotalScore
        # - entry_price: float  # 進場價格
        # - entry_reasons: str  # 進場理由
    
    # 當前狀態（對照用）
    current_regime: Optional[str]  # 當前 Regime
    current_total_score: Optional[float]  # 當前 TotalScore
    current_price: Optional[float]  # 當前價格
    
    # 未實現損益（僅顯示，不驅動行為）
    unrealized_pnl: Optional[float]  # 未實現損益（金額）
    unrealized_pnl_pct: Optional[float]  # 未實現損益（百分比）
    
    # 條件監控狀態
    condition_status: str  # 'valid' / 'warning' / 'invalid'
    condition_details: Dict[str, Any]  # 條件監控詳細資訊
        # - regime_changed: bool  # Regime 是否改變
        # - score_degraded: bool  # TotalScore 是否下降
        # - price_change: float  # 價格變化百分比
    
    # 備註
    notes: str  # 使用者備註
    created_at: str  # 建立時間
    updated_at: str  # 最後更新時間
```

**關鍵欄位說明**：

1. **進場來源（entry_source）**：
   - 必須可追溯回 Phase 3 的產出
   - 保存完整的 Snapshot，確保即使原始資料變更，仍能查看進場時的狀態

2. **進場快照（entry_snapshot）**：
   - 保存進場時的完整狀態（Regime、TotalScore、價格、理由）
   - 用於與當前狀態對照，判斷是否「不符合當初進場假設」

3. **條件監控狀態（condition_status）**：
   - `valid`：仍符合進場條件
   - `warning`：部分條件改變，需要關注
   - `invalid`：明顯不符合進場條件

---

### 2️⃣ Portfolio（整體視圖）

**資料結構**：

```python
@dataclass
class PortfolioDTO:
    """投資組合資料傳輸對象"""
    # 基本資訊
    portfolio_id: str  # 投資組合 ID
    portfolio_name: str  # 投資組合名稱
    
    # 持倉總覽
    total_positions: int  # 目前持倉數量
    active_positions: int  # 活躍持倉數量（is_holding=True）
    
    # 持倉分布
    holding_days_distribution: Dict[str, int]  # 持有天數分布
        # {'0-7': 3, '8-30': 5, '31-90': 2, '90+': 1}
    profile_distribution: Dict[str, int]  # Profile 分布
        # {'profile_1': 5, 'profile_2': 3, ...}
    strategy_version_distribution: Dict[str, int]  # 策略版本分布
        # {'version_1': 4, 'version_2': 2, ...}
    
    # 未實現損益總覽（僅資訊呈現）
    total_unrealized_pnl: float  # 總未實現損益（金額）
    total_unrealized_pnl_pct: float  # 總未實現損益（百分比）
    positions_pnl_breakdown: List[Dict[str, Any]]  # 各持倉損益明細
    
    # 與 Benchmark 的整體對比（資訊性）
    benchmark_comparison: Optional[Dict[str, Any]] = None
        # - benchmark_type: str  # 'buy_hold' / 'market_index'
        # - portfolio_return: float  # 投資組合報酬率
        # - benchmark_return: float  # 基準報酬率
        # - excess_return: float  # 超額報酬率
    
    # 條件監控總覽
    condition_summary: Dict[str, int]  # 條件狀態分布
        # {'valid': 8, 'warning': 2, 'invalid': 1}
    
    # 持倉列表
    positions: List[PositionDTO]  # 所有持倉列表
    
    # 時間戳
    created_at: str  # 建立時間
    updated_at: str  # 最後更新時間
```

**關鍵欄位說明**：

1. **持倉分布**：
   - 幫助使用者了解持倉的結構和來源
   - 用於識別「哪些 Profile/Strategy version 表現較好」

2. **未實現損益總覽**：
   - 僅作為資訊呈現，不驅動任何自動行為
   - 幫助使用者了解整體表現

3. **Benchmark 對比**：
   - 資訊性對比，不作為決策依據
   - 幫助使用者了解投資組合相對於基準的表現

---

### 3️⃣ 與 Phase 3 的關聯（關鍵）

**每個 Position 必須可追溯回**：

1. **Recommendation Snapshot**：
   - 如果從「推薦分析」進場，保存完整的 `RecommendationResultDTO`
   - 包含：推薦配置、推薦理由、當時 Regime、推薦時間

2. **Backtest / Strategy version**：
   - 如果從「回測結果」或「策略版本」進場，保存對應的 ID 和 Snapshot
   - 包含：策略參數、回測績效、驗證狀態

3. **明確標示「此層不做決策，只做狀態呈現」**：
   - 在 UI 中明確標示「此為資訊呈現，不作為交易建議」
   - 所有數值僅供參考，不觸發任何自動操作

---

## 四、資料儲存結構

### Position 儲存

**儲存位置**：`{output_root}/portfolio/positions/`

**儲存格式**：JSON 檔案（每個 Position 一個檔案）

**檔案命名**：`{position_id}.json`

**資料結構範例**：

```json
{
  "position_id": "pos_20260102_2330_001",
  "stock_code": "2330",
  "stock_name": "台積電",
  "is_holding": true,
  "entry_date": "2026-01-02",
  "holding_days": 5,
  "entry_source_type": "recommendation",
  "entry_source_id": "rec_20260102_120000",
  "entry_source_name": "2026-01-02 推薦結果",
  "entry_snapshot": {
    "recommendation_snapshot": {
      "result_id": "rec_20260102_120000",
      "result_name": "2026-01-02 推薦結果",
      "config": {...},
      "regime": "Trend",
      "created_at": "2026-01-02T12:00:00"
    },
    "entry_regime": "Trend",
    "entry_total_score": 75.5,
    "entry_price": 580.0,
    "entry_reasons": "技術指標強勢，圖形模式突破"
  },
  "current_regime": "Trend",
  "current_total_score": 72.3,
  "current_price": 585.0,
  "unrealized_pnl": 5000.0,
  "unrealized_pnl_pct": 0.86,
  "condition_status": "valid",
  "condition_details": {
    "regime_changed": false,
    "score_degraded": true,
    "price_change": 0.86
  },
  "notes": "",
  "created_at": "2026-01-02T12:00:00",
  "updated_at": "2026-01-07T09:00:00"
}
```

### Portfolio 儲存

**儲存位置**：`{output_root}/portfolio/portfolio.json`

**儲存格式**：單一 JSON 檔案（包含所有持倉的 ID 列表和總覽資訊）

---

## 五、服務層設計（骨架）

### PositionService

**檔案位置**：`app_module/position_service.py`

**職責**：
- 管理 Position 的 CRUD 操作
- 更新 Position 的當前狀態（價格、TotalScore、Regime）
- 計算未實現損益
- 監控條件變化

**主要方法**（骨架）：

```python
class PositionService:
    """持倉服務類"""
    
    def create_position(
        self,
        stock_code: str,
        entry_source_type: str,
        entry_source_id: str,
        entry_price: float,
        entry_snapshot: Dict[str, Any]
    ) -> PositionDTO:
        """建立新持倉"""
        pass
    
    def get_position(self, position_id: str) -> Optional[PositionDTO]:
        """取得持倉資訊"""
        pass
    
    def list_positions(self, is_holding: Optional[bool] = None) -> List[PositionDTO]:
        """列出所有持倉"""
        pass
    
    def update_position_status(
        self,
        position_id: str
    ) -> PositionDTO:
        """更新持倉當前狀態（價格、TotalScore、Regime）"""
        pass
    
    def check_condition(self, position_id: str) -> Dict[str, Any]:
        """檢查持倉條件狀態"""
        pass
    
    def close_position(
        self,
        position_id: str,
        exit_date: str,
        exit_price: float,
        exit_reasons: str
    ) -> PositionDTO:
        """平倉（標記為不再持有）"""
        pass
```

### PortfolioService

**檔案位置**：`app_module/portfolio_service.py`

**職責**：
- 管理 Portfolio 總覽
- 計算持倉分布
- 計算整體未實現損益
- 與 Benchmark 對比

**主要方法**（骨架）：

```python
class PortfolioService:
    """投資組合服務類"""
    
    def get_portfolio(self) -> PortfolioDTO:
        """取得投資組合總覽"""
        pass
    
    def update_portfolio(self) -> PortfolioDTO:
        """更新投資組合資訊"""
        pass
    
    def get_benchmark_comparison(
        self,
        benchmark_type: str = 'buy_hold'
    ) -> Dict[str, Any]:
        """取得與 Benchmark 的對比"""
        pass
```

---

## 六、UI 設計（骨架）

### PortfolioView

**檔案位置**：`ui_qt/views/portfolio_view.py`

**主要區塊**：

1. **持倉總覽區塊**：
   - 目前持倉數量
   - 總未實現損益
   - 條件狀態分布

2. **持倉列表區塊**：
   - 表格顯示所有持倉
   - 欄位：股票代號、名稱、進場日期、持有天數、未實現損益、條件狀態
   - 可點擊查看詳細資訊

3. **持倉詳細資訊區塊**：
   - 進場來源（可連結回 Phase 3）
   - 進場快照 vs 當前狀態對照
   - 條件監控結果

4. **明確標示**：
   - 在 UI 頂部顯示：「此為資訊呈現，不作為交易建議」
   - 所有數值僅供參考，不觸發任何自動操作

---

## 七、成功標準（DoD）

### 使用者可以一眼回答：

1. **我現在有哪些部位？從哪來？**
   - ✅ 可以在 Portfolio 視圖看到所有持倉列表
   - ✅ 每個持倉都標示進場來源（Recommendation / Backtest / Strategy version）
   - ✅ 可以點擊查看進場時的完整 Snapshot

2. **這些部位是否已經「不符合當初進場假設」？**
   - ✅ 可以看到條件監控狀態（valid / warning / invalid）
   - ✅ 可以看到進場時 vs 當前狀態的對照（Regime、TotalScore）
   - ✅ 可以看到條件變化的詳細資訊

3. **如果要調整，我該回到 Phase 3 哪一層重新研究？**
   - ✅ 可以從 Position 追溯到 Phase 3 的原始產出
   - ✅ 可以清楚看到問題出在哪一層（Universe / Regime / Score / Execution）
   - ✅ 可以回到 Phase 3 對應的 Tab 重新研究

### 不引入任何自動化風險

- ✅ 系統不執行任何自動操作
- ✅ 所有數值僅供參考
- ✅ UI 明確標示「此為資訊呈現，不作為交易建議」

---

## 八、實作順序建議

### 階段 1：資料結構與服務層骨架（1-2 天）

1. 建立 `PositionDTO` 和 `PortfolioDTO`
2. 建立 `PositionService` 和 `PortfolioService` 骨架
3. 建立資料儲存結構（JSON 檔案）

### 階段 2：基本 CRUD 功能（2-3 天）

1. 實作 `create_position`（從 Phase 3 建立持倉）
2. 實作 `get_position` 和 `list_positions`
3. 實作 `update_position_status`（更新當前狀態）

### 階段 3：條件監控（2-3 天）

1. 實作 `check_condition`（檢查條件變化）
2. 實作 Regime 和 TotalScore 對照邏輯
3. 實作條件狀態判斷（valid / warning / invalid）

### 階段 4：UI 骨架（2-3 天）

1. 建立 `PortfolioView` 基本結構
2. 實作持倉列表顯示
3. 實作持倉詳細資訊顯示
4. 添加「此為資訊呈現」標示

### 階段 5：與 Phase 3 整合（1-2 天）

1. 在 RecommendationView 添加「建立持倉」按鈕
2. 在 BacktestView 添加「建立持倉」按鈕
3. 確保可以追溯回 Phase 3 的原始產出

---

## 九、注意事項

### 資料一致性

- Position 的 `entry_snapshot` 必須保存完整的 Snapshot
- 即使 Phase 3 的原始資料變更，Position 仍能查看進場時的狀態

### 性能考量

- `update_position_status` 可能需要批量更新多個 Position
- 考慮使用 Worker 線程進行非同步更新

### 向後兼容

- Phase 4 不影響 Phase 3 的任何功能
- Phase 3 的研究閉環完全獨立運作

---

**文檔版本**：v1.0  
**最後更新**：2026-01-07  
**適用階段**：Phase 4.1 (Portfolio MVP)

