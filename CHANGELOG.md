# Cambios

## 3.6.0-2 — Actualización legal: códecs patentados

Se aclara la postura del proyecto respecto a H.264, AAC y HEVC. Katphi Browser no
distribuye binarios con códecs patentados. La funcionalidad del navegador no cambia:
VP9, AV1, Opus y MP3 siguen funcionando igual.

- Los paquetes oficiales (Windows, .deb, AppImage) vuelven a usar el Qt WebEngine
  estándar de PySide6, sin H.264/AAC/HEVC.
- El FFmpeg que trae PySide6 para Qt Multimedia sí incluía H.264/HEVC/AAC. En Linux se
  sustituye por FFmpeg 7.1.3 sin esos códecs (`tools/build_ffmpeg_sin_patentes.sh`). En
  Windows no se empaqueta y Qt Multimedia usa Media Foundation (`QT_MEDIA_BACKEND=windows`).
- `katphi_linux.spec` y `katphi_windows.spec` detienen el build si el Qt WebEngine
  del entorno incluye esos códecs. `build_windows.bat` ya no los compila.
- `tools/build_qtwebengine_codecs.sh` y `tools/build_qtwebengine_codecs_windows.ps1`
  muestran un aviso legal y piden escribir `SI` antes de compilar o instalar. Además
  dejan un `AVISO_LEGAL_CODECS.txt` junto al Qt WebEngine que instalan.
- Nuevo `AVISO_LEGAL.md`. README e INSTALACION.md incluyen el aviso legal sobre
  códecs, y la sección de licencia aclara que la licencia MIT no cubre esos códecs.
- La barra de aviso de vídeo no reproducible explica que Katphi Browser no incluye
  H.264/AAC por motivos de licencia y ofrece abrir el vídeo fuera del navegador.
