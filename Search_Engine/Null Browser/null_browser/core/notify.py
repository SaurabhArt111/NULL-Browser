"""Native desktop notifications (Windows toast / macOS Notification Center / freedesktop)
and the web Notification API presenter."""
import logging

from PyQt6.QtCore import QTimer

from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QSystemTrayIcon

log = logging.getLogger("null.notify")


class Notifier:
    def __init__(self, tray: QSystemTrayIcon, settings):
        self.tray = tray
        self.settings = settings
        self._callback = None
        self._web = None
        self.tray.messageClicked.connect(self._clicked)
        self._hide = QTimer(singleShot=True, interval=15000)
        self._hide.timeout.connect(self._maybe_hide)

    def _maybe_hide(self):
        if not self.settings.get("background_running"):
            self.tray.hide()

    def available(self):
        return QSystemTrayIcon.isSystemTrayAvailable() and self.tray.supportsMessages()

    def notify(self, title, message, on_click=None, icon=None, force=False):
        if not force and not self.settings.get("desktop_notifications"):
            return False
        try:
            self._callback = on_click
            self._web = None
            self.tray.show()
            self.tray.showMessage(title, message, icon or self.tray.icon(), 8000)
            self._hide.start()
            return True
        except Exception:
            log.exception("notification failed")
            return False

    def _clicked(self):
        try:
            if self._web is not None:
                self._web.click()
            elif self._callback:
                self._callback()
        except Exception:
            log.exception("notification click failed")

    def present_web(self, notification):
        """QWebEngineProfile notification presenter (called on the GUI thread)."""
        if not self.settings.get("desktop_notifications"):
            notification.close()
            return
        try:
            icon = self.tray.icon()
            img = notification.icon()
            if not img.isNull():
                icon = QIcon(QPixmap.fromImage(img))
            origin = notification.origin().host() or ""
            title = notification.title() or origin
            msg = notification.message()
            if origin and origin not in title:
                msg = f"{msg}\n— {origin}" if msg else origin
            notification.show()
            self.tray.show()
            self._web = notification
            self.tray.showMessage(title, msg, icon, 10000)
            self._hide.start()
        except Exception:
            log.exception("web notification failed")
