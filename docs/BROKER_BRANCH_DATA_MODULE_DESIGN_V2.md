# 券商分點資料更新模組設計規格（修正版 v2.0）

## 一、設計修正摘要

### 1.1 核心概念修正 ✅

**原設計錯誤**：
- ❌ 誤將表格內的「券商名稱」當成可解析出 `branch_code`
- ❌ 誤將表格內的「券商名稱」當成「追蹤的分點」本身
- ❌ 未理解 URL 參數 `a` 和 `b` 才是分點的唯一識別

**修正後**：
- ✅ **追蹤對象**：是「分點」（branch），其唯一識別為 `branch_system_key = {a_code}_{branch_code}`
- ✅ **URL 參數**：`a` 是券商代碼（broker_code），`b` 是分點代碼（branch_code，可能需解碼）
- ✅ **表格內容**：表格內的「券商名稱」是「對手券商」（counterparty），不是追蹤的分點
- ✅ **資料來源**：`branch_code` 來自 registry 或 URL 參數 `b` 解碼結果，**不是從表格欄位 parse**

### 1.2 欄位命名修正 ✅

**原設計錯誤**：
- ❌ 使用「買進金額/賣出金額/差額」，但來源可能是數量而非金額

**修正後**：
- ✅ 使用中性命名：`buy_qty`、`sell_qty`、`net_qty`
- ✅ 保留 `交易類型`（買超/賣超），但明確說明：這只是表格分區，不是交易方向

### 1.3 目錄結構修正 ✅

**原設計錯誤**：
- ❌ 所有分點混在同一個 `daily/` 目錄，難以追蹤單一分點的資料完整性

**修正後**：
- ✅ 每個分點獨立目錄：`data/broker_flow/{branch_system_key}/daily/{YYYY-MM-DD}.csv`
- ✅ 每個分點獨立合併檔案：`data/broker_flow/{branch_system_key}/meta/merged.csv`
- ✅ 檔名使用 `YYYY-MM-DD` 格式（跨平台安全）

### 1.4 Merge 規則修正 ✅

**原設計錯誤**：
- ❌ 將所有分點合併成單一檔案，無法追蹤單一分點的資料完整性

**修正後**：
- ✅ Merge 是「同一分點」內的日資料合併
- ✅ 去重 key：`date + branch_system_key + trade_type + counterparty_broker_code`（如果有）
- ✅ 不同分點不應混在一起合併（除非另做總表）

---

## 二、修正版 CSV 欄位定義

### 2.1 每日原始檔案格式

**檔案路徑**：`data/broker_flow/{branch_system_key}/daily/{YYYY-MM-DD}.csv`

**欄位定義**：

| 欄位名 | 型別 | 說明 | 範例 |
|--------|------|------|------|
| `date` | str | 日期（YYYY-MM-DD） | `2024-11-08` |
| `trade_type` | str | 交易類型（買超/賣超） | `買超` |
| `branch_system_key` | str | 追蹤分點的主鍵（{a_code}_{branch_code}） | `9200_9268` |
| `branch_broker_code` | str | 追蹤分點的券商代碼（來自 URL 參數 a） | `9200` |
| `branch_code` | str | 追蹤分點的分點代碼（來自 registry 或 URL 參數 b 解碼） | `9268` |
| `branch_display_name` | str | 追蹤分點的顯示名稱（僅用於顯示） | `凱基台北` |
| `counterparty_broker_code` | str | 對手券商代碼（從表格「券商名稱」解析，可選） | `1234` |
| `counterparty_broker_name` | str | 對手券商名稱（從表格「券商名稱」解析，可選） | `元大證券` |
| `buy_qty` | float | 買進數量（中性命名，可能是金額或股數） | `1000000.0` |
| `sell_qty` | float | 賣出數量（中性命名，可能是金額或股數） | `500000.0` |
| `net_qty` | float | 淨數量（buy_qty - sell_qty） | `500000.0` |

**範例資料**：
```csv
date,trade_type,branch_system_key,branch_broker_code,branch_code,branch_display_name,counterparty_broker_code,counterparty_broker_name,buy_qty,sell_qty,net_qty
2024-11-08,買超,9200_9268,9200,9268,凱基台北,1234,元大證券,1000000.0,500000.0,500000.0
2024-11-08,賣超,9200_9268,9200,9268,凱基台北,5678,富邦證券,300000.0,800000.0,-500000.0
```

