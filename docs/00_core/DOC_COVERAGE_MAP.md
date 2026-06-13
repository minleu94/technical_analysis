# 文檔覆蓋矩陣（Documentation Coverage Map）

> **給 Documentation Agent 用來判斷 coverage 的規則文件**

## 一、文件權威邊界（Scoped SSOT）

本專案不再使用單一文件承擔所有最高權威。當文件描述衝突時，先判斷主題，再依主題對應的權威文件處理。

| 主題 | 權威文件 | 判斷規則 |
|---|---|---|
| 目前狀態、本週優先事項、高風險區 | `docs/00_core/PROJECT_SNAPSHOT.md` | 開場與日常工作先看 Snapshot。 |
| 未來 6 個月工程路線 | `docs/00_core/ROADMAP_6M_ENGINEERING.md` | 里程碑、交付物與驗收標準以 6M Roadmap 為準。 |
| Roadmap 入口與權威導覽 | `docs/00_core/DEVELOPMENT_ROADMAP.md` | Roadmap Hub 只保存入口與短版 Next，不保存完整歷史。 |
| 舊 Roadmap 未完成事項移交 | `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` | 每個 Legacy 項目必須有唯一處置、月份與驗收定義。 |
| 系統架構、模組邊界、資料流 | `docs/01_architecture/system_architecture.md` | 架構描述衝突時，以系統架構文件為準。 |
| 目前使用者完整操作流程 | `docs/07_guides/APPLICATION_MANUAL.md` | 7 個頂層工作區、跨工作區流程、安全限制與排錯以本手冊為準。 |
| 文檔位置與分類 | `docs/00_core/DOCUMENTATION_INDEX.md` | 只作導航，不取代狀態或架構權威。 |
| 文檔生命週期與歸檔規則 | `docs/00_core/DOCUMENTATION_STRUCTURE.md` | 刪除、搬移、歸檔 Markdown 前必須參考。 |
| 歷史 Phase、舊 Done、舊 Roadmap current section | `docs/09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md` | 只作追溯，不作目前狀態依據。 |

其他專項文件權威：

1. **`PROJECT_NAVIGATION.md`** - 開發者導航權威
   - 三層架構（UI / Service / Domain）的導航說明
   - 功能導航（我要做 X，要去哪裡看？）

2. **`AGENTS.md` / `docs/agents/`** - Codex 與 Agent 指引權威
   - `AGENTS.md` 是 Codex 自動讀取的 repo 指令入口
   - `docs/agents/` 保存完整 Agent 職責、Prompt 與共用上下文

3. **其他專項文檔** - 功能特定權威
   - `docs/02_features/UI_FEATURES_DOCUMENTATION.md` - UI 功能說明
   - `docs/07_guides/APPLICATION_MANUAL.md` - 完整使用手冊
   - `docs/02_features/USER_GUIDE.md` - 進階專題教學
   - `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md` - 策略設計規格

**衝突處理規則：**
- 若 Snapshot、6M Roadmap、Architecture 之間衝突 → 先判斷主題，依上表權威文件修正。
- 若 Index 路徑與實際檔案不符 → 以實際檔案與文件結構規則修正 Index。
- 若 Active 專項文檔仍引用舊 Phase 或舊 Roadmap current section → 更新為 scoped authority；歷史內容移至 archive 或保留歷史語意。
- 無法判斷主題歸屬時，標示「需要確認」，不要自行建立第二套權威。

## 二、變更類型 → 必須更新的文件對照表

### UI / View / Tab 變更

**變更範圍：**
- `ui_qt/views/*.py` 新增/修改/刪除
- Tab 結構變更（新增 Tab、合併 Tab、Tab 順序變更）
- UI 功能新增/修改/移除

**必須更新（Must）：**
- `docs/02_features/UI_FEATURES_DOCUMENTATION.md` - UI 功能說明
- `docs/07_guides/APPLICATION_MANUAL.md` - 新增或改變使用者可操作功能、參數、結果或限制時
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「現在的工作模式」段落（如影響使用流程）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若新增文檔，需更新索引

**應該更新（Should）：**
- `docs/02_features/USER_GUIDE.md` - 使用者指南（如有操作流程變更）
- `PROJECT_NAVIGATION.md` - 「功能導航」段落（如新增功能）
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Roadmap Hub（如影響短版 Next、入口或歷史導引）

