# Check the context behind a fetched tweet

Use xtf to capture a tweet, then use an external MCP client to research a specific
claim or linked source. [Parallel Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp)
provides free web search and page fetching without an account or API key. Anonymous
search uses Fast mode and is intended for exploration and light use.

This is an optional downstream workflow. Parallel runs in your MCP client, not as
an xtf backend; xtf's tweet fetching, Nitter search and configuration stay the same.
Web search results are not a complete X timeline or reply thread.

## 1. Capture the tweet

From your x-tweet-fetcher clone, replace the example URL with the tweet whose
claim or link you want to investigate:

```bash
python3 scripts/fetch_tweet.py \
  --url 'https://x.com/jack/status/20' --pretty > tweet.json
```

Continue only if the command exits successfully. On failure, inspect `error` and
`error_code` in `tweet.json` and resolve the fetch error first. A successful
single-tweet response contains a `tweet` object with `text`, `screen_name` and
`created_at`; quoted content, when present, is in `tweet.quote`. Keep the original
tweet URL alongside the JSON so your report can cite it.

## 2. Connect an MCP client

Use a client that supports remote MCP over Streamable HTTP. For example, in
[VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers),
merge this entry into a workspace-root `.mcp.json` (keep any existing servers):

```json
{
  "mcpServers": {
    "parallel-search": {
      "type": "http",
      "url": "https://search.parallel.ai/mcp"
    }
  }
}
```

Run **MCP: List Servers** from the Command Palette to manage the server, then use
**Configure Tools** in chat to confirm `web_search` and `web_fetch` are available.
No authorization header
or OAuth sign-in is needed for this endpoint. Other clients have different config
formats; use the [client-specific setup instructions](https://docs.parallel.ai/integrations/mcp/search-mcp#installation).

## 3. Research one claim

Attach `tweet.json` to your MCP client's chat and supply the original tweet URL.
Select the Parallel tools and ask:

```text
Read the attached xtf output. Quote one checkable claim from the tweet and
identify who said it, keeping the author's words separate from quoted content.
Use Parallel web_search to find primary sources about that specific claim.
Use web_fetch to read the most relevant sources and any source linked in the
tweet. If a URL is shortened, resolve its destination before citing it.
Compare publication dates with the tweet's created_at date: distinguish what
was known then from later updates. If a date is missing, say so.

Return: claim | source URL | publication date | supporting or conflicting
passage | assessment (supported, contradicted, or unresolved).
Include the original tweet URL. Explain missing evidence and inaccessible
pages; do not treat an excerpt, a repeated claim, or an empty search as proof.
```

Review the cited pages before relying on the assessment. Deleted or private
tweets may fail to fetch, and linked pages may be inaccessible to `web_fetch`.
When a tool reports a limit or failure, leave the claim unresolved rather than
presenting it as verified.
