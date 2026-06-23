# Non-Destructive Release Healthcheck Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Release 前使用的非破壞式 Full App Healthcheck Runner，能以快速、完整、高風險 dry-run 三種模式驗證 PySide6 主 UI、流程閉環、視窗縮放、截圖證據與 service / SQLite oracle，而不寫入正式資料。

**Architecture:** 以 manifest 驅動測試流程，runner 只負責載入情境、驅動 Qt UI、收集截圖與輸出報告；資料正確性由獨立 oracle 讀取 service / SQLite / UI 狀態判斷。第一版預設 `--non-destructive` 且不可關閉，所有資料更新、強制合併、apply、刪除、清空與正式寫入只驗證防呆、取消、dry-run 或唯讀狀態，不執行真正寫入。

**Tech Stack:** Python 3.12, PySide6, pytest, QTest/widget API, SQLite read-only inspection, Markdown / JSON report output, existing `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`, existing `tests/test_ui_qt_*` patterns.

---

## Scope Boundary

本計畫只建立「非破壞式驗收框架」。不做下列事情：

- 不執行快速更新、安全更新、強制合併、正式月營收寫入、資料重建、刪除持倉或清空資料。
- 不建立 Playwright / Selenium 真實桌面滑鼠錄放；第一版使用 PySide6 widget API 與 `QTest` 等級的近真人操作。
- 不修改策略、推薦、回測、資金、倉位、績效或 scoring 邏輯。
- 不直接解析 `APPLICATION_MANUAL.md` 產生自動步驟；第一版由 manifest 明確列測項，文件只作 coverage 來源。
- 不把任何測項標記成正式人工通過；runner 報告只代表自動驗證結果，healthcheck 的 `驗證通過` 仍需使用者人工確認。

第一版只允許：

- 啟動主視窗或單一 view。
- 切換頂層 tab 與子 tab。
- 點擊非寫入或已 mock 的按鈕。
- 對高風險按鈕驗證 confirmation dialog 的取消流程。
- 用 fake service / test config 測 UI 行為。
- 對正式 SQLite 做唯讀查詢。
- 擷取 UI 截圖、檢查 widget visible / enabled / geometry / text。
- 輸出 `output/qa/full_app_healthcheck/<run_id>/` 底下的報告與截圖。

## Final Product Definition

這個 runner 的最終型態不是單純把 pytest 跑一遍，而是把 `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md` 代表的人工驗證流程，逐步機器化成 release 前的「功能覆蓋 + 流程閉環 + UI 可用性 + 版本升級比較」驗收系統。

最終報告必須回答四個問題：

1. **每個功能有沒有被驗到？**
   - 對應 `FULL_APP_HEALTHCHECK_2026_06_16.md` 的 healthcheck ID 或人工段落。
   - 每個項目標記為 `automated`、`existing-test-bridged`、`manual-only`、`blocked`、`not-yet-automated` 或 `retired`。
   - 報告列出缺口，不讓「還沒自動化」被誤看成「已通過」。

2. **每個流程閉環有沒有走通？**
   - 至少覆蓋資料與市場狀態閉環、研究驗證閉環、持倉檢查閉環、每日決策閉環。
   - 每個閉環都要有入口、主要操作、預期狀態、證據、下一步導向。
   - 若某一步只能人工驗，報告要保留斷點與原因。

3. **流程是否合理，而不只是沒有 crash？**
   - 記錄 UI 是否能讓使用者理解下一步、是否有缺漏提示、是否有不可見或被遮住的控制項。
   - 對高風險操作只驗證防呆與取消流程，並記錄是否有明確警示文案。
   - 對視窗縮放與不同 viewport 輸出截圖與 layout 檢查結果。

4. **未來版本升級是否真的更有效？**
   - 每次輸出 structured JSON，保存 commit hash、manifest version、模式、viewport、既有測試橋接結果、coverage matrix、flow diagnostics。
   - 後續版本可比較兩次結果，知道新增/修復/退步/仍未覆蓋項目。
   - quick mode 用於日常快速防退化，full mode 用於 release 前完整巡檢，high-risk-dry-run 用於高風險流程防呆驗證。

## File Map

- Create: `qa/full_app_healthcheck/__init__.py`
  - Package marker。

- Create: `qa/full_app_healthcheck/manifest.py`
  - 定義 manifest dataclass、step dataclass、mode enum、risk enum。

- Create: `qa/full_app_healthcheck/default_manifest.py`
  - 收斂第一版測項：頂層 tab、資料更新非破壞測試、市場觀察讀取、每日決策刷新、推薦與 Research Lab 非寫入導覽、觀察清單唯讀、持倉管理唯讀、Runtime Observatory。

- Create: `qa/full_app_healthcheck/runner.py`
  - 執行 manifest，建立 QApplication / MainWindow，跑步驟，收集結果。

- Create: `qa/full_app_healthcheck/actions.py`
  - UI 操作 primitive：find tab、switch tab、click button、resize window、assert visible、grab screenshot。

- Create: `qa/full_app_healthcheck/oracles.py`
  - 驗證 primitive：widget text、table model row count、readonly SQLite status、dialog button text、layout bounds。

- Create: `qa/full_app_healthcheck/reporting.py`
  - 寫出 JSON 與 Markdown 報告、截圖索引與 failure 摘要。

- Create: `qa/full_app_healthcheck/coverage_matrix.py`
  - 將人工 healthcheck 段落、manifest step、既有測試橋接結果對應成覆蓋矩陣，標示 automated / existing-test-bridged / manual-only / blocked / not-yet-automated / retired。

- Create: `qa/full_app_healthcheck/flow_diagnostics.py`
  - 彙整每個流程閉環的入口、步驟、證據、缺口與不合理處，讓報告能指出流程問題而不只是測試失敗。

- Create: `qa/full_app_healthcheck/safety.py`
  - 統一封鎖破壞性 step，偵測 manifest 裡的 forbidden action。

- Create: `qa/full_app_healthcheck/test_suite_bridge.py`
  - 將既有零碎 pytest / QA scripts 包裝成 runner 可呼叫的非破壞式檢查，避免重複撰寫相同測試。

- Create: `scripts/run_full_app_healthcheck.py`
  - CLI entrypoint：`--mode quick|full|high-risk-dry-run`、`--viewport`、`--output-dir`、`--fail-fast`。

- Create: `tests/test_full_app_healthcheck_manifest.py`
  - 測 manifest safety、模式展開與流程閉環 coverage。

- Create: `tests/test_full_app_healthcheck_runner.py`
  - 用 fake window / fake action 執行 runner，不啟動完整正式 App。

- Create: `tests/test_full_app_healthcheck_reporting.py`
  - 測 Markdown / JSON 報告格式。

- Create: `tests/test_full_app_healthcheck_test_suite_bridge.py`
  - 測既有測試橋接清單、命令組裝與 non-destructive 分類。

- Create: `tests/test_full_app_healthcheck_coverage_matrix.py`
  - 測人工 healthcheck ID 與 manifest / existing tests 的覆蓋狀態彙整。

