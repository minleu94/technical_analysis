# Gate 7 ML Shadow Engineering

> 狀態：engineering in progress / shadow only

Gate 7 使用隔離的 `ml_module/` 建立結構化傳統 ML challenger。此工程不取代 rule-generated signals、不修改推薦 threshold、不接 production scheduler、不產生交易建議，也不具有 production eligibility。

## Frozen dataset manifest

每個訓練資料集必須先建立 immutable manifest，記錄 dataset id、決策日期範圍、row count、feature/label schema、source versions、content hash 與 manifest hash。所有 feature 與 label 欄位都必須具有 available-date contract。Manifest registry 採 append-only；相同 dataset id 不可覆寫。

## Available-date boundary

Feature 必須滿足 `feature.available_date <= row.decision_date`。Label 可以在決策日之後成熟，但訓練時必須是 `ready` 且 `label.available_date <= training_as_of`。Future decision rows、future features、pending labels 與 cutoff 後才可得的 labels 全部隔離並保留 diagnostics。

## Purged walk-forward

模型驗證使用 expanding walk-forward，不使用 random shuffle/K-fold。每個 fold 的 train decision dates 早於 test，且 train label end 不得跨入 test start；test blocks 之間保留明確 embargo。Fold 生成對未來資料保持 prefix invariance。
