# Post-V1 Evidence Operations Weekly History Run（2026-07-03）

## 目的

本紀錄用於保存 V1.3 / V1.4 weekly evidence operations 實際操作的第一個 working-copy run 結論。這不是 production scheduler 啟用紀錄，也不是投資有效性結論。

## 執行範圍

- 期間：2026-06-29 至 2026-07-03。
- DB：`tmp/evidence_ops_20260703/evidence_ops_working.db`。
- data root：`tmp/evidence_ops_20260703/data`。
- output root：`tmp/evidence_ops_20260703/output`。
- 範圍限制：只使用 ignored `tmp/` working-copy；不寫正式 `DATA_ROOT`；不啟用 scheduler；不建立 lifecycle action；不產生買賣建議。

## 執行命令

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-29 --end-date 2026-07-03 --db-path tmp\evidence_ops_20260703\evidence_ops_working.db --data-root tmp\evidence_ops_20260703\data --output-root tmp\evidence_ops_20260703\output --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-29 --end-date 2026-07-03 --db-path tmp\evidence_ops_20260703\evidence_ops_working.db --data-root tmp\evidence_ops_20260703\data --output-root tmp\evidence_ops_20260703\output --plan-action-items --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-29 --end-date 2026-07-03 --db-path tmp\evidence_ops_20260703\evidence_ops_working.db --data-root tmp\evidence_ops_20260703\data --output-root tmp\evidence_ops_20260703\output --save-history --json-output
.\.venv\Scripts\python.exe scripts\build_evidence_operations_weekly_review.py --start-date 2026-06-29 --end-date 2026-07-03 --db-path tmp\evidence_ops_20260703\evidence_ops_working.db --data-root tmp\evidence_ops_20260703\data --output-root tmp\evidence_ops_20260703\output --list-history --json-output
```

## 結果摘要

| 項目 | 結果 |
|---|---|
| weekly review status | `coverage_only` |
| scheduler readiness | `not_ready` |
| production scheduler allowed | `false` |
| decision quality reviews | `0` |
| signal decay observations | `0` |
| manual lifecycle candidates | `0` |
| action item dry-run | `0` planned / `0` created / `write_performed=false` |
| history record | `eor_8d1643ae9fc02bd8` |
| history idempotency | 重複 `--save-history` 後，`evidence_operations_weekly_reviews` 仍為 1 筆 |

Blocking gaps：

- `decision_desk_snapshot_missing`
- `recommendation_persisted_missing`
- `working_copy_confirm_smoke_missing_or_failed`

Warnings：

- `why_not_payload_missing`
- `liquidity_gate_payload_missing`

Next actions：

- `collect_more_evidence`
- `resolve_scheduler_blocking_gaps`
- `keep_production_scheduler_disabled`

## 判讀

本輪完成第一個 weekly evidence operations + history 的 working-copy operating-cycle：CLI 可產生 weekly review、dry-run action item planning、保存 history、讀回 history，且重複保存不會新增重複列。

結果仍是 `coverage_only`，代表樣本與來源仍不足，只能視為操作節奏與 history 機制可用；不得解讀為策略、Profile、警示或推薦有效。

## 邊界

- 未寫正式 production evidence DB。
- 未啟用 production scheduler。
- 未確認 working-copy confirm smoke 通過。
- 未完成多週真實覆盤樣本累積。
- 未產生或套用任何 lifecycle action。
- 未產生買賣建議。

## 同日 follow-up

2026-07-03 後續追查確認 `decision_desk_snapshot_missing` 與 `working_copy_confirm_smoke_missing_or_failed` 主要來自 batch / CLI 路徑未使用 service-backed `DecisionDeskSnapshotBuilder`。已新增 non-UI builder factory，並補上 numpy scalar JSON 正規化。

後續 working-copy 驗證記錄見 `POST_V1_EVIDENCE_DECISION_DESK_WORKING_COPY_SMOKE_2026_07_03.md`。結果顯示 durable snapshot 已可看到 `market_regime`、`market_breadth`、`sector_rotation`、`relative_strength_liquidity` 與 `risk_prompt`；`risk_prompt_capture_ready=true`，working-copy confirm smoke 重跑 idempotency passed。剩餘 scheduler blockers 仍為真實 source 缺口：Recommendation result / why-not / liquidity payload 尚未持久化，default watchlist 無項目，portfolio 無 active positions。
