from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                           QPushButton, QSplitter, QWidget, QLineEdit, QListWidgetItem, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, pyqtSignal
import os
import sqlite3
import datetime

class HistoryManager:
    def __init__(self, parent=None):
        self.parent = parent
        self.db_path = os.path.expanduser("~/.null_browser/history.db")
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Initialize database
        self.init_db()
        
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY,
            title TEXT,
            url TEXT,
            visit_date TEXT
        )
        ''')
        conn.commit()
        conn.close()
        
    def add_visit(self, title, url):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO history (title, url, visit_date) VALUES (?, ?, ?)",
                      (title, url, current_date))
        conn.commit()
        conn.close()
        
    def get_history(self, limit=100):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, url, visit_date FROM history ORDER BY visit_date DESC LIMIT ?", (limit,))
        history = cursor.fetchall()
        conn.close()
        return history
        
    def clear_history(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history")
        conn.commit()
        conn.close()
        if self.parent:
            self.parent.statusBar().showMessage("History cleared", 3000)

class HistoryDialog(QDialog):
    url_selected = pyqtSignal(str)
    
    def __init__(self, history_manager, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager
        self.setWindowTitle("History")
        self.setMinimumSize(800, 500)
        
        layout = QVBoxLayout(self)
        
        # Header with search and controls
        header_layout = QHBoxLayout()
        
        title_label = QLabel("History")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search history...")
        self.search_edit.textChanged.connect(self.filter_history)
        self.search_edit.setClearButtonEnabled(True)
        header_layout.addWidget(self.search_edit)
        
        clear_btn = QPushButton("Clear History")
        clear_btn.clicked.connect(self.clear_history)
        header_layout.addWidget(clear_btn)
        
        layout.addLayout(header_layout)
        
        # Splitter for time periods and history items
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Time periods panel
        time_widget = QWidget()
        time_layout = QVBoxLayout(time_widget)
        time_layout.setContentsMargins(0, 0, 0, 0)
        
        time_label = QLabel("Time Range")
        time_label.setStyleSheet("font-weight: bold;")
        time_layout.addWidget(time_label)
        
        self.time_list = QListWidget()
        self.time_list.addItem("Today")
        self.time_list.addItem("Yesterday")
        self.time_list.addItem("Last 7 Days")
        self.time_list.addItem("Last 30 Days")
        self.time_list.addItem("All History")
        self.time_list.setCurrentRow(0)
        self.time_list.currentRowChanged.connect(self.time_period_changed)
        time_layout.addWidget(self.time_list)
        
        splitter.addWidget(time_widget)
        
        # History items
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(0, 0, 0, 0)
        
        # History list header
        header_widget = QWidget()
        header_widget.setStyleSheet("background-color: #f0f0f0; border-bottom: 1px solid #ccc;")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(10)
        
        title_header = QLabel("Title")
        title_header.setStyleSheet("font-weight: bold;")
        title_header.setMinimumWidth(200)
        title_header.setMaximumWidth(300)
        
        url_header = QLabel("URL")
        url_header.setStyleSheet("font-weight: bold;")
        url_header.setMinimumWidth(250)
        
        date_header = QLabel("Visited")
        date_header.setStyleSheet("font-weight: bold;")
        date_header.setMinimumWidth(150)
        date_header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        header_layout.addWidget(title_header, 3)
        header_layout.addWidget(url_header, 4)
        header_layout.addWidget(date_header, 2)
        
        history_layout.addWidget(header_widget)
        
        # History list
        self.history_list = QListWidget()
        self.history_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.history_list.itemDoubleClicked.connect(self.open_url)
        self.history_list.setStyleSheet("""
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #cccccc;
                border-radius: 8px;  /* Rounded corners */
            }
            QListWidget::item { 
                border-bottom: 1px solid #e0e0e0; 
                padding: 8px; 
                margin: 2px 0px;
                border-radius: 5px;  /* Rounded corners for items */
            }
            QListWidget::item:selected { 
                background: #e0e0ff; 
                color: #000000;
            }
            QListWidget::item:hover { 
                background: #f5f5f5; 
            }
        """)
        history_layout.addWidget(self.history_list)
        
        splitter.addWidget(history_widget)
        
        # Set initial sizes
        splitter.setSizes([200, 600])
        
        layout.addWidget(splitter)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        button_layout.addStretch()
        
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self.open_selected_url)
        button_layout.addWidget(self.open_btn)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.delete_selected_history)
        button_layout.addWidget(self.delete_btn)
        
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        button_layout.addWidget(self.close_btn)
        
        layout.addLayout(button_layout)
        
        # Load history
        self.all_history = []
        self.filtered_history = []
        self.load_history()
        
    def load_history(self):
        self.all_history = self.history_manager.get_history(1000)  # Get up to 1000 items
        self.filtered_history = self.all_history.copy()
        self.refresh_history_list()
        
    def refresh_history_list(self):
        self.history_list.clear()
        
        for history_id, title, url, visit_date in self.filtered_history:
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(8, 8, 8, 8)
            item_layout.setSpacing(10)
            
            # Checkbox for selection
            checkbox = QCheckBox()
            item_layout.addWidget(checkbox)

            # Title - limit length and use elision
            title_text = title if title else "Untitled"
            if len(title_text) > 30:
                title_text = title_text[:27] + "..."
            title_label = QLabel(title_text)
            title_label.setStyleSheet("font-weight: bold;")
            title_label.setToolTip(title)
            title_label.setMinimumWidth(200)
            title_label.setMaximumWidth(300)
            item_layout.addWidget(title_label, 3)
            
            # URL - limit length and use elision
            url_text = url if url else ""
            if len(url_text) > 40:
                url_text = url_text[:37] + "..."
            url_label = QLabel(url_text)
            url_label.setToolTip(url)
            url_label.setStyleSheet("color: #006621;")
            url_label.setMinimumWidth(250)
            item_layout.addWidget(url_label, 4)
            
            # Visit date
            date_label = QLabel(visit_date)
            date_label.setStyleSheet("color: #666;")
            date_label.setMinimumWidth(150)
            date_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_layout.addWidget(date_label, 2)
            
            # Create list item
            list_item = QListWidgetItem(self.history_list)
            list_item.setData(Qt.ItemDataRole.UserRole, url)
            
            # Set a fixed height for consistency
            item_widget.setMinimumHeight(40)
            list_item.setSizeHint(item_widget.sizeHint())
            
            self.history_list.setItemWidget(list_item, item_widget)
            
    def filter_history(self):
        search_text = self.search_edit.text().lower()
        
        if search_text:
            self.filtered_history = [
                item for item in self.all_history 
                if search_text in item[1].lower() or search_text in item[2].lower()
            ]
        else:
            # Apply time filter
            self.apply_time_filter()
            
        self.refresh_history_list()
        
    def apply_time_filter(self):
        time_period = self.time_list.currentItem().text()
        
        # Current date and time
        now = datetime.datetime.now()
        
        # Filter based on selected time period
        if time_period == "Today":
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            self.filtered_history = [
                item for item in self.all_history 
                if datetime.datetime.strptime(item[3], "%Y-%m-%d %H:%M:%S") >= today
            ]
        elif time_period == "Yesterday":
            yesterday = now.replace(hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            self.filtered_history = [
                item for item in self.all_history 
                if yesterday <= datetime.datetime.strptime(item[3], "%Y-%m-%d %H:%M:%S") < today
            ]
        elif time_period == "Last 7 Days":
            week_ago = now - datetime.timedelta(days=7)
            self.filtered_history = [
                item for item in self.all_history 
                if datetime.datetime.strptime(item[3], "%Y-%m-%d %H:%M:%S") >= week_ago
            ]
        elif time_period == "Last 30 Days":
            month_ago = now - datetime.timedelta(days=30)
            self.filtered_history = [
                item for item in self.all_history 
                if datetime.datetime.strptime(item[3], "%Y-%m-%d %H:%M:%S") >= month_ago
            ]
        else:  # All History
            self.filtered_history = self.all_history.copy()
            
    def time_period_changed(self, index):
        self.search_edit.clear()  # Clear search when time period changes
        self.apply_time_filter()
        self.refresh_history_list()
            
    def open_url(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            self.url_selected.emit(url)
            self.accept()
            
    def open_selected_url(self):
        selected_items = self.history_list.selectedItems()
        if selected_items:
            url = selected_items[0].data(Qt.ItemDataRole.UserRole)
            if url:
                self.url_selected.emit(url)
                self.accept()
            
    def delete_selected_history(self):
        # Get all selected items
        selected_items = self.history_list.selectedItems()
        if not selected_items:
            return
            
        # Connect to database and delete selected items
        conn = sqlite3.connect(self.history_manager.db_path)
        cursor = conn.cursor()
        
        for item in selected_items:
            url = item.data(Qt.ItemDataRole.UserRole)
            # Find the history item with this URL and delete it
            for history_item in self.all_history:
                if history_item[2] == url:
                    cursor.execute("DELETE FROM history WHERE id=?", (history_item[0],))
                    break
        
        conn.commit()
        conn.close()
        
        # Reload history
        self.load_history()
        
    def clear_history(self):
        # Ask for confirmation
        confirmation = QMessageBox.question(
            self, "Clear History",
            "Are you sure you want to clear all browsing history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirmation == QMessageBox.StandardButton.Yes:
            self.history_manager.clear_history()
            self.load_history() 