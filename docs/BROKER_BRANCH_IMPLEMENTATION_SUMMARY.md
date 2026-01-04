# 券商分點資料更新功能實作總結

## 變更清單

### 新增檔案

1. **`app_module/broker_branch_update_service.py`**
   - 新增 `BrokerBranchUpdateService` 類別
   - 實作券商分點資料抓取、合併、狀態檢查功能
   - 使用共用的 Selenium driver（避免重複創建 Chrome 實例）

2. **`{meta_data_dir}/broker_branch_registry.csv`**
   - 分點 registry 檔案
   - 包含 6 個追蹤分點的完整資訊

### 修改檔案

1. **`data_module/config.py`**
   - 新增 `broker_flow_dir` 屬性（指向 `{data_root}/broker_flow/`）
   - 新增 `broker_branch_registry_file` 屬性（指向 `{meta_data_dir}/broker_branch_registry.csv`）

2. **`app_module/update_service.py`**
   - 新增 `update_broker_branch()` 方法
   - 新增 `merge_broker_branch_data()` 方法
   - 新增 `check_broker_branch_data_status()` 方法
   - 修改 `check_data_status()` 方法，加入券商分點資料狀態檢查
   - 新增 `List` 類型導入

3. **`ui_qt/views/update_view.py`**
   - 新增「券商分點資料」更新類型選項
   - 新增「券商分點數據」狀態顯示區塊
   - 新增「合併券商分點資料」按鈕
   - 實作 `_execute_merge_broker_branch()` 方法
   - 實作 `_on_merge_broker_branch_finished()` 方法
   - 實作 `_on_merge_broker_branch_error()` 方法

---

## 本地測試方式

### 方式一：使用 Python 腳本測試

建立測試腳本 `test_broker_branch.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-

from data_module.config import TWStockConfig
from app_module.broker_branch_update_service import BrokerBranchUpdateService
from datetime import datetime, timedelta

# 初始化配置
config = TWStockConfig()

# 創建服務
service = BrokerBranchUpdateService(config)

# 測試 1：更新最近 3 天的資料
print("=== 測試 1：更新最近 3 天資料 ===")
end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')

result = service.update_broker_branch_data(
    start_date=start_date,
    end_date=end_date,
    delay_seconds=4.0,
    force_all=False
)

print(f"更新結果: {result['success']}")
print(f"訊息: {result['message']}")
print(f"成功更新的分點: {result['updated_branches']}")
print(f"失敗的分點: {result['failed_branches']}")
print(f"成功更新的日期: {len(result['updated_dates'])} 個")
print(f"總記錄數: {result['total_records']}")

# 測試 2：合併資料
print("\n=== 測試 2：合併資料 ===")
merge_result = service.merge_broker_branch_data(
    force_all=False
)

print(f"合併結果: {merge_result['success']}")
print(f"訊息: {merge_result['message']}")
print(f"成功合併的分點: {merge_result['merged_branches']}")
print(f"新增記錄數: {merge_result['new_records']}")
print(f"總記錄數: {merge_result['total_records']}")

# 測試 3：檢查狀態
print("\n=== 測試 3：檢查狀態 ===")
status = service.check_broker_branch_data_status()
print(f"狀態: {status['status']}")
print(f"最新日期: {status['latest_date']}")
print(f"總記錄數: {status['total_records']}")
print(f"交易日數: {status['date_count']}")
print(f"分點數量: {status['broker_count']}")
```

執行方式：
```bash
python test_broker_branch.py
```

### 方式二：使用 UpdateService 測試

```python
from data_module.config import TWStockConfig
from app_module.update_service import UpdateService
from datetime import datetime, timedelta

config = TWStockConfig()
update_service = UpdateService(config)

# 更新券商分點資料
end_date = datetime.now().strftime('%Y-%m-%d')
start_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')

result = update_service.update_broker_branch(
    start_date=start_date,
    end_date=end_date
)

print(result)

# 合併資料
merge_result = update_service.merge_broker_branch_data()
print(merge_result)

# 檢查狀態
status = update_service.check_broker_branch_data_status()
print(status)
```

### 方式三：使用 UI 測試