- Create: `tests/test_full_app_healthcheck_flow_diagnostics.py`
  - 測閉環診斷能辨識缺步驟、缺證據、無下一步導向等流程問題。

- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
  - 加入 runner 作為自動化輔助入口，但不取代人工驗證。

- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
  - 新增 Release 前非破壞式健康檢查操作段落。

## Data And Safety Contract

- Runner 預設設置 `QT_QPA_PLATFORM=offscreen`，除非使用者之後另開可視化模式。
- Runner 讀取 `TWStockConfig` 時不得改寫 `DATA_ROOT` 或 `OUTPUT_ROOT`。
- Runner 的 SQLite oracle 必須用唯讀 URI：`file:<path>?mode=ro`。
- `UpdateView` 的 quick / safe update、force merge、monthly apply、clear all、delete run 等操作在第一版只能驗證：
  - 按鈕存在。
  - tooltip / label 可讀。
  - confirmation dialog 有取消。
  - 按取消後沒有呼叫 service 寫入方法。
- `output/qa/full_app_healthcheck/` 屬 QA output，不應順手 stage；stage 前仍需依 `docs/agents/git_exclusions.md` 檢查。

## Implementation Tasks

### Task 1: Manifest Contract And Safety Gate

**Files:**
- Create: `qa/full_app_healthcheck/__init__.py`
- Create: `qa/full_app_healthcheck/manifest.py`
- Create: `qa/full_app_healthcheck/safety.py`
- Test: `tests/test_full_app_healthcheck_manifest.py`

- [ ] **Step 1: Write failing tests for manifest modes and destructive-step rejection**

Add to `tests/test_full_app_healthcheck_manifest.py`:

```python
import pytest

from qa.full_app_healthcheck.manifest import (
    HealthcheckManifest,
    HealthcheckMode,
    HealthcheckStep,
    RiskLevel,
)
from qa.full_app_healthcheck.safety import validate_non_destructive_manifest


def test_non_destructive_manifest_rejects_write_step():
    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.QUICK,),
        steps=(
            HealthcheckStep(
                id="U-WRITE",
                title="不應執行快速更新",
                mode=HealthcheckMode.QUICK,
                workspace="數據更新",
                action="click_quick_update",
                risk=RiskLevel.WRITES_DATA,
            ),
        ),
    )

    with pytest.raises(ValueError, match="非破壞模式禁止"):
        validate_non_destructive_manifest(manifest)


def test_non_destructive_manifest_allows_dialog_cancel_step():
    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.HIGH_RISK_DRY_RUN,),
        steps=(
            HealthcheckStep(
                id="U-031",
                title="強制合併取消流程",
                mode=HealthcheckMode.HIGH_RISK_DRY_RUN,
                workspace="數據更新",
                action="assert_force_merge_cancel_dialog",
                risk=RiskLevel.HIGH_RISK_CANCEL_ONLY,
            ),
        ),
    )

    validate_non_destructive_manifest(manifest)
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_manifest.py -q -o addopts=
```

Expected: fail with `ModuleNotFoundError: No module named 'qa.full_app_healthcheck'`.

- [ ] **Step 3: Implement manifest dataclasses**

Create `qa/full_app_healthcheck/__init__.py`:

```python
"""非破壞式 Full App Healthcheck Runner。"""
```

Create `qa/full_app_healthcheck/manifest.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HealthcheckMode(str, Enum):
    QUICK = "quick"
    FULL = "full"
    HIGH_RISK_DRY_RUN = "high-risk-dry-run"


class RiskLevel(str, Enum):
    READ_ONLY = "read-only"
    UI_ONLY = "ui-only"
    DRY_RUN_ONLY = "dry-run-only"
    HIGH_RISK_CANCEL_ONLY = "high-risk-cancel-only"
    WRITES_DATA = "writes-data"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class HealthcheckStep:
    id: str
    title: str
    mode: HealthcheckMode
    workspace: str
    action: str
    risk: RiskLevel = RiskLevel.UI_ONLY
    expected: str = ""
    evidence_kind: str = "text"


@dataclass(frozen=True)
class HealthcheckManifest:
    id: str
    title: str
    modes: tuple[HealthcheckMode, ...]
    steps: tuple[HealthcheckStep, ...]

    def steps_for_mode(self, mode: HealthcheckMode) -> tuple[HealthcheckStep, ...]:
        return tuple(step for step in self.steps if step.mode == mode)
```

Create `qa/full_app_healthcheck/safety.py`:

```python
from __future__ import annotations

from qa.full_app_healthcheck.manifest import HealthcheckManifest, RiskLevel


FORBIDDEN_NON_DESTRUCTIVE_RISKS = {
    RiskLevel.WRITES_DATA,
    RiskLevel.DESTRUCTIVE,
}


def validate_non_destructive_manifest(manifest: HealthcheckManifest) -> None:
    blocked = [
        step
        for step in manifest.steps
        if step.risk in FORBIDDEN_NON_DESTRUCTIVE_RISKS
    ]
    if blocked:
        ids = ", ".join(step.id for step in blocked)
        raise ValueError(f"非破壞模式禁止包含會寫資料或破壞資料的 step: {ids}")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_manifest.py -q -o addopts=
```

Expected: 2 passed.

### Task 2: Default Manifest For Release Modes

**Files:**
- Create: `qa/full_app_healthcheck/default_manifest.py`
- Test: `tests/test_full_app_healthcheck_manifest.py`

- [ ] **Step 1: Add coverage tests for default manifest**

Append to `tests/test_full_app_healthcheck_manifest.py`:

```python
from qa.full_app_healthcheck.default_manifest import build_default_manifest


def test_default_manifest_covers_four_product_loops():
    manifest = build_default_manifest()
    titles = " ".join(step.title for step in manifest.steps)

    assert "資料與市場狀態閉環" in titles
    assert "研究驗證閉環" in titles
    assert "持倉檢查閉環" in titles
    assert "每日決策閉環" in titles


def test_default_manifest_contains_all_release_modes():
    manifest = build_default_manifest()

    assert HealthcheckMode.QUICK in manifest.modes
    assert HealthcheckMode.FULL in manifest.modes
    assert HealthcheckMode.HIGH_RISK_DRY_RUN in manifest.modes
    assert manifest.steps_for_mode(HealthcheckMode.QUICK)
    assert manifest.steps_for_mode(HealthcheckMode.FULL)
    assert manifest.steps_for_mode(HealthcheckMode.HIGH_RISK_DRY_RUN)
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_manifest.py -q -o addopts=
```

Expected: fail with `ModuleNotFoundError` or missing `build_default_manifest`.

- [ ] **Step 3: Implement default manifest**

Create `qa/full_app_healthcheck/default_manifest.py`:

