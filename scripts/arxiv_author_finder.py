#!/usr/bin/env python3
from __future__ import annotations
"""
arxiv_author_finder.py — 从 arxiv 论文自动发现作者 X/Twitter 账号

Pipeline（4层级联）：
  Layer 1: arxiv API → 提取作者名 + GitHub URL
  Layer 2: GitHub HTML scraping → twitter_username (zero API token)
  Layer 3: Scholars on Twitter 本地数据集（需预下载）
  Layer 4: 搜索引擎兜底（SearxNG → Brave → DuckDuckGo → Camofox）

Usage:
  python3 arxiv_author_finder.py --arxiv "https://arxiv.org/abs/2603.10165"
  python3 arxiv_author_finder.py --arxiv "2603.10165" --json
  python3 arxiv_author_finder.py --arxiv "2603.10165" --scholars-db /path/to/scholars.csv

环境变量：
  GITHUB_TOKEN — GitHub Personal Access Token（5000次/小时 vs 60次/小时）

可选依赖：
  duckduckgo_search — Layer 4 网络搜索的首选后端（pip install duckduckgo-search）。
                      未安装时自动回退至本地 SearxNG。
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

from common import (
    http_get, parse_arxiv_id, fetch_arxiv_metadata,
    scrape_github_profile, scrape_repo_contributors, is_github_org,
    extract_twitter_from_profile, verify_twitter_handle,
    normalize_name, match_name_parts,
    match_github_to_author, match_handle_to_author,
    search_web, GITHUB_REPO_RE, TWITTER_URL_RE, TWITTER_SKIP_HANDLES,
)
from config import REQUEST_DELAY


# ─── Layer 1: GitHub search for paper ────────────────────────────────────────

def search_github_for_paper(title: str) -> list[str]:
    """Try to find a GitHub repo URL by searching for the paper title."""
    query = urllib.parse.quote(f'"{title[:80]}"')
    url = f"https://github.com/search?q={query}&type=repositories"
    html = http_get(url, timeout=15)
    repos = []
    if isinstance(html, str):
        repos = re.findall(r'href="(/[^/]+/[^/"]+)"[^>]*data-testid="results-list"', html)
        if not repos:
            repos = re.findall(r'href="/([^/]+/[^/"]+)" data-hydro-click', html)

    # Camofox fallback
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


# ─── Layer 2: GitHub → Twitter ───────────────────────────────────────────────

def find_twitter_via_repo(repo_url: str, authors: list[str]) -> dict[str, str]:
    """Find twitter handles for authors via GitHub repo scraping."""
    m = GITHUB_REPO_RE.match(repo_url.rstrip("/"))
    if not m:
        return {}
    owner, repo = m.group(1), m.group(2)
    results: dict[str, str] = {}

    # 1. Check repo owner's profile
    owner_profile = scrape_github_profile(owner)
    if owner_profile:
        handle = extract_twitter_from_profile(owner_profile)
        if handle:
            matched = match_github_to_author(owner_profile, authors)
            if matched:
                results[matched] = handle

    # 2. If owner is an org, try to match org twitter by handle → author name
    if is_github_org(owner):
        org_handle = owner_profile.get("twitter") if owner_profile else None
        if org_handle:
            matched = match_handle_to_author(org_handle, authors)
            if matched:
                results.setdefault(matched, org_handle)

    # 3. Check contributors from atom feed
    contributors = scrape_repo_contributors(owner, repo)
    for login in contributors[:8]:
        if login == owner:
            continue
        time.sleep(REQUEST_DELAY)
        profile = scrape_github_profile(login)
        if not profile:
            continue
        handle = extract_twitter_from_profile(profile)
        if handle:
            matched = match_github_to_author(profile, authors)
            if matched and matched not in results:
                results[matched] = handle

    return results


def search_github_users_for_author(author_name: str) -> str | None:
    """Find an author's Twitter via GitHub user search (HTML scraping)."""
    parts = author_name.strip().split()
    if len(parts) < 2:
        return None

    query = urllib.parse.quote(author_name)
    url = f"https://github.com/search?q={query}&type=users"
    html = http_get(url, timeout=15)
    if not isinstance(html, str) or len(html) < 1000:
        return None

    logins = re.findall(r'href="/([a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,37})"[^>]*data-', html)
    if not logins:
        logins = re.findall(r'class="[^"]*"[^>]*href="/([a-zA-Z0-9_-]+)"', html)

    skip = {"search", "features", "pricing", "login", "signup", "orgs", "topics", "settings", "explore"}
    norm_author = normalize_name(author_name)
    author_parts = norm_author.split()

    seen = set()
    for login in logins:
        if login in seen or login.lower() in skip:
            continue
        seen.add(login)
        profile = scrape_github_profile(login)
        if not profile or not profile.get("name"):
            continue
        # Word-boundary match
        if len(author_parts) >= 2 and match_name_parts(author_parts, profile["name"]):
            handle = extract_twitter_from_profile(profile)
            if handle:
                return handle
        if len(seen) >= 3:
            break
    return None


