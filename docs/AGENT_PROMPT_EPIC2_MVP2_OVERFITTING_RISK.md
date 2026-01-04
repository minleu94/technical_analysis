# Agent Prompt: Epic 2 MVP-2 - 過擬合風險提示（架構規劃）

**預估時間**：2-3 小時（僅規劃，不實作）  
**目標**：為 Epic 2 MVP-2（過擬合風險提示）功能進行架構層級規劃，定義風險指標計算方法、資料結構、整合點與驗證策略

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

---

## 1) 任務目標

為 Epic 2 MVP-2（過擬合風險提示）功能進行架構層級規劃，包含：

1. **風險指標定義**：定義過擬合風險指標的計算方法與判斷標準
2. **資料結構設計**：定義 `overfitting_risk` 欄位的資料結構
3. **整合點分析**：分析需要修改的模組與整合點
4. **驗證策略**：定義驗證方法與測試案例
5. **風險評估**：識別潛在架構風險與緩解措施

**注意**：本任務僅進行規劃，不進行實作。實作將由後續任務完成。

---

## 2) 背景與前置條件

### 2.1 Epic 2 MVP-1 完成狀態

- ✅ **Walk-Forward 暖機期**：已完成並驗證（29/29 測試通過）
- ✅ **Baseline 對比**：已完成並驗證（Buy & Hold 對比）
- ✅ **驗證報告**：`output/qa/epic2_mvp1_validation/VALIDATION_REPORT.md`
- ✅ **驗證腳本**：`scripts/qa_validate_epic2_mvp1.py`

### 2.2 相關文檔

- `docs/PHASE_3_3B_IMPLEMENTATION_PLAN.md`：實施規劃文檔
- `docs/PHASE3_3B_RESEARCH_DESIGN.md`：研究設計規格
- `docs/DEVELOPMENT_ROADMAP.md`：開發路線圖

### 2.3 現有架構

**相關模組**：
- `backtest_module/performance_metrics.py`：績效指標計算
- `app_module/backtest_service.py`：回測服務
- `app_module/dtos.py`：資料傳輸對象定義
- `app_module/walkforward_service.py`：Walk-Forward 驗證服務

**現有資料結構**：
- `BacktestReportDTO`：已包含 `baseline_comparison: Optional[Dict[str, Any]]`
- `WalkForwardResult`：已包含 `warmup_days` 欄位

---

## 3) 過擬合風險指標定義

### 3.1 風險指標清單（MVP 版本）

**必須實作的指標**（最低可用版本）：

1. **參數敏感性（Parameter Sensitivity）**
   - **定義**：策略績效對參數變化的敏感程度
   - **計算方法**：在參數最佳化過程中，計算參數微小變化（±5%）對績效的影響
   - **風險判斷**：如果參數微小變化導致績效大幅波動（>30%），視為高風險

2. **Walk-Forward 退化程度（Walk-Forward Degradation）**
   - **定義**：Walk-Forward 測試期表現相對於訓練期的退化程度
   - **計算方法**：`(train_performance - test_performance) / train_performance`
   - **風險判斷**：如果退化程度 > 40%，視為高風險

3. **一致性指標（Consistency）**
   - **定義**：Walk-Forward 多個 Fold 之間表現的一致性
   - **計算方法**：計算多個 Fold 的 Sharpe Ratio 標準差
   - **風險判斷**：如果標準差 > 0.5，視為高風險

**可選指標**（可延後實作）：

4. **樣本外表現（Out-of-Sample Performance）**
   - 如果有多個回測期間，比較不同期間的表現差異

5. **參數分佈分析（Parameter Distribution）**
   - 分析最佳化過程中參數的分佈，如果過於集中，可能表示過擬合

### 3.2 風險等級定義

**風險等級**：
- **低風險（Low）**：所有指標都在可接受範圍內
- **中風險（Medium）**：部分指標超出可接受範圍，但仍在容忍範圍內
- **高風險（High）**：多個指標超出可接受範圍，或單一指標嚴重超標

