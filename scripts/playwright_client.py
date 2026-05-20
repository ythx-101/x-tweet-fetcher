#!/usr/bin/env python3
"""
Playwright Client - Drop-in replacement for camofox_client.py.

Provides the same public interface as camofox_client but uses Playwright
(Chromium) instead of the Camofox REST API.

Public interface (mirrors camofox_client.py):
  check_camofox(port)            → always True (Playwright needs no server)
  camofox_open_tab(url, ...)     → returns fake tab_id, fetches page
  camofox_snapshot(tab_id, ...)  → returns stored page text
  camofox_close_tab(tab_id, ...) → frees stored page text
  camofox_fetch_page(url, ...)   → open URL, wait, return text content
  camofox_search(query, ...)     → search via Google/DDG, return results list

Additional high-level helpers for Nitter:
  playwright_fetch_nitter_timeline(username, cursor, wait) → List[Dict]
  playwright_fetch_nitter_replies(username, tweet_id, wait) → List[Dict]
  playwright_get_nitter_cursor(username_or_url, wait)      → str | None
"""

import os
import sys
import time
import secrets
import urllib.parse
from typing import Optional, List, Dict, Any, Tuple

# ---------------------------------------------------------------------------
# Chromium executable path
# ---------------------------------------------------------------------------
_CHROMIUM_EXEC_ENV = "PLAYWRIGHT_CHROMIUM_EXEC"


def _resolve_chromium_executable(browser_type) -> Optional[str]:
    """Return a Chromium executable path, preferring a valid env override."""
    env_path = os.environ.get(_CHROMIUM_EXEC_ENV)
    if env_path:
        if os.path.exists(env_path):
            return env_path
        print(
            f"[playwright_client] {_CHROMIUM_EXEC_ENV} does not exist: {env_path}; "
            "using Playwright bundled Chromium",
            file=sys.stderr,
        )

    executable_path = getattr(browser_type, "executable_path", None)
    return executable_path if executable_path and os.path.exists(executable_path) else None

# Default working Nitter instance (nitter.net is down; tiekoetter is live)
# Nitter fallback chain: tested 2026-03-22, only these 3 are alive
NITTER_INSTANCES = [
    "nitter.tiekoetter.com",   # 🇩🇪 fastest, curl+Playwright both work
    "xcancel.com",             # 🇺🇸 403 to curl but Playwright works
    "nitter.catsarch.com",     # 🇺🇸/🇩🇪 same as above
]
DEFAULT_NITTER = os.environ.get("NITTER_INSTANCE", NITTER_INSTANCES[0])

# ---------------------------------------------------------------------------
# Fake tab registry  (camofox_open_tab / camofox_snapshot compatibility)
# ---------------------------------------------------------------------------
_tab_store: dict = {}   # tab_id → page text


# ---------------------------------------------------------------------------
# Internal browser helpers
# ---------------------------------------------------------------------------

def _launch_browser():
    """Return a (playwright, browser) pair.  Caller must close both."""
    from playwright.sync_api import sync_playwright  # lazy import
    pw = sync_playwright().start()
    launch_options = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    executable_path = _resolve_chromium_executable(pw.chromium)
    if executable_path:
        launch_options["executable_path"] = executable_path
    browser = pw.chromium.launch(**launch_options)
    return pw, browser


def _new_context(browser, lang: str = "zh-CN"):
    return browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale=lang,
        viewport={"width": 1280, "height": 900},
    )


def _safe_goto(page, url: str, timeout: int = 30000):
    """Navigate to url, tolerating timeout errors."""
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        pass  # partial load is fine for JS-heavy pages


def _page_text(page) -> str:
    """Return inner_text of <body>."""
    try:
        return page.inner_text("body", timeout=5000) or ""
    except Exception:
        pass
    try:
        return page.content()
    except Exception:
        return ""


def _fetch_url_text(url: str, wait: float = 8) -> Optional[str]:
    """Fetch *url* with Playwright, return visible text.  None on failure."""
    pw = browser = None
    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser)
        page = ctx.new_page()
        _safe_goto(page, url)
        time.sleep(wait)
        text = _page_text(page)
        ctx.close()
        return text or None
    except Exception as e:
        print(f"[playwright_client] fetch error {url[:80]}: {e}", file=sys.stderr)
        return None
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Nitter DOM parsers (primary implementation)
# ---------------------------------------------------------------------------

