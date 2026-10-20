#!/usr/bin/env python3
"""
Katphi Browser — punto de entrada principal.

Este módulo es SOLO el script de arranque: todo el trabajo con efectos
(logging, flags de Chromium, QApplication...) ocurre dentro de main().
Importarlo no tiene efectos, pero no debe importarse: para reiniciar con o
sin Tor se usa ``from tor_restart import restart_with_tor`` (C-008).
"""

import getpass
import logging
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

_logger = logging.getLogger(__name__)

# El usuario eligió "Continuar sin Tor (esta sesión)": el proceso se relanza
# con esta variable y arranca sin proxy, sin tocar tor.enabled en config.yaml.
_TOR_SKIP_ENV = "KATPHI_TOR_SKIP_SESSION"

# Resultado de _configure_tor_proxy_if_needed()
_TOR_OFF = "off"
_TOR_ON = "on"
_TOR_SOCKS_DOWN = "socks_down"


def _parse_private_flag() -> bool:
    """Detecta --private, lo quita de sys.argv y fija constants.PRIVATE_MODE.

    Debe llamarse antes de crear la QApplication (Qt no conoce el argumento).
    """
    import constants
    private = "--private" in sys.argv
    if private:
        constants.PRIVATE_MODE = True
        sys.argv = [a for a in sys.argv if a != "--private"]
    return private


def _startup_urls() -> list:
    """URLs http(s) pasadas por línea de comandos (p. ej. "abrir con")."""
    urls = []
    for arg in sys.argv[1:]:
        if arg == "--webEngineArgs":
            break
        if arg.lower().startswith(("http://", "https://")):
            urls.append(arg)
    return urls


def _strip_tor_proxy_args() -> None:
    """Quita de sys.argv las flags de proxy de Tor (que no viajen en un execv)."""
    from tor_restart import _clean_argv
    sys.argv = _clean_argv(sys.argv)


def _configure_tor_proxy_if_needed() -> str:
    """
    Inyecta flags de proxy Chromium si Tor está habilitado.
    DEBE llamarse ANTES de crear la QApplication: Qt WebEngine lee
    --webEngineArgs de los argumentos con los que se construyó la aplicación.
    Usa --webEngineArgs en sys.argv (QTWEBENGINE_CHROMIUM_FLAGS sobrescribe webEngineArgs).

    Returns:
        _TOR_OFF, _TOR_ON o _TOR_SOCKS_DOWN (Tor activado pero el SOCKS no
        responde: se inyectan igualmente las flags, para no navegar en claro,
        y main() pregunta al usuario qué hacer).
    """
    try:
        import net_proxy
        from config_manager import config
        from constants import is_private_mode

        enabled = config.is_tor_enabled()
        if is_private_mode():
            # La ventana privada no persiste el estado de Tor: tor_restart lo
            # pasa por el entorno al relanzarse.
            from tor_restart import PRIVATE_TOR_ENV
            env_tor = os.environ.get(PRIVATE_TOR_ENV)
            if env_tor in ("0", "1"):
                enabled = env_tor == "1"
                net_proxy.set_tor_active(enabled)
        if os.environ.pop(_TOR_SKIP_ENV, None) == "1":
            # Solo para esta sesión: la preferencia guardada no cambia.
            _logger.warning("[TOR] Sesión sin Tor por elección del usuario (tor.enabled se conserva)")
            enabled = False
            net_proxy.set_tor_active(False)

        if not enabled:
            if "proxy-server" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
                os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = ""
            # C-008: sin Tor no deben quedar flags de proxy en argv
            _strip_tor_proxy_args()
            _logger.debug("[TOR] tor.enabled=false, omitiendo proxy")
            return _TOR_OFF
        from tor_manager import TorManager
        tm = TorManager()
        socks_port = config.get("tor.socks_port", 9150)
        _logger.debug("[TOR] Verificando SOCKS5 en 127.0.0.1:%s...", socks_port)
        socks_ready = tm.is_socks5_ready()
        # CRÍTICO: NO usar QTWEBENGINE_CHROMIUM_FLAGS — sobrescribe webEngineArgs y
        # host-resolver-rules tiene espacios que se dividen mal. Usar SOLO sys.argv.
        # Formato Chromium: MAP * ^NOTFOUND bloquea DNS local; EXCLUDE 127.0.0.1 permite
        # conectar al proxy. Ver: chromium.org/developers/design-documents/network-stack/socks-proxy
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)
        webengine_args = [
            "--webEngineArgs",
            f"--proxy-server=socks5://127.0.0.1:{socks_port}",
            "--host-resolver-rules=MAP * ^NOTFOUND , EXCLUDE 127.0.0.1",
            "--proxy-bypass-list=<-loopback>",
            "--disable-webrtc",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        ]
        for arg in webengine_args:
            if arg not in sys.argv:
                sys.argv.append(arg)
        if not socks_ready:
            # A-015: no se desactiva ni se persiste nada; main() preguntará.
            _logger.warning(
                "[TOR] SOCKS5 no disponible en 127.0.0.1:%s. Flags inyectadas igualmente; "
                "se preguntará al usuario (reintentar / continuar sin Tor / salir).",
                socks_port,
            )
            return _TOR_SOCKS_DOWN
        _logger.info("[TOR] Chromium proxy flags inyectados vía --webEngineArgs (sin QTWEBENGINE_CHROMIUM_FLAGS)")
        return _TOR_ON
    except Exception as e:
        # D-004: cualquier fallo (config corrupta, módulo ausente...) no debe
        # impedir el arranque.
        _logger.warning("[TOR] No se pudo configurar el proxy Tor: %s", e, exc_info=True)
        return _TOR_OFF


