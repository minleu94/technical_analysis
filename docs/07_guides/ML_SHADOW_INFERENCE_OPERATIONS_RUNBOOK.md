# ML Shadow 單日推論操作 Runbook

## 適用範圍與證據邊界

本 Runbook 僅適用於工程受控的 ML shadow contract path。此流程可驗證 frozen artifact 載入契約、單日推論、prediction registry 冪等寫入、lifecycle rollback 模擬及唯讀檢視；不會改變正式規則、排序、分數、推薦或交易決策。

目前 repository 未提供可供此工作流執行的真實 frozen B artifact，因此尚未完成真實 artifact 的 one-date smoke。CLI 固定回報：

- `evidence_mode = controlled_contract_path`
- `validated_artifact_observed` 表示受控 artifact 已通過載入契約
- `real_frozen_artifact_observed = false`
- `production_blend_alpha_bp = 0`
- `production_action_allowed = false`
- `production_scheduler_allowed = false`

不得把受控 fixture 的成功結果解讀為正式產品、正式模型或 production-ready 證據。

## 執行前準備

所有可寫入路徑都必須位於明確指定的獨立 shadow root 內，且 shadow root 不得等於 `DATA_ROOT` 或位於 `DATA_ROOT` 之下。需要準備：

- frozen model 目錄與 manifest
- 一筆 `HistoricalFeatureRow` JSON
- 一份 `HistoricalMLShadowRunReport` JSON
- source versions JSON 與其預期 hash
- 預期 model family 與 label registry hash
- 獨立 prediction/lifecycle SQLite 路徑

建議先建立本機暫存根目錄，例如 `%TEMP%\technical_analysis_parallel\F\manual-shadow`，不要使用正式資料根目錄。

## 單日推論

以下範例中的所有路徑均需換成實際的絕對路徑：

```powershell
.\.venv\Scripts\python.exe scripts\run_ml_shadow_inference.py `
  --shadow-root C:\Temp\technical_analysis_shadow `
  --model-root C:\Temp\technical_analysis_inputs\model `
  --prediction-registry C:\Temp\technical_analysis_shadow\prediction.sqlite3 `
  --lifecycle-registry C:\Temp\technical_analysis_shadow\lifecycle.sqlite3 `
  --feature-row C:\Temp\technical_analysis_inputs\feature-row.json `
  --run-report C:\Temp\technical_analysis_inputs\run-report.json `
  --source-versions C:\Temp\technical_analysis_inputs\source-versions.json `
  --source-versions-hash <EXPECTED_SOURCE_VERSIONS_HASH> `
  --expected-model-family <EXPECTED_MODEL_FAMILY> `
  --expected-label-registry-hash <EXPECTED_LABEL_REGISTRY_HASH> `
  --output-root C:\Temp\technical_analysis_shadow\output `
  --data-root D:\Min\Python\Project\FA_Data
```

結果同時輸出至 stdout 與 `<output-root>\ml-shadow-operation.json`。相同 model、dataset、decision date 與 feature snapshot 的請求重跑時，prediction registry 只保留同一筆識別結果，不應重複新增。

## Rollback 模擬

在單日推論命令加上：

```powershell
--simulate-rollback-reason "controlled rollback drill"
```

成功推論後會在獨立 lifecycle registry 寫入 rollback/disabled 事件。之後以相同 model 重跑，應取得 `shadow_unavailable` 與 `lifecycle_disabled` blocker；正式規則仍保持不變。這是 lifecycle 安全演練，不會恢復、替換或操作正式模型。

## 唯讀檢視

```powershell
.\.venv\Scripts\python.exe scripts\inspect_ml_shadow_operations.py `
  --prediction-registry C:\Temp\technical_analysis_shadow\prediction.sqlite3 `
  --lifecycle-registry C:\Temp\technical_analysis_shadow\lifecycle.sqlite3 `
  --model-id <MODEL_ID> `
  --data-root D:\Min\Python\Project\FA_Data
```

檢視命令不會初始化或修改 registry。若檔案不存在，會回報 `shadow_registry_unavailable` 並以 exit code 1 結束。

## 結果判讀與排錯

- `shadow_available`：受控契約下有 shadow prediction；不代表正式可用。
- `shadow_unavailable`：查看 `blockers`，不得以預設值或假 prediction 補齊。
- `artifact_unavailable:manifest_missing`：model root 缺少 manifest。
- artifact hash、schema、registry 或 library compatibility blocker：輸入與 frozen manifest 不一致；修正輸入或重新取得合規 artifact，不得略過驗證。
- `lifecycle_disabled` 或 `lifecycle_superseded`：模型已被 lifecycle gate 阻擋，不得繼續 overlay。
- 路徑錯誤：確認 prediction registry、lifecycle registry 與 output root 都是 shadow root 的子路徑，且 shadow root 不在 `DATA_ROOT` 內。

## 安全限制

- 此路徑只載入 frozen artifact，執行時不得呼叫 `.fit()` 或自動重訓。
- 禁止自動 promotion、production scheduling 或 production action。
- 不得把 shadow prediction 混入 Recommendation、runtime、正式 ranking 或正式 score。
- production blend alpha 固定為 0 basis points。
- 輸入不完整或 contract 不相容時必須 rule-only / unavailable，不得產生假值。
- rollback 僅限明確 shadow registry；清理由操作者刪除該獨立暫存根目錄，不得刪除原始或正式資料。
