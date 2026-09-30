#!/usr/bin/env python3
import os as _os
import shutil as _sh
import tempfile as _tf

# Qt QSS url() no tolera espacios ni %20 en rutas de archivo.
# Copiamos el SVG a /tmp (sin espacios) y usamos esa ruta.
_src_svg = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", "..", "icons", "tab_close.svg"))
_tmp_svg = _os.path.join(_tf.gettempdir(), "katphi_tab_close.svg")
try:
    _sh.copy2(_src_svg, _tmp_svg)
    _TAB_CLOSE_SVG = _tmp_svg.replace("\\", "/")
except Exception:
    _TAB_CLOSE_SVG = ""

"""
Modern Theme Styles — Sistema de diseño unificado (Arc/Brave-inspired)

Filosofía: "cada píxel tiene un propósito". Interfaz que se retira y deja
al usuario centrado en el contenido web.

Tokens de diseño:
- SPACING: sistema de 4px
- RADIUS: radios consistentes en toda la app
- HEIGHTS: alturas fijas para componentes
- DARK / LIGHT: paletas de 3 superficies + 1 acento
"""

# ─── Design Tokens ────────────────────────────────────────────────────────────

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32}

RADIUS = {"sm": 4, "md": 6, "lg": 10, "pill": 20}

HEIGHTS = {
    "button_sm": 28, "button_md": 32,
    "input": 32, "navbar": 44, "tab": 32, "sidebar_header": 40,
}

# ─── Paletas de color ──────────────────────────────────────────────────────────

_DARK_TOKENS = {
    # 3 superficies — nada más
    "surface_0":      "#1A1A1A",
    "surface_1":      "#222222",
    "surface_2":      "#2A2A2A",
    "surface_hover":  "#303030",
    "surface_active": "#383838",

    # Texto — 3 niveles
    "text_primary":   "#F0F0F0",
    "text_secondary": "#A0A0A0",
    "text_muted":     "#606060",

    # Un solo acento — azul Brave
    "accent":         "#4B9EFF",
    "accent_hover":   "#67AFFF",
    "accent_subtle":  "rgba(75,158,255,0.12)",

    # Bordes sutiles
    "border":         "rgba(255,255,255,0.08)",
    "border_strong":  "rgba(255,255,255,0.14)",

    # Semánticos
    "success":  "#3FB950",
    "warning":  "#D29922",
    "error":    "#F85149",
    "tor":      "#7B61FF",

    # ── Aliases de compatibilidad con código heredado ──────────────────────────
    "bg_primary":   "#1A1A1A",
    "bg_secondary": "#222222",
    "bg_hover":     "#303030",
    "bg_active":    "#383838",
    "primary":      "#F0F0F0",
    "secondary":    "#A0A0A0",
    "urlbar_bg":    "#1A1A1A",
    "urlbar_border": "rgba(255,255,255,0.08)",
    "tab_bg":       "#1A1A1A",
    "tab_active":   "#222222",
    "shadow":       "rgba(0,0,0,0.5)",
}

_LIGHT_TOKENS = {
    "surface_0":      "#F5F5F5",
    "surface_1":      "#FFFFFF",
    "surface_2":      "#EEEEEE",
    "surface_hover":  "#E8E8E8",
    "surface_active": "#DCDCDC",

    "text_primary":   "#1A1A1A",
    "text_secondary": "#666666",
    "text_muted":     "#AAAAAA",

    "accent":         "#0066CC",
    "accent_hover":   "#0077EE",
    "accent_subtle":  "rgba(0,102,204,0.10)",

    "border":         "rgba(0,0,0,0.08)",
    "border_strong":  "rgba(0,0,0,0.14)",

    "success":  "#1A7F37",
    "warning":  "#9A6700",
    "error":    "#CF222E",
    "tor":      "#5E35B1",

    # ── Aliases de compatibilidad ─────────────────────────────────────────────
    "bg_primary":   "#FFFFFF",
    "bg_secondary": "#F5F5F5",
    "bg_hover":     "#E8E8E8",
    "bg_active":    "#DCDCDC",
    "primary":      "#1A1A1A",
    "secondary":    "#666666",
    "urlbar_bg":    "#F5F5F5",
    "urlbar_border": "rgba(0,0,0,0.08)",
    "tab_bg":       "#F5F5F5",
    "tab_active":   "#FFFFFF",
    "shadow":       "rgba(0,0,0,0.14)",
}