```python
from __future__ import annotations

from qa.full_app_healthcheck.manifest import (
    HealthcheckManifest,
    HealthcheckMode,
    HealthcheckStep,
    RiskLevel,
)


def build_default_manifest() -> HealthcheckManifest:
    return HealthcheckManifest(
        id="full-app-release-healthcheck-v1",
        title="Release 前非破壞式 Full App Healthcheck",
        modes=(
            HealthcheckMode.QUICK,
            HealthcheckMode.FULL,
            HealthcheckMode.HIGH_RISK_DRY_RUN,
        ),
        steps=(
            HealthcheckStep(
                id="LOOP-1",
                title="資料與市場狀態閉環：數據更新狀態、SQLite 唯讀檢查、市場觀察導覽",
                mode=HealthcheckMode.QUICK,
                workspace="數據更新",
                action="assert_data_market_loop_readonly",
                risk=RiskLevel.READ_ONLY,
                expected="可看到資料狀態、可切到市場觀察，不執行資料更新。",
            ),
            HealthcheckStep(
                id="LOOP-2",
                title="研究驗證閉環：推薦分析到 Research Lab 導覽",
                mode=HealthcheckMode.QUICK,
                workspace="推薦分析",
                action="assert_recommendation_to_research_lab_navigation",
                risk=RiskLevel.UI_ONLY,
                expected="推薦頁與策略回測頁可載入，跨頁 signal 可用。",
            ),
            HealthcheckStep(
                id="LOOP-3",
                title="持倉檢查閉環：持倉管理、監控分頁與主力流向下鑽入口",
                mode=HealthcheckMode.FULL,
                workspace="持倉管理",
                action="assert_portfolio_loop_readonly",
                risk=RiskLevel.READ_ONLY,
                expected="持倉管理可載入，監控分頁與下鑽入口可見。",
            ),
            HealthcheckStep(
                id="LOOP-4",
                title="每日決策閉環：Daily Decision Desk snapshot 與風險提示讀取",
                mode=HealthcheckMode.FULL,
                workspace="每日決策",
                action="assert_decision_desk_snapshot_readonly",
                risk=RiskLevel.READ_ONLY,
                expected="每日決策頁可顯示或降級顯示，warning 可讀。",
            ),
            HealthcheckStep(
                id="UI-RESIZE-01",
                title="視窗縮放：1366x768 關鍵工作區不遮擋",
                mode=HealthcheckMode.FULL,
                workspace="全域",
                action="assert_viewport_1366x768_layout",
                risk=RiskLevel.UI_ONLY,
                expected="頂層 tab、狀態列、主要按鈕可見。",
                evidence_kind="screenshot",
            ),
            HealthcheckStep(
                id="HR-001",
                title="高風險 dry-run：強制合併只驗證取消流程",
                mode=HealthcheckMode.HIGH_RISK_DRY_RUN,
                workspace="數據更新",
                action="assert_force_merge_cancel_dialog",
                risk=RiskLevel.HIGH_RISK_CANCEL_ONLY,
                expected="對話框有取消與確認強制合併；按取消不呼叫合併。",
                evidence_kind="dialog",
            ),
        ),
    )
```

- [ ] **Step 4: Run manifest tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_manifest.py -q -o addopts=
```

Expected: all passed.

### Task 3: Report Model And Markdown / JSON Output

**Files:**
- Create: `qa/full_app_healthcheck/reporting.py`
- Test: `tests/test_full_app_healthcheck_reporting.py`

- [ ] **Step 1: Write failing reporting tests**

Create `tests/test_full_app_healthcheck_reporting.py`:

```python
import json

from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.reporting import HealthcheckResult, StepResult, write_reports


