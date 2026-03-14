"""
tweet_growth.py — Tweet Growth Tracker 核心模块
x-tweet-fetcher skill 的新功能

功能：
  1. 新推文前 48h 自动提频（15分钟一次）
  2. ETCH 导数检测 + 滑窗平均（归一化到 per-hour）
  3. 爆点时间窗口精确定位
  4. 同时段话题交叉分析（调用 x_discover）
  5. 传播模式判断（大V驱动 vs 算法驱动）
"""

import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from growth_config import (
    DATA_FILE, DISCOVER_CACHE,
    NEW_TWEET_HOURS, FAST_INTERVAL_MIN, NORM_INTERVAL_MIN,
    ETCH_WINDOW_SIZE, ETCH_SPIKE_RATE, ETCH_CONFIRM_COUNT, ETCH_SURGE_OVERRIDE,
    SATURATION_WINDOW, SATURATION_THRESHOLD,
    WEIGHT_VIEWS, WEIGHT_LIKES, WEIGHT_BOOKMARKS, WEIGHT_RETWEETS, WEIGHT_REPLIES,
    INFLUENCER_RT_RATIO, ALGORITHM_RT_RATIO,
    CROSS_SEARCH_RESULTS, CROSS_TIME_WINDOW_H,
)

FXTWITTER_API = "https://api.fxtwitter.com/status/{tweet_id}"


# ─── 数据层（带文件锁，防止双频 cron 同时写入冲突）────────────────────────────

LOCK_FILE = DATA_FILE.with_suffix(".lock")


