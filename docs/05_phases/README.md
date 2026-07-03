# 歷史 Phase 與研究 SOP 文檔目錄

> **狀態**：Historical / Reference。
> **最後整理**：2026-07-03。
> **判讀規則**：本目錄保留 Phase 時期的設計、驗收與研究 SOP 脈絡，不作為目前 roadmap、目前完成狀態或下一步優先順序依據。

目前專案已改採 Scoped SSOT：

- 目前狀態、本週優先事項與高風險區看 `../00_core/PROJECT_SNAPSHOT.md`。
- 未來 6 個月工程路線看 `../00_core/ROADMAP_6M_ENGINEERING.md`。
- V1 release 後的 V1.1 / V1.2 / V1.3 / V1.4 / V2.0 節奏看 `../00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`。
- 架構與模組邊界看 `../01_architecture/system_architecture.md`。
- 實際操作方式看 `../07_guides/APPLICATION_MANUAL.md`。

本目錄沒有被刪除，是因為仍有 Active 專項文件會引用 Phase 2、Phase 3.3b、Phase 4 與研究 SOP 的歷史設計脈絡。這些文件「留著是對的」，但必須被視為歷史資料；其中的下一步、進行中、Gate 或階段描述若與核心權威文件衝突，以核心權威文件為準。

## 文檔列表與目前處置

| 文件 | 目前處置 | 用途 |
|---|---|---|
| `PHASE2_ARCHITECTURE.md` | 保留為 Historical / Reference | Phase 2 策略架構設計追溯。 |
| `PHASE2_STRATEGY_LIBRARY.md` | 保留為 Historical / Reference | Phase 2 策略資料庫設計追溯。 |
| `PHASE_2A_DATA_SOURCES_AUDIT.md` | 保留為 Historical / Reference | CSV-first 到 DB-first 過渡盤點；目前資料架構以 `../01_architecture/system_architecture.md` 與 `../03_data/` 文件為準。 |
| `PHASE2_5_COMPLETION_STATUS.md` | 保留為 Historical / Reference | Phase 2.5 完成狀態追溯；fixed / quantile 現況以 Snapshot / 6M Roadmap / QA 報告為準。 |
| `PHASE3_3B_RESEARCH_DESIGN.md` | 保留為 Historical / Reference | Research Lab / Promote 早期設計脈絡；目前 Research Run Registry / lifecycle gate 以核心文件與架構文件為準。 |
| `EPIC2_MVP2_ARCHITECTURE_DESIGN.md` | 保留為 Historical / Reference | 過擬合風險提示早期架構設計。 |
| `EPIC2_MVP2_IMPLEMENTATION_CHECKLIST.md` | 保留為 Historical / Reference | 過擬合風險提示實作 checklist 追溯。 |
| `PHASE4_PORTFOLIO_DESIGN.md` | 保留為 Historical / Reference | Portfolio MVP 初始設計；目前 Portfolio / lifecycle 狀態以 Snapshot、Architecture 與 Manual 為準。 |
| `PHASE4_STARTUP_SUMMARY.md` | 保留為 Historical / Reference | Phase 4 啟動摘要追溯。 |
| `phase3_5_research/` | 保留為 Historical SOP / Reference | 研究流程、指標判讀與 Phase 4 entry gate 的歷史 SOP；若要變成日常操作規範，需另行改寫到 `../07_guides/` 或 `../02_features/`。 |

已歸檔的相關文件：

- [PHASE_3_3B_IMPLEMENTATION_PLAN.md](../09_archive/PHASE_3_3B_IMPLEMENTATION_PLAN.md)：Phase 3.3b 實施規劃，已移至歸檔目錄並只作歷史追溯。

## 📁 子目錄

- **`phase3_5_research/`** - Phase 3.5 研究 SOP 歷史文檔
  - `RESEARCH_ITERATION_PLAYBOOK.md` - 研究迭代 SOP（Iteration Playbook）
  - `METRIC_INTERPRETATION_PRIORITY.md` - 指標判讀優先順序
  - `BENCHMARK_PRESENTATION.md` - 回測 Benchmark 對標呈現方式
  - `PHASE4_ENTRY_CRITERIA.md` - Phase 4 進入條件（Gate）

## 狀態判讀

- 目前狀態、本週優先事項與高風險區以 `../00_core/PROJECT_SNAPSHOT.md` 為準。
- 未來 6 個月工程路線以 `../00_core/ROADMAP_6M_ENGINEERING.md` 為準。
- Roadmap 入口、Next 摘要與歷史導引由 `../00_core/DEVELOPMENT_ROADMAP.md` 負責。
- Phase 3.3b、Phase 3.5 與 Phase 4 相關文件保留為設計與實作脈絡，不再代表目前未完成狀態。
- Phase 4 Portfolio 主要深化已完成；後續主線已從舊 Phase 敘事轉為 Post-V1 evidence-driven 版本節奏與 6M Roadmap。
- V1.1 / V1.2 / V1.3 / V1.4 v1 已完成；下一步是以 weekly evidence operations 與 history 累積多週覆盤證據，V2.0 才評估完整 Unified Decision Workbench。

## 🔗 相關目錄

- `../00_core/PROJECT_SNAPSHOT.md` - 目前狀態入口
- `../00_core/ROADMAP_6M_ENGINEERING.md` - 6 個月工程路線
- `../00_core/DEVELOPMENT_ROADMAP.md` - Roadmap Hub
- `../02_features/` - 功能文檔

## 更新記錄

- 2026-07-03：將本目錄重新定位為 Historical / Reference；保留文件但明確標示不作目前 roadmap、完成狀態或下一步依據。
