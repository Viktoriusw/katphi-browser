# Aviso legal sobre códecs

Katphi Browser se distribuye bajo licencia [MIT](LICENSE). Sin embargo, esta licencia
no se extiende a los códecs H.264, AAC ni HEVC, que son tecnologías patentadas cuyas
licencias se gestionan a través de Via Licensing Alliance (<https://www.via-la.com/>).
El código fuente de Katphi Browser no contiene implementaciones de estos códecs.

Katphi Browser no distribuye binarios que incluyan estos códecs. La versión oficial
descargable desde katphi.com no los contiene:

- El motor web es el Qt WebEngine estándar de PySide6, que reproduce VP9, AV1, Opus y
  MP3, pero no H.264, AAC ni HEVC.
- Qt Multimedia (que usan algunos plugins) trae en PySide6 su propio FFmpeg, y ese FFmpeg
  sí incluye H.264/HEVC/AAC. Por eso los paquetes oficiales no lo llevan. En Linux se
  sustituye por FFmpeg 7.1.3 (LGPL 2.1 o posterior), compilado a partir de las fuentes
  oficiales de <https://ffmpeg.org/> sin los decodificadores, codificadores ni parsers de
  H.264, HEVC, VVC y AAC (`tools/build_ffmpeg_sin_patentes.sh`, que incluye la
  configuración exacta). En Windows no se incluye FFmpeg: Qt Multimedia usa Media
  Foundation, es decir, los códecs que el propio Windows trae y licencia.

Los scripts de empaquetado oficiales (`katphi_linux.spec`, `katphi_windows.spec`,
`build_windows.bat`) se detienen si detectan un Qt WebEngine con estos códecs; el de
Linux también si el FFmpeg los tiene, y el de Windows deja el FFmpeg fuera del paquete.

Los scripts `tools/build_qtwebengine_codecs.sh` (Linux) y
`tools/build_qtwebengine_codecs_windows.ps1` (Windows) se proporcionan únicamente como
herramienta para que el usuario compile su propia versión de Qt WebEngine con estos
códecs en su equipo, bajo su exclusiva responsabilidad. Antes de compilar muestran este
aviso y piden una confirmación explícita. El mantenedor de Katphi Browser no asume
ninguna responsabilidad por el uso de estos scripts ni por los binarios que de ellos
resulten, ni por el cumplimiento de las obligaciones de licencia que puedan derivarse.

Si redistribuyes una versión compilada con H.264, AAC o HEVC, deberás obtener las
licencias correspondientes de Via Licensing Alliance.
