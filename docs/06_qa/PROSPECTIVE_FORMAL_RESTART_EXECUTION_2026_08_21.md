# Prospective Formal Restart 執行狀態（2026-08-21）

> 狀態：`planned / scheduled / strict-readiness-pending`
>
> 本文件只記錄新 clock 的受控執行狀態；不把 deferred readiness 視為正式 evidence credit。

## 目前已建立

- clock：`clock:prospective:20260825:v1`
- activation trading day：`2026-08-25`
- 完整準備日：`2026-08-24`
- Rule Champion：`manual-rule-only-daily-rank-v1` + `foreground-owner-bound-v1`
- clock manifest：`D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260825\clock\manifest.json`
- clock manifest hash：`sha256:7321d9d6e59acd16d96811ff5cebb58775172e64e7a2313b4f2c08b880f9b866`
- activation manifest：`status=scheduled`、`inputs_deferred=true`

三個正式 input 尚未建立：

1. `portfolio_ledger\manifest.json`
2. `rule_champion_history\manifest.json`
3. `pit_sector_membership\manifest.json`

這是刻意保留的 future-date gate；在 2026-08-25 前不得用未來日期建立 Rule snapshot 或 simulated Portfolio transition。

## 官方來源 staging

- 上市：[TWSE t187ap03_L](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)
- 上櫃：[TPEX t187ap03_O](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)
- `t187ap03_R` 未啟用，因 clock universe 不含興櫃。
- staging package：`D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260825\staging\pit_source_staging.json`
- staging row count：1932；raw／canonical hash、publication／available／effective、license、clock／universe lineage 已通過。
- staging 不是正式 PIT manifest，activation day 必須重新取得當日官方 raw bytes。

## Activation day 低 CPU 手動順序

不註冊新的 scheduler；由 owner 在真實台北決策時間執行：

1. 重新抓取 TWSE／TPEX 官方 raw bytes，保存 raw hash；不得讀取 `companies.csv`。
2. 以 `scripts\capture_prospective_official_pit_sector.py --fixture-only`（不帶 `--preactivation-staging`）建立正式 PIT sidecar。
3. 以 `scripts\run_manual_rule_only_decision.py --universe-symbols-json` 產生當日 Rule-only TEMP source；只使用決策日前完整日資料。
4. 由受控 store 驗證 HMAC artifact，再執行 `scripts\publish_prospective_rule_champion_history.py`，只提交 activation 後、已到達當下的 snapshot。
5. 以 cash seed、Rule observed target weights 與 T-1 state 執行 `scripts\capture_formal_simulated_portfolio_transition.py`；不得使用 future teacher target 或 same-day advice。
6. 先發布 Portfolio ledger manifest，再將三份 manifest 一起交給 strict readiness；任一缺失或 invalid 都不得 partial start。

所有步驟固定：`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`promotion_eligible=false`、`broker_order_allowed=false`。

## Current gate result

- deferred readiness：`ready_for_future_activation`（3 inputs deferred）
- strict preflight：`waiting_for_prospective_inputs`（0/3 ready）
- calibration：policy identity 已 frozen；calibration audit 尚未通過
- shadow maturity：尚未開始，無成熟 shadow day credit
- promotion：未通過且禁止
- broker：未建立、未呼叫、禁止

## 回滾／隔離

新 clock custody 只使用 create-only／append-only；若後續 gate 失敗，保留 immutable evidence、停止 consumer 採用並建立新的 successor clock，不刪除或覆寫原始資料。舊 `clock-20260819` 不變更。Repo 變更已分三批提交（`002c36c`、`ec05c28`、`c21cd1e`）；回滾時採逐檔 review／revert，不使用 reset 或 checkout 覆寫其他 dirty changes。
