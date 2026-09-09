"""保存台股 session-open 官方 quote bytes，供 Paper source 綁定使用。

這個 producer 只對固定的 TWSE MIS endpoint 發出有界的唯讀 GET。它保存
原始 HTTP bytes、回應 metadata 與由共用 parser 重建出的 row count；不產生
fill、不寫交易資料庫、不把 quote observation 時間冒充成交事件。Paper
consumer 在真正綁定 fill 時，仍須以同一份 capture 重新驗證股票與 reference
price。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys
import stat
import tempfile
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_daily_input_producer import (  # noqa: E402
    PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES,
    PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION,
    PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION,
    PAPER_EXECUTION_SOURCE_TIME_SEMANTICS,
    RULE_SESSION_CLOSE,
    RULE_SESSION_OPEN,
    TAIPEI,
    TWSE_MIS_STOCK_INFO_ENDPOINT,
    _canonical_json,
    _parse_twse_mis_raw_rows,
    _payload_hash,
    _sha256_bytes,
    _twse_mis_request_url,
)


PAPER_EVENT_CAPTURE_PRODUCER_VERSION = "twse-mis-session-open-capture.v1"
PAPER_EVENT_CAPTURE_BINDING_SCHEMA_VERSION = "paper-event-capture-binding.v1"
PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION = "paper-event-capture-durable.v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 30.0


class PaperEventSourceCaptureError(ValueError):
    """官方 Paper event source capture 的 fail-closed 錯誤。"""


def _utc_now() -> datetime:
    """取得實際 UTC 時鐘；測試可替換以重現慢回應的完成時刻。"""

    return datetime.now(timezone.utc)


def _read_bounded_bytes(path: Path, *, role: str) -> bytes:
    """以固定上限讀檔，避免 custody 驗證先把未知大檔載入記憶體。"""

    try:
        with path.open("rb") as stream:
            raw = stream.read(PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES + 1)
    except OSError as error:
        raise PaperEventSourceCaptureError(f"{role} 無法讀取") from error
    if len(raw) > PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES:
        raise PaperEventSourceCaptureError(f"{role} 超過 bounded bytes")
    if not raw:
        raise PaperEventSourceCaptureError(f"{role} bytes 為空")
    return raw


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperEventSourceCaptureError(f"{field} 必須帶時區")
    return value.astimezone(timezone.utc)


def _validate_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for value in symbols:
        if not isinstance(value, str):
            raise PaperEventSourceCaptureError("symbols 必須是文字")
        code = value.strip()
        if len(code) != 4 or not code.isdigit():
            raise PaperEventSourceCaptureError(
                f"只支援四碼 TWSE 股票代號:{code}"
            )
        normalized.add(code)
    if not normalized:
        raise PaperEventSourceCaptureError("symbols 不得為空")
    return tuple(sorted(normalized))


def _require_temp_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temp_root)
    except ValueError as error:
        raise PaperEventSourceCaptureError(
            "Paper event capture output 必須位於系統 TEMP"
        ) from error
    if resolved == temp_root or resolved.is_symlink():
        raise PaperEventSourceCaptureError(
            "Paper event capture output 必須是 TEMP 下的獨立目錄"
        )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise PaperEventSourceCaptureError(
                "Paper event capture output 必須是全新空目錄"
            )
    else:
        try:
            resolved.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise PaperEventSourceCaptureError(
                "Paper event capture output 目錄建立失敗"
            ) from error
    return resolved


def _write_create_only_bytes(path: Path, raw: bytes, role: str) -> str:
    """以 fsync + hard-link 寫入，避免 crash 留下正式半檔或競態覆寫。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as error:
            raise PaperEventSourceCaptureError(
                f"{role} 既有檔案無法讀取"
            ) from error
        if existing == raw:
            return _sha256_bytes(existing)
        raise PaperEventSourceCaptureError(f"{role} 既有 bytes 不一致")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem[:24]}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor_open = False
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as error:
                raise PaperEventSourceCaptureError(
                    f"{role} 競態後既有檔案無法讀取"
                ) from error
            if existing != raw:
                raise PaperEventSourceCaptureError(f"{role} 競態 bytes 不一致")
    except OSError as error:
        raise PaperEventSourceCaptureError(f"{role} 發布失敗") from error
    finally:
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise PaperEventSourceCaptureError(f"{role} 暫存清理失敗") from error
    return _sha256_bytes(raw)


def _response_headers(response: object) -> tuple[str, str | None]:
    headers = getattr(response, "headers", None)
    if headers is None:
        return "application/json", None
    content_type_value = headers.get("Content-Type")
    encoding_value = headers.get("Content-Encoding")
    content_type = (
        str(content_type_value)
        if content_type_value is not None
        else "application/json"
    )
    encoding = None if encoding_value is None else str(encoding_value)
    return content_type, encoding


def _fetch_raw_response(
    request_url: str,
    *,
    timeout_seconds: float,
    fetcher: Callable[[Request, float], object],
) -> tuple[bytes, dict[str, object], datetime]:
    request = Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "technical-analysis-paper-event-capture/1.0",
        },
        method="GET",
    )
    try:
        response_context = fetcher(request, timeout_seconds)
        with cast(Any, response_context) as response:
            status = getattr(response, "status", None)
            final_url = response.geturl()
            content_type, content_encoding = _response_headers(response)
            raw = response.read(PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES + 1)
            # Timestamp after response.read() completes.  This is deliberately
            # separate from the caller's start/observation clock so a slow
            # official response cannot be recorded as an earlier capture.
            completed_at = _utc_now()
    except (OSError, HTTPError, URLError) as error:
        raise PaperEventSourceCaptureError(
            f"TWSE MIS bounded GET 失敗:{type(error).__name__}"
        ) from error
    if isinstance(status, bool) or status != 200:
        raise PaperEventSourceCaptureError("TWSE MIS HTTP status 不是 200")
    if final_url != request_url:
        raise PaperEventSourceCaptureError(
            "TWSE MIS response final URL 與固定 request 不一致"
        )
    if not isinstance(raw, bytes) or not raw:
        raise PaperEventSourceCaptureError("TWSE MIS response bytes 為空")
    if len(raw) > PAPER_EXECUTION_EVENT_CAPTURE_MAX_BYTES:
        raise PaperEventSourceCaptureError("TWSE MIS response 超過 bounded bytes")
    if content_encoding not in {None, "", "identity"}:
        raise PaperEventSourceCaptureError(
            "TWSE MIS response 使用不支援的 content encoding"
        )
    return raw, {
        "http_status": status,
        "final_url": final_url,
        "content_type": content_type,
        "content_encoding": content_encoding,
    }, completed_at


