"""Static dependency and flag guard for the isolated ML shadow package."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


PRODUCTION_ROOTS = (
    "app_module",
    "decision_module",
    "portfolio_module",
    "ui_qt",
    "runtime",
    "backtest_module",
)
FORBIDDEN_ML_IMPORT_ROOTS = frozenset(PRODUCTION_ROOTS)
ALLOWED_READ_ONLY_PRODUCTION_ML_IMPORTS = {
    "app_module/ml_allocation_inference_service.py": frozenset(
        {
            "ml_module.allocation_contracts",
            "ml_module.allocation_training_service",
        }
    ),
    "app_module/ml_allocation_shadow_evidence.py": frozenset(
        {
            "ml_module.allocation_contracts",
            "ml_module.allocation_promotion_reference",
        }
    ),
    "app_module/portfolio_allocation_service.py": frozenset(
        {"ml_module.allocation_validation"}
    ),
    # Release adapter is the single, hash-verified application boundary for
    # optional shadow allocation inference.  It may import only the immutable
    # release and row contracts; production decisions remain fail-closed.
    "app_module/allocation_release_adapter.py": frozenset(
        {
            "ml_module.allocation_contracts",
            "ml_module.allocation_release_contract",
        }
    ),
}
FORBIDDEN_TRUE_FLAGS = frozenset(
    {
        "production_eligible",
        "production_action_allowed",
        "auto_promotion_allowed",
        "apply_promotion",
        "production_scheduler_allowed",
        "trading_allowed",
    }
)


@dataclass(frozen=True)
class MLShadowBoundaryReport:
    inspected_files: int
    violations: tuple[str, ...]
    shadow_only: bool = True


class MLShadowBoundaryGuard:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def inspect(self) -> MLShadowBoundaryReport:
        violations: list[str] = []
        inspected = 0
        ml_root = self.root / "ml_module"
        for path in sorted(ml_root.rglob("*.py")) if ml_root.exists() else ():
            inspected += 1
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            violations.extend(self._inspect_ml_tree(path, tree))
        for root_name in PRODUCTION_ROOTS:
            package_root = self.root / root_name
            if not package_root.exists():
                continue
            for path in sorted(package_root.rglob("*.py")):
                inspected += 1
                tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
                relative = path.relative_to(self.root).as_posix()
                allowed = ALLOWED_READ_ONLY_PRODUCTION_ML_IMPORTS.get(
                    relative,
                    frozenset(),
                )
                for module in _import_modules(tree):
                    if (
                        module == "ml_module"
                        or module.startswith("ml_module.")
                    ) and module not in allowed:
                        violations.append(f"production_imports_ml_module:{path.relative_to(self.root)}:{module}")
        return MLShadowBoundaryReport(inspected, tuple(sorted(violations)))

    def _inspect_ml_tree(self, path: Path, tree: ast.AST) -> tuple[str, ...]:
        violations: list[str] = []
        relative = path.relative_to(self.root)
        for module in _import_modules(tree):
            if module.split(".", 1)[0] in FORBIDDEN_ML_IMPORT_ROOTS:
                violations.append(f"ml_imports_production_path:{relative}:{module}")
        for node in ast.walk(tree):
            name: str | None = None
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            if name in FORBIDDEN_TRUE_FLAGS and isinstance(value, ast.Constant) and value.value is True:
                violations.append(f"forbidden_true_flag:{relative}:{name}")
        return tuple(violations)


def _import_modules(tree: ast.AST) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return tuple(modules)
