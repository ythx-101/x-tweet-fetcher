#!/usr/bin/env python3
from __future__ import annotations
"""
arxiv_author_finder.py — 从 arxiv 论文自动发现作者 X/Twitter 账号

Pipeline（4层级联）：
  Layer 1: arxiv API → 提取作者名 + GitHub URL
  Layer 2: GitHub API → twitter_username / blog 字段
  Layer 3: Scholars on Twitter 本地数据集（需预下载）
  Layer 4: 搜索引擎兜底（SearxNG 或 DuckDuckGo）

Usage:
  python3 arxiv_author_finder.py --arxiv "https://arxiv.org/abs/2603.10165"
  python3 arxiv_author_finder.py --arxiv "2603.10165" --github-token $GITHUB_TOKEN
  python3 arxiv_author_finder.py --arxiv "2603.10165" --json
  python3 arxiv_author_finder.py --arxiv "2603.10165" --scholars-db /path/to/scholars.csv

环境变量：
  GITHUB_TOKEN — GitHub Personal Access Token（5000次/小时 vs 60次/小时）

可选依赖：
  duckduckgo_search — Layer 4 网络搜索的首选后端（pip install duckduckgo-search）。
                      未安装时自动回退至本地 SearxNG（127.0.0.1:8080）。
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ─── Config ───────────────────────────────────────────────────────────────────

ARXIV_API = "https://export.arxiv.org/api/query?id_list={arxiv_id}"
# GitHub HTML scraping (zero API token needed)

TWITTER_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([A-Za-z0-9_]{1,50})(?:[/?#]|$)'
)
GITHUB_REPO_URL_RE = re.compile(
    r'https?://github\.com/([A-Za-z0-9_\-\.]+)/([A-Za-z0-9_\-\.]+)'
)

REQUEST_DELAY = 0.5   # seconds between GitHub API calls


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def _get(url: str, headers: dict | None = None, timeout: int = 15) -> dict | str | None:
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "arxiv-author-finder/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw)
            except Exception:
                return raw
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"[WARN] GitHub rate limit hit. Set GITHUB_TOKEN for higher limits.", file=sys.stderr)
        elif e.code != 404:
            print(f"[WARN] HTTP {e.code} — {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] Request failed ({url[:60]}...): {e}", file=sys.stderr)
        return None


def _scrape_github_profile(username: str) -> dict | None:
    """Scrape GitHub profile HTML for name + twitter handle. No API needed."""
    html = _get(f"https://github.com/{username}", timeout=10)
    if not isinstance(html, str):
        return None
    result = {"login": username, "name": "", "twitter": None, "bio": ""}
    # Display name
    name_m = re.search(r'itemprop="name">([^<]+)<', html)
    if name_m:
        result["name"] = name_m.group(1).strip()
    # Twitter/X link
    tw_m = re.search(r'href="https://(?:twitter\.com|x\.com)/([\w.]+)"', html)
    if tw_m and tw_m.group(1).lower() not in ("home", "share", "intent", "i", "github"):
        result["twitter"] = tw_m.group(1)
    # Bio
    bio_m = re.search(r'<div[^>]*data-bio-text[^>]*>([^<]*)</div>', html)
    if bio_m:
        result["bio"] = bio_m.group(1).strip()
    return result


def _scrape_repo_contributors(owner: str, repo: str) -> list[str]:
    """Get contributor usernames from atom feed (no API needed)."""
    atom = _get(f"https://github.com/{owner}/{repo}/commits/HEAD.atom", timeout=10)
    if not isinstance(atom, str):
        atom = _get(f"https://github.com/{owner}/{repo}/commits/main.atom", timeout=10)
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


def _is_org(owner: str) -> bool:
    """Check if a GitHub owner is an org by scraping repo page."""
    html = _get(f"https://github.com/{owner}", timeout=10)
    if not isinstance(html, str):
        return False
    # Orgs have "Organizations" or org-specific markers
    return 'data-view-component="true" class="avatar-group-item"' in html or \
           'itemtype="http://schema.org/Organization"' in html


# ─── Layer 1: arxiv API ───────────────────────────────────────────────────────

def parse_arxiv_id(url_or_id: str) -> str:
    """Extract arxiv ID from URL or raw ID string."""
    url_or_id = url_or_id.strip().rstrip("/")
    # e.g. arxiv.org/abs/2603.10165 or arxiv.org/abs/cs/0301017
    m = re.search(r'arxiv\.org/(?:abs|pdf|html)/([^\s?#]+)', url_or_id)
    if m:
        return m.group(1)
    # Raw ID like "2603.10165" or "cs.AI/0301017"
    if re.match(r'[\w.]+/\d{7}|\d{4}\.\d{4,5}', url_or_id):
        return url_or_id
    raise ValueError(f"Cannot parse arxiv ID from: {url_or_id!r}")


def fetch_arxiv_paper(arxiv_id: str) -> dict:
    """
    Returns:
      {
        "id": str,
        "title": str,
        "authors": [str, ...],
        "abstract": str,
        "github_urls": [str, ...],   # extracted from abstract/comment
        "arxiv_url": str,
      }
    """
    url = ARXIV_API.format(arxiv_id=urllib.parse.quote(arxiv_id))
    raw = _get(url, timeout=20)
    if not isinstance(raw, str):
        raise RuntimeError(f"Failed to fetch arxiv metadata for {arxiv_id}")

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    try:
        # CPython's expat-based parser does not fetch external entities by default
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError(f"Malformed XML from arxiv API for {arxiv_id}: {exc}") from exc
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise RuntimeError(f"No arxiv entry found for ID: {arxiv_id}")

    title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
    abstract = (entry.findtext("atom:summary", "", ns) or "").strip()
    authors = [
        s for a in entry.findall("atom:author", ns)
        if (s := (a.findtext("atom:name", "", ns) or "").strip())
    ]

    # Extract GitHub URLs from abstract + any comment field
    combined_text = abstract
    comment_el = entry.find("arxiv:comment", ns)
    if comment_el is not None and comment_el.text:
        combined_text += " " + comment_el.text
    # Also check links
    for link in entry.findall("atom:link", ns):
        href = link.get("href", "")
        combined_text += " " + href

    github_urls = list(dict.fromkeys(
        m.group(0).rstrip(".,;)'\"")
        for m in GITHUB_REPO_URL_RE.finditer(combined_text)
    ))

    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"

    return {
        "id": arxiv_id,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "github_urls": github_urls,
        "arxiv_url": arxiv_url,
    }


def search_github_for_paper(title: str, token: str | None = None) -> list[str]:
    """Try to find a GitHub repo URL by searching for the paper title."""
    query = urllib.parse.quote(f'"{title[:80]}"')
    url = f"https://github.com/search?q={query}&type=repositories"
    html = _get(url, timeout=15)
    repos = []
    if isinstance(html, str):
        repos = re.findall(r'href="(/[^/]+/[^/"]+)"[^>]*data-testid="results-list"', html)
        if not repos:
            repos = re.findall(r'href="/([^/]+/[^/"]+)" data-hydro-click', html)

    # Camofox fallback if direct scraping fails (429 or no results)
    if not repos:
        try:
            from camofox_client import check_camofox, camofox_search
            if check_camofox():
                results = camofox_search(f'{title[:80]} github.com', num=5, engine="google")
                for r in results:
                    m = re.search(r'github\.com/([^/]+/[^/\s?"]+)', r.get("url", ""))
                    if m:
                        repos.append(m.group(0))
        except Exception:
            pass

    return [r if r.startswith('http') else
            f"https://{r}" if 'github.com' in r else
            f"https://github.com/{r}"
            for r in [r.lstrip('/') for r in repos[:3]]]


# ─── Layer 2: GitHub API ──────────────────────────────────────────────────────

def extract_twitter_from_profile(profile: dict) -> str | None:
    """Extract twitter handle from scraped profile dict."""
    return profile.get("twitter") if profile else None


def find_twitter_via_repo(repo_url: str, authors: list[str], token: str | None = None) -> dict[str, str]:
    """
    Given a GitHub repo URL, find twitter handles for authors.
    Uses HTML scraping — no API token needed.
    Returns {author_name: twitter_handle}
    """
    m = GITHUB_REPO_URL_RE.match(repo_url.rstrip("/"))
    if not m:
        return {}
    owner, repo = m.group(1), m.group(2)
    results: dict[str, str] = {}

    # 1. Check repo owner's profile
    owner_profile = _scrape_github_profile(owner)
    if owner_profile:
        handle = extract_twitter_from_profile(owner_profile)
        if handle:
            matched = _match_github_to_author(owner_profile, authors)
            if matched:
                results[matched] = handle

    # 2. If owner is an org, try to match org twitter by handle → author name
    if _is_org(owner):
        org_handle = owner_profile.get("twitter") if owner_profile else None
        if org_handle:
            # Try matching handle to an author name (e.g. @LingYang_PU → Ling Yang)
            matched = _match_handle_to_author(org_handle, authors)
            if matched:
                results.setdefault(matched, org_handle)

    # 3. Check contributors from atom feed
    contributors = _scrape_repo_contributors(owner, repo)
    for login in contributors[:8]:
        if login == owner:
            continue  # Already checked
        time.sleep(REQUEST_DELAY)
        profile = _scrape_github_profile(login)
        if not profile:
            continue
        handle = extract_twitter_from_profile(profile)
        if handle:
            matched = _match_github_to_author(profile, authors)
            if matched and matched not in results:
                results[matched] = handle

    return results


def _match_handle_to_author(handle: str, authors: list[str]) -> str | None:
    """Try to match a Twitter handle to one of the paper authors by name parts."""
    h = handle.lower().replace("_", "").replace("-", "")
    for author in authors:
        parts = _normalize_name(author).split()
        if len(parts) >= 2:
            # Check if handle contains both first and last name parts
            if all(p in h for p in parts):
                return author
            # Check lastname + firstname initial
            last = parts[-1]
            if len(last) >= 3 and last in h:
                return author
    return None


def _normalize_name(name: str) -> str:
    """Lowercase, remove punctuation, collapse spaces."""
    return re.sub(r'[^a-z ]', '', name.lower()).strip()


def _match_github_to_author(profile: dict, authors: list[str]) -> str | None:
    """
    Try to match a GitHub user to one of the paper authors.
    Accepts both API response dicts and scraped profile dicts.
    Returns matched author name or None.
    """
    gh_name = _normalize_name(profile.get("name") or "")
    gh_login = _normalize_name(profile.get("login") or "")
    gh_bio = (profile.get("bio") or "").lower()

    best_match = None
    best_score = 0

    for author in authors:
        norm_author = _normalize_name(author)
        if not norm_author:
            continue

        # Exact name match
        if gh_name == norm_author:
            return author

        # Parts match: all parts of author name appear in github name
        author_parts = norm_author.split()
        if len(author_parts) >= 2:
            if all(p in gh_name for p in author_parts):
                return author
            # Last name + first initial
            last = author_parts[-1]
            first_initial = author_parts[0][0] if author_parts[0] else ""
            if last in gh_name and first_initial and first_initial in gh_name:
                score = len(last) + 1
                if score > best_score:
                    best_score = score
                    best_match = author

        # Login contains author last name
        if len(author_parts) >= 1:
            last = author_parts[-1]
            if len(last) >= 4 and last in gh_login:
                score = len(last)
                if score > best_score:
                    best_score = score
                    best_match = author

    return best_match if best_score >= 4 else None


def search_github_users_for_author(author_name: str, token: str | None = None) -> str | None:
    """
    Find an author's Twitter via GitHub user search (HTML scraping).
    Direct search — no guessing, no wasted requests.
    Returns twitter handle or None.
    """
    parts = author_name.strip().split()
    if len(parts) < 2:
        return None

    query = urllib.parse.quote(author_name)
    url = f"https://github.com/search?q={query}&type=users"
    html = _get(url, timeout=15)
    if not isinstance(html, str) or len(html) < 1000:
        return None

    # Extract usernames from search results
    logins = re.findall(r'href="/([a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,37})"[^>]*data-', html)
    if not logins:
        logins = re.findall(r'class="[^"]*"[^>]*href="/([a-zA-Z0-9_-]+)"', html)

    skip = {"search", "features", "pricing", "login", "signup", "orgs", "topics", "settings", "explore"}
    norm_author = _normalize_name(author_name)
    author_parts = norm_author.split()

    seen = set()
    for login in logins:
        if login in seen or login.lower() in skip:
            continue
        seen.add(login)
        profile = _scrape_github_profile(login)
        if not profile or not profile.get("name"):
            continue
        gh_name = _normalize_name(profile["name"])
        if len(author_parts) >= 2 and all(p in gh_name for p in author_parts):
            handle = extract_twitter_from_profile(profile)
            if handle:
                return handle
        if len(seen) >= 3:  # Max 3 profiles per search
            break
    return None


# ─── Layer 3: Scholars on Twitter dataset ─────────────────────────────────────

def load_scholars_dataset(csv_path: str) -> dict[str, str]:
    """
    Load Scholars on Twitter dataset (CSV).
    Expected columns: author_name (or full_name), twitter_handle (or screen_name)
    Returns {normalized_name: handle}
    """
    import csv
    mapping = {}
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            # Build column name mapping: original_header → lowercase for matching
            orig_headers = list(reader.fieldnames or [])
            name_col = next((h for h in orig_headers if "name" in h.lower()), None)
            handle_col = next(
                (h for h in orig_headers if any(k in h.lower() for k in ("twitter", "screen", "handle"))),
                None
            )
            if not name_col or not handle_col:
                print(f"[WARN] Cannot identify name/handle columns in {csv_path}. Headers: {orig_headers}", file=sys.stderr)
                return {}
            for row in reader:
                name = row.get(name_col, "").strip()
                handle = row.get(handle_col, "").strip().lstrip("@")
                if name and handle:
                    mapping[_normalize_name(name)] = handle
    except Exception as e:
        print(f"[WARN] Failed to load scholars dataset: {e}", file=sys.stderr)
    return mapping


def lookup_scholars(author: str, dataset: dict[str, str]) -> str | None:
    """Fuzzy match author name in scholars dataset."""
    norm = _normalize_name(author)
    if norm in dataset:
        return dataset[norm]

    # Try lastname, firstname → firstname lastname
    parts = norm.split()
    if len(parts) == 2:
        reversed_name = f"{parts[1]} {parts[0]}"
        if reversed_name in dataset:
            return dataset[reversed_name]

    # Partial match: last name + first initial
    if len(parts) >= 2:
        last = parts[-1]
        first_init = parts[0][0] if parts[0] else ""
        for key, handle in dataset.items():
            key_parts = key.split()
            if len(key_parts) >= 2 and key_parts[-1] == last:
                if first_init and key_parts[0].startswith(first_init):
                    return handle

    return None


# ─── Layer 4: Search fallback ─────────────────────────────────────────────────

def search_twitter_for_author(author_name: str, affiliation: str = "") -> str | None:
    """
    Use DuckDuckGo or local SearxNG to search for an author's Twitter.
    Returns twitter handle or None.
    """
    queries = [
        f'"{author_name}" site:x.com OR site:twitter.com',
        f'"{author_name}" twitter',
    ]
    if affiliation:
        queries.insert(0, f'"{author_name}" "{affiliation}" twitter')

    for query in queries:
        results = _search_web(query, max_results=5)
        for r in results:
            url = r.get("url", r.get("href", ""))
            snippet = r.get("snippet", r.get("body", ""))
            for text in [url, snippet]:
                m = TWITTER_URL_RE.search(text)
                if m:
                    handle = m.group(1)
                    if handle.lower() not in ("home", "share", "intent", "i", "search"):
                        # Basic name plausibility check
                        if _name_plausibly_matches_handle(author_name, handle):
                            return handle
        time.sleep(0.3)

    return None


def _name_plausibly_matches_handle(author_name: str, handle: str) -> bool:
    """Very loose check: last name appears in handle (case insensitive)."""
    parts = author_name.lower().split()
    if not parts:
        return True
    last = parts[-1]
    if len(last) < 4:
        return True  # Too short to verify
    return last in handle.lower()


_brave_disabled = False  # module-level flag to avoid repeated 429s


def _brave_scrape_twitter(query: str) -> list[str]:
    """Scrape Brave Search HTML for Twitter/X handles. Zero API key needed."""
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
        skip = {'home', 'share', 'intent', 'i', 'search', 'hashtag', 'status',
                'explore', 'settings', 'login', 'signup', 'tos', 'privacy'}
        seen = set()
        clean = []
        for h in handles:
            h = h.lstrip('@')
            if h.lower() not in skip and h not in seen and not h.isdigit() and len(h) > 1:
                seen.add(h)
                clean.append(h)
        return clean
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _brave_disabled = True  # Don't retry Brave this session
        return []
    except Exception:
        return []


def _search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search chain: Brave HTML scrape → SearxNG → DuckDuckGo."""
    # 1. Brave HTML scraping (zero deps, zero API key)
    handles = _brave_scrape_twitter(query)
    if handles:
        return [{"url": f"https://x.com/{h}", "snippet": ""} for h in handles[:max_results]]

    # 2. SearxNG (local instance, if available)
    searxng_urls = ["http://127.0.0.1:8080", "http://localhost:8080"]
    for base in searxng_urls:
        try:
            url = f"{base}/search?q={urllib.parse.quote(query)}&format=json&categories=general"
            raw = _get(url, timeout=10)
            if isinstance(raw, dict) and raw.get("results"):
                return [
                    {"url": r.get("url", ""), "snippet": r.get("content", "")}
                    for r in raw["results"][:max_results]
                ]
        except Exception:
            pass

    # 3. DuckDuckGo (pip optional)
    try:
        from duckduckgo_search import DDGS
        import warnings
        warnings.filterwarnings("ignore")
        results = DDGS().text(query, max_results=max_results)
        if results:
            return results
    except Exception:
        pass

    # 4. Camofox browser (fingerprint browser on Mac — zero 429, real user)
    try:
        from camofox_client import check_camofox, camofox_search
        if check_camofox():
            results = camofox_search(query, num=max_results, engine="google")
            if results:
                return results
    except Exception:
        pass

    return []


