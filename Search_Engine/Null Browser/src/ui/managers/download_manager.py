from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QPushButton, QListWidget, QFrame, QWidget, QListWidgetItem)
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QPixmap
import os
import json
import datetime
import math
import subprocess
import sys

class DownloadManager(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Downloads")
        self.setGeometry(100, 100, 600, 400)
        self.downloads = []
        self.parent = parent
        self.load_downloads()

        # Main layout
        self.layout = QVBoxLayout(self)
        
        # Header with title and buttons
        header_layout = QHBoxLayout()
        
        # Title
        title_label = QLabel("Downloads")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Clear completed button
        self.clear_completed_btn = QPushButton("Clear Completed")
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        header_layout.addWidget(self.clear_completed_btn)
        
        # Clear all button
        self.clear_all_btn = QPushButton("Clear All")
        self.clear_all_btn.clicked.connect(self.clear_downloads)
        header_layout.addWidget(self.clear_all_btn)
        
        self.layout.addLayout(header_layout)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        self.layout.addWidget(separator)
        
        # Download list with headers
        list_layout = QVBoxLayout()
        
        # Headers
        headers_layout = QHBoxLayout()
        headers_layout.addWidget(QLabel("Name"), 3)
        headers_layout.addWidget(QLabel("Status"), 1)
        headers_layout.addWidget(QLabel("Size"), 1)
        headers_layout.addWidget(QLabel("Actions"), 2)
        list_layout.addLayout(headers_layout)
        
        # Download list
        self.download_list = QListWidget()
        self.download_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.download_list.setStyleSheet("""
            QListWidget::item { border-bottom: 1px solid #e0e0e0; padding: 5px; }
            QListWidget::item:selected { background: #e0e0ff; }
        """)
        list_layout.addWidget(self.download_list)
        
        self.layout.addLayout(list_layout)
        
        # Bottom buttons
        bottom_layout = QHBoxLayout()
        
        # Open download folder
        self.open_folder_btn = QPushButton("Open Download Folder")
        self.open_folder_btn.clicked.connect(self.open_download_folder)
        bottom_layout.addWidget(self.open_folder_btn)
        
        bottom_layout.addStretch()
        
        # Close button
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(self.close_btn)
        
        self.layout.addLayout(bottom_layout)
        
        # Populate the list
        self.refresh_download_list()

    def add_download(self, download_item):
        # Extract download details
        download_info = {
            "file_name": download_item.suggestedFileName(),
            "file_path": download_item.downloadDirectory() + "/" + download_item.suggestedFileName(),
            "status": "In Progress",
            "size": self.format_size(download_item.totalBytes()),
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.downloads.append(download_info)
        self.save_downloads()
        self.refresh_download_list()

    def update_download_status(self, download_item):
        file_path = download_item.downloadDirectory() + "/" + download_item.suggestedFileName()
        for download in self.downloads:
            if download["file_path"] == file_path:
                download["status"] = "Completed"
                download["size"] = self.format_size(download_item.totalBytes())
                break
        self.save_downloads()
        self.refresh_download_list()

    def format_size(self, size_bytes):
        # Format file size in human-readable format
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.log(size_bytes, 1024))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

    def save_downloads(self):
        downloads_dir = os.path.expanduser("~/.null_browser")
        os.makedirs(downloads_dir, exist_ok=True)
        
        with open(f"{downloads_dir}/downloads.json", "w") as file:
            json.dump(self.downloads, file, indent=4)

    def load_downloads(self):
        downloads_dir = os.path.expanduser("~/.null_browser")
        downloads_file = f"{downloads_dir}/downloads.json"
        
        if os.path.exists(downloads_file):
            try:
                with open(downloads_file, "r") as file:
                    self.downloads = json.load(file)
            except:
                self.downloads = []
        else:
            self.downloads = []

    def clear_completed(self):
        self.downloads = [d for d in self.downloads if d["status"] != "Completed"]
        self.save_downloads()
        self.refresh_download_list()

    def clear_downloads(self):
        self.downloads = []
        self.save_downloads()
        self.refresh_download_list()
    
    def open_download_folder(self):
        # Get the download directory from settings or use default
        settings = QSettings("NullBrowser", "Preferences")
        download_dir = settings.value("downloads_location", os.path.expanduser("~/Downloads"))
        
        # Open the folder using the system's file manager
        if sys.platform == 'win32':
            os.startfile(download_dir)
        elif sys.platform == 'darwin':  # macOS
            subprocess.call(['open', download_dir])
        else:  # Linux
            subprocess.call(['xdg-open', download_dir])
    
    def refresh_download_list(self):
        self.download_list.clear()
        
        for download in sorted(self.downloads, key=lambda x: x.get("timestamp", ""), reverse=True):
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 5, 5, 5)
            
            # File name with icon
            file_name_layout = QHBoxLayout()
            file_icon = QLabel()
            # You can set an icon based on file type here
            file_icon.setPixmap(QPixmap())  # Placeholder for file icon
            file_name_layout.addWidget(file_icon)
            
            file_name = QLabel(download["file_name"])
            file_name.setToolTip(download["file_path"])
            file_name_layout.addWidget(file_name)
            
            item_layout.addLayout(file_name_layout, 3)
            
            # Status
            status = QLabel(download["status"])
            if download["status"] == "Completed":
                status.setStyleSheet("color: green;")
            elif download["status"] == "In Progress":
                status.setStyleSheet("color: blue;")
            else:
                status.setStyleSheet("color: red;")
            item_layout.addWidget(status, 1)
            
            # Size
            size = QLabel(download.get("size", "Unknown"))
            item_layout.addWidget(size, 1)
            
            # Actions
            actions_layout = QHBoxLayout()
            
            if download["status"] == "Completed":
                open_btn = QPushButton("Open")
                open_btn.clicked.connect(lambda checked, path=download["file_path"]: self.open_file(path))
                actions_layout.addWidget(open_btn)
                
                open_folder_btn = QPushButton("Folder")
                open_folder_btn.clicked.connect(lambda checked, path=download["file_path"]: self.open_containing_folder(path))
                actions_layout.addWidget(open_folder_btn)
            
            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda checked, d=download: self.remove_download(d))
            actions_layout.addWidget(remove_btn)
            
            item_layout.addLayout(actions_layout, 2)
            
            # Create list item
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            
            self.download_list.addItem(list_item)
            self.download_list.setItemWidget(list_item, item_widget)
    
    def open_file(self, file_path):
        # Open the downloaded file
        if sys.platform == 'win32':
            os.startfile(file_path)
        elif sys.platform == 'darwin':  # macOS
            subprocess.call(['open', file_path])
        else:  # Linux
            subprocess.call(['xdg-open', file_path])
    
    def open_containing_folder(self, file_path):
        # Open the folder containing the file
        dir_path = os.path.dirname(file_path)
        
        if sys.platform == 'win32':
            subprocess.run(['explorer', '/select,', file_path])
        elif sys.platform == 'darwin':  # macOS
            subprocess.call(['open', '-R', file_path])
        else:  # Linux
            subprocess.call(['xdg-open', dir_path])
    
    def remove_download(self, download):
        self.downloads.remove(download)
        self.save_downloads()
        self.refresh_download_list() 