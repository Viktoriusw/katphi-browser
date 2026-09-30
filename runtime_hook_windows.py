"""
Runtime hook para Katphi Browser en Windows (PyInstaller).

Se ejecuta ANTES que main.py. Configura rutas de Qt para que
QtWebEngineProcess.exe y los recursos .pak se encuentren correctamente.
"""
import os
import sys

# Directorio donde está el .exe compilado
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
    exe_dir = os.path.dirname(sys.executable)

    # Qt necesita saber dónde están sus plugins y recursos
    os.environ.setdefault('QT_PLUGIN_PATH', os.path.join(base_dir, 'PySide6', 'plugins'))
    os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', os.path.join(base_dir, 'PySide6', 'plugins', 'platforms'))

    # QtWebEngine necesita encontrar su proceso helper
    os.environ.setdefault(
        'QTWEBENGINEPROCESS_PATH',
        os.path.join(base_dir, 'PySide6', 'QtWebEngineProcess.exe')
    )

    # Recursos de QtWebEngine (archivos .pak, icudtl.dat, etc.)
    resources_path = os.path.join(base_dir, 'PySide6', 'resources')
    if os.path.isdir(resources_path):
        os.environ.setdefault('QTWEBENGINE_RESOURCES_PATH', resources_path)

    # Añadir base_dir al PATH para que las DLLs se encuentren
    os.environ['PATH'] = base_dir + os.pathsep + os.environ.get('PATH', '')

    # El navegador abre sus datos (icons/, ui/themes/, plugins/, config.yaml,
    # bookmarks.db...) con rutas relativas al directorio de trabajo. Al lanzarlo
    # desde un acceso directo o desde otra carpeta, ese directorio no es el de la
    # aplicación y faltarían iconos y temas: se fija aquí antes de que arranque.
    os.chdir(base_dir)