# ─── Main finder ──────────────────────────────────────────────────────────────

class ArxivAuthorFinder:
    def __init__(
        self,
        github_token: str | None = None,
        scholars_db: str | None = None,
        skip_search: bool = False,
        verbose: bool = False,
    ):
        self.token = github_token or os.environ.get("GITHUB_TOKEN")  # kept for compat, not used by scraping
        self.scholars: dict[str, str] = {}
        if scholars_db and os.path.exists(scholars_db):
            self.scholars = load_scholars_dataset(scholars_db)
            if verbose:
                print(f"[INFO] Loaded {len(self.scholars)} entries from scholars dataset", file=sys.stderr)
        self.skip_search = skip_search
        self.verbose = verbose

    def find(self, arxiv_url_or_id: str) -> dict:
        """
        Returns:
        {
          "paper": { title, authors, arxiv_url, github_urls },
          "results": { author_name: { "handle": str|None, "source": str, "confidence": str } },
          "summary": { found: int, total: int, coverage_pct: float }
        }
        """
        # Layer 0: Parse paper
        arxiv_id = parse_arxiv_id(arxiv_url_or_id)
        if self.verbose:
            print(f"[INFO] Fetching arxiv:{arxiv_id} ...", file=sys.stderr)
        paper = fetch_arxiv_paper(arxiv_id)

        authors = paper["authors"]
        github_urls = paper["github_urls"]

        if self.verbose:
            print(f"[INFO] Paper: {paper['title'][:60]}", file=sys.stderr)
            print(f"[INFO] Authors ({len(authors)}): {', '.join(authors)}", file=sys.stderr)
            print(f"[INFO] GitHub URLs found: {github_urls}", file=sys.stderr)

        results: dict[str, dict] = {a: {"handle": None, "source": None, "confidence": None} for a in authors}

        # Layer 1: GitHub via repo URLs
        if github_urls:
            for repo_url in github_urls:
                found = find_twitter_via_repo(repo_url, authors, self.token)
                for author, handle in found.items():
                    if results[author]["handle"] is None:
                        results[author] = {"handle": handle, "source": "github_repo", "confidence": "high"}
                        if self.verbose:
                            print(f"  [GitHub] {author} → @{handle}", file=sys.stderr)
        else:
            # Try GitHub search for paper
            if self.verbose:
                print("[INFO] No GitHub URL in paper, trying search...", file=sys.stderr)
            found_repos = search_github_for_paper(paper["title"], self.token)
            for repo_url in found_repos[:2]:
                found = find_twitter_via_repo(repo_url, authors, self.token)
                for author, handle in found.items():
                    if results[author]["handle"] is None:
                        results[author] = {"handle": handle, "source": "github_search", "confidence": "medium"}
                        if self.verbose:
                            print(f"  [GitHub/search] {author} → @{handle}", file=sys.stderr)

        # Layer 1b: GitHub user search for still-missing authors (cap at 8 to bound runtime)
        missing = [a for a, v in results.items() if v["handle"] is None]
        for author in missing[:8]:
            time.sleep(5)  # 5s delay bypasses GitHub search 429
            handle = search_github_users_for_author(author, self.token)
            if handle:
                results[author] = {"handle": handle, "source": "github_user_search", "confidence": "medium"}
                if self.verbose:
                    print(f"  [GitHub/user] {author} → @{handle}", file=sys.stderr)

        # Layer 2: Scholars on Twitter dataset
        missing = [a for a, v in results.items() if v["handle"] is None]
        for author in missing:
            handle = lookup_scholars(author, self.scholars)
            if handle:
                results[author] = {"handle": handle, "source": "scholars_dataset", "confidence": "high"}
                if self.verbose:
                    print(f"  [Scholars] {author} → @{handle}", file=sys.stderr)

        # Layer 3: Search fallback
        if not self.skip_search:
            missing = [a for a, v in results.items() if v["handle"] is None]
            for author in missing:
                handle = search_twitter_for_author(author)
                if handle:
                    results[author] = {"handle": handle, "source": "web_search", "confidence": "low"}
                    if self.verbose:
                        print(f"  [Search] {author} → @{handle}", file=sys.stderr)

        # Summary
        found_count = sum(1 for v in results.values() if v["handle"])
        total = len(authors)
        coverage = found_count / total * 100 if total > 0 else 0

        return {
            "paper": {
                "title": paper["title"],
                "arxiv_id": arxiv_id,
                "arxiv_url": paper["arxiv_url"],
                "authors": authors,
                "github_urls": github_urls,
            },
            "results": results,
            "summary": {
                "found": found_count,
                "total": total,
                "coverage_pct": round(coverage, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        }


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Discover X/Twitter accounts of arxiv paper authors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 arxiv_author_finder.py --arxiv 2603.10165
  python3 arxiv_author_finder.py --arxiv https://arxiv.org/abs/1706.03762 --json
  python3 arxiv_author_finder.py --arxiv 2603.10165 --github-token $GITHUB_TOKEN --verbose
  python3 arxiv_author_finder.py --arxiv 2603.10165 --scholars-db scholars.csv
        """
    )
    parser.add_argument("--arxiv", "-a", required=True, help="arxiv ID or URL (e.g. 2603.10165)")
    parser.add_argument("--github-token", "-t", help="GitHub Personal Access Token (or set GITHUB_TOKEN env)")
    parser.add_argument("--scholars-db", "-s", help="Path to Scholars on Twitter CSV dataset")
    parser.add_argument("--skip-search", action="store_true", help="Skip web search fallback (faster, less coverage)")
    parser.add_argument("--json", "-j", action="store_true", help="Output raw JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show progress")
    args = parser.parse_args()

    finder = ArxivAuthorFinder(
        github_token=args.github_token,
        scholars_db=args.scholars_db,
        skip_search=args.skip_search,
        verbose=args.verbose,
    )

    try:
        output = finder.find(args.arxiv)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # Human-readable output
    paper = output["paper"]
    results = output["results"]
    summary = output["summary"]

    print(f"\n  Paper: {paper['title']}")
    print(f"  arxiv: {paper['arxiv_url']}")
    if paper["github_urls"]:
        print(f"  GitHub: {', '.join(paper['github_urls'])}")
    print()
    print(f"  {'Author':<30} {'Twitter':<25} {'Source':<20} {'Confidence'}")
    print("  " + "─" * 85)
    for author, info in results.items():
        handle = f"@{info['handle']}" if info["handle"] else "—"
        source = info["source"] or ""
        conf = info["confidence"] or ""
        print(f"  {author:<30} {handle:<25} {source:<20} {conf}")
    print()
    print(f"  Coverage: {summary['found']}/{summary['total']} authors ({summary['coverage_pct']}%)")
    print()


if __name__ == "__main__":
    main()
