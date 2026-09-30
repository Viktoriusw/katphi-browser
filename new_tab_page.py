#!/usr/bin/env python3
"""
New Tab Page — Página de nueva pestaña limpia y funcional.

Filosofía: contenido útil, sin ruido visual. Arc/Brave-inspired.
- Barra de búsqueda central (pill)
- Accesos directos (grid 3 cols)
- Sugerencia IA opcional (1 línea)
- Botón de ajustes (esquina superior derecha)
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QFrame, QSizePolicy,
    QDialog, QCheckBox, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QSettings, QSize, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QKeySequence

import logging
_log = logging.getLogger(__name__)


# ─── Constantes de diseño ─────────────────────────────────────────────────────

_DARK = {
    "surface_0":      "#1A1A1A",
    "surface_1":      "#222222",
    "surface_hover":  "#303030",
    "border":         "rgba(255,255,255,0.08)",
    "border_strong":  "rgba(255,255,255,0.14)",
    "text_primary":   "#F0F0F0",
    "text_secondary": "#A0A0A0",
    "text_muted":     "#606060",
    "accent":         "#4B9EFF",
}

def _themed_icon(name: str, size: int):
    """Icono SVG de icons/ teñido con el color del tema activo."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    try:
        from ui.core.strip_icons import build_nav_icon
        return build_nav_icon(name, None, QSize(size, size))
    except Exception:
        return QIcon()


_DEFAULT_SHORTCUTS = [
    {"name": "Google",     "url": "https://google.com"},
    {"name": "GitHub",     "url": "https://github.com"},
    {"name": "YouTube",    "url": "https://youtube.com"},
    {"name": "Wikipedia",  "url": "https://wikipedia.org"},
    {"name": "Reddit",     "url": "https://reddit.com"},
    {"name": "HackerNews", "url": "https://news.ycombinator.com"},
]

_SHORTCUTS_FILE = Path("new_tab_shortcuts.json")


# ─── ShortcutItem ─────────────────────────────────────────────────────────────

class ShortcutItem(QWidget):
    """
    Acceso directo individual: icono centrado + nombre debajo.
    80×70px, border-radius 8px, hover sutil.
    """

    clicked_url = Signal(str)

    def __init__(self, data: dict, colors: dict, parent=None):
        super().__init__(parent)
        self.url = data.get("url", "")
        self.setObjectName("shortcut")
        self.setFixedSize(80, 70)
        self.setCursor(Qt.PointingHandCursor)
        self._setup_ui(data, colors)
        self._apply_style(colors)
    def _setup_ui(self, data: dict, colors: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        # Inicial del nombre en un círculo (el campo "icon" antiguo, con emoji, se ignora)
        icon_label = QLabel((data.get("name") or "?")[:1].upper())
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(32, 32)
        icon_label.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {colors['accent']};"
            f" background: {colors.get('accent_subtle', 'transparent')};"
            " border: none; border-radius: 16px;"
        )
        layout.addWidget(icon_label)

        name_label = QLabel(data.get("name", "")[:12])
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet(
            f"font-size: 11px; color: {colors['text_secondary']}; "
            "background: transparent; border: none;"
        )
        layout.addWidget(name_label)
    def _apply_style(self, c: dict):
        self.setStyleSheet(f"""
            QWidget#shortcut {{
                background: {c['surface_1']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
            QWidget#shortcut:hover {{
                background: {c['surface_hover']};
                border-color: {c['border_strong']};
            }}
        """)
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.url:
            self.clicked_url.emit(self.url)


class AddShortcutItem(QWidget):
    """Botón '+' para añadir acceso directo (mismas dimensiones)."""

    add_clicked = Signal()

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("shortcut")
        self.setFixedSize(80, 70)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)

        plus = QLabel("+")
        plus.setAlignment(Qt.AlignCenter)
        plus.setStyleSheet(
            f"font-size: 22px; color: {colors['text_muted']}; "
            "background: transparent; border: none;"
        )
        layout.addWidget(plus)

        self.setStyleSheet(f"""
            QWidget#shortcut {{
                background: transparent;
                border: 1px dashed {colors['border_strong']};
                border-radius: 8px;
            }}
            QWidget#shortcut:hover {{
                border-color: {colors['accent']};
            }}
        """)
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.add_clicked.emit()


# ─── SettingsDialog ───────────────────────────────────────────────────────────

