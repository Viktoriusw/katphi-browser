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
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
import sqlite3
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
    """

    credential_received = Signal(str, str, str)  # origin, username, password

    @Slot(str)
    def onCredential(self, json_str: str) -> None:
        try:
            data = json.loads(json_str)
            origin   = data.get("origin",   "")
            username = data.get("username", "")
            password = data.get("password", "")
            if origin and username and password:
                logger.info(
                    "[PasswordManager] Credential received via WebChannel: %s / %s",
                    origin, username,
                )
                self.credential_received.emit(origin, username, password)
        except Exception as exc:
            logger.error("[PasswordManager] Error parsing credential payload: %s", exc)


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
# ---------------------------------------------------------------------------

_CAPTURE_JS = r'''
(function() {
    if (window.__katphiCapture) return;
    window.__katphiCapture = true;
    window.__katphi         = null;
    window.__scrapalioCredPend = null;
    window.__katphiLastEmit = 0;

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

    function getOrigin() {
        return window.location.protocol + '//' + window.location.host;
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
        var payload = JSON.stringify({ origin: getOrigin(), username: user, password: pass });
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.password_generator = PasswordGenerator()
        self.settings  = QSettings("Katphi", "Passwords")
        self.db_path   = "passwords.db"
        self.init_ui()
        self.init_database()
        self.load_passwords()
        self.setup_encryption()
        self._browser_connections: dict = {}   # browser_id → {"signals": [...], "receiver": ..., "channel": ...}
        self._dismissed_origins:   set  = set()
        self._active_banner              = None

    # -----------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------

    def init_ui(self):
        layout = QVBoxLayout(self)

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

    # -----------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------

    def init_database(self):
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS passwords (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    url        TEXT NOT NULL,
                    username   TEXT NOT NULL,
                    password   TEXT NOT NULL,
                    notes      TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.conn.commit()
        except Exception as e:
            logger.error("[PasswordManager] Error initializing database: %s", e)

    def load_passwords(self):
        try:
            self.passwords_list.clear()
            cursor = self.conn.cursor()
            cursor.execute("SELECT url, username, notes FROM passwords ORDER BY url")
            for row in cursor.fetchall():
                item = QListWidgetItem(f"{row[0]} - {row[1]}")
                if row[2]:
                    item.setToolTip(row[2])
                self.passwords_list.addItem(item)
            self.passwords_list.itemDoubleClicked.connect(self.view_password_details)
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
        try:
            if not self.settings.contains("encryption_key"):
                self.settings.setValue("encryption_key", Fernet.generate_key().decode())
            self.fernet = Fernet(self.settings.value("encryption_key").encode())
        except Exception as e:
            logger.error("[PasswordManager] Error setting up encryption: %s", e)

    def _decrypt_password(self, raw: str) -> str:
        """Try Fernet decrypt; fall back to raw for legacy plain-text entries."""
        try:
            return self.fernet.decrypt(raw.encode()).decode()
        except Exception:
            return raw

    # -----------------------------------------------------------------
    # CRUD — manual UI dialogs
    # -----------------------------------------------------------------

    def add_password(self):
        try:
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

            current_plain = self._decrypt_password(row[0])

            dialog = QDialog(self)
            dialog.setWindowTitle("Edit Password")
            layout = QVBoxLayout(dialog)

            url_input      = QLineEdit(url)
            username_input = QLineEdit(username)
            password_input = QLineEdit(current_plain)
            password_input.setEchoMode(QLineEdit.Password)
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
            url, username = item.text().split(" - ", 1)

            cur = self.conn.cursor()
            cur.execute(
                "SELECT password, notes FROM passwords WHERE url=? AND username=?",
                (url, username))
            row = cur.fetchone()
            if not row:
                return

            plain = self._decrypt_password(row[0])

            dialog = QDialog(self)
            dialog.setWindowTitle("Password Details")
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(f"<b>URL:</b> {url}"))
            layout.addWidget(QLabel(f"<b>Username:</b> {username}"))

            pw_input = QLineEdit(plain)
            pw_input.setEchoMode(QLineEdit.Password)
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
            enc = self.fernet.encrypt(password.encode()).decode()
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO passwords (url, username, password) VALUES (?,?,?)",
                (url, username, enc))
            conn.commit()
            conn.close()
            logger.info("[PasswordManager] Credential saved: %s / %s", url, username)
            self.load_passwords()
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error saving password: %s", e)
            return False

    def update_password(self, origin: str, username: str, new_password: str) -> bool:
        try:
            enc = self.fernet.encrypt(new_password.encode()).decode()
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE passwords SET password=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE url=? AND username=?",
                (enc, origin, username))
            conn.commit()
            conn.close()
            logger.info("[PasswordManager] Credential updated: %s / %s", origin, username)
            self.load_passwords()
            return True
        except Exception as e:
            logger.error("[PasswordManager] Error updating password: %s", e)
            return False

    def get_password(self, url: str, username: str):
        try:
            conn = sqlite3.connect(self.db_path)
            cur  = conn.cursor()
            cur.execute(
                "SELECT password FROM passwords WHERE url=? AND username=?",
                (url, username))
            row = cur.fetchone()
            conn.close()
            return self._decrypt_password(row[0]) if row else None
        except Exception as e:
            logger.error("[PasswordManager] Error getting password: %s", e)
            return None

    def get_all_passwords(self) -> list:
        try:
            conn = sqlite3.connect(self.db_path)
            cur  = conn.cursor()
            cur.execute("SELECT url, username, password FROM passwords")
            rows = cur.fetchall()
            conn.close()
            result = []
            for url, username, raw in rows:
                try:
                    result.append({"url": url, "username": username,
                                   "password": self._decrypt_password(raw)})
                except Exception:
                    continue
            return result
        except Exception as e:
            logger.error("[PasswordManager] Error getting all passwords: %s", e)
            return []

    def get_credentials_for_origin(self, origin: str) -> list:
        try:
            conn = sqlite3.connect(self.db_path)
            cur  = conn.cursor()
            cur.execute("SELECT username, password FROM passwords WHERE url=?", (origin,))
            rows = cur.fetchall()
            conn.close()
            creds = []
            for username, raw in rows:
                try:
                    creds.append({"username": username,
                                  "password": self._decrypt_password(raw)})
                except Exception:
                    continue
            return creds
        except Exception as e:
            logger.error("[PasswordManager] Error getting credentials for origin: %s", e)
            return []

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
        """Delete every stored credential. Called from 'Clear browsing data'."""
        try:
            for conn in (sqlite3.connect(self.db_path), self.conn):
                conn.execute("DELETE FROM passwords")
                conn.commit()
                if conn is not self.conn:
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
        stored = self.get_password(origin, username)
        if stored is None:
            return ("new", None)
        if stored == password:
            return ("same", stored)
        return ("update", stored)

    # -----------------------------------------------------------------
    # Banner logic
    # -----------------------------------------------------------------

    def _on_credentials_captured(self, origin: str, username: str, password: str):
        try:
            if not username or not password:
                return
            if origin in self._dismissed_origins:
                logger.debug("[PasswordManager] Origin dismissed, skipping: %s", origin)
                return
            action, _ = self.compare_credentials(origin, username, password)
            logger.info("[PasswordManager] Action=%s for %s / %s", action, origin, username)
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
                "[PasswordManager] Showing %s banner for %s / %s",
                "update" if is_update else "save", origin, username)

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
                table.setItem(i, 2, QTableWidgetItem("••••••••"))
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
            if hasattr(self, 'conn'):
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
    #   2. QWebChannel set on the page → injects qt.webChannelTransport in JS
    #   3. On each loadFinished: inject qwebchannel.js + _CAPTURE_JS together
    #   4. JS calls window.__katphi.onCredential(json) → Python slot fires
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
            receiver = CredentialReceiver(browser)
            channel  = QWebChannel(browser.page())
            channel.registerObject("credReceiver", receiver)
            browser.page().setWebChannel(channel)
            logger.info(
                "[PasswordManager] WebChannel configured (browser %s)", browser_id)

            signals = []

            def on_cred(origin, username, password):
                self._on_credentials_captured(origin, username, password)

            receiver.credential_received.connect(on_cred)
            signals.append((receiver.credential_received, on_cred))

            qwc_js = PasswordManager._qwebchannel_js

            def on_load_finished(ok, b=browser):
                if not ok:
                    return
                url = b.url().toString()
                logger.debug(
                    "[PasswordManager] Page loaded, injecting scripts: %s", url)
                if qwc_js:
                    b.page().runJavaScript(qwc_js + "\n" + _CAPTURE_JS)
                else:
                    logger.warning(
                        "[PasswordManager] qwebchannel.js empty — falling back "
                        "to capture-only mode (no WebChannel)")
                    b.page().runJavaScript(_CAPTURE_JS)

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
        try:
            origin = _normalize_origin(browser.url().toString())
            creds  = self.get_credentials_for_origin(origin)
            if not creds:
                return
            creds_json = json.dumps(creds)
            autofill_js = r'''
(function() {
    var creds = ''' + creds_json + r''';
    if (!creds || !creds.length) return;

    function isUsernameField(inp) {
        if (!inp || inp.type === 'hidden') return false;
        var t  = (inp.type || '').toLowerCase();
        var ac = (inp.autocomplete || '').toLowerCase();
        if (t === 'password' || t === 'submit' || t === 'button' ||
            t === 'checkbox'  || t === 'radio'  || t === 'file') return false;
        if (t === 'email') return true;
        if (ac === 'username' || ac === 'email') return true;
        var attrs = [(inp.name||''),(inp.id||''),(inp.placeholder||''),
                     (inp.getAttribute('aria-label')||'')].join(' ').toLowerCase();
        var kw = ['user','email','login','account','nick','identifier',
                  'phone','mobile','correo','usuario','nombre'];
        for (var i = 0; i < kw.length; i++) { if (attrs.indexOf(kw[i]) !== -1) return true; }
        return false;
    }
    function findFields() {
        var inputs = document.querySelectorAll('input'), pw = null, user = null;
        for (var i = 0; i < inputs.length; i++) {
            if ((inputs[i].type||'').toLowerCase() === 'password') { pw = inputs[i]; break; }
        }
        if (!pw) return null;
        var all = Array.prototype.slice.call(inputs), pi = all.indexOf(pw);
        for (var j = pi-1; j>=0; j--) { if (isUsernameField(all[j])) { user=all[j]; break; } }
        if (!user) { for (var k=0; k<all.length; k++) { if (isUsernameField(all[k])) { user=all[k]; break; } } }
        return { username: user, password: pw };
    }
    function setVal(el, v) {
        try {
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
                  .set.call(el, v);
            el.dispatchEvent(new Event('input',  {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        } catch(e) { el.value = v; }
    }
    var f = findFields();
    if (!f || !f.password || f.password.value) return;
    if (f.username && creds[0].username) setVal(f.username, creds[0].username);
    if (f.password && creds[0].password) setVal(f.password, creds[0].password);
})();
'''
            browser.page().runJavaScript(autofill_js)
            logger.info("[PasswordManager] Autofill injected for %s", origin)
        except Exception as e:
            logger.error("[PasswordManager] Error in autofill: %s", e)
