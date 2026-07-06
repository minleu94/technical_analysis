# 文檔結構與維護規則

> **最後更新**：2026-07-06
> **用途**：定義 `docs/` 內每個資料夾的歸屬、文件生命週期、刪除/歸檔規則。

---

## 一、權威文件層級

1. **目前狀態入口**
   - `docs/00_core/PROJECT_SNAPSHOT.md`
   - 定義目前狀態、工作模式、本週優先事項與高風險區。

2. **6 個月工程路線**
   - `docs/00_core/ROADMAP_6M_ENGINEERING.md`
   - 定義未來 6 個月的工程主線、月度里程碑、交付物與驗收標準。

3. **Roadmap Hub**
   - `docs/00_core/DEVELOPMENT_ROADMAP.md`
   - 只放系統定位、短版 Next、風險摘要與權威文件入口，不保存完整歷史。

4. **長期版本階梯 companion**
   - `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`
   - 將 6M Roadmap Phase 與 Vision 成功標準映射為 V2.1-V4.0 版本階梯；不取代 6M Roadmap 或 Vision。

5. **外部參考與版本形狀 companion**
   - `docs/00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`
   - 保存外部開源專案參考、資料源補強優先序、V1.5 至 V2.0 版本形狀與 deferred 技術邊界；不取代 Vision 或 6M Roadmap。

