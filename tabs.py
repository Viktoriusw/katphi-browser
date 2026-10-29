import json

import os

import sys

from PySide6.QtWidgets import QTabWidget, QTabBar, QMenu, QPushButton, QStackedWidget, QToolButton, QWidget, QHBoxLayout

from PySide6.QtWebEngineWidgets import QWebEngineView

from PySide6.QtCore import QUrl, Qt, QSettings, Signal, QEvent, QSize

from PySide6.QtGui import QIcon, QKeySequence, QShortcut

from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineSettings

from tab_groups import TabGroupManager

import app_scheme


def _is_private_mode() -> bool:
    """True si este proceso es una ventana privada (--private)."""
    try:
        from constants import is_private_mode
        return is_private_mode()
    except Exception:
        return "--private" in sys.argv


# Perfil off-the-record compartido por todas las pestañas de la ventana privada
_private_profile = None


def get_private_profile():
    """Devuelve (y crea una sola vez) el perfil sin nombre de la ventana privada.

    Un QWebEngineProfile sin storageName es off-the-record: cookies, caché,
    localStorage e IndexedDB viven solo en memoria y se pierden al cerrar.
    """
    global _private_profile
    if _private_profile is None:
        from PySide6.QtWidgets import QApplication
        # Parent = QApplication: el perfil sobrevive a todas las páginas
        _private_profile = QWebEngineProfile(QApplication.instance())
        try:
            _private_profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
            _private_profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        except Exception as e:
            print(f"[PRIVATE] Could not configure private profile: {e}")
        print(f"[PRIVATE] Off-the-record profile created (offTheRecord={_private_profile.isOffTheRecord()})")
    return _private_profile


_storage_profile_id = None


def apply_profile_storage(profile_manager):
    """Fija las rutas de datos del perfil por defecto según el perfil de usuario.

    Debe llamarse una vez, antes de crear la primera página: Qt WebEngine no
    admite cambiar setPersistentStoragePath/setCachePath con páginas vivas.
    Devuelve False si ya estaba fijado para otro perfil (el cambio de perfil
    se aplica al reiniciar).
    """
    global _storage_profile_id
    if _is_private_mode() or profile_manager is None:
        return True
    profile_id = profile_manager.current_profile_id
    if _storage_profile_id is not None:
        return _storage_profile_id == profile_id
    profile = QWebEngineProfile.defaultProfile()
    try:
        profile.setPersistentStoragePath(profile_manager.get_profile_path())
        profile.setCachePath(profile_manager.get_profile_path(subdirectory="cache"))
        _storage_profile_id = profile_id
        print(f"[PROFILE] Using profile-specific paths: {profile.persistentStoragePath()}")
    except Exception as e:
        print(f"[WARNING] Could not set profile paths: {e}")
    return True


