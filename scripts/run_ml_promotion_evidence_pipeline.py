"""每日建立配置型 ML Promotion Evidence 的 fail-closed 管線。

此 runner 只做固定 custody discovery、雜湊重驗與 unsigned evidence
publication；它不簽章、不選正式 alpha、不改寫模型／來源資料庫，也不具券商
送單權限。任何 formal OOC、雙 replay、Shadow 或 calibration/drift 證據缺件時，
只寫入 machine-readable blocked status，既有 compatible pointer 不會被覆寫。
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.official_trading_calendar import (  # noqa: E402
    OfficialTradingCalendar,
)
from ml_module.allocation_promotion_evidence_builder import (  # noqa: E402
    AllocationPromotionEvidenceBuildRequest,
    build_compatible_allocation_promotion_evidence,
)
from ml_module.allocation_oos_portfolio_replay import (  # noqa: E402
    AllocationOOSPortfolioReplayRequest,
    build_allocation_oos_portfolio_replay,
)


TAIPEI = ZoneInfo("Asia/Taipei")
TASK_NAME = "baldr-ml-promotion-evidence-daily"
STATUS_SCHEMA_VERSION = "ml-promotion-evidence-pipeline-status.v1"
TRAINING_POINTER_SCHEMA_VERSION = "allocation-ooc-training-latest.v1"
TRAINING_SCHEMA_VERSION = "allocation-ooc-training.v5"
STORE_SCHEMA_VERSION = "portfolio-ml-ooc-store.v3"
REPLAY_POINTER_SCHEMA_VERSION = (
    "allocation-ooc-portfolio-replay-pointer.v1"
)
REPLAY_SCHEMA_VERSION = "allocation-ooc-portfolio-replay.v1"
REFERENCE_POINTER_SCHEMA_VERSION = (
    "ml-allocation-promotion-reference-pointer-v1"
)
REFERENCE_METRICS_POINTER_SCHEMA_VERSION = (
    "ml-allocation-reference-metrics-pointer-v1"
)


class _Calendar(Protocol):
    def is_official_trading_day(
        self,
        target_date: date,
    ) -> tuple[bool | None, str]:
        ...


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_mapping(path: Path, *, label: str) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{label} must be a JSON object")
    return payload


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be non-empty text")
    return value.strip()


def _sha256(value: object, *, label: str) -> str:
    result = _text(value, label=label)
    if len(result) != 71 or not result.startswith("sha256:"):
        raise ValueError(f"{label} must be a sha256 hash")
    int(result[7:], 16)
    return result


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
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
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _trusted_file(
    value: object,
    *,
    root: Path,
    label: str,
) -> Path:
    path = Path(_text(value, label=label)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"{label} escapes its fixed custody root")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing")
    return path


def _resolve_relative_file(
    *,
    base: Path,
    value: object,
    root: Path,
    label: str,
) -> Path:
    path = (base / _text(value, label=label)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"{label} escapes its fixed custody root")
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing")
    return path


def _verify_logical_hash(
    payload: Mapping[str, object],
    *,
    field_name: str,
    label: str,
) -> str:
    expected = _sha256(payload.get(field_name), label=f"{label}.{field_name}")
    body = dict(payload)
    body.pop(field_name, None)
    if _payload_hash(body) != expected:
        raise ValueError(f"{label} logical hash mismatch")
    return expected


def _next_official_decision(
    *,
    now: datetime,
    calendar: _Calendar,
) -> tuple[datetime, str]:
    local_now = now.astimezone(TAIPEI)
    for offset in range(15):
        candidate_date = local_now.date() + timedelta(days=offset)
        candidate = datetime.combine(
            candidate_date,
            time(8, 30),
            tzinfo=TAIPEI,
        )
        if candidate <= local_now:
            continue
        is_open, reason = calendar.is_official_trading_day(candidate_date)
        if is_open is None:
            raise RuntimeError(
                "decision_calendar_unknown:"
                f"{candidate_date.isoformat()}:{reason}"
            )
        if is_open:
            return candidate, reason
    raise RuntimeError("next_official_decision_not_found_within_15_days")


def _strict_previous_trading_day(
    *,
    decision_date: date,
    calendar: _Calendar,
) -> tuple[date, str]:
    for offset in range(1, 32):
        candidate = decision_date - timedelta(days=offset)
        is_open, reason = calendar.is_official_trading_day(candidate)
        if is_open is None:
            raise RuntimeError(
                "strict_t_minus_one_calendar_unknown:"
                f"{candidate.isoformat()}:{reason}"
            )
        if is_open:
            return candidate, reason
    raise RuntimeError("strict_t_minus_one_not_found_within_31_days")


def _discover_training_and_store(
    *,
    release_root: Path,
) -> tuple[Path, Path, str]:
    training_root = (
        release_root
        / "portfolio_ml_direct_ooc_training_production_v4_v5"
    )
    pointer_path = training_root / "latest_manifest.json"
    pointer = _read_mapping(pointer_path, label="OOC training pointer")
    if pointer.get("schema_version") != TRAINING_POINTER_SCHEMA_VERSION:
        raise ValueError("OOC training pointer schema mismatch")
    manifest_path = _resolve_relative_file(
        base=training_root,
        value=pointer.get("manifest_path"),
        root=training_root,
        label="OOC training manifest_path",
    )
    manifest = _read_mapping(manifest_path, label="OOC training manifest")
    if (
        manifest.get("schema_version") != TRAINING_SCHEMA_VERSION
        or manifest.get("status") != "complete"
        or manifest.get("formal_source_only") is not True
        or manifest.get("research_shadow_included") is not False
    ):
        raise ValueError("OOC training is not a complete formal v5 run")
    logical_hash = _verify_logical_hash(
        manifest,
        field_name="manifest_hash",
        label="OOC training manifest",
    )
    if pointer.get("manifest_hash") != logical_hash:
        raise ValueError("OOC training pointer hash mismatch")

    store_path = _resolve_relative_file(
        base=manifest_path.parent,
        value=manifest.get("store_manifest_path"),
        root=release_root,
        label="OOC store manifest_path",
    )
    expected_store_file_hash = _sha256(
        manifest.get("store_manifest_file_hash"),
        label="OOC training store_manifest_file_hash",
    )
    if _file_hash(store_path) != expected_store_file_hash:
        raise ValueError("OOC store manifest physical hash mismatch")
    store = _read_mapping(store_path, label="OOC store manifest")
    if store.get("schema_version") != STORE_SCHEMA_VERSION:
        raise ValueError("OOC store schema mismatch")
    _verify_logical_hash(
        store,
        field_name="manifest_hash",
        label="OOC store manifest",
    )
    return (
        manifest_path,
        store_path,
        _text(manifest.get("run_id"), label="OOC training run_id"),
    )


def _discover_replay(
    *,
    release_root: Path,
    lane: str,
) -> tuple[Path, str, str]:
    replay_root = (
        release_root
        / "ml_allocation_oos_replay_production_v4"
        / lane
    )
    pointer = _read_mapping(
        replay_root / "latest_replay.json",
        label=f"{lane} replay pointer",
    )
    if (
        pointer.get("schema_version") != REPLAY_POINTER_SCHEMA_VERSION
        or pointer.get("status") != "complete"
    ):
        raise ValueError(f"{lane} replay pointer is not complete")
    replay_path = _trusted_file(
        pointer.get("replay_path"),
        root=replay_root,
        label=f"{lane} replay_path",
    )
    expected_file_hash = _sha256(
        pointer.get("replay_file_hash"),
        label=f"{lane} replay_file_hash",
    )
    if _file_hash(replay_path) != expected_file_hash:
        raise ValueError(f"{lane} replay physical hash mismatch")
    replay = _read_mapping(replay_path, label=f"{lane} replay")
    if (
        replay.get("schema_version") != REPLAY_SCHEMA_VERSION
        or replay.get("status") != "complete"
    ):
        raise ValueError(f"{lane} replay is not a complete formal replay")
    result_hash = _sha256(
        replay.get("replay_result_hash"),
        label=f"{lane} replay_result_hash",
    )
    if pointer.get("replay_result_hash") != result_hash:
        raise ValueError(f"{lane} replay result hash pointer mismatch")
    run_id = _text(
        replay.get("replay_run_id"),
        label=f"{lane} replay_run_id",
    )
    if pointer.get("replay_run_id") != run_id:
        raise ValueError(f"{lane} replay run id pointer mismatch")
    return replay_path, result_hash, run_id


def _build_replays(
    *,
    release_root: Path,
    training_manifest_path: Path,
    decision_at: datetime,
) -> None:
    """建立兩次獨立 replay；primary blocked 時不製造 verification 外觀。"""

    training_file_hash = _file_hash(training_manifest_path)
    identity = (
        f"{training_file_hash[7:23]}-{decision_at.strftime('%Y%m%d')}"
    )
    replay_root = (
        release_root / "ml_allocation_oos_replay_production_v4"
    )
    primary = build_allocation_oos_portfolio_replay(
        AllocationOOSPortfolioReplayRequest(
            training_manifest_path=training_manifest_path,
            output_root=replay_root,
            replay_run_id=f"primary-{identity}",
            role="primary",
            replay_as_of=decision_at,
        )
    )
    if primary.status != "complete":
        raise RuntimeError(
            "formal_oos_primary_replay_blocked:"
            + ",".join(primary.blockers)
        )
    verification = build_allocation_oos_portfolio_replay(
        AllocationOOSPortfolioReplayRequest(
            training_manifest_path=training_manifest_path,
            output_root=replay_root,
            replay_run_id=f"verification-{identity}",
            role="verification",
            replay_as_of=decision_at,
        )
    )
    if verification.status != "complete":
        raise RuntimeError(
            "formal_oos_verification_replay_blocked:"
            + ",".join(verification.blockers)
        )
    if primary.replay_result_hash != verification.replay_result_hash:
        raise RuntimeError(
            "formal_oos_replay_independent_result_hash_mismatch"
        )


def _discover_reference(
    *,
    release_root: Path,
) -> tuple[Path, str]:
    reference_root = release_root / "ml_promotion_reference_v4"
    pointer = _read_mapping(
        reference_root / "latest_reference.json",
        label="promotion reference pointer",
    )
    if pointer.get("schema_version") != REFERENCE_POINTER_SCHEMA_VERSION:
        raise ValueError("promotion reference pointer schema mismatch")
    reference_path = _trusted_file(
        pointer.get("reference_path"),
        root=reference_root,
        label="promotion reference_path",
    )
    expected_file_hash = _sha256(
        pointer.get("reference_file_hash"),
        label="promotion reference_file_hash",
    )
    if _file_hash(reference_path) != expected_file_hash:
        raise ValueError("promotion reference physical hash mismatch")
    return reference_path, expected_file_hash


def _discover_reference_metrics(
    *,
    output_root: Path,
) -> Path:
    collector_root = (
        output_root
        / "scheduled"
        / "ml_allocation_copilot"
        / "shadow_evidence_collector"
    )
    pointer = _read_mapping(
        collector_root / "latest_reference_metrics.json",
        label="reference metrics pointer",
    )
    if (
        pointer.get("schema_version")
        != REFERENCE_METRICS_POINTER_SCHEMA_VERSION
    ):
        raise ValueError("reference metrics pointer schema mismatch")
    metrics_path = _trusted_file(
        pointer.get("reference_metrics_path"),
        root=collector_root,
        label="reference_metrics_path",
    )
    expected_file_hash = _sha256(
        pointer.get("reference_metrics_file_hash"),
        label="reference_metrics_file_hash",
    )
    if _file_hash(metrics_path) != expected_file_hash:
        raise ValueError("reference metrics physical hash mismatch")
    metrics = _read_mapping(metrics_path, label="reference metrics")
    metrics_hash = _verify_logical_hash(
        metrics,
        field_name="metrics_hash",
        label="reference metrics",
    )
    if pointer.get("reference_metrics_hash") != metrics_hash:
        raise ValueError("reference metrics pointer logical hash mismatch")
    for field_name in (
        "outcome_contract_version",
        "outcome_contract_hash",
    ):
        if pointer.get(field_name) != metrics.get(field_name):
            raise ValueError(
                f"reference metrics pointer {field_name} mismatch"
            )
    return metrics_path


def _status(
    *,
    status: str,
    generated_at: datetime,
    decision_at: datetime | None,
    strict_t_minus_one: date | None,
    blockers: tuple[str, ...],
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "task": TASK_NAME,
        "status": status,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "decision_at": (
            decision_at.isoformat(timespec="seconds")
            if decision_at is not None
            else None
        ),
        "strict_t_minus_one": (
            strict_t_minus_one.isoformat()
            if strict_t_minus_one is not None
            else None
        ),
        "blockers": list(blockers),
        "compatible_evidence_published": status == "published",
        "authority_required": True,
        "authorization_artifact_created": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "broker_order_allowed": False,
        **dict(extra or {}),
    }
    return {**body, "status_hash": _payload_hash(body)}


def run(
    *,
    output_root: Path,
    database_path: Path,
    now: datetime | None = None,
    calendar: _Calendar | None = None,
) -> dict[str, object]:
    local_now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    release_root = (output_root / "release_v4").resolve()
    status_path = (
        output_root
        / "scheduled"
        / "ml_promotion_evidence"
        / "latest_status.json"
    )
    decision_at: datetime | None = None
    strict_t_minus_one: date | None = None
    try:
        calendar_service = calendar or OfficialTradingCalendar(database_path)
        decision_at, decision_reason = _next_official_decision(
            now=local_now,
            calendar=calendar_service,
        )
        strict_t_minus_one, t_minus_one_reason = (
            _strict_previous_trading_day(
                decision_date=decision_at.date(),
                calendar=calendar_service,
            )
        )
        training_path, dataset_path, training_run_id = (
            _discover_training_and_store(release_root=release_root)
        )
        _build_replays(
            release_root=release_root,
            training_manifest_path=training_path,
            decision_at=decision_at,
        )
        replay_primary, primary_hash, primary_run_id = _discover_replay(
            release_root=release_root,
            lane="primary",
        )
        replay_verification, verification_hash, verification_run_id = (
            _discover_replay(
                release_root=release_root,
                lane="verification",
            )
        )
        if primary_run_id == verification_run_id:
            raise ValueError("primary and verification replay run ids match")
        if primary_hash != verification_hash:
            raise ValueError(
                "primary and verification replay result hashes differ"
            )
        shadow_sidecar = (
            output_root
            / "scheduled"
            / "ml_allocation_copilot"
            / "shadow_evidence_collector"
            / "shadow_evidence.sqlite"
        ).resolve()
        if not shadow_sidecar.is_file():
            raise FileNotFoundError("shadow evidence sidecar is missing")
        reference_path, reference_file_hash = _discover_reference(
            release_root=release_root,
        )
        reference_metrics_path = _discover_reference_metrics(
            output_root=output_root,
        )
        result = build_compatible_allocation_promotion_evidence(
            AllocationPromotionEvidenceBuildRequest(
                experiment_id=(
                    f"allocation-ooc-production-v4:{training_run_id}"
                ),
                decision_at=decision_at,
                as_of_date=strict_t_minus_one,
                training_manifest_path=training_path,
                dataset_manifest_path=dataset_path,
                replay_primary_path=replay_primary,
                replay_verification_path=replay_verification,
                shadow_sidecar_database_path=shadow_sidecar,
                promotion_reference_path=reference_path,
                promotion_reference_metrics_path=reference_metrics_path,
                output_root=(
                    release_root / "ml_allocation_promotion_evidence"
                ),
                expected_promotion_reference_file_hash=(
                    reference_file_hash
                ),
            )
        )
        if result.status == "blocked":
            payload = _status(
                status="blocked",
                generated_at=local_now,
                decision_at=decision_at,
                strict_t_minus_one=strict_t_minus_one,
                blockers=result.blockers,
                extra={
                    "decision_calendar_reason": decision_reason,
                    "strict_t_minus_one_reason": t_minus_one_reason,
                    "training_run_id": training_run_id,
                    "replay_result_hash": primary_hash,
                },
            )
        else:
            payload = _status(
                status="published",
                generated_at=local_now,
                decision_at=decision_at,
                strict_t_minus_one=strict_t_minus_one,
                blockers=(),
                extra={
                    "decision_calendar_reason": decision_reason,
                    "strict_t_minus_one_reason": t_minus_one_reason,
                    "training_run_id": training_run_id,
                    "replay_result_hash": primary_hash,
                    "publication_id": result.publication_id,
                    "publication_hash": result.publication_hash,
                    "evidence_hash": result.evidence_hash,
                    "evidence_pointer_hash": result.pointer_hash,
                    "evidence_pointer_path": (
                        str(result.latest_pointer_path.resolve())
                        if result.latest_pointer_path is not None
                        else None
                    ),
                },
            )
    except (
        FileNotFoundError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        payload = _status(
            status="blocked",
            generated_at=local_now,
            decision_at=decision_at,
            strict_t_minus_one=strict_t_minus_one,
            blockers=(
                f"promotion_evidence_preflight:{type(exc).__name__}:"
                f"{' '.join(str(exc).split())}",
            ),
        )
    _atomic_write_json(status_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    data_root = Path(
        os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")
    )
    output_root = Path(
        os.environ.get("OUTPUT_ROOT", str(data_root / "output"))
    )
    parser = argparse.ArgumentParser(
        description=(
            "Discover immutable formal OOC/replay/shadow/reference custody "
            "and publish unsigned promotion evidence; missing evidence is "
            "a successful fail-closed operational state."
        )
    )
    parser.add_argument("--output-root", type=Path, default=output_root)
    parser.add_argument(
        "--database",
        type=Path,
        default=data_root / "sqlite" / "twstock.db",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(
        output_root=args.output_root,
        database_path=args.database,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
