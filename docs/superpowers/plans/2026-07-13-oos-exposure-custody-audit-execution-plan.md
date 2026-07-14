# 2025 OOS Exposure／Custody Audit Execution Plan

> 狀態：可交付 Terra 的第一個受控執行切片；不是 audit 結果，也不授權 formal OOS
>
> 上位設計：[External Evidence Design](../specs/2026-07-13-external-evidence-investment-validation-design.md)
>
> Master Plan：[External Evidence Master Plan](2026-07-13-external-evidence-investment-validation-master-plan.md)
>
> Terra 交接：[Execution Handoff and Prompt Pack](../prompts/2026-07-13-terra-external-evidence-execution-handoff.md)

## 1. 唯一目標

實作一個不讀取 2025 outcome values 的 pure audit 能力，依 machine evidence 與具名人工聲明產生 `OOSExposureCustodyReport.v1`。本切片只回答「2025 是否曾暴露或影響設計」；不建立 dataset、不重訓、不比較 Rule／ML、不解封 OOS、不改 `formal_oos_allowed`。

## 2. Scope

### In

- 建立 `ml_module/oos_exposure_custody.py`。
- 建立 `scripts/audit_ml_oos_exposure.py`。
- 建立 `tests/test_ml_oos_exposure_custody.py`、`tests/test_ml_oos_exposure_cli.py`。
- 只讀 Git metadata、manifest metadata、artifact/access inventory、既有 CLI invocation metadata 與 signed declaration。
- 輸出 canonical JSON report 與 handoff hash。

### Out

- 2025 outcome payload、return、metric、ranking 或 comparison 的讀取與摘要。
- dataset/model generation、fit、calibration、threshold、feature、label、universe 或 Rule 變更。
- production DB、正式 market data、evidence DB、scheduler、broker、promotion 或 UI 修改。
- External Gate revision、Snapshot／Roadmap status 或 formal product closeout 更新。

## 3. 啟動 Hard Gates

全部成立才可進入 RED test：

1. branch=`dev`、`HEAD == origin/dev`、working tree/index clean。
2. `git merge-base --is-ancestor 4f72766a1d1e7bd4b80ccb595ad3cb2fa84bd84a HEAD` exit 0；`4f72766` 只作 A～G 工程錨點。
3. ignored preflight record 保存 `execution_baseline_sha`、UTC timestamp、worker identity、允許路徑與禁止路徑。
4. Terra 不操作 Git index/history/remote；只回傳 ready files、hash、tests 與 blockers。
5. CLI contract 不接受 `--oos-payload`、outcome DB、return report 或任何會讀 2025 outcome values 的參數。
6. 所有輸出只寫 `%TEMP%` 或明確 isolated output；正式資料 root 前後不得改變。
7. 缺 signed declaration 或 machine evidence 時，合法結果只能是 `indeterminate`，不得以 Agent 推測補齊。

## 4. 允許與禁止的證據

| 類別 | 允許 | 禁止 |
|---|---|---|
| Git | commit metadata、path history、command history evidence ID | 從 Git artifact 解包並閱讀 2025 outcome values |
| Manifest | identity、hash、created/frozen time、parent IDs、access-log pointer | payload contents、returns、labels 或 model performance |
| Report | 檔名、hash、mtime、owner、access event、生成命令 | 開啟可能暴露 2025 結果的 report body |
| Human | 具名 signed declaration 與 timestamp | Agent 代簽、預填「未看過」或替人類判定設計影響 |
| Runtime | bounded metadata inventory、read-only path checks | production write、retrain、evaluation、comparison |

若無法只讀 metadata 而不暴露內容，將該 evidence 記為 unavailable，狀態維持 `indeterminate`。

## 5. 狀態判定

優先序固定如下：

1. `seen_oos`：2025 曾影響 Feature、Label、Universe、Rule、threshold、model family、hyperparameter、calibration、blend、sample filter 或 success criteria。
2. `exposed_no_design_influence_declared`：有暴露證據，具名聲明宣告未影響；只能 retrospective OOS，永久不得稱 virgin／untouched。
3. `custody_verified_unopened`：machine evidence、access inventory 與 signed declaration 全部支持未開啟、未影響。
4. `indeterminate`：證據缺失、互相矛盾、無法安全檢查或缺簽署聲明。

只有第 3 種狀態可讓後續 verifier「候選」formal locked OOS；本 audit 本身仍不得把 `formal_oos_allowed` 改為 true。

## 6. 執行順序

### Step 0 — Coordinator preflight

- 記錄動態 execution baseline 與 allowed paths。
- 以 `rg`／Git metadata 建立 candidate artifact inventory；不開啟 2025 payload。
- 若發現工作樹不乾淨、來源不明或可能讀 outcome 的命令，停止並回報。

### Step 1 — RED tests

至少覆蓋：threshold influence→`seen_oos`、missing declaration→`indeterminate`、exposed/no influence→retrospective-only、完整未暴露證據→candidate unopened、CLI 拒絕 outcome payload 參數、canonical hash deterministic。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_oos_exposure_custody.py tests/test_ml_oos_exposure_cli.py -q -o addopts=
```

第一次執行應因 module／CLI 尚不存在而 RED；若意外通過，停止檢查未交接變更。

### Step 2 — Pure auditor

- 使用 frozen dataclass／Literal statuses。
- 對輸入做 identity、時間、hash、空值與 influence-dimension 驗證。
- 不 import dataset builder、trainer、formal evaluator 或 production repository。
- canonical serialization 不包含主機秘密、絕對正式資料路徑或 outcome values。

### Step 3 — Read-only CLI

- 僅接受 generation manifest metadata、access evidence inventory、signed declaration 與 explicit `--output`。
- 預設不建立 parent outside isolated root；拒絕 production-like output path。
- stdout 明示 `oos_payload_read=false`、`training_performed=false`、`formal_oos_changed=false`。

### Step 4 — GREEN verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ml_oos_exposure_custody.py tests/test_ml_oos_exposure_cli.py -q -o addopts=
.\.venv\Scripts\python.exe -m mypy ml_module/oos_exposure_custody.py scripts/audit_ml_oos_exposure.py
.\.venv\Scripts\python.exe scripts/check_ml_shadow_boundary.py
.\.venv\Scripts\python.exe scripts/quant_guard_linter.py
```

再以 TEMP fixtures 做一次 CLI smoke；不得用真實 2025 outcome payload。

### Step 5 — Handoff

Terra 只回傳：execution baseline SHA、ready file list、每檔 SHA-256、測試命令與完整輸出摘要、audit status（若已有合規 evidence）、blockers、production/source write statement、`oos_payload_read=false`。不 commit、不 push。

## 7. Completion 與 Rollback

Engineering completion 是 pure auditor、CLI、tests、mypy、boundary／quant checks 全部通過；它不等於 audit 判定為 unopened。真實 audit 若缺人類聲明，可以 `indeterminate` 誠實完成一次執行。

回滾只移除本切片新檔或 revert 其單一 commit；audit reports 採 append-only revision，不覆寫舊結果。任何失敗維持 Rule-only、`formal_oos_allowed=false`、`production_blend_alpha_bp=0`。

## 8. 後續 Gate

本 Task 完成後也不得自動啟動 Formal OOS、EV1、EV2、EV4 或 EV5。若後續要建立 Experiment V1，先由人類完成 [Preregistration Template](../../06_qa/EXPERIMENT_V1_PREREGISTRATION_TEMPLATE.md) 的兩個 bp 決策與簽核。
