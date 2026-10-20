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
    r.credential_received.connect(lambda o, u, p: got.append((o, u, p)))
    return r, got


def test_on_credential_ignores_payload_origin():
    r, got = _receiver("https://real.example/login?next=/")
    r.onCredential(json.dumps({"origin": "https://bank.com",
                               "username": "x", "password": "y"}))
    assert got == [("https://real.example", "x", "y")]


@pytest.mark.parametrize("payload", [
    "no es json",
    json.dumps(["x", "y"]),
    json.dumps({"username": 1, "password": "y"}),
    json.dumps({"username": "x", "password": ""}),
    json.dumps({"username": "x", "password": "p" * (pm._MAX_PASSWORD_LEN + 1)}),
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


def test_request_autofill_uses_real_origin():
    r = pm.CredentialReceiver(None, origin_getter=lambda: "https://real.example/a")
    got = []
    r.autofill_requested.connect(lambda o, t: got.append((o, t)))
    r.requestAutofill(json.dumps({"username": "alice", "origin": "https://bank.com"}))
    r.requestAutofill(json.dumps({"username": "alice"}))   # limitado por frecuencia
    assert got == [("https://real.example", "alice")]


def test_choose_credential():
    creds = [{"username": "new", "password": "1"}, {"username": "old", "password": "2"}]
    assert pm.PasswordManager._choose_credential(creds, "")["username"] == "new"
    assert pm.PasswordManager._choose_credential(creds, "old")["username"] == "old"
    assert pm.PasswordManager._choose_credential(creds, "otro") is None
    assert pm.PasswordManager._choose_credential([], "") is None


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

def test_webengine_isolated_world_and_gesture_autofill(tmp_path):
    """Extremo a extremo: canal aislado, relleno solo con clic real."""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QEventLoop, QPoint, QTimer, Qt
    except Exception:
        pytest.skip("Qt WebEngine no disponible")

    m = make_pm(tmp_path)
    m.save_password("https://example.com", "alice", "s3cret")
    captured = []
    m._on_credentials_captured = lambda o, u, p: captured.append((o, u, p))

    view = QWebEngineView()
    view.resize(800, 600)
    view.show()
    m.setup_browser(view)

    def wait(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def js(code, world=0):
        out = []
        view.page().runJavaScript(code, world, lambda r: out.append(r))
        for _ in range(100):
            if out:
                break
            wait(50)
        return out[0] if out else None

    loaded = []
    view.loadFinished.connect(lambda ok: loaded.append(ok))
    view.setHtml("<form id=f onsubmit='return false'><input id=u name=username>"
                 "<input id=p type=password></form>", "https://example.com/login")
    for _ in range(200):
        if loaded:
            break
        wait(50)
    if not loaded or not loaded[0]:
        pytest.skip("WebEngine no pudo cargar la página en este entorno")
    wait(1200)

    main = json.loads(js("JSON.stringify({qt: typeof qt, k: typeof window.__katphi,"
                         " f: typeof window.__katphiFill})"))
    assert main == {"qt": "undefined", "k": "undefined", "f": "undefined"}
    assert js("!!window.__katphi && window.__katphiHasCreds", pm._APP_WORLD) is True
    # Sin gesto: nada rellenado; un mousedown sintético de la página tampoco rellena
    js("document.getElementById('p').dispatchEvent(new MouseEvent('mousedown',{bubbles:true})); 1")
    wait(800)
    assert js("document.getElementById('p').value") == ""

    pos = json.loads(js("var r=document.getElementById('p').getBoundingClientRect();"
                        "JSON.stringify([r.left+5, r.top+5])"))
    QTest.mouseClick(view.focusProxy() or view, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(pos[0]), int(pos[1])))
    wait(1500)
    assert json.loads(js("JSON.stringify([document.getElementById('u').value,"
                         " document.getElementById('p').value])")) == ["alice", "s3cret"]

    # Ataque desde la página: no hay canal en el main world
    res = js("try{window.__katphi.onCredential('{}'); 'ok'}catch(e){'blocked'}")
    assert res == "blocked"
    # Captura normal: el origen viene de la URL real
    js("document.getElementById('p').value='newpw';"
       "document.getElementById('f').dispatchEvent(new Event('submit')); 1")
    wait(1000)
    assert captured == [("https://example.com", "alice", "newpw")]
    view.close()
