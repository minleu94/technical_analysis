# Midnight Analyst UI 設計系統規格

> **狀態**：Month 4 v1 functional closure accepted；2026-07-02 完成第一輪全 UI 低風險視覺 polish
> **最後更新**：2026-07-02
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
| 表格樣式 helper | `ui_qt/widgets/table_style.py` |
| 文字 / icon 清理 helper | `ui_qt/widgets/text_sanitizer.py` |
| 主程式套用點 | `ui_qt/main.py` 的 `apply_app_theme()` |
| 樣板頁 | `ui_qt/views/decision_desk_view.py`、`ui_qt/views/portfolio_view.py` |
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
5. **用樣板逐步遷移**：Daily Decision Desk 是第一個 reference screen；2026-07-02 後，持倉管理、推薦分析、回測、Watchlist、資料更新與市場觀察相關表格也已開始共用同一套 token / table helper / button variant。

目前使用者回饋：

- 目前實作已足以支撐 Month 4 service-backed daily workflow 收尾。
- 2026-07-02 已完成第一輪低風險視覺整理：修缺字 icon、統一設計 token、表格樣式、按鈕 variant、空狀態，並優先整理每日決策與持倉管理兩個門面頁。
- 後續調整應繼續改善視覺層級、空間比例與整體精緻度，但不得為了美化改動資料抓取、SQLite 同步、推薦、回測、每日決策 snapshot 或持倉計算語意。

---

## 3. 色彩 Tokens

目前 tokens 定義於 `ui_qt/theme/tokens.py`。

| Token | 值 | 用途 |
|---|---:|---|
| `app_bg` | `#070b12` | App 主背景；降低藍色飽和度，讓長時間閱讀更安定。 |
| `surface_1` | `#101722` | 主要面板、GroupBox、SectionPanel。 |
| `surface_2` | `#182231` | 次級面板、輸入框、MetricCard。 |
| `surface_3` | `#223047` | Hover、選取、按鈕底色。 |
| `border` | `#2a3548` | 邊框與分隔線；比 v1 更收斂，降低框線感。 |
| `text_primary` | `#eef3f8` | 主要文字。 |
| `text_secondary` | `#a8b3c2` | 輔助文字。 |
| `text_muted` | `#788496` | 低優先文字、disabled。 |
| `accent` | `#4fb7e5` | 主重點色、active tab。 |
| `accent_hover` | `#75cdf5` | Hover / focus 重點色。 |
| `accent_warm` | `#f0b35a` | 溫和提示、次要重點與需要被注意但非危險的狀態。 |
| `success` | `#22c55e` | 正常、觀測、偏多正向。 |
| `warning` | `#f6b44b` | 降級、警告、需注意。 |
| `danger` | `#f05b5b` | 缺漏、失敗、風險。 |
| `info` | `#77aef5` | 估算、資訊提示。 |
| `data_positive` | `#00e093` | 表格中的正向數值、獲利、偏多資料。 |
| `data_negative` | `#ff5f6d` | 表格中的負向數值、虧損、偏空資料。 |
| `data_neutral` | `#cbd5e1` | 中性數值與一般資料。 |
| `table_hover` | `#1d2a3d` | 表格 hover 列。 |
| `table_selected` | `#243a5c` | 表格選取列。 |
| `border_subtle` | `#1d2635` | 更低干擾的表格格線與次要分隔線。 |

修改規則：

- 不要在 view 檔案直接新增任意 hex color；應先放入 `ThemeTokens`。
- 若需要新增語意色，命名要描述用途，例如 `risk_extreme`，不要用 `orange_2` 這類視覺名稱。
- 多空顏色不可反覆改定義；一旦有「正向 / 負向 / 風險」語意，須全 UI 一致。
- 表格內的獲利 / 虧損 / 中性數值優先使用 `data_positive`、`data_negative`、`data_neutral`，不要在各 view 內另訂一組綠紅灰。

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

### 5.6 EmptyStatePanel

用途：

- 顯示尚無資料、尚未選取項目、尚未載入或目前結果為空的狀態。

規則：

