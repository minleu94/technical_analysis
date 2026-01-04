# 每日股票更新故障排除指南

## 🎯 快速檢查清單

當每日股票更新卡住時，請按照以下順序檢查：

### 1️⃣ 檢查日誌文件（最優先）

**日誌文件位置：**
- `logs/update_stock_data.log` - 更新腳本日誌
- `data/logs/data_loader.log` - 數據加載器日誌
- `data/logs/config.log` - 配置日誌

**檢查方法：**
```bash
# 查看最新的錯誤日誌（最後 50 行）
powershell -Command "Get-Content logs\update_stock_data.log -Tail 50 -Encoding UTF8"

# 查看數據加載器日誌
powershell -Command "Get-Content data\logs\data_loader.log -Tail 50 -Encoding UTF8"
```

**常見錯誤：**
- ❌ `'charmap' codec can't encode characters` → 編碼問題（已修復，但可能仍有殘留）
- ❌ `HTTP 307` → API 重定向問題（應已處理）
- ❌ `Connection timeout` → 網路連線問題
- ❌ `File not found` → 路徑配置問題

---

### 2️⃣ 檢查數據狀態

**使用 UI 檢查：**
1. 打開 Qt UI：`python ui_qt/main.py`
2. 進入「數據更新」標籤頁
3. 點擊「檢查數據狀態」按鈕
4. 查看「每日股票數據」區塊顯示的狀態

**使用腳本檢查：**
```bash
# 執行驗證腳本
python scripts/qa_validate_update_tab.py
```

**檢查項目：**
- ✅ 最新日期是否正確
- ✅ 記錄數是否正常
- ✅ 狀態是否為 `ok`（不是 `unknown` 或 `error`）

---

### 3️⃣ 檢查更新進程

**檢查是否有卡住的進程：**
```bash
# Windows PowerShell
Get-Process python | Where-Object {$_.Path -like "*technical_analysis*"}
```

**如果發現卡住的進程：**
1. 記錄進程 ID
2. 嘗試正常關閉（先關閉 UI）
3. 如果無法關閉，可能需要強制終止（不建議，可能導致數據損壞）

---

### 4️⃣ 檢查網路連線

**測試 API 連線：**
```bash
# 測試是否能連接到 API
curl -I "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20250101&type=ALL&response=json"
```

**如果無法連線：**
- 檢查網路設定
- 檢查防火牆設定
- 檢查是否需要代理

---

### 5️⃣ 檢查文件權限

**檢查數據目錄權限：**
```bash
# 檢查目錄是否存在且可寫入
python -c "from pathlib import Path; p = Path('data/daily_price'); print(f'存在: {p.exists()}, 可寫: {p.exists() and p.is_dir()}')"
```

**如果權限不足：**
- 檢查資料夾是否為唯讀
- 檢查是否有其他程式正在使用檔案
- 檢查磁碟空間是否充足

---

## 🔍 常見問題與解決方案

### 問題 1：更新卡住，沒有反應

**症狀：**
- UI 顯示「更新中...」但沒有進度
- 日誌文件沒有新記錄
- 進度條不動

**可能原因：**
1. 網路連線問題（API 回應慢或超時）
2. 進程卡在等待回應
3. Worker 線程異常終止

**解決方案：**
1. **檢查日誌**：查看 `logs/update_stock_data.log` 最後的記錄
2. **重啟更新**：
   - 關閉 UI
   - 等待 10 秒
   - 重新打開 UI
   - 重新執行更新
3. **使用命令行更新**（繞過 UI）：
   ```bash
   python scripts/batch_update_daily_data.py --start-date 2025-01-01 --end-date 2025-01-10
   ```

---

### 問題 2：編碼錯誤（charmap codec）

**症狀：**
```
ERROR - 'charmap' codec can't encode characters in position 0-6: character maps to <undefined>
```

**原因：**
- Windows 預設編碼為 `cp1252`，無法處理中文字符
- 某些 `print()` 語句沒有使用 `logging`

**解決方案：**
1. **已修復**：大部分 `print()` 已改為 `logging`
2. **如果仍有問題**：
   - 檢查腳本是否使用 `logging` 而非 `print()`
   - 確保所有文件操作使用 `encoding='utf-8'`
3. **臨時解決**：設定環境變數
   ```bash
   $env:PYTHONIOENCODING="utf-8"
   python ui_qt/main.py
   ```

---

### 問題 3：HTTP 307 重定向錯誤

**症狀：**
```
HTTP 307 Temporary Redirect
```

**原因：**
- API 端點變更或需要重定向

**解決方案：**
1. **已處理**：`DataLoader` 已包含 Session 和 cookie 處理
2. **如果仍有問題**：
   - 檢查 `data_module/data_loader.py` 中的 `download_from_api()` 方法
   - 確認使用 `requests.Session()` 而非單次請求

---

### 問題 4：數據文件損壞或格式錯誤

