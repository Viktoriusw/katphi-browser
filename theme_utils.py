#!/usr/bin/env python3


"""


Theme Utils - Utilidades para migrar colores hardcodeados al sistema de temas


"""


try:
    from ui.core.theme_engine import get_color, get_font, get_spacing, get_border
except ImportError:
    # Fallback al sistema antiguo
    from theme_manager import get_color, get_font, get_spacing, get_border


def get_theme_color(color_key: str, fallback: str = "#000000") -> str:


    """

    Obtiene un color del tema actual con fallback

    Args:
        color_key: Clave del color en el tema

        fallback: Color de respaldo si no se encuentra
    Returns:
        Color en formato hexadecimal
    """

    try:
        return get_color(color_key)
    except:
        return fallback


def get_theme_font(font_key: str, fallback: str = "10pt") -> str:
    """

    Obtiene una configuración de fuente del tema actual con fallback

    Args:
        font_key: Clave de la fuente en el tema

        fallback: Fuente de respaldo si no se encuentra
    Returns:
        Configuración de fuente
    """

    try:
        return get_font(font_key)
    except:
        return fallback


def get_theme_spacing(spacing_key: str, fallback: str = "4px") -> str:
    """

    Obtiene un espaciado del tema actual con fallback

    Args:
        spacing_key: Clave del espaciado en el tema

        fallback: Espaciado de respaldo si no se encuentra
    Returns:
        Espaciado en píxeles
    """

    try:
        return get_spacing(spacing_key)
    except:
        return fallback


def get_theme_border(border_key: str, fallback: str = "1px") -> str:
    """

    Obtiene una configuración de borde del tema actual con fallback

    Args:
        border_key: Clave del borde en el tema

        fallback: Borde de respaldo si no se encuentra
    Returns:
        Configuración de borde
    """

    try:
        return get_border(border_key)
    except:
        return fallback


def create_style_sheet(styles: dict) -> str:
    """

    Crea una hoja de estilos CSS usando colores del tema

    Args:
        styles: Diccionario con estilos CSS
    Returns:
        CSS generado
    """

    css_parts = []

    for selector, properties in styles.items():
        css_parts.append(f"{selector} {{")

        for property_name, value in properties.items():
            css_parts.append(f"    {property_name}: {value};")
        css_parts.append("}")
    return "\n".join(css_parts)


# Funciones de conveniencia para colores comunes


def get_primary_color() -> str:
    """Obtiene el color primario del tema"""

    return get_theme_color("primary", "#000000")


def get_secondary_color() -> str:
    """Obtiene el color secundario del tema"""

    return get_theme_color("secondary", "#333333")


def get_background_color() -> str:
    """Obtiene el color de fondo del tema"""

    return get_theme_color("background", "#f5f5f5")


def get_surface_color() -> str:
    """Obtiene el color de superficie del tema"""

    return get_theme_color("surface", "#ffffff")


def get_accent_color() -> str:
    """Obtiene el color de acento del tema"""

    return get_theme_color("accent", "#0078d4")


def get_success_color() -> str:
    """Obtiene el color de éxito del tema"""

    return get_theme_color("success", "#107c10")


def get_warning_color() -> str:
    """Obtiene el color de advertencia del tema"""

    return get_theme_color("warning", "#ff8c00")


def get_error_color() -> str:
    """Obtiene el color de error del tema"""

    return get_theme_color("error", "#d13438")


def get_border_color() -> str:
    """Obtiene el color de borde del tema"""

    return get_theme_color("border", "#e0e0e0")


def get_hover_color() -> str:
    """Obtiene el color de hover del tema"""

    return get_theme_color("hover", "#e8e8e8")


def get_selected_color() -> str:
    """Obtiene el color de selección del tema"""

    return get_theme_color("selected", "#cce8ff")