# ─── Funciones de estilo ───────────────────────────────────────────────────────

def get_nav_button_style(theme_colors: dict) -> str:
    """
    Botón de navegación (atrás, adelante, refresh) — estilo Brave.
    32×32px, border-radius 6px. Sin borde. Icono 16px.
    """
    hover_bg = theme_colors.get("surface_hover", theme_colors.get("bg_hover", "#303030"))
    active_bg = theme_colors.get("surface_active", theme_colors.get("bg_active", "#383838"))
    return f"""
        QPushButton {{
            background: transparent;
            border: none;
            border-radius: 6px;
            min-width: 32px;
            max-width: 32px;
            min-height: 32px;
            max-height: 32px;
            padding: 0px;
            color: {theme_colors.get('text_secondary', theme_colors.get('secondary', '#A0A0A0'))};
        }}
        QPushButton:hover {{
            background: {hover_bg};
            color: {theme_colors.get('text_primary', theme_colors.get('primary', '#F0F0F0'))};
        }}
        QPushButton:pressed {{
            background: {active_bg};
        }}
        QPushButton:disabled {{
            opacity: 0.35;
        }}
    """


def get_circular_button_style(theme_colors: dict) -> str:
    """Alias de compatibilidad → delega a get_nav_button_style."""
    return get_nav_button_style(theme_colors)


def get_modern_urlbar_style(theme_colors: dict) -> str:
    """
    URL bar expandible — estilo pill (border-radius 16px, altura 32px).
    Reposo: surface_0 + borde sutil. Foco: surface_1 + borde accent.
    """
    bg       = theme_colors.get("surface_0", theme_colors.get("urlbar_bg", "#1A1A1A"))
    bg_focus = theme_colors.get("surface_1", theme_colors.get("bg_primary",  "#222222"))
    border   = theme_colors.get("border", "rgba(255,255,255,0.08)")
    accent   = theme_colors.get("accent", "#4B9EFF")
    text     = theme_colors.get("text_primary",   theme_colors.get("primary",   "#F0F0F0"))
    muted    = theme_colors.get("text_muted",     theme_colors.get("secondary", "#606060"))
    sel_bg   = theme_colors.get("accent_subtle",  "rgba(75,158,255,0.35)")

    return f"""
        QLineEdit {{
            background: {bg};
            border: 1px solid {border};
            border-radius: 16px;
            padding: 4px 12px 4px 30px;
            font-size: 13px;
            color: {text};
            selection-background-color: {sel_bg};
            selection-color: {text};
            min-height: 32px;
            max-height: 32px;
        }}
        QLineEdit:hover {{
            border: 1px solid {theme_colors.get('border_strong', border)};
        }}
        QLineEdit:focus {{
            background: {bg_focus};
            border: 1.5px solid {accent};
            padding: 3px 11px 3px 29px;
        }}
        QLineEdit[readOnly="true"] {{
            color: {muted};
        }}
    """


