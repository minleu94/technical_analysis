from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from ml_module import allocation_base_expert_comparison as comparison
from ml_module import allocation_confirmatory_runner as confirmatory_runner
from ml_module.allocation_confirmatory_runner import (
    ConfirmatoryBoundRequest,
    ConfirmatoryComparisonExecutionError,
    build_confirmatory_bound_request,
    run_authorized_confirmatory_read,
)
from ml_module.allocation_base_expert_comparison_freeze_gate import (
    ConfirmatoryFreezeGateError,
    _future_request_hash,
    _payload_hash,
    _policy_body,
    _request_body,
    authorize_confirmatory_scope,
)
from ml_module import allocation_oos_portfolio_replay as replay
from ml_module import allocation_oos_replay_input_builder as replay_input_builder
from ml_module import allocation_replay_causal_volume_sidecar as causal_volume_sidecar
from scripts.run_ml_allocation_confirmatory_comparison import _blocked


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, body: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _logical_manifest(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body)
    result["manifest_hash"] = _payload_hash(body)
    return result


def _build_receipt(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    source_root = tmp_path / "release_v4" / "runs" / "fixture-run"
    source_root.mkdir(parents=True)
    store_path = source_root / "store.json"
    store = _logical_manifest({"schema_version": "fixture-store.v3"})
    _write_json(store_path, store)
    store_hash = str(store["manifest_hash"])
    parent = _logical_manifest(
        {
            "schema_version": "fixture-parent.v5",
            "store_manifest_path": store_path.name,
            "store_manifest_hash": store_hash,
            "store_manifest_file_hash": _file_hash(store_path),
        }
    )
    parent_path = source_root / "parent.json"
    _write_json(parent_path, parent)
    parent_hash = str(parent["manifest_hash"])
    receipt: dict[str, Any] = {
        "schema_version": comparison.COMPARISON_SCHEMA_VERSION,
        "status": "complete_research",
        "fold_id": "fold-004",
        "horizon": 5,
        "algorithms": ["ridge_logistic"],
        "pack_ids": [
            "data_quality",
            "market_sector_cross_section",
            "price_liquidity_technical",
        ],
        "parent_training_manifest_path": str(parent_path),
        "parent_training_manifest_hash": parent_hash,
        "parent_store_manifest_hash": store_hash,
        "parent_store_manifest_file_hash": _file_hash(store_path),
        "selection_lineage": {
            "liquidity_pool_policy_version": comparison.LIQUIDITY_POOL_POLICY_VERSION,
            "lot_execution_policy_version": comparison.LOT_EXECUTION_POLICY_VERSION,
        },
        "execution_contract": {
            "complete_lot_execution": {
                "policy_version": comparison.LOT_EXECUTION_POLICY_VERSION,
            }
        },
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "research_only": True,
    }
    future_hash = _future_request_hash(
        method_version=comparison.METHOD_FREEZE_VERSION,
        pool_policy_version=comparison.LIQUIDITY_POOL_POLICY_VERSION,
        lot_policy_version=comparison.LOT_EXECUTION_POLICY_VERSION,
        volume_sidecar_policy_version=(
            comparison.CAUSAL_VOLUME_SIDECAR_POLICY_VERSION
        ),
    )
    receipt["future_confirmatory_scopes"] = [
        {
            "fold_id": "fold-005",
            "classification": "confirmatory_oos_pre_registered",
            "status": "registered_not_read",
            "request_hash": future_hash,
            "price_data_read": False,
            "label_data_read": False,
            "result_data_read": False,
            "requires_frozen_method_hash": True,
        }
    ]
    code_hashes = {
        "comparison_file_hash": _file_hash(Path(str(comparison.__file__))),
        "replay_input_builder_file_hash": _file_hash(
            Path(str(replay_input_builder.__file__))
        ),
        "replay_policy_owner_file_hash": _file_hash(Path(str(replay.__file__))),
        "causal_volume_sidecar_file_hash": _file_hash(
            Path(str(causal_volume_sidecar.__file__))
        ),
    }
    request_hash = _payload_hash(
        _request_body(receipt, parent_hash, store_hash)
    )
    policy_hash = _payload_hash(_policy_body(future_hash))
    parent_input_hashes = {
        "parent_training_manifest_hash": parent_hash,
        "parent_store_manifest_hash": store_hash,
    }
    receipt["method_freeze"] = {
        "method_freeze_version": comparison.METHOD_FREEZE_VERSION,
        "request_hash": request_hash,
        "policy_hash": policy_hash,
        "code_file_hashes": code_hashes,
        "parent_input_hashes": parent_input_hashes,
        "future_confirmatory_request_hashes": [future_hash],
        "method_freeze_hash": _payload_hash(
            {
                "method_freeze_version": comparison.METHOD_FREEZE_VERSION,
                "request_hash": request_hash,
                "policy_hash": policy_hash,
                "code_file_hashes": code_hashes,
                "parent_input_hashes": parent_input_hashes,
                "future_confirmatory_request_hashes": [future_hash],
            }
        ),
        "outcome_tuning": False,
    }
    receipt["comparison_hash"] = _payload_hash(receipt)
    receipt_path = tmp_path / "comparison.json"
    _write_json(receipt_path, receipt)
    return receipt_path, receipt


def test_gate_validates_published_receipt_without_future_source_reads(
    tmp_path: Path,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)

    gate = authorize_confirmatory_scope(receipt_path)

    assert gate.fold_id == "fold-005"
    assert gate.as_dict()["status"] == "validated_before_confirmatory_read"
    assert gate.as_dict()["price_data_read"] is False
    assert gate.as_dict()["label_data_read"] is False
    assert gate.as_dict()["result_data_read"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda body: body["method_freeze"]["code_file_hashes"].__setitem__(
                "replay_input_builder_file_hash", "sha256:" + "0" * 64
            ),
            "owner code hash changed",
        ),
        (
            lambda body: body["method_freeze"].__setitem__(
                "policy_hash", "sha256:" + "0" * 64
            ),
            "policy hash mismatch",
        ),
        (
            lambda body: body["method_freeze"]["parent_input_hashes"].__setitem__(
                "parent_store_manifest_hash", "sha256:" + "0" * 64
            ),
            "parent input hashes mismatch",
        ),
        (
            lambda body: body.__setitem__("fold_id", "fold-005"),
            "published receipt must be the frozen exploratory fold-004 receipt",
        ),
    ),
)
def test_gate_rejects_mutated_freeze_before_parent_source_read(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    receipt_path, original = _build_receipt(tmp_path)
    body = deepcopy(original)
    body["parent_training_manifest_path"] = str(tmp_path / "missing-parent.json")
    mutation(body)
    body["comparison_hash"] = _payload_hash(
        {key: value for key, value in body.items() if key != "comparison_hash"}
    )
    _write_json(receipt_path, body)

    with pytest.raises(ConfirmatoryFreezeGateError, match=message):
        authorize_confirmatory_scope(receipt_path)


def test_gate_rejects_unregistered_fold_before_reading_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "does-not-exist.json"

    with pytest.raises(ConfirmatoryFreezeGateError, match="only accepts"):
        authorize_confirmatory_scope(receipt_path, fold_id="fold-006")


def test_runner_binds_request_before_future_source_reader(
    tmp_path: Path,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)
    opened: list[tuple[str, str]] = []

    def reader(gate: Any, request: ConfirmatoryBoundRequest) -> dict[str, Any]:
        opened.append((gate.fold_id, request.fold_id))
        return request.as_dict()

    result = run_authorized_confirmatory_read(
        receipt_path,
        source_reader=reader,
    )

    assert opened == [("fold-005", "fold-005")]
    assert result["status"] == "registered_not_read"
    assert result["parent_training_manifest_hash"].startswith("sha256:")
    assert result["binding_hash"].startswith("sha256:")
    assert result["heavy_lock_path"] == str(
        (tmp_path / "release_v4" / ".ml_heavy_chain.lock").resolve()
    )


def test_runner_rejects_changed_bound_request_before_source_open(
    tmp_path: Path,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)
    gate = authorize_confirmatory_scope(receipt_path)
    bound = build_confirmatory_bound_request(gate)
    changed = replace(bound, pack_ids="unexpected-pack")
    opened = False

    def reader(_: Any, __: ConfirmatoryBoundRequest) -> None:
        nonlocal opened
        opened = True

    with pytest.raises(
        ConfirmatoryFreezeGateError,
        match="bound request does not match",
    ):
        run_authorized_confirmatory_read(
            receipt_path,
            request=changed,
            source_reader=reader,
        )
    assert opened is False


@pytest.mark.parametrize(
    "mutation",
    (
        lambda body: body["method_freeze"]["code_file_hashes"].__setitem__(
            "comparison_file_hash", "sha256:" + "0" * 64
        ),
        lambda body: body["method_freeze"]["parent_input_hashes"].__setitem__(
            "parent_training_manifest_hash", "sha256:" + "0" * 64
        ),
        lambda body: body["future_confirmatory_scopes"][0].__setitem__(
            "request_hash", "sha256:" + "0" * 64
        ),
    ),
)
def test_runner_rejects_hash_or_parent_mutation_before_source_open(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    receipt_path, original = _build_receipt(tmp_path)
    body = deepcopy(original)
    mutation(body)
    body["comparison_hash"] = _payload_hash(
        {key: value for key, value in body.items() if key != "comparison_hash"}
    )
    _write_json(receipt_path, body)
    opened = False

    def reader(_: Any, __: ConfirmatoryBoundRequest) -> None:
        nonlocal opened
        opened = True

    with pytest.raises(ConfirmatoryFreezeGateError):
        run_authorized_confirmatory_read(
            receipt_path,
            source_reader=reader,
        )
    assert opened is False


def test_confirmatory_comparison_runner_gates_engine_in_same_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_engine(**kwargs: Any) -> str:
        bound = kwargs["bound"]
        calls.append((bound.fold_id, bound.request_hash))
        return "engine-called-after-gate"

    monkeypatch.setattr(
        confirmatory_runner,
        "_execute_confirmatory_comparison",
        fake_engine,
    )
    result = confirmatory_runner.run_confirmatory_comparison(
        receipt_path,
        output_root=tmp_path / "confirmatory-output",
    )

    assert result == "engine-called-after-gate"
    assert len(calls) == 1
    assert calls[0][0] == "fold-005"
    assert calls[0][1].startswith("sha256:")


def test_confirmatory_comparison_preflight_never_calls_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)
    monkeypatch.setattr(
        confirmatory_runner,
        "_execute_confirmatory_comparison",
        lambda **_: pytest.fail("preflight must not open confirmatory source"),
    )

    result = confirmatory_runner.preflight_confirmatory_comparison(
        receipt_path,
        output_root=tmp_path / "confirmatory-preflight",
    )

    assert result["status"] == "preflight_passed_before_confirmatory_read"
    assert result["bound_request"]["fold_id"] == "fold-005"
    assert result["price_data_read"] is False


def test_confirmatory_source_failure_publishes_unknown_exposure_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)
    source_reader_called = False
    output_root = tmp_path.parent / f"{tmp_path.name}-confirmatory-output"

    monkeypatch.setattr(
        confirmatory_runner.comparison,
        "_capacity_preflight",
        lambda *_args, **_kwargs: {"status": "fixture_capacity_ok"},
    )
    monkeypatch.setattr(
        confirmatory_runner,
        "acquire_heavy_chain_reservation",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        confirmatory_runner,
        "release_heavy_chain_reservation",
        lambda _reservation: None,
    )

    def fail_after_source_phase_started(**_kwargs: Any) -> None:
        nonlocal source_reader_called
        source_reader_called = True
        raise RuntimeError("injected future source failure")

    monkeypatch.setattr(
        confirmatory_runner.comparison,
        "_build_comparison_payload",
        fail_after_source_phase_started,
    )

    with pytest.raises(ConfirmatoryComparisonExecutionError) as caught:
        confirmatory_runner.run_confirmatory_comparison(
            receipt_path,
            output_root=output_root,
        )

    assert source_reader_called is True
    error = caught.value
    assert error.exposure["status"] == "source_read_started_failed"
    assert error.exposure["source_read_attempted"] is True
    assert error.exposure["source_read_completed"] is False
    assert error.exposure["price_data_read"] is None
    assert error.exposure["label_data_read"] is None
    assert error.exposure["result_data_read"] is None
    assert error.exposure_receipt_path.is_file()
    saved = json.loads(error.exposure_receipt_path.read_text(encoding="utf-8"))
    assert saved == error.exposure
    cli_result = _blocked(error)
    assert cli_result["status"] == "blocked_after_confirmatory_source_phase"
    assert cli_result["price_data_read"] is None
    assert cli_result["label_data_read"] is None
    assert cli_result["result_data_read"] is None

    source_reader_called = False
    with pytest.raises(ConfirmatoryComparisonExecutionError, match="already exists"):
        confirmatory_runner.run_confirmatory_comparison(
            receipt_path,
            output_root=output_root,
        )
    assert source_reader_called is False

    with pytest.raises(
        ConfirmatoryComparisonExecutionError,
        match="output_root cannot be changed",
    ):
        confirmatory_runner.run_confirmatory_comparison(
            receipt_path,
            output_root=tmp_path.parent / f"{tmp_path.name}-different-output",
        )
    assert source_reader_called is False


