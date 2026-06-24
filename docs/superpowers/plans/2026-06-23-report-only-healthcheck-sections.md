# Report-only Healthcheck Sections 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 Full App Healthcheck output 可用 opt-in 方式附加 QA metadata sections，但不改變預設 runner 行為、不啟用 gate、不阻擋 release。

**Architecture:** 新增 `ReportSection` 作為純報告 payload，由 `report_sections.py` 從既有 metadata renderer 產生 Markdown / JSON-safe payload。`reporting.write_reports()` 只在收到 optional sections 時追加內容；CLI 透過 repeatable `--report-section` 明確 opt-in，未傳參數時輸出維持現狀。

**Tech Stack:** Python 3.12, dataclasses, pytest, `qa/full_app_healthcheck/*`, `scripts/run_full_app_healthcheck.py`。

---

## 安全邊界

- 本計畫只做 report-only integration。
- 不啟用 quick / full release gate。
- 不修改 `qa/full_app_healthcheck/test_suite_bridge.py`。
- 不啟動 `MainWindow`。
- 不執行 dialog。
- 不呼叫 live service。
- 不執行 migration、backfill apply 或正式資料寫入。
- 不把 service oracle tests 當成 UI flow steps。
- 不把 manual gap 當成 pass evidence。
- 靜態 sections 透過 `--report-section` 明確 opt-in：`coverage-burndown`、`flow-diagnostics`、`quick-gate-proposal`、`full-release-checklist`。
- `run-history-comparison` 需要 baseline / candidate manifest input，透過 `--compare-baseline-manifest` 與 `--compare-candidate-manifest` 明確 opt-in。

## 檔案結構

- 新增 `qa/full_app_healthcheck/report_sections.py`
  - 定義 `ReportSection`。
  - 定義允許的 section ids。
  - 從既有 metadata modules 建立 opt-in sections。
  - 本模組不寫檔、不執行 runner、不啟動 UI。
- 新增 `tests/test_full_app_healthcheck_report_sections.py`
  - 驗證 opt-in builder、未知 section、Markdown 聚合、payload、無副作用。
- 修改 `qa/full_app_healthcheck/reporting.py`
  - `write_reports()` 新增 optional `report_sections` 參數。
  - 只有傳入 sections 時，才寫入 Markdown / JSON。
- 修改 `tests/test_full_app_healthcheck_reporting.py`
  - 驗證預設輸出不含 optional sections。
  - 驗證 opt-in sections 會出現在 `REPORT.md` 與 `result.json`。
- 修改 `qa/full_app_healthcheck/runner.py`
  - `HealthcheckRunner` 接受 optional `report_sections` 並傳給 `write_reports()`。
- 修改 `tests/test_full_app_healthcheck_runner.py`
  - 驗證 runner 能把 opt-in sections 寫入報告。
- 修改 `scripts/run_full_app_healthcheck.py`
  - 新增 repeatable `--report-section` CLI 參數。
  - 未傳參數時預設為空 tuple，行為不變。
- 修改 inventory 與 QA docs
  - `qa/full_app_healthcheck/test_inventory.py`
  - `tests/test_full_app_healthcheck_test_inventory.py`
  - `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`
  - `docs/06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md`

---

### Task 1：Report Section Metadata Builder

**Files:**
- Create: `qa/full_app_healthcheck/report_sections.py`
- Test: `tests/test_full_app_healthcheck_report_sections.py`

- [ ] **Step 1：先寫失敗測試**

建立 `tests/test_full_app_healthcheck_report_sections.py`：

