from __future__ import annotations

from pathlib import Path

import pytest

from data_module import ml_research_causal_ledger_overlay as overlay
from ml_module.allocation_contracts import AllocationWeightContract


def test_simulation_closes_sqlite_when_inner_step_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_path = tmp_path / "causal_ledger.sqlite"

    def _fail(**_: object) -> dict[str, object]:
        raise ValueError("poison")

    monkeypatch.setattr(
        overlay,
        "_simulate_ledger_open_connection",
        _fail,
    )

    with pytest.raises(ValueError, match="poison"):
        overlay._simulate_ledger(
            source_manifest_path=tmp_path / "manifest.json",
            source_manifest={"manifest_hash": "sha256:" + "0" * 64},
            ledger_path=ledger_path,
            request=overlay.ResearchCausalLedgerOverlayRequest(
                research_union_manifest_path=tmp_path / "manifest.json",
                output_root=tmp_path / "output",
            ),
            policy_hash="sha256:" + "1" * 64,
        )

    moved = tmp_path / "released.sqlite"
    ledger_path.replace(moved)
    assert moved.is_file()


def test_rebalance_does_not_create_ninth_position_when_small_exit_is_banded(
) -> None:
    current = AllocationWeightContract(
        positions_bp=tuple(
            [(f"{index:04d}", 800) for index in range(1, 8)]
            + [("0008", 200)]
        ),
        cash_bp=4_200,
    )
    desired = AllocationWeightContract(
        positions_bp=tuple(
            [(f"{index:04d}", 800) for index in range(1, 8)]
            + [("0009", 300)]
        ),
        cash_bp=4_100,
    )
    runtime = overlay._LedgerRuntime(
        state=None,
        week_key=None,
        price_history={},
        last_trade_index={},
        chain_hash="sha256:" + "2" * 64,
    )
    request = overlay.ResearchCausalLedgerOverlayRequest(
        research_union_manifest_path=Path("manifest.json"),
        output_root=Path("output"),
    )

    result, *_ = overlay._execute_rebalance(
        current=current,
        desired=desired,
        weekly_turnover_used_bp=0,
        runtime=runtime,
        request=request,
    )

    assert len(result.positions_bp) == 8
    assert dict(result.positions_bp).get("0009") is None
    assert result.cash_bp == 4_200

