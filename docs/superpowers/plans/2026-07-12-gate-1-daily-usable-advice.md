# Gate 1 Daily Usable Advice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Gate 1 的可拒絕、可回溯、唯讀 Advice Contract，並在 closeout 後以證據重整 `PROJECT_SNAPSHOT.md`。

**Architecture:** 在 `app_module` 新增純 Advice DTO、Policy 與 Composer；只消費既有 Recommendation、Portfolio、Evidence payload。Workbench 只透過 `WorkbenchDashboardDTO` 呈現 Advice。

**Tech Stack:** Python、dataclass、Decimal、PySide6、pytest、mypy。

## Global Constraints

- 核心權重使用整數 bp；金額使用 `Decimal`。
- 只使用 `decision_date` 時已可得資料；禁止 look-ahead。
- Guided Mode 禁止 candidate / shadow；Professional Mode 與正式 Advice 明確隔離。
- 平衡預設：`min_cash_bp=2000`、`max_positions=8`、`max_position_weight_bp=1500`。
- 不寫 DB、不改 Scoring / ranking / backtest、不串 broker、不啟用 scheduler。

---

### Task 1: 建立 Advice DTO 與 JSON 契約

**Files:**
- Create: `app_module/advice_dtos.py`
- Create: `tests/test_advice_dtos.py`

**Interfaces:**
- Produces: `AdviceAction`、`AdviceMode`、`AdvicePolicyConfig`、`RecommendationAdviceDTO`、`PortfolioAdviceDTO`、`AdviceDashboardDTO`。

- [ ] **Step 1: 寫失敗的 DTO round-trip 與 bp boundary 測試**

```python
def test_portfolio_advice_round_trip_preserves_integer_bp() -> None:
    row = PortfolioAdviceDTO(
        stock_code="2330", advice_action=AdviceAction.ADD_CANDIDATE,
        target_weight_bp=1500, current_weight_bp=0, weight_gap_bp=1500,
        reasons=("score_eligible",),
    )
    assert PortfolioAdviceDTO.from_dict(row.to_dict()) == row
```

- [ ] **Step 2: 執行 RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_dtos.py -q -o addopts=`  
Expected: FAIL，因 `app_module.advice_dtos` 尚不存在。

- [ ] **Step 3: 實作 frozen dataclass 與明確序列化**

```python
class AdviceAction(str, Enum):
    RESEARCH = "RESEARCH"
    ADD_CANDIDATE = "ADD_CANDIDATE"
    HOLD = "HOLD"
    REDUCE_CANDIDATE = "REDUCE_CANDIDATE"
    EXIT_CANDIDATE = "EXIT_CANDIDATE"
    AVOID = "AVOID"
    NO_NEW_POSITION = "NO_NEW_POSITION"
```

- [ ] **Step 4: 執行 GREEN**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_dtos.py -q -o addopts=`  
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add app_module/advice_dtos.py tests/test_advice_dtos.py
git commit -m "feat: add advice contract dtos"
```

### Task 2: 實作 fail-closed Advice Policy

**Files:**
- Create: `app_module/advice_policy.py`
- Create: `tests/test_advice_policy.py`

**Interfaces:**
- Consumes: `AdvicePolicyConfig`、`AdviceMode`。
- Produces: `AdviceAction` 與 immutable rejection reason tuple。

- [ ] **Step 1: 寫失敗測試**

```python
def test_guided_mode_rejects_candidate_strategy() -> None:
    decision = AdvicePolicy().decide(
        mode=AdviceMode.GUIDED, strategy_status="candidate",
        data_quality="OBSERVED", execution_feasible=True, risk_budget_available=True,
    )
    assert decision.action is AdviceAction.NO_NEW_POSITION
    assert "guided_mode_strategy_not_promoted" in decision.reasons
```

- [ ] **Step 2: 執行 RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_policy.py -q -o addopts=`  
Expected: FAIL，因 policy 尚不存在。

- [ ] **Step 3: 最小實作**

依固定順序處理 strategy status、quality、execution、risk budget、持倉數、現金與單檔上限；任一 blocking rule 成立即回傳 `NO_NEW_POSITION`、`AVOID` 或 `RESEARCH`，不推測輸入。

- [ ] **Step 4: 新增邊界測試並 GREEN**

涵蓋 `2000 bp` 現金、8 檔、`1500 bp` 單檔上限、缺資料、degraded、不可成交及 Professional candidate 隔離。  
Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_policy.py -q -o addopts=`  
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add app_module/advice_policy.py tests/test_advice_policy.py
git commit -m "feat: add fail closed advice policy"
```

### Task 3: 建立只讀 Advice Composer

**Files:**
- Create: `app_module/advice_composer.py`
- Create: `tests/test_advice_composer.py`

**Interfaces:**
- Consumes: 既有 Recommendation payload、`PortfolioConstructionResult`、Evidence quality/warnings、`AdvicePolicy`。
- Produces: `AdviceDashboardDTO`，保留 `decision_date`、`data_as_of_date` 與 source trace。

- [ ] **Step 1: 寫失敗的 source trace 與拒絕輸出測試**