```python
import inspect
import sys

import pytest

from qa.full_app_healthcheck.report_sections import (
    ALLOWED_REPORT_SECTION_IDS,
    ReportSection,
    build_report_sections,
    render_report_sections_markdown,
)


def test_build_report_sections_is_opt_in_and_ordered():
    assert build_report_sections(()) == ()

    sections = build_report_sections(("flow-diagnostics", "quick-gate-proposal"))

    assert tuple(section.section_id for section in sections) == (
        "flow-diagnostics",
        "quick-gate-proposal",
    )
    assert all(section.payload["report_only"] is True for section in sections)


def test_report_sections_include_expected_metadata_content():
    sections = build_report_sections(("coverage-burndown", "full-release-checklist"))
    markdown = render_report_sections_markdown(sections)

    assert "Coverage Burn-down" in markdown
    assert "Full Mode Release Checklist" in markdown
    assert "report-only" in markdown
    assert "Activates Release Gate" in markdown


def test_build_report_sections_rejects_unknown_section_id():
    with pytest.raises(ValueError, match="Unknown report section"):
        build_report_sections(("unknown-section",))


def test_report_section_rejects_incomplete_values():
    with pytest.raises(ValueError, match="section_id"):
        ReportSection(section_id="", title="Title", markdown="## Title", payload={"report_only": True})

    with pytest.raises(ValueError, match="report_only"):
        ReportSection(section_id="x", title="Title", markdown="## Title", payload={})


def test_allowed_report_section_ids_are_stable():
    assert ALLOWED_REPORT_SECTION_IDS == frozenset(
        {
            "coverage-burndown",
            "flow-diagnostics",
            "quick-gate-proposal",
            "full-release-checklist",
        }
    )


def test_report_sections_have_no_execution_or_write_side_effects():
    import qa.full_app_healthcheck.report_sections as module

    module_source = inspect.getsource(module)

    assert "Path(" not in module_source
    assert "write_text" not in module_source
    assert "write_bytes" not in module_source
    assert "open(" not in module_source
    assert ".write(" not in module_source
    assert "subprocess" not in module_source
    assert "test_suite_bridge" not in module_source
    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "MainWindow" not in module_source
    assert "PySide6.QtWidgets" not in sys.modules
```

- [ ] **Step 2：確認紅燈**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_report_sections.py -q -o addopts=
```

Expected: collection 失敗，錯誤為 `ModuleNotFoundError: No module named 'qa.full_app_healthcheck.report_sections'`。

- [ ] **Step 3：寫最小實作**

建立 `qa/full_app_healthcheck/report_sections.py`，公開 API 必須包含：

```python
ALLOWED_REPORT_SECTION_IDS = frozenset(
    {
        "coverage-burndown",
        "flow-diagnostics",
        "quick-gate-proposal",
        "full-release-checklist",
    }
)


@dataclass(frozen=True)
class ReportSection:
    section_id: str
    title: str
    markdown: str
    payload: dict[str, object]
```

`ReportSection.__post_init__()` 必須驗證：

```python
if not self.section_id:
    raise ValueError("section_id is required.")
if not self.title:
    raise ValueError("title is required.")
if not self.markdown:
    raise ValueError("markdown is required.")
if self.payload.get("report_only") is not True:
    raise ValueError("payload must include report_only=True.")
```

`build_report_sections(section_ids)` 必須：

```python
def build_report_sections(section_ids: Sequence[str]) -> tuple[ReportSection, ...]:
    builders = _section_builders()
    sections: list[ReportSection] = []
    for section_id in section_ids:
        builder = builders.get(section_id)
        if builder is None:
            allowed = ", ".join(sorted(ALLOWED_REPORT_SECTION_IDS))
            raise ValueError(f"Unknown report section '{section_id}'. Allowed: {allowed}")
        sections.append(builder())
    return tuple(sections)
```

`render_report_sections_markdown(sections)` 必須：

```python
def render_report_sections_markdown(sections: Sequence[ReportSection]) -> str:
    if not sections:
        return ""
    lines = ["## Optional QA Report Sections", ""]
    for section in sections:
        lines.extend([f"### `{section.section_id}` - {section.title}", "", section.markdown, ""])
    return "\n".join(lines).rstrip()
```

每個 section builder 必須呼叫既有 generator / renderer：

- `generate_coverage_burndown_report()` / `render_coverage_burndown_markdown()`
- `generate_flow_diagnostics()` / `render_flow_diagnostics_markdown()`
- `generate_quick_mode_release_gate_proposal()` / `render_quick_mode_release_gate_proposal_markdown()`
- `generate_full_mode_release_checklist()` / `render_full_mode_release_checklist_markdown()`

每個 payload 必須包含 `report_only=True`，並只放摘要欄位，不放不可 JSON 序列化物件。

- [ ] **Step 4：確認綠燈**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_report_sections.py -q -o addopts=
```

