#!/usr/bin/env python3
from __future__ import annotations
"""
paper_recommend.py — 论文推荐工具

从 X 推文 / GitHub 仓库 / ArXiv ID / 论文标题 出发，提取论文信息，
通过 OpenAlex API 查找相关论文（cited-by、references、同作者），
反向查找作者 X/Twitter 账号。

OpenAlex: 完全免费、无需 API Key、不限流。250M+ 论文。

Usage:
  python3 paper_recommend.py --tweet https://x.com/user/status/123456
  python3 paper_recommend.py --github https://github.com/org/repo
  python3 paper_recommend.py --arxiv 2603.10165
  python3 paper_recommend.py --title "Memory Sparse Attention"
  python3 paper_recommend.py --arxiv 1706.03762 --top 3 --skip-twitter
  python3 paper_recommend.py --arxiv 1706.03762 --zh

Zero pip dependencies — stdlib only (urllib/json/re + subprocess).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

from common import (
    http_get, parse_arxiv_id, fetch_arxiv_metadata, strip_arxiv_version,
    scrape_github_profile, scrape_repo_contributors, extract_twitter_from_profile,
    normalize_name, match_name_parts, match_github_to_author,
    GITHUB_REPO_RE, ARXIV_URL_RE, ARXIV_ID_RE,
)
from config import OPENALEX_API, OPENALEX_EMAIL, OPENALEX_DELAY
from arxiv_author_finder import ArxivAuthorFinder


# ─── OpenAlex helpers ────────────────────────────────────────────────────────

def _oa_get(url: str) -> dict | None:
    """OpenAlex API GET with polite pool email."""
    sep = "&" if "?" in url else "?"
    if OPENALEX_EMAIL:
        url += f"{sep}mailto={urllib.parse.quote(OPENALEX_EMAIL)}"
    time.sleep(OPENALEX_DELAY)
    result = http_get(url, timeout=20)
    return result if isinstance(result, dict) else None


def oa_find_paper(arxiv_id: str = None, title: str = None, doi: str = None) -> dict | None:
    """Find a paper on OpenAlex by ArXiv ID, DOI, or title search."""
    if arxiv_id:
        clean = strip_arxiv_version(arxiv_id)
        doi_url = f"https://doi.org/10.48550/arXiv.{clean}"
        data = _oa_get(f"{OPENALEX_API}/works/{urllib.parse.quote(doi_url, safe='')}")
        if data and data.get("id"):
            return data
    if doi:
        data = _oa_get(f"{OPENALEX_API}/works/doi:{urllib.parse.quote(doi)}")
        if data and data.get("id"):
            return data
    if title:
        q = urllib.parse.quote(title[:200], safe='')
        data = _oa_get(f"{OPENALEX_API}/works?filter=title.search:{q}&per_page=1&sort=cited_by_count:desc")
        if data and data.get("results"):
            return data["results"][0]
        if len(title) > 20:
            data = _oa_get(f"{OPENALEX_API}/works?search={q}&per_page=1&sort=relevance_score:desc")
            if data and data.get("results"):
                return data["results"][0]
    if arxiv_id:
        data = _oa_get(f"{OPENALEX_API}/works?search={urllib.parse.quote(arxiv_id)}&per_page=1")
        if data and data.get("results"):
            return data["results"][0]
    return None


def _oa_work_to_paper(w: dict, source: str = "") -> dict:
    """Convert OpenAlex work to our standard paper dict format."""
    authors_raw = w.get("authorships", [])
    authors = [{"name": a["author"]["display_name"], "authorId": (a["author"].get("id") or "").replace("https://openalex.org/", "")}
               for a in authors_raw if a.get("author", {}).get("display_name")]

    ext_ids = {}
    ids = w.get("ids", {})
    if ids.get("doi"):
        ext_ids["DOI"] = ids["doi"].replace("https://doi.org/", "")
    arxiv_id = None
    for loc in w.get("locations", []):
        lid = (loc.get("landing_page_url") or "")
        m = ARXIV_URL_RE.search(lid)
        if m:
            arxiv_id = strip_arxiv_version(m.group(1))
            ext_ids["ArXiv"] = arxiv_id
            break

    abstract = ""
    if w.get("abstract_inverted_index"):
        inv = w["abstract_inverted_index"]
        if isinstance(inv, dict):
            word_pos = []
            for word, positions in inv.items():
                for pos in positions:
                    word_pos.append((pos, word))
            word_pos.sort()
            abstract = " ".join(wp[1] for wp in word_pos)

    return {
        "paperId": w.get("id", "").replace("https://openalex.org/", ""),
        "externalIds": ext_ids,
        "title": w.get("title") or w.get("display_name", ""),
        "authors": authors,
        "year": w.get("publication_year"),
        "citationCount": w.get("cited_by_count", 0),
        "abstract": abstract,
        "url": w.get("doi") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""),
        "_source": source,
        "_oa_id": w.get("id", "").replace("https://openalex.org/", ""),
    }


def oa_get_citations(oa_id: str, limit: int = 30) -> list[dict]:
    data = _oa_get(f"{OPENALEX_API}/works?filter=cites:{oa_id}&sort=cited_by_count:desc&per_page={limit}")
    if not data or not data.get("results"):
        return []
    return [_oa_work_to_paper(w, "cited_by") for w in data["results"]]


def oa_get_references(oa_id: str, limit: int = 30) -> list[dict]:
    data = _oa_get(f"{OPENALEX_API}/works/{oa_id}?select=referenced_works")
    if not data or not data.get("referenced_works"):
        return []
    ref_ids = data["referenced_works"][:limit]
    if not ref_ids:
        return []
    ids_str = "|".join(r.replace("https://openalex.org/", "") for r in ref_ids)
    batch = _oa_get(f"{OPENALEX_API}/works?filter=openalex:{ids_str}&per_page={limit}&sort=cited_by_count:desc")
    if not batch or not batch.get("results"):
        return []
    return [_oa_work_to_paper(w, "reference") for w in batch["results"]]


def oa_get_related(oa_id: str, limit: int = 20) -> list[dict]:
    data = _oa_get(f"{OPENALEX_API}/works/{oa_id}?select=related_works")
    if not data or not data.get("related_works"):
        return []
    rel_ids = data["related_works"][:limit]
    if not rel_ids:
        return []
    ids_str = "|".join(r.replace("https://openalex.org/", "") for r in rel_ids)
    batch = _oa_get(f"{OPENALEX_API}/works?filter=openalex:{ids_str}&per_page={limit}&sort=cited_by_count:desc")
    if not batch or not batch.get("results"):
        return []
    return [_oa_work_to_paper(w, "related") for w in batch["results"]]


def oa_get_author_papers(author_id: str, limit: int = 10) -> list[dict]:
    data = _oa_get(f"{OPENALEX_API}/works?filter=authorships.author.id:{author_id}&sort=cited_by_count:desc&per_page={limit}")
    if not data or not data.get("results"):
        return []
    return [_oa_work_to_paper(w, "same_author") for w in data["results"]]


# ─── Title similarity ────────────────────────────────────────────────────────

def _title_similarity(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    stop = {"a", "an", "the", "of", "for", "and", "in", "on", "to", "with", "by", "is", "at", "from"}
    wa -= stop
    wb -= stop
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


# ─── Input extraction ────────────────────────────────────────────────────────

def extract_from_tweet(tweet_url: str) -> dict | None:
    """Extract paper info from a tweet URL."""
    print(f"[INFO] Fetching tweet: {tweet_url}", file=sys.stderr)

    tweet_id_m = re.search(r'/status/(\d+)', tweet_url)
    if not tweet_id_m:
        print("[ERROR] Cannot extract tweet ID from URL", file=sys.stderr)
        return None

    tweet_id = tweet_id_m.group(1)
    text = ""

    # Method 1: Local fetch_tweet.py
    fetch_script = os.path.join(os.path.dirname(__file__), "fetch_tweet.py")
    if os.path.exists(fetch_script):
        try:
            result = subprocess.run(
                ['python3', fetch_script, '--url', tweet_url],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                tweet_data = json.loads(result.stdout)
                text = tweet_data.get('tweet', {}).get('text', '')
                if text:
                    print(f"[INFO] Got tweet text via local fetch_tweet.py ({len(text)} chars)", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] Local fetch_tweet.py failed ({e}), trying fallbacks...", file=sys.stderr)

    # Method 2: FxTwitter API
    if not text:
        try:
            username_m = re.search(r'(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)/status/', tweet_url)
            fx_username = username_m.group(1) if username_m else "i"
            fx_url = f"https://api.fxtwitter.com/{fx_username}/status/{tweet_id}"
            fx_data = http_get(fx_url, timeout=10)
            if isinstance(fx_data, dict):
                text = fx_data.get("tweet", {}).get("text", "")
                if text:
                    print("[INFO] Got tweet text via FxTwitter API", file=sys.stderr)
        except Exception:
            pass

    if not text:
        print("[WARN] Could not fetch tweet content, trying ArXiv ID from URL only", file=sys.stderr)
        text = tweet_url

    arxiv_id = parse_arxiv_id(text)
    if arxiv_id:
        return fetch_arxiv_metadata(arxiv_id)

    gh_match = GITHUB_REPO_RE.search(text)
    if gh_match:
        return extract_from_github(gh_match.group(0))

    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 20]
    if lines:
        return search_paper_by_title(lines[0][:200])

    print("[ERROR] Could not find paper info in tweet", file=sys.stderr)
    return None


def extract_from_github(github_url: str) -> dict | None:
    """Extract paper info from a GitHub repo URL."""
    print(f"[INFO] Fetching GitHub repo: {github_url}", file=sys.stderr)
    m = GITHUB_REPO_RE.match(github_url.rstrip("/"))
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)

    readme_text = None
    for branch in ["main", "master", "HEAD"]:
        readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
        readme_text = http_get(readme_url, timeout=15)
        if isinstance(readme_text, str) and len(readme_text) > 50:
            break
        readme_text = None

    if isinstance(readme_text, str):
        arxiv_id = parse_arxiv_id(readme_text)
        if arxiv_id:
            info = fetch_arxiv_metadata(arxiv_id)
            if info:
                if github_url not in info.get("github_urls", []):
                    info.setdefault("github_urls", []).append(github_url)
                return info

        pdf_title = ""
        pdf_m = re.search(r'\[(?:\*{0,2})(?:Paper|paper|PDF|pdf)(?:\*{0,2})\]\(([^)]+\.pdf)\)', readme_text)
        if pdf_m:
            pdf_name = pdf_m.group(1).rsplit('/', 1)[-1]
            pdf_name = re.sub(r'\.pdf$', '', pdf_name)
            pdf_title = re.sub(r'\s+', ' ', pdf_name.replace('_', ' ').replace('-', ' ').strip())
            if len(pdf_title) > 15:
                print(f"[INFO] Paper title from PDF filename: {pdf_title[:60]}...", file=sys.stderr)

        titles_to_try = []
        title_m = re.search(r'^#\s+(.+)', readme_text, re.MULTILINE)
        if title_m:
            raw_title = re.sub(r'[\*\[\]`]', '', title_m.group(1)).strip()
            if ':' in raw_title:
                full_part = raw_title.split(':', 1)[1].strip()
                if len(full_part) > 10:
                    titles_to_try.append(full_part)
            if len(raw_title) > 5:
                titles_to_try.append(raw_title)

        if pdf_m and len(pdf_title) > 15:
            titles_to_try.insert(0, pdf_title)

        titles_to_try.append(repo.replace("-", " ").replace("_", " "))

        for title in titles_to_try:
            result = search_paper_by_title(title)
            if result:
                if github_url not in result.get("github_urls", []):
                    result.setdefault("github_urls", []).append(github_url)
                return result

        # Paper not in any database yet — build info from README
        best_title = titles_to_try[0] if titles_to_try else repo
        authors = []
        bib_m = re.search(r'author\s*=\s*\{([^}]+)\}', readme_text)
        if bib_m:
            raw = bib_m.group(1).replace('\n', ' ')
            authors = [a.strip().rstrip(',') for a in raw.split(' and ') if a.strip() and len(a.strip()) > 2][:10]
            authors = [' '.join(reversed(a.split(', '))) if ', ' in a else a for a in authors]
        if not authors:
            author_m = re.search(r'Authors?\s*[:\-]\s*([^\n]+)', readme_text, re.IGNORECASE)
            if author_m:
                raw = re.sub(r'[\*\[\]`]', '', author_m.group(1)).strip()
                authors = [a.strip() for a in re.split(r'[,;·•]', raw) if a.strip() and len(a.strip()) > 2][:10]

        abstract = ""
        abs_m = re.search(r'##\s*(?:Abstract|📝\s*Abstract)\s*\n+(.+?)(?:\n\n##|\n---)', readme_text, re.DOTALL)
        if abs_m:
            abstract = re.sub(r'\s+', ' ', abs_m.group(1).strip())[:500]

        print(f"[INFO] Paper not in databases yet, using README info: {best_title[:60]}", file=sys.stderr)
        return {
            "arxiv_id": None,
            "title": best_title,
            "authors": authors,
            "abstract": abstract,
            "github_urls": [github_url],
        }

    return None


def search_paper_by_title(title: str) -> dict | None:
    """Search for a paper by title via OpenAlex."""
    print(f"[INFO] Searching OpenAlex for: {title[:60]}...", file=sys.stderr)
    oa_paper = oa_find_paper(title=title)
    if not oa_paper:
        return None
    found_title = oa_paper.get("title") or oa_paper.get("display_name", "")
    sim = _title_similarity(title, found_title)
    if sim < 0.3:
        print(f"[WARN] OpenAlex result '{found_title[:50]}' doesn't match query (sim={sim:.2f}), skipping", file=sys.stderr)
        return None
    oa_work = _oa_work_to_paper(oa_paper)
    arxiv_id = (oa_work.get("externalIds") or {}).get("ArXiv")
    if arxiv_id:
        info = fetch_arxiv_metadata(arxiv_id)
        if info:
            return info
    authors = [a.get("name", "") for a in oa_work.get("authors", [])]
    return {
        "arxiv_id": arxiv_id,
        "title": oa_work.get("title", title),
        "authors": authors,
        "abstract": oa_work.get("abstract", ""),
        "github_urls": [],
    }


# ─── Related papers ──────────────────────────────────────────────────────────

def rank_and_dedupe(papers: list[dict], source_paper_id: str = None) -> list[dict]:
    seen = set()
    unique = []
    for p in papers:
        pid = p.get("paperId")
        dedup_key = pid or p.get("title", "").lower().strip()
        if not dedup_key or dedup_key == source_paper_id or dedup_key in seen:
            continue
        title = p.get("title", "")
        if not title or len(title) < 5:
            continue
        seen.add(dedup_key)
        unique.append(p)
    unique.sort(key=lambda x: x.get("citationCount", 0) or 0, reverse=True)
    return unique


def find_related_papers(paper_info: dict, top_n: int = 5) -> list[dict]:
    """Find related papers using OpenAlex."""
    arxiv_id = paper_info.get("arxiv_id")
    title = paper_info.get("title", "")

    print("[INFO] Looking up paper on OpenAlex...", file=sys.stderr)
    oa_paper = oa_find_paper(arxiv_id=arxiv_id, title=title)
    if oa_paper and not arxiv_id and title:
        found_title = oa_paper.get("title") or oa_paper.get("display_name", "")
        sim = _title_similarity(title, found_title)
        if sim < 0.3:
            print(f"[WARN] OpenAlex match too different (sim={sim:.2f}), treating as not found", file=sys.stderr)
            oa_paper = None
    if not oa_paper:
        print("[WARN] Paper not found on OpenAlex — it may be too new (indexing takes days to weeks).", file=sys.stderr)
        print("[INFO] Falling back to keyword search for related papers...", file=sys.stderr)
        q = urllib.parse.quote(title[:200], safe='')
        data = _oa_get(f"{OPENALEX_API}/works?search={q}&per_page={top_n * 3}&sort=cited_by_count:desc")
        if data and data.get("results"):
            candidates = [_oa_work_to_paper(w, "keyword_match") for w in data["results"]]
            return rank_and_dedupe(candidates, "")[:top_n]
        return []

    oa_id = oa_paper.get("id", "").replace("https://openalex.org/", "")
    oa_title = oa_paper.get("title") or oa_paper.get("display_name", "")
    oa_citations = oa_paper.get("cited_by_count", 0)
    print(f"[INFO] OpenAlex: {oa_title[:60]} (citations: {oa_citations})", file=sys.stderr)

    all_candidates = []
    print("[INFO] Fetching citations...", file=sys.stderr)
    all_candidates.extend(oa_get_citations(oa_id, limit=30))
    print("[INFO] Fetching references...", file=sys.stderr)
    all_candidates.extend(oa_get_references(oa_id, limit=30))
    print("[INFO] Fetching related works...", file=sys.stderr)
    all_candidates.extend(oa_get_related(oa_id, limit=20))

    authorships = oa_paper.get("authorships", [])
    for auth in authorships[:2]:
        author_obj = auth.get("author", {})
        author_oa_id = author_obj.get("id", "").replace("https://openalex.org/", "")
        author_name = author_obj.get("display_name", "unknown")
        if author_oa_id:
            print(f"[INFO] Fetching papers by {author_name}...", file=sys.stderr)
            all_candidates.extend(oa_get_author_papers(author_oa_id, limit=10))

    return rank_and_dedupe(all_candidates, oa_id)[:top_n]


# ─── Author Twitter finder (lightweight, for recommended papers) ─────────────

def _scrape_github_twitter_with_name(username: str) -> tuple[str, str] | None:
    """Scrape Twitter handle + display name from GitHub profile."""
    profile = scrape_github_profile(username)
    if not profile or not profile.get("twitter"):
        return None
    return (profile["twitter"], profile.get("name", ""))


def find_author_twitter(author_name: str, github_urls: list[str] | None = None) -> str | None:
    """Find an author's Twitter handle via GitHub HTML scraping."""
    if github_urls:
        for repo_url in github_urls[:2]:
            m = GITHUB_REPO_RE.match(repo_url.rstrip("/"))
            if not m:
                continue
            owner, repo = m.group(1), m.group(2)

            owner_profile = scrape_github_profile(owner)
            if owner_profile and match_github_to_author(owner_profile, [author_name]):
                handle = extract_twitter_from_profile(owner_profile)
                if handle:
                    return handle

            contributors = scrape_repo_contributors(owner, repo)
            for login in contributors[:5]:
                result = _scrape_github_twitter_with_name(login)
                if result:
                    handle, profile_name = result
                    if profile_name and match_name_parts(
                        normalize_name(author_name).split(),
                        profile_name
                    ):
                        return handle
    return None


