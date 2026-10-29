"""
Reproductor integrado de Katphi con los decodificadores del sistema.

Katphi no distribuye decodificadores H.264/AAC (ver AVISO_LEGAL.md). Para
los vídeos que Qt WebEngine no puede reproducir, este reproductor usa el
decodificador que ya trae el sistema operativo, igual que Firefox, Opera o
Vivaldi:

  - Windows: Media Foundation (backend "windows" de Qt Multimedia; lo
    activa runtime_hook_windows.py con QT_MEDIA_BACKEND=windows).
  - macOS: AVFoundation (backend "darwin" de Qt Multimedia).
  - Linux: libmpv del sistema (paquete libmpv2 de la distribución), que
    usa el FFmpeg de la distribución. Se carga con ctypes; si no está
    instalado, el reproductor no está disponible y se explica cómo
    instalarlo. KATPHI_LIBMPV permite indicar otra ruta a libmpv.

En Linux, si yt-dlp está instalado, libmpv también abre la URL de la
página (vídeos MSE/HLS sin URL directa).
"""

import ctypes
import ctypes.util
import locale
import logging
import os
import shutil
import sys

from PySide6.QtCore import QObject, Qt, Signal, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSlider, QStyle,
                               QToolButton, QVBoxLayout, QWidget)

logger = logging.getLogger(__name__)

_IS_LINUX = sys.platform.startswith("linux")


# ---------------------------------------------------------------------------
# libmpv (Linux)
# ---------------------------------------------------------------------------

_MPV_FORMAT_FLAG = 3
_MPV_FORMAT_DOUBLE = 5

_MPV_EVENT_NONE = 0
_MPV_EVENT_SHUTDOWN = 1
_MPV_EVENT_END_FILE = 7
_MPV_EVENT_FILE_LOADED = 8
_MPV_EVENT_PROPERTY_CHANGE = 22

_MPV_END_FILE_REASON_EOF = 0
_MPV_END_FILE_REASON_ERROR = 4

_MPV_RENDER_PARAM_INVALID = 0
_MPV_RENDER_PARAM_API_TYPE = 1
_MPV_RENDER_PARAM_OPENGL_INIT_PARAMS = 2
_MPV_RENDER_PARAM_OPENGL_FBO = 3
_MPV_RENDER_PARAM_FLIP_Y = 4


class _MpvEvent(ctypes.Structure):
    _fields_ = [("event_id", ctypes.c_int),
                ("error", ctypes.c_int),
                ("reply_userdata", ctypes.c_uint64),
                ("data", ctypes.c_void_p)]


class _MpvEventProperty(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("format", ctypes.c_int),
                ("data", ctypes.c_void_p)]


class _MpvEventEndFile(ctypes.Structure):
    _fields_ = [("reason", ctypes.c_int),
                ("error", ctypes.c_int)]


_GET_PROC_ADDRESS = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
_VOID_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class _MpvOpenGLInitParams(ctypes.Structure):
    _fields_ = [("get_proc_address", _GET_PROC_ADDRESS),
                ("get_proc_address_ctx", ctypes.c_void_p)]


class _MpvOpenGLFbo(ctypes.Structure):
    _fields_ = [("fbo", ctypes.c_int),
                ("w", ctypes.c_int),
                ("h", ctypes.c_int),
                ("internal_format", ctypes.c_int)]


class _MpvRenderParam(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int),
                ("data", ctypes.c_void_p)]


_libmpv = None
_libmpv_error = ""


def _load_libmpv():
    """Carga libmpv del sistema una sola vez. Devuelve la biblioteca o None."""
    global _libmpv, _libmpv_error
    if _libmpv is not None or _libmpv_error:
        return _libmpv
    candidates = []
    if os.environ.get("KATPHI_LIBMPV"):
        candidates.append(os.environ["KATPHI_LIBMPV"])
    found = ctypes.util.find_library("mpv")
    if found:
        candidates.append(found)
    candidates += ["libmpv.so.2", "libmpv.so.1"]
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        try:
            _declare_libmpv(lib)
        except AttributeError as e:
            logger.debug("libmpv %s incompleta: %s", name, e)
            continue
        if (lib.mpv_client_api_version() >> 16) < 2:
            # La API 1.x tiene otra estructura de parámetros de OpenGL
            logger.debug("libmpv %s demasiado antigua", name)
            continue
        _libmpv = lib
        logger.info("[PLAYER] libmpv cargada: %s", name)
        return lib
    _libmpv_error = "libmpv no está instalada"
    return None


