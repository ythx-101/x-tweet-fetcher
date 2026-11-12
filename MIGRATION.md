# Migrating from v1 to v2

## TL;DR

If you call `python3 scripts/fetch_tweet.py ...` today, the flags and exit codes are unchanged and the script is now a thin shim over the `xtf` package. JSON fields are unchanged for every mode **except `--search`**, whose per-tweet schema is now unified with `--user` (see *Behavior changes* #4 below). If you consume `--search` output by field name, read that item before upgrading.

## What's new

- **`pip install .`** from a clone (or `pip install git+https://github.com/ythx-101/x-tweet-fetcher`) — installs an `xtf` command and an importable `xtf` Python package (`from xtf import Router`).
- **Unified schema** — all backends produce the same `Tweet`/`Reply`/`Profile`/`Article` shapes.
- **Multi-instance Nitter** — `XTF_NITTER=url1,url2` with health-check and automatic failover.
- **Machine-readable errors** — every error result now also carries `error_code` (and `error_causes` when all backends fail). The v1 `error` string field is unchanged.
- **Retry with backoff** — transient 429/5xx/network failures are retried automatically.
- **Test suite** — parsers are locked by fixture tests; upstream page changes are caught by `pytest`, not by user bug reports.

## Behavior changes (intentional)

1. **No more hardcoded public Nitter default for browser mode.** v1 defaulted `--nitter` to `nitter.tiekoetter.com`, which contradicted the README's own advice. v2 defaults to your `XTF_NITTER` configuration (default `http://127.0.0.1:8788`). If nothing is reachable you get a clear error (exit 1) instead of silent empty results — the router reports `error_code: "all_backends_failed"` and lists each attempted backend's reason under `error_causes` (e.g. `backend_unavailable` for Nitter when no instance is reachable, `backend_unavailable` for the browser when Camofox isn't running). To restore v1 behavior exactly: `--nitter nitter.tiekoetter.com`.
2. **`--port` and `--nitter` no longer have baked-in defaults in the CLI** — they inherit from `XTF_BROWSER_PORT` / `XTF_NITTER` env vars (with the same effective defaults: 9377 and localhost).
3. **New optional flag** `--browser-driver {camofox,playwright}` replaces the v1 implicit "playwright silently overrides camofox if importable" behavior. Default is camofox; nothing is silently swapped anymore.
4. **`--search` per-tweet schema is unified with `--user`/timeline.** v1's `--search` emitted the raw Nitter parser fields `username`, `display_name`, `time`, `url`, `has_media`, `media_urls`. v2 normalizes every list-producing mode to the single `Tweet` shape, so `--search` now emits `author` (`@handle`), `author_name`, `time_ago` alongside the shared `text`, `tweet_id`, `likes`, `retweets`, `replies`, `views` (and `media` only when non-empty). The v1-only fields **`url`, `has_media`, `media_urls` are no longer emitted by `--search`**, and `username`/`display_name`/`time` are renamed as above. `--user` already used this normalized schema in v1 and is unaffected. Every list-producing mode also gains a top-level `backend` field recording which backend served the request; `--user`/`--replies`/`--list` additionally carry `views_supplemented: true`, and `--replies` carries `reply_count` (alias of `count`).

## Where did the other scripts go?

v2 focuses this repo purely on fetching tweets. Removed in v2 (available in the `v1-legacy` git tag):

| Script | Status |
|--------|--------|
| `fetch_china.py`, `sogou_wechat.py` | Moving to a separate repo (Chinese-platform fetching) |
| `tweet_growth*.py`, `x-profile-analyzer.py`, `x_discover.py` | Analytics, out of scope — `v1-legacy` tag |
| `arxiv_author_finder.py`, `paper_recommend.py`, `paper_to_obsidian.py`, `to_obsidian.py` | Unrelated to tweets — `v1-legacy` tag |
| `x_mentions_nitter.py` | Merged into `--monitor --backend nitter` |
| `nitter_client.py`, `camofox_client.py`, `playwright_client.py`, `common.py` | Now live inside `src/xtf/` |

To pin the old world: `git checkout v1-legacy`.

## Mentions cache

The v1 cache at `~/.x-tweet-fetcher/mentions-cache-*.json` is read as-is (including the old bare-list format). No action needed.
