"""Null Browser start-up diagnostics: runs the browser in several configurations and writes diagnose_report.txt.

Double-click diagnose.bat (or run `python diagnose.py`). Your own profile is never cleared: the full self-test only runs
against throw-away profiles; your real profile is only opened for a few seconds and closed cleanly.
"""
import datetime
import glob
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "main.py")
REPORT = os.path.join(HERE, "diagnose_report.txt")
REAL_DATA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "NullBrowser", "Null Browser")
lines = []


def say(text=""):
    print(text, flush=True)
    lines.append(text)
    try:                                                    # written as we go, so a partial run still leaves a usable report
        with open(REPORT, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def tail(path, n=40):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [l.rstrip() for l in f.readlines()[-n:]]
    except OSError:
        return []


def code_text(rc):
    if rc is None:
        return "still running"
    u = rc & 0xFFFFFFFF
    names = {0xC0000005: "access violation (native crash)", 0xC0000409: "fast-fail / abort (Chromium or Qt CHECK failure)",
             0xC000013A: "closed with Ctrl+C", 0xC0000374: "heap corruption"}
    return f"{rc} (0x{u:08X}{' - ' + names[u] if u in names else ''})" if rc else "0 (clean exit)"


def run(label, args, data_dir, selftest, timeout):
    work = tempfile.mkdtemp(prefix="nulldiag_")
    out_path, err_path = os.path.join(work, "out.txt"), os.path.join(work, "err.txt")
    cmd = [sys.executable, "-X", "faulthandler", MAIN, "--new-instance", "--debug", "--data-dir", data_dir] + args
    if selftest:
        cmd += ["--selftest", os.path.join(work, "shots")]
    else:
        cmd += ["--exit-after", "12"]
    say(f"--- {label}")
    say("    " + " ".join(os.path.basename(c) if c == MAIN else c for c in cmd[3:]))
    t0 = time.time()
    with open(out_path, "w", encoding="utf-8") as fo, open(err_path, "w", encoding="utf-8") as fe:
        p = subprocess.Popen(cmd, stdout=fo, stderr=fe, cwd=HERE)
        try:
            rc = p.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            rc = None
    secs = time.time() - t0
    text = "".join(tail(out_path, 4000)) + "".join(tail(err_path, 4000))
    passed = [l for l in (tail(out_path, 4000) + tail(err_path, 4000)) if "checks passed" in l]
    breadcrumbs = [l for l in (tail(out_path, 4000) + tail(err_path, 4000)) if "null: " in l and any(k in l for k in
                   ("Starting", "enhancements", "Creating", "ready", "Windows opened", "Entering", "Clean shutdown", "Exited"))]
    if timed_out:
        verdict = "HUNG (did not finish in time)"
    elif selftest:
        verdict = "OK" if (rc == 0 and passed) else "FAILED"
    else:
        verdict = "OK" if (rc == 0 and "Windows opened" in "\n".join(breadcrumbs)) else "FAILED"
    say(f"    result: {verdict}   exit code: {code_text(rc)}   time: {secs:.0f}s")
    for l in passed[-1:]:
        say("    " + l.split("null")[-1].strip())
    if verdict != "OK":
        say("    progress reached:")
        for l in breadcrumbs[-8:]:
            say("      " + l[:160])
        say("    last output:")
        for l in (tail(err_path, 25) or tail(out_path, 25))[-25:]:
            say("      " + l[:200])
        crash = os.path.join(data_dir, "logs", "native-crash.log")
        c = tail(crash, 40)
        if c:
            say("    native-crash.log (last lines):")
            for l in c:
                say("      " + l[:200])
    say()
    shutil.rmtree(work, ignore_errors=True)
    return verdict


def tasklist():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
        mine = [l.split('","')[0].strip('"') for l in out.splitlines() if any(k in l.lower() for k in ("python", "qtwebengine", "null"))]
        return mine
    except Exception:
        return []


def main():
    try:
        open(REPORT, "w").close()
    except OSError:
        pass
    say("(Please don't click or type in the test windows while this runs: a stray click can fail a test.)")
    say(f"Null Browser diagnostics  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    say(f"Windows: {platform.platform()}   Python: {sys.version.split()[0]} ({platform.architecture()[0]})   exe: {sys.executable}")
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        say(f"PyQt6 {PYQT_VERSION_STR}   Qt {QT_VERSION_STR}")
    except Exception as e:
        say(f"PyQt6 import FAILED: {e!r}")
    try:
        gpu = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController | Select -Expand Name) -join '; '"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        say(f"Graphics: {gpu}")
    except Exception:
        pass
    procs = tasklist()
    say(f"Related processes already running: {', '.join(procs) if procs else 'none'}")
    if any("qtwebengine" in p.lower() for p in procs):
        say("  !! QtWebEngineProcess.exe is running. Leftover processes from earlier crashes can block start-up: end them in Task Manager and run this again.")
    say(f"Your data folder: {REAL_DATA}  (exists: {os.path.isdir(REAL_DATA)})")
    for name in ("startup-failures.txt", "enhancements.off"):
        say(f"  {name}: {'present' if os.path.exists(os.path.join(REAL_DATA, name)) else 'absent'}")
    say()

    results = {}
    fresh = lambda: tempfile.mkdtemp(prefix="nulldiag_profile_")
    results["A  classic (original behaviour), fresh profile, full self-test"] = run("A: classic, fresh profile, full self-test", ["--classic"], fresh(), True, 420)
    results["B  new effects ON, fresh profile, full self-test"] = run("B: new effects ON, fresh profile, full self-test", ["--enhanced"], fresh(), True, 420)
    results["C  new effects ON but no native frame, fresh profile"] = run("C: new effects ON without native frame, fresh profile", ["--enhanced", "--no-native-frame"], fresh(), True, 420)

    # your real profile: open for ~12 seconds, close cleanly; restore the marker files afterwards
    saved = {}
    for name in ("startup-failures.txt", "enhancements.off"):
        p = os.path.join(REAL_DATA, name)
        saved[name] = open(p, "rb").read() if os.path.exists(p) else None
    results["D  classic, YOUR profile (opened ~12 s)"] = run("D: classic, your own profile", ["--classic"], REAL_DATA, False, 90)
    results["E  new effects ON, YOUR profile (opened ~12 s)"] = run("E: new effects ON, your own profile", ["--enhanced"], REAL_DATA, False, 90)
    for name, data in saved.items():
        p = os.path.join(REAL_DATA, name)
        try:
            if data is None:
                os.path.exists(p) and os.remove(p)
            else:
                open(p, "wb").write(data)
        except OSError:
            pass

    say("=" * 70)
    say("SUMMARY")
    for k, v in results.items():
        say(f"  {v:<34} {k}")
    say()
    a, d = results.get("A  classic (original behaviour), fresh profile, full self-test"), results.get("D  classic, YOUR profile (opened ~12 s)")
    if a != "OK":
        say("Even the classic build fails on a clean profile -> the problem is the installation / machine (PyQt, graphics driver, leftover processes), not your profile.")
    elif d != "OK":
        say("Classic works on a clean profile but not on yours -> your profile folder is the problem. Rename it and start again:")
        say(f"    {REAL_DATA}")
    else:
        say("Classic mode works. If B / C / E failed, the new window effects are the problem (see the details above).")
    print(f"\nReport saved to: {REPORT}\nSend me the contents of that file.")


if __name__ == "__main__":
    main()
