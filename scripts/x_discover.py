#!/usr/bin/env python3
"""
X Discover - Search and discover valuable tweets by keyword.
Part of x-tweet-fetcher.

Uses DuckDuckGo search (no API key needed) to find tweets on X/Twitter.

Usage:
  python3 x_discover.py --keywords "AI Agent,automation" --limit 5
  python3 x_discover.py --keywords "openclaw" --json
  python3 x_discover.py --keywords "LLM tool" --limit 10 --cache discover_cache.json
"""

import json
import hashlib
import argparse
import sys
from datetime import datetime
from pathlib import Path


def search_web(query, max_results=5, timelimit=None):
    """Search via DuckDuckGo or Camofox Google (no API key needed)

    timelimit: 'd'=最近1天, 'w'=最近1周, 'm'=最近1月, None=不限
    """
    # Try DuckDuckGo first
    try:
        from duckduckgo_search import DDGS
        import warnings
        warnings.filterwarnings("ignore")
        ddgs = DDGS()
        kwargs = {"max_results": max_results}
        if timelimit:
            kwargs["timelimit"] = timelimit
        results = ddgs.text(query, **kwargs)
        if results:
            return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in results]
    except Exception:
        pass

    # Fallback: Camofox Google search
    try:
        from camofox_client import camofox_search
        results = camofox_search(query)
        if results:
            return results[:max_results]
    except Exception:
        pass

    print(f"All search backends failed for: {query[:40]}...", file=sys.stderr)
    return []


def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]


def load_cache(cache_file):
    if cache_file and Path(cache_file).exists():
        return json.loads(Path(cache_file).read_text())
    return {"seen_urls": []}


def save_cache(cache, cache_file):
    if cache_file:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_file).write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def discover_tweets(keywords, max_results=10, cache_file=None, timelimit=None):
    """
    Search for tweets matching keywords.
    
    Args:
        keywords: list of keyword strings
        max_results: max results per keyword
        cache_file: optional path to cache file (skip seen URLs)
    
    Returns:
        dict with total_new, finds list
    """
    cache = load_cache(cache_file)
    all_finds = []

    for keyword in keywords:
        query = f"site:x.com {keyword}"
        results = search_web(query, max_results=max_results, timelimit=timelimit)

        for r in results:
            url = r.get('url', r.get('href', ''))
            if not url:
                continue

            h = url_hash(url)
            if h in cache["seen_urls"]:
                continue

            cache["seen_urls"].append(h)
            all_finds.append({
                "url": url,
                "title": r.get('title', ''),
                "snippet": r.get('body', r.get('snippet', '')),
                "query": keyword,
                "found_at": datetime.now().isoformat()
            })

    save_cache(cache, cache_file)

    return {
        "timestamp": datetime.now().isoformat(),
        "total_new": len(all_finds),
        "finds": all_finds
    }


def main():
    parser = argparse.ArgumentParser(description="Discover tweets by keyword search")
    parser.add_argument("--keywords", "-k", required=True, help="Comma-separated keywords")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Max results per keyword")
    parser.add_argument("--cache", "-c", help="Cache file path (skip seen URLs)")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    result = discover_tweets(keywords, max_results=args.limit, cache_file=args.cache)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["total_new"] == 0:
            print("No new discoveries.")
        else:
            print(f"Found {result['total_new']} new tweets:\n")
            for i, f in enumerate(result["finds"], 1):
                print(f"{i}. {f['title']}")
                if f['snippet']:
                    print(f"   {f['snippet'][:100]}...")
                print(f"   {f['url']}")
                print()

    sys.exit(0 if result["total_new"] == 0 else 1)


if __name__ == "__main__":
    main()
