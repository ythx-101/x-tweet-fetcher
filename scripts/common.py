#!/usr/bin/env python3
from __future__ import annotations
"""
Shared utilities for x-tweet-fetcher scripts.

Provides: HTTP helpers, ArXiv parsing, GitHub scraping, name matching, web search.
All functions are stateless and can be imported by any script.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from config import (
    ARXIV_API, SEARXNG_URL, GITHUB_TOKEN, REQUEST_DELAY,
)

# ─── Regex patterns ──────────────────────────────────────────────────────────

TWITTER_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,50})(?:[/?#]|$)'
)
GITHUB_REPO_RE = re.compile(
    r'https?://github\.com/([A-Za-z0-9_\-\.]+)/([A-Za-z0-9_\-\.]+)'
)
ARXIV_ID_RE = re.compile(r'(\d{4}\.\d{4,5}(?:v\d+)?)')
ARXIV_URL_RE = re.compile(r'arxiv\.org/(?:abs|pdf|html)/([^\s?#]+?)(?:\.pdf)?(?:[?#]|$)')

# Twitter handles that are not real users
TWITTER_SKIP_HANDLES = frozenset({
    "home", "share", "intent", "i", "search", "hashtag",
    "status", "explore", "settings", "login", "signup",
    "tos", "privacy", "github",
})


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def http_get(url: str, headers: dict | None = None, timeout: int = 15) -> dict | str | None:
    """GET request. Returns parsed JSON (dict) or raw string, or None on error."""
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "x-tweet-fetcher/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except Exception:
                return raw
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"[WARN] Rate limited (403) — {url[:80]}", file=sys.stderr)
        elif e.code == 429:
            print(f"[WARN] Rate limited (429) — {url[:80]}", file=sys.stderr)
        elif e.code != 404:
            print(f"[WARN] HTTP {e.code} — {url[:80]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] Request failed ({url[:60]}...): {e}", file=sys.stderr)
        return None


# ─── ArXiv helpers ────────────────────────────────────────────────────────────

def strip_arxiv_version(arxiv_id: str) -> str:
    """Strip version suffix (e.g. '1706.03762v5' -> '1706.03762')."""
    return re.sub(r'v\d+$', '', arxiv_id)


def parse_arxiv_id(text: str) -> str | None:
    """Extract arxiv ID from URL or raw text. Returns None if not found."""
    text = text.strip().rstrip("/")
    m = ARXIV_URL_RE.search(text)
    if m:
        return strip_arxiv_version(m.group(1))
    m = ARXIV_ID_RE.search(text)
    if m:
        return strip_arxiv_version(m.group(1))
    # Support raw ID like "cs.AI/0301017"
    if re.match(r'[\w.]+/\d{7}', text):
        return text
    return None


def fetch_arxiv_metadata(arxiv_id: str) -> dict | None:
    """
    Fetch paper metadata from ArXiv API.
    Returns {arxiv_id, title, authors, abstract, github_urls} or None.
    """
    clean_id = strip_arxiv_version(arxiv_id)
    url = ARXIV_API.format(arxiv_id=urllib.parse.quote(clean_id))
    raw = http_get(url, timeout=20)
    if not isinstance(raw, str):
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None

    title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
    authors = [
        s for a in entry.findall("atom:author", ns)
        if (s := (a.findtext("atom:name", "", ns) or "").strip())
    ]
    abstract = (entry.findtext("atom:summary", "", ns) or "").strip()

    # Extract GitHub URLs from abstract + comment + links
    combined = abstract
    comment_el = entry.find("arxiv:comment", ns)
    if comment_el is not None and comment_el.text:
        combined += " " + comment_el.text
    for link in entry.findall("atom:link", ns):
        combined += " " + link.get("href", "")
    github_urls = list(dict.fromkeys(
        m.group(0).rstrip(".,;)'\"") for m in GITHUB_REPO_RE.finditer(combined)
    ))

    return {
        "arxiv_id": clean_id,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "github_urls": github_urls,
    }


# ─── GitHub helpers (REST API when token available, HTML scraping as fallback)

def _github_api_get(endpoint: str) -> dict | None:
    """Call GitHub REST API. Returns parsed JSON or None."""
    if not GITHUB_TOKEN:
        return None
    url = f"https://api.github.com{endpoint}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    result = http_get(url, headers=headers, timeout=10)
    return result if isinstance(result, dict) else None


def scrape_github_profile(username: str) -> dict | None:
    """Get GitHub profile (name + twitter). Uses REST API if token available, HTML scraping as fallback."""
    # Try REST API first (stable, won't break on HTML changes)
    api_data = _github_api_get(f"/users/{username}")
    if api_data and api_data.get("login"):
        twitter = api_data.get("twitter_username")
        if twitter and twitter.lower() in TWITTER_SKIP_HANDLES:
            twitter = None
        return {
            "login": api_data.get("login", username),
            "name": api_data.get("name") or "",
            "twitter": twitter,
            "bio": api_data.get("bio") or "",
        }

    # Fallback: HTML scraping (zero token needed)
    html = http_get(f"https://github.com/{username}", timeout=10)
    if not isinstance(html, str):
        return None
    result = {"login": username, "name": "", "twitter": None, "bio": ""}
    name_m = re.search(r'itemprop="name">([^<]+)<', html)
    if name_m:
        result["name"] = name_m.group(1).strip()
    tw_m = re.search(r'href="https://(?:twitter\.com|x\.com)/([\w.]+)"', html)
    if tw_m and tw_m.group(1).lower() not in TWITTER_SKIP_HANDLES:
        result["twitter"] = tw_m.group(1)
    bio_m = re.search(r'<div[^>]*data-bio-text[^>]*>([^<]*)</div>', html)
    if bio_m:
        result["bio"] = bio_m.group(1).strip()
    return result


def scrape_repo_contributors(owner: str, repo: str) -> list[str]:
    """Get contributor usernames. Uses REST API if token available, atom feed as fallback."""
    # Try REST API first
    api_data = _github_api_get(f"/repos/{owner}/{repo}/contributors?per_page=10")
    if isinstance(api_data, list) and api_data:
        return [c.get("login", "") for c in api_data if c.get("login")][:10]

    # Fallback: atom feed (zero token needed)
    atom = http_get(f"https://github.com/{owner}/{repo}/commits/HEAD.atom", timeout=10)
    if not isinstance(atom, str):
        atom = http_get(f"https://github.com/{owner}/{repo}/commits/main.atom", timeout=10)
    if not isinstance(atom, str):
        return []
    names = re.findall(r'<name>([^<]+)</name>', atom)
    seen = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique[:10]


def is_github_org(owner: str) -> bool:
    """Check if a GitHub owner is an org."""
    # Try REST API first
    api_data = _github_api_get(f"/users/{owner}")
    if api_data and api_data.get("type"):
        return api_data["type"] == "Organization"

    # Fallback: HTML scraping
    html = http_get(f"https://github.com/{owner}", timeout=10)
    if not isinstance(html, str):
        return False
    return 'data-view-component="true" class="avatar-group-item"' in html or \
           'itemtype="http://schema.org/Organization"' in html


def extract_twitter_from_profile(profile: dict) -> str | None:
    """Extract twitter handle from scraped profile dict."""
    return profile.get("twitter") if profile else None


def verify_twitter_handle(handle: str, expected_name: str) -> bool:
    """
    Verify a Twitter handle actually belongs to the expected person.
    Uses FxTwitter API to fetch real profile and check name/bio match.
    Returns False if the handle is clearly wrong (spam, unrelated person).
    """
    url = f"https://api.fxtwitter.com/{handle}"
    data = http_get(url, timeout=10)
    if not isinstance(data, dict):
        return True  # Can't verify, give benefit of doubt

    user = data.get("user", data)
    tw_name = (user.get("name") or "").strip()
    tw_bio = (user.get("description") or "").strip()
    followers = user.get("followers", user.get("followers_count", 0)) or 0

    # Red flag: very few followers and no bio
    if followers < 20 and not tw_bio:
        return False

    expected_parts = normalize_name(expected_name).split()
    tw_name_parts = normalize_name(tw_name).split()
    tw_combined = normalize_name(tw_name) + " " + normalize_name(tw_bio)

    if not expected_parts or len(expected_parts) < 2:
        return True

    # Require: last name must match in Twitter display name or bio
    last_name = expected_parts[-1]
    first_name = expected_parts[0]

    if len(last_name) >= 3 and last_name not in tw_combined:
        return False

    # If last name matches, also need first name (or initial) to match
    if len(first_name) >= 3 and first_name not in tw_combined:
        # Allow first initial match
        if not any(p.startswith(first_name[0]) for p in tw_name_parts):
            return False

    return True


# ─── Name matching ────────────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Lowercase, remove punctuation, collapse spaces."""
    return re.sub(r'[^a-z ]', '', name.lower()).strip()


