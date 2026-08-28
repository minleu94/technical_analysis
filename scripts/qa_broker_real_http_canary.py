"""以單一受控請求驗證 MoneyDJ 真實 HTTP parser canary。

預設為 preview-only；只有明確傳入 ``--confirm-real-http-canary`` 才會發出
一個 GET。canary 使用手動指定的 branch identity 與既有 production parser，
不讀／寫正式 registry、CSV、SQLite，不啟動 Selenium，也不啟用平行 fetch。
可選的 ``--baseline-json`` 只用來把成功的 network observation 合併到既有
離線 broker baseline；合併結果仍必須寫到 protected roots 外的明確 output。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app_module.broker_branch_update_service as broker_module  # noqa: E402
from app_module.broker_branch_update_service import (  # noqa: E402
    BrokerBranchUpdateService,
)


CANARY_SCHEMA_VERSION = "broker-real-http-canary.v1"
COMBINED_SCHEMA_VERSION = "broker-performance-baseline.v2"


class _ProbeConfig:
    def __init__(self, root: Path) -> None:
        self.broker_flow_dir = root / "broker_flow"
        self.meta_data_dir = root / "meta_data"


def measure_real_http_canary(
    *,
    staging_root: Path,
    protected_roots: Sequence[Path],
    branch_info: Mapping[str, Any],
    date_str: str,
    metric: str,
    confirm_real_http_canary: bool = False,
    timeout: int = 15,
) -> dict[str, Any]:
    """執行單請求 real HTTP canary，或在未確認時回傳不連線 preview。"""

    resolved_staging = Path(staging_root).expanduser().resolve()
    resolved_protected = _resolve_roots(protected_roots)
    base: dict[str, Any] = {
        "schema_version": CANARY_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "staging_root": str(resolved_staging),
        "protected_roots": [str(path) for path in resolved_protected],
        "confirmation_required": True,
        "confirm_real_http_canary": bool(confirm_real_http_canary),
        "read_only": True,
        "network_enabled": False,
        "real_http_attempted": False,
        "request_count": 0,
        "selenium_invocations": 0,
        "parallelism_enabled": False,
        "staging_write_attempted": False,
        "production_write_attempted": False,
        "production_sqlite_write_attempted": False,
        "cleanup_succeeded": None,
        "branch": dict(branch_info),
        "date": date_str,
        "metric": metric,
        "timeout_seconds": timeout,
    }
    if not confirm_real_http_canary:
        return {
            **base,
            "status": "confirmation_required",
            "blocker": "explicit_confirm_real_http_canary_required",
            "next_safe_step": "明確傳入 --confirm-real-http-canary 後才會發出一個 GET。",
        }
    if not resolved_protected:
        return {
            **base,
            "status": "blocked",
            "blocker": "protected_root_required",
            "next_safe_step": "至少指定一個 protected root。",
        }
    if not resolved_staging.is_dir():
        return {
            **base,
            "status": "blocked",
            "blocker": "staging_root_must_preexist",
            "next_safe_step": "指定已存在且位於正式資料根之外的 staging root。",
        }
    if any(_is_within(resolved_staging, root) for root in resolved_protected):
        return {
            **base,
            "status": "blocked",
            "blocker": "staging_root_inside_protected_root",
            "next_safe_step": "改用 protected roots 外的 staging root。",
        }
    try:
        _validate_request(date_str=date_str, metric=metric, timeout=timeout)
        _validate_branch(branch_info)
    except ValueError as error:
        return {
            **base,
            "status": "blocked",
            "blocker": "real_http_canary_input_invalid",
            "error_type": type(error).__name__,
            "error": str(error),
        }

    report: dict[str, Any]
    temporary_path: Path | None = None
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(
            dir=str(resolved_staging),
            prefix="broker_real_http_canary_",
        ) as temp_name:
            temporary_path = Path(temp_name)
            # BrokerBranchUpdateService creates these paths in __init__; create
            # them first so the service itself does not need to mutate anything
            # beyond an already-ephemeral directory structure.
            (temporary_path / "broker_flow").mkdir()
            (temporary_path / "meta_data").mkdir()
            service = BrokerBranchUpdateService(_ProbeConfig(temporary_path))
            url = service._build_branch_url(
                dict(branch_info),
                _previous_date(date_str),
                date_str,
                metric=metric,
            )
            rows = service._fetch_metric_records_http(
                dict(branch_info),
                date_str,
                metric,
                retries=1,
                timeout=timeout,
            )
            if not rows:
                raise RuntimeError("MoneyDJ real HTTP canary returned no parsed rows")
            canonical = json.dumps(
                rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            report = {
                **base,
                "status": "measured",
                "blocker": None,
                "network_enabled": True,
                "real_http_attempted": True,
                "request_count": 1,
                "endpoint": url,
                "row_count": len(rows),
                "parsed_rows_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "sample_rows": [dict(row) for row in rows[:2]],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "next_safe_step": (
                    "保留 broker fetch pool 與 Selenium fallback 關閉；先由 owner review "
                    "source license／rate-limit，再決定是否做更大範圍 fetch。"
                ),
            }
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        report = {
            **base,
            "status": "blocked",
            "blocker": "real_http_canary_failed",
            "real_http_attempted": True,
            "request_count": 1,
            "error_type": type(error).__name__,
            "error": str(error),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    finally:
        report["cleanup_succeeded"] = (
            temporary_path is not None and not temporary_path.exists()
        )
    return report


def combine_with_broker_baseline(
    baseline_path: Path,
    canary_report: Mapping[str, Any],
) -> dict[str, Any]:
    """將 network observation 附掛於既有離線 baseline，不竄改來源檔。"""

    baseline = _read_json_object(Path(baseline_path))
    combined = dict(baseline)
    combined["schema_version"] = COMBINED_SCHEMA_VERSION
    combined["network_enabled"] = canary_report.get("network_enabled") is True
    combined["real_http_canary"] = dict(canary_report)
    combined["baseline_source_file"] = str(Path(baseline_path).expanduser().resolve())
    combined["baseline_source_sha256"] = _sha256(Path(baseline_path))
    combined["combined_at"] = datetime.now(timezone.utc).isoformat()
    return combined


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, action="append", required=True)
    parser.add_argument("--branch-system-key", required=True)
    parser.add_argument("--branch-broker-code", required=True)
    parser.add_argument("--branch-code", required=True)
    parser.add_argument("--branch-display-name", required=True)
    parser.add_argument("--url-param-a", required=True)
    parser.add_argument("--url-param-b", required=True)
    parser.add_argument("--date", dest="date_str", required=True)
    parser.add_argument("--metric", choices=("lots", "amount"), required=True)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--confirm-real-http-canary", action="store_true")
    parser.add_argument(
        "--baseline-json",
        type=Path,
        help="可選：既有離線 broker baseline；成功時輸出合併 artifact",
    )
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)

    protected = _resolve_roots(args.protected_root)
    if args.output_json is not None:
        output_target = args.output_json.expanduser().resolve()
        if any(_is_within(output_target, root) for root in protected):
            print(
                json.dumps(
                    {
                        "schema_version": CANARY_SCHEMA_VERSION,
                        "status": "blocked",
                        "blocker": "output_json_inside_protected_root",
                        "production_write_attempted": False,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 2

    branch_info = {
        "branch_system_key": args.branch_system_key,
        "branch_broker_code": args.branch_broker_code,
        "branch_code": args.branch_code,
        "branch_display_name": args.branch_display_name,
        "url_param_a": args.url_param_a,
        "url_param_b": args.url_param_b,
    }
    report = measure_real_http_canary(
        staging_root=args.staging_root,
        protected_roots=args.protected_root,
        branch_info=branch_info,
        date_str=args.date_str,
        metric=args.metric,
        confirm_real_http_canary=args.confirm_real_http_canary,
        timeout=args.timeout,
    )
    payload: dict[str, Any] = report
    if args.baseline_json is not None and report.get("status") == "measured":
        try:
            payload = combine_with_broker_baseline(args.baseline_json, report)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"broker canary baseline combine blocked: {error}", file=sys.stderr)
            return 2
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report.get("status") == "measured":
        return 0
    return 2


def _validate_request(*, date_str: str, metric: str, timeout: int) -> None:
    datetime.strptime(date_str, "%Y-%m-%d")
    if metric not in {"lots", "amount"}:
        raise ValueError(f"unsupported metric: {metric}")
    if timeout < 1 or timeout > 120:
        raise ValueError("timeout must be between 1 and 120 seconds")


def _validate_branch(branch_info: Mapping[str, Any]) -> None:
    for key in (
        "branch_system_key",
        "branch_broker_code",
        "branch_code",
        "branch_display_name",
        "url_param_a",
        "url_param_b",
    ):
        if not str(branch_info.get(key, "")).strip():
            raise ValueError(f"branch field is required: {key}")


def _previous_date(date_str: str) -> str:
    from datetime import timedelta

    return (datetime.strptime(date_str, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_roots(roots: Sequence[Path]) -> list[Path]:
    return [Path(root).expanduser().resolve() for root in roots if str(root).strip()]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


if __name__ == "__main__":
    raise SystemExit(main())
