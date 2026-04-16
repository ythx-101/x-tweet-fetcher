#!/usr/bin/env python3
"""
X Profile Analyzer - 用户画像分析工具
通过本地 Nitter 实例（纯 HTTP）抓取推文，生成结构化用户画像

Usage:
    # 完整模式（抓推文 + AI 分析）
    python3 x_profile_analyzer.py --user elonmusk

    # 纯数据模式（只抓推文，不调 AI）让龙虾自己分析
    python3 x_profile_analyzer.py --user elonmusk --no-analyze

    # 数据模式 + 保存原始 JSON
    python3 x_profile_analyzer.py --user elonmusk --no-analyze --output-json data.json

AI 配置（完整模式需要，三选一）：
    export MINIMAX_API_KEY=xxx     # MiniMax
    export OPENAI_API_KEY=xxx      # OpenAI / DeepSeek 等
    export OPENAI_BASE_URL=xxx     # 自定义接口（可选）
    export OPENAI_MODEL=xxx        # 模型名（可选，默认 gpt-4o-mini）
"""

import json
import re
import sys
import os
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, Dict, List, Tuple


# ── 配置 ──────────────────────────────────────────────────────────────────────

MINIMAX_API_URL = "https://api.minimax.io/anthropic/v1/messages"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
# REFERENCE_USER 已移除（v1.1）


# ── 认证 ──────────────────────────────────────────────────────────────────────

def load_api_config() -> tuple:
    """
    加载 AI API 配置，返回 (api_key, api_url, model_name, backend)
    优先级：
      1. MINIMAX_API_KEY 环境变量
      2. OPENAI_API_KEY 环境变量（兼容任何 OpenAI 格式接口）
    """
    # 1. 环境变量 MINIMAX_API_KEY
    mm_key = os.environ.get("MINIMAX_API_KEY")
    if mm_key:
        return mm_key, MINIMAX_API_URL, "MiniMax-M2.5", "minimax"

    # 2. OPENAI_API_KEY（兼容 OpenAI / DeepSeek / 任何兼容接口）
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_url = os.environ.get("OPENAI_BASE_URL", OPENAI_API_URL)
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if openai_key:
        return openai_key, openai_url, openai_model, "openai"

    raise RuntimeError(
        "未找到 AI API Key。请设置以下任一环境变量：\n"
        "  export MINIMAX_API_KEY=your_key   # MiniMax（推荐，免费额度多）\n"
        "  export OPENAI_API_KEY=your_key    # OpenAI / DeepSeek / 兼容接口\n"
        "  export OPENAI_BASE_URL=...        # 自定义接口地址（可选）\n"
        "  export OPENAI_MODEL=gpt-4o-mini   # 模型名称（可选）\n"
        "MiniMax 免费注册：https://www.minimaxi.com"
    )

def load_minimax_key() -> str:
    """兼容旧版调用"""
    key, _, _, _ = load_api_config()
    return key


# ── 推文抓取 (Nitter + Nitter) ────────────────────────────────────────────────

def fetch_user_timeline(username: str, count: int = 20, verbose: bool = False, **kwargs) -> Tuple[List[Dict], Dict]:
    """
    抓取用户时间线推文（纯 HTTP，通过本地 Nitter 实例）
    返回 (tweets_list, user_info)
    """
    return _fetch_user_timeline_nitter(username, count, verbose)


def _fetch_user_timeline_nitter(username: str, count: int, verbose: bool) -> Tuple[List[Dict], Dict]:
    """Fetch user timeline via local Nitter (no browser)."""
    try:
        _scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import nitter_client
    except ImportError as e:
        print(f"[x-profile-analyzer] nitter_client import failed: {e}", file=sys.stderr)
        return [], {}

    if verbose:
        print(f"[Fetcher/Nitter] 抓取 @{username} 时间线 (count={count})", file=sys.stderr)

    tweets_raw = nitter_client.fetch_timeline(username, count=count)
    user_info_raw = nitter_client.fetch_user_info(username)

    # Normalize user_info
    user_info = {
        "username": user_info_raw.get("username", username),
        "display_name": user_info_raw.get("display_name", ""),
        "bio": user_info_raw.get("bio", ""),
        "followers": user_info_raw.get("followers", 0),
        "following": user_info_raw.get("following", 0),
        "tweets_count": user_info_raw.get("tweets_count", 0),
        "joined": user_info_raw.get("joined", ""),
    }

    # Normalize tweets to x-profile-analyzer's format
    tweets = []
    for tw in tweets_raw:
        tweets.append({
            "text": tw.get("text", ""),
            "time": tw.get("time", ""),
            "likes": tw.get("likes", 0),
            "retweets": tw.get("retweets", 0),
            "replies": tw.get("replies", 0),
            "views": tw.get("views", 0),
            "media": tw.get("media_urls", []) if tw.get("media_urls") else [],
            "tweet_id": tw.get("tweet_id", ""),
            "url": tw.get("url", ""),
        })

    if verbose:
        print(f"[Fetcher/Nitter] 共获取 {len(tweets)} 条推文", file=sys.stderr)

    return tweets, user_info


