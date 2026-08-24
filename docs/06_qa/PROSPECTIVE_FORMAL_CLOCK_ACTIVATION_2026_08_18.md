# Prospective Formal Clock Activation Handoff（2026-08-18）

> 狀態：`scheduled / inputs_deferred / formal_oos_allowed=false`
>
> 本文件記錄 owner 在美國加州時間 2026-08-17 13:30 提供的啟動意圖，以及只到 deferred staging 的可驗證交接。它不是 Portfolio transition、Rule snapshot、PIT sidecar 或 promotion 證據。

> **2026-08-19 後續裁決**：本 handoff 的 `2026-08-19` 決策日已經過去，且 canonical clock／activation manifest bytes 與三份正式輸入未在時限內成立，因此此 clock 只保留歷史追溯，禁止重建、沿用或回填。新的 owner 方向見 [Prospective Formal Restart Direction](PROSPECTIVE_FORMAL_RESTART_DIRECTION_2026_08_19.md)。

## Owner 啟動邊界

| 項目 | 值 |
|---|---|
| Owner activation timestamp | `2026-08-17T13:30:00-07:00` |
| 同一時刻台北時間 | `2026-08-18T04:30:00+08:00` |
| Prospective clock | `clock:prospective:20260819:v1` |
| 第一個可用決策日 | `2026-08-19`，決策時間 `08:30:00`（Asia/Taipei） |
| Clock manifest | `prospective-formal-simulated-portfolio-clock.v1` |
| Clock logical hash | `sha256:0a79864665bb5abf0ba4c030f6cdb0358d8fdab75b4a15896c4210de2a441b0c` |
| Clock file hash | `sha256:3231a5673b13a7ae5e478384bc30a9095a8259c7e2d62a221d32331cc00f5b26` |
| Activation manifest | `sha256:025e28c56c76658facd06826d3d7cdcad33e417669a211ff102edfd38cba8c6f` |

8/18 是 owner activation 在台北的同一日期，因此不符合「activation trading day 必須嚴格晚於 owner activation date」；官方 TWSE 2026 holidaySchedule 回應中 8/19 沒有休市列，clock 以 `twse_holiday_schedule_open` 綁定該日證據。

## 目前真正的持倉來源

你在 UI 登錄的交易紀錄位於：

`D:\Min\Python\Project\FA_Data\output\portfolio\trades.jsonl`

目前只讀看到 3 筆買入紀錄（2382、3207、9985）；檔案 hash 是 `sha256:779f1d32cdeca1ddc4247f03d2bc91181974b73aad35e1ff945ffcb8180e3109`。這是 Portfolio UI 的來源資料，不是 clock 起算前的 Formal transition，也不會被倒填進 2014–2026。

Formal simulated clock 的 seed 仍是 contract 定義的 virtual cash（`cash_bp=10000`、`position_count=0`）；真實持倉保留給 Portfolio／風險觀測，不自動變成模擬策略的初始成交。

## 三個路徑的預留位置

這三個不是要你去舊資料夾尋找的檔案，而是 clock 啟動後由受控 producer 產生的 manifest。已預留下列使用者環境值與資料夾：

```text
BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH=D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260819\portfolio_ledger\manifest.json
BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH=D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260819\rule_champion_history\manifest.json
BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH=D:\Min\Python\Project\FA_Data\output\formal_prospective\clock-20260819\pit_sector_membership\manifest.json
```

目前三個 manifest 尚不存在，因此 activation 內明確記錄 `deferred=true`、`path=null`；不會因為預留路徑存在就把 readiness 判成 ready。

## 已驗證的安全結果

- deferred readiness：3 個 input、0 個 ready、3 個 deferred。
- `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`promotion_eligible=false`、`broker_order_allowed=false`。
- `heavy_rebuild_launch_allowed=false`；沒有啟動 Direct、OOC、watcher 或 ML training。
- HMAC secret 沒有被讀出、保存、輸出或改寫；目前只確認受控 secret store `configured=true`。
- calibration policy、source policy、evaluation policy 都已以 hash 凍結；這些是方法／治理規則，不代表 PIT 合法來源已到位。

## 本 handoff 當時的下一個實際關卡（歷史）

在第一個決策日以前，必須由 producer 產生並通過 strict readiness 的三份真實資料：

1. append-only simulated Portfolio ledger（至少一筆合法 T-1 transition，且產生非現金 state）；
2. controlled-store HMAC-signed Rule Champion history；
3. 具 source／license／publication／canonical hash lineage 的 prospective PIT sector sidecar。

三份同時通過後才可進入低 CPU 的每日 capture；仍不會自動開啟 legacy Direct → OOC，也不會解除 calibration、20 個成熟 shadow days、class coverage 或 promotion gates。
