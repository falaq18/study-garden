"""Fetch the newest links for the study garden and write links.json (+ an audit log).

Runs every morning from .github/workflows/daily-links.yml. Python standard library only,
no AI and no paid APIs.

HOW A STORY IS RANKED (v2)
  1. Read top-story feeds from a panel of outlets spread across the political spectrum.
     Each outlet carries a coarse lean bucket, L / C / R, taken from public raters
     (Media Bias/Fact Check, Biasly). Raters disagree, so these are rough buckets, not truth.
     Outlets we have not rated count as coverage but not toward the spectrum.
  2. Cluster headlines about the same story. Rare words (Hormuz, Sebi) count for more than
     common ones (government, minister), so clustering does not glue unrelated stories.
  3. Score each story:
       - independent outlet families covering it (The Hindu + Hindu BusinessLine = one family)
       - CROSS-SPECTRUM agreement: stories chosen by outlets on different sides rank first
       - how many different news sites worldwide carried it in the last day (GDELT, free)
       - editor placement, freshness, and a small boost for policy / economy / courts / diplomacy
       - penalty for live blogs, galleries, celebrity, sports results, deals and promos
  4. Keep the top 3 per section.
  5. AUDIT: compare the picks with Wikipedia's "Current events" page (human-edited, with a
     neutral-point-of-view policy). Written to links.json and appended to audit-log.jsonl so
     we can see over time whether the ranking agrees with an independent editorial standard.
If a feed fails, the others carry on; if a whole section fails, yesterday's picks stay.
"""
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "links.json"
AUDIT_LOG = ROOT / "audit-log.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (study-garden link fetcher; +https://github.com)"}
NOW = datetime.now(timezone.utc)


