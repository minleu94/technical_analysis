# Midnight Analyst UI Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a unified dark PySide6 design language named Midnight Analyst, then rebuild Daily Decision Desk as the first reference screen.

**Architecture:** Add a small theme package under `ui_qt/theme/` with design tokens, QSS generation, and lightweight reusable widgets. Apply global QSS once from `ui_qt/main.py`, then replace local ad hoc Daily Decision Desk styling with shared widgets and compact renderers.

**Tech Stack:** Python 3.11, PySide6, Qt stylesheet (QSS), existing pytest UI tests with `QT_QPA_PLATFORM=offscreen`, existing QA script and mypy gate.

---

## Design Contract

Midnight Analyst uses deep blue-black surfaces, restrained borders, compact spacing, crisp typography, and status colors that match investment decision semantics.

Core palette:

- `app_bg`: `#08111f`
- `surface_1`: `#0f1b2d`
- `surface_2`: `#14233a`
- `surface_3`: `#1d2f4a`
- `border`: `#263b59`
- `text_primary`: `#e5edf7`
- `text_secondary`: `#9fb0c7`
- `text_muted`: `#6f819a`
- `accent`: `#38bdf8`
- `accent_hover`: `#0ea5e9`
- `success`: `#22c55e`
- `warning`: `#f59e0b`
- `danger`: `#ef4444`
- `info`: `#60a5fa`

Shape and density:

- Panel radius: 6 px.
- Badge radius: 4 px.
- Button height: 30-34 px.
- Table row height: 26-30 px.
- No heavy shadows, animations, gradient backgrounds, or widget-per-cell tables.
- Cards are allowed only for top-level summaries, repeated metric summaries, and warnings. Do not nest cards inside cards.

## File Structure

- Create `ui_qt/theme/__init__.py`: exports theme tokens and QSS helpers.
- Create `ui_qt/theme/tokens.py`: typed constants for palette, spacing, and typography.
- Create `ui_qt/theme/qss.py`: global QSS builder and helper snippets.
- Create `ui_qt/widgets/theme_widgets.py`: `StatusBadge`, `MetricCard`, `SectionPanel`, `CompactCodeList`, `WarningList`.
- Modify `ui_qt/main.py`: apply Midnight Analyst QSS globally after `app.setStyle("Fusion")`.
- Modify `ui_qt/views/decision_desk_view.py`: remove local light styling and rebuild layout with shared widgets.
- Modify `tests/test_ui_qt_decision_desk_view.py`: assert compact lists, dark widgets, badges, and warning rendering.
- Add `tests/test_ui_qt_theme.py`: assert QSS tokens and shared widget behavior.
- Modify `docs/07_guides/APPLICATION_MANUAL.md`: describe Midnight Analyst UI language and Daily Decision Desk compact display.

---

### Task 1: Theme Tokens And Global QSS

**Files:**
- Create: `ui_qt/theme/__init__.py`
- Create: `ui_qt/theme/tokens.py`
- Create: `ui_qt/theme/qss.py`
- Add test: `tests/test_ui_qt_theme.py`

- [ ] **Step 1: Write failing tests for token and QSS availability**

Add this to `tests/test_ui_qt_theme.py`:

```python
from ui_qt.theme import MIDNIGHT_ANALYST, build_global_stylesheet


def test_midnight_analyst_tokens_expose_required_palette():
    assert MIDNIGHT_ANALYST.app_bg == "#08111f"
    assert MIDNIGHT_ANALYST.surface_1 == "#0f1b2d"
    assert MIDNIGHT_ANALYST.text_primary == "#e5edf7"
    assert MIDNIGHT_ANALYST.accent == "#38bdf8"


def test_global_stylesheet_contains_core_qt_selectors():
    qss = build_global_stylesheet()
    assert "QMainWindow" in qss
    assert "QTabWidget::pane" in qss
    assert "QTableView" in qss
    assert "#08111f" in qss
```

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py -q -o addopts=
```

Expected: FAIL because `ui_qt.theme` does not exist.

- [ ] **Step 3: Create token dataclass**

Create `ui_qt/theme/tokens.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    app_bg: str
    surface_1: str
    surface_2: str
    surface_3: str
    border: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    success: str
    warning: str
    danger: str
    info: str
    radius_panel: int = 6
    radius_badge: int = 4
    font_family: str = "'Microsoft JhengHei UI', 'Segoe UI', Arial"
    mono_family: str = "Consolas, 'Cascadia Mono', monospace"