**風險判斷邏輯**（MVP 版本）：
```python
def calculate_risk_level(metrics: Dict[str, float]) -> str:
    """計算過擬合風險等級"""
    risk_score = 0
    
    # 參數敏感性檢查
    if metrics.get('parameter_sensitivity', 0) > 0.3:
        risk_score += 2
    elif metrics.get('parameter_sensitivity', 0) > 0.15:
        risk_score += 1
    
    # Walk-Forward 退化程度檢查
    if metrics.get('degradation', 0) > 0.4:
        risk_score += 2
    elif metrics.get('degradation', 0) > 0.2:
        risk_score += 1
    
    # 一致性檢查
    if metrics.get('consistency_std', 0) > 0.5:
        risk_score += 2
    elif metrics.get('consistency_std', 0) > 0.3:
        risk_score += 1
    
    # 判斷風險等級
    if risk_score >= 4:
        return 'high'
    elif risk_score >= 2:
        return 'medium'
    else:
        return 'low'
```

---

## 4) 資料結構設計

### 4.1 BacktestReportDTO 擴充

**新增欄位**：
```python
@dataclass
class BacktestReportDTO:
    # ... 現有欄位 ...
    baseline_comparison: Optional[Dict[str, Any]] = None  # 已存在
    overfitting_risk: Optional[Dict[str, Any]] = None  # 新增
```

**overfitting_risk 資料結構**：
```python
{
    'risk_level': str,  # 'low' | 'medium' | 'high'
    'risk_score': float,  # 0.0 - 10.0（風險分數）
    'metrics': {
        'parameter_sensitivity': float,  # 參數敏感性（0.0 - 1.0）
        'degradation': float,  # Walk-Forward 退化程度（0.0 - 1.0）
        'consistency_std': float,  # 一致性標準差（0.0 - 1.0）
    },
    'warnings': List[str],  # 風險警告訊息（繁體中文）
    'recommendations': List[str],  # 改善建議（繁體中文）
    'calculated_at': str,  # 計算時間（ISO 8601 格式）
}
```

### 4.2 WalkForwardResult 擴充（可選）

如果需要在 Walk-Forward 結果中包含過擬合風險資訊：
```python
@dataclass
class WalkForwardResult:
    # ... 現有欄位 ...
    warmup_days: int = 0  # 已存在
    overfitting_risk: Optional[Dict[str, Any]] = None  # 新增（可選）
```

---

## 5) 整合點分析

### 5.1 需要修改的模組

#### 5.1.1 `backtest_module/performance_metrics.py`（擴充）

**新增方法**：
```python
class PerformanceMetrics:
    # ... 現有方法 ...
    
    def calculate_parameter_sensitivity(
        self,
        backtest_results: List[BacktestReportDTO],
        base_params: Dict[str, Any],
        param_variations: Dict[str, float] = None
    ) -> float:
        """計算參數敏感性
        
        Args:
            backtest_results: 參數最佳化過程中的回測結果列表
            base_params: 基準參數
            param_variations: 參數變化範圍（預設 ±5%）
        
        Returns:
            參數敏感性分數（0.0 - 1.0）
        """
        pass
    
    def calculate_walkforward_degradation(
        self,
        train_performance: Dict[str, float],
        test_performance: Dict[str, float]
    ) -> float:
        """計算 Walk-Forward 退化程度
        
        Args:
            train_performance: 訓練期績效指標
            test_performance: 測試期績效指標
        
        Returns:
            退化程度（0.0 - 1.0）
        """
        pass
    
    def calculate_consistency(
        self,
        fold_performances: List[Dict[str, float]]
    ) -> float:
        """計算 Walk-Forward 一致性
        
        Args:
            fold_performances: 多個 Fold 的績效指標列表
        
        Returns:
            一致性標準差（0.0 - 1.0）
        """
        pass
    
    def calculate_overfitting_risk(
        self,
        backtest_report: BacktestReportDTO,
        walkforward_result: Optional[WalkForwardResult] = None,
        optimization_results: Optional[List[BacktestReportDTO]] = None
    ) -> Dict[str, Any]:
        """計算過擬合風險
        
        Args:
            backtest_report: 回測報告
            walkforward_result: Walk-Forward 驗證結果（可選）
            optimization_results: 參數最佳化結果列表（可選）
        
        Returns:
            過擬合風險資訊字典
        """
        pass
```

