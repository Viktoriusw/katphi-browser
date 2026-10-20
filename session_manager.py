#!/usr/bin/env python3
"""
Session Manager - Gestor avanzado de sesiones del navegador

Características:
- Restauración automática tras crash
- Múltiples sesiones guardadas con nombre
- Guardado de estado de scroll
- Guardado de estado de formularios
- Opción de restaurar sesión anterior al inicio
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QLineEdit, QLabel


def _is_private_mode() -> bool:
    """True si este proceso es una ventana privada (--private)."""
    try:
        from constants import is_private_mode
        return is_private_mode()
    except Exception:
        return "--private" in sys.argv


class SessionManager:
    """Gestor avanzado de sesiones"""

    SESSIONS_DIR = "sessions"
    CURRENT_SESSION_FILE = "current_session.json"
    CRASH_RECOVERY_FILE = "crash_recovery.json"
    LAST_SESSION_FILE = "last_session.json"

    def __init__(self, parent=None):
        self.parent = parent
        self.settings = QSettings("Katphi", "SessionManager")

        # A-001: en la ventana privada no se escribe nada de sesión en disco
        self.private_mode = _is_private_mode()

        # Crear directorio de sesiones si no existe
        if not self.private_mode:
            Path(self.SESSIONS_DIR).mkdir(exist_ok=True)

        # Verificar si hay sesión de crash al iniciar
        self.has_crash_session = False if self.private_mode else self.check_crash_recovery()

        # Timer para auto-guardado (no en modo privado)
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.autosave_current_session)
        if not self.private_mode:
            self.autosave_timer.start(30000)  # Auto-guardar cada 30 segundos
    def check_crash_recovery(self):
        """Verificar si existe sesión de recuperación tras crash"""
        crash_file = Path(self.CRASH_RECOVERY_FILE)
        return crash_file.exists() and crash_file.stat().st_size > 0
    def show_crash_recovery_dialog(self):
        """Mostrar diálogo de recuperación tras crash"""
        if not self.has_crash_session:
            return False
        reply = QMessageBox.question(
            self.parent,
            "Recuperar sesión",
            "El navegador se cerró inesperadamente.\n¿Deseas restaurar la sesión anterior?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            return self.restore_crash_session()
        else:
            # Limpiar archivo de crash
            self.clear_crash_recovery()
            return False
    def restore_crash_session(self):
        """Restaurar sesión desde archivo de crash"""
        try:
            with open(self.CRASH_RECOVERY_FILE, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            self.restore_session_data(session_data)

            # Limpiar archivo de crash después de restaurar
            self.clear_crash_recovery()

            QMessageBox.information(
                self.parent,
                "Sesión restaurada",
                "La sesión anterior ha sido restaurada correctamente."
            )
            return True
        except Exception as e:
            print(f"[SessionManager] Error restoring crash session: {e}")
            QMessageBox.warning(
                self.parent,
                "Error",
                f"No se pudo restaurar la sesión: {e}"
            )
            return False
    def clear_crash_recovery(self):
        """Limpiar archivo de recuperación de crash"""
        try:
            crash_file = Path(self.CRASH_RECOVERY_FILE)
            if crash_file.exists():
                crash_file.unlink()
        except Exception as e:
            print(f"[SessionManager] Error clearing crash recovery: {e}")
    def autosave_current_session(self):
        """Auto-guardar sesión actual (para recuperación de crash)"""
        if self.private_mode:
            return
        if not self.parent or not hasattr(self.parent, 'tab_manager'):
            return
        try:
            session_data = self.capture_session()

            # Guardar en archivo de crash recovery
            with open(self.CRASH_RECOVERY_FILE, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            # También guardar como última sesión
            with open(self.LAST_SESSION_FILE, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SessionManager] Error autosaving session: {e}")
    def capture_session(self):
        """Capturar estado completo de la sesión actual"""
        if not self.parent or not hasattr(self.parent, 'tab_manager'):
            return {}
        tab_manager = self.parent.tab_manager
        tabs_widget = tab_manager.tabs

        tabs_data = []

        for i in range(tabs_widget.count()):
            browser = tabs_widget.widget(i)
            if not browser or not hasattr(browser, 'url'):
                continue
            url = browser.url().toString()
            title = tabs_widget.tabText(i)

            # Capturar estado de scroll (asíncrono: el valor llega en un
            # guardado posterior; el dict se fija por argumento por defecto
            # para no capturar la variable del bucle)
            scroll_data = {'x': 0, 'y': 0}

            def capture_scroll(result, scroll_data=scroll_data):
                if isinstance(result, dict):
                    scroll_data['x'] = result.get('x', 0)
                    scroll_data['y'] = result.get('y', 0)
            # JavaScript para obtener posición de scroll
            try:
                browser.page().runJavaScript(
                    "({x: window.scrollX, y: window.scrollY})",
                    capture_scroll
                )
            except Exception:
                pass

            # Capturar estado de formularios (simplificado)
            # En una implementación completa, esto capturaría todos los campos de formulario

            tab_data = {
                'url': url,
                'title': title,
                'scroll': scroll_data,
                'active': (i == tabs_widget.currentIndex()),
                'pinned': i in tab_manager.pinned_tabs if hasattr(tab_manager, 'pinned_tabs') else False
            }

            tabs_data.append(tab_data)
        session_data = {
            'timestamp': datetime.now().isoformat(),
            'tabs': tabs_data,
            'active_tab_index': tabs_widget.currentIndex()
        }

        return session_data
    def restore_session_data(self, session_data):
        """Restaurar sesión desde datos"""
        if not self.parent or not hasattr(self.parent, 'tab_manager'):
            return
        tab_manager = self.parent.tab_manager
        tabs = session_data.get('tabs', [])

        if not tabs:
            return
        # Índice de la primera pestaña restaurada (para la pestaña activa)
        base_index = None
        # Cerrar pestaña inicial vacía si existe
        if tab_manager.tabs.count() == 1:
            first_tab = tab_manager.tabs.widget(0)
            if first_tab and first_tab.url().toString() in ["", "about:blank", "https://duckduckgo.com"]:
                tab_manager.close_tab(0)
        # Restaurar cada pestaña
        for tab_data in tabs:
            url = tab_data.get('url', '')
            if not url or url == 'about:blank':
                continue
            # Crear pestaña
            browser = tab_manager.add_new_tab(url)
            if browser is None:
                continue
            if base_index is None:
                base_index = tab_manager.tabs.indexOf(browser)

            # Restaurar scroll después de que cargue la página
            scroll_data = tab_data.get('scroll', {}) or {}
            if scroll_data.get('x') or scroll_data.get('y'):
                try:
                    sx = int(scroll_data.get('x', 0))
                    sy = int(scroll_data.get('y', 0))
                except (TypeError, ValueError):
                    sx, sy = 0, 0

                # Valores fijados por argumento por defecto: cada pestaña
                # usa su propio browser y su propio scroll (no los del bucle)
                def restore_scroll(ok, browser=browser, sx=sx, sy=sy):
                    if ok:
                        browser.page().runJavaScript(f"window.scrollTo({sx}, {sy})")
                # Esperar a que cargue la página
                browser.loadFinished.connect(restore_scroll)
            # Restaurar pestaña fijada
            if tab_data.get('pinned', False):
                index = tab_manager.tabs.count() - 1
                if hasattr(tab_manager, 'pin_tab'):
                    tab_manager.pin_tab(index)
        # Restaurar pestaña activa
        active_index = session_data.get('active_tab_index', 0)
        if base_index is not None and isinstance(active_index, int):
            target = base_index + active_index
            if 0 <= target < tab_manager.tabs.count():
                tab_manager.tabs.setCurrentIndex(target)
    def save_named_session(self, session_name):
        """Guardar sesión con nombre específico"""
        if self.private_mode:
            QMessageBox.information(
                self.parent,
                "Ventana privada",
                "En una ventana privada no se guardan sesiones en disco."
            )
            return False
        try:
            session_data = self.capture_session()
            session_data['name'] = session_name

            # Sanitizar nombre de archivo
            safe_name = "".join(c for c in session_name if c.isalnum() or c in (' ', '-', '_')).strip()
            if not safe_name:
                safe_name = "sesion"
            Path(self.SESSIONS_DIR).mkdir(exist_ok=True)
            filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = Path(self.SESSIONS_DIR) / filename

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(
                self.parent,
                "Sesión guardada",
                f"La sesión '{session_name}' ha sido guardada correctamente."
            )
            return True
        except Exception as e:
            print(f"[SessionManager] Error saving named session: {e}")
            QMessageBox.warning(
                self.parent,
                "Error",
                f"No se pudo guardar la sesión: {e}"
            )
            return False
    def get_saved_sessions(self):
        """Obtener lista de sesiones guardadas"""
        sessions = []
        sessions_dir = Path(self.SESSIONS_DIR)

        if not sessions_dir.exists():
            return sessions
        for session_file in sessions_dir.glob("*.json"):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                sessions.append({
                    'filename': session_file.name,
                    'filepath': str(session_file),
                    'name': session_data.get('name', session_file.stem),
                    'timestamp': session_data.get('timestamp', ''),
                    'tab_count': len(session_data.get('tabs', []))
                })
            except Exception as e:
                print(f"[SessionManager] Error reading session {session_file}: {e}")
        # Ordenar por timestamp (más reciente primero)
        sessions.sort(key=lambda x: x['timestamp'], reverse=True)
        return sessions
    def restore_named_session(self, filepath):
        """Restaurar sesión desde archivo"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            # Preguntar si cerrar pestañas actuales
            reply = QMessageBox.question(
                self.parent,
                "Restaurar sesión",
                "¿Deseas cerrar las pestañas actuales antes de restaurar la sesión?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )

            old_tab = None
            if reply == QMessageBox.Yes and hasattr(self.parent, 'tab_manager'):
                # Cerrar todas las pestañas menos una: close_tab() nunca cierra
                # la última, así que un "while count > 0" no terminaría nunca.
                # La que queda se cierra después de abrir las restauradas.
                tab_manager = self.parent.tab_manager
                for i in range(tab_manager.tabs.count() - 1, 0, -1):
                    tab_manager.close_tab(i)
                old_tab = tab_manager.tabs.widget(0)
            self.restore_session_data(session_data)
            if old_tab is not None:
                tab_manager = self.parent.tab_manager
                idx = tab_manager.tabs.indexOf(old_tab)
                if idx != -1 and tab_manager.tabs.count() > 1:
                    tab_manager.close_tab(idx)
            return True
        except Exception as e:
            print(f"[SessionManager] Error restoring named session: {e}")
            QMessageBox.warning(
                self.parent,
                "Error",
                f"No se pudo restaurar la sesión: {e}"
            )
            return False
    def delete_named_session(self, filepath):
        """Eliminar sesión guardada"""
        try:
            Path(filepath).unlink()
            return True
        except Exception as e:
            print(f"[SessionManager] Error deleting session: {e}")
            return False
    def show_session_manager_dialog(self):
        """Mostrar diálogo de gestión de sesiones"""
        dialog = SessionManagerDialog(self, self.parent)
        dialog.exec()
    def on_browser_close(self):
        """Llamar al cerrar el navegador normalmente"""
        if self.private_mode:
            return
        # Guardar sesión actual como última sesión
        self.autosave_current_session()

        # Limpiar archivo de crash recovery (cierre normal)
        self.clear_crash_recovery()


class SessionManagerDialog(QDialog):
    """Diálogo para gestionar sesiones guardadas"""

    def __init__(self, session_manager, parent=None):
        super().__init__(parent)
        self.session_manager = session_manager

        self.setWindowTitle("Gestor de sesiones")
        self.setMinimumSize(600, 400)

        self.setup_ui()
        self.refresh_sessions()
    def setup_ui(self):
        """Configurar interfaz"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Sesiones guardadas")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        # Lista de sesiones
        self.sessions_list = QListWidget()
        self.sessions_list.itemDoubleClicked.connect(self.restore_selected)
        layout.addWidget(self.sessions_list)

        # Botones de acción
        buttons_layout = QHBoxLayout()

        save_btn = QPushButton("Guardar sesión actual")
        save_btn.clicked.connect(self.save_current)
        buttons_layout.addWidget(save_btn)

        restore_btn = QPushButton("Restaurar")
        restore_btn.clicked.connect(self.restore_selected)
        buttons_layout.addWidget(restore_btn)

        delete_btn = QPushButton("Eliminar")
        delete_btn.clicked.connect(self.delete_selected)
        buttons_layout.addWidget(delete_btn)

        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.close)
        buttons_layout.addWidget(close_btn)

        layout.addLayout(buttons_layout)
    def refresh_sessions(self):
        """Actualizar lista de sesiones"""
        self.sessions_list.clear()
        sessions = self.session_manager.get_saved_sessions()

        for session in sessions:
            item_text = f"{session['name']} - {session['tab_count']} pestañas - {session['timestamp'][:19]}"
            self.sessions_list.addItem(item_text)

            # Guardar filepath en item data
            item = self.sessions_list.item(self.sessions_list.count() - 1)
            item.setData(Qt.UserRole, session['filepath'])
    def save_current(self):
        """Guardar sesión actual"""
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self,
            "Guardar sesión",
            "Nombre de la sesión:"
        )

        if ok and name:
            if self.session_manager.save_named_session(name):
                self.refresh_sessions()
    def restore_selected(self):
        """Restaurar sesión seleccionada"""
        current_item = self.sessions_list.currentItem()
        if not current_item:
            return
        filepath = current_item.data(Qt.UserRole)
        if self.session_manager.restore_named_session(filepath):
            self.close()
    def delete_selected(self):
        """Eliminar sesión seleccionada"""
        current_item = self.sessions_list.currentItem()
        if not current_item:
            return
        reply = QMessageBox.question(
            self,
            "Eliminar sesión",
            "¿Estás seguro de eliminar esta sesión?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            filepath = current_item.data(Qt.UserRole)
            if self.session_manager.delete_named_session(filepath):
                self.refresh_sessions()
