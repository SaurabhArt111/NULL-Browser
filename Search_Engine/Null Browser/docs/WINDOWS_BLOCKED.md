# "DLL load failed ... An Application Control policy has blocked this file"

```
ImportError: DLL load failed while importing QtWidgets: An Application Control policy has blocked this file.
```

Windows stopped Python from loading a Qt file (`QtWidgets.pyd` / `Qt6Widgets.dll`). The browser's own code never gets to run, so this is not
something a setting inside Null Browser can change. It comes from one of:

| Source | Typical situation |
|---|---|
| **Smart App Control** (Windows 11) | Personal PC. It blocks programs Microsoft has not seen / signed. A newly installed PyQt6 release can be blocked until it is known. |
| **WDAC / AppLocker** | School or work PC. The administrator decides which programs and folders may run. |
| **Defender / another security product** | The file was quarantined as a "threat"; check Windows Security -> Protection history. |

## Find out which one
Event Viewer -> Applications and Services Logs -> Microsoft -> Windows -> **CodeIntegrity -> Operational** (Smart App Control / WDAC) or
**AppLocker**. The newest "blocked" / "would have been blocked" event names the file and the policy.

## Ways out
* **Try `fix_qt_blocked.bat` first.** It installs Qt (PyQt6 6.9.1, then 6.8.1 if needed) into `%LOCALAPPDATA%\NullBrowser` on your user profile, tests that Qt loads, and starts
  the browser; later start it with `run_null_browser.bat`. If Windows still refuses, it prints the file and policy from the event log. It does not
  switch off or work around any security feature; if an administrator's policy blocks Qt, only the administrator can allow it.
  (Null Browser needs PyQt6 6.8 or newer.)
* Managed computer: ask the administrator to allow the Python environment folder that holds PyQt6, or the whole project folder.
* Went wrong after a re-install: go back to the exact PyQt6 versions that worked (`pip list` in the old environment), e.g.
  `pip install PyQt6==X PyQt6-Qt6==X PyQt6-WebEngine==X PyQt6-WebEngine-Qt6==X` (use the version numbers you had).
  `requirements.txt` only says `>=6.7`, so a brand new environment picks the newest release, which can differ from the one that ran before.
* Defender quarantine: restore the file in Protection history and add an exclusion for the environment folder.
* Smart App Control can be switched off in Windows Security -> App & browser control, but on many Windows 11 versions it cannot be turned on
  again without resetting Windows, so consider the options above first.

Nothing in this project's zip contains compiled Qt files; they come from `pip install`, so the block is about the Python packages
in your environment, not about the files in this folder.
