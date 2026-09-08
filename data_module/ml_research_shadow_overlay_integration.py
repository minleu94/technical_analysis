"""把 official overlay 的研究 labels 接到既有 Research/PIT/Direct readback。

本模組是一個唯讀的 lineage bridge。它不重新建立 PIT、Direct 或 OOC
數值資料，也不把事後取得的 official overlay 當成決策日 feature；overlay
只作 label replay 的差異證據。公開入口會逐一驗證：

* ``ResearchShadowUnion`` manifest 與其 raw input manifest 的 hash；
* shared PIT publication 的 manifest、shared object 與 gzip content hash；
* Direct numeric manifest、年度 artifacts 與 read-only ``rows.sqlite``；
* 33 筆 overlay/replay 的來源 hash、capture time、cutoff 與逐 head label diff。

研究 union 的日期範圍可能早於 overlay，或 Direct/PIT 的股票池可能只有
部分交集。這些情況會在輸出中明確記為 coverage gap，不會補值、回填或把
partial readback 宣稱成 formal custody。輸出只含小型摘要與 hash，來源資料
一律以唯讀方式開啟。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from data_module.ml_daily_price_overlay import load_daily_price_overlay
from data_module.ml_pit_shared_block_resolver import (
    SHARED_PIT_PUBLICATION_SCHEMA_VERSION,
    load_shared_pit_publication,
)
from data_module.ml_direct_shared_block_resolver import (
    resolve_direct_year_artifact_paths,
)
from data_module.ml_research_shadow_union import PUBLICATION_SCHEMA_VERSION
from data_module.twse_historical_daily_capture import (
    TwseHistoricalCaptureError,
    load_twse_capture,
)


INTEGRATION_SCHEMA_VERSION = (
    "allocation-research-shadow-overlay-pit-direct-readback.v1"
)
INTEGRATION_MODE = "research_shadow_overlay_label_only_readback.v1"
INTEGRATION_STATUS = (
    "completed_partial_research_shadow_overlay_pit_direct_readback"
)
_SHA256_PREFIX = "sha256:"
_CHUNK_BYTES = 1 << 20
_DECISION_CLOCK = "08:30:00+08:00"


class ResearchShadowIntegrationError(ValueError):
    """研究 readback lineage 或安全邊界不成立。"""


@dataclass(frozen=True)
class ResearchShadowOverlayDirectReadbackResult:
    """已持久化的唯讀整合摘要。"""

    output_path: Path
    integration_hash: str
    overlay_row_count: int
    direct_overlay_match_count: int
    pit_overlay_match_count: int
    union_overlay_match_count: int


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ResearchShadowIntegrationError(
            f"source file cannot be read: {path}"
        ) from exc
    return _SHA256_PREFIX + digest.hexdigest()


def _required_hash(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != len(_SHA256_PREFIX) + 64
        or not value.startswith(_SHA256_PREFIX)
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ResearchShadowIntegrationError(
            f"{field_name} must be a sha256 digest"
        )
    return value


def _as_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResearchShadowIntegrationError(f"{field_name} must be an object")
    return value


def _as_list(value: object, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ResearchShadowIntegrationError(f"{field_name} must be an array")
    return value


def _read_json(path: Path, *, field_name: str) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise ResearchShadowIntegrationError(
            f"{field_name} is missing or symlinked: {resolved}"
        )
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchShadowIntegrationError(
            f"{field_name} is not readable JSON: {resolved}"
        ) from exc
    return dict(_as_mapping(value, field_name=field_name))


def _verify_embedded_hash(
    payload: Mapping[str, Any],
    *,
    field_name: str,
    hash_field: str,
) -> str:
    declared = _required_hash(payload.get(hash_field), field_name=f"{field_name}.{hash_field}")
    body = dict(payload)
    body.pop(hash_field, None)
    actual = _payload_hash(body)
    if actual != declared:
        raise ResearchShadowIntegrationError(
            f"{field_name}.{hash_field} mismatch"
        )
    return declared


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ResearchShadowIntegrationError(f"{field_name} is missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchShadowIntegrationError(
            f"{field_name} is not an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchShadowIntegrationError(
            f"{field_name} must include timezone"
        )
    return parsed


def _normalise_date(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchShadowIntegrationError(f"{field_name} is missing")
    text = value.strip()
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ResearchShadowIntegrationError(
            f"{field_name} is not a canonical date"
        ) from exc


def _decision_cutoff(decision_date: str) -> datetime:
    return _parse_timestamp(
        f"{decision_date}T{_DECISION_CLOCK}",
        field_name="decision cutoff",
    )


def _source_file_descriptor(
    path: Path,
    *,
    declared_file_hash: object | None = None,
    field_name: str,
) -> dict[str, object]:
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise ResearchShadowIntegrationError(
            f"{field_name} source is missing or symlinked: {resolved}"
        )
    actual_hash = _file_sha256(resolved)
    if declared_file_hash is not None:
        expected = _required_hash(
            declared_file_hash,
            field_name=f"{field_name}.file_sha256",
        )
        if actual_hash != expected:
            raise ResearchShadowIntegrationError(
                f"{field_name} file_sha256 mismatch"
            )
    return {
        "path": str(resolved),
        "file_sha256": actual_hash,
        "bytes": int(resolved.stat().st_size),
        "read_only": True,
    }


def _reject_output_overlap(output_path: Path, source_paths: Iterable[Path]) -> None:
    output = output_path.resolve()
    for raw_source in source_paths:
        source = raw_source.resolve()
        source_root = source if source.is_dir() else source.parent
        if output == source or source_root in output.parents:
            raise ResearchShadowIntegrationError(
                "integration output overlaps a read-only source"
            )


def _write_immutable_json(
    output_path: Path,
    payload: Mapping[str, Any],
    *,
    source_paths: Sequence[Path],
) -> Path:
    output = output_path.resolve()
    _reject_output_overlap(output, source_paths)
    encoded = (_canonical_json(dict(payload)) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.is_symlink() or not output.is_file():
            raise ResearchShadowIntegrationError(
                f"integration output is not a regular file: {output}"
            )
        if output.read_bytes() != encoded:
            raise ResearchShadowIntegrationError(
                f"immutable integration output collision: {output}"
            )
        return output
    temporary = output.with_name(
        f".{output.name}.{os.getpid()}.partial"
    )
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _verify_source_manifest_reference(
    raw_value: object,
    *,
    source_name: str,
) -> dict[str, object]:
    raw = _as_mapping(raw_value, field_name=f"union.raw_inputs.{source_name}")
    path_text = raw.get("path")
    if not isinstance(path_text, str) or not path_text.strip():
        raise ResearchShadowIntegrationError(
            f"union.raw_inputs.{source_name}.path is missing"
        )
    path = Path(path_text).resolve()
    descriptor = _source_file_descriptor(
        path,
        declared_file_hash=raw.get("manifest_file_hash"),
        field_name=f"union.raw_inputs.{source_name}",
    )
    declared_manifest_hash = raw.get("manifest_hash")
    if declared_manifest_hash is not None:
        expected_manifest_hash = _required_hash(
            declared_manifest_hash,
            field_name=f"union.raw_inputs.{source_name}.manifest_hash",
        )
        source_manifest = _read_json(
            path,
            field_name=f"union.raw_inputs.{source_name}.manifest",
        )
        actual_manifest_hash = _verify_embedded_hash(
            source_manifest,
            field_name=f"union.raw_inputs.{source_name}.manifest",
            hash_field="manifest_hash",
        )
        if actual_manifest_hash != expected_manifest_hash:
            raise ResearchShadowIntegrationError(
                f"union.raw_inputs.{source_name} manifest identity mismatch"
            )
        descriptor["manifest_hash"] = actual_manifest_hash
    if raw.get("dataset_identity_hash") is not None:
        descriptor["dataset_identity_hash"] = _required_hash(
            raw.get("dataset_identity_hash"),
            field_name=(
                f"union.raw_inputs.{source_name}.dataset_identity_hash"
            ),
        )
    return descriptor


def _load_overlay_and_replay(
    *,
    overlay_path: Path,
    label_replay_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    str,
    str,
    datetime,
    datetime,
    tuple[str, ...],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, object],
    list[Path],
]:
    overlay_resolved = overlay_path.resolve()
    replay_resolved = label_replay_path.resolve()
    try:
        overlay = load_daily_price_overlay(overlay_resolved)
    except (OSError, TypeError, ValueError) as exc:
        raise ResearchShadowIntegrationError(
            "official overlay cannot be loaded"
        ) from exc
    overlay_hash = _verify_embedded_hash(
        overlay,
        field_name="overlay",
        hash_field="overlay_hash",
    )
    overlay_scope = _as_mapping(overlay.get("scope"), field_name="overlay.scope")
    decision_date = _normalise_date(
        overlay_scope.get("date"),
        field_name="overlay.scope.date",
    )
    raw_symbols = _as_list(
        overlay_scope.get("symbols"),
        field_name="overlay.scope.symbols",
    )
    symbols = tuple(sorted({str(item).strip() for item in raw_symbols if str(item).strip()}))
    if not symbols:
        raise ResearchShadowIntegrationError("overlay symbols must not be empty")
    if overlay_scope.get("row_count") != len(symbols):
        raise ResearchShadowIntegrationError("overlay scope row_count mismatch")
    overlay_rows = _as_list(overlay.get("rows"), field_name="overlay.rows")
    if len(overlay_rows) != len(symbols):
        raise ResearchShadowIntegrationError("overlay rows are incomplete")
    overlay_by_symbol: dict[str, dict[str, Any]] = {}
    canonical_sources: list[Path] = []
    for position, raw_row in enumerate(overlay_rows):
        row = dict(_as_mapping(raw_row, field_name=f"overlay.rows[{position}]"))
        symbol = str(row.get("symbol", "")).strip()
        if symbol not in symbols or symbol in overlay_by_symbol:
            raise ResearchShadowIntegrationError(
                f"overlay row symbol is duplicated or outside scope: {symbol}"
            )
        if _normalise_date(row.get("date"), field_name=f"overlay.rows[{position}].date") != decision_date:
            raise ResearchShadowIntegrationError(
                f"overlay row date mismatch: {symbol}"
            )
        official_row = _as_mapping(
            row.get("official_row"),
            field_name=f"overlay.rows[{position}].official_row",
        )
        if str(official_row.get("symbol", "")).strip() != symbol:
            raise ResearchShadowIntegrationError(
                f"overlay official row symbol mismatch: {symbol}"
            )
        canonical_file = _as_mapping(
            row.get("canonical_file"),
            field_name=f"overlay.rows[{position}].canonical_file",
        )
        canonical_path_text = canonical_file.get("path")
        if not isinstance(canonical_path_text, str) or not canonical_path_text.strip():
            raise ResearchShadowIntegrationError(
                f"overlay canonical file path is missing: {symbol}"
            )
        canonical_path = Path(canonical_path_text).resolve()
        _source_file_descriptor(
            canonical_path,
            declared_file_hash=canonical_file.get("file_sha256"),
            field_name=f"overlay.rows[{position}].canonical_file",
        )
        canonical_sources.append(canonical_path)
        row["official_row_source_hash"] = _payload_hash(dict(official_row))
        row["overlay_row_source_hash"] = _payload_hash(
            _as_mapping(
                row.get("overlay_row"),
                field_name=f"overlay.rows[{position}].overlay_row",
            )
        )
        overlay_by_symbol[symbol] = row
    official_capture = _as_mapping(
        overlay.get("official_capture"),
        field_name="overlay.official_capture",
    )
    captured_at = _parse_timestamp(
        official_capture.get("captured_at_utc"),
        field_name="overlay.official_capture.captured_at_utc",
    )
    cutoff = _decision_cutoff(decision_date)
    if captured_at <= cutoff:
        raise ResearchShadowIntegrationError(
            "official overlay capture must be after historical decision cutoff"
        )
    if official_capture.get("historical_decision_time_available") is not False:
        raise ResearchShadowIntegrationError(
            "official overlay must remain historical_decision_time_available=false"
        )
    for field_name in ("response_sha256", "comparison_hash", "receipt_hash"):
        _required_hash(
            official_capture.get(field_name),
            field_name=f"overlay.official_capture.{field_name}",
        )

    # overlay 的 metadata 只能作索引；這裡重新讀回官方 capture 的
    # receipt/comparison/response，實際驗證每一層內容 hash 與日期/股票池，
    # 避免任意 bytes 只要自填一組一致的宣告 hash 就被當成官方佐證。
    comparison_path_text = official_capture.get("comparison_path")
    if not isinstance(comparison_path_text, str) or not comparison_path_text.strip():
        raise ResearchShadowIntegrationError(
            "overlay.official_capture.comparison_path is missing"
        )
    comparison_path = Path(comparison_path_text).resolve()
    capture_directory = comparison_path.parent
    try:
        receipt, comparison = load_twse_capture(capture_directory)
    except (OSError, TypeError, ValueError, TwseHistoricalCaptureError) as exc:
        raise ResearchShadowIntegrationError(
            "official capture receipt/comparison cannot be verified"
        ) from exc
    comparison_hash = _verify_embedded_hash(
        comparison,
        field_name="official capture comparison",
        hash_field="comparison_hash",
    )
    if comparison_hash != official_capture.get("comparison_hash"):
        raise ResearchShadowIntegrationError(
            "official capture comparison hash is not bound to overlay"
        )
    if _normalise_date(
        comparison.get("date"),
        field_name="official capture comparison.date",
    ) != decision_date:
        raise ResearchShadowIntegrationError(
            "official capture comparison date mismatch"
        )
    comparison_symbols_raw = _as_list(
        comparison.get("requested_symbols"),
        field_name="official capture comparison.requested_symbols",
    )
    comparison_symbols = tuple(
        sorted({str(item).strip() for item in comparison_symbols_raw if str(item).strip()})
    )
    if comparison_symbols != symbols:
        raise ResearchShadowIntegrationError(
            "official capture comparison symbol scope mismatch"
        )
    comparison_rows = _as_list(
        comparison.get("rows"),
        field_name="official capture comparison.rows",
    )
    if len(comparison_rows) != len(symbols):
        raise ResearchShadowIntegrationError(
            "official capture comparison rows are incomplete"
        )
    comparison_row_symbols: list[str] = []
    for position, raw_row in enumerate(comparison_rows):
        comparison_row = _as_mapping(
            raw_row,
            field_name=f"official capture comparison.rows[{position}]",
        )
        comparison_symbol = str(comparison_row.get("symbol", "")).strip()
        if (
            comparison_symbol not in symbols
            or comparison_symbol in comparison_row_symbols
        ):
            raise ResearchShadowIntegrationError(
                "official capture comparison row symbol scope mismatch"
            )
        if _normalise_date(
            comparison_row.get("date"),
            field_name=f"official capture comparison.rows[{position}].date",
        ) != decision_date:
            raise ResearchShadowIntegrationError(
                "official capture comparison row date mismatch"
            )
        comparison_row_symbols.append(comparison_symbol)
    if tuple(sorted(comparison_row_symbols)) != symbols:
        raise ResearchShadowIntegrationError(
            "official capture comparison rows do not cover requested symbols"
        )
    comparison_verification = _as_mapping(
        comparison.get("verification"),
        field_name="official capture comparison.verification",
    )
    if comparison_verification.get("official_requested_rows_present") is not True:
        raise ResearchShadowIntegrationError(
            "official capture comparison does not prove requested rows"
        )
    if comparison_verification.get("official_row_count") != len(symbols):
        raise ResearchShadowIntegrationError(
            "official capture comparison row count mismatch"
        )
    comparison_capture = _as_mapping(
        comparison.get("capture"),
        field_name="official capture comparison.capture",
    )
    if comparison_capture.get("response_sha256") != official_capture.get(
        "response_sha256"
    ):
        raise ResearchShadowIntegrationError(
            "official capture response hash is not bound to comparison"
        )
    if comparison_capture.get("historical_decision_time_available") is not False:
        raise ResearchShadowIntegrationError(
            "official capture comparison must be historical-only"
        )
    comparison_captured_at = _parse_timestamp(
        comparison_capture.get("captured_at_utc"),
        field_name="official capture comparison.capture.captured_at_utc",
    )
    if comparison_captured_at != captured_at:
        raise ResearchShadowIntegrationError(
            "official capture comparison time is not bound to overlay"
        )

    receipt_hash = _verify_embedded_hash(
        receipt,
        field_name="official capture receipt",
        hash_field="receipt_hash",
    )
    if receipt_hash != official_capture.get("receipt_hash"):
        raise ResearchShadowIntegrationError(
            "official capture receipt hash is not bound to overlay"
        )
    if comparison_capture.get("receipt_hash") != receipt_hash:
        raise ResearchShadowIntegrationError(
            "official capture receipt hash is not bound to comparison"
        )
    if receipt.get("date") != decision_date:
        raise ResearchShadowIntegrationError("official capture receipt date mismatch")
    receipt_request = _as_mapping(
        receipt.get("request"), field_name="official capture receipt.request"
    )
    receipt_parameters = _as_mapping(
        receipt_request.get("parameters"),
        field_name="official capture receipt.request.parameters",
    )
    if receipt_parameters.get("date") != decision_date.replace("-", ""):
        raise ResearchShadowIntegrationError(
            "official capture receipt request date mismatch"
        )
    receipt_safety = _as_mapping(
        receipt.get("safety"), field_name="official capture receipt.safety"
    )
    if receipt_safety.get("historical_retroactive_filtering_allowed") is not False:
        raise ResearchShadowIntegrationError(
            "official capture receipt cannot authorize retroactive filtering"
        )
    receipt_timing = _as_mapping(
        receipt.get("capture_timing"),
        field_name="official capture receipt.capture_timing",
    )
    receipt_completed_at = _parse_timestamp(
        receipt_timing.get("response_completed_at_utc"),
        field_name="official capture receipt.capture_timing.response_completed_at_utc",
    )
    if receipt_completed_at != captured_at:
        raise ResearchShadowIntegrationError(
            "official capture completion time is not bound to overlay"
        )
    receipt_path = capture_directory / "receipt.json"
    receipt_descriptor = _source_file_descriptor(
        receipt_path,
        field_name="official capture receipt",
    )
    response = _as_mapping(
        receipt.get("response"), field_name="official capture receipt.response"
    )
    response_path_text = response.get("path")
    if not isinstance(response_path_text, str) or not response_path_text.strip():
        raise ResearchShadowIntegrationError(
            "official capture response.path is missing"
        )
    response_descriptor = _source_file_descriptor(
        Path(response_path_text),
        declared_file_hash=response.get("wire_sha256"),
        field_name="official capture response",
    )
    if response_descriptor["file_sha256"] != official_capture.get("response_sha256"):
        raise ResearchShadowIntegrationError(
            "official capture response hash is not bound to overlay"
        )
    official_capture_readback: dict[str, object] = {
        "comparison": {
            **_source_file_descriptor(
                comparison_path,
                field_name="official capture comparison",
            ),
            "comparison_hash": comparison_hash,
            "date": decision_date,
            "requested_symbol_count": len(symbols),
            "official_row_count": len(comparison_rows),
        },
        "receipt": {
            **receipt_descriptor,
            "receipt_hash": receipt_hash,
            "date": decision_date,
        },
        "response": {
            **response_descriptor,
            "response_sha256": response_descriptor["file_sha256"],
        },
        "captured_at_utc": captured_at.isoformat(),
        "historical_decision_time_available": False,
    }

    replay = _read_json(replay_resolved, field_name="label replay")
    if replay.get("schema_version") != (
        "portfolio-ml-daily-price-research-label-replay.v1"
    ):
        raise ResearchShadowIntegrationError("label replay schema mismatch")
    replay_hash = _verify_embedded_hash(
        replay,
        field_name="label replay",
        hash_field="replay_hash",
    )
    for field_name in (
        "formal_training_allowed",
        "promotion_eligible",
        "historical_decision_time_available",
        "retrained",
    ):
        if replay.get(field_name) is not False:
            raise ResearchShadowIntegrationError(
                f"label replay {field_name} must remain false"
            )
    if replay.get("read_only") is not True:
        raise ResearchShadowIntegrationError("label replay must be read-only")
    replay_scope = _as_mapping(replay.get("scope"), field_name="label replay.scope")
    if _normalise_date(replay_scope.get("date"), field_name="label replay.scope.date") != decision_date:
        raise ResearchShadowIntegrationError("label replay date mismatch")
    replay_symbols_raw = _as_list(
        replay_scope.get("symbols"), field_name="label replay.scope.symbols"
    )
    replay_symbols = tuple(sorted({str(item).strip() for item in replay_symbols_raw if str(item).strip()}))
    if replay_symbols != symbols:
        raise ResearchShadowIntegrationError(
            "label replay symbol scope does not match overlay"
        )
    if replay_scope.get("row_count") != len(symbols):
        raise ResearchShadowIntegrationError("label replay row_count mismatch")
    replay_sources = _as_mapping(replay.get("sources"), field_name="label replay.sources")
    replay_overlay_source = _as_mapping(
        replay_sources.get("overlay"), field_name="label replay.sources.overlay"
    )
    if replay_overlay_source.get("overlay_hash") != overlay_hash:
        raise ResearchShadowIntegrationError(
            "label replay is bound to a different overlay hash"
        )
    overlay_file_hash = _file_sha256(overlay_resolved)
    if replay_overlay_source.get("overlay_file_sha256") != overlay_file_hash:
        raise ResearchShadowIntegrationError(
            "label replay overlay file hash mismatch"
        )
    replay_captured_at = _parse_timestamp(
        replay_overlay_source.get("captured_at_utc"),
        field_name="label replay.sources.overlay.captured_at_utc",
    )
    if replay_captured_at != captured_at:
        raise ResearchShadowIntegrationError(
            "label replay capture time is not bound to overlay"
        )
    for field_name in ("response_sha256", "comparison_hash", "receipt_hash"):
        if replay_overlay_source.get(field_name) != official_capture.get(field_name):
            raise ResearchShadowIntegrationError(
                f"label replay overlay {field_name} mismatch"
            )
    replay_rows = _as_list(replay.get("rows"), field_name="label replay.rows")
    if len(replay_rows) != len(symbols):
        raise ResearchShadowIntegrationError("label replay rows are incomplete")
    replay_by_symbol: dict[str, dict[str, Any]] = {}
    for position, raw_row in enumerate(replay_rows):
        row = dict(_as_mapping(raw_row, field_name=f"label replay.rows[{position}]"))
        symbol = str(row.get("symbol", "")).strip()
        if symbol not in symbols or symbol in replay_by_symbol:
            raise ResearchShadowIntegrationError(
                f"label replay row symbol is duplicated or outside scope: {symbol}"
            )
        if _normalise_date(row.get("decision_date"), field_name=f"label replay.rows[{position}].decision_date") != decision_date:
            raise ResearchShadowIntegrationError(
                f"label replay row date mismatch: {symbol}"
            )
        labels = _as_mapping(
            row.get("labels"), field_name=f"label replay.rows[{position}].labels"
        )
        original = dict(
            _as_mapping(
                labels.get("original"),
                field_name=f"label replay.rows[{position}].labels.original",
            )
        )
        corrected = dict(
            _as_mapping(
                labels.get("corrected"),
                field_name=f"label replay.rows[{position}].labels.corrected",
            )
        )
        changed_fields = labels.get("changed_fields")
        if not isinstance(changed_fields, list) or not all(
            isinstance(item, str) for item in changed_fields
        ):
            raise ResearchShadowIntegrationError(
                f"label replay changed_fields is invalid: {symbol}"
            )
        derived_changed_fields = sorted(
            key for key in set(original) | set(corrected)
            if original.get(key) != corrected.get(key)
        )
        if sorted(changed_fields) != derived_changed_fields:
            raise ResearchShadowIntegrationError(
                f"label replay changed_fields mismatch: {symbol}"
            )
        for field_name in ("original_source_hash", "corrected_source_hash"):
            _required_hash(
                labels.get(field_name),
                field_name=f"label replay.rows[{position}].labels.{field_name}",
            )
        row["derived_changed_fields"] = derived_changed_fields
        replay_by_symbol[symbol] = row

    source_paths: list[Path] = [overlay_resolved, replay_resolved]
    source_paths.extend(canonical_sources)
    # replay receipt 內的 reference/SQLite 與 capture comparison 也屬於唯讀
    # 輸入；若只保護 overlay/replay 本身，caller 仍可能把輸出路徑指向
    # 這些 nested source，形成誤寫來源的旁路。
    for raw_source in replay_sources.values():
        if isinstance(raw_source, Mapping):
            path_text = raw_source.get("path")
            if isinstance(path_text, str) and path_text.strip():
                source_paths.append(Path(path_text).resolve())
            replay_comparison_path_text = raw_source.get("comparison_path")
            if (
                isinstance(replay_comparison_path_text, str)
                and replay_comparison_path_text.strip()
            ):
                source_paths.append(Path(replay_comparison_path_text).resolve())
    official_comparison_path_text = official_capture.get("comparison_path")
    if (
        isinstance(official_comparison_path_text, str)
        and official_comparison_path_text.strip()
    ):
        source_paths.append(Path(official_comparison_path_text).resolve())
    source_lineage = overlay.get("source_lineage")
    if isinstance(source_lineage, Mapping):
        for key in ("sqlite_path", "canonical_daily_price_dir"):
            path_text = source_lineage.get(key)
            if isinstance(path_text, str) and path_text.strip():
                source_paths.append(Path(path_text).resolve())
    source_paths.extend((comparison_path, receipt_path, Path(response_path_text).resolve()))
    return (
        overlay,
        replay,
        decision_date,
        overlay_hash,
        captured_at,
        cutoff,
        symbols,
        overlay_by_symbol,
        replay_by_symbol,
        official_capture_readback,
        list(dict.fromkeys(source_paths)),
    )


def _load_union_readback(
    *,
    manifest_path: Path,
    decision_date: str,
    symbols: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any], list[Path]]:
    resolved = manifest_path.resolve()
    manifest = _read_json(resolved, field_name="ResearchShadowUnion manifest")
    if manifest.get("schema_version") != PUBLICATION_SCHEMA_VERSION:
        raise ResearchShadowIntegrationError("ResearchShadowUnion schema mismatch")
    manifest_hash = _verify_embedded_hash(
        manifest,
        field_name="ResearchShadowUnion manifest",
        hash_field="manifest_hash",
    )
    if manifest.get("research_only") is not True:
        raise ResearchShadowIntegrationError("ResearchShadowUnion must be research-only")
    for field_name in (
        "formal_oos_allowed",
        "production_action_allowed",
        "promotion_eligible",
        "broker_order_allowed",
        "formal_consumer_compatible",
    ):
        if manifest.get(field_name) is not False:
            raise ResearchShadowIntegrationError(
                f"ResearchShadowUnion {field_name} must remain false"
            )
    if manifest.get("production_alpha_bp") != 0:
        raise ResearchShadowIntegrationError(
            "ResearchShadowUnion production_alpha_bp must remain zero"
        )
    raw_inputs = _as_mapping(
        manifest.get("raw_inputs"),
        field_name="ResearchShadowUnion.raw_inputs",
    )
    raw_input_descriptors: dict[str, object] = {}
    source_paths: list[Path] = [resolved]
    for source_name, raw_source in raw_inputs.items():
        descriptor = _verify_source_manifest_reference(
            raw_source,
            source_name=str(source_name),
        )
        raw_input_descriptors[str(source_name)] = descriptor
        descriptor_path = Path(str(descriptor["path"]))
        source_paths.append(descriptor_path)
    shards = _as_list(manifest.get("shards"), field_name="ResearchShadowUnion.shards")
    if not shards:
        raise ResearchShadowIntegrationError("ResearchShadowUnion shards are empty")
    shard_descriptors: list[dict[str, object]] = []
    candidate_shards: list[tuple[Path, Mapping[str, Any]]] = []
    for position, raw_shard in enumerate(shards):
        shard = _as_mapping(
            raw_shard,
            field_name=f"ResearchShadowUnion.shards[{position}]",
        )
        relative_text = shard.get("path")
        if not isinstance(relative_text, str) or not relative_text.strip():
            raise ResearchShadowIntegrationError("ResearchShadowUnion shard path is missing")
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise ResearchShadowIntegrationError("ResearchShadowUnion shard path escapes root")
        shard_path = (resolved.parent / relative).resolve()
        if resolved.parent not in shard_path.parents:
            raise ResearchShadowIntegrationError("ResearchShadowUnion shard path escapes root")
        descriptor = _source_file_descriptor(
            shard_path,
            declared_file_hash=shard.get("compressed_sha256"),
            field_name=f"ResearchShadowUnion.shards[{position}]",
        )
        declared_bytes = shard.get("compressed_bytes")
        if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int):
            raise ResearchShadowIntegrationError("ResearchShadowUnion shard bytes are invalid")
        if int(shard_path.stat().st_size) != declared_bytes:
            raise ResearchShadowIntegrationError("ResearchShadowUnion shard bytes mismatch")
        shard_summary: dict[str, object] = {
            "year": int(shard.get("year", -1)),
            "path": relative.as_posix(),
            "compressed_bytes": declared_bytes,
            "compressed_sha256": descriptor["file_sha256"],
            "content_sha256": _required_hash(
                shard.get("content_sha256"),
                field_name=f"ResearchShadowUnion.shards[{position}].content_sha256",
            ),
            "sample_count": shard.get("sample_count"),
            "min_decision_date": shard.get("min_decision_date"),
            "max_decision_date": shard.get("max_decision_date"),
        }
        shard_descriptors.append(shard_summary)
        source_paths.append(shard_path)
        min_date_text = str(shard.get("min_decision_date", ""))[:10]
        max_date_text = str(shard.get("max_decision_date", ""))[:10]
        min_date = (
            _normalise_date(
                min_date_text,
                field_name=(
                    f"ResearchShadowUnion.shards[{position}].min_decision_date"
                ),
            )
            if min_date_text
            else ""
        )
        max_date = (
            _normalise_date(
                max_date_text,
                field_name=(
                    f"ResearchShadowUnion.shards[{position}].max_decision_date"
                ),
            )
            if max_date_text
            else ""
        )
        if min_date and max_date and min_date > max_date:
            raise ResearchShadowIntegrationError(
                f"ResearchShadowUnion shard date range is reversed: {shard_path}"
            )
        if min_date and max_date and min_date <= decision_date <= max_date:
            candidate_shards.append((shard_path, shard))

    matched_rows: dict[str, list[str]] = defaultdict(list)
    scanned_shard_count = 0
    for shard_path, _shard in candidate_shards:
        scanned_shard_count += 1
        try:
            with gzip.open(shard_path, "rt", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    try:
                        raw_row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ResearchShadowIntegrationError(
                            f"ResearchShadowUnion shard row is invalid: {shard_path}:{line_number}"
                        ) from exc
                    row = _as_mapping(
                        raw_row,
                        field_name=f"ResearchShadowUnion row {shard_path}:{line_number}",
                    )
                    # portfolio-ml-training-shards.v2 的公開 JSONL 以
                    # ``record_type=sample`` 包住實際 dataset row；舊版
                    # readback 則可能直接把 decision_date/symbol 放在列頂層。
                    # 兩種形狀都要由實際 row 取日期與股票，不能因只看
                    # envelope 而把已有的 OOS sample 誤報為零覆蓋。
                    match_row: Mapping[str, Any] = row
                    sample = row.get("sample")
                    if isinstance(sample, Mapping) and isinstance(
                        sample.get("row"), Mapping
                    ):
                        match_row = sample["row"]
                    row_date = str(
                        match_row.get(
                            "decision_date",
                            match_row.get(
                                "date",
                                match_row.get("decision_at", ""),
                            ),
                        )
                    )[:10]
                    symbol = str(
                        match_row.get(
                            "symbol",
                            match_row.get("entity_id", ""),
                        )
                    ).strip()
                    if row_date == decision_date and symbol in symbols:
                        matched_rows[symbol].append(_payload_hash(dict(row)))
        except OSError as exc:
            raise ResearchShadowIntegrationError(
                f"ResearchShadowUnion shard cannot be streamed: {shard_path}"
            ) from exc
    coverage = {
        "manifest_hash": manifest_hash,
        "manifest_file_sha256": _file_sha256(resolved),
        "dataset_id": manifest.get("dataset_id"),
        "dataset_identity_hash": _required_hash(
            manifest.get("dataset_identity_hash"),
            field_name="ResearchShadowUnion.dataset_identity_hash",
        ),
        "source_identity_hash": _required_hash(
            manifest.get("source_identity_hash"),
            field_name="ResearchShadowUnion.source_identity_hash",
        ),
        "feature_registry_hash": _required_hash(
            manifest.get("feature_registry_hash"),
            field_name="ResearchShadowUnion.feature_registry_hash",
        ),
        "training_as_of": manifest.get("training_as_of"),
        "sample_count": manifest.get("sample_count"),
        "feature_count": manifest.get("feature_count"),
        "fold_count": manifest.get("fold_count"),
        "source_manifest_hashes": manifest.get("source_manifest_hashes"),
        "raw_inputs": raw_input_descriptors,
        "shard_count": len(shards),
        "shards_verified": len(shard_descriptors),
        "shards_scanned_for_overlay_date": scanned_shard_count,
        "shards": shard_descriptors,
        "overlay_date_in_union_scope": bool(candidate_shards),
        "overlay_symbol_match_count": sum(
            1 for symbol in symbols if matched_rows.get(symbol)
        ),
        "overlay_row_match_count": sum(len(rows) for rows in matched_rows.values()),
        "matched_row_hashes": {
            symbol: sorted(hashes) for symbol, hashes in sorted(matched_rows.items())
        },
        "research_only": True,
        "formal_oos_allowed": False,
    }
    return manifest, coverage, source_paths


def _scan_pit_readback(
    *,
    manifest_path: Path,
    shared_store_root: Path,
    decision_date: str,
    cutoff: datetime,
    symbols: tuple[str, ...],
) -> tuple[dict[str, Any], list[Path]]:
    resolved_manifest_path = manifest_path.resolve()
    manifest = _read_json(
        resolved_manifest_path,
        field_name="shared PIT publication manifest",
    )
    if manifest.get("schema_version") != SHARED_PIT_PUBLICATION_SCHEMA_VERSION:
        raise ResearchShadowIntegrationError("shared PIT publication schema mismatch")
    manifest_hash = _verify_embedded_hash(
        manifest,
        field_name="shared PIT publication manifest",
        hash_field="manifest_hash",
    )
    semantic = _as_mapping(
        manifest.get("semantic_contract"),
        field_name="shared PIT semantic_contract",
    )
    feature_contract_hash = _required_hash(
        semantic.get("feature_contract_hash"),
        field_name="shared PIT semantic_contract.feature_contract_hash",
    )
    maturity_policy = semantic.get("maturity_policy")
    lane = semantic.get("lane")
    if not isinstance(maturity_policy, str) or not maturity_policy.strip():
        raise ResearchShadowIntegrationError("shared PIT maturity policy is missing")
    if not isinstance(lane, str) or not lane.strip():
        raise ResearchShadowIntegrationError("shared PIT lane is missing")
    try:
        resolved_shards = load_shared_pit_publication(
            manifest_path=resolved_manifest_path,
            shared_store_root=shared_store_root.resolve(),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ResearchShadowIntegrationError(
            "shared PIT publication cannot be loaded"
        ) from exc
    raw_shards = _as_list(manifest.get("shards"), field_name="shared PIT shards")
    if len(raw_shards) != len(resolved_shards):
        raise ResearchShadowIntegrationError("shared PIT shard count mismatch")
    by_symbol: dict[str, dict[str, Any]] = {
        symbol: {
            "matched_row_count": 0,
            "available_before_decision_count": 0,
            "families": [],
            "source_ids": [],
            "source_row_hashes": [],
            "available_at_min": None,
            "available_at_max": None,
        }
        for symbol in symbols
    }
    source_paths: list[Path] = [resolved_manifest_path, shared_store_root.resolve()]
    scanned_shard_summaries: list[dict[str, object]] = []
    for raw_shard, resolved_shard in zip(raw_shards, resolved_shards):
        shard = _as_mapping(raw_shard, field_name="shared PIT shard")
        year = int(shard.get("year", -1))
        source_path = str(shard.get("source_path", ""))
        row_count = 0
        try:
            with gzip.open(resolved_shard.path, "rt", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    try:
                        raw_row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ResearchShadowIntegrationError(
                            f"shared PIT row is invalid: {resolved_shard.path}:{line_number}"
                        ) from exc
                    row = _as_mapping(
                        raw_row,
                        field_name=f"shared PIT row {resolved_shard.path}:{line_number}",
                    )
                    row_count += 1
                    symbol = str(row.get("entity_id", "")).strip()
                    event_at = row.get("event_at")
                    if symbol not in by_symbol or not isinstance(event_at, str):
                        continue
                    try:
                        event_datetime = _parse_timestamp(
                            event_at,
                            field_name="shared PIT row.event_at",
                        )
                    except ResearchShadowIntegrationError:
                        continue
                    if event_datetime.date().isoformat() != decision_date:
                        continue
                    summary = by_symbol[symbol]
                    summary["matched_row_count"] = int(summary["matched_row_count"]) + 1
                    source_hashes = list(summary["source_row_hashes"])
                    source_hashes.append(_payload_hash(dict(row)))
                    summary["source_row_hashes"] = sorted(source_hashes)
                    families = set(str(item) for item in summary["families"])
                    if row.get("family") is not None:
                        families.add(str(row.get("family")))
                    summary["families"] = sorted(families)
                    source_ids = set(str(item) for item in summary["source_ids"])
                    if row.get("source_id") is not None:
                        source_ids.add(str(row.get("source_id")))
                    summary["source_ids"] = sorted(source_ids)
                    available_at = row.get("available_at")
                    if isinstance(available_at, str) and available_at.strip():
                        available_datetime = _parse_timestamp(
                            available_at,
                            field_name="shared PIT row.available_at",
                        )
                        if available_datetime <= cutoff:
                            summary["available_before_decision_count"] = int(
                                summary["available_before_decision_count"]
                            ) + 1
                        available_texts = [
                            value
                            for value in (
                                summary["available_at_min"],
                                summary["available_at_max"],
                                available_at,
                            )
                            if isinstance(value, str)
                        ]
                        parsed_texts = sorted(
                            available_texts,
                            key=lambda text: _parse_timestamp(
                                text,
                                field_name="shared PIT available_at",
                            ),
                        )
                        summary["available_at_min"] = parsed_texts[0]
                        summary["available_at_max"] = parsed_texts[-1]
        except OSError as exc:
            raise ResearchShadowIntegrationError(
                f"shared PIT shard cannot be streamed: {resolved_shard.path}"
            ) from exc
        scanned_shard_summaries.append(
            {
                "year": year,
                "source_path": source_path,
                "compressed_sha256": resolved_shard.compressed_sha256,
                "content_sha256": resolved_shard.content_sha256,
                "compressed_bytes": resolved_shard.compressed_bytes,
                "shared": resolved_shard.shared,
                "streamed_row_count": row_count,
            }
        )
    for summary in by_symbol.values():
        summary["feature_rows_can_be_decision_inputs"] = (
            int(summary["available_before_decision_count"]) > 0
        )
    coverage = {
        "manifest_hash": manifest_hash,
        "manifest_file_sha256": _file_sha256(resolved_manifest_path),
        "manifest_path": str(resolved_manifest_path),
        "shared_store_root": str(shared_store_root.resolve()),
        "dataset_id": manifest.get("dataset_id"),
        "publication_id": manifest.get("publication_id"),
        "source": manifest.get("source"),
        "consumer_dataset_manifest": manifest.get("consumer_dataset_manifest"),
        "feature_contract_hash": feature_contract_hash,
        "label_contract_hash": semantic.get("label_contract_hash"),
        "maturity_policy": maturity_policy,
        "lane": lane,
        "shard_count": len(resolved_shards),
        "shards": scanned_shard_summaries,
        "per_symbol": by_symbol,
        "overlay_symbol_match_count": sum(
            1 for summary in by_symbol.values() if int(summary["matched_row_count"]) > 0
        ),
        "overlay_row_match_count": sum(
            int(summary["matched_row_count"]) for summary in by_symbol.values()
        ),
        "available_before_decision_row_count": sum(
            int(summary["available_before_decision_count"])
            for summary in by_symbol.values()
        ),
        "same_day_overlay_used_as_decision_features": False,
        "readback_only_when_available_after_cutoff": True,
    }
    return coverage, source_paths


def _load_direct_readback(
    *,
    manifest_path: Path,
    decision_date: str,
    cutoff: datetime,
    symbols: tuple[str, ...],
    shared_store_root: Path | None,
) -> tuple[dict[str, Any], list[Path]]:
    resolved_manifest_path = manifest_path.resolve()
    manifest = _read_json(
        resolved_manifest_path,
        field_name="Direct numeric manifest",
    )
    if manifest.get("schema_version") != "portfolio-ml-ooc-store.v3":
        raise ResearchShadowIntegrationError("Direct numeric manifest schema mismatch")
    manifest_hash = _verify_embedded_hash(
        manifest,
        field_name="Direct numeric manifest",
        hash_field="manifest_hash",
    )
    if manifest.get("status") != "complete":
        raise ResearchShadowIntegrationError("Direct numeric manifest is not complete")
    if manifest.get("formal_source_only") is not True:
        raise ResearchShadowIntegrationError(
            "Direct readback source must declare formal_source_only=true"
        )
    years = _as_list(manifest.get("years"), field_name="Direct numeric years")
    target_year = int(decision_date[:4])
    year_manifest: Mapping[str, Any] | None = None
    for raw_year in years:
        candidate = _as_mapping(raw_year, field_name="Direct numeric year")
        if int(candidate.get("year", -1)) == target_year:
            year_manifest = candidate
            break
    source_paths: list[Path] = [resolved_manifest_path]
    if year_manifest is None:
        return (
            {
                "manifest_hash": manifest_hash,
                "manifest_file_sha256": _file_sha256(resolved_manifest_path),
                "manifest_path": str(resolved_manifest_path),
                "dataset_id": manifest.get("dataset_id"),
                "dataset_identity_hash": _required_hash(
                    manifest.get("dataset_identity_hash"),
                    field_name="Direct numeric dataset_identity_hash",
                ),
                "feature_registry_hash": _required_hash(
                    manifest.get("feature_registry_hash"),
                    field_name="Direct numeric feature_registry_hash",
                ),
                "training_as_of": manifest.get("training_as_of"),
                "year": target_year,
                "status": "no_year_artifact_for_decision_date",
                "overlay_symbol_match_count": 0,
                "overlay_row_match_count": 0,
                "per_symbol": {
                    symbol: {"status": "missing"} for symbol in symbols
                },
            },
            source_paths,
        )
    year_directory = resolved_manifest_path.parent / f"year={target_year:04d}"
    try:
        artifact_paths = resolve_direct_year_artifact_paths(
            year_manifest,
            year_directory=year_directory,
            shared_store_root=(
                shared_store_root.resolve() if shared_store_root is not None else None
            ),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise ResearchShadowIntegrationError(
            "Direct annual artifacts cannot be resolved"
        ) from exc
    source_paths.extend(artifact_paths.values())
    rows_path = artifact_paths.get("rows.sqlite")
    if rows_path is None:
        raise ResearchShadowIntegrationError("Direct annual rows.sqlite is missing")
    connection: sqlite3.Connection | None = None
    per_symbol: dict[str, dict[str, Any]] = {}
    try:
        connection = sqlite3.connect(
            f"file:{rows_path.as_posix()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(rows)").fetchall()
        }
        required_columns = {
            "local_row_index",
            "row_id",
            "decision_at",
            "decision_date",
            "symbol",
            "portfolio_state_hash",
            "target_available_at",
            "max_label_available_at",
            "max_horizon_end_date",
            "sample_hash",
        }
        if not required_columns.issubset(columns):
            raise ResearchShadowIntegrationError(
                "Direct rows.sqlite does not expose the frozen readback columns"
            )
        rows = connection.execute(
            "SELECT local_row_index, row_id, decision_at, decision_date, symbol, "
            "portfolio_state_hash, target_available_at, max_label_available_at, "
            "max_horizon_end_date, sample_hash FROM rows "
            "WHERE decision_date=? ORDER BY symbol, local_row_index",
            (decision_date,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise ResearchShadowIntegrationError(
            "Direct rows.sqlite cannot be read-only queried"
        ) from exc
    finally:
        if connection is not None:
            connection.close()
    direct_symbols_seen: set[str] = set()
    for row in rows:
        symbol = str(row["symbol"]).strip()
        if symbol in direct_symbols_seen:
            raise ResearchShadowIntegrationError(
                f"Direct rows.sqlite has duplicate decision row: {symbol}"
            )
        direct_symbols_seen.add(symbol)
        row_decision_at = _parse_timestamp(
            row["decision_at"],
            field_name=f"Direct row {symbol}.decision_at",
        )
        if row_decision_at != cutoff:
            raise ResearchShadowIntegrationError(
                f"Direct row decision_at does not equal frozen cutoff: {symbol}"
            )
        readback_payload = {
            "local_row_index": int(row["local_row_index"]),
            "row_id": str(row["row_id"]),
            "decision_at": str(row["decision_at"]),
            "decision_date": str(row["decision_date"]),
            "symbol": symbol,
            "portfolio_state_hash": str(row["portfolio_state_hash"]),
            "target_available_at": row["target_available_at"],
            "max_label_available_at": row["max_label_available_at"],
            "max_horizon_end_date": row["max_horizon_end_date"],
            "sample_hash": str(row["sample_hash"]),
        }
        per_symbol[symbol] = {
            **readback_payload,
            "readback_row_hash": _payload_hash(readback_payload),
            "status": "matched_decision_row",
        }
    artifact_summaries: list[dict[str, object]] = []
    raw_artifacts = _as_list(
        year_manifest.get("artifacts"),
        field_name="Direct year artifacts",
    )
    for raw_artifact in raw_artifacts:
        artifact = _as_mapping(raw_artifact, field_name="Direct artifact")
        artifact_summaries.append(
            {
                "artifact_id": artifact.get("artifact_id", Path(str(artifact.get("path", ""))).name),
                "storage": artifact.get("storage", "local"),
                "path": artifact.get("path"),
                "byte_count": artifact.get("byte_count"),
                "file_sha256": artifact.get("file_sha256"),
            }
        )
    matched_symbols = [symbol for symbol in symbols if symbol in per_symbol]
    coverage = {
        "manifest_hash": manifest_hash,
        "manifest_file_sha256": _file_sha256(resolved_manifest_path),
        "manifest_path": str(resolved_manifest_path),
        "dataset_id": manifest.get("dataset_id"),
        "publication_id": manifest.get("publication_id"),
        "store_identity": manifest.get("store_identity"),
        "dataset_identity_hash": _required_hash(
            manifest.get("dataset_identity_hash"),
            field_name="Direct numeric dataset_identity_hash",
        ),
        "feature_registry_hash": _required_hash(
            manifest.get("feature_registry_hash"),
            field_name="Direct numeric feature_registry_hash",
        ),
        "source_training_manifest_hash": manifest.get("source_training_manifest_hash"),
        "training_as_of": manifest.get("training_as_of"),
        "year": target_year,
        "year_manifest_hash": _required_hash(
            year_manifest.get("manifest_hash"),
            field_name="Direct year manifest_hash",
        ),
        "year_row_count": year_manifest.get("row_count"),
        "year_feature_count": year_manifest.get("feature_count"),
        "year_feature_registry_hash": year_manifest.get("feature_registry_hash"),
        "year_source_manifest_hashes": year_manifest.get("source_manifest_hashes"),
        "carry_schema_version": year_manifest.get("carry_schema_version"),
        "artifacts": artifact_summaries,
        "rows_sqlite_path": str(rows_path),
        "rows_sqlite_file_sha256": _file_sha256(rows_path),
        "rows_sqlite_read_only": True,
        "decision_row_count": len(rows),
        "overlay_symbol_match_count": len(matched_symbols),
        "overlay_row_match_count": len(matched_symbols),
        "direct_universe_symbols": sorted(direct_symbols_seen),
        "per_symbol": {
            symbol: per_symbol.get(symbol, {"status": "missing"})
            for symbol in symbols
        },
        "numeric_features_read": False,
        "numeric_targets_read": False,
        "same_day_overlay_used_as_decision_features": False,
    }
    return coverage, source_paths


def _label_diff_summary(
    replay_by_symbol: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    field_counts: Counter[str] = Counter()
    changed_symbols: list[str] = []
    total_changed_heads = 0
    for symbol, row in sorted(replay_by_symbol.items()):
        labels = _as_mapping(row.get("labels"), field_name=f"labels[{symbol}]")
        changed_fields = row.get("derived_changed_fields")
        if not isinstance(changed_fields, list):
            raise ResearchShadowIntegrationError(
                f"derived label diff is missing: {symbol}"
            )
        if changed_fields:
            changed_symbols.append(symbol)
        total_changed_heads += len(changed_fields)
        field_counts.update(str(field) for field in changed_fields)
        del labels
    return {
        "row_count": len(replay_by_symbol),
        "changed_symbol_count": len(changed_symbols),
        "changed_symbols": changed_symbols,
        "changed_head_count": total_changed_heads,
        "changed_head_counts": dict(sorted(field_counts.items())),
        "numeric_comparison_boundary": "integer_bp_and_boolean_labels",
    }


def build_research_shadow_overlay_direct_readback(
    *,
    overlay_path: Path,
    label_replay_path: Path,
    research_union_manifest_path: Path,
    pit_manifest_path: Path,
    pit_shared_store_root: Path,
    direct_manifest_path: Path,
    output_path: Path,
    direct_shared_store_root: Path | None = None,
) -> ResearchShadowOverlayDirectReadbackResult:
    """建立 ResearchShadowUnion→PIT→Direct 的唯讀 33 筆 readback。

    ``label_replay_path`` 必須由既有
    ``build_research_label_replay_from_overlay`` 產生；本入口不重跑 label
    spool，也不把 official overlay 寫入任何 SQLite。Direct/PIT/union 僅
    回讀指定 manifest 的 hash-bound artifacts，交集不足會以 coverage gap
    保存。
    """

    (
        overlay,
        replay,
        decision_date,
        overlay_hash,
        captured_at,
        cutoff,
        symbols,
        overlay_by_symbol,
        replay_by_symbol,
        official_capture_readback,
        overlay_replay_sources,
    ) = _load_overlay_and_replay(
        overlay_path=overlay_path,
        label_replay_path=label_replay_path,
    )
    union_manifest, union_coverage, union_sources = _load_union_readback(
        manifest_path=research_union_manifest_path,
        decision_date=decision_date,
        symbols=symbols,
    )
    pit_coverage, pit_sources = _scan_pit_readback(
        manifest_path=pit_manifest_path,
        shared_store_root=pit_shared_store_root,
        decision_date=decision_date,
        cutoff=cutoff,
        symbols=symbols,
    )
    direct_coverage, direct_sources = _load_direct_readback(
        manifest_path=direct_manifest_path,
        decision_date=decision_date,
        cutoff=cutoff,
        symbols=symbols,
        shared_store_root=direct_shared_store_root,
    )

    rows: list[dict[str, object]] = []
    for symbol in symbols:
        overlay_row = overlay_by_symbol[symbol]
        replay_row = replay_by_symbol[symbol]
        labels = _as_mapping(
            replay_row.get("labels"), field_name=f"label replay.labels[{symbol}]"
        )
        pit_per_symbol = _as_mapping(
            pit_coverage["per_symbol"], field_name="PIT coverage.per_symbol"
        )
        direct_per_symbol = _as_mapping(
            direct_coverage["per_symbol"],
            field_name="Direct coverage.per_symbol",
        )
        rows.append(
            {
                "symbol": symbol,
                "decision_date": decision_date,
                "decision_cutoff": cutoff.isoformat(),
                "overlay": {
                    "date": overlay_row.get("date"),
                    "classification": overlay_row.get("classification"),
                    "differing_fields": overlay_row.get("differing_fields"),
                    "official_row": overlay_row.get("official_row"),
                    "official_row_source_hash": overlay_row.get(
                        "official_row_source_hash"
                    ),
                    "overlay_row_source_hash": overlay_row.get(
                        "overlay_row_source_hash"
                    ),
                    "canonical_file": overlay_row.get("canonical_file"),
                    "original_sqlite": overlay_row.get("original_sqlite"),
                },
                "labels": {
                    "original": labels.get("original"),
                    "corrected": labels.get("corrected"),
                    "changed_fields": replay_row.get("derived_changed_fields"),
                    "original_source_hash": labels.get("original_source_hash"),
                    "corrected_source_hash": labels.get("corrected_source_hash"),
                    "corrected_source_kind": labels.get("corrected_source_kind"),
                    "horizon_end_date": labels.get("horizon_end_date"),
                    "available_at": labels.get("available_at"),
                },
                "pit": pit_per_symbol.get(symbol),
                "direct": direct_per_symbol.get(symbol),
                "source_policy": {
                    "official_overlay_used_as_decision_features": False,
                    "same_day_overlay_used_as_decision_features": False,
                    "future_values_used_as_supervised_label_only": True,
                    "historical_decision_time_available": False,
                    "captured_at_utc": captured_at.isoformat(),
                },
            }
        )

    source_paths: list[Path] = [
        *overlay_replay_sources,
        Path(str(research_union_manifest_path)).resolve(),
        Path(str(pit_manifest_path)).resolve(),
        Path(str(pit_shared_store_root)).resolve(),
        Path(str(direct_manifest_path)).resolve(),
    ]
    source_paths.extend(union_sources)
    source_paths.extend(pit_sources)
    source_paths.extend(direct_sources)
    source_paths = list(dict.fromkeys(source_paths))

    overlay_file_descriptor = _source_file_descriptor(
        Path(str(overlay_path)),
        field_name="official overlay",
    )
    replay_file_descriptor = _source_file_descriptor(
        Path(str(label_replay_path)),
        field_name="label replay",
    )
    official_capture = _as_mapping(
        overlay.get("official_capture"),
        field_name="overlay.official_capture",
    )
    replay_sources = _as_mapping(replay.get("sources"), field_name="label replay.sources")
    replay_overlay_source = _as_mapping(
        replay_sources.get("overlay"), field_name="label replay.sources.overlay"
    )
    body: dict[str, Any] = {
        "schema_version": INTEGRATION_SCHEMA_VERSION,
        "status": INTEGRATION_STATUS,
        "integration_mode": INTEGRATION_MODE,
        "read_only": True,
        "research_only": True,
        "formal_training_allowed": False,
        "formal_oos_allowed": False,
        "formal_consumer_compatible": False,
        "promotion_eligible": False,
        "production_alpha_bp": 0,
        "broker_order_allowed": False,
        "labels_mutated": False,
        "retrained": False,
        "source_data_modified": False,
        "decision_scope": {
            "date": decision_date,
            "decision_cutoff": cutoff.isoformat(),
            "symbols": list(symbols),
            "overlay_row_count": len(symbols),
            "historical_decision_time_available": False,
            "official_capture_after_cutoff": captured_at > cutoff,
            "official_capture_at": captured_at.isoformat(),
        },
        "lineage": {
            "chain": [
                "official_overlay_candidate_label_source",
                "existing_assembler_label_replay",
                "ResearchShadowUnion_manifest_readback",
                "shared_PIT_publication_readback",
                "Direct_numeric_rows_readback",
            ],
            "label_replay_existing_pipeline": replay.get("selection", {}).get(
                "existing_pipeline"
            ),
            "same_day_overlay_as_model_feature": False,
            "numeric_features_recomputed": False,
            "numeric_targets_retrained": False,
            "coverage_gaps_are_explicit": True,
            "research_union_assembly_blockers": union_manifest.get(
                "assembly_blockers"
            ),
        },
        "sources": {
            "official_overlay": {
                **overlay_file_descriptor,
                "overlay_hash": overlay_hash,
                "official_capture": dict(official_capture),
                "official_capture_readback": official_capture_readback,
                "replay_binding": {
                    "overlay_hash": replay_overlay_source.get("overlay_hash"),
                    "overlay_file_sha256": replay_overlay_source.get(
                        "overlay_file_sha256"
                    ),
                    "response_sha256": replay_overlay_source.get("response_sha256"),
                    "comparison_hash": replay_overlay_source.get("comparison_hash"),
                    "receipt_hash": replay_overlay_source.get("receipt_hash"),
                },
            },
            "label_replay": {
                **replay_file_descriptor,
                "replay_hash": replay.get("replay_hash"),
                "schema_version": replay.get("schema_version"),
                "selection": replay.get("selection"),
                "sqlite": replay_sources.get("sqlite"),
                "reference_impact": replay_sources.get("reference_impact"),
            },
            "research_shadow_union": union_coverage,
            "shared_pit": pit_coverage,
            "direct_numeric": direct_coverage,
        },
        "coverage": {
            "overlay_row_count": len(symbols),
            "label_replay_row_count": len(replay_by_symbol),
            "union_overlay_symbol_match_count": union_coverage[
                "overlay_symbol_match_count"
            ],
            "union_overlay_row_match_count": union_coverage[
                "overlay_row_match_count"
            ],
            "pit_overlay_symbol_match_count": pit_coverage[
                "overlay_symbol_match_count"
            ],
            "pit_overlay_row_match_count": pit_coverage[
                "overlay_row_match_count"
            ],
            "pit_available_before_decision_row_count": pit_coverage[
                "available_before_decision_row_count"
            ],
            "direct_overlay_symbol_match_count": direct_coverage[
                "overlay_symbol_match_count"
            ],
            "direct_overlay_row_match_count": direct_coverage[
                "overlay_row_match_count"
            ],
            "direct_row_count_for_decision_date": direct_coverage.get(
                "decision_row_count", 0
            ),
            "coverage_interpretation": (
                "partial_readback_only; source/date intersection is not a"
                " performance or formal custody claim"
            ),
            "selected_source_manifests_readback_complete": True,
            "full_chain_scope_complete": False,
        },
        "label_diff": _label_diff_summary(replay_by_symbol),
        "rows": rows,
    }
    body["integration_hash"] = _payload_hash(body)
    output = _write_immutable_json(
        output_path,
        body,
        source_paths=source_paths,
    )
    return ResearchShadowOverlayDirectReadbackResult(
        output_path=output,
        integration_hash=str(body["integration_hash"]),
        overlay_row_count=len(symbols),
        direct_overlay_match_count=int(
            direct_coverage["overlay_symbol_match_count"]
        ),
        pit_overlay_match_count=int(pit_coverage["overlay_symbol_match_count"]),
        union_overlay_match_count=int(
            union_coverage["overlay_symbol_match_count"]
        ),
    )


__all__ = [
    "INTEGRATION_MODE",
    "INTEGRATION_SCHEMA_VERSION",
    "INTEGRATION_STATUS",
    "ResearchShadowIntegrationError",
    "ResearchShadowOverlayDirectReadbackResult",
    "build_research_shadow_overlay_direct_readback",
]
