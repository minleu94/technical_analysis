"""Manual-only Fubon market-data connection test; never calls trading or account APIs."""
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any


SERVICE = "fubon-neo-readonly-api-key"
USERNAME = "market-data"


def run_probe(
    *,
    environ: Mapping[str, str],
    api_key_loader: Callable[[str, str], str | None],
    sdk_factory: Callable[[], Any],
    output: Callable[[str], None] = print,
) -> int:
    """Run the bounded OTC quote probe with explicitly injected dependencies."""
    personal_id = environ.get("FUBON_PERSONAL_ID", "").strip()
    cert_path = environ.get("FUBON_CERT_PATH", "").strip()
    cert_pass = environ.get("FUBON_CERT_PASS", "").strip() or personal_id
    if not personal_id or not cert_path:
        output("missing FUBON_PERSONAL_ID, FUBON_CERT_PATH, or Windows Credential Manager API key")
        return 2
    api_key = api_key_loader(SERVICE, USERNAME)
    if not api_key:
        output("missing FUBON_PERSONAL_ID, FUBON_CERT_PATH, or Windows Credential Manager API key")
        return 2

    sdk = sdk_factory()
    login = sdk.apikey_login(personal_id, api_key, cert_path, cert_pass)
    if not login.is_success:
        output(f"login failed: {login.message}")
        return 1
    sdk.init_realtime()
    quotes = sdk.marketdata.rest_client.stock.snapshot.quotes(market="OTC")
    output(f"read-only market-data connection succeeded; OTC snapshot response type={type(quotes).__name__}")
    return 0


def main() -> int:
    def load_api_key(service: str, username: str) -> str | None:
        from keyring import get_password

        return get_password(service, username)

    def create_sdk() -> Any:
        from fubon_neo.sdk import FubonSDK

        return FubonSDK()

    return run_probe(environ=os.environ, api_key_loader=load_api_key, sdk_factory=create_sdk)


if __name__ == "__main__":
    raise SystemExit(main())
