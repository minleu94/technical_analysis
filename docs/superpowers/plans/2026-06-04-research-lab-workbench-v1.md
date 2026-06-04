# Research Lab Workbench V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe `BacktestView` as a Research Lab workbench with clearer setup/result sections, without changing backtest engines or service contracts.

**Architecture:** This is a UI information-architecture pass on `ui_qt/views/backtest_view.py`. Existing widgets, attributes, signals, and service calls remain in place; the implementation changes group labels, visible copy, lightweight helper text, and result tab labels. Tests lock down the visible Research Lab concepts so future edits do not drift back into generic Backtest wording.

**Tech Stack:** Python, PySide6, pytest, existing `BacktestView`, existing `RESEARCH_LAB_MODES`, Markdown docs.

---

## Scope Boundary

In scope:

- Make the left side read as a Research Lab setup console.
- Put the four concepts on screen: `實驗模式`, `輸入來源`, `策略與風控`, `執行實驗`.
- Rename the right result tabs toward `實驗摘要`, `交易明細`, `圖表`, `批次結果`, `推薦回放`, `歷史與比較`.
- Keep all existing variables and signal connections intact.
- Update UI docs after the UI labels land.

Out of scope:

- Changing `backtest_module/*` or `app_module/backtest_service.py`.
- Changing recommendation replay calculations.
- Adding mode-driven hiding of fields.
- Adding a new fixed-basket storage model.
- Changing Portfolio trade rebuild logic.

## File Structure

- Modify `ui_qt/views/backtest_view.py`
  - Update Research Lab hint text.
  - Reorder mode selector before presets.
  - Split existing `回測配置` controls into `輸入來源` and `策略與風控：資金成本 / 執行`.
  - Rename existing section group boxes to Research Lab language.
  - Rename result tabs and result group labels.

- Create `tests/test_ui_qt_research_lab_workbench_copy.py`
  - Static copy tests for the visible workbench vocabulary.
  - This intentionally avoids instantiating the full Qt view because `BacktestView` requires many services and side effects.

- Modify `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
  - Document Research Lab Workbench V1 after implementation.

- Optional modify `docs/00_core/PROJECT_SNAPSHOT.md`, `docs/00_core/DEVELOPMENT_ROADMAP.md`, `docs/00_core/DOCUMENTATION_INDEX.md`
  - Only if implementation changes current-state wording beyond the already documented Research Lab redesign.

---

### Task 1: Add Research Lab Workbench Copy Tests

**Files:**
- Create: `tests/test_ui_qt_research_lab_workbench_copy.py`

- [ ] **Step 1: Write failing copy tests**

Create `tests/test_ui_qt_research_lab_workbench_copy.py`:

```python
from pathlib import Path


BACKTEST_VIEW_TEXT = Path("ui_qt/views/backtest_view.py").read_text(encoding="utf-8")


def test_backtest_view_names_left_side_as_research_lab_workbench():
    assert "實驗模式" in BACKTEST_VIEW_TEXT
    assert "輸入來源" in BACKTEST_VIEW_TEXT
    assert "策略與風控" in BACKTEST_VIEW_TEXT
    assert "執行實驗" in BACKTEST_VIEW_TEXT
    assert "主要輸入" in BACKTEST_VIEW_TEXT


def test_backtest_view_names_result_tabs_as_experiment_outputs():
    assert "實驗摘要" in BACKTEST_VIEW_TEXT
    assert "交易明細" in BACKTEST_VIEW_TEXT
    assert "批次結果" in BACKTEST_VIEW_TEXT
    assert "推薦回放" in BACKTEST_VIEW_TEXT
    assert "歷史與比較" in BACKTEST_VIEW_TEXT


def test_backtest_view_preserves_existing_advanced_capabilities():
    assert "參數最佳化" in BACKTEST_VIEW_TEXT
    assert "Walk-forward 驗證" in BACKTEST_VIEW_TEXT
    assert "升級為策略版本" in BACKTEST_VIEW_TEXT
```

- [ ] **Step 2: Run tests and verify expected failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_lab_workbench_copy.py -q -o addopts=
```

Expected before implementation: FAIL because `實驗模式`, `輸入來源`, `策略與風控`, `執行實驗`, `實驗摘要`, `推薦回放`, or `歷史與比較` are not all present in `backtest_view.py`.

- [ ] **Step 3: Commit failing tests only**

Run:

```powershell
git add tests\test_ui_qt_research_lab_workbench_copy.py
git commit -m "test(ui): cover research lab workbench copy"
```

---

### Task 2: Update Research Lab Mode Hint and Top Setup Order

