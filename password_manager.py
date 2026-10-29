from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QLineEdit, QListWidget, QListWidgetItem,
                              QDialog, QMessageBox, QCheckBox, QGroupBox,
                              QApplication, QTableWidget, QTableWidgetItem,
                              QHeaderView, QDialogButtonBox, QFrame,
                              QGraphicsOpacityEffect, QMenu)
from PySide6.QtCore import (Qt, QSettings, Signal, QUrl, QObject, Slot,
                            QTimer, QPropertyAnimation, QEasingCurve,
                            QFile, QIODevice, QPoint)
from PySide6.QtGui import QIntValidator
from PySide6.QtWebChannel import QWebChannel
import html
import json
import logging
from cryptography.fernet import Fernet, InvalidToken
import os
import sys
import sqlite3
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Mundo JS aislado donde viven el QWebChannel y los scripts de captura y
# autorrelleno. El JavaScript de la página (main world, id 0) comparte el DOM
# pero no ve las variables ni el objeto qt.webChannelTransport de este mundo.
try:
    from PySide6.QtWebEngineCore import QWebEngineScript
    _APP_WORLD = int(QWebEngineScript.ScriptWorldId.ApplicationWorld)
except Exception:  # pragma: no cover - PySide6 sin WebEngine
    _APP_WORLD = 1

# Texto que se muestra en la UI para entradas que no se pueden descifrar
UNDECRYPTABLE_LABEL = "[no descifrable]"

# Límites del payload que llega desde JS por el canal
_MAX_PAYLOAD_LEN  = 16384
_MAX_USERNAME_LEN = 512
_MAX_PASSWORD_LEN = 4096

# Tipos de formulario que distingue el script de captura y modos de relleno
_CRED_KINDS = ("login", "signup", "change")
_FILL_MODES = ("full", "username", "password")

# Segundos que se espera a saber si el login ha funcionado, y que se recuerda
# el usuario del paso 1 de un login multipaso
_PENDING_TTL       = 120
_STEP_USERNAME_TTL = 600

# Llavero del sistema (opcional): servicio y entrada para la clave Fernet
_KEYRING_SERVICE = "Katphi"
_KEYRING_ENTRY   = "passwords-encryption-key"

_DB_FILENAME = "passwords.db"


def _is_private_mode() -> bool:
    """True si el proceso es una ventana privada (no se capturan credenciales)."""
    try:
        from constants import is_private_mode
        return bool(is_private_mode())
    except Exception:
        return "--private" in sys.argv


def _user_data_dir() -> Path:
    """Carpeta de datos de usuario (misma convención que plugin_paths.py)."""
    if sys.platform.startswith("win"):
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        root = str(Path.home() / "Library" / "Application Support")
    else:
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(root) / "Katphi"


def _restrict_permissions(path) -> None:
    """chmod 0600 en POSIX (en Windows el perfil del usuario ya es privado)."""
    if os.name != "posix":
        return
    try:
        if os.path.exists(path):
            os.chmod(path, 0o600)
    except OSError as exc:
        logger.warning("[PasswordManager] No se pudo aplicar chmod 600 a %s: %s", path, exc)


