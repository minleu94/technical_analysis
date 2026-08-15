"""Small fail-soft console setup for direct Windows CLI execution."""

from __future__ import annotations

import sys


def configure_utf8_console() -> None:
    """Keep CLI help/errors printable without exposing or rewriting payloads."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # Some embedded/test streams do not support reconfiguration.
            continue
