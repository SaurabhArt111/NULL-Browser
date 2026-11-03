"""Scripts the browser injects into every web page (all frames). They run in Qt WebEngine's *application* world: they see
the page's DOM but the page cannot see (or tamper with) them or their variables."""
import logging
import os

from PyQt6.QtWebEngineCore import QWebEngineScript

log = logging.getLogger("null.pagescripts")
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js")
AUTOSCROLL = "null-autoscroll"
WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld


def _read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def install(profile, settings):
    """(Re)install the page scripts on a profile according to the settings."""
    coll = profile.scripts()
    for sc in coll.find(AUTOSCROLL):
        coll.remove(sc)
    if settings.get("custom_autoscroll"):
        sc = QWebEngineScript()
        sc.setName(AUTOSCROLL)
        sc.setSourceCode(_read("autoscroll.js"))
        sc.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
        sc.setWorldId(WORLD)
        sc.setRunsOnSubFrames(True)
        coll.insert(sc)
