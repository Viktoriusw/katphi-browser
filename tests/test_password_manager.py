"""Tests del gestor de contraseñas (password_manager.py).

Se ejecutan con QT_QPA_PLATFORM=offscreen, QSettings aislado en un tmpdir y
la BD en tmp_path. El llavero del sistema se sustituye por un falso.
"""
import json
import os
import sqlite3
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest
from cryptography.fernet import Fernet
from PySide6.QtCore import QSettings, SIGNAL
from PySide6.QtWidgets import QApplication

import password_manager as pm


@pytest.fixture(scope="session")
def qapp():
    try:
        # WebEngine exige este import antes de crear la QApplication
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except Exception:
        pass
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, qapp):
    cfg = tmp_path / "qsettings"
    cfg.mkdir()
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(cfg))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(cfg))
    QSettings("Katphi", "Passwords").clear()
    monkeypatch.setattr(pm, "_keyring_module", lambda: None)
    monkeypatch.setattr(pm, "_is_private_mode", lambda: False)
    monkeypatch.setattr(pm.PasswordManager, "_show_dialogs", False)
    yield


def make_pm(tmp_path, name="passwords.db"):
    return pm.PasswordManager(db_path=str(tmp_path / name))


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, entry):
        return self.store.get((service, entry))

    def set_password(self, service, entry, value):
        self.store[(service, entry)] = value


# ---------------------------------------------------------------- origen

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/login?x=1", "https://example.com"),
    ("https://example.com:443/a", "https://example.com"),
    ("http://example.com:80/", "http://example.com"),
    ("http://localhost:8080/path", "http://localhost:8080"),
    ("https://Sub.Example.COM/", "https://sub.example.com"),
    ("example.com", "https://"),
])
def test_normalize_origin(url, expected):
    assert pm._normalize_origin(url) == expected


# ---------------------------------------------------------------- cifrado

def test_encrypt_roundtrip(tmp_path):
    m = make_pm(tmp_path)
    assert m.fernet is not None
    assert m.save_password("https://a.com", "alice", "s3cret")
    raw = m._get_raw_password("https://a.com", "alice")
    assert raw.startswith("gAAAA") and "s3cret" not in raw
    assert m.get_password("https://a.com", "alice") == "s3cret"
    # Una segunda instancia con el mismo QSettings lee la misma clave
    m2 = make_pm(tmp_path)
    assert m2.get_password("https://a.com", "alice") == "s3cret"


def test_legacy_plaintext_vs_invalid_token(tmp_path):
    m = make_pm(tmp_path)
    other = Fernet(Fernet.generate_key()).encrypt(b"otherkey").decode()
    assert m._decrypt_password("hunter2") == "hunter2"       # texto plano heredado
    assert m._decrypt_password(other) is None                 # InvalidToken
    assert m._decrypt_password("gAAAAbasura") is None         # token mal formado
    assert m._is_decryptable("hunter2")
    assert not m._is_decryptable(other)

    conn = sqlite3.connect(m.db_path)
    conn.execute("INSERT INTO passwords (url, username, password) VALUES (?,?,?)",
                 ("https://b.com", "bob", other))
    conn.execute("INSERT INTO passwords (url, username, password) VALUES (?,?,?)",
                 ("https://b.com", "carol", "plainpw"))
    conn.commit()
    conn.close()

    creds = m.get_credentials_for_origin("https://b.com")
    assert creds == [{"username": "carol", "password": "plainpw"}]   # bob excluido
    assert m.compare_credentials("https://b.com", "bob", "x") == ("update", None)
    entries = {e["username"]: e for e in m.get_all_passwords()}
    assert entries["bob"]["undecryptable"] and entries["bob"]["password"] is None
    m.load_passwords()
    assert m.passwords_list.count() == 2
    assert pm.UNDECRYPTABLE_LABEL in m.status_label.text()
    tips = [m.passwords_list.item(i).toolTip() for i in range(2)]
    assert any(pm.UNDECRYPTABLE_LABEL in t for t in tips)


def test_encryption_failure_disables_saving(tmp_path, monkeypatch):
    def boom(self):
        raise RuntimeError("sin clave")
    monkeypatch.setattr(pm.PasswordManager, "_load_or_create_key", boom)
    m = make_pm(tmp_path)
    assert m.fernet is None
    assert m.save_password("https://a.com", "a", "b") is False
    assert not m.status_label.isHidden()


# ---------------------------------------------------------------- keyring

