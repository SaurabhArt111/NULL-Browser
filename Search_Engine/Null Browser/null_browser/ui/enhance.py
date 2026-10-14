"""Switch for the optional window / animation enhancements.

`main.py` turns this off for a start-up that follows a failed start (a crash before the window finished opening), so a
problem in one of the enhancements can never leave the browser unable to open. Delete `enhancements.off` in the data
folder, or start with `--enhanced`, to turn them back on.
"""
ENABLED = True
NATIVE_FRAME = True            # `--no-native-frame` turns off only the Windows native-frame part
AUTO_DISABLED = False          # True when this start switched them off because the previous start failed
