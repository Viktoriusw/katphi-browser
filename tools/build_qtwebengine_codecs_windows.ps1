# Compila Qt WebEngine con códecs propietarios (H.264, AAC...) para Windows x64
# y lo instala sobre el PySide6 de pip. Versión Windows de
# tools/build_qtwebengine_codecs.sh (ver allí el porqué).
#
# Se compila SOLO el módulo qtwebengine con MSVC, contra el SDK oficial de Qt de
# la misma versión que PySide6, así que Qt6WebEngineCore.dll y
# QtWebEngineProcess.exe sustituyen a los de PySide6 sin tocar el resto.
#
# Requisitos (instalar a mano antes):
#   - Visual Studio 2022 (o Build Tools 2022) 17.6 o superior con
#     "Desarrollo para el escritorio con C++"
#   - Windows 11 SDK 10.0.26100 o superior (componente del instalador de VS)
#   - Python 3 de 64 bits
#   - ~100 GB libres en la unidad de -WorkDir y 16 GB de RAM (32 recomendado)
# Node.js, gperf, bison/flex, cmake, ninja, el SDK de Qt y las fuentes se
# descargan solos en -WorkDir. Tarda de 3 a 8 horas según la CPU.
# Conviene excluir -WorkDir del antivirus (Windows Defender) o tardará el doble.
#
# Licencias: H.264/AAC están cubiertos por patentes; distribuir binarios con
# estos decodificadores puede requerir licencias (ver Qt WebEngine Features).
#
# Uso (PowerShell):
#   tools\build_qtwebengine_codecs_windows.ps1                          # compila e instala en el PySide6 de "python"
#   tools\build_qtwebengine_codecs_windows.ps1 -Python venv_build\Scripts\python.exe
#   tools\build_qtwebengine_codecs_windows.ps1 -WorkDir D:\qtwe -Jobs 6
#   tools\build_qtwebengine_codecs_windows.ps1 install-only             # reinstala lo ya compilado
#   tools\build_qtwebengine_codecs_windows.ps1 restore                  # vuelve al Qt WebEngine original
param(
    [ValidateSet('all', 'build', 'install-only', 'restore')]
    [string]$Action = 'all',
    [string]$Python = 'python',
    # Ruta CORTA y sin espacios: Chromium falla con rutas largas
    [string]$WorkDir = 'C:\qtwe',
    # Cada objeto de QtWebEngineCore pide ~1,5-3 GB de RAM: 4 es seguro con 32 GB
    [int]$Jobs = 4
)

# 'Continue' y no 'Stop': en PowerShell 5.1 cualquier línea que un programa
# escriba en stderr se convierte en error y cortaría el build. Los códigos de
# salida se comprueban a mano.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