# ── MiniMax M2.5 分析 ──────────────────────────────────────────────────────────

def analyze_profile_with_minimax(
    user_info: Dict,
    tweets: List[Dict],
    api_key: str,
    verbose: bool = False,
    api_url: str = None,
    model_name: str = "MiniMax-M2.5",
    backend: str = "minimax",
) -> str:
    """调用 AI API 生成用户画像分析（支持 MiniMax / OpenAI 兼容接口）"""
    if api_url is None:
        api_url = MINIMAX_API_URL

    # 构建推文摘要
    tweets_summary = _build_tweets_summary(tweets)
    user_summary = _build_user_summary(user_info)

    prompt = f"""你是一位专业的社交媒体用户分析师。请基于以下 @{user_info['username']} 的推文数据，生成一份详细的用户画像分析报告。

## 用户基本信息
{user_summary}

## 最近推文（共 {len(tweets)} 条）
{tweets_summary}

## 分析要求
请输出结构化的 Markdown 格式报告，包含以下章节：

1. **话题偏好** - 该用户最常讨论的主题、关注领域、兴趣方向，给出具体例子
2. **写作风格** - 表达方式、语言习惯、句式特点、表情符号使用，引用实际推文原文举例
3. **互动习惯** - 发推频率、回复习惯、转发行为，分析其社交定位（广播型/互动型/潜水型）
4. **技术方向** - 涉及的技术栈、工具、项目、技术观点（如无明显技术内容则标注）
5. **深层动机分析** - 基于推文内容推断：这个人发推的核心驱动力是什么？他/她在追求什么？有什么潜在的焦虑或执念？这是报告的核心章节，要有洞察力，不要泛泛而谈
6. **行为预测** - 基于历史推文，预测这个人接下来最可能做什么，会关注哪些话题，可能的转变方向
7. **AI 测算星座** - 根据推文风格、表达习惯、关注话题，用占星学视角给出"最像哪个星座"，附上 2-3 句有趣理由（娱乐向）
8. **联系切入点** - 如果你想接触这个人，最好的方式是什么？他/她最容易被什么话题吸引？什么开场白会让他/她愿意回复？给出 2-3 个具体建议，要实用，不要套话
9. **一句话人物速写** - 用一句话精准概括这个人，要有记忆点，像一个好的人物传记开头

请保持分析深刻、具体、有洞察力，基于实际推文内容，避免套话。"""

    if verbose:
        print(f"[MiniMax] Sending {len(tweets)} tweets for analysis...", file=sys.stderr)

    try:
        request_body = json.dumps({
            "model": model_name,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            api_url,
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        # 提取文本
        content = result.get("content", [])
        for block in content:
            if block.get("type") == "text":
                return block["text"]

        return f"[Error] Unexpected API response format: {json.dumps(result)[:500]}"

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"MiniMax API HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"MiniMax API connection error: {e.reason}")
    except TimeoutError:
        raise RuntimeError("MiniMax API request timed out (>120s). Try reducing --count.")


def _build_user_summary(user_info: Dict) -> str:
    lines = [
        f"- 用户名: @{user_info.get('username', 'unknown')}",
        f"- 显示名称: {user_info.get('display_name', 'N/A')}",
        f"- 简介: {user_info.get('bio', 'N/A')}",
        f"- 加入时间: {user_info.get('joined', 'N/A')}",
        f"- 推文数: {user_info.get('tweets_count', 0):,}",
        f"- 粉丝数: {user_info.get('followers', 0):,}",
        f"- 关注数: {user_info.get('following', 0):,}",
    ]
    return "\n".join(lines)


def _parse_tweet_date(time_str: str) -> Optional[datetime]:
    """把 Nitter 时间字符串解析成 datetime（尽力而为）"""
    from datetime import timedelta
    now = datetime.now()
    if not time_str:
        return None
    # 相对时间：2h / 15m / 3d / 5s
    m = re.match(r'^(\d+)([smhd])$', time_str.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {'s': timedelta(seconds=n), 'm': timedelta(minutes=n),
                 'h': timedelta(hours=n), 'd': timedelta(days=n)}[unit]
        return now - delta
    # 绝对时间：Jan 19 或 Jan 19, 2026
    for fmt in ("%b %d, %Y", "%b %d"):
        try:
            dt = datetime.strptime(time_str.strip(), fmt)
            if fmt == "%b %d":
                dt = dt.replace(year=now.year)
                # 如果解析出来是未来日期，说明是去年
                if dt > now:
                    dt = dt.replace(year=now.year - 1)
            return dt
        except ValueError:
            continue
    return None


def _build_activity_heatmap(tweets: List[Dict]) -> str:
    """生成推文星期分布 ASCII 热力图"""
    from collections import Counter
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    counts = Counter()
    parsed = 0
    for t in tweets:
        dt = _parse_tweet_date(t.get("time", ""))
        if dt:
            counts[dt.weekday()] += 1
            parsed += 1

    if parsed < 10:
        return ""  # 数据太少，不生成

    total = sum(counts.values())
    max_count = max(counts.values()) if counts else 1
    bar_width = 20

    lines = [f"\n## 活跃时间分析\n", f"发推星期分布（共 {parsed} 条有效数据）：\n"]
    for i, (name, cn) in enumerate(zip(weekday_names, weekday_cn)):
        c = counts.get(i, 0)
        pct = c / total * 100 if total else 0
        filled = int(c / max_count * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)
        lines.append(f"{name} {bar} {c:3d} 条 ({pct:.0f}%)")

    # 最活跃 / 最沉默
    if counts:
        peak_day = max(counts, key=counts.get)
        quiet_day = min(counts, key=counts.get)
        lines.append(f"\n🔥 最活跃：{weekday_cn[peak_day]}  📉 最沉默：{weekday_cn[quiet_day]}")

        # 工作日 vs 周末
        workday = sum(counts.get(i, 0) for i in range(5))
        weekend = sum(counts.get(i, 0) for i in range(5, 7))
        if total > 0:
            if workday / total > 0.7:
                lines.append("💡 工作日驱动型，周末明显减少")
            elif weekend / total > 0.4:
                lines.append("💡 周末活跃型，工作日输出少")
            else:
                lines.append("💡 全周均衡输出，无明显规律")

    return "\n".join(lines)


def _build_tweets_summary(tweets: List[Dict]) -> str:
    parts = []
    for i, t in enumerate(tweets, 1):
        text = t["text"]
        stats = f"回复:{t['replies']} 转推:{t['retweets']} 浏览:{t['views']}"
        has_media = "📷" if bool(t.get("media")) else ""
        quoted = f"\n  > 引用: {t['quoted_text'][:100]}" if t.get("quoted_text") else ""
        parts.append(f"{i}. [{t['time']}] {has_media}{text[:300]}{quoted}\n   ({stats})")
    return "\n\n".join(parts)


# ── 输出格式化 ──────────────────────────────────────────────────────────────────

def format_report(user_info: Dict, tweets: List[Dict], analysis: str) -> str:
    """生成最终 Markdown 报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    username = user_info.get("username", "unknown")
    display_name = user_info.get("display_name", username)
    tweet_count = len(tweets)

    # 数据质量标注
    if tweet_count < 50:
        data_quality = f"⚠️ 低（仅 {tweet_count} 条，Nitter 对该账号收录不足，结果仅供参考）"
    elif tweet_count < 100:
        data_quality = f"⚡ 中（{tweet_count} 条，建议 100+ 条获得更准确分析）"
    else:
        data_quality = f"✅ 高（{tweet_count} 条）"

    header = f"""# 用户画像分析报告：@{username}

> 生成时间：{now}
> 分析工具：x-profile-analyzer v1.5
> 数据来源：Nitter / X.com
> 数据质量：{data_quality}

## 基本信息

| 字段 | 值 |
|------|-----|
| 用户名 | @{username} |
| 显示名称 | {display_name} |
| 简介 | {user_info.get('bio', 'N/A')} |
| 加入时间 | {user_info.get('joined', 'N/A')} |
| 推文数 | {user_info.get('tweets_count', 0):,} |
| 粉丝数 | {user_info.get('followers', 0):,} |
| 关注数 | {user_info.get('following', 0):,} |

*本次分析基于最近 {len(tweets)} 条推文*

---

"""

    heatmap = _build_activity_heatmap(tweets)
    return header + analysis + heatmap + f"\n\n---\n*分析由 AI 生成 | x-profile-analyzer v1.5*\n"


# ── 主程序 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="X 用户画像分析工具 - 抓取推文，可选 AI 分析"
    )
    parser.add_argument("--user", "-u", required=True, help="X/Twitter 用户名（不含 @）")
    parser.add_argument("--count", "-c", type=int, default=300, help="抓取推文数量（默认 300，Nitter 实际上限约 300）")
    parser.add_argument("--output", "-o", help="输出文件路径（默认输出到 stdout）")
    parser.add_argument("--output-json", help="同时保存原始推文 JSON 到指定路径")
    parser.add_argument("--no-analyze", action="store_true", help="只抓推文数据，不调 AI 分析（让调用方自己分析）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细进度信息")
    parser.add_argument("--legacy", action="store_true", help="跳过 Nitter 检查（调试用）")
    args = parser.parse_args()

    username = args.user.lstrip("@")

    # Nitter 直连模式：跳过 Nitter 检查
    # 抓取推文
    print(f"📊 正在抓取 @{username} 的推文...", file=sys.stderr)
    try:
        tweets, user_info = fetch_user_timeline(username, args.count, verbose=args.verbose)
    except RuntimeError as e:
        print(f"[Error] Failed to fetch tweets: {e}", file=sys.stderr)
        sys.exit(1)

    if not tweets:
        print(f"[Warning] No tweets found for @{username}. Account may be protected or not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 成功获取 {len(tweets)} 条推文", file=sys.stderr)

    # 数据质量提示
    if len(tweets) < 50:
        print(f"⚠️  数据不足（仅 {len(tweets)} 条）：该账号在 Nitter 收录较少，可能是小账号或低活跃度账号，分析结果仅供参考", file=sys.stderr)
    elif len(tweets) < 100:
        print(f"⚠️  数据偏少（{len(tweets)} 条）：建议 100 条以上以获得更准确的分析", file=sys.stderr)

    # 保存原始 JSON（可选）
    if args.output_json:
        json_path = Path(args.output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({
            "user_info": user_info,
            "tweets": tweets,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M"),
            "tweet_count": len(tweets),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 原始数据已保存到: {json_path}", file=sys.stderr)

    # --no-analyze：只输出结构化数据，让调用方自己分析
    if args.no_analyze:
        output = _build_data_summary(user_info, tweets)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"✅ 数据已保存到: {args.output}", file=sys.stderr)
        else:
            print(output)
        return

    # AI 分析模式：加载 API Key
    try:
        api_key, api_url, model_name, backend = load_api_config()
        if args.verbose:
            print(f"[Auth] {backend} API loaded: {api_key[:15]}... model={model_name}", file=sys.stderr)
    except RuntimeError as e:
        print(f"[Error] {e}", file=sys.stderr)
        print("提示：使用 --no-analyze 可跳过 AI 分析，直接输出推文数据", file=sys.stderr)
        sys.exit(1)

    print(f"🤖 正在分析用户画像...", file=sys.stderr)
    try:
        analysis = analyze_profile_with_minimax(user_info, tweets, api_key, verbose=args.verbose,
                                                 api_url=api_url, model_name=model_name)
    except RuntimeError as e:
        print(f"[Error] Analysis failed: {e}", file=sys.stderr)
        sys.exit(1)

    report = format_report(user_info, tweets, analysis)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"✅ 报告已保存到: {output_path}", file=sys.stderr)
    else:
        print(report)


def _build_data_summary(user_info: Dict, tweets: List[Dict]) -> str:
    """--no-analyze 模式：输出结构化推文数据，供调用方自行分析"""
    lines = [
        f"# @{user_info.get('username', 'unknown')} 推文数据",
        f"",
        f"## 基本信息",
        f"- 用户名: @{user_info.get('username')}",
        f"- 显示名称: {user_info.get('display_name', 'N/A')}",
        f"- 简介: {user_info.get('bio', 'N/A')}",
        f"- 加入时间: {user_info.get('joined', 'N/A')}",
        f"- 推文数: {user_info.get('tweets_count', 'N/A')}",
        f"- 粉丝数: {user_info.get('followers', 'N/A')}",
        f"- 关注数: {user_info.get('following', 'N/A')}",
        f"",
        f"## 推文列表（共 {len(tweets)} 条）",
        f"",
    ]
    for i, t in enumerate(tweets, 1):
        lines.append(f"### [{i}] {t.get('time', '')} | 💬{t.get('replies',0)} 🔁{t.get('retweets',0)} ❤️{t.get('views',0)}")
        lines.append(t.get('text', '').strip())
        lines.append("")
    # 加热力图
    heatmap = _build_activity_heatmap(tweets)
    if heatmap:
        lines.append(heatmap)
    lines.append("\n---")
    lines.append(f"*x-profile-analyzer v1.5 | 数据抓取时间: {time.strftime('%Y-%m-%d %H:%M')}*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
