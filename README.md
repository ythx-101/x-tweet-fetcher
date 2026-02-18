# x-tweet-fetcher

Fetch tweets from X/Twitter **without login or API keys**.

An [OpenClaw](https://github.com/openclaw/openclaw) skill.

## What It Can Fetch

| Content | Mode | Dependencies |
|---------|------|-------------|
| Single tweet (text + stats + media) | `--url` | None (FxTwitter) |
| X Articles (long-form) | `--url` | None (FxTwitter) |
| Quoted tweets | `--url` | None (FxTwitter) |
| User timeline | `--user` | Camofox + Nitter |
| Tweet replies | `--url --replies` | Camofox + Nitter |

## Quick Start

### Single Tweet (zero dependencies)

```bash
# JSON output
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456"

# Human readable
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --text-only

# Pretty JSON
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --pretty
```

### User Timeline (requires Camofox)

```bash
# Fetch latest 20 tweets (default)
python3 scripts/fetch_tweet.py --user elonmusk

# Fetch latest 5 tweets, human readable
python3 scripts/fetch_tweet.py --user YuLin807 --limit 5 --text-only

# JSON output
python3 scripts/fetch_tweet.py --user YuLin807 --limit 10 --pretty
```

### Tweet Replies (requires Camofox)

```bash
# Fetch replies as JSON
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies --pretty

# Human readable
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies --text-only
```

## Requirements

- Python 3.7+
- **For `--user` and `--replies`**: [Camofox](https://github.com/openclaw/camofox) running on `localhost:9377`
  - Camofox is a local browser proxy that handles X/Nitter requests
  - Without Camofox, the tool prints a clear error and exits cleanly

## How It Works

| Mode | Mechanism |
|------|-----------|
| `--url` | [FxTwitter](https://github.com/FxEmbed/FxEmbed) public API — zero deps |
| `--user` | Camofox opens Nitter, scrapes timeline |
| `--url --replies` | Camofox opens Nitter tweet page, scrapes replies |

## Output Format

All modes output JSON by default. Use `--text-only` for human-readable output.

### Timeline tweet object

```json
{
  "author": "@YuLin807",
  "author_name": "YuLin",
  "text": "Tweet content here",
  "time_ago": "2h",
  "likes": 42,
  "retweets": 5,
  "replies": 3,
  "views": 1000,
  "media": ["https://pbs.twimg.com/media/..."]
}
```

### Reply object

```json
{
  "author": "@someone",
  "author_name": "Someone",
  "text": "Reply content",
  "time_ago": "1h",
  "likes": 10,
  "replies": 0,
  "views": 500,
  "media": []
}
```

## All Options

```
--url URL         Tweet URL (x.com or twitter.com)
--user USERNAME   Fetch user timeline (no @)
--limit N         Max tweets for --user (default: 20)
--replies         Fetch replies instead of single tweet
--pretty          Pretty print JSON
--text-only       Human-readable output
--timeout N       Request timeout in seconds (default: 30)
--port N          Camofox port (default: 9377)
--nitter HOST     Nitter instance (default: nitter.net)
```

## Limitations

- `--user` and `--replies` depend on Nitter availability (nitter.net may be rate-limited)
- Cannot fetch deleted or private tweets
- `--url` depends on FxTwitter service availability

## License

MIT
