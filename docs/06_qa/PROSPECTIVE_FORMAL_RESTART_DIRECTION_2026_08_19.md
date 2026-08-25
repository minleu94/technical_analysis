# Prospective Formal Restart Direction（2026-08-19）

> 狀態：`owner_direction_approved / documentation_only / restart_execution_not_started`
>
> 決策識別：`owner-direction:prospective-formal-restart:20260819:v1`
>
> 安全狀態：`formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`broker_order_allowed=false`。

## 1. 本次定案

Owner 已核准後續長任務採用下列唯一方向：

1. **建立新的未來 clock**：不重建、不沿用，也不回填已錯過的 `clock:prospective:20260819:v1`。下一個長任務必須在執行當下重新取得台北時間與官方交易日證據，選擇仍在未來、且至少保留一個完整準備日的 TWSE／TPEX 共同交易日，建立新的 clock identity。
2. **Rule Champion 由 Codex 提案**：Codex 必須從現有、可重播、版本化且完全規則式的正式路徑中提出一個首選 Rule Champion，列出精確設定、策略版本、政策版本、分數設定 hash、股票池 hash、成本與風控假設，以及不採用其他候選的理由。不得為了讓 ML 容易勝出而調弱 Rule baseline。
3. **產業歸屬採官方來源**：上市股票使用 TWSE 上市公司基本資料 `t187ap03_L`；上櫃股票使用 TPEX 上櫃公司基本資料 `t187ap03_O`。只有 prospective clock 的股票池明確含興櫃時，才另外納入 TPEX `t187ap03_R`；否則興櫃不在本輪範圍。
4. **Broker 維持關閉**：本方向不建立、不測試、不註冊任何券商下單、真實成交、自動再平衡或自動平倉路徑。Clock、Rule history、Portfolio ledger、PIT sector、Formal OOS、promotion 與 broker 是不同權限；任何前置 Gate 通過都不得改變 `broker_order_allowed=false`。

本文件只凍結方向與責任，不建立 clock bytes、Rule snapshot、Portfolio transition、PIT sidecar、Formal OOS、shadow day、promotion credit 或 scheduler 狀態。

## 2. 新未來 clock 的選日規則

下一個長任務不再等待另一輪模糊的「請選未來日期」，而是依本次 owner 核准的決策規則執行：

1. 以執行當下的 `Asia/Taipei` 時間為基準，不使用文件日期或美國本機日期代替。
2. 讀取並保存官方 TWSE 年度休市／交易日證據；TPEX 必須確認同日可交易。週末或任一市場休市日不得選用。
3. Activation day 必須嚴格晚於 owner direction／執行 preflight 的台北日期，並至少保留一個完整準備日，供 Rule Champion、PIT sector、cash seed、frozen model／policy identities 與 strict readiness 凍結。
4. 若候選日已太近、官方來源不可用、三個 producer 尚未 ready，必須順延到下一個合格共同交易日；不得壓縮準備日、改用 same-day activation 或補寫過去日期。
5. 新 clock 使用新的 clock id、owner decision binding、manifest hash 與受控路徑；舊 `clock-20260819` 目錄與文件 hash 只保留歷史追溯，不能被新 clock consumer 接受。

這是 owner 對「選日方法」的明確授權。Codex 可依此方法提出並建立新的 planned clock，不必再次詢問抽象方向；但必須在交付中列出實際選定日期、官方證據、準備日與所有 hash，讓 owner 可稽核。

## 3. Rule Champion 提案準則

Rule Champion 的目的，是提供 ML 必須公平擊敗的正式規則基準，不是挑一個容易被擊敗的弱模型。Codex 提案必須符合：

- 使用目前正式 Recommendation／Portfolio 規則路徑可實際產生的輸出，不得使用 research-only、Teacher label、future target 或手動拼裝分數。
- 所有權重、門檻、成本、現金、單檔與產業上限均版本化；金融核心使用整數基點、整數股數、最小貨幣單位或 `Decimal`。
- 決策日只使用 T-1 前已取得資料；股票池、排序、產業與可成交性都要保存 point-in-time lineage。
- 優先採「目前 active／promoted、實際被正式 Rule path 消費」的單一版本；若目前沒有唯一 active version，Codex 必須提出一個首選與最多兩個替代方案，並以可重播性、穩定性、資料覆蓋、成本後結果與風控完整度比較。
- 不因當次 ML candidate 的表現調整 Rule；Champion 凍結後，同一 clock 期間不得看過 Formal OOS 結果再改規則。

Codex 負責完成候選盤點、比較與首選提案。**Owner 只需在看到精確 proposal 後，對「接受哪一個 Rule Champion identity」做一次明確決議**；在這個具體 proposal 出現前，不要求 owner 自行設計策略或提供 hash。

## 4. 官方產業來源與 PIT 邊界

正式來源方向固定如下：

| 市場 | 官方來源 | 專案端點 | 用途 |
|---|---|---|---|
| 上市 | TWSE 上市公司基本資料 | `https://openapi.twse.com.tw/v1/opendata/t187ap03_L` | 公司代號、產業別與出表日期 |
| 上櫃 | TPEX 上櫃公司基本資料 | `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O` | 公司代號、產業別與出表日期 |
| 興櫃（條件式） | TPEX 興櫃公司基本資料 | `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R` | 只有 clock universe 明確包含興櫃時才啟用 |

