# Making NullBrowser.exe

Yes, Null Browser can be turned into an `.exe`. Two ways: `build_exe.bat` (recommended, one double-click) or the
auto-py-to-exe window. Both use PyInstaller; the batch file just has every setting already filled in (`NullBrowser.spec`).

## The easy way

1. Double-click `setup_and_run.bat` in the project folder once (installs Qt, the search server's packages, ffmpeg).
2. Double-click `Search_Engine\Null Browser\build_exe.bat`.
3. Result: `dist\NullBrowser\NullBrowser.exe`. Copy or zip the **whole `NullBrowser` folder**; the .exe needs the files beside it.

What you get: Task Manager and the taskbar say **Null Browser** with the Null icon (one entry instead of "Python"), no console
window, and the search server runs inside the same program (`NullBrowser.exe --run-engine`), so nothing else has to be installed
on the PC you copy it to. Your data stays in `%APPDATA%\NullBrowser`, as before.

## With auto-py-to-exe

Possible, but it has many settings to get right. In its window:

| Setting | Value |
|---|---|
| Script Location | `Search_Engine\Null Browser\main.py` |
| Onefile | **One Directory** (a one-file build unpacks to a temp folder on every start, which is slow and is what antivirus and Windows application control dislike) |
| Console Window | **Window Based (hide the console)** |
| Icon | `Search_Engine\Null Browser\null_browser\assets\icon.ico` |
| Additional Files > Add Folder | `null_browser\web\static` -> `null_browser/web/static`, `null_browser\web\pages` -> `null_browser/web/pages`, `null_browser\data` -> `null_browser/data`, `null_browser\assets` -> `null_browser/assets`, `null_browser\video\shim.js` -> `null_browser/video`, and the folder `Search_Engine\Null Search Engine` -> `Search_Engine/Null Search Engine` |
| Advanced > `--collect-all` | `uvicorn`, `fastapi`, `starlette`, `pydantic`, `pydantic_core`, `anyio`, `httpx`, `httpcore`, `h11`, `jinja2`, `bs4`, `lxml`, `certifi`, `tzdata`, `imageio_ffmpeg` |
| Advanced > `--hidden-import` | `adblock`, `urllib.robotparser`, `zoneinfo`, `sqlite3`, `email.utils`, `colorsys` |
| Advanced > `--noupx` | on |

`NullBrowser.spec` does all of this (and also scans the search server for the modules it imports), which is why `build_exe.bat` is
the safer choice.

## Things to know

* **Windows may block an `.exe` you built yourself.** A new, unsigned program has no reputation. Smart App Control (Windows 11) and
  application-control policies on school / work PCs can refuse it, the same way they refused Qt before. SmartScreen shows
  "Windows protected your PC" first: *More info > Run anyway* works on a normal PC. If a policy blocks it, only a code-signing
  certificate or an administrator's allow-rule fixes that; the batch launchers (`run_browser_only.bat`) are the fallback.
* The build is about 600-700 MB unpacked (Chromium + Qt). That is normal for Qt WebEngine.
* Build on Windows to get a Windows `.exe`; PyInstaller cannot cross-compile.
* Updating the browser means building again.