def capture_twse_session_open_prices(
    *,
    symbols: Sequence[str],
    execution_date: date,
    output_dir: Path,
    now: datetime | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[[Request, float], object] | None = None,
) -> dict[str, object]:
    """在當日台北 regular session 內保存 TWSE MIS session-open quote capture。

    ``now`` 僅供隔離測試注入；正式 CLI 不暴露此參數，會使用真實完成時間。
    它不建立 Paper fill，也不聲稱 execution event 已由 quote source 證明。
    """

    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise PaperEventSourceCaptureError("timeout_seconds 必須是數字")
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise PaperEventSourceCaptureError("timeout_seconds 超出 0..30 秒界線")
    if not isinstance(execution_date, date):
        raise PaperEventSourceCaptureError("execution_date 必須是 date")
    local_now = _aware(now or _utc_now(), "now").astimezone(TAIPEI)
    if local_now.date() != execution_date:
        raise PaperEventSourceCaptureError(
            "capture 必須在 execution_date 當日台北時區執行"
        )
    local_time = local_now.timetz().replace(tzinfo=None)
    if not RULE_SESSION_OPEN <= local_time < RULE_SESSION_CLOSE:
        raise PaperEventSourceCaptureError(
            "capture 必須位於台北 09:00..13:30 regular session"
        )
    normalized_symbols = _validate_symbols(symbols)
    output_root = _require_temp_directory(output_dir)
    request_channels = "|".join(
        f"tse_{symbol}.tw" for symbol in normalized_symbols
    )
    request_url = _twse_mis_request_url(request_channels)
    raw, response, completed_at = _fetch_raw_response(
        request_url,
        timeout_seconds=float(timeout_seconds),
        fetcher=(fetcher or cast(Callable[[Request, float], object], urlopen)),
    )
    captured_at = _aware(now or completed_at, "captured_at")
    captured_local = captured_at.astimezone(TAIPEI)
    captured_time = captured_local.timetz().replace(tzinfo=None)
    if (
        captured_local.date() != execution_date
        or not RULE_SESSION_OPEN <= captured_time < RULE_SESSION_CLOSE
    ):
        raise PaperEventSourceCaptureError(
            "capture completion 必須位於 execution_date 當日台北 "
            "09:00..13:30 regular session"
        )
    event_at = datetime.combine(
        execution_date,
        RULE_SESSION_OPEN,
        tzinfo=TAIPEI,
    ).astimezone(timezone.utc)
    rows, parse_reason = _parse_twse_mis_raw_rows(
        raw,
        request_channels=request_channels,
        execution_date=execution_date,
        captured_at=captured_at,
    )
    if parse_reason is not None:
        raise PaperEventSourceCaptureError(parse_reason)
    raw_hash = _sha256_bytes(raw)
    raw_path = output_root / "raw_response.bin"
    _write_create_only_bytes(raw_path, raw, "TWSE MIS raw response")
    body: dict[str, object] = {
        "schema_version": PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION,
        "producer": "data_module.paper_event_source_capture",
        "producer_version": PAPER_EVENT_CAPTURE_PRODUCER_VERSION,
        "source_authority": "twse",
        "source_url": TWSE_MIS_STOCK_INFO_ENDPOINT,
        "source_kind": "official_session_open_capture",
        "parser": PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION,
        "source_time_semantics": PAPER_EXECUTION_SOURCE_TIME_SEMANTICS,
        "request": {
            "ex_ch": request_channels,
            "json": "1",
            "delay": "0",
        },
        "response": response,
        "execution_date": execution_date.isoformat(),
        # 這是 Paper 模擬採用的 session-open 事件；raw tlong/t 仍保留每檔
        # quote observation，不能被解讀成這個 simulated event 的成交時間。
        "execution_event_at": event_at.isoformat(),
        "capture_window": {
            "start_at": event_at.isoformat(),
            "end_at": captured_at.isoformat(),
        },
        "captured_at": captured_at.isoformat(),
        "raw_response_path": raw_path.name,
        "raw_response_sha256": raw_hash,
        "raw_response_bytes": len(raw),
        "raw_row_count": len(rows),
    }
    payload = {**body, "content_sha256": _payload_hash(body)}
    capture_raw = (_canonical_json(payload) + "\n").encode("utf-8")
    capture_path = output_root / "capture.json"
    capture_file_hash = _write_create_only_bytes(
        capture_path,
        capture_raw,
        "TWSE MIS capture envelope",
    )
    if _sha256_bytes(raw_path.read_bytes()) != raw_hash:
        raise PaperEventSourceCaptureError("TWSE MIS raw response readback hash mismatch")
    if _sha256_bytes(capture_path.read_bytes()) != capture_file_hash:
        raise PaperEventSourceCaptureError("TWSE MIS capture envelope readback hash mismatch")
    market_source = {
        "execution_event_time_proven": False,
        "execution_source_capture_at_proven": True,
        "intraday_open_availability_proven": True,
        "execution_source_kind": "official_session_open_capture",
        "execution_data_availability": "same_session_intraday_capture",
        "execution_source_time_semantics": PAPER_EXECUTION_SOURCE_TIME_SEMANTICS,
        "execution_date": execution_date.isoformat(),
        "execution_source_capture_schema_version": (
            PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION
        ),
        "execution_source_parser_version": PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION,
        "execution_source_authority": "twse",
        "execution_source_url": TWSE_MIS_STOCK_INFO_ENDPOINT,
        "execution_source_request_url": request_url,
        "execution_source_capture_path": str(capture_path.resolve()),
        "execution_source_capture_file_hash": capture_file_hash,
        "execution_source_capture_content_hash": payload["content_sha256"],
        "execution_source_capture_row_count": len(rows),
        "execution_source_raw_response_path": str(raw_path.resolve()),
        "execution_source_raw_response_hash": raw_hash,
        "execution_event_at": event_at.isoformat(),
        "execution_source_capture_at": captured_at.isoformat(),
    }
    return {
        "status": "source_capture_ready",
        "producer": "data_module.paper_event_source_capture",
        "producer_version": PAPER_EVENT_CAPTURE_PRODUCER_VERSION,
        "capture_path": str(capture_path.resolve()),
        "capture_file_hash": capture_file_hash,
        "raw_response_path": str(raw_path.resolve()),
        "raw_response_hash": raw_hash,
        "raw_response_bytes": len(raw),
        "raw_row_count": len(rows),
        "execution_date": execution_date.isoformat(),
        "execution_event_at": event_at.isoformat(),
        "captured_at": captured_at.isoformat(),
        "market_source": market_source,
        "candidate_only": True,
        "execution_event_time_proven": False,
        "formal_eligible": False,
        "formal_credit": False,
        "broker_order_allowed": False,
        "writes_market_database": False,
        "historical_backfill_claimed": False,
    }


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == len("sha256:") + 64
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:].lower())
    )


