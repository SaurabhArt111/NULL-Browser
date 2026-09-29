import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings
import os

# Ensure the current directory is in the path so imports work correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)  # Get the parent directory (Null Browser)
if current_dir not in sys.path:
    sys.path.append(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Import our components
from ui.main_window import MainWindow
from ui.managers.theme_manager import ThemeManager

def main():
    # Create QApplication instance
    app = QApplication(sys.argv)
    app.setApplicationName("Null Browser")
    app.setApplicationVersion("2.0")
    
    # Apply system style
    app.setStyle("Fusion")
    
    # Check for private browsing mode
    private_mode = "--private" in sys.argv

    # Create main window
    try:
        window = MainWindow(private_mode=private_mode)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error creating main window: {e}")
        sys.exit(1)  # Exit the application if the window cannot be created

    # Apply theme
    try:
        settings = QSettings("NullBrowser", "Preferences")
        theme_name = settings.value("theme", "Light")
        theme_manager = ThemeManager(window)
        theme_manager.apply_theme(theme_name)
    except Exception as e:
        print(f"Could not apply theme, using default styling: {e}")

    # Show the window
    window.show()

    # Start event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 