**症狀：**
- 更新成功但無法讀取數據
- 合併時出現錯誤
- 推薦分析時出現格式錯誤

**檢查方法：**
```bash
# 檢查最新日期的數據文件
python -c "
from pathlib import Path
from datetime import datetime
import pandas as pd

date_str = datetime.today().strftime('%Y-%m-%d')
file_path = Path(f'data/daily_price/{date_str.replace(\"-\", \"\")}.csv')
if file_path.exists():
    df = pd.read_csv(file_path)
    print(f'行數: {len(df)}, 欄位: {list(df.columns)}')
else:
    print('文件不存在')
"
```

**解決方案：**
1. **刪除損壞的文件**：刪除有問題的日期文件
2. **重新下載**：使用更新功能重新下載該日期
3. **檢查合併文件**：如果 `stock_data_whole.csv` 損壞，可能需要重新合併

---

### 問題 5：Worker 線程問題

**症狀：**
```
QThread: Destroyed while thread is still running
```

**原因：**
- UI 關閉時 Worker 仍在執行
- Worker 沒有正確清理

**解決方案：**
1. **已修復**：`TaskWorker` 已改進清理邏輯
2. **如果仍有問題**：
   - 等待更新完成後再關閉 UI
   - 如果卡住，先取消任務再關閉

---

### 問題 6：顯示「成功 0 天，失敗 0 天」但實際有更新 ⭐ **常見問題**

**症狀：**
- UI 顯示：`更新完成：成功 0 天，失敗 0 天`
- 但實際上數據文件已存在或已下載
- 數據狀態顯示最新日期已更新

**排查順序：**

#### 步驟 1：檢查實際腳本輸出
```bash
# 直接執行更新腳本，查看實際輸出
python scripts/batch_update_daily_data.py --start-date 2025-12-23 --end-date 2026-01-02 --delay-min 1 --delay-max 1
```

**檢查重點：**
- 查看最後的總結行：`成功: X 天` 和 `失敗: X 天`
- 查看是否有 `[UPDATE_SUMMARY]` 標記的輸出
- 確認腳本實際執行的結果

#### 步驟 2：檢查數據文件是否真的存在
```bash
# 檢查指定日期範圍的文件
python -c "
from pathlib import Path
from datetime import datetime, timedelta

config_dir = Path('D:/Min/Python/Project/FA_Data/daily_price')  # 根據實際路徑調整
start = datetime(2025, 12, 24)
end = datetime(2026, 1, 2)

for i in range((end - start).days + 1):
    date = start + timedelta(days=i)
    if date.weekday() < 5:  # 只檢查工作日
        file_path = config_dir / f'{date.strftime(\"%Y%m%d\")}.csv'
        exists = '存在' if file_path.exists() else '不存在'
        print(f'{date.strftime(\"%Y-%m-%d\")}: {exists}')
"
```

#### 步驟 3：檢查 UpdateService 解析邏輯
**問題原因：**
1. `UpdateService` 無法正確解析腳本輸出
2. 日誌輸出到 `stderr`，包含時間戳等格式，正則表達式難以匹配
3. Unicode 字符（⚠、✓、✗）在編碼轉換時可能出問題

**解決方案：**
1. **已修復**（2026-01-02）：
   - `batch_update_daily_data.py` 現在會在最後輸出 `[UPDATE_SUMMARY] SUCCESS: X days, FAILED: Y days`
   - `UpdateService` 優先解析這個標記的總結行
   - 備用方案：從日誌行解析

2. **如果問題仍然存在**：
   - 檢查 `app_module/update_service.py` 中的解析邏輯
   - 確認 `subprocess.run()` 正確捕獲了 `stdout` 和 `stderr`
   - 檢查編碼設定是否為 `utf-8`

#### 步驟 4：驗證修復
```bash
# 測試 UpdateService 是否能正確解析
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').absolute()))

from data_module.config import TWStockConfig
from app_module.update_service import UpdateService

config = TWStockConfig()
service = UpdateService(config)

result = service.update_daily('2025-12-23', '2026-01-02', 1.0)
print(f'結果: {result[\"message\"]}')
print(f'成功: {len(result.get(\"updated_dates\", []))} 天')
print(f'失敗: {len(result.get(\"failed_dates\", []))} 天')
"
```

**預期結果：**
- 應該顯示實際的成功和失敗天數
- 例如：`更新完成：成功 6 天，失敗 2 天`

#### 步驟 5：檢查日誌輸出
```bash
# 查看 UpdateService 的調試日誌
# 在 app_module/update_service.py 中，查找包含 "[UpdateService]" 的日誌
```

**排查要點：**
- 確認 `[UPDATE_SUMMARY]` 標記是否出現在輸出中
- 確認正則表達式是否正確匹配
- 確認編碼是否正確處理

