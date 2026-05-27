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
- `docs/00_core/DOCUMENTATION_INDEX.md`
- `PROJECT_NAVIGATION.md`
- 變更所屬功能文件，例如 `docs/02_features/BACKTEST_LAB_FEATURES.md`

## 新增 Markdown 的硬規則

新增或刪除 Markdown 文件時，必須同步更新 `docs/00_core/DOCUMENTATION_INDEX.md`。
