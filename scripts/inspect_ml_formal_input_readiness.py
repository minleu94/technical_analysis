"""唯讀檢查三項正式 ML input 是否已具備可消費 custody。

此工具只讀取受控環境變數、正式 loader 與 PIT sector sidecar discovery，
不會建立或修補 ledger、Rule history、sector mapping，也不會啟動 Direct/OOC。
即使三項 input 都 ready，輸出仍維持 formal_oos_allowed=false，必須由後續
immutable refresh、formal replay 與 promotion authority 重新簽發狀態。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.formal_portfolio_ledger import (  # noqa: E402
    load_formal_portfolio_state_ledger,
)
from data_module.rule_champion_snapshot_service import (  # noqa: E402
    load_verified_rule_champion_snapshot_history,
)
from scripts.continue_ml_direct_ooc_after_store import (  # noqa: E402
    _file_sha256,
    discover_valid_sector_membership,
)
from runtime import controlled_environment as _controlled_environment  # noqa: E402


PORTFOLIO_LEDGER_ENV = "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"
RULE_HISTORY_ENV = "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"
SECTOR_MEMBERSHIP_ENV = "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"
RULE_HMAC_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
RULE_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
READINESS_SCHEMA_VERSION = "ml-formal-input-readiness.v1"
_ATOMIC_REPLACE_RETRY_COUNT = 120
_ATOMIC_REPLACE_RETRY_DELAY_SECONDS = 0.5
_CONTROLLED_RUNTIME_ENVIRONMENT_NAMES = (
    PORTFOLIO_LEDGER_ENV,
    RULE_HISTORY_ENV,
    SECTOR_MEMBERSHIP_ENV,
    RULE_HMAC_KEY_ENV,
    RULE_STORE_ID_ENV,
)
_INITIAL_CONTROLLED_RUNTIME_ENVIRONMENT = {
    name: os.environ.get(name)
    for name in _CONTROLLED_RUNTIME_ENVIRONMENT_NAMES
}
_ADOPTED_CONTROLLED_RUNTIME_ENVIRONMENT: dict[str, str] = {}
winreg = _controlled_environment.winreg


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value.strip()


def _cutoff_date(training_as_of: str) -> date:
    parsed = datetime.fromisoformat(training_as_of.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("training_as_of must include timezone")
    return parsed.date()


def _environment_path(environment_name: str) -> Path | None:
    raw = os.environ.get(environment_name)
    if raw is None or not raw.strip():
        return None
    try:
        return Path(raw.strip()).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _refresh_controlled_runtime_environment() -> tuple[str, ...]:
    """Adopt late Windows owner deposits into this read-only process only."""

    return _controlled_environment.refresh_controlled_runtime_environment(
        environment=os.environ,
        initial_environment=_INITIAL_CONTROLLED_RUNTIME_ENVIRONMENT,
        adopted_environment=_ADOPTED_CONTROLLED_RUNTIME_ENVIRONMENT,
        names=_CONTROLLED_RUNTIME_ENVIRONMENT_NAMES,
        platform_name=os.name,
        registry=winreg,
    )


def _error_reason(error: Exception) -> dict[str, str]:
    detail = str(error).splitlines()[0].strip()
    if len(detail) > 240:
        detail = detail[:237] + "..."
    return {
        "reason": "validation_failed",
        "error_type": type(error).__name__,
        "detail": detail,
    }


def _missing_result(
    *,
    input_name: str,
    environment_name: str,
    reason: str,
    path: Path | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input": input_name,
        "state": "missing",
        "environment_variable": environment_name,
        "reason": reason,
    }
    if path is not None:
        result["path"] = str(path)
    return result


def _invalid_result(
    *,
    input_name: str,
    environment_name: str,
    path: Path,
    error: Exception,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input": input_name,
        "state": "invalid",
        "environment_variable": environment_name,
        "path": str(path),
    }
    result.update(_error_reason(error))
    return result


def _ledger_readiness(
    *,
    training_as_of: str,
) -> dict[str, Any]:
    path = _environment_path(PORTFOLIO_LEDGER_ENV)
    if path is None:
        return _missing_result(
            input_name="causal_non_cash_portfolio_ledger",
            environment_name=PORTFOLIO_LEDGER_ENV,
            reason="environment_variable_unset_or_invalid_path",
        )
    if not path.is_file():
        return _missing_result(
            input_name="causal_non_cash_portfolio_ledger",
            environment_name=PORTFOLIO_LEDGER_ENV,
            reason="configured_path_is_not_a_file",
            path=path,
        )
    try:
        ledger = load_formal_portfolio_state_ledger(path)
        cutoff = _cutoff_date(training_as_of)
        if any(
            date.fromisoformat(decision_date) > cutoff
            for decision_date in ledger.decision_dates
        ):
            raise ValueError("ledger contains decision dates after training_as_of")
        return {
            "input": "causal_non_cash_portfolio_ledger",
            "state": "ready",
            "environment_variable": PORTFOLIO_LEDGER_ENV,
            "path": str(path),
            "file_hash": _file_sha256(path),
            "manifest_hash": ledger.ledger_manifest_hash,
            "transition_chain_hash": ledger.transition_chain_hash,
            "decision_date_count": len(ledger.decision_dates),
            "non_cash_state_day_count": ledger.non_cash_state_day_count,
            "formal_consumer_compatible": True,
        }
    except Exception as error:
        return _invalid_result(
            input_name="causal_non_cash_portfolio_ledger",
            environment_name=PORTFOLIO_LEDGER_ENV,
            path=path,
            error=error,
        )


def _rule_history_readiness(
    *,
    training_as_of: str,
) -> dict[str, Any]:
    path = _environment_path(RULE_HISTORY_ENV)
    if path is None:
        return _missing_result(
            input_name="formal_rule_champion_snapshot_history",
            environment_name=RULE_HISTORY_ENV,
            reason="environment_variable_unset_or_invalid_path",
        )
    if not path.is_file():
        return _missing_result(
            input_name="formal_rule_champion_snapshot_history",
            environment_name=RULE_HISTORY_ENV,
            reason="configured_path_is_not_a_file",
            path=path,
        )
    try:
        history = load_verified_rule_champion_snapshot_history(
            path,
            training_as_of=training_as_of,
        )
        return {
            "input": "formal_rule_champion_snapshot_history",
            "state": "ready",
            "environment_variable": RULE_HISTORY_ENV,
            "path": str(path),
            "file_hash": history.manifest_file_hash,
            "manifest_hash": history.manifest_hash,
            "registered_store_id": history.registered_store_id,
            "decision_date_count": len(history.decision_dates),
            "snapshot_count": len(history.snapshots),
            "formal_consumer_compatible": True,
            "hmac_attestation_configured": True,
        }
    except Exception as error:
        return _invalid_result(
            input_name="formal_rule_champion_snapshot_history",
            environment_name=RULE_HISTORY_ENV,
            path=path,
            error=error,
        )


def _sector_readiness(
    *,
    output_root: Path,
    training_as_of: str,
) -> dict[str, Any]:
    configured = _environment_path(SECTOR_MEMBERSHIP_ENV)
    if configured is not None and not configured.is_file():
        return _missing_result(
            input_name="pit_sector_membership",
            environment_name=SECTOR_MEMBERSHIP_ENV,
            reason="configured_path_is_not_a_file",
            path=configured,
        )
    try:
        candidate = discover_valid_sector_membership(
            output_root=output_root,
            training_as_of=training_as_of,
        )
    except Exception as error:
        result = _invalid_result(
            input_name="pit_sector_membership",
            environment_name=SECTOR_MEMBERSHIP_ENV,
            path=configured or output_root,
            error=error,
        )
        result["candidate_discovery"] = "ambiguous_or_invalid"
        return result
    if candidate is None:
        return _missing_result(
            input_name="pit_sector_membership",
            environment_name=SECTOR_MEMBERSHIP_ENV,
            reason=(
                "no_validated_pit_sidecar_found_under_configured_path_or"
                "_operational_lineage"
            ),
            path=configured,
        )
    return {
        "input": "pit_sector_membership",
        "state": "ready",
        "environment_variable": SECTOR_MEMBERSHIP_ENV,
        "path": str(candidate),
        "file_hash": _file_sha256(candidate),
        "candidate_discovery": "validated_production_sidecar",
        "formal_consumer_compatible": True,
    }


def build_readiness_report(
    *,
    output_root: Path,
    training_as_of: str,
) -> dict[str, Any]:
    """建立不會解除 gate 的 formal input readiness report。"""

    resolved_root = output_root.resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(resolved_root)
    _cutoff_date(training_as_of)
    _refresh_controlled_runtime_environment()
    started_ns = time.monotonic_ns()
    results = [
        _ledger_readiness(training_as_of=training_as_of),
        _rule_history_readiness(training_as_of=training_as_of),
        _sector_readiness(
            output_root=resolved_root,
            training_as_of=training_as_of,
        ),
    ]
    all_ready = all(item.get("state") == "ready" for item in results)
    body: dict[str, Any] = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_root": str(resolved_root),
        "training_as_of": training_as_of,
        "status": "ready" if all_ready else "waiting_for_formal_inputs",
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "promotion_pass": False,
        "read_only": True,
        "inputs": results,
        "runtime_attestation": {
            "hmac_key_configured": bool(
                os.environ.get(RULE_HMAC_KEY_ENV, "").strip()
            ),
            "registered_store_id_configured": bool(
                os.environ.get(RULE_STORE_ID_ENV, "").strip()
            ),
            "secret_values_emitted": False,
        },
        "next_action": (
            "run supervised immutable Direct/OOC refresh, formal OOS replay, "
            "calibration and promotion evidence"
            if all_ready
            else "publish all three owner-controlled formal inputs; no partial "
            "retrain is permitted"
        ),
        "elapsed_validation_ms": (
            time.monotonic_ns() - started_ns
        ) // 1_000_000,
    }
    body["readiness_hash"] = _payload_hash(body)
    return body


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        for attempt in range(_ATOMIC_REPLACE_RETRY_COUNT):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_RETRY_COUNT:
                    raise
                time.sleep(_ATOMIC_REPLACE_RETRY_DELAY_SECONDS)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="唯讀檢查 formal ML input custody readiness。"
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = _build_parser().parse_args(argv)
    try:
        report = build_readiness_report(
            output_root=args.output_root,
            training_as_of=args.training_as_of,
        )
        _atomic_write_json(args.output.resolve(), report)
    except Exception as error:  # pragma: no cover - CLI fail-closed boundary
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "read_only": True,
                    "formal_oos_allowed": False,
                    "production_alpha_bp": 0,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "readiness_hash": report["readiness_hash"],
                "ready_inputs": sum(
                    item.get("state") == "ready"
                    for item in report["inputs"]
                ),
                "input_count": len(report["inputs"]),
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _configure_utf8_stdio() -> None:
    """讓直接執行腳本的 Windows 主控台也能顯示繁中說明與診斷。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 測試 capture stream 或外部 host 管理的 stream 可能禁止重設；
            # 這不應改變 readiness 結果。
            continue


if __name__ == "__main__":
    raise SystemExit(main())
