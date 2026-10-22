"""Can this Python load the Qt parts Null Browser needs? Exit code 0 = yes.  Run: python tools/qt_check.py

When Windows blocks a Qt file (Smart App Control, WDAC, AppLocker, Defender) this also lists the newest block events from the Windows
event logs, which name the exact file and policy."""
import subprocess
import sys

MODULES = ("PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebChannel")


def check():
    bad = None
    for name in MODULES:
        try:
            __import__(name)
        except Exception as e:                      # ImportError for a missing / blocked DLL; anything else is just as fatal here
            bad = (name, e)
            break
    return bad


def blocked_events():
    """Newest code-integrity / AppLocker block events (Windows only; empty elsewhere or without permission)."""
    if not sys.platform.startswith("win"):
        return ""
    ps = (
        "$e=@(); "
        "try{$e+=Get-WinEvent -LogName 'Microsoft-Windows-CodeIntegrity/Operational' -MaxEvents 60 -ErrorAction Stop | "
        "Where-Object {$_.Id -in 3033,3034,3076,3077,3089}}catch{}; "
        "try{$e+=Get-WinEvent -LogName 'Microsoft-Windows-AppLocker/EXE and DLL' -MaxEvents 60 -ErrorAction Stop | "
        "Where-Object {$_.Id -in 8003,8004}}catch{}; "
        "$e | Sort-Object TimeCreated -Descending | Select-Object -First 6 | ForEach-Object {'[{0}] id {1}: {2}' -f $_.TimeCreated,$_.Id,($_.Message -replace '\\s+',' ')}"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=40).stdout.decode("utf-8", "replace")
        return out.strip()
    except Exception:
        return ""


def main():
    import platform
    print(f"Python {platform.python_version()} on {platform.platform()}")
    try:
        import importlib.metadata as md
        for pkg in ("PyQt6", "PyQt6-Qt6", "PyQt6-WebEngine", "PyQt6-WebEngine-Qt6"):
            try:
                print(f"  {pkg} {md.version(pkg)}")
            except md.PackageNotFoundError:
                print(f"  {pkg} NOT INSTALLED")
    except Exception:
        pass
    bad = check()
    if bad is None:
        print("OK: Qt loads.")
        return 0
    print(f"FAILED importing {bad[0]}: {bad[1]}")
    ev = blocked_events()
    if ev:
        print("\nNewest Windows block events (the file named here is the one that was refused):")
        print(ev)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
