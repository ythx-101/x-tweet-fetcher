"""Nitter direct-HTTP backend — timelines, search, replies. No browser.

Supports multiple instances via ``XTF_NITTER=url1,url2`` with health-check
and failover: the first reachable instance is used; on RateLimited /
UpstreamDown mid-task the next instance is tried.
"""
from __future__ import annotations

import sys
import urllib.parse

from .. import config, http
from ..exceptions import BackendUnavailable, XtfError
from ..models import Profile, Reply, Tweet
from ..parsers.nitter_html import (
    _extract_next_cursor,
    _extract_tweets_from_events,
    _extract_user_info,
    _parse_html,
    parse_tweet_detail_html,
)
from .base import Backend

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_MAX_PAGES = 10


class NitterBackend(Backend):
    name = "nitter"

    def __init__(self, instances: list[str] | None = None):
        self.instances = instances or config.nitter_instances()
        self._live: str | None = None  # cached healthy instance

    # ── instance management ──────────────────────────────────────────────
    def _healthy_instance(self) -> str | None:
        if self._live:
            return self._live
        for inst in self.instances:
            if http.probe(inst + "/", timeout=3):
                self._live = inst
                return inst
        return None

    def available(self) -> bool:
        return self._healthy_instance() is not None

    def _get_html(self, path: str) -> str:
        """GET a path, failing over across instances on upstream errors."""
        errors: dict[str, str] = {}
        start = self._healthy_instance()
        candidates = [start] + [i for i in self.instances if i != start] if start else list(self.instances)
        for inst in candidates:
            if inst is None:
                continue
            try:
                html = http.get_text(inst + path, headers=_HEADERS, timeout=15)
                self._live = inst
                return html
            except XtfError as e:
                errors[inst] = f"{e.code}: {e}"
                self._live = None
                print(f"[nitter] {inst} failed ({e.code}), trying next instance...", file=sys.stderr)
        raise BackendUnavailable(
            "No Nitter instance reachable. Set XTF_NITTER to your instance(s), "
            f"e.g. XTF_NITTER=http://127.0.0.1:8788. Tried: {errors}"
        )

    # ── capabilities ─────────────────────────────────────────────────────
    def search(self, query: str, limit: int = 20) -> list[Tweet]:
        tweets_raw: list[dict] = []
        cursor: str | None = None
        page = 1
        while len(tweets_raw) < limit and page <= _MAX_PAGES:
            params = {"q": query, "f": "tweets"}
            if cursor:
                params["cursor"] = cursor
            path = "/search?" + urllib.parse.urlencode(params)
            print(f"[nitter] search page {page}: {path}", file=sys.stderr)
            html = self._get_html(path)
            page_tweets = _extract_tweets_from_events(_parse_html(html).events)
            if not page_tweets:
                break
            for tw in page_tweets:
                if len(tweets_raw) >= limit:
                    break
                tweets_raw.append(tw)
            cursor = _extract_next_cursor(html)
            if not cursor:
                break
            page += 1
        return [Tweet.from_nitter_entry(tw) for tw in tweets_raw]

    def fetch_list(self, list_id: str, limit: int = 20) -> list[Tweet]:
        """List timeline over plain HTTP (/i/lists/ID), paginated by cursor."""
        tweets_raw: list[dict] = []
        cursor: str | None = None
        page = 1
        while len(tweets_raw) < limit and page <= _MAX_PAGES:
            path = f"/i/lists/{list_id}"
            if cursor:
                path += "?" + urllib.parse.urlencode({"cursor": cursor})
            html = self._get_html(path)
            page_tweets = _extract_tweets_from_events(_parse_html(html).events)
            if not page_tweets:
                break
            tweets_raw.extend(page_tweets[: limit - len(tweets_raw)])
            cursor = _extract_next_cursor(html)
            if not cursor:
                break
            page += 1
        return [Tweet.from_nitter_entry(tw) for tw in tweets_raw]

    def fetch_timeline(self, username: str, limit: int = 20) -> list[Tweet]:
        # Direct /{username} route 404s on session-auth Nitter; search works.
        return self.search(f"from:{username}", limit=limit)

    def fetch_replies(self, username: str, tweet_id: str) -> list[Reply]:
        html = self._get_html(f"/{username}/status/{tweet_id}")
        detail = parse_tweet_detail_html(html, username, tweet_id)
        replies: list[Reply] = []
        for r in detail.get("replies_list", []):
            replies.append(
                Reply(
                    author=f"@{r.get('username', '')}",
                    author_name=r.get("display_name", r.get("username", "")),
                    text=r.get("text", ""),
                    time_ago=r.get("time", ""),
                    likes=r.get("likes", 0),
                    retweets=r.get("retweets", 0),
                    replies=r.get("replies", 0),
                    views=r.get("views", 0),
                    tweet_id=str(r.get("tweet_id", "") or ""),
                    media=list(r.get("media_urls", []) or []),
                    links=list(r.get("links", []) or []),
                    is_author_thread=bool(r.get("is_author_thread", False)),
                )
            )
        return replies

    def fetch_user_info(self, username: str) -> Profile:
        html = self._get_html(f"/{username}")
        info = _extract_user_info(html, username)
        return Profile(
            username=info.get("username", username),
            display_name=info.get("display_name", ""),
            bio=info.get("bio", ""),
            tweets_count=info.get("tweets_count", 0),
            following=info.get("following", 0),
            followers=info.get("followers", 0),
            joined=info.get("joined", ""),
        )
