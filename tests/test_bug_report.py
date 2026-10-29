"""Informe de error anónimo (bug_report.py): anonimización, consentimiento y envío."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtWidgets import QApplication

import bug_report


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_redact_removes_personal_data(monkeypatch):
    monkeypatch.setattr(bug_report, "_local_identifiers", lambda: ["/home/ana", "portatil-ana", "ana"])
    text = ("abrir https://banco.example/login?user=ana&token=x en /home/ana/doc.pdf "
            "(equipo portatil-ana, usuario ana) Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijkl "
            "ana@correo.es 192.168.1.20 sc_1a2b3c4d C:\\Users\\Ana\\x sk-proj-ABCDEFGHIJKLMNOPQRST")
    out = bug_report.redact(text)
    for leaked in ("banco.example", "/home/ana", "portatil-ana", " ana", "eyJ", "@correo",
                   "192.168", "sc_1a2b", "Users\\Ana", "sk-proj"):
        assert leaked not in out, (leaked, out)
    assert "<url>" in out and "~/doc.pdf" in out and "<local>" in out


def test_payload_has_no_identity():
    p = bug_report.build_payload("falla al abrir", "ERROR x")
    assert set(p) == {"consent", "app_version", "platform", "os", "description", "log"}
    assert p["consent"] is True
    import socket
    assert socket.gethostname() not in p["os"]


class _Capture(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _Capture.received.append((self.path, dict(self.headers), json.loads(body)))
        out = json.dumps({"ok": True, "report_id": "KR-TEST1234"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_dialog_requires_consent_and_sends_anonymously(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QMessageBox
    log = tmp_path / "katphi_browser.log"
    log.write_text("2026-10-22 [ERROR] fallo en https://privado.example/x?id=7 /home/zoe/a.txt\n", encoding="utf-8")
    import logger_setup
    monkeypatch.setattr(logger_setup, "LOG_FILE_PATH", str(log))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import config_manager
    cfg = config_manager.get_config()
    monkeypatch.setattr(cfg, "get_backend_url", lambda: f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    _Capture.received.clear()

    dlg = bug_report.BugReportDialog()
    assert "privado.example" not in dlg.preview.toPlainText()
    assert "<url>" in dlg.preview.toPlainText()
    assert not dlg.send_btn.isEnabled()                 # sin consentimiento no se puede
    dlg._send()
    assert _Capture.received == []
    dlg.description.setPlainText("Se cerró al abrir un PDF")
    dlg.consent.setChecked(True)
    assert dlg.send_btn.isEnabled()
    dlg._send()
    for _ in range(100):
        if dlg.report_id:
            break
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
    srv.shutdown()
    assert dlg.report_id == "KR-TEST1234"
    path, headers, body = _Capture.received[0]
    assert path == "/api/browser/report"
    assert "Authorization" not in headers and "Cookie" not in headers
    assert body["description"] == "Se cerró al abrir un PDF"
    assert "privado.example" not in body["log"] and "<url>" in body["log"]
    # Sin log: el usuario puede quitarlo
    dlg2 = bug_report.BugReportDialog()
    dlg2.include_log.setChecked(False)
    assert dlg2.payload()["log"] == ""
