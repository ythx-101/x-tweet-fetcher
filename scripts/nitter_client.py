#!/usr/bin/env python3
"""
Nitter Client - 直接通过 Nitter HTTP API 获取推文，无需浏览器依赖。

纯标准库实现 (urllib.request + html.parser + re)

环境变量:
    NITTER_URL  — Nitter 实例地址，默认 http://127.0.0.1:8788

用法:
    python3 nitter_client.py --timeline YuLin807
    python3 nitter_client.py --search openclaw
    python3 nitter_client.py --tweet YuLin807/2036043414429483372
    python3 nitter_client.py --user-info YuLin807
"""

import os
import re
import sys
import json
import argparse
import urllib.request
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NITTER_URL = os.environ.get("NITTER_URL", "http://127.0.0.1:8788").rstrip("/")

_ANTIBOT_MARKERS = (
    "Making sure you're not a bot!",
    "Verifying your request",
    "Anubis",
    "Sorry this pages exist in order to keep the service usable for everyone.",
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _fetch_html(url: str, timeout: int = 15) -> str:
    """Fetch HTML from Nitter. Returns empty string on error."""
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = "utf-8"
            ct = resp.headers.get_content_charset()
            if ct:
                charset = ct
            return resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[nitter] HTTP {e.code}: {url}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"[nitter] Error fetching {url}: {e}", file=sys.stderr)
        return ""


def _looks_like_antibot_page(html: str) -> bool:
    return bool(html) and any(marker in html for marker in _ANTIBOT_MARKERS)