class _NewTabButton(QPushButton):
    """Botón '+' que se posiciona justo después de la última pestaña."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tabBarNewTabBtn")
        self.setFixedSize(26, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Nueva pestaña (Ctrl+T)")
        self._apply_style("#A0A0A0")
    def _apply_style(self, icon_color: str = "#A0A0A0"):
        # Intentar usar newtab.svg
        try:
            from ui.core.strip_icons import build_nav_icon
            from PySide6.QtCore import QSize
            icon = build_nav_icon("newtab", icon_color, QSize(13, 13))
            if not icon.isNull():
                self.setIcon(icon)
                self.setIconSize(QSize(13, 13))
                self.setText("")
                self.setStyleSheet("""
                    QPushButton#tabBarNewTabBtn {
                        background: transparent;
                        border: none;
                        border-radius: 4px;
                        padding: 0px;
                    }
                    QPushButton#tabBarNewTabBtn:hover {
                        background: rgba(255,255,255,0.10);
                    }
                    QPushButton#tabBarNewTabBtn:pressed {
                        background: rgba(255,255,255,0.16);
                    }
                """)
                return
        except Exception:
            pass
        # Fallback texto
        self.setText("+")
        self.setStyleSheet("""
            QPushButton#tabBarNewTabBtn {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: #A0A0A0;
                font-size: 17px;
                font-weight: 300;
                padding-bottom: 2px;
            }
            QPushButton#tabBarNewTabBtn:hover {
                background: rgba(255,255,255,0.10);
                color: #F0F0F0;
            }
            QPushButton#tabBarNewTabBtn:pressed {
                background: rgba(255,255,255,0.16);
            }
        """)
    def refresh_icon(self, color: str):
        self._apply_style(color)


class FullScreenWindow(QWidget):
    """Ventana a pantalla completa para requestFullscreen() de una web (vídeos).

    Como el ejemplo simplebrowser de Qt: la página pasa a una vista propia de
    esta ventana y al salir vuelve a la vista de su pestaña, así la interfaz
    del navegador no hay que ocultarla pieza a pieza.
    """

    def __init__(self, old_view):
        super().__init__(None, Qt.Window)
        self._old_view = old_view
        self._restored = False
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(old_view.window().windowTitle())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._view = QWebEngineView(self)
        layout.addWidget(self._view)
        self._view.setPage(old_view.page())
        # Esc sale (Chromium no la gestiona por sí solo dentro de Qt)
        QShortcut(QKeySequence(Qt.Key_Escape), self,
                  activated=lambda: self._view.page().triggerAction(QWebEnginePage.ExitFullScreen))
        screen = old_view.window().screen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.activateWindow()
        self._view.setFocus()

    def restore(self):
        """Devuelve la página a la vista de la pestaña y cierra la ventana."""
        if self._restored:
            return
        self._restored = True
        try:
            self._old_view.setPage(self._view.page())
            self._old_view.setFocus()
        except RuntimeError:
            pass  # la pestaña ya se destruyó
        self.close()

    def closeEvent(self, event):
        # Alt+F4 / cierre del gestor de ventanas: avisar a la web antes
        if not self._restored:
            try:
                self._view.page().triggerAction(QWebEnginePage.ExitFullScreen)
            except RuntimeError:
                pass
            self.restore()
        super().closeEvent(event)


class BrowserView(QWebEngineView):
    """QWebEngineView que abre target="_blank" / window.open en pestañas del navegador.

    Sin createWindow() QtWebEngine descarta esas navegaciones (no pasa nada al hacer clic).
    """

    def __init__(self, tab_manager, parent=None):
        super().__init__(parent)
        self._tab_manager = tab_manager
        self._fullscreen_window = None

    def setup_fullscreen(self):
        """Permite requestFullscreen(); sin esto las webs dan "Fullscreen is not supported"."""
        page = self.page()
        page.settings().setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        page.fullScreenRequested.connect(self._on_fullscreen_requested)

    def _on_fullscreen_requested(self, request):
        request.accept()
        if request.toggleOn():
            if self._fullscreen_window is None:
                self._fullscreen_window = FullScreenWindow(self)
        else:
            self.exit_fullscreen_window()

    def exit_fullscreen_window(self):
        window, self._fullscreen_window = self._fullscreen_window, None
        if window is not None:
            window.restore()

    def createWindow(self, window_type):
        # Clic central / Ctrl+clic → segundo plano; el resto en primer plano
        background = window_type == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        # Qt carga la URL destino en la vista devuelta
        return self._tab_manager.add_new_tab("about:blank", focus=not background, load=False)


class BrowserTabBar(QTabBar):
    """
    QTabBar con botón '+' integrado que se posiciona justo después
    de la última pestaña y siempre es visible.
    """

    new_tab_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._btn = _NewTabButton(self)
        self._btn.clicked.connect(self.new_tab_requested)
        self._reposition()
    # Reposicionar el botón en cada evento que cambie las pestañas
    def tabLayoutChange(self):
        super().tabLayoutChange()
        self._reposition()
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition()
    def _reposition(self):
        """Coloca el botón '+' justo después de la última pestaña."""
        count = self.count()
        if count > 0:
            last_rect = self.tabRect(count - 1)
            x = last_rect.right() + 4
        else:
            x = 4
        # Si no cabe, pegar al borde derecho con margen
        max_x = self.width() - self._btn.width() - 4
        x = min(x, max_x) if max_x > 0 else x

        y = (self.height() - self._btn.height()) // 2
        self._btn.move(x, max(y, 0))
        self._btn.raise_()
    def refresh_icon(self, color: str):
        self._btn.refresh_icon(color)

    def tabInserted(self, index: int) -> None:
        super().tabInserted(index)
        self._reposition()
        self._install_close_button(index)

    def _install_close_button(self, index: int) -> None:
        """Instala un QToolButton como botón de cierre de pestaña.

        Usa setTabButton() directamente en lugar de QSS image: url() para
        evitar el problema de rutas con espacios que Qt QSS no puede cargar.
        El índice se resuelve dinámicamente al hacer clic para soportar
        pestañas que se eliminan y desplazan los índices restantes.
        """
        # Contenedor transparente: da 6px de margen derecho sin ampliar el hover
        container = QWidget(self)
        container.setStyleSheet("background: transparent;")

        btn = QToolButton(container)
        try:
            from ui.core.strip_icons import build_nav_icon
            btn.setIcon(build_nav_icon("tab_close", "#A0A0A0", QSize(12, 12)))
            btn.setIconSize(QSize(12, 12))
        except Exception:
            btn.setText("×")
        btn.setFixedSize(18, 18)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Cerrar pestaña")
        btn.setStyleSheet("""
            QToolButton {
                color: #A0A0A0;
                background: transparent;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                font-weight: 400;
                padding: 0px;
            }
            QToolButton:hover {
                color: #E8EAED;
                background: rgba(255, 255, 255, 0.20);
            }
            QToolButton:pressed {
                background: rgba(255, 255, 255, 0.30);
            }
        """)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)  # 6px de margen derecho
        layout.setSpacing(0)
        layout.addWidget(btn)
        container.setFixedSize(24, 18)

        def _on_close(_checked=False, btn=btn):
            c = btn.parent()
            bar = c.parent() if c else None
            if bar is None:
                return
            for i in range(bar.count()):
                if bar.tabButton(i, QTabBar.RightSide) is c:
                    bar.tabCloseRequested.emit(i)
                    return

        btn.clicked.connect(_on_close)
        self.setTabButton(index, QTabBar.RightSide, container)


class DetachedTabWidget(QTabWidget):
    """
    QTabWidget cuya barra de pestañas puede vivir FUERA del propio widget,
    reparentada a otra fila del layout (distribución estilo Firefox: la tira
    de pestañas arriba del todo y, debajo, la barra de navegación).

    Cuando la barra se reparenta, QTabWidget sigue reservando en su parte
    superior el espacio donde antes estaba la barra, dejando un hueco. Esta
    subclase fuerza al QStackedWidget interno (el que contiene las páginas)
    a ocupar toda el área disponible, eliminando ese hueco. Toda la API
    pública de QTabWidget se conserva intacta.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inner_stack = None
        self._bar_detached = False

    def set_bar_detached(self, detached: bool) -> None:
        """Activa el modo barra-externa (la barra vive en otro layout)."""
        self._bar_detached = bool(detached)
        self._fit_stack()

    def _stack(self):
        if self._inner_stack is None:
            self._inner_stack = self.findChild(QStackedWidget)
        return self._inner_stack

    def _fit_stack(self):
        if not self._bar_detached:
            return
        st = self._stack()
        if st is not None:
            st.setGeometry(self.rect())

    def _reassert_bar_layout(self):
        """
        QTabWidget vuelve a posicionar su barra (aunque esté reparentada) con
        el ancho del propio QTabWidget en cada pase de layout, pisando al layout
        del contenedor superior. Reactivamos el layout del contenedor padre para
        que recupere la autoridad sobre la geometría de la barra.
        """
        if not self._bar_detached:
            return
        bar = self.tabBar()
        parent = bar.parentWidget() if bar is not None else None
        if parent is not None and parent is not self:
            lay = parent.layout()
            if lay is not None:
                lay.activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_stack()
        self._reassert_bar_layout()

    def event(self, event):
        result = super().event(event)
        if self._bar_detached and event.type() in (
            QEvent.Type.LayoutRequest,
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._fit_stack()
            self._reassert_bar_layout()
        return result


class TabManager:
    SESSION_FILE = "tab_session.json"

    def __init__(self, history_manager, parent):
        self.history_manager = history_manager

        self.parent = parent

        self.tabs = DetachedTabWidget()
        self.tabs.setObjectName("browserTabs")

        # BrowserTabBar: barra de pestañas con botón '+' integrado
        self._tab_bar = BrowserTabBar()
        self.tabs.setTabBar(self._tab_bar)

        self.tabs.setDocumentMode(True)  # Flat tabs style

        self.tabs.setTabsClosable(True)

        self.tabs.tabCloseRequested.connect(self.close_tab)

        self.tabs.currentChanged.connect(self.on_tab_changed)

        # Configure tab context menu

        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)

        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_context_menu)

        # Stack de pestañas cerradas para Ctrl+Shift+T
        self.closed_tabs_stack = []
        self.max_closed_tabs = 10  # Máximo de pestañas cerradas en el historial

        # Pestañas fijadas (pinned tabs)
        self.pinned_tabs = set()  # Conjunto de índices de pestañas fijadas

        # Tab Groups Manager
        self.group_manager = TabGroupManager(parent=self.parent)

        # Diccionario para trackear conexiones de señales y prevenir memory leaks
        self._signal_connections = {}

        # Conectar botón '+' del tab bar a add_new_tab
        self._tab_bar.new_tab_requested.connect(self.add_new_tab)

        # Don't create initial tab here - let ui.py handle it after session restore

        # Conectar señales de grupos de pestañas con la barra de pestañas
        try:
            # Cuando se crea, elimina o actualiza un grupo, refrescar todas las pestañas
            self.group_manager.group_created.connect(
                lambda group_id: self.refresh_all_tab_appearances()
            )
            self.group_manager.group_deleted.connect(
                lambda group_id: self.refresh_all_tab_appearances()
            )
            self.group_manager.group_updated.connect(
                lambda group_id: self.refresh_all_tab_appearances()
            )
            # Cuando una pestaña entra o sale de un grupo, refrescar solo esa pestaña
            self.group_manager.tab_added_to_group.connect(
                lambda group_id, tab_index: self._refresh_tab_appearance(tab_index)
            )
            self.group_manager.tab_removed_from_group.connect(
                lambda group_id, tab_index: self._refresh_tab_appearance(tab_index)
            )
        except Exception as e:
            print(f"[TabGroups] Error connecting group signals: {e}")
    def _inject_dark_scrollbar_css(self, browser):
        """Inyecta CSS de scrollbar oscuro si el tema es dark"""

        try:
            theme = "light"

            if hasattr(self.parent, 'settings'):
                theme = self.parent.settings.value("theme", "light")
            if theme == "dark":
                css = """

                ::-webkit-scrollbar { width: 12px; background: #23272f; }
                ::-webkit-scrollbar-thumb { background: #5a5f6a; border-radius: 6px; }
                ::-webkit-scrollbar-thumb:hover { background: #6c7a89; }
                """

                js = f"""

                (function() {{

                    var style = document.getElementById('katphi-scrollbar-style');

                    if (!style) {{

                        style = document.createElement('style');

                        style.id = 'katphi-scrollbar-style';

                        style.innerHTML = `{css}`;

                        document.head.appendChild(style);
                    }}
                }})();

                """

                browser.page().runJavaScript(js)
        except Exception as e:
            print(f"Error injecting dark scrollbar CSS: {e}")
    def add_new_tab(self, url=None, focus=True, load=True):
        """Creates a new tab and returns it (focus=False la abre en segundo plano;
        load=False no carga la URL: la usa createWindow, que navega la vista él mismo)"""

        try:
            # Si no se proporciona URL, usar la página de inicio configurada
            if url is None or not isinstance(url, str) or not url.strip():
                # Usar homepage_manager si está disponible
                if hasattr(self.parent, 'homepage_manager') and self.parent.homepage_manager:
                    url = self.parent.homepage_manager.get_new_tab_url()
                    print(f"[TabManager] Using configured homepage: {url}")
                else:
                    # Fallback: usar motor de búsqueda predeterminado
                    if hasattr(self.parent, 'search_engine_manager') and self.parent.search_engine_manager:
                        default_engine = self.parent.search_engine_manager.get_default_engine()
                        if default_engine.id == 'google':
                            url = "https://www.google.com"
                        elif default_engine.id == 'duckduckgo':
                            url = "https://duckduckgo.com"
                        elif default_engine.id == 'bing':
                            url = "https://www.bing.com"
                        else:
                            url = "https://duckduckgo.com"
                    else:
                        url = "https://duckduckgo.com"
            # Crear el navegador
            browser = BrowserView(self)
            private = _is_private_mode()

            # A-001: en la ventana privada la página usa el perfil off-the-record
            # compartido (la página es hija de la vista y se destruye con ella)
            if private:
                browser.setPage(QWebEnginePage(get_private_profile(), browser))
            else:
                # Página explícita (mismo perfil por defecto): la implícita de
                # QWebEngineView se destruye al pasarla a la vista de pantalla
                # completa y devolverla
                browser.setPage(QWebEnginePage(QWebEngineProfile.defaultProfile(), browser))

            # IMPORTANTE: Configurar el perfil ANTES de establecer la URL
            # para que la primera petición HTTP use el User-Agent correcto

            # Configurar el perfil con datos aislados por usuario
            profile = browser.page().profile()
            # katphi-app:// (aplicaciones de plugins, p. ej. Katphi Office)
            app_scheme.install_on_profile(profile)

            # Las rutas de almacenamiento del perfil se fijan una sola vez al
            # arrancar (apply_profile_storage): cambiarlas aquí, con otras
            # páginas ya vivas en el mismo perfil, mezclaba datos de perfiles.
            if private:
                profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
                profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
            if not private:
                profile.setPersistentCookiesPolicy(QWebEngineProfile.AllowPersistentCookies)
                profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)

            # Configurar User-Agent del perfil (MÉTODO CORRECTO DE QT)
            if hasattr(self.parent, 'network_interceptor') and self.parent.network_interceptor:
                try:
                    # MÉTODO 1: User-Agent del perfil (navigator.userAgent, cabecera
                    # HTTP y Client Hints coherentes)
                    self.parent.network_interceptor.apply_to_profile(profile)
                    print(f"[UA-PROFILE] User-Agent set on profile: {self.parent.network_interceptor.user_agent_type}")

                    # MÉTODO 2: Configurar interceptor de red (afecta a headers HTTP)
                    profile.setUrlRequestInterceptor(self.parent.network_interceptor)
                    print(f"[UA-INTERCEPTOR] HTTP headers interceptor configured")
                except Exception as e:
                    print(f"[WARNING] Could not configure User-Agent: {e}")
            if hasattr(self.parent, 'privacy_manager') and self.parent.privacy_manager:
                try:
                    self.parent.privacy_manager.apply_privacy_settings(browser)
                except Exception as priv_ex:
                    print(f"[WARNING] apply_privacy_settings on new tab: {priv_ex}")
            browser.setup_fullscreen()
            # Aviso de vídeos H.264/AAC no reproducibles (se desactiva solo si
            # el motor web tiene esos códecs)
            try:
                import media_support
                media_support.install_scripts(profile)
            except Exception as media_ex:
                print(f"[WARNING] media_support on new tab: {media_ex}")
            # Configurar gestor de contraseñas ANTES de cargar la URL
            # para que los scripts estén registrados en la primera carga.
            # En modo privado no se capturan ni autorrellenan contraseñas.
            if not private and hasattr(self.parent, 'password_manager'):
                self.parent.password_manager.setup_browser(browser)
            # Establecer la URL - se cargará con el User-Agent y scripts listos
            if load:
                browser.setUrl(QUrl(url))

            # Conectar señales y guardar referencias para desconectar después
            browser_id = id(browser)
            self._signal_connections[browser_id] = {}

            # Conectar urlChanged (múltiples conexiones)
            url_changed_1 = lambda url, b=browser: self.on_url_changed(url, b)
            browser.urlChanged.connect(url_changed_1)
            url_changed_slots = [url_changed_1]
            # En modo privado no se registra historial
            if not private:
                def url_changed_2(url, _record=self.history_manager.record_history):
                    # Las aplicaciones de plugins no van al historial
                    if not app_scheme.is_app_url(url):
                        _record(url)
                browser.urlChanged.connect(url_changed_2)
                url_changed_slots.append(url_changed_2)
            self._signal_connections[browser_id]['urlChanged'] = url_changed_slots

            # Conectar titleChanged
            title_changed = lambda title: self.update_tab_title(title, browser)
            browser.titleChanged.connect(title_changed)
            self._signal_connections[browser_id]['titleChanged'] = title_changed

            # Conectar iconChanged — actualiza la pestaña Y alimenta el FaviconManager
            def _make_icon_handler(b):
                def _handler(icon):
                    self.update_tab_icon(icon, b)
                    try:
                        from favicon_manager import get_favicon_manager
                        get_favicon_manager().store(b.url().toString(), icon)
                    except Exception:
                        pass
                return _handler
            icon_changed = _make_icon_handler(browser)
            browser.iconChanged.connect(icon_changed)
            self._signal_connections[browser_id]['iconChanged'] = icon_changed

            # Configurar menú contextual

            browser.setContextMenuPolicy(Qt.CustomContextMenu)

            context_menu = lambda pos: self.show_context_menu(pos, browser)
            browser.customContextMenuRequested.connect(context_menu)
            self._signal_connections[browser_id]['customContextMenuRequested'] = context_menu

            # Configurar descargas

            # A-008: downloadRequested se conecta una sola vez por perfil
            # (connect_profile es idempotente); antes se conectaba por pestaña
            if hasattr(self.parent, 'navigation_manager'):
                dm = getattr(self.parent.navigation_manager, 'download_manager', None)
                if dm is not None and hasattr(dm, 'connect_profile'):
                    dm.connect_profile(profile)
                else:
                    self.parent.navigation_manager.setup_downloads(browser)
            # Configurar inyección de UserScripts

            if hasattr(self.parent, 'userscript_manager'):
                browser.loadFinished.connect(lambda ok: self.inject_userscripts(browser, ok))
            # Añadir la pestaña

            index = self.tabs.addTab(browser, "New Tab")

            if focus:
                self.tabs.setCurrentIndex(index)

            # Notificar al group manager sobre la nueva pestaña
            self.group_manager.on_tab_added(index)

            # Actualizar la barra de URL si está disponible

            if focus and load and hasattr(self.parent, 'url_bar'):
                self.parent.url_bar.setText(url)
            # TODO V2: Aplicar profile del grupo aquí si la pestaña va a un grupo específico

            print(f"Tab created successfully with URL: {url}")

            # Inyectar CSS de scrollbar oscuro si aplica

            self._inject_dark_scrollbar_css(browser)

            return browser
        except Exception as e:
            print(f"Error creating new tab: {str(e)}")

            return None
    def update_tab_icon(self, icon, browser):
        try:
            index = self.tabs.indexOf(browser)

            if index != -1:
                if icon.isNull():
                    icon = QIcon(":/icons/bookmark.png")
                self.tabs.setTabIcon(index, icon)
        except Exception as e:
            print(f"Error al actualizar el icono de la pestaña: {str(e)}")
    def _site_name_for_tab(self, browser, fallback_title=""):
        """
        Devuelve el nombre del sitio (host sin 'www.') para mostrar en la
        pestaña, estilo Firefox simplificado. Para páginas sin host (about:,
        nueva pestaña, archivos locales…) usa el título de la página.
        """
        try:
            host = browser.url().host()
        except Exception:
            host = ""
        if host:
            if host.startswith("www."):
                host = host[4:]
            return host
        label = (fallback_title or "").strip()
        return label or "Nueva pestaña"

    @staticmethod
    def app_tab_info(browser):
        """Datos de una pestaña de aplicación (add_app_tab) o None."""
        return getattr(browser, "_katphi_app_tab", None)

    def display_url(self, browser) -> str:
        """Texto de la barra de URL: el título en las pestañas de aplicación."""
        info = self.app_tab_info(browser)
        if info and app_scheme.is_app_url(browser.url()):
            return info.get("display") or info.get("title") or ""
        return browser.url().toString()

    def add_app_tab(self, url, title, icon=None, on_close=None, display=None,
                    focus=True, before_load=None):
        """Pestaña con una aplicación de plugin (katphi-app://...).

        title: texto fijo de la pestaña; display: lo que muestra la barra de
        URL (p. ej. la ruta del archivo); on_close(): devuelve False para
        impedir el cierre (cambios sin guardar); before_load(browser): se
        llama antes de cargar la URL (p. ej. para instalar un QWebChannel). No
        va al historial ni a la sesión guardada.
        """
        browser = self.add_new_tab("about:blank", focus=focus, load=False)
        if browser is None:
            return None
        browser._katphi_app_tab = {"title": title, "on_close": on_close,
                                   "display": display or title}
        if before_load is not None:
            before_load(browser)
        browser.setUrl(QUrl(url))
        index = self.tabs.indexOf(browser)
        if index != -1:
            self.tabs.setTabText(index, title if len(title) <= 30 else title[:27] + "...")
            self.tabs.setTabToolTip(index, display or title)
            if icon is not None:
                self.tabs.setTabIcon(index, icon)
        return browser

    def set_app_tab_title(self, browser, title, display=None):
        """Cambia el título (p. ej. "* informe.docx" con cambios sin guardar)."""
        info = self.app_tab_info(browser)
        if info is None:
            return
        info["title"] = title
        if display is not None:
            info["display"] = display
        self.update_tab_title(title, browser)

    def update_tab_title(self, title, browser):
        try:
            index = self.tabs.indexOf(browser)

            if index != -1:
                # El texto de la pestaña es el nombre del sitio (host), no el
                # título completo de la página.
                label = self._site_name_for_tab(browser, title)
                app_info = self.app_tab_info(browser)
                if app_info:
                    label = app_info.get("title") or label
                    title = label
                if len(label) > 30:
                    label = label[:27] + "..."
                # Agregar indicador visual si la pestaña pertenece a un grupo
                group = self.group_manager.get_tab_group(index)
                if group:
                    # Usar emoji de círculo coloreado como indicador visual
                    label = f"● {label}"
                    # Aplicar color del grupo al tab bar
                    self._apply_group_color_to_tab(index, group.color)
                self.tabs.setTabText(index, label)
                # El título de la ventana sí conserva el título completo.
                if self.tabs.currentWidget() == browser:
                    win_title = (title or label).strip() or label
                    self.parent.setWindowTitle(f"{win_title} - Katphi")
        except Exception as e:
            print(f"Error al actualizar el título de la pestaña: {str(e)}")
    def _disconnect_browser_signals(self, browser):
        """Desconecta todas las señales de un browser para prevenir memory leaks"""
        try:
            # Obtener las conexiones guardadas para este browser
            browser_id = id(browser)
            if browser_id not in self._signal_connections:
                return
            connections = self._signal_connections[browser_id]

            # Desconectar señales
            try:
                if 'urlChanged' in connections:
                    for conn in connections['urlChanged']:
                        browser.urlChanged.disconnect(conn)
            except:
                pass
            try:
                if 'titleChanged' in connections:
                    browser.titleChanged.disconnect(connections['titleChanged'])
            except:
                pass
            try:
                if 'iconChanged' in connections:
                    browser.iconChanged.disconnect(connections['iconChanged'])
            except:
                pass
            try:
                if 'customContextMenuRequested' in connections:
                    browser.customContextMenuRequested.disconnect(connections['customContextMenuRequested'])
            except:
                pass
            # Eliminar del diccionario
            del self._signal_connections[browser_id]
        except Exception as e:
            print(f"Error al desconectar señales del browser: {str(e)}")
    def _destroy_browser(self, browser):
        """Detiene y programa la destrucción de una vista ya quitada del QTabWidget.

        La página (por defecto o la privada) es hija de la vista y se destruye
        con ella; si tuviera otro dueño se libera aparte.
        """
        if browser is None:
            return
        try:
            # Si la pestaña se cierra en pantalla completa, recuperar antes la página
            if hasattr(browser, 'exit_fullscreen_window'):
                browser.exit_fullscreen_window()
            page = browser.page() if hasattr(browser, 'page') else None
            try:
                browser.stop()
            except Exception:
                pass
            if page is not None and page.parent() is not browser:
                page.deleteLater()
            browser.deleteLater()
        except Exception as e:
            print(f"Error al destruir la vista de la pestaña: {e}")

    def dispose_tab_widget(self, browser):
        """Limpieza completa de una vista ya quitada: señales, password manager y deleteLater."""
        if browser is None:
            return
        try:
            self._disconnect_browser_signals(browser)
        except Exception:
            pass
        try:
            if hasattr(self.parent, 'password_manager'):
                self.parent.password_manager.cleanup_browser(browser)
        except Exception:
            pass
        self._destroy_browser(browser)

    def close_tab(self, index):
        try:
            if self.tabs.count() > 1:
                # Guardar información de la pestaña antes de cerrarla
                tab_widget = self.tabs.widget(index)
                app_info = self.app_tab_info(tab_widget) if tab_widget else None
                if app_info and app_info.get("on_close"):
                    try:
                        if app_info["on_close"]() is False:
                            return   # el plugin impide el cierre (cambios sin guardar)
                    except Exception as veto_ex:
                        print(f"[TabManager] on_close de la aplicación falló: {veto_ex}")
                if tab_widget and hasattr(tab_widget, 'url') and not app_info:
                    tab_data = {
                        'url': tab_widget.url().toString(),
                        'title': self.tabs.tabText(index),
                        'icon': self.tabs.tabIcon(index)
                    }

                    # Agregar al stack de pestañas cerradas
                    self.closed_tabs_stack.append(tab_data)

                    # Limitar el tamaño del stack
                    if len(self.closed_tabs_stack) > self.max_closed_tabs:
                        self.closed_tabs_stack.pop(0)
                # Remover de pestañas fijadas si estaba fijada
                if index in self.pinned_tabs:
                    self.pinned_tabs.discard(index)
                    # Actualizar índices de pestañas fijadas
                    self.pinned_tabs = {i - 1 if i > index else i for i in self.pinned_tabs}
                # Desconectar señales del browser para prevenir memory leaks
                if tab_widget:
                    self._disconnect_browser_signals(tab_widget)
                # Limpiar webchannel del password manager para esta pestaña
                if tab_widget and hasattr(self.parent, 'password_manager'):
                    self.parent.password_manager.cleanup_browser(tab_widget)
                # Notificar al group manager para actualizar índices
                self.group_manager.on_tab_closed(index)

                self.tabs.removeTab(index)

                # E-007: removeTab no destruye la vista; liberarla (y su página)
                self._destroy_browser(tab_widget)

                current_browser = self.tabs.currentWidget()

                if current_browser:
                    self.update_tab_title(current_browser.page().title(), current_browser)
        except Exception as e:
            print(f"Error al cerrar la pestaña: {str(e)}")
    def show_context_menu(self, pos, browser):
        try:
            menu = QMenu(self.parent)

            back_action = menu.addAction("Back")

            forward_action = menu.addAction("Forward")

            reload_action = menu.addAction("Reload")

            menu.addSeparator()

            open_in_new_tab = menu.addAction("Open in New Tab")

            menu.addSeparator()

            save_bookmark = menu.addAction("Save as Bookmark")
            inspect_action = menu.addAction("Inspect (Inspeccionar)")

            action = menu.exec(browser.mapToGlobal(pos))

            if action == back_action:
                browser.back()
            elif action == forward_action:
                browser.forward()
            elif action == reload_action:
                browser.reload()
            elif action == open_in_new_tab:
                # Fallback to robust JavaScript detection
                # We traverse up the DOM tree to find the anchor tag if the click was on a child element
                js_code = f"""
                (function() {{
                    var elem = document.elementFromPoint({pos.x()}, {pos.y()});
                    while (elem) {{
                        if (elem.href) return elem.href;
                        elem = elem.parentElement;
                    }}
                    return null;
                }})();
                """
                browser.page().runJavaScript(js_code, self.open_link_in_new_tab)
            elif action == save_bookmark:
                current_url = browser.url().toString()

                if current_url:
                    self.parent.show_save_favorite_menu()
            elif action == inspect_action:
                if hasattr(self.parent, "devtools_dock") and self.parent.devtools_dock:
                    self.parent.devtools_dock.set_browser(browser)
                    self.parent.devtools_dock.show()
                    self.parent.devtools_dock.raise_()
        except Exception as e:
            print(f"Error al mostrar el menú contextual: {str(e)}")
    def open_link_in_new_tab(self, link):
        try:
            if link:
                self.add_new_tab(link)
        except Exception as e:
            print(f"Error al abrir enlace en nueva pestaña: {str(e)}")
    def on_url_changed(self, url, sender_browser):
        """Maneja el cambio de URL en una pestaña"""

        try:
            print(f"\n{'='*60}")
            print(f"[URL_CHANGED] Señal recibida: {url.toString()}")
            print(f"{'='*60}")

            # Solo actualizar la barra de URL si es la pestaña activa
            current_browser = self.tabs.currentWidget()
            print(f"[URL_CHANGED] Sender browser: {sender_browser}")
            print(f"[URL_CHANGED] Current browser: {current_browser}")

            if sender_browser == current_browser:
                print(f"[URL_CHANGED] ✓ Es la pestaña activa - actualizando URL bar")

                # Actualizar la barra de URL si está disponible

                if hasattr(self.parent, 'url_bar'):
                    self.parent.url_bar.setText(self.display_url(sender_browser))
                    print(f"[URL_CHANGED] ✓ URL bar actualizada a: {url.toString()}")
                if hasattr(self.parent, 'tabs'):
                    if current_browser:
                        self._inject_dark_scrollbar_css(current_browser)
            # Refrescar el texto de la pestaña (host del sitio) al cambiar de URL
            try:
                page_title = sender_browser.page().title() if sender_browser else ""
                self.update_tab_title(page_title, sender_browser)
            except Exception:
                pass
            else:
                print(f"[URL_CHANGED] ✗ NO es la pestaña activa - NO actualizando URL bar")
        except Exception as e:
            print(f"[URL_CHANGED] ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
    def on_tab_changed(self, index):
        try:
            current_browser = self.tabs.widget(index)

            if current_browser:
                if hasattr(self.parent, 'devtools_dock'):
                    self.parent.devtools_dock.set_browser(current_browser)
                if hasattr(self.parent, 'url_bar'):
                    self.parent.url_bar.setText(self.display_url(current_browser))
                self.update_tab_title(current_browser.page().title(), current_browser)

                # Sincronizar con el módulo de scraping si está disponible

                if hasattr(self.parent, 'scraping_integration') and self.parent.scraping_integration:
                    current_url = current_browser.url().toString()

                    # Actualizar el widget del navegador en el scraping integration

                    self.parent.scraping_integration.browser_widget = current_browser

                    # Actualizar browser_tab en el panel de scraping

                    if hasattr(self.parent, 'scraping_panel') and self.parent.scraping_panel:
                        self.parent.scraping_panel.browser_tab = current_browser
                    # Obtener el HTML de la página actual

                    current_browser.page().toHtml(

                        lambda html_content: self.parent.scraping_integration.update_content(html_content, current_url)
                    )
        except Exception as e:
            print(f"Error al cambiar de pestaña: {str(e)}")
    def guardar_sesion(self):
        """Guarda la sesión actual de pestañas (URL) en un archivo JSON"""

        # A-001: la ventana privada no deja sesión en disco
        if _is_private_mode():
            return

        session = []

        for i in range(self.tabs.count()):
            browser = self.tabs.widget(i)

            # Las aplicaciones de plugins no se restauran (su URL es de un solo uso)
            if app_scheme.is_app_url(browser.url()) or self.app_tab_info(browser):
                continue
            url = browser.url().toString()

            session.append({"url": url})
        try:
            with open(self.SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
            print(f"Sesión guardada con {len(session)} pestañas.")
        except Exception as e:
            print(f"Error al guardar la sesión: {e}")
    def restaurar_sesion(self):
        """Restore tab session from JSON file"""

        # A-001: la ventana privada empieza siempre limpia
        if _is_private_mode():
            return False

        if not os.path.exists(self.SESSION_FILE):
            print("No saved session to restore.")

            return False
        try:
            with open(self.SESSION_FILE, "r", encoding="utf-8") as f:
                session = json.load(f)
            # Validate session data

            if not session or not isinstance(session, list):
                print("Session file is empty or invalid, no tabs to restore.")

                return False
            # Close existing tabs safely if any exist

            tab_count = self.tabs.count()

            if tab_count > 0:
                # Remove tabs from end to beginning to avoid index issues

                for i in range(tab_count - 1, -1, -1):
                    try:
                        self.close_tab(i)
                    except Exception as e:
                        print(f"Error closing tab {i}: {e}")
            # Restore session tabs

            for tab_data in session:
                url = tab_data.get("url", "")

                # Si no hay URL guardada, usar None para que add_new_tab use el motor predeterminado
                if not url or url == "about:blank":
                    url = None
                self.add_new_tab(url)
            print(f"Session restored with {len(session)} tabs.")

            return True
        except json.JSONDecodeError as e:
            print(f"Error decoding session file: {e}. Starting fresh.")

            return False
        except Exception as e:
            print(f"Error restoring session: {e}")

            import traceback

            traceback.print_exc()

            return False
    def buscar_pestanas(self, query):
        """Filtra las pestañas abiertas por título o URL"""

        query = query.lower().strip()

        for i in range(self.tabs.count()):
            browser = self.tabs.widget(i)

            title = self.tabs.tabText(i).lower()

            url = browser.url().toString().lower()

            visible = query in title or query in url or not query

            self.tabs.setTabVisible(i, visible)
    def close_other_tabs(self, keep_index):
        """Cerrar todas las pestañas excepto la especificada"""

        try:
            # Cerrar desde el final para mantener índices válidos

            for i in range(self.tabs.count() - 1, -1, -1):
                if i != keep_index:
                    self.close_tab(i)
        except Exception as e:
            print(f"Error closing other tabs: {e}")
    def _tab_context_menu(self, pos):
        """Menú contextual por pestaña (MEJORADO)"""

        index = self.tabs.tabBar().tabAt(pos)

        if index < 0:
            return
        menu = QMenu(self.tabs)

        # Recargar pestaña
        reload_action = menu.addAction("Recargar")

        # Duplicar pestaña
        duplicate_action = menu.addAction("Duplicar pestaña")

        menu.addSeparator()

        # === TAB GROUPS SECTION ===
        # Get current group for this tab
        current_group = self.group_manager.get_tab_group(index)

        # Crear nuevo grupo con esta pestaña
        create_group_action = menu.addAction("Crear grupo con esta pestaña")

        # Agregar a grupo existente (submenú)
        add_to_group_menu = menu.addMenu("Agregar a grupo")
        all_groups = self.group_manager.get_all_groups()

        if all_groups:
            for group in all_groups:
                # Skip if tab is already in this group
                if current_group and current_group.id == group.id:
                    continue
                action = add_to_group_menu.addAction(f"● {group.name}")
                action.setData(group.id)  # Store group_id in action data
        else:
            no_groups_action = add_to_group_menu.addAction("(No hay grupos)")
            no_groups_action.setEnabled(False)
        # Remover de grupo (solo si está en un grupo)
        remove_from_group_action = None
        if current_group:
            remove_from_group_action = menu.addAction(f"Quitar de '{current_group.name}'")
        menu.addSeparator()

        # Fijar/Desfijar pestaña
        if index in self.pinned_tabs:
            pin_action = menu.addAction("Desfijar pestaña")
        else:
            pin_action = menu.addAction("Fijar pestaña")
        # Silenciar/Activar audio
        tab_widget = self.tabs.widget(index)
        if tab_widget and hasattr(tab_widget, 'page'):
            if tab_widget.page().isAudioMuted():
                mute_action = menu.addAction("Activar audio")
            else:
                mute_action = menu.addAction("Silenciar audio")
        else:
            mute_action = None
        menu.addSeparator()

        # Acciones de cierre

        close_action = menu.addAction("Cerrar pestaña")

        close_others_action = menu.addAction("Cerrar otras pestañas")

        close_right_action = menu.addAction("Cerrar pestañas a la derecha")

        menu.addSeparator()

        # Split View (mostrar siempre; habilitar si está cargado/instalado)
        split_view_action = menu.addAction("⫿ Abrir en Split View")
        split_view_enabled = False
        if hasattr(self.parent, 'dynamic_plugin_panels') and 'split_view' in getattr(self.parent, 'dynamic_plugin_panels', {}):
            split_view_enabled = True
        elif hasattr(self.parent, 'plugin_manager') and self.parent.plugin_manager:
            try:
                # Si el plugin está instalado pero todavía no cargado, permitimos el intento
                split_view_enabled = self.parent.plugin_manager.is_plugin_installed('split_view')
            except Exception:
                split_view_enabled = False
        split_view_action.setEnabled(bool(split_view_enabled))

        # Ejecutar menú

        action = menu.exec(self.tabs.tabBar().mapToGlobal(pos))

        # Procesar acciones
        if action == reload_action:
            tab_widget = self.tabs.widget(index)
            if tab_widget:
                tab_widget.reload()
        elif action == duplicate_action:
            self.duplicate_tab(index)
        elif action == create_group_action:
            # Crear nuevo grupo con esta pestaña
            self._create_group_with_tab(index)
        elif action in add_to_group_menu.actions() and action.data():
            # Agregar pestaña a grupo existente
            group_id = action.data()
            self.group_manager.add_tab_to_group(group_id, index)
            self._refresh_tab_appearance(index)
            print(f"[TabGroups] Tab {index} added to group {group_id}")
        elif action == remove_from_group_action:
            # Remover pestaña del grupo actual
            if current_group:
                self.group_manager.remove_tab_from_group(current_group.id, index)
                self._refresh_tab_appearance(index)
                print(f"[TabGroups] Tab {index} removed from group {current_group.id}")
        elif action == pin_action:
            self.toggle_pin_tab(index)
        elif action == mute_action and mute_action is not None:
            self.mute_tab(index)
        elif action == close_action:
            self.close_tab(index)
        elif action == close_others_action:
            self.close_other_tabs(index)
        elif action == close_right_action:
            # Cerrar todas las pestañas a la derecha
            for i in range(self.tabs.count() - 1, index, -1):
                self.close_tab(i)
        elif split_view_action and action == split_view_action:
            # Abrir pestaña en Split View (cargar plugin si hace falta)
            try:
                split_view_plugin = None
                if hasattr(self.parent, 'dynamic_plugin_panels'):
                    split_view_plugin = self.parent.dynamic_plugin_panels.get('split_view')
                if not split_view_plugin and hasattr(self.parent, 'plugin_manager') and self.parent.plugin_manager:
                    # Intentar cargarlo bajo demanda
                    if self.parent.plugin_manager.load_plugin('split_view'):
                        if hasattr(self.parent, 'dynamic_plugin_panels'):
                            split_view_plugin = self.parent.dynamic_plugin_panels.get('split_view')
                if split_view_plugin and hasattr(split_view_plugin, 'open_tab_in_split_view'):
                    split_view_plugin.open_tab_in_split_view(index)
                else:
                    print("[TabManager] Split View plugin not available")
            except Exception as e:
                print(f"[TabManager] Error opening Split View: {e}")
    def limpiar_sesion(self):
        """Limpia la sesión guardada (elimina el archivo de sesión)"""

        try:
            if os.path.exists(self.SESSION_FILE):
                os.remove(self.SESSION_FILE)

                print("Sesión limpiada correctamente.")
            else:
                print("No hay sesión guardada para limpiar.")
        except Exception as e:
            print(f"Error al limpiar la sesión: {e}")
    # ============================================================================
    # NUEVAS FUNCIONALIDADES - Plan de Acción UX/UI
    # ============================================================================

    def reopen_closed_tab(self):
        """Reabrir la última pestaña cerrada (Ctrl+Shift+T)"""
        if not self.closed_tabs_stack:
            print("No hay pestañas cerradas para reabrir")
            return None
        # Obtener última pestaña cerrada
        tab_data = self.closed_tabs_stack.pop()

        # Crear nueva pestaña con la URL guardada
        new_tab = self.add_new_tab(tab_data['url'])

        # Restaurar icono si es posible
        if tab_data.get('icon'):
            current_index = self.tabs.indexOf(new_tab)
            self.tabs.setTabIcon(current_index, tab_data['icon'])
        print(f"Reabierta pestaña: {tab_data['title']}")
        return new_tab
    def duplicate_tab(self, index=None):
        """Duplicar una pestaña existente"""
        if index is None:
            index = self.tabs.currentIndex()
        if index < 0:
            return None
        # Obtener pestaña actual
        current_tab = self.tabs.widget(index)
        if not current_tab or not hasattr(current_tab, 'url'):
            return None
        # Crear nueva pestaña con la misma URL
        url = current_tab.url().toString()
        new_tab = self.add_new_tab(url)

        print(f"Pestaña duplicada: {url}")
        return new_tab
    def pin_tab(self, index=None):
        """Fijar una pestaña (evitar cierre accidental)"""
        if index is None:
            index = self.tabs.currentIndex()
        if index < 0:
            return
        # Agregar a conjunto de pestañas fijadas
        self.pinned_tabs.add(index)

        # Actualizar apariencia
        self._update_pinned_tab_appearance(index, pinned=True)

        # Deshabilitar botón de cerrar
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)

        print(f"Pestaña {index} fijada")
    def unpin_tab(self, index=None):
        """Desfijar una pestaña"""
        if index is None:
            index = self.tabs.currentIndex()
        if index < 0 or index not in self.pinned_tabs:
            return
        # Remover de conjunto de pestañas fijadas
        self.pinned_tabs.discard(index)

        # Actualizar apariencia
        self._update_pinned_tab_appearance(index, pinned=False)

        # Restaurar botón de cerrar
        bar = self.tabs.tabBar()
        if hasattr(bar, "_install_close_button"):
            bar._install_close_button(index)
        else:
            from PySide6.QtWidgets import QToolButton
            close_button = QToolButton()
            close_button.setText("×")
            close_button.clicked.connect(lambda: self.close_tab(index))
            bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, close_button)

        print(f"Pestaña {index} desfijada")
    def toggle_pin_tab(self, index=None):
        """Alternar fijado de pestaña"""
        if index is None:
            index = self.tabs.currentIndex()
        if index in self.pinned_tabs:
            self.unpin_tab(index)
        else:
            self.pin_tab(index)
    def _update_pinned_tab_appearance(self, index, pinned=True):
        """Actualizar apariencia visual de pestaña fijada"""
        # Reducir ancho de pestaña fijada
        tab_bar = self.tabs.tabBar()

        if pinned:
            # Pestaña fijada: más estrecha, solo icono
            # (Esto requeriría subclase de QTabBar para control completo)
            # Por ahora solo marcamos visualmente
            bar = self.tabs.tabBar()
            bar.setTabButton(index, bar.RightSide, self._make_tab_badge("pin", "Pestaña fijada"))
    def mute_tab(self, index=None):
        """Silenciar audio de una pestaña"""
        if index is None:
            index = self.tabs.currentIndex()
        if index < 0:
            return
        tab_widget = self.tabs.widget(index)
        if tab_widget and hasattr(tab_widget, 'page'):
            page = tab_widget.page()

            # Silenciar audio
            page.setAudioMuted(not page.isAudioMuted())

            # Actualizar indicador visual
            bar = self.tabs.tabBar()
            badge = self._make_tab_badge("volume-x", "Pestaña silenciada") if page.isAudioMuted() else None
            bar.setTabButton(index, bar.LeftSide, badge)
            print(f"Pestaña {index} {'silenciada' if page.isAudioMuted() else 'con audio'}")
    def _make_tab_badge(self, icon_name: str, tooltip: str):
        """Pequeño icono SVG para indicar el estado de una pestaña (fijada, silenciada)."""
        from PySide6.QtWidgets import QLabel
        badge = QLabel()
        try:
            from ui.core.strip_icons import build_nav_icon, get_icon_color
            badge.setPixmap(build_nav_icon(icon_name, get_icon_color(), QSize(12, 12)).pixmap(12, 12))
        except Exception:
            pass
        badge.setToolTip(tooltip)
        badge.setFixedSize(16, 16)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("background: transparent;")
        return badge
    def get_closed_tabs_history(self):
        """Obtener historial de pestañas cerradas"""
        return list(reversed(self.closed_tabs_stack))  # Más reciente primero
    def inject_userscripts(self, browser, ok):
        """Inyectar UserScripts en la página cargada"""
        if not ok or not hasattr(self.parent, 'userscript_manager'):
            return
        url = browser.url().toString()
        if not url or url == 'about:blank' or app_scheme.is_app_url(browser.url()):
            return
        # Obtener scripts que coinciden con la URL
        scripts = self.parent.userscript_manager.get_scripts_for_url(url)

        if not scripts:
            return
        print(f"[UserScripts] Injecting {len(scripts)} scripts into {url}")

        for script in scripts:
            try:
                # Preparar código del script
                code = script['code']

                # Crear wrapper con API GM_*
                script_id = script['id']
                wrapped_code = f"""
(function() {{
    // GM API
    var GM_setValue = function(key, value) {{
        console.log('[GM_setValue]', key, value);
        // En un entorno real, esto se comunicaría con Python
    }};

    var GM_getValue = function(key, defaultValue) {{
        console.log('[GM_getValue]', key);
        return defaultValue;
    }};

    var GM_addStyle = function(css) {{
        var style = document.createElement('style');
        style.textContent = css;
        document.head.appendChild(style);
        console.log('[GM_addStyle] CSS injected');
    }};

    var GM_log = function(message) {{
        console.log('[UserScript: {script['name']}]', message);
    }};

    // Ejecutar script de usuario
    try {{
        {code}
    }} catch(e) {{
        console.error('[UserScript Error: {script['name']}]', e);
    }}
}})();
"""

                # Inyectar script
                browser.page().runJavaScript(wrapped_code, lambda result: None)
                print(f"[UserScript] Injected: {script['name']}")
            except Exception as e:
                print(f"[ERROR] Failed to inject script '{script['name']}': {e}")
    # ============================================================================
    # TAB GROUPS - Helper Methods
    # ============================================================================

    def _create_group_with_tab(self, tab_index):
        """Create a new group and add this tab to it"""
        from tab_groups_ui import CreateGroupDialog
        from PySide6.QtWidgets import QDialog

        # Get tab title for suggested group name
        tab_title = self.tabs.tabText(tab_index).replace("● ", "")

        dialog = CreateGroupDialog(parent=self.parent)

        # Suggest a name based on tab title
        if tab_title and tab_title != "New Tab":
            dialog.name_input.setText(tab_title[:20])
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_group_data()
            if not data["name"]:
                return
            # Create group with this tab
            group = self.group_manager.create_group(
                name=data["name"],
                color=data["color"],
                tab_indices=[tab_index]
            )

            # Refresh tab appearance
            self._refresh_tab_appearance(tab_index)

            print(f"[TabGroups] Created group '{group.name}' with tab {tab_index}")
    def _refresh_tab_appearance(self, index):
        """Refresh the visual appearance of a tab (group indicator, color)"""
        if index < 0 or index >= self.tabs.count():
            return
        browser = self.tabs.widget(index)
        if browser and hasattr(browser, 'page'):
            # Trigger title update which will apply group styling
            self.update_tab_title(browser.page().title(), browser)
    def _apply_group_color_to_tab(self, index, color):
        """Apply group color styling to a tab"""
        try:
            from PySide6.QtGui import QPalette, QColor

            tab_bar = self.tabs.tabBar()

            # Create a custom palette for this tab
            # Note: QTabBar doesn't support per-tab styling easily
            # We use the color indicator (●) in the title as primary visual cue
            # For more advanced styling, we could subclass QTabBar

            # For now, we'll rely on the ● indicator in the title
            # which provides a clear visual grouping indicator
        except Exception as e:
            print(f"[TabGroups] Error applying color to tab {index}: {e}")
    def refresh_all_tab_appearances(self):
        """Refresh all tab appearances (useful after group changes)"""
        for i in range(self.tabs.count()):
            self._refresh_tab_appearance(i)
