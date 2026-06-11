# 金融 Float 邊界治理實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 建立 AST 型金融 `float` 邊界掃描器、逐行分類標記與 pytest repository gate，阻擋金融核心白名單重新出現未審查的浮點邊界。

**Architecture:** 使用單一 `scripts/check_financial_float_boundaries.py` 提供純函式掃描 API 與 CLI。`ast` 負責辨識受管制語法，`tokenize` 負責同一實體行的分類註解；pytest 先驗證 source-level contract，再以固定白名單執行 repository gate。

**Tech Stack:** Python 3、標準庫 `ast` / `tokenize` / `dataclasses` / `pathlib`、pytest、mypy。

---

## 檔案結構

- Create: `scripts/check_financial_float_boundaries.py`
  - 固定白名單、AST/tokenize 掃描、結構化 violation 與 CLI。
- Create: `tests/test_financial_float_boundary_checker.py`
  - source-level 規則、錯誤處理與 repository gate。
- Modify: `backtest_module/broker_simulator.py`
  - 對 `Trade` DTO float 轉換加入 `dto` 標記。
- Modify: `backtest_module/performance_metrics.py`
  - 對績效 analytics 與回傳 DTO 邊界加入標記。
- Modify: `portfolio_module/core.py`
  - 對 mapping、domain projection 與公開 float contract 加入 `dto` 標記。
- Modify: `app_module/portfolio_service.py`
  - 對 DTO 與 summary 回傳邊界加入 `dto` 標記。
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
  - 對 pandas 輸入、分析指標與 DTO 邊界加入對應標記。
- Modify: `app_module/recommendation_portfolio_dtos.py`
  - 對 PnL DTO 回傳邊界加入 `dto` 標記。
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
  - 將 float 邊界制度化標記完成。
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
  - 同步治理狀態與本週優先事項。
- Modify: `docs/00_core/NEXT_ACTION_PLAN.md`
  - 記錄 P0 金融數值治理收尾結果。
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
  - 加入本實作計畫入口。
- Modify: `docs/agents/shared_state/active_task.yaml`
  - 更新執行與驗證狀態。

## 安全檢查

- Look-ahead bias：本計畫只做 Python source 靜態掃描與註解，不改訊號日、成交日、停損停利、benchmark 或資料窗口。
- 正式資料：不讀寫 `DATA_ROOT`。
- SQLite / CSV：不讀寫、不 migration。
- 金融計算：不改運算式，只標記既有相容邊界；若掃描發現未隔離的核心金額計算，停止標記並改用既有 Decimal helper。
- Git：每次 stage 前執行 `git status --short`，不 stage QA output 或非本任務變更。

### Task 1: 以失敗測試定義 Source-Level 掃描 Contract

**Files:**
- Create: `tests/test_financial_float_boundary_checker.py`
- Create: `scripts/check_financial_float_boundaries.py`

- [x] **Step 1: 建立未標記 `float()` 的失敗測試**

```python
from scripts.check_financial_float_boundaries import scan_source


def test_unmarked_float_call_is_reported() -> None:
    violations = scan_source("value = float(raw)\n", path="sample.py")

    assert [(item.rule, item.line, item.expression) for item in violations] == [
        ("NFB001", 1, "float(...)")
    ]
```

