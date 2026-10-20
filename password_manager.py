from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QLineEdit, QListWidget, QListWidgetItem,
                              QDialog, QMessageBox, QCheckBox, QGroupBox,
                              QApplication, QTableWidget, QTableWidgetItem,
                              QHeaderView, QDialogButtonBox, QFrame,
                              QGraphicsOpacityEffect)
from PySide6.QtCore import (Qt, QSettings, Signal, QUrl, QObject, Slot,
                            QTimer, QPropertyAnimation, QEasingCurve,
                            QFile, QIODevice)
from PySide6.QtGui import QIntValidator
from PySide6.QtWebChannel import QWebChannel
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
_MAX_PAYLOAD_LEN  = 8192
_MAX_USERNAME_LEN = 512
_MAX_PASSWORD_LEN = 4096

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

    credential_received = Signal(str, str, str)  # origin, username, password
    autofill_requested  = Signal(str, str)       # origin, usuario ya escrito

    def __init__(self, parent=None, origin_getter=None):
        super().__init__(parent)
        self._origin_getter = origin_getter
        self._last_fill_request = 0.0

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
            if not isinstance(username, str) or not isinstance(password, str):
                return
            if (not username or not password or len(username) > _MAX_USERNAME_LEN
                    or len(password) > _MAX_PASSWORD_LEN):
                return
            # El campo "origin" del payload se ignora a propósito
            origin = self._current_origin()
            if not origin:
                return
            logger.info("[PasswordManager] Credential received via WebChannel: %s", origin)
            self.credential_received.emit(origin, username, password)
        except Exception as exc:
            logger.error("[PasswordManager] Error parsing credential payload: %s", exc)

    @Slot(str)
    def requestAutofill(self, json_str: str) -> None:
        """El usuario ha pulsado (o tabulado a) un campo de login: pedir relleno."""
        try:
            now = time.monotonic()
            if now - self._last_fill_request < 0.5:
                return
            self._last_fill_request = now
            data = self._parse_payload(json_str)
            if data is None:
                return
            typed = data.get("username", "")
            if not isinstance(typed, str) or len(typed) > _MAX_USERNAME_LEN:
                typed = ""
            origin = self._current_origin()
            if origin:
                self.autofill_requested.emit(origin, typed)
        except Exception as exc:
            logger.error("[PasswordManager] Error en la petición de autorrelleno: %s", exc)


# ---------------------------------------------------------------------------
# PasswordSaveBanner — non-intrusive banner shown below the nav bar
# ---------------------------------------------------------------------------

class PasswordSaveBanner(QFrame):
    """Non-intrusive banner shown below the nav bar when credentials are detected."""

    accepted  = Signal()
    dismissed = Signal()

    def __init__(self, url: str, username: str, password: str,
                 is_update: bool = False, parent=None):
        super().__init__(parent)
        self.url       = url
        self.username  = username
        self.password  = password
        self.is_update = is_update
        self.setObjectName("passwordSaveBanner")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(48)
        self._build_ui()
        self._apply_style()
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(15_000)
        self._auto_timer.timeout.connect(self._on_dismiss)
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
        lbl = QLabel(f"{action} password for <b>{self.username}</b> on {origin}?")
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
#   form submit / button click / Enter key
#     → emitCred()
#       → window.__katphi.onCredential(json)   [QWebChannel slot call]
#         → CredentialReceiver.onCredential()      [Python main thread]
#
# Covers:
#   1. Native <form> submit events (traditional sites)
#   2. Click on ANY button-like element: <button> (any type), role="button",
#      <input type="submit|button">, <a> — handles React/Vue modal buttons
#      that never fire a native submit event.
#   3. Enter key in any <input> field within a login container.
#
# Containers searched (in priority order):
#   <form> → [role="dialog|alertdialog"] → class/id patterns for modal/login
#   → document.body as last resort.
#
# Debounce: 400 ms prevents duplicate emits when click + submit both fire.
# Pending cred: if the WebChannel isn't connected yet at emit time, the
# credential is stored and sent as soon as the channel is ready.
#
# Este script se ejecuta en el ApplicationWorld (mundo aislado): la página no
# puede llamar a window.__katphi ni ver qt.webChannelTransport. El origen no
# se envía (Python lo calcula a partir de la URL real del browser).
#
# Autorrelleno (A-005): al cargar, Python solo indica si hay credenciales
# guardadas (window.__katphiHasCreds). Cuando el usuario hace clic o llega con
# Tab a un campo de usuario o contraseña (evento isTrusted, no sintetizable
# por la página), se pide el relleno a Python, que responde llamando a
# window.__katphiFill() en este mismo mundo con UNA sola credencial.
# ---------------------------------------------------------------------------

