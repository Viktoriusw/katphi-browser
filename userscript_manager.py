#!/usr/bin/env python3
"""
UserScript Manager - Sistema de gestión de scripts de usuario tipo Greasemonkey

Características:
- Gestión completa de scripts JavaScript personalizados
- Editor de código integrado con syntax highlighting
- Inyección automática en páginas web
- API GM_* (GM_setValue, GM_getValue, GM_addStyle, etc.)
- Import/Export de scripts
- Scripts de ejemplo precargados
- Almacenamiento persistente en SQLite
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QListWidget, QListWidgetItem, QTextEdit,
                               QLineEdit, QGroupBox, QTabWidget, QWidget,
                               QMessageBox, QFileDialog, QCheckBox, QComboBox,
                               QSplitter, QDialogButtonBox, QPlainTextEdit)
from PySide6.QtCore import Qt, Signal, QObject, QStandardPaths, QUrl
from PySide6.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor
import sqlite3
import os
import re
import json
from datetime import datetime
from pathlib import Path


class UserScriptManager(QObject):
    """Gestor de scripts de usuario"""

    script_changed = Signal()  # Emite cuando cambia la lista de scripts

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        # Configuración
        self.scripts_dir = self._get_scripts_directory()
        self.db_path = os.path.join(self.scripts_dir, "userscripts.db")
        self.data_dir = os.path.join(self.scripts_dir, "data")

        # Crear directorios
        os.makedirs(self.scripts_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)

        # Inicializar base de datos
        self._init_database()

        # Cargar scripts de ejemplo si es primera vez
        if not self.get_all_scripts():
            self._install_example_scripts()
    def _get_scripts_directory(self):
        """Obtiene el directorio para almacenar scripts"""
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        scripts_dir = os.path.join(app_data, "Katphi", "UserScripts")
        return scripts_dir
    def _init_database(self):
        """Inicializa la base de datos"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                author TEXT,
                version TEXT,
                code TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                match_patterns TEXT,
                run_at TEXT DEFAULT 'document-end',
                grants TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')

        # Tabla para almacenar datos de GM_setValue/getValue
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS script_storage (
                script_id INTEGER,
                key TEXT,
                value TEXT,
                PRIMARY KEY (script_id, key),
                FOREIGN KEY (script_id) REFERENCES scripts(id)
            )
        ''')

        conn.commit()
        conn.close()
    def create_script(self, name, code, description="", author="", version="1.0",
                     match_patterns="*://*/*", run_at="document-end", grants=""):
        """Crear un nuevo script"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now().isoformat()

        cursor.execute('''
            INSERT INTO scripts (name, description, author, version, code,
                               enabled, match_patterns, run_at, grants,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        ''', (name, description, author, version, code, match_patterns,
              run_at, grants, now, now))
        script_id = cursor.lastrowid
        conn.commit()
        conn.close()

        self.script_changed.emit()
        return script_id
    def update_script(self, script_id, **kwargs):
        """Actualizar un script existente"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Construir query dinámicamente
        updates = []
        params = []

        for key, value in kwargs.items():
            if key in ['name', 'description', 'author', 'version', 'code',
                      'enabled', 'match_patterns', 'run_at', 'grants']:
                updates.append(f"{key} = ?")
                params.append(value)
        if updates:
            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(script_id)

            query = f"UPDATE scripts SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)
            conn.commit()
        conn.close()
        self.script_changed.emit()
    def delete_script(self, script_id):
        """Eliminar un script"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Eliminar datos asociados
        cursor.execute('DELETE FROM script_storage WHERE script_id = ?', (script_id,))

        # Eliminar script
        cursor.execute('DELETE FROM scripts WHERE id = ?', (script_id,))

        conn.commit()
        conn.close()

        self.script_changed.emit()
    def get_script(self, script_id):
        """Obtener un script por ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM scripts WHERE id = ?', (script_id,))
        row = cursor.fetchone()

        conn.close()

        if row:
            return {
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'author': row[3],
                'version': row[4],
                'code': row[5],
                'enabled': bool(row[6]),
                'match_patterns': row[7],
                'run_at': row[8],
                'grants': row[9],
                'created_at': row[10],
                'updated_at': row[11]
            }
        return None
    def get_all_scripts(self):
        """Obtener todos los scripts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM scripts ORDER BY name')
        scripts = []

        for row in cursor.fetchall():
            scripts.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'author': row[3],
                'version': row[4],
                'code': row[5],
                'enabled': bool(row[6]),
                'match_patterns': row[7],
                'run_at': row[8],
                'grants': row[9],
                'created_at': row[10],
                'updated_at': row[11]
            })
        conn.close()
        return scripts
    def get_scripts_for_url(self, url):
        """Obtener scripts que coinciden con una URL"""
        matching_scripts = []

        for script in self.get_all_scripts():
            if not script['enabled']:
                continue
            # Verificar si la URL coincide con algún patrón
            patterns = script['match_patterns'].split(',')
            for pattern in patterns:
                pattern = pattern.strip()
                if self._match_pattern(url, pattern):
                    matching_scripts.append(script)
                    break
        return matching_scripts
    def _match_pattern(self, url, pattern):
        """Verificar si una URL coincide con un patrón"""
        # Convertir patrón de match a regex
        # *://*/* → .*://.*/.*
        regex_pattern = pattern.replace('.', r'\.')
        regex_pattern = regex_pattern.replace('*', '.*')
        regex_pattern = f"^{regex_pattern}$"

        try:
            return bool(re.match(regex_pattern, url))
        except:
            return False
    def toggle_script(self, script_id, enabled):
        """Activar/desactivar un script"""
        self.update_script(script_id, enabled=1 if enabled else 0)
    def import_script(self, file_path):
        """Importar script desde archivo"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            # Parsear metadatos
            metadata = self._parse_metadata(code)

            script_id = self.create_script(
                name=metadata.get('name', os.path.basename(file_path)),
                description=metadata.get('description', ''),
                author=metadata.get('author', ''),
                version=metadata.get('version', '1.0'),
                code=code,
                match_patterns=','.join(metadata.get('match', ['*://*/*'])),
                run_at=metadata.get('run-at', 'document-end'),
                grants=','.join(metadata.get('grant', []))
            )

            return script_id
        except Exception as e:
            print(f"[ERROR] Error importing script: {e}")
            return None
    def export_script(self, script_id, file_path):
        """Exportar script a archivo"""
        script = self.get_script(script_id)
        if not script:
            return False
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(script['code'])
            return True
        except Exception as e:
            print(f"[ERROR] Error exporting script: {e}")
            return False
    def _parse_metadata(self, code):
        """Parsear metadatos de un script (comentarios ==UserScript==)"""
        metadata = {}
        in_metadata = False

        for line in code.split('\n'):
            line = line.strip()

            if '==UserScript==' in line:
                in_metadata = True
                continue
            elif '==/UserScript==' in line:
                break
            if in_metadata and line.startswith('//'):
                # @key value
                match = re.match(r'//\s*@(\w+)\s+(.+)', line)
                if match:
                    key = match.group(1)
                    value = match.group(2).strip()

                    if key in ['match', 'grant', 'include', 'exclude']:
                        if key not in metadata:
                            metadata[key] = []
                        metadata[key].append(value)
                    else:
                        metadata[key] = value
        return metadata
    # GM API - Storage
    def gm_set_value(self, script_id, key, value):
        """Implementación de GM_setValue"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO script_storage (script_id, key, value)
            VALUES (?, ?, ?)
        ''', (script_id, key, json.dumps(value)))

        conn.commit()
        conn.close()
    def gm_get_value(self, script_id, key, default=None):
        """Implementación de GM_getValue"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT value FROM script_storage
            WHERE script_id = ? AND key = ?
        ''', (script_id, key))

        row = cursor.fetchone()
        conn.close()

        if row:
            try:
                return json.loads(row[0])
            except:
                return row[0]
        return default
    def _install_example_scripts(self):
        """Instalar scripts de ejemplo precargados"""
        examples = [
            {
                'name': 'Dark Mode Universal',
                'description': 'Aplica tema oscuro a todas las páginas web',
                'author': 'Katphi',
                'version': '1.0',
                'match_patterns': '*://*/*',
                'run_at': 'document-start',
                'code': '''// ==UserScript==
// @name         Dark Mode Universal
// @description  Aplica tema oscuro a todas las páginas
// @match        *://*/*
// @run-at       document-start
// @grant        GM_addStyle
// ==/UserScript==

(function() {
    'use strict';

    const darkModeCSS = `
        html {
            filter: invert(0.9) hue-rotate(180deg) !important;
            background-color: #1a1a1a !important;
        }

        img, video, iframe, [style*="background-image"] {
            filter: invert(1) hue-rotate(180deg) !important;
        }

        * {
            background-color: inherit !important;
            border-color: #444 !important;
        }
    `;

    // Inyectar CSS
    const style = document.createElement('style');
    style.textContent = darkModeCSS;
    document.documentElement.appendChild(style);
})();
'''
            },
            {
                'name': 'Ad Blocker Simple',
                'description': 'Oculta elementos de publicidad comunes',
                'author': 'Katphi',
                'version': '1.0',
                'match_patterns': '*://*/*',
                'run_at': 'document-end',
                'code': '''// ==UserScript==
// @name         Simple Ad Blocker
// @description  Oculta elementos de publicidad comunes
// @match        *://*/*
// @run-at       document-end
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    const adSelectors = [
        '.ad', '.ads', '.advertisement', '.banner',
        '[class*="ad-"]', '[class*="ads-"]',
        '[id*="ad-"]', '[id*="ads-"]',
        '[class*="sponsor"]', '[id*="sponsor"]',
        'iframe[src*="doubleclick"]',
        'iframe[src*="googlesyndication"]'
    ];

    function removeAds() {
        adSelectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => {
                el.style.display = 'none';
                console.log('[Ad Blocker] Blocked:', el);
            });
        });
    }

    // Ejecutar al cargar
    removeAds();

    // Observar cambios en el DOM
    const observer = new MutationObserver(removeAds);
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
})();
'''
            },
            {
                'name': 'Auto HD YouTube',
                'description': 'Fuerza calidad HD en videos de YouTube',
                'author': 'Katphi',
                'version': '1.0',
                'match_patterns': '*://www.youtube.com/*',
                'run_at': 'document-end',
                'code': '''// ==UserScript==
// @name         Auto HD YouTube
// @description  Fuerza calidad HD en videos de YouTube
// @match        *://www.youtube.com/*
// @run-at       document-end
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    function setHDQuality() {
        const video = document.querySelector('video');
        if (video) {
            // Esperar a que el video esté listo
            video.addEventListener('loadedmetadata', () => {
                try {
                    // Intentar configurar calidad HD
                    const player = document.querySelector('.html5-video-player');
                    if (player && player.setPlaybackQualityRange) {
                        player.setPlaybackQualityRange('hd1080');
                        console.log('[Auto HD] Quality set to 1080p');
                    }
                } catch(e) {
                    console.log('[Auto HD] Could not set quality:', e);
                }
            });
        }
    }

    // Ejecutar cuando se carga un video
    setHDQuality();

    // Re-ejecutar al cambiar de video
    const observer = new MutationObserver(setHDQuality);
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
})();
'''
            },
            {
                'name': 'Disable Right-Click Protection',
                'description': 'Habilita click derecho en sitios que lo bloquean',
                'author': 'Katphi',
                'version': '1.0',
                'match_patterns': '*://*/*',
                'run_at': 'document-start',
                'code': '''// ==UserScript==
// @name         Disable Right-Click Protection
// @description  Habilita click derecho en sitios que lo bloquean
// @match        *://*/*
// @run-at       document-start
// @grant        none
// ==/UserScript==

(function() {
    'use strict';

    // Eliminar listeners de contextmenu
    document.addEventListener('contextmenu', function(e) {
        e.stopPropagation();
    }, true);

    // Eliminar protección de selección
    document.addEventListener('selectstart', function(e) {
        e.stopPropagation();
    }, true);

    // Eliminar protección de copia
    document.addEventListener('copy', function(e) {
        e.stopPropagation();
    }, true);

    console.log('[Right-Click] Protection disabled');
})();
'''
            },
            {
                'name': 'Remove Paywalls',
                'description': 'Intenta eliminar paywalls de sitios de noticias',
                'author': 'Katphi',
                'version': '1.0',
                'match_patterns': '*://*/*',
                'run_at': 'document-end',
                'code': '''// ==UserScript==
// @name         Remove Paywalls
// @description  Intenta eliminar paywalls de sitios de noticias
// @match        *://*/*
// @run-at       document-end
// @grant        GM_addStyle
// ==/UserScript==

(function() {
    'use strict';

    // Eliminar overlays comunes de paywall
    const paywallSelectors = [
        '[class*="paywall"]',
        '[class*="subscription"]',
        '[class*="premium-content"]',
        '.tp-modal',
        '.tp-backdrop'
    ];

    paywallSelectors.forEach(selector => {
        document.querySelectorAll(selector).forEach(el => {
            el.remove();
        });
    });

    // Restaurar scroll
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';

    // Eliminar blur
    const style = document.createElement('style');
    style.textContent = `
        * {
            filter: none !important;
            -webkit-filter: none !important;
        }
    `;
    document.head.appendChild(style);

    console.log('[Paywall Remover] Attempted to remove paywalls');
})();
'''
            }
        ]

        for example in examples:
            self.create_script(**example)
        print(f"[OK] {len(examples)} example scripts installed")


class JavaScriptHighlighter(QSyntaxHighlighter):
    """Syntax highlighter para JavaScript"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569CD6"))
        keyword_format.setFontWeight(QFont.Bold)

        keywords = [
            'function', 'var', 'let', 'const', 'if', 'else', 'for', 'while',
            'return', 'break', 'continue', 'switch', 'case', 'default',
            'try', 'catch', 'finally', 'throw', 'new', 'this', 'typeof',
            'class', 'extends', 'super', 'static', 'async', 'await'
        ]

        for keyword in keywords:
            pattern = f"\\b{keyword}\\b"
            self.highlighting_rules.append((re.compile(pattern), keyword_format))
        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178"))
        self.highlighting_rules.append((re.compile(r'"[^"\\]*(\\.[^"\\]*)*"'), string_format))
        self.highlighting_rules.append((re.compile(r"'[^'\\]*(\\.[^'\\]*)*'"), string_format))

        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955"))
        comment_format.setFontItalic(True)
        self.highlighting_rules.append((re.compile(r'//[^\n]*'), comment_format))

        # Numbers
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#B5CEA8"))
        self.highlighting_rules.append((re.compile(r'\b\d+\.?\d*\b'), number_format))

        # Functions
        function_format = QTextCharFormat()
        function_format.setForeground(QColor("#DCDCAA"))
        self.highlighting_rules.append((re.compile(r'\b[A-Za-z0-9_]+(?=\()'), function_format))
    def highlightBlock(self, text):
        """Aplicar highlighting a un bloque de texto"""
        for pattern, format in self.highlighting_rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), format)


