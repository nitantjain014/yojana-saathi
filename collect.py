"""Collects schemes from myScheme into files our app can read.

LIMIT=30 -> quick test (a few requests, writes a report in collect_log.txt)
LIMIT=0  -> collect everything (takes a long time, resumes if run again)

Output:
  schemes.json        -> one short record per scheme (used for the list page)
  details/<slug>.json -> full details of one scheme (used for page 6)
  collect_log.txt     -> what happened, including how many schemes each filter returned
"""
import html
import json
import os
import time

import requests

BASE = "https://www.myscheme.gov.in"
LIST_URL = BASE + "/api/apisetu/search/schemes"
DETAIL_URL = BASE + "/api/apisetu/schemes"
HEAD = {
    "User-Agent": "YojanaSaathi-student-project/1.0 (github.com/nitantjain014/yojana-saathi)",
    "Accept": "application/json",
}
DELAY = 0.4  # seconds between requests, so we do not overload their server
LIMIT = int(os.environ.get("LIMIT") or 0)
LANGS = [x.strip() for x in (os.environ.get("LANGS") or "en,hi").split(",") if x.strip()]
GENDERS = ["Male", "Female", "Transgender"]
AGE_BANDS = [(15, 19), (20, 24), (25, 29), (30, 34), (35, 39), (40, 44), (45, 49),
             (50, 54), (55, 59), (60, 64), (65, 69), (70, 74), (75, 100)]

LOG = []


def log(msg):
    print(msg, flush=True)
    LOG.append(msg)


def get_json(url, params):
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEAD, timeout=40)
            r.raise_for_status()
            time.sleep(DELAY)
            return r.json()
        except Exception as e:  # network or server problem: wait and retry
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url} {params}: {last}")


def qjson(filters):
    return json.dumps(filters, separators=(",", ":"))


def list_page(filters, start, size, lang="en"):
    j = get_json(LIST_URL, {"lang": lang, "q": qjson(filters), "keyword": "", "sort": "",
                            "from": start, "size": size})
    hits = j["data"]["hits"]
    return hits["items"], hits["page"]["total"]


def list_all(filters, size, first_page_only=False):
    """Returns (items, total). first_page_only is used for quick tests."""
    items, total = list_page(filters, 0, size)
    if first_page_only:
        return items, total
    start = size
    while start < total:
        more, _ = list_page(filters, start, size)
        if not more:
            break
        items += more
        start += size
    return items, total


# ---- turning myScheme's rich text into plain text ----
def txt(n):
    if isinstance(n, list):
        return "".join(txt(x) for x in n)
    if not isinstance(n, dict):
        return str(n or "")
    if "text" in n and "children" not in n:
        return n["text"]
    return "".join(txt(c) for c in n.get("children", []))


def blocks(nodes):
    lines = []
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        ch = n.get("children", [])
        if ch and all(isinstance(c, dict) and c.get("type") == "list_item" for c in ch):
            lines += ["- " + txt(c).strip() for c in ch]
        else:
            s = txt(n).strip()
            if s:
                lines.append(s)
    return "\n".join(l for l in lines if l.strip("- "))


def compact(en):
    b = en.get("basicDetails") or {}
    c = en.get("schemeContent") or {}
    e = en.get("eligibilityCriteria") or {}
    apply_ = []
    for a in en.get("applicationProcess") or []:
        apply_.append({"mode": a.get("mode"), "url": a.get("url"), "steps": blocks(a.get("process"))})
    docs = ""
    try:
        d = en.get("documents_required")
        if isinstance(d, list):
            docs = blocks(d)
    except Exception:
        pass
    return {
        "name": b.get("schemeName"),
        "short": b.get("schemeShortTitle"),
        "level": (b.get("level") or {}).get("label"),
        "ministry": (b.get("nodalMinistryName") or {}).get("label"),
        "categories": [x.get("label") for x in (b.get("schemeCategory") or [])],
        "tags": b.get("tags") or [],
        "brief": html.unescape(c.get("briefDescription") or "").strip(),
        "details": html.unescape(c.get("detailedDescription_md") or blocks(c.get("detailedDescription")) or "").replace("<br>", "").strip(),
        "benefits": blocks(c.get("benefits")),
        "eligibility": html.unescape(e.get("eligibilityDescription_md") or blocks(e.get("eligibilityDescription")) or "").strip(),
        "exclusions": blocks(c.get("exclusions")),
        "apply": apply_,
        "documents": docs,
        "logo": c.get("schemeImageUrl") or "",
    }


