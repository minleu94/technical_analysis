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
from data_module.source_acceptance_governance import (  # noqa: E402
    MACHINE_LICENSE_SCOPE_POLICIES,
)


SCHEMA_VERSION = "p0-license-evidence-capture.v1"
MACHINE_LICENSE_ARTIFACT_SCHEMA_VERSION = "source-acceptance-license-evidence.v1"
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
        "producer": "capture_p0_license_evidence.py",
        "producer_code_sha256": _producer_code_sha256(),
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


def build_machine_license_artifact(
    capture_payload: Mapping[str, Any],
    *,
    source_id: str,
    output_path: Path,
    capture_path: Path | None = None,
    capture_root: Path | None = None,
    government_dataset_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """由本次 bounded capture 產生一個可供 machine evaluator 讀取的 artifact。

    這裡只把實際 capture 的 response metadata、內容指紋與客觀關鍵詞結果
    綁定到指定 P0 source；不把條款文字推導成人類授權，也不保存頁面正文。
    ``output_path`` 必須位於 TEMP，呼叫端仍須讓 evaluator 重新讀取並驗證
    artifact bytes。若指定 ``capture_path``，會一併記錄完整 capture JSON 的
    hash，讓後續 consumer 可以追溯到本次 producer 輸出。對於已登錄的政府
    資料平台 scope，``government_dataset_evidence`` 也必須帶入本次 metadata
    原始 bytes 的路徑與雜湊；沒有這份客觀映射時保持 blocked。
    """

    if not isinstance(capture_payload, Mapping):
        raise TypeError("capture payload must be an object")
    if not source_id.strip():
        raise ValueError("source_id is required")
    if not validate_output_path(output_path):
        raise ValueError("machine license artifact must be inside the operating-system TEMP directory")
    if capture_path is not None and not validate_output_path(capture_path):
        raise ValueError("capture artifact must be inside the operating-system TEMP directory")
    if capture_root is not None and not validate_output_path(capture_root):
        raise ValueError("capture root must be inside the operating-system TEMP directory")

    targets = capture_payload.get("targets")
    if isinstance(targets, (str, bytes)) or not isinstance(targets, Sequence):
        raise ValueError("capture payload targets must be an array")
    matching = [
        target
        for target in targets
        if isinstance(target, Mapping)
        and source_id in target.get("source_ids", ())
        and target.get("license_evidence_url") in ALLOWLISTED_LICENSE_URLS
    ]
    if len(matching) != 1:
        raise ValueError(
            f"capture payload must contain exactly one allowlisted target for source: {source_id}"
        )
    target = dict(matching[0])

    keyword_flags = target.get("keyword_flags")
    keyword_flags_mapping: Mapping[str, Any] = (
        keyword_flags if isinstance(keyword_flags, Mapping) else {}
    )
    agreement_flags: Mapping[str, Any] = {}
    raw_agreement = keyword_flags_mapping.get("agreement_or_license")
    if isinstance(raw_agreement, Mapping):
        agreement_flags = raw_agreement

    requested_url = target.get("license_evidence_url")
    final_url = target.get("final_url")
    status = target.get("status")
    http_status = target.get("http_status")
    content_hash = target.get("content_sha256")
    policy = (
        MACHINE_LICENSE_SCOPE_POLICIES.get(str(requested_url))
        if isinstance(requested_url, str)
        else None
    )
    policy_mapping: Mapping[str, Any] = policy if isinstance(policy, Mapping) else {}
    raw_document = policy_mapping.get("official_document")
    official_document: Mapping[str, Any] = (
        raw_document if isinstance(raw_document, Mapping) else {}
    )
    raw_source_scopes = policy_mapping.get("source_scopes")
    source_scopes: Mapping[str, Any] = (
        raw_source_scopes if isinstance(raw_source_scopes, Mapping) else {}
    )
    raw_source_scope = source_scopes.get(source_id)
    source_scope: Mapping[str, Any] = (
        raw_source_scope if isinstance(raw_source_scope, Mapping) else {}
    )
    raw_government_dataset = source_scope.get("government_dataset")
    government_dataset: Mapping[str, Any] = (
        raw_government_dataset
        if isinstance(raw_government_dataset, Mapping)
        else {}
    )
    headers = target.get("headers")
    headers_mapping: Mapping[str, Any] = (
        headers if isinstance(headers, Mapping) else {}
    )
    content_type = str(headers_mapping.get("content_type") or "")
    media_type = content_type.split(";", 1)[0].strip().casefold()
    expected_media_type = str(official_document.get("content_type") or "").casefold()
    expected_hash = official_document.get("content_sha256")
    expected_hash_normalized = _normalize_sha256(expected_hash)
    target_hash_normalized = _normalize_sha256(content_hash)
    expected_bytes = official_document.get("content_bytes")
    expected_last_modified = official_document.get("last_modified")
    keyword_groups_observed = sorted(
        group
        for group, value in keyword_flags_mapping.items()
        if isinstance(group, str)
        and isinstance(value, Mapping)
        and value.get("matched") is True
    )
    capture_producer_verified = (
        capture_payload.get("producer") == "capture_p0_license_evidence.py"
        and capture_payload.get("producer_code_sha256") == _producer_code_sha256()
    )
    government_dataset_evidence_bound = (
        not government_dataset
        or _government_dataset_binding_matches(
            government_dataset_evidence, government_dataset
        )
    )
    objective_checks = {
        "captured": status == "captured",
        "http_success": isinstance(http_status, int) and 200 <= http_status < 300,
        "requested_url_allowlisted": requested_url in ALLOWLISTED_LICENSE_URLS,
        "final_url_exact_allowlisted": final_url == requested_url
        and final_url in ALLOWLISTED_LICENSE_URLS,
        "response_complete": target.get("truncated") is False,
        "capture_producer_verified": capture_producer_verified,
        "official_document_hash_verified": bool(expected_hash_normalized)
        and target_hash_normalized == expected_hash_normalized,
        "official_document_version_verified": (
            bool(official_document)
            and headers_mapping.get("last_modified") == expected_last_modified
        ),
        "official_document_size_verified": (
            isinstance(expected_bytes, int)
            and not isinstance(expected_bytes, bool)
            and target.get("bytes_captured") == expected_bytes
        ),
        "official_document_type_verified": (
            bool(expected_media_type) and media_type == expected_media_type
        ),
        "scope_policy_known": policy is not None,
        "source_scope_known": bool(source_scope),
        "final_host_allowlisted": target.get("final_host_allowlisted") is True,
        "government_dataset_evidence_bound": government_dataset_evidence_bound,
        "content_not_persisted": target.get("content_persisted") is False,
    }
    approved = all(objective_checks.values()) and _is_sha256_hex(content_hash)
    scope_policy_version: Any = policy_mapping.get("policy_version")
    scope_allowed_use_cases = list(
        source_scope.get(
            "allowed_use_cases", policy_mapping.get("allowed_use_cases", ())
        )
    )

    artifact: dict[str, Any] = {
        "schema_version": MACHINE_LICENSE_ARTIFACT_SCHEMA_VERSION,
        "producer": "capture_p0_license_evidence.py",
        "producer_code_sha256": _producer_code_sha256(),
        "source_id": source_id,
        "evidence_id": f"license:{source_id}:{str(content_hash)[:16]}",
        "status": "machine_scope_verified" if approved else "blocked",
        "source_url": requested_url,
        "final_url": final_url,
        "http_status": http_status,
        "content_sha256": f"sha256:{content_hash}" if _is_sha256_hex(content_hash) else content_hash,
        "captured_at_utc": target.get("captured_at_utc"),
        "truncated": target.get("truncated"),
        "keyword_flags": keyword_flags,
        "final_host_allowlisted": target.get("final_host_allowlisted") is True,
        "agreement_or_license_present": agreement_flags.get("matched") is True,
        "content_persisted": target.get("content_persisted"),
        "objective_checks": objective_checks,
        "official_document": dict(official_document),
        "government_dataset_evidence": (
            dict(government_dataset_evidence)
            if isinstance(government_dataset_evidence, Mapping)
            else None
        ),
        "scope_policy": {
            "policy_version": scope_policy_version,
            "official_document": dict(official_document),
            "allowed_use_cases": scope_allowed_use_cases,
            "source_id": source_id,
            "source_scope": dict(source_scope),
            "formal_oos_allowed": policy_mapping.get("formal_oos_allowed") is True,
            "production_scheduler_allowed": policy_mapping.get(
                "production_scheduler_allowed"
            )
            is True,
            "redistribution_allowed": policy_mapping.get("redistribution_allowed")
            is True,
            "legal_acceptance_inferred": policy_mapping.get(
                "legal_acceptance_inferred"
            )
            is True,
            "machine_policy_only": True,
        },
        "keyword_groups_observed": keyword_groups_observed,
        "evidence_scope": "bounded_response_metadata_and_exact_official_document_fingerprint",
        "source_route_ids": target.get("route_ids", []),
    }
    if _is_sha256_hex(content_hash):
        artifact["capture_target_content_sha256"] = f"sha256:{content_hash}"
    if capture_path is not None:
        capture_bytes = capture_path.read_bytes()
        reference_root = capture_root.resolve() if capture_root is not None else output_path.resolve().parent
        try:
            capture_reference = capture_path.resolve().relative_to(reference_root).as_posix()
        except ValueError:
            capture_reference = str(capture_path.resolve())
        artifact["capture_artifact"] = {
            "path": capture_reference,
            "content_sha256": f"sha256:{sha256(capture_bytes).hexdigest()}",
            "bytes": len(capture_bytes),
            "kind": "p0-license-capture-json",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_canonical_json_bytes(artifact))
    return {
        "evidence_id": artifact["evidence_id"],
        "artifact_path": output_path.name,
        "content_sha256": f"sha256:{sha256(output_path.read_bytes()).hexdigest()}",
        "status": artifact["status"],
        "objective_checks": objective_checks,
    }


def _government_dataset_binding_matches(
    evidence: Mapping[str, Any] | None,
    expected: Mapping[str, Any],
) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    for field_name in (
        "dataset_id",
        "dataset_url",
        "metadata_url",
        "identifier",
        "title",
        "data_provider_id",
        "publisher_oid",
        "license_code",
        "license_version",
        "license_url",
        "endpoint_url",
        "resource_url",
        "api_documentation_url",
        "metadata_modified",
    ):
        if evidence.get(field_name) != expected.get(field_name):
            return False
    if _normalize_sha256(evidence.get("content_sha256")) != _normalize_sha256(
        expected.get("metadata_content_sha256")
    ):
        return False
    expected_bytes = expected.get("metadata_content_bytes")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or evidence.get("bytes") != expected_bytes
    ):
        return False
    if evidence.get("http_status") not in range(200, 300):
        return False
    path = evidence.get("path")
    if not isinstance(path, str) or not path.strip():
        return False
    api_evidence = evidence.get("api_documentation_evidence")
    if not isinstance(api_evidence, Mapping):
        return False
    api_bytes = api_evidence.get("bytes")
    api_status = api_evidence.get("http_status")
    return (
        api_evidence.get("metadata_url") == expected.get("api_documentation_url")
        and api_evidence.get("endpoint_url") == expected.get("endpoint_url")
        and isinstance(api_evidence.get("endpoint_path"), str)
        and _is_sha256_hex(api_evidence.get("content_sha256"))
        and isinstance(api_bytes, int)
        and not isinstance(api_bytes, bool)
        and api_bytes > 0
        and api_status in range(200, 300)
    )


