# Changelog

## Unreleased

### 新增

- Nitter：纯 HTTP 抓取 X Lists；router 对 Lists 先 Nitter 后浏览器（`3070293`）
- Nitter：回复中抓取作者自回复串，并展开回复中的短链接（`00112a4`）

### 修复

- `--text-only` 的 search / user-info 输出改走 i18n，`--lang en` 时输出英文（默认中文输出不变）
- `User-Agent` 跟随当前版本号（`x-tweet-fetcher/3.1.0`）

### 文档

- 修正 Lists 后端说明（Nitter 优先，浏览器兜底）、Camofox 链接、自建 Nitter 指引
- 安装方式：未发布到 PyPI，请从源码或 git 安装（`pip install git+https://github.com/ythx-101/x-tweet-fetcher`）
- README 新增中文简介、使用场景/替代方案、FAQ；新增 `llms.txt`；补全 `pyproject.toml` 元数据

## 3.1.0 (2026-08-09)

### 新增：推文库 (Ledger)

- `src/xtf/ledger.py`：SQLite 推文归档核心（schema 与 tweet-ledger 兼容）
  - `archive_tweets`：按 `tweet_id` 去重归档（`INSERT OR IGNORE`），写导入回执
  - `query_ledger`：关键词查询（`full_text` 子串匹配，支持 limit/offset）
  - `ledger_stats`：总量/回复/引用/媒体/链接/语言分布/时间范围统计
- CLI 新参数：
  - `--ledger <db>`：抓取模式（`--user`/`--search`/`--list`/`--replies`/`--url`）下自动归档
  - `--ledger <db> --query <term>`：查询归档库
  - `--ledger <db> --stats`：统计归档库
- 兼容性：
  - 无 `--ledger` 时行为与 3.0.0 完全一致
  - 归档失败不阻断抓取（结果带 `ledger_error`）
  - 单推（fxtwitter）dict 缺少 `tweet_id` 时由 CLI 从 URL 注入
- 测试：89+ 用例通过（归档/去重/查询/统计/CLI 集成/回归）

### 修复

- `ledger_stats`：缺库/空表/无 tweets 表时不再返回 None 或抛错，恒返回完整键集

### 文档

- README 新增「推文库 (Ledger)」章节；`docs/e2e-integration.md` 端到端验证记录

---

## v3.0.0 (2026-07-06)

**Full restructure — same CLI, new internals. See MIGRATION.md.**

- Repo now focuses purely on tweet fetching; analytics / China-platform / Obsidian scripts moved out (`v1-legacy` tag)
- Installable package: `pip install x-tweet-fetcher` → `xtf` command + `from xtf import Router`
- Unified backend protocol (fxtwitter / nitter / browser) with auto-fallback router
- Unified `Tweet`/`Reply`/`Profile`/`Article` data models across all backends
  - **Breaking (`--search`)**: search results now use the normalized `Tweet` schema (`author`/`author_name`/`time_ago`) instead of v1's raw Nitter fields (`username`/`display_name`/`time`); the v1-only `url`/`has_media`/`media_urls` fields are dropped. `--user` timeline already used this schema in v1. See MIGRATION.md.
  - List-producing modes gain a top-level `backend` field; `--replies` adds `reply_count`; empty `media` is omitted rather than emitted as `[]`
- Unreachable-backend errors surface as top-level `error_code: "all_backends_failed"` with per-backend reasons (e.g. `backend_unavailable`) under `error_causes` — a clear error with exit 1, never silent empty results
- Multi-instance Nitter with health-check and failover (`XTF_NITTER=url1,url2`)
- Typed errors with machine-readable `error_code` + per-backend `error_causes`
- Retry with exponential backoff for transient upstream failures
- Test suite: parsers locked by fixture snapshot tests; CI via GitHub Actions
- Removed hardcoded public-Nitter default that contradicted README guidance
- `scripts/fetch_tweet.py` kept as a fully compatible shim
- Removed committed `__pycache__`; fixed `.gitignore`

