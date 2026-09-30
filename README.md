<p align="center">
  <img src="logokatphi.png" alt="Katphi Browser" width="220" />
</p>

## Katphi Browser

Navegador web ligero con sistema de plugins, IA integrada y foco en privacidad.

## Instalación rápida (Linux)

```bash
cd /ruta/a/katphi-browser

# Dependencias del sistema (Qt/X11)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
  libxcb-cursor0 libxcb-xinerama0 libxcb-xtest0 \
  libgl1-mesa-glx libfontconfig1 libssl-dev

# Entorno virtual
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip

# PASO CRÍTICO: PySide6 primero
pip install --upgrade "PySide6>=6.5.0"
python3 -c "from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6 OK')"

# Resto de dependencias
pip install -r requirements.txt

# Verificar e iniciar
python3 check_dependencies.py
python3 main.py
```

---

### Instalación

**Linux / macOS**

```bash
python3 -m venv venv && source venv/bin/activate
pip install --upgrade "PySide6>=6.5.0"    # obligatorio — instalar primero
pip install -r requirements.txt
python3 check_dependencies.py
python3 main.py
```

> Sin **PySide6 + Qt WebEngine** el navegador no arranca. Ver [INSTALACION.md](INSTALACION.md) para la guía completa.

**Windows**

```cmd
run_windows.bat
```

O manualmente: crear `venv_win`, instalar `PySide6>=6.5.0` primero, luego `requirements.txt`.

### Características principales

- **Plugins de la comunidad**: sistema de plugins extensible, con plugins oficiales y desarrollados por la comunidad.
- **Chat IA integrado**: panel de chat con IA y asistencia contextual dentro del navegador.
- **IA en la navegación**: extracción de contexto de páginas, ayuda para búsquedas y tareas directamente sobre los sitios que visitas.
- **Privacidad y seguridad**: gestor de contraseñas, controles avanzados de privacidad y utilidades de seguridad integradas.
- **Navegador muy ligero**: interfaz en PySide6 optimizada, consumo reducido de recursos y tiempos de arranque rápidos.


### Licencia

Consulta el archivo `LICENSE` para los términos completos de uso.