**可選更新（Nice-to-have）：**
- `README.md` - 專案主文檔（如為重大功能變更）

---

### Service / Domain / DTO 變更

**變更範圍：**
- `app_module/*.py` 新增/修改/刪除
- `decision_module/*.py` 新增/修改/刪除
- DTO 結構變更（`app_module/dtos.py`）

**必須更新（Must）：**
- `PROJECT_NAVIGATION.md` - 「三層架構導航」段落（如架構變更）
- `docs/01_architecture/system_architecture.md` - 系統架構文檔（如架構變更）

**應該更新（Should）：**
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「高風險區」段落（如涉及高風險模組）
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Roadmap Hub（如影響短版 Next、入口或歷史導引）

**可選更新（Nice-to-have）：**
- `PROJECT_INVENTORY.md` - 專案盤點（如為重大模組變更）

---

### 回測 / 推薦核心邏輯變更

**變更範圍：**
- `app_module/backtest_service.py` 修改
- `app_module/recommendation_service.py` 修改
- `backtest_module/*.py` 修改
- `decision_module/scoring_engine.py` 修改
- `decision_module/reason_engine.py` 修改
- Strategy registry / preset / promotion 相關服務變更

**必須更新（Must）：**
- `docs/02_features/BACKTEST_LAB_FEATURES.md` - 回測功能文檔（如回測邏輯變更）
- `docs/07_guides/APPLICATION_MANUAL.md` - 回測模式、參數、結果判讀或 Promote 規則變更
- `docs/02_features/USER_GUIDE.md` - 使用者指南（如操作流程變更）
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「高風險區」段落（這些都是高風險區）

**應該更新（Should）：**
- `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md` - 策略設計規格（如策略邏輯變更）
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Roadmap Hub（如影響短版 Next、入口或歷史導引）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若新增文檔，需更新索引

**可選更新（Nice-to-have）：**
- `docs/02_features/UI_FEATURES_DOCUMENTATION.md` - UI 功能說明（如 UI 行為變更）

---

### Agent 文件變更

**變更範圍：**
- `docs/agents/*.md` 新增/修改/刪除
- Agent 職責變更
- Agent Prompt 模板變更

**必須更新（Must）：**
- `AGENTS.md` - 若 Codex 自動讀取入口或強制必讀順序變更
- `docs/agents/README.md` - Agent 總覽（如新增 Agent 或職責變更）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 文檔索引（如新增 Agent 文檔）

**應該更新（Should）：**
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「Tech Lead 的預設任務」段落（如 Tech Lead 變更）

**可選更新（Nice-to-have）：**
- `README.md` - 專案主文檔（如為重大變更）

---

### 使用流程、目前狀態或 Roadmap 變更

**變更範圍：**
- 目前狀態或產品閉環狀態變更
- 工作流程變更（「現在的工作模式」）
- 優先事項變更
- 系統定位變更
- 未來 6 個月工程路線變更

**必須更新（Must）：**
- `docs/00_core/PROJECT_SNAPSHOT.md` - 目前狀態、工作模式、優先事項、高風險區
- `docs/00_core/ROADMAP_6M_ENGINEERING.md` - 若影響 6 個月里程碑、交付物或驗收標準
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - 若新增或調整 Roadmap Hub 入口與短版 Next
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若索引內進度文字過期，需更新

**應該更新（Should）：**
- `README.md` - 專案主文檔（如 Phase 狀態變更）
- `PROJECT_NAVIGATION.md` / `PROJECT_INVENTORY.md` - 若影響開發導航或盤點

**可選更新（Nice-to-have）：**
- `PROJECT_INVENTORY.md` - 專案盤點（如為重大狀態變更）

---

### 資料處理 / 資料架構變更

**變更範圍：**
- `data_module/*.py` 修改
- 資料格式變更
- 資料流程變更

**必須更新（Must）：**
- `docs/01_architecture/data_collection_architecture.md` - 資料收集架構（如資料架構變更）
- `docs/03_data/DATA_FETCHING_LOGIC.md` - 資料獲取邏輯（如資料獲取邏輯變更）
- `docs/03_data/daily_data_update_guide.md` - 每日資料更新指南（如更新流程變更）

**應該更新（Should）：**
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若新增文檔，需更新索引

