<p align="center">
  <img src="logo.png" alt="Katphi Browser" width="200" />
</p>

<h1 align="center">Katphi Browser</h1>

<p align="center">
  Navegador de escritorio con IA integrada, privacidad y sistema de plugins.<br>
  Versión <strong>3.5.1</strong> · Windows · Linux · Licencia MIT
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
pip install --upgrade "PySide6>=6.5.0"
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

## Compilar los paquetes

| Plataforma | Comando | Resultado |
|---|---|---|
| Windows | `build_windows.bat` | `dist\Katphi Browser\` |
| Linux | `pyinstaller katphi_linux.spec --noconfirm` | `dist/katphi-browser/` |

Los paquetes siempre incluyen la configuración pública (`config.example.yaml`); el
build se detiene si esa configuración apunta a una dirección local o privada.

## Configuración

La configuración por defecto funciona sin cambios. Para personalizarla, copia
`config.example.yaml` como `config.yaml` (este archivo no se sube al repositorio).

## Plugins

Para crear tus propios plugins consulta la
[guía de desarrollo de plugins](docs/plugin-development-guide.md).

## Contacto

vicrosdev@proton.me

## Licencia

[MIT](LICENSE)
