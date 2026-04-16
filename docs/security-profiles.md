# Security Profiles

This repository can be used in two different ways.

## 1. Safe default: X-only profile

Recommended for OpenClaw, Claude Code, CI, and shared agent runtimes.

### Keep

- `scripts/fetch_tweet.py`
- `scripts/nitter_client.py`
- `scripts/playwright_client.py`
- `scripts/tweet_growth.py`
- `scripts/tweet_growth_cli.py`
- `README.md`
- `SKILL.md`

### Why

This profile stays focused on X/Twitter fetch, replies, timelines, mentions, search, and growth tracking.
It avoids router queues, SSH helpers, cookie import flows, and local note export.

## 2. Optional extras: review before enabling

### Higher-scope files

- `scripts/fetch_china.py`
- `scripts/sogou_wechat.py`
- `scripts/x-profile-analyzer.py`
- `scripts/to_obsidian.py`
- `scripts/paper_to_obsidian.py`
- `scripts/paper_recommend.py`
- `scripts/arxiv_author_finder.py`

### Why they need extra review

These files may rely on one or more of the following:

- external LLM APIs
- SSH / SCP
- router queue files
- cookies or proxies
- local note export
- broader web scraping scope beyond X/Twitter

## Minimal OpenClaw skill skeleton

Use this shape when packaging the X-only profile as a separate skill:

~~~md
---
name: x-tweet-fetcher-safe
description: >
  Fetch X/Twitter tweets, replies, timelines, mentions, and growth data.
  Default profile excludes router, SSH, cookies, proxies, and local auth reads.
---

# X Tweet Fetcher Safe

## Commands

```bash
python3 scripts/fetch_tweet.py --url https://x.com/user/status/123
python3 scripts/fetch_tweet.py --user username --limit 20
python3 scripts/fetch_tweet.py --url https://x.com/user/status/123 --replies
python3 scripts/tweet_growth_cli.py --add https://x.com/user/status/123 label
```

## Scope

- Safe default: X-only
- Optional extras: disabled by default
- Auth: environment variables only
~~~

## Packaging advice

- Make X-only the default profile in agent runtimes.
- Gate router integration behind explicit env vars.
- Keep API keys env-only.
- Treat cookies and proxies as user-supplied optional inputs, not defaults.