# ─── Layer 3: Scholars on Twitter dataset ────────────────────────────────────

def load_scholars_dataset(csv_path: str) -> dict[str, str]:
    """Load Scholars on Twitter dataset (CSV). Returns {normalized_name: handle}."""
    mapping = {}
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
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
                    mapping[normalize_name(name)] = handle
    except Exception as e:
        print(f"[WARN] Failed to load scholars dataset: {e}", file=sys.stderr)
    return mapping


def lookup_scholars(author: str, dataset: dict[str, str]) -> str | None:
    """Fuzzy match author name in scholars dataset."""
    norm = normalize_name(author)
    if norm in dataset:
        return dataset[norm]

    parts = norm.split()
    if len(parts) == 2:
        reversed_name = f"{parts[1]} {parts[0]}"
        if reversed_name in dataset:
            return dataset[reversed_name]

    if len(parts) >= 2:
        last = parts[-1]
        first_init = parts[0][0] if parts[0] else ""
        for key, handle in dataset.items():
            key_parts = key.split()
            if len(key_parts) >= 2 and key_parts[-1] == last:
                if first_init and key_parts[0].startswith(first_init):
                    return handle

    return None


# ─── Layer 4: Search fallback ────────────────────────────────────────────────

def search_twitter_for_author(author_name: str, affiliation: str = "") -> str | None:
    """Search for an author's X/Twitter account via web search."""
    queries = [
        f'"{author_name}" site:x.com',
        f'"{author_name}" site:twitter.com',
    ]
    if affiliation:
        queries.insert(0, f'"{author_name}" "{affiliation}" site:x.com')

    for query in queries:
        results = search_web(query, max_results=5)
        for r in results:
            url = r.get("url", r.get("href", ""))
            title = r.get("title", r.get("snippet", "")).lower()
            m = TWITTER_URL_RE.search(url)
            if m:
                handle = m.group(1)
                if handle.lower() not in TWITTER_SKIP_HANDLES and not handle.isdigit():
                    if _search_result_matches_author(author_name, title, handle):
                        return handle
        time.sleep(0.3)

    return None


def _search_result_matches_author(author_name: str, result_text: str, handle: str) -> bool:
    """Verify a search result actually belongs to the author."""
    parts = author_name.lower().split()
    if not parts:
        return True
    last = parts[-1]
    first = parts[0] if parts else ""
    combined = result_text.lower() + " " + handle.lower()
    if len(last) >= 3 and last in combined:
        return True
    if len(first) >= 3 and first in combined:
        return True
    return False


# ─── Main finder ─────────────────────────────────────────────────────────────