### 2.2 合併元數據檔案格式

**檔案路徑**：`data/broker_flow/{branch_system_key}/meta/merged.csv`（或 `merged.parquet`）

**欄位定義**：與每日原始檔案相同（見 2.1）

**說明**：
- 此檔案是「同一分點」的歷史資料合併
- 按 `date` 排序
- 去重 key：`date + trade_type + counterparty_broker_code`（如果存在）

### 2.3 總表檔案格式（可選）

**檔案路徑**：`data/broker_flow/all_branches_summary.csv`（可選，用於跨分點查詢）

**欄位定義**：與每日原始檔案相同，但包含所有追蹤分點的資料

**說明**：
- 此檔案是「所有分點」的總表（用於跨分點分析）
- 可選功能，不強制實作

---

## 三、修正版目錄結構

```
{data_root}/
└── broker_flow/                          # 券商分點資料根目錄
    ├── 9A00_9A9P/                        # 永豐竹北分點
    │   ├── daily/                        # 每日原始資料
    │   │   ├── 2024-11-08.csv
    │   │   ├── 2024-11-11.csv
    │   │   └── ...
    │   ├── meta/                         # 元數據
    │   │   └── merged.csv                # 合併後的歷史資料
    │   └── backup/                       # 備份目錄（可選）
    ├── 9200_9268/                        # 凱基台北分點
    │   ├── daily/
    │   │   ├── 2024-11-08.csv
    │   │   └── ...
    │   └── meta/
    │       └── merged.csv
    ├── 9200_9216/                        # 凱基信義分點
    │   ├── daily/
    │   └── meta/
    ├── 9200_9217/                        # 凱基松山分點
    │   ├── daily/
    │   └── meta/
    ├── 9100_9131/                        # 群益民權分點
    │   ├── daily/
    │   └── meta/
    ├── 8450_845B/                        # 康和永和分點
    │   ├── daily/
    │   └── meta/
    └── all_branches_summary.csv          # 總表（可選）
```

**關鍵設計原則**：
- ✅ 每個 `branch_system_key` 一個獨立目錄
- ✅ 檔名使用 `YYYY-MM-DD.csv` 格式（跨平台安全，無中文、無空白）
- ✅ 每日檔案只包含當日資料
- ✅ 合併檔案只包含該分點的歷史資料

---

## 四、需要更新/刪除的舊設計段落

### 4.1 需要刪除的錯誤段落

#### ❌ 段落 1：2.2.2 資料檔案格式（第 62-76 行）
**錯誤原因**：
- 誤將表格內的「券商名稱」當成追蹤分點
- 欄位命名使用「買進金額/賣出金額」，應改為 `buy_qty/sell_qty`
- 未包含 `branch_system_key`、`branch_broker_code`、`branch_code` 等追蹤分點資訊
- 未區分「追蹤分點」和「對手券商」

**應替換為**：見「二、修正版 CSV 欄位定義」

---

#### ❌ 段落 2：2.2.1 目錄結構（第 49-60 行）
**錯誤原因**：
- 所有分點混在同一個 `daily/` 目錄
- 無法追蹤單一分點的資料完整性
- 檔名格式 `{YYYYMMDD}_broker_branch.csv` 不符合跨平台要求

**應替換為**：見「三、修正版目錄結構」

---

#### ❌ 段落 3：2.3.4 `_parse_broker_name()`（第 227-249 行）
**錯誤原因**：
- 誤解了資料結構：表格內的「券商名稱」是「對手券商」，不是「追蹤分點」
- 不應該從表格欄位 parse 出 `branch_code`
- `branch_code` 應該來自 registry 或 URL 參數 `b` 解碼

**應替換為**：
- 新增 `_get_branch_info_from_registry()`：從 registry 獲取分點資訊
- 新增 `_parse_counterparty_broker_name()`：解析表格內的「對手券商」名稱

---