#### 5.1.2 `app_module/backtest_service.py`（擴充）

**修改方法**：
```python
class BacktestService:
    # ... 現有方法 ...
    
    def _generate_backtest_report(
        self,
        # ... 現有參數 ...
        calculate_overfitting_risk: bool = True  # 新增參數
    ) -> BacktestReportDTO:
        """生成回測報告（擴充過擬合風險計算）"""
        # ... 現有邏輯 ...
        
        # 計算過擬合風險（如果啟用）
        if calculate_overfitting_risk:
            overfitting_risk = self._calculate_overfitting_risk(
                backtest_report,
                walkforward_result,
                optimization_results
            )
            backtest_report.overfitting_risk = overfitting_risk
        
        return backtest_report
    
    def _calculate_overfitting_risk(
        self,
        backtest_report: BacktestReportDTO,
        walkforward_result: Optional[WalkForwardResult] = None,
        optimization_results: Optional[List[BacktestReportDTO]] = None
    ) -> Dict[str, Any]:
        """計算過擬合風險（內部方法）"""
        # 調用 PerformanceMetrics.calculate_overfitting_risk()
        pass
```

#### 5.1.3 `app_module/dtos.py`（擴充）

**修改 BacktestReportDTO**：
```python
@dataclass
class BacktestReportDTO:
    # ... 現有欄位 ...
    baseline_comparison: Optional[Dict[str, Any]] = None
    overfitting_risk: Optional[Dict[str, Any]] = None  # 新增
```

#### 5.1.4 `app_module/walkforward_service.py`（擴充，可選）

如果需要在 Walk-Forward 驗證時計算過擬合風險：
```python
class WalkForwardService:
    # ... 現有方法 ...
    
    def walk_forward(
        self,
        # ... 現有參數 ...
        calculate_overfitting_risk: bool = True  # 新增參數
    ) -> WalkForwardResult:
        """執行 Walk-Forward 驗證（擴充過擬合風險計算）"""
        # ... 現有邏輯 ...
        
        # 計算過擬合風險（如果啟用）
        if calculate_overfitting_risk:
            overfitting_risk = self._calculate_overfitting_risk(result)
            result.overfitting_risk = overfitting_risk
        
        return result
```

---

## 6) 驗證策略

### 6.1 單元測試

**測試案例**：
1. `calculate_parameter_sensitivity()` 基本功能測試
2. `calculate_walkforward_degradation()` 基本功能測試
3. `calculate_consistency()` 基本功能測試
4. `calculate_overfitting_risk()` 整合測試
5. 風險等級判斷邏輯測試
6. 邊界條件測試（極端值、空數據等）

### 6.2 整合測試

**測試案例**：
1. `BacktestService` 整合過擬合風險計算
2. `BacktestReportDTO` 序列化測試（包含 `overfitting_risk`）
3. Walk-Forward 驗證整合測試（如果實作）

### 6.3 驗證腳本

**新增驗證腳本**：`scripts/qa_validate_epic2_mvp2.py`

**驗證範圍**：
- 風險指標計算正確性
- 資料結構完整性
- 整合點正確性
- 向後兼容性（`overfitting_risk` 為 Optional）

---

## 7) 風險評估與緩解措施

### 7.1 架構風險

**風險 1：參數敏感性計算需要最佳化結果**
- **描述**：計算參數敏感性需要參數最佳化過程中的多個回測結果
- **影響**：如果沒有執行參數最佳化，無法計算參數敏感性
- **緩解措施**：
  - 將參數敏感性設為可選指標
  - 如果沒有最佳化結果，跳過參數敏感性計算
  - 在風險報告中標註「參數敏感性未計算（缺少最佳化結果）」

