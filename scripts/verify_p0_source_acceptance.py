"""Build a non-applying P0 source acceptance review package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.p0_shadow_observation import P0ShadowObservation
from data_module.p0_source_acceptance_verifier import P0SourceAcceptanceVerifier


def _observation(payload: dict[str, Any]) -> P0ShadowObservation:
    return P0ShadowObservation(
        source_id=str(payload.get("source_id", "")),
        symbol=str(payload.get("symbol", "")),
        decision_date=str(payload.get("decision_date", "")),
        available_date=payload.get("available_date"),
        source_version=str(payload.get("source_version", "")),
        status=str(payload.get("status", "blocked")),
        diagnostics=tuple(str(item) for item in payload.get("diagnostics", ())),
        raw_payload=dict(payload.get("raw_payload", {})),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-coverage-bp", type=int, default=8000)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    result = P0SourceAcceptanceVerifier(
        minimum_coverage_bp=args.minimum_coverage_bp
    ).verify(
        source_id=str(payload["source_id"]),
        decision_date=str(payload.get("decision_date", "")),
        observations=tuple(_observation(item) for item in payload.get("observations", ())),
        coverage_bp=int(payload.get("coverage_bp", -1)),
        license_evidence=str(payload.get("license_evidence", "")),
        quality_evidence=str(payload.get("quality_evidence", "")),
    )
    output = result.to_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