**Files:**
- Modify: `ui_qt/views/backtest_view.py`
- Test: `tests/test_research_lab_mode_taxonomy.py`
- Test: `tests/test_ui_qt_research_lab_workbench_copy.py`

- [ ] **Step 1: Update mode hint helper**

In `ui_qt/views/backtest_view.py`, replace `_on_research_lab_mode_changed` with:

```python
    def _research_lab_mode_hint_text(self, index: int) -> str:
        """建立 Research Lab 模式提示文字。"""
        if index < 0 or index >= len(RESEARCH_LAB_MODES):
            return ""
        mode = RESEARCH_LAB_MODES[index]
        return f"{mode['description']}｜主要輸入：{mode['primary_input']}"

    def _on_research_lab_mode_changed(self, index: int):
        """更新 Research Lab 模式提示。"""
        if hasattr(self, "research_lab_mode_hint"):
            self.research_lab_mode_hint.setText(self._research_lab_mode_hint_text(index))
```

In `_setup_ui`, change the initial hint from:

```python
        self.research_lab_mode_hint = QLabel(RESEARCH_LAB_MODES[0]["description"])
```

to:

```python
        self.research_lab_mode_hint = QLabel(self._research_lab_mode_hint_text(0))
```

- [ ] **Step 2: Rename mode group**

In `_setup_ui`, change:

```python
        mode_group = QGroupBox("Research Lab 模式")
```

to:

```python
        mode_group = QGroupBox("實驗模式")
```

- [ ] **Step 3: Move mode group before strategy preset group**

In `_setup_ui`, the mode group should appear immediately after `config_layout.setContentsMargins(...)` and before:

```python
        # ========== 策略預設區塊 ==========
```

Keep the existing signal connection:

```python
        self.research_lab_mode_combo.currentIndexChanged.connect(self._on_research_lab_mode_changed)
```

Do not rename `self.research_lab_mode_combo` or `self.research_lab_mode_hint`.

- [ ] **Step 4: Run taxonomy and copy tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_lab_mode_taxonomy.py tests\test_ui_qt_research_lab_workbench_copy.py -q -o addopts=
```

Expected: copy tests may still fail until later tasks add all result labels; taxonomy tests must pass.

- [ ] **Step 5: Syntax check**

Run:

```powershell
$env:PYTHONPYCACHEPREFIX="$env:TEMP\codex_pycache"; .\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest_view.py
```

Expected: exits 0.

- [ ] **Step 6: Commit**

Run:

```powershell
git add ui_qt\views\backtest_view.py
git commit -m "feat(ui): clarify research lab mode guidance"
```

---

### Task 3: Split Left Setup Copy Into Input and Strategy/Risk Sections

**Files:**
- Modify: `ui_qt/views/backtest_view.py`
- Test: `tests/test_ui_qt_research_lab_workbench_copy.py`

- [ ] **Step 1: Rename `回測配置` to `輸入來源`**

In `_setup_ui`, change:

```python
        # ========== 回測配置 ==========
        config_group = QGroupBox("回測配置")
        config_form = QFormLayout()
```

to:

```python
        # ========== 輸入來源 ==========
        config_group = QGroupBox("輸入來源")
        config_form = QFormLayout()
```

Keep these controls inside `config_form`:

```python
        self.stock_mode_combo
        self.stock_code_input
        self.watchlist_widget
        self.start_date
        self.end_date
```

- [ ] **Step 2: Create a separate strategy/risk form for capital and execution controls**

Immediately after adding `self.end_date` to `config_form`, close the input source group:

```python
        config_group.setLayout(config_form)
        config_layout.addWidget(config_group)

        # ========== 策略與風控：資金成本 / 執行 ==========
        risk_group = QGroupBox("策略與風控：資金成本 / 執行")
        risk_form = QFormLayout()
```

Move the following existing rows from `config_form.addRow(...)` to `risk_form.addRow(...)`:

```python
        risk_form.addRow("初始資金:", self.capital_input)
        risk_form.addRow("手續費:", self.fee_bps_input)
        risk_form.addRow("滑價:", self.slippage_bps_input)
        risk_form.addRow("執行價格:", self.execution_price_combo)
        risk_form.addRow("停損停利模式:", self.stop_profit_mode_combo)
        risk_form.addRow("停損 (%):", self.stop_loss_input)
        risk_form.addRow("停利 (%):", self.take_profit_input)
        risk_form.addRow("停損 (ATR):", self.stop_loss_atr_input)
        risk_form.addRow("停利 (ATR):", self.take_profit_atr_input)