function Fail([string]$msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Invoke-Checked {
    param([string]$Exe, [string[]]$ArgList)
    & $Exe @ArgList
    if ($LASTEXITCODE -ne 0) { Fail "falló: $Exe $($ArgList -join ' ')" }
}

$QtVersion = & $Python -c "import PySide6.QtCore as c; print(c.qVersion())"
if ($LASTEXITCODE -ne 0 -or -not $QtVersion) { Fail "PySide6 no está instalado en $Python" }
$PySideDir = & $Python -c "import PySide6, os; print(os.path.dirname(PySide6.__file__))"
$Bits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($Bits -ne '64') { Fail "hace falta Python de 64 bits ($Python es de $Bits bits)" }

$QtMinor = $QtVersion.Substring(0, $QtVersion.LastIndexOf('.'))
$Src = Join-Path $WorkDir "qtwebengine-everywhere-src-$QtVersion"
$QtNoDot = $QtVersion -replace '\.', ''
$Build = Join-Path $WorkDir "b$QtNoDot"
$Install = Join-Path $WorkDir "install$QtNoDot"
$SdkRoot = Join-Path $WorkDir 'sdk'
$Sdk = Join-Path $SdkRoot "$QtVersion\msvc2022_64"
$Tools = Join-Path $WorkDir 'tools'
$Venv = Join-Path $WorkDir 'tools-venv'
$VPy = Join-Path $Venv 'Scripts\python.exe'
$Backup = Join-Path $PySideDir '.webengine-original'

$NodeVersion = 'v22.11.0'
$Downloads = @{
    node    = @{ url = "https://nodejs.org/dist/$NodeVersion/node-$NodeVersion-win-x64.zip"
                 sha = '905373a059aecaf7f48c1ce10ffbd5334457ca00f678747f19db5ea7d256c236' }
    gperf   = @{ url = 'https://downloads.sourceforge.net/project/gnuwin32/gperf/3.0.1/gperf-3.0.1-bin.zip'
                 sha = '413d9f5562c39c2fcac1e48b3e2155838680a0aec1ddcb95b23cb2f092962dcc' }
    bison   = @{ url = 'https://github.com/lexxmark/winflexbison/releases/download/v2.5.25/win_flex_bison-2.5.25.zip'
                 sha = '8d324b62be33604b2c45ad1dd34ab93d722534448f55a16ca7292de32b6ac135' }
}

Write-Host "PySide6 / Qt $QtVersion en $PySideDir"
Write-Host "Directorio de trabajo: $WorkDir ($Jobs hilos)"

function Get-Download([string]$Url, [string]$Out, [string]$Sha256) {
    if (-not (Test-Path $Out)) {
        Write-Host "Descargando $Url"
        & curl.exe -fL --retry 3 -o "$Out.part" $Url
        if ($LASTEXITCODE -ne 0) { Fail "no se pudo descargar $Url" }
        Move-Item -Force "$Out.part" $Out
    }
    $hash = (Get-FileHash $Out -Algorithm SHA256).Hash
    if ($hash -ne $Sha256.ToUpper()) {
        Remove-Item -Force $Out
        Fail "SHA-256 incorrecto en $Out (se ha borrado; vuelve a ejecutar)"
    }
}

function Get-Tools {
    New-Item -ItemType Directory -Force $Tools | Out-Null
    if (-not (Test-Path $VPy)) {
        Invoke-Checked $Python @('-m', 'venv', $Venv)
    }
    & $VPy -c "import html5lib, py7zr, cmake, ninja" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked $VPy @('-m', 'pip', 'install', '-q', '--upgrade', 'pip')
        Invoke-Checked $VPy @('-m', 'pip', 'install', '-q', 'html5lib', 'py7zr', 'cmake', 'ninja')
    }
    foreach ($name in $Downloads.Keys) {
        $dir = Join-Path $Tools $name
        if (Test-Path $dir) { continue }
        $zip = Join-Path $Tools "$name.zip"
        Get-Download $Downloads[$name].url $zip $Downloads[$name].sha
        Expand-Archive -Force $zip $dir
        Remove-Item -Force $zip
    }
}

function Get-Sources {
    New-Item -ItemType Directory -Force $WorkDir | Out-Null
    if (-not (Test-Path (Join-Path $Sdk 'lib\cmake\Qt6WebChannel'))) {
        # aqtinstall 3.3.0 no sabe leer el repositorio de Qt 6.11
        Invoke-Checked $VPy @((Join-Path $PSScriptRoot 'fetch_qt_sdk_windows.py'), $QtVersion, $SdkRoot)
    }
    if (-not (Test-Path (Join-Path $Src 'CMakeLists.txt'))) {
        $name = "qtwebengine-everywhere-src-$QtVersion.zip"
        $url = "https://download.qt.io/official_releases/qt/$QtMinor/$QtVersion/submodules/$name"
        $zip = Join-Path $WorkDir $name
        $sha = ((& curl.exe -fsL "$url.sha256") -split '\s+')[0]
        if (-not $sha) { Fail "no se pudo descargar $url.sha256" }
        Get-Download $url $zip $sha
        Write-Host "Descomprimiendo las fuentes (varios minutos)..."
        # tar.exe (Windows 10 1803+) es mucho más rápido que Expand-Archive
        & tar.exe -xf $zip -C $WorkDir
        if ($LASTEXITCODE -ne 0) { Fail "no se pudo descomprimir $zip" }
        Remove-Item -Force $zip
    }
}