所有重要更新记录在此。

---

## [1.6.1] - 2026-03-04

### 修复
- **转推/引用推文分离**：新增 `retweeted_by` 和 `quoted_tweet` 字段，正确识别 RT 标记和嵌套引用
- **Stats 提取修复**：icon 字符正则支持逗号分隔数字（如 2,434）；新增 stats-only 行模式
- **内容识别修复**：`_is_content_anchor` 不再将 avatar/profile link 误判为 TOC link
- **正则容错**：stats 末尾允许非数字字符（如 `..."`）

---

## [1.6.0] - 2026-03-04

### 新增
- **X Lists 抓取**：`--list <id_or_url>` 抓取 X Lists 推文
  - 支持纯数字 ID 和完整 URL（x.com/i/lists/xxx 或 twitter.com/i/lists/xxx）
  - 通过 Camofox + Nitter，零 API Key
  - 支持翻页（MAX_PAGES=10）和去重
  - 支持 `--text-only` 纯文本和 JSON 输出

---

## [1.5.0] - 2026-02-25

### 新增
- **Nitter Mentions 监控**：基于 Nitter 的实时 X 提及监控
- **version_check.py**：自动版本检查工具

---

## [1.4.0] - 2026-02-24

### 新增
- **小红书支持**：`fetch_china.py` 新增小红书平台，支持 `--proxy` 和 `--cookies`
- **搜狗微信搜索**：`sogou_wechat.py` 新增 `--resolve`（Google/DDG 解析真实 URL）和 `--via-ssh`（SSH 代理）
- **路由器代理**：`--via-router` 24/7 家庭 IP 代理搜索

---

## [1.3.0] - 2026-02-23

### 新增
- **Mentions 监控**：`--monitor @username` 实时监控谁提到了你
  - 基于 Google 搜索（通过 Camofox），零 API key
  - 增量检测 — 首次建基线，后续只报新内容
  - 支持 cron 集成（退出码 0=无新 / 1=有新）
  - 本地缓存去重（~/.x-tweet-fetcher/）

---

## [1.2.1] - 2026-02-21

### 修复
- **时间线排序（Issue #25）**：时间线模式下按 Snowflake ID 降序排列（最新在前），`tweet_id` 字段从 Nitter `/status/{id}` 链接提取，Pinned tweet 标记 `is_pinned: true`

---

## [1.2.0] - 2026-02-20

### 新增
- **国内平台支持**：新增 `fetch_china.py`，支持 4 个中国平台
  - 🔥 **微博** — 帖子、评论、互动数据
  - 🎬 **B站** — 视频信息、UP主、播放量、点赞、弹幕
  - 💻 **CSDN** — 技术文章、代码块、阅读量
  - 📖 **微信公众号** — 全文+图片，纯 HTTP 无需 Camofox
- **共享模块**：提取 `camofox_client.py`，fetch_tweet.py 和 fetch_china.py 共用
- **多输出格式**：JSON / Markdown（带 YAML frontmatter）/ 纯文本
- **自动平台识别**：给 URL 自动判断是微博/B站/CSDN/微信
- **双语 README**：中文默认 + 英文切换

### 架构
- Strategy Pattern：每个平台独立 Parser，社区可轻松扩展

---

## [1.1.0] - 2026-02-20

### 修复
- **评论区链接提取**：修复 Nitter 返回 `- link "https://..."` 格式时链接丢失的问题
- **嵌套评论**：新增 `thread_replies` 字段支持嵌套回复提取

---

## [1.0.0] - 2026-02-14

### 初始发布
- **单条推文**：通过 FxTwitter API 抓取，零依赖零 API Key
- **评论区**：通过 Camofox + Nitter 抓取回复
- **用户时间线**：支持翻页，最多 200 条
- **X Articles**：长文完整提取
- **引用推文**：自动包含
- **双语支持**：中文/英文消息
