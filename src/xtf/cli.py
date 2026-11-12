"""CLI — argument-compatible with v1 ``scripts/fetch_tweet.py``.

Same flags, same JSON envelopes, same exit codes:
  0 = success / no new mentions
  1 = error / new mentions found (--monitor)
  2 = monitor setup error
New in v2: errors carry an additional machine-readable ``error_code``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import config
from .backends.fxtwitter import supplement_views
from .exceptions import XtfError
from .i18n import set_lang, t
from .ledger import archive_tweets, ledger_stats, query_ledger
from .monitor import monitor_mentions
from .parsers.urls import extract_list_id, parse_article_id, parse_tweet_url
from .router import Router


def _emit(result: dict[str, Any], pretty: bool) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2 if pretty else None))


def _fail(result: dict[str, Any], exc: XtfError) -> dict[str, Any]:
    result["error"] = str(exc) or exc.code
    result["error_code"] = exc.code
    if getattr(exc, "causes", None):
        result["error_causes"] = {k: str(v) for k, v in exc.causes.items()}
    return result


def _archive_if_requested(args, result: dict[str, Any], tweet_dicts) -> None:
    """Archive fetched tweet dicts when --ledger is set (never fatal).

    Without --ledger this is a no-op, keeping legacy behavior identical.
    """
    if not args.ledger:
        return
    if result.get("error") or not tweet_dicts:
        return
    db = Path(args.ledger).expanduser()
    try:
        report = archive_tweets(
            db, tweet_dicts, source=f"xtf:{result.get('backend', 'fetch')}"
        )
        result["ledger"] = report
    except Exception as exc:  # archiving must not break a successful fetch
        result["ledger_error"] = f"{type(exc).__name__}: {exc}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xtf",
        description=(
            "Fetch tweets from X/Twitter.\n"
            "  --url <URL>              Single tweet via FxTwitter (zero deps)\n"
            "  --url <URL> --replies    Tweet replies via Nitter / browser\n"
            "  --user <username>        User timeline via Nitter / browser\n"
            "  --search <query>         Search tweets via Nitter\n"
            "  --user-info <username>   User profile via FxTwitter\n"
            "  --article <URL_or_ID>    X Article full text via browser\n"
            "  --monitor @username      Monitor X mentions (incremental, cron-friendly)\n"
            "  --list <list_url_or_id>  Fetch tweets from an X List via Nitter (browser fallback)\n"
            "\n"
            "Backends: auto (default, Nitter first then browser), nitter, browser.\n"
            "Configure Nitter instances via XTF_NITTER=url1,url2 (see README)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", "-u", help="Tweet URL (x.com or twitter.com)")
    parser.add_argument("--user", help="X/Twitter username (without @)")
    parser.add_argument("--search", "-s", metavar="QUERY", help="Search tweets (via Nitter)")
    parser.add_argument("--user-info", metavar="USERNAME", help="Get user profile info (via FxTwitter)")
    parser.add_argument("--article", "-a", metavar="URL_or_ID",
                        help="X Article URL (https://x.com/i/article/ID) or bare article ID")
    parser.add_argument("--monitor", "-m", metavar="@USERNAME",
                        help="Monitor X mentions for a username")
    parser.add_argument("--list", "-l", metavar="LIST_URL_OR_ID",
                        help="Fetch tweets from an X List (URL or ID; Nitter first, browser fallback)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max tweets for --user / max results for --monitor (default: 50 for --user, 10 for --monitor)")
    parser.add_argument("--replies", "-r", action="store_true", help="Fetch replies")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty print JSON")
    parser.add_argument("--text-only", "-t", action="store_true", help="Human-readable output")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds (default: 30)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Browser (Camofox) port (default: {config.DEFAULT_BROWSER_PORT})")
    parser.add_argument("--nitter", default=None,
                        help="Nitter instance(s), comma-separated. Overrides XTF_NITTER.")
    parser.add_argument("--backend", choices=["auto", "nitter", "browser"], default="auto",
                        help="Backend: nitter (direct HTTP), browser (Camofox/Playwright), auto (nitter first, browser fallback)")
    parser.add_argument("--browser-driver", choices=["camofox", "playwright"], default=None,
                        help="Browser driver (default: XTF_BROWSER env or camofox)")
    parser.add_argument("--ledger", metavar="DB",
                        help="SQLite ledger DB. With a fetch mode: archive results after fetch. "
                             "With --query/--stats: search/inspect the archive without fetching.")
    parser.add_argument("--query", metavar="TERM",
                        help="Search archived tweets by keyword (requires --ledger)")
    parser.add_argument("--stats", action="store_true",
                        help="Show ledger statistics (requires --ledger)")
    parser.add_argument("--lang", default=None, choices=["zh", "en"],
                        help="Output language for tool messages: zh (default) or en")
    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    set_lang(args.lang or config.default_lang())
    pretty = args.pretty

    modes = [bool(args.url), bool(args.user), bool(args.search),
             bool(args.user_info), bool(args.article), bool(args.monitor), bool(args.list)]
    ledger_mode = bool(args.query or args.stats)
    if ledger_mode and not args.ledger:
        print(t("err_prefix") + "--query/--stats require --ledger <db>", file=sys.stderr)
        sys.exit(1)
    if args.query and args.stats:
        print(t("err_prefix") + "--query and --stats are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if sum(modes) + int(ledger_mode) > 1:
        print(t("err_mutually_exclusive"), file=sys.stderr)
        sys.exit(1)
    if not any(modes) and (not args.ledger or not ledger_mode):
        parser.print_help()
        sys.exit(1)

    # ── Ledger-only modes: query / stats (no fetch) ─────────────────────
    if args.ledger and ledger_mode:
        db = Path(args.ledger).expanduser()
        result: dict[str, Any] = {"ledger": str(db)}
        try:
            if args.query:
                hits = query_ledger(db, keyword=args.query, limit=args.limit)
                for hit in hits:
                    hit.pop("raw_json", None)  # keep CLI output compact
                result.update({"query": args.query, "count": len(hits), "tweets": hits})
            else:
                result["stats"] = ledger_stats(db)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["error_code"] = "ledger_error"
            _emit(result, pretty)
            sys.exit(1)
        _emit(result, pretty)
        sys.exit(0)

    nitter_instances = None
    if args.nitter:
        nitter_instances = [config._normalize_instance(p) for p in args.nitter.split(",") if p.strip()]

    router = Router(
        backend=args.backend,
        nitter_instances=nitter_instances,
        browser_driver=args.browser_driver,
        browser_port=args.port,
        browser_nitter=nitter_instances[0] if nitter_instances else None,
    )

    # ── Mode: Search ─────────────────────────────────────────────────────
    if args.search:
        result: dict[str, Any] = {"query": args.search}
        try:
            tweets = [tw.to_dict() for tw in router.search(args.search, limit=args.limit)]
            result.update({"tweets": tweets, "count": len(tweets), "backend": router.last_backend})
        except XtfError as e:
            _fail(result, e)
        _archive_if_requested(args, result, result.get("tweets", []))
        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            print(t("search_header", query=args.search, count=result["count"]) + "\n")
            for i, tw in enumerate(result["tweets"], 1):
                print(f"[{i}] {tw.get('author_name','')} ({tw.get('author','')}) · {tw.get('time_ago','')}")
                print(f"     {tw.get('text','')[:200]}")
                print(f"     ❤ {tw.get('likes',0)}  💬 {tw.get('replies',0)}  👁 {tw.get('views',0)}")
                print()
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: User Info ──────────────────────────────────────────────────
    if args.user_info:
        result = {}
        try:
            result = router.fetch_user_info(args.user_info)
        except XtfError as e:
            result = _fail({"username": args.user_info}, e)
        if args.text_only:
            if result.get("error"):
                print(t("err_text_prefix", error=result["error"]), file=sys.stderr)
                sys.exit(1)
            print(f"@{result.get('username','')} ({result.get('display_name','')})")
            if result.get("bio"):
                print(t("info_bio", bio=result["bio"]))
            print(t("info_counts", tweets=result.get("tweets_count", 0),
                         following=result.get("following", 0),
                         followers=result.get("followers", 0)))
            if result.get("joined"):
                print(t("info_joined", joined=result["joined"]))
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: Mentions monitor ───────────────────────────────────────────
    if args.monitor:
        monitor_limit = args.limit if args.limit != 50 else 10
        use_nitter = args.backend == "nitter" or (
            args.backend == "auto" and router.nitter.available()
        )
        result = monitor_mentions(router, args.monitor, limit=monitor_limit,
                                  use_nitter=use_nitter)
        if result.get("error"):
            print(t("err_prefix") + result["error"], file=sys.stderr)
            sys.exit(2)
        if result.get("is_baseline"):
            if not args.text_only:
                _emit(result, pretty)
            sys.exit(0)
        new_mentions = result.get("new_mentions", [])
        if args.text_only:
            if new_mentions:
                print(t("monitor_header", username=result["username"], count=len(new_mentions)) + "\n")
                for idx, m in enumerate(new_mentions, 1):
                    print(f"[{idx}] {m['title']}")
                    print(f"     {m['url']}")
                    if m.get("snippet"):
                        print(f"     {m['snippet'][:120]}")
                    print()
        else:
            _emit(result, pretty)
        sys.exit(1 if new_mentions else 0)

    # ── Mode: User timeline ──────────────────────────────────────────────
    if args.user:
        result = {"username": args.user, "limit": args.limit}
        try:
            tweets = [tw.to_dict() for tw in router.fetch_timeline(args.user, limit=args.limit)]
            tweets = supplement_views(tweets)
            result.update({
                "tweets": tweets, "count": len(tweets),
                "backend": router.last_backend, "views_supplemented": True,
            })
            if not tweets:
                result["warning"] = t("warn_no_tweets")
        except XtfError as e:
            _fail(result, e)
        _archive_if_requested(args, result, result.get("tweets", []))
        _print_timeline_result(result, args, header=t("timeline_header", user=args.user,
                                                      count=result.get("count", 0)))
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: X Article ──────────────────────────────────────────────────
    if args.article:
        if args.backend == "nitter":
            print("[warning] --article requires a browser backend. "
                  "Nitter cannot fetch X Articles. Falling back to browser.", file=sys.stderr)
        article_id = parse_article_id(args.article)
        if not article_id:
            print(t("err_prefix") + t("err_invalid_article", input=args.article), file=sys.stderr)
            sys.exit(1)
        result = {"article_id": article_id}
        try:
            article = router.fetch_article(article_id)
            result = article.to_dict()
            if article.is_partial:
                result["warning"] = t("article_login_note")
        except XtfError as e:
            _fail(result, e)
        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            title = result.get("title") or "(no title)"
            author = result.get("author") or result.get("author_handle") or ""
            print(t("article_header", title=title))
            if author:
                print(f"@{result.get('author_handle', '').lstrip('@') or author}  {author}")
            print(t("article_words", word_count=result.get("word_count", 0)))
            if result.get("warning"):
                print(f"⚠️  {result['warning']}")
            print()
            print(result.get("content") or "(empty)")
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: Tweet replies ──────────────────────────────────────────────
    if args.url and args.replies:
        try:
            username, tweet_id = parse_tweet_url(args.url)
        except ValueError as e:
            _emit({"url": args.url, "error": str(e), "error_code": "invalid_input"}, pretty)
            sys.exit(1)
        result = {"url": args.url, "username": username, "tweet_id": tweet_id}
        try:
            replies = [r.to_dict() for r in router.fetch_replies(username, tweet_id)]
            replies = supplement_views(replies)
            result.update({
                "replies": replies, "reply_count": len(replies),
                "count": len(replies), "backend": router.last_backend,
                "views_supplemented": True,
            })
            if not replies:
                result["warning"] = t("warn_no_replies")
        except XtfError as e:
            _fail(result, e)
        if args.ledger:
            # Mark every reply as a reply to the parent tweet so the ledger
            # archives them with is_reply=1. Prefer any backend-provided value.
            parent_id = result.get("tweet_id") or ""
            for reply in result.get("replies", []):
                reply.setdefault("in_reply_to_status_id", parent_id)
        _archive_if_requested(args, result, result.get("replies", []))
        if args.text_only:
            if result.get("error"):
                print(t("err_prefix") + result["error"], file=sys.stderr)
                sys.exit(1)
            print(t("replies_header", url=args.url) + "\n")
            for idx, r in enumerate(result.get("replies", []), 1):
                print(f"[{idx}] {r['author_name']} ({r['author']}) · {r.get('time_ago', '')}")
                print(f"     {r['text']}")
                stats = f"     ❤ {r['likes']}  💬 {r['replies']}  👁 {r['views']}"
                if r.get("media"):
                    stats += "  " + t("media_label_with_urls", n=len(r["media"]),
                                      urls=", ".join(r["media"]))
                print(stats)
                print()
        else:
            _emit(result, pretty)
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: X List ─────────────────────────────────────────────────────
    if args.list:
        list_id = extract_list_id(args.list)
        if not list_id:
            print(t("err_prefix") + t("err_invalid_list", input=args.list), file=sys.stderr)
            sys.exit(1)
        result = {"list_id": list_id, "limit": args.limit}
        try:
            tweets = [tw.to_dict() for tw in router.fetch_list(list_id, limit=args.limit)]
            tweets = supplement_views(tweets)
            result.update({
                "tweets": tweets, "count": len(tweets),
                "backend": router.last_backend, "views_supplemented": True,
            })
            if not tweets:
                result["warning"] = t("warn_no_tweets")
        except XtfError as e:
            _fail(result, e)
        _archive_if_requested(args, result, result.get("tweets", []))
        _print_timeline_result(result, args, header=t("list_header", list_id=list_id,
                                                      count=result.get("count", 0)))
        sys.exit(1 if result.get("error") else 0)

    # ── Mode: Single tweet via FxTwitter ─────────────────────────────────
    try:
        username, tweet_id = parse_tweet_url(args.url)
    except ValueError as e:
        result = {"url": args.url, "error": str(e), "error_code": "invalid_input"}
        _emit(result, pretty)
        sys.exit(1)

    result = {"url": args.url, "username": username, "tweet_id": tweet_id}
    try:
        result["tweet"] = router.fetch_tweet(username, tweet_id)
    except XtfError as e:
        _fail(result, e)
    if result.get("tweet") and not result.get("error"):
        # fxtwitter dicts carry no tweet_id; inject the one from the URL.
        tweet_dict = dict(result["tweet"])
        tweet_dict.setdefault("tweet_id", result.get("tweet_id") or "")
        _archive_if_requested(args, result, [tweet_dict])
    else:
        _archive_if_requested(args, result, [])

    if args.text_only:
        tweet = result.get("tweet", {})
        if tweet.get("is_article") and tweet.get("article", {}).get("full_text"):
            article = tweet["article"]
            print(f"# {article['title']}\n")
            print(t("article_by", screen_name=tweet["screen_name"],
                    created_at=tweet.get("created_at", "")))
            print(t("article_stats", likes=tweet["likes"], retweets=tweet["retweets"],
                    views=tweet["views"]))
            print(t("article_words", word_count=article["word_count"]) + "\n")
            print(article["full_text"])
        elif tweet.get("text"):
            print(f"@{tweet['screen_name']}: {tweet['text']}")
            print(t("tweet_stats", likes=tweet["likes"], retweets=tweet["retweets"],
                    views=tweet["views"]))
        elif result.get("error"):
            print(t("err_prefix") + result["error"], file=sys.stderr)
            sys.exit(1)
    else:
        _emit(result, pretty)

    sys.exit(1 if result.get("error") else 0)


def _print_timeline_result(result: dict[str, Any], args, header: str) -> None:
    if args.text_only:
        if result.get("error"):
            print(t("err_prefix") + result["error"], file=sys.stderr)
            sys.exit(1)
        print(header + "\n")
        for idx, tw in enumerate(result.get("tweets", []), 1):
            print(f"[{idx}] {tw['author_name']} ({tw['author']}) · {tw.get('time_ago', '')}")
            print(f"     {tw['text']}")
            stats = f"     ❤ {tw['likes']}  💬 {tw['replies']}  👁 {tw['views']}"
            if tw.get("media"):
                stats += "  " + t("media_label", n=len(tw["media"]))
            print(stats)
            print()
    else:
        _emit(result, args.pretty)


if __name__ == "__main__":
    main()
