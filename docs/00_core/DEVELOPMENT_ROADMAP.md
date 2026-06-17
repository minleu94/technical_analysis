# DEVELOPMENT_ROADMAP（Roadmap Hub）

> **最後更新**：2026-06-17
> **定位**：本文件是 Roadmap Hub，不再保存完整歷史長文。它負責指向目前狀態、6 個月工程路線、系統架構與歷史歸檔。

---

## 1. 文件權威邊界

本專案改採 **Scoped SSOT（分範圍單一真相來源）**，不再由單一 Roadmap 文件承擔所有決策、歷史與架構資訊。

| 文件 | 權威範圍 |
|---|---|
| [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) | 目前狀態、當前工作模式、本週優先事項與高風險區。 |
| [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) | 未來 6 個月可執行工程路線、里程碑、交付物與驗收標準。 |
| [system_architecture.md](../01_architecture/system_architecture.md) | 目前系統架構、模組邊界、資料流與高風險技術邊界。 |
| [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) | 文檔導航與文件所在位置，不作為功能或狀態事實來源。 |
| [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md) | 舊 Roadmap 未完成事項的逐項處置、移交月份與結案 Gate。 |
| [DEVELOPMENT_ROADMAP_LEGACY_2026_06.md](../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md) | 舊線性 Phase、歷史 Done、舊 Roadmap current section；只作追溯，不作目前狀態依據。 |

若文件描述衝突，依「該主題的權威文件」判斷；例如目前狀態看 Snapshot，未來 6 個月看 6M Roadmap，架構看 system architecture。

---

## 2. 系統定位

這不是每天吐股票的工具，而是一個可驗證、可回溯、可演化的台股投資決策系統。

目前產品已形成三個已落地的產品閉環，並新增一個未來目標閉環：

1. **資料與市場狀態閉環**：Update → SQLite 狀態 → Market Watch / Smart Money → 候選池。
2. **研究驗證閉環**：Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Promote。
3. **持倉檢查閉環**：Recommendation / Backtest → Portfolio → Condition Monitor / Chip Monitor → Journal → 回到研究。
4. **每日決策閉環（v1）**：Market Intelligence → Daily Decision Desk → Watchlist Trigger / Portfolio Alert / Research Input。此閉環已接上主 UI 首頁（Daily Decision Desk），其餘 section 仍逐步補齊 providers。

---

## 3. 目前執行狀態

目前狀態以 [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) 為準。短版摘要如下：

- 三個產品閉環的基礎與主要深化已完成。
- Strategy & Scoring Governance 增量 A / B 與 10 檔 fixed / quantile OOS 實證已完成；交易樣本與 Regime coverage Gate 通過，quantile 未優於 fixed 並維持 opt-in。
- Phase 5 已完成圖表渲染優化、批次回測並行化、大表格分頁與 Excel 報告；PDF 仍待後續。
- Month 2 M2-A / M2-B / M2-C 與 final registry governance gate 已完成：參數與權重契約、Research Run Registry 基礎保存、Comparability Service、Registry 比較子頁、Registry-based Promote Gate、補償 / reconciliation 防線與文件收尾均已落地。
- Portfolio 已具備策略/價格監控、停損停利警示、籌碼監控與 Smart Money 下鑽。
- Month 5 Fundamental Layer v1 已完成 closeout：月營收、季度財報、P/E valuation、Fundamental provider/service、available_date gate 與 abnormal diagnostics 已落地；只輸出 factor records / diagnostics 與風險提示，不接 `ScoringEngine`。
- 後續要提升「準確度」必須先建立實證比較、factor attribution、資料因子層與實驗治理，不應直接把新資料硬塞進 scoring engine。

---

## 4. 下一步 Next

未來 6 個月工程主線以 [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) 為準；產品北極星與長期能力圖像見 [system_vision_specification.md](../01_architecture/system_vision_specification.md)。

目前立即執行優先順序：

1. **已完成：Fixed / Quantile 真實 Walk-forward 實證**
   - 10 檔股票、每檔 8 個 OOS fold，資料版本、成本與成交假設固定。
   - Fixed 57 筆、quantile 79 筆交易與 100% Regime coverage 通過 Gate。
   - Quantile 未優於 fixed，維持 opt-in，不宣稱改善績效或穩健度。

2. **已完成：Month 3 Factor Layer v1 與 Portfolio Replay 可信度**
   - Month 2 Registry governance gate 已關閉。
   - Factor DTO / registry / Look-ahead gate / adapters / FactorService snapshot/contribution serialization 已落地；`ResearchRunService.save_run()` 已接入 `factor_snapshot` / `factor_contributions` 實際寫入流程，推薦組合回放、單股回測、批次回測與固定組合 per-stock 保存都能供給 factor records / metadata。
   - 推薦組合回放已具備現金帳、權重、再平衡、未成交、Liquidity、成本、整股 sizing、weight exposure 與 Gap risk labels；更細的零股、價差、完整撮合與 Gap 實際成交模型列為後續深化，不阻塞 Month 4。

