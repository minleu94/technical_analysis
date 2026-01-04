# Agent Prompt: 清理 recommendation_module 重複

## 1) 任務目標

確認 `recommendation_module/` 的使用情況，根據實際使用狀態決定保留（重命名為 legacy 並添加棄用警告）或移除（移動到 archive），避免與 `app_module/recommendation_service.py` 的功能重複造成混淆。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

## 2) 影響範圍

### 需要檢查的檔案（確認使用情況）
- `examples/main_example.py`（檢查是否使用 `recommendation_module`）
- `tests/test_recommendation/test_recommendation_report.py`（檢查是否使用）
- `tests/test_backtest/test_backtest_recommendation.py`（檢查是否使用）
- 所有其他可能引用 `recommendation_module` 的檔案

### 可能修改的檔案（根據檢查結果）

**方案 A（仍在使用）：**
- `recommendation_module/` → 重命名為 `recommendation_module_legacy/`
- `recommendation_module_legacy/__init__.py`（添加棄用警告）
- `examples/main_example.py`（更新 import 路徑）
- `tests/test_recommendation/test_recommendation_report.py`（更新 import 路徑）
- `tests/test_backtest/test_backtest_recommendation.py`（更新 import 路徑）

**方案 B（不再使用）：**
- `recommendation_module/` → 移動到 `archive/recommendation_module_legacy/`
- 所有引用檔案（更新 import 路徑或移除引用）

## 3) 明確禁止事項

1. **禁止刪除 recommendation_module**：即使不再使用，也必須移動到 `archive/` 而非直接刪除，保留歷史記錄
2. **禁止修改業務邏輯**：不得修改 `recommendation_module` 中的任何業務邏輯或功能
3. **禁止破壞現有功能**：如果仍有檔案在使用，必須保持功能完全正常，僅添加棄用警告
4. **禁止修改 app_module**：不得修改 `app_module/recommendation_service.py` 或相關檔案
5. **禁止修改 decision_module**：不得修改 `decision_module/` 中的任何檔案
6. **禁止修改測試邏輯**：如果更新測試檔案的 import，不得修改測試邏輯或斷言
7. **禁止使用簡體中文**：所有程式碼註解、文件字串（docstring）、變數名稱、註釋必須使用繁體中文，嚴禁使用簡體中文
8. **禁止跳過驗證步驟**：必須完整執行所有檢查與驗證步驟，不得假設使用情況

## 4) 實作步驟

### Step 4.1: 檢查 recommendation_module 的使用情況

**操作**：
1. 搜尋整個專案中所有引用 `recommendation_module` 的檔案：
   ```bash
   grep -r "from recommendation_module" . --exclude-dir=__pycache__ --exclude-dir=.git
   grep -r "import recommendation_module" . --exclude-dir=__pycache__ --exclude-dir=.git
   grep -r "RecommendationEngine" . --exclude-dir=__pycache__ --exclude-dir=.git | grep -v "RecommendationService"
   ```

2. 記錄所有使用 `recommendation_module` 的檔案清單

3. 確認 `app_module/recommendation_service.py` 是否完全取代舊版功能（檢查功能重疊情況）

### Step 4.2: 根據檢查結果選擇處理方案

#### 方案 A：如果仍有檔案在使用（重命名為 legacy 並添加棄用警告）

**Step 4.2.1: 重命名目錄**
```bash
# 在專案根目錄執行
mv recommendation_module recommendation_module_legacy
```

**Step 4.2.2: 更新 recommendation_module_legacy/__init__.py**

在檔案開頭添加棄用警告：

```python
"""
推薦引擎模組（舊版，已棄用）

⚠️ 警告：此模組已棄用，請使用 app_module.recommendation_service.RecommendationService 替代。

此模組保留僅為向後兼容，新專案請勿使用。
"""

import warnings

# 發出棄用警告
warnings.warn(
    "recommendation_module 已棄用，請使用 app_module.recommendation_service.RecommendationService 替代。"
    "此模組將在未來版本中移除。",
    DeprecationWarning,
    stacklevel=2
)

from .recommendation_engine import RecommendationEngine

__all__ = ['RecommendationEngine']
```

**Step 4.2.3: 更新所有引用檔案的 import**

對於每個使用 `recommendation_module` 的檔案，更新 import 語句：

**檔案 1: `examples/main_example.py`**
```python
# 舊的 import
# from recommendation_module import RecommendationEngine

# 新的 import（替換為）
from recommendation_module_legacy import RecommendationEngine
```

**檔案 2: `tests/test_recommendation/test_recommendation_report.py`**
```python
# 舊的 import
# from recommendation_module import RecommendationEngine

# 新的 import（替換為）
from recommendation_module_legacy import RecommendationEngine
```

**檔案 3: `tests/test_backtest/test_backtest_recommendation.py`**
```python
# 舊的 import
# from recommendation_module import RecommendationEngine

# 新的 import（替換為）
from recommendation_module_legacy import RecommendationEngine
```

**其他檔案**：根據 Step 4.1 的檢查結果，更新所有其他引用檔案

#### 方案 B：如果不再使用（移動到 archive）

**Step 4.2.1: 創建 archive 目錄（如果不存在）**
```bash
mkdir -p archive
```

**Step 4.2.2: 移動目錄**
```bash
mv recommendation_module archive/recommendation_module_legacy
```

**Step 4.2.3: 更新或移除引用**

如果發現任何引用（雖然理論上不應該有），更新 import 路徑：
```python
# 舊的 import
# from recommendation_module import RecommendationEngine

# 新的 import（替換為）
from archive.recommendation_module_legacy import RecommendationEngine
```

