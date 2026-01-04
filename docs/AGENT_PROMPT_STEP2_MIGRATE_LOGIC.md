# Agent Prompt: 遷移業務邏輯到 decision_module

## 1) 任務目標

將 `ui_app/` 中的 6 個業務邏輯模組實際遷移到 `decision_module/`，替換現有的適配器層，並在 `ui_app/` 中保留轉發以維持向後兼容，確保所有現有功能與測試完全正常運作。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

## 2) 影響範圍

### 需要遷移的檔案（6 個，按依賴順序）
1. `ui_app/industry_mapper.py` → `decision_module/industry_mapper.py`（無依賴，優先遷移）
2. `ui_app/market_regime_detector.py` → `decision_module/market_regime_detector.py`（依賴 `industry_mapper`）
3. `ui_app/stock_screener.py` → `decision_module/stock_screener.py`（依賴 `industry_mapper`）
4. `ui_app/scoring_engine.py` → `decision_module/scoring_engine.py`（無依賴）
5. `ui_app/strategy_configurator.py` → `decision_module/strategy_configurator.py`（依賴 `scoring_engine`）
6. `ui_app/reason_engine.py` → `decision_module/reason_engine.py`（依賴 `strategy_configurator`）

### 需要修改的檔案（6 個 ui_app 轉發 + 1 個 __init__.py）
- `ui_app/industry_mapper.py`（改為轉發）
- `ui_app/market_regime_detector.py`（改為轉發）
- `ui_app/stock_screener.py`（改為轉發）
- `ui_app/scoring_engine.py`（改為轉發）
- `ui_app/strategy_configurator.py`（改為轉發）
- `ui_app/reason_engine.py`（改為轉發）
- `decision_module/__init__.py`（更新導出，確保所有類別正確導出）

## 3) 明確禁止事項

1. **禁止修改業務邏輯**：遷移時必須完整複製原始程式碼，不得修改任何方法實作、演算法、計算邏輯
2. **禁止刪除原始檔案**：不得刪除 `ui_app/` 中的任何檔案，必須改為轉發以保持向後兼容
3. **禁止改變類別介面**：所有類別的方法簽名、參數、返回值必須與原始版本完全相同
4. **禁止修改測試檔案**：不得修改任何 `tests/` 目錄下的檔案
5. **禁止修改 UI 層**：不得修改 `ui_qt/` 或 `ui_app/main.py` 中的任何程式碼
6. **禁止修改 app_module**：不得修改 `app_module/` 中的任何檔案（已在步驟 1 完成）
7. **禁止使用簡體中文**：所有程式碼註解、文件字串（docstring）、變數名稱、註釋必須使用繁體中文，嚴禁使用簡體中文
8. **禁止改變檔案結構**：不得新增或刪除任何方法、類別、函數，必須保持與原始檔案完全一致

## 4) 實作步驟

### Step 4.1: 遷移 industry_mapper.py（無依賴，優先處理）

**操作**：
1. 讀取 `ui_app/industry_mapper.py` 的完整內容
2. 複製到 `decision_module/industry_mapper.py`，覆蓋現有的適配器檔案
3. 檢查檔案內是否有 `from ui_app.xxx import` 或 `import ui_app.xxx`，如果有則改為 `from decision_module.xxx import` 或 `import decision_module.xxx`
4. 檢查檔案內是否有其他 `ui_app` 的引用，全部改為 `decision_module`
5. 保持所有其他程式碼完全不變（包括註解、文件字串、邏輯）

**修改 ui_app/industry_mapper.py 為轉發**：
```python
"""
產業映射模組（向後兼容：轉發到 decision_module）
此檔案保留以維持向後兼容，實際邏輯已遷移至 decision_module
"""

from decision_module.industry_mapper import IndustryMapper

__all__ = ['IndustryMapper']
```

### Step 4.2: 遷移 market_regime_detector.py（依賴 industry_mapper）