def _is_sha256_hex(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    digest = value.removeprefix("sha256:")
    if len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True


def _normalize_sha256(value: Any) -> str:
    if not _is_sha256_hex(value):
        return ""
    return str(value).removeprefix("sha256:").casefold()


def _producer_code_sha256() -> str:
    return f"sha256:{sha256(Path(__file__).resolve().read_bytes()).hexdigest()}"


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


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
    parser.add_argument(
        "--machine-source-id",
        help="將本次 capture 綁定為指定 P0 source 的 machine license artifact",
    )
    parser.add_argument(
        "--machine-artifact-output",
        type=Path,
        help="machine license artifact 輸出（必須位於 OS TEMP，需搭配 --output）",
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
    machine_artifact: dict[str, Any] | None = None
    if args.machine_source_id is not None or args.machine_artifact_output is not None:
        if not confirmed:
            raise ValueError("machine license artifact requires confirmed bounded capture")
        if args.machine_source_id is None or args.machine_artifact_output is None:
            raise ValueError(
                "--machine-source-id and --machine-artifact-output must be provided together"
            )
        if args.output is None:
            raise ValueError("machine license artifact requires --output capture JSON")
        machine_artifact = build_machine_license_artifact(
            payload,
            source_id=args.machine_source_id,
            output_path=args.machine_artifact_output,
            capture_path=args.output,
        )
    rendered: dict[str, Any] = {"capture": payload}
    if machine_artifact is not None:
        rendered["machine_artifact"] = machine_artifact
    print(json.dumps(rendered if machine_artifact is not None else payload, ensure_ascii=False, indent=2))
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