- [x] **Step 2: 執行測試並確認因掃描器不存在而失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py::test_unmarked_float_call_is_reported -q -o addopts=
```

Expected: FAIL during import because `scripts.check_financial_float_boundaries` does not exist.

- [x] **Step 3: 實作最小 `Violation` 與 `scan_source()`**

Create `scripts/check_financial_float_boundaries.py` with:

```python
"""檢查金融核心白名單中的 float 邊界標記。"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    column: int
    rule: str
    expression: str
    message: str


def scan_source(source: str, *, path: str = "<memory>") -> list[Violation]:
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
        ):
            violations.append(
                Violation(
                    path=path,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    rule="NFB001",
                    expression="float(...)",
                    message="float(...) 必須標記合法數值邊界",
                )
            )
    return sorted(violations, key=lambda item: (item.line, item.column, item.rule))
```

- [x] **Step 4: 執行單一測試並確認通過**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py::test_unmarked_float_call_is_reported -q -o addopts=
```

Expected: `1 passed`.

- [x] **Step 5: 追加合法標記、非法標記、astype、dtype 與誤報測試**

Append to `tests/test_financial_float_boundary_checker.py`:

```python
import pytest

from scripts.check_financial_float_boundaries import BoundaryCheckError


@pytest.mark.parametrize("category", ["dto", "analytics", "visualization"])
def test_supported_boundary_categories_allow_same_line_float(category: str) -> None:
    source = f"value = float(raw)  # numeric-boundary: {category}\n"
    assert scan_source(source, path="sample.py") == []


def test_invalid_boundary_category_is_reported_once() -> None:
    violations = scan_source(
        "left = float(a); right = float(b)  # numeric-boundary: allow\n",
        path="sample.py",
    )
    assert [(item.rule, item.line) for item in violations] == [("NFB004", 1)]


@pytest.mark.parametrize(
    ("source", "rule", "expression"),
    [
        ("values.astype(float)\n", "NFB002", ".astype(float)"),
        ('values.astype("float")\n', "NFB002", ".astype(float)"),
        ("pd.Series(values, dtype=float)\n", "NFB003", "dtype=float"),
        ('pd.Series(values, dtype="float")\n', "NFB003", "dtype=float"),
    ],
)
def test_numpy_pandas_float_boundaries_are_reported(
    source: str,
    rule: str,
    expression: str,
) -> None:
    violations = scan_source(source, path="sample.py")
    assert [(item.rule, item.expression) for item in violations] == [(rule, expression)]


def test_comments_strings_and_previous_line_marker_do_not_hide_violation() -> None:
    source = (
        '# float(raw)\n'
        'message = "float(raw)"\n'
        "# numeric-boundary: dto\n"
        "value = float(raw)\n"
    )
    violations = scan_source(source, path="sample.py")
    assert [(item.rule, item.line) for item in violations] == [("NFB001", 4)]


def test_syntax_error_raises_boundary_check_error() -> None:
    with pytest.raises(BoundaryCheckError, match="無法解析"):
        scan_source("value = float(\n", path="broken.py")
```

- [x] **Step 6: 執行新增測試並確認正確失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py -q -o addopts=
```

Expected: first test passes; new tests fail because marker、`astype`、`dtype` and `BoundaryCheckError` are not implemented.

- [x] **Step 7: 完成 AST/tokenize source scanner**

Replace the scanner body with these components:

```python
import io
import re
import tokenize

ALLOWED_CATEGORIES = frozenset({"dto", "analytics", "visualization"})
BOUNDARY_MARKER = re.compile(r"^#\s*numeric-boundary:\s*(\S+)\s*$")


class BoundaryCheckError(RuntimeError):
    """來源檔無法接受治理檢查。"""


def _comment_categories(source: str, *, path: str) -> dict[int, str | None]:
    categories: dict[int, str | None] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT or "numeric-boundary:" not in token.string:
                continue
            match = BOUNDARY_MARKER.fullmatch(token.string.strip())
            categories[token.start[0]] = match.group(1) if match else None
    except (IndentationError, tokenize.TokenError) as exc:
        raise BoundaryCheckError(f"{path}: 無法解析註解: {exc}") from exc
    return categories


def _is_float_value(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Name)
        and node.id == "float"
    ) or (
        isinstance(node, ast.Constant)
        and node.value == "float"
    )


def _managed_calls(tree: ast.AST) -> list[tuple[ast.Call, str, str]]:
    matches: list[tuple[ast.Call, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            matches.append((node, "NFB001", "float(...)"))
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "astype"
            and node.args
            and _is_float_value(node.args[0])
        ):
            matches.append((node, "NFB002", ".astype(float)"))
        if any(
            keyword.arg == "dtype" and _is_float_value(keyword.value)
            for keyword in node.keywords
        ):
            matches.append((node, "NFB003", "dtype=float"))
    return matches
```

Implement `scan_source()` so that:

```python
def scan_source(source: str, *, path: str = "<memory>") -> list[Violation]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise BoundaryCheckError(f"{path}: 無法解析 Python: {exc.msg}") from exc

    categories = _comment_categories(source, path=path)
    violations: list[Violation] = []
    invalid_marker_lines: set[int] = set()

    for line, category in categories.items():
        if category not in ALLOWED_CATEGORIES:
            invalid_marker_lines.add(line)
            violations.append(
                Violation(
                    path=path,
                    line=line,
                    column=1,
                    rule="NFB004",
                    expression="numeric-boundary",
                    message="numeric-boundary 分類必須是 dto、analytics 或 visualization",
                )
            )

    for node, rule, expression in _managed_calls(tree):
        category = categories.get(node.lineno)
        if category in ALLOWED_CATEGORIES or node.lineno in invalid_marker_lines:
            continue
        violations.append(
            Violation(
                path=path,
                line=node.lineno,
                column=node.col_offset + 1,
                rule=rule,
                expression=expression,
                message=f"{expression} 必須標記合法數值邊界",
            )
        )

    return sorted(violations, key=lambda item: (item.line, item.column, item.rule))
```

此實作保證：

1. `ast.parse()` exceptions become `BoundaryCheckError`。
2. Invalid marker lines create one `NFB004` violation each。
3. Valid same-line categories suppress managed-call violations。
4. Invalid marker lines do not additionally emit `NFB001`/`NFB002`/`NFB003`。
5. Results sort by `(line, column, rule)`。

- [x] **Step 8: 執行 source-level 測試並確認全綠**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py -q -o addopts=
```

Expected: all source-level tests pass.

- [x] **Step 9: 提交 source scanner**

```powershell
git status --short
git add scripts/check_financial_float_boundaries.py tests/test_financial_float_boundary_checker.py
git commit -m "test: define financial float boundary scanner"
```

### Task 2: 建立固定白名單、CLI 與錯誤處理

**Files:**
- Modify: `scripts/check_financial_float_boundaries.py`
- Modify: `tests/test_financial_float_boundary_checker.py`

- [x] **Step 1: 先寫路徑掃描與缺檔失敗測試**

Append:

```python
from pathlib import Path

from scripts.check_financial_float_boundaries import scan_paths


def test_scan_paths_reports_relative_path(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("value = float(raw)\n", encoding="utf-8")

    violations = scan_paths(tmp_path, ("module.py",))

    assert [(item.path, item.rule) for item in violations] == [
        ("module.py", "NFB001")
    ]


def test_scan_paths_fails_when_allowlisted_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(BoundaryCheckError, match="白名單檔案不存在"):
        scan_paths(tmp_path, ("missing.py",))
```

- [x] **Step 2: 執行兩個測試並確認因 `scan_paths` 不存在而失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py -q -o addopts=
```

Expected: collection/import fails for missing `scan_paths`.

- [x] **Step 3: 實作固定白名單與 `scan_paths()`**

Add:

```python
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
FINANCIAL_FLOAT_BOUNDARY_FILES = (
    "backtest_module/broker_simulator.py",
    "backtest_module/performance_metrics.py",
    "portfolio_module/core.py",
    "app_module/portfolio_service.py",
    "app_module/recommendation_portfolio_backtest_service.py",
    "app_module/recommendation_portfolio_dtos.py",
)


def scan_paths(root: Path, paths: Sequence[str]) -> list[Violation]:
    violations: list[Violation] = []
    for relative_path in paths:
        target = root / relative_path
        if not target.is_file():
            raise BoundaryCheckError(f"{relative_path}: 白名單檔案不存在")
        try:
            source = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise BoundaryCheckError(f"{relative_path}: 無法讀取: {exc}") from exc
        violations.extend(scan_source(source, path=relative_path))
    return sorted(
        violations,
        key=lambda item: (item.path, item.line, item.column, item.rule),
    )
```

- [x] **Step 4: 執行路徑測試並確認通過**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py -q -o addopts=
```

Expected: all current tests pass.

- [x] **Step 5: 實作 CLI**

Add:

```python
def _format_violation(violation: Violation) -> str:
    return (
        f"{violation.path}:{violation.line}:{violation.column} "
        f"{violation.rule} {violation.message} [{violation.expression}]"
    )


def main() -> int:
    try:
        violations = scan_paths(REPO_ROOT, FINANCIAL_FLOAT_BOUNDARY_FILES)
    except BoundaryCheckError as exc:
        print(f"NFB000 {exc}")
        return 1
    for violation in violations:
        print(_format_violation(violation))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 6: 執行 CLI 並確認它因現存未標記邊界回傳失敗**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: exit code `1`，輸出六個白名單檔案的 `NFB001` / `NFB003` violations。這是預期 RED 狀態。

- [x] **Step 7: 提交 CLI 與白名單**

```powershell
git status --short
git add scripts/check_financial_float_boundaries.py tests/test_financial_float_boundary_checker.py
git commit -m "feat: add financial float boundary checker cli"
```

### Task 3: 建立 Repository Gate 並標記既有合法邊界

**Files:**
- Modify: `tests/test_financial_float_boundary_checker.py`
- Modify: `backtest_module/broker_simulator.py`
- Modify: `backtest_module/performance_metrics.py`
- Modify: `portfolio_module/core.py`
- Modify: `app_module/portfolio_service.py`
- Modify: `app_module/recommendation_portfolio_backtest_service.py`
- Modify: `app_module/recommendation_portfolio_dtos.py`

- [x] **Step 1: 先寫 repository gate**

Append:

```python
from scripts.check_financial_float_boundaries import (
    FINANCIAL_FLOAT_BOUNDARY_FILES,
    REPO_ROOT,
)


def test_financial_core_allowlist_has_no_unmarked_float_boundaries() -> None:
    violations = scan_paths(REPO_ROOT, FINANCIAL_FLOAT_BOUNDARY_FILES)

    assert violations == [], "\n".join(
        f"{item.path}:{item.line}:{item.column} {item.rule} {item.message}"
        for item in violations
    )
```

- [x] **Step 2: 執行 repository gate 並確認因現存未標記邊界失敗**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py::test_financial_core_allowlist_has_no_unmarked_float_boundaries -q -o addopts=
```

Expected: FAIL with current white-list violations.

- [x] **Step 3: 標記 `broker_simulator.py` 的 Trade DTO 邊界**

在 `_execute_buy()` 與 `_execute_sell()` 的 `Trade(...)` 建構值同一行加入：

```python
price=float(execution_price_dec),  # numeric-boundary: dto
value=float(value_dec),  # numeric-boundary: dto
fee=float(fee_dec),  # numeric-boundary: dto
slippage=float(slippage_cost_dec),  # numeric-boundary: dto
```

賣出 fee 行保留原本中文說明並改為：

```python
fee=float(fee_dec + tax_dec),  # numeric-boundary: dto
```

- [x] **Step 4: 標記 Portfolio domain/service DTO 邊界**

在 `portfolio_module/core.py`：

- `Trade.from_mapping()` 的 quantity、price、fees、taxes → `dto`
- `Position.invested_amount` 回傳 → `dto`
- 建立／更新 `Position` 的 quantity、average_cost、realized_pnl → `dto`

範例：

```python
quantity=float(data.get("quantity", 0.0)),  # numeric-boundary: dto
return float(quantize_money(amount))  # numeric-boundary: dto
```

在 `app_module/portfolio_service.py`：

- `TradeDTO(...)` 的 quantity、price、fees、taxes → `dto`
- `_sum_money()` 回傳 → `dto`

- [x] **Step 5: 標記績效分析邊界**

在 `backtest_module/performance_metrics.py`：

- `_trade_profit()`、`_sum_money()`、`_mean_money()` 對公開 float contract 的回傳 → `dto`
- `_trade_return_pct()`、權益曲線、CAGR、Sharpe、drawdown、baseline comparison、walk-forward consistency → `analytics`
- `PerformanceMetrics(...)` 建構時的 `float(...)` → `dto`
- `pd.Series(dtype=float)` → `analytics`

同一行已有其他註解時，以數值治理標記取代非必要敘述，必要中文說明移到前一行。例如：

```python
return float(to_decimal(profit) / invested_dec)  # numeric-boundary: analytics
returns = pd.Series(dtype=float)  # numeric-boundary: analytics
total_return=float(total_return),  # numeric-boundary: dto
```

精確分類清單：

| 現有位置／運算 | 分類 |
|---|---|
| `_trade_profit()` 回傳 | `dto` |
| `_trade_return_pct()` 回傳 | `analytics` |
| `_sum_money()` / `_mean_money()` 回傳 | `dto` |
| `summarize()` 的 final equity、initial capital、return、CAGR、Sharpe、drawdown 正規化 | `analytics` |
| `pd.Series(dtype=float)` | `analytics` |
| `PerformanceMetrics(...)` 的 total/annual/sharpe/drawdown 欄位 | `dto` |
| baseline 起訖價格、return、annualized return、drawdown、Sharpe | `analytics` |
| baseline 結果 dict 的四個 float 欄位 | `dto` |
| `calculate_baseline_comparison()` 的六個輸入正規化與四個比較運算 | `analytics` |
| `calculate_consistency()` 的 `std_dev` 與 `normalized_std` | `analytics` |

- [x] **Step 6: 標記推薦組合 backtest 與 DTO 邊界**

在 `app_module/recommendation_portfolio_backtest_service.py`：

- pandas row 的價格／分數輸入轉換 → `analytics`
- equity curve 輸出、holding PnL 回傳與 DTO 欄位轉換 → `dto`
- score weighting 與 max drawdown → `analytics`

分類範例：

```python
entry_price = float(entry_row["收盤價"])  # numeric-boundary: analytics
total_score=float(rec.get("total_score", 0.0)),  # numeric-boundary: dto
return float(drawdown.min())  # numeric-boundary: analytics
```

在 `app_module/recommendation_portfolio_dtos.py`：

```python
return float(  # numeric-boundary: dto
    quantize_money(
        to_decimal(self.allocation_amount) * to_decimal(self.return_pct)
    )
)
```

`recommendation_portfolio_backtest_service.py` 的精確分類清單：

| 現有位置／運算 | 分類 |
|---|---|
| entry / exit / stop-check / mark-to-market 收盤價 | `analytics` |
| recommendation `total_score` 讀取與 score weighting | `analytics`，但寫入 `PeriodHoldingDTO.total_score` 的建構行標記 `dto` |
| equity curve 的 `round(float(equity), 6)` 與 final equity | `dto` |
| `_holding_pnl_at_date()` 金額量化後回傳 | `dto` |
| `_calculate_max_drawdown()` 回傳 | `analytics` |

- [x] **Step 7: 執行 repository gate 並確認通過**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: pytest 全部通過，CLI exit code `0` 且無 violation。

- [x] **Step 8: 執行既有金融治理回歸測試**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_units.py tests/test_performance_numeric_governance.py tests/test_portfolio_numeric_governance.py tests/test_recommendation_portfolio_numeric_governance.py -q -o addopts=
```

Expected: all pass.

- [x] **Step 9: 提交 repository gate 與標記**

```powershell
git status --short
git add tests/test_financial_float_boundary_checker.py scripts/check_financial_float_boundaries.py backtest_module/broker_simulator.py backtest_module/performance_metrics.py portfolio_module/core.py app_module/portfolio_service.py app_module/recommendation_portfolio_backtest_service.py app_module/recommendation_portfolio_dtos.py
git commit -m "test: enforce financial float boundary annotations"
```

### Task 4: 文件收尾與完整驗證

**Files:**
- Modify: `docs/00_core/DEVELOPMENT_ROADMAP.md`
- Modify: `docs/00_core/PROJECT_SNAPSHOT.md`
- Modify: `docs/00_core/NEXT_ACTION_PLAN.md`
- Modify: `docs/00_core/DOCUMENTATION_INDEX.md`
- Modify: `docs/agents/shared_state/active_task.yaml`

- [x] **Step 1: 更新 Roadmap**

在 Living Section「金融核心數值治理」將原本：

```text
⏳ 下一步：制度化檢查其餘 analytics / visualization 邊界
```

改為完成狀態，記錄：

- 固定金融核心白名單。
- AST 偵測 `float()` / `astype(float)` / `dtype=float`。
- 只接受 `dto` / `analytics` / `visualization` 逐行標記。
- pytest repository gate 已建立。

- [x] **Step 2: 同步 Snapshot 與 Next Action Plan**

`PROJECT_SNAPSHOT.md`：

- 本週優先事項第 1 項改為 Portfolio Phase 4.1 深化。
- 技術治理進展補上 float 邊界 gate 完成。
- 高風險區保留金融核心，但說明已有自動防回歸。

`NEXT_ACTION_PLAN.md`：

- P0 金融核心數值治理標記為完成。
- 尚未完成項目導向 Portfolio 策略版本追蹤、Price 對照與持倉風險提示。

- [x] **Step 3: 更新索引與 shared state**

在 `DOCUMENTATION_INDEX.md` 加入：

```markdown
| [2026-06-11-financial-float-boundary-governance.md](../superpowers/plans/2026-06-11-financial-float-boundary-governance.md) | 金融 float 邊界 AST 掃描與 pytest gate 實作計畫。 |
```

更新 `active_task.yaml`：

```yaml
status: verification
verification:
  pytest: pass
  mypy: pending
  py_compile: pending
next_action: 執行完整型態與語法驗證
```

- [x] **Step 4: 執行語法檢查**

Run:

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\check_financial_float_boundaries.py tests\test_financial_float_boundary_checker.py backtest_module\broker_simulator.py backtest_module\performance_metrics.py portfolio_module\core.py app_module\portfolio_service.py app_module\recommendation_portfolio_backtest_service.py app_module\recommendation_portfolio_dtos.py
```

Expected: exit code `0`.

- [x] **Step 5: 執行型態檢查**

Run:

```powershell
.\.venv\Scripts\python.exe -m mypy ui_qt app_module data_module analysis_module backtest_module decision_module portfolio_module runtime financial_module scripts\check_financial_float_boundaries.py
```

Expected: 不新增錯誤；若 repo 既有 baseline error，記錄完整輸出並確認本次檔案無新增錯誤。

- [x] **Step 6: 執行最終測試矩陣**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_financial_float_boundary_checker.py tests/test_financial_units.py tests/test_performance_numeric_governance.py tests/test_portfolio_numeric_governance.py tests/test_recommendation_portfolio_numeric_governance.py -q -o addopts=
.\.venv\Scripts\python.exe scripts\check_financial_float_boundaries.py
```

Expected: 全部通過，CLI exit code `0`。

- [x] **Step 7: 更新 shared state 為完成驗證**

```yaml
status: done
verification:
  pytest: pass
  mypy: pass
  py_compile: pass
next_action: 進入 Portfolio Phase 4.1 深化設計
```

若 mypy 只有既有 baseline error，`mypy` 記為 `baseline_only`，並在 YAML 加入 `verification_notes`。

- [x] **Step 8: 檢查文件一致性與 Git 範圍**

Run:

```powershell
git diff --check
git status --short
```

Expected:

- Roadmap、Snapshot、Next Action Plan 對 float 治理狀態一致。
- 無 QA output、本機資料庫、暫存檔或非本任務檔案被 stage。

- [x] **Step 9: 提交文件收尾**

```powershell
git add docs/00_core/DEVELOPMENT_ROADMAP.md docs/00_core/PROJECT_SNAPSHOT.md docs/00_core/NEXT_ACTION_PLAN.md docs/00_core/DOCUMENTATION_INDEX.md docs/agents/shared_state/active_task.yaml
git commit -m "docs: complete financial float boundary governance"
```

## 完成條件

- 所有新函式均先有失敗測試。
- source-level scanner 與 repository gate 全綠。
- CLI 對固定白名單回傳 exit code `0`。
- 六個白名單檔案沒有未標記的受管制 float 語法。
- 既有金融數值治理測試全綠。
- `py_compile` 通過。
- mypy 無本次新增錯誤。
- Roadmap / Snapshot / Next Action Plan / Index 一致。
