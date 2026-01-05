# 文檔覆蓋矩陣（Documentation Coverage Map）

> **給 Documentation Agent 用來判斷 coverage 的規則文件**

## 一、文件權威順序（Single Source of Truth Priority）

當文件描述衝突時，依以下順序判斷權威性：

1. **`docs/00_core/DEVELOPMENT_ROADMAP.md`** - 最高權威
   - Phase 狀態、功能清單、技術架構的 Single Source of Truth
   - 所有其他文件必須與 Roadmap 的 Living Section 一致
   - **Living Section 定義**：見該文件的「📍 Living Section 定義」段落

2. **`docs/00_core/PROJECT_SNAPSHOT.md`** - 次級權威
   - 從 Roadmap 抽出的短版入口
   - 必須與 Roadmap 的當前狀態一致

3. **`docs/00_core/DOCUMENTATION_INDEX.md`** - 索引權威
   - 文檔結構與導航的 Single Source of Truth
   - 若索引內進度文字與 Roadmap 衝突，以 Roadmap 為準

4. **`PROJECT_NAVIGATION.md`** - 架構導航權威
   - 三層架構（UI / Service / Domain）的導航說明
   - 功能導航（我要做 X，要去哪裡看？）

5. **其他專項文檔** - 功能特定權威
   - `docs/02_features/UI_FEATURES_DOCUMENTATION.md` - UI 功能說明
   - `docs/02_features/USER_GUIDE.md` - 使用者指南
   - `docs/01_architecture/system_architecture.md` - 系統架構
   - `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md` - 策略設計規格

**衝突處理規則：**
- 若 Snapshot / Index 與 Roadmap 衝突 → 以 Roadmap 為準，更新 Snapshot / Index
- 若專項文檔與 Roadmap 衝突 → 以 Roadmap 為準，更新專項文檔
- 若專項文檔之間衝突 → 以 Roadmap 為準，或要求使用者澄清

## 二、變更類型 → 必須更新的文件對照表

### UI / View / Tab 變更

**變更範圍：**
- `ui_qt/views/*.py` 新增/修改/刪除
- Tab 結構變更（新增 Tab、合併 Tab、Tab 順序變更）
- UI 功能新增/修改/移除

**必須更新（Must）：**
- `docs/02_features/UI_FEATURES_DOCUMENTATION.md` - UI 功能說明
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「現在的工作模式」段落（如影響使用流程）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若新增文檔，需更新索引

**應該更新（Should）：**
- `docs/02_features/USER_GUIDE.md` - 使用者指南（如有操作流程變更）
- `PROJECT_NAVIGATION.md` - 「功能導航」段落（如新增功能）
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Living Section（如影響 Phase 狀態）

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
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Living Section（如影響 Phase 狀態）
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「高風險區」段落（如涉及高風險模組）

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
- `docs/02_features/USER_GUIDE.md` - 使用者指南（如操作流程變更）
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「高風險區」段落（這些都是高風險區）

**應該更新（Should）：**
- `docs/02_features/STRATEGY_DESIGN_SPECIFICATION.md` - 策略設計規格（如策略邏輯變更）
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Living Section（如影響 Phase 狀態）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若新增文檔，需更新索引

**可選更新（Nice-to-have）：**
- `docs/UI_FEATURES_DOCUMENTATION.md` - UI 功能說明（如 UI 行為變更）

---

### Agent 文件變更

**變更範圍：**
- `docs/agents/*.md` 新增/修改/刪除
- Agent 職責變更
- Agent Prompt 模板變更

**必須更新（Must）：**
- `docs/agents/README.md` - Agent 總覽（如新增 Agent 或職責變更）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 文檔索引（如新增 Agent 文檔）

**應該更新（Should）：**
- `docs/00_core/PROJECT_SNAPSHOT.md` - 「Tech Lead 的預設任務」段落（如 Tech Lead 變更）

**可選更新（Nice-to-have）：**
- `README.md` - 專案主文檔（如為重大變更）

---

### 使用流程或 Phase 狀態變更

**變更範圍：**
- Phase 完成狀態變更
- 工作流程變更（「現在的工作模式」）
- 優先事項變更
- 系統定位變更

**必須更新（Must）：**
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Living Section（Phase 狀態、Next、Blockers）
  - **Living Section 範圍**：見該文件的「📍 Living Section 定義」段落
- `docs/00_core/PROJECT_SNAPSHOT.md` - 所有相關段落（當前狀態、工作模式、優先事項）
- `docs/00_core/DOCUMENTATION_INDEX.md` - 若索引內進度文字過期，需更新

