"""Tests for the sqlite tweet ledger: schema, archiving, dedupe, query, stats."""
import json
import sqlite3

import pytest

from xtf.ledger import (
    archive_tweets,
    count_existing_tweets,
    ensure_tables,
    ledger_stats,
    normalize,
    query_ledger,
)
from xtf.models import Tweet


def _tweet_dict(tweet_id: str, text: str, **extra) -> dict:
    return {"tweet_id": tweet_id, "text": text, **extra}


# ── schema ────────────────────────────────────────────────────────────────
def test_ensure_tables_creates_ledger_schema(tmp_path):
    db = tmp_path / "ledger.db"
    conn = sqlite3.connect(db)
    try:
        ensure_tables(conn)
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"tweets", "import_receipts"} <= tables
        columns = [row[1] for row in conn.execute("PRAGMA table_info(tweets)")]
        for col in (
            "tweet_id", "created_at", "full_text", "lang", "is_reply",
            "in_reply_to_status_id", "retweeted_status_id", "quoted_status_id",
            "urls_json", "media_json", "raw_json", "imported_at",
        ):
            assert col in columns
    finally:
        conn.close()


# ── archiving + dedupe ───────────────────────────────────────────────────
def test_archive_inserts_and_dedupes(tmp_path):
    db = tmp_path / "ledger.db"
    first = archive_tweets(db, [_tweet_dict("1", "hello world"), _tweet_dict("2", "second")])
    assert first["inserted"] == 2 and first["duplicates"] == 0 and first["skipped"] == 0

    second = archive_tweets(db, [_tweet_dict("1", "hello world"), _tweet_dict("3", "third")])
    assert second["inserted"] == 1 and second["duplicates"] == 1
    assert second["inserted_ids"] == ["3"]

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0] == 3
    finally:
        conn.close()


def test_archive_accepts_tweet_objects(tmp_path):
    db = tmp_path / "ledger.db"
    tweet = Tweet(author="@a", author_name="A", text="from model",
                  tweet_id="42", media=["https://pbs.twimg.com/x.jpg"])
    report = archive_tweets(db, [tweet])
    assert report["inserted"] == 1
    row = query_ledger(db, limit=10)[0]
    assert row["tweet_id"] == "42"
    assert json.loads(row["media_json"]) == ["https://pbs.twimg.com/x.jpg"]


def test_archive_skips_records_without_id_or_text(tmp_path):
    db = tmp_path / "ledger.db"
    report = archive_tweets(db, [
        _tweet_dict("1", "ok"),
        {"tweet_id": ""},
        {"text": "no id"},
        {},
    ])
    assert report["inserted"] == 1 and report["skipped"] == 3
    assert report["inserted_ids"] == ["1"]


def test_archive_skips_malformed_serialized_list_fields(tmp_path):
    db = tmp_path / "ledger.db"
    report = archive_tweets(db, [
        _tweet_dict("1", "ok", urls_json='["https://t.co/a"]'),
        _tweet_dict("2", "bad", media_json="{not-json"),
    ])
    assert report["inserted"] == 1
    assert report["skipped"] == 1
    row = query_ledger(db)[0]
    assert json.loads(row["urls_json"]) == ["https://t.co/a"]


def test_archive_is_idempotent_with_existing_db(tmp_path):
    db = tmp_path / "ledger.db"
    archive_tweets(db, [_tweet_dict("1", "x"), _tweet_dict("2", "y")])
    before = count_existing_tweets(db, ["1", "2", "3"])
    assert before == 2
    report = archive_tweets(db, [_tweet_dict("1", "x"), _tweet_dict("3", "z")])
    assert report["inserted"] == 1
    assert count_existing_tweets(db, ["1", "2", "3"]) == 3


