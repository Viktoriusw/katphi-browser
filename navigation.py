from PySide6.QtCore import QUrl


from downloads import DownloadManager


from PySide6.QtWebEngineWidgets import QWebEngineView


from PySide6.QtCore import QThread


def format_url(url):
    """Format URL adding https:// if no protocol is present"""

    if not url.startswith("http"):
        return f"https://{url}"
    return url


class NavigationManager:
    def __init__(self, parent):
        self.parent = parent

        self.tab_manager = None  # Postpone assignment until all managers are initialized

        self.download_manager = DownloadManager(parent)  # Ensure DownloadManager is correctly initialized
    def initialize_tab_manager(self, tab_manager):
        """Initialize the tab manager after creation to avoid circular dependencies"""

        self.tab_manager = tab_manager
    def _get_current_widget(self):
        """Get the current active QWebEngineView widget or None if not available"""

        if not self.tab_manager or not self.tab_manager.tabs:
            print("Error: No tab manager or tabs available")

            return None
        current_widget = self.tab_manager.tabs.currentWidget()

        if isinstance(current_widget, QWebEngineView):
            return current_widget
        print("Error: Active tab is not a QWebEngineView.")

        return None
    def navigate_back(self):
        """Navigate to the previous page in history"""

        current_widget = self._get_current_widget()

        if current_widget:
            current_widget.page().triggerAction(current_widget.page().WebAction.Back)
    def navigate_forward(self):
        """Navigate to the next page in history"""

        current_widget = self._get_current_widget()

        if current_widget:
            current_widget.page().triggerAction(current_widget.page().WebAction.Forward)
    def refresh_page(self):
        """Reload the current page"""

        current_widget = self._get_current_widget()

        if current_widget:
            current_widget.page().triggerAction(current_widget.page().WebAction.Reload)
    def navigate_to_url(self, url):
        """Navigate to the specified URL after proper validation"""

        try:
            if not isinstance(url, str) or not url.strip():
                print("Error: Empty URL or not a string")

                return
            # Use format_url for consistent URL formatting

            formatted_url = format_url(url)

            qurl = QUrl(formatted_url)

            if not qurl.isValid():
                print(f"Error: Invalid URL {formatted_url}")

                return
            current_widget = self._get_current_widget()

            if current_widget:
                current_widget.setUrl(qurl)

                print(f"Successful navigation to: {formatted_url}")
            else:
                print("Error: No active tab available")
        except Exception as e:
            print(f"Unexpected error trying to navigate to URL: {e}")
    def truncate_tab_title(self, title, max_length=15):
        """Truncate long tab titles with ellipsis"""

        if not title:
            return "New Tab"
        return title if len(title) <= max_length else title[:max_length] + "..."
    def setup_downloads(self, browser):
        """Configure download handling for the browser"""

        try:
            if not browser or not hasattr(browser, 'page'):
                print("Error: Invalid browser for configuring downloads")

                return
            browser.page().profile().downloadRequested.connect(self.download_manager.handle_download)

            print("Downloads configured correctly.")
        except Exception as e:
            print(f"Error configuring downloads: {e}")