每次 capture 必須保存 source id、endpoint、授權條款識別、HTTP／raw bytes hash、抓取時間、來源出表／publication 時間、available time、effective date、canonical rows hash、股票池 hash 與 clock id。來源沒有可證明的 publication／available time、回傳 schema 不符、產業代碼未知或股票缺列時，該列必須 fail closed。

這些官方基本資料屬「從新 clock 往後累積」的 first-seen prospective PIT 來源。不得把當期快照倒灌成 2014–2026 歷史產業歸屬，也不得用現有 `companies.csv` 的下載時間冒充過去可得時間。

## 5. 責任分工

| 工作 | Codex 可完成 | 必須由 Owner 決議 | 理由 |
|---|---:|---:|---|
| 新 clock 日期 preflight、官方日曆證據與 planned manifest | 是 | 否；本文件已核准選日方法 | 屬可重播的工程執行；不得越過未來日期與準備日規則 |
| Rule Champion 候選盤點、比較與首選 proposal | 是 | 否 | Codex 應先把具體方案與 hashes 準備完整 |
| 接受特定 Rule Champion identity | 否 | 是，一次 | 這會凍結正式比較基準，不能由產生 proposal 的同一角色自我核准 |
| TWSE／TPEX source adapter、prospective capture、lineage 與 QA | 是 | 只有來源授權政策出現新歧義時 | 官方來源與使用方向已核准；仍須保留 license 與 source acceptance 證據 |
| Portfolio／Rule／PIT 三份 manifest 與 strict readiness | 是 | 不需逐步核准 | 只要沿用既有 PFS contract、create-only、no-backfill 與 controlled-store 邊界 |
| 自然成熟 shadow 日 | 不能加速，只能每日可靠蒐集 | 否 | 必須等待真實交易日與各 horizon outcome 成熟 |
| Promotion 簽章、非零 ML alpha | 否 | 是 | 這是 ML 開始影響正式配置的獨立人類授權 |
| Broker／真實下單 | 否 | 未授權，維持關閉 | 不屬本計畫；即使 promotion 通過也不自動開啟 |

## 6. 下一個長任務的完成順序

1. 唯讀 preflight：確認舊 clock 已失效、目前台北時間、官方共同交易日、受控路徑、secret-store configured flag 與現有 Rule versions。
2. 產出 Rule Champion proposal：一個首選、必要時最多兩個替代方案；列出完整 identity、比較證據與 Look-ahead 自查。
3. 建立官方 TWSE／TPEX sector source registry 與 prospective first-seen capture producer；先用 fixture／staging 驗證，再接受控路徑。
4. 在 Owner 對具體 Rule Champion 做一次接受後，依本文件選日規則建立新 clock，凍結 Rule／policy／universe／source／model／calibration／evaluation identities。
5. 產生 clock-bound Rule history、首日 simulated Portfolio transition 與 PIT sector manifest，執行 strict readiness。
6. Readiness 通過後才啟動低 CPU daily capture；不啟動 legacy Direct／OOC rebuild，不重訓、不 promotion、不變更 alpha。
7. 讓 shadow observations 自然成熟，再處理 calibration、Formal OOS、promotion review；Broker 在整條路徑中持續為 false。

