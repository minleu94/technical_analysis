# 券商分點資料更新模組設計規格

## 一、Crawler.ipynb 分析

### 1.1 資料來源
- **網站**：MoneyDJ（https://5850web.moneydj.com）
- **頁面類型**：券商分點每日買賣資料頁面
- **URL 格式**：`https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=8450&b=0038003400350042&c=E&e={date}&f={date}`
- **抓取方式**：使用 Selenium + BeautifulSoup 解析 HTML 表格

### 1.2 抓取的資料內容
- **買超資料表**：表格索引 13
- **賣超資料表**：表格索引 14
- **原始欄位**：
  - `券商名稱`：格式為 `{代號}{名稱}`（例如：`1234元大證券`）
  - `買進金額`：數值（含千分位逗號）
  - `賣出金額`：數值（含千分位逗號）
  - `差額`：數值（含千分位逗號）

### 1.3 資料處理流程（Notebook 現況）
1. **爬取階段**：
   - 遍歷指定日期範圍（排除週末）
   - 檢查已存在檔案，跳過已處理日期
   - 使用 Selenium 抓取 HTML
   - 解析表格，提取買超/賣超資料
   - 保存為 `{YYYYMMDD}_buy_sell.csv`

2. **合併階段**：
   - 讀取所有 `*_buy_sell.csv` 檔案
   - 拆分券商名稱為 `證券代號` 和 `證券名稱`
   - 添加 `日期` 和 `交易類型`（買超/賣超）欄位
   - 合併到元數據檔案 `KY__buy_sell.csv`（⚠️ 此命名違反系統公約）

### 1.4 現有問題
1. **命名違規**：使用 `KY__buy_sell.csv` 作為元數據檔案名（應使用系統標準命名）
2. **主鍵不明確**：未建立 `system_key = {broker_code}_{branch_code}` 格式
3. **資料結構不完整**：缺少券商代號與分點代號的分離
4. **路徑硬編碼**：使用固定路徑 `D:\Min\Python\Project\FA_Data\KY__buy_sell`

---

## 二、券商分點資料更新模組接口規格

### 2.1 模組位置
- **檔案路徑**：`app_module/broker_branch_update_service.py`
- **類別名稱**：`BrokerBranchUpdateService`
- **依賴**：`data_module.config.TWStockConfig`

### 2.2 資料存儲結構

#### 2.2.1 目錄結構
```
{data_root}/
├── broker_branch/              # 券商分點資料目錄（新增）
│   ├── daily/                  # 每日原始資料
│   │   └── {YYYYMMDD}_broker_branch.csv
│   └── backup/                 # 備份目錄
└── meta_data/
    └── broker_branch_data.csv   # 整合元數據檔案（統一格式）
```

#### 2.2.2 資料檔案格式

**每日原始檔案**：`{YYYYMMDD}_broker_branch.csv`
```csv
日期,交易類型,broker_code,branch_code,broker_name_cn,買進金額,賣出金額,差額
2024-11-08,買超,1234,001,元大證券,1000000,500000,500000
2024-11-08,賣超,5678,002,凱基證券,300000,800000,-500000
```

**整合元數據檔案**：`broker_branch_data.csv`
```csv
日期,交易類型,system_key,broker_code,branch_code,broker_name_cn,買進金額,賣出金額,差額
2024-11-08,買超,1234_001,1234,001,元大證券,1000000,500000,500000
2024-11-08,賣超,5678_002,5678,002,凱基證券,300000,800000,-500000
```

**關鍵欄位說明**：
- `system_key`：`{broker_code}_{branch_code}`（主鍵，用於 join）
- `broker_code`：券商代號（數字或字母數字組合）
- `branch_code`：分點代號（通常為 3 位數字，如 001, 002）
- `broker_name_cn`：券商中文名稱（僅用於顯示）
- `交易類型`：`買超` 或 `賣超`
- `日期`：`YYYY-MM-DD` 格式

### 2.3 核心方法接口規格

#### 2.3.1 `update_broker_branch_data()`
**功能**：更新券商分點每日買賣資料

**輸入參數**：
```python
def update_broker_branch_data(
    self,
    start_date: str,           # 開始日期（YYYY-MM-DD）
    end_date: str,              # 結束日期（YYYY-MM-DD）
    delay_seconds: float = 4.0, # 請求間隔（秒）
    force_all: bool = False,    # 是否強制重新抓取（忽略已存在檔案）
    progress_callback: Optional[Callable[[str, int], None]] = None  # 進度回調
) -> Dict[str, Any]:
```

