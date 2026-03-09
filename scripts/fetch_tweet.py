#!/usr/bin/env python3
"""
X Tweet Fetcher - Fetch tweets from X/Twitter without login or API keys.

Modes:
  --url <URL>              Fetch single tweet via FxTwitter (zero deps)
  --url <URL> --replies    Fetch tweet + replies via Camofox + Nitter
  --user <username>        Fetch user timeline via Camofox + Nitter
  --article <URL_or_ID>    Fetch X Article (long-form) full text via Camofox
  --monitor @username      Monitor X mentions (incremental, cron-friendly)
  --list <list_url_or_id>  Fetch tweets from an X List via Camofox + Nitter

Note on --article mode:
  X Articles (x.com/i/article/...) require X login to view the full content.
  Without login, Camofox will capture whatever is publicly visible (title +
  partial preview). This is an X platform limitation, not a tool limitation.

Note on --monitor mode:
  Uses Google search via Camofox to find mentions. First run establishes a
  baseline (no output). Subsequent runs only report new mentions.
  Exit code: 0 = no new mentions, 1 = new mentions found (cron-friendly).
"""

import json
import os
import re
import sys
import argparse
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, List, Any


# ---------------------------------------------------------------------------
# i18n — bilingual messages (zh default, en via --lang en)
# ---------------------------------------------------------------------------

_MESSAGES = {
    "zh": {
        # stderr progress
        "opening_via_camofox": "[x-tweet-fetcher] 正在通过 Camofox 打开 {url} ...",
        "camofox_tab_error": "[Camofox] 打开标签页失败: {err}",
        "camofox_snapshot_error": "[Camofox] 获取快照失败: {err}",
        # error field values (go into JSON output)
        "err_camofox_not_running_user": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --user 前请先启动 Camofox。"
            "参考: https://github.com/openclaw/camofox"
        ),
        "err_camofox_not_running_replies": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --replies 前请先启动 Camofox。"
            "参考: https://github.com/openclaw/camofox"
        ),
        "err_snapshot_failed": "无法从 Camofox 获取页面快照",
        "err_mutually_exclusive": "错误：--user、--url、--article、--monitor 和 --list 不能同时使用",
        "err_no_input": "错误：请提供 --url 或 --user",
        "err_prefix": "错误：",
        # warning field values
        "warn_no_tweets": (
            "未解析到推文。Nitter 可能触发了频率限制，或该用户不存在，请稍后重试。"
        ),
        "warn_no_replies": (
            "未解析到评论。该推文可能没有回复，或 Nitter 触发了频率限制，请稍后重试。"
        ),
        # text-only labels
        "timeline_header": "@{user} — 最新 {count} 条推文",
        "replies_header": "{url} 的评论区",
        "media_label": "🖼 {n} 张图片",
        "media_label_with_urls": "🖼 {n} 张图片: {urls}",
        # article/tweet text-only
        "article_by": "作者 @{screen_name} | {created_at}",
        "article_stats": "点赞: {likes} | 转推: {retweets} | 浏览: {views}",
        "article_words": "字数: {word_count}",
        "tweet_stats": "\n点赞: {likes} | 转推: {retweets} | 浏览: {views}",
        # article mode
        "opening_article_via_camofox": "[x-tweet-fetcher] 正在通过 Camofox 打开 X Article {url} ...",
        "err_camofox_not_running_article": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --article 前请先启动 Camofox。"
            "参考: https://github.com/openclaw/camofox"
        ),
        "err_invalid_article": "无法解析 Article URL 或 ID: {input}",
        "article_header": "X Article: {title}",
        "article_content_label": "正文",
        "article_login_note": (
            "注意：X Article 需要登录才能查看完整内容。"
            "未登录时 Camofox 只能抓到公开部分（标题+摘要）。"
        ),
        # FxTwitter network error
        "err_network": "网络错误：重试后仍无法获取推文",
        "err_unexpected": "获取推文时发生意外错误",
        # monitor mode
        "monitor_baseline": "[monitor] 首次运行，建立基线 ({count} 条)，下次运行起报告增量。",
        "monitor_no_new": "[monitor] 无新 mentions（已知 {known} 条）。",
        "monitor_new_found": "[monitor] 发现 {count} 条新 mentions！",
        "monitor_searching": "[monitor] 搜索 mentions: {query}",
        "monitor_camofox_error": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --monitor 前请先启动 Camofox。"
            "参考: https://github.com/openclaw/camofox"
        ),
        "monitor_header": "@{username} 的新 mentions ({count} 条)",
        # list mode
        "list_header": "X List {list_id} — 最新 {count} 条推文",
        "err_invalid_list": "无法解析 List URL 或 ID: {input}",
        "err_camofox_not_running_list": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --list 前请先启动 Camofox。"
            "参考: https://github.com/openclaw/camofox"
        ),
    },
    "en": {
        "opening_via_camofox": "[x-tweet-fetcher] Opening {url} via Camofox...",
        "camofox_tab_error": "[Camofox] open tab error: {err}",
        "camofox_snapshot_error": "[Camofox] snapshot error: {err}",
        "err_camofox_not_running_user": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --user. "
            "See: https://github.com/openclaw/camofox"
        ),
        "err_camofox_not_running_replies": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --replies. "
            "See: https://github.com/openclaw/camofox"
        ),
        "err_snapshot_failed": "Failed to get page snapshot from Camofox",
        "err_mutually_exclusive": "Error: --user, --url, --article, --monitor, and --list are mutually exclusive",
        "err_no_input": "Error: provide --url or --user",
        "err_prefix": "Error: ",
        "warn_no_tweets": (
            "No tweets parsed. Nitter may be rate-limited or the user doesn't exist. "
            "Try again later."
        ),
        "warn_no_replies": (
            "No replies parsed. The tweet may have no replies, "
            "or Nitter may be rate-limited. Try again later."
        ),
        "timeline_header": "@{user} — latest {count} tweets",
        "replies_header": "Replies to {url}",
        "media_label": "🖼 {n} media",
        "media_label_with_urls": "🖼 {n} image(s): {urls}",
        "article_by": "By @{screen_name} | {created_at}",
        "article_stats": "Likes: {likes} | Retweets: {retweets} | Views: {views}",
        "article_words": "Words: {word_count}",
        "tweet_stats": "\nLikes: {likes} | Retweets: {retweets} | Views: {views}",
        # article mode
        "opening_article_via_camofox": "[x-tweet-fetcher] Opening X Article {url} via Camofox...",
        "err_camofox_not_running_article": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --article. "
            "See: https://github.com/openclaw/camofox"
        ),
        "err_invalid_article": "Cannot parse Article URL or ID: {input}",
        "article_header": "X Article: {title}",
        "article_content_label": "Content",
        "article_login_note": (
            "Note: X Articles require login to view full content. "
            "Without login, Camofox can only capture the public portion (title + preview)."
        ),
        "err_network": "Network error: Failed to fetch tweet after retry",
        "err_unexpected": "An unexpected error occurred while fetching the tweet",
        # monitor mode
        "monitor_baseline": "[monitor] First run: baseline established ({count} entries). Future runs will report incremental results.",
        "monitor_no_new": "[monitor] No new mentions (known: {known}).",
        "monitor_new_found": "[monitor] Found {count} new mention(s)!",
        "monitor_searching": "[monitor] Searching mentions: {query}",
        "monitor_camofox_error": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --monitor. "
            "See: https://github.com/openclaw/camofox"
        ),
        "monitor_header": "New mentions for @{username} ({count})",
        # list mode
        "list_header": "X List {list_id} — latest {count} tweets",
        "err_invalid_list": "Cannot parse List URL or ID: {input}",
        "err_camofox_not_running_list": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --list. "
            "See: https://github.com/openclaw/camofox"
        ),
    },
}

# Module-level lang (set once in main(), read everywhere)
_lang: str = "zh"


def t(key: str, **kwargs) -> str:
    """Look up a message in the current language, formatting with kwargs."""
    msg = _MESSAGES.get(_lang, _MESSAGES["zh"]).get(key, key)
    return msg.format(**kwargs) if kwargs else msg


# ---------------------------------------------------------------------------
# Camofox helpers
# ---------------------------------------------------------------------------

