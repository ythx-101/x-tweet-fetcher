---
name: x-tweet-fetcher
description: >
  Fetch tweets, replies, and user timelines from X/Twitter without login or API keys.
  Also supports Chinese platforms (Weibo, Bilibili, CSDN, WeChat).
  Includes camofox_search() for zero-cost Google search without API keys.
  Basic tweet fetching: zero dependencies. Replies/timelines/search: requires Camofox.
  Paper tools: find paper authors' X/Twitter accounts (ArXiv → GitHub → web search),
  recommend related papers via OpenAlex (250M+ papers, free, no API key).
  X-Tracker for tweet growth monitoring with burst detection.
---

# X Tweet Fetcher

Fetch tweets from X/Twitter without authentication. Supports tweet content, reply threads, user timelines, Chinese platforms, and tweet growth tracking.

## Feature Overview

| Feature | Command | Dependencies |
|---------|---------|-------------|
| Single tweet | `--url <tweet_url>` | None (zero deps) |
| Reply threads | `--url <tweet_url> --replies` | **Camofox** |
| User timeline | `--user <username> --limit 300` | **Camofox** |
| Chinese platforms | `fetch_china.py --url <url>` | **Camofox** (except WeChat) |
| Google search | `camofox_search("query")` | **Camofox** |
| **X-Tracker** (growth) | `tweet_growth_cli.py --add/--run/--report` | None (zero deps) |
| **Paper → Author X** | `arxiv_author_finder.py --arxiv <id>` | None (zero deps) |
| **Paper Recommend** | `paper_recommend.py --arxiv/--title/--github` | None (zero deps) |

---

## Basic Usage (Zero Dependencies)

### Fetch a Single Tweet

```bash
# JSON output
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456"

# Text only (human readable)
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --text-only

# Pretty JSON
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --pretty
```

### What It Fetches

| Content Type | Support |
|-------------|---------|
| Regular tweets | ✅ Full text + stats |
| Long tweets (Twitter Blue) | ✅ Full text |
| X Articles (long-form) | ✅ Complete article text |
| Quoted tweets | ✅ Included |
| Stats (likes/RT/views) | ✅ Included |
| Media URLs | ✅ Images + videos |

---

## Advanced Features (Requires Camofox)

