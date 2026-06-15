# DEVELOPMENT_ROADMAP（Roadmap Hub）

> **最後更新**：2026-06-14
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

目前產品已形成三個閉環：

1. **資料與市場狀態閉環**：Update → SQLite 狀態 → Market Watch / Smart Money → 候選池。
2. **研究驗證閉環**：Recommendation Profile → Research Lab / Backtest / Replay / Walk-forward → Promote。
3. **持倉檢查閉環**：Recommendation / Backtest → Portfolio → Condition Monitor / Chip Monitor → Journal → 回到研究。

---

## 3. 目前執行狀態

目前狀態以 [PROJECT_SNAPSHOT.md](PROJECT_SNAPSHOT.md) 為準。短版摘要如下：

- 三個產品閉環的基礎與主要深化已完成。
- Strategy & Scoring Governance 增量 A / B 與 10 檔 fixed / quantile OOS 實證已完成；交易樣本與 Regime coverage Gate 通過，quantile 未優於 fixed 並維持 opt-in。
- Phase 5 已完成圖表渲染優化、批次回測並行化、大表格分頁與 Excel 報告；PDF 仍待後續。
- Month 2 M2-A / M2-B / M2-C 與 final registry governance gate 已完成：參數與權重契約、Research Run Registry 基礎保存、Comparability Service、Registry 比較子頁、Registry-based Promote Gate、補償 / reconciliation 防線與文件收尾均已落地。
- Portfolio 已具備策略/價格監控、停損停利警示、籌碼監控與 Smart Money 下鑽。
- 後續要提升「準確度」必須先建立實證比較、factor attribution、資料因子層與實驗治理，不應直接把新資料硬塞進 scoring engine。

---

## 4. 下一步 Next

未來 6 個月工程主線以 [ROADMAP_6M_ENGINEERING.md](ROADMAP_6M_ENGINEERING.md) 為準。

目前立即執行優先順序：

1. **已完成：Fixed / Quantile 真實 Walk-forward 實證**
   - 10 檔股票、每檔 8 個 OOS fold，資料版本、成本與成交假設固定。
   - Fixed 57 筆、quantile 79 筆交易與 100% Regime coverage 通過 Gate。
   - Quantile 未優於 fixed，維持 opt-in，不宣稱改善績效或穩健度。

2. **P1：Month 3 Factor Layer v1 實作**
   - Month 2 Registry governance gate 已關閉。
   - Factor DTO / registry / Look-ahead gate / adapters / FactorService snapshot serialization 已開始落地；下一步是把 `factor_snapshot` / `factor_contributions` 接進實際 Research Run 寫入流程，不直接接營收與法人。

3. **P2：Phase 5 研究輸出後續**
   - PDF 規格化報告仍待後續。

4. **P3：文件治理持續檢查**
   - Snapshot、6M Roadmap、Architecture、Index、Agent 指引已採 Scoped SSOT；後續功能變更需依 Coverage Map 同步更新入口摘要。
   - 清理仍引用舊 Phase / 舊 UI 路徑的 Active 文件，並維持 Manual completeness Gate。

---

## 5. Blockers / Risks

- **回測與推薦不可宣稱更準**：真實 walk-forward 已完成，但結果未證明 quantile 優於 fixed。
- **Look-ahead bias**：任何策略、回測、推薦、factor、benchmark、停損停利與標準化改動都必須先自查資料可得日。
- **金融核心數值邊界**：核心金額、交易成本、倉位、PnL 與風控不可新增裸 `float`；必須使用 `Decimal`、整數單位或明確標示的 analytics / visualization 邊界。
- **資料因子擴充風險**：營收、財報、三大法人、估值與籌碼因子必須走 factor layer，不得直接污染既有 scoring engine。
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
