import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app_module.research_session import ResearchSessionStore
from ui_qt.widgets.session_context_strip import SessionContextStrip


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_session_context_strip_elides_context_in_compact_viewport():
    app()
    strip = SessionContextStrip(ResearchSessionStore())
    strip.resize(140, 18)
    strip.show()
    app().processEvents()

    # Frame/layout chrome may contribute a small fixed edge width; the
    # session label itself must remain yieldable.
    assert strip.minimumWidth() <= 20
    assert strip.context_label.minimumWidth() == 0
    assert "…" in strip.context_label.text()
    assert strip.context_label.text() != strip._full_context_text


def test_session_context_strip_restores_full_context_when_space_is_available():
    app()
    strip = SessionContextStrip(ResearchSessionStore())
    strip.resize(900, 18)
    strip.show()
    app().processEvents()

    assert strip.context_label.text() == strip._full_context_text
