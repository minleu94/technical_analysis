"""唯讀驗證 OOC frozen rows 與可交付 ML release 的逐列 parity。

這個工具只讀取明確指定的 release root、inference input 與 OOC audit；不寫入
模型、資料庫、pointer 或 promotion 狀態。任何 release contract、policy、universe
或模型輸出不一致都以 blocked／非零 exit code 結束。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.allocation_release_adapter import AllocationReleaseAdapter  # noqa: E402
from scripts.infer_ml_allocation_copilot import _load_rows  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--ooc-audit", type=Path, required=True)
    parser.add_argument("--model-id")
    parser.add_argument("--universe-id", required=True)
    parser.add_argument("--policy-id")
    parser.add_argument("--policy-hash", required=True)
    parser.add_argument("--expected-universe-hash")
    parser.add_argument("--expected-release-identity-hash")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_utf8()
    args = _parser().parse_args(argv)
    try:
        release = AllocationReleaseAdapter().load(
            args.release_root,
            expected_release_identity_hash=args.expected_release_identity_hash,
        )
        rows = _load_rows(args.input)
        ooc_outputs: object = json.loads(args.ooc_audit.read_text(encoding="utf-8"))
        parity = release.validate_frozen_rows(
            rows=rows,
            ooc_outputs=ooc_outputs,
            model_id=args.model_id,
            universe_id=args.universe_id,
            policy_id=args.policy_id,
            policy_hash=args.policy_hash,
            expected_universe_hash=args.expected_universe_hash,
        )
        payload: dict[str, Any] = {
            "status": "matched",
            "release_id": release.release_id,
            "model_id": release.model_id,
            "dataset_id": release.dataset_id,
            "release_identity_hash": release.manifest.release_identity_hash,
            "row_count": parity.row_count,
            "release_output_hash": parity.release_output_hash,
            "ooc_output_hash": parity.ooc_output_hash,
            "mismatched_row_ids": list(parity.mismatched_row_ids),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
        }
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        payload = {
            "status": "blocked",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "formal_oos_allowed": False,
            "production_alpha_bp": 0,
            "production_action_allowed": False,
            "broker_order_allowed": False,
        }
        _emit(payload, args.output)
        return 2
    _emit(payload, args.output)
    return 0


def _emit(payload: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and output.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"refusing to overwrite different parity output: {output}")
        if not output.exists():
            output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def _configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
