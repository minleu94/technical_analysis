# Agent Prompt: 整理文件組織

## 1) 任務目標

清理專案根目錄，整理測試腳本與實驗文件，將測試腳本遷移到 `tests/scripts/`，實驗文件整理到 `notebooks/`，工具模組統一到 `utils/`，提升專案結構清晰度與可維護性。

**語言要求**：所有程式碼註解、文件字串（docstring）、註釋必須使用繁體中文，嚴禁使用簡體中文。

## 2) 影響範圍

### 需要遷移的檔案

**測試腳本（5 個檔案）**：
- `scripts/test_all_branches_one_day.py` → `tests/scripts/test_all_branches_one_day.py`
- `scripts/test_broker_branch_10days.py` → `tests/scripts/test_broker_branch_10days.py`
- `scripts/test_broker_branch_single.py` → `tests/scripts/test_broker_branch_single.py`
- `scripts/test_moneydj_requests_tables.py` → `tests/scripts/test_moneydj_requests_tables.py`
- `scripts/test_moneydj_requests.py` → `tests/scripts/test_moneydj_requests.py`

**實驗文件 - Jupyter Notebooks（4 個檔案）**：
- `01_stock_data_collector.ipynb` → `notebooks/01_stock_data_collector.ipynb`
- `02_technical_calculator.ipynb` → `notebooks/02_technical_calculator.ipynb`
- `Crawler.ipynb` → `notebooks/Crawler.ipynb`
- `install_dependencies.ipynb` → `notebooks/install_dependencies.ipynb`

**實驗文件 - Markdown（2 個檔案，可選）**：
- `01_stock_data_collector.md` → `notebooks/01_stock_data_collector.md` 或 `docs/experimental/01_stock_data_collector.md`
- `02_technical_calculator.md` → `notebooks/02_technical_calculator.md` 或 `docs/experimental/02_technical_calculator.md`

**工具模組（1 個檔案）**：
- `technical_analysis/utils/io_utils.py` → `utils/io_utils.py`

### 需要修改的檔案（更新 import 路徑）

**工具模組引用（3 個檔案）**：
- `scripts/update_all_data.py`（更新 `from technical_analysis.utils.io_utils` → `from utils.io_utils`）
- `scripts/update_stock_data.py`（更新 `from technical_analysis.utils.io_utils` → `from utils.io_utils`）
- `tests/e2e/test_data_path_isolation.py`（更新 `from technical_analysis.utils.io_utils` → `from utils.io_utils`）

### 需要處理的目錄（可選）

**demo_* 目錄（7 個目錄，可選）**：
- `demo_atomic_data/` → 保留或移動到 `archive/demo_atomic_data/`
- `demo_atomic_output/` → 保留或移動到 `archive/demo_atomic_output/`
- `demo_dry_run_data/` → 保留或移動到 `archive/demo_dry_run_data/`
- `demo_dry_run_output/` → 保留或移動到 `archive/demo_dry_run_output/`
- `demo_helpers_data/` → 保留或移動到 `archive/demo_helpers_data/`
- `demo_helpers_output/` → 保留或移動到 `archive/demo_helpers_output/`
- `demo_test_data/` → 保留或移動到 `archive/demo_test_data/`

### 需要刪除的目錄（如果為空）

- `technical_analysis/`（移動 `utils/` 後，如果目錄為空則刪除）

## 3) 明確禁止事項

1. **禁止修改測試腳本邏輯**：遷移測試腳本時，不得修改任何測試邏輯、斷言或功能
2. **禁止修改 Notebook 內容**：移動 `.ipynb` 檔案時，不得修改任何 cell 內容或執行結果
3. **禁止修改工具模組功能**：移動 `io_utils.py` 時，不得修改任何函數實作或介面
4. **禁止刪除 demo_* 目錄**：即使移動到 archive，也不得直接刪除，保留歷史記錄
5. **禁止修改業務邏輯**：不得修改任何業務邏輯模組（`app_module`, `decision_module`, `analysis_module` 等）
6. **禁止修改測試檔案**：除了更新 import 路徑外，不得修改 `tests/` 目錄下的其他檔案
7. **禁止使用簡體中文**：所有程式碼註解、文件字串（docstring）、變數名稱、註釋必須使用繁體中文，嚴禁使用簡體中文
8. **禁止跳過驗證步驟**：必須完整執行所有檢查與驗證步驟，確保所有檔案可正常運作

