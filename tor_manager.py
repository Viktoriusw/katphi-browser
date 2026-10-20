#!/usr/bin/env python3
"""
Gestión del proceso Tor para Katphi Browser.

Ciclo de vida del proceso Tor usando stem, con estados:
STOPPED, STARTING, BOOTSTRAPPING(0-100%), CONNECTED, ERROR.

El proceso Tor muere automáticamente si el proceso Python termina (__OwningControllerProcess).
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


# Variable de entorno con la contraseña del ControlPort del Tor que lanzamos.
# Sobrevive a os.execv (reinicio con/sin Tor) para poder pararlo después.
_CONTROL_PW_ENV = "KATPHI_TOR_CONTROL_PW"


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
            self._control_password: Optional[str] = os.environ.get(_CONTROL_PW_ENV) or None
            self._cancel_requested = False
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
        # C-007: se lanza Tor con Popen propio (en lugar de
        # stem.process.launch_tor_with_config, que no devuelve el Popen hasta
        # terminar el bootstrap). Así self._process existe desde el primer
        # momento y stop() puede terminarlo si el usuario cancela.
        # __OwningControllerProcess equivale a take_ownership=True de stem:
        # Tor se cierra solo si muere este proceso.
        torrc_path = data_dir.parent / "torrc"
        try:
            lines = []
            for key, value in config.items():
                for v in (value if isinstance(value, list) else [value]):
                    lines.append(f"{key} {v}")
            fd = os.open(str(torrc_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            cmd = [
                tor_bin, "-f", str(torrc_path),
                "__OwningControllerProcess", str(os.getpid()),
            ]
            logger.debug("[TOR] Lanzando Tor: %s", cmd[0])
            popen_kwargs = {}
            if platform.system() == "Windows":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._cancel_requested = False
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                **popen_kwargs,
            )
            self._process = proc
            # Disponible tras un execv (el entorno se conserva) para poder
            # pararlo por ControlPort aunque se haya perdido el Popen.
            os.environ[_CONTROL_PW_ENV] = self._control_password
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

        # Leer la salida hasta "Bootstrapped 100%". Si stop() termina el
        # proceso, readline() devuelve "" y se sale del bucle.
        problem_pattern = re.compile(r"\[(warn|err)\] (.*)$")
        last_problem = None
        bootstrapped = False
        try:
            for line in iter(proc.stdout.readline, ""):
                init_msg_handler(line)
                m = problem_pattern.search(line.strip())
                if m:
                    last_problem = m.group(2)
                if "Bootstrapped 100%" in line:
                    bootstrapped = True
                    break
        except Exception as e:
            logger.debug("[TOR] Lectura de la salida de Tor interrumpida: %s", e)

        if self._cancel_requested or self._process is not proc:
            logger.info("[TOR] Bootstrap cancelado por el usuario")
            self._status = TorStatus.STOPPED
            return False
        if not bootstrapped:
            self._status = TorStatus.ERROR
            self._error_message = last_problem or "Tor terminó inesperadamente"
            logger.error("[TOR] Tor no completó el bootstrap: %s", self._error_message)
            self.stop()
            return False

        # Seguir vaciando stdout en segundo plano: si nadie lo lee, la tubería
        # se llena y Tor se bloquea al escribir su log.
        def _drain(stream) -> None:
            try:
                for _ in iter(stream.readline, ""):
                    pass
            except Exception:
                pass
        import threading
        threading.Thread(target=_drain, args=(proc.stdout,), daemon=True,
                         name="tor-stdout").start()

        # Esperar a que SOCKS5 esté listo
        import time
        start = time.time()
        while time.time() - start < 10:
            if self._cancel_requested or self._process is not proc:
                self._status = TorStatus.STOPPED
                return False
            if proc.poll() is not None:
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
        """Termina el proceso Tor limpiamente.

        Puede llamarse desde el hilo de la GUI mientras start() espera el
        bootstrap en un QThread: al terminar el proceso, start() sale.
        Si no tenemos el Popen (p. ej. tras un reinicio con execv) pero sí la
        contraseña del ControlPort, se pide a Tor que se cierre (SIGNAL HALT).
        """
        self._cancel_requested = True
        proc = self._process
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._process = None
        elif TOR_AVAILABLE and self._control_password and self.is_socks5_ready(timeout=0.5):
            try:
                from stem.control import Controller
                from stem import Signal
                with Controller.from_port(port=self.TOR_CONTROL_PORT) as ctrl:
                    ctrl.authenticate(password=self._control_password)
                    ctrl.signal(Signal.HALT)
                logger.info("[TOR] Tor detenido vía ControlPort (HALT)")
            except Exception as e:
                logger.debug("[TOR] No se pudo detener Tor vía ControlPort: %s", e)
        os.environ.pop(_CONTROL_PW_ENV, None)
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
