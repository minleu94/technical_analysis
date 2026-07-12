# V2.1 Engineering Readiness

> 日期：2026-07-12
> 狀態：**Engineering readiness complete**；正式版本判定另見 `V2_1_FORMAL_CLOSEOUT_2026_07_12.md`。
> 範圍：Gate 1 Daily Usable Advice 的 bounded、read-only Workbench 能力。
> 非範圍：投資有效性、broker execution、production scheduler、DB write、lifecycle action、P0 source acceptance。

## 1. 交付契約

| 項目 | readiness 判定 | 證據 |
|---|---|---|
| Guided 策略准入 | 僅 `promoted`、`parameters_locked=true`、`disclosure_complete=true` 三者同時成立；任一不成立均 fail-closed 為 `NO_NEW_POSITION`。 | `592d3db`、`tests/test_advice_policy.py`、`tests/test_advice_composer.py` |
| 最大持倉設定 | `max_positions` 僅接受非布林整數 `1..8`；無效設定拒絕建立 policy，防止繞過 8 檔上限。 | `592d3db`、`tests/test_advice_dtos.py`、`tests/test_advice_policy.py` |
| Professional 候選隔離 | candidate 僅能是 `RESEARCH`，標記為 `PROFESSIONAL_CANDIDATE`；Qt 以獨立「Professional 研究候選（不屬於正式 Advice）」區呈現，不混入正式 Advice。 | `592d3db`、`tests/test_advice_dtos.py`、`tests/test_workbench_advice_contract.py`、`tests/test_ui_qt_workbench_view.py` |
| Workbench 唯讀邊界 | UI 僅渲染注入的 `AdviceDashboardDTO`；不執行 policy / composer、不寫 DB、不重算 scoring、portfolio、backtest 或 lifecycle。 | `e7b8db0`、`592d3db`、Workbench focused tests |
| 安全拒絕與風險限制 | 資料缺漏或降級、不可成交、風險預算／現金／持倉限制均採 fail-closed；`NO_NEW_POSITION`、`RESEARCH`、`AVOID` 是正常安全輸出。平衡風險檔維持最低現金 `2000 bp`、單檔上限 `1500 bp`，權重使用整數 bp、金額使用 `Decimal`。 | `4b1b2c3`、`592d3db`、focused suite |
| as-of / trace | Composer 保留 `decision_date`、`data_as_of_date`、source trace，拒絕未來資料與未來 portfolio input。 | `d90943e`、`a505d01`、`tests/test_advice_composer.py` |

## 2. Focused 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_advice_dtos.py tests/test_advice_policy.py tests/test_advice_composer.py tests/test_workbench_advice_contract.py tests/test_ui_qt_workbench_view.py tests/test_ui_qt_update_view_workbench.py -q -o addopts=
```

結果：**94 passed in 2.91s**（2026-07-12）。

本 suite 覆蓋 Advice DTO / JSON 與 bp contract、Guided / Professional policy、composer 的 as-of guard、Workbench Advice contract、Workbench Qt 呈現與 Update View regression。這是工程契約驗證，不是策略報酬、投資有效性或 broker 執行驗證。

## 3. 人工 UI 文案 smoke

- 檢視 Workbench Advice 區文案後，正式列標題為「正式 Advice / 唯讀呈現」；Professional 候選明確以「Professional 研究候選（不屬於正式 Advice）」分區。
- 摘要明示 `AdviceDashboardDTO` 注入、decision / as-of date、warnings 與正式／候選筆數；未將候選描述為可執行交易或正式 Advice。
- `NO_NEW_POSITION`、`RESEARCH`、`AVOID` 的文案與 closeout 一致，均為安全輸出而非下單指令。

結論：文案 smoke 通過 bounded / read-only 語意檢查；此結論不宣稱獲利、投資有效性、broker order 或自動交易。

## 4. 殘餘限制與後續 Gate

- V2.1 不產生 broker order、不自動交易、不自動平倉、不寫正式資料庫、不啟用 production scheduler。
- V2.2 仍須以真實時間累積 weekly history、manual review note 與 action-item rhythm；現況 weekly history 為 `0/3 waiting_for_time`，不可由 replay、fixture 或人工改表補足。
- V2.3 P0 source acceptance、V2.4 paper portfolio / execution feasibility，以及策略與 Advice 投資有效性均不由本次 closeout 證明。

## 5. 回退與追溯

- Gate 1 實作回退錨點：`592d3db5d88262bbc5e48c0d363e7f43f8c69389`（Guided promoted + locked + disclosure、`max_positions` 1..8、Professional UI 分區）。若需回退功能，應由最新相依 commit 起反序處理，並重跑本文件的 focused suite。
- Gate 1 的前序原子 commits 為 `566acd4`、`99c26d5`、`4b1b2c3`、`7713344`、`d90943e`、`a505d01`、`e7b8db0`、`31813c5`；不以回退為由刪除 evidence 或改寫正式資料。
- 正式版本結論、人工 smoke 與版本邊界見 `V2_1_FORMAL_CLOSEOUT_2026_07_12.md`；現況權威仍為 `docs/00_core/PROJECT_SNAPSHOT.md`。

## 更新記錄

- 2026-07-12：建立 V2.1 engineering readiness，納入 `592d3db` 的三項 Gate 1 safeguards 與 focused suite 結果。
