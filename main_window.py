from PySide6.QtWidgets import (
    QMainWindow,
    QToolBar,
    QPushButton,
    QLineEdit,
    QDockWidget,
    QMenu,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QSplitter,
    QFrame,
    QCheckBox,
    QTabWidget,
    QTextEdit,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QComboBox,
    QStackedWidget,
    QListWidget,
    QSizePolicy,
)
from PySide6.QtCore import (
    QEvent,
    QRect,
    QSettings,
    QSize,
    QThread,
    QTimer,
    QUrl,
    Qt,
    Signal,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtGui import QIcon, QPalette, QColor, QAction, QCursor, QMouseEvent
from PySide6.QtWebEngineWidgets import QWebEngineView
from tabs import TabManager
from navigation import NavigationManager
from history import HistoryManager, HistoryPanel
from devtools import DevToolsDock
from privacy import PrivacyManager
from favorites_bar import FavoritesBar
import socket
import sqlite3
import os
import subprocess
from contextlib import closing
from maintag import BookmarkManager

# ── Sistema jerárquico de carpetas de marcadores ──────────────────────────────
try:
    from folders_manager import FoldersManager, BookmarksMigration
    from bookmark_panel_ui import BookmarkPanelWidget, AddBookmarkDialog
    _FOLDERS_AVAILABLE = True
except ImportError as _e:
    _FOLDERS_AVAILABLE = False
    import logging as _logging
    _logging.getLogger(__name__).warning("Sistema de carpetas no disponible: %s", _e)
from password_manager import PasswordManager
from auth_manager import AuthManager
from auth_panel import LoginDialog, AuthPanel
from plugin_paths import find_plugin_dir, BUNDLED_PLUGINS_DIR
import time
import urllib.parse

# ============================================================================
# NUEVAS FUNCIONALIDADES UX/UI - Plan de Acción
# ============================================================================
from find_in_page import FindInPageBar, FindInPageManager
from modern_statusbar import ModernStatusBar, SslIndicatorButton
from download_panel import DownloadPanel
from screenshot_tool import ScreenshotTool, ScreenshotDialog
from profile_manager import ProfileManager, ProfileSwitcher
from network_interceptor import NetworkInterceptor, NetworkSettingsDialog
from userscript_manager import UserScriptManager, UserScriptDialog
from performance_monitor import PerformanceMonitor, PerformanceDiagnostic
from screenshot_advanced import RegionSelector, AnnotationEditor, ElementSelector
from session_manager import SessionManager
from search_engine_manager import (
    SearchEngineManager,
    SearchEngineButton,
    SearchEngineSettingsDialog,
)
from url_autocomplete import UrlAutocompleteSystem
from homepage_manager import HomepageManager, HomepageSettingsDialog

# Import modern styles adapter
try:
    from ui.core.modern_theme_styles import ModernStylesAdapter

    MODERN_STYLES_AVAILABLE = True
except ImportError:
    # Fallback al sistema antiguo
    try:
        from modern_styles import ThemeManager as ModernStylesAdapter

        MODERN_STYLES_AVAILABLE = True
    except ImportError:
        MODERN_STYLES_AVAILABLE = False

        # Dummy class
        class ModernStylesAdapter:
            def __init__(self, theme_name="light"):
                pass
            def get_tab_style(self):
                return ""
            def get_urlbar_style(self):
                return ""
            def get_navbar_style(self):
                return ""


# Import modern widgets
try:
    from ui.components.widgets import ExpandableUrlBar, CircularButton
except ImportError:
    # Fallback: usar widgets estándar
    from PySide6.QtWidgets import (
        QLineEdit as ExpandableUrlBar,
        QPushButton as CircularButton,
    )

    print("[WARNING] Using standard Qt widgets instead of modern widgets")

# Import theme system
try:
    from ui.core.theme_engine import (
        get_theme_engine as get_theme_manager,
        get_color,
        get_font,
        get_spacing,
        get_border,
    )
    from ui.core.strip_icons import (
        build_strip_icon,
        build_nav_icon,
        build_nav_action,
        refresh_action_icon,
        get_icon_color,
    )

    THEME_SYSTEM_AVAILABLE = True
    print("[OK] Theme engine loaded (new unified system)")
except ImportError:
    # Fallback al sistema antiguo
    try:
        from theme_manager import (
            get_theme_manager,
            get_color,
            get_font,
            get_spacing,
            get_border,
        )

        THEME_SYSTEM_AVAILABLE = True
        print("[OK] Theme system loaded (legacy)")

        # Funciones de iconos SVG no disponibles en el sistema legacy
        def build_strip_icon(resolved_path, color_hex, size):
            return QIcon(resolved_path)
        def build_nav_icon(name, color_hex=None, size=None, icons_dir=None):
            return QIcon(f"icons/{name}.svg")
        def build_nav_action(parent, name, tooltip, callback,
                             color_hex=None, size=None, icons_dir=None):
            from PySide6.QtGui import QAction as _QAction
            act = _QAction(QIcon(f"icons/{name}.svg"), tooltip, parent)
            if callback:
                act.triggered.connect(callback)
            return act
        def refresh_action_icon(action, color_hex, size=None):
            pass
        def get_icon_color(theme_name="dark"):
            return "#A0A0A0"
    except ImportError as e:
        THEME_SYSTEM_AVAILABLE = False
        print(f"[WARNING] Theme system not available: {e}")

        def build_strip_icon(resolved_path, color_hex, size):
            return QIcon(resolved_path)
        def build_nav_icon(name, color_hex=None, size=None, icons_dir=None):
            return QIcon(f"icons/{name}.svg")
        def build_nav_action(parent, name, tooltip, callback,
                             color_hex=None, size=None, icons_dir=None):
            from PySide6.QtGui import QAction as _QAction
            act = _QAction(QIcon(f"icons/{name}.svg"), tooltip, parent)
            if callback:
                act.triggered.connect(callback)
            return act
        def refresh_action_icon(action, color_hex, size=None):
            pass
        def get_icon_color(theme_name="dark"):
            return "#A0A0A0"
        # Create dummy functions for compatibility
        def get_theme_manager():
            return None
        def get_color(color_key, theme_name=None):
            return "#000000"
        def get_font(font_key, theme_name=None):
            return "10pt"
        def get_spacing(spacing_key, theme_name=None):
            return "4px"
        def get_border(border_key, theme_name=None):
            return "1px"

# ============================================================================
# LEGACY COMPATIBILITY: Dummy functions for plugins now loaded dynamically
# ============================================================================
# These functions exist only for backward compatibility with older code.
# All plugins are now loaded dynamically through UnifiedPluginManager.
# TODO: Remove these once all legacy references are updated.

print("[INFO] Plugins will be loaded dynamically through UnifiedPluginManager")

# Plugin availability flags
# These are set to False initially and will be set to True when plugins are loaded dynamically
SCRAPING_AVAILABLE = False
PROXY_AVAILABLE = False

# Import AI chat module
try:
    from chat_panel_safe import ChatPanelSafe as ChatPanel

    CHAT_AVAILABLE = True
    print("[OK] AI chat module loaded correctly")
except ImportError as e:
    CHAT_AVAILABLE = False
    print(f"Warning: AI chat module not available - {e}")

# Import Log Viewer panel
try:
    from log_viewer_panel import LogViewerPanel

    LOG_VIEWER_AVAILABLE = True
    print("[OK] Log viewer panel loaded")
except ImportError as e:
    LOG_VIEWER_AVAILABLE = False
    print(f"Warning: Log viewer not available - {e}")

# Import GenTab system (AI-First generative tabs, inspired by Google Disco)
try:
    from gentab_panel import GenTabPanel

    GENTAB_AVAILABLE = True
    print("[OK] GenTab system loaded correctly")
except ImportError as e:
    GENTAB_AVAILABLE = False
    print(f"Warning: GenTab system not available - {e}")

# Import AI Navigation system
try:
    from ai_context_engine import ContextVectorStore, ContentChunker, IndexWorker
    from session_intent_detector import SessionContextAnalyzer, SessionIntent
    from proactive_suggestion_engine import (
        ProactiveSuggestionEngine,
        SuggestionToast,
        SuggestionModel,
        SuggestionType,
    )
    from conversational_navbar import ConversationalNavBar

    AI_NAV_AVAILABLE = True
    print("[OK] AI Navigation system loaded correctly")
except ImportError as e:
    AI_NAV_AVAILABLE = False
    print(f"Warning: AI Navigation system not available - {e}")


# Import unified plugin system
try:
    from unified_plugin_manager import UnifiedPluginManager, PluginAccessLevel
    from unified_plugin_panel import UnifiedPluginPanel

    PLUGIN_SYSTEM_AVAILABLE = True
    print("[OK] Unified Plugin system loaded correctly")
except ImportError as e:
    PLUGIN_SYSTEM_AVAILABLE = False
    print(f"[WARNING] Unified Plugin system not available: {e}")

# Import authentication system
try:
    from auth_manager import AuthManager, AuthResult
    from auth_panel import AuthPanel
    from premium_decorators import PremiumMixin

    AUTH_SYSTEM_AVAILABLE = True
    print("[OK] Authentication system loaded correctly")
except ImportError as e:
    AUTH_SYSTEM_AVAILABLE = False
    print(f"Warning: Authentication system not available - {e}")

# Import Tor integration
try:
    from tor_manager import TorManager, TOR_AVAILABLE
    from tor_panel import TorPanel
except ImportError:
    TOR_AVAILABLE = False
    TorManager = None
    TorPanel = None


# Worker thread for asynchronous login
class LoginWorker(QThread):
    """Worker thread para ejecutar login de forma asíncrona sin bloquear la UI"""

    # Señales para comunicar resultados
    login_completed = Signal(object)  # Emite AuthResult

    def __init__(self, auth_manager, email, password):
        super().__init__()
        self.auth_manager = auth_manager
        self.email = email
        self.password = password
    def run(self):
        """Ejecutar login en un hilo separado"""
        try:
            print(
                f"[LoginWorker] Executing login for {self.email} in background thread..."
            )
            result = self.auth_manager.login(self.email, self.password)
            print(f"[LoginWorker] Login completed with success={result.success}")
            self.login_completed.emit(result)
        except Exception as e:
            print(f"[LoginWorker] Login error: {e}")
            # Crear un resultado de error
            from auth_manager import AuthError

            error_result = AuthResult(
                False, AuthError.NETWORK_ERROR, f"Error: {str(e)}"
            )
            self.login_completed.emit(error_result)


def _cursor_shape_for_resize_edges(edges: Qt.Edge) -> Qt.CursorShape:
    """Cursor de tamaño coherente con la combinación de bordes indicada."""
    le = Qt.Edge.LeftEdge
    ri = Qt.Edge.RightEdge
    top = Qt.Edge.TopEdge
    bot = Qt.Edge.BottomEdge
    diag_f = (le | top, ri | bot)
    diag_b = (ri | top, le | bot)
    if edges in diag_f:
        return Qt.CursorShape.SizeFDiagCursor
    if edges in diag_b:
        return Qt.CursorShape.SizeBDiagCursor
    if edges == le or edges == ri:
        return Qt.CursorShape.SizeHorCursor
    return Qt.CursorShape.SizeVerCursor


class _FrameResizeHandle(QWidget):
    """Zona sensible en el borde para iniciar resize vía compositor (`startSystemResize`)."""

    THICKNESS = 8

    def __init__(self, main_window: QMainWindow, edges: Qt.Edge) -> None:
        super().__init__(main_window)
        self._mw = main_window
        self._edges = edges
        self.setStyleSheet("background: transparent;")
        self.setCursor(QCursor(_cursor_shape_for_resize_edges(self._edges)))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — API Qt
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        wh = self._mw.windowHandle()
        if wh is None:
            super().mousePressEvent(event)
            return
        try:
            wh.startSystemResize(self._edges)
        except Exception:
            pass


class MainWindow(QMainWindow):
    # UI Constants
    BTN_BOX = 36  # button box - tamaño uniforme para todos los botones
    ICON_18 = QSize(14, 14)  # Tamaño estándar de icono
    FRAMELESS_MIN_W = 720
    FRAMELESS_MIN_H = 480

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Katphi")
        self.setGeometry(100, 100, 1200, 800)
        self.settings = QSettings("Katphi", "Settings")
        self._window_frameless = False

        # VENTANA NORMAL - Comportamiento completo del sistema operativo
        # Sin FramelessWindowHint para mantener TODA la funcionalidad:
        # - Redimensionable desde bordes/esquinas
        # - Snap to edges (arrastrar a laterales)
        # - Doble clic en barra para maximizar
        # - Todas las características modernas del SO

        # Configurar ventana sin bordes internos
        self.setContentsMargins(0, 0, 0, 0)

        # Worker thread para login asíncrono
        self.login_worker = None
        # Panel de temas (plugin) integrado en advanced_panel_stack (no ventana emergente)
        self.themes_panel_widget = None

        # Los estilos ahora se manejan completamente por el sistema de temas JSON
        # No se aplican estilos hardcodeados aquí

        # Inicializar componentes en el orden correcto
        self.history_manager = HistoryManager()
        self.bookmark_manager = BookmarkManager(self)

        # ── Migración + sistema de carpetas ──────────────────────────────────
        self.folders_manager = None
        self.bookmark_panel_widget = None
        if _FOLDERS_AVAILABLE:
            try:
                _migration = BookmarksMigration("bookmarks.db")
                _migration.migrate()
                self.folders_manager = FoldersManager("bookmarks.db")
            except Exception as _ex:
                import logging as _log
                _log.getLogger(__name__).error("Error iniciando FoldersManager: %s", _ex)
        self.password_manager = PasswordManager(self)
        self.navigation_manager = NavigationManager(self)
        self.tab_manager = TabManager(self.history_manager, self)
        self.navigation_manager.initialize_tab_manager(self.tab_manager)

        # ====================================================================
        # NUEVAS FUNCIONALIDADES UX/UI
        # ====================================================================

        # 1. Búsqueda en página
        self.find_bar = FindInPageBar(self)
        self.find_manager = FindInPageManager(self.find_bar, self.tab_manager)

        # 2. Status bar moderna con SSL (se configurará más adelante)
        self.status_bar = ModernStatusBar(self)

        # 3. Sistema de perfiles de usuario
        self.profile_manager = ProfileManager(self)
        print(
            f"[OK] Profile system initialized - Current profile: {self.profile_manager.current_profile_id}"
        )

        # 4. Network Interceptor para modificar peticiones HTTP
        self.network_interceptor = NetworkInterceptor(self)
        from config_manager import config
        self.network_interceptor.tor_mode = config.is_tor_enabled()
        print(
            f"[OK] Network interceptor initialized - UA: {self.network_interceptor.user_agent_type}"
        )

        # 4.1. Configurar User-Agent en el perfil global/predeterminado
        # Esto asegura que todas las pestañas usen el User-Agent correcto desde el inicio
        self._configure_default_profile_user_agent()

        # 5. UserScript Manager para scripts personalizados
        self.userscript_manager = UserScriptManager(self)
        scripts_count = len(self.userscript_manager.get_all_scripts())
        print(f"[OK] UserScript manager initialized - {scripts_count} scripts loaded")

        # 6. Modern Theme Manager para estilos visuales modernos
        self.modern_styles = ModernStylesAdapter("light")  # Tema por defecto: light
        print(f"[OK] Modern styles adapter initialized")

        # Initialize authentication system (SYNCHRONOUS - needed for plugins)
        self.auth_manager = None
        if AUTH_SYSTEM_AVAILABLE:
            try:
                self.auth_manager = AuthManager()
                print("[OK] Authentication system initialized")
            except Exception as e:
                print(f"[ERROR] Failed to initialize auth system: {e}")
        else:
            print("[WARNING] Authentication system not available")
        # Initialize GenTab panel early (needed by setup_side_strip before setup_dock_widgets)
        self.gentab_panel = None
        if GENTAB_AVAILABLE:
            try:
                self.gentab_panel = GenTabPanel(self)
                self.gentab_panel.gentab_created.connect(self._open_gentab_in_new_tab)
                print("[OK] GenTab panel initialized")
            except Exception as e:
                self.gentab_panel = None
                print(f"[ERROR] Failed to initialize GenTab panel: {e}")
        # Initialize Tor manager
        self.tor_manager = None
        if TOR_AVAILABLE:
            try:
                self.tor_manager = TorManager()
                print("[OK] Tor manager initialized")
            except Exception as e:
                self.tor_manager = None
                print(f"[ERROR] Failed to initialize Tor manager: {e}")
        # ====================================================================
        # AI NAVIGATION SYSTEM
        # ====================================================================
        self.ai_nav_enabled = False
        self.context_store = None
        self.session_analyzer = None
        self.suggestion_engine = None
        self._index_workers: list = []

        if AI_NAV_AVAILABLE:
            try:
                ai_disabled = QSettings("Katphi", "AINavigation").value(
                    "disabled",
                    False,
                    type=bool,
                )
                if not ai_disabled:
                    self.context_store = ContextVectorStore()
                    self.session_analyzer = SessionContextAnalyzer(self)
                    self.suggestion_engine = ProactiveSuggestionEngine(self)
                    self.ai_nav_enabled = True
                    print("[OK] AI Navigation system initialized")
                else:
                    print("[INFO] AI Navigation system disabled by user")
            except Exception as e:
                print(f"[WARNING] AI Navigation init failed (graceful): {e}")
        # Initialize unified plugin system (needs auth_manager)
        self.plugin_manager = None
        self.dynamic_plugin_actions = {}  # Para guardar acciones de plugins dinámicos
        self.dynamic_plugin_panels = {}  # Para guardar paneles de plugins dinámicos

        if PLUGIN_SYSTEM_AVAILABLE and self.auth_manager:
            try:
                self.plugin_manager = UnifiedPluginManager(
                    auth_manager=self.auth_manager, parent=self
                )

                # Conectar señales para carga dinámica de plugins
                self.plugin_manager.plugin_loaded.connect(self.on_plugin_loaded)
                self.plugin_manager.plugin_unloaded.connect(self.on_plugin_unloaded)

                # Resincronizar plugins con el usuario actual ante CUALQUIER
                # cambio de sesión o de licencia (no solo en el diálogo de
                # logout). Evita que una sesión herede plugins de la anterior.
                try:
                    self.auth_manager.logout_successful.connect(
                        self.resync_plugins_to_current_user
                    )
                    self.auth_manager.login_successful.connect(
                        self.resync_plugins_to_current_user
                    )
                    self.auth_manager.auth_state_changed.connect(
                        self.resync_plugins_to_current_user
                    )
                    self.auth_manager.plugin_license_changed.connect(
                        self.resync_plugins_to_current_user
                    )
                    print("[OK] Plugin resync conectado a señales de auth")
                except Exception as _sig_e:
                    print(f"[WARNING] No se pudieron conectar señales de auth para resync: {_sig_e}")

                print("[OK] Unified Plugin system initialized with auth")

                # Cargar plugins gratuitos inmediatamente (sin necesidad de autenticación)
                QTimer.singleShot(1000, self._load_free_plugins)
            except Exception as e:
                print(f"[ERROR] Failed to initialize plugin system: {e}")
        else:
            print("[WARNING] Plugin system not available or auth_manager missing")
        # Search Engine Manager (ANTES de crear la barra de navegación)
        try:
            self.search_engine_manager = SearchEngineManager(self)
            print("[OK] Search Engine Manager initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize Search Engine Manager: {e}")
            self.search_engine_manager = None
        # Homepage Manager (DESPUÉS del SearchEngineManager)
        try:
            self.homepage_manager = HomepageManager(self)
            print("[OK] Homepage Manager initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize Homepage Manager: {e}")
            self.homepage_manager = None
        # Crear la barra de navegación después de tener navigation_manager
        self.nav_bar = QToolBar("Navigation")
        self.setup_nav_bar()

        # Crear contenedor principal con QVBoxLayout para nav_bar y contenido
        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Sin márgenes gruesos
        main_layout.setSpacing(0)  # Sin espaciado
        self.main_layout = main_layout

        # ── Distribución estilo Firefox (de arriba a abajo) ───────────────────
        #   Fila 1: tira de pestañas  (barra reparentada desde el QTabWidget)
        #   Fila 2: barra de navegación (botones + barra de direcciones)
        #   Fila 3: barra de marcadores/favoritos (se inserta en setup_dock_widgets)
        # El contenido web va debajo, dentro del content_splitter.

        # Contenedor de la tira de pestañas (fila superior)
        self.tab_strip_container = QWidget()
        self.tab_strip_container.setObjectName("tabStripContainer")
        # Altura fija a su contenido: evita que el contenedor absorba espacio
        # sobrante y deje la barra de pestañas flotando con huecos.
        self.tab_strip_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        tab_strip_layout = QHBoxLayout(self.tab_strip_container)
        tab_strip_layout.setContentsMargins(0, 0, 0, 0)
        tab_strip_layout.setSpacing(0)

        # Reparentar la barra de pestañas del QTabWidget a la fila superior.
        # El QTabWidget conserva el contenido (vistas web) dentro del
        # content_splitter; DetachedTabWidget elimina el hueco que quedaría.
        _tab_bar = self.tab_manager.tabs.tabBar()
        # objectName propio: al reparentar la barra fuera del QTabWidget, los
        # selectores "#browserTabs QTabBar" dejan de alcanzarla (ya no es
        # descendiente). Con un id propio los temas la estilizan esté donde esté.
        _tab_bar.setObjectName("browserTabBar")
        _tab_bar.setExpanding(False)  # pestañas compactas alineadas a la izquierda
        # Estilo base (no temático) directo sobre la barra como fallback.
        try:
            _tab_bar.setStyleSheet(self.modern_styles.get_tab_style())
        except Exception:
            pass
        tab_strip_layout.addWidget(_tab_bar, 1)
        if hasattr(self.tab_manager.tabs, "set_bar_detached"):
            self.tab_manager.tabs.set_bar_detached(True)

        # Controles de ventana (min/max/cerrar) a la derecha de la tira de
        # pestañas — ubicación estilo Firefox. Solo visibles en modo sin marco
        # (su visibilidad la gobierna _sync_window_chrome_visibility_from_flags).
        if hasattr(self, "_window_chrome_container") and self._window_chrome_container:
            tab_strip_layout.addWidget(self._window_chrome_container, 0)

        main_layout.addWidget(self.tab_strip_container)  # Fila 1: pestañas
        main_layout.addWidget(self.nav_bar)              # Fila 2: navegación
        main_layout.addWidget(self.find_bar)  # Barra de búsqueda (inicialmente oculta)

        # Crear splitter horizontal REDIMENSIONABLE pero con barra lateral fija
        content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter = content_splitter
        content_splitter.setChildrenCollapsible(
            False
        )  # No permitir colapsar completamente
        # Eliminar el handle visible del splitter para el sidebar
        content_splitter.setHandleWidth(0)
        content_splitter.setStyleSheet("""
            QSplitter::handle {
                background: transparent;
                border: none;
            }
        """)

        # Crear contenedor para la barra lateral IZQUIERDA (NO redimensionable)
        self.sidebar_container = QWidget()
        self.sidebar_container.setFixedWidth(
            36
        )  # Ancho reducido para iconos más pequeños
        # Eliminar borde del sidebar
        self.sidebar_container.setStyleSheet("""
            QWidget {
                border: none;
                background: transparent;
            }
        """)
        sidebar_layout = QVBoxLayout(self.sidebar_container)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Configurar barra lateral vertical FIJA
        self.side_strip = QToolBar()
        self.side_strip.setObjectName("sideStrip")
        self.side_strip.setOrientation(Qt.Vertical)
        self.side_strip.setMovable(False)
        self.side_strip.setFixedWidth(36)  # Ancho reducido para iconos más pequeños
        self.side_strip.setFloatable(False)
        self.setup_side_strip()
        sidebar_layout.addWidget(self.side_strip)

        # Agregar sidebar a la IZQUIERDA primero
        content_splitter.addWidget(self.sidebar_container)

        # Configurar stacked widget para paneles avanzados (inicialmente oculto)
        self.advanced_panel_stack = QStackedWidget()
        self.advanced_panel_stack.setMinimumWidth(0)
        self.advanced_panel_stack.setMaximumWidth(0)  # oculto por defecto
        self.advanced_panel_stack.hide()
        content_splitter.addWidget(self.advanced_panel_stack)

        # Botón de cierre para paneles avanzados (se reubica por panel activo)
        self.close_panel_btn = QPushButton("X", self.advanced_panel_stack)
        self.close_panel_btn.setToolTip("Cerrar panel")
        self.close_panel_btn.setFixedSize(24, 24)
        self.close_panel_btn.clicked.connect(self.hide_advanced_panel)
        self.close_panel_btn.setStyleSheet(
            """
            QPushButton {
                border: 1px solid rgba(150, 150, 150, 0.25);
                border-radius: 12px;
                background-color: rgba(0, 0, 0, 0.22);
                color: #f0f0f0;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(220, 50, 50, 0.85);
                border-color: rgba(220, 50, 50, 1);
            }
            """
        )
        self.close_panel_btn.hide()
        content_splitter.splitterMoved.connect(
            lambda *_: self._position_panel_close_button()
        )

        # Agregar pestañas (se expande)
        content_splitter.addWidget(self.tab_manager.tabs)

        # Aplicar estilo trapezoidal moderno a las pestañas
        tab_style = self.modern_styles.get_tab_style()
        self.tab_manager.tabs.setStyleSheet(tab_style)
        self.tab_manager.tabs.setDocumentMode(True)  # Pestañas integradas
        self.tab_manager.tabs.setTabsClosable(True)  # Botón X en pestañas
        self.tab_manager.tabs.setMovable(True)  # Pestañas movibles

        # Configurar proporciones: sidebar fija, panel redimensionable, pestañas expandibles
        content_splitter.setStretchFactor(0, 0)  # Sidebar FIJA (no redimensionable)
        content_splitter.setStretchFactor(1, 0)  # Panel tamaño específico
        content_splitter.setStretchFactor(2, 1)  # Pestañas se expanden

        main_layout.addWidget(content_splitter)
        self.setCentralWidget(main_container)

        # Status bar oculta — el SSL se muestra en la navbar (SslIndicatorButton)
        self.setStatusBar(self.status_bar)
        self.status_bar.hide()

        # Configurar paneles dock
        self.setup_dock_widgets()

        # Configurar tema y atajos
        self.setup_theme()
        self.setup_shortcuts()

        # Garantía final: si por cualquier motivo faltaron botones de asistentes, los reinyectamos
        self._ensure_chat_button_visible()
        self._ensure_navigation_assistant_button_visible()

        # Initialize authentication UI state first
        self.update_auth_ui()

        # Restore session or Tor pending URLs
        session_restored = False
        from config_manager import config
        pending_urls = config.get_tor_pending_urls()
        if pending_urls:
            # Prioridad: URLs guardadas antes del reinicio Tor
            for url in pending_urls:
                if url and url not in ("about:blank", ""):
                    self.tab_manager.add_new_tab(url)
            config.clear_tor_pending_urls()
            config.persist_config()
            session_restored = True
            print(f"[TOR] Restored {len(pending_urls)} tabs after reinicio")
        elif self.auth_manager and self.auth_manager.auth_state.is_authenticated:
            print("[AUTH] User is authenticated, restoring session...")
            session_restored = self.tab_manager.restaurar_sesion()
        else:
            print("[AUTH] User not authenticated, skipping session restoration")
        # Configure application close event
        self.closeEvent = self.on_close

        # Ensure at least one tab is active at startup (only if session wasn't restored or no tabs exist)
        if not session_restored or self.tab_manager.tabs.count() == 0:
            print("Creating initial tab...")
            self.tab_manager.add_new_tab()
        # Conectar señales de cambio de pestaña al status bar
        self.tab_manager.tabs.currentChanged.connect(self._connect_browser_to_statusbar)

        # Conectar el browser actual al status bar
        self._connect_browser_to_statusbar()

        # ── AI Navigation: toast de sugerencias + hooks de pestañas ──
        self.suggestion_toast = None
        if self.ai_nav_enabled and AI_NAV_AVAILABLE:
            try:
                self.suggestion_toast = SuggestionToast(self)
                self.suggestion_toast.action_clicked.connect(
                    self._on_suggestion_accepted
                )
                self.suggestion_toast.dismissed.connect(self._on_suggestion_dismissed)

                self.tab_manager.tabs.currentChanged.connect(self._ai_on_tab_changed)

                self._ai_analysis_timer = QTimer(self)
                self._ai_analysis_timer.setSingleShot(True)
                self._ai_analysis_timer.setInterval(5000)
                self._ai_analysis_timer.timeout.connect(self._ai_run_analysis)

                print("[OK] AI Navigation hooks connected")
            except Exception as e:
                print(f"[WARNING] AI Navigation hooks failed: {e}")
        # Asegurar que el botón de favoritos de la barra de navegación tenga su objectName para estilos
        try:
            if hasattr(self, "favorite_nav_action"):
                fav_btn = self.nav_bar.widgetForAction(self.favorite_nav_action)
                if fav_btn:
                    fav_btn.setObjectName("favoriteNavButton")
        except Exception:
            pass

        # Modo ventana sin marco (persistente): establecer antes del primer show
        if self.settings.value("ui/frameless_window", False, type=bool):
            self.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            )
            self._window_frameless = True
        self._sync_window_chrome_visibility_from_flags()

        self.showMaximized()
    def setup_dock_widgets(self):
        # Configurar DevTools
        self.devtools_dock = DevToolsDock(self)
        self.devtools_dock.setAllowedAreas(
            Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.devtools_dock)
        self.devtools_dock.hide()

        # Configurar Bookmark Manager (panel clásico — mantenido por compatibilidad)
        self.bookmark_dock = QDockWidget("Gestor de Marcadores", self)
        self.bookmark_dock.setWidget(self.bookmark_manager)
        self.bookmark_dock.setAllowedAreas(
            Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.bookmark_dock)
        self.bookmark_dock.hide()

        # ── Nuevo panel de carpetas jerárquicas ───────────────────────────────
        if _FOLDERS_AVAILABLE and self.folders_manager:
            # parent=None es obligatorio: si se pone self (MainWindow) Qt
            # renderiza el widget como hijo flotante en posición (0,0),
            # superponiéndose a los botones de navegación. show_advanced_panel
            # lo reparenta al stack cuando se necesita mostrar.
            self.bookmark_panel_widget = BookmarkPanelWidget(
                bookmark_manager=self.bookmark_manager,
                folders_manager=self.folders_manager,
                parent=None,
            )
            self.bookmark_panel_widget.bookmark_opened.connect(self.load_url)
            self.bookmark_panel_widget.new_tab_requested.connect(
                lambda url: self.tab_manager.add_new_tab(url)
                if hasattr(self, "tab_manager") else None
            )
            self.bookmark_panel_widget.data_changed.connect(self._on_bookmarks_data_changed)
        # Configurar Barra de Favoritos (fila 3, debajo de la navegación — estilo Firefox)
        self.favorites_bar = FavoritesBar(self)
        self.favorites_bar.setMovable(False)
        self.favorites_bar.setFloatable(False)
        try:
            _fav_idx = self.main_layout.indexOf(self.content_splitter)
            if _fav_idx < 0:
                _fav_idx = self.main_layout.count()
            self.main_layout.insertWidget(_fav_idx, self.favorites_bar)
        except Exception as _fav_ex:
            import logging as _l
            _l.getLogger(__name__).warning(
                "No se pudo insertar favorites_bar en el layout, usando toolbar: %s",
                _fav_ex,
            )
            self.favorites_bar.setAllowedAreas(
                Qt.TopToolBarArea | Qt.BottomToolBarArea
            )
            self.addToolBar(Qt.TopToolBarArea, self.favorites_bar)
        self.favorites_bar.hide()  # Inicialmente oculta
        # Conectar señal de clic en favorito
        self.favorites_bar.favorite_clicked.connect(self.load_url)

        # Conexión de pestaña para estrella no implementada

        # Configurar Privacy Manager
        self.privacy_manager = PrivacyManager(self)
        self.privacy_dock = QDockWidget("Privacy Settings", self)
        self.privacy_dock.setWidget(self.privacy_manager)
        self.privacy_dock.setAllowedAreas(
            Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.privacy_dock)
        self.privacy_dock.hide()

        # Conectar señal para aplicar cambios al vuelo
        self.privacy_manager.settings_changed.connect(self.reapply_privacy_to_all_tabs)

        try:
            self.privacy_manager.sync_default_webengine_profile()
        except Exception as _sync_ex:
            print(f"[WARNING] sync_default_webengine_profile: {_sync_ex}")

        # Configurar Password Manager
        self.password_dock = QDockWidget("Password Manager", self)
        self.password_dock.setWidget(self.password_manager)
        self.password_dock.setAllowedAreas(
            Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.password_dock)
        self.password_dock.hide()

        # Configurar Download Panel (NUEVA FUNCIONALIDAD)
        self.download_panel = DownloadPanel(self)
        self.download_dock = QDockWidget("Descargas", self)
        self.download_dock.setWidget(self.download_panel)
        self.download_dock.setAllowedAreas(
            Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.download_dock)
        self.download_dock.hide()

        # Configurar Tor Panel: SIEMPRE crear para que el usuario pueda ver instrucciones
        self.tor_panel = None
        if TorPanel is not None:
            try:
                self.tor_panel = TorPanel(self.tor_manager, self)
                if self.tor_manager:
                    self.tor_panel.set_restart_callback(
                        lambda enabled: self._restart_with_tor(enabled)
                    )
                if self.advanced_panel_stack.indexOf(self.tor_panel) < 0:
                    self.advanced_panel_stack.addWidget(self.tor_panel)
                print("[OK] Tor panel configured correctly")
            except Exception as e:
                self.tor_panel = None
                print(f"[ERROR] Failed to configure Tor panel: {e}")
        # Configurar Scraping Panel (si está disponible)
        if SCRAPING_AVAILABLE:
            self.scraping_integration = scraping_integration
            self.scraping_panel = ScrapingPanel(
                self.scraping_integration,
                plugin_validator=self.plugin_manager,
            )
            self.scraping_dock = QDockWidget("Scrapelillo Completo", self)
            self.scraping_dock.setWidget(self.scraping_panel)
            self.scraping_dock.setAllowedAreas(
                Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
            )
            self.addDockWidget(Qt.RightDockWidgetArea, self.scraping_dock)
            self.scraping_dock.hide()
            # Inicialmente deshabilitado hasta que el usuario se autentique
            self.scraping_panel.setEnabled(False)
            print("[OK] Scraping panel configured correctly")
        else:
            self.scraping_integration = None
            self.scraping_panel = None
            self.scraping_dock = None
            print("[INFO] Plugin Scraping no instalado")
        # Configurar Proxy Panel (si está disponible)
        if PROXY_AVAILABLE:
            # Obtener el proxy manager del scraping integration si está disponible
            proxy_manager = None
            if SCRAPING_AVAILABLE and hasattr(scraping_integration, "proxy_manager"):
                proxy_manager = scraping_integration.proxy_manager
            self.proxy_panel = ProxyPanel(proxy_manager, plugin_validator=self.plugin_manager)
            self.proxy_dock = QDockWidget("Proxy Management", self)
            self.proxy_dock.setWidget(self.proxy_panel)
            self.proxy_dock.setAllowedAreas(
                Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
            )
            self.addDockWidget(Qt.RightDockWidgetArea, self.proxy_dock)
            self.proxy_dock.hide()
            # Inicialmente deshabilitado hasta que el usuario se autentique
            self.proxy_panel.setEnabled(False)
            print("[OK] Proxy management panel configured correctly")
        else:
            self.proxy_panel = None
            self.proxy_dock = None
            print("[INFO] Plugin Proxy no instalado")
        # Configurar Chat Panel (si está disponible)
        if CHAT_AVAILABLE:
            self.chat_panel = ChatPanel()
            # Conectar señal de GenTab desde el chat
            if hasattr(self.chat_panel, "gentab_requested"):
                self.chat_panel.gentab_requested.connect(self._on_gentab_from_navbar)
            self.chat_dock = QDockWidget("Chat con IA", self)
            self.chat_dock.setWidget(self.chat_panel)
            self.chat_dock.setAllowedAreas(
                Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
            )
            self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
            self.chat_dock.hide()
            print("[OK] AI chat panel configured correctly (with AI Navigation)")
        else:
            self.chat_panel = None
            self.chat_dock = None
            print("[ERROR] AI chat panel not available")
        # Log Viewer Panel
        if LOG_VIEWER_AVAILABLE:
            self.log_viewer_panel = LogViewerPanel()
            print("[OK] Log viewer panel initialized")
        else:
            self.log_viewer_panel = None
        # GenTab Panel ya inicializado en __init__ (antes de setup_side_strip)

        # Configurar Tab Groups Panel
        try:
            from tab_groups_ui import TabGroupsPanel

            self.tab_groups_panel = TabGroupsPanel(
                group_manager=self.tab_manager.group_manager,
                tab_manager=self.tab_manager,
            )
            self.tab_groups_dock = QDockWidget("Tab Groups", self)
            self.tab_groups_dock.setWidget(self.tab_groups_panel)
            self.tab_groups_dock.setAllowedAreas(
                Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
            )
            self.addDockWidget(Qt.RightDockWidgetArea, self.tab_groups_dock)
            self.tab_groups_dock.hide()
            print("[OK] Tab Groups panel configured correctly")
        except Exception as e:
            self.tab_groups_panel = None
            self.tab_groups_dock = None
            print(f"[ERROR] Tab Groups panel not available: {e}")
        # SEO Analyzer Plugin - NOW LOADED DYNAMICALLY through UnifiedPluginManager
        # (Removed static initialization)

        # Configurar Unified Plugin Panel (usa plugin_manager ya inicializado)
        self.unified_plugin_panel = None
        self.plugin_store_dock = None

        if PLUGIN_SYSTEM_AVAILABLE and self.plugin_manager:
            try:
                # Crear el panel unificado de plugins usando el manager ya inicializado
                self.unified_plugin_panel = UnifiedPluginPanel(self.plugin_manager)
                self.plugin_store_dock = QDockWidget("Plugin Store", self)
                self.plugin_store_dock.setWidget(self.unified_plugin_panel)
                self.plugin_store_dock.setAllowedAreas(
                    Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
                )
                self.addDockWidget(Qt.RightDockWidgetArea, self.plugin_store_dock)
                self.plugin_store_dock.hide()
                print("[OK] Unified plugin panel configured correctly")
            except Exception as e:
                self.unified_plugin_panel = None
                self.plugin_store_dock = None
                print(f"[ERROR] Failed to configure plugin panel: {e}")
        else:
            print(
                "[WARNING] Plugin panel not configured (system not available or auth_manager missing)"
            )
        # Configurar Auth Panel (si está disponible) - diferido
        self.auth_panel = None
        self.auth_dock = None
        if AUTH_SYSTEM_AVAILABLE:
            # Delay auth panel creation until auth_manager is ready
            QTimer.singleShot(1500, self._setup_auth_panel)
            print("[OK] Authentication panel will be configured")
        else:
            print("[ERROR] Authentication panel not available")
    def setup_theme(self):
        # Cargar configuración de tema (Settings ya existe desde __init__)
        if getattr(self, "settings", None) is None:
            self.settings = QSettings("Katphi", "Settings")

        # Configurar sistema de temas modular
        self._setup_theme_system()

        if THEME_SYSTEM_AVAILABLE:
            tm = get_theme_manager()
            if tm:
                tm.theme_changed.connect(self._refresh_side_strip_icons)
                tm.theme_changed.connect(lambda _: self.refresh_all_nav_icons())
                tm.theme_changed.connect(self._refresh_side_strip_style)
                tm.theme_changed.connect(self._refresh_navbar_style)
                tm.theme_changed.connect(self._refresh_tab_bar_style)
                tm.theme_changed.connect(self._refresh_url_bar_style)
                # Sin esta conexión, el QToolTip global se queda con el estilo
                # del arranque cuando el tema se cambia desde el plugin de Temas
                # (que llama a theme_engine.apply_theme() directamente, sin pasar
                # por MainWindow.apply_theme()).
                tm.theme_changed.connect(lambda _: self._apply_tooltip_theme())
                # Por si el tema ya estaba aplicado antes de crear la barra lateral
                QTimer.singleShot(0, self._refresh_side_strip_icons)
                QTimer.singleShot(100, self.refresh_all_nav_icons)
                QTimer.singleShot(120, self._refresh_side_strip_style)
                QTimer.singleShot(140, self._refresh_tab_bar_style)
                QTimer.singleShot(150, self._refresh_url_bar_style)
        # Aplicar estilo inicial al navbar siempre (con o sin ThemeEngine)
        QTimer.singleShot(130, self._refresh_navbar_style)
    def setup_shortcuts(self):
        """Configurar atajos de teclado globales"""
        from PySide6.QtGui import QShortcut, QKeySequence

        # Nueva pestaña
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(
            lambda: self.tab_manager.add_new_tab()
        )

        # Reabrir pestaña cerrada
        QShortcut(QKeySequence("Ctrl+Shift+T"), self).activated.connect(
            self.tab_manager.reopen_closed_tab
        )

        # Nueva ventana
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.open_new_window)

        # Ventana privada
        QShortcut(QKeySequence("Ctrl+Shift+P"), self).activated.connect(
            self.open_private_window
        )

        # Imprimir
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self.print_page)

        # Guardar como
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save_page_as)

        # Buscar en página (nueva funcionalidad mejorada)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self.find_manager.activate_find
        )

        # Panel de descargas (Ctrl+J)
        QShortcut(QKeySequence("Ctrl+J"), self).activated.connect(
            self.toggle_download_panel
        )

        # Captura de pantalla (Ctrl+Shift+S)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(
            self.take_screenshot
        )

        # Zoom
        QShortcut(QKeySequence("Ctrl++"), self).activated.connect(self.zoom_in)
        QShortcut(QKeySequence("Ctrl+="), self).activated.connect(
            self.zoom_in
        )  # Alternativo sin Shift
        QShortcut(QKeySequence("Ctrl+-"), self).activated.connect(self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(self.zoom_reset)

        # Pantalla completa
        QShortcut(QKeySequence("F11"), self).activated.connect(self.toggle_fullscreen)

        # GenTab (Ctrl+G)
        QShortcut(QKeySequence("Ctrl+G"), self).activated.connect(
            self.toggle_gentab_panel
        )

        # DevTools
        QShortcut(QKeySequence("F12"), self).activated.connect(self.toggle_dev_tools)

        # Ver código fuente
        QShortcut(QKeySequence("Ctrl+U"), self).activated.connect(self.view_page_source)

        # Cerrar
        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self.close)

        # Descargas
        QShortcut(QKeySequence("Ctrl+Shift+Y"), self).activated.connect(
            self.show_downloads
        )

        # Extensiones
        QShortcut(QKeySequence("Ctrl+Shift+A"), self).activated.connect(
            self.show_plugins_panel
        )

        print("[OK] Atajos de teclado configurados")
    def _ensure_chat_button_visible(self):
        """Garantiza que el botón de Chat IA esté presente en la barra lateral."""
        try:
            if not hasattr(self, "side_strip") or not self.side_strip:
                return
            # Si ya existe, no duplicar
            if (
                hasattr(self, "chat_action")
                and self.chat_action
                and self.chat_action in self.side_strip.actions()
            ):
                return
            icon = QIcon("icons/chat.svg")
            if icon.isNull():
                icon = QIcon("icons/sidebar.svg")
            self.chat_action = QAction(icon, "Chat IA", self)
            self.chat_action.triggered.connect(self.toggle_chat_panel)
            self.side_strip.addAction(self.chat_action)
            print("[UI] Chat IA button re-injected into sidebar")
        except Exception as e:
            print(f"[UI] Error ensuring Chat IA button visibility: {e}")
    def _ensure_navigation_assistant_button_visible(self):
        """El asistente de navegación está integrado en el chat — no se añade botón separado."""
        pass
    def on_close(self, event):
        """Handle browser close event"""
        try:
            # AI Navigation cleanup
            if self.ai_nav_enabled:
                for w in self._index_workers:
                    if w.isRunning():
                        w.quit()
                        w.wait(1000)
                if self.suggestion_engine:
                    self.suggestion_engine.reset_session()
                print("[AI] Navigation system cleaned up")
            # UnifiedPluginManager no requiere shutdown explícito
            if PLUGIN_SYSTEM_AVAILABLE and self.plugin_manager:
                print("[Browser] Unified Plugin Manager cleanup...")
                # shutdown_all_plugins() no existe en UnifiedPluginManager
                # La limpieza se hace automáticamente en el destructor
            # Session Manager - guardar para recuperación de crash
            if hasattr(self, "session_manager") and self.session_manager:
                print("[Browser] Saving session for crash recovery...")
                self.session_manager.on_browser_close()
            # Save session only if user is authenticated
            if hasattr(self, "tab_manager"):
                if self.auth_manager and self.auth_manager.auth_state.is_authenticated:
                    print("[AUTH] User is authenticated, saving session...")
                    self.tab_manager.guardar_sesion()
                else:
                    print("[AUTH] User not authenticated, clearing session...")
                    self.tab_manager.limpiar_sesion()
            event.accept()
        except Exception as e:
            print(f"[Browser] Error during shutdown: {e}")
            event.accept()
    def resizeEvent(self, event):
        """
        Manejar el redimensionamiento de la ventana para ocultar/mostrar elementos
        de la barra de navegación según el espacio disponible.
        """
        super().resizeEvent(event)
        # Mantener el hueco de la barra de pestañas para los controles de ventana
        self._sync_tab_strip_widths()
        # Reposicionar botón X global de cierre de panel
        if hasattr(self, "close_panel_btn") and self.close_panel_btn and self.close_panel_btn.isVisible():
            self._position_panel_close_button()
        # Obtener ancho actual de la ventana
        window_width = self.width()

        # Definir umbrales de ancho
        WIDTH_FULL = 1200  # Ancho completo - todos los elementos visibles
        WIDTH_MEDIUM = 950  # Ancho medio - ocultar tab_search
        WIDTH_SMALL = 750  # Ancho pequeño - ocultar más elementos
        WIDTH_MINIMAL = 600  # Ancho mínimo - solo esenciales

        try:
            # Gestión responsive de elementos secundarios
            if window_width >= WIDTH_FULL:
                # ANCHO COMPLETO: Mostrar todo
                if hasattr(self, "tab_search"):
                    self.tab_search.show()
                if hasattr(self, "url_separator"):
                    self.url_separator.show()
                if hasattr(self, "search_engine_button"):
                    self.search_engine_button.show()
            elif window_width >= WIDTH_MEDIUM:
                # ANCHO MEDIO: Ocultar tab_search
                if hasattr(self, "tab_search"):
                    self.tab_search.hide()
                if hasattr(self, "url_separator"):
                    self.url_separator.hide()
                if hasattr(self, "search_engine_button"):
                    self.search_engine_button.show()
            elif window_width >= WIDTH_SMALL:
                # ANCHO PEQUEÑO: Ocultar tab_search
                if hasattr(self, "tab_search"):
                    self.tab_search.hide()
                if hasattr(self, "url_separator"):
                    self.url_separator.hide()
                if hasattr(self, "search_engine_button"):
                    self.search_engine_button.show()
            else:
                # ANCHO MÍNIMO: Solo esenciales (URL bar, menú, login)
                if hasattr(self, "tab_search"):
                    self.tab_search.hide()
                if hasattr(self, "url_separator"):
                    self.url_separator.hide()
                if hasattr(self, "profile_switcher"):
                    self.profile_switcher.hide()
                if hasattr(self, "search_engine_button"):
                    self.search_engine_button.hide()
        except Exception as e:
            print(f"[UI] Error in resizeEvent: {e}")
        try:
            self._layout_frameless_resize_handles()
        except Exception as e_layout:
            print(f"[UI] Frameless resize layout: {e_layout}")
    def setup_nav_bar(self):
        # Configurar toolbar moderno con constantes uniformes
        self.nav_bar.setIconSize(self.ICON_18)
        self.nav_bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.nav_bar.setObjectName("navigationBar")

        # IMPORTANTE: Evitar que el toolbar se envuelva (wrap) a múltiples líneas
        self.nav_bar.setMovable(False)
        self.nav_bar.setFloatable(False)

        # El estilo del navbar se aplica vía _refresh_navbar_style()
        # que lee los colores navbar_button_* del ThemeEngine activo.
        # Se llama al final de setup_dock_widgets() tras conectar las señales.

        # ── Construir iconos SVG temáticos ────────────────────────────────────
        _nav_color = self._get_nav_icon_color()

        def _nav_action(icon_name: str, tooltip: str, callback) -> "QAction":
            """Crea QAction con SVG temático y almacena la ruta del icono."""
            try:
                from ui.core.strip_icons import build_nav_action as _bna
                act = _bna(self, icon_name, tooltip, callback,
                           color_hex=_nav_color, size=self.ICON_18)
            except Exception:
                act = QAction(QIcon(f"icons/{icon_name}.svg"), tooltip, self)
                if callback:
                    act.triggered.connect(callback)
            return act
        # Toggle Sidebar
        self.sidebar_visible = True
        self.toggle_sidebar_action = _nav_action(
            "sidebar", "Ocultar/Mostrar Panel Lateral", self.toggle_sidebar
        )
        self.nav_bar.addAction(self.toggle_sidebar_action)

        # Back
        self.back_action = _nav_action(
            "back", "Atrás (Alt+←)", self.navigation_manager.navigate_back
        )
        self.nav_bar.addAction(self.back_action)

        # Forward
        self.forward_action = _nav_action(
            "forward", "Adelante (Alt+→)", self.navigation_manager.navigate_forward
        )
        self.nav_bar.addAction(self.forward_action)

        # Refresh
        self.refresh_action_nav = _nav_action(
            "refresh", "Recargar (F5)", self.navigation_manager.refresh_page
        )
        self.nav_bar.addAction(self.refresh_action_nav)

        # History
        self.history_action_nav = _nav_action(
            "history", "Historial",
            lambda: self.history_manager.show_history(self.tab_manager)
        )
        self.nav_bar.addAction(self.history_action_nav)

        # Guardar referencias para el refresco de tema
        self._nav_icon_actions = [
            self.toggle_sidebar_action,
            self.back_action,
            self.forward_action,
            self.refresh_action_nav,
            self.history_action_nav,
        ]

        # ── Botón Nueva Pestaña en la esquina derecha de la barra de pestañas ──
        # (Se inicializa con QTimer para asegurar que el tab widget esté listo)
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, self._connect_tabbar_newtab_icon)

        # Search Engine Button (antes de la URL bar)
        if hasattr(self, "search_engine_manager") and self.search_engine_manager:
            self.search_engine_button = SearchEngineButton(
                self.search_engine_manager, self
            )
            self.search_engine_button.engine_selected.connect(
                self.on_search_engine_selected
            )
            self.nav_bar.addWidget(self.search_engine_button)
            self.selected_search_engine = None  # Para búsquedas temporales
        # URL Bar — usa ConversationalNavBar si el sistema AI está activo
        if self.ai_nav_enabled and AI_NAV_AVAILABLE:
            self.url_bar = ConversationalNavBar()
            self.url_bar.navigation_requested.connect(self.load_url)
            self.url_bar.search_requested.connect(self.load_url)
            self.url_bar.ai_query_requested.connect(self._on_ai_query)
            self.url_bar.gentab_requested.connect(self._on_gentab_from_navbar)
            print("[OK] Conversational NavBar active")
        else:
            self.url_bar = ExpandableUrlBar()
            self.url_bar.setPlaceholderText("Buscar o escribir URL...")
        self.url_bar.setObjectName("urlBar")
        self.url_bar.returnPressed.connect(lambda: self.load_url(self.url_bar.text()))
        self.url_bar.setFixedHeight(36)
        self.url_bar.setMinimumWidth(250)
        self.url_bar.setMaximumWidth(600)

        # El estilo del url_bar lo aplica _refresh_url_bar_style() via theme_changed
        if hasattr(self.url_bar, "setClearButtonEnabled"):
            self.url_bar.setClearButtonEnabled(False)
        # Sistema de autocompletado desactivado temporalmente
        self.autocomplete_system = None

        # Indicador SSL — icono candado/advertencia antes de la URL bar
        self.ssl_indicator = SslIndicatorButton()
        self.nav_bar.addWidget(self.ssl_indicator)

        self.nav_bar.addWidget(self.url_bar)

        # Botón de favoritos (entre URL bar y búsqueda de pestañas)
        self.favorite_nav_action = _nav_action(
            "star", "Guardar pestaña actual en marcadores",
            self.show_save_favorite_menu
        )
        self.nav_bar.addAction(self.favorite_nav_action)
        self._nav_icon_actions.append(self.favorite_nav_action)

        # Botón para mostrar/ocultar la barra de favoritos (junto al anterior)
        self.toggle_favbar_nav_action = _nav_action(
            "heart", "Mostrar / ocultar barra de favoritos",
            self.toggle_favorites_bar
        )
        self.nav_bar.addAction(self.toggle_favbar_nav_action)
        self._nav_icon_actions.append(self.toggle_favbar_nav_action)

        # Hueco flexible entre URL/favoritos y controles derechos (alinea zona derecha al borde)
        self._navbar_trailing_spacer = QWidget()
        self._navbar_trailing_spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.nav_bar.addWidget(self._navbar_trailing_spacer)

        # Separador visual entre URL bar/favoritos y tab search
        self.url_separator = QFrame()
        self.url_separator.setFrameShape(QFrame.VLine)
        self.url_separator.setFrameShadow(QFrame.Sunken)
        self.url_separator.setMaximumWidth(1)
        # El color del separador se maneja por el tema JSON
        self.nav_bar.addWidget(self.url_separator)

        # Solo guardar referencia de las acciones para aplicar iconos después
        self.function_actions = {}

        # Campo de búsqueda de pestañas - PUEDE OCULTARSE en ventanas pequeñas
        self.tab_search = QLineEdit()
        self.tab_search.setPlaceholderText("Search tabs...")
        # CRÍTICO: Reducir ancho mínimo para evitar overflow
        self.tab_search.setMinimumWidth(100)  # Reducido de 200 a 100
        self.tab_search.setMaximumWidth(250)  # Reducido de 350 a 250
        self.tab_search.setFixedHeight(36)
        self.tab_search.textChanged.connect(self.tab_manager.buscar_pestanas)
        self.nav_bar.addWidget(self.tab_search)

        # Profile Switcher — oculto de la navbar, acceso desde menú hamburguesa
        self.profile_switcher = ProfileSwitcher(self.profile_manager, self)
        self.profile_switcher.hide()

        # Hamburger Menu Button
        self.menu_btn = QPushButton()
        try:
            from ui.core.strip_icons import build_nav_icon as _bni_menu
            self.menu_btn.setIcon(_bni_menu("menu", _nav_color, self.ICON_18))
            self.menu_btn.setIconSize(self.ICON_18)
        except Exception:
            self.menu_btn.setIcon(QIcon("icons/menu.svg"))
        self.menu_btn.setFixedSize(36, 36)  # Ajustado para coincidir con sidebar
        self.menu_btn.setToolTip("Menú principal")
        self.menu_btn.setProperty("class", "menu-button")
        self.menu_btn.clicked.connect(self.show_main_menu)
        self.nav_bar.addWidget(self.menu_btn)

        # Login Button with account icon
        self.login_btn = QPushButton()
        self.login_btn.setFixedSize(36, 36)  # Ajustado para coincidir con sidebar
        self.login_btn.setToolTip("Iniciar sesión en Katphi")
        self.login_btn.clicked.connect(self.show_login_dialog)

        # Icono SVG temático (se re-colorea en refresh_all_nav_icons)
        try:
            from ui.core.strip_icons import build_nav_icon as _bni
            _login_icon = _bni("account", _nav_color, self.ICON_18)
        except Exception:
            _login_icon = QIcon("icons/account.svg")
        self.login_btn.setIcon(_login_icon)
        self.login_btn.setIconSize(self.ICON_18)

        # Los estilos del botón de login se manejan por el tema JSON
        self.login_btn.setProperty("class", "login-button")
        self.nav_bar.addWidget(self.login_btn)

        # User Status Label (initially hidden)
        self.user_status_label = QLabel("")
        # Los estilos de la etiqueta de estado se manejan por el tema JSON
        self.user_status_label.setProperty("class", "status-label")
        self.user_status_label.hide()
        self.nav_bar.addWidget(self.user_status_label)

        # Controles tipo “cliente”: solo visibles en modo ventana sin marco (Frameless)
        self._setup_window_chrome_controls()

        self.nav_bar.installEventFilter(self)
        # Permitir mover/maximizar la ventana arrastrando el hueco vacío de la
        # tira de pestañas (estilo Firefox), en modo ventana sin marco.
        try:
            self.tab_manager.tabs.tabBar().installEventFilter(self)
            self.tab_strip_container.installEventFilter(self)
        except Exception:
            pass

        # ── Botón Nueva Pestaña en la esquina derecha de la barra de pestañas ──
        pass  # botón '+' del tab bar se gestiona en BrowserTabBar (tabs.py)
    def setup_side_strip(self):
        """Configure the fixed vertical sidebar with standard buttons"""
        self.side_strip.setIconSize(QSize(16, 16))
        self.side_strip.setToolButtonStyle(Qt.ToolButtonIconOnly)

        # Aplica estilos iniciales; se refrescan en _refresh_side_strip_style()
        # cuando cambia el tema para que hover/bg sean siempre los del tema activo.
        self._refresh_side_strip_style()

        # Función helper para crear acciones de la barra lateral
        def create_strip_action(icon_path, tooltip, callback):
            # Priorizar SVG para permitir tematización de color
            icon_file = os.path.basename(icon_path)
            icon_name, _ = os.path.splitext(icon_file)
            icon_dir = os.path.dirname(icon_path) or "icons"

            # Alias para compatibilidad entre nombres legacy y nuevos SVG
            svg_alias = {
                "settings": "plugins",
                "security": "pentesting",
                "tor_off": "tor",
                "wrench": "debug",
            }

            svg_path = os.path.join(icon_dir, f"{icon_name}.svg")
            if os.path.exists(svg_path):
                resolved_icon_path = svg_path
            elif icon_name in svg_alias:
                aliased_svg = os.path.join(icon_dir, f"{svg_alias[icon_name]}.svg")
                resolved_icon_path = aliased_svg if os.path.exists(aliased_svg) else icon_path
            else:
                resolved_icon_path = icon_path
            if not os.path.isfile(resolved_icon_path):
                resolved_icon_path = icon_path
            icon_color = "#5F6368"
            if THEME_SYSTEM_AVAILABLE:
                tm = get_theme_manager()
                if tm:
                    colors = tm.get_theme_data().get("colors", {})
                    icon_color = colors.get("icon_color", colors.get("primary", "#5F6368"))
            sz = self.side_strip.iconSize()
            icon = build_strip_icon(
                os.path.abspath(resolved_icon_path), icon_color, sz
            )
            if icon.isNull():
                icon = QIcon(resolved_icon_path)
            if icon.isNull():
                icon = QIcon("icons/sidebar.svg")
            action = QAction(icon, tooltip, self)
            action.setProperty("strip_icon_path", os.path.abspath(resolved_icon_path))
            action.triggered.connect(callback)
            return action
        # Botón de Chat IA SIEMPRE visible y en primera posición (panel izquierdo)
        self.chat_action = create_strip_action(
            "icons/chat.png", "Asistente IA", self.toggle_chat_panel
        )
        self.side_strip.addAction(self.chat_action)

        # Crear acciones de funciones
        self.privacy_action = create_strip_action(
            "icons/lock.png", "Privacy", self.toggle_privacy_panel
        )
        self.side_strip.addAction(self.privacy_action)

        self.password_action = create_strip_action(
            "icons/key.png", "Password Manager", self.toggle_password_manager
        )
        self.side_strip.addAction(self.password_action)

        # Botón DevTools removido del sidebar (acceso desde menú contextual -> Inspect)
        self.devtools_action = None

        # Chat IA ya agregado al inicio de la barra lateral

        # Botones condicionales
        if SCRAPING_AVAILABLE:
            self.scraping_action = create_strip_action(
                "icons/scrap.png", "Scraping", self.toggle_scraping_panel
            )
            self.side_strip.addAction(self.scraping_action)
        if PROXY_AVAILABLE:
            self.proxy_action = create_strip_action(
                "icons/proxy.png", "Proxies", self.toggle_proxy_panel
            )
            self.side_strip.addAction(self.proxy_action)
        # Botón Tor: SIEMPRE visible para que el usuario pueda acceder al panel
        self.tor_action = create_strip_action(
            "icons/tor_off.png", "Tor", self.toggle_tor_panel
        )
        if self.tor_action.icon().isNull():
            fb = os.path.abspath("icons/lock.png")
            ic_col = "#5F6368"
            if THEME_SYSTEM_AVAILABLE:
                tm = get_theme_manager()
                if tm:
                    ic_col = tm.get_theme_data().get("colors", {}).get(
                        "icon_color", "#5F6368"
                    )
            ic = build_strip_icon(fb, ic_col, self.side_strip.iconSize())
            self.tor_action.setIcon(ic if not ic.isNull() else QIcon("icons/lock.png"))
            self.tor_action.setProperty("strip_icon_path", fb)
        self.side_strip.addAction(self.tor_action)

        # El asistente de navegación está integrado en el panel de Chat IA
        self.gentab_action = None

        # Tab Groups Panel
        if hasattr(self, "tab_groups_panel") and self.tab_groups_panel:
            self.tab_groups_action = create_strip_action(
                "icons/bookmark.png", "Tab Groups", self.toggle_tab_groups_panel
            )
            self.side_strip.addAction(self.tab_groups_action)
        # SEO Analyzer - NOW LOADED DYNAMICALLY
        # (Button will be added automatically by UnifiedPluginManager when plugin is installed)

        if PLUGIN_SYSTEM_AVAILABLE:
            self.plugin_action = create_strip_action(
                "icons/settings.png", "Plugins", self.toggle_plugin_panel
            )
            self.side_strip.addAction(self.plugin_action)
        # Pentesting Suite - botón fijo en la barra lateral
        # La lógica de carga del panel se resuelve en toggle_pentesting_panel
        if PLUGIN_SYSTEM_AVAILABLE:
            self.pentesting_action = create_strip_action(
                "icons/security.png", "Pentesting Suite", self.toggle_pentesting_panel
            )
            self.side_strip.addAction(self.pentesting_action)
        # Botón de "Cuenta" eliminado según requerimiento del usuario

        self.bookmark_action = create_strip_action(
            "icons/bookmark.png", "Marcadores", self.toggle_bookmark_manager
        )
        self.side_strip.addAction(self.bookmark_action)

        self.theme_action = create_strip_action(
            "icons/themes.svg", "Gestor de Temas", self.open_theme_selector
        )
        self.side_strip.addAction(self.theme_action)

        # Visor de logs (siempre visible para depuración)
        self.log_viewer_action = create_strip_action(
            "icons/logviewer.svg", "Log Viewer", self.toggle_log_viewer
        )
        self.side_strip.addAction(self.log_viewer_action)
    def _setup_theme_system(self):
        """Configura el sistema de temas básico (sin dependencias de plugins)"""
        # Usar siempre el sistema básico para evitar dependencias
        self._load_legacy_theme()
        print("[OK] Basic theme system configured")
    def _make_strip_action(
        self,
        icon_name: str,
        tooltip: str,
        callback,
        color: str | None = None,
    ) -> "QAction":
        """
        Crea un QAction para el side strip con icono SVG temático.

        A diferencia de la función local `create_strip_action` que sólo
        existe dentro de `setup_side_strip`, este método está disponible
        en todo el ciclo de vida de MainWindow — útil para plugins que se
        cargan dinámicamente DESPUÉS del arranque.

        Almacena automáticamente `strip_icon_path` para que
        `_refresh_side_strip_icons` y `refresh_all_nav_icons` puedan
        actualizar el color del icono al cambiar de tema.
        """
        from PySide6.QtGui import QAction as _QAction

        if color is None:
            color = self._get_nav_icon_color()
        sz = self.side_strip.iconSize() if hasattr(self, "side_strip") else QSize(16, 16)

        try:
            from ui.core.strip_icons import resolve_icon_path, build_strip_icon
            path = resolve_icon_path(icon_name)
            if path:
                icon = build_strip_icon(path, color, sz)
            else:
                icon = QIcon(f"icons/{icon_name}.svg")
                path = os.path.abspath(f"icons/{icon_name}.svg")
        except Exception:
            icon = QIcon(f"icons/{icon_name}.svg")
            path = os.path.abspath(f"icons/{icon_name}.svg")
        action = _QAction(icon, tooltip, self)
        action.setToolTip(tooltip)
        action.setProperty("strip_icon_path", path)
        action.setProperty("strip_icon_name", icon_name)
        if callback:
            action.triggered.connect(callback)
        return action
    def _refresh_side_strip_style(self, theme_id=None):
        """
        Aplica al sidebar el QSS con los colores hover/background del tema activo.
        Llamar al arrancar y cada vez que cambie el tema.
        """
        if not hasattr(self, "side_strip"):
            return
        # Leer colores del tema; usar fallbacks razonables si no existen
        bg_color = "transparent"
        hover_color = "rgba(255,255,255,0.10)"

        if THEME_SYSTEM_AVAILABLE:
            try:
                tm = get_theme_manager()
                if tm:
                    colors = tm.get_theme_data().get("colors", {})
                    bg_color = colors.get("icon_button_background", "transparent")
                    hover_color = colors.get(
                        "icon_button_hover",
                        colors.get("hover", colors.get("button_hover", "rgba(255,255,255,0.10)"))
                    )
            except Exception:
                pass
        self.side_strip.setStyleSheet(f"""
            QToolBar {{
                spacing: 2px;
                padding: 0px;
                border: none;
                background: transparent;
            }}
            QToolButton {{
                width: 36px;
                height: 36px;
                padding: 0px;
                margin: 0px;
                border: none;
                border-radius: 6px;
                background-color: {bg_color};
            }}
            QToolButton:hover {{
                background-color: {hover_color};
            }}
            QToolButton:pressed {{
                background-color: {hover_color};
                opacity: 0.7;
            }}
        """)
    def _refresh_navbar_style(self, theme_id=None):
        """
        Reaplica el QSS de la barra de navegación superior usando los colores
        del ThemeEngine activo (navbar_button_* del tema seleccionado).
        """
        if not hasattr(self, "nav_bar"):
            return
        btn_bg      = "transparent"
        btn_hover   = "rgba(255,255,255,0.10)"
        btn_pressed = "rgba(255,255,255,0.15)"
        toolbar_bg  = "transparent"
        toolbar_border = "rgba(255,255,255,0.08)"

        if THEME_SYSTEM_AVAILABLE:
            try:
                tm = get_theme_manager()
                if tm:
                    colors = tm.get_theme_data().get("colors", {})
                    btn_bg      = colors.get("navbar_button_background", "transparent")
                    btn_hover   = colors.get("navbar_button_hover",
                                             colors.get("hover", "rgba(255,255,255,0.10)"))
                    btn_pressed = colors.get("navbar_button_pressed",
                                             colors.get("button_pressed", btn_hover))
                    toolbar_bg  = colors.get("toolbar_background",
                                             colors.get("background", "transparent"))
                    toolbar_border = colors.get("toolbar_border",
                                                colors.get("border", "rgba(255,255,255,0.08)"))
            except Exception:
                pass
        self.nav_bar.setStyleSheet(f"""
            QToolBar {{
                background: {toolbar_bg};
                border-bottom: 1px solid {toolbar_border};
                spacing: 4px;
                padding: 0px 8px;
                border: none;
            }}
            QToolButton, QPushButton {{
                background-color: {btn_bg};
                border: none;
                border-radius: 6px;
                min-width: 32px;
                max-width: 36px;
                min-height: 32px;
                max-height: 36px;
                padding: 0px;
                margin: 0px;
            }}
            QToolButton:hover, QPushButton:hover {{
                background-color: {btn_hover};
            }}
            QToolButton:pressed, QPushButton:pressed {{
                background-color: {btn_pressed};
            }}
            QToolButton:disabled, QPushButton:disabled {{
                opacity: 0.35;
            }}
        """)
        # La tira de pestañas (con los controles de ventana) usa el mismo fondo
        # que la barra de navegación. Así los botones min/max/cerrar mantienen el
        # contraste correcto al cambiar de tema (antes quedaban "invisibles").
        if hasattr(self, "tab_strip_container") and self.tab_strip_container:
            try:
                self.tab_strip_container.setStyleSheet(
                    f"QWidget#tabStripContainer {{ background: {toolbar_bg}; }}"
                )
            except Exception:
                pass
        self._refresh_window_chrome_style()

        # Actualizar fondo del indicador SSL para que encaje con la navbar
        if hasattr(self, "ssl_indicator"):
            try:
                self.ssl_indicator.setStyleSheet(
                    f"background: transparent; border: none;"
                )
            except Exception:
                pass

    def _refresh_url_bar_style(self, theme_id=None):
        """
        Aplica el QSS de la barra de URL usando los colores del tema activo.
        Lee url_bar_background / url_bar_text / url_bar_border del tema
        (con fallback a surface/primary/border) para que sea editable
        desde el plugin editor de temas.
        """
        if not hasattr(self, "url_bar"):
            return

        bg      = "#2b2d30"
        text    = "#e8eaed"
        border  = "#45484a"
        ph      = "#9aa0a6"
        focus   = "#8ab4f8"

        if THEME_SYSTEM_AVAILABLE:
            try:
                tm = get_theme_manager()
                if tm:
                    colors = tm.get_theme_data().get("colors", {})
                    bg     = colors.get("url_bar_background",
                                        colors.get("surface",     bg))
                    text   = colors.get("url_bar_text",
                                        colors.get("primary",     text))
                    border = colors.get("url_bar_border",
                                        colors.get("border",      border))
                    ph     = colors.get("url_bar_placeholder",
                                        colors.get("secondary",   ph))
                    focus  = colors.get("accent",                  focus)
            except Exception:
                pass

        self.url_bar.setStyleSheet(f"""
            QLineEdit#urlBar, QLineEdit#conversationalNavBar {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 13px;
                selection-background-color: {focus};
            }}
            QLineEdit#urlBar:focus, QLineEdit#conversationalNavBar:focus {{
                border: 1px solid {focus};
            }}
            QLineEdit#urlBar::placeholder, QLineEdit#conversationalNavBar::placeholder {{
                color: {ph};
            }}
        """)

    def _setup_window_chrome_controls(self):
        """Minimizar / maximizar / cerrar incrustados (modo ventana sin marco)."""
        chrome = QWidget()
        chrome.setObjectName("windowChrome")
        chrome.setMinimumHeight(36)
        # Tamaño fijo: impide que el contenedor se expanda dentro del QHBoxLayout
        # de la tira de pestañas (evita que los botones se separen al maximizar).
        chrome.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(chrome)
        lay.setContentsMargins(0, 2, 2, 2)
        lay.setSpacing(0)

        def _mk(txt: str, tip: str, slot, name: str) -> QPushButton:
            b = QPushButton(txt)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(tip)
            b.setFixedSize(40, 32)
            b.setObjectName(name)
            b.clicked.connect(slot)
            return b

        self._chrome_min_btn = _mk("\u2212", "Minimizar", self._chrome_minimize, "chromeMin")
        self._chrome_max_btn = _mk(
            "\u25a1", "Maximizar o restaurar", self._chrome_toggle_maximize, "chromeMax"
        )
        self._chrome_close_btn = _mk("\u2715", "Cerrar", self._chrome_close_window, "chromeClose")
        lay.addWidget(self._chrome_min_btn)
        lay.addWidget(self._chrome_max_btn)
        lay.addWidget(self._chrome_close_btn)

        self._window_chrome_container = chrome
        # Nota: el contenedor se inserta en la fila de pestañas (arriba a la
        # derecha, estilo Firefox) al construir el layout principal, no aquí.
        chrome.hide()
        self._chrome_update_max_glyph()

    def _refresh_window_chrome_style(self):
        """Alinear estilo de botones de ventana con la barra de navegación."""
        if not hasattr(self, "_chrome_min_btn"):
            return
        btn_bg = "transparent"
        btn_hover = "rgba(255,255,255,0.12)"
        close_hover = "#c42b1c"
        fg = "rgba(255,255,255,0.9)"
        if THEME_SYSTEM_AVAILABLE:
            try:
                tm = get_theme_manager()
                if tm:
                    colors = tm.get_theme_data().get("colors", {})
                    btn_hover = colors.get(
                        "navbar_button_hover",
                        colors.get("hover", btn_hover),
                    )
                    fg = colors.get(
                        "navbar_text",
                        colors.get("text_primary", fg),
                    )
            except Exception:
                pass
        qss = f"""
            QWidget#windowChrome QPushButton#chromeMin,
            QWidget#windowChrome QPushButton#chromeMax,
            QWidget#windowChrome QPushButton#chromeClose {{
                background: {btn_bg};
                border: none;
                color: {fg};
                font-size: 16px;
                font-weight: bold;
                border-radius: 4px;
            }}
            QWidget#windowChrome QPushButton#chromeMin:hover,
            QWidget#windowChrome QPushButton#chromeMax:hover {{
                background: {btn_hover};
            }}
            QWidget#windowChrome QPushButton#chromeClose:hover {{
                background: {close_hover};
                color: #ffffff;
            }}
        """
        self._window_chrome_container.setStyleSheet(qss)

    def _chrome_minimize(self):
        self.showMinimized()

    def _chrome_toggle_maximize(self):
        self.toggle_maximize()

    def _chrome_close_window(self):
        self.close()

    def _chrome_update_max_glyph(self):
        if not hasattr(self, "_chrome_max_btn"):
            return
        try:
            # □ maximizar · restaurar (símbolos Unicode bien soportados)
            self._chrome_max_btn.setText("\u25aa" if self.isMaximized() else "\u25a1")
        except Exception:
            self._chrome_max_btn.setText("□")

    def _sync_window_chrome_visibility_from_flags(self):
        if not hasattr(self, "_window_chrome_container"):
            return
        frameless = bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self._window_frameless = frameless
        self._window_chrome_container.setVisible(frameless)
        self._apply_frameless_window_size_policy()
        self._ensure_frameless_resize_handles()
        self._layout_frameless_resize_handles()
        self._sync_frameless_resize_handles_visibility()
        self._sync_tab_strip_widths()
        QTimer.singleShot(0, self._chrome_update_max_glyph)
        QTimer.singleShot(0, self._sync_tab_strip_widths)

    def _sync_tab_strip_widths(self):
        """
        Acota el ancho máximo de la barra de pestañas para dejar hueco a los
        controles de ventana (estilo Firefox). QTabWidget reposiciona su barra
        (aunque esté reparentada) al ancho del contenido; ese setGeometry queda
        limitado por el maximumWidth, evitando que las pestañas se solapen con
        los botones de minimizar/maximizar/cerrar.
        """
        if not hasattr(self, "tab_strip_container") or not hasattr(self, "tab_manager"):
            return
        try:
            bar = self.tab_manager.tabs.tabBar()
            cont_w = self.tab_strip_container.width()
            chrome_w = 0
            ch = getattr(self, "_window_chrome_container", None)
            if ch is not None and ch.isVisible():
                # Usar SOLO el sizeHint (estable). Usar ch.width() creaba un
                # bucle de realimentación que inflaba el contenedor del chrome.
                chrome_w = ch.sizeHint().width()
            avail = cont_w - chrome_w
            if avail > 0:
                bar.setMaximumWidth(avail)
        except Exception:
            pass

    def _frameless_top_reserve_y(self) -> int:
        """
        Desplazamiento vertical del borde redimensionable superior.

        En el layout estilo Firefox la tira de pestañas está en el borde real
        de la ventana, por lo que el redimensionado superior debe situarse en
        y=0 (esquinas y banda superior sobre el borde físico de la ventana).
        """
        return 0

    def _ensure_frameless_resize_handles(self) -> None:
        if getattr(self, "_frameless_resize_handles_created", False):
            return
        le = Qt.Edge.LeftEdge
        ri = Qt.Edge.RightEdge
        top = Qt.Edge.TopEdge
        bot = Qt.Edge.BottomEdge
        edge_specs = (
            le,
            ri,
            top,
            bot,
            le | top,
            ri | top,
            le | bot,
            ri | bot,
        )
        self._frameless_resize_handles = [_FrameResizeHandle(self, e) for e in edge_specs]
        self._frameless_resize_handles_created = True
        for h in self._frameless_resize_handles:
            h.hide()

    def _layout_frameless_resize_handles(self) -> None:
        """Coloca bands de píxeles sobre bordes y esquinas (transparentes)."""
        if not getattr(self, "_frameless_resize_handles_created", False):
            return
        handles = getattr(self, "_frameless_resize_handles", None)
        if not handles:
            return
        t = _FrameResizeHandle.THICKNESS
        w_win = max(self.width(), t * 4)
        h_win = max(self.height(), t * 4)
        top_y = self._frameless_top_reserve_y()
        if top_y > h_win - 3 * t:
            top_y = max(0, h_win - 3 * t)
        ih = max(0, h_win - top_y - 2 * t)
        iw = max(0, w_win - 2 * t)
        rects = [
            QRect(0, top_y + t, t, ih),
            QRect(w_win - t, top_y + t, t, ih),
            QRect(t, top_y, iw, t),
            QRect(t, h_win - t, iw, t),
            QRect(0, top_y, t, t),
            QRect(w_win - t, top_y, t, t),
            QRect(0, h_win - t, t, t),
            QRect(w_win - t, h_win - t, t, t),
        ]
        for gh, rr in zip(handles, rects):
            gh.setGeometry(rr)
            gh.raise_()

    def _sync_frameless_resize_handles_visibility(self) -> None:
        if not getattr(self, "_frameless_resize_handles_created", False):
            return
        show_it = (
            getattr(self, "_window_frameless", False)
            and not self.isMaximized()
            and not self.isFullScreen()
        )
        for gh in getattr(self, "_frameless_resize_handles", ()):
            gh.setVisible(show_it)

    def _apply_frameless_window_size_policy(self) -> None:
        if getattr(self, "_window_frameless", False):
            self.setMinimumSize(self.FRAMELESS_MIN_W, self.FRAMELESS_MIN_H)
        else:
            self.setMinimumSize(0, 0)

    def _set_frameless_window(self, enabled: bool, *, persist: bool = True) -> None:
        """Activa/desactiva ventana sin decoración del SO; controles en la navbar."""
        if persist:
            self.settings.setValue("ui/frameless_window", enabled)
            self.settings.sync()

        geom = self.frameGeometry()
        was_visible = self.isVisible()
        was_max = self.isMaximized()

        flags = Qt.WindowType.Window
        if enabled:
            flags |= Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        self._window_frameless = enabled

        if was_visible:
            if was_max:
                self.showMaximized()
            else:
                self.showNormal()
                if geom.isValid():
                    if enabled:
                        try:
                            self.move(geom.topLeft())
                            self.resize(
                                max(int(geom.width()), self.FRAMELESS_MIN_W),
                                max(int(geom.height()), self.FRAMELESS_MIN_H),
                            )
                        except Exception:
                            self.resize(self.FRAMELESS_MIN_W, self.FRAMELESS_MIN_H)
                    else:
                        self.setGeometry(geom)
                self.show()
        else:
            self.show()

        self._sync_window_chrome_visibility_from_flags()

        fs_chk = getattr(self, "_frameless_settings_check", None)
        if fs_chk is not None:
            try:
                fs_chk.blockSignals(True)
                fs_chk.setChecked(enabled)
            except RuntimeError:
                self._frameless_settings_check = None
            finally:
                try:
                    fs_chk.blockSignals(False)
                except RuntimeError:
                    pass

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            QTimer.singleShot(0, self._chrome_update_max_glyph)
            QTimer.singleShot(0, self._sync_frameless_resize_handles_visibility)
            QTimer.singleShot(0, self._layout_frameless_resize_handles)
            QTimer.singleShot(0, self._sync_tab_strip_widths)
        super().changeEvent(event)

    def eventFilter(self, obj, event):  # noqa: N802 — API Qt
        # Arrastre / doble-clic-maximizar desde el hueco vacío de la tira de
        # pestañas (barra de pestañas o su contenedor), solo en modo sin marco.
        if getattr(self, "_window_frameless", False) and isinstance(event, QMouseEvent):
            tab_bar = None
            try:
                tab_bar = self.tab_manager.tabs.tabBar()
            except Exception:
                tab_bar = None
            strip = getattr(self, "tab_strip_container", None)
            if obj is tab_bar or obj is strip:
                et = event.type()
                pos_pt = (
                    event.position().toPoint()
                    if hasattr(event, "position")
                    else event.pos()
                )
                # En la barra de pestañas solo el área SIN pestaña es "agarrable".
                on_empty = True
                if obj is tab_bar and tab_bar is not None:
                    on_empty = tab_bar.tabAt(pos_pt) == -1
                if on_empty and event.button() == Qt.MouseButton.LeftButton:
                    try:
                        wh = self.windowHandle()
                        if wh is not None:
                            if et == QEvent.Type.MouseButtonDblClick:
                                self.toggle_maximize()
                                return True
                            if et == QEvent.Type.MouseButtonPress:
                                wh.startSystemMove()
                                return True
                    except Exception:
                        pass

        if (
            getattr(self, "_window_frameless", False)
            and obj is getattr(self, "nav_bar", None)
        ):
            et = event.type()
            spacer = getattr(self, "_navbar_trailing_spacer", None)
            try:
                wh = self.windowHandle()
                if wh is None:
                    raise RuntimeError("sin windowHandle")
                if isinstance(event, QMouseEvent):
                    pos_pt = (
                        event.position().toPoint()
                        if hasattr(event, "position")
                        else event.pos()
                    )
                    cw = self.nav_bar.childAt(pos_pt)
                    drag_zone = spacer is not None and cw is spacer
                    if et == QEvent.Type.MouseButtonDblClick and drag_zone:
                        if event.button() == Qt.MouseButton.LeftButton:
                            self.toggle_maximize()
                            return False
                    if et == QEvent.Type.MouseButtonPress and drag_zone:
                        if event.button() == Qt.MouseButton.LeftButton:
                            try:
                                wh.startSystemMove()
                            except Exception:
                                pass
                            return False
            except Exception:
                pass
        return False

    def _on_theme_changed(self, theme_id: str):
        """Callback cuando cambia el tema — actualiza iconos, hover y ajustes."""
        self.settings.setValue("theme", theme_id)
        print(f"[OK] Theme changed to: {theme_id}")
        QTimer.singleShot(50, self.refresh_all_nav_icons)
        QTimer.singleShot(60, self._refresh_side_strip_style)
        QTimer.singleShot(65, self._refresh_navbar_style)
        QTimer.singleShot(70, self._refresh_tab_bar_style)
        QTimer.singleShot(75, self._refresh_url_bar_style)

    def _refresh_tab_bar_style(self, theme_id=None):
        """
        Reaplica el QSS del tab bar (pestañas de navegación) usando los colores
        del ThemeEngine activo.

        El tab bar tiene su propio setStyleSheet() local que toma precedencia sobre
        app.setStyleSheet(). Sin este método, el tab bar ignora los cambios de tema.
        """
        if not hasattr(self, "tab_manager") or not self.tab_manager:
            return
        tab_bg    = "#2B2D30"
        tab_sel   = "#3C3F41"
        tab_hover = "#45484A"
        tab_text  = "#BBBBBB"
        tab_text_sel = "#E8EAED"
        strip_bg  = "transparent"
        close_hover = "rgba(255,255,255,0.16)"

        if THEME_SYSTEM_AVAILABLE:
            try:
                tm = get_theme_manager()
                if tm:
                    colors = tm.get_theme_data().get("colors", {})
                    tab_bg       = colors.get("tab_background",  colors.get("surface",     tab_bg))
                    tab_sel      = colors.get("tab_selected",    colors.get("surface",     tab_sel))
                    tab_hover    = colors.get("tab_hover",       colors.get("hover",       tab_hover))
                    tab_text     = colors.get("secondary",       tab_text)
                    tab_text_sel = colors.get("primary",         tab_text_sel)
                    strip_bg     = colors.get("toolbar_background",
                                             colors.get("background", strip_bg))
                    close_hover  = colors.get("tab_close_hover", close_hover)
            except Exception:
                pass

        tab_bar_qss = f"""
            QTabBar {{
                background-color: transparent;
            }}
            QTabBar::tab {{
                background-color: {tab_bg};
                color: {tab_text};
                border: none;
                padding: 5px 12px;
                margin-right: 4px;
                margin-top: 4px;
                border-radius: 8px;
                min-width: 160px;
                max-width: 240px;
                height: 26px;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background-color: {tab_sel};
                color: {tab_text_sel};
                margin-top: 2px;
                height: 28px;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {tab_hover};
            }}
        """

        tab_widget_qss = f"""
            QTabWidget::pane {{
                background-color: transparent;
                border: none;
            }}
            QTabBar::tab {{
                background-color: {tab_bg};
                color: {tab_text};
                border: none;
                padding: 5px 12px;
                margin-right: 4px;
                margin-top: 4px;
                border-radius: 8px;
                min-width: 160px;
                max-width: 240px;
                height: 26px;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background-color: {tab_sel};
                color: {tab_text_sel};
                margin-top: 2px;
                height: 28px;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {tab_hover};
            }}
        """

        try:
            from PySide6.QtWidgets import QToolButton
            tab_bar = self.tab_manager.tabs.tabBar()
            tab_bar.setStyleSheet(tab_bar_qss)
            self.tab_manager.tabs.setStyleSheet(tab_widget_qss)
            # Actualizar colores de los botones de cierre existentes con el color del tema.
            # Los botones son QToolButton instalados via setTabButton() en BrowserTabBar.
            _btn_qss = f"""
                QToolButton {{
                    color: {tab_text};
                    background: transparent;
                    border: none;
                    border-radius: 4px;
                    font-size: 13px;
                    font-weight: 400;
                    padding: 0px;
                }}
                QToolButton:hover {{
                    color: {tab_text_sel};
                    background: {close_hover};
                }}
                QToolButton:pressed {{
                    background: {tab_hover};
                }}
            """
            from PySide6.QtWidgets import QWidget, QTabBar
            for i in range(tab_bar.count()):
                widget = tab_bar.tabButton(i, QTabBar.ButtonPosition.RightSide)
                if isinstance(widget, QToolButton):
                    widget.setFixedSize(18, 18)
                    widget.setStyleSheet(_btn_qss)
                elif isinstance(widget, QWidget):
                    btn = widget.findChild(QToolButton)
                    if btn:
                        btn.setFixedSize(18, 18)
                        btn.setStyleSheet(_btn_qss)
        except Exception as e:
            print(f"[THEME] Error actualizando estilo del tab bar: {e}")

    def _refresh_side_strip_icons(self, theme_id=None):
        """Vuelve a tiñar iconos SVG/PNG de la barra lateral según icon_color del tema."""
        if not THEME_SYSTEM_AVAILABLE or not hasattr(self, "side_strip"):
            return
        tm = get_theme_manager()
        if not tm:
            return
        colors = tm.get_theme_data().get("colors", {})
        icon_color = colors.get("icon_color", colors.get("primary", "#000000"))
        sz = self.side_strip.iconSize()
        for act in self.side_strip.actions():
            path = act.property("strip_icon_path")
            if not path:
                continue
            icon = build_strip_icon(path, icon_color, sz)
            if not icon.isNull():
                act.setIcon(icon)
    def open_themes_editor_tab(self):
        """Muestra el panel de temas y cambia a la pestaña Editor (sin ventana nueva)."""
        if not getattr(self, "themes_plugin_instance", None):
            return
        panel = self._ensure_themes_panel_widget()
        if not panel:
            return
        from PySide6.QtWidgets import QTabWidget

        tw = panel.findChild(QTabWidget)
        if tw:
            for i in range(tw.count()):
                if "Editor" in tw.tabText(i):
                    tw.setCurrentIndex(i)
                    break
        self.show_advanced_panel(panel)
    def _load_legacy_theme(self):
        """Sistema de temas usando el nuevo theme manager"""
        if THEME_SYSTEM_AVAILABLE:
            theme_manager = get_theme_manager()
            if theme_manager:
                # El theme manager ya carga el tema guardado en su inicialización
                print(
                    f"[THEME] Theme loaded via theme manager: {theme_manager.get_current_theme()}"
                )
            else:
                print("[ERROR] Theme manager not available")
        else:
            print("[ERROR] Theme system not available")
    def load_theme(self):
        """Carga el tema guardado o usa el tema por defecto"""
        self._load_legacy_theme()
        self._apply_tooltip_theme()
    def apply_theme(self, theme):
        """Aplica el tema especificado usando el theme manager"""
        print(f"[THEME] Applying theme: {theme}")
        if THEME_SYSTEM_AVAILABLE:
            theme_manager = get_theme_manager()
            if theme_manager:
                theme_manager.apply_theme(theme)
                self._apply_tooltip_theme(theme_manager)
            else:
                print("[ERROR] Theme manager not available")
        else:
            print("[ERROR] Theme system not available")
    def _apply_tooltip_theme(self, theme_manager=None):
        """Aplica el estilo de QToolTip según el tema activo"""
        try:
            if theme_manager is None and THEME_SYSTEM_AVAILABLE:
                theme_manager = get_theme_manager()
            if not theme_manager:
                return
            c = theme_manager.get_theme_data().get("colors", {})
            bg = c.get("surface", "#3C3F41")
            text = c.get("primary", "#E8EAED")
            border = c.get("border", "#5F6368")
            # QToolTip no tiene setStyleSheet() estático en PySide6 (solo
            # setFont/setPalette, sin soporte de border-radius/padding).
            # Para estilizar tooltips con QSS hay que inyectar la regla en
            # el stylesheet de QApplication, ya que el popup del tooltip no
            # hereda el stylesheet del widget que lo muestra.
            import re
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return
            # ThemeEngine.apply_theme() ya hace app.setStyleSheet(css_completo)
            # justo antes de emitir theme_changed. Si aquí usáramos setStyleSheet()
            # a secas, sobrescribiríamos ese CSS completo y solo dejaríamos la
            # regla de QToolTip. Por eso quitamos cualquier QToolTip previo que
            # hayamos inyectado nosotros y AÑADIMOS el nuevo al final del CSS
            # existente, en vez de remplazarlo.
            #
            # IMPORTANTE: _generate_complete_css() define "* { color: ... !important; }"
            # y "QWidget { background-color: ...; color: ...; !important; }". El popup del
            # QToolTip también es un QWidget, así que sin !important aquí esas reglas
            # universales siempre ganan y el tooltip se queda con el estilo nativo del
            # sistema (fondo amarillo, texto sin contraste). Por eso forzamos !important
            # también en nuestra regla.
            existing_css = re.sub(r'QToolTip\s*\{[^}]*\}', '', app.styleSheet(), flags=re.DOTALL)
            app.setStyleSheet(existing_css + f"""
                QToolTip {{
                    background-color: {bg} !important;
                    color: {text} !important;
                    border: 1px solid {border} !important;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 12px;
                }}
            """)
        except Exception as e:
            print(f"[THEME] Error actualizando estilo de tooltip: {e}")
    def toggle_theme(self):
        """Alterna entre tema claro y oscuro usando el theme manager"""
        if THEME_SYSTEM_AVAILABLE:
            theme_manager = get_theme_manager()
            if theme_manager:
                theme_manager.toggle_theme()
                self._apply_tooltip_theme(theme_manager)
                print(f"[THEME] Theme toggled to: {theme_manager.get_current_theme()}")
            else:
                print("[ERROR] Theme manager not available")
        else:
            print("[ERROR] Theme system not available")
    def open_theme_selector(self):
        """Abre el gestor de temas en el panel lateral (como el resto de funciones)."""
        # Si el plugin de temas está cargado, usar el panel integrado
        if getattr(self, "themes_plugin_instance", None):
            self.toggle_themes_panel()
            return
        # Sin plugin: selector simple claro/oscuro
        if THEME_SYSTEM_AVAILABLE:
            theme_manager = get_theme_manager()
            if theme_manager:
                from PySide6.QtWidgets import (
                    QDialog,
                    QVBoxLayout,
                    QHBoxLayout,
                    QPushButton,
                    QLabel,
                )

                dialog = QDialog(self)
                dialog.setWindowTitle("Seleccionar Tema")
                dialog.setModal(True)
                dialog.resize(300, 150)

                layout = QVBoxLayout(dialog)

                title = QLabel("Selecciona un tema:")
                title.setStyleSheet(
                    "font-size: 14px; font-weight: bold; margin-bottom: 10px;"
                )
                layout.addWidget(title)

                buttons_layout = QHBoxLayout()

                light_btn = QPushButton("Tema Claro")
                light_btn.clicked.connect(lambda: self._select_theme("light", dialog))
                buttons_layout.addWidget(light_btn)

                dark_btn = QPushButton("Tema Oscuro")
                dark_btn.clicked.connect(lambda: self._select_theme("dark", dialog))
                buttons_layout.addWidget(dark_btn)

                layout.addLayout(buttons_layout)

                cancel_btn = QPushButton("Cancelar")
                cancel_btn.clicked.connect(dialog.reject)
                layout.addWidget(cancel_btn)

                dialog.exec()
            else:
                print("[ERROR] Theme manager not available")
        else:
            print("[ERROR] Theme system not available")
    def _select_theme(self, theme, dialog):
        """Selecciona un tema y cierra el diálogo"""
        if THEME_SYSTEM_AVAILABLE:
            theme_manager = get_theme_manager()
            if theme_manager:
                theme_manager.apply_theme(theme)
                dialog.accept()
            else:
                print("[ERROR] Theme manager not available")
        else:
            print("[ERROR] Theme system not available")
    def _load_custom_styles(self):
        """Carga estilos QSS personalizados desde themes/modern.qss (legacy)"""
        try:
            import os

            qss_path = "themes/modern.qss"
            if os.path.exists(qss_path):
                with open(qss_path, "r", encoding="utf-8") as f:
                    return f.read()
            return ""
        except Exception as e:
            print(f"Error cargando estilos personalizados: {e}")
            return ""
    # Métodos de estilos básicos - ahora se usan los temas JSON

    def _close_button_qss(self) -> str:
        """Generate QSS for close button with absolute path"""
        import os

        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "icons", "tab_close.svg")
        )
        path = path.replace("\\", "/")  # Qt QSS necesita / incluso en Windows
        return f"""
        /* Override explícito del icono de cierre de pestañas */
        QTabBar::close-button {{
            image: url("{path}");
            width: 16px; height: 16px;
            subcontrol-position: right;
            margin-left: 6px;
        }}
        QTabBar::close-button:hover {{
            background: rgba(255,255,255,0.16);
            border-radius: 9px;
        }}
        """
    def toggle_bookmark_manager(self):
        """
        Alterna la visibilidad del gestor de marcadores.

        Muestra preferentemente el nuevo panel jerárquico de carpetas si está
        disponible; si no, cae al gestor clásico.
        """
        # Elegir el widget a mostrar: nuevo panel > gestor clásico
        panel = getattr(self, "bookmark_panel_widget", None) or getattr(self, "bookmark_manager", None)
        if not panel:
            return
        if (
            self.advanced_panel_stack.currentWidget() == panel
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(panel)
            # Recargar datos al abrir el panel
            if hasattr(panel, "reload"):
                panel.reload()
    def toggle_sidebar(self):
        """Oculta o muestra el panel lateral izquierdo"""
        if hasattr(self, "sidebar_container") and self.sidebar_container:
            if self.sidebar_visible:
                # Ocultar el sidebar
                self.sidebar_container.hide()
                self.sidebar_visible = False
            else:
                # Mostrar el sidebar
                self.sidebar_container.show()
                self.sidebar_visible = True
    def toggle_privacy_panel(self):
        """Alterna la visibilidad del panel de privacidad USANDO EL STACK FIJO"""
        if hasattr(self, "privacy_manager") and self.privacy_manager:
            if (
                self.advanced_panel_stack.currentWidget() == self.privacy_manager
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.privacy_manager)
    def toggle_password_manager(self):
        """Toggle password manager visibility USING FIXED STACK"""
        if hasattr(self, "password_manager") and self.password_manager:
            if (
                self.advanced_panel_stack.currentWidget() == self.password_manager
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.password_manager)
    def show_advanced_panel(self, widget):
        """Muestra un panel avanzado REDIMENSIONABLE sin mover la barra lateral"""
        if widget is None:
            self.hide_advanced_panel()
            return
        if self.advanced_panel_stack.indexOf(widget) < 0:
            self.advanced_panel_stack.addWidget(widget)
        self.advanced_panel_stack.setCurrentWidget(widget)
        # Reanclar la X al panel actual para que quede integrada en cada panel
        self.close_panel_btn.setParent(widget)

        # Hacer el panel REDIMENSIONABLE con límites razonables
        self.advanced_panel_stack.setMinimumWidth(350)  # Mínimo para ver contenido
        self.advanced_panel_stack.setMaximumWidth(1000)  # Máximo generoso
        self.advanced_panel_stack.show()
        self._position_panel_close_button()
        self.close_panel_btn.show()
        self.close_panel_btn.raise_()

        # Establecer tamaño inicial para el splitter (esto es redimensionable)
        content_splitter = self.advanced_panel_stack.parent()
        if hasattr(content_splitter, "setSizes"):
            # Dar tamaño inicial: sidebar fijo, panel 30%, pestañas 70%
            total_width = content_splitter.width() - 36  # Restar ancho de sidebar
            panel_width = min(450, total_width * 0.3)  # 30% o 450px, lo que sea menor
            tabs_width = total_width - panel_width
            content_splitter.setSizes(
                [36, int(panel_width), int(tabs_width)]
            )  # [sidebar, panel, tabs]
    def hide_advanced_panel(self):
        """Oculta el panel avanzado actual"""
        self.advanced_panel_stack.setMinimumWidth(0)
        self.advanced_panel_stack.setMaximumWidth(0)
        self.advanced_panel_stack.hide()
        if hasattr(self, "close_panel_btn") and self.close_panel_btn:
            self.close_panel_btn.hide()
            # Volver al stack al ocultar para evitar referencias a paneles destruidos
            self.close_panel_btn.setParent(self.advanced_panel_stack)
        # Resetear el splitter para dar todo el espacio a las pestañas
        content_splitter = self.advanced_panel_stack.parent()
        if hasattr(content_splitter, "setSizes"):
            total_width = content_splitter.width() - 36
            content_splitter.setSizes([36, 0, total_width])  # [sidebar, panel, tabs]
    def _position_panel_close_button(self):
        """Posiciona la X en la esquina superior derecha del panel activo."""
        if not hasattr(self, "close_panel_btn") or not self.close_panel_btn:
            return
        parent_widget = self.close_panel_btn.parentWidget()
        if not parent_widget:
            return
        x = max(4, parent_widget.width() - self.close_panel_btn.width() - 8)
        self.close_panel_btn.move(x, 8)
    # ── Iconos SVG temáticos ──────────────────────────────────────────────────

    def _get_nav_icon_color(self) -> str:
        """Devuelve el color de icono activo según el tema cargado."""
        try:
            from ui.core.strip_icons import get_icon_color
            return get_icon_color()
        except Exception:
            return "#A0A0A0"
    def _connect_tabbar_newtab_icon(self):
        """
        Aplica el color del tema activo al botón '+' integrado en BrowserTabBar.
        Se llama con QTimer.singleShot(0) para asegurar que el tab widget esté listo.
        """
        try:
            color = self._get_nav_icon_color()
            tab_bar = self.tab_manager.tabs.tabBar()
            if hasattr(tab_bar, "refresh_icon"):
                tab_bar.refresh_icon(color)
                print(f"[OK] Tab bar new-tab button icon refreshed (color={color})")
        except Exception as e:
            print(f"[WARNING] _connect_tabbar_newtab_icon: {e}")
    def refresh_all_nav_icons(self, color: str | None = None) -> None:
        """
        Actualiza el color de todos los iconos de navegación (navbar + sidebar).
        Llamar cuando cambia el tema.

        Args:
            color: Nuevo color de iconos. Si None, lo obtiene del tema activo.
        """
        if color is None:
            color = self._get_nav_icon_color()
        try:
            from ui.core.strip_icons import refresh_action_icon, build_nav_icon

            # ── Navbar actions ─────────────────────────────────────────────────
            for action in getattr(self, "_nav_icon_actions", []):
                refresh_action_icon(action, color, self.ICON_18)
            # ── Favorite action ────────────────────────────────────────────────
            if hasattr(self, "favorite_nav_action"):
                refresh_action_icon(self.favorite_nav_action, color, self.ICON_18)
            # ── Side strip actions ─────────────────────────────────────────────
            if hasattr(self, "side_strip"):
                sz = self.side_strip.iconSize()
                for action in self.side_strip.actions():
                    path = action.property("strip_icon_path")
                    if path:
                        refresh_action_icon(action, color, sz)
            # ── SearchEngineButton ─────────────────────────────────────────────
            if hasattr(self, "search_engine_button"):
                btn = self.search_engine_button
                if hasattr(btn, "refresh_theme_icon"):
                    btn.refresh_theme_icon(color)
            # ── BrowserTabBar new-tab button ───────────────────────────────────
            if hasattr(self, "tab_manager"):
                tab_bar = self.tab_manager.tabs.tabBar()
                if hasattr(tab_bar, "refresh_icon"):
                    tab_bar.refresh_icon(color)
            # ── Login button ───────────────────────────────────────────────────
            if hasattr(self, "login_btn"):
                _login_ico = build_nav_icon("account", color, self.ICON_18)
                if not _login_ico.isNull():
                    self.login_btn.setIcon(_login_ico)
                    self.login_btn.setIconSize(self.ICON_18)
            if hasattr(self, "menu_btn"):
                _menu_ico = build_nav_icon("menu", color, self.ICON_18)
                if not _menu_ico.isNull():
                    self.menu_btn.setIcon(_menu_ico)
            print(f"[OK] Nav icons refreshed with color {color}")
        except Exception as e:
            print(f"[WARNING] Error refreshing nav icons: {e}")
    # ── Animación de paneles ──────────────────────────────────────────────────

    @staticmethod
    def animate_panel(widget, show: bool, target_width: int = 400) -> None:
        """
        Anima la apertura/cierre de un panel lateral via maximumWidth.

        Args:
            widget:       QWidget a animar (debe tener tamaño dinámico)
            show:         True = abrir, False = cerrar
            target_width: Ancho objetivo al abrir (px)
        """
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve

        end_value = target_width if show else 0
        start_value = widget.maximumWidth() if widget.maximumWidth() < 16000 else 0

        if show:
            widget.setMaximumWidth(16777215)  # Quitar restricción antes de animar
            widget.show()
        anim = QPropertyAnimation(widget, b"maximumWidth")
        anim.setDuration(180)
        anim.setStartValue(start_value)
        anim.setEndValue(end_value)
        anim.setEasingCurve(QEasingCurve.OutQuart)

        if not show:
            anim.finished.connect(widget.hide)
        anim.start()
        widget._panel_anim = anim  # Mantener referencia para evitar GC
    # Métodos del botón de favorito no implementados

    def load_url(self, url):
        """Load a URL or perform a search using the configured search engine"""
        try:
            url = url.strip()

            # Determinar si es búsqueda o URL
            if hasattr(self, "search_engine_manager") and self.search_engine_manager:
                is_search = self.search_engine_manager.is_search_query(url)

                if is_search:
                    # Es una búsqueda - usar motor de búsqueda
                    engine_id = (
                        self.selected_search_engine
                        if hasattr(self, "selected_search_engine")
                        and self.selected_search_engine
                        else None
                    )
                    final_url = self.search_engine_manager.search(url, engine_id)
                    # Resetear motor temporal
                    if hasattr(self, "selected_search_engine"):
                        self.selected_search_engine = None
                else:
                    # Es una URL
                    final_url = (
                        url
                        if url.startswith(("http://", "https://"))
                        else "https://" + url
                    )
            else:
                # Fallback al comportamiento anterior
                if url.startswith(("http://", "https://")) or (
                    "." in url and " " not in url
                ):
                    final_url = (
                        url
                        if url.startswith(("http://", "https://"))
                        else "https://" + url
                    )
                else:
                    query = urllib.parse.quote(url)
                    final_url = f"https://duckduckgo.com/?q={query}"
            # Navegar en la pestaña actual o crear nueva
            current_tab = self.tab_manager.tabs.currentWidget()
            if current_tab and isinstance(current_tab, QWebEngineView):
                # Navegar en pestaña actual
                if hasattr(self, "privacy_manager"):
                    self.privacy_manager.apply_privacy_settings(current_tab)
                current_tab.setUrl(QUrl(final_url))
                self.url_bar.setText(final_url)
            else:
                # Crear nueva pestaña
                new_tab = self.tab_manager.add_new_tab()
                if new_tab:
                    if hasattr(self, "privacy_manager"):
                        self.privacy_manager.apply_privacy_settings(new_tab)
                    # Conectar la señal de carga terminada para sincronizar con scraping
                    new_tab.loadFinished.connect(
                        lambda success: self.on_page_loaded(new_tab, final_url)
                    )

                    new_tab.setUrl(QUrl(final_url))
                    self.url_bar.setText(final_url)
                    self.tab_manager.tabs.setCurrentWidget(new_tab)
                else:
                    QMessageBox.warning(self, "Error", "Could not create a new tab")
        except Exception as e:
            error_msg = f"Error loading URL: {str(e)}"
            print(error_msg)
            QMessageBox.critical(self, "Error", error_msg)
    def open_new_tab(self, url=None):
        """Abre una nueva pestaña con la URL dada (o página de inicio si url es None). Usado por Split View y otros."""
        if hasattr(self, "tab_manager") and self.tab_manager:
            return self.tab_manager.add_new_tab(url)
        return None
    def on_search_engine_selected(self, engine_id):
        """Callback cuando se selecciona un motor de búsqueda temporal"""
        self.selected_search_engine = engine_id
        # Dar foco a la barra de URL para que el usuario escriba
        self.url_bar.setFocus()
        self.url_bar.selectAll()
    def on_page_loaded(self, browser_tab, url):
        """Callback when page loading is finished"""
        try:
            # Obtener el HTML de la página cargada
            browser_tab.page().toHtml(
                lambda html_content: self.on_html_loaded(html_content, url)
            )

            # También actualizar el scraping integration con el widget del navegador
            if SCRAPING_AVAILABLE and self.scraping_integration:
                self.scraping_integration.browser_widget = browser_tab
        except Exception as e:
            print(f"Error en on_page_loaded: {e}")
    def update_tab_title(self, title):
        """Update the title of the current tab"""
        current_tab = self.tab_manager.tabs.currentWidget()
        if current_tab:
            index = self.tab_manager.tabs.indexOf(current_tab)
            self.tab_manager.tabs.setTabText(index, title)
    def show_save_favorite_menu(self):
        """
        Muestra el menú para guardar la página actual como marcador.

        Si el sistema de carpetas está activo, usa el diálogo AddBookmarkDialog
        que permite elegir carpeta. Si no, usa el sistema clásico de categorías.
        """
        fm = getattr(self, "folders_manager", None)
        bm = getattr(self, "bookmark_manager", None)

        if _FOLDERS_AVAILABLE and fm and bm:
            # ── Nuevo diálogo con selector de carpeta ─────────────────────────
            url, title = "", ""
            try:
                tab = self.tab_manager.tabs.currentWidget()
                if tab:
                    url = tab.url().toString()
                    title = tab.page().title() if hasattr(tab, "page") else url
            except Exception:
                url = self.url_bar.text().strip()
                title = url
            dlg = AddBookmarkDialog(self, title=title, url=url, folders_manager=fm)
            if dlg.exec():
                if dlg.result_url:
                    bm.add_bookmark_to_folder(
                        dlg.result_url,
                        dlg.result_title or dlg.result_url,
                        dlg.result_folder_id,
                    )
                    self.statusBar().showMessage("Marcador guardado", 4000)
                    self.update_favorites_bar()
                    if self.bookmark_panel_widget:
                        self.bookmark_panel_widget.reload()
            return
        # ── Fallback: sistema clásico de categorías ───────────────────────────
        try:
            with closing(self._get_db_connection()) as conn:
                if conn is None:
                    return
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM categories")
                categories = [row[0] for row in cursor.fetchall()]

                menu = QMenu(self)
                for category in categories:
                    menu.addAction(
                        category, lambda c=category: self.save_favorite_to_category(c)
                    )
                fav_action = self.sender()
                if isinstance(fav_action, QAction):
                    button = self.nav_bar.widgetForAction(fav_action)
                    if button:
                        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
                    else:
                        menu.exec(QCursor.pos())
        except sqlite3.Error as e:
            QMessageBox.critical(
                self, "Database Error", f"Error loading categories: {e}"
            )
    def save_favorite_to_category(self, category):
        """Save a favorite in the specified category with safe transaction"""
        current_url = self.url_bar.text().strip()
        if not current_url:
            self.statusBar().showMessage("Error: No URL to save", 5000)
            return
        try:
            with closing(self._get_db_connection()) as conn:
                if conn is None:
                    return
                with conn:  # Usa el contexto como transacción
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO bookmarks (title, url, category, notes, tags) VALUES (?, ?, ?, ?, ?)",
                        (
                            "Untitled",
                            current_url,
                            category,
                            "Saved from browser",
                            "No tags",
                        ),
                    )
                self.statusBar().showMessage(f"Bookmark saved in '{category}'", 5000)
        except sqlite3.IntegrityError:
            QMessageBox.warning(
                self, "Error", "This URL already exists in the selected category"
            )
        except sqlite3.Error as e:
            QMessageBox.critical(self, "Database Error", f"Error saving bookmark: {e}")
    def _get_db_connection(self):
        """Get a database connection with safe handling"""
        try:
            conn = sqlite3.connect("bookmarks.db")
            conn.execute("PRAGMA foreign_keys = ON")
            return conn
        except sqlite3.Error as e:
            QMessageBox.critical(
                self, "Database Error", f"Could not connect to database: {e}"
            )
            return None
    def toggle_devtools(self):
        """Toggle DevTools visibility"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            if self.devtools_dock.isVisible():
                self.devtools_dock.hide()
            else:
                self.devtools_dock.set_browser(current_browser)
                self.devtools_dock.show()
                # Ajustar el tamaño del dock widget
                self.devtools_dock.setMinimumWidth(400)
                self.devtools_dock.setMinimumHeight(300)
    def toggle_download_panel(self):
        """Toggle Download Panel visibility (Ctrl+J)"""
        if hasattr(self, "download_dock") and self.download_dock:
            if self.download_dock.isVisible():
                self.download_dock.hide()
            else:
                self.download_dock.show()
                # Ajustar tamaño mínimo
                self.download_dock.setMinimumWidth(400)
                self.download_dock.setMinimumHeight(300)
    def take_screenshot(self):
        """Capturar screenshot de la página actual (Ctrl+Shift+S)"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            # Crear herramienta de screenshot para el browser actual
            screenshot_tool = ScreenshotTool(current_browser, self)
            screenshot_tool.show_screenshot_dialog()
        else:
            QMessageBox.warning(
                self, "Sin página activa", "No hay ninguna página activa para capturar."
            )
    def reload_with_new_profile(self):
        """Recargar el navegador con el nuevo perfil activo"""
        try:
            # Cerrar todas las pestañas
            while self.tab_manager.tabs.count() > 0:
                self.tab_manager.tabs.removeTab(0)
            # Limpiar historial de navegación en memoria
            if hasattr(self, "navigation_manager"):
                self.navigation_manager.history.clear()
            # Crear nueva pestaña vacía
            self.tab_manager.add_new_tab()

            # Actualizar UI con el nuevo perfil
            if hasattr(self, "profile_switcher"):
                self.profile_switcher.update_current_profile()
            # Mostrar mensaje
            profile = self.profile_manager.get_current_profile()
            if profile:
                self.status_bar.update_status(
                    f"Cambiado a perfil: {profile['name']}"
                )
            print(
                f"[OK] Browser reloaded with profile: {self.profile_manager.current_profile_id}"
            )
        except Exception as e:
            print(f"[ERROR] Error reloading with new profile: {e}")
            QMessageBox.critical(
                self,
                "Error al cambiar perfil",
                f"Ocurrió un error al cambiar de perfil:\n{str(e)}",
            )
    def toggle_scraping_panel(self):
        """Alterna la visibilidad del panel de scraping USANDO EL STACK FIJO"""
        # Verificar si el plugin está disponible estáticamente O dinámicamente cargado
        plugin_available = SCRAPING_AVAILABLE or (
            hasattr(self, "plugin_manager")
            and self.plugin_manager
            and self.plugin_manager.is_plugin_installed("scraping")
        )

        # Si el plugin está disponible pero el panel no existe, reutilizar el pipeline
        # real de carga dinámica (on_plugin_loaded -> _load_scraping_plugin_dynamic)
        # en vez de reconstruir el panel a mano aquí (antes se pasaba `self` como
        # scraping_integration por error, y el kwarg plugin_validator no existía).
        if plugin_available and (
            not hasattr(self, "scraping_panel") or not self.scraping_panel
        ):
            try:
                if self.plugin_manager and "scraping" not in self.plugin_manager.plugins:
                    self.plugin_manager.load_plugin("scraping")
                if self.plugin_manager and "scraping" in self.plugin_manager.plugins:
                    self.on_plugin_loaded("scraping")
                if not hasattr(self, "scraping_panel") or not self.scraping_panel:
                    plugin_available = False
                elif self.advanced_panel_stack.indexOf(self.scraping_panel) < 0:
                    self.advanced_panel_stack.addWidget(self.scraping_panel)
                print("[OK] Scraping panel loaded dynamically")
            except Exception as e:
                print(f"[ERROR] Failed to load scraping panel dynamically: {e}")
                plugin_available = False
        if plugin_available and hasattr(self, "scraping_panel") and self.scraping_panel:
            if (
                self.advanced_panel_stack.currentWidget() == self.scraping_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                # Actualizar el contenido antes de mostrar
                self.update_scraping_content()
                self.show_advanced_panel(self.scraping_panel)

                # Activar automáticamente la selección interactiva si hay un navegador activo
                current_browser = self.tab_manager.tabs.currentWidget()
                if current_browser and hasattr(self.scraping_panel, "browser_tab"):
                    self.scraping_panel.browser_tab = current_browser
        else:
            QMessageBox.information(
                self,
                "Premium Feature",
                "Advanced Scraping is a premium feature.\n"
                "Please install the Advanced Scraping plugin to use this functionality.",
            )
    def _restart_with_tor(self, enabled: bool):
        """Callback para reiniciar con Tor activado/desactivado."""
        from main import restart_with_tor
        restart_with_tor(enabled, self)
    def toggle_tor_panel(self):
        """Toggle Tor panel visibility USING FIXED STACK"""
        if hasattr(self, "tor_panel") and self.tor_panel:
            if (
                self.advanced_panel_stack.currentWidget() == self.tor_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.tor_panel)
                if TOR_AVAILABLE and hasattr(self, "network_interceptor") and self.network_interceptor:
                    from config_manager import config
                    self.network_interceptor.tor_mode = config.is_tor_enabled()
        else:
            QMessageBox.information(
                self,
                "Tor",
                "Tor no está disponible.\n\n"
                "Instale: pip install stem\n"
                "Y asegúrese de tener el binario 'tor' en su sistema.",
            )
    def toggle_proxy_panel(self):
        """Toggle proxy management panel visibility USING FIXED STACK"""
        if PROXY_AVAILABLE and hasattr(self, "proxy_panel") and self.proxy_panel:
            if (
                self.advanced_panel_stack.currentWidget() == self.proxy_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                # Actualizar la lista de proxies si es necesario
                if hasattr(self.proxy_panel, "refresh_proxy_list"):
                    self.proxy_panel.refresh_proxy_list()
                self.show_advanced_panel(self.proxy_panel)
        else:
            QMessageBox.information(
                self,
                "Premium Feature",
                "Proxy Management is a premium feature.\n"
                "Please install the Proxy Management plugin to use this functionality.",
            )
    def toggle_pentesting_panel(self):
        """Toggle Pentesting Suite panel visibility USING FIXED STACK"""
        panel = getattr(self, "pentesting_panel", None)

        # Pentesting Suite es premium: sin licencia no se crea el panel, aunque
        # los ficheros del plugin estén instalados en la carpeta de usuario.
        if panel is None and not (
            self.plugin_manager and self.plugin_manager.can_load_plugin("pentesting_tool")
        ):
            QMessageBox.information(
                self,
                "Plugin premium",
                "Pentesting Suite es un plugin premium.\n"
                "Inicia sesión con una cuenta con licencia e instálalo desde la tienda de plugins.",
            )
            return
        # Crear el panel directamente desde el módulo del plugin si aún no existe
        if panel is None:
            try:
                # Agregar directorio del plugin al path para que pueda importar core.payloads
                import sys
                from pathlib import Path

                _pt_base = find_plugin_dir("pentesting_tool") or (
                    BUNDLED_PLUGINS_DIR / "pentesting_tool"
                )
                plugin_dir = _pt_base / "pentesting_tool"
                for _p in (str(_pt_base), str(plugin_dir)):
                    if _p not in sys.path:
                        sys.path.insert(0, _p)
                from plugins.pentesting_tool.pentesting_tool.ui.panel import (
                    PentestingPanel as PentestingPanelClass,
                )

                print(
                    "[UI] Creating Pentesting panel from plugins.pentesting_tool.ui.panel"
                )
                self.pentesting_panel = PentestingPanelClass(parent=self)
                panel = self.pentesting_panel
                # Registrar en el stack avanzado si aún no está
                if hasattr(self, "advanced_panel_stack"):
                    if self.advanced_panel_stack.indexOf(panel) < 0:
                        self.advanced_panel_stack.addWidget(panel)
            except Exception as e:
                error_msg = f"[UI] Error creating Pentesting panel: {e}"
                print(error_msg)
                # Escribir a archivo para depuración
                import traceback

                with open("pentesting_debug.log", "a") as f:
                    f.write(f"{error_msg}\n")
                    f.write(traceback.format_exc())
                panel = None
        if panel is None:
            QMessageBox.information(
                self,
                "Pentesting Suite",
                "El panel de Pentesting no está disponible.\n"
                "Asegúrate de tener instalado y activado el plugin Pentesting Suite.",
            )
            print("[UI] Pentesting panel not available or plugin not loaded")
            return
        if (
            self.advanced_panel_stack.currentWidget() == panel
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(panel)
    def toggle_plugin_store(self):
        """Toggle plugin store panel visibility"""
        if hasattr(self, "plugin_store_dock") and self.plugin_store_dock:
            if self.plugin_store_dock.isVisible():
                self.plugin_store_dock.hide()
            else:
                self.plugin_store_dock.show()
                # Refresh the plugin list when opening the store
                if hasattr(self, "unified_plugin_panel") and self.unified_plugin_panel:
                    self.unified_plugin_panel.load_available_plugins()
        else:
            QMessageBox.information(
                self,
                "Plugin Store",
                "The Plugin Store is not available.\n"
                "Please ensure you are logged in to access the plugin store.",
            )
    def toggle_chat_panel(self):
        """Toggle AI chat panel visibility USING FIXED STACK"""
        # El Asistente de IA es gratuito e incluido en el navegador: no requiere
        # login ni licencia (ver entrada "ai_assistant" en unified_plugin_manager.py,
        # registrada como free_features=["chat_access"]).
        # Lazy-load del panel para evitar que desaparezca el botón si hubo fallo temporal al importar
        if (not hasattr(self, "chat_panel")) or self.chat_panel is None:
            try:
                from chat_panel_safe import ChatPanelSafe as LazyChatPanel

                self.chat_panel = LazyChatPanel()
                if hasattr(self.chat_panel, "gentab_requested"):
                    self.chat_panel.gentab_requested.connect(
                        self._on_gentab_from_navbar
                    )
            except Exception as e:
                self.chat_panel = None
                print(f"[ERROR] Failed to lazy-load AI chat panel: {e}")
        if hasattr(self, "chat_panel") and self.chat_panel:
            if (
                self.advanced_panel_stack.currentWidget() == self.chat_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.chat_panel)
        else:
            QMessageBox.information(
                self,
                "AI Chat",
                "AI chat tools are not available. Verify that chat_panel_safe.py is present and valid.",
            )
    def toggle_log_viewer(self):
        """Toggle Log Viewer panel visibility."""
        if not hasattr(self, "log_viewer_panel") or self.log_viewer_panel is None:
            try:
                from log_viewer_panel import LogViewerPanel

                self.log_viewer_panel = LogViewerPanel()
            except Exception as exc:
                import logging as _lg

                _lg.getLogger(__name__).error("Error cargando Log Viewer: %s", exc)
                QMessageBox.information(
                    self,
                    "Log Viewer",
                    "El visor de logs no está disponible.\n"
                    f"Revisa el fichero katphi_browser.log manualmente.\n\nError: {exc}",
                )
                return
        panel = self.log_viewer_panel
        if (
            self.advanced_panel_stack.currentWidget() == panel
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(panel)
    def toggle_gentab_panel(self):
        """Toggle GenTab panel visibility USING FIXED STACK"""
        # Lazy-load del panel de navegación para evitar pérdida del módulo por errores de carga tempranos
        if (not hasattr(self, "gentab_panel")) or self.gentab_panel is None:
            try:
                from gentab_panel import GenTabPanel as LazyGenTabPanel

                self.gentab_panel = LazyGenTabPanel(self)
                self.gentab_panel.gentab_created.connect(self._open_gentab_in_new_tab)
            except Exception as e:
                self.gentab_panel = None
                print(f"[ERROR] Failed to lazy-load GenTab panel: {e}")
        if hasattr(self, "gentab_panel") and self.gentab_panel:
            if (
                self.advanced_panel_stack.currentWidget() == self.gentab_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.gentab_panel)
        else:
            QMessageBox.information(
                self,
                "GenTab",
                "GenTab no está disponible.\n"
                "Verifica que gentab_panel.py y gentab_engine.py estén presentes.",
            )
    def _open_gentab_in_new_tab(self, title: str, html_content: str):
        """Abre una GenTab generada en una nueva pestaña del navegador."""
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtCore import QUrl

            if not html_content or len(html_content.strip()) < 80:
                print(
                    f"[GenTab] Empty/invalid HTML received for '{title}' (len={len(html_content or '')})"
                )
                QMessageBox.warning(
                    self,
                    "GenTab",
                    "La IA devolvió contenido vacío o inválido. Revisa el contexto de pestañas e inténtalo de nuevo.",
                )
                return
            browser = QWebEngineView()

            profile = browser.page().profile()
            if hasattr(self, "network_interceptor") and self.network_interceptor:
                try:
                    user_agent = self.network_interceptor._get_user_agent()
                    profile.setHttpUserAgent(user_agent)
                except Exception:
                    pass
            base_url = QUrl("https://gentab.local/")
            browser.setHtml(html_content, base_url)
            browser.loadFinished.connect(
                lambda ok, t=title: print(f"[GenTab] loadFinished title='{t}' ok={ok}")
            )

            display_title = f"{title}" if len(title) <= 28 else f"{title[:25]}..."
            index = self.tab_manager.tabs.addTab(browser, display_title)
            self.tab_manager.tabs.setCurrentIndex(index)

            if hasattr(self, "url_bar"):
                self.url_bar.setText(f"gentab://{title.lower().replace(' ', '-')}")
            self.setWindowTitle(f"{title} - Katphi GenTab")
            print(f"[GenTab] Opened GenTab: {title} | html_len={len(html_content)}")
        except Exception as e:
            print(f"[GenTab] Error opening GenTab: {e}")
            QMessageBox.warning(self, "GenTab", f"Error al abrir GenTab: {str(e)}")
    def toggle_tab_groups_panel(self):
        """Toggle Tab Groups panel visibility USING FIXED STACK"""
        if hasattr(self, "tab_groups_panel") and self.tab_groups_panel:
            if (
                self.advanced_panel_stack.currentWidget() == self.tab_groups_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.tab_groups_panel)
        else:
            QMessageBox.information(
                self, "Tab Groups", "Tab Groups panel is not available."
            )
    def toggle_history_panel(self):
        """Toggle History panel visibility using MAIN SIDEBAR STACK"""
        if not hasattr(self, "history_panel"):
            # Lazy loading if not initialized
            try:
                from history import HistoryPanel

                self.history_panel = HistoryPanel(
                    self.history_manager, self.tab_manager
                )
            except ImportError:
                print("Error importing HistoryPanel")
                return
        # Use helper method
        if (
            self.advanced_panel_stack.currentWidget() == self.history_panel
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(self.history_panel)
    def toggle_download_panel(self):
        """Toggle Download panel visibility using MAIN SIDEBAR STACK"""
        if not hasattr(self, "download_panel"):
            return
        # Use helper method
        if (
            self.advanced_panel_stack.currentWidget() == self.download_panel
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(self.download_panel)
    def _ensure_pentesting_panel_loaded(self):
        """
        Asegura que el panel de Pentesting esté creado y registrado.
        Intenta cargar el plugin dinámicamente si aún no está disponible.
        """
        # Mantener función por compatibilidad; la creación directa se hace en toggle_pentesting_panel
        if hasattr(self, "pentesting_panel") and self.pentesting_panel:
            return self.pentesting_panel
        return None
    def toggle_password_manager(self):
        """Toggle Password Manager visibility using MAIN SIDEBAR STACK"""
        if not hasattr(self, "password_manager") or not self.password_manager:
            return
        # Use helper method
        if (
            self.advanced_panel_stack.currentWidget() == self.password_manager
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(self.password_manager)
    def toggle_bookmark_manager(self):
        """
        Toggle Bookmark Manager visibility using MAIN SIDEBAR STACK.
        Usa el nuevo panel jerárquico de carpetas si está disponible.
        """
        panel = getattr(self, "bookmark_panel_widget", None) or getattr(self, "bookmark_manager", None)
        if not panel:
            return
        if (
            self.advanced_panel_stack.currentWidget() == panel
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(panel)
            if hasattr(panel, "reload"):
                panel.reload()
    # toggle_seo_panel method removed - SEO Analyzer is now a downloadable plugin
    # and will be managed by UnifiedPluginManager

    def toggle_plugin_panel(self):
        """Toggle plugin management panel visibility USING FIXED STACK"""
        if (
            PLUGIN_SYSTEM_AVAILABLE
            and hasattr(self, "unified_plugin_panel")
            and self.unified_plugin_panel
        ):
            if (
                self.advanced_panel_stack.currentWidget() == self.unified_plugin_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.unified_plugin_panel)
        else:
            QMessageBox.information(
                self,
                "Plugins",
                "Plugin system is not available.\n"
                "Verify that:\n"
                "• Authentication system is working\n"
                "• Plugin files are present\n"
                "• You are connected to the backend",
            )
    def toggle_auth_panel(self):
        """Toggle authentication panel visibility USING FIXED STACK"""
        if AUTH_SYSTEM_AVAILABLE and hasattr(self, "auth_panel") and self.auth_panel:
            if (
                self.advanced_panel_stack.currentWidget() == self.auth_panel
                and self.advanced_panel_stack.isVisible()
            ):
                self.hide_advanced_panel()
            else:
                self.show_advanced_panel(self.auth_panel)
        else:
            QMessageBox.information(
                self, "Autenticación", "Sistema de autenticación no disponible."
            )
    def update_scraping_content(self):
        """Update the content of the current page in the scraping integration"""
        if SCRAPING_AVAILABLE and self.scraping_integration:
            current_browser = self.tab_manager.tabs.currentWidget()
            if current_browser:
                # Obtener la URL actual
                current_url = current_browser.url().toString()

                # Actualizar el widget del navegador en el scraping integration
                self.scraping_integration.browser_widget = current_browser

                # La selección interactiva se maneja desde el scraping_panel

                # Obtener el HTML de la página actual
                current_browser.page().toHtml(
                    lambda html_content: self.on_html_loaded(html_content, current_url)
                )

                # Actualizar el panel de scraping si está visible
                if hasattr(self, "scraping_panel") and self.scraping_panel:
                    self.scraping_panel.browser_tab = current_browser
    # La selección interactiva se maneja desde scraping_panel.py

    def handle_element_click(self, click_data):
        """Handle click on page element"""
        try:
            if SCRAPING_AVAILABLE and hasattr(self, "scraping_panel"):
                x = click_data.get("x", 0)
                y = click_data.get("y", 0)
                self.scraping_panel.handle_page_click(x, y)
        except Exception as e:
            print(f"Error manejando clic en elemento: {e}")
    def on_html_loaded(self, html_content, url):
        """Callback when page HTML is loaded"""
        if SCRAPING_AVAILABLE and self.scraping_integration:
            self.scraping_integration.update_content(html_content, url)
        # AI Navigation: indexar contenido de la pestaña
        if self.ai_nav_enabled and self.context_store and html_content:
            self._ai_index_page(html_content, url)
    # ── AI Navigation slots ──────────────────────────────────────────────────

    def _ai_index_page(self, html_content: str, url: str) -> None:
        """Indexa el HTML de una página en el vector store en segundo plano."""
        if not self.ai_nav_enabled or not self.context_store:
            return
        # Respetar privacidad
        if hasattr(self, "privacy_manager"):
            pm = self.privacy_manager
            if hasattr(pm, "is_tracking_blocked") and pm.is_tracking_blocked():
                return
        try:
            import hashlib

            tab_id = hashlib.md5(url.encode()).hexdigest()[:12]
            current = self.tab_manager.tabs.currentWidget()
            title = current.title() if current else ""
            worker = IndexWorker(self.context_store, tab_id, url, title, html_content)
            worker.indexing_done.connect(lambda tid: self._ai_schedule_analysis())
            self._index_workers.append(worker)
            worker.finished.connect(lambda: self._ai_cleanup_worker(worker))
            worker.start()
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("AI index error: %s", e)
    def _ai_cleanup_worker(self, worker) -> None:
        """Elimina referencia al worker finalizado."""
        try:
            self._index_workers.remove(worker)
        except ValueError:
            pass
    def _ai_on_tab_changed(self, index: int) -> None:
        """Cuando cambia la pestaña activa, programa un análisis."""
        if self.ai_nav_enabled:
            self._ai_schedule_analysis()
    def _ai_schedule_analysis(self) -> None:
        """Programa el análisis de sesión con un delay para no saturar."""
        if hasattr(self, "_ai_analysis_timer") and self._ai_analysis_timer:
            self._ai_analysis_timer.start()
    def _ai_run_analysis(self) -> None:
        """Ejecuta el análisis de sesión y muestra sugerencias si procede."""
        if not self.ai_nav_enabled or not self.session_analyzer:
            return
        try:
            analysis = self.session_analyzer.analyze_current_session(self.tab_manager)
            if not analysis or analysis.get("confidence", 0) < 0.5:
                return
            if self.suggestion_engine:
                suggestions = self.suggestion_engine.generate_suggestions(analysis)
                if suggestions and self.suggestion_toast:
                    self.suggestion_toast.show_suggestion(suggestions[0])
            # Actualizar placeholder de la barra conversacional
            action = analysis.get("suggested_action", "")
            if action and isinstance(self.url_bar, ConversationalNavBar):
                self.url_bar.set_placeholder_with_suggestion(
                    f"{action} — o escribe tu búsqueda..."
                )
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("AI analysis error: %s", e)
    def _on_suggestion_accepted(self, suggestion) -> None:
        """Sugerencia aceptada — abre el chat con la acción sugerida."""
        if not self.suggestion_engine:
            return
        try:
            stype = suggestion.type if hasattr(suggestion, "type") else None
            if stype:
                self.suggestion_engine.record_acceptance(stype)
            payload = (
                suggestion.action_payload
                if hasattr(suggestion, "action_payload")
                else {}
            )
            action = payload.get("action", "")
            intent = payload.get("intent", "")

            chat = getattr(self, "chat_panel", None)
            if chat:
                self.show_advanced_panel(chat)
                if action in (
                    "gentab",
                    "summarize",
                    "compare",
                    "document",
                    "briefing",
                    "itinerary",
                    "playlist",
                ):
                    prompt_map = {
                        "summarize": "Resume el contenido de todas mis pestañas abiertas con los puntos clave.",
                        "compare": "Compara los productos/contenidos de todas mis pestañas en una tabla interactiva.",
                        "document": "Genera documentación técnica a partir del contenido de mis pestañas de código.",
                        "briefing": "Crea un briefing de noticias con las pestañas que tengo abiertas.",
                        "itinerary": "Crea un itinerario de viaje interactivo basado en mis pestañas de viajes.",
                        "playlist": "Organiza mi contenido de entretenimiento en una lista.",
                        "gentab": "Genera una aplicación interactiva con el contenido de mis pestañas.",
                    }
                    p = prompt_map.get(
                        action,
                        suggestion.description
                        if hasattr(suggestion, "description")
                        else "",
                    )
                    if p:
                        if action == "gentab" or action in ("compare", "itinerary"):
                            chat.set_prompt(p)
                        else:
                            chat.set_input_text(p)
                            mode_map = {
                                "summarize": "Resumen pestañas abiertas",
                                "briefing": "Analizar sesión",
                                "document": "Analizar sesión",
                                "playlist": "Resumen pestañas abiertas",
                            }
                            target_mode = mode_map.get(action, "Analizar sesión")
                            if hasattr(chat, "assistant_mode"):
                                idx = chat.assistant_mode.findText(target_mode)
                                if idx >= 0:
                                    chat.assistant_mode.setCurrentIndex(idx)
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("Suggestion acceptance error: %s", e)
    def _on_suggestion_dismissed(self, suggestion) -> None:
        """Procesa el descarte de una sugerencia."""
        if self.suggestion_engine and hasattr(suggestion, "type"):
            self.suggestion_engine.record_dismissal(suggestion.type)
    def _on_ai_query(self, query: str) -> None:
        """Query en lenguaje natural desde la barra conversacional → chat."""
        chat = getattr(self, "chat_panel", None)
        if chat:
            self.show_advanced_panel(chat)
            chat.set_input_text(query)
        else:
            self.load_url(query)
    def _on_gentab_from_navbar(self, prompt: str) -> None:
        """Solicitud de GenTab desde la barra o el chat → abre GenTab panel."""
        if hasattr(self, "gentab_panel") and self.gentab_panel:
            self.show_advanced_panel(self.gentab_panel)
            if prompt and hasattr(self.gentab_panel, "prompt_input"):
                self.gentab_panel.prompt_input.setPlainText(prompt)
        else:
            chat = getattr(self, "chat_panel", None)
            if chat:
                self.show_advanced_panel(chat)
                chat.set_prompt(prompt)
    def toggle_favorites_bar(self):
        """Alterna la visibilidad de la barra de favoritos"""
        if hasattr(self, "favorites_bar"):
            if self.favorites_bar.isVisible():
                self.favorites_bar.hide()
                self.statusBar().showMessage("Barra de favoritos oculta", 3000)
            else:
                self.favorites_bar.show()
                self.update_favorites_bar()   # Carga con carpetas si están disponibles
                self.statusBar().showMessage("Barra de favoritos visible", 3000)
        else:
            QMessageBox.information(
                self, "Favorites Bar", "The favorites bar is not available."
            )
    def update_favorites_bar(self):
        """
        Actualiza la barra de favoritos.

        Si el sistema de carpetas está disponible, usa load_with_folders() para
        mostrar carpetas como submenús; de lo contrario, usa refresh_favorites().
        """
        if not hasattr(self, "favorites_bar"):
            return
        fm = getattr(self, "folders_manager", None)
        if fm:
            self.favorites_bar.load_with_folders(fm)
        else:
            self.favorites_bar.refresh_favorites()
    def _on_bookmarks_data_changed(self):
        """Callback cuando el panel de marcadores modifica datos — refresca la barra."""
        self.update_favorites_bar()
    # ── Acciones de marcadores desde el menú hamburguesa ──────────────────────

    def _hamburger_new_folder(self):
        """Crea una nueva carpeta de marcadores (desde el menú hamburguesa)."""
        fm = getattr(self, "folders_manager", None)
        bpw = getattr(self, "bookmark_panel_widget", None)
        if not fm:
            QMessageBox.information(self, "Marcadores", "El sistema de carpetas no está disponible.")
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
        if ok and name.strip():
            try:
                fm.create_folder(name.strip())
                self.update_favorites_bar()
                if bpw:
                    bpw.reload()
                self.statusBar().showMessage(f"Carpeta '{name.strip()}' creada", 3000)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"No se pudo crear la carpeta:\n{e}")
    def _hamburger_export_bookmarks(self):
        """Exporta los marcadores a HTML (desde el menú hamburguesa)."""
        bm = getattr(self, "bookmark_manager", None)
        fm = getattr(self, "folders_manager", None)
        if not bm or not fm:
            QMessageBox.information(self, "Exportar", "El sistema de carpetas no está disponible.")
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar marcadores", "bookmarks.html", "HTML (*.html)"
        )
        if path:
            if bm.export_bookmarks_html(path, fm):
                QMessageBox.information(self, "Exportado", f"Marcadores exportados a:\n{path}")
            else:
                QMessageBox.critical(self, "Error", "No se pudieron exportar los marcadores.")
    def reapply_privacy_to_all_tabs(self):
        """Apply privacy settings to all open tabs"""
        try:
            if not (
                hasattr(self, "tab_manager")
                and self.tab_manager
                and hasattr(self, "privacy_manager")
            ):
                print("Tab manager o privacy manager no disponibles")
                return
            # Obtener todas las pestañas
            tabs_count = self.tab_manager.tabs.count()
            if tabs_count == 0:
                print("No open tabs")
                return
            # Variables para controlar recarga
            needs_reload = False

            # Verificar si cambios críticos requieren recarga
            current_block_ads = self.privacy_manager.settings.get_setting("block_ads")
            current_block_third_party = self.privacy_manager.settings.get_setting(
                "block_third_party"
            )
            current_block_javascript = self.privacy_manager.settings.get_setting(
                "block_javascript"
            )

            # Inicializar estados previos si no existen
            if not hasattr(self, "_last_privacy_settings"):
                self._last_privacy_settings = {
                    "block_ads": current_block_ads,
                    "block_third_party": current_block_third_party,
                    "block_javascript": current_block_javascript,
                }
            else:
                # Verificar si hubo cambios que requieren recarga
                if (
                    self._last_privacy_settings["block_ads"] != current_block_ads
                    or self._last_privacy_settings["block_third_party"]
                    != current_block_third_party
                ):
                    needs_reload = True
                    print("Detectados cambios en filtros de red - programando recarga")
                # Actualizar estados guardados
                self._last_privacy_settings.update(
                    {
                        "block_ads": current_block_ads,
                        "block_third_party": current_block_third_party,
                        "block_javascript": current_block_javascript,
                    }
                )
            # Aplicar configuración a cada pestaña
            successful_applications = 0
            failed_applications = 0

            for i in range(tabs_count):
                try:
                    tab = self.tab_manager.tabs.widget(i)
                    if tab and hasattr(tab, "page"):
                        # Aplicar configuración de privacidad
                        self.privacy_manager.apply_privacy_settings(tab)
                        successful_applications += 1

                        # Recarga suave si es necesario para cambios de filtros de red
                        if needs_reload:
                            try:
                                # Solo recargar si la pestaña tiene contenido
                                current_url = tab.url()
                                if (
                                    not current_url.isEmpty()
                                    and current_url.toString() != "about:blank"
                                ):
                                    tab.reload()
                                    print(
                                        f"Tab {i + 1} reloaded: {current_url.toString()[:50]}..."
                                    )
                            except Exception as reload_error:
                                print(f"Error reloading tab {i + 1}: {reload_error}")
                except Exception as tab_error:
                    print(f"Error applying privacy to tab {i + 1}: {tab_error}")
                    failed_applications += 1
            # Reporte de resultados
            print(
                f"Privacy settings applied: {successful_applications}/{tabs_count} successful tabs"
            )
            if failed_applications > 0:
                print(f"Errors in {failed_applications} tabs")
            if needs_reload:
                print("Tabs with content reloaded to apply network filters")
            try:
                self.privacy_manager.sync_default_webengine_profile()
            except Exception as sync_err:
                print(f"[WARNING] sync_default_webengine_profile: {sync_err}")
        except Exception as e:
            print(f"Critical error reapplying privacy settings: {e}")
            import traceback

            traceback.print_exc()
    def toggle_maximize(self):
        """Alternar entre maximizado y restaurado"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
    def show_main_menu(self):
        """Mostrar menú principal del navegador (estilo Chromium)"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #ccc;
                padding: 5px 0px;
                min-width: 280px;
            }
            QMenu::item {
                padding: 8px 35px 8px 25px;
                color: #333;
            }
            QMenu::item:selected {
                background-color: #e8eaed;
            }
            QMenu::separator {
                height: 1px;
                background: #e0e0e0;
                margin: 5px 10px;
            }
            QMenu::icon {
                margin-left: 8px;
            }
        """)

        # === Sección 1: Pestañas y Ventanas ===
        new_tab_action = menu.addAction("Nueva pestaña")
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(lambda: self.tab_manager.add_new_tab())

        new_window_action = menu.addAction("Nueva ventana")
        new_window_action.setShortcut("Ctrl+N")
        new_window_action.triggered.connect(self.open_new_window)

        private_window_action = menu.addAction("Nueva ventana privada")
        private_window_action.setShortcut("Ctrl+Shift+P")
        private_window_action.triggered.connect(self.open_private_window)

        menu.addSeparator()

        # === Sección 1.5: Gestión de sesiones ===
        session_menu = menu.addMenu("Sesiones")
        session_menu.addAction("Guardar sesión actual...").triggered.connect(
            self.save_current_session
        )
        session_menu.addAction("Restaurar sesión...").triggered.connect(
            self.show_session_manager
        )

        menu.addSeparator()

        # === Sección 2: Gestión de contenido ===
        bookmarks_menu = menu.addMenu("Marcadores")

        bookmarks_menu.addAction("Abrir panel de marcadores").triggered.connect(
            self.toggle_bookmark_manager
        )

        bookmarks_menu.addAction("Guardar esta página…").triggered.connect(
            self.show_save_favorite_menu
        )

        bookmarks_menu.addSeparator()

        bookmarks_menu.addAction("Nueva carpeta…").triggered.connect(
            self._hamburger_new_folder
        )

        bookmarks_menu.addAction("Exportar marcadores…").triggered.connect(
            self._hamburger_export_bookmarks
        )

        bookmarks_menu.addSeparator()

        bookmarks_menu.addAction("Mostrar / ocultar barra de favoritos").triggered.connect(
            self.toggle_favorites_bar
        )

        history_action = menu.addAction("Historial")
        history_action.triggered.connect(self.toggle_history_panel)

        downloads_action = menu.addAction("Descargas")
        downloads_action.setShortcut("Ctrl+Shift+Y")
        downloads_action.triggered.connect(self.toggle_download_panel)

        passwords_action = menu.addAction("Contraseñas")
        passwords_action.triggered.connect(self.toggle_password_manager)

        extensions_action = menu.addAction("Extensiones y temas")
        extensions_action.setShortcut("Ctrl+Shift+A")
        # Fix: Ensure plugin store toggle works or falls back to basic panel
        extensions_action.triggered.connect(
            self.toggle_plugin_store
            if hasattr(self, "toggle_plugin_store")
            else self.show_plugins_panel
        )

        menu.addSeparator()

        # === Sección 3: Herramientas de página ===
        print_action = menu.addAction("Imprimir...")
        print_action.setShortcut("Ctrl+P")
        print_action.triggered.connect(self.print_page)

        save_action = menu.addAction("Guardar como...")
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_page_as)

        find_action = menu.addAction("Buscar en la página...")
        find_action.setShortcut("Ctrl+F")
        find_action.triggered.connect(self.show_find_dialog)

        menu.addSeparator()

        # === Sección 4: Zoom ===
        zoom_menu = menu.addMenu("Tamaño")

        zoom_in_action = zoom_menu.addAction("Aumentar")
        zoom_in_action.setShortcut("Ctrl++")
        zoom_in_action.triggered.connect(self.zoom_in)

        zoom_out_action = zoom_menu.addAction("Reducir")
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(self.zoom_out)

        zoom_reset_action = zoom_menu.addAction("Restablecer")
        zoom_reset_action.setShortcut("Ctrl+0")
        zoom_reset_action.triggered.connect(self.zoom_reset)

        zoom_menu.addSeparator()

        fullscreen_action = zoom_menu.addAction("Pantalla completa")
        fullscreen_action.setShortcut("F11")
        fullscreen_action.triggered.connect(self.toggle_fullscreen)

        menu.addSeparator()

        # === Sección 5: Más herramientas ===
        tools_menu = menu.addMenu("Más herramientas")

        tools_menu.addAction("Limpiar datos de navegación...").triggered.connect(
            self.show_clear_data_dialog
        )
        tools_menu.addAction("Configuración de red...").triggered.connect(
            self.show_network_settings
        )
        tools_menu.addAction("UserScripts...").triggered.connect(self.show_userscripts)

        # Submenú de temas modernos - AUDITED & FIXED
        themes_menu = tools_menu.addMenu("Cambiar tema visual")
        # Use simple string identifiers for the theme manager
        themes_menu.addAction("Tema Claro (Light)").triggered.connect(
            lambda: self.apply_theme("light")
        )
        themes_menu.addAction("Tema Oscuro (Dark)").triggered.connect(
            lambda: self.apply_theme("dark")
        )
        # themes_menu.addAction("Tema Azul (Blue)").triggered.connect(
        #     lambda: self.apply_theme('blue'))

        tools_menu.addAction("Herramientas de desarrollador").setShortcut("F12")
        tools_menu.actions()[-1].triggered.connect(self.toggle_dev_tools)
        tools_menu.addAction("Administrador de tareas").triggered.connect(
            self.show_performance_monitor
        )
        tools_menu.addAction("Diagnóstico de rendimiento").triggered.connect(
            self.run_performance_diagnostic
        )
        tools_menu.addAction("Ver código fuente").setShortcut("Ctrl+U")
        tools_menu.actions()[-1].triggered.connect(self.view_page_source)

        menu.addSeparator()

        # === Sección 6: Configuración y ayuda ===
        settings_menu = menu.addMenu("Ajustes")
        prefs_action = settings_menu.addAction("Preferencias…")
        prefs_action.triggered.connect(self.show_settings)
        settings_menu.addSeparator()
        ff_action = settings_menu.addAction("Ventana sin marco del sistema")
        ff_action.setCheckable(True)
        ff_action.setChecked(
            bool(self.windowFlags() & Qt.WindowType.FramelessWindowHint)
        )
        ff_action.triggered.connect(
            lambda c: self._set_frameless_window(bool(c), persist=True)
        )

        help_menu = menu.addMenu("Ayuda")
        help_menu.addAction("Acerca de Katphi").triggered.connect(self.show_about)
        help_menu.addAction("Documentación").triggered.connect(
            lambda: self.tab_manager.add_new_tab("https://katphi.com")
        )
        help_menu.addAction("Informar de un problema").triggered.connect(
            self.report_issue
        )

        menu.addSeparator()

        # === Sección 7: Perfiles de usuario ===
        profiles_menu = menu.addMenu("Perfiles")
        try:
            if hasattr(self, "profile_manager") and self.profile_manager:
                profiles     = self.profile_manager.get_all_profiles()
                current_id   = self.profile_manager.current_profile_id

                for profile in profiles:
                    pid   = profile["id"]
                    name  = profile.get("name", pid)
                    label = name + ("  ✓" if pid == current_id else "")
                    act   = profiles_menu.addAction(label)
                    act.triggered.connect(
                        lambda checked=False, p=pid: self._switch_profile_from_menu(p)
                    )

                profiles_menu.addSeparator()
                profiles_menu.addAction("Nuevo perfil…").triggered.connect(
                    self._create_profile_from_menu
                )
                profiles_menu.addAction("Gestionar perfiles…").triggered.connect(
                    self._manage_profiles_from_menu
                )
            else:
                profiles_menu.addAction("Gestor de perfiles no disponible").setEnabled(False)
        except Exception as e:
            profiles_menu.addAction(f"Error: {e}").setEnabled(False)

        menu.addSeparator()

        # === Sección 8: Salir ===
        exit_action = menu.addAction("Salir")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)

        # Mostrar el menú justo debajo del botón
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def _switch_profile_from_menu(self, profile_id: str):
        """Cambia al perfil indicado desde el menú hamburguesa."""
        try:
            if hasattr(self, "profile_manager") and self.profile_manager:
                self.profile_manager.switch_profile(profile_id)
                if hasattr(self, "profile_switcher"):
                    self.profile_switcher.update_current_profile()
        except Exception as e:
            print(f"[PROFILE] Error switching profile: {e}")

    def _create_profile_from_menu(self):
        """Abre el diálogo de creación de perfil."""
        try:
            from profile_manager import ProfileDialog
            dialog = ProfileDialog(None, self.profile_manager, self)
            if dialog.exec():
                if hasattr(self, "profile_switcher"):
                    self.profile_switcher.update_current_profile()
        except Exception as e:
            print(f"[PROFILE] Error opening profile dialog: {e}")

    def _manage_profiles_from_menu(self):
        """Abre el gestor completo de perfiles (ProfileSwitcher como diálogo)."""
        try:
            if hasattr(self, "profile_switcher"):
                self.profile_switcher.show_profile_menu()
        except Exception as e:
            print(f"[PROFILE] Error opening profile manager: {e}")

    def show_login_dialog(self):
        """Mostrar diálogo de login"""
        if not self.auth_manager:
            QMessageBox.warning(self, "Error", "Sistema de autenticación no disponible")
            return
        # Verificar si ya está autenticado
        if self.auth_manager.auth_state.is_authenticated:
            self.show_logout_dialog()
            return
        # Mostrar diálogo de login
        login_dialog = LoginDialog(self)

        # Conectar señales - IMPORTANTE: conectar ANTES de exec()
        login_dialog.login_requested.connect(
            lambda email, password: self.handle_login(email, password, login_dialog)
        )
        login_dialog.register_requested.connect(self.open_registration_page)

        # Conectar señal de éxito para cerrar el diálogo automáticamente
        self.auth_manager.login_successful.connect(login_dialog.accept)

        # Ejecutar diálogo modal
        result = login_dialog.exec()

        # Desconectar señales después de cerrar para evitar fugas de memoria
        try:
            self.auth_manager.login_successful.disconnect(login_dialog.accept)
        except:
            pass
    def handle_login(self, email, password, dialog=None):
        """Manejar login de usuario de forma ASÍNCRONA usando QThread para evitar congelamiento"""
        if not self.auth_manager:
            QMessageBox.critical(
                self, "Error", "Sistema de autenticación no disponible"
            )
            return
        # Verificar si ya hay un login en progreso
        if self.login_worker and self.login_worker.isRunning():
            print("[UI] Login already in progress, ignoring duplicate request")
            return
        # Deshabilitar botón durante el login
        self.login_btn.setEnabled(False)
        self.login_btn.setToolTip("Validando credenciales...")

        # Guardar referencia al diálogo para usarla en el callback
        self._current_login_dialog = dialog

        print(f"[UI] Starting ASYNC login process in separate thread for: {email}")

        # CRÍTICO: Crear y ejecutar worker thread para login asíncrono
        # Esto evita que el hilo principal de Qt se congele completamente
        self.login_worker = LoginWorker(self.auth_manager, email, password)
        self.login_worker.login_completed.connect(self._on_login_completed)
        self.login_worker.start()

        print("[UI] Login worker thread started, UI remains responsive")
    def _on_login_completed(self, result):
        """Callback cuando el login se completa en el worker thread"""
        print(f"[UI] Login completed callback received: success={result.success}")

        # Restaurar botón
        self.login_btn.setEnabled(True)
        self.login_btn.setToolTip("Iniciar sesión en Katphi")

        # Limpiar worker thread
        if self.login_worker:
            self.login_worker.deleteLater()
            self.login_worker = None
        try:
            if result.success:
                # Actualizar UI (esto se llama automáticamente por las señales, pero lo hacemos explícito)
                self.update_auth_ui()

                # Obtener email del diálogo
                email = (
                    self._current_login_dialog.email_edit.text()
                    if self._current_login_dialog
                    else "usuario"
                )

                # Cerrar el diálogo primero
                if self._current_login_dialog:
                    self._current_login_dialog.accept()
                    self._current_login_dialog = None
                # Mostrar mensaje de éxito DESPUÉS de cerrar el diálogo
                QTimer.singleShot(
                    200,
                    lambda: QMessageBox.information(
                        self,
                        "Inicio de Sesión Exitoso",
                        f"¡Bienvenido, {email}!\n\n"
                        "• Sesión iniciada correctamente\n"
                        "• Acceso a plugins premium habilitado\n"
                        "• Sincronización completada",
                    ),
                )
            else:
                # Preparar mensaje de error específico
                from auth_manager import AuthError

                error_details = ""
                if result.error == AuthError.INVALID_CREDENTIALS:
                    error_details = (
                        "Credenciales incorrectas. Verifica tu email y contraseña."
                    )
                elif result.error == AuthError.USER_NOT_VERIFIED:
                    error_details = "Cuenta no verificada. Revisa tu correo electrónico y activa tu cuenta."
                elif result.error == AuthError.NETWORK_ERROR:
                    error_details = (
                        "Error de conexión. Verifica tu conexión a internet."
                    )
                else:
                    error_details = f"Error: {result.message}"
                print(f"[UI] Showing error in login dialog: {result.error}")

                # CRÍTICO: Mostrar error DIRECTAMENTE en el diálogo sin QMessageBox
                # Esto evita bloqueos modales y mantiene el navegador responsive
                if self._current_login_dialog:
                    self._current_login_dialog.show_error_in_dialog(error_details)
        except Exception as e:
            print(f"[UI] Login callback error: {e}")
            import traceback

            traceback.print_exc()

            # Mostrar error crítico en el diálogo
            error_msg = f"Error crítico: {str(e)}"
            if self._current_login_dialog:
                self._current_login_dialog.show_error_in_dialog(error_msg)
    def show_logout_dialog(self):
        """Mostrar opciones de logout"""
        if not self.auth_manager or not self.auth_manager.auth_state.is_authenticated:
            return
        reply = QMessageBox.question(
            self,
            "Cerrar Sesión",
            "¿Deseas cerrar sesión?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.auth_manager.logout()
            self.update_auth_ui()  # Esto ya llama a disable_premium_plugins()
            QMessageBox.information(
                self, "Sesión Cerrada", "Has cerrado sesión correctamente"
            )
    def update_auth_ui(self):
        """Actualizar la interfaz de usuario según el estado de autenticación"""
        if not self.auth_manager:
            return
        if self.auth_manager.auth_state.is_authenticated:
            # Usuario autenticado
            user_info = self.auth_manager.get_user_info()
            email = user_info.get("email", "Usuario") if user_info else "Usuario"

            # Keep the account icon but change tooltip and class
            self.login_btn.setToolTip(f"Cerrar sesión ({email})")
            # Los estilos del botón de logout se manejan por el tema JSON
            self.login_btn.setProperty("class", "logout-button")

            # Mostrar estado del usuario
            self.user_status_label.setText(f"✓ {email}")
            self.user_status_label.show()

            # Habilitar plugins premium
            self.enable_premium_plugins()
        else:
            # Usuario no autenticado
            self.login_btn.setToolTip("Iniciar sesión en Katphi")
            # Los estilos del botón de login se manejan por el tema JSON
            self.login_btn.setProperty("class", "login-button")

            # Ocultar estado del usuario
            self.user_status_label.hide()

            # Deshabilitar plugins premium
            self.disable_premium_plugins()
    def open_registration_page(self):
        """Abrir página de registro en una nueva pestaña"""
        try:
            from network_config import get_registration_url

            registration_url = get_registration_url()
        except ImportError:
            # Fallback si no existe network_config.py
            registration_url = "https://katphi.com/auth/registro.html"
        self.tab_manager.add_new_tab(registration_url)
    def _plugin_has_subscription(self, plugin_id: str) -> bool:
        """Comprobar si la cuenta autenticada tiene licencia o trial activo
        para un plugin concreto (no solo si hay sesión iniciada)."""
        if not hasattr(self, "plugin_manager") or not self.plugin_manager:
            return False
        try:
            access_info = self.plugin_manager.get_plugin_access(plugin_id)
            return access_info.access_level in (
                PluginAccessLevel.PREMIUM,
                PluginAccessLevel.TRIAL,
            )
        except Exception as e:
            print(f"[AUTH] Error checking subscription for {plugin_id}: {e}")
            return False
    def enable_premium_plugins(self):
        """(compat) Delegado en resync_plugins_to_current_user()."""
        self.resync_plugins_to_current_user()

    def disable_premium_plugins(self):
        """(compat) Delegado en resync_plugins_to_current_user()."""
        self.resync_plugins_to_current_user()

    def _plugin_is_free(self, plugin_id: str) -> bool:
        """True solo si el plugin_info.json del plugin declara premium:false.
        Fail-closed: si falta el fichero o no se puede leer, se trata como premium."""
        try:
            import json

            plugin_dir = find_plugin_dir(plugin_id)
            if plugin_dir is None:
                return False
            info = plugin_dir / "plugin_info.json"
            if not info.exists():
                return False
            with open(info, "r", encoding="utf-8") as f:
                return not json.load(f).get("premium", True)
        except Exception:
            return False

    def _gate_core_panel(self, plugin_id, panel, dock, allowed):
        """Activar/cortar un panel core (scraping/proxy) según el derecho real.
        Cuando se corta no solo se hace setEnabled(False): se intenta detener
        cualquier trabajo en curso y se oculta el dock."""
        if not panel:
            return
        try:
            panel.setEnabled(bool(allowed))
            if not allowed:
                for meth in ("stop", "shutdown", "cleanup", "deactivate", "on_logout"):
                    fn = getattr(panel, meth, None)
                    if callable(fn):
                        try:
                            fn()
                        except Exception:
                            pass
                if dock is not None:
                    try:
                        dock.hide()
                    except Exception:
                        pass
            print(f"[AUTH] Core panel {plugin_id}: {'activo' if allowed else 'cortado'}")
        except Exception as e:
            print(f"[AUTH] Error en _gate_core_panel({plugin_id}): {e}")

    def resync_plugins_to_current_user(self, *args, **kwargs):
        """Punto ÚNICO de sincronización de plugins con el usuario actual.

        Se ejecuta en login, logout, cambio de estado de auth y cambios de
        licencia. A diferencia del antiguo enable/disable (solo aditivo), aquí
        también se DESCARGAN los plugins premium a los que el usuario actual ya
        no tiene derecho, de modo que una sesión no pueda heredar los plugins
        de la sesión anterior.
        """
        pm = getattr(self, "plugin_manager", None)
        authed = bool(
            self.auth_manager and self.auth_manager.auth_state.is_authenticated
        )

        # --- 1. Plugins premium/trial con derecho para el usuario actual
        entitled = set()
        if pm:
            for plugin_id in list(getattr(pm, "plugin_configs_data", {}).keys()):
                try:
                    access = pm.get_plugin_access(plugin_id)
                    if access.is_licensed or access.access_level in (
                        PluginAccessLevel.PREMIUM,
                        PluginAccessLevel.TRIAL,
                    ):
                        entitled.add(plugin_id)
                except Exception as e:
                    print(f"[AUTH] resync: error consultando {plugin_id}: {e}")

        # --- 2. Descargar de memoria los plugins cargados SIN derecho
        #        (los realmente gratuitos se mantienen)
        if pm:
            for plugin_id in list(pm.plugins.keys()):
                if plugin_id in entitled or self._plugin_is_free(plugin_id):
                    continue
                print(f"[AUTH] resync: descargando plugin sin derecho: {plugin_id}")
                try:
                    # Dispara on_plugin_unloaded -> quita botón del sidebar y panel
                    pm.unload_plugin(plugin_id)
                except Exception as e:
                    print(f"[AUTH] resync: error descargando {plugin_id}: {e}")

        # --- 2b. Barrido defensivo de restos de UI de plugins ya no permitidos
        for attr in ("dynamic_plugin_actions", "dynamic_plugin_panels"):
            mapping = getattr(self, attr, None)
            if not mapping:
                continue
            for plugin_id in list(mapping.keys()):
                if plugin_id in entitled or self._plugin_is_free(plugin_id):
                    continue
                try:
                    obj = mapping.pop(plugin_id)
                    if attr == "dynamic_plugin_actions":
                        if getattr(self, "side_strip", None):
                            self.side_strip.removeAction(obj)
                    else:
                        try:
                            self.removeDockWidget(obj)
                        except Exception:
                            pass
                    print(f"[AUTH] resync: UI de {plugin_id} eliminada ({attr})")
                except Exception as e:
                    print(f"[AUTH] resync: error limpiando {plugin_id} ({attr}): {e}")

        # --- 3. Paneles core (scraping / proxy / seo_analyzer / ai_live_ide)
        self._gate_core_panel(
            "scraping",
            getattr(self, "scraping_panel", None),
            getattr(self, "scraping_dock", None),
            "scraping" in entitled,
        )
        self._gate_core_panel(
            "proxy",
            getattr(self, "proxy_panel", None),
            getattr(self, "proxy_dock", None),
            "proxy" in entitled,
        )
        self._gate_core_panel(
            "seo_analyzer",
            getattr(self, "seo_panel", None),
            getattr(self, "seo_dock", None),
            "seo_analyzer" in entitled,
        )
        self._gate_core_panel(
            "ai_live_ide",
            getattr(self, "ai_live_ide_panel", None),
            getattr(self, "ai_live_ide_dock", None),
            "ai_live_ide" in entitled,
        )

        # --- 4. Cargar los plugins instalados a los que el usuario SÍ tiene acceso
        if pm and authed:
            try:
                results = pm.load_all_installed_plugins()
                ok = sum(1 for v in results.values() if v)
                print(f"[AUTH] resync: {ok}/{len(results)} plugins instalados cargados")
            except Exception as e:
                print(f"[AUTH] resync: error cargando instalados: {e}")

        # --- 5. Restaurar sesión de pestañas solo con usuario autenticado
        if authed and hasattr(self, "tab_manager"):
            try:
                self.tab_manager.restaurar_sesion()
            except Exception as e:
                print(f"[AUTH] resync: error restaurando sesión: {e}")

        print(
            f"[AUTH] resync completado (authed={authed}, "
            f"con_derecho={sorted(entitled)})"
        )
    def set_light_theme(self):
        """Aplica el tema claro usando el sistema de temas JSON"""
        try:
            if THEME_SYSTEM_AVAILABLE:
                theme_manager = get_theme_manager()
                if theme_manager:
                    theme_manager.apply_theme("light")
                    self._apply_tooltip_theme(theme_manager)
                    print("[OK] Light theme applied via theme manager")
                else:
                    print("[ERROR] Theme manager not available")
            else:
                print("[ERROR] Theme system not available")
        except Exception as e:
            print(f"[ERROR] Failed to apply light theme: {e}")
    def set_dark_theme(self):
        """Aplica el tema oscuro usando el sistema de temas JSON"""
        try:
            if THEME_SYSTEM_AVAILABLE:
                theme_manager = get_theme_manager()
                if theme_manager:
                    theme_manager.apply_theme("dark")
                    self._apply_tooltip_theme(theme_manager)
                    print("[OK] Dark theme applied via theme manager")
                else:
                    print("[ERROR] Theme manager not available")
            else:
                print("[ERROR] Theme system not available")
        except Exception as e:
            print(f"[ERROR] Failed to apply dark theme: {e}")
    def _initialize_auth_system(self):
        """Initialize authentication system after startup"""
        try:
            if AUTH_SYSTEM_AVAILABLE:
                self.auth_manager = AuthManager()
                print("[OK] Authentication system initialized (delayed)")
            else:
                print("[WARNING] Authentication system not available")
        except Exception as e:
            print(f"[ERROR] Failed to initialize auth system: {e}")
    def _initialize_plugin_system(self):
        """Initialize plugin system after startup (LEGACY - YA NO SE USA)"""
        # Este método es legacy del sistema antiguo de plugins
        # El UnifiedPluginManager se inicializa síncronamente en __init__
        # Este método nunca se llama porque quitamos QTimer.singleShot
        print(
            "[INFO] _initialize_plugin_system is legacy code - UnifiedPluginManager already initialized"
        )
    def _configure_default_profile_user_agent(self):
        """
        Configurar User-Agent en el perfil predeterminado de QWebEngine.
        Este método se llama al iniciar la aplicación para asegurar que
        todas las pestañas usen el User-Agent correcto desde el principio.
        """
        try:
            if not hasattr(self, "network_interceptor") or not self.network_interceptor:
                print(
                    "[WARNING] Network interceptor not available, cannot configure User-Agent"
                )
                return
            # Obtener el perfil predeterminado
            default_profile = QWebEngineProfile.defaultProfile()

            # Obtener el User-Agent configurado
            user_agent_string = self.network_interceptor._get_user_agent()

            # Configurar el User-Agent en el perfil predeterminado
            default_profile.setHttpUserAgent(user_agent_string)

            # Configurar el interceptor de red en el perfil predeterminado
            default_profile.setUrlRequestInterceptor(self.network_interceptor)

            print(
                f"[UA-GLOBAL] ✓ User-Agent configured on default profile: {self.network_interceptor.user_agent_type}"
            )
            print(f"[UA-GLOBAL] ✓ User-Agent string: {user_agent_string[:100]}...")
        except Exception as e:
            print(f"[ERROR] Failed to configure default profile User-Agent: {e}")
            import traceback

            traceback.print_exc()
    def update_global_user_agent(self):
        """
        Actualizar el User-Agent del perfil global cuando se cambia en las configuraciones.
        Este método debe llamarse cuando el usuario cambia el User-Agent en las opciones.
        """
        try:
            if not hasattr(self, "network_interceptor") or not self.network_interceptor:
                print(
                    "[WARNING] Network interceptor not available, cannot update User-Agent"
                )
                return False
            # Obtener el perfil predeterminado
            default_profile = QWebEngineProfile.defaultProfile()

            # Obtener el User-Agent configurado actualizado
            user_agent_string = self.network_interceptor._get_user_agent()

            # Actualizar el User-Agent en el perfil predeterminado
            default_profile.setHttpUserAgent(user_agent_string)

            print(
                f"[UA-UPDATE] ✓ User-Agent updated on default profile: {self.network_interceptor.user_agent_type}"
            )
            print(f"[UA-UPDATE] ✓ New User-Agent: {user_agent_string[:100]}...")

            return True
        except Exception as e:
            print(f"[ERROR] Failed to update global User-Agent: {e}")
            import traceback

            traceback.print_exc()
            return False
    def _load_free_plugins(self):
        """Cargar plugins gratuitos automáticamente sin necesidad de autenticación.

        También descubre automáticamente nuevos plugins gratuitos que estén en la
        carpeta plugins/ (útil durante desarrollo de nuevos plugins libres).
        """
        if not self.plugin_manager:
            return
        print("[UI] Loading free plugins...")

        try:
            import json
            import os
            from pathlib import Path
            from plugin_paths import (
                resolve_config_file,
                find_plugin_dir,
                iter_installed_plugin_ids,
            )
            from plugin_policy import is_free_plugin, dev_mode_allowed

            loaded_any = False

            # 1. Cargar desde plugin_config.json (plugins registrados)
            config_file = resolve_config_file()
            plugin_config = {}
            if config_file.exists():
                with open(config_file, "r") as f:
                    plugin_config = json.load(f)

            for plugin_id, config in plugin_config.items():
                if not config.get("enabled", False):
                    continue
                plugin_dir = find_plugin_dir(plugin_id)
                if plugin_dir is None:
                    continue

                # Gratuito o premium lo decide plugin_policy (dentro del programa),
                # no el plugin_info.json del plugin, que el usuario puede editar.
                is_premium = not is_free_plugin(plugin_id)

                # dev_mode solo cuenta ejecutando desde el código fuente con KATPHI_DEV=1
                dev_mode = bool(config.get("dev_mode", False)) and dev_mode_allowed()

                if (not is_premium) or dev_mode:
                    label = "dev" if (is_premium and dev_mode) else "free"
                    print(f"[UI] Loading {label} plugin: {plugin_id}")
                    if self.plugin_manager.load_plugin(plugin_id):
                        print(f"[UI] {label.capitalize()} plugin {plugin_id} loaded successfully")
                        loaded_any = True
                    else:
                        print(f"[UI] Failed to load {label} plugin {plugin_id}")
                else:
                    print(f"[UI] Skipping premium plugin: {plugin_id}")

            # 2. Descubrimiento automático de plugins gratuitos nuevos (para desarrollo)
            # Esto permite que un plugin nuevo con "premium": false en su plugin_info.json
            # se cargue aunque no esté todavía en plugin_config.json.
            # Recorre tanto los plugins descargados (carpeta de usuario) como los
            # preinstalados (bundle).
            for plugin_id in iter_installed_plugin_ids():
                    if plugin_id in plugin_config:   # ya procesado arriba
                        continue
                    if plugin_id in self.plugin_manager.plugins:  # ya cargado
                        continue

                    item = find_plugin_dir(plugin_id)
                    if item is None:
                        continue
                    init_file = item / "__init__.py"
                    info_file = item / "plugin_info.json"
                    if not init_file.exists() or not info_file.exists():
                        continue

                    try:
                        with open(info_file, "r", encoding="utf-8") as f:
                            plugin_info = json.load(f)

                        if not is_free_plugin(plugin_id):
                            continue  # solo auto-cargamos gratuitos en descubrimiento

                        print(f"[UI] Auto-discovered free plugin: {plugin_id}")
                        if self.plugin_manager.load_plugin(plugin_id):
                            print(f"[UI] Free plugin {plugin_id} loaded successfully (auto-discovered)")
                            loaded_any = True
                        else:
                            print(f"[UI] Failed to auto-load free plugin {plugin_id}")
                    except Exception as e:
                        print(f"[UI] Error auto-discovering plugin {plugin_id}: {e}")

            if not loaded_any:
                print("[UI] No additional free plugins to load")

        except Exception as e:
            print(f"[UI] Error loading free plugins: {e}")
            import traceback
            traceback.print_exc()
    def _setup_auth_panel(self):
        """Setup authentication panel after auth_manager is ready"""
        try:
            if self.auth_manager and AUTH_SYSTEM_AVAILABLE:
                self.auth_panel = AuthPanel(self.auth_manager)
                self.auth_dock = QDockWidget("Cuenta", self)
                self.auth_dock.setWidget(self.auth_panel)
                self.auth_dock.setAllowedAreas(
                    Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
                )
                self.addDockWidget(Qt.RightDockWidgetArea, self.auth_dock)
                self.auth_dock.hide()
                print("[OK] Authentication panel configured (delayed)")
            else:
                print("[WARNING] Auth manager not ready for panel setup")
        except Exception as e:
            print(f"[ERROR] Failed to setup auth panel: {e}")
    def on_plugin_loaded(self, plugin_id: str):
        """
        Manejar la carga de un plugin dinámicamente
        Agregar botón al sidebar y crear panel
        """
        print(f"[UI] Plugin loaded signal received: {plugin_id}")

        try:
            # Obtener el módulo del plugin
            if not self.plugin_manager or plugin_id not in self.plugin_manager.plugins:
                print(f"[UI] Plugin {plugin_id} not found in plugin manager")
                return
            plugin_module = self.plugin_manager.plugins[plugin_id]

            # NUEVO: Soporte para plugins basados en PluginBase
            if hasattr(plugin_module, "get_plugin_instance"):
                print(f"[UI] Plugin {plugin_id} uses PluginBase architecture")
                plugin_instance = plugin_module.get_plugin_instance()

                if plugin_instance and hasattr(plugin_instance, "initialize"):
                    print(f"[UI] Initializing PluginBase plugin: {plugin_id}")
                    try:
                        success = plugin_instance.initialize(
                            self
                        )  # Pass browser instance
                        if success:
                            print(f"[UI] Plugin {plugin_id} initialized successfully")
                            # Store instance for later use
                            self.dynamic_plugin_panels[plugin_id] = plugin_instance

                            # Split View: reponer acceso visible en el sidebar
                            if (
                                plugin_id == "split_view"
                                and plugin_id not in self.dynamic_plugin_actions
                            ):
                                split_action = self._make_strip_action(
                                    "splitview", "Split View", self.toggle_split_view
                                )

                                actions = self.side_strip.actions()
                                store_index = -1
                                for i, action in enumerate(actions):
                                    if action.text() == "Plugin Store":
                                        store_index = i
                                        break
                                if store_index >= 0:
                                    self.side_strip.insertAction(
                                        actions[store_index], split_action
                                    )
                                else:
                                    self.side_strip.addAction(split_action)
                                self.dynamic_plugin_actions[plugin_id] = split_action
                                print("[UI] Split View button added to sidebar")
                            # Cargar UI específica del plugin de temas
                            if plugin_id == "themes":
                                self._load_themes_plugin_dynamic(plugin_instance)

                            # ============================================================
                            # GENERIC SUPPORT FOR PLUGINBASE PLUGINS WITH SIDEBAR
                            # ============================================================
                            # Any plugin that follows the pattern can get a left sidebar
                            # button + advanced panel without modifying ui.py again.
                            self._try_register_plugin_sidebar(plugin_instance, plugin_id)

                        else:
                            print(
                                f"[UI] Plugin {plugin_id} initialization returned False"
                            )
                    except Exception as e:
                        print(f"[UI] Error initializing plugin {plugin_id}: {e}")
                        import traceback

                        traceback.print_exc()
                return
            # Verificar si el plugin tiene get_plugin_panel (plugins antiguos)
            # pentesting_tool y ai_live_ide usan get_panel_class, no bloquearlos
            if plugin_id not in ("pentesting_tool", "ai_live_ide"):
                if (
                    not hasattr(plugin_module, "get_scraping_panel")
                    and not hasattr(plugin_module, "get_proxy_panel")
                    and not hasattr(plugin_module, "get_seo_panel")
                ):
                    print(f"[UI] Plugin {plugin_id} doesn't have a panel getter")
                    return
            # Cargar panel según el tipo de plugin (plugins antiguos)
            if plugin_id == "scraping" and hasattr(plugin_module, "get_scraping_panel"):
                self._load_scraping_plugin_dynamic(plugin_module)
            elif plugin_id == "proxy" and hasattr(plugin_module, "get_proxy_panel"):
                self._load_proxy_plugin_dynamic(plugin_module)
            elif plugin_id == "seo_analyzer" and hasattr(
                plugin_module, "get_seo_panel"
            ):
                self._load_seo_plugin_dynamic(plugin_module)
            elif plugin_id == "pentesting_tool" and hasattr(
                plugin_module, "get_panel_class"
            ):
                self._load_pentesting_plugin_dynamic(plugin_module)
            elif plugin_id == "ai_live_ide" and hasattr(
                plugin_module, "get_panel_class"
            ):
                self._load_ai_live_ide_plugin_dynamic(plugin_module)
            elif plugin_id == "themes":
                print(f"[UI] Themes plugin loaded, no UI changes needed")
            else:
                print(f"[UI] Unknown plugin type: {plugin_id}")
        except Exception as e:
            print(f"[UI] Error loading plugin UI for {plugin_id}: {e}")
            import traceback

            traceback.print_exc()

    def _try_register_plugin_sidebar(self, plugin_instance, plugin_id: str):
        """
        Generic handler for PluginBase plugins that want a button in the
        left sidebar + panel in advanced_panel_stack.

        A well-behaved plugin should expose after initialize():
            - .panel (the QWidget / KatphiPanelBase to show)
            - .get_sidebar_action() -> QAction   (optional but recommended)
            - .sidebar_action                  (fallback)
        """
        try:
            # 1. Register the panel if the plugin created one
            panel = None
            if hasattr(plugin_instance, "get_panel"):
                panel = plugin_instance.get_panel()
            elif hasattr(plugin_instance, "panel"):
                panel = plugin_instance.panel

            if panel and hasattr(self, "advanced_panel_stack"):
                if self.advanced_panel_stack.indexOf(panel) < 0:
                    self.advanced_panel_stack.addWidget(panel)
                    print(f"[UI] Panel registered for plugin: {plugin_id}")

            # 2. Add sidebar button if the plugin provides one
            action = None
            if hasattr(plugin_instance, "get_sidebar_action"):
                action = plugin_instance.get_sidebar_action()
            elif hasattr(plugin_instance, "sidebar_action"):
                action = plugin_instance.sidebar_action

            if action and hasattr(self, "side_strip"):
                if plugin_id not in self.dynamic_plugin_actions:
                    # Try to insert before "Plugin Store" for nice ordering
                    actions = self.side_strip.actions()
                    store_index = -1
                    for i, a in enumerate(actions):
                        if "plugin" in a.text().lower() or "store" in a.text().lower():
                            store_index = i
                            break

                    if store_index >= 0:
                        self.side_strip.insertAction(actions[store_index], action)
                    else:
                        self.side_strip.addAction(action)

                    self.dynamic_plugin_actions[plugin_id] = action
                    print(f"[UI] Sidebar button added for plugin: {plugin_id}")

        except Exception as e:
            print(f"[UI] Error in generic sidebar registration for {plugin_id}: {e}")
            import traceback
            traceback.print_exc()

    def _load_scraping_plugin_dynamic(self, plugin_module):
        """Cargar plugin de scraping dinámicamente"""
        global SCRAPING_AVAILABLE
        try:
            print("[UI] Loading scraping plugin dynamically...")

            # Obtener componentes del plugin
            ScrapingPanel = plugin_module.get_scraping_panel()
            scraping_integration = plugin_module.get_scraping_integration()

            if not ScrapingPanel or not scraping_integration:
                print("[UI] Failed to get scraping components")
                return
            # Crear panel
            self.scraping_panel = ScrapingPanel(scraping_integration, plugin_validator=self.plugin_manager)
            self.scraping_integration = scraping_integration

            # Crear dock widget (reemplazar si ya existe)
            if hasattr(self, "scraping_dock") and self.scraping_dock:
                # Ya existe, solo actualizar el widget
                self.scraping_dock.setWidget(self.scraping_panel)
                print("[UI] Updated existing scraping dock widget")
            else:
                # Crear nuevo dock widget
                self.scraping_dock = QDockWidget("Scraping Avanzado", self)
                self.scraping_dock.setWidget(self.scraping_panel)
                self.scraping_dock.setAllowedAreas(
                    Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
                )
                self.addDockWidget(Qt.RightDockWidgetArea, self.scraping_dock)
                self.scraping_dock.hide()
                print("[UI] Created new scraping dock widget")
            # Habilitar panel solo si el usuario está autenticado Y tiene licencia/trial de scraping
            if self.auth_manager and self.auth_manager.auth_state.is_authenticated:
                self.scraping_panel.setEnabled(self._plugin_has_subscription("scraping"))
            # Verificar si ya existe un botón de scraping (del import estático)
            existing_scraping_action = None
            for action in self.side_strip.actions():
                if action.text() == "Scraping" and action.toolTip() == "Scraping":
                    existing_scraping_action = action
                    print("[UI] Found existing scraping button from static import")
                    break
            # Si no existe botón (ni estático ni dinámico), crearlo
            if (
                not existing_scraping_action
                and "scraping" not in self.dynamic_plugin_actions
            ):
                print("[UI] Creating new scraping button...")
                self.scraping_action = self._make_strip_action(
                    "scrap", "Scraping", self.toggle_scraping_panel
                )

                # Insertar antes del botón de Plugin Store
                actions = self.side_strip.actions()
                store_index = -1
                for i, action in enumerate(actions):
                    if action.text() == "Plugin Store":
                        store_index = i
                        break
                if store_index >= 0:
                    self.side_strip.insertAction(
                        actions[store_index], self.scraping_action
                    )
                    print(
                        f"[UI] Inserted scraping button before Plugin Store (index {store_index})"
                    )
                else:
                    self.side_strip.addAction(self.scraping_action)
                    print("[UI] Added scraping button to end of sidebar")
                self.dynamic_plugin_actions["scraping"] = self.scraping_action
                self.dynamic_plugin_panels["scraping"] = self.scraping_panel

                print("[UI] Scraping plugin loaded and button added to sidebar")
            elif existing_scraping_action:
                # Ya existe botón estático, solo asegurarnos que funciona
                print("[UI] Scraping plugin loaded, using existing static button")
                self.dynamic_plugin_panels["scraping"] = self.scraping_panel
            else:
                print(
                    "[UI] Scraping plugin loaded, button already exists in dynamic_plugin_actions"
                )
            # Marcar scraping como disponible
            SCRAPING_AVAILABLE = True
            print("[UI] SCRAPING_AVAILABLE set to True")
        except Exception as e:
            print(f"[UI] Error loading scraping plugin: {e}")
            import traceback

            traceback.print_exc()
    def _load_proxy_plugin_dynamic(self, plugin_module):
        """Cargar plugin de proxy dinámicamente"""
        global PROXY_AVAILABLE
        try:
            print("[UI] Loading proxy plugin dynamically...")

            # Obtener componentes del plugin
            ProxyPanel = plugin_module.get_proxy_panel()

            if not ProxyPanel:
                print("[UI] Failed to get proxy panel")
                return
            # Obtener proxy manager del scraping integration si existe
            proxy_manager = None
            if hasattr(self, "scraping_integration") and hasattr(
                self.scraping_integration, "proxy_manager"
            ):
                proxy_manager = self.scraping_integration.proxy_manager
            # Crear panel
            self.proxy_panel = ProxyPanel(proxy_manager, plugin_validator=self.plugin_manager)

            # Crear dock widget (reemplazar si ya existe)
            if hasattr(self, "proxy_dock") and self.proxy_dock:
                # Ya existe, solo actualizar el widget
                self.proxy_dock.setWidget(self.proxy_panel)
                print("[UI] Updated existing proxy dock widget")
            else:
                # Crear nuevo dock widget
                self.proxy_dock = QDockWidget("Gestión de Proxies", self)
                self.proxy_dock.setWidget(self.proxy_panel)
                self.proxy_dock.setAllowedAreas(
                    Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
                )
                self.addDockWidget(Qt.RightDockWidgetArea, self.proxy_dock)
                self.proxy_dock.hide()
                print("[UI] Created new proxy dock widget")
            # Habilitar panel solo si el usuario está autenticado Y tiene licencia/trial de proxy
            if self.auth_manager and self.auth_manager.auth_state.is_authenticated:
                self.proxy_panel.setEnabled(self._plugin_has_subscription("proxy"))
            # Verificar si ya existe un botón de proxy (del import estático)
            existing_proxy_action = None
            for action in self.side_strip.actions():
                if action.text() == "Proxies":
                    existing_proxy_action = action
                    print("[UI] Found existing proxy button from static import")
                    break
            # Si no existe botón (ni estático ni dinámico), crearlo
            if not existing_proxy_action and "proxy" not in self.dynamic_plugin_actions:
                print("[UI] Creating new proxy button...")
                self.proxy_action = self._make_strip_action(
                    "proxy", "Proxies", self.toggle_proxy_panel
                )

                # Insertar antes del botón de Plugin Store
                actions = self.side_strip.actions()
                store_index = -1
                for i, action in enumerate(actions):
                    if action.text() == "Plugin Store":
                        store_index = i
                        break
                if store_index >= 0:
                    self.side_strip.insertAction(
                        actions[store_index], self.proxy_action
                    )
                    print(
                        f"[UI] Inserted proxy button before Plugin Store (index {store_index})"
                    )
                else:
                    self.side_strip.addAction(self.proxy_action)
                    print("[UI] Added proxy button to end of sidebar")
                self.dynamic_plugin_actions["proxy"] = self.proxy_action
                self.dynamic_plugin_panels["proxy"] = self.proxy_panel

                print("[UI] Proxy plugin loaded and button added to sidebar")
            elif existing_proxy_action:
                # Ya existe botón estático, solo asegurarnos que funciona
                print("[UI] Proxy plugin loaded, using existing static button")
                self.dynamic_plugin_panels["proxy"] = self.proxy_panel
            else:
                print(
                    "[UI] Proxy plugin loaded, button already exists in dynamic_plugin_actions"
                )
            # Marcar proxy como disponible
            PROXY_AVAILABLE = True
            print("[UI] PROXY_AVAILABLE set to True")
        except Exception as e:
            print(f"[UI] Error loading proxy plugin: {e}")
            import traceback

            traceback.print_exc()
    def _load_seo_plugin_dynamic(self, plugin_module):
        """Cargar plugin de SEO dinámicamente"""
        try:
            print("[UI] Loading SEO plugin dynamically...")

            # Obtener componente del plugin
            SEOPanel = plugin_module.get_seo_panel()

            if not SEOPanel:
                print("[UI] SEO plugin running in compatibility mode (no UI available)")
                return
            # Determinar el tier real según la licencia del usuario (antes el panel
            # SEO caía siempre en tier "pro" por defecto, sin validar suscripción).
            tier = "free"
            try:
                if self.plugin_manager:
                    access_info = self.plugin_manager.get_plugin_access("seo_analyzer")
                    if access_info.access_level.value != "free":
                        tier = "pro"
            except Exception as e:
                print(f"[WARNING] No se pudo determinar el tier real de SEO Analyzer: {e}")

            TierManagerClass = None
            if hasattr(plugin_module, "get_tier_manager"):
                try:
                    TierManagerClass = plugin_module.get_tier_manager()
                except Exception as e:
                    print(f"[WARNING] No se pudo obtener TierManager del plugin SEO: {e}")

            # Crear panel
            if TierManagerClass:
                self.seo_panel = SEOPanel(parent=self, tier_manager=TierManagerClass(tier))
            else:
                self.seo_panel = SEOPanel(parent=self)

            # Crear dock widget (reemplazar si ya existe)
            if hasattr(self, "seo_dock") and self.seo_dock:
                # Ya existe, solo actualizar el widget
                self.seo_dock.setWidget(self.seo_panel)
                print("[UI] Updated existing SEO dock widget")
            else:
                # Crear nuevo dock widget
                self.seo_dock = QDockWidget("SEO Analyzer Pro", self)
                self.seo_dock.setWidget(self.seo_panel)
                self.seo_dock.setAllowedAreas(
                    Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea
                )
                self.addDockWidget(Qt.RightDockWidgetArea, self.seo_dock)
                self.seo_dock.hide()
                print("[UI] Created new SEO dock widget")
            # Habilitar panel si el usuario está autenticado
            if self.auth_manager and self.auth_manager.auth_state.is_authenticated:
                self.seo_panel.setEnabled(True)
            # Verificar si ya existe un botón de SEO
            existing_seo_action = None
            for action in self.side_strip.actions():
                if action.text() == "SEO" or action.text() == "SEO Analyzer":
                    existing_seo_action = action
                    print("[UI] Found existing SEO button")
                    break
            # Si no existe botón, crearlo
            if (
                not existing_seo_action
                and "seo_analyzer" not in self.dynamic_plugin_actions
            ):
                print("[UI] Creating new SEO button...")
                self.seo_action = self._make_strip_action(
                    "seo", "SEO", self.toggle_seo_panel
                )

                # Insertar antes del botón de Plugin Store
                actions = self.side_strip.actions()
                store_index = -1
                for i, action in enumerate(actions):
                    if action.text() == "Plugin Store":
                        store_index = i
                        break
                if store_index >= 0:
                    self.side_strip.insertAction(actions[store_index], self.seo_action)
                    print(
                        f"[UI] Inserted SEO button before Plugin Store (index {store_index})"
                    )
                else:
                    self.side_strip.addAction(self.seo_action)
                    print("[UI] Added SEO button to end of sidebar")
                self.dynamic_plugin_actions["seo_analyzer"] = self.seo_action
                self.dynamic_plugin_panels["seo_analyzer"] = self.seo_panel

                print("[UI] SEO plugin loaded and button added to sidebar")
            elif existing_seo_action:
                # Ya existe botón, solo asegurarnos que funciona
                print("[UI] SEO plugin loaded, using existing button")
                self.dynamic_plugin_panels["seo_analyzer"] = self.seo_panel
            else:
                print(
                    "[UI] SEO plugin loaded, button already exists in dynamic_plugin_actions"
                )
        except Exception as e:
            print(f"[UI] Error loading SEO plugin: {e}")
            import traceback

            traceback.print_exc()
    def _load_pentesting_plugin_dynamic(self, plugin_module):
        """Cargar plugin de Pentesting dinámicamente"""
        try:
            print("[UI] Loading Pentesting plugin dynamically...")

            # Agregar directorio del plugin al path para que pueda importar core.payloads
            import sys
            from pathlib import Path

            _pt_base = find_plugin_dir("pentesting_tool") or (
                BUNDLED_PLUGINS_DIR / "pentesting_tool"
            )
            plugin_dir = _pt_base / "pentesting_tool"
            for _p in (str(_pt_base), str(plugin_dir)):
                if _p not in sys.path:
                    sys.path.insert(0, _p)
            # Obtener clase del panel
            PentestingPanelClass = plugin_module.get_panel_class()

            if not PentestingPanelClass:
                print("[UI] Pentesting plugin panel class not available")
                return
            # Crear panel
            self.pentesting_panel = PentestingPanelClass(parent=self)

            # Agregar al advanced_panel_stack
            if hasattr(self, "advanced_panel_stack"):
                self.advanced_panel_stack.addWidget(self.pentesting_panel)
                print("[UI] Added Pentesting panel to advanced_panel_stack")
            # Verificar si ya existe un botón de Pentesting
            existing_pentest_action = None
            for action in self.side_strip.actions():
                if action.text() == "Pentest" or action.text() == "Pentesting":
                    existing_pentest_action = action
                    print("[UI] Found existing Pentesting button")
                    break
            # Si no existe botón, crearlo
            if (
                not existing_pentest_action
                and "pentesting_tool" not in self.dynamic_plugin_actions
            ):
                print("[UI] Creating new Pentesting button...")
                self.pentesting_action = self._make_strip_action(
                    "pentesting", "Pentesting Suite", self.toggle_pentesting_panel
                )

                # Insertar antes del botón de Plugin Store
                actions = self.side_strip.actions()
                store_index = -1
                for i, action in enumerate(actions):
                    if action.text() == "Plugin Store":
                        store_index = i
                        break
                if store_index >= 0:
                    self.side_strip.insertAction(
                        actions[store_index], self.pentesting_action
                    )
                    print(
                        f"[UI] Inserted Pentesting button before Plugin Store (index {store_index})"
                    )
                else:
                    self.side_strip.addAction(self.pentesting_action)
                    print("[UI] Added Pentesting button to end of sidebar")
                self.dynamic_plugin_actions["pentesting_tool"] = self.pentesting_action
                self.dynamic_plugin_panels["pentesting_tool"] = self.pentesting_panel

                print("[UI] Pentesting plugin loaded and button added to sidebar")
            elif existing_pentest_action:
                print("[UI] Pentesting plugin loaded, using existing button")
                self.dynamic_plugin_panels["pentesting_tool"] = self.pentesting_panel
            else:
                print(
                    "[UI] Pentesting plugin loaded, button already exists in dynamic_plugin_actions"
                )
        except Exception as e:
            print(f"[UI] Error loading Pentesting plugin: {e}")
            import traceback

            traceback.print_exc()
    def _load_ai_live_ide_plugin_dynamic(self, plugin_module):
        """Cargar plugin AI Live IDE dinámicamente.

        DISEÑO UI/UX:
            - El panel se monta DIRECTAMENTE en el área central del navegador,
              dentro de un QSplitter vertical que envuelve a las pestañas web
              (arriba) y al panel del IDE (abajo). NO usamos QDockWidget porque
              eso forzaba al QMainWindow a comprimir la nav_bar y demás
              controles en columnas verticales a los lados del dock.
            - Con este enfoque la nav_bar (URL, recargar, etc.) queda intacta
              ARRIBA y el IDE ocupa el área de contenido sin reorganizar nada
              más.
            - Por defecto, al abrir el IDE se ocultan las pestañas web para
              dar pantalla completa al editor. El usuario puede mostrarlas con
              el botón "Pestañas web" del propio panel (modo split).

        Si el plugin está en `dev_mode` (plugin_config.json) o el usuario
        no está autenticado todavía, instanciamos el panel SIN validator
        para que `@requires_premium` aplique bypass automático.
        """
        try:
            print("[UI] Loading AI Live IDE plugin dynamically...")

            import sys
            from pathlib import Path

            from plugin_paths import resolve_config_file
            plugin_dir = find_plugin_dir("ai_live_ide") or (
                BUNDLED_PLUGINS_DIR / "ai_live_ide"
            )
            if str(plugin_dir) not in sys.path:
                sys.path.insert(0, str(plugin_dir))
            AILiveIDEPanelClass = plugin_module.get_panel_class()

            if not AILiveIDEPanelClass:
                print("[UI] AI Live IDE plugin panel class not available")
                return
            # Detectar modo desarrollo desde plugin_config.json
            import json
            dev_mode = False
            cfg_path = resolve_config_file()
            try:
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf-8") as _f:
                        _cfg = json.load(_f)
                    dev_mode = bool(
                        _cfg.get("ai_live_ide", {}).get("dev_mode", False)
                    )
            except Exception as _e:
                print(f"[UI] Could not read plugin_config.json: {_e}")
            from plugin_policy import dev_mode_allowed
            dev_mode = dev_mode and dev_mode_allowed()
            validator = None if dev_mode else self.plugin_manager
            print(
                f"[UI] AI Live IDE: dev_mode={dev_mode} "
                f"(validator={'None' if validator is None else 'plugin_manager'})"
            )

            # ── 1) Limpiar cualquier dock previo de versiones anteriores ──
            #     (sesiones previas de Qt pueden haber serializado un dock)
            old_dock = getattr(self, "ai_live_ide_dock", None)
            if old_dock is not None:
                try:
                    self.removeDockWidget(old_dock)
                    old_dock.deleteLater()
                except Exception:  # noqa: BLE001
                    pass
                self.ai_live_ide_dock = None

            # ── 2) Reutilizar panel si ya existe ─────────────────────────
            existing_panel = getattr(self, "ai_live_ide_panel", None)
            if existing_panel is not None:
                print("[UI] AI Live IDE panel already exists, reusing")
                self.dynamic_plugin_panels["ai_live_ide"] = existing_panel
                return

            # ── 3) Crear el panel ────────────────────────────────────────
            self.ai_live_ide_panel = AILiveIDEPanelClass(
                plugin_validator=validator,
                parent=self,
            )

            # Conectar señales del panel hacia el host (mostrar/ocultar tabs)
            try:
                self.ai_live_ide_panel.toggle_browser_tabs_requested.connect(
                    self._toggle_browser_tabs_from_ide
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[UI] toggle_browser_tabs signal connect warn: {exc}")
            try:
                self.ai_live_ide_panel.close_ide_requested.connect(
                    self._close_ide_mode
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[UI] close_ide signal connect warn: {exc}")

            # ── 4) Insertar en el área central con un QSplitter vertical ──
            self._ensure_workspace_v_splitter()
            self._workspace_v_splitter.addWidget(self.ai_live_ide_panel)
            self.ai_live_ide_panel.hide()  # oculto hasta activar
            # Stretch: tabs flexible, IDE flexible. Al ocultar uno, el otro
            # ocupa el 100% automáticamente.
            self._workspace_v_splitter.setStretchFactor(0, 1)
            self._workspace_v_splitter.setStretchFactor(1, 1)

            # ── 5) Añadir botón al side strip ────────────────────────────
            existing_action = None
            for action in self.side_strip.actions():
                if action.text() == "AI Live IDE":
                    existing_action = action
                    break
            if (
                not existing_action
                and "ai_live_ide" not in self.dynamic_plugin_actions
            ):
                print("[UI] Creating AI Live IDE side-strip button...")
                self.ai_live_ide_action = self._make_strip_action(
                    "ai_live_ide", "AI Live IDE", self.toggle_ai_live_ide_panel
                )
                actions = self.side_strip.actions()
                store_index = -1
                for i, action in enumerate(actions):
                    if action.text() == "Plugin Store":
                        store_index = i
                        break
                if store_index >= 0:
                    self.side_strip.insertAction(
                        actions[store_index], self.ai_live_ide_action
                    )
                else:
                    self.side_strip.addAction(self.ai_live_ide_action)
                self.dynamic_plugin_actions["ai_live_ide"] = self.ai_live_ide_action
                print("[UI] AI Live IDE button added to sidebar")
            self.dynamic_plugin_panels["ai_live_ide"] = self.ai_live_ide_panel

            # Refrescar UI premium una vez con el validador real
            if hasattr(self.ai_live_ide_panel, "update_premium_ui"):
                self.ai_live_ide_panel.update_premium_ui("ai_live_ide")
            print("[UI] AI Live IDE plugin loaded successfully (central area)")
        except Exception as e:
            print(f"[UI] Error loading AI Live IDE plugin: {e}")
            import traceback

            traceback.print_exc()

    # ── Helpers de integración con el área central ───────────────────────

    def _ensure_workspace_v_splitter(self):
        """Crea (idempotente) un QSplitter vertical que envuelve las
        pestañas web del navegador y deja sitio para el panel del IDE
        debajo. La nav_bar (URL/controles) queda intacta arriba porque
        vive en `main_layout`, fuera del `content_splitter`.
        """
        if getattr(self, "_workspace_v_splitter", None) is not None:
            return
        from PySide6.QtWidgets import QSplitter as _QSplitter

        tabs = getattr(self.tab_manager, "tabs", None)
        if tabs is None:
            print("[UI] tab_manager.tabs missing — no se puede crear split")
            return
        cs = self.content_splitter
        tabs_idx = cs.indexOf(tabs)
        if tabs_idx < 0:
            print("[UI] tabs widget no está en content_splitter")
            return
        sizes_before = cs.sizes()

        v_splitter = _QSplitter(Qt.Vertical)
        v_splitter.setObjectName("aiLiveIdeWorkspaceSplit")
        v_splitter.setChildrenCollapsible(True)
        v_splitter.setHandleWidth(2)
        v_splitter.setStyleSheet(
            "QSplitter::handle { background: rgba(255,255,255,0.06); } "
            "QSplitter::handle:hover { background: rgba(75,158,255,0.40); }"
        )
        # Mover las tabs al splitter vertical (arriba)
        tabs.setParent(None)
        v_splitter.addWidget(tabs)
        # Insertar el splitter en la misma posición que ocupaban las tabs
        cs.insertWidget(tabs_idx, v_splitter)
        cs.setSizes(sizes_before)
        cs.setStretchFactor(tabs_idx, 1)
        self._workspace_v_splitter = v_splitter
        print("[UI] Created vertical workspace splitter for AI Live IDE")

    def toggle_ai_live_ide_panel(self):
        """Activar/desactivar el modo IDE en el área central."""
        panel = getattr(self, "ai_live_ide_panel", None)
        if panel is None:
            print("[UI] AI Live IDE panel not initialized yet")
            return
        if panel.isVisible():
            self._close_ide_mode()
        else:
            self._open_ide_mode()

    def _open_ide_mode(self):
        """Entra en modo IDE: oculta las pestañas web y muestra el panel
        del IDE ocupando todo el área de contenido. La nav_bar y la
        side_strip quedan visibles e interactivas.
        """
        panel = getattr(self, "ai_live_ide_panel", None)
        if panel is None:
            return
        v_splitter = getattr(self, "_workspace_v_splitter", None)
        tabs = getattr(self.tab_manager, "tabs", None) if hasattr(
            self, "tab_manager"
        ) else None
        if tabs is not None:
            if not hasattr(self, "_browser_tabs_prev_visible"):
                self._browser_tabs_prev_visible = tabs.isVisible()
            tabs.hide()
        panel.show()
        # Sincronizar el toggle del propio panel
        if hasattr(panel, "_act_toggle_browser_tabs"):
            try:
                panel._act_toggle_browser_tabs.blockSignals(True)
                panel._act_toggle_browser_tabs.setChecked(False)
                panel._act_toggle_browser_tabs.blockSignals(False)
            except Exception:  # noqa: BLE001
                pass
        # Ajustar el split vertical para que el IDE ocupe el 100%
        if v_splitter is not None:
            v_splitter.setSizes([0, v_splitter.height() or 800])
        # Refrescar estado premium al mostrarse
        if hasattr(panel, "update_premium_ui"):
            panel.update_premium_ui("ai_live_ide")

    def _close_ide_mode(self):
        """Sale del modo IDE: oculta el panel del IDE y restaura las
        pestañas web del navegador.
        """
        panel = getattr(self, "ai_live_ide_panel", None)
        if panel is None:
            return
        panel.hide()
        tabs = getattr(self.tab_manager, "tabs", None) if hasattr(
            self, "tab_manager"
        ) else None
        if tabs is not None:
            # Restauramos tabs si fueron ocultadas por nosotros
            if getattr(self, "_browser_tabs_prev_visible", True):
                tabs.show()
            if hasattr(self, "_browser_tabs_prev_visible"):
                delattr(self, "_browser_tabs_prev_visible")
        v_splitter = getattr(self, "_workspace_v_splitter", None)
        if v_splitter is not None:
            v_splitter.setSizes([v_splitter.height() or 800, 0])

    def _toggle_browser_tabs_from_ide(self):
        """Slot llamado por el panel del IDE cuando el usuario pulsa
        'Pestañas web': alterna la visibilidad del QTabWidget mientras
        seguimos en modo IDE (vista split).
        """
        tabs = getattr(self.tab_manager, "tabs", None) if hasattr(
            self, "tab_manager"
        ) else None
        if tabs is None:
            return
        panel = getattr(self, "ai_live_ide_panel", None)
        v_splitter = getattr(self, "_workspace_v_splitter", None)
        if tabs.isVisible():
            tabs.hide()
            # IDE ocupa todo
            if v_splitter is not None:
                v_splitter.setSizes([0, v_splitter.height() or 800])
            if panel is not None and hasattr(panel, "_act_toggle_browser_tabs"):
                try:
                    panel._act_toggle_browser_tabs.blockSignals(True)
                    panel._act_toggle_browser_tabs.setChecked(False)
                    panel._act_toggle_browser_tabs.blockSignals(False)
                except Exception:  # noqa: BLE001
                    pass
        else:
            tabs.show()
            # Split 40% tabs / 60% IDE
            if v_splitter is not None:
                total = v_splitter.height() or 800
                v_splitter.setSizes([int(total * 0.40), int(total * 0.60)])
            if panel is not None and hasattr(panel, "_act_toggle_browser_tabs"):
                try:
                    panel._act_toggle_browser_tabs.blockSignals(True)
                    panel._act_toggle_browser_tabs.setChecked(True)
                    panel._act_toggle_browser_tabs.blockSignals(False)
                except Exception:  # noqa: BLE001
                    pass
    def _load_themes_plugin_dynamic(self, plugin_instance):
        """Cargar plugin de temas dinámicamente"""
        try:
            print("[UI] Loading themes plugin dynamically...")
            print(f"[UI] Plugin instance: {plugin_instance}")

            # Solo guardar la referencia al plugin, NO crear dock widget
            # El widget se creará cuando se abra el diálogo
            self.themes_plugin_instance = plugin_instance
            print("[UI] Saved plugin instance reference for later dialog creation")

            # Verificar si ya existe un botón de temas (del setup_side_strip hardcodeado)
            existing_theme_action = None

            # Verificar si existe self.theme_action del setup estático
            if hasattr(self, "theme_action") and self.theme_action:
                existing_theme_action = self.theme_action
                print(
                    "[UI] Found existing theme button from static setup (self.theme_action)"
                )

                # Desconectar TODAS las conexiones previas
                try:
                    existing_theme_action.triggered.disconnect()
                    print("[UI] Disconnected all previous callbacks")
                except Exception as e:
                    print(f"[UI] Could not disconnect callbacks: {e}")
                # Conectar el nuevo callback
                existing_theme_action.triggered.connect(self.toggle_themes_panel)
                existing_theme_action.setToolTip("Gestor de Temas Avanzado")
                print("[UI] Reconnected theme button to toggle_themes_panel")
                # Asegurar ruta SVG para re-tinte al cambiar tema
                tp = os.path.abspath("icons/themes.svg")
                if os.path.isfile(tp):
                    existing_theme_action.setProperty("strip_icon_path", tp)
            # Si no existe botón (ni estático ni dinámico), crearlo
            if (
                not existing_theme_action
                and "themes" not in self.dynamic_plugin_actions
            ):
                print("[UI] Creating new themes button...")

                # Intentar obtener acciones del toolbar del plugin
                toolbar_actions = []
                if hasattr(plugin_instance, "get_toolbar_actions"):
                    toolbar_actions = plugin_instance.get_toolbar_actions()
                # Si el plugin provee acciones, usar la primera como botón principal
                if toolbar_actions and len(toolbar_actions) > 0:
                    # Usar el icono/acción del plugin pero conectarlo a nuestro toggle
                    theme_action = toolbar_actions[0]
                    # Reconectar para abrir el panel en lugar de toggle rápido
                    try:
                        theme_action.triggered.disconnect()
                    except:
                        pass
                    theme_action.triggered.connect(self.toggle_themes_panel)
                    theme_action.setToolTip("Gestor de Temas Avanzado")
                    self.themes_action = theme_action
                    tp = os.path.abspath("icons/themes.svg")
                    if os.path.isfile(tp):
                        self.themes_action.setProperty("strip_icon_path", tp)
                else:
                    # Crear botón personalizado con tinte según tema
                    tp = os.path.abspath("icons/themes.svg")
                    ic_col = "#5F6368"
                    if THEME_SYSTEM_AVAILABLE:
                        tm = get_theme_manager()
                        if tm:
                            ic_col = tm.get_theme_data().get("colors", {}).get(
                                "icon_color", "#5F6368"
                            )
                    ic = build_strip_icon(tp, ic_col, self.side_strip.iconSize())
                    self.themes_action = QAction(
                        ic if not ic.isNull() else QIcon("icons/themes.svg"),
                        "Temas",
                        self,
                    )
                    self.themes_action.setProperty("strip_icon_path", tp)
                    self.themes_action.setToolTip("Gestor de Temas Avanzado")
                    self.themes_action.triggered.connect(self.toggle_themes_panel)
                # Insertar antes del botón de Plugin Store
                actions = self.side_strip.actions()
                store_index = -1
                for i, action in enumerate(actions):
                    if action.text() == "Plugin Store":
                        store_index = i
                        break
                if store_index >= 0:
                    self.side_strip.insertAction(
                        actions[store_index], self.themes_action
                    )
                    print(
                        f"[UI] Inserted themes button before Plugin Store (index {store_index})"
                    )
                else:
                    self.side_strip.addAction(self.themes_action)
                    print("[UI] Added themes button to end of sidebar")
                self.dynamic_plugin_actions["themes"] = self.themes_action
            print("[UI] Themes plugin button configured successfully")
            self._refresh_side_strip_icons()
        except Exception as e:
            print(f"[UI] Error loading themes plugin: {e}")
            import traceback

            traceback.print_exc()
    def _ensure_themes_panel_widget(self):
        """Construye el panel de temas (selector + editor) en el stack lateral."""
        if self.themes_panel_widget is not None:
            return self.themes_panel_widget
        if not getattr(self, "themes_plugin_instance", None):
            print("[UI] Themes plugin not loaded")
            return None
        from PySide6.QtWidgets import QTabWidget, QVBoxLayout

        try:
            sel = None
            ed = None
            if hasattr(self.themes_plugin_instance, "get_theme_selector"):
                sel = self.themes_plugin_instance.get_theme_selector()
            if hasattr(self.themes_plugin_instance, "get_theme_editor"):
                ed = self.themes_plugin_instance.get_theme_editor()
            if not sel and hasattr(self.themes_plugin_instance, "get_settings_widget"):
                sel = self.themes_plugin_instance.get_settings_widget()
            if not sel and not ed:
                print("[UI] No theme widgets from plugin")
                return None
            container = QWidget()
            container.setObjectName("themesPanelContainer")
            lay = QVBoxLayout(container)
            lay.setContentsMargins(0, 0, 0, 0)
            tabs = QTabWidget()
            if sel:
                tabs.addTab(sel, "Temas")
            if ed:
                tabs.addTab(ed, "Editor")
            lay.addWidget(tabs)
            self.themes_panel_widget = container
            return self.themes_panel_widget
        except Exception as e:
            print(f"[UI] Error building themes panel: {e}")
            import traceback

            traceback.print_exc()
            return None
    def toggle_themes_panel(self):
        """Muestra/oculta el gestor de temas en el panel lateral (sin ventanas emergentes)."""
        print("[UI] toggle_themes_panel() called")
        panel = self._ensure_themes_panel_widget()
        if not panel:
            self.open_theme_selector()
            return
        if (
            self.advanced_panel_stack.currentWidget() == panel
            and self.advanced_panel_stack.isVisible()
        ):
            self.hide_advanced_panel()
        else:
            self.show_advanced_panel(panel)
    def toggle_seo_panel(self):
        """Toggle visibility of SEO panel"""
        if hasattr(self, "seo_dock"):
            if self.seo_dock.isVisible():
                self.seo_dock.hide()
            else:
                self.seo_dock.show()
                self.seo_dock.raise_()
    def toggle_split_view(self):
        """Toggle Split View si el plugin está cargado"""
        try:
            plugin = None
            if hasattr(self, "dynamic_plugin_panels"):
                plugin = self.dynamic_plugin_panels.get("split_view")
            if plugin and hasattr(plugin, "toggle_split_view"):
                plugin.toggle_split_view()
            else:
                print(
                    "[UI] Split View plugin not loaded or missing toggle_split_view()"
                )
        except Exception as e:
            print(f"[UI] Error toggling Split View: {e}")
    def on_plugin_unloaded(self, plugin_id: str):
        """
        Manejar la descarga de un plugin dinámicamente
        Remover botón del sidebar y panel
        """
        print(f"[UI] Plugin unloaded signal received: {plugin_id}")

        try:
            # Remover acción del sidebar
            if plugin_id in self.dynamic_plugin_actions:
                action = self.dynamic_plugin_actions[plugin_id]
                self.side_strip.removeAction(action)
                del self.dynamic_plugin_actions[plugin_id]
                print(f"[UI] Removed {plugin_id} button from sidebar")
            # Remover panel
            if plugin_id in self.dynamic_plugin_panels:
                del self.dynamic_plugin_panels[plugin_id]
                print(f"[UI] Removed {plugin_id} panel")
            # Limpiar referencias específicas
            if plugin_id == "scraping":
                if hasattr(self, "scraping_dock") and self.scraping_dock:
                    self.scraping_dock.hide()
                    self.scraping_dock.setWidget(None)
                self.scraping_panel = None
                self.scraping_integration = None
            elif plugin_id == "proxy":
                if hasattr(self, "proxy_dock") and self.proxy_dock:
                    self.proxy_dock.hide()
                    self.proxy_dock.setWidget(None)
                self.proxy_panel = None
            elif plugin_id == "seo_analyzer":
                if hasattr(self, "seo_dock") and self.seo_dock:
                    self.seo_dock.hide()
                    self.seo_dock.setWidget(None)
                self.seo_panel = None
            elif plugin_id == "ai_live_ide":
                # Oculta el panel y restaura las pestañas del navegador antes
                # de soltar la referencia, para que el IDE premium deje de
                # ser accesible inmediatamente tras perder la licencia/sesión.
                if hasattr(self, "_close_ide_mode"):
                    try:
                        self._close_ide_mode()
                    except Exception:
                        pass
                old_dock = getattr(self, "ai_live_ide_dock", None)
                if old_dock is not None:
                    try:
                        self.removeDockWidget(old_dock)
                        old_dock.deleteLater()
                    except Exception:
                        pass
                    self.ai_live_ide_dock = None
                panel = getattr(self, "ai_live_ide_panel", None)
                if panel is not None:
                    try:
                        panel.setParent(None)
                        panel.deleteLater()
                    except Exception:
                        pass
                self.ai_live_ide_panel = None
        except Exception as e:
            print(f"[UI] Error unloading plugin UI for {plugin_id}: {e}")
            import traceback

            traceback.print_exc()
    # ========== MÉTODOS DEL MENÚ PRINCIPAL ==========

    def open_new_window(self):
        """Abrir una nueva ventana del navegador"""
        try:
            import subprocess
            import sys

            subprocess.Popen([sys.executable, "main.py"])
            print("[Menu] Nueva ventana abierta")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo abrir nueva ventana: {e}")
    def open_private_window(self):
        """Abrir una ventana de navegación privada"""
        try:
            import subprocess
            import sys

            subprocess.Popen([sys.executable, "main.py", "--private"])
            print("[Menu] Ventana privada abierta")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"No se pudo abrir ventana privada: {e}")
    def show_bookmarks_panel(self):
        """Mostrar panel de marcadores"""
        if hasattr(self, "bookmark_manager") and self.bookmark_manager:
            self.bookmark_manager.show()
    def show_downloads(self):
        """Mostrar panel de descargas"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            download_folder = os.path.expanduser("~/Downloads")
            if os.path.exists(download_folder):
                try:
                    import subprocess
                    import platform

                    if platform.system() == "Windows":
                        os.startfile(download_folder)
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.Popen(["open", download_folder])
                    else:  # Linux
                        subprocess.Popen(["xdg-open", download_folder])
                except Exception as e:
                    QMessageBox.information(
                        self, "Descargas", f"Carpeta de descargas: {download_folder}"
                    )
    def show_plugins_panel(self):
        """Mostrar panel de plugins/extensiones"""
        if hasattr(self, "unified_plugin_panel") and self.unified_plugin_panel:
            self.unified_plugin_panel.show()
            self.unified_plugin_panel.raise_()
    def print_page(self):
        """Imprimir página actual"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser and hasattr(current_browser, "page"):
            try:
                from PySide6.QtPrintSupport import QPrintDialog, QPrinter

                printer = QPrinter(QPrinter.HighResolution)
                dialog = QPrintDialog(printer, self)
                if dialog.exec():
                    current_browser.page().print(
                        printer,
                        lambda success: print(f"[Menu] Página impresa: {success}"),
                    )
            except ImportError:
                QMessageBox.warning(self, "Error", "Módulo de impresión no disponible")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Error al imprimir: {e}")
    def save_page_as(self):
        """Guardar página actual"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser and hasattr(current_browser, "url"):
            from PySide6.QtWidgets import QFileDialog

            url = current_browser.url().toString()
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Guardar página como",
                os.path.expanduser("~"),
                "HTML Files (*.html *.htm);;All Files (*.*)",
            )
            if filename:
                try:
                    current_browser.page().save(filename)
                    QMessageBox.information(
                        self, "Éxito", f"Página guardada en: {filename}"
                    )
                except Exception as e:
                    QMessageBox.warning(
                        self, "Error", f"No se pudo guardar la página: {e}"
                    )
    def show_find_dialog(self):
        """Mostrar diálogo de búsqueda en página"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            from PySide6.QtWidgets import QInputDialog

            text, ok = QInputDialog.getText(self, "Buscar en página", "Texto a buscar:")
            if ok and text:
                current_browser.findText(text)
    def zoom_in(self):
        """Aumentar zoom de la página"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            current_zoom = current_browser.zoomFactor()
            new_zoom = min(current_zoom + 0.1, 5.0)  # Máximo 500%
            current_browser.setZoomFactor(new_zoom)
            self.status_bar.update_zoom(new_zoom)  # Actualizar status bar
            print(f"[Menu] Zoom aumentado a {int(new_zoom * 100)}%")
    def zoom_out(self):
        """Reducir zoom de la página"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            current_zoom = current_browser.zoomFactor()
            new_zoom = max(current_zoom - 0.1, 0.25)  # Mínimo 25%
            current_browser.setZoomFactor(new_zoom)
            self.status_bar.update_zoom(new_zoom)  # Actualizar status bar
            print(f"[Menu] Zoom reducido a {int(new_zoom * 100)}%")
    def zoom_reset(self):
        """Restablecer zoom al 100%"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            current_browser.setZoomFactor(1.0)
            self.status_bar.update_zoom(1.0)  # Actualizar status bar
            print("[Menu] Zoom restablecido a 100%")
    def _connect_browser_to_statusbar(self, index=None):
        """Conectar señales del browser actual al status bar"""
        if index is None:
            index = self.tab_manager.tabs.currentIndex()
        if index < 0:
            return
        browser = self.tab_manager.tabs.widget(index)
        if not browser:
            return
        # Obtener la página del browser
        page = browser.page()
        if not page:
            return
        # IMPORTANTE: NO desconectar browser.urlChanged porque eliminaría
        # la conexión crítica que actualiza la barra de URL en tabs.py
        # Solo desconectamos las señales específicas del status bar si existen

        import warnings as _warnings

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore", RuntimeWarning)
            try:
                page.linkHovered.disconnect(self.status_bar.update_url_hover)
            except Exception:
                pass
            try:
                browser.loadProgress.disconnect(self.status_bar.update_load_progress)
            except Exception:
                pass
        try:
            page.loadStarted.disconnect()
        except:
            pass
        try:
            page.loadFinished.disconnect()
        except:
            pass
        # Indicador SSL en la navbar (reemplaza la barra de estado inferior)
        if hasattr(self, "ssl_indicator"):
            browser.urlChanged.connect(
                lambda url: self.ssl_indicator.update_ssl(url.toString())
            )
            current_url = browser.url().toString()
            if current_url:
                self.ssl_indicator.update_ssl(current_url)

        # Status bar oculta — mantener señales funcionales para showMessage()
        browser.loadProgress.connect(self.status_bar.update_load_progress)
        page.loadStarted.connect(
            lambda: self.status_bar.update_load_status("Cargando...")
        )
        page.loadFinished.connect(lambda: self.status_bar.update_load_status(""))

        # Actualizar zoom level
        zoom_factor = browser.zoomFactor()
        self.status_bar.update_zoom(zoom_factor)
    def toggle_fullscreen(self):
        """Alternar modo pantalla completa"""
        if self.isFullScreen():
            self.showNormal()
            print("[Menu] Modo pantalla completa desactivado")
        else:
            self.showFullScreen()
            print("[Menu] Modo pantalla completa activado")
    def show_clear_data_dialog(self):
        """Mostrar diálogo para limpiar datos de navegación"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Limpiar datos de navegación")
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("Seleccione los datos a eliminar:"))

        history_check = QCheckBox("Historial de navegación")
        history_check.setChecked(True)
        layout.addWidget(history_check)

        cache_check = QCheckBox("Caché")
        cache_check.setChecked(True)
        layout.addWidget(cache_check)

        cookies_check = QCheckBox("Cookies y datos de sitios")
        layout.addWidget(cookies_check)

        passwords_check = QCheckBox("Contraseñas guardadas")
        layout.addWidget(passwords_check)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec():
            try:
                if history_check.isChecked():
                    self.history_manager.clear_history()
                    print("[Menu] Historial limpiado")
                if cache_check.isChecked():
                    profile = QWebEngineProfile.defaultProfile()
                    profile.clearHttpCache()
                    print("[Menu] Caché limpiado")
                if cookies_check.isChecked():
                    profile = QWebEngineProfile.defaultProfile()
                    profile.cookieStore().deleteAllCookies()
                    print("[Menu] Cookies eliminadas")
                if passwords_check.isChecked() and hasattr(self, "password_manager"):
                    self.password_manager.clear_all_passwords()
                QMessageBox.information(
                    self, "Éxito", "Datos de navegación eliminados correctamente"
                )
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Error al limpiar datos: {e}")
    def show_network_settings(self):
        """Mostrar configuración de red e interceptación"""
        if hasattr(self, "network_interceptor"):
            dialog = NetworkSettingsDialog(self.network_interceptor, self)
            dialog.exec()
        else:
            QMessageBox.warning(
                self,
                "Network Interceptor no disponible",
                "El interceptor de red no está inicializado.",
            )
    def show_homepage_settings(self, parent_dialog=None):
        """Mostrar configuración de página de inicio"""
        if hasattr(self, "homepage_manager") and self.homepage_manager:
            dialog = HomepageSettingsDialog(
                self.homepage_manager, parent_dialog or self
            )
            dialog.exec()
        else:
            QMessageBox.warning(
                self,
                "Homepage Manager no disponible",
                "El gestor de página de inicio no está inicializado.",
            )
    def show_userscripts(self):
        """Mostrar gestor de UserScripts"""
        if hasattr(self, "userscript_manager"):
            dialog = UserScriptDialog(self.userscript_manager, self)
            dialog.exec()
        else:
            QMessageBox.warning(
                self,
                "UserScript Manager no disponible",
                "El gestor de UserScripts no está inicializado.",
            )
    def change_visual_theme(self, theme_name):
        """Cambiar tema visual del navegador (light, dark, blue)"""
        try:
            # Cambiar tema en el theme manager
            self.modern_styles.change_theme(theme_name)

            # Aplicar nuevos estilos a la navbar usando ThemeEngine
            self._refresh_navbar_style()

            # Aplicar nuevo estilo al URL bar (vía ThemeEngine)
            self._refresh_url_bar_style()

            # Aplicar nuevo estilo a las pestañas (vía ThemeEngine para respetar el tema)
            self._refresh_tab_bar_style()

            # Mensaje de confirmación en status bar
            theme_names = {"light": "Claro", "dark": "Oscuro", "blue": "Azul"}
            self.status_bar.showMessage(
                f"Tema cambiado a: {theme_names.get(theme_name, theme_name)}", 3000
            )

            print(f"[THEME] Tema visual cambiado a: {theme_name}")
        except Exception as e:
            QMessageBox.warning(
                self, "Error al cambiar tema", f"No se pudo cambiar el tema: {str(e)}"
            )
            print(f"[ERROR] Error al cambiar tema visual: {e}")
    def toggle_dev_tools(self):
        """Alternar herramientas de desarrollador"""
        if hasattr(self, "devtools_dock") and self.devtools_dock:
            if self.devtools_dock.isVisible():
                self.devtools_dock.hide()
                print("[Menu] DevTools ocultadas")
            else:
                self.devtools_dock.show()
                print("[Menu] DevTools mostradas")
    def show_task_manager(self):
        """Mostrar administrador de tareas del navegador"""
        QMessageBox.information(
            self,
            "Administrador de tareas",
            "Administrador de tareas del navegador\n\n"
            "Pestaña actual: "
            + (
                self.tab_manager.tabs.tabText(self.tab_manager.tabs.currentIndex())
                if self.tab_manager.tabs.count() > 0
                else "Ninguna"
            )
            + f"\nTotal de pestañas: {self.tab_manager.tabs.count()}",
        )
    def show_screenshot_dialog(self):
        """Mostrar diálogo de captura de pantalla"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser:
            screenshot_tool = ScreenshotTool(current_browser, self)
            screenshot_tool.show_screenshot_dialog()
    def show_region_capture(self):
        """Captura de región específica"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if not current_browser:
            QMessageBox.warning(self, "Sin página", "No hay ninguna página activa.")
            return
        # Capturar pantalla completa primero
        screenshot_tool = ScreenshotTool(current_browser, self)
        full_image = screenshot_tool.capture_visible_area()

        if full_image:
            # Mostrar selector de región
            selector = RegionSelector(full_image, self)
            selector.region_selected.connect(
                lambda rect: self._save_region_capture(full_image, rect)
            )
            selector.show()
    def _save_region_capture(self, image, rect):
        """Guardar captura de región"""
        # Recortar imagen
        cropped = image.copy(rect)

        # Guardar
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime

        default_name = f"region_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar captura de región",
            os.path.join(os.path.expanduser("~"), "Pictures", default_name),
            "PNG Image (*.png);;JPEG Image (*.jpg)",
        )

        if filename:
            cropped.save(filename)
            QMessageBox.information(
                self, "Guardado", f"Captura guardada en:\n{filename}"
            )
    def show_annotated_capture(self):
        """Captura con editor de anotaciones"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if not current_browser:
            QMessageBox.warning(self, "Sin página", "No hay ninguna página activa.")
            return
        # Capturar pantalla
        screenshot_tool = ScreenshotTool(current_browser, self)
        image = screenshot_tool.capture_visible_area()

        if image:
            # Abrir editor de anotaciones
            editor = AnnotationEditor(image, self)
            if editor.exec() == QDialog.Accepted:
                annotated_image = editor.get_annotated_image()

                # Guardar
                from PySide6.QtWidgets import QFileDialog
                from datetime import datetime

                default_name = (
                    f"annotated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                )
                filename, _ = QFileDialog.getSaveFileName(
                    self,
                    "Guardar captura anotada",
                    os.path.join(os.path.expanduser("~"), "Pictures", default_name),
                    "PNG Image (*.png);;JPEG Image (*.jpg)",
                )

                if filename:
                    annotated_image.save(filename)
                    QMessageBox.information(
                        self, "Guardado", f"Captura guardada en:\n{filename}"
                    )
    def show_performance_monitor(self):
        """Mostrar administrador de tareas"""
        monitor = PerformanceMonitor(self)
        monitor.show()
    def run_performance_diagnostic(self):
        """Ejecutar diagnóstico de rendimiento"""
        PerformanceDiagnostic.run_diagnostic(self)
    def save_current_session(self):
        """Guardar sesión actual con nombre"""
        if not self.session_manager:
            QMessageBox.warning(self, "Error", "Session Manager no disponible")
            return
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Guardar sesión", "Nombre de la sesión:")

        if ok and name:
            self.session_manager.save_named_session(name)
    def show_session_manager(self):
        """Mostrar gestor de sesiones"""
        if not self.session_manager:
            QMessageBox.warning(self, "Error", "Session Manager no disponible")
            return
        self.session_manager.show_session_manager_dialog()
    def show_userscript_manager(self):
        """Mostrar gestor de UserScripts"""
        if hasattr(self, "userscript_manager") and self.userscript_manager:
            dialog = UserScriptDialog(self.userscript_manager, self)
            dialog.exec()
        else:
            QMessageBox.warning(
                self,
                "UserScript Manager no disponible",
                "El gestor de UserScripts no está inicializado.",
            )
    def view_page_source(self):
        """Ver código fuente de la página"""
        current_browser = self.tab_manager.tabs.currentWidget()
        if current_browser and hasattr(current_browser, "page"):
            current_browser.page().toHtml(self._show_source_dialog)
    def _show_source_dialog(self, html):
        """Mostrar diálogo con código fuente"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit

        dialog = QDialog(self)
        dialog.setWindowTitle("Código fuente de la página")
        dialog.setMinimumSize(800, 600)

        layout = QVBoxLayout(dialog)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(html)
        layout.addWidget(text_edit)

        dialog.exec()
    def show_settings(self):
        """Mostrar panel de configuración"""
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QTabWidget,
            QWidget,
            QLabel,
            QGroupBox,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Configuración - Katphi")
        dialog.setMinimumSize(600, 500)

        layout = QVBoxLayout(dialog)

        tabs = QTabWidget()

        # Tab 1: General
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.addWidget(QLabel("Configuración general del navegador"))

        appearance_gb = QGroupBox("Ventana")
        apl = QVBoxLayout(appearance_gb)
        frameless_chk = QCheckBox(
            "Ventana sin marco del sistema (botones − □ en la barra superior)"
        )
        frameless_chk.setChecked(
            self.settings.value("ui/frameless_window", False, type=bool)
        )
        frameless_chk.setToolTip(
            "Oculta la decoración nativa del escritorio.\n"
            "Arrastra la ventana desde el espacio flexible entre la URL "
            "y los iconos derechos."
        )
        frameless_chk.toggled.connect(
            lambda c: self._set_frameless_window(bool(c), persist=True)
        )
        self._frameless_settings_check = frameless_chk
        apl.addWidget(frameless_chk)
        apl.addStretch(1)
        general_layout.addWidget(appearance_gb)

        # Página de inicio
        if hasattr(self, "homepage_manager") and self.homepage_manager:
            homepage_section = QGroupBox("Página de inicio y nuevas pestañas")
            homepage_layout = QVBoxLayout()

            # Botón para configurar página de inicio
            homepage_btn = QPushButton("Configurar página de inicio")
            homepage_btn.clicked.connect(lambda: self.show_homepage_settings(dialog))
            homepage_btn.setMaximumWidth(250)
            homepage_btn.setStyleSheet("""
                QPushButton {
                    padding: 8px 16px;
                    background-color: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
            """)
            homepage_layout.addWidget(homepage_btn)

            # Mostrar configuración actual
            current_type = self.homepage_manager.homepage_type
            type_labels = {
                "blank": "Página en blanco",
                "search_engine": "Motor de búsqueda predeterminado",
                "custom_url": f"URL personalizada: {self.homepage_manager.custom_url}",
                "new_tab_page": "Página de nueva pestaña",
            }
            current_label = QLabel(
                f"Actual: {type_labels.get(current_type, 'No configurada')}"
            )
            current_label.setStyleSheet(
                "color: #666; font-size: 11px; margin-top: 5px;"
            )
            homepage_layout.addWidget(current_label)

            homepage_section.setLayout(homepage_layout)
            general_layout.addWidget(homepage_section)
        general_layout.addStretch()
        tabs.addTab(general_tab, "General")

        # Tab 2: Búsqueda
        if hasattr(self, "search_engine_manager") and self.search_engine_manager:
            search_settings = SearchEngineSettingsDialog(
                self.search_engine_manager, dialog
            )
            # Usar el contenido del diálogo como tab
            search_tab = QWidget()
            search_layout = QVBoxLayout(search_tab)

            # Motor predeterminado
            default_layout = QHBoxLayout()
            default_layout.addWidget(QLabel("Motor predeterminado:"))

            default_combo = QComboBox()
            for engine in self.search_engine_manager.get_all_engines():
                default_combo.addItem(engine.name, engine.id)
            current_engine = self.search_engine_manager.get_default_engine()
            if current_engine:
                index = default_combo.findData(current_engine.id)
                if index >= 0:
                    default_combo.setCurrentIndex(index)
            default_combo.currentIndexChanged.connect(
                lambda idx: self.search_engine_manager.set_default_engine(
                    default_combo.itemData(idx)
                )
            )
            default_layout.addWidget(default_combo)
            default_layout.addStretch()

            search_layout.addLayout(default_layout)

            # Lista de motores
            search_layout.addWidget(QLabel("Motores disponibles:"))
            engines_list = QListWidget()
            for engine in self.search_engine_manager.get_all_engines():
                engines_list.addItem(f"{engine.name} - {engine.url_template}")
            search_layout.addWidget(engines_list)

            search_layout.addStretch()
            tabs.addTab(search_tab, "Búsqueda")
        # Tab 3: Privacidad
        privacy_tab = QWidget()
        privacy_layout = QVBoxLayout(privacy_tab)
        privacy_layout.addWidget(QLabel("Configuración de privacidad"))
        privacy_btn = QPushButton("Abrir panel de privacidad")
        privacy_btn.clicked.connect(lambda: self.toggle_privacy_panel())
        privacy_layout.addWidget(privacy_btn)
        privacy_layout.addStretch()
        tabs.addTab(privacy_tab, "Privacidad")

        layout.addWidget(tabs)

        # Botón cerrar
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        def _cleanup_frameless_ref(_result=None):
            setattr(self, "_frameless_settings_check", None)

        dialog.finished.connect(_cleanup_frameless_ref)
        dialog.exec()
    def show_about(self):
        """Mostrar información acerca de"""
        QMessageBox.about(
            self,
            "Acerca de Katphi",
            "<h2>Katphi Browser</h2>"
            "<p>Navegador profesional con capacidades avanzadas de scraping.</p>"
            "<p><b>Versión:</b> 3.4.7</p>"
            "<p><b>Motor:</b> QtWebEngine (Chromium)</p>"
            "<p><b>Framework:</b> PySide6</p>"
            "<br>"
            "<p>© 2024 Katphi. Todos los derechos reservados.</p>",
        )
    def report_issue(self):
        """Informar de un problema"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Informar de un problema")
        dialog.setMinimumSize(500, 400)

        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("Describe el problema que encontraste:"))

        text_edit = QTextEdit()
        text_edit.setPlaceholderText(
            "Por favor describe el problema con el mayor detalle posible...\n\n"
            "Incluye:\n"
            "- Qué estabas haciendo\n"
            "- Qué esperabas que sucediera\n"
            "- Qué sucedió en su lugar"
        )
        layout.addWidget(text_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        if dialog.exec():
            issue_text = text_edit.toPlainText()
            if issue_text.strip():
                QMessageBox.information(
                    self,
                    "Gracias",
                    "Gracias por tu reporte. Hemos registrado el problema.",
                )
                print(f"[Menu] Problema reportado: {issue_text[:100]}...")
            else:
                QMessageBox.warning(
                    self, "Aviso", "Por favor describe el problema antes de enviar."
                )


class UrlBar(QLineEdit):
    def __init__(self, parent=None, load_url_callback=None):
        super().__init__(parent)
        self.load_url_callback = load_url_callback
    def insertFromMimeData(self, source):
        # Llama al método original para pegar el texto
        super().insertFromMimeData(source)
        text = self.text().strip()
        if self.load_url_callback and text:
            # Si el texto pegado es un enlace, navega automáticamente
            if text.startswith(("http://", "https://")) or (
                "." in text and " " not in text
            ):
                self.load_url_callback(text)
