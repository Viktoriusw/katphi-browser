#!/usr/bin/env python3
"""
Comprueba qué códecs de audio/vídeo reproduce el Qt WebEngine instalado.

Ejecutar con el mismo Python que usa Katphi:
    python3 tools/check_codecs.py

Si "H.264 + AAC" sale NO, ese Qt WebEngine está compilado sin códecs
propietarios y los vídeos de casi todas las webs (salvo YouTube) no se
reproducirán. Ver tools/build_qtwebengine_codecs.sh.
Código de salida: 0 si hay H.264/AAC, 1 si no.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QUrl, qVersion  # noqa: E402
from PySide6.QtWebEngineCore import qWebEngineChromiumVersion  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

TESTS = [
    ("H.264 + AAC (MP4/HLS, casi todas las webs)", 'video/mp4; codecs="avc1.42E01E, mp4a.40.2"'),
    ("H.264 High", 'video/mp4; codecs="avc1.640028"'),
    ("AAC", 'audio/mp4; codecs="mp4a.40.2"'),
    ("HEVC / H.265", 'video/mp4; codecs="hvc1.1.6.L93.B0"'),
    ("VP9 + Opus (WebM, YouTube)", 'video/webm; codecs="vp9, opus"'),
    ("AV1 (YouTube)", 'video/mp4; codecs="av01.0.05M.08"'),
    ("MP3", "audio/mpeg"),
]

JS = ("JSON.stringify(%s.map(function (t) { return [document.createElement('video')"
      ".canPlayType(t) || 'no', !!(window.MediaSource && MediaSource.isTypeSupported(t))]; }))"
      % json.dumps([mime for _, mime in TESTS]))


def main():
    app = QApplication(sys.argv)
    view = QWebEngineView()
    status = {"code": 1}

    def report(result):
        rows = json.loads(result)
        print(f"Qt {qVersion()} / Chromium {qWebEngineChromiumVersion()}\n")
        print(f"{'Formato':44} {'<video>':10} MSE")
        print("-" * 60)
        for (name, _), (can_play, mse) in zip(TESTS, rows):
            print(f"{name:44} {can_play:10} {'SÍ' if mse else 'NO'}")
        h264 = rows[0][1]
        print()
        print("OK: este Qt WebEngine reproduce H.264/AAC." if h264 else
              "Este Qt WebEngine NO tiene H.264/AAC (códecs propietarios).")
        status["code"] = 0 if h264 else 1
        app.quit()

    view.loadFinished.connect(
        lambda _ok: QTimer.singleShot(300, lambda: view.page().runJavaScript(JS, 0, report)))
    view.setHtml("<html><body></body></html>", QUrl("https://codec-check.local/"))
    QTimer.singleShot(30000, app.quit)
    app.exec()
    return status["code"]


if __name__ == "__main__":
    sys.exit(main())
