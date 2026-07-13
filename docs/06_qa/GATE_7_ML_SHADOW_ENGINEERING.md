# Gate 7 ML Shadow Engineering

> 狀態：engineering in progress / shadow only

Gate 7 使用隔離的 `ml_module/` 建立結構化傳統 ML challenger。此工程不取代 rule-generated signals、不修改推薦 threshold、不接 production scheduler、不產生交易建議，也不具有 production eligibility。

## Frozen dataset manifest

每個訓練資料集必須先建立 immutable manifest，記錄 dataset id、決策日期範圍、row count、feature/label schema、source versions、content hash 與 manifest hash。所有 feature 與 label 欄位都必須具有 available-date contract。Manifest registry 採 append-only；相同 dataset id 不可覆寫。
