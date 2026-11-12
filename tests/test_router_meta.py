"""Router order, version consistency, and --text-only i18n tests (no network)."""
import re
from pathlib import Path

import pytest

import xtf
from xtf import cli, i18n
from xtf.exceptions import BackendUnavailable
from xtf.router import Router

ROOT = Path(__file__).parent.parent


def test_fetch_list_tries_nitter_before_browser(monkeypatch):
    router = Router()
    calls = []

    def nitter_list(list_id, limit=20):
        calls.append("nitter")
        raise BackendUnavailable("no nitter")

    def browser_list(list_id, limit=20):
        calls.append("browser")
        return []

    monkeypatch.setattr(router.nitter, "fetch_list", nitter_list)
    monkeypatch.setattr(router.browser, "fetch_list", browser_list)
    assert router.fetch_list("123") == []
    assert calls == ["nitter", "browser"]
    assert router.last_backend == "browser"


def test_version_consistent():
    version_file = (ROOT / "VERSION").read_text().strip()
    pyproject = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m
    assert version_file == m.group(1) == xtf.__version__


class _FakeInfoRouter:
    def __init__(self, *a, **k):
        pass

    def fetch_user_info(self, username):
        return {"username": "alice", "display_name": "Alice", "bio": "hello",
                "tweets_count": 1, "following": 2, "followers": 3, "joined": "2020"}


@pytest.mark.parametrize("lang,expected", [
    ("en", ["Bio: hello", "Tweets: 1 | Following: 2 | Followers: 3", "Joined: 2020"]),
    ("zh", ["简介: hello", "推文: 1 | 关注: 2 | 粉丝: 3", "加入: 2020"]),
])
def test_user_info_text_only_follows_lang(monkeypatch, capsys, lang, expected):
    monkeypatch.setattr(cli, "Router", _FakeInfoRouter)
    try:
        with pytest.raises(SystemExit) as exc:
            cli.main(["--user-info", "alice", "--text-only", "--lang", lang])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        for line in expected:
            assert line in out
    finally:
        i18n.set_lang("zh")
