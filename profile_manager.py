#!/usr/bin/env python3
"""
Profile Manager - Sistema de gestión de perfiles de usuario

Características:
- Múltiples perfiles con datos aislados
- Cookies, historial, marcadores y descargas separados por perfil
- Iconos y personalización por perfil
- Cambio rápido entre perfiles
- Gestión completa de perfiles (crear, editar, eliminar)
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QDialog, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QDialogButtonBox, QGroupBox, QComboBox,
                               QFrame, QMenu, QInputDialog)
from PySide6.QtCore import Qt, Signal, QObject, QDir, QStandardPaths
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
import sqlite3
import os
import shutil
from datetime import datetime
from pathlib import Path


class ProfileManager(QObject):
    """Gestor de perfiles de usuario"""

    profile_changed = Signal(str)  # Emite ID del nuevo perfil
    profile_created = Signal(str)  # Emite ID del perfil creado
    profile_deleted = Signal(str)  # Emite ID del perfil eliminado

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.current_profile_id = None
        self.profiles_dir = self._get_profiles_directory()
        self.db_path = os.path.join(self.profiles_dir, "profiles.db")

        # Asegurar que el directorio existe
        os.makedirs(self.profiles_dir, exist_ok=True)

        # Inicializar base de datos
        self.setup_database()

        # Cargar o crear perfil por defecto
        self.load_or_create_default_profile()
    def _get_profiles_directory(self):
        """Obtiene el directorio para almacenar perfiles"""
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        profiles_dir = os.path.join(app_data, "Katphi", "Profiles")
        return profiles_dir
    def setup_database(self):
        """Configura la base de datos de perfiles"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                icon TEXT,
                color TEXT,
                created_at TEXT,
                last_used TEXT,
                is_default INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
        conn.close()
    def create_profile(self, name, icon="Usuario", color="#4a90e2"):
        """
        Crea un nuevo perfil

        Args:
            name: Nombre del perfil
            icon: Categoría del perfil (Usuario, Trabajo, Personal...)
            color: Color de acento del perfil
        Returns:
            str: ID del perfil creado
        """
        # Generar ID único basado en timestamp
        profile_id = f"profile_{int(datetime.now().timestamp() * 1000)}"

        # Crear directorio del perfil
        profile_path = os.path.join(self.profiles_dir, profile_id)
        os.makedirs(profile_path, exist_ok=True)

        # Crear subdirectorios para datos aislados
        os.makedirs(os.path.join(profile_path, "cookies"), exist_ok=True)
        os.makedirs(os.path.join(profile_path, "cache"), exist_ok=True)
        os.makedirs(os.path.join(profile_path, "downloads"), exist_ok=True)
        os.makedirs(os.path.join(profile_path, "history"), exist_ok=True)
        os.makedirs(os.path.join(profile_path, "bookmarks"), exist_ok=True)

        # Guardar en base de datos
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO profiles (id, name, icon, color, created_at, last_used, is_default)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        ''', (profile_id, name, icon, color, now, now))

        conn.commit()
        conn.close()

        self.profile_created.emit(profile_id)
        return profile_id
    def load_or_create_default_profile(self):
        """Carga el perfil por defecto o lo crea si no existe"""
        profiles = self.get_all_profiles()

        if not profiles:
            # Crear perfil por defecto
            default_id = self.create_profile("Usuario Principal", "Usuario", "#4a90e2")
            self.set_default_profile(default_id)
            self.current_profile_id = default_id
        else:
            # Cargar perfil por defecto o el último usado
            default = self.get_default_profile()
            if default:
                self.current_profile_id = default['id']
            else:
                self.current_profile_id = profiles[0]['id']
    def get_all_profiles(self):
        """Obtiene todos los perfiles"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, icon, color, created_at, last_used, is_default
            FROM profiles
            ORDER BY last_used DESC
        ''')

        profiles = []
        for row in cursor.fetchall():
            profiles.append({
                'id': row[0],
                'name': row[1],
                'icon': row[2],
                'color': row[3],
                'created_at': row[4],
                'last_used': row[5],
                'is_default': bool(row[6])
            })
        conn.close()
        return profiles
    def get_profile(self, profile_id):
        """Obtiene un perfil específico"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, icon, color, created_at, last_used, is_default
            FROM profiles
            WHERE id = ?
        ''', (profile_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'id': row[0],
                'name': row[1],
                'icon': row[2],
                'color': row[3],
                'created_at': row[4],
                'last_used': row[5],
                'is_default': bool(row[6])
            }
        return None
    def get_default_profile(self):
        """Obtiene el perfil marcado como predeterminado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, name, icon, color, created_at, last_used, is_default
            FROM profiles
            WHERE is_default = 1
            LIMIT 1
        ''')

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'id': row[0],
                'name': row[1],
                'icon': row[2],
                'color': row[3],
                'created_at': row[4],
                'last_used': row[5],
                'is_default': bool(row[6])
            }
        return None
    def set_default_profile(self, profile_id):
        """Establece un perfil como predeterminado"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Quitar default de todos
        cursor.execute('UPDATE profiles SET is_default = 0')

        # Establecer nuevo default
        cursor.execute('UPDATE profiles SET is_default = 1 WHERE id = ?', (profile_id,))

        conn.commit()
        conn.close()
    def switch_profile(self, profile_id):
        """Cambia al perfil especificado"""
        profile = self.get_profile(profile_id)
        if not profile:
            return False
        # Actualizar last_used
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE profiles
            SET last_used = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), profile_id))

        conn.commit()
        conn.close()

        self.current_profile_id = profile_id
        self.profile_changed.emit(profile_id)
        return True
    def update_profile(self, profile_id, name=None, icon=None, color=None):
        """Actualiza los datos de un perfil"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if icon is not None:
            updates.append("icon = ?")
            params.append(icon)
        if color is not None:
            updates.append("color = ?")
            params.append(color)
        if updates:
            params.append(profile_id)
            query = f"UPDATE profiles SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
        conn.close()
    def delete_profile(self, profile_id):
        """Elimina un perfil"""
        # No permitir eliminar el último perfil
        profiles = self.get_all_profiles()
        if len(profiles) <= 1:
            return False
        # No permitir eliminar el perfil actual
        if profile_id == self.current_profile_id:
            return False
        # Eliminar directorio del perfil
        profile_path = os.path.join(self.profiles_dir, profile_id)
        if os.path.exists(profile_path):
            try:
                shutil.rmtree(profile_path)
            except Exception as e:
                print(f"Error eliminando directorio del perfil: {e}")
                return False
        # Eliminar de base de datos
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('DELETE FROM profiles WHERE id = ?', (profile_id,))

        conn.commit()
        conn.close()

        self.profile_deleted.emit(profile_id)
        return True
    def get_profile_path(self, profile_id=None, subdirectory=None):
        """
        Obtiene la ruta del directorio de un perfil

        Args:
            profile_id: ID del perfil (usa el actual si es None)
            subdirectory: Subdirectorio específico (cookies, cache, etc.)
        """
        if profile_id is None:
            profile_id = self.current_profile_id
        path = os.path.join(self.profiles_dir, profile_id)

        if subdirectory:
            path = os.path.join(path, subdirectory)
        return path
    def get_current_profile(self):
        """Obtiene los datos del perfil actual"""
        if self.current_profile_id:
            return self.get_profile(self.current_profile_id)
        return None


class ProfileDialog(QDialog):
    """Diálogo para crear o editar perfiles"""

    def __init__(self, profile_manager, profile_id=None, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.profile_id = profile_id
        self.is_edit_mode = profile_id is not None

        self.setWindowTitle("Editar perfil" if self.is_edit_mode else "Nuevo perfil")
        self.setModal(True)
        self.setMinimumWidth(400)

        self.setup_ui()

        if self.is_edit_mode:
            self.load_profile_data()
    def setup_ui(self):
        """Configurar interfaz del diálogo"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Editar perfil" if self.is_edit_mode else "Crear nuevo perfil")
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Nombre del perfil
        name_group = QGroupBox("Nombre del perfil")
        name_layout = QVBoxLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ej: Trabajo, Personal, Desarrollo...")
        self.name_input.setMaxLength(50)
        name_layout.addWidget(self.name_input)

        name_group.setLayout(name_layout)
        layout.addWidget(name_group)

        # Icono del perfil
        icon_group = QGroupBox("Icono del perfil")
        icon_layout = QHBoxLayout()

        self.icon_combo = QComboBox()
        self.icon_combo.addItems([
            "Usuario",
            "Trabajo",
            "Personal",
            "Gaming",
            "Estudio",
            "Desarrollo",
            "Diseño",
            "Análisis",
            "Navegación",
            "Privado"
        ])
        icon_layout.addWidget(self.icon_combo)

        icon_group.setLayout(icon_layout)
        layout.addWidget(icon_group)

        # Color del perfil
        color_group = QGroupBox("Color de acento")
        color_layout = QHBoxLayout()

        self.color_combo = QComboBox()
        self.color_combo.addItem("Azul", "#4a90e2")
        self.color_combo.addItem("Rojo", "#e74c3c")
        self.color_combo.addItem("Verde", "#2ecc71")
        self.color_combo.addItem("Amarillo", "#f39c12")
        self.color_combo.addItem("Púrpura", "#9b59b6")
        self.color_combo.addItem("Naranja", "#e67e22")
        self.color_combo.addItem("Gris", "#7f8c8d")
        self.color_combo.addItem("Café", "#795548")
        color_layout.addWidget(self.color_combo)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Preview del perfil
        preview_group = QGroupBox("Vista previa")
        preview_layout = QHBoxLayout()

        self.preview_label = QLabel()
        self.preview_label.setStyleSheet("""
            QLabel {
                padding: 10px;
                border-radius: 8px;
                background-color: #f0f0f0;
                min-height: 60px;
            }
        """)
        preview_layout.addWidget(self.preview_label)

        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        # Conectar señales para actualizar preview
        self.name_input.textChanged.connect(self.update_preview)
        self.icon_combo.currentIndexChanged.connect(self.update_preview)
        self.color_combo.currentIndexChanged.connect(self.update_preview)

        # Botones
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept_dialog)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Actualizar preview inicial
        self.update_preview()
    def load_profile_data(self):
        """Cargar datos del perfil para edición"""
        profile = self.profile_manager.get_profile(self.profile_id)
        if profile:
            self.name_input.setText(profile['name'])

            # Buscar icono
            icon_text = profile['icon']
            for i in range(self.icon_combo.count()):
                if self.icon_combo.itemText(i) == icon_text:
                    self.icon_combo.setCurrentIndex(i)
                    break
            # Buscar color
            color = profile['color']
            for i in range(self.color_combo.count()):
                if self.color_combo.itemData(i) == color:
                    self.color_combo.setCurrentIndex(i)
                    break
    def update_preview(self):
        """Actualizar vista previa del perfil"""
        name = self.name_input.text() or "Nuevo perfil"
        icon = self.icon_combo.currentText() or "Usuario"
        color = self.color_combo.currentData() or "#4a90e2"

        self.preview_label.setText(f"<span style='font-size: 16px; font-weight: bold;'>{name}</span> "
                                   f"<span style='font-size: 12px;'>({icon})</span>")
        self.preview_label.setStyleSheet(f"""
            QLabel {{
                padding: 10px;
                border-radius: 8px;
                background-color: {color}20;
                border: 2px solid {color};
                min-height: 60px;
            }}
        """)
    def accept_dialog(self):
        """Procesar creación o edición del perfil"""
        name = self.name_input.text().strip()

        if not name:
            QMessageBox.warning(self, "Nombre requerido",
                              "Por favor ingresa un nombre para el perfil.")
            return
        icon = self.icon_combo.currentText() or "Usuario"
        color = self.color_combo.currentData() or "#4a90e2"

        if self.is_edit_mode:
            # Actualizar perfil existente
            self.profile_manager.update_profile(self.profile_id, name, icon, color)
        else:
            # Crear nuevo perfil
            self.profile_manager.create_profile(name, icon, color)
        self.accept()


class ProfileSwitcher(QWidget):
    """Widget para cambiar rápidamente entre perfiles"""

    def __init__(self, profile_manager, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager
        self.parent_window = parent

        self.setup_ui()
        self.update_current_profile()

        # Conectar señales
        self.profile_manager.profile_changed.connect(self.update_current_profile)
        self.profile_manager.profile_created.connect(self.update_current_profile)
        self.profile_manager.profile_deleted.connect(self.update_current_profile)
    def setup_ui(self):
        """Configurar interfaz del switcher"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Botón del perfil actual
        self.profile_button = QPushButton()
        self.profile_button.setFixedSize(36, 36)
        self.profile_button.setToolTip("Cambiar perfil")
        self.profile_button.setStyleSheet("""
            QPushButton {
                border: 2px solid #ddd;
                border-radius: 18px;
                background-color: white;
                font-size: 18px;
            }
            QPushButton:hover {
                border-color: #4a90e2;
                background-color: #f8f9fa;
            }
        """)
        self.profile_button.clicked.connect(self.show_profile_menu)

        layout.addWidget(self.profile_button)
    def update_current_profile(self):
        """Actualizar botón con el perfil actual"""
        profile = self.profile_manager.get_current_profile()
        if profile:
            color = profile['color']
            name = profile['name']

            self.profile_button.setText((name or "?")[:1].upper())
            self.profile_button.setToolTip(f"Perfil: {name}\nClick para cambiar")
            self.profile_button.setStyleSheet(f"""
                QPushButton {{
                    border: 2px solid {color};
                    border-radius: 18px;
                    background-color: white;
                    font-size: 18px;
                }}
                QPushButton:hover {{
                    border-color: {color};
                    background-color: {color}20;
                }}
            """)
    def show_profile_menu(self):
        """Mostrar menú de perfiles"""
        menu = QMenu(self)

        # Listar todos los perfiles
        profiles = self.profile_manager.get_all_profiles()
        current_id = self.profile_manager.current_profile_id

        for profile in profiles:
            profile_id = profile['id']
            name = profile['name']
            action = menu.addAction(name)
            action.setData(profile_id)

            if profile_id == current_id:
                action.setEnabled(False)
                font = action.font()
                font.setBold(True)
                action.setFont(font)
        menu.addSeparator()

        # Opción para crear nuevo perfil
        new_action = menu.addAction("Nuevo perfil...")
        new_action.triggered.connect(self.create_new_profile)

        # Opción para gestionar perfiles
        manage_action = menu.addAction("Gestionar perfiles...")
        manage_action.triggered.connect(self.manage_profiles)

        # Ejecutar menú
        action = menu.exec(self.profile_button.mapToGlobal(self.profile_button.rect().bottomLeft()))

        if action and action.data():
            # Cambiar a perfil seleccionado
            self.switch_to_profile(action.data())
    def switch_to_profile(self, profile_id):
        """Cambiar a un perfil específico"""
        if profile_id != self.profile_manager.current_profile_id:
            reply = QMessageBox.question(
                self,
                "Cambiar perfil",
                "Al cambiar de perfil, se cerrarán todas las pestañas actuales.\n¿Deseas continuar?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.profile_manager.switch_profile(profile_id)
                # Recargar navegador con nuevo perfil
                if self.parent_window and hasattr(self.parent_window, 'reload_with_new_profile'):
                    self.parent_window.reload_with_new_profile()
    def create_new_profile(self):
        """Crear nuevo perfil"""
        dialog = ProfileDialog(self.profile_manager, parent=self.parent_window)
        if dialog.exec():
            self.update_current_profile()
    def manage_profiles(self):
        """Abrir gestor de perfiles"""
        dialog = ProfileManagerDialog(self.profile_manager, parent=self.parent_window)
        dialog.exec()


class ProfileManagerDialog(QDialog):
    """Diálogo para gestionar todos los perfiles"""

    def __init__(self, profile_manager, parent=None):
        super().__init__(parent)
        self.profile_manager = profile_manager

        self.setWindowTitle("Gestionar perfiles")
        self.setModal(True)
        self.setMinimumSize(500, 400)

        self.setup_ui()
        self.load_profiles()
    def setup_ui(self):
        """Configurar interfaz del gestor"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Gestión de perfiles")
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Lista de perfiles
        self.profiles_list = QListWidget()
        self.profiles_list.itemDoubleClicked.connect(self.edit_profile_item)
        layout.addWidget(self.profiles_list)

        # Botones de acción
        buttons_layout = QHBoxLayout()

        new_btn = QPushButton("Nuevo")
        new_btn.clicked.connect(self.new_profile)
        buttons_layout.addWidget(new_btn)

        edit_btn = QPushButton("Editar")
        edit_btn.clicked.connect(self.edit_profile)
        buttons_layout.addWidget(edit_btn)

        delete_btn = QPushButton("Eliminar")
        delete_btn.clicked.connect(self.delete_profile)
        buttons_layout.addWidget(delete_btn)

        buttons_layout.addStretch()

        default_btn = QPushButton("Predeterminado")
        default_btn.clicked.connect(self.set_default)
        buttons_layout.addWidget(default_btn)

        layout.addLayout(buttons_layout)

        # Botón cerrar
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    def load_profiles(self):
        """Cargar lista de perfiles"""
        self.profiles_list.clear()
        profiles = self.profile_manager.get_all_profiles()

        for profile in profiles:
            item_text = profile['name']
            if profile['is_default']:
                item_text += " (predeterminado)"
            if profile['id'] == self.profile_manager.current_profile_id:
                item_text += " (Activo)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, profile['id'])
            self.profiles_list.addItem(item)
    def new_profile(self):
        """Crear nuevo perfil"""
        dialog = ProfileDialog(self.profile_manager, parent=self)
        if dialog.exec():
            self.load_profiles()
    def edit_profile(self):
        """Editar perfil seleccionado"""
        current_item = self.profiles_list.currentItem()
        if current_item:
            self.edit_profile_item(current_item)
    def edit_profile_item(self, item):
        """Editar un perfil específico"""
        profile_id = item.data(Qt.UserRole)
        dialog = ProfileDialog(self.profile_manager, profile_id, parent=self)
        if dialog.exec():
            self.load_profiles()
    def delete_profile(self):
        """Eliminar perfil seleccionado"""
        current_item = self.profiles_list.currentItem()
        if not current_item:
            return
        profile_id = current_item.data(Qt.UserRole)
        profile = self.profile_manager.get_profile(profile_id)

        if not profile:
            return
        # Verificar si es el perfil actual
        if profile_id == self.profile_manager.current_profile_id:
            QMessageBox.warning(
                self,
                "No se puede eliminar",
                "No puedes eliminar el perfil activo. Cambia a otro perfil primero."
            )
            return
        # Confirmar eliminación
        reply = QMessageBox.question(
            self,
            "Eliminar perfil",
            f"¿Estás seguro de que deseas eliminar el perfil '{profile['name']}'?\n"
            "Se eliminarán todos los datos asociados (cookies, historial, etc.).",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.profile_manager.delete_profile(profile_id):
                self.load_profiles()
                QMessageBox.information(self, "Perfil eliminado",
                                      f"El perfil '{profile['name']}' ha sido eliminado.")
            else:
                QMessageBox.critical(self, "Error",
                                   "No se pudo eliminar el perfil.")
    def set_default(self):
        """Establecer perfil seleccionado como predeterminado"""
        current_item = self.profiles_list.currentItem()
        if not current_item:
            return
        profile_id = current_item.data(Qt.UserRole)
        self.profile_manager.set_default_profile(profile_id)
        self.load_profiles()

        QMessageBox.information(self, "Perfil predeterminado",
                              "El perfil se estableció como predeterminado.")
