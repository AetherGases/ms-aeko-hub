"""Shared HTTP handler messages, header names, limits, and widget paths."""

from pathlib import Path

UNEXPECTED_SERVER_ERROR = "Unexpected server error."
INTERNAL_AUTHENTICATION_KEY_ENV = "INTERNAL_AUTHENTICATION_KEY"
MESSAGE_INPUT_MAX_LENGTH = 8192

_WIDGETS_DIR = (
    Path(__file__).resolve().parents[2] / "cmd" / "api" / "acl" / "open_ai" / "widgets"
)
_SIGN_IN_TEMPLATE_PATH = _WIDGETS_DIR / "oauth_sign_in.html"
_MASCOT_PATH = _WIDGETS_DIR / "ic_aeko_mascot.png"
MASCOT_PATH = "/ai/oauth/ic_aeko_mascot.png"
