"""唯讀檢查正式 App 路徑、logs 與 Research Registry 的環境能力。"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence

# 直接以 ``python scripts/<name>.py`` 執行時，Python 只把 scripts/ 放在
# sys.path；補入 repo root 以維持與其他 CLI 相同的可重現入口。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.runtime_services.environment_readiness_service import (
    EnvironmentReadinessService,
)


DEFAULT_DATA_ROOT = "D:/Min/Python/Project/FA_Data"


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="唯讀檢查 DATA_ROOT、OUTPUT_ROOT、logs 與 Research Run Registry。"
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="覆蓋 DATA_ROOT；未指定時讀取環境變數或正式預設路徑。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="覆蓋 OUTPUT_ROOT；未指定時讀取環境變數或 DATA_ROOT/output。",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="輸出格式，預設 json。",
    )
    parser.add_argument(
        "--write-probe-root",
        type=Path,
        default=None,
        help="指定非正式、已存在的 staging 目錄供實際 ephemeral file／Registry SQLite probe；預設不寫入。",
    )
    parser.add_argument(
        "--confirm-write-probe",
        action="store_true",
        help="明確確認執行 ephemeral file／Registry SQLite transaction／rollback probe；禁止指向 DATA_ROOT／OUTPUT_ROOT。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="可選的 JSON／Markdown 報告輸出路徑；不指定則只輸出 stdout。",
    )
    args = parser.parse_args(argv)

    if args.confirm_write_probe and args.write_probe_root is None:
        parser.error("--confirm-write-probe 必須搭配 --write-probe-root")

    data_root = args.data_root or Path(os.environ.get("DATA_ROOT", DEFAULT_DATA_ROOT))
    output_root = args.output_root or Path(
        os.environ.get("OUTPUT_ROOT", str(data_root / "output"))
    )
    service = EnvironmentReadinessService(data_root, output_root)
    if args.write_probe_root is not None:
        result = service.run_write_probe(
            args.write_probe_root,
            confirm=args.confirm_write_probe,
        )
        rendered = (
            _render_write_probe(result)
            if args.format == "markdown"
            else json.dumps(_write_probe_payload(result), ensure_ascii=False, indent=2)
        )
        _emit_rendered(rendered, args.output)
        return 0 if result.status == "passed" else 2

    snapshot = service.get_snapshot()
    rendered = (
        _render_markdown(snapshot)
        if args.format == "markdown"
        else json.dumps(_to_payload(snapshot), ensure_ascii=False, indent=2)
    )
    _emit_rendered(rendered, args.output)
    return 0 if snapshot.overall_state == "ready" else 2


def _emit_rendered(rendered: str, output: Path | None) -> None:
    if output is not None:
        target = output.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered.rstrip("\n") + "\n", encoding="utf-8")
    print(rendered)


def _to_payload(snapshot: Any) -> dict[str, Any]:
    return {
        "schema_version": "runtime-environment-readiness.v1",
        "overall_state": snapshot.overall_state,
        "observed_at": _isoformat(snapshot.observed_at),
        "data_root": snapshot.data_root,
        "output_root": snapshot.output_root,
        "log_root": snapshot.log_root,
        "research_registry": snapshot.research_registry,
        "side_effect_free": snapshot.side_effect_free,
        "write_probe": snapshot.write_probe,
        "diagnostics": list(snapshot.diagnostics),
        "paths": [
            {
                "key": item.key,
                "label": item.label,
                "path": item.path,
                "kind": item.kind,
                "exists": item.exists,
                "parent_exists": item.parent_exists,
                "readable": item.readable,
                "writable": item.writable,
                "requires_write": item.requires_write,
                "status": item.status,
                "diagnostic": item.diagnostic,
            }
            for item in snapshot.paths
        ],
    }


def _render_markdown(snapshot: Any) -> str:
    lines = [
        "# Runtime Environment Readiness",
        "",
        f"- overall_state: `{snapshot.overall_state}`",
        f"- observed_at: `{_isoformat(snapshot.observed_at)}`",
        f"- side_effect_free: `{snapshot.side_effect_free}`",
        f"- write_probe: `{snapshot.write_probe}`（不建立 probe 檔）",
        "",
        "| 路徑 | 狀態 | 存在 | 可讀 | 可寫 | 診斷 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in snapshot.paths:
        lines.append(
            f"| `{item.label}` (`{item.path}`) | `{item.status}` | "
            f"`{item.exists}` | `{item.readable}` | `{item.writable}` | "
            f"`{item.diagnostic or 'none'}` |"
        )
    lines.extend(
        [
            "",
            "診斷反映目前程序的路徑可見性、`os.access` hint，以及對既有 logger／Registry 檔案的無寫入 handle probe；不等於已實際寫入，也不會替操作員修改權限。",
        ]
    )
    if snapshot.diagnostics:
        lines.extend(["", "Diagnostics:", ""])
        lines.extend(f"- `{diagnostic}`" for diagnostic in snapshot.diagnostics)
    return "\n".join(lines)


def _write_probe_payload(result: Any) -> dict[str, Any]:
    return {
        "schema_version": "runtime-environment-write-probe.v1",
        "status": result.status,
        "probe_root": result.probe_root,
        "observed_at": _isoformat(result.observed_at),
        "file_write_succeeded": result.file_write_succeeded,
        "sqlite_write_succeeded": result.sqlite_write_succeeded,
        "registry_transaction_succeeded": result.registry_transaction_succeeded,
        "cleanup_succeeded": result.cleanup_succeeded,
        "side_effect_free": result.side_effect_free,
        "write_probe": result.write_probe,
        "diagnostic": result.diagnostic,
    }


def _render_write_probe(result: Any) -> str:
    lines = [
        "# Runtime Environment Write Probe",
        "",
        f"- status: `{result.status}`",
        f"- probe_root: `{result.probe_root}`",
        f"- observed_at: `{_isoformat(result.observed_at)}`",
        f"- side_effect_free: `{result.side_effect_free}`",
        f"- write_probe: `{result.write_probe}`",
        f"- file_write_succeeded: `{result.file_write_succeeded}`",
        f"- sqlite_write_succeeded: `{result.sqlite_write_succeeded}`",
        f"- registry_transaction_succeeded: `{result.registry_transaction_succeeded}`",
        f"- cleanup_succeeded: `{result.cleanup_succeeded}`",
        f"- diagnostic: `{result.diagnostic or 'none'}`",
        "",
        "此結果只代表指定非正式 staging 目錄的 ephemeral file 與實際 Research Run Registry schema transaction／rollback 及清理；不代表正式 Registry schema、ACL 或正式資料可寫。",
    ]
    return "\n".join(lines)


def _isoformat(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _configure_utf8_stdio() -> None:
    """讓直接執行腳本的 Windows 主控台也能顯示繁中說明與診斷。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # 測試 capture stream 或被外部 host 管理的 stream 可能禁止重設；
            # 這不應改變 readiness 結果。
            continue


if __name__ == "__main__":
    raise SystemExit(main())
