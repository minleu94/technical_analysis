"""Resolve Fubon read-only runtime values without placing secrets in the repository."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping


USERNAME = "market-data"
API_KEY_SERVICE = "fubon-neo-readonly-api-key"
PERSONAL_ID_SERVICE = "fubon-neo-readonly-personal-id"
CERT_PATH_SERVICE = "fubon-neo-readonly-cert-path"
CERT_PASS_SERVICE = "fubon-neo-readonly-cert-pass"


@dataclass(frozen=True)
class FubonReadOnlyRuntime:
    """Runtime-only values for the market-data lane; never serialize these."""

    api_key: str
    personal_id: str
    cert_path: str
    cert_pass: str


def load_fubon_readonly_runtime(
    environ: Mapping[str, str], password_loader: Callable[[str, str], str | None]
) -> FubonReadOnlyRuntime | None:
    """Prefer an explicitly injected process value, then Credential Manager."""

    def resolve(environment_name: str, service: str) -> str:
        return environ.get(environment_name, "").strip() or (password_loader(service, USERNAME) or "").strip()

    api_key = password_loader(API_KEY_SERVICE, USERNAME) or ""
    personal_id = resolve("FUBON_PERSONAL_ID", PERSONAL_ID_SERVICE)
    cert_path = _normalize_windows_path(resolve("FUBON_CERT_PATH", CERT_PATH_SERVICE))
    cert_pass = resolve("FUBON_CERT_PASS", CERT_PASS_SERVICE) or personal_id
    if not api_key or not personal_id or not cert_path:
        return None
    return FubonReadOnlyRuntime(
        api_key=api_key,
        personal_id=personal_id,
        cert_path=cert_path,
        cert_pass=cert_pass,
    )


def _normalize_windows_path(value: str) -> str:
    """Accept Explorer's quoted ``Copy as path`` form without logging it."""

    return value[1:-1] if len(value) >= 2 and value.startswith('"') and value.endswith('"') else value
