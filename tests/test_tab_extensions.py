"""Tests de los puntos de extensión de las pestañas (tabs.TabExtensions).

Perfil por pestaña, datos de pestaña guardados con la sesión, pestañas en
espera de perfil, filtros de navegación, menús y decoración. Se ejecutan con
QT_QPA_PLATFORM=offscreen sin red (about:blank y data:).
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu

try:
    # WebEngine exige este import antes de crear la QApplication
    import PySide6.QtWebEngineWidgets  # noqa: F401
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
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
    monkeypatch.chdir(tmp_path)   # TabGroupManager escribe tab_groups.json aquí
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


@pytest.fixture
def container_profile(qapp):
    profile = QWebEngineProfile(qapp)  # off-the-record: no deja nada en disco
    yield profile


def test_new_tab_uses_given_profile_and_custom_page(tm, container_profile):
    view = tm.add_new_tab("about:blank", profile=container_profile,
                          extra={"profile_key": "container:work", "note": 1})
    assert isinstance(view.page(), tabs.KatphiWebPage)
    assert view.page().profile() is container_profile
    assert view.tab_extra == {"profile_key": "container:work", "note": 1}
    default_view = tm.add_new_tab("about:blank")
    assert default_view.page().profile() is QWebEngineProfile.defaultProfile()
    assert default_view.tab_extra == {}


def test_create_window_inherits_profile_and_profile_key(tm, container_profile):
    view = tm.add_new_tab("about:blank", profile=container_profile,
                          extra={"profile_key": "container:work", "other": "x"})
    child = view.createWindow(QWebEnginePage.WebWindowType.WebBrowserTab)
    assert child.page().profile() is container_profile
    assert child.tab_extra == {"profile_key": "container:work"}


def test_pending_tab_waits_for_resolver(tm, container_profile, qapp):
    url = "data:text/html,hola"
    view = tm.add_new_tab(url, extra={"profile_key": "container:work"})
    assert view.pending_url == url
    assert view.page().profile() is QWebEngineProfile.defaultProfile()
    assert tm.tab_url(view) == url

    calls = []

    def resolver(extra):
        calls.append(extra)
        return container_profile if extra.get("profile_key") == "container:work" else None

    tm.extensions.register("profile_resolver", resolver)
    assert calls, "registrar un resolver debe resolver las pestañas en espera"
    assert view.pending_url is None
    assert view.page().profile() is container_profile
    assert view.url() == QUrl(url)
    tm.extensions.unregister("profile_resolver", resolver)


def test_resolver_used_on_creation(tm, container_profile):
    tm.extensions.register("profile_resolver", lambda extra: container_profile)
    view = tm.add_new_tab("about:blank", extra={"profile_key": "container:x"})
    assert view.pending_url is None
    assert view.page().profile() is container_profile


def test_navigation_filter_cancels_main_frame(tm):
    seen = []

    def filt(browser, url, nav_type):
        seen.append((browser, url.toString()))
        return url.host() == "blocked.invalid"

    tm.extensions.register("navigation_filter", filt)
    view = tm.add_new_tab("about:blank")
    page = view.page()
    nav = QWebEnginePage.NavigationType.NavigationTypeLinkClicked
    assert page.acceptNavigationRequest(QUrl("https://blocked.invalid/"), nav, True) is False
    assert page.acceptNavigationRequest(QUrl("https://ok.invalid/"), nav, True) is True
    # Los subframes no pasan por los filtros
    before = len(seen)
    assert page.acceptNavigationRequest(QUrl("https://blocked.invalid/"), nav, False) is True
    assert len(seen) == before
    assert all(b is view for b, _ in seen)


def test_failing_extension_is_ignored(tm):
    def broken(*args):
        raise RuntimeError("boom")

    for kind in ("navigation_filter", "tab_setup_hook", "tab_decorator"):
        tm.extensions.register(kind, broken)
    view = tm.add_new_tab("about:blank")
    assert view is not None
    nav = QWebEnginePage.NavigationType.NavigationTypeTyped
    assert view.page().acceptNavigationRequest(QUrl("https://a.invalid/"), nav, True) is True


def test_setup_hook_runs_before_load(tm, container_profile):
    seen = []
    tm.extensions.register("tab_setup_hook",
                           lambda browser, profile: seen.append((browser.url().toString(), profile)))
    tm.add_new_tab("about:blank", profile=container_profile)
    assert seen and seen[-1] == ("", container_profile)


def test_session_round_trip_keeps_extra(tm, container_profile):
    tm.add_new_tab("about:blank")
    tm.add_new_tab("data:text/html,a", profile=container_profile,
                   extra={"profile_key": "container:work"})
    pending = tm.add_new_tab("data:text/html,b", extra={"profile_key": "container:gone"})
    assert pending.pending_url
    tm.guardar_sesion()
    with open(tm.SESSION_FILE, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved[1] == {"url": "data:text/html,a", "extra": {"profile_key": "container:work"}}
    # Una pestaña en espera guarda su URL real, no el aviso
    assert saved[2] == {"url": "data:text/html,b", "extra": {"profile_key": "container:gone"}}

    tm.extensions.register(
        "profile_resolver",
        lambda extra: container_profile if extra.get("profile_key") == "container:work" else None)
    assert tm.restaurar_sesion() is True
    views = [tm.tabs.widget(i) for i in range(tm.tabs.count())]
    work = [v for v in views if v.tab_extra.get("profile_key") == "container:work"]
    assert len(work) == 1 and work[0].page().profile() is container_profile
    gone = [v for v in views if v.tab_extra.get("profile_key") == "container:gone"]
    assert len(gone) == 1 and gone[0].pending_url == "data:text/html,b"


def test_duplicate_and_reopen_keep_container(tm, container_profile):
    tm.add_new_tab("about:blank")
    view = tm.add_new_tab("about:blank", profile=container_profile,
                          extra={"profile_key": "container:work"})
    index = tm.tabs.indexOf(view)
    dup = tm.duplicate_tab(index)
    assert dup.page().profile() is container_profile
    assert dup.tab_extra == {"profile_key": "container:work"}

    tm.extensions.register("profile_resolver", lambda extra: container_profile)
    tm.close_tab(tm.tabs.indexOf(dup))
    reopened = tm.reopen_closed_tab()
    assert reopened.tab_extra == {"profile_key": "container:work"}
    assert reopened.page().profile() is container_profile


def test_tab_decorator_and_menu_provider(tm):
    view = tm.add_new_tab("about:blank")
    index = tm.tabs.indexOf(view)

    def deco(i, browser):
        return {"prefix": "■", "color": "#ff0000", "tooltip": "Trabajo"} if browser is view else None

    tm.extensions.register("tab_decorator", deco)
    assert tm.tabs.tabText(index).startswith("■ ")
    assert tm.tabs.tabBar().tabTextColor(index).name() == "#ff0000"
    assert tm.tabs.tabToolTip(index) == "Trabajo"
    tm.extensions.unregister("tab_decorator", deco)
    assert not tm.tabs.tabText(index).startswith("■")
    assert tm.tabs.tabToolTip(index) == ""

    calls = []
    tm.extensions.register("tab_menu_provider",
                           lambda menu, i, browser: calls.append((i, browser)) or menu.addAction("X"))
    menu = QMenu()
    tm.extensions.populate_tab_menu(menu, index, view)
    assert calls == [(index, view)]
    assert [a.text() for a in menu.actions()] == ["X"]


def test_unknown_extension_kind_rejected(tm):
    with pytest.raises(ValueError):
        tm.extensions.register("nope", lambda: None)
