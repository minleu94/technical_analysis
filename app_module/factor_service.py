"""Factor Layer application service。"""

from __future__ import annotations

from datetime import date
from typing import Any

from decision_module.factors.factor_dtos import FactorRecord
from decision_module.factors.factor_gate import FactorGate


class FactorService:
    """收集與序列化 factor snapshot，不修改 scoring 核心。"""

    def __init__(self, gate: FactorGate | None = None):
        self.gate = gate or FactorGate()

    def build_snapshot(
        self,
        records: list[FactorRecord],
        *,
        decision_date: date,
        factor_set_version: str = "factor-layer-v1",
    ) -> dict[str, Any]:
        gate_result = self.gate.validate_for_decision(
            records,
            decision_date=decision_date,
        )
        return {
            "schema_version": 1,
            "decision_date": decision_date.isoformat(),
            "factor_set_version": factor_set_version,
            "records": [record.to_dict() for record in gate_result.accepted],
            "neutralized": [record.to_dict() for record in gate_result.neutralized],
            "skipped": [record.to_dict() for record in gate_result.skipped],
            "diagnostics": [item.to_dict() for item in gate_result.diagnostics],
        }
