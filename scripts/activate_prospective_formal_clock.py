"""Fixture-only CLI for publishing a prospective PFS-07 activation manifest.

The optional ``--controlled-environment`` source reads the three formal paths
and the non-secret store identity through the shared Windows controlled
environment reader.  It never reads or prints the HMAC secret, changes the
environment, starts a watcher, or launches Direct/OOC.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, cast

from data_module.prospective_calibration_policy import (
    load_prospective_calibration_policy,
)
from data_module.prospective_formal_clock import load_clock_manifest
from data_module.prospective_formal_clock_activation import (
    ProspectiveClockActivationError,
    build_prospective_clock_activation_manifest,
    write_immutable_clock_activation_manifest,
)
from data_module.prospective_activation_environment import (
    CONTROLLED_STORE_ID_ENV_NAME,
    FORMAL_PATH_ENV_NAMES,
    ProspectiveActivationEnvironmentError,
    build_prospective_activation_environment_preflight,
    resolve_controlled_store_id,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-only", action="store_true")
    parser.add_argument("--clock-manifest", type=Path, required=True)
    parser.add_argument("--calibration-policy", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--portfolio-ledger-path", type=Path)
    parser.add_argument("--rule-history-path", type=Path)
    parser.add_argument("--pit-sector-path", type=Path)
    parser.add_argument("--controlled-store-id")
    parser.add_argument("--hmac-secret-store-configured", action="store_true")
    parser.add_argument(
        "--controlled-environment",
        action="store_true",
        help=(
            "read formal paths/store identity from the shared Windows controlled "
            "environment; still requires --fixture-only"
        ),
    )
    parser.add_argument("--owner-activation-id", required=True)
    parser.add_argument("--owner-activation-timestamp", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.fixture_only:
        print(
            "refusing activation CLI without explicit --fixture-only; "
            "this command never writes Windows environment variables",
            file=sys.stderr,
        )
        return 2
    if args.controlled_environment and any(
        value is not None
        for value in (
            args.portfolio_ledger_path,
            args.rule_history_path,
            args.pit_sector_path,
            args.controlled_store_id,
        )
    ):
        print(
            "blocked: --controlled-environment forbids explicit formal paths/store id",
            file=sys.stderr,
        )
        return 2
    try:
        if args.controlled_environment:
            environment_report = build_prospective_activation_environment_preflight()
            blockers = list(cast(list[object], environment_report["blockers"]))
            store_id = resolve_controlled_store_id()
            if store_id is None:
                blockers.append(f"{CONTROLLED_STORE_ID_ENV_NAME}:missing")
            hmac_store = cast(Mapping[str, object], environment_report["hmac_secret_store"])
            if hmac_store.get("configured") is not True:
                blockers.append("RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY:missing")
            if blockers:
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "reason": "controlled environment preflight is not ready",
                            "environment_status": environment_report["status"],
                            "environment_blockers": sorted(set(blockers)),
                            "heavy_rebuild_launch_allowed": False,
                            "formal_oos_allowed": False,
                            "secret_values_emitted": False,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                return 2
            formal_paths = cast(dict[str, object], environment_report["formal_paths"])
            resolved_paths: dict[str, Path] = {}
            for name in FORMAL_PATH_ENV_NAMES:
                entry = formal_paths.get(name)
                if not isinstance(entry, Mapping):
                    raise ProspectiveActivationEnvironmentError(
                        f"controlled environment path entry is invalid: {name}"
                    )
                value = entry.get("path")
                if not isinstance(value, str) or not value:
                    raise ProspectiveActivationEnvironmentError(
                        f"controlled environment path is invalid: {name}"
                    )
                resolved_paths[name] = Path(value)
            if store_id is None:  # pragma: no cover - guarded above
                raise ProspectiveActivationEnvironmentError(
                    f"{CONTROLLED_STORE_ID_ENV_NAME} is missing"
                )
            portfolio_path = resolved_paths[FORMAL_PATH_ENV_NAMES[0]]
            rule_path = resolved_paths[FORMAL_PATH_ENV_NAMES[1]]
            pit_path = resolved_paths[FORMAL_PATH_ENV_NAMES[2]]
            controlled_store_id = store_id
            hmac_configured = True
        else:
            if any(
                value is None
                for value in (
                    args.portfolio_ledger_path,
                    args.rule_history_path,
                    args.pit_sector_path,
                    args.controlled_store_id,
                )
            ):
                raise ProspectiveActivationEnvironmentError(
                    "fixture mode requires all three formal paths and controlled store id"
                )
            portfolio_path = args.portfolio_ledger_path
            rule_path = args.rule_history_path
            pit_path = args.pit_sector_path
            controlled_store_id = args.controlled_store_id
            hmac_configured = args.hmac_secret_store_configured
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        activation_timestamp = datetime.fromisoformat(
            args.owner_activation_timestamp.replace("Z", "+00:00")
        )
        clock = load_clock_manifest(args.clock_manifest, now=now)
        policy = load_prospective_calibration_policy(args.calibration_policy)
        readiness = _read_json_object(args.readiness_report)
        manifest = build_prospective_clock_activation_manifest(
            clock=clock,
            calibration_policy=policy,
            readiness_report=readiness,
            controlled_paths={
                "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH": portfolio_path,
                "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH": rule_path,
                "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH": pit_path,
            },
            controlled_store_id=controlled_store_id,
            hmac_secret_store_configured=hmac_configured,
            owner_activation_id=args.owner_activation_id,
            owner_activation_timestamp=activation_timestamp,
            now=now,
        )
        file_hash = write_immutable_clock_activation_manifest(args.output, manifest)
    except (
        OSError,
        ValueError,
        ProspectiveClockActivationError,
        ProspectiveActivationEnvironmentError,
    ) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "clock_id": manifest["clock_id"],
                "activation_trading_day": manifest["activation_trading_day"],
                "manifest_hash": manifest["manifest_hash"],
                "file_hash": file_hash,
                "heavy_rebuild_launch_allowed": False,
                "formal_oos_allowed": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _read_json_object(path: Path) -> dict[str, object]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("readiness report root must be an object")
    return raw


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
