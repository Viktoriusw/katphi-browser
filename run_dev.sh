#!/usr/bin/env bash
# Lanza Katphi desde el código fuente en modo desarrollo: carga los plugins
# marcados con "dev_mode": true en plugins/plugin_config.json (p. ej. katphi_tv)
# aunque sean premium y no haya licencia. Solo funciona desde el código fuente.
cd "$(dirname "$0")"
KATPHI_DEV=1 exec python3 main.py "$@"
