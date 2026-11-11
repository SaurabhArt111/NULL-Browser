"""Global constants for Null Browser."""
APP_NAME = "Null Browser"
APP_ID = "NullBrowser"
ORG_NAME = "NullBrowser"
VERSION = "3.1.2"
SCHEME = "null"                      # internal pages: null://history, null://settings ...
UA_TOKEN = f"NullBrowser/{VERSION}"  # only shown in About / logs: it is NOT sent to websites (the user agent looks like plain Chrome)
DEFAULT_SEARCH_PORT = 8000
