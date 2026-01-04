# Agent Prompt: 移除 ui_app 中的業務邏輯轉發

## 1) 任務目標

完全移除 `ui_app/` 中的業務邏輯轉發檔案，僅保留 Tkinter UI 相關代碼，完成架構清理的最後一步。執行前需先確認所有依賴已遷移，並更新仍在使用 `ui_app` 業務邏輯的檔案。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

## 2) 影響範圍

### 需要檢查的檔案（確認依賴情況）

**UI 層**：
- `ui_qt/main.py`（檢查是否仍使用 `ui_app` 的業務邏輯）
- `ui_app/main.py`（Tkinter UI，應保留但需確認依賴）

**腳本檔案**：
- `scripts/qa_validate_recommendation_tab.py`（檢查是否仍使用 `ui_app` 的業務邏輯）
- `scripts/qa_validate_phase2_5.py`（檢查是否仍使用 `ui_app` 的業務邏輯）
- 其他可能引用 `ui_app` 業務邏輯的腳本

### 需要更新的檔案（更新 import 路徑）

根據檢查結果，可能需要更新：
- `ui_qt/main.py`（將 `from ui_app.industry_mapper` 改為 `from decision_module.industry_mapper`）
- `scripts/qa_validate_recommendation_tab.py`（更新所有 `ui_app` 引用為 `decision_module`）
- `scripts/qa_validate_phase2_5.py`（更新所有 `ui_app` 引用為 `decision_module`）

### 需要刪除的檔案（業務邏輯轉發）

**業務邏輯轉發檔案（6 個）**：
- `ui_app/strategy_configurator.py`（轉發檔案，可刪除）
- `ui_app/reason_engine.py`（轉發檔案，可刪除）
- `ui_app/industry_mapper.py`（轉發檔案，可刪除）
- `ui_app/market_regime_detector.py`（轉發檔案，可刪除）
- `ui_app/stock_screener.py`（轉發檔案，可刪除）
- `ui_app/scoring_engine.py`（轉發檔案，可刪除）

### 需要保留的檔案（Tkinter UI）

**Tkinter UI 相關檔案**：
- `ui_app/main.py`（Tkinter UI 主程式，需保留但需更新 import）
- `ui_app/strategies.py`（如果存在且為 UI 相關，需保留）
- `ui_app/__init__.py`（需保留）
- `ui_app/README.md`（需更新標註）

## 3) 明確禁止事項

1. **禁止刪除 ui_app/main.py**：Tkinter UI 主程式必須保留，僅更新其 import 路徑
2. **禁止修改業務邏輯**：不得修改 `decision_module/` 中的任何業務邏輯
3. **禁止修改 app_module**：不得修改 `app_module/` 中的任何檔案
4. **禁止修改 ui_qt**：除了更新 import 路徑外，不得修改 `ui_qt/` 中的其他程式碼
5. **禁止修改測試檔案**：不得修改任何 `tests/` 目錄下的檔案
6. **禁止使用簡體中文**：所有程式碼註解、文件字串（docstring）、變數名稱、註釋必須使用繁體中文，嚴禁使用簡體中文
7. **禁止跳過檢查步驟**：必須完整執行所有依賴檢查，確認無遺漏後才能刪除檔案
8. **禁止直接刪除未確認的檔案**：必須先確認所有引用已更新，才能刪除業務邏輯轉發檔案

## 4) 實作步驟

### Step 4.1: 檢查所有 ui_app 業務邏輯的使用情況

**操作**：
1. 搜尋整個專案中所有引用 `ui_app` 業務邏輯模組的檔案：
   ```bash
   grep -r "from ui_app\.strategy_configurator" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs
   grep -r "from ui_app\.reason_engine" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs
   grep -r "from ui_app\.industry_mapper" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs
   grep -r "from ui_app\.market_regime_detector" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs
   grep -r "from ui_app\.stock_screener" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs
   grep -r "from ui_app\.scoring_engine" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs
   ```

2. 記錄所有仍在使用 `ui_app` 業務邏輯的檔案清單

3. 確認 `app_module` 不再依賴 `ui_app`（應該已在步驟 1 完成）

### Step 4.2: 更新仍在使用 ui_app 業務邏輯的檔案

**檔案 1: `ui_qt/main.py`**

檢查並更新第 60 行附近的 import：
```python
# 舊的 import（約第 60 行）
# from ui_app.industry_mapper import IndustryMapper

# 新的 import（替換為）
from decision_module.industry_mapper import IndustryMapper
```

**檔案 2: `scripts/qa_validate_recommendation_tab.py`**

檢查並更新所有 `ui_app` 業務邏輯的 import：
```python
# 舊的 import（約第 25-26 行）
# from ui_app.industry_mapper import IndustryMapper
# from ui_app.strategy_configurator import StrategyConfigurator

# 新的 import（替換為）
from decision_module.industry_mapper import IndustryMapper
from decision_module.strategy_configurator import StrategyConfigurator
```

