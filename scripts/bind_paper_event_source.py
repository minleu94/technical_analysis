"""將 Paper candidate 綁定 durable session capture 後交給 Formal consumer。

此步驟是 EOD Paper writer 與 Formal input producer 之間的受控 consumer。
它只讀既有 candidate／durable capture，並在受控 output 下建立新的 bound
candidate；不改寫原 candidate、Paper ledger、行情 DB 或 D 槽來源。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.paper_event_source_capture import (  # noqa: E402
    PaperEventSourceCaptureError,
    bind_paper_candidate_file_to_capture,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-candidate", type=Path, required=True)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = bind_paper_candidate_file_to_capture(
            args.paper_candidate,
            capture_manifest_path=args.capture_manifest,
            output_path=args.output_path,
        )
    except (OSError, TypeError, ValueError, PaperEventSourceCaptureError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(error).__name__,
                    "reason": str(error),
                    "formal_credit": False,
                    "broker_order_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