def _acquire_lock():
    """返回持有排他锁的文件对象，调用方负责关闭（即释放锁）"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lf = open(LOCK_FILE, "w")
    fcntl.flock(lf, fcntl.LOCK_EX)
    return lf


def load_data() -> dict:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return {"tweets": {}}
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {"tweets": {}}


def save_data(data: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)  # 原子替换


# ─── FxTwitter 抓取 ────────────────────────────────────────────────────────────

def fetch_tweet_stats(tweet_id: str, retries: int = 2) -> dict | None:
    url = FXTWITTER_API.format(tweet_id=tweet_id)
    req = urllib.request.Request(url, headers={"User-Agent": "tweet-growth/2.1"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.load(resp)
            tweet = raw.get("tweet") or raw.get("status")
            if not tweet:
                return None
            # created_at: FxTwitter 有时返回 Unix int，有时 ISO 字符串
            created = tweet.get("created_at", 0)
            if isinstance(created, str) and created.isdigit():
                created = int(created)
            return {
                "views":      int(tweet.get("views", 0) or 0),
                "likes":      int(tweet.get("likes", 0) or 0),
                "retweets":   int(tweet.get("retweets", 0) or 0),
                "bookmarks":  int(tweet.get("bookmarks", 0) or 0),
                "replies":    int(tweet.get("replies", 0) or 0),
                "created_at": created,
            }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt < retries:
                time.sleep(2 ** attempt)
        except Exception:
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


# ─── 时间工具 ──────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def tweet_age_hours(record: dict) -> float:
    """推文从发出到现在过了多少小时"""
    history = record.get("history", [])
    if not history:
        return 999.0
    created = history[0].get("created_at", 0)
    try:
        if isinstance(created, (int, float)) and created > 1e9:
            dt = datetime.fromtimestamp(created, tz=timezone.utc)
        elif isinstance(created, str):
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            raise ValueError
        return (now_utc() - dt).total_seconds() / 3600
    except Exception:
        # fallback：用第一条采样时间
        try:
            dt = datetime.fromisoformat(history[0]["ts"])
            return (now_utc() - dt).total_seconds() / 3600
        except Exception:
            return 999.0


def should_sample(record: dict, fast_mode: bool) -> bool:
    """根据推文年龄和当前运行模式，判断是否该采这条推文"""
    age = tweet_age_hours(record)
    is_new = age < NEW_TWEET_HOURS
    if fast_mode:
        return is_new    # fast pass：只采新推文（<48h）
    return not is_new    # normal pass：只采老推文，新推文由 fast cron 负责


# ─── ETCH 检测（归一化到 per-hour）────────────────────────────────────────────

def composite_score(snap: dict) -> float:
    return (
        snap["views"]     * WEIGHT_VIEWS +
        snap["likes"]     * WEIGHT_LIKES +
        snap["bookmarks"] * WEIGHT_BOOKMARKS +
        snap["retweets"]  * WEIGHT_RETWEETS +
        snap["replies"]   * WEIGHT_REPLIES
    )


def _hours_between(snap_a: dict, snap_b: dict) -> float:
    """两个采样点之间的小时数，最小0.01防除零"""
    try:
        ta = datetime.fromisoformat(snap_a["ts"])
        tb = datetime.fromisoformat(snap_b["ts"])
        return max(abs((tb - ta).total_seconds()) / 3600, 0.01)
    except Exception:
        return 1.0  # 默认1小时


def _hourly_rate(val_prev: float, val_curr: float, hours: float) -> float:
    """每小时增量（归一化后的比例）"""
    if val_prev <= 0:
        return 0.0
    return (val_curr - val_prev) / val_prev / hours


def detect_spike(history: list[dict]) -> dict:
    """
    ETCH 导数检测，所有增速归一化到 per-hour。
    返回：
      spike_score  — 最近窗口综合增速（相对基线，归一化）
      view_rate    — 最近两样本浏览量每小时增速
      confirmed    — 是否连续3窗口均超阈值
      reason       — 确认原因文字
    """
    result = {"spike_score": 0.0, "view_rate": 0.0, "confirmed": False, "reason": ""}

    if len(history) < ETCH_WINDOW_SIZE + 1:
        return result

    # 1. 最近两点的浏览量每小时增速
    prev, curr = history[-2], history[-1]
    hours_last = _hours_between(prev, curr)
    result["view_rate"] = _hourly_rate(prev["views"], curr["views"], hours_last)

    # 2. 滑窗内综合得分每小时增速 vs 基线
    window = history[-(ETCH_WINDOW_SIZE + 1):]
    scores = [composite_score(s) for s in window]
    # 计算窗口内各相邻点的每小时增速
    hourly_deltas = []
    for i in range(1, len(window)):
        h = _hours_between(window[i-1], window[i])
        if scores[i-1] > 0:
            hourly_deltas.append((scores[i] - scores[i-1]) / scores[i-1] / h)
    if not hourly_deltas:
        return result

    baseline = sum(hourly_deltas[:-1]) / max(len(hourly_deltas) - 1, 1) if len(hourly_deltas) > 1 else 0
    latest_rate = hourly_deltas[-1]
    spike_score = latest_rate - baseline
    result["spike_score"] = spike_score

    # 3. 单窗口巨大涌入直接确认
    if latest_rate >= ETCH_SURGE_OVERRIDE:
        result["confirmed"] = True
        result["reason"] = f"单窗口涌入 +{latest_rate:.0%}/h"
        return result

    # 4. 连续 ETCH_CONFIRM_COUNT 个窗口均超阈值
    if len(history) >= ETCH_CONFIRM_COUNT + ETCH_WINDOW_SIZE:
        confirms = 0
        for i in range(1, ETCH_CONFIRM_COUNT + 1):
            a = history[-(i + 1)]
            b = history[-i]
            h = _hours_between(a, b)
            rate = _hourly_rate(a["views"], b["views"], h)
            if rate >= ETCH_SPIKE_RATE:
                confirms += 1
        if confirms >= ETCH_CONFIRM_COUNT:
            result["confirmed"] = True
            result["reason"] = f"连续{ETCH_CONFIRM_COUNT}窗口增速≥{ETCH_SPIKE_RATE:.0%}/h"

    return result


def detect_saturation(history: list[dict]) -> bool:
    """连续多个样本每小时增速都低于阈值，判定进入长尾"""
    if len(history) < SATURATION_WINDOW + 1:
        return False
    window = history[-(SATURATION_WINDOW + 1):]
    for i in range(1, len(window)):
        h = _hours_between(window[i-1], window[i])
        rate = _hourly_rate(window[i-1]["views"], window[i]["views"], h)
        if rate > SATURATION_THRESHOLD:
            return False
    return True


# ─── 功能3：爆点时间窗口精确定位 ─────────────────────────────────────────────

def find_burst_windows(history: list[dict]) -> list[dict]:
    """
    找出所有连续高增长区间。
    返回：[{start_ts, end_ts, views_gained, peak_rate, duration_h}]，按 views_gained 降序。
    """
    if len(history) < 2:
        return []

    # 计算每个相邻样本对的每小时增速
    rates = []
    for i in range(1, len(history)):
        h = _hours_between(history[i-1], history[i])
        rate = _hourly_rate(history[i-1]["views"], history[i]["views"], h)
        rates.append((i, rate))

    # 找连续超过阈值的区间
    windows = []
    in_burst = False
    burst_start = None

    for idx, (i, rate) in enumerate(rates):
        if rate >= ETCH_SPIKE_RATE and not in_burst:
            in_burst = True
            burst_start = i - 1
        elif rate < ETCH_SPIKE_RATE and in_burst:
            in_burst = False
            burst_end = i
            windows.append(_make_window(history, burst_start, burst_end, rates))
    if in_burst:
        windows.append(_make_window(history, burst_start, len(history) - 1, rates))

    return sorted(windows, key=lambda w: w["views_gained"], reverse=True)


def _make_window(history: list[dict], start: int, end: int, rates: list) -> dict:
    duration_h = _hours_between(history[start], history[end])
    views_gained = history[end]["views"] - history[start]["views"]
    # rates[i] 表示 history[i-1] → history[i] 的增速，所以区间用 start < i <= end
    window_rates = [r for i, r in rates if start < i <= end]
    peak_rate = max(window_rates) if window_rates else 0.0
    return {
        "start_ts":    history[start]["ts"],
        "end_ts":      history[end]["ts"],
        "views_gained": views_gained,
        "peak_rate":   round(peak_rate, 3),
        "duration_h":  round(duration_h, 2),
    }


# ─── 功能4：同时段话题交叉分析 ───────────────────────────────────────────────

def cross_analyze_burst(record: dict, burst: dict) -> dict:
    """
    在爆点时间窗口内，搜索同话题推文，判断是否有外部事件驱动。
    burst — find_burst_windows() 返回的单个窗口
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from x_discover import discover_tweets
    except ImportError:
        return {"error": "x_discover 不可用", "candidates": []}

    keywords = _extract_keywords(record)
    if not keywords:
        return {"keywords": [], "candidates": []}

    # DuckDuckGo timelimit: 'd'=1天, 'w'=1周
    # 爆点窗口如果在最近24h内，搜 'd'；否则搜 'w'
    try:
        burst_end = datetime.fromisoformat(burst["end_ts"])
        if burst_end.tzinfo is None:
            burst_end = burst_end.replace(tzinfo=timezone.utc)
        hours_ago = (now_utc() - burst_end).total_seconds() / 3600
        timelimit = "d" if hours_ago < 24 else "w"
    except Exception:
        timelimit = "w"

    result = discover_tweets(
        keywords=keywords,
        max_results=CROSS_SEARCH_RESULTS,
        timelimit=timelimit,
        cache_file=str(DISCOVER_CACHE),
    )

    return {
        "keywords":   keywords,
        "timelimit":  timelimit,
        "candidates": result.get("finds", [])[:5],
        "total_found": result.get("total_new", 0),
    }