def _declare_libmpv(lib):
    c_void_p, c_char_p, c_int = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    sigs = {
        "mpv_client_api_version": (ctypes.c_ulong, []),
        "mpv_create": (c_void_p, []),
        "mpv_initialize": (c_int, [c_void_p]),
        "mpv_terminate_destroy": (None, [c_void_p]),
        "mpv_set_option_string": (c_int, [c_void_p, c_char_p, c_char_p]),
        "mpv_set_property_string": (c_int, [c_void_p, c_char_p, c_char_p]),
        "mpv_command": (c_int, [c_void_p, ctypes.POINTER(c_char_p)]),
        "mpv_observe_property": (c_int, [c_void_p, ctypes.c_uint64, c_char_p, c_int]),
        "mpv_wait_event": (ctypes.POINTER(_MpvEvent), [c_void_p, ctypes.c_double]),
        "mpv_set_wakeup_callback": (None, [c_void_p, _VOID_CALLBACK, c_void_p]),
        "mpv_error_string": (c_char_p, [c_int]),
        "mpv_render_context_create": (c_int, [ctypes.POINTER(c_void_p), c_void_p,
                                              ctypes.POINTER(_MpvRenderParam)]),
        "mpv_render_context_set_update_callback": (None, [c_void_p, _VOID_CALLBACK, c_void_p]),
        "mpv_render_context_render": (c_int, [c_void_p, ctypes.POINTER(_MpvRenderParam)]),
        "mpv_render_context_free": (None, [c_void_p]),
    }
    for name, (restype, argtypes) in sigs.items():
        fn = getattr(lib, name)
        fn.restype = restype
        fn.argtypes = argtypes


