# Agent / Developer Context

> **用途**：本檔是給 Codex、Antigravity 與專案開發者的高密度入口。使用者導向介紹請看 [README.md](README.md)；Codex 強制規則入口仍是 [AGENTS.md](AGENTS.md)。

## 專案定位

baldr 是一套可驗證、可回溯、可演化的台股研究與投資決策工作台。核心不是「每天吐股票」，而是把資料、研究、回測、候選、持倉與策略生命週期串成可檢查的決策流程。

## 目前狀態（2026-08-30）

目前為 `V3.3 Engineering Complete / V4 Evidence Accumulation`，整體 readiness=`action_required`，
不是正式 V4.0 Production。開始工作前先讀
[Program Status Rebaseline](docs/06_qa/PROGRAM_STATUS_REBASELINE_2026_08_29.md)；涉及
`FA_Data/output/release_v4` 時再讀
[Storage Retention Cleanup](docs/06_qa/ML_RELEASE_V4_STORAGE_RETENTION_CLEANUP_2026_08_29.md)，
不可依舊 low-space artifact 或已刪 run 路徑推論現在狀態；8/30 fresh inventory 觀察到
約 `338.9 GiB` headroom，Direct/OOC 僅以 `--preflight-only` 做安全檢查，未啟動長任務。

## 分支與工作流

| 分支 | 用途 |
|---|---|
| `main` | 乾淨可 clone 版本，保留必要文件、程式碼、測試與範例。 |
| `dev` | 日常開發主線，延續目前進行中的 healthcheck、UI smoke、文件與功能深化。 |
| `codex/*` / `feature/*` | 短期任務分支，完成合併後清理。 |

不要把本機輸出、QA artifact、SQLite DB、log、暫存資料或正式資料根目錄內容提交到 `main`。

## 必讀順序

1. [AGENTS.md](AGENTS.md) - Codex repo 指令入口。
2. [docs/agents/README.md](docs/agents/README.md) - Agent 總覽與強制流程。
3. [docs/agents/shared_context.md](docs/agents/shared_context.md) - 全 Agent 共用規範。
4. [docs/agents/git_exclusions.md](docs/agents/git_exclusions.md) - 不應提交清單。
5. [docs/00_core/PROJECT_SNAPSHOT.md](docs/00_core/PROJECT_SNAPSHOT.md) - 目前狀態、高風險區與工作模式。
6. [docs/00_core/DEVELOPMENT_ROADMAP.md](docs/00_core/DEVELOPMENT_ROADMAP.md) - Roadmap Hub。
7. [docs/00_core/ROADMAP_6M_ENGINEERING.md](docs/00_core/ROADMAP_6M_ENGINEERING.md) - 未來 6 個月工程路線。
8. [docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md](docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md) - V2.0 之後長期版本階梯（涉及 V2 之後版本命名或長期成熟度時）。
9. [docs/00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md](docs/00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md) - 外部專案參考、資料源優先序與 V1.5-V2.0 版本形狀（涉及方向或版本規劃時）。
10. [docs/01_architecture/system_architecture.md](docs/01_architecture/system_architecture.md) - 架構與模組邊界。
11. [docs/07_guides/APPLICATION_MANUAL.md](docs/07_guides/APPLICATION_MANUAL.md) - 使用者操作權威。
12. 與任務對應的 Agent 文件，例如 `execution_agent.md`、`documentation_agent.md`、`data_cleanup_agent.md`。

## Scoped SSOT

| 主題 | 權威文件 |
|---|---|
| 目前狀態 / 高風險區 | `docs/00_core/PROJECT_SNAPSHOT.md` |
| 未來 6 個月工程路線 | `docs/00_core/ROADMAP_6M_ENGINEERING.md` |
| V2.0 之後長期版本階梯 | `docs/00_core/VERSION_ROADMAP_V2_1_TO_V4_0.md` |
| 外部參考 / V1.5-V2.0 版本形狀 | `docs/00_core/EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md` |
| Roadmap 入口 | `docs/00_core/DEVELOPMENT_ROADMAP.md` |
| 舊 Roadmap 移交 | `docs/00_core/LEGACY_ROADMAP_CARRYOVER.md` |
| 架構 / 模組邊界 | `docs/01_architecture/system_architecture.md` |
| 使用者操作 | `docs/07_guides/APPLICATION_MANUAL.md` |
| 文件索引 | `docs/00_core/DOCUMENTATION_INDEX.md` |
| 文件生命週期 | `docs/00_core/DOCUMENTATION_STRUCTURE.md` |

## 主要入口與模組

- 主 UI：`ui_qt/main.py`
- Application services：`app_module/`
- Decision domain：`decision_module/`
- Backtest engine：`backtest_module/`
- Portfolio domain：`portfolio_module/`
- Runtime：`runtime/`
- Data / SQLite / config：`data_module/`
- QA / maintenance scripts：`scripts/`

## 高風險規則

- 不刪除或破壞正式資料根目錄。資料位置以 `TWStockConfig` / `DATA_ROOT` 為準。
- 策略、回測、推薦、資金、倉位、風控與績效不可新增裸 `float` 核心計算。
- 涉及策略、回測、推薦、績效、風控時，先做 Look-ahead bias 自查。
- UI 不直接重算 scoring、screening、broker flow、portfolio 或 Daily Decision Desk domain logic。
- Stage / commit 前先看 `docs/agents/git_exclusions.md`，並確認 `git status --short` 只包含本任務檔案。

## 常用驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

金融核心修改另跑：

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

## 更新記錄

- 2026-08-29：補入目前 maturity、七 lane rebaseline 與 release_v4 retention custody 入口。
- 2026-07-06：補上 V2.0 之後長期版本階梯 companion 入口，供 Agent 在 V2.1-V4.0 規劃時定位 `VERSION_ROADMAP_V2_1_TO_V4_0.md`。
- 2026-07-04：補上外部專案參考與 V1.5-V2.0 版本形狀 companion 入口，供 Agent 在方向規劃時定位 `EXTERNAL_REFERENCE_VERSION_BLUEPRINT.md`。
- 2026-06-30：從根目錄 README 拆出 Agent / Developer 上下文，使 `README.md` 可作為乾淨使用者入口。
