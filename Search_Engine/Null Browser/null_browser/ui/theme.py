"""Light / dark / private palettes and the application stylesheet."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPalette

LIGHT = dict(strip="#dde0ec", bar="#ffffff", text="#1c1d26", muted="#6a6d80", field="#eef0f7", field_focus="#ffffff",
             border="#d3d6e4", hover="#e4e6f1", press="#d6d9e8", tab_hover="#eceef6", menu="#ffffff", tip="#22232d",
             tip_text="#ffffff", danger="#d93a4a", ok="#1f9d63", warn="#c98a0b", dark=False)
DARK = dict(strip="#0f1016", bar="#1d1f29", text="#ebecf4", muted="#9a9db3", field="#2a2d3b", field_focus="#14151c",
            border="#363a4f", hover="#2b2e3d", press="#363a4f", tab_hover="#181a23", menu="#222534", tip="#ebecf4",
            tip_text="#14151c", danger="#ff6b7a", ok="#43d28d", warn="#f0b429", dark=True)
PRIVATE = dict(DARK, strip="#1a1030", bar="#2a1d4a", field="#3a2a63", field_focus="#1a1030", border="#4b3a7c",
               hover="#38285f", press="#45337a", tab_hover="#241743", menu="#2a1d4a")


LIGHT["dark"], DARK["dark"], PRIVATE["dark"] = False, True, True


def system_is_dark():
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def resolve(theme, private=False):
    if private:
        return dict(PRIVATE)
    if theme == "dark" or (theme == "system" and system_is_dark()):
        return dict(DARK)
    return dict(LIGHT)


def apply_color_scheme(theme):
    """Make native dialogs / title bars follow the chosen theme (Qt 6.8+)."""
    try:
        scheme = {"dark": Qt.ColorScheme.Dark, "light": Qt.ColorScheme.Light}.get(theme, Qt.ColorScheme.Unknown)
        QGuiApplication.styleHints().setColorScheme(scheme)
    except Exception:
        pass


def palette(p, accent):
    pal = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "bar"), (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Base, "field"),
                      (QPalette.ColorRole.AlternateBase, "hover"), (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "bar"),
                      (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.ToolTipBase, "tip"),
                      (QPalette.ColorRole.ToolTipText, "tip_text"), (QPalette.ColorRole.PlaceholderText, "muted")):
        pal.setColor(role, QColor(p[key]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(accent))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    return pal


def stylesheet(p, accent):
    a = accent
    return f"""
