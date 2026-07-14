"""Bounded TWSE T86 fetch 與 immutable raw-envelope persistence。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

import requests


T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
PARSER_VERSION = "twse-t86-candidate.v1"


class T86FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchAttempt:
    attempt: int
    status_code: int | None
    error: str | None
    retry_after: str | None
    elapsed_ms: int


@dataclass(frozen=True)
class RawFetchEnvelope:
    observation_date: str
    source_url: str
    request_params: Mapping[str, str]
    requested_at: datetime
    retrieved_at: datetime
    http_status: int
    content_type: str
    byte_count: int
    raw_row_count: int | None
    payload_sha256: str
    parser_version: str
    endpoint_version: str
    payload: bytes
    attempts: tuple[FetchAttempt, ...]


def fetch_t86_envelope(
    observation_date: date,
    *,
    transport: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    timeout_seconds: float = 15.0,
    max_attempts: int = 3,
) -> RawFetchEnvelope:
    params = {"response": "json", "date": observation_date.strftime("%Y%m%d"), "selectType": "ALL"}
    requested_at = now()
    attempts: list[FetchAttempt] = []
    response: Any = None
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = transport(
                url=T86_URL, params=params,
                headers={"User-Agent": "technical-analysis-candidate-research/1.0"},
                timeout=timeout_seconds,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            status = int(response.status_code)
            retry_after = response.headers.get("Retry-After")
            attempts.append(FetchAttempt(attempt, status, None, retry_after, elapsed_ms))
            if status == 200:
                break
            if status != 429 and not 500 <= status <= 599:
                raise T86FetchError(f"non_retryable_http_status:{status}")
        except T86FetchError:
            raise
        except (requests.RequestException, TimeoutError) as exc:
            attempts.append(FetchAttempt(attempt, None, type(exc).__name__, None, int((time.perf_counter() - started) * 1000)))
        if attempt < max_attempts:
            retry_after_value = attempts[-1].retry_after
            delay = min(float(retry_after_value), 4.0) if retry_after_value and retry_after_value.isdigit() else min(2 ** (attempt - 1), 4)
            sleep(delay)
    if response is None or int(response.status_code) != 200:
        raise T86FetchError("bounded_fetch_exhausted")
    payload = bytes(response.content)
    content_type = str(response.headers.get("Content-Type", ""))
    if not payload:
        raise T86FetchError("empty_payload")
    if "json" not in content_type.lower() or payload.lstrip().lower().startswith(b"<html"):
        raise T86FetchError("non_json_payload")
    try:
        decoded = json.loads(payload)
        raw_row_count = len(decoded["data"]) if isinstance(decoded.get("data"), list) else None
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        raw_row_count = None
    retrieved_at = now()
    return RawFetchEnvelope(
        observation_date.isoformat(), T86_URL, params, requested_at, retrieved_at,
        200, content_type, len(payload), raw_row_count, sha256(payload).hexdigest(), PARSER_VERSION,
        "twse:rwd:zh:fund:T86.v1", payload, tuple(attempts),
    )


def persist_raw_envelope(envelope: RawFetchEnvelope, *, output_root: Path) -> Path:
    raw_dir = output_root.resolve() / "raw" / envelope.observation_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    payload_path = raw_dir / f"{envelope.payload_sha256}.json"
    if payload_path.exists():
        if sha256(payload_path.read_bytes()).hexdigest() != envelope.payload_sha256:
            raise FileExistsError(f"raw artifact hash conflict: {payload_path}")
    else:
        with payload_path.open("xb") as stream:
            stream.write(envelope.payload)
    payload_metadata = {
        "observation_date": envelope.observation_date,
        "source_url": envelope.source_url,
        "request_params": dict(envelope.request_params),
        "http_status": envelope.http_status,
        "content_type": envelope.content_type,
        "byte_count": envelope.byte_count,
        "raw_row_count": envelope.raw_row_count,
        "payload_sha256": envelope.payload_sha256,
        "parser_version": envelope.parser_version,
        "endpoint_version": envelope.endpoint_version,
    }
    metadata_path = raw_dir / "metadata" / f"{envelope.payload_sha256}.json"
    _write_immutable_json(metadata_path, payload_metadata)

    retrieval = {
        "observation_date": envelope.observation_date,
        "payload_sha256": envelope.payload_sha256,
        "requested_at": envelope.requested_at.isoformat(),
        "retrieved_at": envelope.retrieved_at.isoformat(),
        "attempts": [asdict(item) for item in envelope.attempts],
    }
    retrieval_bytes = _canonical_json_bytes(retrieval)
    retrieval_id = sha256(retrieval_bytes).hexdigest()
    retrieval_path = raw_dir / "retrievals" / f"{retrieval_id}.json"
    _write_immutable_bytes(retrieval_path, retrieval_bytes)
    return payload_path


def _write_immutable_json(path: Path, value: object) -> None:
    _write_immutable_bytes(path, _canonical_json_bytes(value))


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def _write_immutable_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise FileExistsError(f"immutable artifact conflict: {path}")
        return
    with path.open("xb") as stream:
        stream.write(value)
