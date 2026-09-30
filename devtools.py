from PySide6.QtWidgets import QDockWidget, QVBoxLayout, QToolBar, QPushButton, QTabWidget, QTabBar, QWidget


from PySide6.QtWebEngineWidgets import QWebEngineView


from PySide6.QtCore import Qt


class DevToolsDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Developer Tools", parent)

        self.parent = parent

        self.browser = None

        # Create central widget

        self.central_widget = QWidget()

        self.setWidget(self.central_widget)

        # Create layout

        self.layout = QVBoxLayout(self.central_widget)

        # Create DevTools view

        self.dev_tools_view = QWebEngineView()

        self.layout.addWidget(self.dev_tools_view)

        # Configure minimum size

        self.setMinimumWidth(400)

        self.setMinimumHeight(300)

        # Remove hardcoded styles to inherit global theme

        # Force dark theme in web view (with error handling)

        try:
            self.dev_tools_view.page().setBackgroundColor(Qt.black)
        except Exception as e:
            print(f"Error configuring background color in DevTools: {e}")
        # Background styles now inherit from global theme
    def set_browser(self, browser):
        """Set the current browser for DevTools"""

        if isinstance(browser, QWebEngineView):
            self.browser = browser

            # Connect DevTools to browser

            self.browser.page().setDevToolsPage(self.dev_tools_view.page())

            # Show DevTools

            self.dev_tools_view.page().setInspectedPage(self.browser.page())
        else:
            # If not a valid browser, clear DevTools

            self.browser = None

            self.dev_tools_view.setUrl(None)
    def init_ui(self):
        """Initialize user interface"""

        layout = QVBoxLayout(self)

        # Remove hardcoded styles to inherit global theme

        # Create toolbar