def test_key_migrates_to_keyring(tmp_path, monkeypatch):
    m = make_pm(tmp_path)                  # clave creada en QSettings
    m.save_password("https://a.com", "alice", "pw")
    key = QSettings("Katphi", "Passwords").value("encryption_key")
    assert key

    kr = FakeKeyring()
    monkeypatch.setattr(pm, "_keyring_module", lambda: kr)
    m2 = make_pm(tmp_path)
    s = QSettings("Katphi", "Passwords")
    assert kr.get_password(pm._KEYRING_SERVICE, pm._KEYRING_ENTRY) == key
    assert not s.contains("encryption_key")
    assert m2.get_password("https://a.com", "alice") == "pw"

    # Si el llavero deja de estar disponible no se genera otra clave
    monkeypatch.setattr(pm, "_keyring_module", lambda: None)
    m3 = make_pm(tmp_path)
    assert m3.fernet is None
    assert not QSettings("Katphi", "Passwords").contains("encryption_key")


# ---------------------------------------------------------------- BD

def test_db_permissions(tmp_path):
    m = make_pm(tmp_path)
    if os.name == "posix":
        assert (os.stat(m.db_path).st_mode & 0o777) == 0o600


def test_corrupt_db_is_moved_aside(tmp_path):
    db = tmp_path / "passwords.db"
    db.write_bytes(b"esto no es una base de datos sqlite" * 100)
    m = make_pm(tmp_path)
    assert (tmp_path / "passwords.db.corrupt").exists()
    assert m.conn is not None
    assert m.save_password("https://a.com", "a", "b")
    assert not m.status_label.isHidden()


def test_legacy_db_migration(tmp_path, monkeypatch):
    old_cwd = tmp_path / "cwd"
    old_cwd.mkdir()
    legacy = old_cwd / "passwords.db"
    conn = sqlite3.connect(legacy)
    conn.execute(pm.PasswordManager._CREATE_TABLE_SQL)
    conn.execute("INSERT INTO passwords (url, username, password) VALUES ('u','n','p')")
    conn.commit()
    conn.close()
    data = tmp_path / "data" / "Katphi"
    monkeypatch.setattr(pm, "_user_data_dir", lambda: data)
    monkeypatch.chdir(old_cwd)

    path = pm._resolve_db_path()
    assert path == str(data / "passwords.db")
    rows = sqlite3.connect(path).execute("SELECT url, username, password FROM passwords").fetchall()
    assert rows == [("u", "n", "p")]
    assert not legacy.exists()
    assert (old_cwd / "passwords.db.migrated").exists()
    # Segunda llamada: no vuelve a migrar ni toca nada
    assert pm._resolve_db_path() == path


def test_double_click_connected_once(tmp_path):
    m = make_pm(tmp_path)
    for _ in range(3):
        m.load_passwords()
    assert m.passwords_list.receivers(
        SIGNAL("itemDoubleClicked(QListWidgetItem*)")) == 1


def test_clear_all_passwords(tmp_path):
    m = make_pm(tmp_path)
    m.save_password("https://a.com", "a", "1")
    m.save_password("https://b.com", "b", "2")
    assert m.clear_all_passwords()
    assert sqlite3.connect(m.db_path).execute("SELECT COUNT(*) FROM passwords").fetchone()[0] == 0
    assert m.passwords_list.count() == 0


# ---------------------------------------------------------------- receiver

def _receiver(url):
    r = pm.CredentialReceiver(None, origin_getter=lambda: url)
    got = []
    r.credential_received.connect(lambda o, info: got.append((o, info)))
    return r, got


def test_on_credential_ignores_payload_origin():
    r, got = _receiver("https://real.example/login?next=/")
    r.onCredential(json.dumps({"origin": "https://bank.com",
                               "username": "x", "password": "y"}))
    assert got == [("https://real.example",
                    {"username": "x", "password": "y", "old_password": "", "kind": "login",
                     "doc": ""})]


def test_on_credential_kinds_and_empty_username():
    r, got = _receiver("https://real.example/")
    r.onCredential(json.dumps({"username": "", "password": "new",
                               "old_password": "old", "kind": "change"}))
    r.onCredential(json.dumps({"username": "u", "password": "p", "kind": "rara"}))
    assert got[0][1]["kind"] == "change" and got[0][1]["old_password"] == "old"
    assert got[1][1]["kind"] == "login"


@pytest.mark.parametrize("payload", [
    "no es json",
    json.dumps(["x", "y"]),
    json.dumps({"username": 1, "password": "y"}),
    json.dumps({"username": "x", "password": ""}),
    json.dumps({"username": "x", "password": "p" * (pm._MAX_PASSWORD_LEN + 1)}),
    json.dumps({"username": "x", "password": "y", "old_password": 5}),
    "x" * (pm._MAX_PAYLOAD_LEN + 1),
])
def test_on_credential_rejects_invalid(payload):
    r, got = _receiver("https://real.example/")
    r.onCredential(payload)
    assert got == []


