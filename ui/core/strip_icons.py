#!/usr/bin/env python3
"""
Iconos temáticos para Katphi Browser.

Los SVG suelen traer fill="#..." fijo; QSS `color` no los tiñe.
Aquí reemplazamos fills/strokes en tiempo de ejecución y renderizamos
a QIcon, tanto para SVG como para PNG monocromo.

Funciones públicas principales:
    build_strip_icon(path, color, size)  → QIcon temático
    build_nav_icon(name, color, size)    → QIcon para acciones de navbar
    refresh_action_icon(action, color)   → actualiza el icono de un QAction
    get_icon_color(theme_name)           → color de icono según tema
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Directorio de iconos por defecto (relativo a la raíz del proyecto)
_ICONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "icons")
_ICONS_DIR = os.path.normpath(_ICONS_DIR)

# Colores estándar por tema
_THEME_ICON_COLORS: dict[str, str] = {
    "dark":   "#A0A0A0",   # text_secondary del tema oscuro
    "light":  "#5F6368",   # texto secundario del tema claro
}

# Tamaño estándar para iconos de navbar (16×16 px lógicos)
NAV_ICON_SIZE = QSize(16, 16)
# Tamaño estándar para iconos de sidebar strip
STRIP_ICON_SIZE = QSize(16, 16)


# ─── Bajo nivel ───────────────────────────────────────────────────────────────

def _svg_bytes_tinted(svg_text: str, color_hex: str) -> bytes:
    """Sustituye todos los fills/strokes hardcodeados por color_hex."""
    c = (color_hex or "#A0A0A0").strip()
    if not c.startswith("#"):
        c = "#" + c
    out = svg_text.replace('fill="currentColor"', f'fill="{c}"')
    out = out.replace("fill='currentColor'", f"fill='{c}'")
    out = out.replace('stroke="currentColor"', f'stroke="{c}"')
    out = out.replace("stroke='currentColor'", f"stroke='{c}'")
    # Reemplazar cualquier fill/stroke hex (iconos monocromo con color fijo)
    out = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{c}"', out)
    out = re.sub(r"fill='#([0-9a-fA-F]{3,8})'", f"fill='{c}'", out)
    out = re.sub(r'stroke="#[0-9a-fA-F]{3,8}"', f'stroke="{c}"', out)
    out = re.sub(r"stroke='#([0-9a-fA-F]{3,8})'", f"stroke='{c}'", out)
    # fill="none" NO debe ser reemplazado (es transparente intencional)
    # Corregir: si reemplazamos none, revertir
    out = out.replace(f'fill="{c}" ', 'fill="none" ').replace(
        f"fill='{c}' ", "fill='none' "
    ) if f'fill="{c}"' in svg_text and 'fill="none"' in svg_text else out
    return out.encode("utf-8")


def _svg_bytes_tinted_v2(svg_text: str, color_hex: str) -> bytes:
    """
    Tinteado robusto de SVG. Cubre CUATRO casos que aparecen en SVGs reales:
    1. Atributos directos:  fill="#000000"  stroke="#000000"
    2. CSS inline en <style>: .st0{fill:#000000;}
    3. currentColor / inherited
    4. SVG sin fills explícitos (hereda negro por defecto de SVG)
       → se añade fill="COLOR" en el elemento <svg> raíz para que todos
         los paths lo hereden.
    En todos los casos se preserva fill="none" / fill="transparent".
    """
    c = (color_hex or "#A0A0A0").strip()
    if not c.startswith("#"):
        c = "#" + c
    # ── Paso 1: Reemplazar fills en bloques <style>...</style> ────────────────
    # Cubre:  .st0{fill:#000000;}  y variantes con espacios
    def _tint_style_block(match: re.Match) -> str:
        tag_attrs = match.group(1)   # atributos del tag <style ...>
        css_body  = match.group(2)   # contenido CSS

        # Proteger none/transparent dentro del CSS
        css_body = css_body.replace("fill:none", "fill:__NONE__")
        css_body = css_body.replace("fill: none", "fill: __NONE__")
        css_body = css_body.replace("fill:transparent", "fill:__TRANSPARENT__")

        # Reemplazar hex
        css_body = re.sub(
            r"(fill\s*:\s*)#[0-9a-fA-F]{3,8}",
            lambda m: m.group(1) + c,
            css_body,
        )
        css_body = re.sub(
            r"(stroke\s*:\s*)#[0-9a-fA-F]{3,8}",
            lambda m: m.group(1) + c,
            css_body,
        )

        # Restaurar
        css_body = css_body.replace("fill:__NONE__", "fill:none")
        css_body = css_body.replace("fill: __NONE__", "fill: none")
        css_body = css_body.replace("fill:__TRANSPARENT__", "fill:transparent")

        return f"<style{tag_attrs}>{css_body}</style>"
    out = re.sub(
        r"<style([^>]*)>(.*?)</style>",
        _tint_style_block,
        svg_text,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # ── Paso 2: Proteger fill="none" / fill="transparent" en atributos ────────
    out = out.replace('fill="none"',        'fill="__NONE__"')
    out = out.replace("fill='none'",        "fill='__NONE__'")
    out = out.replace('fill="transparent"', 'fill="__TRANSPARENT__"')
    out = out.replace("fill='transparent'", "fill='__TRANSPARENT__'")

    # ── Paso 3: currentColor ───────────────────────────────────────────────────
    out = out.replace('fill="currentColor"',   f'fill="{c}"')
    out = out.replace("fill='currentColor'",   f"fill='{c}'")
    out = out.replace('stroke="currentColor"', f'stroke="{c}"')
    out = out.replace("stroke='currentColor'", f"stroke='{c}'")

    # ── Paso 4: Atributos hex directos ────────────────────────────────────────
    out = re.sub(r'fill="#[0-9a-fA-F]{3,8}"',   f'fill="{c}"',   out)
    out = re.sub(r"fill='#[0-9a-fA-F]{3,8}'",   f"fill='{c}'",   out)
    out = re.sub(r'stroke="#[0-9a-fA-F]{3,8}"', f'stroke="{c}"', out)
    out = re.sub(r"stroke='#[0-9a-fA-F]{3,8}'", f"stroke='{c}'", out)

    # ── Paso 5: SVG sin ningún atributo de color (default negro de SVG) ────────
    # Solo se aplica cuando el SVG no tiene NI fills NI strokes de color:
    # es decir, paths que dependen del fill negro implícito del SVG spec.
    # Ejemplo: plugins.svg → <path d="..."/> sin fill ni stroke.
    #
    # NO se aplica a SVGs de solo-stroke (chat.svg, lock.svg…): éstos ya
    # tienen stroke="{c}" puesto en el paso 4 y no necesitan inject de fill.
    # Inyectar fill en esos SVGs crea un atributo fill duplicado en <svg>
    # (junto al fill="none" original) y puede romper el render.
    has_any_color = (
        f'fill="{c}"'   in out
        or f"fill='{c}'" in out
        or f"fill:{c}"   in out
        or f'stroke="{c}"'   in out
        or f"stroke='{c}'"   in out
        or f"stroke:{c}"     in out
    )
    # Además, no inyectar si la raíz <svg> ya tiene un fill (ej. fill="__NONE__")
    root_already_has_fill = bool(
        re.search(r"<svg\b[^>]*\bfill\s*=", out, re.IGNORECASE)
    )
    if not has_any_color and not root_already_has_fill:
        # Añadir fill al elemento <svg> raíz para que los paths hereden el color
        out = re.sub(
            r"(<svg\b)([^>]*?)(/>|>)",
            lambda m: f"{m.group(1)}{m.group(2)} fill=\"{c}\"{m.group(3)}",
            out,
            count=1,
            flags=re.IGNORECASE,
        )
    # ── Paso 6: Restaurar protegidos ──────────────────────────────────────────
    out = out.replace('fill="__NONE__"',        'fill="none"')
    out = out.replace("fill='__NONE__'",        "fill='none'")
    out = out.replace('fill="__TRANSPARENT__"', 'fill="transparent"')
    out = out.replace("fill='__TRANSPARENT__'", "fill='transparent'")

    return out.encode("utf-8")


def _icon_from_svg_bytes(data: bytes, size: QSize) -> QIcon:
    ba = QByteArray(data)
    renderer = QSvgRenderer(ba)
    if not renderer.isValid():
        return QIcon()
    pm = QPixmap(size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return QIcon(pm)


def _icon_from_png_tinted(path: str, color_hex: str, size: QSize) -> QIcon:
    """Tiñe un PNG monocromo con color_hex usando SourceIn blending."""
    pm = QPixmap(path)
    if pm.isNull():
        return QIcon()
    pm = pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    color = QColor(color_hex)
    if not color.isValid():
        color = QColor("#A0A0A0")
    tinted = QPixmap(pm.size())
    tinted.fill(Qt.transparent)
    p = QPainter(tinted)
    p.drawPixmap(0, 0, pm)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), color)
    p.end()
    return QIcon(tinted)


# ─── API pública ──────────────────────────────────────────────────────────────

def build_strip_icon(resolved_path: str, color_hex: str, size: QSize) -> QIcon:
    """
    Construye un QIcon temático desde SVG o PNG.

    - SVG: sustituye todos los fills/strokes y renderiza al tamaño indicado.
    - PNG: tiñe con SourceIn (asume icono monocromo sobre canal alpha).

    Args:
        resolved_path: Ruta absoluta al archivo de icono.
        color_hex:     Color deseado (p.ej. "#A0A0A0").
        size:          QSize de salida.
    Returns:
        QIcon con el color aplicado, o QIcon() si falla.
    """
    if not resolved_path or not os.path.isfile(resolved_path):
        return QIcon()
    ext = os.path.splitext(resolved_path)[1].lower()
    try:
        if ext == ".svg":
            with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            data = _svg_bytes_tinted_v2(raw, color_hex)
            icon = _icon_from_svg_bytes(data, size)
            if not icon.isNull():
                return icon
            return QIcon(resolved_path)
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            icon = _icon_from_png_tinted(resolved_path, color_hex, size)
            if not icon.isNull():
                return icon
            return QIcon(resolved_path)
    except OSError:
        pass
    return QIcon(resolved_path)


def get_icon_color(theme_name: str = "dark") -> str:
    """
    Devuelve el color de icono apropiado para el tema dado.
    Intenta obtenerlo del ThemeEngine; si no, usa el valor por defecto.
    """
    try:
        from ui.core.theme_engine import get_theme_engine
        engine = get_theme_engine()
        if engine:
            colors = engine.get_theme_data().get("colors", {})
            color = colors.get("icon_color") or colors.get("text_secondary") or colors.get("primary")
            if color:
                return color
    except Exception:
        pass
    return _THEME_ICON_COLORS.get(theme_name, "#A0A0A0")


def resolve_icon_path(name: str, icons_dir: str | None = None) -> str:
    """
    Resuelve la ruta al icono con prioridad SVG > PNG.

    Args:
        name:      Nombre del icono sin extensión (p.ej. "back").
        icons_dir: Directorio de iconos. Si None, usa el directorio por defecto.
    Returns:
        Ruta absoluta al archivo, o cadena vacía si no existe.
    """
    # Alias para mantener compatibilidad con nombres legacy
    _ALIASES = {
        "settings": "plugins",
        "security": "pentesting",
        "tor_off":  "tor",
        "wrench":   "plugins",
        "chat":     "chat",
        "new-tab":  "newtab",
        "new_tab":  "newtab",
    }

    d = icons_dir or _ICONS_DIR
    canonical = _ALIASES.get(name, name)

    for n in (canonical, name):
        for ext in (".svg", ".png", ".jpg"):
            p = os.path.join(d, f"{n}{ext}")
            if os.path.isfile(p):
                return os.path.abspath(p)
    return ""


def build_nav_icon(
    name: str,
    color_hex: str | None = None,
    size: QSize | None = None,
    icons_dir: str | None = None,
) -> QIcon:
    """
    Construye un QIcon temático para botones de navegación (navbar, sidebar…).

    Args:
        name:      Nombre del icono sin extensión (p.ej. "back", "refresh").
        color_hex: Color deseado. Si None, usa el color del tema activo.
        size:      Tamaño del icono. Si None, usa NAV_ICON_SIZE.
        icons_dir: Directorio de iconos. Si None, usa el directorio por defecto.
    Returns:
        QIcon con el color aplicado, o QIcon() si el archivo no existe.
    """
    if color_hex is None:
        color_hex = get_icon_color()
    if size is None:
        size = NAV_ICON_SIZE
    path = resolve_icon_path(name, icons_dir)
    if not path:
        return QIcon()
    return build_strip_icon(path, color_hex, size)


def refresh_action_icon(
    action,
    color_hex: str,
    size: QSize | None = None,
) -> None:
    """
    Actualiza el icono de un QAction con un nuevo color temático.

    El QAction debe tener la propiedad `strip_icon_path` con la ruta
    absoluta al icono (se asigna automáticamente con `build_nav_action`).

    Args:
        action:    QAction cuyo icono se va a actualizar.
        color_hex: Nuevo color del icono.
        size:      Tamaño del icono. Si None, usa NAV_ICON_SIZE.
    """
    if size is None:
        size = NAV_ICON_SIZE
    path = action.property("strip_icon_path")
    if path and os.path.isfile(path):
        icon = build_strip_icon(path, color_hex, size)
        if not icon.isNull():
            action.setIcon(icon)


def build_nav_action(
    parent,
    name: str,
    tooltip: str,
    callback,
    color_hex: str | None = None,
    size: QSize | None = None,
    icons_dir: str | None = None,
):
    """
    Crea un QAction con icono SVG temático y almacena la ruta del icono.

    El QAction resultante tiene la propiedad `strip_icon_path` para
    poder refrescar el color al cambiar de tema con `refresh_action_icon`.

    Args:
        parent:    Widget padre del QAction.
        name:      Nombre del icono sin extensión.
        tooltip:   Texto del tooltip.
        callback:  Función a llamar cuando se activa la acción.
        color_hex: Color del icono. Si None, usa el color del tema activo.
        size:      Tamaño del icono. Si None, usa NAV_ICON_SIZE.
        icons_dir: Directorio de iconos. Si None, usa el directorio por defecto.
    Returns:
        QAction con icono temático configurado.
    """
    from PySide6.QtGui import QAction

    if color_hex is None:
        color_hex = get_icon_color()
    if size is None:
        size = NAV_ICON_SIZE
    path = resolve_icon_path(name, icons_dir)
    icon = build_strip_icon(path, color_hex, size) if path else QIcon()

    action = QAction(icon, tooltip, parent)
    action.setProperty("strip_icon_path", path)
    action.setProperty("strip_icon_name", name)
    if callback:
        action.triggered.connect(callback)
    return action
