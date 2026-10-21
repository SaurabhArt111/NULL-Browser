"""Per-tab permission and authentication handling."""
import logging

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QInputDialog, QLabel, QLineEdit, QMessageBox)

from ..core import crash
from ..core.permissions import BY_ID, PROMPT_VERBS, QT_PERMISSION_MAP, origin_of

log = logging.getLogger("null.tab")


class PermissionsMixin:
    """Permission prompts, file-system / screen-share requests and HTTP auth dialogs for a tab."""

    def ask_shim_permission(self, feature, origin_url):
        """Synchronous permission prompt used by the JS API gate (called from javaScriptConfirm)."""
        if feature not in BY_ID:
            return False
        origin = origin_of(self.page.url().toString()) or origin_of(origin_url.toString())
        val = self.app.perms.effective(origin, feature, self.private)
        if val == "allow":
            return True
        if val == "block":
            return False
        box = QMessageBox(self.window())
        box.setWindowTitle("Permission request")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{origin or 'This site'} wants to {PROMPT_VERBS.get(feature, 'use ' + BY_ID[feature]['label'])}")
        allow = box.addButton("Allow", QMessageBox.ButtonRole.AcceptRole)
        once = box.addButton("Allow this time", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Block", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c is allow:
            self.app.perms.set_site(origin, feature, "allow", self.private)
            return True
        if c is once:
            return True
        self.app.perms.set_site(origin, feature, "block", self.private)
        return False

    # ---- permissions ------------------------------------------------------------------------
    def on_permission(self, perm):
        try:
            feats = QT_PERMISSION_MAP.get(perm.permissionType().name)
            if not feats:
                perm.deny()
                return
            origin = origin_of(perm.origin().toString()) or self.current_origin
            vals = [self.app.perms.effective(origin, f, self.private) for f in feats]
            if "block" in vals:
                perm.deny()
            elif all(v == "allow" for v in vals):
                perm.grant()
            else:
                self.bubble.request(origin, [f for f, v in zip(feats, vals) if v != "allow"], feats, perm)
        except Exception:
            crash.log.exception("permission request")
            try:
                perm.deny()
            except Exception:
                pass

    def on_fs_access(self, req):
        origin = origin_of(req.origin().toString()) or self.current_origin
        v = self.app.perms.effective(origin, "file_editing", self.private)
        if v == "block":
            return req.reject()
        if v == "ask":
            r = QMessageBox.question(self.window(), "Edit files?", f"{origin} wants to access files or folders on your device.")
            if r != QMessageBox.StandardButton.Yes:
                return req.reject()
        req.accept()

    def on_desktop_media(self, req):
        origin = origin_of(self.page.url().toString())
        if self.app.perms.effective(origin, "screen_capture", self.private) == "block":
            return req.cancel()
        try:
            model = req.screensModel()
            names = [str(model.data(model.index(i, 0))) for i in range(model.rowCount())]
            if not names:
                return req.cancel()
            pick = names[0]
            if len(names) > 1:
                pick, ok = QInputDialog.getItem(self.window(), "Share your screen", f"Choose what {origin} can see:", names, 0, False)
                if not ok:
                    return req.cancel()
            req.selectScreen(model.index(names.index(pick), 0))
        except Exception:
            crash.log.exception("desktop media")
            req.cancel()

    def on_auth(self, url, auth):
        self._auth_dialog(f"Sign in to {url.host()}", auth.realm() or url.host(), auth)

    def on_proxy_auth(self, url, auth, host):
        self._auth_dialog(f"Proxy {host}", auth.realm() or host, auth)

    def _auth_dialog(self, title, realm, auth):
        d = QDialog(self.window())
        d.setWindowTitle(title)
        form = QFormLayout(d)
        form.addRow(QLabel(f"<b>{title}</b><br>Realm: {realm}"))
        user, pw = QLineEdit(), QLineEdit()
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", user)
        form.addRow("Password", pw)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        form.addRow(bb)
        if d.exec():
            auth.setUser(user.text())
            auth.setPassword(pw.text())
        else:
            auth.setUser("")
            auth.setPassword("")
