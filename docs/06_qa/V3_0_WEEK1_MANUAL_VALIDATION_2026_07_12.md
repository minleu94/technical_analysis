# V3.0 Week 1 Manual Validation

> 日期：2026-07-12
> 決議：`DEFER_ALL_PRUNING_DECISIONS`
> 狀態：真實資料人工驗證已開始；不是 V3.0 formal closeout。

## 證據來源

- DB：V2.2 Week 1 隔離 working-copy。
- 唯讀報告：`D:/Min/Python/Project/FA_Data/output/v3_validation/score_effectiveness_20260712.json`。
- 最小樣本門檻：30。
- Access boundary：writes、production scheduler、investment-effectiveness claim、ML training 全為 false。

## 結果

| Score bucket | Events | Ready outcomes | Missing outcomes | 決議 |
|---|---:|---:|---:|---|
| 0-40 | 0 | 0 | 0 | defer |
| 40-50 | 0 | 0 | 0 | defer |
| 50-60 | 1 | 0 | 4 | defer |
| 60-70 | 2 | 0 | 8 | defer |
| 70-80 | 0 | 0 | 0 | defer |
| 80-100 | 0 | 0 | 0 | defer |

- 有 score 的事件只有 3 筆，所有 12 個 horizon outcomes 均 missing。
- 另有 1,134 個事件缺 `score_bp`，不能納入 TotalScore bucket 判讀。
- 沒有任何 bucket 達到 retain / restrict / downweight / retire 所需的成熟樣本。

## 人工判讀

本輪不能判斷 bucket monotonicity、Precision@K、benchmark / industry excess、MAE / MFE、regime 或 liquidity stability。所有 pruning 決議維持 defer；不調整 score、threshold、Profile、gate、alert 或 lifecycle。後續必須等待真實 forward horizon 成熟，並釐清哪些 event family 本來就不應具有 `score_bp`，不得為了填滿 V3 報表而錯誤回補。