MIDNIGHT_ANALYST = ThemeTokens(
    app_bg="#08111f",
    surface_1="#0f1b2d",
    surface_2="#14233a",
    surface_3="#1d2f4a",
    border="#263b59",
    text_primary="#e5edf7",
    text_secondary="#9fb0c7",
    text_muted="#6f819a",
    accent="#38bdf8",
    accent_hover="#0ea5e9",
    success="#22c55e",
    warning="#f59e0b",
    danger="#ef4444",
    info="#60a5fa",
)
```

- [ ] **Step 4: Create global QSS builder**

Create `ui_qt/theme/qss.py`:

```python
from .tokens import MIDNIGHT_ANALYST, ThemeTokens


def build_global_stylesheet(tokens: ThemeTokens = MIDNIGHT_ANALYST) -> str:
    return f"""
    QWidget {{
        background: {tokens.app_bg};
        color: {tokens.text_primary};
        font-family: {tokens.font_family};
        font-size: 10pt;
    }}
    QMainWindow, QDialog {{
        background: {tokens.app_bg};
    }}
    QTabWidget::pane {{
        border: 1px solid {tokens.border};
        background: {tokens.surface_1};
        border-radius: {tokens.radius_panel}px;
    }}
    QTabBar::tab {{
        background: {tokens.surface_2};
        color: {tokens.text_secondary};
        padding: 7px 12px;
        border: 1px solid {tokens.border};
        border-bottom: none;
        min-height: 24px;
    }}
    QTabBar::tab:selected {{
        background: {tokens.surface_1};
        color: {tokens.text_primary};
        border-top: 2px solid {tokens.accent};
    }}
    QPushButton {{
        background: {tokens.surface_3};
        color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        padding: 6px 10px;
        min-height: 28px;
    }}
    QPushButton:hover {{
        border-color: {tokens.accent};
        background: {tokens.surface_2};
    }}
    QPushButton:disabled {{
        color: {tokens.text_muted};
        background: {tokens.surface_1};
    }}
    QGroupBox {{
        background: {tokens.surface_1};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        margin-top: 10px;
        padding-top: 12px;
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {tokens.text_primary};
    }}
    QTableView {{
        background: {tokens.surface_1};
        alternate-background-color: {tokens.surface_2};
        color: {tokens.text_primary};
        gridline-color: {tokens.border};
        selection-background-color: {tokens.surface_3};
        selection-color: {tokens.text_primary};
        border: 1px solid {tokens.border};
    }}
    QHeaderView::section {{
        background: {tokens.surface_2};
        color: {tokens.text_secondary};
        padding: 5px 6px;
        border: 0;
        border-right: 1px solid {tokens.border};
        border-bottom: 1px solid {tokens.border};
        font-weight: 700;
    }}
    QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        background: {tokens.surface_2};
        color: {tokens.text_primary};
        border: 1px solid {tokens.border};
        border-radius: {tokens.radius_panel}px;
        padding: 5px 7px;
    }}
    QScrollArea {{
        border: 0;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: {tokens.app_bg};
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: {tokens.surface_3};
        border-radius: 5px;
    }}
    """
```

- [ ] **Step 5: Export theme helpers**

Create `ui_qt/theme/__init__.py`:

```python
from .tokens import MIDNIGHT_ANALYST, ThemeTokens
from .qss import build_global_stylesheet

