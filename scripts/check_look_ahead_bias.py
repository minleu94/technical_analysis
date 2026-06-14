"""未來函數 (Look-ahead bias) 靜態檢查工具。"""

from __future__ import annotations

import ast
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
STRATEGY_FILES_TO_SCAN = (
    "app_module/strategies/baseline_score_executor.py",
    "app_module/strategies/momentum_aggressive_executor.py",
    "app_module/strategies/stable_conservative_executor.py",
)


class LookAheadCheckError(RuntimeError):
    """來源檔無法接受未來函數治理檢查。"""


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    column: int
    expression: str
    message: str

class LookAheadVisitor(ast.NodeVisitor):
    def __init__(self, path: str):
        self.path = path
        self.violations: list[Violation] = []
        self.loop_indices: dict[str, int] = {}

    def visit_For(self, node: ast.For):
        # 識別迴圈變數，例如 `for i, ... in enumerate(...)`
        index_var = None
        if isinstance(node.target, ast.Tuple) and len(node.target.elts) >= 1:
            first_elt = node.target.elts[0]
            if isinstance(first_elt, ast.Name):
                index_var = first_elt.id
        elif isinstance(node.target, ast.Name):
            index_var = node.target.id
            
        if index_var:
            self.loop_indices[index_var] = self.loop_indices.get(index_var, 0) + 1
            
        self.generic_visit(node)
        
        if index_var:
            remaining = self.loop_indices[index_var] - 1
            if remaining:
                self.loop_indices[index_var] = remaining
            else:
                del self.loop_indices[index_var]

    def visit_Subscript(self, node: ast.Subscript):
        self.generic_visit(node)
        
        # 判斷是否為 Slice 切片
        if isinstance(node.slice, ast.Slice):
            # 對於 Slice 的 lower 進行全面檢查
            if node.slice.lower:
                self._check_expression(node.slice.lower, node)
            # 對於 Slice 的 upper，允許剛好是 i + 1 (包含當前 i 元素)，但禁止 i + 2 或更高
            if node.slice.upper:
                self._check_expression(node.slice.upper, node, is_upper_bound=True)
            if node.slice.step:
                self._check_expression(node.slice.step, node)
        else:
            # 一般單一索引存取，禁止任何 + 1 / + 2
            self._check_expression(node.slice, node)

    def _check_expression(self, expr_node: ast.AST, parent_subscript: ast.Subscript, is_upper_bound: bool = False):
        for child in ast.walk(expr_node):
            if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Add):
                has_loop_idx = False
                idx_name = ""
                constant_val: int | float | None = None
                
                # 判斷是否為 `index + constant` 結構
                if isinstance(child.left, ast.Name) and child.left.id in self.loop_indices:
                    has_loop_idx = True
                    idx_name = child.left.id
                    if isinstance(child.right, ast.Constant) and isinstance(child.right.value, (int, float)):
                        constant_val = child.right.value
                elif isinstance(child.right, ast.Name) and child.right.id in self.loop_indices:
                    has_loop_idx = True
                    idx_name = child.right.id
                    if isinstance(child.left, ast.Constant) and isinstance(child.left.value, (int, float)):
                        constant_val = child.left.value

                if has_loop_idx:
                    # 如果是 Slice 的 upper bound 且加數剛好為 1，則是正常的 exclusive 包含當前元素，安全
                    if is_upper_bound and constant_val == 1:
                        continue
                    if constant_val is not None and constant_val <= 0:
                        continue
                    
                    expr_str = ast.unparse(parent_subscript) if hasattr(ast, "unparse") else "subscript"
                    self.violations.append(Violation(
                        path=self.path,
                        line=child.lineno,
                        column=child.col_offset + 1,
                        expression=expr_str,
                        message=(
                            f"偵測到在索引中對迴圈變數 '{idx_name}' 進行"
                            f"向前加法運算 (+{constant_val if constant_val is not None else 'dynamic'})，"
                            "可能引入未來函數 (Look-ahead bias)"
                        )
                    ))

def scan_source(source: str, *, path: str = "<memory>") -> list[Violation]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise LookAheadCheckError(f"{path}: 無法解析 Python: {exc.msg}") from exc

    visitor = LookAheadVisitor(path)
    visitor.visit(tree)
    return visitor.violations

def scan_paths(root: Path, paths: Sequence[str]) -> list[Violation]:
    violations: list[Violation] = []
    for relative_path in paths:
        source_path = root / relative_path
        if not source_path.is_file():
            raise LookAheadCheckError(f"{relative_path}: 管理檔案不存在")
        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise LookAheadCheckError(f"{relative_path}: 無法讀取: {exc}") from exc
        violations.extend(scan_source(source, path=relative_path))
    return sorted(
        violations,
        key=lambda item: (item.path, item.line, item.column),
    )

def main() -> int:
    if hasattr(sys.stdout, "reconfigure") and str(getattr(sys.stdout, "encoding", "")).lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    try:
        violations = scan_paths(REPO_ROOT, STRATEGY_FILES_TO_SCAN)
    except LookAheadCheckError as exc:
        print(f"LAB000 {exc}")
        return 1
    for violation in violations:
        print(f"{violation.path}:{violation.line}:{violation.column} LAB001 {violation.message} [{violation.expression}]")
    
    return 1 if violations else 0

if __name__ == "__main__":
    raise SystemExit(main())