**操作**：
1. 讀取 `ui_app/market_regime_detector.py` 的完整內容
2. 複製到 `decision_module/market_regime_detector.py`，覆蓋現有的適配器檔案
3. 修改所有 `from ui_app.industry_mapper import` 為 `from decision_module.industry_mapper import`
4. 檢查檔案內是否有其他 `ui_app` 的引用，全部改為 `decision_module`
5. 保持所有其他程式碼完全不變

**修改 ui_app/market_regime_detector.py 為轉發**：
```python
"""
市場狀態檢測模組（向後兼容：轉發到 decision_module）
此檔案保留以維持向後兼容，實際邏輯已遷移至 decision_module
"""

from decision_module.market_regime_detector import MarketRegimeDetector

__all__ = ['MarketRegimeDetector']
```

### Step 4.3: 遷移 stock_screener.py（依賴 industry_mapper）

**操作**：
1. 讀取 `ui_app/stock_screener.py` 的完整內容
2. 複製到 `decision_module/stock_screener.py`，覆蓋現有的適配器檔案
3. 修改所有 `from ui_app.industry_mapper import` 為 `from decision_module.industry_mapper import`
4. 檢查檔案內是否有其他 `ui_app` 的引用，全部改為 `decision_module`
5. 保持所有其他程式碼完全不變

**修改 ui_app/stock_screener.py 為轉發**：
```python
"""
股票篩選模組（向後兼容：轉發到 decision_module）
此檔案保留以維持向後兼容，實際邏輯已遷移至 decision_module
"""

from decision_module.stock_screener import StockScreener

__all__ = ['StockScreener']
```

### Step 4.4: 遷移 scoring_engine.py（無依賴）

**操作**：
1. 讀取 `ui_app/scoring_engine.py` 的完整內容
2. 複製到 `decision_module/scoring_engine.py`，覆蓋現有的適配器檔案
3. 檢查檔案內是否有 `from ui_app.xxx import` 或 `import ui_app.xxx`，如果有則改為 `from decision_module.xxx import` 或 `import decision_module.xxx`
4. 檢查檔案內是否有其他 `ui_app` 的引用，全部改為 `decision_module`
5. 保持所有其他程式碼完全不變

**修改 ui_app/scoring_engine.py 為轉發**：
```python
"""
打分引擎模組（向後兼容：轉發到 decision_module）
此檔案保留以維持向後兼容，實際邏輯已遷移至 decision_module
"""

from decision_module.scoring_engine import ScoringEngine

__all__ = ['ScoringEngine']
```

### Step 4.5: 遷移 strategy_configurator.py（依賴 scoring_engine）

**操作**：
1. 讀取 `ui_app/strategy_configurator.py` 的完整內容
2. 複製到 `decision_module/strategy_configurator.py`，覆蓋現有的適配器檔案
3. 修改所有 `from ui_app.scoring_engine import` 為 `from decision_module.scoring_engine import`
4. 檢查檔案內是否有其他 `ui_app` 的引用，全部改為 `decision_module`
5. 保持所有其他程式碼完全不變

**修改 ui_app/strategy_configurator.py 為轉發**：
```python
"""
策略配置器模組（向後兼容：轉發到 decision_module）
此檔案保留以維持向後兼容，實際邏輯已遷移至 decision_module
"""

from decision_module.strategy_configurator import StrategyConfigurator

__all__ = ['StrategyConfigurator']
```

### Step 4.6: 遷移 reason_engine.py（依賴 strategy_configurator）

**操作**：
1. 讀取 `ui_app/reason_engine.py` 的完整內容
2. 複製到 `decision_module/reason_engine.py`，覆蓋現有的適配器檔案
3. 修改所有 `from ui_app.strategy_configurator import` 為 `from decision_module.strategy_configurator import`
4. 檢查檔案內是否有其他 `ui_app` 的引用，全部改為 `decision_module`
5. 保持所有其他程式碼完全不變

