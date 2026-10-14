from pathlib import Path

from xtf.parsers.nitter_html import parse_tweet_detail_html

FIX = Path(__file__).parent / "fixtures" / "nitter_status_author_thread.html"


def test_author_self_reply_is_captured_with_full_link():
    html = FIX.read_text(encoding="utf-8")
    d = parse_tweet_detail_html(html, "YuLin807", "2110063107968245984")
    assert "Kami" in d["text"]
    rs = d["replies_list"]
    assert len(rs) == 1
    r = rs[0]
    assert r["is_author_thread"] is True
    assert r["tweet_id"] == "2110063376391180729"
    full = "https://drive.google.com/file/d/1Twv2QimYZdEju4u21N7BED_4AT7VRjOG/view?usp=drivesdk"
    assert r["links"] == [full]
    assert full in r["text"]