__all__ = ["MIDNIGHT_ANALYST", "ThemeTokens", "build_global_stylesheet"]
```

- [ ] **Step 6: Verify tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py -q -o addopts=
```

Expected: PASS.

---

### Task 2: Shared Theme Widgets

**Files:**
- Create: `ui_qt/widgets/theme_widgets.py`
- Modify test: `tests/test_ui_qt_theme.py`

- [ ] **Step 1: Write failing shared widget tests**

Append to `tests/test_ui_qt_theme.py`:

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui_qt.widgets.theme_widgets import CompactCodeList, StatusBadge


def _app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_status_badge_maps_quality_to_dark_styles():
    _app()
    badge = StatusBadge("OBSERVED", "observed")
    assert badge.text() == "OBSERVED"
    assert "#22c55e" in badge.styleSheet()


def test_compact_code_list_limits_each_group():
    _app()
    widget = CompactCodeList(limit=4)
    widget.set_groups(
        [
            ("強勢", tuple(f"T{i:03d}" for i in range(7))),
            ("弱勢", ("W001",)),
        ]
    )
    text = widget.text()
    assert "強勢：T000, T001, T002, T003（另 3 檔）" in text
    assert "T006" not in text
    assert "弱勢：W001" in text
    assert widget.wordWrap()
```

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py -q -o addopts=
```

Expected: FAIL because `theme_widgets.py` does not exist.

- [ ] **Step 3: Implement shared widgets**

Create `ui_qt/widgets/theme_widgets.py`:

```python
from collections.abc import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ui_qt.theme import MIDNIGHT_ANALYST


class StatusBadge(QLabel):
    def __init__(self, text: str = "", quality: str = "observed", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(22)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        self.setFont(font)
        self.set_quality(quality)

    def set_quality(self, quality: str) -> None:
        token = quality.lower()
        color = {
            "observed": MIDNIGHT_ANALYST.success,
            "estimated": MIDNIGHT_ANALYST.info,
            "degraded": MIDNIGHT_ANALYST.warning,
            "missing": MIDNIGHT_ANALYST.danger,
        }.get(token, MIDNIGHT_ANALYST.text_muted)
        self.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {color}; "
            f"border: 1px solid {color}; border-radius: {MIDNIGHT_ANALYST.radius_badge}px; "
            "padding: 2px 7px;"
        )


class SectionPanel(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("midnightSectionPanel")
        self.setStyleSheet(
            f"#midnightSectionPanel {{ background: {MIDNIGHT_ANALYST.surface_1}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-weight: 700; font-size: 11pt;")
        self.layout.addWidget(title_label)


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "N/A", parent=None):
        super().__init__(parent)
        self.setObjectName("midnightMetricCard")
        self.setStyleSheet(
            f"#midnightMetricCard {{ background: {MIDNIGHT_ANALYST.surface_2}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; "
            f"border-radius: {MIDNIGHT_ANALYST.radius_panel}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_secondary}; font-size: 9pt;")
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; font-size: 15pt; font-weight: 700;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)


class CompactCodeList(QLabel):
    def __init__(self, limit: int = 8, parent=None):
        super().__init__("", parent)
        self.limit = limit
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet(f"color: {MIDNIGHT_ANALYST.text_primary}; line-height: 130%;")

    def set_groups(self, groups: Iterable[tuple[str, Sequence[str]]]) -> None:
        self.setText("\n".join(self._format_group(label, codes) for label, codes in groups))

    def _format_group(self, label: str, codes: Sequence[str]) -> str:
        items = [str(code) for code in codes if str(code)]
        if not items:
            return f"{label}：無"
        shown = items[: self.limit]
        suffix = f"（另 {len(items) - self.limit} 檔）" if len(items) > self.limit else ""
        return f"{label}：" + ", ".join(shown) + suffix


class WarningList(QLabel):
    def __init__(self, parent=None):
        super().__init__("無警示", parent)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setStyleSheet(
            f"background: {MIDNIGHT_ANALYST.surface_2}; color: {MIDNIGHT_ANALYST.text_secondary}; "
            f"border: 1px solid {MIDNIGHT_ANALYST.border}; border-radius: {MIDNIGHT_ANALYST.radius_panel}px; "
            "padding: 8px;"
        )

    def set_warnings(self, warnings: Sequence[str]) -> None:
        self.setText("\n".join(warnings) if warnings else "無警示")
```