Expected: `6 passed`。

- [ ] **Step 5：提交 Task 1**

Run:

```powershell
git add qa/full_app_healthcheck/report_sections.py tests/test_full_app_healthcheck_report_sections.py
git commit -m "Add report-only healthcheck sections"
```

Expected: commit succeeds。

---

### Task 2：Reporting Layer Optional Sections

**Files:**
- Modify: `qa/full_app_healthcheck/reporting.py`
- Modify: `tests/test_full_app_healthcheck_reporting.py`

- [ ] **Step 1：新增失敗測試**

在 `tests/test_full_app_healthcheck_reporting.py` 加入：

```python
from qa.full_app_healthcheck.report_sections import ReportSection


def test_write_reports_omits_optional_sections_by_default(tmp_path):
    result = HealthcheckResult(
        run_id="run-no-sections",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(),
    )

    files = write_reports(result, tmp_path)

    markdown = files.markdown.read_text(encoding="utf-8")
    payload = json.loads(files.json.read_text(encoding="utf-8"))
    assert "Optional QA Report Sections" not in markdown
    assert "report_sections" not in payload


def test_write_reports_includes_optional_report_sections(tmp_path):
    result = HealthcheckResult(
        run_id="run-with-sections",
        mode=HealthcheckMode.QUICK,
        status="passed",
        steps=(),
    )
    section = ReportSection(
        section_id="quick-gate-proposal",
        title="Quick Gate Proposal",
        markdown="## Quick Gate Proposal\n\n- report-only",
        payload={"report_only": True, "gate_status": "proposal-only"},
    )

    files = write_reports(result, tmp_path, report_sections=(section,))

    markdown = files.markdown.read_text(encoding="utf-8")
    payload = json.loads(files.json.read_text(encoding="utf-8"))
    assert "Optional QA Report Sections" in markdown
    assert "quick-gate-proposal" in markdown
    assert payload["report_sections"][0]["section_id"] == "quick-gate-proposal"
    assert payload["report_sections"][0]["payload"]["report_only"] is True
```

- [ ] **Step 2：確認紅燈**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_reporting.py -q -o addopts=
```

Expected: `TypeError: write_reports() got an unexpected keyword argument 'report_sections'`。

- [ ] **Step 3：修改 reporting**

在 `qa/full_app_healthcheck/reporting.py` 加入：

```python
from qa.full_app_healthcheck.report_sections import ReportSection, render_report_sections_markdown
```

修改 `write_reports()` signature：

```python
def write_reports(
    result: HealthcheckResult,
    output_dir: Path,
    coverage_items: Sequence[Any] | None = None,
    report_sections: Sequence[ReportSection] | None = None,
) -> ReportFiles:
```

JSON payload 加入：

```python
if report_sections:
    payload["report_sections"] = [asdict(section) for section in report_sections]
```

Markdown 寫入改成：

```python
markdown_path.write_text(
    _render_markdown(result, coverage_items, report_sections),
    encoding="utf-8",
)
```

`_render_markdown()` signature 改成：

```python
def _render_markdown(
    result: HealthcheckResult,
    coverage_items: Sequence[Any] | None = None,
    report_sections: Sequence[ReportSection] | None = None,
) -> str:
```

在 return 前加入：

```python
if report_sections:
    lines.append(render_report_sections_markdown(report_sections))
    lines.append("")
```

- [ ] **Step 4：確認綠燈**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_reporting.py tests/test_full_app_healthcheck_report_sections.py -q -o addopts=
```

Expected: all tests pass。

- [ ] **Step 5：提交 Task 2**

Run:

```powershell
git add qa/full_app_healthcheck/reporting.py tests/test_full_app_healthcheck_reporting.py
git commit -m "Support optional healthcheck report sections"
```

Expected: commit succeeds。

---

### Task 3：Runner 與 CLI Opt-in Wiring

**Files:**
- Modify: `qa/full_app_healthcheck/runner.py`
- Modify: `tests/test_full_app_healthcheck_runner.py`
- Modify: `scripts/run_full_app_healthcheck.py`

- [ ] **Step 1：新增失敗測試**