def match_name_parts(author_parts: list[str], target_name: str) -> bool:
    """
    Match author name parts against target using word boundaries.
    Prevents false positives like "Li Wei" matching "Weilin Chen".

    Each author name part must match a complete word in target.
    For multi-part names: all parts must match as complete words (>= 2 parts).
    For single-part names: the part must be >= 4 chars and match exactly.
    """
    target_parts = normalize_name(target_name).split()
    if not target_parts:
        return False

    matched = 0
    for ap in author_parts:
        if any(ap == tp for tp in target_parts):
            matched += 1

    if len(author_parts) == 1:
        # Single name (e.g. mononym): require exact word match + long enough to avoid false positives
        return matched == 1 and len(author_parts[0]) >= 4

    # Multi-part: all parts must match as complete words
    return matched == len(author_parts) and matched >= 2


def match_github_to_author(profile: dict, authors: list[str]) -> str | None:
    """
    Match a GitHub user profile to one of the paper authors.
    Returns matched author name or None.
    """
    gh_name = normalize_name(profile.get("name") or "")
    gh_login = normalize_name(profile.get("login") or "")

    best_match = None
    best_score = 0

    for author in authors:
        norm_author = normalize_name(author)
        if not norm_author:
            continue

        # Exact name match
        if gh_name == norm_author:
            return author

        author_parts = norm_author.split()
        if len(author_parts) >= 2:
            # Word-boundary match (prevents "Li Wei" matching "Weilin Chen")
            if match_name_parts(author_parts, gh_name):
                return author

            # Last name + first initial (only for long last names)
            last = author_parts[-1]
            first_initial = author_parts[0][0] if author_parts[0] else ""
            if len(last) >= 4 and last in gh_name.split() and first_initial:
                if any(tp.startswith(first_initial) for tp in gh_name.split()):
                    score = len(last) + 1
                    if score > best_score:
                        best_score = score
                        best_match = author

        # Login contains author last name (exact word match)
        if len(author_parts) >= 1:
            last = author_parts[-1]
            if len(last) >= 4 and last in gh_login.split():
                score = len(last)
                if score > best_score:
                    best_score = score
                    best_match = author

    return best_match if best_score >= 4 else None