#### ❌ 段落 4：2.3.5 `_generate_system_key()`（第 252-268 行）
**錯誤原因**：
- 命名不準確：應為 `branch_system_key`，不是 `system_key`
- 標準化邏輯不適用：`branch_code` 可能包含字母（如 `9A9P`、`845B`），不應補零

**應替換為**：
```python
def _generate_branch_system_key(
    self,
    broker_code: str,      # 來自 URL 參數 a（例如：9A00, 9200）
    branch_code: str       # 來自 registry 或 URL 參數 b 解碼（例如：9A9P, 9268）
) -> str:
    """生成 branch_system_key = {broker_code}_{branch_code}"""
    # 標準化：去除空白、轉大寫
    # 不補零（因為 branch_code 可能包含字母）
    return f"{broker_code.upper().strip()}_{branch_code.upper().strip()}"
```

---

#### ❌ 段落 5：2.3.2 `merge_broker_branch_data()` 處理邏輯（第 169-176 行）
**錯誤原因**：
- 誤將所有分點合併成單一檔案
- 去重 key 不完整（缺少 `counterparty_broker_code`）

**應替換為**：
```python
# 處理邏輯（修正版）：
# 1. 遍歷所有追蹤分點（從 registry 讀取 branch_system_key 列表）
# 2. 對每個分點：
#    a. 讀取該分點的 daily/ 目錄下所有 CSV 檔案
#    b. 檢查該分點的 meta/merged.csv 中已存在的日期，跳過已處理日期（除非 force_all=True）
#    c. 驗證資料格式（必須包含 branch_system_key、branch_broker_code、branch_code）
#    d. 合併新舊資料，按 date 排序
#    e. 去重（基於 date + trade_type + counterparty_broker_code）
#    f. 備份現有合併檔案（如果存在）
#    g. 保存到該分點的 meta/merged.csv
# 3. 可選：生成總表 all_branches_summary.csv（包含所有分點）
```

---

#### ❌ 段落 6：5.1 模組職責 - 資料標準化（第 361-364 行）
**錯誤原因**：
- 誤解了資料標準化的對象

**應替換為**：
```markdown
2. **資料標準化**：
   - 從 registry 獲取追蹤分點資訊（branch_system_key、branch_broker_code、branch_code、branch_display_name）
   - 解析表格內的「對手券商」名稱為 counterparty_broker_code 和 counterparty_broker_name
   - 統一資料格式（日期格式、數值格式）
   - 生成 branch_system_key = {broker_code}_{branch_code}
```

---

#### ❌ 段落 7：6.1 必備欄位（第 413-419 行）
**錯誤原因**：
- 欄位命名錯誤（買進金額/賣出金額）
- 缺少追蹤分點相關欄位

**應替換為**：
```markdown
### 6.1 必備欄位
- `date`：必須為 `YYYY-MM-DD` 格式
- `branch_system_key`：必須為 `{broker_code}_{branch_code}` 格式（例如：`9200_9268`）
- `branch_broker_code`：必須存在且不為空（來自 URL 參數 a）
- `branch_code`：必須存在且不為空（來自 registry 或 URL 參數 b 解碼）
- `trade_type`：必須為 `買超` 或 `賣超`
- `buy_qty`、`sell_qty`、`net_qty`：必須為數值
```

---

### 4.2 需要更新的段落

#### ⚠️ 段落 1：2.3.1 `update_broker_branch_data()` 輸入參數（第 92-100 行）
**需要更新**：
- 新增參數：`branch_system_keys: Optional[List[str]] = None`（如果為 None，則更新所有追蹤分點）

**修正後**：
```python
def update_broker_branch_data(
    self,
    start_date: str,                      # 開始日期（YYYY-MM-DD）
    end_date: str,                         # 結束日期（YYYY-MM-DD）
    branch_system_keys: Optional[List[str]] = None,  # 要更新的分點列表（None=全部）
    delay_seconds: float = 4.0,            # 請求間隔（秒）
    force_all: bool = False,               # 是否強制重新抓取
    progress_callback: Optional[Callable[[str, int], None]] = None
) -> Dict[str, Any]:
```

---

#### ⚠️ 段落 2：2.3.1 輸出結果（第 103-113 行）
**需要更新**：
- 新增：`updated_branches: List[str]`（成功更新的分點列表）
- 新增：`failed_branches: List[str]`（失敗的分點列表）

