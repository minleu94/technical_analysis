# V2.1 Formal Closeout Approval Record

> 日期：2026-07-12
> 狀態：**`awaiting_release_owner_confirmation`**；engineering readiness 已完成，**尚未**成立正式 closeout。
> 工程 readiness：見 `V2_1_ENGINEERING_READINESS_2026_07_12.md`。
> 不代表：投資有效性、保證獲利、broker execution、production scheduler、DB write、lifecycle action 或 P0 source acceptance。

## 1. 正式 closeout 的必要人工確認

本文件保留正式 closeout 所需的審核欄位，但不代填、推論或虛構 release owner 的決策。在下列欄位由授權 owner 明確填寫前，V2.1 的唯一狀態是 `engineering_readiness_complete` / `awaiting_release_owner_confirmation`。

| 必填欄位 | 目前記錄 | 規則 |
|---|---|---|
| release owner | `TBD — 未提供，不得虛構` | 必須是具有版本發布決策權的人工 owner。 |
| confirmation timestamp | `TBD — 未提供，不得虛構` | 使用實際確認的時區時間戳。 |
| decision | `TBD — 未提供，不得虛構` | 必須明確記錄 `approve`、`hold` 或 `reject`，並附必要限制／理由。 |

只有 decision 為 `approve` 且三欄完整時，才可把本文件及 Snapshot / Version Roadmap 的狀態改為正式 closeout；`hold` 或 `reject` 必須保留工程證據與 rollback SHA，不能刪除或改寫。

## 2. Engineering readiness 的版本範圍

V2.1 將既有 Workbench 定位為可日常檢視的 bounded Advice 入口：Advice 由 application-layer composer / policy 產生，Qt 僅透過 `WorkbenchDashboardDTO.advice_dashboard` 唯讀呈現。輸入保留 decision / data-as-of date 與 source trace；資料、策略或風險條件不成立時，系統明確拒絕或降級，而不是補值或湊出候選。

Guided Mode 只接受同時符合 `promoted`、參數已鎖定與 disclosure 完整的策略。Professional Mode 的 candidate 僅能作 `RESEARCH`，並在 UI 與正式 Advice 分區；兩者共用同一 policy、DTO 與資料品質規則，沒有第二套計算路徑。

## 3. Engineering readiness 檢核

| Closeout 條件 | 結論 | 證據 |
|---|---|---|
| 可拒絕、可重算、可回溯的 Advice contract | 通過 | Advice DTO / Policy / Composer focused tests；source trace、decision date、data-as-of date 與 future-input guard。 |
| Guided 策略治理 | 通過 | `promoted` + locked + disclosure 三重門檻；任一不成立即 `NO_NEW_POSITION`。 |
| Professional 研究隔離 | 通過 | candidate 僅 `RESEARCH`，以 `PROFESSIONAL_CANDIDATE` 標記並於 Workbench 獨立分區。 |
| 資金與持倉防線 | 通過 | 最低現金 `2000 bp`、單檔 `1500 bp`、最大持倉只允許 `1..8`；整數 bp / `Decimal` 契約維持。 |
| Workbench read-only boundary | 通過 | UI 不執行 policy / composer、不寫 DB、不重算核心、不建立 broker order 或 scheduler。 |
| focused automated verification | 通過 | 2026-07-12：`94 passed in 2.91s`。 |
| 人工 UI 文案 smoke | 通過 | 正式 Advice 與 Professional 研究候選分區清楚；安全 action 不表述為交易指令；不使用保證獲利或自動交易語氣。 |

## 4. 驗證命令與結果

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_advice_dtos.py tests/test_advice_policy.py tests/test_advice_composer.py tests/test_workbench_advice_contract.py tests/test_ui_qt_workbench_view.py tests/test_ui_qt_update_view_workbench.py -q -o addopts=
```

結果：**94 passed in 2.91s**。

完整工程檢核、人工文案 smoke 範圍與限制見 readiness artifact。先前 Gate 1 closeout 的基礎證據見 `GATE_1_ADVICE_CLOSEOUT_2026_07_12.md`；本文件以 `592d3db` 的最新 safeguards 作 engineering readiness 判讀基準，不能替代 release owner confirmation。

## 5. 已知限制與後續工作

- 這是 bounded Advice / read-only Workbench 版本，不驗證選股、Advice、Portfolio 或 Exit 的投資有效性。
- 不連接 broker、不產生訂單、不自動下單或平倉；不將 candidate、shadow、replay 或 dry-run 說成正式投資證據。
- V2.2 僅在真實 weekly history、manual review note、action-item rhythm 與必要人工核准成立後才可 closeout；production scheduler 仍為 `production_scheduler_allowed=false`。
- V2.3 至 V3.0 的資料可信度、Portfolio、Position Health 與 effectiveness / pruning 仍須各自的證據與人工 Gate，不因 V2.1 closeout 提前成立。

## 6. 回退

- V2.1 Gate 1 程式回退錨點為 `592d3db5d88262bbc5e48c0d363e7f43f8c69389`。此 commit 納入 Guided 三重門檻、持倉上限 1..8 驗證與 Professional candidate UI 分區；回退功能時，必須同步重跑 focused suite。
- closeout 文件可獨立 revert；任何功能回退均不得刪除既有 evidence、改寫正式資料或解除 broker / scheduler 禁令。

## 更新記錄

- 2026-07-12：修正為正式 closeout approval record；保留最新 safeguards、focused suite、人工 UI 文案 smoke 與 rollback 證據，等待 release owner 的 owner / timestamp / decision 三項明確確認。
