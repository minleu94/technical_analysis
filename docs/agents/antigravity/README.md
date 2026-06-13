# Antigravity Agent 入口

> 給 Antigravity 使用的角色分流入口。專案權威仍維護在 `docs/agents/` 與 `docs/00_core/`。

## 先讀什麼

Antigravity 開工前依序閱讀：

1. `GEMINI.md`
2. `docs/agents/README.md`
3. `docs/agents/shared_context.md`
4. `docs/agents/git_exclusions.md`
5. `docs/00_core/PROJECT_SNAPSHOT.md`
6. `docs/00_core/DEVELOPMENT_ROADMAP.md`（Roadmap Hub）
7. 任務涉及方向、架構或中高風險時讀 `docs/00_core/ROADMAP_6M_ENGINEERING.md`
8. 任務涉及舊工作承接、Phase Gate 或優先順序時讀 `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md`
9. 任務涉及架構、資料流或模組邊界時讀 `docs/01_architecture/system_architecture.md`
10. 任務涉及 UI、使用流程、參數、結果判讀或安全限制時讀 `docs/07_guides/APPLICATION_MANUAL.md`
11. 本目錄中與任務對應的角色文件

## 角色選擇

| 任務類型 | 使用角色文件 | 原始權威文件 |
|---|---|---|
| 架構判斷、是否該做、風險評估 | `tech_lead_agent.md` | `docs/agents/tech_lead.md` |
| 功能實作、Bug 修復、測試補強 | `execution_agent.md` | `docs/agents/execution_agent.md` |
| 文檔 Coverage、索引與 Snapshot / Roadmap Hub / 6M Roadmap / Carryover / Architecture / Manual 同步 | `documentation_agent.md` | `docs/agents/documentation_agent.md` |
| 資料完整性、資料對比、資料品質 | `data_audit_agent.md` | `docs/agents/data_audit_agent.md` |
| 清理、移除、整理、未使用檔案判斷 | `data_cleanup_agent.md` | `docs/agents/data_cleanup_agent.md` |

## 使用方式

在 Antigravity 中開新任務時，直接貼上：

```text
請依照 GEMINI.md 與 docs/agents/antigravity/README.md 工作。
本次任務類型是：[Tech Lead / Execution / Documentation / Data Audit / Cleanup]。
請先閱讀必讀文件，再執行任務。
```

## 跨工具協作原則

- Codex、Antigravity 與使用者可能同時留下未提交變更；任何 Agent 都不得覆寫非自己產生的變更。
- 若任務要平行開發，優先使用獨立 branch 或 worktree。
- 若只是在同一個根目錄輪流切換工具，先確認目前工具已停止工作，再交給下一個工具。
