# Evidence Rehearsal Engineering Closeout（2026-07-14）

> **唯一 closeout 狀態：`engineering_rehearsal_complete`**。本文件只結束唯讀工程預演底座；不改寫 External Validation Register，亦不把任何 external、正式產品、資料來源接受或 ML promotion 狀態標成 `complete`。

## 範圍與結果

本次完成的工程底座以不可變 DTO、唯讀投影與受控 CLI 連接既有 replay、coverage、P0 source shadow、paper / health、ML shadow comparison 與 lineage 檢查。它的目的在於讓工程故障情境可重跑、可揭露，而不是建立第二套 registry、寫入正式資料或提供投資結論。

| 層級 | 已完成的工程能力 | 不代表 |
|---|---|---|
| `engineering_fixture` | fixture contract、coverage / quality / missingness / lineage 投影 | 真實資料或正式 Gate 證據 |
| `historical_replay_candidate` | PIT-bound historical replay 與 rollback reference | forward effectiveness |
| `shadow_comparison` | P0 / ML shadow comparison、outage 與 insufficient sample blocker | source acceptance 或 ML promotion |
| `forward_handoff_pending` | 明確轉交所需真實時間、授權與人工 Gate | forward handoff 已完成 |

Coverage 以 `CoverageMetric` 的 observed、missing、degraded、future-blocked 與 immature-label 分類呈現；13 個 P0 contract 即使沒有 ingestion 也必須可見為 missing，不得被誤標 accepted。`RehearsalArtifact` 的 `outage`、`insufficient`、`missing`、`degraded`、`blocked` 與 `insufficient_sample` 都會 fail closed；沒有 diagnostics 時同樣阻擋 Workbench 的預演狀態。

## 安全與資料邊界

- 只讀 engineering rehearsal；不寫 production DB、正式 Evidence / Recommendation artifact、scheduler、broker、action、promotion 或 Advice。
- replay、source shadow 與 ML comparison 都不是 forward evidence；Workbench 只顯示注入 DTO，沒有 apply / promote 控制。
- `available_date`、`as_of_date` 與決策日維持 PIT fail-closed；不足樣本一律 defer。
- CLI 僅可寫入明確指定且不在 `DATA_ROOT` 及其子目錄的 output root；輸出可重跑的 JSON / Markdown 報告與 forward handoff，但不寫入資料來源。

## 已知缺口與 forward handoff

以下項目仍只能在 [External Validation Register](GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md) 依其 owner、日期、artifact 與 completion rule 進行；本 closeout 不會自動推進其狀態：

1. 真實 weekly / multi-day / forward / paper / exit 時間證據，以及 backup、rollback、recovery 演練。
2. 每個 P0 source 的 license、quality、PIT、missing/outage 處置與具名人工 acceptance。
3. 真實 ML shadow days、revalidation、drift review、rule baseline 與 promotion review。
4. 正式 production scheduler / broker / auto-promotion / auto-exit 的 owner approval；目前全部維持禁止。

## Coverage Pass / Patch Pass

本 closeout 已覆蓋目前狀態、Roadmap Hub、6M engineering roadmap、QA closeout、文件索引與專案導航；現有 [System Architecture](../01_architecture/system_architecture.md) 保持 application-service / DTO / Qt thin-shell 邊界，既有 [Application Manual](../07_guides/APPLICATION_MANUAL.md) 的 Workbench 唯讀與 replay 安全限制仍適用。沒有改變使用者可執行的操作或參數，因此不另改寫 architecture / manual；受控 CLI 的操作入口維持在 [Evidence Rehearsal Runbook](../07_guides/EVIDENCE_REHEARSAL_RUNBOOK.md)。

## 驗證紀錄

本次工作樹驗證結果如下。QA raw output 不提交；下列命令是從 repository root 可完整重跑的 PowerShell closeout sequence。

| 檢查 | 結果 |
|---|---|
| Full pytest | `1997 passed`（24 個既有 warning） |
| 指定 UI pytest | `59 passed` |
| Update Tab QA | `23 passed / 0 failed / 4 skipped` |
| 全模組 mypy | `406 source files` 無 issue |
| UTF-8 encoding | 661 files；0 invalid UTF-8、0 mojibake warning |
| 相對 Markdown links / active index | 345 files 均可解析；closeout 已列入 Documentation Index |
| Quant guard / Look-ahead | 全部通過 |
| ML shadow boundary | 351 files，0 violation，`shadow_only=true` |
| Gate 2–7 verifier | engineering package `complete`、external validation `pending`、35/35 requirements；非 formal product closeout |
| 變更 Python `py_compile` / `git diff --check` | 全部通過 |

### 可重跑 PowerShell closeout sequence

```powershell
$ErrorActionPreference = "Stop"

function Invoke-Verification {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed with exit code $LASTEXITCODE"
    }
}

Invoke-Verification { .\.venv\Scripts\python.exe -m pytest -q -o addopts= }
Invoke-Verification { .\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py tests\test_ui_qt_workbench_view.py -q -o addopts= }
Invoke-Verification { .\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py }
Invoke-Verification { .\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime }
Invoke-Verification { .\.venv\Scripts\python.exe scripts\audit_document_encoding.py --root . --fail-on-mojibake }

@'
from pathlib import Path
import re

root = Path.cwd()
files = [*root.joinpath("docs").rglob("*.md"), root / "PROJECT_NAVIGATION.md"]
pattern = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")
missing = []
for path in files:
    for target in pattern.findall(path.read_text(encoding="utf-8")):
        target = target.split("#", 1)[0].strip()
        if target and "://" not in target and not target.startswith("mailto:") and not (path.parent / target).resolve().exists():
            missing.append(f"{path.relative_to(root)} -> {target}")
if missing:
    raise SystemExit("missing relative markdown links:\n" + "\n".join(missing))
print(f"relative_markdown_links_ok={len(files)} files")
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw "Relative Markdown link verification failed" }

Invoke-Verification { rg -n "EVIDENCE_REHEARSAL_ENGINEERING_CLOSEOUT_2026_07_14" docs\00_core\DOCUMENTATION_INDEX.md }
Invoke-Verification { .\.venv\Scripts\python.exe scripts\quant_guard_linter.py }
Invoke-Verification { .\.venv\Scripts\python.exe scripts\check_ml_shadow_boundary.py }
New-Item -ItemType Directory -Force output\qa | Out-Null
Invoke-Verification { .\.venv\Scripts\python.exe scripts\verify_gate_2_to_7_closeout.py --output output\qa\task9_gate_2_to_7_closeout.json }
Invoke-Verification { .\.venv\Scripts\python.exe -m py_compile app_module\engineering_closure_dashboard_service.py app_module\historical_evidence_replay.py qa\full_app_healthcheck\test_inventory.py tests\test_engineering_closure_dashboard_service.py tests\test_full_app_healthcheck_test_inventory.py tests\test_ui_qt_workbench_view.py }
Invoke-Verification { git diff --check }
```

`output\qa\task9_gate_2_to_7_closeout.json` 與 Update Tab QA 產物都是 ignored local output，不能 stage 或提交。Gate verifier 的 `--output` 是必要參數；其 output 的 engineering package 結果不會覆寫 external register 狀態。
