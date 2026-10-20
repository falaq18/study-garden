"""Fetch the newest links for the study garden and write links.json.

Runs every morning from .github/workflows/daily-links.yml with the Python
standard library only.

How news is picked (no AI, but not random either):
  1. Read ~15 editor-curated "top stories" feeds from respected outlets.
  2. Group headlines that are about the same story across outlets.
  3. Score each story: how many outlets cover it (the big signal), how high
     editors placed it in their own feed, how fresh it is, and whether it is
     about policy, economy, courts, elections or diplomacy. Live blogs, photo
     galleries, horoscopes, celebrity and sports results are pushed down.
  4. Keep the top 3 distinct stories per section.
If a feed fails, the others carry on; if a whole section fails, yesterday's
picks are kept, so the site never goes blank.
"""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "links.json"
UA = {"User-Agent": "Mozilla/5.0 (study-garden link fetcher; +https://github.com)"}
NOW = datetime.now(timezone.utc)

NEWS = {
    "india": [
        ("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
        ("Indian Express", "https://indianexpress.com/section/india/feed/"),
        ("Hindustan Times", "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml"),
        ("NDTV", "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("Mint Politics", "https://www.livemint.com/rss/politics"),
        ("BBC India", "https://feeds.bbci.co.uk/news/world/asia/india/rss.xml"),
    ],
    "world": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml"),
        ("DW", "https://rss.dw.com/rdf/rss-en-world"),
        ("The Hindu World", "https://www.thehindu.com/news/international/feeder/default.rss"),
    ],
    "business": [
        ("Mint", "https://www.livemint.com/rss/markets"),
        ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms"),
        ("Business Standard", "https://www.business-standard.com/rss/home_page_top_stories.rss"),
        ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
        ("The Guardian Business", "https://www.theguardian.com/business/rss"),
        ("The Hindu Business", "https://www.thehindu.com/business/feeder/default.rss"),
    ],
}
EXPLAINER = ("Indian Express Explained", "https://indianexpress.com/section/explained/feed/")

# Course feeds: plain RSS URLs, or "yt:@handle" for a YouTube channel.
COURSES = {
    "FIN": [("CA Rachana Ranade", "yt:@CARachanaRanade"), ("Mint Money", "https://www.livemint.com/rss/money")],
    "PRD": [("Lenny's Newsletter", "https://www.lennysnewsletter.com/feed"), ("Exponent", "yt:@tryexponent")],
    "AI": [("One Useful Thing", "https://www.oneusefulthing.org/feed"), ("3Blue1Brown", "yt:@3blue1brown"),
           ("Andrej Karpathy", "yt:@AndrejKarpathy")],
    "HIS": [("ThePrint · Cut the Clutter", "yt:@ThePrintIndia"), ("Caspian Report", "yt:@CaspianReport")],
    "FINAL": [("Vinh Giang", "yt:@vinhgiang"), ("One Useful Thing", "https://www.oneusefulthing.org/feed")],
}

STOP = set("""a an the and or but of to in on for with at by from as is are was were be been being it its this that these those
into over after before about against between under amid than then so not no yes new news says said say will would can could
may might has have had do does did up down out off more most less least very just also how why what who whom which when where
amid via vs his her their our your my he she they we you i us them him one two three four five six seven eight nine ten
first last year years day days week today tomorrow yesterday report reports update updates latest live""".split())
BOOST = set("""rbi budget gdp inflation rate rates repo tariff tariffs trade deal deals election elections poll polls vote
parliament lok sabha rajya bill law court supreme verdict judge ceasefire war attack strike sanctions summit treaty talks minister
president pm government policy reform tax gst fed ecb imf economy economic market markets sensex nifty rupee dollar oil crude
climate flood floods earthquake cyclone protest protests ban security military nuclear china pakistan russia ukraine israel gaza
iran us eu un""".split())
DROP = re.compile(r"\b(live|liveblog|photos?|in pics|gallery|horoscope|quiz|watch:|video:|recipe|celebrit|bollywood|ipl|"
                  r"cricket score|match report|highlights|wordle|crossword|deal of the day|sale|lottery)\b", re.I)


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
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


def same_story(a, b):
    shared = a & b
    return len(shared) >= 3 or (len(shared) >= 2 and len(shared) / max(1, min(len(a), len(b))) >= 0.5)


def rank_section(items, n=3):
    for it in items:
        it["w"] = words(it["title"])
    # cluster headlines about the same story
    clusters = []
    for it in items:
        for c in clusters:
            if any(same_story(it["w"], o["w"]) for o in c):
                c.append(it)
                break
        else:
            clusters.append([it])
    scored = []
    for c in clusters:
        outlets = {i["source"] for i in c}
        best = min(c, key=lambda i: (i["rank"], -(i["dt"] or NOW).timestamp()))
        score = 4.0 * (len(outlets) - 1)                       # covered by several outlets
        score += max(0, 3 - best["rank"]) * 0.8                # placed near the top by editors
        newest = max((i["dt"] for i in c if i["dt"]), default=None)
        if newest:
            age = (NOW - newest).total_seconds() / 3600
            score += 2.0 if age < 12 else 1.0 if age < 24 else -3.0 if age > 48 else 0
        allw = set().union(*(i["w"] for i in c))
        score += 0.7 * min(4, len(allw & BOOST))               # policy, economy, courts, diplomacy
        if DROP.search(best["title"]):
            score -= 6
        scored.append((score, best, sorted(outlets)))
    scored.sort(key=lambda x: -x[0])
    picks = []
    for score, best, outlets in scored[:n]:
        picks.append({
            "title": best["title"], "url": best["url"], "source": best["source"],
            "date": best["dt"].strftime("%-d %b") if best["dt"] else "",
            "outlets": len(outlets), "also": [o for o in outlets if o != best["source"]][:3],
        })
    return picks


def collect(sources, per_source):
    out = []
    for name, url in sources:
        try:
            out += parse(name, url, per_source)
        except Exception as e:  # keep going if one feed is down
            print(f"skip {name}: {e}")
    return out


def plain(items, total):
    return [{"title": i["title"], "url": i["url"], "source": i["source"],
             "date": i["dt"].strftime("%-d %b") if i["dt"] else ""} for i in items][:total]


def main():
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
        except Exception:
            old = {}
    data = {"updated": NOW.isoformat(timespec="minutes"), "method": "ranked", "news": {}, "explainer": [], "courses": {}}
    for k, sources in NEWS.items():
        items = collect(sources, 15)
        data["news"][k] = rank_section(items) if items else old.get("news", {}).get(k, [])
        print(k, len(items), "headlines ->", [p["outlets"] for p in data["news"][k]])
    ex = collect([EXPLAINER], 2)
    data["explainer"] = plain(ex, 1) or old.get("explainer", [])
    for k, sources in COURSES.items():
        items = collect(sources, 2)
        data["courses"][k] = plain(items, 4) or old.get("courses", {}).get(k, [])
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
