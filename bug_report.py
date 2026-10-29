#!/usr/bin/env python3
"""
Informe de error anónimo desde el panel de logs.

Solo se envía si el usuario lo decide: el diálogo muestra exactamente el
texto que saldrá del equipo (ya anonimizado), permite añadir una descripción
o quitar el log, y exige marcar una casilla de confirmación.

Qué se envía: versión de Katphi, sistema operativo (sin nombre del equipo),
la descripción del usuario y el final del último log, anonimizado. Qué no se
envía: cuenta, token, cookies, IP guardada en el servidor, URLs visitadas,
rutas personales, correos ni claves.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import platform
import re
import socket
import sys

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QVBoxLayout)

logger = logging.getLogger(__name__)

REPORT_PATH = "/api/browser/report"
MAX_LOG_CHARS = 400_000          # final del log (el servidor admite 600.000)
MAX_DESCRIPTION = 4000

# Mismas reglas que el backend (app/bug_reports.py); primero las URL completas
_REDACTIONS = [
    (re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s\"'<>)]+"), "<url>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "<token>"),
    (re.compile(r"(?i)\b(bearer|token|authorization|api[_-]?key|password|passwd|secret)\b(\s*[:=]\s*|\s+)\S+"),
     r"\1\2<oculto>"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}"), "<clave>"),
    (re.compile(r"\b(hf|gh[pousr])_[A-Za-z0-9]{16,}"), "<clave>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "<clave>"),
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "<correo>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b"), "<ip>"),
    (re.compile(r"(?i)(/home/|/Users/|C:\\Users\\)[^/\\\s]+"), r"\1<usuario>"),
    (re.compile(r"\bsc_[0-9a-f]{6,}\b"), "<cuenta>"),
    (re.compile(r"\b[0-9a-f]{32,}\b"), "<id>"),
]


def _local_identifiers() -> list:
    """Nombre de usuario, del equipo y carpeta personal (se borran del texto)."""
    out = []
    for getter in (getpass.getuser, socket.gethostname, lambda: os.path.expanduser("~")):
        try:
            value = (getter() or "").strip()
        except Exception:
            value = ""
        if len(value) >= 3:
            out.append(value)
    return sorted(set(out), key=len, reverse=True)


def redact(text: str) -> str:
    if not text:
        return ""
    # Orden: carpeta personal → URL, correos, tokens… → nombres sueltos.
    # Si los nombres fueran antes, partirían URL y correos y quedarían restos.
    idents = _local_identifiers()
    for value in idents:
        if value.startswith(("/", "\\")) or ":" in value:
            text = text.replace(value, "~")
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    for value in idents:
        if not (value.startswith(("/", "\\")) or ":" in value):
            text = re.sub(r"(?i)(?<![\w])" + re.escape(value) + r"(?![\w])", "<local>", text)
    return text


def read_last_log() -> str:
    """Final del último log del navegador (líneas completas)."""
    try:
        from logger_setup import LOG_FILE_PATH
    except Exception:
        return ""
    if not os.path.isfile(LOG_FILE_PATH):
        return ""
    try:
        size = os.path.getsize(LOG_FILE_PATH)
        with open(LOG_FILE_PATH, "rb") as f:
            if size > MAX_LOG_CHARS:
                f.seek(size - MAX_LOG_CHARS)
                f.readline()           # descartar la línea cortada
            return f.read().decode("utf-8", "replace")
    except OSError as e:
        logger.warning("[bug_report] No se pudo leer el log: %s", e)
        return ""


def _platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def os_description() -> str:
    """Sistema operativo y arquitectura, sin nombre del equipo."""
    try:
        return f"{platform.system()} {platform.release()} {platform.machine()}"[:120]
    except Exception:
        return ""


def app_version() -> str:
    try:
        from constants import APP_VERSION
        return APP_VERSION
    except Exception:
        return "0.0.0"


def build_payload(description: str, log_text: str) -> dict:
    return {"consent": True, "app_version": app_version(), "platform": _platform_name(),
            "os": os_description(), "description": redact(description)[:MAX_DESCRIPTION],
            "log": redact(log_text)[-MAX_LOG_CHARS:]}


class _Sender(QObject):
    finished = Signal(bool, str)    # ok, id del informe o mensaje de error

    def __init__(self, payload: dict):
        super().__init__()
        self.payload = payload

    def run(self):
        try:
            import requests
            from config_manager import get_config
            try:
                from net_proxy import requests_proxies
            except Exception:
                requests_proxies = lambda _url="": None   # noqa: E731
            url = get_config().get_backend_url().rstrip("/") + REPORT_PATH
            # Sin token, sin cookies: el informe es anónimo
            r = requests.post(url, data=json.dumps(self.payload).encode("utf-8"),
                              headers={"Content-Type": "application/json"},
                              timeout=30, proxies=requests_proxies(url))
            if r.status_code == 200:
                self.finished.emit(True, r.json().get("report_id", ""))
            else:
                try:
                    detail = r.json().get("detail", "")
                except ValueError:
                    detail = ""
                self.finished.emit(False, detail or f"Error del servidor ({r.status_code})")
        except Exception as e:
            self.finished.emit(False, f"No se pudo conectar con Katphi ({type(e).__name__})")


class BugReportDialog(QDialog):
    """Vista previa + consentimiento explícito antes de enviar nada."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Informar de un error a Katphi")
        self.setMinimumSize(720, 560)
        self._thread = None
        self._raw_log = read_last_log()
        self.report_id = ""

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Puedes enviarnos el último log del navegador para ayudarnos a encontrar el error. "
            "<b>Solo se envía si tú lo confirmas.</b><br>"
            "Se envía: versión de Katphi, sistema operativo, tu descripción y el log de abajo, "
            "ya anonimizado.<br>No se envía: tu cuenta, cookies, el nombre del equipo, "
            "las páginas que visitas (las direcciones se sustituyen por &lt;url&gt;), rutas "
            "personales, correos ni claves. Los informes se borran a los 90 días.")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        layout.addWidget(intro)

        layout.addWidget(QLabel("¿Qué estabas haciendo cuando ocurrió el error? (opcional)"))
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Por ejemplo: al abrir un PDF descargado el navegador se cerró.")
        self.description.setMaximumHeight(90)
        layout.addWidget(self.description)

        self.include_log = QCheckBox("Incluir el log (recomendado)")
        self.include_log.setChecked(bool(self._raw_log))
        self.include_log.setEnabled(bool(self._raw_log))
        self.include_log.toggled.connect(self._refresh_preview)
        layout.addWidget(self.include_log)

        layout.addWidget(QLabel("Esto es exactamente lo que se enviará:"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.preview.setFont(QFont("Monospace", 9))
        layout.addWidget(self.preview, 1)
        self.description.textChanged.connect(self._refresh_preview)

        self.consent = QCheckBox("He revisado el contenido y quiero enviarlo a Katphi")
        layout.addWidget(self.consent)

        self.status = QLabel("")
        layout.addWidget(self.status)

        self.buttons = QDialogButtonBox()
        self.send_btn = self.buttons.addButton("Enviar informe", QDialogButtonBox.AcceptRole)
        self.buttons.addButton("Cancelar", QDialogButtonBox.RejectRole)
        self.send_btn.setEnabled(False)
        self.consent.toggled.connect(self._update_send)
        self.buttons.accepted.connect(self._send)
        self.buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.buttons)
        layout.addLayout(row)
        self._refresh_preview()

    def payload(self) -> dict:
        log_text = self._raw_log if self.include_log.isChecked() else ""
        return build_payload(self.description.toPlainText(), log_text)

    def _refresh_preview(self):
        p = self.payload()
        text = (f"Katphi {p['app_version']} · {p['platform']} · {p['os']}\n\n"
                f"--- Descripción ---\n{p['description'] or '(sin descripción)'}\n\n"
                f"--- Log ---\n{p['log'] or '(no se incluye el log)'}")
        self.preview.setPlainText(text)
        self._update_send()

    def _update_send(self):
        p = self.payload()
        has_content = bool(p["description"].strip() or p["log"].strip())
        self.send_btn.setEnabled(self.consent.isChecked() and has_content and self._thread is None)

    def _send(self):
        if not self.consent.isChecked():
            return
        payload = self.payload()
        self.status.setText("Enviando…")
        self.send_btn.setEnabled(False)
        self._thread = QThread(self)
        self._sender = _Sender(payload)
        self._sender.moveToThread(self._thread)
        self._thread.started.connect(self._sender.run)
        self._sender.finished.connect(self._on_finished)
        self._sender.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_finished(self, ok: bool, info: str):
        self._thread = None
        if ok:
            self.report_id = info
            QMessageBox.information(
                self, "Informe enviado",
                f"Gracias. Tu informe se ha enviado con el código {info}.\n"
                "Si nos escribes sobre este error, indica ese código.")
            self.accept()
        else:
            self.status.setText(info)
            self._update_send()


def show_dialog(parent=None) -> str:
    """Abre el diálogo; devuelve el código del informe si se envió."""
    dlg = BugReportDialog(parent)
    dlg.exec()
    return dlg.report_id
