# 舊 Roadmap 移交矩陣

> **最後更新**：2026-06-15
> **定位**：本文件是舊 Roadmap 未完成事項的結案與移交證據。它不新增平行 Roadmap，而是確保每個舊項目都有唯一處置。

## 1. 判讀規則

每個舊項目只能有下列一種處置：

- **已完成**：功能與必要機制已存在；若仍需實證，實證另列為獨立項目。
- **移交**：新版 6M Roadmap 有明確月份、交付物與驗收標準。
- **被取代**：舊解法已被更完整的新架構取代，並指出替代方案。
- **正式取消**：記錄不做的原因與影響。

禁止使用「之後再做」、「持續改善」或沒有月份與驗收標準的模糊狀態。

## 2. 舊 Roadmap 未勾選項目

| Legacy 項目 | 處置 | 新版落點 | 完成或驗收定義 |
|---|---|---|---|
| 指標參數改進（RSI/MACD/KD/ADX/MA/ATR/BBANDS） | 已完成 | Month 2「參數與權重治理」 | 已建立 Indicator Parameter Registry；參數具單位、範圍、預設值、版本與適用資料頻率；研究 run 可保存完整參數快照。 |
| buy_score / sell_score 改為分位數 | 已完成 | - | fixed / quantile 雙模式已完成，且已於 2026-06-14 完成 10 檔代表性個股的 OOS 實證比較，產出大盤 regime 分層歸因報告。 |
| 推薦系統參數改進 | 已完成 | Month 2「參數與權重治理」 | 推薦技術、圖形、量能權重已建立可版本化 Recommendation Weight Contract，並可保存到 Research Run。 |
| 完整測試與穩定性驗證 | 已完成 | Month 2 Registry | 2026-06-14 已完成 10 檔個股 OOS 比較、資料版本/成本/成交假設鎖定實證；並完成 Unified Research Run Registry 實作、hash integrity、crash reconciliation、UI 保存、比較 UI、promotion gate 與完整驗證。 |
| 大表格分頁 | 已完成 | Month 1「Phase 5 最小可用輸出」 | 已完成 SQLite Inspector 穩定分頁查詢與 UI 頁碼控制，解決大量資料載入 UI 假死。 |
| 匯出研究報告（Excel / PDF） | 部分完成 | Month 1「Phase 5 最小可用輸出」；PDF 移交研究輸出 backlog | Excel 報告匯出與資料完整性/追溯元數據已完成，背景 TaskWorker + 原子寫入防護；PDF 尚未完成，後續驗收需具備同等元數據、資料完整性區域與非阻塞匯出防護，但不阻塞 Month 3 Factor Layer、Portfolio Replay 可信度或 Month 4 Daily Decision Desk。 |
| 回測結果摘要模板 | 已完成 | Month 1「Phase 5 最小可用輸出」 | Excel 報告中已包含完整元數據與資料完整性檢核區域。 |

## 3. 舊 Roadmap current section 的後續工作

| Legacy 後續工作 | 處置 | 新版落點 | 驗收定義 |
|---|---|---|---|
| fixed / quantile 真實 walk-forward 比較 | 已完成 | - | 同股票池與成本。2026-06-14 以 fixed 55/45 完成 10 檔、每檔 8 個 OOS fold；fixed 57 筆、quantile 79 筆交易皆通過 20 筆最低樣本 Gate，並完成 100% Regime coverage 的分層歸因。 |
| 推薦組合跨 run 比較 | 已完成 | Month 2 | Research Lab 比較子頁支援 2-5 個 registry run，比較 OOS 指標、參數差異、Regime、benchmark 與正規化 equity；incompatible run 不產生優劣排名。 |
| Benchmark-relative attribution | 已完成 | Month 2 | Cross-run comparison 只使用 run 已保存的 benchmark results，顯示 benchmark-relative attribution，不於比較時重新抓取目前資料。 |
| Factor / failure attribution | 移交 | Month 3 與 Month 6 | Month 3 先完成更多 Research Lab 路徑的 factor contribution 與 Portfolio Replay 可信度；Month 6 再完成 Portfolio post-trade attribution，區分訊號、執行、資料與市場落差。 |
| 自動參數建議 | 被取代 | Month 2 Cross-run + Month 6 策略生命週期 | 不直接做黑箱自動調參；先用可追溯 run 比較與 rule-based promote/demote/retire。 |
| 清理過期 `app_module/README.md`、`ui_qt/README.md` | 已納入本次文件重構 | 2026-06-13 Documentation Patch Pass | README 必須反映 `ui_qt` 主入口、目前 service 邊界與已完成 Phase。 |

## 4. Carryover Gate

新版 Roadmap 可以執行 Month 1 與 Month 2，但 **Month 3 Factor Layer 不得在下列項目仍無正式結果時宣告開始**：

1. fixed / quantile 真實 walk-forward Gate 已通過；報告保留 quantile 未優於 fixed 的結果，且 quantile 維持 opt-in。
2. Phase 5 最小可用輸出已有實作結果，不只是設計稿。
3. Indicator Parameter Registry 與 Recommendation Weight Contract 已完成。
4. Research Run Registry 能保存資料、策略、參數、成本與成交假設，並支援比較、hash integrity、archive/promote guard 與 registry-based promote gate。
5. 本矩陣每個項目都有完成證據、移交狀態或正式決策記錄。

這個 Gate 防止舊 Roadmap 尚未結案時，直接用新資料源或新 Factor 擴張系統。

## 5. 結案判定

- 舊 Roadmap 文件維持 Archive，不再回寫新進度。
- 新進度只更新 `PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md` 與對應專題文件。
- 當本矩陣所有「移交」項目完成後，保留本文件作為歷史交接證據，不刪除。

## 6. 更新記錄

- 2026-06-15：對齊 IDS 願景與新版 6M Roadmap，明確 PDF 屬研究輸出 backlog，不阻塞 Month 3 / Month 4；Factor / failure attribution 拆為 Month 3 factor contribution / Portfolio Replay 可信度與 Month 6 post-trade attribution。
