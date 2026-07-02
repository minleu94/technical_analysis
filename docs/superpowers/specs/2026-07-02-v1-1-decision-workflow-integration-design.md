# V1.1 Decision Workflow Integration Design

## 目標

V1.1 不重整整個資訊架構，也不宣稱推薦有效性。它要把已完成的 Daily Decision Desk、Market Watch / Smart Money、Recommendation Profile、Research Lab 推薦回放與 Evidence Review 串成一條每天可操作、可回溯、可人工審核的工作流。

本設計補齊使用者確認的推薦策略閉環：

```text
大盤狀態 / Regime
  -> 推薦 Profile / 策略假設
  -> 今日推薦與 Why / Why Not
  -> Research Lab 推薦回放 / Profile Replay Comparison
  -> Research Run Registry / Forward Evidence
  -> 人工 promote / hold / demote_candidate / retire_candidate 判讀
```

## 範圍內

1. Daily Decision Desk 保持為每日入口，新增或強化到市場觀察、推薦分析、Research Lab、Evidence Review 的導引。
2. Market Watch / Smart Money 保持獨立頁籤，但作為 Daily Decision 的 evidence drill-down。
3. Recommendation Profile 顯示要能回答「三個內建 Profile 差在哪裡」，至少揭露權重、技術分類、型態數與主要 filter。
4. Research Lab 增加 Profile Replay Comparison 的服務邊界，能用同一資料期間與同一假設比較多個 Profile。
5. V1.1 只產生 promote / hold / demote_candidate / retire_candidate 的判讀入口與 evidence summary，不自動降級、不自動刪除策略版本、不自動交易。
6. Empty / degraded state 必須說清楚是資料不足、evidence pending、source missing，不能讓使用者誤判為策略結論。

## 範圍外

1. 不在 V1.1 做完整 Unified Decision Workbench。
2. 不新增 production write-mode scheduler。
3. 不把 demote / retire 做成自動套用策略狀態的按鈕。
4. 不在推薦或回測核心加入裸 `float` 計算。
5. 不修改 ScoringEngine 的 factor 權重契約；若要新增權重維度，留到 V1.2+ 並先完成 factor governance。
6. 不更新 `PROJECT_SNAPSHOT.md`、`ROADMAP_6M_ENGINEERING.md`、`VERSION_ROADMAP_V1_1_TO_V2_0.md` 的完成狀態，直到 V1.1 checkpoint 驗證完成。

## 架構

新增 `app_module/profile_replay_comparison_service.py` 作為 V1.1 的比較服務邊界。它不重新設計推薦演算法，而是接收已治理的 Profile config、日期範圍與共同 replay 假設，呼叫既有推薦回放服務或可注入 runner，產生 Profile 層級比較 DTO。

UI 層只讀 DTO。Recommendation View 可先補 Profile 詳細摘要；Research Lab 後續可接 Profile Replay Comparison 的結果表。Daily Decision Desk 只放導引與 evidence summary，不直接計算推薦、回測或 evidence。

## 資料流

```text
RecommendationProfileService.list_profiles()
  -> ProfileReplayComparisonService.compare_profiles()
      -> Recommendation replay runner
      -> ProfileReplayComparisonResult
  -> Research Lab / Daily Decision UI presentation
```

每個 comparison row 至少保存：

- `profile_id`
- `profile_name`
- `profile_version`
- `applicable_regimes`
- `total_return_bp`
- `benchmark_excess_bp`
- `max_drawdown_bp`
- `trade_count`
- `quality`
- `warnings`
- `lifecycle_candidate`

`lifecycle_candidate` 只表示人工覆盤候選：

- `promote_candidate`
- `hold`
- `demote_candidate`
- `retire_candidate`
- `insufficient_evidence`

## Look-ahead 自查

Profile Replay Comparison 的比較日期必須固定。若用訓練 / 驗證切分，調整只能使用訓練窗結果；驗證窗只讀凍結後的 Profile / threshold / weight 設定。

V1.1 的最小可接受測試設計：

```text
Training window: T-2Y 到 T-1Y
  -> 比較 Profile / threshold / filter / weight 候選
  -> 產生凍結設定

Validation window: T-1Y 到 T
  -> 只驗證凍結設定
  -> 不再依驗證結果回頭調整同一輪設定
```

更完整設計留給 V1.2 walk-forward：每個月只使用該月之前已成熟的 evidence 決定下個月規則。

## 升降級語意

V1.1 不把降級做成直接操作。原因是目前已存在 Signal Decay / Lifecycle proposed payload，但 UI 仍缺人工審核與策略狀態套用流程。V1.1 只把判讀說清楚：

- Promote：Research Run Registry 與 lifecycle gate 通過後才可升級。
- Hold：樣本不足、benchmark / factor / regime evidence 不足，或結果混雜。
- Demote candidate：短窗 evidence 弱於長窗、回撤惡化、benchmark excess 轉弱或 live gap 擴大。
- Retire candidate：長短窗都弱、回撤嚴重、品質足夠且 live gap 也支持失效假設。

真正 demote / retire 的套用流程放在 V1.3 Manual Lifecycle。

## 測試策略

1. Profile config tests：確認內建 Profile 的權重、指標、型態與 filter 可被摘要與序列化。
2. Service tests：用 fake replay runner 驗證 Profile Replay Comparison 能產生排序、品質狀態與 lifecycle candidate。
3. UI tests：確認 Profile 詳細摘要可見，不把 mismatch 當自動排除。
4. Contract tests：確認 UI 不直接 import replay / lifecycle / evidence repository 做計算。
5. Quant guard：若修改推薦、回測、績效核心，執行量化防禦檢查。

## Checkpoint

V1.1 完成 checkpoint 才更新權威文件，條件是：

1. Profile Replay Comparison service 與測試完成。
2. Recommendation / Research Lab / Daily Decision workflow 至少有一條可操作導引。
3. Empty / degraded state 有明確文案。
4. 必要 UI 測試、相關 focused tests、mypy / py_compile 通過或列出阻塞。
5. 分段 commits 已 push。
