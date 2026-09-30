#!/usr/bin/env python3
"""
Panel de Plugins Simplificado para SaaS
Sistema claro y funcional para gestión de plugins premium
"""

import logging
import webbrowser
from typing import List, Optional
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,  
    QFrame, QScrollArea, QMessageBox, QProgressBar, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QFont, QColor, QPalette

from base_panel import BasePanel
from config_manager import get_config
# Importar motor de temas
try:
    from ui.core.theme_engine import get_color, get_font, get_theme_engine
    THEME_AVAILABLE = True
except ImportError:
    THEME_AVAILABLE = False
    def get_color(key, theme=None): return "#333" if key == "primary" else "#fff"
    def get_font(key, theme=None): return "10pt"
    def get_theme_engine(): return None
# Importar iconos SVG (con fallback vacío si no está disponible)
try:
    from ui.core.strip_icons import build_nav_icon
except ImportError:
    from PySide6.QtGui import QIcon
    def build_nav_icon(name, color_hex=None, size=None, icons_dir=None): return QIcon()

# Configurar logging
logger = logging.getLogger(__name__)


class PluginRow(QFrame):
    """
    Fila de plugin — 40px, diseño minimalista:
    [icono 20px] [nombre 13px] [badge estado] [espacio] [acción]

    Reemplaza las tarjetas (PluginCard) para una lista más limpia.
    """

    install_clicked  = Signal(str)
    purchase_clicked = Signal(str)

    # Colores de diseño (independientes del motor de temas para robustez)
    _C = {
        "surface_0":     "#1A1A1A",
        "surface_hover": "#303030",
        "border":        "rgba(255,255,255,0.08)",
        "text_primary":  "#F0F0F0",
        "text_secondary":"#A0A0A0",
        "accent":        "#4B9EFF",
        "accent_subtle": "rgba(75,158,255,0.12)",
        "success":       "#3FB950",
        "success_subtle":"rgba(63,185,80,0.12)",
        "warning":       "#D29922",
        "error":         "#F85149",
    }

    def __init__(
        self,
        plugin_data: dict,
        license_data: dict = None,
        is_installed: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.plugin_data  = plugin_data
        self.license_data = license_data
        self.is_installed = is_installed

        self.setObjectName("pluginRow")
        self.setFixedHeight(48)
        self.setCursor(Qt.PointingHandCursor)
        self._setup_ui()
        self._apply_row_style()
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(10)

        # Icono (SVG por categoría)
        category = self.plugin_data.get("category", "general").lower()
        _ICON_NAMES = {
            "seo": "seo", "scraping": "scrap", "pentesting": "pentesting",
            "proxy": "proxy", "themes": "themes", "split": "splitview",
        }
        icon_name = _ICON_NAMES.get(category, "plugins")
        icon_lbl = QLabel()
        icon_lbl.setPixmap(build_nav_icon(icon_name, self._C["text_secondary"], QSize(18, 18)).pixmap(18, 18))
        icon_lbl.setFixedWidth(24)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon_lbl)

        # Nombre
        name_lbl = QLabel(self.plugin_data.get("name", "Plugin"))
        name_lbl.setObjectName("pluginName")
        name_lbl.setStyleSheet(
            f"font-size: 13px; color: {self._C['text_primary']}; "
            "background: transparent; border: none;"
        )
        layout.addWidget(name_lbl, 1)

        # Badge de estado
        badge = self._make_badge()
        if badge:
            layout.addWidget(badge)
        # Botón de acción compacto
        action_btn = self._make_action_button()
        if action_btn:
            layout.addWidget(action_btn)
    def _make_badge(self) -> QLabel | None:
        c = self._C
        if self.is_installed:
            lbl = QLabel("Active")
            lbl.setStyleSheet(
                f"background: {c['success_subtle']}; color: {c['success']}; "
                "font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 3px; "
                "border: none;"
            )
            return lbl
        if self.license_data and self.license_data.get("is_licensed"):
            trial = self.license_data.get("trial_remaining", 0)
            if trial > 0:
                lbl = QLabel(f"Trial {trial}d")
                lbl.setStyleSheet(
                    f"background: rgba(210,153,34,0.15); color: {c['warning']}; "
                    "font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 3px; "
                    "border: none;"
                )
                return lbl
        # Plugin de pago sin licencia
        if self.plugin_data.get("price", 0) > 0:
            lbl = QLabel("Pro")
            lbl.setStyleSheet(
                f"background: {c['accent_subtle']}; color: {c['accent']}; "
                "font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 3px; "
                "border: none;"
            )
            return lbl
        return None
    def _make_action_button(self) -> QPushButton | None:
        c = self._C
        if self.is_installed:
            return None  # Sin botón si ya está instalado
        if self.license_data and self.license_data.get("is_licensed"):
            btn = QPushButton(build_nav_icon("download", c['accent'], QSize(14, 14)), "")
            btn.setToolTip("Instalar")
            btn.setFixedHeight(26)
            btn.setFixedWidth(34)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['accent_subtle']}; color: {c['accent']};
                    border: 1px solid {c['accent']}; border-radius: 4px;
                    padding: 0px 10px; font-size: 12px;
                }}
                QPushButton:hover {{ background: {c['accent']}; color: #FFFFFF; }}
            """)
            btn.clicked.connect(lambda: self.install_clicked.emit(self.plugin_data["id"]))
            return btn
        if self.plugin_data.get("price", 0) > 0:
            btn = QPushButton(build_nav_icon("unlock", c['success'], QSize(14, 14)), "")
            btn.setToolTip("Suscribir")
            btn.setFixedHeight(26)
            btn.setFixedWidth(34)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['success_subtle']}; color: {c['success']};
                    border: 1px solid {c['success']}; border-radius: 4px;
                    padding: 0px 10px; font-size: 12px;
                }}
                QPushButton:hover {{ background: {c['success']}; color: #FFFFFF; }}
            """)
            btn.clicked.connect(lambda: self.purchase_clicked.emit(self.plugin_data["id"]))
            return btn
        return None
    def _apply_row_style(self):
        c = self._C
        self.setStyleSheet(f"""
            QFrame#pluginRow {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {c['border']};
            }}
            QFrame#pluginRow:hover {{
                background: {c['surface_hover']};
            }}
        """)
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            plugin_id = self.plugin_data.get("id", "")
            if self.is_installed:
                pass
            elif self.license_data and self.license_data.get("is_licensed"):
                self.install_clicked.emit(plugin_id)
            elif self.plugin_data.get("price", 0) > 0:
                self.purchase_clicked.emit(plugin_id)


# ── Compatibilidad: mantener PluginCard como alias ────────────────────────────

class PluginCard(PluginRow):
    """Alias de compatibilidad — delega a PluginRow."""
    pass


class PluginsPanelV2(BasePanel):
    """Panel de plugins simplificado - v2.0"""

    plugin_action_requested = Signal(str, str)  # plugin_id, action (install/purchase)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Datos
        self.plugins = []
        self.licenses = {}
        self.installed_plugins = set()

        # Conectar cambios de tema
        engine = get_theme_engine()
        if engine:
            engine.theme_changed.connect(self.on_theme_changed)
        # Conectar con backend
        try:
            from backend_integration import backend_integration
            self.backend = backend_integration

            # Conectar señales
            if self.backend:
                self.backend.login_successful.connect(self.on_login)
                self.backend.plugin_downloaded.connect(self.on_plugin_downloaded)
        except ImportError:
            logger.error("No se pudo importar backend_integration")
            self.backend = None
        # Cargar datos si ya está autenticado
        if self.backend and self.backend.is_authenticated():
            QTimer.singleShot(500, self.load_data)
    def on_theme_changed(self, theme_name):
        """Re-render cuando cambia el tema"""
        # Recargar la vista actual para aplicar nuevos colores
        self.load_data()
    def get_tab_definitions(self):
        """Definir pestañas del panel"""
        return [
            (self.create_main_tab, "store", "Mis Plugins")
        ]
    def create_main_tab(self):
        """Crear pestaña principal — lista de plugins en filas."""
        widget = QWidget()
        main_layout = QVBoxLayout(widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setStyleSheet(
            "background: #222222; border-bottom: 1px solid rgba(255,255,255,0.08);"
        )
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 0, 12, 0)
        toolbar.setFixedHeight(40)

        title_label = QLabel("PLUGINS")
        title_label.setStyleSheet(
            "font-size: 11px; font-weight: 600; letter-spacing: 0.8px; "
            "color: #A0A0A0; background: transparent;"
        )
        toolbar_layout.addWidget(title_label)
        toolbar_layout.addStretch()

        refresh_btn = QPushButton(build_nav_icon("refresh", "#A0A0A0", QSize(16, 16)), "")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Actualizar lista de plugins")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self.load_data)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: #303030; }
        """)
        toolbar_layout.addWidget(refresh_btn)
        main_layout.addWidget(toolbar)

        # ── Lista de plugins (scroll) ─────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: #1A1A1A; }
            QScrollBar:vertical { background: transparent; width: 6px; border: none; }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.12); border-radius: 3px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.25); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self.scroll_widget = QWidget()
        self.scroll_widget.setStyleSheet("background: #1A1A1A;")
        self.scroll_layout = QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(0)

        scroll.setWidget(self.scroll_widget)
        main_layout.addWidget(scroll)

        # ── Barra de estado ───────────────────────────────────────────────────
        status_bar = QFrame()
        status_bar.setFixedHeight(36)
        status_bar.setStyleSheet(
            "background: #222222; border-top: 1px solid rgba(255,255,255,0.08);"
        )
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(16, 0, 12, 0)

        self.status_label = QLabel("Cargando plugins...")
        self.status_label.setStyleSheet("color: #606060; font-size: 11px; background: transparent;")
        sb_layout.addWidget(self.status_label)
        sb_layout.addStretch()

        dashboard_btn = QPushButton(build_nav_icon("ide_external_link", "#4B9EFF", QSize(14, 14)), "")
        dashboard_btn.setToolTip("Dashboard")
        dashboard_btn.setFixedSize(28, 28)
        dashboard_btn.setCursor(Qt.PointingHandCursor)
        dashboard_btn.clicked.connect(self.open_dashboard)
        dashboard_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; border-radius: 4px;
            }
            QPushButton:hover { background: #303030; }
        """)
        sb_layout.addWidget(dashboard_btn)
        main_layout.addWidget(status_bar)

        return widget
    def load_data(self):
        """Cargar datos de plugins y licencias"""
        if not self.backend or not self.backend.is_authenticated():
            self.status_label.setText("Por favor, inicia sesión para ver tus plugins")
            self._show_login_message()
            return
        try:
            self.status_label.setText("Cargando plugins y licencias...")

            # Refrescar licencias
            self.backend.refresh_licenses()

            # Obtener datos
            self.plugins = self.backend.get_available_plugins()
            user_licenses = self.backend.get_user_licenses()

            # Crear diccionario de licencias por plugin_id
            self.licenses = {lic.plugin_id: lic for lic in user_licenses}

            # Obtener plugins instalados
            plugins_dir = Path("plugins")
            if plugins_dir.exists():
                self.installed_plugins = {
                    d.name for d in plugins_dir.iterdir() 
                    if d.is_dir() and (d / "__init__.py").exists()
                }
            # Actualizar UI
            self._populate_plugins()

            # Actualizar status
            licensed_count = len([l for l in user_licenses if l.is_licensed])
            installed_count = len(self.installed_plugins)

            self.status_label.setText(
                f"{len(self.plugins)} plugins disponibles | "
                f"{licensed_count} licencias activas | "
                f"{installed_count} instalados"
            )

            logger.info(f"Panel loaded: {len(self.plugins)} plugins, {licensed_count} licenses")
        except Exception as e:
            logger.error(f"Error loading plugin data: {e}")
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"Error al cargar plugins: {str(e)}")
            # QMessageBox.critical(self, "Error", f"Error al cargar plugins:\n{str(e)}")
    def _populate_plugins(self):
        """Poblar la lista de plugins"""
        # Limpiar layout
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        if not self.plugins:
            self._show_empty_message()
            return
        # Ordenar plugins: Con licencia primero
        sorted_plugins = sorted(
            self.plugins,
            key=lambda p: (
                not self.licenses.get(p.id, None),  # Con licencia primero
                not (p.id in self.installed_plugins),  # Instalados primero
                p.name  # Luego alfabéticamente
            )
        )

        # Agregar filas de plugins
        for plugin in sorted_plugins:
            plugin_dict = {
                "id": plugin.id,
                "name": plugin.name,
                "description": plugin.description,
                "version": plugin.version,
                "author": plugin.author,
                "price": plugin.price,
                "currency": plugin.currency,
                "billing_cycle": plugin.billing_cycle,
                "category": plugin.category,
                "features": plugin.features,
                "trial_days": plugin.trial_days,
            }

            license_obj = self.licenses.get(plugin.id)
            license_dict = None
            if license_obj:
                license_dict = {
                    "plugin_id":       license_obj.plugin_id,
                    "plugin_name":     license_obj.plugin_name,
                    "is_licensed":     license_obj.is_licensed,
                    "expires_at":      license_obj.expires_at,
                    "trial_remaining": license_obj.trial_remaining,
                }
            is_installed = plugin.id in self.installed_plugins

            row = PluginRow(plugin_dict, license_dict, is_installed, self)
            row.install_clicked.connect(self.install_plugin)
            row.purchase_clicked.connect(self.purchase_plugin)
            self.scroll_layout.addWidget(row)
        # Spacer al final
        self.scroll_layout.addStretch()
    def _show_empty_state(self, icon_name: str, message: str):
        """Muestra un estado vacío centrado (login requerido, sin plugins, etc.)."""
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setAlignment(Qt.AlignCenter)
        cl.setSpacing(8)
        cl.setContentsMargins(24, 48, 24, 48)

        lbl_icon = QLabel()
        lbl_icon.setPixmap(build_nav_icon(icon_name, "#606060", QSize(40, 40)).pixmap(40, 40))
        lbl_icon.setAlignment(Qt.AlignCenter)
        lbl_icon.setStyleSheet("background: transparent;")
        cl.addWidget(lbl_icon)

        lbl_msg = QLabel(message)
        lbl_msg.setAlignment(Qt.AlignCenter)
        lbl_msg.setWordWrap(True)
        lbl_msg.setStyleSheet("font-size: 13px; color: #A0A0A0; background: transparent;")
        cl.addWidget(lbl_msg)

        self.scroll_layout.addWidget(container)
        self.scroll_layout.addStretch()
    def _show_login_message(self):
        """Mostrar mensaje de login requerido."""
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._show_empty_state(
            "lock",
            "Inicia sesión para ver tus plugins y suscripciones."
        )
    def _show_empty_message(self):
        """Mostrar mensaje cuando no hay plugins."""
        self._show_empty_state("plugins", "No hay plugins disponibles.")
    def install_plugin(self, plugin_id: str):
        """Instalar un plugin"""
        logger.info(f"Installing plugin: {plugin_id}")

        if not self.backend or not self.backend.is_authenticated():
            QMessageBox.warning(self, "No Autenticado", "Debes iniciar sesión para instalar plugins")
            return
        # Verificar licencia
        if plugin_id not in self.licenses or not self.licenses[plugin_id].is_licensed:
            QMessageBox.warning(self, "Licencia Requerida", 
                              f"Necesitas una licencia activa para instalar este plugin.\n\n"
                              f"Haz clic en 'Suscribirse' para obtener acceso.")
            return
        # Mostrar progreso
        progress = QMessageBox(self)
        progress.setWindowTitle("Instalando Plugin")
        progress.setText(f"Descargando e instalando {plugin_id}...")
        progress.setStandardButtons(QMessageBox.NoButton)
        progress.show()

        try:
            # Descargar plugin
            response = self.backend.download_plugin(plugin_id)

            progress.close()

            if response.success:
                QMessageBox.information(self, "Plugin Instalado",
                                      f"El plugin se ha instalado correctamente.\n\n"
                                      f"Reinicia el navegador para comenzar a usarlo.")
                # Recargar datos
                self.load_data()
            else:
                QMessageBox.critical(self, "Error",
                                   f"No se pudo instalar el plugin:\n{response.message}")
        except Exception as e:
            progress.close()
            logger.error(f"Error installing plugin: {e}")
            QMessageBox.critical(self, "Error", f"Error al instalar:\n{str(e)}")
    def purchase_plugin(self, plugin_id: str):
        """Iniciar proceso de compra de plugin"""
        logger.info(f"Purchase requested for: {plugin_id}")

        # Obtener info del plugin
        plugin = None
        for p in self.plugins:
            if p.id == plugin_id:
                plugin = p
                break
        if not plugin:
            return
        # Abrir dashboard web en la página de suscripción
        dashboard_url = get_config().get_dashboard_url()

        msg = QMessageBox(self)
        msg.setWindowTitle("Suscripción a Plugin")
        # Usar colores seguros o texto
        msg.setText(f"<h3>{plugin.name}</h3>")
        msg.setInformativeText(
            f"<p><b>Precio:</b> ${plugin.price:.2f}/{plugin.billing_cycle}</p>"
            f"<p><b>Incluye:</b> {plugin.trial_days} días de prueba gratis</p>"
            f"<p>Para suscribirte, ve al dashboard web y completa el proceso de pago.</p>"
        )
        msg.setTextFormat(Qt.RichText)

        open_btn = msg.addButton("Abrir Dashboard", QMessageBox.ActionRole)
        cancel_btn = msg.addButton("Cancelar", QMessageBox.RejectRole)

        msg.exec()

        if msg.clickedButton() == open_btn:
            webbrowser.open(dashboard_url)

            # Mostrar instrucciones adicionales
            QMessageBox.information(self, "Instrucciones", 
                                  f"1. Completa la suscripción en el dashboard web\n"
                                  f"2. Vuelve a este panel\n"
                                  f"3. Haz clic en 'Actualizar' para refrescar tus licencias\n"
                                  f"4. El botón 'Instalar' se habilitará automáticamente")
    def open_dashboard(self):
        """Abrir dashboard web"""
        webbrowser.open(get_config().get_dashboard_url())
    def on_login(self, user):
        """Callback cuando el usuario inicia sesión"""
        logger.info(f"User logged in: {user.email}")
        QTimer.singleShot(1000, self.load_data)
    def on_plugin_downloaded(self, plugin_id: str, success: bool):
        """Callback cuando se descarga un plugin"""
        if success:
            logger.info(f"Plugin downloaded successfully: {plugin_id}")
            self.load_data()  # Recargar para actualizar estado