def gnews(query):
    """Google News RSS search: a way to read outlets that no longer publish an RSS feed."""
    q = urllib.parse.quote(query + " when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"


NEWS = {
    "india": [
        ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
        ("Indian Express", "https://indianexpress.com/section/india/feed/"),
        ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"),
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("Times of India", "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
        ("India Today", "https://www.indiatoday.in/rss/1206514"),
        ("ThePrint", "https://theprint.in/feed/"),
        ("Business Standard", "https://www.business-standard.com/rss/india-news-216.rss"),
        ("BBC India", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml"),
        ("Reuters India", gnews("site:reuters.com india")),
        ("Mint Politics", "https://www.livemint.com/rss/politics"),
    ],
    "world": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("DW", "https://rss.dw.com/rdf/rss-en-world"),
        ("Reuters World", gnews("site:reuters.com world")),
        ("AP", gnews("site:apnews.com world")),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml"),
        ("The Telegraph", "https://www.telegraph.co.uk/news/world/rss.xml"),
        ("WSJ", gnews("site:wsj.com world")),
        ("The Hindu World", "https://www.thehindu.com/news/international/feeder/default.rss"),
    ],
    "business": [
        ("Mint", "https://www.livemint.com/rss/markets"),
        ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
        ("Business Standard", "https://www.business-standard.com/rss/home_page_top_stories.rss"),
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("The Guardian Business", "https://www.theguardian.com/business/rss"),
        ("The Hindu Business", "https://www.thehindu.com/business/feeder/default.rss"),
        ("Reuters Business", gnews("site:reuters.com business")),
        ("WSJ Business", gnews("site:wsj.com business")),
    ],
}
EXPLAINER = ("Indian Express Explained", "https://indianexpress.com/section/explained/feed/")

# Same company = one family (so it cannot vote twice).
FAMILY = {
    "BBC India": "BBC", "BBC World": "BBC", "BBC Business": "BBC",
    "The Hindu World": "The Hindu", "The Hindu Business": "The Hindu",
    "The Guardian Business": "The Guardian",
    "Reuters India": "Reuters", "Reuters World": "Reuters", "Reuters Business": "Reuters",
    "WSJ Business": "WSJ", "Mint Politics": "Mint",
}
# Coarse lean buckets from Media Bias/Fact Check and Biasly (see docstring). None = not rated.
LEAN = {
    "The Hindu": "L", "Indian Express": "L", "Hindustan Times": "L", "NDTV": "L",
    "Al Jazeera": "L", "The Guardian": "L", "NPR": "L",
    "Times of India": "C", "BBC": "C", "DW": "C", "Reuters": "C", "AP": "C",
    "India Today": "R", "ThePrint": "R", "Business Standard": "R", "The Telegraph": "R", "WSJ": "R",
}


def family(source):
    return FAMILY.get(source, source)


def lean(source):
    return LEAN.get(family(source))


# Course feeds: plain RSS URLs, or "yt:@handle" for a YouTube channel.
COURSES = {
    "FIN": [("CA Rachana Ranade", "yt:@CARachanaRanade"), ("Mint Money", "https://www.livemint.com/rss/money")],
    "PRD": [("Lenny's Newsletter", "https://www.lennysnewsletter.com/feed"), ("Exponent", "yt:@tryexponent")],
    "AI": [("One Useful Thing", "https://www.oneusefulthing.org/feed"), ("3Blue1Brown", "yt:@3blue1brown"),
           ("Andrej Karpathy", "yt:@AndrejKarpathy")],
    "FINAL": [("Vinh Giang", "yt:@vinhgiang"), ("One Useful Thing", "https://www.oneusefulthing.org/feed")],
}

STOP = set("""a an the and or but of to in on for with at by from as is are was were be been being it its this that these those
into over after before about against between under amid than then so not no yes new news says said say will would can could
may might has have had do does did up down out off more most less least very just also how why what who whom which when where
via vs his her their our your my he she they we you i us them him one two three four five six seven eight nine ten
first last year years day days week today tomorrow yesterday report reports update updates latest live reuters ap pti ani""".split())
BOOST = set("""rbi budget gdp inflation rate rates repo tariff tariffs trade deal deals election elections poll polls vote
parliament lok sabha rajya bill law court supreme verdict judge ceasefire war attack strike sanctions summit treaty talks minister
president pm government policy reform tax gst fed ecb imf economy economic market markets sensex nifty rupee dollar oil crude
climate flood floods earthquake cyclone protest protests ban security military nuclear china pakistan russia ukraine israel gaza
iran us eu un sebi""".split())
DROP = re.compile(r"\b(live|liveblog|live updates|photos?|in pics|gallery|horoscope|quiz|watch:|video:|recipe|celebrit|bollywood|ipl|"
                  r"cricket score|match report|highlights|wordle|crossword|deal of the day|sale|lottery|opinion|podcast|newsletter)\b", re.I)

LOG = []  # human-readable notes on what worked and what didn't


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def youtube_feed(handle):
    html = get(f"https://www.youtube.com/{handle}").decode("utf-8", "ignore")
    m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', html) or re.search(r'channel/(UC[\w-]{22})', html)
    if not m:
        raise ValueError(f"no channel id for {handle}")
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"


def when(text):
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
    except Exception:
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse(source, url, limit):
    if url.startswith("yt:"):
        url = youtube_feed(url[3:])
    root = ET.fromstring(get(url))
    items = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = link = ""
        dt = None
        for ch in node:
            t = ch.tag.split("}")[-1]
            if t == "title":
                title = re.sub(r"\s+", " ", (ch.text or "")).strip()
            elif t == "link":
                link = ch.get("href") or (ch.text or "").strip() or link
            elif t in ("pubDate", "published", "updated", "date") and dt is None:
                dt = when((ch.text or "").strip())
        title = re.sub(r"\s+-\s+(Reuters|AP News|The Associated Press|WSJ|The Wall Street Journal)$", "", title)
        if title and link:
            items.append({"title": title, "url": link, "source": source, "dt": dt, "rank": len(items)})
        if len(items) >= limit:
            break
    return items


def words(title):
    toks = re.findall(r"[a-z0-9]+", title.lower())
    out = set()
    for t in toks:
        if t in STOP or len(t) < 3:
            continue
        out.add(t[:-1] if t.endswith("s") and len(t) > 4 else t)
    return out


def make_idf(token_sets):
    df = Counter()
    for s in token_sets:
        df.update(s)
    n = max(1, len(token_sets))
    return {w: math.log((n + 1) / (c + 0.5)) + 0.3 for w, c in df.items()}


def similarity(a, b, idf):
    """IDF-weighted overlap. Three or more shared content words is a strong same-story sign, so it
    gets a small bonus that lets it clear the threshold even when one headline is much longer."""
    shared = a & b
    if len(shared) < 2:
        return 0.0
    got = sum(idf.get(w, 1.0) for w in shared)
    base = min(sum(idf.get(w, 1.0) for w in a), sum(idf.get(w, 1.0) for w in b))
    s = got / base if base else 0.0
    return s + (0.1 if len(shared) >= 3 else 0.0)


SAME = 0.4


def cluster(items, idf):
    clusters = []
    for it in items:
        for c in clusters:
            if any(similarity(it["w"], o["w"], idf) >= SAME for o in c):
                c.append(it)
                break
        else:
            clusters.append([it])
    return clusters


# ---------- GDELT: how many different sites worldwide ran this story in the last day ----------
GDELT_OK = {"on": True}


def gdelt_domains(best_title, idf):
    """Distinct news domains carrying a story in the last 24h. Free, no key. None if unavailable."""
    if not GDELT_OK["on"]:
        return None
    toks = [w for w in re.findall(r"[A-Za-z0-9]+", best_title)
            if w.lower() not in STOP and len(w) >= 4]
    toks.sort(key=lambda w: -idf.get(w.lower(), idf.get(w.lower().rstrip("s"), 1.0)))
    q = " ".join(dict.fromkeys(w.lower() for w in toks[:3]))
    if not q:
        return None
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=" + urllib.parse.quote(f"{q} sourcelang:english") +
           "&mode=artlist&maxrecords=250&format=json&timespan=1d&sort=hybridrel")
    try:
        time.sleep(5.2)  # GDELT asks for one request every 5 seconds
        data = json.loads(get(url, timeout=30).decode("utf-8", "ignore") or "{}")
        return len({a.get("domain") for a in data.get("articles", []) if a.get("domain")})
    except Exception as e:
        LOG.append(f"gdelt off: {type(e).__name__} {e}")
        GDELT_OK["on"] = False
        return None


def score_cluster(c, idf, domains=None):
    fams = {family(i["source"]) for i in c}
    buckets = {lean(f) for f in fams if lean(f)}
    best = min(c, key=lambda i: (i["rank"], -(i["dt"] or NOW).timestamp()))
    s = 3.0 * min(len(fams) - 1, 4)                         # independent outlets
    s += 3.0 * max(0, len(buckets) - 1)                      # cross-spectrum agreement
    s += max(0, 3 - min(i["rank"] for i in c)) * 0.5        # editor placement
    newest = max((i["dt"] for i in c if i["dt"]), default=None)
    if newest:
        age = (NOW - newest).total_seconds() / 3600
        s += 1.0 if age < 12 else 0 if age < 36 else -3.0
    allw = set().union(*(i["w"] for i in c))
    s += 0.5 * min(4, len(allw & BOOST))                    # consequence topics
    if DROP.search(best["title"]):
        s -= 6
    if domains is not None:
        s += min(4.0, 1.5 * math.log2(1 + domains / 10))     # worldwide pickup
    return s, best, fams, buckets


def rank_section(items, n=3):
    for it in items:
        it["w"] = words(it["title"])
    idf = make_idf([it["w"] for it in items])
    clusters = cluster(items, idf)
    pre = []
    for c in clusters:
        s, best, fams, buckets = score_cluster(c, idf)
        pre.append((s, c))
    pre.sort(key=lambda x: -x[0])
    scored = []
    for k, (s0, c) in enumerate(pre):
        dom = gdelt_domains(min(c, key=lambda i: i["rank"])["title"], idf) if k < 6 else None
        s, best, fams, buckets = score_cluster(c, idf, dom)
        scored.append({"score": s, "best": best, "fams": fams, "buckets": buckets, "domains": dom, "n": len(c)})
    # tier 1: picked by outlets on at least two different sides. Within a tier, by score.
    scored.sort(key=lambda x: (len(x["buckets"]) >= 2, x["score"]), reverse=True)
    picks = []
    for x in scored[:n]:
        b = x["best"]
        picks.append({
            "title": b["title"], "url": b["url"], "source": b["source"],
            "date": b["dt"].strftime("%-d %b") if b["dt"] else "",
            "outlets": len(x["fams"]), "also": sorted(f for f in x["fams"] if f != family(b["source"]))[:3],
            "lean": "".join(sorted(x["buckets"], key=lambda z: "LCR".index(z))),
            "sites": x["domains"],
        })
    return picks


def collect(sources, per_source, ok=None, bad=None):
    out = []
    for name, url in sources:
        try:
            got = parse(name, url, per_source)
            out += got
            if ok is not None:
                ok.append(f"{name}:{len(got)}")
        except Exception as e:  # keep going if one feed is down
            print(f"skip {name}: {e}")
            if bad is not None:
                bad.append(f"{name}: {type(e).__name__}")
    return out


def plain(items, total):
    return [{"title": i["title"], "url": i["url"], "source": i["source"],
             "date": i["dt"].strftime("%-d %b") if i["dt"] else ""} for i in items][:total]


# ---------- audit against Wikipedia "Current events" ----------
def wiki_events(day):
    title = f"Portal:Current_events/{day.year}_{day.strftime('%B')}_{day.day}"
    url = "https://en.wikipedia.org/w/index.php?title=" + urllib.parse.quote(title) + "&action=raw"
    raw = get(url, timeout=30).decode("utf-8", "ignore")
    lines = []
    for ln in raw.splitlines():
        if not ln.lstrip().startswith("*"):
            continue
        t = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", ln, flags=re.S)
        t = re.sub(r"\{\{[^{}]*\}\}", "", t)
        t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)
        t = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", t)
        t = re.sub(r"[*'#:]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) > 30:
            lines.append(t)
    return lines


def audit(sections):
    res = {"wiki_items": 0, "matched": 0, "total": 0, "by_section": {}, "note": ""}
    try:
        events = []
        for back in (0, 1):
            try:
                events += wiki_events((NOW - timedelta(days=back)).date())
            except Exception as e:
                LOG.append(f"wiki {back}d: {type(e).__name__}")
        res["wiki_items"] = len(events)
        if not events:
            res["note"] = "wikipedia unavailable"
            return res
        ev_w = [words(e) for e in events]
        for key, picks in sections.items():
            hit = 0
            for p in picks:
                pw = words(p["title"])
                idf = make_idf(ev_w + [pw])
                ok = any(similarity(pw, w, idf) >= 0.4 for w in ev_w)
                p["wiki"] = ok
                hit += ok
            res["by_section"][key] = f"{hit}/{len(picks)}"
            res["matched"] += hit
            res["total"] += len(picks)
    except Exception as e:
        res["note"] = f"audit failed: {type(e).__name__}"
    return res


def main():
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
        except Exception:
            old = {}
    data = {"updated": NOW.isoformat(timespec="minutes"), "method": "spectrum-v2", "news": {}, "explainer": [], "courses": {}}
    ok, bad = [], []
    for k, sources in NEWS.items():
        items = collect(sources, 15, ok, bad)
        data["news"][k] = rank_section(items) if items else old.get("news", {}).get(k, [])
        print(k, len(items), "headlines ->", [(p["outlets"], p.get("lean")) for p in data["news"][k]])
    ex = collect([EXPLAINER], 2, ok, bad)
    data["explainer"] = plain(ex, 1) or old.get("explainer", [])
    for k, sources in COURSES.items():
        items = collect(sources, 2, ok, bad)
        data["courses"][k] = plain(items, 4) or old.get("courses", {}).get(k, [])
    data["audit"] = audit(data["news"])
    data["audit"].update({"feeds_ok": ok, "feeds_failed": bad, "notes": LOG[:6]})
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({"date": NOW.strftime("%Y-%m-%d"), "audit": data["audit"],
                            "picks": {k: [{"t": p["title"], "src": p["source"], "n": p["outlets"], "lean": p.get("lean"),
                                           "sites": p.get("sites"), "wiki": p.get("wiki")} for p in v]
                                      for k, v in data["news"].items()}}, ensure_ascii=False) + "\n")
    print("wrote", OUT, data["audit"])


