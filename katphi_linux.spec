# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para Katphi Browser - Linux (paquete .deb, edición gratuita)
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

# ── Sin códecs patentados (H.264/AAC/HEVC) ─────────────────────────────────
# Katphi no distribuye binarios con códecs patentados (ver AVISO_LEGAL.md):
# si el PySide6 de este entorno lleva el Qt WebEngine que compilan
# tools/build_qtwebengine_codecs*.{sh,ps1}, el build se detiene. Se detecta
# por la copia de seguridad y el aviso que dejan esos scripts y por el
# codificador OpenH264, que solo existe en un Qt WebEngine con códecs.
import mmap as _mmap
import PySide6 as _pyside6

def _webengine_con_codecs():
    base = os.path.dirname(_pyside6.__file__)
    for marca in (os.path.join(base, '.webengine-original'),
                  os.path.join(base, 'Qt', '.webengine-original'),
                  os.path.join(base, 'AVISO_LEGAL_CODECS.txt'),
                  os.path.join(base, 'Qt', 'AVISO_LEGAL_CODECS.txt')):
        if os.path.exists(marca):
            return marca
    for lib in (os.path.join(base, 'Qt6WebEngineCore.dll'),
                os.path.join(base, 'Qt', 'lib', 'libQt6WebEngineCore.so.6')):
        if os.path.isfile(lib):
            with open(lib, 'rb') as _f, _mmap.mmap(_f.fileno(), 0, access=_mmap.ACCESS_READ) as _m:
                if _m.find(b'CWelsH264SVCEncoder') != -1:
                    return lib
    return None

_codecs = _webengine_con_codecs()
if _codecs:
    raise SystemExit(
        "El Qt WebEngine de este entorno incluye H.264/AAC (" + _codecs + ").\n"
        "Los builds oficiales no pueden llevar códecs patentados: usa un entorno con\n"
        "el PySide6 de pip o ejecuta tools/build_qtwebengine_codecs.sh restore.")

# Qt Multimedia trae su propio FFmpeg con H.264/HEVC/AAC: el paquete solo
# puede llevar el que compila tools/build_ffmpeg_sin_patentes.sh. Se
# comprueba cargándolo; si no carga (el de Qt depende de VA-API) se aborta.
import ctypes as _ctypes
_QT_LIB = os.path.realpath(os.path.join(os.path.dirname(_pyside6.__file__), 'Qt', 'lib'))

def _ffmpeg_con_patentes():
    try:
        for _l in ('libavutil.so.59', 'libswresample.so.5', 'libavcodec.so.61'):
            _lib = _ctypes.CDLL(os.path.join(_QT_LIB, _l), mode=_ctypes.RTLD_GLOBAL)
    except OSError as _e:
        return f"no se puede comprobar: {_e}"
    _dec = _lib.avcodec_find_decoder_by_name
    _dec.restype = _ctypes.c_void_p
    _found = [n for n in ('h264', 'hevc', 'vvc', 'aac', 'aac_fixed', 'aac_latm') if _dec(n.encode())]
    return ', '.join(_found) or None

if os.path.isfile(os.path.join(_QT_LIB, 'libavcodec.so.61')):
    _ff = _ffmpeg_con_patentes()
    if _ff:
        raise SystemExit(
            "El FFmpeg de Qt Multimedia no vale para un build oficial (" + _ff + ").\n"
            "Instala el FFmpeg recortado: PYTHON=<python del entorno> tools/build_ffmpeg_sin_patentes.sh")

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
    'PySide6.QtTextToSpeech',
    # Katphi Office (plugins cargados en tiempo de ejecución): imprimir PDF
    'PySide6.QtPdf',
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
    # Solo lectura (runtime_hook_linux.py los enlaza en la carpeta del usuario)
    ('icons', 'icons'),
    ('plugins', 'plugins'),
    # Editables: se copian a ~/.local/share/Katphi/app si faltan
    ('ui', 'defaults/ui'),
    ('easylist.txt', 'defaults'),
    ('easyprivacy.txt', 'defaults'),
    ('custom_filters.txt', 'defaults'),
    ('dark_theme.json', 'defaults'),
    ('light_theme.json', 'defaults'),
    (RELEASE_CONFIG, 'defaults'),
    ('unified_plugin_config.json', 'defaults'),
    ('logo.png', 'defaults'),
]

# Edición gratuita: el paquete solo puede llevar los plugins gratuitos.
_FREE_PLUGINS = {'themes', 'split_view', 'voice_control', 'office_viewer'}
_bundled = {d for d in os.listdir('plugins')
            if os.path.isdir(os.path.join('plugins', d)) and d != '__pycache__'}
if _bundled - _FREE_PLUGINS:
    raise SystemExit(f"plugins/ contiene plugins premium: {sorted(_bundled - _FREE_PLUGINS)}")

# ── Hidden imports del proyecto ─────────────────────────────────────────────
app_hiddenimports = [
    # Núcleo 3.6: esquema katphi-app:// y manejadores de archivo para plugins
    'app_scheme',
    'file_handlers',
    # Informe de error anónimo (panel de logs)
    'bug_report',
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
    # Usados solo por plugins (se empaquetan como datos y PyInstaller no los analiza)
    'wave',          # voice_control
    'array',         # voice_control
    'struct',        # katphi_tv
    'socket',
    'ipaddress',
    'argparse',
    'signal',
    'itertools',
    'collections',
    'html',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
    'cryptography.hazmat.primitives.asymmetric.x25519',
    'cryptography.hazmat.primitives.ciphers.aead',
    'cryptography.hazmat.primitives.kdf.hkdf',
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
    hookspath=[],          # carpeta con hooks personalizados (ver abajo)
    hooksconfig={
        'PySide6': {
            'include_qml_files': False,
        },
    },
    runtime_hooks=['runtime_hook_linux.py'],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# Ningún libavcodec que no sea el comprobado arriba (otro paquete podría
# arrastrar el del sistema, que sí trae H.264/AAC)
_ajenos = sorted({src for _n, src, _t in a.binaries
                  if os.path.basename(_n).startswith('libavcodec')
                  and os.path.realpath(os.path.dirname(src)) != _QT_LIB})
if _ajenos:
    raise SystemExit(f"Se empaquetaría un libavcodec no comprobado: {_ajenos}")

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
    name='katphi-browser',
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='katphi-browser',
)
