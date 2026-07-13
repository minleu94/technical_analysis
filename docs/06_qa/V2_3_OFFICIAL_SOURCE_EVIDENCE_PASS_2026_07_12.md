# V2.3 Official Source Evidence Pass

> 日期：2026-07-12
> 狀態：官方來源存在性與初步頻率證據已補；所有來源仍為 `requires_human_acceptance`，`downstream eligibility=none`。

## 已確認的一手來源

| Source group | 官方入口 | 已確認內容 | 尚缺 Gate 證據 | 建議決議 |
|---|---|---|---|---|
| TWSE 三大法人 / 融資融券 / 停止交易 / 除權息 | `https://openapi.twse.com.tw/` | 官方 Swagger，Base URL `/v1`；可見集中市場融資融券餘額、暫停交易證券、除權除息預告等 endpoints。 | 個股三大法人 endpoint 精確 contract、歷史 retention、發布完成時間、逐列 available-date、rate limit 與再散布審核。 | `deferred_pending_contract_evidence` |
| TPEx 三大法人 / 融資融券 / 停復牌 / 漲跌停未成交 | `https://www.tpex.org.tw/openapi/` | 官方 OAS3；可見 `tpex_3insti_daily_trading`、`tpex_mainboard_margin_balance`、`tpex_spendi_today/history`、`tpex_ceil_non_trading`。 | endpoint schema/version snapshot、發布完成時間、歷史 retention、available-date、rate limit 與使用條款審核。 | `deferred_pending_contract_evidence` |
| TDCC 集保戶股權分散 | `https://openapi.tdcc.com.tw/` `/v1/opendata/1-5` | 官方 OpenAPI；官方查詢頁說明資料以每週最後一個營業日收盤後庫存歸戶編製，屬週頻。 | API version snapshot、實際發布延遲、歷史 retention、缺週政策、rate limit 與再散布條款審核。 | `deferred_pending_contract_evidence` |

## 授權邊界

- TWSE 一般網站使用條款指出，未取得書面同意不得任意重製、散布等；經「政府資料開放平臺」授權的資料例外。因此不能僅因 endpoint 公開就推定所有用途或再散布均獲授權。
- TPEx 即時／交易資訊另有供給使用契約與收費制度；OpenAPI 與付費交易資訊的邊界仍需逐 endpoint 判定。
- TDCC 已提供官方 OpenAPI 與開放資料入口，但本次未找到足以直接批准產品內再散布或 production ingestion 的完整條款證據。

## PIT / Look-ahead 判讀

1. `observation_date`、交易日或週末資料截止日不得直接當成 `available_date`。
2. 正式 ingestion 必須保存實際取得時間與來源版本；同日資料在官方發布完成前不可供當日 decision。
3. TDCC 週資料須以實際發布可得日作 Gate，不可用「每週最後營業日」回填為決策當日可得。
4. 缺資料、schema drift、outage 或 future available-date 一律 fail-closed；不得補值進 Score / Advice / Portfolio。

## 結論

官方候選入口已足以支持 adapter / diagnostics 的後續工程研究，但不足以把任一 P0 source 改為 `accepted`。下一步需逐 endpoint 保存 schema/version、實測取得 timestamp、coverage / missing 統計與具名 license review，之後再向 data-governance owner提出 `accepted / limited / rejected / deferred` 決策卡。