def test_write_reports_outputs_markdown_and_json(tmp_path):
    result = HealthcheckResult(
        run_id="run-001",
        mode=HealthcheckMode.QUICK,
        status="failed",
        steps=(
            StepResult(
                id="LOOP-1",
                title="資料與市場狀態閉環",
                status="passed",
                evidence={"message": "ok"},
            ),
            StepResult(
                id="LOOP-2",
                title="研究驗證閉環",
                status="failed",
                evidence={"error": "button missing"},
            ),
        ),
    )

    files = write_reports(result, tmp_path)

    assert files.markdown.exists()
    assert files.json.exists()
    markdown = files.markdown.read_text(encoding="utf-8")
    assert "# Full App Healthcheck Report" in markdown
    assert "資料與市場狀態閉環" in markdown
    assert "研究驗證閉環" in markdown
    payload = json.loads(files.json.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-001"
    assert payload["status"] == "failed"
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_reporting.py -q -o addopts=
```

Expected: fail with missing module.

- [ ] **Step 3: Implement reporting**

Create `qa/full_app_healthcheck/reporting.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
from typing import Any

from qa.full_app_healthcheck.manifest import HealthcheckMode


@dataclass(frozen=True)
class StepResult:
    id: str
    title: str
    status: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class HealthcheckResult:
    run_id: str
    mode: HealthcheckMode
    status: str
    steps: tuple[StepResult, ...]


@dataclass(frozen=True)
class ReportFiles:
    markdown: Path
    json: Path


def write_reports(result: HealthcheckResult, output_dir: Path) -> ReportFiles:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "REPORT.md"
    json_path = output_dir / "result.json"
    json_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    return ReportFiles(markdown=markdown_path, json=json_path)


def _render_markdown(result: HealthcheckResult) -> str:
    lines = [
        "# Full App Healthcheck Report",
        "",
        f"- Run ID: `{result.run_id}`",
        f"- Mode: `{result.mode.value}`",
        f"- Status: `{result.status}`",
        "",
        "## Steps",
        "",
    ]
    for step in result.steps:
        lines.append(f"### {step.id} - {step.title}")
        lines.append(f"- Status: `{step.status}`")
        if step.evidence:
            lines.append("- Evidence:")
            for key, value in step.evidence.items():
                lines.append(f"  - `{key}`: {value}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run reporting tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_reporting.py -q -o addopts=
```

Expected: passed.

### Task 4: UI Action Primitives

**Files:**
- Create: `qa/full_app_healthcheck/actions.py`
- Test: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Write failing action tests**

Create `tests/test_full_app_healthcheck_runner.py`:

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget, QWidget

from qa.full_app_healthcheck.actions import (
    click_button_by_text,
    find_child_button_by_text,
    switch_tab_by_text,
)


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_switch_tab_by_text_changes_current_index():
    app()
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "數據更新")
    tabs.addTab(QWidget(), "市場觀察")

    switch_tab_by_text(tabs, "市場觀察")

    assert tabs.currentIndex() == 1


def test_find_and_click_button_by_text():
    app()
    parent = QWidget()
    button = QPushButton("刷新", parent)
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))

    assert find_child_button_by_text(parent, "刷新") is button
    click_button_by_text(parent, "刷新")

    assert clicked == [True]
```

- [ ] **Step 2: Run failing action tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: fail with missing `actions`.

- [ ] **Step 3: Implement actions**

Create `qa/full_app_healthcheck/actions.py`:

```python
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget


def switch_tab_by_text(tabs: QTabWidget, tab_text: str) -> None:
    for index in range(tabs.count()):
        if tabs.tabText(index) == tab_text:
            tabs.setCurrentIndex(index)
            return
    raise AssertionError(f"找不到 tab: {tab_text}")


def find_child_button_by_text(parent: QWidget, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"找不到按鈕: {text}")


def click_button_by_text(parent: QWidget, text: str) -> None:
    find_child_button_by_text(parent, text).click()


def grab_widget_screenshot(widget: QWidget, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    if pixmap.isNull():
        raise AssertionError("截圖失敗：pixmap is null")
    pixmap.save(str(path))
    return path
```

- [ ] **Step 4: Run action tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: passed.

### Task 5: Oracles For Layout, Dialog, And SQLite Readonly

**Files:**
- Create: `qa/full_app_healthcheck/oracles.py`
- Test: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Add failing oracle tests**

Append to `tests/test_full_app_healthcheck_runner.py`:

```python
from PySide6.QtWidgets import QLabel, QVBoxLayout

from qa.full_app_healthcheck.oracles import assert_child_text_contains, assert_no_visible_widget_overflows


def test_assert_child_text_contains_finds_label_text():
    app()
    parent = QWidget()
    layout = QVBoxLayout(parent)
    label = QLabel("整體品質：觀察到")
    layout.addWidget(label)

    assert_child_text_contains(parent, "整體品質")


def test_assert_no_visible_widget_overflows_accepts_basic_layout():
    app()
    parent = QWidget()
    parent.resize(400, 200)
    layout = QVBoxLayout(parent)
    layout.addWidget(QLabel("文字"))
    parent.show()
    app().processEvents()

    assert_no_visible_widget_overflows(parent)
```

- [ ] **Step 2: Run failing oracle tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: fail with missing `oracles`.

- [ ] **Step 3: Implement oracles**

Create `qa/full_app_healthcheck/oracles.py`:

```python
from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QLabel, QWidget


def assert_child_text_contains(parent: QWidget, expected: str) -> None:
    texts = [label.text() for label in parent.findChildren(QLabel)]
    if not any(expected in text for text in texts):
        raise AssertionError(f"找不到包含文字 `{expected}` 的 QLabel；現有文字: {texts[:20]}")


def assert_no_visible_widget_overflows(root: QWidget) -> None:
    root_rect = QRect(0, 0, root.width(), root.height())
    offenders = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisible():
            continue
        top_left = widget.mapTo(root, widget.rect().topLeft())
        bottom_right = widget.mapTo(root, widget.rect().bottomRight())
        rect = QRect(top_left, bottom_right)
        if rect.width() <= 0 or rect.height() <= 0:
            continue
        if not root_rect.intersects(rect):
            offenders.append((widget.__class__.__name__, rect.getRect()))
    if offenders:
        raise AssertionError(f"可見元件超出 root 可視範圍: {offenders[:10]}")
```

- [ ] **Step 4: Run oracle tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: passed.

### Task 6: Runner Core With Action Dispatch

**Files:**
- Create: `qa/full_app_healthcheck/runner.py`
- Modify: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Add failing runner dispatch test**

Append to `tests/test_full_app_healthcheck_runner.py`:

```python
from qa.full_app_healthcheck.manifest import HealthcheckManifest, HealthcheckMode, HealthcheckStep, RiskLevel
from qa.full_app_healthcheck.runner import HealthcheckRunner


def test_runner_dispatches_registered_action(tmp_path):
    calls = []

    def fake_action(context, step):
        calls.append((context["name"], step.id))
        return {"message": "ok"}

    manifest = HealthcheckManifest(
        id="test",
        title="測試",
        modes=(HealthcheckMode.QUICK,),
        steps=(
            HealthcheckStep(
                id="S-001",
                title="測試步驟",
                mode=HealthcheckMode.QUICK,
                workspace="測試",
                action="fake_action",
                risk=RiskLevel.UI_ONLY,
            ),
        ),
    )
    runner = HealthcheckRunner(
        manifest=manifest,
        actions={"fake_action": fake_action},
        context={"name": "ctx"},
        output_dir=tmp_path,
    )

    result = runner.run(HealthcheckMode.QUICK)

    assert calls == [("ctx", "S-001")]
    assert result.status == "passed"
    assert result.steps[0].status == "passed"
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: fail with missing `runner`.

- [ ] **Step 3: Implement runner**

Create `qa/full_app_healthcheck/runner.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from qa.full_app_healthcheck.manifest import HealthcheckManifest, HealthcheckMode, HealthcheckStep
from qa.full_app_healthcheck.reporting import HealthcheckResult, StepResult, write_reports
from qa.full_app_healthcheck.safety import validate_non_destructive_manifest

Action = Callable[[dict[str, Any], HealthcheckStep], dict[str, Any]]


class HealthcheckRunner:
    def __init__(
        self,
        *,
        manifest: HealthcheckManifest,
        actions: dict[str, Action],
        context: dict[str, Any],
        output_dir: Path,
        fail_fast: bool = False,
    ) -> None:
        self.manifest = manifest
        self.actions = actions
        self.context = context
        self.output_dir = output_dir
        self.fail_fast = fail_fast

    def run(self, mode: HealthcheckMode) -> HealthcheckResult:
        validate_non_destructive_manifest(self.manifest)
        step_results: list[StepResult] = []
        for step in self.manifest.steps_for_mode(mode):
            action = self.actions.get(step.action)
            if action is None:
                step_results.append(
                    StepResult(
                        id=step.id,
                        title=step.title,
                        status="failed",
                        evidence={"error": f"找不到 action: {step.action}"},
                    )
                )
                if self.fail_fast:
                    break
                continue
            try:
                evidence = action(self.context, step)
                step_results.append(
                    StepResult(id=step.id, title=step.title, status="passed", evidence=evidence)
                )
            except Exception as exc:  # noqa: BLE001
                step_results.append(
                    StepResult(
                        id=step.id,
                        title=step.title,
                        status="failed",
                        evidence={"error": str(exc), "type": exc.__class__.__name__},
                    )
                )
                if self.fail_fast:
                    break
        status = "passed" if all(result.status == "passed" for result in step_results) else "failed"
        result = HealthcheckResult(
            run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
            mode=mode,
            status=status,
            steps=tuple(step_results),
        )
        write_reports(result, self.output_dir / result.run_id)
        return result
```

- [ ] **Step 4: Run runner tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: passed.

### Task 7: CLI Entrypoint

**Files:**
- Create: `scripts/run_full_app_healthcheck.py`
- Test: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Add CLI parser smoke test**

Append to `tests/test_full_app_healthcheck_runner.py`:

```python
from scripts.run_full_app_healthcheck import parse_args


def test_full_app_healthcheck_cli_parse_mode_and_output():
    args = parse_args(["--mode", "full", "--output-dir", "out", "--fail-fast"])

    assert args.mode == "full"
    assert args.output_dir == "out"
    assert args.fail_fast is True
```

- [ ] **Step 2: Run failing test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: fail with missing script.

- [ ] **Step 3: Implement CLI skeleton**

Create `scripts/run_full_app_healthcheck.py`:

```python
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qa.full_app_healthcheck.default_manifest import build_default_manifest
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.runner import HealthcheckRunner


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="非破壞式 Full App Healthcheck Runner")
    parser.add_argument("--mode", choices=[mode.value for mode in HealthcheckMode], default="quick")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "output" / "qa" / "full_app_healthcheck"))
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--viewport", default="1366x768")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = HealthcheckMode(args.mode)
    manifest = build_default_manifest()
    runner = HealthcheckRunner(
        manifest=manifest,
        actions={},
        context={"viewport": args.viewport},
        output_dir=Path(args.output_dir),
        fail_fast=args.fail_fast,
    )
    result = runner.run(mode)
    print(f"Healthcheck {result.status}: {result.run_id}")
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI parser test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py::test_full_app_healthcheck_cli_parse_mode_and_output -q -o addopts=
```

Expected: passed.

### Task 8: First Real Non-Destructive UI Actions

**Files:**
- Modify: `qa/full_app_healthcheck/default_manifest.py`
- Modify: `qa/full_app_healthcheck/runner.py`
- Modify: `scripts/run_full_app_healthcheck.py`
- Test: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Add action registry behavior tests**

Append to `tests/test_full_app_healthcheck_runner.py`:

```python
from scripts.run_full_app_healthcheck import build_action_registry


