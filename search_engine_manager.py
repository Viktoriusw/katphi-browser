#!/usr/bin/env python3
"""
Search Engine Manager - Gestor de motores de búsqueda

Características:
- Múltiples motores de búsqueda predefinidos
- Motor predeterminado configurable
- Selector rápido en barra de búsqueda
- Búsqueda directa desde barra de direcciones
"""

from PySide6.QtCore import QSettings, Signal, QObject, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QComboBox, QPushButton, QListWidget, QMessageBox,
                               QMenu, QToolButton)
from PySide6.QtGui import QIcon, QPixmap
import urllib.parse


class SearchEngine:
    """Representa un motor de búsqueda"""

    def __init__(self, id, name, url_template, icon_name=None, suggestions_url=None):
        """
        Args:
            id: Identificador único del motor
            name: Nombre visible del motor
            url_template: URL con {query} como placeholder
            icon_name: Nombre del archivo de icono (opcional)
            suggestions_url: URL para sugerencias (opcional)
        """
        self.id = id
        self.name = name
        self.url_template = url_template
        self.icon_name = icon_name
        self.suggestions_url = suggestions_url
    def get_search_url(self, query):
        """Generar URL de búsqueda para una consulta"""
        encoded_query = urllib.parse.quote(query)
        return self.url_template.replace("{query}", encoded_query)
    def to_dict(self):
        """Convertir a diccionario para serialización"""
        return {
            'id': self.id,
            'name': self.name,
            'url_template': self.url_template,
            'icon_name': self.icon_name,
            'suggestions_url': self.suggestions_url
        }
    @staticmethod
    def from_dict(data):
        """Crear desde diccionario"""
        return SearchEngine(
            id=data['id'],
            name=data['name'],
            url_template=data['url_template'],
            icon_name=data.get('icon_name'),
            suggestions_url=data.get('suggestions_url')
        )