**修正後**：
```python
{
    'success': bool,                       # 是否成功
    'message': str,                        # 結果訊息
    'updated_dates': List[str],           # 成功更新的日期列表（跨所有分點）
    'failed_dates': List[str],            # 失敗的日期列表
    'skipped_dates': List[str],           # 跳過的日期列表
    'updated_branches': List[str],        # 成功更新的分點列表（branch_system_key）
    'failed_branches': List[str],         # 失敗的分點列表
    'total_processed': int,               # 總處理日期數
    'total_records': int                  # 總記錄數
}
```

---

#### ⚠️ 段落 3：2.3.2 `merge_broker_branch_data()` 輸出結果（第 153-166 行）
**需要更新**：
- 新增：`merged_branches: List[str]`（成功合併的分點列表）

**修正後**：
```python
{
    'success': bool,                       # 是否成功
    'message': str,                       # 結果訊息
    'merged_branches': List[str],         # 成功合併的分點列表（branch_system_key）
    'merged_files': int,                  # 合併的檔案數（跨所有分點）
    'new_records': int,                   # 新增記錄數（跨所有分點）
    'total_records': int,                 # 總記錄數（跨所有分點）
    'date_range': {                       # 日期範圍（跨所有分點）
        'start_date': str,
        'end_date': str
    },
    'duplicate_records': int              # 去重後的記錄數
}
```

---

#### ⚠️ 段落 4：7.1 配置整合（第 433-435 行）
**需要更新**：
- 新增：`broker_flow_dir` 屬性
- 新增：`broker_branch_registry_file` 屬性（分點 registry 檔案）

**修正後**：
```markdown
### 7.1 配置整合
- 使用 `TWStockConfig` 獲取資料路徑
- 新增 `broker_flow_dir` 屬性到 `TWStockConfig`（指向 `{data_root}/broker_flow/`）
- 新增 `broker_branch_registry_file` 屬性（指向 `{meta_data_dir}/broker_branch_registry.csv`）
```

---

## 五、新增設計需求

### 5.1 分點 Registry 設計

**檔案路徑**：`{meta_data_dir}/broker_branch_registry.csv`

**欄位定義**：

| 欄位名 | 型別 | 說明 | 範例 |
|--------|------|------|------|
| `branch_system_key` | str | 分點主鍵（{broker_code}_{branch_code}） | `9200_9268` |
| `branch_broker_code` | str | 券商代碼（URL 參數 a） | `9200` |
| `branch_code` | str | 分點代碼（URL 參數 b 解碼後） | `9268` |
| `branch_display_name` | str | 顯示名稱（僅用於顯示） | `凱基台北` |
| `url_param_a` | str | URL 參數 a（原始值） | `9200` |
| `url_param_b` | str | URL 參數 b（原始值，可能是 UTF-16 編碼） | `0038003400350042` |
| `is_active` | bool | 是否啟用追蹤 | `True` |
| `created_at` | str | 建立時間 | `2024-11-08T10:00:00` |
| `updated_at` | str | 更新時間 | `2024-11-08T10:00:00` |

**範例資料**：
```csv
branch_system_key,branch_broker_code,branch_code,branch_display_name,url_param_a,url_param_b,is_active,created_at,updated_at
9A00_9A9P,9A00,9A9P,永豐竹北,9A00,0038003400350042,True,2024-11-08T10:00:00,2024-11-08T10:00:00
9200_9268,9200,9268,凱基台北,9200,9268,True,2024-11-08T10:00:00,2024-11-08T10:00:00
9200_9216,9200,9216,凱基信義,9200,9216,True,2024-11-08T10:00:00,2024-11-08T10:00:00
9200_9217,9200,9217,凱基松山,9200,9217,True,2024-11-08T10:00:00,2024-11-08T10:00:00
9100_9131,9100,9131,群益民權,9100,9131,True,2024-11-08T10:00:00,2024-11-08T10:00:00
8450_845B,8450,845B,康和永和,8450,0038003400350042,True,2024-11-08T10:00:00,2024-11-08T10:00:00
```

**說明**：
- Registry 用於管理「追蹤的分點清單」
- `branch_code` 是解碼後的結果（避免在爬蟲模組中耦合解碼邏輯）
- `url_param_b` 保留原始值（用於構建 URL）

