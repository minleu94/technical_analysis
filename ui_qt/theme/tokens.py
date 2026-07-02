from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    app_bg: str
    surface_1: str
    surface_2: str
    surface_3: str
    border: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    success: str
    warning: str
    danger: str
    info: str
    accent_warm: str = "#d97706"
    data_positive: str = "#22c55e"
    data_negative: str = "#ef4444"
    data_neutral: str = "#a8b3c2"
    table_hover: str = "#20334a"
    table_selected: str = "#1d4f6b"
    border_subtle: str = "#1f2937"
    radius_panel: int = 6
    radius_badge: int = 4
    font_family: str = "'Microsoft JhengHei UI', 'Segoe UI', Arial"
    mono_family: str = "Consolas, 'Cascadia Mono', monospace"


MIDNIGHT_ANALYST = ThemeTokens(
    app_bg="#070b12",
    surface_1="#101722",
    surface_2="#182231",
    surface_3="#223047",
    border="#2a3548",
    text_primary="#eef3f8",
    text_secondary="#a8b3c2",
    text_muted="#788496",
    accent="#4fb7e5",
    accent_hover="#75cdf5",
    success="#22c55e",
    warning="#f6b44b",
    danger="#f05b5b",
    info="#77aef5",
    accent_warm="#d97706",
    data_positive="#22c55e",
    data_negative="#ef4444",
    data_neutral="#a8b3c2",
    table_hover="#20334a",
    table_selected="#1d4f6b",
    border_subtle="#1f2937",
)