* {{ font-family: "Segoe UI Variable", "Segoe UI", system-ui, "SF Pro Text", "Noto Sans", sans-serif; font-size: 13px; }}
QMainWindow {{ background: {p['strip']}; color: {p['text']}; }}
QDialog {{ background: {p['bar']}; color: {p['text']}; }}
QWidget#tabstrip {{ background: {p['strip']}; }}
QWidget#toolbar {{ background: {p['bar']}; }}
QWidget#infobars {{ background: {p['bar']}; }}
QWidget#bookmarkbar {{ background: {p['bar']}; border-bottom: 1px solid {p['border']}; }}
QToolButton {{ background: transparent; border: none; border-radius: 16px; padding: 6px; color: {p['text']}; }}
QToolButton:hover {{ background: {p['hover']}; }}
QToolButton:pressed {{ background: {p['press']}; }}
QToolButton:disabled {{ color: {p['muted']}; }}
QToolButton::menu-indicator {{ image: none; }}
QToolButton#newtab {{ border-radius: 13px; padding: 4px; margin: 10px 2px 0 4px; }}
QToolButton#tabsearch {{ border-radius: 12px; padding: 4px; margin: 10px 4px 0 0; }}
QToolButton#wc_min, QToolButton#wc_max, QToolButton#wc_close {{ border-radius: 0; padding: 0; margin: 0; background: transparent; }}
QToolButton#wc_min:hover, QToolButton#wc_max:hover {{ background: {p['hover']}; }}
QToolButton#wc_close:hover {{ background: #e81123; }}
QFrame#drophint {{ background: {a}; border-radius: 1px; }}
QToolButton#bm {{ border-radius: 8px; padding: 4px 8px; font-size: 12px; }}
QToolButton#tabclose, QToolButton#tabaudio {{ border-radius: 9px; padding: 3px; }}
QToolButton#tabclose:hover, QToolButton#tabaudio:hover {{ background: {p['press']}; }}
QToolButton#devtoolsClose {{ border-radius: 6px; padding: 2px 8px; }}
QToolButton#chip {{ border-radius: 12px; padding: 3px 9px 3px 6px; font-size: 12px; background: {p['field']}; }}
QToolButton#chip:hover {{ background: {p['hover']}; }}
QLabel#privatebadge {{ background: {a}; color: white; border-radius: 11px; padding: 3px 12px; font-weight: 600; }}
QLabel {{ color: {p['text']}; background: transparent; }}
QLineEdit#omnibox {{ background: {p['field']}; border: 2px solid transparent; border-radius: 18px; padding: 5px 8px; min-height: 22px; selection-background-color: {a}; color: {p['text']}; font-size: 14px; }}
QLineEdit#omnibox:hover {{ background: {p['hover']}; }}
QLineEdit#omnibox:focus {{ background: {p['field_focus']}; border: 2px solid {a}; }}
QLineEdit {{ background: {p['field']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 8px; color: {p['text']}; selection-background-color: {a}; }}
QLineEdit:focus {{ border: 1px solid {a}; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {p['muted']}; border-top-left-radius: 10px; border-top-right-radius: 10px; margin-top: 7px; height: 33px; padding: 0 8px; }}
QTabBar::tab:selected {{ background: {p['bar']}; color: {p['text']}; }}
QTabBar::tab:hover:!selected {{ background: {p['tab_hover']}; color: {p['text']}; }}
QTabBar QToolButton {{ background: {p['strip']}; border-radius: 4px; }}
QProgressBar#loadbar {{ background: transparent; border: none; max-height: 3px; min-height: 3px; }}
QProgressBar#loadbar::chunk {{ background: {a}; }}
QMenu {{ background: {p['menu']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['hover']}; }}
QMenu::item:disabled {{ color: {p['muted']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QToolTip {{ background: {p['tip']}; color: {p['tip_text']}; border: none; border-radius: 6px; padding: 5px 8px; }}
QPushButton {{ background: {p['field']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 16px; padding: 6px 16px; }}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton:default, QPushButton#primary {{ background: {a}; color: white; border: none; }}
QPushButton#linkbtn {{ background: transparent; border: none; color: {a}; padding: 4px 8px; }}
QFrame#bubble, QFrame#popup {{ background: {p['menu']}; border: 1px solid {p['border']}; border-radius: 14px; }}
QFrame#findbar {{ background: {p['menu']}; border: 1px solid {p['border']}; border-radius: 12px; }}
QFrame#infobar {{ background: {p['field']}; border-bottom: 1px solid {p['border']}; }}
QLabel#hoverstatus {{ background: {p['menu']}; border: 1px solid {p['border']}; border-radius: 4px; padding: 3px 8px; color: {p['text']}; }}
QListWidget#suggest {{ background: {p['menu']}; border: 1px solid {p['border']}; border-radius: 14px; padding: 6px; outline: none; }}
QListWidget#suggest::item {{ padding: 7px 10px; border-radius: 8px; color: {p['text']}; }}
QListWidget#suggest::item:selected {{ background: {a}; color: white; }}
QComboBox {{ background: {p['field']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px 8px; color: {p['text']}; }}
QComboBox QAbstractItemView {{ background: {p['menu']}; color: {p['text']}; selection-background-color: {a}; border: 1px solid {p['border']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }} QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background: {p['border']}; }}
QCheckBox {{ color: {p['text']}; }}
"""