3. **已完成：Month 5 Fundamental Layer v1**
   - Month 4 Daily Decision Desk v1 已以 service-backed daily workflow 收尾，UI 只讀 service snapshot，不重算 scoring、screening、portfolio、broker flow 或 liquidity。
   - Month 5 已完成 Fundamental Layer 的保守接入：正式 fundamental tables、月營收 / 季度財報 / P/E records、Fundamental provider/service、Revenue / statement / valuation adapters、available_date gate 與 diagnostics 已落地。P/B、P/S、官方歷史 point-in-time 公告日與更完整 valuation policy 保留為後續 residual。

4. **進行中：Month 6 Strategy Lifecycle 與 Portfolio Feedback v1**
   - 已完成第一輪資料契約與 service：Promote / demote / retire rule engine、StrategyDriftDetector、Regime compatibility、append-only lifecycle evidence、Portfolio post-trade attribution、Live vs research gap report 與 Portfolio Review snapshot。
   - Registry-based Promote Gate 已改走 Month 6 lifecycle gate，成功升級後可保存 applied evidence；demote / retire 先保存 proposed evidence；持倉管理新增「生命週期回顧」分頁。v1 不直接改 scoring、回測績效、Portfolio PnL 或 fundamental factor 權重。

5. **P2：Phase 5 研究輸出後續**
   - PDF 規格化報告仍待後續，屬研究輸出 backlog，不阻塞 Month 3 / Month 4。

6. **P3：文件治理持續檢查**
   - Snapshot、6M Roadmap、Architecture、Index、Agent 指引已採 Scoped SSOT；後續功能變更需依 Coverage Map 同步更新入口摘要。
   - 清理仍引用舊 Phase / 舊 UI 路徑的 Active 文件，並維持 Manual completeness Gate。

---

## 5. Blockers / Risks

- **回測與推薦不可宣稱更準**：真實 walk-forward 已完成，但結果未證明 quantile 優於 fixed。
- **Look-ahead bias**：任何策略、回測、推薦、factor、benchmark、停損停利與標準化改動都必須先自查資料可得日。
- **金融核心數值邊界**：核心金額、交易成本、倉位、PnL 與風控不可新增裸 `float`；必須使用 `Decimal`、整數單位或明確標示的 analytics / visualization 邊界。
- **資料因子擴充風險**：營收、財報、三大法人、估值與籌碼因子必須走 factor layer，不得直接污染既有 scoring engine。
- **Daily Decision Desk 降級顯示風險**：Daily Decision Desk v1 已完成 Month 4 收尾，但各 section 仍可能因 provider 缺值降級為 `MISSING` / `DEGRADED`；文件與 UI 必須持續揭露 quality / warnings，不得誤導為資料永遠完整。
- **文件權威混淆**：Roadmap Hub 只指向權威文件；不要把完整歷史、架構細節與長期研究筆記重新塞回本文件。

---

## 6. 歷史與追溯

- 舊版完整 Roadmap 已歸檔至 [DEVELOPMENT_ROADMAP_LEGACY_2026_06.md](../09_archive/DEVELOPMENT_ROADMAP_LEGACY_2026_06.md)。
- 舊 Roadmap 未完成事項的唯一處置見 [LEGACY_ROADMAP_CARRYOVER.md](LEGACY_ROADMAP_CARRYOVER.md)。
- 已執行完畢的短期行動計畫見 [NEXT_ACTION_PLAN.md](../09_archive/NEXT_ACTION_PLAN.md)。
- 文檔重組與刪除規則見 [DOCUMENTATION_STRUCTURE.md](DOCUMENTATION_STRUCTURE.md)。

---

## 7. 更新記錄

- 2026-06-13：將 Roadmap 從單一最高權威文件重構為 Roadmap Hub；引入 Scoped SSOT，新增 6 個月工程 Roadmap，並將舊 Roadmap 完整歸檔。
- 2026-06-13：新增 Legacy Carryover Matrix，逐項承接舊 Roadmap 未完成事項並設定 Month 3 前結案 Gate。
- 2026-06-15：依 IDS 願景重排 Roadmap Hub 的短版 Next，將 Month 3 補強為 Factor Layer + Portfolio Replay 可信度，並將 Daily Decision Desk 明確列為 Month 4 v1 首頁，其他 section 逐步接線。
- 2026-06-16：完成 Month 4 Daily Decision Desk 收尾定位，將短版 Next 轉向 Month 5 Fundamental Layer preflight，並保留 Daily Decision Desk quality / warnings 降級風險。
- 2026-06-17：完成 Month 5 Fundamental Layer v1 closeout，Roadmap Hub 的短版 Next 進入 Month 6 Strategy Lifecycle 與 Portfolio Feedback。
- 2026-06-17：啟動並完成 Month 6 Strategy Lifecycle / Portfolio Feedback v1，新增 lifecycle gate、drift detector、post-trade attribution、Portfolio Review snapshot 與持倉管理生命週期回顧分頁。
- 2026-06-17：補上 Month 6 lifecycle residual，新增 append-only lifecycle evidence、latest state projection 與 demote / retire proposed evidence 保存。