- [ ] **Step 4: Verify shared widget tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py -q -o addopts=
```

Expected: PASS.

---

### Task 3: Apply Global Theme At Startup

**Files:**
- Modify: `ui_qt/main.py`
- Test: `tests/test_ui_qt_theme.py`

- [ ] **Step 1: Write failing test for app theme application helper**

Append to `tests/test_ui_qt_theme.py`:

```python
from ui_qt.main import apply_app_theme


def test_apply_app_theme_sets_global_stylesheet():
    app = _app()
    apply_app_theme(app)
    assert "#08111f" in app.styleSheet()
    assert "QTableView" in app.styleSheet()
```

- [ ] **Step 2: Verify test fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py::test_apply_app_theme_sets_global_stylesheet -q -o addopts=
```

Expected: FAIL because `apply_app_theme` does not exist.

- [ ] **Step 3: Add helper and call it from main**

Modify `ui_qt/main.py`:

```python
from ui_qt.theme import build_global_stylesheet


def apply_app_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(build_global_stylesheet())
```

In `main()`, replace:

```python
app.setStyle('Fusion')
print("[Main] 應用程序樣式設置完成")
```

with:

```python
apply_app_theme(app)
print("[Main] Midnight Analyst 樣式設置完成")
```

- [ ] **Step 4: Verify theme helper test passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py::test_apply_app_theme_sets_global_stylesheet -q -o addopts=
```

Expected: PASS.

---

### Task 4: Rebuild Daily Decision Desk As Reference Screen

**Files:**
- Modify: `ui_qt/views/decision_desk_view.py`
- Modify: `tests/test_ui_qt_decision_desk_view.py`

- [ ] **Step 1: Write failing tests for Midnight Analyst reference layout**

Add to `tests/test_ui_qt_decision_desk_view.py`:

```python
def test_decision_desk_view_uses_midnight_reference_widgets():
    app()
    view = DecisionDeskView(FakeBuilder(_snapshot()))

    assert hasattr(view, "overall_quality_badge")
    assert hasattr(view, "relative_strength_codes")
    assert hasattr(view, "warning_list")
    assert view.relative_strength_codes.wordWrap()
    assert "#08111f" not in view.styleSheet()


def test_decision_desk_view_renders_compact_code_widget_from_snapshot():
    app()
    snapshot = _snapshot()
    snapshot = replace(
        snapshot,
        relative_strength_liquidity=RelativeStrengthLiquiditySummary(
            as_of_date=snapshot.as_of_date,
            quality=DecisionDeskQuality.OBSERVED,
            warnings=(),
            top_strength_codes=tuple(f"T{i:03d}" for i in range(10)),
            weak_strength_codes=("W001",),
            low_liquidity_codes=("L001", "L002"),
        ),
    )

    view = DecisionDeskView(FakeBuilder(snapshot))
    text = view.relative_strength_codes.text()

    assert "強勢：T000, T001, T002, T003, T004, T005, T006, T007（另 2 檔）" in text
    assert "弱勢：W001" in text
    assert "低流動性：L001, L002" in text
```

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py::test_decision_desk_view_uses_midnight_reference_widgets tests\test_ui_qt_decision_desk_view.py::test_decision_desk_view_renders_compact_code_widget_from_snapshot -q -o addopts=
```

Expected: FAIL because the attributes do not exist yet.

