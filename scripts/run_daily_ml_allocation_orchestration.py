"""執行配置型 ML Production Co-pilot 的每日完整、fail-closed 編排。

流程固定為：

1. 以官方交易日曆確認決策日及 strict T-1。
2. 從正式 SQLite 建立 11 檔 bounded、immutable PIT raw publication。
3. 以凍結訓練 manifest 建立 post-freeze inference input。
4. 以嚴格 T-1 Paper ledger 建立 0/2000/3500/5000 四條研究 lane，
   經 V4 hard projector 後寫入 append-only evidence sidecar。
5. 成熟既有 20 日 observation；promotion evaluator 僅能讀取 collector
   產生且 consumer-compatible 的 hash-bound evidence。

任一 ML 階段失敗時只寫入 Rule-only status；不呼叫後續 promotion evaluator，
因此不會把「沒有 inference 的排程成功」偽計為一個 shadow observation。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Protocol, Sequence, cast
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_module.ml_pit_year_shard_exporter import (  # noqa: E402
    PITYearShardBuildRequest,
    PITYearShardExporter,
)
from data_module.official_trading_calendar import (  # noqa: E402
    OfficialTradingCalendar,
)
from data_module.ml_storage_capacity import (  # noqa: E402
    MLStorageCapacityBudget,
)
from app_module.ml_allocation_inference_service import (  # noqa: E402
    _feature_snapshot_hash,
)
from app_module.ml_allocation_shadow_evidence import (  # noqa: E402
    MLAllocationShadowCollector,
)
from ml_module.allocation_contracts import PortfolioMLDatasetRow  # noqa: E402
from ml_module.allocation_promotion_reference import (  # noqa: E402
    load_promotion_reference,
)
from scripts.build_ml_allocation_post_freeze_shadow_input import (  # noqa: E402
    _run as _build_post_freeze_shadow_input,
)
from scripts.infer_ml_allocation_copilot import (  # noqa: E402
    _load_rows as _load_inference_rows,
    _run as _infer_ml_allocation,
)
from scripts.run_ml_allocation_copilot import (  # noqa: E402
    _parse_decision_at,
    _promotion_trust_configuration,
    run as _run_promotion,
)


TAIPEI = ZoneInfo("Asia/Taipei")
TASK_NAME = "baldr-ml-allocation-copilot-daily"
SCHEMA_VERSION = "ml-allocation-daily-orchestration.v3"
TRAINING_MANIFEST_SCHEMA_VERSION = "allocation-training-output-manifest-v2"
PROMOTION_REFERENCE_POINTER_SCHEMA_VERSION = (
    "ml-allocation-promotion-reference-pointer-v1"
)
PROMOTION_AUTHORITY_POINTER_SCHEMA_VERSION = (
    "baldr-promotion-authorization-pointer.v1"
)
FORMAL_DATASET_ID = "all_field_enriched"
POLICY_HASH = (
    "sha256:b196364ec3d67149580b556979c21f75f3c4864f7dc4a06fc4654e53d2c46631"
)
DEFAULT_SYMBOLS = (
    "1101",
    "1216",
    "1301",
    "2002",
    "2303",
    "2317",
    "2330",
    "2412",
    "2454",
    "2881",
    "6505",
)
DEFAULT_MODEL_ID = "baldr-ml-allocation-bounded-v4-operational"
DEFAULT_UNIVERSE_ID = "twse-bounded-11-v4"
DEFAULT_POLICY_ID = "balanced-v4-operational"
DEFAULT_RAW_LOOKBACK_DAYS = 730
ALLOWED_ALPHA_BP = frozenset({0, 2_000, 3_500, 5_000})
AUTO_CATCH_UP_MAX_CALENDAR_DAYS = 31


@dataclass(frozen=True)
class FrozenRelease:
    release_root: Path
    training_manifest_path: Path
    training_manifest_file_hash: str
    training_as_of: datetime
    dataset_id: str
    dataset_identity_hash: str
    dataset_manifest_file_hash: str
    artifact_path: Path
    artifact_hash: str


@dataclass(frozen=True)
class RawPublication:
    publication_id: str
    publication_directory: Path
    publication_manifest_path: Path
    publication_manifest_hash: str
    publication_manifest_file_hash: str
    dataset_manifest_path: Path
    dataset_manifest_hash: str
    dataset_manifest_file_hash: str
    row_count: int
    shard_count: int
    # Optional defaults keep the immutable value object compatible with
    # existing callers that construct a test/read-only publication before
    # capacity telemetry is available.
    capacity_preflight: Mapping[str, Any] = field(default_factory=dict)
    temporary_peak_bytes_observed: int | None = None
    capacity_checkpoint_count: int = 0
    capacity_last_stage: str = "not_observed"


@dataclass(frozen=True)
class FrozenPromotionReference:
    pointer_path: Path
    pointer_file_hash: str
    reference_path: Path
    reference_hash: str
    reference_file_hash: str


class TradingCalendar(Protocol):
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
    return f"sha256:{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()}"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _load_promotion_authority_pointer(
    *,
    pointer_path: Path | None,
    decision_at: datetime,
    release_root: Path,
) -> dict[str, Path] | None:
    """Load only the fixed, signed-custody pointer for this decision window.

    Invalid, stale, or absent pointers are not fatal to Rule operations; the
    caller falls back to the current unsigned collector evidence and therefore
    remains at alpha=0.
    """

    if pointer_path is None or not pointer_path.is_file():
        return None
    try:
        pointer = _read_json_object(
            pointer_path,
            field_name="promotion authority pointer",
        )
        if (
            pointer.get("schema_version")
            != PROMOTION_AUTHORITY_POINTER_SCHEMA_VERSION
        ):
            return None
        pointer_hash = pointer.get("pointer_hash")
        if not isinstance(pointer_hash, str):
            return None
        body = {
            key: value
            for key, value in pointer.items()
            if key != "pointer_hash"
        }
        if pointer_hash != _payload_hash(body):
            return None
        pointer_decision = datetime.fromisoformat(
            _text(
                pointer.get("decision_at"),
                field_name="promotion authority decision_at",
            ).replace("Z", "+00:00")
        ).astimezone(TAIPEI)
        valid_from = datetime.fromisoformat(
            _text(
                pointer.get("decision_valid_from"),
                field_name="promotion authority valid_from",
            ).replace("Z", "+00:00")
        ).astimezone(TAIPEI)
        valid_until = datetime.fromisoformat(
            _text(
                pointer.get("decision_valid_until"),
                field_name="promotion authority valid_until",
            ).replace("Z", "+00:00")
        ).astimezone(TAIPEI)
        if pointer_decision != decision_at or not (
            valid_from <= decision_at <= valid_until
        ):
            return None
        resolved_release_root = release_root.resolve()
        custody_root = Path(
            _text(
                pointer.get("custody_root"),
                field_name="promotion authority custody_root",
            )
        ).resolve()
        if custody_root != resolved_release_root:
            return None
        path_fields = {
            "evidence_path": "evidence_path",
            "authorization_path": "authorization_path",
            "registry_revision_path": "registry_revision_path",
            "model_artifact_path": "model_artifact_path",
            "dataset_manifest_path": "dataset_manifest_path",
            "oof_bundle_path": "oof_bundle_path",
            "shadow_evidence_path": "shadow_evidence_path",
        }
        resolved: dict[str, Path] = {}
        for output_name, source_name in path_fields.items():
            raw_value = pointer.get(source_name)
            if not isinstance(raw_value, str) or not raw_value.strip():
                return None
            path = Path(raw_value).resolve()
            if (
                not path.is_file()
                or not path.is_relative_to(resolved_release_root)
            ):
                return None
            resolved[output_name] = path
        authorization_file_hash = pointer.get("authorization_file_hash")
        if (
            not isinstance(authorization_file_hash, str)
            or _file_hash(resolved["authorization_path"])
            != authorization_file_hash
        ):
            return None
    except (OSError, TypeError, ValueError):
        return None
    return resolved


def _with_hash(
    payload: Mapping[str, object],
    *,
    field_name: str,
) -> dict[str, object]:
    result = dict(payload)
    result[field_name] = _payload_hash(result)
    return result


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_json_object(path: Path, *, field_name: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"{field_name} is missing: {path}") from None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field_name} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    return payload


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value.strip()


def _integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _sha256_text(value: object, *, field_name: str) -> str:
    result = _text(value, field_name=field_name)
    if len(result) != 71 or not result.startswith("sha256:"):
        raise ValueError(f"{field_name} must be a sha256 hash")
    try:
        int(result[7:], 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a sha256 hash") from exc
    return result


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    text_value = _text(value, field_name=field_name)
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must contain a timezone")
    return parsed.astimezone(TAIPEI)


def _validate_decision_at(decision_at: datetime) -> datetime:
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("decision_at must contain a timezone")
    local = decision_at.astimezone(TAIPEI)
    if local.timetz().replace(tzinfo=None) != time(8, 30):
        raise ValueError("decision_at must equal 08:30 Asia/Taipei")
    return local


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _load_frozen_release(release_root: Path) -> FrozenRelease:
    resolved_root = release_root.resolve()
    manifest_path = resolved_root / "training_manifest_v2.json"
    manifest = _read_json_object(
        manifest_path,
        field_name="training manifest",
    )
    if manifest.get("schema_version") != TRAINING_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported training manifest schema")

    artifact_file = _text(
        manifest.get("artifact_file"),
        field_name="training.artifact_file",
    )
    artifact_path = (resolved_root / artifact_file).resolve()
    if not _is_within(artifact_path, resolved_root):
        raise ValueError("training artifact escapes the release root")
    if not artifact_path.is_file():
        raise FileNotFoundError(f"training artifact is missing: {artifact_path}")

    expected_artifact_hash = _sha256_text(
        manifest.get("artifact_hash"),
        field_name="training.artifact_hash",
    )
    if _file_hash(artifact_path) != expected_artifact_hash:
        raise ValueError("training artifact hash mismatch")

    return FrozenRelease(
        release_root=resolved_root,
        training_manifest_path=manifest_path,
        training_manifest_file_hash=_file_hash(manifest_path),
        training_as_of=_aware_datetime(
            manifest.get("training_as_of"),
            field_name="training.training_as_of",
        ),
        dataset_id=_text(
            manifest.get("dataset_id"),
            field_name="training.dataset_id",
        ),
        dataset_identity_hash=_sha256_text(
            manifest.get("dataset_identity_hash"),
            field_name="training.dataset_identity_hash",
        ),
        dataset_manifest_file_hash=_sha256_text(
            manifest.get("dataset_manifest_file_hash"),
            field_name="training.dataset_manifest_file_hash",
        ),
        artifact_path=artifact_path,
        artifact_hash=expected_artifact_hash,
    )


def _load_promotion_reference_pointer(
    *,
    pointer_path: Path,
    release: FrozenRelease,
    policy_hash: str,
) -> FrozenPromotionReference:
    resolved_pointer = pointer_path.resolve()
    pointer = _read_json_object(
        resolved_pointer,
        field_name="promotion reference pointer",
    )
    if (
        pointer.get("schema_version")
        != PROMOTION_REFERENCE_POINTER_SCHEMA_VERSION
    ):
        raise ValueError("unsupported promotion reference pointer schema")
    reference_path = Path(
        _text(
            pointer.get("reference_path"),
            field_name="promotion_reference.reference_path",
        )
    ).resolve()
    if not _is_within(reference_path, resolved_pointer.parent):
        raise ValueError("promotion reference escapes its publication root")
    reference_hash = _sha256_text(
        pointer.get("reference_hash"),
        field_name="promotion_reference.reference_hash",
    )
    reference_file_hash = _sha256_text(
        pointer.get("reference_file_hash"),
        field_name="promotion_reference.reference_file_hash",
    )
    reference = load_promotion_reference(
        reference_path,
        expected_reference_file_hash=reference_file_hash,
        expected_model_artifact_hash=release.artifact_hash,
        expected_dataset_identity_hash=release.dataset_identity_hash,
        expected_promotion_policy_hash=policy_hash,
    )
    if reference.get("reference_hash") != reference_hash:
        raise ValueError("promotion reference pointer canonical hash mismatch")
    return FrozenPromotionReference(
        pointer_path=resolved_pointer,
        pointer_file_hash=_file_hash(resolved_pointer),
        reference_path=reference_path,
        reference_hash=reference_hash,
        reference_file_hash=reference_file_hash,
    )


def _calendar_day_state(
    calendar: TradingCalendar,
    target_date: date,
) -> tuple[bool | None, str]:
    try:
        return calendar.is_official_trading_day(target_date)
    except Exception as exc:  # noqa: BLE001 - 排程狀態必須 fail closed 並持久化
        return None, f"calendar_exception:{type(exc).__name__}"


def _strict_previous_trading_day(
    calendar: TradingCalendar,
    decision_date: date,
) -> tuple[date, str]:
    for day_offset in range(1, 32):
        candidate = decision_date - timedelta(days=day_offset)
        is_open, reason = _calendar_day_state(calendar, candidate)
        if is_open is True:
            return candidate, reason
        if is_open is None:
            raise RuntimeError(
                f"strict_t_minus_one_calendar_unknown:{candidate.isoformat()}:{reason}"
            )
    raise RuntimeError("strict_t_minus_one_not_found_within_31_days")


def _automatic_previous_decision_candidates(
    *,
    calendar: TradingCalendar,
    requested_decision_at: datetime,
    now: datetime,
) -> tuple[datetime, ...]:
    requested = _validate_decision_at(requested_decision_at)
    local_now = now.astimezone(TAIPEI)
    if requested.date() <= local_now.date():
        return ()
    candidates: list[datetime] = []
    for offset in range(1, AUTO_CATCH_UP_MAX_CALENDAR_DAYS + 1):
        candidate_date = requested.date() - timedelta(days=offset)
        if candidate_date > local_now.date():
            continue
        is_open, _reason = _calendar_day_state(calendar, candidate_date)
        if is_open is None:
            if candidates:
                return tuple(candidates)
            raise RuntimeError(
                "automatic_catch_up_calendar_unknown:"
                f"{candidate_date.isoformat()}"
            )
        if is_open is True:
            candidates.append(
                datetime.combine(
                    candidate_date,
                    time(8, 30),
                    tzinfo=TAIPEI,
                )
            )
    return tuple(candidates)


def _is_retryable_automatic_catch_up_failure(
    *,
    payload: Mapping[str, object],
    requested_decision_at: datetime,
    selected_decision_at: datetime,
    now: datetime,
) -> bool:
    requested = _validate_decision_at(requested_decision_at)
    selected = _validate_decision_at(selected_decision_at)
    if requested.date() <= now.astimezone(TAIPEI).date():
        return False
    if selected.date() > now.astimezone(TAIPEI).date():
        candidate_selected = True
    else:
        candidate_selected = (
            payload.get("decision_selection_mode")
            == "automatic_catch_up"
        )
    if not candidate_selected:
        return False
    if payload.get("orchestration_status") != "fail_closed":
        return False
    failed_stage = payload.get("failed_stage")
    if failed_stage not in {"raw_pit_publication", "post_freeze_input"}:
        return False
    failed_reasons = payload.get("failed_reasons")
    reason_text = " ".join(
        str(item) for item in failed_reasons
    ).lower() if isinstance(failed_reasons, list) else ""
    return any(marker in reason_text for marker in (
        "strict t-1",
        "strict_t_minus_one",
        "expected_price_date",
        "latest provable t-1",
        "raw rows are missing",
    ))


def _taipei_now() -> datetime:
    """Return the scheduler clock through one patchable boundary."""

    return datetime.now(TAIPEI)


def _build_raw_publication(
    *,
    database_path: Path,
    output_root: Path,
    decision_at: datetime,
    strict_t_minus_one: date,
    symbols: tuple[str, ...],
    raw_lookback_days: int,
    batch_size: int,
    compression_level: int,
    capacity_budget: MLStorageCapacityBudget | None = None,
) -> RawPublication:
    if (
        isinstance(raw_lookback_days, bool)
        or not isinstance(raw_lookback_days, int)
        or raw_lookback_days < 1
    ):
        raise ValueError("raw_lookback_days must be a positive integer")
    history_start = strict_t_minus_one - timedelta(days=raw_lookback_days)
    years = tuple(range(history_start.year, decision_at.year + 1))
    publication = PITYearShardExporter().build(
        PITYearShardBuildRequest(
            database_path=database_path,
            output_root=output_root,
            decision_at=decision_at.isoformat(timespec="seconds"),
            history_start_date=history_start.isoformat(),
            symbols=symbols,
            years=years,
            batch_size=batch_size,
            compression_level=compression_level,
            temporary_storage_budget_bytes=(
                capacity_budget.temporary_peak_bytes_budget
                if capacity_budget is not None
                else None
            ),
            persistent_new_bytes_budget=(
                capacity_budget.persistent_new_bytes_budget
                if capacity_budget is not None
                else None
            ),
            safety_reserve_bytes=(
                capacity_budget.safety_reserve_bytes
                if capacity_budget is not None
                else None
            ),
        )
    )
    dataset_manifest_path = Path(
        publication.dataset_manifest_paths[FORMAL_DATASET_ID]
    ).resolve()
    publication_directory = publication.publication_directory.resolve()
    if not _is_within(dataset_manifest_path, publication_directory):
        raise ValueError("raw dataset manifest escapes immutable publication")
    if any(part.startswith(".pit-shards-") for part in dataset_manifest_path.parts):
        raise ValueError("raw dataset manifest points to staging")
    dataset_manifest = _read_json_object(
        dataset_manifest_path,
        field_name="raw all_field_enriched manifest",
    )
    if dataset_manifest.get("dataset_id") != FORMAL_DATASET_ID:
        raise ValueError("raw dataset manifest is not all_field_enriched")
    dataset_manifest_hash = _sha256_text(
        dataset_manifest.get("manifest_hash"),
        field_name="raw dataset manifest_hash",
    )
    return RawPublication(
        publication_id=publication.publication_id,
        publication_directory=publication_directory,
        publication_manifest_path=publication.manifest_path.resolve(),
        publication_manifest_hash=publication.manifest_hash,
        publication_manifest_file_hash=_file_hash(
            publication.manifest_path.resolve()
        ),
        dataset_manifest_path=dataset_manifest_path,
        dataset_manifest_hash=dataset_manifest_hash,
        dataset_manifest_file_hash=_file_hash(dataset_manifest_path),
        row_count=publication.row_count,
        shard_count=publication.shard_count,
        capacity_preflight=dict(publication.capacity_preflight),
        temporary_peak_bytes_observed=publication.temporary_peak_bytes_observed,
        capacity_checkpoint_count=publication.capacity_checkpoint_count,
        capacity_last_stage=publication.capacity_last_stage,
    )


def _build_post_freeze_input(
    *,
    raw: RawPublication,
    release: FrozenRelease,
    decision_at: datetime,
    strict_t_minus_one: date,
    symbols: tuple[str, ...],
    input_output: Path,
    audit_output: Path,
    batch_size: int,
    compression_level: int,
    pit_machine_operational_path: Path | None = None,
) -> Mapping[str, Any]:
    return _build_post_freeze_shadow_input(
        raw_dataset_manifest=raw.dataset_manifest_path,
        expected_raw_publication_manifest_hash=(
            raw.publication_manifest_hash
        ),
        expected_raw_dataset_manifest_hash=raw.dataset_manifest_hash,
        training_manifest=release.training_manifest_path,
        expected_training_manifest_file_hash=(
            release.training_manifest_file_hash
        ),
        decision_at=decision_at.isoformat(timespec="seconds"),
        expected_price_date=strict_t_minus_one.isoformat(),
        pit_machine_operational_publication=pit_machine_operational_path,
        expected_symbol_count=len(symbols),
        post_freeze_shadow_input_output=input_output,
        audit_output=audit_output,
        batch_size=batch_size,
        compression_level=compression_level,
    )


def _run_inference(
    *,
    release: FrozenRelease,
    input_path: Path,
    proposal_output: Path,
    audit_output: Path,
    model_id: str,
    universe_id: str,
    policy_id: str,
    policy_hash: str,
    expected_universe_hash: str,
) -> Mapping[str, Any]:
    # 新 release manifest 存在時走 hash-bound adapter；舊 training manifest
    # 測試／歷史輸出沒有 release contract 時維持相容的 immutable artifact path。
    # 這個判斷不會自動把舊 artifact 升格；若 manifest 存在但驗證失敗，
    # adapter 例外會讓整個 ML stage fail closed。
    if (release.release_root / "release_manifest.json").is_file():
        return _infer_ml_allocation(
            artifact_path=None,
            expected_artifact_hash=None,
            expected_dataset_id=None,
            release_root=release.release_root,
            input_path=input_path,
            model_id=model_id,
            universe_id=universe_id,
            policy_id=policy_id,
            policy_hash=policy_hash,
            expected_universe_hash=expected_universe_hash,
            proposal_output=proposal_output,
            audit_output=audit_output,
        )
    return _infer_ml_allocation(
        artifact_path=release.artifact_path,
        expected_artifact_hash=release.artifact_hash,
        expected_dataset_id=release.dataset_id,
        release_root=None,
        input_path=input_path,
        model_id=model_id,
        universe_id=universe_id,
        policy_id=policy_id,
        policy_hash=policy_hash,
        expected_universe_hash=expected_universe_hash,
        proposal_output=proposal_output,
        audit_output=audit_output,
    )


def _run_promotion_evaluator(
    *,
    output_root: Path,
    decision_at: datetime,
    evidence_path: Path | None,
    authorization_path: Path | None,
    calendar: TradingCalendar,
    registry_revision_path: Path | None,
    model_artifact_path: Path | None,
    dataset_manifest_path: Path | None,
    oof_bundle_path: Path | None,
    shadow_evidence_path: Path | None,
    trusted_issuer_keys: Mapping[str, bytes] | None,
    trusted_custody_roots: Sequence[Path],
    trusted_custody_id: str | None,
) -> Mapping[str, object]:
    return _run_promotion(
        output_root=output_root,
        decision_at=decision_at,
        evidence_path=evidence_path,
        authorization_path=authorization_path,
        calendar=cast(OfficialTradingCalendar, calendar),
        registry_revision_path=registry_revision_path,
        model_artifact_path=model_artifact_path,
        dataset_manifest_path=dataset_manifest_path,
        oof_bundle_path=oof_bundle_path,
        shadow_evidence_path=shadow_evidence_path,
        trusted_issuer_keys=trusted_issuer_keys,
        trusted_custody_roots=trusted_custody_roots,
        trusted_custody_id=trusted_custody_id,
    )


def _run_shadow_evidence_collector(
    *,
    database_path: Path,
    paper_state_db_path: Path,
    run_root: Path,
    decision_date: date,
    strict_t_minus_one: date,
    proposal_path: Path,
    proposal_hash: str,
    proposal_file_hash: str,
    replay_hash: str,
    orchestration_run_hash: str,
    rule_policy_hash: str,
    release_training_manifest_file_hash: str,
    raw_publication_manifest_hash: str,
    inference_universe_hash: str,
    promotion_reference: FrozenPromotionReference | None,
    model_artifact_path: Path | None,
    post_freeze_rows: Sequence[PortfolioMLDatasetRow],
    post_freeze_input_hash: str | None,
) -> Mapping[str, object]:
    collector_root = run_root / "shadow_evidence_collector"
    collector = MLAllocationShadowCollector(
        market_database_path=database_path,
        paper_state_db_path=paper_state_db_path,
        sidecar_database_path=collector_root / "shadow_evidence.sqlite",
        artifact_root=collector_root,
        promotion_reference_path=(
            promotion_reference.reference_path
            if promotion_reference is not None
            else None
        ),
        promotion_reference_file_hash=(
            promotion_reference.reference_file_hash
            if promotion_reference is not None
            else None
        ),
    )
    return collector.record_and_mature(
        decision_date=decision_date,
        strict_t_minus_one=strict_t_minus_one,
        proposal_path=proposal_path,
        proposal_hash=proposal_hash,
        proposal_file_hash=proposal_file_hash,
        replay_hash=replay_hash,
        orchestration_run_hash=orchestration_run_hash,
        rule_policy_hash=rule_policy_hash,
        release_training_manifest_file_hash=(
            release_training_manifest_file_hash
        ),
        raw_publication_manifest_hash=raw_publication_manifest_hash,
        inference_universe_hash=inference_universe_hash,
        model_artifact_path=model_artifact_path,
        post_freeze_rows=post_freeze_rows,
        post_freeze_input_hash=post_freeze_input_hash,
    )


def _stage_error(stage: str, exc: Exception) -> str:
    message = " ".join(str(exc).split())
    if len(message) > 1_000:
        message = f"{message[:997]}..."
    return f"{stage}:{type(exc).__name__}:{message}"


def _calculate_inference_universe_hash(input_path: Path) -> str:
    rows = _load_inference_rows(input_path)
    row_ids = tuple(row.row_id for row in rows)
    symbols = tuple(row.symbol for row in rows)
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("inference input row ids must be unique")
    if len(symbols) != len(set(symbols)):
        raise ValueError("inference input symbols must be unique")
    canonical_rows = tuple(sorted(rows, key=lambda row: row.symbol))
    return _payload_hash(
        [
            {
                "row_id": row.row_id,
                "symbol": row.symbol,
                "feature_snapshot_hash": _feature_snapshot_hash(row),
            }
            for row in canonical_rows
        ]
    )


def _base_status(
    *,
    decision_at: datetime,
    trading_calendar_is_open: bool | None,
    trading_calendar_reason: str,
    decision_selection_mode: str,
    requested_decision_at: datetime,
    decision_selection_reason: str | None,
    decision_selection_attempts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task": TASK_NAME,
        "status": "passed_rule_only",
        "operation_mode": "rule_only",
        "orchestration_status": "fail_closed",
        "decision_at": decision_at.isoformat(timespec="seconds"),
        "decision_selection_mode": decision_selection_mode,
        "requested_decision_at": requested_decision_at.isoformat(
            timespec="seconds"
        ),
        "decision_selection_reason": decision_selection_reason,
        "decision_selection_attempts": [
            dict(attempt) for attempt in decision_selection_attempts
        ],
        "trading_calendar_validated": trading_calendar_is_open is not None,
        "trading_calendar_is_open": trading_calendar_is_open,
        "trading_calendar_reason": trading_calendar_reason,
        "strict_t_minus_one": None,
        "strict_t_minus_one_reason": None,
        "selected_alpha_bp": 0,
        "production_blend_alpha_bp": 0,
        "formal_oos_allowed": False,
        "production_action_allowed": False,
        "broker_order_allowed": False,
        "broker_execution": False,
        "rule_lane_operational": True,
        "ml_pipeline_status": "blocked",
        "post_freeze_input_status": "not_run",
        "inference_status": "not_run",
        "shadow_evidence_status": "not_run",
        "promotion_status": "not_run",
        "shadow_observation_recorded": False,
        "shadow_day_credit_allowed": False,
        "shadow_observation_hash": None,
        "shadow_observation_path": None,
        "shadow_observation_revision": None,
        "shadow_lane_count": 0,
        "shadow_evidence_hash": None,
        "shadow_evidence_path": None,
        "matured_shadow_observation_count": 0,
        "compatible_promotion_evidence_path": None,
        "production_advice_path": None,
        "production_advice_hash": None,
        "failed_stage": None,
        "failed_reasons": [],
        "stage_results": {},
        "orchestration_run_hash": None,
        "release_training_manifest_file_hash": None,
        "release_dataset_identity_hash": None,
        "release_dataset_manifest_file_hash": None,
        "release_model_artifact_hash": None,
        "promotion_reference_pointer_path": None,
        "promotion_reference_pointer_file_hash": None,
        "promotion_reference_path": None,
        "promotion_reference_hash": None,
        "promotion_reference_file_hash": None,
        "promotion_reference_observation_hash": None,
        "promotion_current_distribution_hash": None,
        "promotion_reference_metrics_hash": None,
        "raw_publication_id": None,
        "raw_publication_manifest_hash": None,
        "raw_publication_manifest_file_hash": None,
        "raw_dataset_manifest_hash": None,
        "raw_dataset_manifest_file_hash": None,
        "post_freeze_input_hash": None,
        "post_freeze_audit_hash": None,
        "post_freeze_audit_file_hash": None,
        "proposal_hash": None,
        "proposal_file_hash": None,
        "replay_hash": None,
        "inference_universe_hash": None,
        "inference_audit_file_hash": None,
        "promotion_status_hash": None,
        "promotion_artifact_hash": None,
        "promotion_artifact_file_hash": None,
        "promotion_sidecar_record_hash": None,
        "promotion_sidecar_file_hash": None,
        "writes_source_database": False,
        "changes_portfolio_state": False,
    }


def _write_status(
    run_root: Path,
    status: Mapping[str, object],
) -> dict[str, object]:
    payload_without_hash = dict(status)
    payload_without_hash.pop("status_hash", None)
    payload = _with_hash(
        payload_without_hash,
        field_name="status_hash",
    )
    _atomic_write_json(run_root / "latest_status.json", payload)
    return payload


def _fail_closed(
    *,
    run_root: Path,
    status: Mapping[str, object],
    stage: str,
    exc: Exception,
) -> dict[str, object]:
    payload = dict(status)
    payload["status"] = "passed_rule_only"
    payload["operation_mode"] = "rule_only"
    payload["orchestration_status"] = "fail_closed"
    payload["ml_pipeline_status"] = "blocked"
    payload["selected_alpha_bp"] = 0
    payload["production_blend_alpha_bp"] = 0
    payload["formal_oos_allowed"] = False
    payload["production_action_allowed"] = False
    payload["broker_order_allowed"] = False
    payload["broker_execution"] = False
    if stage != "promotion":
        payload["shadow_observation_recorded"] = False
        payload["shadow_day_credit_allowed"] = False
    payload["failed_stage"] = stage
    payload["failed_reasons"] = [_stage_error(stage, exc)]
    if stage == "post_freeze_input":
        payload["post_freeze_input_status"] = "failed"
    elif stage == "inference":
        payload["inference_status"] = "failed"
    elif stage == "shadow_evidence":
        payload["shadow_evidence_status"] = "failed"
    elif stage == "promotion":
        payload["promotion_status"] = "failed"
    return _write_status(run_root, payload)


def _validate_stage_result(
    payload: Mapping[str, Any],
    *,
    expected_status: str,
    stage: str,
) -> None:
    if payload.get("status") != expected_status:
        raise ValueError(f"{stage} returned unexpected status")
    if payload.get("broker_order_allowed") is not False:
        raise ValueError(f"{stage} attempted to allow broker orders")
    if payload.get("production_blend_alpha_bp") != 0:
        raise ValueError(f"{stage} must remain alpha=0 before promotion")


def _status_stage_results(
    status: Mapping[str, object],
) -> dict[str, object]:
    value = status.get("stage_results")
    if not isinstance(value, dict):
        raise TypeError("status.stage_results must be an object")
    return dict(value)


def _validate_promotion_result(
    payload: Mapping[str, object],
) -> tuple[int, bool]:
    selected_alpha_bp = _integer(
        payload.get("selected_alpha_bp"),
        field_name="promotion.selected_alpha_bp",
    )
    production_alpha_bp = _integer(
        payload.get("production_blend_alpha_bp"),
        field_name="promotion.production_blend_alpha_bp",
    )
    formal_oos_allowed = payload.get("formal_oos_allowed") is True
    if selected_alpha_bp not in ALLOWED_ALPHA_BP:
        raise ValueError("promotion selected an unsupported alpha lane")
    if production_alpha_bp != selected_alpha_bp:
        raise ValueError("promotion alpha fields disagree")
    if (selected_alpha_bp != 0) != formal_oos_allowed:
        raise ValueError("promotion formal OOS and alpha state disagree")
    if payload.get("broker_execution") is not False:
        raise ValueError("promotion attempted broker execution")
    return selected_alpha_bp, formal_oos_allowed


def _promotion_custody_inputs(
    *,
    release: FrozenRelease,
    requested_model_artifact_path: Path | None,
    requested_dataset_manifest_path: Path | None,
) -> tuple[Path, Path | None]:
    if requested_model_artifact_path is not None:
        requested_model = requested_model_artifact_path.resolve()
        if requested_model != release.artifact_path:
            raise ValueError(
                "promotion model artifact does not equal the inference release artifact"
            )

    if requested_dataset_manifest_path is None:
        return release.artifact_path, None
    dataset_manifest_path = requested_dataset_manifest_path.resolve()
    if _file_hash(dataset_manifest_path) != release.dataset_manifest_file_hash:
        raise ValueError(
            "promotion dataset manifest file hash does not match the inference release"
        )
    dataset_manifest = _read_json_object(
        dataset_manifest_path,
        field_name="promotion dataset manifest",
    )
    dataset_identity_hash = _sha256_text(
        dataset_manifest.get("dataset_identity_hash"),
        field_name="promotion dataset_manifest.dataset_identity_hash",
    )
    if dataset_identity_hash != release.dataset_identity_hash:
        raise ValueError(
            "promotion dataset identity does not match the inference release"
        )
    return release.artifact_path, dataset_manifest_path


def run(
    *,
    database_path: Path,
    output_root: Path,
    release_root: Path,
    paper_state_db_path: Path | None = None,
    decision_at: datetime,
    decision_selection_mode: str = "requested",
    requested_decision_at: datetime | None = None,
    decision_selection_reason: str | None = None,
    decision_selection_attempts: Sequence[Mapping[str, object]] = (),
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    policy_hash: str = POLICY_HASH,
    raw_lookback_days: int = DEFAULT_RAW_LOOKBACK_DAYS,
    batch_size: int = 2_048,
    compression_level: int = 6,
    capacity_budget: MLStorageCapacityBudget | None = None,
    pit_machine_operational_path: Path | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    universe_id: str = DEFAULT_UNIVERSE_ID,
    policy_id: str = DEFAULT_POLICY_ID,
    evidence_path: Path | None = None,
    authorization_path: Path | None = None,
    calendar: TradingCalendar | None = None,
    registry_revision_path: Path | None = None,
    model_artifact_path: Path | None = None,
    dataset_manifest_path: Path | None = None,
    oof_bundle_path: Path | None = None,
    shadow_evidence_path: Path | None = None,
    promotion_reference_pointer_path: Path | None = None,
    promotion_authority_pointer_path: Path | None = None,
    trusted_issuer_keys: Mapping[str, bytes] | None = None,
    trusted_custody_roots: Sequence[Path] = (),
    trusted_custody_id: str | None = None,
) -> dict[str, object]:
    local_decision_at = _validate_decision_at(decision_at)
    local_requested_decision_at = (
        _validate_decision_at(requested_decision_at)
        if requested_decision_at is not None
        else local_decision_at
    )
    if not decision_selection_mode.strip():
        raise ValueError("decision_selection_mode must not be empty")
    normalized_symbols = tuple(dict.fromkeys(symbol.strip() for symbol in symbols))
    if normalized_symbols != DEFAULT_SYMBOLS:
        raise ValueError("daily orchestration universe must equal the fixed 11 symbols")
    _sha256_text(policy_hash, field_name="policy_hash")
    run_root = output_root / "scheduled" / "ml_allocation_copilot"
    effective_paper_state_db_path = (
        paper_state_db_path
        if paper_state_db_path is not None
        else output_root / "paper_portfolio" / "paper_portfolio.sqlite"
    )
    calendar_service = calendar or OfficialTradingCalendar(database_path)
    is_trading_day, calendar_reason = _calendar_day_state(
        calendar_service,
        local_decision_at.date(),
    )
    status = _base_status(
        decision_at=local_decision_at,
        trading_calendar_is_open=is_trading_day,
        trading_calendar_reason=calendar_reason,
        decision_selection_mode=decision_selection_mode,
        requested_decision_at=local_requested_decision_at,
        decision_selection_reason=decision_selection_reason,
        decision_selection_attempts=decision_selection_attempts,
    )

    if is_trading_day is False:
        status["status"] = "skipped_non_trading_day"
        status["operation_mode"] = "not_run"
        status["orchestration_status"] = "skipped"
        status["ml_pipeline_status"] = "not_run"
        status["rule_lane_operational"] = True
        status["failed_stage"] = "trading_calendar"
        status["failed_reasons"] = [
            f"non_trading_day:{calendar_reason}"
        ]
        return _write_status(run_root, status)
    if is_trading_day is None:
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="trading_calendar",
            exc=RuntimeError(
                f"trading_calendar_unknown:{calendar_reason}"
            ),
        )

    promotion_reference: FrozenPromotionReference | None = None
    try:
        release = _load_frozen_release(release_root)
        if local_decision_at <= release.training_as_of:
            raise ValueError(
                "decision_at must be strictly after frozen model training_as_of"
            )
        if promotion_reference_pointer_path is not None:
            promotion_reference = _load_promotion_reference_pointer(
                pointer_path=promotion_reference_pointer_path,
                release=release,
                policy_hash=policy_hash,
            )
        status["release_training_manifest_file_hash"] = (
            release.training_manifest_file_hash
        )
        status["release_dataset_identity_hash"] = (
            release.dataset_identity_hash
        )
        status["release_dataset_manifest_file_hash"] = (
            release.dataset_manifest_file_hash
        )
        status["release_model_artifact_hash"] = release.artifact_hash
        if promotion_reference is not None:
            status["promotion_reference_pointer_path"] = str(
                promotion_reference.pointer_path
            )
            status["promotion_reference_pointer_file_hash"] = (
                promotion_reference.pointer_file_hash
            )
            status["promotion_reference_path"] = str(
                promotion_reference.reference_path
            )
            status["promotion_reference_hash"] = (
                promotion_reference.reference_hash
            )
            status["promotion_reference_file_hash"] = (
                promotion_reference.reference_file_hash
            )
        status["stage_results"] = {
            "release_preflight": {
                "status": "completed",
                "training_manifest_file_hash": (
                    release.training_manifest_file_hash
                ),
                "artifact_hash": release.artifact_hash,
                "dataset_id": release.dataset_id,
                "dataset_identity_hash": (
                    release.dataset_identity_hash
                ),
                "dataset_manifest_file_hash": (
                    release.dataset_manifest_file_hash
                ),
                "training_as_of": release.training_as_of.isoformat(
                    timespec="seconds"
                ),
                "promotion_reference": (
                    {
                        "status": "ready",
                        "pointer_path": str(
                            promotion_reference.pointer_path
                        ),
                        "pointer_file_hash": (
                            promotion_reference.pointer_file_hash
                        ),
                        "reference_path": str(
                            promotion_reference.reference_path
                        ),
                        "reference_hash": (
                            promotion_reference.reference_hash
                        ),
                        "reference_file_hash": (
                            promotion_reference.reference_file_hash
                        ),
                    }
                    if promotion_reference is not None
                    else {"status": "not_configured"}
                ),
            }
        }
    except Exception as exc:  # noqa: BLE001 - ML 失敗不得拖垮 Rule lane
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="release_preflight",
            exc=exc,
        )

    try:
        strict_t_minus_one, t_minus_one_reason = (
            _strict_previous_trading_day(
                calendar_service,
                local_decision_at.date(),
            )
        )
        status["strict_t_minus_one"] = strict_t_minus_one.isoformat()
        status["strict_t_minus_one_reason"] = t_minus_one_reason
        stage_results = dict(
            status["stage_results"]
            if isinstance(status["stage_results"], dict)
            else {}
        )
        stage_results["strict_t_minus_one"] = {
            "status": "completed",
            "price_date": strict_t_minus_one.isoformat(),
            "calendar_reason": t_minus_one_reason,
        }
        status["stage_results"] = stage_results
    except Exception as exc:  # noqa: BLE001
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="strict_t_minus_one",
            exc=exc,
        )

    decision_key = local_decision_at.strftime("%Y%m%d")
    raw_output_root = run_root / "raw_pit_publications"
    try:
        raw = _build_raw_publication(
            database_path=database_path,
            output_root=raw_output_root,
            decision_at=local_decision_at,
            strict_t_minus_one=strict_t_minus_one,
            symbols=normalized_symbols,
            raw_lookback_days=raw_lookback_days,
            batch_size=batch_size,
            compression_level=compression_level,
            capacity_budget=capacity_budget,
        )
        status["raw_publication_id"] = raw.publication_id
        status["raw_publication_manifest_hash"] = (
            raw.publication_manifest_hash
        )
        status["raw_publication_manifest_file_hash"] = (
            raw.publication_manifest_file_hash
        )
        status["raw_dataset_manifest_hash"] = raw.dataset_manifest_hash
        status["raw_dataset_manifest_file_hash"] = (
            raw.dataset_manifest_file_hash
        )
        stage_results = _status_stage_results(status)
        stage_results["raw_pit_publication"] = {
            "status": "completed",
            "publication_id": raw.publication_id,
            "publication_manifest_path": str(
                raw.publication_manifest_path
            ),
            "publication_manifest_hash": (
                raw.publication_manifest_hash
            ),
            "publication_manifest_file_hash": (
                raw.publication_manifest_file_hash
            ),
            "dataset_manifest_path": str(raw.dataset_manifest_path),
            "dataset_manifest_hash": raw.dataset_manifest_hash,
            "dataset_manifest_file_hash": (
                raw.dataset_manifest_file_hash
            ),
            "row_count": raw.row_count,
            "shard_count": raw.shard_count,
            "symbol_count": len(normalized_symbols),
            "raw_lookback_days": raw_lookback_days,
            "source_database_mode": "ro",
            "query_only": True,
            "immutable_publication": True,
            "capacity_preflight": dict(raw.capacity_preflight),
            "temporary_peak_bytes_observed": (
                raw.temporary_peak_bytes_observed
            ),
            "capacity_checkpoint_count": raw.capacity_checkpoint_count,
            "capacity_last_stage": raw.capacity_last_stage,
        }
        status["stage_results"] = stage_results
    except Exception as exc:  # noqa: BLE001
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="raw_pit_publication",
            exc=exc,
        )

    pit_machine_publication_resolved: Path | None = None
    pit_machine_publication_file_hash: str | None = None
    if pit_machine_operational_path is not None:
        pit_machine_publication_resolved = (
            pit_machine_operational_path.expanduser().resolve()
        )
        if not pit_machine_publication_resolved.is_file():
            return _fail_closed(
                run_root=run_root,
                status=status,
                stage="post_freeze_input",
                exc=FileNotFoundError(
                    "pit machine operational publication is missing: "
                    f"{pit_machine_publication_resolved}"
                ),
            )
        try:
            pit_machine_publication_file_hash = _file_hash(
                pit_machine_publication_resolved
            )
        except OSError as exc:
            return _fail_closed(
                run_root=run_root,
                status=status,
                stage="post_freeze_input",
                exc=exc,
            )

    orchestration_run_hash = _payload_hash(
        {
            "decision_at": local_decision_at.isoformat(timespec="seconds"),
            "decision_selection_mode": decision_selection_mode,
            "requested_decision_at": local_requested_decision_at.isoformat(
                timespec="seconds"
            ),
            "decision_selection_reason": decision_selection_reason,
            "decision_selection_attempts": [
                dict(attempt) for attempt in decision_selection_attempts
            ],
            "raw_publication_manifest_hash": (
                raw.publication_manifest_hash
            ),
            "raw_publication_manifest_file_hash": (
                raw.publication_manifest_file_hash
            ),
            "raw_dataset_manifest_hash": raw.dataset_manifest_hash,
            "raw_dataset_manifest_file_hash": (
                raw.dataset_manifest_file_hash
            ),
            "training_manifest_file_hash": (
                release.training_manifest_file_hash
            ),
            "dataset_identity_hash": release.dataset_identity_hash,
            "dataset_manifest_file_hash": (
                release.dataset_manifest_file_hash
            ),
            "model_artifact_hash": release.artifact_hash,
            "policy_hash": policy_hash,
            "promotion_reference_hash": (
                promotion_reference.reference_hash
                if promotion_reference is not None
                else None
            ),
            "promotion_reference_file_hash": (
                promotion_reference.reference_file_hash
                if promotion_reference is not None
                else None
            ),
            "pit_machine_operational_publication": (
                None
                if pit_machine_publication_resolved is None
                else str(pit_machine_publication_resolved)
            ),
            "pit_machine_operational_publication_file_hash": (
                pit_machine_publication_file_hash
            ),
        }
    )
    status["orchestration_run_hash"] = orchestration_run_hash
    orchestration_root = (
        run_root
        / "orchestration"
        / decision_key
        / orchestration_run_hash[7:23]
    )
    input_output = (
        orchestration_root
        / f"{decision_key}_post_freeze_shadow_input.json.gz"
    )
    input_audit_output = (
        orchestration_root
        / f"{decision_key}_post_freeze_shadow_input_audit.json"
    )
    try:
        input_result = _build_post_freeze_input(
            raw=raw,
            release=release,
            decision_at=local_decision_at,
            strict_t_minus_one=strict_t_minus_one,
            symbols=normalized_symbols,
            input_output=input_output,
            audit_output=input_audit_output,
            batch_size=batch_size,
            compression_level=compression_level,
            pit_machine_operational_path=pit_machine_operational_path,
        )
        _validate_stage_result(
            input_result,
            expected_status="post_freeze_shadow_input_built",
            stage="post_freeze_input",
        )
        input_hash = _sha256_text(
            input_result.get("inference_input_compressed_hash"),
            field_name="post_freeze_input.inference_input_compressed_hash",
        )
        input_audit_hash = _sha256_text(
            input_result.get("audit_hash"),
            field_name="post_freeze_input.audit_hash",
        )
        input_file_hash = _file_hash(input_output)
        if input_hash != input_file_hash:
            raise ValueError(
                "post-freeze input file hash does not match builder result"
            )
        input_audit_file_hash = _file_hash(input_audit_output)
        inference_universe_hash = _calculate_inference_universe_hash(
            input_output
        )
        status["post_freeze_input_status"] = "completed"
        status["post_freeze_input_hash"] = input_hash
        status["post_freeze_audit_hash"] = input_audit_hash
        status["post_freeze_audit_file_hash"] = input_audit_file_hash
        status["inference_universe_hash"] = inference_universe_hash
        stage_results = _status_stage_results(status)
        stage_results["post_freeze_input"] = {
            "status": "completed",
            "input_path": str(input_output.resolve()),
            "input_hash": input_hash,
            "audit_path": str(input_audit_output.resolve()),
            "audit_hash": input_audit_hash,
            "audit_file_hash": input_audit_file_hash,
            "inference_universe_hash": inference_universe_hash,
            "selected_symbol_count": input_result.get(
                "selected_symbol_count"
            ),
            "selected_row_count": input_result.get("selected_row_count"),
            "pit_machine_operational_publication": input_result.get(
                "pit_machine_operational_publication"
            ),
            "pit_machine_operational_publication_file_hash": (
                pit_machine_publication_file_hash
            ),
            "feature_counts": input_result.get("feature_counts"),
        }
        status["stage_results"] = stage_results
    except Exception as exc:  # noqa: BLE001
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="post_freeze_input",
            exc=exc,
        )

    proposal_output = (
        orchestration_root / f"{decision_key}_allocation_proposal.json"
    )
    inference_audit_output = (
        orchestration_root / f"{decision_key}_allocation_inference_audit.json"
    )
    try:
        inference_result = _run_inference(
            release=release,
            input_path=input_output,
            proposal_output=proposal_output,
            audit_output=inference_audit_output,
            model_id=model_id,
            universe_id=universe_id,
            policy_id=policy_id,
            policy_hash=policy_hash,
            expected_universe_hash=inference_universe_hash,
        )
        _validate_stage_result(
            inference_result,
            expected_status="inference_completed",
            stage="inference",
        )
        proposal_hash = _sha256_text(
            inference_result.get("proposal_hash"),
            field_name="inference.proposal_hash",
        )
        replay_hash = _sha256_text(
            inference_result.get("replay_hash"),
            field_name="inference.replay_hash",
        )
        proposal_file_hash = _file_hash(proposal_output)
        inference_audit_file_hash = _file_hash(inference_audit_output)
        status["inference_status"] = "completed"
        status["proposal_hash"] = proposal_hash
        status["proposal_file_hash"] = proposal_file_hash
        status["replay_hash"] = replay_hash
        status["inference_audit_file_hash"] = inference_audit_file_hash
        stage_results = _status_stage_results(status)
        stage_results["inference"] = {
            "status": "completed",
            "proposal_path": str(proposal_output.resolve()),
            "proposal_hash": proposal_hash,
            "proposal_file_hash": proposal_file_hash,
            "replay_hash": replay_hash,
            "audit_path": str(inference_audit_output.resolve()),
            "audit_file_hash": inference_audit_file_hash,
            "coverage_bp": inference_result.get("coverage_bp"),
            "fallback_reason": inference_result.get("fallback_reason"),
        }
        status["stage_results"] = stage_results
    except Exception as exc:  # noqa: BLE001
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="inference",
            exc=exc,
        )

    try:
        post_freeze_rows: Sequence[PortfolioMLDatasetRow] = (
            _load_inference_rows(input_output)
            if promotion_reference is not None
            else ()
        )
        shadow = _run_shadow_evidence_collector(
            database_path=database_path,
            paper_state_db_path=effective_paper_state_db_path,
            run_root=run_root,
            decision_date=local_decision_at.date(),
            strict_t_minus_one=strict_t_minus_one,
            proposal_path=proposal_output,
            proposal_hash=proposal_hash,
            proposal_file_hash=proposal_file_hash,
            replay_hash=replay_hash,
            orchestration_run_hash=orchestration_run_hash,
            rule_policy_hash=policy_hash,
            release_training_manifest_file_hash=(
                release.training_manifest_file_hash
            ),
            raw_publication_manifest_hash=(
                raw.publication_manifest_hash
            ),
            inference_universe_hash=inference_universe_hash,
            promotion_reference=promotion_reference,
            model_artifact_path=(
                release.artifact_path
                if promotion_reference is not None
                else None
            ),
            post_freeze_rows=post_freeze_rows,
            post_freeze_input_hash=(
                input_hash if promotion_reference is not None else None
            ),
        )
        if shadow.get("status") != "shadow_observation_recorded":
            raise ValueError("shadow collector returned unexpected status")
        if shadow.get("observation_recorded") is not True:
            raise ValueError("shadow collector did not record an observation")
        shadow_day_credit_allowed = (
            shadow.get("shadow_day_credit_allowed") is True
        )
        if shadow.get("lane_count") != 4:
            raise ValueError("shadow collector must record four alpha lanes")
        if shadow.get("formal_oos_allowed") is not False:
            raise ValueError("shadow collector cannot authorize formal OOS")
        if shadow.get("selected_alpha_bp") != 0:
            raise ValueError("shadow collector cannot select non-zero alpha")
        if shadow.get("broker_order_allowed") is not False:
            raise ValueError("shadow collector attempted broker authority")
        status["shadow_evidence_status"] = str(
            shadow.get("evidence_status", "insufficient_evidence")
        )
        status["shadow_observation_recorded"] = True
        status["shadow_day_credit_allowed"] = shadow_day_credit_allowed
        status["shadow_observation_hash"] = _sha256_text(
            shadow.get("observation_hash"),
            field_name="shadow.observation_hash",
        )
        status["shadow_observation_path"] = _text(
            shadow.get("observation_path"),
            field_name="shadow.observation_path",
        )
        status["shadow_observation_revision"] = _integer(
            shadow.get("observation_revision"),
            field_name="shadow.observation_revision",
        )
        status["shadow_lane_count"] = _integer(
            shadow.get("lane_count"),
            field_name="shadow.lane_count",
        )
        status["shadow_evidence_hash"] = _sha256_text(
            shadow.get("evidence_hash"),
            field_name="shadow.evidence_hash",
        )
        status["shadow_evidence_path"] = _text(
            shadow.get("evidence_path"),
            field_name="shadow.evidence_path",
        )
        status["matured_shadow_observation_count"] = _integer(
            shadow.get("matured_observation_count"),
            field_name="shadow.matured_observation_count",
        )
        reference_observation_hash = shadow.get(
            "promotion_reference_observation_hash"
        )
        if reference_observation_hash is not None:
            status["promotion_reference_observation_hash"] = _sha256_text(
                reference_observation_hash,
                field_name="shadow.promotion_reference_observation_hash",
            )
        current_distribution_hash = shadow.get(
            "promotion_current_distribution_hash"
        )
        if current_distribution_hash is not None:
            status["promotion_current_distribution_hash"] = _sha256_text(
                current_distribution_hash,
                field_name="shadow.promotion_current_distribution_hash",
            )
        reference_metrics_hash = shadow.get(
            "promotion_reference_metrics_hash"
        )
        if reference_metrics_hash is not None:
            status["promotion_reference_metrics_hash"] = _sha256_text(
                reference_metrics_hash,
                field_name="shadow.promotion_reference_metrics_hash",
            )
        compatible_evidence = shadow.get(
            "compatible_promotion_evidence_path"
        )
        if compatible_evidence is not None and not isinstance(
            compatible_evidence,
            str,
        ):
            raise ValueError(
                "compatible promotion evidence path must be a string or null"
            )
        status["compatible_promotion_evidence_path"] = (
            compatible_evidence
        )
        status["production_advice_path"] = _text(
            shadow.get("production_advice_path"),
            field_name="shadow.production_advice_path",
        )
        status["production_advice_hash"] = _sha256_text(
            shadow.get("production_advice_hash"),
            field_name="shadow.production_advice_hash",
        )
        stage_results = _status_stage_results(status)
        stage_results["shadow_evidence"] = {
            "status": "completed",
            "observation_hash": status["shadow_observation_hash"],
            "observation_path": status["shadow_observation_path"],
            "observation_revision": status[
                "shadow_observation_revision"
            ],
            "idempotent": shadow.get("observation_idempotent"),
            "lane_count": status["shadow_lane_count"],
            "lane_alphas_bp": shadow.get("lane_alphas_bp"),
            "shadow_day_credit_allowed": shadow_day_credit_allowed,
            "evidence_status": status["shadow_evidence_status"],
            "evidence_hash": status["shadow_evidence_hash"],
            "evidence_path": status["shadow_evidence_path"],
            "matured_observation_count": status[
                "matured_shadow_observation_count"
            ],
            "promotion_reference_observation_hash": status[
                "promotion_reference_observation_hash"
            ],
            "promotion_current_distribution_hash": status[
                "promotion_current_distribution_hash"
            ],
            "promotion_reference_metrics_hash": status[
                "promotion_reference_metrics_hash"
            ],
            "compatible_promotion_evidence_path": (
                compatible_evidence
            ),
            "production_advice_path": status[
                "production_advice_path"
            ],
            "production_advice_hash": status[
                "production_advice_hash"
            ],
            "writes_source_database": False,
            "broker_order_allowed": False,
        }
        status["stage_results"] = stage_results
    except Exception as exc:  # noqa: BLE001
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="shadow_evidence",
            exc=exc,
        )

    try:
        authority_inputs = _load_promotion_authority_pointer(
            pointer_path=promotion_authority_pointer_path,
            decision_at=local_decision_at,
            release_root=output_root / "release_v4",
        )
        (
            effective_model_artifact_path,
            effective_dataset_manifest_path,
        ) = _promotion_custody_inputs(
            release=release,
            requested_model_artifact_path=None,
            requested_dataset_manifest_path=None,
        )
        collector_evidence_path = (
            Path(compatible_evidence).resolve()
            if isinstance(compatible_evidence, str)
            else None
        )
        # 外部參數不再能繞過每日 collector／獨立 Authority。只有固定
        # release_v4 pointer 中、且適用本決策窗的 immutable signed custody
        # 可以取代當日尚未簽章的 collector evidence。
        del evidence_path
        del shadow_evidence_path
        del authorization_path
        del registry_revision_path
        del oof_bundle_path
        del model_artifact_path
        del dataset_manifest_path
        if authority_inputs is not None:
            try:
                (
                    effective_model_artifact_path,
                    effective_dataset_manifest_path,
                ) = _promotion_custody_inputs(
                    release=release,
                    requested_model_artifact_path=authority_inputs[
                        "model_artifact_path"
                    ],
                    requested_dataset_manifest_path=authority_inputs[
                        "dataset_manifest_path"
                    ],
                )
            except (OSError, TypeError, ValueError) as exc:
                status["promotion_authority_pointer_rejection"] = (
                    "inference_release_custody_mismatch:"
                    f"{type(exc).__name__}"
                )
                authority_inputs = None
            else:
                collector_evidence_path = authority_inputs[
                    "evidence_path"
                ]
        promotion = _run_promotion_evaluator(
            output_root=output_root,
            decision_at=local_decision_at,
            evidence_path=collector_evidence_path,
            authorization_path=(
                authority_inputs["authorization_path"]
                if authority_inputs is not None
                else None
            ),
            calendar=calendar_service,
            registry_revision_path=(
                authority_inputs["registry_revision_path"]
                if authority_inputs is not None
                else None
            ),
            model_artifact_path=effective_model_artifact_path,
            dataset_manifest_path=effective_dataset_manifest_path,
            oof_bundle_path=(
                authority_inputs["oof_bundle_path"]
                if authority_inputs is not None
                else None
            ),
            shadow_evidence_path=(
                authority_inputs["shadow_evidence_path"]
                if authority_inputs is not None
                else (
                    Path(
                        _text(
                            status["shadow_evidence_path"],
                            field_name="status.shadow_evidence_path",
                        )
                    ).resolve()
                    if collector_evidence_path is not None
                    else None
                )
            ),
            trusted_issuer_keys=trusted_issuer_keys,
            trusted_custody_roots=trusted_custody_roots,
            trusted_custody_id=trusted_custody_id,
        )
        selected_alpha_bp, formal_oos_allowed = (
            _validate_promotion_result(promotion)
        )
        promotion_status_hash = _sha256_text(
            promotion.get("status_hash"),
            field_name="promotion.status_hash",
        )
        promotion_artifact_hash = _sha256_text(
            promotion.get("artifact_hash"),
            field_name="promotion.artifact_hash",
        )
        promotion_sidecar_hash = _sha256_text(
            promotion.get("sidecar_record_hash"),
            field_name="promotion.sidecar_record_hash",
        )
        promotion_artifact_path = Path(
            _text(
                promotion.get("artifact_path"),
                field_name="promotion.artifact_path",
            )
        ).resolve()
        promotion_sidecar_path = Path(
            _text(
                promotion.get("sidecar_path"),
                field_name="promotion.sidecar_path",
            )
        ).resolve()
        promotion_artifact_file_hash = _file_hash(
            promotion_artifact_path
        )
        promotion_sidecar_file_hash = _file_hash(
            promotion_sidecar_path
        )
        status["status"] = (
            "passed_ml_blend"
            if formal_oos_allowed
            else "passed_rule_only"
        )
        status["operation_mode"] = (
            "ml_blend_authorized"
            if formal_oos_allowed
            else "rule_only"
        )
        status["orchestration_status"] = "completed"
        status["ml_pipeline_status"] = "completed"
        status["promotion_status"] = "completed"
        status["selected_alpha_bp"] = selected_alpha_bp
        status["production_blend_alpha_bp"] = selected_alpha_bp
        status["formal_oos_allowed"] = formal_oos_allowed
        status["production_action_allowed"] = formal_oos_allowed
        status["broker_order_allowed"] = False
        status["broker_execution"] = False
        status["shadow_observation_recorded"] = True
        status["shadow_day_credit_allowed"] = bool(
            status["shadow_day_credit_allowed"]
        )
        status["failed_stage"] = None
        failed_reasons = promotion.get("failed_reasons")
        status["failed_reasons"] = (
            list(failed_reasons)
            if isinstance(failed_reasons, list)
            else []
        )
        status["promotion_status_hash"] = promotion_status_hash
        status["promotion_authority_pointer_used"] = (
            authority_inputs is not None
        )
        status["promotion_artifact_hash"] = promotion_artifact_hash
        status["promotion_artifact_file_hash"] = (
            promotion_artifact_file_hash
        )
        status["promotion_sidecar_record_hash"] = (
            promotion_sidecar_hash
        )
        status["promotion_sidecar_file_hash"] = (
            promotion_sidecar_file_hash
        )
        stage_results = _status_stage_results(status)
        stage_results["promotion"] = {
            "status": "completed",
            "promotion_status": promotion.get("status"),
            "status_hash": promotion_status_hash,
            "selected_alpha_bp": selected_alpha_bp,
            "formal_oos_allowed": formal_oos_allowed,
            "artifact_path": str(promotion_artifact_path),
            "artifact_hash": promotion_artifact_hash,
            "artifact_file_hash": promotion_artifact_file_hash,
            "sidecar_path": str(promotion_sidecar_path),
            "sidecar_record_hash": promotion_sidecar_hash,
            "sidecar_file_hash": promotion_sidecar_file_hash,
        }
        status["stage_results"] = stage_results
        return _write_status(run_root, status)
    except Exception as exc:  # noqa: BLE001
        return _fail_closed(
            run_root=run_root,
            status=status,
            stage="promotion",
            exc=exc,
        )


def _default_data_root() -> Path:
    return Path(
        os.environ.get(
            "DATA_ROOT",
            "D:/Min/Python/Project/FA_Data",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    data_root = _default_data_root()
    output_root = Path(
        os.environ.get(
            "OUTPUT_ROOT",
            str(data_root / "output"),
        )
    )
    parser = argparse.ArgumentParser(
        description=(
            "建立 bounded PIT raw publication、post-freeze input、ML proposal，"
            "再執行 fail-closed promotion evaluator。"
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=data_root / "sqlite" / "twstock.db",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=output_root,
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=Path(
            os.environ.get(
                "BALDR_ML_RELEASE_ROOT",
                str(
                    output_root
                    / "release_v4"
                    / "ml_allocation_bounded_v4_operational"
                ),
            )
        ),
    )
    parser.add_argument(
        "--paper-state-db",
        type=Path,
        default=output_root / "paper_portfolio" / "paper_portfolio.sqlite",
        help="append-only Paper ledger sidecar；決策日只讀取嚴格 T-1 快照。",
    )
    parser.add_argument(
        "--promotion-reference-pointer",
        type=Path,
        default=(
            output_root
            / "release_v4"
            / "ml_promotion_reference_v4"
            / "latest_reference.json"
        ),
        help=(
            "hash-bound frozen calibration/PSI reference pointer; "
            "missing or mismatched custody fails closed"
        ),
    )
    parser.add_argument(
        "--promotion-authorization-pointer",
        type=Path,
        default=(
            output_root
            / "release_v4"
            / "ml_promotion_authority"
            / "latest_authorization_pointer.json"
        ),
        help=(
            "DPAPI Authority 產生且適用當次決策窗的 immutable custody "
            "pointer；缺少或過期時自動維持 alpha=0"
        ),
    )
    parser.add_argument(
        "--decision-at",
        help="含時區 ISO timestamp；必須對應 Asia/Taipei 08:30。",
    )
    parser.add_argument(
        "--auto-catch-up",
        action="store_true",
        help=(
            "未明指定決策時間時，若實際 orchestration 證明下一個候選日的"
            "strict T-1 尚未就緒，只向後重試最近的已過交易日。"
        ),
    )
    parser.add_argument(
        "--raw-lookback-days",
        type=int,
        default=DEFAULT_RAW_LOOKBACK_DAYS,
    )
    parser.add_argument("--batch-size", type=int, default=2_048)
    parser.add_argument(
        "--compression-level",
        type=int,
        choices=range(0, 10),
        default=6,
        metavar="0..9",
    )
    parser.add_argument("--promotion-evidence", type=Path)
    parser.add_argument("--promotion-authorization", type=Path)
    parser.add_argument("--promotion-registry-revision", type=Path)
    parser.add_argument("--promotion-model-artifact", type=Path)
    parser.add_argument("--promotion-dataset-manifest", type=Path)
    parser.add_argument("--promotion-oof-bundle", type=Path)
    parser.add_argument("--promotion-shadow-evidence", type=Path)
    parser.add_argument(
        "--pit-machine-operational-publication",
        type=Path,
        help=(
            "可選的受控 current-day PIT sector publication；只在本次 "
            "decision_at 已達 available_at 後接入 shadow feature snapshot"
        ),
    )
    return parser


def _configure_standard_streams_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_standard_streams_utf8()
    args = build_parser().parse_args(argv)
    try:
        requested_decision_at = _parse_decision_at(args.decision_at)
        selected_decision_at = requested_decision_at
        automatic_mode = args.auto_catch_up and args.decision_at is None
        automatic_now = _taipei_now() if automatic_mode else None
        decision_selection_mode = (
            "automatic_candidate" if automatic_mode else "requested"
        )
        decision_selection_reason = (
            "scheduler_candidate" if automatic_mode else None
        )
        decision_selection_attempts: tuple[Mapping[str, object], ...] = ()
        trusted_keys, trusted_roots, trusted_custody_id = (
            _promotion_trust_configuration(output_root=args.output_root)
        )
        def _execute(
            *,
            candidate_decision_at: datetime,
            selection_mode: str,
            selection_reason: str | None,
            selection_attempts: Sequence[Mapping[str, object]],
        ) -> dict[str, object]:
            return run(
                database_path=args.database,
                output_root=args.output_root,
                release_root=args.release_root,
                paper_state_db_path=args.paper_state_db,
                decision_at=candidate_decision_at,
                decision_selection_mode=selection_mode,
                requested_decision_at=requested_decision_at,
                decision_selection_reason=selection_reason,
                decision_selection_attempts=selection_attempts,
                pit_machine_operational_path=(
                    args.pit_machine_operational_publication
                ),
                raw_lookback_days=args.raw_lookback_days,
                batch_size=args.batch_size,
                compression_level=args.compression_level,
                evidence_path=args.promotion_evidence,
                authorization_path=args.promotion_authorization,
                registry_revision_path=args.promotion_registry_revision,
                model_artifact_path=args.promotion_model_artifact,
                dataset_manifest_path=args.promotion_dataset_manifest,
                oof_bundle_path=args.promotion_oof_bundle,
                shadow_evidence_path=args.promotion_shadow_evidence,
                promotion_reference_pointer_path=(
                    args.promotion_reference_pointer
                ),
                promotion_authority_pointer_path=(
                    args.promotion_authorization_pointer
                ),
                trusted_issuer_keys=trusted_keys,
                trusted_custody_roots=trusted_roots,
                trusted_custody_id=trusted_custody_id,
            )

        payload = _execute(
            candidate_decision_at=selected_decision_at,
            selection_mode=decision_selection_mode,
            selection_reason=decision_selection_reason,
            selection_attempts=decision_selection_attempts,
        )
        if automatic_mode and automatic_now is not None:
            if _is_retryable_automatic_catch_up_failure(
                payload=payload,
                requested_decision_at=requested_decision_at,
                selected_decision_at=selected_decision_at,
                now=automatic_now,
            ):
                failure_attempt: dict[str, object] = {
                    "decision_at": selected_decision_at.isoformat(
                        timespec="seconds"
                    ),
                    "selection": "not_selected",
                    "failed_stage": payload.get("failed_stage"),
                    "failed_reasons": payload.get("failed_reasons"),
                }
                attempts: tuple[Mapping[str, object], ...] = (
                    failure_attempt,
                )
                try:
                    candidates = _automatic_previous_decision_candidates(
                        calendar=OfficialTradingCalendar(args.database),
                        requested_decision_at=requested_decision_at,
                        now=automatic_now,
                    )
                except Exception:
                    candidates = ()
                for candidate in candidates:
                    candidate_attempt: dict[str, object] = {
                        "decision_at": candidate.isoformat(
                            timespec="seconds"
                        ),
                        "selection": "selected",
                    }
                    attempts = (*attempts, candidate_attempt)
                    payload = _execute(
                        candidate_decision_at=candidate,
                        selection_mode="automatic_catch_up",
                        selection_reason=(
                            "runtime_strict_t_minus_one_not_ready"
                        ),
                        selection_attempts=attempts,
                    )
                    if not _is_retryable_automatic_catch_up_failure(
                        payload=payload,
                        requested_decision_at=requested_decision_at,
                        selected_decision_at=candidate,
                        now=automatic_now,
                    ):
                        break
                    attempts = (
                        *attempts,
                        {
                            "decision_at": candidate.isoformat(
                                timespec="seconds"
                            ),
                            "selection": "not_selected",
                            "failed_stage": payload.get("failed_stage"),
                            "failed_reasons": payload.get("failed_reasons"),
                        },
                    )
    except Exception as exc:  # noqa: BLE001 - 無法寫入 status 的啟動錯誤
        print(
            json.dumps(
                {
                    "task": TASK_NAME,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "production_blend_alpha_bp": 0,
                    "formal_oos_allowed": False,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return (
        0
        if str(payload.get("status", "")).startswith(
            ("passed_", "skipped_")
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
