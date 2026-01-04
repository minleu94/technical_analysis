# 券商分點資料更新功能 - 測試與故障排除指南

## 最後更新：2025-12-29

---

## 一、快速測試方法

### 1.1 測試單一分點（推薦先用這個）

```bash
python scripts/test_broker_branch_single.py
```

**預期結果**：
- 成功下載 1 個分點的資料
- 記錄數 > 0
- 無錯誤訊息

### 1.2 測試所有分點（一天）

```bash
python scripts/test_all_branches_one_day.py
```

**預期結果**：
- 所有 6 個分點都成功下載
- 每個分點都有記錄數（通常 50-100 筆）
- 總記錄數 = 6 × 單一分點記錄數

### 1.3 測試多天資料（10 天）

```bash
python scripts/test_broker_branch_10days.py
```

**預期結果**：
- 成功下載至少 10 個交易日的資料
- 每個分點都有對應的 CSV 檔案

---

## 二、常見問題與解決方案

### 2.1 URL 參數錯誤

**問題現象**：
- 頁面載入超時
- 找不到足夠的表格
- 頁面內容過少

**原因**：
- URL 參數 `c` 應該是 `B` 而不是 `E`
- 日期範圍應該是 `e=前一天&f=當天` 而不是 `e=當天&f=當天`

**解決方案**：
- 檢查 `app_module/broker_branch_update_service.py` 中的 `_build_branch_url` 方法
- 確認使用 `c=B` 參數
- 確認日期範圍邏輯：`e=prev_date&f=date`（前一天到當天）

**驗證方法**：
```python
# 檢查 URL 格式
url = service._build_branch_url(branch_info, '2025-12-21', '2025-12-22')
# 應該包含：c=B&e=2025-12-21&f=2025-12-22
```

### 2.2 Registry 檔案編碼問題（Mojibake）

**問題現象**：
- `branch_display_name` 顯示為亂碼（例如：`æ°¸è±ç«¹åŒ—`）
- 中文名稱無法正確顯示

**原因**：
- CSV 檔案編碼不正確（不是 UTF-8 with BOM）
- 讀取時使用了錯誤的編碼

**解決方案**：
1. **自動修復**：系統會自動檢測並修復 mojibake
   - 檢測到亂碼時會自動修復
   - 修復後會寫回 registry 檔案

2. **手動修復**：
   ```bash
   python scripts/fix_broker_branch_registry.py
   ```

3. **驗證修復**：
   ```bash
   python scripts/verify_registry.py
   ```

**預防措施**：
- 所有 CSV 讀寫操作都使用 `encoding='utf-8-sig'`
- Registry 檔案自動修復機制已內建

### 2.3 URL 參數前導零丟失

**問題現象**：
- URL 中的 `b` 參數缺少前導零（例如：`b=39004100390050` 應該是 `b=0039004100390050`）
- 頁面無法正確載入

**原因**：
- CSV 讀取時將 `url_param_b` 當作數字處理，前導零被移除

**解決方案**：
1. **自動修復**：系統會自動檢測並修復
   - 讀取時強制 `url_param_b` 為字串類型
   - 檢測到缺少前導零時自動修復

2. **手動檢查**：
   ```python
   import pandas as pd
   from data_module.config import TWStockConfig
   
   config = TWStockConfig()
   df = pd.read_csv(config.broker_branch_registry_file, encoding='utf-8-sig', dtype={'url_param_b': str})
   print(df[['branch_system_key', 'url_param_b']])
   ```

**驗證方法**：
- 檢查 URL 日誌，確認 `b` 參數包含前導零
- 例如：`b=0039004100390050`（正確）vs `b=39004100390050`（錯誤）

### 2.4 ChromeDriver 崩潰

**問題現象**：
- `TimeoutException` 或 `WebDriverException`
- Stacktrace 顯示 ChromeDriver 崩潰
- 錯誤訊息包含 `'session'`, `'chrome'`, `'driver'`, `'crash'`

**原因**：
- ChromeDriver 版本不匹配
- 記憶體不足
- 頁面載入超時

**解決方案**：
1. **自動恢復**：系統會自動檢測並重新創建 driver
   - 檢測到 driver 崩潰時自動重建
   - 最多重試 3 次

2. **手動檢查**：
   - 確認 Chrome 瀏覽器版本
   - 更新 ChromeDriver 到匹配版本
   - 檢查系統記憶體使用情況

3. **調整參數**：
   - 增加 `delay_seconds`（例如：5-6 秒）
   - 增加超時時間（目前：頁面載入 45 秒，腳本執行 30 秒）

**驗證方法**：
- 查看日誌中的 driver 重建訊息
- 確認重試後是否成功

### 2.5 頁面載入超時

**問題現象**：
- `TimeoutException: Message: ...`
- 頁面內容過少
- 找不到表格

**原因**：
- 網路連線慢
- MoneyDJ 網站響應慢
- 頁面需要 JavaScript 執行（動態載入）

**解決方案**：
1. **增加超時時間**（已實現）：
   - 頁面載入超時：45 秒
   - 腳本執行超時：30 秒
   - 等待表格載入：10 秒

