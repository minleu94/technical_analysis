# Shim／Legacy Removal Audit（2026-07-12）

## 結論

使用者已於 2026-07-12 明確核准 Wave 6 移除。所有 production/test consumers 遷移後，三個 compatibility shim、`recommendation_module_legacy`、舊 example 與兩個 legacy manual checks 已刪除；本文件記錄最終 closeout 證據。

## 候選與證據

| 候選 | Production 靜態 consumer | Dynamic route | Persisted class-path | 目前判定 |
|---|---:|---|---|---|
| `decision_module.indicator_parameter_registry` | 0 | 未發現目標字串的 `import_module` / `__import__` | 未發現 pickle/joblib consumer | 已移除；analysis domain path 為唯一入口 |
| `app_module.dtos.broker_flow_dtos` | 0 | 未發現目標 dynamic import | 未發現 Flow DTO pickle/joblib consumer | 已移除；`decision_module.flow_contracts` 為唯一入口 |
| `app_module.dtos.flow_signal_dtos` | 0 | 未發現目標 dynamic import | 未發現 Flow DTO pickle/joblib consumer | 已移除；`decision_module.flow_contracts` 為唯一入口 |
| `recommendation_module_legacy` | 0 | 未發現目標 dynamic import | 未發現 pickle/joblib consumer | 已連同三個明示棄用 consumers 移除 |

歷史 migration 文件保留原路徑敘述並加註最終移除日期；目前導航、架構與狀態文件均指向新的唯一入口。

## Wave 6 Gate

- [x] production code 的三個新 compatibility path 靜態引用已降為零。
- [x] 已檢查 `import_module`、`__import__`、相關 `getattr` 與 Qt route，未發現以候選 module path 動態載入。
- [x] 已檢查 pickle/joblib 關鍵字，未發現候選 DTO／registry 的 persisted class-path consumer。
- [x] `recommendation_module_legacy` 靜態 consumer 為零。
- [x] 使用者明確核准本次移除，取代原先等待下一版的保守排程。
- [x] 對應 tests 已改驗證舊檔不存在，healthcheck 不再 import 候選路徑。
- [x] Full App Healthcheck `20260712_025311` passed；刪除後完整 pytest 與 release gates 無回歸。
- [x] 人工核准刪除清單與回滾方式。

## 已執行刪除清單

1. 移除 `examples/main_example.py`、兩個 legacy recommendation manual checks 與 `recommendation_module_legacy/`。
2. 移除三個 compatibility re-export 檔。
3. 更新 test inventory、Project Navigation、Migration Plan 與 architecture docs。
4. 重跑 full pytest、full-app healthcheck、Update QA、全域 mypy與 financial float checker。

## 回滾方式

刪除必須以獨立 commit 執行；若任何 import、serialization、UI smoke 或 automation gate 失敗，完整 revert 該刪除 commit，不以臨時 dynamic import 或複製 class 定義補洞。

## 刪除後驗證

- Full App Healthcheck full mode：passed（run `20260712_025311`）。
- 完整 pytest：`1676 passed`，24 個 warnings 均為既有 recommendation portfolio 同日收盤研究假設揭露。
- Update Qt focused tests：`38 passed`。
- Update QA：`23 passed / 0 failed / 4 skipped`；跳過項為防止正式下載／合併。
- 全域 mypy：`364 source files`，無 error。
- Financial float boundary checker：`37 passed`。
- `compileall`、`git diff --check`：passed。
- Production/test Python source 的四個已刪 module import path：零引用。
