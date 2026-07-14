"""以隔離輸入輸出執行純 metadata 的 2025 OOS custody 稽核。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml_module.oos_exposure_custody import (
    AuditEvidenceMetadata,
    OOSExposureCustodyAuditor,
    OOSExposureCustodyRequest,
    SignedCustodyDeclaration,
)


_FORBIDDEN_METADATA_TERMS = frozenset(
    {"2025", "outcome", "return", "metric", "ranking", "report", "payload"}
)
_EVIDENCE_METADATA_KEYS = frozenset(
    {"evidence_id", "sha256", "recorded_at", "access_state"}
)
_DECLARATION_METADATA_KEYS = frozenset(
    {
        "declaration_id",
        "reviewer_identity",
        "signed_at",
        "declares_no_design_influence",
    }
)
_ALL_METADATA_KEYS = _EVIDENCE_METADATA_KEYS | _DECLARATION_METADATA_KEYS


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation-manifest-metadata", required=True, type=Path)
    parser.add_argument("--access-inventory", required=True, type=Path)
    parser.add_argument("--signed-declaration", type=Path)
    parser.add_argument("--isolated-output-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def _validate_metadata_path(path: Path) -> None:
    normalized_name = path.name.casefold()
    if path.suffix.casefold() != ".json" or any(
        term in normalized_name for term in _FORBIDDEN_METADATA_TERMS
    ):
        raise ValueError("unsafe_metadata_path")


def _load_object(
    path: Path,
    allowed_keys: frozenset[str] = _ALL_METADATA_KEYS,
) -> dict[str, object]:
    _validate_metadata_path(path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"metadata object required: {path.name}")
    keys = {str(key).casefold() for key in loaded}
    if (
        not keys.issubset(allowed_keys)
        or any(term in key for key in keys for term in _FORBIDDEN_METADATA_TERMS)
    ):
        raise ValueError("metadata_key_not_allowed")
    return loaded


def _evidence(path: Path) -> AuditEvidenceMetadata:
    values = _load_object(path, _EVIDENCE_METADATA_KEYS)
    return AuditEvidenceMetadata(**values)  # type: ignore[arg-type]


def _declaration(path: Path | None) -> SignedCustodyDeclaration | None:
    if path is None:
        return None
    values = _load_object(path, _DECLARATION_METADATA_KEYS)
    return SignedCustodyDeclaration(**values)  # type: ignore[arg-type]


def _isolated_output(output: Path, isolated_root: Path) -> Path:
    resolved_output = output.resolve()
    resolved_root = isolated_root.resolve()
    if resolved_output == resolved_root or resolved_root not in resolved_output.parents:
        raise ValueError("output_must_be_under_explicit_isolated_root")
    return resolved_output


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        output = _isolated_output(args.output, args.isolated_output_root)
        if output.exists():
            raise FileExistsError("append_only_output_already_exists")
        request = OOSExposureCustodyRequest(
            generation_manifest=_evidence(args.generation_manifest_metadata),
            access_inventory=_evidence(args.access_inventory),
            signed_declaration=_declaration(args.signed_declaration),
            influence_dimensions=(),
        )
        report = OOSExposureCustodyAuditor().audit(request)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.canonical_json() + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": report.status,
                "report_sha256": report.canonical_sha256(),
                "oos_payload_read": False,
                "training_performed": False,
                "formal_oos_changed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