class NewTabSettingsDialog(QDialog):
    """Modal de configuración de la nueva pestaña."""

    def __init__(self, show_ai: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva pestaña — Ajustes")
        self.setFixedWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("Módulos activos")
        title.setStyleSheet("font-size: 13px; font-weight: 600; color: #F0F0F0;")
        layout.addWidget(title)

        self.ai_check = QCheckBox("Sugerencia IA (requiere chat activo)")
        self.ai_check.setChecked(show_ai)
        self.ai_check.setStyleSheet("color: #A0A0A0; font-size: 13px;")
        layout.addWidget(self.ai_check)

        save_btn = QPushButton("Guardar")
        save_btn.setStyleSheet("""
            QPushButton {
                background: #4B9EFF;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background: #67AFFF; }
        """)
        save_btn.clicked.connect(self.accept)
        layout.addWidget(save_btn)

        self.setStyleSheet("""
            QDialog { background: #222222; }
            QCheckBox { padding: 4px 0; }
        """)


# ─── NewTabPage ───────────────────────────────────────────────────────────────

class NewTabPage(QWidget):
    """
    Página de nueva pestaña — limpia, centrada, útil.

    Señales:
        navigate_requested(url)  — el usuario pide navegar a una URL
        open_chat_panel()        — clic en la sugerencia IA
    """

    navigate_requested = Signal(str)
    open_chat_panel    = Signal()

    def __init__(self, parent=None, colors: dict | None = None):
        super().__init__(parent)
        self.setObjectName("newTabPage")
        self.colors = colors or _DARK

        self.settings    = QSettings("Katphi", "NewTab")
        self._show_ai    = self.settings.value("show_ai", True, type=bool)
        self._shortcuts  = self._load_shortcuts()

        self._setup_ui()
        self._apply_style()
    # ── Construcción de la UI ──────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Botón ajustes — esquina superior derecha
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(16, 12, 16, 0)
        top_bar.addStretch()
        self._settings_btn = QPushButton()
        self._settings_btn.setIcon(_themed_icon("ide_gear", 16))
        self._settings_btn.setObjectName("settingsBtn")
        self._settings_btn.setFixedSize(28, 28)
        self._settings_btn.setCursor(Qt.PointingHandCursor)
        self._settings_btn.setToolTip("Ajustes de nueva pestaña")
        self._settings_btn.clicked.connect(self._open_settings)
        top_bar.addWidget(self._settings_btn)
        root.addLayout(top_bar)

        # Espaciado vertical — centrar contenido en el 40% vertical
        root.addStretch(3)

        # Contenedor central — máx 600px
        center_wrapper = QHBoxLayout()
        center_wrapper.addStretch()

        self._center = QWidget()
        self._center.setMaximumWidth(600)
        self._center.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_wrapper.addWidget(self._center, 1)
        center_wrapper.addStretch()
        root.addLayout(center_wrapper)

        self._build_center()

        root.addStretch(2)
    def _build_center(self):
        layout = QVBoxLayout(self._center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)

        # ── Barra de búsqueda ──────────────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)

        search_icon = QLabel()
        search_icon.setPixmap(_themed_icon("search", 16).pixmap(16, 16))
        search_icon.setStyleSheet(
            f"font-size: 16px; color: {self.colors['text_muted']}; "
            "background: transparent;"
        )
        search_icon.setFixedSize(42, 44)
        search_icon.setAlignment(Qt.AlignCenter)

        self._search = QLineEdit()
        self._search.setObjectName("newTabSearch")
        self._search.setPlaceholderText("Buscar o escribir URL")
        self._search.returnPressed.connect(self._on_search)

        # Superponer el icono como padding izquierdo usando un container
        search_container = QWidget()
        search_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sc_layout = QHBoxLayout(search_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(0)

        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wl = QHBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)

        # La barra con padding interno para el icono
        self._search.setStyleSheet(
            f"""
            QLineEdit#newTabSearch {{
                background: {self.colors['surface_1']};
                border: 1px solid {self.colors['border']};
                border-radius: 22px;
                padding: 0px 16px 0px 42px;
                font-size: 15px;
                color: {self.colors['text_primary']};
                min-height: 44px;
                max-height: 44px;
                selection-background-color: rgba(75,158,255,0.35);
            }}
            QLineEdit#newTabSearch:focus {{
                border: 1.5px solid {self.colors['accent']};
                background: {self.colors['surface_hover']};
            }}
            """
        )
        layout.addWidget(self._search)

        # ── Accesos directos ───────────────────────────────────────────────────
        self._shortcuts_frame = QWidget()
        shortcuts_grid = QGridLayout(self._shortcuts_frame)
        shortcuts_grid.setContentsMargins(0, 0, 0, 0)
        shortcuts_grid.setSpacing(8)
        shortcuts_grid.setAlignment(Qt.AlignLeft)

        self._populate_shortcuts(shortcuts_grid)
        layout.addWidget(self._shortcuts_frame)

        # ── Sugerencia IA ──────────────────────────────────────────────────────
        self._ai_widget = QWidget()
        ai_layout = QHBoxLayout(self._ai_widget)
        ai_layout.setContentsMargins(4, 0, 0, 0)
        ai_layout.setSpacing(4)

        ai_prefix = QLabel("AI:")
        ai_prefix.setStyleSheet(
            f"font-size: 12px; color: {self.colors['accent']}; "
            "background: transparent; font-weight: 600;"
        )
        ai_layout.addWidget(ai_prefix)

        self._ai_text = QLabel("Haz clic para preguntar algo sobre esta sesión...")
        self._ai_text.setObjectName("aiSuggestion")
        self._ai_text.setStyleSheet(
            f"font-size: 12px; color: {self.colors['text_muted']}; background: transparent;"
        )
        self._ai_text.setCursor(Qt.PointingHandCursor)
        self._ai_text.mousePressEvent = lambda _: self.open_chat_panel.emit()
        ai_layout.addWidget(self._ai_text)
        ai_layout.addStretch()

        self._ai_widget.setVisible(self._show_ai)
        layout.addWidget(self._ai_widget)
    def _populate_shortcuts(self, grid: QGridLayout):
        """Rellena el grid con accesos directos (máx 6) + botón +."""
        for i in reversed(range(grid.count())):
            widget = grid.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        items = self._shortcuts[:6]
        for idx, data in enumerate(items):
            row, col = divmod(idx, 3)
            item = ShortcutItem(data, self.colors)
            item.clicked_url.connect(self.navigate_requested.emit)
            grid.addWidget(item, row, col)
        # Botón "+" si hay espacio
        if len(items) < 6:
            row, col = divmod(len(items), 3)
            add_btn = AddShortcutItem(self.colors)
            add_btn.add_clicked.connect(self._add_shortcut_placeholder)
            grid.addWidget(add_btn, row, col)
    # ── Lógica ────────────────────────────────────────────────────────────────

    def _on_search(self):
        query = self._search.text().strip()
        if not query:
            return
        if "." in query and " " not in query and not query.startswith("http"):
            url = f"https://{query}"
        elif query.startswith(("http://", "https://")):
            url = query
        else:
            url = f"https://duckduckgo.com/?q={quote_plus(query)}"
        self._search.clear()
        self.navigate_requested.emit(url)
    def _open_settings(self):
        dlg = NewTabSettingsDialog(self._show_ai, self)
        if dlg.exec():
            self._show_ai = dlg.ai_check.isChecked()
            self.settings.setValue("show_ai", self._show_ai)
            self._ai_widget.setVisible(self._show_ai)
    def _add_shortcut_placeholder(self):
        """Placeholder: añadir acceso directo (extensible)."""
        _log.info("Nueva pestaña: añadir acceso directo (pendiente)")
    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load_shortcuts(self) -> list:
        if _SHORTCUTS_FILE.exists():
            try:
                return json.loads(_SHORTCUTS_FILE.read_text())
            except Exception:
                pass
        return list(_DEFAULT_SHORTCUTS)
    def _save_shortcuts(self):
        try:
            _SHORTCUTS_FILE.write_text(json.dumps(self._shortcuts, ensure_ascii=False, indent=2))
        except Exception as e:
            _log.error("No se pudieron guardar los accesos directos: %s", e)
    # ── Estilo global del widget ───────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet(f"""
            QWidget#newTabPage {{
                background: {self.colors['surface_0']};
            }}
            QPushButton#settingsBtn {{
                background: transparent;
                border: none;
                border-radius: 4px;
                font-size: 16px;
                color: {self.colors['text_muted']};
            }}
            QPushButton#settingsBtn:hover {{
                background: {self.colors['surface_hover']};
                color: {self.colors['text_secondary']};
            }}
        """)
    def update_ai_suggestion(self, text: str):
        """Actualiza el texto de sugerencia IA desde fuera."""
        if hasattr(self, "_ai_text"):
            self._ai_text.setText(text[:120])
    def set_colors(self, colors: dict):
        """Permite cambiar la paleta de colores (para cambio de tema)."""
        self.colors = colors
        self._apply_style()
        # Reconstruir shortcuts con nuevos colores
        if hasattr(self, "_shortcuts_frame"):
            grid = self._shortcuts_frame.layout()
            if grid:
                self._populate_shortcuts(grid)
