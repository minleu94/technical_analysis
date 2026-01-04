# Recommendation Analysis Tab 問題盤點

## 1️⃣ 邏輯錯誤（Machine-checkable）

### 1.1 篩選邏輯問題

**問題**: `volume_ratio_min` 單位不一致
- **位置**: `ui_app/strategy_configurator.py:259-310`
- **描述**: UI 傳遞的是比率（1.0 = 100%），但 `screen_stocks` 期望百分比變化（0%）
- **影響**: 當 `volume_ratio_min: 1.0` 時，實際要求成交量變化率 >= 100%，過於嚴格
- **狀態**: ✅ 已修復（添加自動轉換邏輯）

**問題**: 篩選時欄位檢查錯誤
- **位置**: `ui_app/strategy_configurator.py:238, 257`
- **描述**: 檢查 `latest_df.index` 而不是 `latest_df.columns`（DataFrame 應檢查 columns）
- **影響**: 可能導致 `漲幅%` 和 `成交量變化率%` 欄位未正確添加
- **狀態**: ✅ 已修復

### 1.2 數據計算問題

**問題**: `漲幅%` 和 `成交量變化率%` 在篩選前未計算
- **位置**: `ui_app/strategy_configurator.py:generate_recommendations()`
- **描述**: `screen_stocks` 需要這些欄位，但在 `generate_recommendations` 中未計算
- **影響**: 篩選可能失敗或跳過
- **狀態**: ✅ 已修復（在篩選前計算這些欄位）

### 1.3 異常處理問題

**問題**: 所有股票都拋出異常時，沒有詳細的錯誤信息
- **位置**: `app_module/recommendation_service.py:273`
- **描述**: 異常被吞掉，只記錄 `continue`，沒有日誌
- **影響**: 難以診斷問題
- **狀態**: ✅ 已修復（添加詳細異常日誌）

---

## 2️⃣ 不一致的 DTO / 欄位命名

### 2.1 DTO 欄位命名

**問題**: DTO 屬性名與 `to_dict()` 輸出欄位名不一致
- **位置**: `app_module/dtos.py:RecommendationDTO`
- **描述**: 
  - DTO 屬性: `price_change` (英文)
  - `to_dict()` 輸出: `漲幅%` (中文)
- **影響**: UI 必須使用 `to_dict()` 的輸出，不能直接訪問屬性
- **狀態**: ⚠️ 設計選擇（需要文檔說明）

### 2.2 UI 期望欄位

**問題**: UI 期望的欄位與 DTO 輸出不完全一致
- **位置**: `ui_qt/views/recommendation_view.py:526`
- **描述**: UI 使用 `rec.to_dict()` 轉換為 DataFrame，期望欄位：
  - `證券代號`, `證券名稱`, `收盤價`, `漲幅%`, `總分`, `指標分`, `圖形分`, `成交量分`, `推薦理由`, `產業`, `Regime匹配`
- **狀態**: ✅ 一致（DTO.to_dict() 提供所有必要欄位）

---

## 3️⃣ 隱含假設

### 3.1 DataFrame 結構假設

**問題**: 假設 DataFrame 有 `日期` 欄位且可排序
- **位置**: `ui_app/strategy_configurator.py:217`
- **描述**: `df.sort_values('日期')` 可能失敗如果欄位不存在
- **影響**: 可能導致異常
- **狀態**: ⚠️ 有檢查但可能不夠嚴格

**問題**: 假設 DataFrame 至少有 20 筆數據
- **位置**: `app_module/recommendation_service.py:156`
- **描述**: 如果數據不足 20 筆，直接跳過
- **影響**: 新上市股票無法分析
- **狀態**: ✅ 有檢查（跳過並記錄）

### 3.2 欄位存在假設

**問題**: 假設價格欄位存在（`收盤價`, `Close`, `close`）
- **位置**: `ui_app/strategy_configurator.py:240`
- **描述**: 如果所有價格欄位都不存在，會設置 `漲幅% = 0.0`
- **影響**: 可能導致錯誤的篩選結果
- **狀態**: ⚠️ 有處理但可能不夠明顯

