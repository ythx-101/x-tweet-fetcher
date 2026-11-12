"""Unified configuration. All knobs are environment variables.

  XTF_NITTER        Comma-separated Nitter base URLs, tried in order.
                    Accepts full URLs (http://127.0.0.1:8788) or bare
                    hosts (nitter.example.com -> https:// assumed).
                    Default: http://127.0.0.1:8788 (self-hosted).
                    NITTER_URL (v1 name) is honored as a fallback.
  XTF_BROWSER       Browser driver for snapshot mode: "camofox" (default)
                    or "playwright".
  XTF_BROWSER_PORT  Camofox HTTP port (default 9377).
  XTF_LANG          Default message language: zh (default) or en.
  XTF_CACHE_DIR     Mentions-monitor cache dir (default ~/.x-tweet-fetcher).
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_NITTER = "http://127.0.0.1:8788"
DEFAULT_BROWSER_PORT = 9377
USER_AGENT = "x-tweet-fetcher/3.1.0"

# Retry / backoff for upstream HTTP calls
RETRY_ATTEMPTS = 2          # retries after the first attempt
RETRY_BACKOFF_BASE = 1.0    # seconds; doubles each retry


def _normalize_instance(raw: str) -> str:
    raw = raw.strip().rstrip("/")
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def nitter_instances() -> list[str]:
    """Ordered list of Nitter base URLs to try. Never empty."""
    raw = os.environ.get("XTF_NITTER") or os.environ.get("NITTER_URL") or DEFAULT_NITTER
    out = []
    for part in raw.split(","):
        norm = _normalize_instance(part)
        if norm and norm not in out:
            out.append(norm)
    return out or [DEFAULT_NITTER]


def browser_driver() -> str:
    d = os.environ.get("XTF_BROWSER", "camofox").strip().lower()
    return d if d in ("camofox", "playwright") else "camofox"


def browser_port() -> int:
    try:
        return int(os.environ.get("XTF_BROWSER_PORT", DEFAULT_BROWSER_PORT))
    except ValueError:
        return DEFAULT_BROWSER_PORT


def default_lang() -> str:
    lang = os.environ.get("XTF_LANG", "zh").strip().lower()
    return lang if lang in ("zh", "en") else "zh"


def cache_dir() -> Path:
    return Path(os.environ.get("XTF_CACHE_DIR", "")) if os.environ.get("XTF_CACHE_DIR") else Path.home() / ".x-tweet-fetcher"
