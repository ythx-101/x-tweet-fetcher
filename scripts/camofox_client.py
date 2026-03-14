#!/usr/bin/env python3
"""
Camofox Client - Shared module for Camofox browser automation.

Provides functions to open tabs, get snapshots, and fetch pages via Camofox REST API.
Used by fetch_tweet.py and fetch_china.py.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from typing import Optional


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
        print(f"[Camofox] open tab error: {e}", file=sys.stderr)
        return None


def camofox_snapshot(tab_id: str, port: int = 9377) -> Optional[str]:
    """Get page snapshot text from Camofox tab."""
    try:
        url = f"http://localhost:{port}/tabs/{tab_id}/snapshot?userId=x-tweet-fetcher"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return data.get("snapshot", "")
    except Exception as e:
        print(f"[Camofox] snapshot error: {e}", file=sys.stderr)
        return None


def camofox_close_tab(tab_id: str, port: int = 9377):
    """Close a Camofox tab."""
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


import re
import urllib.parse


def camofox_search(query: str, num: int = 10, lang: str = "zh-CN", engine: str = "google", port: int = 9377) -> list:
    """
    Search via Camofox. Supports Google and DuckDuckGo.
    
    Args:
        query: search keywords
        num: max results
        lang: language code
        engine: "google" or "duckduckgo"
        port: Camofox port
    
    Returns list of dicts: [{"title": ..., "url": ..., "snippet": ...}, ...]
    """
    encoded = urllib.parse.quote(query)
    
    if engine == "duckduckgo":
        search_url = f"https://duckduckgo.com/?q={encoded}&kl={lang}&t=h_"
        snapshot = camofox_fetch_page(search_url, f"ddg-{int(time.time())}", wait=5, port=port)
        if not snapshot:
            return []
        return _parse_duckduckgo_results(snapshot, num)
    else:
        search_url = f"https://www.google.com/search?q={encoded}&hl={lang}&num={num}"
        snapshot = camofox_fetch_page(search_url, f"search-{int(time.time())}", wait=4, port=port)
        if not snapshot:
            return []
        return _parse_google_results(snapshot)


def _parse_duckduckgo_results(snapshot: str, max_results: int = 10) -> list:
    """Parse DuckDuckGo search results from Camofox snapshot text."""
    results = []
    lines = snapshot.split("\n")
    i = 0
    while i < len(lines) and len(results) < max_results:
        line = lines[i].strip()
        # DuckDuckGo result pattern: heading with link
        if '- heading "' in line and '[level=' in line:
            m = re.search(r'heading "(.+?)"', line)
            title = m.group(1) if m else ""
            
            # Look for URL nearby
            url = ""
            for j in range(max(0, i - 3), min(len(lines), i + 3)):
                if "/url:" in lines[j]:
                    candidate = lines[j].strip().split("/url:", 1)[1].strip()
                    if candidate and "duckduckgo.com" not in candidate:
                        url = candidate
                        break
            
            # Look forward for snippet
            snippet_parts = []
            k = i + 1
            while k < len(lines) and k < i + 8:
                sline = lines[k].strip()
                if sline.startswith("- heading ") or sline.startswith("- link "):
                    break
                for prefix in ["- text:", "text:", "- emphasis:", "emphasis:"]:
                    if sline.startswith(prefix):
                        snippet_parts.append(sline.split(prefix, 1)[1].strip())
                        break
                k += 1
            
            snippet = " ".join(snippet_parts).strip()
            
            if url and title:
                results.append({"title": title, "url": url, "snippet": snippet})
        i += 1
    return results


def _parse_google_results(snapshot: str) -> list:
    """Parse Google search results from Camofox snapshot text."""
    results = []
    lines = snapshot.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Look for search result links with heading inside
        # Pattern: - link "Title ... site https://..." [eNN]:
        #            - /url: https://actual-url
        #            - heading "Title" [level=3]
        #            - text: site description
        #          - text: snippet...
        if '- heading "' in line and '[level=3]' in line:
            # Extract title
            m = re.search(r'heading "(.+?)"', line)
            title = m.group(1) if m else ""
            
            # Look backwards for the URL
            url = ""
            for j in range(max(0, i - 3), i):
                if "/url:" in lines[j]:
                    url = lines[j].strip().split("/url:", 1)[1].strip()
                    break
            
            # Look forward for snippet text
            snippet_parts = []
            k = i + 1
            # Skip the "text: site description" line right after heading
            if k < len(lines) and "text:" in lines[k] and ("https://" in lines[k] or "http://" in lines[k]):
                k += 1
            # Collect snippet lines until next link/heading
            while k < len(lines):
                sline = lines[k].strip()
                if sline.startswith("- link ") or sline.startswith("- heading "):
                    break
                if sline.startswith("- text:"):
                    snippet_parts.append(sline.split("- text:", 1)[1].strip())
                elif sline.startswith("- emphasis:"):
                    snippet_parts.append(sline.split("- emphasis:", 1)[1].strip())
                elif sline.startswith("text:"):
                    snippet_parts.append(sline.split("text:", 1)[1].strip())
                elif sline.startswith("emphasis:"):
                    snippet_parts.append(sline.split("emphasis:", 1)[1].strip())
                k += 1
            
            snippet = " ".join(snippet_parts).strip()
            
            # Filter out non-result entries
            if url and title and not url.startswith("/search") and "google.com" not in url:
                results.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                })
        i += 1
    return results


if __name__ == "__main__":
    import sys
    # Usage: python3 camofox_client.py [--engine google|duckduckgo] query...
    engine = "google"
    args = sys.argv[1:]
    if "--engine" in args:
        idx = args.index("--engine")
        if idx + 1 < len(args):
            engine = args[idx + 1]
            args = args[:idx] + args[idx + 2:]
        else:
            args = args[:idx]
    query = " ".join(args) if args else "AI Agent"
    print(f"Searching ({engine}): {query}")
    results = camofox_search(query, engine=engine)
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['title']}")
        print(f"   {r['url']}")
        print(f"   {r['snippet'][:100]}...")