**檔案 3: `scripts/qa_validate_phase2_5.py`**

檢查並更新所有 `ui_app` 業務邏輯的 import：
```python
# 舊的 import（約第 29 行）
# from ui_app.industry_mapper import IndustryMapper

# 新的 import（替換為）
from decision_module.industry_mapper import IndustryMapper
```

**檔案 4: `ui_app/main.py`（Tkinter UI）**

更新所有業務邏輯的 import，改為使用 `decision_module`：
```python
# 舊的 import（約第 41-45 行）
# from ui_app.strategy_configurator import StrategyConfigurator
# from ui_app.stock_screener import StockScreener
# from ui_app.reason_engine import ReasonEngine
# from ui_app.market_regime_detector import MarketRegimeDetector
# from ui_app.industry_mapper import IndustryMapper

# 新的 import（替換為）
from decision_module.strategy_configurator import StrategyConfigurator
from decision_module.stock_screener import StockScreener
from decision_module.reason_engine import ReasonEngine
from decision_module.market_regime_detector import MarketRegimeDetector
from decision_module.industry_mapper import IndustryMapper
```

**其他檔案**：根據 Step 4.1 的檢查結果，更新所有其他引用檔案

### Step 4.3: 驗證所有引用已更新

**操作**：
1. 再次搜尋整個專案，確認沒有遺漏的 `from ui_app.xxx` 引用（除了 `ui_app/main.py` 本身和文檔中的說明）
2. 確認所有引用已更新為 `decision_module` 或已移除

### Step 4.4: 刪除業務邏輯轉發檔案

**操作**：
確認所有引用已更新後，刪除以下 6 個轉發檔案：

```bash
# 刪除業務邏輯轉發檔案
rm ui_app/strategy_configurator.py
rm ui_app/reason_engine.py
rm ui_app/industry_mapper.py
rm ui_app/market_regime_detector.py
rm ui_app/stock_screener.py
rm ui_app/scoring_engine.py

# Windows 使用：
# del ui_app\strategy_configurator.py
# del ui_app\reason_engine.py
# del ui_app\industry_mapper.py
# del ui_app\market_regime_detector.py
# del ui_app\stock_screener.py
# del ui_app\scoring_engine.py
```

### Step 4.5: 更新 ui_app/README.md

**操作**：
更新 `ui_app/README.md`，標註為舊版 Tkinter UI：

```markdown
# Tkinter UI 模組（舊版，僅供參考）

⚠️ **注意**：此模組為舊版 Tkinter UI 實作，僅供參考使用。

**當前推薦**：
- 新專案請使用 `ui_qt/`（PySide6/Qt UI）
- 業務邏輯請使用 `app_module/` 中的服務層
- 決策邏輯請使用 `decision_module/` 中的模組

**模組狀態**：
- `main.py`：Tkinter UI 主程式（已更新為使用 `decision_module`）
- 業務邏輯已遷移至 `decision_module/`
- 此模組保留僅為向後兼容與參考用途
```

### Step 4.6: 最終驗證

**操作**：
1. 確認 `ui_app/` 目錄中僅保留 Tkinter UI 相關檔案
2. 確認所有業務邏輯轉發檔案已刪除
3. 執行所有測試與驗證

## 5) 完成條件

### 5.1 靜態檢查
- [ ] 已完整檢查所有 `ui_app` 業務邏輯模組的使用情況
- [ ] 所有仍在使用 `ui_app` 業務邏輯的檔案已更新為使用 `decision_module`
- [ ] 專案中不再有 `from ui_app.strategy_configurator` 等業務邏輯引用（除了文檔中的說明）
- [ ] 6 個業務邏輯轉發檔案已刪除
- [ ] `ui_app/main.py` 已更新為使用 `decision_module`
- [ ] `ui_app/README.md` 已更新標註
- [ ] `ui_app/` 目錄中僅保留 Tkinter UI 相關檔案
- [ ] 所有程式碼註解、文件字串使用繁體中文，無簡體中文

### 5.2 功能驗證

**驗證 import 無錯誤**：
```bash
# 1. 驗證 ui_qt 可正常 import
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from ui_qt.main import MainWindow
print('✓ ui_qt/main.py import 成功')
"

# 2. 驗證 ui_app 可正常 import（Tkinter UI）
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from ui_app.main import TradingAnalysisApp
print('✓ ui_app/main.py import 成功')
"

# 3. 驗證 scripts 可正常 import
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from scripts.qa_validate_recommendation_tab import *
print('✓ scripts/qa_validate_recommendation_tab.py import 成功')
"

python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from scripts.qa_validate_phase2_5 import *
print('✓ scripts/qa_validate_phase2_5.py import 成功')
"
```

