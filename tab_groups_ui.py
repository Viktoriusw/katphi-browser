#!/usr/bin/env python3
"""
Tab Groups UI - Interfaz de usuario para gestionar grupos de pestañas
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QColorDialog, QMessageBox, QDialog, QDialogButtonBox,
                               QComboBox, QGroupBox, QScrollArea, QFrame, QMenu)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QPalette, QBrush, QPainter


def _themed_icon(name: str) -> QIcon:
    """Icono SVG de icons/ teñido con el color del tema activo."""
    try:
        from ui.core.strip_icons import build_nav_icon
        return build_nav_icon(name, None, QSize(16, 16))
    except Exception:
        return QIcon()
from tab_groups import TabGroupManager, TabGroup


class ColorButton(QPushButton):
    """Botón selector de color"""

    colorChanged = Signal(str)

    def __init__(self, color="#1976d2", parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(40, 30)
        self.update_color()
        self.clicked.connect(self.choose_color)
    def update_color(self):
        """Actualizar color visual del botón"""
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self._color};
                border: 2px solid #333;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border: 2px solid #666;
            }}
        """)
    def choose_color(self):
        """Abrir selector de color"""
        color = QColorDialog.getColor(QColor(self._color), self, "Select Group Color")
        if color.isValid():
            self._color = color.name()
            self.update_color()
            self.colorChanged.emit(self._color)
    def get_color(self):
        """Obtener color actual"""
        return self._color
    def set_color(self, color):
        """Establecer color"""
        self._color = color
        self.update_color()


class CreateGroupDialog(QDialog):
    """Diálogo para crear/editar grupo"""

    def __init__(self, group=None, parent=None):
        super().__init__(parent)
        self.group = group
        self.setWindowTitle("Edit Group" if group else "Create New Group")
        self.setModal(True)
        self.setMinimumWidth(400)

        self.setup_ui()
    def setup_ui(self):
        """Configurar interfaz"""
        layout = QVBoxLayout(self)

        # Nombre del grupo
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Group Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("E.g. Work, Personal, Shopping...")

        if self.group:
            self.name_input.setText(self.group.name)
        else:
            self.name_input.setText("")
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)

        # Color del grupo
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Group Color:"))

        self.color_button = ColorButton()
        if self.group:
            self.color_button.set_color(self.group.color)
        color_layout.addWidget(self.color_button)

        # Colores predefinidos
        presets_label = QLabel("Quick colors:")
        color_layout.addWidget(presets_label)

        for color, _ in TabGroupManager.COLORS[:5]:
            preset_btn = QPushButton()
            preset_btn.setFixedSize(25, 25)
            preset_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    border: 1px solid #333;
                    border-radius: 3px;
                }}
            """)
            preset_btn.clicked.connect(lambda checked, c=color: self.color_button.set_color(c))
            color_layout.addWidget(preset_btn)
        color_layout.addStretch()
        layout.addLayout(color_layout)

        # Botones
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    def get_group_data(self):
        """Obtener datos del grupo"""
        return {
            "name": self.name_input.text().strip(),
            "color": self.color_button.get_color()
        }


class TabGroupWidget(QFrame):
    """Widget para mostrar un grupo de pestañas"""

    groupClicked = Signal(str)  # group_id
    editRequested = Signal(str)  # group_id
    deleteRequested = Signal(str)  # group_id
    tabsRequested = Signal(str)  # group_id
    collapseToggled = Signal(str)  # group_id

    def __init__(self, group: TabGroup, parent=None):
        super().__init__(parent)
        self.group = group
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(2)
        self.setup_ui()
        self.update_style()
    def setup_ui(self):
        """Configurar interfaz del widget"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Indicador de color
        self.color_indicator = QLabel()
        self.color_indicator.setFixedSize(20, 40)
        self.color_indicator.setStyleSheet(f"""
            QLabel {{
                background-color: {self.group.color};
                border-radius: 4px;
            }}
        """)
        layout.addWidget(self.color_indicator)

        # Información del grupo
        info_layout = QVBoxLayout()

        # Nombre y contador
        self.name_label = QLabel(f"<b>{self.group.name}</b>")
        self.name_label.setStyleSheet("font-size: 14px;")
        info_layout.addWidget(self.name_label)

        self.count_label = QLabel(f"{len(self.group.tab_indices)} tabs")
        self.count_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self.count_label)

        layout.addLayout(info_layout, 1)

        # Botón de colapsar
        self.collapse_btn = QPushButton("▾" if not self.group.collapsed else "▸")
        self.collapse_btn.setFixedSize(30, 30)
        self.collapse_btn.clicked.connect(lambda: self.collapseToggled.emit(self.group.id))
        layout.addWidget(self.collapse_btn)

        # Botón de ver pestañas
        view_tabs_btn = QPushButton()
        view_tabs_btn.setIcon(_themed_icon("list"))
        view_tabs_btn.setFixedSize(30, 30)
        view_tabs_btn.setToolTip("View tabs in this group")
        view_tabs_btn.clicked.connect(lambda: self.tabsRequested.emit(self.group.id))
        layout.addWidget(view_tabs_btn)

        # Botón de editar
        edit_btn = QPushButton()
        edit_btn.setIcon(_themed_icon("edit"))
        edit_btn.setFixedSize(30, 30)
        edit_btn.setToolTip("Edit group")
        edit_btn.clicked.connect(lambda: self.editRequested.emit(self.group.id))
        layout.addWidget(edit_btn)

        # Botón de eliminar
        delete_btn = QPushButton()
        delete_btn.setIcon(_themed_icon("ide_trash"))
        delete_btn.setFixedSize(30, 30)
        delete_btn.setToolTip("Delete group")
        delete_btn.clicked.connect(lambda: self.deleteRequested.emit(self.group.id))
        layout.addWidget(delete_btn)
    def update_style(self):
        """Actualizar estilo del widget"""
        self.setStyleSheet(f"""
            TabGroupWidget {{
                border: 2px solid {self.group.color};
                border-radius: 6px;
                background-color: rgba(0, 0, 0, 0.02);
            }}
            TabGroupWidget:hover {{
                background-color: rgba(0, 0, 0, 0.05);
            }}
        """)
    def update_group(self, group: TabGroup):
        """Actualizar datos del grupo"""
        self.group = group
        self.name_label.setText(f"<b>{group.name}</b>")
        self.count_label.setText(f"{len(group.tab_indices)} tabs")
        self.color_indicator.setStyleSheet(f"""
            QLabel {{
                background-color: {group.color};
                border-radius: 4px;
            }}
        """)
        self.collapse_btn.setText("▾" if not group.collapsed else "▸")
        self.update_style()