# JS snippet to parse timeline items from a Nitter page
_TIMELINE_JS = """() => {
    const items = document.querySelectorAll(".timeline-item");
    const results = [];
    for (const item of items) {
        const link = item.querySelector("a.tweet-link");
        const href = link ? link.getAttribute("href") : "";
        const m = href ? href.match(/status\\/(\\d+)/) : null;
        const tweetId = m ? m[1] : "";

        const fullname = item.querySelector("a.fullname");
        const username = item.querySelector("a.username");
        const dateEl = item.querySelector(".tweet-date a");
        const content = item.querySelector(".tweet-content");

        // Media images
        const mediaImgs = item.querySelectorAll(".attachments img.still-image");
        const mediaUrls = [];
        for (const img of mediaImgs) {
            const src = img.getAttribute("src") || "";
            if (src.startsWith("/pic/")) {
                const decoded = decodeURIComponent(src.replace("/pic/", ""));
                if (decoded.startsWith("media/")) {
                    mediaUrls.push("https://pbs.twimg.com/media/" + decoded.slice(6));
                }
            }
        }

        // Stats
        let replies=0, retweets=0, likes=0, views=0;
        const statsEls = item.querySelectorAll(".tweet-stat");
        for (const s of statsEls) {
            const val = parseInt(s.textContent.replace(/,/g,"").trim()) || 0;
            if (s.querySelector(".icon-comment")) replies = val;
            else if (s.querySelector(".icon-retweet")) retweets = val;
            else if (s.querySelector(".icon-heart")) likes = val;
            else if (s.querySelector(".icon-stats")) views = val;
        }

        // Retweet banner
        const rtBanner = item.querySelector(".retweet-header");
        const retweetedBy = rtBanner ? rtBanner.textContent.trim().replace(/ retweeted$/, "").trim() : null;

        // Quoted tweet (nested)
        const quoteEl = item.querySelector(".quote");
        let quotedTweet = null;
        if (quoteEl) {
            const qLink = quoteEl.querySelector("a.quote-link");
            const qHref = qLink ? qLink.getAttribute("href") : "";
            const qm = qHref ? qHref.match(/status\\/(\\d+)/) : null;
            const qFn = quoteEl.querySelector(".fullname");
            const qUn = quoteEl.querySelector(".username");
            const qContent = quoteEl.querySelector(".quote-text");
            quotedTweet = {
                tweet_id: qm ? qm[1] : "",
                author: qUn ? qUn.textContent.trim() : "",
                author_name: qFn ? qFn.textContent.trim() : "",
                text: qContent ? qContent.textContent.trim() : "",
            };
        }

        results.push({
            tweet_id: tweetId,
            author_name: fullname ? fullname.textContent.trim() : "",
            author: username ? username.textContent.trim() : "",
            time_ago: dateEl ? dateEl.textContent.trim() : "",
            text: content ? content.textContent.trim() : "",
            replies, retweets, likes, views,
            retweeted_by: retweetedBy,
            media: mediaUrls.length ? mediaUrls : null,
            quoted_tweet: quotedTweet,
        });
    }
    return results;
}"""

# JS snippet to extract "load more" cursor from Nitter page
_CURSOR_JS = """() => {
    const moreLink = document.querySelector("a.show-more[href*='cursor'], .show-more a[href*='cursor']");
    if (!moreLink) return null;
    const href = moreLink.getAttribute("href");
    const m = href.match(/[?&]cursor=([^&#]+)/);
    return m ? decodeURIComponent(m[1]) : null;
}"""

