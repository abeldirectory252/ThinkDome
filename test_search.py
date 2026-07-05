import asyncio
import httpx
import re
import urllib.parse

async def search_ddg_html(query: str, max_results: int = 5):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(url)
        print("Status code:", resp.status_code)
        html = resp.text
        print("HTML length:", len(html))
        
        # Let's extract result blocks
        # DDG HTML results usually look like:
        # <div class="result results_links results_links_deep web-result ">
        #   <div class="links_main links_deep result__body">
        #     <h2 class="result__title">
        #       <a class="result__a" rel="nofollow" href="https://example.com">Title</a>
        #     </h2>
        #     <a class="result__url" href="https://example.com">url</a>
        #     <span class="result__snippet">snippet text</span>
        #   </div>
        # </div>
        results = []
        blocks = re.findall(r'<div class="[^"]*result__body[^"]*">.*?</div>\s*</div>', html, re.DOTALL)
        print("Found blocks:", len(blocks))
        
        # If result__body regex is too strict, let's try a broader match
        if not blocks:
            # Let's try matching result links results_links_deep
            blocks = re.findall(r'<div class="[^"]*web-result[^"]*">.*?</div>\s*</div>\s*</div>', html, re.DOTALL)
            print("Found blocks (web-result):", len(blocks))

        for block in blocks[:max_results]:
            # Link/URL: <a class="result__a" href="URL">
            match_link = re.search(r'href="([^"]+)"', block)
            # Title: inside <a class="result__a">Title</a>
            match_title = re.search(r'<a class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
            # Snippet: <a class="result__snippet">Snippet</a> or <span class="result__snippet">Snippet</span>
            match_snippet = re.search(r'<a class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not match_snippet:
                match_snippet = re.search(r'<span class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL)
                
            def clean_html(text):
                return re.sub(r'<[^>]+>', '', text).strip() if text else ""
            
            if match_link:
                link = match_link.group(1)
                # Unpack DDG redirect
                if "/l/?uddg=" in link:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
                    link = parsed.get("uddg", [link])[0]
                
                title = clean_html(match_title.group(1)) if match_title else "No Title"
                snippet = clean_html(match_snippet.group(1)) if match_snippet else ""
                
                results.append({
                    "title": title,
                    "url": link,
                    "snippet": snippet
                })
        
        return results

async def main():
    res = await search_ddg_html("latest python version")
    print("Results:")
    for r in res:
        print(r)

if __name__ == "__main__":
    asyncio.run(main())