**可選更新（Nice-to-have）：**
- `docs/02_features/USER_GUIDE.md` - 進階使用者指南（如影響使用者操作）
- `docs/07_guides/APPLICATION_MANUAL.md` - 完整操作手冊（如影響使用流程、參數、結果判讀或安全限制）

---

### 策略設計 / 策略規格變更

**變更範圍：**
- `docs/strategies/*.md` 新增/修改/刪除
- 策略邏輯變更
- 策略參數變更

**必須更新（Must）：**
- `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md` - 策略設計規格（如策略規格變更）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若新增策略文檔，需更新索引

**應該更新（Should）：**
- `docs/02_features/USER_GUIDE.md` - 使用者指南（如影響策略使用）
- `docs/02_features/BACKTEST_LAB_FEATURES.md` - 回測功能文檔（如策略回測變更）

**可選更新（Nice-to-have）：**
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Roadmap Hub（如為重大策略方向或入口變更）

---

### 文檔結構 / 文檔組織變更

**變更範圍：**
- 新增/刪除/重組文檔
- 文檔索引結構變更

**必須更新（Must）：**
- `docs/00_core/DOCUMENTATION_INDEX.md` - 文檔索引（必須反映最新結構）
- `docs/00_core/DOCUMENTATION_STRUCTURE.md` - 若資料夾歸屬、刪除/歸檔規則、文件生命週期有變更

**應該更新（Should）：**
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「指定權威文件」段落（如權威文件變更）

**可選更新（Nice-to-have）：**
- `README.md` - 專案主文檔（如為重大結構變更）

## 三、Documentation Definition of Done（DoD）

文件更新完成必須滿足以下所有條件：

### 必須條件（Must）

1. **所有 Must 優先級的文件已更新**
   - 根據「變更類型 → 必須更新的文件對照表」檢查
   - 所有標示為 Must 的文件都已更新

2. **Scoped Authority 一致性檢查通過**
   - `PROJECT_SNAPSHOT.md` 的目前狀態與本週優先事項合理反映當前工作。
   - `ROADMAP_6M_ENGINEERING.md` 的 6 個月路線與 Roadmap Hub 的 Next 不衝突。
   - `system_architecture.md` 的架構描述不落後於 Snapshot 的已完成能力。
   - `DOCUMENTATION_INDEX.md` 包含新增、搬移或歸檔的 Markdown。
   - 若發現不一致，必須依主題權威文件修正，而不是一律回寫 Roadmap。

3. **文件結構已更新**
   - 新增/刪除/搬移 Markdown 後，`DOCUMENTATION_INDEX.md` 必須同步
   - 若文件分類或刪除規則改變，`DOCUMENTATION_STRUCTURE.md` 必須同步

4. **相關使用指南已更新**
   - 若變更影響使用者操作流程，`docs/07_guides/APPLICATION_MANUAL.md` 必須更新
   - 若變更影響進階專題教學，`docs/02_features/USER_GUIDE.md` 必須更新
   - 若變更影響 UI 功能，`docs/02_features/UI_FEATURES_DOCUMENTATION.md` 必須更新

5. **Manual 完整性 Gate 已通過**
   - 每個使用者可見工作區都有入口與前置條件。
   - 每個可操作功能都有步驟與參數意義。
   - 結果頁有判讀方式，不只列出功能名稱。
   - 危險操作、不可逆行為與目前限制有明確警告。
   - 至少包含常見失敗與排錯入口。

6. **變更日誌已記錄**
   - 根據 `docs/agents/shared_context.md` 的「更新記錄 / 變更日誌規範」記錄變更
   - 若存在變更日誌文件（如 `docs/UPDATE_LOG_*.md`），需記錄變更

### 應該條件（Should）

1. **所有 Should 優先級的文件已更新**
   - 根據「變更類型 → 必須更新的文件對照表」檢查
   - 所有標示為 Should 的文件都已更新

2. **架構文檔已更新**
   - 若變更影響系統架構，`docs/01_architecture/system_architecture.md` 或 `PROJECT_NAVIGATION.md` 已更新

3. **專案主文檔已更新**
   - 若為重大變更，`README.md` 已更新

### 可選條件（Nice-to-have）

1. **所有 Nice-to-have 優先級的文件已更新**
   - 根據「變更類型 → 必須更新的文件對照表」檢查