## 4) 實作步驟

### Step 4.1: 遷移測試腳本到 tests/scripts/

**操作**：
1. 創建 `tests/scripts/` 目錄（如果不存在）
   ```bash
   mkdir -p tests/scripts
   ```

2. 移動 5 個測試腳本檔案
   ```bash
   mv scripts/test_all_branches_one_day.py tests/scripts/
   mv scripts/test_broker_branch_10days.py tests/scripts/
   mv scripts/test_broker_branch_single.py tests/scripts/
   mv scripts/test_moneydj_requests_tables.py tests/scripts/
   mv scripts/test_moneydj_requests.py tests/scripts/
   ```

3. 檢查這些檔案是否有相對路徑引用需要更新（通常不需要，因為它們是獨立腳本）

### Step 4.2: 整理實驗文件 - 創建 notebooks/ 目錄並移動 Jupyter Notebooks

**操作**：
1. 創建 `notebooks/` 目錄
   ```bash
   mkdir notebooks
   ```

2. 移動 4 個 Jupyter Notebook 檔案
   ```bash
   mv 01_stock_data_collector.ipynb notebooks/
   mv 02_technical_calculator.ipynb notebooks/
   mv Crawler.ipynb notebooks/
   mv install_dependencies.ipynb notebooks/
   ```

3. 移動實驗性 Markdown 檔案（可選，建議移動到 `notebooks/` 以保持關聯）
   ```bash
   mv 01_stock_data_collector.md notebooks/
   mv 02_technical_calculator.md notebooks/
   ```

### Step 4.3: 處理 technical_analysis/utils/ → utils/

**操作**：
1. 創建 `utils/` 目錄（根目錄）
   ```bash
   mkdir utils
   ```

2. 移動 `io_utils.py`
   ```bash
   mv technical_analysis/utils/io_utils.py utils/io_utils.py
   ```

3. 創建 `utils/__init__.py`（如果不存在）
   ```python
   """
   工具模組（Utilities）
   提供通用工具函數
   """
   
   from utils.io_utils import atomic_write_df, safe_write_with_dry_run
   
   __all__ = ['atomic_write_df', 'safe_write_with_dry_run']
   ```

4. 更新所有引用檔案的 import 路徑

   **檔案 1: `scripts/update_all_data.py`**
   ```python
   # 舊的 import（約第 27 行）
   # from technical_analysis.utils.io_utils import safe_write_with_dry_run
   
   # 新的 import（替換為）
   from utils.io_utils import safe_write_with_dry_run
   ```

   **檔案 2: `scripts/update_stock_data.py`**
   ```python
   # 舊的 import（約第 14 行）
   # from technical_analysis.utils.io_utils import safe_write_with_dry_run
   
   # 新的 import（替換為）
   from utils.io_utils import safe_write_with_dry_run
   ```

   **檔案 3: `tests/e2e/test_data_path_isolation.py`**
   ```python
   # 舊的 import（約第 20 行）
   # from technical_analysis.utils.io_utils import atomic_write_df, safe_write_with_dry_run
   
   # 新的 import（替換為）
   from utils.io_utils import atomic_write_df, safe_write_with_dry_run
   ```

5. 檢查 `technical_analysis/` 目錄是否為空
   ```bash
   # 檢查目錄內容
   ls technical_analysis/
   # 如果只有 __pycache__ 或為空，則刪除
   rm -rf technical_analysis/
   # Windows: rmdir /s /q technical_analysis
   ```

### Step 4.4: 處理 demo_* 目錄（可選）

