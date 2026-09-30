#!/usr/bin/env python3
"""
UI Core Constants - Constantes centralizadas para toda la interfaz

Este archivo centraliza todos los valores hardcodeados que antes estaban
dispersos por el código. Facilita el mantenimiento y la consistencia visual.
"""

from PySide6.QtCore import QSize

# ============================================================================
# CONSTANTES DE COMPONENTES
# ============================================================================

class ComponentSize:
    """Tamaños estandarizados para componentes"""

    # Botones
    BUTTON_SMALL = QSize(24, 24)
    BUTTON_MEDIUM = QSize(36, 36)
    BUTTON_LARGE = QSize(48, 48)

    # Iconos
    ICON_SMALL = QSize(14, 14)
    ICON_MEDIUM = QSize(20, 20)
    ICON_LARGE = QSize(32, 32)

    # Barras
    SIDEBAR_WIDTH = 36
    STATUSBAR_HEIGHT = 24
    NAVBAR_HEIGHT = 48

    # URL Bar
    URLBAR_DEFAULT_WIDTH = 600
    URLBAR_EXPANDED_WIDTH = 800

    # Tabs (estilo Chrome - extra compacto)
    TAB_HEIGHT = 12
    TAB_MIN_WIDTH = 100
    TAB_MAX_WIDTH = 200
    TAB_PADDING_H = 12  # padding horizontal
    TAB_PADDING_V = 5   # padding vertical (reducido)

class Spacing:
    """Espaciados estandarizados"""
    XS = 2
    SM = 4
    MD = 8
    LG = 12
    XL = 16
    XXL = 24

class Animation:
    """Duraciones de animaciones"""
    FAST = 150
    NORMAL = 250
    SLOW = 500

class ZIndex:
    """Niveles de elevación para componentes"""
    BACKGROUND = 0
    NORMAL = 1
    ELEVATED = 2
    POPUP = 3
    OVERLAY = 4
    MODAL = 5

# ============================================================================
# CONSTANTES DE NAVEGACIÓN
# ============================================================================

class Navigation:
    """Constantes relacionadas con navegación"""
    DEFAULT_URL = "https://www.google.com"
    BLANK_PAGE = "about:blank"
    MAX_HISTORY = 100
    MAX_TABS = 50

# ============================================================================
# CONSTANTES DE TEMAS
# ============================================================================

class ThemeDefaults:
    """Valores por defecto para temas"""
    DEFAULT_THEME = "light"
    THEME_DIRECTORY = "ui/themes"
    CUSTOM_THEME_DIRECTORY = "ui/themes/custom"

    # Temas base disponibles
    BASE_THEMES = ["light", "dark"]

    # Colores de fallback si un tema no tiene un valor
    FALLBACK_PRIMARY = "#000000"
    FALLBACK_BACKGROUND = "#ffffff"
    FALLBACK_ACCENT = "#0078d4"

# ============================================================================
# CONSTANTES DE PLUGINS
# ============================================================================

class Plugins:
    """Constantes relacionadas con plugins"""
    PLUGIN_DIRECTORY = "plugins"
    PLUGIN_CONFIG_FILE = "plugin_info.json"
    MAX_PLUGIN_LOAD_TIME = 5000  # ms

# ============================================================================
# CONSTANTES DE SEGURIDAD
# ============================================================================

class Security:
    """Constantes de seguridad"""
    SSL_TIMEOUT = 30
    CERTIFICATE_CACHE_TIME = 3600  # 1 hora

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_spacing(size: str) -> int:
    """Obtener valor de espaciado por nombre"""
    return getattr(Spacing, size.upper(), Spacing.MD)

def get_component_size(component: str, size: str = "MEDIUM") -> QSize:
    """Obtener tamaño de componente por nombre"""
    attr_name = f"{component.upper()}_{size.upper()}"
    return getattr(ComponentSize, attr_name, ComponentSize.BUTTON_MEDIUM)

def get_animation_duration(speed: str = "NORMAL") -> int:
    """Obtener duración de animación por velocidad"""
    return getattr(Animation, speed.upper(), Animation.NORMAL)