**應該更新（Should）：**
- `README.md` - 專案主文檔（如 Phase 狀態變更）
- `docs/00_core/PROJECT_SNAPSHOT.md` - 專案快照（開場 30 秒必讀）

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
- `docs/USER_GUIDE.md` - 使用者指南（如影響使用者操作）

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
- `docs/00_core/DEVELOPMENT_ROADMAP.md` - Living Section（如為重大策略變更）

---

### 文檔結構 / 文檔組織變更

**變更範圍：**
- 新增/刪除/重組文檔
- 文檔索引結構變更

**必須更新（Must）：**
- `docs/00_core/DOCUMENTATION_INDEX.md` - 文檔索引（必須反映最新結構）

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

2. **Snapshot / Index / Roadmap 一致性檢查通過**
   - `docs/00_core/PROJECT_SNAPSHOT.md` 與 `docs/00_core/DEVELOPMENT_ROADMAP.md` 的 Living Section 一致
   - `docs/00_core/DOCUMENTATION_INDEX.md` 與 `docs/00_core/DEVELOPMENT_ROADMAP.md` 的 Living Section 進度描述一致
   - 若發現不一致，必須修正（以 Roadmap 的 Living Section 為準）
   - **Living Section 定義**：見 `docs/00_core/DEVELOPMENT_ROADMAP.md` 的「📍 Living Section 定義」段落

3. **相關使用指南已更新**
   - 若變更影響使用者操作流程，`docs/02_features/USER_GUIDE.md` 必須更新
   - 若變更影響 UI 功能，`docs/02_features/UI_FEATURES_DOCUMENTATION.md` 必須更新

4. **變更日誌已記錄**
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

### Snapshot ↔ Roadmap 一致性
- [ ] Phase 狀態一致（Snapshot 的「當前狀態」與 Roadmap Living Section 的「現況」一致）
- [ ] 工作模式描述一致（Snapshot 的「現在的工作模式」與 Roadmap Living Section 一致）
- [ ] 優先事項一致（Snapshot 的「本週優先事項」與 Roadmap Living Section 的「下一步 Next」一致）
- [ ] 高風險區一致（Snapshot 的「高風險區」與 Roadmap Living Section 的「Blockers / Risks」一致）

### Index ↔ Roadmap 一致性
- [ ] 進度描述一致（Index 的進度描述與 Roadmap Living Section 一致，以 Roadmap 為準）
- [ ] 文檔索引完整（所有新文檔已加入索引）

### 專項文檔 ↔ Roadmap 一致性
- [ ] UI 功能描述與 Roadmap 一致
- [ ] 使用者指南與 Roadmap 一致
- [ ] 架構文檔與 Roadmap 一致

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
   - 當進度描述過期時 → 必須更新（以 Roadmap 為準）

3. **`docs/00_core/DEVELOPMENT_ROADMAP.md`**
   - 當 Phase 狀態變更時 → 必須更新 Living Section 的「現況」段落
   - 當優先事項變更時 → 必須更新 Living Section 的「下一步 Next」段落
   - 當風險變更時 → 必須更新 Living Section 的「Blockers / Risks」段落
   - **Living Section 定義**：見該文件的「📍 Living Section 定義」段落

### 特定變更類型必須檢查

4. **`PROJECT_NAVIGATION.md`**
   - 當架構變更時 → 必須更新「三層架構導航」
   - 當功能變更時 → 必須更新「功能導航」

5. **`README.md`**
   - 當為重大功能變更時 → 應該更新（雖然優先級較低，但容易被忽略）

## 使用說明（給 Documentation Agent）

1. **收到變更請求時**：
   - 根據「變更類型 → 必須更新的文件對照表」識別需要更新的文件
   - **特別檢查「容易被忽略但必須更新的文件清單」**
   - 標示優先級（Must / Should / Nice-to-have）

2. **執行 Coverage Pass 時**：
   - 列出所有需要更新的文件清單（包括容易被忽略的文件）
   - 檢查 Snapshot / Index / Roadmap 一致性（使用下方「一致性檢查清單」）
   - 標示需要更新的具體段落

3. **執行 Patch Pass 時**：
   - 僅更新已確認的 Coverage 清單中的文件
   - 確保所有 Must 優先級的文件已更新
   - **特別確保 Snapshot / Index / Roadmap 已更新並一致**

4. **完成後驗證**：
   - 執行「一致性檢查清單」
   - 確認所有 DoD 條件已滿足
   - **確認所有容易被忽略的文件已檢查並更新（如適用）**

---

**最後更新**：2026-01-03

