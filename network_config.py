#!/usr/bin/env python3


"""


Configuraci?n de red robusta para Katphi Browser


Manejo avanzado de conectividad con fallbacks y verificaci?n


"""


import os


import socket


import requests


import time


from typing import Dict, Any, Optional, List, Tuple


from dataclasses import dataclass


from enum import Enum


class NetworkStatus(Enum):
    """Estados de conectividad de red"""

    UNKNOWN = "unknown"

    CONNECTED = "connected"

    DISCONNECTED = "disconnected"

    TIMEOUT = "timeout"

    ERROR = "error"


@dataclass


class NetworkEndpoint:
    """Informaci?n de un endpoint de red"""

    name: str

    url: str

    ip: str

    port: int

    timeout: int = 5

    retries: int = 3

    status: NetworkStatus = NetworkStatus.UNKNOWN

    last_check: float = 0.0

    response_time: float = 0.0


# Configuraci?n de red


NETWORK_CONFIG = {


    # Modo de red: 'localhost' o 'network'

    "mode": "network",  # Cambiar a 'localhost' para desarrollo local

    # Configuraci?n para red interna

    "network": {

        "backend_ip": "api.katphi.com",  # Backend API

        "website_ip": "katphi.com",  # Sitio Web

        "backend_port": 443,  # HTTPS vía Cloudflare Tunnel

        "website_port": 443,

        "timeout": 10,  # Timeout por defecto

        "retries": 3,   # Reintentos por defecto
    },

    # Configuraci?n para localhost

    "localhost": {

        "server_ip": "localhost",

        "backend_port": 8000,

        "website_port": 8001,

        "timeout": 5,

        "retries": 2,
    }


}


# Endpoints de fallback


FALLBACK_ENDPOINTS = {


    "backend": [

        "https://api.katphi.com",
    ],

    "website": [

        "https://katphi.com",
    ]


}


class NetworkManager:
    """Gestor de conectividad de red con fallbacks"""

    def __init__(self):
        self.endpoints: Dict[str, NetworkEndpoint] = {}

        self._initialize_endpoints()
    def _initialize_endpoints(self):
        """Inicializar endpoints de red"""

        config = self._get_base_config()

        # Backend endpoint

        self.endpoints["backend"] = NetworkEndpoint(

            name="Backend API",

            url=f"{'https' if config['backend_port'] == 443 else 'http'}://{config['backend_ip']}:{config['backend_port']}",

            ip=config["backend_ip"],

            port=config["backend_port"],

            timeout=config.get("timeout", 10),

            retries=config.get("retries", 3)
        )

        # Website endpoint

        self.endpoints["website"] = NetworkEndpoint(

            name="Website",

            url=f"{'https' if config['website_port'] == 443 else 'http'}://{config['website_ip']}:{config['website_port']}",

            ip=config["website_ip"],

            port=config["website_port"],

            timeout=config.get("timeout", 10),

            retries=config.get("retries", 3)
        )
    def _get_base_config(self) -> Dict[str, Any]:
        """Obtener configuraci?n base"""

        mode = os.getenv("KATPHI_NETWORK_MODE", NETWORK_CONFIG["mode"])

        if mode == "network":
            return NETWORK_CONFIG["network"]
        else:
            return NETWORK_CONFIG["localhost"]
    def check_connectivity(self, endpoint_name: str, force_check: bool = False) -> NetworkStatus:
        """Verificar conectividad de un endpoint"""

        if endpoint_name not in self.endpoints:
            return NetworkStatus.ERROR
        endpoint = self.endpoints[endpoint_name]

        # Si ya se verific? recientemente y no se fuerza, usar estado actual

        if not force_check and time.time() - endpoint.last_check < 30:
            return endpoint.status
        try:
            start_time = time.time()

            # Verificar conectividad TCP primero

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            sock.settimeout(endpoint.timeout)

            result = sock.connect_ex((endpoint.ip, endpoint.port))

            sock.close()

            if result != 0:
                endpoint.status = NetworkStatus.DISCONNECTED

                endpoint.last_check = time.time()

                return endpoint.status
            # Verificar HTTP si es posible

            try:
                response = requests.get(

                    f"{endpoint.url}/health" if endpoint_name == "backend" else endpoint.url,

                    timeout=endpoint.timeout
                )

                if response.status_code == 200:
                    endpoint.status = NetworkStatus.CONNECTED

                    endpoint.response_time = time.time() - start_time
                else:
                    endpoint.status = NetworkStatus.ERROR
            except requests.exceptions.RequestException:
                endpoint.status = NetworkStatus.TIMEOUT
            endpoint.last_check = time.time()

            return endpoint.status
        except Exception as e:
            endpoint.status = NetworkStatus.ERROR

            endpoint.last_check = time.time()

            return endpoint.status
    def get_working_endpoint(self, endpoint_name: str) -> Optional[str]:
        """Obtener un endpoint funcional con fallback"""

        # Verificar endpoint principal

        if self.check_connectivity(endpoint_name) == NetworkStatus.CONNECTED:
            return self.endpoints[endpoint_name].url
        # Probar endpoints de fallback

        fallback_urls = FALLBACK_ENDPOINTS.get(endpoint_name, [])

        for url in fallback_urls:
            try:
                response = requests.get(f"{url}/health" if endpoint_name == "backend" else url, timeout=5)

                if response.status_code == 200:
                    return url
            except:
                continue
        return None
    def get_backend_url(self) -> str:
        """Obtener URL del backend con fallback"""

        working_url = self.get_working_endpoint("backend")

        if working_url:
            return working_url
        # Fallback a configuraci?n por defecto

        config = self._get_base_config()

        scheme = 'https' if config['backend_port'] == 443 else 'http'

        return f"{scheme}://{config['backend_ip']}:{config['backend_port']}"
    def get_website_url(self) -> str:
        """Obtener URL del sitio web con fallback"""

        working_url = self.get_working_endpoint("website")

        if working_url:
            return working_url
        # Fallback a configuraci?n por defecto

        config = self._get_base_config()

        scheme = 'https' if config['website_port'] == 443 else 'http'

        return f"{scheme}://{config['website_ip']}:{config['website_port']}"
    def get_all_status(self) -> Dict[str, NetworkStatus]:
        """Obtener estado de todos los endpoints"""

        status = {}

        for endpoint_name in self.endpoints:
            status[endpoint_name] = self.check_connectivity(endpoint_name)
        return status