def get_trapezoidal_tab_style(theme_colors: dict) -> str:
    """
    Pestañas estilo Brave:
    - 30px alto, border-radius 6px
    - Inactiva: transparente. Hover: surface_hover. Activa: surface_1
    - Sin línea inferior, sin sombras, sin decoraciones
    """
    s1        = theme_colors.get("surface_1",       theme_colors.get("tab_active", "#222222"))
    s_hover   = theme_colors.get("surface_hover",   theme_colors.get("bg_hover",   "#303030"))
    s_0       = theme_colors.get("surface_0",       theme_colors.get("bg_primary", "#1A1A1A"))
    text_sec  = theme_colors.get("text_secondary",  theme_colors.get("secondary",  "#A0A0A0"))
    text_pri  = theme_colors.get("text_primary",    theme_colors.get("primary",    "#F0F0F0"))
    accent    = theme_colors.get("accent", "#4B9EFF")
    err       = theme_colors.get("error",  "#F85149")

    return f"""
        QTabWidget::pane {{
            border: none;
            background: {s_0};
            top: 0px;
        }}

        QTabBar {{
            background: transparent;
            qproperty-drawBase: 0;
        }}

        QTabBar::tab {{
            background: transparent;
            color: {text_sec};
            border: none;
            border-radius: 5px;
            padding: 0px 8px;
            height: 26px;
            margin: 2px 1px 0px 1px;
            font-size: 12px;
            min-width: 64px;
            max-width: 200px;
        }}

        QTabBar::tab:hover:!selected {{
            background: {s_hover};
            color: {text_pri};
        }}

        QTabBar::tab:selected {{
            background: {s1};
            color: {text_pri};
            font-weight: 500;
        }}

        QTabBar::close-button {{
            image: url("{_TAB_CLOSE_SVG}");
            subcontrol-position: right;
            margin: 1px 6px 1px 1px;
            border-radius: 5px;
            width: 20px;
            height: 20px;
        }}

        QTabBar::close-button:hover {{
            background: rgba(255,255,255,0.16);
            border-radius: 5px;
        }}

        QTabBar::scroller {{
            width: 24px;
        }}

        QTabBar QToolButton {{
            background: transparent;
            border: none;
            border-radius: 4px;
            min-width: 24px;
            max-width: 24px;
            min-height: 24px;
            max-height: 24px;
        }}

        QTabBar QToolButton:hover {{
            background: {s_hover};
        }}
    """


def get_modern_navbar_style(theme_colors: dict) -> str:
    """
    Navbar limpia — 44px alto, surface_1, sin borde inferior decorativo.
    Separador sutil via border-bottom.
    """
    bg     = theme_colors.get("surface_1", theme_colors.get("bg_primary", "#222222"))
    border = theme_colors.get("border", "rgba(255,255,255,0.08)")

    return f"""
        QWidget#navbar {{
            background: {bg};
            border-bottom: 1px solid {border};
            min-height: 44px;
            max-height: 44px;
        }}
        QToolBar {{
            background: transparent;
            border: none;
            spacing: 4px;
            padding: 0px 8px;
        }}
        QToolButton {{
            background: transparent;
            border: none;
            border-radius: 6px;
            min-width: 32px;
            max-width: 32px;
            min-height: 32px;
            max-height: 32px;
            padding: 0px;
            margin: 0px;
            color: {theme_colors.get('text_secondary', '#A0A0A0')};
        }}
        QToolButton:hover {{
            background: {theme_colors.get('surface_hover', theme_colors.get('bg_hover', '#303030'))};
            color: {theme_colors.get('text_primary', '#F0F0F0')};
        }}
        QToolButton:pressed {{
            background: {theme_colors.get('surface_active', theme_colors.get('bg_active', '#383838'))};
        }}
        QToolButton:disabled {{
            opacity: 0.35;
        }}
    """


def get_sidebar_style(theme_colors: dict) -> str:
    """Sidebar limpia — surface_0, borde derecho sutil."""
    bg     = theme_colors.get("surface_0", theme_colors.get("bg_secondary", "#1A1A1A"))
    border = theme_colors.get("border", "rgba(255,255,255,0.08)")
    text   = theme_colors.get("text_primary", theme_colors.get("primary", "#F0F0F0"))

    return f"""
        QFrame#sidebar {{
            background: {bg};
            border-right: 1px solid {border};
        }}
        QLabel#sidebar_title {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: {theme_colors.get('text_secondary', '#A0A0A0')};
            padding: 12px 16px;
        }}
    """


