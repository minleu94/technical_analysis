# Prospective Formal Calendar Capture（2026-08-28）

## 結果

2026-08-28 以明確 `--confirm-network` 執行一次 bounded official calendar
capture，範圍為 `2026-09-01..2026-09-02`。只對下列兩個官方來源各發出一次 GET，沒有
寫市場 SQLite、Formal path、clock、scheduler 或 broker：

| 市場 | Endpoint | response bytes SHA-256 |
|---|---|---|
| TWSE | `https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule?queryYear=115` | `sha256:7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117` |
| TPEX | `https://info.tpex.org.tw/api/mktCalendar?ym=202609&lang=zh-tw` | `sha256:1105710f7b81b0eb89d6150dc5f0e1cb63a55ceeb5556ff6616e8f15c96c2f74` |

兩日的 TWSE 年表／TPEX 月表均通過 schema 與日期驗證，正規化結果為
`official-trading-calendar-bundle.v1`，`capture_mode=bounded_network`、
`network_enabled=true`、`candidate_only=true`。候選 artifact 僅保存於作業系統 TEMP：

- bundle：`C:\Users\archi\AppData\Local\Temp\technical_analysis_calendar_bundle_network_20260828_110409.json`
- bundle hash：`sha256:6cdc5fecbcdc863a7ba29ae699e5dcf9c4903a919d977773d6580d0ed01948ca`
- file hash：`sha256:22c6e869d8addcabc24ee9b6d4441b030b22933be2fa44f4e6831c5b742aab14`

## 日期 planner

將 bundle 交給 `scripts/plan_prospective_formal_clock.py` 後，在呼叫端提供合法的
owner decision timestamp 與既有 clock ids 時，第一個候選日為 `2026-09-01`，候選 clock
identity 為 `clock:prospective:20260901:planned-v1`，準備窗口從台北當日往前保留至少
一個完整 calendar day。這只是 `candidate_ready` proposal；planner 不建立 clock、不
選 same-day override、不修改 `BALDR_ML_*` path，也不給 Formal OOS／promotion／broker
權限。

本次沒有使用文件日期或舊 `clock-20260819` 回填，也沒有把 capture bundle 直接當成
新的 Formal input。真正建立新 planned clock 前，仍要由呼叫端提供可稽核的 owner-bound
timestamp／decision identity，並完成 Rule／Portfolio／PIT 三份受控 producer 與 strict
readiness；任一缺件均保持 fail-closed。

## 可重跑命令

```powershell
.\.venv\Scripts\python.exe scripts\capture_official_calendar_bundle.py `
  --start-date 2026-09-01 --end-date 2026-09-02 `
  --confirm-network `
  --output <NEW_TEMP_CANDIDATE_JSON>
```

同一 output 已存在時工具拒絕覆寫；網路未明確確認、官方回應缺日期、狀態／年月不符
或 TPEX 平日 row 不完整時，工具不建立輸出。

## 安全邊界

- `formal_clock_created=false`
- `formal_oos_allowed=false`
- `production_scheduler_allowed=false`
- `broker_order_allowed=false`
- `secret_values_emitted=false`