2. **專案盤點已更新**
   - 若為重大結構變更，`PROJECT_INVENTORY.md` 已更新

---

## 一致性檢查清單

每次文件更新後，必須檢查以下一致性：

### Snapshot ↔ Roadmap Hub ↔ 6M Roadmap 一致性
- [ ] Snapshot 的「本週優先事項」落在 6M Roadmap 的 Month 1 或當前月度目標內。
- [ ] Roadmap Hub 的 Next 不新增與 6M Roadmap 衝突的平行方向。
- [ ] Snapshot 的高風險區涵蓋 6M Roadmap 近期任務的高風險模組。

### Index ↔ Scoped Authority 一致性
- [ ] Index 的進度描述不與 Snapshot、6M Roadmap 或 Architecture 衝突。
- [ ] 文檔索引完整（所有新文檔已加入索引）

### 專項文檔 ↔ Scoped Authority 一致性
- [ ] UI 功能描述與 Snapshot / UI docs 一致。
- [ ] 完整操作手冊與目前 7 個工作區、按鈕啟用狀態及工作模式一致。
- [ ] 進階使用者指南與完整操作手冊不衝突。
- [ ] 架構文檔與目前模組實際邊界一致。

---

## 容易被忽略但必須更新的文件清單

以下文件在變更時容易被忽略，但根據變更類型，必須檢查：

### 所有變更類型都必須檢查

1. **`docs/00_core/PROJECT_SNAPSHOT.md`**
   - 當變更影響「現在的工作模式」時 → 必須更新
   - 當變更影響 Phase 狀態時 → 必須更新
   - 當變更影響優先事項時 → 必須更新
   - 當變更涉及高風險區時 → 必須更新

2. **`docs/00_core/DOCUMENTATION_INDEX.md`**
   - 當新增/刪除文檔時 → 必須更新索引
   - 當文檔結構變更時 → 必須更新索引
   - 當進度描述過期時 → 必須依 Scoped Authority 更新

3. **`docs/00_core/DOCUMENTATION_STRUCTURE.md`**
   - 當新增/刪除資料夾時 → 必須更新資料夾歸屬
   - 當刪除 Active Markdown 時 → 必須確認符合 Delete 條件
   - 當文件被改為 Historical 時 → 必須確認是否應移入 `09_archive/`

4. **`docs/00_core/DEVELOPMENT_ROADMAP.md`**
   - 當 Roadmap Hub 入口、Next 摘要或權威文件指向變更時 → 必須更新。
   - 不再把完整歷史 Done、長期架構細節或所有風險都塞回本文件。

5. **`docs/00_core/ROADMAP_6M_ENGINEERING.md`**
   - 當 6 個月工程方向、月度里程碑、交付物或驗收標準變更時 → 必須更新。
   - 當只是單日完成小修復，且不影響 6 個月方向時 → 不需要更新。

### 特定變更類型必須檢查

6. **`PROJECT_NAVIGATION.md`**
   - 當架構變更時 → 必須更新「三層架構導航」
   - 當功能變更時 → 必須更新「功能導航」

7. **`README.md`**
   - 當為重大功能變更時 → 應該更新（雖然優先級較低，但容易被忽略）

## 使用說明（給 Documentation Agent）

1. **收到變更請求時**：
   - 根據「變更類型 → 必須更新的文件對照表」識別需要更新的文件
   - **特別檢查「容易被忽略但必須更新的文件清單」**
   - 標示優先級（Must / Should / Nice-to-have）

2. **執行 Coverage Pass 時**：
   - 列出所有需要更新的文件清單（包括容易被忽略的文件）
   - 檢查 Snapshot / Roadmap Hub / 6M Roadmap / Architecture / Index 一致性（使用下方「一致性檢查清單」）
   - 標示需要更新的具體段落

3. **執行 Patch Pass 時**：
   - 僅更新已確認的 Coverage 清單中的文件
   - 確保所有 Must 優先級的文件已更新
   - **特別確保 Snapshot / Roadmap Hub / 6M Roadmap / Architecture / Index 已更新並一致**

4. **完成後驗證**：
   - 執行「一致性檢查清單」
   - 確認所有 DoD 條件已滿足
   - **確認所有容易被忽略的文件已檢查並更新（如適用）**

---

**最後更新**：2026-06-13