def match_handle_to_author(handle: str, authors: list[str]) -> str | None:
    """Match a Twitter handle to one of the paper authors by name parts."""
    h = handle.lower().replace("_", "").replace("-", "")
    for author in authors:
        parts = normalize_name(author).split()
        if len(parts) >= 2:
            # For handle matching, substring is OK (handles are concatenated)
            # but require last name (>= 3 chars) to be present
            last = parts[-1]
            if len(last) >= 3 and last in h:
                # Also need at least first name initial
                if parts[0][0] in h:
                    return author
    return None


# ─── Web search chain ────────────────────────────────────────────────────────

_brave_disabled = False


def _brave_scrape_twitter(query: str) -> list[str]:
    """Scrape Brave Search HTML for Twitter/X handles."""
    global _brave_disabled
    if _brave_disabled:
        return []
    try:
        url = f'https://search.brave.com/search?q={urllib.parse.quote(query)}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html',
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        handles = re.findall(r'(?:twitter\.com|x\.com)/(@?[A-Za-z0-9_]+)', html)
        seen = set()
        clean = []
        for h in handles:
            h = h.lstrip('@')
            if h.lower() not in TWITTER_SKIP_HANDLES and h not in seen and not h.isdigit() and len(h) > 1:
                seen.add(h)
                clean.append(h)
        return clean
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _brave_disabled = True
        return []
    except Exception:
        return []


def search_web(query: str, max_results: int = 5, fresh: bool = False) -> list[dict]:
    """
    Search chain: SearxNG → Brave HTML → DuckDuckGo → Camofox.
    Returns list of {url, title, snippet} dicts.
    """
    # 1. SearxNG (local instance, zero-cost, best for fresh results)
    try:
        params = {
            "q": query, "format": "json", "categories": "general",
            "engines": "google,duckduckgo,brave,bing", "pageno": 1,
        }
        if fresh:
            params["time_range"] = "week"
        url = f"{SEARXNG_URL}?{urllib.parse.urlencode(params)}"
        raw = http_get(url, timeout=10)
        if isinstance(raw, dict) and raw.get("results"):
            return [
                {"url": r.get("url", ""), "title": r.get("title", ""),
                 "snippet": r.get("content", ""), "publishedDate": r.get("publishedDate", "")}
                for r in raw["results"][:max_results]
            ]
    except Exception:
        pass

    # 2. Brave HTML scraping (zero deps, but gets 429'd)
    handles = _brave_scrape_twitter(query)
    if handles:
        return [{"url": f"https://x.com/{h}", "title": "", "snippet": ""} for h in handles[:max_results]]

    # 3. DuckDuckGo (pip optional)
    try:
        from duckduckgo_search import DDGS
        import warnings
        warnings.filterwarnings("ignore")
        results = DDGS().text(query, max_results=max_results)
        if results:
            return [{"url": r.get("href", ""), "title": r.get("title", ""), "snippet": r.get("body", "")} for r in results]
    except Exception:
        pass

    # 4. Camofox browser (fingerprint browser, zero 429)
    try:
        from camofox_client import check_camofox, camofox_search
        if check_camofox():
            results = camofox_search(query, num=max_results, engine="google")
            if results:
                return results[:max_results]
    except Exception:
        pass

    return []


if __name__ == '__main__':
    # Quick self-test
    print("=== ArXiv parse test ===")
    assert parse_arxiv_id("https://arxiv.org/abs/2603.10165") == "2603.10165"
    assert parse_arxiv_id("1706.03762v5") == "1706.03762"
    print("  OK")

    print("=== Name matching test ===")
    assert match_name_parts(["li", "wei"], "Li Wei") is True
    assert match_name_parts(["li", "wei"], "Weilin Chen") is False
    assert match_name_parts(["ashish", "vaswani"], "Ashish Vaswani") is True
    # Single-name matching: >= 4 chars OK, < 4 chars rejected
    assert match_name_parts(["hinton"], "Geoffrey Hinton") is True
    assert match_name_parts(["li"], "Li Wei") is False  # too short, ambiguous
    print("  OK")

    print("=== All tests passed ===")