# ─── Output formatting ───────────────────────────────────────────────────────

def format_paper(p: dict, idx: int, twitter_map: dict) -> str:
    title = p.get("title", "Unknown")
    year = p.get("year") or "?"
    citations = p.get("citationCount", 0) or 0
    source = p.get("_source", "")
    url = p.get("url", "")
    ext = p.get("externalIds", {}) or {}
    arxiv = ext.get("ArXiv")
    if arxiv:
        url = f"https://arxiv.org/abs/{arxiv}"

    authors = [a.get("name", "") for a in (p.get("authors") or [])[:3]]
    author_str = ", ".join(authors)
    if len(p.get("authors", [])) > 3:
        author_str += " et al."

    lines = [f"  {idx}. {title}"]
    lines.append(f"     {author_str} ({year}) | Citations: {citations} | Source: {source}")
    if url:
        lines.append(f"     {url}")

    abstract = p.get("abstract") or ""
    if abstract:
        abstract = abstract.strip().replace("\n", " ")
        if len(abstract) > 200:
            abstract = abstract[:197] + "..."
        lines.append(f"     Abstract: {abstract}")

    tw_links = []
    for a in (p.get("authors") or []):
        name = a.get("name", "")
        if name in twitter_map and twitter_map[name]:
            tw_links.append(f"https://x.com/{twitter_map[name]}")
    if tw_links:
        lines.append(f"     Twitter: {', '.join(tw_links)}")

    return "\n".join(lines)