def test_on_credential_requires_http_origin():
    for url in ("file:///etc/passwd", "data:text/html,x", "about:blank", ""):
        r, got = _receiver(url)
        r.onCredential(json.dumps({"username": "x", "password": "y"}))
        assert got == []


def test_username_and_outcome_slots():
    r = pm.CredentialReceiver(None, origin_getter=lambda: "https://a.example/step1")
    users, outcomes = [], []
    r.username_captured.connect(lambda o, u: users.append((o, u)))
    r.login_outcome.connect(lambda o, res: outcomes.append((o, res)))
    r.onUsername(json.dumps({"username": "alice@a.example"}))
    r.onUsername(json.dumps({"username": ""}))
    r.onLoginOutcome(json.dumps({"result": "success"}))
    r.onLoginOutcome(json.dumps({"result": "otra"}))
    assert users == [("https://a.example", "alice@a.example")]
    assert outcomes == [("https://a.example", "success")]


def test_request_autofill_uses_real_origin():
    r = pm.CredentialReceiver(None, origin_getter=lambda: "https://real.example/a")
    got = []
    r.autofill_requested.connect(lambda o, info: got.append((o, info)))
    r.requestAutofill(json.dumps({"username": "alice", "origin": "https://bank.com",
                                  "mode": "password", "auto": True,
                                  "rect": [1, 2, 3, 4]}))
    r.requestAutofill(json.dumps({"username": "alice"}))   # limitado por frecuencia
    assert got == [("https://real.example",
                    {"username": "alice", "hidden_user": "", "mode": "password",
                     "auto": True, "rect": [1.0, 2.0, 3.0, 4.0]})]


def test_request_autofill_sanitizes():
    r = pm.CredentialReceiver(None, origin_getter=lambda: "https://real.example/a")
    got = []
    r.autofill_requested.connect(lambda o, info: got.append(info))
    r.requestAutofill(json.dumps({"mode": "x", "auto": "yes", "rect": [1, "2", 3, 4]}))
    assert got == [{"username": "", "hidden_user": "", "mode": "full",
                    "auto": False, "rect": None}]


def test_candidates():
    creds = [{"username": "alice", "password": "1"}, {"username": "bob", "password": "2"},
             {"username": "Alfred", "password": "3"}]
    names = lambda cs: [c["username"] for c in cs]
    c = pm.PasswordManager._candidates
    assert names(c(creds, "full", "")) == ["alice", "bob", "Alfred"]
    assert names(c(creds, "full", "bob")) == ["bob"]
    assert names(c(creds, "full", "al")) == ["alice", "Alfred"]
    assert c(creds, "full", "zoe") == []
    assert c(creds, "username", "bob") == []           # ya está completo
    assert names(c(creds, "password", "", "bob")) == ["bob"]
    assert c(creds, "password", "", "zoe") == []
    assert len(c(creds, "password", "")) == 3


# ---------------------------------------------------------------- guardado provisional

class FakeBrowser:
    def __init__(self, url):
        self._url = url

    def url(self):
        from PySide6.QtCore import QUrl
        return QUrl(self._url)


def _record_banner(m, monkeypatch):
    shown = []
    monkeypatch.setattr(m, "_show_save_banner",
                        lambda o, u, p, is_update, browser=None: shown.append((o, u, p, is_update)))
    return shown


def test_capture_waits_for_login_result(tmp_path, monkeypatch):
    m = make_pm(tmp_path)
    shown = _record_banner(m, monkeypatch)
    b = FakeBrowser("https://a.com/login")
    m._on_credentials_captured("https://a.com", "u", "p", browser=b)
    assert shown == [] and m._pending[id(b)]["username"] == "u"
    m._confirm_pending(b)
    assert shown == [("https://a.com", "u", "p", False)]
    assert id(b) not in m._pending

    # Caducada: no se ofrece
    m._on_credentials_captured("https://a.com", "u", "p2", browser=b)
    m._pending[id(b)]["t"] -= pm._PENDING_TTL + 1
    m._confirm_pending(b)
    assert len(shown) == 1

    # Sin browser (entrada heredada): banner inmediato
    m._on_credentials_captured("https://b.com", "u", "p")
    assert shown[-1] == ("https://b.com", "u", "p", False)