def _extract_keywords(record: dict) -> list[str]:
    """从推文 label 提取关键词（支持中英文混合）"""
    import re
    label = record.get("label", "")
    if not label:
        return []
    # 分离中文片段和英文单词
    # 中文：连续汉字作为一个词（2-4字切分）
    # 英文：空格分词 + 去停用词
    stopwords = {"the", "a", "an", "and", "or", "for", "in", "of", "to", "is", "it", "on"}
    keywords = []
    # 英文单词
    en_words = re.findall(r'[a-zA-Z]{3,}', label)
    keywords.extend(w for w in en_words if w.lower() not in stopwords)
    # 中文：提取连续汉字段，长段切成2-4字的词
    cn_segments = re.findall(r'[\u4e00-\u9fff]{2,}', label)
    for seg in cn_segments:
        if len(seg) <= 4:
            keywords.append(seg)
        else:
            # 按4字切分
            for i in range(0, len(seg) - 1, 4):
                keywords.append(seg[i:i+4])
    return keywords[:4]  # 最多4个关键词


# ─── 功能5：传播模式判断 ──────────────────────────────────────────────────────

def analyze_propagation(history: list[dict], burst: dict | None = None) -> dict:
    """
    通过 RT/浏览比的变化，判断推文是怎么火的。
    返回：{
      mode: "influencer" | "algorithm" | "mixed" | "unknown",
      description: str,
      evidence: {...}
    }
    """
    if len(history) < 3:
        return {"mode": "unknown", "description": "数据不足", "evidence": {}}

    # 计算每个采样点的 RT 每千次浏览比
    rt_ratios = []
    for snap in history:
        v = snap.get("views", 0)
        rt = snap.get("retweets", 0)
        if v > 100:  # 浏览量太少时比值不稳定
            rt_ratios.append(rt / v * 1000)

    if not rt_ratios:
        return {"mode": "unknown", "description": "浏览量不足", "evidence": {}}

    avg_ratio = sum(rt_ratios) / len(rt_ratios)

    # 如果有爆点窗口，重点看爆点前后的比值变化
    burst_ratio_jump = None
    if burst:
        try:
            burst_start = datetime.fromisoformat(burst["start_ts"])
            before, after = [], []
            for snap in history:
                ts = datetime.fromisoformat(snap["ts"])
                v = snap.get("views", 0)
                rt = snap.get("retweets", 0)
                if v > 100:
                    ratio = rt / v * 1000
                    if ts < burst_start:
                        before.append(ratio)
                    else:
                        after.append(ratio)
            if before and after:
                burst_ratio_jump = sum(after) / len(after) - sum(before) / len(before)
        except Exception:
            pass

    # 判断传播模式
    if avg_ratio >= INFLUENCER_RT_RATIO:
        mode = "influencer"
        desc = f"大号转发驱动（平均 {avg_ratio:.1f}‰ RT/千次浏览，远高于均值）"
    elif avg_ratio <= ALGORITHM_RT_RATIO:
        mode = "algorithm"
        desc = f"算法推荐驱动（平均 {avg_ratio:.1f}‰ RT/千次浏览，增长平滑）"
    else:
        mode = "mixed"
        desc = f"混合传播（平均 {avg_ratio:.1f}‰ RT/千次浏览）"

    if burst_ratio_jump is not None and burst_ratio_jump > 1.0:
        mode = "influencer"
        desc += f"，爆点时 RT 比突增 +{burst_ratio_jump:.1f}‰（疑似大号在此时转发）"

    return {
        "mode": mode,
        "description": desc,
        "evidence": {
            "avg_rt_per_1k_views": round(avg_ratio, 2),
            "burst_ratio_jump":    round(burst_ratio_jump, 2) if burst_ratio_jump is not None else None,
        }
    }


