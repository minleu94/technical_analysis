"""Read-only / TEMP-only CLI tool for Fubon market-data shadow decision inspection.

Performs Point-in-Time safe evaluation of candidate Fubon market-data shadow decisions
(Score, Recommendation, Portfolio, Exit / Position Health) against Baseline Rule-only
results, prints JSON to stdout by default, and enforces path safety if an output root is provided.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.fubon_shadow_authorization import FubonShadowComputationAuthorization
from data_module.fubon_shadow_candidate_repository import FubonShadowCandidateRepository
from app_module.fubon_shadow_decision_service import FubonShadowDecisionService


def is_path_safe(path: Path) -> bool:
    """Validate path is strictly isolated from formal data roots and repository."""
    try:
        resolved = path.resolve()
    except Exception:
        return False

    data_root = Path(os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")).resolve()
    output_root = Path(os.environ.get("OUTPUT_ROOT", "D:/Min/Python/Project/FA_Data/output")).resolve()
    sqlite_dir = data_root / "sqlite"
    repo_root = Path(__file__).resolve().parents[1].resolve()

    for forbidden in (data_root, output_root, sqlite_dir, repo_root):
        if resolved == forbidden or resolved.is_relative_to(forbidden):
            return False
    return True


def validate_output_root(output_root: Path) -> Path:
    """Enforce explicit safe shadow output root under TEMP or authorized directory."""
    if not output_root.is_absolute():
        raise ValueError("output_root must be an absolute path")

    try:
        resolved = output_root.resolve()
    except Exception as exc:
        raise ValueError(f"cannot resolve output_root: {exc}") from exc

    if not is_path_safe(resolved):
        raise ValueError("output_root cannot be inside formal data root, market DB, or repo root")

    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    parser = argparse.ArgumentParser(description="Read-only Fubon Shadow Decision Inspection CLI")
    parser.add_argument("--authorization", type=Path, help="JSON file containing Fubon shadow authorization")
    parser.add_argument("--input", type=Path, help="JSON/JSONL file containing Fubon observations")
    parser.add_argument("--decision-timestamp", help="Explicit ISO-8601 decision timestamp")
    parser.add_argument("--strategy-config", type=Path, help="Explicit strategy configuration JSON")
    parser.add_argument("--output-root", type=Path, help="Explicit safe shadow output root (e.g. $env:TEMP/technical_analysis_fubon_shadow)")
    parser.add_argument("--candidate-db", type=Path, help="Optional isolated candidate/shadow SQLite DB")
    parser.add_argument("--format", choices=["json"], default="json", help="Output format")

    parser.add_argument("--universe", type=Path, help="CSV or JSON file containing market universe dataframe")
    args = parser.parse_args(argv)

    if not args.input or not args.input.exists():
        err_payload = {
            "error_code": "fubon_cli_missing_input_file",
            "message": "Explicit --input observation file is required and must exist.",
        }
        print(json.dumps(err_payload, ensure_ascii=False))
        return 1

    if not args.universe or not args.universe.exists():
        err_payload = {
            "error_code": "fubon_cli_missing_universe_file",
            "message": "Explicit --universe market data file is required and must exist.",
        }
        print(json.dumps(err_payload, ensure_ascii=False))
        return 1

    if not args.strategy_config or not args.strategy_config.exists():
        print(
            json.dumps(
                {
                    "error_code": "fubon_cli_missing_strategy_config",
                    "message": "Explicit --strategy-config JSON file is required.",
                },
                ensure_ascii=False,
            )
        )
        return 1
    if not args.decision_timestamp:
        print(
            json.dumps(
                {
                    "error_code": "fubon_cli_missing_decision_timestamp",
                    "message": "Explicit --decision-timestamp is required.",
                },
                ensure_ascii=False,
            )
        )
        return 1
    decision_timestamp = args.decision_timestamp

    # Load Authorization
    if args.authorization and args.authorization.exists():
        auth_data = json.loads(args.authorization.read_text(encoding="utf-8"))
        authorization = FubonShadowComputationAuthorization.from_dict(auth_data)
    else:
        authorization = FubonShadowComputationAuthorization()

    # Load Observations
    raw_observations: list[dict[str, Any]] = []
    raw_text = args.input.read_text(encoding="utf-8").strip()
    if raw_text.startswith("["):
        raw_observations = json.loads(raw_text)
    else:
        for line in raw_text.splitlines():
            if line.strip():
                raw_observations.append(json.loads(line))

    # Load Universe DataFrame
    if str(args.universe).endswith(".csv"):
        universe_df = pd.read_csv(args.universe)
    else:
        universe_df = pd.read_json(args.universe)

    strategy_config = json.loads(args.strategy_config.read_text(encoding="utf-8"))
    if not isinstance(strategy_config, dict):
        print(
            json.dumps(
                {
                    "error_code": "fubon_cli_invalid_strategy_config",
                    "message": "Strategy configuration root must be an object.",
                },
                ensure_ascii=False,
            )
        )
        return 1

    service = FubonShadowDecisionService(authorization)
    bundle = service.evaluate_shadow_decision(
        raw_observations=raw_observations,
        decision_timestamp=decision_timestamp,
        universe_df=universe_df,
        strategy_config=strategy_config,
    )

    output_payload = bundle.to_dict()
    if args.candidate_db:
        validation = service.pit_validator.validate_batch(
            raw_observations, decision_timestamp
        )
        repository = FubonShadowCandidateRepository(args.candidate_db)
        persistence = repository.save_shadow_decision_bundle(
            bundle,
            (
                validation.accepted_observations
                + validation.degraded_observations
                + validation.quarantined_observations
            ),
        )
        output_payload["candidate_persistence"] = persistence.to_dict()
    output_json = json.dumps(
        _redact_secrets(output_payload),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )

    if args.output_root:
        safe_root = validate_output_root(args.output_root)
        safe_root.mkdir(parents=True, exist_ok=True)
        outfile = safe_root / f"{bundle.run_id}.json"
        outfile.write_text(output_json, encoding="utf-8")

    print(output_json)
    return 0


def _redact_secrets(value: Any) -> Any:
    """Recursively redact sensitive values based on normalized key names."""
    sensitive_tokens = (
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "personal_id",
        "authorization_header",
    )
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(token in str(key).lower() for token in sensitive_tokens)
                else _redact_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_secrets(item) for item in value]
    return value


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
