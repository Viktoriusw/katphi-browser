"""
Runtime hook para Katphi Browser en Linux (PyInstaller, paquete .deb).

Se ejecuta ANTES que main.py.

El navegador abre y ESCRIBE sus datos (config.yaml, bookmarks.db, passwords.db,
easylist.txt, sesión de pestañas...) con rutas relativas al directorio de
trabajo. Instalado desde el .deb, la app vive en /opt/katphi-browser, que es
de solo lectura para el usuario, así que el directorio de trabajo pasa a ser una
carpeta por usuario:

    $XDG_DATA_HOME/Katphi/app   (por defecto ~/.local/share/Katphi/app)

- icons/ y plugins/ (solo lectura) se enlazan desde la instalación.
- Los ficheros editables que viajan en defaults/ se copian solo si faltan, para
  no pisar la configuración ni los datos del usuario al actualizar el paquete.
"""
import os
import shutil
import sys

if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS

    # QtWebEngine: proceso helper y recursos dentro del bundle
    os.environ.setdefault('QT_PLUGIN_PATH', os.path.join(base_dir, 'PySide6', 'Qt', 'plugins'))
    helper = os.path.join(base_dir, 'PySide6', 'Qt', 'libexec', 'QtWebEngineProcess')
    if os.path.exists(helper):
        os.environ.setdefault('QTWEBENGINEPROCESS_PATH', helper)

    data_root = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    work_dir = os.path.join(data_root, 'Katphi', 'app')
    os.makedirs(work_dir, exist_ok=True)

    # Recursos de solo lectura: enlace simbólico a la instalación
    for name in ('icons', 'plugins'):
        target = os.path.join(base_dir, name)
        link = os.path.join(work_dir, name)
        if os.path.islink(link) and os.readlink(link) != target:
            os.remove(link)
        if not os.path.lexists(link) and os.path.exists(target):
            os.symlink(target, link)

    # Ficheros editables: copiar los que falten desde defaults/
    defaults_dir = os.path.join(base_dir, 'defaults')
    for root, _dirs, files in os.walk(defaults_dir):
        rel = os.path.relpath(root, defaults_dir)
        dest_root = work_dir if rel == '.' else os.path.join(work_dir, rel)
        os.makedirs(dest_root, exist_ok=True)
        for fname in files:
            dest = os.path.join(dest_root, fname)
            if not os.path.exists(dest):
                shutil.copyfile(os.path.join(root, fname), dest)
                os.chmod(dest, 0o644)

    os.chdir(work_dir)
