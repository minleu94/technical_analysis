# Gate 2–7 Pure Engineering Closeout（2026-07-12）

> 結論：Gate 2–7 已完成本次批准範圍內的純工程包；這不是 Gate 2–7 formal product closeout，也不代表人工、時間、授權、投資有效性或 production eligibility 已通過。

## 已完成工程包

| Package | Engineering slices | 狀態 |
|---|---:|---|
| Evidence / V3 Data Quality | 5 | complete |
| P0 Source Contracts / Shadow Adapters | 7 | complete |
| Paper Portfolio Daily Loop | 5 | complete |
| Position Health / Exit | 4 | complete |
| Gate 7 Structured Traditional ML Shadow | 9 | complete |
| Control Center / Closeout | 5 + registry CLI | complete |

每個切片均以獨立 commit 交付。機器可讀 closeout verifier 逐項檢查 35 個必要 artifact/commit pairs；最終驗證命令：

```powershell
.\.venv\Scripts\python.exe scripts\verify_gate_2_to_7_closeout.py --output <closeout.json> --gate-db <control.sqlite>
```

## 固定安全邊界

- P0 source 最高只能 `eligible_for_human_review`；未經逐來源人工決議前 `downstream_eligibility=none`。
- Paper Portfolio、Position Health、Exit 全部 research/proposal-only，不連 broker、不自動再平衡或退出。
- Gate 7 使用結構化傳統 ML（gradient boosting regression/ranking/downside classification + OOF isotonic calibration），固定 shadow-only。
- ML production packages 不得 import `ml_module`；static guard 必須保持 zero violations。
- Pruning、health transition、source acceptance、ML promotion 全部不自動 apply。
- Engineering completion 與 external validation 分開；`formal_product_closeout=false`。

## 尚待外部驗證

完整可維護清單見 [GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md](GATE_2_TO_7_EXTERNAL_VALIDATION_REGISTER.md)。狀態更新使用 append-only `EngineeringGateRegistry` 與 `scripts/manage_engineering_gate_registry.py`，不得改寫舊 revision。

## Rollback / Review

- 每一切片可依獨立 commit 回顧與處理，不需要整包一起啟用。
- 禁止以 rollback 為理由刪除 evidence、paper、health、ML 或 control-center append-only histories。
- 任何正式 P0 acceptance、ML promotion、scheduler enablement、Advice/Portfolio 接線或交易功能必須另立人工核准與 rollback Gate。
