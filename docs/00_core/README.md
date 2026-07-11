# 核心文檔目錄

> **核心文檔（必讀）**

本目錄包含系統的核心文檔。專案目前採用 Scoped SSOT：不同主題由不同文件負責，不再由單一 Roadmap 承擔所有權威。

## 📄 文檔列表

- **`PROJECT_SNAPSHOT.md`** ⭐ **開場必讀**
  - 專案快照（開場 30 秒狀態）
  - 目前狀態、本週優先事項、高風險區的權威入口

- **`ROADMAP_6M_ENGINEERING.md`**
  - 未來 6 個月可執行工程路線
  - 把 Post-Refactor Product Roadmap 轉成 Gate、交付物、依賴、測試、禁止事項與 Exit Criteria

- **`PRODUCT_ROADMAP_POST_REFACTOR.md`**
  - 安全重構完成後的產品方向權威
  - 定義 bounded investment advice、Guided / Professional Mode、Portfolio Advice、Position Health / Exit、Evidence、Data、ML 與 signal pruning 的產品演進

- **`VERSION_ROADMAP_V1_1_TO_V2_0.md`**
  - V1.1 至 V2.0 已完成歷史版本與 V2.0 形成過程
  - 不承擔目前產品 Next，且工程完成不等於投資有效性

- **`VERSION_ROADMAP_V2_1_TO_V4_0.md`**
  - V2.0 之後的長期產品成熟度與版本階梯
  - V2.x 聚焦 Daily Advice / Evidence / Data / Portfolio foundation；V3.x 聚焦 effectiveness / pruning / ML shadow；V4.0 需長期 evidence 支持

- **`DEVELOPMENT_ROADMAP.md`**
  - Roadmap Hub
  - 指向 Snapshot、6M Roadmap、長期版本階梯、系統架構與歷史歸檔
  - 不保存完整歷史 Done，也不作為唯一狀態權威

- **`LEGACY_ROADMAP_CARRYOVER.md`**
  - 舊 Roadmap 未完成事項的完整移交矩陣
  - 每個項目均指定新 Roadmap 月份、交付物與驗收方式

- **`DOCUMENTATION_INDEX.md`**
  - 文檔索引（文檔結構的 Single Source of Truth）
  - 完整的文檔導航和分類

- **`DOC_COVERAGE_MAP.md`**
  - 文檔覆蓋矩陣（Documentation Agent 判斷 coverage 的規則文件）
  - 定義變更類型 → 必須更新的文件對照表

- **`DOCUMENTATION_STRUCTURE.md`**
  - 文檔生命週期、歸檔與刪除規則
  - 新增、搬移或整理 Markdown 前必讀

> 根目錄 `README.md` 是使用者導向入口；Agent / 開發者快速上下文請看 repo 根目錄 `AGENT_CONTEXT.md`。本目錄只保留核心權威文件與文件治理規則。

## Scoped SSOT 導航

| 想找的內容 | 權威文件 |
|---|---|
| 現在狀態、本週優先事項、目前 Gate、高風險區 | `PROJECT_SNAPSHOT.md` |
| North Star、Product Principles、Bounded Advice、Evidence、Success Levels、Non-goals | `../01_architecture/system_vision_specification.md` |
| 重構完成後產品方向、投資問題與產品能力演進 | `PRODUCT_ROADMAP_POST_REFACTOR.md` |
| 未來六個月工程 Gate、deliverables、dependencies、tests、Exit Criteria | `ROADMAP_6M_ENGINEERING.md` |
| V1.1-V2.0 歷史版本 | `VERSION_ROADMAP_V1_1_TO_V2_0.md` |
| V2.1-V4.0 長期產品成熟度 | `VERSION_ROADMAP_V2_1_TO_V4_0.md` |
| 現在真實架構 | `../01_architecture/system_architecture.md` |
| Transitional / Target Architecture | `../01_architecture/target_system_architecture.md` |
| 行為不變安全重構計畫 | `../01_architecture/SAFE_REFACTORING_MASTER_REPORT.md` |
| 現在已實作的操作流程 | `../07_guides/APPLICATION_MANUAL.md` |
| 文件位置 | `DOCUMENTATION_INDEX.md` |

## 🔗 相關目錄

- `../01_architecture/` - 架構文檔
- `../02_features/` - 功能文檔
- `../03_data/` - 數據相關文檔
- `../07_guides/` - 指南文檔

## 判讀順序

1. 先讀 `PROJECT_SNAPSHOT.md` 取得目前狀態。
2. 若要理解產品為何存在與安全邊界，讀 `../01_architecture/system_vision_specification.md`。
3. 若要規劃重構完成後的產品方向，讀 `PRODUCT_ROADMAP_POST_REFACTOR.md`。
4. 若要執行未來六個月工程，讀 `ROADMAP_6M_ENGINEERING.md`。
5. 若要理解歷史或長期版號，分別讀兩份 Version Roadmap。
6. 若要確認目前或目標架構，分別讀 `system_architecture.md` 與 `target_system_architecture.md`。
7. 若要執行安全重構，讀 `SAFE_REFACTORING_MASTER_REPORT.md`；它不承擔產品 Roadmap。
8. 若要操作目前系統，讀 `../07_guides/APPLICATION_MANUAL.md`。
9. 若要找文件位置，讀 `DOCUMENTATION_INDEX.md`。
10. 若要追溯舊 Phase 或歷史 Done，讀 archive；Historical 文件不作目前狀態依據。

## 更新記錄

- 2026-07-11：加入 Post-Refactor Product Roadmap 與 Target Architecture 入口，重整 Scoped SSOT 導航與判讀順序，明確分開產品、工程、版本、Current / Target Architecture 與 Safe Refactor 權威。