def get_panel_base_style(theme_colors: dict, border_side: str = "left") -> str:
    """
    Estilo base para paneles (plugins, chat, etc.)
    border_side: 'left' o 'right'
    """
    bg     = theme_colors.get("surface_0", "#1A1A1A")
    border = theme_colors.get("border", "rgba(255,255,255,0.08)")
    text   = theme_colors.get("text_primary", "#F0F0F0")

    border_prop = (
        f"border-left: 1px solid {border};"
        if border_side == "left"
        else f"border-right: 1px solid {border};"
    )

    return f"""
        QWidget {{
            background: {bg};
            color: {text};
            font-size: 13px;
        }}
        QFrame#panelBase {{
            background: {bg};
            {border_prop}
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 6px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(255,255,255,0.12);
            border-radius: 3px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(255,255,255,0.25);
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
    """


def get_plugin_row_style(theme_colors: dict) -> str:
    """Estilo para filas de plugins (40px, hover, separador)."""
    hover  = theme_colors.get("surface_hover", "#303030")
    border = theme_colors.get("border", "rgba(255,255,255,0.08)")
    text_p = theme_colors.get("text_primary", "#F0F0F0")
    text_s = theme_colors.get("text_secondary", "#A0A0A0")
    accent = theme_colors.get("accent", "#4B9EFF")
    succ   = theme_colors.get("success", "#3FB950")

    return f"""
        QFrame#pluginRow {{
            background: transparent;
            border-bottom: 1px solid {border};
            min-height: 40px;
            max-height: 40px;
        }}
        QFrame#pluginRow:hover {{
            background: {hover};
        }}
        QLabel#pluginName {{
            font-size: 13px;
            color: {text_p};
        }}
        QLabel#badgeActive {{
            background: rgba(63,185,80,0.12);
            color: {succ};
            font-size: 10px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 3px;
        }}
        QLabel#badgePro {{
            background: {theme_colors.get('accent_subtle', 'rgba(75,158,255,0.12)')};
            color: {accent};
            font-size: 10px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 3px;
        }}
    """


def get_chat_style(theme_colors: dict) -> str:
    """Estilo para el panel de chat — funcional y limpio (Linear/Arc sidebar)."""
    s0     = theme_colors.get("surface_0", "#1A1A1A")
    s1     = theme_colors.get("surface_1", "#222222")
    border = theme_colors.get("border", "rgba(255,255,255,0.08)")
    text_p = theme_colors.get("text_primary", "#F0F0F0")
    text_s = theme_colors.get("text_secondary", "#A0A0A0")
    accent = theme_colors.get("accent", "#4B9EFF")
    a_sub  = theme_colors.get("accent_subtle", "rgba(75,158,255,0.12)")
    err    = theme_colors.get("error", "#F85149")
    hover  = theme_colors.get("surface_hover", "#303030")

    return f"""
        QWidget#chatPanel {{
            background: {s0};
        }}

        /* Header */
        QWidget#chatHeader {{
            background: {s0};
            border-bottom: 1px solid {border};
            min-height: 40px;
            max-height: 40px;
        }}
        QLabel#chatTitle {{
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.8px;
            color: {text_s};
        }}

        /* Área de mensajes */
        QScrollArea#chatScroll {{
            background: transparent;
            border: none;
        }}
        QWidget#chatMessagesWidget {{
            background: {s0};
        }}

        /* Mensajes — estilo documento */
        QWidget#userBubble {{
            background: {a_sub};
            border-left: 2px solid {accent};
            border-radius: 0px 6px 6px 0px;
            margin: 2px 0px 2px 16px;
        }}
        QWidget#assistantBubble {{
            background: transparent;
        }}
        QWidget#errorBubble {{
            background: rgba(248,81,73,0.08);
            border-left: 2px solid {err};
            border-radius: 0px 6px 6px 0px;
        }}

        QLabel#bubbleTitle {{
            font-size: 11px;
            color: {text_s};
            font-weight: 600;
        }}
        QLabel#bubbleMsg {{
            font-size: 13px;
            color: {text_p};
            line-height: 1.5;
        }}

        /* Input area */
        QWidget#chatInputArea {{
            background: {s1};
            border-top: 1px solid {border};
        }}
        QTextEdit#chatInput {{
            background: transparent;
            border: none;
            font-size: 13px;
            color: {text_p};
            padding: 8px 4px;
        }}

        /* Scrollbar */
        QScrollBar:vertical {{
            background: transparent;
            width: 6px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(255,255,255,0.12);
            border-radius: 3px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(255,255,255,0.25);
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
    """


