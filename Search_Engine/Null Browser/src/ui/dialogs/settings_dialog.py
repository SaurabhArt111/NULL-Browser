from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, 
                           QWidget, QLabel, QLineEdit, QComboBox, QPushButton,
                           QGridLayout, QCheckBox, QFileDialog, QFormLayout,
                           QMessageBox)
from PyQt6.QtCore import QSettings
import os
import sys
import traceback

from ui.managers.theme_manager import ThemeManager

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(560, 460)
        
        layout = QVBoxLayout(self)
        
        # Create tabs for different settings categories
        self.tabs_widget = QTabWidget()
        tabs = self.tabs_widget
        
        # General settings tab
        general_tab = QWidget()
        general_layout = QGridLayout(general_tab)
        
        # Home page setting
        general_layout.addWidget(QLabel("Home Page:"), 0, 0)
        home_row = QHBoxLayout()
        self.home_page_edit = QLineEdit(self.get_home_page())
        self.home_page_edit.setPlaceholderText("newtab (or a URL, e.g. https://example.com)")
        home_row.addWidget(self.home_page_edit)
        general_layout.addLayout(home_row, 0, 1)
        
        # Default search engine
        general_layout.addWidget(QLabel("Default Search Engine:"), 1, 0)
        self.search_engine_combo = QComboBox()
        self.search_engine_combo.addItems(["Null Search", "Google", "Bing", "DuckDuckGo"])
        self.search_engine_combo.setCurrentIndex(self.get_search_engine_index())
        general_layout.addWidget(self.search_engine_combo, 1, 1)
        
        # Theme
        general_layout.addWidget(QLabel("Theme:"), 2, 0)
        theme_row = QHBoxLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Light", "Dark", "Night", "Brave", "Ocean", "Custom"])
        theme_index = self.get_theme_index()
        if theme_index >= 0:
            self.theme_combo.setCurrentIndex(theme_index)
        theme_row.addWidget(self.theme_combo)
        self.custom_color_btn = QPushButton("Pick accent color...")
        self.custom_color_btn.clicked.connect(self.pick_custom_accent)
        theme_row.addWidget(self.custom_color_btn)
        general_layout.addLayout(theme_row, 2, 1)
        
        # Downloads directory
        general_layout.addWidget(QLabel("Downloads Location:"), 3, 0)
        downloads_layout = QHBoxLayout()
        self.downloads_edit = QLineEdit(self.get_downloads_location())
        downloads_layout.addWidget(self.downloads_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_downloads_location)
        downloads_layout.addWidget(browse_btn)
        general_layout.addLayout(downloads_layout, 3, 1)
        
        # Startup setting
        general_layout.addWidget(QLabel("On Startup:"), 4, 0)
        self.startup_combo = QComboBox()
        self.startup_combo.addItems(["Open Home Page", "Open New Tab Page", "Continue where you left off"])
        self.startup_combo.setCurrentIndex(self.get_startup_option())
        general_layout.addWidget(self.startup_combo, 4, 1)
        
        # Tabs settings tab
        tabs_tab = QWidget()
        tabs_layout = QGridLayout(tabs_tab)
        
        # New tab behavior
        tabs_layout.addWidget(QLabel("When opening a new tab:"), 0, 0)
        self.new_tab_combo = QComboBox()
        self.new_tab_combo.addItems(["Open Home Page", "Open New Tab Page", "Open Blank Page"])
        self.new_tab_combo.setCurrentIndex(self.get_new_tab_option())
        tabs_layout.addWidget(self.new_tab_combo, 0, 1)
        
        # Privacy settings tab
        privacy_tab = QWidget()
        privacy_layout = QGridLayout(privacy_tab)
        
        # Cookie settings
        privacy_layout.addWidget(QLabel("Cookie Policy:"), 0, 0)
        self.cookie_combo = QComboBox()
        self.cookie_combo.addItems(["Accept all cookies", "Block third-party cookies", "Block all cookies"])
        self.cookie_combo.setCurrentIndex(self.get_cookie_policy())
        privacy_layout.addWidget(self.cookie_combo, 0, 1)
        
        # Do Not Track
        privacy_layout.addWidget(QLabel("Send 'Do Not Track' requests:"), 1, 0)
        self.dnt_combo = QComboBox()
        self.dnt_combo.addItems(["Yes", "No"])
        self.dnt_combo.setCurrentIndex(self.get_do_not_track())
        privacy_layout.addWidget(self.dnt_combo, 1, 1)

        # Ad & tracker blocker (Brave-style shields)
        self.adblock_checkbox = QCheckBox("Block ads and trackers")
        self.adblock_checkbox.setChecked(
            QSettings("NullBrowser", "Preferences").value("adblock_enabled", True, type=bool))
        privacy_layout.addWidget(self.adblock_checkbox, 2, 0, 1, 2)

        # Popup blocker
        self.popup_checkbox = QCheckBox("Block pop-up windows")
        self.popup_checkbox.setChecked(
            QSettings("NullBrowser", "Preferences").value("block_popups", True, type=bool))
        privacy_layout.addWidget(self.popup_checkbox, 3, 0, 1, 2)

        # Ask where to save each download
        self.ask_download_checkbox = QCheckBox("Ask where to save each file before downloading")
        self.ask_download_checkbox.setChecked(
            QSettings("NullBrowser", "Preferences").value("ask_download_location", True, type=bool))
        privacy_layout.addWidget(self.ask_download_checkbox, 4, 0, 1, 2)
        
        # Clear browsing data button
        clear_data_btn = QPushButton("Clear Browsing Data...")
        clear_data_btn.clicked.connect(self.show_clear_data_dialog)
        privacy_layout.addWidget(clear_data_btn, 5, 0, 1, 2)
        
        # Add tabs to tab widget
        tabs.addTab(general_tab, "General")
        tabs.addTab(tabs_tab, "Tabs")
        self._privacy_tab_index = tabs.addTab(privacy_tab, "Privacy && Security")
        
        layout.addWidget(tabs)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset_settings)
        button_layout.addWidget(reset_btn)
        
        layout.addLayout(button_layout)
        
    def show_privacy_tab(self):
        self.tabs_widget.setCurrentIndex(self._privacy_tab_index)

    def get_home_page(self):
        settings = QSettings("NullBrowser", "Preferences")
        return settings.value("home_page", "newtab")
        
    def get_search_engine_index(self):
        settings = QSettings("NullBrowser", "Preferences")
        index = settings.value("search_engine", 0)
        if isinstance(index, str):
            try:
                index = int(index)
            except:
                index = 0
        return index
        
    def get_theme_index(self):
        settings = QSettings("NullBrowser", "Preferences")
        theme = settings.value("theme", "Light")
        themes = ["Light", "Dark", "Night", "Brave", "Ocean", "Custom"]
        if theme in themes:
            return themes.index(theme)
        return 0  # Default to Light

    def pick_custom_accent(self):
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor
        settings = QSettings("NullBrowser", "Preferences")
        current = settings.value("custom_accent", "#1A73E8")
        color = QColorDialog.getColor(QColor(current), self, "Pick accent color")
        if color.isValid():
            settings.setValue("custom_accent", color.name())
            self.theme_combo.setCurrentText("Custom")
        
    def get_downloads_location(self):
        settings = QSettings("NullBrowser", "Preferences")
        return settings.value("downloads_location", os.path.expanduser("~/Downloads"))
        
    def get_startup_option(self):
        settings = QSettings("NullBrowser", "Preferences")
        option = settings.value("startup_option", 0)
        if isinstance(option, str):
            try:
                option = int(option)
            except:
                option = 0
        return option
        
    def get_new_tab_option(self):
        settings = QSettings("NullBrowser", "Preferences")
        option = settings.value("new_tab_option", 0)
        if isinstance(option, str):
            try:
                option = int(option)
            except:
                option = 0
        return option
        
    def get_cookie_policy(self):
        settings = QSettings("NullBrowser", "Preferences")
        policy = settings.value("cookie_policy", 0)
        if isinstance(policy, str):
            try:
                policy = int(policy)
            except:
                policy = 0
        return policy
        
    def get_do_not_track(self):
        settings = QSettings("NullBrowser", "Preferences")
        option = settings.value("do_not_track", 1)
        if isinstance(option, str):
            try:
                option = int(option)
            except:
                option = 1
        return option
        
    def browse_downloads_location(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Downloads Folder", self.downloads_edit.text())
        if folder:
            self.downloads_edit.setText(folder)
            
    def show_clear_data_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Clear Browsing Data")
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("Select items to clear:"))
        
        checkboxes = []
        
        browsing_history = QCheckBox("Browsing History")
        browsing_history.setChecked(True)
        layout.addWidget(browsing_history)
        checkboxes.append(browsing_history)
        
        cookies = QCheckBox("Cookies and Site Data")
        layout.addWidget(cookies)
        checkboxes.append(cookies)
        
        cache = QCheckBox("Cached Images and Files")
        layout.addWidget(cache)
        checkboxes.append(cache)
        
        passwords = QCheckBox("Saved Passwords")
        layout.addWidget(passwords)
        checkboxes.append(passwords)
        
        autofill = QCheckBox("Autofill Form Data")
        layout.addWidget(autofill)
        checkboxes.append(autofill)
        
        layout.addWidget(QLabel("Time range:"))
        
        time_range = QComboBox()
        time_range.addItems(["Last hour", "Last day", "Last week", "Last month", "All time"])
        time_range.setCurrentIndex(4)  # All time
        layout.addWidget(time_range)
        
        button_layout = QHBoxLayout()
        
        clear_btn = QPushButton("Clear Data")
        clear_btn.clicked.connect(lambda: self.clear_browsing_data(dialog, checkboxes, time_range.currentText()))
        button_layout.addWidget(clear_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        dialog.exec()
        
    def clear_browsing_data(self, dialog, checkboxes, time_range):
        items_to_clear = [cb.text() for cb in checkboxes if cb.isChecked()]
        main_window = self.parent()

        try:
            if main_window is not None and hasattr(main_window, "clear_browsing_data"):
                main_window.clear_browsing_data(
                    cache=("Cached Images and Files" in items_to_clear),
                    cookies=("Cookies and Site Data" in items_to_clear),
                    history=("Browsing History" in items_to_clear),
                )
            elif "Browsing History" in items_to_clear and hasattr(main_window, "history_manager"):
                main_window.history_manager.clear_history()

            if "Saved Passwords" in items_to_clear or "Autofill Form Data" in items_to_clear:
                # Not yet implemented: Null Browser has no password/autofill
                # store in this build, so we simply note that to the user
                # rather than silently pretending it was cleared.
                if main_window is not None:
                    main_window.statusBar().showMessage(
                        "Note: saved passwords/autofill aren't stored by Null Browser yet", 4000)

            if main_window is not None:
                main_window.statusBar().showMessage(
                    f"Cleared: {', '.join(items_to_clear) or 'nothing selected'} ({time_range})", 3000)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(self, "Error", f"Could not clear all browsing data: {e}")
        dialog.accept()
        
    def save_settings(self):
        try:
            settings = QSettings("NullBrowser", "Preferences")
            main_window = self.parent()

            # Save home page
            home_page = self.home_page_edit.text().strip() or "newtab"
            settings.setValue("home_page", home_page)

            # Save search engine
            search_engine_index = self.search_engine_combo.currentIndex()
            settings.setValue("search_engine", search_engine_index)
            if main_window is not None and hasattr(main_window, "search_engine"):
                main_window.search_engine.setCurrentIndex(search_engine_index)

            # Save theme (with a smooth cross-fade if the main window supports it)
            theme_name = self.theme_combo.currentText()
            settings.setValue("theme", theme_name)
            try:
                theme_manager = ThemeManager(main_window)
                theme_manager.apply_theme(theme_name)
            except Exception:
                traceback.print_exc()

            # Save downloads location (create it if missing)
            downloads_location = self.downloads_edit.text().strip() or os.path.expanduser("~/Downloads")
            try:
                os.makedirs(downloads_location, exist_ok=True)
            except OSError as e:
                QMessageBox.warning(self, "Downloads folder",
                                     f"Could not create/use that folder: {e}\nKeeping the previous location.")
                downloads_location = self.get_downloads_location()
            settings.setValue("downloads_location", downloads_location)

            # Save startup option
            settings.setValue("startup_option", self.startup_combo.currentIndex())

            # Save new tab option
            settings.setValue("new_tab_option", self.new_tab_combo.currentIndex())

            # Save cookie policy and apply it to the active profile
            cookie_policy = self.cookie_combo.currentIndex()
            settings.setValue("cookie_policy", cookie_policy)
            self._apply_cookie_policy(cookie_policy)

            # Save Do Not Track setting
            settings.setValue("do_not_track", self.dnt_combo.currentIndex())

            # Ad-block / popup blocker / download prompt
            settings.setValue("adblock_enabled", self.adblock_checkbox.isChecked())
            settings.setValue("block_popups", self.popup_checkbox.isChecked())
            settings.setValue("ask_download_location", self.ask_download_checkbox.isChecked())
            if main_window is not None:
                if hasattr(main_window, "adblocker"):
                    main_window.adblocker.enabled = self.adblock_checkbox.isChecked()
                main_window.block_popups = self.popup_checkbox.isChecked()
                main_window.statusBar().showMessage("Settings saved", 3000)

            self.accept()
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Could not save settings: {e}")

    def _apply_cookie_policy(self, policy_index):
        """0 = accept all, 1 = block third-party, 2 = block all."""
        try:
            from PyQt6.QtWebEngineCore import QWebEngineProfile
            main_window = self.parent()
            profile = getattr(main_window, "web_profile", None) or QWebEngineProfile.defaultProfile()
            if policy_index == 2:
                profile.setPersistentCookiesPolicy(
                    QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
            else:
                profile.setPersistentCookiesPolicy(
                    QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
            # Note: fine-grained same-site/third-party cookie blocking isn't
            # exposed by QtWebEngine's public API; "Block third-party
            # cookies" is best-effort and primarily governs the ad-blocker's
            # tracker rules rather than the cookie jar itself.
        except Exception:
            traceback.print_exc()
        
    def reset_settings(self):
        # Reset to default values
        self.home_page_edit.setText("newtab")
        self.search_engine_combo.setCurrentIndex(0)
        self.theme_combo.setCurrentIndex(0)
        self.downloads_edit.setText(os.path.expanduser("~/Downloads"))
        self.startup_combo.setCurrentIndex(0)
        self.new_tab_combo.setCurrentIndex(0)
        self.cookie_combo.setCurrentIndex(0)
        self.dnt_combo.setCurrentIndex(1)
        self.adblock_checkbox.setChecked(True)
        self.popup_checkbox.setChecked(True)
        self.ask_download_checkbox.setChecked(True) 