class SearchEngineManager(QObject):
    """Gestor de motores de búsqueda"""

    # Señal emitida cuando cambia el motor predeterminado
    default_engine_changed = Signal(str)  # engine_id

    # Motores de búsqueda predefinidos
    PREDEFINED_ENGINES = [
        SearchEngine(
            id='google',
            name='Google',
            url_template='https://www.google.com/search?q={query}',
            icon_name='google.png',
            suggestions_url='https://www.google.com/complete/search?client=firefox&q={query}'
        ),
        SearchEngine(
            id='duckduckgo',
            name='DuckDuckGo',
            url_template='https://duckduckgo.com/?q={query}',
            icon_name='duckduckgo.png',
            suggestions_url='https://ac.duckduckgo.com/ac/?q={query}'
        ),
        SearchEngine(
            id='bing',
            name='Bing',
            url_template='https://www.bing.com/search?q={query}',
            icon_name='bing.png',
            suggestions_url='https://api.bing.com/osjson.aspx?query={query}'
        ),
        SearchEngine(
            id='yahoo',
            name='Yahoo',
            url_template='https://search.yahoo.com/search?p={query}',
            icon_name='yahoo.png'
        ),
        SearchEngine(
            id='wikipedia',
            name='Wikipedia',
            url_template='https://es.wikipedia.org/wiki/Special:Search?search={query}',
            icon_name='wikipedia.png'
        ),
        SearchEngine(
            id='youtube',
            name='YouTube',
            url_template='https://www.youtube.com/results?search_query={query}',
            icon_name='youtube.png'
        ),
        SearchEngine(
            id='github',
            name='GitHub',
            url_template='https://github.com/search?q={query}',
            icon_name='github.png'
        ),
        SearchEngine(
            id='stackoverflow',
            name='Stack Overflow',
            url_template='https://stackoverflow.com/search?q={query}',
            icon_name='stackoverflow.png'
        )
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("Katphi", "SearchEngines")
        self.engines = {}
        self.default_engine_id = None

        # Cargar motores predefinidos
        self._load_predefined_engines()

        # Cargar configuración
        self.load_settings()
    def _load_predefined_engines(self):
        """Cargar motores de búsqueda predefinidos"""
        for engine in self.PREDEFINED_ENGINES:
            self.engines[engine.id] = engine
    def load_settings(self):
        """Cargar configuración guardada"""
        # Cargar motor predeterminado
        self.default_engine_id = self.settings.value(
            "default_engine", 
            "duckduckgo"  # DuckDuckGo por defecto
        )

        # Validar que el motor existe
        if self.default_engine_id not in self.engines:
            self.default_engine_id = "duckduckgo"
    def save_settings(self):
        """Guardar configuración"""
        self.settings.setValue("default_engine", self.default_engine_id)
        self.settings.sync()
    def get_default_engine(self):
        """Obtener motor de búsqueda predeterminado"""
        return self.engines.get(self.default_engine_id)
    def set_default_engine(self, engine_id):
        """Establecer motor de búsqueda predeterminado"""
        if engine_id in self.engines:
            self.default_engine_id = engine_id
            self.save_settings()
            self.default_engine_changed.emit(engine_id)
            return True
        return False
    def get_engine(self, engine_id):
        """Obtener motor de búsqueda por ID"""
        return self.engines.get(engine_id)
    def get_all_engines(self):
        """Obtener lista de todos los motores"""
        return list(self.engines.values())
    def search(self, query, engine_id=None):
        """
        Generar URL de búsqueda

        Args:
            query: Texto a buscar
            engine_id: ID del motor (None = usar predeterminado)
        Returns:
            URL de búsqueda
        """
        if engine_id is None:
            engine = self.get_default_engine()
        else:
            engine = self.get_engine(engine_id)
        if engine:
            return engine.get_search_url(query)
        # Fallback a DuckDuckGo
        return f"https://duckduckgo.com/?q={urllib.parse.quote(query)}"
    def is_search_query(self, text):
        """
        Determinar si el texto es una búsqueda o una URL

        Returns:
            True si es una búsqueda, False si es una URL
        """
        text = text.strip()

        # Si está vacío, no es nada
        if not text:
            return False
        # Si empieza con protocolo, es URL
        if text.startswith(('http://', 'https://', 'file://', 'ftp://')):
            return False
        # Si tiene espacios, probablemente es búsqueda
        if ' ' in text:
            return True
        # Si tiene punto y no tiene espacios, probablemente es URL
        if '.' in text and ' ' not in text:
            # Verificar si tiene extensión de dominio válida
            parts = text.split('.')
            if len(parts) >= 2:
                tld = parts[-1].lower()
                # Lista de TLDs comunes
                common_tlds = ['com', 'org', 'net', 'edu', 'gov', 'io', 'co', 'uk', 
                              'es', 'de', 'fr', 'it', 'jp', 'cn', 'ru', 'br', 'in']
                if tld in common_tlds or len(tld) == 2:  # TLD de 2 letras (país)
                    return False
        # Por defecto, considerar como búsqueda
        return True


class SearchEngineButton(QToolButton):
    """
    Botón selector de motor de búsqueda para la barra de URL.
    Muestra search.svg temático + nombre del motor activo.
    """

    engine_selected = Signal(str)  # engine_id

    # Colores para los estados del icono
    _ICON_COLOR_NORMAL = "#A0A0A0"
    _ICON_COLOR_HOVER  = "#F0F0F0"

    def __init__(self, search_manager, parent=None):
        super().__init__(parent)
        self.search_manager = search_manager
        self._current_icon_color = self._ICON_COLOR_NORMAL

        self.setPopupMode(QToolButton.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(32)
        self.setMaximumWidth(130)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Cambiar motor de búsqueda")

        self._apply_style()
        self.setup_menu()
        self.update_display()
        self.search_manager.default_engine_changed.connect(self.update_display)
    def _apply_style(self):
        self.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 2px 6px;
                color: #A0A0A0;
                font-size: 12px;
            }
            QToolButton:hover {
                background: rgba(255,255,255,0.08);
                color: #F0F0F0;
            }
            QToolButton::menu-indicator {
                image: none;
                width: 0px;
            }
        """)
    def setup_menu(self):
        """Configurar menú de motores de búsqueda."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #222222;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
                padding: 4px 0px;
            }
            QMenu::item {
                padding: 7px 20px;
                color: #F0F0F0;
                font-size: 13px;
            }
            QMenu::item:selected {
                background: #303030;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255,255,255,0.08);
                margin: 2px 8px;
            }
        """)

        for engine in self.search_manager.get_all_engines():
            action = menu.addAction(engine.name)
            action.setData(engine.id)
            action.triggered.connect(
                lambda checked=False, eid=engine.id: self.select_engine(eid)
            )
        menu.addSeparator()
        manage_action = menu.addAction("Gestionar motores...")
        manage_action.triggered.connect(self.show_settings)
        self.setMenu(menu)
    def select_engine(self, engine_id: str):
        self.engine_selected.emit(engine_id)
    def update_display(self):
        """Actualiza icono y texto con el motor activo."""
        engine = self.search_manager.get_default_engine()
        if engine:
            self.setText(engine.name[:12])
        self._refresh_icon(self._current_icon_color)
    def _refresh_icon(self, color: str):
        """Reconstruye el icono search.svg con el color dado."""
        try:
            from ui.core.strip_icons import build_nav_icon, NAV_ICON_SIZE
            icon = build_nav_icon("search", color, NAV_ICON_SIZE)
            if not icon.isNull():
                self.setIcon(icon)
                self.setIconSize(NAV_ICON_SIZE)
        except Exception:
            pass
    def refresh_theme_icon(self, color: str):
        """Llamar externamente cuando cambia el tema para actualizar el color."""
        self._current_icon_color = color
        self._refresh_icon(color)
    def show_settings(self):
        dialog = SearchEngineSettingsDialog(self.search_manager, self.parent())
        dialog.exec()


class SearchEngineSettingsDialog(QDialog):
    """Diálogo de configuración de motores de búsqueda"""

    def __init__(self, search_manager, parent=None):
        super().__init__(parent)
        self.search_manager = search_manager

        self.setWindowTitle("Configuración de motores de búsqueda")
        self.setMinimumSize(500, 400)

        self.setup_ui()
    def setup_ui(self):
        """Configurar interfaz"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Motores de búsqueda")
        title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Motor predeterminado
        default_layout = QHBoxLayout()
        default_layout.addWidget(QLabel("Motor predeterminado:"))

        self.default_combo = QComboBox()
        for engine in self.search_manager.get_all_engines():
            self.default_combo.addItem(engine.name, engine.id)
        # Seleccionar motor actual
        current_engine = self.search_manager.get_default_engine()
        if current_engine:
            index = self.default_combo.findData(current_engine.id)
            if index >= 0:
                self.default_combo.setCurrentIndex(index)
        self.default_combo.currentIndexChanged.connect(self.on_default_changed)
        default_layout.addWidget(self.default_combo)
        default_layout.addStretch()

        layout.addLayout(default_layout)

        # Lista de motores disponibles
        layout.addWidget(QLabel("Motores disponibles:"))

        self.engines_list = QListWidget()
        for engine in self.search_manager.get_all_engines():
            item_text = f"{engine.name} - {engine.url_template}"
            self.engines_list.addItem(item_text)
        layout.addWidget(self.engines_list)

        # Información
        info_label = QLabel(
            "Puedes cambiar el motor predeterminado o usar el selector "
            "en la barra de búsqueda para búsquedas específicas."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; font-size: 11px; margin-top: 10px;")
        layout.addWidget(info_label)

        # Botones
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()

        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(close_btn)

        layout.addLayout(buttons_layout)
    def on_default_changed(self, index):
        """Cambiar motor predeterminado"""
        engine_id = self.default_combo.itemData(index)
        if engine_id:
            self.search_manager.set_default_engine(engine_id)
            QMessageBox.information(
                self,
                "Motor cambiado",
                f"Motor de búsqueda predeterminado cambiado a: {self.default_combo.currentText()}"
            )