1. 啟動應用程式
2. 切換到「數據更新」Tab
3. 選擇「券商分點資料」更新類型
4. 設定日期範圍（例如：最近 3 天）
5. 點擊「開始更新」
6. 等待更新完成
7. 點擊「合併券商分點資料」按鈕
8. 點擊「檢查數據狀態」查看結果

---

## 驗收標準檢查

### ✅ 1. 執行 update_broker_branch_data 對任意日期區間（含 1~3 天）能產生 6 個分點的 daily 檔案

**檢查方式**：
```bash
# 檢查目錄結構
ls -R {data_root}/broker_flow/

# 應該看到：
# broker_flow/
# ├── 9A00_9A9P/daily/YYYY-MM-DD.csv
# ├── 9200_9268/daily/YYYY-MM-DD.csv
# ├── 9200_9216/daily/YYYY-MM-DD.csv
# ├── 9200_9217/daily/YYYY-MM-DD.csv
# ├── 9100_9131/daily/YYYY-MM-DD.csv
# └── 8450_845B/daily/YYYY-MM-DD.csv
```

### ✅ 2. 每個分點的 daily 檔案包含 branch_system_key 欄位且與分點一致

**檢查方式**：
```python
import pandas as pd
from data_module.config import TWStockConfig

config = TWStockConfig()
branch_key = '9200_9268'  # 凱基台北
daily_file = config.broker_flow_dir / branch_key / 'daily' / '2024-11-08.csv'

if daily_file.exists():
    df = pd.read_csv(daily_file)
    print(df.columns)
    print(df[['branch_system_key', 'branch_broker_code', 'branch_code']].head())
    # 應該看到 branch_system_key 都是 9200_9268
```

### ✅ 3. merge_broker_branch_data 後每個分點都有 meta/merged.csv，且不混分點資料

**檢查方式**：
```python
import pandas as pd
from data_module.config import TWStockConfig

config = TWStockConfig()

# 檢查每個分點的 merged.csv
for branch_key in ['9A00_9A9P', '9200_9268', '9200_9216', '9200_9217', '9100_9131', '8450_845B']:
    merged_file = config.broker_flow_dir / branch_key / 'meta' / 'merged.csv'
    if merged_file.exists():
        df = pd.read_csv(merged_file)
        # 確認所有記錄的 branch_system_key 都一致
        unique_keys = df['branch_system_key'].unique()
        print(f"{branch_key}: {unique_keys}")
        assert len(unique_keys) == 1 and unique_keys[0] == branch_key, f"分點資料混雜: {branch_key}"
```

### ✅ 4. logging 會印出：分點、日期、成功/失敗/跳過統計

**檢查方式**：
```bash
# 查看日誌檔案
tail -f {log_dir}/broker_branch_update_*.log

# 應該看到類似：
# INFO: 開始更新 6 個分點的資料: 2024-11-08 至 2024-11-10
# INFO: 處理分點 凱基台北 (1/6)...
# INFO: 處理 凱基台北 - 2024-11-08 (1/18)...
# INFO: 成功更新: 9200_9268/2024-11-08, 記錄數: 50
# INFO: 更新完成：成功 6 個分點，失敗 0 個分點；成功 3 個日期，失敗 0 個日期，跳過 0 個日期；總記錄數: 300
```

### ✅ 5. 不允許出現 KY__buy_sell 這種舊命名作為新輸出

**檢查方式**：
```bash
# 確認沒有舊命名檔案
find {data_root}/broker_flow -name "*KY*" -o -name "*buy_sell*"
# 應該沒有輸出

# 確認新命名格式
find {data_root}/broker_flow -name "*.csv" | head -5
# 應該看到：YYYY-MM-DD.csv 格式
```

---

## 資料結構驗證

### Registry 檔案格式

**檔案位置**：`{meta_data_dir}/broker_branch_registry.csv`