6. **舊 Roadmap 移交權威**
   - `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
   - 保存舊 Roadmap 未完成事項的唯一處置、目標月份、交付物與驗收 Gate。

7. **目前操作手冊**
   - `docs/07_guides/APPLICATION_MANUAL.md`
   - 保存目前 8 個工作區的完整操作、結果判讀、安全限制與排錯方式。

8. **架構權威**
   - `docs/01_architecture/system_architecture.md`
   - 定義目前架構、模組邊界、資料流與高風險技術邊界。

9. **索引與維護規則**
   - `docs/00_core/DOCUMENTATION_INDEX.md`
   - `docs/00_core/DOC_COVERAGE_MAP.md`
   - `docs/00_core/DOCUMENTATION_STRUCTURE.md`

10. **專項文件**
   - 架構、功能、資料、Phase、QA、指南、技術、Agent、策略文件。

11. **Archive**
   - `docs/09_archive/`
   - 僅作歷史追溯，不作目前狀態依據。

---

## 二、資料夾歸屬

| 目錄 | 放什麼 | 不放什麼 |
|---|---|---|
| `00_core/` | snapshot、6 個月 roadmap、roadmap hub、索引、文件治理規則 | 完整歷史 Done、單一功能的長篇操作教學 |
| `01_architecture/` | 架構、資料流、依賴邊界、Runtime 規範 | 一次性 QA 記錄 |
| `02_features/` | 使用者可見功能、UI、策略、回測、評分說明 | Phase 規劃草案 |
| `03_data/` | 資料更新、資料流、資料重建、資料故障排除 | 券商分點專屬細節 |
| `04_broker_branch/` | 券商分點資料、分點解析、籌碼資料更新 | 一般每日資料更新 |
| `05_phases/` | 歷史 Phase 設計、Phase 3.5 SOP、Phase 4 設計追溯 | 目前 roadmap、目前完成狀態、日常操作指南 |
| `06_qa/` | QA 問題、總結、驗證、審核報告 | 長期架構設計 |
| `07_guides/` | 快速開始、安裝、腳本、測試操作 | 系統權威狀態 |
| `08_technical/` | 技術優化、環境、參數設計備忘 | 使用者導向流程 |
| `09_archive/` | 歷史總結、已執行提案、舊調查、舊完整 Roadmap | 仍需日常引用的文件 |
| `agents/` | Agent 職責、協作規範、上下文 | 一般使用者指南 |
| `governance/` | 流程治理、決策紀錄、政策文件；目前為預留目錄 | 功能教學或一次性 QA |
| `strategies/` | 策略說明與 Why | 策略程式碼或測試 |
| `superpowers/` | Superpowers specs / plans、設計追溯與 execution artifacts | 目前 roadmap、目前狀態、raw output 或正式 QA closeout |

---

## 三、文件生命週期

### Active

日常使用、開發或決策會引用的文件。Active 文件必須：

- 出現在 `DOCUMENTATION_INDEX.md`
- 相對連結有效
- 狀態描述不與對應 scoped authority 衝突

### Historical

仍有追溯價值，但不應作為目前狀態依據。Historical 文件應放入 `09_archive/`，並在 README 中明確標註。

適合歸檔的內容：

- 舊線性 Phase 的完整 Done 與 Exit Criteria。
- 已執行完畢的 Next Action Plan。
- 舊 Roadmap current section。
- 過期但仍有決策脈絡價值的調查或提案。

### Delete

符合以下所有條件即可刪除：

- 沒有被 Active 文件引用
- 沒有保留歷史脈絡的必要
- 內容已被更新、更完整的文件取代
- 文件本身是一次性 debug log、patch note、單日執行指南或過期草稿

---

## 四、目前已確認的整理決策

- `PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、`DEVELOPMENT_ROADMAP.md`、`VERSION_ROADMAP_V2_1_TO_V4_0.md`、`EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`、`DOCUMENTATION_INDEX.md` 保持為核心入口。
- `DEVELOPMENT_ROADMAP.md` 是 Roadmap Hub，不再是完整歷史或唯一最高權威。
- 舊完整 Roadmap 已歸檔為 `docs/09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md`。
- `PROJECT_NAVIGATION.md`、`PROJECT_INVENTORY.md` 位於 repo 根目錄，仍屬專案級導航文件；索引需用正確相對路徑指向它們。
- 根目錄 `README.md` 保持使用者導向，說明專案目的、啟動方式與乾淨 `main` 使用方式；Agent / 開發者上下文放在 `AGENT_CONTEXT.md`。
- `ui_qt/README.md` 不屬於 `docs/`，但若 `docs` 索引引用它，需標註它可能落後於 roadmap。
- `09_archive/` 保留歷史文件，但 Active 文件不應依賴 archive 內容判斷目前狀態。
- `output/`、`output/qa/` 與根目錄臨時資料樣本屬於本機執行產物，不應作為 Active 文件或乾淨 `main` 內容；需要保存結論時整理為 `docs/06_qa/` 摘要。
- 一次性 QA debug / patch 文件可刪除，保留 summary / issues / audit 類文件即可。
- `docs/05_phases/` 維持原位置作為歷史 Phase / 設計追溯區，不整包搬入 archive，原因是仍有 Active 專項文件引用其設計脈絡；但每個入口必須明確標示 Historical / Reference，不得把其中的「下一步」「進行中」「Phase Gate」當作目前 roadmap。
- 若未來要進一步整理 `docs/05_phases/`，優先做「分批搬移 + redirect README + Index 修正」，不要直接刪除；Phase 3.5 SOP 若仍有操作價值，應先改寫到 `docs/02_features/` 或 `docs/07_guides/`，再把原文件歸檔。
- `docs/superpowers/` 保留為 spec / plan 追溯區；新增 `README.md` 作為資料夾邊界，避免大量 plan / spec 被誤讀成目前 roadmap。
- `docs/06_qa/UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md` 已因 2026-05-19 舊狀態容易誤導而歸檔為 `docs/09_archive/UI_QT_DEVELOPMENT_ROADMAP_AUDIT_2026_05_19.md`。
- `docs/agents/PATCH_MEMO.md` 已移至 `docs/08_technical/MCP_YFINANCE_OPENMARKETS_PATCH_MEMO.md`；MCP / openmarkets patch memo 屬技術環境備忘，不屬 Agent 角色規範。

---

## 五、每次整理後必跑檢查

1. Markdown 文件數量與目錄分布。
2. Active 文件是否都有 README 或索引入口。
3. Broken relative links。
4. Snapshot / 6M Roadmap / V2.1-V4.0 Roadmap / Roadmap Hub / Architecture / Index 狀態是否一致。
5. 是否有明顯過期的「待開始 / 進行中」描述。

## 六、更新記錄

- 2026-07-06：完成 push 前 docs 結構稽核後補上 `superpowers/` folder ownership、歸檔舊 UI Qt roadmap audit，並將 MCP patch memo 移至技術文件。
- 2026-07-06：新增 `VERSION_ROADMAP_V2_1_TO_V4_0.md` 作為 V2.0 之後長期版本階梯 companion，納入核心入口與文件權威層級。
- 2026-07-04：新增 `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md` 作為外部參考與 V1.5-V2.0 版本形狀 companion，納入核心入口與文件權威層級。
- 2026-07-03：將 `docs/05_phases/` 明確降格為 Historical / Reference 區，保留歷史設計與研究 SOP 脈絡，但不作目前 roadmap、目前完成狀態或日常操作權威。
