@echo off
chcp 65001 >nul
echo ================================================
echo   Katphi Browser - Lanzador Portable Windows
echo ================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.11 o 3.12 desde python.org
    echo         Marca "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

python --version

:: Crear entorno virtual si no existe
if not exist "venv_win\Scripts\activate.bat" (
    echo.
    echo [INFO] Creando entorno virtual...
    python -m venv venv_win
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual
        pause
        exit /b 1
    )
)

:: Activar entorno virtual
call venv_win\Scripts\activate.bat

:: Instalar/actualizar dependencias (solo la primera vez o si falta algo)
if not exist "venv_win\.deps_installed" (
    echo.
    echo [INFO] Instalando dependencias ^(primera vez, puede tardar 5-10 minutos^)...
    echo.

    pip install --upgrade pip

    :: Core - PySide6 WebEngine (lo mas importante)
    pip install "PySide6>=6.5.0"
    if errorlevel 1 ( echo [ERROR] Fallo instalando PySide6 & pause & exit /b 1 )

    :: Resto de dependencias (incluye las librerias que usan los plugins de la tienda)
    pip install -r requirements.txt
    if errorlevel 1 ( echo [ERROR] Fallo instalando requirements.txt & pause & exit /b 1 )

    :: Marcar como instalado
    echo 1 > venv_win\.deps_installed
    echo.
    echo [OK] Dependencias instaladas correctamente.
)

echo.
echo [INFO] Iniciando Katphi Browser...
echo.

python main.py

if errorlevel 1 (
    echo.
    echo [ERROR] El navegador cerro con un error. Revisa el log arriba.
    pause
)
