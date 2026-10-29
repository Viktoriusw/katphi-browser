"""
Aviso de vídeo no reproducible por falta de códecs H.264/AAC.

El Qt WebEngine de PySide6 (pip) se compila sin códecs propietarios: no
reproduce H.264, AAC ni HEVC. YouTube funciona porque sirve VP9/AV1 + Opus,
pero casi todas las demás webs solo ofrecen MP4/HLS con H.264 y el vídeo
falla sin explicación. Katphi no distribuye binarios con códecs patentados
(ver AVISO_LEGAL.md), así que detecta el fallo y ofrece verlo en el
reproductor integrado (native_player.py, con los decodificadores del sistema
operativo) o abrirlo fuera del navegador. El aviso no remite a compilar
códecs: esa opción solo se documenta en el README y en los scripts, con su aviso legal.

Detección (sin tocar nada si el motor sí tiene H.264):
  - MainWorld: envoltorio pasivo de MediaSource.isTypeSupported y
    canPlayType que avisa con un evento DOM cuando la página pide H.264/AAC
    y el motor dice que no (los reproductores HLS/DASH fallan así, sin
    error en el <video>).
  - ApplicationWorld: escucha ese evento y los errores de <video>/<audio>
    (MEDIA_ERR_SRC_NOT_SUPPORTED), también en iframes, y expone un estado
    que Python consulta cada pocos segundos en la pestaña visible.
"""

import logging
import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, QTimer, QEvent, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QStyle, QToolButton)

logger = logging.getLogger(__name__)

_APP_WORLD = int(QWebEngineScript.ScriptWorldId.ApplicationWorld)
_HOOK_SCRIPT_NAME = "katphi-media-hook"
_DETECT_SCRIPT_NAME = "katphi-media-detect"

# El motor tiene H.264: se sabe tras la primera consulta y desactiva todo
_codecs_available = None

_HOOK_JS = r"""
(function () {
    'use strict';
    var RX = /avc1|avc3|mp4a|hvc1|hev1|^video\/mp4|^audio\/mp4|^audio\/aac/i;
    var sent = false;
    function miss() {
        if (sent) { return; }
        sent = true;
        try { document.dispatchEvent(new Event('katphi-codec-miss')); } catch (e) {}
    }
    function wrap(obj, name) {
        var orig = obj && obj[name];
        if (typeof orig !== 'function') { return; }
        var w = function (t) {
            var r = orig.apply(this, arguments);
            if (!r && typeof t === 'string' && RX.test(t)) { miss(); }
            return r;
        };
        try {
            Object.defineProperty(w, 'name', { value: orig.name });
            Object.defineProperty(w, 'toString', {
                value: function () { return Function.prototype.toString.call(orig); }
            });
        } catch (e) {}
        try { obj[name] = w; } catch (e) {}
    }
    if (window.MediaSource) { wrap(window.MediaSource, 'isTypeSupported'); }
    if (window.ManagedMediaSource) { wrap(window.ManagedMediaSource, 'isTypeSupported'); }
    if (window.HTMLMediaElement) { wrap(window.HTMLMediaElement.prototype, 'canPlayType'); }
})();
"""

_DETECT_JS = r"""
(function () {
    'use strict';
    if (window.__katphiMedia) { return; }
    var isTop = (window.top === window);
    var st = { miss: 0, unsupported: false, frame: false, src: '' };

    function mediaOf(t) {
        if (!t || !t.tagName) { return null; }
        if (t.tagName === 'VIDEO' || t.tagName === 'AUDIO') { return t; }
        if (t.tagName === 'SOURCE') { return t.parentElement; }
        return null;
    }
    function httpSrc(m) {
        var s = (m && m.currentSrc) || '';
        if (!s && m) {
            var so = m.querySelector('source[src]');
            s = so ? so.src : '';
        }
        return /^https?:/i.test(s) ? s : '';
    }
    function anyPlaying() {
        var vs = document.querySelectorAll('video');
        for (var i = 0; i < vs.length; i++) {
            if (vs[i].readyState >= 2) { return true; }
        }
        return false;
    }
    function stuckVideo() {
        var vs = document.querySelectorAll('video');
        if (!vs.length || anyPlaying()) { return null; }
        return vs[0];
    }
    function failed() {
        if (st.unsupported) { return true; }
        // Pidió H.264 hace más de 4 s y ningún vídeo ha llegado a tener imagen
        return !!(st.miss && (Date.now() - st.miss) > 4000 && stuckVideo());
    }
    function notifyTop() {
        if (isTop) { return; }
        try { window.top.postMessage({ __katphiMedia: 'unsupported' }, '*'); } catch (e) {}
    }
    function markUnsupported(m) {
        st.unsupported = true;
        st.src = st.src || httpSrc(m);
        notifyTop();
    }

    document.addEventListener('error', function (e) {
        var m = mediaOf(e.target);
        if (!m) { return; }
        setTimeout(function () {
            // 4 = MEDIA_ERR_SRC_NOT_SUPPORTED; 3 = NETWORK_NO_SOURCE (fallaron todos los <source>)
            if ((m.error && m.error.code === 4) || m.networkState === 3) { markUnsupported(m); }
        }, 0);
    }, true);

    document.addEventListener('katphi-codec-miss', function () {
        if (st.miss) { return; }
        st.miss = Date.now();
        if (!isTop) {
            setTimeout(function () { if (failed()) { notifyTop(); } }, 5000);
        }
    });

    if (isTop) {
        window.addEventListener('message', function (e) {
            if (e && e.data && e.data.__katphiMedia === 'unsupported') { st.frame = true; }
        });
    }

    window.__katphiMedia = {
        report: function () {
            var h264 = false;
            try {
                h264 = !!(window.MediaSource &&
                    MediaSource.isTypeSupported('video/mp4; codecs="avc1.42E01E, mp4a.40.2"'));
            } catch (e) {}
            var bad = !h264 && (failed() || st.frame);
            if (bad && !st.src) { st.src = httpSrc(stuckVideo()); }
            return JSON.stringify({ h264: h264, failed: bad, src: st.src });
        }
    };
})();
"""