**操作**：
根據專案需求選擇以下方案之一：

**方案 A：移動到 archive（如果確認不再使用）**
```bash
# 創建 archive 目錄（如果不存在）
mkdir -p archive

# 移動所有 demo_* 目錄
mv demo_atomic_data archive/
mv demo_atomic_output archive/
mv demo_dry_run_data archive/
mv demo_dry_run_output archive/
mv demo_helpers_data archive/
mv demo_helpers_output archive/
mv demo_test_data archive/
```

**方案 B：保留但添加 .gitignore 規則（如果仍在使用）**
在 `.gitignore` 中添加：
```
# Demo 目錄（測試用，不提交）
demo_*/
demo_*/*/
```

**方案 C：保留不變（如果仍在使用且需要提交）**
不做任何處理。

**建議**：先檢查這些目錄的使用情況，如果確認不再使用，採用方案 A；如果不確定，採用方案 B。

### Step 4.5: 驗證所有檔案可正常運作

**操作**：
1. 檢查所有移動的檔案是否存在於新位置
2. 檢查所有 import 路徑是否已更新
3. 執行相關測試與腳本驗證

## 5) 完成條件

### 5.1 靜態檢查
- [ ] `tests/scripts/` 目錄存在，包含 5 個測試腳本檔案
- [ ] `notebooks/` 目錄存在，包含 4 個 Jupyter Notebook 檔案
- [ ] `utils/` 目錄存在，包含 `io_utils.py` 和 `__init__.py`
- [ ] 所有 3 個引用檔案的 import 已從 `technical_analysis.utils.io_utils` 更新為 `utils.io_utils`
- [ ] `scripts/` 目錄中不再有 `test_*.py` 檔案
- [ ] 根目錄中不再有 `.ipynb` 檔案（除了可能遺漏的）
- [ ] `technical_analysis/` 目錄已刪除（如果為空）
- [ ] 所有程式碼註解、文件字串使用繁體中文，無簡體中文

### 5.2 功能驗證

**驗證工具模組 import**：
```bash
# 1. 驗證 utils 模組可正常 import
python -c "
from utils.io_utils import atomic_write_df, safe_write_with_dry_run
print('✓ utils.io_utils import 成功')
"

# 2. 驗證所有更新後的檔案可正常 import
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from scripts.update_all_data import *
print('✓ scripts/update_all_data.py import 成功')
"

python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from scripts.update_stock_data import *
print('✓ scripts/update_stock_data.py import 成功')
"

python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))
from tests.e2e.test_data_path_isolation import *
print('✓ tests/e2e/test_data_path_isolation.py import 成功')
"
```

**驗證測試腳本位置**：
```bash
# 確認測試腳本在新位置
ls tests/scripts/test_*.py
# 預期輸出：5 個檔案

# 確認測試腳本不在舊位置
ls scripts/test_*.py 2>&1
# 預期輸出：No such file or directory（或無結果）
```

**驗證 Notebook 位置**：
```bash
# 確認 Notebook 在新位置
ls notebooks/*.ipynb
# 預期輸出：4 個檔案

# 確認 Notebook 不在根目錄
ls *.ipynb 2>&1
# 預期輸出：No such file or directory（或無結果，除了可能遺漏的）
```

### 5.3 腳本執行驗證（可選）
```bash
# 如果可能，執行一個測試腳本驗證路徑正確
# 注意：這些腳本可能需要特定環境，僅在確認環境可用時執行
python tests/scripts/test_moneydj_requests.py --help 2>&1 || echo "腳本可能需要特定環境"
```

### 5.4 完整性驗證
- [ ] 所有測試通過（執行 `python -m pytest tests/ -v`）
- [ ] 所有腳本可正常 import（無語法錯誤）
- [ ] 專案結構清晰，根目錄不再混亂
- [ ] 所有檔案路徑正確，無遺漏或錯誤

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