```python
def test_composer_preserves_dates_and_returns_no_new_position_for_missing_evidence() -> None:
    result = AdviceComposer(AdvicePolicy()).compose(
        recommendations=(), portfolio_result=None, evidence_quality="MISSING",
        decision_date=date(2026, 7, 12), data_as_of_date=date(2026, 7, 12),
        mode=AdviceMode.GUIDED,
    )
    assert result.recommendations[0].advice_action is AdviceAction.NO_NEW_POSITION
    assert result.recommendations[0].source_trace == "RecommendationResultDTO"
```

- [ ] **Step 2: 執行 RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_composer.py -q -o addopts=`  
Expected: FAIL，因 composer 尚不存在。

- [ ] **Step 3: 最小實作**

Composer 只接收注入 payload；不得直接讀 SQLite、UI state 或目前日期。所有 target/current/gap 以整數 bp 檢核並保留 missing diagnostics。

- [ ] **Step 4: GREEN 與 no-look-ahead 檢查**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_composer.py -q -o addopts=`  
Expected: PASS。

- [ ] **Step 5: Commit**

```powershell
git add app_module/advice_composer.py tests/test_advice_composer.py
git commit -m "feat: compose read only advice dashboard"
```

### Task 4: 將 Advice 掛入 Workbench DTO、composer 與 Qt 唯讀視圖

**Files:**
- Modify: `app_module/workbench_dtos.py`
- Modify: `app_module/workbench_read_only_composer.py`
- Modify: `ui_qt/views/workbench_view.py`
- Modify: `ui_qt/models/workbench_table_models.py`
- Create: `tests/test_workbench_advice_contract.py`
- Modify: `tests/test_ui_qt_workbench_view.py`

**Interfaces:**
- Produces: `WorkbenchDashboardDTO.advice_dashboard: AdviceDashboardDTO | None`。

- [ ] **Step 1: 寫失敗的 DTO / UI boundary 測試**

```python
def test_workbench_renders_advice_dto_without_policy_execution(qtbot) -> None:
    view = UnifiedDecisionWorkbenchView(dashboard=dashboard_with_advice())
    assert "NO_NEW_POSITION" in view.advice_summary.text()
```

- [ ] **Step 2: 執行 RED**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_workbench_advice_contract.py tests/test_ui_qt_workbench_view.py -q -o addopts=`  
Expected: FAIL，因 Workbench 尚無 Advice payload / 區塊。

- [ ] **Step 3: 最小 DTO-to-view 接線**

只由 `WorkbenchReadOnlyComposer` 接受注入的 `AdviceDashboardDTO`；Qt 顯示 action、理由、資料品質、可成交性、target/current/gap 與 boundary banner，不新增寫入或核心計算。

- [ ] **Step 4: GREEN 與 UI 必跑驗證**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_workbench_advice_contract.py tests/test_ui_qt_workbench_view.py tests/test_ui_qt_update_view_workbench.py -q -o addopts=`  
Expected: PASS。

Run: `./.venv/Scripts/python.exe scripts/qa_validate_update_tab.py`  
Expected: 既有 Update Tab QA 通過。

- [ ] **Step 5: Commit**

```powershell
git add app_module/workbench_dtos.py app_module/workbench_read_only_composer.py ui_qt/views/workbench_view.py ui_qt/models/workbench_table_models.py tests
git commit -m "feat: render read only workbench advice"
```

### Task 5: Gate 1 文件 closeout 與全面 Snapshot 稽核

**Files:**
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/ROADMAP_6M_ENGINEERING.md`
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/01_architecture/system_architecture.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Modify: `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
- Modify: `PROJECT_NAVIGATION.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Create: `docs/06_qa/GATE_1_ADVICE_CLOSEOUT_2026_07_12.md`
- Create: `docs/06_qa/PROJECT_SNAPSHOT_AUDIT_2026_07_12.md`

- [ ] **Step 1: 建立 Snapshot 證據矩陣**

每個 Snapshot claim 必須對應 Git SHA、QA artifact 或 scoped authority；分類為「目前保留」、「移至歷史」、「改為限制」、「刪除重複」。不使用檔名日期推論完成日。

- [ ] **Step 2: 重寫 Snapshot 的當前狀態與本週優先事項**

將 Gate 0 明列為已 closeout（引用 `ae83740` 和 Master Report），Gate 1 僅在測試與人工 smoke 通過後標為 complete；將散落的舊 `0/3` / `1/3` 時間型記錄移至歷史節，保留目前值與來源。

- [ ] **Step 3: 同步使用者與架構文件**

Manual 必須說明 Guided / Professional、平衡限制、Advice 拒絕輸出和 weekly review working-copy 保存；不把 Advice 寫成 broker 指令或績效保證。

- [ ] **Step 4: 完整驗證**

Run: `./.venv/Scripts/python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime`  
Expected: Success。

Run: `./.venv/Scripts/python.exe scripts/check_financial_float_boundaries.py`  
Expected: 通過。

Run: `./.venv/Scripts/python.exe -m pytest tests/test_advice_dtos.py tests/test_advice_policy.py tests/test_advice_composer.py tests/test_workbench_advice_contract.py -q -o addopts=`  
Expected: PASS。

Run: `git diff --check`  
Expected: 無 whitespace error。

- [ ] **Step 5: Commit**

```powershell
git add docs PROJECT_NAVIGATION.md
git commit -m "docs: close gate 1 and reconcile project snapshot"
```
