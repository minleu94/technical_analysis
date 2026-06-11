"""檢查金融核心白名單中的 float 邊界標記。"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass


ALLOWED_CATEGORIES = frozenset({"dto", "analytics", "visualization"})
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


def _managed_calls(tree: ast.AST) -> list[tuple[ast.AST, str, str]]:
    matches: list[tuple[ast.AST, str, str]] = []
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
