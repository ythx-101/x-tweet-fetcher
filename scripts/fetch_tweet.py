#!/usr/bin/env python3
"""
X Tweet Fetcher - Fetch tweets from X/Twitter without login or API keys.

Modes:
  --url <URL>              Fetch single tweet via FxTwitter (zero deps)
  --url <URL> --replies    Fetch tweet + replies via Camofox + Nitter
  --user <username>        Fetch user timeline via Camofox + Nitter
"""

import json
import re
import sys
import argparse
import time
import urllib.request
import urllib.error
import urllib.parse
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
        "err_mutually_exclusive": "错误：--user 和 --url 不能同时使用",
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
        # FxTwitter network error
        "err_network": "网络错误：重试后仍无法获取推文",
        "err_unexpected": "获取推文时发生意外错误",
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
        "err_mutually_exclusive": "Error: --user and --url are mutually exclusive",
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
        "err_network": "Network error: Failed to fetch tweet after retry",
        "err_unexpected": "An unexpected error occurred while fetching the tweet",
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
    username, tweet_id = parse_tweet_url(url)
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
    # Pattern: text content followed by 2–4 space-separated numbers at end
    # e.g. "我已经打通...  1   22  4,418"
    # Numbers may have commas (thousands separator)
    stat_match = re.search(
        r"^(.*?)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)$",
        raw.rstrip(),
    )
    if stat_match:
        text_part = stat_match.group(1).strip()
        nums = [int(stat_match.group(i).replace(",", "")) for i in (2, 3, 4)]
        # Nitter columns: replies | retweets | likes (views sometimes separate)
        return text_part, nums[0], nums[1], nums[2], 0

    # Only 2 trailing numbers
    stat_match2 = re.search(
        r"^(.*?)\s{2,}(\d[\d,]*)\s{2,}(\d[\d,]*)$",
        raw.rstrip(),
    )
    if stat_match2:
        text_part = stat_match2.group(1).strip()
        nums = [int(stat_match2.group(i).replace(",", "")) for i in (2, 3)]
        return text_part, nums[0], 0, nums[1], 0

    # Private-use unicode icon stats (from replies page or some Nitter versions)
    icon_match = re.search(
        r"^(.*?)\s*\ue803\s*(\d+)\s*\ue80c\s*\ue801\s*(\d+)\s*\ue800\s*(\d+)",
        raw,
    )
    if icon_match:
        return (
            icon_match.group(1).strip(),
            int(icon_match.group(2)),
            0,
            int(icon_match.group(3)),
            int(icon_match.group(4)),
        )

    # No stats found — clean any icon chars and return raw text
    cleaned = re.sub(r"\s*[\ue800-\ue8ff]\s*[\d,]+", "", raw).strip()
    return cleaned, 0, 0, 0, 0


