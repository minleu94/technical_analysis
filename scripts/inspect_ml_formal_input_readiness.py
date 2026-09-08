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
import re
import sys
import time
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


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
from data_module.pit_sector_membership_machine import (  # noqa: E402
    MachinePITSourceError,
    validate_machine_pit_receipt,
)
from data_module.pit_sector_machine_publisher import (  # noqa: E402
    consume_machine_pit_operational_candidate,
)
from runtime import controlled_environment as _controlled_environment  # noqa: E402


PORTFOLIO_LEDGER_ENV = "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH"
RULE_HISTORY_ENV = "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH"
SECTOR_MEMBERSHIP_ENV = "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH"
PIT_MACHINE_RECEIPT_ENV = (
    "BALDR_ML_PIT_SECTOR_MEMBERSHIP_MACHINE_RECEIPT_PATH"
)
PIT_MACHINE_PUBLICATION_ENV = (
    "BALDR_ML_PIT_SECTOR_MEMBERSHIP_MACHINE_PUBLICATION_PATH"
)
RULE_HMAC_KEY_ENV = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"
RULE_STORE_ID_ENV = "RULE_CHAMPION_CONTROLLED_STORE_ID"
READINESS_SCHEMA_VERSION = "ml-formal-input-readiness.v1"
_EXPECTED_SCHEMA_VERSION_BY_INPUT = {
    "causal_non_cash_portfolio_ledger": "causal-portfolio-ledger.v1",
    "formal_rule_champion_snapshot_history": (
        "rule-champion-snapshot-history.v1"
    ),
    "pit_sector_membership": "pit-sector-membership-sidecar-v1",
}
_PROSPECTIVE_LANE = "prospective_formal_simulation"
_PROSPECTIVE_READ_BYTES = 2_000_000
_PROSPECTIVE_HEADER_BYTES = 256 * 1024
_PROSPECTIVE_CLOCK_COMPONENT_RE = re.compile(
    r"^clock-(?P<date>\d{8})(?:-|$)",
    re.IGNORECASE,
)
_PROSPECTIVE_OUTPUT_ROOT_NAMES = ("formal_prospective", "prospective_formal")
_PROSPECTIVE_CLOCK_LIMIT = 24
_PROSPECTIVE_FORMAL_RELATIVE_PATHS = {
    "causal_non_cash_portfolio_ledger": Path(
        "portfolio_ledger/manifest.json"
    ),
    "formal_rule_champion_snapshot_history": Path(
        "rule_champion_history/manifest.json"
    ),
    "pit_sector_membership": Path(
        "pit_sector_membership/manifest.json"
    ),
}
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
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")


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
    # Formal ledger dates are Taiwan trading dates; preserve full timestamp
    # checks for Rule/PIT loaders while deriving this date-only cutoff locally.
    return _training_as_datetime(training_as_of).astimezone(_TAIPEI_TZ).date()


