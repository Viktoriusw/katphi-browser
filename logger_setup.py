#!/usr/bin/env python3
"""
Sistema de logging centralizado para Katphi Browser.

Características:
- Fichero rotante (5 MB × 3 backups) → katphi_browser.log
- Handler en memoria (ring-buffer de 2 000 registros) con señal Qt
- Captura de excepciones no capturadas en el hilo principal y en threads
- Captura de mensajes Qt (qInstallMessageHandler)
- Captura de avisos de Python (warnings → logging)
- Formato rico con módulo, función y línea para facilitar el debug
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import traceback
import warnings
from collections import deque
from datetime import datetime
from typing import Deque, List, Optional

from PySide6.QtCore import QObject, Signal

# ── Ruta del fichero de log ───────────────────────────────────────────────────
# Empaquetado (PyInstaller), __file__ apunta dentro del bundle, que puede ser de
# solo lectura (/opt en Linux); el runtime hook ya ha fijado como directorio de
# trabajo la carpeta de datos de la app, así que el log va ahí.
if getattr(sys, "frozen", False):
    _LOG_DIR = os.getcwd()
else:
    _LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(_LOG_DIR, "katphi_browser.log")

_MAX_MEMORY_RECORDS = 2_000
_LOG_FORMAT = (
    "%(asctime)s [%(levelname)-8s] %(name)s (%(funcName)s:%(lineno)d): %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ── Señal Qt para notificación en tiempo real ─────────────────────────────────

class _LogSignals(QObject):
    """Objeto que emite señales cuando llegan nuevos registros de log."""
    new_record = Signal(object)   # LogRecord


_log_signals: Optional[_LogSignals] = None


def get_log_signals() -> _LogSignals:
    """Devuelve el objeto de señales (singleton), creándolo si es necesario."""
    global _log_signals
    if _log_signals is None:
        _log_signals = _LogSignals()
    return _log_signals


# ── Handler en memoria + señal ────────────────────────────────────────────────

class MemoryLogHandler(logging.Handler):
    """
    Handler que acumula registros en un ring-buffer y emite una señal Qt
    por cada nuevo registro, permitiendo actualizar la UI en tiempo real.
    """

    def __init__(self, maxlen: int = _MAX_MEMORY_RECORDS) -> None:
        super().__init__()
        self._records: Deque[logging.LogRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._records.append(record)
            sigs = get_log_signals()
            sigs.new_record.emit(record)
        except Exception:
            self.handleError(record)
    def get_records(self, level: int = logging.DEBUG) -> List[logging.LogRecord]:
        """Devuelve copia filtrada por nivel mínimo."""
        with self._lock:
            return [r for r in self._records if r.levelno >= level]
    def clear(self) -> None:
        with self._lock:
            self._records.clear()


# Instancia global accesible desde cualquier módulo
memory_handler: Optional[MemoryLogHandler] = None


def get_memory_handler() -> MemoryLogHandler:
    """Devuelve el MemoryLogHandler global (creado por setup_logging)."""
    global memory_handler
    if memory_handler is None:
        memory_handler = MemoryLogHandler()
    return memory_handler


# ── Formatter con color para la consola ──────────────────────────────────────

_LEVEL_COLORS = {
    logging.DEBUG:    "\033[36m",    # cian
    logging.INFO:     "\033[32m",    # verde
    logging.WARNING:  "\033[33m",    # amarillo
    logging.ERROR:    "\033[31m",    # rojo
    logging.CRITICAL: "\033[35m",    # magenta
}
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        msg = super().format(record)
        return f"{color}{msg}{_RESET}" if color else msg


# ── Función principal de configuración ───────────────────────────────────────

def setup_logging(level: str = "DEBUG") -> None:
    """
    Configura el sistema de logging de Katphi Browser.

    Llama a esta función una sola vez al inicio de ``main.py`` en lugar de
    ``logging.basicConfig``.  Después, todos los módulos hacen simplemente::
        import logging
        _log = logging.getLogger(__name__)
    Args:
        level: Nivel mínimo de logging (``"DEBUG"``, ``"INFO"``, etc.).
    """
    global memory_handler

    numeric_level = getattr(logging, level.upper(), logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # capturar todo; los handlers filtran

    # Eliminar handlers heredados para evitar duplicados
    root.handlers.clear()

    # ── Handler de consola (stderr) con colores ───────────────────────────────
    console_h = logging.StreamHandler(sys.stdout)
    console_h.setLevel(numeric_level)
    console_h.setFormatter(
        _ColorFormatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    )
    root.addHandler(console_h)

    # ── Handler de fichero rotante ────────────────────────────────────────────
    try:
        file_h = logging.handlers.RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=5 * 1024 * 1024,   # 5 MB por fichero
            backupCount=3,
            encoding="utf-8",
        )
        file_h.setLevel(logging.DEBUG)   # guardar todo en fichero
        file_h.setFormatter(
            logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
        )
        root.addHandler(file_h)
    except Exception as exc:
        print(f"[logger_setup] No se pudo abrir el fichero de log: {exc}", file=sys.stderr)
    # ── Handler en memoria ────────────────────────────────────────────────────
    memory_handler = MemoryLogHandler()
    memory_handler.setLevel(logging.DEBUG)
    memory_handler.setFormatter(
        logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    )
    root.addHandler(memory_handler)

    # ── Avisos de Python → logging ────────────────────────────────────────────
    logging.captureWarnings(True)

    # ── Excepciones no capturadas en el hilo principal ────────────────────────
    _log = logging.getLogger("katphi.crash")

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _log.critical(
            "EXCEPCIÓN NO CAPTURADA:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
    sys.excepthook = _excepthook

    # ── Excepciones no capturadas en threads secundarios ─────────────────────
    def _threading_excepthook(args):
        _log.critical(
            "EXCEPCIÓN NO CAPTURADA EN THREAD [%s]:\n%s",
            getattr(args.thread, "name", "?"),
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_tb)),
        )
    threading.excepthook = _threading_excepthook

    # ── Mensajes Qt → logging ─────────────────────────────────────────────────
    _install_qt_message_handler()

    _log.info(
        "Sistema de logging iniciado — nivel=%s, fichero=%s",
        level.upper(),
        LOG_FILE_PATH,
    )


_QT_NOISE_SUBSTRINGS = (
    # Chromium DevTools protocol errors que no podemos corregir desde Python
    "Autofill.enable",
    "Autofill.setAddresses",
    "Storage.getStorageKeyForFrame",
    "Frame tree node for given frame not found",
    # Avisos de Permissions-Policy de sitios web externos
    "Permissions-Policy header",
    # Cloudflare Turnstile (challenge en sitios visitados)
    "Cloudflare Turnstile",
    "challenges.cloudflare.com",
    # WebGPU no disponible en Qt WebEngine en Linux
    "Failed to create WebGPU",
    # Avisos de preload de recursos de sitios externos
    "was preloaded using link preload but not used",
    # CSS externo que no nos compete
    "font-size:0;color:transparent",
    # GBM/Vulkan (entorno gráfico, no errores nuestros)
    "GBM is not supported",
    "Fallback to Vulkan",
)


def _install_qt_message_handler() -> None:
    """Redirige los mensajes internos de Qt al logger de Python.

    Filtra el ruido de Chromium/DevTools que no es accionable desde Python.
    """
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        _qt_log = logging.getLogger("Qt")
        _QT_LEVEL_MAP = {
            QtMsgType.QtDebugMsg:    logging.DEBUG,
            QtMsgType.QtInfoMsg:     logging.INFO,
            QtMsgType.QtWarningMsg:  logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg:    logging.CRITICAL,
        }

        def _qt_handler(msg_type, context, message):
            # Silenciar mensajes ruidosos de Chromium que no son accionables
            for noise in _QT_NOISE_SUBSTRINGS:
                if noise in message:
                    return
            level = _QT_LEVEL_MAP.get(msg_type, logging.DEBUG)
            location = ""
            if context.file:
                location = f" [{context.file}:{context.line}]"
            _qt_log.log(level, "%s%s", message, location)
        qInstallMessageHandler(_qt_handler)
    except Exception as exc:
        logging.getLogger(__name__).debug(
            "No se pudo instalar el handler Qt: %s", exc
        )
