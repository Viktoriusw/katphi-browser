# Cambios

## 3.6.2 — Bloqueador de anuncios nuevo e interfaz en inglés

### Bloqueador de anuncios

- Nuevo plugin gratuito **Katphi AdBlock** (incluido en los paquetes), que sustituye al
  bloqueo de anuncios del núcleo:
  - Bloqueo de red con EasyList, EasyPrivacy, EasyList Spanish y uBlock filters
    (motor compatible con la sintaxis de AdBlock Plus / uBlock Origin).
  - Ocultación de elementos (reglas `##`): huecos de anuncios, banners y patrocinados.
  - Anuncios de YouTube eliminados de las respuestas del reproductor y scriptlets
    anti-antiadblock de uBlock.
  - Las listas vienen incluidas y se actualizan solas cada 4 días.
  - Sitios sin bloqueo y filtros propios desde su panel.
- El bloqueo del núcleo anterior tenía errores: los tipos `$xmlhttprequest`,
  `$stylesheet`, `$font` y `$subdocument` nunca coincidían, `domain=` se comprobaba
  contra el servidor de la petición y bloqueaba de más (p. ej. fonts.googleapis.com).
  Privacidad ofrece ahora un punto de enganche (`privacy.set_external_ad_decider`)
  para que el plugin decida.
- Corregido: la barra «no se puede reproducir el vídeo» aparecía en páginas sin
  ningún vídeo roto (p. ej. abc.es). Ahora solo sale con un vídeo grande y visible
  que se ha intentado reproducir y lleva 5 s parado, o con un error visible.

### Interfaz en inglés

- Katphi Browser está disponible en español y en inglés. El idioma se elige en
  Ajustes > General > Idioma (por defecto, el del sistema) y se aplica al reiniciar.
  La variable de entorno `KATPHI_LANG=es|en` manda sobre el ajuste.
- Nuevo módulo `i18n.py` (`tr()`) con catálogos en `locales/en.py` (español → inglés)
  y `locales/es.py` (textos que estaban en inglés → español). Los plugins registran
  su propio catálogo con `register_catalog()` y funcionan igual (en español) con
  navegadores anteriores.
- Las páginas GenTab, el reproductor de Katphi TV y el visor de Katphi Office también
  salen en el idioma elegido.
- Corregido: el diálogo «Acerca de» mostraba la versión 3.4.7.
- Corregido: los desplegables del panel de privacidad y la categoría de perfil ya no
  dependen del texto visible.

## 3.6.1 — Asistente con plugins, Containers y Katphi Sync

- El asistente de navegación (gratuito) puede usar los plugins Scraping, SEO Analyzer
  y Katphi Office desde el chat: detectar patrones y exportar datos, analizar el SEO de
  la página y crear informes (PDF, Word, HTML, Excel, Markdown, JSON o CSV), crear hojas
  de cálculo y leer documentos abiertos. Solo usa los plugins que el usuario tiene
  instalados con su licencia.
- Puntos de extensión de pestañas para plugins (`tab_manager.extensions`): perfil de
  WebEngine propio por pestaña que se conserva en la sesión, al duplicar y al reabrir,
  herencia en ventanas emergentes, filtro de navegación, menús y decoración de la
  pestaña. Los usan los nuevos plugins premium Containers y Katphi Sync.
- El gestor de plugins reconoce Containers y Katphi Sync.
- GenTab: seis formatos de plantilla distintos.

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