# JS snippet to parse replies from a Nitter tweet status page
_REPLIES_JS = """() => {
    const items = document.querySelectorAll(".timeline-item");
    const results = [];
    for (const item of items) {
        const link = item.querySelector("a.tweet-link");
        const href = link ? link.getAttribute("href") : "";
        const m = href ? href.match(/status\\/(\\d+)/) : null;
        const tweetId = m ? m[1] : "";

        const fullname = item.querySelector("a.fullname");
        const username = item.querySelector("a.username");
        const dateEl = item.querySelector(".tweet-date a");
        const content = item.querySelector(".tweet-content");
        const replyInfo = item.querySelector(".replying-to");

        // Media
        const mediaImgs = item.querySelectorAll(".attachments img.still-image");
        const mediaUrls = [];
        for (const img of mediaImgs) {
            const src = img.getAttribute("src") || "";
            if (src.startsWith("/pic/")) {
                const decoded = decodeURIComponent(src.replace("/pic/", ""));
                if (decoded.startsWith("media/")) {
                    mediaUrls.push("https://pbs.twimg.com/media/" + decoded.slice(6));
                }
            }
        }

        // Stats
        let replies=0, retweets=0, likes=0, views=0;
        const statsEls = item.querySelectorAll(".tweet-stat");
        for (const s of statsEls) {
            const val = parseInt(s.textContent.replace(/,/g,"").trim()) || 0;
            if (s.querySelector(".icon-comment")) replies = val;
            else if (s.querySelector(".icon-retweet")) retweets = val;
            else if (s.querySelector(".icon-heart")) likes = val;
            else if (s.querySelector(".icon-stats")) views = val;
        }

        // Links in tweet
        const linkEls = content ? content.querySelectorAll("a[href]") : [];
        const links = [];
        for (const a of linkEls) {
            const ahref = a.getAttribute("href") || "";
            if (ahref.startsWith("http")) links.push(ahref);
        }

        results.push({
            tweet_id: tweetId,
            author_name: fullname ? fullname.textContent.trim() : "",
            author: username ? username.textContent.trim() : "",
            time_ago: dateEl ? dateEl.textContent.trim() : "",
            text: content ? content.textContent.trim() : "",
            replies, retweets, likes, views,
            replying_to: replyInfo ? replyInfo.textContent.trim() : null,
            media: mediaUrls.length ? mediaUrls : null,
            links: links.length ? links : null,
        });
    }
    return results;
}"""


def playwright_fetch_nitter_timeline(
    username: str,
    cursor: Optional[str] = None,
    nitter: str = DEFAULT_NITTER,
    wait: float = 7,
) -> Tuple[List[Dict], Optional[str]]:
    """
    Fetch one page of a user's Nitter timeline via Playwright DOM parsing.

    Returns (tweets_list, next_cursor_or_None).
    """
    if cursor:
        url = f"https://{nitter}/{username}?cursor={urllib.parse.quote(cursor, safe='')}"
    else:
        url = f"https://{nitter}/{username}"

    pw = browser = None
    tweets: List[Dict] = []
    next_cursor: Optional[str] = None

    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser)
        page = ctx.new_page()
        _safe_goto(page, url)
        time.sleep(wait)

        tweets = page.evaluate(_TIMELINE_JS) or []
        next_cursor = page.evaluate(_CURSOR_JS)
        ctx.close()
    except Exception as e:
        print(f"[playwright_client] timeline error ({username}): {e}", file=sys.stderr)
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass

    return tweets, next_cursor


def playwright_fetch_nitter_replies(
    username: str,
    tweet_id: str,
    nitter: str = DEFAULT_NITTER,
    wait: float = 7,
) -> Tuple[List[Dict], Optional[str]]:
    """
    Fetch replies for a tweet from its Nitter status page.

    Returns (all_items_list, next_cursor_or_None).
    The first item is usually the original tweet itself.
    """
    url = f"https://{nitter}/{username}/status/{tweet_id}"
    pw = browser = None
    items: List[Dict] = []
    next_cursor: Optional[str] = None

    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser)
        page = ctx.new_page()
        _safe_goto(page, url)
        time.sleep(wait)

        items = page.evaluate(_REPLIES_JS) or []
        next_cursor = page.evaluate(_CURSOR_JS)
        ctx.close()
    except Exception as e:
        print(f"[playwright_client] replies error ({username}/{tweet_id}): {e}", file=sys.stderr)
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass

    return items, next_cursor


