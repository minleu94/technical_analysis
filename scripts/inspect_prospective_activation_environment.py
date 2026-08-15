"""Read-only inspector for prospective activation environment custody."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.prospective_activation_environment import (
    ProspectiveActivationEnvironmentError,
    build_prospective_activation_environment_preflight,
    write_immutable_activation_environment_preflight,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_prospective_activation_environment_preflight()
        file_hash = None
        if args.output is not None:
            file_hash = write_immutable_activation_environment_preflight(
                args.output,
                report,
            )
    except (OSError, ValueError, ProspectiveActivationEnvironmentError) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    controlled_store = cast(Mapping[str, object], report["controlled_store"])
    hmac_store = cast(Mapping[str, object], report["hmac_secret_store"])
    summary = {
        "status": report["status"],
        "blockers": report["blockers"],
        "controlled_store_configured": controlled_store["configured"],
        "hmac_secret_store_configured": hmac_store["configured"],
        "activation_launch_allowed": False,
        "heavy_rebuild_launch_allowed": False,
        "formal_oos_allowed": False,
        "promotion_eligible": False,
        "secret_values_emitted": False,
    }
    if file_hash is not None:
        summary["file_hash"] = file_hash
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