# Instancia global del gestor de red


_network_manager = NetworkManager()


def get_config() -> Dict[str, Any]:
    """Obtener configuraci?n de red actual (compatible con versi?n anterior)"""

    mode = os.getenv("KATPHI_NETWORK_MODE", NETWORK_CONFIG["mode"])

    if mode == "network":
        config = NETWORK_CONFIG["network"]

        return {

            "mode": mode,

            "backend_ip": config["backend_ip"],

            "website_ip": config["website_ip"],

            "backend_port": config["backend_port"],

            "website_port": config["website_port"],

            "backend_url": _network_manager.get_backend_url(),

            "website_url": _network_manager.get_website_url(),

            "timeout": config.get("timeout", 10),

            "retries": config.get("retries", 3),
        }
    else:
        config = NETWORK_CONFIG["localhost"]

        return {

            "mode": mode,

            "server_ip": config["server_ip"],

            "backend_port": config["backend_port"],

            "website_port": config["website_port"],

            "backend_url": f"http://{config['server_ip']}:{config['backend_port']}",

            "website_url": f"http://{config['server_ip']}:{config['website_port']}",

            "timeout": config.get("timeout", 5),

            "retries": config.get("retries", 2),
        }


def get_backend_url() -> str:
    """Obtener URL del backend con verificaci?n de conectividad"""

    return _network_manager.get_backend_url()


def get_website_url() -> str:
    """Obtener URL del sitio web con verificaci?n de conectividad"""

    return _network_manager.get_website_url()


def get_registration_url() -> str:
    """Obtener URL de registro"""

    return f"{get_website_url()}/auth/registro.html"


def check_network_health() -> Dict[str, Any]:
    """Verificar salud de la red"""

    status = _network_manager.get_all_status()

    config = get_config()

    return {

        "config": config,

        "status": {name: status.value for name, status in status.items()},

        "backend_url": get_backend_url(),

        "website_url": get_website_url(),

        "all_connected": all(s == NetworkStatus.CONNECTED for s in status.values())
    }


def print_network_info():
    """Imprimir informaci?n detallada de la configuraci?n de red"""

    health = check_network_health()

    config = health["config"]

    status = health["status"]

    print("=" * 80)

    print("CONFIGURACION DE RED - KATPHI BROWSER")

    print("=" * 80)

    print(f"Modo: {config['mode']}")

    print(f"Backend API: {health['backend_url']} [{status.get('backend', 'unknown')}]")

    print(f"Sitio Web: {health['website_url']} [{status.get('website', 'unknown')}]")

    print(f"Estado general: {'CONECTADO' if health['all_connected'] else 'PROBLEMAS'}")

    print("=" * 80)

    print()

    print("Para cambiar el modo de red:")

    print("  - Localhost: set KATPHI_NETWORK_MODE=localhost")

    print("  - Red interna: set KATPHI_NETWORK_MODE=network")

    print("=" * 80)


def test_connectivity() -> bool:
    """Probar conectividad a todos los endpoints"""

    print("Verificando conectividad...")

    backend_status = _network_manager.check_connectivity("backend", force_check=True)

    website_status = _network_manager.check_connectivity("website", force_check=True)

    print(f"Backend: {'OK' if backend_status == NetworkStatus.CONNECTED else 'FAIL'} {backend_status.value}")

    print(f"Website: {'OK' if website_status == NetworkStatus.CONNECTED else 'FAIL'} {website_status.value}")

    return backend_status == NetworkStatus.CONNECTED and website_status == NetworkStatus.CONNECTED


if __name__ == "__main__":
    print_network_info()

    test_connectivity()
