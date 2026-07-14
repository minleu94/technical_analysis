# Historical ML Shadow MVP Closeout（2026-07-15）

## 結論

本次結果為 **`continue_shadow` / historical research rehearsal**，不是 clean/formal locked OOS，也不是投資有效性結論。Production alpha 固定為 0，沒有讀取任何 2025 locked payload，沒有 production apply。

## Frozen research artifact

- 正式來源：`D:/Min/Python/Project/FA_Data/sqlite/twstock.db`，`mode=ro` / `query_only`。
- Output：`%TEMP%/technical_analysis_parallel/B/B6-B10-final-safe-core/artifacts/formal-core-shape-safe-20260713175735`。
- 範圍：10 檔 Core 股票、22 個月度 decision dates（2023-01 至 2024-10）；這是 bounded engineering artifact，不是全市場母體。
- Feature rows：220；strict labels：0；strict exclusion：`corporate_action_coverage_blocked=220`。
- Research labels：840；frozen dataset rows：210；corporate coverage：`research_only_degraded`。
- Dataset content hash：`sha256:316bbfad1b3daea009d0e50d6e80e84e02d63fd09ed01f79a706d597963d4634`。
- Dataset manifest hash：`sha256:c21f1b1af779da1ed13273644b59ac43995bf6f22e63e6d18044d6948f9ca62b`。

## Training freeze

- Split：2 個 expanding trading-calendar purged walk-forward folds（`fold-001`、`fold-002`）。
- Challengers：linear 與 histogram gradient boosting；相同 feature schema/folds。
- OOF selection：linear；research alpha=5000 bp；production alpha=0。
- Rule comparison blocker：目前 B dataset 無 governed persisted rule champion score；本 rehearsal 明確使用 neutral-zero baseline，不冒充 rule champion。
- Max train decision date：`2024-10-02`。
- Max train label available date：`2024-11-04`。
- Max blend-selection label available date：`2024-08-29`。
- Model artifact hash：`sha256:39ee2982aa184e14fa21ee5e8bd61f9570126eafa1f5b6dd6d13d23e417ae587`。
- Model manifest hash：`sha256:e2c45c85d04dda07c2afbbb2c2aad5743b71cbcdac34786c03ff8c9a0963d4c4`。
- 全缺 ADX/industry-relative 欄位由 fold-only imputer 保留 frozen 20-column shape；未補成來源觀測值。

## Locked-OOS preflight

使用 `--confirm-locked-oos` 執行實際 preflight，並將 OOS path 指向不存在的 sentinel 檔。結果：

- exit code：2（預期 blocked）。
- blocker：`dataset_not_formal_oos_eligible`。
- `executed=false`。
- `oos_payload_read=false`。
- `production_alpha_bp=0`。

這證明 corporate coverage unknown 會在任何 2025 read 前 fail closed。2025 locked OOS **未執行**；沒有 metrics、沒有 model win/loss 判斷，也沒有調參重跑。

## Blockers 與後續 gate

1. E2 formal audit 的 corporate-action coverage 仍 unknown，strict dataset 為 0 rows。
2. Fundamental eligible=0，Core 繼續完全排除 fundamentals。
3. 缺 governed persisted rule champion score，不能完成正式 champion/blend comparison。
4. 只有 corporate coverage、clean dataset generation 與 rule baseline 都完成後，才可建立新 generation 再做一次 locked-OOS preflight；不得覆寫本 generation。
5. Daily inference 仍由 F workstream 負責；promotion、production scheduler、Recommendation/Advice 整合全部未授權。