**修改 ui_app/reason_engine.py 為轉發**：
```python
"""
推薦理由引擎模組（向後兼容：轉發到 decision_module）
此檔案保留以維持向後兼容，實際邏輯已遷移至 decision_module
"""

from decision_module.reason_engine import ReasonEngine

__all__ = ['ReasonEngine']
```

### Step 4.7: 更新 decision_module/__init__.py

確保 `decision_module/__init__.py` 正確導出所有類別：

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

## 5) 完成條件

### 5.1 靜態檢查
- [ ] 所有 6 個檔案已從 `ui_app/` 完整複製到 `decision_module/`（覆蓋適配器）
- [ ] `decision_module/` 中所有檔案不再有 `from ui_app.xxx import`（除了註解中的舊引用）
- [ ] `ui_app/` 中所有 6 個檔案已改為轉發模式（僅包含 import 和 __all__）
- [ ] `decision_module/__init__.py` 正確導出所有 6 個類別
- [ ] 所有 Python 檔案無語法錯誤
- [ ] 所有程式碼註解、文件字串使用繁體中文，無簡體中文

### 5.2 依賴關係驗證
```bash
# 檢查 decision_module 內部依賴是否正確
grep -r "from ui_app\." decision_module/ --exclude-dir=__pycache__ | grep -v "^#"
# 預期輸出：無結果（或只有註解中的舊引用）

# 檢查 ui_app 轉發是否正確
grep -r "from decision_module\." ui_app/*.py | grep -v "^#"
# 預期輸出：6 個檔案都有 "from decision_module.xxx import"

# 檢查 ui_app 是否仍有業務邏輯（應該只有轉發）
wc -l ui_app/industry_mapper.py ui_app/market_regime_detector.py ui_app/stock_screener.py ui_app/scoring_engine.py ui_app/strategy_configurator.py ui_app/reason_engine.py
# 預期輸出：每個檔案應該只有 5-10 行（僅轉發程式碼）
```

### 5.3 功能驗證
執行以下測試確保功能不變：

```bash
# 1. 執行現有測試套件
python -m pytest tests/ -v

# 2. 驗證所有類別可正常實例化
python -c "
from decision_module.industry_mapper import IndustryMapper
from decision_module.market_regime_detector import MarketRegimeDetector
from decision_module.stock_screener import StockScreener
from decision_module.scoring_engine import ScoringEngine
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.reason_engine import ReasonEngine
from data_module.config import TWStockConfig
config = TWStockConfig()
print('✓ 所有類別 import 成功')
im = IndustryMapper(config)
print('✓ IndustryMapper 實例化成功')
mrd = MarketRegimeDetector(config)
print('✓ MarketRegimeDetector 實例化成功')
ss = StockScreener(config)
print('✓ StockScreener 實例化成功')
se = ScoringEngine()
print('✓ ScoringEngine 實例化成功')
sc = StrategyConfigurator()
print('✓ StrategyConfigurator 實例化成功')
re = ReasonEngine()
print('✓ ReasonEngine 實例化成功')
"

# 3. 驗證 ui_app 轉發仍可正常運作
python -c "
from ui_app.industry_mapper import IndustryMapper
from ui_app.market_regime_detector import MarketRegimeDetector
from ui_app.stock_screener import StockScreener
from ui_app.scoring_engine import ScoringEngine
from ui_app.strategy_configurator import StrategyConfigurator
from ui_app.reason_engine import ReasonEngine
from data_module.config import TWStockConfig
config = TWStockConfig()
print('✓ ui_app 轉發 import 成功')
im = IndustryMapper(config)
print('✓ ui_app IndustryMapper 轉發成功')
"

# 4. 驗證 app_module 仍可正常運作
python -c "
from app_module.recommendation_service import RecommendationService
from app_module.screening_service import ScreeningService
from app_module.regime_service import RegimeService
from data_module.config import TWStockConfig
config = TWStockConfig()
rs = RecommendationService(config)
print('✓ RecommendationService 正常')
ss = ScreeningService(config)
print('✓ ScreeningService 正常')
rgs = RegimeService(config)
print('✓ RegimeService 正常')
"
```

