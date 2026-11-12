---
name: x-tweet-fetcher
description: >
  Fetch tweets, replies, timelines, search results, X Lists, and X Articles
  from X/Twitter without login or API keys. Single tweets: zero dependencies
  (FxTwitter). Timelines/search/replies: a Nitter instance (XTF_NITTER).
  Lists: Nitter first, browser fallback. Articles: a browser driver
  (Camofox or Playwright). Unified JSON
  schema across all backends; machine-readable error_code for agent branching.
  Field reports and agent-use questions: Agent Waystation #22 Teahouse:
  https://github.com/ythx-101/openclaw-qa/discussions/22
---

# X Tweet Fetcher

Fetch tweets from X/Twitter without authentication. For agent-use stories, failures, and field reports, start from **[#22 Teahouse / 茶座](https://github.com/ythx-101/openclaw-qa/discussions/22)**.

## Feature Overview

| Feature | Command | Dependencies |
|---------|---------|-------------|
| Single tweet | `xtf --url <tweet_url>` | None (zero deps) |
| Reply threads | `xtf --url <tweet_url> --replies` | Nitter or browser |
| User timeline | `xtf --user <username> --limit 50` | Nitter or browser |
| Search | `xtf --search "<query>"` | Nitter |
| User profile | `xtf --user-info <username>` | None (zero deps) |
| X List | `xtf --list <list_url_or_id>` | Nitter, browser fallback (Camofox/Playwright) |
| X Article | `xtf --article <url_or_id>` | Browser (Camofox/Playwright) |
| Mentions monitor | `xtf --monitor @<username>` | Nitter or browser |

`python3 scripts/fetch_tweet.py` accepts the same flags (v1-compatible entry point).

## Basic Usage (Zero Dependencies)

```bash
# JSON output (default)
xtf --url https://x.com/user/status/1234567890

# Human-readable
xtf --url https://x.com/user/status/1234567890 --text-only

# Output covers: text, author, stats (likes/retweets/views), media URLs,
# quoted tweets, and full article text for tweet-embedded articles.
```

## Timeline / Search / Replies (Nitter)

```bash
export XTF_NITTER=http://127.0.0.1:8788   # your instance; comma-separate for failover
xtf --user elonmusk --limit 20
xtf --search "openclaw" --limit 10
xtf --url https://x.com/user/status/123 --replies
```

Backend selection: `--backend auto` (default, Nitter first then browser), `--backend nitter`, `--backend browser`.

## Lists & Articles

Lists try Nitter first (plain HTTP) and fall back to the browser; Articles need the browser.

```bash
# Articles (and the Lists browser fallback) need a browser driver:
# Camofox running on localhost:9377 (default), or:
export XTF_BROWSER=playwright

xtf --list https://x.com/i/lists/1455045069516357634 --limit 30
xtf --article https://x.com/i/article/2011779830157557760
```

Note: full X Article text requires X login; without it you get title + public preview (`is_partial: true`).

## Mentions Monitor (cron-friendly)

```bash
xtf --monitor @yourhandle
# exit 0 = no new mentions, 1 = new mentions found, 2 = setup error
# First run builds a baseline silently; later runs report only new URLs.
```

## Error Handling for Agents

Every error result includes `error` (message) and `error_code`:
`invalid_input` · `not_found` · `rate_limited` · `upstream_down` · `backend_unavailable` · `all_backends_failed` (with per-backend `error_causes`).

## Python API

```python
from xtf import Router
router = Router()
tweets = router.fetch_timeline("elonmusk", limit=20)  # list[Tweet]
print(tweets[0].to_dict())
```

## Directory Structure

```
src/xtf/
├── backends/   # fxtwitter.py, nitter.py, browser.py
├── parsers/    # pure parsing functions, fixture-tested
├── router.py   # auto-fallback
├── monitor.py  # mentions monitor
└── cli.py      # the `xtf` command
scripts/fetch_tweet.py  # v1-compatible shim
```

Looking for Chinese-platform fetching (Weibo/Bilibili/WeChat) or tweet growth tracking? Those moved out of this repo in v2 — see MIGRATION.md.