**問題**: 假設成交量欄位存在（`成交股數`）
- **位置**: `ui_app/strategy_configurator.py:257`
- **描述**: 如果欄位不存在，會設置 `成交量變化率% = 0.0`
- **影響**: 可能導致錯誤的篩選結果
- **狀態**: ⚠️ 有處理但可能不夠明顯

---

## 4️⃣ 可能導致空結果 / NaN / 全 0 分數的情況

### 4.1 空結果情況

1. **篩選條件太嚴格**
   - `volume_ratio_min: 1.0` → 要求成交量變化率 >= 0%
   - 如果所有股票當天成交量都低於 20 日均量，會被全部過濾
   - **狀態**: ✅ 已添加診斷日誌

2. **產業篩選無匹配**
   - 如果選擇的產業在數據中沒有股票
   - **狀態**: ✅ 有錯誤提示

3. **技術指標計算失敗**
   - 如果數據格式不正確或缺少必要欄位
   - **狀態**: ⚠️ 有異常處理但可能不夠詳細

### 4.2 NaN 情況

1. **技術指標計算產生 NaN**
   - RSI、MACD 等指標在數據不足時會產生 NaN
   - **狀態**: ⚠️ 需要檢查 NaN 處理邏輯

2. **分數計算產生 NaN**
   - 如果指標分數為 NaN，總分也會是 NaN
   - **狀態**: ⚠️ 需要檢查 NaN 處理邏輯

### 4.3 全 0 分數情況

1. **圖形模式未識別**
   - 如果沒有找到任何圖形模式，`pattern_score` 可能為 0
   - **狀態**: ✅ 正常行為

2. **技術指標未啟用**
   - 如果所有技術指標都未啟用，`indicator_score` 可能為 0
   - **狀態**: ✅ 正常行為

---

## 5️⃣ UI 與 Service Contract 不一致

### 5.1 配置參數不一致

**問題**: UI 預設配置與 Service 預設配置可能不一致
- **位置**: 
  - UI: `ui_qt/views/recommendation_view.py:_get_default_config()`
  - Service: `app_module/recommendation_service.py` (無預設配置)
- **描述**: UI 有自己的預設配置，但 Service 不提供預設
- **影響**: 可能導致行為不一致
- **狀態**: ⚠️ 需要驗證

### 5.2 篩選參數名稱不一致

**問題**: UI 使用 `volume_ratio_min`，但 Service 可能期望 `min_volume_ratio`
- **位置**: 
  - UI: `ui_qt/views/recommendation_view.py:415`
  - Service: `ui_app/strategy_configurator.py:254-310`
- **描述**: 有轉換邏輯，但可能不夠清晰
- **影響**: 可能導致篩選不正確
- **狀態**: ✅ 已修復（添加轉換邏輯）

---

## 6️⃣ 其他問題

### 6.1 日誌不足

**問題**: 關鍵步驟缺少日誌
- **位置**: 多處
- **描述**: 
  - Service 入口缺少輸入參數日誌
  - 中間結果缺少統計信息
  - 回傳摘要缺少詳細信息
- **影響**: 難以診斷問題
- **狀態**: ⚠️ 需要添加（見 logging patch）

### 6.2 錯誤處理不完整

**問題**: 部分異常被吞掉
- **位置**: `ui_app/strategy_configurator.py:configure_technical_indicators()`
- **描述**: 技術指標計算失敗時只記錄 debug 日誌，不中斷流程
- **影響**: 可能導致部分指標缺失但繼續執行
- **狀態**: ⚠️ 設計選擇（需要評估）

---

## 問題分類

### ✅ 可全自動驗證（QA script 可 cover）

- DTO 結構驗證
- 分數範圍驗證
- DataFrame 品質驗證
- 篩選邏輯驗證
- 欄位存在性驗證

### ⚠️ 需啟動 Qt 但可自動化（pytest-qt / QTest）

- UI 組件初始化
- 信號/槽連接
- 表格模型設置
- 配置收集邏輯

### 👀 必須人工檢查（純視覺/UX）

- UI 布局
- 按鈕樣式
- 進度條動畫
- 錯誤訊息顯示格式

