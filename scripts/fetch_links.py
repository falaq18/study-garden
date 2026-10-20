"""Fetch the newest links for the study garden and write links.json.

Runs every morning from .github/workflows/daily-links.yml. Uses only the
Python standard library. If a feed fails, the previous items for that slot
are kept, so the site never goes blank.
"""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "links.json"
UA = {"User-Agent": "Mozilla/5.0 (study-garden link fetcher; +https://github.com)"}

NEWS = {
    "india": [("Indian Express Explained", "https://indianexpress.com/section/explained/feed/"),
              ("The Hindu · National", "https://www.thehindu.com/news/national/feeder/default.rss")],
    "world": [("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
              ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml")],
    "business": [("Mint", "https://www.livemint.com/rss/news"),
                 ("Mint Markets", "https://www.livemint.com/rss/markets")],
}

# Course feeds: plain RSS URLs, or "yt:@handle" for a YouTube channel.
COURSES = {
    "FIN": [("CA Rachana Ranade", "yt:@CARachanaRanade"), ("Mint Money", "https://www.livemint.com/rss/money")],
    "PRD": [("Lenny's Newsletter", "https://www.lennysnewsletter.com/feed"), ("Exponent", "yt:@tryexponent")],
    "AI": [("One Useful Thing", "https://www.oneusefulthing.org/feed"), ("3Blue1Brown", "yt:@3blue1brown"),
           ("Andrej Karpathy", "yt:@AndrejKarpathy")],
    "HIS": [("ThePrint · Cut the Clutter", "yt:@ThePrintIndia"), ("Caspian Report", "yt:@CaspianReport")],
    "FINAL": [("Vinh Giang", "yt:@vinhgiang"), ("One Useful Thing", "https://www.oneusefulthing.org/feed")],
}


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


def nice_date(text):
    if not text:
        return ""
    try:
        d = parsedate_to_datetime(text)
    except Exception:
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return ""
    return d.strftime("%-d %b")


def parse(source, url, limit=3):
    if url.startswith("yt:"):
        url = youtube_feed(url[3:])
    root = ET.fromstring(get(url))
    items = []
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = date = ""
        for ch in node:
            t = ch.tag.split("}")[-1]
            if t == "title":
                title = (ch.text or "").strip()
            elif t == "link":
                link = ch.get("href") or (ch.text or "").strip() or link
            elif t in ("pubDate", "published", "updated") and not date:
                date = nice_date((ch.text or "").strip())
        if title and link:
            items.append({"title": title, "url": link, "source": source, "date": date})
        if len(items) >= limit:
            break
    return items


def collect(sources, per_source, total):
    out = []
    for name, url in sources:
        try:
            out += parse(name, url, per_source)
        except Exception as e:  # keep going if one feed is down
            print(f"skip {name}: {e}")
    return out[:total]


def main():
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
        except Exception:
            old = {}
    data = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "news": {}, "courses": {}}
    for k, sources in NEWS.items():
        items = collect(sources, 3, 3)
        data["news"][k] = items or old.get("news", {}).get(k, [])
    for k, sources in COURSES.items():
        items = collect(sources, 2, 4)
        data["courses"][k] = items or old.get("courses", {}).get(k, [])
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
