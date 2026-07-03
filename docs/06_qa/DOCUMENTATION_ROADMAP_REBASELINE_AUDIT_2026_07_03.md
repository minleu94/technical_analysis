# Documentation / Roadmap Rebaseline Audit（2026-07-03）

> **範圍**：本稽核整理 roadmap、docs 入口與 `docs/05_phases/` 判讀邊界。
> **結論**：`docs/05_phases/` 保留是對的，但必須明確降格為 Historical / Reference；目前 roadmap 只看 core scoped authority 與 Post-V1 version roadmap。

## 1. 稽核結論

本次盤點確認專案已從舊線性 Phase 規劃轉為 Scoped SSOT 與 Post-V1 version cadence：

- 目前狀態：`docs/00_core/PROJECT_SNAPSHOT.md`
- 未來 6 個月工程路線：`docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Roadmap 入口：`docs/00_core/DEVELOPMENT_ROADMAP.md`
- V1.1 至 V2.0 版本節奏：`docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`
- 架構邊界：`docs/01_architecture/system_architecture.md`
- 使用流程：`docs/07_guides/APPLICATION_MANUAL.md`

`docs/05_phases/` 仍有歷史價值與 Active 文件引用，因此本輪不刪除、不搬移。整理方式是：

1. 更新 `docs/05_phases/README.md`，將整個目錄定位為 Historical / Reference。
2. 在每個 Phase / SOP 文件開頭加入歷史判讀提示。
3. 更新 `DOCUMENTATION_INDEX.md`、`DOCUMENTATION_STRUCTURE.md`、`docs/README.md`、Roadmap Hub、AI context、Project Inventory 與 Project Navigation，避免把 Phase 文件誤讀為目前 roadmap。

## 2. Coverage Pass

| 文件 | 優先級 | 處置 | 原因 |
|---|---|---|---|
| `docs/README.md` | Must | 更新 `docs/` 入口與目錄狀態 | docs 首頁必須反映 Post-V1 與 phase 目錄降格。 |
| `docs/00_core/DOCUMENTATION_STRUCTURE.md` | Must | 更新 `05_phases/` 生命週期與整理決策 | 文檔結構規則是刪除 / 歸檔 / 保留判斷權威。 |
| `docs/00_core/DOCUMENTATION_INDEX.md` | Must | 更新 phase 區標題、用途與本 audit 索引 | Index 必須反映所有新增與重新定位文件。 |
| `docs/00_core/DEVELOPMENT_ROADMAP.md` | Must | 補充 phase 目錄的歷史判讀 | Roadmap Hub 需要明確說明舊 phase 不作目前 roadmap。 |
| `docs/05_phases/README.md` | Must | 改寫為 Historical / Reference 入口 | 使用者明確詢問 phase 目錄是否過時。 |
| `docs/05_phases/**/*.md` | Should | 加入歷史判讀提示 | 避免單獨開啟個別 Phase 文件時誤判。 |
| `docs/00_core/AI_CONTEXT_PACK.md` | Should | 同步 Post-V1 / V1.4 現況 | 外部 AI / Agent 常用入口，不能停留在 Month 6 舊狀態。 |
| `PROJECT_INVENTORY.md` | Should | 同步 docs 目錄與目前主線 | 根目錄盤點需反映目前 docs 定位。 |
| `PROJECT_NAVIGATION.md` | Should | 同步 roadmap 判讀與修正舊架構路徑 | 新接手工程師需避免沿用舊 phase 或舊路徑。 |

## 3. Phase 目錄判定

| 類別 | 判定 | 後續建議 |
|---|---|---|
| Phase 2 / Phase 2A / Phase 2.5 | Historical / Reference | 保留於 `05_phases/`，不得作目前 roadmap；若未來搬移，需同步所有引用。 |
| Phase 3.3b | Historical / Reference | 保留 Research Lab / Promote 早期設計脈絡；目前 registry / lifecycle 以 core docs 為準。 |
| Phase 3.5 research SOP | Historical SOP / Reference | 若要重新啟用為日常 SOP，應改寫到 `docs/07_guides/` 或 `docs/02_features/`。 |
| Phase 4 Portfolio | Historical / Reference | 保留 Portfolio MVP 初始設計；目前 Portfolio / lifecycle 以 Snapshot、Architecture、Manual 為準。 |
| Epic 2 MVP-2 | Historical / Reference | 保留過擬合風險提示設計脈絡；目前可信度治理以 Post-V1 / Research Credibility docs 為準。 |

## 4. 不做事項

- 不刪除 `docs/05_phases/`。
- 不搬移 Phase 文件到 `09_archive/`，避免一次性破壞大量相對連結。
- 不把 Phase 文件內容重寫成目前狀態；歷史文件只加判讀提示。
- 不修改程式碼、資料、SQLite、QA raw output 或正式資料根目錄。

## 5. 後續整理準則

若未來要進一步壓縮 docs：

1. 先檢查 `rg "docs/05_phases|05_phases|PHASE2|PHASE3|PHASE4|EPIC2" .`。
2. 對仍被 Active 文件引用的文件，先改引用到新的權威文件或保留 redirect。
3. Phase 3.5 SOP 若仍有操作價值，先改寫到 `docs/07_guides/` 或 `docs/02_features/`。
4. 完成引用遷移後，再分批移入 `docs/09_archive/phase_legacy/`。
5. 每批搬移都要同步 `DOCUMENTATION_INDEX.md`、`DOCUMENTATION_STRUCTURE.md` 與相關 README。

## 6. 驗證建議

本輪屬文件整理，建議驗證：

```powershell
rg -n "docs/architecture/runtime|接續主線是全 UI 健檢|Phase 設計與研究 SOP \\| 階段規劃|Phase 開發階段相關文檔" docs PROJECT_NAVIGATION.md PROJECT_INVENTORY.md --glob "!docs/06_qa/DOCUMENTATION_ROADMAP_REBASELINE_AUDIT_2026_07_03.md" --glob "!docs/05_phases/README.md"
rg -n "Historical / Reference|歷史判讀" docs/05_phases docs/00_core/DOCUMENTATION_INDEX.md docs/README.md
git status --short
```

若後續改成搬移 / 刪除文件，需額外做 Markdown relative link 檢查。
