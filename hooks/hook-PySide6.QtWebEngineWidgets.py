"""
Hook personalizado para PySide6.QtWebEngineWidgets en Windows.

Asegura que QtWebEngineProcess.exe y todos los recursos .pak
se incluyan en el build de PyInstaller.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, is_module_satisfies
from PyInstaller.compat import is_win
import os
import glob

datas = []
binaries = []
hiddenimports = [
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebChannel',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
    'PySide6.QtPositioning',
]

# Recopilar todos los archivos de datos de PySide6
try:
    datas += collect_data_files('PySide6', includes=[
        'resources/*',
        'translations/qtwebengine*',
        'Qt/resources/*',
        'Qt/translations/qtwebengine*',
    ])
except Exception:
    pass

# En Windows: incluir QtWebEngineProcess.exe explícitamente
if is_win:
    try:
        import PySide6
        pyside6_dir = os.path.dirname(PySide6.__file__)

        # Buscar QtWebEngineProcess.exe
        for pattern in [
            os.path.join(pyside6_dir, 'QtWebEngineProcess.exe'),
            os.path.join(pyside6_dir, 'Qt', 'bin', 'QtWebEngineProcess.exe'),
        ]:
            matches = glob.glob(pattern)
            if matches:
                for match in matches:
                    binaries.append((match, 'PySide6'))
                break

        # Buscar recursos WebEngine (.pak, .dat, .bin)
        for resources_dir in [
            os.path.join(pyside6_dir, 'resources'),
            os.path.join(pyside6_dir, 'Qt', 'resources'),
        ]:
            if os.path.isdir(resources_dir):
                for f in os.listdir(resources_dir):
                    full_path = os.path.join(resources_dir, f)
                    if os.path.isfile(full_path):
                        datas.append((full_path, os.path.join('PySide6', 'resources')))
                break

    except Exception as e:
        print(f'[hook-QtWebEngineWidgets] Advertencia: {e}')
