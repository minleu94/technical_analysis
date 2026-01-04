# Agent Prompt: 建立 decision_module 骨架與橋接層

## 1) 任務目標

建立 `decision_module/` 目錄結構，並創建適配器（adapter）模組作為橋接層，讓 `app_module` 從依賴 `ui_app` 改為依賴 `decision_module`，同時保持所有現有業務邏輯行為完全不變。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

## 2) 影響範圍

### 新增檔案（6 個適配器 + 1 個 __init__.py）
- `decision_module/__init__.py`（新建）
- `decision_module/strategy_configurator.py`（新建，適配器）
- `decision_module/reason_engine.py`（新建，適配器）
- `decision_module/industry_mapper.py`（新建，適配器）
- `decision_module/market_regime_detector.py`（新建，適配器）
- `decision_module/stock_screener.py`（新建，適配器）
- `decision_module/scoring_engine.py`（新建，適配器）

### 修改檔案（7 個 import 更新）
- `app_module/recommendation_service.py`（修改 import）
- `app_module/screening_service.py`（修改 import）
- `app_module/regime_service.py`（修改 import）
- `app_module/strategies/momentum_aggressive_executor.py`（修改 import）
- `app_module/strategies/stable_conservative_executor.py`（修改 import）
- `app_module/strategies/baseline_score_executor.py`（修改 import）
- `app_module/strategy_executor_adapter.py`（修改 import）

## 3) 明確禁止事項

1. **禁止修改任何業務邏輯**：所有適配器必須是純轉發（pass-through），不得改變任何類別的方法、屬性、行為
2. **禁止刪除任何檔案**：不得刪除 `ui_app/` 中的任何檔案，也不得刪除 `app_module/` 中的任何檔案
3. **禁止重構既有程式碼**：不得修改 `ui_app/` 中的原始檔案，不得修改 `app_module/` 中除了 import 語句以外的任何程式碼
4. **禁止改變對外 API**：`app_module` 的所有公開方法、參數、返回值必須與修改前完全相同
5. **禁止新增功能**：不得在適配器中新增任何方法、屬性或功能
6. **禁止修改測試檔案**：不得修改任何 `tests/` 目錄下的檔案
7. **禁止修改 UI 層**：不得修改 `ui_qt/` 或 `ui_app/main.py` 中的任何程式碼
8. **禁止使用簡體中文**：所有程式碼註解、文件字串（docstring）、變數名稱、註釋必須使用繁體中文，嚴禁使用簡體中文

## 4) 實作步驟

### Step 4.1: 建立 decision_module 目錄結構
```bash
# 在專案根目錄執行
mkdir decision_module
touch decision_module/__init__.py
```

### Step 4.2: 建立適配器模組（6 個檔案）

**重要**：所有程式碼註解、文件字串必須使用繁體中文，禁止使用簡體中文。

每個適配器檔案採用以下模式（以 `strategy_configurator.py` 為例）：

```python
"""
策略配置器適配器（遷移中：目前轉發到 ui_app）
此模組作為橋接層，未來將遷移實際邏輯到此處
"""

from ui_app.strategy_configurator import StrategyConfigurator as _StrategyConfigurator

class StrategyConfigurator(_StrategyConfigurator):
    """策略配置器（遷移中：目前轉發到 ui_app）"""
    pass

__all__ = ['StrategyConfigurator']
```

需要建立的 6 個適配器檔案：
1. `decision_module/strategy_configurator.py` → 轉發 `ui_app.strategy_configurator.StrategyConfigurator`
2. `decision_module/reason_engine.py` → 轉發 `ui_app.reason_engine.ReasonEngine`
3. `decision_module/industry_mapper.py` → 轉發 `ui_app.industry_mapper.IndustryMapper`
4. `decision_module/market_regime_detector.py` → 轉發 `ui_app.market_regime_detector.MarketRegimeDetector`
5. `decision_module/stock_screener.py` → 轉發 `ui_app.stock_screener.StockScreener`
6. `decision_module/scoring_engine.py` → 轉發 `ui_app.scoring_engine.ScoringEngine`

### Step 4.3: 建立 decision_module/__init__.py

