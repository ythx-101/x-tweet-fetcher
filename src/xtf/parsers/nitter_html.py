"""Parsers for raw Nitter HTML pages (direct HTTP mode, no browser).

Pure functions + a stdlib HTMLParser state machine. Extracted verbatim
from the original nitter_client.py; locked by fixture tests.
"""
from __future__ import annotations

import re
import urllib.parse
from html.parser import HTMLParser


class _NitterHTMLParser(HTMLParser):
    """
    State-machine HTML parser for Nitter pages.
    Collects tags/attrs/text into a flat event list for post-processing.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: list[tuple] = []  # ("open", tag, attrs) | ("close", tag) | ("text", data)

    def handle_starttag(self, tag: str, attrs):
        self.events.append(("open", tag, dict(attrs)))

    def handle_endtag(self, tag: str):
        self.events.append(("close", tag))

    def handle_data(self, data: str):
        stripped = data.strip()
        if stripped:
            self.events.append(("text", stripped))


def _parse_html(html: str) -> _NitterHTMLParser:
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


def _extract_tweets_from_events(events: list[tuple], base_url: str = "") -> list[dict]:
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
        links: list[str] = []

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
                    cur_href = ""
                    while j < n and tc_depth > 0:
                        tev = events[j]
                        if tev[0] == "open" and tev[1] in ("div", "p", "span"):
                            tc_depth += 1
                        elif tev[0] == "close" and tev[1] in ("div", "p", "span"):
                            tc_depth -= 1
                        elif tev[0] == "open" and tev[1] == "a":
                            href = (tev[2].get("href") or "").strip()
                            # External links only; skip /user, /search?q=#tag
                            cur_href = href if href.startswith(("http://", "https://")) else ""
                            if cur_href and cur_href not in links:
                                links.append(cur_href)
                        elif tev[0] == "close" and tev[1] == "a":
                            cur_href = ""
                        elif tev[0] == "text" and tc_depth > 0:
                            txt = tev[1]
                            # Nitter shortens link text ("drive.google.com/file/d/1Twv…");
                            # put the real URL back so the text is usable.
                            if cur_href and txt.strip().endswith("…"):
                                txt = cur_href
                            text_parts.append(txt)
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
                if jev[1] == "div" or jev[1] == "span":
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
            "links": links,
            "url": f"https://x.com/{tweet_url.rstrip('#m')}",
            "tweet_id": tweet_id,
        }
        tweets.append(tweet)

    return tweets


def _extract_next_cursor(html: str) -> str | None:
    """Extract next-page cursor from Nitter HTML.

    Nitter renders: <div class="show-more"><a href="?cursor=XXX">Load more</a></div>
    Or with extra params: <div class="show-more"><a href="?f=tweets&q=...&cursor=XXX">
    """
    # HTML entities: &amp; in href becomes & after unescaping
    m = re.search(r'<div class="show-more"><a href="[^"]*[?&](?:amp;)?cursor=([^"&]+)', html)
    if m:
        return urllib.parse.unquote(m.group(1))
    return None


def _extract_user_info(html: str, username: str) -> dict:
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


def parse_tweet_detail_html(html: str, username: str, tweet_id: str) -> dict:
    """Split a Nitter /user/status/ID page into main tweet + replies. Pure."""
    main_html = ""
    replies_html = ""

    m_start = re.search(r'<div[^>]+id="m"[^>]*>', html)
    r_start = re.search(r'<div[^>]+id="r"[^>]*class="replies"', html)
    if not r_start:
        r_start = re.search(r'<div[^>]+class="replies"[^>]*id="r"', html)

    # Author self-replies (a thread continuation, e.g. "link in the reply")
    # render in <div class="after-tweet ..."> between the main tweet and the
    # replies section, not inside #r. Capture them separately.
    a_start = re.search(r'<div[^>]+class="after-tweet[^"]*"', html)
    if a_start and m_start and a_start.start() < m_start.start():
        a_start = None
    if a_start and r_start and a_start.start() > r_start.start():
        a_start = None

    after_html = ""
    if m_start:
        main_end = a_start.start() if a_start else (r_start.start() if r_start else len(html))
        main_html = html[m_start.start():main_end]
        if a_start:
            after_html = html[a_start.start():(r_start.start() if r_start else len(html))]
        if r_start:
            replies_html = html[r_start.start():]
    else:
        main_html = html

    main_tweets = _extract_tweets_from_events(_parse_html(main_html).events)
    if not main_tweets:
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
    main_tweet["username"] = username
    main_tweet["tweet_id"] = tweet_id
    main_tweet["url"] = f"https://x.com/{username}/status/{tweet_id}"

    og_m = re.search(r'<meta property="og:description" content="([^"]*)"', html)
    if og_m:
        og_text = og_m.group(1).strip()
        if og_text and len(og_text) >= len(main_tweet.get("text", "")):
            main_tweet["text"] = og_text

    replies: list[dict] = []
    if after_html:
        for tw in _extract_tweets_from_events(_parse_html(after_html).events):
            tw["is_author_thread"] = True
            replies.append(tw)
    if replies_html:
        replies.extend(_extract_tweets_from_events(_parse_html(replies_html).events))

    main_tweet["replies_list"] = replies
    return main_tweet