def _migrate_legacy_db(legacy: str, new: str) -> bool:
    """Copia la BD antigua (relativa al CWD) a la nueva ruta.

    Usa la API de backup de sqlite (copia consistente aunque haya journal),
    comprueba que el número de filas coincide y solo entonces deja la nueva en
    su sitio. La antigua NO se borra: se renombra a .migrated como copia de
    seguridad (si no se puede renombrar, se deja intacta).
    """
    tmp = new + ".tmp"
    try:
        os.makedirs(os.path.dirname(new), mode=0o700, exist_ok=True)
        src = sqlite3.connect(Path(legacy).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
                n_src = src.execute("SELECT COUNT(*) FROM passwords").fetchone()[0]
                n_dst = dst.execute("SELECT COUNT(*) FROM passwords").fetchone()[0]
            finally:
                dst.close()
        finally:
            src.close()
        if n_src != n_dst:
            raise RuntimeError(f"recuento distinto tras copiar ({n_src} != {n_dst})")
        os.replace(tmp, new)
        _restrict_permissions(new)
        logger.info("[PasswordManager] BD de contraseñas migrada a %s (%d entradas)", new, n_dst)
    except Exception as exc:
        logger.error("[PasswordManager] No se pudo migrar %s -> %s: %s", legacy, new, exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
    try:
        os.replace(legacy, legacy + ".migrated")
    except OSError as exc:
        logger.warning(
            "[PasswordManager] BD migrada; la antigua se deja intacta en %s (%s)", legacy, exc)
    return True


def _resolve_db_path() -> str:
    """Ruta absoluta de passwords.db en el directorio de datos del usuario.

    Si existe una BD antigua en el directorio de trabajo (versiones anteriores
    usaban una ruta relativa al CWD) y la nueva no existe, se migra. Si la
    migración falla, se sigue usando la antigua con su ruta absoluta para no
    perder datos.
    """
    new = str(_user_data_dir() / _DB_FILENAME)
    legacy = os.path.abspath(_DB_FILENAME)
    if os.path.normcase(legacy) == os.path.normcase(new):
        return new
    if not os.path.exists(new) and os.path.isfile(legacy):
        if not _migrate_legacy_db(legacy, new):
            return legacy
    try:
        os.makedirs(os.path.dirname(new), mode=0o700, exist_ok=True)
    except OSError as exc:
        logger.error("[PasswordManager] No se pudo crear %s: %s", os.path.dirname(new), exc)
    return new


def _keyring_module():
    """Devuelve el módulo keyring si está instalado, habilitado y con backend real."""
    try:
        import keyring
        from keyring.backends import fail
    except Exception:
        return None
    try:
        from config_manager import get_config
        if not get_config().use_keyring_for_tokens():
            return None
    except Exception:
        pass  # sin configuración: se usa si está disponible
    try:
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
    except Exception:
        return None
    return keyring

try:
    from password_generator import PasswordGenerator
except ImportError:
    class PasswordGenerator:
        def generate_password(self, length=16, **kwargs):
            import random
            import string
            chars = string.ascii_letters + string.digits + "!@#$%^&*"
            return {
                "password": ''.join(random.choice(chars) for _ in range(length)),
                "time": "0.1s",
                "cpu_usage": "1%",
                "ram_usage": "1MB",
            }


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1")


def _is_insecure_origin(origin: str) -> bool:
    """http:// que no es la propia máquina (la contraseña viaja en claro)."""
    if not origin.startswith("http://"):
        return False
    host = (urlparse(origin).hostname or "").lower()
    return host not in _LOCAL_HOSTS and not host.endswith(".localhost")


def _normalize_origin(url_str: str) -> str:
    """Normalize a URL to its origin (scheme://host[:port])."""
    try:
        parsed = urlparse(url_str)
        scheme = parsed.scheme or "https"
        host = parsed.hostname or ""
        port = parsed.port
        if port and port not in (80, 443):
            return f"{scheme}://{host}:{port}"
        return f"{scheme}://{host}"
    except Exception:
        return url_str


# ---------------------------------------------------------------------------
# CredentialReceiver — Python object exposed to JS via QWebChannel
# ---------------------------------------------------------------------------

class CredentialReceiver(QObject):
    """Receives credentials from the JS capture script via QWebChannel.

    The JS side calls  window.__katphi.onCredential(jsonString)  which
    triggers the @Slot below in the Python main thread — no timing issues,
    no virtual-method override problems.

    Seguridad: el canal solo existe en el ApplicationWorld (la página no lo
    ve) y, aun así, el origen NUNCA se toma del payload: se calcula aquí a
    partir de la URL real del browser (origin_getter).
    """

    credential_received = Signal(str, object)  # origin, {username, password, old_password, kind}
    username_captured   = Signal(str, str)     # origin, usuario (paso 1 de un login multipaso)
    login_outcome       = Signal(str, str)     # origin, "success"
    page_ready          = Signal(str, str, bool)  # origin, id de documento, ¿pide login?
    autofill_requested  = Signal(str, object)  # origin, {username, hidden_user, mode, auto, rect}

    def __init__(self, parent=None, origin_getter=None, flags_getter=None):
        super().__init__(parent)
        self._origin_getter = origin_getter
        # origin -> {"has": bool, "auto": bool}; lo da PasswordManager
        self._flags_getter = flags_getter
        self._last_fill_request = 0.0

    @staticmethod
    def _doc_id(data) -> str:
        doc = data.get("doc", "")
        return doc if isinstance(doc, str) and len(doc) <= 64 else ""

    def _current_origin(self) -> str:
        """Origen (solo http/https) de la URL actual del browser propietario."""
        try:
            url = self._origin_getter() if self._origin_getter else ""
        except Exception:
            return ""
        if not isinstance(url, str) or not url:
            return ""
        try:
            scheme = (urlparse(url).scheme or "").lower()
        except Exception:
            return ""
        if scheme not in ("http", "https"):
            return ""
        return _normalize_origin(url)

    @staticmethod
    def _parse_payload(json_str):
        """JSON -> dict, o None si no es válido (tipo, tamaño o estructura)."""
        if not isinstance(json_str, str) or len(json_str) > _MAX_PAYLOAD_LEN:
            return None
        try:
            data = json.loads(json_str)
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    @Slot(str)
    def onCredential(self, json_str: str) -> None:
        try:
            data = self._parse_payload(json_str)
            if data is None:
                logger.warning("[PasswordManager] Payload de credencial descartado (formato)")
                return
            username = data.get("username", "")
            password = data.get("password", "")
            old_password = data.get("old_password", "") or ""
            kind = data.get("kind", "login")
            if not all(isinstance(v, str) for v in (username, password, old_password)):
                return
            # Usuario vacío permitido: paso 2 de un login multipaso o cambio de
            # contraseña (Python lo resuelve)
            if (not password or len(username) > _MAX_USERNAME_LEN
                    or len(password) > _MAX_PASSWORD_LEN
                    or len(old_password) > _MAX_PASSWORD_LEN):
                return
            if kind not in _CRED_KINDS:
                kind = "login"
            # El campo "origin" del payload se ignora a propósito
            origin = self._current_origin()
            if not origin:
                return
            logger.info("[PasswordManager] Credential received via WebChannel: %s (%s)",
                        origin, kind)
            self.credential_received.emit(origin, {
                "username": username, "password": password,
                "old_password": old_password, "kind": kind,
                "doc": self._doc_id(data)})
        except Exception as exc:
            logger.error("[PasswordManager] Error parsing credential payload: %s", exc)

    @Slot(str)
    def onUsername(self, json_str: str) -> None:
        """Formulario con solo el usuario enviado (paso 1 de un login multipaso)."""
        try:
            data = self._parse_payload(json_str)
            if data is None:
                return
            username = data.get("username", "")
            if not isinstance(username, str) or not username or len(username) > _MAX_USERNAME_LEN:
                return
            origin = self._current_origin()
            if origin:
                self.username_captured.emit(origin, username)
        except Exception as exc:
            logger.error("[PasswordManager] Error parsing username payload: %s", exc)

    @Slot(str, result=str)
    def hello(self, json_str: str) -> str:
        """Documento nuevo conectado al canal: ¿hay credenciales y relleno automático?"""
        flags = {"has": False, "auto": False}
        try:
            origin = self._current_origin()
            if origin and self._flags_getter is not None:
                got = self._flags_getter(origin) or {}
                flags = {"has": bool(got.get("has")), "auto": bool(got.get("auto"))}
        except Exception as exc:
            logger.error("[PasswordManager] Error in hello: %s", exc)
        return json.dumps(flags)

    @Slot(str)
    def onPageReady(self, json_str: str) -> None:
        """Un segundo después de cargar: id del documento y si muestra un login vacío."""
        try:
            data = self._parse_payload(json_str)
            if data is None:
                return
            doc = self._doc_id(data)
            origin = self._current_origin()
            if origin and doc:
                self.page_ready.emit(origin, doc, data.get("login_form") is True)
        except Exception as exc:
            logger.error("[PasswordManager] Error parsing page-ready payload: %s", exc)

    @Slot(str)
    def onLoginOutcome(self, json_str: str) -> None:
        """La página indica que el formulario de login ha desaparecido (SPA)."""
        try:
            data = self._parse_payload(json_str)
            if data is None or data.get("result") != "success":
                return
            origin = self._current_origin()
            if origin:
                self.login_outcome.emit(origin, "success")
        except Exception as exc:
            logger.error("[PasswordManager] Error parsing login outcome: %s", exc)

    @staticmethod
    def _parse_rect(value):
        """[x, y, ancho, alto] del campo en píxeles CSS, o None."""
        if not isinstance(value, list) or len(value) != 4:
            return None
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
            return None
        return [max(-1e5, min(1e5, float(v))) for v in value]

    @Slot(str)
    def requestAutofill(self, json_str: str) -> None:
        """Campo de login pulsado/tabulado, o formulario visible al cargar (auto)."""
        try:
            now = time.monotonic()
            if now - self._last_fill_request < 0.5:
                return
            self._last_fill_request = now
            data = self._parse_payload(json_str)
            if data is None:
                return
            info = {}
            for key in ("username", "hidden_user"):
                v = data.get(key, "")
                info[key] = v if isinstance(v, str) and len(v) <= _MAX_USERNAME_LEN else ""
            mode = data.get("mode", "full")
            info["mode"] = mode if mode in _FILL_MODES else "full"
            info["auto"] = data.get("auto") is True
            info["rect"] = self._parse_rect(data.get("rect"))
            origin = self._current_origin()
            if origin:
                self.autofill_requested.emit(origin, info)
        except Exception as exc:
            logger.error("[PasswordManager] Error en la petición de autorrelleno: %s", exc)


# ---------------------------------------------------------------------------
# PasswordSaveBanner — non-intrusive banner shown below the nav bar
# ---------------------------------------------------------------------------

class PasswordSaveBanner(QFrame):
    """Non-intrusive banner shown below the nav bar when credentials are detected."""

    accepted  = Signal()
    dismissed = Signal()
    never     = Signal()   # "Never for this site" (persistente)
    timed_out = Signal()   # se cerró solo: no cuenta como "Not now"

    def __init__(self, url: str, username: str, password: str,
                 is_update: bool = False, parent=None, insecure: bool = False):
        super().__init__(parent)
        self.url       = url
        self.username  = username
        self.password  = password
        self.is_update = is_update
        self.insecure  = insecure
        self.setObjectName("passwordSaveBanner")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(48)
        self._build_ui()
        self._apply_style()
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(15_000)
        self._auto_timer.timeout.connect(self._on_timeout)
        self._auto_timer.start()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        key_icon = QLabel()
        try:
            from ui.core.strip_icons import build_nav_icon
            from PySide6.QtCore import QSize
            key_icon.setPixmap(build_nav_icon("key", None, QSize(16, 16)).pixmap(16, 16))
        except Exception:
            pass
        layout.addWidget(key_icon)

        action = "Update" if self.is_update else "Save"
        origin = _normalize_origin(self.url)
        text = f"{action} password for <b>{html.escape(self.username)}</b> on {html.escape(origin)}?"
        if self.insecure:
            text += " <i>(not secure connection: it can be intercepted)</i>"
        lbl = QLabel(text)
        lbl.setTextFormat(Qt.RichText)
        layout.addWidget(lbl, 1)

        save_btn = QPushButton("Update" if self.is_update else "Save")
        save_btn.setFixedHeight(30)
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._on_accept)
        layout.addWidget(save_btn)

        dismiss_btn = QPushButton("Not now")
        dismiss_btn.setFixedHeight(30)
        dismiss_btn.setCursor(Qt.PointingHandCursor)
        dismiss_btn.clicked.connect(self._on_dismiss)
        layout.addWidget(dismiss_btn)

        if not self.is_update:
            never_btn = QPushButton("Never for this site")
            never_btn.setFixedHeight(30)
            never_btn.setCursor(Qt.PointingHandCursor)
            never_btn.clicked.connect(self._on_never)
            layout.addWidget(never_btn)

    def _apply_style(self):
        self.setStyleSheet("""
            QFrame#passwordSaveBanner {
                background-color: rgba(30, 80, 160, 0.92);
                border-bottom: 1px solid rgba(100, 160, 255, 0.4);
            }
            QFrame#passwordSaveBanner QLabel {
                color: #f0f0f0;
                font-size: 13px;
            }
            QFrame#passwordSaveBanner QPushButton {
                background-color: rgba(255, 255, 255, 0.15);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 4px;
                padding: 2px 14px;
                font-size: 12px;
            }
            QFrame#passwordSaveBanner QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.28);
            }
        """)

    def _on_accept(self):
        self._auto_timer.stop()
        self.accepted.emit()
        self._animate_out()

    def _on_dismiss(self):
        self._auto_timer.stop()
        self.dismissed.emit()
        self._animate_out()

    def _on_never(self):
        self._auto_timer.stop()
        self.never.emit()
        self._animate_out()

    def _on_timeout(self):
        self.timed_out.emit()
        self._animate_out()

    def _animate_out(self):
        try:
            anim = QPropertyAnimation(self, b"maximumHeight", self)
            anim.setDuration(200)
            anim.setStartValue(self.height())
            anim.setEndValue(0)
            anim.setEasingCurve(QEasingCurve.InQuad)
            anim.finished.connect(self.deleteLater)
            anim.start()
        except Exception:
            self.deleteLater()


# ---------------------------------------------------------------------------
# JS capture script
#
# Communication path:
#   form submit / submit-like button click / Enter key
#     → tryCapture()
#       → window.__katphi.onCredential(json)   [QWebChannel slot call]
#         → CredentialReceiver.onCredential()      [Python main thread]
#
# Guardado provisional (como Chrome/Firefox): la captura NO muestra el banner.
# Python la guarda como pendiente y solo la ofrece si el login funciona:
#   - el campo de contraseña desaparece de la página (SPA) → onLoginOutcome
#   - o la pestaña navega y en la página nueva no hay un formulario de login
#     vacío (si reaparece, el login ha fallado y se descarta).
#
# Botones: <button>, role="button", <input type="submit|button"> y <a> sin
# href de navegación. Se ignoran "olvidé mi contraseña", "cancelar", el icono
# de mostrar/ocultar contraseña y similares.
#
# Tipos de formulario (por número de campos y autocomplete):
#   login  → 1 contraseña
#   signup → new-password, o 2 contraseñas iguales (se guarda la nueva)
#   change → current-password + new-password, o actual + nueva (+ repetir)
# Login multipaso (Google, Microsoft): un formulario con solo el usuario envía
# onUsername; Python lo recuerda para el paso de la contraseña. También se lee
# el campo oculto autocomplete="username" que muchos sitios dejan en el paso 2.
#
# Containers searched (in priority order):
#   <form> → [role="dialog|alertdialog"] → class/id patterns for modal/login
#   → document.body as last resort.
#
# Debounce: 400 ms prevents duplicate emits when click + submit both fire.
# Si el WebChannel aún no está conectado, las llamadas se encolan.
#
# Este script se ejecuta en el ApplicationWorld (mundo aislado): la página no
# puede llamar a window.__katphi ni ver qt.webChannelTransport. El origen no
# se envía (Python lo calcula a partir de la URL real del browser).
#
# Inyección: QWebEngineScript en DocumentReady y en todos los frames (no
# depende de loadFinished). Qt solo instala qt.webChannelTransport en el frame
# principal, así que los iframes hablan con Python a través del script del
# frame principal (window.top.__katphiRelay, mismo mundo aislado). Solo los
# iframes del MISMO origen que la pestaña: desde otro origen, acceder a
# window.top lanza SecurityError y el script queda inerte (si no, Python les
# atribuiría el origen de la pestaña).
#
# Al conectar el canal, hello() devuelve si hay credenciales guardadas
# (__katphiHasCreds) y si se permite rellenar sin gesto (__katphiAutoAllowed:
# una sola cuenta y https). onPageReady (con un id de documento) permite a
# Python saber si tras enviar el login la página nueva vuelve a pedirlo.
#
# Autorrelleno con gesto: se pide cuando el usuario hace clic o llega con Tab
# a un campo de login (evento isTrusted, no sintetizable por la página). Con
# varias cuentas (o en http) Python muestra un menú para elegir. Python
# responde llamando a window.__katphiFill() en el frame principal con UNA sola
# credencial, que la pasa al frame que hizo la petición.
# ---------------------------------------------------------------------------

_CAPTURE_JS = r'''
(function() {
    if (window.__katphiCapture) return;
    var isTop = window === window.top;
    var T = window.top;   // estado compartido y canal: en el frame principal
    try { void T.location.href; } catch(e) { return; }   // iframe de otro origen
    window.__katphiCapture     = true;
    // Id de este documento: distingue la página del envío de la siguiente
    var DOC = Math.random().toString(36).slice(2) + Date.now().toString(36);
    if (isTop) {
        window.__katphi            = null;
        window.__katphiQueue       = [];
        window.__katphiHasCreds    = false;
        window.__katphiAutoAllowed = false;
        window.__katphiAutoDone    = false;
        window.__katphiFillFrame   = null;
    }
    window.__katphiLastEmit    = 0;
    window.__katphiLastFill    = 0;
    window.__katphiFillTarget  = null;
    window.__katphiWatch       = null;

    // ── Helpers ──────────────────────────────────────────────────────────

    function acTokens(inp) {
        return (inp.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/);
    }

    function hasTok(inp, tok) { return acTokens(inp).indexOf(tok) !== -1; }

    function inputs(root) {
        return root ? Array.prototype.slice.call(root.querySelectorAll('input')) : [];
    }

    function isVisible(el) {
        if (!el || !el.isConnected || el.type === 'hidden') return false;
        if (!el.getClientRects().length || !el.offsetWidth || !el.offsetHeight) return false;
        var s = window.getComputedStyle(el);
        return s.visibility !== 'hidden' && s.display !== 'none';
    }

    function isPasswordField(inp) {
        if (!inp || inp.tagName !== 'INPUT') return false;
        var t = (inp.type || '').toLowerCase();
        if (t === 'password') return true;
        // "Mostrar contraseña" activado: type=text pero conserva el autocomplete
        return t === 'text' &&
               (hasTok(inp, 'current-password') || hasTok(inp, 'new-password'));
    }

    function isUsernameField(inp) {
        if (!inp || inp.type === 'hidden' || isPasswordField(inp)) return false;
        var t  = (inp.type || '').toLowerCase();
        if (t === 'submit' || t === 'button' || t === 'checkbox' ||
            t === 'radio'  || t === 'file') return false;
        if (t === 'email') return true;
        if (hasTok(inp, 'username') || hasTok(inp, 'email') || hasTok(inp, 'tel')) return true;
        var attrs = [(inp.name  || ''), (inp.id   || ''),
                     (inp.placeholder || ''),
                     (inp.getAttribute('aria-label') || '')].join(' ').toLowerCase();
        var kw = ['user','email','login','account','nick','identifier',
                  'phone','mobile','correo','usuario','nombre','mail','tel'];
        for (var i = 0; i < kw.length; i++) {
            if (attrs.indexOf(kw[i]) !== -1) return true;
        }
        return false;
    }

    // Más estricto: para rellenar sin gesto un formulario de solo usuario
    // (no un campo de newsletter cualquiera)
    function isLoginUsername(inp) {
        if (!isUsernameField(inp)) return false;
        if (hasTok(inp, 'username') || hasTok(inp, 'webauthn')) return true;
        return /identifier|login|user/.test(((inp.name || '') + ' ' + (inp.id || '')).toLowerCase());
    }

    // Campos de contraseña visibles o con valor (los ocultos y vacíos suelen
    // ser trampas anti-bot)
    function passwordFields(root, needVisible) {
        return inputs(root).filter(function(i) {
            return isPasswordField(i) && (isVisible(i) || (!needVisible && !!i.value));
        });
    }

    function findUsername(root, pw) {
        var all = inputs(root);
        var start = pw ? all.indexOf(pw) : all.length;
        for (var j = start - 1; j >= 0; j--) {
            if (isUsernameField(all[j]) && isVisible(all[j])) return all[j];
        }
        for (var k = 0; k < all.length; k++) {
            if (isUsernameField(all[k]) && isVisible(all[k])) return all[k];
        }
        return null;
    }

    // Paso 2 de un login multipaso: el usuario suele ir en un campo oculto
    function hiddenUsername(root) {
        var all = inputs(root).concat(inputs(document));
        for (var i = 0; i < all.length; i++) {
            if (all[i].value && hasTok(all[i], 'username') && !isPasswordField(all[i]))
                return all[i].value;
        }
        return '';
    }

    // Clasifica el formulario y extrae la credencial a guardar
    function analyze(root) {
        var pws = passwordFields(root, false).filter(function(i) { return !!i.value; });
        if (!pws.length || pws.length > 3) return null;
        var news = pws.filter(function(i) { return hasTok(i, 'new-password'); });
        var curs = pws.filter(function(i) { return hasTok(i, 'current-password'); });
        var kind = 'login', pass = '', old = '', field = pws[0];
        if (news.length) {
            if (news.length > 1 && news[0].value !== news[1].value) return null;
            pass = news[0].value; field = news[0];
            if (curs.length) { kind = 'change'; old = curs[0].value; }
            else kind = 'signup';
        } else if (pws.length === 1) {
            pass = pws[0].value;
        } else if (pws.length === 2) {
            if (pws[0].value === pws[1].value) { kind = 'signup'; pass = pws[0].value; }
            else { kind = 'change'; old = pws[0].value; pass = pws[1].value; field = pws[1]; }
        } else {
            if (pws[1].value !== pws[2].value) return null;   // la repetición no coincide
            kind = 'change'; old = pws[0].value; pass = pws[1].value; field = pws[1];
        }
        var u = findUsername(root, pws[0]);
        return { kind: kind, password: pass, old_password: old, field: field,
                 username: (u && u.value) || hiddenUsername(root) };
    }

    // Formulario con solo usuario (paso 1 de un login multipaso)
    function loneUsername(root) {
        if (passwordFields(root, true).length) return '';
        var u = findUsername(root, null);
        return (u && u.value) ? u.value : '';
    }

    function findContainer(el) {
        var form   = el.closest('form');
        if (form)   return form;
        var dialog = el.closest('[role="dialog"],[role="alertdialog"]');
        if (dialog) return dialog;
        var modal  = el.closest(
            '[class*="modal"],[class*="popup"],[class*="login"],' +
            '[class*="signin"],[class*="sign-in"],[class*="auth"],' +
            '[id*="modal"],[id*="login"],[id*="signin"]'
        );
        if (modal)  return modal;
        return document.body;
    }

    function findButtonAncestor(el) {
        var cur = el;
        while (cur && cur !== document.body) {
            var tag  = (cur.tagName              || '').toLowerCase();
            var type = (cur.getAttribute('type') || '').toLowerCase();
            var role = (cur.getAttribute('role') || '').toLowerCase();
            if (tag === 'button' ||
                (tag === 'input' && (type === 'submit' || type === 'button')) ||
                role === 'button' ||
                tag === 'a') return cur;
            cur = cur.parentElement;
        }
        return null;
    }

    var SKIP_BTN = /forgot|olvid|recuper|reset|restablec|recover|cancel|mostrar|ocultar|show|hide|ver contrase/i;

    // ¿Es un botón que envía el login? (no "olvidé mi contraseña", no el ojo)
    function isSubmitLike(btn) {
        var text = (btn.innerText || btn.value || '').trim();
        var label = text + ' ' + (btn.getAttribute('aria-label') || '') + ' ' +
                    (btn.getAttribute('title') || '');
        if (SKIP_BTN.test(label)) return false;
        if (btn.tagName === 'A') {
            var href = (btn.getAttribute('href') || '').trim().toLowerCase();
            if (href && href.charAt(0) !== '#' && href.indexOf('javascript:') !== 0) return false;
        }
        if (!text && !(btn.tagName === 'BUTTON' && btn.type === 'submit')) {
            // Icono sin texto junto al campo: el botón de mostrar contraseña
            var p = btn.parentElement;
            for (var i = 0; i < 2 && p; i++, p = p.parentElement) {
                if (passwordFields(p, true).length) return false;
            }
        }
        return true;
    }

    // ── Emit ─────────────────────────────────────────────────────────────

    // fillFn: en requestAutofill, función que rellena el frame que pregunta
    function call(name, payload, fillFn) {
        if (!isTop) {
            var tries = 0;
            (function relay() {
                try {
                    if (T.__katphiRelay) { T.__katphiRelay(name, payload, fillFn || null); return; }
                } catch(e) { return; }
                if (++tries < 20) setTimeout(relay, 250);   // el top aún no ha cargado
            })();
            return;
        }
        if (name === 'requestAutofill') window.__katphiFillFrame = fillFn || null;
        if (window.__katphi) {
            try { window.__katphi[name](payload); } catch(e) {}
        } else if (window.__katphiQueue.length < 10) {
            // Channel not ready yet; send when it connects
            window.__katphiQueue.push([name, payload, fillFn]);
        }
    }

    if (isTop) window.__katphiRelay = call;

    function debounced() {
        var now = Date.now();
        if (now - window.__katphiLastEmit < 400) return false;
        window.__katphiLastEmit = now;
        return true;
    }

    // Documentos de la pestaña accesibles (frame principal + iframes del mismo origen)
    function allDocs() {
        var out = [], stack = [T];
        while (stack.length && out.length < 50) {
            var w = stack.pop();
            try { var d = w.document; void d.documentElement; out.push(d); }
            catch(e) { continue; }
            for (var i = 0; i < w.frames.length; i++) stack.push(w.frames[i]);
        }
        return out;
    }

    function loginFormShown() {
        var docs = allDocs();
        for (var d = 0; d < docs.length; d++) {
            var all = inputs(docs[d]);
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                if (isPasswordField(el) && isVisible(el) && !el.value &&
                    !hasTok(el, 'new-password')) return true;
            }
        }
        return false;
    }
    if (isTop) window.__katphiLoginFormShown = loginFormShown;

    // Login de una SPA: el campo desaparece sin navegar. Si en su lugar
    // aparece otro formulario de login vacío (re-render tras un error), no.
    function watchOutcome(field) {
        if (window.__katphiWatch) clearInterval(window.__katphiWatch);
        var n = 0, gone = 0;
        window.__katphiWatch = setInterval(function() {
            n++;
            gone = (isVisible(field) || loginFormShown()) ? 0 : gone + 1;
            if (gone >= 2 || n >= 40) {
                clearInterval(window.__katphiWatch);
                window.__katphiWatch = null;
                if (gone >= 2) call('onLoginOutcome', JSON.stringify({ result: 'success' }));
            }
        }, 500);
    }

    function tryCapture(container) {
        var a = analyze(container);
        if (a) {
            if (!debounced()) return;
            call('onCredential', JSON.stringify({
                username: a.username, password: a.password,
                old_password: a.old_password, kind: a.kind, doc: DOC
            }));
            watchOutcome(a.field);
            return;
        }
        var u = loneUsername(container);
        if (u && debounced()) call('onUsername', JSON.stringify({ username: u }));
    }

    // ── Connect to QWebChannel ───────────────────────────────────────────
    // qt.webChannelTransport is injected by Qt when page.setWebChannel() was called.

    if (isTop && typeof QWebChannel !== 'undefined' &&
        typeof qt !== 'undefined' && qt.webChannelTransport) {
        new QWebChannel(qt.webChannelTransport, function(channel) {
            window.__katphi = channel.objects.credReceiver;
            window.__katphi.hello(JSON.stringify({ doc: DOC }), function(res) {
                try {
                    var r = JSON.parse(res);
                    window.__katphiHasCreds    = !!r.has;
                    window.__katphiAutoAllowed = !!r.auto;
                } catch(e) {}
            });
            var q = window.__katphiQueue;
            window.__katphiQueue = [];
            for (var i = 0; i < q.length; i++) call(q[i][0], q[i][1], q[i][2]);
            // Margen para que la página pinte su formulario (SPA)
            setTimeout(function() {
                call('onPageReady', JSON.stringify({ doc: DOC, login_form: loginFormShown() }));
            }, 1000);
        });
    }

    // ── Event listeners (document-level capture) ─────────────────────────

    // 1. Traditional <form> submit (fires before navigation)
    document.addEventListener('submit', function(e) {
        try {
            var form = e.target;
            if (form && form.tagName === 'FORM') tryCapture(form);
        } catch(ex) {}
    }, true);

    // 2. Click on a submit-like element (React/Vue modals, type="button")
    document.addEventListener('click', function(e) {
        try {
            var btn = findButtonAncestor(e.target);
            if (btn && isSubmitLike(btn)) tryCapture(findContainer(btn));
        } catch(ex) {}
    }, true);

    // 3. Enter key in any input (single-field forms, modal text fields)
    document.addEventListener('keydown', function(e) {
        try {
            if (e.key !== 'Enter' && e.keyCode !== 13) return;
            var t = e.target;
            if (t && t.tagName === 'INPUT') tryCapture(findContainer(t));
        } catch(ex) {}
    }, true);

    // ── Autorrelleno ─────────────────────────────────────────────────────

    // Qué campos se pueden rellenar. Nunca un new-password (registro).
    function fillPlan(root) {
        var pws = passwordFields(root, true);
        var pw = null, kind = 'login';
        if (pws.length === 1 && !hasTok(pws[0], 'new-password')) {
            pw = pws[0];
        } else if (pws.length > 1) {
            var curs = pws.filter(function(i) { return hasTok(i, 'current-password'); });
            if (curs.length !== 1) return null;
            pw = curs[0]; kind = 'change';
        } else if (pws.length) {
            return null;
        }
        var user = kind === 'change' ? null : findUsername(root, pw);
        if (!pw && !user) return null;
        return { pw: pw, user: user, kind: kind,
                 mode: pw ? (user ? 'full' : 'password') : 'username' };
    }

    // Rectángulo del campo en coordenadas del frame principal (para el menú)
    function viewportRect(el) {
        var r = el.getBoundingClientRect(), x = r.left, y = r.top, w = window;
        try {
            while (w !== w.top && w.frameElement) {
                var fe = w.frameElement, fr = fe.getBoundingClientRect();
                x += fr.left + fe.clientLeft;
                y += fr.top + fe.clientTop;
                w = w.parent;
            }
        } catch(e) {}
        return [x, y, r.width, r.height];
    }

    function requestFill(c, p, t, auto) {
        window.__katphiFillTarget = c;
        call('requestAutofill', JSON.stringify({
            username: p.user ? (p.user.value || '') : '',
            hidden_user: p.user ? '' : hiddenUsername(c),
            mode: p.mode,
            auto: !!auto,
            rect: viewportRect(t)
        }), isTop ? null : doFill);
    }

    function maybeRequestFill(e) {
        try {
            if (!e.isTrusted || !T.__katphiHasCreds || !T.__katphi) return;
            var t = e.target;
            if (!t || t.tagName !== 'INPUT') return;
            var c = findContainer(t);
            var p = fillPlan(c);
            if (!p || (t !== p.pw && t !== p.user)) return;
            if (p.pw && p.pw.value) return;
            var now = Date.now();
            if (now - window.__katphiLastFill < 1000) return;
            window.__katphiLastFill = now;
            requestFill(c, p, t, false);
        } catch(ex) {}
    }

    document.addEventListener('mousedown', maybeRequestFill, true);
    document.addEventListener('keyup', function(e) {
        if (e.key === 'Tab') maybeRequestFill(e);
    }, true);

    // Relleno al cargar (una sola cuenta): primer formulario de login visible
    function tryAuto() {
        try {
            if (T.__katphiAutoDone || !T.__katphiAutoAllowed || !T.__katphi) return;
            var all = inputs(document);
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                if (!isVisible(el) || !(isPasswordField(el) || isLoginUsername(el))) continue;
                var c = findContainer(el), p = fillPlan(c);
                if (!p || p.kind !== 'login') continue;
                if (p.mode === 'username' && !isLoginUsername(p.user)) continue;
                T.__katphiAutoDone = true;
                if ((p.pw && p.pw.value) || (p.mode === 'username' && p.user.value)) return;
                requestFill(c, p, p.pw || p.user, true);
                return;
            }
        } catch(ex) {}
    }

    // Los flags llegan con hello() y los formularios de las SPA aparecen
    // tarde: se reintenta unos segundos (en cada frame)
    (function startAuto() {
        var n = 0;
        var iv = setInterval(function() {
            n++;
            tryAuto();
            if (T.__katphiAutoDone || n >= 20) clearInterval(iv);
        }, 500);
    })();

    function setVal(el, v) {
        try {
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')
                  .set.call(el, v);
        } catch(e) { el.value = v; }
        el.dispatchEvent(new Event('input',  {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }

    // Rellena este frame con una única credencial si su origen es el
    // esperado. Sin password (cred.password vacío) solo se rellena el usuario.
    function doFill(cred, expectedOrigin) {
        try {
            // Origen del documento (también en iframes srcdoc/about:blank, que
            // lo heredan); misma forma que _normalize_origin() en Python
            var here = window.origin;
            if (!here || here === 'null') {
                var port = window.location.port;
                here = window.location.protocol + '//' + window.location.hostname +
                       ((port && port !== '80' && port !== '443') ? ':' + port : '');
            }
            if (!cred || here !== expectedOrigin) return false;
            var c = window.__katphiFillTarget || document.body;
            window.__katphiFillTarget = null;
            var p = fillPlan(c);
            if (!p) return false;
            var done = false;
            if (p.user && cred.username) {
                var v = (p.user.value || '').toLowerCase();
                // El usuario está escribiendo otra cuenta: no se toca nada
                if (v && cred.username.toLowerCase().indexOf(v) !== 0) return false;
                if (p.user.value !== cred.username) setVal(p.user, cred.username);
                done = true;
            }
            if (p.pw && cred.password && !p.pw.value) {
                setVal(p.pw, cred.password);
                done = true;
            }
            return done;
        } catch(ex) { return false; }
    }

    // Python la llama en el frame principal; se rellena el frame que hizo la
    // petición (ownFrame: desde la llave de la barra de URL, el principal)
    if (isTop) window.__katphiFill = function(cred, expectedOrigin, ownFrame) {
        var f = ownFrame ? null : window.__katphiFillFrame;
        window.__katphiFillFrame = null;
        if (ownFrame) window.__katphiFillTarget = null;
        try { return f ? f(cred, expectedOrigin) : doFill(cred, expectedOrigin); }
        catch(ex) { return false; }
    };
})();
'''


# ---------------------------------------------------------------------------
# PasswordManager — main widget + DB + encryption + browser integration
# ---------------------------------------------------------------------------

class PasswordManager(QWidget):
    password_saved   = Signal(str, str)  # url, username
    password_updated = Signal(str, str)  # url, username
    password_deleted = Signal(str)       # url

    # Class-level cache: qwebchannel.js loaded once from Qt resources
    _qwebchannel_js: str = ""

    # Los tests lo ponen a False para no abrir diálogos modales
    _show_dialogs: bool = True

    def __init__(self, parent=None, db_path=None):
        super().__init__(parent)
        self.parent = parent
        self.password_generator = PasswordGenerator()
        self.settings  = QSettings("Katphi", "Passwords")
        # Ruta absoluta en el directorio de datos del usuario (con migración
        # desde la antigua passwords.db relativa al CWD)
        self.db_path   = os.path.abspath(db_path) if db_path else _resolve_db_path()
        self.fernet    = None
        self.conn      = None
        self._browser_connections: dict = {}   # browser_id → {"signals": [...], "receiver": ..., "channel": ...}
        self._dismissed_origins:   set  = set()
        self._active_banner              = None
        self._pending:        dict       = {}  # browser_id → captura provisional (espera al login)
        self._step_usernames: dict       = {}  # browser_id → (origin, usuario, t) del paso 1
        self._account_menu               = None
        self._unsaved:        dict       = {}  # browser_id → credencial ofrecida y no guardada
        self._script_name                = "katphi-passwords"
        self._url_bar                    = None
        self._key_action                 = None
        self._current_browser_getter     = None
        self._notified: set              = set()
        self.init_ui()
        # El cifrado va antes que cualquier lectura o escritura de la BD
        self.setup_encryption()
        self.init_database()
        self.load_passwords()

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Aviso visible para errores de cifrado o de BD (oculto por defecto)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #d9534f; font-weight: bold;")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search passwords...")
        self.search_input.setFixedHeight(32)
        if hasattr(self.search_input, "setClearButtonEnabled"):
            self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.filter_passwords)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        self.passwords_list = QListWidget()
        self.passwords_list.setToolTip("Double-click to view password details")
        # Se conecta una sola vez (antes se reconectaba en cada load_passwords)
        self.passwords_list.itemDoubleClicked.connect(self.view_password_details)
        layout.addWidget(self.passwords_list)

        buttons_layout = QHBoxLayout()
        for label, slot in [
            ("Add",      self.add_password),
            ("View",     lambda: self.view_password_details(self.passwords_list.currentItem())
                         if self.passwords_list.currentItem() else None),
            ("Edit",     self.edit_password),
            ("Remove",   self.remove_password),
            ("Generate", self.show_generator),
            ("Exceptions", self.show_never_save_sites),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            buttons_layout.addWidget(btn)
        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def _notify_user(self, title: str, message: str, key: str = None) -> None:
        """Muestra el problema en el panel y, una vez por tipo, en un diálogo."""
        logger.warning("[PasswordManager] %s: %s", title, message)
        try:
            self.status_label.setText(message)
            self.status_label.show()
        except Exception:
            pass
        key = key or title
        if key in self._notified:
            return
        self._notified.add(key)
        if self._show_dialogs:
            QTimer.singleShot(0, lambda: QMessageBox.warning(self, title, message))

    # -----------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------

    _CREATE_TABLE_SQL = '''
                CREATE TABLE IF NOT EXISTS passwords (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    url        TEXT NOT NULL,
                    username   TEXT NOT NULL,
                    password   TEXT NOT NULL,
                    notes      TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''

    # Sitios marcados con "Never for this site" (no se ofrece guardar)
    _CREATE_NEVER_SQL = '''
                CREATE TABLE IF NOT EXISTS never_save (
                    origin     TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''

    def _open_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(self._CREATE_TABLE_SQL)
        conn.execute(self._CREATE_NEVER_SQL)
        conn.execute("SELECT COUNT(*) FROM passwords").fetchone()
        conn.commit()
        return conn

    def init_database(self):
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        except OSError:
            pass
        try:
            self.conn = self._open_database()
        except sqlite3.DatabaseError as e:
            # BD corrupta: se aparta (no se borra) y se crea una nueva
            logger.error("[PasswordManager] Corrupt password database %s: %s", self.db_path, e)
            try:
                if self.conn is not None:
                    self.conn.close()
            except Exception:
                pass
            self.conn = None
            corrupt = self.db_path + ".corrupt"
            if os.path.exists(corrupt):
                corrupt = f"{self.db_path}.{datetime.now():%Y%m%d%H%M%S}.corrupt"
            try:
                os.replace(self.db_path, corrupt)
                self.conn = self._open_database()
                self._notify_user(
                    "Password database damaged",
                    "The password database was damaged and could not be read. "
                    f"It has been moved to {corrupt} and a new empty one was created.",
                    key="db_corrupt")
            except Exception as e2:
                logger.error("[PasswordManager] Could not recreate password database: %s", e2)
                self.conn = None
                self._notify_user(
                    "Password database unavailable",
                    f"The password database could not be opened ({e2}). "
                    "Saved passwords are unavailable in this session.",
                    key="db_unavailable")
        except Exception as e:
            logger.error("[PasswordManager] Error initializing database: %s", e)
            self.conn = None
            self._notify_user(
                "Password database unavailable",
                f"The password database could not be opened ({e}). "
                "Saved passwords are unavailable in this session.",
                key="db_unavailable")
        _restrict_permissions(self.db_path)

    def load_passwords(self):
        try:
            self.passwords_list.clear()
            if self.conn is None:
                return
            cursor = self.conn.cursor()
            cursor.execute("SELECT url, username, notes, password FROM passwords ORDER BY url")
            undecryptable = 0
            for url, username, notes, raw in cursor.fetchall():
                item = QListWidgetItem(f"{url} - {username}")
                tooltip = notes or ""
                if not self._is_decryptable(raw):
                    undecryptable += 1
                    item.setForeground(Qt.gray)
                    tooltip = f"{UNDECRYPTABLE_LABEL} {tooltip}".strip()
                if tooltip:
                    item.setToolTip(tooltip)
                self.passwords_list.addItem(item)
            if undecryptable:
                self._notify_user(
                    "Passwords cannot be decrypted",
                    f"{undecryptable} saved password(s) cannot be decrypted with the "
                    "current key (the key may have been lost or changed). They are "
                    f"marked {UNDECRYPTABLE_LABEL} and will not be autofilled.",
                    key="undecryptable")
            self.refresh_key_icon()
        except Exception as e:
            logger.error("[PasswordManager] Error loading passwords: %s", e)

    def filter_passwords(self):
        search = self.search_input.text().lower()
        for i in range(self.passwords_list.count()):
            item = self.passwords_list.item(i)
            item.setHidden(search not in item.text().lower())

    # -----------------------------------------------------------------
    # Encryption helpers
    # -----------------------------------------------------------------

    def setup_encryption(self):
        """Prepara self.fernet. Si falla, el guardado queda desactivado."""
        self.fernet = None
        try:
            key = self._load_or_create_key()
            self.fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as e:
            logger.error("[PasswordManager] Error setting up encryption: %s", e)
            self.fernet = None
            self._notify_user(
                "Password encryption unavailable",
                f"Password encryption could not be initialised ({e}). Saving "
                "passwords is disabled for this session.",
                key="encryption")

    def _settings_flag(self, name: str) -> bool:
        return str(self.settings.value(name, "false")).lower() in ("true", "1")

    def _load_or_create_key(self) -> str:
        """Obtiene la clave Fernet: llavero del sistema si existe, si no QSettings.

        - Si hay clave en QSettings y keyring funciona, se copia al llavero y
          solo se borra de QSettings tras comprobar que se lee igual.
        - Si la clave ya se migró al llavero (flag key_in_keyring) y ahora no
          se puede leer, NO se genera otra (se perderían las existentes): se
          lanza un error y el guardado queda desactivado.
        """
        qs_key = self.settings.value("encryption_key")
        qs_key = qs_key if isinstance(qs_key, str) and qs_key else None
        kr = _keyring_module()
        kr_key = None
        if kr is not None:
            try:
                kr_key = kr.get_password(_KEYRING_SERVICE, _KEYRING_ENTRY)
            except Exception as exc:
                logger.warning("[PasswordManager] keyring no disponible: %s", exc)
                kr = None

        if qs_key:
            if kr is None:
                logger.warning(
                    "[PasswordManager] keyring no disponible: la clave de cifrado "
                    "sigue en QSettings (en claro en el perfil del usuario)")
                return qs_key
            if kr_key and kr_key != qs_key:
                logger.warning(
                    "[PasswordManager] La clave del llavero no coincide con la de "
                    "QSettings; se usa la de QSettings y no se toca ninguna")
                return qs_key
            try:
                if not kr_key:
                    kr.set_password(_KEYRING_SERVICE, _KEYRING_ENTRY, qs_key)
                if kr.get_password(_KEYRING_SERVICE, _KEYRING_ENTRY) == qs_key:
                    self.settings.setValue("key_in_keyring", True)
                    self.settings.remove("encryption_key")
                    self.settings.sync()
                    logger.info("[PasswordManager] Clave de cifrado migrada al llavero del sistema")
            except Exception as exc:
                logger.warning(
                    "[PasswordManager] No se pudo migrar la clave al llavero: %s", exc)
            return qs_key

        if kr_key:
            return kr_key
        if self._settings_flag("key_in_keyring"):
            raise RuntimeError(
                "the encryption key is stored in the system keyring, which is not "
                "available right now")

        new_key = Fernet.generate_key().decode()
        if kr is not None:
            try:
                kr.set_password(_KEYRING_SERVICE, _KEYRING_ENTRY, new_key)
                if kr.get_password(_KEYRING_SERVICE, _KEYRING_ENTRY) == new_key:
                    self.settings.setValue("key_in_keyring", True)
                    self.settings.sync()
                    return new_key
            except Exception as exc:
                logger.warning("[PasswordManager] No se pudo guardar la clave en el llavero: %s", exc)
        logger.warning(
            "[PasswordManager] keyring no disponible: la clave de cifrado se guarda en QSettings")
        self.settings.setValue("encryption_key", new_key)
        self.settings.sync()
        return new_key

    def _require_fernet(self) -> bool:
        if self.fernet is not None:
            return True
        self._notify_user(
            "Password encryption unavailable",
            "Password encryption is not available, so passwords cannot be saved "
            "in this session.",
            key="encryption")
        return False

    @staticmethod
    def _is_legacy_plain(raw) -> bool:
        """Texto plano heredado: lo que no tiene forma de token Fernet."""
        return isinstance(raw, str) and not raw.startswith("gAAAA")

    def _is_decryptable(self, raw) -> bool:
        """Comprueba el HMAC del token sin sacar el texto en claro."""
        if self._is_legacy_plain(raw):
            return True
        if self.fernet is None or not isinstance(raw, str):
            return False
        try:
            self.fernet.extract_timestamp(raw.encode())
            return True
        except (InvalidToken, ValueError, TypeError):
            return False

    def _decrypt_password(self, raw):
        """Devuelve el texto en claro, o None si la entrada no se puede descifrar.

        - Entrada que no parece un token Fernet (no empieza por gAAAA): texto
          plano heredado de versiones antiguas, se devuelve tal cual.
        - Token Fernet que no se descifra (InvalidToken, clave perdida o
          distinta): None. Nunca se devuelve el texto cifrado como contraseña.
        """
        if raw is None:
            return None
        if self._is_legacy_plain(raw):
            return raw
        if self.fernet is None:
            return None
        try:
            return self.fernet.decrypt(raw.encode()).decode()
        except (InvalidToken, ValueError, TypeError, UnicodeDecodeError):
            return None

    # -----------------------------------------------------------------
    # CRUD — manual UI dialogs
    # -----------------------------------------------------------------

    def add_password(self):
        try:
            if not self._require_fernet() or self.conn is None:
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("Add Password")
            layout = QVBoxLayout(dialog)

            url_input      = QLineEdit()
            username_input = QLineEdit()
            password_input = QLineEdit()
            password_input.setEchoMode(QLineEdit.Password)
            notes_input    = QLineEdit()

            show_btn = QPushButton()

            show_btn.setToolTip("Mostrar u ocultar")

            try:

                from ui.core.strip_icons import build_nav_icon

                from PySide6.QtCore import QSize

                show_btn.setIcon(build_nav_icon("eye", None, QSize(16, 16)))

            except Exception:

                pass
            show_btn.setFixedSize(32, 32)
            show_btn.setCheckable(True)
            show_btn.toggled.connect(
                lambda c: password_input.setEchoMode(
                    QLineEdit.Normal if c else QLineEdit.Password))

            pw_layout = QHBoxLayout()
            pw_layout.addWidget(password_input)
            pw_layout.addWidget(show_btn)

            for label, widget in [("URL:", url_input), ("Username:", username_input),
                                   ("Notes:", notes_input)]:
                layout.addWidget(QLabel(label))
                layout.addWidget(widget)
                if label == "Username:":
                    layout.addWidget(QLabel("Password:"))
                    layout.addLayout(pw_layout)

            btn_layout = QHBoxLayout()
            save_btn   = QPushButton("Save");   save_btn.clicked.connect(dialog.accept)
            cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(save_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)

            if dialog.exec():
                encrypted = self.fernet.encrypt(password_input.text().encode()).decode()
                cur = self.conn.cursor()
                cur.execute(
                    "INSERT INTO passwords (url, username, password, notes) VALUES (?,?,?,?)",
                    (url_input.text(), username_input.text(), encrypted, notes_input.text()))
                self.conn.commit()
                self.load_passwords()
                self.password_saved.emit(url_input.text(), username_input.text())
        except Exception as e:
            logger.error("[PasswordManager] Error adding password: %s", e)

    def edit_password(self):
        try:
            item = self.passwords_list.currentItem()
            if not item:
                return
            url, username = item.text().split(" - ", 1)

            cur = self.conn.cursor()
            cur.execute(
                "SELECT password, notes FROM passwords WHERE url=? AND username=?",
                (url, username))
            row = cur.fetchone()
            if not row:
                return

            if not self._require_fernet():
                return
            current_plain = self._decrypt_password(row[0])
            undecryptable = current_plain is None

            dialog = QDialog(self)
            dialog.setWindowTitle("Edit Password")
            layout = QVBoxLayout(dialog)

            url_input      = QLineEdit(url)
            username_input = QLineEdit(username)
            password_input = QLineEdit("" if undecryptable else current_plain)
            password_input.setEchoMode(QLineEdit.Password)
            if undecryptable:
                password_input.setPlaceholderText(
                    f"{UNDECRYPTABLE_LABEL} - type a new password to replace it")
            notes_input    = QLineEdit(row[1] or "")

            show_btn = QPushButton()

            show_btn.setToolTip("Mostrar u ocultar")

            try:

                from ui.core.strip_icons import build_nav_icon

                from PySide6.QtCore import QSize

                show_btn.setIcon(build_nav_icon("eye", None, QSize(16, 16)))

            except Exception:

                pass
            show_btn.setFixedSize(32, 32)
            show_btn.setCheckable(True)
            show_btn.toggled.connect(
                lambda c: password_input.setEchoMode(
                    QLineEdit.Normal if c else QLineEdit.Password))

            pw_layout = QHBoxLayout()
            pw_layout.addWidget(password_input)
            pw_layout.addWidget(show_btn)

            for label, widget in [("URL:", url_input), ("Username:", username_input),
                                   ("Notes:", notes_input)]:
                layout.addWidget(QLabel(label))
                layout.addWidget(widget)
                if label == "Username:":
                    layout.addWidget(QLabel("Password:"))
                    layout.addLayout(pw_layout)

            btn_layout = QHBoxLayout()
            save_btn   = QPushButton("Save");   save_btn.clicked.connect(dialog.accept)
            cancel_btn = QPushButton("Cancel"); cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(save_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)

            if dialog.exec():
                if undecryptable and not password_input.text():
                    # Sin contraseña nueva: se conserva el valor guardado tal cual
                    encrypted = row[0]
                else:
                    encrypted = self.fernet.encrypt(password_input.text().encode()).decode()
                cur.execute(
                    "UPDATE passwords SET url=?, username=?, password=?, notes=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE url=? AND username=?",
                    (url_input.text(), username_input.text(), encrypted,
                     notes_input.text(), url, username))
                self.conn.commit()
                self.load_passwords()
                self.password_updated.emit(url_input.text(), username_input.text())
        except Exception as e:
            logger.error("[PasswordManager] Error editing password: %s", e)

    def view_password_details(self, item):
        try:
            if item is None or self.conn is None:
                return
            url, username = item.text().split(" - ", 1)

            cur = self.conn.cursor()
            cur.execute(
                "SELECT password, notes FROM passwords WHERE url=? AND username=?",
                (url, username))
            row = cur.fetchone()
            if not row:
                return

            plain = self._decrypt_password(row[0])
            undecryptable = plain is None

            dialog = QDialog(self)
            dialog.setWindowTitle("Password Details")
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(f"<b>URL:</b> {url}"))
            layout.addWidget(QLabel(f"<b>Username:</b> {username}"))

            pw_input = QLineEdit(UNDECRYPTABLE_LABEL if undecryptable else plain)
            pw_input.setEchoMode(QLineEdit.Normal if undecryptable else QLineEdit.Password)
            pw_input.setReadOnly(True)

            show_btn = QPushButton()

            show_btn.setToolTip("Mostrar u ocultar")

            try:

                from ui.core.strip_icons import build_nav_icon

                from PySide6.QtCore import QSize

                show_btn.setIcon(build_nav_icon("eye", None, QSize(16, 16)))

            except Exception:

                pass
            show_btn.setFixedSize(32, 32)
            show_btn.setCheckable(True)
            show_btn.toggled.connect(
                lambda c: pw_input.setEchoMode(
                    QLineEdit.Normal if c else QLineEdit.Password))

            copy_btn = QPushButton()
            try:
                from ui.core.strip_icons import build_nav_icon
                from PySide6.QtCore import QSize
                copy_btn.setIcon(build_nav_icon("clipboard", None, QSize(16, 16)))
            except Exception:
                pass
            copy_btn.setFixedSize(32, 32)
            copy_btn.setToolTip("Copy password to clipboard")
            copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(plain))
            if undecryptable:
                show_btn.setEnabled(False)
                copy_btn.setEnabled(False)

            pw_layout = QHBoxLayout()
            pw_layout.addWidget(pw_input)
            pw_layout.addWidget(show_btn)
            pw_layout.addWidget(copy_btn)

            layout.addWidget(QLabel("<b>Password:</b>"))
            layout.addLayout(pw_layout)
            if row[1]:
                layout.addWidget(QLabel(f"<b>Notes:</b> {row[1]}"))

            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            dialog.exec()
        except Exception as e:
            logger.error("[PasswordManager] Error viewing password details: %s", e)

    def remove_password(self):
        try:
            item = self.passwords_list.currentItem()
            if not item:
                return
            url, username = item.text().split(" - ", 1)
            reply = QMessageBox.question(
                self, "Confirm removal",
                f"Are you sure you want to remove the password for {url}?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                cur = self.conn.cursor()
                cur.execute(
                    "DELETE FROM passwords WHERE url=? AND username=?",
                    (url, username))
                self.conn.commit()
                self.load_passwords()
                self.password_deleted.emit(url)
        except Exception as e:
            logger.error("[PasswordManager] Error removing password: %s", e)

    # -----------------------------------------------------------------
    # Password generator dialog
    # -----------------------------------------------------------------

    def show_generator(self):
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Password Generator")
            layout = QVBoxLayout(dialog)

            opts = QGroupBox("Options")
            opts_layout = QVBoxLayout()
            length_input = QLineEdit("16")
            length_input.setValidator(QIntValidator(8, 10_000_000))
            row = QHBoxLayout()
            row.addWidget(QLabel("Length:"))
            row.addWidget(length_input)
            opts_layout.addLayout(row)
            checks = {}
            for name in ("Include numbers", "Include uppercase",
                         "Include lowercase", "Include special characters"):
                cb = QCheckBox(name)
                cb.setChecked(True)
                checks[name] = cb
                opts_layout.addWidget(cb)
            opts.setLayout(opts_layout)
            layout.addWidget(opts)

            result_group = QGroupBox("Result")
            result_layout = QVBoxLayout()
            pw_out    = QLineEdit(); pw_out.setReadOnly(True)
            stats_lbl = QLabel()
            result_layout.addWidget(pw_out)
            result_layout.addWidget(stats_lbl)
            result_group.setLayout(result_layout)
            layout.addWidget(result_group)

            def generate():
                try:
                    length = int(length_input.text())
                    result = self.password_generator.generate_password(
                        length=length,
                        include_numbers=checks["Include numbers"].isChecked(),
                        include_uppercase=checks["Include uppercase"].isChecked(),
                        include_lowercase=checks["Include lowercase"].isChecked(),
                        include_special=checks["Include special characters"].isChecked(),
                    )
                    pw_out.setText(result["password"])
                    stats_lbl.setText(
                        f"Time: {result['time']}  CPU: {result['cpu_usage']}  "
                        f"RAM: {result['ram_usage']}")
                except Exception as exc:
                    QMessageBox.critical(dialog, "Error", str(exc))

            btn_row = QHBoxLayout()
            for label, slot in [
                ("Generate", generate),
                ("Copy",     lambda: QApplication.clipboard().setText(pw_out.text())),
                ("Close",    dialog.accept),
            ]:
                b = QPushButton(label); b.clicked.connect(slot); btn_row.addWidget(b)
            layout.addLayout(btn_row)
            generate()
            dialog.exec()
        except Exception as e:
            logger.error("[PasswordManager] Error showing generator: %s", e)

    # -----------------------------------------------------------------
    # Encrypted CRUD — used by browser integration
    # -----------------------------------------------------------------

    def save_password(self, url: str, username: str, password: str) -> bool:
        try:
            if not self._require_fernet():
                return False
            enc = self.fernet.encrypt(password.encode()).decode()
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO passwords (url, username, password) VALUES (?,?,?)",
                (url, username, enc))
            conn.commit()
            conn.close()
            logger.info("[PasswordManager] Credential saved: %s", url)
            self.load_passwords()
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error saving password: %s", e)
            self._notify_user("Password not saved",
                              f"The password for {url} could not be saved ({e}).",
                              key="save_error")
            return False

    def update_password(self, origin: str, username: str, new_password: str) -> bool:
        try:
            if not self._require_fernet():
                return False
            enc = self.fernet.encrypt(new_password.encode()).decode()
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE passwords SET password=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE url=? AND username=?",
                (enc, origin, username))
            conn.commit()
            conn.close()
            logger.info("[PasswordManager] Credential updated: %s", origin)
            self.load_passwords()
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error updating password: %s", e)
            self._notify_user("Password not updated",
                              f"The password for {origin} could not be updated ({e}).",
                              key="save_error")
            return False

    def _get_raw_password(self, url: str, username: str):
        """Valor almacenado (cifrado) o None si no existe la entrada."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT password FROM passwords WHERE url=? AND username=? "
                "ORDER BY updated_at DESC, id DESC LIMIT 1",
                (url, username)).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def get_password(self, url: str, username: str):
        """Contraseña en claro, o None si no existe o no se puede descifrar."""
        try:
            raw = self._get_raw_password(url, username)
            return self._decrypt_password(raw) if raw is not None else None
        except Exception as e:
            logger.error("[PasswordManager] Error getting password: %s", e)
            return None

    def get_all_passwords(self) -> list:
        """Lista de entradas; las no descifrables llevan password=None y undecryptable=True."""
        try:
            conn = sqlite3.connect(self.db_path)
            cur  = conn.cursor()
            cur.execute("SELECT url, username, password FROM passwords")
            rows = cur.fetchall()
            conn.close()
            result = []
            for url, username, raw in rows:
                plain = self._decrypt_password(raw)
                result.append({"url": url, "username": username,
                               "password": plain,
                               "undecryptable": plain is None})
            return result
        except Exception as e:
            logger.error("[PasswordManager] Error getting all passwords: %s", e)
            return []

    def get_credentials_for_origin(self, origin: str) -> list:
        """Credenciales descifrables del origen, de la más reciente a la más antigua.

        Las entradas no descifrables se excluyen (nunca se autorrellenan).
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cur  = conn.cursor()
            cur.execute(
                "SELECT username, password FROM passwords WHERE url=? "
                "ORDER BY updated_at DESC, id DESC", (origin,))
            rows = cur.fetchall()
            conn.close()
            creds = []
            for username, raw in rows:
                plain = self._decrypt_password(raw)
                if plain is None:
                    continue
                creds.append({"username": username, "password": plain})
            return creds
        except Exception as e:
            logger.error("[PasswordManager] Error getting credentials for origin: %s", e)
            return []

    def has_credentials_for_origin(self, origin: str) -> bool:
        """True si hay al menos una credencial descifrable (sin sacar texto en claro)."""
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT password FROM passwords WHERE url=?", (origin,)).fetchall()
            conn.close()
            return any(self._is_decryptable(r[0]) for r in rows)
        except Exception as e:
            logger.error("[PasswordManager] Error checking credentials for origin: %s", e)
            return False

    def delete_password(self, url: str, username: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM passwords WHERE url=? AND username=?", (url, username))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error deleting password: %s", e)
            return False

    def clear_all_passwords(self) -> bool:
        """Delete every stored credential. Called from 'Clear browsing data'.

        Borra de la BD real (self.db_path), también la lista de sitios "Never
        for this site", y hace VACUUM para que las filas borradas no queden en
        páginas libres del archivo.
        """
        try:
            if self.conn is not None:
                self.conn.execute("DELETE FROM passwords")
                self.conn.execute(self._CREATE_NEVER_SQL)
                self.conn.execute("DELETE FROM never_save")
                self.conn.commit()
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("DELETE FROM passwords")
                conn.execute(self._CREATE_NEVER_SQL)
                conn.execute("DELETE FROM never_save")
                conn.commit()
                conn.execute("VACUUM")
            finally:
                conn.close()
            self.load_passwords()
            logger.info("[PasswordManager] All saved passwords cleared")
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error clearing all passwords: %s", e)
            return False

    # -----------------------------------------------------------------
    # "Never for this site"
    # -----------------------------------------------------------------

    def is_never_save(self, origin: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT 1 FROM never_save WHERE origin=?", (origin,)).fetchone()
            finally:
                conn.close()
            return row is not None
        except Exception as e:
            logger.error("[PasswordManager] Error checking never-save list: %s", e)
            return False

    def add_never_save(self, origin: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(self._CREATE_NEVER_SQL)
                conn.execute("INSERT OR IGNORE INTO never_save (origin) VALUES (?)", (origin,))
                conn.commit()
            finally:
                conn.close()
            logger.info("[PasswordManager] Never save passwords for %s", origin)
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error adding never-save origin: %s", e)
            return False

    def remove_never_save(self, origin: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("DELETE FROM never_save WHERE origin=?", (origin,))
                conn.commit()
            finally:
                conn.close()
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error removing never-save origin: %s", e)
            return False

    def get_never_save_origins(self) -> list:
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                rows = conn.execute("SELECT origin FROM never_save ORDER BY origin").fetchall()
            finally:
                conn.close()
            return [r[0] for r in rows]
        except Exception as e:
            logger.error("[PasswordManager] Error reading never-save list: %s", e)
            return []

    def show_never_save_sites(self):
        """Diálogo con los sitios en los que nunca se ofrece guardar."""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Never save passwords for")
            dialog.setMinimumSize(420, 300)
            layout = QVBoxLayout(dialog)
            sites = QListWidget()
            sites.addItems(self.get_never_save_origins())
            layout.addWidget(sites)
            empty = QLabel("No sites. They are added with \"Never for this site\" "
                           "when Katphi offers to save a password.")
            empty.setWordWrap(True)
            empty.setVisible(sites.count() == 0)
            layout.addWidget(empty)

            def remove_selected():
                item = sites.currentItem()
                if item is None:
                    return
                if self.remove_never_save(item.text()):
                    sites.takeItem(sites.row(item))
                    empty.setVisible(sites.count() == 0)

            btn_row = QHBoxLayout()
            remove_btn = QPushButton("Remove"); remove_btn.clicked.connect(remove_selected)
            close_btn  = QPushButton("Close");  close_btn.clicked.connect(dialog.accept)
            btn_row.addWidget(remove_btn)
            btn_row.addWidget(close_btn)
            layout.addLayout(btn_row)
            dialog.exec()
        except Exception as e:
            logger.error("[PasswordManager] Error showing never-save sites: %s", e)

    # -----------------------------------------------------------------
    # Credential comparison
    # -----------------------------------------------------------------

    def compare_credentials(self, origin: str, username: str, password: str):
        raw = self._get_raw_password(origin, username)
        if raw is None:
            return ("new", None)
        stored = self._decrypt_password(raw)
        if stored is None:
            # Entrada no descifrable: se ofrece sustituirla
            return ("update", None)
        if stored == password:
            return ("same", stored)
        return ("update", stored)

    # -----------------------------------------------------------------
    # Banner logic
    # -----------------------------------------------------------------

    def _on_credentials_captured(self, origin: str, username: str, password: str,
                                 browser=None, old_password: str = "",
                                 kind: str = "login", doc: str = ""):
        """Credencial enviada por un formulario.

        Sin browser (entrada heredada) se ofrece guardar en el acto. Con
        browser la captura queda pendiente hasta saber si el login ha
        funcionado (_confirm_pending / _on_page_ready).
        """
        try:
            if _is_private_mode():
                return  # ventana privada: no se guardan credenciales
            if not password:
                return
            if self.fernet is None:
                self._require_fernet()
                return
            if origin in self._dismissed_origins:
                logger.debug("[PasswordManager] Origin dismissed, skipping: %s", origin)
                return
            if self.is_never_save(origin):
                logger.debug("[PasswordManager] Never-save origin, skipping: %s", origin)
                return
            if browser is not None:
                # Un envío nuevo sustituye al que estuviera pendiente
                self._pending.pop(id(browser), None)
                username = self._resolve_username(browser, origin, username,
                                                  old_password, kind)
            if not username:
                logger.debug("[PasswordManager] No username for %s (%s), skipping", origin, kind)
                return
            action, _ = self.compare_credentials(origin, username, password)
            logger.info("[PasswordManager] Action=%s for %s (%s)", action, origin, kind)
            if action == "same":
                return
            if browser is None:
                self._show_save_banner(origin, username, password,
                                       is_update=(action == "update"))
                return
            self._pending[id(browser)] = {
                "origin": origin, "username": username, "password": password,
                "is_update": action == "update", "t": time.monotonic(), "doc": doc}
        except Exception as e:
            logger.error("[PasswordManager] Error handling captured credentials: %s", e)

    def _resolve_username(self, browser, origin: str, username: str,
                          old_password: str, kind: str) -> str:
        """Usuario de una captura que no lo trae (multipaso o cambio de contraseña)."""
        if username:
            return username
        if kind == "change":
            creds = self.get_credentials_for_origin(origin)
            if old_password:
                for c in creds:
                    if c["password"] == old_password:
                        return c["username"]
            return creds[0]["username"] if len(creds) == 1 else ""
        step = self._step_username(browser, origin)
        if step:
            return step
        if kind == "login":
            creds = self.get_credentials_for_origin(origin)
            if len(creds) == 1:
                return creds[0]["username"]
        return ""

    def _remember_step_username(self, browser, origin: str, username: str):
        if username and len(username) <= _MAX_USERNAME_LEN:
            self._step_usernames[id(browser)] = (origin, username, time.monotonic())

    def _step_username(self, browser, origin: str) -> str:
        """Usuario del paso 1 de un login multipaso en esta pestaña, si es reciente."""
        step = self._step_usernames.get(id(browser))
        if step and step[0] == origin and time.monotonic() - step[2] <= _STEP_USERNAME_TTL:
            return step[1]
        return ""

    def _confirm_pending(self, browser):
        """El login ha funcionado: ofrecer guardar la captura pendiente."""
        pend = self._pending.pop(id(browser), None)
        if not pend or time.monotonic() - pend["t"] > _PENDING_TTL:
            return
        self._show_save_banner(pend["origin"], pend["username"], pend["password"],
                               is_update=pend["is_update"], browser=browser)

    def _on_page_ready(self, browser, origin: str, doc: str, login_form: bool):
        """Documento nuevo tras un envío: si vuelve a pedir el login, falló."""
        bid = id(browser)
        pend = self._pending.get(bid)
        if not pend or not doc or doc == pend.get("doc"):
            return   # sin captura pendiente, o es la misma página del envío
        if time.monotonic() - pend["t"] > _PENDING_TTL:
            self._pending.pop(bid, None)
            return
        if login_form:
            logger.info("[PasswordManager] Login form shown again on %s: "
                        "login failed, credential discarded", origin)
            self._pending.pop(bid, None)
        else:
            self._confirm_pending(browser)

    def _show_save_banner(self, origin: str, username: str, password: str,
                          is_update: bool, browser=None):
        try:
            if self._active_banner is not None:
                try:
                    self._active_banner.deleteLater()
                except RuntimeError:
                    pass
                self._active_banner = None

            main_win = self._find_main_window()
            if main_win is None:
                self._store_credential(origin, username, password, is_update)
                logger.warning(
                    "[PasswordManager] Main window not found; credential for %s "
                    "saved silently (no banner)", origin)
                return

            logger.info(
                "[PasswordManager] Showing %s banner for %s",
                "update" if is_update else "save", origin)

            banner = PasswordSaveBanner(origin, username, password,
                                        is_update=is_update, parent=None,
                                        insecure=_is_insecure_origin(origin))
            self._active_banner = banner
            bid = id(browser) if browser is not None else None

            def keep_unsaved():
                # La llave de la barra de URL lo vuelve a ofrecer en esta pestaña
                if bid is not None:
                    self._unsaved[bid] = {
                        "origin": origin, "username": username, "password": password,
                        "is_update": is_update, "t": time.monotonic()}
                    self.refresh_key_icon()

            def on_accepted():
                if bid is not None:
                    self._unsaved.pop(bid, None)
                self._store_credential(origin, username, password, is_update)
                self._active_banner = None

            def on_dismissed():
                logger.info("[PasswordManager] Banner dismissed for %s", origin)
                self._dismissed_origins.add(origin)
                self._active_banner = None
                keep_unsaved()

            def on_never():
                if bid is not None:
                    self._unsaved.pop(bid, None)
                self.add_never_save(origin)
                self._active_banner = None

            def on_timed_out():
                self._active_banner = None
                keep_unsaved()

            banner.accepted.connect(on_accepted)
            banner.dismissed.connect(on_dismissed)
            banner.never.connect(on_never)
            banner.timed_out.connect(on_timed_out)
            self._insert_banner_in_layout(main_win, banner)
        except Exception as e:
            logger.error("[PasswordManager] Error showing save banner: %s", e)

    def _store_credential(self, origin: str, username: str, password: str,
                          is_update: bool):
        if is_update:
            self.update_password(origin, username, password)
            self.password_updated.emit(origin, username)
        else:
            self.save_password(origin, username, password)
            self.password_saved.emit(origin, username)

    def _find_main_window(self):
        widget = self.parent
        while widget is not None:
            if hasattr(widget, 'centralWidget'):
                return widget
            widget = getattr(widget, 'parent', None)
            if callable(widget):
                widget = widget()
        return None

    def _insert_banner_in_layout(self, main_win, banner):
        try:
            central = main_win.centralWidget()
            if central is None:
                banner.setParent(main_win); banner.show(); return
            layout = central.layout()
            if layout is None:
                banner.setParent(main_win); banner.show(); return
            layout.insertWidget(1, banner)
            banner.show()
        except Exception as e:
            logger.error("[PasswordManager] Error inserting banner: %s", e)
            banner.setParent(main_win)
            banner.show()

    # -----------------------------------------------------------------
    # Legacy entry point
    # -----------------------------------------------------------------

    def show_password_dialog(self, url: str, username: str, password: str):
        self._on_credentials_captured(_normalize_origin(url), username, password)

    def show_passwords_dialog(self):
        try:
            dialog = QDialog(self.parent)
            dialog.setWindowTitle("Saved Passwords")
            dialog.setMinimumSize(600, 400)
            layout = QVBoxLayout()

            table = QTableWidget()
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels(["URL", "Username", "Password"])
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            passwords = self.get_all_passwords()
            table.setRowCount(len(passwords))
            for i, pwd in enumerate(passwords):
                table.setItem(i, 0, QTableWidgetItem(pwd['url']))
                table.setItem(i, 1, QTableWidgetItem(pwd['username']))
                table.setItem(i, 2, QTableWidgetItem(
                    UNDECRYPTABLE_LABEL if pwd.get('undecryptable') else "••••••••"))
            layout.addWidget(table)

            btns = QDialogButtonBox(QDialogButtonBox.Close)
            btns.rejected.connect(dialog.reject)
            layout.addWidget(btns)
            dialog.setLayout(layout)
            dialog.exec()
        except Exception as e:
            logger.error("[PasswordManager] Error showing passwords dialog: %s", e)

    # -----------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------

    def closeEvent(self, event):
        try:
            if getattr(self, 'conn', None) is not None:
                self.conn.close()
        except Exception as e:
            logger.error("[PasswordManager] Error closing DB connection: %s", e)
        finally:
            super().closeEvent(event)

    def cleanup_browser(self, browser):
        try:
            browser_id = id(browser)
            self._pending.pop(browser_id, None)
            self._step_usernames.pop(browser_id, None)
            self._unsaved.pop(browser_id, None)
            if browser_id in self._browser_connections:
                entry = self._browser_connections.pop(browser_id)
                for signal, slot in entry.get("signals", []):
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
                script = entry.pop("script", None)
                if script is not None:
                    try:
                        browser.page().scripts().remove(script)
                    except (RuntimeError, AttributeError):
                        pass
                # Drop Python references so QObjects can be cleaned up
                entry.pop("receiver", None)
                entry.pop("channel",  None)
                logger.debug("[PasswordManager] Cleaned up browser %s", browser_id)
        except Exception as e:
            logger.error("[PasswordManager] Error cleaning up browser: %s", e)

    # -----------------------------------------------------------------
    # Browser integration — QWebChannel approach
    #
    # Architecture:
    #   1. CredentialReceiver (QObject) exposed to JS as "credReceiver"
    #   2. QWebChannel set on the page in the ApplicationWorld → injects
    #      qt.webChannelTransport only in that isolated world
    #   3. qwebchannel.js + _CAPTURE_JS as a QWebEngineScript (DocumentReady,
    #      ApplicationWorld, all frames; same-origin iframes relay through the
    #      main frame). hello() tells it whether there are creds and whether it
    #      may fill without a gesture (one account, https)
    #   4. JS calls window.__katphi.onCredential(json) → Python slot fires
    #      (origin computed in Python from browser.url()) → pending until the
    #      login succeeds (onLoginOutcome, or onPageReady of the next document)
    #   5. Trusted click/Tab on a login field → requestAutofill → Python
    #      injects ONE credential via window.__katphiFill() (isolated world),
    #      or shows a menu to choose when there are several accounts
    # -----------------------------------------------------------------

    @staticmethod
    def _load_qwebchannel_js() -> str:
        """Read qwebchannel.js from Qt resources (bundled with PySide6)."""
        f = QFile(":/qtwebchannel/qwebchannel.js")
        if f.open(QIODevice.OpenModeFlag.ReadOnly):
            content = bytes(f.readAll()).decode("utf-8")
            f.close()
            logger.debug(
                "[PasswordManager] qwebchannel.js loaded from Qt resources (%d bytes)",
                len(content))
            return content
        logger.error(
            "[PasswordManager] Could not load qwebchannel.js from Qt resources — "
            "credential capture will NOT work. Check PySide6.QtWebChannel is installed.")
        return ""

    def _make_script(self):
        """QWebEngineScript con qwebchannel.js + captura, en todos los frames."""
        from PySide6.QtWebEngineCore import QWebEngineScript
        script = QWebEngineScript()
        script.setName(self._script_name)
        script.setSourceCode((PasswordManager._qwebchannel_js or "") + "\n" + _CAPTURE_JS)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(_APP_WORLD)
        script.setRunsOnSubFrames(True)
        return script

    def setup_browser(self, browser):
        """Install QWebChannel and credential capture script for this browser tab."""
        try:
            if _is_private_mode():
                logger.debug("[PasswordManager] Private mode: credential capture disabled")
                return
            if not browser or not hasattr(browser, 'page'):
                logger.warning("[PasswordManager] setup_browser: invalid browser object")
                return
            browser_id = id(browser)
            if browser_id in self._browser_connections:
                return  # already configured

            # Load qwebchannel.js once (class-level cache).
            # QtWebChannel resources are only registered after QWebChannel is
            # imported, which happens at module level — so this is safe here.
            if not PasswordManager._qwebchannel_js:
                PasswordManager._qwebchannel_js = self._load_qwebchannel_js()
            if not PasswordManager._qwebchannel_js:
                logger.warning(
                    "[PasswordManager] qwebchannel.js empty — capture-only mode "
                    "(no WebChannel)")

            # Create receiver + channel, register on current page.
            # IMPORTANT: keep strong Python references to both objects in
            # _browser_connections — PySide6 may GC the wrappers even when Qt
            # parent-child ownership is set, which silently breaks the @Slot.
            # El origen lo calcula el receiver con la URL real de este browser.
            receiver = CredentialReceiver(
                browser, origin_getter=lambda b=browser: b.url().toString(),
                flags_getter=self._page_flags)
            page = browser.page()
            channel  = QWebChannel(page)
            channel.registerObject("credReceiver", receiver)
            # Mundo aislado: el JS de la página no ve qt.webChannelTransport
            page.setWebChannel(channel, _APP_WORLD)

            # Se inyecta en cada documento (y sus iframes) al estar listo el
            # DOM, sin depender de loadFinished
            script = self._make_script()
            for old in page.scripts().find(self._script_name):
                page.scripts().remove(old)
            page.scripts().insert(script)
            if browser.url().scheme() in ("http", "https"):
                # Documento ya cargado antes de configurar la pestaña
                page.runJavaScript(script.sourceCode(), _APP_WORLD)
            logger.info(
                "[PasswordManager] WebChannel configured (browser %s)", browser_id)

            signals = []

            def on_cred(origin, info, b=browser):
                self._on_credentials_captured(
                    origin, info.get("username", ""), info.get("password", ""),
                    browser=b, old_password=info.get("old_password", ""),
                    kind=info.get("kind", "login"), doc=info.get("doc", ""))

            receiver.credential_received.connect(on_cred)
            signals.append((receiver.credential_received, on_cred))

            def on_username(origin, username, b=browser):
                self._remember_step_username(b, origin, username)

            receiver.username_captured.connect(on_username)
            signals.append((receiver.username_captured, on_username))

            def on_outcome(origin, result, b=browser):
                pend = self._pending.get(id(b))
                if result == "success" and pend and pend["origin"] == origin:
                    self._confirm_pending(b)

            receiver.login_outcome.connect(on_outcome)
            signals.append((receiver.login_outcome, on_outcome))

            def on_page_ready(origin, doc, login_form, b=browser):
                self._on_page_ready(b, origin, doc, login_form)

            receiver.page_ready.connect(on_page_ready)
            signals.append((receiver.page_ready, on_page_ready))

            def on_fill_request(origin, info, b=browser):
                self._fill_on_request(b, origin, info)

            receiver.autofill_requested.connect(on_fill_request)
            signals.append((receiver.autofill_requested, on_fill_request))

            def on_url_changed(url, b=browser):
                self._on_url_changed(b, url.toString())

            browser.urlChanged.connect(on_url_changed)
            signals.append((browser.urlChanged, on_url_changed))

            # Store receiver + channel alongside signal pairs so their Python
            # wrappers cannot be garbage-collected while the tab is open.
            self._browser_connections[browser_id] = {
                "signals":  signals,
                "receiver": receiver,
                "channel":  channel,
                "script":   script,
            }
        except Exception as e:
            logger.error("[PasswordManager] Error setting up browser: %s", e)

    def _page_credentials(self, origin: str) -> list:
        """Credenciales para la página: las del origen o, en https sin ninguna,
        las guardadas para la versión http del mismo sitio (como Chrome)."""
        creds = self.get_credentials_for_origin(origin)
        if not creds and origin.startswith("https://"):
            creds = self.get_credentials_for_origin("http://" + origin[len("https://"):])
        return creds

    def _page_flags(self, origin: str) -> dict:
        """Para hello(): ¿hay credenciales? ¿se puede rellenar sin gesto?"""
        if _is_private_mode():
            return {"has": False, "auto": False}
        creds = self._page_credentials(origin)
        return {"has": bool(creds), "auto": self._auto_fill_allowed(origin, creds)}

    @staticmethod
    def _auto_fill_allowed(origin: str, creds: list) -> bool:
        """Relleno sin gesto: una sola cuenta, https y fuera del modo privado."""
        return len(creds) == 1 and origin.startswith("https://") and not _is_private_mode()

    @staticmethod
    def _candidates(creds: list, mode: str, typed: str, known: str = "") -> list:
        """Cuentas que se pueden ofrecer para el campo pulsado.

        - password (paso 2 o solo contraseña): la del usuario conocido, o todas.
        - full/username: la del usuario ya escrito; si es parcial, las que
          empiezan por él; si no hay nada escrito, todas. En modo username con
          el usuario ya completo no hay nada que rellenar.
        """
        if mode == "password":
            if known:
                return [c for c in creds if c["username"] == known]
            return list(creds)
        if typed:
            exact = [c for c in creds if c["username"] == typed]
            if exact:
                return [] if mode == "username" else exact
            low = typed.lower()
            return [c for c in creds if c["username"].lower().startswith(low)]
        return list(creds)

    def _fill_on_request(self, browser, origin: str, info: dict):
        """Petición de relleno: inyecta una credencial o muestra el selector."""
        try:
            if _is_private_mode() or not origin:
                return
            # La página pudo navegar entre la petición y la respuesta
            if _normalize_origin(browser.url().toString()) != origin:
                return
            creds = self._page_credentials(origin)
            if not creds:
                return
            mode = info.get("mode", "full")
            typed = info.get("username") or ""
            if info.get("auto"):
                if not self._auto_fill_allowed(origin, creds):
                    return
                if typed and typed != creds[0]["username"]:
                    return
                self._inject_fill(browser, origin, creds[0], mode)
                return
            known = ""
            if mode == "password":
                known = info.get("hidden_user") or self._step_username(browser, origin)
            cands = self._candidates(creds, mode, typed, known)
            # En http la contraseña viaja en claro: siempre se pregunta, con aviso
            if len(cands) == 1 and not _is_insecure_origin(origin):
                self._inject_fill(browser, origin, cands[0], mode)
            elif cands:
                self._show_account_menu(browser, origin, cands, mode, info.get("rect"))
        except Exception as e:
            logger.error("[PasswordManager] Error filling credential: %s", e)

    def _inject_fill(self, browser, origin: str, cred: dict, mode: str,
                     own_frame: bool = False):
        """Envía UNA credencial al mundo aislado (sin contraseña en modo username).

        own_frame: rellenar el frame principal aunque la última petición
        viniera de un iframe (relleno desde la llave de la barra de URL).
        """
        # Host en punycode, como lo ve location.hostname en JS
        js_origin = _normalize_origin(bytes(browser.url().toEncoded()).decode("ascii", "replace"))
        payload = {"username": cred["username"],
                   "password": "" if mode == "username" else cred["password"]}
        js = ("window.__katphiFill && window.__katphiFill("
              + json.dumps(payload) + ", " + json.dumps(js_origin)
              + (", true" if own_frame else "") + ");")
        browser.page().runJavaScript(js, _APP_WORLD)
        if mode == "username":
            # Para rellenar la contraseña en el paso 2 del login
            self._remember_step_username(browser, origin, cred["username"])
        logger.info("[PasswordManager] Autofill (%s) for %s", mode, origin)

    def _show_account_menu(self, browser, origin: str, cands: list, mode: str, rect):
        """Menú bajo el campo para elegir cuenta (sin contraseñas en memoria)."""
        if self._account_menu is not None:
            try:
                self._account_menu.close()
            except RuntimeError:
                pass
        menu = QMenu(browser)
        if _is_insecure_origin(origin):
            warn = menu.addAction("Not secure connection (http): the password can be intercepted")
            warn.setEnabled(False)
            menu.addSeparator()
        for c in cands:
            act = menu.addAction(c["username"].replace("&", "&&"))
            act.triggered.connect(
                lambda _=False, u=c["username"]: self._fill_selected(browser, origin, u, mode))
        menu.aboutToHide.connect(menu.deleteLater)
        try:
            zoom = float(browser.zoomFactor())
        except Exception:
            zoom = 1.0
        pos = QPoint(0, 0)
        if rect:
            pos = QPoint(int(rect[0] * zoom), int((rect[1] + rect[3]) * zoom))
        self._account_menu = menu
        menu.popup(browser.mapToGlobal(pos))

    def _fill_selected(self, browser, origin: str, username: str, mode: str):
        """Cuenta elegida en el menú: se vuelve a leer de la BD y se rellena."""
        try:
            self._account_menu = None
            if _is_private_mode() or _normalize_origin(browser.url().toString()) != origin:
                return
            for c in self._page_credentials(origin):
                if c["username"] == username:
                    self._inject_fill(browser, origin, c, mode)
                    return
        except Exception as e:
            logger.error("[PasswordManager] Error filling selected account: %s", e)

    # -----------------------------------------------------------------
    # Llave en la barra de URL
    # -----------------------------------------------------------------

    def attach_url_bar(self, url_bar, current_browser_getter):
        """Añade a la barra de URL la llave de contraseñas de la pestaña actual."""
        try:
            from PySide6.QtWidgets import QLineEdit
            self._url_bar = url_bar
            self._current_browser_getter = current_browser_getter
            icon = None
            try:
                from ui.core.strip_icons import build_nav_icon
                from PySide6.QtCore import QSize
                icon = build_nav_icon("key", None, QSize(16, 16))
            except Exception:
                pass
            if icon is None:
                from PySide6.QtGui import QIcon
                icon = QIcon()
            self._key_action = url_bar.addAction(icon, QLineEdit.TrailingPosition)
            self._key_action.setVisible(False)
            self._key_action.triggered.connect(self._show_key_menu)
            self.refresh_key_icon()
        except Exception as e:
            logger.error("[PasswordManager] Error attaching key icon: %s", e)

    def _current_browser(self):
        try:
            return self._current_browser_getter() if self._current_browser_getter else None
        except Exception:
            return None

    @staticmethod
    def _browser_origin(browser) -> str:
        try:
            url = browser.url().toString()
        except Exception:
            return ""
        if urlparse(url).scheme.lower() not in ("http", "https"):
            return ""
        return _normalize_origin(url)

    def _unsaved_for(self, browser, origin: str):
        entry = self._unsaved.get(id(browser))
        if not entry:
            return None
        if entry["origin"] != origin or time.monotonic() - entry["t"] > _PENDING_TTL * 5:
            self._unsaved.pop(id(browser), None)
            return None
        return entry

    def _on_url_changed(self, browser, url: str):
        # La credencial sin guardar solo se ofrece mientras se siga en su sitio
        entry = self._unsaved.get(id(browser))
        if entry and _normalize_origin(url) != entry["origin"]:
            self._unsaved.pop(id(browser), None)
        if browser is self._current_browser():
            self.refresh_key_icon()

    def refresh_key_icon(self):
        """Muestra la llave si la pestaña actual tiene cuentas o algo por guardar."""
        action = self._key_action
        if action is None:
            return
        try:
            visible, tip = False, ""
            browser = self._current_browser()
            origin = self._browser_origin(browser) if browser is not None else ""
            if origin and not _is_private_mode():
                unsaved = self._unsaved_for(browser, origin)
                n = len(self._page_credentials(origin))
                visible = bool(n or unsaved)
                tip = (f"Saved passwords for this site: {n}" if n else "Passwords")
                if unsaved:
                    tip += " - click to save the password you just used"
            action.setVisible(visible)
            action.setToolTip(tip)
        except RuntimeError:
            self._key_action = None   # la barra de URL ya no existe
        except Exception as e:
            logger.error("[PasswordManager] Error refreshing key icon: %s", e)

    def _build_key_menu(self, browser, origin: str):
        """Menú de la llave: cuentas del sitio, guardar lo pendiente, gestionar."""
        menu = QMenu(self._url_bar)
        if _is_insecure_origin(origin):
            warn = menu.addAction("Not secure connection (http): passwords can be intercepted")
            warn.setEnabled(False)
            menu.addSeparator()
        creds = self._page_credentials(origin)
        if creds:
            head = menu.addAction("Fill in:")
            head.setEnabled(False)
            for c in creds:
                act = menu.addAction(c["username"].replace("&", "&&"))
                act.triggered.connect(
                    lambda _=False, u=c["username"]: self._fill_from_key(browser, origin, u))
        unsaved = self._unsaved_for(browser, origin)
        if unsaved:
            if creds:
                menu.addSeparator()
            verb = "Update" if unsaved["is_update"] else "Save"
            act = menu.addAction(f"{verb} password for {unsaved['username']}".replace("&", "&&"))
            act.triggered.connect(lambda _=False, b=browser: self._save_unsaved(b))
        menu.addSeparator()
        manage = menu.addAction("Manage passwords")
        manage.triggered.connect(self._open_manager_panel)
        return menu

    def _show_key_menu(self):
        try:
            browser = self._current_browser()
            origin = self._browser_origin(browser) if browser is not None else ""
            if not origin or self._url_bar is None:
                return
            menu = self._build_key_menu(browser, origin)
            menu.aboutToHide.connect(menu.deleteLater)
            bar = self._url_bar
            x = max(0, bar.width() - menu.sizeHint().width())
            menu.popup(bar.mapToGlobal(QPoint(x, bar.height())))
        except Exception as e:
            logger.error("[PasswordManager] Error showing key menu: %s", e)

    def _fill_from_key(self, browser, origin: str, username: str):
        if _is_private_mode() or self._browser_origin(browser) != origin:
            return
        for c in self._page_credentials(origin):
            if c["username"] == username:
                self._inject_fill(browser, origin, c, "full", own_frame=True)
                return

    def _save_unsaved(self, browser):
        entry = self._unsaved.pop(id(browser), None)
        if not entry:
            return
        self._dismissed_origins.discard(entry["origin"])
        self._store_credential(entry["origin"], entry["username"], entry["password"],
                               entry["is_update"])
        self.refresh_key_icon()

    def _open_manager_panel(self):
        main_win = self._find_main_window()
        if main_win is not None and hasattr(main_win, "toggle_password_manager"):
            try:
                main_win.toggle_password_manager()
            except Exception as e:
                logger.error("[PasswordManager] Error opening password panel: %s", e)