```python
"""
決策邏輯模組（Decision Module）
核心決策邏輯模組，提供策略配置、推薦理由、打分、篩選、市場狀態檢測等功能
"""

from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.reason_engine import ReasonEngine
from decision_module.industry_mapper import IndustryMapper
from decision_module.market_regime_detector import MarketRegimeDetector
from decision_module.stock_screener import StockScreener
from decision_module.scoring_engine import ScoringEngine

__all__ = [
    'StrategyConfigurator',
    'ReasonEngine',
    'IndustryMapper',
    'MarketRegimeDetector',
    'StockScreener',
    'ScoringEngine',
]
```

### Step 4.4: 更新 app_module 的 import 語句

**檔案 1: `app_module/recommendation_service.py`**
```python
# 舊的 import（第 17-20 行）
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.reason_engine import ReasonEngine
# from ui_app.industry_mapper import IndustryMapper
# from ui_app.market_regime_detector import MarketRegimeDetector

# 新的 import（替換為）
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.reason_engine import ReasonEngine
from decision_module.industry_mapper import IndustryMapper
from decision_module.market_regime_detector import MarketRegimeDetector
```

**檔案 2: `app_module/screening_service.py`**
```python
# 舊的 import（第 10-11 行）
# from ui_app.stock_screener import StockScreener
# from ui_app.industry_mapper import IndustryMapper

# 新的 import（替換為）
from decision_module.stock_screener import StockScreener
from decision_module.industry_mapper import IndustryMapper
```

**檔案 3: `app_module/regime_service.py`**
```python
# 舊的 import（第 9 行）
# from ui_app.market_regime_detector import MarketRegimeDetector

# 新的 import（替換為）
from decision_module.market_regime_detector import MarketRegimeDetector
```

**檔案 4: `app_module/strategies/momentum_aggressive_executor.py`**
```python
# 舊的 import（第 10-12 行）
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.scoring_engine import ScoringEngine
# from ui_app.reason_engine import ReasonEngine

# 新的 import（替換為）
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.scoring_engine import ScoringEngine
from decision_module.reason_engine import ReasonEngine
```

**檔案 5: `app_module/strategies/stable_conservative_executor.py`**
```python
# 舊的 import（第 10-12 行）
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.scoring_engine import ScoringEngine
# from ui_app.reason_engine import ReasonEngine

# 新的 import（替換為）
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.scoring_engine import ScoringEngine
from decision_module.reason_engine import ReasonEngine
```

**檔案 6: `app_module/strategies/baseline_score_executor.py`**
```python
# 舊的 import（第 11-13 行）
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.scoring_engine import ScoringEngine
# from ui_app.reason_engine import ReasonEngine

# 新的 import（替換為）
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.scoring_engine import ScoringEngine
from decision_module.reason_engine import ReasonEngine
```

**檔案 7: `app_module/strategy_executor_adapter.py`**
```python
# 舊的 import（第 11-13 行）
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.scoring_engine import ScoringEngine
# from ui_app.reason_engine import ReasonEngine

# 新的 import（替換為）
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.scoring_engine import ScoringEngine
from decision_module.reason_engine import ReasonEngine
```

## 5) 完成條件

### 5.1 靜態檢查
- [ ] `decision_module/` 目錄存在，包含 7 個檔案（6 個適配器 + 1 個 __init__.py）
- [ ] 所有適配器檔案都使用 `pass` 繼承模式，無額外邏輯
- [ ] `app_module` 中所有檔案不再直接 import `ui_app.*`（除了註解中的舊 import）
- [ ] 所有 import 語句語法正確，無語法錯誤
- [ ] 所有程式碼註解、文件字串使用繁體中文，無簡體中文（檢查所有 `decision_module/` 中的檔案）

### 5.2 功能驗證
執行以下測試確保功能不變：

