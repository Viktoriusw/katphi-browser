"""Configuración común de los tests.

El esquema katphi-app:// tiene que registrarse antes de crear cualquier
QApplication (Qt lo exige), así que se hace al importar este conftest, que
pytest carga antes que los módulos de test.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import PySide6.QtWebEngineWidgets  # noqa: F401  (antes de la QApplication)
    import app_scheme
    app_scheme.register_scheme()
except Exception:   # pragma: no cover - sin WebEngine
    pass
