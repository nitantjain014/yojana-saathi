"""Step 1 of the myScheme collector.
Fetches a few scheme pages from myscheme.gov.in and saves what it finds in sample.json,
so we can see how the data is structured before collecting everything.
It never crashes: any problem is written into sample.json under "errors"."""
import json
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.myscheme.gov.in"
HEAD = {"User-Agent": "YojanaSaathi-student-project/1.0"}
out = {"errors": [], "sitemap_urls_found": 0, "scheme_urls_found": 0, "first_urls": [], "samples": []}


def get(url):
    r = requests.get(url, headers=HEAD, timeout=30)
    r.raise_for_status()
    return r.text


def sitemap_urls(url, depth=0):
    urls = []
    try:
        xml = get(url)
    except Exception as e:
        out["errors"].append(f"sitemap {url}: {e}")
        return urls
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
        if loc.endswith(".xml") and depth < 2:
            urls += sitemap_urls(loc, depth + 1)
        else:
            urls.append(loc)
    return urls


def scheme_page(url):
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    item = {
        "url": url,
        "title": soup.title.string if soup.title else None,
        "h1": [h.get_text(strip=True) for h in soup.find_all("h1")][:3],
    }
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            item["next_data"] = json.loads(nd.string)
        except Exception as e:
            item["next_data_error"] = str(e)
    else:
        item["next_data"] = None
        item["text_start"] = soup.get_text(" ", strip=True)[:3000]
    return item


try:
    urls = sitemap_urls(BASE + "/sitemap.xml")
    schemes = [u for u in urls if "/schemes/" in u]
    out["sitemap_urls_found"] = len(urls)
    out["scheme_urls_found"] = len(schemes)
    out["first_urls"] = urls[:10]
    pick = schemes[:5] or [BASE + "/schemes/apy", BASE + "/schemes/nsjbsy"]
    for u in pick:
        try:
            out["samples"].append(scheme_page(u))
        except Exception as e:
            out["errors"].append(f"page {u}: {e}")
        time.sleep(2)
except Exception as e:
    out["errors"].append(f"main: {e}")

with open("sample.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("Done. Errors:", out["errors"])