class UserScriptDialog(QDialog):
    """Diálogo de gestión de UserScripts"""

    def __init__(self, script_manager, parent=None):
        super().__init__(parent)
        self.script_manager = script_manager
        self.current_script_id = None

        self.setWindowTitle("UserScripts Manager")
        self.setModal(True)
        self.setMinimumSize(900, 600)

        self.setup_ui()
        self.load_scripts()

        # Conectar señales
        self.script_manager.script_changed.connect(self.load_scripts)
    def setup_ui(self):
        """Configurar interfaz del diálogo"""
        layout = QVBoxLayout(self)

        # Título
        title = QLabel("Gestión de UserScripts")
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)

        # Tabs
        tabs = QTabWidget()

        # Tab 1: Mis Scripts
        scripts_tab = self.create_scripts_tab()
        tabs.addTab(scripts_tab, "Mis Scripts")

        # Tab 2: Editor
        editor_tab = self.create_editor_tab()
        tabs.addTab(editor_tab, "Editor")

        # Tab 3: Ejemplos
        examples_tab = self.create_examples_tab()
        tabs.addTab(examples_tab, "Scripts de Ejemplo")

        layout.addWidget(tabs)

        # Botón cerrar
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
    def create_scripts_tab(self):
        """Crear tab de lista de scripts"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Lista de scripts
        self.scripts_list = QListWidget()
        self.scripts_list.itemClicked.connect(self.on_script_selected)
        self.scripts_list.itemDoubleClicked.connect(self.edit_script)
        layout.addWidget(self.scripts_list)

        # Botones
        buttons_layout = QHBoxLayout()

        new_btn = QPushButton("Nuevo")
        new_btn.clicked.connect(self.new_script)
        buttons_layout.addWidget(new_btn)

        edit_btn = QPushButton("Editar")
        edit_btn.clicked.connect(self.edit_script)
        buttons_layout.addWidget(edit_btn)

        delete_btn = QPushButton("Eliminar")
        delete_btn.clicked.connect(self.delete_script)
        buttons_layout.addWidget(delete_btn)

        buttons_layout.addStretch()

        import_btn = QPushButton("Importar")
        import_btn.clicked.connect(self.import_script)
        buttons_layout.addWidget(import_btn)

        export_btn = QPushButton("Exportar")
        export_btn.clicked.connect(self.export_script)
        buttons_layout.addWidget(export_btn)

        layout.addLayout(buttons_layout)

        # Info del script seleccionado
        info_group = QGroupBox("Información del Script")
        info_layout = QVBoxLayout()

        self.info_label = QLabel("Selecciona un script para ver su información")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        return widget
    def create_editor_tab(self):
        """Crear tab de editor"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Metadata
        meta_group = QGroupBox("Metadatos del Script")
        meta_layout = QVBoxLayout()

        # Nombre
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Nombre:"))
        self.editor_name = QLineEdit()
        name_layout.addWidget(self.editor_name)
        meta_layout.addLayout(name_layout)

        # Descripción
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("Descripción:"))
        self.editor_desc = QLineEdit()
        desc_layout.addWidget(self.editor_desc)
        meta_layout.addLayout(desc_layout)

        # Match pattern
        match_layout = QHBoxLayout()
        match_layout.addWidget(QLabel("Match Pattern:"))
        self.editor_match = QLineEdit()
        self.editor_match.setPlaceholderText("*://*/*")
        match_layout.addWidget(self.editor_match)
        meta_layout.addLayout(match_layout)

        # Run-at
        runat_layout = QHBoxLayout()
        runat_layout.addWidget(QLabel("Run At:"))
        self.editor_runat = QComboBox()
        self.editor_runat.addItems(['document-start', 'document-ready', 'document-end'])
        self.editor_runat.setCurrentText('document-end')
        runat_layout.addWidget(self.editor_runat)
        meta_layout.addLayout(runat_layout)

        meta_group.setLayout(meta_layout)
        layout.addWidget(meta_group)

        # Editor de código
        code_label = QLabel("Código JavaScript:")
        layout.addWidget(code_label)

        self.code_editor = QPlainTextEdit()
        self.code_editor.setFont(QFont("Consolas", 10))
        self.code_editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 8px;
            }
        """)

        # Syntax highlighter
        self.highlighter = JavaScriptHighlighter(self.code_editor.document())

        layout.addWidget(self.code_editor)

        # Botones del editor
        editor_buttons = QHBoxLayout()

        save_btn = QPushButton("Guardar")
        save_btn.clicked.connect(self.save_script)
        editor_buttons.addWidget(save_btn)

        clear_btn = QPushButton("Limpiar")
        clear_btn.clicked.connect(self.clear_editor)
        editor_buttons.addWidget(clear_btn)

        editor_buttons.addStretch()

        layout.addLayout(editor_buttons)

        return widget
    def create_examples_tab(self):
        """Crear tab de ejemplos"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(QLabel("Scripts de ejemplo precargados:"))

        info = QLabel(
            "Los siguientes scripts de ejemplo ya están instalados y listos para usar:\n\n"
            "• Dark Mode Universal - Tema oscuro para todas las páginas\n"
            "• Ad Blocker Simple - Bloquea publicidad común\n"
            "• Auto HD YouTube - Fuerza calidad HD en YouTube\n"
            "• Disable Right-Click Protection - Habilita click derecho\n"
            "• Remove Paywalls - Intenta eliminar paywalls de noticias\n\n"
            "Puedes activar/desactivar estos scripts desde la pestaña 'Mis Scripts'."
        )
        info.setWordWrap(True)
        info.setStyleSheet("background-color: #f9f9f9; padding: 15px; border-radius: 8px;")
        layout.addWidget(info)

        layout.addStretch()

        return widget
    def load_scripts(self):
        """Cargar lista de scripts"""
        self.scripts_list.clear()

        for script in self.script_manager.get_all_scripts():
            item_text = script['name']
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, script['id'])
            item.setCheckState(Qt.Checked if script['enabled'] else Qt.Unchecked)
            self.scripts_list.addItem(item)
    def on_script_selected(self, item):
        """Cuando se selecciona un script"""
        script_id = item.data(Qt.UserRole)
        script = self.script_manager.get_script(script_id)

        if script:
            info = f"""
<b>Nombre:</b> {script['name']}<br>
<b>Descripción:</b> {script['description']}<br>
<b>Autor:</b> {script['author']}<br>
<b>Versión:</b> {script['version']}<br>
<b>Match Patterns:</b> {script['match_patterns']}<br>
<b>Run At:</b> {script['run_at']}<br>
<b>Estado:</b> {'Activo' if script['enabled'] else 'Desactivado'}<br>
            """
            self.info_label.setText(info)
        # Toggle al hacer click en checkbox
        enabled = item.checkState() == Qt.Checked
        self.script_manager.toggle_script(script_id, enabled)
    def new_script(self):
        """Crear nuevo script"""
        self.current_script_id = None
        self.clear_editor()
    def edit_script(self):
        """Editar script seleccionado"""
        current_item = self.scripts_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No hay script seleccionado",
                              "Por favor selecciona un script para editar.")
            return
        script_id = current_item.data(Qt.UserRole)
        script = self.script_manager.get_script(script_id)

        if script:
            self.current_script_id = script_id
            self.editor_name.setText(script['name'])
            self.editor_desc.setText(script['description'])
            self.editor_match.setText(script['match_patterns'])
            self.editor_runat.setCurrentText(script['run_at'])
            self.code_editor.setPlainText(script['code'])
    def delete_script(self):
        """Eliminar script seleccionado"""
        current_item = self.scripts_list.currentItem()
        if not current_item:
            return
        script_id = current_item.data(Qt.UserRole)
        script = self.script_manager.get_script(script_id)

        reply = QMessageBox.question(
            self,
            "Eliminar script",
            f"¿Eliminar el script '{script['name']}'?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.script_manager.delete_script(script_id)
            QMessageBox.information(self, "Script eliminado",
                                  f"El script '{script['name']}' ha sido eliminado.")
    def save_script(self):
        """Guardar script desde el editor"""
        name = self.editor_name.text().strip()
        code = self.code_editor.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "Nombre requerido",
                              "Por favor ingresa un nombre para el script.")
            return
        if not code:
            QMessageBox.warning(self, "Código requerido",
                              "Por favor ingresa el código del script.")
            return
        if self.current_script_id:
            # Actualizar script existente
            self.script_manager.update_script(
                self.current_script_id,
                name=name,
                description=self.editor_desc.text(),
                code=code,
                match_patterns=self.editor_match.text() or '*://*/*',
                run_at=self.editor_runat.currentText()
            )
            QMessageBox.information(self, "Script actualizado",
                                  f"El script '{name}' ha sido actualizado.")
        else:
            # Crear nuevo script
            self.script_manager.create_script(
                name=name,
                description=self.editor_desc.text(),
                code=code,
                match_patterns=self.editor_match.text() or '*://*/*',
                run_at=self.editor_runat.currentText()
            )
            QMessageBox.information(self, "Script creado",
                                  f"El script '{name}' ha sido creado.")
        self.clear_editor()
    def clear_editor(self):
        """Limpiar editor"""
        self.current_script_id = None
        self.editor_name.clear()
        self.editor_desc.clear()
        self.editor_match.setText('*://*/*')
        self.editor_runat.setCurrentText('document-end')
        self.code_editor.clear()
    def import_script(self):
        """Importar script desde archivo"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar UserScript",
            "",
            "JavaScript Files (*.js);;All Files (*.*)"
        )

        if file_path:
            script_id = self.script_manager.import_script(file_path)
            if script_id:
                QMessageBox.information(self, "Script importado",
                                      "El script ha sido importado correctamente.")
            else:
                QMessageBox.critical(self, "Error",
                                   "No se pudo importar el script.")
    def export_script(self):
        """Exportar script a archivo"""
        current_item = self.scripts_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "No hay script seleccionado",
                              "Por favor selecciona un script para exportar.")
            return
        script_id = current_item.data(Qt.UserRole)
        script = self.script_manager.get_script(script_id)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar UserScript",
            f"{script['name']}.js",
            "JavaScript Files (*.js);;All Files (*.*)"
        )

        if file_path:
            if self.script_manager.export_script(script_id, file_path):
                QMessageBox.information(self, "Script exportado",
                                      f"El script ha sido exportado a:\n{file_path}")
            else:
                QMessageBox.critical(self, "Error",
                                   "No se pudo exportar el script.")
