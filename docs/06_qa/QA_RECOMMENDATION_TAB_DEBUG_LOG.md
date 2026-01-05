# Recommendation Analysis Tab Debug 日誌分析

## 🔍 根據日誌發現的問題

### 問題 1: 類型轉換錯誤（Blocker）

**日誌證據**:
```
2025-12-17 14:51:20,966 - DEBUG - generate_recommendations 處理異常: unsupported operand type(s) for -: 'str' and 'str'
```

**出現頻率**: 所有 50 支股票都出現此錯誤

**錯誤位置**: `ui_app/strategy_configurator.py:350-353`

**根本原因**:
```python
# ❌ 錯誤代碼
prev_price = df.iloc[-2].get(close_col, 0)  # 可能是字符串
curr_price = latest_df.get(close_col, 0)     # 返回 Series 或字符串
price_change = (curr_price - prev_price) / prev_price * 100  # 字符串減法！
```

**問題分析**:
1. `latest_df.get(close_col, 0)` 在 DataFrame 上使用 `get()` 可能返回 Series 或字符串
2. 如果 `close_col` 欄位是字符串類型（例如從 CSV 讀取時未轉換），`get()` 會返回字符串
3. 嘗試對兩個字符串進行減法運算導致 `TypeError`

**修復方案**:
```python
# ✅ 修復後代碼
prev_price = pd.to_numeric(df.iloc[-2].get(close_col, 0), errors='coerce')
curr_price = pd.to_numeric(latest_df.iloc[0].get(close_col, 0) if len(latest_df) > 0 else 0, errors='coerce')
# 處理 NaN
if pd.isna(prev_price):
    prev_price = 0
if pd.isna(curr_price):
    curr_price = 0
```

**修復位置**: `ui_app/strategy_configurator.py:349-358`

---

### 問題 2: 日期解析錯誤

**日誌證據**:
```
2025-12-17 14:41:54,302 - INFO - [RecommendationService] 數據讀取完成: 總筆數=500000, 股票數=924, 日期範圍=1970-01-01 00:00:00.020140407 ~ 1970-01-01 00:00:00.020160721
```

**問題**: 日期範圍顯示為 1970-01-01，這表示日期解析失敗（1970-01-01 是 Unix 時間戳 0）

**根本原因**: 
- CSV 文件中的日期可能是 YYYYMMDD 整數格式（如 20241217）
- `pd.to_datetime()` 無法自動識別此格式

**修復方案**: 添加多種日期格式支持（見 `app_module/recommendation_service.py:82-100`）

**狀態**: ✅ 已修復

---

## 📊 Debug 過程

### 步驟 1: 查看日誌文件
```bash
grep "generate_recommendations 處理異常" output/qa/recommendation_tab/RUN_LOG.txt
```

**發現**: 所有股票都出現相同的錯誤：`unsupported operand type(s) for -: 'str' and 'str'`

### 步驟 2: 定位錯誤位置
- 錯誤發生在 `generate_recommendations` 方法中
- 根據錯誤信息，是字符串減法運算
- 檢查代碼中所有減法運算的位置

### 步驟 3: 找到根因
- 在 `ui_app/strategy_configurator.py:350-353` 發現問題
- `latest_df.get(close_col, 0)` 返回的不是數值
- 需要確保類型轉換

### 步驟 4: 修復
- 使用 `pd.to_numeric()` 確保類型轉換
- 正確訪問 DataFrame 的值（使用 `iloc[0]`）
- 添加 NaN 處理

---

## ✅ 修復驗證

### 修復前
- 所有 50 支股票都拋出異常
- `generate_recommendations` 返回空 DataFrame
- 統計：成功=0, 無結果=50

### 修復後（預期）
- 不再出現類型轉換錯誤
- `generate_recommendations` 正常返回結果
- 至少部分股票能通過篩選

### 驗證方法
```bash
# 重新運行 QA 腳本
python scripts/qa_validate_recommendation_tab.py

# 檢查日誌中是否還有類型錯誤
grep "unsupported operand type" output/qa/recommendation_tab/RUN_LOG.txt
```

---

## 🎯 經驗教訓

1. **類型安全很重要**: 從 CSV 讀取的數據可能是字符串，需要明確轉換
2. **DataFrame.get() 的行為**: 在 DataFrame 上使用 `get()` 可能返回 Series，不是單個值
3. **DEBUG 日誌的價值**: 啟用 DEBUG 日誌級別能快速定位問題
4. **異常處理**: 即使有 try-except，也要記錄詳細的錯誤信息

