# Evidence Rehearsal Real E2E 工程收口（2026-07-13）

## Truth status

本工作流目前只可標示為 `engineering_real_e2e_complete`。CLI contract v2 的 `working_copy_e2e` 已接入真實 orchestration；source 維持唯讀，historical replay 與故障 mutation 僅作用於 `DATA_ROOT` 外的 working copy，P0／ML 狀態由既有 boundary service 計算，lineage 與 blockers 來自實際產物。

這不是 formal product closeout，也不是 external、forward、paper 或 live 證據。所有報告仍強制：

- `formal_product_closeout=false`
- `production_actions_allowed=false`
- `forward_handoff_pending`

## 已收口的工程契約

- CLI v2 的 working-copy E2E 會呼叫 source probe、historical replay、P0 comparison、可選 ML comparison、lineage verifier 與 evidence rehearsal service。
- `missing_day` 與 `schema_missing` 會修改 working copy，再由 historical replay 偵測；source byte content 保持不變。
- `immature_label` 使用結構化 ML boundary input，由 ML comparison 計算 immature row，不接受任意 supplied status。
- `--ml-evidence-root` 讀取 `rehearsal-ml-input.json`，驗證 frozen shadow-only manifest、boundary rows 與 prediction safety flags。
- projection-only 模式拒絕所有故障注入，避免把靜態 blocker 誤稱為 real detector。

## 仍待外部／產品 gate

- 外部資料來源、license、coverage 與 source acceptance 尚未核准。
- 真實 forward window、paper observation、weekly scheduler 與 live evidence 尚未完成。
- ML training／calibration／champion promotion 與任何 production action 尚未授權。
- Advice、Portfolio、Exit、broker 或其他產品行為均未因本收口啟用。
- lineage 缺少的真實下游 stage 仍應顯示 incomplete／blocker，不得以 fixture 補成 complete。

## 驗證紀錄

最終 focused regression、型態／語法、量化 float guard、ML dependency boundary、diff check 與檔案 SHA-256 由本 slice handoff 記錄；只有實際執行成功的結果可填入 handoff，不在本文件預先宣告未跑的測試。
