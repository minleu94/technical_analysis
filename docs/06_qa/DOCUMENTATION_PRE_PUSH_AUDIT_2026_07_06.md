# Docs Pre-push Governance Audit（2026-07-06）

> **稽核日期**：2026-07-06
> **範圍**：`docs/` 全目錄 Markdown、主要 README / Index、Archive placement、Superpowers specs / plans、策略說明與技術備忘位置。
> **定位**：本文件是 push 前文檔治理稽核紀錄，不取代 `PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、版本 roadmap 或 Architecture。

## 稽核結論

本輪 docs 結構整體可維持，不需要大規模重組或刪除。需要修補的是：

1. 部分文件缺少資料夾入口或索引入口。
2. 一份舊 QA roadmap audit 放在 active QA 區會誤導目前狀態。
3. 一份 MCP patch memo 放在 `docs/agents/`，不符合 Agent 角色文件歸屬。
4. 少量歷史文件與 plan/spec 內部連結仍指向舊位置或本機絕對路徑。

已完成整理：

- 新增 `docs/superpowers/README.md`，將 `specs/`、`plans/` 明確定位為 Historical / Implementation Trace。
- 新增 `docs/strategies/README.md`，說明策略說明文件與 StrategyRegistry / strategy code 的邊界。
- 將 `docs/06_qa/UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md` 歸檔為 `docs/09_archive/UI_QT_DEVELOPMENT_ROADMAP_AUDIT_2026_05_19.md`。
- 將 `docs/agents/PATCH_MEMO.md` 移至 `docs/08_technical/MCP_YFINANCE_OPENMARKETS_PATCH_MEMO.md`。
- 補上 `RESEARCH_RUN_REGISTRY_SPEC.md`、`POST_V1_FORWARD_PERFORMANCE_READ_MODEL_QA_2026_07_03.md` 與本文件的索引。
- 修正舊的本機 `c:/Projects/...` 絕對 file-scheme 連結為 repo 內相對路徑。
- 修正 `docs/superpowers/plans/` 中錯誤的 `../superpowers/...` 自我參照。

## Archive 判斷

| 文件 | 決策 | 理由 |
|---|---|---|
| `docs/06_qa/UI_QT_DEVELOPMENT_ROADMAP_AUDIT.md` | 移入 `09_archive/` | 2026-05-19 舊 roadmap 對照內含已過時狀態，例如 Portfolio UI 未完成；保留追溯價值，但不應放 active QA。 |
| `docs/09_archive/DOCUMENTATION_UPDATE_SUMMARY.md` | 留在 archive | 2025-12 文檔整理歷史仍有脈絡價值；已補 archive 判讀並修正舊連結至目前對應入口。 |
| `docs/05_phases/` | 不整包搬 archive | 既有 structure 已將其定義為 Historical / Reference，且 active docs 仍引用 Phase 設計脈絡；目前不做大搬移。 |
| `docs/superpowers/` | 不搬 archive | 數量大且屬實作軌跡；以 README 降權與索引重點文件即可。 |
| `docs/08_technical/RUN_WITHOUT_VENV.md` | 暫留 technical | 是 fallback 技術備忘，不是 active install authority；未確認完全失效前不歸檔。 |

## 版本治理判斷

目前不新增獨立 `RELEASE_VERSION_POLICY.md` 或版本控制政策文件。原因：

- V1 release 後至 V2.0 的交付節奏已有 `docs/00_core/VERSION_ROADMAP_V1_1_TO_V2_0.md`。
- V2.0 之後的版本階梯已有 `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md`。
- 未來 6 個月工程 gate 仍以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準。
- 本次新增的稽核文件已足夠記錄 push 前文檔位置與生命週期判斷。

若未來開始頻繁建立正式 Git release tag、release note 或 semver gate，再評估新增 `docs/00_core/RELEASE_VERSION_POLICY.md`。

## 後續維護規則

- 新增 active Markdown 時，更新 `docs/00_core/DOCUMENTATION_INDEX.md` 與對應資料夾 README。
- 大量 Superpowers plan/spec 不需逐一搬 archive，但仍需由 `docs/superpowers/README.md` 降權。
- 歷史文件若保留 markdown link，應優先指向目前存在的對應入口；若只是本機 raw output，改為 code path 並註明非 repo 文檔入口。
- `docs/agents/` 只放 Agent 職責、協作、Prompt 與上下文；工具 patch、環境修補與本機 MCP 備忘應放 `docs/08_technical/`。

## 驗證紀錄

本輪整理後已完成以下檢查：

| 項目 | 結果 |
|---|---|
| Markdown 檔案數 | `269` |
| Markdown relative links | `checked_relative_links=504`，`missing_count=0` |
| 本機 file-scheme 絕對連結 | `0` |
| `docs/superpowers/plans/` 錯誤 `../superpowers/...` 連結 | `0` |
| `git diff --check` | 通過；僅顯示 Windows `LF will be replaced by CRLF` 提示，無 whitespace error。 |
| `scripts/audit_document_encoding.py` | `scanned_files=430`，`invalid_utf8=0`，`mojibake_warnings=1`。唯一警告為既有 `docs/04_broker_branch/BROKER_BRANCH_TESTING_AND_TROUBLESHOOTING.md:71`，非本次新增問題。 |

Markdown 目錄分布：

| 目錄 | Markdown 數 |
|---|---:|
| `00_core/` | 12 |
| `01_architecture/` | 9 |
| `02_features/` | 9 |
| `03_data/` | 11 |
| `04_broker_branch/` | 6 |
| `05_phases/` | 15 |
| `06_qa/` | 45 |
| `07_guides/` | 8 |
| `08_technical/` | 7 |
| `09_archive/` | 14 |
| `agents/` | 21 |
| `strategies/` | 3 |
| `superpowers/` | 108 |
| `docs/README.md` | 1 |
