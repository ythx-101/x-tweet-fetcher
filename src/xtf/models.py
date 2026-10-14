"""Unified data models.

Every backend normalizes its raw output into these dataclasses, so agent
callers see a single schema regardless of whether data came from FxTwitter,
Nitter HTML, or a browser snapshot.

``to_dict()`` intentionally reproduces the v1 JSON field names and
omission rules (optional fields absent rather than null) so existing
integrations keep working byte-for-byte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _drop_empty(d: dict[str, Any], keys: tuple) -> dict[str, Any]:
    for k in keys:
        if not d.get(k):
            d.pop(k, None)
    return d


@dataclass
class Tweet:
    """A tweet from any backend (timeline / list / search entry)."""

    author: str = ""            # "@handle"
    author_name: str = ""
    text: str = ""
    time_ago: str = ""
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    tweet_id: str = ""
    media: list[str] = field(default_factory=list)
    retweeted_by: str | None = None
    quoted_tweet: Tweet | None = None

    @classmethod
    def from_snapshot_entry(cls, d: dict[str, Any]) -> Tweet:
        qt = d.get("quoted_tweet")
        return cls(
            author=d.get("author", ""),
            author_name=d.get("author_name", d.get("author", "")),
            text=d.get("text", ""),
            time_ago=d.get("time_ago", ""),
            likes=d.get("likes", 0),
            retweets=d.get("retweets", 0),
            replies=d.get("replies", 0),
            views=d.get("views", 0),
            tweet_id=str(d.get("tweet_id", "") or ""),
            media=list(d.get("media", []) or []),
            retweeted_by=d.get("retweeted_by"),
            quoted_tweet=cls.from_snapshot_entry(qt) if qt else None,
        )

    @classmethod
    def from_nitter_entry(cls, d: dict[str, Any]) -> Tweet:
        """Normalize nitter_html parser output (username/display_name/time keys)."""
        user = d.get("username", "")
        return cls(
            author=f"@{user}" if user and not user.startswith("@") else user,
            author_name=d.get("display_name", user),
            text=d.get("text", ""),
            time_ago=d.get("time", ""),
            likes=d.get("likes", 0),
            retweets=d.get("retweets", 0),
            replies=d.get("replies", 0),
            views=d.get("views", 0),
            tweet_id=str(d.get("tweet_id", "") or ""),
            media=list(d.get("media_urls", []) or []),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "author": self.author,
            "author_name": self.author_name,
            "text": self.text,
            "time_ago": self.time_ago,
            "likes": self.likes,
            "retweets": self.retweets,
            "replies": self.replies,
            "views": self.views,
            "tweet_id": self.tweet_id,
        }
        if self.media:
            d["media"] = self.media
        if self.retweeted_by:
            d["retweeted_by"] = self.retweeted_by
        if self.quoted_tweet:
            d["quoted_tweet"] = self.quoted_tweet.to_dict()
        return d


@dataclass
class Reply:
    """A reply under a tweet."""

    author: str = ""
    author_name: str = ""
    text: str = ""
    time_ago: str = ""
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0
    tweet_id: str = ""
    media: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    thread_replies: list[dict[str, Any]] = field(default_factory=list)
    is_author_thread: bool = False

    @classmethod
    def from_snapshot_entry(cls, d: dict[str, Any]) -> Reply:
        return cls(
            author=d.get("author", ""),
            author_name=d.get("author_name", d.get("author", "")),
            text=d.get("text", ""),
            time_ago=d.get("time_ago", "") or "",
            likes=d.get("likes", 0),
            retweets=d.get("retweets", 0),
            replies=d.get("replies", 0),
            views=d.get("views", 0),
            tweet_id=str(d.get("tweet_id", "") or ""),
            media=list(d.get("media", []) or []),
            links=list(d.get("links", []) or []),
            thread_replies=list(d.get("thread_replies", []) or []),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "author": self.author,
            "author_name": self.author_name,
            "text": self.text,
            "time_ago": self.time_ago,
            "likes": self.likes,
            "replies": self.replies,
            "views": self.views,
        }
        if self.retweets:
            d["retweets"] = self.retweets
        if self.tweet_id:
            d["tweet_id"] = self.tweet_id
        if self.media:
            d["media"] = self.media
        if self.links:
            d["links"] = self.links
        if self.thread_replies:
            d["thread_replies"] = self.thread_replies
        if self.is_author_thread:
            d["is_author_thread"] = True
        return d


@dataclass
class Profile:
    username: str = ""
    display_name: str = ""
    bio: str = ""
    tweets_count: int = 0
    following: int = 0
    followers: int = 0
    joined: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "bio": self.bio,
            "tweets_count": self.tweets_count,
            "following": self.following,
            "followers": self.followers,
            "joined": self.joined,
        }


@dataclass
class Article:
    article_id: str = ""
    url: str = ""
    title: str = ""
    author: str = ""
    author_handle: str = ""
    content: str = ""
    paragraphs: list[str] = field(default_factory=list)
    word_count: int = 0
    char_count: int = 0
    is_partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "author_handle": self.author_handle,
            "content": self.content,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "is_partial": self.is_partial,
            "paragraphs": self.paragraphs,
        }
