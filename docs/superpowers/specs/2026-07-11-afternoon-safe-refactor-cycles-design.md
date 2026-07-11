# 2026-07-11 下午安全重構五輪循環設計

## 目標

只在 2026-07-11 14:00–19:00（America/Los_Angeles）追加五輪 `SAFE_REFACTORING_MASTER_PROGRAM`。每輪維持 Planner → Implementation → QA 的完整交接，最多安排兩個彼此獨立且能在同一時間盒內完成的切片；不以增加數量為由略過 RED／GREEN、focused tests、conditional gates、push 或獨立 QA。

## 前置條件

- Repository 必須位於 `dev`，非 ignored 工作區乾淨。
- 啟動前將本機已驗證 commit push，使 `dev == origin/dev`。
- `latest_refactor_qa.json` 必須指向 `READY_TO_CONTINUE`；若為 remediation 或 blocked，第一輪只處理該狀態。
- 所有角色完整讀取 `docs/01_architecture/SAFE_REFACTORING_MASTER_REPORT.md`。
- `output/automation/**` 與 `graphify-out/**` 永不 stage。

## 時程

| 輪次 | Planner | Implementation | QA |
|---|---:|---:|---:|
| H | 14:00／核准後立即 | 14:10 | 14:45 |
| I | 15:00 | 15:10 | 15:45 |
| J | 16:00 | 16:10 | 16:45 |
| K | 17:00 | 17:10 | 17:45 |
| L | 18:00 | 18:10 | 18:45–19:00 closeout |

若建立排程時已超過 H Planner 時點，H Planner 改為建立完成後立即受控執行；H Implementation 及 QA 只有在 exact Plan 已存在且前一角色完成後才可繼續。若無法在 15:00 前完成 H，不壓縮後續輪次，H 產出 `NO_SAFE_SLICE` 或 `BLOCKED`，I 依 latest QA 接手。

## 每輪工作量

- Planner 最多選擇兩個切片：優先為一個中型主切片加一個低風險 helper／import／characterization 切片。
- 兩片必須沒有共享未提交狀態，且各自具備 exact files、RED oracle、最小 GREEN、Gate、commit message 與 rollback。
- Implementation 逐片執行；每片各自測試、atomic commit 並 push。第一片失敗、超時、偏離 scope 或 push 失敗時，第二片不得開始。
- QA 驗收該輪零至兩個 commit，核對每個 parent／Plan linkage／diff scope，並執行兩片 focused suite 聯集。
- 禁止同輪同時安排兩個 Qt lifecycle 切片、兩個 production-data orchestration 切片，或兩個金融公式／portfolio 核心切片。
- 五輪容量上限為十個切片；預期完成七至十個，實際以 Gate 結果為準。

## Automation 產物

- Planner：`refactor_plan_20260711_HHMM.md/.json`
- Implementation：`refactor_implementation_20260711_HHMM.md/.json`
- QA：`refactor_qa_20260711_HHMM.md/.json`
- 最終：`refactor_afternoon_closeout_20260711.md/.json` 與 `AFTERNOON_README.md`
- 每個 latest pointer 必須包含 exact artifact、cycle、status、baseline/result SHA 與 handoff。

## 安全與停止規則

- 只允許行為不變的最小切片；優先 import cycle、characterization 與已有 oracle 的 helper／facade。
- 禁止 production DB/evidence write、正式資料改寫、scheduler 行為變更、交易、lifecycle action、ScoringEngine／threshold／weights／portfolio 語意變更。
- Protected contracts、DTO／序列化、排序、diagnostic token、SQL fallback、Qt lifecycle 與副作用順序不得改變。
- Planner 發現連一個切片都無法安全完成時必須 `NO_SAFE_SLICE`；只能安全完成一片時不得為湊數加入第二片。
- Implementation 僅消費 exact Plan；每片未通過 Gate 不得 commit/push，也不得開始下一片。
- QA 必須 fresh rerun 關鍵證據；remediation 優先於新切片。
- 前輪未完成、工作區不乾淨、`dev != origin/dev`、pointer mismatch 或 non-fast-forward 時，後輪不得開工。

## 一次性生命週期

建立 15 個今天限定 automation。優先使用支援單次執行的 recurrence（`COUNT=1`）；若 Codex automation runtime 不接受單次 recurrence，使用可驗證的臨時 daily recurrence，並在 19:00 closeout 後立即設為 `INACTIVE`，不得保留到隔日觸發。建立後逐一核對名稱、狀態、時區、下一次執行時間與 project target。

## 驗收

- 五輪每輪都有完整 Plan／Implementation／QA artifact，或明確 `NO_SAFE_SLICE`／`BLOCKED`；Implementation artifact 必須逐片列出 commit 與 Gate。
- 每個實作 commit 均 atomic、已 push，且 parent 對上 Plan baseline。
- 19:00 前產出 afternoon closeout，列出完成切片、測試、remediation、revert point 與剩餘建議。
- 排程不會在 2026-07-12 再次執行。
- 正式資料、Evidence DB、交易與使用者可見行為未被修改。