```

After `self.take_profit_atr_input` is added, close the new group:

```python
        risk_group.setLayout(risk_form)
        config_layout.addWidget(risk_group)
```

Remove the old duplicate block:

```python
        config_group.setLayout(config_form)
        config_layout.addWidget(config_group)
```

from below the ATR controls, because the input source group is now closed earlier.

- [ ] **Step 3: Rename existing strategy/risk groups**

In `_setup_ui`, change group labels:

```python
        sizing_group = QGroupBox("策略與風控：部位 Sizing")
        position_mgmt_group = QGroupBox("策略與風控：部位管理")
        market_constraints_group = QGroupBox("策略與風控：市場限制")
        strategy_group = QGroupBox("策略與風控：策略配置")
```

Change the preset group label:

```python
            preset_group = QGroupBox("策略來源 / 預設")
```

Change optimization and walk-forward labels:

```python
            self.optimization_group = QGroupBox("進階驗證：參數最佳化")
            wf_group = QGroupBox("進階驗證：Walk-forward 驗證")
```

Change recommendation replay setup label:

```python
        self.recommendation_portfolio_group = QGroupBox("推薦回放設定")
```

- [ ] **Step 4: Run copy tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_lab_workbench_copy.py -q -o addopts=
```

Expected: may still fail only on result labels if Task 4 has not run.

- [ ] **Step 5: Syntax check**

Run:

```powershell
$env:PYTHONPYCACHEPREFIX="$env:TEMP\codex_pycache"; .\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest_view.py
```

Expected: exits 0.

- [ ] **Step 6: Commit**

Run:

```powershell
git add ui_qt\views\backtest_view.py
git commit -m "feat(ui): group research lab setup sections"
```

---

### Task 4: Rename Execute Area and Result Tabs

**Files:**
- Modify: `ui_qt/views/backtest_view.py`
- Test: `tests/test_ui_qt_research_lab_workbench_copy.py`

- [ ] **Step 1: Wrap execute controls in an execution group**

Replace the plain execute row / progress widget insertion:

```python
        config_layout.addLayout(execute_row)
        ...
        config_layout.addWidget(progress_widget)
```

with:

```python
        execution_group = QGroupBox("執行與下一步")
        execution_layout = QVBoxLayout()
        execution_layout.addLayout(execute_row)
        execution_layout.addWidget(progress_widget)
        execution_group.setLayout(execution_layout)
        config_layout.addWidget(execution_group)
```

Keep `execute_row`, `self.execute_btn`, `self.save_result_btn`, `self.promote_btn`, `self.progress_label`, and `self.progress_bar` unchanged as attributes and local variables.

- [ ] **Step 2: Rename execute button**

Change:

```python
        self.execute_btn = QPushButton("執行回測")
```

to:

```python
        self.execute_btn = QPushButton("執行實驗")
```

- [ ] **Step 3: Rename summary group and result tab**

Change:

```python
        summary_group = QGroupBox("績效摘要")
        result_tabs.addTab(result_tab, "結果")
```

to:

```python
        summary_group = QGroupBox("實驗摘要")
        result_tabs.addTab(result_tab, "實驗摘要")
```

Keep `trades_group = QGroupBox("交易明細")` unchanged.

- [ ] **Step 4: Rename result tabs**

Change tab labels:

```python
            result_tabs.addTab(optimization_result_tab, "最佳化 / 驗證")
            result_tabs.addTab(compare_tab, "歷史與比較")
            result_tabs.addTab(batch_result_tab, "批次結果")
            result_tabs.addTab(recommendation_portfolio_tab, "推薦回放")
```

The existing chart tab can remain:

```python
            result_tabs.addTab(chart_tab, "圖表")
```

- [ ] **Step 5: Rename recommendation replay action buttons**

Change:

```python
        self.execute_recommendation_portfolio_btn = QPushButton("執行推薦組合回測")
        self.save_portfolio_result_btn = QPushButton("保存推薦回測")
        self.delete_portfolio_result_btn = QPushButton("刪除推薦回測")
```

to:

```python
        self.execute_recommendation_portfolio_btn = QPushButton("執行推薦回放")
        self.save_portfolio_result_btn = QPushButton("保存推薦回放")
        self.delete_portfolio_result_btn = QPushButton("刪除推薦回放")
```