_CAPTURE_JS = r'''
(function() {
    if (window.__katphiCapture) return;
    window.__katphiCapture = true;
    window.__katphi         = null;
    window.__scrapalioCredPend = null;
    window.__katphiLastEmit = 0;
    window.__katphiHasCreds = false;
    window.__katphiLastFill = 0;
    window.__katphiFillTarget = null;

    // ── Helpers ──────────────────────────────────────────────────────────

    function isUsernameField(inp) {
        if (!inp || inp.type === 'hidden') return false;
        var t  = (inp.type          || '').toLowerCase();
        var ac = (inp.autocomplete  || '').toLowerCase();
        if (t === 'password' || t === 'submit' || t === 'button' ||
            t === 'checkbox' || t === 'radio'  || t === 'file') return false;
        if (t === 'email') return true;
        if (ac === 'username' || ac === 'email' || ac === 'tel') return true;
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

    function findPasswordField(root) {
        var inputs = root.querySelectorAll('input');
        for (var i = 0; i < inputs.length; i++) {
            var t  = (inputs[i].type         || '').toLowerCase();
            var ac = (inputs[i].autocomplete || '').toLowerCase();
            if (t === 'password' ||
                ac === 'current-password' ||
                ac === 'new-password') return inputs[i];
        }
        return null;
    }

    function findFormFields(root) {
        var fields = { username: null, password: null };
        var pw = findPasswordField(root);
        if (!pw) return fields;
        fields.password = pw;
        var all = Array.prototype.slice.call(root.querySelectorAll('input'));
        var pi  = all.indexOf(pw);
        for (var j = pi - 1; j >= 0; j--) {
            if (isUsernameField(all[j])) { fields.username = all[j]; break; }
        }
        if (!fields.username) {
            for (var k = 0; k < all.length; k++) {
                if (isUsernameField(all[k])) { fields.username = all[k]; break; }
            }
        }
        return fields;
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

    // ── Emit ─────────────────────────────────────────────────────────────

    function emitCred(user, pass) {
        var now = Date.now();
        if (now - window.__katphiLastEmit < 400) return;   // debounce
        window.__katphiLastEmit = now;
        var payload = JSON.stringify({ username: user, password: pass });
        if (window.__katphi) {
            try { window.__katphi.onCredential(payload); } catch(e) {}
        } else {
            // Channel not ready yet; store and send when it connects
            window.__scrapalioCredPend = payload;
        }
    }

    function tryCapture(container) {
        var f = findFormFields(container);
        if (f.username && f.password && f.username.value && f.password.value) {
            emitCred(f.username.value, f.password.value);
        }
    }

    // ── Connect to QWebChannel ───────────────────────────────────────────
    // qt.webChannelTransport is injected by Qt when page.setWebChannel() was called.

    if (typeof QWebChannel !== 'undefined' &&
        typeof qt !== 'undefined' && qt.webChannelTransport) {
        new QWebChannel(qt.webChannelTransport, function(channel) {
            window.__katphi = channel.objects.credReceiver;
            if (window.__scrapalioCredPend) {
                try { window.__katphi.onCredential(window.__scrapalioCredPend); }
                catch(e) {}
                window.__scrapalioCredPend = null;
            }
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

    // 2. Click on any button-like element (React/Vue modals, type="button")
    document.addEventListener('click', function(e) {
        try {
            var btn = findButtonAncestor(e.target);
            if (btn) tryCapture(findContainer(btn));
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

    // ── Autorrelleno con gesto del usuario ───────────────────────────────

    function maybeRequestFill(e) {
        try {
            if (!e.isTrusted || !window.__katphiHasCreds || !window.__katphi) return;
            var t = e.target;
            if (!t || t.tagName !== 'INPUT') return;
            var c = findContainer(t);
            var f = findFormFields(c);
            if (!f.password || f.password.value) return;
            if (t !== f.password && t !== f.username) return;
            var now = Date.now();
            if (now - window.__katphiLastFill < 1000) return;
            window.__katphiLastFill = now;
            window.__katphiFillTarget = c;
            window.__katphi.requestAutofill(JSON.stringify({
                username: f.username ? (f.username.value || '') : ''
            }));
        } catch(ex) {}
    }

    document.addEventListener('mousedown', maybeRequestFill, true);
    document.addEventListener('keyup', function(e) {
        if (e.key === 'Tab') maybeRequestFill(e);
    }, true);

    function setVal(el, v) {
        try {
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')
                  .set.call(el, v);
        } catch(e) { el.value = v; }
        el.dispatchEvent(new Event('input',  {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }

    // Python la llama con una única credencial y el origen esperado
    window.__katphiFill = function(cred, expectedOrigin) {
        try {
            // Misma normalización que _normalize_origin() en Python
            var port = window.location.port;
            var here = window.location.protocol + '//' + window.location.hostname +
                       ((port && port !== '80' && port !== '443') ? ':' + port : '');
            if (!cred || here !== expectedOrigin) return false;
            var c = window.__katphiFillTarget || document.body;
            window.__katphiFillTarget = null;
            var f = findFormFields(c);
            if (!f.password || f.password.value) return false;
            if (f.username && cred.username && !f.username.value) setVal(f.username, cred.username);
            if (cred.password) setVal(f.password, cred.password);
            return true;
        } catch(ex) { return false; }
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

    def _open_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(self._CREATE_TABLE_SQL)
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

        Borra de la BD real (self.db_path) y hace VACUUM para que las filas
        borradas no queden en páginas libres del archivo.
        """
        try:
            if self.conn is not None:
                self.conn.execute("DELETE FROM passwords")
                self.conn.commit()
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("DELETE FROM passwords")
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

    def _on_credentials_captured(self, origin: str, username: str, password: str):
        try:
            if _is_private_mode():
                return  # ventana privada: no se guardan credenciales
            if not username or not password:
                return
            if self.fernet is None:
                self._require_fernet()
                return
            if origin in self._dismissed_origins:
                logger.debug("[PasswordManager] Origin dismissed, skipping: %s", origin)
                return
            action, _ = self.compare_credentials(origin, username, password)
            logger.info("[PasswordManager] Action=%s for %s", action, origin)
            if action == "same":
                return
            self._show_save_banner(origin, username, password,
                                   is_update=(action == "update"))
        except Exception as e:
            logger.error("[PasswordManager] Error handling captured credentials: %s", e)

    def _show_save_banner(self, origin: str, username: str, password: str,
                          is_update: bool):
        try:
            if self._active_banner is not None:
                try:
                    self._active_banner.deleteLater()
                except RuntimeError:
                    pass
                self._active_banner = None

            main_win = self._find_main_window()
            if main_win is None:
                if is_update:
                    self.update_password(origin, username, password)
                    self.password_updated.emit(origin, username)
                else:
                    self.save_password(origin, username, password)
                    self.password_saved.emit(origin, username)
                logger.warning(
                    "[PasswordManager] Main window not found; credential for %s "
                    "saved silently (no banner)", origin)
                return

            logger.info(
                "[PasswordManager] Showing %s banner for %s",
                "update" if is_update else "save", origin)

            banner = PasswordSaveBanner(origin, username, password,
                                        is_update=is_update, parent=None)
            self._active_banner = banner

            def on_accepted():
                if is_update:
                    self.update_password(origin, username, password)
                    self.password_updated.emit(origin, username)
                else:
                    self.save_password(origin, username, password)
                    self.password_saved.emit(origin, username)
                self._active_banner = None

            def on_dismissed():
                logger.info("[PasswordManager] Banner dismissed for %s", origin)
                self._dismissed_origins.add(origin)
                self._active_banner = None

            banner.accepted.connect(on_accepted)
            banner.dismissed.connect(on_dismissed)
            self._insert_banner_in_layout(main_win, banner)
        except Exception as e:
            logger.error("[PasswordManager] Error showing save banner: %s", e)

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
            if browser_id in self._browser_connections:
                entry = self._browser_connections.pop(browser_id)
                for signal, slot in entry.get("signals", []):
                    try:
                        signal.disconnect(slot)
                    except (RuntimeError, TypeError):
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
    #   3. On each loadFinished: inject qwebchannel.js + _CAPTURE_JS together
    #      in the same ApplicationWorld, then tell it whether there are creds
    #   4. JS calls window.__katphi.onCredential(json) → Python slot fires
    #      (origin computed in Python from browser.url())
    #   5. Trusted click/Tab on a login field → requestAutofill → Python
    #      injects ONE credential via window.__katphiFill() (isolated world)
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

            # Create receiver + channel, register on current page.
            # IMPORTANT: keep strong Python references to both objects in
            # _browser_connections — PySide6 may GC the wrappers even when Qt
            # parent-child ownership is set, which silently breaks the @Slot.
            # El origen lo calcula el receiver con la URL real de este browser.
            receiver = CredentialReceiver(
                browser, origin_getter=lambda b=browser: b.url().toString())
            channel  = QWebChannel(browser.page())
            channel.registerObject("credReceiver", receiver)
            # Mundo aislado: el JS de la página no ve qt.webChannelTransport
            browser.page().setWebChannel(channel, _APP_WORLD)
            logger.info(
                "[PasswordManager] WebChannel configured (browser %s)", browser_id)

            signals = []

            def on_cred(origin, username, password):
                self._on_credentials_captured(origin, username, password)

            receiver.credential_received.connect(on_cred)
            signals.append((receiver.credential_received, on_cred))

            def on_fill_request(origin, typed, b=browser):
                self._fill_on_request(b, origin, typed)

            receiver.autofill_requested.connect(on_fill_request)
            signals.append((receiver.autofill_requested, on_fill_request))

            qwc_js = PasswordManager._qwebchannel_js

            def on_load_finished(ok, b=browser):
                if not ok:
                    return
                logger.debug("[PasswordManager] Page loaded, injecting scripts")
                if qwc_js:
                    b.page().runJavaScript(qwc_js + "\n" + _CAPTURE_JS, _APP_WORLD)
                else:
                    logger.warning(
                        "[PasswordManager] qwebchannel.js empty — falling back "
                        "to capture-only mode (no WebChannel)")
                    b.page().runJavaScript(_CAPTURE_JS, _APP_WORLD)

                # Verify JS state 800 ms after injection to help diagnose issues
                def _verify():
                    try:
                        b.page().runJavaScript(
                            "JSON.stringify({"
                            "  qwc: typeof QWebChannel !== 'undefined',"
                            "  qt:  typeof qt !== 'undefined',"
                            "  tr:  !!(typeof qt !== 'undefined' && qt.webChannelTransport),"
                            "  ch:  !!(window.__katphi),"
                            "  cap: !!(window.__katphiCapture)"
                            "})",
                            _APP_WORLD,
                            lambda r: logger.debug(
                                "[PasswordManager] JS state after inject: %s", r)
                        )
                    except Exception:
                        pass
                QTimer.singleShot(800, _verify)

                self._attempt_autofill(b)

            browser.loadFinished.connect(on_load_finished)
            signals.append((browser.loadFinished, on_load_finished))

            # Store receiver + channel alongside signal pairs so their Python
            # wrappers cannot be garbage-collected while the tab is open.
            self._browser_connections[browser_id] = {
                "signals":  signals,
                "receiver": receiver,
                "channel":  channel,
            }
        except Exception as e:
            logger.error("[PasswordManager] Error setting up browser: %s", e)

    def _attempt_autofill(self, browser):
        """Al cargar: solo marca (en el mundo aislado) si hay credenciales.

        No se rellena nada ni se envía ninguna contraseña a la página hasta
        que el usuario pulsa o tabula a un campo de login (ver _fill_on_request).
        """
        try:
            url = browser.url().toString()
            if urlparse(url).scheme.lower() not in ("http", "https"):
                return
            origin = _normalize_origin(url)
            has = self.has_credentials_for_origin(origin)
            browser.page().runJavaScript(
                "window.__katphiHasCreds = " + ("true" if has else "false") + ";",
                _APP_WORLD)
            if has:
                logger.debug("[PasswordManager] Autofill available for %s", origin)
        except Exception as e:
            logger.error("[PasswordManager] Error in autofill: %s", e)

    @staticmethod
    def _choose_credential(creds: list, typed: str):
        """Elige UNA credencial: la del usuario ya escrito o, si no, la más reciente."""
        if not creds:
            return None
        if typed:
            for c in creds:
                if c["username"] == typed:
                    return c
            return None  # el usuario está escribiendo otra cuenta: no se rellena
        return creds[0]  # get_credentials_for_origin ya ordena por más reciente

    def _fill_on_request(self, browser, origin: str, typed: str):
        """Respuesta a un gesto del usuario: inyecta una sola credencial."""
        try:
            if _is_private_mode() or not origin:
                return
            # La página pudo navegar entre la petición y la respuesta
            if _normalize_origin(browser.url().toString()) != origin:
                return
            cred = self._choose_credential(self.get_credentials_for_origin(origin), typed)
            if cred is None:
                return
            # Host en punycode, como lo ve location.hostname en JS
            js_origin = _normalize_origin(bytes(browser.url().toEncoded()).decode("ascii", "replace"))
            js = ("window.__katphiFill && window.__katphiFill("
                  + json.dumps({"username": cred["username"], "password": cred["password"]})
                  + ", " + json.dumps(js_origin) + ");")
            browser.page().runJavaScript(js, _APP_WORLD)
            logger.info("[PasswordManager] Autofill on user gesture for %s", origin)
        except Exception as e:
            logger.error("[PasswordManager] Error filling credential: %s", e)