```bash
# 1. 執行現有測試套件
python -m pytest tests/ -v

# 2. 驗證 import 無錯誤
python -c "from app_module.recommendation_service import RecommendationService; print('✓ RecommendationService import OK')"
python -c "from app_module.screening_service import ScreeningService; print('✓ ScreeningService import OK')"
python -c "from app_module.regime_service import RegimeService; print('✓ RegimeService import OK')"

# 3. 驗證適配器可正常實例化
python -c "from decision_module.strategy_configurator import StrategyConfigurator; s = StrategyConfigurator(); print('✓ StrategyConfigurator instantiation OK')"
python -c "from decision_module.reason_engine import ReasonEngine; r = ReasonEngine(); print('✓ ReasonEngine instantiation OK')"
python -c "from decision_module.industry_mapper import IndustryMapper; from data_module.config import TWStockConfig; i = IndustryMapper(TWStockConfig()); print('✓ IndustryMapper instantiation OK')"
```

### 5.3 行為一致性驗證
- [ ] `RecommendationService.run_recommendation()` 返回結果與修改前相同（可執行簡單測試腳本比較）
- [ ] `ScreeningService` 的篩選結果與修改前相同
- [ ] `RegimeService` 的市場狀態檢測結果與修改前相同
- [ ] 所有策略執行器（strategies/*）的行為與修改前相同

### 5.4 依賴方向驗證
```bash
# 檢查 app_module 是否仍直接依賴 ui_app（應該為空）
grep -r "from ui_app\." app_module/ --exclude-dir=__pycache__ | grep -v "^#"
# 預期輸出：無結果（或只有註解中的舊 import）

# 檢查 decision_module 是否正確轉發到 ui_app
grep -r "from ui_app\." decision_module/ --exclude-dir=__pycache__
# 預期輸出：6 個適配器檔案都有 "from ui_app.xxx import"
```

## 6) 回退方式

### 6.1 Git 回退（推薦）
```bash
# 如果所有改動都在單一 commit
git log --oneline -1  # 查看最新 commit hash
git revert <commit_hash>

# 或直接重置到改動前
git reset --hard HEAD~1  # 如果只有一個 commit
git reset --hard <previous_commit_hash>  # 如果有多個 commit
```

### 6.2 手動回退步驟

**Step 1: 恢復 app_module 的 import**
將以下 7 個檔案中的 import 語句改回原樣：
- `app_module/recommendation_service.py`（第 17-20 行）
- `app_module/screening_service.py`（第 10-11 行）
- `app_module/regime_service.py`（第 9 行）
- `app_module/strategies/momentum_aggressive_executor.py`（第 10-12 行）
- `app_module/strategies/stable_conservative_executor.py`（第 10-12 行）
- `app_module/strategies/baseline_score_executor.py`（第 11-13 行）
- `app_module/strategy_executor_adapter.py`（第 11-13 行）

**Step 2: 刪除 decision_module 目錄**
```bash
rm -rf decision_module
# Windows: rmdir /s /q decision_module
```

### 6.3 回退驗證
```bash
# 確認 app_module 恢復直接依賴 ui_app
grep -r "from ui_app\." app_module/ --exclude-dir=__pycache__ | grep -v "^#"
# 預期輸出：7 個檔案都有 "from ui_app.xxx import"

# 確認 decision_module 不存在
ls decision_module 2>&1
# 預期輸出：No such file or directory

# 執行測試確認功能恢復
python -m pytest tests/ -v
```

---

## 檢查清單

- [ ] **目錄結構**：`decision_module/` 目錄已建立，包含 7 個檔案
- [ ] **適配器模式**：6 個適配器檔案都使用純繼承（pass-through）模式
- [ ] **Import 更新**：7 個 `app_module` 檔案的 import 已全部更新
- [ ] **語法檢查**：所有 Python 檔案無語法錯誤
- [ ] **繁體中文檢查**：所有程式碼註解、文件字串使用繁體中文，無簡體中文
- [ ] **功能測試**：所有現有測試通過，功能行為不變
- [ ] **依賴方向**：`app_module` 不再直接依賴 `ui_app`（僅通過 `decision_module` 間接依賴）
- [ ] **無破壞性變更**：未修改任何業務邏輯、未刪除任何檔案、未改變任何 API
- [ ] **回退準備**：所有改動已 commit，可隨時回退

---

## 版本/變更註記

### v1.0 (2025-01-XX)
- 初始版本：建立 `decision_module/` 骨架與適配器層
- 完成 `app_module` 的 import 遷移，從依賴 `ui_app` 改為依賴 `decision_module`
- 所有適配器採用純轉發模式，保持 100% 向後兼容