def _training_as_datetime(training_as_of: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(training_as_of.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("training_as_of must be valid ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("training_as_of must include timezone")
    return parsed.astimezone(timezone.utc)


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


def _path_looks_prospective(path: Path) -> bool:
    """僅由明確命名推測 deferred/prospective 路徑，避免把它當正式 input。"""

    parts = tuple(part.casefold() for part in path.parts)
    return any(
        part in {"formal_prospective", "prospective_formal"}
        or "prospective-formal" in part
        for part in parts
    )


def _inspect_prospective_output_roots(output_root: Path) -> dict[str, Any]:
    """觀察 prospective clock/staging，但絕不將其當成正式 input。

    Formal input readiness 必須遵守 owner 明確指定的 path；這個觀察只回答
    「同一 output root 是否有另一個 prospective artifact」的診斷問題，避免
    使用者看到 staging 檔案卻誤以為 validator 漏掃。它只讀取固定深度的
    `formal_prospective`／`prospective_formal` 直屬 `clock-*` 目錄名稱與少量
    marker path，不讀 rows、不做 schema validation，也不改變任何 input state。
    """

    candidates: list[dict[str, Any]] = []
    observed_roots: list[str] = []
    root = output_root.expanduser().resolve()
    for root_name in _PROSPECTIVE_OUTPUT_ROOT_NAMES:
        prospective_root = root / root_name
        try:
            if not prospective_root.is_dir():
                continue
            observed_roots.append(str(prospective_root))
            children = sorted(
                prospective_root.iterdir(),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            continue
        for child in children:
            if len(candidates) >= _PROSPECTIVE_CLOCK_LIMIT:
                break
            if not child.is_dir() or _PROSPECTIVE_CLOCK_COMPONENT_RE.match(
                child.name
            ) is None:
                continue
            clock_manifest = child / "clock" / "manifest.json"
            try:
                if not clock_manifest.is_file():
                    continue
                published_count = sum(
                    (child / relative_path).is_file()
                    for relative_path in _PROSPECTIVE_FORMAL_RELATIVE_PATHS.values()
                )
                staging_present = (child / "staging").is_dir()
                readiness_present = (child / "readiness").is_dir()
            except OSError:
                continue
            if not (published_count or staging_present or readiness_present):
                continue
            candidates.append(
                {
                    "clock_id": child.name,
                    "clock_manifest_path": str(clock_manifest),
                    "published_formal_input_count": published_count,
                    "staging_present": staging_present,
                    "readiness_present": readiness_present,
                    "lane": _PROSPECTIVE_LANE,
                    "formal_consumer_compatible": False,
                    "authority": "diagnostic_only",
                }
            )
    candidates.sort(key=lambda item: str(item["clock_id"]).casefold())
    if not candidates:
        status = "none_observed"
    elif len(candidates) >= _PROSPECTIVE_CLOCK_LIMIT:
        status = "observed_truncated"
    else:
        status = "staging_or_prospective_observed"
    return {
        "status": status,
        "observed_roots": observed_roots,
        "candidate_clock_count": len(candidates),
        "candidate_clocks": candidates,
        "diagnostic": (
            "prospective artifacts are diagnostic-only; they never replace the "
            "explicit owner-controlled BALDR_ML_FORMAL_* paths"
        ),
    }


def _prospective_manifest_hint(path: Path) -> dict[str, str] | None:
    """以 bounded read 偵測 prospective wrapper，不載入 rows 或秘密值。"""

    try:
        size = path.stat().st_size
        if size > _PROSPECTIVE_READ_BYTES:
            raw = path.read_bytes()[:_PROSPECTIVE_HEADER_BYTES]
            payload: object | None = None
        else:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
    except (
        OSError,
        UnicodeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return None

    candidates: list[Mapping[str, object]] = []
    if isinstance(payload, Mapping):
        candidates.append(payload)
        for key in ("manifest", "metadata"):
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                candidates.append(nested)

    def _hint(
        *,
        schema: object,
        mode: object,
        scope: object,
    ) -> dict[str, str] | None:
        schema_text = schema.strip() if isinstance(schema, str) else ""
        mode_text = mode.strip() if isinstance(mode, str) else ""
        scope_text = scope.strip() if isinstance(scope, str) else ""
        if not (
            schema_text.startswith("prospective-formal-")
            or "-prospective-" in schema_text
            or mode_text == _PROSPECTIVE_LANE
            or scope_text == "prospective_only"
        ):
            return None
        result = {"lane": _PROSPECTIVE_LANE}
        if schema_text:
            result["schema_version"] = schema_text
        if mode_text:
            result["consumer_mode"] = mode_text
        if scope_text:
            result["scope"] = scope_text
        return result

    for candidate in candidates:
        result = _hint(
            schema=candidate.get("schema_version"),
            mode=candidate.get("consumer_mode", candidate.get("mode")),
            scope=candidate.get("scope"),
        )
        if result is not None:
            return result

    # Large PIT envelopes put rows after the manifest.  Regex is restricted to
    # known marker fields and never returns arbitrary payload text.
    schema_match = re.search(
        rb'"schema_version"\s*:\s*"([^"]+)"',
        raw,
    )
    mode_match = re.search(
        rb'"(?:consumer_mode|mode)"\s*:\s*"([^"]+)"',
        raw,
    )
    scope_match = re.search(
        rb'"scope"\s*:\s*"([^"]+)"',
        raw,
    )
    return _hint(
        schema=(
            schema_match.group(1).decode("utf-8", errors="replace")
            if schema_match
            else ""
        ),
        mode=(
            mode_match.group(1).decode("utf-8", errors="replace")
            if mode_match
            else ""
        ),
        scope=(
            scope_match.group(1).decode("utf-8", errors="replace")
            if scope_match
            else ""
        ),
    )


def _prospective_invalid_result(
    *,
    input_name: str,
    environment_name: str,
    path: Path,
    hint: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "input": input_name,
        "state": "invalid",
        "environment_variable": environment_name,
        "path": str(path),
        "expected_schema_version": _EXPECTED_SCHEMA_VERSION_BY_INPUT[
            input_name
        ],
        "reason": "prospective_manifest_requires_formal_consumer_publication",
        "source_lane": _PROSPECTIVE_LANE,
        "prospective_manifest": dict(hint),
        "formal_consumer_compatible": False,
    }


def _missing_result(
    *,
    input_name: str,
    environment_name: str,
    reason: str,
    path: Path | None = None,
    training_as_of: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "input": input_name,
        "state": "missing",
        "environment_variable": environment_name,
        "reason": reason,
        "expected_schema_version": _EXPECTED_SCHEMA_VERSION_BY_INPUT[
            input_name
        ],
    }
    if path is not None:
        result["path"] = str(path)
        if _path_looks_prospective(path):
            result["reason"] = "prospective_output_not_published"
            result["source_lane"] = _PROSPECTIVE_LANE
            result["formal_consumer_compatible"] = False
            _add_prospective_clock_hint(
                result,
                path=path,
                training_as_of=training_as_of,
            )
    return result


def _add_prospective_clock_hint(
    result: dict[str, Any],
    *,
    path: Path,
    training_as_of: str | None,
) -> None:
    """Expose an explicit stale-clock hint without discovering replacement paths."""

    if training_as_of is None:
        return
    clock_component = next(
        (
            part
            for part in reversed(path.parts)
            if _PROSPECTIVE_CLOCK_COMPONENT_RE.match(part)
        ),
        None,
    )
    if clock_component is None:
        return
    match = _PROSPECTIVE_CLOCK_COMPONENT_RE.match(clock_component)
    if match is None:  # pragma: no cover - guarded by the comprehension
        return
    try:
        clock_date = datetime.strptime(
            match.group("date"),
            "%Y%m%d",
        ).date()
        cutoff_date = _cutoff_date(training_as_of)
    except (TypeError, ValueError):
        return
    result["configured_clock_id"] = clock_component
    result["configured_clock_date"] = clock_date.isoformat()
    result["training_as_of_date"] = cutoff_date.isoformat()
    result["configured_clock_date_before_training_as_of"] = (
        clock_date < cutoff_date
    )
    if clock_date < cutoff_date:
        result["diagnostic"] = (
            "configured prospective clock is older than training_as_of; "
            "publish the current owner-controlled clock output and update the "
            "explicit path, without automatic path discovery"
        )


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
        "expected_schema_version": _EXPECTED_SCHEMA_VERSION_BY_INPUT[
            input_name
        ],
        "formal_consumer_compatible": False,
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
            training_as_of=training_as_of,
        )
    prospective_hint = _prospective_manifest_hint(path)
    if prospective_hint is not None:
        return _prospective_invalid_result(
            input_name="causal_non_cash_portfolio_ledger",
            environment_name=PORTFOLIO_LEDGER_ENV,
            path=path,
            hint=prospective_hint,
        )
    try:
        ledger = load_formal_portfolio_state_ledger(path)
        cutoff = _cutoff_date(training_as_of)
        if any(
            date.fromisoformat(decision_date) >= cutoff
            for decision_date in ledger.decision_dates
        ):
            raise ValueError(
                "ledger date-only transition requires a later Taiwan calendar-day "
                "training_as_of; intraday same-day availability is unproven"
            )
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
            "cutoff_semantics": "taipei_calendar_date_after_date_only_transition",
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
            training_as_of=training_as_of,
        )
    prospective_hint = _prospective_manifest_hint(path)
    if prospective_hint is not None:
        return _prospective_invalid_result(
            input_name="formal_rule_champion_snapshot_history",
            environment_name=RULE_HISTORY_ENV,
            path=path,
            hint=prospective_hint,
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
        machine_publication = _environment_path(PIT_MACHINE_PUBLICATION_ENV)
        if machine_publication is not None:
            machine_result = _machine_pit_publication_readiness(
                machine_publication,
                decision_at=_training_as_datetime(training_as_of),
            )
            if machine_result is not None:
                return machine_result
        machine_receipt = _environment_path(PIT_MACHINE_RECEIPT_ENV)
        if machine_receipt is not None:
            machine_result = _machine_pit_receipt_readiness(
                machine_receipt,
                decision_at=_training_as_datetime(training_as_of),
            )
            if machine_result is not None:
                return machine_result
        return _missing_result(
            input_name="pit_sector_membership",
            environment_name=SECTOR_MEMBERSHIP_ENV,
            reason="configured_path_is_not_a_file",
            path=configured,
            training_as_of=training_as_of,
        )
    if configured is not None:
        prospective_hint = _prospective_manifest_hint(configured)
        if prospective_hint is not None:
            return _prospective_invalid_result(
                input_name="pit_sector_membership",
                environment_name=SECTOR_MEMBERSHIP_ENV,
                path=configured,
                hint=prospective_hint,
            )
    if configured is None:
        machine_publication = _environment_path(PIT_MACHINE_PUBLICATION_ENV)
        if machine_publication is not None:
            machine_result = _machine_pit_publication_readiness(
                machine_publication,
                decision_at=_training_as_datetime(training_as_of),
            )
            if machine_result is not None:
                return machine_result
        machine_receipt = _environment_path(PIT_MACHINE_RECEIPT_ENV)
        if machine_receipt is not None:
            machine_result = _machine_pit_receipt_readiness(
                machine_receipt,
                decision_at=_training_as_datetime(training_as_of),
            )
            if machine_result is not None:
                return machine_result
    try:
        candidate = discover_valid_sector_membership(
            output_root=output_root,
            training_as_of=training_as_of,
            **(
                {"expected_file_hash": _file_sha256(configured)}
                if configured is not None
                else {}
            ),
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
            training_as_of=training_as_of,
        )
    if configured is not None and candidate.resolve() != configured.resolve():
        result = _invalid_result(
            input_name="pit_sector_membership",
            environment_name=SECTOR_MEMBERSHIP_ENV,
            path=configured,
            error=ValueError(
                "configured PIT sector path was not the validated candidate"
            ),
        )
        result["candidate_discovery"] = "configured_path_not_authoritative"
        return result
    prospective_hint = _prospective_manifest_hint(candidate)
    if prospective_hint is not None:
        return _prospective_invalid_result(
            input_name="pit_sector_membership",
            environment_name=SECTOR_MEMBERSHIP_ENV,
            path=candidate,
            hint=prospective_hint,
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


def _machine_pit_publication_readiness(
    publication_path: Path,
    *,
    decision_at: datetime,
) -> dict[str, Any] | None:
    """把受控 machine operational publication 投影為 candidate 狀態。"""

    if not publication_path.is_file():
        return _missing_result(
            input_name="pit_sector_membership",
            environment_name=PIT_MACHINE_PUBLICATION_ENV,
            reason="machine_publication_configured_path_is_not_a_file",
            path=publication_path,
        )
    try:
        consumed = consume_machine_pit_operational_candidate(
            publication_path,
            decision_at=decision_at,
        )
    except (MachinePITSourceError, OSError, TypeError, ValueError) as error:
        return _invalid_result(
            input_name="pit_sector_membership",
            environment_name=PIT_MACHINE_PUBLICATION_ENV,
            path=publication_path,
            error=error,
        )
    raw_receipt = consumed.get("receipt")
    receipt = raw_receipt if isinstance(raw_receipt, Mapping) else {}
    source_ids = consumed.get("source_ids")
    if not isinstance(source_ids, list):
        return _invalid_result(
            input_name="pit_sector_membership",
            environment_name=PIT_MACHINE_PUBLICATION_ENV,
            path=publication_path,
            error=ValueError("machine operational publication source_ids are invalid"),
        )
    return {
        "input": "pit_sector_membership",
        "state": "machine_verified",
        "environment_variable": PIT_MACHINE_PUBLICATION_ENV,
        "path": str(publication_path),
        "file_hash": str(consumed.get("operational_file_hash") or ""),
        "receipt_path": str(receipt.get("receipt_path") or ""),
        "publication_file_hash": str(
            receipt.get("publication_file_hash") or ""
        ),
        "capture_id": str(consumed.get("capture_id") or ""),
        "captured_at": str(consumed.get("available_at") or ""),
        "decision_at": str(consumed.get("consumer_decision_at") or ""),
        "effective_from": str(consumed.get("effective_from") or ""),
        "row_count": consumed.get("row_count"),
        "source_ids": list(source_ids),
        "publisher_id": str(consumed.get("publisher_id") or ""),
        "publisher_code_sha256": str(consumed.get("publisher_code_sha256") or ""),
        "machine_verified": True,
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "source_custody_verified": consumed.get("source_custody_verified") is True,
        "rows_rebuilt_from_raw": consumed.get("rows_rebuilt_from_raw") is True,
        "reason": "machine_verified_candidate_formal_owner_publication_pending",
    }


def _machine_pit_receipt_readiness(
    receipt_path: Path,
    *,
    decision_at: datetime,
) -> dict[str, Any] | None:
    """把明確指定的 PIT receipt 投影為 machine candidate 狀態。

    receipt 是可重驗的 machine evidence，但沒有 owner-controlled formal
    publication。因此它不計入 ``ready_input_count``，也不會解除 Formal OOS。
    """

    if not receipt_path.is_file():
        return _missing_result(
            input_name="pit_sector_membership",
            environment_name=PIT_MACHINE_RECEIPT_ENV,
            reason="machine_receipt_configured_path_is_not_a_file",
            path=receipt_path,
        )
    try:
        receipt = validate_machine_pit_receipt(
            receipt_path,
            now=decision_at,
        )
    except (MachinePITSourceError, OSError, TypeError, ValueError) as error:
        return _invalid_result(
            input_name="pit_sector_membership",
            environment_name=PIT_MACHINE_RECEIPT_ENV,
            path=receipt_path,
            error=error,
        )
    source_ids = receipt.get("source_ids")
    if not isinstance(source_ids, list):
        return _invalid_result(
            input_name="pit_sector_membership",
            environment_name=PIT_MACHINE_RECEIPT_ENV,
            path=receipt_path,
            error=ValueError("machine PIT receipt source_ids are invalid"),
        )
    return {
        "input": "pit_sector_membership",
        "state": "machine_verified",
        "environment_variable": PIT_MACHINE_RECEIPT_ENV,
        "path": str(receipt_path),
        "file_hash": str(receipt.get("receipt_file_hash") or ""),
        "publication_file_hash": str(
            receipt.get("publication_file_hash") or ""
        ),
        "publication_content_hash": str(
            receipt.get("publication_content_hash") or ""
        ),
        "capture_id": str(receipt.get("capture_id") or ""),
        "captured_at": str(receipt.get("captured_at") or ""),
        "decision_at": decision_at.isoformat(),
        "effective_from": str(receipt.get("effective_from") or ""),
        "row_count": receipt.get("row_count"),
        "source_ids": list(source_ids),
        "machine_verified": True,
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "candidate_only": True,
        "source_custody_verified": receipt.get("source_custody_verified") is True,
        "rows_rebuilt_from_raw": receipt.get("rows_rebuilt_from_raw") is True,
        "reason": "machine_verified_candidate_formal_owner_publication_pending",
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
    ready_input_count = sum(item.get("state") == "ready" for item in results)
    machine_verified_input_count = sum(
        item.get("state") == "machine_verified" for item in results
    )
    input_count = len(results)
    state_counts = {
        state: sum(item.get("state") == state for item in results)
        for state in ("missing", "unknown", "invalid", "ready")
    }
    formal_consumer_compatible_count = sum(
        item.get("state") == "ready"
        and item.get("formal_consumer_compatible") is True
        for item in results
    )
    all_ready = ready_input_count == input_count
    prospective_observation = _inspect_prospective_output_roots(resolved_root)
    body: dict[str, Any] = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_root": str(resolved_root),
        "training_as_of": training_as_of,
        "status": "ready" if all_ready else "waiting_for_formal_inputs",
        "ready_input_count": ready_input_count,
        "machine_verified_input_count": machine_verified_input_count,
        "machine_candidate_input_count": machine_verified_input_count,
        "formal_consumer_compatible_count": formal_consumer_compatible_count,
        "missing_input_count": state_counts["missing"],
        "unknown_input_count": state_counts["unknown"],
        "invalid_input_count": state_counts["invalid"],
        "input_count": input_count,
        "ready_input_ratio": f"{ready_input_count}/{input_count}",
        "formal_oos_allowed": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "promotion_pass": False,
        "read_only": True,
        "inputs": results,
        "prospective_output_observation": prospective_observation,
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
                "ready_inputs": report["ready_input_count"],
                "input_count": report["input_count"],
                "ready_input_ratio": report["ready_input_ratio"],
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