def _resolve_tor_unavailable() -> str:
    """Tor estaba activado pero el SOCKS no responde: preguntar al usuario.

    Se llama con la QApplication ya creada y antes de crear ninguna vista web.

    Returns:
        "on" si Tor quedó disponible, "continue" (sin Tor esta sesión) o "quit".
    """
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QMessageBox, QProgressDialog
    from tor_manager import TorManager

    tm = TorManager()
    extra = ""
    while True:
        box = QMessageBox(QMessageBox.Warning, "Tor no disponible",
                          "Tor está activado, pero no responde en "
                          f"127.0.0.1:{tm.TOR_SOCKS_PORT}.{extra}")
        box.setInformativeText(
            "Para no navegar con tu IP real todavía no se ha cargado ninguna página.\n\n"
            "Reintentar: arranca Tor y espera a que conecte.\n"
            "Continuar sin Tor: navega sin Tor solo en esta sesión; "
            "la preferencia guardada no cambia.\n"
            "Salir: cierra el navegador."
        )
        retry_btn = box.addButton("Reintentar", QMessageBox.AcceptRole)
        continue_btn = box.addButton("Continuar sin Tor (esta sesión)", QMessageBox.DestructiveRole)
        quit_btn = box.addButton("Salir", QMessageBox.RejectRole)
        box.setDefaultButton(retry_btn)
        box.setEscapeButton(quit_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is continue_btn:
            return "continue"
        if clicked is not retry_btn:
            return "quit"

        if tm.is_socks5_ready():
            return "on"
        if tm.get_availability_error():
            extra = "\n\n" + tm.get_availability_error()
            continue

        # Arrancar Tor en segundo plano con un diálogo de progreso cancelable
        from tor_panel import TorBootstrapWorker, _live_workers
        progress = QProgressDialog("Conectando a la red Tor...", "Cancelar", 0, 100)
        progress.setWindowTitle("Tor")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        worker = TorBootstrapWorker(tm)
        _live_workers.add(worker)
        result = {"ok": False, "error": None, "done": False}
        loop = QEventLoop()
        worker.progress.connect(progress.setValue)
        worker.finished_success.connect(lambda: result.update(ok=True))
        worker.finished_error.connect(lambda msg: result.update(error=msg))
        worker.finished.connect(lambda: result.update(done=True))
        worker.finished.connect(loop.quit)
        worker.finished.connect(lambda w=worker: _live_workers.discard(w))
        worker.finished.connect(worker.deleteLater)

        def _cancel():
            worker.cancel()
            tm.stop()
        progress.canceled.connect(_cancel)
        worker.start()
        progress.show()
        if not result["done"]:
            loop.exec()
        progress.close()
        if result["ok"] and tm.is_socks5_ready():
            return "on"
        if result["error"]:
            extra = f"\n\nNo se pudo arrancar Tor: {result['error']}"
        else:
            extra = "\n\nSe canceló la conexión."


def _configure_stealth_chromium_flags():
    """Inyecta flags Chromium que eliminan las señales de automatización.

    --disable-blink-features=AutomationControlled: impide que Chromium
    establezca navigator.webdriver=true vía C++, que es la señal principal
    que usa Google para redirigir a /sorry/index con CAPTCHA infinito.

    Debe llamarse ANTES de crear QApplication (los flags se leen al inicio).
    Si --webEngineArgs ya está en sys.argv (ej. por Tor), los flags se
    insertan inmediatamente después para que Chromium los recoja.
    """
    stealth_flags = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        # SharedArrayBuffer sin COOP/COEP: necesario para WASM workers (Amazon IVS/Twitch).
        "--enable-features=SharedArrayBuffer",
        # Deshabilitar VA-API (hardware decode) — falla en este sistema (vaMapBuffer2 missing).
        # Forzar FFmpeg software decode, que sí tiene H.264/AAC compilado.
        "--disable-features=VaapiVideoDecoder,VaapiVideoDecodeLinuxGL",
    ]
    if "--webEngineArgs" in sys.argv:
        idx = sys.argv.index("--webEngineArgs")
        for flag in stealth_flags:
            if flag not in sys.argv:
                idx += 1
                sys.argv.insert(idx, flag)
    else:
        sys.argv.append("--webEngineArgs")
        for flag in stealth_flags:
            if flag not in sys.argv:
                sys.argv.append(flag)
    _logger.debug("[STEALTH] Chromium anti-automation flags configurados: %s", stealth_flags)


