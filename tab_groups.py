#!/usr/bin/env python3
"""
Tab Groups Manager - Sistema de agrupación de pestañas similar a Firefox
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Set
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor


class TabGroup:
    """Representa un grupo de pestañas"""

    def __init__(self, group_id: str, name: str, color: str = "#1976d2"):
        self.id = group_id
        self.name = name
        self.color = color  # Color hex del grupo
        self.tab_indices: Set[int] = set()  # Índices de pestañas en este grupo
        self.created_at = datetime.now().isoformat()
        self.collapsed = False  # Si el grupo está colapsado
    def add_tab(self, index: int):
        """Agregar pestaña al grupo"""
        self.tab_indices.add(index)
    def remove_tab(self, index: int):
        """Remover pestaña del grupo"""
        self.tab_indices.discard(index)
    def has_tab(self, index: int) -> bool:
        """Verificar si una pestaña está en este grupo"""
        return index in self.tab_indices
    def update_indices_after_close(self, closed_index: int):
        """Actualizar índices después de cerrar una pestaña"""
        # Remover la pestaña cerrada
        self.tab_indices.discard(closed_index)

        # Decrementar índices mayores al cerrado
        updated_indices = set()
        for idx in self.tab_indices:
            if idx > closed_index:
                updated_indices.add(idx - 1)
            else:
                updated_indices.add(idx)
        self.tab_indices = updated_indices
    def update_indices_after_add(self, new_index: int):
        """Actualizar índices después de agregar una pestaña"""
        # Incrementar índices mayores o iguales al nuevo
        updated_indices = set()
        for idx in self.tab_indices:
            if idx >= new_index:
                updated_indices.add(idx + 1)
            else:
                updated_indices.add(idx)
        self.tab_indices = updated_indices
    def to_dict(self) -> Dict:
        """Serializar grupo a diccionario"""
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "tab_indices": list(self.tab_indices),
            "created_at": self.created_at,
            "collapsed": self.collapsed
        }
    @staticmethod
    def from_dict(data: Dict) -> 'TabGroup':
        """Deserializar grupo desde diccionario"""
        group = TabGroup(
            group_id=data["id"],
            name=data["name"],
            color=data.get("color", "#1976d2")
        )
        group.tab_indices = set(data.get("tab_indices", []))
        group.created_at = data.get("created_at", datetime.now().isoformat())
        group.collapsed = data.get("collapsed", False)
        return group


class TabGroupManager(QObject):
    """Gestor de grupos de pestañas"""

    # Señales
    group_created = Signal(str)  # group_id
    group_deleted = Signal(str)  # group_id
    group_updated = Signal(str)  # group_id
    tab_added_to_group = Signal(str, int)  # group_id, tab_index
    tab_removed_from_group = Signal(str, int)  # group_id, tab_index

    GROUPS_FILE = "tab_groups.json"

    # Colores predefinidos
    COLORS = [
        ("#1976d2", "Blue"),
        ("#388e3c", "Green"),
        ("#f57c00", "Orange"),
        ("#d32f2f", "Red"),
        ("#7b1fa2", "Purple"),
        ("#0097a7", "Cyan"),
        ("#c2185b", "Pink"),
        ("#455a64", "Gray"),
        ("#fbc02d", "Yellow"),
        ("#5d4037", "Brown")
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups: Dict[str, TabGroup] = {}  # group_id -> TabGroup
        self.next_group_number = 1

        # Cargar grupos guardados
        self.load_groups()
    def create_group(self, name: str = None, color: str = None, tab_indices: List[int] = None) -> TabGroup:
        """Crear un nuevo grupo"""
        # Generar nombre automático si no se proporciona
        if not name:
            name = f"Group {self.next_group_number}"
            self.next_group_number += 1
        # Seleccionar color aleatorio si no se proporciona
        if not color:
            color = self.COLORS[len(self.groups) % len(self.COLORS)][0]
        # Generar ID único
        group_id = f"group_{int(datetime.now().timestamp() * 1000)}"

        # Crear grupo
        group = TabGroup(group_id, name, color)

        # Agregar pestañas iniciales
        if tab_indices:
            for idx in tab_indices:
                group.add_tab(idx)
        # Guardar grupo
        self.groups[group_id] = group

        # Emitir señal
        self.group_created.emit(group_id)

        # Guardar cambios
        self.save_groups()

        return group
    def delete_group(self, group_id: str) -> bool:
        """Eliminar un grupo"""
        if group_id not in self.groups:
            return False
        # Eliminar grupo
        del self.groups[group_id]

        # Emitir señal
        self.group_deleted.emit(group_id)

        # Guardar cambios
        self.save_groups()

        return True
    def rename_group(self, group_id: str, new_name: str) -> bool:
        """Renombrar un grupo"""
        if group_id not in self.groups:
            return False
        self.groups[group_id].name = new_name

        # Emitir señal
        self.group_updated.emit(group_id)

        # Guardar cambios
        self.save_groups()

        return True
    def change_group_color(self, group_id: str, new_color: str) -> bool:
        """Cambiar el color de un grupo"""
        if group_id not in self.groups:
            return False
        self.groups[group_id].color = new_color

        # Emitir señal
        self.group_updated.emit(group_id)

        # Guardar cambios
        self.save_groups()

        return True
    def add_tab_to_group(self, group_id: str, tab_index: int) -> bool:
        """Agregar una pestaña a un grupo"""
        if group_id not in self.groups:
            return False
        # Remover de otros grupos primero
        self.remove_tab_from_all_groups(tab_index)

        # Agregar al grupo
        self.groups[group_id].add_tab(tab_index)

        # Emitir señales
        self.tab_added_to_group.emit(group_id, tab_index)
        self.group_updated.emit(group_id)

        # Guardar cambios
        self.save_groups()

        return True
    def remove_tab_from_group(self, group_id: str, tab_index: int) -> bool:
        """Remover una pestaña de un grupo"""
        if group_id not in self.groups:
            return False
        self.groups[group_id].remove_tab(tab_index)

        # Emitir señales
        self.tab_removed_from_group.emit(group_id, tab_index)
        self.group_updated.emit(group_id)

        # Guardar cambios
        self.save_groups()

        return True
    def remove_tab_from_all_groups(self, tab_index: int):
        """Remover una pestaña de todos los grupos"""
        for group_id, group in self.groups.items():
            if group.has_tab(tab_index):
                group.remove_tab(tab_index)
                self.tab_removed_from_group.emit(group_id, tab_index)
                self.group_updated.emit(group_id)
        self.save_groups()
    def get_tab_group(self, tab_index: int) -> Optional[TabGroup]:
        """Obtener el grupo al que pertenece una pestaña"""
        for group in self.groups.values():
            if group.has_tab(tab_index):
                return group
        return None
    def get_group(self, group_id: str) -> Optional[TabGroup]:
        """Obtener un grupo por ID"""
        return self.groups.get(group_id)
    def get_all_groups(self) -> List[TabGroup]:
        """Obtener todos los grupos"""
        return list(self.groups.values())
    def toggle_group_collapse(self, group_id: str) -> bool:
        """Colapsar/expandir un grupo"""
        if group_id not in self.groups:
            return False
        group = self.groups[group_id]
        group.collapsed = not group.collapsed

        # Emitir señal
        self.group_updated.emit(group_id)

        # Guardar cambios
        self.save_groups()

        return True
    def on_tab_closed(self, tab_index: int):
        """Manejar cierre de pestaña - actualizar índices en todos los grupos"""
        for group in self.groups.values():
            group.update_indices_after_close(tab_index)
        # Eliminar grupos vacíos
        empty_groups = [gid for gid, g in self.groups.items() if len(g.tab_indices) == 0]
        for gid in empty_groups:
            self.delete_group(gid)
        self.save_groups()
    def on_tab_added(self, tab_index: int):
        """Manejar adición de pestaña - actualizar índices en todos los grupos"""
        for group in self.groups.values():
            group.update_indices_after_add(tab_index)
        self.save_groups()
    def move_tab_in_group(self, tab_index: int, target_group_id: str) -> bool:
        """Mover una pestaña a otro grupo"""
        if target_group_id not in self.groups:
            return False
        # Remover de grupo actual
        self.remove_tab_from_all_groups(tab_index)

        # Agregar al nuevo grupo
        self.add_tab_to_group(target_group_id, tab_index)

        return True
    def get_group_tabs(self, group_id: str) -> List[int]:
        """Obtener lista de pestañas de un grupo"""
        if group_id not in self.groups:
            return []
        return sorted(list(self.groups[group_id].tab_indices))
    def save_groups(self):
        """Guardar grupos a archivo JSON"""
        try:
            data = {
                "groups": {gid: g.to_dict() for gid, g in self.groups.items()},
                "next_group_number": self.next_group_number,
                "saved_at": datetime.now().isoformat()
            }

            with open(self.GROUPS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[TabGroups] Saved {len(self.groups)} groups")
        except Exception as e:
            print(f"[TabGroups] Error saving groups: {e}")
    def load_groups(self):
        """Cargar grupos desde archivo JSON"""
        if not os.path.exists(self.GROUPS_FILE):
            print("[TabGroups] No saved groups file")
            return
        try:
            with open(self.GROUPS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Cargar grupos
            self.groups = {}
            for gid, gdata in data.get("groups", {}).items():
                self.groups[gid] = TabGroup.from_dict(gdata)
            # Restaurar contador
            self.next_group_number = data.get("next_group_number", 1)

            print(f"[TabGroups] Loaded {len(self.groups)} groups")
        except Exception as e:
            print(f"[TabGroups] Error loading groups: {e}")
            import traceback
            traceback.print_exc()
    def clear_all_groups(self):
        """Eliminar todos los grupos"""
        self.groups.clear()
        self.next_group_number = 1
        self.save_groups()

        print("[TabGroups] All groups cleared")