在 `tests/test_full_app_healthcheck_runner.py` 加入：

```python
import json

from qa.full_app_healthcheck.report_sections import ReportSection


def test_runner_writes_optional_report_sections(tmp_path):
    def fake_action(context, step):
        return {"message": "ok"}

    section = ReportSection(
        section_id="quick-gate-proposal",
        title="Quick Gate Proposal",
        markdown="## Quick Gate Proposal\n\n- report-only",
        payload={"report_only": True, "gate_status": "proposal-only"},
    )
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
        report_sections=(section,),
    )

    result = runner.run(HealthcheckMode.QUICK)
    payload = json.loads((tmp_path / result.run_id / "result.json").read_text(encoding="utf-8"))
    markdown = (tmp_path / result.run_id / "REPORT.md").read_text(encoding="utf-8")

    assert payload["report_sections"][0]["section_id"] == "quick-gate-proposal"
    assert "Optional QA Report Sections" in markdown


def test_full_app_healthcheck_cli_parse_report_sections():
    args = parse_args(
        [
            "--mode",
            "quick",
            "--report-section",
            "coverage-burndown",
            "--report-section",
            "flow-diagnostics",
        ]
    )

    assert args.report_sections == ["coverage-burndown", "flow-diagnostics"]
```

- [ ] **Step 2：確認紅燈**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py -q -o addopts=
```

Expected: 因 `HealthcheckRunner.__init__()` 尚未接受 `report_sections`，或 `args.report_sections` 尚不存在而失敗。

- [ ] **Step 3：修改 runner**

在 `qa/full_app_healthcheck/runner.py` 加入：

```python
from qa.full_app_healthcheck.report_sections import ReportSection
```

在 `HealthcheckRunner.__init__()` 加入參數：

```python
report_sections: tuple[ReportSection, ...] | None = None,
```

保存欄位：

```python
self.report_sections = report_sections
```

改寫 report call：

```python
write_reports(
    result,
    self.output_dir / result.run_id,
    self.coverage_items,
    self.report_sections,
)
```

- [ ] **Step 4：修改 CLI**

在 `scripts/run_full_app_healthcheck.py` 加入：

```python
from qa.full_app_healthcheck.report_sections import ALLOWED_REPORT_SECTION_IDS, build_report_sections
```

在 `parse_args()` 加入：

```python
parser.add_argument(
    "--report-section",
    dest="report_sections",
    action="append",
    choices=sorted(ALLOWED_REPORT_SECTION_IDS),
    default=[],
    help="Append an opt-in, report-only QA metadata section to REPORT.md and result.json.",
)
```

在 `main()` 建立 sections：

```python
report_sections = build_report_sections(args.report_sections)
```

傳入 runner：

```python
report_sections=report_sections,
```

- [ ] **Step 5：確認綠燈**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_runner.py tests/test_full_app_healthcheck_reporting.py tests/test_full_app_healthcheck_report_sections.py -q -o addopts=
```

Expected: all tests pass。

- [ ] **Step 6：驗證 CLI 預設與 opt-in**