function Import-VsEnv {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { Fail "no se encuentra Visual Studio 2022 (vswhere.exe)" }
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vs) { Fail "Visual Studio no tiene las herramientas de C++ x64 (Desarrollo para el escritorio con C++)" }
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
    $sdkDirs = Get-ChildItem (Join-Path $kits 'Include') -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^10\.0\.(\d+)\.0$' } |
        Sort-Object { [int]$_.Name.Split('.')[2] }
    $winSdk = $sdkDirs | Select-Object -Last 1
    if (-not $winSdk -or [int]$winSdk.Name.Split('.')[2] -lt 26100) {
        Fail "hace falta el Windows 11 SDK 10.0.26100 o superior (instálalo desde el instalador de Visual Studio)"
    }
    if (-not (Test-Path (Join-Path $kits 'Debuggers\x64\dbghelp.dll'))) {
        Write-Host "AVISO: faltan las 'Debugging Tools for Windows' del SDK; si el build falla por dbghelp.dll," -ForegroundColor Yellow
        Write-Host "       instálalas en Aplicaciones > Windows Software Development Kit > Modificar." -ForegroundColor Yellow
    }
    $vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
    $lines = cmd /c "`"$vcvars`" $($winSdk.Name) >nul && set"
    foreach ($line in $lines) {
        if ($line -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
    }
    if (-not $env:WindowsSDKVersion) { Fail "vcvars64.bat no configuró el entorno de MSVC" }
    Write-Host "MSVC: $vs / Windows SDK $($winSdk.Name)"
}

function Set-BuildEnv {
    Import-VsEnv
    $node = Join-Path $Tools "node\node-$NodeVersion-win-x64"
    $env:PATH = "$(Join-Path $Venv 'Scripts');$node;$(Join-Path $Tools 'gperf\bin');$(Join-Path $Tools 'bison');$env:PATH"
    # El ninja interior de Chromium solo lee NINJAFLAGS al configurar (ver
    # add_ninja_command en cmake/Functions.cmake); sin él lanza un compilador
    # por núcleo y el equipo se queda sin memoria
    $env:NINJAFLAGS = "-j$Jobs"
}

function Invoke-Build {
    Set-BuildEnv
    New-Item -ItemType Directory -Force $Build | Out-Null
    Push-Location $Build
    try {
        if (-not (Test-Path 'build.ninja')) {
            $log = Join-Path $WorkDir 'configure.log'
            & cmake -G Ninja $Src `
                "-DCMAKE_PREFIX_PATH=$Sdk" `
                "-DCMAKE_INSTALL_PREFIX=$Install" `
                -DCMAKE_BUILD_TYPE=Release `
                -DFEATURE_webengine_proprietary_codecs=ON `
                -DFEATURE_qtpdf_build=OFF `
                "-DPython3_EXECUTABLE=$VPy" | Tee-Object -FilePath $log
            if ($LASTEXITCODE -ne 0) { Fail "cmake falló (ver $log)" }
            if (Select-String -Path $log -Pattern "won't be built" -Quiet) {
                Fail "faltan dependencias (ver $log)"
            }
            if (-not (Select-String -Path 'CMakeCache.txt' -Pattern 'QT_FEATURE_webengine_proprietary_codecs:INTERNAL=ON' -Quiet)) {
                Fail "proprietary_codecs no quedó activado"
            }
        }
        # Si se configuró con otro -Jobs, ajustar el -j del ninja interior
        $ninjaFile = Join-Path $Build 'build.ninja'
        $text = [IO.File]::ReadAllText($ninjaFile)
        $patched = [regex]::Replace($text, '(ninja(?:\.exe)?)(?: -j\d+)? -C (\S*core[\\/]Release)', "`$1 -j$Jobs -C `$2")
        if ($patched -ne $text) { [IO.File]::WriteAllText($ninjaFile, $patched) }

        # Prioridad baja (la heredan los compiladores) para que el PC siga usable
        [Diagnostics.Process]::GetCurrentProcess().PriorityClass = 'BelowNormal'
        Invoke-Checked 'ninja' @('-j1')
        Invoke-Checked 'cmake' @('--install', '.')
    } finally {
        Pop-Location
    }
}

function Find-Built([string]$Filter, [switch]$Directory) {
    $item = Get-ChildItem $Install -Recurse -Filter $Filter -Directory:$Directory -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $item) { Fail "no hay $Filter en $Install (compila primero sin argumentos)" }
    return $item.FullName
}

function Install-IntoPySide6 {
    $core = Find-Built 'Qt6WebEngineCore.dll'
    $proc = Find-Built 'QtWebEngineProcess.exe'
    $res = Join-Path $Install 'resources'
    $locales = Find-Built 'qtwebengine_locales' -Directory
    $dstCore = Join-Path $PySideDir 'Qt6WebEngineCore.dll'
    $dstProc = Join-Path $PySideDir 'QtWebEngineProcess.exe'
    $dstRes = Join-Path $PySideDir 'resources'
    $dstLocales = Join-Path $PySideDir 'translations\qtwebengine_locales'
    if (-not (Test-Path $dstCore)) { Fail "no está $dstCore (¿falta PySide6_Addons?)" }

    if (-not (Test-Path $Backup)) {
        Write-Host "Copia de seguridad del Qt WebEngine original en $Backup"
        New-Item -ItemType Directory -Force (Join-Path $Backup 'resources'), (Join-Path $Backup 'qtwebengine_locales') | Out-Null
        Copy-Item $dstCore, $dstProc $Backup
        Copy-Item (Join-Path $dstRes '*') (Join-Path $Backup 'resources') -Recurse
        Copy-Item (Join-Path $dstLocales '*') (Join-Path $Backup 'qtwebengine_locales')
    }
    Copy-Item -Force $core $dstCore
    Copy-Item -Force $proc $dstProc
    Copy-Item -Force (Join-Path $res '*') $dstRes -Recurse
    Copy-Item -Force (Join-Path $locales '*.pak') $dstLocales
    Write-Host "Instalado. Comprueba: $Python tools\check_codecs.py"
}

function Restore-Original {
    if (-not (Test-Path $Backup)) { Fail "no hay copia de seguridad en $Backup" }
    Copy-Item -Force (Join-Path $Backup 'Qt6WebEngineCore.dll'), (Join-Path $Backup 'QtWebEngineProcess.exe') $PySideDir
    Copy-Item -Force (Join-Path $Backup 'resources\*') (Join-Path $PySideDir 'resources') -Recurse
    Copy-Item -Force (Join-Path $Backup 'qtwebengine_locales\*') (Join-Path $PySideDir 'translations\qtwebengine_locales')
    Write-Host "Restaurado el Qt WebEngine original de PySide6."
}

function Test-Built {
    return [bool](Get-ChildItem $Install -Recurse -Filter 'Qt6WebEngineCore.dll' -ErrorAction SilentlyContinue)
}

switch ($Action) {
    'all' {
        # build_windows.bat recrea venv_build en cada build: si la compilación
        # ya está hecha solo se reinstala (segundos en vez de horas)
        if (-not (Test-Built)) { Get-Tools; Get-Sources; Invoke-Build }
        Install-IntoPySide6
    }
    'build'        { Get-Tools; Get-Sources; Invoke-Build }
    'install-only' { Install-IntoPySide6 }
    'restore'      { Restore-Original }
}
exit 0
