"""Hover tooltips: a bold title, an optional keyboard shortcut and a one-line explanation of what the control does."""
from html import escape


def tip_html(title, hint="", shortcut=""):
    head = f"<b>{escape(title)}</b>"
    if shortcut:
        head += f"&nbsp;&nbsp;<span style='opacity:0.6'>{escape(shortcut)}</span>"
    body = f"<br><span style='opacity:0.85'>{escape(hint)}</span>" if hint else ""
    return f"<p style='white-space:pre;margin:0'>{head}{body}</p>"


def tip(widget, title, hint="", shortcut=""):
    """Attach a rich tooltip to any widget and return the widget (so it can be used inline)."""
    widget.setToolTip(tip_html(title, hint, shortcut))
    widget.setToolTipDuration(8000)
    return widget
