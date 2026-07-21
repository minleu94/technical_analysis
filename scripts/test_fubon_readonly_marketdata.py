"""Manual-only Fubon market-data connection test; never calls trading or account APIs."""
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

from data_module.fubon_readonly_runtime import (
    API_KEY_SERVICE,
    USERNAME,
    load_fubon_readonly_runtime,
)

SERVICE = API_KEY_SERVICE


def run_probe(
    *,
    environ: Mapping[str, str],
    api_key_loader: Callable[[str, str], str | None],
    sdk_factory: Callable[[], Any],
    output: Callable[[str], None] = print,
) -> int:
    """Run the bounded OTC quote probe with explicitly injected dependencies."""
    credentials = load_fubon_readonly_runtime(environ, api_key_loader)
    if credentials is None:
        output("missing Fubon read-only credentials (environment or Windows Credential Manager)")
        return 2

    sdk = sdk_factory()
    login = sdk.apikey_login(
        credentials.personal_id,
        credentials.api_key,
        credentials.cert_path,
        credentials.cert_pass,
    )
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
