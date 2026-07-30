"""等待 direct numeric store 完成，驗證 custody 後自動啟動 OOC v5 訓練。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-process-id", type=int, required=True)
    parser.add_argument("--store-output-dir", type=Path, required=True)
    parser.add_argument("--training-output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8_192)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--memory-budget-mb", type=int, default=4_096)
    parser.add_argument("--ridge-alpha-bp", type=int, default=100)
    parser.add_argument("--logistic-iterations", type=int, default=6)
    parser.add_argument("--hgb-max-iter", type=int, default=100)
    parser.add_argument("--hgb-max-fit-rows", type=int, default=250_000)
    parser.add_argument("--poll-seconds", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_streams()
    args = _parser().parse_args(argv)
    status_path = args.training_output_dir.resolve() / "continuation_status.json"
    try:
        _wait_for_expected_process(
            process_id=args.direct_process_id,
            expected_text=str(args.store_output_dir.resolve()),
            poll_seconds=args.poll_seconds,
        )
        store_manifest_path, store_manifest = _validated_store_manifest(
            args.store_output_dir.resolve()
        )
        _atomic_write_json(
            status_path,
            {
                "status": "store_validated_training_starting",
                "store_manifest_path": str(store_manifest_path),
                "store_manifest_hash": store_manifest["manifest_hash"],
                "direct_store_complete": True,
                "full_market_ready": store_manifest["execution"][
                    "full_market_ready"
                ],
                "readiness_failed_checks": store_manifest["execution"][
                    "readiness_failed_checks"
                ],
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
        )
        command = [
            sys.executable,
            str(ROOT / "scripts" / "train_ml_allocation_out_of_core.py"),
            "--store-manifest",
            str(store_manifest_path),
            "--output-dir",
            str(args.training_output_dir.resolve()),
            "--batch-size",
            str(args.batch_size),
            "--workers",
            str(args.workers),
            "--memory-budget-mb",
            str(args.memory_budget_mb),
            "--ridge-alpha-bp",
            str(args.ridge_alpha_bp),
            "--logistic-iterations",
            str(args.logistic_iterations),
            "--hgb-max-iter",
            str(args.hgb_max_iter),
            "--hgb-max-fit-rows",
            str(args.hgb_max_fit_rows),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "OOC training command failed with exit code "
                f"{completed.returncode}"
            )
        training_path, training = _latest_manifest(
            args.training_output_dir.resolve()
        )
        replay_status_path = (
            training_path.parent
            / "artifacts"
            / "oos_portfolio_replay_inputs"
            / "build_status.json"
        )
        replay_status = (
            _read_json(replay_status_path)
            if replay_status_path.is_file()
            else {
                "status": "blocked",
                "blockers": ["replay_input_build_status_missing"],
            }
        )
        _atomic_write_json(
            status_path,
            {
                "status": "complete",
                "store_manifest_path": str(store_manifest_path),
                "store_manifest_hash": store_manifest["manifest_hash"],
                "training_manifest_path": str(training_path),
                "training_manifest_hash": training["manifest_hash"],
                "training_schema_version": training["schema_version"],
                "base_expert_count": training["base_expert_count"],
                "meta_fold_count": training["meta_fold_count"],
                "replay_input_status": replay_status["status"],
                "replay_input_blockers": replay_status.get(
                    "blockers",
                    [],
                ),
                "replay_input_manifest_path": replay_status.get(
                    "manifest_path"
                ),
                "replay_input_manifest_hash": replay_status.get(
                    "manifest_hash"
                ),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
        )
        print(
            json.dumps(
                _read_json(status_path),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        _atomic_write_json(
            status_path,
            {
                "status": "blocked",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "formal_oos_allowed": False,
                "production_alpha_bp": 0,
            },
        )
        print(
            json.dumps(
                _read_json(status_path),
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


def _wait_for_expected_process(
    *,
    process_id: int,
    expected_text: str,
    poll_seconds: int,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError(
            "psutil is required for process custody"
        ) from exc
    while True:
        try:
            process = psutil.Process(process_id)
            command = " ".join(process.cmdline())
            if expected_text.casefold() not in command.casefold():
                return
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return
        time.sleep(poll_seconds)


def _validated_store_manifest(
    output_root: Path,
) -> tuple[Path, dict[str, Any]]:
    manifest_path, manifest = _latest_manifest(output_root)
    execution = _mapping(manifest.get("execution"), field_name="execution")
    if manifest.get("status") != "complete":
        raise RuntimeError("direct store manifest is not complete")
    if execution.get("direct_numeric_store") is not True:
        raise RuntimeError("latest store is not a direct numeric store")
    if execution.get("direct_store_complete") is not True:
        raise RuntimeError("direct numeric store is incomplete")
    if execution.get("memory_budget_enforced") is not True:
        raise RuntimeError("direct store memory budget was not enforced")
    if execution.get("within_memory_budget") is not True:
        raise RuntimeError("direct store exceeded memory budget")
    preflight = _mapping(
        execution.get("temporary_storage_preflight"),
        field_name="temporary_storage_preflight",
    )
    if preflight.get("within_budget") is not True:
        raise RuntimeError("direct store temporary preflight failed")
    if manifest.get("formal_source_only") is not True:
        raise RuntimeError("direct store is not formal-source-only")
    if manifest.get("research_shadow_included") is not False:
        raise RuntimeError("direct store includes research shadow data")
    if int(manifest.get("fold_count", 0)) < 4:
        raise RuntimeError("direct store has fewer than four folds")
    if int(manifest.get("row_count", 0)) <= 0:
        raise RuntimeError("direct store has no numeric rows")
    return manifest_path, manifest


def _latest_manifest(output_root: Path) -> tuple[Path, dict[str, Any]]:
    pointer = _read_json(output_root / "latest_manifest.json")
    relative = pointer.get("manifest_path")
    if not isinstance(relative, str) or not relative:
        raise TypeError("latest pointer manifest_path must be non-empty text")
    manifest_path = (output_root / relative).resolve()
    if not manifest_path.is_relative_to(output_root.resolve()):
        raise ValueError("latest pointer escapes output root")
    return manifest_path, _read_json(manifest_path)


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
