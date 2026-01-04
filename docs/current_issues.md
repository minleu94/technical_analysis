# 當前開發問題與解決方案

## 🔴 當前最優先問題：數據更新 API 連接問題

### 問題描述
- **現象**：無法從台灣證交所 API 更新股票數據
- **錯誤**：HTTP 307 重定向錯誤，API 返回「頁面無法執行，因為安全性考量」
- **影響範圍**：
  - `01_stock_data_collector.ipynb` - notebook 版本無法更新
  - `01_stock_data_collector_enhanced.py` - enhanced 版本無法更新
  - `scripts/update_stock_data.py` - 正式腳本也遇到相同問題
  - `data_module/data_loader.py` - 數據加載器也遇到 307 錯誤

### 問題分析

#### 1. API 防護機制增強
台灣證交所可能加強了 API 防護：
- 需要更真實的瀏覽器行為
- 可能需要更完整的 cookie 和 session 處理
- 可能有請求頻率限制

#### 2. 不同版本的實現差異

**Notebook 版本** (`01_stock_data_collector.ipynb`):
- 使用 `type=ALL`
- 直接 `requests.get(url)`，無 session
- 使用 `data['tables'][8]` 獲取數據
- 使用 `stock_data['data']` 和 `stock_data['fields']` 構建 DataFrame

**Enhanced 版本** (`01_stock_data_collector_enhanced.py`):
- 使用 `type=ALLBUT0999`
- 使用 `headers` 但無 session
- 遍歷 `data['tables']` 尋找 `'個股行情'`
- 使用 `table.get('rows', [])` 獲取數據

**DataLoader 版本** (`data_module/data_loader.py`):
- 使用 `STOCK_DAY` API（不同端點）
- 使用 session 和 cookie
- 有等待時間和重試機制

### 已知問題記錄（從 docs/note.txt）

1. **技術問題**：
   - ✅ 數據源連接不穩定（當前主要問題）
   - 圖表顯示中文亂碼
   - 回測結果導出格式不統一

2. **下一步開發計劃（優先）**：
   - ✅ 每日股票數據更新與整合測試（當前問題）
   - 產業指數更新測試
   - 大盤指數更新測試

## 💡 解決方案建議

### 方案 1：改進 API 請求機制（推薦）

#### 1.1 使用更完整的瀏覽器模擬
```python
# 需要改進的地方：
- 使用 requests.Session() 維持 cookie
- 先訪問主頁獲取 cookie
- 添加更完整的 headers（Referer, Accept-Language 等）
- 增加隨機等待時間
- 處理重定向
```

#### 1.2 嘗試多種 API 端點
- `MI_INDEX` with `type=ALL`（notebook 方式）
- `MI_INDEX` with `type=ALLBUT0999`（enhanced 方式）
- `STOCK_DAY`（data_loader 方式）

#### 1.3 添加重試和錯誤處理
- 自動重試機制
- 錯誤日誌記錄
- 降級策略（如果一個 API 失敗，嘗試另一個）

### 方案 2：使用替代數據源

1. **FinMind API**（已在 enhanced 版本中部分實現）
   - 需要 API token
   - 更穩定的數據源
   - 可能需要付費

2. **yfinance**（用於大盤指數）
   - 已在 enhanced 版本中使用
   - 但個股數據可能不完整

### 方案 3：優化現有實現

基於 `01_stock_data_collector_enhanced.py` 改進：
1. 添加 session 和 cookie 處理
2. 改進錯誤處理
3. 添加多種 API 嘗試機制
4. 只更新 daily_price，不自動 merge

## 📋 建議的開發步驟

### 階段 1：修復 API 連接問題（當前優先）

1. **創建改進的更新腳本**
   - 基於 `01_stock_data_collector_enhanced.py`
   - 添加 session 和 cookie 處理
   - 實現多種 API 嘗試機制
   - 只更新 daily_price，不 merge

2. **測試和驗證**
   - 測試單日更新
   - 測試批量更新
   - 驗證數據格式正確性

3. **整合到正式腳本**
   - 更新 `scripts/update_stock_data.py`
   - 更新 `data_module/data_loader.py`

### 階段 2：完善數據更新流程

1. **分離更新和合併邏輯**
   - 更新 daily_price 是獨立步驟
   - merge 是另一個獨立步驟
   - 用戶可以選擇是否 merge

2. **改進錯誤處理**
   - 更詳細的錯誤日誌
   - 自動重試機制
   - 錯誤通知

### 階段 3：長期優化

1. **添加數據源備援**
   - 主要：證交所 API
   - 備用：FinMind、yfinance

2. **實現數據驗證**
   - 檢查數據完整性
   - 驗證數據格式
   - 自動修復常見問題

## 🛠️ 當前可用的工具

### 已創建的腳本
- `update_20250828.py` - 單日更新腳本（使用成功驗證的邏輯）
- `update_daily_enhanced.py` - 增強版更新腳本（支援 Selenium 和 FinMind 備用）
- `update_daily_only.py` - 只更新 daily_price，不 merge（基於 enhanced 版本改進）

### 使用方式
```bash
# 更新單日（推薦，使用成功驗證的邏輯）
python update_20250828.py --date 2025-08-28

# 使用增強版（支援多種數據源）
python update_daily_enhanced.py --date 2025-08-28

# 批量更新
python update_daily_only.py --start-date 2024-08-28 --end-date 2024-08-30
```

### 合併數據（手動執行）
```bash
python scripts/merge_daily_data.py
```

### 📖 詳細文檔
- **`DATA_FETCHING_LOGIC.md`** - 數據獲取邏輯詳細說明（包含使用方式和錯誤排查）
- **`docs/data_collection_architecture.md`** - 數據收集架構說明

## 📝 開發進度追蹤

### 當前狀態
- [x] 識別問題：API 307 錯誤
- [x] 分析不同版本的實現差異
- [x] 創建改進的更新腳本
- [ ] 測試和驗證 API 連接修復
- [ ] 整合到正式腳本
- [ ] 完善錯誤處理和日誌

### 下一步行動
1. 測試 `update_daily_only.py` 是否能成功更新數據
2. 如果仍然失敗，嘗試更完整的瀏覽器模擬
3. 考慮使用替代數據源（FinMind）
4. 更新文檔記錄解決方案


