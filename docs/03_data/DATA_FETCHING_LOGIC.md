# 股票數據獲取邏輯說明

## 📖 快速導航

- **如何使用** → 查看 [使用方式](#使用方式) 章節
- **遇到錯誤** → 查看 [錯誤排查指南](#錯誤排查指南) 章節
- **邏輯詳情** → 查看 [獲取邏輯](#獲取邏輯update_20250828py) 章節
- **相關文檔** → 查看 [相關文檔](#相關文檔) 章節

## 概述

本文檔說明用於獲取股票數據的核心邏輯（基於成功更新 0828 數據的實現），以及如何將此邏輯整合到主模組中。

**重要提示：** 如果遇到 API 連接問題，請先查看 [錯誤排查指南](#錯誤排查指南)。

日常每日股價管線現在包含兩個市場來源：

- TWSE：`MI_INDEX type=ALL`，輸出到 `DATA_ROOT/daily_price/YYYYMMDD.csv`。
- TPEX：official afterTrading historical daily close quotes endpoint，輸出到 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`。

SQLite 同步階段會讀取上述兩個目錄，依 `(證券代號, 日期)` upsert 到 `daily_prices`。TPEX 日價是市場資料層，只補市場行情，不修改 `companies.csv`、fundamental tables、技術指標計算邏輯或推薦分數。

## 獲取邏輯（update_20250828.py）

### 1. API 端點和參數

**使用的 API：**
- **端點**: `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX`
- **API 名稱**: MI_INDEX API
- **參數**:
  ```python
  params = {
      'date': '20250828',  # YYYYMMDD 格式
      'type': 'ALL',       # 使用 ALL（不是 ALLBUT0999）
      'response': 'json'
  }
  ```

**關鍵點：**
- 使用 `type=ALL` 而不是 `type=ALLBUT0999`
- 使用 `requests.Session()` 維持 cookie（避免 307 重定向）
- 先訪問主頁獲取 cookie（模擬真實瀏覽器行為）
- 添加延遲時間（1.5-2.5 秒隨機延遲，避免請求過快被限制）
- 添加完整的請求頭（User-Agent, Referer 等）

### 2. 數據提取

```python
# 檢查響應狀態
if data.get('stat') != 'OK':
    return None

# 檢查是否有足夠的表格（至少9個）
if 'tables' not in data or len(data['tables']) < 9:
    return None

# 取得股票交易資料（第9個table，索引為8）
stock_data = data['tables'][8]

# 使用 data 和 fields 創建 DataFrame
df = pd.DataFrame(stock_data['data'], columns=stock_data['fields'])
```

**關鍵點：**
- 從 `data['tables'][8]` 取得數據（第9個表格）
- 使用 `stock_data['data']` 和 `stock_data['fields']` 直接創建 DataFrame

### 3. 數據處理

```python
# 只保留4位數股票代號
df = df[df['證券代號'].str.len() == 4]

# 處理數值欄位
numeric_columns = ['成交股數', '成交筆數', '成交金額', '開盤價', '最高價', 
                 '最低價', '收盤價', '漲跌價差', '最後揭示買價', 
                 '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']

for col in numeric_columns:
    if col in df.columns:
        # 移除逗號並轉換為數值
        df[col] = df[col].replace({'--': np.nan, '': np.nan})
        df[col] = df[col].apply(lambda x: str(x).replace(',', '') if pd.notnull(x) else x)
        df[col] = pd.to_numeric(df[col], errors='coerce')

# 處理漲跌符號（從 HTML 標籤中提取）
if '漲跌(+/-)' in df.columns:
    df['漲跌(+/-)'] = df['漲跌(+/-)'].apply(
        lambda x: '+' if 'color:red' in str(x) else 
                 '-' if 'color:green' in str(x) else ''
    )
```

**關鍵點：**
- 過濾只保留4位數股票代號
- 處理 '--' 和空值為 NaN
- 移除逗號並轉換為數值
- 從 HTML 標籤中提取漲跌符號（'color:red' 表示漲，'color:green' 表示跌）

### 4. 保存數據

```python
# 保存到 daily_price 目錄
daily_price_file = config.daily_price_dir / f'{formatted_date}.csv'
df.to_csv(daily_price_file, index=False, encoding='utf-8-sig')
```

**關鍵點：**
- 使用 `utf-8-sig` 編碼（支援 Excel 打開）
- 不包含索引

### 5. TPEX daily close quotes adapter

TPEX 日常來源由 `data_module/tpex_daily_price_source.py` 處理：

1. 呼叫 official afterTrading historical daily close quotes endpoint。
2. 指定更新日期或日期範圍，並把民國日期 / `YYYY-MM-DD` / `YYYYMMDD` 正規化成 `YYYYMMDD`。
3. 重用 `data_module/tpex_daily_price_backfill.py` 的 normalize 邏輯，只保留四碼普通股、有效正收盤價與日價欄位。
4. 跳過 ETF、債券、權證、停牌無價或無效代號 rows，並在結果 summary 中回報 skipped / diagnostics。
5. 輸出 `DATA_ROOT/daily_price_tpex/YYYYMMDD.csv`。

日常每日股價、快速更新、安全更新與背景補齊流程都會使用此 adapter 補缺少的 TPEX CSV，並由 SQLite sync 與 TWSE 一併 upsert 到 `daily_prices`。TPEX endpoint timeout 時應回報 warning，不應阻斷已成功的 TWSE 或其他同步步驟。

## 與舊邏輯的差異

### 舊邏輯（data_loader.py 的 download_from_api）

1. **API 參數：** 使用 `type=ALLBUT0999`（排除權證）
2. **數據提取：** 遍歷所有表格，尋找包含 '個股交易資訊' 的表格
3. **數據處理：** 手動構建字典列表，然後轉換為 DataFrame
4. **欄位名稱：** 使用不同的欄位名稱（如 '股票代號' vs '證券代號'）

### 目前邏輯（data_loader.py）

1. **API 參數：** 先使用 `type=ALL`；若 TWSE 回傳錯誤狀態、HTTP 307 或查無資料，fallback 到 `type=ALLBUT0999`。
2. **數據提取：** 不再硬編碼 `data['tables'][8]`，而是尋找同時包含 `證券代號` 與 `收盤價` 欄位的個股交易表。
3. **數據處理：** 使用 DataFrame 的 `data` 和 `fields` 直接創建，後續仍只保留四碼普通股並正規化數值欄位。
4. **失敗處理：** 每日股價 batch 若回報 failed dates，`UpdateService.update_daily()` 會回傳 `success=false`，避免快速 / 安全更新在個股日價缺漏時誤顯示完成。
5. **欄位名稱：** 保持原始欄位名稱（與 notebook 一致）。

## 更新到主模組

已將新邏輯更新到 `data_module/data_loader.py` 的 `download_from_api` 方法中：

- ✅ 使用 `type=ALL` 參數
- ✅ 直接從 `data['tables'][8]` 取得數據
- ✅ 使用 `stock_data['data']` 和 `stock_data['fields']` 創建 DataFrame
- ✅ 保持原始欄位名稱
- ✅ 處理數值欄位和漲跌符號

## 使用方式

### 方法 1：批量更新多日數據（最推薦 ⭐⭐⭐）

```bash
# 更新從指定日期之後到今天的所有交易日
python scripts/batch_update_daily_data.py --start-date 2025-08-28

# 更新指定日期範圍
python scripts/batch_update_daily_data.py --start-date 2025-08-28 --end-date 2025-09-05

# 自訂延遲時間（更安全）
python scripts/batch_update_daily_data.py --start-date 2025-08-28 --delay-min 4 --delay-max 4
```

**詳細說明**：請參考 [HOW_TO_UPDATE_DAILY_DATA.md](HOW_TO_UPDATE_DAILY_DATA.md)

### 方法 2：使用主模組腳本（推薦 ⭐⭐）

```bash
# 更新單日數據（只更新 daily_price）
python scripts/update_daily_stock_data.py --date 2025-08-29

# 更新並自動合併到 meta_data
python scripts/update_daily_stock_data.py --date 2025-08-29 --merge
```

### 方法 3：使用主模組（程式碼方式）

```python
from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader

config = TWStockConfig()
loader = DataLoader(config)

# 更新指定日期的數據
date = "2025-08-28"
df = loader.download_from_api(date)

if df is not None:
    print(f"成功獲取 {len(df)} 筆數據")
    print(f"數據已保存到: {config.daily_price_dir / '20250828.csv'}")
else:
    print("獲取數據失敗，請查看錯誤排查指南")
```

### 方法 4：使用目前 PySide6 UI

```powershell
# 啟動圖形化界面
.\.venv\Scripts\python.exe ui_qt\main.py
```

在 UI 中選擇「數據更新」，日常可使用快速更新；需要完整 CSV 備份時使用安全更新。快速更新與安全更新預設補結束日前最近 10 個工作日；個別資料來源可從左側導覽設定日期範圍與手動下載。

## 錯誤排查指南

### 🔴 常見錯誤及解決方案

#### 1. HTTP 307 重定向錯誤

**錯誤訊息：**
```
HTTP 307 Temporary Redirect
或
無法獲取數據: HTTP 307
```

**原因：**
- 證交所 API 加強了安全防護
- 需要更真實的瀏覽器行為

**解決方案：**

**方案 A：使用 UI 應用程式（推薦）**
- UI 應用程式已整合所有更新功能
- 自動處理延遲和錯誤

**方案 B：檢查 API 參數**
- 確認使用 `type=ALL`（不是 `ALLBUT0999`）
- 確認日期格式為 `YYYYMMDD`（如 `20250828`）

**方案 C：使用替代數據源**
- 安裝 FinMind：`pip install finmind`
- 使用 FinMind API 作為備用

#### 2. API 返回錯誤狀態

**錯誤訊息：**
```
API返回錯誤狀態: 查詢日期大於今日
或
API返回錯誤狀態: 查無資料
```

**解決方案：**
- 確認日期不超過今天
- 確認日期是交易日（非週末、非假日）
- 檢查日期格式是否正確

#### 3. 數據為空或格式錯誤

**錯誤訊息：**
```
API響應中沒有足夠的資料表
或
股票交易資料為空
```

**解決方案：**
- 確認 API 響應包含 `tables` 欄位
- 確認 `tables[8]` 存在（第9個表格）
- 檢查 `stock_data['data']` 和 `stock_data['fields']` 是否存在

#### 4. 欄位名稱不匹配

**錯誤訊息：**
```
KeyError: '證券代號'
或
欄位不存在
```

**解決方案：**
- 確認使用正確的 API 參數（`type=ALL`）
- 檢查 DataFrame 的欄位名稱
- 參考 [獲取邏輯](#獲取邏輯update_20250828py) 章節確認欄位名稱

### 🔍 調試步驟

1. **檢查 API 響應**
```python
import requests
url = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'
params = {'date': '20250828', 'type': 'ALL', 'response': 'json'}
response = requests.get(url, params=params)
print(f"狀態碼: {response.status_code}")
print(f"響應: {response.json()}")
```

2. **檢查數據結構**
```python
data = response.json()
print(f"tables 數量: {len(data.get('tables', []))}")
if len(data.get('tables', [])) >= 9:
    stock_data = data['tables'][8]
    print(f"欄位: {stock_data.get('fields', [])}")
    print(f"數據行數: {len(stock_data.get('data', []))}")
```

3. **檢查文件保存**
```python
from pathlib import Path
from data_module.config import TWStockConfig

config = TWStockConfig()
file_path = config.daily_price_dir / '20250828.csv'
print(f"文件是否存在: {file_path.exists()}")
if file_path.exists():
    import pandas as pd
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    print(f"數據行數: {len(df)}")
    print(f"欄位: {list(df.columns)}")
```

### 📞 需要更多幫助？

1. 查看 `TROUBLESHOOTING_DAILY_UPDATE.md` - 每日股票更新故障排除指南
2. 查看 `../00_core/PROJECT_SNAPSHOT.md` - 目前狀態、已知風險與優先事項
3. 查看 `../01_architecture/data_collection_architecture.md` - 數據收集架構說明

## 相關文檔

### 主要文檔
- **`TROUBLESHOOTING_DAILY_UPDATE.md`** - 每日股票更新故障排除指南（包含 API 連接問題解決方案）
- **`../00_core/PROJECT_SNAPSHOT.md`** - 目前狀態、已知風險與優先事項
- **`../01_architecture/data_collection_architecture.md`** - 數據收集架構說明

### 腳本文檔
- **`scripts/batch_update_daily_data.py`** - 批量更新腳本（推薦使用）
- **`scripts/update_daily_stock_data.py`** - 單日更新腳本（推薦使用）
- **`scripts/merge_daily_data.py`** - 數據合併腳本

### 模組文檔
- **`data_module/data_loader.py`** - 數據加載器（已更新為使用本文檔的邏輯）
- **`data_module/config.py`** - 配置管理

## 延遲時間和請求優化

### 為什麼需要延遲時間？

證交所 API 有防護機制，過快的請求可能會被限制或返回 307 重定向錯誤。

### 實現方式

1. **使用 Session 維持 cookie**
   ```python
   session = requests.Session()
   session.get("https://www.twse.com.tw/")  # 先訪問主頁獲取 cookie
   ```

2. **添加隨機延遲**
   ```python
   delay_time = random.uniform(1.5, 2.5)  # 1.5-2.5 秒隨機延遲
   time.sleep(delay_time)
   ```

3. **添加完整的請求頭**
   ```python
   headers = {
       'User-Agent': 'Mozilla/5.0 ...',
       'Referer': 'https://www.twse.com.tw/',
       'Accept': 'application/json, text/plain, */*',
       ...
   }
   ```

### 當前實現狀態

- ✅ `data_module/data_loader.py` 的 `download_from_api` - **已添加延遲和 Session**
- ✅ `scripts/batch_update_daily_data.py` - **已添加延遲和 Session**
- ✅ `scripts/update_daily_stock_data.py` - **已添加延遲和 Session**
- ✅ `ui_qt/main.py` - **目前主要 PySide6 UI**

## 注意事項

1. **API 穩定性：** 證交所 API 可能會變更，如果新邏輯失效，可以考慮：
   - 使用 UI 應用程式（已整合所有功能）
   - 使用主模組腳本（已包含錯誤處理）

2. **請求頻率：** 
   - 單次請求：已添加 1.5-2.5 秒延遲
   - 批量請求：建議在每次請求之間添加額外延遲（3-5 秒）

3. **數據完整性：** 某些股票可能因為停牌等原因缺少價格數據，這是正常現象

4. **編碼問題：** 確保使用 `utf-8-sig` 編碼以支援 Excel 打開

5. **日期格式：** 輸入日期格式為 `YYYY-MM-DD`，內部轉換為 `YYYYMMDD` 格式

6. **更新流程：** 
   - 先更新 `daily_price` 目錄中的單日文件
   - 然後使用 `merge_daily_data.py` 合併到 `meta_data` 目錄
   - 這兩個步驟是分開的，可以獨立執行

## MoneyDJ 券商分點 E/B 指標

- `c=E`：張數，寫入 `*_lots`。
- `c=B`：金額，單位仟元，寫入 `*_amount_k_twd`。
- E 與 B 是兩份獨立排序的買超/賣超 Top 50 榜單，兩榜顯示股票集合不必相同。
- 更新服務同日抓取兩個頁面，使用表頭辨認資料表，不依賴固定 table index。
- `GenLink2stk(...)` JavaScript 股票列也會解析，避免遺漏資料。
- 每筆保留 `trade_type`、`lots_observed`、`amount_observed`、`lots_rank` 與 `amount_rank`。
- E-only/B-only 的榜外欄位保存為 `NULL`，不可解讀為 0；舊檔缺少 rank 時，依各方向榜單淨值排序補回 1 至 50。
- SQLite `broker_flows` 唯一鍵包含 `trade_type`：`(分點名稱, 證券代號, 日期, trade_type)`。這是因為同一分點 / 股票 / 日期可能同時出現在買超榜與賣超榜；同步舊 DB 時會先備份再受控升級主鍵。