**預期內容**：
```csv
branch_system_key,branch_broker_code,branch_code,branch_display_name,url_param_a,url_param_b,is_active,created_at,updated_at
9A00_9A9P,9A00,9A9P,永豐竹北,9A00,0039004100390050,True,2025-12-27T00:00:29,2025-12-27T00:00:29
9200_9268,9200,9268,凱基台北,9200,9268,True,2025-12-27T00:00:29,2025-12-27T00:00:29
9200_9216,9200,9216,凱基信義,9200,9216,True,2025-12-27T00:00:29,2025-12-27T00:00:29
9200_9217,9200,9217,凱基松山,9200,9217,True,2025-12-27T00:00:29,2025-12-27T00:00:29
9100_9131,9100,9131,群益民權,9100,9131,True,2025-12-27T00:00:29,2025-12-27T00:00:29
8450_845B,8450,845B,康和永和,8450,0038003400350042,True,2025-12-27T00:00:29,2025-12-27T00:00:29
```

### 每日檔案格式

**檔案位置**：`{data_root}/broker_flow/{branch_system_key}/daily/{YYYY-MM-DD}.csv`

**預期欄位**：
- `date` (str): 日期（YYYY-MM-DD）
- `trade_type` (str): 交易類型（買超/賣超）
- `branch_system_key` (str): 分點主鍵（例如：9200_9268）
- `branch_broker_code` (str): 券商代碼（例如：9200）
- `branch_code` (str): 分點代碼（例如：9268）
- `branch_display_name` (str): 顯示名稱（例如：凱基台北）
- `counterparty_broker_code` (str): 對手券商代碼
- `counterparty_broker_name` (str): 對手券商名稱
- `buy_qty` (int/float): 買進數量
- `sell_qty` (int/float): 賣出數量
- `net_qty` (int/float): 淨數量

---

## 注意事項

1. **Selenium Driver 共用**：
   - 整個更新流程共用一個 Chrome driver
   - 任務結束時會自動關閉 driver
   - 如果中途發生錯誤，driver 也會被清理

2. **錯誤處理**：
   - 單一分點失敗不影響其他分點
   - 單一日期失敗不影響其他日期
   - 所有錯誤都會記錄到日誌

3. **資料完整性**：
   - 每個分點獨立目錄，不會混雜
   - 去重 key：`date + trade_type + counterparty_broker_code`
   - 合併時會備份現有檔案

4. **效能考量**：
   - 預設請求間隔 4 秒（可調整）
   - 支援進度回調（用於 UI 顯示）
   - 增量更新：跳過已存在的檔案

---

## 已知限制

1. **Selenium 依賴**：
   - 需要安裝 Chrome 瀏覽器
   - 需要安裝 `selenium` 和 `webdriver-manager`（可選）
   - 如果沒有 `webdriver-manager`，需要手動管理 ChromeDriver

2. **網路依賴**：
   - 需要能訪問 MoneyDJ 網站
   - 如果網站結構變更，可能需要調整表格索引

3. **資料格式**：
   - 假設表格索引 13 是買超資料，索引 14 是賣超資料
   - 如果網站結構變更，需要調整解析邏輯

---

## 修復記錄

### 2025-12-29：URL 參數與日期範圍修復

**問題**：
1. URL 參數 `c` 使用錯誤值（`E` 而非 `B`）
2. 日期範圍邏輯錯誤（`e=當天&f=當天` 而非 `e=前一天&f=當天`）
3. Registry 檔案 `url_param_b` 前導零丟失
4. ChromeDriver 崩潰時無法自動恢復
5. `datetime` 導入錯誤（函數內重複導入）

**修復內容**：
1. ✅ URL 參數 `c`：從 `E` 改為 `B`
2. ✅ 日期範圍：從 `e=date&f=date` 改為 `e=prev_date&f=date`（前一天到當天）
3. ✅ Registry 自動修復：修復 `url_param_b` 前導零問題（讀取時強制為字串類型）
4. ✅ Selenium 穩定性：改進超時處理、錯誤檢測、driver 重建機制
5. ✅ `datetime` 導入：移除函數內重複導入

**測試結果**（2025-12-29）：
- ✅ 所有 6 個分點都成功下載
- ✅ 每個分點都有 100 筆記錄
- ✅ 總記錄數：600 筆
- ✅ URL 格式正確：`c=B&e=2025-12-21&f=2025-12-22`
- ✅ 無失敗分點或日期

**相關文檔**：
- 測試與故障排除指南：`docs/BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md`

---

**實作完成日期**：2025-12-27  
**最後修復日期**：2025-12-29  
**版本**：v1.1