## 7. Definition of Done

下一個長任務只有同時滿足下列條件才算完成第一階段：

- 新 clock 的實際選日、官方交易日證據、至少一個完整準備日與新 identity 可稽核。
- Rule Champion proposal 具單一首選、完整設定與 hashes，且沒有使用 Formal OOS 結果調參。
- TWSE／TPEX source registry 與 prospective PIT capture 通過 fixture、schema、license、publication／available time、hash、unknown-code 與 missing-row tests。
- 三份 clock-bound manifests 存在並通過 strict readiness；沒有使用舊 `clock-20260819`、research history 或 current snapshot 回填。
- `formal_oos_allowed=false`、`production_blend_alpha_bp=0`、`promotion_eligible=false`、`broker_order_allowed=false` 在產物、測試與文件中一致。
- 沒有啟動重型 ML rebuild、auto promotion、broker、真實持倉寫入或歷史回填。

## 8. 明確非目標

- 本方向不要求本輪解決機率校準、`rebalance_worthwhile` class coverage、20 個成熟 shadow days 或 promotion 簽章。
- 不宣稱 ML 已正式生效；在非零 alpha 另行獲准前，所有正式 Tab 仍是 Rule-only。
- 不把 source endpoint 可連線直接當成 source acceptance；仍須保存授權、品質、PIT、coverage、rollback 與 reviewer evidence。
- 不建立 broker adapter，不下單，不把 UI 持倉當成 simulated clock seed。

## 9. 2026-08-26 owner 單次同日 pre-open 修正

Owner 在 `2026-08-26` 開盤前明確要求排除「必須再等一個完整自然準備日」造成的循環延期，並要求由 Codex 直接建立當日三份正式 input。這項較新的具體決議只對 `clock:prospective:20260826:v1` 形成下列窄化修正，取代第 2 節第 3、4 點在本 clock 的完整準備日要求；其餘 no-backfill、PIT、T-1、controlled store 與安全 Gate 均不變：

1. 同日 activation 只可在當日 `08:30:00 Asia/Taipei` PIT boundary 前，以具名 `prospective-same-day-preopen-owner-override.v1` 寫入新的 create-only clock；沒有 override、已達 PIT boundary 或 activation 已過去時仍 fail closed。
2. Override 必須保存 owner override id、實際 timezone-aware timestamp、activation day、固定 reason code，且 `historical_backfill_allowed=false`、`same_day_preopen_only=true`；不能成為任意日期 bypass。
3. 2026-08-26 的 Portfolio T-1 固定為 2026-08-25。市場 DB 已有該日 `1955` rows／`1955` symbols；不得刪除這一天，也不得改用 2026-08-26 same-day close。
4. TWSE／TPEX 官方日曆必須證明 2026-08-26 為共同交易日；官方 `t187ap03_L`／`t187ap03_O` raw bytes 的 first-seen `available_at` 必須早於 2026-08-26 08:30，effective date 才可設為 2026-08-26。
5. Rule／Portfolio 仍只能在真實 09:00 boundary 後建立，三份正式 input 必須以 staging transaction 一起發布並通過 strict readiness；任何失敗不得留下 partial formal output。
6. 本修正不授權歷史回填、ML training／retraining、Direct／OOC watcher、promotion、非零 alpha、broker adapter、下單、自動再平衡或自動平倉。

具體 clock、hash、官方來源與一次性操作證據見 [2026-08-26 same-day staging record](PROSPECTIVE_FORMAL_RESTART_CLOCK_2026_08_26_STAGING.md)。
