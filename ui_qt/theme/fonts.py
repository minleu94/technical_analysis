from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable


_REGISTERED_FONT_FAMILIES: tuple[str, ...] = ()
_CHINESE_FONT_MARKERS = ("JhengHei", "Noto Sans TC", "MingLiU", "PMingLiU", "YaHei")


def default_chinese_font_paths() -> tuple[Path, ...]:
    windows_root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    fonts_dir = windows_root / "Fonts"
    return (
        fonts_dir / "msjh.ttc",
        fonts_dir / "NotoSansTC-VF.ttf",
        fonts_dir / "mingliu.ttc",
        fonts_dir / "msyh.ttc",
    )


def register_qt_chinese_fonts(
    *,
    qfont_database: Any | None = None,
    font_paths: Iterable[Path] | None = None,
) -> tuple[str, ...]:
    """Register CJK-capable fonts for Qt offscreen screenshot evidence."""
    global _REGISTERED_FONT_FAMILIES
    use_cache = qfont_database is None and font_paths is None
    if use_cache and _REGISTERED_FONT_FAMILIES:
        return _REGISTERED_FONT_FAMILIES

    if qfont_database is None:
        from PySide6.QtGui import QFontDatabase

        qfont_database = QFontDatabase

    existing_families = tuple(str(family) for family in qfont_database.families())
    if _has_chinese_font(existing_families):
        if use_cache:
            _REGISTERED_FONT_FAMILIES = existing_families
        return existing_families

    loaded: list[str] = []
    for path in font_paths or default_chinese_font_paths():
        if not path.exists():
            continue
        font_id = qfont_database.addApplicationFont(str(path))
        if font_id < 0:
            continue
        loaded.extend(str(family) for family in qfont_database.applicationFontFamilies(font_id))

    registered_families = tuple(dict.fromkeys(loaded))
    if use_cache:
        _REGISTERED_FONT_FAMILIES = registered_families
    return registered_families


def preferred_qt_chinese_font_family(families: Iterable[str]) -> str | None:
    family_list = tuple(families)
    for marker in _CHINESE_FONT_MARKERS:
        for family in family_list:
            if marker in family:
                return family
    return family_list[0] if family_list else None


def _has_chinese_font(families: Iterable[str]) -> bool:
    return any(marker in family for marker in _CHINESE_FONT_MARKERS for family in families)