def test_confirmatory_publish_failure_records_completed_source_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)
    output_root = tmp_path.parent / f"{tmp_path.name}-confirmatory-output"

    monkeypatch.setattr(
        confirmatory_runner.comparison,
        "_capacity_preflight",
        lambda *_args, **_kwargs: {"status": "fixture_capacity_ok"},
    )
    monkeypatch.setattr(
        confirmatory_runner,
        "acquire_heavy_chain_reservation",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        confirmatory_runner,
        "release_heavy_chain_reservation",
        lambda _reservation: None,
    )
    monkeypatch.setattr(
        confirmatory_runner.comparison,
        "_build_comparison_payload",
        lambda **_kwargs: {"schema_version": "fixture-payload.v1"},
    )
    monkeypatch.setattr(
        confirmatory_runner.comparison,
        "_publish_comparison",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected publication failure")
        ),
    )

    with pytest.raises(ConfirmatoryComparisonExecutionError) as caught:
        confirmatory_runner.run_confirmatory_comparison(
            receipt_path,
            output_root=output_root,
        )

    error = caught.value
    assert error.exposure["status"] == "source_read_completed_publish_failed"
    assert error.exposure["source_read_attempted"] is True
    assert error.exposure["source_read_completed"] is True
    assert error.exposure["price_data_read"] is True
    assert error.exposure["label_data_read"] is True
    assert error.exposure["result_data_read"] is True
    assert error.exposure_receipt_path.is_file()