- 空狀態應說明目前狀態與下一個合理動作，但不要塞入操作教學長文。
- 空狀態只屬於呈現層，不得因此自動觸發資料抓取、推薦、回測或持倉動作。
- 大面積空白區優先使用 `EmptyStatePanel`，避免畫面看起來像未載入完成或壞掉。

### 5.7 Financial Table Helper

`apply_financial_table_style(table)` 定義於 `ui_qt/widgets/table_style.py`。

用途：

- 統一金融資料表格的列高、選取行為、交錯列、header 對齊、文字省略與 scroll 行為。

規則：

- 新增或整理 `QTableView` 時，除非該表格有明確 domain 特殊視覺需求，應優先套用此 helper。
- 不要在每個 view 內重複設定 row height、alternating rows、selection behavior、header 尺寸與 elide mode。
- 表格仍應維持 model/view；不要為了美化改成每格 QWidget。

### 5.8 Text Sanitizer

`ui_qt/widgets/text_sanitizer.py` 提供 `strip_leading_symbol_icon()`、`remove_symbol_icons()` 與 `sanitize_button_texts()`。

用途：

- 清理舊版 emoji / symbol icon 造成的缺字、寬度失控或跨平台顯示不一致。

規則：

- 主流程按鈕、danger action、tab label、context menu action 應使用清楚文字與 button variant，不依賴 emoji 表達語意。
- 若既有資料文字仍含 emoji / symbol，顯示前可在 UI 邊界清理；不要改寫底層 DTO、snapshot 或歷史保存資料。

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
- `QTableCornerButton`
- `QHeaderView::section`
- `QTextEdit`
- `QLineEdit`
- `QComboBox`
- `QSpinBox`
- `QDoubleSpinBox`
- `QDateEdit`
- `QScrollArea`
- vertical `QScrollBar`
- horizontal `QScrollBar`
- `QProgressBar`
- `QToolTip`
- `QFrame#midnightEmptyState`

2026-06-18 polish 補強：

- `QLabel` 預設透明背景，降低深色頁面內文字塊的割裂感。
- Button / Tab / Input 補上 hover、pressed 與 focus 狀態。
- Table item 增加一致 padding，header 稍微提高可讀性。
- ComboBox popup、ProgressBar 與 ScrollBar hover 納入全域語言。

2026-07-02 polish 補強：

- `QPushButton[variant="primary"]`、`danger`、`ghost` 納入全域語言，用屬性表達操作層級，避免各 view 重複 inline stylesheet。
- 表格 hover / selected / corner button / horizontal scrollbar 納入同一套金融資料表格語言。
- `QToolTip` 與 `QFrame#midnightEmptyState` 納入全域 QSS，使提示與空狀態在各工作區一致。
- 主視窗建立完成後會呼叫 `sanitize_button_texts(self)`，清理舊版缺字 icon 類按鈕文字。

規則：

- 全域 QSS 只定義基礎語言，不應包含單一頁面的特殊 layout。
- 單一 view 若需要特殊樣式，優先新增共用 widget 或 helper，不要在 view 裡大量 inline stylesheet。
- 若某個既有 view 已有成熟樣式（例如 Smart Money Terminal），遷移時要保留其 domain 語意，再逐步對齊 token。
- 若只是表達操作重要性，優先設定 button `variant` property；不要為每顆按鈕新增自訂 stylesheet。

---

## 7. 效能限制

禁止或避免：

- 大量陰影。
- 動畫。
- 透明玻璃效果。
- 多層巢狀卡片。
- 在大型表格中每格塞 QWidget。
- 每次刷新都重建整個大型表格 widget。
- 用 icon / emoji 取代清楚文字，導致缺字、寬度失控或跨平台顯示不一致。

允許：

- QSS 純色背景。
- 1px 邊框。
- 少量 badge。
- 少量摘要卡片。
- `QTableView` + model/view。
- 長清單摘要化或用 table 呈現。
- 清楚文字、tooltip、button variant 與狀態色。

---

## 8. Daily Decision Desk 目前實作狀態

目前 Daily Decision Desk 已使用：

- `SectionPanel`
- `MetricCard`
- `StatusBadge`
- `CompactCodeList`
- `WarningList`

目前狀態：

