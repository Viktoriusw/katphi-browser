@echo off
chcp 65001 >nul
echo ================================================
echo   Katphi Browser - Build Ejecutable Windows
echo ================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado. Instala Python 3.11 desde python.org
    pause
    exit /b 1
)

:: Verificar version (recomendado Python 3.11 para maxima compatibilidad con PySide6)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [INFO] Python version: %PYVER%

:: Crear entorno virtual de build
if exist "venv_build" (
    echo [INFO] Eliminando entorno virtual anterior...
    rmdir /s /q venv_build
)

echo [INFO] Creando entorno virtual de build...
python -m venv venv_build
call venv_build\Scripts\activate.bat

:: Actualizar pip
python -m pip install --upgrade pip setuptools wheel

echo.
echo [INFO] Instalando dependencias...
echo.

:: PyInstaller y hooks
pip install "pyinstaller>=6.0.0"
pip install "pyinstaller-hooks-contrib>=2024.0"

:: Core
pip install "PySide6>=6.5.0"
pip install "requests>=2.28.0"
pip install "beautifulsoup4>=4.11.0"
pip install "lxml>=4.9.0"
pip install "aiohttp>=3.8.0"
pip install "aiohttp-socks>=0.7.0"

:: Datos
pip install "pandas>=1.5.0"
pip install "numpy>=1.24.0"
pip install "openpyxl>=3.0.0"
pip install "PyYAML>=6.0"
pip install "Pillow>=9.0.0"

:: UI

:: Auth
pip install "PyJWT>=2.8.0"
pip install "cryptography>=41.0.0"

:: Sistema
pip install "psutil>=5.9.0"
pip install "packaging>=23.0"
pip install "schedule>=1.2.0"
pip install "stem>=1.8.0"
pip install "PySocks>=1.7.1"

:: IA (tarda bastante, comentar para build rapido de prueba)
pip install "sentence-transformers>=2.2.0"

:: PDF export (plugin SEO)
pip install "reportlab>=4.0.0"

:: Legibilidad de texto (dependencia del plugin seo_analyzer)
pip install "textstat>=0.7.3"

echo.
echo [INFO] Iniciando build con PyInstaller...
echo       Esto puede tardar 5-15 minutos...
echo.

:: El ejecutable NO usa el config.yaml local: katphi_windows.spec empaqueta
:: siempre config.example.yaml (backend https://api.katphi.com).

:: Limpiar builds anteriores
if exist "build" rmdir /s /q build
if exist "dist\Katphi Browser" rmdir /s /q "dist\Katphi Browser"

:: Ejecutar PyInstaller
pyinstaller katphi_windows.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] El build fallo. Revisa los errores arriba.
    echo.
    echo Sugerencias:
    echo   1. Si falla por sentence-transformers: comenta esa linea en requirements
    echo   2. Si falla por un modulo no encontrado: aniadelo a hiddenimports en el .spec
    echo   3. Si falla por icons\katphi.ico: edita el .spec y quita la linea 'icon='
    pause
    exit /b 1
)

echo.
echo ================================================
echo   BUILD COMPLETADO
echo ================================================
echo.
echo El ejecutable esta en: dist\Katphi Browser\
echo Ejecuta: dist\Katphi Browser\Katphi Browser.exe
echo.
echo IMPORTANTE: Distribuye TODA la carpeta "Katphi Browser",
echo no solo el .exe. El navegador no funcionara sin los demas archivos.
echo.
pause
