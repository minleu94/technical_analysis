# TWSE T86 20 日 Candidate Source Recovery Pilot

## 結論

本次只完成 retroactive-baseline candidate research。TWSE T86 source dossier 狀態固定為 **`deferred`**；`source_accepted=false`、`formal_validation_allowed=false`、`formal_oos_allowed=false`、`production_blend_alpha_bp=0`。本結果不構成 source acceptance、正式 ingestion、forward evidence 或投資有效性證據。

建議：**停止擴張來源範圍，保留 T86 candidate adapter 並先處理 universe authority／license review。** 目前 fetch、raw conservation、normalization、lineage 與 failure semantics 足以繼續有限 candidate research，但大量 non-ordinary-security rows 與歷史 available timestamp 不可得，尚不足以進入正式來源審核。

## Endpoint 與固定窗口

- Endpoint：`https://www.twse.com.tw/rwd/zh/fund/T86`
- Params：`response=json`、`selectType=ALL`、逐日 `date=YYYYMMDD`
- 固定窗口：2026-06-11 至 2026-07-09，共 20 個由正式 `daily_prices` 唯讀解析的已完成交易日。
- Raw 與報告輸出：獨立 `DEVELOPMENT_OUTPUT_ROOT`；未寫入 repository 或正式 DB。
- `observation_date` 為交易日；`first_observed_at` 為實際 retroactive fetch UTC；歷史 `available_at=null`，未以交易日或 fetch time 猜測歷史可得時間。

## Coverage 與 conservation

| 指標 | 結果 |
|---|---:|
| requested / received / successful dates | 20 / 20 / 20 |
| failed dates | 0 |
| HTTP attempts | 20 |
| HTTP 200 | 20 |
| retry / 429 observations | 0 / 0 |
| raw rows | 284,089 |
| accepted ordinary-stock candidate rows | 21,585 |
| quarantined rows | 0 |
| explicitly ignored rows | 262,504 |
| row conservation | 284,089 = 21,585 + 0 + 262,504 |
| schema fingerprints | 1 |
| schema diffs | 0 |
| observed revision diffs | 0 |
| summed missing ordinary-stock/date observations | 17,740 |
| summed extra/non-universe observations | 262,504 |

`selectType=ALL` 會回傳大量 ETF、權證或其他非同日普通股 universe 證券。它們保留於 immutable raw bytes，parser 報告為 `outside_ordinary_stock_universe` 並計入 explicitly ignored／extra；未建立補零 row。Missing 只列 coverage gap，不代表法人交易量為零。

## Schema、revision 與 rate-limit 觀測

- 20 日皆為同一 schema fingerprint，未觀察到欄位增刪或順序 drift。
- 每個 observation date 本次只抓取一個 payload revision，未觀察到同日內容 revision；這不是「來源不會修訂」的證明。
- 20 次 request 皆第一次取得 HTTP 200，未觀察到 429、5xx 或 Retry-After；這不是正式 rate-limit policy。
- Unit tests 另以 fake transport 覆蓋 429、5xx、empty、HTML error、bounded retry、schema drift、duplicate、conflict、missing value 與 raw idempotency。

## Lineage 與安全邊界

每日 raw envelope 保存 request params、requested/retrieved UTC、HTTP status/content type/byte count、payload SHA-256、endpoint/parser version、attempt metadata 與 raw bytes。Normalized row 保存 observation date、symbol、integer share quantities、raw-row hash、raw-payload hash及 first-observed timestamp。

正式 SQLite 在 live run 前後的 SHA-256 均為 `604E8FC5C046E40FAEDDD5A6E183D088F6BD90D0E462D2C8E4E96101C0B6D8B4`；正式 DB bytes 與 mtime 未變。未呼叫 Update All、scheduler、Score、Recommendation、Advice、Portfolio、training 或 EV2 acceptance mutation。

## Expand / stop 建議

目前建議 **stop source expansion, continue bounded T86-only candidate observation**：

1. 先由 Data Governance／License owner 確認 TWSE terms、保存與再散布範圍；狀態維持 deferred。
2. 將 TWSE ordinary-stock universe authority 與 T86 missing semantics 做人工資料稽核；不得將 missing 補零。
3. 若後續需要 revision coverage，另以固定 observation date 做低頻、明確授權的 content-hash re-fetch；不得由本次單次抓取宣稱無 revision。
4. 在上述 Gate 完成前，不擴張到信用交易、TDCC、月營收、財報或券商分點，也不接正式 DB／scheduler／Score／ML。
