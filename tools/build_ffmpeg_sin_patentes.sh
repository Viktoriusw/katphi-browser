#!/usr/bin/env bash
# Compila FFmpeg SIN los códecs patentados H.264, HEVC, VVC y AAC y lo instala
# sobre el FFmpeg que trae el PySide6 de pip (Linux x86_64).
#
# Por qué: el Qt WebEngine de PySide6 no lleva códecs patentados, pero Qt
# Multimedia sí trae su propio FFmpeg (PySide6/Qt/lib/libavcodec.so.61) con
# decodificadores H.264/HEVC/AAC. Katphi no distribuye binarios con esos
# códecs (ver AVISO_LEGAL.md), así que los paquetes oficiales de Linux se
# hacen con este FFmpeg recortado. Qt Multimedia (plugin katphi_tv, voz)
# sigue funcionando con VP9, AV1, VP8, Opus, Vorbis, FLAC, MP3...
# katphi_linux.spec detiene el build si el FFmpeg del entorno tiene H.264/AAC.
#
# Se compila la misma versión que usa Qt (misma ABI .so.61 y versiones de
# símbolos) con la configuración de Qt, sin VA-API (decodificación por CPU).
#
# Requisitos: gcc, make, nasm, cabeceras de OpenSSL 3 y zlib (Debian/Ubuntu:
# nasm libssl-dev zlib1g-dev). Tarda unos minutos.
#
# Uso (PYTHON = el Python del entorno de build, nunca el del sistema):
#   PYTHON=venv/bin/python tools/build_ffmpeg_sin_patentes.sh            # compila e instala
#   PYTHON=venv/bin/python tools/build_ffmpeg_sin_patentes.sh install-only
#   PYTHON=venv/bin/python tools/build_ffmpeg_sin_patentes.sh restore    # vuelve al FFmpeg de Qt
#   PYTHON=venv/bin/python tools/build_ffmpeg_sin_patentes.sh check      # ¿tiene códecs patentados?
set -euo pipefail

PYTHON="${PYTHON:-python3}"
WORKDIR="${WORKDIR:-$HOME/ffb}"
JOBS="${JOBS:-$(nproc)}"
ACTION="${1:-all}"

PYSIDE_LIB="$("$PYTHON" -c 'import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), "Qt", "lib"))')"
# Versión del FFmpeg de Qt: va en su --prefix (/usr/local/FFmpeg-n7.1.3)
FF_VERSION="${FF_VERSION:-$(strings -a "$PYSIDE_LIB/libavcodec.so.61" | grep -m1 -oE 'FFmpeg-n[0-9.]+' | sed 's/FFmpeg-n//' || true)}"
FF_VERSION="${FF_VERSION:-7.1.3}"
SRC="$WORKDIR/ffmpeg-$FF_VERSION"
PREFIX="$WORKDIR/install-$FF_VERSION"
BACKUP="$WORKDIR/qt-ffmpeg-original"
# PySide6 trae cada librería tres veces (.so, .so.N, .so.N.x.y), como ficheros
LIBS="avcodec avformat avutil swresample swscale"

# Códecs con patentes en vigor gestionadas por pools (Via LA, Access Advance)
PATENTADOS_DEC='h264*,hevc*,vvc*,aac*'
PATENTADOS_ENC='h264*,hevc*,aac*'
PATENTADOS_PARSER='h264,hevc,vvc,aac,aac_latm'
# Los bitstream filters (h264_mp4toannexb...) se dejan: solo reempaquetan
# cabeceras, no decodifican, y sin ellos el plugin FFmpeg de Qt Multimedia
# se cae al enumerar formatos (QPlatformMediaIntegration::formatInfo)

echo "FFmpeg $FF_VERSION para $PYSIDE_LIB"

fetch() {
    mkdir -p "$WORKDIR"
    cd "$WORKDIR"
    if [ ! -d "$SRC" ]; then
        curl -fL -o "ffmpeg-$FF_VERSION.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$FF_VERSION.tar.xz"
        tar xf "ffmpeg-$FF_VERSION.tar.xz"
    fi
}