def selftest():
    """Offline check of clustering + spectrum logic on made-up headlines."""
    def mk(src, title, rank=0):
        return {"title": title, "url": "x", "source": src, "dt": NOW - timedelta(hours=3), "rank": rank}
    items = [
        mk("The Hindu", "RBI keeps repo rate unchanged at 5.5 percent", 0),
        mk("Indian Express", "RBI holds repo rate steady, signals cautious stance on inflation", 1),
        mk("India Today", "RBI policy: repo rate unchanged, governor flags inflation risks", 0),
        mk("Times of India", "Repo rate unchanged: RBI governor says inflation outlook benign", 2),
        mk("The Hindu", "Heavy rain lashes Chennai, schools shut", 3),
        mk("Indian Express", "Chennai rains: schools closed, waterlogging in several areas", 4),
        mk("NDTV", "Chennai rain: schools shut as waterlogging hits traffic", 2),
        mk("India Today", "Celebrity couple announces engagement photos", 1),
        mk("ThePrint", "Supreme Court to hear plea on electoral bonds records", 3),
        mk("India Today", "Supreme Court to hear electoral bonds plea next week", 5),
        mk("Hindustan Times", "Live updates: Stock market today Sensex Nifty", 0),
    ]
    GDELT_OK["on"] = False
    for p in rank_section(items, 4):
        print(p["outlets"], p["lean"] or "-", p["title"])


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
