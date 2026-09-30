#!/usr/bin/env python3
"""
Script para verificar que todas las dependencias están instaladas correctamente.

PySide6 + Qt WebEngine son OBLIGATORIOS: sin ellos el navegador no arranca.
"""

import sys
import importlib

PYSIDE6_INSTALL_HINT = (
    "  → Instala PySide6 en el entorno activo:\n"
    "     pip install --upgrade \"PySide6>=6.5.0\"\n"
    "  → Comprueba que usas el Python del venv:\n"
    "     which python3   (Linux/macOS)  |  where python  (Windows)"
)


def check_dependency(module_name, package_name=None):
    """Verifica si una dependencia está instalada."""
    try:
        importlib.import_module(module_name)
        print(f"✓ {package_name or module_name} está instalado")
        return True
    except ImportError as e:
        print(f"✗ {package_name or module_name} NO está instalado: {e}")
        return False


def check_pyside6_webengine():
    """
    Verifica PySide6 y sus módulos Qt WebEngine (críticos para el navegador).

    Katphi Browser usa exclusivamente PySide6; PyQt5/PyQt6 NO son compatibles.
    """
    print("--- PySide6 (OBLIGATORIO) ---")
    print(f"  Python en uso: {sys.executable}")
    all_ok = True

    pyside_modules = [
        ("PySide6", "PySide6 (paquete base)"),
        ("PySide6.QtCore", "PySide6.QtCore"),
        ("PySide6.QtWidgets", "PySide6.QtWidgets"),
        ("PySide6.QtWebEngineCore", "PySide6.QtWebEngineCore"),
        ("PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineWidgets"),
    ]

    for module, label in pyside_modules:
        if not check_dependency(module, label):
            all_ok = False

    if all_ok:
        try:
            from PySide6 import __version__ as pyside_version
            print(f"  Versión PySide6: {pyside_version}")
        except ImportError:
            pass
    else:
        print(PYSIDE6_INSTALL_HINT)

    print()
    return all_ok


def main():
    print("Verificando dependencias de Katphi Browser...")
    print("=" * 50)

    pyside_ok = check_pyside6_webengine()

    dependencies = [
        # Núcleo
        ("requests", "requests"),
        ("socks", "PySocks"),
        ("bs4", "beautifulsoup4"),
        ("numpy", "numpy"),
        ("yaml", "PyYAML"),
        ("jwt", "PyJWT"),
        ("cryptography", "cryptography"),
        ("psutil", "psutil"),
        ("packaging", "packaging"),
        ("stem", "stem"),

        # Librerías disponibles para los plugins de la tienda
        ("lxml", "lxml"),
        ("aiohttp", "aiohttp"),
        ("aiohttp_socks", "aiohttp-socks"),
        ("pandas", "pandas"),
        ("openpyxl", "openpyxl"),
        ("PIL", "Pillow"),
        ("reportlab", "reportlab"),
        ("textstat", "textstat"),
        ("schedule", "schedule"),
    ]

    other_ok = True

    for module, package in dependencies:
        if not check_dependency(module, package):
            other_ok = False

    all_ok = pyside_ok and other_ok
    print("=" * 50)

    if not pyside_ok:
        print("CRÍTICO: PySide6 o Qt WebEngine no están instalados correctamente.")
        print("   El navegador NO funcionará sin ellos.")
        print(PYSIDE6_INSTALL_HINT)
    elif all_ok:
        print("¡Todas las dependencias están instaladas correctamente!")
        print("Puedes ejecutar el programa con: python3 main.py")
    else:
        print("Faltan dependencias secundarias. Ejecuta:")
        print("   pip install -r requirements.txt")
        if pyside_ok:
            print("   (PySide6 OK — el navegador debería arrancar)")
    return all_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
