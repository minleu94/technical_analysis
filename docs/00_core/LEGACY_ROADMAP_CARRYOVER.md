# 舊 Roadmap 移交矩陣

> **最後更新**：2026-06-13
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
| 指標參數改進（RSI/MACD/KD/ADX/MA/ATR/BBANDS） | 移交 | Month 2「參數與權重治理」 | 建立 Indicator Parameter Registry；參數具單位、範圍、預設值、版本與適用資料頻率；研究 run 可保存完整參數快照。 |
| `buy_score` / `sell_score` 改為分位數 | 已完成機制；實證移交 | 機制已完成；真實績效比較在 Month 1 | fixed / quantile 雙模式、Expanding T-1、60 個有效觀測暖機與推薦橫斷面百分位已完成；Month 1 必須用相同資料與成本完成實證。 |
| 推薦系統參數改進 | 移交 | Month 2「參數與權重治理」 | 推薦技術、圖形、量能權重不得只存在硬編碼；建立可版本化 Recommendation Weight Contract，並保存到 Research Run。 |
| 完整測試與穩定性驗證 | 移交 | Month 1 基準線；Month 2 Registry；之後為持續 Gate | 完成真實股票池 OOS 比較、資料版本鎖定、成本與成交假設鎖定；後續 promote 必須讀取可追溯驗證結果。 |
| 大表格分頁 | 移交 | Month 1「Phase 5 最小可用輸出」 | SQLite Inspector 與至少一個大型研究結果表具分頁或虛擬捲動；大量資料不得一次載入造成 UI 假死。 |
| 匯出研究報告（Excel / PDF） | 移交 | Month 1「Phase 5 最小可用輸出」 | 回測 run 與推薦回放至少可匯出一種規格化研究包；Excel/PDF 均有明確 schema 與缺失資料標示。 |
| 回測結果摘要模板 | 移交 | Month 1「Phase 5 最小可用輸出」 | 報告包含資料版本、策略版本、參數、成本、成交假設、Regime、benchmark、風險與驗證狀態。 |

## 3. 舊 Roadmap current section 的後續工作

| Legacy 後續工作 | 處置 | 新版落點 | 驗收定義 |
|---|---|---|---|
| fixed / quantile 真實 walk-forward 比較 | 移交 | Month 1 | 同股票池、資料版本、成本、成交假設與窗口；無論結果是否改善都保存。 |
| 推薦組合跨 run 比較 | 移交 | Month 2 | 至少比較 3 個策略版本或參數組合的 OOS 指標。 |
| Benchmark-relative attribution | 移交 | Month 2 | 可對 TAIEX、產業與 buy-and-hold 顯示超額報酬與風險差異。 |
| Factor / failure attribution | 移交 | Month 3 與 Month 6 | 研究 run 保存 factor contribution；Portfolio 可區分訊號、執行、資料與市場落差。 |
| 自動參數建議 | 被取代 | Month 2 Cross-run + Month 6 策略生命週期 | 不直接做黑箱自動調參；先用可追溯 run 比較與 rule-based promote/demote/retire。 |
| 清理過期 `app_module/README.md`、`ui_qt/README.md` | 已納入本次文件重構 | 2026-06-13 Documentation Patch Pass | README 必須反映 `ui_qt` 主入口、目前 service 邊界與已完成 Phase。 |

## 4. Carryover Gate

新版 Roadmap 可以執行 Month 1 與 Month 2，但 **Month 3 Factor Layer 不得在下列項目仍無正式結果時宣告開始**：

1. fixed / quantile 真實 walk-forward 比較已完成並保存。
2. Phase 5 最小可用輸出已有實作結果，不只是設計稿。
3. Indicator Parameter Registry 與 Recommendation Weight Contract 已完成或有正式取消決策。
4. Research Run Registry 能保存資料、策略、參數、成本與成交假設。
5. 本矩陣每個項目都有完成證據、移交狀態或正式決策記錄。

這個 Gate 防止舊 Roadmap 尚未結案時，直接用新資料源或新 Factor 擴張系統。

## 5. 結案判定

- 舊 Roadmap 文件維持 Archive，不再回寫新進度。
- 新進度只更新 `PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md` 與對應專題文件。
- 當本矩陣所有「移交」項目完成後，保留本文件作為歷史交接證據，不刪除。