**已知修復記錄：**
- **2026-01-02**：添加 `[UPDATE_SUMMARY]` 標記輸出，改進解析邏輯
- **2026-01-02**：修復 Unicode 編碼問題，使用英文標記避免編碼錯誤

---

## 🛠️ 進階故障排除

### 使用驗證腳本

**執行完整驗證：**
```bash
# 驗證更新 Tab 功能
python scripts/qa_validate_update_tab.py

# 查看驗證報告
# output/qa/update_tab/VALIDATION_REPORT.md
```

**驗證項目包括：**
- Service 層方法測試
- UI ↔ Service Contract 驗證
- 數據狀態檢查邏輯
- 日期格式驗證

---

### 手動測試更新流程

**步驟 1：測試單日更新**
```bash
python scripts/update_daily_stock_data.py --date 2025-01-10
```

**步驟 2：檢查下載的文件**
```bash
# 檢查文件是否存在
dir data\daily_price\20250110.csv
```

**步驟 3：測試合併**
```bash
python scripts/merge_daily_data.py
```

**步驟 4：驗證合併結果**
```bash
python -c "
import pandas as pd
df = pd.read_csv('data/meta_data/stock_data_whole.csv')
print(f'總記錄數: {len(df)}')
print(f'最新日期: {df[\"date\"].max() if \"date\" in df.columns else \"N/A\"}')"
```

---

### 檢查配置

**檢查數據路徑配置：**
```python
from data_module.config import TWStockConfig

config = TWStockConfig()
print(f"數據根目錄: {config.data_root}")
print(f"每日價格目錄: {config.daily_price_dir}")
print(f"元數據目錄: {config.meta_data_dir}")
```

**如果路徑不正確：**
- 檢查環境變數 `DATA_ROOT`
- 檢查 `data_module/config.py` 中的預設路徑
- 確認路徑存在且可寫入

---

## 📞 獲取幫助

### 收集診斷資訊

如果問題無法解決，請收集以下資訊：

1. **日誌文件**：
   - `logs/update_stock_data.log`（最後 100 行）
   - `data/logs/data_loader.log`（最後 100 行）

2. **系統資訊**：
   ```bash
   python --version
   python -c "import sys; print(sys.platform)"
   ```

3. **配置資訊**：
   ```python
   from data_module.config import TWStockConfig
   config = TWStockConfig()
   print(config.data_root)
   ```

4. **錯誤截圖**：UI 錯誤訊息截圖

5. **操作步驟**：重現問題的詳細步驟

---

## 📚 相關文檔

- **[如何更新每日數據](HOW_TO_UPDATE_DAILY_DATA.md)** - 更新流程說明
- **[數據更新 Tab QA 問題](QA_UPDATE_TAB_ISSUES.md)** - 已知問題清單
- **[數據獲取邏輯](DATA_FETCHING_LOGIC.md)** - API 使用說明
- **[數據更新 Tab 驗證腳本](../scripts/qa_validate_update_tab.py)** - 自動驗證腳本

---

## ✅ 快速修復檢查表

### 情況 A：更新卡住或沒有反應

按順序執行：

- [ ] 1. 檢查日誌文件（`logs/update_stock_data.log`）
- [ ] 2. 檢查是否有卡住的 Python 進程
- [ ] 3. 重啟 UI 應用程式
- [ ] 4. 使用命令行更新測試（`batch_update_daily_data.py`）
- [ ] 5. 檢查網路連線
- [ ] 6. 檢查數據目錄權限
- [ ] 7. 執行驗證腳本（`qa_validate_update_tab.py`）
- [ ] 8. 檢查配置路徑是否正確

### 情況 B：顯示「成功 0 天，失敗 0 天」但實際有更新 ⭐

按順序執行：

- [ ] 1. **直接執行腳本查看實際輸出**：
  ```bash
  python scripts/batch_update_daily_data.py --start-date 2025-12-23 --end-date 2026-01-02
  ```
  檢查最後的總結行是否顯示正確的天數

- [ ] 2. **檢查數據文件是否真的存在**：
  ```bash
  dir data\daily_price\*.csv
  ```
  確認文件確實已下載

- [ ] 3. **檢查 UpdateService 解析邏輯**：
  - 查看 `app_module/update_service.py` 中的解析代碼
  - 確認是否有 `[UPDATE_SUMMARY]` 標記的輸出
  - 檢查編碼設定是否為 `utf-8`

- [ ] 4. **驗證修復**：
  - 重新執行更新，查看是否正確顯示天數
  - 如果仍顯示 0 天，檢查日誌中的調試訊息

- [ ] 5. **如果問題持續**：
  - 檢查 `scripts/batch_update_daily_data.py` 是否包含 `[UPDATE_SUMMARY]` 輸出
  - 檢查 `app_module/update_service.py` 的解析邏輯是否正確
  - 查看相關修復記錄（2026-01-02）

如果以上都無法解決，請收集診斷資訊並查看相關文檔。