def test_resolve_username(tmp_path, monkeypatch):
    m = make_pm(tmp_path)
    shown = _record_banner(m, monkeypatch)
    b = FakeBrowser("https://a.com/")
    m.save_password("https://a.com", "alice", "old1")
    m.save_password("https://a.com", "bob", "old2")
    # Cambio de contraseña sin usuario: se identifica por la contraseña actual
    m._on_credentials_captured("https://a.com", "", "nueva", browser=b,
                               old_password="old2", kind="change")
    assert m._pending[id(b)]["username"] == "bob" and m._pending[id(b)]["is_update"]
    # Paso 2 sin usuario y varias cuentas: se usa el del paso 1
    m._remember_step_username(b, "https://a.com", "alice")
    m._on_credentials_captured("https://a.com", "", "otra", browser=b)
    assert m._pending[id(b)]["username"] == "alice"
    # Sin paso 1 ni cuenta única: se descarta
    m._step_usernames.clear()
    m._on_credentials_captured("https://a.com", "", "x", browser=b)
    assert id(b) not in m._pending
    assert shown == []


def test_same_password_clears_pending(tmp_path, monkeypatch):
    m = make_pm(tmp_path)
    _record_banner(m, monkeypatch)
    b = FakeBrowser("https://a.com/")
    m.save_password("https://a.com", "alice", "pw")
    m._on_credentials_captured("https://a.com", "alice", "mal", browser=b)
    assert id(b) in m._pending
    m._on_credentials_captured("https://a.com", "alice", "pw", browser=b)
    assert id(b) not in m._pending


# ---------------------------------------------------------------- nunca para este sitio

def test_never_save_persists(tmp_path, monkeypatch):
    m = make_pm(tmp_path)
    assert m.add_never_save("https://a.com")
    m2 = make_pm(tmp_path)
    shown = _record_banner(m2, monkeypatch)
    assert m2.is_never_save("https://a.com")
    assert m2.get_never_save_origins() == ["https://a.com"]
    m2._on_credentials_captured("https://a.com", "u", "p")
    assert shown == []
    assert m2.remove_never_save("https://a.com")
    m2._on_credentials_captured("https://a.com", "u", "p")
    assert len(shown) == 1
    m2.add_never_save("https://c.com")
    m2.clear_all_passwords()
    assert m2.get_never_save_origins() == []


def test_banner_buttons_and_timeout(qapp):
    b = pm.PasswordSaveBanner("https://a.com", "u", "p")
    got = []
    for name in ("accepted", "dismissed", "never", "timed_out"):
        getattr(b, name).connect(lambda n=name: got.append(n))
    b._on_timeout()
    b2 = pm.PasswordSaveBanner("https://a.com", "u", "p")
    b2.never.connect(lambda: got.append("never2"))
    b2._on_never()
    assert got == ["timed_out", "never2"]
    labels = [w.text() for w in b2.findChildren(pm.QPushButton)]
    assert "Never for this site" in labels
    upd = pm.PasswordSaveBanner("https://a.com", "u", "p", is_update=True)
    assert "Never for this site" not in [w.text() for w in upd.findChildren(pm.QPushButton)]


# ---------------------------------------------------------------- modo privado

def test_private_mode_no_capture(tmp_path, monkeypatch):
    m = make_pm(tmp_path)
    monkeypatch.setattr(pm, "_is_private_mode", lambda: True)
    shown = []
    monkeypatch.setattr(m, "_show_save_banner", lambda *a, **k: shown.append(a))
    m._on_credentials_captured("https://a.com", "u", "p")
    assert shown == []

    class FakeBrowser:
        def page(self):
            raise AssertionError("no debe tocarse la página en modo privado")
    m.setup_browser(FakeBrowser())
    assert m._browser_connections == {}


# ---------------------------------------------------------------- WebEngine

LOGIN_HTML = ("<form id=f onsubmit='return false'><input id=u name=username>"
              "<input id=p type=password><button id=go>Log in</button>"
              "<button id=forgot type=button>Forgot password?</button></form>")