### 5.4 UI 驗證（可選，但強烈建議）
```bash
# 驗證 Tkinter UI 仍可正常啟動（不執行完整流程，僅檢查 import）
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from ui_app.main import TradingAnalysisApp
print('✓ ui_app/main.py import 成功')
"

# 驗證 Qt UI 仍可正常啟動（不執行完整流程，僅檢查 import）
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from ui_qt.main import MainWindow
print('✓ ui_qt/main.py import 成功')
"
```

### 5.5 行為一致性驗證
- [ ] `RecommendationService.run_recommendation()` 返回結果與遷移前相同
- [ ] `ScreeningService` 的篩選結果與遷移前相同
- [ ] `RegimeService` 的市場狀態檢測結果與遷移前相同
- [ ] 所有策略執行器（strategies/*）的行為與遷移前相同
- [ ] `ui_app/main.py`（Tkinter UI）可正常運行（如果有的話）
- [ ] `ui_qt/main.py`（Qt UI）可正常運行

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

**Step 1: 恢復 ui_app/ 中的原始檔案**

需要恢復的 6 個檔案（從 Git 歷史或備份恢復）：
- `ui_app/industry_mapper.py`
- `ui_app/market_regime_detector.py`
- `ui_app/stock_screener.py`
- `ui_app/scoring_engine.py`
- `ui_app/strategy_configurator.py`
- `ui_app/reason_engine.py`

**Step 2: 恢復 decision_module/ 為適配器模式**

將 `decision_module/` 中的 6 個檔案改回適配器模式（如步驟 1 的狀態）：

```python
# decision_module/industry_mapper.py
from ui_app.industry_mapper import IndustryMapper as _IndustryMapper

class IndustryMapper(_IndustryMapper):
    """產業映射器（遷移中：目前轉發到 ui_app）"""
    pass

__all__ = ['IndustryMapper']
```

對其他 5 個檔案執行相同操作。

### 6.3 回退驗證
```bash
# 確認 ui_app 恢復原始業務邏輯
grep -r "from decision_module\." ui_app/*.py 2>&1 | grep -v "^#"
# 預期輸出：無結果

# 確認 decision_module 恢復適配器模式
grep -r "from ui_app\." decision_module/*.py --exclude-dir=__pycache__ | grep -v "^#"
# 預期輸出：6 個檔案都有 "from ui_app.xxx import"

# 執行測試確認功能恢復
python -m pytest tests/ -v
```

---

## 檢查清單

- [ ] **遷移完成**：6 個檔案已從 `ui_app/` 完整複製到 `decision_module/`（覆蓋適配器）
- [ ] **Import 修正**：`decision_module/` 中所有內部 import 已從 `ui_app` 改為 `decision_module`
- [ ] **轉發建立**：`ui_app/` 中 6 個檔案已改為轉發模式（僅 5-10 行）
- [ ] **__init__.py 更新**：`decision_module/__init__.py` 正確導出所有類別
- [ ] **繁體中文檢查**：所有程式碼註解、文件字串使用繁體中文，無簡體中文
- [ ] **功能測試**：所有現有測試通過，功能行為不變
- [ ] **UI 驗證**：`ui_app/main.py` 和 `ui_qt/main.py` 仍可正常運行
- [ ] **依賴方向**：`decision_module` 不再依賴 `ui_app`，`ui_app` 轉發到 `decision_module`
- [ ] **無破壞性變更**：未修改任何業務邏輯、未刪除任何檔案、未改變任何 API
- [ ] **回退準備**：所有改動已 commit，可隨時回退

---

## 版本/變更註記

### v1.0 (2025-01-XX)
- 初始版本：將 `ui_app/` 中的業務邏輯實際遷移到 `decision_module/`
- 完成 6 個模組的遷移（按依賴順序）
- 在 `ui_app/` 中保留轉發以維持向後兼容
- 所有功能與測試保持 100% 兼容

