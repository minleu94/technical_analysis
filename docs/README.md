# Docs 文檔目錄

> **最後整理**：2026-08-30
> **權威判讀**：目前狀態看 `00_core/PROJECT_SNAPSHOT.md`，未來 6 個月看 `00_core/ROADMAP_6M_ENGINEERING.md`，V2.0 之後長期版號階梯看 `00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`，外部參考與 V1.5-V2.0 版本形狀看 `00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`，架構看 `01_architecture/system_architecture.md`，索引只負責導航。
> **本輪盤點**：[2026-08-30 程式現況重估](06_qa/PROGRAM_STATUS_REBASELINE_2026_08_29.md)；[release_v4 儲存清理與保留鏈](06_qa/ML_RELEASE_V4_STORAGE_RETENTION_CLEANUP_2026_08_29.md)；P0／Evidence／Paper／Formal／Runtime／Data Update 的 fresh handoff 入口見 [Documentation Index](00_core/DOCUMENTATION_INDEX.md)。
> **系統整合入口**：跨流 adapter 位於 `app_module/system_execution_blueprint_adapters.py`，純驗證入口位於 `scripts/verify_system_execution_blueprint.py`。兩者只組合／驗證既有輸出；任一 evidence、data、ML、dashboard 或 latency 契約失敗時，必須回到對應 owner 修正，不得在整合層補值或放寬 Gate。

本目錄是專案文件的主要入口。文件已依用途分區，日常查找請優先使用：

1. [專案快照](00_core/PROJECT_SNAPSHOT.md) - 30 秒讀完的目前狀態、本週優先事項與高風險區
2. [6 個月工程路線](00_core/ROADMAP_6M_ENGINEERING.md) - 未來 6 個月的可執行工程計畫
3. [Roadmap Hub](00_core/DEVELOPMENT_ROADMAP.md) - Roadmap 入口與權威文件導覽
4. [V1.1 至 V2.0 版本路線圖](00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md) - V1 release 後的版本化交付節奏
5. [V2.1 至 V4.0 版本路線圖](00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md) - V2.0 之後的長期版號階梯與成熟度邊界
6. [外部參考與未來版本藍圖](00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md) - 外部開源專案參考、資料源優先序與 V1.5-V2.0 版本形狀
7. [舊 Roadmap 移交矩陣](00_core/LEGACY_ROADMAP_CARRYOVER.md) - 舊版未完成事項的新位置與驗收條件
8. [完整操作手冊](07_guides/APPLICATION_MANUAL.md) - 8 個工作區、跨頁流程、安全限制與排錯
9. [文檔索引](00_core/DOCUMENTATION_INDEX.md) - 所有保留文檔的導航
10. [文檔結構與維護規則](00_core/DOCUMENTATION_STRUCTURE.md) - 資料夾歸屬、刪除與歸檔規則
11. [文檔覆蓋矩陣](00_core/DOC_COVERAGE_MAP.md) - 文件更新時要同步哪些文檔

---

## 目錄歸屬

| 目錄 | 用途 | 狀態 |
|---|---|---|
| `00_core/` | snapshot、6 個月 roadmap、長期版本階梯、Roadmap Hub、索引、coverage 規則 | 必讀 |
| `01_architecture/` | 系統架構、資料流、Runtime 規範、多 Agent 工作流、UI 設計系統 | 長期維護 |
| `02_features/` | UI、使用者指南、回測、評分、策略規格 | 使用者與功能說明 |
| `03_data/` | 每日資料、資料流、重建與故障排除、基本面來源盤點 | 資料更新操作 |
| `04_broker_branch/` | 券商分點資料與 Smart Money 前置資料 | 籌碼資料專區 |
| `05_phases/` | 歷史 Phase 設計、Phase 3.5 SOP 與 Phase 4 Portfolio 設計追溯 | Historical / Reference，不作目前 roadmap |
| `06_qa/` | QA 問題、總結、驗證與審核報告 | 驗證紀錄 |
| `07_guides/` | 快速開始、安裝、命令、腳本與測試說明 | 操作手冊 |
| `08_technical/` | 技術優化、參數設計、路徑/環境說明 | 技術備忘 |
| `09_archive/` | 已過期但仍有歷史價值的文件 | 不作日常依據 |
| `agents/` | Agent 職責、協作規範、上下文 | Agent 工作文件 |
| `governance/` | 預留給流程治理、決策紀錄或政策文件 | 目前無 Markdown 文件 |
| `strategies/` | 策略說明文件 | StrategyRegistry / 使用者理解 |
| `superpowers/` | Superpowers specs / plans 與 execution artifacts | Historical / Implementation Trace，不作目前 roadmap |

> Codex 自動讀取入口位於 repo 根目錄 `AGENTS.md`。`docs/agents/` 保留完整 Agent 架構與 Prompt 文件。

---

## 目前狀態摘要

