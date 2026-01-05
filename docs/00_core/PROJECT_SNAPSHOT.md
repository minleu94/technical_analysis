# PROJECT_SNAPSHOT（必讀｜每次開新對話先看）

> **開場 30 秒內讀完** - 只放今天的狀態，不放歷史細節

## 系統定位（一句話）

這不是每天吐股票的工具，而是一個可驗證、可回溯、可演化的投資決策系統。

## 當前狀態（以 DEVELOPMENT_ROADMAP.md 的 Living Section 為準）

> **注意**：Living Section 定義見 `DEVELOPMENT_ROADMAP.md` 的「📍 Living Section 定義」段落。

- Phase 1 ✅ / Phase 2 ✅ / Phase 2.5 ✅（核心已完成並驗證）
- Phase 3.1 ✅ / Phase 3.2 ✅ / Phase 3.3b ✅（研究閉環已完成，含 Promote / Walk-forward / Baseline / Overfitting risk / 視覺驗證）

## 現在的工作模式（你每天要用的流程）

1. Update 更新資料
2. Market Watch 看 Regime + 強弱
3. Recommendation 用 Profile 出名單 + 看 Why/WhyNot → 丟 Watchlist
4. Backtest 從 Watchlist / 一鍵送回測 → 產出報告 / Promote（如需要）

## Tech Lead 的預設任務（開場要先做什麼）

- 給出「下一步最合理的工程行動」與原因（不寫 code）
- 如需看程式碼：先提出要 review 的檔案清單與目的，等我授權 scope

## 本週優先事項（只列 3 個）

1. 以「實際使用」找出 UX/理解斷點（不是加功能）
2. 把日常流程與關鍵指標說明補齊（文件一致）
3. 對回測對標呈現方式做最後定稿（benchmark/normalize/hover）

## 高風險區（改動需謹慎）

- `app_module/backtest_service.py` / `backtest_module/*`
- `app_module/recommendation_service.py`
- Strategy registry / preset / promotion 相關服務
- UI ↔ service contract（DTO）

## 指定權威文件（需要細節再看）

- `DEVELOPMENT_ROADMAP.md` - 完整開發路線圖（Single Source of Truth）
- `DOCUMENTATION_INDEX.md` - 文檔索引
- `DOC_COVERAGE_MAP.md` - 文檔覆蓋矩陣（Documentation Agent 判斷 coverage 的規則）
- `PROJECT_NAVIGATION.md` / `PROJECT_INVENTORY.md` - 專案導航與盤點

---

**注意**：此 Snapshot 內容從 `DEVELOPMENT_ROADMAP.md` 的「Living Section」（定義見該文件的「📍 Living Section 定義」段落）與 `DOCUMENTATION_INDEX.md` 抽出的短版入口。詳細資訊請參考權威文件。

