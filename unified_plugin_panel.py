#!/usr/bin/env python3
"""
Unified Plugin Panel - Panel unificado SIMPLIFICADO para gestión de plugins
Versión rediseñada: Solo Tienda y Gestión
"""

from i18n import tr
from typing import Optional
import html
import logging
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
    QPushButton, QLabel, QHeaderView, QMessageBox, QFrame,
    QListWidget, QListWidgetItem, QScrollArea, QProgressBar
)
from PySide6.QtCore import Qt, QTimer, Signal, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QIcon
from base_panel import BasePanel, ICONS_AVAILABLE, resolve_icon_path, build_strip_icon
from unified_plugin_manager import UnifiedPluginManager, PluginInfo, PluginAccessInfo, PluginAccessLevel

logger = logging.getLogger(__name__)


class UnifiedPluginPanel(BasePanel):
    """Panel unificado SIMPLIFICADO para gestión de plugins"""

    # Resultado del refresco de licencias hecho en un hilo (C-003):
    # (éxito, nº de licencias, mensaje de error)
    _licenses_refresh_done = Signal(bool, int, str)

    def __init__(self, plugin_manager: UnifiedPluginManager, parent=None):
        # Inicializar elementos UI antes de super().__init__
        self.plugin_list = None
        self.status_label = None
        self.progress_bar = None
        self.management_table = None

        super().__init__(parent)
        self.plugin_manager = plugin_manager
        self.plugins_loaded = False

        # Estado de la prueba gratuita (/licenses/me/trial), cacheado 60 s
        self._trial = None
        self._trial_fetched_at = 0.0

        # Contador para prevenir bucle infinito
        self._ui_init_attempts = 0
        self._max_ui_init_attempts = 3

        # Un único refresco diferido: el login dispara access_granted por cada
        # plugin además de auth_state_changed/login_successful, y refrescar el
        # panel completo en cada señal hacía decenas de recargas seguidas.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_all_after_login)

        # Refresco de licencias en segundo plano (no bloquea la GUI)
        self._licenses_refresh_running = False
        self._licenses_refresh_done.connect(self._on_licenses_refreshed, Qt.QueuedConnection)

        # Conectar señales del plugin manager
        self.plugin_manager.plugin_installed.connect(self.on_plugin_installed)
        self.plugin_manager.plugin_uninstalled.connect(self.on_plugin_uninstalled)
        self.plugin_manager.plugin_error.connect(self.on_plugin_error)
        self.plugin_manager.access_granted.connect(self.on_access_granted)

        # Conectar señales de autenticación
        if self.plugin_manager.auth_manager:
            self.plugin_manager.auth_manager.auth_state_changed.connect(self.on_auth_state_changed)
            self.plugin_manager.auth_manager.login_successful.connect(self.on_login_successful)
            print(tr("[UnifiedPluginPanel] Conectado a señales de autenticación"))
        # Cargar plugins después de que las pestañas estén listas
        QTimer.singleShot(500, self.initial_load)
    def get_tab_definitions(self):
        """Definir SOLO 2 pestañas: Tienda y Gestión"""
        return [
            (self.create_store_tab, "store", "Tienda"),
            (self.create_management_tab, "ide_gear", tr("Gestión")),
        ]

    # Tamaño compacto de los botones-icono, igual que en el resto de paneles
    _BTN_SIZE = 28
    _BTN_ICON = 16

    def _apply_base_theme(self):
        """Aplicar tema al panel y actualizar widgets con colores dinámicos."""
        super()._apply_base_theme()
        c = self.get_theme_colors()
        # Estilos propios de la tienda, por objectName: así tarjetas, insignias
        # y tabla siguen el tema activo sin tener que reconstruirse.
        self.setStyleSheet(self.styleSheet() + f"""
            QLabel#storeTitle {{
                font-size: 11px; font-weight: 600; letter-spacing: 0.8px;
                color: {c['text_secondary']}; background: transparent;
            }}
            QLabel#storeHint, QLabel#storeStatus {{
                font-size: 11px; color: {c['text_secondary']}; background: transparent;
            }}
            QListWidget#storeList {{
                background: transparent; border: none; outline: none;
            }}
            QListWidget#storeList::item,
            QListWidget#storeList::item:hover,
            QListWidget#storeList::item:selected {{
                background: transparent; border: none; padding: 0px;
            }}
            QWidget#storeCardWrap {{ background: transparent; }}
            QFrame#storeCard {{
                background: {c['surface_1']};
                border: 1px solid {c['border']};
                border-radius: 6px;
            }}
            QFrame#storeCard:hover {{ border-color: {c['accent']}; }}
            QFrame#storeCard QLabel {{ background: transparent; border: none; }}
            QFrame#storeCard QWidget#storeCardRow {{ background: transparent; }}
            QLabel#storeCardName {{
                font-size: 12px; font-weight: 600; color: {c['text_primary']};
            }}
            QLabel#storeCardDesc {{ font-size: 11px; color: {c['text_secondary']}; }}
            QLabel#storeBadge {{
                font-size: 9px; font-weight: 600; letter-spacing: 0.5px;
                padding: 1px 6px; border-radius: 3px;
            }}
            QFrame#storeCard QLabel#storeBadge[kind="installed"] {{
                color: {c['accent']}; background: {c['accent_subtle']};
            }}
            QFrame#storeCard QLabel#storeBadge[kind="subscribed"] {{
                color: {c['success']}; border: 1px solid {c['success']};
            }}
            QFrame#storeCard QLabel#storeBadge[kind="premium"] {{
                color: {c['warning']}; border: 1px solid {c['warning']};
            }}
            QFrame#storeCard QLabel#storeBadge[kind="trial"] {{
                color: {c['accent']}; border: 1px solid {c['accent']};
            }}
            QLabel#storeCardTrial {{ font-size: 11px; font-weight: 600; color: {c['accent']}; }}
            QFrame#storeTrialBanner {{
                background: {c['accent_subtle']};
                border: 1px solid {c['accent']};
                border-radius: 6px;
            }}
            QFrame#storeTrialBanner QLabel {{ background: transparent; border: none; }}
            QLabel#storeTrialTitle {{ font-size: 12px; font-weight: 600; color: {c['accent']}; }}
            QLabel#storeTrialText {{ font-size: 11px; color: {c['text_primary']}; }}
            QPushButton#katphiIconBtn[kind="danger"]:hover {{
                border-color: {c['error']}; background: {c['error_subtle']};
            }}
            QPushButton#katphiIconBtn[kind="primary"] {{ border-color: {c['accent']}; }}
            QProgressBar {{
                background: {c['surface_1']}; border: none; border-radius: 2px;
                max-height: 4px; min-height: 4px;
            }}
            QProgressBar::chunk {{ background: {c['accent']}; border-radius: 2px; }}
            QTableWidget#storeTable {{
                background: {c['surface_1']};
                alternate-background-color: {c['surface_1']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                gridline-color: {c['border']};
                font-size: 11px;
            }}
            QTableWidget#storeTable::item:selected {{ background: {c['selected']}; }}
            QTableWidget#storeTable QWidget {{ background: transparent; }}
            QLabel#storeCell {{ padding: 0px 6px; color: {c['text_primary']}; }}
            QLabel#storeCell[kind="success"] {{ color: {c['success']}; }}
            QLabel#storeCell[kind="warning"] {{ color: {c['warning']}; }}
            QLabel#storeCell[kind="error"] {{ color: {c['error']}; }}
            QLabel#storeCell[kind="text_secondary"] {{ color: {c['text_secondary']}; }}
            QHeaderView::section {{
                background: {c['surface_0']};
                color: {c['text_secondary']};
                border: none;
                border-bottom: 1px solid {c['border']};
                padding: 4px 6px;
                font-size: 10px; font-weight: 600;
            }}
            QTableCornerButton::section {{ background: {c['surface_0']}; border: none; }}
        """)
        for lbl in self.findChildren(QLabel, "storeLockIcon"):
            lbl.setPixmap(self._themed_pixmap("lock", 16))

    def _themed_pixmap(self, icon_name: str, size: int):
        """Icono SVG teñido con el color secundario del tema activo."""
        color = self.get_theme_colors().get("text_secondary", "#A0A0A0")
        path = resolve_icon_path(icon_name) if ICONS_AVAILABLE else ""
        if path:
            return build_strip_icon(path, color, QSize(size, size)).pixmap(size, size)
        return QIcon(f"icons/{icon_name}.svg").pixmap(size, size)

    def _icon_btn(self, icon_name: str, tooltip: str, callback=None, kind: str = "") -> QPushButton:
        """Botón sólo-icono compacto y temático (como en el resto de paneles)."""
        btn = self.create_icon_button(icon_name, tooltip, callback,
                                      size=self._BTN_SIZE, icon_size=self._BTN_ICON)
        if kind:
            btn.setProperty("kind", kind)
        return btn

    def _make_header(self, title: str, buttons) -> QHBoxLayout:
        """Cabecera de pestaña: título en versalitas + botones-icono a la derecha."""
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        title_label = QLabel(title.upper())
        title_label.setObjectName("storeTitle")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        for icon_name, tooltip, callback in buttons:
            header_layout.addWidget(self._icon_btn(icon_name, tooltip, callback))
        return header_layout

    def initial_load(self):
        """Carga inicial de plugins"""
        if not self.plugins_loaded:
            print(tr("[UnifiedPluginPanel] Iniciando carga inicial de plugins..."))
            self.plugins_loaded = True
            self.load_available_plugins()
            self.refresh_management_tab()
    # ==================== PRUEBA GRATUITA ====================

    def _get_trial(self, force: bool = False):
        """Estado de la prueba gratuita de la cuenta, o None."""
        import time as _time
        auth = self.plugin_manager.auth_manager
        if not auth or not auth.auth_state.is_authenticated:
            self._trial = None
            return None
        if not force and self._trial_fetched_at and _time.time() - self._trial_fetched_at < 60:
            return self._trial
        backend = getattr(auth, "backend", None)
        trial = None
        if backend is not None and hasattr(backend, "get_trial_status"):
            try:
                trial = backend.get_trial_status()
            except Exception as e:
                logger.warning(tr("No se pudo consultar la prueba gratuita: {e}", e=e))
        self._trial = trial
        self._trial_fetched_at = _time.time()
        return trial

    def _trial_for(self, plugin_id: str):
        """La prueba activa si cubre este plugin, si no None."""
        trial = self._trial
        if trial and trial.get("active") and plugin_id in trial.get("plugin_ids", ()):
            return trial
        return None

    @staticmethod
    def _trial_end_text(trial) -> str:
        from datetime import datetime
        try:
            return datetime.fromisoformat(str(trial.get("ends_at"))).strftime("%d/%m/%Y")
        except Exception:
            return ""

    @staticmethod
    def _days_text(days: int) -> str:
        return tr("1 día") if days == 1 else tr("{days} días", days=days)

    def _create_trial_banner(self, trial) -> QWidget:
        """Aviso superior de la tienda con la prueba gratuita activa."""
        widget = QWidget()
        widget.setObjectName("storeCardWrap")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        frame = QFrame()
        frame.setObjectName("storeTrialBanner")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(2)
        days = trial.get("days_remaining", 0)
        title = QLabel(tr("Prueba gratuita activa: te quedan {value}", value=self._days_text(days)))
        title.setObjectName("storeTrialTitle")
        title.setWordWrap(True)
        inner.addWidget(title)
        end = self._trial_end_text(trial)
        text = QLabel(
            tr("Puedes instalar y usar todos los plugins premium")
            + (tr(" hasta el {end}", end=end) if end else "")
            + tr(". Después, suscríbete solo a los que quieras seguir usando.")
        )
        text.setObjectName("storeTrialText")
        text.setWordWrap(True)
        inner.addWidget(text)
        layout.addWidget(frame)
        return widget

    # ==================== PESTAÑA TIENDA ====================

    def create_store_tab(self):
        """Crear pestaña de tienda de plugins"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addLayout(self._make_header(tr("Tienda de plugins"), [
            ("key", tr("Refrescar licencias — actualiza el estado de tus suscripciones desde el servidor"),
             self.refresh_licenses_from_backend),
            ("refresh", tr("Actualizar"), self.load_available_plugins),
        ]))

        # Lista de plugins
        self.plugin_list = QListWidget()
        self.plugin_list.setObjectName("storeList")
        self.plugin_list.setSpacing(3)
        self.plugin_list.setSelectionMode(QListWidget.NoSelection)
        self.plugin_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        layout.addWidget(self.plugin_list)

        # Barra de progreso
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Etiqueta de estado
        self.status_label = QLabel(tr("Cargando plugins..."))
        self.status_label.setObjectName("storeStatus")
        layout.addWidget(self.status_label)

        return widget

    # ==================== PESTAÑA GESTIÓN ====================

    def create_management_tab(self):
        """Crear pestaña de gestión de plugins"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addLayout(self._make_header(tr("Mis plugins"), [
            ("refresh", tr("Actualizar"), self.refresh_management_tab),
        ]))

        # Descripción
        desc_label = QLabel(
            tr("Plugins instalados localmente. Inicia sesión para ver el estado de tus suscripciones.")
        )
        desc_label.setObjectName("storeHint")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Tabla de plugins suscritos
        self.management_table = QTableWidget()
        self.management_table.setObjectName("storeTable")
        self.management_table.setColumnCount(6)
        self.management_table.setHorizontalHeaderLabels([
            tr("Plugin"), tr("Estado"), tr("Expira"), tr("Instalado"), "", ""
        ])
        self.management_table.horizontalHeaderItem(4).setToolTip(tr("Instalar / desinstalar"))
        self.management_table.horizontalHeaderItem(5).setToolTip(tr("Información"))
        self.management_table.verticalHeader().setVisible(False)
        self.management_table.verticalHeader().setDefaultSectionSize(self._BTN_SIZE + 12)
        self.management_table.setShowGrid(False)
        self.management_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.management_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.management_table.setFocusPolicy(Qt.NoFocus)

        # Configurar tabla
        header = self.management_table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 4):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
        for col in (4, 5):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.management_table.setColumnWidth(col, self._BTN_SIZE + 10)

        layout.addWidget(self.management_table)

        return widget

    def _set_colored_item(self, row: int, col: int, text: str, color_key: str) -> None:
        """Celda de texto coloreada con un color del tema (vía QSS, sigue al tema)."""
        label = QLabel(text)
        label.setObjectName("storeCell")
        label.setProperty("kind", color_key)
        label.setWordWrap(col == 0)  # nombre del plugin / mensajes a ancho completo
        self.management_table.setCellWidget(row, col, label)

    def _fit_text_columns(self) -> None:
        """Ajusta Estado/Expira/Instalado a su contenido (las celdas son QLabel)."""
        table = self.management_table
        header = table.horizontalHeader()
        for col in range(1, 4):
            width = header.sectionSizeFromContents(col).width()
            for row in range(table.rowCount()):
                if table.columnSpan(row, 0) > 1:
                    continue
                cell = table.cellWidget(row, col)
                if cell:
                    width = max(width, cell.sizeHint().width())
            table.setColumnWidth(col, width + 4)

    def _cell_button(self, btn: QPushButton) -> QWidget:
        """Centra un botón-icono dentro de una celda de la tabla."""
        cell = QWidget()
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(0, 0, 0, 0)
        cell_layout.addWidget(btn, 0, Qt.AlignCenter)
        return cell
    def refresh_management_tab(self):
        """Refrescar tabla de gestión con todos los plugins instalados localmente."""
        if not hasattr(self, 'management_table'):
            return
        self.management_table.setRowCount(0)

        is_authenticated = (
            self.plugin_manager.auth_manager is not None
            and self.plugin_manager.auth_manager.auth_state.is_authenticated
        )

        if is_authenticated:
            self._get_trial()

        # Siempre mostrar plugins instalados localmente
        local_ids = self.plugin_manager.get_installed_plugins()

        # Sin plugins locales NO se sale aquí: un usuario recién suscrito no tiene
        # nada instalado y necesita ver sus plugins suscritos con el botón Instalar.
        for plugin_id in local_ids:
            plugin_info = self.plugin_manager.get_plugin_info(plugin_id)
            if plugin_info is None:
                # Leer plugin_info.json del directorio si existe
                import json as _json
                from pathlib import Path as _Path
                info_file = self.plugin_manager.plugins_dir / plugin_id / "plugin_info.json"
                _meta: dict = {}
                if info_file.exists():
                    try:
                        _meta = _json.loads(info_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                plugin_info = PluginInfo(
                    id=plugin_id,
                    name=_meta.get("name", plugin_id.replace("_", " ").title()),
                    version=_meta.get("version", "—"),
                    description=_meta.get("description", tr("Plugin instalado localmente")),
                    author=_meta.get("author", "—"),
                    price=float(_meta.get("price", 0.0)),
                    category=_meta.get("category", "local"),
                )

            # get_plugin_access() ya resuelve correctamente el caso sin sesión:
            # devuelve FREE+is_licensed=True para un plugin gratuito de verdad,
            # y NONE (sin acceso) para uno premium sin login/licencia — no hace
            # falta (ni es correcto) fabricar aquí un PluginAccessInfo distinto.
            access_info = self.plugin_manager.get_plugin_access(plugin_id)
            self._add_plugin_to_management_table(plugin_info, access_info)

        # Si además está autenticado, añadir plugins suscritos no instalados
        if is_authenticated:
            try:
                backend_plugins = self.plugin_manager.load_available_plugins() or []
                for plugin_info in backend_plugins:
                    if plugin_info.id in local_ids:
                        continue
                    access_info = self.plugin_manager.get_plugin_access(plugin_info.id)
                    if access_info.access_level in [PluginAccessLevel.PREMIUM, PluginAccessLevel.TRIAL]:
                        self._add_plugin_to_management_table(plugin_info, access_info)
            except Exception as e:
                logger.warning(tr("No se pudieron cargar plugins del backend: {e}", e=e))

        if self.management_table.rowCount() == 0:
            self._show_no_subscriptions_message()
        self._fit_text_columns()
    def _add_plugin_to_management_table(self, plugin_info: PluginInfo, access_info: PluginAccessInfo):
        """Agregar un plugin a la tabla de gestión"""
        row = self.management_table.rowCount()
        self.management_table.insertRow(row)

        # Columna 0: Nombre del plugin
        self._set_colored_item(row, 0, f"<b>{html.escape(plugin_info.name)}</b>", "text_primary")

        # Columna 1: Estado
        trial = self._trial_for(plugin_info.id) if access_info.is_licensed else None
        if trial:
            self._set_colored_item(row, 1, tr("Prueba ({value}d)", value=trial.get('days_remaining', 0)), "warning")
        elif access_info.access_level == PluginAccessLevel.PREMIUM:
            self._set_colored_item(row, 1, "Premium", "success")
        elif access_info.access_level == PluginAccessLevel.TRIAL:
            self._set_colored_item(row, 1, tr("Prueba ({trial_remaining}d)", trial_remaining=access_info.trial_remaining), "warning")
        elif access_info.access_level == PluginAccessLevel.FREE:
            self._set_colored_item(row, 1, tr("Gratis"), "text_secondary")
        else:  # NONE (sin sesión/licencia) o EXPIRED
            self._set_colored_item(row, 1, tr("Sin acceso — inicia sesión"), "error")

        # Columna 2: Fecha de expiración
        expires_text = "N/A"
        if access_info.license_info and hasattr(access_info.license_info, 'expires_at'):
            from datetime import datetime
            try:
                if access_info.license_info.expires_at:
                    # Verificar si expires_at es timestamp (float) o string ISO
                    if isinstance(access_info.license_info.expires_at, (int, float)):
                        expires_date = datetime.fromtimestamp(access_info.license_info.expires_at)
                    else:
                        expires_date = datetime.fromisoformat(str(access_info.license_info.expires_at).replace('Z', '+00:00'))
                    expires_text = expires_date.strftime('%Y-%m-%d')
            except Exception as e:
                logger.warning(tr("Error parsing expires_at: {e}", e=e))
                expires_text = "N/A"
        self._set_colored_item(row, 2, expires_text, "text_secondary")

        # Columna 3: Instalado (Si/No)
        is_installed = self.plugin_manager.is_plugin_installed(plugin_info.id)
        if is_installed:
            self._set_colored_item(row, 3, tr("Sí"), "success")
        else:
            self._set_colored_item(row, 3, tr("No"), "text_secondary")

        # Columna 4: Botón de Acción (Instalar/Desinstalar)
        if is_installed:
            action_btn = self._icon_btn(
                "ide_trash", tr("Desinstalar"),
                lambda checked=False, pid=plugin_info.id: self.uninstall_plugin(pid),
                kind="danger")
        else:
            action_btn = self._icon_btn(
                "download", tr("Instalar"),
                lambda checked=False, pid=plugin_info.id: self.install_plugin(pid),
                kind="primary")
        self.management_table.setCellWidget(row, 4, self._cell_button(action_btn))

        # Columna 5: Botón de Información
        info_btn = self._icon_btn(
            "info", tr("Ver información del plugin"),
            lambda checked=False, pinfo=plugin_info: self.show_plugin_info_simple(pinfo))
        self.management_table.setCellWidget(row, 5, self._cell_button(info_btn))
    def _show_auth_required_message(self):
        """Mostrar mensaje de que se requiere autenticación"""
        self.management_table.setRowCount(1)
        self._set_colored_item(0, 0, tr("Por favor, inicia sesión para ver tus plugins suscritos"),
                               "text_secondary")
        self.management_table.setSpan(0, 0, 1, 6)
    def _show_no_subscriptions_message(self):
        """Mostrar mensaje de que no hay suscripciones"""
        self.management_table.setRowCount(1)
        self._set_colored_item(
            0, 0,
            tr("No tienes plugins suscritos. Visita la pestaña Tienda para ver los plugins disponibles."),
            "text_secondary")
        self.management_table.setSpan(0, 0, 1, 6)
    def show_plugin_info_simple(self, plugin_info: PluginInfo):
        """Mostrar información básica del plugin"""
        QMessageBox.information(
            self,
            f"{plugin_info.name}",
            tr("<b>Nombre:</b> {name}<br><b>Versión:</b> {version}<br><b>Autor:</b> {author}<br><br><b>Descripción:</b><br>{description}<br><br><b>Características:</b><br>• ", name=plugin_info.name, version=plugin_info.version, author=plugin_info.author, description=tr(plugin_info.description or "")) + "<br>• ".join([tr(x) for x in plugin_info.features[:5]] if plugin_info.features else [tr("No disponible")])
        )
    # ==================== ACCIONES DE PLUGINS ====================

    def install_plugin(self, plugin_id: str):
        """Instalar un plugin"""
        if not self.plugin_manager.auth_manager or not self.plugin_manager.auth_manager.auth_state.is_authenticated:
            QMessageBox.warning(self, tr("Autenticación Requerida"), 
                               tr("Por favor, inicia sesión para instalar plugins."))
            return
        # Verificar si ya está instalado
        if self.plugin_manager.is_plugin_installed(plugin_id):
            QMessageBox.information(self, tr("Plugin Ya Instalado"), 
                                   tr("El plugin '{plugin_id}' ya está instalado.", plugin_id=plugin_id))
            return
        # Iniciar instalación
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(tr("Descargando {plugin_id}...", plugin_id=plugin_id))

        success = self.plugin_manager.install_plugin(
            plugin_id, 
            self.progress_bar.setValue
        )

        if not success:
            QMessageBox.warning(self, tr("Error de Instalación"), 
                               tr("No se pudo iniciar la instalación del plugin."))
            self.progress_bar.setVisible(False)
            self.status_label.setText(tr("Error de instalación"))
    def uninstall_plugin(self, plugin_id: str):
        """Desinstalar un plugin"""
        reply = QMessageBox.question(
            self, tr("Confirmar Desinstalación"),
            tr("¿Estás seguro de que quieres desinstalar el plugin '{plugin_id}'?\n\nEsto eliminará todos sus archivos.", plugin_id=plugin_id),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            success = self.plugin_manager.uninstall_plugin(plugin_id)

            if success:
                QMessageBox.information(self, tr("Desinstalación Exitosa"), 
                                       tr("Plugin '{plugin_id}' ha sido desinstalado exitosamente.", plugin_id=plugin_id))
                self.refresh_management_tab()
                self.load_available_plugins()
            else:
                QMessageBox.warning(self, tr("Error"), 
                                   tr("No se pudo desinstalar el plugin '{plugin_id}'.", plugin_id=plugin_id))
    # ==================== CARGA DE PLUGINS PARA TIENDA ====================

    def load_available_plugins(self):
        """Cargar plugins disponibles desde el backend"""
        print("[UnifiedPluginPanel] load_available_plugins() called")

        if not hasattr(self, 'status_label') or not hasattr(self, 'plugin_list'):
            print("[UnifiedPluginPanel] WARNING: UI elements not ready yet")
            self._ui_init_attempts += 1
            if self._ui_init_attempts < self._max_ui_init_attempts:
                QTimer.singleShot(1000, self.load_available_plugins)
            return
        self._ui_init_attempts = 0
        self.status_label.setText(tr("Cargando plugins desde el servidor..."))
        self.plugin_list.clear()

        if not self.plugin_manager.auth_manager:
            self.status_label.setText(tr("Error: Sistema de autenticación no disponible"))
            return
        if not self.plugin_manager.auth_manager.auth_state.is_authenticated:
            print("[UnifiedPluginPanel] User not authenticated")
            self.status_label.setText(tr("Por favor, inicia sesión para ver los plugins disponibles"))
            auth_item = QListWidgetItem()
            auth_widget = self.create_auth_required_widget()
            auth_item.setSizeHint(auth_widget.sizeHint())
            self.plugin_list.addItem(auth_item)
            self.plugin_list.setItemWidget(auth_item, auth_widget)
            return
        print("[UnifiedPluginPanel] User authenticated, loading plugins from backend...")
        try:
            plugins = self.plugin_manager.load_available_plugins()
            print(f"[UnifiedPluginPanel] Loaded {len(plugins) if plugins else 0} plugins")

            if not plugins or len(plugins) == 0:
                self.status_label.setText(tr("No hay plugins disponibles en el servidor"))
                return
            trial = self._get_trial(force=True)
            if trial and trial.get("active"):
                banner_item = QListWidgetItem()
                banner = self._create_trial_banner(trial)
                banner_item.setSizeHint(banner.sizeHint())
                self.plugin_list.addItem(banner_item)
                self.plugin_list.setItemWidget(banner_item, banner)
            for plugin_info in plugins:
                print(f"[UnifiedPluginPanel] Adding plugin: {plugin_info.name}")
                self.add_plugin_to_list(plugin_info)
            self.status_label.setText(tr("Cargados {count} plugins disponibles", count=len(plugins)))
        except Exception as e:
            print(tr("[UnifiedPluginPanel] ERROR loading plugins: {e}", e=e))
            import traceback
            traceback.print_exc()
            self.status_label.setText(tr("Error al cargar plugins: {value}", value=str(e)))
    def add_plugin_to_list(self, plugin_info: PluginInfo):
        """Agregar un plugin a la lista de la tienda"""
        if not hasattr(self, 'plugin_list'):
            return
        item = QListWidgetItem()
        plugin_widget = self.create_plugin_widget(plugin_info)
        item.setSizeHint(plugin_widget.sizeHint())
        self.plugin_list.addItem(item)
        self.plugin_list.setItemWidget(item, plugin_widget)
    def create_plugin_widget(self, plugin_info: PluginInfo) -> QWidget:
        """Crear widget para un plugin en la tienda"""
        widget = QWidget()
        widget.setObjectName("storeCardWrap")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        access_info = self.plugin_manager.get_plugin_access(plugin_info.id)
        is_free = access_info.access_level == PluginAccessLevel.FREE
        has_subscription = access_info.access_level in [PluginAccessLevel.PREMIUM, PluginAccessLevel.TRIAL]
        is_installed = self.plugin_manager.is_plugin_installed(plugin_info.id)

        container = QFrame()
        container.setObjectName("storeCard")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(10, 8, 8, 8)
        container_layout.setSpacing(4)

        # Encabezado: nombre + insignia de estado + acciones
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        name_label = QLabel(plugin_info.name)
        name_label.setObjectName("storeCardName")
        header_layout.addWidget(name_label)

        trial = self._trial_for(plugin_info.id) if access_info.is_licensed else None

        if is_installed:
            badge_text, badge_kind = tr("INSTALADO"), "installed"
        elif trial:
            badge_text, badge_kind = tr("PRUEBA"), "trial"
        elif is_free:
            badge_text, badge_kind = tr("GRATIS"), "installed"
        elif has_subscription:
            badge_text, badge_kind = tr("SUSCRITO"), "subscribed"
        else:
            badge_text, badge_kind = "PREMIUM", "premium"
        status_badge = QLabel(badge_text)
        status_badge.setObjectName("storeBadge")
        status_badge.setProperty("kind", badge_kind)
        header_layout.addWidget(status_badge, 0, Qt.AlignVCenter)

        header_layout.addStretch()

        header_layout.addWidget(self._icon_btn(
            "info", tr("Más información"),
            lambda checked=False, pinfo=plugin_info: self.show_plugin_info_simple(pinfo)))

        # Suscrito pero sin instalar: instalar directamente desde la tienda
        if (has_subscription or is_free) and not is_installed:
            header_layout.addWidget(self._icon_btn(
                "download", tr("Instalar"),
                lambda checked=False, pid=plugin_info.id: self.install_plugin(pid),
                kind="primary"))

        # Botón de URL del sitio web (se abre en el navegador Katphi)
        header_layout.addWidget(self._icon_btn(
            "link", tr("Ver en la web"),
            lambda checked=False, pid=plugin_info.id: self.open_plugin_in_browser(pid)))

        container_layout.addLayout(header_layout)

        # Descripción
        desc_label = QLabel(tr(plugin_info.description or ""))
        desc_label.setObjectName("storeCardDesc")
        desc_label.setWordWrap(True)
        desc_label.setMaximumHeight(44)
        container_layout.addWidget(desc_label)

        if trial:
            days = trial.get("days_remaining", 0)
            end = self._trial_end_text(trial)
            trial_label = QLabel(
                tr("Prueba gratuita: quedan {value}", value=self._days_text(days))
                + (tr(" (hasta el {end})", end=end) if end else "")
            )
            trial_label.setObjectName("storeCardTrial")
            trial_label.setWordWrap(True)
            container_layout.addWidget(trial_label)

        layout.addWidget(container)

        return widget
    def open_plugin_in_browser(self, plugin_id: str):
        """Abrir URL del plugin en el navegador KATPHI (no externo)"""
        try:
            from network_config import get_website_url
            website_url = get_website_url()
            url = f"{website_url}/app/dashboard.html?plugin={plugin_id}"

            # Emitir señal para abrir en el navegador Katphi
            # Buscar la ventana principal del navegador
            main_window = self.window()
            if hasattr(main_window, 'browser_widget'):
                # Crear nueva pestaña con la URL
                main_window.browser_widget.tabs_widget.add_tab(url)
                QMessageBox.information(self, tr("Abriendo en Navegador"), 
                                       tr("Se ha abierto una nueva pestaña con el plugin '{plugin_id}'.", plugin_id=plugin_id))
            else:
                QMessageBox.warning(self, tr("Error"), 
                                   tr("No se pudo abrir en el navegador. Abriendo en navegador externo..."))
                QDesktopServices.openUrl(QUrl(url))
        except Exception as e:
            print(tr("[UnifiedPluginPanel] Error opening plugin in browser: {e}", e=e))
            QMessageBox.warning(self, tr("Error"), 
                               tr("No se pudo abrir la URL del plugin:\n{value}", value=str(e)))
    def create_auth_required_widget(self) -> QWidget:
        """Widget para mostrar que se requiere autenticación"""
        widget = QWidget()
        widget.setObjectName("storeCardWrap")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("storeCard")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(10, 8, 10, 8)
        container_layout.setSpacing(4)

        title_layout = QHBoxLayout()
        title_layout.setSpacing(6)
        title_icon_label = QLabel()
        title_icon_label.setObjectName("storeLockIcon")
        title_icon_label.setPixmap(self._themed_pixmap("lock", 16))
        title_layout.addWidget(title_icon_label)
        title_label = QLabel(tr("Autenticación requerida"))
        title_label.setObjectName("storeCardName")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        container_layout.addLayout(title_layout)

        desc_label = QLabel(tr("Para acceder a los plugins disponibles, necesitas iniciar sesión con tu cuenta de usuario."))
        desc_label.setObjectName("storeCardDesc")
        desc_label.setWordWrap(True)
        container_layout.addWidget(desc_label)

        layout.addWidget(container)
        return widget
    def refresh_licenses_from_backend(self):
        """Refrescar licencias del usuario desde el backend.

        Las peticiones (/licenses/me/entitlements y /api/plugins/available) se
        hacen en un hilo; el resultado vuelve por _licenses_refresh_done
        (conexión encolada) y la UI se toca solo en el hilo de la GUI.
        """
        print(tr("[UnifiedPluginPanel] Refrescando licencias desde el backend..."))

        if self._licenses_refresh_running:
            print(tr("[UnifiedPluginPanel] Refresco de licencias ya en curso"))
            return
        try:
            from backend_integration import backend_integration

            if not backend_integration.is_authenticated():
                QMessageBox.warning(self, tr("No Autenticado"), 
                                  tr("Debes iniciar sesión para refrescar las licencias."))
                return
        except Exception as e:
            print(tr("[UnifiedPluginPanel] Error al refrescar licencias: {e}", e=e))
            QMessageBox.critical(self, tr("Error"), tr("Error al refrescar licencias:\n{value}", value=str(e)))
            return
        self._licenses_refresh_running = True
        if self.status_label:
            self.status_label.setText(tr("Refrescando licencias..."))

        def _worker():
            try:
                ok = bool(backend_integration.refresh_licenses())
                self._licenses_refresh_done.emit(ok, len(backend_integration.user_licenses), "")
            except Exception as e:
                self._licenses_refresh_done.emit(False, 0, str(e))

        try:
            threading.Thread(target=_worker, name="katphi-refresh-licenses", daemon=True).start()
        except Exception as e:
            self._licenses_refresh_running = False
            QMessageBox.critical(self, tr("Error"), tr("Error al refrescar licencias:\n{value}", value=str(e)))
    def _on_licenses_refreshed(self, success: bool, count: int, error: str):
        """Resultado del refresco de licencias (hilo de la GUI)"""
        self._licenses_refresh_running = False

        if error:
            print(tr("[UnifiedPluginPanel] Error al refrescar licencias: {error}", error=error))
            QMessageBox.critical(self, tr("Error"), tr("Error al refrescar licencias:\n{error}", error=error))
            return
        if success:
            # Las licencias de AuthManager (las que usa el panel) se
            # recalculan con lo que acaba de cargar el backend
            try:
                am = self.plugin_manager.auth_manager
                if am:
                    am._load_user_entitlements()
            except Exception as e:
                print(tr("[UnifiedPluginPanel] No se pudieron recargar las licencias locales: {e}", e=e))
            self.refresh_all_after_login()
            QMessageBox.information(self, tr("Licencias Actualizadas"),
                                  tr("Las licencias se han actualizado correctamente.\n\nLicencias activas: {count}", count=count))
            print(tr("[UnifiedPluginPanel] Licencias refrescadas: {count} activas", count=count))
        else:
            if self.status_label:
                self.status_label.setText(tr("No se pudieron refrescar las licencias"))
            QMessageBox.warning(self, tr("Error"),
                              tr("No se pudieron refrescar las licencias. Verifica tu conexión."))
    # ==================== MANEJADORES DE SEÑALES ====================

    def on_plugin_installed(self, plugin_id: str):
        """Manejar instalación exitosa de plugin"""
        print(f"[UnifiedPluginPanel] Plugin '{plugin_id}' installed successfully")
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(False)
        if hasattr(self, 'status_label'):
            self.status_label.setText(tr("Plugin '{plugin_id}' instalado exitosamente", plugin_id=plugin_id))
        QMessageBox.information(self, tr("Instalación Exitosa"),
                               tr("Plugin '{plugin_id}' ha sido instalado exitosamente!", plugin_id=plugin_id))
        self.refresh_management_tab()
        self.load_available_plugins()
    def on_plugin_uninstalled(self, plugin_id: str):
        """Manejar desinstalación de plugin"""
        print(f"[UnifiedPluginPanel] Plugin '{plugin_id}' uninstalled")
        if hasattr(self, 'status_label'):
            self.status_label.setText(tr("Plugin '{plugin_id}' desinstalado", plugin_id=plugin_id))
        self.refresh_management_tab()
        self.load_available_plugins()
    def on_plugin_error(self, plugin_id: str, error: str):
        """Manejar error de plugin"""
        print(tr("[UnifiedPluginPanel] Error en plugin '{plugin_id}': {error}", plugin_id=plugin_id, error=error))
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(False)
        if hasattr(self, 'status_label'):
            self.status_label.setText(tr("Error: {error}", error=error))
        QMessageBox.warning(self, tr("Error de Plugin"), 
                           tr("Error en plugin '{plugin_id}':\n\n{error}", plugin_id=plugin_id, error=error))
    def on_access_granted(self, plugin_id: str):
        """Manejar acceso concedido a plugin"""
        print(f"[UnifiedPluginPanel] Access granted to plugin '{plugin_id}'")
        if hasattr(self, 'status_label'):
            self.status_label.setText(tr("Acceso concedido a plugin '{plugin_id}'", plugin_id=plugin_id))
        self._schedule_refresh(300)
    def on_auth_state_changed(self, is_authenticated: bool):
        """Manejar cambio en el estado de autenticación"""
        print(tr("[UnifiedPluginPanel] Estado de autenticación cambió: {is_authenticated}", is_authenticated=is_authenticated))

        if is_authenticated:
            self._schedule_refresh(1000)
        else:
            self._refresh_timer.stop()
            if hasattr(self, 'plugin_list') and self.plugin_list:
                self.plugin_list.clear()
            if hasattr(self, 'management_table') and self.management_table:
                self._show_auth_required_message()
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(tr("Por favor, inicia sesión"))
    def on_login_successful(self):
        """Manejar login exitoso"""
        print("[UnifiedPluginPanel] Login exitoso detectado - recargando plugins...")
        self._schedule_refresh(1500)

    def _schedule_refresh(self, delay_ms: int):
        """Agrupar varias peticiones de refresco en una sola recarga del panel"""
        self._refresh_timer.start(max(delay_ms, self._refresh_timer.remainingTime()))
    def refresh_all_after_login(self):
        """Refrescar TODO el panel después del login"""
        print(tr("[UnifiedPluginPanel] Refrescando panel completo después del login..."))

        if hasattr(self, 'load_available_plugins'):
            self.load_available_plugins()
        if hasattr(self, 'refresh_management_tab'):
            self.refresh_management_tab()
        print(tr("[UnifiedPluginPanel] Panel refrescado completamente"))
