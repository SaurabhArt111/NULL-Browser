"""Chrome-style permission prompt anchored to the top-left of the page."""
import logging
from urllib.parse import urlsplit

from PyQt6.QtWidgets import (QFrame, QLabel, QPushButton, QVBoxLayout)

from ..core import crash
from ..core.permissions import BY_ID, PROMPT_VERBS
from .tips import tip

log = logging.getLogger("null.tab")


class PermissionBubble(QFrame):
    """Chrome-style permission prompt anchored to the top-left of the page."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.setObjectName("bubble")
        self.queue, self.current = [], None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.sub = QLabel()
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet("color: gray; font-size: 12px;")
        self.btn_allow = QPushButton("Allow while visiting the site")
        self.btn_once = QPushButton("Allow this time")
        self.btn_deny = QPushButton("Don't allow")
        tip(self.btn_allow, "Allow while visiting", "Remember this choice for the site")
        tip(self.btn_once, "Allow this time", "Only for this visit; you will be asked again next time")
        tip(self.btn_deny, "Don't allow", "Block this request and remember the choice")
        self.btn_allow.setObjectName("primary")
        for w in (self.title, self.sub, self.btn_allow, self.btn_once, self.btn_deny):
            lay.addWidget(w)
        self.setFixedWidth(330)
        self.btn_allow.clicked.connect(lambda: self.decide("allow"))
        self.btn_once.clicked.connect(lambda: self.decide("once"))
        self.btn_deny.clicked.connect(lambda: self.decide("block"))

    def request(self, origin, ask_feats, all_feats, perm):
        self.queue.append((origin, ask_feats, all_feats, perm))
        if self.current is None:
            self._next()

    def _next(self):
        if not self.queue:
            self.current = None
            self.hide()
            return
        self.current = self.queue.pop(0)
        origin, _ask, allf, _perm = self.current
        verbs = " and ".join(PROMPT_VERBS.get(f, "use " + BY_ID[f]["label"].lower()) for f in allf)
        self.title.setText(f"{urlsplit(origin).hostname or origin} wants to {verbs}")
        self.sub.setText("In a private window the decision is forgotten when all private windows close." if self.tab.private
                         else "Your decision is remembered for this site. Change it any time from the icon left of the address.")
        self.adjustSize()
        self.show()
        self.raise_()
        self.tab._place_overlays()

    def decide(self, choice):
        if self.current is None:
            return
        origin, _ask, allf, perm = self.current
        try:
            if choice == "block":
                for f in allf:
                    self.tab.app.perms.set_site(origin, f, "block", self.tab.private)
                perm.deny()
            else:
                if choice == "allow":
                    for f in allf:
                        self.tab.app.perms.set_site(origin, f, "allow", self.tab.private)
                perm.grant()
        except Exception:
            crash.log.exception("permission decision")
        self.tab.securityChanged.emit()
        self._next()