- [ ] **Step 3: Replace local styling with shared widgets**

Modify `ui_qt/views/decision_desk_view.py`:

- Import `CompactCodeList`, `MetricCard`, `SectionPanel`, `StatusBadge`, `WarningList`.
- Keep `QScrollArea` and `Qt.ScrollBarAlwaysOff`.
- Replace `overall_warn_label: QTextEdit` with `warning_list: WarningList`.
- Add `overall_quality_badge: StatusBadge`.
- Add `relative_strength_codes: CompactCodeList`.
- Remove white/light local styles from `QGroupBox`, row widgets, and labels.
- Keep existing public labels used by older tests until all call sites are updated.

Use this quality mapping helper inside `DecisionDeskView`:

```python
@staticmethod
def _quality_token(quality: DecisionDeskQuality) -> str:
    return quality.value if hasattr(quality, "value") else str(quality).lower()
```

During `_render_snapshot`, set:

```python
self.overall_quality_badge.setText(self._quality_label(snapshot.overall_quality))
self.overall_quality_badge.set_quality(self._quality_token(snapshot.overall_quality))
self.relative_strength_codes.set_groups(
    [
        ("強勢", snapshot.relative_strength_liquidity.top_strength_codes),
        ("弱勢", snapshot.relative_strength_liquidity.weak_strength_codes),
        ("低流動性", snapshot.relative_strength_liquidity.low_liquidity_codes),
    ]
)
self.warning_list.set_warnings(warning_lines)
```

- [ ] **Step 4: Verify Daily Decision Desk tests pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_decision_desk_view.py -q -o addopts=
```

Expected: PASS.

---

### Task 5: Documentation And Mandatory Verification

**Files:**
- Modify: `docs/07_guides/APPLICATION_MANUAL.md`
- Optional modify: `docs/00_core/PROJECT_SNAPSHOT.md` only if the UI language becomes a project status item.

- [ ] **Step 1: Update Manual**

In `docs/07_guides/APPLICATION_MANUAL.md`, section `8. 每日決策（Daily Decision Desk）`, add:

```markdown
Daily Decision Desk 採用 Midnight Analyst 深色介面：深色背景、狀態 badge、緊湊摘要卡片與分行代碼清單。強勢、弱勢與低流動性代碼每類預設顯示前 8 檔，其餘以剩餘檔數摘要；完整資料仍由 service snapshot 保留，不因 UI 摘要而改變計算結果。
```

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_qt_theme.py tests\test_ui_qt_decision_desk_view.py tests\test_ui_qt_decision_desk_main_integration.py -q -o addopts=
```

Expected: all tests pass.

- [ ] **Step 3: Run required UI gate**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui_qt_update_view_workbench.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\qa_validate_update_tab.py
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime
.\.venv\Scripts\python.exe -m py_compile ui_qt\main.py ui_qt\views\decision_desk_view.py ui_qt\widgets\theme_widgets.py ui_qt\theme\tokens.py ui_qt\theme\qss.py
```

Expected:

- UpdateView pytest passes.
- QA report shows 21 passed, 0 failed.
- mypy shows no issues.
- py_compile exits with code 0.

- [ ] **Step 4: Inspect working tree**

Run:

```powershell
git status --short
```

Expected: only planned files and QA output if generated. Do not stage `output/qa/update_tab/RUN_LOG.txt` or `output/qa/update_tab/VALIDATION_REPORT.md` unless explicitly requested.

## Execution Notes

- This plan intentionally does not restyle every tab in the first pass.
- Daily Decision Desk becomes the reference implementation.
- After the reference screen is accepted, create a second plan to migrate `UpdateView`, Market Watch tables, Recommendation, Research Lab, Portfolio, and Runtime Observatory in that order.
- Avoid replacing `QTableView` models or adding widget-heavy table cells.
- Avoid gradients, animations, translucent effects, and expensive shadows.

