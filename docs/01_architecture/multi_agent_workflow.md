# Multi-Agent Collaboration Workflow Protocol

This document defines the formal multi-agent collaboration workflow for the repository.

## Branch Roles

### `main`
* Production-like stable branch.
* 必須永遠可執行。
* 不允許直接開發。

### `ag/*` (Antigravity)
* Implementation branches.
* UI / feature / service integration.
* Additive change preferred.

### `codex/*` (Codex)
* Architecture / governance / review branches.
* Proposal / audit / migration design.
* 不直接假設 full rewrite。

### `research/*`
* Experimental ideas.
* 不保證 merge。

## Merge Protocol

任何 branch merge 前，必須檢查以下項目：

### 1. Compile / Runtime
* Application 可啟動。
* Imports 無循環依賴。
* DTO contract 未破壞。

### 2. Architecture Boundary
* `ui_qt` 不直接 import repository/db。
* `app_module` 不依賴 `ui_qt`。
* Domain logic 不回流 UI。

### 3. Merge Risk Analysis
在 Merge 前必須明確標示：
* Safe to merge
* Requires migration
* Breaking change
* Experimental only

### 4. Shared Contract Safety
**必須避免：**
* Rename shared DTO。
* Changing event payload schema。
* Changing service signatures。
* Hidden coupling。

## Conflict Resolution

如果 branch concept 發生衝突：
**絕對不要直接 rewrite 對方實作。**

而是必須依序：
1. 提出 Conflict explanation。
2. 提出 Migration path。
3. 提出 Compatibility adapter。
4. 提出 Phased transition plan。

## Development Principle

**優先：**
* Additive architecture
* Adapters
* Extension points
* Compatibility layer

**避免：**
* Destructive rewrite
* Hidden dependency
* Broad refactor without migration
* Silent contract breaking

## Git Workflow

推薦流程：

```text
main
  ↑
develop
  ↑
feature/ag/*
feature/codex/*
research/*
```

> **注意：**
> AI agents 不可自行 merge 到 `main`。
> 最終 merge decision 由 human architecture owner 決定。
