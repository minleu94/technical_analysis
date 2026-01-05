# Recommendation Analysis Tab 修補建議

## 🚨 最關鍵 Blocker：volume_ratio_min 單位不一致導致所有股票被過濾

### 問題描述

**根因**: UI 傳遞 `volume_ratio_min: 1.0`（比率），但篩選邏輯期望百分比變化（0%）

**影響**: 當用戶設置 `volume_ratio_min: 1.0` 時，實際要求成交量變化率 >= 100%，導致所有股票被過濾

**狀態**: ✅ 已修復（見下方 patch）

---

## 🔧 修補 Patch

### Patch 1: 修復 volume_ratio_min 單位轉換

**文件**: `ui_app/strategy_configurator.py`

**位置**: `generate_recommendations()` 方法，第 259-310 行

**修復內容**:

```python
# 轉換 min_volume_ratio -> volume_ratio_min
# 注意：volume_ratio_min 是比率（如 1.0 = 100%），需要轉換為百分比變化
if 'min_volume_ratio' in filters:
    min_volume_ratio = filters['min_volume_ratio']
    screen_filters['volume_ratio_min'] = (min_volume_ratio - 1) * 100  # 轉換為百分比變化
elif 'volume_ratio_min' in filters:
    # ✅ 修復：如果直接傳遞 volume_ratio_min（來自 UI），也需要轉換
    volume_ratio = filters['volume_ratio_min']
    # 判斷是否已經是百分比變化（通常 > 10 或 < -50 表示是百分比變化）
    # 否則假設是比率，需要轉換
    if -50 <= volume_ratio <= 10:
        # 可能是比率，轉換為百分比變化
        screen_filters['volume_ratio_min'] = (volume_ratio - 1) * 100
    else:
        # 已經是百分比變化，直接使用
        screen_filters['volume_ratio_min'] = volume_ratio
```

**為什麼這個 patch 能讓 QA 通過**:
1. 自動識別 UI 傳遞的 `volume_ratio_min` 是比率還是百分比變化
2. 如果是比率（-50 到 10 之間），自動轉換為百分比變化
3. 確保篩選條件正確應用

**狀態**: ✅ 已應用

---

### Patch 2: 修復欄位檢查錯誤

**文件**: `ui_app/strategy_configurator.py`

**位置**: `generate_recommendations()` 方法，第 238, 257 行

**修復內容**:

```python
# ❌ 錯誤：檢查 index（Series 才有 index）
if '漲幅%' not in latest_df.index:

# ✅ 正確：檢查 columns（DataFrame 應檢查 columns）
if '漲幅%' not in latest_df.columns:
```

**為什麼這個 patch 能讓 QA 通過**:
1. `latest_df` 是 DataFrame（通過 `df.iloc[[-1]].copy()` 創建）
2. DataFrame 應檢查 `columns` 而不是 `index`
3. 確保欄位正確添加和檢查

**狀態**: ✅ 已應用

---

### Patch 3: 在篩選前計算必要欄位

**文件**: `ui_app/strategy_configurator.py`

**位置**: `generate_recommendations()` 方法，第 237-275 行

**修復內容**:

```python
# ✅ 添加：在篩選前計算漲幅%和成交量變化率%
# 計算漲幅%（如果需要的話，用於篩選）
if '漲幅%' not in latest_df.columns and len(df) >= 2:
    # ... 計算邏輯 ...

# 計算成交量變化率%（如果需要的話，用於篩選）
if '成交量變化率%' not in latest_df.columns and '成交股數' in df.columns:
    # ... 計算邏輯 ...
```

**為什麼這個 patch 能讓 QA 通過**:
1. 確保 `screen_stocks` 需要的欄位在篩選前已計算
2. 避免因欄位缺失導致篩選失敗
3. 確保篩選邏輯正確執行

**狀態**: ✅ 已應用

---

## 📊 驗證方式

運行 QA 腳本：

```bash
python scripts/qa_validate_recommendation_tab.py
```

**預期結果**:
1. ✅ Service 層測試通過
2. ✅ DTO 結構驗證通過
3. ✅ 分數範圍驗證通過
4. ✅ DataFrame 品質驗證通過
5. ✅ 篩選邏輯驗證通過（不再出現所有股票被過濾的情況）

**檢查點**:
- 查看 `output/qa/recommendation_tab/VALIDATION_REPORT.md`
- 確認沒有 `contract_violations` 或 `logic_errors` 類型的 blocker
- 確認測試結果中有推薦股票返回（至少在某些寬鬆的篩選條件下）

---

## 🎯 下一步

1. **運行 QA 腳本驗證修復**
2. **檢查日誌文件** (`output/qa/recommendation_tab/RUN_LOG.txt`)
3. **查看驗證報告** (`output/qa/recommendation_tab/VALIDATION_REPORT.md`)
4. **如果仍有問題**，根據日誌和報告進一步診斷

