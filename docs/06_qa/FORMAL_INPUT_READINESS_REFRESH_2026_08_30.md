# Formal／ML Input Readiness Refresh（2026-08-30）

> 本文件記錄三項 Formal／ML owner-controlled input 的 strict read-only 重驗；它不發布、不複製、不改名任何 prospective／research artifact，也不授予 Formal credit。

## Validator

```powershell
.\.venv\Scripts\python.exe scripts\inspect_ml_formal_input_readiness.py `
  --output-root D:\Min\Python\Project\FA_Data\output `
  --training-as-of 2026-08-28T00:00:00+08:00 `
  --output C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\ml_formal_input_readiness_20260830.json
```

輸出 artifact：

- path：`C:\Users\archi\AppData\Local\Temp\technical_analysis_program_readiness\ml_formal_input_readiness_20260830.json`
- file SHA-256：`sha256:82873CED517019B2315DFCDF4F83C49F67E4E56ACA1AE03C9D8A2E8DE0CE216A`
- readiness hash：`sha256:c912b1a0603bb4d1dec90c80f73f05d7390741f4b4816a918e07e76bac9aa9c0`
- status：`waiting_for_formal_inputs`
- ready ratio：`0/3`
- safety：`formal_oos_allowed=false`、`production_alpha_bp=0`、`broker_order_allowed=false`

## 三條正式輸入

| Input | 明確路徑現況 | 原因 |
|---|---|---|
| causal non-cash portfolio ledger | `missing` | `BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH` 指向 `formal_prospective\clock-20260819\portfolio_ledger\manifest.json`，未發布為正式 consumer schema；clock date 早於 training cutoff |
| Rule Champion snapshot history | `missing` | `BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH` 指向 `formal_prospective\clock-20260819\rule_champion_history\manifest.json`，同樣是 prospective output 未發布 |
| PIT sector membership | `missing` | `BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH` 指向 `formal_prospective\clock-20260819\pit_sector_membership\manifest.json`，同樣未成為 validated production sidecar |

## 為什麼不能直接拿現有檔案補上

Validator 另外觀察到 `formal_prospective` 下 6 個 clock：`clock-20260825`、`clock-20260826-v1`、`clock-20260827`、`clock-20260827-v2`、`clock-20260827-v3`、`clock-20260828`。它們的 lane 都是 `prospective_formal_simulation`、authority=`diagnostic_only`；`clock-20260825` 雖顯示 1 個 published-looking component，仍不是三項正式 input 的 owner-controlled publication。將其中任一 path 直接改接會把 staging／prospective lineage 轉成 Formal custody，違反 explicit path、clock、schema、hash、owner 與 rollback 契約。

## 可持續推進

1. 由 owner-controlled publisher 以新的、仍在 cutoff 內的 clock 發布三份 expected schema manifests。
2. 每份 manifest 經 loader、hash、cutoff、HMAC／store identity 與 source lineage 檢查後，再更新明確 `BALDR_ML_FORMAL_*` path。
3. 重新執行本 validator，確認 `3/3`；這仍只代表 input custody ready，不代表 Formal OOS、ML promotion 或非零 alpha。
4. 只有後續 immutable replay、calibration、drift、promotion authority 全部獨立通過，才可產生新的 gate revision；禁止 partial retrain、replay 回填或手動開旗標。

## 安全邊界

- 本輪只寫 TEMP readiness artifact，沒有寫 controlled path、Registry、Formal DB 或 production output。
- 所有 prospective／research artifact 保持原路徑與 diagnostic-only 身分。
- scheduler、training、promotion、broker 與 production blend 維持關閉。