> ⚠️ The following features require **Camofox** browser service running on `localhost:9377`.
> See [Camofox Setup](#camofox-setup) below.

### Fetch Reply Threads

```bash
# Fetch tweet + all replies (including nested replies)
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies

# Text-only mode with replies
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies --text-only
```

### Fetch User Timeline

```bash
# Fetch latest tweets from a user (supports pagination, MAX_PAGES=20)
python3 scripts/fetch_tweet.py --user <username> --limit 300
```

### Fetch Chinese Platform Content

```bash
# Auto-detects platform from URL
python3 scripts/fetch_china.py --url "https://weibo.com/..."     # Weibo
python3 scripts/fetch_china.py --url "https://bilibili.com/..."  # Bilibili
python3 scripts/fetch_china.py --url "https://csdn.net/..."      # CSDN
python3 scripts/fetch_china.py --url "https://mp.weixin.qq.com/..." # WeChat (no Camofox needed!)
```

| Platform | Status | Notes |
|----------|--------|-------|
| WeChat Articles | ✅ | Uses web_fetch directly, no Camofox |
| Weibo | ✅ | Camofox renders JS |
| Bilibili | ✅ | Video info + stats |
| CSDN | ✅ | Articles + code blocks |
| Zhihu / Xiaohongshu | ⚠️ | Needs cookie import for login |

### Google Search (Zero API Key)

```python
# Python
from scripts.camofox_client import camofox_search
results = camofox_search("your search query")
# Returns: [{"title": "...", "url": "...", "snippet": "..."}, ...]
```

```bash
# CLI
python3 scripts/camofox_client.py "your search query"
```

Uses Camofox browser to search Google directly. **No Brave API key needed, no cost.**

---

## Camofox Setup

### What is Camofox?

Camofox is an anti-detection browser service based on [Camoufox](https://camoufox.com) (a Firefox fork with C++ level fingerprint masking). It bypasses:
- Cloudflare bot detection
- Browser fingerprinting
- JavaScript challenges

### Installation

**Option 1: OpenClaw Plugin**

```bash
openclaw plugins install @askjo/camofox-browser
```

**Option 2: Manual Install**

```bash
git clone https://github.com/jo-inc/camofox-browser
cd camofox-browser
npm install && npm start
```

### Verify

```bash
curl http://localhost:9377/health
# Should return: {"status":"ok"}
```

### REST API

```bash
# Create tab
POST http://localhost:9377/tabs
Body: {"userId":"test", "sessionKey":"test", "url":"https://example.com"}

# Get page snapshot
GET http://localhost:9377/tabs/<TAB_ID>/snapshot?userId=test

# Close tab
DELETE http://localhost:9377/tabs/<TAB_ID>?userId=test
```

---

## From Agent Code

```python
from scripts.fetch_tweet import fetch_tweet

result = fetch_tweet("https://x.com/user/status/123456")
tweet = result["tweet"]

# Regular tweet
print(tweet["text"])
print(f"Likes: {tweet['likes']}, Views: {tweet['views']}")

# X Article (long-form)
if tweet.get("is_article"):
    print(tweet["article"]["title"])
    print(tweet["article"]["full_text"])

# Links found in replies
for reply in result.get("replies", []):
    for link in reply.get("links", []):
        print(link)
```

## Output Format

```json
{
  "url": "https://x.com/user/status/123",
  "username": "user",
  "tweet_id": "123",
  "tweet": {
    "text": "Tweet content...",
    "author": "Display Name",
    "screen_name": "username",
    "likes": 100,
    "retweets": 50,
    "bookmarks": 25,
    "views": 10000,
    "replies_count": 30,
    "created_at": "Mon Jan 01 12:00:00 +0000 2026",
    "is_note_tweet": false,
    "is_article": true,
    "article": {
      "title": "Article Title",
      "full_text": "Complete article content...",
      "word_count": 4847
    }
  },
  "replies": [
    {
      "author": "@someone",
      "text": "Reply text...",
      "likes": 5,
      "links": ["https://github.com/..."],
      "thread_replies": [{"text": "Nested reply..."}]
    }
  ]
}
```

## Paper Tools (Zero Dependencies)

Find paper authors' X/Twitter accounts and discover related papers.

### Find Author X/Twitter from a Paper

```bash
# From ArXiv ID
python3 scripts/arxiv_author_finder.py --arxiv 2603.10165

# From ArXiv URL
python3 scripts/arxiv_author_finder.py --arxiv "https://arxiv.org/abs/1706.03762"

# JSON output
python3 scripts/arxiv_author_finder.py --arxiv 2603.10165 --json

# With verbose progress
python3 scripts/arxiv_author_finder.py --arxiv 2603.10165 -v
```

**Output:** Each author's X profile link (`https://x.com/handle`), source, and confidence level.

**How it finds authors (4-layer cascade):**

| Layer | Method | Confidence |
|-------|--------|-----------|
| GitHub repo | Paper's GitHub link → scrape contributor profiles | High |
| GitHub user search | Search author name → check profile | Medium |
| Scholars dataset | Offline academic Twitter dataset | High |
| Web search | SearxNG/DuckDuckGo `"name" site:x.com` | Low |

### Recommend Related Papers + Author Twitter

```bash
# From ArXiv paper
python3 scripts/paper_recommend.py --arxiv 2603.10165

# From paper title (works for non-ArXiv papers too)
python3 scripts/paper_recommend.py --title "Attention Is All You Need"

# From GitHub repo
python3 scripts/paper_recommend.py --github https://github.com/org/repo

# From a tweet that mentions a paper
python3 scripts/paper_recommend.py --tweet https://x.com/user/status/123456

# Chinese output
python3 scripts/paper_recommend.py --arxiv 2603.10165 --zh

# Top 10 recommendations, JSON output
python3 scripts/paper_recommend.py --arxiv 2603.10165 --top 10 --json

# Skip Twitter lookup (faster)
python3 scripts/paper_recommend.py --arxiv 2603.10165 --skip-twitter
```

**What it recommends (via OpenAlex, 250M+ papers, free):**

| Source | What |
|--------|------|
| cited_by | Papers that cite this one (follow-up work) |
| reference | Papers this one cites (prior work) |
| related | OpenAlex algorithm recommendations |
| same_author | Top papers by the same authors |

**Output:** Related papers ranked by citations, each with title, authors, year, ArXiv link, and author X/Twitter links.

### From Agent Code

```python
# Find author Twitter
from scripts.arxiv_author_finder import ArxivAuthorFinder
finder = ArxivAuthorFinder()
result = finder.find("2603.10165")
for author, info in result["results"].items():
    if info["handle"]:
        print(f"{author}: https://x.com/{info['handle']}")

# Recommend papers
from scripts.paper_recommend import find_related_papers, fetch_arxiv_metadata
paper = fetch_arxiv_metadata("2603.10165")
recommendations = find_related_papers(paper, top_n=5)
for p in recommendations:
    print(f"{p['title']} ({p['citationCount']} citations)")
```

---

## File Structure

```
x-tweet-fetcher/
├── SKILL.md                    # This file
├── README.md                   # GitHub page with full docs
├── scripts/
│   ├── fetch_tweet.py          # Main fetcher (tweet + replies + timeline)
│   ├── fetch_china.py          # Chinese platform fetcher
│   ├── camofox_client.py       # Camofox REST API client + camofox_search()
│   ├── x-profile-analyzer.py   # User profile analysis (AI-powered)
│   ├── paper_recommend.py      # Paper recommendation + author Twitter
│   ├── arxiv_author_finder.py  # ArXiv author → X/Twitter finder
│   ├── common.py               # Shared utilities (HTTP, ArXiv, GitHub, search)
│   └── config.py               # Environment variable configuration
└── CHANGELOG.md
```

## Requirements

- **Basic**: Python 3.7+, no external packages, no API keys
- **Advanced**: Camofox running on localhost:9377
- **Profile Analyzer**: MiniMax M2.5 API key (for AI analysis)

---

## X-Tracker: Tweet Growth Monitoring

Track your tweets' growth and detect viral moments — inspired by semiconductor ETCH Endpoint Detection.

### Quick Start

```bash
# Add a tweet to track
python3 scripts/tweet_growth_cli.py --add "https://x.com/user/status/123" "my launch tweet"

# List all tracked tweets
python3 scripts/tweet_growth_cli.py --list

# Run sampling (new tweets <48h, every 15min)
python3 scripts/tweet_growth_cli.py --run --fast

# Run sampling (all tweets, hourly)
python3 scripts/tweet_growth_cli.py --run --normal

# Generate analysis report
python3 scripts/tweet_growth_cli.py --report 123456789

# Report with topic cross-analysis
python3 scripts/tweet_growth_cli.py --report 123456789 --cross
```

### Cron Integration

```bash
# Dual-frequency sampling
*/15 * * * * python3 tweet_growth_cli.py --run --fast    # New tweets (<48h)
0 * * * *    python3 tweet_growth_cli.py --run --normal  # All tweets (hourly)
```

### Detection Algorithm

| Component | Method | Purpose |
|-----------|--------|---------|
| **Derivative detection** | dV/dt per hour | Spot sudden acceleration |
| **Sliding window** | 5-sample moving average | Filter noise |
| **Multi-signal fusion** | views×1 + likes×1 + bookmarks×1.5 + RT×3 | Weighted composite score |
| **Burst confirmation** | 3 consecutive windows above threshold | Prevent false positives |
| **Surge override** | Single window +100%/h | Catch massive spikes |
| **Saturation** | 6 samples < 2%/h growth | Detect long tail |
| **Propagation** | RT-per-1k-views ratio | Influencer vs algorithm driven |

### Output Example

```
🎯 Burst detected at 2026-03-14 08:45
   - Growth rate: 156%/h
   - Composite score: +2847 (views +1200, RT +89, likes +234)
   - Propagation: 12.3 RT/1k views (influencer-driven)
```

---

## How It Works

- **Basic tweets**: [FxTwitter](https://github.com/FxEmbed/FxEmbed) public API
- **Replies/timelines**: Camofox → Nitter (privacy-respecting X frontend)
- **Chinese platforms**: Camofox renders JS → extracts content
- **Google search**: Camofox opens Google → parses results
- **X-Tracker**: FxTwitter API + derivative detection + burst confirmation
