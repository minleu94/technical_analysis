"""建立 Formal 三項受控路徑的唯讀 attestation／handoff plan。

公開入口只讀目前程序的 effective environment、正式 consumer 與明確傳入的
proposed 路徑；不會自動尋找最新 clock、不會複製 candidate、不會修改
Windows registry／process environment／D 原始資料，也不會啟動訓練或下單。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_controlled_handoff import (
    FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION,
    FormalControlledHandoffError,
    build_formal_controlled_handoff_plan,
    write_immutable_formal_controlled_handoff_plan,
)
from data_module.prospective_activation_environment import FORMAL_PATH_ENV_NAMES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-db", type=Path, required=True)
    parser.add_argument("--training-as-of", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--development-output-root", type=Path, required=True)
    parser.add_argument("--proposed-portfolio-ledger", type=Path)
    parser.add_argument("--proposed-rule-history", type=Path)
    parser.add_argument("--proposed-pit-sector", type=Path)
    parser.add_argument("--proposed-clock-manifest", type=Path)
    parser.add_argument("--proposed-identity-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    proposed_paths = {
        FORMAL_PATH_ENV_NAMES[0]: args.proposed_portfolio_ledger,
        FORMAL_PATH_ENV_NAMES[1]: args.proposed_rule_history,
        FORMAL_PATH_ENV_NAMES[2]: args.proposed_pit_sector,
    }
    try:
        plan = build_formal_controlled_handoff_plan(
            market_db=args.market_db,
            training_as_of=args.training_as_of,
            output_root=args.output_root,
            development_output_root=args.development_output_root,
            now=datetime.now(timezone.utc),
            proposed_paths=proposed_paths,
            proposed_clock_manifest=args.proposed_clock_manifest,
            proposed_identity_manifest=args.proposed_identity_manifest,
        )
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        file_hash = write_immutable_formal_controlled_handoff_plan(output, plan)
    except (OSError, ValueError, FormalControlledHandoffError) as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "schema_version": FORMAL_CONTROLLED_HANDOFF_SCHEMA_VERSION,
                "status": plan["status"],
                "blockers": cast(dict[str, object], plan["proposed_controlled_configuration"])[
                    "blockers"
                ],
                "plan_hash": plan["plan_hash"],
                "file_hash": file_hash,
                "read_only": True,
                "writes_windows_environment": False,
                "secret_values_emitted": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())