- V1 release baseline 已完成：資料與市場狀態、研究驗證、持倉檢查、每日決策四個產品閉環已形成可操作基準。
- Post-V1 evidence-driven 主線已建立：Evidence Event Store、Forward Outcome、Evidence Importers、Forward Performance read model / dashboard、pipeline dry-run、Live vs Research Gap、Signal Decay、Decision Quality、Evidence Review dashboards、V1.3 weekly evidence operations 與 V1.4 weekly review history 都已具備 v1。
- V3.3 engineering foundation、Workbench 主 UI 與受控 evidence／Paper／ML shadow 工程入口已完成；目前進入 V4 evidence accumulation，整體 readiness 仍為 `action_required`，不是正式 V4.0。
- P0 為 13/13 machine evidence 但 accepted 0；Evidence formal credit 未授予；Paper 21/21 但 fills／cost 0；Formal inputs 0/3。Production Evidence／ML／broker writer 仍未啟用。
- 2026-08-29 retention cleanup 後 D 槽可用約 410.31 GiB，physical storage blocker 已解除；舊 low-space status 是歷史 artifact，且容量恢復不代表任何產品 Gate 通過。
- `docs/05_phases/` 保留歷史設計與研究 SOP 脈絡，但不再作目前 roadmap 或完成狀態依據。

詳細狀態以 [PROJECT_SNAPSHOT.md](00_core/PROJECT_SNAPSHOT.md) 為準；未來 6 個月方向以 [ROADMAP_6M_ENGINEERING.md](00_core/ROADMAP_6M_ENGINEERING.md) 為準；V2.0 之後長期版號階梯以 [VERSION_ROADMAP_V2_1_TO_V4_0.md](00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md) 為準；外部專案參考與 V1.5-V2.0 版本形狀以 [EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md](00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md) 為準。

---

## 快速閱讀路徑

### 第一次接觸

1. [PROJECT_SNAPSHOT.md](00_core/PROJECT_SNAPSHOT.md)
2. [ROADMAP_6M_ENGINEERING.md](00_core/ROADMAP_6M_ENGINEERING.md)
3. [DEVELOPMENT_ROADMAP.md](00_core/DEVELOPMENT_ROADMAP.md)
4. [VERSION_ROADMAP_V1_1_TO_V2_0.md](00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md)
5. [VERSION_ROADMAP_V2_1_TO_V4_0.md](00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md)
6. [EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md](00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md)
7. [DOCUMENTATION_INDEX.md](00_core/DOCUMENTATION_INDEX.md)
8. [system_architecture.md](01_architecture/system_architecture.md)

### 要查策略回測

1. [BACKTEST_LAB_FEATURES.md](02_features/BACKTEST_LAB_FEATURES.md)
2. [BACKTEST_LAB_CHECKLIST.md](02_features/BACKTEST_LAB_CHECKLIST.md)
3. [BACKTEST_LAB_FAQ.md](02_features/BACKTEST_LAB_FAQ.md)
4. [UI_QT_CHART_RENDERING.md](08_technical/UI_QT_CHART_RENDERING.md)

### 要使用系統

1. [APPLICATION_MANUAL.md](07_guides/APPLICATION_MANUAL.md)
2. [QUICK_START.md](07_guides/QUICK_START.md)
3. [USER_GUIDE.md](02_features/USER_GUIDE.md)
4. [UI_FEATURES_DOCUMENTATION.md](02_features/UI_FEATURES_DOCUMENTATION.md)
5. [HOW_TO_UPDATE_DAILY_DATA.md](03_data/HOW_TO_UPDATE_DAILY_DATA.md)

### 要開發或整理文件

1. [DOC_COVERAGE_MAP.md](00_core/DOC_COVERAGE_MAP.md)
2. [DOCUMENTATION_STRUCTURE.md](00_core/DOCUMENTATION_STRUCTURE.md)
3. [AGENT_CONTEXT.md](../AGENT_CONTEXT.md)
4. [PROJECT_NAVIGATION.md](../PROJECT_NAVIGATION.md)
5. [PROJECT_INVENTORY.md](../PROJECT_INVENTORY.md)

---

## 維護原則

- 不確定狀態時，先判斷主題：現在看 Snapshot，未來 6 個月路線看 6M Roadmap，V2.0 之後長期版號看 V2.1-V4.0 roadmap，架構看 system architecture。
- 新增、刪除或搬移文件後，必須更新 `00_core/DOCUMENTATION_INDEX.md`。
- 根目錄 `README.md` 保持使用者導向；Agent / 開發者上下文放在 `../AGENT_CONTEXT.md` 與 `agents/`。
- 會影響使用者操作、參數、結果判讀或安全限制的變更，必須同步 `07_guides/APPLICATION_MANUAL.md`；專題教學或功能說明再同步 `02_features/USER_GUIDE.md`、`02_features/UI_FEATURES_DOCUMENTATION.md`。
- 過期但仍有歷史價值的文件放入 `09_archive/`；沒有引用、沒有歷史價值、且內容已被新文件取代的文件可以刪除。