或者，如果確定不再需要，移除相關引用。

### Step 4.3: 驗證所有引用已更新

**操作**：
1. 再次搜尋整個專案，確認沒有遺漏的 `from recommendation_module` 或 `import recommendation_module`
2. 確認所有引用已更新為 `recommendation_module_legacy` 或已移除

## 5) 完成條件

### 5.1 靜態檢查
- [ ] 已完整檢查所有 `recommendation_module` 的使用情況
- [ ] 已根據使用情況選擇並執行對應方案（A 或 B）
- [ ] 目錄已重命名為 `recommendation_module_legacy` 或移動到 `archive/recommendation_module_legacy/`
- [ ] 所有引用檔案的 import 已更新（如果採用方案 A）
- [ ] `recommendation_module_legacy/__init__.py` 已添加棄用警告（如果採用方案 A）
- [ ] 專案中不再有 `from recommendation_module` 或 `import recommendation_module`（除了棄用警告中的說明）
- [ ] 所有程式碼註解、文件字串使用繁體中文，無簡體中文

### 5.2 功能驗證

**如果採用方案 A（仍在使用）：**
```bash
# 1. 驗證 legacy 模組仍可正常 import（會顯示棄用警告）
python -c "
import warnings
warnings.simplefilter('always')
from recommendation_module_legacy import RecommendationEngine
print('✓ RecommendationEngine import 成功（已顯示棄用警告）')
"

# 2. 驗證所有更新後的檔案仍可正常 import
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from examples.main_example import *
print('✓ examples/main_example.py import 成功')
"

# 3. 執行相關測試
python -m pytest tests/test_recommendation/ -v
python -m pytest tests/test_backtest/test_backtest_recommendation.py -v
```

**如果採用方案 B（不再使用）：**
```bash
# 1. 確認 archive 目錄存在
ls archive/recommendation_module_legacy/ 2>&1
# 預期輸出：顯示 __init__.py 和 recommendation_engine.py

# 2. 驗證專案中無遺漏的引用
grep -r "from recommendation_module" . --exclude-dir=__pycache__ --exclude-dir=.git --exclude-dir=archive
# 預期輸出：無結果（或只有註解中的舊引用）
```

### 5.3 棄用警告驗證（方案 A）

```bash
# 驗證棄用警告會正確顯示
python -c "
import warnings
warnings.simplefilter('always')
try:
    from recommendation_module_legacy import RecommendationEngine
    print('✓ 棄用警告已正確觸發')
except DeprecationWarning as e:
    print(f'✓ 棄用警告內容: {e}')
"
```

### 5.4 完整性驗證
- [ ] 所有測試通過（如果採用方案 A）
- [ ] `examples/main_example.py` 仍可正常運行（如果採用方案 A）
- [ ] 專案結構清晰，無重複或混淆的模組名稱
- [ ] `app_module/recommendation_service.py` 的功能說明已明確標註為新版推薦方式

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

**如果採用方案 A（重命名為 legacy）：**

**Step 1: 恢復目錄名稱**
```bash
mv recommendation_module_legacy recommendation_module
```

**Step 2: 恢復所有引用檔案的 import**

將以下檔案的 import 改回原樣：
- `examples/main_example.py`
- `tests/test_recommendation/test_recommendation_report.py`
- `tests/test_backtest/test_backtest_recommendation.py`
- 其他在 Step 4.1 中發現的引用檔案

**Step 3: 恢復 __init__.py**
移除 `recommendation_module/__init__.py` 中的棄用警告，恢復原始內容。

**如果採用方案 B（移動到 archive）：**

**Step 1: 恢復目錄位置**
```bash
mv archive/recommendation_module_legacy recommendation_module
```

**Step 2: 恢復所有引用檔案的 import**

將所有更新過的 import 改回原樣（如果有的話）。

### 6.3 回退驗證
```bash
# 確認 recommendation_module 已恢復
ls recommendation_module/ 2>&1
# 預期輸出：顯示 __init__.py 和 recommendation_engine.py

# 確認所有引用已恢復
grep -r "from recommendation_module" . --exclude-dir=__pycache__ --exclude-dir=.git
# 預期輸出：顯示所有引用檔案都有 "from recommendation_module import"

# 執行測試確認功能恢復
python -m pytest tests/ -v
```

---

## 檢查清單

- [ ] **使用情況檢查**：已完整檢查所有 `recommendation_module` 的引用
- [ ] **方案選擇**：已根據檢查結果選擇並執行對應方案（A 或 B）
- [ ] **目錄處理**：目錄已重命名或移動到正確位置
- [ ] **Import 更新**：所有引用檔案的 import 已更新（如果採用方案 A）
- [ ] **棄用警告**：已添加棄用警告到 `__init__.py`（如果採用方案 A）
- [ ] **繁體中文檢查**：所有程式碼註解、文件字串使用繁體中文，無簡體中文
- [ ] **功能測試**：所有相關測試通過（如果採用方案 A）
- [ ] **無遺漏引用**：專案中不再有未更新的 `recommendation_module` 引用
- [ ] **結構清晰**：專案結構清晰，無重複或混淆的模組名稱
- [ ] **回退準備**：所有改動已 commit，可隨時回退

---

## 版本/變更註記

### v1.0 (2025-01-XX)
- 初始版本：清理 `recommendation_module` 重複，根據使用情況決定保留（legacy）或移除（archive）
- 完成使用情況檢查與處理方案執行
- 保持向後兼容（如果仍在使用）或歸檔（如果不再使用）