def test_action_registry_contains_default_manifest_actions():
    actions = build_action_registry()

    assert "assert_data_market_loop_readonly" in actions
    assert "assert_force_merge_cancel_dialog" in actions
```

- [ ] **Step 2: Implement action registry with real minimum checks**

Modify `scripts/run_full_app_healthcheck.py`:

```python
def _require_window(context):
    window = context.get("window")
    if window is None:
        raise AssertionError("此 action 需要已啟動的 MainWindow context")
    return window


def assert_data_market_loop_readonly(context, step):
    from qa.full_app_healthcheck.actions import switch_tab_by_text
    from qa.full_app_healthcheck.oracles import assert_no_visible_widget_overflows

    window = _require_window(context)
    switch_tab_by_text(window.tabs, "數據更新")
    switch_tab_by_text(window.tabs, "市場觀察")
    assert_no_visible_widget_overflows(window)
    return {"message": "數據更新與市場觀察可非破壞導覽"}


def assert_recommendation_to_research_lab_navigation(context, step):
    from qa.full_app_healthcheck.actions import switch_tab_by_text

    window = _require_window(context)
    switch_tab_by_text(window.tabs, "推薦分析")
    switch_tab_by_text(window.tabs, "策略回測")
    return {"message": "推薦分析與策略回測頂層工作區可非破壞導覽"}


def assert_portfolio_loop_readonly(context, step):
    from qa.full_app_healthcheck.actions import switch_tab_by_text
    from qa.full_app_healthcheck.oracles import assert_no_visible_widget_overflows

    window = _require_window(context)
    switch_tab_by_text(window.tabs, "持倉管理")
    assert_no_visible_widget_overflows(window)
    return {"message": "持倉管理可唯讀載入且主要元件未溢出主視窗"}


def assert_decision_desk_snapshot_readonly(context, step):
    from qa.full_app_healthcheck.actions import switch_tab_by_text
    from qa.full_app_healthcheck.oracles import assert_child_text_contains

    window = _require_window(context)
    switch_tab_by_text(window.tabs, "每日決策")
    assert_child_text_contains(window, "每日決策")
    return {"message": "每日決策頁可載入並保留可讀標題或降級內容"}


def assert_viewport_1366x768_layout(context, step):
    from qa.full_app_healthcheck.actions import grab_widget_screenshot
    from qa.full_app_healthcheck.oracles import assert_no_visible_widget_overflows

    window = _require_window(context)
    window.resize(1366, 768)
    context["app"].processEvents()
    assert_no_visible_widget_overflows(window)
    screenshot = grab_widget_screenshot(window, context["output_dir"] / f"{step.id}.png")
    return {"screenshot": str(screenshot), "message": "1366x768 視窗截圖已保存"}


def assert_force_merge_cancel_dialog(context, step):
    return {
        "message": "此 step 必須在 Task 10 以 dialog interception 驗證取消流程；在完成 Task 10 前不可把 high-risk-dry-run 當 release gate。",
        "called_merge": False,
    }


def build_action_registry():
    return {
        "assert_data_market_loop_readonly": assert_data_market_loop_readonly,
        "assert_recommendation_to_research_lab_navigation": assert_recommendation_to_research_lab_navigation,
        "assert_portfolio_loop_readonly": assert_portfolio_loop_readonly,
        "assert_decision_desk_snapshot_readonly": assert_decision_desk_snapshot_readonly,
        "assert_viewport_1366x768_layout": assert_viewport_1366x768_layout,
        "assert_force_merge_cancel_dialog": assert_force_merge_cancel_dialog,
    }
```

Then change runner construction:

```python
actions=build_action_registry(),
```

- [ ] **Step 3: Run CLI in quick mode**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck --fail-fast
```

Expected: fails with `此 action 需要已啟動的 MainWindow context` until Task 9 wires the CLI to create a real window context. This is intentional: no action may silently pass without a UI context.

- [ ] **Step 4: Do not treat partial actions as a release gate**

The first infrastructure slice may verify only top-level read-only navigation. Before this runner becomes a release gate, each action in the manifest must either perform a real assertion or return `failed`; no action may silently pass because it is merely registered.

### Task 9: MainWindow Launch And Read-Only Navigation

**Files:**
- Create: `qa/full_app_healthcheck/app_context.py`
- Modify: `scripts/run_full_app_healthcheck.py`
- Test: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Add context creation smoke test with monkeypatched window**

Append to `tests/test_full_app_healthcheck_runner.py`:

```python
from qa.full_app_healthcheck.app_context import parse_viewport


def test_parse_viewport_accepts_width_height():
    assert parse_viewport("1366x768") == (1366, 768)
```

- [ ] **Step 2: Implement app context helper**

Create `qa/full_app_healthcheck/app_context.py`:

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def parse_viewport(value: str) -> tuple[int, int]:
    width_text, height_text = value.lower().split("x", 1)
    return int(width_text), int(height_text)


def ensure_qapplication() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance
```

- [ ] **Step 3: Add real read-only UI action later in same file**

Implement context creation in `scripts/run_full_app_healthcheck.py`:

```python
def _build_main_window_context(viewport: str):
    from qa.full_app_healthcheck.app_context import ensure_qapplication, parse_viewport
    from ui_qt.main import MainWindow

    app = ensure_qapplication()
    window = MainWindow()
    width, height = parse_viewport(viewport)
    window.resize(width, height)
    window.show()
    app.processEvents()
    return {"app": app, "window": window, "viewport": viewport}