---

### 5.2 新增方法：`_load_branch_registry()`

**功能**：從 registry 載入追蹤分點清單

**輸入參數**：
```python
def _load_branch_registry(
    self,
    active_only: bool = True  # 是否只載入啟用的分點
) -> List[Dict[str, Any]]:
```

**輸出結果**：
```python
[
    {
        'branch_system_key': '9200_9268',
        'branch_broker_code': '9200',
        'branch_code': '9268',
        'branch_display_name': '凱基台北',
        'url_param_a': '9200',
        'url_param_b': '9268',
        'is_active': True
    },
    ...
]
```

---

### 5.3 新增方法：`_parse_counterparty_broker_name()`

**功能**：解析表格內的「對手券商」名稱

**輸入參數**：
```python
def _parse_counterparty_broker_name(
    self,
    counterparty_name: str  # 表格內的「券商名稱」（例如："1234元大證券"）
) -> Tuple[str, str]:
    # 返回：(counterparty_broker_code, counterparty_broker_name)
```

**處理邏輯**：
1. 使用正則表達式解析對手券商名稱
2. 提取券商代號（開頭的數字或字母數字組合）
3. 提取中文名稱（剩餘部分）
4. 如果無法解析，返回 `('UNKNOWN', counterparty_name)`，記錄警告

**說明**：
- 此方法用於解析「對手券商」，不是「追蹤分點」
- 對手券商資訊是可選的（用於未來研究分析）

---

## 六、URL 構建邏輯

### 6.1 URL 格式

**基礎 URL**：`https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm`

**參數**：
- `a`：券商代碼（broker_code），例如：`9A00`、`9200`、`9100`、`8450`
- `b`：分點代碼（branch_code），可能是：
  - 直接代碼：`9268`、`9216`、`9131`
  - UTF-16 編碼：`0038003400350042`（需要解碼為 `9A9P` 或 `845B`）
- `c`：固定值 `E`
- `e`：開始日期（YYYY-MM-DD）
- `f`：結束日期（YYYY-MM-DD）

**完整 URL 範例**：
```
https://5850web.moneydj.com/z/zg/zgb/zgb0.djhtm?a=9200&b=9268&c=E&e=2024-11-08&f=2024-11-08
```

### 6.2 URL 構建方法

**方法簽名**：
```python
def _build_branch_url(
    self,
    branch_info: Dict[str, Any],  # 從 registry 載入的分點資訊
    start_date: str,              # 開始日期（YYYY-MM-DD）
    end_date: str                  # 結束日期（YYYY-MM-DD）
) -> str:
    """構建分點資料 URL"""
    # 使用 branch_info['url_param_a'] 和 branch_info['url_param_b']
    # 構建完整 URL
```

---

## 七、資料流程修正

### 7.1 更新流程（修正版）

1. **載入分點 Registry**：
   - 從 `broker_branch_registry.csv` 載入追蹤分點清單
   - 如果指定了 `branch_system_keys`，只處理指定的分點

2. **對每個分點**：
   - 構建 URL（使用 registry 中的 `url_param_a` 和 `url_param_b`）
   - 遍歷日期範圍（排除週末）
   - 檢查該分點的 `daily/{YYYY-MM-DD}.csv` 是否已存在
   - 使用 Selenium 抓取 HTML
   - 解析表格（買超/賣超）
   - 對每筆記錄：
     - 添加追蹤分點資訊（`branch_system_key`、`branch_broker_code`、`branch_code`、`branch_display_name`）
     - 解析對手券商資訊（`counterparty_broker_code`、`counterparty_broker_name`）
     - 標準化數值欄位（`buy_qty`、`sell_qty`、`net_qty`）
   - 保存到該分點的 `daily/{YYYY-MM-DD}.csv`

3. **錯誤處理**：
   - 單一分點失敗不影響其他分點
   - 單一日期失敗不影響其他日期
   - 記錄詳細錯誤資訊

### 7.2 合併流程（修正版）

1. **載入分點 Registry**：
   - 從 `broker_branch_registry.csv` 載入追蹤分點清單

