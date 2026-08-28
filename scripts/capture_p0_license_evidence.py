"""Capture bounded, candidate-only license/terms evidence for the P0 routes.

The route registry already records an official terms or OpenAPI URL for every
candidate route.  This tool can fetch the *small set of unique, allowlisted*
URLs and retain only a content hash, response metadata, and bounded keyword
flags.  It deliberately does not persist page text, grant acceptance, modify
the source registry, write market data, or enable any downstream consumer.

The default invocation is a no-network preview.  A live request requires the
exact ``--confirm capture-p0-license-evidence`` token and is still only a
candidate evidence capture.  Output is restricted to the operating-system
TEMP directory so the formal data root and repository cannot be overwritten.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.p0_source_acquisition_routes import (  # noqa: E402
    build_p0_acquisition_route_registry,
)
from data_module.p0_source_contract_registry import P0_SOURCE_IDS  # noqa: E402


SCHEMA_VERSION = "p0-license-evidence-capture.v1"
CONFIRMATION = "capture-p0-license-evidence"
DEFAULT_MAX_BYTES = 64 * 1024
MAX_ALLOWED_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_TIMEOUT_SECONDS = 60.0

# Exact URLs are taken from the governed route registry.  This allowlist is a
# second boundary: a malformed or newly introduced URL must be reviewed in
# code before this candidate capture can connect to it.
ALLOWLISTED_LICENSE_URLS = frozenset(
    {
        "https://www.twse.com.tw/zh/terms/use.html",
        "https://www.tpex.org.tw/web/inc/gtsm_disclaimer.php?l=zh-tw",
        "https://openapi.tdcc.com.tw/",
    }
)

KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "automated_access_or_crawler": (
        "自動",
        "程式",
        "爬蟲",
        "automated",
        "crawler",
        "script",
        "robot",
    ),
    "open_data_or_government_exception": (
        "開放資料",
        "政府資料",
        "open data",
        "government open data",
        "政府資料開放",
    ),
    "source_attribution_or_integrity": (
        "來源",
        "引用",
        "完整性",
        "source",
        "attribution",
        "integrity",
    ),
    "internal_use_or_redistribution": (
        "內部",
        "再散布",
        "再分發",
        "redistribut",
        "internal use",
    ),
    "agreement_or_license": (
        "同意",
        "授權",
        "條款",
        "consent",
        "agreement",
        "license",
        "terms",
    ),
}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_output_path(path: Path) -> bool:
    """Only permit candidate artifacts under the OS TEMP directory."""

    return _is_relative_to(path, Path(tempfile.gettempdir()))


def _target_catalog() -> list[dict[str, Any]]:
    registry = build_p0_acquisition_route_registry()
    grouped: dict[str, dict[str, Any]] = {}
    route_count = 0
    for source_id in P0_SOURCE_IDS:
        for route in registry.for_source(source_id):
            route_count += 1
            url = route.license_evidence_url
            if url not in ALLOWLISTED_LICENSE_URLS:
                raise ValueError(
                    f"route license URL is not allowlisted: {route.route_id} -> {url}"
                )
            entry = grouped.setdefault(
                url,
                {
                    "license_evidence_url": url,
                    "source_ids": [],
                    "route_ids": [],
                },
            )
            if source_id not in entry["source_ids"]:
                entry["source_ids"].append(source_id)
            entry["route_ids"].append(route.route_id)

    targets = sorted(grouped.values(), key=lambda item: item["license_evidence_url"])
    if len(targets) == 0 or route_count == 0:
        raise ValueError("P0 route registry contains no license evidence targets")
    for target in targets:
        target["source_ids"] = sorted(target["source_ids"])
        target["route_ids"] = sorted(target["route_ids"])
    return targets


def build_preview_payload(decision_date: date) -> dict[str, Any]:
    """Build a deterministic no-network preview of the capture plan."""

    targets: list[dict[str, Any]] = []
    for target in _target_catalog():
        targets.append(
            {
                **target,
                "status": "not_captured",
                "capture_required": True,
                "content_persisted": False,
            }
        )
    return _base_payload(
        decision_date,
        capture_mode="preview_no_network",
        capture_executed=False,
        confirmation_required=True,
        targets=targets,
    )


def _base_payload(
    decision_date: date,
    *,
    capture_mode: str,
    capture_executed: bool,
    confirmation_required: bool,
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_date": decision_date.isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "capture_mode": capture_mode,
        "capture_executed": capture_executed,
        "confirmation_required": confirmation_required,
        "candidate_only": True,
        "source_acceptance_granted": False,
        "license_accepted": False,
        "downstream_eligibility": "none",
        "formal_eligible": False,
        "formal_evidence_credit_authorized": False,
        "production_ingestion_allowed": False,
        "production_scheduler_allowed": False,
        "network_scope": {
            "allowlisted_url_count": len(targets),
            "max_bytes_per_url": None,
            "timeout_seconds": None,
            "page_text_persisted": False,
        },
        "targets": targets,
        "summary": {
            "target_count": len(targets),
            "captured_count": sum(item.get("status") == "captured" for item in targets),
            "failed_count": sum(item.get("status") not in {"captured", "not_captured"} for item in targets),
            "preview_count": sum(item.get("status") == "not_captured" for item in targets),
        },
        "human_review": {
            "required": True,
            "decision": "requires_human_acceptance",
            "note": "條款指紋與關鍵限制僅供 Owner／Reviewer 審查；不得由此自動推導 accepted 或 limited。",
        },
        "safety_boundary": {
            "market_db_written": False,
            "source_registry_written": False,
            "scoring_or_advice_changed": False,
            "broker_or_scheduler_changed": False,
        },
    }


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is not None:
            return str(value)
    return None


def _response_status(response: Any) -> int | None:
    value = getattr(response, "status", None)
    if value is None:
        getcode = getattr(response, "getcode", None)
        if callable(getcode):
            value = getcode()
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _decode_bytes(raw: bytes, headers: Any) -> str:
    content_type = (_header_value(headers, "Content-Type") or "").lower()
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, UnicodeError):
            pass
    text = raw.decode("utf-8", errors="replace")
    if text.count("�") > max(3, len(text) // 100):
        return raw.decode("cp950", errors="replace")
    return text


def _keyword_flags(text: str) -> dict[str, dict[str, Any]]:
    folded = text.casefold()
    result: dict[str, dict[str, Any]] = {}
    for group, terms in KEYWORD_GROUPS.items():
        matches = [term for term in terms if term.casefold() in folded]
        result[group] = {"matched": bool(matches), "terms": matches}
    return result


def _capture_one(
    target: Mapping[str, Any],
    *,
    opener: Callable[..., Any],
    timeout_seconds: float,
    max_bytes: int,
) -> dict[str, Any]:
    url = str(target["license_evidence_url"])
    requested_host = urlparse(url).netloc.lower()
    request = Request(
        url,
        headers={
            "User-Agent": "technical-analysis-p0-license-evidence/1.0",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.7",
        },
    )
    captured_at = datetime.now(timezone.utc).isoformat()
    try:
        with opener(request, timeout=timeout_seconds) as response:
            raw = response.read(max_bytes + 1)
            if not isinstance(raw, bytes):
                raw = bytes(raw)
            truncated = len(raw) > max_bytes
            sample = raw[:max_bytes]
            headers: Any = getattr(response, "headers", None)
            final_url = str(getattr(response, "geturl", lambda: url)() or url)
            final_host = urlparse(final_url).netloc.lower()
            text = _decode_bytes(sample, headers)
            return {
                **target,
                "status": "captured",
                "http_status": _response_status(response),
                "requested_host": requested_host,
                "final_url": final_url,
                "final_host_allowlisted": final_host == requested_host,
                "captured_at_utc": captured_at,
                "bytes_captured": len(sample),
                "truncated": truncated,
                "content_sha256": sha256(sample).hexdigest(),
                "headers": {
                    "date": _header_value(headers, "Date"),
                    "last_modified": _header_value(headers, "Last-Modified"),
                    "content_type": _header_value(headers, "Content-Type"),
                    "content_length": _header_value(headers, "Content-Length"),
                },
                "keyword_flags": _keyword_flags(text),
                "content_persisted": False,
                "evidence_scope": "bounded_response_sample_hash_and_keyword_flags",
            }
    except HTTPError as exc:
        return {
            **target,
            "status": "http_error",
            "http_status": int(exc.code),
            "requested_host": requested_host,
            "captured_at_utc": captured_at,
            "error_type": "HTTPError",
            "error": str(exc.reason)[:240],
            "content_persisted": False,
        }
    except Exception as exc:  # noqa: BLE001 - candidate probe must retain typed failure
        return {
            **target,
            "status": "transport_error",
            "http_status": None,
            "requested_host": requested_host,
            "captured_at_utc": captured_at,
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
            "content_persisted": False,
        }


def capture_p0_license_evidence(
    decision_date: date,
    *,
    confirmed: bool = False,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    opener: Callable[..., Any] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Return preview or bounded live candidate license evidence.

    ``opener`` is injectable for offline tests; production callers use the
    standard urllib opener only after the explicit confirmation token.
    """

    if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be in (0, {MAX_TIMEOUT_SECONDS}]")
    if max_bytes <= 0 or max_bytes > MAX_ALLOWED_BYTES:
        raise ValueError(f"max_bytes must be in (0, {MAX_ALLOWED_BYTES}]")
    if output_path is not None and not validate_output_path(output_path):
        raise ValueError("output path must be inside the operating-system TEMP directory")

    if not confirmed:
        payload = build_preview_payload(decision_date)
    else:
        selected_opener = opener or urlopen
        catalog = _target_catalog()
        targets = [
            _capture_one(
                target,
                opener=selected_opener,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
            for target in catalog
        ]
        payload = _base_payload(
            decision_date,
            capture_mode="confirmed_bounded_live_readonly",
            capture_executed=True,
            confirmation_required=False,
            targets=targets,
        )
        payload["network_scope"] = {
            "allowlisted_url_count": len(targets),
            "max_bytes_per_url": max_bytes,
            "timeout_seconds": timeout_seconds,
            "page_text_persisted": False,
        }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decision-date",
        type=date.fromisoformat,
        required=True,
        help="證據封套日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="候選 JSON 輸出（必須位於 OS TEMP）",
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=f"啟用 bounded live-only GET 的精確 token：{CONFIRMATION}",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
    )
    args = parser.parse_args(argv)
    confirmed = args.confirm == CONFIRMATION
    payload = capture_p0_license_evidence(
        args.decision_date,
        confirmed=confirmed,
        timeout_seconds=args.timeout_seconds,
        max_bytes=args.max_bytes,
        output_path=args.output,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _configure_utf8_stdio() -> None:
    """讓 Windows 主控台能輸出條款關鍵詞的繁體中文。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # pytest capture streams or a host-managed stream may be immutable.
            continue


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
