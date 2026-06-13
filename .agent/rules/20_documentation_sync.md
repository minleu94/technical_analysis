# Antigravity Rule 20 - Documentation Sync

## 適用時機

新增、修改或刪除功能、使用流程、架構、Agent 文件、Markdown 文件時套用。

## Coverage 規則

1. 讀 `docs/agents/antigravity/documentation_agent.md`。
2. 讀 `docs/00_core/DOC_COVERAGE_MAP.md`。
3. 先做 Coverage Pass：列出需要更新的文件、優先級、段落與原因。
4. 使用者確認後再做 Patch Pass，除非使用者明確要求直接更新。

## 必查文件

- `docs/00_core/PROJECT_SNAPSHOT.md`
- `docs/00_core/DEVELOPMENT_ROADMAP.md`
- `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`（涉及舊工作移交或 Gate 時）
- `docs/01_architecture/system_architecture.md`
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `docs/07_guides/APPLICATION_MANUAL.md`（涉及使用者可見流程、參數、結果或限制時）
- `PROJECT_NAVIGATION.md`
- 變更所屬功能文件，例如 `docs/02_features/BACKTEST_LAB_FEATURES.md`

## 權威判讀

- 目前狀態、Next、Risks 以 `docs/00_core/PROJECT_SNAPSHOT.md` 為準。
- 未來 6 個月工程路線以 `docs/00_core/ROADMAP_6M_ENGINEERING.md` 為準。
- Roadmap 入口與歷史導引由 `docs/00_core/DEVELOPMENT_ROADMAP.md` 負責。
- 舊 Roadmap 未完成事項的承接與 Gate 由 `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` 負責。
- 架構、資料流與模組邊界以 `docs/01_architecture/system_architecture.md` 為準。
- 目前操作流程、參數、結果判讀與安全限制以 `docs/07_guides/APPLICATION_MANUAL.md` 為準。

## 新增 Markdown 的硬規則

新增或刪除 Markdown 文件時，必須同步更新 `docs/00_core/DOCUMENTATION_INDEX.md`。

功能改變若會影響使用者操作、參數、結果判讀或安全限制，必須同步更新 `docs/07_guides/APPLICATION_MANUAL.md`；手冊至少涵蓋入口、步驟與參數、結果判讀、安全限制、常見排錯。
