#!/usr/bin/env python3
"""
Sogou WeChat Search - Search WeChat articles via Sogou.
Part of x-tweet-fetcher.

Usage:
  python3 sogou_wechat.py --keyword "AI" --limit 5
  python3 sogou_wechat.py --keyword "人工智能" --json

  # Resolve to real mp.weixin.qq.com URLs (via Google/DuckDuckGo)
  python3 sogou_wechat.py --keyword "AI Agent" --limit 3 --resolve --json

  # Use SSH proxy to avoid IP bans (set env vars)
  export SOGOU_SSH_HOST=user@host
  python3 sogou_wechat.py --keyword "AI Agent" --via-ssh

Workflow: Sogou search → get titles → Google/DDG find real WeChat URL → fetch_china.py reads full text
"""

from urllib.parse import quote
import re
import json
import argparse
import shlex
import sys
import os
import html as html_lib
import subprocess


def sogou_wechat_search_via_router(keyword, max_results=10):
    """Search Sogou WeChat via home router (cmd-queue/cmd-result pattern).
    
    Router polls VPS every minute, executes queued commands, pushes results back.
    Uses home IP — never gets banned by Sogou.
    """
    import time
    queue_file = os.environ.get("ROUTER_CMD_QUEUE", "/root/router-agent/cmd-queue")
    result_file = os.environ.get("ROUTER_CMD_RESULT", "/root/router-agent/cmd-result")
    output_file = os.environ.get("ROUTER_CMD_OUTPUT", "/root/router-agent/cmd-output")

    for path_var in (queue_file, result_file, output_file):
        if not os.path.isabs(path_var) or '..' in path_var:
            print(f"Invalid router path: {path_var}", file=sys.stderr)
            return sogou_wechat_search(keyword, max_results)
    
    # Mark current result file position
    try:
        with open(result_file) as f:
            before = f.read()
        before_len = len(before)
    except FileNotFoundError:
        before_len = 0
    
    # Queue the curl command — router will fetch raw HTML
    encoded_kw = quote(keyword)
    search_url = f'https://weixin.sogou.com/weixin?type=2&query={encoded_kw}'
    cmd = f'curl -s {shlex.quote(search_url)} -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"'
    
    with open(queue_file, 'w') as f:
        f.write(cmd)
    
    print(f"Command queued, waiting for router (up to 90s)...", file=sys.stderr)
    
    # Wait for result (router polls every ~60s)
    for _ in range(18):  # 18 * 5s = 90s max
        time.sleep(5)
        try:
            with open(result_file) as f:
                after = f.read()
            if len(after) > before_len:
                # New result arrived — read the output file
                try:
                    with open(output_file) as f:
                        html_text = f.read()
                    if 'txt-box' in html_text:
                        return _parse_sogou_html(html_text, max_results)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
    
    print("Router timeout, falling back to direct", file=sys.stderr)
    return sogou_wechat_search(keyword, max_results)