def _make_script(name, source, world, subframes=True):
    script = QWebEngineScript()
    script.setName(name)
    script.setSourceCode(source)
    script.setInjectionPoint(QWebEngineScript.DocumentCreation)
    script.setWorldId(world)
    script.setRunsOnSubFrames(subframes)
    return script


def install_scripts(profile):
    """Instala (una vez por perfil) los scripts de detección."""
    if _codecs_available:
        return
    try:
        scripts = profile.scripts()
        if scripts.find(_DETECT_SCRIPT_NAME):
            return
        scripts.insert(_make_script(_HOOK_SCRIPT_NAME, _HOOK_JS,
                                    QWebEngineScript.MainWorld))
        scripts.insert(_make_script(_DETECT_SCRIPT_NAME, _DETECT_JS, _APP_WORLD))
    except Exception as e:
        logger.debug("media_support.install_scripts: %s", e)


def _remove_scripts(profile):
    try:
        scripts = profile.scripts()
        for name in (_HOOK_SCRIPT_NAME, _DETECT_SCRIPT_NAME):
            for existing in scripts.find(name):
                scripts.remove(existing)
    except Exception:
        pass


def _external_players():
    """[(etiqueta, ejecutable, admite_url_de_pagina)] instalados en el sistema."""
    players = []
    mpv = shutil.which("mpv")
    if mpv:
        # mpv abre URLs de página a través de yt-dlp si está instalado
        players.append(("mpv", mpv, bool(shutil.which("yt-dlp") or shutil.which("youtube-dl"))))
    vlc = shutil.which("vlc")
    if vlc:
        players.append(("VLC", vlc, False))
    return players


