#!/usr/bin/env bash
# Compila Qt WebEngine con códecs propietarios (H.264, AAC, HEVC...) para Linux
# x86_64 y lo instala sobre el PySide6 de pip.
#
# Por qué: el Qt WebEngine que trae `pip install PySide6` está compilado sin
# webengine_proprietary_codecs. YouTube funciona (VP9/AV1 + Opus) pero casi
# todas las demás webs sirven MP4/HLS con H.264 y sus vídeos no se reproducen.
# Comprobación: python3 tools/check_codecs.py
#
# Se compila SOLO el módulo qtwebengine, contra el SDK oficial de Qt de la
# misma versión que PySide6 (descargado con aqtinstall), así que las librerías
# resultantes sustituyen a las de PySide6/Qt sin tocar el resto.
#
# Requisitos: ~40 GB libres, 16 GB de RAM como mínimo (32 recomendado), gcc,
# cmake >= 3.19, nodejs >= 14 y python3-venv. Tarda de 1 a 4 horas según la CPU.
# No necesita sudo: las cabeceras que faltan (nss, dbus, X11...) y flex/bison/
# gperf se descargan como .deb con `apt-get download` y se extraen en local.
# Solo para Debian/Ubuntu; en otras distros instala esos paquetes de desarrollo.
#
# Licencias: H.264/AAC/HEVC están cubiertos por patentes. Distribuir binarios
# con estos decodificadores puede requerir licencias (Qt lo avisa en su
# documentación de Qt WebEngine Features); revísalo antes de publicar builds.
#
# Uso:
#   tools/build_qtwebengine_codecs.sh                 # compila e instala en el PySide6 de python3
#   PYTHON=venv_build/bin/python tools/build_qtwebengine_codecs.sh
#   WORKDIR=~/qtwe JOBS=8 tools/build_qtwebengine_codecs.sh
#   tools/build_qtwebengine_codecs.sh install-only    # reinstala lo ya compilado
#   tools/build_qtwebengine_codecs.sh restore         # vuelve al Qt WebEngine original
set -euo pipefail

PYTHON="${PYTHON:-python3}"
# Ruta CORTA: Chromium genera nombres de fichero a partir de la ruta del
# directorio de build y con rutas largas falla con "File name too long".
WORKDIR="${WORKDIR:-$HOME/qtwe}"
JOBS="${JOBS:-$(( $(nproc) > 8 ? 8 : $(nproc) ))}"
ACTION="${1:-all}"

QT_VERSION="$("$PYTHON" -c 'import PySide6.QtCore as c; print(c.qVersion())')"
PYSIDE_QT="$("$PYTHON" -c 'import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), "Qt"))')"
QT_MINOR="${QT_VERSION%.*}"
SRC="$WORKDIR/qtwebengine-everywhere-src-$QT_VERSION"
BUILD="$WORKDIR/build"
DEVROOT="$WORKDIR/devroot"
BACKUP="$PYSIDE_QT/.webengine-original"

echo "PySide6 / Qt $QT_VERSION en $PYSIDE_QT"
echo "Directorio de trabajo: $WORKDIR ($JOBS hilos)"

fetch_sources() {
    mkdir -p "$WORKDIR"
    cd "$WORKDIR"
    if [ ! -x tools-venv/bin/aqt ]; then
        "$PYTHON" -m venv tools-venv
        tools-venv/bin/pip -q install aqtinstall html5lib ninja
    fi
    if [ ! -d "sdk/$QT_VERSION/gcc_64" ]; then
        tools-venv/bin/aqt install-qt linux desktop "$QT_VERSION" linux_gcc_64 -O sdk \
            -m qtwebchannel qtpositioning qtwebsockets
    fi
    if [ ! -d "$SRC" ]; then
        curl -fL -o qtwebengine-src.tar.xz \
            "https://download.qt.io/official_releases/qt/$QT_MINOR/$QT_VERSION/submodules/qtwebengine-everywhere-src-$QT_VERSION.tar.xz"
        tar xf qtwebengine-src.tar.xz
        rm -f qtwebengine-src.tar.xz
    fi
}