Run default:

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
```

Expected: `Healthcheck passed: <run_id>`。

Run opt-in:

```powershell
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast --report-section quick-gate-proposal --report-section full-release-checklist
```

Expected: `Healthcheck passed: <run_id>`，產出的 `REPORT.md` 包含 `Optional QA Report Sections`，且不啟用 gate。

- [ ] **Step 7：提交 Task 3**

Run:

```powershell
git add qa/full_app_healthcheck/runner.py scripts/run_full_app_healthcheck.py tests/test_full_app_healthcheck_runner.py
git commit -m "Wire opt-in healthcheck report sections"
```

Expected: commit succeeds。

---

### Task 4：Inventory、文件與最終驗證

**Files:**
- Modify: `qa/full_app_healthcheck/test_inventory.py`
- Modify: `tests/test_full_app_healthcheck_test_inventory.py`
- Modify: `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md`
- Modify: `docs/06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md`

- [ ] **Step 1：註冊新測試檔**

在 `qa/full_app_healthcheck/test_inventory.py` 的 `healthcheck-runner-owned` 區塊加入：

```python
"tests/test_full_app_healthcheck_report_sections.py": "healthcheck-runner-owned",
```

- [ ] **Step 2：取得實際 collect-only 數量**

Run:

```powershell
$out = .\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=; if ($LASTEXITCODE -ne 0) { $out; exit $LASTEXITCODE }; $out[-1]
```

Expected: 新增一個 collected test file 與六個 tests 後，預期為 `1037 tests collected`；若實際時間 suffix 不同，以命令回報的 test count 為準。

- [ ] **Step 3：更新 inventory assertions**

在 `tests/test_full_app_healthcheck_test_inventory.py` 更新：

```python
assert len(PYTEST_COLLECTED_FILES) == 177
assert len(get_files_by_category("healthcheck-runner-owned")) == 28
```

- [ ] **Step 4：更新 QA classification 文件**

在 `docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md` 更新：

```markdown
目前有效測試區 Python 檔共 208 個，不含 `__pycache__` 與 `.pytest_cache`。分類結果如下：
| `healthcheck-runner-owned` | 28 | Runner 自身單元測試，不由 runner 呼叫。 |
| 預設 pytest gate 會收集 | 177 files / 1037 tests | 仍屬現行自動化測試；沒有逐名出現在文件中也不代表 unused。 |
| 目前已由 healthcheck runner bridge 呼叫 | 6 files | direct bridge UI 測試；另有 `scripts/qa_validate_update_tab.py` 作為 QA script bridge，不屬 `tests/` 208 files。 |
```

並在 healthcheck-runner-owned 清單加入：

```markdown
- `tests/test_full_app_healthcheck_report_sections.py`
```

- [ ] **Step 5：更新 closeout**

在 `docs/06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md` 的「建議下一步」段落確認保留：

```markdown
補充：選項 2 已完成為 opt-in report-only sections，可透過 `--report-section` 加入 coverage burn-down、flow diagnostics、quick gate proposal 與 full release checklist；也可透過 `--compare-baseline-manifest` 與 `--compare-candidate-manifest` 加入 run-history-comparison。未傳上述參數時預設 healthcheck output 與 runner bridge 行為不變。
```

- [ ] **Step 6：最終驗證**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_full_app_healthcheck_report_sections.py tests/test_full_app_healthcheck_reporting.py tests/test_full_app_healthcheck_runner.py tests/test_full_app_healthcheck_test_inventory.py -q -o addopts=
.\.venv\Scripts\python.exe -m pytest --collect-only -q -o addopts=
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast
.\.venv\Scripts\python.exe scripts\run_full_app_healthcheck.py --mode quick --output-dir output\qa\full_app_healthcheck_tmp --fail-fast --report-section quick-gate-proposal --report-section full-release-checklist
.\.venv\Scripts\python.exe -m py_compile qa/full_app_healthcheck/report_sections.py qa/full_app_healthcheck/reporting.py qa/full_app_healthcheck/runner.py scripts/run_full_app_healthcheck.py tests/test_full_app_healthcheck_report_sections.py tests/test_full_app_healthcheck_reporting.py tests/test_full_app_healthcheck_runner.py
git diff --check
```

Expected:

- Focused tests pass。
- collect-only count 與文件一致。
- default quick runner passes。
- opt-in quick runner passes。
- `py_compile` succeeds。
- `git diff --check` 無 whitespace errors。

- [ ] **Step 7：提交 Task 4**

Run:

```powershell
git add qa/full_app_healthcheck/test_inventory.py tests/test_full_app_healthcheck_test_inventory.py docs/06_qa/TEST_INVENTORY_HEALTHCHECK_CLASSIFICATION_2026_06_23.md docs/06_qa/FULL_APP_HEALTHCHECK_AGENT_CLOSEOUT_2026_06_23.md
git commit -m "Document report-only healthcheck sections"
```

Expected: commit succeeds。

---

## 最終交接

所有 tasks 通過後推送：

```powershell
git push origin main
```

最終回報必須包含：

- Commit hashes。
- 驗證命令與輸出。
- 確認未使用 `--report-section` 時，預設 healthcheck 行為不變。
- 確認沒有新增 release gate、runner bridge mutation、MainWindow execution、dialog execution、service call、migration、backfill apply 或資料寫入。
