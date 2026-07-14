# External Evidence Wave 1 執行授權增補

> 日期：2026-07-13
>
> 授權人：使用者明確授權
>
> 基線：`dev`、`ee326d6`（A～G immutable engineering anchor：`4f72766`）
>
> 上位文件：[External Evidence Master Plan](../plans/2026-07-13-external-evidence-investment-validation-master-plan.md)
>
> 執行交接：[Terra External Evidence Execution Handoff](../prompts/2026-07-13-terra-external-evidence-execution-handoff.md)

## 1. 授權範圍

本增補以使用者明確授權取代舊交接中「只允許 EV3-A」的啟動限制；僅允許下列三個切片自本授權基線**平行啟動**：

| 切片 | 授權工作 | 僅可達成的工程狀態 |
|---|---|---|
| EV1-A | Causal Evidence Clock | immutable decision snapshot、append-only outcome revision ledger、manual/shadow capture readiness |
| EV3-A | 2025 OOS Exposure／Custody Audit | 純 custody／exposure audit；結果可為 `indeterminate` |
| EV4-A | Rule Champion 與 Experiment V1 Preregistration | Rule Champion snapshot／manifest 與 preregistration contract；可等待人工決策 |

EV2 與 EV5 **仍未授權**。本增補不修改任何 external status、External Gate revision 或 formal product 狀態。

## 2. 不變的硬性安全邊界

下列條件在三個切片全程均為不變的 fail-closed Gate：

1. `formal_oos_allowed=false`。
2. `production_blend_alpha_bp=0`。
3. Forward evidence、source acceptance、promotion 與 automation 均維持 `pending`。
4. 工程完成不得自動解鎖任何 External Gate，亦不得視為 formal OOS、promotion eligible、production ready 或 ML 優於 Rule。
5. 缺少人工 bp 決策、具名 reviewer identity、signed declaration 或要求的 machine evidence 時，必須輸出 `needs_human_decision` 或 `indeterminate`；不得猜測、代填或代替人類簽署。
6. 不得啟動 EV2、EV5、OOS unblind、training、Rule／ML comparison、alpha blending 或 production automation。

## 3. 切片專屬限制

### EV1-A：Causal Evidence Clock

- 只保存真實 observed decision；市場尚未產生新 decision 時，只可交付工程 contract 與 manual capture readiness，不得合成 observed day 或以歷史回填冒充 forward evidence。
- 僅允許 bounded、read-only 正式來源讀取；capture 必須明確由人工 CLI 啟動，輸出只可寫入 `TEMP` 或顯式 shadow `OUTPUT_ROOT`。
- 禁止 production scheduler、broker、auto write 與任何正式行為變更；不得改 Feature、Label、ML 或 Recommendation 語意。

### EV3-A：2025 OOS Exposure／Custody Audit

- 原有 hard gates 完全不變：不得讀取 2025 outcome／return／metric／ranking／report body，不得 fit、retrain、calibrate 或 compare。
- 缺 signed declaration 或 machine evidence 必須為 `indeterminate`；audit 本身不得改寫 `formal_oos_allowed` 或 production alpha。
- 唯一 canonical execution companion 為 [OOS Exposure／Custody Audit Execution Plan](../plans/2026-07-13-oos-exposure-custody-audit-execution-plan.md)。

### EV4-A：Rule Champion 與 Experiment V1 Preregistration

- 只做 preregistration 與 formal rule-only Champion contract；不得 unblind、training、Rule／ML comparison 或根據任何 OOS 結果調整 preregistration。
- `minimum_material_effect_bp` 與 `downside_noninferiority_margin_bp` 必須由人類以整數 bp 決定；工程不得代填。
- 缺這兩個 bp 數字、reviewer identity 或 EV3 custody 結果時，輸出 `needs_human_decision` 並停在合法 Gate。

## 4. Git、交接與接受規則

唯一 Git Coordinator 固定使用目前 `dev` 與同一 working tree；不得建立或切換 branch/worktree，亦不得自行 pull、reset、stash、switch。每個 worker 不得執行任何 git mutation，且必須使用獨立 `TEMP`、`OUTPUT_ROOT`、pytest `--basetemp`、pytest cache directory 與 handoff JSON。

每個 handoff 必須含：`task_id`、`execution_baseline_sha`、`ready_files`、`sha256_by_file`、`red_evidence`、`green_verification`、`boundary_checks`、`blockers`、`human_decisions_pending`、zero-write 聲明、rollback notes 與 suggested commit message。Coordinator 必須重算 SHA-256、重跑 focused tests／boundary guards、確認其他 worker 檔案未被 stage、精確 stage 單一 slice、檢查 cached diff、序列 commit 並 push `dev`；只有 push 成功才可解凍該 worker。每個 worker 完成後，Coordinator 必須以空出的 slot建立獨立唯讀 QA reviewer；QA 通過後才接受 handoff。

## 5. 授權終點與停止條件

本 Wave 1 只允許宣稱：EV1 Evidence Clock engineering ready（且只計入真實 observed decisions）、EV3 custody auditor 完成（可為 `indeterminate`）、EV4 preregistration／Champion contract ready（可等待人工 bp 值）。三個切片完成後立即停止。

不得宣稱 2025 formal OOS 已允許、ML 優於 Rule、forward evidence 成熟、promotion eligible 或 production ready。
