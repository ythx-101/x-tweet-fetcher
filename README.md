# x-tweet-fetcher

不需要登录，不需要 API Key，直接抓推文。

[English](#english) | 中文

An [OpenClaw](https://github.com/openclaw/openclaw) skill.

---

## 能抓什么

| 内容 | 参数 | 依赖 |
|------|------|------|
| 单条推文（文字+数据+图片） | `--url` | 无（FxTwitter） |
| X 长文（Article） | `--url` | 无（FxTwitter） |
| 引用推文 | `--url` | 无（FxTwitter） |
| 用户时间线 | `--user` | Camofox + Nitter |
| 推文评论区 | `--url --replies` | Camofox + Nitter |

## 快速开始

### 抓单条推文（零依赖）

```bash
# JSON 输出
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456"

# 易读格式
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --text-only

# 格式化 JSON
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --pretty
```

### 抓用户时间线（需要 Camofox）

```bash
# 抓最新 50 条（默认，自动翻页）
python3 scripts/fetch_tweet.py --user elonmusk

# 抓最新 5 条，易读格式
python3 scripts/fetch_tweet.py --user YuLin807 --limit 5 --text-only

# 抓 100 条，自动跨多页
python3 scripts/fetch_tweet.py --user YuLin807 --limit 100 --pretty
```

### 抓评论区（需要 Camofox）

```bash
# JSON 输出
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies --pretty

# 易读格式
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies --text-only
```

## 环境要求

- Python 3.7+
- **`--user` 和 `--replies` 需要**：[Camofox](https://github.com/openclaw/camofox) 运行在 `localhost:9377`
  - 没有 Camofox 会有明确提示，不会崩溃

## 工作原理

| 模式 | 机制 |
|------|------|
| `--url` | FxTwitter 公开 API，零依赖 |
| `--user` | Camofox 打开 Nitter，抓时间线 |
| `--url --replies` | Camofox 打开 Nitter 推文页，抓评论 |

## 输出格式

默认 JSON 输出，`--text-only` 切换易读格式。

### 时间线推文

```json
{
  "author": "@username",
  "author_name": "Display Name",
  "text": "推文正文内容",
  "time_ago": "2h",
  "likes": 42,
  "retweets": 5,
  "replies": 3,
  "views": 1000,
  "media": ["https://pbs.twimg.com/media/..."]
}
```

### 评论对象

```json
{
  "author": "@someone",
  "author_name": "Someone",
  "text": "评论内容",
  "time_ago": "1h",
  "likes": 10,
  "replies": 0,
  "views": 500,
  "media": []
}
```

## 全部参数

```
--url URL         推文链接（x.com 或 twitter.com）
--user USERNAME   抓用户时间线（不带 @）
--limit N         --user 最多抓几条（默认 50，自动翻页，最多约 200 条）
--replies         抓评论区
--pretty          格式化 JSON 输出
--text-only       易读文本输出
--lang zh|en      提示语言（默认 zh 中文）
--timeout N       请求超时秒数（默认 30）
--port N          Camofox 端口（默认 9377）
--nitter HOST     Nitter 实例（默认 nitter.net）
```

## 限制

- `--user` 和 `--replies` 依赖 Nitter 可用性
- 无法抓已删除或私密推文
- `--url` 依赖 FxTwitter 服务可用性

## License

MIT

---

## English

<a name="english"></a>

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
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456"
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --text-only
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --pretty
```

### User Timeline (requires Camofox)

```bash
python3 scripts/fetch_tweet.py --user elonmusk
python3 scripts/fetch_tweet.py --user YuLin807 --limit 5 --text-only
python3 scripts/fetch_tweet.py --user YuLin807 --limit 100 --pretty
```

### Tweet Replies (requires Camofox)

```bash
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies --pretty
python3 scripts/fetch_tweet.py --url "https://x.com/user/status/123456" --replies --text-only
```

## Requirements

- Python 3.7+
- **For `--user` and `--replies`**: [Camofox](https://github.com/openclaw/camofox) running on `localhost:9377`

## How It Works

| Mode | Mechanism |
|------|-----------|
| `--url` | [FxTwitter](https://github.com/FxEmbed/FxEmbed) public API — zero deps |
| `--user` | Camofox opens Nitter, scrapes timeline |
| `--url --replies` | Camofox opens Nitter tweet page, scrapes replies |

## All Options

```
--url URL         Tweet URL (x.com or twitter.com)
--user USERNAME   Fetch user timeline (no @)
--limit N         Max tweets for --user (default: 50, auto-paginates up to ~200)
--replies         Fetch replies instead of single tweet
--pretty          Pretty print JSON
--text-only       Human-readable output
--lang zh|en      Message language (default: zh)
--timeout N       Request timeout in seconds (default: 30)
--port N          Camofox port (default: 9377)
--nitter HOST     Nitter instance (default: nitter.net)
```

## Limitations

- `--user` and `--replies` depend on Nitter availability
- Cannot fetch deleted or private tweets
- `--url` depends on FxTwitter service availability

## License

MIT
