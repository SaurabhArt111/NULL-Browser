"""The "Install app" confirmation (name, icon, shortcuts)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout


class InstallDialog(QDialog):
    def __init__(self, window, manifest, pixmap):
        super().__init__(window)
        self.setWindowTitle("Install app")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.setSpacing(12)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        top.addWidget(icon)
        col = QVBoxLayout()
        self.edit = QLineEdit(manifest["name"])
        self.edit.setMaxLength(60)
        col.addWidget(self.edit)
        host = manifest["start_url"].split("/")[2] if manifest["start_url"].count("/") >= 2 else manifest["start_url"]
        sub = QLabel(host)
        sub.setStyleSheet("color: gray;")
        col.addWidget(sub)
        top.addLayout(col, 1)
        v.addLayout(top)
        note = QLabel("The app opens in its own window with its own sign-ins and data. Clearing your browsing data does not touch it.")
        note.setWordWrap(True)
        v.addWidget(note)
        self.desktop = QCheckBox("Add a shortcut to the desktop")
        self.desktop.setChecked(True)
        self.menu = QCheckBox("Add to the Start menu / app launcher")
        self.menu.setChecked(True)
        self.auto = QCheckBox("Keep the app up to date automatically")
        self.auto.setChecked(True)
        for c in (self.desktop, self.menu, self.auto):
            v.addWidget(c)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        install = bb.addButton("Install", QDialogButtonBox.ButtonRole.AcceptRole)
        install.setDefault(True)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def name(self):
        return self.edit.text().strip() or None

    def want_desktop(self):
        return self.desktop.isChecked()

    def want_menu(self):
        return self.menu.isChecked()

    def auto_update(self):
        return self.auto.isChecked()