# ─── 核心：采样一条推文 ───────────────────────────────────────────────────────

def sample_tweet(tweet_id: str, record: dict) -> dict:
    snap = fetch_tweet_stats(tweet_id)
    if snap is None:
        return record

    snap["ts"] = now_utc().isoformat()
    history = record.get("history", [])
    history.append(snap)
    record["history"] = history
    record["latest"] = snap

    # delta vs 上一次
    if len(history) >= 2:
        prev = history[-2]
        record["last_delta"] = {
            k: snap.get(k, 0) - prev.get(k, 0)
            for k in ("views", "likes", "retweets", "bookmarks", "replies")
        }
        record["last_delta"]["hours_elapsed"] = round(_hours_between(prev, snap), 2)

    # ETCH 检测
    record["spike"] = detect_spike(history)

    # 饱和检测
    if detect_saturation(history):
        record.setdefault("saturated", snap["ts"])
    else:
        record.pop("saturated", None)

    return record


# ─── 报告生成 ─────────────────────────────────────────────────────────────────

def generate_report(tweet_id: str, record: dict, cross_analysis: bool = False) -> str:
    label   = record.get("label", tweet_id)
    history = record.get("history", [])
    lines   = [
        "═" * 50,
        f"  推文增长报告：{label}",
        f"  ID: {tweet_id}",
        f"  生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "═" * 50,
    ]

    if not history:
        lines.append("  暂无数据")
        return "\n".join(lines)

    first, last = history[0], history[-1]

    def pct(a, b):
        return f"+{(b-a)/a*100:.1f}%" if a > 0 else "N/A"

    lines += [
        "",
        "  ── 整体增长 ──",
        f"  浏览：  {first['views']:,} → {last['views']:,}  ({pct(first['views'], last['views'])})",
        f"  点赞：  {first['likes']:,} → {last['likes']:,}  ({pct(first['likes'], last['likes'])})",
        f"  转发：  {first['retweets']:,} → {last['retweets']:,}  ({pct(first['retweets'], last['retweets'])})",
        f"  收藏：  {first['bookmarks']:,} → {last['bookmarks']:,}  ({pct(first['bookmarks'], last['bookmarks'])})",
    ]

    # 参与度比
    v = last["views"]
    if v > 0:
        lines += [
            "",
            "  ── 参与度（每千次浏览）──",
            f"  转发率：{last['retweets']/v*1000:.2f}‰",
            f"  收藏率：{last['bookmarks']/v*1000:.2f}‰",
            f"  点赞率：{last['likes']/v*1000:.2f}‰",
            f"  收藏/点赞：{last['bookmarks']/last['likes']:.2f}" if last['likes'] > 0 else "  收藏/点赞：N/A",
        ]

    # 爆点窗口
    bursts = find_burst_windows(history)
    if bursts:
        top = bursts[0]
        lines += [
            "",
            "  ── 爆点时间窗口 ──",
            f"  开始：{top['start_ts'][:16]}",
            f"  结束：{top['end_ts'][:16]}",
            f"  持续：{top['duration_h']:.1f}h",
            f"  新增浏览：+{top['views_gained']:,}",
            f"  峰值增速：{top['peak_rate']:.0%}/h",
        ]
        if len(bursts) > 1:
            lines.append(f"  （共检测到 {len(bursts)} 个爆点窗口）")

        # 传播模式
        prop = analyze_propagation(history, top)
        lines += [
            "",
            "  ── 传播模式 ──",
            f"  {prop['description']}",
        ]

        # 话题交叉分析
        if cross_analysis:
            lines += ["", "  ── 同时段话题 ──"]
            ca = cross_analyze_burst(record, top)
            if ca.get("error"):
                lines.append(f"  {ca['error']}")
            elif ca.get("candidates"):
                for c in ca["candidates"][:3]:
                    lines.append(f"  · {c.get('title','')[:50]}")
                    lines.append(f"    {c.get('url','')}")
            else:
                lines.append("  未找到同时段相关推文")
    else:
        prop = analyze_propagation(history)
        lines += [
            "",
            "  ── 传播模式 ──",
            f"  {prop['description']}",
        ]

    # 当前状态
    lines += ["", "  ── 当前状态 ──"]
    if record.get("saturated"):
        lines.append(f"  阶段：长尾（{record['saturated'][:16]} 起）")
    else:
        spike = record.get("spike", {})
        if spike.get("confirmed"):
            lines.append(f"  阶段：爆点确认 ★ — {spike.get('reason','')}")
        elif spike.get("spike_score", 0) > ETCH_SPIKE_RATE:
            lines.append(f"  阶段：候选爆点（得分 {spike['spike_score']:.2%}/h，待确认）")
        else:
            lines.append("  阶段：正常增长")

    age = tweet_age_hours(record)
    mode = f"快速采样({FAST_INTERVAL_MIN}min)" if age < NEW_TWEET_HOURS else f"常规采样({NORM_INTERVAL_MIN}min)"
    lines += [
        "",
        f"  样本数：{len(history)}",
        f"  推文年龄：{age:.1f}h",
        f"  采样模式：{mode}",
        "═" * 50,
    ]
    return "\n".join(lines)