def playwright_fetch_nitter_list(
    list_id: str,
    cursor: Optional[str] = None,
    nitter: str = DEFAULT_NITTER,
    wait: float = 7,
) -> Tuple[List[Dict], Optional[str]]:
    """
    Fetch one page of tweets from a Nitter list.

    Returns (tweets_list, next_cursor_or_None).
    """
    if cursor:
        url = f"https://{nitter}/i/lists/{list_id}?cursor={urllib.parse.quote(cursor, safe='')}"
    else:
        url = f"https://{nitter}/i/lists/{list_id}"

    pw = browser = None
    tweets: List[Dict] = []
    next_cursor: Optional[str] = None

    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser)
        page = ctx.new_page()
        _safe_goto(page, url)
        time.sleep(wait)

        tweets = page.evaluate(_TIMELINE_JS) or []
        next_cursor = page.evaluate(_CURSOR_JS)
        ctx.close()
    except Exception as e:
        print(f"[playwright_client] list error ({list_id}): {e}", file=sys.stderr)
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass

    return tweets, next_cursor


def playwright_fetch_nitter_user_info(
    username: str,
    nitter: str = DEFAULT_NITTER,
    wait: float = 7,
) -> Dict[str, Any]:
    """
    Fetch user profile info from Nitter.
    Returns dict with display_name, bio, joined, tweets_count, followers, following.
    """
    url = f"https://{nitter}/{username}"
    pw = browser = None
    info: Dict[str, Any] = {"username": username}

    _USER_INFO_JS = """() => {
        const profile = document.querySelector(".profile-card");
        if (!profile) return {};
        const fullname = profile.querySelector(".profile-card-fullname");
        const bio = profile.querySelector(".profile-bio");
        const joined = profile.querySelector(".profile-joindate");
        const stats = {};
        for (const s of profile.querySelectorAll(".profile-stat")) {
            const label = s.querySelector(".profile-stat-header");
            const val = s.querySelector(".profile-stat-num");
            if (label && val) stats[label.textContent.trim()] = val.textContent.trim().replace(/,/g,"");
        }
        return {
            display_name: fullname ? fullname.textContent.trim() : "",
            bio: bio ? bio.textContent.trim() : "",
            joined: joined ? joined.textContent.trim() : "",
            tweets_count: parseInt(stats["Tweets"] || "0"),
            followers: parseInt(stats["Followers"] || "0"),
            following: parseInt(stats["Following"] || "0"),
        };
    }"""

    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser)
        page = ctx.new_page()
        _safe_goto(page, url)
        time.sleep(wait)
        result = page.evaluate(_USER_INFO_JS) or {}
        info.update(result)
        ctx.close()
    except Exception as e:
        print(f"[playwright_client] user_info error ({username}): {e}", file=sys.stderr)
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass

    return info


# ---------------------------------------------------------------------------
# camofox_client.py compatible API
# ---------------------------------------------------------------------------

def check_camofox(port: int = 9377) -> bool:
    """Always returns True – Playwright needs no separate server."""
    return True


def camofox_open_tab(url: str, session_key: str, port: int = 9377) -> Optional[str]:
    """Fetch *url* and store the text; return a synthetic tab_id."""
    if not url.startswith(("http://", "https://")):
        print(f"[playwright_client] rejected non-HTTP URL: {url[:60]}", file=sys.stderr)
        return None
    text = _fetch_url_text(url, wait=8)
    if text is None:
        return None
    tab_id = f"pw-{session_key}-{secrets.token_hex(4)}"
    _tab_store[tab_id] = text
    return tab_id


def camofox_snapshot(tab_id: str, port: int = 9377) -> Optional[str]:
    """Return stored text for *tab_id*."""
    return _tab_store.get(tab_id)


def camofox_close_tab(tab_id: str, port: int = 9377):
    """Free the stored page text."""
    _tab_store.pop(tab_id, None)


def camofox_fetch_page(url: str, session_key: str, wait: float = 8, port: int = 9377) -> Optional[str]:
    """Fetch *url* via Playwright; return visible text.  Primary entry point."""
    return _fetch_url_text(url, wait=wait)


