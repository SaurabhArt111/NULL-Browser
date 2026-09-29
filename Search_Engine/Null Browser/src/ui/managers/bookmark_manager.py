from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                           QPushButton, QSplitter, QWidget, QFormLayout, QLineEdit,
                           QInputDialog, QFileDialog, QListWidgetItem, QFrame)
from PyQt6.QtCore import Qt, pyqtSignal
import os
import sqlite3
import datetime

class BookmarkManager:
    def __init__(self, parent=None):
        self.parent = parent
        self.db_path = os.path.expanduser("~/.null_browser/bookmarks.db")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Initialize database
        self.init_db()
        
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY,
            title TEXT,
            url TEXT,
            added_date TEXT
        )
        ''')
        conn.commit()
        conn.close()
        
    def add_bookmark(self, title, url):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO bookmarks (title, url, added_date) VALUES (?, ?, ?)",
                      (title, url, current_date))
        conn.commit()
        conn.close()
        if self.parent:
            self.parent.statusBar().showMessage(f"Bookmark added: {title}", 3000)
        
    def get_all_bookmarks(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, url, added_date FROM bookmarks ORDER BY title")
        bookmarks = cursor.fetchall()
        conn.close()
        return bookmarks
        
    def delete_bookmark(self, bookmark_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        conn.commit()
        conn.close()
        if self.parent:
            self.parent.statusBar().showMessage("Bookmark deleted", 3000)

class BookmarksDialog(QDialog):
    bookmark_selected = pyqtSignal(str)
    
    def __init__(self, bookmark_manager, parent=None):
        super().__init__(parent)
        self.bookmark_manager = bookmark_manager
        self.setWindowTitle("Bookmarks")
        self.setMinimumSize(800, 500)
        
        layout = QVBoxLayout(self)
        
        # Header with search
        header_layout = QHBoxLayout()
        
        title_label = QLabel("Bookmarks")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search bookmarks...")
        self.search_edit.textChanged.connect(self.filter_bookmarks)
        self.search_edit.setClearButtonEnabled(True)
        header_layout.addWidget(self.search_edit)
        
        layout.addLayout(header_layout)
        
        # Splitter for folder tree and bookmark list
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Folders panel
        folder_widget = QWidget()
        folder_layout = QVBoxLayout(folder_widget)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        
        folder_label = QLabel("Folders")
        folder_label.setStyleSheet("font-weight: bold;")
        folder_layout.addWidget(folder_label)
        
        self.folder_list = QListWidget()
        self.folder_list.addItem("All Bookmarks")
        self.folder_list.addItem("Bookmarks Bar")
        self.folder_list.addItem("Other Bookmarks")
        self.folder_list.setCurrentRow(0)
        self.folder_list.currentRowChanged.connect(self.folder_changed)
        folder_layout.addWidget(self.folder_list)
        
        # Add new folder button
        new_folder_btn = QPushButton("New Folder")
        new_folder_btn.clicked.connect(self.create_new_folder)
        folder_layout.addWidget(new_folder_btn)
        
        splitter.addWidget(folder_widget)
        
        # Bookmarks list
        bookmark_widget = QWidget()
        bookmark_layout = QVBoxLayout(bookmark_widget)
        bookmark_layout.setContentsMargins(0, 0, 0, 0)
        
        # Bookmark list header
        header_widget = QWidget()
        header_widget.setStyleSheet("background-color: #f0f0f0; border-bottom: 1px solid #ccc;")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        header_layout.addWidget(QLabel("Name"), 3)
        header_layout.addWidget(QLabel("URL"), 4)
        header_layout.addWidget(QLabel("Added"), 2)
        header_layout.addWidget(QLabel("Actions"), 2)
        
        bookmark_layout.addWidget(header_widget)
        
        # Bookmarks list
        self.bookmarks_list = QListWidget()
        self.bookmarks_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.bookmarks_list.itemDoubleClicked.connect(self.open_bookmark)
        self.bookmarks_list.setStyleSheet("""
            QListWidget::item { border-bottom: 1px solid #e0e0e0; padding: 5px; }
            QListWidget::item:selected { background: #e0e0ff; }
        """)
        bookmark_layout.addWidget(self.bookmarks_list)
        
        splitter.addWidget(bookmark_widget)
        
        # Set initial sizes
        splitter.setSizes([200, 600])
        
        layout.addWidget(splitter)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.import_btn = QPushButton("Import...")
        self.import_btn.clicked.connect(self.import_bookmarks)
        button_layout.addWidget(self.import_btn)
        
        self.export_btn = QPushButton("Export...")
        self.export_btn.clicked.connect(self.export_bookmarks)
        button_layout.addWidget(self.export_btn)
        
        button_layout.addStretch()
        
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self.open_selected_bookmark)
        button_layout.addWidget(self.open_btn)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_selected_bookmark)
        button_layout.addWidget(self.delete_btn)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        
        # Load bookmarks
        self.all_bookmarks = []
        self.filtered_bookmarks = []
        self.load_bookmarks()
        
    def load_bookmarks(self):
        self.all_bookmarks = self.bookmark_manager.get_all_bookmarks()
        self.filtered_bookmarks = self.all_bookmarks.copy()
        self.refresh_bookmark_list()
        
    def refresh_bookmark_list(self):
        self.bookmarks_list.clear()
        
        for bookmark_id, title, url, added_date in self.filtered_bookmarks:
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 5, 5, 5)
            
            # Title
            title_label = QLabel(title)
            title_label.setStyleSheet("font-weight: bold;")
            title_label.setToolTip(title)
            item_layout.addWidget(title_label, 3)
            
            # URL
            url_label = QLabel(url)
            url_label.setToolTip(url)
            url_label.setStyleSheet("color: #006621;")
            item_layout.addWidget(url_label, 4)
            
            # Added date
            date_label = QLabel(added_date)
            date_label.setStyleSheet("color: #666;")
            item_layout.addWidget(date_label, 2)
            
            # Actions
            actions_layout = QHBoxLayout()
            
            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda checked, bid=bookmark_id, t=title, u=url: self.edit_bookmark(bid, t, u))
            actions_layout.addWidget(edit_btn)
            
            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(lambda checked, bid=bookmark_id: self.delete_bookmark(bid))
            actions_layout.addWidget(delete_btn)
            
            item_layout.addLayout(actions_layout, 2)
            
            # Create list item
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, (bookmark_id, url))
            list_item.setSizeHint(item_widget.sizeHint())
            
            self.bookmarks_list.addItem(list_item)
            self.bookmarks_list.setItemWidget(list_item, item_widget)
            
    def filter_bookmarks(self):
        search_text = self.search_edit.text().lower()
        
        if search_text:
            self.filtered_bookmarks = [
                bookmark for bookmark in self.all_bookmarks 
                if search_text in bookmark[1].lower() or search_text in bookmark[2].lower()
            ]
        else:
            self.filtered_bookmarks = self.all_bookmarks.copy()
            
        self.refresh_bookmark_list()
            
    def folder_changed(self, index):
        # In a real implementation, this would filter bookmarks by folder
        # For this example, we'll just show all bookmarks
        self.load_bookmarks()
            
    def open_bookmark(self, item):
        _, url = item.data(Qt.ItemDataRole.UserRole)
        self.bookmark_selected.emit(url)
        self.close()
        
    def open_selected_bookmark(self):
        selected_items = self.bookmarks_list.selectedItems()
        if selected_items:
            self.open_bookmark(selected_items[0])
            
    def delete_selected_bookmark(self):
        selected_items = self.bookmarks_list.selectedItems()
        if selected_items:
            for item in selected_items:
                bookmark_id, _ = item.data(Qt.ItemDataRole.UserRole)
                self.delete_bookmark(bookmark_id)
                
    def delete_bookmark(self, bookmark_id):
        self.bookmark_manager.delete_bookmark(bookmark_id)
        self.load_bookmarks()
        
    def edit_bookmark(self, bookmark_id, title, url):
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Bookmark")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        form_layout = QFormLayout()
        
        title_edit = QLineEdit(title)
        form_layout.addRow("Title:", title_edit)
        
        url_edit = QLineEdit(url)
        form_layout.addRow("URL:", url_edit)
        
        layout.addLayout(form_layout)
        
        button_box = QHBoxLayout()
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(dialog.accept)
        button_box.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_box.addWidget(cancel_btn)
        
        layout.addLayout(button_box)
        
        if dialog.exec():
            # Update bookmark in database
            new_title = title_edit.text()
            new_url = url_edit.text()
            
            # In a real implementation, you would update the bookmark in the database
            # For now, we'll delete and re-add
            self.bookmark_manager.delete_bookmark(bookmark_id)
            self.bookmark_manager.add_bookmark(new_title, new_url)
            
            # Refresh list
            self.load_bookmarks()
            
    def create_new_folder(self):
        # In a real implementation, this would create a new folder
        # For this example, we'll just show a placeholder
        folder_name, ok = QInputDialog.getText(self, "New Folder", "Enter folder name:")
        
        if ok and folder_name:
            self.folder_list.addItem(folder_name)
            
    def import_bookmarks(self):
        # In a real implementation, this would import bookmarks from an HTML file
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Bookmarks", "", "HTML Files (*.html)")
        
        if file_path:
            # Placeholder for import functionality
            pass
            
    def export_bookmarks(self):
        # In a real implementation, this would export bookmarks to an HTML file
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Bookmarks", "", "HTML Files (*.html)")
        
        if file_path:
            # Placeholder for export functionality
            pass 