fetch_dev_packages() {
    # Paquetes de desarrollo sin sudo. Solo los que Qt WebEngine usa del
    # sistema; el resto (ffmpeg, harfbuzz, libvpx...) va empaquetado dentro
    # de Chromium para que el resultado funcione en cualquier distro.
    local pkgs="flex bison gperf m4 libfl2 libfl-dev libnss3-dev libnspr4-dev libdbus-1-dev
        libxcomposite-dev libdrm-dev libxdamage-dev libxkbfile-dev libxshmfence-dev libxtst-dev
        libxkbcommon-dev libxkbcommon-x11-dev libgbm-dev libx11-xcb-dev libxrandr-dev libxfixes-dev
        libxext-dev libxi-dev libxrender-dev libxcb1-dev libxcb-dri3-dev libxcb-present-dev
        libxcb-xfixes0-dev libxcb-randr0-dev libxcb-shm0-dev libxcb-xkb-dev libxcb-glx0-dev
        libxcb-icccm4-dev libxcb-image0-dev libxcb-keysyms1-dev libxcb-render-util0-dev
        libxcb-render0-dev libxcb-shape0-dev libxcb-sync-dev libxcb-xinerama0-dev libxcb-xinput-dev
        libxcb-cursor-dev libasound2-dev libpulse-dev libegl-dev libgl-dev libglx-dev libopengl-dev
        libxau-dev libxdmcp-dev x11proto-dev xtrans-dev libudev-dev libcups2-dev libxss-dev"
    [ -d "$DEVROOT/usr" ] && return
    mkdir -p "$WORKDIR/devdebs" "$DEVROOT"
    (cd "$WORKDIR/devdebs" && for p in $pkgs; do apt-get download "$p" >/dev/null 2>&1 || echo "  aviso: no se pudo descargar $p"; done)
    for f in "$WORKDIR"/devdebs/*.deb; do dpkg-deb -x "$f" "$DEVROOT"; done
    local r="$DEVROOT/usr" l="$DEVROOT/usr/lib/x86_64-linux-gnu"
    # Reubicar los .pc al prefijo local
    sed -i "s#^prefix=/usr\$#prefix=$r#; s#^original_prefix=/usr\$#original_prefix=$r#; s#^exec_prefix=/usr\$#exec_prefix=$r#; s#^libdir=/usr/#libdir=$r/#; s#^includedir=/usr/#includedir=$r/#" \
        "$l"/pkgconfig/*.pc "$r"/share/pkgconfig/*.pc 2>/dev/null || true
    # Los -dev traen enlaces libX.so -> libX.so.N relativos: apuntarlos a las
    # librerías de ejecución del sistema
    for so in "$l"/*.so; do
        [ -e "$so" ] && continue
        local target
        target="$(basename "$(readlink "$so")")"
        [ -e "/usr/lib/x86_64-linux-gnu/$target" ] && ln -sf "/usr/lib/x86_64-linux-gnu/$target" "$so"
    done
}

build_env() {
    local r="$DEVROOT/usr" l="$DEVROOT/usr/lib/x86_64-linux-gnu"
    export PATH="$r/bin:$WORKDIR/tools-venv/bin:$PATH"
    export PKG_CONFIG_PATH="$l/pkgconfig:$r/share/pkgconfig"
    export BISON_PKGDATADIR="$r/share/bison"
    export M4="$r/bin/m4"
    export LD_LIBRARY_PATH="$l"
    export CPATH="$r/include"
}

configure_and_build() {
    build_env
    mkdir -p "$BUILD"
    cd "$BUILD"
    if [ ! -f build.ninja ]; then
        cmake -G Ninja "$SRC" \
            -DCMAKE_PREFIX_PATH="$WORKDIR/sdk/$QT_VERSION/gcc_64" \
            -DCMAKE_INSTALL_PREFIX="$WORKDIR/install" \
            -DCMAKE_BUILD_TYPE=Release \
            -DFEATURE_webengine_proprietary_codecs=ON \
            -DFEATURE_qtpdf_build=OFF \
            -DFEATURE_webengine_kerberos=OFF \
            -DPython3_EXECUTABLE="$WORKDIR/tools-venv/bin/python" | tee "$WORKDIR/configure.log"
        if grep -q "won't be built" "$WORKDIR/configure.log"; then
            echo "ERROR: faltan dependencias (ver arriba)." >&2
            exit 1
        fi
        grep -q "QT_FEATURE_webengine_proprietary_codecs:INTERNAL=ON" CMakeCache.txt || {
            echo "ERROR: proprietary_codecs no quedó activado." >&2; exit 1; }
    fi
    nice -n 15 ninja -j"$JOBS"
}

install_into_pyside6() {
    local out="$BUILD"
    [ -f "$out/lib/libQt6WebEngineCore.so.$QT_VERSION" ] || {
        echo "ERROR: no hay build en $out (ejecuta primero sin argumentos)." >&2; exit 1; }
    if [ ! -d "$BACKUP" ]; then
        echo "Copia de seguridad del Qt WebEngine original en $BACKUP"
        mkdir -p "$BACKUP/lib" "$BACKUP/libexec" "$BACKUP/resources"
        cp -a "$PYSIDE_QT"/lib/libQt6WebEngineCore.so.6 "$BACKUP/lib/"
        cp -a "$PYSIDE_QT"/libexec/QtWebEngineProcess "$BACKUP/libexec/"
        cp -a "$PYSIDE_QT"/resources/. "$BACKUP/resources/"
    fi
    # El .so.6 de PySide6 es un fichero (no un enlace): se sustituye por la build
    cp -f "$out/lib/libQt6WebEngineCore.so.$QT_VERSION" "$PYSIDE_QT/lib/libQt6WebEngineCore.so.6"
    cp -f "$out/libexec/QtWebEngineProcess" "$PYSIDE_QT/libexec/QtWebEngineProcess"
    for f in qtwebengine_resources.pak qtwebengine_resources_100p.pak qtwebengine_resources_200p.pak \
             qtwebengine_devtools_resources.pak icudtl.dat v8_context_snapshot.bin; do
        [ -f "$out/resources/$f" ] && cp -f "$out/resources/$f" "$PYSIDE_QT/resources/$f"
    done
    if [ -d "$out/translations/qtwebengine_locales" ]; then
        cp -f "$out"/translations/qtwebengine_locales/*.pak "$PYSIDE_QT/translations/qtwebengine_locales/" 2>/dev/null || true
    fi
    echo "Instalado. Comprueba: $PYTHON tools/check_codecs.py"
}

restore_original() {
    [ -d "$BACKUP" ] || { echo "No hay copia de seguridad en $BACKUP"; exit 1; }
    cp -f "$BACKUP/lib/libQt6WebEngineCore.so.6" "$PYSIDE_QT/lib/"
    cp -f "$BACKUP/libexec/QtWebEngineProcess" "$PYSIDE_QT/libexec/"
    cp -a "$BACKUP/resources/." "$PYSIDE_QT/resources/"
    echo "Restaurado el Qt WebEngine original de PySide6."
}

case "$ACTION" in
    all)          fetch_sources; fetch_dev_packages; configure_and_build; install_into_pyside6 ;;
    build)        fetch_sources; fetch_dev_packages; configure_and_build ;;
    install-only) install_into_pyside6 ;;
    restore)      restore_original ;;
    *)            echo "Uso: $0 [all|build|install-only|restore]"; exit 2 ;;
esac
