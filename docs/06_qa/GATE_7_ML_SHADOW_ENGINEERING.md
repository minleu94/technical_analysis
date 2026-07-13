# Gate 7 ML Shadow Engineering

> 狀態：engineering in progress / shadow only

Gate 7 使用隔離的 `ml_module/` 建立結構化傳統 ML challenger。此工程不取代 rule-generated signals、不修改推薦 threshold、不接 production scheduler、不產生交易建議，也不具有 production eligibility。

## Frozen dataset manifest

每個訓練資料集必須先建立 immutable manifest，記錄 dataset id、決策日期範圍、row count、feature/label schema、source versions、content hash 與 manifest hash。所有 feature 與 label 欄位都必須具有 available-date contract。Manifest registry 採 append-only；相同 dataset id 不可覆寫。

## Available-date boundary

Feature 必須滿足 `feature.available_date <= row.decision_date`。Label 可以在決策日之後成熟，但訓練時必須是 `ready` 且 `label.available_date <= training_as_of`。Future decision rows、future features、pending labels 與 cutoff 後才可得的 labels 全部隔離並保留 diagnostics。

## Purged walk-forward

模型驗證使用 expanding walk-forward，不使用 random shuffle/K-fold。每個 fold 的 train decision dates 早於 test，且 train label end 不得跨入 test start；test blocks 之間保留明確 embargo。Fold 生成對未來資料保持 prefix invariance。

## Boosted challengers

第一組完整 challenger 使用 scikit-learn histogram gradient boosting：regressor 同時提供 future return bp prediction 與 ranking score，classifier 提供 downside probability。訓練要求 feature shape 一致、有限值、至少十列及 downside 兩類樣本。Bundle 固定 `shadow_only=true`、`production_eligible=false`；float 僅存在 `ml_module` 模型邊界。

## Probability calibration

Downside probability 使用 isotonic calibration，且 calibration input 必須來自至少兩個 walk-forward out-of-fold blocks。校準拒絕樣本不足、單一 label class、非有限值或超出 0..1 的 raw probability。Calibrator 固定 shadow-only，不提供 production eligibility。

## Model and prediction registries

Model registry append-only 保存 model/dataset id、feature list、artifact path/hash、calibration id 與固定 `shadow_candidate` lifecycle。Prediction registry append-only 保存 symbol、decision/available date、return/ranking/downside outputs；future-available 或非有限值會被拒絕。兩者皆無 production action eligibility。

## Drift and champion comparison

Feature drift 使用 frozen baseline quantile bins 計算 PSI，分成 stable、moderate 與 major drift；任何狀態都不會自動 retrain。Champion comparison 強制使用同一組 unique matured samples，比較 Precision@K、challenger return MAE 與 downside Brier；結果只提供 direction review，`auto_promotion_allowed=false`。

## Rollback and promotion review

`scripts/build_ml_promotion_review.py` 產生非套用型 review package。需要最低 shadow days、可審查 comparison、無 major drift、calibration passed、rollback artifact 與 verification artifacts；否則 `defer`。最高狀態只有 `eligible_for_human_review`，固定 `apply_promotion=false`、`auto_promotion_allowed=false`、`production_scheduler_allowed=false`。

## Static shadow boundary

`scripts/check_ml_shadow_boundary.py` 以 AST 檢查 production packages 不得 import `ml_module`，`ml_module` 不得 import Advice/Decision/Portfolio/UI/runtime/backtest 路徑，且不得把 production/promotion/trading flags 設為 true。違反時 CLI exit 1。
