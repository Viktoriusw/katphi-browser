#!/usr/bin/env python3
"""
Utilidades de seguridad para cifrado de tokens y datos sensibles.
"""

import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class TokenEncryption:
    """Clase para cifrado seguro de tokens"""

    def __init__(self):
        """Inicializa el sistema de cifrado"""
        self._key = None
        self._fernet = None
        self._initialize_encryption()
    def _initialize_encryption(self):
        """Inicializa la clave de cifrado"""
        # Generar una clave única por máquina basada en identificadores del sistema
        machine_id = self._get_machine_id()
        salt = b'katphi_browser_salt_v1'  # Salt fijo para consistencia

        # Derivar clave usando PBKDF2HMAC
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))

        self._key = key
        self._fernet = Fernet(key)
    def _get_machine_id(self) -> str:
        """Obtiene un identificador único de la máquina"""
        try:
            # En Linux, usa /etc/machine-id
            if os.path.exists('/etc/machine-id'):
                with open('/etc/machine-id', 'r') as f:
                    return f.read().strip()
            # En Windows, usa una combinación de variables de entorno
            import platform
            machine_data = f"{platform.node()}_{platform.machine()}_{os.getenv('USERNAME', 'default')}"
            return hashlib.sha256(machine_data.encode()).hexdigest()
        except Exception:
            # Fallback: usar un hash del directorio home
            home = os.path.expanduser('~')
            return hashlib.sha256(home.encode()).hexdigest()
    def encrypt(self, data: str) -> str:
        """Cifra datos sensibles y devuelve el token Fernet como string.

        Args:
            data: String a cifrar.
        Returns:
            Token cifrado Fernet (base64url) como str, o "" si falla.
        """
        if not data:
            return ""
        try:
            return self._fernet.encrypt(data.encode()).decode()
        except Exception as e:
            logger.error("Error cifrando datos: %s", e)
            return ""
    def decrypt(self, encrypted_data: str) -> str:
        """Descifra un token Fernet.

        Args:
            encrypted_data: Token Fernet como str (base64url).
        Returns:
            String descifrado, o "" si el token es inválido o está corrupto.
        """
        if not encrypted_data:
            return ""
        try:
            return self._fernet.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            err_msg = repr(e) if not str(e) else str(e)
            logger.debug("Error descifrando datos (token inválido/expirado): %s", err_msg)
            return ""
    # Alias para compatibilidad
    def encrypt_token(self, token: str) -> str:
        """Alias para encrypt() - compatibilidad con código existente"""
        return self.encrypt(token)
    def decrypt_token(self, encrypted_token: str) -> str:
        """Alias para decrypt() - compatibilidad con código existente"""
        return self.decrypt(encrypted_token)


# Instancia global
_token_encryption = None


def get_token_encryption() -> TokenEncryption:
    """Obtiene la instancia global de cifrado"""
    global _token_encryption
    if _token_encryption is None:
        _token_encryption = TokenEncryption()
    return _token_encryption