def fetch_detail(slug, lang):
    j = get_json(DETAIL_URL, {"slug": slug, "lang": lang})
    data = j.get("data") or {}
    block = data.get(lang)
    return compact(block) if block else None


def main():
    os.makedirs("details", exist_ok=True)
    quick = LIMIT > 0
    log(f"Mode: {'QUICK TEST' if quick else 'FULL'}  limit={LIMIT}  langs={LANGS}")

    # 1. how many schemes can one request return?
    size = 10
    try:
        items, total = list_page([], 0, 100)
        if len(items) > 10:
            size = 100
        log(f"Asked for 100 per page, got {len(items)}. Total schemes: {total}. Using size={size}.")
    except Exception as e:
        log(f"List test failed: {e}")
        return

    # 2. the full list (no filter)
    items, total = list_all([], size, first_page_only=quick)
    index = {}
    for it in items:
        f = it.get("fields", {})
        slug = f.get("slug")
        if not slug:
            continue
        index[slug] = {
            "s": slug,
            "n": f.get("schemeName"),
            "sh": f.get("schemeShortTitle"),
            "l": f.get("level"),
            "st": f.get("beneficiaryState") or [],
            "c": f.get("schemeCategory") or [],
            "t": f.get("tags") or [],
            "b": (f.get("briefDescription") or "")[:200],
            "cl": f.get("schemeCloseDate"),
            "g": [],
            "a": [],
        }
    log(f"No filter: total={total}, collected {len(index)}")

    # 3. which schemes does myScheme return for each gender and age band?
    probes = [("gender", g, [{"identifier": "gender", "value": g}]) for g in GENDERS]
    probes += [("age", f"{lo}-{hi}", [{"identifier": "age-general", "min": lo, "max": hi}]) for lo, hi in AGE_BANDS]
    probes.append(("age", "35-35", [{"identifier": "age-general", "min": 35, "max": 35}]))
    for kind, label, filt in probes:
        try:
            got, tot = list_all(filt, size, first_page_only=quick)
        except Exception as e:
            log(f"Filter {kind}={label}: FAILED ({e})")
            continue
        log(f"Filter {kind}={label}: total={tot}")
        if quick or label == "35-35":
            continue
        key = "g" if kind == "gender" else "a"
        for it in got:
            slug = (it.get("fields") or {}).get("slug")
            if slug in index:
                index[slug][key].append(label)

    # 4. details of each scheme, in each language
    slugs = list(index.keys())
    if quick:
        slugs = slugs[:LIMIT]
    log(f"Fetching details for {len(slugs)} schemes in {LANGS}")
    for i, slug in enumerate(slugs, 1):
        path = f"details/{slug}.json"
        rec = {}
        if os.path.exists(path):
            try:
                rec = json.load(open(path, encoding="utf-8"))
            except Exception:
                rec = {}
        for lang in LANGS:
            if lang in rec:
                continue
            try:
                d = fetch_detail(slug, lang)
                if d:
                    rec[lang] = d
            except Exception as e:
                log(f"Detail {slug} {lang}: FAILED ({e})")
        if rec:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
            hi = rec.get("hi")
            if hi:
                index[slug]["nh"] = hi.get("name")
                index[slug]["bh"] = (hi.get("brief") or "")[:200]
        if i % 100 == 0:
            log(f"  ...{i}/{len(slugs)} done")
            save_index(index, quick)

    save_index(index, quick)
    log("Finished.")


def save_index(index, quick):
    out = {
        "generated": time.strftime("%Y-%m-%d"),
        "source": "myScheme.gov.in",
        "test_run": quick,
        "age_bands": AGE_BANDS,
        "count": len(index),
        "schemes": list(index.values()),
    }
    with open("schemes.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"STOPPED WITH ERROR: {e}")
    finally:
        with open("collect_log.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(LOG))