class MediaFallbackBar(QFrame):
    """Barra sobre la vista web con alternativas para ver el vídeo."""

    def __init__(self, view, page_url, media_src, parent_window):
        super().__init__(view)
        self.setObjectName("mediaFallbackBar")
        self._view = view
        self._page_url = page_url
        self._media_src = media_src
        self._window = parent_window
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "QFrame#mediaFallbackBar { background: palette(window);"
            " border-bottom: 1px solid palette(mid); }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(8)

        label = QLabel(
            "Este vídeo usa H.264/AAC, códecs patentados que Katphi Browser "
            "no incluye por motivos de licencia. Puedes verlo con el reproductor "
            "de Katphi, que usa los decodificadores de tu sistema, o abrirlo fuera:")
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        self._add_native_player_button(layout)

        browser_btn = QPushButton("Abrir en el navegador del sistema")
        browser_btn.clicked.connect(self._open_in_system_browser)
        layout.addWidget(browser_btn)

        for name, exe, page_ok in _external_players():
            target = media_src or (page_url if page_ok else "")
            if not target:
                continue
            btn = QPushButton(f"Abrir con {name}")
            btn.setToolTip(target)
            btn.clicked.connect(lambda _=False, e=exe, t=target: self._open_with_player(e, t))
            layout.addWidget(btn)

        close_btn = QToolButton()
        close_btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        close_btn.setToolTip("Cerrar")
        close_btn.setAutoRaise(True)
        close_btn.clicked.connect(self.dismiss)
        layout.addWidget(close_btn)

        view.installEventFilter(self)
        view.urlChanged.connect(self.dismiss)
        self._place()
        self.show()
        self.raise_()

    def _add_native_player_button(self, layout):
        try:
            import native_player
        except Exception as e:
            logger.debug("native_player no disponible: %s", e)
            return
        available, _reason = native_player.is_available()
        target = self._media_src or (
            self._page_url if native_player.accepts_page_urls() else "")
        if available and not target:
            return
        btn = QPushButton("Reproducir en Katphi")
        if available:
            btn.setToolTip(target)
            btn.clicked.connect(lambda _=False: self._open_native_player(target))
        elif native_player.install_hint():
            btn.setToolTip("Necesita libmpv del sistema")
            btn.clicked.connect(lambda _=False: QMessageBox.information(
                self._window, "Reproductor de Katphi",
                "El reproductor de Katphi usa los decodificadores de vídeo de tu "
                "sistema y aquí no están instalados.\n\n" + native_player.install_hint()))
        else:
            return
        layout.addWidget(btn)

    def _open_native_player(self, target):
        if not self._confirm_leaving("el reproductor de Katphi", tor_only=True):
            return
        import native_player
        try:
            user_agent = self._view.page().profile().httpUserAgent()
        except Exception:
            user_agent = ""
        try:
            native_player.open_player(target, referrer=self._page_url,
                                      user_agent=user_agent, title=self._view.title(),
                                      parent=self._window)
            self.dismiss()
        except Exception as e:
            logger.warning("[MEDIA] Reproductor de Katphi: %s", e)
            QMessageBox.warning(self._window, "Reproductor de Katphi",
                                f"No se pudo abrir el reproductor: {e}")

    def dismiss(self, *_):
        try:
            self._view.urlChanged.disconnect(self.dismiss)
        except (RuntimeError, TypeError):
            pass
        self._view.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def eventFilter(self, obj, event):
        if obj is self._view and event.type() == QEvent.Resize:
            self._place()
        return False

    def _place(self):
        self.setGeometry(0, 0, self._view.width(), self.sizeHint().height())

    def _confirm_leaving(self, what, tor_only=False):
        """Con Tor o en ventana privada, avisar antes de sacar la URL fuera.

        tor_only: el destino no guarda historial (reproductor integrado), así
        que solo importa que su tráfico no pasa por Tor.
        """
        warnings = []
        try:
            import net_proxy
            if net_proxy.is_tor_active():
                warnings.append("se abrirá fuera de Tor, con tu IP real")
        except Exception:
            pass
        try:
            from constants import is_private_mode
            if is_private_mode() and not tor_only:
                warnings.append("quedará en el historial de esa aplicación")
        except Exception:
            pass
        if not warnings:
            return True
        reply = QMessageBox.question(
            self._window, "Reproducir sin Tor" if tor_only else "Abrir fuera de Katphi",
            f"El vídeo se abrirá en {what}: " + " y ".join(warnings) + ".\n\n¿Continuar?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return reply == QMessageBox.Yes

    def _open_in_system_browser(self):
        if not self._confirm_leaving("el navegador del sistema"):
            return
        QDesktopServices.openUrl(QUrl(self._page_url))
        self.dismiss()

    def _open_with_player(self, exe, target):
        if not self._confirm_leaving("un reproductor externo"):
            return
        args = [exe]
        if "mpv" in exe.lower() and self._page_url:
            args.append(f"--referrer={self._page_url}")
        args += ["--", target] if "mpv" in exe.lower() else [target]
        try:
            kwargs = {}
            if sys.platform.startswith("win"):
                kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **kwargs)
            self.dismiss()
        except Exception as e:
            QMessageBox.warning(self._window, "Reproductor externo",
                                f"No se pudo abrir el reproductor: {e}")


class MediaSupportMonitor(QObject):
    """Consulta cada pocos segundos la pestaña visible y muestra la barra."""

    POLL_MS = 3000

    def __init__(self, tab_manager, window):
        super().__init__(window)
        self._tab_manager = tab_manager
        self._window = window
        self._handled = set()  # (id de vista, URL) ya avisadas o descartadas
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        if _codecs_available is not True:
            self._timer.start()

    def stop(self):
        self._timer.stop()

    def _current_view(self):
        try:
            view = self._tab_manager.tabs.currentWidget()
        except Exception:
            return None
        return view if view is not None and hasattr(view, "page") else None

    def _poll(self):
        view = self._current_view()
        if view is None or not self._window.isVisible():
            return
        url = view.url().toString()
        if not url.startswith(("http://", "https://")):
            return
        key = (id(view), url)
        if key in self._handled:
            return
        try:
            view.page().runJavaScript(
                "window.__katphiMedia ? window.__katphiMedia.report() : ''",
                _APP_WORLD,
                lambda result, v=view, k=key: self._on_report(v, k, result))
        except Exception:
            pass

    def _on_report(self, view, key, result):
        global _codecs_available
        if not result:
            return
        try:
            import json
            data = json.loads(result)
        except Exception:
            return
        if data.get("h264"):
            # Motor con códecs propietarios: nada que vigilar
            _codecs_available = True
            self.stop()
            for profile in {self._view_profile(v) for v in self._all_views()} - {None}:
                _remove_scripts(profile)
            logger.info("[MEDIA] Qt WebEngine con H.264/AAC: aviso de códecs desactivado")
            return
        _codecs_available = False
        if not data.get("failed") or key in self._handled:
            return
        if self._current_view() is not view or view.url().toString() != key[1]:
            return
        self._handled.add(key)
        logger.info("[MEDIA] Vídeo con códecs no soportados en %s", key[1])
        MediaFallbackBar(view, key[1], data.get("src") or "", self._window)

    def _all_views(self):
        try:
            tabs = self._tab_manager.tabs
            return [tabs.widget(i) for i in range(tabs.count())]
        except Exception:
            return []

    @staticmethod
    def _view_profile(view):
        try:
            return view.page().profile()
        except Exception:
            return None