**Step 1: 恢復測試腳本位置**
```bash
mv tests/scripts/test_all_branches_one_day.py scripts/
mv tests/scripts/test_broker_branch_10days.py scripts/
mv tests/scripts/test_broker_branch_single.py scripts/
mv tests/scripts/test_moneydj_requests_tables.py scripts/
mv tests/scripts/test_moneydj_requests.py scripts/
rmdir tests/scripts 2>/dev/null || true  # 如果目錄為空則刪除
```

**Step 2: 恢復 Notebook 位置**
```bash
mv notebooks/01_stock_data_collector.ipynb .
mv notebooks/02_technical_calculator.ipynb .
mv notebooks/Crawler.ipynb .
mv notebooks/install_dependencies.ipynb .
mv notebooks/01_stock_data_collector.md . 2>/dev/null || true
mv notebooks/02_technical_calculator.md . 2>/dev/null || true
rmdir notebooks 2>/dev/null || true  # 如果目錄為空則刪除
```

**Step 3: 恢復工具模組位置**
```bash
# 恢復 technical_analysis 目錄結構
mkdir -p technical_analysis/utils
mv utils/io_utils.py technical_analysis/utils/
rmdir utils 2>/dev/null || true  # 如果目錄為空則刪除
```

**Step 4: 恢復所有引用檔案的 import**

將以下 3 個檔案的 import 改回原樣：
- `scripts/update_all_data.py`（約第 27 行）
- `scripts/update_stock_data.py`（約第 14 行）
- `tests/e2e/test_data_path_isolation.py`（約第 20 行）

```python
# 恢復為
from technical_analysis.utils.io_utils import safe_write_with_dry_run
# 或
from technical_analysis.utils.io_utils import atomic_write_df, safe_write_with_dry_run
```

**Step 5: 恢復 demo_* 目錄（如果已移動）**
```bash
# 如果移動到 archive，恢復到根目錄
mv archive/demo_atomic_data .
mv archive/demo_atomic_output .
mv archive/demo_dry_run_data .
mv archive/demo_dry_run_output .
mv archive/demo_helpers_data .
mv archive/demo_helpers_output .
mv archive/demo_test_data .
```

### 6.3 回退驗證
```bash
# 確認測試腳本已恢復
ls scripts/test_*.py
# 預期輸出：5 個檔案

# 確認 Notebook 已恢復
ls *.ipynb
# 預期輸出：4 個檔案

# 確認工具模組已恢復
ls technical_analysis/utils/io_utils.py
# 預期輸出：檔案存在

# 確認所有 import 已恢復
grep -r "from technical_analysis.utils.io_utils" scripts/ tests/
# 預期輸出：3 個檔案都有正確的 import

# 執行測試確認功能恢復
python -m pytest tests/ -v
```

---

## 檢查清單

- [ ] **測試腳本遷移**：5 個測試腳本已移動到 `tests/scripts/`
- [ ] **Notebook 整理**：4 個 Jupyter Notebook 已移動到 `notebooks/`
- [ ] **工具模組遷移**：`io_utils.py` 已移動到 `utils/`，並創建 `__init__.py`
- [ ] **Import 更新**：3 個引用檔案的 import 已更新為 `utils.io_utils`
- [ ] **目錄清理**：`technical_analysis/` 目錄已刪除（如果為空）
- [ ] **demo_* 處理**：demo_* 目錄已處理（移動到 archive 或保留）
- [ ] **繁體中文檢查**：所有程式碼註解、文件字串使用繁體中文，無簡體中文
- [ ] **功能測試**：所有相關測試通過，腳本可正常 import
- [ ] **結構清晰**：根目錄不再混亂，檔案組織清晰
- [ ] **回退準備**：所有改動已 commit，可隨時回退

---

## 版本/變更註記

### v1.0 (2025-01-XX)
- 初始版本：整理文件組織，清理根目錄
- 完成測試腳本遷移到 `tests/scripts/`
- 完成實驗文件整理到 `notebooks/`
- 完成工具模組統一到 `utils/`
- 保持所有功能正常運作

