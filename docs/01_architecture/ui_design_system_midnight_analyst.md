# Midnight Analyst UI 設計系統規格

> **狀態**：草案 v0.1（目前實作未被使用者接受為最終美術方向）
> **最後更新**：2026-06-16
> **權威範圍**：本文件定義 PySide6 UI 深色主題、設計 token、共用元件、效能限制與後續修改規則。

---

## 1. 文件定位

本文件是未來修改 UI 外觀時的參考規格。它不宣稱目前畫面已經美觀完成，而是把現有 Midnight Analyst 主題的設計決策、問題與可修改點集中記錄，避免未來 agent 只看程式碼猜測設計意圖。

相關程式入口：

| 類型 | 檔案 |
|---|---|
| Theme tokens | `ui_qt/theme/tokens.py` |
| 全域 QSS | `ui_qt/theme/qss.py` |
| Theme export | `ui_qt/theme/__init__.py` |
| 共用元件 | `ui_qt/widgets/theme_widgets.py` |
| 主程式套用點 | `ui_qt/main.py` 的 `apply_app_theme()` |
| 第一個樣板頁 | `ui_qt/views/decision_desk_view.py` |
| Theme 測試 | `tests/test_ui_qt_theme.py` |
| Daily Decision Desk UI 測試 | `tests/test_ui_qt_decision_desk_view.py` |

相關規劃文件：

- `docs/superpowers/plans/2026-06-16-midnight-analyst-ui-design-system.md`

---

## 2. 設計目標

Midnight Analyst 的原始目標是建立一套深色、專業、效能友善的投資決策工作台 UI 語言。

核心目標：

1. **深色為主**：降低長時間閱讀疲勞，讓資料、狀態與警示成為視覺焦點。
2. **資訊密度高但可掃描**：適合表格、排行、風險提示與研究結果。
3. **效能優先**：避免大量陰影、動畫、透明效果、漸層與 widget-per-cell。
4. **一致的狀態語言**：`OBSERVED`、`ESTIMATED`、`DEGRADED`、`MISSING` 必須用同一套 badge / 色彩規則呈現。
5. **先建立樣板再遷移**：Daily Decision Desk 是第一個 reference screen，其他工作區不得各自發明另一套主題。

目前使用者回饋：

- 目前實作仍「不好看」。
- 未來調整應優先改善視覺層級、空間比例、卡片使用方式與整體精緻度。
- 本文件應作為修改依據，不應把現有樣式視為完成品。

---

## 3. 色彩 Tokens

目前 tokens 定義於 `ui_qt/theme/tokens.py`。

| Token | 值 | 用途 |
|---|---:|---|
| `app_bg` | `#08111f` | App 主背景。 |
| `surface_1` | `#0f1b2d` | 主要面板、GroupBox、SectionPanel。 |
| `surface_2` | `#14233a` | 次級面板、輸入框、MetricCard。 |
| `surface_3` | `#1d2f4a` | Hover、選取、按鈕底色。 |
| `border` | `#263b59` | 邊框與分隔線。 |
| `text_primary` | `#e5edf7` | 主要文字。 |
| `text_secondary` | `#9fb0c7` | 輔助文字。 |
| `text_muted` | `#6f819a` | 低優先文字、disabled。 |
| `accent` | `#38bdf8` | 主重點色、active tab。 |
| `accent_hover` | `#0ea5e9` | Hover 重點色。 |
| `success` | `#22c55e` | 正常、觀測、偏多正向。 |
| `warning` | `#f59e0b` | 降級、警告、需注意。 |
| `danger` | `#ef4444` | 缺漏、失敗、風險。 |
| `info` | `#60a5fa` | 估算、資訊提示。 |

修改規則：

- 不要在 view 檔案直接新增任意 hex color；應先放入 `ThemeTokens`。
- 若需要新增語意色，命名要描述用途，例如 `risk_extreme`，不要用 `orange_2` 這類視覺名稱。
- 多空顏色不可反覆改定義；一旦有「正向 / 負向 / 風險」語意，須全 UI 一致。

---

## 4. 字體與密度

目前預設：

- 主字體：`Microsoft JhengHei UI`, `Segoe UI`, `Arial`
- 等寬字體：`Consolas`, `Cascadia Mono`, `monospace`
- 全域字級：10pt
- Badge 字級：9pt
- MetricCard 主值：15pt
- Section title：11pt
- 頁標題：目前 Daily Decision Desk 使用 17pt

建議調整方向：

- 若畫面仍顯得醜，優先調整字級層級與 spacing，不要先加特效。
- 頁標題、區塊標題、狀態 badge、主要數字必須有明顯層級。
- 表格 row height 應維持 26-30 px，避免大量資料頁變得過高。

---

## 5. 共用元件規格

共用元件定義於 `ui_qt/widgets/theme_widgets.py`。

### 5.1 StatusBadge

用途：

- 顯示品質、狀態、風險等短標籤。

目前 quality 對應：

| quality | 顏色 |
|---|---|
| `observed` | `success` |
| `estimated` | `info` |
| `degraded` | `warning` |
| `missing` | `danger` |
| unknown | `text_muted` |

規則：

- Badge 只顯示短詞，不放長句。
- 長說明放在旁邊的 label、tooltip 或 warning 區。

### 5.2 MetricCard

用途：

- 顯示少量摘要數字，例如決策日、生成時間、總警示數、持倉警示數。

規則：

- 不要把每個欄位都做成卡片。
- 卡片只用於第一眼掃描資訊。
- 不要在卡片內再放卡片。

### 5.3 SectionPanel

用途：

- 作為頁面主要區塊容器。

