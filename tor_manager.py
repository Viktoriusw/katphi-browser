#!/usr/bin/env python3
"""
Gestión del proceso Tor para Katphi Browser.

Ciclo de vida del proceso Tor usando stem, con estados:
STOPPED, STARTING, BOOTSTRAPPING(0-100%), CONNECTED, ERROR.

El proceso Tor muere automáticamente si el proceso Python termina (take_ownership=True).
"""

import logging
import os
import platform
import re
import shutil
import socket
import subprocess
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Degradación graceful si stem no está instalado
TOR_AVAILABLE = False
get_hash = None
try:
    import stem.process
    import stem.control
    try:
        from stem.util.term import get_hash
    except ImportError:
        pass  # stem.util.term.get_hash no existe en versiones antiguas (ej. stem de apt)
    TOR_AVAILABLE = True
except ImportError:
    pass


def _hash_control_password(password: str, tor_binary: str = "tor") -> str:
    """
    Genera hash para HashedControlPassword.
    Usa stem.util.term.get_hash si existe, sino subprocess a tor --hash-password.
    """
    if get_hash is not None:
        return get_hash(password)
    # Fallback: tor --hash-password (compatible con stem de sistema/apt)
    try:
        proc = subprocess.run(
            [tor_binary, "--hash-password", password],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            for line in proc.stdout.strip().split("\n"):
                if line.startswith("16:"):
                    return line.strip()
    except Exception as e:
        logger.warning("[TOR] Fallback hash-password falló: %s", e)
    return ""


class TorStatus(Enum):
    """Estados del proceso Tor."""
    STOPPED = "stopped"
    STARTING = "starting"
    BOOTSTRAPPING = "bootstrapping"
    CONNECTED = "connected"
    ERROR = "error"


class TorManager:
    """
    Singleton que gestiona el ciclo de vida del proceso Tor.
    Solo puede existir una instancia activa.
    """

    # 9150/9151: evita conflicto con Tor del sistema (9050/9051)
    TOR_SOCKS_PORT = 9150
    TOR_CONTROL_PORT = 9151
    TOR_BINARY = "tor"
    BOOTSTRAP_TIMEOUT = 120

    _instance: Optional["TorManager"] = None
    _process = None

    def __new__(cls) -> "TorManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._process = None
            self._status = TorStatus.STOPPED
            self._control_password: Optional[str] = None
            self._bootstrap_percent = 0
            self._error_message: Optional[str] = None
            self._initialized = True
    def is_socks5_ready(self, timeout: float = 2.0) -> bool:
        """Verifica que el puerto SOCKS5 acepte conexiones TCP."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex(("127.0.0.1", self.TOR_SOCKS_PORT))
            sock.close()
            ready = result == 0
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[TOR] is_socks5_ready(127.0.0.1:%s) -> %s", self.TOR_SOCKS_PORT, ready)
            return ready
        except Exception as e:
            logger.debug("[TOR] is_socks5_ready falló: %s", e)
            return False
    def _find_tor_binary(self) -> Optional[str]:
        """Detecta el binario tor en el sistema."""
        candidates = ["/usr/bin/tor", "/usr/local/bin/tor"]
        if platform.system() == "Windows":
            candidates.extend([
                os.path.expandvars(r"%LOCALAPPDATA%\Tor\tor.exe"),
                r"C:\Program Files\Tor\tor.exe",
            ])
        for path in candidates:
            if path and os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        found = shutil.which("tor")
        return found
    def _get_install_instructions(self) -> str:
        """Instrucciones de instalación según el sistema operativo."""
        system = platform.system()
        if system == "Linux":
            return (
                "Para instalar Tor en Linux:\n\n"
                "• Debian/Ubuntu: sudo apt install tor\n"
                "• Fedora: sudo dnf install tor\n"
                "• Arch: sudo pacman -S tor\n\n"
                "Luego reinicie el navegador."
            )
        if system == "Darwin":
            return (
                "Para instalar Tor en macOS:\n\n"
                "• brew install tor\n\n"
                "O descargue Tor Expert Bundle desde torproject.org"
            )
        if system == "Windows":
            return (
                "Para instalar Tor en Windows:\n\n"
                "Descargue Tor Expert Bundle desde:\n"
                "https://www.torproject.org/download/tor/\n\n"
                "Extraiga y añada la carpeta al PATH, o coloque tor.exe en:\n"
                "%LOCALAPPDATA%\\Tor\\"
            )
        return "Instale Tor desde https://www.torproject.org/download/"
    def get_availability_error(self) -> Optional[str]:
        """
        Retorna mensaje de error si Tor no está disponible.
        None si todo está correcto.
        """
        if not TOR_AVAILABLE:
            return (
                "La librería 'stem' no está instalada.\n\n"
                "Ejecute: pip install stem\n\n"
                "Luego reinicie el navegador."
            )
        tor_path = self._find_tor_binary()
        if not tor_path:
            return (
                "El binario 'tor' no se encontró en el sistema.\n\n"
                f"{self._get_install_instructions()}"
            )
        return None
    def start(self, progress_callback: Optional[Callable[[int], None]] = None) -> bool:
        """
        Inicia el proceso Tor y espera bootstrap completo.

        Si SOCKS5 ya está escuchando en nuestros puertos (p. ej. Tor huérfano tras reinicio),
        no lanza otro proceso para evitar "Failed to bind one of the listener ports".

        Args:
            progress_callback: Llamado con el porcentaje (0-100) durante bootstrap.
        Returns:
            True si bootstrap exitoso o Tor ya estaba activo, False en caso contrario.
        """
        err = self.get_availability_error()
        if err:
            self._status = TorStatus.ERROR
            self._error_message = err
            logger.error("[TOR] %s", err)
            return False
        if self._process is not None and self._process.poll() is None:
            logger.debug("[TOR] Proceso Tor ya corriendo (PID=%s)", self._process.pid)
            self._status = TorStatus.CONNECTED
            return True
        # Tor ya escuchando (p. ej. proceso huérfano tras reinicio) → no lanzar otro
        if self.is_socks5_ready():
            logger.info(
                "[TOR] SOCKS5 ya activo en 127.0.0.1:%s. "
                "Reutilizando Tor existente (evitando conflicto de puertos).",
                self.TOR_SOCKS_PORT,
            )
            self._status = TorStatus.CONNECTED
            self._bootstrap_percent = 100
            if progress_callback:
                progress_callback(100)
            return True
        logger.debug("[TOR] Iniciando proceso Tor (SOCKS=%s, Control=%s)", self.TOR_SOCKS_PORT, self.TOR_CONTROL_PORT)
        self._status = TorStatus.STARTING
        self._bootstrap_percent = 0
        self._error_message = None

        # Generar contraseña aleatoria para Control Port
        import secrets
        self._control_password = secrets.token_hex(16)
        tor_bin = self._find_tor_binary() or "tor"
        hashed = _hash_control_password(self._control_password, tor_bin)
        if not hashed:
            self._status = TorStatus.ERROR
            self._error_message = "No se pudo generar hash de contraseña (tor --hash-password)"
            return False
        data_dir = Path.home() / ".katphi" / "tor" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        data_dir_str = str(data_dir)

        # Tor debe loguear a stdout para que init_msg_handler reciba el progreso
        config = {
            "SocksPort": str(self.TOR_SOCKS_PORT),
            "ControlPort": str(self.TOR_CONTROL_PORT),
            "HashedControlPassword": hashed,
            "DataDirectory": data_dir_str,
            "Log": ["NOTICE stdout"],
        }

        bootstrap_pattern = re.compile(r"Bootstrapped\s+(\d+)%")

        def init_msg_handler(line: str) -> None:
            match = bootstrap_pattern.search(line)
            if match:
                pct = int(match.group(1))
                self._bootstrap_percent = pct
                self._status = TorStatus.BOOTSTRAPPING
                if progress_callback:
                    progress_callback(pct)
        try:
            logger.debug("[TOR] Llamando stem.process.launch_tor_with_config (timeout=None, take_ownership=True)")
            # timeout=None: stem solo permite timeout en el hilo principal.
            # Llamamos desde QThread, así que sin timeout. El usuario puede cancelar.
            self._process = stem.process.launch_tor_with_config(
                config=config,
                init_msg_handler=init_msg_handler,
                timeout=None,
                take_ownership=True,
                close_output=False,
            )
        except OSError as e:
            self._status = TorStatus.ERROR
            self._error_message = str(e)
            logger.error(
                "[TOR] Error al iniciar Tor: %s. "
                "Si los puertos %s/%s están ocupados, otro Tor puede estar corriendo.",
                e, self.TOR_SOCKS_PORT, self.TOR_CONTROL_PORT,
            )
            return False
        except Exception as e:
            self._status = TorStatus.ERROR
            self._error_message = str(e)
            logger.exception("[TOR] Error inesperado: %s", e)
            return False
        # Esperar a que SOCKS5 esté listo
        import time
        start = time.time()
        while time.time() - start < 10:
            if self._process.poll() is not None:
                self._status = TorStatus.ERROR
                self._error_message = "Tor terminó inesperadamente"
                return False
            if self.is_socks5_ready():
                logger.debug("[TOR] Puerto SOCKS5 listo tras %.1fs", time.time() - start)
                self._status = TorStatus.CONNECTED
                self._bootstrap_percent = 100
                if progress_callback:
                    progress_callback(100)
                return True
            time.sleep(0.2)
        logger.error("[TOR] Timeout (10s) esperando puerto SOCKS5 en 127.0.0.1:%s", self.TOR_SOCKS_PORT)
        self._status = TorStatus.ERROR
        self._error_message = "Timeout esperando puerto SOCKS5"
        self.stop()
        return False
    def stop(self) -> None:
        """Termina el proceso Tor limpiamente."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._status = TorStatus.STOPPED
        self._bootstrap_percent = 0
    def request_new_identity(self) -> bool:
        """Solicita nuevo circuito vía Control Port (nueva IP de salida)."""
        if not TOR_AVAILABLE or self._control_password is None:
            return False
        if not self.is_socks5_ready():
            return False
        try:
            from stem.control import Controller
            from stem import Signal
            with Controller.from_port(port=self.TOR_CONTROL_PORT) as ctrl:
                ctrl.authenticate(password=self._control_password)
                ctrl.signal(Signal.NEWNYM)
            return True
        except Exception as e:
            logger.error("[TOR] Error en NEWNYM: %s", e)
            return False
    @property
    def status(self) -> TorStatus:
        return self._status
    @property
    def bootstrap_percent(self) -> int:
        return self._bootstrap_percent
    @property
    def error_message(self) -> Optional[str]:
        return self._error_message
