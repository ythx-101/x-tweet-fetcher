<div align="center">

# x-tweet-fetcher

**Fetch X/Twitter tweets, replies, timelines, lists, and articles — no login, no API keys.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org)
[![GitHub stars](https://img.shields.io/github/stars/ythx-101/x-tweet-fetcher?style=social)](https://github.com/ythx-101/x-tweet-fetcher)

*Three backends · Auto fallback · Unified JSON schema · Built for AI agents*

[Quick Start](#-quick-start) · [Backends](#-three-backends) · [Capabilities](#-capabilities) · [Python API](#-python-api) · [Self-hosted Nitter](#-self-hosted-nitter) · [Migrating from v1](#-migrating-from-v1)

</div>

---

## 😤 Problem

```
You: fetch that tweet / list / article for me
AI:  I can't access X/Twitter. Please copy-paste the content manually.

You: ...seriously?
```

X has no free API. Scraping gets you blocked. Browser automation is fragile in headless environments.

**x-tweet-fetcher** solves this with **smart backend routing**: FxTwitter for single tweets (zero deps), Nitter for timelines and search (direct HTTP), a browser driver for everything else — with automatic fallback between them.

## 🚀 Quick Start

```bash
git clone https://github.com/ythx-101/x-tweet-fetcher
cd x-tweet-fetcher && pip install .

# Single tweet — works instantly, zero configuration
xtf --url https://x.com/user/status/1234567890

# User timeline (needs a Nitter instance, see below)
export XTF_NITTER=http://127.0.0.1:8788
xtf --user elonmusk --limit 20

# Search
xtf --search "openclaw" --limit 10

# Human-readable output instead of JSON
xtf --user elonmusk --text-only
```

Prefer not to install? `python3 scripts/fetch_tweet.py --url ...` works straight from the clone (same flags).

To check a fetched tweet's claims or linked sources, see the optional [tweet context workflow with Parallel Search MCP](docs/tweet-context.md).

## 🔀 Three Backends

| Backend | Deps | Speed | Covers |
|---------|------|-------|--------|
| **fxtwitter** | None (stdlib) | ⚡⚡ | Single tweets, user profiles |
| **nitter** | A Nitter instance | ⚡ | Timeline, search, replies, mentions |
| **browser** | Camofox *or* Playwright | 🐢 | Everything above + **Lists** + **X Articles** |
| **auto** (default) | Best available | ⚡→🐢 | Nitter first, browser fallback |

```bash
xtf --user elonmusk                    # auto (default)
xtf --user elonmusk --backend nitter   # direct HTTP only
xtf --list 1455045069516357634         # lists always use the browser
```

**Browser driver** defaults to Camofox (`localhost:9377`). Playwright users:

```bash
pip install ".[playwright]"            # from the clone
export XTF_BROWSER=playwright          # or: --browser-driver playwright
```

## 📊 Capabilities

| Feature | Flag | Backend |
|---------|------|---------|
| Single tweet (text, stats, media, quotes) | `--url` | fxtwitter |
| Reply comments (threaded) | `--url --replies` | nitter / browser |
| User timeline (paginated) | `--user` | nitter / browser |
| Search | `--search` | nitter |
| User profile | `--user-info` | fxtwitter → nitter |
| X List tweets | `--list` | browser |
| X Article full text | `--article` | browser |
| Mentions monitor (incremental, cron-friendly) | `--monitor` | nitter / browser |
| Archive fetch results (dedupe, SQLite) | `--ledger <db>` | any |
| Search / stats the archive (offline) | `--ledger <db> --query/--stats` | offline |

**Exit codes** (cron-friendly): `0` success / no new mentions · `1` error / new mentions found · `2` monitor setup error.

**Errors are machine-readable.** Every failure carries `error` (human message) plus `error_code` — one of `invalid_input`, `not_found`, `rate_limited`, `upstream_down`, `backend_unavailable`, `all_backends_failed` — so agents can branch on it. `all_backends_failed` additionally includes per-backend `error_causes`.

## 📚 推文库 (Ledger)

`--ledger <db>` turns xtf into a **fetch + archive + query** local tweet library: every timeline / search / list / replies / single-tweet fetch is archived into a SQLite DB, deduped by `tweet_id` (`INSERT OR IGNORE`, idempotent). Schema is compatible with the tweet-ledger (OpenClaw) `tweets` table, so the same DB can be read by both tools.

```bash
# Fetch + archive a timeline
xtf --user YuLin807 --limit 20 --ledger ~/tweets.db

# Search the archive (offline)
xtf --ledger ~/tweets.db --query "sop"

# Stats: totals, languages, media/urls, time ranges
xtf --ledger ~/tweets.db --stats
```

Behavior without `--ledger` is unchanged (3.0.0-compatible). Archiving never breaks a successful fetch — on failure the JSON envelope carries `ledger_error` instead. Single-tweet (fxtwitter) dicts lack `tweet_id`, so the CLI injects it from the URL; `--replies` results are archived with `is_reply=1` and `in_reply_to_status_id` pointing at the parent tweet.

`tweets` table: `tweet_id` (PK) · `created_at` · `full_text` · `lang` · `source_file` · `is_reply` · `in_reply_to_status_id` · `retweeted_status_id` · `quoted_status_id` · `urls_json` · `media_json` · `raw_json` · `imported_at`

End-to-end integration test record: [docs/e2e-integration.md](docs/e2e-integration.md).

## 🐍 Python API

```python
from xtf import Router, NotFound, RateLimited

router = Router()                                  # backend="auto"
tweet   = router.fetch_tweet("user", "1234567890") # dict, v1-compatible shape
tweets  = router.fetch_timeline("user", limit=20)  # list[Tweet]
replies = router.fetch_replies("user", "1234567890")
results = router.search("openclaw", limit=10)

for tw in tweets:
    print(tw.author, tw.likes, tw.text)
    print(tw.to_dict())                            # JSON-ready
```

All backends normalize into one `Tweet` / `Reply` / `Profile` / `Article` schema — your downstream prompt only ever needs to describe one shape.

## ⚙️ Configuration

Everything is an environment variable (CLI flags override):

| Variable | Default | Meaning |
|----------|---------|---------|
| `XTF_NITTER` | `http://127.0.0.1:8788` | Comma-separated Nitter instances, tried in order with failover |
| `XTF_BROWSER` | `camofox` | Browser driver: `camofox` or `playwright` |
| `XTF_BROWSER_PORT` | `9377` | Camofox HTTP port |
| `XTF_LANG` | `zh` | Message language: `zh` or `en` |
| `XTF_CACHE_DIR` | `~/.x-tweet-fetcher` | Mentions-monitor cache |

`NITTER_URL` (the v1 name) is still honored as a fallback for `XTF_NITTER`.

## 🏗 Self-hosted Nitter

Public Nitter instances are unreliable and frequently dead. **Self-hosting is strongly recommended** for timeline/search/replies:

```bash
# See https://github.com/zedeus/nitter for full setup
docker run -d -p 8788:8080 --name nitter zedeus/nitter:latest
export XTF_NITTER=http://127.0.0.1:8788
```

Multiple instances failover automatically:

```bash
export XTF_NITTER=http://127.0.0.1:8788,https://your-backup-instance.example
```

If no instance is reachable, you get a clear error (`error_code: "all_backends_failed"`, with each backend's reason — e.g. `backend_unavailable` — under `error_causes`) telling you exactly what to set. Never a silent empty result.

## 📁 Project Structure

```
src/xtf/
├── models.py        # Tweet / Reply / Profile / Article dataclasses
├── backends/
│   ├── fxtwitter.py # single tweets + profiles
│   ├── nitter.py    # direct HTTP, multi-instance failover
│   └── browser.py   # Camofox / Playwright snapshot fetching
├── parsers/         # pure functions, locked by fixture tests
├── router.py        # auto-fallback chain
├── monitor.py       # incremental mentions monitor
└── cli.py           # the `xtf` command
scripts/fetch_tweet.py   # v1-compatible entry point (thin shim)
tests/fixtures/          # captured page structures — regression protection
```

## 🔄 Migrating from v1

`python3 scripts/fetch_tweet.py` still works with all v1 flags and exit codes, and JSON fields are unchanged for every mode **except `--search`**, whose per-tweet schema is now unified with `--user` (fields renamed, `url`/`has_media`/`media_urls` dropped). See [MIGRATION.md](MIGRATION.md) for the full list, including where the analytics/China/Obsidian scripts went (spoiler: their own repos — this project is now purely about fetching tweets; the old world lives at the `v1-legacy` tag).

## 🧪 Development

```bash
pip install -e ".[dev]"
pytest          # all parsers locked by fixture tests
ruff check src tests
```

When Nitter or X change their page structure, capture a fresh snapshot into `tests/fixtures/` — the failing test will show exactly which parser and field broke.

## 🙏 Acknowledgments

- **[Nitter](https://github.com/zedeus/nitter)** by [zedeus](https://github.com/zedeus) — self-hosted Twitter frontend
- **[FxTwitter](https://github.com/FxEmbed/FxEmbed)** — public API for single tweet data
- **[Camofox](https://github.com/openclaw/camofox)** — anti-fingerprint browser, default browser driver
- **[Playwright](https://github.com/microsoft/playwright)** — alternative browser automation driver
- **[OpenClaw](https://github.com/openclaw/openclaw)** — AI agent framework this tool grew up in

## 📜 License

[MIT](LICENSE)

---

<div align="center">

*Three backends. Auto fallback. Built for AI agents.*

**[GitHub](https://github.com/ythx-101/x-tweet-fetcher)** · **[Issues](https://github.com/ythx-101/x-tweet-fetcher/issues)** · **[#22 Teahouse](https://github.com/ythx-101/openclaw-qa/discussions/22)** · **[Agent Waystation](https://github.com/ythx-101/openclaw-qa)**

</div>