def get_new_tab_style(theme_colors: dict) -> str:
    """Estilo para la página de nueva pestaña."""
    s0     = theme_colors.get("surface_0", "#1A1A1A")
    s1     = theme_colors.get("surface_1", "#222222")
    s2     = theme_colors.get("surface_2", "#2A2A2A")
    hover  = theme_colors.get("surface_hover", "#303030")
    border = theme_colors.get("border", "rgba(255,255,255,0.08)")
    border_s = theme_colors.get("border_strong", "rgba(255,255,255,0.14)")
    text_p = theme_colors.get("text_primary", "#F0F0F0")
    text_s = theme_colors.get("text_secondary", "#A0A0A0")
    text_m = theme_colors.get("text_muted", "#606060")
    accent = theme_colors.get("accent", "#4B9EFF")

    return f"""
        QWidget#newTabPage {{
            background: {s0};
        }}
        QLineEdit#newTabSearch {{
            background: {s1};
            border: 1px solid {border};
            border-radius: 22px;
            padding: 0px 16px 0px 42px;
            font-size: 15px;
            color: {text_p};
            min-height: 44px;
            max-height: 44px;
            selection-background-color: {theme_colors.get('accent_subtle', 'rgba(75,158,255,0.35)')};
        }}
        QLineEdit#newTabSearch:focus {{
            border: 1.5px solid {accent};
            background: {s2};
        }}
        QWidget#shortcut {{
            background: {s1};
            border: 1px solid {border};
            border-radius: 8px;
        }}
        QWidget#shortcut:hover {{
            background: {hover};
            border-color: {border_s};
        }}
        QLabel#aiSuggestion {{
            font-size: 12px;
            color: {text_m};
        }}
        QLabel#aiPrefix {{
            color: {accent};
        }}
        QPushButton#settingsBtn {{
            background: transparent;
            border: none;
            border-radius: 4px;
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
        }}
        QPushButton#settingsBtn:hover {{
            background: {hover};
        }}
    """


# ─── Clases del sistema de temas ──────────────────────────────────────────────

class ModernTheme:
    """Temas modernos con tokens de diseño Arc/Brave."""

    DARK  = _DARK_TOKENS
    LIGHT = _LIGHT_TOKENS

    @staticmethod
    def get_theme(name: str = "light") -> dict:
        return {
            "dark":  ModernTheme.DARK,
            "light": ModernTheme.LIGHT,
        }.get(name.lower(), ModernTheme.LIGHT)


class ModernStylesAdapter:
    """
    Adaptador que mantiene compatibilidad con código existente que usa
    ThemeManager / ModernStylesAdapter.
    """

    def __init__(self, theme_name: str = "light"):
        self.current_theme_name = theme_name
        self.current_theme = ModernTheme.get_theme(theme_name)
        self.widgets: list = []
    def get_tab_style(self) -> str:
        return get_trapezoidal_tab_style(self.current_theme)
    def get_urlbar_style(self) -> str:
        return get_modern_urlbar_style(self.current_theme)
    def get_navbar_style(self) -> str:
        return get_modern_navbar_style(self.current_theme)
    def get_sidebar_style(self) -> str:
        return get_sidebar_style(self.current_theme)
    def get_circular_button_style(self) -> str:
        return get_nav_button_style(self.current_theme)
    def get_current_theme(self) -> dict:
        return self.current_theme
    def change_theme(self, theme_name: str) -> None:
        self.current_theme_name = theme_name
        self.current_theme = ModernTheme.get_theme(theme_name)


# Alias de compatibilidad
ThemeManager = ModernStylesAdapter