**輸出結果**：
```python
{
    'success': bool,                    # 是否成功
    'message': str,                     # 結果訊息
    'updated_dates': List[str],         # 成功更新的日期列表
    'failed_dates': List[str],          # 失敗的日期列表
    'skipped_dates': List[str],         # 跳過的日期列表（已存在）
    'total_processed': int,            # 總處理日期數
    'total_records': int                # 總記錄數（所有日期）
}
```

**錯誤情境**：
1. **網路錯誤**：請求超時、連線失敗
   - 處理：記錄錯誤，加入 `failed_dates`，繼續處理其他日期
   - Logging：`WARNING` 級別，記錄日期和錯誤訊息

2. **頁面解析錯誤**：表格結構變更、元素找不到
   - 處理：記錄錯誤，加入 `failed_dates`，繼續處理其他日期
   - Logging：`WARNING` 級別，記錄日期和解析錯誤詳情

3. **資料格式錯誤**：券商名稱無法拆分、數值轉換失敗
   - 處理：記錄警告，跳過該筆記錄，繼續處理其他記錄
   - Logging：`WARNING` 級別，記錄日期、券商名稱和錯誤詳情

4. **檔案系統錯誤**：目錄不存在、檔案寫入失敗
   - 處理：嘗試創建目錄，如果失敗則返回錯誤
   - Logging：`ERROR` 級別，記錄完整錯誤堆疊

**Logging 重點**：
- **INFO**：開始/結束更新、處理日期進度、成功更新日期
- **WARNING**：單一日期失敗、資料格式錯誤、跳過已存在檔案
- **ERROR**：系統級錯誤（檔案系統、配置錯誤）
- **DEBUG**：詳細的請求 URL、解析過程、資料轉換步驟

---

#### 2.3.2 `merge_broker_branch_data()`
**功能**：合併每日原始資料到整合元數據檔案

**輸入參數**：
```python
def merge_broker_branch_data(
    self,
    force_all: bool = False,    # 是否強制重新合併（忽略現有元數據）
    progress_callback: Optional[Callable[[str, int], None]] = None
) -> Dict[str, Any]:
```

**輸出結果**：
```python
{
    'success': bool,                    # 是否成功
    'message': str,                     # 結果訊息
    'merged_files': int,                # 合併的檔案數
    'new_records': int,                 # 新增記錄數
    'total_records': int,                # 總記錄數
    'date_range': {                     # 日期範圍
        'start_date': str,
        'end_date': str
    },
    'duplicate_records': int           # 去重後的記錄數
}
```

**處理邏輯**：
1. 讀取 `broker_branch/daily/` 目錄下所有 `*_broker_branch.csv` 檔案
2. 檢查元數據檔案中已存在的日期，跳過已處理日期（除非 `force_all=True`）
3. 驗證資料格式（必須包含 `system_key`、`broker_code`、`branch_code`）
4. 合併新舊資料，按日期和 `system_key` 排序
5. 去重（基於 `日期` + `system_key` + `交易類型`）
6. 備份現有元數據檔案（如果存在）
7. 保存整合資料到 `meta_data/broker_branch_data.csv`

**錯誤情境**：
1. **檔案讀取錯誤**：檔案損壞、編碼問題
   - 處理：記錄錯誤，跳過該檔案，繼續處理其他檔案
   - Logging：`WARNING` 級別

2. **資料驗證錯誤**：缺少必要欄位、`system_key` 格式錯誤
   - 處理：記錄警告，跳過該筆記錄或該檔案
   - Logging：`WARNING` 級別，記錄詳細錯誤

3. **合併錯誤**：資料類型不一致、記憶體不足
   - 處理：返回錯誤，保留現有元數據檔案
   - Logging：`ERROR` 級別

**Logging 重點**：
- **INFO**：開始/結束合併、處理檔案進度、合併統計
- **WARNING**：檔案讀取錯誤、資料驗證失敗
- **ERROR**：合併過程錯誤、檔案保存失敗

---

#### 2.3.3 `check_broker_branch_data_status()`
**功能**：檢查券商分點資料狀態

**輸入參數**：
```python
def check_broker_branch_data_status(self) -> Dict[str, Any]:
```

**輸出結果**：
```python
{
    'latest_date': Optional[str],       # 最新資料日期（YYYY-MM-DD）
    'total_records': int,               # 總記錄數
    'date_count': int,                 # 交易日數
    'broker_count': int,                # 券商數量（unique system_key）
    'date_range': {                     # 日期範圍
        'start_date': Optional[str],
        'end_date': Optional[str]
    },
    'status': str                       # 'ok' | 'empty' | 'error'
}
```

