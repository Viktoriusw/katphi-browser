#!/usr/bin/env python3
"""
Theme Loader - Sistema consolidado de temas
Carga y aplica temas desde archivos JSON con soporte para temas personalizados
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, List
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

class ThemeLoader(QObject):
    """
    Sistema consolidado de temas - Único punto de gestión de temas
    Soporta temas base (claro/oscuro) y temas personalizados
    """
    
    # Señales para notificar cambios de tema
    theme_changed = Signal(str)  # nombre del tema
    theme_loaded = Signal(dict)  # datos del tema
    
    def __init__(self):
        super().__init__()
        self.current_theme = "light"
        self.themes = {}
        self.themes_dir = Path("themes")
        self.custom_themes_dir = Path("themes/custom")
        
        # Crear directorios si no existen
        self.themes_dir.mkdir(exist_ok=True)
        self.custom_themes_dir.mkdir(parents=True, exist_ok=True)
        
        # Cargar todos los temas
        self._load_theme_files()
    
    def _load_theme_files(self):
        """Carga todos los archivos de tema disponibles (base y personalizados)"""
        # Cargar temas base (obligatorios)
        base_theme_files = [
            "light_theme.json",
            "dark_theme.json"
        ]
        
        # Cargar temas base
        for theme_file in base_theme_files:
            if os.path.exists(theme_file):
                try:
                    with open(theme_file, 'r', encoding='utf-8') as f:
                        theme_data = json.load(f)
                        theme_id = theme_data.get("id") or Path(theme_file).stem.replace("_theme", "")
                        theme_name_key = theme_data.get("name", theme_id).lower()
                        
                        # Guardar con ambas claves
                        self.themes[theme_id.lower()] = theme_data
                        self.themes[theme_name_key] = theme_data
                        print(f"[OK] Loaded base theme: {theme_data.get('name', theme_id)} (id: {theme_id})")
                except Exception as e:
                    print(f"[ERROR] Failed to load base theme {theme_file}: {e}")
        
        # Cargar temas personalizados del directorio themes/
        if self.themes_dir.exists():
            for theme_file in self.themes_dir.glob("*.json"):
                if theme_file.name not in ["light_theme.json", "dark_theme.json"]:
                    try:
                        with open(theme_file, 'r', encoding='utf-8') as f:
                            theme_data = json.load(f)
                            theme_id = theme_data.get("id") or theme_file.stem
                            theme_name_key = theme_data.get("name", theme_id).lower()
                            
                            # Guardar tema personalizado
                            self.themes[theme_id.lower()] = theme_data
                            self.themes[theme_name_key] = theme_data
                            print(f"[OK] Loaded custom theme: {theme_data.get('name', theme_id)} (id: {theme_id})")
                    except Exception as e:
                        print(f"[ERROR] Failed to load custom theme {theme_file}: {e}")
        
        # Cargar temas personalizados del directorio themes/custom/
        if self.custom_themes_dir.exists():
            for theme_file in self.custom_themes_dir.glob("*.json"):
                try:
                    with open(theme_file, 'r', encoding='utf-8') as f:
                        theme_data = json.load(f)
                        theme_id = theme_data.get("id") or theme_file.stem
                        theme_name_key = theme_data.get("name", theme_id).lower()
                        
                        # Guardar tema personalizado
                        self.themes[theme_id.lower()] = theme_data
                        self.themes[theme_name_key] = theme_data
                        print(f"[OK] Loaded user theme: {theme_data.get('name', theme_id)} (id: {theme_id})")
                except Exception as e:
                    print(f"[ERROR] Failed to load user theme {theme_file}: {e}")
    
    def get_available_themes(self) -> List[Dict[str, str]]:
        """Retorna lista de temas disponibles con metadatos"""
        themes_list = []
        for theme_id, theme_data in self.themes.items():
            if " " not in theme_id:  # Evitar duplicados por nombre
                themes_list.append({
                    "id": theme_id,
                    "name": theme_data.get("name", theme_id),
                    "description": theme_data.get("description", ""),
                    "version": theme_data.get("version", "1.0.0"),
                    "type": "base" if theme_id in ["light", "dark"] else "custom"
                })
        return sorted(themes_list, key=lambda x: (x["type"] != "base", x["name"]))
    
    def get_theme_data(self, theme_name: str) -> Optional[Dict]:
        """Obtiene los datos de un tema específico"""
        return self.themes.get(theme_name.lower())
    
    def get_base_themes(self) -> List[str]:
        """Retorna solo los temas base (light, dark)"""
        return ["light", "dark"]
    
    def get_custom_themes(self) -> List[str]:
        """Retorna solo los temas personalizados"""
        return [theme_id for theme_id in self.themes.keys() 
                if theme_id not in ["light", "dark"] and " " not in theme_id]
    
    def apply_theme(self, theme_name: str) -> bool:
        """
        Aplica un tema específico
        
        Args:
            theme_name: Nombre del tema a aplicar
            
        Returns:
            True si se aplicó correctamente, False en caso contrario
        """
        key = theme_name.lower().strip()
        theme_data = self.themes.get(key)
        
        # Si no se encuentra, intentar mapear por nombre
        if not theme_data:
            if "light" in key:
                theme_data = self.themes.get("light")
            elif "dark" in key:
                theme_data = self.themes.get("dark")
        
        if not theme_data:
            print(f"[ERROR] Theme '{theme_name}' not found")
            return False
        
        try:
            # Aplicar estilos CSS basados en el tema
            css = self._generate_css(theme_data)
            app = QApplication.instance()
            if app:
                # Limpiar estilos previos y aplicar nuevos
                app.setStyleSheet("")
                app.setStyleSheet(css)
                print(f"[DEBUG] CSS applied, length: {len(css)}")
            
            self.current_theme = theme_data.get("id", key)
            self.theme_changed.emit(self.current_theme)
            self.theme_loaded.emit(theme_data)
            print(f"[OK] Applied theme: {theme_data.get('name', self.current_theme)}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to apply theme {theme_name}: {e}")
            return False
    
    def _generate_css(self, theme_data: Dict) -> str:
        """
        Genera CSS basado en los datos del tema
        
        Args:
            theme_data: Datos del tema desde JSON
            
        Returns:
            CSS generado
        """
        colors = theme_data.get("colors", {})
        fonts = theme_data.get("fonts", {})
        spacing = theme_data.get("spacing", {})
        borders = theme_data.get("borders", {})
        
        return f"""
        /* === TEMA: {theme_data.get('name', 'Unknown')} === */
        
        /* Estilos base - FORZAR APLICACIÓN */
        * {{
            color: {colors.get('primary', '#000000')} !important;
            font-family: {fonts.get('family', 'Segoe UI, Arial, sans-serif')} !important;
        }}
        
        QMainWindow {{
            background-color: {colors.get('background', '#f5f5f5')} !important;
            border: {borders.get('width', '1px')} solid {colors.get('border', '#e0e0e0')} !important;
        }}
        
        QWidget {{
            background-color: {colors.get('background', '#f5f5f5')} !important;
            color: {colors.get('primary', '#000000')} !important;
        }}
        
        /* Toolbar */
        QToolBar {{
            background-color: {colors.get('toolbar_background', colors.get('surface', '#ffffff'))} !important;
            border: {borders.get('width', '1px')} solid {colors.get('toolbar_border', colors.get('border', '#e0e0e0'))} !important;
            border-radius: {borders.get('radius', '4px')} !important;
            padding: {spacing.get('md', '8px')} !important;
            spacing: {spacing.get('sm', '4px')} !important;
        }}
        
        /* Botones de toolbar - Tamaño uniforme (24x24px) sin marco */
        QToolBar QToolButton {{
            background-color: {colors.get('button_background', colors.get('surface', '#ffffff'))};
            color: {colors.get('primary', '#000000')};
            border: none;
            border-radius: {borders.get('radius', '4px')};
            padding: 4px;
            margin: 2px;
            font-size: {fonts.get('size_normal', '10pt')};
            font-weight: bold;
            min-width: 24px;
            min-height: 24px;
            max-width: 24px;
            max-height: 24px;
        }}
        
        QToolBar QToolButton:hover {{
            background-color: {colors.get('button_hover', colors.get('hover', '#e8e8e8'))};
        }}
        
        QToolBar QToolButton:pressed {{
            background-color: {colors.get('button_pressed', colors.get('selected', '#cce8ff'))};
        }}
        
        
        /* Botones generales - Sin marco */
        QPushButton {{
            background-color: {colors.get('button_background', colors.get('surface', '#ffffff'))};
            color: {colors.get('primary', '#000000')};
            border: none;
            border-radius: {borders.get('radius', '4px')};
            padding: 4px 8px;
            font-size: {fonts.get('size_normal', '10pt')};
            font-weight: bold;
            min-height: 24px;
        }}
        
        /* Botones de control de ventana - Tamaño uniforme (24x24px) sin marco */
        QToolBar QPushButton {{
            background-color: {colors.get('button_background', colors.get('surface', '#ffffff'))};
            color: {colors.get('primary', '#000000')};
            border: none;
            border-radius: {borders.get('radius', '4px')};
            padding: 2px 4px;
            font-size: 12px;
            font-weight: bold;
            min-width: 24px;
            min-height: 24px;
            max-width: 24px;
            max-height: 24px;
        }}
        
        QPushButton:hover {{
            background-color: {colors.get('button_hover', colors.get('hover', '#e8e8e8'))};
        }}
        
        QPushButton:pressed {{
            background-color: {colors.get('button_pressed', colors.get('selected', '#cce8ff'))};
        }}
        
        QToolBar QPushButton:hover {{
            background-color: {colors.get('button_hover', colors.get('hover', '#e8e8e8'))};
        }}
        
        QToolBar QPushButton:pressed {{
            background-color: {colors.get('button_pressed', colors.get('selected', '#cce8ff'))};
        }}
        
        /* Campos de entrada */
        QLineEdit {{
            background-color: {colors.get('input_background', colors.get('surface', '#ffffff'))};
            color: {colors.get('primary', '#000000')};
            border: {borders.get('width', '1px')} solid {colors.get('input_border', colors.get('border', '#e0e0e0'))};
            border-radius: {borders.get('radius', '4px')};
            padding: {spacing.get('sm', '4px')} {spacing.get('md', '8px')};
            font-size: {fonts.get('size_normal', '10pt')};
        }}
        
        QLineEdit:focus {{
            border-color: {colors.get('input_focus', colors.get('accent', '#0078d4'))};
            box-shadow: 0 0 0 2px {colors.get('input_focus', colors.get('accent', '#0078d4'))}33;
        }}
        
        QLineEdit:hover {{
            border-color: {colors.get('accent', '#0078d4')};
        }}
        
        /* Pestañas */
        QTabWidget::pane {{
            background-color: {colors.get('background', '#f5f5f5')};
            border: {borders.get('width', '1px')} solid {colors.get('border', '#e0e0e0')};
        }}
        
        QTabBar::tab {{
            background-color: {colors.get('tab_background', colors.get('surface', '#ffffff'))};
            color: {colors.get('primary', '#000000')};
            border: {borders.get('width', '1px')} solid {colors.get('border', '#e0e0e0')};
            padding: {spacing.get('sm', '4px')} {spacing.get('md', '8px')};
            margin-right: {spacing.get('xs', '2px')};
            border-top-left-radius: {borders.get('radius', '4px')};
            border-top-right-radius: {borders.get('radius', '4px')};
        }}
        
        QTabBar::tab:selected {{
            background-color: {colors.get('tab_selected', colors.get('surface', '#ffffff'))};
            border-bottom-color: {colors.get('tab_selected', colors.get('surface', '#ffffff'))};
        }}
        
        QTabBar::tab:hover {{
            background-color: {colors.get('tab_hover', colors.get('hover', '#e8e8e8'))};
        }}
        
        /* Dock widgets */
        QDockWidget::title {{
            background-color: {colors.get('surface', '#ffffff')};
            color: {colors.get('primary', '#000000')};
            padding: {spacing.get('sm', '4px')} {spacing.get('md', '8px')};
        }}
        
        /* Scrollbars */
        QScrollBar:vertical, QScrollBar:horizontal {{
            background-color: {colors.get('background', '#f5f5f5')};
            border: none;
            width: 12px;
        }}
        
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
            background-color: {colors.get('border', '#e0e0e0')};
            border-radius: 6px;
            min-height: 20px;
        }}
        
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
            background-color: {colors.get('accent', '#0078d4')};
        }}
        
        /* Separadores */
        QFrame {{
            color: {colors.get('border', '#e0e0e0')};
        }}
        """
    
    def get_current_theme(self) -> str:
        """Retorna el tema actual"""
        return self.current_theme
    
    def create_custom_theme(self, theme_id: str, theme_data: Dict, save_to_file: bool = True) -> bool:
        """
        Crea un tema personalizado
        
        Args:
            theme_id: ID único del tema
            theme_data: Datos del tema
            save_to_file: Si guardar en archivo JSON
            
        Returns:
            True si se creó correctamente
        """
        try:
            # Validar datos del tema
            if not self._validate_theme_data(theme_data):
                print(f"[ERROR] Invalid theme data for {theme_id}")
                return False
            
            # Agregar metadatos
            theme_data["id"] = theme_id
            theme_data["version"] = theme_data.get("version", "1.0.0")
            theme_data["created"] = True
            
            # Guardar en memoria
            self.themes[theme_id.lower()] = theme_data
            self.themes[theme_data.get("name", theme_id).lower()] = theme_data
            
            # Guardar en archivo si se solicita
            if save_to_file:
                theme_file = self.custom_themes_dir / f"{theme_id}.json"
                with open(theme_file, 'w', encoding='utf-8') as f:
                    json.dump(theme_data, f, indent=2, ensure_ascii=False)
                print(f"[OK] Custom theme created: {theme_id}")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to create custom theme {theme_id}: {e}")
            return False
    
    def delete_custom_theme(self, theme_id: str) -> bool:
        """
        Elimina un tema personalizado
        
        Args:
            theme_id: ID del tema a eliminar
            
        Returns:
            True si se eliminó correctamente
        """
        try:
            if theme_id in ["light", "dark"]:
                print(f"[ERROR] Cannot delete base theme: {theme_id}")
                return False
            
            # Eliminar de memoria
            if theme_id.lower() in self.themes:
                del self.themes[theme_id.lower()]
            
            # Eliminar archivo
            theme_file = self.custom_themes_dir / f"{theme_id}.json"
            if theme_file.exists():
                theme_file.unlink()
            
            print(f"[OK] Custom theme deleted: {theme_id}")
            return True
            
        except Exception as e:
            print(f"[ERROR] Failed to delete custom theme {theme_id}: {e}")
            return False
    
    def _validate_theme_data(self, theme_data: Dict) -> bool:
        """Valida que los datos del tema sean correctos"""
        required_keys = ["name", "colors"]
        for key in required_keys:
            if key not in theme_data:
                return False
        
        # Validar colores requeridos
        required_colors = ["primary", "background", "surface"]
        colors = theme_data.get("colors", {})
        for color in required_colors:
            if color not in colors:
                return False
        
        return True
    
    def reload_themes(self):
        """Recarga todos los temas desde archivos"""
        self.themes.clear()
        self._load_theme_files()
        print("[OK] Themes reloaded")
