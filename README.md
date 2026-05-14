<div align="center">

# 🦞 x-tweet-fetcher

**Fetch tweets, lists, articles, and WeChat content — with smart backend routing.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenClaw Skill](https://img.shields.io/badge/OpenClaw-Skill-blue.svg)](https://github.com/openclaw/openclaw)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7+-green.svg)](https://www.python.org)
[![GitHub stars](https://img.shields.io/github/stars/ythx-101/x-tweet-fetcher?style=social)](https://github.com/ythx-101/x-tweet-fetcher)

*Three backends · Auto fallback · Works everywhere (VPS / Mac / Windows / CI / Claude Code / OpenClaw)*

[Quick Start](#-quick-start) · [Backends](#-three-backends) · [Capabilities](#-capabilities) · [Agent Waystation](#-agent-waystation) · [Self-hosted Nitter](#-self-hosted-nitter-setup) · [Claude Code & CC](#-works-with-claude-code--cc)

</div>

---

## 😤 Problem

```
You: fetch that tweet / list / article for me
AI:  I can't access X/Twitter. Please copy-paste the content manually.

You: ...seriously?
```

X has no free API. Scraping gets you blocked. Browser automation is fragile and won't work in headless environments.

**x-tweet-fetcher** solves this with **smart backend routing**: Nitter for zero-dependency speed, Playwright for full-feature coverage, auto fallback between them.

## 🔀 Three Backends

```bash
# Auto mode (default) — Nitter first, browser fallback
python3 scripts/fetch_tweet.py --user elonmusk

# Nitter only — zero dependency, no browser
python3 scripts/fetch_tweet.py --user elonmusk --backend nitter

# Browser only — full features (lists, articles)
python3 scripts/fetch_tweet.py --list 1455045069516357634 --backend browser
```

| Backend | Deps | Speed | Features |
|---------|------|-------|----------|
| **nitter** | None (stdlib only) | ⚡ Fast | Timeline, search, replies, profile, mentions |
| **browser** | Playwright/Chromium | 🐢 Slower | Everything above + **Lists** + **Articles** + **fetch_china** |
| **auto** (default) | Best available | ⚡→🐢 | Tries nitter first, falls back to browser |

> **OpenClaw users**: Playwright + Chromium are built-in. `--backend auto` just works — no extra install needed.

## 📊 Capabilities

| Feature | Backend | Output |
|---------|---------|--------|
| Single tweet | FxTwitter (always) | text, stats, media, quotes |
| Reply comments | nitter / browser | threaded comment list |
| User timeline | nitter / browser | paginated tweet list |
| @mentions monitor | nitter / browser | incremental new mentions |
| Keyword search | nitter / browser | real-time tweet stream |
| **X Lists** | **browser only** | list member tweets |
| **X Articles** | **browser only** | full long-form content |
| User profile analysis | nitter + LLM | MBTI, Big Five, topic graph |
| WeChat article search | Sogou (direct HTTP) | title, url, author, date |
| **WeChat/Weibo/Bilibili** | **browser only** | via fetch_china.py |
| Tweet growth tracker | FxTwitter API | growth curves, burst detection |

> **For AI Agents**: All output is structured JSON. Import as Python modules for direct integration. Exit codes are cron-friendly (`0`=nothing new, `1`=new content).

## 🧭 Agent Waystation

x-tweet-fetcher is one of the field tools maintained from **[Agent Waystation](https://github.com/ythx-101/openclaw-qa)** — a stopover for AI agents, builders, tools, and field reports.

If you are building an agent that reads X/Twitter, bring it to the Waystation as a field report or tool walkthrough:

- What does your agent observe?
- What does it remember?
- Where does it fail?
- What field tool does it still need?
- Which runtime, backend, shipped output, and evidence links would help another builder reproduce it?

Known limitation: the current first-run field report verifies onboarding, CLI help, structured error paths, local Nitter failure handling, and empty local state behavior. It does not prove that public tweet fetching is currently restored end to end. Treat it as an error-path / first-run case study, not a successful fetch recovery announcement.

中文：如果你也在养一个会看 X/Twitter 的 Agent，欢迎带它来 **Agent 驿站** 报到。说说它会看什么、会记什么、最容易在哪翻车。

→ **[Visit Agent Waystation / Agent 驿站](https://github.com/ythx-101/openclaw-qa)**

## 🚀 Quick Start

### Single tweet (zero setup)

```bash
# Works immediately — no Nitter, no browser needed
python3 scripts/fetch_tweet.py --url https://x.com/elonmusk/status/123456789
```

### Timeline, search, replies

```bash
# Set your Nitter instance URL (for nitter/auto mode)
export NITTER_URL=http://127.0.0.1:8788

# User timeline
python3 scripts/fetch_tweet.py --user elonmusk --limit 20

# Keyword search — real-time tweets
python3 scripts/nitter_client.py --search "AI agent"

# Tweet replies
python3 scripts/fetch_tweet.py --url https://x.com/elonmusk/status/123456789 --replies

# @mentions monitoring (cron-friendly)
python3 scripts/fetch_tweet.py --monitor @yourusername

# User profile analysis
python3 scripts/x-profile-analyzer.py --user elonmusk --count 100
```

### Lists & Articles (browser backend)

```bash
# X List — requires Playwright
python3 scripts/fetch_tweet.py --list 1455045069516357634 --backend browser

# X Article
python3 scripts/fetch_tweet.py --article https://x.com/user/article/123 --backend browser

# WeChat / Weibo / Bilibili
python3 scripts/fetch_china.py --url "https://mp.weixin.qq.com/s/..."
```

### WeChat search (always zero-dep)

```bash
python3 scripts/sogou_wechat.py --keyword "AI Agent" --limit 5 --json
```

## 🖥️ Works with Claude Code / CC

Since x-tweet-fetcher has **zero mandatory dependencies**, it works perfectly in constrained environments:

| Environment | nitter mode | browser mode | Notes |
|-------------|:----------:|:------------:|-------|
| **Claude Code (CC)** | ✅ | ❌ | No browser runtime |
| **OpenClaw** | ✅ | ✅ | Playwright built-in |
| **VPS (headless Linux)** | ✅ | ✅* | *needs `pip install playwright` |
| **Mac / Windows** | ✅ | ✅* | *needs `pip install playwright` |
| **CI/CD pipelines** | ✅ | ⚠️ | Possible but heavy |
| **Docker containers** | ✅ | ⚠️ | Needs Chromium in image |
| **Termux (Android)** | ✅ | ❌ | No Chromium |

```bash
# In Claude Code (nitter mode, zero deps):
export NITTER_URL=http://your-vps:8788
python3 scripts/fetch_tweet.py --user YuLin807 --limit 10

# In OpenClaw (auto mode, full features):
python3 scripts/fetch_tweet.py --user YuLin807 --limit 10
# → auto-detects Nitter, falls back to Playwright if needed
```

## 🔧 Self-hosted Nitter Setup

> ⚠️ **Public Nitter instances are dead or unreliable** (as of March 2026). Self-hosting is the only reliable option.

### Why you need this

Twitter removed guest API access in 2023. Public Nitter instances get rate-limited because thousands of users share a few accounts. **Your own instance = your own rate limits.**

### 5-minute setup guide

#### 1. Install dependencies

```bash
# Ubuntu/Debian
sudo apt install -y redis-server libpcre3-dev libsass-dev

# Install Nim
curl https://nim-lang.org/choosenim/init.sh -sSf | sh
export PATH=$HOME/.nimble/bin:$PATH
```

#### 2. Build Nitter

```bash
git clone https://github.com/zedeus/nitter
cd nitter
nimble build -d:release
nimble scss
cp nitter.example.conf nitter.conf
```

#### 3. Get X session cookies

Use a **secondary account** (not your main).

1. Log into X in browser → DevTools → Application → Cookies → `x.com`
2. Copy `auth_token` and `ct0`
3. Create `sessions.jsonl`:

```json
{"name":"myaccount","auth_token":"YOUR_AUTH_TOKEN","ct0":"YOUR_CT0"}
```

#### 4. Configure

```ini
[Server]
address = "127.0.0.1"  # Local only!
port = 8788

[Config]
hmacKey = "$(openssl rand -hex 32)"

[Tokens]
tokenFile = "sessions.jsonl"
```

#### 5. Run & test

```bash
sudo systemctl start redis-server
./nitter

# Test
curl http://127.0.0.1:8788/YuLin807
export NITTER_URL=http://127.0.0.1:8788
python3 scripts/nitter_client.py --search "test"
```

### Security

- **Bind to `127.0.0.1` only** — never expose to public internet
- **Use a secondary X account** — session token gives full access
- **Session tokens last ~1 year**

## 📐 How It Works

```
                    ┌─────────────┐
 --url              │  FxTwitter  │  ← Public API, no auth needed
                    │  (free)     │
                    └──────┬──────┘
                           │ JSON
              ┌────────────┴────────────┐
              │    --backend auto       │
              │  ┌───────┐  ┌────────┐  │       ┌──────────┐
 --user       │  │Nitter │→→│Browser │  │       │  Agent   │
 --replies    │  │(fast) │  │(full)  │  │──────▶│  (JSON)  │
 --monitor    │  │ 0 dep │  │Playwrt │  │       │          │
 --search     │  └───────┘  └────────┘  │       └──────────┘
 --list       └─────────────────────────┘
 --article
              ┌─────────────┐
 sogou_wechat │   Sogou     │  ← Direct HTTP, no API key
 fetch_china  │  (search)   │
              └─────────────┘
```

- **Single tweets**: [FxTwitter](https://github.com/FxEmbed/FxEmbed) — always works, zero auth
- **Timeline / Replies / Search / Mentions**: Self-hosted [Nitter](https://github.com/zedeus/nitter) or Playwright browser
- **Lists / Articles**: Playwright browser (Nitter doesn't support these)
- **WeChat / China platforms**: Sogou search + fetch_china.py

## 📦 Requirements

```
Python 3.7+     (that's it for nitter mode)
```

| Mode | Extra requirement |
|------|-----------------|
| `--backend nitter` | Nothing (Python stdlib only) |
| `--backend browser` | `pip install playwright` + `playwright install chromium` |
| `--backend auto` | Uses whatever is available |

## ⏰ Cron Integration

Exit codes for automation: `0`=nothing new, `1`=new content, `2`=error.

```bash
# Check mentions every 30 min
*/30 * * * * NITTER_URL=http://127.0.0.1:8788 python3 fetch_tweet.py --monitor @username

# Discover tweets daily
0 9 * * * python3 nitter_client.py --search "AI Agent" >> ~/discoveries.jsonl
```

## 🤝 Contributing

Issues and PRs welcome! Core platforms:

- **X/Twitter** — Nitter + Playwright backends
- **WeChat articles** — Sogou search

Other platforms welcome as community PRs.

## 🙏 Acknowledgments

- **[Nitter](https://github.com/zedeus/nitter)** by [zedeus](https://github.com/zedeus) (12.6k ⭐) — self-hosted Twitter frontend
- **[FxTwitter](https://github.com/FxEmbed/FxEmbed)** — public API for single tweet data
- **[Playwright](https://github.com/microsoft/playwright)** — browser automation for full-feature coverage
- **[OpenClaw](https://github.com/openclaw/openclaw)** — AI agent framework

## 📄 License

[MIT](LICENSE)

---

<div align="center">

*Three backends. Auto fallback. Works everywhere.* 🦞

**[GitHub](https://github.com/ythx-101/x-tweet-fetcher)** · **[Issues](https://github.com/ythx-101/x-tweet-fetcher/issues)** · **[OpenClaw Q&A](https://github.com/ythx-101/openclaw-qa)** · **[Agent Field Reports](https://github.com/ythx-101/openclaw-qa/discussions/categories/show-and-tell)**

</div>
