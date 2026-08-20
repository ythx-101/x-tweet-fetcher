"""SQLite tweet ledger — archive, dedupe, and query xtf fetch results.

Ported from the tweet-ledger importer (OpenClaw openclaw-data) and adapted to
xtf's ``Tweet`` model. The schema matches the tweet-ledger ``tweets`` table so
an xtf archive can be read by the existing ledger tooling and vice versa.

Idempotency: archiving is keyed on ``tweets.tweet_id`` (INSERT OR IGNORE);
existing rows are never deleted or overwritten.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

#: Key fallbacks accept richer backend dicts (FxTwitter / Nitter raw rows)
#: when available. Relative time fields (``time_ago``/``time``, e.g. "3h")
#: are deliberately excluded from ``_CREATED_KEYS``: they are never real
#: timestamps and would corrupt ordering and stats time ranges.
_TEXT_KEYS = ("full_text", "text", "content", "tweet")
_ID_KEYS = ("tweet_id", "id_str", "id")
_CREATED_KEYS = ("created_at", "timestamp", "date")
_LANG_KEYS = ("lang", "language")
_REPLY_KEYS = ("in_reply_to_status_id", "in_reply_to_status_id_str")
_RT_KEYS = ("retweeted_status_id", "retweeted_status_id_str")
_QT_KEYS = ("quoted_status_id", "quoted_status_id_str")
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

_INSERT_SQL = """
    INSERT OR IGNORE INTO tweets (
        tweet_id, created_at, full_text, lang, source_file, is_reply,
        in_reply_to_status_id, retweeted_status_id, quoted_status_id,
        urls_json, media_json, raw_json, imported_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the ledger schema if missing (compatible with tweet-ledger)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tweets (
            tweet_id TEXT PRIMARY KEY,
            created_at TEXT,
            full_text TEXT NOT NULL,
            lang TEXT,
            source_file TEXT,
            is_reply INTEGER DEFAULT 0,
            in_reply_to_status_id TEXT,
            retweeted_status_id TEXT,
            quoted_status_id TEXT,
            urls_json TEXT,
            media_json TEXT,
            raw_json TEXT NOT NULL,
            imported_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tweets_created_at ON tweets(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tweets_reply ON tweets(in_reply_to_status_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tweets_quoted ON tweets(quoted_status_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            tweet_count INTEGER NOT NULL,
            notes TEXT
        )
        """
    )


def _first(record: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _extract_urls(text: str) -> List[str]:
    """Extract http(s) links from free text when the record has no urls list."""
    return list(dict.fromkeys(_URL_RE.findall(text)))


def _normalize_list_field(
    record: Dict[str, Any],
    field: str,
    serialized_field: str,
    fallback: List[Any],
) -> List[Any]:
    """Return a JSON-array-compatible list from a native or serialized field.

    Native fields may be lists, tuples, or one scalar string. Serialized
    ``*_json`` fields must decode to a JSON array. Invalid shapes raise
    ``ValueError`` so ``archive_tweets`` skips the malformed record instead of
    storing a double-encoded string that downstream readers cannot consume.
    """
    value = record.get(field)
    serialized = False
    if value in (None, "", []):
        value = record.get(serialized_field)
        serialized = value not in (None, "", [])
    if value in (None, "", []):
        return list(fallback)

    if serialized and isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{serialized_field} must contain a valid JSON array") from exc
    elif isinstance(value, str):
        value = [value]

    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        source_name = serialized_field if serialized else field
        raise ValueError(f"{source_name} must be a list or JSON array")
    return value


def normalize(
    record: Dict[str, Any],
    source: str,
    imported_at: str,
) -> Tuple[str, ...]:
    """Map a tweet dict (xtf ``to_dict()`` or a raw backend row) to a ledger row.

    Raises ValueError when the record has no usable tweet id or text, or when a
    serialized list field is malformed.
    """
    tweet_id = _first(record, *_ID_KEYS)
    text = _first(record, *_TEXT_KEYS)
    if not tweet_id or not text:
        raise ValueError("record missing tweet_id/id or full_text/text")

    created_at = _first(record, *_CREATED_KEYS)
    lang = _first(record, *_LANG_KEYS)
    in_reply_to = _first(record, *_REPLY_KEYS)
    retweeted_id = _first(record, *_RT_KEYS)

    quoted_id = _first(record, *_QT_KEYS)
    if not quoted_id:
        quoted = record.get("quoted_tweet")
        if isinstance(quoted, dict):
            quoted_id = _first(quoted, *_ID_KEYS)
        elif quoted is not None and hasattr(quoted, "to_dict"):
            quoted_id = quoted.to_dict().get("tweet_id") or None

    urls = _normalize_list_field(record, "urls", "urls_json", _extract_urls(text))
    media = _normalize_list_field(record, "media", "media_json", [])

    return (
        tweet_id,
        created_at,
        text,
        lang,
        str(source),
        int(bool(in_reply_to)),
        in_reply_to,
        retweeted_id,
        quoted_id,
        json.dumps(urls, ensure_ascii=False),
        json.dumps(media, ensure_ascii=False),
        json.dumps(record, ensure_ascii=False, sort_keys=True),
        imported_at,
    )


def _as_dict(tweet: Union[Dict[str, Any], Any]) -> Dict[str, Any]:
    """Accept either a dict or any object exposing ``to_dict()`` (e.g. Tweet)."""
    if hasattr(tweet, "to_dict"):
        return tweet.to_dict()
    return dict(tweet)


def count_existing_tweets(db_path: Path, tweet_ids: Iterable[str]) -> int:
    """Count how many of the given ids already exist (read-only)."""
    ids = list(tweet_ids)
    if not ids or not Path(db_path).exists():
        return 0
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        count = 0
        for offset in range(0, len(ids), 900):
            chunk = ids[offset : offset + 900]
            placeholders = ",".join("?" for _ in chunk)
            count += conn.execute(
                f"SELECT COUNT(*) FROM tweets WHERE tweet_id IN ({placeholders})",
                chunk,
            ).fetchone()[0]
        return count
    finally:
        conn.close()


def archive_tweets(
    db_path: Path,
    tweets: Iterable[Union[Dict[str, Any], Any]],
    source: str = "xtf",
) -> Dict[str, Any]:
    """Archive tweet dicts/objects into the ledger, deduping on tweet_id.

    Returns a report dict with input/inserted/duplicate/skipped counts and the
    ids of newly inserted rows.
    """
    db_path = Path(db_path)
    imported_at = utc_now()
    records = [_as_dict(t) for t in tweets]

    rows: List[Tuple[str, ...]] = []
    skipped = 0
    for record in records:
        try:
            rows.append(normalize(record, source, imported_at))
        except ValueError:
            skipped += 1

    if not db_path.parent.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        ensure_tables(conn)
        inserted_ids: List[str] = []
        for row in rows:
            cursor = conn.execute(_INSERT_SQL, row)
            if cursor.rowcount == 1:
                inserted_ids.append(row[0])
        inserted = len(inserted_ids)
        duplicates = len(rows) - inserted
        conn.execute(
            "INSERT INTO import_receipts(source_path, imported_at, tweet_count, notes)"
            " VALUES (?, ?, ?, ?)",
            (
                str(source),
                imported_at,
                inserted,
                f"input={len(records)} skipped={skipped} duplicates={duplicates}",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "input_records": len(records),
        "inserted": inserted,
        "inserted_ids": inserted_ids,
        "skipped": skipped,
        "duplicates": duplicates,
    }


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so keywords match literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def query_ledger(
    db_path: Path,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Search archived tweets by keyword (substring match on full_text)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    conn = _connect_ro(db_path)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tweets'"
        ).fetchone()
        if table is None:
            # DB file exists but has no ledger schema — nothing to query.
            return []
        sql = "SELECT * FROM tweets"
        params: List[Any] = []
        if keyword:
            sql += " WHERE full_text LIKE ? ESCAPE '\\'"
            params.append(f"%{_escape_like(keyword)}%")
        sql += " ORDER BY imported_at DESC, tweet_id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def _empty_stats(exists: bool) -> Dict[str, Any]:
    """Stable stats skeleton so callers can rely on the full key set."""
    return {
        "exists": exists,
        "total_tweets": 0,
        "total_replies": 0,
        "total_quoted": 0,
        "total_retweeted": 0,
        "total_with_media": 0,
        "total_with_urls": 0,
        "first_created_at": None,
        "last_created_at": None,
        "last_imported_at": None,
        "langs": {},
    }


def ledger_stats(db_path: Path) -> Dict[str, Any]:
    """Aggregate stats over the archived tweets.

    Never returns None and never raises for a missing/empty/foreign DB:
    the returned dict always carries the full key set (see ``_empty_stats``).
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return _empty_stats(exists=False)
    conn = _connect_ro(db_path)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tweets'"
        ).fetchone()
        if table is None:
            return _empty_stats(exists=True)
        total = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
        if total == 0:
            return _empty_stats(exists=True)
        replies = conn.execute("SELECT COUNT(*) FROM tweets WHERE is_reply = 1").fetchone()[0]
        quoted = conn.execute(
            "SELECT COUNT(*) FROM tweets WHERE quoted_status_id IS NOT NULL"
        ).fetchone()[0]
        retweeted = conn.execute(
            "SELECT COUNT(*) FROM tweets WHERE retweeted_status_id IS NOT NULL"
        ).fetchone()[0]
        with_media = conn.execute(
            "SELECT COUNT(*) FROM tweets WHERE media_json NOT IN ('', '[]')"
        ).fetchone()[0]
        with_urls = conn.execute(
            "SELECT COUNT(*) FROM tweets WHERE urls_json NOT IN ('', '[]')"
        ).fetchone()[0]
        first, last = conn.execute(
            "SELECT MIN(created_at), MAX(created_at) FROM tweets"
        ).fetchone()
        last_import = conn.execute(
            "SELECT MAX(imported_at) FROM tweets"
        ).fetchone()[0]
        lang_rows = conn.execute(
            "SELECT lang, COUNT(*) AS n FROM tweets WHERE lang IS NOT NULL"
            " GROUP BY lang ORDER BY n DESC LIMIT 10"
        ).fetchall()
        return {
            "exists": True,
            "total_tweets": total,
            "total_replies": replies,
            "total_quoted": quoted,
            "total_retweeted": retweeted,
            "total_with_media": with_media,
            "total_with_urls": with_urls,
            "first_created_at": first,
            "last_created_at": last,
            "last_imported_at": last_import,
            "langs": {row["lang"]: row["n"] for row in lang_rows},
        }
    finally:
        conn.close()