def check_camofox(port: int = 9377) -> bool:
    """Return True if Camofox is reachable."""
    try:
        req = urllib.request.Request(f"http://localhost:{port}/tabs", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            resp.read()
        return True
    except Exception:
        return False


def camofox_open_tab(url: str, session_key: str, port: int = 9377) -> Optional[str]:
    """Open a new Camofox tab; return tabId or None."""
    try:
        payload = json.dumps({
            "userId": "x-tweet-fetcher",
            "sessionKey": session_key,
            "url": url,
        }).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/tabs",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("tabId")
    except Exception as e:
        print(t("camofox_tab_error", err=e), file=sys.stderr)
        return None


def camofox_snapshot(tab_id: str, port: int = 9377) -> Optional[str]:
    """Get Nitter page snapshot text from Camofox tab."""
    try:
        url = f"http://localhost:{port}/tabs/{tab_id}/snapshot?userId=x-tweet-fetcher"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return data.get("snapshot", "")
    except Exception as e:
        print(t("camofox_snapshot_error", err=e), file=sys.stderr)
        return None


def camofox_close_tab(tab_id: str, port: int = 9377):
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/tabs/{tab_id}",
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def camofox_fetch_page(url: str, session_key: str, wait: float = 8, port: int = 9377) -> Optional[str]:
    """Open URL in Camofox, wait, snapshot, close. Returns snapshot text."""
    tab_id = camofox_open_tab(url, session_key, port)
    if not tab_id:
        return None
    time.sleep(wait)
    snapshot = camofox_snapshot(tab_id, port)
    camofox_close_tab(tab_id, port)
    return snapshot


# ---------------------------------------------------------------------------
# FxTwitter single-tweet fetch (zero deps)
# ---------------------------------------------------------------------------

def parse_tweet_url(url: str) -> tuple:
    """Extract username and tweet_id from X/Twitter URL."""
    patterns = [
        r'(?:x\.com|twitter\.com)/([a-zA-Z0-9_]{1,15})/status/(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            username = match.group(1)
            tweet_id = match.group(2)
            if not re.match(r'^[a-zA-Z0-9_]{1,15}$', username):
                raise ValueError(f"Invalid username format: {username}")
            if not tweet_id.isdigit():
                raise ValueError(f"Invalid tweet ID format: {tweet_id}")
            return username, tweet_id
    raise ValueError(f"Cannot parse tweet URL: {url}")


def extract_media(tweet_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract media information (photos/videos) from tweet object."""
    media_data = {}
    media = tweet_obj.get("media", {})

    all_media = media.get("all", [])
    if all_media and isinstance(all_media, list):
        photos = [item for item in all_media if item.get("type") == "photo"]
        if photos:
            media_data["images"] = []
            for photo in photos:
                image_info = {"url": photo.get("url", "")}
                if photo.get("width"):
                    image_info["width"] = photo.get("width")
                if photo.get("height"):
                    image_info["height"] = photo.get("height")
                media_data["images"].append(image_info)

    videos = media.get("videos", [])
    if videos and isinstance(videos, list) and len(videos) > 0:
        media_data["videos"] = []
        for video in videos:
            video_info = {}
            if video.get("url"):
                video_info["url"] = video.get("url")
            if video.get("duration"):
                video_info["duration"] = video.get("duration")
            if video.get("thumbnail_url"):
                video_info["thumbnail"] = video.get("thumbnail_url")
            if video.get("variants") and isinstance(video.get("variants"), list):
                video_info["variants"] = []
                for variant in video.get("variants", []):
                    variant_info = {}
                    if variant.get("url"):
                        variant_info["url"] = variant.get("url")
                    if variant.get("bitrate"):
                        variant_info["bitrate"] = variant.get("bitrate")
                    if variant.get("content_type"):
                        variant_info["content_type"] = variant.get("content_type")
                    if variant_info:
                        video_info["variants"].append(variant_info)
            if video_info:
                media_data["videos"].append(video_info)

    return media_data if media_data else None


def fetch_tweet(url: str, timeout: int = 30) -> Dict[str, Any]:
    """Fetch single tweet via FxTwitter API (zero deps)."""
    try:
        username, tweet_id = parse_tweet_url(url)
    except ValueError as e:
        return {"url": url, "error": str(e)}
    result = {"url": url, "username": username, "tweet_id": tweet_id}

    api_url = f"https://api.fxtwitter.com/{username}/status/{tweet_id}"

    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())

            if data.get("code") != 200:
                result["error"] = f"FxTwitter returned code {data.get('code')}: {data.get('message', 'Unknown')}"
                return result

            tweet = data["tweet"]
            tweet_data = {
                "text": tweet.get("text", ""),
                "author": tweet.get("author", {}).get("name", ""),
                "screen_name": tweet.get("author", {}).get("screen_name", ""),
                "likes": tweet.get("likes", 0),
                "retweets": tweet.get("retweets", 0),
                "bookmarks": tweet.get("bookmarks", 0),
                "views": tweet.get("views", 0),
                "replies_count": tweet.get("replies", 0),
                "created_at": tweet.get("created_at", ""),
                "is_note_tweet": tweet.get("is_note_tweet", False),
                "lang": tweet.get("lang", ""),
            }

            media = extract_media(tweet)
            if media:
                tweet_data["media"] = media

            if tweet.get("quote"):
                qt = tweet["quote"]
                tweet_data["quote"] = {
                    "text": qt.get("text", ""),
                    "author": qt.get("author", {}).get("name", ""),
                    "screen_name": qt.get("author", {}).get("screen_name", ""),
                    "likes": qt.get("likes", 0),
                    "retweets": qt.get("retweets", 0),
                    "views": qt.get("views", 0),
                }
                quote_media = extract_media(qt)
                if quote_media:
                    tweet_data["quote"]["media"] = quote_media

            article = tweet.get("article")
            if article:
                article_data = {
                    "title": article.get("title", ""),
                    "preview_text": article.get("preview_text", ""),
                    "created_at": article.get("created_at", ""),
                }
                content = article.get("content", {})
                blocks = content.get("blocks", [])
                if blocks:
                    full_text = "\n\n".join(
                        b.get("text", "") for b in blocks if b.get("text", "")
                    )
                    article_data["full_text"] = full_text
                    article_data["word_count"] = len(full_text.split())
                    article_data["char_count"] = len(full_text)
                # 提取 article 内的图片
                article_images = []
                cover = article.get("cover_media", {})
                if cover:
                    cover_url = cover.get("media_info", {}).get("original_img_url")
                    if cover_url:
                        article_images.append({"type": "cover", "url": cover_url})
                for entity in article.get("media_entities", []):
                    img_url = entity.get("media_info", {}).get("original_img_url")
                    if img_url:
                        article_images.append({"type": "image", "url": img_url})
                if article_images:
                    article_data["images"] = article_images
                    article_data["image_count"] = len(article_images)

                tweet_data["article"] = article_data
                tweet_data["is_article"] = True
            else:
                tweet_data["is_article"] = False

            result["tweet"] = tweet_data
            return result

        except urllib.error.URLError:
            if attempt < max_attempts - 1:
                time.sleep(1)
                continue
            else:
                result["error"] = t("err_network")
                return result
        except urllib.error.HTTPError as e:
            result["error"] = f"HTTP {e.code}: {e.reason}"
            return result
        except Exception:
            result["error"] = t("err_unexpected")
            return result

    return result


# ---------------------------------------------------------------------------
# Nitter snapshot parsers
# ---------------------------------------------------------------------------

def _parse_stats_from_text(raw: str) -> tuple:
    """Parse stats numbers from Nitter text line like 'content  1   22  4,418'.

    Nitter renders stats as plain numbers separated by spaces (no icon chars on timeline).
    Returns (cleaned_text, replies, retweets, likes, views).
    """
    # Pattern 0: stats-only line (no text prefix), e.g. " 7  9  83 " or "  6  3  39 "
    stat_only = re.match(
        r"^\s*(\d[\d,]*)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s*[^\d]*$",
        raw.rstrip(),
    )
    if stat_only:
        nums = [int(stat_only.group(i).replace(",", "")) for i in (1, 2, 3)]
        return "", nums[0], nums[1], nums[2], 0

    # Pattern 1: text content followed by 2–4 space-separated numbers at end
    # e.g. "我已经打通...  1   22  4,418"
    # Numbers may have commas (thousands separator)
    stat_match = re.search(
        r"^(.*?)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s*[^\d]*$",
        raw.rstrip(),
    )
    if stat_match:
        text_part = stat_match.group(1).strip()
        nums = [int(stat_match.group(i).replace(",", "")) for i in (2, 3, 4)]
        # Nitter columns: replies | retweets | likes (views sometimes separate)
        return text_part, nums[0], nums[1], nums[2], 0

    # Only 2 trailing numbers
    stat_match2 = re.search(
        r"^(.*?)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s*[^\d]*$",
        raw.rstrip(),
    )
    if stat_match2:
        text_part = stat_match2.group(1).strip()
        nums = [int(stat_match2.group(i).replace(",", "")) for i in (2, 3)]
        return text_part, nums[0], 0, nums[1], 0

    # Private-use unicode icon stats (from replies page or some Nitter versions)
    # Icon stats: \ue803=replies \ue80c=retweets \ue801=likes \ue800=views
    # Numbers are OPTIONAL — Nitter omits them when value is 0
    icon_match = re.search(
        r"\ue803\s*(\d[\d,]*)?\s*\ue80c\s*(\d[\d,]*)?\s*\ue801\s*(\d[\d,]*)?\s*\ue800",
        raw,
    )
    if icon_match:
        prefix = raw[:icon_match.start()].strip()
        def _icon_int(g):
            return int(g.replace(",", "")) if g else 0
        return (
            prefix,
            _icon_int(icon_match.group(1)),
            _icon_int(icon_match.group(2)),
            _icon_int(icon_match.group(3)),
            0,
        )

    # No stats found — clean any icon chars and return raw text
    cleaned = re.sub(r"\s*[\ue800-\ue8ff]\s*[\d,]+", "", raw).strip()
    return cleaned, 0, 0, 0, 0


def parse_timeline_snapshot(snapshot: str, limit: int = 20) -> List[Dict]:
    """Parse Nitter user/list timeline page snapshot into tweet list.

    Handles retweets (``XXX retweeted``), quoted tweets (nested status
    anchors), and inline @mentions split across multiple text/link lines.
    """
    tweets = []
    lines = snapshot.split("\n")
    n = len(lines)

    # ── Step 1: collect all bare-link tweet anchors ────────────────────────
    all_anchors = []  # (line_index, status_path, user, status_id)
    for i in range(n - 1):
        line = lines[i].strip()
        if not re.match(r'^- link \[e\d+\]:$', line):
            continue
        url_line = lines[i + 1].strip()
        url_match = re.match(r'^- /url:\s+(/(\w+)/status/(\d+)#m)$', url_line)
        if url_match:
            all_anchors.append((i, url_match.group(1), url_match.group(2), url_match.group(3)))

    # ── Step 2: separate TOC anchors from content anchors ─────────────────
    def _is_content_anchor(anchor_idx: int) -> bool:
        i = all_anchors[anchor_idx][0]
        for j in range(i + 2, min(n, i + 8)):
            stripped = lines[j].strip()
            if re.match(r'^- link "[^"]+"\s*(\[e\d+\])?:?$', stripped):
                return True
            if stripped.startswith("- text:"):
                return True
            if re.match(r'^- link \[e\d+\]:$', stripped):
                # Could be avatar/profile link — check if its URL is a
                # profile (no /status/) vs another tweet anchor
                if j + 1 < n:
                    next_url = lines[j + 1].strip()
                    url_m = re.match(r'^- /url:\s+(/\w+)$', next_url)
                    if url_m:
                        # Profile link (e.g. /username) — skip, keep looking
                        continue
                return False
            if stripped.startswith("- list:"):
                return False
        return False

    content_anchors = [
        a for idx, a in enumerate(all_anchors)
        if _is_content_anchor(idx)
    ]

    # ── Step 2b: for each anchor, check if "retweeted" appears within ─────
    # 5 lines after it. If so, the anchor's tweet was retweeted by someone.
    # Also detect if a second status anchor appears in the same block (= quote).
    
    # First, build tweet card boundaries.
    # Each card starts at an anchor. A card ends where the next card starts.
    # But a "quoted" anchor (second anchor inside a card) is NOT a card start.
    #
    # Heuristic: an anchor is a "quote" if the anchor immediately before it
    # (in content_anchors) has a different user AND this anchor appears
    # within 30 lines AND there is NO "retweeted" marker between them.
    # Actually simpler: a quote anchor's user differs from the preceding
    # card's primary user, AND there's tweet text between them.
    
    # Simpler approach: just mark anchors that have a "retweeted" line
    # within lines [anchor+1 .. anchor+5]. Those are primary card anchors.
    # Non-retweeted anchors that have tweet text before them from the
    # previous anchor are quotes.
    
    # Let's just use the fact that a quoted tweet's anchor appears AFTER
    # the main tweet's text content. So if we see text content (not just
    # author/handle/time) between anchor N-1 and anchor N, then N is a quote.

    # 如果没有找到任何内容锚点，直接返回空列表
    if not content_anchors:
        return tweets

    primary_indices = [0]  # first anchor is always primary
    quoted_set = set()     # indices into content_anchors that are quotes

    for idx in range(1, len(content_anchors)):
        prev_i = content_anchors[idx - 1][0]
        curr_i = content_anchors[idx][0]
        
        # A quoted tweet appears AFTER the main tweet text but BEFORE
        # the stats line. If we see a stats-only line between anchors,
        # that means the previous tweet's content is complete and this
        # anchor starts a NEW card, not a quote.
        has_tweet_text = False
        has_stats_line = False
        for j in range(prev_i + 2, curr_i):
            stripped = lines[j].strip()
            if stripped.startswith("- text:"):
                raw = stripped[len("- text:"):].strip()
                if not raw:
                    continue
                if re.search(r"retweeted\s*$", raw, re.I):
                    continue
                if raw == "Replying to":
                    continue
                # Check for stats-only line (e.g. "  7  9  83 ")
                _, rc, rt, lk, vw = _parse_stats_from_text(raw)
                if lk or rc or vw:
                    tp = raw
                    stat_m = re.search(r"\s{2,}\d[\d,]*\s{2,}\d[\d,]*", raw)
                    if stat_m:
                        tp = raw[:stat_m.start()].strip()
                    if len(tp) <= 15:
                        has_stats_line = True
                        continue
                if len(raw) > 15:
                    has_tweet_text = True

        # If prev anchor is itself a quote, curr can't be a quote of a quote
        prev_is_quote = (idx - 1) in quoted_set
        
        # Quote only if: has text, NO stats line after it, and prev isn't a quote
        if has_tweet_text and not has_stats_line and not prev_is_quote:
            quoted_set.add(idx)
        else:
            primary_indices.append(idx)

    # ── Helper to parse a block of lines into tweet fields ────────────────
    def _parse_block(start, end, status_id=""):
        author_name = None
        author_handle = None
        time_ago = None
        text_parts = []
        stats_set = False
        likes = rt_count = replies_count = views = 0
        media_urls = []

        for j in range(start, min(end, start + 80)):
            line = lines[j].strip()

            if not author_name:
                m = re.match(r'^- link "([^@#][^"]*?)"\s*(\[e\d+\])?:?$', line)
                if m:
                    name = m.group(1).strip()
                    skip = (
                        re.match(r'^\d+[smhd]$', name)
                        or re.match(r'^[A-Z][a-z]{2} \d+', name)
                        or name.lower() in (
                            "nitter", "logo", "more replies",
                            "tweets", "tweets & replies", "media", "search",
                            "pinned tweet", "retweeted",
                        )
                        or name == ""
                    )
                    if not skip:
                        author_name = name

            if not author_handle:
                m = re.match(r'^- link "@(\w+)"\s*(\[e\d+\])?:?$', line)
                if m:
                    author_handle = "@" + m.group(1)

            if not time_ago:
                m = re.match(r'^- link "(\d+[smhd])"\s*(\[e\d+\])?:?$', line)
                if m:
                    time_ago = m.group(1)
            if not time_ago:
                m = re.match(r'^- link "([A-Z][a-z]{2} \d+(?:, \d{4})?)"\s*(\[e\d+\])?:?$', line)
                if m:
                    time_ago = m.group(1)

            if line.startswith("- text:"):
                raw = line[len("- text:"):].strip()
                if not raw:
                    continue
                if re.match(r'^.+\s+retweeted\s*$', raw):
                    continue
                if raw == "Replying to":
                    continue
                text_part, rc, rt, lk, vw = _parse_stats_from_text(raw)
                if (lk or rc or vw) and not stats_set:
                    likes, rt_count, replies_count, views = lk, rt, rc, vw
                    stats_set = True
                if text_part:
                    skip_labels = {"pinned tweet", "retweeted", ""}
                    if text_part.strip().lower() not in skip_labels:
                        text_parts.append(text_part.strip())

            url_m = re.match(r'^- /url:\s+(/pic/orig/(.+))$', line)
            if url_m:
                decoded = urllib.parse.unquote(url_m.group(2))
                if decoded.startswith("media/"):
                    mu = "https://pbs.twimg.com/media/" + decoded[6:]
                    if mu not in media_urls:
                        media_urls.append(mu)

        tweet_text = " ".join(text_parts).strip() if text_parts else None
        if not tweet_text or not author_handle:
            return None
        entry = {
            "author": author_handle,
            "author_name": author_name or author_handle,
            "text": tweet_text,
            "time_ago": time_ago or "",
            "likes": likes, "retweets": rt_count,
            "replies": replies_count, "views": views,
            "tweet_id": status_id,
        }
        if media_urls:
            entry["media"] = media_urls
        return entry

    # ── Step 3: parse each primary tweet card ──────────────────────────────
    for pi_pos, pi in enumerate(primary_indices):
        if len(tweets) >= limit:
            break

        start_i = content_anchors[pi][0]
        # End at next primary anchor
        if pi_pos + 1 < len(primary_indices):
            end_i = content_anchors[primary_indices[pi_pos + 1]][0]
        else:
            end_i = n

        # Detect "retweeted" marker within first 5 lines after anchor
        retweeted_by = None
        for j in range(start_i + 1, min(start_i + 6, n)):
            stripped = lines[j].strip()
            if stripped.startswith("- text:"):
                raw = stripped[len("- text:"):].strip()
                rt_m = re.match(r'^(.+?)\s+retweeted\s*$', raw)
                if rt_m:
                    retweeted_by = rt_m.group(1).strip()
                    break

        # Find quoted tweet anchor (if any)
        quote_start = end_i
        for qidx in range(pi + 1, len(content_anchors)):
            if content_anchors[qidx][0] >= end_i:
                break
            if qidx in quoted_set:
                quote_start = content_anchors[qidx][0]
                break

        # Parse main tweet (up to quote boundary)
        entry = _parse_block(start_i, quote_start, content_anchors[pi][3])
        if not entry:
            continue

        if retweeted_by:
            entry["retweeted_by"] = retweeted_by

        # Parse quoted tweet
        if quote_start < end_i:
            q_entry = _parse_block(quote_start, end_i)
            if q_entry:
                entry["quoted_tweet"] = q_entry

        # Deduplicate - for retweets, include retweeted_by in key to preserve different retweeters
        if entry.get("retweeted_by"):
            # Retweets: key includes retweeted_by so different people retweeting same content aren't deduped
            key = (entry["retweeted_by"], entry["text"][:80])
        else:
            key = (entry["author"], entry["text"][:80])
        if not any((t.get("retweeted_by") or t["author"], t["text"][:80]) == key for t in tweets):
            tweets.append(entry)

    return tweets



def parse_replies_snapshot(snapshot: str, original_author: str) -> List[Dict]:
    """Parse replies from Nitter tweet page snapshot.

    Each reply block in Nitter looks like:
      - link [eN]:           ← reply permalink (url /author/status/ID#m)
      - link "AuthorName":   ← replier display name
      - link "@handle":      ← replier handle
      - link "12h":          ← time ago (OR "Feb 15" for older)
      - text: Replying to    ← reply marker
      - link "@original":    ← who they replied to
      - text: reply content  ← actual text (may have stats at end)
      - link [eN]:           ← optional media
      - text:  1  0  60      ← optional stats-only line
    """
    replies = []
    lines = snapshot.split("\n")
    n = len(lines)

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line == "- text: Replying to":
            author_handle = None
            author_name = None
            reply_text = None
            reply_tweet_id = None  # 新增：回复的 tweet ID（用于递归抓嵌套）
            time_ago = None
            likes = 0
            replies_count = 0
            views = 0
            media_urls = []
            links = []  # 新增：提取评论中的链接
            thread_replies = []  # 新增：嵌套回复
            stats_set = False

            # Scan backwards for author info (within ~15 lines)
            for j in range(i - 1, max(0, i - 15), -1):
                prev = lines[j].strip()

                # Extract reply tweet ID from permalink: /url: /author/status/12345#m
                if not reply_tweet_id:
                    tid_m = re.match(r'^- /url:\s+/\w+/status/(\d+)#m$', prev)
                    if tid_m:
                        reply_tweet_id = tid_m.group(1)

                # @handle (not the original author)
                if not author_handle:
                    m = re.match(r'^- link "@(\w+)"\s*(\[e\d+\])?:?$', prev)
                    if m and m.group(1).lower() != original_author.lower():
                        author_handle = f"@{m.group(1)}"

                # Display name (not time, not nav items)
                if not author_name:
                    m = re.match(r'^- link "([^@#][^"]*?)"\s*(\[e\d+\])?:?$', prev)
                    if m:
                        name = m.group(1).strip()
                        is_time = bool(
                            re.match(r'^\d+[smhd]$', name)
                            or re.match(r'^[A-Z][a-z]{2} \d+', name)
                        )
                        is_skip = name.lower() in (
                            "nitter", "logo", "more replies", ""
                        )
                        if not is_time and not is_skip:
                            author_name = name

                # Timestamp (short: "12h") or date ("Feb 15")
                if not time_ago:
                    m = re.match(r'^- link "(\d+[smhd])"\s*(\[e\d+\])?:?$', prev)
                    if m:
                        time_ago = m.group(1)
                if not time_ago:
                    m = re.match(r'^- link "([A-Z][a-z]{2} \d+(?:, \d{4})?)"\s*(\[e\d+\])?:?$', prev)
                    if m:
                        time_ago = m.group(1)

                if author_handle and author_name and time_ago:
                    break

            # Scan forward for reply text and media (skip "@original" link line)
            for j in range(i + 1, min(n, i + 20)):
                fwd = lines[j].strip()

                # Skip the "@original_author" line right after "Replying to"
                if re.match(r'^- link "@\w+"\s*(\[e\d+\])?:?$', fwd):
                    continue

                if fwd.startswith("- text:"):
                    raw = fwd[len("- text:"):].strip()
                    if not raw:
                        continue

                    text_part, rc, rt, lk, vw = _parse_stats_from_text(raw)

                    # Capture stats once
                    if (lk or rc or vw) and not stats_set:
                        likes = lk
                        replies_count = rc
                        views = vw
                        stats_set = True

                    if text_part and not reply_text:
                        skip_labels = {"replying to", ""}
                        if text_part.strip().lower() not in skip_labels:
                            reply_text = text_part.strip()

                # Media URL line
                url_match = re.match(r'^- /url:\s+(/pic/orig/(.+))$', fwd)
                if url_match:
                    encoded = url_match.group(2)
                    decoded = urllib.parse.unquote(encoded)
                    if decoded.startswith("media/"):
                        media_file = decoded[6:]
                        media_url = f"https://pbs.twimg.com/media/{media_file}"
                        if media_url not in media_urls:
                            media_urls.append(media_url)

                # Link URL line: extract from /url: lines following any link element
                link_url_match = re.match(r'^- /url:\s+(.+)$', fwd)
                if link_url_match:
                    url_part = link_url_match.group(1).strip()
                    # Skip media URLs (already handled above)
                    if not url_part.startswith("/pic/"):
                        decoded_url = urllib.parse.unquote(url_part)
                        # Filter out relative paths and keep valid URLs
                        if decoded_url.startswith("http"):
                            if decoded_url not in links:
                                links.append(decoded_url)

                # Named link where the link text itself is a URL:
                # e.g. - link "https://github.com/some/repo":
                named_link_match = re.match(r'^- link "([^"]+)"\s*(\[e\d+\])?:?$', fwd)
                if named_link_match:
                    link_text = named_link_match.group(1).strip()
                    if link_text.startswith("http"):
                        if link_text not in links:
                            links.append(link_text)

                # Stop at next "Replying to" block - but collect nested replies first
                if fwd == "- text: Replying to":
                    # Continue scanning for nested replies within this thread
                    # Skip the @original line and continue parsing nested content
                    nested_reply_text = None
                    nested_time_ago = None
                    nested_likes = 0
                    nested_replies_count = 0
                    nested_views = 0
                    
                    for k in range(j + 1, min(n, j + 15)):
                        nested_line = lines[k].strip()
                        
                        # Skip @handle lines
                        if re.match(r'^- link "@\w+"\s*(\[e\d+\])?:?$', nested_line):
                            continue
                            
                        # Check for timestamp
                        if not nested_time_ago:
                            m = re.match(r'^- link "(\d+[smhd])"\s*(\[e\d+\])?:?$', nested_line)
                            if m:
                                nested_time_ago = m.group(1)
                        
                        # Parse nested reply text
                        if nested_line.startswith("- text:"):
                            raw = nested_line[len("- text:"):].strip()
                            if raw:
                                text_part, rc, rt, lk, vw = _parse_stats_from_text(raw)
                                if text_part and not nested_reply_text:
                                    skip_labels = {"replying to", ""}
                                    if text_part.strip().lower() not in skip_labels:
                                        nested_reply_text = text_part.strip()
                                        nested_likes = lk
                                        nested_replies_count = rc
                                        nested_views = vw
                        
                        # Stop at next "Replying to" block
                        if nested_line == "- text: Replying to":
                            break
                    
                    if nested_reply_text:
                        thread_replies.append({
                            "text": nested_reply_text,
                            "time_ago": nested_time_ago,
                            "likes": nested_likes,
                            "replies": nested_replies_count,
                            "views": nested_views
                        })
                    
                    # Now break for the main loop
                    break

            if author_handle and reply_text:
                reply = {
                    "author": author_handle,
                    "author_name": author_name or author_handle,
                    "text": reply_text,
                    "time_ago": time_ago,
                    "likes": likes,
                    "replies": replies_count,
                    "views": views,
                }
                if reply_tweet_id:
                    reply["tweet_id"] = reply_tweet_id
                if media_urls:
                    reply["media"] = media_urls
                if links:
                    reply["links"] = links
                if thread_replies:
                    reply["thread_replies"] = thread_replies

                # Deduplicate
                if not any(
                    r["author"] == author_handle and r["text"] == reply_text
                    for r in replies
                ):
                    replies.append(reply)

        i += 1

    return replies


# ---------------------------------------------------------------------------
# High-level feature functions
# ---------------------------------------------------------------------------

def extract_next_cursor(snapshot: str) -> Optional[str]:
    """Extract the next-page cursor from a Nitter timeline snapshot.

    Nitter aria snapshot format for the "Load more" link:
        - link "Load more" [eN]:
          - /url: "?cursor=XXXXXX"

    Returns the raw cursor string (URL-decoded), or None if not found.
    """
    lines = snapshot.split("\n")
    for i, line in enumerate(lines):
        if 'link "Load more"' in line:
            # Next line should be the /url: line
            for j in range(i + 1, min(len(lines), i + 4)):
                url_line = lines[j].strip()
                m = re.match(r'^- /url:\s+"?\?cursor=([^"&\s]+)"?', url_line)
                if m:
                    return urllib.parse.unquote(m.group(1))
    return None


def fetch_user_timeline(
    username: str,
    limit: int = 20,
    camofox_port: int = 9377,
    nitter_instance: str = "nitter.net",
) -> Dict[str, Any]:
    """Fetch user timeline via Camofox + Nitter, with multi-page support.

    When limit > ~20 (one page), automatically follows Nitter's cursor-based
    pagination until enough tweets are collected or no more pages exist.
    """
    result = {"username": username, "limit": limit}

    if not check_camofox(camofox_port):
        result["error"] = t("err_camofox_not_running_user", port=camofox_port)
        return result

    tweets: List[Dict] = []
    cursor: Optional[str] = None
    page = 1
    MAX_PAGES = 6  # safety cap — never fetch more than ~120 tweets

    while len(tweets) < limit and page <= MAX_PAGES:
        if cursor:
            encoded = urllib.parse.quote(cursor, safe="")
            nitter_url = f"https://{nitter_instance}/{username}?cursor={encoded}"
        else:
            nitter_url = f"https://{nitter_instance}/{username}"

        print(
            f"[x-tweet-fetcher] 翻页 {page}/{MAX_PAGES} — {nitter_url}",
            file=sys.stderr,
        )

        snapshot = camofox_fetch_page(
            nitter_url,
            session_key=f"timeline-{username}-p{page}",
            wait=8,
            port=camofox_port,
        )

        if not snapshot:
            if page == 1:
                result["error"] = t("err_snapshot_failed")
                return result
            # Partial failure on later pages — stop gracefully
            print(f"[x-tweet-fetcher] 第 {page} 页快照失败，停止翻页", file=sys.stderr)
            break

        remaining = limit - len(tweets)
        new_tweets = parse_timeline_snapshot(snapshot, limit=remaining)

        # Deduplicate across pages by (author, text[:80])
        seen = {(tw["author"], tw["text"][:80]) for tw in tweets}
        for tw in new_tweets:
            key = (tw["author"], tw["text"][:80])
            if key not in seen:
                tweets.append(tw)
                seen.add(key)

        print(
            f"[x-tweet-fetcher] 第 {page} 页: +{len(new_tweets)} 条，累计 {len(tweets)} 条",
            file=sys.stderr,
        )

        if len(new_tweets) == 0:
            break  # no tweets on this page — Nitter probably rate-limited

        # Extract cursor for next page
        cursor = extract_next_cursor(snapshot)
        if not cursor:
            break  # no more pages

        page += 1
        if len(tweets) < limit:
            time.sleep(2)  # be polite between pages

    # 用 FxTwitter 补充浏览量
    tweets = supplement_views(tweets)

    result["tweets"] = tweets
    result["count"] = len(tweets)
    result["pages_fetched"] = page
    result["views_supplemented"] = True

    if len(tweets) == 0:
        result["warning"] = t("warn_no_tweets")

    return result


def extract_list_id(input_str: str) -> Optional[str]:
    """Extract list ID from a URL or raw ID string.

    Accepts:
      - Pure numeric ID:           "123456789"
      - List URL:                 "https://x.com/i/lists/123456789"
      - List URL (twitter.com):  "https://twitter.com/i/lists/123456789"
      - List URL (no scheme):    "x.com/i/lists/123456789"

    Returns the list ID string (digits only), or None if unparseable.
    """
    input_str = input_str.strip()

    # Pure numeric ID
    if re.match(r'^\d+$', input_str):
        return input_str

    # URL containing /i/lists/<id>
    m = re.search(r'/i/lists/(\d+)', input_str)
    if m:
        return m.group(1)

    return None


def fetch_list_tweets(
    list_id: str,
    limit: int = 20,
    camofox_port: int = 9377,
    nitter_instance: str = "nitter.net",
) -> Dict[str, Any]:
    """Fetch tweets from an X List via Camofox + Nitter, with multi-page support.

    When limit > ~20 (one page), automatically follows Nitter's cursor-based
    pagination until enough tweets are collected or no more pages exist.
    """
    result = {"list_id": list_id, "limit": limit}

    if not check_camofox(camofox_port):
        result["error"] = t("err_camofox_not_running_list", port=camofox_port)
        return result

    tweets: List[Dict] = []
    cursor: Optional[str] = None
    page = 1
    MAX_PAGES = 10  # safety cap — never fetch more than ~200 tweets

    while len(tweets) < limit and page <= MAX_PAGES:
        if cursor:
            encoded = urllib.parse.quote(cursor, safe="")
            nitter_url = f"https://{nitter_instance}/i/lists/{list_id}?cursor={encoded}"
        else:
            nitter_url = f"https://{nitter_instance}/i/lists/{list_id}"

        print(
            f"[x-tweet-fetcher] 翻页 {page}/{MAX_PAGES} — {nitter_url}",
            file=sys.stderr,
        )

        snapshot = camofox_fetch_page(
            nitter_url,
            session_key=f"list-{list_id}-p{page}",
            wait=8,
            port=camofox_port,
        )

        if not snapshot:
            if page == 1:
                result["error"] = t("err_snapshot_failed")
                return result
            # Partial failure on later pages — stop gracefully
            print(f"[x-tweet-fetcher] 第 {page} 页快照失败，停止翻页", file=sys.stderr)
            break

        remaining = limit - len(tweets)
        new_tweets = parse_timeline_snapshot(snapshot, limit=remaining)

        # Deduplicate across pages by (author, text[:80])
        seen = {(tw["author"], tw["text"][:80]) for tw in tweets}
        for tw in new_tweets:
            key = (tw["author"], tw["text"][:80])
            if key not in seen:
                tweets.append(tw)
                seen.add(key)

        print(
            f"[x-tweet-fetcher] 第 {page} 页: +{len(new_tweets)} 条，累计 {len(tweets)} 条",
            file=sys.stderr,
        )

        if len(new_tweets) == 0:
            break  # no tweets on this page — Nitter probably rate-limited

        # Extract cursor for next page
        cursor = extract_next_cursor(snapshot)
        if not cursor:
            break  # no more pages

        page += 1
        if len(tweets) < limit:
            time.sleep(2)  # be polite between pages

    # 用 FxTwitter 补充浏览量
    tweets = supplement_views(tweets)

    result["tweets"] = tweets
    result["count"] = len(tweets)
    result["pages_fetched"] = page
    result["views_supplemented"] = True

    if len(tweets) == 0:
        result["warning"] = t("warn_no_tweets")

    return result



def fetch_tweet_replies(
    url: str,
    camofox_port: int = 9377,
    nitter_instance: str = "nitter.net",
) -> Dict[str, Any]:
    """Fetch tweet replies via Camofox + Nitter."""
    try:
        username, tweet_id = parse_tweet_url(url)
    except ValueError as e:
        return {"url": url, "error": str(e)}

    result = {"url": url, "username": username, "tweet_id": tweet_id}

    if not check_camofox(camofox_port):
        result["error"] = t("err_camofox_not_running_replies", port=camofox_port)
        return result

    nitter_url = f"https://{nitter_instance}/{username}/status/{tweet_id}"
    print(t("opening_via_camofox", url=nitter_url), file=sys.stderr)

    snapshot = camofox_fetch_page(
        nitter_url,
        session_key=f"replies-{tweet_id}",
        wait=8,
        port=camofox_port,
    )

    if not snapshot:
        result["error"] = t("err_snapshot_failed")
        return result

    replies = parse_replies_snapshot(snapshot, original_author=username)

    # ── 递归抓取嵌套回复（Issue #24 修复） ──
    # 对有 replies > 0 且有 tweet_id 的评论，访问其独立 status 页面
    # 获取嵌套回复内容（Nitter 评论区页面不展开嵌套回复）
    for reply in replies:
        if reply.get("replies", 0) > 0 and reply.get("tweet_id"):
            reply_author = reply["author"].lstrip("@")
            reply_tid = reply["tweet_id"]
            nested_url = f"https://{nitter_instance}/{reply_author}/status/{reply_tid}"
            print(
                f"[x-tweet-fetcher] 抓取嵌套回复: {reply_author}/status/{reply_tid}",
                file=sys.stderr,
            )

            nested_snapshot = camofox_fetch_page(
                nested_url,
                session_key=f"nested-{reply_tid}",
                wait=8,
                port=camofox_port,
            )

            if nested_snapshot:
                nested_replies = parse_replies_snapshot(
                    nested_snapshot, original_author=reply_author
                )
                if nested_replies:
                    reply["thread_replies"] = nested_replies

    result["replies"] = replies
    result["reply_count"] = len(replies)

    if len(replies) == 0:
        result["warning"] = t("warn_no_replies")

    return result


# ---------------------------------------------------------------------------
# X Article helpers
# ---------------------------------------------------------------------------

def parse_article_id(input_str: str) -> Optional[str]:
    """Extract article ID from a URL or raw ID string.

    Accepts:
      - Pure numeric ID:           "2011779830157557760"
      - Article URL:               "https://x.com/i/article/2011779830157557760"
      - Article URL (no scheme):   "x.com/i/article/2011779830157557760"
      - Tweet URL whose text links to an article (pass the ID directly in that case)

    Returns the article ID string, or None if unparseable.
    """
    input_str = input_str.strip()

    # Pure numeric ID
    if re.match(r'^\d{10,25}$', input_str):
        return input_str

    # URL containing /i/article/<id>
    m = re.search(r'/i/article/(\d{10,25})', input_str)
    if m:
        return m.group(1)

    return None


def parse_article_snapshot(snapshot: str) -> Dict[str, Any]:
    """Parse an X Article page snapshot (Camofox aria snapshot) into structured data.

    X Article accessibility tree structure (observed):
      - heading "Article title"          ← article title
      - text: @AuthorHandle              ← author handle
      - text: Author Name                ← author display name
      - text: <date>                     ← publish date
      - text: paragraph 1
      - text: paragraph 2
      ...

    Because X requires login for full content, the snapshot may only contain
    title + preview/teaser. We capture whatever is available.

    Returns a dict with keys:
      title, author, author_handle, paragraphs, content, word_count, char_count,
      is_partial (True when content is likely truncated due to login wall)
    """
    lines = snapshot.split("\n")
    title: Optional[str] = None
    author_handle: Optional[str] = None
    author_name: Optional[str] = None
    paragraphs: List[str] = []

    # Patterns
    heading_re = re.compile(r'^-\s+heading\s+"(.+)"', re.IGNORECASE)
    text_re = re.compile(r'^-\s+text:\s+(.*)')
    link_re = re.compile(r'^-\s+link\s+"([^"]+)"')
    handle_re = re.compile(r'^@(\w+)$')

    # Strings to skip (navigation / boilerplate / empty)
    _SKIP_TEXTS = {
        "", "x", "home", "explore", "notifications", "messages", "grok",
        "profile", "more", "post", "log in", "sign up", "sign in",
        "already have an account?", "don't have an account?",
        "subscribe", "get the app", "help", "settings", "privacy policy",
        "terms of service", "cookie policy", "accessibility",
        "ads info", "more options", "follow", "following",
    }

    def _is_skip(text: str) -> bool:
        stripped = text.strip().lower()
        return stripped in _SKIP_TEXTS or len(stripped) < 2

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # ── Heading → title ────────────────────────────────────────────────
        m = heading_re.match(line)
        if m and not title:
            candidate = m.group(1).strip()
            if not _is_skip(candidate):
                title = candidate
            i += 1
            continue

        # ── text: lines ────────────────────────────────────────────────────
        m = text_re.match(line)
        if m:
            raw = m.group(1).strip()

            # Author @handle
            hm = handle_re.match(raw)
            if hm and not author_handle:
                author_handle = raw  # keep with @
                i += 1
                continue

            # Skip boilerplate
            if _is_skip(raw):
                i += 1
                continue

            # Skip short date-like strings immediately after author info
            # (e.g. "Feb 10, 2025") — we don't extract date for now, just skip
            if re.match(r'^[A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}$', raw):
                i += 1
                continue

            # Author display name heuristic: single line, no spaces (but allow
            # names like "John Doe"), appears early before paragraphs, not a sentence
            if not author_name and not paragraphs and len(raw.split()) <= 4 and not raw.endswith("."):
                author_name = raw
                i += 1
                continue

            # Everything else is paragraph content
            paragraphs.append(raw)
            i += 1
            continue

        # ── Named links can sometimes be author name or article sub-heading ─
        m = link_re.match(line)
        if m:
            text = m.group(1).strip()
            hm = handle_re.match(text)
            if hm and not author_handle:
                author_handle = text
            elif not _is_skip(text) and not author_name and not paragraphs:
                author_name = text
            i += 1
            continue

        i += 1

    content = "\n\n".join(paragraphs)
    word_count = len(content.split()) if content else 0
    char_count = len(content)

    # Heuristic: if content is very short (< 100 chars), likely login wall
    is_partial = char_count < 100

    return {
        "title": title or "",
        "author": author_name or "",
        "author_handle": author_handle or "",
        "paragraphs": paragraphs,
        "content": content,
        "word_count": word_count,
        "char_count": char_count,
        "is_partial": is_partial,
    }


def fetch_article(
    input_str: str,
    camofox_port: int = 9377,
) -> Dict[str, Any]:
    """Fetch an X Article via Camofox.

    ``input_str`` can be:
      - A full article URL:  https://x.com/i/article/2011779830157557760
      - A bare article ID:   2011779830157557760

    Note: X Articles require login to read the full text. Without login,
    only publicly visible content (title + preview) is captured.
    Camofox must be running on the given port.

    Returns a dict with:
      article_id, url, title, author, author_handle, content,
      word_count, char_count, is_partial, warning (if partial)
    """
    article_id = parse_article_id(input_str)
    if not article_id:
        return {
            "input": input_str,
            "error": t("err_invalid_article", input=input_str),
        }

    article_url = f"https://x.com/i/article/{article_id}"
    result: Dict[str, Any] = {
        "article_id": article_id,
        "url": article_url,
    }

    if not check_camofox(camofox_port):
        result["error"] = t("err_camofox_not_running_article", port=camofox_port)
        return result

    print(t("opening_article_via_camofox", url=article_url), file=sys.stderr)

    # X Articles are JS-heavy; use a longer wait (10 s)
    snapshot = camofox_fetch_page(
        article_url,
        session_key=f"article-{article_id}",
        wait=10,
        port=camofox_port,
    )

    if not snapshot:
        result["error"] = t("err_snapshot_failed")
        return result

    parsed = parse_article_snapshot(snapshot)

    result["title"] = parsed["title"]
    result["author"] = parsed["author"]
    result["author_handle"] = parsed["author_handle"]
    result["content"] = parsed["content"]
    result["word_count"] = parsed["word_count"]
    result["char_count"] = parsed["char_count"]
    result["is_partial"] = parsed["is_partial"]
    result["paragraphs"] = parsed["paragraphs"]

    if parsed["is_partial"]:
        # Surface the login-wall note so callers / users understand the limitation
        result["warning"] = t("article_login_note")

    return result


# ---------------------------------------------------------------------------
# Mentions 监控（--monitor 模式）
# ---------------------------------------------------------------------------

# 缓存目录：~/.x-tweet-fetcher/
_CACHE_DIR = Path.home() / ".x-tweet-fetcher"
# 单个用户缓存最大保留 URL 数量
_CACHE_MAX = 500


def _get_cache_path(username: str) -> Path:
    """返回指定用户的 mentions 缓存文件路径。"""
    # 去掉 @ 前缀，统一小写，避免大小写重复
    clean = username.lstrip("@").lower()
    return _CACHE_DIR / f"mentions-cache-{clean}.json"


def _load_cache(username: str) -> dict:
    """加载 mentions 缓存，返回 {'seen': [...url...], 'is_baseline': bool}。"""
    path = _get_cache_path(username)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧格式（纯列表）
            if isinstance(data, list):
                return {"seen": data, "is_baseline": False}
            return data
        except Exception:
            pass
    return {"seen": [], "is_baseline": True}


def _save_cache(username: str, cache: dict):
    """保存 mentions 缓存到磁盘，超过上限时截断最旧条目。"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # 限制缓存大小，保留最新的 _CACHE_MAX 条
    if len(cache["seen"]) > _CACHE_MAX:
        cache["seen"] = cache["seen"][-_CACHE_MAX:]
    path = _get_cache_path(username)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _search_mentions(username: str, limit: int = 10, port: int = 9377) -> List[Dict]:
    """
    通过 Camofox + Google 搜索该用户的 mentions，返回去重后的搜索结果列表。

    搜索策略：
      1. site:x.com @username   — 带 @ 的直接提及
      2. site:x.com username    — 不带 @ 的提及（更广）

    每种策略最多取 limit 条，最终合并去重（以 URL 为 key）。
    """
    # 避免循环 import：在函数内部 import
    try:
        import sys as _sys
        import os as _os
        # 将 scripts/ 目录加入路径，确保 camofox_client 可 import
        scripts_dir = _os.path.dirname(_os.path.abspath(__file__))
        if scripts_dir not in _sys.path:
            _sys.path.insert(0, scripts_dir)
        from camofox_client import camofox_search
    except ImportError:
        # fallback：直接用内置的 camofox_search（如果在同目录运行）
        from scripts.camofox_client import camofox_search

    clean = username.lstrip("@")
    queries = [
        f"site:x.com @{clean}",
        f"site:x.com {clean}",
    ]

    seen_urls: set = set()
    results: List[Dict] = []

    for query in queries:
        print(t("monitor_searching", query=query), file=sys.stderr)
        raw = camofox_search(query, num=limit, port=port)
        for item in raw:
            url = item.get("url", "").strip()
            # 只保留 x.com 下的推文 URL（过滤搜索引擎导航链接）
            if url and url not in seen_urls and "x.com" in url:
                seen_urls.add(url)
                results.append({
                    "url": url,
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                })

    return results


def monitor_mentions(
    username: str,
    limit: int = 10,
    camofox_port: int = 9377,
) -> Dict[str, Any]:
    """
    监控 X mentions 增量变化。

    首次运行：建立基线，不报任何新内容（exit code 0）。
    后续运行：与缓存对比，只报告新增 URL（exit code 1 = 有新内容）。

    返回格式：
    {
        "username": "...",
        "new_mentions": [...],   # 新增条目列表
        "is_baseline": True/False,
        "known_count": N,
        "error": "..." (可选)
    }
    """
    result: Dict[str, Any] = {
        "username": username.lstrip("@"),
        "new_mentions": [],
        "is_baseline": False,
        "known_count": 0,
    }

    # 检查 Camofox 是否运行
    if not check_camofox(camofox_port):
        result["error"] = t("monitor_camofox_error", port=camofox_port)
        return result

    # 加载本地缓存
    cache = _load_cache(username)
    seen_set = set(cache["seen"])
    result["known_count"] = len(seen_set)

    # 搜索 mentions
    all_results = _search_mentions(username, limit=limit, port=camofox_port)

    if cache["is_baseline"]:
        # 首次运行：将所有搜索结果写入缓存作为基线，不报新内容
        new_urls = [r["url"] for r in all_results]
        cache["seen"] = list(seen_set | set(new_urls))
        cache["is_baseline"] = False
        _save_cache(username, cache)
        result["is_baseline"] = True
        result["known_count"] = len(cache["seen"])
        print(t("monitor_baseline", count=len(cache["seen"])), file=sys.stderr)
    else:
        # 后续运行：只报告不在缓存中的新条目
        new_mentions = [r for r in all_results if r["url"] not in seen_set]

        # 将新 URL 加入缓存
        for r in new_mentions:
            cache["seen"].append(r["url"])
        _save_cache(username, cache)

        result["new_mentions"] = new_mentions
        result["known_count"] = len(cache["seen"])

        if new_mentions:
            print(t("monitor_new_found", count=len(new_mentions)), file=sys.stderr)
        else:
            print(t("monitor_no_new", known=len(seen_set)), file=sys.stderr)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global _lang

    parser = argparse.ArgumentParser(
        description=(
            "Fetch tweets from X/Twitter.\n"
            "  --url <URL>              Single tweet via FxTwitter (zero deps)\n"
            "  --url <URL> --replies    Tweet replies via Camofox + Nitter\n"
            "  --user <username>        User timeline via Camofox + Nitter\n"
            "  --article <URL_or_ID>    X Article full text via Camofox\n"
            "  --monitor @username      Monitor X mentions (incremental, cron-friendly)\n"
            "  --list <list_url_or_id>  Fetch tweets from an X List via Camofox + Nitter\n"
            "\n"
            "Note: --article requires Camofox. X Articles also require X login\n"
            "for full content; without login only public preview is captured.\n"
            "Note: --monitor requires Camofox. First run builds a baseline (no output).\n"
            "Subsequent runs report only new mentions. Exit code 1 = new content found."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", "-u", help="Tweet URL (x.com or twitter.com)")
    parser.add_argument("--user", help="X/Twitter username (without @)")
    parser.add_argument("--article", "-a", metavar="URL_or_ID",
                        help="X Article URL (https://x.com/i/article/ID) or bare article ID")
    parser.add_argument("--monitor", "-m", metavar="@USERNAME",
                        help="Monitor X mentions for a username (requires Camofox)")
    parser.add_argument("--list", "-l", metavar="LIST_URL_OR_ID",
                        help="Fetch tweets from an X List (URL or ID, requires Camofox)")
    parser.add_argument("--limit", type=int, default=50, help="Max tweets for --user / max results for --monitor (default: 50 for --user, 10 for --monitor)")
    parser.add_argument("--replies", "-r", action="store_true", help="Fetch replies (requires Camofox)")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty print JSON")
    parser.add_argument("--text-only", "-t", action="store_true", help="Human-readable output")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds (default: 30)")
    parser.add_argument("--port", type=int, default=9377, help="Camofox port (default: 9377)")
    parser.add_argument("--nitter", default="nitter.net", help="Nitter instance (default: nitter.net)")
    parser.add_argument(
        "--lang", default="zh", choices=["zh", "en"],
        help="Output language for tool messages: zh (default) or en",
    )

    args = parser.parse_args()

    # Apply language setting globally before any t() calls
    _lang = args.lang

    # Count how many primary modes are requested
    _modes = [bool(args.url), bool(args.user), bool(args.article), bool(args.monitor), bool(args.list)]
    if sum(_modes) > 1:
        print(t("err_mutually_exclusive"), file=sys.stderr)
        sys.exit(1)

    if not any(_modes):
        parser.print_help()
        sys.exit(1)

    indent = 2 if args.pretty else None

    # ── Mode 0: Mentions 监控 ─────────────────────────────────────────────
    if args.monitor:
        # --limit 对 --monitor 默认 10（搜索结果），若用户显式传 limit 则用用户的值
        monitor_limit = args.limit if args.limit != 50 else 10
        result = monitor_mentions(
            args.monitor,
            limit=monitor_limit,
            camofox_port=args.port,
        )

        if result.get("error"):
            print(t("err_prefix") + result["error"], file=sys.stderr)
            sys.exit(2)

        if result.get("is_baseline"):
            # 首次建基线，静默退出（exit 0）
            if not args.text_only:
                print(json.dumps(result, ensure_ascii=False, indent=indent))
            sys.exit(0)

        new_mentions = result.get("new_mentions", [])

        if args.text_only:
            username_clean = result["username"]
            if new_mentions:
                print(t("monitor_header", username=username_clean, count=len(new_mentions)) + "\n")
                for idx, m in enumerate(new_mentions, 1):
                    print(f"[{idx}] {m['title']}")
                    print(f"     {m['url']}")
                    if m.get("snippet"):
                        print(f"     {m['snippet'][:120]}")
                    print()
            # 无新内容时 text-only 模式不输出任何内容（方便 cron）
        else:
            print(json.dumps(result, ensure_ascii=False, indent=indent))

        # exit 1 = 有新 mentions（cron 友好），exit 0 = 无新内容
        sys.exit(1 if new_mentions else 0)

    # ── Mode 1: User timeline ─────────────────────────────────────────────
    if args.user:
        result = fetch_user_timeline(
            args.user,
            limit=args.limit,
            camofox_port=args.port,
            nitter_instance=args.nitter,
        )

        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            tweets = result.get("tweets", [])
            print(t("timeline_header", user=args.user, count=len(tweets)) + "\n")
            for idx, tw in enumerate(tweets, 1):
                print(f"[{idx}] {tw['author_name']} ({tw['author']}) · {tw.get('time_ago', '')}")
                print(f"     {tw['text']}")
                stats = f"     ❤ {tw['likes']}  💬 {tw['replies']}  👁 {tw['views']}"
                if tw.get("media"):
                    stats += "  " + t("media_label", n=len(tw["media"]))
                print(stats)
                print()
        else:
            print(json.dumps(result, ensure_ascii=False, indent=indent))

        if result.get("error"):
            sys.exit(1)
        return

    # ── Mode 2: X Article ────────────────────────────────────────────────
    if args.article:
        result = fetch_article(
            args.article,
            camofox_port=args.port,
        )

        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            title = result.get("title") or "(no title)"
            author = result.get("author") or result.get("author_handle") or ""
            content = result.get("content", "")
            wc = result.get("word_count", 0)
            print(t("article_header", title=title))
            if author:
                print(f"@{result.get('author_handle', '').lstrip('@') or author}  {author}")
            print(t("article_words", word_count=wc))
            if result.get("warning"):
                print(f"⚠️  {result['warning']}")
            print()
            print(content or "(empty)")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))

        if result.get("error"):
            sys.exit(1)
        return

    # ── Mode 3: Tweet replies ─────────────────────────────────────────────
    if args.url and args.replies:
        result = fetch_tweet_replies(
            args.url,
            camofox_port=args.port,
            nitter_instance=args.nitter,
        )

        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            replies = result.get("replies", [])
            # 用 FxTwitter 补充浏览量
            replies = supplement_views(replies)
            print(t("replies_header", url=args.url) + "\n")
            for idx, r in enumerate(replies, 1):
                print(f"[{idx}] {r['author_name']} ({r['author']}) · {r.get('time_ago', '')}")
                print(f"     {r['text']}")
                stats = f"     ❤ {r['likes']}  💬 {r['replies']}  👁 {r['views']}"
                if r.get("media"):
                    stats += "  " + t("media_label_with_urls", n=len(r["media"]), urls=", ".join(r["media"]))
                print(stats)
                print()
        else:
            # 用 FxTwitter 补充浏览量
            if result.get("replies"):
                result["replies"] = supplement_views(result["replies"])
                result["views_supplemented"] = True
            print(json.dumps(result, ensure_ascii=False, indent=indent))

        if result.get("error"):
            sys.exit(1)
        return

    # ── Mode 4: X List tweets ─────────────────────────────────────────────
    if args.list:
        # Extract list_id from input
        list_id = extract_list_id(args.list)
        if not list_id:
            print(t("err_prefix") + t("err_invalid_list", input=args.list), file=sys.stderr)
            sys.exit(1)

        result = fetch_list_tweets(
            list_id,
            limit=args.limit,
            camofox_port=args.port,
            nitter_instance=args.nitter,
        )

        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            tweets = result.get("tweets", [])
            print(t("list_header", list_id=list_id, count=len(tweets)) + "\n")
            for idx, tw in enumerate(tweets, 1):
                print(f"[{idx}] {tw['author_name']} ({tw['author']}) · {tw.get('time_ago', '')}")
                print(f"     {tw['text']}")
                stats = f"     ❤ {tw['likes']}  💬 {tw['replies']}  👁 {tw['views']}"
                if tw.get("media"):
                    stats += "  " + t("media_label", n=len(tw["media"]))
                print(stats)
                print()
        else:
            print(json.dumps(result, ensure_ascii=False, indent=indent))

        if result.get("error"):
            sys.exit(1)
        return

    # ── Mode 4: Single tweet via FxTwitter (original, zero deps) ─────────
    result = fetch_tweet(args.url, timeout=args.timeout)

    if args.text_only:
        tweet = result.get("tweet", {})
        if tweet.get("is_article") and tweet.get("article", {}).get("full_text"):
            article = tweet["article"]
            print(f"# {article['title']}\n")
            print(t("article_by", screen_name=tweet["screen_name"], created_at=tweet.get("created_at", "")))
            print(t("article_stats", likes=tweet["likes"], retweets=tweet["retweets"], views=tweet["views"]))
            print(t("article_words", word_count=article["word_count"]) + "\n")
            print(article["full_text"])
        elif tweet.get("text"):
            print(f"@{tweet['screen_name']}: {tweet['text']}")
            print(t("tweet_stats", likes=tweet["likes"], retweets=tweet["retweets"], views=tweet["views"]))
        elif result.get("error"):
            print(t("err_prefix") + result["error"], file=sys.stderr)
            sys.exit(1)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=indent))

    if result.get("error"):
        sys.exit(1)




def supplement_views(tweets: List[Dict], max补充: int = 50) -> List[Dict]:
    """用 FxTwitter API 补充浏览量数据"""
    import requests
    for i, tw in enumerate(tweets[:max补充]):
        if tw.get("views", 0) != 0:
            continue  # 已有浏览量，跳过
        # 从 author 构建 tweet URL
        author = tw.get("author", "")
        if not author or not author.startswith("@"):
            # 记录没有 author 的推文
            print(f"[views] 跳过无 author: {tw.get('text', '')[:50]}...", file=sys.stderr)
            continue
        username = author.lstrip("@")
        # 需要 tweet_id - 如果没有 tweet_id 就跳过并打日志
        tweet_id = tw.get("tweet_id") or tw.get("id")
        if not tweet_id:
            print(f"[views] 跳过无 tweet_id: @{username} - {tw.get('text', '')[:50]}...", file=sys.stderr)
            continue
        try:
            resp = requests.get(f"https://api.fxtwitter.com/status/{tweet_id}", timeout=5)
            data = resp.json()
            views = data.get("tweet", {}).get("views", 0)
            if views:
                tw["views"] = views
                print(f"[views] {username}/{tweet_id[:8]}... → {views}", file=sys.stderr)
        except Exception as e:
            pass
    return tweets
if __name__ == "__main__":
    # Version check (best-effort, no crash if unavailable)
    try:
        from scripts.version_check import check_for_update
        check_for_update("ythx-101/x-tweet-fetcher")
    except Exception:
        pass

    main()
