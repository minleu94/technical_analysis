# Historical ML Shadow Runbook

## 定位與安全邊界

此流程只建立 research-only 傳統 ML challenger，不改 Score、Recommendation、Advice、Portfolio 或 production scheduler。正式 SQLite 必須使用 `mode=ro` 與 `PRAGMA query_only=ON`；dataset、model、preflight report 只能寫入呼叫者明確指定、且不位於 `DATA_ROOT` 的 ignored output root。

Core family 只接受 price、technical、market、industry。Fundamental 在正式 PIT audit 顯示 eligible=0 時維持排除；broker 維持獨立 add-on，不補 0。所有持久化數值使用整數 bp/count；`float` 只存在 sklearn 模型邊界。

## 訓練與選模

1. Feature T 使用前一交易日資料；label 從 feature cutoff close 起算 20 個共同市場交易日。
2. `decision_date`、`label.available_date` 都必須小於等於 `training_as_of`；本版 frozen cutoff 固定為 `2024-12-31`。
3. Split 使用 expanding trading-calendar purged walk-forward，不允許 shuffle/K-fold。Train label end 必須早於 test start。
4. Linear 與 HGB 使用相同 fold/schema；imputer/scaler 只 fit train fold。全缺欄位必須保留 frozen feature shape。
5. Downside calibration 只使用至少兩個 OOF blocks。Research blend 只使用 `label.available_date <= 2024-12-31` 的 OOF rows，候選 alpha 固定為 0/2500/5000/7500/10000 bp。
6. `production_alpha_bp` 永遠是 0。Research alpha 不會寫回 production path，也不代表 promotion。

## Corporate-action gate

- `strict`：coverage unknown 時排除 label window；不得建立 clean/formal OOS dataset。
- `research`：可保留 degraded labels，但 manifest 必須是 `research_only_degraded`、`formal_oos_allowed=false`，並保存 blocker。
- E2 coverage 改善後仍需建立新 dataset/model generation，不可覆寫既有 manifest 或 artifact。

## Locked OOS 指令

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_ml_2025_oos.py `
  --freeze-summary <OUTPUT_ROOT>\freeze_summary.json `
  --oos-payload <LOCKED_2025_PAYLOAD> `
  --output-root <OUTPUT_ROOT>\locked-oos-preflight `
  --confirm-locked-oos
```

Preflight 必須在讀取 `--oos-payload` 前驗證：顯式 confirm、完整 dataset/model hash、所有 train/blend cutoff、`formal_oos_allowed=true`、`production_alpha_bp=0`。任一 blocker 會輸出 `locked_oos_preflight.json`、exit 2，且 `oos_payload_read=false`。

禁止因 blocked 或結果不佳而改參數後重跑同一 locked OOS。合法狀態為 `reject`、`continue_shadow`、`shadow_candidate`；工程成功不等於投資有效。

## 名詞區分

- Historical research rehearsal：可含 degraded coverage，不是 clean OOS。
- Locked historical OOS：freeze/preflight 全綠後才可一次性讀取。
- Daily shadow inference：由 F workstream 負責，仍無 production action。
- Forward evidence：真實時間後續累積，不可由歷史 OOS 取代。
- Promotion：必須另經人工 review；本流程不自動套用。