def test_confirmatory_started_receipt_survives_base_exception_and_blocks_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path, _ = _build_receipt(tmp_path)
    output_root = tmp_path.parent / f"{tmp_path.name}-confirmatory-output"
    source_reader_called = False

    monkeypatch.setattr(
        confirmatory_runner.comparison,
        "_capacity_preflight",
        lambda *_args, **_kwargs: {"status": "fixture_capacity_ok"},
    )
    monkeypatch.setattr(
        confirmatory_runner,
        "acquire_heavy_chain_reservation",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        confirmatory_runner,
        "release_heavy_chain_reservation",
        lambda _reservation: None,
    )

    def terminate_after_source_open(**_kwargs: Any) -> None:
        nonlocal source_reader_called
        source_reader_called = True
        raise KeyboardInterrupt("simulated process interruption")

    monkeypatch.setattr(
        confirmatory_runner.comparison,
        "_build_comparison_payload",
        terminate_after_source_open,
    )

    with pytest.raises(KeyboardInterrupt):
        confirmatory_runner.run_confirmatory_comparison(
            receipt_path,
            output_root=output_root,
        )
    assert source_reader_called is True
    started_path = next(
        (output_root / "runs").rglob("confirmatory_exposure.json")
    )
    started = json.loads(started_path.read_text(encoding="utf-8"))
    assert started["status"] == "source_read_started"
    assert started["price_data_read"] is None

    source_reader_called = False
    with pytest.raises(ConfirmatoryComparisonExecutionError, match="already exists"):
        confirmatory_runner.run_confirmatory_comparison(
            receipt_path,
            output_root=output_root,
        )
    assert source_reader_called is False