```

Then update `main()` so real CLI runs provide a window:

```python
context = _build_main_window_context(args.viewport)
context["output_dir"] = Path(args.output_dir)
runner = HealthcheckRunner(
    manifest=manifest,
    actions=build_action_registry(),
    context=context,
    output_dir=Path(args.output_dir),
    fail_fast=args.fail_fast,
)
```

- [ ] **Step 4: Run CLI quick mode with real UI context**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck --fail-fast
```

Expected: command writes `REPORT.md` / `result.json`; failures are acceptable only when they identify a real UI launch, tab lookup, or layout assertion issue. The command must not execute data update, merge, apply, delete, or clear actions.

### Task 10: High-Risk Dry-Run Dialog Action

**Files:**
- Modify: `scripts/run_full_app_healthcheck.py`
- Test: `tests/test_full_app_healthcheck_runner.py`

- [ ] **Step 1: Add high-risk action unit test around fake update view**

Append to `tests/test_full_app_healthcheck_runner.py`:

```python
def test_high_risk_force_merge_action_requires_cancel_only():
    actions = build_action_registry()
    action = actions["assert_force_merge_cancel_dialog"]

    assert action.__name__ == "assert_force_merge_cancel_dialog"
```

- [ ] **Step 2: Implement action only after UpdateView has explicit dialog test coverage**

This action depends on the UI fix from `UPDATE-ISSUE-031`. Implement:

```python
def assert_force_merge_cancel_dialog(context, step):
    window = context["window"]
    update_view = window.tabs.widget(0)
    observed = {
        "cancel_button": "取消",
        "confirm_button": "確認強制合併",
        "called_merge": False,
    }
    # 實作時用 monkeypatch / dialog interception 測取消，不直接點確認。
    return observed
```

Replace the Task 8 temporary high-risk implementation only when the dialog can be intercepted safely without invoking `_do_merge(force_all=True)`.

### Task 11: Existing Test Suite Bridge

**Files:**
- Create: `qa/full_app_healthcheck/test_suite_bridge.py`
- Create: `tests/test_full_app_healthcheck_test_suite_bridge.py`
- Modify: `scripts/run_full_app_healthcheck.py`
- Modify: `qa/full_app_healthcheck/default_manifest.py`

- [ ] **Step 1: Write tests for reusable existing suite registry**

Create `tests/test_full_app_healthcheck_test_suite_bridge.py`:

```python
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.test_suite_bridge import (
    ExistingSuite,
    build_existing_suite_registry,
    suites_for_mode,
)


def test_existing_suite_registry_reuses_current_ui_and_qa_tests():
    suites = build_existing_suite_registry()
    ids = {suite.id for suite in suites}

    assert "ui-update-workbench" in ids
    assert "ui-decision-desk" in ids
    assert "ui-research-workflow" in ids
    assert "qa-update-tab" in ids


def test_quick_mode_uses_fast_non_destructive_existing_tests():
    suites = suites_for_mode(HealthcheckMode.QUICK)
    commands = [" ".join(suite.command) for suite in suites]

    assert any("tests/test_ui_qt_update_view_workbench.py" in command for command in commands)
    assert any("tests/test_ui_qt_decision_desk_view.py" in command for command in commands)
    assert all(suite.non_destructive for suite in suites)


def test_full_mode_includes_broader_existing_ui_contract_tests():
    suites = suites_for_mode(HealthcheckMode.FULL)
    commands = [" ".join(suite.command) for suite in suites]

    assert any("tests/test_ui_qt_research_workflow.py" in command for command in commands)
    assert any("tests/test_ui_qt_smart_money_flow_view.py" in command for command in commands)
    assert all(suite.non_destructive for suite in suites)


def test_existing_suite_command_is_explicit_and_not_shell_joined():
    suite = ExistingSuite(
        id="sample",
        title="sample",
        modes=(HealthcheckMode.QUICK,),
        command=(".\\.venv\\Scripts\\python.exe", "-m", "pytest", "tests/test_ui_qt_update_view_workbench.py", "-q", "-o", "addopts="),
        non_destructive=True,
    )

    assert suite.command[0].endswith("python.exe")
    assert "&&" not in suite.command
```

- [ ] **Step 2: Run failing bridge tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_test_suite_bridge.py -q -o addopts=
```

Expected: fail with missing `test_suite_bridge`.

- [ ] **Step 3: Implement existing suite bridge**

Create `qa/full_app_healthcheck/test_suite_bridge.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from qa.full_app_healthcheck.manifest import HealthcheckMode


PYTHON = ".\\.venv\\Scripts\\python.exe"


@dataclass(frozen=True)
class ExistingSuite:
    id: str
    title: str
    modes: tuple[HealthcheckMode, ...]
    command: tuple[str, ...]
    non_destructive: bool


def build_existing_suite_registry() -> tuple[ExistingSuite, ...]:
    return (
        ExistingSuite(
            id="ui-update-workbench",
            title="既有 UpdateView widget / contract 測試",
            modes=(HealthcheckMode.QUICK, HealthcheckMode.FULL),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_update_view_workbench.py", "-q", "-o", "addopts="),
            non_destructive=True,
        ),
        ExistingSuite(
            id="ui-decision-desk",
            title="既有 Daily Decision Desk UI 測試",
            modes=(HealthcheckMode.QUICK, HealthcheckMode.FULL),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_decision_desk_view.py", "-q", "-o", "addopts="),
            non_destructive=True,
        ),
        ExistingSuite(
            id="ui-research-workflow",
            title="既有 Research Lab / Recommendation / Watchlist 跨頁 workflow 測試",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_research_workflow.py", "-q", "-o", "addopts="),
            non_destructive=True,
        ),
        ExistingSuite(
            id="ui-smart-money-flow",
            title="既有 Smart Money Flow UI 測試",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "-m", "pytest", "tests/test_ui_qt_smart_money_flow_view.py", "-q", "-o", "addopts="),
            non_destructive=True,
        ),
        ExistingSuite(
            id="qa-update-tab",
            title="既有 Data Update Tab QA script",
            modes=(HealthcheckMode.FULL,),
            command=(PYTHON, "scripts\\qa_validate_update_tab.py"),
            non_destructive=True,
        ),
    )


def suites_for_mode(mode: HealthcheckMode) -> tuple[ExistingSuite, ...]:
    suites = tuple(suite for suite in build_existing_suite_registry() if mode in suite.modes)
    unsafe = [suite.id for suite in suites if not suite.non_destructive]
    if unsafe:
        raise ValueError(f"非破壞 runner 不可呼叫會寫資料的既有測試: {', '.join(unsafe)}")
    return suites
```

- [ ] **Step 4: Run bridge tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_test_suite_bridge.py -q -o addopts=
```

Expected: all passed.

- [ ] **Step 5: Add existing-suite steps to default manifest**

Modify `qa/full_app_healthcheck/default_manifest.py` so the manifest includes one step per bridge group:

```python
HealthcheckStep(
    id="EXISTING-QUICK-UI",
    title="呼叫既有快速 UI contract 測試：UpdateView + Daily Decision Desk",
    mode=HealthcheckMode.QUICK,
    workspace="既有測試",
    action="run_existing_suites_for_mode",
    risk=RiskLevel.UI_ONLY,
    expected="重用既有快速 UI 測試，不重寫同等測試邏輯。",
),
HealthcheckStep(
    id="EXISTING-FULL-UI",
    title="呼叫既有完整 UI / QA 測試：Research workflow、Smart Money、Update QA",
    mode=HealthcheckMode.FULL,
    workspace="既有測試",
    action="run_existing_suites_for_mode",
    risk=RiskLevel.READ_ONLY,
    expected="重用既有完整 UI 與 QA scripts，避免重複測試檔案。",
),
```

- [ ] **Step 6: Implement runner action for existing suites**

Modify `scripts/run_full_app_healthcheck.py`:

```python
import subprocess


def run_existing_suites_for_mode(context, step):
    from qa.full_app_healthcheck.test_suite_bridge import suites_for_mode

    mode = context["mode"]
    outputs = []
    for suite in suites_for_mode(mode):
        completed = subprocess.run(
            suite.command,
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
        outputs.append({
            "id": suite.id,
            "title": suite.title,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
        })
        if completed.returncode != 0:
            raise AssertionError(f"既有測試失敗：{suite.id}")
    return {"suites": outputs}
```

Also add `"run_existing_suites_for_mode": run_existing_suites_for_mode` to `build_action_registry()` and include `context["mode"] = mode` before creating `HealthcheckRunner`.

- [ ] **Step 7: Document reuse policy**

Add this rule to the plan implementation notes or final docs:

```markdown
新增 full app runner 測項前，先檢查既有測試是否已覆蓋同一行為。若已覆蓋，優先把既有測試登錄到 `test_suite_bridge.py`，不要複製一份相同行為測試。
```

### Task 12: Documentation

**Files:**
- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`

- [ ] **Step 1: Add healthcheck runner section to healthcheck doc**

Add near the top of `docs/06_qa/FULL_APP_HEALTHCHECK_2026_06_16.md`:

```markdown
## 自動化輔助入口（非破壞式）

Release 前可先執行非破壞式 Full App Healthcheck Runner：

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode full
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode high-risk-dry-run
```

此 runner 只作自動化輔助，不取代人工驗證。第一版不執行快速更新、安全更新、強制合併、正式資料寫入、刪除或清空；高風險流程只驗證防呆與取消。

Runner 會優先呼叫既有非破壞式 pytest / QA scripts，例如 UpdateView、Daily Decision Desk、Research workflow 與 Smart Money UI 測試；只有既有測試沒有覆蓋的跨頁導覽、截圖、視窗縮放與高風險取消流程，才新增 runner 專屬測項。
```

- [ ] **Step 2: Add manual section**

Add to `docs/07_guides/APPLICATION_MANUAL.md` under validation or QA section:

```markdown
### Release 前非破壞式健康檢查

可用 `scripts\run_full_app_healthcheck.py` 執行三種模式：

| 模式 | 用途 | 安全邊界 |
|---|---|---|
| `quick` | 快速確認主 UI 與主要閉環入口可載入 | 不寫資料，只做導覽與唯讀檢查 |
| `full` | 增加截圖、視窗縮放與更多工作區檢查 | 不寫資料，只收集報告與截圖 |
| `high-risk-dry-run` | 檢查高風險按鈕的防呆 / 取消流程 | 只驗證對話框，不按確認 |

輸出位於 `output/qa/full_app_healthcheck/`。報告中的 `passed` 代表自動化步驟通過，不等同人工 healthcheck 已驗證通過。

Runner 會重用既有非破壞式測試；新增驗收項目前，先確認是否能登錄既有 pytest 或 QA script，避免重複維護同一行為。
```

- [ ] **Step 3: Do not update Snapshot unless the runner becomes a release gate**

For the first plan execution, this is a QA helper. Update `PROJECT_SNAPSHOT.md` only if the project decides this runner is now an official release gate.

### Task 13: Coverage Matrix And Flow Diagnostics

**Files:**
- Create: `qa/full_app_healthcheck/coverage_matrix.py`
- Create: `qa/full_app_healthcheck/flow_diagnostics.py`
- Modify: `qa/full_app_healthcheck/reporting.py`
- Test: `tests/test_full_app_healthcheck_coverage_matrix.py`
- Test: `tests/test_full_app_healthcheck_flow_diagnostics.py`

- [ ] **Step 1: Write failing tests for healthcheck coverage status**

Create `tests/test_full_app_healthcheck_coverage_matrix.py`:

```python
from qa.full_app_healthcheck.coverage_matrix import (
    CoverageStatus,
    HealthcheckCoverageItem,
    detect_coverage_gaps,
)


def test_detect_coverage_gaps_keeps_manual_and_missing_visible():
    items = (
        HealthcheckCoverageItem(
            healthcheck_id="UPDATE-001",
            title="數據更新頁可載入",
            status=CoverageStatus.AUTOMATED,
            evidence="manifest:LOOP-1",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="UPDATE-009",
            title="快速更新實際寫入",
            status=CoverageStatus.MANUAL_ONLY,
            evidence="非破壞模式不執行正式寫入",
        ),
        HealthcheckCoverageItem(
            healthcheck_id="PORTFOLIO-004",
            title="持倉刪除流程",
            status=CoverageStatus.NOT_YET_AUTOMATED,
            evidence="尚未建立高風險取消測項",
        ),
    )

    gaps = detect_coverage_gaps(items)

    assert [gap.healthcheck_id for gap in gaps] == ["UPDATE-009", "PORTFOLIO-004"]
    assert gaps[0].status is CoverageStatus.MANUAL_ONLY
```

- [ ] **Step 2: Implement coverage matrix dataclasses**

Create `qa/full_app_healthcheck/coverage_matrix.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CoverageStatus(str, Enum):
    AUTOMATED = "automated"
    EXISTING_TEST_BRIDGED = "existing-test-bridged"
    MANUAL_ONLY = "manual-only"
    BLOCKED = "blocked"
    NOT_YET_AUTOMATED = "not-yet-automated"
    RETIRED = "retired"


GAP_STATUSES = {
    CoverageStatus.MANUAL_ONLY,
    CoverageStatus.BLOCKED,
    CoverageStatus.NOT_YET_AUTOMATED,
}


@dataclass(frozen=True)
class HealthcheckCoverageItem:
    healthcheck_id: str
    title: str
    status: CoverageStatus
    evidence: str = ""
    owner: str = ""
    notes: str = ""


def detect_coverage_gaps(
    items: tuple[HealthcheckCoverageItem, ...],
) -> tuple[HealthcheckCoverageItem, ...]:
    return tuple(item for item in items if item.status in GAP_STATUSES)
```

- [ ] **Step 3: Write failing tests for flow diagnostics**

Create `tests/test_full_app_healthcheck_flow_diagnostics.py`:

```python
from qa.full_app_healthcheck.flow_diagnostics import (
    FlowStepObservation,
    diagnose_flow,
)


def test_diagnose_flow_flags_missing_evidence_and_next_step():
    diagnostic = diagnose_flow(
        flow_id="daily-decision-loop",
        title="每日決策閉環",
        steps=(
            FlowStepObservation(
                id="decision-open",
                title="開啟 Daily Decision Desk",
                observed=True,
                evidence="screenshot:decision.png",
                next_step="檢查 watchlist trigger",
            ),
            FlowStepObservation(
                id="watchlist-trigger",
                title="檢查 Watchlist Trigger",
                observed=True,
                evidence="",
                next_step="",
            ),
        ),
    )

    assert diagnostic.status == "needs-attention"
    assert "缺少證據" in diagnostic.issues
    assert "缺少下一步導向" in diagnostic.issues
```

- [ ] **Step 4: Implement flow diagnostics**

Create `qa/full_app_healthcheck/flow_diagnostics.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowStepObservation:
    id: str
    title: str
    observed: bool
    evidence: str = ""
    next_step: str = ""
    notes: str = ""


@dataclass(frozen=True)
class FlowDiagnostic:
    flow_id: str
    title: str
    status: str
    issues: tuple[str, ...]
    steps: tuple[FlowStepObservation, ...]


def diagnose_flow(
    flow_id: str,
    title: str,
    steps: tuple[FlowStepObservation, ...],
) -> FlowDiagnostic:
    issues: list[str] = []
    if any(not step.observed for step in steps):
        issues.append("有步驟未觀測到")
    if any(step.observed and not step.evidence for step in steps):
        issues.append("缺少證據")
    if any(step.observed and not step.next_step for step in steps[:-1]):
        issues.append("缺少下一步導向")

    return FlowDiagnostic(
        flow_id=flow_id,
        title=title,
        status="passed" if not issues else "needs-attention",
        issues=tuple(issues),
        steps=steps,
    )
```

- [ ] **Step 5: Add coverage and diagnostics sections to reports**

Modify `qa/full_app_healthcheck/reporting.py` so Markdown reports include:

```markdown
## Coverage Summary

| Healthcheck ID | Title | Status | Evidence | Notes |
|---|---|---|---|---|

## Flow Diagnostics

| Flow | Status | Issues |
|---|---|---|
```

If no coverage matrix or flow diagnostics are passed to the reporter yet, render:

```markdown
尚未產生 coverage matrix。
尚未產生 flow diagnostics。
```

- [ ] **Step 6: Connect existing test bridge to coverage statuses**

When `test_suite_bridge.py` registers an existing pytest or QA script, it should expose the healthcheck IDs or flow IDs it covers. The coverage matrix should mark those as `existing-test-bridged` instead of requiring duplicate runner steps.

Implementation rule:

```markdown
同一個 UI 行為只能有一個主要測試來源。若既有測試已覆蓋，runner 只橋接並記錄 coverage，不重寫一份相同測試。
```

- [ ] **Step 7: Use coverage matrix as the expansion path for `FULL_APP_HEALTHCHECK_2026_06_16.md`**

Do not attempt to fully automate the whole healthcheck mother file in one PR. Instead:

1. Add explicit coverage items for the already-known manual healthcheck sections.
2. Mark non-destructive-safe items as `automated` or `existing-test-bridged`.
3. Mark write/destructive/data-changing items as `manual-only` or `blocked` until a safe dry-run path exists.
4. Keep `not-yet-automated` visible in every report so future work naturally burns the list down.

### Task 14: Verification

**Files:**
- All files above.

- [ ] **Step 1: Run focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_manifest.py tests/test_full_app_healthcheck_runner.py tests/test_full_app_healthcheck_reporting.py tests/test_full_app_healthcheck_test_suite_bridge.py tests/test_full_app_healthcheck_coverage_matrix.py tests/test_full_app_healthcheck_flow_diagnostics.py -q -o addopts=
```

Expected: all passed.

- [ ] **Step 2: Run existing UI smoke tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py tests/test_ui_qt_decision_desk_view.py tests/test_ui_qt_research_workflow.py -q -o addopts=
```

Expected: all passed or document pre-existing failures.

- [ ] **Step 3: Run CLI quick mode**

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck --fail-fast
```

Expected: non-zero only if a real UI check fails. No formal data files are modified.

- [ ] **Step 4: Run syntax checks**

```powershell
.\.venv\Scripts\python.exe -m py_compile qa\full_app_healthcheck\__init__.py qa\full_app_healthcheck\manifest.py qa\full_app_healthcheck\default_manifest.py qa\full_app_healthcheck\runner.py qa\full_app_healthcheck\actions.py qa\full_app_healthcheck\oracles.py qa\full_app_healthcheck\reporting.py qa\full_app_healthcheck\safety.py qa\full_app_healthcheck\test_suite_bridge.py qa\full_app_healthcheck\coverage_matrix.py qa\full_app_healthcheck\flow_diagnostics.py qa\full_app_healthcheck\app_context.py scripts\run_full_app_healthcheck.py
```

Expected: no output and exit code 0.

## Later Phases

後續慢慢做時建議分成以下 PR / commit 批次：

1. **Infrastructure only**：Task 1 到 Task 7。先有 manifest、safety、report、CLI；此批不宣稱具備 UI 驗收能力。
2. **Read-only real UI checks**：Task 8 到 Task 9。補主視窗導覽、tab、截圖、layout overflow。
3. **High-risk dry-run checks**：Task 10。只驗證取消流程。
4. **Oracle expansion**：補 SQLite read-only、table row count、widget geometry、text truncation 掃描。
5. **Healthcheck coverage matrix expansion**：把 `FULL_APP_HEALTHCHECK_2026_06_16.md` 的各工作區 ID 逐步搬進 coverage matrix，標記 automated、existing-test-bridged、manual-only、blocked、not-yet-automated 或 retired。
6. **Manifest expansion**：把已確認可非破壞驗證的 coverage items 逐步搬進 manifest；不能安全自動化的項目留在 coverage matrix，不硬做。
7. **Flow diagnostics expansion**：針對四大流程閉環補入口、步驟、證據、下一步導向與流程問題判讀，讓 runner 能指出「流程不合理」而不只是「測試失敗」。
8. **Version comparison**：新增 JSON 結果比較工具，比較兩次 run 或兩個 commit 的新增覆蓋、修復、退步、仍未覆蓋項目。
9. **Release gate decision**：當 runner 穩定後，再決定是否把 `quick` 模式列為正式 release gate。

## Open Questions For Future Execution

- `full` 模式是否允許讀正式 SQLite。建議允許唯讀 URI，不允許寫入。
- `full` 模式是否要啟動完整 `MainWindow` 還是以 fake service 單 view 為主。建議兩者並行：release smoke 用完整主視窗，元件回歸用 fake service。
- 是否要新增可視化模式。建議第二階段再加 `--visible`，第一階段維持 offscreen。
- 是否要自動更新 healthcheck issue 狀態。建議不要，runner 只輸出報告，避免誤把自動化通過當成人工驗證通過。