def _qt_multimedia_backend():
    """Backend de Qt Multimedia con decodificadores del sistema, o ''."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return ""


def is_available():
    """(disponible, motivo si no lo está)."""
    if _IS_LINUX:
        if _load_libmpv() is None:
            return False, _libmpv_error
        return True, ""
    backend = _qt_multimedia_backend()
    if not backend:
        return False, "plataforma no soportada"
    if os.environ.get("QT_MEDIA_BACKEND", backend) != backend:
        return False, f"QT_MEDIA_BACKEND={os.environ['QT_MEDIA_BACKEND']}"
    return True, ""


def accepts_page_urls():
    """True si el reproductor puede abrir la URL de la página (vía yt-dlp)."""
    return _IS_LINUX and bool(shutil.which("yt-dlp"))


def install_hint():
    """Texto con la forma de instalar lo que falta en este sistema."""
    if not _IS_LINUX:
        return ""
    return ("Instala libmpv desde los repositorios de tu distribución:\n"
            "  Debian/Ubuntu: sudo apt install libmpv2\n"
            "  Fedora: sudo dnf install mpv-libs\n"
            "  Arch: sudo pacman -S mpv\n\n"
            "Opcional, para vídeos sin enlace directo: instala yt-dlp.")


class _Backend(QObject):
    """Interfaz común de los dos motores de reproducción."""

    positionChanged = Signal(float)
    durationChanged = Signal(float)
    pausedChanged = Signal(bool)
    errorOccurred = Signal(str)
    finished = Signal()

    def widget(self):
        raise NotImplementedError

    def play(self, url, referrer="", user_agent=""):
        raise NotImplementedError

    def set_paused(self, paused):
        raise NotImplementedError

    def seek(self, seconds):
        raise NotImplementedError

    def set_volume(self, percent):
        raise NotImplementedError

    def set_muted(self, muted):
        raise NotImplementedError

    def shutdown(self):
        pass


if _IS_LINUX:
    from PySide6.QtGui import QOpenGLContext
    from PySide6.QtOpenGLWidgets import QOpenGLWidget

    class _MpvVideoWidget(QOpenGLWidget):
        """Dibuja la salida de libmpv con su API de render OpenGL.

        Funciona igual en X11 y Wayland (no depende de incrustar ventanas).
        """

        _frameReady = Signal()

        def __init__(self, backend, parent=None):
            super().__init__(parent)
            self._backend = backend
            self._ctx = ctypes.c_void_p()
            # Referencias vivas mientras libmpv pueda llamarlas
            self._get_proc = _GET_PROC_ADDRESS(self._get_proc_address)
            self._update_cb = _VOID_CALLBACK(self._on_mpv_update)
            self._frameReady.connect(self.update, Qt.QueuedConnection)

        @staticmethod
        def _get_proc_address(_ctx, name):
            context = QOpenGLContext.currentContext()
            if context is None:
                return None
            return context.getProcAddress(name) or None

        def _on_mpv_update(self, _data):
            # Hilo de libmpv: solo se puede pedir el repintado
            self._frameReady.emit()

        def initializeGL(self):
            lib, handle = _libmpv, self._backend.handle
            if not handle or self._ctx:
                return
            init = _MpvOpenGLInitParams(self._get_proc, None)
            params = (_MpvRenderParam * 3)(
                _MpvRenderParam(_MPV_RENDER_PARAM_API_TYPE,
                                ctypes.cast(ctypes.c_char_p(b"opengl"), ctypes.c_void_p)),
                _MpvRenderParam(_MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,
                                ctypes.cast(ctypes.pointer(init), ctypes.c_void_p)),
                _MpvRenderParam(_MPV_RENDER_PARAM_INVALID, None))
            err = lib.mpv_render_context_create(ctypes.byref(self._ctx), handle, params)
            if err < 0:
                self._ctx = ctypes.c_void_p()
                self._backend.report_error("render", err)
                return
            lib.mpv_render_context_set_update_callback(self._ctx, self._update_cb, None)
            self._backend.render_ready()

        def paintGL(self):
            if not self._ctx:
                return
            ratio = self.devicePixelRatioF()
            fbo = _MpvOpenGLFbo(self.defaultFramebufferObject(),
                                int(self.width() * ratio), int(self.height() * ratio), 0)
            flip = ctypes.c_int(1)
            params = (_MpvRenderParam * 3)(
                _MpvRenderParam(_MPV_RENDER_PARAM_OPENGL_FBO,
                                ctypes.cast(ctypes.pointer(fbo), ctypes.c_void_p)),
                _MpvRenderParam(_MPV_RENDER_PARAM_FLIP_Y,
                                ctypes.cast(ctypes.pointer(flip), ctypes.c_void_p)),
                _MpvRenderParam(_MPV_RENDER_PARAM_INVALID, None))
            _libmpv.mpv_render_context_render(self._ctx, params)

        def free_render_context(self):
            if not self._ctx:
                return
            self.makeCurrent()
            _libmpv.mpv_render_context_free(self._ctx)
            self._ctx = ctypes.c_void_p()
            self.doneCurrent()

    class _MpvBackend(_Backend):
        _wakeup = Signal()

        _OBS_TIME, _OBS_DURATION, _OBS_PAUSE = 1, 2, 3

        def __init__(self, parent=None):
            super().__init__(parent)
            lib = _load_libmpv()
            # libmpv exige LC_NUMERIC "C" (Qt puede haberlo cambiado)
            locale.setlocale(locale.LC_NUMERIC, "C")
            self.handle = lib.mpv_create()
            if not self.handle:
                raise RuntimeError("mpv_create falló")
            options = {
                "vo": "libmpv",
                "hwdec": "auto-safe",
                "keep-open": "yes",
                "idle": "yes",
                "osc": "no",
                "input-default-bindings": "no",
                "terminal": "no",
                # Sin configuración, historial ni posición guardada
                "config": "no",
                "save-position-on-quit": "no",
                "ytdl": "yes" if accepts_page_urls() else "no",
            }
            for key, value in options.items():
                lib.mpv_set_option_string(self.handle, key.encode(), value.encode())
            err = lib.mpv_initialize(self.handle)
            if err < 0:
                lib.mpv_terminate_destroy(self.handle)
                self.handle = None
                raise RuntimeError(lib.mpv_error_string(err).decode())
            lib.mpv_observe_property(self.handle, self._OBS_TIME, b"time-pos", _MPV_FORMAT_DOUBLE)
            lib.mpv_observe_property(self.handle, self._OBS_DURATION, b"duration", _MPV_FORMAT_DOUBLE)
            lib.mpv_observe_property(self.handle, self._OBS_PAUSE, b"pause", _MPV_FORMAT_FLAG)
            self._wakeup_cb = _VOID_CALLBACK(lambda _d: self._wakeup.emit())
            self._wakeup.connect(self._drain_events, Qt.QueuedConnection)
            lib.mpv_set_wakeup_callback(self.handle, self._wakeup_cb, None)
            self._pending = None
            self._ready = False
            self._video = _MpvVideoWidget(self)

        def widget(self):
            return self._video

        def _command(self, *args):
            if not self.handle:
                return
            arr = (ctypes.c_char_p * (len(args) + 1))(*[a.encode() for a in args], None)
            err = _libmpv.mpv_command(self.handle, arr)
            if err < 0:
                logger.debug("mpv %s: %s", args[0], _libmpv.mpv_error_string(err))

        def _set(self, name, value):
            if self.handle:
                _libmpv.mpv_set_property_string(self.handle, name.encode(), value.encode())

        def render_ready(self):
            self._ready = True
            if self._pending:
                self._command("loadfile", self._pending)
                self._pending = None

        def report_error(self, what, err):
            msg = _libmpv.mpv_error_string(err).decode(errors="replace")
            self.errorOccurred.emit(f"{what}: {msg}")

        def play(self, url, referrer="", user_agent=""):
            if referrer:
                self._set("referrer", referrer)
            if user_agent:
                self._set("user-agent", user_agent)
            if self._ready:
                self._command("loadfile", url)
            else:
                # El contexto OpenGL aún no existe: se carga al crearlo
                self._pending = url

        def set_paused(self, paused):
            self._set("pause", "yes" if paused else "no")

        def seek(self, seconds):
            self._command("seek", f"{seconds:.3f}", "absolute")

        def set_volume(self, percent):
            self._set("volume", str(int(percent)))

        def set_muted(self, muted):
            self._set("mute", "yes" if muted else "no")

        def _drain_events(self):
            while self.handle:
                event = _libmpv.mpv_wait_event(self.handle, 0).contents
                if event.event_id == _MPV_EVENT_NONE:
                    break
                if event.event_id == _MPV_EVENT_SHUTDOWN:
                    break
                if event.event_id == _MPV_EVENT_PROPERTY_CHANGE and event.data:
                    self._on_property(ctypes.cast(event.data,
                                                  ctypes.POINTER(_MpvEventProperty)).contents)
                elif event.event_id == _MPV_EVENT_END_FILE and event.data:
                    end = ctypes.cast(event.data, ctypes.POINTER(_MpvEventEndFile)).contents
                    if end.reason == _MPV_END_FILE_REASON_ERROR:
                        self.report_error("No se pudo reproducir", end.error)
                    elif end.reason == _MPV_END_FILE_REASON_EOF:
                        self.finished.emit()

        def _on_property(self, prop):
            if not prop.data:
                return
            if prop.format == _MPV_FORMAT_DOUBLE:
                value = ctypes.cast(prop.data, ctypes.POINTER(ctypes.c_double)).contents.value
                if prop.name == b"time-pos":
                    self.positionChanged.emit(value)
                elif prop.name == b"duration":
                    self.durationChanged.emit(value)
            elif prop.format == _MPV_FORMAT_FLAG and prop.name == b"pause":
                self.pausedChanged.emit(bool(ctypes.cast(
                    prop.data, ctypes.POINTER(ctypes.c_int)).contents.value))

        def shutdown(self):
            if not self.handle:
                return
            self._video.free_render_context()
            _libmpv.mpv_set_wakeup_callback(self.handle, _VOID_CALLBACK(), None)
            handle, self.handle = self.handle, None
            _libmpv.mpv_terminate_destroy(handle)


class _QtMultimediaBackend(_Backend):
    """QMediaPlayer con el backend nativo (Media Foundation / AVFoundation)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        self._QMediaPlayer = QMediaPlayer
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._video = QVideoWidget()
        self._player.setVideoOutput(self._video)
        self._player.positionChanged.connect(lambda ms: self.positionChanged.emit(ms / 1000.0))
        self._player.durationChanged.connect(lambda ms: self.durationChanged.emit(ms / 1000.0))
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(
            lambda _err, text: self.errorOccurred.emit(text or "No se pudo reproducir"))

    def widget(self):
        return self._video

    def play(self, url, referrer="", user_agent=""):
        # QMediaPlayer no admite cabeceras HTTP propias
        self._player.setSource(QUrl(url))
        self._player.play()

    def set_paused(self, paused):
        if paused:
            self._player.pause()
        else:
            self._player.play()

    def seek(self, seconds):
        self._player.setPosition(int(seconds * 1000))

    def set_volume(self, percent):
        self._audio.setVolume(max(0.0, min(1.0, percent / 100.0)))

    def set_muted(self, muted):
        self._audio.setMuted(muted)

    def _on_state(self, state):
        self.pausedChanged.emit(state != self._QMediaPlayer.PlayingState)

    def _on_status(self, status):
        if status == self._QMediaPlayer.EndOfMedia:
            self.finished.emit()

    def shutdown(self):
        self._player.stop()
        self._player.setSource(QUrl())


