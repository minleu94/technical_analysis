"""檢查金融核心白名單中的 float 邊界標記。"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


ALLOWED_CATEGORIES = frozenset({"dto", "analytics", "visualization"})
REPO_ROOT = Path(__file__).resolve().parents[1]
FINANCIAL_FLOAT_BOUNDARY_FILES = (
    "backtest_module/broker_simulator.py",
    "backtest_module/performance_metrics.py",
    "portfolio_module/core.py",
    "app_module/portfolio_service.py",
    "app_module/recommendation_portfolio_backtest_service.py",
    "app_module/recommendation_portfolio_dtos.py",
)
BOUNDARY_MARKER_INTENT = re.compile(r"^#\s*numeric-boundary")
BOUNDARY_MARKER = re.compile(r"^#\s*numeric-boundary:\s*(\S+)\s*$")


class BoundaryCheckError(RuntimeError):
    """來源檔無法接受治理檢查。"""


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    column: int
    rule: str
    expression: str
    message: str


def _comment_categories(source: str, *, path: str) -> dict[int, str | None]:
    categories: dict[int, str | None] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if (
                token.type != tokenize.COMMENT
                or not BOUNDARY_MARKER_INTENT.match(token.string.strip())
            ):
                continue
            match = BOUNDARY_MARKER.fullmatch(token.string.strip())
            categories[token.start[0]] = match.group(1) if match else None
    except (IndentationError, tokenize.TokenError) as exc:
        raise BoundaryCheckError(f"{path}: 無法解析註解: {exc}") from exc
    return categories


def _is_float_value(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "float") or (
        isinstance(node, ast.Constant) and node.value == "float"
    )


def _managed_calls(tree: ast.AST) -> list[tuple[ast.expr, str, str]]:
    matches: list[tuple[ast.expr, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            matches.append((node.func, "NFB001", "float(...)"))
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "astype"
            and node.args
            and _is_float_value(node.args[0])
        ):
            matches.append((node.args[0], "NFB002", ".astype(float)"))
        for keyword in node.keywords:
            if keyword.arg == "dtype" and _is_float_value(keyword.value):
                matches.append((keyword.value, "NFB003", "dtype=float"))
    return matches


def scan_source(source: str, *, path: str = "<memory>") -> list[Violation]:
    categories = _comment_categories(source, path=path)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise BoundaryCheckError(f"{path}: 無法解析 Python: {exc.msg}") from exc

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
                    message=(
                        "numeric-boundary 分類必須是 dto、analytics 或 visualization"
                    ),
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


def scan_paths(root: Path, paths: Sequence[str]) -> list[Violation]:
    violations: list[Violation] = []
    for relative_path in paths:
        source_path = root / relative_path
        if not source_path.is_file():
            raise BoundaryCheckError(f"{relative_path}: 白名單檔案不存在")
        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BoundaryCheckError(f"{relative_path}: 無法讀取: {exc}") from exc
        violations.extend(scan_source(source, path=relative_path))
    return sorted(
        violations,
        key=lambda item: (item.path, item.line, item.column, item.rule),
    )


def _format_violation(violation: Violation) -> str:
    return (
        f"{violation.path}:{violation.line}:{violation.column} "
        f"{violation.rule} {violation.message} [{violation.expression}]"
    )


def _configure_stdout_utf8() -> None:
    if (
        hasattr(sys.stdout, "reconfigure")
        and str(getattr(sys.stdout, "encoding", "")).lower() != "utf-8"
    ):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError, io.UnsupportedOperation):
            pass


def main() -> int:
    _configure_stdout_utf8()

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
