"""Arranque como un navegador normal (2026-11-02).

- La sesión anterior no se reabre sola; restaurarla a petición no duplica
  pestañas y sustituye la pestaña de inicio sin usar.
- Abrir y cerrar sin navegar no machaca la sesión anterior guardada.
- Tor es solo de sesión: nunca se guarda enabled: true en config.yaml.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest
import yaml
from PySide6.QtWidgets import QApplication, QMainWindow

try:
    import PySide6.QtWebEngineWidgets  # noqa: F401
except Exception:  # pragma: no cover
    pytest.skip("Qt WebEngine no disponible", allow_module_level=True)

import tabs


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _History:
    def record_history(self, url):
        pass


@pytest.fixture
def tm(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tabs, "_is_private_mode", lambda: False)
    monkeypatch.setattr(tabs.TabManager, "SESSION_FILE", str(tmp_path / "tab_session.json"))
    window = QMainWindow()
    manager = tabs.TabManager(_History(), window)
    window.setCentralWidget(manager.tabs)
    yield manager
    for i in range(manager.tabs.count() - 1, -1, -1):
        view = manager.tabs.widget(i)
        manager.tabs.removeTab(i)
        manager._destroy_browser(view)
    window.deleteLater()
    qapp.processEvents()


def _write_session(tm, n):
    urls = [f"data:text/html,tab{i}" for i in range(n)]
    with open(tm.SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump([{"url": u} for u in urls], f)
    return urls


def _urls(tm):
    return [tm.tab_url(tm.tabs.widget(i)) for i in range(tm.tabs.count())]


def test_restore_replaces_start_tab_without_duplicates(tm):
    urls = _write_session(tm, 5)
    tm.add_new_tab()                       # pestaña de inicio del arranque
    assert tm.saved_session_count() == 5
    assert tm.restaurar_sesion() is True
    assert _urls(tm) == urls               # 5, no 6 ni 10
    # Pedirlo otra vez no duplica nada
    assert tm.restaurar_sesion() is False
    assert _urls(tm) == urls


def test_restore_keeps_tabs_the_user_opened(tm):
    urls = _write_session(tm, 3)
    tm.add_new_tab("data:text/html,mine")
    tm.add_new_tab(urls[0])                # ya abierta: no se repite
    tm.restaurar_sesion()
    got = _urls(tm)
    assert got.count(urls[0]) == 1
    assert "data:text/html,mine" in got
    assert len(got) == 4


def test_close_without_browsing_keeps_previous_session(tm):
    urls = _write_session(tm, 5)
    tm.add_new_tab()                       # arranca y se cierra sin navegar
    tm.guardar_sesion()
    with open(tm.SESSION_FILE, encoding="utf-8") as f:
        assert [t["url"] for t in json.load(f)] == urls


def test_close_after_browsing_saves_current_tabs(tm):
    _write_session(tm, 5)
    tm.add_new_tab("data:text/html,new")
    tm.guardar_sesion()
    with open(tm.SESSION_FILE, encoding="utf-8") as f:
        assert [t["url"] for t in json.load(f)] == ["data:text/html,new"]


def test_tor_is_session_only(tmp_path, monkeypatch):
    import config_manager
    monkeypatch.delenv(config_manager.TOR_SESSION_ENV, raising=False)
    cfg = config_manager.config
    monkeypatch.setattr(cfg, "config_file", tmp_path / "config.yaml")
    # Config antigua con Tor guardado como activado: se ignora
    cfg._config.setdefault("tor", {})["enabled"] = True
    assert cfg.is_tor_enabled() is False
    cfg.set_tor_enabled(True)              # relanzamiento "con Tor"
    assert cfg.is_tor_enabled() is True
    cfg.persist_config()
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["tor"]["enabled"] is False
    cfg.set_tor_enabled(False)
    assert cfg.is_tor_enabled() is False