1. Daily Decision Desk 已可作為 Month 4 v1 reference screen。
2. section quality 已以 `StatusBadge` 放在 section header，不再以可見長文字重複「品質：」。
3. 強勢、弱勢與低流動性代碼由 `CompactCodeList` 單一呈現；舊 `relative_strength_liquidity_value` 僅保留為相容欄位且不顯示。
4. `tests/test_decision_desk_ui_contract.py` 會阻擋 UI 直接 import scoring、screening、backtest、portfolio core 等計算模組。
5. 2026-07-02 已完成第一輪低風險 polish：主要操作按鈕、空狀態、提示色與全域樣式已對齊金融研究工作台語言。

後續改善方向：

- 把 Daily Decision Desk 拆為：
  1. 頂部 summary strip
  2. Market Intelligence grid
  3. Watchlist / Portfolio action panel
  4. Why Not / Warning panel
- 進一步把市場資訊、Watchlist / Portfolio action、Why Not / Warning 做成更清楚的 dashboard grid。
- 將強弱 / 流動性從分行文字升級為 compact table 或 chip row。
- 保留 service snapshot 邊界，不因視覺重做而在 UI 層新增計算。

---

## 9. 全 UI 遷移狀態

2026-07-02 第一輪低風險遷移已完成下列範圍：

- 設計 token：新增資料正負色、低干擾邊框、表格 hover / selected 與溫和重點色。
- 全域 QSS：補齊 button variants、tooltip、表格 corner、水平 / 垂直 scrollbar 與空狀態框。
- 共用 helper：新增 `EmptyStatePanel`、`apply_financial_table_style()` 與 text sanitizer。
- 門面頁：每日決策與持倉管理已整理為較一致的工作台視覺。
- 其他工作區：資料更新、推薦分析、回測、Watchlist、市場觀察與 evidence review 相關表格已逐步套用通用表格與按鈕語言。

本輪遷移邊界：

- 只改呈現層，不改資料抓取、SQLite 同步、推薦、回測、每日決策 snapshot 或持倉計算。
- 不重寫 layout 架構、不移除既有工作流、不改變資料來源與 DTO。
- 舊 view 仍可能保留少量 domain-specific inline style；後續應在不影響行為的前提下逐步抽到 token / helper。

---

## 10. 後續 Agent 修改流程

未來 agent 若要修改 UI theme，請依序執行：

1. 閱讀本文件。
2. 閱讀 `ui_qt/theme/tokens.py`、`ui_qt/theme/qss.py`、`ui_qt/widgets/theme_widgets.py`、`ui_qt/widgets/table_style.py`、`ui_qt/widgets/text_sanitizer.py`。
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

## 11. 遷移順序建議

後續若要把整個 UI 統一，建議順序：

1. Daily Decision Desk：已是 reference screen，後續可再改善 dashboard grid 與 action panel。
2. 持倉管理：已完成第一輪門面整理，後續可再統一風險 badge、籌碼警示與生命週期回顧細節。
3. 資料更新：已清理主要缺字 icon 與狀態卡，後續可再抽離更多 inline QSS。
4. 市場觀察：表格與按鈕已開始共用 helper，後續可整理 Smart Money domain-specific 樣式。
5. 推薦分析：已統一主要按鈕、表格與 detail 空狀態，後續可整理 Why / Why Not / Explain 區塊。
6. Research Lab：重點仍是高密度表單、結果頁與 Evidence Review 子頁的一致性。
7. Runtime Observatory：可維持工程監控風格，但應使用相同 token 與空狀態語言。

每一步都應獨立驗收，不要一次改完所有工作區。

---

## 12. 修改範例

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

## 13. 更新記錄

- 2026-07-02：同步全 UI 低風險 polish 狀態；補記新增 token、button variants、表格 helper、EmptyStatePanel、text sanitizer、全域 QSS 補強、遷移狀態與「只改呈現層、不改 service/domain 運算」邊界。
- 2026-06-16：建立 Midnight Analyst UI 設計系統規格，記錄目前 theme token、共用元件、效能限制、已知問題與後續 agent 修改流程。
- 2026-06-18：完成第一輪保守全域 polish，降低主背景藍色飽和度、提高 surface 層級、收斂 border，並補強 Tab / Button / Table / Input / ProgressBar 的全域 QSS 狀態。