def _parse_sogou_html(text, max_results=10):
    """Parse Sogou search result HTML into structured results."""
    results = []
    blocks = re.findall(r'<div class="txt-box">(.*?)</div>\s*</div>', text, re.DOTALL)
    for block in blocks[:max_results]:
        title_match = re.search(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_match:
            continue
        article_url = title_match.group(1).replace('&amp;', '&')
        raw_title = title_match.group(2)
        title = re.sub(r'<[^>]+>', '', raw_title).strip()
        title = html_lib.unescape(title)
        author_match = re.search(r'<a[^>]*class="account"[^>]*>(.*?)</a>', block, re.DOTALL)
        author = re.sub(r'<[^>]+>', '', author_match.group(1)).strip() if author_match else ''
        snippet_match = re.search(r'<p class="txt-info">(.*?)</p>', block, re.DOTALL)
        snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip() if snippet_match else ''
        snippet = html_lib.unescape(snippet)
        date_match = re.search(r"document\.write\(timeConvert\('(\d+)'\)\)", block)
        if date_match:
            from datetime import datetime
            ts = int(date_match.group(1))
            date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
        else:
            date = ''
        if article_url.startswith('/link'):
            article_url = 'https://weixin.sogou.com' + article_url
        results.append({'title': title, 'url': article_url, 'author': author, 'snippet': snippet, 'date': date})
    return results


def sogou_wechat_search_via_ssh(keyword, max_results=10, ssh_host=None):
    """Search Sogou WeChat via SSH proxy to avoid IP bans.

    Requires: SOGOU_SSH_HOST env var or ssh_host param (e.g. user@host).
    """
    host = ssh_host or os.environ.get("SOGOU_SSH_HOST")
    if not host:
        print("SOGOU_SSH_HOST not set, falling back to direct", file=sys.stderr)
        return sogou_wechat_search(keyword, max_results)

    if not re.match(r'^[\w.-]+@[\w.-]+$', host):
        print(f"Invalid SSH host format: {host}", file=sys.stderr)
        return sogou_wechat_search(keyword, max_results)

    script = f'''
import requests, re, json, html as html_lib
from urllib.parse import quote
headers = {{"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}}
url = f"https://weixin.sogou.com/weixin?type=2&query={{quote({repr(keyword)})}}"
r = requests.get(url, headers=headers, timeout=10)
results = []
blocks = re.findall(r'<div class="txt-box">(.*?)</div>\\s*</div>', r.text, re.DOTALL)
for block in blocks[:{max_results}]:
    title_m = re.search(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
    if not title_m: continue
    article_url = title_m.group(1).replace("&amp;", "&")
    title = re.sub(r'<[^>]+>', '', title_m.group(2)).strip()
    title = html_lib.unescape(title)
    author_m = re.search(r'<a[^>]*class="account"[^>]*>(.*?)</a>', block, re.DOTALL)
    author = re.sub(r'<[^>]+>', '', author_m.group(1)).strip() if author_m else ''
    snippet_m = re.search(r'<p class="txt-info">(.*?)</p>', block, re.DOTALL)
    snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ''
    snippet = html_lib.unescape(snippet)
    from datetime import datetime
    date_m = re.search(r"document\\.write\\(timeConvert\\('(\\d+)'\\)\\)", block)
    date = datetime.fromtimestamp(int(date_m.group(1))).strftime('%Y-%m-%d') if date_m else ''
    if article_url.startswith('/link'): article_url = 'https://weixin.sogou.com' + article_url
    results.append({{"title": title, "url": article_url, "author": author, "snippet": snippet, "date": date}})
print(json.dumps(results, ensure_ascii=False))
'''
    try:
        # Write script to temp file and scp to remote
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            local_path = f.name

        remote_path = "/tmp/_sogou_search.py"
        try:
            subprocess.run(["scp", "-o", "ConnectTimeout=5", "-q", local_path, f"{host}:{remote_path}"],
                           capture_output=True, timeout=10)
        finally:
            os.unlink(local_path)

        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", host, "python3", remote_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
        else:
            print(f"SSH search failed: {result.stderr[:100]}", file=sys.stderr)
            return sogou_wechat_search(keyword, max_results)
    except Exception as e:
        print(f"SSH error: {e}, falling back to direct", file=sys.stderr)
        return sogou_wechat_search(keyword, max_results)


def sogou_wechat_search(keyword, max_results=10):
    """搜索搜狗微信公众号文章"""
    import requests

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    url = f'https://weixin.sogou.com/weixin?type=2&query={quote(keyword)}'
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        text = response.text
        
        results = []
        
        # 找到所有 txt-box 块
        blocks = re.findall(r'<div class="txt-box">(.*?)</div>\s*</div>', text, re.DOTALL)
        
        for block in blocks[:max_results]:
            # 标题和链接
            title_match = re.search(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not title_match:
                continue
            
            article_url = title_match.group(1).replace('&amp;', '&')
            # 清理标题中的 HTML 标签
            raw_title = title_match.group(2)
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            title = html_lib.unescape(title)
            
            # 作者/公众号
            author_match = re.search(r'<a[^>]*class="account"[^>]*>(.*?)</a>', block, re.DOTALL)
            author = re.sub(r'<[^>]+>', '', author_match.group(1)).strip() if author_match else ''
            
            # 摘要
            snippet_match = re.search(r'<p class="txt-info">(.*?)</p>', block, re.DOTALL)
            snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip() if snippet_match else ''
            snippet = html_lib.unescape(snippet)
            
            # 日期 (timestamp)
            date_match = re.search(r"document\.write\(timeConvert\('(\d+)'\)\)", block)
            if date_match:
                from datetime import datetime
                ts = int(date_match.group(1))
                date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            else:
                date = ''
            
            # 完整链接
            if article_url.startswith('/link'):
                article_url = 'https://weixin.sogou.com' + article_url
            
            results.append({
                'title': title,
                'url': article_url,
                'author': author,
                'snippet': snippet,
                'date': date
            })
            
        return results
        
    except Exception as e:
        print(f"搜索失败: {e}", file=sys.stderr)
        return []


def resolve_sogou_link(sogou_url, port=9377):
    """Resolve Sogou redirect link to real mp.weixin.qq.com URL via Camofox."""
    try:
        from camofox_client import camofox_open_tab, camofox_snapshot, camofox_close_tab
        import time
        tab_id = camofox_open_tab(sogou_url, f"resolve-{int(time.time())}", port=port)
        if not tab_id:
            return sogou_url
        time.sleep(5)
        snapshot = camofox_snapshot(tab_id, port=port)
        camofox_close_tab(tab_id, port=port)
        if snapshot:
            # Look for mp.weixin.qq.com in the final page URL or content
            import re
            mp_match = re.search(r'(https?://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+)', snapshot)
            if mp_match:
                return mp_match.group(1)
            # Check for canonical URL
            canon = re.search(r'canonical.*?(https?://mp\.weixin\.qq\.com[^\s"<>]+)', snapshot)
            if canon:
                return canon.group(1)
        return sogou_url
    except Exception:
        return sogou_url


def resolve_via_google(title, port=9377):
    """Resolve article title to real mp.weixin.qq.com URL via Google search."""
    try:
        from camofox_client import camofox_search
        query = f'site:mp.weixin.qq.com "{title}"'
        results = camofox_search(query, num=3, port=port)
        for r in results:
            url = r.get('url', '')
            if 'mp.weixin.qq.com' in url:
                return url
    except Exception:
        pass
    # Fallback: try DuckDuckGo
    try:
        from duckduckgo_search import DDGS
        import warnings
        warnings.filterwarnings("ignore")
        ddgs = DDGS()
        query = f'site:mp.weixin.qq.com {title}'
        results = ddgs.text(query, max_results=3)
        for r in results:
            url = r.get('href', '')
            if 'mp.weixin.qq.com' in url:
                return url
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Search WeChat articles via Sogou")
    parser.add_argument("--keyword", "-k", required=True, help="Search keyword")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Max results")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON")
    parser.add_argument("--resolve", "-r", action="store_true", help="Resolve Sogou links to real WeChat URLs (requires Camofox)")
    parser.add_argument("--via-ssh", action="store_true", help="Route search via SSH proxy (set SOGOU_SSH_HOST env var)")
    parser.add_argument("--via-router", action="store_true", help="Route search via home router (cmd-queue pattern, 24/7)")
    args = parser.parse_args()

    if args.via_router:
        results = sogou_wechat_search_via_router(args.keyword, args.limit)
    elif args.via_ssh:
        results = sogou_wechat_search_via_ssh(args.keyword, args.limit)
    else:
        results = sogou_wechat_search(args.keyword, args.limit)

    if args.resolve and results:
        print("Resolving to real WeChat URLs (Sogou → Google/DuckDuckGo → mp.weixin.qq.com)...", file=sys.stderr)
        for r in results:
            real_url = resolve_via_google(r['title'])
            if real_url:
                r['url'] = real_url
                r['resolved'] = True
            else:
                # Fallback: try Camofox direct resolve
                resolved = resolve_sogou_link(r['url'])
                if resolved != r['url']:
                    r['url'] = resolved
                    r['resolved'] = True

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("未找到结果")
        for i, article in enumerate(results, 1):
            print(f"{i}. {article['title']}")
            if article['author']:
                print(f"   公众号: {article['author']}")
            if article['date']:
                print(f"   日期: {article['date']}")
            if article['snippet']:
                print(f"   摘要: {article['snippet'][:80]}...")
            print(f"   链接: {article['url'][:80]}...")
            print()

    sys.exit(0 if results else 1)


if __name__ == "__main__":
    main()