**驗證業務邏輯轉發檔案已刪除**：
```bash
# 確認轉發檔案不存在
ls ui_app/strategy_configurator.py 2>&1
# 預期輸出：No such file or directory

ls ui_app/reason_engine.py 2>&1
# 預期輸出：No such file or directory

ls ui_app/industry_mapper.py 2>&1
# 預期輸出：No such file or directory

ls ui_app/market_regime_detector.py 2>&1
# 預期輸出：No such file or directory

ls ui_app/stock_screener.py 2>&1
# 預期輸出：No such file or directory

ls ui_app/scoring_engine.py 2>&1
# 預期輸出：No such file or directory
```

**驗證無遺漏引用**：
```bash
# 確認專案中不再有 ui_app 業務邏輯引用（排除文檔和 ui_app/main.py 本身）
grep -r "from ui_app\.strategy_configurator" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs --exclude="ui_app/main.py" | grep -v "^#"
# 預期輸出：無結果

grep -r "from ui_app\.reason_engine" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs --exclude="ui_app/main.py" | grep -v "^#"
# 預期輸出：無結果

grep -r "from ui_app\.industry_mapper" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs --exclude="ui_app/main.py" | grep -v "^#"
# 預期輸出：無結果（或只有已更新的引用）
```

### 5.3 UI 驗證（可選，但強烈建議）
```bash
# 驗證 Qt UI 仍可正常啟動（不執行完整流程，僅檢查 import）
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from ui_qt.main import MainWindow
print('✓ ui_qt/main.py import 成功，UI 可正常啟動')
"
```

### 5.4 完整性驗證
- [ ] 所有測試通過（執行 `python -m pytest tests/ -v`）
- [ ] `ui_qt/main.py` 可正常運行（如果可能，啟動 UI 驗證）
- [ ] `ui_app/main.py` 可正常運行（如果可能，啟動 Tkinter UI 驗證）
- [ ] 專案結構清晰，`ui_app/` 僅包含 Tkinter UI 代碼

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

**Step 1: 恢復業務邏輯轉發檔案**

從 Git 歷史恢復 6 個轉發檔案：
```bash
# 從 Git 恢復轉發檔案
git checkout HEAD~1 -- ui_app/strategy_configurator.py
git checkout HEAD~1 -- ui_app/reason_engine.py
git checkout HEAD~1 -- ui_app/industry_mapper.py
git checkout HEAD~1 -- ui_app/market_regime_detector.py
git checkout HEAD~1 -- ui_app/stock_screener.py
git checkout HEAD~1 -- ui_app/scoring_engine.py
```

**Step 2: 恢復所有引用檔案的 import**

將以下檔案的 import 改回原樣：
- `ui_qt/main.py`（約第 60 行）
- `scripts/qa_validate_recommendation_tab.py`（約第 25-26 行）
- `scripts/qa_validate_phase2_5.py`（約第 29 行）
- `ui_app/main.py`（約第 41-45 行）

**Step 3: 恢復 ui_app/README.md**

從 Git 歷史恢復原始 README：
```bash
git checkout HEAD~1 -- ui_app/README.md
```

### 6.3 回退驗證
```bash
# 確認轉發檔案已恢復
ls ui_app/strategy_configurator.py
# 預期輸出：檔案存在

ls ui_app/reason_engine.py
# 預期輸出：檔案存在

# 確認所有 import 已恢復
grep -r "from ui_app\.industry_mapper" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=docs
# 預期輸出：顯示所有引用檔案都有 "from ui_app.industry_mapper import"

# 執行測試確認功能恢復
python -m pytest tests/ -v
```

---

## 檢查清單

- [ ] **依賴檢查**：已完整檢查所有 `ui_app` 業務邏輯模組的使用情況
- [ ] **Import 更新**：所有仍在使用 `ui_app` 業務邏輯的檔案已更新為 `decision_module`
- [ ] **轉發檔案刪除**：6 個業務邏輯轉發檔案已刪除
- [ ] **ui_app/main.py 更新**：Tkinter UI 主程式已更新為使用 `decision_module`
- [ ] **README 更新**：`ui_app/README.md` 已更新標註為舊版
- [ ] **繁體中文檢查**：所有程式碼註解、文件字串使用繁體中文，無簡體中文
- [ ] **無遺漏引用**：專案中不再有未更新的 `ui_app` 業務邏輯引用
- [ ] **功能測試**：所有相關測試通過，UI 可正常運行
- [ ] **結構清晰**：`ui_app/` 僅包含 Tkinter UI 代碼，業務邏輯已完全分離
- [ ] **回退準備**：所有改動已 commit，可隨時回退

---

## 版本/變更註記

### v1.0 (2025-01-XX)
- 初始版本：移除 `ui_app/` 中的業務邏輯轉發，完成架構清理
- 完成所有依賴檢查與 import 更新
- 刪除 6 個業務邏輯轉發檔案
- 更新 `ui_app/README.md` 標註為舊版
- 保持 Tkinter UI 功能正常運作

