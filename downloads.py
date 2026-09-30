from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 


                              QLabel, QProgressBar, QFileDialog, QMessageBox)


from PySide6.QtCore import Qt, Signal, QObject, QStandardPaths, QTimer


from PySide6.QtWebEngineCore import QWebEngineDownloadRequest


from PySide6.QtGui import QIcon, QPixmap


import os


import re


from pathlib import Path


import mimetypes


class DownloadManager(QObject):
    download_started = Signal(str)

    download_progress = Signal(int)

    download_completed = Signal(str)

    download_failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.parent = parent

        self.safe_chars = re.compile(r'[^\\/\w\d\-_\.\s]', re.ASCII)  # Caracteres permitidos en nombres de archivo

        self.downloads = {}

        self.init_ui()

        self.init_mime_types()
    def init_mime_types(self):
        """Initializes MIME types and their descriptions"""

        self.mime_descriptions = {

            # Documents

            'application/pdf': 'PDF Document',

            'application/msword': 'Word Document',

            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word Document',

            'application/vnd.ms-excel': 'Excel Spreadsheet',

            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'Excel Spreadsheet',

            'application/vnd.ms-powerpoint': 'PowerPoint Presentation',

            'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PowerPoint Presentation',

            'text/plain': 'Text File',

            'text/html': 'Web Page',

            'text/css': 'Style Sheet',

            'text/javascript': 'JavaScript Script',

            # Images

            'image/jpeg': 'JPEG Image',

            'image/png': 'PNG Image',

            'image/gif': 'GIF Image',

            'image/svg+xml': 'SVG Vector Image',

            'image/webp': 'WebP Image',

            # Audio

            'audio/mpeg': 'MP3 Audio File',

            'audio/wav': 'WAV Audio File',

            'audio/ogg': 'OGG Audio File',

            'audio/webm': 'WebM Audio File',

            # Video

            'video/mp4': 'MP4 Video',

            'video/webm': 'WebM Video',

            'video/ogg': 'OGG Video',

            # Compressed

            'application/zip': 'ZIP Archive',

            'application/x-rar-compressed': 'RAR Archive',

            'application/x-7z-compressed': '7Z Archive',

            'application/x-tar': 'TAR Archive',

            'application/gzip': 'GZIP Archive',

            # Executables

            'application/x-msdownload': 'Windows Application',

            'application/x-executable': 'Executable Application',

            'application/x-shockwave-flash': 'Flash Application',

            # Others

            'application/json': 'JSON File',

            'application/xml': 'XML File',

            'application/octet-stream': 'Binary File'
        }
    def init_ui(self):
        self.widget = QWidget()

        layout = QVBoxLayout(self.widget)

        # Title

        title = QLabel("Downloads")

        title.setStyleSheet("font-size: 16px; font-weight: bold;")

        layout.addWidget(title)

        # Downloads list

        self.downloads_layout = QVBoxLayout()

        layout.addLayout(self.downloads_layout)

        self.widget.setLayout(layout)
    def _sanitize_filename(self, filename):
        """Cleans up potentially dangerous characters from filenames"""

        if not filename:
            return "download"
        # Remove unsafe characters

        clean_name = self.safe_chars.sub('', filename)

        # Limit filename length

        clean_name = clean_name[:150]  # Reasonable maximum length

        return clean_name or "download"  # Fallback if empty
    def _get_safe_download_dir(self):
        """Gets a safe directory for downloads"""

        # Use the system's default download directory

        download_dir = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)

        # Check if the directory exists and is writable

        if not os.access(download_dir, os.W_OK):
            download_dir = os.path.expanduser("~")  # Fallback to user's home
        return download_dir
    def handle_download(self, download):
        """Handles a new download"""

        try:
            # Get the filename from the URL

            suggested_name = download.suggestedFileName()

            if not suggested_name:
                suggested_name = "download"
            # Show dialog to select location

            file_path, _ = QFileDialog.getSaveFileName(

                self.parent,

                "Save File",

                os.path.expanduser(f"~/Downloads/{suggested_name}"),

                "All Files (*.*)"
            )

            if file_path:
                # Configure the download

                download.setDownloadDirectory(os.path.dirname(file_path))

                download.setDownloadFileName(os.path.basename(file_path))

                # Connect signals

                download.stateChanged.connect(

                    lambda state: self.download_state_changed(download, state)
                )

                # Start the download

                download.accept()

                # Create download widget

                self.create_download_widget(download, file_path)

                # Add to NEW download panel if available
                if hasattr(self.parent, 'download_panel'):
                    self.parent.download_panel.add_download(download)
                    # Show download panel automatically
                    if hasattr(self.parent, 'download_dock'):
                        self.parent.download_dock.show()
                self.download_started.emit(file_path)
            else:
                download.cancel()
        except Exception as e:
            print(f"Error handling download: {str(e)}")

            self.download_failed.emit(str(e))
    def download_state_changed(self, download, state):
        """Handles download state changes"""

        try:
            if download in self.downloads:
                if state == QWebEngineDownloadRequest.DownloadCompleted:
                    self.downloads[download]['progress_bar'].setValue(100)

                    self.download_completed.emit(self.downloads[download]['path'])

                    self.show_download_confirmation(self.downloads[download]['path'])

                    # Clean up after a time

                    QTimer.singleShot(5000, lambda: self.cleanup_download(download))
                elif state == QWebEngineDownloadRequest.DownloadCancelled:
                    self.download_failed.emit("Download cancelled")

                    self.cleanup_download(download)
                elif state == QWebEngineDownloadRequest.DownloadInProgress:
                    # Update progress

                    received = download.receivedBytes()

                    total = download.totalBytes()

                    if total > 0:
                        progress = int((received / total) * 100)

                        self.downloads[download]['progress_bar'].setValue(progress)

                        self.download_progress.emit(progress)
        except Exception as e:
            print(f"Error handling state change: {str(e)}")
    def get_file_type_info(self, file_path):
        """Gets information about the file type"""

        try:
            # Get MIME type

            mime_type, _ = mimetypes.guess_type(file_path)

            if not mime_type:
                # Try to determine type by extension

                ext = os.path.splitext(file_path)[1].lower()

                if ext == '.pdf':
                    mime_type = 'application/pdf'
                elif ext in ['.doc', '.docx']:
                    mime_type = 'application/msword'
                elif ext in ['.xls', '.xlsx']:
                    mime_type = 'application/vnd.ms-excel'
                elif ext in ['.ppt', '.pptx']:
                    mime_type = 'application/vnd.ms-powerpoint'
                elif ext in ['.jpg', '.jpeg']:
                    mime_type = 'image/jpeg'
                elif ext == '.png':
                    mime_type = 'image/png'
                elif ext == '.gif':
                    mime_type = 'image/gif'
                elif ext in ['.mp3', '.wav', '.ogg']:
                    mime_type = 'audio/mpeg'
                elif ext in ['.mp4', '.webm']:
                    mime_type = 'video/mp4'
                elif ext in ['.zip', '.rar', '.7z']:
                    mime_type = 'application/zip'
                else:
                    mime_type = 'application/octet-stream'
            # Get description

            description = self.mime_descriptions.get(mime_type, 'Unknown file')

            # Get icon based on type

            icon_name = self._get_icon_name(mime_type)

            return {

                'mime_type': mime_type,

                'description': description,

                'icon': icon_name
            }
        except Exception as e:
            print(f"Error getting file type: {str(e)}")

            return {

                'mime_type': 'application/octet-stream',

                'description': 'Unknown file',

                'icon': 'unknown'
            }
    def _get_icon_name(self, mime_type):
        """Gets the icon name based on the MIME type"""

        if mime_type.startswith('image/'):
            return 'image'
        elif mime_type.startswith('video/'):
            return 'video'
        elif mime_type.startswith('audio/'):
            return 'audio'
        elif mime_type.startswith('text/'):
            return 'text'
        elif mime_type == 'application/pdf':
            return 'pdf'
        elif mime_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
            return 'word'
        elif mime_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
            return 'excel'
        elif mime_type in ['application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
            return 'powerpoint'
        elif mime_type in ['application/zip', 'application/x-rar-compressed', 'application/x-7z-compressed']:
            return 'archive'
        elif mime_type in ['application/x-msdownload', 'application/x-executable']:
            return 'executable'
        else:
            return 'unknown'
    def create_download_widget(self, download, file_path):
        """Creates a widget to display download progress"""

        try:
            container = QWidget()

            layout = QHBoxLayout(container)

            # Get file type information

            file_info = self.get_file_type_info(file_path)

            # Container for icon and name

            info_container = QWidget()

            info_layout = QVBoxLayout(info_container)

            # File type icon

            icon_label = QLabel()

            icon_label.setPixmap(QIcon(f":/icons/{file_info['icon']}.png").pixmap(32, 32))

            info_layout.addWidget(icon_label)

            # File name

            name_label = QLabel(os.path.basename(file_path))

            name_label.setStyleSheet("font-weight: bold;")

            info_layout.addWidget(name_label)

            # File type

            type_label = QLabel(file_info['description'])

            type_label.setStyleSheet("color: gray; font-size: 10px;")

            info_layout.addWidget(type_label)

            layout.addWidget(info_container)

            # Progress bar

            progress_bar = QProgressBar()

            progress_bar.setMinimum(0)

            progress_bar.setMaximum(100)

            layout.addWidget(progress_bar)

            # Cancel button

            cancel_button = QPushButton("Cancel")

            cancel_button.clicked.connect(lambda: self.cancel_download(download))

            layout.addWidget(cancel_button)

            # Save reference

            self.downloads[download] = {

                'widget': container,

                'progress_bar': progress_bar,

                'path': file_path,

                'file_info': file_info
            }

            self.downloads_layout.addWidget(container)
        except Exception as e:
            print(f"Error creating download widget: {str(e)}")
    def cancel_download(self, download):
        """Cancels an ongoing download"""

        try:
            if download in self.downloads:
                download.cancel()

                self.cleanup_download(download)

                self.download_failed.emit("Download cancelled by user")
        except Exception as e:
            print(f"Error cancelling download: {str(e)}")
    def cleanup_download(self, download):
        """Cleans up download resources"""

        try:
            if download in self.downloads:
                widget = self.downloads[download]['widget']

                self.downloads_layout.removeWidget(widget)

                widget.deleteLater()

                del self.downloads[download]
        except Exception as e:
            print(f"Error cleaning up download: {str(e)}")
    def get_widget(self):
        """Returns the main widget of the download manager"""

        return self.widget
    def _validate_extension(self, save_path, original_name):
        """Validates that the file extension is safe"""

        original_ext = Path(original_name).suffix.lower()

        new_ext = save_path.suffix.lower()

        # Allows changing known extensions

        common_extensions = {'.pdf', '.jpg', '.png', '.txt', '.zip', '.exe', '.msi'}

        if not original_ext and not new_ext:
            return True
        if original_ext in common_extensions and new_ext in common_extensions:
            return True
        return new_ext == original_ext
    def show_download_confirmation(self, save_path):
        """Shows download confirmation with detailed information"""

        try:
            path = Path(save_path)

            file_info = self.get_file_type_info(save_path)

            msg = QMessageBox()

            msg.setIcon(QMessageBox.Information)

            msg.setWindowTitle("Download started")

            msg.setText(f"Downloading {file_info['description']}")

            msg.setInformativeText(f"Name: {path.name}\nLocation: {save_path}")

            # Add warning based on file type

            if file_info['mime_type'] in ['application/x-msdownload', 'application/x-executable']:
                msg.setDetailedText("WARNING: This is an executable file. Ensure it comes from a trusted source.")
            elif file_info['mime_type'].startswith('application/') and not file_info['mime_type'] in ['application/pdf', 'application/zip']:
                msg.setDetailedText("WARNING: This file may contain executable code. Verify its source before opening it.")
            msg.exec()
        except Exception as e:
            print(f"Error showing confirmation: {str(e)}")

            QMessageBox.information(self.parent, "Download started",

                                  f"The file is being downloaded to: {save_path}")
