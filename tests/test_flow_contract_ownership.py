from dataclasses import asdict
import ast
from pathlib import Path


def test_removed_application_flow_dto_shims_are_not_importable() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "app_module" / "dtos" / "broker_flow_dtos.py").exists()
    assert not (root / "app_module" / "dtos" / "flow_signal_dtos.py").exists()


def test_flow_signal_engine_has_no_application_dto_dependency() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "decision_module"
        / "flow_signal_engine.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(module.startswith("app_module.dtos") for module in modules)


def test_flow_contract_payload_shape_remains_dataclass_compatible() -> None:
    from decision_module.flow_contracts import (
        BrokerFlowEvent,
        FlowSignalDTO,
        StockFlowAggregation,
    )

    event = BrokerFlowEvent("2026-07-10", "A", "分點", "2330", "台積電")
    aggregation = StockFlowAggregation("2330", "台積電", events=[event])
    signal = FlowSignalDTO("2330", "台積電", aggregation)

    payload = asdict(signal)

    assert payload["stock_code"] == "2330"
    assert payload["aggregation"]["events"][0]["branch_system_key"] == "A"
