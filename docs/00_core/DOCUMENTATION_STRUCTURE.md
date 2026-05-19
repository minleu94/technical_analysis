# 文檔結構與維護規則

> **最後更新**：2026-05-19  
> **用途**：定義 `docs/` 內每個資料夾的歸屬、文件生命週期、刪除/歸檔規則。

---

## 一、權威文件層級

1. **Roadmap / Living Section**
   - `docs/00_core/DEVELOPMENT_ROADMAP.md`
   - 定義目前 Phase 狀態、Next、Blockers/Risks。

2. **入口摘要**
   - `docs/00_core/PROJECT_SNAPSHOT.md`
   - 只放目前狀態，不放長歷史。

3. **索引與維護規則**
   - `docs/00_core/DOCUMENTATION_INDEX.md`
   - `docs/00_core/DOC_COVERAGE_MAP.md`
   - `docs/00_core/DOCUMENTATION_STRUCTURE.md`

4. **專項文件**
   - 架構、功能、資料、Phase、QA、指南、技術、Agent、策略文件。

5. **Archive**
   - `docs/09_archive/`
   - 僅作歷史追溯，不作目前狀態依據。

---

## 二、資料夾歸屬

| 目錄 | 放什麼 | 不放什麼 |
|---|---|---|
| `00_core/` | roadmap、snapshot、索引、文件治理規則 | 單一功能的長篇操作教學 |
| `01_architecture/` | 架構、資料流、依賴邊界、Runtime 規範 | 一次性 QA 記錄 |
| `02_features/` | 使用者可見功能、UI、策略、回測、評分說明 | Phase 規劃草案 |
| `03_data/` | 資料更新、資料流、資料重建、資料故障排除 | 券商分點專屬細節 |
| `04_broker_branch/` | 券商分點資料、分點解析、籌碼資料更新 | 一般每日資料更新 |
| `05_phases/` | Phase 設計、Phase 3.5 SOP、Phase 4 設計 | 日常操作指南 |
| `06_qa/` | QA 問題、總結、驗證、審核報告 | 長期架構設計 |
| `07_guides/` | 快速開始、安裝、腳本、測試操作 | 系統權威狀態 |
| `08_technical/` | 技術優化、環境、參數設計備忘 | 使用者導向流程 |
| `09_archive/` | 歷史總結、已執行提案、舊調查 | 仍需日常引用的文件 |
| `agents/` | Agent 職責、協作規範、上下文 | 一般使用者指南 |
| `governance/` | 流程治理、決策紀錄、政策文件；目前為預留目錄 | 功能教學或一次性 QA |
| `strategies/` | 策略說明與 Why | 策略程式碼或測試 |

---

## 三、文件生命週期

### Active

日常使用、開發或決策會引用的文件。Active 文件必須：

- 出現在 `DOCUMENTATION_INDEX.md`
- 相對連結有效
- 狀態描述不與 roadmap Living Section 衝突

### Historical

仍有追溯價值，但不應作為目前狀態依據。Historical 文件應放入 `09_archive/`，並在 README 中明確標註。

### Delete

符合以下所有條件即可刪除：

- 沒有被 Active 文件引用
- 沒有保留歷史脈絡的必要
- 內容已被更新、更完整的文件取代
- 文件本身是一次性 debug log、patch note、單日執行指南或過期草稿

---

## 四、目前已確認的整理決策

- `DEVELOPMENT_ROADMAP.md`、`PROJECT_SNAPSHOT.md`、`DOCUMENTATION_INDEX.md` 保持為核心入口。
- `PROJECT_NAVIGATION.md`、`PROJECT_INVENTORY.md` 位於 repo 根目錄，仍屬專案級導航文件；索引需用正確相對路徑指向它們。
- `ui_qt/README.md` 不屬於 `docs/`，但若 `docs` 索引引用它，需標註它可能落後於 roadmap。
- `09_archive/` 保留歷史文件，但 Active 文件不應依賴 archive 內容判斷目前狀態。
- 一次性 QA debug / patch 文件可刪除，保留 summary / issues / audit 類文件即可。

---

## 五、每次整理後必跑檢查

1. Markdown 文件數量與目錄分布。
2. Active 文件是否都有 README 或索引入口。
3. Broken relative links。
4. Roadmap / Snapshot / Index 狀態是否一致。
5. 是否有明顯過期的「待開始 / 進行中」描述。
