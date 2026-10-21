#!/usr/bin/env python3
"""
Descarga el SDK oficial de Qt para Windows (MSVC 2022 x64) de una versión
concreta, solo con los módulos que necesita compilar Qt WebEngine.

Sustituye a `aqt install-qt`: aqtinstall 3.3.0 no entiende el repositorio de
Qt 6.11 (qt6_6110/qt6_6110_msvc2022_64) y falla con "Failed to download
checksum for the file 'Updates.xml'".

Uso (lo llama tools/build_qtwebengine_codecs_windows.ps1):
    python tools/fetch_qt_sdk_windows.py 6.11.0 C:\\qtwe\\sdk

Resultado: <destino>\\<versión>\\msvc2022_64 (con bin\\qt.conf). Requiere py7zr.
"""
import hashlib
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import py7zr

BASE = "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop"
ARCH = "win64_msvc2022_64"
# Del paquete principal solo hace falta esto: qtdoc, qttools, qttranslations y
# opengl32sw no intervienen en el build de qtwebengine
MAIN_ARCHIVES = ("qtbase-", "qtsvg-", "qtdeclarative-")
ADDONS = ("qtwebchannel", "qtpositioning", "qtwebsockets")


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    version, dest = sys.argv[1], Path(sys.argv[2])
    nodot = version.replace(".", "")
    repo = f"{BASE}/qt6_{nodot}/qt6_{nodot}_msvc2022_64"
    prefix = dest / version / "msvc2022_64"
    if (prefix / "lib" / "cmake" / "Qt6WebChannel").is_dir():
        print(f"SDK ya presente en {prefix}")
        return 0

    root = ET.fromstring(fetch(f"{repo}/Updates.xml"))
    wanted = {f"qt.qt6.{nodot}.{ARCH}": MAIN_ARCHIVES}
    wanted.update({f"qt.qt6.{nodot}.addons.{m}.{ARCH}": None for m in ADDONS})

    prefix.mkdir(parents=True, exist_ok=True)
    found = set()
    for pkg in root.findall("PackageUpdate"):
        name = pkg.findtext("Name")
        if name not in wanted:
            continue
        found.add(name)
        pkg_version = pkg.findtext("Version")
        archives = [a.strip() for a in (pkg.findtext("DownloadableArchives") or "").split(",") if a.strip()]
        filters = wanted[name]
        for archive in archives:
            if filters and not archive.startswith(filters):
                continue
            url = f"{repo}/{name}/{pkg_version}{archive}"
            print(f"Descargando {archive}...", flush=True)
            data = fetch(url)
            expected = fetch(url + ".sha1").decode().split()[0].strip()
            if hashlib.sha1(data).hexdigest() != expected:
                raise SystemExit(f"SHA-1 incorrecto en {archive}")
            tmp = dest / archive
            tmp.write_bytes(data)
            with py7zr.SevenZipFile(tmp) as z:
                # Los paquetes de 6.11 vienen sin la carpeta <versión>\msvc2022_64
                # que traían los de versiones anteriores
                nested = any(n.startswith(f"{version}/") for n in z.getnames())
                z.extractall(dest if nested else prefix)
            tmp.unlink()

    missing = set(wanted) - found
    if missing:
        raise SystemExit(f"No están en el repositorio: {sorted(missing)}")
    # Lo mismo que hace aqt: los binarios del SDK traen el prefijo de la
    # máquina de Qt (c:/Users/qt/work/install)
    (prefix / "bin" / "qt.conf").write_text("[Paths]\nPrefix=..\n", encoding="utf-8")
    print(f"SDK de Qt {version} instalado en {prefix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
