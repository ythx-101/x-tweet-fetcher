#!/usr/bin/env python3
"""
tweet_growth_cli.py — Tweet Growth Tracker CLI
x-tweet-fetcher skill 新功能入口

用法：
  python3 tweet_growth_cli.py --add "https://x.com/.../status/123" "标签"
  python3 tweet_growth_cli.py --list
  python3 tweet_growth_cli.py --run --fast        # 新推文（<48h），每15min跑一次
  python3 tweet_growth_cli.py --run --normal      # 所有推文，每小时跑一次
  python3 tweet_growth_cli.py --report TWEET_ID
  python3 tweet_growth_cli.py --report TWEET_ID --cross  # 含话题交叉分析

Cron 配置（VPS）：
  */15 * * * * python3 tweet_growth_cli.py --run --fast  >> ~/.tweet-growth/growth.log 2>&1
  0 * * * *    python3 tweet_growth_cli.py --run --normal >> ~/.tweet-growth/growth.log 2>&1

环境变量：
  TWEET_GROWTH_DATA — 数据文件路径（默认 ~/.tweet-growth/data.json）
"""

import argparse
import sys
from datetime import datetime

import tweet_growth as tg
from growth_config import NEW_TWEET_HOURS, FAST_INTERVAL_MIN, NORM_INTERVAL_MIN


# ─── 命令 ─────────────────────────────────────────────────────────────────────

def cmd_add(url_or_id: str, label: str):
    tweet_id = url_or_id.strip("/").split("/")[-1].split("?")[0]
    if not tweet_id.isdigit():
        print(f"[ERROR] 无法从 {url_or_id!r} 解析推文 ID")
        sys.exit(1)

    data = tg.load_data()
    if tweet_id in data["tweets"]:
        existing = data["tweets"][tweet_id].get("label", "")
        print(f"[INFO] 已在追踪：{tweet_id}（{existing}）")
        return

    data["tweets"][tweet_id] = {"label": label, "history": []}
    tg.save_data(data)
    print(f"[OK] 开始追踪 {tweet_id} — 「{label}」")


def cmd_list():
    data = tg.load_data()
    tweets = data.get("tweets", {})
    if not tweets:
        print("暂无追踪推文。用 --add 添加。")
        return

    print(f"{'ID':<22} {'标签':<30} {'样本':>6} {'最新浏览':>10}  状态")
    print("─" * 80)
    for tid, rec in tweets.items():
        h = rec.get("history", [])
        views   = h[-1]["views"] if h else 0
        samples = len(h)
        age     = tg.tweet_age_hours(rec)
        mode    = f"快速({FAST_INTERVAL_MIN}m)" if age < NEW_TWEET_HOURS else f"常规({NORM_INTERVAL_MIN}m)"

        if rec.get("saturated"):
            status = "长尾"
        elif rec.get("spike", {}).get("confirmed"):
            status = "★ 爆点"
        else:
            status = mode

        print(f"{tid:<22} {rec.get('label',''):<30} {samples:>6} {views:>10,}  {status}")


def cmd_run(fast_mode: bool):
    # 进程级排他锁：防止双频 cron 同时 read-modify-write 数据文件
    lock_fh = tg._acquire_lock()
    try:
        _do_run(fast_mode)
    finally:
        lock_fh.close()  # 关闭即释放锁


def _do_run(fast_mode: bool):
    data  = tg.load_data()
    tweets = data.get("tweets", {})
    if not tweets:
        print("[INFO] 无追踪推文，用 --add 添加。")
        return

    mode_label = f"快速({FAST_INTERVAL_MIN}m)" if fast_mode else f"常规({NORM_INTERVAL_MIN}m)"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] {mode_label} 采样开始", flush=True)

    sampled = 0
    for tweet_id, record in tweets.items():
        if not tg.should_sample(record, fast_mode):
            continue

        updated = tg.sample_tweet(tweet_id, record)
        data["tweets"][tweet_id] = updated
        sampled += 1

        h      = updated.get("history", [])
        latest = h[-1] if h else {}
        delta  = updated.get("last_delta", {})
        spike  = updated.get("spike", {})

        dv     = delta.get("views", 0)
        dv_str = f"+{dv:,}" if dv >= 0 else f"{dv:,}"
        flags  = ""
        if spike.get("confirmed"):
            flags += " ★SPIKE"
        if updated.get("saturated"):
            flags += " [长尾]"

        print(
            f"  {tweet_id}  [{updated.get('label','')[:20]}]  "
            f"浏览={latest.get('views',0):,}({dv_str})  "
            f"赞={latest.get('likes',0)}  RT={latest.get('retweets',0)}  "
            f"收藏={latest.get('bookmarks',0)}{flags}",
            flush=True,
        )

        if spike.get("confirmed"):
            print(
                f"    → 爆点：{spike.get('reason','')} | "
                f"综合增速={spike.get('spike_score',0):.1%}/h | "
                f"浏览增速={spike.get('view_rate',0):.1%}/h",
                flush=True,
            )

    tg.save_data(data)
    print(f"[{ts}] 完成，采样 {sampled}/{len(tweets)} 条", flush=True)


def cmd_report(tweet_id: str, cross: bool):
    data = tg.load_data()
    rec  = data["tweets"].get(tweet_id)
    if not rec:
        print(f"[ERROR] 未找到推文 {tweet_id}")
        sys.exit(1)
    print(tg.generate_report(tweet_id, rec, cross_analysis=cross))


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Tweet Growth Tracker — x-tweet-fetcher 新功能",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--add",    nargs=2, metavar=("URL", "标签"), help="添加追踪")
    parser.add_argument("--list",   action="store_true",              help="列出所有追踪推文")
    parser.add_argument("--run",    action="store_true",              help="执行一次采样")
    parser.add_argument("--fast",   action="store_true",              help="快速模式（新推文）")
    parser.add_argument("--normal", action="store_true",              help="常规模式（所有推文）")
    parser.add_argument("--report", metavar="ID",                     help="生成分析报告")
    parser.add_argument("--cross",  action="store_true",              help="报告含话题交叉分析")
    args = parser.parse_args()

    if args.add:
        cmd_add(args.add[0], args.add[1])
    elif args.list:
        cmd_list()
    elif args.run:
        if not args.fast and not args.normal:
            parser.error("--run 需要搭配 --fast 或 --normal")
        cmd_run(fast_mode=args.fast)
    elif args.report:
        cmd_report(args.report, cross=args.cross)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