class TabGroupsPanel(QWidget):
    """Panel principal para gestionar grupos de pestañas"""

    assignTabRequested = Signal(int, str)  # tab_index, group_id

    def __init__(self, group_manager: TabGroupManager, tab_manager=None, parent=None):
        super().__init__(parent)
        self.group_manager = group_manager
        self.tab_manager = tab_manager
        self.setup_ui()
        self.connect_signals()
        self.refresh_groups()
    def setup_ui(self):
        """Configurar interfaz"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("<h2>Tab Groups</h2>")
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Botón de crear grupo
        create_btn = QPushButton("Create Group")
        create_btn.clicked.connect(self.create_group)
        header_layout.addWidget(create_btn)

        # Botón de crear grupo con tabs seleccionados
        create_from_tabs_btn = QPushButton("Group Selected Tabs")
        create_from_tabs_btn.clicked.connect(self.create_group_from_selected)
        header_layout.addWidget(create_from_tabs_btn)

        layout.addWidget(header)

        # Scroll area para grupos
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self.groups_container = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_container)
        self.groups_layout.setAlignment(Qt.AlignTop)
        self.groups_layout.setSpacing(10)

        scroll.setWidget(self.groups_container)
        layout.addWidget(scroll, 1)

        # Footer con info
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 5, 10, 5)

        self.info_label = QLabel("No groups yet")
        self.info_label.setStyleSheet("color: #666; font-size: 11px;")
        footer_layout.addWidget(self.info_label)

        footer_layout.addStretch()

        # Botón para limpiar todos los grupos
        clear_all_btn = QPushButton("Clear All Groups")
        clear_all_btn.clicked.connect(self.clear_all_groups)
        footer_layout.addWidget(clear_all_btn)

        layout.addWidget(footer)
    def connect_signals(self):
        """Conectar señales del group manager"""
        self.group_manager.group_created.connect(self.on_group_created)
        self.group_manager.group_deleted.connect(self.on_group_deleted)
        self.group_manager.group_updated.connect(self.on_group_updated)
        # También reaccionar cuando cambian las pestañas dentro de un grupo
        self.group_manager.tab_added_to_group.connect(
            lambda group_id, tab_index: self.on_group_updated(group_id)
        )
        self.group_manager.tab_removed_from_group.connect(
            lambda group_id, tab_index: self.on_group_updated(group_id)
        )
    def create_group(self):
        """Crear nuevo grupo"""
        dialog = CreateGroupDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_group_data()
            if not data["name"]:
                QMessageBox.warning(self, "Error", "Please enter a group name")
                return
            group = self.group_manager.create_group(
                name=data["name"],
                color=data["color"]
            )

            QMessageBox.information(self, "Success", f"Group '{group.name}' created!")
    def create_group_from_selected(self):
        """Crear grupo con las pestañas seleccionadas"""
        if not self.tab_manager:
            QMessageBox.warning(self, "Error", "Tab manager not available")
            return
        # Obtener pestaña actual
        current_index = self.tab_manager.tabs.currentIndex()
        if current_index < 0:
            QMessageBox.warning(self, "Error", "No tab selected")
            return
        dialog = CreateGroupDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_group_data()
            if not data["name"]:
                QMessageBox.warning(self, "Error", "Please enter a group name")
                return
            # Crear grupo con la pestaña actual
            group = self.group_manager.create_group(
                name=data["name"],
                color=data["color"],
                tab_indices=[current_index]
            )

            QMessageBox.information(self, "Success",
                                  f"Group '{group.name}' created with 1 tab!")
    def edit_group(self, group_id: str):
        """Editar grupo existente"""
        group = self.group_manager.get_group(group_id)
        if not group:
            return
        dialog = CreateGroupDialog(group=group, parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_group_data()

            if data["name"]:
                self.group_manager.rename_group(group_id, data["name"])
            self.group_manager.change_group_color(group_id, data["color"])
    def delete_group(self, group_id: str):
        """Eliminar grupo"""
        group = self.group_manager.get_group(group_id)
        if not group:
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete group '{group.name}'?\n\nTabs will not be closed, only ungrouped.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.group_manager.delete_group(group_id)
    def view_group_tabs(self, group_id: str):
        """Ver pestañas del grupo"""
        group = self.group_manager.get_group(group_id)
        if not group or not self.tab_manager:
            return
        tabs_info = []
        for idx in sorted(group.tab_indices):
            if idx < self.tab_manager.tabs.count():
                title = self.tab_manager.tabs.tabText(idx)
                tabs_info.append(f"  • Tab {idx + 1}: {title}")
        if tabs_info:
            msg = f"Tabs in group '{group.name}':\n\n" + "\n".join(tabs_info)
        else:
            msg = f"No tabs in group '{group.name}'"
        QMessageBox.information(self, f"Group: {group.name}", msg)
    def toggle_collapse(self, group_id: str):
        """Colapsar/expandir grupo"""
        self.group_manager.toggle_group_collapse(group_id)
    def refresh_groups(self):
        """Refrescar lista de grupos"""
        # Limpiar widgets existentes
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # Obtener grupos
        groups = self.group_manager.get_all_groups()

        if not groups:
            no_groups_label = QLabel("No groups created yet.\n\nCreate a group to organize your tabs!")
            no_groups_label.setAlignment(Qt.AlignCenter)
            no_groups_label.setStyleSheet("color: #999; padding: 40px; font-size: 13px;")
            self.groups_layout.addWidget(no_groups_label)
            self.info_label.setText("No groups")
            return
        # Crear widgets para cada grupo
        for group in groups:
            widget = TabGroupWidget(group)
            widget.editRequested.connect(self.edit_group)
            widget.deleteRequested.connect(self.delete_group)
            widget.tabsRequested.connect(self.view_group_tabs)
            widget.collapseToggled.connect(self.toggle_collapse)
            self.groups_layout.addWidget(widget)
        # Actualizar info
        total_tabs = sum(len(g.tab_indices) for g in groups)
        self.info_label.setText(f"{len(groups)} groups • {total_tabs} tabs grouped")
    def clear_all_groups(self):
        """Limpiar todos los grupos"""
        reply = QMessageBox.question(
            self, "Confirm Clear All",
            "Delete ALL groups?\n\nTabs will not be closed, only ungrouped.",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.group_manager.clear_all_groups()
            self.refresh_groups()
    def on_group_created(self, group_id: str):
        """Callback: grupo creado"""
        self.refresh_groups()
    def on_group_deleted(self, group_id: str):
        """Callback: grupo eliminado"""
        self.refresh_groups()
    def on_group_updated(self, group_id: str):
        """Callback: grupo actualizado"""
        self.refresh_groups()