# ── normalize ────────────────────────────────────────────────────────────
def test_normalize_from_tweet_to_dict_derives_fields():
    d = Tweet(
        author="@qy", author_name="QingYue", text="see https://x.com/a/status/9",
        tweet_id="100", media=["https://pbs.twimg.com/m.jpg"],
        quoted_tweet=Tweet(tweet_id="99", text="quoted"),
    ).to_dict()
    row = normalize(d, "test", "2026-08-09T00:00:00+00:00")
    assert row[0] == "100"                        # tweet_id
    assert row[2] == d["text"]                    # full_text
    assert row[6] is None                         # in_reply_to_status_id
    assert row[8] == "99"                         # quoted_status_id from quoted_tweet
    urls = json.loads(row[9])
    assert "https://x.com/a/status/9" in urls     # urls extracted from text
    media = json.loads(row[10])
    assert media == ["https://pbs.twimg.com/m.jpg"]
    raw = json.loads(row[11])
    assert raw["author"] == "@qy"                 # raw_json round-trips


def test_normalize_accepts_raw_backend_keys():
    row = normalize(
        {"id": "7", "full_text": "raw row", "created_at": "2026-01-01T00:00:00Z",
         "lang": "zh", "in_reply_to_status_id_str": "6",
         "retweeted_status_id": "5", "quoted_status_id": "4",
         "urls": ["https://t.co/a"], "media": ["https://pbs.twimg.com/b.jpg"]},
        "nitter",
        "2026-08-09T00:00:00+00:00",
    )
    assert row[0] == "7" and row[1] == "2026-01-01T00:00:00Z"
    assert row[3] == "zh" and row[6] == "6" and row[7] == "5" and row[8] == "4"
    assert json.loads(row[9]) == ["https://t.co/a"]


def test_normalize_accepts_serialized_json_fields_without_double_encoding():
    row = normalize(
        {
            "tweet_id": "9",
            "text": "serialized fields",
            "urls_json": json.dumps(["https://t.co/a"]),
            "media_json": json.dumps([{"url": "https://pbs.twimg.com/a.jpg"}]),
        },
        "legacy-db",
        "2026-08-09T00:00:00+00:00",
    )
    urls = json.loads(row[9])
    media = json.loads(row[10])
    assert urls == ["https://t.co/a"]
    assert media == [{"url": "https://pbs.twimg.com/a.jpg"}]
    assert not isinstance(urls, str)
    assert not isinstance(media, str)


def test_normalize_wraps_native_scalar_url_as_a_list():
    row = normalize(
        {"tweet_id": "10", "text": "single URL", "urls": "https://x.com/a"},
        "backend",
        "2026-08-09T00:00:00+00:00",
    )
    assert json.loads(row[9]) == ["https://x.com/a"]


def test_normalize_rejects_malformed_serialized_json_fields():
    with pytest.raises(ValueError, match="urls_json"):
        normalize(
            {"tweet_id": "11", "text": "bad urls", "urls_json": "not-json"},
            "legacy-db",
            "2026-08-09T00:00:00+00:00",
        )
    with pytest.raises(ValueError, match="media_json"):
        normalize(
            {"tweet_id": "12", "text": "bad media", "media_json": '{"url":"x"}'},
            "legacy-db",
            "2026-08-09T00:00:00+00:00",
        )


def test_normalize_ignores_relative_time_keys():
    # B1: time_ago / time are relative ("3h"), never real timestamps.
    row = normalize(
        {"tweet_id": "8", "text": "x", "time_ago": "3h", "time": "1h"},
        "t", "2026-08-09T00:00:00+00:00",
    )
    assert row[1] is None  # created_at stays unset


def test_normalize_rejects_conversation_id_only():
    # S1: conversation_id is not a stable tweet id; do not dedupe on it.
    with pytest.raises(ValueError):
        normalize(
            {"conversation_id": "123", "text": "no real id"},
            "t", "2026-08-09T00:00:00+00:00",
        )


def test_normalize_rejects_missing_fields():
    with pytest.raises(ValueError):
        normalize({"text": "no id"}, "t", "2026-08-09T00:00:00+00:00")
    with pytest.raises(ValueError):
        normalize({"tweet_id": "1"}, "t", "2026-08-09T00:00:00+00:00")


