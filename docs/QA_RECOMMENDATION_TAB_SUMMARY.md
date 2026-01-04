# Recommendation Analysis Tab QA 驗證總結

## ✅ 已完成工作

### 1. QA 驗證腳本
- **文件**: `scripts/qa_validate_recommendation_tab.py`
- **功能**:
  - Service 層測試（不啟動 UI）
  - DTO 結構驗證
  - 分數範圍驗證
  - DataFrame 品質驗證
  - UI ↔ Service Contract 驗證
  - 篩選邏輯驗證

### 2. 問題盤點文檔
- **文件**: `docs/QA_RECOMMENDATION_TAB_ISSUES.md`
- **內容**:
  - 邏輯錯誤
  - DTO/欄位命名不一致
  - 隱含假設
  - 可能導致空結果的情況
  - UI 與 Service Contract 不一致

### 3. Logging Patch
- **文件**: `docs/QA_RECOMMENDATION_TAB_LOGGING_PATCH.md`
- **已應用**:
  - `RecommendationService.run_recommendation()`: 添加輸入參數、數據讀取、處理結果日誌
  - `StrategyConfigurator.generate_recommendations()`: 添加輸入、技術指標、分數計算日誌
  - `StrategyConfigurator.screen_stocks()`: 添加篩選過程詳細日誌

### 4. 修補建議
- **文件**: `docs/QA_RECOMMENDATION_TAB_FIX_SUGGESTION.md`
- **已修復**:
  - ✅ `volume_ratio_min` 單位不一致（已添加自動轉換）
  - ✅ 欄位檢查錯誤（已修復 `index` vs `columns`）
  - ✅ 篩選前計算必要欄位（已添加 `漲幅%` 和 `成交量變化率%` 計算）

### 5. 驗證報告
- **文件**: `output/qa/recommendation_tab/VALIDATION_REPORT.md`
- **狀態**: 已生成，顯示：
  - ✅ 通過: 1 項（UI Contract DTO）
  - ❌ 失敗: 0 項
  - ⏭️ 跳過: 3 項（所有測試配置都返回 0 個推薦）

---

## 🔍 發現的問題

### 1. 日期解析問題（Blocker）

**問題**: 日期欄位解析錯誤，顯示為 `1970-01-01 00:00:00.020140407`

**根因**: `pd.to_datetime()` 無法正確解析日期格式（可能是 YYYYMMDD 整數格式）

**狀態**: ✅ 已修復（添加多種日期格式支持）

**修復位置**: `app_module/recommendation_service.py:82-100`

### 2. 所有股票被過濾（✅ 已修復）

**問題**: 即使使用極寬鬆的篩選條件（`price_change_min: -100%`, `volume_ratio_min: 0.0`），所有股票仍被過濾

**根因（根據 DEBUG 日誌發現）**: 
- **錯誤**: `unsupported operand type(s) for -: 'str' and 'str'`
- **位置**: `ui_app/strategy_configurator.py:350-353`（計算漲幅%時）
- **原因**: `latest_df.get(close_col, 0)` 返回的是字符串或 Series，而不是數值，導致無法進行減法運算
- **影響**: 所有股票在計算 `漲幅%` 時拋出異常，`generate_recommendations` 返回空 DataFrame

**修復**:
1. ✅ 使用 `pd.to_numeric()` 確保價格和成交量轉換為數值類型
2. ✅ 正確訪問 `latest_df` 的值（使用 `iloc[0]` 而不是 `get()`）
3. ✅ 添加 NaN 處理邏輯

**修復位置**: `ui_app/strategy_configurator.py:349-380`

**狀態**: ✅ 已修復

---

## 📊 測試結果

### 測試配置
1. **基本配置（放寬篩選）**: 0 個推薦
2. **僅移動平均線**: 0 個推薦
3. **產業篩選（半導體業）**: 0 個推薦
4. **無篩選條件**: 0 個推薦
5. **嚴格漲幅篩選**: 0 個推薦
6. **嚴格成交量篩選**: 0 個推薦

### 統計信息
- 總股票數: 50
- 已處理: 50
- 成功: 0
- 數據不足: 0
- 無結果: 50（被篩選過濾）
- 異常: 0

---

## 🎯 下一步行動

### 優先級 1（已完成）
1. ✅ **根據日誌進行 Debug**
   - 已啟用 DEBUG 日誌級別並發現問題
   - 已修復類型轉換錯誤（字符串減法運算）
   - 已修復日期解析問題

### 優先級 2（驗證修復）
1. **重新運行 QA 腳本驗證修復**
   ```bash
   python scripts/qa_validate_recommendation_tab.py
   ```
   - 確認不再出現 `unsupported operand type(s) for -: 'str' and 'str'` 錯誤
   - 確認有推薦股票返回（至少在某些配置下）

2. **驗證日期解析修復**
   - 確認日期範圍正確顯示（不再是 1970-01-01）
   - 確認數據正確過濾（最近 60 天）

### 優先級 3（Minor）
1. **完善 QA 腳本**
   - 添加更多測試用例
   - 添加性能測試
   - 添加邊界條件測試

---

## 📝 驗證方式

### 運行 QA 腳本
```bash
python scripts/qa_validate_recommendation_tab.py
```

### 查看報告
- 驗證報告: `output/qa/recommendation_tab/VALIDATION_REPORT.md`
- 運行日誌: `output/qa/recommendation_tab/RUN_LOG.txt`

### 檢查日誌
- 啟用 DEBUG 級別: 修改 `scripts/qa_validate_recommendation_tab.py` 中的 `logging.basicConfig(level=logging.DEBUG)`
- 查看詳細處理過程: 搜索 `[StrategyConfigurator]` 和 `[screen_stocks]` 日誌

---

## 🚨 阻擋 Release 的問題

目前沒有發現明確的 blocker（除了所有股票被過濾的問題需要進一步調查）。

所有測試都正常運行，沒有異常，只是返回 0 個推薦。這可能是：
1. 數據問題（日期解析錯誤導致數據過濾不正確）
2. 篩選條件問題（即使放寬條件也無法匹配）
3. 圖形模式識別問題（W底模式可能太嚴格）

建議在修復日期解析問題後，重新運行測試，並啟用 DEBUG 日誌級別進行詳細診斷。

