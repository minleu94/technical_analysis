# Gate 1 Daily Usable Advice Closeout

> 日期：2026-07-12
> 結論：**完成（read-only / bounded Advice Contract）**
> 非目標：投資有效性、broker execution、production scheduler、DB write、lifecycle action、P0 source acceptance。

## 範圍與證據

| 能力 | 實作證據 |
|---|---|
| Advice DTO 與 JSON / bp contract | `566acd4`、`99c26d5` |
| fail-closed policy 與 invalid mode | `4b1b2c3`、`7713344` |
| read-only composer、as-of / future input guard | `d90943e`、`a505d01` |
| Workbench DTO-to-view render | `e7b8db0` |
| Gate 1 type repair | `31813c5` |
| Gate 0 前置 closeout | `ae83740`、`docs/01_architecture/SAFE_REFACTORING_MASTER_REPORT.md` |

## 已驗收行為

- `AdviceAction` 支援 `RESEARCH`、`ADD_CANDIDATE`、`HOLD`、`REDUCE_CANDIDATE`、`EXIT_CANDIDATE`、`AVOID`、`NO_NEW_POSITION`。
- Guided Mode 對 candidate / shadow 或無效 mode fail-closed；Professional Mode 的 candidate 維持研究呈現，不與 formal Advice 混用。
- 缺資料、降級、不可成交、風險預算滿載、最低現金、最大持倉與單檔上限均輸出安全 action 或理由，不補值。
- 平衡限制：最低現金 `2000 bp`、最多 8 檔、單檔上限 `1500 bp`；權重為整數 bp，金額為 `Decimal`。
- Composer 保留 `decision_date`、`data_as_of_date`、source trace，並拒絕未來 data-as-of 或未來 portfolio input。
- Workbench 只渲染 `AdviceDashboardDTO`；不呼叫 policy / composer、不寫 DB、不重算 scoring / portfolio / backtest / lifecycle、不建立 broker order 或 scheduler。

## 本次驗證

| 命令 | 實際結果 |
|---|---|
| `./.venv/Scripts/python.exe -m pytest tests/test_advice_dtos.py tests/test_advice_policy.py tests/test_advice_composer.py tests/test_workbench_advice_contract.py tests/test_ui_qt_workbench_view.py tests/test_ui_qt_update_view_workbench.py -q -o addopts=` | `87 passed in 2.75s` |
| `./.venv/Scripts/python.exe scripts/qa_validate_update_tab.py` | `23` 通過、`0` 失敗、`4` 跳過；未執行實際下載或合併。 |
| `./.venv/Scripts/python.exe scripts/check_financial_float_boundaries.py` | exit `0`。 |
| `./.venv/Scripts/python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime` | `Success: no issues found in 367 source files`；僅既有 untyped-body notes。 |

## 人工文案 / smoke 判讀

Qt focused tests 已驗證 Advice DTO 可被 Workbench 呈現，且無 policy 執行邊界。文件人工稽核確認文案不宣稱保證獲利、自動交易或 broker 指令；`NO_NEW_POSITION`、`RESEARCH`、`AVOID` 均說明為正常的安全輸出。

## 殘餘與下一 Gate

- Gate 2 仍需真實 weekly review history、manual review note 與 action-item rhythm；目前 weekly history 是 `0/3 waiting_for_time`。
- multi-day dry-run 的目前可驗證值為 `3/3 ready`，但不代表 production scheduler approval。
- Gate 1 不驗證策略 / Advice 的投資有效性，也不接受 replay、fixture 或 candidate source 作為 Gate 2 / Gate 3 credit。

## 回退

Gate 1 由上述原子 commits 組成；如需回退，依 commit 反序處理並重跑本文件的 focused suite。不得以回退為由刪除既有 evidence 或改寫正式資料。
