# Guía de instalación — Katphi Browser 3.5.1

Esta guía explica cómo ejecutar Katphi Browser desde el código fuente y cómo
compilar los paquetes. Si solo quieres usar el navegador, descarga la versión
lista para usar desde [katphi.com/descargar.html](https://katphi.com/descargar.html).

---

## Requisitos

| Componente | Recomendado |
|---|---|
| **Sistema** | Windows 10/11, Linux (Debian, Ubuntu, Fedora…) o macOS 12+ |
| **Python** | 3.10 – 3.12 (3.11 o 3.12 recomendado) |
| **RAM** | 4 GB (8 GB si usas embeddings de IA locales) |
| **Pantalla** | Entorno gráfico (X11 o Wayland) |

### Librerías del sistema (Linux)

Qt WebEngine necesita librerías nativas. En **Debian/Ubuntu**:

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip \
  libxcb-cursor0 libxcb-xinerama0 libxcb-xtest0 \
  libgl1 libfontconfig1 \
  libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1
```

En **Fedora**:

```bash
sudo dnf install -y python3 python3-pip libxcb xcb-util-cursor mesa-libGL fontconfig
```

### Tor (opcional)

Para navegar a través de la red Tor desde el panel Tor:

```bash
sudo apt install tor      # Debian/Ubuntu
sudo dnf install tor      # Fedora
```

Katphi usa los puertos **9150** (SOCKS5) y **9151** (control) para no chocar con
una instancia de Tor del sistema (9050/9051).

---

## Instalación desde el código fuente

### 1. Obtener el código

```bash
git clone https://github.com/Viktoriusw/katphi-browser.git
cd katphi-browser
```

### 2. Crear un entorno virtual

```bash
python3 -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate.bat         # Windows
pip install --upgrade pip
```

### 3. Instalar PySide6 (obligatorio, antes que el resto)

```bash
pip install --upgrade "PySide6>=6.5.0"
python3 -c "from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6 OK')"
```

Si esta comprobación falla, el navegador no arrancará: revisa la sección
[Solución de problemas](#solución-de-problemas).

### 4. Instalar el resto de dependencias

```bash
pip install -r requirements.txt
```

`requirements.txt` incluye el núcleo del navegador y las librerías que pueden usar
los plugins de la tienda. La navegación asistida por IA con embeddings locales
(`sentence-transformers`) es opcional y descarga varios GB:

```bash
pip install "sentence-transformers>=2.2.0"
```

### 5. Comprobar e iniciar

```bash
python3 check_dependencies.py
python3 main.py
```

En Windows, `run_windows.bat` hace los pasos 2 a 5 automáticamente.

---

## Configuración

La configuración por defecto funciona sin cambios. Para personalizarla, copia
`config.example.yaml` como `config.yaml` en la carpeta del proyecto. `config.yaml`
está en `.gitignore` y no se sube al repositorio.

| Clave | Descripción | Valor por defecto |
|---|---|---|
| `backend.primary_url` | API de cuentas y licencias | `https://api.katphi.com` |
| `frontend.url` | Sitio web | `https://katphi.com` |
| `tor.enabled` | Activar Tor al arrancar | `false` |
| `tor.socks_port` | Puerto SOCKS5 de Tor | `9150` |
| `logging.level` | Nivel de log | `INFO` |

### Variables de entorno (opcional)

| Variable | Uso |
|---|---|
| `KATPHI_BACKEND_URL` | Sustituye la URL de la API |
| `KATPHI_FRONTEND_URL` | Sustituye la URL del sitio web |
| `KATPHI_LOG_LEVEL` | Nivel de log (`DEBUG`, `INFO`…) |

### Chat con IA

El chat se configura desde el propio panel del navegador. Proveedores disponibles:
OpenAI, Anthropic, Google Gemini, DeepSeek, Mistral, xAI (Grok), Qwen, Groq,
OpenRouter, HuggingFace, llmapi.ai y modelos locales (Ollama en
`http://localhost:11434`, o LM Studio y otros servidores compatibles con OpenAI en
`http://localhost:1234`).

Las claves de API se guardan en la configuración de usuario del sistema
(`QSettings`), nunca en archivos del proyecto.

### Plugins

El repositorio incluye el sistema de plugins, pero no los plugins. Se instalan
desde la tienda integrada del navegador: los gratuitos (Custom Themes, Split View)
y los de pago (SEO Analyzer, Advanced Scraping, Proxy, AI Live IDE), que requieren
una cuenta en [katphi.com](https://katphi.com).

Para desarrollar plugins propios consulta la
[guía de desarrollo de plugins](docs/plugin-development-guide.md).

---

## Compilar los paquetes

Se usa PyInstaller en modo carpeta (Qt WebEngine necesita su proceso auxiliar
junto al ejecutable).

### Windows

```cmd
build_windows.bat
```

Resultado: `dist\Katphi Browser\`. Distribuye **toda la carpeta**, no solo el `.exe`.

### Linux

```bash
pip install pyinstaller pyinstaller-hooks-contrib
pyinstaller katphi_linux.spec --noconfirm
```

Resultado: `dist/katphi-browser/`, listo para empaquetar como `.deb` (en
`/opt/katphi-browser`) o como AppImage. Instalado, el navegador guarda sus datos
en `~/.local/share/Katphi`.

Ambos builds empaquetan `config.example.yaml` como configuración y se detienen si
contiene una dirección local o privada, o si `plugins/` contiene plugins de pago.

---

## Solución de problemas

### `ModuleNotFoundError: No module named 'PySide6'`

PySide6 no está instalado en el entorno con el que ejecutas el navegador.

```bash
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate.bat         # Windows
pip install --upgrade "PySide6>=6.5.0"
python3 -m pip show PySide6       # debe estar dentro de venv/
```

Causas habituales:
- Se ejecutó `pip install` **sin activar** el entorno virtual.
- `pip install -r requirements.txt` falló a medias y PySide6 no llegó a instalarse:
  instálalo primero por separado.
- Se instaló **PyQt6** en lugar de **PySide6**: no son equivalentes.

### `No module named 'PySide6.QtWebEngineWidgets'`

PySide6 está instalado sin el componente WebEngine:

```bash
pip uninstall -y PySide6 PySide6-Essentials PySide6-Addons
pip install --no-cache-dir --force-reinstall "PySide6>=6.5.0"
```

En Linux, si persiste, instala las librerías del sistema de la sección de requisitos.

### `Could not load the Qt platform plugin "xcb"`

```bash
sudo apt install libxcb-cursor0 libxcb-xinerama0 libxcb-xtest0
```

### `externally-managed-environment` al usar pip (Ubuntu 23.04+)

Usa siempre un entorno virtual (`python3 -m venv venv`) en lugar del Python del sistema.

### El navegador arranca pero las páginas no cargan

- Revisa `katphi_browser.log` en la carpeta del proyecto.
- Si Tor está activado pero no está instalado, desactívalo (`tor.enabled: false`)
  o instala Tor.

### Puerto en uso al arrancar

Katphi abre un socket local para comunicarse entre instancias. Cierra otras
ventanas de Katphi Browser que sigan abiertas.

---

## Licencia

Katphi Browser se distribuye bajo la licencia [MIT](LICENSE).
