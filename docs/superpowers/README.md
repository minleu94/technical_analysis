# Superpowers Specs / Plans 目錄

> **最後整理**：2026-07-06
> **定位**：本目錄保存 Superpowers 流程產生的設計規格、實作計畫與歷史 execution artifacts。它是實作脈絡與追溯資料，不是目前狀態、roadmap 或版本權威。

目前專案的狀態與方向仍以 scoped authority 判讀：

- 目前狀態、本週優先事項與高風險區看 `../00_core/PROJECT_SNAPSHOT.md`。
- 未來 6 個月工程路線看 `../00_core/ROADMAP_6M_ENGINEERING.md`。
- V1 release 後至 V2.0 的版本節奏看 `../00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`。
- V2.0 之後的長期版號階梯看 `../00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`。
- 架構與模組邊界看 `../01_architecture/system_architecture.md`。

## 子目錄

| 目錄 | 放什麼 | 判讀方式 |
|---|---|---|
| `specs/` | 功能或治理增量的設計規格、邊界、資料契約與非目標 | 可作設計追溯；是否已完成仍以 Snapshot、QA closeout 與 Git closeout 為準。 |
| `plans/` | 實作計畫、工作拆分、驗收 gate 與文件同步清單 | 可作 execution trace；不單獨代表目前優先順序。 |

## 維護規則

- 新增仍在推動中的 spec / plan 時，若會被日常引用，應同步加入 `../00_core/DOCUMENTATION_INDEX.md`。
- 歷史 plan / spec 可以留在本目錄，不必逐一搬入 `09_archive/`；但它們不得取代 core roadmap、snapshot 或 architecture。
- 檔名日期是里程碑或計畫日期，不一定等於完成日期；完成狀態要看 QA closeout、Snapshot、Roadmap 或 Git 記錄。
- 原始輸出、暫存報告與本機執行產物不應放入本目錄；需要保存結論時整理為 `../06_qa/` 摘要。

## 相關入口

- `../00_core/DOCUMENTATION_INDEX.md` - 已納入文檔索引的主要 spec / plan。
- `../06_qa/SUPERPOWERS_PLAN_SPEC_DATE_AUDIT_2026_07_06.md` - Superpowers plan / spec 日期與完成狀態稽核。
- `../06_qa/DOCUMENTATION_PRE_PUSH_AUDIT_2026_07_06.md` - 本輪 push 前 docs 結構與關聯稽核。