def format_paper_zh(p: dict, idx: int, twitter_map: dict) -> str:
    title = p.get("title", "Unknown")
    year = p.get("year") or "?"
    citations = p.get("citationCount", 0) or 0
    source_label = {"cited_by": "引用", "reference": "参考文献", "same_author": "同作者", "related": "相关", "keyword_match": "关键词"}.get(
        p.get("_source", ""), p.get("_source", "")
    )
    url = p.get("url", "") or ""
    ext = p.get("externalIds", {}) or {}
    arxiv = ext.get("ArXiv")
    if arxiv:
        url = f"https://arxiv.org/abs/{arxiv}"

    authors = [a.get("name", "") for a in (p.get("authors") or [])[:3]]
    author_str = ", ".join(authors)
    if len(p.get("authors", [])) > 3:
        author_str += " 等"

    tw = []
    for a in (p.get("authors") or []):
        name = a.get("name", "")
        if name in twitter_map and twitter_map[name]:
            tw.append(f"https://x.com/{twitter_map[name]}")
    tw_str = f" | 推特: {', '.join(tw)}" if tw else ""

    lines = [f"  {idx}. {title}"]
    lines.append(f"     {author_str} ({year}) | 引用: {citations} | 来源: {source_label}{tw_str}")
    if url:
        lines.append(f"     {url}")

    abstract = p.get("abstract") or ""
    if abstract:
        abstract = abstract.strip().replace("\n", " ")
        if len(abstract) > 200:
            abstract = abstract[:197] + "..."
        lines.append(f"     摘要: {abstract}")

    return "\n".join(lines)


