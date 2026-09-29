from PyQt6.QtCore import QSettings, QPropertyAnimation, QEasingCurve
import traceback

try:
    from PyQt6.QtWidgets import QGraphicsOpacityEffect
except ImportError:  # pragma: no cover - defensive, PyQt6 always has this
    QGraphicsOpacityEffect = None


class ThemeManager:
    """Applies a colour theme to the whole browser chrome (toolbar, tabs,
    bookmark bar, menus, dialogs, status bar) via a single QSS stylesheet.

    Ships with a handful of built-in themes similar to what Chrome/Brave/Edge
    offer out of the box, plus a "Custom" theme driven by a user-chosen
    accent colour (see set_custom_accent)."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.themes = {
            "Light": {
                "background": "#FFFFFF", "surface": "#F1F3F4", "text": "#202124",
                "links": "#1A73E8", "accent": "#E8EAED", "border": "#DADCE0",
                "highlight": "#1A73E8",
            },
            "Dark": {
                "background": "#202124", "surface": "#303134", "text": "#E8EAED",
                "links": "#8AB4F8", "accent": "#3C4043", "border": "#5F6368",
                "highlight": "#8AB4F8",
            },
            "Night": {
                "background": "#0F1115", "surface": "#181A20", "text": "#D7DCE3",
                "links": "#5FB3FF", "accent": "#22252C", "border": "#2A2E38",
                "highlight": "#5FB3FF",
            },
            "Brave": {  # warm dark theme reminiscent of Brave's default palette
                "background": "#1A1625", "surface": "#231B33", "text": "#F0EEF7",
                "links": "#FF7A59", "accent": "#332845", "border": "#3D3153",
                "highlight": "#FF5000",
            },
            "Ocean": {
                "background": "#0B1E30", "surface": "#123049", "text": "#E5F1FA",
                "links": "#43C6FF", "accent": "#173D5C", "border": "#1F4B70",
                "highlight": "#43C6FF",
            },
        }

    # -- custom accent (user-chosen colour) --------------------------------
    def set_custom_accent(self, hex_color):
        settings = QSettings("NullBrowser", "Preferences")
        settings.setValue("custom_accent", hex_color)
        self.themes["Custom"] = dict(self.themes["Light"])
        self.themes["Custom"]["links"] = hex_color
        self.themes["Custom"]["highlight"] = hex_color

    def apply_theme(self, theme_name):
        try:
            if theme_name == "Custom":
                settings = QSettings("NullBrowser", "Preferences")
                accent = settings.value("custom_accent", "#1A73E8")
                self.set_custom_accent(accent)
            if theme_name not in self.themes:
                theme_name = "Light"

            theme = self.themes[theme_name]
            self._fade_and_apply(self._build_stylesheet(theme))

            # Store theme preference
            settings = QSettings("NullBrowser", "Preferences")
            settings.setValue("theme", theme_name)

            if self.main_window is not None:
                try:
                    self.main_window.statusBar().showMessage(f"Theme changed to {theme_name}", 3000)
                except Exception:
                    pass
        except Exception:
            traceback.print_exc()

    def _fade_and_apply(self, stylesheet):
        """Applies the stylesheet with a short opacity fade so theme changes
        feel smoother than an instant colour swap (Qt Widgets has no native
        CSS transitions, so this is approximated with QPropertyAnimation)."""
        if self.main_window is None:
            return
        central = self.main_window.centralWidget() if hasattr(self.main_window, "centralWidget") else None
        if central is None or QGraphicsOpacityEffect is None:
            self.main_window.setStyleSheet(stylesheet)
            return
        try:
            effect = QGraphicsOpacityEffect(central)
            central.setGraphicsEffect(effect)
            fade_out = QPropertyAnimation(effect, b"opacity", central)
            fade_out.setDuration(90)
            fade_out.setStartValue(1.0)
            fade_out.setEndValue(0.55)
            fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

            def apply_and_fade_in():
                self.main_window.setStyleSheet(stylesheet)
                fade_in = QPropertyAnimation(effect, b"opacity", central)
                fade_in.setDuration(140)
                fade_in.setStartValue(0.55)
                fade_in.setEndValue(1.0)
                fade_in.setEasingCurve(QEasingCurve.Type.InCubic)
                fade_in.finished.connect(lambda: central.setGraphicsEffect(None))
                fade_in.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
                self._fade_in_anim = fade_in

            fade_out.finished.connect(apply_and_fade_in)
            fade_out.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
            self._fade_out_anim = fade_out
        except Exception:
            traceback.print_exc()
            self.main_window.setStyleSheet(stylesheet)

    def _build_stylesheet(self, theme):
        return f"""
        QMainWindow, QDialog {{
            background-color: {theme['background']};
            color: {theme['text']};
        }}

        QWidget {{
            color: {theme['text']};
        }}

        QTabWidget::pane {{
            border: none;
            background-color: {theme['background']};
        }}

        QTabBar::tab {{
            background-color: {theme['surface']};
            color: {theme['text']};
            padding: 7px 14px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}

        QTabBar::tab:selected {{
            background-color: {theme['background']};
            border: 1px solid {theme['border']};
            border-bottom: none;
        }}

        QTabBar::tab:hover {{
            background-color: {theme['accent']};
        }}

        QLineEdit {{
            background-color: {theme['surface']};
            color: {theme['text']};
            border: 1px solid {theme['border']};
            padding: 6px 10px;
            border-radius: 16px;
            selection-background-color: {theme['highlight']};
        }}

        QLineEdit:focus {{
            border: 1px solid {theme['highlight']};
        }}

        QPushButton {{
            background-color: {theme['accent']};
            color: {theme['text']};
            padding: 6px 12px;
            border: none;
            border-radius: 6px;
        }}

        QPushButton:hover {{
            background-color: {theme['highlight']};
            color: #FFFFFF;
        }}

        QToolButton {{
            background: transparent;
            border-radius: 6px;
            padding: 4px 6px;
        }}

        QToolButton:hover {{
            background-color: {theme['accent']};
        }}

        QToolBar {{
            background-color: {theme['background']};
            border-bottom: 1px solid {theme['border']};
            spacing: 4px;
            padding: 3px;
        }}

        #bookmarkBar {{
            background-color: {theme['surface']};
            border-bottom: 1px solid {theme['border']};
        }}

        #bookmarkBar QPushButton {{
            background: transparent;
            border-radius: 4px;
            padding: 3px 8px;
            color: {theme['text']};
        }}

        #bookmarkBar QPushButton:hover {{
            background-color: {theme['accent']};
        }}

        QStatusBar {{
            background-color: {theme['background']};
            color: {theme['text']};
            border-top: 1px solid {theme['border']};
        }}

        QMenuBar {{
            background-color: {theme['background']};
            color: {theme['text']};
        }}

        QMenuBar::item:selected {{
            background-color: {theme['accent']};
        }}

        QMenu {{
            background-color: {theme['surface']};
            color: {theme['text']};
            border: 1px solid {theme['border']};
        }}

        QMenu::item:selected {{
            background-color: {theme['highlight']};
            color: #FFFFFF;
        }}

        QComboBox {{
            background-color: {theme['surface']};
            color: {theme['text']};
            border: 1px solid {theme['border']};
            padding: 5px;
            border-radius: 6px;
        }}

        QListWidget, QTreeWidget {{
            background-color: {theme['background']};
            color: {theme['text']};
            border: 1px solid {theme['border']};
        }}

        QProgressBar {{
            background-color: {theme['surface']};
            border: none;
            height: 3px;
        }}

        QProgressBar::chunk {{
            background-color: {theme['highlight']};
        }}
        """
