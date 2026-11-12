<div align="center">

# x-tweet-fetcher

**Fetch X/Twitter tweets, replies, timelines, lists, and articles — no login, no API keys.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-green.svg)](https://www.python.org)
[![GitHub stars](https://img.shields.io/github/stars/ythx-101/x-tweet-fetcher?style=social)](https://github.com/ythx-101/x-tweet-fetcher)

*Three backends · Auto fallback · Unified JSON schema · Built for AI agents*

[Quick Start](#-quick-start) · [Backends](#-three-backends) · [Capabilities](#-capabilities) · [When to use](#-when-to-use--alternatives) · [FAQ](#-faq) · [Python API](#-python-api) · [Self-hosted Nitter](#-self-hosted-nitter) · [Migrating from v1](#-migrating-from-v1)

</div>

---

**x-tweet-fetcher (`xtf`) is a Python CLI and library that lets AI agents and developers fetch X/Twitter tweets, replies, timelines, search results, Lists and X Articles without logging in or using the X API — it routes between FxTwitter, Nitter and a browser driver with automatic fallback and returns one unified JSON schema.**

### 中文简介

免登录、免 API key 抓取 X（推特）的推文、回复、时间线、搜索、Lists 和长文（X Articles）。适合给 AI agent（OpenClaw、Claude Code 等能跑命令行的 agent）当“读推特”的工具，无需 API，输出统一 JSON，并可存入本地 SQLite 推文库。单条推文零依赖；时间线/搜索需要 Nitter；Lists 可走 Nitter 或浏览器；X Article 需要浏览器。

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

# Or in one step (not published on PyPI):
pip install git+https://github.com/ythx-101/x-tweet-fetcher

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

## 🔀 Three Backends

| Backend | Deps | Speed | Covers |
|---------|------|-------|--------|
| **fxtwitter** | None (stdlib) | ⚡⚡ | Single tweets, user profiles |
| **nitter** | A Nitter instance | ⚡ | Timeline, search, replies, mentions, **Lists** |
| **browser** | Camofox *or* Playwright | 🐢 | Everything above + **X Articles** (also the Lists fallback) |
| **auto** (default) | Best available | ⚡→🐢 | Nitter first, browser fallback |

```bash
xtf --user elonmusk                    # auto (default)
xtf --user elonmusk --backend nitter   # direct HTTP only
xtf --list 1455045069516357634         # Lists: Nitter first, browser fallback
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
| X List tweets | `--list` | nitter / browser |
| X Article full text | `--article` | browser |
| Mentions monitor (incremental, cron-friendly) | `--monitor` | nitter / browser |
| Archive fetch results (dedupe, SQLite) | `--ledger <db>` | any |
| Search / stats the archive (offline) | `--ledger <db> --query/--stats` | offline |

**Exit codes** (cron-friendly): `0` success / no new mentions · `1` error / new mentions found · `2` monitor setup error.

**Errors are machine-readable.** Every failure carries `error` (human message) plus `error_code` — one of `invalid_input`, `not_found`, `rate_limited`, `upstream_down`, `backend_unavailable`, `all_backends_failed` — so agents can branch on it. `all_backends_failed` additionally includes per-backend `error_causes`.

## 🧭 When to use / Alternatives

| Approach | Login / keys | Good for | Trade-off |
|---|---|---|---|
| Official X API | Developer account + API keys | Production, write access, guaranteed terms | Account setup, paid access tiers |
| Account-based scrapers | Requires X accounts / cookies | Large-scale collection | Account ban risk, credential handling |
| **x-tweet-fetcher** | None for single tweets; your own Nitter / browser for the rest | AI agents reading tweets on demand, small archives | Depends on FxTwitter / Nitter / page structure; read-only |

**Use it when…**

- an AI agent or script needs to read a tweet, thread, timeline or List on demand, without handling X credentials;
- you want one JSON shape no matter which backend answered;
- you want a small local archive of what you fetched (`--ledger`).

**Don't use it when…**

- you need to post or do anything other than read — xtf is read-only;
- you need contractual guarantees or official support for production workloads — use the official X API.

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

Running your own instance needs two things: a `nitter.conf` (copy the official `nitter.example.conf` and edit it) and a separately running Redis/Valkey. Follow the official guide, including the docker-compose option: <https://github.com/zedeus/nitter#docker>. The official single-container example is:

```bash
docker run -v $(pwd)/nitter.conf:/src/nitter.conf -d --network host zedeus/nitter:latest
```

Start Redis first, and set the port in `nitter.conf` to the one you want. Then point xtf at it:

```bash
export XTF_NITTER=http://127.0.0.1:<port>
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

## ❓ FAQ

**Do I need an X/Twitter API key or account? / 需要 API key 或登录吗？**
No. Single tweets go through FxTwitter with no setup. Full X Article text needs a browser that is already logged in to X; otherwise you get the title plus the public preview (`is_partial: true`).

**Why does `--user` / `--search` fail with `all_backends_failed`?**
No Nitter instance was reachable. Set `XTF_NITTER` to a working instance and check `error_causes` in the output for each backend's reason.

**Can I use public Nitter instances?**
Yes — `XTF_NITTER` accepts several comma-separated instances and fails over between them. Public instances are often unreliable, so [self-hosting](#-self-hosted-nitter) is recommended.

**How do I use it from an AI agent (OpenClaw, Claude Code, others)?**
Have the agent run `xtf ...`, parse the JSON, and branch on `error_code`. The repo ships a [SKILL.md](SKILL.md) describing the commands.

**Can it fetch X Lists and X Articles?**
Lists: Nitter first, browser fallback. Articles: browser only (Camofox or Playwright).

**How do I keep a local archive? / 怎么存档？**
Add `--ledger <db>` to any fetch; query it offline with `--ledger <db> --query <term>` or `--stats`.

**Is it on PyPI?**
Not currently. Install from source: `pip install git+https://github.com/ythx-101/x-tweet-fetcher`.

**Does it post or write to X?**
No, it is read-only.

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
- **[Camofox (camofox-browser)](https://github.com/jo-inc/camofox-browser)** — anti-fingerprint browser, default browser driver
- **[Playwright](https://github.com/microsoft/playwright)** — alternative browser automation driver
- **[OpenClaw](https://github.com/openclaw/openclaw)** — AI agent framework this tool grew up in

## 📜 License

[MIT](LICENSE)

---

<div align="center">

*Three backends. Auto fallback. Built for AI agents.*

**[GitHub](https://github.com/ythx-101/x-tweet-fetcher)** · **[Issues](https://github.com/ythx-101/x-tweet-fetcher/issues)** · **[#22 Teahouse](https://github.com/ythx-101/openclaw-qa/discussions/22)** · **[Agent Waystation](https://github.com/ythx-101/openclaw-qa)**

</div>