# ── query + stats ────────────────────────────────────────────────────────
def test_query_ledger_keyword_and_limit(tmp_path):
    db = tmp_path / "ledger.db"
    archive_tweets(db, [
        _tweet_dict("1", "openclaw agent notes", created_at="2026-08-01T00:00:00Z"),
        _tweet_dict("2", "nitter outage today", created_at="2026-08-02T00:00:00Z"),
        _tweet_dict("3", "another openclaw tip", created_at="2026-08-03T00:00:00Z"),
    ])
    hits = query_ledger(db, keyword="openclaw")
    assert {h["tweet_id"] for h in hits} == {"1", "3"}
    assert query_ledger(db, keyword="nitter")[0]["tweet_id"] == "2"
    assert len(query_ledger(db, limit=2)) == 2


def test_query_ledger_missing_db(tmp_path):
    assert query_ledger(tmp_path / "nope.db", keyword="x") == []


def test_query_ledger_missing_table_returns_empty(tmp_path):
    # B2: file exists but has no tweets table -> [] instead of OperationalError.
    db = tmp_path / "foreign.db"
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    assert query_ledger(db) == []
    assert query_ledger(db, keyword="x") == []


def test_query_ledger_sorts_by_imported_at(tmp_path, monkeypatch):
    # B1: sort by imported_at DESC (not relative created_at), tie-break tweet_id.
    import xtf.ledger as ledger
    db = tmp_path / "ledger.db"
    stamps = iter(["2026-08-01T00:00:00+00:00", "2026-08-02T00:00:00+00:00"])
    monkeypatch.setattr(ledger, "utc_now", lambda: next(stamps))
    archive_tweets(db, [_tweet_dict("1", "older import", created_at="2026-08-05T00:00:00Z")])
    archive_tweets(db, [_tweet_dict("2", "newer import", created_at="2026-08-01T00:00:00Z")])
    ids = [h["tweet_id"] for h in query_ledger(db)]
    assert ids == ["2", "1"]


def test_query_ledger_escapes_like_metacharacters(tmp_path):
    # S3: % and _ must match literally, not as LIKE wildcards.
    db = tmp_path / "ledger.db"
    archive_tweets(db, [
        _tweet_dict("1", "progress 100% done"),
        _tweet_dict("2", "progress 1000 done"),
        _tweet_dict("3", "use snake_case names"),
        _tweet_dict("4", "use snake case names"),
    ])
    assert [h["tweet_id"] for h in query_ledger(db, keyword="100%")] == ["1"]
    assert [h["tweet_id"] for h in query_ledger(db, keyword="snake_case")] == ["3"]


def test_ledger_stats(tmp_path):
    db = tmp_path / "ledger.db"
    archive_tweets(db, [
        _tweet_dict("1", "hello", lang="zh"),
        _tweet_dict("2", "world", lang="en"),
        _tweet_dict("3", "reply here", lang="zh",
                    in_reply_to_status_id="1"),
        _tweet_dict("4", "with media", media=["https://pbs.twimg.com/m.jpg"]),
        _tweet_dict("5", "with link https://t.co/x"),
    ])
    stats = ledger_stats(db)
    assert stats["exists"] is True
    assert stats["total_tweets"] == 5
    assert stats["total_replies"] == 1
    assert stats["total_with_media"] == 1
    assert stats["total_with_urls"] == 1
    assert stats["langs"]["zh"] == 2 and stats["langs"]["en"] == 1
    assert stats["last_imported_at"]


def test_ledger_stats_missing_db(tmp_path):
    assert ledger_stats(tmp_path / "nope.db")["total_tweets"] == 0


# ── stats hardening (never None, never crash) ───────────────────────────
def test_ledger_stats_empty_db(tmp_path):
    db = tmp_path / "ledger.db"
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        ensure_tables(conn)
    finally:
        conn.close()
    stats = ledger_stats(db)
    assert stats["exists"] is True and stats["total_tweets"] == 0
    for key in ("total_replies", "total_quoted", "total_retweeted",
                "total_with_media", "total_with_urls", "first_created_at",
                "last_created_at", "last_imported_at"):
        assert key in stats


def test_ledger_stats_foreign_db_no_crash(tmp_path):
    db = tmp_path / "foreign.db"
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        conn.execute("CREATE TABLE other (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    stats = ledger_stats(db)
    assert stats["exists"] is True and stats["total_tweets"] == 0
