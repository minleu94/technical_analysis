# V2.1 至 V3.0 前版本化交付設計

> 日期：2026-07-12  
> 狀態：已確認版本交付規則，待執行  
> 範圍：V2.1、V2.2、V2.3、V2.4、V2.5；V3.0 只準備正式 closeout 所需證據，不提前宣告完成。

## 目標

將 V2.1 至 V2.5 拆為可獨立檢視、測試、回滾與選擇性推送至 `main` 的版本交付單位。每個版本都必須有版本說明、驗收證據、已知限制與後續人工作業清單。

## 版本 Commit 規則

每個版本最多分為兩個有意義的 closeout commit：

1. `feat(vX.Y): complete engineering readiness`：只包含該版本可由程式碼與自動驗證完成的能力。
2. `docs(vX.Y): record formal closeout`：只有真實時間、人工覆盤、資料接受或 paper evidence 都滿足時才建立；記錄人工證據、版本限制與 rollback SHA。

工程 readiness 不得宣稱正式版本完成。每個版本都要在 `PROJECT_SNAPSHOT.md`、版本說明 QA 文件與 `VERSION_ROADMAP_V2_1_TO_V4_0.md` 的現況段落留下明確狀態；Roadmap 的 maturity 定義不因單次工程 commit 改寫。

## 版本範圍

| 版本 | 工程交付 | 正式 closeout 前的人工作業 |
|---|---|---|
| V2.1 | bounded Advice、Guided/Professional 隔離、拒絕輸出、target/current/gap、唯讀 Workbench | UI／文案人工 smoke 與 release owner 確認 |
| V2.2 | weekly review、append-only review artifact、action-item rhythm、working-copy recovery 與 scheduler approval package | 至少 3 個真實週期 weekly history、人工 review、backup/rollback/recovery 演練、明確 scheduler approval |
| V2.3 | P0 source registry、diagnostics/shadow/acceptance workflow、source control read model | 每個 P0 source 的 accepted/limited/rejected/deferred 人工決議與 license/quality/PIT 審核 |
| V2.4 | risk budget、target/current/gap、Equal Weight、paper portfolio、execution feasibility | 真實 paper portfolio／成本後比較與人工 policy review |
| V2.5 | thesis/invalidation/health state/decision journal/override contract | 每個 active position 的真實 thesis 與人工 state transition 覆盤 |
| V3.0 | score/component/gate/alert/profile effectiveness 與 pruning workflow | 真實 forward/paper evidence、人工 retain/restrict/downweight/retire 決議；在此前不得標 V3.0 complete |

## 共通安全條件

- 全部金融權重使用整數 bp，金額使用 `Decimal`；禁止新增核心裸 `float`。
- 所有資料遵守 `available_date <= decision_date`；replay、candidate、dry-run、shadow 與 live 不可混用。
- 不串 broker、不自動交易、不自動平倉、不自動 lifecycle action。
- 每版需有 focused tests、適用 UI QA、mypy、py_compile、financial float guard、look-ahead guard、`git diff --check`。
- 每版 closeout 都必須記錄 rollback commit SHA；不覆寫使用者既有未提交變更。

## 文件與回滾

每版會新增 `docs/06_qa/VX_Y_ENGINEERING_READINESS_YYYY_MM_DD.md`，正式 closeout 時另新增 `VX_Y_FORMAL_CLOSEOUT_YYYY_MM_DD.md`。`PROJECT_SNAPSHOT.md` 只保存目前狀態與當前阻擋項；過時數字移入有日期的歷史段落；`docs/06_qa/PROJECT_SNAPSHOT_AUDIT_*.md` 保存稽核依據。

回滾時可依版本 commit SHA 逐版反轉，而不必撤銷後續版本；任何與正式資料、scheduler 或 broker 有關的操作仍須另行人工批准。
