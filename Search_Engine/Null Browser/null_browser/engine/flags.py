"""Chromium command-line switches: the single place they are decided.

Switches must be in the environment before `QApplication` exists, so settings.json is read directly. Every switch here has a
reason; nothing is added "just in case".
"""
import json
import os
import sys

from ..core import vpn


def build(settings_path, safe=False, enhanced=True, debug=False):
    """Return the list of switches for this start."""
    data = {}
    try:
        with open(settings_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    flags = []
    features_off = []                                       # Chromium keeps only the LAST --disable-features, so they are collected and written once
    features_on = []
    gpu = not (safe or data.get("hardware_acceleration") is False)
    if not gpu:
        flags.append("--disable-gpu")
    else:
        flags.append("--enable-gpu-rasterization")          # page tiles are drawn on the GPU: smoother scrolling and less CPU on heavy feeds
        flags.append("--enable-zero-copy")                  # rasterised tiles go to the compositor without an extra copy
    if (data.get("permission_defaults") or {}).get("js_optimization") == "block" and not safe:
        flags.append("--js-flags=--jitless")
    if safe:
        flags.append("--disable-extensions")
    if enhanced and not safe and data.get("smooth_scrolling") is not False:
        flags.append("--enable-smooth-scrolling")           # Chromium's eased wheel / keyboard scrolling (off by default in Qt WebEngine)
    if sys.platform == "win32" and not safe:
        # Chromium on Windows works out which windows are hidden behind others and stops / restarts painting them; with a frameless
        # window that shows up as flashes of the page background while switching tabs, resizing or snapping.
        features_off.append("CalculateNativeWinOcclusion")
    if not safe and data.get("custom_autoscroll") is False and sys.platform != "win32":
        features_on.append("MiddleClickAutoscroll")         # only when our own in-page auto-scroll is switched off
    # --- speed: things that make pages load / download faster without telling anyone anything
    if not safe:
        flags.append("--enable-quic")                       # HTTP/3 where the site offers it (fewer round trips)
        features_on.append("ParallelDownloading")           # large downloads use several connections
    # --- privacy: Chromium's own background traffic and "ad privacy" APIs are switched off (the default is on: "share nothing")
    if data.get("share_nothing", True) and not safe:
        flags += ["--disable-background-networking", "--disable-component-update", "--disable-domain-reliability", "--no-pings",
                  "--disable-client-side-phishing-detection", "--no-report-upload", "--disable-breakpad", "--disable-sync",
                  "--disable-default-apps", "--no-default-browser-check", "--dns-prefetch-disable"]
        features_off += ["OptimizationHints", "OptimizationGuideModelDownloading", "OptimizationHintsFetching", "OptimizationTargetPrediction",
                         "BrowsingTopics", "BrowsingTopicsParameters", "Fledge", "FledgeBiddingAndAuctionServer", "InterestGroupStorage",
                         "AttributionReporting", "PrivateAggregationApi", "SharedStorageAPI", "PrivateStateTokens", "InterestFeedContentSuggestions",
                         "NetworkTimeServiceQuerying", "AutofillServerCommunication", "MediaRouter", "GlobalMediaControls", "NetworkPrediction",
                         "PrivacySandboxSettings4", "TrackingProtection3pcd"]
    if features_off:
        flags.append("--disable-features=" + ",".join(dict.fromkeys(features_off)))
    if features_on:
        flags.append("--enable-features=" + ",".join(dict.fromkeys(features_on)))
    if not safe:
        flags += vpn.chromium_args(os.path.dirname(os.path.abspath(settings_path)))      # the built-in VPN (core/vpn.py)
    if not debug:
        flags.append("--log-level=3")                       # only fatal Chromium messages (hides harmless GPU-fallback "ERROR"s)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        flags.append("--no-sandbox")                        # Chromium refuses to run as root otherwise
    return flags, data


def apply(settings_path, safe=False, enhanced=True, debug=False):
    flags, data = build(settings_path, safe, enhanced, debug)
    existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (existing + " " + " ".join(flags)).strip()
    port = int(data.get("remote_debugging_port") or 0)
    if port and "QTWEBENGINE_REMOTE_DEBUGGING" not in os.environ:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = str(port)
    return flags