class Page:
    """QWebEngineView con el gestor instalado y utilidades de espera."""

    def __init__(self, m):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.m = m
        self.view = QWebEngineView()
        self.view.resize(800, 600)
        self.view.show()
        m.setup_browser(self.view)
        self._loaded = []
        self.view.loadFinished.connect(lambda ok: self._loaded.append(ok))

    def wait(self, ms):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(self, fn, ms=5000):
        for _ in range(ms // 50):
            if fn():
                return True
            self.wait(50)
        return fn()

    def load(self, html, url="https://example.com/login", settle=1200):
        self._loaded.clear()
        self.view.setHtml(html, url)
        if not self.until(lambda: self._loaded, 10000) or not self._loaded[0]:
            pytest.skip("WebEngine no pudo cargar la página en este entorno")
        self.wait(settle)

    def js(self, code, world=0):
        out = []
        self.view.page().runJavaScript(code, world, lambda r: out.append(r))
        self.until(lambda: out)
        return out[0] if out else None

    def values(self, *ids):
        return json.loads(self.js("JSON.stringify([" + ",".join(
            "document.getElementById('%s').value" % i for i in ids) + "])"))

    def click(self, el_id):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint, Qt
        pos = json.loads(self.js(
            "var r=document.getElementById('%s').getBoundingClientRect();"
            "JSON.stringify([r.left+5, r.top+5])" % el_id))
        QTest.mouseClick(self.view.focusProxy() or self.view, Qt.LeftButton,
                         Qt.NoModifier, QPoint(int(pos[0]), int(pos[1])))

    def submit(self, form="f"):
        self.js("document.getElementById('%s').dispatchEvent(new Event('submit')); 1" % form)

    def close(self):
        self.view.close()


@pytest.fixture
def page(tmp_path):
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
        from PySide6.QtTest import QTest  # noqa: F401
    except Exception:
        pytest.skip("Qt WebEngine no disponible")
    m = make_pm(tmp_path)
    p = Page(m)
    yield p
    p.close()


def test_webengine_isolated_world_and_gesture_autofill(page, monkeypatch):
    """Extremo a extremo: canal aislado, relleno solo con clic real."""
    m = page.m
    m.save_password("https://example.com", "alice", "s3cret")
    monkeypatch.setattr(pm.PasswordManager, "_auto_fill_allowed",
                        staticmethod(lambda b, c: False))
    captured = []
    monkeypatch.setattr(m, "_on_credentials_captured",
                        lambda o, u, p, **k: captured.append((o, u, p, k.get("kind"))))
    page.load(LOGIN_HTML)

    main = json.loads(page.js("JSON.stringify({qt: typeof qt, k: typeof window.__katphi,"
                              " f: typeof window.__katphiFill})"))
    assert main == {"qt": "undefined", "k": "undefined", "f": "undefined"}
    assert page.js("!!window.__katphi && window.__katphiHasCreds", pm._APP_WORLD) is True
    # Sin gesto: nada rellenado; un mousedown sintético de la página tampoco rellena
    page.js("document.getElementById('p').dispatchEvent(new MouseEvent('mousedown',{bubbles:true})); 1")
    page.wait(800)
    assert page.values("p") == [""]

    page.click("p")
    assert page.until(lambda: page.values("u", "p") == ["alice", "s3cret"])

    # Ataque desde la página: no hay canal en el main world
    res = page.js("try{window.__katphi.onCredential('{}'); 'ok'}catch(e){'blocked'}")
    assert res == "blocked"
    # Captura normal: el origen viene de la URL real
    page.js("document.getElementById('p').value='newpw'; 1")
    page.submit()
    assert page.until(lambda: captured)
    assert captured == [("https://example.com", "alice", "newpw", "login")]


def test_webengine_autofill_on_load_single_account(page):
    page.m.save_password("https://example.com", "alice", "s3cret")
    page.load(LOGIN_HTML)
    assert page.until(lambda: page.values("u", "p") == ["alice", "s3cret"])


def test_webengine_no_autofill_on_load_with_two_accounts_or_http(page):
    page.m.save_password("https://example.com", "alice", "1")
    page.m.save_password("https://example.com", "bob", "2")
    page.load(LOGIN_HTML)
    page.wait(1500)
    assert page.values("u", "p") == ["", ""]
    page.m.save_password("http://plain.example", "alice", "1")
    page.load(LOGIN_HTML, "http://plain.example/login")
    page.wait(1500)
    assert page.values("u", "p") == ["", ""]


def test_webengine_account_chooser(page):
    m = page.m
    m.save_password("https://example.com", "alice", "1")
    m.save_password("https://example.com", "bob", "2")
    page.load(LOGIN_HTML)
    page.click("u")
    assert page.until(lambda: m._account_menu is not None)
    acts = m._account_menu.actions()
    assert sorted(a.text() for a in acts) == ["alice", "bob"]
    next(a for a in acts if a.text() == "bob").trigger()
    m._account_menu.close() if m._account_menu else None
    assert page.until(lambda: page.values("u", "p") == ["bob", "2"])


def test_webengine_spa_success_shows_banner(page, monkeypatch):
    shown = _record_banner(page.m, monkeypatch)
    page.load(LOGIN_HTML)
    page.js("document.getElementById('u').value='alice';"
            "document.getElementById('p').value='pw1';"
            "document.getElementById('f').addEventListener('submit', function(){"
            " setTimeout(function(){document.getElementById('f').remove();}, 200);}); 1")
    page.submit()
    page.wait(400)
    assert shown == []                    # aún pendiente
    assert page.until(lambda: shown)
    assert shown == [("https://example.com", "alice", "pw1", False)]


def test_webengine_failed_login_is_discarded(page, monkeypatch):
    shown = _record_banner(page.m, monkeypatch)
    page.load(LOGIN_HTML)
    page.js("document.getElementById('u').value='alice';"
            "document.getElementById('p').value='mal'; 1")
    page.submit()
    assert page.until(lambda: page.m._pending)
    page.load(LOGIN_HTML + "<p>Wrong password</p>", settle=1800)   # vuelve el formulario
    assert shown == [] and not page.m._pending


def test_webengine_navigation_success_shows_banner(page, monkeypatch):
    shown = _record_banner(page.m, monkeypatch)
    page.load(LOGIN_HTML)
    page.js("document.getElementById('u').value='alice';"
            "document.getElementById('p').value='pw1'; 1")
    page.click("go")
    assert page.until(lambda: page.m._pending)
    page.load("<h1>Welcome</h1>", "https://example.com/home", settle=200)
    assert page.until(lambda: shown)
    assert shown == [("https://example.com", "alice", "pw1", False)]


def test_webengine_forgot_button_does_not_capture(page, monkeypatch):
    shown = _record_banner(page.m, monkeypatch)
    page.load(LOGIN_HTML)
    page.js("document.getElementById('u').value='alice';"
            "document.getElementById('p').value='pw1'; 1")
    page.click("forgot")
    page.wait(800)
    assert not page.m._pending and shown == []


def test_webengine_multistep_login(page, monkeypatch):
    shown = _record_banner(page.m, monkeypatch)
    page.load("<form id=f onsubmit='return false'><input id=u type=email name=identifier>"
              "<button>Next</button></form>", "https://example.com/signin")
    page.js("document.getElementById('u').value='alice@example.com'; 1")
    page.submit()
    assert page.until(lambda: page.m._step_usernames)
    page.load("<form id=f onsubmit='return false'><input id=p type=password>"
              "<button>Sign in</button></form>", "https://example.com/signin/pwd")
    page.js("document.getElementById('p').value='pw2'; 1")
    page.submit()
    assert page.until(lambda: page.m._pending)
    assert page.m._pending[id(page.view)]["username"] == "alice@example.com"
    page.load("<h1>Inbox</h1>", "https://example.com/inbox", settle=200)
    assert page.until(lambda: shown)
    assert shown == [("https://example.com", "alice@example.com", "pw2", False)]


def test_webengine_multistep_autofill(page):
    m = page.m
    m.save_password("https://example.com", "alice", "1")
    m.save_password("https://example.com", "bob", "2")
    page.load("<form id=f onsubmit='return false'><input id=u name=username>"
              "<button>Next</button></form>", "https://example.com/signin")
    page.click("u")
    assert page.until(lambda: m._account_menu is not None)
    next(a for a in m._account_menu.actions() if a.text() == "bob").trigger()
    assert page.until(lambda: page.values("u") == ["bob"])
    page.load("<form id=f onsubmit='return false'><input id=p type=password>"
              "<button>Sign in</button></form>", "https://example.com/signin/pwd")
    page.click("p")
    assert page.until(lambda: page.values("p") == ["2"])


def test_webengine_change_password_form(page, monkeypatch):
    m = page.m
    m.save_password("https://example.com", "alice", "old1")
    m.save_password("https://example.com", "bob", "old2")
    _record_banner(m, monkeypatch)
    page.load("<form id=f onsubmit='return false'>"
              "<input id=c type=password autocomplete=current-password>"
              "<input id=n type=password autocomplete=new-password>"
              "<input id=r type=password autocomplete=new-password>"
              "<button>Change</button></form>", "https://example.com/settings")
    page.js("document.getElementById('c').value='old2';"
            "document.getElementById('n').value='nueva';"
            "document.getElementById('r').value='nueva'; 1")
    page.submit()
    assert page.until(lambda: m._pending)
    pend = m._pending[id(page.view)]
    assert (pend["username"], pend["password"], pend["is_update"]) == ("bob", "nueva", True)


def test_webengine_signup_form_not_autofilled(page, monkeypatch):
    m = page.m
    m.save_password("https://example.com", "alice", "1")
    _record_banner(m, monkeypatch)
    page.load("<form id=f onsubmit='return false'><input id=u type=email name=email>"
              "<input id=p1 type=password><input id=p2 type=password>"
              "<button>Create account</button></form>", "https://example.com/join")
    page.click("p1")
    page.wait(1200)
    assert page.values("u", "p1", "p2") == ["", "", ""]
    page.js("document.getElementById('u').value='new@example.com';"
            "document.getElementById('p1').value='s1';"
            "document.getElementById('p2').value='s1'; 1")
    page.submit()
    assert page.until(lambda: m._pending)
    pend = m._pending[id(page.view)]
    assert (pend["username"], pend["password"], pend["is_update"]) == ("new@example.com", "s1", False)


# ---------------------------------------------------------------- fase 2: iframes, http, llave

def test_insecure_origin():
    assert pm._is_insecure_origin("http://example.com")
    assert not pm._is_insecure_origin("https://example.com")
    for local in ("http://localhost:8080", "http://127.0.0.1:5000", "http://app.localhost"):
        assert not pm._is_insecure_origin(local)


def test_page_credentials_fall_back_to_http(tmp_path):
    m = make_pm(tmp_path)
    m.save_password("http://example.com", "alice", "1")
    assert [c["username"] for c in m._page_credentials("https://example.com")] == ["alice"]
    assert m._page_credentials("https://other.com") == []
    m.save_password("https://example.com", "bob", "2")
    assert [c["username"] for c in m._page_credentials("https://example.com")] == ["bob"]


def test_page_flags(tmp_path):
    m = make_pm(tmp_path)
    assert m._page_flags("https://a.com") == {"has": False, "auto": False}
    m.save_password("https://a.com", "u", "p")
    assert m._page_flags("https://a.com") == {"has": True, "auto": True}
    m.save_password("http://b.com", "u", "p")
    assert m._page_flags("http://b.com") == {"has": True, "auto": False}


def test_hello_slot_returns_flags():
    r = pm.CredentialReceiver(None, origin_getter=lambda: "https://a.com/x",
                              flags_getter=lambda o: {"has": o == "https://a.com", "auto": 1})
    assert json.loads(r.hello("{}")) == {"has": True, "auto": True}
    r2 = pm.CredentialReceiver(None, origin_getter=lambda: "file:///x",
                               flags_getter=lambda o: {"has": True, "auto": True})
    assert json.loads(r2.hello("{}")) == {"has": False, "auto": False}


def test_page_ready_ignores_same_document(tmp_path, monkeypatch):
    m = make_pm(tmp_path)
    shown = _record_banner(m, monkeypatch)
    b = FakeBrowser("https://a.com/")
    m._on_credentials_captured("https://a.com", "u", "p", browser=b, doc="d1")
    m._on_page_ready(b, "https://a.com", "d1", False)    # la propia página del envío
    assert shown == [] and id(b) in m._pending
    m._on_page_ready(b, "https://a.com", "d2", True)     # vuelve a pedir login
    assert shown == [] and id(b) not in m._pending
    m._on_credentials_captured("https://a.com", "u", "p", browser=b, doc="d2")
    m._on_page_ready(b, "https://a.com", "d3", False)
    assert shown == [("https://a.com", "u", "p", False)]


FRAME_LOGIN = ("<body style='margin:0'><form id=f onsubmit='return false'>"
               "<input id=u name=username style='position:absolute;left:0;top:0;width:200px;height:30px'>"
               "<input id=p type=password style='position:absolute;left:0;top:40px;width:200px;height:30px'>"
               "</form></body>")


@pytest.fixture
def http_server():
    import threading
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    pages = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path.split("?")[0], "<p>404</p>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], pages
    srv.shutdown()


def _click_at(page, x, y):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint, Qt
    QTest.mouseClick(page.view.focusProxy() or page.view, Qt.LeftButton,
                     Qt.NoModifier, QPoint(int(x), int(y)))


def test_webengine_same_origin_iframe(page, http_server, monkeypatch):
    port, pages = http_server
    origin = f"http://127.0.0.1:{port}"
    pages["/"] = ("<body style='margin:0'><iframe id=fr src='/frame' "
                  "style='position:absolute;left:100px;top:100px;width:300px;height:200px;border:0'>"
                  "</iframe></body>")
    pages["/frame"] = FRAME_LOGIN
    m = page.m
    m.save_password(origin, "alice", "s3cret")
    page._loaded.clear()
    page.view.load(pm.QUrl(f"{origin}/"))
    assert page.until(lambda: page._loaded, 10000)
    page.wait(1500)
    fv = lambda: json.loads(page.js(
        "var d=document.getElementById('fr').contentDocument;"
        "JSON.stringify([d.getElementById('u').value, d.getElementById('p').value])"))
    _click_at(page, 100 + 10, 100 + 50)            # campo de contraseña del iframe
    assert page.until(lambda: fv() == ["alice", "s3cret"])

    # Captura desde el iframe: se atribuye al origen de la pestaña
    shown = _record_banner(m, monkeypatch)
    page.js("var d=document.getElementById('fr').contentDocument;"
            "d.getElementById('p').value='nueva';"
            "d.getElementById('f').dispatchEvent(new Event('submit')); 1")
    assert page.until(lambda: m._pending)
    assert m._pending[id(page.view)]["origin"] == origin
    assert m._pending[id(page.view)]["password"] == "nueva"


def test_webengine_cross_origin_iframe_is_inert(page, http_server):
    port, pages = http_server
    origin = f"http://127.0.0.1:{port}"
    pages["/"] = (f"<body style='margin:0'><iframe id=fr src='http://localhost:{port}/frame' "
                  "style='position:absolute;left:100px;top:100px;width:300px;height:200px;border:0'>"
                  "</iframe></body>")
    pages["/frame"] = FRAME_LOGIN
    m = page.m
    m.save_password(origin, "alice", "s3cret")
    m.save_password(f"http://localhost:{port}", "bob", "otra")
    page._loaded.clear()
    page.view.load(pm.QUrl(f"{origin}/"))
    assert page.until(lambda: page._loaded, 10000)
    page.wait(1500)
    _click_at(page, 100 + 10, 100 + 50)
    page.wait(1500)
    assert m._account_menu is None
    # El iframe de otro origen no puede rellenarse ni hablar con Python: el
    # frame principal no recibió ninguna petición ni hay nada pendiente
    assert page.js("window.__katphiFillFrame === null", pm._APP_WORLD) is True
    assert not m._pending


def test_webengine_works_without_loadfinished(page):
    """Regresión: main_window cortaba page.loadFinished con disconnect()."""
    import warnings
    page.m.save_password("https://example.com", "alice", "s3cret")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        page.view.page().loadFinished.disconnect()
    page.view.setHtml(LOGIN_HTML, pm.QUrl("https://example.com/login"))
    assert page.until(lambda: (page.js("document.getElementById('p') && "
                                       "document.getElementById('p').value") == "s3cret"), 8000)


def test_webengine_http_always_asks_with_warning(page):
    m = page.m
    m.save_password("http://plain.example", "alice", "1")
    page.load(LOGIN_HTML, "http://plain.example/login")
    page.click("p")
    assert page.until(lambda: m._account_menu is not None)
    acts = m._account_menu.actions()
    assert not acts[0].isEnabled() and "Not secure" in acts[0].text()
    assert page.values("p") == [""]
    next(a for a in acts if a.text() == "alice").trigger()
    assert page.until(lambda: page.values("u", "p") == ["alice", "1"])


def test_webengine_https_uses_http_credentials(page):
    page.m.save_password("http://example.com", "alice", "viejo")
    page.load(LOGIN_HTML)
    assert page.until(lambda: page.values("u", "p") == ["alice", "viejo"])


def test_key_icon_and_menu(page, monkeypatch):
    from PySide6.QtWidgets import QLineEdit
    m = page.m
    bar = QLineEdit()
    m.attach_url_bar(bar, lambda: page.view)
    assert m._key_action is not None and not m._key_action.isVisible()

    m.save_password("https://example.com", "alice", "1")
    m.save_password("https://example.com", "bob", "2")
    page.load(LOGIN_HTML)
    m.refresh_key_icon()
    assert m._key_action.isVisible()
    assert "2" in m._key_action.toolTip()

    menu = m._build_key_menu(page.view, "https://example.com")
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[0] == "Fill in:" and texts[-1] == "Manage passwords"
    assert sorted(texts[1:-1]) == ["alice", "bob"]
    next(a for a in menu.actions() if a.text() == "bob").trigger()
    assert page.until(lambda: page.values("u", "p") == ["bob", "2"])

    # Banner descartado: la llave permite guardarla después
    monkeypatch.setattr(m, "_find_main_window", lambda: None)
    m._unsaved[id(page.view)] = {"origin": "https://example.com", "username": "carol",
                                 "password": "3", "is_update": False, "t": pm.time.monotonic()}
    menu = m._build_key_menu(page.view, "https://example.com")
    save = next(a for a in menu.actions() if a.text() == "Save password for carol")
    save.trigger()
    assert m.get_password("https://example.com", "carol") == "3"
    assert id(page.view) not in m._unsaved

    # Otra web: sin cuentas ni nada pendiente, no hay llave
    page.load("<p>x</p>", "https://nothing.example/")
    m.refresh_key_icon()
    assert not m._key_action.isVisible()


def test_dismissed_banner_is_kept_for_key(tmp_path, monkeypatch):
    m = make_pm(tmp_path)
    inserted = []
    monkeypatch.setattr(m, "_find_main_window", lambda: object())
    monkeypatch.setattr(m, "_insert_banner_in_layout", lambda w, b: inserted.append(b))
    b = FakeBrowser("https://a.com/")
    m._show_save_banner("https://a.com", "u", "p", False, browser=b)
    inserted[0]._on_dismiss()
    assert m._unsaved[id(b)]["username"] == "u"
    m._on_url_changed(b, "https://other.com/")
    assert id(b) not in m._unsaved