**Logging 重點**：
- **INFO**：檢查完成、資料統計
- **WARNING**：資料檔案不存在、資料為空

---

#### 2.3.4 `_parse_broker_name()`（私有方法）
**功能**：解析券商名稱為 `broker_code`、`branch_code`、`broker_name_cn`

**輸入參數**：
```python
def _parse_broker_name(
    self,
    broker_name: str  # 原始券商名稱（例如："1234元大證券" 或 "5678_002凱基證券"）
) -> Tuple[str, str, str]:
    # 返回：(broker_code, branch_code, broker_name_cn)
```

**處理邏輯**：
1. 使用正則表達式解析券商名稱
2. 提取券商代號（開頭的數字或字母數字組合）
3. 提取分點代號（如果存在，通常為 `_XXX` 格式）
4. 提取中文名稱（剩餘部分）
5. 如果無法解析，記錄警告並返回預設值

**錯誤情境**：
- 券商名稱格式不符合預期
- 處理：返回 `('UNKNOWN', '000', broker_name)`，記錄警告

---

#### 2.3.5 `_generate_system_key()`（私有方法）
**功能**：生成 `system_key = {broker_code}_{branch_code}`

**輸入參數**：
```python
def _generate_system_key(
    self,
    broker_code: str,
    branch_code: str
) -> str:
```

**處理邏輯**：
1. 標準化 `broker_code`（去除空白、轉大寫）
2. 標準化 `branch_code`（補零到 3 位數，例如：`1` → `001`）
3. 組合為 `{broker_code}_{branch_code}`

---

## 三、整合到 UpdateService

### 3.1 UpdateService 新增方法

```python
# 在 app_module/update_service.py 中新增

def update_broker_branch(
    self,
    start_date: str,
    end_date: str,
    delay_seconds: float = 4.0,
    force_all: bool = False
) -> Dict[str, Any]:
    """更新券商分點資料
    
    Args:
        start_date: 開始日期（YYYY-MM-DD）
        end_date: 結束日期（YYYY-MM-DD）
        delay_seconds: 請求間隔（秒）
        force_all: 是否強制重新抓取
        
    Returns:
        dict: 更新結果
    """
    # 實作：創建 BrokerBranchUpdateService 實例並調用 update_broker_branch_data()
    pass

def merge_broker_branch_data(
    self,
    force_all: bool = False
) -> Dict[str, Any]:
    """合併券商分點資料
    
    Args:
        force_all: 是否強制重新合併
        
    Returns:
        dict: 合併結果
    """
    # 實作：創建 BrokerBranchUpdateService 實例並調用 merge_broker_branch_data()
    pass
```

### 3.2 調用流程
1. **UpdateService.update_broker_branch()** 被調用
2. 創建 `BrokerBranchUpdateService` 實例（傳入 `config`）
3. 調用 `BrokerBranchUpdateService.update_broker_branch_data()`
4. 返回結果給 UI 層

---

## 四、整合到 UI（資料更新頁）

### 4.1 UI 新增功能

#### 4.1.1 更新類型選項
在「更新類型」RadioButton 組中新增：
- `self.broker_branch_radio = QRadioButton("券商分點資料")`

#### 4.1.2 更新配置
- 使用與其他更新類型相同的日期範圍配置
- 可選：添加「強制重新抓取」選項

#### 4.1.3 操作按鈕
- 「開始更新」按鈕：當選擇「券商分點資料」時，調用 `update_service.update_broker_branch()`
- 「合併券商分點資料」按鈕：調用 `update_service.merge_broker_branch_data()`

#### 4.1.4 資料狀態顯示
在「數據狀態」面板中新增區塊：
- **券商分點資料區塊**：顯示最新日期、總記錄數、狀態

### 4.2 UI 使用流程
1. 用戶選擇「券商分點資料」更新類型
2. 設定日期範圍（或使用預設）
3. 點擊「開始更新」
4. 系統顯示進度（使用 ProgressTaskWorker）
5. 更新完成後顯示結果
6. 可選：點擊「合併券商分點資料」合併每日資料

---

## 五、模組職責邊界

### 5.1 這個模組應該做的事 ✅

1. **資料抓取**：
   - 從 MoneyDJ 網站抓取券商分點每日買賣資料
   - 處理網路請求、頁面解析、資料提取

2. **資料標準化**：
   - 解析券商名稱為 `broker_code`、`branch_code`、`broker_name_cn`
   - 生成 `system_key = {broker_code}_{branch_code}`
   - 統一資料格式（日期格式、數值格式）