# ── Instancia única (D-001 / C-002) ───────────────────────────────────────────
# Sustituye al antiguo BookmarkListener (socket TCP 65432 en un hilo): el
# bind() tumbaba la segunda instancia y navigate_to_url se llamaba fuera del
# hilo de la GUI. QLocalServer entrega las conexiones en el hilo principal.
#
# Protocolo: el cliente envía líneas "OPEN <url>" y una línea "END"; el
# servidor responde "OK". Sin respuesta en 1,5 s el servidor se da por muerto
# (p. ej. un socket heredado tras os.execv) y esta instancia toma el relevo.

_INSTANCE_ACK_TIMEOUT_MS = 1500


def _instance_server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = str(os.getuid()) if hasattr(os, "getuid") else "user"
    safe = "".join(c for c in user if c.isalnum() or c in "-_") or "user"
    return f"katphi-browser-{safe}"


def _is_web_url(url: str) -> bool:
    from PySide6.QtCore import QUrl
    qurl = QUrl(url)
    return qurl.isValid() and qurl.scheme().lower() in ("http", "https") and bool(qurl.host())


def _send_to_running_instance(urls: list) -> bool:
    """True si otra instancia viva recibió las URLs (y confirmó con OK)."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_instance_server_name())
    if not sock.waitForConnected(500):
        return False
    try:
        payload = "".join(f"OPEN {u}\n" for u in urls) + "END\n"
        sock.write(payload.encode("utf-8"))
        sock.waitForBytesWritten(500)
        data = b""
        while b"OK" not in data:
            if not sock.waitForReadyRead(_INSTANCE_ACK_TIMEOUT_MS):
                break
            data += bytes(sock.readAll())
        return b"OK" in data
    finally:
        sock.abort()


class _InstanceServer:
    """QLocalServer que recibe URLs de otras instancias (en el hilo GUI)."""

    def __init__(self, on_url):
        from PySide6.QtNetwork import QLocalServer
        self._on_url = on_url
        self._buffers = {}
        self.server = QLocalServer()
        # Solo el mismo usuario puede conectarse
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._on_new_connection)

    def listen(self) -> bool:
        from PySide6.QtNetwork import QLocalServer
        name = _instance_server_name()
        if self.server.listen(name):
            return True
        # Socket huérfano de una instancia que ya no responde: liberarlo
        QLocalServer.removeServer(name)
        if self.server.listen(name):
            return True
        _logger.warning("[INSTANCIA] No se pudo escuchar en %s: %s", name, self.server.errorString())
        return False

    def close(self) -> None:
        try:
            self.server.close()
        except Exception:
            pass

    def _on_new_connection(self) -> None:
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            if sock is None:
                break
            self._buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._on_ready_read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _drop(self, sock) -> None:
        self._buffers.pop(sock, None)
        sock.deleteLater()

    def _on_ready_read(self, sock) -> None:
        buf = self._buffers.get(sock, b"") + bytes(sock.readAll())
        if len(buf) > 64 * 1024:
            # Mensaje anómalo: cortar
            self._buffers.pop(sock, None)
            sock.abort()
            return
        self._buffers[sock] = buf
        if b"END\n" not in buf:
            return
        sock.write(b"OK\n")
        sock.flush()
        for line in buf.decode("utf-8", errors="replace").splitlines():
            if not line.startswith("OPEN "):
                continue
            url = line[5:].strip()
            if _is_web_url(url):
                _logger.info("URL recibida de otra instancia: %s", url)
                try:
                    self._on_url(url)
                except Exception as e:
                    _logger.error("Error abriendo URL recibida: %s", e)
            else:
                _logger.warning("URL rechazada (solo http/https): %r", url[:200])
        try:
            self._on_url(None)   # traer la ventana al frente
        except Exception:
            pass
        sock.disconnectFromServer()


def _open_url_in_window(window, url) -> None:
    """Abre url en una pestaña nueva (url=None: solo activar la ventana)."""
    if url:
        tab_manager = getattr(window, "tab_manager", None)
        if tab_manager is not None and hasattr(tab_manager, "add_new_tab"):
            tab_manager.add_new_tab(url)
        elif getattr(window, "navigation_manager", None):
            window.navigation_manager.navigate_to_url(url)
        return
    if window.isMinimized():
        window.showNormal()
    window.raise_()
    window.activateWindow()


def main():
    # Copia de sys.argv ANTES de cualquier modificación (para reinicio limpio;
    # incluye --private para que el reinicio siga siendo privado).
    sys.argv_original = sys.argv.copy()

    import tor_restart
    tor_restart.init(sys.argv_original)

    private = _parse_private_flag()

    # ── Logging centralizado ──────────────────────────────────────────────────
    # setup_logging() configura: fichero rotante, colores en consola, buffer en
    # memoria, captura de excepciones en hilos y mensajes Qt. En la ventana
    # privada no se escribe nada a disco (solo consola y memoria).
    from logger_setup import setup_logging
    setup_logging(level="DEBUG", file_enabled=not private)

    from constants import APP_NAME

    # CRÍTICO: Configurar proxy Tor ANTES de crear la QApplication.
    tor_state = _configure_tor_proxy_if_needed()
    _configure_stealth_chromium_flags()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Registrar rutas de plugins (paquete bundled + carpeta escribible de usuario)
    # ANTES de importar main_window / el gestor de plugins.
    try:
        import plugin_paths
        plugin_paths.register_sys_path()
        _logger.info(
            "[PLUGINS] bundled=%s  user=%s",
            plugin_paths.BUNDLED_PLUGINS_DIR,
            plugin_paths.USER_PLUGINS_DIR,
        )
    except Exception as _e:  # pragma: no cover
        _logger.warning("[PLUGINS] No se pudo inicializar plugin_paths: %s", _e)
    # QtWebEngineWidgets (vía main_window) debe importarse antes de crear la
    # QApplication.
    from main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setDesktopFileName("katphi-browser")
    _icon_path = os.path.join("icons", "katphi.ico")
    if os.path.exists(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))

    startup_urls = _startup_urls()

    # Instancia única: si ya hay una ventana normal abierta y nos pasan URLs,
    # se le envían y este proceso termina. Sin URLs (p. ej. "Nueva ventana")
    # se abre una ventana independiente, como antes. La ventana privada es
    # siempre un proceso aparte y no participa.
    if not private and startup_urls and _send_to_running_instance(startup_urls):
        _logger.info("URLs enviadas a la instancia en ejecución; saliendo")
        sys.exit(0)

    # A-015: Tor activado pero sin SOCKS → preguntar antes de crear ninguna vista
    if tor_state == _TOR_SOCKS_DOWN:
        # Que cerrar el diálogo (aún no hay ventana principal) no cierre la app
        app.setQuitOnLastWindowClosed(False)
        choice = _resolve_tor_unavailable()
        app.setQuitOnLastWindowClosed(True)
        if choice == "quit":
            sys.exit(0)
        if choice == "continue":
            # Las flags de proxy ya están en los argumentos de la QApplication
            # y Qt WebEngine las leerá al crear el primer perfil: se relanza el
            # proceso sin ellas, solo para esta sesión.
            os.environ[_TOR_SKIP_ENV] = "1"
            tor_restart.relaunch()
            return

    # B-002: QNetworkAccessManager (favicons, etc.) también por Tor
    try:
        import net_proxy
        net_proxy.apply_qt_application_proxy()
    except Exception as e:
        _logger.warning("[TOR] No se pudo aplicar el proxy de aplicación Qt: %s", e)

    window = MainWindow()

    instance_server = None
    if not private:
        try:
            instance_server = _InstanceServer(lambda url: _open_url_in_window(window, url))
            if not instance_server.listen():
                instance_server = None
        except Exception as e:
            # D-001: sin instancia única el navegador funciona igual
            _logger.warning("[INSTANCIA] Servidor de instancia única desactivado: %s", e)
            instance_server = None
    window.show()

    if startup_urls:
        from PySide6.QtCore import QTimer
        for url in startup_urls:
            if _is_web_url(url):
                QTimer.singleShot(0, lambda u=url: _open_url_in_window(window, u))

    try:
        exit_code = app.exec()
    except Exception as e:
        _logger.error("Error de aplicación: %s", e, exc_info=True)
        exit_code = 1
    finally:
        if instance_server:
            instance_server.close()
    sys.exit(exit_code)


def restart_with_tor(enabled: bool, window):
    """Obsoleto: usar ``from tor_restart import restart_with_tor``.

    Se mantiene por compatibilidad; ya no tiene efectos importar este módulo.
    """
    import tor_restart
    tor_restart.restart_with_tor(enabled, window)


if __name__ == "__main__":
    main()
