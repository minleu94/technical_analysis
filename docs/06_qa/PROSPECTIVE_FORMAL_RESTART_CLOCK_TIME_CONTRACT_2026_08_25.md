# Prospective Formal Restart clock time contract

日期：2026-08-25（Asia/Taipei）

## 決策邊界

Prospective Formal Restart 的新 clock 將兩個邊界明確分開：

- `pit_decision_time=08:30:00`：只供官方公司基本資料的 prospective PIT capture 使用。
- `decision_time=09:00:00`：作為 owner-bound Rule decision 的最早 boundary，並作為首日 simulated Portfolio transition 的精確 clock time。

這個分離符合第一階段要求：PIT 等待 08:30 decision timestamp，Rule 等待 09:00 後的真實 owner-bound decision，Portfolio 使用同一個 09:00 decision boundary。

## 契約變更

`pit_decision_time` 是向後相容的 optional clock 欄位。舊 clock 若沒有此欄位，PIT validator 會沿用既有 `decision_time`，因此既有 immutable clock 與歷史 custody 不變。新 clock 若提供此欄位，必須滿足：

- 使用 `Asia/Taipei` 的無時區 local time 字串。
- 不得晚於 owner-bound `decision_time`。
- 仍由 clock manifest hash 綁定，不能在 capture 時另行改寫。

PIT publisher 會選擇 `pit_decision_time`（若存在），Rule publisher 接受不早於 `decision_time` 且不晚於實際 capture `now` 的真實 owner-bound timestamp，Portfolio publisher 維持使用精確的 `decision_time`。strict readiness report 同時保存 `decision_timestamp` 與 `pit_decision_timestamp`，分別驗證 Rule／Portfolio 與 PIT；activation custody 也可保存 optional `pit_decision_time`。Portfolio ledger 在建立 transition 時驗證輸入與 clock 的 `decision_time`，在讀回 ledger summary 時再次以同一個 immutable clock boundary 驗證；因此舊 08:30 clock 維持相容，新的 09:00 clock 不會被舊的硬編碼時間錯誤拒絕。舊 readiness／activation JSON 若沒有新欄位，validator 會依舊 clock contract 相容解讀。這是 contract clarification，不是移除 readiness、資料來源、look-ahead 或安全 gate。

## Immutable 與安全界線

- `clock:prospective:20260819:v1` 與 `clock:prospective:20260825:v1` 只能歷史追溯，不能重建、沿用或回填。
- 已建立但仍為 planned 的單時間 successor clock 也不修改；若時間 contract 不符，另建 create-only successor。
- `formal_oos_allowed=false`、ML alpha=0、`promotion=false`、`broker_order_allowed=false` 持續固定。
- 不建立 broker adapter、不下單、不自動再平衡、不自動平倉。
- 新 clock 尚未到 activation day 前，不產生 Rule／Portfolio／PIT 正式 manifest；不得用 staging 或 deferred readiness 冒充正式 input。

## 驗證證據

2026-08-25 已通過 focused contract suite：51 passed，1 個 pytest cache permission warning（不影響測試結果）；prospective regression suite：108 passed。涵蓋 clock schema、雙時間邊界、PIT capture、clock publisher、Rule publisher、Portfolio ledger、activation custody 與 strict readiness。
