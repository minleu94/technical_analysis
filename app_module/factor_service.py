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

    def build_contributions(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        by_stock: dict[str, list[dict[str, Any]]] = {}
        summary_by_factor: dict[str, dict[str, int]] = {}

        for state, key in (
            ("accepted", "records"),
            ("neutralized", "neutralized"),
            ("skipped", "skipped"),
        ):
            for record in self._records_from_snapshot(snapshot, key):
                factor_name = str(record.get("factor_name", ""))
                stock_code = str(record.get("stock_code", ""))
                if not factor_name or not stock_code:
                    continue
                summary = self._summary_for(summary_by_factor, factor_name)
                summary[f"{state}_count"] += 1
                by_stock.setdefault(stock_code, []).append(
                    {
                        "factor_name": factor_name,
                        "state": state,
                        "score_bp": record.get("score_bp"),
                        "quality": record.get("quality"),
                    }
                )

        for diagnostic in self._records_from_snapshot(snapshot, "diagnostics"):
            factor_name = str(diagnostic.get("factor_name", ""))
            if factor_name:
                self._summary_for(summary_by_factor, factor_name)["diagnostic_count"] += 1

        return {
            "schema_version": 1,
            "factor_set_version": snapshot.get("factor_set_version", "factor-layer-v1"),
            "by_stock": by_stock,
            "summary_by_factor": summary_by_factor,
        }

    def _records_from_snapshot(self, snapshot: dict[str, Any], key: str) -> list[dict[str, Any]]:
        records = snapshot.get(key, [])
        if not isinstance(records, list):
            return []
        return [dict(item) for item in records if isinstance(item, dict)]

    def _summary_for(
        self,
        summary_by_factor: dict[str, dict[str, int]],
        factor_name: str,
    ) -> dict[str, int]:
        return summary_by_factor.setdefault(
            factor_name,
            {
                "accepted_count": 0,
                "neutralized_count": 0,
                "skipped_count": 0,
                "diagnostic_count": 0,
            },
        )