def check_nitter(url: str = NITTER_URL, timeout: int = 5) -> bool:
    """Return True if Nitter is reachable."""
    try:
        req = urllib.request.Request(url + "/", headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            sample = resp.read(4096).decode(charset, errors="replace")
        return not _looks_like_antibot_page(sample)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HTML Parser
# ---------------------------------------------------------------------------

class _NitterHTMLParser(HTMLParser):
    """
    State-machine HTML parser for Nitter pages.
    Collects tags/attrs/text into a flat event list for post-processing.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: List[Tuple] = []  # ("open", tag, attrs) | ("close", tag) | ("text", data)

    def handle_starttag(self, tag: str, attrs):
        self.events.append(("open", tag, dict(attrs)))

    def handle_endtag(self, tag: str):
        self.events.append(("close", tag))

    def handle_data(self, data: str):
        stripped = data.strip()
        if stripped:
            self.events.append(("text", stripped))


def _parse_html(html: str) -> "_NitterHTMLParser":
    p = _NitterHTMLParser()
    p.feed(html)
    return p


# ---------------------------------------------------------------------------
# Low-level extractors
# ---------------------------------------------------------------------------

def _parse_stat_number(text: str) -> int:
    """Parse a stat number like '1,234' → 1234."""
    if not text:
        return 0
    text = text.strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        return 0


def _extract_tweets_from_events(events: List[Tuple], base_url: str = NITTER_URL) -> List[Dict]:
    """
    Extract tweet dicts from the parsed event list.

    Nitter HTML structure per tweet:
        <div class="timeline-item " data-username="...">
          <a class="tweet-link" href="/user/status/ID#m"></a>
          <div class="tweet-body">
            ...
            <a class="fullname" href="/user" title="DisplayName">DisplayName</a>
            <a class="username" href="/user" title="@user">@user</a>
            <span class="tweet-date"><a ... title="Mar 23, 2026 · 11:32 AM UTC">31m</a></span>
            <div class="tweet-content media-body" dir="auto">TEXT</div>
            ...
            <div class="attachments">
              <a class="still-image" href="/pic/orig/media%2FXXX.jpg">
                <img src="/pic/media%2FXXX.jpg...">
              </a>
            </div>
            <div class="tweet-stats">
              <span class="tweet-stat">
                <div class="icon-container">
                  <span class="icon-comment"></span> 1
                </div>
              </span>
              ...
            </div>
          </div>
        </div>
    """
    tweets = []
    i = 0
    n = len(events)

    while i < n:
        ev = events[i]
        # Find start of timeline-item
        if ev[0] != "open" or ev[1] != "div":
            i += 1
            continue
        cls = ev[2].get("class", "")
        if "timeline-item" not in cls:
            i += 1
            continue

        data_username = ev[2].get("data-username", "")
        tweet_url = ""
        username = ""
        fullname = ""
        tweet_time_title = ""
        tweet_time_ago = ""
        tweet_text = ""
        stats_context = None  # "replies" | "retweets" | "likes" | "views"
        replies = retweets = likes = views = 0
        media_urls = []

        # Walk forward to collect this timeline-item's content.
        # We track depth to know when the div closes.
        depth = 1
        j = i + 1

        while j < n and depth > 0:
            jev = events[j]

            if jev[0] == "open":
                jtag = jev[1]
                jcls = jev[2].get("class", "")
                jhref = jev[2].get("href", "")
                jtitle = jev[2].get("title", "")

                if jtag == "div":
                    depth += 1
                    # Ignore nested timeline-items (quoted tweets / retweets)
                    if "timeline-item" in jcls and depth > 1:
                        # skip inner timeline-item block entirely
                        inner_depth = 1
                        j += 1
                        while j < n and inner_depth > 0:
                            if events[j][0] == "open" and events[j][1] == "div":
                                inner_depth += 1
                            elif events[j][0] == "close" and events[j][1] == "div":
                                inner_depth -= 1
                            j += 1
                        depth -= 1  # the outer div was already counted
                        continue

                elif jtag == "span":
                    depth += 1

                # tweet-link anchor: /user/status/ID#m
                if jtag == "a" and "tweet-link" in jcls and not tweet_url:
                    m = re.search(r'/(\w+)/status/(\d+)#m', jhref)
                    if m:
                        tweet_url = jhref.lstrip("/")
                        if not username:
                            username = m.group(1)

                # fullname
                if jtag == "a" and "fullname" in jcls and jtitle and not fullname:
                    fullname = jtitle

                # username
                if jtag == "a" and "username" in jcls and jtitle and not username:
                    username = jtitle.lstrip("@")

                # tweet-date anchor — also capture href for tweet_id fallback
                if jtag == "a" and not tweet_time_title:
                    # Look for date in parent span.tweet-date
                    if jtitle and re.search(r'\d{4}', jtitle):
                        tweet_time_title = jtitle
                        # Also extract tweet_url from this anchor if not yet found
                        if not tweet_url and jhref:
                            m_td = re.search(r'/(\w+)/status/(\d+)', jhref)
                            if m_td:
                                tweet_url = jhref.lstrip("/").split("#")[0]
                                if not username:
                                    username = m_td.group(1)

                # tweet-content: mark that next text is tweet body
                if jtag == "div" and "tweet-content" in jcls:
                    # Collect text nodes until we close this div
                    text_parts = []
                    tc_depth = 1
                    j += 1
                    while j < n and tc_depth > 0:
                        tev = events[j]
                        if tev[0] == "open" and tev[1] in ("div", "p", "span"):
                            tc_depth += 1
                        elif tev[0] == "close" and tev[1] in ("div", "p", "span"):
                            tc_depth -= 1
                        elif tev[0] == "text" and tc_depth > 0:
                            text_parts.append(tev[1])
                        j += 1
                    tweet_text = " ".join(text_parts).strip()
                    depth -= 1  # div was already counted above
                    continue

                # Stats icons — identify stat type from class
                if jtag == "span":
                    if "icon-comment" in jcls:
                        stats_context = "replies"
                    elif "icon-retweet" in jcls:
                        stats_context = "retweets"
                    elif "icon-heart" in jcls:
                        stats_context = "likes"
                    elif "icon-views" in jcls:
                        stats_context = "views"

                # Media: still-image / video anchors inside attachments
                if jtag == "a" and ("still-image" in jcls or "animated-gif" in jcls):
                    # href is Nitter-proxied path like /pic/orig/media%2FXXX.jpg
                    # Decode to get real twimg URL
                    raw_path = jhref  # e.g. /pic/orig/media%2FXXX.jpg
                    decoded = urllib.parse.unquote(raw_path)
                    # decoded: /pic/orig/media/XXX.jpg
                    m2 = re.search(r'/pic/(?:orig/)?(.+)', decoded)
                    if m2:
                        media_path = m2.group(1)
                        if media_path.startswith("media/"):
                            real_url = "https://pbs.twimg.com/" + media_path
                        else:
                            real_url = "https://pbs.twimg.com/media/" + media_path.split("/")[-1]
                        if real_url not in media_urls:
                            media_urls.append(real_url)

            elif jev[0] == "close":
                if jev[1] == "div":
                    depth -= 1
                elif jev[1] == "span":
                    depth -= 1

            elif jev[0] == "text":
                text_val = jev[1]
                # Time ago (short form like "31m", "2h", "Mar 21")
                if not tweet_time_ago and re.match(r'^\d+[smhd]$|^[A-Z][a-z]{2}\s+\d+', text_val):
                    tweet_time_ago = text_val

                # Stats number following an icon
                if stats_context and re.match(r'^[\d,]+$', text_val.replace(",", "")):
                    val = _parse_stat_number(text_val)
                    if stats_context == "replies":
                        replies = val
                    elif stats_context == "retweets":
                        retweets = val
                    elif stats_context == "likes":
                        likes = val
                    elif stats_context == "views":
                        views = val
                    stats_context = None

            j += 1

        i = j

        # For main tweet detail page, tweet-link may be absent
        # Fall back to tweet-date anchor which also has the status URL
        if not tweet_url and data_username:
            # Try extracting from tweet-date anchor's URL that was captured in time
            # or from the data-username + tweet_id discovered via other means
            pass

        if not tweet_url and not data_username:
            continue

        # Extract tweet_id from url (or try tweet-date title text)
        tweet_id_m = re.search(r'/status/(\d+)', tweet_url) if tweet_url else None
        tweet_id = tweet_id_m.group(1) if tweet_id_m else ""
        if not tweet_url and data_username and tweet_id:
            tweet_url = f"{data_username}/status/{tweet_id}"

        tweet = {
            "text": tweet_text,
            "username": data_username or username,
            "display_name": fullname or (data_username or username),
            "time": tweet_time_title or tweet_time_ago,
            "likes": likes,
            "retweets": retweets,
            "replies": replies,
            "views": views,
            "has_media": bool(media_urls),
            "media_urls": media_urls,
            "url": f"https://x.com/{tweet_url.rstrip('#m')}",
            "tweet_id": tweet_id,
        }
        tweets.append(tweet)

    return tweets


def _extract_next_cursor(html: str) -> Optional[str]:
    """Extract next-page cursor from Nitter HTML.

    Nitter renders: <div class="show-more"><a href="?cursor=XXX">Load more</a></div>
    Or with extra params: <div class="show-more"><a href="?f=tweets&q=...&cursor=XXX">
    """
    # HTML entities: &amp; in href becomes & after unescaping
    m = re.search(r'<div class="show-more"><a href="[^"]*[?&](?:amp;)?cursor=([^"&]+)', html)
    if m:
        return urllib.parse.unquote(m.group(1))
    return None


def _extract_user_info(html: str, username: str) -> Dict:
    """Extract profile info from Nitter user page."""
    info = {
        "username": username,
        "display_name": "",
        "bio": "",
        "tweets_count": 0,
        "followers": 0,
        "following": 0,
        "joined": "",
    }

    # display name
    m = re.search(r'<a class="profile-card-fullname"[^>]+title="([^"]+)"', html)
    if m:
        info["display_name"] = m.group(1)

    # bio
    m = re.search(r'<div class="profile-bio"><p[^>]*>(.*?)</p>', html, re.DOTALL)
    if m:
        raw_bio = m.group(1)
        # Strip HTML tags
        info["bio"] = re.sub(r'<[^>]+>', '', raw_bio).strip()

    # joined date
    m = re.search(r'Joined ([A-Z][a-z]+ \d{4})', html)
    if m:
        info["joined"] = m.group(1)

    # stat numbers from profile-statlist
    # <li class="posts"><span class="profile-stat-header">Tweets</span><span class="profile-stat-num">4,295</span></li>
    stat_blocks = re.findall(
        r'<li class="(\w+)">\s*<span[^>]*>[^<]+</span>\s*<span[^>]*>([\d,]+)</span>',
        html,
    )
    for cls, num in stat_blocks:
        val = _parse_stat_number(num)
        if cls == "posts":
            info["tweets_count"] = val
        elif cls == "followers":
            info["followers"] = val
        elif cls == "following":
            info["following"] = val

    return info


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_timeline(username: str, count: int = 20, cursor: Optional[str] = None) -> List[Dict]:
    """Fetch user timeline tweets from Nitter.

    Uses /search?q=from:{username} as the direct /{username} route
    returns 404 with current session-based auth (guest tokens no longer work).

    Args:
        username: Twitter/X username (without @)
        count: Max number of tweets to return
        cursor: Pagination cursor (optional)

    Returns:
        List of tweet dicts
    """
    return search_tweets(f"from:{username}", count=count, cursor=cursor)


def search_tweets(query: str, count: int = 20, cursor: Optional[str] = None) -> List[Dict]:
    """Search tweets on Nitter.

    Args:
        query: Search query string
        count: Max number of tweets to return
        cursor: Pagination cursor (optional)

    Returns:
        List of tweet dicts
    """
    tweets = []
    current_cursor = cursor
    page = 1
    MAX_PAGES = 10

    while len(tweets) < count and page <= MAX_PAGES:
        params = {"q": query, "f": "tweets"}
        if current_cursor:
            params["cursor"] = current_cursor
        url = f"{NITTER_URL}/search?" + urllib.parse.urlencode(params)

        print(f"[nitter] search page {page}: {url}", file=sys.stderr)
        html = _fetch_html(url)
        if not html:
            break

        parser = _parse_html(html)
        page_tweets = _extract_tweets_from_events(parser.events)

        if not page_tweets:
            break

        for tw in page_tweets:
            if len(tweets) >= count:
                break
            tweets.append(tw)

        current_cursor = _extract_next_cursor(html)
        if not current_cursor:
            break

        page += 1

    return tweets


def fetch_tweet_detail(username: str, tweet_id: str) -> Dict:
    """Fetch a single tweet with its replies.

    Args:
        username: Twitter/X username (without @)
        tweet_id: Tweet ID

    Returns:
        Tweet dict with 'replies_list' key containing list of reply dicts
    """
    url = f"{NITTER_URL}/{username}/status/{tweet_id}"
    print(f"[nitter] tweet detail: {url}", file=sys.stderr)
    html = _fetch_html(url)
    if not html:
        return {"error": f"Failed to fetch {url}"}
    if _looks_like_antibot_page(html):
        return {"error": f"Nitter anti-bot challenge blocked {url}"}

    # Split HTML into main tweet and replies sections
    main_html = ""
    replies_html = ""

    # The main tweet is inside <div id="m" class="main-tweet">
    m_start = re.search(r'<div[^>]+id="m"[^>]*>', html)
    r_start = re.search(r'<div[^>]+id="r"[^>]*class="replies"', html)
    if not r_start:
        r_start = re.search(r'<div[^>]+class="replies"[^>]*id="r"', html)

    if m_start and r_start:
        main_html = html[m_start.start():r_start.start()]
        replies_html = html[r_start.start():]
    elif m_start:
        main_html = html[m_start.start():]
    else:
        main_html = html

    # Parse main tweet
    main_parser = _parse_html(main_html)
    main_tweets = _extract_tweets_from_events(main_parser.events)
    if not main_tweets:
        # Fallback: use og:description for text
        og_text = ""
        m2 = re.search(r'<meta property="og:description" content="([^"]*)"', html)
        if m2:
            og_text = m2.group(1)
        return {
            "text": og_text,
            "username": username,
            "tweet_id": tweet_id,
            "url": f"https://x.com/{username}/status/{tweet_id}",
            "replies_list": [],
        }

    main_tweet = main_tweets[0]
    # Ensure correct username (in case parser picked up reply username)
    main_tweet["username"] = username
    main_tweet["tweet_id"] = tweet_id
    main_tweet["url"] = f"https://x.com/{username}/status/{tweet_id}"

    # Enrich text from og:description (more reliable for full text)
    og_m = re.search(r'<meta property="og:description" content="([^"]*)"', html)
    if og_m:
        og_text = og_m.group(1).strip()
        if og_text and len(og_text) >= len(main_tweet.get("text", "")):
            main_tweet["text"] = og_text

    # Parse replies
    replies = []
    if replies_html:
        replies_parser = _parse_html(replies_html)
        replies = _extract_tweets_from_events(replies_parser.events)

    main_tweet["replies_list"] = replies
    return main_tweet


def fetch_user_info(username: str) -> Dict:
    """Fetch user profile info via FxTwitter API.

    Falls back to Nitter /{user} page if FxTwitter fails.
    """
    username = username.lstrip("@")
    # Try FxTwitter first (reliable, no auth needed)
    try:
        api_url = f"https://api.fxtwitter.com/{username}"
        print(f"[fxtwitter] user info: {api_url}", file=sys.stderr)
        req = urllib.request.Request(api_url, headers={"User-Agent": "x-tweet-fetcher/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        u = data.get("user", {})
        if u:
            return {
                "username": u.get("screen_name", username),
                "display_name": u.get("name", ""),
                "bio": u.get("description", ""),
                "tweets_count": u.get("tweets", 0),
                "followers": u.get("followers", 0),
                "following": u.get("following", 0),
                "joined": u.get("joined", ""),
                "avatar": u.get("avatar_url", ""),
                "banner": u.get("banner_url", ""),
                "likes": u.get("likes", 0),
                "website": u.get("website", ""),
            }
    except Exception as e:
        print(f"[fxtwitter] failed: {e}, trying nitter...", file=sys.stderr)

    # Fallback to Nitter
    url = f"{NITTER_URL}/{username}"
    print(f"[nitter] user info: {url}", file=sys.stderr)
    html = _fetch_html(url)
    if not html:
        return {"error": f"Failed to fetch user info for {username}", "username": username}

    return _extract_user_info(html, username)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Nitter Client — fetch tweets without browser dependency",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 nitter_client.py --timeline YuLin807
  python3 nitter_client.py --timeline YuLin807 --count 10
  python3 nitter_client.py --search openclaw
  python3 nitter_client.py --tweet YuLin807/2036043414429483372
  python3 nitter_client.py --user-info YuLin807
        """,
    )
    parser.add_argument("--timeline", metavar="USERNAME", help="Fetch user timeline")
    parser.add_argument("--search", metavar="QUERY", help="Search tweets")
    parser.add_argument("--tweet", metavar="USER/ID", help="Fetch tweet detail (user/tweet_id)")
    parser.add_argument("--user-info", metavar="USERNAME", help="Fetch user profile info")
    parser.add_argument("--count", type=int, default=20, help="Max items to return (default: 20)")
    parser.add_argument("--cursor", default=None, help="Pagination cursor")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--nitter-url", default=None, help="Nitter URL (default: from NITTER_URL env or http://127.0.0.1:8788)")
    parser.add_argument("--text", action="store_true", help="Human-readable text output")

    args = parser.parse_args()

    # Override NITTER_URL if provided
    global NITTER_URL
    if args.nitter_url:
        NITTER_URL = args.nitter_url.rstrip("/")

    indent = 2 if args.pretty else None

    modes = [args.timeline, args.search, args.tweet, args.user_info]
    if not any(modes):
        parser.print_help()
        sys.exit(1)

    if args.timeline:
        result = fetch_timeline(args.timeline, count=args.count, cursor=args.cursor)
        if args.text:
            print(f"@{args.timeline} — {len(result)} tweets\n")
            for i, tw in enumerate(result, 1):
                print(f"[{i}] {tw['display_name']} (@{tw['username']}) · {tw['time']}")
                print(f"     {tw['text'][:200]}")
                print(f"     ❤ {tw['likes']}  🔁 {tw['retweets']}  💬 {tw['replies']}  👁 {tw['views']}")
                if tw["has_media"]:
                    print(f"     🖼 {len(tw['media_urls'])} media: {', '.join(tw['media_urls'][:2])}")
                print()
        else:
            print(json.dumps(result, ensure_ascii=False, indent=indent))

    elif args.search:
        result = search_tweets(args.search, count=args.count, cursor=args.cursor)
        if args.text:
            print(f"Search: {args.search} — {len(result)} results\n")
            for i, tw in enumerate(result, 1):
                print(f"[{i}] @{tw['username']} · {tw['time']}")
                print(f"     {tw['text'][:200]}")
                print(f"     ❤ {tw['likes']}  🔁 {tw['retweets']}  💬 {tw['replies']}  👁 {tw['views']}")
                print()
        else:
            print(json.dumps(result, ensure_ascii=False, indent=indent))

    elif args.tweet:
        parts = args.tweet.split("/", 1)
        if len(parts) != 2:
            print("Error: --tweet requires format USER/TWEET_ID", file=sys.stderr)
            sys.exit(1)
        user_part, tweet_id_part = parts
        result = fetch_tweet_detail(user_part, tweet_id_part)
        if args.text:
            print(f"@{result.get('username', user_part)}: {result.get('text', '')}")
            print(f"❤ {result.get('likes',0)}  🔁 {result.get('retweets',0)}  💬 {result.get('replies',0)}  👁 {result.get('views',0)}")
            replies_list = result.get("replies_list", [])
            if replies_list:
                print(f"\n--- {len(replies_list)} replies ---")
                for r in replies_list:
                    print(f"  @{r['username']}: {r['text'][:150]}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=indent))

    elif args.user_info:
        result = fetch_user_info(args.user_info)
        if args.text:
            print(f"@{result.get('username','')} ({result.get('display_name','')})")
            print(f"Bio: {result.get('bio','')}")
            print(f"Joined: {result.get('joined','')}")
            print(f"Tweets: {result.get('tweets_count',0)}  Followers: {result.get('followers',0)}  Following: {result.get('following',0)}")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