def format_output(paper_info: dict, recommendations: list[dict], twitter_map: dict,
                  as_json: bool = False, zh: bool = False) -> str:
    if as_json:
        output = {
            "source_paper": {
                "title": paper_info.get("title"),
                "arxiv_id": paper_info.get("arxiv_id"),
                "authors": paper_info.get("authors", []),
                "github_urls": paper_info.get("github_urls", []),
            },
            "recommendations": [],
        }
        for p in recommendations:
            rec = {
                "title": p.get("title"),
                "year": p.get("year"),
                "citations": p.get("citationCount", 0),
                "source": p.get("_source", ""),
                "url": p.get("url", ""),
                "authors": [a.get("name", "") for a in (p.get("authors") or [])],
                "author_twitter": {},
            }
            ext = p.get("externalIds", {}) or {}
            if ext.get("ArXiv"):
                rec["arxiv_id"] = ext["ArXiv"]
            for a in (p.get("authors") or []):
                name = a.get("name", "")
                if name in twitter_map and twitter_map[name]:
                    rec["author_twitter"][name] = twitter_map[name]
            output["recommendations"].append(rec)
        return json.dumps(output, ensure_ascii=False, indent=2)

    if not zh:
        lines = []
        lines.append(f"\n  Source: {paper_info.get('title', 'Unknown')}")
        if paper_info.get("arxiv_id"):
            lines.append(f"  ArXiv: https://arxiv.org/abs/{paper_info['arxiv_id']}")
        if paper_info.get("authors"):
            author_strs = []
            for a in paper_info['authors'][:5]:
                if a in twitter_map:
                    author_strs.append(f"{a} (https://x.com/{twitter_map[a]})")
                else:
                    author_strs.append(a)
            lines.append(f"  Authors: {', '.join(author_strs)}")
        if paper_info.get("github_urls"):
            lines.append(f"  GitHub: {', '.join(paper_info['github_urls'])}")
        lines.append(f"\n  Top-{len(recommendations)} Related Papers:")
        lines.append("  " + "-" * 70)
        for i, p in enumerate(recommendations, 1):
            lines.append(format_paper(p, i, twitter_map))
            if i < len(recommendations):
                lines.append("")
        lines.append("")
        return "\n".join(lines)

    # Chinese output
    lines = []
    lines.append(f"\n  📄 论文: {paper_info.get('title', 'Unknown')}")
    if paper_info.get("arxiv_id"):
        lines.append(f"  🔗 arXiv: https://arxiv.org/abs/{paper_info['arxiv_id']}")
    if paper_info.get("authors"):
        author_strs = []
        for a in paper_info['authors'][:5]:
            if a in twitter_map:
                author_strs.append(f"{a} (https://x.com/{twitter_map[a]})")
            else:
                author_strs.append(a)
        lines.append(f"  👥 作者: {', '.join(author_strs)}")
    if paper_info.get("github_urls"):
        lines.append(f"  💻 GitHub: {', '.join(paper_info['github_urls'])}")
    lines.append(f"\n  🔖 相关论文 Top-{len(recommendations)}：")
    lines.append("  " + "-" * 60)
    for i, p in enumerate(recommendations, 1):
        lines.append(format_paper_zh(p, i, twitter_map))
        if i < len(recommendations):
            lines.append("")
    lines.append("")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Paper recommendation tool — find related papers + author Twitter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 paper_recommend.py --tweet https://x.com/user/status/123456
  python3 paper_recommend.py --github https://github.com/org/paper-repo
  python3 paper_recommend.py --arxiv 2603.10165
  python3 paper_recommend.py --title "Memory Sparse Attention"
  python3 paper_recommend.py --arxiv 1706.03762 --top 3 --skip-twitter
  python3 paper_recommend.py --arxiv 1706.03762 --zh
        """
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tweet", "-t", help="X/Twitter URL containing paper link")
    group.add_argument("--github", "-g", help="GitHub repo URL for the paper")
    group.add_argument("--arxiv", "-a", help="ArXiv ID or URL (e.g. 2603.10165)")
    group.add_argument("--title", help="Paper title to search for")
    parser.add_argument("--top", "-n", type=int, default=5, choices=range(1, 21), metavar="N",
                        help="Number of recommendations (1-20, default: 5)")
    parser.add_argument("--json", "-j", action="store_true", help="Output raw JSON")
    parser.add_argument("--zh", action="store_true", help="Simplified Chinese output")
    parser.add_argument("--skip-twitter", action="store_true", help="Skip Twitter lookup (faster)")
    args = parser.parse_args()

    # Step 1: Extract paper info
    paper_info = None
    if args.title:
        paper_info = search_paper_by_title(args.title)
    elif args.arxiv:
        arxiv_id = parse_arxiv_id(args.arxiv)
        if not arxiv_id:
            arxiv_id = args.arxiv.strip()
        paper_info = fetch_arxiv_metadata(arxiv_id)
    elif args.github:
        paper_info = extract_from_github(args.github)
    elif args.tweet:
        paper_info = extract_from_tweet(args.tweet)

    if not paper_info:
        print("[ERROR] Could not extract paper information from input", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Found: {paper_info.get('title', 'Unknown')}", file=sys.stderr)
    print(f"  Authors: {', '.join(paper_info.get('authors', [])[:5])}", file=sys.stderr)

    # Step 2: Find related papers
    recommendations = find_related_papers(paper_info, top_n=args.top)
    if not recommendations:
        print("[WARN] No recommendations found", file=sys.stderr)

    # Step 3: Find author Twitter handles
    twitter_map: dict[str, str] = {}
    if not args.skip_twitter:
        # 3a. Source paper authors
        arxiv_id = paper_info.get("arxiv_id")
        if arxiv_id:
            # Has ArXiv ID — use full 4-layer finder
            print("[INFO] Looking up source paper author Twitter...", file=sys.stderr)
            try:
                finder = ArxivAuthorFinder(skip_search=True)
                finder_output = finder.find(arxiv_id)
                for name, info in finder_output.get("results", {}).items():
                    handle = info.get("handle", "")
                    if name and handle:
                        twitter_map[name] = handle.lstrip("@")
                        print(f"  [Twitter] {name} -> @{handle}", file=sys.stderr)
            except Exception as e:
                print(f"[WARN] arxiv_author_finder failed: {e}", file=sys.stderr)
        else:
            # No ArXiv ID — fallback: use GitHub URLs + lightweight search
            print("[INFO] No ArXiv ID, looking up author Twitter via GitHub...", file=sys.stderr)
            authors = paper_info.get("authors", [])
            github_urls = paper_info.get("github_urls", [])
            for author in authors[:5]:
                if author in twitter_map:
                    continue
                handle = find_author_twitter(author, github_urls)
                if handle:
                    twitter_map[author] = handle
                    print(f"  [Twitter] {author} -> @{handle}", file=sys.stderr)

        # 3b. Recommended paper authors — full finder for top papers, lightweight for rest
        if recommendations:
            print("[INFO] Looking up recommended paper author Twitter...", file=sys.stderr)
            # Full ArxivAuthorFinder for top 3 recommended papers that have ArXiv IDs
            top_with_arxiv = [p for p in recommendations if (p.get("externalIds") or {}).get("ArXiv")][:3]
            for p in top_with_arxiv:
                rec_arxiv = p["externalIds"]["ArXiv"]
                try:
                    rec_finder = ArxivAuthorFinder(skip_search=True)
                    rec_output = rec_finder.find(rec_arxiv)
                    for name, info in rec_output.get("results", {}).items():
                        handle = info.get("handle", "")
                        if name and handle and name not in twitter_map:
                            twitter_map[name] = handle.lstrip("@")
                            print(f"  [Twitter] {name} -> @{handle}", file=sys.stderr)
                except Exception:
                    pass

            # Lightweight GitHub scraping for remaining authors
            all_authors = set()
            for p in recommendations:
                for a in (p.get("authors") or [])[:2]:
                    name = a.get("name", "")
                    if name and len(name) > 3 and name not in twitter_map:
                        all_authors.add(name)

            all_gh_urls = list(paper_info.get("github_urls", []))
            for author in list(all_authors)[:10]:
                handle = find_author_twitter(author, all_gh_urls)
                if handle:
                    twitter_map[author] = handle
                    print(f"  [Twitter] {author} -> @{handle}", file=sys.stderr)

    # Step 4: Output
    output = format_output(paper_info, recommendations, twitter_map,
                           as_json=args.json, zh=args.zh)
    print(output)


if __name__ == "__main__":
    main()
