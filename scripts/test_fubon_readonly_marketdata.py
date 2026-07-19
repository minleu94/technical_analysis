"""Manual-only Fubon market-data connection test; never calls trading or account APIs."""
from __future__ import annotations

import os
import sys

import keyring


SERVICE = "fubon-neo-readonly-api-key"
USERNAME = "market-data"


def main() -> int:
    personal_id = os.environ.get("FUBON_PERSONAL_ID", "").strip()
    cert_path = os.environ.get("FUBON_CERT_PATH", "").strip()
    cert_pass = os.environ.get("FUBON_CERT_PASS", "").strip() or personal_id
    api_key = keyring.get_password(SERVICE, USERNAME)
    if not all((personal_id, cert_path, api_key)):
        print("missing FUBON_PERSONAL_ID, FUBON_CERT_PATH, or Windows Credential Manager API key")
        return 2

    from fubon_neo.sdk import FubonSDK

    sdk = FubonSDK()
    login = sdk.apikey_login(personal_id, api_key, cert_path, cert_pass)
    if not login.is_success:
        print(f"login failed: {login.message}")
        return 1
    sdk.init_realtime()
    quotes = sdk.marketdata.rest_client.stock.snapshot.quotes(market="OTC")
    print(f"read-only market-data connection succeeded; OTC snapshot response type={type(quotes).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