def _strict_execution_date(value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise PaperEventSourceCaptureError("execution_date 必須是 date")
    return value


def _load_frozen_recommendation_identity(
    recommendation_path: Path,
    *,
    observed: datetime,
) -> dict[str, object]:
    """重用 Paper writer 的 frozen recommendation parser，避免自行猜 symbols。"""

    resolved = recommendation_path.expanduser().resolve()
    try:
        from data_module.paper_daily_execution_producer import (  # noqa: PLC0415
            _load_recommendation,
        )

        recommendation = _load_recommendation(resolved, observed=observed)
    except Exception as error:  # noqa: BLE001 - source boundary is fail closed
        raise PaperEventSourceCaptureError(
            "frozen recommendation 無法通過 Paper parser:"
            f"{type(error).__name__}:{error}"
        ) from error
    return {
        "path": str(recommendation.path),
        "file_hash": recommendation.file_hash,
        "content_hash": recommendation.content_hash,
        "result_id": recommendation.result_id,
        "portfolio_id": recommendation.portfolio_id,
        "profile_id": recommendation.profile_id,
        "created_at": recommendation.created_at.isoformat(),
        "decision_date": recommendation.decision_date.isoformat(),
        "symbols": [candidate.stock_code for candidate in recommendation.candidates],
        "raw_row_count": recommendation.raw_count,
    }


def _capture_source_paths(capture_result: Mapping[str, object]) -> tuple[Path, Path]:
    source = capture_result.get("market_source")
    if not isinstance(source, Mapping):
        raise PaperEventSourceCaptureError("capture result market_source 缺失")
    capture_value = source.get("execution_source_capture_path")
    raw_value = source.get("execution_source_raw_response_path")
    if not isinstance(capture_value, str) or not capture_value.strip():
        raise PaperEventSourceCaptureError("capture envelope path 缺失")
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise PaperEventSourceCaptureError("capture raw response path 缺失")
    capture_path = Path(capture_value).expanduser().resolve()
    raw_path = Path(raw_value).expanduser().resolve()
    if (
        capture_path.is_symlink()
        or raw_path.is_symlink()
        or not capture_path.is_file()
        or not raw_path.is_file()
    ):
        raise PaperEventSourceCaptureError("capture source file missing")
    return capture_path, raw_path


def _recommendation_identity_from_capture(
    capture_result: Mapping[str, object],
) -> dict[str, object]:
    value = capture_result.get("recommendation")
    if not isinstance(value, Mapping):
        raise PaperEventSourceCaptureError(
            "capture result 未綁定 frozen recommendation"
        )
    identity = {str(key): item for key, item in value.items()}
    for field in (
        "path",
        "file_hash",
        "result_id",
        "portfolio_id",
        "decision_date",
    ):
        if not isinstance(identity.get(field), str) or not str(identity[field]).strip():
            raise PaperEventSourceCaptureError(
                f"capture recommendation identity 缺少:{field}"
            )
    if not _is_sha256(identity["file_hash"]):
        raise PaperEventSourceCaptureError(
            "capture recommendation file hash invalid"
        )
    return identity


def _rebuild_partial_durable_capture(
    bucket: Path,
    *,
    expected_identity: Mapping[str, object],
    execution_date: date,
) -> dict[str, object]:
    """由 identity/raw/envelope 續寫曾在 manifest 前 crash 的 durable capture。"""

    identity_path = bucket / "identity.json"
    capture_path = bucket / "capture.json"
    raw_path = bucket / "raw_response.bin"
    identity_raw = _read_bounded_bytes(
        identity_path,
        role="partial durable capture identity",
    )
    try:
        identity_value = json.loads(identity_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError(
            "partial durable capture identity JSON invalid"
        ) from error
    if not isinstance(identity_value, Mapping):
        raise PaperEventSourceCaptureError(
            "partial durable capture identity 必須是 object"
        )
    identity_body = dict(identity_value)
    identity_hash = identity_body.pop("content_sha256", None)
    if (
        not _is_sha256(identity_hash)
        or _payload_hash(identity_body) != identity_hash
        or identity_body.get("schema_version")
        != PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION
        or identity_body.get("kind") != "recommendation_identity"
        or identity_body.get("execution_date") != execution_date.isoformat()
        or identity_body.get("recommendation") != dict(expected_identity)
    ):
        raise PaperEventSourceCaptureError(
            "partial durable capture identity content mismatch"
        )
    capture_raw = _read_bounded_bytes(capture_path, role="partial durable capture")
    raw_response = _read_bounded_bytes(
        raw_path,
        role="partial durable raw response",
    )
    try:
        capture_value = json.loads(capture_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError(
            "partial durable capture envelope JSON invalid"
        ) from error
    if not isinstance(capture_value, Mapping):
        raise PaperEventSourceCaptureError(
            "partial durable capture envelope 必須是 object"
        )
    capture_payload = {str(key): value for key, value in capture_value.items()}
    content_hash = capture_payload.get("content_sha256")
    body = dict(capture_payload)
    body.pop("content_sha256", None)
    raw_hash = capture_payload.get("raw_response_sha256")
    if (
        capture_payload.get("schema_version")
        != PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION
        or not _is_sha256(content_hash)
        or _payload_hash(body) != content_hash
        or capture_payload.get("raw_response_path") != "raw_response.bin"
        or not _is_sha256(raw_hash)
        or _sha256_bytes(raw_response) != raw_hash
        or capture_payload.get("execution_date") != execution_date.isoformat()
        or capture_payload.get("source_url") != TWSE_MIS_STOCK_INFO_ENDPOINT
        or capture_payload.get("parser")
        != PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION
        or capture_payload.get("source_time_semantics")
        != PAPER_EXECUTION_SOURCE_TIME_SEMANTICS
    ):
        raise PaperEventSourceCaptureError(
            "partial durable capture content is not source-valid"
        )
    request_value = capture_payload.get("request")
    request_channels = (
        request_value.get("ex_ch")
        if isinstance(request_value, Mapping)
        else None
    )
    if not isinstance(request_channels, str) or not request_channels:
        raise PaperEventSourceCaptureError(
            "partial durable capture request channels missing"
        )
    try:
        captured_at = _aware(
            datetime.fromisoformat(str(capture_payload.get("captured_at"))),
            "partial capture.captured_at",
        )
        event_at = _aware(
            datetime.fromisoformat(str(capture_payload.get("execution_event_at"))),
            "partial capture.execution_event_at",
        )
    except (TypeError, ValueError) as error:
        raise PaperEventSourceCaptureError(
            "partial durable capture timestamps invalid"
        ) from error
    rows, parse_reason = _parse_twse_mis_raw_rows(
        raw_response,
        request_channels=request_channels,
        execution_date=execution_date,
        captured_at=captured_at,
    )
    if parse_reason is not None:
        raise PaperEventSourceCaptureError(parse_reason)
    source = {
        "execution_event_time_proven": False,
        "execution_source_capture_at_proven": True,
        "intraday_open_availability_proven": True,
        "execution_source_kind": "official_session_open_capture",
        "execution_data_availability": "same_session_intraday_capture",
        "execution_source_time_semantics": PAPER_EXECUTION_SOURCE_TIME_SEMANTICS,
        "execution_date": execution_date.isoformat(),
        "execution_source_capture_schema_version": PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION,
        "execution_source_parser_version": PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION,
        "execution_source_authority": "twse",
        "execution_source_url": TWSE_MIS_STOCK_INFO_ENDPOINT,
        "execution_source_request_url": _twse_mis_request_url(request_channels),
        "execution_source_capture_path": str(capture_path.resolve()),
        "execution_source_capture_file_hash": _sha256_bytes(capture_raw),
        "execution_source_capture_content_hash": content_hash,
        "execution_source_capture_row_count": len(rows),
        "execution_source_raw_response_path": str(raw_path.resolve()),
        "execution_source_raw_response_hash": raw_hash,
        "execution_source_recommendation_path": expected_identity["path"],
        "execution_source_recommendation_file_hash": expected_identity["file_hash"],
        "execution_source_result_id": expected_identity["result_id"],
        "execution_source_portfolio_id": expected_identity["portfolio_id"],
        "execution_source_decision_date": expected_identity["decision_date"],
        "execution_event_at": event_at.isoformat(),
        "execution_source_capture_at": captured_at.isoformat(),
    }
    return {
        "status": "source_capture_ready",
        "schema_version": PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION,
        "producer": "data_module.paper_event_source_capture",
        "producer_version": PAPER_EVENT_CAPTURE_PRODUCER_VERSION,
        "capture_path": str(capture_path.resolve()),
        "capture_file_hash": _sha256_bytes(capture_raw),
        "raw_response_path": str(raw_path.resolve()),
        "raw_response_hash": raw_hash,
        "raw_response_bytes": len(raw_response),
        "raw_row_count": len(rows),
        "execution_date": execution_date.isoformat(),
        "execution_event_at": event_at.isoformat(),
        "captured_at": captured_at.isoformat(),
        "market_source": source,
        "recommendation": dict(expected_identity),
        "candidate_only": True,
        "execution_event_time_proven": False,
        "formal_eligible": False,
        "formal_credit": False,
        "broker_order_allowed": False,
        "writes_market_database": False,
        "historical_backfill_claimed": False,
    }


def _validate_durable_root(
    durable_root: Path,
    *,
    allowed_root: Path | None,
) -> Path:
    root = durable_root.expanduser().resolve()
    base = (allowed_root or (ROOT / "output")).expanduser().resolve()
    if root == base or root.is_symlink():
        raise PaperEventSourceCaptureError(
            "durable capture root 必須是受控 output 下的獨立目錄"
        )
    try:
        root.relative_to(base)
    except ValueError as error:
        raise PaperEventSourceCaptureError(
            "durable capture root 超出受控 output"
        ) from error
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PaperEventSourceCaptureError("durable capture root 建立失敗") from error
    return root


def _is_reparse_component(path: Path) -> bool:
    """Detect Windows junction/reparse points as well as ordinary symlinks."""

    if path.is_symlink():
        return True
    try:
        attributes = int(path.lstat().st_file_attributes)
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _reject_reparse_chain(path: Path, *, root: Path) -> None:
    """Reject an existing reparse component between root and final target."""

    current = path
    root_resolved = root.resolve()
    while True:
        if current.exists() or current.is_symlink():
            if _is_reparse_component(current):
                raise PaperEventSourceCaptureError(
                    "durable capture path contains a symlink or junction"
                )
        if current == root_resolved:
            break
        try:
            current.relative_to(root_resolved)
        except ValueError as error:
            raise PaperEventSourceCaptureError(
                "durable capture path escaped controlled root"
            ) from error
        parent = current.parent
        if parent == current:
            raise PaperEventSourceCaptureError(
                "durable capture path root traversal failed"
            )
        current = parent


def persist_twse_event_source_capture(
    capture_result: Mapping[str, object],
    *,
    durable_root: Path,
    allowed_root: Path | None = None,
) -> dict[str, object]:
    """把 session capture 以 pinned recommendation identity 持久保存。

    ``capture_result`` 只能來自本模組的 producer；目標路徑按
    ``execution_date + recommendation file hash`` 固定，既有 bytes 只接受
    exact replay。這一步仍不寫 Paper ledger，Paper writer 會在 EOD 讀取這個
    durable source，再把同一份 source metadata 放入 operational receipt。
    """

    identity = _recommendation_identity_from_capture(capture_result)
    execution_date = _strict_execution_date(
        date.fromisoformat(str(capture_result.get("execution_date")))
    )
    recommendation_file_hash = identity.get("file_hash")
    if not isinstance(recommendation_file_hash, str) or not _is_sha256(
        recommendation_file_hash
    ):  # pragma: no cover - helper guard
        raise PaperEventSourceCaptureError("recommendation file hash invalid")
    root = _validate_durable_root(durable_root, allowed_root=allowed_root)
    capture_path, raw_path = _capture_source_paths(capture_result)
    source = capture_result.get("market_source")
    if not isinstance(source, Mapping):  # pragma: no cover - helper guard
        raise PaperEventSourceCaptureError("capture result market_source 缺失")
    capture_hash = source.get("execution_source_capture_file_hash")
    raw_hash = source.get("execution_source_raw_response_hash")
    content_hash = source.get("execution_source_capture_content_hash")
    if not _is_sha256(capture_hash) or not _is_sha256(raw_hash):
        raise PaperEventSourceCaptureError("capture source hash 缺失或無效")
    if not _is_sha256(content_hash):
        raise PaperEventSourceCaptureError("capture content hash 缺失或無效")
    capture_raw = _read_bounded_bytes(capture_path, role="capture envelope")
    raw_response = _read_bounded_bytes(raw_path, role="capture raw response")
    if _sha256_bytes(capture_raw) != capture_hash:
        raise PaperEventSourceCaptureError("capture envelope file hash mismatch")
    if _sha256_bytes(raw_response) != raw_hash:
        raise PaperEventSourceCaptureError("capture raw response hash mismatch")

    # The payload's sibling path is deliberately fixed before copying so a
    # source can never point the durable envelope at an unrelated file.
    try:
        capture_payload_value = json.loads(capture_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError("capture envelope JSON invalid") from error
    if not isinstance(capture_payload_value, Mapping):
        raise PaperEventSourceCaptureError("capture envelope 必須是 object")
    capture_payload = {str(key): value for key, value in capture_payload_value.items()}
    if capture_payload.get("raw_response_path") != "raw_response.bin":
        raise PaperEventSourceCaptureError(
            "capture envelope raw_response_path 必須是 raw_response.bin"
        )
    if capture_payload.get("raw_response_sha256") != raw_hash:
        raise PaperEventSourceCaptureError("capture envelope raw hash not bound")
    if capture_payload.get("content_sha256") != content_hash:
        raise PaperEventSourceCaptureError("capture envelope content hash not bound")
    if capture_payload.get("execution_date") != execution_date.isoformat():
        raise PaperEventSourceCaptureError("capture execution date not bound")

    bucket = root / execution_date.isoformat() / recommendation_file_hash[7:23]
    _reject_reparse_chain(bucket, root=root)
    try:
        bucket.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise PaperEventSourceCaptureError(
            "durable capture identity path escaped controlled root"
        ) from error
    if bucket.is_symlink() or (bucket.exists() and not bucket.is_dir()):
        raise PaperEventSourceCaptureError("durable capture identity path invalid")
    try:
        bucket.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PaperEventSourceCaptureError("durable capture identity path unavailable") from error
    durable_capture_path = bucket / "capture.json"
    durable_raw_path = bucket / "raw_response.bin"
    durable_identity_path = bucket / "identity.json"
    durable_manifest_path = bucket / "manifest.json"
    _reject_reparse_chain(durable_identity_path, root=root)
    _reject_reparse_chain(durable_capture_path, root=root)
    _reject_reparse_chain(durable_raw_path, root=root)
    _reject_reparse_chain(durable_manifest_path, root=root)
    if durable_manifest_path.is_file():
        try:
            existing_manifest_value = json.loads(
                _read_bounded_bytes(
                    durable_manifest_path,
                    role="existing durable capture manifest",
                ).decode("utf-8")
            )
        except (UnicodeError, json.JSONDecodeError) as error:
            raise PaperEventSourceCaptureError(
                "existing durable capture manifest JSON invalid"
            ) from error
        if not isinstance(existing_manifest_value, Mapping):
            raise PaperEventSourceCaptureError(
                "existing durable capture manifest 必須是 object"
            )
        existing_identity = existing_manifest_value.get("recommendation")
        existing_hash = (
            existing_identity.get("file_hash")
            if isinstance(existing_identity, Mapping)
            else None
        )
        if existing_hash != recommendation_file_hash:
            raise PaperEventSourceCaptureError(
                "durable capture identity hash collision"
            )
        if existing_manifest_value.get("execution_date") != execution_date.isoformat():
            raise PaperEventSourceCaptureError(
                "durable capture identity date collision"
            )
    identity_body: dict[str, object] = {
        "schema_version": PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION,
        "kind": "recommendation_identity",
        "execution_date": execution_date.isoformat(),
        "recommendation": identity,
    }
    identity_payload = {
        **identity_body,
        "content_sha256": _payload_hash(identity_body),
    }
    identity_raw = (_canonical_json(identity_payload) + "\n").encode("utf-8")
    if durable_identity_path.is_file():
        try:
            existing_identity_value = json.loads(
                _read_bounded_bytes(
                    durable_identity_path,
                    role="existing durable capture identity",
                ).decode("utf-8")
            )
        except (UnicodeError, json.JSONDecodeError) as error:
            raise PaperEventSourceCaptureError(
                "existing durable capture identity JSON invalid"
            ) from error
        if not isinstance(existing_identity_value, Mapping):
            raise PaperEventSourceCaptureError(
                "existing durable capture identity 必須是 object"
            )
        existing_identity_body = dict(existing_identity_value)
        existing_identity_hash = existing_identity_body.pop("content_sha256", None)
        if (
            not _is_sha256(existing_identity_hash)
            or _payload_hash(existing_identity_body) != existing_identity_hash
            or existing_identity_body != identity_body
        ):
            raise PaperEventSourceCaptureError(
                "durable capture identity hash collision"
            )
    elif bucket.exists() and any(bucket.iterdir()):
        # A directory with payloads but without the identity sentinel cannot
        # prove which recommendation owns it.  Do not let a rare 16-char
        # namespace collision overwrite its meaning.
        raise PaperEventSourceCaptureError(
            "durable capture identity sentinel missing; refuse reuse"
        )
    identity_file_hash = _write_create_only_bytes(
        durable_identity_path,
        identity_raw,
        "durable TWSE MIS recommendation identity",
    )
    had_complete_manifest = durable_manifest_path.is_file()
    _write_create_only_bytes(
        durable_raw_path,
        raw_response,
        "durable TWSE MIS raw response",
    )
    _write_create_only_bytes(
        durable_capture_path,
        capture_raw,
        "durable TWSE MIS capture envelope",
    )
    manifest_body: dict[str, object] = {
        "schema_version": PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION,
        "producer": "data_module.paper_event_source_capture",
        "producer_version": PAPER_EVENT_CAPTURE_PRODUCER_VERSION,
        "execution_date": execution_date.isoformat(),
        "recommendation": identity,
        "identity_path": "identity.json",
        "identity_file_hash": identity_file_hash,
        "capture_path": "capture.json",
        "capture_file_hash": capture_hash,
        "raw_response_path": "raw_response.bin",
        "raw_response_hash": raw_hash,
        "raw_response_bytes": len(raw_response),
        "capture_content_hash": content_hash,
        "execution_event_at": capture_payload.get("execution_event_at"),
        "captured_at": capture_payload.get("captured_at"),
        "source_url": capture_payload.get("source_url"),
        "parser": capture_payload.get("parser"),
        "custody_semantics": "create_only_fsync_hardlink_exact_replay",
    }
    manifest_payload = {
        **manifest_body,
        "content_sha256": _payload_hash(manifest_body),
    }
    manifest_raw = (_canonical_json(manifest_payload) + "\n").encode("utf-8")
    manifest_file_hash = _write_create_only_bytes(
        durable_manifest_path,
        manifest_raw,
        "durable TWSE MIS capture manifest",
    )
    # Readback checks the durable paths rather than trusting the source TEMP
    # directory, which can disappear after the Paper EOD task starts.
    if _sha256_bytes(_read_bounded_bytes(durable_capture_path, role="durable capture")) != capture_hash:
        raise PaperEventSourceCaptureError("durable capture readback hash mismatch")
    if _sha256_bytes(_read_bounded_bytes(durable_raw_path, role="durable raw response")) != raw_hash:
        raise PaperEventSourceCaptureError("durable raw response readback hash mismatch")
    durable_source = dict(source)
    durable_source.update(
        {
            "execution_source_capture_path": str(durable_capture_path.resolve()),
            "execution_source_capture_file_hash": capture_hash,
            "execution_source_raw_response_path": str(durable_raw_path.resolve()),
            "execution_source_raw_response_hash": raw_hash,
            "execution_source_capture_manifest_path": str(
                durable_manifest_path.resolve()
            ),
            "execution_source_capture_manifest_file_hash": manifest_file_hash,
            "execution_source_capture_identity_path": str(
                durable_identity_path.resolve()
            ),
            "execution_source_capture_identity_file_hash": identity_file_hash,
            "execution_source_recommendation_path": identity["path"],
            "execution_source_recommendation_file_hash": identity["file_hash"],
            "execution_source_result_id": identity["result_id"],
        }
    )
    durable = {
        "status": "source_capture_durable",
        "schema_version": PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION,
        "root": str(root),
        "identity_path": str(bucket.resolve()),
        "recommendation_identity_path": str(durable_identity_path.resolve()),
        "recommendation_identity_file_hash": identity_file_hash,
        "capture_path": str(durable_capture_path.resolve()),
        "capture_file_hash": capture_hash,
        "raw_response_path": str(durable_raw_path.resolve()),
        "raw_response_hash": raw_hash,
        "manifest_path": str(durable_manifest_path.resolve()),
        "manifest_file_hash": manifest_file_hash,
        "recommendation": identity,
        "execution_date": execution_date.isoformat(),
        "idempotent_replay": had_complete_manifest,
        "readback_verified": True,
        "market_source": durable_source,
        "formal_credit": False,
        "broker_order_allowed": False,
    }
    return durable


def capture_twse_session_open_prices_for_recommendation(
    *,
    recommendation_path: Path,
    execution_date: date,
    output_dir: Path,
    durable_root: Path,
    now: datetime | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[[Request, float], object] | None = None,
    allowed_durable_root: Path | None = None,
    expected_recommendation_file_hash: str | None = None,
    expected_recommendation_content_hash: str | None = None,
) -> dict[str, object]:
    """以 frozen recommendation 作唯一 symbol source，完成 capture→durable custody。

    ``execution_date`` 必須由已驗證的官方 calendar caller 傳入；此函式不以
    weekday 或檔名推測下一交易日。每次 retry 使用相同 recommendation hash
    的 durable identity，若 bytes 不同便 fail closed。
    """

    execution_date = _strict_execution_date(execution_date)
    observed = _aware(now or _utc_now(), "now")
    identity = _load_frozen_recommendation_identity(
        recommendation_path,
        observed=observed,
    )
    if (
        expected_recommendation_file_hash is not None
        and identity.get("file_hash") != expected_recommendation_file_hash
    ):
        raise PaperEventSourceCaptureError(
            "frozen recommendation file hash changed during capture retry"
        )
    if (
        expected_recommendation_content_hash is not None
        and identity.get("content_hash") != expected_recommendation_content_hash
    ):
        raise PaperEventSourceCaptureError(
            "frozen recommendation content hash changed during capture retry"
        )
    decision_date = date.fromisoformat(str(identity["decision_date"]))
    if decision_date >= execution_date:
        raise PaperEventSourceCaptureError(
            "frozen recommendation decision_date 必須早於 execution_date"
        )
    recommendation_file_hash = identity.get("file_hash")
    if not isinstance(recommendation_file_hash, str) or not _is_sha256(
        recommendation_file_hash
    ):
        raise PaperEventSourceCaptureError("frozen recommendation file hash invalid")
    durable_parent = _validate_durable_root(
        durable_root,
        allowed_root=allowed_durable_root,
    )
    durable_bucket = (
        durable_parent
        / execution_date.isoformat()
        / recommendation_file_hash[7:23]
    )
    _reject_reparse_chain(durable_bucket, root=durable_parent)
    try:
        durable_bucket.resolve().relative_to(durable_parent.resolve())
    except ValueError as error:
        raise PaperEventSourceCaptureError(
            "durable capture identity path escaped controlled root"
        ) from error
    if durable_bucket.exists():
        if durable_bucket.is_symlink() or not durable_bucket.is_dir():
            raise PaperEventSourceCaptureError(
                "existing durable capture identity path invalid"
            )
        existing_manifest = durable_bucket / "manifest.json"
        if existing_manifest.is_file():
            loaded = load_persisted_twse_event_source_capture(existing_manifest)
            loaded_identity = _recommendation_identity_from_capture(loaded)
            if loaded_identity != identity:
                raise PaperEventSourceCaptureError(
                    "existing durable capture recommendation identity mismatch"
                )
            loaded["status"] = "source_capture_ready"
            loaded["producer"] = "data_module.paper_event_source_capture"
            loaded["producer_version"] = PAPER_EVENT_CAPTURE_PRODUCER_VERSION
            loaded["candidate_only"] = True
            loaded["execution_event_time_proven"] = False
            loaded["formal_eligible"] = False
            loaded["formal_credit"] = False
            loaded["broker_order_allowed"] = False
            loaded["idempotent_replay"] = True
            return loaded
        identity_sentinel = durable_bucket / "identity.json"
        partial_capture = durable_bucket / "capture.json"
        partial_raw = durable_bucket / "raw_response.bin"
        if (
            identity_sentinel.is_file()
            and partial_capture.is_file()
            and partial_raw.is_file()
        ):
            rebuilt = _rebuild_partial_durable_capture(
                durable_bucket,
                expected_identity=identity,
                execution_date=execution_date,
            )
            durable = persist_twse_event_source_capture(
                rebuilt,
                durable_root=durable_root,
                allowed_root=allowed_durable_root,
            )
            rebuilt["durable_capture"] = durable
            rebuilt["market_source"] = durable["market_source"]
            rebuilt["capture_path"] = durable["capture_path"]
            rebuilt["capture_file_hash"] = durable["capture_file_hash"]
            rebuilt["raw_response_path"] = durable["raw_response_path"]
            rebuilt["raw_response_hash"] = durable["raw_response_hash"]
            rebuilt["manifest_path"] = durable["manifest_path"]
            rebuilt["manifest_file_hash"] = durable["manifest_file_hash"]
            rebuilt["durable_readback_verified"] = durable["readback_verified"]
            rebuilt["recovered_after_manifest_failure"] = True
            rebuilt["idempotent_replay"] = True
            return rebuilt
        if any(durable_bucket.iterdir()):
            raise PaperEventSourceCaptureError(
                "existing durable capture identity is incomplete; refuse new fetch"
            )
    symbols_value = identity.get("symbols")
    if not isinstance(symbols_value, list) or not symbols_value:
        raise PaperEventSourceCaptureError("frozen recommendation symbols 缺失")
    result = capture_twse_session_open_prices(
        symbols=tuple(str(item) for item in symbols_value),
        execution_date=execution_date,
        output_dir=output_dir,
        # ``now`` is a test clock only.  Production must let the lower-level
        # fetcher stamp ``captured_at`` with its actual response completion;
        # passing the caller's start time would make a slow GET look earlier
        # than it really completed.
        now=observed if now is not None else None,
        timeout_seconds=timeout_seconds,
        fetcher=fetcher,
    )
    source = result.get("market_source")
    if not isinstance(source, Mapping):  # pragma: no cover - producer invariant
        raise PaperEventSourceCaptureError("capture market_source 缺失")
    bound_source = dict(source)
    bound_source.update(
        {
            "execution_source_recommendation_path": identity["path"],
            "execution_source_recommendation_file_hash": identity["file_hash"],
            "execution_source_result_id": identity["result_id"],
            "execution_source_portfolio_id": identity["portfolio_id"],
            "execution_source_decision_date": identity["decision_date"],
        }
    )
    result["market_source"] = bound_source
    result["recommendation"] = identity
    durable = persist_twse_event_source_capture(
        result,
        durable_root=durable_root,
        allowed_root=allowed_durable_root,
    )
    result["durable_capture"] = durable
    result["market_source"] = durable["market_source"]
    result["capture_path"] = durable["capture_path"]
    result["capture_file_hash"] = durable["capture_file_hash"]
    result["raw_response_path"] = durable["raw_response_path"]
    result["raw_response_hash"] = durable["raw_response_hash"]
    result["manifest_path"] = durable["manifest_path"]
    result["manifest_file_hash"] = durable["manifest_file_hash"]
    result["durable_readback_verified"] = durable["readback_verified"]
    return result


def load_persisted_twse_event_source_capture(
    manifest_path: Path,
) -> dict[str, object]:
    """讀取 durable capture manifest 並由 envelope/raw 重建 source metadata。"""

    manifest = manifest_path.expanduser().resolve()
    if manifest.is_symlink() or not manifest.is_file():
        raise PaperEventSourceCaptureError("durable capture manifest missing")
    manifest_raw = _read_bounded_bytes(manifest, role="durable capture manifest")
    try:
        value = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError("durable capture manifest JSON invalid") from error
    if not isinstance(value, Mapping):
        raise PaperEventSourceCaptureError("durable capture manifest 必須是 object")
    payload = {str(key): item for key, item in value.items()}
    if payload.get("schema_version") != PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION:
        raise PaperEventSourceCaptureError("durable capture manifest schema invalid")
    supplied = payload.get("content_sha256")
    body = dict(payload)
    body.pop("content_sha256", None)
    if not _is_sha256(supplied) or _payload_hash(body) != supplied:
        raise PaperEventSourceCaptureError("durable capture manifest content hash mismatch")
    identity = payload.get("recommendation")
    if not isinstance(identity, Mapping):
        raise PaperEventSourceCaptureError("durable capture recommendation identity missing")
    identity_map = {str(key): item for key, item in identity.items()}
    for field in ("path", "file_hash", "result_id", "portfolio_id", "decision_date"):
        if not isinstance(identity_map.get(field), str) or not str(identity_map[field]).strip():
            raise PaperEventSourceCaptureError(
                f"durable capture recommendation identity missing:{field}"
            )
    identity_rel = payload.get("identity_path")
    capture_rel = payload.get("capture_path")
    raw_rel = payload.get("raw_response_path")
    if (
        identity_rel != "identity.json"
        or capture_rel != "capture.json"
        or raw_rel != "raw_response.bin"
    ):
        raise PaperEventSourceCaptureError("durable capture manifest file names invalid")
    identity_path = manifest.parent / "identity.json"
    capture_path = manifest.parent / "capture.json"
    raw_path = manifest.parent / "raw_response.bin"
    identity_raw = _read_bounded_bytes(
        identity_path,
        role="durable capture identity",
    )
    identity_file_hash = payload.get("identity_file_hash")
    if not _is_sha256(identity_file_hash) or _sha256_bytes(identity_raw) != identity_file_hash:
        raise PaperEventSourceCaptureError("durable capture identity file hash mismatch")
    try:
        identity_value = json.loads(identity_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError("durable capture identity JSON invalid") from error
    if not isinstance(identity_value, Mapping):
        raise PaperEventSourceCaptureError("durable capture identity 必須是 object")
    identity_body = dict(identity_value)
    identity_hash = identity_body.pop("content_sha256", None)
    if (
        not _is_sha256(identity_hash)
        or _payload_hash(identity_body) != identity_hash
        or identity_body.get("schema_version") != PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION
        or identity_body.get("kind") != "recommendation_identity"
        or identity_body.get("execution_date") != payload.get("execution_date")
        or identity_body.get("recommendation") != identity
    ):
        raise PaperEventSourceCaptureError("durable capture identity content mismatch")
    capture_raw = _read_bounded_bytes(capture_path, role="durable capture")
    raw_response = _read_bounded_bytes(raw_path, role="durable raw response")
    capture_hash = payload.get("capture_file_hash")
    raw_hash = payload.get("raw_response_hash")
    if not _is_sha256(capture_hash) or _sha256_bytes(capture_raw) != capture_hash:
        raise PaperEventSourceCaptureError("durable capture file hash mismatch")
    if not _is_sha256(raw_hash) or _sha256_bytes(raw_response) != raw_hash:
        raise PaperEventSourceCaptureError("durable raw response hash mismatch")
    try:
        capture_value = json.loads(capture_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError("durable capture envelope JSON invalid") from error
    if not isinstance(capture_value, Mapping):
        raise PaperEventSourceCaptureError("durable capture envelope 必須是 object")
    capture_payload = {str(key): item for key, item in capture_value.items()}
    content_hash = capture_payload.get("content_sha256")
    capture_body = dict(capture_payload)
    capture_body.pop("content_sha256", None)
    if not _is_sha256(content_hash) or _payload_hash(capture_body) != content_hash:
        raise PaperEventSourceCaptureError("durable capture content hash mismatch")
    if capture_payload.get("raw_response_path") != "raw_response.bin":
        raise PaperEventSourceCaptureError("durable capture raw path is not sibling")
    if capture_payload.get("raw_response_sha256") != raw_hash:
        raise PaperEventSourceCaptureError("durable capture raw hash not bound")
    execution_date = _strict_execution_date(
        date.fromisoformat(str(payload.get("execution_date")))
    )
    if capture_payload.get("execution_date") != execution_date.isoformat():
        raise PaperEventSourceCaptureError("durable capture execution date mismatch")
    try:
        captured_at = _aware(
            datetime.fromisoformat(str(capture_payload.get("captured_at"))),
            "capture.captured_at",
        )
        event_at = _aware(
            datetime.fromisoformat(str(capture_payload.get("execution_event_at"))),
            "capture.execution_event_at",
        )
    except (TypeError, ValueError) as error:
        raise PaperEventSourceCaptureError("durable capture timestamps invalid") from error
    request = capture_payload.get("request")
    request_channels = request.get("ex_ch") if isinstance(request, Mapping) else None
    if not isinstance(request_channels, str) or not request_channels:
        raise PaperEventSourceCaptureError("durable capture request channels missing")
    rows, parse_reason = _parse_twse_mis_raw_rows(
        raw_response,
        request_channels=request_channels,
        execution_date=execution_date,
        captured_at=captured_at,
    )
    if parse_reason is not None:
        raise PaperEventSourceCaptureError(parse_reason)
    source = {
        "execution_event_time_proven": False,
        "execution_source_capture_at_proven": True,
        "intraday_open_availability_proven": True,
        "execution_source_kind": "official_session_open_capture",
        "execution_data_availability": "same_session_intraday_capture",
        "execution_source_time_semantics": PAPER_EXECUTION_SOURCE_TIME_SEMANTICS,
        "execution_date": execution_date.isoformat(),
        "execution_source_capture_schema_version": PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION,
        "execution_source_parser_version": PAPER_EXECUTION_EVENT_CAPTURE_PARSER_VERSION,
        "execution_source_authority": "twse",
        "execution_source_url": TWSE_MIS_STOCK_INFO_ENDPOINT,
        "execution_source_request_url": _twse_mis_request_url(request_channels),
        "execution_source_capture_path": str(capture_path.resolve()),
        "execution_source_capture_file_hash": capture_hash,
        "execution_source_capture_content_hash": content_hash,
        "execution_source_capture_row_count": len(rows),
        "execution_source_raw_response_path": str(raw_path.resolve()),
        "execution_source_raw_response_hash": raw_hash,
        "execution_source_capture_manifest_path": str(manifest),
        "execution_source_capture_manifest_file_hash": _sha256_bytes(manifest_raw),
        "execution_source_capture_identity_path": str(identity_path.resolve()),
        "execution_source_capture_identity_file_hash": identity_file_hash,
        "execution_source_recommendation_path": identity_map["path"],
        "execution_source_recommendation_file_hash": identity_map["file_hash"],
        "execution_source_result_id": identity_map["result_id"],
        "execution_source_portfolio_id": identity_map["portfolio_id"],
        "execution_source_decision_date": identity_map["decision_date"],
        "execution_event_at": event_at.isoformat(),
        "execution_source_capture_at": captured_at.isoformat(),
    }
    durable = {
        "status": "source_capture_durable",
        "schema_version": PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION,
        "identity_path": str(manifest.parent.resolve()),
        "recommendation_identity_path": str(identity_path.resolve()),
        "recommendation_identity_file_hash": identity_file_hash,
        "capture_path": str(capture_path.resolve()),
        "capture_file_hash": capture_hash,
        "raw_response_path": str(raw_path.resolve()),
        "raw_response_hash": raw_hash,
        "manifest_path": str(manifest),
        "manifest_file_hash": _sha256_bytes(manifest_raw),
        "recommendation": identity_map,
        "execution_date": execution_date.isoformat(),
        "idempotent_replay": True,
        "readback_verified": True,
        "market_source": source,
        "formal_credit": False,
        "broker_order_allowed": False,
    }
    return {
        "status": "source_capture_durable",
        "schema_version": PAPER_EXECUTION_EVENT_CAPTURE_SCHEMA_VERSION,
        "execution_date": execution_date.isoformat(),
        "capture_path": str(capture_path.resolve()),
        "capture_file_hash": capture_hash,
        "raw_response_path": str(raw_path.resolve()),
        "raw_response_hash": raw_hash,
        "manifest_path": str(manifest),
        "manifest_file_hash": _sha256_bytes(manifest_raw),
        "recommendation": identity_map,
        "market_source": source,
        "durable_capture": durable,
        "formal_credit": False,
        "broker_order_allowed": False,
    }


def resolve_persisted_twse_event_source_capture_for_recommendation(
    *,
    recommendation_path: Path,
    execution_date: date,
    durable_root: Path,
    observed: datetime | None = None,
    allowed_durable_root: Path | None = None,
) -> dict[str, object] | None:
    """以 frozen recommendation identity 讀取既有 durable session capture。

    EOD writer 不能在 session 結束後重新發出 MIS GET，也不能掃描 latest
    capture 來猜來源。這個 resolver 只使用 ``execution_date`` 與完整
    recommendation file hash 組成的固定 bucket；沒有完整 manifest 時回傳
    ``None``，由 caller 保留 Paper custody-only 結果並讓下一輪重試。
    manifest、identity、envelope 與 raw bytes 仍由既有 loader 全部重建驗證。
    """

    execution_date = _strict_execution_date(execution_date)
    observed_at = _aware(observed or _utc_now(), "observed")
    identity = _load_frozen_recommendation_identity(
        recommendation_path,
        observed=observed_at,
    )
    decision_date = date.fromisoformat(str(identity["decision_date"]))
    if decision_date >= execution_date:
        raise PaperEventSourceCaptureError(
            "frozen recommendation decision_date 必須早於 execution_date"
        )
    root = _validate_durable_root(
        durable_root,
        allowed_root=allowed_durable_root,
    )
    file_hash = identity.get("file_hash")
    if not isinstance(file_hash, str) or not _is_sha256(file_hash):
        raise PaperEventSourceCaptureError(
            "frozen recommendation file hash invalid"
        )
    bucket = root / execution_date.isoformat() / file_hash[7:23]
    _reject_reparse_chain(bucket, root=root)
    try:
        bucket.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise PaperEventSourceCaptureError(
            "durable capture identity path escaped controlled root"
        ) from error
    if not bucket.exists():
        return None
    if bucket.is_symlink() or not bucket.is_dir():
        raise PaperEventSourceCaptureError(
            "durable capture identity path invalid"
        )
    manifest = bucket / "manifest.json"
    _reject_reparse_chain(manifest, root=root)
    if not manifest.is_file():
        return None
    loaded = load_persisted_twse_event_source_capture(manifest)
    loaded_identity = _recommendation_identity_from_capture(loaded)
    if loaded_identity != identity:
        raise PaperEventSourceCaptureError(
            "durable capture recommendation identity mismatch"
        )
    if loaded.get("execution_date") != execution_date.isoformat():
        raise PaperEventSourceCaptureError(
            "durable capture execution date mismatch"
        )
    loaded["resolved_for_recommendation"] = True
    loaded["resolver_observed_at"] = observed_at.isoformat()
    durable_capture = loaded.get("durable_capture")
    loaded["readback_verified"] = (
        durable_capture.get("readback_verified") is True
        if isinstance(durable_capture, Mapping)
        else False
    )
    return loaded


def bind_paper_execution_result_to_capture(
    paper_result: Mapping[str, object],
    capture_result: Mapping[str, object],
    *,
    require_durable: bool = True,
) -> dict[str, object]:
    """把 Paper candidate 綁到同一份 durable source，交給 Formal 重驗。

    綁定只在 recommendation／execution date／每筆 fill reference price 與 raw
    MIS rows 一致時成功。`execution_event_at` 是明示的 Paper session-open
    模擬事件；它不把每檔 raw `tlong` 冒充成交時間。Formal eligibility 仍由
    `formal_daily_input_producer` 以 receipt `recorded_at` 再做完整驗證。
    """

    result = {str(key): value for key, value in paper_result.items()}
    if result.get("formal_credit") is True or result.get("broker_order_allowed") is True:
        raise PaperEventSourceCaptureError(
            "Paper source binding 不得接收已授權 credit 或 broker 結果"
        )
    paper_identity = result.get("recommendation")
    if not isinstance(paper_identity, Mapping):
        raise PaperEventSourceCaptureError("Paper result recommendation identity missing")
    capture_identity = _recommendation_identity_from_capture(capture_result)
    for field in ("path", "file_hash", "result_id", "portfolio_id", "decision_date"):
        if paper_identity.get(field) != capture_identity.get(field):
            raise PaperEventSourceCaptureError(
                f"Paper/capture recommendation identity mismatch:{field}"
            )
    execution_date_value = result.get("execution_date")
    if not isinstance(execution_date_value, str):
        raise PaperEventSourceCaptureError("Paper result execution_date missing")
    execution_date = date.fromisoformat(execution_date_value)
    if capture_result.get("execution_date") != execution_date.isoformat():
        raise PaperEventSourceCaptureError("Paper/capture execution_date mismatch")

    source: Mapping[str, object]
    if require_durable:
        durable_value = capture_result.get("durable_capture")
        if not isinstance(durable_value, Mapping):
            raise PaperEventSourceCaptureError(
                "Paper source binding requires durable capture custody"
            )
        manifest_value = durable_value.get("manifest_path")
        if not isinstance(manifest_value, str) or not manifest_value.strip():
            raise PaperEventSourceCaptureError("durable capture manifest path missing")
        loaded = load_persisted_twse_event_source_capture(Path(manifest_value))
        loaded_identity = _recommendation_identity_from_capture(loaded)
        if loaded_identity != capture_identity:
            raise PaperEventSourceCaptureError(
                "durable capture recommendation identity differs from candidate"
            )
        source_value = loaded.get("market_source")
        if not isinstance(source_value, Mapping):
            raise PaperEventSourceCaptureError("durable capture market_source missing")
        source = source_value
    else:
        source_value = capture_result.get("market_source")
        if not isinstance(source_value, Mapping):
            raise PaperEventSourceCaptureError("capture market_source missing")
        source = source_value

    source_path_value = source.get("execution_source_capture_path")
    raw_path_value = source.get("execution_source_raw_response_path")
    request_url = source.get("execution_source_request_url")
    if not isinstance(source_path_value, str) or not isinstance(raw_path_value, str):
        raise PaperEventSourceCaptureError("capture source paths missing")
    capture_path = Path(source_path_value).expanduser().resolve()
    raw_path = Path(raw_path_value).expanduser().resolve()
    capture_raw = _read_bounded_bytes(capture_path, role="Paper binding capture")
    raw_response = _read_bounded_bytes(raw_path, role="Paper binding raw response")
    if not isinstance(request_url, str) or "?" not in request_url:
        raise PaperEventSourceCaptureError("capture request URL missing")
    request = json.loads(capture_raw.decode("utf-8"))
    if not isinstance(request, Mapping):
        raise PaperEventSourceCaptureError("capture envelope invalid")
    request_value = request.get("request")
    request_channels = request_value.get("ex_ch") if isinstance(request_value, Mapping) else None
    captured_value = request.get("captured_at")
    if not isinstance(request_channels, str) or not isinstance(captured_value, str):
        raise PaperEventSourceCaptureError("capture request/window metadata missing")
    captured_at = _aware(datetime.fromisoformat(captured_value), "capture.captured_at")
    rows, parse_reason = _parse_twse_mis_raw_rows(
        raw_response,
        request_channels=request_channels,
        execution_date=execution_date,
        captured_at=captured_at,
    )
    if parse_reason is not None:
        raise PaperEventSourceCaptureError(parse_reason)
    raw_by_symbol = {str(row["stock_code"]): row for row in rows}
    fills_value = result.get("fills")
    if not isinstance(fills_value, list):
        raise PaperEventSourceCaptureError("Paper result fills missing")
    reference_prices: dict[str, str] = {}
    for item in fills_value:
        if not isinstance(item, Mapping):
            raise PaperEventSourceCaptureError("Paper fill row invalid")
        fill = item.get("fill", item)
        if not isinstance(fill, Mapping):
            raise PaperEventSourceCaptureError("Paper fill payload invalid")
        event_date = fill.get("event_date")
        if event_date != execution_date.isoformat():
            raise PaperEventSourceCaptureError("Paper fill event_date mismatch")
        stock_code = fill.get("stock_code")
        if not isinstance(stock_code, str) or not stock_code.strip():
            raise PaperEventSourceCaptureError("Paper fill stock_code missing")
        quantity_value = fill.get("filled_quantity")
        if isinstance(quantity_value, bool) or not isinstance(quantity_value, int) or quantity_value < 0:
            raise PaperEventSourceCaptureError("Paper fill quantity invalid")
        reference_value = fill.get("reference_price")
        if reference_value is None:
            if quantity_value > 0:
                raise PaperEventSourceCaptureError("Paper filled row reference price missing")
            continue
        try:
            reference = Decimal(str(reference_value))
        except InvalidOperation as error:
            raise PaperEventSourceCaptureError("Paper fill reference price invalid") from error
        raw_row = raw_by_symbol.get(stock_code)
        if raw_row is None:
            raise PaperEventSourceCaptureError(
                f"Paper fill stock not present in capture:{stock_code}"
            )
        try:
            source_price = Decimal(str(raw_row["price"]))
        except (InvalidOperation, KeyError) as error:
            raise PaperEventSourceCaptureError("capture source price invalid") from error
        if reference != source_price:
            raise PaperEventSourceCaptureError(
                f"Paper fill reference price differs from capture:{stock_code}"
            )
        reference_prices[stock_code] = format(reference, "f")

    prior_source = result.get("market_source")
    if isinstance(prior_source, Mapping):
        result["diagnostic_prior_market_source"] = dict(prior_source)
    bound_source = dict(source)
    bound_source.update(
        {
            "execution_event_time_proven": True,
            "execution_source_capture_at_proven": True,
            "intraday_open_availability_proven": True,
            "execution_event_time_basis": (
                "paper_simulated_session_open_from_official_capture"
            ),
            "execution_source_recommendation_path": capture_identity["path"],
            "execution_source_recommendation_file_hash": capture_identity["file_hash"],
            "execution_source_result_id": capture_identity["result_id"],
            "execution_source_portfolio_id": capture_identity["portfolio_id"],
            "execution_source_decision_date": capture_identity["decision_date"],
        }
    )
    result.update(
        {
            "market_source": bound_source,
            "execution_replay_mode": "same_session_event_time_capture",
            "execution_event_time_basis": (
                "paper_simulated_session_open_from_official_capture"
            ),
            "execution_event_time_proven": True,
            "formal_consumer_compatible": True,
            "formal_eligibility_schema_version": "paper-receipt-formal-eligibility.v2",
            "formal_ready": False,
            "formal_credit": False,
            "candidate_only": True,
            "research_only": True,
            "broker_order_allowed": False,
            "event_source_binding": {
                "schema_version": PAPER_EVENT_CAPTURE_BINDING_SCHEMA_VERSION,
                "binding_mode": "paper_simulated_session_open_from_official_capture",
                "recommendation": capture_identity,
                "execution_date": execution_date.isoformat(),
                "capture_manifest_path": bound_source.get(
                    "execution_source_capture_manifest_path"
                ),
                "capture_file_hash": bound_source.get(
                    "execution_source_capture_file_hash"
                ),
                "raw_response_hash": bound_source.get(
                    "execution_source_raw_response_hash"
                ),
                "reference_prices_by_symbol": dict(sorted(reference_prices.items())),
                "quote_time_semantics": (
                    "raw_tlong_is_per_symbol_quote_observation_time"
                ),
                "simulated_execution_semantics": (
                    "Paper event is scheduled session-open and uses captured o price;"
                    " it is not a broker fill timestamp"
                ),
                "formal_credit": False,
            },
        }
    )
    return result


def bind_paper_candidate_file_to_capture(
    paper_candidate_path: Path,
    *,
    capture_manifest_path: Path,
    output_path: Path,
    allowed_output_root: Path | None = None,
) -> dict[str, object]:
    """在 Paper writer 與 Formal receipt 之間消費一次 durable capture。

    這是 EOD caller 的受控邊界：讀取 Paper writer 已產生的 candidate、由
    manifest 重建 durable source、完成逐筆 reference-price 綁定，再以
    create-only 方式產生新的 bound candidate。它不改寫原 candidate、ledger
    或 SQLite；operational receipt 應由呼叫端以這個 bound candidate 的結果
    寫入，避免 Formal 讀到尚未綁 source 的舊 receipt。
    """

    candidate_path = paper_candidate_path.expanduser().resolve()
    if candidate_path.is_symlink() or not candidate_path.is_file():
        raise PaperEventSourceCaptureError("Paper candidate file missing")
    candidate_raw = _read_bounded_bytes(candidate_path, role="Paper candidate")
    try:
        candidate_value = json.loads(candidate_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError("Paper candidate JSON invalid") from error
    if not isinstance(candidate_value, Mapping):
        raise PaperEventSourceCaptureError("Paper candidate 必須是 object")
    candidate = {str(key): value for key, value in candidate_value.items()}
    candidate_content_hash = candidate.get("content_sha256")
    candidate_body = dict(candidate)
    candidate_body.pop("content_sha256", None)
    if not _is_sha256(candidate_content_hash) or _payload_hash(candidate_body) != candidate_content_hash:
        raise PaperEventSourceCaptureError("Paper candidate content hash mismatch")
    capture_result = load_persisted_twse_event_source_capture(capture_manifest_path)
    bound = bind_paper_execution_result_to_capture(candidate, capture_result)
    bound["source_candidate_path"] = str(candidate_path)
    bound["source_candidate_file_hash"] = _sha256_bytes(candidate_raw)
    bound["source_candidate_content_hash"] = candidate_content_hash
    bound.pop("content_sha256", None)
    bound["content_sha256"] = _payload_hash(bound)

    output = output_path.expanduser().resolve()
    allowed = (allowed_output_root or (ROOT / "output")).expanduser().resolve()
    if output == allowed:
        raise PaperEventSourceCaptureError("bound Paper candidate output path invalid")
    try:
        output.relative_to(allowed)
    except ValueError as error:
        raise PaperEventSourceCaptureError(
            "bound Paper candidate output escaped controlled output"
        ) from error
    _reject_reparse_chain(output, root=allowed)
    if output.is_symlink() or (output.exists() and not output.is_file()):
        raise PaperEventSourceCaptureError("bound Paper candidate output path invalid")
    encoded = (_canonical_json(bound) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output_file_hash = _write_create_only_bytes(
        output,
        encoded,
        "bound Paper candidate",
    )
    bound["candidate_path"] = str(output)
    bound["candidate_file_hash"] = output_file_hash
    bound["bound_candidate_readback_verified"] = (
        _sha256_bytes(_read_bounded_bytes(output, role="bound Paper candidate"))
        == output_file_hash
    )
    if bound["bound_candidate_readback_verified"] is not True:
        raise PaperEventSourceCaptureError("bound Paper candidate readback mismatch")
    return bound


def _read_symbols_file(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PaperEventSourceCaptureError("symbols file 無法讀取") from error
    if isinstance(payload, Mapping):
        payload = payload.get("symbols")
    if not isinstance(payload, list):
        raise PaperEventSourceCaptureError("symbols file 必須是陣列或 {symbols:[...]}")
    return _validate_symbols(payload)


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise PaperEventSourceCaptureError("execution-date 必須是 YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise PaperEventSourceCaptureError("execution-date 必須是 YYYY-MM-DD")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-date", required=True)
    parser.add_argument("--symbols", help="逗號分隔的四碼 TWSE 代號")
    parser.add_argument("--symbols-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-live-readonly", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if not args.live or not args.confirm_live_readonly:
            raise PaperEventSourceCaptureError(
                "官方 Paper capture 必須同時帶 --live 與 --confirm-live-readonly"
            )
        if (args.symbols is None) == (args.symbols_file is None):
            raise PaperEventSourceCaptureError(
                "--symbols 與 --symbols-file 必須擇一"
            )
        symbols = (
            _read_symbols_file(args.symbols_file)
            if args.symbols_file is not None
            else _validate_symbols(args.symbols.split(","))
        )
        result = capture_twse_session_open_prices(
            symbols=symbols,
            execution_date=_parse_date(args.execution_date),
            output_dir=args.output_dir,
            timeout_seconds=args.timeout_seconds,
        )
    except (
        OSError,
        TypeError,
        ValueError,
        HTTPError,
        URLError,
        PaperEventSourceCaptureError,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "formal_credit": False,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PAPER_EVENT_CAPTURE_BINDING_SCHEMA_VERSION",
    "PAPER_EVENT_CAPTURE_DURABLE_SCHEMA_VERSION",
    "PAPER_EVENT_CAPTURE_PRODUCER_VERSION",
    "PaperEventSourceCaptureError",
    "bind_paper_candidate_file_to_capture",
    "bind_paper_execution_result_to_capture",
    "capture_twse_session_open_prices",
    "capture_twse_session_open_prices_for_recommendation",
    "load_persisted_twse_event_source_capture",
    "persist_twse_event_source_capture",
    "resolve_persisted_twse_event_source_capture_for_recommendation",
]