規則：

- 每個 panel 應有清楚標題。
- panel 內可以放表格、摘要列、warning list 或少量 cards。
- 不要用 `QGroupBox` 和 `SectionPanel` 混搭出兩套容器語言。

### 5.4 CompactCodeList

用途：

- 顯示股票代碼群組，例如強勢、弱勢、低流動性。

規則：

- 預設每組最多顯示 8 檔。
- 超過上限顯示「另 N 檔」。
- 完整清單應由底層 DTO / service 保留；UI 摘要不得改變計算結果。

### 5.5 WarningList

用途：

- 顯示品質降級、fallback、缺資料與風險提示。

規則：

- 警示應分行顯示，不應塞進單行長句。
- 若 warning 很多，後續應改為可收合或分組，而不是無限制拉高版面。

---

## 6. 全域 QSS 規格

全域 QSS 定義於 `ui_qt/theme/qss.py`，由 `build_global_stylesheet()` 產生，在 `ui_qt/main.py` 的 `apply_app_theme(app)` 套用。

目前覆蓋：

- `QWidget`
- `QMainWindow`
- `QDialog`
- `QTabWidget::pane`
- `QTabBar::tab`
- `QPushButton`
- `QGroupBox`
- `QTableView`
- `QHeaderView::section`
- `QTextEdit`
- `QLineEdit`
- `QComboBox`
- `QSpinBox`
- `QDoubleSpinBox`
- `QDateEdit`
- `QScrollArea`
- vertical `QScrollBar`

規則：

- 全域 QSS 只定義基礎語言，不應包含單一頁面的特殊 layout。
- 單一 view 若需要特殊樣式，優先新增共用 widget 或 helper，不要在 view 裡大量 inline stylesheet。
- 若某個既有 view 已有成熟樣式（例如 Smart Money Terminal），遷移時要保留其 domain 語意，再逐步對齊 token。

---

## 7. 效能限制

禁止或避免：

- 大量陰影。
- 動畫。
- 透明玻璃效果。
- 多層巢狀卡片。
- 在大型表格中每格塞 QWidget。
- 每次刷新都重建整個大型表格 widget。
- 用過多 icon / emoji 取代清楚文字，導致寬度失控。

允許：

- QSS 純色背景。
- 1px 邊框。
- 少量 badge。
- 少量摘要卡片。
- `QTableView` + model/view。
- 長清單摘要化或用 table 呈現。

---

## 8. Daily Decision Desk 目前實作狀態

目前 Daily Decision Desk 已使用：

- `SectionPanel`
- `MetricCard`
- `StatusBadge`
- `CompactCodeList`
- `WarningList`

目前仍有明顯問題：

1. 版面仍偏工程拼裝，缺少真正的視覺節奏。
2. 各 section 仍是垂直文字列，未形成好看的 dashboard grid。
3. `relative_strength_liquidity_value` 與 `relative_strength_codes` 有資訊重複。
4. 一些舊測試相容 label 仍保留，造成 view 內同時存在新舊呈現模式。
5. 卡片、badge、warning 的比例仍需設計審核。

後續改善方向：

- 把 Daily Decision Desk 拆為：
  1. 頂部 summary strip
  2. Market Intelligence grid
  3. Watchlist / Portfolio action panel
  4. Why Not / Warning panel
- 移除新舊重複文字。
- 把品質狀態統一放在 section header badge，不在每段文字重複「品質：」。
- 將強弱 / 流動性從純文字改為 compact table 或 chip row。

---

## 9. 後續 Agent 修改流程

未來 agent 若要修改 UI theme，請依序執行：

1. 閱讀本文件。
2. 閱讀 `ui_qt/theme/tokens.py`、`ui_qt/theme/qss.py`、`ui_qt/widgets/theme_widgets.py`。
3. 若修改 Daily Decision Desk，閱讀 `ui_qt/views/decision_desk_view.py` 與 `tests/test_ui_qt_decision_desk_view.py`。
4. 若新增或修改共用元件，先補 `tests/test_ui_qt_theme.py`。
5. 修改後至少執行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

如果只是改文件，不需要跑 UI gate；但如果文件描述了 UI 行為，仍需確認實作與文件一致。

---

## 10. 遷移順序建議

後續若要把整個 UI 統一，建議順序：

1. Daily Decision Desk：先完成 reference screen。
2. 數據更新：已有深色局部風格，但 inline QSS 很多，適合抽 token。
3. 市場觀察：統一表格、按鈕與狀態顯示。
4. 推薦分析：統一 Why / Why Not / Explain 區塊。
5. Research Lab：重點是高密度表單與結果頁。
6. 持倉管理：統一風險 badge、損益色彩、籌碼警示。
7. Runtime Observatory：可維持工程監控風格，但應使用相同 token。

每一步都應獨立驗收，不要一次改完所有工作區。

---

## 11. 修改範例

如果想讓整體更精緻，優先嘗試：

1. 降低 `app_bg` 的藍色飽和度。
2. 提高 `surface_1` 與 `surface_2` 對比。
3. 減少 border 的亮度。
4. 增加 section 內 spacing，但保持表格密度。
5. 把 `MetricCard` 字級從 15pt 調整到 13-14pt。

不要優先嘗試：

1. 加陰影。
2. 加漸層。
3. 大量加圓角。
4. 把所有內容卡片化。
5. 把表格改成大量 QLabel / QWidget 組成。

---

## 12. 更新記錄

- 2026-06-16：建立 Midnight Analyst UI 設計系統規格，記錄目前 theme token、共用元件、效能限制、已知問題與後續 agent 修改流程。