# ---------------------------------------------------------------------------
# Search (Google / DuckDuckGo)
# ---------------------------------------------------------------------------

def camofox_search(
    query: str,
    num: int = 10,
    lang: str = "zh-CN",
    engine: str = "google",
    port: int = 9377,
) -> list:
    """
    Search via Playwright (Google or DuckDuckGo).

    Returns [{"title": ..., "url": ..., "snippet": ...}, ...]
    """
    encoded = urllib.parse.quote(query)
    pw = browser = None
    results = []

    try:
        pw, browser = _launch_browser()
        ctx = _new_context(browser, lang=lang)
        page = ctx.new_page()

        if engine == "duckduckgo":
            search_url = f"https://duckduckgo.com/?q={encoded}&kl={lang}&t=h_"
            _safe_goto(page, search_url)
            time.sleep(5)
            results = _extract_ddg_results(page, num)
        else:
            search_url = f"https://www.google.com/search?q={encoded}&hl={lang}&num={num}"
            _safe_goto(page, search_url)
            time.sleep(4)
            results = _extract_google_results(page, num)

        ctx.close()
    except Exception as e:
        print(f"[playwright_client] search error: {e}", file=sys.stderr)
    finally:
        try:
            browser and browser.close()
        except Exception:
            pass
        try:
            pw and pw.stop()
        except Exception:
            pass

    return results


def _extract_google_results(page, max_results: int = 10) -> list:
    results = []
    try:
        items = page.query_selector_all("div.g")
        if not items:
            items = page.query_selector_all("div[data-hveid]")
        for item in items:
            if len(results) >= max_results:
                break
            try:
                title_el = item.query_selector("h3")
                title = title_el.inner_text().strip() if title_el else ""
                link_el = item.query_selector("a[href]")
                href = link_el.get_attribute("href") if link_el else ""
                url = href if href and href.startswith("http") else ""
                snippet = ""
                for sel in ["div[data-sncf='1']", "div.IsZvec", "span.aCOpRe",
                             "div[style*='-webkit-line-clamp']"]:
                    sn_el = item.query_selector(sel)
                    if sn_el:
                        snippet = sn_el.inner_text().strip()
                        break
                if not snippet:
                    all_text = item.inner_text().strip()
                    snippet = all_text.replace(title, "").strip()[:200]
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
            except Exception:
                continue
    except Exception as e:
        print(f"[playwright_client] google parse: {e}", file=sys.stderr)
    return results


def _extract_ddg_results(page, max_results: int = 10) -> list:
    results = []
    try:
        items = page.query_selector_all("article[data-testid='result']")
        if not items:
            items = page.query_selector_all("li.PartialSearchResults-item")
        for item in items:
            if len(results) >= max_results:
                break
            try:
                title_el = item.query_selector("h2") or item.query_selector("h3")
                title = title_el.inner_text().strip() if title_el else ""
                link_el = item.query_selector("a[href]")
                href = link_el.get_attribute("href") if link_el else ""
                url = href if href and href.startswith("http") else ""
                snippet_el = (item.query_selector("div[data-result='snippet']") or
                              item.query_selector("span.result__snippet"))
                snippet = snippet_el.inner_text().strip() if snippet_el else ""
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})
            except Exception:
                continue
    except Exception as e:
        print(f"[playwright_client] ddg parse: {e}", file=sys.stderr)
    return results


# Legacy snapshot-based stubs (kept for import compatibility)
def _parse_duckduckgo_results(snapshot: str, max_results: int = 10) -> list:
    return []


def _parse_google_results(snapshot: str) -> list:
    return []


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys
    engine = "google"
    args = _sys.argv[1:]
    if "--engine" in args:
        idx = args.index("--engine")
        if idx + 1 < len(args):
            engine = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            args = args[:idx]
    query = " ".join(args) if args else "AI Agent"
    print(f"Searching ({engine}): {query}", file=_sys.stderr)
    results = camofox_search(query, engine=engine)
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['title']}")
        print(f"   {r['url']}")
        print(f"   {r['snippet'][:100]}...")
