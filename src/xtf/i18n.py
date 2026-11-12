"""Bilingual (zh/en) user-facing messages for CLI and error fields."""
from __future__ import annotations

_MESSAGES = {
    "zh": {
        # stderr progress
        "opening_via_camofox": "[x-tweet-fetcher] 正在通过 Camofox 打开 {url} ...",
        "camofox_tab_error": "[Camofox] 打开标签页失败: {err}",
        "camofox_snapshot_error": "[Camofox] 获取快照失败: {err}",
        # error field values (go into JSON output)
        "err_camofox_not_running_user": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --user 前请先启动 Camofox。"
            "参考: https://github.com/jo-inc/camofox-browser"
        ),
        "err_camofox_not_running_replies": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --replies 前请先启动 Camofox。"
            "参考: https://github.com/jo-inc/camofox-browser"
        ),
        "err_snapshot_failed": "无法从 Camofox 获取页面快照",
        "err_mutually_exclusive": "错误：--user、--url、--article、--monitor 和 --list 不能同时使用",
        "err_no_input": "错误：请提供 --url 或 --user",
        "err_prefix": "错误：",
        # warning field values
        "warn_no_tweets": (
            "未解析到推文。Nitter 可能触发了频率限制，或该用户不存在，请稍后重试。"
        ),
        "warn_no_replies": (
            "未解析到评论。该推文可能没有回复，或 Nitter 触发了频率限制，请稍后重试。"
        ),
        # text-only labels
        "timeline_header": "@{user} — 最新 {count} 条推文",
        "replies_header": "{url} 的评论区",
        "media_label": "🖼 {n} 张图片",
        "media_label_with_urls": "🖼 {n} 张图片: {urls}",
        # article/tweet text-only
        "article_by": "作者 @{screen_name} | {created_at}",
        "article_stats": "点赞: {likes} | 转推: {retweets} | 浏览: {views}",
        "article_words": "字数: {word_count}",
        "tweet_stats": "\n点赞: {likes} | 转推: {retweets} | 浏览: {views}",
        # article mode
        "opening_article_via_camofox": "[x-tweet-fetcher] 正在通过 Camofox 打开 X Article {url} ...",
        "err_camofox_not_running_article": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --article 前请先启动 Camofox。"
            "参考: https://github.com/jo-inc/camofox-browser"
        ),
        "err_invalid_article": "无法解析 Article URL 或 ID: {input}",
        "article_header": "X Article: {title}",
        "article_content_label": "正文",
        "article_login_note": (
            "注意：X Article 需要登录才能查看完整内容。"
            "未登录时 Camofox 只能抓到公开部分（标题+摘要）。"
        ),
        # FxTwitter network error
        "err_network": "网络错误：重试后仍无法获取推文",
        "err_unexpected": "获取推文时发生意外错误",
        # monitor mode
        "monitor_baseline": "[monitor] 首次运行，建立基线 ({count} 条)，下次运行起报告增量。",
        "monitor_no_new": "[monitor] 无新 mentions（已知 {known} 条）。",
        "monitor_new_found": "[monitor] 发现 {count} 条新 mentions！",
        "monitor_searching": "[monitor] 搜索 mentions: {query}",
        "monitor_camofox_error": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --monitor 前请先启动 Camofox。"
            "参考: https://github.com/jo-inc/camofox-browser"
        ),
        "monitor_header": "@{username} 的新 mentions ({count} 条)",
        # list mode
        "list_header": "X List {list_id} — 最新 {count} 条推文",
        "err_invalid_list": "无法解析 List URL 或 ID: {input}",
        # text-only output (search / user-info)
        "err_text_prefix": "错误: {error}",
        "search_header": '搜索 "{query}" — {count} 条结果',
        "info_bio": "简介: {bio}",
        "info_counts": "推文: {tweets} | 关注: {following} | 粉丝: {followers}",
        "info_joined": "加入: {joined}",
        "err_camofox_not_running_list": (
            "Camofox 未在 localhost:{port} 运行。"
            "使用 --list 前请先启动 Camofox。"
            "参考: https://github.com/jo-inc/camofox-browser"
        ),
    },
    "en": {
        "opening_via_camofox": "[x-tweet-fetcher] Opening {url} via Camofox...",
        "camofox_tab_error": "[Camofox] open tab error: {err}",
        "camofox_snapshot_error": "[Camofox] snapshot error: {err}",
        "err_camofox_not_running_user": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --user. "
            "See: https://github.com/jo-inc/camofox-browser"
        ),
        "err_camofox_not_running_replies": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --replies. "
            "See: https://github.com/jo-inc/camofox-browser"
        ),
        "err_snapshot_failed": "Failed to get page snapshot from Camofox",
        "err_mutually_exclusive": "Error: --user, --url, --article, --monitor, and --list are mutually exclusive",
        "err_no_input": "Error: provide --url or --user",
        "err_prefix": "Error: ",
        "warn_no_tweets": (
            "No tweets parsed. Nitter may be rate-limited or the user doesn't exist. "
            "Try again later."
        ),
        "warn_no_replies": (
            "No replies parsed. The tweet may have no replies, "
            "or Nitter may be rate-limited. Try again later."
        ),
        "timeline_header": "@{user} — latest {count} tweets",
        "replies_header": "Replies to {url}",
        "media_label": "🖼 {n} media",
        "media_label_with_urls": "🖼 {n} image(s): {urls}",
        "article_by": "By @{screen_name} | {created_at}",
        "article_stats": "Likes: {likes} | Retweets: {retweets} | Views: {views}",
        "article_words": "Words: {word_count}",
        "tweet_stats": "\nLikes: {likes} | Retweets: {retweets} | Views: {views}",
        # article mode
        "opening_article_via_camofox": "[x-tweet-fetcher] Opening X Article {url} via Camofox...",
        "err_camofox_not_running_article": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --article. "
            "See: https://github.com/jo-inc/camofox-browser"
        ),
        "err_invalid_article": "Cannot parse Article URL or ID: {input}",
        "article_header": "X Article: {title}",
        "article_content_label": "Content",
        "article_login_note": (
            "Note: X Articles require login to view full content. "
            "Without login, Camofox can only capture the public portion (title + preview)."
        ),
        "err_network": "Network error: Failed to fetch tweet after retry",
        "err_unexpected": "An unexpected error occurred while fetching the tweet",
        # monitor mode
        "monitor_baseline": "[monitor] First run: baseline established ({count} entries). Future runs will report incremental results.",
        "monitor_no_new": "[monitor] No new mentions (known: {known}).",
        "monitor_new_found": "[monitor] Found {count} new mention(s)!",
        "monitor_searching": "[monitor] Searching mentions: {query}",
        "monitor_camofox_error": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --monitor. "
            "See: https://github.com/jo-inc/camofox-browser"
        ),
        "monitor_header": "New mentions for @{username} ({count})",
        # list mode
        "list_header": "X List {list_id} — latest {count} tweets",
        "err_invalid_list": "Cannot parse List URL or ID: {input}",
        # text-only output (search / user-info)
        "err_text_prefix": "Error: {error}",
        "search_header": 'Search "{query}" — {count} results',
        "info_bio": "Bio: {bio}",
        "info_counts": "Tweets: {tweets} | Following: {following} | Followers: {followers}",
        "info_joined": "Joined: {joined}",
        "err_camofox_not_running_list": (
            "Camofox is not running on localhost:{port}. "
            "Please start Camofox before using --list. "
            "See: https://github.com/jo-inc/camofox-browser"
        ),
    },
}

_lang = "zh"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in _MESSAGES else "zh"


def get_lang() -> str:
    return _lang


def t(key: str, **kwargs) -> str:
    """Look up a message in the current language, formatting with kwargs."""
    msg = _MESSAGES.get(_lang, _MESSAGES["zh"]).get(key, key)
    return msg.format(**kwargs) if kwargs else msg