3. **資料存儲**：
   - 保存每日原始資料到 `broker_branch/daily/`
   - 合併資料到整合元數據檔案 `meta_data/broker_branch_data.csv`
   - 管理備份和版本控制

4. **資料驗證**：
   - 驗證必要欄位存在
   - 驗證 `system_key` 格式正確
   - 驗證數值欄位格式

5. **錯誤處理**：
   - 處理網路錯誤、解析錯誤、檔案錯誤
   - 記錄詳細日誌
   - 提供錯誤統計

6. **進度報告**：
   - 支持進度回調（用於 UI 顯示）
   - 報告處理進度和統計資訊

### 5.2 這個模組不應該做的事 ❌

1. **策略分析**：
   - ❌ 不應該計算券商分點買賣的「影響分數」
   - ❌ 不應該判斷「主力進出」
   - ❌ 不應該進行「分點追蹤」分析

2. **推薦邏輯**：
   - ❌ 不應該基於券商分點資料生成推薦
   - ❌ 不應該評分或排序券商分點

3. **資料關聯**：
   - ❌ 不應該與股票價格資料進行 join（這屬於上層分析模組）
   - ❌ 不應該計算「分點買賣與股價相關性」

4. **視覺化**：
   - ❌ 不應該生成圖表或報表（這屬於 UI 層）

5. **業務邏輯**：
   - ❌ 不應該判斷「哪些分點值得關注」
   - ❌ 不應該進行「分點行為模式分析」

**總結**：此模組是純粹的「資料管線」模組，只負責「抓取 → 標準化 → 存儲」，不涉及任何分析、策略或業務邏輯。

---

## 六、資料品質要求

### 6.1 必備欄位
- `日期`：必須為 `YYYY-MM-DD` 格式
- `system_key`：必須為 `{broker_code}_{branch_code}` 格式
- `broker_code`：必須存在且不為空
- `branch_code`：必須存在且為 3 位數字（補零）
- `交易類型`：必須為 `買超` 或 `賣超`
- `買進金額`、`賣出金額`、`差額`：必須為數值

### 6.2 資料完整性
- 每日資料應包含買超和賣超兩種類型
- 如果某日期沒有資料，應記錄為「無資料日期」，不應產生錯誤

### 6.3 資料一致性
- `system_key` 必須唯一（同一日期、同一 system_key、同一交易類型只能有一筆記錄）
- 合併時應去重（基於 `日期` + `system_key` + `交易類型`）

---

## 七、與現有系統的整合點

### 7.1 配置整合
- 使用 `TWStockConfig` 獲取資料路徑
- 新增 `broker_branch_dir` 和 `broker_branch_data_file` 屬性到 `TWStockConfig`

### 7.2 日誌整合
- 使用系統統一的 logging 機制
- 日誌檔案：`{log_dir}/broker_branch_update_{YYYYMMDD}.log`

### 7.3 錯誤處理整合
- 遵循系統統一的錯誤處理模式
- 返回結構化的結果字典

### 7.4 UI 整合
- 使用 `ProgressTaskWorker` 支持進度顯示
- 遵循現有 UI 更新流程的模式

---

## 八、實作優先順序建議

### Phase 1：核心功能
1. 實作 `_parse_broker_name()` 和 `_generate_system_key()`
2. 實作 `update_broker_branch_data()`（資料抓取）
3. 實作 `merge_broker_branch_data()`（資料合併）

### Phase 2：整合
1. 在 `UpdateService` 中新增方法
2. 在 `TWStockConfig` 中新增路徑配置
3. 在 UI 中新增更新選項

### Phase 3：優化
1. 添加重試機制
2. 優化並行處理（如果需要）
3. 添加資料驗證和修復機制

---

## 九、注意事項

1. **系統公約遵守**：
   - ✅ 必須使用 `system_key = {broker_code}_{branch_code}` 作為主鍵
   - ✅ 不得使用中文名稱或暱稱作為檔案名或 join key
   - ✅ 中文名稱僅用於顯示

2. **向後兼容**：
   - 如果現有資料使用舊格式，需要提供遷移腳本
   - 遷移時應將 `KY__buy_sell.csv` 轉換為新格式

3. **效能考量**：
   - 每日資料檔案應保持較小（只包含當日資料）
   - 整合元數據檔案可能較大，需要考慮讀寫效能
   - 建議使用增量合併，避免每次重新處理所有資料

4. **錯誤恢復**：
   - 單一日期失敗不應影響其他日期的處理
   - 合併失敗時應保留現有元數據檔案
   - 提供手動重試機制

---

**文件版本**：v1.0  
**建立日期**：2025-12-26  
**作者**：系統架構設計