def _format_time(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class NativePlayerWindow(QWidget):
    """Ventana del reproductor: vídeo y controles con iconos."""

    SEEK_STEP = 5

    def __init__(self, url, referrer="", user_agent="", title="", parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"{title} — Reproductor Katphi" if title else "Reproductor Katphi")
        self.resize(960, 600)

        self._backend = _MpvBackend(self) if _IS_LINUX else _QtMultimediaBackend(self)
        self._duration = 0.0
        self._paused = False
        self._dragging = False

        video = self._backend.widget()
        video.setMinimumSize(320, 180)

        style = self.style()
        self._play_btn = self._tool_button(style.standardIcon(QStyle.SP_MediaPause), "Pausa (espacio)")
        self._play_btn.clicked.connect(self._toggle_pause)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.setToolTip("Posición")
        self._slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self._slider.sliderReleased.connect(self._on_seek_released)
        self._time_label = QLabel("0:00 / 0:00")
        self._mute_btn = self._tool_button(style.standardIcon(QStyle.SP_MediaVolume), "Silenciar")
        self._mute_btn.setCheckable(True)
        self._mute_btn.toggled.connect(self._on_mute)
        self._volume = QSlider(Qt.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(100)
        self._volume.setFixedWidth(90)
        self._volume.setToolTip("Volumen")
        self._volume.valueChanged.connect(self._backend.set_volume)
        self._full_btn = self._tool_button(style.standardIcon(QStyle.SP_TitleBarMaxButton),
                                           "Pantalla completa (F)")
        self._full_btn.clicked.connect(self._toggle_fullscreen)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.hide()

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 6)
        controls.setSpacing(6)
        controls.addWidget(self._play_btn)
        controls.addWidget(self._slider, 1)
        controls.addWidget(self._time_label)
        controls.addWidget(self._mute_btn)
        controls.addWidget(self._volume)
        controls.addWidget(self._full_btn)
        self._controls = QWidget()
        self._controls.setLayout(controls)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(video, 1)
        layout.addWidget(self._status)
        layout.addWidget(self._controls)

        for keys, slot in (("Space", self._toggle_pause), ("F", self._toggle_fullscreen),
                           ("Escape", self._exit_fullscreen),
                           ("Left", lambda: self._seek_relative(-self.SEEK_STEP)),
                           ("Right", lambda: self._seek_relative(self.SEEK_STEP))):
            QShortcut(QKeySequence(keys), self, activated=slot)

        self._backend.positionChanged.connect(self._on_position)
        self._backend.durationChanged.connect(self._on_duration)
        self._backend.pausedChanged.connect(self._on_paused)
        self._backend.errorOccurred.connect(self._on_error)
        self._position = 0.0
        self._backend.play(url, referrer, user_agent)

    @staticmethod
    def _tool_button(icon, tooltip):
        btn = QToolButton()
        btn.setIcon(icon)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(True)
        return btn

    def _toggle_pause(self):
        self._backend.set_paused(not self._paused)

    def _seek_relative(self, delta):
        target = max(0.0, self._position + delta)
        if self._duration:
            target = min(target, self._duration)
        self._backend.seek(target)

    def _on_seek_released(self):
        self._dragging = False
        self._backend.seek(self._slider.value())

    def _on_mute(self, muted):
        self._backend.set_muted(muted)
        self._mute_btn.setIcon(self.style().standardIcon(
            QStyle.SP_MediaVolumeMuted if muted else QStyle.SP_MediaVolume))

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._controls.hide()
            self.showFullScreen()

    def _exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self._controls.show()

    def _on_position(self, seconds):
        self._position = seconds
        if not self._dragging:
            self._slider.setValue(int(seconds))
        self._time_label.setText(f"{_format_time(seconds)} / {_format_time(self._duration)}")

    def _on_duration(self, seconds):
        self._duration = seconds
        self._slider.setRange(0, int(seconds))

    def _on_paused(self, paused):
        self._paused = paused
        self._play_btn.setIcon(self.style().standardIcon(
            QStyle.SP_MediaPlay if paused else QStyle.SP_MediaPause))
        self._play_btn.setToolTip("Reproducir (espacio)" if paused else "Pausa (espacio)")

    def _on_error(self, message):
        logger.warning("[PLAYER] %s", message)
        self._status.setText(f"  {message}")
        self._status.show()

    def closeEvent(self, event):
        self._backend.shutdown()
        super().closeEvent(event)


def open_player(url, referrer="", user_agent="", title="", parent=None):
    """Abre el reproductor. Devuelve la ventana o lanza RuntimeError."""
    ok, reason = is_available()
    if not ok:
        raise RuntimeError(reason)
    window = NativePlayerWindow(url, referrer, user_agent, title, parent)
    window.show()
    window.raise_()
    window.activateWindow()
    return window
