from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from scripts.test_fubon_readonly_marketdata import SERVICE, USERNAME, run_probe


@dataclass(frozen=True)
class _Login:
    is_success: bool
    message: str = ""


class _SDK:
    def __init__(self, *, login: _Login) -> None:
        self.login = login
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        snapshot = SimpleNamespace(quotes=self._quotes)
        stock = SimpleNamespace(snapshot=snapshot)
        rest_client = SimpleNamespace(stock=stock)
        self.marketdata = SimpleNamespace(rest_client=rest_client)

    def apikey_login(self, *args: Any) -> _Login:
        self.calls.append(("apikey_login", args, {}))
        return self.login

    def init_realtime(self) -> None:
        self.calls.append(("init_realtime", (), {}))

    def _quotes(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(("quotes", (), kwargs))
        return {"data": []}


def test_probe_fails_closed_when_credentials_are_missing() -> None:
    sdk_created = False
    credential_loaded = False

    def sdk_factory() -> _SDK:
        nonlocal sdk_created
        sdk_created = True
        return _SDK(login=_Login(True))

    def load_api_key(service: str, username: str) -> None:
        nonlocal credential_loaded
        credential_loaded = True

    messages: list[str] = []
    result = run_probe(
        environ={},
        api_key_loader=load_api_key,
        sdk_factory=sdk_factory,
        output=messages.append,
    )

    assert result == 2
    assert sdk_created is False
    assert credential_loaded is False
    assert messages == ["missing FUBON_PERSONAL_ID, FUBON_CERT_PATH, or Windows Credential Manager API key"]


def test_probe_stops_after_failed_login() -> None:
    sdk = _SDK(login=_Login(False, "denied"))
    result = run_probe(
        environ={"FUBON_PERSONAL_ID": "id", "FUBON_CERT_PATH": "cert"},
        api_key_loader=lambda service, username: "key",
        sdk_factory=lambda: sdk,
        output=lambda message: None,
    )

    assert result == 1
    assert [call[0] for call in sdk.calls] == ["apikey_login"]


def test_probe_uses_only_otc_snapshot_after_successful_login() -> None:
    sdk = _SDK(login=_Login(True))
    credential_request: list[tuple[str, str]] = []

    def load_api_key(service: str, username: str) -> str:
        credential_request.append((service, username))
        return "key"

    result = run_probe(
        environ={"FUBON_PERSONAL_ID": "id", "FUBON_CERT_PATH": "cert", "FUBON_CERT_PASS": "pass"},
        api_key_loader=load_api_key,
        sdk_factory=lambda: sdk,
        output=lambda message: None,
    )

    assert result == 0
    assert credential_request == [(SERVICE, USERNAME)]
    assert sdk.calls == [
        ("apikey_login", ("id", "key", "cert", "pass"), {}),
        ("init_realtime", (), {}),
        ("quotes", (), {"market": "OTC"}),
    ]