def parse_timeline_snapshot(snapshot: str, limit: int = 20) -> List[Dict]:
    """Parse Nitter user timeline page snapshot into tweet list.

    Nitter snapshot format (Camofox aria snapshot):
      Page starts with a TOC section (bare link anchors with no surrounding content),
      then the actual tweet cards follow. Each tweet card:

        - link [eN]:           ← tweet permalink (url ends with /status/ID#m)
        - link [eN]:           ← (optional) avatar/profile link
        - link "AuthorName":   ← author display name
        - text: ...            ← (optional blank)
        - link "@handle":      ← author @handle
        - link "10h":          ← timestamp (url also points to /status/ID#m)
        - link "#hashtag":     ← optional hashtags / inline links
        - text: tweet content  1  5  1,234   ← text (+ optional trailing stats)
        - link [eN]:           ← optional media (url has /pic/orig/media%2F...)
        - text:  1   7  541    ← optional separate stats-only line after media
    """
    tweets = []
    lines = snapshot.split("\n")
    n = len(lines)

    # ── Step 1: collect all bare-link tweet anchors ────────────────────────
    # Format:  "- link [eN]:"  followed by "  - /url: /user/status/DIGITS#m"
    all_anchors = []  # (line_index, status_path)
    for i in range(n - 1):
        line = lines[i].strip()
        if not re.match(r'^- link \[e\d+\]:$', line):
            continue
        url_line = lines[i + 1].strip()
        url_match = re.match(r'^- /url:\s+(/\w+/status/(\d+)#m)$', url_line)
        if url_match:
            all_anchors.append((i, url_match.group(1)))

    # ── Step 2: separate TOC anchors from content anchors ─────────────────
    # TOC anchors appear in the top section where consecutive anchors are packed
    # together (next line after the /url: is another anchor or a nav list).
    # Content anchors have author name / text within a window of ~5 lines.
    def _is_content_anchor(anchor_idx: int) -> bool:
        """True if this anchor is followed by author/text (not another anchor)."""
        i, _ = all_anchors[anchor_idx]
        # Look at lines i+2 … i+8 for a named link or text
        for j in range(i + 2, min(n, i + 8)):
            stripped = lines[j].strip()
            if re.match(r'^- link "[^"]+"\s*(\[e\d+\])?:?$', stripped):
                return True   # named link → content
            if stripped.startswith("- text:"):
                return True   # text line → content
            if re.match(r'^- link \[e\d+\]:$', stripped):
                return False  # another bare link → still in TOC
            if stripped.startswith("- list:"):
                return False  # nav list → still in header area
        return False

    content_anchors = [
        a for idx, a in enumerate(all_anchors)
        if _is_content_anchor(idx)
    ]

    # ── Step 3: parse each content tweet block ─────────────────────────────
    for idx, (start_i, tweet_path) in enumerate(content_anchors):
        if len(tweets) >= limit:
            break

        end_i = content_anchors[idx + 1][0] if idx + 1 < len(content_anchors) else n

        author_name = None
        author_handle = None
        time_ago = None
        text_parts: List[str] = []
        stats_set = False
        likes = 0
        retweets = 0
        replies_count = 0
        views = 0
        media_urls = []

        for j in range(start_i, min(end_i, start_i + 60)):
            line = lines[j].strip()

            # Author display name: - link "Name" [eN]: or - link "Name":
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

            # Author @handle
            if not author_handle:
                m = re.match(r'^- link "@(\w+)"\s*(\[e\d+\])?:?$', line)
                if m:
                    author_handle = f"@{m.group(1)}"

            # Timestamp
            if not time_ago:
                m = re.match(r'^- link "(\d+[smhd])"\s*(\[e\d+\])?:?$', line)
                if m:
                    time_ago = m.group(1)
            if not time_ago:
                m = re.match(r'^- link "([A-Z][a-z]{2} \d+(?:, \d{4})?)"\s*(\[e\d+\])?:?$', line)
                if m:
                    time_ago = m.group(1)

            # Text lines (may be multiple for multi-para tweets or embedded @mentions)
            if line.startswith("- text:"):
                raw = line[len("- text:"):].strip()
                if not raw:
                    continue
                text_part, rc, rt, lk, vw = _parse_stats_from_text(raw)
                if lk or rc:
                    # Stats found — capture only once
                    if not stats_set:
                        likes = lk
                        retweets = rt
                        replies_count = rc
                        views = vw
                        stats_set = True
                if text_part:
                    # Skip label-like lines
                    skip_labels = {"pinned tweet", "retweeted", ""}
                    if text_part.strip().lower() not in skip_labels:
                        text_parts.append(text_part.strip())

            # Media URL
            url_match = re.match(r'^- /url:\s+(/pic/orig/(.+))$', line)
            if url_match:
                encoded = url_match.group(2)
                decoded = urllib.parse.unquote(encoded)
                if decoded.startswith("media/"):
                    media_file = decoded[6:]
                    media_url = f"https://pbs.twimg.com/media/{media_file}"
                    if media_url not in media_urls:
                        media_urls.append(media_url)

        tweet_text = " ".join(text_parts).strip() if text_parts else None

        if tweet_text and author_handle:
            tweet_entry = {
                "author": author_handle,
                "author_name": author_name or author_handle,
                "text": tweet_text,
                "time_ago": time_ago or "",
                "likes": likes,
                "retweets": retweets,
                "replies": replies_count,
                "views": views,
            }
            if media_urls:
                tweet_entry["media"] = media_urls

            # Deduplicate by (author, text)
            key = (author_handle, tweet_text[:80])
            if not any(
                (t["author"], t["text"][:80]) == key
                for t in tweets
            ):
                tweets.append(tweet_entry)

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
            time_ago = None
            likes = 0
            replies_count = 0
            views = 0
            media_urls = []
            stats_set = False

            # Scan backwards for author info (within ~15 lines)
            for j in range(i - 1, max(0, i - 15), -1):
                prev = lines[j].strip()

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

                # Stop at next "Replying to" block
                if fwd == "- text: Replying to":
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
                if media_urls:
                    reply["media"] = media_urls

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

def fetch_user_timeline(
    username: str,
    limit: int = 20,
    camofox_port: int = 9377,
    nitter_instance: str = "nitter.net",
) -> Dict[str, Any]:
    """Fetch user timeline via Camofox + Nitter."""
    result = {"username": username, "limit": limit}

    if not check_camofox(camofox_port):
        result["error"] = t("err_camofox_not_running_user", port=camofox_port)
        return result

    nitter_url = f"https://{nitter_instance}/{username}"
    print(t("opening_via_camofox", url=nitter_url), file=sys.stderr)

    snapshot = camofox_fetch_page(
        nitter_url,
        session_key=f"timeline-{username}",
        wait=8,
        port=camofox_port,
    )

    if not snapshot:
        result["error"] = t("err_snapshot_failed")
        return result

    tweets = parse_timeline_snapshot(snapshot, limit=limit)
    result["tweets"] = tweets
    result["count"] = len(tweets)

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
    result["replies"] = replies
    result["reply_count"] = len(replies)

    if len(replies) == 0:
        result["warning"] = t("warn_no_replies")

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    global _lang

    parser = argparse.ArgumentParser(
        description=(
            "Fetch tweets from X/Twitter.\n"
            "  --url <URL>            Single tweet via FxTwitter (zero deps)\n"
            "  --url <URL> --replies  Tweet replies via Camofox + Nitter\n"
            "  --user <username>      User timeline via Camofox + Nitter"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", "-u", help="Tweet URL (x.com or twitter.com)")
    parser.add_argument("--user", help="X/Twitter username (without @)")
    parser.add_argument("--limit", type=int, default=20, help="Max tweets for --user (default: 20)")
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

    # Validate argument combinations
    if args.user and args.url:
        print(t("err_mutually_exclusive"), file=sys.stderr)
        sys.exit(1)

    if not args.user and not args.url:
        parser.print_help()
        sys.exit(1)

    indent = 2 if args.pretty else None

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

    # ── Mode 2: Tweet replies ─────────────────────────────────────────────
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
            print(json.dumps(result, ensure_ascii=False, indent=indent))

        if result.get("error"):
            sys.exit(1)
        return

    # ── Mode 3: Single tweet via FxTwitter (original, zero deps) ─────────
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


if __name__ == "__main__":
    # Version check (best-effort, no crash if unavailable)
    try:
        from scripts.version_check import check_for_update
        check_for_update("ythx-101/x-tweet-fetcher")
    except Exception:
        pass

    main()
