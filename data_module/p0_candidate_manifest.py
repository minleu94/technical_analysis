"""P0 candidate raw payload manifest 與 quarantine 契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping


_SECRET_PARAMETER_NAMES = {"token", "api_key", "apikey", "key", "secret", "password"}
_SAFE_HTTP_HEADERS = {"content-type", "date", "etag", "last-modified"}


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fetched_at 必須包含 timezone")


@dataclass(frozen=True)
class RawPayloadManifest:
    run_id: str
    source_id: str
    source_version: str
    endpoint_id: str
    request_parameters: Mapping[str, str]
    http_status: int
    http_headers: Mapping[str, str]
    fetched_at: datetime
    payload_sha256: str
    payload_size_bytes: int
    parser_version: str
    raw_row_count: int
    accepted_row_count: int
    duplicate_row_count: int
    quarantine_row_count: int
    blocked_row_count: int

    def __post_init__(self) -> None:
        _require_aware(self.fetched_at)
        counts = (
            self.raw_row_count,
            self.accepted_row_count,
            self.duplicate_row_count,
            self.quarantine_row_count,
            self.blocked_row_count,
        )
        if any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in counts):
            raise ValueError("row counts 必須為非負 integer")
        if self.raw_row_count != sum(counts[1:]):
            raise ValueError("row conservation violated")
        if (
            isinstance(self.payload_size_bytes, bool)
            or not isinstance(self.payload_size_bytes, int)
            or self.payload_size_bytes < 0
        ):
            raise ValueError("payload_size_bytes 必須為非負 integer")
        if len(self.payload_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.payload_sha256.lower()
        ):
            raise ValueError("payload_sha256 必須是 64 字元 SHA-256")

    @classmethod
    def capture(
        cls,
        *,
        run_id: str,
        source_id: str,
        source_version: str,
        endpoint_id: str,
        request_parameters: Mapping[str, object],
        http_status: int,
        http_headers: Mapping[str, object],
        fetched_at: datetime,
        payload: bytes,
        parser_version: str,
        raw_row_count: int,
        accepted_row_count: int,
        duplicate_row_count: int,
        quarantine_row_count: int,
        blocked_row_count: int,
    ) -> "RawPayloadManifest":
        _require_aware(fetched_at)
        classified = accepted_row_count + duplicate_row_count + quarantine_row_count + blocked_row_count
        if raw_row_count != classified:
            raise ValueError(f"row conservation violated: raw={raw_row_count}, classified={classified}")
        counts = (raw_row_count, accepted_row_count, duplicate_row_count, quarantine_row_count, blocked_row_count)
        if any(count < 0 for count in counts):
            raise ValueError("row counts 不可為負數")
        safe_parameters = {
            str(key): str(value)
            for key, value in request_parameters.items()
            if str(key).lower() not in _SECRET_PARAMETER_NAMES
        }
        safe_headers = {
            str(key).lower(): str(value)
            for key, value in http_headers.items()
            if str(key).lower() in _SAFE_HTTP_HEADERS
        }
        return cls(
            run_id=run_id,
            source_id=source_id,
            source_version=source_version,
            endpoint_id=endpoint_id,
            request_parameters=MappingProxyType(safe_parameters),
            http_status=http_status,
            http_headers=MappingProxyType(safe_headers),
            fetched_at=fetched_at,
            payload_sha256=sha256(payload).hexdigest(),
            payload_size_bytes=len(payload),
            parser_version=parser_version,
            raw_row_count=raw_row_count,
            accepted_row_count=accepted_row_count,
            duplicate_row_count=duplicate_row_count,
            quarantine_row_count=quarantine_row_count,
            blocked_row_count=blocked_row_count,
        )
    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.__dict__)
        payload["request_parameters"] = dict(self.request_parameters)
        payload["http_headers"] = dict(self.http_headers)
        payload["fetched_at"] = self.fetched_at.isoformat()
        return payload


@dataclass(frozen=True)
class QuarantineRecord:
    run_id: str
    source_id: str
    source_version: str
    raw_row_sha256: str
    reason_code: str
    detail: str

    def __post_init__(self) -> None:
        if not all((self.run_id, self.source_id, self.source_version, self.reason_code, self.detail)):
            raise ValueError("quarantine identity and reason are required")
        if len(self.raw_row_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.raw_row_sha256.lower()
        ):
            raise ValueError("raw_row_sha256 必須是 64 字元 SHA-256")

    @classmethod
    def from_raw_row(
        cls,
        *,
        run_id: str,
        source_id: str,
        source_version: str,
        raw_row: Mapping[str, Any],
        reason_code: str,
        detail: str,
    ) -> "QuarantineRecord":
        canonical = json.dumps(raw_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(
            run_id=run_id,
            source_id=source_id,
            source_version=source_version,
            raw_row_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
            reason_code=reason_code,
            detail=detail,
        )
