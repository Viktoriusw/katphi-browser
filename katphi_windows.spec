# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para Katphi Browser - Windows
# Requiere: pip install pyinstaller pyinstaller-hooks-contrib
#
# IMPORTANTE: Usar ONE-DIR (no one-file) porque QtWebEngineProcess.exe
# debe existir como ejecutable independiente junto al .exe principal.
#
# Ejecutar: pyinstaller katphi_windows.spec

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

# ── Recopilar archivos de PySide6 WebEngine (crítico) ──────────────────────
pyside6_datas = collect_data_files('PySide6')
pyside6_datas += collect_data_files('PySide6.QtWebEngine')

# Binarios de PySide6 (DLLs, QtWebEngineProcess.exe, etc.)
pyside6_binaries = collect_dynamic_libs('PySide6')

# Hidden imports de PySide6
pyside6_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebChannel',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtPositioning',
    'PySide6.QtQuick',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtDBus',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
]

# ── config.yaml de distribución ────────────────────────────────────────────
# El config.yaml local del desarrollador puede apuntar a la LAN
# (una IP de la red local) y NUNCA debe viajar en el ejecutable: el usuario
# final tiene que conectarse a https://api.katphi.com desde cualquier red.
# Se empaqueta siempre una copia de config.example.yaml (la plantilla pública)
# y se aborta el build si contiene una dirección privada o localhost.
import re as _re
_release_dir = os.path.join('build', 'release_config')
os.makedirs(_release_dir, exist_ok=True)
RELEASE_CONFIG = os.path.join(_release_dir, 'config.yaml')
with open('config.example.yaml', encoding='utf-8') as _f:
    _release_text = _f.read()
_bad = _re.search(r'https?://(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)',
                  _release_text)
if _bad:
    raise SystemExit(f"config.example.yaml contiene una URL no publica: {_bad.group(0)}")
with open(RELEASE_CONFIG, 'w', encoding='utf-8') as _f:
    _f.write(_release_text)

# ── Archivos de datos del proyecto ─────────────────────────────────────────
project_datas = [
    ('icons', 'icons'),
    ('plugins', 'plugins'),
    ('ui', 'ui'),
    ('easylist.txt', '.'),
    ('easyprivacy.txt', '.'),
    ('custom_filters.txt', '.'),
    ('dark_theme.json', '.'),
    ('light_theme.json', '.'),
    (RELEASE_CONFIG, '.'),
    ('unified_plugin_config.json', '.'),
    ('logo.png', '.'),
]

# Edición gratuita: el paquete solo puede llevar los plugins gratuitos.
_FREE_PLUGINS = {'themes', 'split_view'}
_bundled = {d for d in os.listdir('plugins')
            if os.path.isdir(os.path.join('plugins', d)) and d != '__pycache__'}
if _bundled - _FREE_PLUGINS:
    raise SystemExit(f"plugins/ contiene plugins premium: {sorted(_bundled - _FREE_PLUGINS)}")

# Los archivos de estado en tiempo de ejecución (bookmarks.db, passwords.db,
# downloads_history.db, tab_groups.json, katphi_browser.log) NO se empaquetan:
# son datos del equipo donde se compila y el navegador los crea vacíos al
# arrancar si no existen.

# ── Hidden imports del proyecto ─────────────────────────────────────────────
app_hiddenimports = [
    # Stdlib usados por reflexión
    'importlib.util',
    'importlib.metadata',
    'importlib.resources',
    'email.mime.text',
    'email.mime.multipart',
    'xml.etree.ElementTree',
    'urllib.parse',
    'urllib.request',
    'sqlite3',
    'json',
    'csv',
    'io',
    'base64',
    'hashlib',
    'hmac',
    'secrets',
    'threading',
    'queue',
    'concurrent.futures',
    'asyncio',
    'dataclasses',
    'typing',
    'pathlib',
    're',
    'copy',
    'traceback',
    'weakref',
    # Third-party
    'requests',
    'requests.adapters',
    'requests.auth',
    'urllib3',
    'certifi',
    'charset_normalizer',
    'idna',
    'bs4',
    'bs4.builder',
    'lxml',
    'lxml.etree',
    'lxml.html',
    'aiohttp',
    'aiohttp.connector',
    'aiohttp_socks',
    'pandas',
    'pandas.core.frame',
    'numpy',
    'numpy.core',
    'openpyxl',
    'openpyxl.styles',
    'yaml',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'jwt',
    'cryptography',
    'cryptography.fernet',
    'cryptography.hazmat.primitives',
    'cryptography.hazmat.backends',
    'psutil',
    'schedule',
    'stem',
    'stem.control',
    'socks',
    # IA (opcional — comentar si no se usa)
    'sentence_transformers',
    # PDF export (plugin SEO)
    'reportlab',
    'reportlab.lib',
    'reportlab.platypus',
    # Legibilidad de texto (dependencia declarada por el plugin seo_analyzer)
    'textstat',
    # Allow-list de dependencias de plugins: todo plugin descargado del backend
    # solo puede usar la stdlib + estas librerías (ya empaquetadas arriba):
    #   requests, aiohttp, aiohttp_socks, bs4, lxml, pandas, numpy, openpyxl,
    #   yaml, PIL, reportlab, textstat, cryptography, jwt, psutil.
    # Monaco editor (plugin ai_live_ide) — solo archivos estáticos, no imports adicionales
]

# ── Módulos a excluir (reducen tamaño) ────────────────────────────────────
excludes = [
    'PyQt6',       # No usar PyQt6 — solo PySide6
    'PyQt5',
    'tkinter',
    'wx',
    'matplotlib',  # No usado en el navegador
    'scipy',
    'sklearn',
    'tensorflow',
    'keras',
    'test',
    'unittest',
    'doctest',
]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=pyside6_binaries,
    datas=pyside6_datas + project_datas,
    hiddenimports=pyside6_hiddenimports + app_hiddenimports,
    hookspath=['hooks'],          # carpeta con hooks personalizados (ver abajo)
    hooksconfig={
        'PySide6': {
            'include_qml_files': False,
        },
    },
    runtime_hooks=['runtime_hook_windows.py'],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # ONE-DIR mode (obligatorio para WebEngine)
    # PyInstaller 6 mete por defecto todos los datos en "_internal\". El código
    # del navegador abre icons/, ui/themes/, plugins/, bookmarks.db... con rutas
    # relativas al directorio de trabajo, así que los datos tienen que quedar
    # junto al .exe, igual que en el código fuente (ver runtime_hook_windows.py).
    contents_directory='.',
    name='Katphi Browser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # UPX puede romper WebEngine DLLs en Windows
    console=False,                # Sin ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icons\\katphi.ico',  # Cambia si tienes un .ico; si no, quita esta línea
    version='version_info.txt',   # Opcional: metadata del exe
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Katphi Browser',
)