class ArxivAuthorFinder:
    def __init__(
        self,
        scholars_db: str | None = None,
        skip_search: bool = False,
        verbose: bool = False,
    ):
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
        arxiv_id = parse_arxiv_id(arxiv_url_or_id)
        if not arxiv_id:
            raise ValueError(f"Cannot parse arxiv ID from: {arxiv_url_or_id!r}")

        if self.verbose:
            print(f"[INFO] Fetching arxiv:{arxiv_id} ...", file=sys.stderr)
        paper = fetch_arxiv_metadata(arxiv_id)
        if not paper:
            raise RuntimeError(f"Failed to fetch arxiv metadata for {arxiv_id}")

        authors = paper["authors"]
        github_urls = paper["github_urls"]

        if self.verbose:
            print(f"[INFO] Paper: {paper['title'][:60]}", file=sys.stderr)
            print(f"[INFO] Authors ({len(authors)}): {', '.join(authors)}", file=sys.stderr)
            print(f"[INFO] GitHub URLs found: {github_urls}", file=sys.stderr)

        results: dict[str, dict] = {a: {"handle": None, "url": None, "source": None, "confidence": None} for a in authors}

        # Layer 1: GitHub via repo URLs
        if github_urls:
            for repo_url in github_urls:
                found = find_twitter_via_repo(repo_url, authors)
                for author, handle in found.items():
                    if results[author]["handle"] is None:
                        results[author] = {"handle": handle, "url": f"https://x.com/{handle}", "source": "github_repo", "confidence": "high"}
                        if self.verbose:
                            print(f"  [GitHub] {author} -> @{handle}", file=sys.stderr)
        else:
            if self.verbose:
                print("[INFO] No GitHub URL in paper, trying search...", file=sys.stderr)
            found_repos = search_github_for_paper(paper["title"])
            for repo_url in found_repos[:2]:
                found = find_twitter_via_repo(repo_url, authors)
                for author, handle in found.items():
                    if results[author]["handle"] is None:
                        results[author] = {"handle": handle, "url": f"https://x.com/{handle}", "source": "github_search", "confidence": "medium"}
                        if self.verbose:
                            print(f"  [GitHub/search] {author} -> @{handle}", file=sys.stderr)

        # Layer 1b: GitHub user search
        missing = [a for a, v in results.items() if v["handle"] is None]
        for author in missing[:8]:
            time.sleep(1)
            handle = search_github_users_for_author(author)
            if handle:
                results[author] = {"handle": handle, "url": f"https://x.com/{handle}", "source": "github_user_search", "confidence": "medium"}
                if self.verbose:
                    print(f"  [GitHub/user] {author} -> @{handle}", file=sys.stderr)

        # Layer 2: Scholars on Twitter dataset
        missing = [a for a, v in results.items() if v["handle"] is None]
        for author in missing:
            handle = lookup_scholars(author, self.scholars)
            if handle:
                results[author] = {"handle": handle, "url": f"https://x.com/{handle}", "source": "scholars_dataset", "confidence": "high"}
                if self.verbose:
                    print(f"  [Scholars] {author} -> @{handle}", file=sys.stderr)

        # Layer 3: Search fallback
        if not self.skip_search:
            missing = [a for a, v in results.items() if v["handle"] is None]
            for author in missing:
                handle = search_twitter_for_author(author)
                if handle:
                    results[author] = {"handle": handle, "url": f"https://x.com/{handle}", "source": "web_search", "confidence": "low"}
                    if self.verbose:
                        print(f"  [Search] {author} -> @{handle}", file=sys.stderr)

        # Verify: check each found handle against real Twitter profile
        for author, info in results.items():
            handle = info.get("handle")
            if handle and not verify_twitter_handle(handle, author):
                if self.verbose:
                    print(f"  [REJECTED] {author} -> @{handle} (Twitter profile doesn't match)", file=sys.stderr)
                results[author] = {"handle": None, "url": None, "source": None, "confidence": None}

        # Summary
        found_count = sum(1 for v in results.values() if v["handle"])
        total = len(authors)
        coverage = found_count / total * 100 if total > 0 else 0

        return {
            "paper": {
                "title": paper["title"],
                "arxiv_id": arxiv_id,
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}",
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


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Discover X/Twitter accounts of arxiv paper authors",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 arxiv_author_finder.py --arxiv 2603.10165
  python3 arxiv_author_finder.py --arxiv https://arxiv.org/abs/1706.03762 --json
  python3 arxiv_author_finder.py --arxiv 2603.10165 --scholars-db scholars.csv
        """
    )
    parser.add_argument("--arxiv", "-a", required=True, help="arxiv ID or URL (e.g. 2603.10165)")
    parser.add_argument("--scholars-db", "-s", help="Path to Scholars on Twitter CSV dataset")
    parser.add_argument("--skip-search", action="store_true", help="Skip web search fallback (faster, less coverage)")
    parser.add_argument("--json", "-j", action="store_true", help="Output raw JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show progress")
    args = parser.parse_args()

    finder = ArxivAuthorFinder(
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

    paper = output["paper"]
    results = output["results"]
    summary = output["summary"]

    print(f"\n  Paper: {paper['title']}")
    print(f"  arxiv: {paper['arxiv_url']}")
    if paper["github_urls"]:
        print(f"  GitHub: {', '.join(paper['github_urls'])}")
    print()
    print(f"  {'Author':<30} {'Twitter':<40} {'Source':<20} {'Confidence'}")
    print("  " + "-" * 100)
    for author, info in results.items():
        twitter = info["url"] if info["url"] else "-"
        source = info["source"] or ""
        conf = info["confidence"] or ""
        print(f"  {author:<30} {twitter:<40} {source:<20} {conf}")
    print()
    print(f"  Coverage: {summary['found']}/{summary['total']} authors ({summary['coverage_pct']}%)")
    print()


if __name__ == "__main__":
    main()