2. **改進等待策略**（已實現）：
   - 先等待 `body` 標籤載入（15 秒）
   - 額外等待 2 秒讓 JavaScript 執行
   - 檢查頁面內容長度（至少 500 字符）

3. **檢查網路**：
   - 確認網路連線正常
   - 嘗試手動訪問 URL 確認網站可訪問

### 2.6 無法解析對手券商名稱

**問題現象**：
- 警告訊息：`無法解析對手券商名稱: 元大高股息`
- 警告訊息：`無法解析對手券商名稱: 6643M31`

**原因**：
- 這些是 ETF 名稱或特殊格式，不是標準的券商名稱格式
- 系統會將它們標記為 `counterparty_broker_code='UNKNOWN'`

**解決方案**：
- **這是正常行為**，不需要修復
- ETF 名稱（如「元大高股息」、「元大台灣50」）會被標記為 `UNKNOWN`
- 資料仍會正常保存，只是 `counterparty_broker_code` 為 `UNKNOWN`

---

## 三、測試腳本說明

### 3.1 `test_broker_branch_single.py`

**用途**：快速測試單一分點的一天資料

**功能**：
- 測試單一分點（永豐竹北）
- 強制重新抓取（`force_all=True`）
- 顯示詳細結果

**使用方式**：
```bash
python scripts/test_broker_branch_single.py
```

### 3.2 `test_all_branches_one_day.py`

**用途**：測試所有分點的一天資料

**功能**：
- 測試所有 6 個分點
- 強制重新抓取（`force_all=True`）
- 顯示每個分點的成功/失敗狀態

**使用方式**：
```bash
python scripts/test_all_branches_one_day.py
```

### 3.3 `test_broker_branch_10days.py`

**用途**：測試多天資料（10 天）

**功能**：
- 測試所有分點的 10 天資料
- 先測試單一分點，成功後再測試全部
- 顯示詳細進度和結果

**使用方式**：
```bash
python scripts/test_broker_branch_10days.py
```

### 3.4 `check_branch_files.py`

**用途**：檢查下載的檔案是否存在

**功能**：
- 檢查指定日期的所有分點檔案
- 顯示每個檔案的記錄數

**使用方式**：
```bash
python scripts/check_branch_files.py
```

### 3.5 `verify_branch_data.py`

**用途**：驗證下載的資料格式

**功能**：
- 讀取並顯示 CSV 檔案內容
- 檢查欄位和資料類型
- 顯示前幾筆記錄

**使用方式**：
```bash
python scripts/verify_branch_data.py
```

---

## 四、URL 格式說明

### 4.1 正確的 URL 格式

```
https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm
  ?a={broker_code}           # 券商代碼（例如：9A00、9200）
  &b={branch_code}           # 分點代碼（例如：0039004100390050、9268）
  &c=B                       # 固定值：B（不是 E）
  &e={start_date}            # 開始日期（YYYY-MM-DD，前一天）
  &f={end_date}              # 結束日期（YYYY-MM-DD，當天）
```

### 4.2 範例

**康和永和（2025-12-29）**：
```
https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm
  ?a=8450
  &b=0038003400350042
  &c=B
  &e=2025-12-28
  &f=2025-12-29
```

**永豐竹北（2025-12-22）**：
```
https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm
  ?a=9A00
  &b=0039004100390050
  &c=B
  &e=2025-12-21
  &f=2025-12-22
```

### 4.3 重要注意事項

1. **`c` 參數必須是 `B`**（不是 `E`）
2. **日期範圍**：`e=前一天&f=當天`（不是 `e=當天&f=當天`）
3. **`b` 參數必須保留前導零**（例如：`0039004100390050` 不是 `39004100390050`）

---

## 五、資料存儲結構

### 5.1 目錄結構

```
{data_root}/broker_flow/
  ├── {branch_system_key}/
  │   ├── daily/
  │   │   ├── YYYY-MM-DD.csv      # 每日資料
  │   │   └── ...
  │   └── meta/
  │       └── merged.csv          # 合併後的資料
  └── ...
```

### 5.2 檔案命名規則

- **每日檔案**：`{YYYY-MM-DD}.csv`（例如：`2025-12-22.csv`）
- **合併檔案**：`merged.csv`
- **檔名不得包含中文或空白**

### 5.3 CSV 檔案欄位

**每日檔案欄位**：
- `date`：日期（YYYY-MM-DD）
- `trade_type`：交易類型（買超/賣超）
- `branch_system_key`：分點主鍵（例如：`9A00_9A9P`）
- `branch_broker_code`：券商代碼（例如：`9A00`）
- `branch_code`：分點代碼（例如：`9A9P`）
- `branch_display_name`：顯示名稱（例如：`永豐竹北`）
- `counterparty_broker_code`：對手券商代碼（或 `UNKNOWN`）
- `counterparty_broker_name`：對手券商名稱
- `buy_qty`：買進數量
- `sell_qty`：賣出數量
- `net_qty`：淨數量

---

## 六、Registry 檔案說明

