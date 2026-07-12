import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_technical_indicator_kernel_does_not_import_decision_registry() -> None:
    source = ROOT / "analysis_module" / "technical_analysis" / "technical_indicators.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(module.startswith("decision_module") for module in imports)


def test_removed_decision_registry_shim_is_not_importable() -> None:
    assert not (ROOT / "decision_module" / "indicator_parameter_registry.py").exists()
