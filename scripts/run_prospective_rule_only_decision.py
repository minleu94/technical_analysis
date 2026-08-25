"""Create one activation-time prospective Rule-only source artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from development_module.prospective_rule_only_decision import (  # noqa: E402
    ProspectiveRuleOnlyDecisionError,
    produce_prospective_rule_only_decision,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-output-root", required=True)
    parser.add_argument("--market-db", required=True)
    parser.add_argument("--clock-manifest", required=True)
    parser.add_argument("--universe-symbols-json", required=True)
    parser.add_argument("--owner-acceptance-json", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = produce_prospective_rule_only_decision(
            development_output_root=args.development_output_root,
            market_db=args.market_db,
            clock_manifest_path=args.clock_manifest,
            universe_symbols_json=args.universe_symbols_json,
            owner_acceptance_json=args.owner_acceptance_json,
        )
    except (OSError, TypeError, ValueError, KeyError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                    "promotion_eligible": False,
                    "broker_order_allowed": False,
                    "secret_values_emitted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    from runtime.console_encoding import configure_utf8_console

    configure_utf8_console()
    raise SystemExit(main())