### 6.1 檔案位置

```
{meta_data_dir}/broker_branch_registry.csv
```

### 6.2 欄位定義

| 欄位名 | 型別 | 說明 | 範例 |
|--------|------|------|------|
| `branch_system_key` | str | 分點主鍵 | `9A00_9A9P` |
| `branch_broker_code` | str | 券商代碼 | `9A00` |
| `branch_code` | str | 分點代碼 | `9A9P` |
| `branch_display_name` | str | 顯示名稱 | `永豐竹北` |
| `url_param_a` | str | URL 參數 a | `9A00` |
| `url_param_b` | str | URL 參數 b（保留前導零） | `0039004100390050` |
| `is_active` | bool | 是否啟用 | `True` |
| `created_at` | str | 建立時間 | `2025-12-27T00:00:00` |
| `updated_at` | str | 更新時間 | `2025-12-27T00:00:00` |

### 6.3 當前追蹤的分點

1. **永豐竹北**：`9A00_9A9P`
   - `url_param_a`: `9A00`
   - `url_param_b`: `0039004100390050`

2. **凱基台北**：`9200_9268`
   - `url_param_a`: `9200`
   - `url_param_b`: `9268`

3. **凱基信義**：`9200_9216`
   - `url_param_a`: `9200`
   - `url_param_b`: `9216`

4. **凱基松山**：`9200_9217`
   - `url_param_a`: `9200`
   - `url_param_b`: `9217`

5. **群益民權**：`9100_9131`
   - `url_param_a`: `9100`
   - `url_param_b`: `9131`

6. **康和永和**：`8450_845B`
   - `url_param_a`: `8450`
   - `url_param_b`: `0038003400350042`

---

## 七、已知限制與注意事項

### 7.1 頁面動態載入

- MoneyDJ 頁面需要 JavaScript 執行才能顯示完整內容
- 使用 `requests` 無法抓取完整資料（只能抓到 5 個表格）
- **必須使用 Selenium** 才能抓取完整資料（15+ 個表格）

### 7.2 對手券商解析

- 表格中的「券商名稱」欄位可能包含：
  - 標準券商名稱（例如：`1234元大證券`）→ 可解析
  - ETF 名稱（例如：`元大高股息`）→ 標記為 `UNKNOWN`
  - 特殊格式（例如：`6643M31`）→ 標記為 `UNKNOWN`

### 7.3 資料完整性

- 某些日期可能沒有交易數據（例如：假日、特殊情況）
- 系統會記錄警告但不會失敗
- 檢查日誌中的「沒有交易數據」訊息

### 7.4 Windows 終端機編碼

- Windows PowerShell 可能無法正確顯示中文
- 編碼錯誤不影響功能，只是顯示問題
- 測試腳本已設置 UTF-8 編碼處理

---

## 八、驗證清單

### 8.1 基本功能驗證

- [ ] 所有 6 個分點都能成功下載資料
- [ ] URL 格式正確（`c=B&e=前一天&f=當天`）
- [ ] 每個分點都有記錄數（通常 50-100 筆）
- [ ] CSV 檔案正確保存到對應目錄
- [ ] Registry 檔案中文顯示正常（無 mojibake）

### 8.2 資料格式驗證

- [ ] CSV 檔案包含所有必要欄位
- [ ] `branch_system_key` 與分點一致
- [ ] 日期格式正確（YYYY-MM-DD）
- [ ] 數值欄位（buy_qty, sell_qty, net_qty）為數字類型

### 8.3 穩定性驗證

- [ ] ChromeDriver 崩潰時能自動恢復
- [ ] 頁面載入超時時能重試
- [ ] 網路問題時能正確處理錯誤

---

## 九、測試記錄

### 9.1 2025-12-29 測試結果

**測試環境**：
- 日期：2025-12-22
- 分點數：6 個
- 測試腳本：`test_all_branches_one_day.py`

**測試結果**：
- ✅ 所有 6 個分點都成功下載
- ✅ 每個分點都有 100 筆記錄
- ✅ 總記錄數：600 筆
- ✅ URL 格式正確：`c=B&e=2025-12-21&f=2025-12-22`
- ✅ 無失敗分點或日期

**修復內容**：
1. URL 參數 `c`：從 `E` 改為 `B`
2. 日期範圍：從 `e=date&f=date` 改為 `e=prev_date&f=date`
3. Registry 自動修復：修復 `url_param_b` 前導零問題
4. Selenium 穩定性：改進超時處理、錯誤檢測、driver 重建
5. `datetime` 導入：移除函數內重複導入

---

## 十、參考資料

- **設計文檔**：`docs/BROKER_BRANCH_DATA_MODULE_DESIGN_V2.md`
- **實作總結**：`docs/BROKER_BRANCH_IMPLEMENTATION_SUMMARY.md`
- **原始爬蟲**：`Crawler.ipynb`
- **修復腳本**：`scripts/fix_broker_branch_registry.py`
- **驗證腳本**：`scripts/verify_registry.py`

---

**最後更新**：2025-12-29  
**維護者**：系統開發團隊