- [ ] **Step 6: Run copy tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_research_lab_workbench_copy.py -q -o addopts=
```

Expected: PASS.

- [ ] **Step 7: Syntax check**

Run:

```powershell
$env:PYTHONPYCACHEPREFIX="$env:TEMP\codex_pycache"; .\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest_view.py
```

Expected: exits 0.

- [ ] **Step 8: Commit**

Run:

```powershell
git add ui_qt\views\backtest_view.py
git commit -m "feat(ui): rename research lab execution outputs"
```

---

### Task 5: Update Research Lab Workbench Documentation

**Files:**
- Modify: `docs/02_features/UI_FEATURES_DOCUMENTATION.md`
- Optional modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Optional modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Optional modify: `docs/00_core/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Update UI features documentation**

In `docs/02_features/UI_FEATURES_DOCUMENTATION.md`, under `### Tab 4：策略回測 / Research Lab (BacktestView)`, add or update a short subsection:

```markdown
#### Research Lab 工作台 V1

BacktestView 第一版整理為「左側實驗設定台、右側實驗結果台」：

- 左側設定台依序呈現：實驗模式、輸入來源、策略與風控、執行與下一步。
- 實驗模式提示會顯示模式用途與主要輸入，協助使用者判斷本次實驗要回答什麼問題。
- 右側結果台以實驗摘要、交易明細、圖表、批次結果、推薦回放、歷史與比較等語意呈現。
- V1 只整理資訊架構與文案；不改回測核心、不改推薦回放計算、不做模式驅動隱藏。
```

- [ ] **Step 2: Decide whether core docs need a current-state update**

Run:

```powershell
rg -n "Research Lab 工作流重整|Research Lab 工作台|策略回測 / Research Lab" docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\DEVELOPMENT_ROADMAP.md docs\00_core\DOCUMENTATION_INDEX.md
```

If these files already describe Research Lab 工作流重整 as in progress, do not add another status block. If they do not mention Workbench V1 and the implementation materially changes current state, add one concise bullet:

```markdown
- Research Lab 工作台 V1 已將 BacktestView 整理為左側實驗設定台與右側實驗結果台，保留既有回測核心。
```

- [ ] **Step 3: Run documentation grep**

Run:

```powershell
rg -n "一鍵送回測|送往回測|推薦組合回測區塊|回測配置" docs\02_features\UI_FEATURES_DOCUMENTATION.md
```

Expected: No stale phrase that contradicts the new visible labels in the current Research Lab section. Historical sections may remain only if they are clearly historical.

- [ ] **Step 4: Commit docs**

Run:

```powershell
git add docs\02_features\UI_FEATURES_DOCUMENTATION.md docs\00_core\PROJECT_SNAPSHOT.md docs\00_core\DEVELOPMENT_ROADMAP.md docs\00_core\DOCUMENTATION_INDEX.md
git commit -m "docs: document research lab workbench v1"
```

If the optional core docs were not modified, stage only `docs\02_features\UI_FEATURES_DOCUMENTATION.md`.

---

### Task 6: Final Verification

**Files:**
- Verify all changed files.

- [ ] **Step 1: Run focused Research Lab tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_research_lab_mode_taxonomy.py tests\test_ui_qt_research_lab_workbench_copy.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 2: Run prior copy / provenance tests to catch workflow drift**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_recommendation_next_steps_copy.py tests\test_ui_qt_watchlist_candidate_pool_copy.py tests\test_portfolio_source_adapter.py tests\test_portfolio_mvp.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 3: Compile changed Python files**

Run:

```powershell
$env:PYTHONPYCACHEPREFIX="$env:TEMP\codex_pycache"; .\.venv\Scripts\python.exe -m py_compile ui_qt\views\backtest_view.py tests\test_research_lab_mode_taxonomy.py tests\test_ui_qt_research_lab_workbench_copy.py
```

Expected: exits 0.

- [ ] **Step 4: Run required UpdateView UI test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_update_view_workbench.py -q -o addopts=
```

Expected: pass.

- [ ] **Step 5: Run required Update Tab QA**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
```

Expected: pass. If it updates tracked QA report files under `output/qa/update_tab/`, do not stage those files unless this task explicitly requires QA output updates.

- [ ] **Step 6: Run mypy**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
```

Expected: this repository currently has known mypy debt. If errors remain, capture the count and confirm whether any error points to `ui_qt/views/backtest_view.py` or `tests/test_ui_qt_research_lab_workbench_copy.py`.

- [ ] **Step 7: Check git status and exclusions**

Run:

```powershell
git status --short
```

Expected: only intentional source/test/doc changes are present. Do not stage `.superpowers/`, temp files, or tracked QA output from `output/qa/update_tab/`.

- [ ] **Step 8: Final commit if needed**

If Task 6 produced any verification-only doc note or small fix, commit it:

```powershell
git add <intentional-files-only>
git commit -m "test(ui): verify research lab workbench v1"
```

If no files changed, do not create an empty commit.