build() {
    cd "$SRC"
    make distclean >/dev/null 2>&1 || true
    # Misma configuración que Qt (ver `strings libavcodec.so.61 | grep -- --prefix`)
    # menos los códecs patentados y la aceleración por hardware
    ./configure --prefix="$PREFIX" \
        --disable-programs --disable-doc --disable-debug --enable-network --disable-lzma \
        --enable-pic --disable-vulkan --disable-v4l2-m2m --disable-decoder=truemotion1 \
        --enable-shared --disable-static --enable-openssl \
        --disable-vaapi --disable-vdpau --disable-ffnvcodec --disable-cuda-llvm \
        --disable-nvdec --disable-nvenc --disable-cuvid --disable-xlib --disable-libxcb \
        --disable-sdl2 --disable-iconv --disable-bzlib \
        --disable-decoder="$PATENTADOS_DEC" --disable-encoder="$PATENTADOS_ENC" \
        --disable-parser="$PATENTADOS_PARSER" \
        ${FF_EXTRA_CONFIGURE:-}
    make -j"$JOBS"
    rm -rf "$PREFIX"
    make install
}

check() {
    # 0 = sin códecs patentados; 1 = los tiene
    local dir="${1:-$PYSIDE_LIB}"
    LD_LIBRARY_PATH="$dir" "$PYTHON" - "$dir" <<'PY'
import ctypes, os, sys
try:
    lib = ctypes.CDLL(os.path.join(sys.argv[1], "libavcodec.so.61"))
except OSError as e:
    # El FFmpeg de Qt no carga suelto (VA-API por stubs): se da por patentado
    print("No se puede comprobar el FFmpeg (se asume con códecs patentados):", e)
    sys.exit(1)
dec, enc = lib.avcodec_find_decoder_by_name, lib.avcodec_find_encoder_by_name
dec.restype = enc.restype = ctypes.c_void_p
found = [n for n in ("h264", "hevc", "vvc", "aac", "aac_fixed", "aac_latm") if dec(n.encode())]
found += [n + " (enc)" for n in ("aac", "h264_vaapi", "hevc_vaapi") if enc(n.encode())]
print("FFmpeg con códecs patentados: " + ", ".join(found) if found else
      "FFmpeg sin H.264/HEVC/VVC/AAC")
sys.exit(1 if found else 0)
PY
}

install_into_pyside6() {
    [ -f "$PREFIX/lib/libavcodec.so.61" ] || {
        echo "ERROR: no hay build en $PREFIX (ejecuta primero sin argumentos)." >&2; exit 1; }
    check "$PREFIX/lib"
    if [ ! -d "$BACKUP" ]; then
        echo "Copia de seguridad del FFmpeg de Qt en $BACKUP (fuera de PySide6: no se empaqueta)"
        mkdir -p "$BACKUP"
        for l in $LIBS; do cp -a "$PYSIDE_LIB"/lib$l.so* "$BACKUP/"; done
    fi
    local f
    for l in $LIBS; do
        for f in "$PYSIDE_LIB"/lib$l.so*; do cp -fL "$PREFIX/lib/lib$l.so" "$f"; done
    done
    check
}

restore_original() {
    [ -d "$BACKUP" ] || { echo "No hay copia de seguridad en $BACKUP"; exit 1; }
    cp -f "$BACKUP"/lib*.so* "$PYSIDE_LIB/"
    echo "Restaurado el FFmpeg de Qt (con H.264/AAC: no usar para builds oficiales)."
}

case "$ACTION" in
    all)          fetch; build; install_into_pyside6 ;;
    build)        fetch; build ;;
    install-only) install_into_pyside6 ;;
    restore)      restore_original ;;
    check)        check ;;
    *)            echo "Uso: $0 [all|build|install-only|restore|check]"; exit 2 ;;
esac