**風險 2：Walk-Forward 結果可能不存在**
- **描述**：過擬合風險計算依賴 Walk-Forward 驗證結果
- **影響**：如果沒有執行 Walk-Forward 驗證，無法計算退化程度和一致性
- **緩解措施**：
  - 將 Walk-Forward 相關指標設為可選
  - 如果沒有 Walk-Forward 結果，僅計算可用的指標
  - 在風險報告中標註「部分指標未計算（缺少 Walk-Forward 結果）」

**風險 3：計算複雜度可能影響性能**
- **描述**：過擬合風險計算可能涉及大量數據處理
- **影響**：可能導致回測報告生成變慢
- **緩解措施**：
  - 使用 Feature Flag 控制是否計算過擬合風險
  - 將計算設為可選（預設開啟，但可關閉）
  - 考慮異步計算（如果性能問題嚴重）

### 7.2 向後兼容性

**保證措施**：
1. `overfitting_risk` 欄位為 `Optional`，預設為 `None`
2. 所有新增參數都有預設值（`calculate_overfitting_risk=True`）
3. 現有程式碼不傳入新參數時行為不變（僅新增欄位）

---

## 8) 實施檢查清單

### 8.1 規劃階段（本任務）

- [ ] 風險指標定義完成
- [ ] 資料結構設計完成
- [ ] 整合點分析完成
- [ ] 驗證策略定義完成
- [ ] 風險評估完成

### 8.2 實作階段（後續任務）

- [ ] 實作 `PerformanceMetrics` 新增方法
- [ ] 實作 `BacktestService` 整合邏輯
- [ ] 更新 `BacktestReportDTO` 資料結構
- [ ] 實作單元測試
- [ ] 實作整合測試
- [ ] 實作驗證腳本
- [ ] 更新文檔

---

## 9) 輸出要求

### 9.1 規劃文檔

**必須產出**：
1. **架構設計文檔**（Markdown 格式）
   - 風險指標計算方法詳細說明
   - 資料結構完整定義
   - 整合點詳細分析
   - 驗證策略完整定義

2. **實作檢查清單**（Markdown 格式）
   - 詳細的實作步驟
   - 每個步驟的驗收標準
   - 測試案例清單

### 9.2 文檔位置

- 架構設計文檔：`docs/EPIC2_MVP2_ARCHITECTURE_DESIGN.md`
- 實作檢查清單：`docs/EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md`

---

## 10) 參考資料

### 10.1 相關文檔

- `docs/PHASE_3_3B_IMPLEMENTATION_PLAN.md`：實施規劃
- `docs/PHASE3_3B_RESEARCH_DESIGN.md`：研究設計規格
- `docs/AGENT_PROMPT_EPIC2_MVP1_BASELINE_WARMUP.md`：Epic 2 MVP-1 實作 prompt

### 10.2 過擬合檢測方法參考

- **參數敏感性分析**：計算參數變化對績效的影響
- **Walk-Forward 驗證**：比較訓練期與測試期表現
- **一致性分析**：分析多個 Fold 之間的一致性
- **樣本外測試**：使用完全獨立的數據集測試

---

## 11) 檢查清單

### 規劃前檢查
- [ ] 已閱讀相關文檔（`PHASE_3_3B_IMPLEMENTATION_PLAN.md`、`PHASE3_3B_RESEARCH_DESIGN.md`）
- [ ] 已確認 Epic 2 MVP-1 完成狀態
- [ ] 已理解現有架構與資料結構

### 規劃執行
- [ ] 風險指標定義完成
- [ ] 資料結構設計完成
- [ ] 整合點分析完成
- [ ] 驗證策略定義完成
- [ ] 風險評估完成

### 規劃後
- [ ] 生成架構設計文檔
- [ ] 生成實作檢查清單
- [ ] 更新 `PHASE_3_3B_IMPLEMENTATION_PLAN.md`（標註規劃完成）

---

**版本**：v1.0（架構規劃版）  
**預估時間**：2-3 小時（僅規劃，不實作）  
**最後更新**：2025-12-30

