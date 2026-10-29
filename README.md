<p align="center">
  <img src="logo.png" alt="Katphi Browser" width="200" />
</p>

<h1 align="center">Katphi Browser</h1>

<p align="center">
  Navegador de escritorio con IA integrada, privacidad y sistema de plugins.<br>
  Versión <strong>3.6.0</strong> · Windows · Linux · Licencia MIT
</p>

<p align="center">
  <a href="https://katphi.com">katphi.com</a> ·
  <a href="https://katphi.com/descargar.html">Descargas</a> ·
  <a href="INSTALACION.md">Guía de instalación</a>
</p>

---

## Descarga

Si solo quieres usar el navegador, descarga la versión lista para usar desde
[katphi.com/descargar.html](https://katphi.com/descargar.html):

| Sistema | Formato |
|---|---|
| Windows 10/11 x64 | ZIP portable (descomprimir y ejecutar `Katphi Browser.exe`) |
| Debian / Ubuntu x64 | Paquete `.deb` |
| Cualquier Linux x64 | `AppImage` |

En macOS puede ejecutarse desde el código fuente (ver abajo).

## Características

- **Navegación completa** sobre Qt WebEngine (Chromium): pestañas, grupos de pestañas,
  restauración de sesión, marcadores, historial, descargas, buscar en la página,
  herramientas de desarrollador y capturas de pantalla.
- **Chat con IA** en un panel lateral, con el contexto de la página que estás viendo.
  Proveedores: OpenAI, Anthropic, Google Gemini, DeepSeek, Mistral, xAI (Grok),
  Qwen, Groq, OpenRouter, HuggingFace, llmapi.ai y modelos locales
  (Ollama, LM Studio o cualquier servidor compatible con OpenAI).
  Las claves de API se guardan en tu equipo, nunca en archivos del proyecto.
- **Privacidad**: bloqueo de anuncios y rastreadores (listas EasyList y EasyPrivacy),
  integración con la red Tor y controles de privacidad y limpieza de datos.
- **Gestor de contraseñas** cifrado localmente y generador de contraseñas.
- **Temas** claro y oscuro, y scripts de usuario.
- **Plugins**: el navegador incluye el sistema de plugins; los plugins se instalan
  desde la tienda integrada. Hay plugins gratuitos (Custom Themes, Split View) y de
  pago (SEO Analyzer, Advanced Scraping, Proxy, AI Live IDE), que requieren una
  cuenta en [katphi.com](https://katphi.com).

## Ejecutar desde el código fuente

Requisitos: Python 3.10 o superior (recomendado 3.11/3.12).

**Linux / macOS**

```bash
git clone https://github.com/Viktoriusw/katphi-browser.git
cd katphi-browser

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# PySide6 primero: sin Qt WebEngine el navegador no arranca
pip install --upgrade "PySide6>=6.8.0"
pip install -r requirements.txt

python3 check_dependencies.py
python3 main.py
```

En Debian/Ubuntu pueden hacer falta estas librerías del sistema:

```bash
sudo apt install -y python3-venv libxcb-cursor0 libxcb-xinerama0 libgl1 libfontconfig1
```

**Windows**

```cmd
run_windows.bat
```

Crea el entorno virtual, instala las dependencias la primera vez y arranca el navegador.

La guía completa, con solución de problemas, está en [INSTALACION.md](INSTALACION.md).

### Vídeo H.264/AAC

El Qt WebEngine que instala `pip install PySide6` está compilado sin códecs
propietarios: reproduce VP9, AV1, Opus y MP3 (YouTube funciona), pero no H.264, AAC
ni HEVC, que es lo que sirven la mayoría de webs de vídeo. Cuando un vídeo no se puede
reproducir por eso, Katphi lo avisa y ofrece abrirlo en el navegador del sistema o en
mpv/VLC si están instalados.

**Katphi Browser no distribuye binarios que incluyan H.264, AAC ni HEVC.** La versión
oficial descargable desde katphi.com no contiene estos códecs, precisamente para no
incurrir en obligaciones de licencia de patentes (gestionadas por Via Licensing
Alliance). Los scripts de compilación oficiales se niegan a empaquetar un Qt WebEngine
que los incluya.

Si necesitas reproducir contenido H.264/AAC dentro de Katphi, puedes compilar tu propia
versión de Qt WebEngine en tu equipo con los scripts incluidos. Es una opción avanzada,
no hace falta para usar el navegador:

```bash
python3 tools/check_codecs.py              # ¿qué códecs tiene tu Qt WebEngine?
tools/build_qtwebengine_codecs.sh          # Linux: compilarlo con H.264/AAC (1-4 h, ~40 GB)
tools/build_qtwebengine_codecs.sh restore  # volver al de PySide6
```

En Windows el equivalente es `tools\build_qtwebengine_codecs_windows.ps1` (compila con
MSVC en `C:\qtwe`: 3-8 h, ~100 GB; requiere Visual Studio 2022 con C++ y el
Windows 11 SDK 10.0.26100). Ambos scripts muestran un aviso legal y piden confirmación
antes de compilar.

> **Aviso legal importante:** H.264, AAC y HEVC están sujetos a patentes. Al ejecutar
> estos scripts y compilar tu propia versión, tú, como usuario, eres el único
> responsable de cumplir con las obligaciones de licencia que puedan derivarse del uso
> o distribución de esa compilación. El mantenedor de Katphi Browser no asume ninguna
> responsabilidad por el uso de estos scripts ni por los binarios que de ellos resulten.
> Si redistribuyes una versión compilada con estos códecs, deberás obtener las licencias
> correspondientes de Via Licensing Alliance (<https://www.via-la.com/>).
> Ver [AVISO_LEGAL.md](AVISO_LEGAL.md).

## Compilar los paquetes

| Plataforma | Comando | Resultado |
|---|---|---|
| Windows | `build_windows.bat` | `dist\Katphi Browser\` |
| Linux | `pyinstaller katphi_linux.spec --noconfirm` | `dist/katphi-browser/` |

Los paquetes siempre incluyen la configuración pública (`config.example.yaml`); el
build se detiene si esa configuración apunta a una dirección local o privada.

Los paquetes nunca llevan códecs patentados ([AVISO_LEGAL.md](AVISO_LEGAL.md)):

- El build se detiene si el Qt WebEngine instalado tiene H.264/AAC (por ejemplo, si
  ejecutaste `tools/build_qtwebengine_codecs.sh`). Usa un entorno con el PySide6 de pip o
  ejecuta antes `tools/build_qtwebengine_codecs.sh restore`.
- En Linux, el FFmpeg de Qt Multimedia que trae PySide6 incluye H.264/HEVC/AAC. Antes
  de `pyinstaller` hay que sustituirlo en el entorno de build con
  `PYTHON=<python del entorno> tools/build_ffmpeg_sin_patentes.sh` (FFmpeg 7.1.3 sin
  H.264/HEVC/VVC/AAC; tarda unos minutos). Si no lo haces, el build se detiene.
- En Windows el FFmpeg no se empaqueta y Qt Multimedia usa Media Foundation.

## Configuración

La configuración por defecto funciona sin cambios. Para personalizarla, copia
`config.example.yaml` como `config.yaml` (este archivo no se sube al repositorio).

## Plugins

Para crear tus propios plugins consulta la
[guía de desarrollo de plugins](docs/plugin-development-guide.md).

## Contacto

vicrosdev@proton.me

## Licencia

El código fuente de Katphi Browser se distribuye bajo licencia [MIT](LICENSE). Esta
licencia no cubre los códecs H.264, AAC ni HEVC, que son tecnologías patentadas y
cuyas licencias se gestionan de forma independiente a través de Via Licensing
Alliance. Katphi Browser no distribuye binarios que incluyan estos códecs. Más
detalles en [AVISO_LEGAL.md](AVISO_LEGAL.md).