2. **對每個分點**：
   - 讀取該分點的 `daily/` 目錄下所有 CSV 檔案
   - 檢查該分點的 `meta/merged.csv` 中已存在的日期
   - 跳過已處理日期（除非 `force_all=True`）
   - 驗證資料格式
   - 合併新舊資料，按 `date` 排序
   - 去重（基於 `date + trade_type + counterparty_broker_code`）
   - 備份現有合併檔案
   - 保存到該分點的 `meta/merged.csv`

3. **可選：生成總表**：
   - 合併所有分點的資料到 `all_branches_summary.csv`

---

## 八、錯誤情境修正

### 8.1 資料格式錯誤（修正版）

**原設計錯誤**：
- 誤將「券商名稱無法拆分」當成錯誤

**修正後**：
- **對手券商名稱無法解析**：
  - 處理：記錄警告，使用 `('UNKNOWN', counterparty_name)`，繼續處理其他記錄
  - Logging：`WARNING` 級別，記錄日期、對手券商名稱和錯誤詳情

- **追蹤分點資訊缺失**：
  - 處理：這是嚴重錯誤，應跳過該筆記錄或該日期
  - Logging：`ERROR` 級別，記錄完整錯誤

---

## 九、與現有系統的整合點（修正版）

### 9.1 配置整合（修正版）

- 使用 `TWStockConfig` 獲取資料路徑
- 新增 `broker_flow_dir` 屬性到 `TWStockConfig`（指向 `{data_root}/broker_flow/`）
- 新增 `broker_branch_registry_file` 屬性（指向 `{meta_data_dir}/broker_branch_registry.csv`）

### 9.2 日誌整合

- 使用系統統一的 logging 機制
- 日誌檔案：`{log_dir}/broker_branch_update_{YYYYMMDD}.log`
- 日誌應包含 `branch_system_key` 資訊，方便追蹤單一分點的處理狀態

---

## 十、實作優先順序建議（修正版）

### Phase 1：核心功能
1. 實作分點 Registry 管理（讀取、驗證）
2. 實作 `_build_branch_url()` 和 `_parse_counterparty_broker_name()`
3. 實作 `update_broker_branch_data()`（資料抓取，支援多分點）
4. 實作 `merge_broker_branch_data()`（資料合併，每個分點獨立）

### Phase 2：整合
1. 在 `UpdateService` 中新增方法
2. 在 `TWStockConfig` 中新增路徑配置
3. 在 UI 中新增更新選項

### Phase 3：優化
1. 添加重試機制
2. 優化並行處理（如果需要）
3. 添加資料驗證和修復機制
4. 可選：生成總表功能

---

## 十一、注意事項（修正版）

1. **系統公約遵守**：
   - ✅ 必須使用 `branch_system_key = {broker_code}_{branch_code}` 作為主鍵
   - ✅ `branch_code` 來自 registry 或 URL 參數 `b` 解碼，**不是從表格欄位 parse**
   - ✅ 表格內的「券商名稱」是「對手券商」，不是「追蹤分點」
   - ✅ 不得使用中文名稱或暱稱作為檔案名或 join key
   - ✅ 中文名稱僅用於顯示

2. **資料隔離**：
   - ✅ 每個分點獨立目錄，便於追蹤單一分點的資料完整性
   - ✅ 每個分點獨立合併檔案，避免資料混雜

3. **向後兼容**：
   - 如果現有資料使用舊格式（`KY__buy_sell.csv`），需要提供遷移腳本
   - 遷移時應：
     - 識別追蹤的分點（需要手動建立 registry）
     - 將資料拆分到各分點目錄
     - 轉換欄位命名（買進金額 → buy_qty）

4. **效能考量**：
   - 每日資料檔案應保持較小（只包含當日資料）
   - 合併檔案只包含該分點的歷史資料，避免檔案過大
   - 建議使用增量合併，避免每次重新處理所有資料

5. **錯誤恢復**：
   - 單一分點失敗不應影響其他分點
   - 單一日期失敗不應影響其他日期
   - 合併失敗時應保留現有合併檔案
   - 提供手動重試機制

---

**文件版本**：v2.0（修正版）  
**建立日期**：2025-12-26  
**修正日期**：2025-12-26  
**作者**：系統架構設計

