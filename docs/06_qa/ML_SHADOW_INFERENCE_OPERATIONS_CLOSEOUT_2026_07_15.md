# ML Shadow 推論操作層 Closeout（2026-07-15）

## 結論

Workstream F 已完成工程受控的 ML shadow 單日推論操作層：明確 shadow root、production-path 拒絕、frozen artifact contract 載入、prediction registry 冪等寫入、lifecycle rollback 模擬、後續 overlay 阻擋，以及不建立 registry 的唯讀檢視。

本 closeout 只代表 controlled-contract engineering path 完成，不代表正式產品功能、正式模型上線或 Gate 7 全面完成。正式規則、ranking、score、Recommendation 與 runtime 路徑均未變更。

## 依賴基線

- B 成熟資料邊界：`e1c8ed`
- F 受控單日推論：`b673ec6f`
- F drift / calibration 監控：`3422aa17`

上述 SHA 僅作工程依賴識別；本文件不主張其外部 gate 已自動解除。

## 完成範圍

- `scripts/run_ml_shadow_inference.py`
  - 要求所有寫入路徑位於明確 shadow root。
  - 拒絕把 shadow root 放在 `DATA_ROOT` 或其子路徑。
  - 以 frozen artifact loader 驗證 manifest、hash、schema 與相容性。
  - 以穩定 prediction identity 支援相同請求冪等重跑。
  - 支援明確 rollback 模擬，disabled/superseded lifecycle 後停止 overlay。
  - 固定揭露 controlled evidence，不把 fixture 宣稱為 real frozen artifact。
- `scripts/inspect_ml_shadow_operations.py`
  - 唯讀列出 prediction 與 lifecycle 狀態。
  - registry 不存在時不建立檔案。
- 操作與排錯由 `docs/07_guides/ML_SHADOW_INFERENCE_OPERATIONS_RUNBOOK.md` 說明。

## 證據限制與 blocker

截至本 closeout，repository 中沒有可供此操作層執行的真實 frozen B artifact。因此：

- 真實 artifact one-date smoke：**blocked**
- 受控 fixture contract path：已驗證
- `real_frozen_artifact_observed`：固定為 `false`
- 正式 production action、auto-promotion、auto-retrain、scheduler：均為 `false`
- production blend alpha：0 basis points

待 B 提供具有可核對 manifest、artifact hash、schema/registry hash 與 library compatibility 的真實 frozen artifact 後，才可另行執行真實 one-date smoke 並產生新的 QA 證據。不得用目前的受控 fixture 結果替代。

## 驗證項目

本 slice 的驗證涵蓋：

- 相同單日請求重跑不增加 prediction row。
- rollback 模擬後 lifecycle 為 disabled，下一次推論 rule-only / unavailable。
- artifact 缺失時沒有假 prediction。
- `DATA_ROOT` 內的輸出路徑被拒絕。
- inspect 不變更 registry mtime，缺檔時也不建立 registry。
- production、promotion、retrain、scheduler 旗標維持關閉。

本 slice 最終驗證結果：

- focused pytest：`30 passed in 2.13s`
- 兩支新 CLI 的隔離型態檢查（`mypy --follow-imports=skip`）：`Success: no issues found in 2 source files`
- 直接遞迴 import 的 mypy：被既有 `ml_module/model_artifact_manifest.py:135` 型別錯誤阻擋；本 slice 未修改該相依檔案
- `py_compile`：兩支新 CLI 通過

若後續任何檔案變更，必須重新執行 focused pytest、mypy、py_compile 與 safety scan，不得沿用本次結果。

## 外部 gates

外部資料可得性、真實 artifact 交付、產品 approval、production scheduling 與正式 rollout gate 均未由本 slice 變更或解除。
